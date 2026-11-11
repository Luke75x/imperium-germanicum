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
die der Bot (Modul ticket.py / zollamt.py) befüllt. Zugang: Kaiserliche Zollverwaltung, Kanzler (Admins nicht).
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
# Reichsbehörden mit eigenem Untertab („Bereich“) und Logo. Wer eine der Rollen hat, gehört zur Behörde, sieht ihren Untertab
# und bekommt ihr Logo (Reihenfolge = Vorrang). Kanzler und Kaiser sehen alle Bereiche. Logo-Texte: amt_logos_liste.py,
# Bilder: werkzeuge/amt_logos.py. leitung = Rollen, die als Leitung der Behörde gelten (dürfen Mitteilungen anderer löschen).
BEHOERDEN = [
    {"schl": "polizei", "name": "Kaiserliche Polizeibehörde", "kurz": "Polizei", "icon": "siren", "domain": "polizei",
     "rollen": [ROLLE_POLIZEI, "1557335971966750780"], "leitung": ["1557335971966750780"]},
    {"schl": "zoll", "name": "Kaiserliche Zollverwaltung", "kurz": "Zoll", "icon": "stamp", "domain": "zoll",
     "rollen": [ROLLE_ZOLL, "1557188989729906708"], "leitung": ["1557188989729906708"]},
    {"schl": "katastrophenschutz", "name": "Kaiserlicher Katastrophenschutz", "kurz": "Katastrophenschutz", "icon": "life-buoy",
     "domain": "katastrophenschutz", "rollen": [ROLLE_KATASTROPHENSCHUTZ], "leitung": []},
    {"schl": "krs", "name": "Kaiserliches Reichssicherheitsamt", "kurz": "KRS", "icon": "shield-check", "domain": "krs",
     "rollen": ["1526343577481904379", "1522913765035606086"], "leitung": ["1522913765035606086"]},
    {"schl": "inquisition", "name": "Die Inquisition (Staatsanwaltschaft)", "kurz": "Inquisition", "icon": "scale", "domain": "inquisition",
     "rollen": ["1522700028739584000", "1555987375287574609"], "leitung": ["1522700028739584000"]},
    # Zentralbank und Finanzverwaltung (schatzamt.py). Discord-Rollen folgen noch – bis dahin verwalten Kanzler/Kaiser (Admins OOC).
    {"schl": "schatzamt", "name": "Kaiserliches Schatz- und Währungsamt", "kurz": "Schatzamt", "icon": "landmark", "domain": "schatzamt",
     "rollen": [], "leitung": []},
]
LOGOS = [(ROLLE_KANZLER, "kanzler", "Der Kanzler")] + [(r, b["schl"], b["name"]) for b in BEHOERDEN for r in b["rollen"]]
LOGO_ORDNER = os.path.join(config.HIER, "amt_logos")
ROLLE_STAATSBUERGER = "1522929940885143683"
# Zugang: Rollen oder Nutzer-IDs (Kaiser, Rolle 1526348059984789504, Hand des Kaisers 1522693216053235903); Server-Admins nicht
# Kategorie „Akten“ (Bürger-/Einbürgerungsakten, Statistik, Löschprotokoll): NUR Rolle „Reichsverwaltung“ (Trenner 1561686761778716762),
# aber nie zusammen mit einer Amtsrolle der Teilstaaten (Bürgermeister, Magistrat, Gouverneur, Generalgouverneur, Vizekönig).
# Daneben sehen Kaiser und Kanzler wie überall alles. Server-Admins, Zoll-Rolle u. a. allein reichen nicht.
ROLLE_AKTEN = "1561686761778716762"
ROLLEN_AKTEN_NIE = {"1525948431267532860", "1555971841888223242", "1525947612639793253", "1525947448776986665", "1525947356049309788"}
ZUGANG_IDS = {config.KAISER_ID}
ROLLEN_ZUGANG = {ROLLE_KANZLER}
SEITE_GROESSE = 50

STATUS_AKTE = {"staatsbuerger": "Staatsbürger", "einwanderer": "Einwanderer", "nicht_mehr": "Nicht mehr Staatsbürger"}
ERGEBNIS = {"offen": "Offen", "eingebuergert": "Eingebürgert", "abgelehnt": "Abgelehnt", "geschlossen": "Ohne Einbürgerung geschlossen"}
PHASE = {1: "Phase I (OOC) – Prüfung", 2: "Phase II eingeleitet – wartet auf Antragsteller", 3: "Phase II ausgefüllt – Entscheidung offen"}
SCHICHTEN = ["Bürgerstand", "Adelsstand", "Klerus", "Bauernstand", "Sonstiges"]
BERUFE = ["Militärischer Natur", "Beamter", "Sonstiges"]
GESCHLECHTER = ["Männlich", "Weiblich", "Divers"]
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
    if "position" not in spalten:
        con.execute("ALTER TABLE amt_akten ADD COLUMN position TEXT NOT NULL DEFAULT ''")
    if "geschlecht" not in spalten:
        con.execute("ALTER TABLE amt_akten ADD COLUMN geschlecht TEXT NOT NULL DEFAULT ''")
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


def ist_ooc_admin(k):
    """Serveradministrator (Discord-Berechtigung „Administrator“) ohne Kaiser-/Kanzleramt: darf alles wie Kaiser und Kanzler,
    aber ausdrücklich nur OOC – jede Seite der Amtsseite zeigt dann den OOC-Hinweis."""
    return bool(k) and bool(k["admin"]) and bool(k["mitglied"]) and not (k["id"] == config.KAISER_ID or ROLLE_KANZLER in k["rollen"])


def ist_beamter(k):
    if not k:
        return False
    rollen = set(k["rollen"])
    if k["id"] in ZUGANG_IDS or ROLLEN_ZUGANG & rollen or ist_ooc_admin(k):
        return True
    return ROLLE_AKTEN in rollen and not (ROLLEN_AKTEN_NIE & rollen)


# Nur Lesezugriff (kein Schreibrecht). Leer: Unterbehörden (KRS, Polizei, Inquisition …) sehen keine Bürger-/Einbürgerungsakten.
LESE_IDS = set()


def ist_leser(k):
    """Darf die Amtsseite ansehen (Beamte mit Schreibrecht und die Leseberechtigten)."""
    return ist_beamter(k) or (bool(k) and bool(LESE_IDS & ({k["id"]} | set(k["rollen"]))))


def darf_verschluss(k):
    """Kaiser und Kanzler (und OOC die Serveradministratoren): Akten unter Verschluss setzen und solche Akten einsehen."""
    return bool(k) and (k["id"] == config.KAISER_ID or ROLLE_KANZLER in k["rollen"] or ist_ooc_admin(k))


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
:root{--ink:#16171a;--grau:#6b6f76;--linie:#e3e4e8;--hell:#f5f6f8;--flaeche:#f5f6f8;--kopf:#1f2f45;--akzent:#1f4e8c;--warn:#8a5a00;--ok:#1d6b34;--rot:#9b1c1c;
 --r:10px;--seite:252px;--tab:64px;--schrift:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
*{box-sizing:border-box}
html{font-size:16px;-webkit-text-size-adjust:100%}
body{margin:0;font:15px/1.55 var(--schrift);color:var(--ink);background:#fff;-webkit-font-smoothing:antialiased}
a{color:var(--akzent)}
.icon{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;vertical-align:-3px;flex:none}

/* ---- Grundgerüst: Seitenleiste links, Inhalt rechts ---- */
.app{display:flex;min-height:100vh}
.seite{width:var(--seite);flex:none;position:sticky;top:0;height:100vh;overflow-y:auto;display:flex;flex-direction:column;
 background:#fff;border-right:1px solid var(--linie);padding:18px 12px 14px;scrollbar-width:thin}
.seite .logo{display:block;line-height:0;padding:2px 8px 14px}
.seite .logo img{width:100%;height:auto;max-height:56px;object-fit:contain;object-position:left center}
.gruppe{margin:6px 0 10px}
.gruppe-titel{margin:0;padding:8px 10px 4px;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#9a9da4}
.seite a.ein{position:relative;display:flex;align-items:center;gap:12px;padding:8px 10px;margin:1px 0;border-radius:8px;color:#33363c;text-decoration:none;font-size:14.5px}
.seite a.ein:hover{background:var(--hell);color:var(--ink)}
.seite a.ein.aktiv{background:#eef2f8;color:var(--akzent);font-weight:600}
.seite a.ein.aktiv .icon{color:var(--akzent)}
.seite a.ein .icon{color:#7c8088}
.seite a.ein span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.zahl{margin-left:auto;background:var(--rot);color:#fff;font:600 11px/18px var(--schrift);min-width:18px;padding:0 5px;border-radius:9px;text-align:center;font-style:normal}
.seite .fuss{margin-top:auto;padding-top:12px;border-top:1px solid var(--linie)}
.seite .fuss a.ein{font-size:13.5px;color:var(--grau)}
.konto-box{display:flex;align-items:center;gap:10px;padding:10px 6px 2px 10px}
.avatar{width:34px;height:34px;border-radius:50%;background:var(--kopf);color:#fff;display:grid;place-items:center;font:600 13px/1 var(--schrift);flex:none;letter-spacing:.02em}
.konto-text{min-width:0;flex:1;line-height:1.25}
.konto-text b{display:block;font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.konto-text small{display:block;font-size:12px;color:var(--grau);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.konto-box form{margin:0}
.knopf-rund{all:unset;box-sizing:border-box;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;color:var(--grau);cursor:pointer}
.knopf-rund:hover,.knopf-rund:focus-visible{background:var(--hell);color:var(--ink)}
.knopf-rund:focus-visible{outline:2px solid var(--akzent);outline-offset:1px}
.blatt-kopf{display:none}

.spalte{flex:1;min-width:0;display:flex;flex-direction:column}
.kopf{position:sticky;top:0;z-index:15;display:flex;align-items:center;gap:10px;padding:12px 28px;min-height:64px;
 background:rgba(255,255,255,.88);-webkit-backdrop-filter:saturate(1.6) blur(12px);backdrop-filter:saturate(1.6) blur(12px);border-bottom:1px solid var(--linie)}
.kopf .logo{display:none;line-height:0}
.kopf .logo img{height:36px;width:auto}
.kopf .raum{flex:1}
.kopf form.suche{margin:0;display:flex;align-items:center;position:relative}
.kopf form.suche .icon{position:absolute;left:11px;color:#8b8f96;pointer-events:none}
.kopf input[type=search]{border:1px solid var(--linie);background:var(--hell);color:var(--ink);padding:8px 12px 8px 36px;font:inherit;font-size:14px;width:300px;border-radius:999px;transition:border-color .15s,background .15s,box-shadow .15s}
.kopf input[type=search]:focus{outline:0;background:#fff;border-color:#b9c3d3;box-shadow:0 0 0 3px rgba(31,78,140,.12)}
.kopf .knopf-rund.such-auf{display:none}
main{flex:1;width:100%;max-width:1120px;padding:28px 32px 64px;animation:rein .28s ease both}
@keyframes rein{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.tableiste,.schleier{display:none}

/* ---- Inhalt ---- */
.reiter{display:flex;flex-wrap:wrap;gap:4px 18px;margin:0 0 16px;border-bottom:1px solid var(--linie)}
*{scrollbar-width:thin;scrollbar-color:#c3c9d2 transparent}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#c3c9d2;border-radius:999px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background:#9aa3b0;background-clip:content-box}
::-webkit-scrollbar-button,::-webkit-scrollbar-corner{display:none;width:0;height:0}
.reiter a{padding:8px 2px;color:var(--grau);text-decoration:none;border-bottom:2px solid transparent;margin-bottom:-1px}
.reiter a.aktiv{color:var(--ink);border-bottom-color:var(--ink);font-weight:600}
h1{font-size:24px;line-height:1.25;margin:0 0 4px;font-weight:650;letter-spacing:-.01em;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
h1 .icon{width:22px;height:22px;color:var(--grau)}
h2{font-size:17px;margin:32px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--ink)}
.az{color:var(--grau);margin:0 0 16px;font-size:14px}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border:1px solid var(--linie);padding:8px 10px;text-align:left;vertical-align:top}
th{background:var(--hell);font-weight:600;white-space:nowrap}
table.daten th{width:240px}
td.text{white-space:pre-wrap;word-break:break-word}
.status{display:inline-flex;align-items:center;gap:4px;border:1px solid currentColor;padding:0 8px;font-size:13px;white-space:nowrap;border-radius:999px}
.status .icon{width:13px;height:13px}
.s-offen{color:var(--warn)}.s-ok{color:var(--ok)}.s-nein{color:var(--rot)}.s-neutral{color:var(--grau)}
form.zeile{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin:10px 0}
label{display:block;font-size:13px;color:var(--grau);margin-bottom:3px}
input[type=text],input[type=search],input[type=number],input[type=date],input[type=file],input[type=password],select,textarea{font:inherit;padding:8px 10px;border:1px solid #c9ccd2;border-radius:8px;background:#fff;color:var(--ink);max-width:100%}
input:focus,select:focus,textarea:focus{outline:0;border-color:#8aa3c7;box-shadow:0 0 0 3px rgba(31,78,140,.12)}
textarea{width:100%;min-height:90px}
.btn,button.btn{font:inherit;font-size:14.5px;font-weight:500;border:1px solid var(--kopf);background:var(--kopf);color:#fff;padding:8px 15px;cursor:pointer;text-decoration:none;display:inline-flex;gap:7px;align-items:center;border-radius:8px;transition:filter .15s,background .15s}
.btn:hover{filter:brightness(1.12)}
.btn.zweit{background:#fff;color:var(--kopf);border-color:#c9ccd2}
.btn.zweit:hover{background:var(--hell);filter:none}
.btn.gefahr{background:#fff;color:var(--rot);border-color:#e3c3c3}
.btn.arbeitet{pointer-events:none;opacity:.75}
.btn.arbeitet .icon{display:none}
.btn.arbeitet::before{content:"";width:14px;height:14px;border-radius:50%;border:2px solid currentColor;border-right-color:transparent;animation:dreh .7s linear infinite}
@keyframes dreh{to{transform:rotate(360deg)}}
.hinweis{border:1px solid var(--linie);border-left:4px solid var(--akzent);background:var(--hell);padding:10px 14px;margin:12px 0;border-radius:8px}
.hinweis.fehler{border-left-color:var(--rot)}
.kennzahlen{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:12px 0}
.kennzahlen div{border:1px solid var(--linie);border-radius:var(--r);padding:12px 16px;color:var(--grau);font-size:13.5px}
.kennzahlen b{display:block;font-size:26px;font-weight:600;color:var(--ink);line-height:1.2}
.leer{color:var(--grau);padding:8px 0}
.seiten{display:flex;gap:12px;margin:10px 0}
.balken{display:block;height:10px;background:var(--kopf);min-width:1px;border-radius:5px}
td.bar{width:45%}
.aktionen{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0}
.ooc-hinweis{display:flex;gap:10px;align-items:baseline;border:1px dashed currentColor;border-radius:8px;padding:8px 12px;margin:0 0 14px;font-size:13px}
.ooc-hinweis b{font-size:11px;letter-spacing:.12em;border:1px solid currentColor;border-radius:4px;padding:1px 6px;flex:none}
.warnung{border:1px solid var(--rot);border-left:4px solid var(--rot);padding:10px 14px;margin:12px 0;border-radius:8px}

/* ---- Bearbeitungsformulare ---- */
.zurueck{margin:0 0 10px;font-size:14px}
.zurueck a{color:var(--grau);text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.zurueck a:hover{color:var(--ink)}
.zurueck .icon{width:16px;height:16px}
.formular{max-width:760px}
.formular fieldset{border:1px solid var(--linie);border-radius:var(--r);padding:18px 20px 20px;margin:18px 0}
.formular legend{padding:0 6px;margin-left:-6px;font-weight:600;font-size:15px}
.felder{display:grid;grid-template-columns:1fr 1fr;gap:16px 18px}
.feld.breit{grid-column:1/-1}
.feld input,.feld select{width:100%}
.feld small{display:block;color:var(--grau);font-size:12.5px;margin-top:4px}
.formular-fuss{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}
@media (max-width:800px){
 .formular fieldset{padding:14px 14px 16px}
 .felder{grid-template-columns:1fr}
 .feld input,.feld select{font-size:16px}
 .formular-fuss{position:sticky;bottom:calc(var(--tab) + env(safe-area-inset-bottom));background:rgba(255,255,255,.94);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  margin:18px -16px 0;padding:10px 16px;border-top:1px solid var(--linie)}
 .formular-fuss .btn{flex:1;justify-content:center}
}
html.min .formular fieldset{border-color:#eceef0}

/* ---- Verlauf (Vorgänge / Protokoll) als Zeitleiste ---- */
.verlauf{list-style:none;margin:12px 0;padding:0}
.verlauf>li{position:relative;padding:0 0 20px 46px;break-inside:avoid}
.verlauf>li::before{content:"";position:absolute;left:16px;top:36px;bottom:4px;width:2px;border-radius:1px;background:var(--linie)}
.verlauf>li:last-child{padding-bottom:4px}
.verlauf>li:last-child::before{display:none}
.v-ic{position:absolute;left:0;top:0;width:34px;height:34px;border-radius:50%;background:var(--hell);border:1px solid var(--linie);display:grid;place-items:center;color:#5f636b}
.v-ic .icon{width:16px;height:16px}
.v-ic.t-ok{background:#eaf4ed;border-color:#cfe5d6;color:var(--ok)}
.v-ic.t-warn{background:#fbf3e6;border-color:#f0dfc0;color:var(--warn)}
.v-ic.t-rot{background:#fbeeee;border-color:#efd2d2;color:var(--rot)}
.v-ic.t-blau{background:#eef2f8;border-color:#d6e0ee;color:var(--akzent)}
.v-kopf{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 10px;padding-top:6px}
.v-art{font-weight:600}
.v-meta{color:var(--grau);font-size:13px}
.v-text{margin-top:4px;white-space:pre-wrap;word-break:break-word;color:#2a2c31}
.v-text.notiz{background:var(--hell);border-radius:8px;padding:10px 12px;margin-top:8px}
.aend{margin:8px 0 0;display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:0;border:1px solid var(--linie);border-radius:8px;overflow:hidden;font-size:14px}
.aend dt,.aend dd{margin:0;padding:7px 12px;border-top:1px solid var(--linie)}
.aend dt:first-of-type,.aend dt:first-of-type+dd{border-top:0}
.aend dt{color:var(--grau);background:var(--hell)}
.aend dd{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;word-break:break-word}
.aend .alt{color:var(--grau);text-decoration:line-through;text-decoration-color:#b5b8be}
.aend .neu{font-weight:600}
.aend .pfeil{color:#a3a7ae;width:14px;height:14px}
.leerwert{color:#9a9da4;font-style:italic;font-weight:400}
.v-link{font-size:13px}

/* ---- Skeleton beim Laden ---- */
.sk{display:block;border-radius:6px;background:linear-gradient(90deg,#eceef1 0,#f6f7f9 40%,#eceef1 80%);background-size:300% 100%;animation:schimmer 1.3s ease-in-out infinite}
@keyframes schimmer{from{background-position:100% 0}to{background-position:0 0}}
.skelett{display:none}
body.laedt main>*:not(.skelett){display:none}
body.laedt main>.skelett{display:block;animation:rein .2s ease both}
.sk-h1{height:28px;width:min(340px,70%);margin:2px 0 12px}
.sk-az{height:14px;width:min(200px,45%);margin-bottom:26px}
.sk-kz{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:30px}
.sk-kz .sk{height:76px;border-radius:var(--r)}
.sk-h2{height:16px;width:160px;margin:26px 0 14px}
.sk-zeile{display:flex;gap:16px;align-items:center;padding:13px 0;border-bottom:1px solid #f0f1f3}
.sk-zeile .sk{height:13px}
.sk-dt{display:grid;grid-template-columns:200px 1fr;gap:14px 20px;margin-bottom:8px}
.sk-dt .sk{height:13px}
.ladebalken{position:fixed;top:0;left:0;right:0;height:2px;z-index:60;overflow:hidden;opacity:0;transition:opacity .2s;pointer-events:none}
.ladebalken::before{content:"";position:absolute;top:0;bottom:0;width:40%;background:var(--akzent);animation:balken 1s ease-in-out infinite}
body.laedt .ladebalken{opacity:1}
@keyframes balken{from{left:-40%}to{left:100%}}
@media (prefers-reduced-motion:reduce){*,*::before{animation-duration:.01ms!important;animation-iteration-count:1!important;transition:none!important}}

@media print{.seite,.kopf,.tableiste,.aktionen,form,.ladebalken{display:none}.app{display:block}main{animation:none}}

/* ---- Handy und schmale Fenster: Kopfleiste oben, Tab-Leiste unten, Menü als Blatt ---- */
@media (max-width:800px){
 body{padding-bottom:calc(var(--tab) + env(safe-area-inset-bottom))}
 .app{display:block;min-height:0}
 .kopf{padding:8px 8px 8px 14px;min-height:56px;padding-top:calc(8px + env(safe-area-inset-top))}
 .kopf .logo{display:block}
 .kopf form.suche{display:none}
 .kopf .knopf-rund.such-auf{display:grid;width:42px;height:42px}
 .kopf.suche-offen form.suche{display:flex;position:absolute;left:8px;right:8px;top:calc(100% + 0px);padding:8px 6px 10px;background:#fff;border-bottom:1px solid var(--linie)}
 .kopf.suche-offen form.suche .icon{left:19px}
 .kopf.suche-offen input[type=search]{width:100%;font-size:16px}
 main{padding:18px 16px 32px}
 h1{font-size:21px}
 .seite{position:fixed;left:0;right:0;bottom:0;top:auto;width:auto;height:auto;max-height:82vh;z-index:40;border:0;border-radius:18px 18px 0 0;
  box-shadow:0 -10px 40px rgba(0,0,0,.18);padding:6px 14px calc(14px + env(safe-area-inset-bottom));transform:translateY(105%);visibility:hidden;
  transition:transform .28s cubic-bezier(.2,.8,.2,1),visibility 0s linear .28s;overscroll-behavior:contain}
 body.menue-offen .seite{transform:none;visibility:visible;transition:transform .28s cubic-bezier(.2,.8,.2,1)}
 .seite .logo{display:none}
 .blatt-kopf{display:flex;align-items:center;justify-content:space-between;padding:4px 4px 2px 10px;position:sticky;top:-6px;background:#fff;z-index:1}
 .blatt-kopf::before{content:"";position:absolute;top:2px;left:50%;width:38px;height:4px;margin-left:-19px;border-radius:2px;background:#d6d8dc}
 .blatt-kopf b{font-size:17px;padding-top:12px}
 .seite .gruppen{display:grid;grid-template-columns:1fr 1fr;gap:0 10px}
 .seite .gruppe{margin:4px 0}
 .seite a.ein{padding:11px 10px;font-size:15px}
 .schleier{display:block;position:fixed;inset:0;z-index:35;background:rgba(15,17,21,.38);opacity:0;visibility:hidden;transition:opacity .25s,visibility 0s linear .25s}
 body.menue-offen .schleier{opacity:1;visibility:visible;transition:opacity .25s}
 body.menue-offen{overflow:hidden}
 .tableiste{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:30;height:calc(var(--tab) + env(safe-area-inset-bottom));padding:0 4px env(safe-area-inset-bottom);
  background:rgba(255,255,255,.94);-webkit-backdrop-filter:saturate(1.6) blur(14px);backdrop-filter:saturate(1.6) blur(14px);border-top:1px solid var(--linie)}
 .tableiste a,.tableiste button{all:unset;box-sizing:border-box;flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;
  color:#80848c;font:500 11px/1.1 var(--schrift);cursor:pointer;position:relative;-webkit-tap-highlight-color:transparent}
 .tableiste span{max-width:100%;padding:0 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .tableiste .icon{width:22px;height:22px;transition:transform .15s}
 .tableiste .aktiv{color:var(--akzent)}
 .tableiste .aktiv .icon{stroke-width:2.3}
 .tableiste a:active .icon,.tableiste button:active .icon{transform:scale(.9)}
 .tableiste .zahl{position:absolute;top:7px;left:50%;margin-left:6px;font-size:10px;line-height:16px;min-width:16px;padding:0 4px}
 table.daten th{width:auto;white-space:normal}
 table.liste,table.liste tbody,table.liste tr,table.liste td{display:block;width:100%}
 table.liste thead{display:none}
 table.liste tr{border:1px solid var(--linie);border-radius:var(--r);margin-bottom:10px;overflow:hidden}
 table.liste td{border:0;border-bottom:1px solid #eef0f2}
 table.liste td:last-child{border-bottom:0}
 table.liste td::before{content:attr(data-l);display:block;color:var(--grau);font-size:12px}
 .aend{grid-template-columns:1fr}
 .aend dt{padding-bottom:2px;background:none;font-size:12.5px}
 .aend dd{border-top:0;padding-top:0}
 .aend dt:not(:first-of-type){border-top:1px solid var(--linie);padding-top:9px}
 .verlauf>li{padding-left:42px}
 .kennzahlen{grid-template-columns:repeat(2,1fr)}
 .sk-dt{grid-template-columns:110px 1fr}
 form.zeile>div{flex:1 1 100%}
 form.zeile>div select,form.zeile>div input{width:100%}
}
/* Bürgerakten-Liste am Handy: eine kompakte, ganz antippbare Zeile je Akte */
.nur-klein{display:none}
@media (max-width:800px){
 .nur-gross{display:none}.nur-klein{display:inline}
 form.filter{flex-wrap:nowrap;gap:8px;align-items:flex-end}
 form.filter>div{flex:1 1 auto;min-width:0}
 form.filter>div.f-suche{flex:1 1 60%}
 form.filter label{font-size:12px}
 form.filter .btn{flex:none;padding:8px 12px;height:42px}
 table.liste.akten tr{position:relative;display:flex;flex-wrap:wrap;align-items:center;gap:1px 8px;padding:9px 28px 9px 0;margin:0;line-height:1.35;
  border:0;border-bottom:1px solid #eef0f2;border-radius:0}
 table.liste.akten tr::after{content:"";order:2;flex-basis:100%;height:0}
 table.liste.akten tr::before{content:"";position:absolute;right:6px;top:50%;width:7px;height:7px;margin-top:-4px;border:solid #b5b8be;border-width:2px 2px 0 0;transform:rotate(45deg)}
 table.liste.akten td{display:block;width:auto;border:0;padding:0;font-size:13px;color:var(--grau);min-width:0}
 table.liste.akten td::before{display:none}
 table.liste.akten td:nth-child(2){order:0;flex:1 1 0;font-size:15.5px;font-weight:600;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 table.liste.akten td:nth-child(2) .leerwert{font-size:12.5px}
 table.liste.akten td:nth-child(5){order:1;flex:none;font-size:12px}
 table.liste.akten td:nth-child(1){order:3}
 table.liste.akten td:nth-child(3){order:4;max-width:45%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 table.liste.akten td:nth-child(4){order:5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%}
 table.liste.akten td:nth-child(3)::before,table.liste.akten td:nth-child(4)::before{content:"· ";display:inline;font-size:inherit;color:#b5b8be}
 table.liste.akten td:nth-child(1) a{color:var(--grau);text-decoration:none;font-variant-numeric:tabular-nums}
 table.liste.akten td:nth-child(1) a::after{content:"";position:absolute;inset:0}
 table.liste.akten tr:active{background:var(--hell)}
 table.liste.akten tr:has(td:nth-child(2) .nur-klein) td:nth-child(3),table.liste.akten tr:has(.leer-f) td:nth-child(4){display:none}
 table.liste.akten td:nth-child(5) .status{padding:1px 8px;font-size:11.5px}
 table.liste.akten td:nth-child(5) .s-ok{display:none}
 form.filter>div:not(.f-suche){flex:0 0 34%}
 form.filter input,form.filter select{height:42px;padding-top:0;padding-bottom:0}
 form.filter label{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
 html.min table.liste.akten tr{padding:9px 28px 9px 0}
}
@media (max-width:380px){.seite .gruppen{grid-template-columns:1fr}}

/* ---- Design-Modus „Minimalistisch“ (html.min, Standard): ruhiger, flacher ---- */
html.min body{color:#1d1f23}
html.min .seite{background:#fafafa;border-right-color:#eceef0}
html.min .seite a.ein.aktiv{background:#fff;color:#111;box-shadow:0 1px 2px rgba(0,0,0,.06),0 0 0 1px #eceef0}
html.min .seite a.ein.aktiv .icon{color:#111}
html.min .avatar{background:#111}
html.min .kopf{border-bottom-color:transparent}
html.min main{max-width:1040px}
html.min h1{font-size:24px;font-weight:650}
html.min h1 .icon{display:none}
html.min h2{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#8b8f96;border:0;margin:36px 0 10px;padding:0}
html.min .az{color:#8b8f96}
html.min th,html.min td{border:0;border-bottom:1px solid #eef0f2;padding:10px 12px 10px 0}
html.min th{background:transparent;color:#8b8f96;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
html.min table.daten th{text-transform:none;font-size:14px;letter-spacing:0;font-weight:400}
html.min .status{border:0;background:#f1f2f4;padding:2px 10px;font-size:12.5px}
html.min .s-ok.status{background:#eaf4ed}html.min .s-offen.status{background:#fbf3e6}html.min .s-nein.status{background:#fbeeee}
html.min .kennzahlen div{border:0;background:#f7f8f9}
html.min .kennzahlen b{font-size:28px;font-weight:550}
html.min .btn,html.min button.btn{background:#111;border-color:#111}
html.min .btn.zweit{background:#fff;color:#111;border-color:#dcdee2}
html.min .btn.zweit:hover{background:#f6f7f8}
html.min .btn.gefahr{background:#fff;color:var(--rot);border-color:#ecd0d0}
html.min input[type=text],html.min input[type=search],html.min input[type=password],html.min select,html.min textarea{border-color:#dcdee2}
html.min .hinweis{border:0;background:#f5f6f8}
html.min .warnung{border:0;background:#fbf1f1}
html.min .balken{background:#111}
html.min .reiter a.aktiv{border-bottom-color:#111}
html.min .seite a.ein .zahl,html.min .tableiste .zahl{background:var(--rot)}
html.min .tableiste .aktiv{color:#111}
html.min .v-ic.t-blau{background:#f1f2f4;border-color:#e3e4e8;color:#111}
@media (max-width:800px){
 html.min .seite{background:#fff}
 html.min .kopf{border-bottom-color:#eef0f2}
 html.min table.liste tr{border:0;border-bottom:1px solid #eef0f2;border-radius:0;margin:0;padding:8px 0}
 html.min table.liste td{border:0;padding:3px 0}
}
.nur-min{display:none}
html.min .nur-min{display:inline}html.min .nur-std{display:none}
"""


ICONS["panel-left"] = '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>'
ICONS["menu"] = '<line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/>'
ICONS["layout-grid"] = ('<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/>'
                        '<rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>')
ICONS["flag"] = '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>'
ICONS["file-plus"] = ('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
                      '<path d="M9 15h6"/><path d="M12 18v-6"/>')
ICONS["arrow-right"] = '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>'
ICONS["paperclip"] = ('<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>')


def ic(name):
    return f'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'


NAV = [("uebersicht", "layout-dashboard", "Übersicht", ""), ("buerger", "book-user", "Bürgerakten", "buerger/"),
       ("verfahren", "folder-open", "Einbürgerungsakten", "verfahren/"), ("statistik", "chart-column", "Statistiken", "statistik/"),
       ("protokoll", "scroll-text", "Löschprotokoll", "protokoll/")]


NAV_EXTRA = []    # [(Gruppentitel, fn(konto) -> [(schl, icon, text, pfad)])], von anderen Modulen gefüllt
AKTE_ZUSATZ = []  # [fn(request, con, akte, schreiben) -> HTML], unter den Stammdaten der Bürgerakte

NAV_ALLE = [("post", "mail", "Postfach", "postfach/"), ("einstellungen", "sliders-horizontal", "Einstellungen", "einstellungen/")]

# Kurze Beschriftungen für die Tab-Leiste am Handy
TAB_KURZ = {"uebersicht": "Übersicht", "buerger": "Bürger", "verfahren": "Verfahren", "post": "Postfach", "einstellungen": "Einstellungen"}


def nav_gruppen(k):
    """Navigation in sinnvollen Gruppen: [(Titel, [(schl, icon, text, pfad)])]."""
    import bereiche
    leser = ist_leser(k)
    gruppen = []
    if leser:
        gruppen.append(("Akten", list(NAV[:3])))
    behoerden = [("b-" + b["schl"], b["icon"], b["kurz"], "bereich/" + b["schl"] + "/") for b in bereiche.sichtbar(k)]
    if behoerden:
        gruppen.append(("Behörden", behoerden))
    if leser:
        gruppen.append(("Auswertung", NAV[3:]))
    for titel, fn in NAV_EXTRA:   # weitere Module (Amtshilfe, Meldewesen …): Einträge in bestehende oder neue Gruppe
        es = fn(k)
        if not es:
            continue
        g = next((g for g in gruppen if g[0] == titel), None)
        if g:
            g[1].extend(es)
        else:
            gruppen.append((titel, es))
    gruppen = [(t, list(es)) for t, es in gruppen]
    pers = next((g for g in gruppen if g[0] == "Persönlich"), None)   # Module können „Persönlich“ ergänzen (z. B. Mein Pass)
    if pers:
        gruppen.remove(pers)
    gruppen.append(("Persönlich", (pers[1] if pers else []) + list(NAV_ALLE)))
    return gruppen


def _initialen(name):
    teile = [t for t in "".join(c if c.isalnum() else " " for c in name).split() if t]
    namen = [t for t in teile if not (t.isupper() and len(t) > 1)]   # Titel/Ordnungszahlen wie „SKKM“ oder „IX“ überspringen
    teile = namen or teile
    return ((teile[0][0] + (teile[-1][0] if len(teile) > 1 else "")) if teile else "?").upper()


# Ladeanzeige: Skeleton im Inhalt beim Wechsel auf eine andere Amtsseite, Ladekreis an Knöpfen, Menü-Blatt am Handy
JS = """(function(){
var B=document.body,M=document.getElementById("inhalt"),BASIS=%s,uhr=null,warte=null;
function z(w,h){return '<span class="sk" style="width:'+w+';'+(h?'height:'+h:'')+'"></span>'}
function zeilen(n,sp){var s="";for(var i=0;i<n;i++){s+='<div class="sk-zeile">';for(var j=0;j<sp.length;j++)s+=z(sp[j]);s+='</div>'}return s}
function skelett(u){var p=u.pathname,s='<div class="skelett" aria-hidden="true"><span class="sk sk-h1"></span><span class="sk sk-az"></span>';
 if(/\\/\\d+\\/$/.test(p)){s+='<span class="sk sk-h2"></span><div class="sk-dt">';for(var i=0;i<7;i++)s+=z((25+(i*37%%30))+'%%')+z((35+(i*53%%45))+'%%');
  s+='</div><span class="sk sk-h2"></span>'+zeilen(4,['22%%','48%%','14%%'])}
 else if(p===BASIS||/statistik\\/$/.test(p)){s+='<div class="sk-kz">';for(var i=0;i<5;i++)s+='<span class="sk"></span>';s+='</div><span class="sk sk-h2"></span>'+zeilen(5,['16%%','30%%','26%%','12%%'])}
 else s+=zeilen(9,['14%%','28%%','22%%','16%%']);
 return s+'</div>'}
function laden(u){fertig();warte=setTimeout(function(){var alt=M.querySelector(".skelett");if(alt)alt.remove();M.insertAdjacentHTML("afterbegin",skelett(u));B.classList.add("laedt");window.scrollTo(0,0)},90);
 uhr=setTimeout(fertig,15000)}
function fertig(){clearTimeout(warte);clearTimeout(uhr);B.classList.remove("laedt");var s=M.querySelector(".skelett");if(s)s.remove();
 document.querySelectorAll(".btn.arbeitet").forEach(function(b){b.classList.remove("arbeitet");b.disabled=false})}
function intern(u){return u.origin===location.origin&&u.pathname.indexOf(BASIS)===0&&!/(\\/pdf$|\\/logo\\/|\\/anhang\\/)/.test(u.pathname)}
document.addEventListener("click",function(e){if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
 var a=e.target.closest("a[href]");if(!a||a.target||a.hasAttribute("download"))return;var u=new URL(a.href,location.href);
 if(!intern(u))return;if(u.pathname===location.pathname&&u.search===location.search&&u.hash)return;menue(false);markieren(u);laden(u)});
function markieren(u){var z=[].filter.call(document.querySelectorAll(".seite a.ein,.tableiste a"),function(a){return a.pathname===u.pathname});if(!z.length)return;
 document.querySelectorAll(".seite a.ein.aktiv,.tableiste .aktiv").forEach(function(a){a.classList.remove("aktiv")});z.forEach(function(a){a.classList.add("aktiv")})}
document.addEventListener("submit",function(e){if(e.defaultPrevented)return;var f=e.target,b=e.submitter||f.querySelector("[type=submit]");
 if(b&&b.classList.contains("btn")){b.classList.add("arbeitet");setTimeout(function(){b.disabled=true},0)}
 if((f.getAttribute("method")||"get").toLowerCase()==="get"){var u=new URL(f.action||location.href,location.href);if(intern(u))laden(u)}});
addEventListener("pageshow",fertig);
function menue(auf){B.classList.toggle("menue-offen",auf);var k=document.getElementById("menue-auf");if(k)k.setAttribute("aria-expanded",auf?"true":"false");
 if(auf){var x=document.getElementById("menue-zu");if(x)x.focus()}}
var mk=document.getElementById("menue-auf");if(mk)mk.addEventListener("click",function(){menue(!B.classList.contains("menue-offen"))});
document.getElementById("menue-zu").addEventListener("click",function(){menue(false)});
document.getElementById("schleier").addEventListener("click",function(){menue(false)});
addEventListener("keydown",function(e){if(e.key==="Escape"){menue(false);var k=document.querySelector(".kopf");if(k)k.classList.remove("suche-offen")}});
var sa=document.querySelector(".such-auf");if(sa)sa.addEventListener("click",function(){var k=document.querySelector(".kopf"),o=k.classList.toggle("suche-offen");
 sa.setAttribute("aria-expanded",o?"true":"false");if(o)k.querySelector("input[type=search]").focus()});
var st=0,blatt=document.getElementById("menue");blatt.addEventListener("touchstart",function(e){st=e.touches[0].clientY},{passive:true});
blatt.addEventListener("touchend",function(e){if(blatt.scrollTop<=0&&e.changedTouches[0].clientY-st>70)menue(false)},{passive:true});
})();"""


def rahmen(titel, aktiv, inhalt, k, csrf, q="", portal=None):
    """Seitenrahmen der Amtsseite. portal = {"basis", "gruppen", "haupt", "logo": (schl, name), "name"} für eigene Portale im selben
    Stil (z. B. schatzamt.py): eigene Navigation, eigenes Logo, eigener Basispfad, keine Aktensuche. Optional "unter_logo" (HTML unter
    dem Logo der Seitenleiste) und "kopf_zusatz" (HTML neben dem Logo im Kopf, sichtbar auf dem Handy)."""
    import post
    basis = portal["basis"] if portal else BASIS
    leser = ist_leser(k) and not portal
    ungel = post.ungelesen(k)
    logo, logo_name = portal["logo"] if portal else logo_von(k)
    seitenname = portal["name"] if portal else "Amtsseite"
    zahl = lambda schl: f'<i class="zahl" title="{ungel} ungelesen">{ungel}</i>' if schl == "post" and ungel else ""
    gruppen = portal["gruppen"] if portal else nav_gruppen(k)

    def ein(schl, sym, text, pfad):
        cur = ' aria-current="page"' if schl == aktiv else ""
        ziel = pfad if pfad.startswith("/") else basis + pfad
        return f'<a class="ein{" aktiv" if schl == aktiv else ""}" href="{ziel}"{cur}>{ic(sym)}<span>{esc(text)}</span>{zahl(schl)}</a>'

    nav = "".join(f'<div class="gruppe"><p class="gruppe-titel">{esc(t)}</p>{"".join(ein(*e) for e in es)}</div>' for t, es in gruppen)
    # Tab-Leiste (Handy): die wichtigsten Ziele, dazu „Menü“ für alles Übrige
    alle = [e for _, es in gruppen for e in es]
    behoerden = [e for e in alle if e[0].startswith("b-")]
    haupt = (NAV[:3] if leser else behoerden[:2]) + [NAV_ALLE[0]]
    if not leser:
        haupt.append(NAV_ALLE[1])
    haupt = (portal["haupt"] if portal else haupt)[:4]
    im_menue = aktiv not in {e[0] for e in haupt}
    tabs = "".join(f'<a href="{pfad if pfad.startswith("/") else basis + pfad}" class="{"aktiv" if schl == aktiv else ""}"{" aria-current=page" if schl == aktiv else ""}>'
                   f'{ic(sym)}{zahl(schl)}<span>{esc(TAB_KURZ.get(schl, text))}</span></a>' for schl, sym, text, pfad in haupt)
    tabs += (f'<button type="button" id="menue-auf" class="{"aktiv" if im_menue else ""}" aria-controls="menue" aria-expanded="false">'
             f'{ic("layout-grid")}<span>Menü</span></button>')
    suche = portal["suche"] if portal and portal.get("suche") else ((f'<form class="suche" action="{BASIS}buerger/" method="get" role="search">{ic("search")}'
             f'<input type="search" name="q" value="{esc(q)}" placeholder="Suchen: Name, Aktenzeichen, ID" aria-label="Akten suchen"></form>'
             f'<button class="knopf-rund such-auf" type="button" aria-label="Suche öffnen" aria-expanded="false">{ic("search")}</button>') if leser else "")
    js = JS % json.dumps(basis)
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#ffffff"><meta name="robots" content="noindex,nofollow"><title>{esc(titel)} – {esc(logo_name)}, {esc(seitenname)}</title><style>{CSS}</style>
<script>(function(){{var m;try{{m=localStorage.getItem("amtModus")}}catch(e){{}}document.documentElement.className=m==="std"?"std":"min"}})()</script></head>
<body><div class="ladebalken" aria-hidden="true"></div>
<div class="app">
<aside class="seite" id="menue" aria-label="Navigation">
<div class="blatt-kopf"><b>Menü</b><button class="knopf-rund" type="button" id="menue-zu" aria-label="Menü schließen">{ic("x")}</button></div>
<a class="logo" href="{basis}" title="{esc(logo_name)} – {esc(seitenname)}"><img src="{BASIS}logo/{logo}-kopf.png" alt="{esc(logo_name)}"></a>{portal.get("unter_logo", "") if portal else ""}
<div class="gruppen">{nav}</div>
<div class="fuss"><a class="ein" href="{"/" if portal else "/informationen/die-reichsbehoerden/"}">{ic("house")}<span>Zur Website</span></a>
<div class="konto-box"><span class="avatar" aria-hidden="true">{esc(_initialen(k["name"]))}</span><span class="konto-text"><b>{esc(k["name"])}</b><small>{esc(logo_name)}</small></span>
<form method="post" action="/abmelden/"><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="weiter" value="/">
<button class="knopf-rund" type="submit" title="Abmelden" aria-label="Abmelden">{ic("log-out")}</button></form></div></div>
</aside>
<div class="spalte">
<header class="kopf"><a class="logo" href="{basis}" title="{esc(logo_name)} – {esc(seitenname)}"><img src="{BASIS}logo/{logo}-kurz.png" alt="{esc(logo_name)}"></a>{portal.get("kopf_zusatz", "") if portal else ""}<span class="raum"></span>{suche}</header>
<main id="inhalt">{OOC_HINWEIS if ist_ooc_admin(k) else ""}{inhalt}</main>
</div></div>
<div class="schleier" id="schleier"></div>
<nav class="tableiste" aria-label="Schnellzugriff">{tabs}</nav>
<script>{js}</script></body></html>"""


OOC_HINWEIS = ('<div class="ooc-hinweis" role="note"><b>OOC</b><span>Du siehst diese Seite als Serveradministrator mit vollem Zugriff. '
               'Dieser Zugriff ist rein OOC und verleiht kein Amt im Spiel.</span></div>')


# ---------------------------------------------------------------- Verlauf (Vorgänge, Aktenprotokoll)

import re as _re
_AEND = _re.compile(r"^(?:(?P<feld>[^:„“\n]{1,40}): )?„(?P<alt>.*)“ → „(?P<neu>.*)“$")
# Lesbare Namen der Datenbankfelder in Änderungsprotokollen
FELDNAMEN = {"ic_name": "Name (IC)", "ic_geburt": "Geburtsdatum (IC)", "fraktion": "Fraktion", "schicht": "Gesellschaftsschicht",
             "beruf": "Berufliche Zugehörigkeit", "geschlecht": "Geschlecht", "position": "Beruf / Position", "titel": "Titel",
             "tatbestand": "Tatbestand", "tatzeit": "Tatzeit (IC)", "tatort": "Tatort", "gericht": "Gericht", "termin": "Termin",
             "strafe": "Strafe", "haft_von": "Haft von", "haft_bis": "Haft bis", "haft_ort": "Haftort", "urteil": "Urteil"}
_PFEIL = ic("arrow-right").replace('class="icon"', 'class="icon pfeil"')
_ART_ICON = [("vermerk", "notebook-pen", "blau"), ("stammdaten", "pencil", ""), ("verfahrensdaten", "pencil", ""), ("geändert", "pencil", ""),
             ("verschluss", "lock", "rot"), ("gelöscht", "trash-2", "rot"), ("abgelehnt", "file-x", "rot"), ("eingebürgert", "user-check", "ok"),
             ("angelegt", "file-plus", "ok"), ("eröffnet", "file-plus", "ok"), ("abgabe", "arrow-right", "warn"), ("abgegeben", "arrow-right", "warn"),
             ("anhang", "paperclip", ""), ("beweis", "paperclip", ""), ("status", "flag", "warn"), ("stand", "flag", "warn"),
             ("phase", "flag", "warn"), ("einreise", "stamp", "blau"), ("ticket", "stamp", ""), ("geschlossen", "archive", "")]


def _art_icon(art):
    a = art.lower()
    for stichwort, sym, ton in _ART_ICON:
        if stichwort in a:
            return sym, ton
    return "clock", ""


def zeit_lesbar(ts):
    """„Heute, 14:32“, „Gestern, 09:10“, sonst Datum mit Uhrzeit."""
    if not ts:
        return "–"
    d = datetime.fromtimestamp(ts, BERLIN)
    tage = (datetime.now(BERLIN).date() - d.date()).days
    if tage == 0:
        return "Heute, " + d.strftime("%H:%M")
    if tage == 1:
        return "Gestern, " + d.strftime("%H:%M")
    return d.strftime("%d.%m.%Y, %H:%M")


def _wert(w, klasse):
    return f'<span class="{klasse}">{esc(w)}</span>' if w.strip() else '<span class="leerwert">leer</span>'


def aenderungen_teilen(text):
    """Zerlegt einen Protokolltext in Änderungen [(Feld, alt, neu)] und übrige Zeilen."""
    aend, rest = [], []
    for zeile in (text or "").split("\n"):
        m = _AEND.match(zeile.strip())
        if m:
            aend.append((m["feld"], m["alt"], m["neu"]))
        else:
            rest.append(zeile)
    return aend, "\n".join(rest).strip()


def kurztext(text, n=160):
    """Einzeilige Zusammenfassung eines Protokolleintrags (für Übersichten)."""
    aend, rest = aenderungen_teilen(text)
    teile = [f"{FELDNAMEN.get(f, f) + ': ' if f else ''}{n_ or 'leer'}" for f, _a, n_ in aend]
    s = " · ".join(([rest] if rest else []) + teile)
    return s if len(s) <= n else s[:n - 1] + "…"


def verlauf_html(eintraege, leer="Noch keine Vorgänge.", link=None):
    """Einträge (Zeilen mit zeit, art, text, autor_name) als Zeitleiste. link(e) → optional (href, Beschriftung)."""
    if not eintraege:
        return f'<p class="leer">{esc(leer)}</p>'
    out = []
    for e in eintraege:
        sym, ton = _art_icon(e["art"])
        aend, rest = aenderungen_teilen(e["text"])
        dl = ""
        if aend:
            dl = '<dl class="aend">' + "".join(
                f'<dt>{esc(FELDNAMEN.get(f, f) if f else e["art"])}</dt><dd>'
                + (f'{_wert(a, "alt")}{_PFEIL}' if a.strip() else "")
                + (_wert(n, "neu") if n.strip() else '<span class="leerwert">entfernt</span>') + "</dd>"
                for f, a, n in aend) + "</dl>"
        notiz = " notiz" if e["art"] == "Vermerk" else ""
        text = f'<div class="v-text{notiz}">{esc(rest)}</div>' if rest else ""
        verweis = ""
        if link:
            l = link(e)
            if l:
                verweis = f' · <a class="v-link" href="{l[0]}">{esc(l[1])}</a>'
        out.append(f'<li><span class="v-ic{" t-" + ton if ton else ""}">{ic(sym)}</span>'
                   f'<div class="v-kopf"><span class="v-art">{esc(e["art"])}</span>'
                   f'<span class="v-meta"><time title="{_zeit(e["zeit"])}">{zeit_lesbar(e["zeit"])}</time> · {esc(e["autor_name"] or "System")}{verweis}</span></div>'
                   f'{text}{dl}</li>')
    return '<ol class="verlauf">' + "".join(out) + "</ol>"


def status_marke(klasse, text):
    return f'<span class="status s-{klasse}">{esc(text)}</span>'


def akte_marke(s):
    return status_marke({"staatsbuerger": "ok", "einwanderer": "offen"}.get(s, "neutral"), STATUS_AKTE.get(s, s))


def ergebnis_marke(e):
    return status_marke({"eingebuergert": "ok", "abgelehnt": "nein", "offen": "offen"}.get(e, "neutral"), ERGEBNIS.get(e, e))


def tabelle(kopf, zeilen, leer="Keine Einträge.", klasse=""):
    if not zeilen:
        return f'<p class="leer">{esc(leer)}</p>'
    th = "".join(f"<th>{esc(h)}</th>" for h in kopf)
    tr = "".join("<tr>" + "".join(f'<td data-l="{esc(kopf[i])}">{c}</td>' for i, c in enumerate(z)) + "</tr>" for z in zeilen)
    return f'<table class="liste{" " + klasse if klasse else ""}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'


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
    return verlauf_html(con.execute("SELECT * FROM amt_eintraege WHERE ziel=? AND ziel_id=? ORDER BY zeit DESC, id DESC", (ziel, ziel_id)).fetchall())


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
            akte_sichern(con, m["id"], m["name"], "staatsbuerger", "", "Akte angelegt (Abgleich)")   # IC-Name ≠ Discord-Name: leer lassen
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
    return anmeldung.angemeldet(ist_leser, "Die Akten sind der Reichsverwaltung vorbehalten.")(handler)


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


async def uebersicht(request):
    k = await anmeldung.konto(request)
    if k is None:
        raise web.HTTPFound("/anmelden/?weiter=" + BASIS)
    if not ist_leser(k):
        import bereiche
        eigene = bereiche.sichtbar(k)
        extra = [e for _, fn in NAV_EXTRA for e in fn(k)]
        raise web.HTTPFound(BASIS + (f"bereich/{eigene[0]['schl']}/" if eigene else extra[0][3] if extra else "postfach/"))
    return await _uebersicht(request)


@_beamter
async def _uebersicht(request):
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
    def _letzte(e):
        gesperrt = (e["ziel"] == "akte" and e["ziel_id"] in sa) or (e["ziel"] == "verfahren" and e["ziel_id"] in verf_gesperrt)
        return {"zeit": e["zeit"], "art": "Unter Verschluss" if gesperrt else e["art"], "text": "" if gesperrt else kurztext(e["text"], 220),
                "autor_name": "–" if gesperrt else e["autor_name"], "ziel": e["ziel"], "ziel_id": e["ziel_id"]}
    letzte = [_letzte(e) for e in con.execute("SELECT * FROM amt_eintraege ORDER BY id DESC LIMIT 12")]
    link = lambda e: (f'{BASIS}{"buerger" if e["ziel"] == "akte" else "verfahren"}/{e["ziel_id"]}/',
                      az_akte(e["ziel_id"]) if e["ziel"] == "akte" else "Verfahren " + str(e["ziel_id"]))
    inhalt = (f'<h1>{ic("layout-dashboard")} Übersicht</h1><p class="az">Reichsbehörden · Kaiserliche Zollverwaltung</p>{meldung(request)}'
              f'<div class="kennzahlen">{zahlen}</div>'
              f'<h2>Zur Bearbeitung</h2>{tabelle(["Aktenzeichen", "Name", "Stand", "Zuletzt"], zeilen, "Keine offenen Verfahren.")}'
              f'<h2>Letzte Vorgänge</h2>{verlauf_html(letzte, link=link)}'
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
              (f'<a href="{BASIS}buerger/{r["id"]}/">{az_akte(r["id"])}</a>',
               esc(r["ic_name"]) if r["ic_name"] else f'<span class="nur-gross">–</span><span class="nur-klein">{esc(r["name"])} <i class="leerwert">(Discord)</i></span>',
               esc(r["name"]), esc(r["fraktion"]) if r["fraktion"] else '<span class="nur-gross leer-f">–</span>',
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
              f'<form class="zeile filter" method="get"><div class="f-suche"><label for="q">Suche</label><input type="search" id="q" name="q" value="{esc(q)}" placeholder="Name, Aktenzeichen, ID"></div>'
              f'<div><label for="st">Status</label><select id="st" name="status"><option value="">Alle</option>{opt}</select></div>'
              f'<button class="btn" type="submit" aria-label="Suchen">{ic("search")}<span class="nur-gross">Suchen</span></button></form>'
              f'{tabelle(["Aktenzeichen", "Name (IC)", "Discord-Name", "Fraktion", "Status"], zeilen, "Keine Akten gefunden.", "akten")}'
              f'<div class="seiten">{nav}</div>')
    return _ant(request, "Bürgerakten", "buerger", inhalt, q)


def _optionen(liste, aktuell, leer="–"):
    o = f'<option value="">{leer}</option>' + "".join(f'<option{" selected" if x == aktuell else ""}>{esc(x)}</option>' for x in liste)
    if aktuell and aktuell not in liste:
        o += f'<option selected>{esc(aktuell)}</option>'
    return o


def anzeige_name(z):
    """Name für Überschriften: der IC-Name; fehlt er, der Discord-Name mit Hinweis (beides sind verschiedene Namen)."""
    return z["ic_name"] or f'{z["name"]} (Discord-Name, IC-Name fehlt)'


def _stamm(z):
    return daten_tabelle([("Aktenzeichen", az_akte(z["id"])), ("Status", akte_marke(z["status"])), ("Name (IC)", esc(z["ic_name"] or "– (nicht erfasst)")),
                           ("Geburtsdatum (IC)", esc(z["ic_geburt"] or "–")), ("Geschlecht", esc(z["geschlecht"] or "–")), ("Fraktion", esc(z["fraktion"] or "–")),
                           ("Gesellschaftsschicht", esc(z["schicht"] or "–")), ("Berufliche Zugehörigkeit", esc(z["beruf"] or "–")),
                           ("Aktueller Beruf / Position", esc(z["position"] or "–")),
                           ("Discord-Name (von Discord, nicht bearbeitbar)", esc(z["name"])), ("Discord-ID", esc(z["konto_id"])),
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
    vs = [_verfahren_zeile(v) for v in con.execute("SELECT * FROM amt_verfahren WHERE konto_id=? ORDER BY id DESC", (z["konto_id"],))]
    w = schreiben(request)
    verschluss_form = ""
    if darf_verschluss(request["konto"]):
        verschluss_form = (f'<form method="post" action="{pfad}verschluss" style="display:inline">{csrf_feld(request)}'
                           f'<input type="hidden" name="wert" value="{0 if z["verschluss"] else 1}">'
                           f'<button class="btn zweit" type="submit">{ic("lock-open" if z["verschluss"] else "lock")}'
                           f'{"Verschluss aufheben" if z["verschluss"] else "Unter Verschluss setzen"}</button></form>')
    inhalt = (f'<h1>{ic("book-user")} Bürgerakte {az_akte(z["id"])}</h1><p class="az">{esc(anzeige_name(z))}</p>{meldung(request)}'
              + (f'<div class="warnung">{ic("lock")} Diese Akte steht unter Verschluss; nur Kaiser und Kanzler können sie einsehen.</div>' if z["verschluss"] else "")
              + (f'<div class="hinweis">Nur Lesezugriff: Änderungen sind mit deiner Berechtigung nicht möglich.</div>' if not w else "")
              + f'<div class="aktionen">' + (f'<a class="btn" href="{pfad}bearbeiten/">{ic("pencil")}Akte bearbeiten</a>' if w else "")
              + f'<a class="btn zweit" href="{pfad}pdf">{ic("file-down")}Als PDF exportieren</a>'
              + (f'<a class="btn gefahr" href="{pfad}loeschen/">{ic("trash-2")}Akte löschen</a>' if w else "") + verschluss_form + '</div>'
              f'<h2>Stammdaten</h2>{stamm}' + "".join(f(request, con, z, w) for f in AKTE_ZUSATZ) +
              f'<h2>Einbürgerungsakten</h2>{tabelle(["Aktenzeichen", "Name", "Stand", "Zuletzt"], vs, "Kein Einreiseverfahren erfasst.")}'
              f'<h2>Vorgänge</h2>{eintraege_html(con, "akte", z["id"])}' + (f'<h2>Vermerk</h2>{vermerk_formular(request, pfad)}' if w else ""))
    return _ant(request, f"Bürgerakte {az_akte(z['id'])}", "buerger", inhalt)


def _feld(fid, label, eingabe, hilfe=""):
    return f'<div class="feld"><label for="{fid}">{esc(label)}</label>{eingabe}' + (f'<small>{esc(hilfe)}</small>' if hilfe else "") + "</div>"


@_beamter
async def buerger_bearbeiten_seite(request):
    con = request.app["db"]
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (request.match_info["id"],)).fetchone() if request.match_info["id"].isdigit() else None
    if not z:
        raise web.HTTPNotFound(text="Akte nicht gefunden.")
    if z["verschluss"] and not darf_verschluss(request["konto"]):
        return _gesperrt_seite(request, "Bürgerakte", "buerger", az_akte(z["id"]))
    pfad = f"{BASIS}buerger/{z['id']}/"
    if not schreiben(request):
        raise web.HTTPSeeOther(pfad)
    t = lambda fid, name, n: f'<input type="text" id="{fid}" name="{name}" value="{esc(z[name])}" maxlength="{n}">'
    inhalt = (f'<p class="zurueck"><a href="{pfad}">{ic("arrow-left")}Bürgerakte {az_akte(z["id"])}</a></p>'
              f'<h1>Akte bearbeiten</h1><p class="az">{esc(anzeige_name(z))} · {az_akte(z["id"])}</p>{meldung(request)}'
              f'<form class="formular" method="post" action="{pfad}bearbeiten">{csrf_feld(request)}'
              '<fieldset><legend>Person (im Charakter)</legend><div class="felder">'
              + _feld("n", "Name (IC)", t("n", "ic_name", 80), "Nicht der Discord-Name.")
              + _feld("g", "Geburtsdatum (IC)", t("g", "ic_geburt", 40))
              + _feld("ge", "Geschlecht", f'<select id="ge" name="geschlecht">{_optionen(GESCHLECHTER, z["geschlecht"])}</select>')
              + _feld("f", "Fraktion", t("f", "fraktion", 80))
              + '</div></fieldset><fieldset><legend>Stand und Beruf</legend><div class="felder">'
              + _feld("s", "Gesellschaftsschicht", f'<select id="s" name="schicht">{_optionen(SCHICHTEN, z["schicht"])}</select>')
              + _feld("b", "Berufliche Zugehörigkeit", f'<select id="b" name="beruf">{_optionen(BERUFE, z["beruf"])}</select>')
              + _feld("po", "Aktueller Beruf / Position", t("po", "position", 120)).replace('class="feld"', 'class="feld breit"')
              + '</div></fieldset>'
              f'<p class="az">Discord-Name ({esc(z["name"])}) und Discord-ID kommen von Discord und lassen sich hier nicht ändern. Jede Änderung wird in den Vorgängen der Akte protokolliert.</p>'
              f'<div class="formular-fuss"><a class="btn zweit" href="{pfad}">Abbrechen</a><button class="btn" type="submit">{ic("check")}Speichern</button></div></form>')
    return _ant(request, f"Akte bearbeiten – {az_akte(z['id'])}", "buerger", inhalt)


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
            f'<h2>Staatsbürger nach Geschlecht</h2>{_balken(gruppe("geschlecht"))}'
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
    inhalt = (f'<h1>{ic("trash-2")} Bürgerakte {az_akte(z["id"])} löschen</h1><p class="az">{esc(anzeige_name(z))}</p>{meldung(request)}'
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
    zeilen = [(_zeit(r["zeit"]), esc(r["aktenzeichen"]), esc(r["ic_name"] or r["name"] + " (Discord)"), esc(r["konto_id"]), esc(STATUS_AKTE.get(r["status"], r["status"])),
               "ja" if r["verfahren_geloescht"] else "nein", esc(r["grund"]), esc(r["autor_name"]))
              for r in con.execute("SELECT * FROM amt_loeschungen ORDER BY id DESC LIMIT 500")]
    inhalt = (f'<h1>{ic("scroll-text")} Löschprotokoll</h1><p class="az">Gelöschte Bürgerakten</p>{meldung(request)}'
              + tabelle(["Zeit", "Aktenzeichen", "Name", "Discord-ID", "Status", "Einbürgerungsakten mitgelöscht", "Grund", "Bearbeiter"], zeilen, "Es wurden noch keine Akten gelöscht."))
    return _ant(request, "Löschprotokoll", "protokoll", inhalt)


# ---------------------------------------------------------------- PDF-Export

# Amtliches Layout: Briefkopf mit Behördenlogo und Kennblock (Az., Datum, Bearbeiter), VS-Einstufung und Seitenzählung auf
# jeder Seite, nummerierte Abschnitte, schwacher Adler als Wasserzeichen, am Ende Dienstsiegel und Schlussvermerk.
import base64 as _b64
_GRUND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "werkzeuge", "logo_grundlage")


def _datei_b64(pfad):
    with open(pfad, "rb") as f:
        return _b64.b64encode(f.read()).decode()


_PDF_SCHRIFT = _datei_b64(os.path.join(_GRUND, "source-sans-3.woff2"))
_PDF_ADLER = _datei_b64(os.path.join(_GRUND, "adler.png"))
_PDF_LOGOS = {}

EINSTUFUNG_NFD = "VS – Nur für den Dienstgebrauch"
EINSTUFUNG_VERTRAULICH = "VS – Vertraulich"
EINSTUFUNG_GEHEIM = "VS – Geheim"


def stelle_behoerde(schl):
    """(Logo-Schlüssel, Name) einer Behörde aus BEHOERDEN, für den PDF-Briefkopf."""
    b = next((b for b in BEHOERDEN if b["schl"] == schl), None)
    return (b["schl"], b["name"]) if b else ("reichsbehoerden", "Die Reichsbehörden")


STELLE_KANZLER = ("kanzler", "Der Kanzler")
STELLE_REICHSBEHOERDEN = ("reichsbehoerden", "Die Reichsbehörden")


def _pdf_logo(schl):
    if schl not in _PDF_LOGOS:
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amt_logos", schl + ".png")
        _PDF_LOGOS[schl] = _datei_b64(pfad if os.path.exists(pfad) else pfad.replace(schl + ".png", "reichsbehoerden.png"))
    return _PDF_LOGOS[schl]


def _ohne_mobil(css):
    """Entfernt die @media(max-width…)-Blöcke: die A4-Seite ist schmaler als 800 px, sonst griffe im PDF die Handy-Ansicht."""
    out, i = [], 0
    while True:
        j = css.find("@media (max-width", i)
        if j < 0:
            return "".join(out) + css[i:]
        out.append(css[i:j])
        tiefe, n = 0, css.index("{", j)
        while True:
            tiefe += {"{": 1, "}": -1}.get(css[n], 0)
            n += 1
            if tiefe == 0:
                break
        i = n


PDF_CSS = _ohne_mobil(CSS) + """
@font-face{font-family:SS3;src:url(data:font/woff2;base64,%s);font-weight:200 900}
html,body{background:#fff}
body{font:10.5pt/1.45 SS3,"Liberation Sans",Arial,sans-serif;color:#000;counter-reset:abschnitt}
.kopf,nav{display:none}.rahmen{display:block;min-height:0}main{padding:0;max-width:none}
.wz{position:fixed;left:50%%;top:50%%;width:120mm;transform:translate(-50%%,-50%%);opacity:.045;z-index:-1}
.bk{display:flex;justify-content:space-between;align-items:flex-start;gap:10mm;margin:0 0 9mm}
.bk-logo img{width:64mm;height:auto;display:block}
.bk-logo .unter{margin:1.5mm 0 0 21.3mm;font-size:9pt;color:#333}
.bk-rechts{display:flex;gap:3.5mm;align-items:flex-start}
.bk-qr{width:19mm;text-align:center;font-size:5.6pt;color:#444;letter-spacing:.04em}.bk-qr span{display:block;margin-top:.4mm}
.bk-block{width:52mm;font-size:8.5pt;line-height:1.35;border-left:.6pt solid #000;padding-left:3.5mm}
.bk-block dt{color:#555;text-transform:uppercase;letter-spacing:.06em;font-size:6.8pt;margin-top:1.6mm}
.bk-block dt:first-child{margin-top:0}.bk-block dd{margin:0;font-weight:600}
.vs{display:inline-block;border:1pt solid #000;padding:.6mm 2.4mm;font-size:8pt;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin:0 0 4mm}
.vs.rot{color:#a00;border-color:#a00}
.doktyp{font-size:8pt;letter-spacing:.14em;text-transform:uppercase;color:#555;margin:0 0 1mm}
main>h1:first-of-type{font-size:17pt;font-weight:700;margin:0 0 1mm;letter-spacing:0;display:block}
h1 .icon,h2 .icon{display:none}
main>p.az:first-of-type{font-size:10pt;color:#333;margin:0 0 6mm;padding-bottom:3mm;border-bottom:.6pt solid #000}
h2{counter-increment:abschnitt;font-size:11.5pt;font-weight:700;margin:7mm 0 2.5mm;padding:0 0 1.2mm;border-bottom:.6pt solid #000;break-after:avoid}
h2::before{content:counter(abschnitt) ".\\00a0\\00a0"}
h3{font-size:10.5pt;break-after:avoid}
table{font-size:9.5pt;margin:2mm 0}table,tr{break-inside:avoid}
table.daten th,table.daten td,table.liste th,table.liste td{border:0;border-bottom:.4pt solid #999;padding:1.4mm 2mm;background:none;vertical-align:top}
table.daten th{width:58mm;font-weight:600;color:#333}
table.liste thead th{border-bottom:.8pt solid #000;font-size:7.5pt;text-transform:uppercase;letter-spacing:.06em;color:#000;font-weight:700}
table.liste td a,a{color:#000;text-decoration:none}
.status{border-radius:0;border:.6pt solid #000;color:#000!important;background:none!important;font-size:7.5pt;text-transform:uppercase;letter-spacing:.06em;padding:0 1.6mm}
.kennzahlen{grid-template-columns:repeat(4,1fr);gap:2mm}.kennzahlen div{border:.6pt solid #000;border-radius:0;padding:2mm 3mm;min-width:0;color:#333}
.kennzahlen b{font-size:16pt}
.verlauf>li{padding:0 0 3mm 9mm}.verlauf>li::before{left:3mm;top:7mm;background:#999;width:.6pt}
.v-ic{width:6mm!important;height:6mm!important;border-color:#000!important;color:#000!important;background:#fff!important}
.v-ic .icon{width:3.4mm!important;height:3.4mm!important}
.leer{color:#555;font-style:italic}
.btn,button,form,.aktionen,.meldung,.ooc-hinweis{display:none!important}
.schluss{margin-top:10mm;display:flex;gap:8mm;align-items:center;break-inside:avoid;border-top:.6pt solid #000;padding-top:5mm}
.siegel{width:32mm;height:32mm;flex:none}
.schluss-text{font-size:9pt;line-height:1.5}
.schluss-text .ia{margin:0 0 7mm}.schluss-text .linie{border-top:.4pt solid #000;width:60mm;padding-top:1mm}
.schluss-text .s-hinweis{margin-top:3mm;font-size:7.5pt;color:#444}
.ooc-export{margin-top:4mm;border:1pt dashed #000;padding:2mm 3mm;font-size:8.5pt}
""" % _PDF_SCHRIFT
_pdf_sperre = asyncio.Semaphore(1)


def _siegel(name):
    """Rundes Dienstsiegel: Adler in der Mitte, Behördenname und „Imperium Germanicum“ als Umschrift."""
    oben, unten = esc(name.upper()), "IMPERIUM GERMANICUM"
    return (f'<svg class="siegel" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            f'<defs><path id="so" d="M 30 100 A 70 70 0 0 1 170 100"/><path id="su" d="M 24 100 A 76 76 0 0 0 176 100"/></defs>'
            f'<circle cx="100" cy="100" r="96" fill="none" stroke="#000" stroke-width="3"/><circle cx="100" cy="100" r="90" fill="none" stroke="#000" stroke-width="1"/>'
            f'<circle cx="100" cy="100" r="54" fill="none" stroke="#000" stroke-width="1"/>'
            f'<text font-family="SS3,Arial" font-size="{13 if len(oben) < 26 else 11}" font-weight="700" letter-spacing="1.5" text-anchor="middle">'
            f'<textPath href="#so" startOffset="50%">{oben}</textPath></text>'
            f'<text font-family="SS3,Arial" font-size="12" font-weight="600" letter-spacing="2.5" text-anchor="middle">'
            f'<textPath href="#su" startOffset="50%">{unten}</textPath></text>'
            f'<text x="22" y="105" font-size="12" text-anchor="middle">★</text><text x="178" y="105" font-size="12" text-anchor="middle">★</text>'
            f'<image href="data:image/png;base64,{_PDF_ADLER}" x="62" y="64" width="76" height="70" preserveAspectRatio="xMidYMid meet"/></svg>')


def _pdf_html(titel, inhalt, k, stelle=None, az="", einstufung=EINSTUFUNG_NFD, doktyp="", unterzeile="", schluss="", qr_url="", bearbeiter=None):
    schl, name = stelle or logo_von(k)
    bearbeiter = bearbeiter or k["name"]
    jetzt = _zeit(int(time.time()))
    block = "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in
                    [("Dienststelle", unterzeile or name), ("Aktenzeichen", az), ("Datum", jetzt.split(" ")[0]),
                     ("Erstellt", jetzt + " Uhr"), ("Bearbeitet von", bearbeiter)] if b)
    kopf = (f'<img class="wz" src="data:image/png;base64,{_PDF_ADLER}" alt="">'
            f'<div class="bk"><div class="bk-logo"><img src="data:image/png;base64,{_pdf_logo(schl)}" alt="{esc(name)}">'
            f'{f"<div class=unter>{esc(unterzeile)}</div>" if unterzeile else ""}</div>'
            f'<div class="bk-rechts">{_pdf_qr(qr_url)}<dl class="bk-block">{block}</dl></div></div>'
            + (f'<div class="vs{" rot" if einstufung != EINSTUFUNG_NFD else ""}">{esc(einstufung)}</div>' if einstufung else "")
            + (f'<p class="doktyp">{esc(doktyp)}</p>' if doktyp else ""))
    ooc = ('<div class="ooc-export"><b>OOC</b> – Erstellt durch einen Serveradministrator mit OOC-Zugriff. '
           'Dieses Dokument ist kein amtliches Schriftstück im Spiel.</div>') if ist_ooc_admin(k) else ""
    fuss = (f'<div class="schluss">{_siegel(name)}<div class="schluss-text">'
            f'{schluss or "<p class=ia>Im Auftrag</p>"}'
            f'<div class="linie">{esc(bearbeiter)}<br>{esc(unterzeile or name)}</div>'
            f'<p class="s-hinweis">Dieses Schriftstück wurde maschinell erstellt und ist ohne Unterschrift gültig. '
            f'Auszug aus den Akten der Reichsbehörden des Imperium Germanicum, Stand {jetzt} Uhr.</p></div></div>{ooc}')
    return (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{esc(titel)}</title><style>{PDF_CSS}</style></head>'
            f'<body><main>{kopf}{inhalt}{fuss}</main></body></html>')


def _pdf_qr(url):
    if not url:
        return ""
    import qr
    return f'<div class="bk-qr">{qr.svg(url, 19)}<span>Echtheit prüfen</span></div>'


def _pdf_rand(text, name, einstufung):
    """Kopf- und Fußzeile auf jeder Seite (Playwright-Vorlagen: eigene Inline-Stile, keine eingebetteten Schriften)."""
    st = "font-family:'Liberation Sans',Arial,sans-serif;font-size:7.5pt;color:#333;width:100%;margin:0 20mm 0 20mm;display:flex;justify-content:space-between"
    vs = f'<b style="letter-spacing:.08em;text-transform:uppercase;color:{"#000" if einstufung == EINSTUFUNG_NFD else "#a00"}">{esc(einstufung)}</b>' if einstufung else "<span></span>"
    kopf = f'<div style="{st}"><span>{esc(name)}</span>{vs}</div>'
    fuss = (f'<div style="{st};border-top:.5pt solid #999;padding-top:1.5mm"><span>Imperium Germanicum · {esc(name)} · {esc(text)}</span>'
            '<span>Seite <span class="pageNumber"></span> von <span class="totalPages"></span></span></div>')
    return kopf, fuss


async def _pdf_antwort(request, dateiname, titel, inhalt, stelle=None, az="", einstufung=EINSTUFUNG_NFD, doktyp="", unterzeile="", schluss="", qr_url=None, bearbeiter=None):
    """PDF im amtlichen Layout. stelle = (Logo-Schlüssel, Behördenname) der ausstellenden Stelle (sonst die des Kontos),
    az = Aktenzeichen im Kennblock, einstufung = VS-Vermerk („“ = keiner, z. B. Bescheinigungen für Bürger)."""
    from playwright.async_api import async_playwright
    import bild  # setzt PLAYWRIGHT_BROWSERS_PATH
    k = request["konto"]
    stelle = stelle or logo_von(k)
    if qr_url is None:   # Standard: Seite des Dokuments in der Amtsseite (Pfad ohne letztes Segment, z. B. …/buerger/13/pdf → …/buerger/13/)
        qr_url = config.SITE_URL + request.path.rsplit("/", 1)[0] + "/"
    text = _pdf_html(titel, inhalt, k, stelle, az, einstufung, doktyp, unterzeile, schluss, qr_url, bearbeiter)
    kopf, fuss = _pdf_rand(az or titel, unterzeile or stelle[1], einstufung)
    async with _pdf_sperre:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                pg = await browser.new_page()
                await pg.set_content(text)
                await pg.evaluate("document.fonts.ready")
                pdf = await pg.pdf(format="A4", print_background=True, display_header_footer=True, header_template=kopf, footer_template=fuss,
                                   margin={"top": "17mm", "bottom": "20mm", "left": "20mm", "right": "18mm"})
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
    inhalt = (f'<h1>Bürgerakte {az_akte(z["id"])}</h1><p class="az">{esc(anzeige_name(z))}</p>'
              f'<h2>Stammdaten</h2>{_stamm(z)}'
              f'<h2>Einbürgerungsakten</h2>{tabelle(["Aktenzeichen", "Name", "Stand", "Zuletzt"], vs, "Kein Einreiseverfahren erfasst.")}'
              f'<h2>Vorgänge</h2>{eintraege_html(con, "akte", z["id"])}')
    return await _pdf_antwort(request, az_akte(z["id"]), f"Bürgerakte {az_akte(z['id'])}", inhalt, az=az_akte(z["id"]),
                              doktyp="Aktenauszug · Bürgerakte", einstufung=EINSTUFUNG_VERTRAULICH if z["verschluss"] else EINSTUFUNG_NFD)


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
    return await _pdf_antwort(request, az, f"Einbürgerungsakte {az}", inhalt, az=az, doktyp="Aktenauszug · Einbürgerungsakte")


@_beamter
async def statistik_pdf(request):
    inhalt = f'<h1>Statistiken</h1><p class="az">Stand {_zeit(int(time.time()))}</p>{statistik_inhalt(request.app["db"])}'
    return await _pdf_antwort(request, "statistik-" + datetime.now(BERLIN).strftime("%Y-%m-%d"), "Statistiken", inhalt, doktyp="Statistischer Bericht")

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
           "schicht": _text(form, "schicht", 40), "beruf": _text(form, "beruf", 40),
           "geschlecht": _text(form, "geschlecht", 20), "position": _text(form, "position", 120)}
    aenderungen = [f"{f}: „{z[f]}“ → „{w}“" for f, w in neu.items() if z[f] != w]
    pfad = f"{BASIS}buerger/{i}/"
    if not aenderungen:
        _umleiten(pfad, "Keine Änderung.")
    con.execute("UPDATE amt_akten SET ic_name=?, ic_geburt=?, fraktion=?, schicht=?, beruf=?, geschlecht=?, position=?, aktualisiert=? WHERE id=?",
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
    erlaubt = {l[1] for l in LOGOS} | {"reichsbehoerden"} | {b["schl"] for b in BEHOERDEN}
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
    app.router.add_get(BASIS + "buerger/{id}/bearbeiten/", buerger_bearbeiten_seite)
    app.router.add_post(BASIS + "buerger/{id}/bearbeiten", buerger_bearbeiten)
    app.router.add_post(BASIS + "buerger/{id}/vermerk", vermerk)
    app.router.add_post(BASIS + "buerger/{id}/verschluss", verschluss_setzen)
    app.router.add_post(BASIS + "verfahren/{id}/vermerk", vermerk)
    app.router.add_post(BASIS + "verfahren/{id}/schliessen", verfahren_schliessen)
    app.router.add_post("/intern-api/amt/einreise", api_einreise)
    app.router.add_post("/intern-api/amt/einbuergerung", api_einbuergerung)
    app.router.add_post("/intern-api/amt/ticket-geschlossen", api_ticket_geschlossen)
