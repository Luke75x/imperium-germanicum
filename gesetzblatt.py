"""Reichsgesetzblatt: neuer Beitrag im Forum → DM an den Kaiser → nach Bestätigung auf die Website.

Ablauf (vgl. _build/gesetzblatt.py der Website): Der Bot lädt Text und Anhänge des Eröffnungsbeitrags in einen
Ordner mit eintrag.json, ruft _build/gesetzblatt.py auf und danach deploy.sh.
Die Knöpfe in der DM tragen die Thread-ID in der custom_id und funktionieren daher auch nach einem Neustart.

Abgeschaltet, solange GESETZBLATT_FORUM oder KAISER_ID in config.py fehlen.
"""
import json
import re
import tempfile

import discord
from discord.ext import commands

import config
import website

PREFIX = "gesetzblatt:"
URL = re.compile(r"https?://\S+")


class Gesetzblatt(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent_id != config.GESETZBLATT_FORUM:
            return
        kaiser = await self.bot.fetch_user(config.KAISER_ID)
        knoepfe = discord.ui.View(timeout=None)
        knoepfe.add_item(discord.ui.Button(label="Auf die Website", style=discord.ButtonStyle.success,
                                           custom_id=f"{PREFIX}ja:{thread.id}"))
        knoepfe.add_item(discord.ui.Button(label="Nicht aufnehmen", style=discord.ButtonStyle.secondary,
                                           custom_id=f"{PREFIX}nein:{thread.id}"))
        await kaiser.send(f"Neuer Eintrag im Reichsgesetzblatt: **{thread.name}**\n{thread.jump_url}\n"
                          "Soll er unter „Neue Erlasse und Gesetze“ auf der Website erscheinen?", view=knoepfe)

    @commands.Cog.listener()
    async def on_interaction(self, inter: discord.Interaction):
        cid = (inter.data or {}).get("custom_id", "")
        if inter.type != discord.InteractionType.component or not cid.startswith(PREFIX):
            return
        if inter.user.id != config.KAISER_ID:
            await inter.response.send_message("Nur der Kaiser kann das entscheiden.", ephemeral=True)
            return
        aktion, tid = cid[len(PREFIX):].split(":")
        if aktion == "nein":
            await inter.response.edit_message(content=inter.message.content + "\n\n✗ Nicht aufgenommen.", view=None)
            return

        await inter.response.edit_message(content=inter.message.content + "\n\n… wird aufgenommen.", view=None)
        ok, log = await self.aufnehmen(int(tid))
        ergebnis = "✓ Auf der Website veröffentlicht." if ok else f"✗ Fehler:\n```\n{log[-1500:]}\n```"
        await inter.edit_original_response(content=inter.message.content.replace("… wird aufgenommen.", ergebnis))

    async def aufnehmen(self, tid):
        thread = self.bot.get_channel(tid) or await self.bot.fetch_channel(tid)
        start = await thread.fetch_message(thread.id)
        tags = [t.name for t in thread.applied_tags]
        with tempfile.TemporaryDirectory(prefix="gesetzblatt-") as ordner:
            dateien = []
            for a in start.attachments:
                await a.save(f"{ordner}/{a.filename}")
                dateien.append(a.filename)
            eintrag = {
                "id": str(thread.id),
                "titel": thread.name,
                "art": tags[0] if tags else "Erlass",
                "text": URL.sub("", start.content).strip(),
                "datum": thread.created_at.date().isoformat(),
                "dateien": dateien,
                "links": URL.findall(start.content),
            }
            with open(f"{ordner}/eintrag.json", "w", encoding="utf-8") as fh:
                json.dump(eintrag, fh, ensure_ascii=False)
            ok, log = await website.gesetzblatt_aufnehmen(ordner)
        if ok:
            ok, log = await website.deploy()
        return ok, log


async def setup(bot):
    if config.GESETZBLATT_FORUM and config.KAISER_ID:
        await bot.add_cog(Gesetzblatt(bot))
