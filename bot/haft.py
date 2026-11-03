"""Haft: /u-haft und /haft (Reichsgerichtshof), /krs-haft (Reichssicherheitsamt).

- /u-haft nutzer grund dauer: alle Rollen weg, dafür Häftling; nach Ablauf kommen die Rollen zurück.
- /haft nutzer grund rollen-nach-haft [dauer]: wie /u-haft, aber die Auszeichnungsrollen (alle Rollen bis einschließlich
  des Trenners HAFT_BEHALTEN_BIS) bleiben. Ohne Dauer gilt die Haft, bis die Rolle Häftling von Hand entfernt wird.
  „Rollen nach Haft: Nein“ gibt die Rollen am Ende nicht zurück.
- /krs-haft nutzer grund dauer: wie /u-haft, aber mit der Rolle KRS-Häftling.
Die Haftfälle liegen in haft.db (überstehen Neustarts), ein Hintergrundlauf beendet abgelaufene Haften. Entfernt jemand die
Haftrolle von Hand, gilt das als vorzeitige Entlassung. Jede Ausführung und jedes Ende steht als Log im Kanal HAFT_LOG.
"""
import json
import logging
import os
import re
import sqlite3
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

log = logging.getLogger("imperium-bot.haft")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "haft.db")

ARTEN = {
    "u-haft": ("Untersuchungshaft", config.HAFT_ROLLE, 0xE0A030),
    "haft": ("Haft", config.HAFT_ROLLE, 0xC0502A),
    "krs-haft": ("KRS-Haft", config.KRS_HAFT_ROLLE, 0xA3261B),
}
EINHEITEN = {"w": 604800, "wo": 604800, "woche": 604800, "wochen": 604800,
             "d": 86400, "t": 86400, "tag": 86400, "tage": 86400, "tagen": 86400,
             "h": 3600, "std": 3600, "stunde": 3600, "stunden": 3600,
             "m": 60, "min": 60, "minute": 60, "minuten": 60}
MAX_SEKUNDEN = 365 * 86400


def dauer_lesen(text: str):
    """„3d“, „12h“, „1d12h“, „2 Wochen“ → Sekunden, sonst None."""
    text = text.strip().lower()
    if not re.fullmatch(r"(?:\s*\d+\s*[a-zäöü]+)+\s*", text):
        return None
    gesamt = 0
    for zahl, einheit in re.findall(r"(\d+)\s*([a-zäöü]+)", text):
        if einheit not in EINHEITEN:
            return None
        gesamt += int(zahl) * EINHEITEN[einheit]
    return gesamt if 60 <= gesamt <= MAX_SEKUNDEN else None


def datenbank():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS haft (
        user_id INTEGER PRIMARY KEY, art TEXT NOT NULL, rollen TEXT NOT NULL, wiederherstellen INTEGER NOT NULL,
        ende INTEGER, grund TEXT NOT NULL, von_id INTEGER NOT NULL, beginn INTEGER NOT NULL)""")
    return con


def zuweisbar(guild: discord.Guild, rolle: discord.Role) -> bool:
    return not rolle.is_default() and not rolle.managed and rolle < guild.me.top_role


class Haft(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = datenbank()

    async def cog_load(self):
        self.ablauf.start()

    async def cog_unload(self):
        self.ablauf.cancel()
        self.db.close()

    # ---------------------------------------------------------------- Log

    async def log_senden(self, titel, farbe, felder, beschreibung=None):
        embed = discord.Embed(title=titel, color=farbe, description=beschreibung, timestamp=discord.utils.utcnow())
        for name, wert in felder:
            embed.add_field(name=name, value=str(wert)[:1024] or "–", inline=False)
        try:
            kanal = self.bot.get_channel(config.HAFT_LOG) or await self.bot.fetch_channel(config.HAFT_LOG)
            await kanal.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Haft-Log konnte nicht geschrieben werden")

    # ---------------------------------------------------------------- Befehlskern

    async def inhaftieren(self, inter: discord.Interaction, art: str, nutzer: discord.Member, grund: str,
                          dauer: str | None, wiederherstellen: bool, behalten_bis: int | None, pflicht_rolle: int):
        guild = inter.guild
        if not (inter.user.guild_permissions.administrator or any(r.id == pflicht_rolle for r in inter.user.roles)):
            await inter.response.send_message("Dafür fehlt dir die nötige Rolle.", ephemeral=True)
            return
        name, haft_id, farbe = ARTEN[art]
        sekunden = None
        if dauer is not None:
            sekunden = dauer_lesen(dauer)
            if sekunden is None:
                await inter.response.send_message("Die Dauer verstehe ich nicht. Beispiele: `3d`, `12h`, `1d12h`, `2 Wochen` (1 Minute bis 365 Tage).",
                                                  ephemeral=True)
                return
        if nutzer.bot or nutzer.id == inter.user.id:
            await inter.response.send_message("Diese Person kann nicht in Haft genommen werden.", ephemeral=True)
            return
        if not inter.user.guild_permissions.administrator and nutzer.top_role >= inter.user.top_role:
            await inter.response.send_message("Die Rolle der Person steht nicht unter deiner eigenen.", ephemeral=True)
            return
        if self.db.execute("SELECT 1 FROM haft WHERE user_id = ?", (nutzer.id,)).fetchone() or \
                any(r.id in (config.HAFT_ROLLE, config.KRS_HAFT_ROLLE) for r in nutzer.roles):
            await inter.response.send_message("Die Person befindet sich bereits in Haft.", ephemeral=True)
            return
        haft_rolle = guild.get_role(haft_id)
        if haft_rolle is None or not zuweisbar(guild, haft_rolle):
            await inter.response.send_message("Die Haftrolle ist nicht vergebbar (fehlt oder steht über dem Bot).", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)
        grenze = guild.get_role(behalten_bis).position if behalten_bis else None
        entfernen = [r for r in nutzer.roles if zuweisbar(guild, r) and (grenze is None or r.position > grenze)]
        behalten = [r for r in nutzer.roles if r not in entfernen and not r.is_default()]
        try:
            await nutzer.edit(roles=behalten + [haft_rolle], reason=f"{name} durch {inter.user}: {grund}")
        except discord.HTTPException as e:
            log.exception("Rollenänderung für %s fehlgeschlagen", nutzer)
            await inter.followup.send(f"Die Rollen konnten nicht geändert werden ({e.status}).", ephemeral=True)
            return
        jetzt = int(time.time())
        ende = jetzt + sekunden if sekunden else None
        self.db.execute("INSERT INTO haft VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (nutzer.id, art, json.dumps([r.id for r in entfernen]), int(wiederherstellen), ende, grund, inter.user.id, jetzt))
        self.db.commit()

        felder = [("Person", f"{nutzer.mention} ({nutzer.id})"), ("Durch", inter.user.mention), ("Grund", grund),
                  ("Dauer", f"bis <t:{ende}:F> (<t:{ende}:R>)" if ende else "unbefristet"),
                  ("Rollen nach Haft", "Ja, werden zurückgegeben" if wiederherstellen else "Nein"),
                  ("Entfernte Rollen", ", ".join(r.name for r in entfernen) or "keine")]
        await self.log_senden(f"{name} verhängt", farbe, felder)
        bis = f" bis <t:{ende}:F>" if ende else " (unbefristet)"
        await inter.followup.send(f"{nutzer.mention} ist in **{name}**{bis}. {len(entfernen)} Rollen wurden entfernt.", ephemeral=True)

    async def entlassen(self, guild: discord.Guild, fall: sqlite3.Row, grund_text: str, farbe: int = 0x2F6B3A, zusatz=()):
        """Beendet einen Haftfall: Haftrolle weg, Rollen zurück (wenn vorgesehen), Log."""
        self.db.execute("DELETE FROM haft WHERE user_id = ?", (fall["user_id"],))
        self.db.commit()
        name, haft_id, _ = ARTEN[fall["art"]]
        felder = [("Person", f"<@{fall['user_id']}> ({fall['user_id']})"), ("Grund der Haft", fall["grund"]), *zusatz]
        try:
            member = guild.get_member(fall["user_id"]) or await guild.fetch_member(fall["user_id"])
        except discord.NotFound:
            felder.append(("Hinweis", "Die Person ist nicht mehr auf dem Server; es wurden keine Rollen zurückgegeben."))
            await self.log_senden(f"{name} beendet ({grund_text})", farbe, felder)
            return
        zurueck = []
        if fall["wiederherstellen"]:
            zurueck = [r for r in (guild.get_role(i) for i in json.loads(fall["rollen"])) if r and zuweisbar(guild, r)]
        neu = [r for r in member.roles if r.id != haft_id and not r.is_default()]
        neu += [r for r in zurueck if r not in neu]
        try:
            await member.edit(roles=neu, reason=f"{name} beendet ({grund_text})")
            felder.append(("Rollen zurückgegeben", ", ".join(r.name for r in zurueck) if fall["wiederherstellen"] else "nein, laut Haftbeschluss nicht vorgesehen"))
        except discord.HTTPException as e:
            log.exception("Entlassung von %s fehlgeschlagen", member)
            felder.append(("Fehler", f"Die Rollen konnten nicht zurückgegeben werden ({e.status}). Bitte von Hand nachholen."))
            farbe = 0xA3261B
        await self.log_senden(f"{name} beendet ({grund_text})", farbe, felder)

    # ---------------------------------------------------------------- Ablauf

    @tasks.loop(seconds=30)
    async def ablauf(self):
        faelle = self.db.execute("SELECT * FROM haft WHERE ende IS NOT NULL AND ende <= ?", (int(time.time()),)).fetchall()
        guild = self.bot.get_guild(config.GUILD_ID)
        for fall in faelle:
            try:
                await self.entlassen(guild, fall, "Zeit abgelaufen")
            except Exception:
                log.exception("Beenden der Haft von %s fehlgeschlagen", fall["user_id"])

    @ablauf.before_loop
    async def _warten(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_update(self, vorher: discord.Member, nachher: discord.Member):
        """Haftrolle von Hand entfernt = vorzeitige Entlassung."""
        fall = self.db.execute("SELECT * FROM haft WHERE user_id = ?", (nachher.id,)).fetchone()
        if not fall:
            return
        haft_id = ARTEN[fall["art"]][1]
        if any(r.id == haft_id for r in vorher.roles) and not any(r.id == haft_id for r in nachher.roles):
            await self.entlassen(nachher.guild, fall, "Haftrolle von Hand entfernt")

    # ---------------------------------------------------------------- Befehle

    @app_commands.command(name="u-haft", description="Untersuchungshaft: alle Rollen weg, nach Ablauf kommen sie zurück")
    @app_commands.guild_only()
    @app_commands.describe(nutzer="Person in Untersuchungshaft", grund="Grund der Untersuchungshaft", dauer="z. B. 3d, 12h, 1d12h")
    async def u_haft(self, inter: discord.Interaction, nutzer: discord.Member, grund: str, dauer: str):
        await self.inhaftieren(inter, "u-haft", nutzer, grund, dauer, True, None, config.HAFT_BEFUGTE_ROLLE)

    @app_commands.command(name="haft", description="Haft: alle Rollen außer den Auszeichnungen werden entfernt")
    @app_commands.guild_only()
    @app_commands.describe(nutzer="Person in Haft", grund="Grund der Haft", rollen_nach_haft="Bekommt die Person ihre Rollen nach der Haft zurück?",
                           dauer="Optional, z. B. 3d, 12h, 1d12h – ohne Angabe unbefristet")
    @app_commands.rename(rollen_nach_haft="rollen-nach-haft")
    @app_commands.choices(rollen_nach_haft=[app_commands.Choice(name="Ja", value="ja"), app_commands.Choice(name="Nein", value="nein")])
    async def haft(self, inter: discord.Interaction, nutzer: discord.Member, grund: str, rollen_nach_haft: app_commands.Choice[str],
                   dauer: str | None = None):
        await self.inhaftieren(inter, "haft", nutzer, grund, dauer, rollen_nach_haft.value == "ja", config.HAFT_BEHALTEN_BIS, config.HAFT_BEFUGTE_ROLLE)

    @app_commands.command(name="krs-haft", description="KRS-Haft: alle Rollen weg, nach Ablauf kommen sie zurück")
    @app_commands.guild_only()
    @app_commands.describe(nutzer="Person in KRS-Haft", grund="Grund der KRS-Haft", dauer="z. B. 3d, 12h, 1d12h")
    async def krs_haft(self, inter: discord.Interaction, nutzer: discord.Member, grund: str, dauer: str):
        await self.inhaftieren(inter, "krs-haft", nutzer, grund, dauer, True, None, config.KRS_BEFUGTE_ROLLE)

    @app_commands.command(name="entlassen", description="Eine Person vorzeitig aus der Haft entlassen")
    @app_commands.guild_only()
    @app_commands.describe(nutzer="Person in Haft", grund="Optional: Grund der vorzeitigen Entlassung")
    async def entlassen_befehl(self, inter: discord.Interaction, nutzer: discord.Member, grund: str | None = None):
        fall = self.db.execute("SELECT * FROM haft WHERE user_id = ?", (nutzer.id,)).fetchone()
        if not fall:
            await inter.response.send_message("Diese Person ist nicht in Haft (oder die Haft wurde nicht über den Bot verhängt).", ephemeral=True)
            return
        pflicht = config.KRS_BEFUGTE_ROLLE if fall["art"] == "krs-haft" else config.HAFT_BEFUGTE_ROLLE
        if not (inter.user.guild_permissions.administrator or any(r.id == pflicht for r in inter.user.roles)):
            await inter.response.send_message("Diese Haft kann nur die zuständige Stelle beenden.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        zusatz = [("Entlassen durch", inter.user.mention)] + ([("Begründung", grund)] if grund else [])
        await self.entlassen(inter.guild, fall, "vorzeitig entlassen", zusatz=zusatz)
        await inter.followup.send(f"{nutzer.mention} wurde aus der Haft entlassen.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Haft(bot))
