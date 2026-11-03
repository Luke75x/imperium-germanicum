"""/newsflash: öffnet ein Formular (Zeitungsname, Schlagzeile, Inhalt) und veröffentlicht die Meldung im News-Kanal.

- Landesherren (und Administratoren) veröffentlichen sofort.
- Staatsbürger ohne Landesherr-Rolle müssen vorher freigeschaltet werden: Ihre erste Meldung geht als Antrag in den Kanal
  NEWSFLASH_PRUEFUNG; mit „Freischalten und veröffentlichen“ ist die Person dauerhaft freigeschaltet (Tabelle freigeschaltet).
- Enthält Zeitungsname, Schlagzeile oder Inhalt eine Wendung aus newsflash_filter.txt, wird die Meldung (auch von Landesherren)
  nicht sofort veröffentlicht, sondern mit „Veröffentlichen“/„Ablehnen“ in den Prüfkanal geschickt.
Der Verfasser bekommt zu jeder Entscheidung eine DM. Meldungen liegen in newsflash.db (Betriebsdaten, nicht im Repo).
"""
import logging
import os
import re
import sqlite3
import time
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("imperium-bot.newsflash")
HIER = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HIER, "newsflash.db")
FILTER_DATEI = os.path.join(HIER, "newsflash_filter.txt")
PREFIX = "newsflash:"
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
    return con


def news_embed(zeitung, schlagzeile, inhalt) -> discord.Embed:
    e = discord.Embed(title=schlagzeile[:256], description=inhalt, color=FARBE_NEWS, timestamp=discord.utils.utcnow())
    e.set_author(name=zeitung)
    e.set_footer(text="Newsflash")
    return e


def pruef_view(meldung_id: int, freischalten: bool) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Freischalten und veröffentlichen" if freischalten else "Veröffentlichen",
                                 style=discord.ButtonStyle.success, custom_id=f"{PREFIX}ja:{meldung_id}"))
    v.add_item(discord.ui.Button(label="Ablehnen", style=discord.ButtonStyle.danger, custom_id=f"{PREFIX}nein:{meldung_id}"))
    return v


class NewsflashModal(discord.ui.Modal, title="Newsflash"):
    zeitung = discord.ui.TextInput(label="Zeitungsname", min_length=2, max_length=80)
    schlagzeile = discord.ui.TextInput(label="Schlagzeile", min_length=3, max_length=200)
    inhalt = discord.ui.TextInput(label="Inhalt", style=discord.TextStyle.paragraph, min_length=10, max_length=3500)

    def __init__(self, cog: "Newsflash"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, inter: discord.Interaction):
        await self.cog.einreichen(inter, self.zeitung.value, self.schlagzeile.value, self.inhalt.value)

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

    @app_commands.command(name="newsflash", description="Eine Zeitungsmeldung veröffentlichen")
    @app_commands.guild_only()
    async def newsflash(self, inter: discord.Interaction):
        """Prüft die Berechtigung und öffnet das Formular (Zeitungsname, Schlagzeile, Inhalt)."""
        rollen = {r.id for r in inter.user.roles}
        if config.LANDESHERR_ROLLE not in rollen and config.STAATSBUERGER_ROLLE not in rollen and not inter.user.guild_permissions.administrator:
            await inter.response.send_message("Zeitungen können nur Staatsbürger und Landesherren veröffentlichen.", ephemeral=True)
            return
        if not self.freigeschaltet(inter.user) and self.db.execute(
                "SELECT 1 FROM meldungen WHERE user_id = ? AND status = 'offen' AND grund LIKE '%freischaltung%'", (inter.user.id,)).fetchone():
            await inter.response.send_message("Dein Antrag auf Freischaltung liegt der Leitung schon vor. Bitte warte auf die Entscheidung.", ephemeral=True)
            return
        await inter.response.send_modal(NewsflashModal(self))

    def freigeschaltet(self, user: discord.Member) -> bool:
        return (config.LANDESHERR_ROLLE in {r.id for r in user.roles} or user.guild_permissions.administrator
                or bool(self.db.execute("SELECT 1 FROM freigeschaltet WHERE user_id = ?", (user.id,)).fetchone()))

    async def einreichen(self, inter: discord.Interaction, zeitung: str, schlagzeile: str, inhalt: str):
        freigeschaltet = self.freigeschaltet(inter.user)
        zeitung, schlagzeile, inhalt = zeitung.strip(), schlagzeile.strip(), inhalt.strip()
        treffer = filter_treffer(zeitung, schlagzeile, inhalt)

        gruende = []
        if not freigeschaltet:
            if self.db.execute("SELECT 1 FROM meldungen WHERE user_id = ? AND status = 'offen' AND grund LIKE '%freischaltung%'", (inter.user.id,)).fetchone():
                await inter.response.send_message("Dein Antrag auf Freischaltung liegt der Leitung schon vor. Bitte warte auf die Entscheidung.", ephemeral=True)
                return
            gruende.append("freischaltung")
        if treffer:
            gruende.append("filter")

        if not gruende:   # sofort veröffentlichen
            await inter.response.defer(ephemeral=True)
            kanal = self.bot.get_channel(config.NEWS_KANAL) or await self.bot.fetch_channel(config.NEWS_KANAL)
            nachricht = await kanal.send(embed=news_embed(zeitung, schlagzeile, inhalt), allowed_mentions=discord.AllowedMentions.none())
            self.db.execute("INSERT INTO meldungen (user_id, zeitung, schlagzeile, inhalt, status, zeit, nachricht_id) VALUES (?, ?, ?, ?, 'veroeffentlicht', ?, ?)",
                            (inter.user.id, zeitung, schlagzeile, inhalt, int(time.time()), nachricht.id))
            self.db.commit()
            await inter.followup.send(f"Deine Meldung wurde veröffentlicht: {nachricht.jump_url}", ephemeral=True)
            return

        # Prüfung durch die Leitung
        await inter.response.defer(ephemeral=True)
        cur = self.db.execute("INSERT INTO meldungen (user_id, zeitung, schlagzeile, inhalt, status, grund, treffer, zeit) VALUES (?, ?, ?, ?, 'offen', ?, ?, ?)",
                              (inter.user.id, zeitung, schlagzeile, inhalt, ",".join(gruende), ", ".join(treffer), int(time.time())))
        self.db.commit()
        mid = cur.lastrowid
        embed = news_embed(zeitung, schlagzeile, inhalt)
        embed.color = FARBE_PRUEFUNG
        embed.set_footer(text=f"Meldung Nr. {mid}")
        warum = []
        if "freischaltung" in gruende:
            warum.append("**Freischaltung:** Die Person ist Staatsbürger ohne Landesherr-Rolle und noch nicht freigeschaltet. "
                         "Mit „Freischalten und veröffentlichen“ darf sie künftig ohne Prüfung veröffentlichen.")
        if "filter" in gruende:
            warum.append(f"**Filter:** Treffer bei {', '.join(f'„{t}“' for t in treffer)}.")
        embed.add_field(name="Zur Prüfung", value=f"Von {inter.user.mention} ({inter.user.id})\n" + "\n".join(warum), inline=False)
        kanal = self.bot.get_channel(config.NEWSFLASH_PRUEFUNG) or await self.bot.fetch_channel(config.NEWSFLASH_PRUEFUNG)
        pruef = await kanal.send(embed=embed, view=pruef_view(mid, "freischaltung" in gruende), allowed_mentions=discord.AllowedMentions.none())
        self.db.execute("UPDATE meldungen SET nachricht_id = ? WHERE id = ?", (pruef.id, mid))
        self.db.commit()
        if "freischaltung" in gruende:
            text = "Du bist noch nicht als Zeitung freigeschaltet. Deine Meldung liegt der Leitung als Antrag vor; du bekommst eine Nachricht, sobald entschieden wurde."
        else:
            text = "Deine Meldung wird vor der Veröffentlichung von der Leitung geprüft. Du bekommst eine Nachricht, sobald entschieden wurde."
        await inter.followup.send(text, ephemeral=True)

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

    async def entscheiden(self, inter: discord.Interaction, mid: int, nachricht: discord.Message, ja: bool, begruendung: str = ""):
        m = self.db.execute("SELECT * FROM meldungen WHERE id = ? AND status = 'offen'", (mid,)).fetchone()
        if not m:
            await inter.followup.send("Diese Meldung ist schon entschieden.", ephemeral=True)
            return
        embed = nachricht.embeds[0]
        if ja:
            kanal = self.bot.get_channel(config.NEWS_KANAL) or await self.bot.fetch_channel(config.NEWS_KANAL)
            veroeffentlicht = await kanal.send(embed=news_embed(m["zeitung"], m["schlagzeile"], m["inhalt"]), allowed_mentions=discord.AllowedMentions.none())
            self.db.execute("UPDATE meldungen SET status = 'veroeffentlicht', nachricht_id = ? WHERE id = ?", (veroeffentlicht.id, mid))
            freigeschaltet = "freischaltung" in m["grund"]
            if freigeschaltet:
                self.db.execute("INSERT OR IGNORE INTO freigeschaltet VALUES (?, ?, ?)", (m["user_id"], inter.user.id, int(time.time())))
            text = (f"Deine Meldung **„{m['schlagzeile']}“** wurde veröffentlicht: {veroeffentlicht.jump_url}"
                    + ("\nDu bist außerdem als Zeitung freigeschaltet und kannst künftig ohne Antrag veröffentlichen." if freigeschaltet else ""))
            stand, farbe = "✅ Veröffentlicht" + (" und freigeschaltet" if freigeschaltet else ""), FARBE_OK
        else:
            self.db.execute("UPDATE meldungen SET status = 'abgelehnt' WHERE id = ?", (mid,))
            text = f"Deine Meldung **„{m['schlagzeile']}“** wurde **abgelehnt**." + (f"\n> {begruendung}" if begruendung else "")
            stand, farbe = "❌ Abgelehnt", FARBE_NEIN
        self.db.commit()
        embed.color = farbe
        embed.add_field(name="Entscheidung", value=f"{stand} von {inter.user.mention}", inline=False)
        if begruendung:
            embed.add_field(name="Begründung", value=begruendung, inline=False)
        try:
            user = self.bot.get_user(m["user_id"]) or await self.bot.fetch_user(m["user_id"])
            await user.send(text)
        except discord.HTTPException:
            embed.add_field(name="Hinweis", value="Die Direktnachricht an den Verfasser konnte nicht zugestellt werden.", inline=False)
        await nachricht.edit(embed=embed, view=None)


async def setup(bot):
    await bot.add_cog(Newsflash(bot))
