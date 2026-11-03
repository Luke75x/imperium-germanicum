"""/antrag: Abgeordnete und Landesherren des Reichstags reichen Anträge ein.

Das Modal fragt Titel, Antragstext und Begründung ab. Gespeichert wird der Antrag vom Imperium-Dienst
(reichstag.py, lokale Schnittstelle mit dem Bot-Token); dort prüft sich auch die Berechtigung, im Anträge-Kanal
erscheint der Antrag und das Präsidium bekommt eine DM. Das Präsidium setzt ihn über die interne Ansicht
(imperiumgermanicum.de/informationen/der-reichstag/intern/) auf die Tagesordnung einer Sitzung.
"""
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("imperium-bot.antrag")
DIENST = "http://127.0.0.1:8090/intern-api/reichstag/antrag"


class AntragModal(discord.ui.Modal, title="Antrag an den Reichstag"):
    titel = discord.ui.TextInput(label="Betreff", placeholder="Worum geht es?", min_length=5, max_length=150)
    text = discord.ui.TextInput(label="Antragstext", style=discord.TextStyle.paragraph, min_length=10, max_length=2500,
                                placeholder="Hiermit wird beantragt, …")
    begruendung = discord.ui.TextInput(label="Begründung", style=discord.TextStyle.paragraph, required=False, max_length=1000)

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        daten = {"konto_id": str(inter.user.id), "titel": self.titel.value, "text": self.text.value,
                 "begruendung": self.begruendung.value}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.post(DIENST, json=daten, headers={"X-Bot-Token": config.env("DISCORD_TOKEN")}) as r:
                    antwort = await r.json()
        except (aiohttp.ClientError, ValueError):
            log.exception("Imperium-Dienst nicht erreichbar")
            await inter.followup.send("Der Antrag konnte gerade nicht gespeichert werden. Bitte versuche es gleich noch einmal.", ephemeral=True)
            return
        if not antwort.get("ok"):
            await inter.followup.send(antwort.get("fehler", "Der Antrag wurde nicht angenommen."), ephemeral=True)
            return
        await inter.followup.send(f"Dein Antrag wurde als **Nr. {antwort['id']}** beim Reichstag eingebracht. "
                                  f"Das Präsidium setzt ihn auf die Tagesordnung einer Sitzung.\n{antwort['url']}", ephemeral=True)

    async def on_error(self, inter: discord.Interaction, error: Exception):
        log.exception("Antrag fehlgeschlagen", exc_info=error)
        if inter.response.is_done():
            await inter.followup.send("Beim Einreichen ist ein Fehler aufgetreten.", ephemeral=True)
        else:
            await inter.response.send_message("Beim Einreichen ist ein Fehler aufgetreten.", ephemeral=True)


class Antrag(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="antrag", description="Einen Antrag an den Reichstag einreichen")
    @app_commands.guild_only()
    async def antrag(self, inter: discord.Interaction):
        if not any(r.id in config.REICHSTAG_ROLLEN for r in inter.user.roles) and not inter.user.guild_permissions.administrator:
            await inter.response.send_message("Anträge können nur Abgeordnete und Landesherren des Reichstags einreichen.", ephemeral=True)
            return
        await inter.response.send_modal(AntragModal())


async def setup(bot):
    await bot.add_cog(Antrag(bot))
