"""/newsflash [deckblatt] [artikelbild]: öffnet ein Formular (Zeitungsname, Schlagzeile, Verfasser optional, Inhalt) und veröffentlicht die
Meldung als Zeitungsartikel im News-Kanal: Zeitungskopf mit Datum (automatisch, deutsche Zeit) und optionalem Deckblatt-Bild,
darunter der Artikel mit Schlagzeile und Verfasserzeile. Die Bilder (Deckblatt, Artikelbild) kommen als Anhänge des Befehls (Modals können keine Dateien).

- Landesherren (und Administratoren) veröffentlichen sofort.
- Staatsbürger ohne Landesherr-Rolle brauchen für JEDE Meldung eine Genehmigung (seit 11.11.2026; keine dauerhafte Freischaltung mehr, die
  Tabelle freigeschaltet wird nicht mehr ausgewertet): Die Meldung geht in den Kanal NEWSFLASH_PRUEFUNG, bis zu 3 unentschiedene je Person.
- Enthält Zeitungsname, Schlagzeile oder Inhalt eine Wendung aus newsflash_filter.txt, wird die Meldung (auch von Landesherren)
  nicht sofort veröffentlicht, sondern mit „Veröffentlichen“/„Ablehnen“ in den Prüfkanal geschickt.
Jeder Artikel kostet 12 Kr (Einstellung „gebuehren“ → „zeitungsartikel“ im Imperium-Dienst, Privatkonto → Reichskasse; bei Ablehnung erstattet).
Der Verfasser bekommt zu jeder Entscheidung eine DM. Meldungen liegen in newsflash.db (Betriebsdaten, nicht im Repo).
"""
import io
import logging
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

import amt_api
import config

log = logging.getLogger("imperium-bot.newsflash")
HIER = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HIER, "newsflash.db")
FILTER_DATEI = os.path.join(HIER, "newsflash_filter.txt")
PREFIX = "newsflash:"
MAX_OFFEN = 3   # höchstens so viele unentschiedene Meldungen je Staatsbürger
BILDER = os.path.join(HIER, "newsflash_bilder")   # Deckblätter wartender Meldungen (Betriebsdaten, nicht im Repo)
BILD_TYPEN = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
BILD_MAX = 8 * 1024 * 1024
TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
FARBE_NEWS, FARBE_PRUEFUNG, FARBE_OK, FARBE_NEIN = 0x2E4A7D, 0xE0A030, 0x2F6B3A, 0xA3261B


def normalisieren(text: str) -> str:
    """Kleinschreibung ohne Akzente, ä/ö/ü/ß als ae/oe/ue/ss; alles außer a–z und Ziffern wird zum Trenner."""
    text = unicodedata.normalize("NFKD", text.casefold().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def filter_treffer(*texte: str) -> list[str]:
    """Wendungen aus der Filterdatei, die im Text vorkommen: am Wortanfang, mit Endungen („Volksfeinde“) und mit
    einzelnen Trennzeichen mitten im Wort („Volks-Feind“, „V o l k s f e i n d“); mitten in anderen Wörtern nicht."""
    try:
        with open(FILTER_DATEI, encoding="utf-8") as fh:
            begriffe = [z.strip() for z in fh if z.strip() and not z.lstrip().startswith("#")]
    except FileNotFoundError:
        log.warning("Filterdatei %s fehlt", FILTER_DATEI)
        return []
    heu = normalisieren(" ".join(texte))
    treffer = []
    for b in begriffe:
        woerter = normalisieren(b).split()
        if woerter and re.search(r"(?<![a-z0-9])" + r"[^a-z0-9]{1,2}".join(
                "[^a-z0-9]?".join(re.escape(c) for c in w) for w in woerter), heu):
            treffer.append(b)
    return treffer


def datenbank():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS freigeschaltet (user_id INTEGER PRIMARY KEY, von_id INTEGER NOT NULL, zeit INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS meldungen (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, zeitung TEXT NOT NULL, schlagzeile TEXT NOT NULL,
            inhalt TEXT NOT NULL, status TEXT NOT NULL, grund TEXT NOT NULL DEFAULT '', treffer TEXT NOT NULL DEFAULT '',
            zeit INTEGER NOT NULL, nachricht_id INTEGER);""")
    for spalte, typ in (("verfasser", "TEXT"), ("bild", "TEXT"), ("artikelbild", "TEXT"), ("gebuehr", "INTEGER")):   # später ergänzt (gebuehr = abgebuchte Gebühr in Heller)
        try:
            con.execute(f"ALTER TABLE meldungen ADD COLUMN {spalte} {typ} NOT NULL DEFAULT {0 if typ == 'INTEGER' else repr('')}")
        except sqlite3.OperationalError:
            pass
    return con


def datum_heute() -> str:
    d = datetime.now(ZoneInfo("Europe/Berlin"))
    return f"{TAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"


def zeitung_embeds(zeitung, schlagzeile, inhalt, verfasser="", bild=None, artikelbild=None) -> list[discord.Embed]:
    """Zeitungsartikel: Kopf (Zeitungsname, Datum, Deckblatt) und Artikel (Schlagzeile, Verfasser, Text, Artikelbild)."""
    kopf = discord.Embed(description=f"# {zeitung}\n*{datum_heute()}*", color=FARBE_NEWS)
    if bild:
        kopf.set_image(url=f"attachment://{bild}")
    artikel = discord.Embed(title=schlagzeile[:256], description=(f"**Von {verfasser}**\n\n" if verfasser else "") + inhalt, color=FARBE_NEWS)
    if artikelbild:
        artikel.set_image(url=f"attachment://{artikelbild}")
    artikel.set_footer(text=f"{zeitung} · Newsflash")
    return [kopf, artikel]


async def bild_lesen(anhang: discord.Attachment | None):
    """(Bytes, Dateiendung) des Anhangs oder (None, None)."""
    if anhang is None:
        return None, None
    return await anhang.read(), BILD_TYPEN[(anhang.content_type or "").split(";")[0]]


def bild_ungueltig(anhang: discord.Attachment | None) -> bool:
    return anhang is not None and ((anhang.content_type or "").split(";")[0] not in BILD_TYPEN or anhang.size > BILD_MAX)


def bilddateien(deckblatt, artikelbild) -> list[discord.File]:
    """Anhänge der Nachricht; Eingabe je (Bytes, Endung) oder (None, None)."""
    return [discord.File(io.BytesIO(b), filename=f"{name}.{e}") for name, (b, e) in (("deckblatt", deckblatt), ("artikelbild", artikelbild)) if b]


def bildnamen(deckblatt, artikelbild):
    return tuple(f"{name}.{e}" if b else None for name, (b, e) in (("deckblatt", deckblatt), ("artikelbild", artikelbild)))


def pruef_view(meldung_id: int, freischalten: bool) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Freischalten und veröffentlichen" if freischalten else "Veröffentlichen",
                                 style=discord.ButtonStyle.success, custom_id=f"{PREFIX}ja:{meldung_id}"))
    v.add_item(discord.ui.Button(label="Ablehnen", style=discord.ButtonStyle.danger, custom_id=f"{PREFIX}nein:{meldung_id}"))
    return v


def kr(heller: int) -> str:
    m, p = divmod(int(heller), 100)
    return f"{m:,}".replace(",", ".") + (f",{p:02d}" if p else "") + " Kr"


class NewsflashModal(discord.ui.Modal, title="Newsflash"):
    zeitung = discord.ui.TextInput(label="Zeitungsname", min_length=2, max_length=80)
    schlagzeile = discord.ui.TextInput(label="Schlagzeile", min_length=3, max_length=200)
    verfasser = discord.ui.TextInput(label="Verfasser (optional)", required=False, max_length=80)
    inhalt = discord.ui.TextInput(label="Inhalt des Artikels", style=discord.TextStyle.paragraph, min_length=10, max_length=3500)

    def __init__(self, cog: "Newsflash", deckblatt: discord.Attachment | None, artikelbild: discord.Attachment | None, gebuehr: int = 0):
        super().__init__(title=f"Newsflash (Gebühr {kr(gebuehr)})" if gebuehr else "Newsflash")
        self.cog, self.deckblatt, self.artikelbild = cog, deckblatt, artikelbild

    async def on_submit(self, inter: discord.Interaction):
        await self.cog.einreichen(inter, self.zeitung.value, self.schlagzeile.value, self.inhalt.value, self.verfasser.value, self.deckblatt, self.artikelbild)

    async def on_error(self, inter: discord.Interaction, error: Exception):
        log.exception("Newsflash fehlgeschlagen", exc_info=error)
        msg = "Die Meldung konnte nicht verarbeitet werden. Bitte versuche es später noch einmal."
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)


class AblehnenModal(discord.ui.Modal, title="Meldung ablehnen"):
    begruendung = discord.ui.TextInput(label="Begründung (optional)", style=discord.TextStyle.paragraph, required=False, max_length=1000)

    def __init__(self, cog: "Newsflash", meldung_id: int, nachricht: discord.Message):
        super().__init__()
        self.cog, self.meldung_id, self.nachricht = cog, meldung_id, nachricht

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer()
        await self.cog.entscheiden(inter, self.meldung_id, self.nachricht, False, self.begruendung.value.strip())


class Newsflash(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = datenbank()

    async def cog_unload(self):
        self.db.close()

    # ---------------------------------------------------------------- Befehl

    @app_commands.command(name="newsflash", description="Einen Zeitungsartikel veröffentlichen")
    @app_commands.guild_only()
    @app_commands.describe(deckblatt="Optional: Bild für das Deckblatt (PNG, JPG, WEBP oder GIF, bis 8 MB)",
                           artikelbild="Optional: Bild zum Artikel (PNG, JPG, WEBP oder GIF, bis 8 MB)")
    async def newsflash(self, inter: discord.Interaction, deckblatt: discord.Attachment | None = None,
                        artikelbild: discord.Attachment | None = None):
        """Prüft die Berechtigung und öffnet das Formular (Zeitungsname, Schlagzeile, Verfasser, Inhalt)."""
        rollen = {r.id for r in inter.user.roles}
        if config.LANDESHERR_ROLLE not in rollen and config.STAATSBUERGER_ROLLE not in rollen and not inter.user.guild_permissions.administrator:
            await inter.response.send_message("Zeitungen können nur Staatsbürger und Landesherren veröffentlichen.", ephemeral=True)
            return
        if not self.freigeschaltet(inter.user) and self.offene_meldungen(inter.user) >= MAX_OFFEN:
            await inter.response.send_message(f"Du hast bereits {MAX_OFFEN} Meldungen, über die die Leitung noch nicht entschieden hat. Bitte warte auf die Entscheidung.", ephemeral=True)
            return
        if bild_ungueltig(deckblatt) or bild_ungueltig(artikelbild):
            await inter.response.send_message("Deckblatt und Artikelbild müssen Bilder sein (PNG, JPG, WEBP oder GIF) und dürfen höchstens 8 MB groß sein.", ephemeral=True)
            return
        pruef = await amt_api.gebuehr("pruefen", inter.user.id, "zeitungsartikel")
        if pruef is None:
            await inter.response.send_message("Die Gebührenabrechnung ist gerade nicht erreichbar. Bitte versuche es später erneut.", ephemeral=True)
            return
        if not pruef.get("ok"):
            await inter.response.send_message(f"Zeitungsartikel kosten {kr(pruef.get('betrag', 0))}. {pruef.get('fehler', '')}", ephemeral=True)
            return
        await inter.response.send_modal(NewsflashModal(self, deckblatt, artikelbild, pruef["betrag"]))

    def freigeschaltet(self, user: discord.Member) -> bool:
        """Darf ohne Genehmigung veröffentlichen: nur Landesherren und Administratoren. Staatsbürger brauchen für JEDE Meldung eine Genehmigung
        (die frühere dauerhafte Freischaltung, Tabelle freigeschaltet, gilt nicht mehr)."""
        return config.LANDESHERR_ROLLE in {r.id for r in user.roles} or user.guild_permissions.administrator

    def offene_meldungen(self, user) -> int:
        return self.db.execute("SELECT COUNT(*) FROM meldungen WHERE user_id = ? AND status = 'offen'", (user.id,)).fetchone()[0]

    async def kanal(self, kanal_id):
        return self.bot.get_channel(kanal_id) or await self.bot.fetch_channel(kanal_id)

    async def veroeffentlichen(self, zeitung, schlagzeile, inhalt, verfasser, deckblatt=(None, None), artikelbild=(None, None)) -> discord.Message:
        return await (await self.kanal(config.NEWS_KANAL)).send(
            embeds=zeitung_embeds(zeitung, schlagzeile, inhalt, verfasser, *bildnamen(deckblatt, artikelbild)),
            files=bilddateien(deckblatt, artikelbild), allowed_mentions=discord.AllowedMentions.none())

    async def einreichen(self, inter: discord.Interaction, zeitung: str, schlagzeile: str, inhalt: str, verfasser: str = "",
                         deckblatt_anhang: discord.Attachment | None = None, artikelbild_anhang: discord.Attachment | None = None):
        await inter.response.defer(ephemeral=True)
        zeitung, schlagzeile, inhalt, verfasser = zeitung.strip(), schlagzeile.strip(), inhalt.strip(), verfasser.strip()
        treffer = filter_treffer(zeitung, schlagzeile, inhalt, verfasser)
        deckblatt, artikelbild = await bild_lesen(deckblatt_anhang), await bild_lesen(artikelbild_anhang)

        gruende = []
        if not self.freigeschaltet(inter.user):
            if self.offene_meldungen(inter.user) >= MAX_OFFEN:
                await inter.followup.send(f"Du hast bereits {MAX_OFFEN} Meldungen, über die die Leitung noch nicht entschieden hat. Bitte warte auf die Entscheidung.", ephemeral=True)
                return
            gruende.append("genehmigung")
        if treffer:
            gruende.append("filter")

        # Gebühr abbuchen (bei Ablehnung wird sie erstattet); scheitert die Buchung, wird nichts veröffentlicht
        abbuchung = await amt_api.gebuehr("buchen", inter.user.id, "zeitungsartikel", f"„{schlagzeile[:80]}“", "NEWSFLASH")
        if abbuchung is None or not abbuchung.get("ok"):
            await inter.followup.send("Die Gebühr konnte nicht abgebucht werden: " + (abbuchung.get("fehler", "") if abbuchung else "Die Abrechnung ist gerade nicht erreichbar.")
                                      + " Dein Artikel wurde nicht eingereicht.", ephemeral=True)
            return
        gebuehr = int(abbuchung.get("betrag", 0))
        hinweis = f"\nGebühr: {kr(gebuehr)} abgebucht." if gebuehr else ""

        if not gruende:   # sofort veröffentlichen
            nachricht = await self.veroeffentlichen(zeitung, schlagzeile, inhalt, verfasser, deckblatt, artikelbild)
            self.db.execute("INSERT INTO meldungen (user_id, zeitung, schlagzeile, inhalt, verfasser, status, zeit, nachricht_id, gebuehr) VALUES (?, ?, ?, ?, ?, 'veroeffentlicht', ?, ?, ?)",
                            (inter.user.id, zeitung, schlagzeile, inhalt, verfasser, int(time.time()), nachricht.id, gebuehr))
            self.db.commit()
            await inter.followup.send(f"Dein Artikel wurde veröffentlicht: {nachricht.jump_url}{hinweis}", ephemeral=True)
            return

        # Prüfung durch die Leitung: Meldung (und Deckblatt) werden bis zur Entscheidung gespeichert
        cur = self.db.execute("INSERT INTO meldungen (user_id, zeitung, schlagzeile, inhalt, verfasser, status, grund, treffer, zeit, gebuehr) VALUES (?, ?, ?, ?, ?, 'offen', ?, ?, ?, ?)",
                              (inter.user.id, zeitung, schlagzeile, inhalt, verfasser, ",".join(gruende), ", ".join(treffer), int(time.time()), gebuehr))
        mid = cur.lastrowid
        dateien = {}
        for spalte, (daten, endung) in (("bild", deckblatt), ("artikelbild", artikelbild)):
            dateien[spalte] = ""
            if daten:
                os.makedirs(BILDER, exist_ok=True)
                dateien[spalte] = f"{mid}-{spalte}.{endung}"
                with open(os.path.join(BILDER, dateien[spalte]), "wb") as fh:
                    fh.write(daten)
        self.db.execute("UPDATE meldungen SET bild = ?, artikelbild = ? WHERE id = ?", (dateien["bild"], dateien["artikelbild"], mid))
        self.db.commit()

        warum = []
        if "genehmigung" in gruende:
            warum.append("**Genehmigung:** Die Person ist Staatsbürger ohne Landesherr-Rolle; jede Meldung von Staatsbürgern braucht eine Genehmigung der Leitung.")
        if "filter" in gruende:
            warum.append(f"**Filter:** Treffer bei {', '.join(f'„{t}“' for t in treffer)}.")
        pruef = discord.Embed(title=f"Meldung Nr. {mid} zur Prüfung", color=FARBE_PRUEFUNG,
                              description=f"Von {inter.user.mention} ({inter.user.id})\n" + "\n".join(warum) + "\n\nSo würde der Artikel erscheinen (Datum = Tag der Veröffentlichung):")
        nachricht = await (await self.kanal(config.NEWSFLASH_PRUEFUNG)).send(
            embeds=[pruef] + zeitung_embeds(zeitung, schlagzeile, inhalt, verfasser, *bildnamen(deckblatt, artikelbild)),
            files=bilddateien(deckblatt, artikelbild),
            view=pruef_view(mid, False), allowed_mentions=discord.AllowedMentions.none())
        self.db.execute("UPDATE meldungen SET nachricht_id = ? WHERE id = ?", (nachricht.id, mid))
        self.db.commit()
        if "genehmigung" in gruende:
            text = "Meldungen von Staatsbürgern brauchen eine Genehmigung. Dein Artikel liegt der Leitung zur Prüfung vor; du bekommst eine Nachricht, sobald entschieden wurde."
        else:
            text = "Dein Artikel wird vor der Veröffentlichung von der Leitung geprüft. Du bekommst eine Nachricht, sobald entschieden wurde."
        await inter.followup.send(text + hinweis + ("\nWird der Artikel abgelehnt, bekommst du die Gebühr erstattet." if gebuehr else ""), ephemeral=True)

    # ---------------------------------------------------------------- Prüfung

    @commands.Cog.listener()
    async def on_interaction(self, inter: discord.Interaction):
        cid = (inter.data or {}).get("custom_id", "")
        if inter.type != discord.InteractionType.component or not cid.startswith(PREFIX):
            return
        aktion, _, mid = cid[len(PREFIX):].partition(":")
        if not mid.isdigit():
            return
        if not inter.channel.permissions_for(inter.user).view_channel:
            await inter.response.send_message("Darüber entscheidet die Server- und RP-Leitung.", ephemeral=True)
            return
        if aktion == "nein":
            await inter.response.send_modal(AblehnenModal(self, int(mid), inter.message))
        else:
            await inter.response.defer()
            await self.entscheiden(inter, int(mid), inter.message, True)

    @staticmethod
    def gespeichertes_bild(datei: str):
        """(Bytes, Endung) eines für die Prüfung gespeicherten Bildes oder (None, None)."""
        if not datei:
            return None, None
        try:
            with open(os.path.join(BILDER, datei), "rb") as fh:
                return fh.read(), datei.rsplit(".", 1)[-1]
        except FileNotFoundError:
            log.warning("Bild %s fehlt", datei)
            return None, None

    async def entscheiden(self, inter: discord.Interaction, mid: int, nachricht: discord.Message, ja: bool, begruendung: str = ""):
        m = self.db.execute("SELECT * FROM meldungen WHERE id = ? AND status = 'offen'", (mid,)).fetchone()
        if not m:
            await inter.followup.send("Diese Meldung ist schon entschieden.", ephemeral=True)
            return
        embeds = nachricht.embeds
        embed = embeds[0]
        embed_hinweis = ""
        if ja:
            bilder = [self.gespeichertes_bild(m[spalte]) for spalte in ("bild", "artikelbild")]
            veroeffentlicht = await self.veroeffentlichen(m["zeitung"], m["schlagzeile"], m["inhalt"], m["verfasser"], *bilder)
            self.db.execute("UPDATE meldungen SET status = 'veroeffentlicht', nachricht_id = ? WHERE id = ?", (veroeffentlicht.id, mid))
            text = f"Deine Meldung **„{m['schlagzeile']}“** wurde veröffentlicht: {veroeffentlicht.jump_url}"
            stand, farbe = "✅ Veröffentlicht", FARBE_OK
        else:
            self.db.execute("UPDATE meldungen SET status = 'abgelehnt' WHERE id = ?", (mid,))
            text = f"Deine Meldung **„{m['schlagzeile']}“** wurde **abgelehnt**." + (f"\n> {begruendung}" if begruendung else "")
            if m["gebuehr"]:
                erst = await amt_api.gebuehr("erstatten", m["user_id"], "zeitungsartikel", f"„{m['schlagzeile'][:80]}“ abgelehnt", f"NEWSFLASH-{mid}", m["gebuehr"])
                if erst and erst.get("ok"):
                    text += f"\nDie Gebühr von {kr(m['gebuehr'])} wurde dir erstattet."
                else:
                    text += f"\nDie Gebühr von {kr(m['gebuehr'])} konnte nicht automatisch erstattet werden; wende dich an die Leitung."
                    embed_hinweis = f"⚠️ Erstattung von {kr(m['gebuehr'])} fehlgeschlagen – bitte manuell im Schatzamt-Portal erstatten."
            stand, farbe = "❌ Abgelehnt", FARBE_NEIN
        self.db.commit()
        embed.color = farbe
        embed.add_field(name="Entscheidung", value=f"{stand} von {inter.user.mention}", inline=False)
        if begruendung:
            embed.add_field(name="Begründung", value=begruendung, inline=False)
        if embed_hinweis:
            embed.add_field(name="Hinweis", value=embed_hinweis, inline=False)
        try:
            user = self.bot.get_user(m["user_id"]) or await self.bot.fetch_user(m["user_id"])
            await user.send(text)
        except discord.HTTPException:
            embed.add_field(name="Hinweis", value="Die Direktnachricht an den Verfasser konnte nicht zugestellt werden.", inline=False)
        for datei in (m["bild"], m["artikelbild"]):
            if datei:
                try:
                    os.remove(os.path.join(BILDER, datei))
                except FileNotFoundError:
                    pass
        await nachricht.edit(embeds=[embed] + embeds[1:], view=None)


async def setup(bot):
    await bot.add_cog(Newsflash(bot))
