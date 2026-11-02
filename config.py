"""Einstellungen des Imperium-Bots. Geheimnisse stehen nicht hier, sondern in /root/.env."""
import os

GUILD_ID = 1522685223014371479
INFO_KANAL = 1523117025952661597

# Reichsgesetzblatt (Discord-Forum) und der Kaiser, der neue Einträge per DM bestätigt.
# Noch unbekannt – solange None, ist das Modul Gesetzblatt abgeschaltet.
GESETZBLATT_FORUM = 1561866155273228359  # 📜｜reichsgesetzblatt
KAISER_ID = None

# Website-Repo und Deploy (siehe /root/imperium_germanicum/README.md)
WEBSITE_DIR = "/root/imperium_germanicum"
VENV_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin")
ENV_DATEI = "/root/.env"


def env(name, default=None):
    """Liest einen Wert aus der Umgebung oder aus /root/.env."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        with open(ENV_DATEI, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return default
