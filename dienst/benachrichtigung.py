"""Benachrichtigungen des Bots (Discord-DM) nach den Einstellungen jedes Nutzers (Profil im Schatzamt: /schatzamt/profil/#benachrichtigungen).

* ARTEN: jede Art von Nachricht mit Standard (an/aus). Gespeichert in nutzer_einstellungen (post.einstellung) unter „dm_<art>“;
  die interne Post nutzt weiter ihren alten Schlüssel „dm“. „rp“ (Mitteilungen der RP-Leitung) ist Pflicht und lässt sich nicht abschalten.
* discord_api.Discord.dm(nutzer_id, text, art=…) fragt hier nach (pruefen): „senden“, „aus“ oder „spaeter“ (Ruhezeit) – dann wird die
  Nachricht in bn_warteschlange vorgemerkt und nach der Ruhezeit verschickt.
* Zahlungseingang/Abbuchung: geld.NACH_BUCHUNG ruft buchung() in derselben Transaktion auf; die Nachricht geht in die Warteschlange
  (wird eine Buchung zurückgerollt – z. B. die Vorschau der RP-Leitung –, verschwindet auch die Nachricht).
* Hintergrund (alle 20 s): Warteschlange abarbeiten; einmal täglich zu Beginn der Änderungsperiode die Landesherren an den Etat erinnern.
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import amt
import config
import geld

log = logging.getLogger("benachrichtigung")
ZONE = ZoneInfo("Europe/Berlin")
CON = None

# (Schlüssel, Titel, Beschreibung, Standard an?, Pflicht?, Gruppe)
ARTEN = [
    ("eingang", "Zahlungseingang", "Geld geht auf dein Privat- oder Gewerbekonto ein (Überweisung, Erstattung, Entschädigung …).", False, False, "Mein Geld"),
    ("abgang", "Abbuchung durch andere", "Geld wird ohne dein Zutun abgebucht: Pfändung, Korrektur, Eingriffe (Steuern und Besitzkosten haben eigene Nachrichten).", True, False, "Mein Geld"),
    ("gehalt", "Gehalt", "Lohnlauf: Gehalt gezahlt, einbehalten oder nachgezahlt.", True, False, "Mein Geld"),
    ("steuer", "Steuerbescheide", "Ein Bescheid wurde für dich festgesetzt.", True, False, "Mein Geld"),
    ("besitz", "Kosten für Besitz", "Monatliche Kosten deiner Fahrzeuge und Immobilien, Pfändung.", True, False, "Mein Geld"),
    ("bankkarte", "Bankkarte", "Deine Karte wurde nach zu vielen falschen PIN-Eingaben gesperrt.", True, False, "Mein Geld"),
    ("post", "Interne Post", "Neue Nachricht in deinem Postfach der Reichsverwaltung.", False, False, "Dienst"),
    ("krise", "Krise im Teilstaat", "Eine Krise in deinem Teilstaat verlangt eine Reaktion (nur Landesherren).", True, False, "Teilstaat"),
    ("notlage", "Haushaltsnotlage", "Eine Kasse deines Teilstaats ist im Minus oder die Notlage endet.", True, False, "Teilstaat"),
    ("vollmacht", "Vollmachten", "Ein Regent hat dich für seinen Teilstaat bevollmächtigt oder die Vollmacht widerrufen.", True, False, "Teilstaat"),
    ("etat", "Änderungsperiode", "Erinnerung zu Beginn der Änderungsperiode, den Etat einzureichen.", True, False, "Teilstaat"),
    ("rp", "Mitteilungen der RP-Leitung", "Eingriffe der RP-Leitung in deine Konten. Lässt sich nicht abschalten.", True, True, "Pflicht"),
]
ART = {a[0]: a for a in ARTEN}
OHNE_EINGANG = {"gehalt"}                                    # hat eine eigene Nachricht
OHNE_ABGANG = {"lohnsteuer", "sozialabgabe", "ueberweisung", "steuer", "gebuehr", "privatsteuer", "privatkosten", "privatkauf", "erwerbsteuer"}   # eigene Nachricht (Gehalt, Bescheid, Besitz) bzw. selbst veranlasst

SCHEMA = """
CREATE TABLE IF NOT EXISTS bn_warteschlange (id INTEGER PRIMARY KEY AUTOINCREMENT, konto_id TEXT NOT NULL, art TEXT NOT NULL, text TEXT NOT NULL, zeit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bn_erinnert (art TEXT NOT NULL, periode TEXT NOT NULL, konto_id TEXT NOT NULL, PRIMARY KEY (art, periode, konto_id));
"""


def _schluessel(art):
    return "dm" if art == "post" else "dm_" + art


def einstellung(con, kid, schluessel, standard=""):
    import post
    return post.einstellung(con, kid, schluessel, standard)


def an(con, kid, art):
    a = ART.get(art)
    if not a:
        return True
    if a[4]:
        return True
    return einstellung(con, kid, _schluessel(art), "1" if a[3] else "0") == "1"


def ruhezeit(con, kid):
    """(von, bis) in vollen Stunden oder None."""
    v, b = einstellung(con, kid, "dm_ruhe_von"), einstellung(con, kid, "dm_ruhe_bis")
    if v.isdigit() and b.isdigit() and int(v) != int(b):
        return int(v) % 24, int(b) % 24
    return None


def in_ruhezeit(con, kid, jetzt=None):
    r = ruhezeit(con, kid)
    if not r:
        return False
    h = (jetzt or datetime.now(ZONE)).hour
    v, b = r
    return v <= h < b if v < b else (h >= v or h < b)


def pruefen(kid, art):
    """'senden' | 'aus' | 'spaeter' (Ruhezeit)."""
    if CON is None or not art or not kid:
        return "senden"
    try:
        if not an(CON, kid, art):
            return "aus"
        return "spaeter" if in_ruhezeit(CON, kid) else "senden"
    except Exception as e:   # Einstellungen dürfen eine Nachricht nie verhindern
        log.warning("Benachrichtigung prüfen: %s", e)
        return "senden"


def vormerken(con, kid, art, text, commit=True):
    con.execute("INSERT INTO bn_warteschlange (konto_id, art, text, zeit) VALUES (?,?,?,?)", (str(kid), art, text[:1900], int(time.time())))
    if commit:
        con.commit()


def melden(con, kid, art, text):
    """Nachricht in der laufenden Transaktion vormerken, wenn der Nutzer sie haben will (Versand durch den Hintergrund, auch nach Ruhezeit)."""
    if kid and an(con, kid, art):
        vormerken(con, kid, art, text, commit=False)


# ---------------------------------------------------------------- Buchungen (geld.NACH_BUCHUNG)

def buchung(con, kv, ka, betrag, art, zweck, k):
    link = f"{config.SITE_URL}/schatzamt/konto/"
    autor = (k or {}).get("id") if k else None
    eigene_umbuchung = bool(kv and ka and kv["inhaber_id"] and kv["inhaber_id"] == ka["inhaber_id"])
    if ka and ka["art"] in ("privat", "gewerbe") and ka["inhaber_id"] and art not in OHNE_EINGANG and not eigene_umbuchung:
        kid = ka["inhaber_id"]
        ab = einstellung(con, kid, "dm_eingang_ab", "0")
        ab = int(ab) * 100 if ab.isdigit() else 0
        if betrag >= ab:
            von = kv["name"] if kv else "außerhalb"
            melden(con, kid, "eingang", f"💶 Zahlungseingang: +{geld.mark(betrag)} auf „{ka['name']}“ von {von}" + (f" – {zweck}" if zweck else "") + f"\n{link}")
    if kv and kv["art"] in ("privat", "gewerbe") and kv["inhaber_id"] and art not in OHNE_ABGANG and autor != kv["inhaber_id"]:
        an_ = ka["name"] if ka else "außerhalb"
        melden(con, kv["inhaber_id"], "abgang", f"💸 Abbuchung: −{geld.mark(betrag)} von „{kv['name']}“ an {an_} ({geld.BUCHUNGSART.get(art, art)})"
               + (f" – {zweck}" if zweck else "") + f"\n{link}")


# ---------------------------------------------------------------- Hintergrund

async def _abarbeiten(app):
    con = app["db"]
    jetzt = datetime.now(ZONE)
    for r in con.execute("SELECT * FROM bn_warteschlange ORDER BY id LIMIT 40").fetchall():
        if r["art"] != "test" and in_ruhezeit(con, r["konto_id"], jetzt):
            continue
        con.execute("DELETE FROM bn_warteschlange WHERE id=?", (r["id"],))
        con.commit()
        await app["discord"].dm(r["konto_id"], r["text"])   # ohne art: schon geprüft


async def _etat_erinnern(app):
    """Einmal je Änderungsperiode (ab ihrem ersten Tag, 9 Uhr) alle Regenten erinnern."""
    import etatplan
    import karte
    jetzt = datetime.now(ZONE)
    von, bis = etatplan.aenderungsperiode(jetzt.date())
    if not (von <= jetzt.date() <= bis) or jetzt.hour < 9:
        return
    con = app["db"]
    periode = jetzt.strftime("%Y-%m")
    for z in con.execute("SELECT * FROM konten WHERE mitglied=1").fetchall():
        k = dict(z)
        k["rollen"] = json.loads(k["rollen"] or "[]")
        k["mitglied"], k["admin"] = bool(k["mitglied"]), bool(k["admin"])
        rollen = set(k["rollen"])
        if not (karte.ROLLE_LANDESHERR in rollen or rollen & set(karte.ROLLEN_AEMTER) or amt.ROLLE_KANZLER in rollen):
            continue
        if con.execute("SELECT 1 FROM bn_erinnert WHERE art='etat' AND periode=? AND konto_id=?", (periode, k["id"])).fetchone():
            continue
        try:
            kassen = geld.regierte_staatskassen(con, k)
        except Exception:
            continue
        con.execute("INSERT OR IGNORE INTO bn_erinnert (art, periode, konto_id) VALUES ('etat',?,?)", (periode, k["id"]))
        con.commit()
        if not kassen or not an(con, k["id"], "etat"):
            continue
        namen = ", ".join(r["name"].replace("Staatskasse ", "") for r in kassen[:4])
        text = (f"🗓 Die Änderungsperiode hat begonnen (bis {bis.strftime('%d.%m.%Y')}). Jetzt kann der Etat für den Folgemonat eingereicht werden: {namen}.\n"
                f"{config.SITE_URL}/schatzamt/etatverteilung/")
        if in_ruhezeit(con, k["id"]):
            vormerken(con, k["id"], "etat", text)
        else:
            await app["discord"].dm(k["id"], text)


async def _schleife(app):
    n = 0
    while True:
        try:
            await _abarbeiten(app)
            if n % 45 == 0:   # etwa alle 15 Minuten
                await _etat_erinnern(app)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Benachrichtigungen: %s", e)
        n += 1
        await asyncio.sleep(20)


async def _start(app):
    app["bn_task"] = asyncio.create_task(_schleife(app))


async def _stop(app):
    t = app.get("bn_task")
    if t:
        t.cancel()


def registrieren(app):
    global CON
    CON = app["db"]
    CON.executescript(SCHEMA)
    CON.commit()
    if buchung not in geld.NACH_BUCHUNG:
        geld.NACH_BUCHUNG.append(buchung)
    app.on_startup.append(_start)
    app.on_cleanup.append(_stop)
