"""Einstellungen des Imperium-Dienstes. Geheimnisse stehen in /root/.env (DISCORD_TOKEN, DISCORD_CLIENT_SECRET)."""
import os

HIER = os.path.dirname(os.path.abspath(__file__))

SITE_URL = "https://imperiumgermanicum.de"
WEBROOT = "/var/www/imperium"
WEBSITE_DIR = "/root/imperium_germanicum"   # Repo der Website (Bilderliste _build/bilder.json)
DB = os.path.join(HIER, "daten", "dienst.db")
HOST, PORT = "127.0.0.1", 8090

GUILD_ID = 1522685223014371479
KAISER_ID = "463089934765391872"        # Der Kaiser: darf immer bearbeiten (Karte, Organigramme)
CLIENT_ID = 1560287961189322752          # Anwendung „Imperium Germanicum“ (gleich dem Bot)
REDIRECT_URI = SITE_URL + "/anmelden/rueckruf"   # so im Developer Portal eingetragen

SITZUNG_COOKIE = "ig_sitzung"
SITZUNG_TAGE = 30
STATE_COOKIE = "ig_anmeldung"
STATE_MINUTEN = 10
ROLLEN_AKTUALISIEREN_MIN = 10   # Rollen werden höchstens so oft bei Discord nachgefragt

ENV_DATEI = "/root/.env"


def env(name):
    if os.environ.get(name):
        return os.environ[name]
    with open(ENV_DATEI, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{name} fehlt in {ENV_DATEI}")
