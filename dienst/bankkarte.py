"""Digitale Bankkarte des Kaiserlichen Schatz- und Währungsamts (/schatzamt/bankkarte/).

Aufgebaut wie der Personalausweis (Kartenformat ID-1, Guilloche, Chip, Wappen, Vorder- und Rückseite zum Umdrehen, QR-Code zur Echtheitsprüfung,
maschinenlesbare Zone mit Prüfziffern). Adelsstände erhalten die **Goldene Karte**, alle anderen die **Standardkarte** – die Kartenart folgt den
aktuellen Discord-Rollen (Adelstitel).
- Beantragen: jedes Mitglied im Portal; dabei legt es seinen **Bank-PIN** (4–6 Ziffern) fest. Die Karte gilt 5 Jahre, je Person eine aktive Karte.
  Verlust → Karte sperren; danach kann eine Ersatzkarte (neue Nummer, neuer PIN) beantragt werden.
- PIN: wird nur als PBKDF2-Hash gespeichert. Nach 5 Fehlversuchen ist die Karte 15 Minuten gesperrt. Das Schatzamt kann den PIN zurücksetzen
  (der Inhaber legt dann einen neuen fest) und Karten sperren/freigeben (/schatzamt/amt/bankkarten/).
- **Mein Geld ist PIN-geschützt** (Middleware `pin_sperre`): Übersicht (privat), Konto & Umsätze, Überweisen, Steuern & Gebühren, Gehalt und Gewerbe
  öffnen erst nach Eingabe des PIN (20 Minuten ohne Aktivität, an die Sitzung gebunden). Die staatliche Ansicht („Staatl.“) und alle Informationsseiten
  bleiben frei. Ohne gültige Karte ist „Mein Geld“ gesperrt.
- **Ohne Karte keine Geldbewegung:** geld.buchen lehnt vom Inhaber selbst veranlasste Zahlungen (Überweisung, Steuerzahlung, Gebühr) von Privat- und
  Gewerbekonten ab, wenn er keine gültige Karte hat (karte_gueltig). Gutschriften (Gehalt, Grundpolster …) und Buchungen des Schatzamts bleiben möglich.
Tabellen: bk_karten, bk_entsperrt.
"""
import base64
import hashlib
import io
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit

from aiohttp import web

import amt
import anmeldung
import config
import db
import geld
import passdruck
import qr
import schatzamt as sa

esc = amt.esc
PFAD = sa.PFAD + "bankkarte/"
PRUEF = sa.PFAD + "karte/"
GUELTIG_JAHRE = 5
ENTSPERRT_MIN = 20
MAX_VERSUCHE = 5
SPERRE_MIN = 15
BIN = "4907"   # Kartenpräfix des Imperium Germanicum

# Adelstitel (Discord-Rollen der Gruppe „Adelstitel“): Goldene Karte
ADELSROLLEN = {"1522703851579375788",   # Adelstitel (Gruppe)
               "1522703961130537080", "1522704023935909969", "1522704134602489926", "1522704469677178991", "1522704536806883348",
               "1522704631728439351", "1522704685864194298", "1522704849194582066", "1522704916794048572", "1552045497781330042",
               "1522705004727767060", "1522705104858255380", "1522705180905308191"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS bk_karten (id INTEGER PRIMARY KEY AUTOINCREMENT, konto_id TEXT NOT NULL, nummer TEXT NOT NULL UNIQUE, token TEXT NOT NULL UNIQUE,
    art TEXT NOT NULL DEFAULT 'standard', pin_hash TEXT NOT NULL DEFAULT '', pin_salt TEXT NOT NULL DEFAULT '', ausgestellt INTEGER NOT NULL,
    gueltig_bis INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'aktiv', sperrgrund TEXT NOT NULL DEFAULT '', fehlversuche INTEGER NOT NULL DEFAULT 0,
    gesperrt_bis INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS bk_karten_k ON bk_karten (konto_id, status);
CREATE TABLE IF NOT EXISTS bk_entsperrt (sitzung TEXT PRIMARY KEY, konto_id TEXT NOT NULL, bis INTEGER NOT NULL);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Karten und PIN

def ist_adel(rollen):
    return bool(set(rollen or ()) & ADELSROLLEN)


def kartenart(rollen):
    return "gold" if ist_adel(rollen) else "standard"


def karte_von(con, konto_id):
    """Aktuelle Karte (aktiv oder gesperrt) des Kontos, sonst None."""
    return con.execute("SELECT * FROM bk_karten WHERE konto_id=? AND status IN ('aktiv','gesperrt') ORDER BY id DESC LIMIT 1", (konto_id,)).fetchone()


def karte_gueltig(con, konto_id):
    """Hat das Konto eine aktive, nicht abgelaufene Karte? (Voraussetzung für jede selbst veranlasste Geldbewegung)"""
    r = karte_von(con, konto_id)
    return bool(r and r["status"] == "aktiv" and r["gueltig_bis"] > time.time())


def _luhn(ziffern):
    s = 0
    for i, c in enumerate(reversed(ziffern)):
        d = int(c) * (2 if i % 2 == 0 else 1)
        s += d - 9 if d > 9 else d
    return str((10 - s % 10) % 10)


def _neue_nummer(con):
    while True:
        rumpf = BIN + "".join(str(secrets.randbelow(10)) for _ in range(11))
        nummer = rumpf + _luhn(rumpf)
        if not con.execute("SELECT 1 FROM bk_karten WHERE nummer=?", (nummer,)).fetchone():
            return nummer


def nummer_anzeige(n):
    return " ".join(n[i:i + 4] for i in range(0, len(n), 4))


def _hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def pin_fehler(pin, pin2=None):
    """Prüft einen neuen PIN (4–6 Ziffern, nicht trivial); gibt den Fehlertext oder None zurück."""
    if not re.fullmatch(r"\d{4,6}", pin or ""):
        return "Der PIN muss aus 4 bis 6 Ziffern bestehen."
    if pin2 is not None and pin != pin2:
        return "Die beiden PIN-Eingaben stimmen nicht überein."
    if len(set(pin)) == 1 or pin in ("1234", "4321", "12345", "54321", "123456", "654321", "0123", "3210"):
        return "Dieser PIN ist zu einfach. Bitte wähle eine andere Ziffernfolge."
    return None


def _pin_setzen(con, karte_id, pin):
    salt = secrets.token_hex(16)
    con.execute("UPDATE bk_karten SET pin_hash=?, pin_salt=?, fehlversuche=0, gesperrt_bis=0 WHERE id=?", (_hash(pin, salt), salt, karte_id))


def beantragen(con, k, pin, pin2):
    """Stellt dem Mitglied eine Bankkarte aus (Kartenart nach Adelstitel). Gibt (Karte, Fehler) zurück."""
    if not k["mitglied"]:
        return None, "Eine Bankkarte können nur Mitglieder unseres Discord-Servers beantragen."
    vorh = karte_von(con, k["id"])
    if vorh and vorh["status"] == "aktiv" and vorh["gueltig_bis"] > time.time():
        return None, "Du besitzt bereits eine gültige Bankkarte."
    f = pin_fehler(pin, pin2)
    if f:
        return None, f
    geld.privatkonto(con, k["id"], k=k)   # Privatkonto sicherstellen
    if vorh:
        con.execute("UPDATE bk_karten SET status='ersetzt' WHERE konto_id=? AND status IN ('aktiv','gesperrt')", (k["id"],))
    jetzt = datetime.now()
    bis = int((jetzt + timedelta(days=365 * GUELTIG_JAHRE)).timestamp())
    cur = con.execute("INSERT INTO bk_karten (konto_id, nummer, token, art, ausgestellt, gueltig_bis) VALUES (?,?,?,?,?,?)",
                      (k["id"], _neue_nummer(con), secrets.token_urlsafe(18), kartenart(k["rollen"]), int(jetzt.timestamp()), bis))
    _pin_setzen(con, cur.lastrowid, pin)
    geld.protokoll(con, k, "Bankkarte ausgestellt", f'{k["name"]}: {kartenart(k["rollen"])}')
    return con.execute("SELECT * FROM bk_karten WHERE id=?", (cur.lastrowid,)).fetchone(), None


def pin_pruefen(con, karte, pin):
    """('ok'|'falsch'|'gesperrt'|'kein_pin', Rest) – zählt Fehlversuche; nach MAX_VERSUCHE Sperre für SPERRE_MIN Minuten."""
    jetzt = int(time.time())
    if karte["status"] != "aktiv":
        return "gesperrt", 0
    if karte["gesperrt_bis"] > jetzt:
        return "gesperrt", karte["gesperrt_bis"] - jetzt
    if not karte["pin_hash"]:
        return "kein_pin", 0
    if secrets.compare_digest(_hash(re.sub(r"\D", "", pin or "")[:12], karte["pin_salt"]), karte["pin_hash"]):
        con.execute("UPDATE bk_karten SET fehlversuche=0, gesperrt_bis=0 WHERE id=?", (karte["id"],))
        return "ok", 0
    n = karte["fehlversuche"] + 1
    if n >= MAX_VERSUCHE:
        con.execute("UPDATE bk_karten SET fehlversuche=0, gesperrt_bis=? WHERE id=?", (jetzt + SPERRE_MIN * 60, karte["id"]))
        return "gesperrt", SPERRE_MIN * 60
    con.execute("UPDATE bk_karten SET fehlversuche=? WHERE id=?", (n, karte["id"]))
    return "falsch", MAX_VERSUCHE - n


# ---------------------------------------------------------------- Entsperrung von „Mein Geld“ (je Sitzung)

def _sitzung(request):
    t = request.cookies.get(config.SITZUNG_COOKIE)
    return db._hash(t) if t else None


def entsperrt(con, request, k, verlaengern=True):
    s = _sitzung(request)
    if not s:
        return False
    r = con.execute("SELECT * FROM bk_entsperrt WHERE sitzung=? AND konto_id=?", (s, k["id"])).fetchone()
    jetzt = int(time.time())
    if not r or r["bis"] < jetzt:
        return False
    if verlaengern:
        con.execute("UPDATE bk_entsperrt SET bis=? WHERE sitzung=?", (jetzt + ENTSPERRT_MIN * 60, s))
    return True


def entsperren(con, request, k):
    s = _sitzung(request)
    if s:
        con.execute("INSERT OR REPLACE INTO bk_entsperrt (sitzung, konto_id, bis) VALUES (?,?,?)", (s, k["id"], int(time.time()) + ENTSPERRT_MIN * 60))
        con.execute("DELETE FROM bk_entsperrt WHERE bis<?", (int(time.time()) - 86400,))


def wieder_sperren(con, request):
    s = _sitzung(request)
    if s:
        con.execute("DELETE FROM bk_entsperrt WHERE sitzung=?", (s,))


# ---------------------------------------------------------------- Zugriffsschutz „Mein Geld“

MEIN_GELD = ("steuern", "gehalt", "gewerbe")     # immer privat
DUAL = ("", "konto", "ueberweisen")               # Staatl. frei, Privat geschützt


def braucht_pin(con, request, k):
    """Gehört die Anfrage zu „Mein Geld“ (privat)? Beamte des Schatzamts lesen fremde Abrechnungen und Kontoauszüge ohne eigenen PIN."""
    p = request.path
    if not p.startswith(sa.PFAD) or not k or not k["mitglied"]:
        return False
    teile = p[len(sa.PFAD):].strip("/").split("/")
    erste = teile[0]
    if erste not in MEIN_GELD + DUAL:
        return False
    if erste in DUAL:
        if request.cookies.get(sa.MODUS_COOKIE) == "staat" and sa.hat_staat(con, k):
            return False
    if len(teile) > 1 and teile[1].isdigit() and geld.ist_beamter(k):   # gehalt/<id>, konto/<id>/pdf
        return False
    return True


@web.middleware
async def pin_sperre(request, handler):
    if request.path.startswith(sa.PFAD) and not request.path.startswith(PFAD):
        k = await anmeldung.konto(request)
        con = request.app["db"]
        if k and braucht_pin(con, request, k) and not entsperrt(con, request, k):
            if request.method == "GET":
                raise web.HTTPFound(f"{PFAD}entsperren?weiter={quote(request.path_qs)}")
            raise web.HTTPSeeOther(f"{PFAD}entsperren")
    return await handler(request)


# ---------------------------------------------------------------- Kartenbild

CSS = """<style>
.bk-buehne{max-width:460px;margin:8px auto 4px;perspective:1600px}
.bk-dreher{position:relative;container-type:inline-size;width:100%;aspect-ratio:85.6/54;cursor:pointer}
.bk-innen{position:absolute;inset:0;transform-style:preserve-3d;transition:transform .8s cubic-bezier(.65,.05,.36,1)}
.bk-dreher.um .bk-innen{transform:rotateY(180deg)}
.bk-seite{position:absolute;inset:0;border-radius:3.4cqw;overflow:hidden;backface-visibility:hidden;-webkit-backface-visibility:hidden;
 box-shadow:0 1.6cqw 5cqw rgba(10,15,39,.35);font-family:var(--schrift,system-ui,sans-serif)}
.bk-seite.hinten{transform:rotateY(180deg)}
.bk-standard{background:linear-gradient(135deg,#141d38,#2a3a69 55%,#18223f);color:#e9edf7}
.bk-gold{background:linear-gradient(135deg,#f7e6a8,#dcbc6a 38%,#b98a2e 72%,#ecd38c);color:#2b2108}
.bk-seite .muster{position:absolute;inset:0;width:100%;height:100%;opacity:.55}
.bk-seite .rosette{position:absolute;width:44cqw;right:-12cqw;top:16cqw;opacity:.4}
.bk-kopf{position:absolute;left:6cqw;top:5cqw;line-height:1.15}
.bk-kopf b{display:block;font-size:3.4cqw;letter-spacing:.22em}
.bk-kopf span{display:block;margin-top:.8cqw;font-size:2cqw;letter-spacing:.1em;text-transform:uppercase;opacity:.85}
.bk-wappen{position:absolute;right:5.5cqw;top:4.2cqw;height:12.5cqw}
.bk-gold .bk-wappen{filter:brightness(.18) sepia(1) saturate(.9)}
.bk-chip{position:absolute;left:6cqw;top:24cqw;width:13cqw}
.bk-nfc{position:absolute;left:22cqw;top:25.5cqw;width:7cqw;opacity:.8}
.bk-nummer{position:absolute;left:6cqw;top:39.5cqw;font:600 6.1cqw/1 "Liberation Mono","DejaVu Sans Mono",monospace;letter-spacing:.1em;white-space:nowrap}
.bk-gold .bk-nummer{text-shadow:0 .25cqw .2cqw rgba(255,255,255,.55)}
.bk-standard .bk-nummer{text-shadow:0 .25cqw .3cqw rgba(0,0,0,.6)}
.bk-name{position:absolute;left:6cqw;bottom:5cqw;font-size:3.5cqw;font-weight:600;letter-spacing:.06em;text-transform:uppercase;max-width:56cqw;
 line-height:1.2;max-height:8.6cqw;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.bk-gueltig{position:absolute;right:5.5cqw;bottom:5cqw;line-height:1.15;text-align:right}
.bk-gueltig i{display:block;font-style:normal;font-size:1.7cqw;letter-spacing:.12em;text-transform:uppercase;opacity:.8}
.bk-gueltig b{display:block;font:600 3.6cqw "Liberation Mono",monospace}
.bk-art{position:absolute;right:5.5cqw;top:22.5cqw;text-align:right;line-height:1}
.bk-art b{display:block;font:italic 700 4.8cqw "Liberation Serif",Georgia,serif;letter-spacing:.1em;text-transform:uppercase}
.bk-art i{display:block;font-style:normal;font-size:1.6cqw;letter-spacing:.2em;text-transform:uppercase;margin-top:.8cqw;opacity:.8}
.bk-glanz{position:absolute;inset:0;pointer-events:none;mix-blend-mode:soft-light;opacity:.8;
 background:linear-gradient(115deg,transparent 28%,rgba(255,255,255,.5) 42%,rgba(255,255,255,.12) 52%,transparent 66%);background-size:260% 100%;background-position:120% 0;
 animation:bk-glanz 6s ease-in-out infinite}
@keyframes bk-glanz{0%,35%{background-position:120% 0}75%,100%{background-position:-30% 0}}
.bk-streifen{position:absolute;left:0;right:0;top:8cqw;height:12cqw;background:#101114}
.bk-gold .bk-streifen{background:#2a2108}
.bk-unter{position:absolute;left:6cqw;right:6cqw;top:24cqw;height:9cqw;background:repeating-linear-gradient(135deg,#f3f1ea 0 1.4cqw,#e9e6db 1.4cqw 2.8cqw);
 color:#222;display:flex;align-items:center;justify-content:space-between;padding:0 2.4cqw;font:600 3.4cqw "Liberation Mono",monospace;border-radius:.6cqw}
.bk-unter i{font:italic 400 2cqw "Liberation Serif",Georgia,serif;color:#555}
.bk-qr{position:absolute;left:6cqw;top:35cqw;background:rgba(255,255,255,.92);border-radius:1cqw;padding:.7cqw;line-height:0}
.bk-qr svg{width:13.5cqw!important;height:13.5cqw!important}
.bk-info{position:absolute;left:24cqw;right:6cqw;top:35.5cqw;font-size:2.15cqw;line-height:1.4;opacity:.92}
.bk-info b{font-weight:700}
.bk-mrz{position:absolute;left:6cqw;right:4cqw;bottom:3.4cqw;font:400 2.9cqw/1.25 "Liberation Mono","DejaVu Sans Mono",monospace;white-space:pre;letter-spacing:.02em}
.bk-vermerk{position:absolute;left:6cqw;bottom:.9cqw;font-size:1.25cqw;opacity:.7;white-space:nowrap}
.bk-gesperrt .bk-seite::before{content:"GESPERRT";position:absolute;z-index:5;left:50%;top:50%;transform:translate(-50%,-50%) rotate(-14deg);font:800 11cqw "Liberation Sans",Arial;
 letter-spacing:.1em;color:rgba(190,20,20,.82);border:.9cqw solid rgba(190,20,20,.82);padding:.8cqw 3cqw;border-radius:1.4cqw;background:rgba(255,255,255,.35)}
.bk-hinweis{text-align:center;color:var(--grau);font-size:13px;margin:6px 0 14px}
.bk-leiste{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin:10px 0}
</style>"""


def _chip_svg(gold):
    c1, c2 = ("#e8d089", "#b78b2e") if not gold else ("#f6e7ae", "#a8791f")
    return (f'<svg class="bk-chip" viewBox="0 0 40 30" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="chg{int(gold)}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient></defs>'
            f'<rect x="1" y="1" width="38" height="28" rx="5" fill="url(#chg{int(gold)})" stroke="#6a4f12" stroke-width=".8"/>'
            '<g fill="none" stroke="#6a4f12" stroke-width=".8"><path d="M1 10h12M27 10h12M1 20h12M27 20h12M13 1v28M27 1v28"/><rect x="13" y="8" width="14" height="14" rx="3"/></g></svg>')


def _nfc_svg():
    return ('<svg class="bk-nfc" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" xmlns="http://www.w3.org/2000/svg">'
            '<path d="M7 5.5a9 9 0 0 1 0 13"/><path d="M11 3.2a12.5 12.5 0 0 1 0 17.6"/><path d="M15 1a16 16 0 0 1 0 22"/></svg>')


def _mrz(karte, name):
    n = karte["nummer"]
    z1 = ("BK" + passdruck.STAAT + n + passdruck.pruefziffer(n))[:30].ljust(30, "<")
    ab = datetime.fromtimestamp(karte["gueltig_bis"]).strftime("%y%m%d")
    z2 = (ab + passdruck.pruefziffer(ab) + ("G" if karte["art"] == "gold" else "S") + "<" * 3 + passdruck._mrz_name(name, 18))[:30].ljust(30, "<")
    return z1, z2


def karte_html(karte, name, kontonr, gesperrt=False):
    """Bankkarte (Vorder- und Rückseite, Klick dreht um) als HTML. karte: bk_karten-Zeile mit aktueller Art."""
    gold = karte["art"] == "gold"
    klasse = "bk-gold" if gold else "bk-standard"
    linie = "#7a5a14" if gold else "#8fa4d8"
    z1, z2 = _mrz(karte, name)
    ab = datetime.fromtimestamp(karte["gueltig_bis"]).strftime("%m/%y")
    wappen = passdruck.bild("wappen_gold.png" if not gold else "wappen.png")
    muster = passdruck.guilloche(85.6, 54, linie, 26, 1.4, 3.2, 0.1)
    rosette = passdruck.rosette(20, linie)
    vorn = (f'<div class="bk-seite vorn {klasse}">{muster}{rosette}<div class="bk-kopf"><b>IMPERIUM GERMANICUM</b><span>Kaiserliches Schatz- und Währungsamt · Bankkarte</span></div>'
            f'<img class="bk-wappen" src="{wappen}" alt="">{_chip_svg(gold)}{_nfc_svg()}'
            f'<div class="bk-nummer">{esc(nummer_anzeige(karte["nummer"]))}</div><div class="bk-name">{esc(name)}</div>'
            f'<div class="bk-gueltig"><i>Gültig bis / Valid thru</i><b>{ab}</b></div>'
            f'<div class="bk-art"><b>{"Gold" if gold else "Standard"}</b><i>{"Goldene Karte" if gold else "Bankkarte"}</i></div><div class="bk-glanz"></div></div>')
    pruef = qr.svg(f"{config.SITE_URL}{PRUEF}{karte['token']}", 17, "#000")
    hinten = (f'<div class="bk-seite hinten {klasse}">{passdruck.guilloche(85.6, 54, linie, 26, 1.4, 2.6, 0.1, 2.1)}<div class="bk-streifen"></div>'
              f'<div class="bk-unter"><span>{esc(kontonr)}</span><i>Konto / Account</i></div><div class="bk-qr">{pruef}</div>'
              '<div class="bk-info"><b>Echtheit prüfen:</b> QR-Code scannen. Bei Verlust die Karte sofort im Schatzamt-Portal sperren.<br>'
              f'<b>Kartenart:</b> {"Goldene Karte (Adelsstand)" if gold else "Standardkarte"}</div>'
              f'<div class="bk-mrz">{esc(z1)}\n{esc(z2)}</div><div class="bk-vermerk">{esc(passdruck.VERMERK.replace("Ausweisdokument", "Zahlungsmittel"))}</div></div>')
    return (f'<div class="bk-buehne"><div class="bk-dreher{" bk-gesperrt" if gesperrt else ""}" id="bk-dreher" onclick="this.classList.toggle(\'um\')" role="img" '
            f'aria-label="Bankkarte {esc(name)}, Klick dreht die Karte um"><div class="bk-innen">{vorn}{hinten}</div></div></div>')


def _karteninfo(con, karte, rollen=None):
    """(Karte mit aktueller Kartenart, Anzeigename, Kontonummer)."""
    if rollen is not None and karte["art"] != kartenart(rollen):
        con.execute("UPDATE bk_karten SET art=? WHERE id=?", (kartenart(rollen), karte["id"]))
        karte = con.execute("SELECT * FROM bk_karten WHERE id=?", (karte["id"],)).fetchone()
    name = geld.anzeigename(con, karte["konto_id"])
    p = con.execute("SELECT nummer FROM gk_konten WHERE art='privat' AND inhaber_id=?", (karte["konto_id"],)).fetchone()
    return karte, name, geld.nummer_anzeige(p["nummer"]) if p else "–"


# ---------------------------------------------------------------- Seiten

def _datum(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y")


@sa.seite("mitglied")
async def seite(request, k):
    con = request.app["db"]
    karte = karte_von(con, k["id"])
    gold = ist_adel(k["rollen"])
    c = amt.csrf_feld(request)
    if karte:
        karte, name, kontonr = _karteninfo(con, karte, k["rollen"])
        con.commit()
        gesperrt = karte["status"] != "aktiv"
        abgelaufen = karte["gueltig_bis"] <= time.time()
        status = (amt.status_marke("nein", "Gesperrt") if gesperrt else amt.status_marke("nein", "Abgelaufen") if abgelaufen else amt.status_marke("ok", "Aktiv"))
        offen = entsperrt(con, request, k, verlaengern=False)
        daten = amt.daten_tabelle([("Kartenart", "Goldene Karte (Adelsstand)" if karte["art"] == "gold" else "Standardkarte"), ("Kartennummer", nummer_anzeige(karte["nummer"])),
                                   ("Konto", kontonr), ("Ausgestellt", _datum(karte["ausgestellt"])), ("Gültig bis", _datum(karte["gueltig_bis"])), ("Status", status)])
        pin_form = ""
        if not gesperrt and not abgelaufen:
            if karte["pin_hash"]:
                pin_form = (f'<h2>Bank-PIN ändern</h2><form class="sa-formular" method="post" action="{PFAD}pin">{c}<div class="zeilen">'
                            '<div><label for="a">Bisheriger PIN</label><input type="password" id="a" name="alt" inputmode="numeric" autocomplete="off" maxlength="6" required></div>'
                            '<div><label for="n">Neuer PIN (4–6 Ziffern)</label><input type="password" id="n" name="neu" inputmode="numeric" autocomplete="off" maxlength="6" required></div>'
                            '<div><label for="n2">Neuer PIN wiederholen</label><input type="password" id="n2" name="neu2" inputmode="numeric" autocomplete="off" maxlength="6" required></div></div>'
                            f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}PIN ändern</button></div></form>')
            else:
                pin_form = (f'<div class="warnung">{amt.ic("triangle-alert")} Dein PIN wurde vom Schatzamt zurückgesetzt. Lege jetzt einen neuen fest, sonst bleibt „Mein Geld“ gesperrt.</div>'
                            f'<form class="sa-formular" method="post" action="{PFAD}pin">{c}<div class="zeilen">'
                            '<div><label for="n">Neuer PIN (4–6 Ziffern)</label><input type="password" id="n" name="neu" inputmode="numeric" autocomplete="off" maxlength="6" required></div>'
                            '<div><label for="n2">PIN wiederholen</label><input type="password" id="n2" name="neu2" inputmode="numeric" autocomplete="off" maxlength="6" required></div></div>'
                            f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}PIN festlegen</button></div></form>')
        aktionen = ""
        if not gesperrt and not abgelaufen:
            aktionen = (f'<div class="bk-leiste"><a class="btn zweit" href="{PFAD}bild?seite=vorn">{amt.ic("file-down")}Vorderseite als Bild</a>'
                        f'<a class="btn zweit" href="{PFAD}bild?seite=hinten">{amt.ic("file-down")}Rückseite als Bild</a>'
                        + (f'<form method="post" action="{PFAD}abmelden" style="display:inline">{c}<button class="btn zweit" type="submit">{amt.ic("lock")}Mein Geld jetzt sperren</button></form>' if offen else
                           f'<a class="btn" href="{PFAD}entsperren">{amt.ic("lock-open")}Mein Geld entsperren</a>')
                        + '</div>')
        ersatz = ""
        if gesperrt or abgelaufen:
            ersatz = (f'<h2>Ersatzkarte beantragen</h2><p class="az">{"Die Karte ist gesperrt" if gesperrt else "Die Karte ist abgelaufen"}'
                      f'{": " + esc(karte["sperrgrund"]) if karte["sperrgrund"] else ""}. Mit einer Ersatzkarte (neue Nummer, neuer PIN) kannst du wieder Geld bewegen.</p>'
                      + _antrag_form(c, "Ersatzkarte beantragen"))
        sperr = ""
        if not gesperrt and not abgelaufen:
            sperr = (f'<h2>Karte sperren</h2><form class="sa-leiste" method="post" action="{PFAD}sperren" onsubmit="return confirm(\'Karte wirklich sperren? Danach sind keine Geldbewegungen mehr möglich, bis du eine Ersatzkarte beantragst.\')">{c}'
                     '<div><label for="g">Grund (z. B. Verlust)</label><input type="text" id="g" name="grund" maxlength="80" value="Verlust"></div>'
                     f'<button class="btn zweit gefahr" type="submit">{amt.ic("lock")}Karte sperren</button></form>')
        inhalt = (f'<h1>{amt.ic("credit-card")} Bankkarte</h1>{amt.meldung(request)}' + CSS + karte_html(karte, name, kontonr, gesperrt or abgelaufen)
                  + '<p class="bk-hinweis">Klicke auf die Karte, um sie umzudrehen.</p>' + aktionen + '<h2>Kartendaten</h2>' + daten
                  + pin_form + ersatz + sperr
                  + '<p class="sa-hinweis">Der Bank-PIN öffnet „Mein Geld“ (Konto, Überweisen, Steuern, Gehalt, Gewerbe). Ohne gültige Karte sind keine Geldbewegungen möglich.</p>')
    else:
        inhalt = (f'<h1>{amt.ic("credit-card")} Bankkarte</h1>{amt.meldung(request)}'
                  '<p class="az">Die digitale Bankkarte ist dein Zugang zu „Mein Geld“: Ohne Karte sind keine Geldbewegungen möglich. Du beantragst sie hier beim Schatzamt und legst dabei deinen Bank-PIN fest.</p>'
                  f'<div class="sa-erkl"><b>Welche Karte erhalte ich?</b><ol><li><b>Goldene Karte</b> für Adelsstände (Inhaber eines Adelstitels).</li><li><b>Standardkarte</b> für alle anderen.</li>'
                  '<li>Die Karte gilt fünf Jahre, ist im Aufbau dem Personalausweis nachempfunden und lässt sich über den QR-Code auf Echtheit prüfen.</li></ol></div>'
                  + CSS + f'<div class="bk-vorschau">{_vorschau(k, gold)}</div>'
                  + (f'<p class="az">Deine Karte wird <b>{"golden" if gold else "eine Standardkarte"}</b>.</p>')
                  + '<h2>Karte beantragen</h2>' + _antrag_form(c, "Bankkarte beantragen"))
    return sa.ant(request, k, "Bankkarte", "sa-bankkarte", inhalt)


def _antrag_form(c, text):
    return (f'<form class="sa-formular" method="post" action="{PFAD}beantragen">{c}<div class="zeilen">'
            '<div><label for="p1">Bank-PIN festlegen (4–6 Ziffern)</label><input type="password" id="p1" name="pin" inputmode="numeric" autocomplete="new-password" maxlength="6" required></div>'
            '<div><label for="p2">PIN wiederholen</label><input type="password" id="p2" name="pin2" inputmode="numeric" autocomplete="new-password" maxlength="6" required></div></div>'
            '<p class="sa-hinweis">Merke dir den PIN gut: Er wird verschlüsselt gespeichert und kann nicht angezeigt werden. Das Schatzamt kann ihn nur zurücksetzen.</p>'
            f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}{esc(text)}</button></div></form>')


def _vorschau(k, gold):
    muster = {"nummer": "4907 •••• •••• ••••", "art": "gold" if gold else "standard", "gueltig_bis": int((datetime.now() + timedelta(days=365 * GUELTIG_JAHRE)).timestamp()),
              "token": "vorschau"}
    karte = dict(muster)
    return karte_html(karte, k["name"], "IG•• •••• •••• ••••")


async def beantragen_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    karte, fehler = beantragen(con, k, str(form.get("pin", "")), str(form.get("pin2", "")))
    if fehler:
        con.rollback()
        sa.weiter(PFAD, fehler, True)
    entsperren(con, request, k)   # frisch Beantragte kommen direkt in „Mein Geld“
    con.commit()
    sa.weiter(PFAD, f'Bankkarte {"Gold" if karte["art"] == "gold" else "Standard"} ausgestellt. „Mein Geld“ ist jetzt entsperrt.')


async def pin_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    karte = karte_von(con, k["id"])
    if not karte or karte["status"] != "aktiv":
        sa.weiter(PFAD, "Keine aktive Karte.", True)
    f = pin_fehler(str(form.get("neu", "")), str(form.get("neu2", "")))
    if f:
        sa.weiter(PFAD, f, True)
    if karte["pin_hash"]:
        res, rest = pin_pruefen(con, karte, str(form.get("alt", "")))
        con.commit()
        if res != "ok":
            sa.weiter(PFAD, "Der bisherige PIN ist falsch." if res == "falsch" else f"Die Karte ist vorübergehend gesperrt ({max(1, rest // 60)} Min.).", True)
    _pin_setzen(con, karte["id"], str(form.get("neu")))
    geld.protokoll(con, k, "Bank-PIN geändert", k["name"])
    con.commit()
    sa.weiter(PFAD, "PIN gespeichert.")


async def sperren_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    karte = karte_von(con, k["id"])
    if karte and karte["status"] == "aktiv":
        grund = sa._f(form, "grund", 80) or "Gesperrt vom Inhaber"
        con.execute("UPDATE bk_karten SET status='gesperrt', sperrgrund=? WHERE id=?", (grund, karte["id"]))
        wieder_sperren(con, request)
        geld.protokoll(con, k, "Bankkarte gesperrt", f'{k["name"]}: {grund}')
        con.commit()
    sa.weiter(PFAD, "Karte gesperrt. Beantrage eine Ersatzkarte, um wieder Geld zu bewegen.")


async def abmelden_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    await sa.formular(request)
    wieder_sperren(request.app["db"], request)
    request.app["db"].commit()
    sa.weiter(PFAD, "„Mein Geld“ ist wieder gesperrt.")


def _sicherer_weg(weiter):
    u = urlsplit(weiter or "")
    pfad = u.path if u.path.startswith(sa.PFAD) and not u.path.startswith(PFAD) else sa.PFAD
    return pfad + ("?" + u.query if u.query and pfad != sa.PFAD else "")


@sa.seite("mitglied")
async def entsperren_seite(request, k):
    con = request.app["db"]
    weiter = _sicherer_weg(request.query.get("weiter", ""))
    karte = karte_von(con, k["id"])
    if karte and karte["status"] == "aktiv" and karte["gueltig_bis"] > time.time() and karte["pin_hash"]:
        if entsperrt(con, request, k, verlaengern=False):
            raise web.HTTPFound(weiter)
        inhalt = (f'<h1>{amt.ic("lock")} Mein Geld</h1>{amt.meldung(request)}'
                  '<p class="az">Gib deinen Bank-PIN ein, um „Mein Geld“ zu öffnen (Konto, Überweisen, Steuern, Gehalt, Gewerbe).</p>'
                  f'<form class="sa-formular" method="post" action="{PFAD}entsperren" style="max-width:360px">{amt.csrf_feld(request)}<input type="hidden" name="weiter" value="{esc(weiter)}">'
                  '<div><label for="p">Bank-PIN</label><input type="password" id="p" name="pin" inputmode="numeric" autocomplete="off" maxlength="6" required autofocus '
                  'style="font-size:22px;letter-spacing:.4em;text-align:center"></div>'
                  f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("lock-open")}Entsperren</button><a class="btn zweit" href="{PFAD}">Zur Bankkarte</a></div></form>')
    elif karte and karte["status"] == "aktiv" and karte["gueltig_bis"] > time.time():   # PIN zurückgesetzt
        inhalt = (f'<h1>{amt.ic("lock")} Mein Geld</h1><div class="warnung">{amt.ic("triangle-alert")} Dein PIN wurde zurückgesetzt. Lege unter „Bankkarte“ einen neuen fest.</div>'
                  f'<p><a class="btn" href="{PFAD}">Zur Bankkarte</a></p>')
    else:
        grund = ("Deine Bankkarte ist gesperrt oder abgelaufen." if karte else "Du hast noch keine Bankkarte.")
        inhalt = (f'<h1>{amt.ic("lock")} Mein Geld</h1><div class="warnung">{amt.ic("triangle-alert")} {grund} Ohne gültige Karte ist „Mein Geld“ gesperrt und es sind keine Geldbewegungen möglich.</div>'
                  f'<p><a class="btn" href="{PFAD}">{amt.ic("credit-card")}{"Ersatzkarte beantragen" if karte else "Bankkarte beantragen"}</a></p>')
    return sa.ant(request, k, "Mein Geld", "sa-bankkarte", inhalt)


async def entsperren_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    weiter = _sicherer_weg(str(form.get("weiter", "")))
    karte = karte_von(con, k["id"])
    ziel = f"{PFAD}entsperren?weiter={quote(weiter)}"
    if not karte:
        sa.weiter(ziel, "Du hast noch keine Bankkarte.", True)
    res, rest = pin_pruefen(con, karte, str(form.get("pin", "")))
    con.commit()
    if res == "ok":
        entsperren(con, request, k)
        con.commit()
        raise web.HTTPSeeOther(weiter)
    sa.weiter(ziel, {"falsch": f"Falscher PIN. Noch {rest} Versuch(e).", "gesperrt": f"Zu viele Fehlversuche bzw. Karte gesperrt – bitte in {max(1, rest // 60)} Min. erneut versuchen.",
                     "kein_pin": "Für diese Karte ist kein PIN gesetzt. Bitte unter „Bankkarte“ einen festlegen."}[res], True)


# ---------------------------------------------------------------- Bild und Prüfseite

async def bild(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    con = request.app["db"]
    karte = karte_von(con, k["id"])
    if not karte or karte["status"] != "aktiv":
        raise web.HTTPNotFound(text="Keine aktive Karte.")
    karte, name, kontonr = _karteninfo(con, karte, k["rollen"])
    hinten = request.query.get("seite") == "hinten"
    from playwright.async_api import async_playwright
    import bild as bildmod  # noqa: F401  (setzt PLAYWRIGHT_BROWSERS_PATH)
    kh = karte_html(karte, name, kontonr)
    if hinten:
        kh = kh.replace('class="bk-dreher', 'class="bk-dreher um', 1)
    html = ('<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;background:transparent;font-family:"Liberation Sans",Arial,sans-serif}'
            '.bk-innen{transition:none!important}.bk-glanz{animation:none!important}.bk-seite{box-shadow:none!important}</style>' + CSS
            + f'</head><body><div style="width:856px">{kh}</div></body></html>')
    async with amt._pdf_sperre:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            try:
                pg = await b.new_page(viewport={"width": 900, "height": 600}, device_scale_factor=2)
                await pg.set_content(html)
                await pg.wait_for_timeout(150)
                png = await pg.locator("#bk-dreher").screenshot(omit_background=True)
            finally:
                await b.close()
    return web.Response(body=png, content_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="bankkarte-{"rueckseite" if hinten else "vorderseite"}.png"', "Cache-Control": "no-store"})


async def pruefen(request):
    """Öffentliche Echtheitsprüfung (QR-Code): zeigt Gültigkeit, Inhaber und Kartenart, keine Konto- oder Kartennummer."""
    con = request.app["db"]
    karte = con.execute("SELECT * FROM bk_karten WHERE token=?", (request.match_info["token"],)).fetchone()
    if karte:
        jetzt = time.time()
        zustand = ("ungueltig", "Gesperrt") if karte["status"] == "gesperrt" else ("ungueltig", "Ersetzt") if karte["status"] == "ersetzt" else \
                  ("ungueltig", "Abgelaufen") if karte["gueltig_bis"] <= jetzt else ("gueltig", "Gültig")
        name = geld.anzeigename(con, karte["konto_id"])
        zeilen = (f'<dl><dt>Karteninhaber</dt><dd>{esc(name)}</dd><dt>Kartenart</dt><dd>{"Goldene Karte (Adelsstand)" if karte["art"] == "gold" else "Standardkarte"}</dd>'
                  f'<dt>Karte endet auf</dt><dd>•••• {esc(karte["nummer"][-4:])}</dd><dt>Gültig bis</dt><dd>{_datum(karte["gueltig_bis"])}</dd>'
                  f'<dt>Ausgestellt von</dt><dd>Kaiserliches Schatz- und Währungsamt</dd></dl>')
    else:
        zustand, zeilen = ("ungueltig", "Unbekannt"), "<p>Zu diesem Code gibt es keine Bankkarte.</p>"
    farbe = "#1d6b34" if zustand[0] == "gueltig" else "#9b1c1c"
    text = (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            f'<title>Bankkarte prüfen – Imperium Germanicum</title><style>body{{margin:0;font:16px/1.5 system-ui,sans-serif;background:#f5f6f8;color:#16171a}}main{{max-width:460px;margin:8vh auto;background:#fff;'
            f'border:1px solid #e3e4e8;border-radius:14px;padding:26px 28px}}h1{{font-size:20px;margin:0 0 4px}}.s{{display:inline-block;margin:10px 0 14px;padding:4px 14px;border-radius:999px;'
            f'font-weight:700;color:#fff;background:{farbe}}}dl{{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:0}}dt{{color:#6b6f76}}dd{{margin:0;font-weight:600}}'
            f'small{{display:block;margin-top:18px;color:#6b6f76}}</style></head><body><main><h1>Bankkarte prüfen</h1><div class="s">{zustand[1]}</div>{zeilen}'
            f'<small>Rollenspieldokument des Imperium Germanicum · Kaiserliches Schatz- und Währungsamt</small></main></body></html>')
    return web.Response(text=text, content_type="text/html", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- Verwaltung (Schatzamt)

@sa.seite("beamter")
async def verwaltung(request, k):
    con = request.app["db"]
    c = amt.csrf_feld(request)
    q = " ".join(request.query.get("q", "").split())[:40]
    rows = con.execute("SELECT * FROM bk_karten WHERE status IN ('aktiv','gesperrt') ORDER BY id DESC").fetchall()
    zeilen = []
    for r in rows:
        name = geld.anzeigename(con, r["konto_id"])
        if q and q.lower() not in name.lower() and q not in r["nummer"]:
            continue
        status = ("Gesperrt" if r["status"] == "gesperrt" else "Abgelaufen" if r["gueltig_bis"] <= time.time() else "Aktiv")
        akt = (f'<form method="post" action="{PFAD}verwalten" style="display:inline">{c}<input type="hidden" name="id" value="{r["id"]}">'
               + (f'<button class="btn zweit klein" name="aktion" value="freigeben" type="submit">Freigeben</button> ' if r["status"] == "gesperrt" else
                  f'<button class="btn zweit klein gefahr" name="aktion" value="sperren" type="submit">Sperren</button> ')
               + f'<button class="btn zweit klein" name="aktion" value="pin" type="submit" onclick="return confirm(\'PIN zurücksetzen? Der Inhaber legt danach einen neuen fest.\')">PIN zurücksetzen</button></form>')
        zeilen.append((esc(name), "Gold" if r["art"] == "gold" else "Standard", f'<span class="sa-nr">…{esc(r["nummer"][-4:])}</span>', _datum(r["ausgestellt"]),
                       amt.status_marke("ok" if status == "Aktiv" else "nein", status) + ("" if r["pin_hash"] else " " + amt.status_marke("warn", "PIN offen")), akt))
    ohne = con.execute("SELECT COUNT(*) FROM gk_konten WHERE art='privat' AND inhaber_id NOT IN (SELECT konto_id FROM bk_karten WHERE status='aktiv')").fetchone()[0]
    inhalt = (f'<h1>{amt.ic("credit-card")} Bankkarten</h1>{amt.meldung(request)}'
              f'<div class="kennzahlen"><div><b>{sum(1 for r in rows if r["status"] == "aktiv")}</b>Aktive Karten</div><div><b>{sum(1 for r in rows if r["art"] == "gold" and r["status"] == "aktiv")}</b>davon Gold</div>'
              f'<div><b>{sum(1 for r in rows if r["status"] == "gesperrt")}</b>Gesperrt</div><div><b>{ohne}</b>Privatkonten ohne Karte</div></div>'
              f'<form class="sa-leiste" method="get"><div><label for="q">Name oder Kartenende</label><input type="search" id="q" name="q" value="{esc(q)}"></div>'
              f'<button class="btn zweit" type="submit">{amt.ic("search")}Suchen</button></form>'
              + amt.tabelle(["Inhaber", "Art", "Karte", "Ausgestellt", "Status", ""], zeilen, "Keine Karten.")
              + '<p class="sa-hinweis">Ohne gültige Karte sind für den Inhaber keine Geldbewegungen möglich. Zurückgesetzte PINs legt der Inhaber unter „Bankkarte“ neu fest.</p>')
    return sa.ant(request, k, "Bankkarten", "sa-amt-bankkarten", inhalt)


async def verwalten_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_beamter(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    r = con.execute("SELECT * FROM bk_karten WHERE id=?", (int(form["id"]),)).fetchone() if str(form.get("id", "")).isdigit() else None
    if not r:
        raise web.HTTPNotFound()
    aktion = form.get("aktion")
    name = geld.anzeigename(con, r["konto_id"])
    if aktion == "sperren":
        con.execute("UPDATE bk_karten SET status='gesperrt', sperrgrund='Gesperrt durch das Schatzamt' WHERE id=?", (r["id"],))
        text = "gesperrt"
    elif aktion == "freigeben":
        con.execute("UPDATE bk_karten SET status='aktiv', sperrgrund='', fehlversuche=0, gesperrt_bis=0 WHERE id=?", (r["id"],))
        text = "freigegeben"
    elif aktion == "pin":
        con.execute("UPDATE bk_karten SET pin_hash='', pin_salt='', fehlversuche=0, gesperrt_bis=0 WHERE id=?", (r["id"],))
        con.execute("DELETE FROM bk_entsperrt WHERE konto_id=?", (r["konto_id"],))
        text = "PIN zurückgesetzt"
    else:
        raise web.HTTPBadRequest()
    geld.protokoll(con, k, "Bankkarte " + text, f'{name} (…{r["nummer"][-4:]})')
    con.commit()
    sa.weiter(f"{sa.PFAD}amt/bankkarten/", f"Karte von {name}: {text}.")


def registrieren(app):
    einrichten(app["db"])
    amt.ICONS.setdefault("credit-card", '<rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/>')
    amt.ICONS.setdefault("lock-open", '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>')
    r = app.router
    r.add_get(PFAD, seite)
    r.add_post(PFAD + "beantragen", beantragen_post)
    r.add_post(PFAD + "pin", pin_post)
    r.add_post(PFAD + "sperren", sperren_post)
    r.add_post(PFAD + "abmelden", abmelden_post)
    r.add_get(PFAD + "entsperren", entsperren_seite)
    r.add_post(PFAD + "entsperren", entsperren_post)
    r.add_get(PFAD + "bild", bild)
    r.add_post(PFAD + "verwalten", verwalten_post)
    r.add_get(sa.PFAD + "amt/bankkarten/", verwaltung)
    r.add_get(PRUEF + "{token}", pruefen)
