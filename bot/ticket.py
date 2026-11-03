"""Ticketsystem der Einwanderungsbehörde (Kanal 🛂｜einwanderungsbehörde).

Das Panel (Nachricht EINREISE_PANEL mit Auswahlmenü „Anliegen wählen …“) stammt vom alten Bot und bleibt bestehen.
„Einreise beantragen“ → Modal (IC-Name, Geschichte, Vorstellung) → privater Thread im Kanal mit den Antworten,
dem Antragsteller und der Kaiserlichen Zollverwaltung. „Ticket schließen“ archiviert und sperrt den Thread.
Die Bedienelemente sind persistent (feste custom_id) und funktionieren daher auch nach einem Neustart.
"""
import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger("imperium-bot.ticket")

PANEL_ID = "einreise-panel"
SCHLIESSEN_ID = "ticket-schliessen"
FARBE = 16763937


def ticket_name(user: discord.abc.User) -> str:
    return f"einreise-{user.name}"[:100]


def darf_bearbeiten(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.id == config.ZOLLVERWALTUNG_ROLLE for r in member.roles)


class EinreiseModal(discord.ui.Modal, title="Antrag auf Einreise"):
    ic_name = discord.ui.TextInput(label="IC-Name", placeholder="Name Ihres Charakters im Rollenspiel",
                                   min_length=2, max_length=32)
    geschichte = discord.ui.TextInput(label="Geschichte Ihres Charakters", style=discord.TextStyle.paragraph,
                                      min_length=10, max_length=1000)
    vorstellung = discord.ui.TextInput(label="Wie stellen Sie sich bei uns vor?", style=discord.TextStyle.paragraph,
                                       min_length=10, max_length=1000)

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        guild, user = inter.guild, inter.user
        kanal = guild.get_channel(config.TICKET_KANAL) or await guild.fetch_channel(config.TICKET_KANAL)

        name = ticket_name(user)
        for t in await guild.active_threads():
            if t.parent_id == kanal.id and t.name == name:
                await inter.followup.send(f"Sie haben bereits ein offenes Ticket: {t.mention}", ephemeral=True)
                return

        thread = await kanal.create_thread(name=name, type=discord.ChannelType.private_thread, invitable=False,
                                           reason=f"Antrag auf Einreise von {user}")
        await thread.add_user(user)

        antrag = discord.Embed(title="Antrag auf Einreise", color=FARBE)
        antrag.set_author(name=f"{user.name}", icon_url=user.display_avatar.url)
        antrag.add_field(name="IC-Name", value=self.ic_name.value.strip(), inline=False)
        antrag.add_field(name="Geschichte des Charakters", value=self.geschichte.value.strip(), inline=False)
        antrag.add_field(name="Vorstellung", value=self.vorstellung.value.strip(), inline=False)
        antrag.set_footer(text="Imperium Germanicum · Kaiserliche Zollverwaltung")
        await thread.send(
            content=f"{user.mention} <@&{config.ZOLLVERWALTUNG_ROLLE}>\n"
                    "Ihr Antrag wurde eingereicht. Die zuständigen Beamten der Zollverwaltung bearbeiten ihn "
                    "in diesem Ticket und melden sich bei Ihnen.",
            embed=antrag, view=SchliessenView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await inter.followup.send(f"Ihr Ticket wurde eröffnet: {thread.mention}", ephemeral=True)

    async def on_error(self, inter: discord.Interaction, error: Exception):
        log.exception("Ticket konnte nicht eröffnet werden", exc_info=error)
        msg = "Das Ticket konnte nicht eröffnet werden. Bitte wenden Sie sich an die Zollverwaltung."
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(custom_id=PANEL_ID, placeholder="Anliegen wählen …", min_values=1, max_values=1, options=[
        discord.SelectOption(label="Einreise beantragen", value="einreise", emoji="🛂",
                             description="Antrag auf Einreise und Einbürgerung stellen")])
    async def auswahl(self, inter: discord.Interaction, select: discord.ui.Select):
        await inter.response.send_modal(EinreiseModal())
        try:  # Auswahl zurücksetzen, damit das Menü erneut benutzt werden kann
            await inter.message.edit(view=PanelView())
        except discord.HTTPException:
            pass


class SchliessenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket schließen", style=discord.ButtonStyle.danger, custom_id=SCHLIESSEN_ID, emoji="🔒")
    async def schliessen(self, inter: discord.Interaction, button: discord.ui.Button):
        if not darf_bearbeiten(inter.user):
            await inter.response.send_message("Nur die Kaiserliche Zollverwaltung kann das Ticket schließen.",
                                              ephemeral=True)
            return
        await inter.response.send_message(f"🔒 Ticket von {inter.user.mention} geschlossen.")
        await inter.channel.edit(archived=True, locked=True, reason=f"Ticket geschlossen von {inter.user}")


class Ticket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelView())
        self.bot.add_view(SchliessenView())


async def setup(bot):
    await bot.add_cog(Ticket(bot))
