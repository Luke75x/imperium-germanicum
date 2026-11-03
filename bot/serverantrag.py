"""/serverantrag: Jeder Nutzer kann ein Ereignis für den Server (Rollenspiel) beantragen.

Das Modal fragt Ereignis, Beschreibung, betroffene Charaktere und Zeitpunkt ab. Der Antrag erscheint im Kanal
SERVERANTRAG_KANAL mit den Knöpfen „Akzeptieren“ und „Abweisen“ (bei Abweisen optional mit Begründung); wer den Kanal
sehen kann, darf entscheiden. Der Antragsteller bekommt zu jeder Entscheidung eine DM. Die Knöpfe sind persistent; die
Antragsteller-ID steht im Footer des Antrags, es gibt keine Datenbank.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("imperium-bot.serverantrag")

PREFIX = "serverantrag:"
FARBE_OFFEN, FARBE_OK, FARBE_NEIN = 0x2E4A7D, 0x2F6B3A, 0xA3261B
FOOTER = "Antragsteller-ID: "


def antragsteller_id(embed: discord.Embed) -> int:
    return int((embed.footer.text or "").removeprefix(FOOTER))


async def dm_senden(user: discord.abc.User, text: str) -> bool:
    try:
        await user.send(text)
        return True
    except discord.HTTPException:
        return False


def darf_entscheiden(inter: discord.Interaction) -> bool:
    return inter.channel.permissions_for(inter.user).view_channel


async def abschliessen(inter: discord.Interaction, nachricht: discord.Message, akzeptiert: bool, begruendung: str = ""):
    """Markiert den Antrag als entschieden (Farbe, Feld, ohne Knöpfe) und schreibt dem Antragsteller."""
    embed = nachricht.embeds[0]
    embed.color = FARBE_OK if akzeptiert else FARBE_NEIN
    stand = "✅ Akzeptiert" if akzeptiert else "❌ Abgewiesen"
    embed.add_field(name="Entscheidung", value=f"{stand} von {inter.user.mention}", inline=False)
    if begruendung:
        embed.add_field(name="Begründung", value=begruendung, inline=False)

    user = inter.client.get_user(antragsteller_id(embed)) or await inter.client.fetch_user(antragsteller_id(embed))
    ereignis = embed.title.removeprefix("Serverantrag: ")
    if akzeptiert:
        text = f"Dein Serverantrag **„{ereignis}“** wurde **akzeptiert**."
    else:
        text = f"Dein Serverantrag **„{ereignis}“** wurde **abgewiesen**." + (f"\n> {begruendung}" if begruendung else "")
    if not await dm_senden(user, text):
        embed.add_field(name="Hinweis", value="Die Direktnachricht an den Antragsteller konnte nicht zugestellt werden.", inline=False)
    await nachricht.edit(embed=embed, view=None)


class AbweisenModal(discord.ui.Modal, title="Antrag abweisen"):
    begruendung = discord.ui.TextInput(label="Begründung (optional)", style=discord.TextStyle.paragraph, required=False, max_length=1000)

    def __init__(self, nachricht: discord.Message):
        super().__init__()
        self.nachricht = nachricht

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer()
        await abschliessen(inter, self.nachricht, False, self.begruendung.value.strip())

    async def on_error(self, inter: discord.Interaction, error: Exception):
        log.exception("Abweisen fehlgeschlagen", exc_info=error)
        if not inter.response.is_done():
            await inter.response.send_message("Beim Abweisen ist ein Fehler aufgetreten.", ephemeral=True)


class EntscheidungView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Akzeptieren", style=discord.ButtonStyle.success, custom_id=PREFIX + "ja")
    async def akzeptieren(self, inter: discord.Interaction, button: discord.ui.Button):
        if not darf_entscheiden(inter):
            await inter.response.send_message("Darüber entscheidet die Server- und RP-Leitung.", ephemeral=True)
            return
        await inter.response.defer()
        await abschliessen(inter, inter.message, True)

    @discord.ui.button(label="Abweisen", style=discord.ButtonStyle.danger, custom_id=PREFIX + "nein")
    async def abweisen(self, inter: discord.Interaction, button: discord.ui.Button):
        if not darf_entscheiden(inter):
            await inter.response.send_message("Darüber entscheidet die Server- und RP-Leitung.", ephemeral=True)
            return
        await inter.response.send_modal(AbweisenModal(inter.message))


class AntragModal(discord.ui.Modal, title="Serverantrag"):
    ereignis = discord.ui.TextInput(label="Welches Ereignis?", placeholder="z. B. Krönungsfeier, Aufstand, Krieg …", max_length=100)
    beschreibung = discord.ui.TextInput(label="Beschreibung des Ereignisses", style=discord.TextStyle.paragraph, max_length=1000)
    charaktere = discord.ui.TextInput(label="Betroffene Charaktere", style=discord.TextStyle.paragraph, max_length=1000)
    zeitpunkt = discord.ui.TextInput(label="Zeitpunkt / Zeitrahmen", placeholder="z. B. Samstag, 20:00 Uhr oder nächste Woche", max_length=100)

    async def on_submit(self, inter: discord.Interaction):
        kanal = inter.client.get_channel(config.SERVERANTRAG_KANAL) or await inter.client.fetch_channel(config.SERVERANTRAG_KANAL)
        embed = discord.Embed(title=f"Serverantrag: {self.ereignis.value.strip()}"[:256], color=FARBE_OFFEN,
                              description=f"Eingereicht von {inter.user.mention}")
        embed.add_field(name="Beschreibung des Ereignisses", value=self.beschreibung.value.strip(), inline=False)
        embed.add_field(name="Betroffene Charaktere", value=self.charaktere.value.strip(), inline=False)
        embed.add_field(name="Zeitpunkt / Zeitrahmen", value=self.zeitpunkt.value.strip(), inline=False)
        embed.set_author(name=inter.user.display_name, icon_url=inter.user.display_avatar.url)
        embed.set_footer(text=f"{FOOTER}{inter.user.id}")
        embed.timestamp = discord.utils.utcnow()
        await kanal.send(embed=embed, view=EntscheidungView(), allowed_mentions=discord.AllowedMentions.none())
        await inter.response.send_message("Dein Serverantrag wurde eingereicht. Du bekommst eine Nachricht, sobald er bearbeitet wurde.",
                                          ephemeral=True)

    async def on_error(self, inter: discord.Interaction, error: Exception):
        log.exception("Serverantrag fehlgeschlagen", exc_info=error)
        if not inter.response.is_done():
            await inter.response.send_message("Der Antrag konnte nicht eingereicht werden. Bitte versuche es später noch einmal.", ephemeral=True)


class Serverantrag(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(EntscheidungView())

    @app_commands.command(name="serverantrag", description="Ein Ereignis für den Server beantragen")
    @app_commands.guild_only()
    async def serverantrag(self, inter: discord.Interaction):
        await inter.response.send_modal(AntragModal())


async def setup(bot):
    await bot.add_cog(Serverantrag(bot))
