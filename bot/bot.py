"""Imperium-Bot (Discord) für den Server des Imperium Germanicum.

Start: .venv/bin/python bot.py   (als Dienst: imperium-bot.service)
Braucht DISCORD_TOKEN (Bot-Token) in /root/.env.
"""
import logging

import discord
from discord.ext import commands

import config

MODULE = ["info_kanal", "gesetzblatt", "zollamt", "ticket", "audienz", "antrag"]

log = logging.getLogger("imperium-bot")


class ImperiumBot(commands.Bot):
    async def setup_hook(self):
        for modul in MODULE:
            await self.load_extension(modul)
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        befehle = await self.tree.sync(guild=guild)
        log.info("%d Befehle synchronisiert, Module: %s", len(befehle), ", ".join(self.cogs))

    async def on_ready(self):
        log.info("Angemeldet als %s (%s)", self.user, self.user.id)


def main():
    token = config.env("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN fehlt in /root/.env")
    intents = discord.Intents.default()
    intents.members = True  # Beitritt/Austritt fürs Zollamt (privilegierter Intent, im Developer-Portal aktiv)
    bot = ImperiumBot(command_prefix=commands.when_mentioned, intents=intents)
    bot.run(token, root_logger=True)


if __name__ == "__main__":
    main()
