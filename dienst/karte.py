"""Reichskarte (karte.js): Teilstaaten auf NUTS-3-Gebieten, Anzeige, Editor, Gebietsnamen und Anträge der Regenten.

    GET  /karte/                 Anzeige (auch /en/karte/)
    GET  /karte/bearbeiten/      Editor (nur Server-Admins)
    GET  /karte/geo.json         Geodaten (karte_daten/geo.json, gebaut von werkzeuge/karte_bauen.py)
    GET  /karte/daten.json       aktueller Stand (Teilstaaten, Zuordnung, Gebietsnamen)
    GET  /karte/info.json        Einwohner, Regenten je Teilstaat, für Angemeldete: Rechte und eigene Anträge
    POST /karte/speichern        neuer Stand aus dem Editor (Konflikterkennung über basis)
    POST /karte/antrag           Regent beantragt einen Gebietsnamen → DM an den Kanzler
    POST /karte/gebietsname      Kanzler setzt einen Gebietsnamen unmittelbar (leer = heutiger Name)
    GET  /karte/antraege/        Kanzler: offene Anträge entscheiden (POST …/entscheiden) → DM an den Antragsteller
    GET  /karte/karte.png        Bild für die Startseite (karte_bild.py)

Regent eines Teilstaats: Landesherr mit der Fraktionsrolle des Teilstaats; Teilstaaten ohne Fraktionsrolle verwaltet der Kanzler.
Jeder Stand ist eine Zeile in karte_versionen; der jüngste gilt. Startstand: karte_daten/startstand.json (aus der alten Karte).
"""
import asyncio
import gzip
import html
import json
import logging
import os
import re
import secrets
import shutil
import time
from datetime import datetime, timezone

from aiohttp import web

import anmeldung
import config
import karte_bild
from seiten import seite

esc = html.escape
log = logging.getLogger("karte")
DATEN = os.path.join(config.HIER, "karte_daten")
ROLLE_LANDESHERR = "1522701576295415969"
ROLLE_SOUVERAEN = "1522685953054081054"      # Imperator Rex
# Zusatzämter von Regenten (Vizekönig … Bürgermeister), erscheinen in der Gebietsübersicht
ROLLEN_AEMTER = ("1525947356049309788", "1525947448776986665", "1525947612639793253", "1555971841888223242", "1525948431267532860")
REICHSGEBIETE = "Freie Reichsgebiete"        # kein Teilstaat: Kanzler und Souverän regieren
ROLLE_KANZLER = "1561856444913946664"
# Fraktionsrollen, die zugleich etwas anderes bedeuten: „Heiliger Stuhl“ ist auch die Rolle des Klerus (Kardinal, Bischof …).
# Sie zählt nur als Fraktion, wenn die Person keine andere Fraktionsrolle hat (z. B. Kardinal Baier → St. Longinus Orden).
FRAKTION_NACHRANGIG = {"1522705410069631017"}


def fraktionen(rollen, staaten):
    """Wirksame Fraktionsrollen einer Person (nachrangige Doppelrollen fallen weg, sobald eine andere Fraktion da ist)."""
    rollen = set(rollen or ())
    fr = {s["fraktion"] for s in staaten if s.get("fraktion") and s["fraktion"] in rollen}
    return fr - FRAKTION_NACHRANGIG if fr - FRAKTION_NACHRANGIG else fr
MUSTER = ("voll", "streifen", "karo", "punkte")

with open(os.path.join(DATEN, "geo.json"), encoding="utf-8") as _fh:
    GEO = json.load(_fh)
with open(os.path.join(DATEN, "bevoelkerung.json"), encoding="utf-8") as _fh:
    BEV = json.load(_fh)

T = {
    "de": {"answer": "Antwort", "area": "Fläche", "capital": "Hauptstadt", "loading": "Karte wird geladen …", "loadingRetry": "Karte wird geladen … (Versuch {n})",
           "retry": "Erneut versuchen",
           "capitalPrompt": "Name der Hauptstadt von „{state}“", "toolCapital": "Hauptstadt",
           "capitalHint": "Hauptstadt: Mit gewähltem Teilstaat auf die Karte klicken setzt dessen Hauptstadt an diese Stelle (der Name kommt vom nächsten Ort oder wird abgefragt).", "changes": "{n} ungespeicherte Änderungen", "chooseState": "Teilstaat wählen",
           "confirmDelete": "Teilstaat „{name}“ löschen? {n} Gebiete werden dann keinem Teilstaat mehr zugeordnet.",
           "conflict": "Inzwischen hat {name} einen neueren Stand gespeichert. Bitte lade die Seite neu und übernimm deine Änderungen erneut.",
           "countryPick": "– Land wählen –", "density": "Bevölkerungsdichte", "edit": "Bearbeiten", "editState": "Teilstaat bearbeiten",
           "infoError": "Die Angaben konnten nicht geladen werden.", "inhabitants": "Einwohner",
           "kanzlerIntro": "Als Kanzler legst du den Namen dieses Gebiets im Rollenspiel unmittelbar fest. Leer lassen oder zurücksetzen stellt den heutigen Namen wieder her.",
           "kanzlerNote": "Der Teilstaat hat keinen eigenen Regenten; der Kanzler verwaltet ihn als Vertreter des Souveräns.",
           "leave": "Es gibt ungespeicherte Änderungen.", "loadError": "Die Karte konnte nicht geladen werden.", "login": "Mit Discord anmelden",
           "loginHint": "Regenten dieses Teilstaats können nach der Anmeldung einen neuen Namen für das Gebiet beantragen.",
           "more": "Teilstaaten und Speichern", "nameEmpty": "Bitte einen Namen angeben.", "nameField": "Name im Rollenspiel",
           "nameSaved": "Name gespeichert.", "nameTaken": "Diesen Namen trägt schon ein anderer Teilstaat.", "newName": "Neuer Name",
           "newState": "Neuer Teilstaat", "noChanges": "Keine Änderungen", "noData": "keine Angabe",
           "noFaction": "kein Regent hinterlegt", "noKanzler": "Das Amt des Kanzlers ist unbesetzt.", "noState": "keinem Teilstaat zugeordnet",
           "notFound": "Kein Gebiet gefunden.", "notReich": "Nicht Teil des Reiches", "perKm2": "Einwohner je km²", "population": "Bevölkerung",
           "reason": "Begründung", "regent": "Regent", "regionCount": "Gebiete", "renameBtn": "Neuen Namen beantragen",
           "renameH": "Name im Rollenspiel",
           "renameIntro": "Als Regent dieses Teilstaats kannst du einen neuen Namen für das Gebiet beantragen. Der Kanzler entscheidet darüber; die Antwort erhältst du per Direktnachricht auf Discord.",
           "resetName": "Heutigen Namen wiederherstellen", "save": "Speichern", "saved": "Gespeichert.", "saveError": "Speichern fehlgeschlagen.",
           "send": "Antrag senden", "setName": "Namen festlegen", "shareArea": "Anteil an der Fläche des Reiches",
           "sharePop": "Anteil an der Bevölkerung des Reiches", "sheetClose": "Zur Karte",
           "source": "Einwohner: Eurostat, Stand {j}. Grenzen: © EuroGeographics (NUTS 2021).", "state": "Teilstaat", "reich": "Reichsgebiete", "und": "und", "vertreten": "vertreten durch",
           "today": "heute", "todayName": "Heutiger Name", "toolPaint": "Malen", "toolPan": "Verschieben", "toolPick": "Pipette",
           "unassigned": "Kein Teilstaat", "undo": "Rückgängig", "vacant": "unbesetzt (kein Landesherr mit der Rolle „{f}“)",
           "pending": "Dein Antrag vom {d} auf „{n}“ liegt dem Kanzler vor.", "accepted": "Dein Antrag vom {d} auf „{n}“ wurde angenommen.",
           "rejected": "Dein Antrag vom {d} auf „{n}“ wurde abgelehnt."},
    "en": {"answer": "Answer", "area": "Area", "capital": "Capital", "loading": "Loading map …", "loadingRetry": "Loading map … (attempt {n})",
           "retry": "Try again",
           "capitalPrompt": "Name of the capital of “{state}”", "toolCapital": "Capital",
           "capitalHint": "Capital: with a state selected, click the map to place its capital there (the name comes from the nearest place or is asked for).", "changes": "{n} unsaved changes", "chooseState": "Choose a state",
           "confirmDelete": "Delete the state “{name}”? {n} regions will then no longer belong to any state.",
           "conflict": "{name} has saved a newer version in the meantime. Please reload the page and apply your changes again.",
           "countryPick": "– choose a country –", "density": "Population density", "edit": "Edit", "editState": "Edit state",
           "infoError": "The details could not be loaded.", "inhabitants": "inhabitants",
           "kanzlerIntro": "As Chancellor you set this region's name in the role-play directly. Leave it empty or reset it to restore today's name.",
           "kanzlerNote": "The state has no ruler of its own; the Chancellor administers it on behalf of the Sovereign.",
           "leave": "There are unsaved changes.", "loadError": "The map could not be loaded.", "login": "Sign in with Discord",
           "loginHint": "Rulers of this state can request a new name for the region after signing in.",
           "more": "States and saving", "nameEmpty": "Please enter a name.", "nameField": "Name in the role-play",
           "nameSaved": "Name saved.", "nameTaken": "Another state already has this name.", "newName": "New name",
           "newState": "New state", "noChanges": "No changes", "noData": "no data",
           "noFaction": "no ruler on record", "noKanzler": "The office of Chancellor is vacant.", "noState": "not assigned to a state",
           "notFound": "No region found.", "notReich": "Not part of the Empire", "perKm2": "inhabitants per km²", "population": "Population",
           "reason": "Reason", "regent": "Ruler", "regionCount": "Regions", "renameBtn": "Request a new name",
           "renameH": "Name in the role-play",
           "renameIntro": "As ruler of this state you can request a new name for the region. The Chancellor decides; you will receive the answer as a direct message on Discord.",
           "resetName": "Restore today's name", "save": "Save", "saved": "Saved.", "saveError": "Saving failed.",
           "send": "Send request", "setName": "Set name", "shareArea": "Share of the Empire's area",
           "sharePop": "Share of the Empire's population", "sheetClose": "To the map",
           "source": "Population: Eurostat, {j}. Boundaries: © EuroGeographics (NUTS 2021).", "state": "State", "reich": "Imperial territories", "und": "and", "vertreten": "represented by",
           "today": "today", "todayName": "Today's name", "toolPaint": "Paint", "toolPan": "Move", "toolPick": "Eyedropper",
           "unassigned": "No state", "undo": "Undo", "vacant": "vacant (no Landesherr with the role “{f}”)",
           "pending": "Your request of {d} for “{n}” is with the Chancellor.", "accepted": "Your request of {d} for “{n}” was accepted.",
           "rejected": "Your request of {d} for “{n}” was rejected."},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS karte_versionen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, stand TEXT NOT NULL, bemerkung TEXT NOT NULL DEFAULT '',
    autor_id TEXT, autor_name TEXT NOT NULL, zeit INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS karte_antraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, gebiet TEXT NOT NULL, staat TEXT NOT NULL, neu TEXT NOT NULL, begruendung TEXT NOT NULL,
    nutzer_id TEXT NOT NULL, nutzer_name TEXT NOT NULL, zeit INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen', antwort TEXT NOT NULL DEFAULT '', entschieden_von TEXT, entschieden_zeit INTEGER
);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM karte_versionen").fetchone():
        with open(os.path.join(DATEN, "startstand.json"), encoding="utf-8") as fh:
            stand = pruefen(json.load(fh))
        con.execute("INSERT INTO karte_versionen (stand, bemerkung, autor_name, zeit) VALUES (?, ?, ?, ?)",
                    (json.dumps(stand, ensure_ascii=False), "Startstand: aus der alten Karte rekonstruiert (02.11.2026)", "System", int(time.time())))
    con.commit()


def aktuell(con):
    row = con.execute("SELECT * FROM karte_versionen ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row, stand=json.loads(row["stand"]))


def neue_version(con, stand, bemerkung, konto):
    c = con.execute("INSERT INTO karte_versionen (stand, bemerkung, autor_id, autor_name, zeit) VALUES (?, ?, ?, ?, ?)",
                    (json.dumps(stand, ensure_ascii=False), bemerkung[:300], konto["id"], konto["name"], int(time.time())))
    con.commit()
    karte_bild.neu_erzeugen(GEO, stand)
    return c.lastrowid


class Ungueltig(Exception):
    pass


def pruefen(stand):
    if not isinstance(stand, dict) or not isinstance(stand.get("staaten"), list) or len(stand["staaten"]) > 200:
        raise Ungueltig("Ungültiger Stand.")
    staaten, ids, namen = [], set(), set()
    for s in stand["staaten"]:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not re.match(r"^s[0-9]{1,5}$", s["id"]) or s["id"] in ids:
            raise Ungueltig("Ungültige Kennung eines Teilstaats.")
        name = str(s.get("name", "")).strip()[:120]
        if not name or name.lower() in namen:
            raise Ungueltig("Jeder Teilstaat braucht einen eigenen Namen.")
        for f in ("farbe", "farbe2"):
            if not re.match(r"^#[0-9a-fA-F]{6}$", str(s.get(f, ""))):
                raise Ungueltig("Ungültige Farbe.")
        fr = str(s.get("fraktion") or "")
        if fr and not re.match(r"^[0-9]{5,22}$", fr):
            raise Ungueltig("Ungültige Fraktionsrolle.")
        ids.add(s["id"]); namen.add(name.lower())
        eintrag = {"id": s["id"], "name": name, "farbe": s["farbe"].lower(), "muster": s.get("muster") if s.get("muster") in MUSTER else "voll",
                   "farbe2": s["farbe2"].lower(), "fraktion": fr}
        h = s.get("hauptstadt")
        if h:   # Hauptstadt: Name und Lage auf der Karte (Weltkoordinaten)
            x0, y0, x1, y1 = GEO["welt"]   # Kartenfläche in Weltkoordinaten
            if not isinstance(h, dict) or not all(isinstance(h.get(k), (int, float)) and not isinstance(h.get(k), bool) for k in ("x", "y")) \
                    or not (x0 <= h["x"] <= x1 and y0 <= h["y"] <= y1):
                raise Ungueltig("Ungültige Hauptstadt.")
            hn = str(h.get("name", "")).strip()[:80]
            if hn:
                eintrag["hauptstadt"] = {"name": hn, "x": round(float(h["x"]), 1), "y": round(float(h["y"]), 1)}
        staaten.append(eintrag)
    gebiete = {}
    for g, sid in (stand.get("gebiete") or {}).items():
        if g not in GEO["gebiete"] or sid not in ids:
            raise Ungueltig("Ungültige Zuordnung eines Gebiets.")
        gebiete[g] = sid
    gnamen = {}
    for g, n in (stand.get("namen") or {}).items():
        n = str(n).strip()[:80]
        if g in GEO["gebiete"] and n and n != GEO["gebiete"][g]["n"]:
            gnamen[g] = n
    return {"staaten": staaten, "gebiete": dict(sorted(gebiete.items())), "namen": dict(sorted(gnamen.items()))}


# ---------- Hilfen ----------
def _lang(request):
    return "en" if request.path.startswith("/en/") else "de"


def _datum(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m.%Y")


def _ist_kanzler(k):
    return bool(k) and ROLLE_KANZLER in k["rollen"]


def _regent_von(k, stand):
    """IDs der Teilstaaten, deren Regent das Konto ist (Landesherr + Fraktionsrolle)."""
    if not k or ROLLE_LANDESHERR not in k["rollen"]:
        return []
    fr = fraktionen(k["rollen"], stand["staaten"])
    return [s["id"] for s in stand["staaten"] if s["fraktion"] and s["fraktion"] in fr]


def _swatch(s, groesse=18):
    if s["muster"] == "voll":
        return f'<svg class="karte-swatch" viewBox="0 0 18 18" width="{groesse}" height="{groesse}" aria-hidden="true"><rect width="18" height="18" fill="{s["farbe"]}"/></svg>'
    pid = "lsw-" + s["id"]
    if s["muster"] == "streifen":
        koerper = f'<rect width="6" height="6" fill="{s["farbe"]}"/><rect width="2.1" height="6" fill="{s["farbe2"]}"/>'
    elif s["muster"] == "karo":
        koerper = f'<rect width="6" height="6" fill="{s["farbe"]}"/><rect width="3" height="3" fill="{s["farbe2"]}"/><rect x="3" y="3" width="3" height="3" fill="{s["farbe2"]}"/>'
    else:
        koerper = f'<rect width="6" height="6" fill="{s["farbe"]}"/><circle cx="3" cy="3" r="1.32" fill="{s["farbe2"]}"/>'
    rot = ' patternTransform="rotate(45)"' if s["muster"] == "streifen" else ""
    return (f'<svg class="karte-swatch" viewBox="0 0 18 18" width="{groesse}" height="{groesse}" aria-hidden="true"><defs>'
            f'<pattern id="{pid}" width="6" height="6" patternUnits="userSpaceOnUse"{rot}>{koerper}</pattern></defs>'
            f'<rect width="18" height="18" fill="url(#{pid})"/></svg>')


def _zahlen(stand):
    n, ew = {}, {}
    for g, sid in stand["gebiete"].items():
        n[sid] = n.get(sid, 0) + 1
        if g in BEV:
            ew[sid] = ew.get(sid, 0) + BEV[g][0]
    return n, ew


# ---------- Seite ----------
def seite_html(request, modus, konto, csrf, version, rollen):
    lang = _lang(request)
    en = lang == "en"
    L = (lambda de, e: e if en else de)
    prefix = "/en" if en else ""
    stand = version["stand"]
    cfg = {"i18n": T[lang], "lang": lang, "modus": modus, "stand": stand, "basis": version["id"], "version": None,
           "geo": _geo_url("geo"), "geoAlt": f"/karte/geo.json?v={_geo_version()}",
           "geoFein": _geo_url("geo_fein"), "geoFeinAlt": f"/karte/geo_fein.json?v={_geo_version()}", "bild": "/karte/karte.png", "info": "/karte/info.json", "speichern": "/karte/speichern", "antrag": "/karte/antrag",
           "gebietsname": "/karte/gebietsname", "anmelden": "/anmelden/?weiter=" + request.path, "csrf": csrf or "",
           "laender": GEO["laender"]}
    cfg_json = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    titel = L("Die Reichskarte", "The Imperial Map")
    krumen = f'<li><a href="{prefix}/">{L("Hauptseite", "Home")}</a></li>'
    if modus == "bearbeiten":
        krumen += f'<li><a href="{prefix}/karte/">{titel}</a></li><li><span aria-current="page">{L("Bearbeiten", "Edit")}</span></li>'
    else:
        krumen += f'<li><span aria-current="page">{titel}</span></li>'
    n_staaten, ew = _zahlen(stand)
    gesamt_ew = sum(ew.values())
    lead = L(f"Das Hoheitsgebiet des Imperium Germanicum mit seinen {sum(1 for t in stand['staaten'] if t['name'] != REICHSGEBIETE)} Teilstaaten: {len(stand['gebiete']):,} Gebiete und rund "
             f"{round(gesamt_ew / 1e6):,} Millionen Einwohner. Ein Klick auf ein Gebiet nennt Teilstaat, Regent, Einwohner und Fläche.".replace(",", "."),
             f"The territory of the Imperium Germanicum with its {sum(1 for t in stand['staaten'] if t['name'] != REICHSGEBIETE)} constituent states: {len(stand['gebiete']):,} regions and about "
             f"{round(gesamt_ew / 1e6):,} million inhabitants. Click a region to see its state, ruler, population and area.")
    kopf = (f'<div class="page-head"><div class="wrap"><nav class="breadcrumb" aria-label="{L("Brotkrumen", "Breadcrumb")}"><ol>{krumen}</ol></nav>'
            f'<span class="eyebrow">{L("Hoheitsgebiet", "Territory")}</span><h1>{titel}</h1><p class="wiki-intro rt-lead">{esc(lead)}</p></div></div>')
    leiste = (f'<div class="karte-leiste"><div class="karte-zoom">'
              f'<button type="button" class="btn btn-line" data-zoom="in" aria-label="{L("Vergrößern", "Zoom in")}">+</button>'
              f'<button type="button" class="btn btn-line" data-zoom="out" aria-label="{L("Verkleinern", "Zoom out")}">−</button>'
              f'<button type="button" class="btn btn-line" data-zoom="fit">{L("Ganz zeigen", "Fit")}</button></div>'
              f'<form class="karte-suche field" role="search"><label class="sr-only" for="karte-suche">{L("Gebiet suchen", "Search region")}</label>'
              f'<input id="karte-suche" type="search" list="karte-gebiete" autocomplete="off" placeholder="{L("Gebiet suchen, z. B. Heidelberg", "Search a region, e.g. Heidelberg")}">'
              f'<datalist id="karte-gebiete"></datalist></form>'
              f'<label class="field-check karte-grenzen"><input type="checkbox" data-grenzen> {L("Gebietsgrenzen", "Region borders")}</label>'
              f'<label class="field-check karte-grenzen"><input type="checkbox" data-ebene="bauwerke" checked> {L("Gebäude", "Buildings")}</label></div>')
    wurzel = (f'<div class="karte karte-cols" data-karte>{leiste}<div class="karte-buehne">'
              f'<div class="karte-flaeche" tabindex="0" aria-label="{titel}"><p class="karte-laden">{L("Karte wird geladen …", "Loading map …")}</p>'
              f'<noscript><img src="/karte/karte.png" alt="{titel}"></noscript></div>'
              f'<div class="karte-info" aria-live="polite"></div></div>'
              f'<p class="karte-quelle">{L("Stand", "As of")} {_datum(version["zeit"])}. '
              f'{L("Grenzen: © EuroGeographics (NUTS 2021), Einwohner: Eurostat, Gewässer und Länder: Natural Earth", "Boundaries: © EuroGeographics (NUTS 2021), population: Eurostat, water and countries: Natural Earth")}'
              f'.</p></div>')

    if modus == "bearbeiten":
        rollen_opt = f'<option value="">{L("– keine (verwaltet der Kanzler) –", "– none (administered by the Chancellor) –")}</option>' + "".join(
            f'<option value="{esc(r["id"])}">{esc(r["name"])}</option>' for r in rollen)
        aside = (f'<aside class="karte-aside karte-editor wiki-aside">'
                 f'<div class="aside-box"><p><strong>{L("Werkzeug", "Tool")}</strong></p><div class="karte-aktionen">'
                 f'<button type="button" class="btn btn-line btn-small" data-werkzeug="malen" aria-pressed="true">{T[lang]["toolPaint"]}</button>'
                 f'<button type="button" class="btn btn-line btn-small" data-werkzeug="pipette" aria-pressed="false">{T[lang]["toolPick"]}</button>'
                 f'<button type="button" class="btn btn-line btn-small" data-werkzeug="hauptstadt" aria-pressed="false">{T[lang]["toolCapital"]}</button>'
                 f'<button type="button" class="btn btn-line btn-small" data-werkzeug="verschieben" aria-pressed="false">{T[lang]["toolPan"]}</button></div>'
                 f'<p class="karte-feldhinweis">{L("Malen: klicken oder ziehen weist Gebiete dem gewählten Teilstaat zu; mit Umschalt entfernen. Leertaste halten: verschieben.", "Paint: click or drag assigns regions to the selected state; hold Shift to remove. Hold Space to move.")}</p>'
                 f'<p class="karte-feldhinweis">{T[lang]["capitalHint"]}</p>'
                 f'<div class="karte-verlauf"><button type="button" class="btn btn-line btn-small" data-aktion="undo" disabled>↶ {T[lang]["undo"]}</button>'
                 f'<button type="button" class="btn btn-line btn-small" data-aktion="redo" disabled>↷</button></div></div>'
                 f'<nav class="aside-nav"><h2 class="wiki-aside-h">{L("Teilstaaten", "States")}</h2><ul class="karte-legende karte-staaten" data-staaten></ul></nav>'
                 f'<button type="button" class="btn btn-line btn-small" data-aktion="neu">+ {T[lang]["newState"]}</button>'
                 f'<div class="aside-nav"><h2 class="wiki-aside-h">{L("Ganzes Land", "Whole country")}</h2><div class="field"><label class="sr-only" for="karte-land">{L("Land", "Country")}</label>'
                 f'<select id="karte-land" data-land></select></div><button type="button" class="btn btn-line btn-small" data-aktion="land">{L("dem gewählten Teilstaat zuweisen", "assign to selected state")}</button></div>'
                 f'<div class="aside-box"><p><strong>{L("Speichern", "Save")}</strong> <span class="karte-stand" data-stand></span></p>'
                 f'<div class="field"><label for="karte-bemerkung">{L("Bemerkung", "Note")}</label><input id="karte-bemerkung" data-bemerkung maxlength="300"></div>'
                 f'<div data-meldung></div><div class="karte-aktionen"><button type="button" class="btn btn-navy" data-aktion="speichern" disabled>{T[lang]["save"]}</button>'
                 f'<a class="btn btn-line" href="{prefix}/karte/" data-aktion="verwerfen">{L("Zur Ansicht", "To the view")}</a></div></div></aside>')
        dialoge = (f'<dialog class="dialog karte-dialog" data-dialog><form method="dialog" class="form">'
                   f'<h2 data-dialog-titel></h2><p class="form-status err" data-dialog-fehler hidden></p>'
                   f'<div class="field"><label for="ks-name">{L("Name", "Name")}</label><input id="ks-name" maxlength="120"></div>'
                   f'<div class="karte-farben"><div class="field"><label for="ks-farbe">{L("Farbe", "Colour")}</label><input id="ks-farbe" type="color"></div>'
                   f'<div class="field"><label for="ks-muster">{L("Muster", "Pattern")}</label><select id="ks-muster">'
                   f'<option value="voll">{L("einfarbig", "solid")}</option><option value="streifen">{L("Streifen", "stripes")}</option>'
                   f'<option value="karo">{L("Karo", "checks")}</option><option value="punkte">{L("Punkte", "dots")}</option></select></div>'
                   f'<div class="field" data-farbe2><label for="ks-farbe2">{L("Zweite Farbe", "Second colour")}</label><input id="ks-farbe2" type="color"></div>'
                   f'<div class="field karte-vorschau-feld"><label>{L("Vorschau", "Preview")}</label><div data-vorschau></div></div></div>'
                   f'<div class="field"><label for="ks-fraktion">{L("Fraktionsrolle (Regent: Landesherr mit dieser Rolle)", "Faction role (ruler: Landesherr with this role)")}</label>'
                   f'<select id="ks-fraktion">{rollen_opt}</select></div>'
                   f'<div class="field"><label for="ks-hauptstadt">{T[lang]["capital"]}</label><input id="ks-hauptstadt" maxlength="80" list="ks-orte" autocomplete="off">'
                   f'<datalist id="ks-orte"></datalist><p class="karte-feldhinweis">{L("Ein Ortsname aus der Liste setzt die Hauptstadt an dessen Lage; sonst mit dem Werkzeug „Hauptstadt“ auf der Karte platzieren.", "A place name from the list puts the capital at its location; otherwise place it on the map with the “Capital” tool.")}</p></div>'
                   f'<div class="dialog-actions"><button class="btn btn-navy" value="ok">{L("Übernehmen", "Apply")}</button>'
                   f'<button class="btn btn-line" value="cancel" formnovalidate>{L("Abbrechen", "Cancel")}</button>'
                   f'<button type="button" class="btn btn-line karte-loeschen" data-aktion="loeschen">{L("Löschen", "Delete")}</button></div></form></dialog>')
    else:
        staaten = sorted(stand["staaten"], key=lambda s: s["name"])
        legende = "".join(
            f'<li><button type="button" class="karte-legende-item" data-staat="{s["id"]}" aria-pressed="false">{_swatch(s)}'
            f'<span class="karte-legende-name">{esc(s["name"])}</span><span class="karte-legende-zahl">{n_staaten.get(s["id"], 0)}</span></button></li>'
            for s in staaten)
        aktionen = ""
        if konto and konto["admin"]:
            aktionen += f'<a class="btn btn-line btn-small" href="{prefix}/karte/bearbeiten/">{L("Karte bearbeiten", "Edit map")}</a>'
        if _ist_kanzler(konto):
            offen = request.app["db"].execute("SELECT COUNT(*) FROM karte_antraege WHERE status = 'offen'").fetchone()[0]
            aktionen += f'<a class="btn btn-line btn-small" href="/karte/antraege/">{L("Anträge", "Requests")} ({offen})</a>'
        aside = (f'<aside class="karte-aside wiki-aside"><nav class="aside-nav" aria-label="{L("Teilstaaten", "States")}">'
                 f'<h2>{L("Die Teilstaaten", "The states")}</h2><ul class="karte-legende">{legende}</ul></nav>'
                 + (f'<div class="karte-aktionen">{aktionen}</div>' if aktionen else "")
                 + f'<div class="aside-box"><p>{L("Ein Klick auf einen Teilstaat hebt ihn hervor; ein Klick auf ein Gebiet nennt Regent, Einwohner und Fläche.", "Click a state to highlight it; click a region to see its ruler, population and area.")}</p></div></aside>')
        dialoge = (f'<dialog class="dialog karte-gebiet" data-gebiet aria-labelledby="karte-gebiet-titel"><div data-gebiet-inhalt tabindex="-1"></div>'
                   f'<div class="dialog-actions"><button type="button" class="btn btn-line" data-gebiet-zu>{L("Schließen", "Close")}</button></div></dialog>')
    inhalt = (f'{kopf}<div class="section wiki"><div class="wrap with-aside wiki-cols"><div class="wiki-main">{wurzel}</div>{aside}</div></div>'
              f'{dialoge}<script type="application/json" id="karte-cfg">{cfg_json}</script>')
    v = int(time.time() // 86400)
    head = f'<link rel="stylesheet" href="/assets/css/wiki.css?v={v}">\n<script src="/assets/js/karte.js?v={v}" defer></script>'
    if modus == "bearbeiten":
        head += '\n<meta name="robots" content="noindex">'
    return seite(titel + (" – " + L("Bearbeiten", "Edit") if modus == "bearbeiten" else ""), inhalt, kopf=head, body_klasse="wiki-page karte-cols",   # Farben (Land) auch für Seitenleiste und Fenster
                 konto=konto, csrf=csrf, pfad=request.path, lang=lang, canonical=prefix + "/karte/" + ("bearbeiten/" if modus == "bearbeiten" else ""))


async def anzeige(request):
    k = await anmeldung.konto(request)
    return web.Response(text=seite_html(request, "anzeigen", k, request.get("csrf"), aktuell(request.app["db"]), []), content_type="text/html")


@anmeldung.angemeldet(lambda k: k["admin"], "Die Karte bearbeiten dürfen nur Administratoren unseres Discord-Servers.")
async def editor(request):
    rollen = await request.app["discord"].rollen_liste()
    return web.Response(text=seite_html(request, "bearbeiten", request["konto"], request["csrf"], aktuell(request.app["db"]), rollen),
                        content_type="text/html", headers={"Cache-Control": "no-store"})


def _geo_version():
    return int(max(os.path.getmtime(os.path.join(DATEN, n)) for n in ("geo.json", "geo_fein.json")))


STATISCH = "/var/lib/imperium-karte"   # von nginx ausgeliefert (location /karte-daten/), unabhängig vom Dienst


def _gz_schreiben(quelle, ziel):
    """gzip -9 nach ziel (atomar)."""
    with open(quelle, "rb") as fh, gzip.open(ziel + ".tmp", "wb", compresslevel=9) as out:
        shutil.copyfileobj(fh, out)
    os.replace(ziel + ".tmp", ziel)


def _vorverdichtet(name):
    """Pfad der vorverdichteten Geodatei (cache/<name>.gz) oder None, solange sie fehlt oder veraltet ist (dann liefert die Route die Rohdatei,
    statt im Request 16 MB zu verdichten und den Dienst zu blockieren)."""
    quelle = os.path.join(DATEN, name)
    ziel = os.path.join(DATEN, "cache", name + ".gz")
    return ziel if os.path.exists(ziel) and os.path.getmtime(ziel) >= os.path.getmtime(quelle) else None


def _geo_url(basis):
    """Adresse der Geodatei: statisch über nginx (mit Version im Namen, unveränderlich), solange die Dateien da sind, sonst über die Route des Dienstes."""
    name = basis + ".json"
    v = int(os.path.getmtime(os.path.join(DATEN, name)))
    if all(os.path.exists(f"{STATISCH}/{basis}-{v}.json{e}") for e in ("", ".gz")):
        return f"/karte-daten/{basis}-{v}.json"
    return f"/karte/{name}?v={_geo_version()}"


def geo_vorbereiten():
    """Verdichtet die Geodateien und legt sie versioniert für nginx ab (läuft im Hintergrund, blockiert den Dienst nicht)."""
    os.makedirs(os.path.join(DATEN, "cache"), exist_ok=True)
    os.makedirs(STATISCH, mode=0o755, exist_ok=True)
    os.chmod(STATISCH, 0o755)
    for name in ("geo.json", "geo_fein.json"):
        quelle = os.path.join(DATEN, name)
        basis, v = name[:-5], int(os.path.getmtime(quelle))
        cache = os.path.join(DATEN, "cache", name + ".gz")
        if not os.path.exists(cache) or os.path.getmtime(cache) < os.path.getmtime(quelle):
            _gz_schreiben(quelle, cache)
        ziel = f"{STATISCH}/{basis}-{v}.json"
        if not os.path.exists(ziel + ".gz"):
            shutil.copyfile(cache, ziel + ".gz.tmp")
            os.replace(ziel + ".gz.tmp", ziel + ".gz")
        if not os.path.exists(ziel):
            shutil.copyfile(quelle, ziel + ".tmp")
            os.replace(ziel + ".tmp", ziel)
        for f in os.listdir(STATISCH):   # alte Versionen entfernen
            if re.fullmatch(re.escape(basis) + r"-\d+\.json(\.gz)?", f) and not f.startswith(f"{basis}-{v}.json"):
                os.remove(os.path.join(STATISCH, f))
        for e in ("", ".gz"):
            os.chmod(ziel + e, 0o644)
        log.info("Geodatei %s (Version %s) bereit", name, v)


async def _geo_hintergrund(app):
    async def lauf():
        try:
            await asyncio.get_running_loop().run_in_executor(None, geo_vorbereiten)
        except Exception:
            log.exception("Geodateien konnten nicht vorbereitet werden (die Route des Dienstes liefert sie weiter)")
    app["geo_task"] = asyncio.get_running_loop().create_task(lauf())


def _geo_antwort(request, name):
    # Die Adresse trägt die Version (?v=…), deshalb darf der Browser die Datei lange behalten
    kopf = {"Cache-Control": "public, max-age=31536000, immutable", "Vary": "Accept-Encoding", "Content-Type": "application/json"}
    gz = _vorverdichtet(name)
    if gz and "gzip" in request.headers.get("Accept-Encoding", ""):
        kopf["Content-Encoding"] = "gzip"
        return web.FileResponse(gz, headers=kopf)
    return web.FileResponse(os.path.join(DATEN, name), headers=kopf)


async def geo_fein_json(request):
    return _geo_antwort(request, "geo_fein.json")


async def geo_json(request):
    return _geo_antwort(request, "geo.json")


async def daten_json(request):
    return web.json_response(aktuell(request.app["db"])["stand"], headers={"Cache-Control": "public, max-age=60"})


async def info_json(request):
    dc = request.app["discord"]
    k = await anmeldung.konto(request)
    stand = aktuell(request.app["db"])["stand"]
    mitglieder = await dc.mitglieder()
    titel_rollen = await dc.rollen_der_gruppe("Adelstitel")
    rollen = {r["id"]: r["name"] for r in await dc.rollen_liste()}

    rang = {r["id"]: i for i, r in enumerate(await dc.rollen_liste())}   # oberste Rolle zuerst

    def person(m, fraktion=None):
        # nur der höchste Titel; Zusatzämter nur zusammen mit der Fraktionsrolle
        titel = sorted((r for r in m["rollen"] if r in titel_rollen and r in rollen), key=lambda r: rang.get(r, 9999))[:1]
        aemter = sorted((r for r in m["rollen"] if fraktion and r in ROLLEN_AEMTER and r in rollen),
                        key=lambda r: rang.get(r, 9999))
        return {"name": m["name"], "titel": [rollen[r] for r in titel], "aemter": [rollen[r] for r in aemter]}
    kanzler = [person(m) for m in mitglieder if ROLLE_KANZLER in m["rollen"]]
    souveraen = [{"name": m["name"], "titel": [], "aemter": []} for m in mitglieder if ROLLE_SOUVERAEN in m["rollen"]]
    regenten = {}
    for s in stand["staaten"]:
        art = "reich" if s["name"] == REICHSGEBIETE else "kanzler"
        if art == "kanzler" and s["fraktion"]:
            # Regent: Fraktionsrolle plus Landesherr oder eines der Zusatzämter (Gouverneur, Vizekönig …)
            personen = [person(m, s["fraktion"]) for m in mitglieder
                        if s["fraktion"] in fraktionen(m["rollen"], stand["staaten"])
                        and (ROLLE_LANDESHERR in m["rollen"] or any(r in ROLLEN_AEMTER for r in m["rollen"]))]
            if personen:
                regenten[s["id"]] = {"art": "landesherr", "fraktion": rollen.get(s["fraktion"], ""), "personen": personen}
                continue
        # ohne eingesetzten Regenten: der Souverän, vertreten durch den Kanzler
        regenten[s["id"]] = {"art": art, "personen": souveraen, "vertreter": [{"name": p["name"]} for p in kanzler]}
    ich = None
    if k:
        antraege = {}
        for a in request.app["db"].execute("SELECT * FROM karte_antraege WHERE nutzer_id = ? ORDER BY id", (k["id"],)):
            antraege[a["gebiet"]] = {"status": a["status"], "neu": a["neu"], "zeit": a["zeit"], "antwort": a["antwort"]}
        ich = {"kanzler": _ist_kanzler(k), "regent_von": _regent_von(k, stand), "antraege": antraege}
    return web.json_response({"bev": BEV, "regenten": regenten, "ich": ich, "angemeldet": bool(k)}, headers={"Cache-Control": "no-store"})


async def _json_anfrage(request, pruefung=None):
    """Angemeldetes Konto + JSON-Daten mit gültigem csrf, sonst eine fertige Fehlerantwort."""
    k = await anmeldung.konto(request)
    if not k or (pruefung and not pruefung(k)):
        return None, None, web.json_response({"ok": False, "fehler": "Nicht angemeldet oder keine Berechtigung."}, status=403)
    try:
        daten = await request.json()
    except ValueError:
        return None, None, web.json_response({"ok": False, "fehler": "Ungültige Anfrage."}, status=400)
    if not secrets.compare_digest(str(daten.get("csrf", "")), request["csrf"]):
        return None, None, web.json_response({"ok": False, "fehler": "Sitzung abgelaufen. Bitte lade die Seite neu."}, status=403)
    return k, daten, None


async def speichern(request):
    k, daten, fehler = await _json_anfrage(request, lambda k: k["admin"])
    if fehler is not None:   # aiohttp-Antworten sind als Mapping „leer“ und damit falsy
        return fehler
    con = request.app["db"]
    cur = aktuell(con)
    if daten.get("basis") != cur["id"]:
        return web.json_response({"ok": False, "konflikt": True, "name": cur["autor_name"]})
    try:
        stand = pruefen(daten.get("stand"))
    except Ungueltig as e:
        return web.json_response({"ok": False, "fehler": str(e)})
    return web.json_response({"ok": True, "version": neue_version(con, stand, str(daten.get("bemerkung") or ""), k)})


async def gebietsname(request):
    k, daten, fehler = await _json_anfrage(request, _ist_kanzler)
    if fehler is not None:   # aiohttp-Antworten sind als Mapping „leer“ und damit falsy
        return fehler
    gebiet, name = str(daten.get("gebiet", "")), str(daten.get("name") or "").strip()[:80]
    if gebiet not in GEO["gebiete"]:
        return web.json_response({"ok": False, "fehler": "Unbekanntes Gebiet."})
    con = request.app["db"]
    stand = aktuell(con)["stand"]
    namen = dict(stand["namen"])
    if name and name != GEO["gebiete"][gebiet]["n"]:
        namen[gebiet] = name
    else:
        namen.pop(gebiet, None)
    stand["namen"] = dict(sorted(namen.items()))
    neue_version(con, stand, f"Gebietsname {GEO['gebiete'][gebiet]['n']}: {name or '(heutiger Name)'}", k)
    return web.json_response({"ok": True, "namen": stand["namen"]})


async def antrag(request):
    k, daten, fehler = await _json_anfrage(request)
    if fehler is not None:   # aiohttp-Antworten sind als Mapping „leer“ und damit falsy
        return fehler
    gebiet = str(daten.get("gebiet", ""))
    neu = str(daten.get("neu") or "").strip()[:80]
    grund = str(daten.get("begruendung") or "").strip()[:1000]
    con = request.app["db"]
    stand = aktuell(con)["stand"]
    sid = stand["gebiete"].get(gebiet)
    if not sid or sid not in _regent_von(k, stand):
        return web.json_response({"ok": False, "fehler": "Nur der Regent dieses Teilstaats kann einen Namen beantragen."}, status=403)
    if not neu or not grund:
        return web.json_response({"ok": False, "fehler": "Bitte neuen Namen und Begründung angeben."})
    if con.execute("SELECT 1 FROM karte_antraege WHERE gebiet = ? AND status = 'offen'", (gebiet,)).fetchone():
        return web.json_response({"ok": False, "fehler": "Für dieses Gebiet liegt dem Kanzler bereits ein Antrag vor."})
    jetzt = int(time.time())
    con.execute("INSERT INTO karte_antraege (gebiet, staat, neu, begruendung, nutzer_id, nutzer_name, zeit) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (gebiet, sid, neu, grund, k["id"], k["name"], jetzt))
    con.commit()
    staat = next(s["name"] for s in stand["staaten"] if s["id"] == sid)
    alt = stand["namen"].get(gebiet, GEO["gebiete"][gebiet]["n"])
    text = (f"**Antrag auf einen Gebietsnamen** ({staat})\n{k['name']} beantragt für „{alt}“ den Namen **„{neu}“**.\n"
            f"> {grund[:600]}\n\nEntscheiden: {config.SITE_URL}/karte/antraege/")
    dc = request.app["discord"]
    for m in await dc.mitglieder():
        if ROLLE_KANZLER in m["rollen"]:
            await dc.dm(m["id"], text)
    return web.json_response({"ok": True, "antrag": {"status": "offen", "neu": neu, "zeit": jetzt, "antwort": ""}})


@anmeldung.angemeldet(_ist_kanzler, "Über Anträge auf Gebietsnamen entscheidet der Kanzler.")
async def antraege_seite(request):
    con = request.app["db"]
    stand = aktuell(con)["stand"]
    staaten = {s["id"]: s["name"] for s in stand["staaten"]}
    zeilen = []
    for a in con.execute("SELECT * FROM karte_antraege ORDER BY status = 'offen' DESC, id DESC LIMIT 100"):
        g = GEO["gebiete"].get(a["gebiet"], {"n": a["gebiet"]})
        jetzt_name = stand["namen"].get(a["gebiet"], g["n"])
        if a["status"] == "offen":
            aktion = (f'<form method="post" action="/karte/antraege/entscheiden" class="form" style="gap:10px">'
                      f'<input type="hidden" name="csrf" value="{esc(request["csrf"])}"><input type="hidden" name="id" value="{a["id"]}">'
                      f'<div class="field" style="margin:0"><label for="antwort-{a["id"]}">Antwort (bei Ablehnung nötig)</label>'
                      f'<input id="antwort-{a["id"]}" name="antwort" maxlength="500"></div><div class="dialog-actions">'
                      f'<button class="btn btn-navy btn-small" name="entscheidung" value="angenommen">Annehmen</button>'
                      f'<button class="btn btn-line btn-small" name="entscheidung" value="abgelehnt">Ablehnen</button></div></form>')
        else:
            aktion = f'<strong>{"Angenommen" if a["status"] == "angenommen" else "Abgelehnt"}</strong> am {_datum(a["entschieden_zeit"])}' + (
                f'<br><span class="karte-feldhinweis">{esc(a["antwort"])}</span>' if a["antwort"] else "")
        zeilen.append(f'<tr><td>{_datum(a["zeit"])}</td><td><strong>{esc(jetzt_name)}</strong> → <strong>„{esc(a["neu"])}“</strong><br>'
                      f'<span class="karte-feldhinweis">{esc(staaten.get(a["staat"], ""))} · {esc(g["n"])} · beantragt von {esc(a["nutzer_name"])}</span>'
                      f'<p style="margin:8px 0 0">{esc(a["begruendung"])}</p></td><td>{aktion}</td></tr>')
    tabelle = ('<div class="table-scroll"><table class="styles-table"><thead><tr><th>Eingang</th><th>Antrag</th><th>Entscheidung</th></tr></thead><tbody>'
               + "".join(zeilen) + "</tbody></table></div>") if zeilen else '<p class="callout">Es liegen keine Anträge vor.</p>'
    meldung = {"ok": '<div class="form-status ok" role="status">Entscheidung gespeichert; der Antragsteller wurde per Direktnachricht benachrichtigt.</div>',
               "grund": '<div class="form-status err" role="status">Bitte begründe die Ablehnung in der Antwort.</div>'}.get(request.query.get("m"), "")
    inhalt = ('<div class="page-head"><div class="wrap"><nav class="breadcrumb" aria-label="Brotkrumen"><ol><li><a href="/">Hauptseite</a></li>'
              '<li><a href="/karte/">Die Reichskarte</a></li><li><span aria-current="page">Anträge</span></li></ol></nav>'
              '<span class="eyebrow">Kanzler</span><h1>Anträge auf Gebietsnamen</h1>'
              '<p class="wiki-intro rt-lead">Regenten beantragen hier neue Namen für Gebiete ihres Teilstaats. Angenommene Namen erscheinen sofort auf der Karte.</p></div></div>'
              f'<div class="section"><div class="wrap">{meldung}{tabelle}</div></div>')
    return web.Response(text=seite("Anträge auf Gebietsnamen", inhalt, konto=request["konto"], csrf=request["csrf"], pfad=request.path,
                                   kopf='<meta name="robots" content="noindex">'), content_type="text/html", headers={"Cache-Control": "no-store"})


@anmeldung.angemeldet(_ist_kanzler, "Über Anträge auf Gebietsnamen entscheidet der Kanzler.")
async def antrag_entscheiden(request):
    form = await request.post()
    if not secrets.compare_digest(form.get("csrf", ""), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    entscheidung, antwort = form.get("entscheidung"), str(form.get("antwort", "")).strip()[:500]
    con = request.app["db"]
    a = con.execute("SELECT * FROM karte_antraege WHERE id = ? AND status = 'offen'", (form.get("id"),)).fetchone()
    if not a or entscheidung not in ("angenommen", "abgelehnt"):
        raise web.HTTPSeeOther("/karte/antraege/")
    if entscheidung == "abgelehnt" and not antwort:
        raise web.HTTPSeeOther("/karte/antraege/?m=grund")
    k = request["konto"]
    con.execute("UPDATE karte_antraege SET status = ?, antwort = ?, entschieden_von = ?, entschieden_zeit = ? WHERE id = ?",
                (entscheidung, antwort, k["id"], int(time.time()), a["id"]))
    con.commit()
    alt = GEO["gebiete"][a["gebiet"]]["n"]
    if entscheidung == "angenommen":
        stand = aktuell(con)["stand"]
        alt = stand["namen"].get(a["gebiet"], alt)
        stand["namen"][a["gebiet"]] = a["neu"]
        stand["namen"] = dict(sorted(stand["namen"].items()))
        neue_version(con, stand, f"Antrag von {a['nutzer_name']}: {alt} → {a['neu']}", k)
        text = f"Dein Antrag, das Gebiet „{alt}“ in **„{a['neu']}“** umzubenennen, wurde vom Kanzler **angenommen**." + (f"\n> {antwort}" if antwort else "")
    else:
        text = f"Dein Antrag, das Gebiet „{alt}“ in „{a['neu']}“ umzubenennen, wurde vom Kanzler **abgelehnt**.\n> {antwort}"
    await request.app["discord"].dm(a["nutzer_id"], text + f"\n{config.SITE_URL}/karte/")
    raise web.HTTPSeeOther("/karte/antraege/?m=ok")


async def png(request):
    if not os.path.exists(karte_bild.PFAD):
        raise web.HTTPNotFound()
    return web.FileResponse(karte_bild.PFAD, headers={"Cache-Control": "public, max-age=300"})


async def _bild_beim_start(app):
    if not os.path.exists(karte_bild.PFAD):
        karte_bild.neu_erzeugen(GEO, aktuell(app["db"])["stand"], verzoegerung=1)


def registrieren(app):
    einrichten(app["db"])
    app.on_startup.append(_geo_hintergrund)
    app.on_startup.append(_bild_beim_start)
    for p in ("", "/en"):
        app.router.add_get(p + "/karte/", anzeige)
        app.router.add_get(p + "/karte/bearbeiten/", editor)
    for pfad, h in (("geo.json", geo_json), ("geo_fein.json", geo_fein_json), ("daten.json", daten_json), ("info.json", info_json), ("karte.png", png),
                    ("antraege/", antraege_seite)):
        app.router.add_get("/karte/" + pfad, h)
    for pfad, h in (("speichern", speichern), ("gebietsname", gebietsname), ("antrag", antrag), ("antraege/entscheiden", antrag_entscheiden)):
        app.router.add_post("/karte/" + pfad, h)
