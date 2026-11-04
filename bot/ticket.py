"""Ticketsystem der Einwanderungsbehörde (Kanal 🛂｜einwanderungsbehörde).

Das Panel (Nachricht EINREISE_PANEL mit Auswahlmenü „Anliegen wählen …“) stammt vom alten Bot und bleibt bestehen.
„Einreise beantragen“ → Modal (IC-Name, Geschichte, Vorstellung) → privater Thread im Kanal mit den Antworten,
dem Antragsteller und der Kaiserlichen Zollverwaltung. „Ticket schließen“ archiviert und sperrt den Thread.
Die Bedienelemente sind persistent (feste custom_id) und funktionieren daher auch nach einem Neustart.
"""
import datetime
import json
import logging
import os
import sqlite3

import discord
from discord.ext import commands

import amt_api
import config

log = logging.getLogger("imperium-bot.ticket")

PANEL_ID = "einreise-panel"
SCHLIESSEN_ID = "ticket-schliessen"
FARBE = 16763937
EINLEITEN_ID = "einreise-phase2-einleiten"
STARTEN_ID = "einreise-phase2-starten"
MINDESTALTER = 16
KEINE_FRAKTION = "Imperium Germanicum (kein Teilstaat)"
KEIN_TEILSTAAT = {"Freie Reichsgebiete"}
SCHICHTEN = ["Bürgerstand", "Adelsstand", "Klerus", "Bauernstand", "Sonstiges"]
BERUFE = ["Militärischer Natur", "Beamter", "Sonstiges"]
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "einreise.db")


def _db():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS einreise (thread_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, phase INTEGER NOT NULL)")
    return con


def db_setzen(thread_id: int, user_id: int, phase: int):
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO einreise VALUES (?,?,?)", (thread_id, user_id, phase))


def db_holen(thread_id: int):
    """(user_id, phase) oder None. Phase 1 = OOC, 2 = IC eingeleitet, 3 = IC ausgefüllt."""
    with _db() as con:
        return con.execute("SELECT user_id, phase FROM einreise WHERE thread_id=?", (thread_id,)).fetchone()


def ticket_name(user: discord.abc.User) -> str:
    return f"einreise-{user.name}"[:100]


def darf_bearbeiten(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.id == config.ZOLLVERWALTUNG_ROLLE for r in member.roles)


def parse_datum(text: str):
    """TT.MM.JJJJ → date oder None."""
    try:
        return datetime.datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def alter(geb: datetime.date) -> int:
    heute = datetime.date.today()
    return heute.year - geb.year - ((heute.month, heute.day) < (geb.month, geb.day))


class EinreiseModal(discord.ui.Modal, title="Einreise – Phase I (OOC)"):
    name = discord.ui.TextInput(label="Name (OOC)", placeholder="Ihr echter Vorname / Anzeigename", min_length=2, max_length=32)
    geburtsdatum = discord.ui.TextInput(label="Geburtsdatum (mind. 16 Jahre)", placeholder="TT.MM.JJJJ",
                                        min_length=8, max_length=10)
    aufmerksam = discord.ui.TextInput(label="Wie bist du auf uns aufmerksam geworden?", max_length=300)
    wunsch = discord.ui.TextInput(label="Vorstellung bei uns / Wunschposition",
                                  style=discord.TextStyle.paragraph, min_length=5, max_length=1000)
    rolle = discord.ui.TextInput(label="Beschreibung deiner Rolle", style=discord.TextStyle.paragraph,
                                 min_length=10, max_length=1000)

    async def on_submit(self, inter: discord.Interaction):
        geb = parse_datum(self.geburtsdatum.value)
        if geb is None or geb > datetime.date.today():
            await inter.response.send_message("Das Geburtsdatum ist ungültig. Bitte im Format TT.MM.JJJJ angeben.", ephemeral=True)
            return
        if alter(geb) < MINDESTALTER:
            await inter.response.send_message(f"Eine Einreise ist erst ab {MINDESTALTER} Jahren möglich.", ephemeral=True)
            return
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

        antrag = discord.Embed(title="Einreise – Phase I (OOC)", color=FARBE)
        antrag.set_author(name=f"{user.name}", icon_url=user.display_avatar.url)
        antrag.add_field(name="Name (OOC)", value=self.name.value.strip(), inline=True)
        antrag.add_field(name="Geburtsdatum", value=f"{geb:%d.%m.%Y} ({alter(geb)} Jahre)", inline=True)
        antrag.add_field(name="Aufmerksam geworden durch", value=self.aufmerksam.value.strip(), inline=False)
        antrag.add_field(name="Vorstellung / Wunschposition", value=self.wunsch.value.strip(), inline=False)
        antrag.add_field(name="Beschreibung der Rolle", value=self.rolle.value.strip(), inline=False)
        antrag.set_footer(text="Imperium Germanicum · Kaiserliche Zollverwaltung")
        db_setzen(thread.id, user.id, 1)
        await thread.send(
            content=f"{user.mention} <@&{config.ZOLLVERWALTUNG_ROLLE}>\n"
                    "Ihr Antrag (Phase I, außerhalb des Charakters) wurde eingereicht. Die Zollverwaltung prüft ihn; "
                    "bei Zustimmung leitet sie **Phase II (im Charakter)** ein, die Sie dann hier starten.",
            embed=antrag, view=PhaseIView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await inter.followup.send(f"Ihr Ticket wurde eröffnet: {thread.mention}", ephemeral=True)
        await amt_api.melden("einreise", {"konto_id": str(user.id), "name": user.name, "thread_id": str(thread.id), "phase": 1, "daten": {
            "name": self.name.value.strip(), "geburtsdatum": f"{geb:%d.%m.%Y}", "aufmerksam": self.aufmerksam.value.strip(),
            "wunsch": self.wunsch.value.strip(), "rolle": self.rolle.value.strip()}})

    async def on_error(self, inter: discord.Interaction, error: Exception):
        log.exception("Ticket konnte nicht eröffnet werden", exc_info=error)
        msg = "Das Ticket konnte nicht eröffnet werden. Bitte wenden Sie sich an die Zollverwaltung."
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)


def fraktionen() -> list[str]:
    """Teilstaaten aus dem aktuellen Stand der Reichskarte (Dienst-DB) + Imperium Germanicum (kein Teilstaat)."""
    namen = []
    try:
        con = sqlite3.connect(f"file:{config.DIENST_DB}?mode=ro", uri=True)
        try:
            zeile = con.execute("SELECT stand FROM karte_versionen ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            con.close()
        namen = [s["name"] for s in json.loads(zeile[0]).get("staaten", []) if s.get("name") and s["name"] not in KEIN_TEILSTAAT]
    except Exception:
        log.exception("Teilstaaten konnten nicht gelesen werden")
    return sorted(namen)[:24] + [KEINE_FRAKTION]


class Phase2Modal(discord.ui.Modal, title="Einreise – Phase II (IC)"):
    name = discord.ui.TextInput(label="Vor- und Nachname (IC)", min_length=3, max_length=60)
    geburtsdatum = discord.ui.TextInput(label="Geburtsdatum (In Charakter!)", placeholder="z. B. 12.03.1987", max_length=40)
    vorgeschichte = discord.ui.TextInput(label="Personelle Vorgeschichte", style=discord.TextStyle.paragraph,
                                         min_length=10, max_length=1500)

    def __init__(self, thread_id: int, wahl: dict):
        super().__init__()
        self.thread_id, self.wahl = thread_id, wahl

    async def on_submit(self, inter: discord.Interaction):
        row = db_holen(self.thread_id)
        if not row or row[1] != 2:
            await inter.response.send_message("Phase II ist nicht (mehr) offen.", ephemeral=True)
            return
        db_setzen(self.thread_id, row[0], 3)
        e = discord.Embed(title="Einreise – Phase II (IC)", color=FARBE)
        e.set_author(name=inter.user.name, icon_url=inter.user.display_avatar.url)
        e.add_field(name="Name (IC)", value=self.name.value.strip(), inline=True)
        e.add_field(name="Geburtsdatum (IC)", value=self.geburtsdatum.value.strip(), inline=True)
        e.add_field(name="Fraktion", value=self.wahl["fraktion"], inline=False)
        e.add_field(name="Gesellschaftsschicht", value=self.wahl["schicht"], inline=True)
        e.add_field(name="Berufliche Zugehörigkeit", value=self.wahl["beruf"], inline=True)
        e.add_field(name="Personelle Vorgeschichte", value=self.vorgeschichte.value.strip(), inline=False)
        e.set_footer(text="Imperium Germanicum · Kaiserliche Zollverwaltung")
        await inter.channel.send(
            content=f"<@&{config.ZOLLVERWALTUNG_ROLLE}> Phase II wurde ausgefüllt. Die Zollverwaltung kann nun "
                    "über die Einbürgerung entscheiden (`/einbürgern`).",
            embed=e, allowed_mentions=discord.AllowedMentions(roles=True))
        await inter.response.edit_message(content="✅ Phase II wurde übermittelt.", view=None)
        await amt_api.melden("einreise", {"konto_id": str(inter.user.id), "name": inter.user.name, "thread_id": str(inter.channel.id), "phase": 3, "daten": {
            "name": self.name.value.strip(), "geburtsdatum": self.geburtsdatum.value.strip(), "fraktion": self.wahl["fraktion"],
            "schicht": self.wahl["schicht"], "beruf": self.wahl["beruf"], "vorgeschichte": self.vorgeschichte.value.strip()}})
        try:  # „Phase II starten“ aus der Thread-Nachricht entfernen
            if self.wahl.get("nachricht"):
                await inter.channel.get_partial_message(self.wahl["nachricht"]).edit(view=None)
        except discord.HTTPException:
            pass

    async def on_error(self, inter: discord.Interaction, error: Exception):
        log.exception("Phase II fehlgeschlagen", exc_info=error)
        if not inter.response.is_done():
            await inter.response.send_message("Phase II konnte nicht übermittelt werden.", ephemeral=True)


class Phase2Auswahl(discord.ui.View):
    """Ephemere Auswahl (Fraktion, Schicht, Beruf), danach das Textmodal."""

    def __init__(self, thread_id: int, nachricht: int):
        super().__init__(timeout=900)
        self.thread_id = thread_id
        self.wahl = {"nachricht": nachricht}
        for schluessel, platzhalter, optionen in (
                ("fraktion", "Fraktion wählen …", fraktionen()),
                ("schicht", "Gesellschaftsschicht wählen …", SCHICHTEN),
                ("beruf", "Berufliche Zugehörigkeit wählen …", BERUFE)):
            sel = discord.ui.Select(placeholder=platzhalter, options=[discord.SelectOption(label=o, value=o) for o in optionen])
            sel.callback = self._callback(schluessel, sel)
            self.add_item(sel)

    def _callback(self, schluessel: str, sel: discord.ui.Select):
        async def cb(inter: discord.Interaction):
            self.wahl[schluessel] = sel.values[0]
            for opt in sel.options:
                opt.default = opt.value == sel.values[0]
            await inter.response.edit_message(view=self)
        return cb

    @discord.ui.button(label="Weiter", style=discord.ButtonStyle.success, row=4)
    async def weiter(self, inter: discord.Interaction, button: discord.ui.Button):
        if not all(k in self.wahl for k in ("fraktion", "schicht", "beruf")):
            await inter.response.send_message("Bitte zuerst Fraktion, Gesellschaftsschicht und Berufliche Zugehörigkeit wählen.", ephemeral=True)
            return
        await inter.response.send_modal(Phase2Modal(self.thread_id, self.wahl))


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
        await amt_api.melden("ticket-geschlossen", {"thread_id": str(inter.channel.id), "beamter_id": str(inter.user.id),
                                                    "beamter_name": inter.user.display_name})
        await inter.channel.edit(archived=True, locked=True, reason=f"Ticket geschlossen von {inter.user}")


class PhaseIView(SchliessenView):
    """Antrag der Phase I: Einleiten-Knopf + Schließen-Knopf."""

    @discord.ui.button(label="Einreise – Phase II einleiten", style=discord.ButtonStyle.primary, custom_id=EINLEITEN_ID, emoji="➡️")
    async def einleiten(self, inter: discord.Interaction, button: discord.ui.Button):
        if not darf_bearbeiten(inter.user):
            await inter.response.send_message("Nur die Kaiserliche Zollverwaltung kann Phase II einleiten.", ephemeral=True)
            return
        row = db_holen(inter.channel.id)
        if not row:
            await inter.response.send_message("Zu diesem Ticket ist kein Antragsteller gespeichert (altes Ticket).", ephemeral=True)
            return
        if row[1] != 1:
            await inter.response.send_message("Phase II wurde bereits eingeleitet.", ephemeral=True)
            return
        db_setzen(inter.channel.id, row[0], 2)
        # Knopf im Antrag entfernen, Schließen-Knopf behalten
        await inter.response.edit_message(view=SchliessenView())
        await inter.channel.send(
            content=f"<@{row[0]}> Ihr Antrag wurde von {inter.user.mention} angenommen. Die Einreise geht nun in "
                    "**Phase II (im Charakter)** über. Drücken Sie auf „Einreise – Phase II starten“.",
            view=Phase2StartView(), allowed_mentions=discord.AllowedMentions(users=True))
        await amt_api.melden("einreise", {"konto_id": str(row[0]), "name": "", "thread_id": str(inter.channel.id), "phase": 2,
                                          "beamter_id": str(inter.user.id), "beamter_name": inter.user.display_name})


class Phase2StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Einreise – Phase II starten", style=discord.ButtonStyle.success, custom_id=STARTEN_ID, emoji="🛂")
    async def starten(self, inter: discord.Interaction, button: discord.ui.Button):
        row = db_holen(inter.channel.id)
        if not row or inter.user.id != row[0]:
            await inter.response.send_message("Nur der Antragsteller kann Phase II starten.", ephemeral=True)
            return
        if row[1] != 2:
            await inter.response.send_message("Phase II ist nicht offen.", ephemeral=True)
            return
        await inter.response.send_message("**Phase II – im Charakter.** Wählen Sie zuerst Ihre Angaben und drücken Sie dann „Weiter“.",
                                          view=Phase2Auswahl(inter.channel.id, inter.message.id), ephemeral=True)


def panel_embed() -> discord.Embed:
    e = discord.Embed(
        title="Antrag auf Einreise",
        description=(
            "Wer im Imperium Germanicum ansässig werden und die Staatsbürgerschaft erlangen möchte, stellt bei der "
            "Kaiserlichen Zollverwaltung einen Antrag auf Einreise. Das Verfahren verläuft in zwei Phasen.\n\n"
            "**Phase I – außerhalb des Charakters (OOC)**\n"
            "Wählen Sie unten „Einreise beantragen“ und geben Sie Ihren Namen, Ihr Geburtsdatum (mindestens 16 Jahre), "
            "an, wie Sie auf uns aufmerksam geworden sind, was Sie sich bei uns vorstellen (Wunschposition) und eine "
            "Beschreibung Ihrer Rolle. Daraufhin wird ein Ticket eröffnet.\n\n"
            "**Phase II – im Charakter (IC)**\n"
            "Stimmt die Zollverwaltung zu, leitet sie Phase II ein. Sie starten diese im Ticket und geben Ihren "
            "IC-Namen, Ihre Vorgeschichte, Ihr IC-Geburtsdatum, Fraktion, Gesellschaftsschicht und Berufliche "
            "Zugehörigkeit an."),
        color=FARBE)
    e.set_footer(text="Imperium Germanicum · Kaiserliche Zollverwaltung")
    return e


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


class Ticket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelView())
        self.bot.add_view(SchliessenView())
        self.bot.add_view(PhaseIView())
        self.bot.add_view(Phase2StartView())


async def setup(bot):
    await bot.add_cog(Ticket(bot))
