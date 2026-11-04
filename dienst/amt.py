"""Amtsseite der Reichsbehörden: Akten der Bürger und Einbürgerungsakten (Einreiseverfahren).

    GET  /informationen/die-reichsbehoerden/intern/                 Übersicht (Zur Bearbeitung, Kennzahlen, letzte Vorgänge)
    GET  …/intern/buerger/?q=&status=&seite=                         Aktenverzeichnis der Bürger (Suche)
    GET  …/intern/buerger/<id>/                                      Bürgerakte (Stammdaten, Verfahren, Vorgänge, Vermerke)
    GET  …/intern/verfahren/?status=                                 Einbürgerungsakten
    GET  …/intern/verfahren/<id>/                                    Einbürgerungsakte (Phase I und II, Vorgänge)
    POST …/intern/buerger/<id>/bearbeiten | vermerk                  Stammdaten ändern / Vermerk anfügen
    POST …/intern/verfahren/<id>/vermerk | schliessen                Vermerk anfügen / Verfahren ohne Einbürgerung schließen
    POST /intern-api/amt/einreise | einbuergerung | ticket-geschlossen   nur lokal (Bot, Header X-Bot-Token)

Jeder Staatsbürger hat eine Bürgerakte (Aktenzeichen BA-nnnnn). Sie wird beim Start und alle 15 Minuten aus den Discord-Rollen angelegt
(Rolle Staatsbürger); Bewerber erhalten sie mit dem Einreiseantrag. Jedes Einreiseverfahren ist eine Einbürgerungsakte (EB-jjjj-nnnn),
die der Bot (Modul ticket.py / zollamt.py) befüllt. Zugang: Kaiserliche Zollverwaltung, Kanzler, Server-Admins.
"""
import asyncio
import html
import json
import logging
import os
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp import web

import anmeldung
import config
from amt_icons import ICONS

log = logging.getLogger("amt")
esc = html.escape
BERLIN = ZoneInfo("Europe/Berlin")

BASIS = "/informationen/die-reichsbehoerden/intern/"
ROLLE_ZOLL = "1557187375006875758"
ROLLE_KANZLER = "1561856444913946664"
ROLLE_POLIZEI = "1557800373861753002"
ROLLE_KATASTROPHENSCHUTZ = "1557187293100515328"
# Behördenlogo je Rolle (Reihenfolge = Vorrang bei mehreren Rollen); Bilder erzeugt werkzeuge/amt_logos.py, Texte in amt_logos_liste.py
LOGOS = [(ROLLE_KANZLER, "kanzler", "Der Kanzler"), (ROLLE_POLIZEI, "polizei", "Kaiserliche Polizeibehörde"),
         (ROLLE_ZOLL, "zoll", "Kaiserliche Zollverwaltung"), (ROLLE_KATASTROPHENSCHUTZ, "katastrophenschutz", "Kaiserlicher Katastrophenschutz")]
LOGO_ORDNER = os.path.join(config.HIER, "amt_logos")
ROLLE_STAATSBUERGER = "1522929940885143683"
# Zugang: Rollen oder Nutzer-IDs (Kaiser, Rolle 1526348059984789504, Hand des Kaisers 1522693216053235903), dazu Server-Admins
ZUGANG_IDS = {"463089934765391872", "1526348059984789504", "1522693216053235903"}
ROLLEN_ZUGANG = {ROLLE_ZOLL, ROLLE_KANZLER} | ZUGANG_IDS
SEITE_GROESSE = 50

STATUS_AKTE = {"staatsbuerger": "Staatsbürger", "einwanderer": "Einwanderer", "nicht_mehr": "Nicht mehr Staatsbürger"}
ERGEBNIS = {"offen": "Offen", "eingebuergert": "Eingebürgert", "abgelehnt": "Abgelehnt", "geschlossen": "Ohne Einbürgerung geschlossen"}
PHASE = {1: "Phase I (OOC) – Prüfung", 2: "Phase II eingeleitet – wartet auf Antragsteller", 3: "Phase II ausgefüllt – Entscheidung offen"}
SCHICHTEN = ["Bürgerstand", "Adelsstand", "Klerus", "Bauernstand", "Sonstiges"]
BERUFE = ["Militärischer Natur", "Beamter", "Sonstiges"]
PHASE1_FELDER = [("name", "Name (OOC)"), ("geburtsdatum", "Geburtsdatum"), ("aufmerksam", "Aufmerksam geworden durch"),
                 ("wunsch", "Vorstellung / Wunschposition"), ("rolle", "Beschreibung der Rolle")]
PHASE2_FELDER = [("name", "Name (IC)"), ("geburtsdatum", "Geburtsdatum (IC)"), ("fraktion", "Fraktion"),
                 ("schicht", "Gesellschaftsschicht"), ("beruf", "Berufliche Zugehörigkeit"), ("vorgeschichte", "Personelle Vorgeschichte")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS amt_akten (
    id INTEGER PRIMARY KEY AUTOINCREMENT, konto_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, ic_name TEXT NOT NULL DEFAULT '',
    ic_geburt TEXT NOT NULL DEFAULT '', fraktion TEXT NOT NULL DEFAULT '', schicht TEXT NOT NULL DEFAULT '', beruf TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'einwanderer', angelegt INTEGER NOT NULL, aktualisiert INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS amt_verfahren (
    id INTEGER PRIMARY KEY AUTOINCREMENT, konto_id TEXT NOT NULL, name TEXT NOT NULL, thread_id TEXT UNIQUE, phase INTEGER NOT NULL DEFAULT 1,
    ergebnis TEXT NOT NULL DEFAULT 'offen', phase1 TEXT NOT NULL DEFAULT '{}', phase2 TEXT NOT NULL DEFAULT '{}',
    erstellt INTEGER NOT NULL, aktualisiert INTEGER NOT NULL, abgeschlossen INTEGER);
CREATE TABLE IF NOT EXISTS amt_eintraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ziel TEXT NOT NULL, ziel_id INTEGER NOT NULL, zeit INTEGER NOT NULL, art TEXT NOT NULL,
    text TEXT NOT NULL, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS amt_loeschungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, aktenzeichen TEXT NOT NULL, konto_id TEXT NOT NULL, name TEXT NOT NULL, ic_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '', verfahren_geloescht INTEGER NOT NULL DEFAULT 0, grund TEXT NOT NULL, zeit INTEGER NOT NULL,
    autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS amt_eintraege_ziel ON amt_eintraege (ziel, ziel_id);
CREATE INDEX IF NOT EXISTS amt_verfahren_konto ON amt_verfahren (konto_id);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    spalten = {r[1] for r in con.execute("PRAGMA table_info(amt_akten)")}
    if "verschluss" not in spalten:
        con.execute("ALTER TABLE amt_akten ADD COLUMN verschluss INTEGER NOT NULL DEFAULT 0")
    con.commit()


def az_akte(i):
    return f"BA-{i:05d}"


def az_verfahren(i, zeit):
    return f"EB-{datetime.fromtimestamp(zeit, BERLIN).year}-{i:04d}"


def logo_von(k):
    """(Logo-Schlüssel, Behördenname) der Behörde des Kontos; ohne Behördenrolle das allgemeine Logo der Reichsbehörden."""
    rollen = set(k["rollen"])
    for rolle, schl, name in LOGOS:
        if rolle in rollen:
            return schl, name
    return "reichsbehoerden", "Die Reichsbehörden"


def ist_beamter(k):
    return bool(k) and (k["admin"] or k["id"] in ZUGANG_IDS or bool(ROLLEN_ZUGANG & set(k["rollen"])))


# Nur Lesezugriff (kein Schreibrecht): Kaiserliches Reichssicherheitsamt
LESE_IDS = {"1522913765035606086"}


def ist_leser(k):
    """Darf die Amtsseite ansehen (Beamte mit Schreibrecht und die Leseberechtigten)."""
    return ist_beamter(k) or (bool(k) and bool(LESE_IDS & ({k["id"]} | set(k["rollen"]))))


def darf_verschluss(k):
    """Kaiser und Kanzler: Akten unter Verschluss setzen und solche Akten einsehen."""
    return bool(k) and (k["id"] == config.KAISER_ID or ROLLE_KANZLER in k["rollen"])


def sperren(con, k):
    """(Akten-IDs, Konto-IDs) der Akten unter Verschluss, die dieses Konto nicht sehen darf."""
    if darf_verschluss(k):
        return set(), set()
    rows = con.execute("SELECT id, konto_id FROM amt_akten WHERE verschluss=1").fetchall()
    return {r["id"] for r in rows}, {r["konto_id"] for r in rows}


def konto_gesperrt(con, k, konto_id):
    z = con.execute("SELECT verschluss FROM amt_akten WHERE konto_id=?", (konto_id,)).fetchone()
    return bool(z and z["verschluss"]) and not darf_verschluss(k)


def _zeit(ts, uhr=True):
    if not ts:
        return "–"
    return datetime.fromtimestamp(ts, BERLIN).strftime("%d.%m.%Y %H:%M" if uhr else "%d.%m.%Y")


# ---------------------------------------------------------------- Darstellung

CSS = """
:root{--ink:#111;--grau:#5a5a5a;--linie:#b9b9b9;--hell:#f1f1f1;--kopf:#1f2f45;--akzent:#1f4e8c;--warn:#8a5a00;--ok:#1d6b34;--rot:#9b1c1c}
*{box-sizing:border-box}
html{font-size:16px}
body{margin:0;font:15px/1.5 Arial,Helvetica,sans-serif;color:var(--ink);background:#fff}
a{color:var(--akzent)}
.icon{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;vertical-align:-3px;flex:none}
.kopf{background:#fff;color:var(--ink);display:flex;align-items:center;gap:12px;padding:8px 16px;border-bottom:1px solid var(--linie)}
.kopf .logo{display:block;line-height:0}
.kopf .logo img{height:64px;width:auto;display:block}
.kopf .raum{flex:1}
.kopf form{margin:0;display:flex}
.kopf input[type=search]{border:1px solid #777;background:#fff;color:#111;padding:6px 8px;font:inherit;width:220px;border-radius:0}
.kopf button{border:1px solid var(--kopf);background:var(--kopf);color:#fff;padding:6px 10px;font:inherit;cursor:pointer;border-radius:0}
.kopf .logo img.kurz{display:none}
.rahmen{display:flex;min-height:calc(100vh - 81px)}
nav{width:220px;flex:none;border-right:1px solid var(--linie);background:var(--hell);padding:12px 0}
nav a{display:flex;align-items:center;gap:10px;padding:9px 16px;color:var(--ink);text-decoration:none;border-left:4px solid transparent}
nav a:hover{background:#e4e4e4}
nav a.aktiv{border-left-color:var(--akzent);background:#fff;font-weight:bold}
nav hr{border:0;border-top:1px solid var(--linie);margin:10px 0}
nav .konto{padding:6px 16px;color:var(--grau);font-size:13px}
nav form{margin:0}
nav button.link{all:unset;display:flex;align-items:center;gap:10px;padding:9px 16px;cursor:pointer;width:100%;box-sizing:border-box}
nav button.link:hover{background:#e4e4e4}
main{flex:1;min-width:0;padding:20px 24px 48px;max-width:1100px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:28px 0 8px;padding-bottom:4px;border-bottom:2px solid var(--ink)}
.az{color:var(--grau);margin:0 0 16px;font-size:14px}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border:1px solid var(--linie);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--hell);font-weight:bold;white-space:nowrap}
table.daten th{width:240px}
td.text{white-space:pre-wrap;word-break:break-word}
.status{display:inline-block;border:1px solid currentColor;padding:0 6px;font-size:13px;white-space:nowrap}
.s-offen{color:var(--warn)}.s-ok{color:var(--ok)}.s-nein{color:var(--rot)}.s-neutral{color:var(--grau)}
form.zeile{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin:8px 0}
label{display:block;font-size:13px;color:var(--grau);margin-bottom:2px}
input[type=text],input[type=search],select,textarea{font:inherit;padding:6px 8px;border:1px solid #777;border-radius:0;background:#fff;color:var(--ink);max-width:100%}
textarea{width:100%;min-height:90px}
.btn,button.btn{font:inherit;border:1px solid var(--kopf);background:var(--kopf);color:#fff;padding:7px 14px;cursor:pointer;text-decoration:none;display:inline-flex;gap:6px;align-items:center;border-radius:0}
.btn.zweit{background:#fff;color:var(--kopf)}
.btn.gefahr{background:#fff;color:var(--rot);border-color:var(--rot)}
.hinweis{border:1px solid var(--linie);border-left:4px solid var(--akzent);background:var(--hell);padding:8px 12px;margin:12px 0}
.hinweis.fehler{border-left-color:var(--rot)}
.kennzahlen{display:flex;gap:0;flex-wrap:wrap;margin:8px 0}
.kennzahlen div{border:1px solid var(--linie);margin:0 -1px -1px 0;padding:10px 18px;min-width:150px}
.kennzahlen b{display:block;font-size:24px}
.leer{color:var(--grau);padding:8px 0}
.seiten{display:flex;gap:12px;margin:10px 0}
.balken{display:block;height:12px;background:var(--kopf);min-width:1px}
td.bar{width:45%}
.aktionen{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 0}
.warnung{border:1px solid var(--rot);border-left:4px solid var(--rot);padding:8px 12px;margin:12px 0}
@media print{nav,.kopf,.aktionen,form{display:none}.rahmen{display:block}}
@media (max-width:800px){
 .kopf input[type=search]{width:130px}
 .kopf .logo img{height:48px}
 .kopf .logo img.lang{display:none}.kopf .logo img.kurz{display:block}
 .rahmen{display:block}
 nav{width:auto;border-right:0;border-bottom:1px solid var(--linie);display:flex;flex-wrap:wrap;padding:0}
 nav a{border-left:0;border-bottom:3px solid transparent;padding:10px 12px}
 nav a.aktiv{border-bottom-color:var(--akzent)}
 nav hr,nav .konto{display:none}
 nav form{margin-left:auto}
 main{padding:16px 14px 40px}
 table.daten th{width:auto;white-space:normal}
 table.liste,table.liste tbody,table.liste tr,table.liste td{display:block;width:100%}
 table.liste thead{display:none}
 table.liste tr{border:1px solid var(--linie);margin-bottom:8px}
 table.liste td{border:0;border-bottom:1px solid #e0e0e0}
 table.liste td::before{content:attr(data-l) ": ";color:var(--grau);font-size:13px}
}

/* ---- Design-Modus „Minimalistisch“ (html.min): Symbolleiste links, fährt beim Darüberfahren aus; auf dem Handy Standard ---- */
html.min body{color:#222;font-size:15px}
html.min .kopf{border-bottom:0;padding:10px 16px 10px 72px;min-height:56px}
html.min .kopf .logo img{height:40px}
html.min .kopf input[type=search]{border:0;border-bottom:1px solid #ccc;padding:6px 4px;width:200px;background:transparent}
html.min .kopf input[type=search]:focus{outline:0;border-bottom-color:#111}
html.min .kopf button{background:transparent;border:0;color:#555;padding:6px}
html.min .rahmen{display:block;min-height:0}
html.min nav{position:fixed;top:0;bottom:0;left:0;width:56px;z-index:20;overflow:hidden;display:block;padding:12px 0;background:#fff;border:0;border-right:1px solid #eee;transition:width .18s ease,box-shadow .18s ease}
html.min nav:hover,html.min nav:focus-within,html.min nav.offen{width:236px;box-shadow:4px 0 24px rgba(0,0,0,.08)}
html.min nav a,html.min nav button.link{white-space:nowrap;gap:16px;padding:11px 19px;border-left:0;color:#444;border-bottom:0}
html.min nav a:hover,html.min nav button.link:hover{background:#f4f4f4}
html.min nav a.aktiv{background:transparent;color:#000;font-weight:600;box-shadow:inset 3px 0 0 #111}
html.min nav span{opacity:0;transition:opacity .12s}
html.min nav:hover span,html.min nav:focus-within span,html.min nav.offen span{opacity:1}
html.min nav hr{display:block;border-top:1px solid #eee;margin:10px 16px}
html.min nav .konto{display:block;padding:6px 19px;white-space:nowrap;opacity:0;transition:opacity .12s}
html.min nav:hover .konto,html.min nav:focus-within .konto,html.min nav.offen .konto{opacity:1}
html.min nav form{margin:0}
html.min main{max-width:980px;margin:0 auto;padding:24px 20px 56px 72px}
html.min h1{font-size:20px;font-weight:600}
html.min h2{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--grau);border:0;margin:34px 0 6px;padding:0}
html.min .az{color:#888}
html.min table{border-collapse:collapse}
html.min th,html.min td{border:0;border-bottom:1px solid #eee;padding:9px 10px 9px 0}
html.min th{background:transparent;color:#888;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
html.min table.daten th{text-transform:none;font-size:14px;letter-spacing:0}
html.min .status{border:0;background:#f3f3f3;border-radius:10px;padding:1px 9px;font-size:12px}
html.min .kennzahlen div{border:0;margin:0;padding:6px 32px 6px 0;min-width:0}
html.min .kennzahlen b{font-size:28px;font-weight:500}
html.min .btn,html.min button.btn{background:#111;border:1px solid #111;border-radius:6px;padding:7px 14px}
html.min .btn.zweit{background:transparent;color:#111;border-color:#ddd}
html.min .btn.gefahr{background:transparent;color:var(--rot);border-color:#e4c4c4}
html.min input[type=text],html.min input[type=search],html.min select,html.min textarea{border:1px solid #ddd;border-radius:6px;padding:7px 9px}
html.min .hinweis{border:0;border-radius:6px;background:#f6f6f6}
html.min .warnung{border:0;border-radius:6px;background:#fbf1f1}
html.min .balken{background:#111;border-radius:2px}
@media (max-width:800px){
 html.min .kopf{padding:8px 12px 8px 60px}
 html.min .kopf .logo img.lang{display:none}html.min .kopf .logo img.kurz{display:block;height:38px}
 html.min .kopf input[type=search]{width:120px}
 html.min nav{width:48px}
 html.min nav a,html.min nav button.link{padding:12px 15px}
 html.min nav .konto{padding:6px 15px}
 html.min main{padding:16px 14px 48px 60px}
 html.min table.liste tr{border:0;border-bottom:1px solid #eee;margin:0;padding:6px 0}
 html.min table.liste td{border:0;padding:3px 0}
}
.nur-min{display:none}
html.min .nur-min{display:inline}html.min .nur-std{display:none}
"""


ICONS["panel-left"] = '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>'


def ic(name):
    return f'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'


NAV = [("uebersicht", "layout-dashboard", "Übersicht", ""), ("buerger", "book-user", "Bürgerakten", "buerger/"),
       ("verfahren", "folder-open", "Einbürgerungsakten", "verfahren/"), ("statistik", "chart-column", "Statistiken", "statistik/"),
       ("protokoll", "scroll-text", "Löschprotokoll", "protokoll/")]


def rahmen(titel, aktiv, inhalt, k, csrf, q=""):
    logo, logo_name = logo_von(k)
    nav = "".join(f'<a href="{BASIS}{pfad}" title="{esc(text)}" class="{"aktiv" if schl == aktiv else ""}">{ic(sym)}<span>{esc(text)}</span></a>'
                  for schl, sym, text, pfad in NAV)
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{esc(titel)} – {esc(logo_name)}, Amtsseite</title><style>{CSS}</style>
<script>(function(){{var m;try{{m=localStorage.getItem("amtModus")}}catch(e){{}}if(m!=="min"&&m!=="std")m=matchMedia("(max-width:800px)").matches?"min":"std";document.documentElement.className=m}})()</script></head>
<body>
<header class="kopf"><a class="logo" href="{BASIS}" title="{esc(logo_name)} – Amtsseite"><img class="lang" src="{BASIS}logo/{logo}-kopf.png" alt="{esc(logo_name)}"><img class="kurz" src="{BASIS}logo/{logo}-kurz.png" alt="{esc(logo_name)}"></a><span class="raum"></span>
<form action="{BASIS}buerger/" method="get" role="search"><input type="search" name="q" value="{esc(q)}" placeholder="Name, Aktenzeichen, ID" aria-label="Suche"><button type="submit" aria-label="Suchen">{ic("search")}</button></form></header>
<div class="rahmen"><nav aria-label="Amtsseite">{nav}<hr>
<a href="/informationen/die-reichsbehoerden/" title="Zur Website">{ic("house")}<span>Zur Website</span></a>
<div class="konto">{esc(k["name"])}</div>
<button class="link" type="button" id="modus" title="Design-Modus wechseln">{ic("panel-left")}<span><span class="nur-std">Design: Minimalistisch</span><span class="nur-min">Design: Standard</span></span></button>
<form method="post" action="/abmelden/"><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="weiter" value="/">
<button class="link" type="submit" title="Abmelden">{ic("log-out")}<span>Abmelden</span></button></form></nav>
<main id="inhalt">{inhalt}</main></div>
<script>document.getElementById("modus").addEventListener("click",function(){{var d=document.documentElement,m=d.className==="min"?"std":"min";d.className=m;try{{localStorage.setItem("amtModus",m)}}catch(e){{}}}});
document.querySelector("nav").addEventListener("touchstart",function(e){{if(!this.classList.contains("offen")&&e.target.closest("a,button")===null)this.classList.add("offen")}},{{passive:true}});
document.addEventListener("touchstart",function(e){{var n=document.querySelector("nav");if(!n.contains(e.target))n.classList.remove("offen")}},{{passive:true}});</script></body></html>"""


def status_marke(klasse, text):
    return f'<span class="status s-{klasse}">{esc(text)}</span>'


def akte_marke(s):
    return status_marke({"staatsbuerger": "ok", "einwanderer": "offen"}.get(s, "neutral"), STATUS_AKTE.get(s, s))


def ergebnis_marke(e):
    return status_marke({"eingebuergert": "ok", "abgelehnt": "nein", "offen": "offen"}.get(e, "neutral"), ERGEBNIS.get(e, e))


def tabelle(kopf, zeilen, leer="Keine Einträge."):
    if not zeilen:
        return f'<p class="leer">{esc(leer)}</p>'
    th = "".join(f"<th>{esc(h)}</th>" for h in kopf)
    tr = "".join("<tr>" + "".join(f'<td data-l="{esc(kopf[i])}">{c}</td>' for i, c in enumerate(z)) + "</tr>" for z in zeilen)
    return f'<table class="liste"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'


def daten_tabelle(paare):
    return '<table class="daten">' + "".join(f'<tr><th>{esc(a)}</th><td class="text">{b}</td></tr>' for a, b in paare) + "</table>"


def csrf_feld(request):
    return f'<input type="hidden" name="csrf" value="{esc(request["csrf"])}">'


def meldung(request):
    m = request.query.get("m")
    if not m:
        return ""
    return f'<div class="hinweis{" fehler" if request.query.get("f") else ""}">{esc(m)}</div>'


def eintraege_html(con, ziel, ziel_id):
    zeilen = [(_zeit(e["zeit"]), esc(e["art"]), f'<span style="white-space:pre-wrap">{esc(e["text"])}</span>', esc(e["autor_name"] or "System"))
              for e in con.execute("SELECT * FROM amt_eintraege WHERE ziel=? AND ziel_id=? ORDER BY zeit DESC, id DESC", (ziel, ziel_id))]
    return tabelle(["Zeit", "Art", "Inhalt", "Bearbeiter"], zeilen, "Noch keine Vorgänge.")


def vermerk_formular(request, pfad):
    return (f'<form method="post" action="{pfad}vermerk">{csrf_feld(request)}<label for="vm">Neuer Vermerk</label>'
            f'<textarea id="vm" name="text" required maxlength="2000"></textarea><p><button class="btn" type="submit">{ic("notebook-pen")}Vermerk anfügen</button></p></form>')


# ---------------------------------------------------------------- Daten

def eintrag(con, ziel, ziel_id, art, text, autor_id=None, autor_name=""):
    con.execute("INSERT INTO amt_eintraege (ziel, ziel_id, zeit, art, text, autor_id, autor_name) VALUES (?,?,?,?,?,?,?)",
                (ziel, ziel_id, int(time.time()), art, text, autor_id, autor_name))


def akte_sichern(con, konto_id, name, status="einwanderer", ic_name="", art="Akte angelegt"):
    """Bürgerakte zum Konto (legt sie an, falls sie fehlt). Gibt die Zeile zurück."""
    z = con.execute("SELECT * FROM amt_akten WHERE konto_id=?", (konto_id,)).fetchone()
    if z:
        return z
    jetzt = int(time.time())
    cur = con.execute("INSERT INTO amt_akten (konto_id, name, ic_name, status, angelegt, aktualisiert) VALUES (?,?,?,?,?,?)",
                      (konto_id, name, ic_name, status, jetzt, jetzt))
    eintrag(con, "akte", cur.lastrowid, art, f"Bürgerakte {az_akte(cur.lastrowid)} angelegt.")
    return con.execute("SELECT * FROM amt_akten WHERE id=?", (cur.lastrowid,)).fetchone()


async def abgleich(app):
    """Bürgerakten für alle Staatsbürger anlegen, Namen und Status nachführen."""
    dc, con = app["discord"], app["db"]
    mitglieder = await dc.mitglieder()
    if not mitglieder:
        return
    da = {m["id"]: m for m in mitglieder}
    neu = 0
    for m in mitglieder:
        if ROLLE_STAATSBUERGER not in m["rollen"]:
            continue
        z = con.execute("SELECT * FROM amt_akten WHERE konto_id=?", (m["id"],)).fetchone()
        if not z:
            if con.execute("SELECT 1 FROM amt_loeschungen WHERE konto_id=?", (m["id"],)).fetchone():
                continue   # bewusst gelöscht: nicht neu anlegen
            akte_sichern(con, m["id"], m["name"], "staatsbuerger", m["name"], "Akte angelegt (Abgleich)")
            neu += 1
            continue
        if z["status"] != "staatsbuerger":
            con.execute("UPDATE amt_akten SET status='staatsbuerger', aktualisiert=? WHERE id=?", (int(time.time()), z["id"]))
            eintrag(con, "akte", z["id"], "Status", "Staatsbürger (laut Discord-Rolle).")
        if z["name"] != m["name"]:
            con.execute("UPDATE amt_akten SET name=? WHERE id=?", (m["name"], z["id"]))
    for z in con.execute("SELECT * FROM amt_akten WHERE status='staatsbuerger'").fetchall():
        m = da.get(z["konto_id"])
        if not m or ROLLE_STAATSBUERGER not in m["rollen"]:
            con.execute("UPDATE amt_akten SET status='nicht_mehr', aktualisiert=? WHERE id=?", (int(time.time()), z["id"]))
            eintrag(con, "akte", z["id"], "Status", "Nicht mehr Staatsbürger bzw. nicht mehr auf dem Server.")
    con.commit()
    if neu:
        log.info("Bürgerakten angelegt: %d", neu)


async def abgleich_schleife(app):
    while True:
        try:
            await abgleich(app)
        except Exception:
            log.exception("Abgleich der Bürgerakten fehlgeschlagen")
        await asyncio.sleep(15 * 60)


async def _start(app):
    app["amt_task"] = asyncio.create_task(abgleich_schleife(app))


async def _stop(app):
    app["amt_task"].cancel()


# ---------------------------------------------------------------- Seiten

def _beamter(handler):
    """Lesezugriff (Beamte und Leseberechtigte); Änderungen prüft _post() auf Schreibrecht."""
    return anmeldung.angemeldet(ist_leser, "Die Amtsseite ist den Beamten der Kaiserlichen Zollverwaltung, dem Kanzler und weiteren Berechtigten vorbehalten.")(handler)


def schreiben(request):
    return ist_beamter(request["konto"])


def _gesperrt_seite(request, titel, aktiv, az):
    inhalt = (f'<h1>{ic("lock")} {esc(az)}</h1><p class="az">{esc(titel)}</p>'
              f'<div class="warnung">{ic("lock")} Diese Akte steht unter Verschluss. Sie haben keinen Zugang. '
              'Einsicht ist nur dem Kaiser und dem Kanzler vorbehalten.</div>'
              f'<p><a class="btn zweit" href="{BASIS}">{ic("arrow-left")}Zurück zur Übersicht</a></p>')
    return web.Response(status=403, content_type="text/html", text=rahmen(titel, aktiv, inhalt, request["konto"], request["csrf"]))


def _verschluss_marke():
    return f'<span class="status s-nein">{ic("lock")} Unter Verschluss</span>'


def _ant(request, titel, aktiv, inhalt, q=""):
    return web.Response(content_type="text/html", text=rahmen(titel, aktiv, inhalt, request["konto"], request["csrf"], q))


def _verfahren_zeile(v, sperr=frozenset()):
    if v["konto_id"] in sperr:
        return (f'<a href="{BASIS}verfahren/{v["id"]}/">{az_verfahren(v["id"], v["erstellt"])}</a>', _verschluss_marke(), "–", "–")
    return (f'<a href="{BASIS}verfahren/{v["id"]}/">{az_verfahren(v["id"], v["erstellt"])}</a>', esc(v["name"]),
            esc(ERGEBNIS[v["ergebnis"]] if v["ergebnis"] != "offen" else PHASE.get(v["phase"], "")), _zeit(v["aktualisiert"]))


@_beamter
async def uebersicht(request):
    con = request.app["db"]
    n = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    kz = [("Bürgerakten", n("SELECT COUNT(*) FROM amt_akten")), ("Staatsbürger", n("SELECT COUNT(*) FROM amt_akten WHERE status='staatsbuerger'")),
          ("Einwanderer", n("SELECT COUNT(*) FROM amt_akten WHERE status='einwanderer'")),
          ("Offene Verfahren", n("SELECT COUNT(*) FROM amt_verfahren WHERE ergebnis='offen'")),
          ("Eingebürgert", n("SELECT COUNT(*) FROM amt_verfahren WHERE ergebnis='eingebuergert'"))]
    zahlen = "".join(f"<div><b>{z}</b>{esc(t)}</div>" for t, z in kz)
    offen = con.execute("SELECT * FROM amt_verfahren WHERE ergebnis='offen' ORDER BY (phase=3) DESC, (phase=1) DESC, aktualisiert").fetchall()
    sa, sk = sperren(con, request["konto"])
    zeilen = [_verfahren_zeile(v, sk) for v in offen]
    verf_gesperrt = {r["id"] for r in con.execute("SELECT id, konto_id FROM amt_verfahren") if r["konto_id"] in sk}
    letzte = [(_zeit(e["zeit"]), esc(e["art"]) if not ((e["ziel"] == "akte" and e["ziel_id"] in sa) or (e["ziel"] == "verfahren" and e["ziel_id"] in verf_gesperrt)) else "–",
               esc(e["text"][:160]) if not ((e["ziel"] == "akte" and e["ziel_id"] in sa) or (e["ziel"] == "verfahren" and e["ziel_id"] in verf_gesperrt)) else _verschluss_marke(),
               f'<a href="{BASIS}{"buerger" if e["ziel"] == "akte" else "verfahren"}/{e["ziel_id"]}/">'
               f'{az_akte(e["ziel_id"]) if e["ziel"] == "akte" else "Verfahren " + str(e["ziel_id"])}</a>')
              for e in con.execute("SELECT * FROM amt_eintraege ORDER BY id DESC LIMIT 12")]
    inhalt = (f'<h1>{ic("layout-dashboard")} Übersicht</h1><p class="az">Reichsbehörden · Kaiserliche Zollverwaltung</p>{meldung(request)}'
              f'<div class="kennzahlen">{zahlen}</div>'
              f'<h2>Zur Bearbeitung</h2>{tabelle(["Aktenzeichen", "Name", "Stand", "Zuletzt"], zeilen, "Keine offenen Verfahren.")}'
              f'<h2>Letzte Vorgänge</h2>{tabelle(["Zeit", "Art", "Inhalt", "Akte"], letzte, "Noch keine Vorgänge.")}'
              '<p class="az">Phase II einleiten und einbürgern erfolgt im Ticket auf dem Discord-Server (Kanal Einwanderungsbehörde, Befehl /einbürgern).</p>')
    return _ant(request, "Übersicht", "uebersicht", inhalt)


@_beamter
async def buerger_liste(request):
    con = request.app["db"]
    q = request.query.get("q", "").strip()[:80]
    status = request.query.get("status", "")
    seite_nr = max(1, int(request.query.get("seite", "1")) if request.query.get("seite", "1").isdigit() else 1)
    wo, par = [], []
    if q:
        like = f"%{q}%"
        wo.append("(name LIKE ? OR ic_name LIKE ? OR konto_id LIKE ? OR fraktion LIKE ? OR ('BA-' || printf('%05d', id)) LIKE ?)")
        par += [like] * 5
    if status in STATUS_AKTE:
        wo.append("status=?")
        par.append(status)
    w = (" WHERE " + " AND ".join(wo)) if wo else ""
    gesamt = con.execute(f"SELECT COUNT(*) FROM amt_akten{w}", par).fetchone()[0]
    rows = con.execute(f"SELECT * FROM amt_akten{w} ORDER BY ic_name COLLATE NOCASE, name COLLATE NOCASE LIMIT ? OFFSET ?",
                       par + [SEITE_GROESSE, (seite_nr - 1) * SEITE_GROESSE]).fetchall()
    sa, _sk = sperren(con, request["konto"])
    zeilen = [(f'<a href="{BASIS}buerger/{r["id"]}/">{az_akte(r["id"])}</a>', "–", "–", "–", _verschluss_marke()) if r["id"] in sa else
              (f'<a href="{BASIS}buerger/{r["id"]}/">{az_akte(r["id"])}</a>', esc(r["ic_name"] or "–"), esc(r["name"]), esc(r["fraktion"] or "–"),
               akte_marke(r["status"]) + (" " + _verschluss_marke() if r["verschluss"] else ""))
              for r in rows]
    opt = "".join(f'<option value="{k}"{" selected" if k == status else ""}>{esc(v)}</option>' for k, v in STATUS_AKTE.items())
    basis = f"?q={esc(q)}&amp;status={esc(status)}"
    nav = ""
    if seite_nr > 1:
        nav += f'<a href="{basis}&amp;seite={seite_nr - 1}">← Zurück</a>'
    if seite_nr * SEITE_GROESSE < gesamt:
        nav += f'<a href="{basis}&amp;seite={seite_nr + 1}">Weiter →</a>'
    inhalt = (f'<h1>{ic("book-user")} Bürgerakten</h1><p class="az">{gesamt} Akten</p>{meldung(request)}'
              f'<form class="zeile" method="get"><div><label for="q">Suche</label><input type="search" id="q" name="q" value="{esc(q)}"></div>'
              f'<div><label for="st">Status</label><select id="st" name="status"><option value="">Alle</option>{opt}</select></div>'
              f'<button class="btn" type="submit">{ic("search")}Suchen</button></form>'
              f'{tabelle(["Aktenzeichen", "Name (IC)", "Discord-Name", "Fraktion", "Status"], zeilen, "Keine Akten gefunden.")}'
              f'<div class="seiten">{nav}</div>')
    return _ant(request, "Bürgerakten", "buerger", inhalt, q)


def _optionen(liste, aktuell, leer="–"):
    o = f'<option value="">{leer}</option>' + "".join(f'<option{" selected" if x == aktuell else ""}>{esc(x)}</option>' for x in liste)
    if aktuell and aktuell not in liste:
        o += f'<option selected>{esc(aktuell)}</option>'
    return o


def _stamm(z):
    return daten_tabelle([("Aktenzeichen", az_akte(z["id"])), ("Status", akte_marke(z["status"])), ("Name (IC)", esc(z["ic_name"] or "–")),
                           ("Geburtsdatum (IC)", esc(z["ic_geburt"] or "–")), ("Fraktion", esc(z["fraktion"] or "–")),
                           ("Gesellschaftsschicht", esc(z["schicht"] or "–")), ("Berufliche Zugehörigkeit", esc(z["beruf"] or "–")),
                           ("Discord-Name", esc(z["name"])), ("Discord-ID", esc(z["konto_id"])),
                           ("Angelegt", _zeit(z["angelegt"])), ("Zuletzt geändert", _zeit(z["aktualisiert"]))])


@_beamter
async def buerger_akte(request):
    con = request.app["db"]
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (request.match_info["id"],)).fetchone() if request.match_info["id"].isdigit() else None
    if not z:
        raise web.HTTPNotFound(text="Akte nicht gefunden.")
    if z["verschluss"] and not darf_verschluss(request["konto"]):
        return _gesperrt_seite(request, "Bürgerakte", "buerger", az_akte(z["id"]))
    stamm = _stamm(z)
    pfad = f"{BASIS}buerger/{z['id']}/"
    form = (f'<form class="zeile" method="post" action="{pfad}bearbeiten">{csrf_feld(request)}'
            f'<div><label for="n">Name (IC)</label><input type="text" id="n" name="ic_name" value="{esc(z["ic_name"])}" maxlength="80"></div>'
            f'<div><label for="g">Geburtsdatum (IC)</label><input type="text" id="g" name="ic_geburt" value="{esc(z["ic_geburt"])}" maxlength="40"></div>'
            f'<div><label for="f">Fraktion</label><input type="text" id="f" name="fraktion" value="{esc(z["fraktion"])}" maxlength="80"></div>'
            f'<div><label for="s">Schicht</label><select id="s" name="schicht">{_optionen(SCHICHTEN, z["schicht"])}</select></div>'
            f'<div><label for="b">Beruf</label><select id="b" name="beruf">{_optionen(BERUFE, z["beruf"])}</select></div>'
            f'<button class="btn zweit" type="submit">{ic("pencil")}Stammdaten ändern</button></form>')
    vs = [_verfahren_zeile(v) for v in con.execute("SELECT * FROM amt_verfahren WHERE konto_id=? ORDER BY id DESC", (z["konto_id"],))]
    w = schreiben(request)
    verschluss_form = ""
    if darf_verschluss(request["konto"]):
        verschluss_form = (f'<form method="post" action="{pfad}verschluss" style="display:inline">{csrf_feld(request)}'
                           f'<input type="hidden" name="wert" value="{0 if z["verschluss"] else 1}">'
                           f'<button class="btn zweit" type="submit">{ic("lock-open" if z["verschluss"] else "lock")}'
                           f'{"Verschluss aufheben" if z["verschluss"] else "Unter Verschluss setzen"}</button></form>')
    inhalt = (f'<h1>{ic("book-user")} Bürgerakte {az_akte(z["id"])}</h1><p class="az">{esc(z["ic_name"] or z["name"])}</p>{meldung(request)}'
              + (f'<div class="warnung">{ic("lock")} Diese Akte steht unter Verschluss; nur Kaiser und Kanzler können sie einsehen.</div>' if z["verschluss"] else "")
              + (f'<div class="hinweis">Nur Lesezugriff: Änderungen sind mit deiner Berechtigung nicht möglich.</div>' if not w else "")
              + f'<div class="aktionen"><a class="btn zweit" href="{pfad}pdf">{ic("file-down")}Als PDF exportieren</a>'
              + (f'<a class="btn gefahr" href="{pfad}loeschen/">{ic("trash-2")}Akte löschen</a>' if w else "") + verschluss_form + '</div>'
              f'<h2>Stammdaten</h2>{stamm}{form if w else ""}'
              f'<h2>Einbürgerungsakten</h2>{tabelle(["Aktenzeichen", "Name", "Stand", "Zuletzt"], vs, "Kein Einreiseverfahren erfasst.")}'
              f'<h2>Vorgänge</h2>{eintraege_html(con, "akte", z["id"])}' + (f'<h2>Vermerk</h2>{vermerk_formular(request, pfad)}' if w else ""))
    return _ant(request, f"Bürgerakte {az_akte(z['id'])}", "buerger", inhalt)


@_beamter
async def verfahren_liste(request):
    con = request.app["db"]
    status = request.query.get("status", "")
    w, par = ("WHERE ergebnis=?", [status]) if status in ERGEBNIS else ("", [])
    rows = con.execute(f"SELECT * FROM amt_verfahren {w} ORDER BY id DESC LIMIT 500", par).fetchall()
    _sa, sk = sperren(con, request["konto"])
    zeilen = [_verfahren_zeile(v, sk) + (("–",) if v["konto_id"] in sk else (ergebnis_marke(v["ergebnis"]),)) for v in rows]
    opt = "".join(f'<option value="{k}"{" selected" if k == status else ""}>{esc(v)}</option>' for k, v in ERGEBNIS.items())
    inhalt = (f'<h1>{ic("folder-open")} Einbürgerungsakten</h1><p class="az">{len(rows)} Akten</p>{meldung(request)}'
              f'<form class="zeile" method="get"><div><label for="st">Ergebnis</label><select id="st" name="status"><option value="">Alle</option>{opt}</select></div>'
              f'<button class="btn" type="submit">{ic("search")}Filtern</button></form>'
              f'{tabelle(["Aktenzeichen", "Name", "Stand", "Zuletzt", "Ergebnis"], zeilen, "Keine Akten.")}')
    return _ant(request, "Einbürgerungsakten", "verfahren", inhalt)


def _felder(daten, felder):
    d = json.loads(daten or "{}")
    return daten_tabelle([(lbl, esc(d.get(k) or "–")) for k, lbl in felder]) if d else '<p class="leer">Noch nicht ausgefüllt.</p>'


def _verfahren_kopf(con, v):
    akte = con.execute("SELECT id FROM amt_akten WHERE konto_id=?", (v["konto_id"],)).fetchone()
    return daten_tabelle([("Aktenzeichen", az_verfahren(v["id"], v["erstellt"])), ("Antragsteller", esc(v["name"])), ("Discord-ID", esc(v["konto_id"])),
                          ("Stand", esc(PHASE.get(v["phase"], "") if v["ergebnis"] == "offen" else "Abgeschlossen")), ("Ergebnis", ergebnis_marke(v["ergebnis"])),
                          ("Eingegangen", _zeit(v["erstellt"])), ("Abgeschlossen", _zeit(v["abgeschlossen"])),
                          ("Bürgerakte", f'<a href="{BASIS}buerger/{akte["id"]}/">{az_akte(akte["id"])}</a>' if akte else "–"),
                          ("Ticket", esc(f"Discord-Thread {v['thread_id']}") if v["thread_id"] else "–")])


@_beamter
async def verfahren_akte(request):
    con = request.app["db"]
    v = con.execute("SELECT * FROM amt_verfahren WHERE id=?", (request.match_info["id"],)).fetchone() if request.match_info["id"].isdigit() else None
    if not v:
        raise web.HTTPNotFound(text="Akte nicht gefunden.")
    if konto_gesperrt(con, request["konto"], v["konto_id"]):
        return _gesperrt_seite(request, "Einbürgerungsakte", "verfahren", az_verfahren(v["id"], v["erstellt"]))
    pfad = f"{BASIS}verfahren/{v['id']}/"
    kopf = _verfahren_kopf(con, v)
    w = schreiben(request)
    schliessen = ""
    if v["ergebnis"] == "offen" and w:
        schliessen = (f'<h2>Abschluss</h2><form class="zeile" method="post" action="{pfad}schliessen">{csrf_feld(request)}'
                      f'<div><label for="e">Verfahren beenden als</label><select id="e" name="ergebnis"><option value="abgelehnt">Abgelehnt</option>'
                      f'<option value="geschlossen">Ohne Einbürgerung geschlossen</option></select></div>'
                      f'<div><label for="g">Begründung</label><input type="text" id="g" name="grund" maxlength="300" required></div>'
                      f'<button class="btn gefahr" type="submit">{ic("file-x")}Verfahren beenden</button></form>'
                      '<p class="az">Die Einbürgerung selbst erfolgt mit /einbürgern auf dem Discord-Server.</p>')
    inhalt = (f'<h1>{ic("folder-open")} Einbürgerungsakte {az_verfahren(v["id"], v["erstellt"])}</h1><p class="az">{esc(v["name"])}</p>{meldung(request)}'
              f'<div class="aktionen"><a class="btn zweit" href="{pfad}pdf">{ic("file-down")}Als PDF exportieren</a></div>'
              f'<h2>Akte</h2>{kopf}<h2>Phase I – außerhalb des Charakters</h2>{_felder(v["phase1"], PHASE1_FELDER)}'
              f'<h2>Phase II – im Charakter</h2>{_felder(v["phase2"], PHASE2_FELDER)}{schliessen}'
              f'<h2>Vorgänge</h2>{eintraege_html(con, "verfahren", v["id"])}' + (f'<h2>Vermerk</h2>{vermerk_formular(request, pfad)}' if w else ""))
    return _ant(request, "Einbürgerungsakte", "verfahren", inhalt)



# ---------------------------------------------------------------- Statistiken

def _balken(zeilen, leer="Keine Daten."):
    """zeilen: [(Bezeichnung, Anzahl)] → Tabelle mit Balken."""
    if not zeilen:
        return f'<p class="leer">{esc(leer)}</p>'
    m = max(z for _, z in zeilen) or 1
    return ('<table><thead><tr><th>Bezeichnung</th><th>Anzahl</th><th></th></tr></thead><tbody>' + "".join(
        f'<tr><td>{esc(b)}</td><td>{z}</td><td class="bar"><span class="balken" style="width:{round(100 * z / m)}%"></span></td></tr>' for b, z in zeilen) + '</tbody></table>')


def statistik_inhalt(con, drucken=False):
    def gruppe(spalte, status="staatsbuerger"):
        return [(r[0] or "Nicht erfasst", r[1]) for r in con.execute(
            f"SELECT {spalte}, COUNT(*) n FROM amt_akten WHERE status=? GROUP BY {spalte} ORDER BY n DESC", (status,))]
    n = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    kz = [("Bürgerakten", n("SELECT COUNT(*) FROM amt_akten")), ("Staatsbürger", n("SELECT COUNT(*) FROM amt_akten WHERE status='staatsbuerger'")),
          ("Einwanderer", n("SELECT COUNT(*) FROM amt_akten WHERE status='einwanderer'")),
          ("Nicht mehr Staatsbürger", n("SELECT COUNT(*) FROM amt_akten WHERE status='nicht_mehr'")),
          ("Einbürgerungsakten", n("SELECT COUNT(*) FROM amt_verfahren")), ("Offene Verfahren", n("SELECT COUNT(*) FROM amt_verfahren WHERE ergebnis='offen'"))]
    zahlen = "".join(f"<div><b>{z}</b>{esc(t)}</div>" for t, z in kz)
    erg = [(ERGEBNIS[r[0]], r[1]) for r in con.execute("SELECT ergebnis, COUNT(*) FROM amt_verfahren GROUP BY ergebnis ORDER BY 2 DESC")]
    phasen = [(PHASE[r[0]], r[1]) for r in con.execute("SELECT phase, COUNT(*) FROM amt_verfahren WHERE ergebnis='offen' GROUP BY phase ORDER BY phase")]
    monate = {}
    for (t,) in con.execute("SELECT abgeschlossen FROM amt_verfahren WHERE ergebnis='eingebuergert' AND abgeschlossen IS NOT NULL"):
        m = datetime.fromtimestamp(t, BERLIN).strftime("%Y-%m")
        monate[m] = monate.get(m, 0) + 1
    monatsliste = [(f"{m[5:]}/{m[:4]}", z) for m, z in sorted(monate.items())[-12:]]
    dauer = con.execute("SELECT AVG(abgeschlossen - erstellt), COUNT(*) FROM amt_verfahren WHERE ergebnis='eingebuergert' AND thread_id IS NOT NULL").fetchone()
    dauer_text = f"{dauer[0] / 86400:.1f} Tage (aus {dauer[1]} Verfahren mit Ticket)" if dauer[1] else "Keine Daten"
    return (f'<div class="kennzahlen">{zahlen}</div>'
            f'<h2>Staatsbürger nach Fraktion</h2>{_balken(gruppe("fraktion"))}'
            f'<h2>Staatsbürger nach Gesellschaftsschicht</h2>{_balken(gruppe("schicht"))}'
            f'<h2>Staatsbürger nach beruflicher Zugehörigkeit</h2>{_balken(gruppe("beruf"))}'
            f'<h2>Einbürgerungsverfahren nach Ergebnis</h2>{_balken(erg)}'
            f'<h2>Offene Verfahren nach Stand</h2>{_balken(phasen, "Keine offenen Verfahren.")}'
            f'<h2>Einbürgerungen je Monat (letzte 12 Monate mit Einbürgerungen)</h2>{_balken(monatsliste)}'
            f'<h2>Durchschnittliche Verfahrensdauer</h2><p>{esc(dauer_text)}</p>'
            '<p class="az">Hinweis: „Nicht erfasst“ sind Staatsbürger, deren Angaben im Charakter noch nicht in der Akte stehen (z. B. Einbürgerungen vor dem 03.11.2026).</p>')


@_beamter
async def statistik(request):
    inhalt = (f'<h1>{ic("chart-column")} Statistiken</h1><p class="az">Stand {_zeit(int(time.time()))}</p>'
              f'<div class="aktionen"><a class="btn zweit" href="{BASIS}statistik/pdf">{ic("file-down")}Als PDF exportieren</a></div>'
              f'{statistik_inhalt(request.app["db"])}')
    return _ant(request, "Statistiken", "statistik", inhalt)


# ---------------------------------------------------------------- Löschen und Protokoll

@_beamter
async def buerger_loeschen_seite(request):
    con, i = request.app["db"], request.match_info["id"]
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not z:
        raise web.HTTPNotFound(text="Akte nicht gefunden.")
    if not schreiben(request):
        raise web.HTTPForbidden(text="Nur Lesezugriff.")
    if z["verschluss"] and not darf_verschluss(request["konto"]):
        return _gesperrt_seite(request, "Bürgerakte", "buerger", az_akte(z["id"]))
    nv = con.execute("SELECT COUNT(*) FROM amt_verfahren WHERE konto_id=?", (z["konto_id"],)).fetchone()[0]
    pfad = f"{BASIS}buerger/{i}/"
    inhalt = (f'<h1>{ic("trash-2")} Bürgerakte {az_akte(z["id"])} löschen</h1><p class="az">{esc(z["ic_name"] or z["name"])}</p>{meldung(request)}'
              f'<div class="warnung">{ic("triangle-alert")} Die Akte mit allen Vorgängen und Vermerken wird endgültig gelöscht. Das kann nicht rückgängig gemacht werden. '
              'Die Löschung wird im Löschprotokoll festgehalten (ohne Akteninhalt). Gelöschte Staatsbürger werden vom Abgleich nicht erneut angelegt.</div>'
              f'{_stamm(z)}'
              f'<form method="post" action="{pfad}loeschen">{csrf_feld(request)}'
              f'<p><label for="az">Zur Bestätigung das Aktenzeichen eingeben ({az_akte(z["id"])})</label><input type="text" id="az" name="bestaetigung" autocomplete="off" required></p>'
              f'<p><label for="gr">Grund der Löschung</label><input type="text" id="gr" name="grund" maxlength="300" required style="width:100%"></p>'
              + (f'<p><label><input type="checkbox" name="mit_verfahren" value="1"> Auch die {nv} zugehörige(n) Einbürgerungsakte(n) löschen</label></p>' if nv else "")
              + f'<p class="aktionen"><button class="btn gefahr" type="submit">{ic("trash-2")}Endgültig löschen</button>'
              f'<a class="btn zweit" href="{pfad}">Abbrechen</a></p></form>')
    return _ant(request, "Akte löschen", "buerger", inhalt)


async def buerger_loeschen(request):
    k, form = await _post(request)
    con, i = request.app["db"], request.match_info["id"]
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not z:
        raise web.HTTPNotFound()
    if z["verschluss"] and not darf_verschluss(k):
        raise web.HTTPForbidden(text="Diese Akte steht unter Verschluss.")
    pfad = f"{BASIS}buerger/{i}/loeschen/"
    grund = _text(form, "grund", 300)
    if str(form.get("bestaetigung", "")).strip().upper() != az_akte(z["id"]) or not grund:
        _umleiten(pfad, "Aktenzeichen oder Begründung fehlen bzw. stimmen nicht.", True)
    mit = bool(form.get("mit_verfahren"))
    nv = 0
    if mit:
        for v in con.execute("SELECT id FROM amt_verfahren WHERE konto_id=?", (z["konto_id"],)).fetchall():
            con.execute("DELETE FROM amt_eintraege WHERE ziel='verfahren' AND ziel_id=?", (v["id"],))
            nv += 1
        con.execute("DELETE FROM amt_verfahren WHERE konto_id=?", (z["konto_id"],))
    con.execute("DELETE FROM amt_eintraege WHERE ziel='akte' AND ziel_id=?", (z["id"],))
    con.execute("DELETE FROM amt_akten WHERE id=?", (z["id"],))
    con.execute("INSERT INTO amt_loeschungen (aktenzeichen, konto_id, name, ic_name, status, verfahren_geloescht, grund, zeit, autor_id, autor_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (az_akte(z["id"]), z["konto_id"], z["name"], z["ic_name"], z["status"], nv, grund, int(time.time()), k["id"], k["name"]))
    con.commit()
    log.info("Bürgerakte %s gelöscht von %s", az_akte(z["id"]), k["id"])
    _umleiten(BASIS + "buerger/", f"Akte {az_akte(z['id'])} gelöscht.")


@_beamter
async def protokoll(request):
    con = request.app["db"]
    zeilen = [(_zeit(r["zeit"]), esc(r["aktenzeichen"]), esc(r["ic_name"] or r["name"]), esc(r["konto_id"]), esc(STATUS_AKTE.get(r["status"], r["status"])),
               "ja" if r["verfahren_geloescht"] else "nein", esc(r["grund"]), esc(r["autor_name"]))
              for r in con.execute("SELECT * FROM amt_loeschungen ORDER BY id DESC LIMIT 500")]
    inhalt = (f'<h1>{ic("scroll-text")} Löschprotokoll</h1><p class="az">Gelöschte Bürgerakten</p>{meldung(request)}'
              + tabelle(["Zeit", "Aktenzeichen", "Name", "Discord-ID", "Status", "Einbürgerungsakten mitgelöscht", "Grund", "Bearbeiter"], zeilen, "Es wurden noch keine Akten gelöscht."))
    return _ant(request, "Löschprotokoll", "protokoll", inhalt)


# ---------------------------------------------------------------- PDF-Export

PDF_CSS = CSS + """
body{font-size:11pt}.kopf,nav{display:none}.rahmen{display:block;min-height:0}main{padding:0;max-width:none}
h2{break-after:avoid}table,tr{break-inside:avoid}.kennzahlen div{min-width:110px}
.pdf-kopf{border-bottom:2px solid #000;margin-bottom:14px;padding-bottom:6px}.pdf-kopf b{font-size:14pt}.pdf-kopf span{display:block;color:#444;font-size:9pt}
"""
_pdf_sperre = asyncio.Semaphore(1)


def _pdf_html(titel, inhalt, k):
    kopf = (f'<div class="pdf-kopf"><b>Reichsbehörden – {esc(logo_von(k)[1])}</b>'
            f'<span>Amtsseite · {esc(titel)} · Vertraulich, nur für den Dienstgebrauch</span></div>')
    fuss = f'<p class="az">Erstellt am {_zeit(int(time.time()))} von {esc(k["name"])}. Imperium Germanicum, imperiumgermanicum.de</p>'
    return (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{esc(titel)}</title><style>{PDF_CSS}</style></head>'
            f'<body><main>{kopf}{inhalt}{fuss}</main></body></html>')


async def _pdf_antwort(request, dateiname, titel, inhalt):
    from playwright.async_api import async_playwright
    import bild  # setzt PLAYWRIGHT_BROWSERS_PATH
    text = _pdf_html(titel, inhalt, request["konto"])
    async with _pdf_sperre:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                pg = await browser.new_page()
                await pg.set_content(text)
                pdf = await pg.pdf(format="A4", print_background=True, margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
            finally:
                await browser.close()
    return web.Response(body=pdf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{dateiname}.pdf"', "Cache-Control": "no-store"})


@_beamter
async def buerger_pdf(request):
    con, i = request.app["db"], request.match_info["id"]
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not z:
        raise web.HTTPNotFound(text="Akte nicht gefunden.")
    if z["verschluss"] and not darf_verschluss(request["konto"]):
        return _gesperrt_seite(request, "Bürgerakte", "buerger", az_akte(z["id"]))
    vs = [_verfahren_zeile(v) for v in con.execute("SELECT * FROM amt_verfahren WHERE konto_id=? ORDER BY id DESC", (z["konto_id"],))]
    inhalt = (f'<h1>Bürgerakte {az_akte(z["id"])}</h1><p class="az">{esc(z["ic_name"] or z["name"])}</p>'
              f'<h2>Stammdaten</h2>{_stamm(z)}'
              f'<h2>Einbürgerungsakten</h2>{tabelle(["Aktenzeichen", "Name", "Stand", "Zuletzt"], vs, "Kein Einreiseverfahren erfasst.")}'
              f'<h2>Vorgänge</h2>{eintraege_html(con, "akte", z["id"])}')
    return await _pdf_antwort(request, az_akte(z["id"]), f"Bürgerakte {az_akte(z['id'])}", inhalt)


@_beamter
async def verfahren_pdf(request):
    con, i = request.app["db"], request.match_info["id"]
    v = con.execute("SELECT * FROM amt_verfahren WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not v:
        raise web.HTTPNotFound(text="Akte nicht gefunden.")
    az = az_verfahren(v["id"], v["erstellt"])
    if konto_gesperrt(con, request["konto"], v["konto_id"]):
        return _gesperrt_seite(request, "Einbürgerungsakte", "verfahren", az)
    inhalt = (f'<h1>Einbürgerungsakte {az}</h1><p class="az">{esc(v["name"])}</p><h2>Akte</h2>{_verfahren_kopf(con, v)}'
              f'<h2>Phase I – außerhalb des Charakters</h2>{_felder(v["phase1"], PHASE1_FELDER)}'
              f'<h2>Phase II – im Charakter</h2>{_felder(v["phase2"], PHASE2_FELDER)}'
              f'<h2>Vorgänge</h2>{eintraege_html(con, "verfahren", v["id"])}')
    return await _pdf_antwort(request, az, f"Einbürgerungsakte {az}", inhalt)


@_beamter
async def statistik_pdf(request):
    inhalt = f'<h1>Statistiken</h1><p class="az">Stand {_zeit(int(time.time()))}</p>{statistik_inhalt(request.app["db"])}'
    return await _pdf_antwort(request, "statistik-" + datetime.now(BERLIN).strftime("%Y-%m-%d"), "Statistiken", inhalt)

# ---------------------------------------------------------------- Aktionen

def _umleiten(pfad, text, fehler=False):
    from urllib.parse import quote
    raise web.HTTPSeeOther(f"{pfad}?m={quote(text)}" + ("&f=1" if fehler else ""))


async def _post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + BASIS)
    if not ist_beamter(k):
        raise web.HTTPForbidden(text="Dafür fehlen dir die nötigen Rollen (Lesezugriff reicht für Änderungen nicht).")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    return k, form


def _text(form, feld, maximum):
    return " ".join(str(form.get(feld, "")).split())[:maximum]


async def buerger_bearbeiten(request):
    k, form = await _post(request)
    con, i = request.app["db"], request.match_info["id"]
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not z:
        raise web.HTTPNotFound()
    if z["verschluss"] and not darf_verschluss(k):
        raise web.HTTPForbidden(text="Diese Akte steht unter Verschluss.")
    neu = {"ic_name": _text(form, "ic_name", 80), "ic_geburt": _text(form, "ic_geburt", 40), "fraktion": _text(form, "fraktion", 80),
           "schicht": _text(form, "schicht", 40), "beruf": _text(form, "beruf", 40)}
    aenderungen = [f"{f}: „{z[f]}“ → „{w}“" for f, w in neu.items() if z[f] != w]
    pfad = f"{BASIS}buerger/{i}/"
    if not aenderungen:
        _umleiten(pfad, "Keine Änderung.")
    con.execute("UPDATE amt_akten SET ic_name=?, ic_geburt=?, fraktion=?, schicht=?, beruf=?, aktualisiert=? WHERE id=?",
                (*neu.values(), int(time.time()), i))
    eintrag(con, "akte", z["id"], "Stammdaten geändert", "\n".join(aenderungen), k["id"], k["name"])
    con.commit()
    _umleiten(pfad, "Stammdaten gespeichert.")


async def verschluss_setzen(request):
    k, form = await _post(request)
    if not darf_verschluss(k):
        raise web.HTTPForbidden(text="Nur der Kaiser und der Kanzler können Akten unter Verschluss setzen.")
    con, i = request.app["db"], request.match_info["id"]
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not z:
        raise web.HTTPNotFound()
    wert = 1 if form.get("wert") == "1" else 0
    con.execute("UPDATE amt_akten SET verschluss=?, aktualisiert=? WHERE id=?", (wert, int(time.time()), z["id"]))
    eintrag(con, "akte", z["id"], "Verschluss", "Unter Verschluss gesetzt." if wert else "Verschluss aufgehoben.", k["id"], k["name"])
    con.commit()
    _umleiten(f"{BASIS}buerger/{i}/", "Akte unter Verschluss gesetzt." if wert else "Verschluss aufgehoben.")


async def vermerk(request):
    k, form = await _post(request)
    con, i = request.app["db"], request.match_info["id"]
    ziel = "akte" if "/buerger/" in request.path else "verfahren"
    tabelle_ = "amt_akten" if ziel == "akte" else "amt_verfahren"
    pfad = f"{BASIS}{'buerger' if ziel == 'akte' else 'verfahren'}/{i}/"
    text = str(form.get("text", "")).strip()[:2000]
    zeile = con.execute(f"SELECT konto_id FROM {tabelle_} WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not zeile:
        raise web.HTTPNotFound()
    if konto_gesperrt(con, k, zeile["konto_id"]):
        raise web.HTTPForbidden(text="Diese Akte steht unter Verschluss.")
    if not text:
        _umleiten(pfad, "Der Vermerk ist leer.", True)
    eintrag(con, ziel, int(i), "Vermerk", text, k["id"], k["name"])
    con.commit()
    _umleiten(pfad, "Vermerk angefügt.")


async def verfahren_schliessen(request):
    k, form = await _post(request)
    con, i = request.app["db"], request.match_info["id"]
    v = con.execute("SELECT * FROM amt_verfahren WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not v:
        raise web.HTTPNotFound()
    if konto_gesperrt(con, k, v["konto_id"]):
        raise web.HTTPForbidden(text="Diese Akte steht unter Verschluss.")
    pfad = f"{BASIS}verfahren/{i}/"
    erg, grund = form.get("ergebnis"), _text(form, "grund", 300)
    if v["ergebnis"] != "offen" or erg not in ("abgelehnt", "geschlossen") or not grund:
        _umleiten(pfad, "Das Verfahren kann so nicht beendet werden (Begründung nötig).", True)
    jetzt = int(time.time())
    con.execute("UPDATE amt_verfahren SET ergebnis=?, abgeschlossen=?, aktualisiert=? WHERE id=?", (erg, jetzt, jetzt, i))
    eintrag(con, "verfahren", v["id"], "Verfahren beendet", f"{ERGEBNIS[erg]}. Begründung: {grund}", k["id"], k["name"])
    akte = con.execute("SELECT id FROM amt_akten WHERE konto_id=?", (v["konto_id"],)).fetchone()
    if akte:
        eintrag(con, "akte", akte["id"], "Einbürgerungsverfahren", f"{az_verfahren(v['id'], v['erstellt'])}: {ERGEBNIS[erg]}.", k["id"], k["name"])
    con.commit()
    _umleiten(pfad, "Verfahren beendet.")


# ---------------------------------------------------------------- Schnittstelle für den Bot

def _bot(request):
    if not secrets.compare_digest(request.headers.get("X-Bot-Token", ""), request.app["discord"].bot_token):
        raise web.HTTPForbidden()


def _offenes_verfahren(con, konto_id, thread_id=None):
    if thread_id:
        v = con.execute("SELECT * FROM amt_verfahren WHERE thread_id=?", (str(thread_id),)).fetchone()
        if v:
            return v
    return con.execute("SELECT * FROM amt_verfahren WHERE konto_id=? AND ergebnis='offen' ORDER BY id DESC", (konto_id,)).fetchone()


async def api_einreise(request):
    """Phase 1 = Antrag (OOC), 2 = Phase II eingeleitet, 3 = Phase II ausgefüllt."""
    _bot(request)
    d = await request.json()
    con, jetzt = request.app["db"], int(time.time())
    konto_id, name, thread, phase = str(d["konto_id"]), str(d.get("name", ""))[:80], str(d.get("thread_id") or "") or None, int(d["phase"])
    daten = {k: str(v)[:2000] for k, v in (d.get("daten") or {}).items()}
    akte = akte_sichern(con, konto_id, name, "einwanderer", "", "Akte angelegt (Einreiseantrag)")
    v = _offenes_verfahren(con, konto_id, thread)
    if phase == 1 or not v:
        if not (v and v["thread_id"] == thread):
            cur = con.execute("INSERT INTO amt_verfahren (konto_id, name, thread_id, phase, phase1, erstellt, aktualisiert) VALUES (?,?,?,?,?,?,?)",
                              (konto_id, name, thread, 1, json.dumps(daten if phase == 1 else {}, ensure_ascii=False), jetzt, jetzt))
            v = con.execute("SELECT * FROM amt_verfahren WHERE id=?", (cur.lastrowid,)).fetchone()
            eintrag(con, "verfahren", v["id"], "Antrag", "Einreiseantrag (Phase I, OOC) eingegangen." if phase == 1 else "Verfahren ohne erfassten Antrag (Phase I fehlt).", konto_id, name)
            eintrag(con, "akte", akte["id"], "Einreiseantrag", f"Einbürgerungsakte {az_verfahren(v['id'], jetzt)} eröffnet.", konto_id, name)
    if phase == 2:
        con.execute("UPDATE amt_verfahren SET phase=2, aktualisiert=? WHERE id=?", (jetzt, v["id"]))
        eintrag(con, "verfahren", v["id"], "Phase II eingeleitet", "Phase II (im Charakter) eingeleitet.", str(d.get("beamter_id") or ""), str(d.get("beamter_name") or ""))
    elif phase == 3:
        con.execute("UPDATE amt_verfahren SET phase=3, phase2=?, aktualisiert=? WHERE id=?", (json.dumps(daten, ensure_ascii=False), jetzt, v["id"]))
        eintrag(con, "verfahren", v["id"], "Phase II ausgefüllt", "Angaben im Charakter eingereicht.", konto_id, name)
        con.execute("UPDATE amt_akten SET ic_name=?, ic_geburt=?, fraktion=?, schicht=?, beruf=?, aktualisiert=? WHERE id=?",
                    (daten.get("name", ""), daten.get("geburtsdatum", ""), daten.get("fraktion", ""), daten.get("schicht", ""), daten.get("beruf", ""), jetzt, akte["id"]))
        eintrag(con, "akte", akte["id"], "Stammdaten", "Angaben aus Phase II übernommen.", konto_id, name)
    con.commit()
    return web.json_response({"ok": True, "verfahren": v["id"], "akte": akte["id"]})


async def api_einbuergerung(request):
    _bot(request)
    d = await request.json()
    con, jetzt = request.app["db"], int(time.time())
    konto_id, name, ic_name = str(d["konto_id"]), str(d.get("name", ""))[:80], str(d.get("ic_name", ""))[:80]
    bid, bname = str(d.get("beamter_id") or ""), str(d.get("beamter_name") or "")
    akte = akte_sichern(con, konto_id, name, "einwanderer", ic_name, "Akte angelegt (Einbürgerung)")
    v = _offenes_verfahren(con, konto_id, d.get("thread_id"))
    if not v:
        cur = con.execute("INSERT INTO amt_verfahren (konto_id, name, phase, phase1, erstellt, aktualisiert) VALUES (?,?,?,?,?,?)",
                          (konto_id, name, 1, "{}", jetzt, jetzt))
        v = con.execute("SELECT * FROM amt_verfahren WHERE id=?", (cur.lastrowid,)).fetchone()
        eintrag(con, "verfahren", v["id"], "Eröffnet", "Ohne Einreiseantrag im Ticketsystem (Direkteinbürgerung).", bid, bname)
    con.execute("UPDATE amt_verfahren SET ergebnis='eingebuergert', abgeschlossen=?, aktualisiert=? WHERE id=?", (jetzt, jetzt, v["id"]))
    eintrag(con, "verfahren", v["id"], "Eingebürgert", f"Einbürgerung als „{ic_name}“ vollzogen.", bid, bname)
    con.execute("UPDATE amt_akten SET status='staatsbuerger', ic_name=?, name=?, aktualisiert=? WHERE id=?", (ic_name or akte["ic_name"], name or akte["name"], jetzt, akte["id"]))
    eintrag(con, "akte", akte["id"], "Eingebürgert", f"Staatsbürgerschaft verliehen ({az_verfahren(v['id'], v['erstellt'])}).", bid, bname)
    con.commit()
    return web.json_response({"ok": True, "verfahren": v["id"], "akte": akte["id"]})


async def api_ticket_geschlossen(request):
    _bot(request)
    d = await request.json()
    con, jetzt = request.app["db"], int(time.time())
    v = con.execute("SELECT * FROM amt_verfahren WHERE thread_id=?", (str(d["thread_id"]),)).fetchone()
    if v and v["ergebnis"] == "offen":
        con.execute("UPDATE amt_verfahren SET ergebnis='geschlossen', abgeschlossen=?, aktualisiert=? WHERE id=?", (jetzt, jetzt, v["id"]))
        eintrag(con, "verfahren", v["id"], "Ticket geschlossen", "Ticket ohne Einbürgerung geschlossen.", str(d.get("beamter_id") or ""), str(d.get("beamter_name") or ""))
        con.commit()
    return web.json_response({"ok": True})


async def logo_datei(request):
    name = request.match_info["name"]
    schl = name[:-4] if name.endswith(".png") else ""
    erlaubt = {l[1] for l in LOGOS} | {"reichsbehoerden"}
    if schl.rsplit("-", 1)[0] not in erlaubt and schl not in erlaubt:
        raise web.HTTPNotFound()
    pfad = os.path.join(LOGO_ORDNER, name)
    if not os.path.isfile(pfad):
        raise web.HTTPNotFound()
    return web.FileResponse(pfad, headers={"Cache-Control": "public, max-age=3600"})


def registrieren(app):
    einrichten(app["db"])
    app.on_startup.append(_start)
    app.on_cleanup.append(_stop)
    app.router.add_get(BASIS, uebersicht)
    app.router.add_get(BASIS + "logo/{name}", logo_datei)
    app.router.add_get(BASIS + "buerger/", buerger_liste)
    app.router.add_get(BASIS + "buerger/{id}/", buerger_akte)
    app.router.add_get(BASIS + "verfahren/", verfahren_liste)
    app.router.add_get(BASIS + "verfahren/{id}/", verfahren_akte)
    app.router.add_get(BASIS + "statistik/", statistik)
    app.router.add_get(BASIS + "statistik/pdf", statistik_pdf)
    app.router.add_get(BASIS + "protokoll/", protokoll)
    app.router.add_get(BASIS + "buerger/{id}/pdf", buerger_pdf)
    app.router.add_get(BASIS + "buerger/{id}/loeschen/", buerger_loeschen_seite)
    app.router.add_post(BASIS + "buerger/{id}/loeschen", buerger_loeschen)
    app.router.add_get(BASIS + "verfahren/{id}/pdf", verfahren_pdf)
    app.router.add_post(BASIS + "buerger/{id}/bearbeiten", buerger_bearbeiten)
    app.router.add_post(BASIS + "buerger/{id}/vermerk", vermerk)
    app.router.add_post(BASIS + "buerger/{id}/verschluss", verschluss_setzen)
    app.router.add_post(BASIS + "verfahren/{id}/vermerk", vermerk)
    app.router.add_post(BASIS + "verfahren/{id}/schliessen", verfahren_schliessen)
    app.router.add_post("/intern-api/amt/einreise", api_einreise)
    app.router.add_post("/intern-api/amt/einbuergerung", api_einbuergerung)
    app.router.add_post("/intern-api/amt/ticket-geschlossen", api_ticket_geschlossen)
