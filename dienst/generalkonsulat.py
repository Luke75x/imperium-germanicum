"""Kaiserliches Generalkonsulat: eigener Webauftritt unter /regierung/generalkonsulat/ (nginx: /regierung/ → Dienst).

Aufbau nach dem Vorbild der Seite des Auswärtigen Amts (auswaertiges-amt.de), im Design der Website (webseite.seite):
eigene Bereichsleiste (Das Generalkonsulat · Länder & Reisen · Service · Meldungen · Verträge · Intern) mit Suche;
Startseite: Willkommen + Meldungen, „Sicher reisen“ (Länderauswahl, aktuelle Reisewarnungen, drei Lebenslagen-Kacheln),
Leitung, Verträge.

Öffentlich:  Start, /laender/ (A–Z), /laender/<schl>/ (Reise- und Sicherheitshinweise, Beziehungen, Vertretung, Verträge),
             /reisewarnungen/, /meldungen/, /meldungen/<id>/, /vertraege/, /das-generalkonsulat/, /suche/?q=
Angemeldet:  /service/ (Konsularischer Service), /service/antrag/?art=… (Visum/Einreise, Konsularische Hilfe, Beglaubigung,
             Diplomatische Anfrage), /service/meine-antraege/ (+ /<id>/), /krisenvorsorge/ (Krisenvorsorgeliste, wie ELEFAND)
Intern (/intern/…):
  Mitarbeiter = Gruppierungsrolle Generalkonsulat 1561687905812873346 → alles lesen, Meldungen entwerfen, Vermerke zu Anträgen
  Konsul      = 1522702883215249631 → Anträge bearbeiten und entscheiden, Meldungen veröffentlichen, Länder pflegen
                (Reisehinweis bis Stufe 1), Vertragsentwürfe
  Generalkonsul = 1522702617833246822 (Leitung) → zusätzlich Teil-/Reisewarnungen, Beziehungsstatus, Vertragsstatus
                (unterzeichnet/ratifiziert/gekündigt), Konsul je Land zuordnen, Löschen
  Kaiser, Kronkanzler und OOC-Admins (bereiche._alle) haben die Rechte der Leitung.
Benachrichtigungen (Bot-DM): neuer Antrag → Generalkonsul + Konsuln; Entscheidung/Antwort → Antragsteller;
Reisewarnung (Stufe 3) → alle in der Krisenvorsorgeliste für dieses Land Eingetragenen.
Tabellen konsulat_* (NICHT gk_*: das ist das Geldsystem); jede Änderung im Protokoll konsulat_protokoll.
"""
import html
import os
import re
import secrets
import time
from datetime import datetime

from aiohttp import web

import anmeldung
import bereiche
import config
import webseite

esc = html.escape
PFAD = "/regierung/generalkonsulat/"
ROLLE_GENERALKONSUL = "1522702617833246822"
ROLLE_KONSUL = "1522702883215249631"
ROLLE_GRUPPE = "1561687905812873346"
LOGO = os.path.join(config.HIER, "amt_logos", "generalkonsulat-kopf.png")
LOGO_KURZ = os.path.join(config.HIER, "amt_logos", "generalkonsulat-kurz.png")

STUFEN = {0: ("Keine besonderen Hinweise", "gk-s0"), 1: ("Sicherheitshinweis", "gk-s1"),
          2: ("Teilreisewarnung", "gk-s2"), 3: ("Reisewarnung", "gk-s3")}
BEZIEHUNGEN = {"verbuendet": "Verbündet", "befreundet": "Befreundet", "diplomatisch": "Diplomatische Beziehungen",
               "neutral": "Neutral", "angespannt": "Angespannt", "keine": "Keine Beziehungen", "feindlich": "Feindselig"}
ARTEN_LAND = ["Staat", "Gemeinschaft", "Organisation", "Sonstiges"]
MELDUNGSARTEN = {"artikel": "Artikel", "pressemitteilung": "Pressemitteilung", "rede": "Rede", "reise": "Reise und Sicherheit"}
ANTRAGSARTEN = {
    "visum": ("Visum und Einreise", "Für Ausländer: Einreise, Aufenthalt oder Durchreise im Imperium Germanicum beantragen."),
    "hilfe": ("Konsularische Hilfe", "Für Untertanen des Reiches in der Fremde: Beistand in Notlagen, bei Verlust von Papieren oder Festnahme."),
    "beglaubigung": ("Beglaubigung", "Beglaubigung von Urkunden und Erklärungen für den Gebrauch im Ausland."),
    "anfrage": ("Diplomatische Anfrage", "Für Vertreter fremder Staaten und Gemeinschaften: Kontaktaufnahme, Besuch, Gesprächswunsch."),
}
ANTRAGSSTATUS = {"eingegangen": "Eingegangen", "bearbeitung": "In Bearbeitung", "rueckfrage": "Rückfrage",
                 "genehmigt": "Genehmigt", "abgelehnt": "Abgelehnt", "erledigt": "Erledigt"}
OFFEN = ("eingegangen", "bearbeitung", "rueckfrage")
VERTRAGSARTEN = ["Freundschaftsvertrag", "Handelsabkommen", "Beistandspakt", "Nichtangriffspakt", "Konsularabkommen", "Sonstiges Abkommen"]
VERTRAGSSTATUS = {"entwurf": "Entwurf", "verhandlung": "In Verhandlung", "unterzeichnet": "Unterzeichnet",
                  "ratifiziert": "In Kraft", "gekuendigt": "Gekündigt"}
VERTRAG_LEITUNG = {"unterzeichnet", "ratifiziert", "gekuendigt"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS konsulat_laender (
    id INTEGER PRIMARY KEY AUTOINCREMENT, schl TEXT NOT NULL UNIQUE, name TEXT NOT NULL, art TEXT NOT NULL DEFAULT 'Staat',
    hauptstadt TEXT NOT NULL DEFAULT '', oberhaupt TEXT NOT NULL DEFAULT '', beziehung TEXT NOT NULL DEFAULT 'neutral',
    stufe INTEGER NOT NULL DEFAULT 0, hinweise TEXT NOT NULL DEFAULT '', einreise TEXT NOT NULL DEFAULT '', info TEXT NOT NULL DEFAULT '',
    vertretung TEXT NOT NULL DEFAULT '', konsul_id TEXT NOT NULL DEFAULT '', konsul_name TEXT NOT NULL DEFAULT '',
    aktualisiert INTEGER NOT NULL, hinweise_zeit INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS konsulat_meldungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, titel TEXT NOT NULL, art TEXT NOT NULL DEFAULT 'artikel', kurz TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '', land_id INTEGER, status TEXT NOT NULL DEFAULT 'entwurf', autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '',
    erstellt INTEGER NOT NULL, veroeffentlicht INTEGER);
CREATE TABLE IF NOT EXISTS konsulat_antraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, az TEXT NOT NULL UNIQUE, art TEXT NOT NULL, konto_id TEXT NOT NULL, name TEXT NOT NULL,
    land_id INTEGER, betreff TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'eingegangen',
    bearbeiter_id TEXT NOT NULL DEFAULT '', bearbeiter_name TEXT NOT NULL DEFAULT '', erstellt INTEGER NOT NULL, aktualisiert INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS konsulat_antrag_eintraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, antrag_id INTEGER NOT NULL, zeit INTEGER NOT NULL, art TEXT NOT NULL,
    text TEXT NOT NULL, intern INTEGER NOT NULL DEFAULT 0, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS konsulat_vorsorge (
    id INTEGER PRIMARY KEY AUTOINCREMENT, konto_id TEXT NOT NULL, name TEXT NOT NULL, land_id INTEGER NOT NULL,
    von TEXT NOT NULL DEFAULT '', bis TEXT NOT NULL DEFAULT '', notiz TEXT NOT NULL DEFAULT '', erstellt INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS konsulat_vertraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, titel TEXT NOT NULL, land_id INTEGER, art TEXT NOT NULL DEFAULT 'Sonstiges Abkommen',
    status TEXT NOT NULL DEFAULT 'entwurf', text TEXT NOT NULL DEFAULT '', oeffentlich INTEGER NOT NULL DEFAULT 0, datum TEXT NOT NULL DEFAULT '',
    erstellt INTEGER NOT NULL, aktualisiert INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS konsulat_protokoll (
    id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '', text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS konsulat_antrag_eintraege_a ON konsulat_antrag_eintraege (antrag_id);
CREATE INDEX IF NOT EXISTS konsulat_vorsorge_land ON konsulat_vorsorge (land_id);
"""

CSS = """<style>
.gk-leiste{background:var(--navy-950);color:#fff;position:relative;z-index:5}
.gk-leiste .wrap{display:flex;align-items:center;gap:6px;flex-wrap:wrap;min-height:58px}
.gk-marke{display:flex;align-items:center;gap:10px;color:#fff;text-decoration:none;margin-right:14px;padding:8px 0}
.gk-marke img{height:34px;width:auto;filter:brightness(0) invert(1)}
@media(max-width:860px){.gk-suche input{width:100px}.gk-marke span{font-size:.95rem}}
.gk-marke span{font:500 1.05rem/1.1 var(--serif);letter-spacing:.02em}
.gk-marke small{display:block;font:500 .66rem/1.2 var(--sans);letter-spacing:.18em;text-transform:uppercase;color:var(--gold-300)}
.gk-nav{display:flex;flex-wrap:wrap;gap:2px;flex:1}
.gk-nav a{color:rgba(255,255,255,.82);text-decoration:none;padding:9px 12px;font:500 .9rem var(--sans);border-bottom:2px solid transparent}
.gk-nav a:hover{color:#fff}.gk-nav a[aria-current]{color:#fff;border-bottom-color:var(--gold-500)}
.gk-suche{display:flex;gap:0}.gk-suche input{width:170px;min-height:38px;border:1px solid rgba(255,255,255,.3);background:rgba(255,255,255,.08);color:#fff;padding:6px 10px;font:inherit;font-size:.9rem}
.gk-suche input::placeholder{color:rgba(255,255,255,.6)}
.gk-suche button{min-height:38px;border:0;background:var(--gold-500);color:var(--navy-950);padding:0 12px;font:600 .85rem var(--sans);cursor:pointer}
@media(max-width:860px){.gk-nav{order:3;flex-basis:100%;overflow-x:auto;flex-wrap:nowrap}.gk-nav a{white-space:nowrap}.gk-suche{margin-left:auto}.gk-suche input{width:120px}}
.gk-held{background:var(--navy-900);color:rgba(255,255,255,.85);padding:clamp(36px,6vw,72px) 0}
.gk-held h1{color:#fff;margin:6px 0 10px}.gk-held .eyebrow{color:var(--gold-300)}
.gk-held .wrap{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:32px;align-items:center}
.gk-held img{height:clamp(90px,14vw,160px);width:auto;filter:brightness(0) invert(1);opacity:.9}
@media(max-width:700px){.gk-held .wrap{grid-template-columns:1fr}.gk-held img{display:none}}
.gk-teaser{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:22px}
.gk-tkarte{display:flex;flex-direction:column;border:1px solid var(--rule);background:var(--white);padding:20px 22px;color:var(--ink);text-decoration:none;border-radius:var(--radius);transition:border-color .2s}
.gk-tkarte:hover{border-color:var(--rule-strong)}
.gk-tkarte h3{font-size:1.25rem;margin:6px 0 8px}.gk-tkarte p{color:var(--ink-2);margin:0 0 10px;flex:1}
.gk-art{font:600 .7rem/1 var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--gold-600)}
.gk-datum{font-size:.85rem;color:var(--muted)}
.gk-liste{list-style:none;margin:0;padding:0;border-top:1px solid var(--rule)}
.gk-liste li{border-bottom:1px solid var(--rule);padding:12px 0;display:flex;gap:16px;justify-content:space-between;align-items:baseline;flex-wrap:wrap}
.gk-liste a{color:var(--ink);text-decoration:none;font-weight:500}.gk-liste a:hover{color:var(--gold-600)}
.gk-reisen{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:clamp(24px,4vw,48px)}
@media(max-width:860px){.gk-reisen{grid-template-columns:1fr}}
.gk-wahl{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 18px}.gk-wahl select{min-height:46px;font-size:16px;padding:8px 12px;min-width:min(100%,300px);flex:1}
.gk-kacheln{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,240px),1fr));gap:18px;margin-top:28px}
.gk-kachel{border:1px solid var(--rule);background:var(--white);padding:18px 20px;border-radius:var(--radius)}
.gk-kachel h3{font-size:1.15rem;margin:0 0 10px}.gk-kachel ul{margin:0;padding:0;list-style:none}.gk-kachel li{padding:4px 0}
.gk-kachel a{color:var(--navy-800)}
.gk-stufe{display:inline-block;font:600 .72rem/1 var(--sans);letter-spacing:.08em;text-transform:uppercase;padding:5px 8px;border-radius:2px;white-space:nowrap}
.gk-s0{background:var(--success-bg);color:var(--success)}.gk-s1{background:#eef1f8;color:var(--navy-800)}
.gk-s2{background:#fbf1dc;color:#8a5a00}.gk-s3{background:var(--danger-bg);color:var(--danger)}
.gk-warnbox{border:1px solid var(--rule);border-left:4px solid var(--flag);background:var(--paper);padding:14px 18px;margin:0 0 22px}
.gk-warnbox.gk-w3{border-left-color:var(--danger);background:var(--danger-bg)}.gk-warnbox.gk-w2{border-left-color:#c98a00;background:#fbf1dc}
.gk-az{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:4px 28px}
.gk-az h3{grid-column:1/-1;margin:22px 0 6px;font-size:1.3rem;border-bottom:1px solid var(--rule);padding-bottom:4px}
.gk-az a{display:flex;justify-content:space-between;gap:8px;padding:7px 0;color:var(--ink);text-decoration:none}.gk-az a:hover{color:var(--gold-600)}
.gk-text{max-width:760px}.gk-text p{margin:0 0 1em;white-space:pre-line}
.gk-daten{display:grid;grid-template-columns:minmax(0,220px) minmax(0,1fr);border-top:1px solid var(--rule);margin:0 0 28px}
.gk-daten dt,.gk-daten dd{margin:0;padding:10px 0;border-bottom:1px solid var(--rule)}.gk-daten dt{color:var(--muted);padding-right:14px}
@media(max-width:520px){.gk-daten{grid-template-columns:1fr}.gk-daten dt{border:0;padding-bottom:0}}
.gk-reiter{display:flex;gap:2px;border-bottom:1px solid var(--rule);margin:0 0 26px;overflow-x:auto}
.gk-reiter a{padding:10px 14px;color:var(--muted);text-decoration:none;border-bottom:2px solid transparent;white-space:nowrap;font:500 .95rem var(--sans)}
.gk-reiter a[aria-current]{color:var(--ink);border-bottom-color:var(--gold-500)}
.gk-tab{width:100%;border-collapse:collapse;font:.95rem var(--sans);margin:0 0 24px}
.gk-tab th,.gk-tab td{text-align:left;padding:9px 10px 9px 0;border-bottom:1px solid var(--rule);vertical-align:top}
.gk-tab th{font-weight:600;color:var(--muted);font-size:.82rem;text-transform:uppercase;letter-spacing:.06em}
@media(max-width:700px){.gk-tab thead{display:none}.gk-tab tr{display:block;border-bottom:1px solid var(--rule);padding:8px 0}.gk-tab td{display:block;border:0;padding:2px 0}}
.gk-form{display:grid;gap:14px;max-width:760px;margin:0 0 30px}
.gk-form label{display:grid;gap:5px;font:600 .88rem var(--sans);color:var(--ink-2)}
.gk-form input,.gk-form select,.gk-form textarea{font:inherit;font-weight:400;font-size:16px;padding:9px 11px;border:1px solid var(--rule-strong);background:var(--white);color:var(--ink);border-radius:2px;width:100%;box-sizing:border-box}
.gk-form textarea{min-height:130px;resize:vertical}.gk-form .gk-zwei{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:600px){.gk-form .gk-zwei{grid-template-columns:1fr}}
.gk-form .gk-check{display:flex;gap:8px;align-items:center;font-weight:400}.gk-form .gk-check input{width:auto}
.gk-knoepfe{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.gk-meldung{border:1px solid var(--rule);border-left:4px solid var(--success);background:var(--success-bg);padding:10px 14px;margin:0 0 20px}
.gk-meldung.fehler{border-left-color:var(--danger);background:var(--danger-bg)}
.gk-hinweis{color:var(--muted);border-left:2px solid var(--gold-500);padding:4px 0 4px 14px;margin:0 0 26px}
.gk-zahlen{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin:0 0 28px}
.gk-zahlen a,.gk-zahlen div{display:block;border:1px solid var(--rule);background:var(--white);padding:14px 16px;color:var(--muted);text-decoration:none;font:.85rem var(--sans)}
.gk-zahlen b{display:block;font:600 1.6rem/1.2 var(--serif);color:var(--ink)}
.gk-verlauf{list-style:none;margin:0 0 26px;padding:0;border-left:2px solid var(--rule)}
.gk-verlauf li{padding:8px 0 10px 16px;position:relative}.gk-verlauf li::before{content:"";position:absolute;left:-6px;top:14px;width:10px;height:10px;border-radius:50%;background:var(--navy-700)}
.gk-verlauf li.intern::before{background:var(--gold-500)}.gk-verlauf small{color:var(--muted);display:block}
.gk-verlauf p{margin:4px 0 0;white-space:pre-line}
.gk-personen{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:16px}
.gk-person{border:1px solid var(--rule);background:var(--white);padding:16px 18px}.gk-person b{display:block;font:500 1.2rem var(--serif)}
.gk-person span{color:var(--muted);font-size:.9rem}
.gk-inline{display:inline}.gk-inline button{background:none;border:0;color:var(--danger);cursor:pointer;font:inherit;padding:0}
</style>"""

NAV = [("start", "", "Das Generalkonsulat"), ("laender", "laender/", "Länder & Reisen"), ("service", "service/", "Service"),
       ("meldungen", "meldungen/", "Meldungen"), ("vertraege", "vertraege/", "Verträge")]


# ---------------------------------------------------------------- Rechte

def stufe(k):
    """'leitung' | 'konsul' | 'mitarbeiter' | None."""
    if not k or not k["mitglied"]:
        return None
    r = set(k["rollen"])
    if bereiche._alle(k) or ROLLE_GENERALKONSUL in r:
        return "leitung"
    if ROLLE_KONSUL in r:
        return "konsul"
    if ROLLE_GRUPPE in r:
        return "mitarbeiter"
    return None


def ist_leitung(k):
    return stufe(k) == "leitung"


def ist_konsul(k):
    return stufe(k) in ("leitung", "konsul")


def ist_mitarbeiter(k):
    return stufe(k) is not None


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Hilfen

def _datum(ts, uhr=False):
    if not ts:
        return "–"
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y, %H:%M Uhr" if uhr else "%d.%m.%Y")


def _absatz(t):
    return "".join(f"<p>{esc(a)}</p>" for a in re.split(r"\n\s*\n", (t or "").strip()) if a.strip())


def _schl(name):
    s = name.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "land"


def _stufe_html(n):
    t, kl = STUFEN.get(n, STUFEN[0])
    return f'<span class="gk-stufe {kl}">{esc(t)}</span>'


def _opt(werte, aktuell):
    """werte: Liste von (wert, text)."""
    return "".join(f'<option value="{esc(str(w))}"{" selected" if str(w) == str(aktuell) else ""}>{esc(t)}</option>' for w, t in werte)


def _laender(con):
    return con.execute("SELECT * FROM konsulat_laender ORDER BY name COLLATE NOCASE").fetchall()


def _land(con, i):
    return con.execute("SELECT * FROM konsulat_laender WHERE id=?", (i,)).fetchone() if i else None


def _protokoll(con, k, text):
    con.execute("INSERT INTO konsulat_protokoll (zeit, autor_id, autor_name, text) VALUES (?,?,?,?)", (int(time.time()), k["id"], k["name"], text))


def _leiste(aktiv, k, q=""):
    links = [(s, u, t) for s, u, t in NAV] + ([("intern", "intern/", "Intern")] if ist_mitarbeiter(k) else [])
    nav = "".join(f'<a href="{PFAD}{u}"{" aria-current=\"page\"" if s == aktiv else ""}>{esc(t)}</a>' for s, u, t in links)
    return (f'<div class="gk-leiste"><div class="wrap"><a class="gk-marke" href="{PFAD}"><img src="{PFAD}logo-kurz.png" alt="">'
            f'<span><small>Imperium Germanicum</small>Kaiserliches Generalkonsulat</span></a><nav class="gk-nav" aria-label="Generalkonsulat">{nav}</nav>'
            f'<form class="gk-suche" action="{PFAD}suche/" role="search"><input name="q" value="{esc(q)}" placeholder="Wonach suchen Sie?" aria-label="Suche">'
            '<button type="submit">Suchen</button></form></div></div>')


def _kopf(titel, pfad, lead="", eyebrow=""):
    kr = "".join(f'<li><a href="{esc(u)}">{esc(t)}</a></li>' if u else f'<li><span aria-current="page">{esc(t)}</span></li>'
                 for t, u in [("Hauptseite", "/"), ("Generalkonsulat", PFAD)] + pfad)
    return (f'<div class="page-head"><div class="wrap"><nav class="breadcrumb" aria-label="Brotkrumen"><ol>{kr}</ol></nav>'
            f'{f"<span class=eyebrow>{esc(eyebrow)}</span>" if eyebrow else ""}<h1>{esc(titel)}</h1>{f"<p class=lead>{lead}</p>" if lead else ""}</div></div>')


def _antwort(request, k, aktiv, titel, inhalt, q=""):
    m = request.query.get("m")
    f = request.query.get("f")
    note = (f'<div class="wrap" style="margin-top:20px"><div class="gk-meldung">{esc(m)}</div></div>' if m else "") + \
           (f'<div class="wrap" style="margin-top:20px"><div class="gk-meldung fehler">{esc(f)}</div></div>' if f else "")
    if _ooc(k):
        note = '<div class="wrap" style="margin-top:16px"><div class="gk-hinweis">OOC-Zugang als Serveradministrator.</div></div>' + note
    return webseite.antwort(titel + " – Generalkonsulat", _leiste(aktiv, k, q) + note + inhalt, CSS)


def ist_konsul_rolle(k):
    return bool(k) and bool({ROLLE_GENERALKONSUL, ROLLE_KONSUL} & set(k["rollen"]))


def _ooc(k):
    import amt
    return amt.ist_ooc_admin(k)


def _abschnitt(inhalt, klasse="section tight"):
    return f'<section class="{klasse}"><div class="wrap">{inhalt}</div></section>'


async def _namen_mit_rolle(request, rolle):
    try:
        return sorted(m["name"] for m in await request.app["discord"].mitglieder() if rolle in m["rollen"])
    except Exception:
        return []


async def _post(request, pruefung=None):
    k = await anmeldung.konto(request)
    if not k or not k["mitglied"]:
        raise web.HTTPForbidden(text="Bitte anmelden.")
    if pruefung and not pruefung(k):
        raise web.HTTPForbidden(text="Dafür fehlt dir die Berechtigung.")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), str(request.get("csrf", ""))):
        raise web.HTTPForbidden(text="Sitzung abgelaufen – bitte neu laden.")
    return k, form


def _csrf(request):
    return f'<input type="hidden" name="csrf" value="{esc(request.get("csrf", ""))}">'


def _weiter(url, m=None, f=None):
    from urllib.parse import quote
    zus = (f"m={quote(m)}" if m else "") + (f"f={quote(f)}" if f else "")
    raise web.HTTPSeeOther(url + (("&" if "?" in url else "?") + zus if zus else ""))


async def _konto_oder_login(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    return k


def _meldung_karte(m, laender):
    land = laender.get(m["land_id"])
    return (f'<a class="gk-tkarte" href="{PFAD}meldungen/{m["id"]}/"><span class="gk-art">{esc(MELDUNGSARTEN.get(m["art"], "Artikel"))}'
            f'{" · " + esc(land["name"]) if land else ""}</span><h3>{esc(m["titel"])}</h3><p>{esc(m["kurz"])}</p>'
            f'<span class="gk-datum">{_datum(m["veroeffentlicht"])}</span></a>')


# ---------------------------------------------------------------- Öffentlich

async def logo(request):
    datei = LOGO_KURZ if request.match_info.get("art") == "-kurz" else LOGO
    if not os.path.exists(datei):
        raise web.HTTPNotFound()
    return web.FileResponse(datei, headers={"Cache-Control": "no-cache"})


async def weiterleiten(request):
    raise web.HTTPMovedPermanently(PFAD)


async def start(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    laender = {l["id"]: l for l in _laender(con)}
    ms = con.execute("SELECT * FROM konsulat_meldungen WHERE status='veroeffentlicht' ORDER BY veroeffentlicht DESC LIMIT 9").fetchall()
    held = (f'<div class="gk-held"><div class="wrap"><div><span class="eyebrow">Imperium Germanicum</span>'
            '<h1>Willkommen auf den Seiten des Kaiserlichen Generalkonsulats</h1>'
            '<p class="lead" style="color:rgba(255,255,255,.8)">Das Generalkonsulat vertritt das Reich und seine Untertanen in der Fremde, '
            'pflegt die Verbindungen zu befreundeten Staaten und Gemeinschaften und steht Reisenden mit Rat und Beistand zur Seite.</p></div>'
            f'<img src="{PFAD}logo.png" alt=""></div></div>')
    if ms:
        neu = '<div class="gk-teaser">' + "".join(_meldung_karte(m, laender) for m in ms[:3]) + "</div>"
        if ms[3:]:
            neu += ('<h3 style="margin:34px 0 10px">Weitere Meldungen</h3><ul class="gk-liste">'
                    + "".join(f'<li><a href="{PFAD}meldungen/{m["id"]}/">{esc(m["titel"])}</a><span class="gk-datum">'
                              f'{esc(MELDUNGSARTEN.get(m["art"], ""))} · {_datum(m["veroeffentlicht"])}</span></li>' for m in ms[3:]) + "</ul>")
        neu += f'<p style="margin-top:18px"><a class="link-arrow" href="{PFAD}meldungen/">Alle Meldungen</a></p>'
    else:
        neu = '<p class="gk-hinweis">Noch keine Meldungen veröffentlicht.</p>'
    meldungen = _abschnitt('<div class="section-head"><span class="eyebrow">Newsroom</span><h2>Aktuelles aus dem Generalkonsulat</h2></div>' + neu)

    warn = [l for l in laender.values() if l["stufe"] >= 2]
    warn.sort(key=lambda l: (-l["stufe"], l["name"]))
    sel = _opt([("", "Land auswählen …")] + [(l["schl"], l["name"]) for l in laender.values()], "")
    warnliste = ('<ul class="gk-liste">' + "".join(f'<li><a href="{PFAD}laender/{esc(l["schl"])}/">{esc(l["name"])}</a>{_stufe_html(l["stufe"])}</li>'
                                                    for l in warn[:8]) + "</ul>") if warn else '<p class="gk-hinweis">Zurzeit bestehen keine Reisewarnungen.</p>'
    reisen = _abschnitt(
        '<div class="gk-reisen"><div><span class="eyebrow">Sicher reisen</span><h2>Reise- und Sicherheitshinweise</h2>'
        '<p>Informieren Sie sich vor jeder Reise über die Lage in Ihrem Reiseland, die Einreisebestimmungen und die Vertretung des Reiches vor Ort.</p>'
        f'<form class="gk-wahl" onsubmit="if(this.l.value)location.href=\'{PFAD}laender/\'+this.l.value+\'/\';return false">'
        f'<select name="l" aria-label="Reiseland">{sel}</select><button class="btn btn-navy" type="submit">Suchen</button></form>'
        f'<p><a class="link-arrow" href="{PFAD}laender/">Alle Länder A–Z</a></p></div>'
        f'<div><h3>Aktuelle Reisewarnungen</h3>{warnliste}<p style="margin-top:14px"><a class="btn btn-line btn-small" href="{PFAD}reisewarnungen/">Alle Reisewarnungen</a></p></div></div>'
        '<div class="gk-kacheln">'
        f'<div class="gk-kachel"><h3>Sie sind in der Fremde?</h3><ul><li><a href="{PFAD}service/antrag/?art=hilfe">Konsularische Hilfe</a></li>'
        f'<li><a href="{PFAD}krisenvorsorge/">Krisenvorsorgeliste</a></li></ul></div>'
        f'<div class="gk-kachel"><h3>Sie wollen verreisen?</h3><ul><li><a href="{PFAD}laender/">Länderinformationen</a></li>'
        f'<li><a href="{PFAD}reisewarnungen/">Reisewarnungen</a></li><li><a href="{PFAD}service/antrag/?art=beglaubigung">Beglaubigung</a></li></ul></div>'
        f'<div class="gk-kachel"><h3>Sie wollen ins Reich kommen?</h3><ul><li><a href="{PFAD}service/antrag/?art=visum">Visum und Einreise</a></li>'
        f'<li><a href="{PFAD}service/antrag/?art=anfrage">Diplomatische Anfrage</a></li></ul></div></div>', "section tight paper")

    gk = await _namen_mit_rolle(request, ROLLE_GENERALKONSUL)
    leitung = _abschnitt(
        '<div class="gk-reisen"><div><span class="eyebrow">Leitung</span><h2>' + (esc(", ".join(gk)) if gk else "Das Amt des Generalkonsuls ist zurzeit unbesetzt") +
        '</h2><p>Der Generalkonsul leitet das Kaiserliche Generalkonsulat; ihm unterstehen die Konsuln des Reiches. Der Souverän ernennt und entlässt '
        'die Konsuln, der Kronkanzler verwaltet sie in seinem Namen.</p>'
        f'<p><a class="link-arrow" href="{PFAD}das-generalkonsulat/">Das Generalkonsulat und seine Konsuln</a></p></div>'
        + _vertraege_kurz(con, laender) + '</div>')
    return _antwort(request, k, "start", "Startseite", held + meldungen + reisen + leitung)


def _vertraege_kurz(con, laender):
    vs = con.execute("SELECT * FROM konsulat_vertraege WHERE oeffentlich=1 AND status IN ('unterzeichnet','ratifiziert') ORDER BY aktualisiert DESC LIMIT 5").fetchall()
    if not vs:
        return '<div><h3>Verträge und Abkommen</h3><p class="gk-hinweis">Noch keine veröffentlichten Verträge.</p></div>'
    return ('<div><h3>Verträge und Abkommen</h3><ul class="gk-liste">'
            + "".join(f'<li><a href="{PFAD}vertraege/#v{v["id"]}">{esc(v["titel"])}</a><span class="gk-datum">'
                      f'{esc(laender[v["land_id"]]["name"]) if v["land_id"] in laender else ""} · {esc(VERTRAGSSTATUS[v["status"]])}</span></li>' for v in vs)
            + f'</ul><p style="margin-top:14px"><a class="link-arrow" href="{PFAD}vertraege/">Alle Verträge</a></p></div>')


async def laender_liste(request):
    k = await anmeldung.konto(request)
    ls = _laender(request.app["db"])
    if ls:
        teile, buchst = [], None
        for l in ls:
            b = (l["name"][:1] or "#").upper().replace("Ä", "A").replace("Ö", "O").replace("Ü", "U")
            if b != buchst:
                teile.append(f"<h3>{esc(b)}</h3>")
                buchst = b
            teile.append(f'<a href="{PFAD}laender/{esc(l["schl"])}/"><span>{esc(l["name"])}</span>{_stufe_html(l["stufe"]) if l["stufe"] else ""}</a>')
        inhalt = '<div class="gk-az">' + "".join(teile) + "</div>"
    else:
        inhalt = '<p class="gk-hinweis">Das Generalkonsulat hat noch keine Länderinformationen veröffentlicht.</p>'
    kopf = _kopf("Länderinformationen A–Z", [("Länder & Reisen", None)],
                 "Reise- und Sicherheitshinweise, Einreisebestimmungen, Beziehungen zum Reich und die Vertretungen des Reiches – für alle Staaten und Gemeinschaften, mit denen das Reich in Verbindung steht.",
                 "Sicher reisen")
    return _antwort(request, k, "laender", "Länder", kopf + _abschnitt(
        f'<p><a class="btn btn-line btn-small" href="{PFAD}reisewarnungen/">Aktuelle Reisewarnungen</a></p>' + inhalt))


async def land_seite(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    l = con.execute("SELECT * FROM konsulat_laender WHERE schl=?", (request.match_info["schl"],)).fetchone()
    if not l:
        raise web.HTTPNotFound(text="Land nicht gefunden.")
    reiter = request.query.get("t", "reise")
    tabs = [("reise", "Reise- und Sicherheitshinweise"), ("beziehungen", "Beziehungen zum Reich"), ("vertretung", "Vertretung")]
    leiste = '<div class="gk-reiter">' + "".join(f'<a href="?t={s}"{" aria-current=\"page\"" if s == reiter else ""}>{t}</a>' for s, t in tabs) + "</div>"
    if reiter == "beziehungen":
        vs = con.execute("SELECT * FROM konsulat_vertraege WHERE land_id=? AND oeffentlich=1 ORDER BY aktualisiert DESC", (l["id"],)).fetchall()
        ms = con.execute("SELECT * FROM konsulat_meldungen WHERE land_id=? AND status='veroeffentlicht' ORDER BY veroeffentlicht DESC LIMIT 10", (l["id"],)).fetchall()
        teil = (f'<dl class="gk-daten"><dt>Art</dt><dd>{esc(l["art"])}</dd><dt>Hauptstadt / Sitz</dt><dd>{esc(l["hauptstadt"] or "–")}</dd>'
                f'<dt>Staatsoberhaupt</dt><dd>{esc(l["oberhaupt"] or "–")}</dd><dt>Beziehungen zum Reich</dt><dd>{esc(BEZIEHUNGEN.get(l["beziehung"], l["beziehung"]))}</dd></dl>'
                f'<div class="gk-text">{_absatz(l["info"]) or "<p class=gk-hinweis>Noch keine Angaben zu den bilateralen Beziehungen.</p>"}</div>')
        if vs:
            teil += ('<h3>Verträge und Abkommen</h3><table class="gk-tab"><tbody>' + "".join(
                f'<tr><td><a href="{PFAD}vertraege/#v{v["id"]}">{esc(v["titel"])}</a></td><td>{esc(v["art"])}</td><td>{esc(VERTRAGSSTATUS[v["status"]])}</td></tr>' for v in vs)
                + "</tbody></table>")
        if ms:
            teil += '<h3>Meldungen</h3><ul class="gk-liste">' + "".join(
                f'<li><a href="{PFAD}meldungen/{m["id"]}/">{esc(m["titel"])}</a><span class="gk-datum">{_datum(m["veroeffentlicht"])}</span></li>' for m in ms) + "</ul>"
    elif reiter == "vertretung":
        teil = (f'<dl class="gk-daten"><dt>Zuständiger Konsul</dt><dd>{esc(l["konsul_name"] or "Das Generalkonsulat (unmittelbar)")}</dd></dl>'
                f'<div class="gk-text">{_absatz(l["vertretung"]) or "<p class=gk-hinweis>Das Reich unterhält hier kein eigenes Konsulat. Zuständig ist das Generalkonsulat.</p>"}</div>'
                f'<p><a class="btn btn-navy" href="{PFAD}service/antrag/?art=hilfe&land={l["id"]}">Konsularische Hilfe anfordern</a></p>')
    else:
        stand = f'Stand: {_datum(l["hinweise_zeit"] or l["aktualisiert"], True)} – unverändert gültig.'
        kl = {3: " gk-w3", 2: " gk-w2"}.get(l["stufe"], "")
        warn = ""
        if l["stufe"] == 3:
            warn = f'<div class="gk-warnbox gk-w3"><strong>Reisewarnung:</strong> Vor Reisen nach {esc(l["name"])} wird gewarnt.</div>'
        elif l["stufe"] == 2:
            warn = f'<div class="gk-warnbox gk-w2"><strong>Teilreisewarnung:</strong> Für Teile von {esc(l["name"])} wird von Reisen abgeraten.</div>'
        teil = (f'<p>{_stufe_html(l["stufe"])} <span class="gk-datum">{stand}</span></p>{warn}'
                f'<h3>Sicherheit</h3><div class="gk-text">{_absatz(l["hinweise"]) or "<p>Keine besonderen Hinweise.</p>"}</div>'
                f'<h3>Einreise und Zoll</h3><div class="gk-text">{_absatz(l["einreise"]) or "<p>Keine besonderen Bestimmungen bekannt.</p>"}</div>'
                f'<div class="gk-warnbox{kl if l["stufe"] else ""}">Sie reisen nach {esc(l["name"])}? Tragen Sie sich in die '
                f'<a href="{PFAD}krisenvorsorge/?land={l["id"]}">Krisenvorsorgeliste</a> ein, damit das Generalkonsulat Sie in einer Krise erreichen kann.</div>')
    bearb = f'<p><a class="btn btn-line btn-small" href="{PFAD}intern/laender/{l["id"]}/">Intern bearbeiten</a></p>' if ist_konsul(k) else ""
    kopf = _kopf(l["name"], [("Länder & Reisen", PFAD + "laender/"), (l["name"], None)], "", "Länderinformation")
    return _antwort(request, k, "laender", l["name"], kopf + _abschnitt(leiste + teil + bearb))


async def reisewarnungen(request):
    k = await anmeldung.konto(request)
    ls = [l for l in _laender(request.app["db"]) if l["stufe"] > 0]
    ls.sort(key=lambda l: (-l["stufe"], l["name"]))
    if ls:
        inhalt = ('<table class="gk-tab"><thead><tr><th>Land</th><th>Stufe</th><th>Stand</th></tr></thead><tbody>' + "".join(
            f'<tr><td><a href="{PFAD}laender/{esc(l["schl"])}/">{esc(l["name"])}</a></td><td>{_stufe_html(l["stufe"])}</td>'
            f'<td>{_datum(l["hinweise_zeit"] or l["aktualisiert"])}</td></tr>' for l in ls) + "</tbody></table>")
    else:
        inhalt = '<p class="gk-hinweis">Zurzeit bestehen weder Reisewarnungen noch Sicherheitshinweise.</p>'
    stufen = "".join(f"<dt>{_stufe_html(n)}</dt><dd>{esc(t)}</dd>" for n, t in [
        (1, "Hinweis auf besondere Gefahren; Reisen sind möglich."), (2, "Von Reisen in bestimmte Landesteile wird abgeraten."),
        (3, "Vor Reisen in das ganze Land wird gewarnt; Untertanen des Reiches werden zur Ausreise aufgefordert.")])
    kopf = _kopf("Aktuelle Reisewarnungen", [("Länder & Reisen", PFAD + "laender/"), ("Reisewarnungen", None)],
                 "Das Generalkonsulat warnt vor Reisen, wenn Leib und Leben der Untertanen des Reiches in Gefahr sind.", "Sicher reisen")
    return _antwort(request, k, "laender", "Reisewarnungen", kopf + _abschnitt(inhalt + f'<h3>Die Stufen</h3><dl class="gk-daten">{stufen}</dl>'))


async def meldungen_liste(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    laender = {l["id"]: l for l in _laender(con)}
    art = request.query.get("art", "")
    sql, par = "SELECT * FROM konsulat_meldungen WHERE status='veroeffentlicht'", []
    if art in MELDUNGSARTEN:
        sql += " AND art=?"
        par.append(art)
    ms = con.execute(sql + " ORDER BY veroeffentlicht DESC LIMIT 200", par).fetchall()
    filt = '<div class="gk-reiter">' + "".join(f'<a href="?art={a}"{" aria-current=\"page\"" if a == art else ""}>{t}</a>'
                                               for a, t in [("", "Alle")] + list(MELDUNGSARTEN.items())) + "</div>"
    inhalt = ('<div class="gk-teaser">' + "".join(_meldung_karte(m, laender) for m in ms) + "</div>") if ms else '<p class="gk-hinweis">Keine Meldungen.</p>'
    kopf = _kopf("Meldungen", [("Meldungen", None)], "Artikel, Pressemitteilungen, Reden und Hinweise des Kaiserlichen Generalkonsulats.", "Newsroom")
    return _antwort(request, k, "meldungen", "Meldungen", kopf + _abschnitt(filt + inhalt))


async def meldung_seite(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    m = con.execute("SELECT * FROM konsulat_meldungen WHERE id=?", (request.match_info["id"],)).fetchone()
    if not m or (m["status"] != "veroeffentlicht" and not ist_mitarbeiter(k)):
        raise web.HTTPNotFound(text="Meldung nicht gefunden.")
    land = _land(con, m["land_id"])
    entwurf = '<div class="gk-warnbox">Entwurf – noch nicht veröffentlicht.</div>' if m["status"] != "veroeffentlicht" else ""
    kopf = _kopf(m["titel"], [("Meldungen", PFAD + "meldungen/"), (MELDUNGSARTEN.get(m["art"], "Artikel"), None)],
                 esc(m["kurz"]), MELDUNGSARTEN.get(m["art"], "Artikel"))
    landlink = f' · <a href="{PFAD}laender/{esc(land["schl"])}/">{esc(land["name"])}</a>' if land else ""
    fuss = f'<p class="gk-datum">{_datum(m["veroeffentlicht"] or m["erstellt"], True)}{landlink}</p>'
    bearb = f'<p><a class="btn btn-line btn-small" href="{PFAD}intern/meldungen/{m["id"]}/">Intern bearbeiten</a></p>' if ist_mitarbeiter(k) else ""
    return _antwort(request, k, "meldungen", m["titel"], kopf + _abschnitt(entwurf + fuss + f'<div class="gk-text">{_absatz(m["text"])}</div>' + bearb))


async def vertraege(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    laender = {l["id"]: l for l in _laender(con)}
    vs = con.execute("SELECT * FROM konsulat_vertraege WHERE oeffentlich=1 ORDER BY CASE status WHEN 'ratifiziert' THEN 0 WHEN 'unterzeichnet' THEN 1 ELSE 2 END, aktualisiert DESC").fetchall()
    if vs:
        inhalt = "".join(
            f'<article id="v{v["id"]}" class="gk-kachel" style="margin:0 0 18px"><span class="gk-art">{esc(v["art"])} · {esc(VERTRAGSSTATUS[v["status"]])}</span>'
            f'<h3 style="margin-top:6px">{esc(v["titel"])}</h3><p class="gk-datum">'
            f'{"Vertragspartner: " + esc(laender[v["land_id"]]["name"]) if v["land_id"] in laender else ""}{" · " + esc(v["datum"]) if v["datum"] else ""}</p>'
            f'<div class="gk-text">{_absatz(v["text"])}</div></article>' for v in vs)
    else:
        inhalt = '<p class="gk-hinweis">Es sind noch keine Verträge veröffentlicht.</p>'
    kopf = _kopf("Verträge und Abkommen", [("Verträge", None)], "Die vom Reich geschlossenen und veröffentlichten Verträge mit fremden Staaten und Gemeinschaften.", "Vertragssammlung")
    return _antwort(request, k, "vertraege", "Verträge", kopf + _abschnitt(inhalt))


async def ueber(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    gk = await _namen_mit_rolle(request, ROLLE_GENERALKONSUL)
    ks = await _namen_mit_rolle(request, ROLLE_KONSUL)
    zust = {}
    for l in _laender(con):
        if l["konsul_name"]:
            zust.setdefault(l["konsul_name"], []).append(l["name"])
    personen = "".join(f'<div class="gk-person"><b>{esc(n)}</b><span>Generalkonsul</span></div>' for n in gk)
    personen += "".join(f'<div class="gk-person"><b>{esc(n)}</b><span>Konsul{" · " + esc(", ".join(zust[n])) if n in zust else ""}</span></div>' for n in ks)
    aufgaben = ["Vertritt das Reich und seine Untertanen im Ausland und stellt ihnen Schutz und Beistand.",
                "Unterhält die Konsulate des Reiches; der Souverän ernennt und entlässt die Konsuln, der Kronkanzler verwaltet sie in seinem Namen.",
                "Führt den diplomatischen Verkehr der Konsulate und bereitet Verträge und Abkommen vor.",
                "Gibt Reise- und Sicherheitshinweise heraus und führt die Krisenvorsorgeliste.",
                "Entscheidet über Visa und Einreiseanträge von Ausländern und beglaubigt Urkunden für den Gebrauch im Ausland."]
    inhalt = (_abschnitt('<div class="gk-reisen"><div><h2>Aufgaben</h2><ul>' + "".join(f"<li>{esc(a)}</li>" for a in aufgaben) + "</ul></div>"
                         '<div><h2>Sitz</h2><p>Auswärtiges Amt, Berlin – Sitz des Kaiserlichen Generalkonsulats.</p>'
                         '<p>Das Generalkonsulat gehört zu den <a href="/informationen/die-reichsbehoerden/">Reichsbehörden</a> und arbeitet eng mit dem Kronkanzleramt zusammen.</p></div></div>')
              + _abschnitt('<h2>Leitung und Konsuln</h2>' + (f'<div class="gk-personen">{personen}</div>' if personen else '<p class="gk-hinweis">Zurzeit sind keine Ämter besetzt.</p>'), "section tight paper"))
    kopf = _kopf("Das Generalkonsulat", [("Über uns", None)], "Kaiserliches Generalkonsulat – die auswärtige Vertretung des Imperium Germanicum.", "Reichsbehörde")
    return _antwort(request, k, "start", "Das Generalkonsulat", kopf + inhalt)


async def suche(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    q = (request.query.get("q") or "").strip()[:80]
    treffer = []
    if len(q) >= 2:
        like = f"%{q}%"
        for l in con.execute("SELECT * FROM konsulat_laender WHERE name LIKE ? OR hinweise LIKE ? OR info LIKE ? OR hauptstadt LIKE ? ORDER BY name", (like,) * 4):
            treffer.append(("Länderinformation", l["name"], f'{PFAD}laender/{l["schl"]}/'))
        for m in con.execute("SELECT * FROM konsulat_meldungen WHERE status='veroeffentlicht' AND (titel LIKE ? OR kurz LIKE ? OR text LIKE ?) ORDER BY veroeffentlicht DESC LIMIT 50", (like,) * 3):
            treffer.append((MELDUNGSARTEN.get(m["art"], "Meldung"), m["titel"], f'{PFAD}meldungen/{m["id"]}/'))
        for v in con.execute("SELECT * FROM konsulat_vertraege WHERE oeffentlich=1 AND (titel LIKE ? OR text LIKE ?)", (like,) * 2):
            treffer.append(("Vertrag", v["titel"], f'{PFAD}vertraege/#v{v["id"]}'))
        for schl, (t, b) in ANTRAGSARTEN.items():
            if q.lower() in (t + b).lower():
                treffer.append(("Service", t, f"{PFAD}service/antrag/?art={schl}"))
    if not q:
        inhalt = '<p class="gk-hinweis">Geben Sie einen Suchbegriff ein.</p>'
    elif treffer:
        inhalt = f'<p>{len(treffer)} Treffer für „{esc(q)}“</p><ul class="gk-liste">' + "".join(
            f'<li><a href="{esc(u)}">{esc(t)}</a><span class="gk-art">{esc(a)}</span></li>' for a, t, u in treffer) + "</ul>"
    else:
        inhalt = f'<p class="gk-hinweis">Keine Suchergebnisse für „{esc(q)}“ gefunden.</p>'
    return _antwort(request, k, "", "Suche", _kopf("Suche", [("Suche", None)]) + _abschnitt(inhalt), q)


# ---------------------------------------------------------------- Service (angemeldet)

async def service(request):
    k = await anmeldung.konto(request)
    kacheln = "".join(f'<a class="gk-tkarte" href="{PFAD}service/antrag/?art={s}"><span class="gk-art">Antrag</span><h3>{esc(t)}</h3><p>{esc(b)}</p>'
                      '<span class="link-arrow">Antrag stellen</span></a>' for s, (t, b) in ANTRAGSARTEN.items())
    eigene = ""
    if k:
        n = request.app["db"].execute("SELECT COUNT(*) FROM konsulat_antraege WHERE konto_id=?", (k["id"],)).fetchone()[0]
        eigene = (f'<div class="gk-kacheln"><div class="gk-kachel"><h3>Meine Anträge</h3><p>{n} Antrag/Anträge gestellt.</p>'
                  f'<a class="link-arrow" href="{PFAD}service/meine-antraege/">Zu meinen Anträgen</a></div>'
                  f'<div class="gk-kachel"><h3>Krisenvorsorgeliste</h3><p>Reisen ins Ausland eintragen, damit wir Sie in einer Krise erreichen.</p>'
                  f'<a class="link-arrow" href="{PFAD}krisenvorsorge/">Zur Krisenvorsorgeliste</a></div></div>')
    else:
        eigene = f'<p class="gk-hinweis" style="margin-top:26px">Für Anträge und die Krisenvorsorgeliste <a href="/anmelden/?weiter={PFAD}service/">melden Sie sich mit Discord an</a>.</p>'
    kopf = _kopf("Konsularischer Service", [("Service", None)], "Anträge an das Generalkonsulat – online gestellt, mit Aktenzeichen und Bescheid per Discord-Nachricht.", "Service")
    return _antwort(request, k, "service", "Service", kopf + _abschnitt(f'<div class="gk-teaser">{kacheln}</div>{eigene}'))


async def antrag_formular(request):
    k = await _konto_oder_login(request)
    con = request.app["db"]
    art = request.query.get("art", "visum")
    if art not in ANTRAGSARTEN:
        art = "visum"
    t, b = ANTRAGSARTEN[art]
    land = request.query.get("land", "")
    laender = [("", "– kein bestimmtes Land –")] + [(l["id"], l["name"]) for l in _laender(con)]
    artwahl = _opt([(s, x[0]) for s, x in ANTRAGSARTEN.items()], art)
    hilfe = {"visum": "Wer sind Sie, woher kommen Sie, wohin im Reich wollen Sie, wie lange und zu welchem Zweck?",
             "hilfe": "Wo befinden Sie sich, was ist geschehen und welche Hilfe benötigen Sie?",
             "beglaubigung": "Welche Urkunde oder Erklärung soll beglaubigt werden und für welches Land?",
             "anfrage": "Wen vertreten Sie, und worum geht es?"}[art]
    form = (f'<form class="gk-form" method="post" action="{PFAD}service/antrag/">{_csrf(request)}'
            f'<label>Art des Antrags<select name="art" onchange="location.href=\'?art=\'+this.value">{artwahl}</select></label>'
            f'<p class="gk-hinweis" style="margin:0">{esc(b)}</p>'
            f'<label>Betreff<input name="betreff" maxlength="140" required></label>'
            f'<label>Land / Gemeinschaft<select name="land">{_opt(laender, land)}</select></label>'
            f'<label>Ihr Anliegen<textarea name="text" maxlength="5000" required placeholder="{esc(hilfe)}"></textarea></label>'
            f'<p class="gk-datum" style="margin:0">Sie stellen den Antrag als <strong>{esc(k["name"])}</strong>. Den Bescheid erhalten Sie per Discord-Nachricht und unter „Meine Anträge“.</p>'
            '<div class="gk-knoepfe"><button class="btn btn-navy" type="submit">Antrag einreichen</button></div></form>')
    kopf = _kopf(t, [("Service", PFAD + "service/"), (t, None)], "", "Antrag")
    return _antwort(request, k, "service", t, kopf + _abschnitt(form))


async def antrag_senden(request):
    k, form = await _post(request)
    con = request.app["db"]
    art = form.get("art", "")
    betreff = (form.get("betreff") or "").strip()[:140]
    text = (form.get("text") or "").strip()[:5000]
    if art not in ANTRAGSARTEN or not betreff or not text:
        _weiter(f"{PFAD}service/antrag/?art={art}", f="Bitte Betreff und Anliegen ausfüllen.")
    if con.execute("SELECT COUNT(*) FROM konsulat_antraege WHERE konto_id=? AND erstellt>?", (k["id"], int(time.time()) - 3600)).fetchone()[0] >= 5:
        _weiter(f"{PFAD}service/meine-antraege/", f="Zu viele Anträge in kurzer Zeit – bitte später erneut versuchen.")
    land = form.get("land", "")
    land_id = int(land) if land.isdigit() and _land(con, int(land)) else None
    jahr = datetime.now().year
    n = con.execute("SELECT COUNT(*) FROM konsulat_antraege WHERE az LIKE ?", (f"GK-{jahr}-%",)).fetchone()[0] + 1
    az = f"GK-{jahr}-{n:04d}"
    jetzt = int(time.time())
    cur = con.execute("INSERT INTO konsulat_antraege (az, art, konto_id, name, land_id, betreff, text, erstellt, aktualisiert) VALUES (?,?,?,?,?,?,?,?,?)",
                      (az, art, k["id"], k["name"], land_id, betreff, text, jetzt, jetzt))
    con.execute("INSERT INTO konsulat_antrag_eintraege (antrag_id, zeit, art, text, autor_id, autor_name) VALUES (?,?,?,?,?,?)",
                (cur.lastrowid, jetzt, "Eingang", "Antrag eingereicht.", k["id"], k["name"]))
    con.commit()
    dc = request.app["discord"]
    try:
        for m in await dc.mitglieder():
            if {ROLLE_GENERALKONSUL, ROLLE_KONSUL} & set(m["rollen"]):
                await dc.dm(m["id"], f"📨 Neuer Antrag beim Generalkonsulat: **{az}** – {ANTRAGSARTEN[art][0]}: {betreff}\n"
                                     f"{config.SITE_URL}{PFAD}intern/antraege/{cur.lastrowid}/")
    except Exception:
        pass
    _weiter(f"{PFAD}service/meine-antraege/{cur.lastrowid}/", f"Antrag {az} eingereicht.")


async def meine_antraege(request):
    k = await _konto_oder_login(request)
    rs = request.app["db"].execute("SELECT * FROM konsulat_antraege WHERE konto_id=? ORDER BY erstellt DESC", (k["id"],)).fetchall()
    if rs:
        inhalt = ('<table class="gk-tab"><thead><tr><th>Az.</th><th>Art</th><th>Betreff</th><th>Stand</th><th>Datum</th></tr></thead><tbody>' + "".join(
            f'<tr><td><a href="{PFAD}service/meine-antraege/{r["id"]}/">{esc(r["az"])}</a></td><td>{esc(ANTRAGSARTEN[r["art"]][0])}</td>'
            f'<td>{esc(r["betreff"])}</td><td>{esc(ANTRAGSSTATUS[r["status"]])}</td><td>{_datum(r["erstellt"])}</td></tr>' for r in rs) + "</tbody></table>")
    else:
        inhalt = '<p class="gk-hinweis">Sie haben noch keine Anträge gestellt.</p>'
    inhalt += f'<p><a class="btn btn-navy" href="{PFAD}service/">Neuen Antrag stellen</a></p>'
    kopf = _kopf("Meine Anträge", [("Service", PFAD + "service/"), ("Meine Anträge", None)], "", "Service")
    return _antwort(request, k, "service", "Meine Anträge", kopf + _abschnitt(inhalt))


def _verlauf(con, antrag_id, intern):
    es = con.execute("SELECT * FROM konsulat_antrag_eintraege WHERE antrag_id=?" + ("" if intern else " AND intern=0") + " ORDER BY zeit", (antrag_id,)).fetchall()
    return '<ul class="gk-verlauf">' + "".join(
        f'<li class="{"intern" if e["intern"] else ""}"><small>{_datum(e["zeit"], True)} · {esc(e["art"])}{" (intern)" if e["intern"] else ""} · {esc(e["autor_name"])}</small>'
        f'<p>{esc(e["text"])}</p></li>' for e in es) + "</ul>"


def _antrag_daten(con, r):
    land = _land(con, r["land_id"])
    return (f'<dl class="gk-daten"><dt>Aktenzeichen</dt><dd>{esc(r["az"])}</dd><dt>Art</dt><dd>{esc(ANTRAGSARTEN[r["art"]][0])}</dd>'
            f'<dt>Stand</dt><dd><strong>{esc(ANTRAGSSTATUS[r["status"]])}</strong></dd><dt>Antragsteller</dt><dd>{esc(r["name"])}</dd>'
            f'<dt>Land</dt><dd>{esc(land["name"]) if land else "–"}</dd><dt>Eingang</dt><dd>{_datum(r["erstellt"], True)}</dd>'
            f'<dt>Bearbeiter</dt><dd>{esc(r["bearbeiter_name"] or "–")}</dd></dl>'
            f'<h3>{esc(r["betreff"])}</h3><div class="gk-text">{_absatz(r["text"])}</div>')


async def mein_antrag(request):
    k = await _konto_oder_login(request)
    con = request.app["db"]
    r = con.execute("SELECT * FROM konsulat_antraege WHERE id=?", (request.match_info["id"],)).fetchone()
    if not r or r["konto_id"] != k["id"]:
        raise web.HTTPNotFound(text="Antrag nicht gefunden.")
    nachreichen = ""
    if r["status"] in OFFEN:
        nachreichen = (f'<form class="gk-form" method="post" action="{PFAD}service/meine-antraege/{r["id"]}/nachricht">{_csrf(request)}'
                       '<label>Nachricht an das Generalkonsulat<textarea name="text" maxlength="3000" required></textarea></label>'
                       '<div class="gk-knoepfe"><button class="btn btn-line" type="submit">Senden</button></div></form>')
    kopf = _kopf(r["az"], [("Service", PFAD + "service/"), ("Meine Anträge", PFAD + "service/meine-antraege/"), (r["az"], None)], "", "Antrag")
    return _antwort(request, k, "service", r["az"], kopf + _abschnitt(_antrag_daten(con, r) + "<h3>Verlauf</h3>" + _verlauf(con, r["id"], False) + nachreichen))


async def mein_antrag_nachricht(request):
    k, form = await _post(request)
    con = request.app["db"]
    r = con.execute("SELECT * FROM konsulat_antraege WHERE id=?", (request.match_info["id"],)).fetchone()
    text = (form.get("text") or "").strip()[:3000]
    if not r or r["konto_id"] != k["id"] or r["status"] not in OFFEN or not text:
        raise web.HTTPForbidden(text="Nicht möglich.")
    jetzt = int(time.time())
    con.execute("INSERT INTO konsulat_antrag_eintraege (antrag_id, zeit, art, text, autor_id, autor_name) VALUES (?,?,?,?,?,?)",
                (r["id"], jetzt, "Nachricht des Antragstellers", text, k["id"], k["name"]))
    neu = "bearbeitung" if r["status"] == "rueckfrage" else r["status"]
    con.execute("UPDATE konsulat_antraege SET aktualisiert=?, status=? WHERE id=?", (jetzt, neu, r["id"]))
    con.commit()
    if r["bearbeiter_id"]:
        await request.app["discord"].dm(r["bearbeiter_id"], f"📨 Neue Nachricht zu Antrag **{r['az']}**: {config.SITE_URL}{PFAD}intern/antraege/{r['id']}/")
    _weiter(f"{PFAD}service/meine-antraege/{r['id']}/", "Nachricht gesendet.")


async def krisenvorsorge(request):
    k = await _konto_oder_login(request)
    con = request.app["db"]
    laender = {l["id"]: l for l in _laender(con)}
    es = con.execute("SELECT * FROM konsulat_vorsorge WHERE konto_id=? ORDER BY erstellt DESC", (k["id"],)).fetchall()
    eigene = ('<table class="gk-tab"><thead><tr><th>Land</th><th>Zeitraum</th><th>Hinweis</th><th></th></tr></thead><tbody>' + "".join(
        f'<tr><td>{esc(laender[e["land_id"]]["name"]) if e["land_id"] in laender else "–"} {_stufe_html(laender[e["land_id"]]["stufe"]) if e["land_id"] in laender and laender[e["land_id"]]["stufe"] else ""}</td>'
        f'<td>{esc(e["von"] or "?")} – {esc(e["bis"] or "offen")}</td><td>{esc(e["notiz"])}</td>'
        f'<td><form class="gk-inline" method="post" action="{PFAD}krisenvorsorge/{e["id"]}/loeschen">{_csrf(request)}<button>Austragen</button></form></td></tr>'
        for e in es) + "</tbody></table>") if es else '<p class="gk-hinweis">Sie sind derzeit für kein Land eingetragen.</p>'
    if laender:
        form = (f'<h3>Aufenthalt eintragen</h3><form class="gk-form" method="post" action="{PFAD}krisenvorsorge/">{_csrf(request)}'
                f'<label>Land<select name="land" required>{_opt([(l["id"], l["name"]) for l in laender.values()], request.query.get("land", ""))}</select></label>'
                '<div class="gk-zwei"><label>Von (IC-Datum)<input name="von" maxlength="20" placeholder="TT.MM.JJJJ"></label>'
                '<label>Bis (IC-Datum)<input name="bis" maxlength="20" placeholder="TT.MM.JJJJ"></label></div>'
                '<label>Hinweis (Aufenthaltsort, Mitreisende)<input name="notiz" maxlength="200"></label>'
                '<div class="gk-knoepfe"><button class="btn btn-navy" type="submit">Eintragen</button></div></form>')
    else:
        form = ""
    kopf = _kopf("Krisenvorsorgeliste", [("Service", PFAD + "service/"), ("Krisenvorsorgeliste", None)],
                 "Untertanen des Reiches, die sich in der Fremde aufhalten, können sich hier eintragen. Spricht das Generalkonsulat eine Reisewarnung aus, "
                 "werden alle Eingetragenen des betroffenen Landes sofort per Discord-Nachricht benachrichtigt.", "Sicher reisen")
    return _antwort(request, k, "service", "Krisenvorsorgeliste", kopf + _abschnitt("<h3>Meine Eintragungen</h3>" + eigene + form))


async def krisenvorsorge_eintragen(request):
    k, form = await _post(request)
    con = request.app["db"]
    land = form.get("land", "")
    if not land.isdigit() or not _land(con, int(land)):
        _weiter(PFAD + "krisenvorsorge/", f="Bitte ein Land wählen.")
    if con.execute("SELECT COUNT(*) FROM konsulat_vorsorge WHERE konto_id=?", (k["id"],)).fetchone()[0] >= 20:
        _weiter(PFAD + "krisenvorsorge/", f="Höchstens 20 Eintragungen.")
    con.execute("INSERT INTO konsulat_vorsorge (konto_id, name, land_id, von, bis, notiz, erstellt) VALUES (?,?,?,?,?,?,?)",
                (k["id"], k["name"], int(land), (form.get("von") or "")[:20], (form.get("bis") or "")[:20], (form.get("notiz") or "").strip()[:200], int(time.time())))
    con.commit()
    _weiter(PFAD + "krisenvorsorge/", "Eingetragen.")


async def krisenvorsorge_loeschen(request):
    k, _ = await _post(request)
    con = request.app["db"]
    con.execute("DELETE FROM konsulat_vorsorge WHERE id=? AND konto_id=?", (request.match_info["id"], k["id"]))
    con.commit()
    _weiter(PFAD + "krisenvorsorge/", "Ausgetragen.")


# ---------------------------------------------------------------- Intern

INTERN_TABS = [("", "Übersicht"), ("antraege/", "Anträge"), ("meldungen/", "Meldungen"), ("laender/", "Länder"),
               ("vertraege/", "Verträge"), ("krisenvorsorge/", "Krisenvorsorge"), ("protokoll/", "Protokoll")]


async def _intern_konto(request):
    k = await _konto_oder_login(request)
    if not ist_mitarbeiter(k):
        raise web.HTTPForbidden(text="Nur für Angehörige des Generalkonsulats.")
    return k


def _intern(request, k, aktiv, titel, inhalt, pfad=()):
    tabs = '<div class="gk-reiter">' + "".join(f'<a href="{PFAD}intern/{u}"{" aria-current=\"page\"" if u == aktiv else ""}>{t}</a>' for u, t in INTERN_TABS) + "</div>"
    rang = {"leitung": "Leitung", "konsul": "Konsul", "mitarbeiter": "Mitarbeiter"}[stufe(k)]
    pfad = list(pfad) or ([(titel, None)] if aktiv else [])
    kopf = _kopf(titel, [("Intern", PFAD + "intern/")] + pfad, f"Angemeldet als {esc(k['name'])} · {rang}", "Intern")
    return _antwort(request, k, "intern", titel, kopf + _abschnitt(tabs + inhalt))


async def intern_start(request):
    k = await _intern_konto(request)
    con = request.app["db"]
    z = lambda sql, *p: con.execute(sql, p).fetchone()[0]
    offen = z("SELECT COUNT(*) FROM konsulat_antraege WHERE status IN ('eingegangen','bearbeitung','rueckfrage')")
    neu = z("SELECT COUNT(*) FROM konsulat_antraege WHERE status='eingegangen'")
    entw = z("SELECT COUNT(*) FROM konsulat_meldungen WHERE status='entwurf'")
    warn = z("SELECT COUNT(*) FROM konsulat_laender WHERE stufe>=2")
    vors = z("SELECT COUNT(*) FROM konsulat_vorsorge")
    verh = z("SELECT COUNT(*) FROM konsulat_vertraege WHERE status IN ('entwurf','verhandlung')")
    zahlen = (f'<div class="gk-zahlen"><a href="{PFAD}intern/antraege/?s=eingegangen"><b>{neu}</b>Neue Anträge</a>'
              f'<a href="{PFAD}intern/antraege/"><b>{offen}</b>Offene Anträge</a><a href="{PFAD}intern/meldungen/"><b>{entw}</b>Meldungsentwürfe</a>'
              f'<a href="{PFAD}reisewarnungen/"><b>{warn}</b>(Teil-)Reisewarnungen</a><a href="{PFAD}intern/krisenvorsorge/"><b>{vors}</b>Eingetragene Reisende</a>'
              f'<a href="{PFAD}intern/vertraege/"><b>{verh}</b>Verträge in Arbeit</a></div>')
    meine = con.execute("SELECT * FROM konsulat_antraege WHERE bearbeiter_id=? AND status IN ('eingegangen','bearbeitung','rueckfrage') ORDER BY aktualisiert DESC", (k["id"],)).fetchall()
    rechte = {"leitung": "Sie haben alle Rechte der Leitung: Reisewarnungen, Beziehungsstatus, Vertragsabschluss, Zuordnung der Konsuln, Löschen.",
              "konsul": "Als Konsul bearbeiten und entscheiden Sie Anträge, veröffentlichen Meldungen und pflegen Länderinformationen (Hinweise bis Stufe 1).",
              "mitarbeiter": "Als Mitarbeiter sehen Sie alles, schreiben Meldungsentwürfe und Vermerke zu Anträgen. Entscheidungen treffen Konsuln und Leitung."}[stufe(k)]
    teil = zahlen + f'<p class="gk-hinweis">{rechte}</p>'
    if meine:
        teil += "<h3>Meine offenen Anträge</h3>" + _antrag_tabelle(meine)
    log = con.execute("SELECT * FROM konsulat_protokoll ORDER BY zeit DESC LIMIT 8").fetchall()
    if log:
        teil += '<h3>Zuletzt</h3><ul class="gk-liste">' + "".join(f'<li><span>{esc(p["text"])}</span><span class="gk-datum">{esc(p["autor_name"])} · {_datum(p["zeit"], True)}</span></li>' for p in log) + "</ul>"
    return _intern(request, k, "", "Generalkonsulat intern", teil)


def _antrag_tabelle(rs):
    return ('<table class="gk-tab"><thead><tr><th>Az.</th><th>Art</th><th>Betreff</th><th>Antragsteller</th><th>Stand</th><th>Bearbeiter</th><th>Eingang</th></tr></thead><tbody>'
            + "".join(f'<tr><td><a href="{PFAD}intern/antraege/{r["id"]}/">{esc(r["az"])}</a></td><td>{esc(ANTRAGSARTEN[r["art"]][0])}</td><td>{esc(r["betreff"])}</td>'
                      f'<td>{esc(r["name"])}</td><td>{esc(ANTRAGSSTATUS[r["status"]])}</td><td>{esc(r["bearbeiter_name"] or "–")}</td><td>{_datum(r["erstellt"])}</td></tr>' for r in rs)
            + "</tbody></table>")


async def intern_antraege(request):
    k = await _intern_konto(request)
    s = request.query.get("s", "offen")
    sql = "SELECT * FROM konsulat_antraege"
    par = []
    if s == "offen":
        sql += " WHERE status IN ('eingegangen','bearbeitung','rueckfrage')"
    elif s in ANTRAGSSTATUS:
        sql += " WHERE status=?"
        par.append(s)
    rs = request.app["db"].execute(sql + " ORDER BY aktualisiert DESC LIMIT 300", par).fetchall()
    filt = '<div class="gk-reiter">' + "".join(f'<a href="?s={a}"{" aria-current=\"page\"" if a == s else ""}>{t}</a>'
                                               for a, t in [("offen", "Offen"), ("alle", "Alle")] + list(ANTRAGSSTATUS.items())) + "</div>"
    return _intern(request, k, "antraege/", "Anträge", filt + (_antrag_tabelle(rs) if rs else '<p class="gk-hinweis">Keine Anträge.</p>'))


async def intern_antrag(request):
    k = await _intern_konto(request)
    con = request.app["db"]
    r = con.execute("SELECT * FROM konsulat_antraege WHERE id=?", (request.match_info["id"],)).fetchone()
    if not r:
        raise web.HTTPNotFound(text="Antrag nicht gefunden.")
    aktion = f"{PFAD}intern/antraege/{r['id']}/"
    form = (f'<h3>Vermerk / Antwort</h3><form class="gk-form" method="post" action="{aktion}eintrag">{_csrf(request)}'
            '<label>Text<textarea name="text" maxlength="3000" required></textarea></label>')
    if ist_konsul(k):
        form += (f'<div class="gk-zwei"><label>Neuer Stand<select name="status">{_opt([("", "– unverändert –")] + list(ANTRAGSSTATUS.items()), "")}</select></label>'
                 '<label class="gk-check" style="align-self:end"><input type="checkbox" name="intern" value="1"> Nur interner Vermerk (Antragsteller sieht ihn nicht)</label></div>')
    else:
        form += '<input type="hidden" name="intern" value="1"><p class="gk-datum" style="margin:0">Mitarbeiter schreiben interne Vermerke.</p>'
    form += '<div class="gk-knoepfe"><button class="btn btn-navy" type="submit">Speichern</button></div></form>'
    if ist_konsul(k) and r["bearbeiter_id"] != k["id"]:
        form = (f'<form method="post" action="{aktion}uebernehmen" style="margin:0 0 18px">{_csrf(request)}'
                '<button class="btn btn-line btn-small" type="submit">Antrag übernehmen</button></form>') + form
    if ist_leitung(k):
        form += (f'<form method="post" action="{aktion}loeschen" onsubmit="return confirm(\'Antrag endgültig löschen?\')">{_csrf(request)}'
                 '<button class="btn btn-line btn-small" style="color:var(--danger)" type="submit">Antrag löschen</button></form>')
    return _intern(request, k, "antraege/", r["az"], _antrag_daten(con, r) + "<h3>Verlauf</h3>" + _verlauf(con, r["id"], True) + form,
                   [("Anträge", PFAD + "intern/antraege/"), (r["az"], None)])


async def intern_antrag_uebernehmen(request):
    k, _ = await _post(request, ist_konsul)
    con = request.app["db"]
    r = con.execute("SELECT * FROM konsulat_antraege WHERE id=?", (request.match_info["id"],)).fetchone()
    if not r:
        raise web.HTTPNotFound()
    jetzt = int(time.time())
    neu = "bearbeitung" if r["status"] == "eingegangen" else r["status"]
    con.execute("UPDATE konsulat_antraege SET bearbeiter_id=?, bearbeiter_name=?, status=?, aktualisiert=? WHERE id=?", (k["id"], k["name"], neu, jetzt, r["id"]))
    con.execute("INSERT INTO konsulat_antrag_eintraege (antrag_id, zeit, art, text, autor_id, autor_name) VALUES (?,?,?,?,?,?)",
                (r["id"], jetzt, "Bearbeitung", f"{k['name']} bearbeitet den Antrag.", k["id"], k["name"]))
    _protokoll(con, k, f"Antrag {r['az']} übernommen")
    con.commit()
    _weiter(f"{PFAD}intern/antraege/{r['id']}/", "Übernommen.")


async def intern_antrag_eintrag(request):
    k, form = await _post(request, ist_mitarbeiter)
    con = request.app["db"]
    r = con.execute("SELECT * FROM konsulat_antraege WHERE id=?", (request.match_info["id"],)).fetchone()
    text = (form.get("text") or "").strip()[:3000]
    if not r or not text:
        _weiter(f"{PFAD}intern/antraege/{request.match_info['id']}/", f="Bitte einen Text eingeben.")
    intern = 1 if (form.get("intern") or not ist_konsul(k)) else 0
    status = form.get("status", "") if ist_konsul(k) else ""
    jetzt = int(time.time())
    art = "Interner Vermerk" if intern else "Antwort des Generalkonsulats"
    if status in ANTRAGSSTATUS and status != r["status"]:
        art = f"Stand: {ANTRAGSSTATUS[status]}"
        intern = 0 if not form.get("intern") else intern
        con.execute("UPDATE konsulat_antraege SET status=? WHERE id=?", (status, r["id"]))
        if not r["bearbeiter_id"]:
            con.execute("UPDATE konsulat_antraege SET bearbeiter_id=?, bearbeiter_name=? WHERE id=?", (k["id"], k["name"], r["id"]))
        _protokoll(con, k, f"Antrag {r['az']}: {ANTRAGSSTATUS[status]}")
    con.execute("INSERT INTO konsulat_antrag_eintraege (antrag_id, zeit, art, text, intern, autor_id, autor_name) VALUES (?,?,?,?,?,?,?)",
                (r["id"], jetzt, art, text, intern, k["id"], k["name"]))
    con.execute("UPDATE konsulat_antraege SET aktualisiert=? WHERE id=?", (jetzt, r["id"]))
    con.commit()
    if not intern:
        await request.app["discord"].dm(r["konto_id"], f"🏛️ Generalkonsulat – Antrag **{r['az']}** ({r['betreff']}):\n**{art}**\n{text[:1200]}\n"
                                                       f"{config.SITE_URL}{PFAD}service/meine-antraege/{r['id']}/")
    _weiter(f"{PFAD}intern/antraege/{r['id']}/", "Gespeichert" + ("" if intern else " – Antragsteller benachrichtigt") + ".")


async def intern_antrag_loeschen(request):
    k, _ = await _post(request, ist_leitung)
    con = request.app["db"]
    r = con.execute("SELECT * FROM konsulat_antraege WHERE id=?", (request.match_info["id"],)).fetchone()
    if r:
        con.execute("DELETE FROM konsulat_antrag_eintraege WHERE antrag_id=?", (r["id"],))
        con.execute("DELETE FROM konsulat_antraege WHERE id=?", (r["id"],))
        _protokoll(con, k, f"Antrag {r['az']} gelöscht")
        con.commit()
    _weiter(f"{PFAD}intern/antraege/", "Antrag gelöscht.")


# --- Meldungen

async def intern_meldungen(request):
    k = await _intern_konto(request)
    ms = request.app["db"].execute("SELECT * FROM konsulat_meldungen ORDER BY COALESCE(veroeffentlicht, erstellt) DESC LIMIT 300").fetchall()
    tab = ('<table class="gk-tab"><thead><tr><th>Titel</th><th>Art</th><th>Stand</th><th>Verfasser</th><th>Datum</th></tr></thead><tbody>' + "".join(
        f'<tr><td><a href="{PFAD}intern/meldungen/{m["id"]}/">{esc(m["titel"])}</a></td><td>{esc(MELDUNGSARTEN.get(m["art"], ""))}</td>'
        f'<td>{"Veröffentlicht" if m["status"] == "veroeffentlicht" else "Entwurf"}</td><td>{esc(m["autor_name"])}</td>'
        f'<td>{_datum(m["veroeffentlicht"] or m["erstellt"])}</td></tr>' for m in ms) + "</tbody></table>") if ms else '<p class="gk-hinweis">Noch keine Meldungen.</p>'
    return _intern(request, k, "meldungen/", "Meldungen", f'<p><a class="btn btn-navy" href="{PFAD}intern/meldungen/neu/">Neue Meldung</a></p>' + tab)


async def intern_meldung(request):
    k = await _intern_konto(request)
    con = request.app["db"]
    i = request.match_info.get("id")
    m = con.execute("SELECT * FROM konsulat_meldungen WHERE id=?", (i,)).fetchone() if i else None
    if i and not m:
        raise web.HTTPNotFound()
    w = lambda f, d="": (m[f] if m else d)
    laender = [("", "– kein Land –")] + [(l["id"], l["name"]) for l in _laender(con)]
    knoepfe = '<button class="btn btn-line" name="aktion" value="entwurf" type="submit">Als Entwurf speichern</button>'
    if ist_konsul(k):
        knoepfe = '<button class="btn btn-navy" name="aktion" value="veroeffentlichen" type="submit">Veröffentlichen</button>' + knoepfe
    form = (f'<form class="gk-form" method="post" action="{PFAD}intern/meldungen/{i + "/" if i else "neu/"}">{_csrf(request)}'
            f'<label>Titel<input name="titel" maxlength="160" required value="{esc(w("titel"))}"></label>'
            f'<div class="gk-zwei"><label>Art<select name="art">{_opt(MELDUNGSARTEN.items(), w("art", "artikel"))}</select></label>'
            f'<label>Land<select name="land">{_opt(laender, w("land_id", "") or "")}</select></label></div>'
            f'<label>Kurztext (Teaser)<input name="kurz" maxlength="300" value="{esc(w("kurz"))}"></label>'
            f'<label>Text (Absätze mit Leerzeile trennen)<textarea name="text" style="min-height:280px" maxlength="20000">{esc(w("text"))}</textarea></label>'
            f'<div class="gk-knoepfe">{knoepfe}</div></form>')
    if m:
        st = "Veröffentlicht am " + _datum(m["veroeffentlicht"], True) if m["status"] == "veroeffentlicht" else "Entwurf"
        form = f'<p class="gk-datum">{st} · Verfasser: {esc(m["autor_name"])} · <a href="{PFAD}meldungen/{m["id"]}/">Ansehen</a></p>' + form
        if ist_konsul(k) and m["status"] == "veroeffentlicht":
            form += (f'<form method="post" action="{PFAD}intern/meldungen/{m["id"]}/zurueckziehen" style="margin-top:10px">{_csrf(request)}'
                     '<button class="btn btn-line btn-small" type="submit">Zurückziehen (wieder Entwurf)</button></form>')
        if ist_leitung(k) or (m["status"] == "entwurf" and m["autor_id"] == k["id"]):
            form += (f'<form method="post" action="{PFAD}intern/meldungen/{m["id"]}/loeschen" style="margin-top:10px" onsubmit="return confirm(\'Löschen?\')">{_csrf(request)}'
                     '<button class="btn btn-line btn-small" style="color:var(--danger)" type="submit">Löschen</button></form>')
    titel = m["titel"] if m else "Neue Meldung"
    return _intern(request, k, "meldungen/", titel, form, [("Meldungen", PFAD + "intern/meldungen/"), (titel, None)])


async def intern_meldung_speichern(request):
    k, form = await _post(request, ist_mitarbeiter)
    con = request.app["db"]
    i = request.match_info.get("id")
    m = con.execute("SELECT * FROM konsulat_meldungen WHERE id=?", (i,)).fetchone() if i else None
    if i and not m:
        raise web.HTTPNotFound()
    if m and m["status"] == "veroeffentlicht" and not ist_konsul(k):
        raise web.HTTPForbidden(text="Veröffentlichte Meldungen ändern nur Konsuln und Leitung.")
    titel = (form.get("titel") or "").strip()[:160]
    if not titel:
        _weiter(request.path, f="Titel fehlt.")
    art = form.get("art") if form.get("art") in MELDUNGSARTEN else "artikel"
    land = form.get("land", "")
    land_id = int(land) if land.isdigit() else None
    werte = (titel, art, (form.get("kurz") or "").strip()[:300], (form.get("text") or "").strip()[:20000], land_id)
    jetzt = int(time.time())
    if m:
        con.execute("UPDATE konsulat_meldungen SET titel=?, art=?, kurz=?, text=?, land_id=? WHERE id=?", werte + (m["id"],))
        mid = m["id"]
    else:
        mid = con.execute("INSERT INTO konsulat_meldungen (titel, art, kurz, text, land_id, autor_id, autor_name, erstellt) VALUES (?,?,?,?,?,?,?,?)",
                          werte + (k["id"], k["name"], jetzt)).lastrowid
    if form.get("aktion") == "veroeffentlichen" and ist_konsul(k) and not (m and m["status"] == "veroeffentlicht"):
        con.execute("UPDATE konsulat_meldungen SET status='veroeffentlicht', veroeffentlicht=? WHERE id=?", (jetzt, mid))
        _protokoll(con, k, f"Meldung veröffentlicht: {titel}")
    else:
        _protokoll(con, k, f"Meldung gespeichert: {titel}")
    con.commit()
    _weiter(f"{PFAD}intern/meldungen/{mid}/", "Gespeichert.")


async def intern_meldung_zurueck(request):
    k, _ = await _post(request, ist_konsul)
    con = request.app["db"]
    con.execute("UPDATE konsulat_meldungen SET status='entwurf', veroeffentlicht=NULL WHERE id=?", (request.match_info["id"],))
    _protokoll(con, k, f"Meldung {request.match_info['id']} zurückgezogen")
    con.commit()
    _weiter(f"{PFAD}intern/meldungen/{request.match_info['id']}/", "Zurückgezogen.")


async def intern_meldung_loeschen(request):
    k, _ = await _post(request, ist_mitarbeiter)
    con = request.app["db"]
    m = con.execute("SELECT * FROM konsulat_meldungen WHERE id=?", (request.match_info["id"],)).fetchone()
    if m and (ist_leitung(k) or (m["status"] == "entwurf" and m["autor_id"] == k["id"])):
        con.execute("DELETE FROM konsulat_meldungen WHERE id=?", (m["id"],))
        _protokoll(con, k, f"Meldung gelöscht: {m['titel']}")
        con.commit()
    _weiter(f"{PFAD}intern/meldungen/", "Gelöscht.")


# --- Länder

async def intern_laender(request):
    k = await _intern_konto(request)
    con = request.app["db"]
    ls = _laender(con)
    n_vs = dict(con.execute("SELECT land_id, COUNT(*) FROM konsulat_vorsorge GROUP BY land_id").fetchall())
    tab = ('<table class="gk-tab"><thead><tr><th>Land</th><th>Beziehung</th><th>Reisehinweis</th><th>Konsul</th><th>Reisende</th></tr></thead><tbody>' + "".join(
        f'<tr><td><a href="{PFAD}intern/laender/{l["id"]}/">{esc(l["name"])}</a></td><td>{esc(BEZIEHUNGEN.get(l["beziehung"], ""))}</td>'
        f'<td>{_stufe_html(l["stufe"])}</td><td>{esc(l["konsul_name"] or "–")}</td><td>{n_vs.get(l["id"], 0)}</td></tr>' for l in ls)
        + "</tbody></table>") if ls else '<p class="gk-hinweis">Noch keine Länder angelegt.</p>'
    neu = f'<p><a class="btn btn-navy" href="{PFAD}intern/laender/neu/">Land anlegen</a></p>' if ist_konsul(k) else ""
    return _intern(request, k, "laender/", "Länder", neu + tab)


async def intern_land(request):
    k = await _intern_konto(request)
    con = request.app["db"]
    i = request.match_info.get("id")
    l = _land(con, int(i)) if i else None
    if i and not l:
        raise web.HTTPNotFound()
    if not i and not ist_konsul(k):
        raise web.HTTPForbidden(text="Länder legen Konsuln und Leitung an.")
    w = lambda f, d="": (l[f] if l else d)
    lt, kn = ist_leitung(k), ist_konsul(k)
    dis = "" if kn else " disabled"
    stufen = [(n, t) for n, (t, _) in STUFEN.items() if lt or n <= 1 or (l and n == l["stufe"])]
    konsuln = []
    if lt:
        try:
            konsuln = [(m["id"], m["name"]) for m in await request.app["discord"].mitglieder() if ROLLE_KONSUL in m["rollen"]]
        except Exception:
            konsuln = []
        if l and l["konsul_id"] and l["konsul_id"] not in dict(konsuln):
            konsuln.append((l["konsul_id"], l["konsul_name"] + " (ohne Konsul-Rolle)"))
    bez = (f'<label>Beziehungen zum Reich<select name="beziehung">{_opt(BEZIEHUNGEN.items(), w("beziehung", "neutral"))}</select></label>' if lt else
           f'<label>Beziehungen zum Reich<input value="{esc(BEZIEHUNGEN.get(w("beziehung", "neutral"), ""))}" disabled></label>')
    kon = (f'<label>Zuständiger Konsul<select name="konsul">{_opt([("", "– Generalkonsulat unmittelbar –")] + konsuln, w("konsul_id"))}</select></label>' if lt else
           f'<label>Zuständiger Konsul<input value="{esc(w("konsul_name") or "–")}" disabled></label>')
    form = (f'<form class="gk-form" method="post" action="{PFAD}intern/laender/{i + "/" if i else "neu/"}">{_csrf(request)}'
            f'<div class="gk-zwei"><label>Name<input name="name" maxlength="80" required value="{esc(w("name"))}"{dis}></label>'
            f'<label>Art<select name="art"{dis}>{_opt([(a, a) for a in ARTEN_LAND], w("art", "Staat"))}</select></label></div>'
            f'<div class="gk-zwei"><label>Hauptstadt / Sitz<input name="hauptstadt" maxlength="80" value="{esc(w("hauptstadt"))}"{dis}></label>'
            f'<label>Staatsoberhaupt<input name="oberhaupt" maxlength="120" value="{esc(w("oberhaupt"))}"{dis}></label></div>'
            f'<div class="gk-zwei">{bez}<label>Reise- und Sicherheitshinweis<select name="stufe"{dis}>{_opt(stufen, w("stufe", 0))}</select></label></div>'
            f'{kon}'
            f'<label>Sicherheitshinweise<textarea name="hinweise" maxlength="8000"{dis}>{esc(w("hinweise"))}</textarea></label>'
            f'<label>Einreise und Zoll<textarea name="einreise" maxlength="8000"{dis}>{esc(w("einreise"))}</textarea></label>'
            f'<label>Beziehungen zum Reich (Text)<textarea name="info" maxlength="8000"{dis}>{esc(w("info"))}</textarea></label>'
            f'<label>Vertretung des Reiches (Konsulat, Anschrift, Erreichbarkeit)<textarea name="vertretung" maxlength="4000"{dis}>{esc(w("vertretung"))}</textarea></label>'
            + ('<p class="gk-datum" style="margin:0">Bei Stufe „Reisewarnung“ werden alle Eingetragenen der Krisenvorsorgeliste für dieses Land per Discord benachrichtigt.</p>'
               '<div class="gk-knoepfe"><button class="btn btn-navy" type="submit">Speichern</button></div>' if kn else "") + '</form>')
    if l:
        form = f'<p class="gk-datum">Zuletzt geändert {_datum(l["aktualisiert"], True)} · <a href="{PFAD}laender/{esc(l["schl"])}/">Öffentliche Seite</a></p>' + form
        vs = con.execute("SELECT * FROM konsulat_vorsorge WHERE land_id=? ORDER BY erstellt DESC", (l["id"],)).fetchall()
        if vs:
            form += "<h3>Krisenvorsorgeliste für dieses Land</h3>" + _vorsorge_tabelle(vs, {l["id"]: l})
        if lt:
            form += (f'<form method="post" action="{PFAD}intern/laender/{l["id"]}/loeschen" style="margin-top:14px" onsubmit="return confirm(\'Land mit allen Einträgen der Krisenvorsorgeliste löschen?\')">'
                     f'{_csrf(request)}<button class="btn btn-line btn-small" style="color:var(--danger)" type="submit">Land löschen</button></form>')
    titel = l["name"] if l else "Land anlegen"
    return _intern(request, k, "laender/", titel, form, [("Länder", PFAD + "intern/laender/"), (titel, None)])


async def intern_land_speichern(request):
    k, form = await _post(request, ist_konsul)
    con = request.app["db"]
    i = request.match_info.get("id")
    l = _land(con, int(i)) if i else None
    if i and not l:
        raise web.HTTPNotFound()
    lt = ist_leitung(k)
    name = (form.get("name") or "").strip()[:80]
    if not name:
        _weiter(request.path, f="Name fehlt.")
    stufe_neu = int(form.get("stufe", "0")) if str(form.get("stufe", "0")).isdigit() else 0
    stufe_neu = min(max(stufe_neu, 0), 3)
    alt_stufe = l["stufe"] if l else 0
    if not lt and stufe_neu >= 2 and stufe_neu != alt_stufe:
        _weiter(request.path, f="Teilreisewarnungen und Reisewarnungen spricht nur der Generalkonsul aus.")
    if not lt and alt_stufe >= 2 and stufe_neu != alt_stufe:
        _weiter(request.path, f="Eine bestehende (Teil-)Reisewarnung hebt nur der Generalkonsul auf.")
    beziehung = form.get("beziehung") if lt and form.get("beziehung") in BEZIEHUNGEN else (l["beziehung"] if l else "neutral")
    konsul_id, konsul_name = (l["konsul_id"], l["konsul_name"]) if l else ("", "")
    if lt:
        konsul_id = form.get("konsul", "") or ""
        konsul_name = ""
        if konsul_id:
            m = next((m for m in await request.app["discord"].mitglieder() if m["id"] == konsul_id), None)
            konsul_name = m["name"] if m else (l["konsul_name"] if l and l["konsul_id"] == konsul_id else "")
            if not konsul_name:
                konsul_id = ""
    art = form.get("art") if form.get("art") in ARTEN_LAND else "Staat"
    texte = {f: (form.get(f) or "").strip()[:8000] for f in ("hinweise", "einreise", "info", "vertretung")}
    jetzt = int(time.time())
    hz = jetzt if (not l or texte["hinweise"] != l["hinweise"] or stufe_neu != alt_stufe) else l["hinweise_zeit"]
    werte = (name, art, (form.get("hauptstadt") or "").strip()[:80], (form.get("oberhaupt") or "").strip()[:120], beziehung, stufe_neu,
             texte["hinweise"], texte["einreise"], texte["info"], texte["vertretung"][:4000], konsul_id, konsul_name, jetzt, hz)
    if l:
        con.execute("UPDATE konsulat_laender SET name=?, art=?, hauptstadt=?, oberhaupt=?, beziehung=?, stufe=?, hinweise=?, einreise=?, info=?, vertretung=?,"
                    " konsul_id=?, konsul_name=?, aktualisiert=?, hinweise_zeit=? WHERE id=?", werte + (l["id"],))
        lid = l["id"]
    else:
        schl, n = _schl(name), 2
        while con.execute("SELECT 1 FROM konsulat_laender WHERE schl=?", (schl,)).fetchone():
            schl = f"{_schl(name)}-{n}"
            n += 1
        lid = con.execute("INSERT INTO konsulat_laender (name, art, hauptstadt, oberhaupt, beziehung, stufe, hinweise, einreise, info, vertretung, konsul_id,"
                          " konsul_name, aktualisiert, hinweise_zeit, schl) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", werte + (schl,)).lastrowid
    text = f"Land {'angelegt' if not l else 'geändert'}: {name}"
    if stufe_neu != alt_stufe:
        text += f" – Reisehinweis jetzt „{STUFEN[stufe_neu][0]}“"
    if l and beziehung != l["beziehung"]:
        text += f" – Beziehung jetzt „{BEZIEHUNGEN[beziehung]}“"
    _protokoll(con, k, text)
    con.commit()
    zus = ""
    if stufe_neu == 3 and alt_stufe != 3:
        empf = {r["konto_id"] for r in con.execute("SELECT konto_id FROM konsulat_vorsorge WHERE land_id=?", (lid,))}
        schl = con.execute("SELECT schl FROM konsulat_laender WHERE id=?", (lid,)).fetchone()[0]
        for kid in empf:
            await request.app["discord"].dm(kid, f"⚠️ **Reisewarnung für {name}**\nDas Kaiserliche Generalkonsulat warnt vor Reisen nach {name}. "
                                                 f"Sie sind in der Krisenvorsorgeliste für dieses Land eingetragen. Bitte informieren Sie sich:\n"
                                                 f"{config.SITE_URL}{PFAD}laender/{schl}/")
        zus = f" – {len(empf)} Reisende benachrichtigt"
    _weiter(f"{PFAD}intern/laender/{lid}/", "Gespeichert" + zus + ".")


async def intern_land_loeschen(request):
    k, _ = await _post(request, ist_leitung)
    con = request.app["db"]
    l = _land(con, int(request.match_info["id"]))
    if l:
        con.execute("DELETE FROM konsulat_vorsorge WHERE land_id=?", (l["id"],))
        con.execute("UPDATE konsulat_meldungen SET land_id=NULL WHERE land_id=?", (l["id"],))
        con.execute("UPDATE konsulat_vertraege SET land_id=NULL WHERE land_id=?", (l["id"],))
        con.execute("UPDATE konsulat_antraege SET land_id=NULL WHERE land_id=?", (l["id"],))
        con.execute("DELETE FROM konsulat_laender WHERE id=?", (l["id"],))
        _protokoll(con, k, f"Land gelöscht: {l['name']}")
        con.commit()
    _weiter(f"{PFAD}intern/laender/", "Gelöscht.")


# --- Verträge

async def intern_vertraege(request):
    k = await _intern_konto(request)
    con = request.app["db"]
    laender = {l["id"]: l for l in _laender(con)}
    vs = con.execute("SELECT * FROM konsulat_vertraege ORDER BY aktualisiert DESC").fetchall()
    tab = ('<table class="gk-tab"><thead><tr><th>Titel</th><th>Partner</th><th>Art</th><th>Stand</th><th>Öffentlich</th></tr></thead><tbody>' + "".join(
        f'<tr><td><a href="{PFAD}intern/vertraege/{v["id"]}/">{esc(v["titel"])}</a></td><td>{esc(laender[v["land_id"]]["name"]) if v["land_id"] in laender else "–"}</td>'
        f'<td>{esc(v["art"])}</td><td>{esc(VERTRAGSSTATUS[v["status"]])}</td><td>{"Ja" if v["oeffentlich"] else "Nein"}</td></tr>' for v in vs)
        + "</tbody></table>") if vs else '<p class="gk-hinweis">Noch keine Verträge.</p>'
    neu = f'<p><a class="btn btn-navy" href="{PFAD}intern/vertraege/neu/">Neuer Vertragsentwurf</a></p>' if ist_konsul(k) else ""
    return _intern(request, k, "vertraege/", "Verträge", neu + tab)


async def intern_vertrag(request):
    k = await _intern_konto(request)
    con = request.app["db"]
    i = request.match_info.get("id")
    v = con.execute("SELECT * FROM konsulat_vertraege WHERE id=?", (i,)).fetchone() if i else None
    if i and not v:
        raise web.HTTPNotFound()
    if not i and not ist_konsul(k):
        raise web.HTTPForbidden(text="Vertragsentwürfe legen Konsuln und Leitung an.")
    w = lambda f, d="": (v[f] if v else d)
    kn, lt = ist_konsul(k), ist_leitung(k)
    dis = "" if kn and (lt or w("status", "entwurf") not in VERTRAG_LEITUNG) else " disabled"
    stati = [(s, t) for s, t in VERTRAGSSTATUS.items() if lt or s not in VERTRAG_LEITUNG or s == w("status", "entwurf")]
    laender = [("", "– kein Partner –")] + [(l["id"], l["name"]) for l in _laender(con)]
    form = (f'<form class="gk-form" method="post" action="{PFAD}intern/vertraege/{i + "/" if i else "neu/"}">{_csrf(request)}'
            f'<label>Titel<input name="titel" maxlength="160" required value="{esc(w("titel"))}"{dis}></label>'
            f'<div class="gk-zwei"><label>Vertragspartner<select name="land"{dis}>{_opt(laender, w("land_id", "") or "")}</select></label>'
            f'<label>Art<select name="art"{dis}>{_opt([(a, a) for a in VERTRAGSARTEN], w("art", VERTRAGSARTEN[-1]))}</select></label></div>'
            f'<div class="gk-zwei"><label>Stand<select name="status"{dis}>{_opt(stati, w("status", "entwurf"))}</select></label>'
            f'<label>Datum (IC, Unterzeichnung)<input name="datum" maxlength="40" value="{esc(w("datum"))}"{dis}></label></div>'
            f'<label>Vertragstext<textarea name="text" style="min-height:300px" maxlength="30000"{dis}>{esc(w("text"))}</textarea></label>'
            f'<label class="gk-check"><input type="checkbox" name="oeffentlich" value="1"{" checked" if w("oeffentlich", 0) else ""}{"" if lt else " disabled"}> '
            'In der öffentlichen Vertragssammlung zeigen (Leitung)</label>'
            + ('<div class="gk-knoepfe"><button class="btn btn-navy" type="submit">Speichern</button></div>' if not dis else
               '<p class="gk-datum" style="margin:0">Unterzeichnete Verträge ändert nur die Leitung.</p>' if kn else "") + "</form>")
    if v and lt:
        form += (f'<form method="post" action="{PFAD}intern/vertraege/{v["id"]}/loeschen" style="margin-top:12px" onsubmit="return confirm(\'Vertrag löschen?\')">{_csrf(request)}'
                 '<button class="btn btn-line btn-small" style="color:var(--danger)" type="submit">Löschen</button></form>')
    titel = v["titel"] if v else "Neuer Vertragsentwurf"
    return _intern(request, k, "vertraege/", titel, form, [("Verträge", PFAD + "intern/vertraege/"), (titel, None)])


async def intern_vertrag_speichern(request):
    k, form = await _post(request, ist_konsul)
    con = request.app["db"]
    i = request.match_info.get("id")
    v = con.execute("SELECT * FROM konsulat_vertraege WHERE id=?", (i,)).fetchone() if i else None
    if i and not v:
        raise web.HTTPNotFound()
    lt = ist_leitung(k)
    if v and v["status"] in VERTRAG_LEITUNG and not lt:
        raise web.HTTPForbidden(text="Unterzeichnete Verträge ändert nur die Leitung.")
    status = form.get("status") if form.get("status") in VERTRAGSSTATUS else "entwurf"
    if status in VERTRAG_LEITUNG and not lt:
        status = v["status"] if v else "entwurf"
    titel = (form.get("titel") or "").strip()[:160]
    if not titel:
        _weiter(request.path, f="Titel fehlt.")
    land = form.get("land", "")
    oeff = (1 if form.get("oeffentlich") else 0) if lt else (v["oeffentlich"] if v else 0)
    jetzt = int(time.time())
    werte = (titel, int(land) if land.isdigit() else None, form.get("art") if form.get("art") in VERTRAGSARTEN else VERTRAGSARTEN[-1],
             status, (form.get("text") or "").strip()[:30000], oeff, (form.get("datum") or "").strip()[:40], jetzt)
    if v:
        con.execute("UPDATE konsulat_vertraege SET titel=?, land_id=?, art=?, status=?, text=?, oeffentlich=?, datum=?, aktualisiert=? WHERE id=?", werte + (v["id"],))
        vid = v["id"]
    else:
        vid = con.execute("INSERT INTO konsulat_vertraege (titel, land_id, art, status, text, oeffentlich, datum, aktualisiert, erstellt) VALUES (?,?,?,?,?,?,?,?,?)",
                          werte + (jetzt,)).lastrowid
    _protokoll(con, k, f"Vertrag {'angelegt' if not v else 'geändert'}: {titel} ({VERTRAGSSTATUS[status]})")
    con.commit()
    _weiter(f"{PFAD}intern/vertraege/{vid}/", "Gespeichert.")


async def intern_vertrag_loeschen(request):
    k, _ = await _post(request, ist_leitung)
    con = request.app["db"]
    v = con.execute("SELECT * FROM konsulat_vertraege WHERE id=?", (request.match_info["id"],)).fetchone()
    if v:
        con.execute("DELETE FROM konsulat_vertraege WHERE id=?", (v["id"],))
        _protokoll(con, k, f"Vertrag gelöscht: {v['titel']}")
        con.commit()
    _weiter(f"{PFAD}intern/vertraege/", "Gelöscht.")


# --- Krisenvorsorge, Protokoll

def _vorsorge_tabelle(vs, laender):
    return ('<table class="gk-tab"><thead><tr><th>Person</th><th>Land</th><th>Zeitraum</th><th>Hinweis</th><th>Eingetragen</th></tr></thead><tbody>' + "".join(
        f'<tr><td>{esc(e["name"])}</td><td>{esc(laender[e["land_id"]]["name"]) if e["land_id"] in laender else "–"}</td>'
        f'<td>{esc(e["von"] or "?")} – {esc(e["bis"] or "offen")}</td><td>{esc(e["notiz"])}</td><td>{_datum(e["erstellt"])}</td></tr>' for e in vs) + "</tbody></table>")


async def intern_vorsorge(request):
    k = await _intern_konto(request)
    con = request.app["db"]
    laender = {l["id"]: l for l in _laender(con)}
    vs = con.execute("SELECT * FROM konsulat_vorsorge ORDER BY land_id, erstellt DESC").fetchall()
    return _intern(request, k, "krisenvorsorge/", "Krisenvorsorgeliste",
                   '<p class="gk-hinweis">Wer hier steht, wird bei einer Reisewarnung für sein Land automatisch per Discord benachrichtigt.</p>'
                   + (_vorsorge_tabelle(vs, laender) if vs else '<p class="gk-hinweis">Niemand eingetragen.</p>'))


async def intern_protokoll(request):
    k = await _intern_konto(request)
    ps = request.app["db"].execute("SELECT * FROM konsulat_protokoll ORDER BY zeit DESC LIMIT 300").fetchall()
    return _intern(request, k, "protokoll/", "Protokoll", ('<table class="gk-tab"><thead><tr><th>Zeit</th><th>Wer</th><th>Was</th></tr></thead><tbody>' + "".join(
        f'<tr><td>{_datum(p["zeit"], True)}</td><td>{esc(p["autor_name"])}</td><td>{esc(p["text"])}</td></tr>' for p in ps) + "</tbody></table>")
                   if ps else '<p class="gk-hinweis">Noch keine Einträge.</p>')


def registrieren(app):
    einrichten(app["db"])
    r = app.router
    r.add_get("/regierung/", weiterleiten)
    r.add_get("/regierung/generalkonsulat", weiterleiten)
    r.add_get("/regierung/generalkonsulat.de", weiterleiten)
    r.add_get("/regierung/generalkonsulat.de/", weiterleiten)
    r.add_get(PFAD, start)
    r.add_get(PFAD + "logo{art:(-kurz)?}.png", logo)
    r.add_get(PFAD + "laender/", laender_liste)
    r.add_get(PFAD + "laender/{schl}/", land_seite)
    r.add_get(PFAD + "reisewarnungen/", reisewarnungen)
    r.add_get(PFAD + "meldungen/", meldungen_liste)
    r.add_get(PFAD + "meldungen/{id:\\d+}/", meldung_seite)
    r.add_get(PFAD + "vertraege/", vertraege)
    r.add_get(PFAD + "das-generalkonsulat/", ueber)
    r.add_get(PFAD + "suche/", suche)
    r.add_get(PFAD + "service/", service)
    r.add_get(PFAD + "service/antrag/", antrag_formular)
    r.add_post(PFAD + "service/antrag/", antrag_senden)
    r.add_get(PFAD + "service/meine-antraege/", meine_antraege)
    r.add_get(PFAD + "service/meine-antraege/{id:\\d+}/", mein_antrag)
    r.add_post(PFAD + "service/meine-antraege/{id:\\d+}/nachricht", mein_antrag_nachricht)
    r.add_get(PFAD + "krisenvorsorge/", krisenvorsorge)
    r.add_post(PFAD + "krisenvorsorge/", krisenvorsorge_eintragen)
    r.add_post(PFAD + "krisenvorsorge/{id:\\d+}/loeschen", krisenvorsorge_loeschen)
    r.add_get(PFAD + "intern/", intern_start)
    r.add_get(PFAD + "intern/antraege/", intern_antraege)
    r.add_get(PFAD + "intern/antraege/{id:\\d+}/", intern_antrag)
    r.add_post(PFAD + "intern/antraege/{id:\\d+}/uebernehmen", intern_antrag_uebernehmen)
    r.add_post(PFAD + "intern/antraege/{id:\\d+}/eintrag", intern_antrag_eintrag)
    r.add_post(PFAD + "intern/antraege/{id:\\d+}/loeschen", intern_antrag_loeschen)
    r.add_get(PFAD + "intern/meldungen/", intern_meldungen)
    r.add_get(PFAD + "intern/meldungen/neu/", intern_meldung)
    r.add_post(PFAD + "intern/meldungen/neu/", intern_meldung_speichern)
    r.add_get(PFAD + "intern/meldungen/{id:\\d+}/", intern_meldung)
    r.add_post(PFAD + "intern/meldungen/{id:\\d+}/", intern_meldung_speichern)
    r.add_post(PFAD + "intern/meldungen/{id:\\d+}/zurueckziehen", intern_meldung_zurueck)
    r.add_post(PFAD + "intern/meldungen/{id:\\d+}/loeschen", intern_meldung_loeschen)
    r.add_get(PFAD + "intern/laender/", intern_laender)
    r.add_get(PFAD + "intern/laender/neu/", intern_land)
    r.add_post(PFAD + "intern/laender/neu/", intern_land_speichern)
    r.add_get(PFAD + "intern/laender/{id:\\d+}/", intern_land)
    r.add_post(PFAD + "intern/laender/{id:\\d+}/", intern_land_speichern)
    r.add_post(PFAD + "intern/laender/{id:\\d+}/loeschen", intern_land_loeschen)
    r.add_get(PFAD + "intern/vertraege/", intern_vertraege)
    r.add_get(PFAD + "intern/vertraege/neu/", intern_vertrag)
    r.add_post(PFAD + "intern/vertraege/neu/", intern_vertrag_speichern)
    r.add_get(PFAD + "intern/vertraege/{id:\\d+}/", intern_vertrag)
    r.add_post(PFAD + "intern/vertraege/{id:\\d+}/", intern_vertrag_speichern)
    r.add_post(PFAD + "intern/vertraege/{id:\\d+}/loeschen", intern_vertrag_loeschen)
    r.add_get(PFAD + "intern/krisenvorsorge/", intern_vorsorge)
    r.add_get(PFAD + "intern/protokoll/", intern_protokoll)
