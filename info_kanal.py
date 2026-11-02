"""Informationskanal: Richtlinien des Servers und „Zu welchem Zeitpunkt gilt die Rolle?“ als Embeds.

Die Website liest diese Embeds mit _build/regelwerk_holen.py aus (Titel und Aufbau daher nicht ändern:
Richtlinien als „**n.** Text“-Absätze, Rollenspiel als Absätze + Felder, Herausgeber als Autor).
Kanäle werden als „#name“ geschrieben und beim Senden in Erwähnungen umgewandelt.

Wiederhergestellt am 02.11.2026 aus _build/regelwerk.json der Website (Stand 26.10.2026).
"""
import re

import discord
from discord import app_commands
from discord.ext import commands

import config
import website

FARBE = discord.Colour.from_rgb(20, 33, 61)

RICHTLINIEN_TITEL = "Richtlinien des Servers"
RICHTLINIEN = [
    "Der Server ist Eigentum von Bastian Hüsch und Karl Benjamin Wollnik, jeweils zu Anteilen von 50 %.",
    "Neue Mitglieder im Rollenspiel haben eine allgemeine Probezeit von 2 Wochen.",
    "Beleidigungen, Hassrede, Extremismus und Sexismus werden nicht geduldet.",
    "Unerlaubte Werbung für andere Projekte ist nicht gestattet.",
    "Spam oder andere Arten von Aufdringlichkeiten werden nicht geduldet.",
    "Wir bestehen auf einen höflichen und respektvollen Umgang miteinander.",
    "Zuschauer oder Gastrollen sind von befristeten Probezeiten ausgenommen, für sie gilt immer die Regelung der Probezeit.",
    "Weitere Regeln können jederzeit hinzugefügt werden.",
    "Mitspieler, die gegen diese Regeln verstoßen, müssen mit einer Verwarnung oder mit dem Ausschluss aus der Community rechnen.",
]

ROLLENSPIEL_TITEL = "Zu welchem Zeitpunkt gilt die Rolle?"
ROLLENSPIEL_HERAUSGEBER = "Management des Rollenspiels"
ROLLENSPIEL_ABSAETZE = [
    "Jeder Teilnehmer des Rollenspiels übernimmt eine Rolle. Diese Rolle darf den tatsächlichen Namen der Person oder "
    "einen erfundenen Namen tragen; zudem darf sie der realen Persönlichkeit entsprechen oder davon abweichen.",
    "Wichtig ist, dass wir auf diesem Server die Rolle grundsätzlich nie vollständig ablegen. Die Rolle bleibt, wenn auch "
    "etwas gelockert, immer erhalten, um die Natur des Rollenspiels zu keiner Zeit abzulehnen.",
    "Um die Bereiche zu unterscheiden, gibt es Bereiche, in denen die Rolle etwas gelockert ist, und jene, in denen sie "
    "vollkommen gilt.",
]
ROLLENSPIEL_FELDER = [
    ("Bereiche mit gelockerter Rolle",
     "#klatsch-und-tratsch · #kurpfalz\n#Café · #Braustube · #Spielothek\n\n"
     "Hier sind die Rollen etwas gelockert, aber nie ganz abgelegt, es sei denn, ein geplantes Event schreibt die strenge "
     "Rolle vor. Für vollständig rollenfreie Kommunikation sind Gespräche privat zu führen."),
    ("Was „gelockert“ bedeutet",
     "Zur Begrüßung und zum Abschied wird klassisch die korrekte Anrede genannt. Im Verlauf des Gesprächs darf zum Du "
     "gewechselt und offen über private Themen des echten Lebens gesprochen werden. Die Rangstruktur des Rollenspiels und "
     "die Würde, die die jeweiligen Positionen mit sich bringen, sind dabei zu beachten."),
    ("Wichtig", "**Die Rollen werden nie ganz abgelegt.**"),
]


def kanaele_verlinken(guild, text):
    """„#name“ → <#id>, wenn es einen Kanal gibt, dessen Name (ohne Emoji-Präfix „…｜“) passt."""
    namen = {}
    for kanal in guild.channels:
        namen.setdefault(kanal.name.split("｜", 1)[-1].lower(), kanal.id)

    def ersetzen(m):
        kid = namen.get(m.group(1).lower())
        return f"<#{kid}>" if kid else m.group(0)
    return re.sub(r"#([\w\-äöüßÄÖÜé]+)", ersetzen, text)


def embeds(guild):
    richtlinien = discord.Embed(
        title=RICHTLINIEN_TITEL, colour=FARBE,
        description=kanaele_verlinken(guild, "\n\n".join(f"**{i}.** {t}" for i, t in enumerate(RICHTLINIEN, 1))))
    rollenspiel = discord.Embed(
        title=ROLLENSPIEL_TITEL, colour=FARBE,
        description=kanaele_verlinken(guild, "\n\n".join(ROLLENSPIEL_ABSAETZE)))
    rollenspiel.set_author(name=ROLLENSPIEL_HERAUSGEBER)
    for name, text in ROLLENSPIEL_FELDER:
        rollenspiel.add_field(name=name, value=kanaele_verlinken(guild, text), inline=False)
    return [richtlinien, rollenspiel]


class InfoKanal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="info-kanal", description="Informationskanal neu schreiben und die Website aktualisieren")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(website_aktualisieren="Regelwerk danach auf die Website übernehmen (Standard: ja)")
    async def info_kanal(self, inter: discord.Interaction, website_aktualisieren: bool = True):
        await inter.response.defer(ephemeral=True, thinking=True)
        kanal = self.bot.get_channel(config.INFO_KANAL) or await self.bot.fetch_channel(config.INFO_KANAL)

        # Vorhandene Bot-Nachrichten mit diesen Titeln bearbeiten statt neu zu posten
        vorhanden = {}
        async for m in kanal.history(limit=50):
            if m.author.id == self.bot.user.id:
                for e in m.embeds:
                    if e.title:
                        vorhanden[e.title] = m
        neu = 0
        for embed in embeds(inter.guild):
            if embed.title in vorhanden:
                # Nur das Text-Embed ersetzen, Banner-Embed (ohne Titel) davor bleibt erhalten
                m = vorhanden[embed.title]
                await m.edit(embeds=[embed if e.title == embed.title else e for e in m.embeds])
            else:
                await kanal.send(embed=embed)
                neu += 1
        antwort = f"Informationskanal aktualisiert ({neu} neu, {2 - neu} bearbeitet)."

        if website_aktualisieren:
            ok, log = await website.regelwerk_holen()
            if ok:
                ok, log = await website.deploy()
            antwort += "\nWebsite: " + ("aktualisiert." if ok else f"Fehler:\n```\n{log[-1500:]}\n```")
        await inter.followup.send(antwort, ephemeral=True)


async def setup(bot):
    await bot.add_cog(InfoKanal(bot))
