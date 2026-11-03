"""Discord: OAuth2 (Code → Nutzer) und Abgleich der Mitgliedschaft auf dem Server per Bot-Token."""
import logging
import time
from urllib.parse import urlencode

import aiohttp

import config

API = "https://discord.com/api/v10"
ADMINISTRATOR = 1 << 3
UA = "DiscordBot (https://imperiumgermanicum.de, 1)"


class DiscordFehler(Exception):
    pass


def autorisieren_url(state):
    return "https://discord.com/oauth2/authorize?" + urlencode({
        "client_id": config.CLIENT_ID, "redirect_uri": config.REDIRECT_URI, "response_type": "code",
        "scope": "identify", "state": state, "prompt": "none"})


class Discord:
    def __init__(self):
        self.bot_token = config.env("DISCORD_TOKEN")
        self.secret = config.env("DISCORD_CLIENT_SECRET")
        self.session = None
        self._rollen = (0, [])   # (Zeitpunkt, Rollen wie von Discord)
        self._owner = None
        self._mitglieder = (0, [])

    async def start(self, _app=None):
        self.session = aiohttp.ClientSession(headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=15))

    async def stop(self, _app=None):
        await self.session.close()

    async def _bot(self, pfad):
        async with self.session.get(API + pfad, headers={"Authorization": "Bot " + self.bot_token}) as r:
            if r.status == 404:
                return None
            if r.status >= 400:
                raise DiscordFehler(f"{pfad}: HTTP {r.status}")
            return await r.json()

    async def nutzer_aus_code(self, code):
        daten = {"grant_type": "authorization_code", "code": code, "redirect_uri": config.REDIRECT_URI}
        auth = aiohttp.BasicAuth(str(config.CLIENT_ID), self.secret)
        async with self.session.post(API + "/oauth2/token", data=daten, auth=auth) as r:
            if r.status != 200:
                raise DiscordFehler(f"Token-Tausch: HTTP {r.status}")
            token = (await r.json())["access_token"]
        async with self.session.get(API + "/users/@me", headers={"Authorization": "Bearer " + token}) as r:
            if r.status != 200:
                raise DiscordFehler(f"Nutzerdaten: HTTP {r.status}")
            return await r.json()

    async def _rollen_roh(self):
        """Rollen des Servers wie von Discord, oberste zuerst (5 Minuten zwischengespeichert)."""
        zeit, liste = self._rollen
        if time.time() - zeit > 300 or not liste:
            liste = sorted(await self._bot(f"/guilds/{config.GUILD_ID}/roles") or [], key=lambda r: -r["position"])
            self._rollen = (time.time(), liste)
        return liste

    async def server_rollen(self):
        rollen = {r["id"]: {"name": r["name"], "permissions": int(r["permissions"]), "position": r["position"]}
                  for r in await self._rollen_roh()}
        if self._owner is None:
            self._owner = (await self._bot(f"/guilds/{config.GUILD_ID}") or {}).get("owner_id")
        return rollen

    async def rollen_liste(self):
        """Rollen des Servers für Auswahllisten, oberste zuerst; ohne @everyone, Bot-Rollen und Trenner („» ━━━『 … 』━━━ «“)."""
        return [{"id": r["id"], "name": r["name"]} for r in await self._rollen_roh()
                if r["id"] != str(config.GUILD_ID) and not r.get("managed") and "━" not in r["name"]]

    async def rollen_der_gruppe(self, gruppe):
        """IDs der Rollen unter einem Trenner (z. B. „Adelstitel“) bis zum nächsten Trenner."""
        out, drin = set(), False
        for r in await self._rollen_roh():
            if "━" in r["name"]:
                drin = gruppe in r["name"]
            elif drin and r["name"] != gruppe:   # die gleichnamige Sammelrolle gehört nicht dazu
                out.add(r["id"])
        return out

    async def mitglieder(self):
        """Alle Mitglieder (id, name, rollen), zwei Minuten zwischengespeichert."""
        zeit, liste = self._mitglieder
        if time.time() - zeit < 120:
            return liste
        liste, nach = [], "0"
        while True:
            seite = await self._bot(f"/guilds/{config.GUILD_ID}/members?limit=1000&after={nach}") or []
            for m in seite:
                if m["user"].get("bot"):
                    continue
                u = m["user"]
                liste.append({"id": u["id"], "name": m.get("nick") or u.get("global_name") or u["username"], "rollen": m["roles"]})
            if len(seite) < 1000:
                break
            nach = seite[-1]["user"]["id"]
        self._mitglieder = (time.time(), liste)
        return liste

    async def dm(self, nutzer_id, text):
        """Direktnachricht vom Bot; Fehler (z. B. DMs gesperrt) nur protokollieren."""
        auth = {"Authorization": "Bot " + self.bot_token}
        try:
            async with self.session.post(API + "/users/@me/channels", json={"recipient_id": nutzer_id}, headers=auth) as r:
                kanal = (await r.json())["id"]
            async with self.session.post(API + f"/channels/{kanal}/messages", json={"content": text[:1900]}, headers=auth) as r:
                if r.status >= 400:
                    raise DiscordFehler(f"HTTP {r.status}")
            return True
        except (DiscordFehler, KeyError, aiohttp.ClientError) as e:
            logging.getLogger("discord").warning("DM an %s fehlgeschlagen: %s", nutzer_id, e)
            return False

    async def konto(self, nutzer):
        """Baut aus Discord-Nutzer + Servermitgliedschaft die Kontodaten (id, name, avatar, rollen, mitglied, admin)."""
        mitglied = await self._bot(f"/guilds/{config.GUILD_ID}/members/{nutzer['id']}")
        rollen = await self.server_rollen()
        eigene = mitglied["roles"] if mitglied else []
        rechte = rollen.get(str(config.GUILD_ID), {}).get("permissions", 0)   # @everyone
        for rid in eigene:
            rechte |= rollen.get(rid, {}).get("permissions", 0)
        name = ((mitglied or {}).get("nick") or nutzer.get("global_name") or nutzer["username"])
        return {
            "id": nutzer["id"], "name": name, "avatar": nutzer.get("avatar"),
            "rollen": eigene, "mitglied": mitglied is not None,
            "admin": mitglied is not None and (bool(rechte & ADMINISTRATOR) or nutzer["id"] in (self._owner, config.KAISER_ID)),
        }

    async def konto_neu(self, konto_id):
        nutzer = await self._bot(f"/users/{konto_id}")
        if not nutzer:
            raise DiscordFehler("Nutzer nicht gefunden")
        return await self.konto(nutzer)
