"""/vertreter: Abgeordnete und Landesherren des Reichstags ernennen eine beliebige Person zu ihrem Vertreter (oder heben die Vertretung auf).
Gespeichert wird im Imperium-Dienst (reichstag.py); in der Abstimmungs- und Anwesenheitsliste steht dann unter dem Namen
„Vertreten durch: <Name>“. Ohne Angabe einer Person wird die Vertretung aufgehoben.
"""
import logging
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("imperium-bot.vertreter")
DIENST = "http://127.0.0.1:8090/intern-api/reichstag/vertreter"


class Vertreter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="vertreter", description="Einen Vertreter im Reichstag ernennen (ohne Angabe: Vertretung aufheben)")
    @app_commands.describe(person="Die Person, die dich vertritt – leer lassen, um die Vertretung aufzuheben")
    @app_commands.guild_only()
    async def vertreter(self, inter: discord.Interaction, person: Optional[discord.Member] = None):
        if not any(r.id in config.REICHSTAG_ROLLEN for r in inter.user.roles) and not inter.user.guild_permissions.administrator:
            await inter.response.send_message("Einen Vertreter können nur Abgeordnete und Landesherren des Reichstags ernennen.", ephemeral=True)
            return
        if person is not None and person.bot:
            await inter.response.send_message("Ein Bot kann dich nicht vertreten.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        daten = {"konto_id": str(inter.user.id), "vertreter_id": str(person.id) if person else ""}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.post(DIENST, json=daten, headers={"X-Bot-Token": config.env("DISCORD_TOKEN")}) as r:
                    antwort = await r.json()
        except (aiohttp.ClientError, ValueError):
            log.exception("Imperium-Dienst nicht erreichbar")
            await inter.followup.send("Die Vertretung konnte gerade nicht gespeichert werden. Bitte versuche es gleich noch einmal.", ephemeral=True)
            return
        if not antwort.get("ok"):
            await inter.followup.send(antwort.get("fehler", "Das hat nicht geklappt."), ephemeral=True)
        elif antwort["aktion"] == "ernannt":
            await inter.followup.send(f"✓ {person.mention} ist jetzt dein Vertreter. In den Listen des Reichstags steht unter deinem Namen: "
                                      f"„Vertreten durch: {antwort['name']}“. Mit `/vertreter` ohne Person hebst du die Vertretung auf.",
                                      ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await inter.followup.send("✓ Deine Vertretung ist aufgehoben." if antwort.get("alt") else "Du hattest keinen Vertreter ernannt.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Vertreter(bot))
