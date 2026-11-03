"""Kaiserliches Zollamt (Kanal 🧳｜kaiserliches-zollamt).

- Mitglied tritt bei  → Aufenthaltsvisum-Embed in den Thread „Erteilte Aufenthaltsvisen“.
- Mitglied verlässt   → „Aufenthaltvisum abgelaufen“-Embed in den Thread „Abgelaufene Aufenthaltsvisen“.
- /einbürgern @Person → Modal nach dem IC-Namen, danach Rollen vergeben, Person umbenannt und
                        Einbürgerungs-Embed in den Thread „Erfolgreiche Einbürgerungen“.
Die Texte entsprechen den Nachrichten des alten Bots (siehe Konstanten in config.py).
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("imperium-bot.zollamt")

FARBE_BLAU = 4877950
FARBE_ABGELAUFEN = 9187129


def embed_visum(member: discord.Member) -> discord.Embed:
    e = discord.Embed(
        title="Aufenthaltvisum",
        description=(
            f"Im Namen von seiner Majestät dem Kaiser wird dem Einwanderer {member.mention}, von der Zollverwaltung "
            "ein Visum für einen befristeten Aufenthalt im **Imperium Germanicum** genehmigt.\n\n"
            "Die Einbürgerung des Einwanderers wird in dieser Zeit von den zuständigen Beamten bearbeitet, und dieser "
            "erhält in Kürze eine Nachricht für das weitere Verfahren.\n\n"
            "Im Namen von seiner kaiserlichen und königlichen Majestät Alexander IX.\n\n"
            "Der Staatssekretär in der kaiserlichen Zollverwaltung"),
        color=FARBE_BLAU)
    e.set_author(name="Kaiserliche Zollverwaltung")
    e.set_thumbnail(url=config.ZOLL_BILD_VISUM)
    e.set_footer(text="Das Imperium Germanicum")
    return e


def zoll_bild() -> discord.File:
    return discord.File(config.ZOLL_BILD_ABGELAUFEN, filename="zoll.png")


def embed_abgelaufen(member: discord.abc.User) -> discord.Embed:
    e = discord.Embed(
        title="Kaiserliche Zollverwaltung",
        description=(
            f"Im Namen seiner Majestät dem Kaiser verkündet die Zollverwaltung, dass das Aufenthaltvisum von "
            f"**{member.name}** abgelaufen ist und das Imperium Germanicum daher wieder verlassen wurde.\n\n"
            "Im Namen von seiner kaiserlichen und königlichen Majestät Alexander IX.\n\n"
            "**Der Staatssekretär in der kaiserlichen Zollverwaltung**\nDas Imperium Germanicum"),
        color=FARBE_ABGELAUFEN)
    e.set_author(name="Aufenthaltvisum abgelaufen")
    e.set_thumbnail(url="attachment://zoll.png")
    return e


def embed_einbuergerung(member: discord.Member) -> discord.Embed:
    e = discord.Embed(
        title="Einbürgerung",
        description=(
            "Verehrte Untertanen des Imperiums,\n\n"
            f"der Einwanderer **{member.name}** hat das Einbürgerungsverfahren abgeschlossen und im Namen seiner "
            "Majestät dem Kaiser durch die Zollverwaltung die Staatsbürgerschaft im Imperium Germanicum erhalten.\n\n"
            "Herzlichen Glückwunsch an den neuen Bürger dieses glorreichen Imperiums."),
        color=FARBE_BLAU)
    e.set_author(name="Kaiserliche Zollverwaltung")
    e.set_thumbnail(url=config.ZOLL_BILD_VISUM)
    e.set_footer(text="Der Staatssekretär im der kaiserlichen Zollverwaltung")
    return e


class NameModal(discord.ui.Modal, title="Einbürgerung"):
    ic_name = discord.ui.TextInput(label="IC-Name", placeholder="Name im Rollenspiel", min_length=1, max_length=32)

    def __init__(self, cog: "Zollamt", ziel: discord.Member):
        super().__init__()
        self.cog = cog
        self.ziel = ziel

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        ziel, guild = self.ziel, inter.guild
        name = self.ic_name.value.strip()
        if not name:
            await inter.followup.send("Ohne IC-Namen keine Einbürgerung.", ephemeral=True)
            return

        rollen = [r for r in (guild.get_role(i) for i in config.EINBUERGERUNG_ROLLEN) if r]
        fehlend = [i for i in config.EINBUERGERUNG_ROLLEN if guild.get_role(i) is None]
        try:
            await ziel.add_roles(*rollen, reason=f"Einbürgerung durch {inter.user}")
        except discord.Forbidden:
            await inter.followup.send("Ich darf diese Rollen nicht vergeben (Rollen-Hierarchie).", ephemeral=True)
            return

        hinweise = []
        if fehlend:
            hinweise.append(f"Rollen nicht gefunden: {', '.join(map(str, fehlend))}")
        try:
            await ziel.edit(nick=name, reason=f"Einbürgerung durch {inter.user}")
        except discord.Forbidden:
            hinweise.append("Umbenennen nicht möglich (Rolle der Person steht über meiner oder sie ist Serverbesitzer).")

        thread = self.cog.bot.get_channel(config.THREAD_EINBUERGERUNGEN) \
            or await self.cog.bot.fetch_channel(config.THREAD_EINBUERGERUNGEN)
        await thread.send(content=ziel.mention, embed=embed_einbuergerung(ziel))

        text = f"{ziel.mention} wurde als **{name}** eingebürgert."
        if hinweise:
            text += "\n⚠ " + "\n⚠ ".join(hinweise)
        await inter.followup.send(text, ephemeral=True)

    async def on_error(self, inter: discord.Interaction, error: Exception):
        log.exception("Einbürgerung fehlgeschlagen", exc_info=error)
        msg = "Bei der Einbürgerung ist ein Fehler aufgetreten."
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)


class Zollamt(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _thread(self, thread_id):
        return self.bot.get_channel(thread_id) or await self.bot.fetch_channel(thread_id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != config.GUILD_ID or member.bot:
            return
        rolle = member.guild.get_role(config.EINWANDERER_ROLLE)
        try:
            await member.add_roles(rolle, reason="Beitritt: Einwanderer")
        except (discord.HTTPException, AttributeError):
            log.exception("Einwanderer-Rolle konnte %s nicht gegeben werden", member)
        for thread_id in config.THREAD_VISEN:
            try:
                thread = await self._thread(thread_id)
                await thread.send(content=member.mention, embed=embed_visum(member))
            except discord.HTTPException:
                log.exception("Visum-Meldung nach %s fehlgeschlagen", thread_id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.guild.id != config.GUILD_ID or member.bot:
            return
        thread = await self._thread(config.THREAD_ABGELAUFEN)
        await thread.send(content=member.mention, embed=embed_abgelaufen(member), file=zoll_bild())

    @app_commands.command(name="einbürgern", description="Bürgert eine Person im Imperium Germanicum ein")
    @app_commands.guild_only()
    @app_commands.describe(person="Die Person, die eingebürgert wird")
    async def einbuergern(self, inter: discord.Interaction, person: discord.Member):
        if not any(r.id == config.ZOLLVERWALTUNG_ROLLE for r in inter.user.roles):
            await inter.response.send_message("Nur die Kaiserliche Zollverwaltung darf einbürgern.", ephemeral=True)
            return
        if person.bot:
            await inter.response.send_message("Bots lassen sich nicht einbürgern.", ephemeral=True)
            return
        await inter.response.send_modal(NameModal(self, person))


async def setup(bot):
    await bot.add_cog(Zollamt(bot))
