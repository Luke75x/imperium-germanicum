"""Einstellungen des Imperium-Bots. Geheimnisse stehen nicht hier, sondern in /root/.env."""
import os

GUILD_ID = 1522685223014371479
INFO_KANAL = 1523117025952661597

# Reichsgesetzblatt (Discord-Forum) und der Kaiser, der neue Einträge per DM bestätigt.
# Solange einer der Werte None ist, ist das Modul Gesetzblatt abgeschaltet.
GESETZBLATT_FORUM = 1561866155273228359  # 📜｜reichsgesetzblatt
KAISER_ID = 463089934765391872

# Kaiserliches Zollamt (Kanal 1537221044648022036) mit seinen Threads
ZOLLVERWALTUNG_ROLLE = 1557187375006875758  # darf /einbürgern
THREAD_VISEN = [1565505165048553503,        # Erteilte Aufenthaltsvisen (Beitritt), Zollamt
                1565505917829652613]        # dasselbe als Thread in der Einwanderungsbehörde
EINWANDERER_ROLLE = 1522930374332780614     # Rolle für neu Beigetretene
AUDIENZ_KANAL = 1523025487847227402         # 🤴🏼｜Audienzzimmer (Sprachkanal), Beitritt des Kaisers löst die DM aus
NEWS_KANAL = 1522995542047723581            # 📰｜news, dort erscheint die Generalaudienz
# Reichstag: wer /antrag nutzen darf (Reichstag, Abgeordneter, Präsidium, Landesherr), Rest im Imperium-Dienst
REICHSTAG_ROLLEN = {1522700666856800447, 1528931629819494454, 1522701497413144776, 1522701576295415969}
SERVERANTRAG_KANAL = 1567217562477928528     # 📄｜anträge (Server- und RP-Leitung): Serverantrag mit Akzeptieren/Abweisen
# Haft (haft.py): Befugte, Haftrollen, Trenner „Auszeichnungen“ (alles bis einschließlich bleibt bei /haft) und Log-Thread
HAFT_BEFUGTE_ROLLE = 1522699091279216710    # Reichsgerichtshof: /u-haft und /haft
KRS_BEFUGTE_ROLLE = 1526343577481904379     # Kaiserliches Reichssicherheitsamt: /krs-haft
HAFT_ROLLE = 1562930209622069298            # Häftling
KRS_HAFT_ROLLE = 1564696460258316429        # KRS-Häftling
HAFT_BEHALTEN_BIS = 1560326270229938196     # » ━━━『 Auszeichnungen 』━━━ «
HAFT_LOG = 1567218532691877989              # Thread „RP-Ereignisse: Haft- und Untersuchungshaft“
# Newsflash (newsflash.py): Prüf-Thread der Leitung, Rollen Landesherr / Staatsbürger
NEWSFLASH_PRUEFUNG = 1567221657121067108    # Thread „RP-Ereignisse: Newsflash (Filter- und Staatsbürger)“
LANDESHERR_ROLLE = 1522701576295415969
STAATSBUERGER_ROLLE = 1522929940885143683
TICKET_KANAL = 1523025911493038203          # 🛂｜einwanderungsbehörde, Panel 1565507299345436713
THREAD_ABGELAUFEN = 1565505112888058019     # Abgelaufene Aufenthaltsvisen (Austritt)
THREAD_EINBUERGERUNGEN = 1565505189132243026  # Erfolgreiche Einbürgerungen
# Rollen bei der Einbürgerung: Fraktionen-/Imperium-Trenner, Gefolgschaft, Staatsbürger
EINBUERGERUNG_ROLLEN = [1560633153243058226, 1522931909959880844, 1522931993661407363,
                        1560633154480377956, 1522929767706398871, 1522929940885143683]
ZOLL_BILD_VISUM = ("https://cdn-longterm.mee6.xyz/plugins/welcome/images/1522685223014371479/"
                   "e968ca8a0aa5365d1e86839ab23aefbd875498b2d0d46c9aa301fd55b4769142.png")
ZOLL_BILD_ABGELAUFEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sicherung", "zoll.png")

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
