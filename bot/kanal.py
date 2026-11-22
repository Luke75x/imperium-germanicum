"""Eigene Sprachkanäle: Wer den Warteraum (Sprachkanal „» Eigener Kanal“) betritt, bekommt vom Bot eine DM mit der Frage nach
Name, Personenbegrenzung und Zugriff (für alle oder nur der eigene Teilstaat). Danach wird ein temporärer Sprachkanal in
derselben Kategorie erstellt und die Person hineinverschoben. Leere temporäre Kanäle werden automatisch gelöscht.
Die Knöpfe sind persistent (feste custom_id). Die erstellten Kanäle merkt sich der Bot in kanaele.json (Betriebsdaten).
"""
import json
import logging
import os
import re
import sqlite3
import time

import discord
from discord.ext import commands, tasks

import config

log = logging.getLogger("imperium-bot.kanal")

DATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kanaele.json")
NACHRANGIG = {"1522705410069631017"}   # Heiliger Stuhl zählt nur, wenn keine andere Fraktionsrolle da ist (wie in der Reichskarte)
FRIST = 600                              # so lange (Sekunden) darf ein neu erstellter Kanal leer sein, bevor er gelöscht wird


def laden() -> dict:
    try:
        with open(DATEI, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def speichern(d: dict):
    with open(DATEI, "w", encoding="utf-8") as fh:
        json.dump(d, fh)


def teilstaat_rollen(member: discord.Member) -> list[discord.Role]:
    """Fraktionsrollen (= Teilstaat) der Person laut aktuellem Stand der Reichskarte."""
    try:
        con = sqlite3.connect(f"file:{config.DIENST_DB}?mode=ro", uri=True)
        try:
            zeile = con.execute("SELECT stand FROM karte_versionen ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            con.close()
        ids = {s["fraktion"] for s in json.loads(zeile[0]).get("staaten", []) if s.get("fraktion")}
    except Exception:
        log.exception("Teilstaaten konnten nicht gelesen werden")
        return []
    eigene = {str(r.id): r for r in member.roles if str(r.id) in ids}
    wirksam = set(eigene) - NACHRANGIG or set(eigene)
    return [eigene[i] for i in wirksam]


class KanalModal(discord.ui.Modal, title="Eigener Sprachkanal"):
    name = discord.ui.TextInput(label="Name des Kanals", min_length=2, max_length=60)
    limit = discord.ui.TextInput(label="Personenbegrenzung (0 = unbegrenzt)", default="0", max_length=2)

    def __init__(self, nur_teilstaat: bool):
        super().__init__()
        self.nur_teilstaat = nur_teilstaat

    async def on_submit(self, inter: discord.Interaction):
        guild = inter.client.get_guild(config.GUILD_ID)
        member = guild.get_member(inter.user.id) or await guild.fetch_member(inter.user.id)
        if not self.limit.value.strip().isdigit():
            await inter.response.send_message("Die Personenbegrenzung muss eine Zahl von 0 bis 99 sein.", ephemeral=True)
            return
        limit = int(self.limit.value)
        name = re.sub(r"\s+", " ", self.name.value).strip()[:60]
        warte = guild.get_channel(config.EIGENER_KANAL_WARTERAUM)
        if member.voice is None or member.voice.channel is None or member.voice.channel.id != warte.id:
            await inter.response.send_message("Du musst dafür im Warteraum sein. Betritt ihn erneut, dann fragt dich der Bot noch einmal.", ephemeral=True)
            return
        ueberschreibungen = {guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True),
                             member: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True, mute_members=True)}
        zusatz = ""
        if self.nur_teilstaat:
            rollen = teilstaat_rollen(member)
            if not rollen:
                await inter.response.send_message("Du gehörst keinem Teilstaat an. Wähle „Für alle“.", ephemeral=True)
                return
            ueberschreibungen[guild.default_role] = discord.PermissionOverwrite(view_channel=False, connect=False)
            for r in rollen:
                ueberschreibungen[r] = discord.PermissionOverwrite(view_channel=True, connect=True)
            zusatz = f" Zugriff haben nur Mitglieder von {', '.join(r.name for r in rollen)}."
        await inter.response.defer(ephemeral=True)
        try:
            kanal = await guild.create_voice_channel(f"🔊｜{name}", category=warte.category, user_limit=limit, overwrites=ueberschreibungen,
                                                     reason=f"Eigener Kanal von {member}")
            await member.move_to(kanal, reason="Eigener Kanal")
        except discord.Forbidden:
            await inter.followup.send("Dem Bot fehlen die Rechte (Kanäle verwalten / Mitglieder verschieben).", ephemeral=True)
            return
        d = laden()
        d[str(kanal.id)] = {"besitzer": member.id, "erstellt": int(time.time())}
        speichern(d)
        await inter.followup.send(f"✓ Dein Kanal {kanal.mention} wurde erstellt.{zusatz}", ephemeral=True)


class KanalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Für alle", style=discord.ButtonStyle.primary, custom_id="kanal:alle")
    async def alle(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.send_modal(KanalModal(False))

    @discord.ui.button(label="Nur mein Teilstaat", style=discord.ButtonStyle.secondary, custom_id="kanal:teilstaat")
    async def teilstaat(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.send_modal(KanalModal(True))

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.danger, custom_id="kanal:abbrechen")
    async def abbrechen(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.edit_message(content=f"{inter.message.content}\n\n✗ Abgebrochen.", view=None)


class EigenerKanal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(KanalView())
        self.aufraeumen.start()

    async def cog_unload(self):
        self.aufraeumen.cancel()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        if after.channel is not None and after.channel.id == config.EIGENER_KANAL_WARTERAUM and (before.channel is None or before.channel.id != after.channel.id):
            try:
                await member.send("**Eigenen Sprachkanal erstellen?**\nWähle, wer deinen Kanal betreten darf, und gib dann Name und "
                                  "Personenbegrenzung an. Dein Kanal wird erstellt und du wirst direkt hineinverschoben.\n\n"
                                  "Bleibe dafür im Warteraum, bis dein Kanal fertig ist.", view=KanalView())
            except discord.Forbidden:
                log.info("DM an %s nicht möglich", member)
        if before.channel is not None and before.channel != after.channel:
            await self._leer_loeschen(before.channel)

    async def _leer_loeschen(self, kanal):
        d = laden()
        if str(kanal.id) in d and not kanal.members:
            try:
                await kanal.delete(reason="Eigener Kanal leer")
            except discord.NotFound:
                pass
            d.pop(str(kanal.id), None)
            speichern(d)

    @tasks.loop(minutes=2)
    async def aufraeumen(self):
        """Fängt leere Kanäle ab, die z. B. während eines Neustarts leer wurden oder nie betreten wurden."""
        d = laden()
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            return
        for kid, info in list(d.items()):
            kanal = guild.get_channel(int(kid))
            if kanal is None:
                d.pop(kid)
            elif not kanal.members and time.time() - info["erstellt"] > FRIST:
                try:
                    await kanal.delete(reason="Eigener Kanal leer")
                except discord.NotFound:
                    pass
                d.pop(kid)
        speichern(d)

    @aufraeumen.before_loop
    async def _warten(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(EigenerKanal(bot))
