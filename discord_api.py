"""Discord: OAuth2 (Code → Nutzer) und Abgleich der Mitgliedschaft auf dem Server per Bot-Token."""
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
        self._rollen = (0, {})   # (Zeitpunkt, {rollen_id: {name, permissions, position}})
        self._owner = None

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

    async def server_rollen(self):
        zeit, rollen = self._rollen
        if time.time() - zeit > 300 or not rollen:
            liste = await self._bot(f"/guilds/{config.GUILD_ID}/roles") or []
            rollen = {r["id"]: {"name": r["name"], "permissions": int(r["permissions"]), "position": r["position"]}
                      for r in liste}
            self._rollen = (time.time(), rollen)
        if self._owner is None:
            self._owner = (await self._bot(f"/guilds/{config.GUILD_ID}") or {}).get("owner_id")
        return rollen

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
            "admin": mitglied is not None and (bool(rechte & ADMINISTRATOR) or nutzer["id"] == self._owner),
        }

    async def konto_neu(self, konto_id):
        nutzer = await self._bot(f"/users/{konto_id}")
        if not nutzer:
            raise DiscordFehler("Nutzer nicht gefunden")
        return await self.konto(nutzer)
