"""/einstellen person institution dienstgrad: Landesherren stellen Personen ein bzw. befördern sie (Dienstgradstrukturen in dienstgrade.py).

- Landesherren (und der Kaiser) dürfen bis einschließlich OF-5 direkt einstellen/befördern; ab OF-6 geht ein Antrag in den
  Genehmigungs-Thread, den nur der Kaiser mit „Genehmigen“/„Ablehnen“ entscheidet.
- Eine Person ohne Dienstgrad der Institution wird eingestellt (Institutionsrolle + „Abteilungen“ + Dienstgrad + Gruppenrolle),
  mit niedrigerem Dienstgrad wird sie befördert (alte Dienstgrad-Rollen der Institution entfallen). Herabstufungen gibt es hier nicht.
- Jede ausgeführte Einstellung/Beförderung erscheint als Log im Thread PERSONAL_LOG.
Die Knöpfe tragen alle Angaben in der custom_id (kein Speicher nötig, auch nach Neustart gültig).
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import dienstgrade as dg

log = logging.getLogger("imperium-bot.einstellen")
PREFIX = "einstellen:"
FARBE_OK, FARBE_NEIN, FARBE_OFFEN = 0x2F6B3A, 0xA3261B, 0xE0A030
ALLE_RANGROLLEN = {rid for raenge in dg.RAENGE.values() for _, _, rid in raenge}
GRUPPEN_IDS = set(dg.GRUPPENROLLEN.values())
INSTITUTIONS_IDS = {rid for _, rid in dg.INSTITUTIONEN.values()}


def ist_landesherr(user: discord.Member) -> bool:
    return user.id == config.KAISER_ID or any(r.id == config.LANDESHERR_ROLLE for r in user.roles)


def aktueller_rang(member: discord.Member, schluessel: str):
    """Index des höchsten Dienstgrads dieser Institution, den die Person trägt (oder None)."""
    ids = {r.id for r in member.roles}
    treffer = [i for i, (_, _, rid) in enumerate(dg.RAENGE[schluessel]) if rid in ids]
    return max(treffer) if treffer else None


def andere_institution(member: discord.Member, schluessel: str):
    """Name einer anderen Institution, zu der die Person gehört (Institutionsrolle oder ausschließlich dort vergebener Dienstgrad)."""
    ids = {r.id for r in member.roles}
    eigene = {rid for _, _, rid in dg.RAENGE[schluessel]}
    for k, (name, rid) in dg.INSTITUTIONEN.items():
        if k == schluessel:
            continue
        if rid in ids and rid != dg.INSTITUTIONEN[schluessel][1]:
            return name
        if any(r in ids and r not in eigene for _, _, r in dg.RAENGE[k]):
            return name
    return None


async def anwenden(guild: discord.Guild, ziel: discord.Member, schluessel: str, index: int, grund: str):
    """Setzt Dienstgrad und Rollen. Gibt (Fehlertext oder None, vorheriger Index oder None) zurück."""
    stufe, name, rid = dg.RAENGE[schluessel][index]
    alt = aktueller_rang(ziel, schluessel)
    if alt is not None and alt >= index:
        return f"{ziel.mention} hat bereits den Dienstgrad {dg.bezeichnung(schluessel, alt)} oder höher.", alt
    rolle = guild.get_role(rid)
    if rolle is None:
        return f"Die Rolle für {name} fehlt auf dem Server.", alt
    eigene = {rid_ for _, _, rid_ in dg.RAENGE[schluessel]}
    behalten = [r for r in ziel.roles if r.id not in eigene and r.id not in GRUPPEN_IDS and not r.is_default()]
    neu = behalten + [rolle]
    # Gruppenrollen: genau die, die zu den verbleibenden Dienstgraden passen
    gruppen = {dg.gruppe(stufe)}
    ids = {r.id for r in neu}
    for k, raenge in dg.RAENGE.items():
        gruppen |= {dg.gruppe(s) for s, _, r in raenge if r in ids}
    neu += [guild.get_role(dg.GRUPPENROLLEN[g]) for g in gruppen if guild.get_role(dg.GRUPPENROLLEN[g])]
    for rid_ in (dg.INSTITUTIONEN[schluessel][1], dg.SAMMELROLLE_ABTEILUNGEN):
        r = guild.get_role(rid_)
        if r and r not in neu:
            neu.append(r)
    await ziel.edit(roles=neu, reason=grund)
    return None, alt


class Einstellen(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def kanal(self, kanal_id):
        return self.bot.get_channel(kanal_id) or await self.bot.fetch_channel(kanal_id)

    async def log_senden(self, ziel, schluessel, index, alt, durch, genehmigt_von=None):
        institution = dg.INSTITUTIONEN[schluessel][0]
        art = "Beförderung" if alt is not None else "Einstellung"
        e = discord.Embed(title=f"{art}: {institution}", color=FARBE_OK, timestamp=discord.utils.utcnow())
        e.add_field(name="Person", value=f"{ziel.mention} ({ziel.id})", inline=False)
        e.add_field(name="Dienstgrad", value=(f"{dg.bezeichnung(schluessel, alt)} → " if alt is not None else "") + f"**{dg.bezeichnung(schluessel, index)}**", inline=False)
        e.add_field(name="Durch", value=durch.mention, inline=True)
        if genehmigt_von:
            e.add_field(name="Genehmigt durch", value=genehmigt_von.mention, inline=True)
        try:
            await (await self.kanal(config.PERSONAL_LOG)).send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Personal-Log konnte nicht geschrieben werden")

    # ---------------------------------------------------------------- Befehl

    @app_commands.command(name="einstellen", description="Eine Person in eine Institution einstellen oder befördern")
    @app_commands.guild_only()
    @app_commands.describe(person="Die Person", institution="Institution (bestimmt die Dienstgradstruktur)", dienstgrad="Dienstgrad nach der Tabelle der Institution")
    @app_commands.choices(institution=[app_commands.Choice(name=n, value=k) for k, (n, _) in dg.INSTITUTIONEN.items()])
    async def einstellen(self, inter: discord.Interaction, person: discord.Member, institution: app_commands.Choice[str], dienstgrad: str):
        if not ist_landesherr(inter.user):
            await inter.response.send_message("Einstellen und Befördern dürfen nur Landesherren.", ephemeral=True)
            return
        schluessel = institution.value
        index = self.rang_index(schluessel, dienstgrad)
        if index is None:
            await inter.response.send_message("Diesen Dienstgrad gibt es bei der Institution nicht. Bitte aus der Liste wählen.", ephemeral=True)
            return
        if person.bot or (person.id == inter.user.id and inter.user.id != config.KAISER_ID):
            await inter.response.send_message("Diese Person kann nicht eingestellt werden (Bots und man selbst).", ephemeral=True)
            return
        fehler = self.pruefen(inter.user, person, schluessel, index)
        if fehler:
            await inter.response.send_message(fehler, ephemeral=True)
            return
        stufe = dg.RAENGE[schluessel][index][0]
        bezeichnung = dg.bezeichnung(schluessel, index)

        if dg.braucht_genehmigung(stufe) and inter.user.id != config.KAISER_ID:
            await inter.response.defer(ephemeral=True)
            alt = aktueller_rang(person, schluessel)
            e = discord.Embed(title=f"Genehmigung: {'Beförderung' if alt is not None else 'Einstellung'} – {dg.INSTITUTIONEN[schluessel][0]}",
                              color=FARBE_OFFEN, timestamp=discord.utils.utcnow(),
                              description=f"{inter.user.mention} beantragt für {person.mention} den Dienstgrad **{bezeichnung}**.\nAb OF-{dg.KAISER_AB} entscheidet der Kaiser.")
            if alt is not None:
                e.add_field(name="Bisheriger Dienstgrad", value=dg.bezeichnung(schluessel, alt))
            v = discord.ui.View(timeout=None)
            daten = f"{person.id}:{schluessel}:{index}:{inter.user.id}"
            v.add_item(discord.ui.Button(label="Genehmigen", style=discord.ButtonStyle.success, custom_id=f"{PREFIX}ja:{daten}"))
            v.add_item(discord.ui.Button(label="Ablehnen", style=discord.ButtonStyle.danger, custom_id=f"{PREFIX}nein:{daten}"))
            await (await self.kanal(config.GENEHMIGUNG_KANAL)).send(content=f"<@{config.KAISER_ID}>", embed=e, view=v,
                                                                     allowed_mentions=discord.AllowedMentions(users=[discord.Object(config.KAISER_ID)]))
            await inter.followup.send(f"Der Dienstgrad **{bezeichnung}** liegt ab OF-{dg.KAISER_AB} nicht in deiner Hand: Der Antrag liegt dem Kaiser zur Genehmigung vor. "
                                      "Du bekommst eine Nachricht, sobald er entschieden hat.", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)
        try:
            text, alt = await anwenden(inter.guild, person, schluessel, index, f"/einstellen durch {inter.user}")
        except discord.HTTPException as e:
            log.exception("Rollenänderung fehlgeschlagen")
            await inter.followup.send(f"Die Rollen konnten nicht geändert werden ({e.status}).", ephemeral=True)
            return
        if text:
            await inter.followup.send(text, ephemeral=True)
            return
        await self.log_senden(person, schluessel, index, alt, inter.user)
        await inter.followup.send(f"{person.mention} wurde {'befördert' if alt is not None else 'eingestellt'}: **{bezeichnung}** ({dg.INSTITUTIONEN[schluessel][0]}).", ephemeral=True)

    @einstellen.autocomplete("dienstgrad")
    async def dienstgrad_vorschlaege(self, inter: discord.Interaction, eingabe: str):
        schluessel = getattr(inter.namespace, "institution", None)
        if schluessel not in dg.RAENGE:
            return []
        low = eingabe.casefold()
        return [app_commands.Choice(name=dg.bezeichnung(schluessel, i), value=str(i))
                for i in range(len(dg.RAENGE[schluessel])) if low in dg.bezeichnung(schluessel, i).casefold()][:25]

    @staticmethod
    def rang_index(schluessel: str, eingabe: str):
        raenge = dg.RAENGE[schluessel]
        if eingabe.isdigit() and int(eingabe) < len(raenge):
            return int(eingabe)
        low = eingabe.casefold().strip()
        for i in range(len(raenge)):
            if low in (dg.bezeichnung(schluessel, i).casefold(), raenge[i][1].casefold()):
                return i
        return None

    @staticmethod
    def pruefen(durch: discord.Member, ziel: discord.Member, schluessel: str, index: int):
        """Fehlertext, wenn die Einstellung/Beförderung nicht möglich ist."""
        alt = aktueller_rang(ziel, schluessel)
        if alt is not None and alt >= index:
            return f"{ziel.mention} hat bereits den Dienstgrad {dg.bezeichnung(schluessel, alt)} oder höher. Herabstufungen sind mit /einstellen nicht möglich."
        if alt is None and durch.id != config.KAISER_ID:
            anderswo = andere_institution(ziel, schluessel)
            if anderswo:
                return f"{ziel.mention} gehört bereits zu {anderswo}. Eine Versetzung nimmt der Kaiser vor."
        return None

    # ---------------------------------------------------------------- Genehmigung durch den Kaiser

    @commands.Cog.listener()
    async def on_interaction(self, inter: discord.Interaction):
        cid = (inter.data or {}).get("custom_id", "")
        if inter.type != discord.InteractionType.component or not cid.startswith(PREFIX):
            return
        aktion, _, rest = cid[len(PREFIX):].partition(":")
        try:
            ziel_id, schluessel, index, antragsteller_id = rest.split(":")
            ziel_id, index, antragsteller_id = int(ziel_id), int(index), int(antragsteller_id)
            dg.RAENGE[schluessel][index]
        except (ValueError, KeyError, IndexError):
            return
        if inter.user.id != config.KAISER_ID:
            await inter.response.send_message("Darüber entscheidet der Kaiser.", ephemeral=True)
            return
        await inter.response.defer()
        embed = inter.message.embeds[0]
        antragsteller = inter.guild.get_member(antragsteller_id) or await self.bot.fetch_user(antragsteller_id)
        bezeichnung = dg.bezeichnung(schluessel, index)
        if aktion == "nein":
            stand, farbe, ergebnis = "❌ Abgelehnt", FARBE_NEIN, f"Dein Antrag auf den Dienstgrad **{bezeichnung}** wurde vom Kaiser **abgelehnt**."
        else:
            ziel = inter.guild.get_member(ziel_id)
            if ziel is None:
                stand, farbe, ergebnis = "⚠ Person nicht mehr auf dem Server", FARBE_NEIN, "Die Person ist nicht mehr auf dem Server; der Antrag wurde nicht ausgeführt."
            else:
                try:
                    text, alt = await anwenden(inter.guild, ziel, schluessel, index, f"/einstellen, genehmigt durch {inter.user}")
                except discord.HTTPException as e:
                    log.exception("Rollenänderung fehlgeschlagen")
                    text, alt = f"Die Rollen konnten nicht geändert werden ({e.status}).", None
                if text:
                    stand, farbe, ergebnis = f"⚠ Nicht ausgeführt: {text}", FARBE_NEIN, f"Dein Antrag wurde genehmigt, konnte aber nicht ausgeführt werden: {text}"
                else:
                    stand, farbe = "✅ Genehmigt und ausgeführt", FARBE_OK
                    ergebnis = f"Dein Antrag wurde vom Kaiser **genehmigt**: {ziel.mention} ist jetzt **{bezeichnung}**."
                    await self.log_senden(ziel, schluessel, index, alt, antragsteller if isinstance(antragsteller, discord.Member) else inter.user, genehmigt_von=inter.user)
        embed.color = farbe
        embed.add_field(name="Entscheidung", value=f"{stand} von {inter.user.mention}", inline=False)
        await inter.message.edit(embed=embed, view=None)
        try:
            await antragsteller.send(ergebnis)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Einstellen(bot))
