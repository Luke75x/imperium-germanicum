"""Generalaudienz: Betritt der Kaiser das Audienzzimmer (Sprachkanal), fragt der Bot ihn per DM, ob die
Generalaudienz eröffnet werden soll. „Ja“ veröffentlicht die Bekanntmachung im News-Kanal, „Nein“ verwirft die Frage.
Die Knöpfe sind persistent (feste custom_id) und funktionieren nach einem Neustart weiter.
"""
import logging
import os

import discord
from discord.ext import commands

import config

log = logging.getLogger("imperium-bot.audienz")

BILDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sicherung")


def bekanntmachung():
    """Embed und Bilddateien der Generalaudienz (Text wie die bisherigen Bekanntmachungen im News-Kanal)."""
    e = discord.Embed(
        title="Generalaudienz",
        description=(
            "Verehrte Untertanen des Imperium Germanicum,\n\n"
            "seine kaiserliche und königliche Majestät Kaiser Alexander IX. steht ihnen nun persönlich zu einer "
            "Generalaudienz zu Verfügung und öffnet spontan die Tore Charlottenburgs.\n\n"
            "Alle Untertanen welche die Generalaudienz mit seiner Majestät wahrnehmen möchten dürfen sich nun im "
            "🕰️｜Vorzimmer einfinden und werden in Kürze empfangen."),
        color=13214778)
    e.set_author(name="Das Schloss Charlottenburg")
    e.set_image(url="attachment://schloss.png")
    e.set_thumbnail(url="attachment://icon.png")
    dateien = [discord.File(os.path.join(BILDER, n), filename=n) for n in ("schloss.png", "icon.png")]
    return e, dateien


class AudienzView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _antwort(self, inter: discord.Interaction, text: str):
        await inter.response.edit_message(content=f"{inter.message.content}\n\n{text}", view=None)

    @discord.ui.button(label="Ja", style=discord.ButtonStyle.success, custom_id="audienz:ja")
    async def ja(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id != config.KAISER_ID:
            await inter.response.send_message("Nur der Kaiser kann das entscheiden.", ephemeral=True)
            return
        kanal = inter.client.get_channel(config.NEWS_KANAL) or await inter.client.fetch_channel(config.NEWS_KANAL)
        embed, dateien = bekanntmachung()
        await kanal.send(embed=embed, files=dateien)
        await self._antwort(inter, f"✓ Die Generalaudienz wurde in {kanal.mention} bekanntgegeben.")

    @discord.ui.button(label="Nein", style=discord.ButtonStyle.secondary, custom_id="audienz:nein")
    async def nein(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id != config.KAISER_ID:
            await inter.response.send_message("Nur der Kaiser kann das entscheiden.", ephemeral=True)
            return
        await self._antwort(inter, "✗ Keine Generalaudienz.")


class Audienz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(AudienzView())

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id != config.KAISER_ID or after.channel is None or after.channel.id != config.AUDIENZ_KANAL:
            return
        if before.channel is not None and before.channel.id == after.channel.id:
            return  # nur Stummschalten o. Ä., kein Beitritt
        await member.send("Majestät, Sie haben das Audienzzimmer betreten.\n**Generalaudienz öffnen?**",
                          view=AudienzView())


async def setup(bot):
    await bot.add_cog(Audienz(bot))
