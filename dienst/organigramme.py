"""Organigramme: allgemeines Organigramm des Reiches (staatsaufbau.js) und Organigramm der Reichsverwaltung (organigramm.js).

Je Organigramm (auch unter /en/…):
    GET  <pfad>             Anzeige
    GET  <pfad>bearbeiten/  Editor (nur Server-Admins)
    GET  <pfad>info.json    Amtsträger, Mitgliederzahlen und Rollennamen aus Discord (live)
    GET  <pfad>organigramm.png  Bild (Startseite), erzeugt von bild.py
    POST <pfad>speichern    neuer Stand (JSON: csrf, basis, stand, bemerkung) → {ok, version, stand} | {konflikt, name} | {fehler}

Jeder gespeicherte Stand ist eine Version in der Tabelle organigramm_versionen; der jüngste gilt.
Gibt es noch keinen Stand, wird der Startstand aus organigramme_start.py angelegt.
Das HTML-Gerüst (Leiste, Fläche, Seitenleiste, Fenster, Editor-Dialoge) entspricht dem, was die Skripte und wiki.css erwarten.
"""
import html
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

from aiohttp import web

import anmeldung
import bild
import config
import organigramme_start
from seiten import seite

routes = web.RouteTableDef()
esc = html.escape

SICHTBAR = ["wahl", "ernennung", "ausfertigung", "bildung", "beschluss", "gliederung"]   # standardmäßig sichtbare Beziehungsarten, der Rest lässt sich einblenden
ARTEN = ["vorschlag", "wahl", "ernennung", "ausfertigung", "bildung", "beschluss", "veto", "kontrolle", "gliederung"]
FORMEN = {"organ": ("Organ", "Body"), "krone": ("Krone", "Crown"), "volk": ("Volk", "People"), "dokument": ("Dokument", "Document")}
ARTEN_AMT = {"amt": ("Amt", "Office"), "kanzlei": ("Kanzlei", "Chancellery"), "saeule": ("Säule", "Pillar"),
             "krone": ("Krone", "Crown"), "gruppe": ("Gruppe", "Group")}

ORGANIGRAMME = {
    "staatsaufbau": {
        "pfad": "/informationen/organigramm/", "js": "staatsaufbau.js", "cfg": "og-cfg", "praefix": "og",
        "titel": ("Organigramm des Reiches", "Organisation chart of the Empire"),
        "eyebrow": ("Staatsaufbau", "Structure of the state"),
        "lead": ("Die Organe des Imperium Germanicum, ihre gegenwärtigen Amtsträger und wie sie zueinander stehen: wer wen wählt, "
                 "ernennt, kontrolliert oder überstimmen kann. Ein Klick auf ein Organ nennt Amtsträger, Mitglieder und alle Beziehungen.",
                 "The bodies of the Imperium Germanicum, their current office holders and how they relate to each other: who elects, "
                 "appoints, controls or can overrule whom. Click a body to see its office holders, members and all relations."),
        "brotkrumen": [("/informationen/", ("Staatsaufbau", "Structure of the state"))],
    },
    "verwaltung": {
        "pfad": "/informationen/die-reichsbehoerden/organigramm/", "js": "staatsaufbau.js", "cfg": "og-cfg", "praefix": "og",
        "titel": ("Organigramm der Reichsverwaltung", "Organisation chart of the Imperial Administration"),
        "eyebrow": ("Die Reichsbehörden", "The Imperial Authorities"),
        "lead": ("Alle Ämter und Behörden der Reichsverwaltung mit ihren gegenwärtigen Amtsträgern und wie sie gegliedert sind. "
                 "Ein Klick auf ein Amt nennt Amtsträger, Aufgaben und alle Beziehungen.",
                 "All offices and authorities of the Imperial Administration with their current office holders and how they are organised. "
                 "Click an office to see its office holders, tasks and all relations."),
        "brotkrumen": [("/informationen/", ("Staatsaufbau", "Structure of the state")),
                       ("/informationen/die-reichsbehoerden/", ("Die Reichsbehörden", "The Imperial Authorities"))],
    },
}

# ---------- Texte für die Skripte (cfg.i18n) ----------
T_GEMEINSAM = {
    "de": {"asOf": "Stand", "byDecree": "per Dekret", "changes": "{n} ungespeicherte Änderungen", "noChanges": "Keine Änderungen",
           "conflict": "Inzwischen hat {name} einen neueren Stand gespeichert. Bitte lade die Seite neu und übernimm deine Änderungen erneut.",
           "holder": "Amtsträger", "holders": "Amtsträger", "idsBad": "Dekret-IDs: nur Discord-Nutzer-IDs (Ziffern), durch Kommas getrennt.",
           "infoError": "Die Amtsträger konnten nicht geladen werden.", "leave": "Es gibt ungespeicherte Änderungen.",
           "linkBad": "Der Verweis muss ein Pfad dieser Website sein, z. B. /informationen/der-senat/.",
           "loadError": "Das Organigramm konnte nicht geladen werden.", "members": "Mitglieder", "nameEmpty": "Bitte einen Namen angeben.",
           "notFound": "Nichts gefunden.", "or": "oder", "remove": "Entfernen",
           "rolesAnd": "und zusätzlich „{z}“", "rolesNote": "Amtsträger ist, wer auf dem Discord-Server die Rolle {r} hat.",
           "saved": "Gespeichert.", "saveError": "Speichern fehlgeschlagen.", "toPage": "Zur Seite", "vacant": "unbesetzt"},
    "en": {"asOf": "As of", "byDecree": "by decree", "changes": "{n} unsaved changes", "noChanges": "No changes",
           "conflict": "{name} has saved a newer version in the meantime. Please reload the page and apply your changes again.",
           "holder": "Office holder", "holders": "Office holders", "idsBad": "Decree IDs: Discord user IDs only (digits), separated by commas.",
           "infoError": "The office holders could not be loaded.", "leave": "There are unsaved changes.",
           "linkBad": "The link must be a path on this website, e.g. /informationen/der-senat/.",
           "loadError": "The chart could not be loaded.", "members": "Members", "nameEmpty": "Please enter a name.",
           "notFound": "Nothing found.", "or": "or", "remove": "Remove",
           "rolesAnd": "and additionally “{z}”", "rolesNote": "Office holder is whoever has the role {r} on the Discord server.",
           "saved": "Saved.", "saveError": "Saving failed.", "toPage": "To the page", "vacant": "vacant"},
}
T_STAATSAUFBAU = {
    "de": {"about": "Über das Organ", "editBody": "Organ bearbeiten", "newBody": "Neues Organ", "thisBody": "dieses Organ",
           "legend": "Beziehungen", "png": "Organigramm des Imperium Germanicum", "relations": "Beziehungen",
           "noRelations": "Noch keine Beziehungen.", "nHolders": "{n} Amtsträger",
           "membersNote": "Mitglieder: alle mit der Rolle „{r}“.",
           "confirmDelete": "„{name}“ mit {n} Beziehungen löschen?",
           "arten": {"vorschlag": ("schlägt vor", "vorgeschlagen von"), "wahl": ("wählt", "gewählt von"),
                     "ernennung": ("ernennt", "ernannt von"), "ausfertigung": ("fertigt aus", "ausgefertigt von"),
                     "bildung": ("bildet", "gebildet von"), "beschluss": ("beschließt für", "Beschlüsse von"),
                     "veto": ("Veto gegen", "Veto durch"), "kontrolle": ("kontrolliert", "kontrolliert von"),
                     "gliederung": ("gliedert sich in", "gehört zu")}},
    "en": {"about": "About this body", "editBody": "Edit body", "newBody": "New body", "thisBody": "this body",
           "legend": "Relations", "png": "Organisation chart of the Imperium Germanicum", "relations": "Relations",
           "noRelations": "No relations yet.", "nHolders": "{n} office holders",
           "membersNote": "Members: everyone with the role “{r}”.",
           "confirmDelete": "Delete “{name}” with {n} relations?",
           "arten": {"vorschlag": ("proposes", "proposed by"), "wahl": ("elects", "elected by"),
                     "ernennung": ("appoints", "appointed by"), "ausfertigung": ("promulgates", "promulgated by"),
                     "bildung": ("forms", "formed by"), "beschluss": ("decides for", "decisions by"),
                     "veto": ("veto against", "veto by"), "kontrolle": ("controls", "controlled by"),
                     "gliederung": ("comprises", "part of")}},
}
T_VERWALTUNG = {
    "de": {"collapse": "Zuklappen", "expand": "Aufklappen", "editOffice": "Amt bearbeiten", "newOffice": "Neues Amt",
           "lead": "Leitung", "more": "und {n} weitere", "nSub": "{n} untergeordnete Ämter", "png": "Organigramm der Reichsverwaltung",
           "sub": "Untergeordnet", "superior": "Übergeordnet", "tasks": "Aufgaben", "top": "– oberste Ebene –",
           "confirmDelete": "„{name}“ und {n} untergeordnete Ämter löschen?", "confirmDelete1": "„{name}“ löschen?"},
    "en": {"collapse": "Collapse", "expand": "Expand", "editOffice": "Edit office", "newOffice": "New office",
           "lead": "Leadership", "more": "and {n} more", "nSub": "{n} subordinate offices", "png": "Organisation chart of the Imperial Administration",
           "sub": "Subordinate", "superior": "Superior", "tasks": "Tasks", "top": "– top level –",
           "confirmDelete": "Delete “{name}” and {n} subordinate offices?", "confirmDelete1": "Delete “{name}”?"},
}


def graph(name):
    """Organigramme mit frei gesetzten Organen und Beziehungen (staatsaufbau.js) statt Baumansicht."""
    return ORGANIGRAMME[name]["js"] == "staatsaufbau.js"


def texte(name, lang):
    t = dict(T_GEMEINSAM[lang])
    if graph(name):
        s = dict(T_STAATSAUFBAU[lang])
        s["arten"] = {a: {"aktiv": v[0], "passiv": v[1]} for a, v in s["arten"].items()}
        s["png"] = ORGANIGRAMME[name]["titel"][lang == "en"]
        t.update(s)
    else:
        t.update(T_VERWALTUNG[lang])
    return t


# ---------- Speicher ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS organigramm_versionen (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    stand      TEXT NOT NULL,
    bemerkung  TEXT NOT NULL DEFAULT '',
    autor_id   TEXT,
    autor_name TEXT NOT NULL,
    zeit       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS organigramm_versionen_name ON organigramm_versionen(name, id);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    for name in ORGANIGRAMME:
        if not con.execute("SELECT 1 FROM organigramm_versionen WHERE name = ?", (name,)).fetchone():
            stand = organigramme_start.STAATSAUFBAU if name == "staatsaufbau" else organigramme_start.VERWALTUNG
            con.execute("INSERT INTO organigramm_versionen (name, stand, bemerkung, autor_name, zeit) VALUES (?, ?, ?, ?, ?)",
                        (name, json.dumps(pruefen(name, stand)), "Startstand (Neuaufbau 02.11.2026)", "System", int(time.time())))
    con.commit()


def aktuell(con, name):
    row = con.execute("SELECT * FROM organigramm_versionen WHERE name = ? ORDER BY id DESC LIMIT 1", (name,)).fetchone()
    return dict(row, stand=json.loads(row["stand"]))


class Ungueltig(Exception):
    pass


def _text(v, maxlen=4000):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise Ungueltig("Ungültiger Text.")
    return v.strip()[:maxlen]


def _ids(v, muster=r"^[0-9]{5,22}$"):
    if not isinstance(v, list) or not all(isinstance(x, str) and re.match(muster, x) for x in v):
        raise Ungueltig("Ungültige ID-Liste.")
    return list(dict.fromkeys(v))[:50]


def _rolle(v):
    v = _text(v, 30)
    if v and not re.match(r"^[0-9]{5,22}$", v):
        raise Ungueltig("Ungültige Rolle.")
    return v


def _link(v):
    v = _text(v, 300)
    if v and not re.match(r"^/[^/\\\s]", v):
        raise Ungueltig("Ungültiger Verweis.")
    return v


def pruefen(name, stand):
    """Prüft einen Stand aus dem Editor und gibt ihn bereinigt zurück (Kennungen der Beziehungen neu vergeben)."""
    if not isinstance(stand, dict) or not isinstance(stand.get("knoten"), list) or len(stand["knoten"]) > 500:
        raise Ungueltig("Ungültiger Stand.")
    knoten, ids = [], set()
    for k in stand["knoten"]:
        if not isinstance(k, dict) or not isinstance(k.get("id"), str) or not re.match(r"^[a-z][0-9]{1,6}$", k["id"]) or k["id"] in ids:
            raise Ungueltig("Ungültige oder doppelte Kennung.")
        ids.add(k["id"])
        n = {"id": k["id"]}
        felder = ["titel", "titel_en", "kurz", "kurz_en", "text", "text_en"] + (["leitung", "leitung_en"] if not graph(name) else [])
        for f in felder:
            n[f] = _text(k.get(f), 4000 if f.startswith("text") else 200)
        if not n["titel"]:
            raise Ungueltig("Jedes Organ braucht einen Namen.")
        n.update(rollen=[_rolle(r) for r in _ids(k.get("rollen", []))], zusatz=_rolle(k.get("zusatz")),
                 nutzer=_ids(k.get("nutzer", [])), angehoerige=_rolle(k.get("angehoerige")), link=_link(k.get("link")))
        if graph(name):
            n["form"] = k.get("form") if k.get("form") in FORMEN else "organ"
            n["bild"] = _text(k.get("bild"), 40)
            if n["bild"] and not re.match(r"^i[0-9a-f]{16}-(640|1280)$", n["bild"]):
                raise Ungueltig("Ungültiges Bild.")
            n["rahmen"] = _text(k.get("rahmen"), 10)
            for a in ("x", "y"):
                if not isinstance(k.get(a), (int, float)) or abs(k[a]) > 100000:
                    raise Ungueltig("Ungültige Position.")
                n[a] = int(round(k[a]))
        else:
            n["art"] = k.get("art") if k.get("art") in ARTEN_AMT else "amt"
            n["eltern"] = _text(k.get("eltern"), 10)
        knoten.append(n)

    if not graph(name):
        for n in knoten:
            if n["eltern"] and n["eltern"] not in ids:
                raise Ungueltig("Übergeordnetes Amt fehlt.")
        eltern = {n["id"]: n["eltern"] for n in knoten}
        for n in knoten:   # keine Kreise
            seen, k = set(), n["id"]
            while k:
                if k in seen:
                    raise Ungueltig("Kreis in der Gliederung.")
                seen.add(k)
                k = eltern.get(k)
        return {"knoten": knoten}

    rahmen, rids = [], set()
    for r in stand.get("rahmen", []):
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not re.match(r"^r[0-9]{1,6}$", r["id"]) or r["id"] in rids:
            raise Ungueltig("Ungültiger Rahmen.")
        rids.add(r["id"])
        rahmen.append({"id": r["id"], "titel": _text(r.get("titel"), 200), "titel_en": _text(r.get("titel_en"), 200)})
    for n in knoten:
        if n["rahmen"] and n["rahmen"] not in rids:
            n["rahmen"] = ""
    rahmen = [r for r in rahmen if any(n["rahmen"] == r["id"] for n in knoten)]
    kanten, schluessel = [], set()
    for e in stand.get("kanten", []):
        if not isinstance(e, dict) or e.get("von") not in ids or e.get("nach") not in ids or e.get("art") not in ARTEN or e["von"] == e["nach"]:
            raise Ungueltig("Ungültige Beziehung.")
        s = (e["von"], e["nach"], e["art"])
        if s not in schluessel:
            schluessel.add(s)
            kanten.append({"id": f"e{len(kanten) + 1}", "von": e["von"], "nach": e["nach"], "art": e["art"]})
    bahnen = []
    for b in (stand.get("bahnen") or [])[:12]:
        try:
            bahnen.append({"titel": _text(b.get("titel"), 100), "titel_en": _text(b.get("titel_en"), 100), "von": round(float(b["von"])), "bis": round(float(b["bis"]))})
        except (AttributeError, KeyError, TypeError, ValueError):
            raise Ungueltig("Ungültige Bahn.")
    return {"knoten": knoten, "rahmen": rahmen, "kanten": kanten, "bahnen": bahnen}


# ---------- Seiten ----------
def _lang(request):
    return "en" if request.path.startswith("/en/") else "de"


def _name(request):
    pfad = request.path[3:] if request.path.startswith("/en/") else request.path
    for name, o in ORGANIGRAMME.items():
        if pfad.startswith(o["pfad"]):
            return name
    raise web.HTTPNotFound()


def _optionen(werte, gewaehlt=None):
    return "".join(f'<option value="{esc(v)}"{" selected" if v == gewaehlt else ""}>{esc(t)}</option>' for v, t in werte)


def _feld(id_, label, inhalt=None, typ="text", extra="", hinweis=""):
    if inhalt is None:
        inhalt = f'<input id="of-{id_}" type="{typ}" {extra}>'
    h = f'<p class="karte-feldhinweis">{esc(hinweis)}</p>' if hinweis else ""
    return f'<div class="field"><label for="of-{id_}">{esc(label)}</label>{inhalt}{h}</div>'


def _rollen_optionen(rollen, leer):
    return f'<option value="">{esc(leer)}</option>' + "".join(
        f'<option value="{esc(r["id"])}">{esc(r["name"])}</option>' for r in rollen)


def _swatch(a):
    spitze = "" if a == "gliederung" else f'<path class="og-spitze og-f-{a}" d="M19 1L27 6L19 11Z"/>'
    return (f'<svg class="og-strich" viewBox="0 0 28 12" width="22" height="10" aria-hidden="true">'
            f'<path class="og-k-{a}" d="M1 6H21"/>{spitze}</svg>')


def _editor_dialog(name, lang, rollen, bilder):
    en = lang == "en"
    L = (lambda de, e: e if en else de)
    rolle_leer = L("– Rolle hinzufügen –", "– add role –")
    kopf = (f'<h2 data-dialog-titel></h2><p class="form-status err" data-dialog-fehler hidden></p>'
            '<div class="org-felder">'
            + _feld("titel", L("Name", "Name"), extra='maxlength="200" required')
            + _feld("titel_en", L("Name (englisch)", "Name (English)"), extra='maxlength="200"')
            + _feld("kurz", L("Kurzbezeichnung (über dem Namen)", "Label (above the name)"), extra='maxlength="200"')
            + _feld("kurz_en", L("Kurzbezeichnung (englisch)", "Label (English)"), extra='maxlength="200"'))
    if not graph(name):
        kopf += (_feld("leitung", L("Leitung", "Leadership"), extra='maxlength="200"')
                 + _feld("leitung_en", L("Leitung (englisch)", "Leadership (English)"), extra='maxlength="200"'))
    kopf += (_feld("text", L("Beschreibung (Absätze durch Leerzeile)", "Description (blank line between paragraphs)"),
                   '<textarea id="of-text" rows="5" maxlength="4000"></textarea>')
             + _feld("text_en", L("Beschreibung (englisch)", "Description (English)"),
                     '<textarea id="of-text_en" rows="5" maxlength="4000"></textarea>'))
    if graph(name):
        kopf += (_feld("form", L("Darstellung", "Display"),
                       f'<select id="of-form">{_optionen([(k, v[1] if en else v[0]) for k, v in FORMEN.items()])}</select>')
                 + '<div class="org-felder" style="grid-template-columns:1fr auto;gap:0 12px">'
                 + _feld("bild", L("Wappen/Siegel", "Emblem/seal"),
                         f'<select id="of-bild"><option value="">{esc(L("– ohne (Initialen) –", "– none (initials) –"))}</option>'
                         + "".join(f'<option value="{esc(b)}">{esc(t)}</option>' for b, t in bilder) + "</select>")
                 + '<div class="og-bild-vorschau" data-bild-vorschau></div></div>'
                 + _feld("rahmen", L("Rahmen (z. B. Senatskanzlei)", "Frame (e.g. Senate Chancellery)"),
                         '<input id="of-rahmen" list="og-rahmen-liste" maxlength="200"><datalist id="og-rahmen-liste"></datalist>'))
    else:
        kopf += (_feld("art", L("Darstellung", "Display"),
                       f'<select id="of-art">{_optionen([(k, v[1] if en else v[0]) for k, v in ARTEN_AMT.items()])}</select>')
                 + _feld("eltern", L("Übergeordnet", "Superior"), '<select id="of-eltern"></select>'))
    kopf += "</div>"
    rollen_teil = (
        '<div class="org-felder">'
        + _feld("rolle", L("Amtsträger über Rollen", "Office holders by role"),
                f'<ul class="org-chips" data-chips></ul><select id="of-rolle">{_rollen_optionen(rollen, rolle_leer)}</select>',
                hinweis=L("Wer eine dieser Rollen hat, ist Amtsträger.", "Whoever has one of these roles holds the office."))
        + _feld("zusatz", L("… und zusätzlich die Rolle", "… and additionally the role"),
                f'<select id="of-zusatz">{_rollen_optionen(rollen, L("– keine –", "– none –"))}</select>')
        + _feld("nutzer", L("Amtsträger per Dekret (Discord-IDs)", "Office holders by decree (Discord IDs)"),
                extra='inputmode="numeric" placeholder="123456789012345678, …"')
        + _feld("angehoerige", L("Mitglieder/Angehörige: Rolle", "Members: role"),
                f'<select id="of-angehoerige">{_rollen_optionen(rollen, L("– keine –", "– none –"))}</select>')
        + _feld("link", L("Verweis auf eine Seite", "Link to a page"), extra='maxlength="300" placeholder="/informationen/der-senat/"')
        + "</div>")
    kanten = ""
    if graph(name):
        arten = [(a, texte(name, lang)["arten"][a]["aktiv"]) for a in ARTEN]
        kanten = (f'<h3 class="karte-gebiet-h">{esc(L("Beziehungen", "Relations"))}</h3><ul class="og-beziehungen" data-kanten></ul>'
                  '<div class="og-neue-kante">'
                  + _feld("richtung", L("Richtung", "Direction"),
                          f'<select id="of-richtung">{_optionen([("aus", L("dieses Organ …", "this body …")), ("ein", L("… dieses Organ", "… this body"))])}</select>')
                  + _feld("art", L("Art", "Type"), f'<select id="of-art">{_optionen(arten)}</select>')
                  + _feld("ziel", L("anderes Organ", "other body"), '<select id="of-ziel"></select>')
                  + f'<button type="button" class="btn btn-line" data-aktion="kante">{esc(L("Hinzufügen", "Add"))}</button></div>')
        mehr = f'<button type="button" class="btn btn-line karte-loeschen" data-aktion="loeschen">{esc(L("Löschen", "Delete"))}</button>'
    else:
        mehr = (f'<button type="button" class="btn btn-line" data-aktion="links" title="{esc(L("nach links", "move left"))}">←</button>'
                f'<button type="button" class="btn btn-line" data-aktion="rechts" title="{esc(L("nach rechts", "move right"))}">→</button>'
                f'<button type="button" class="btn btn-line" data-aktion="kind">{esc(L("Untergeordnetes Amt", "Subordinate office"))}</button>'
                f'<button type="button" class="btn btn-line karte-loeschen" data-aktion="loeschen">{esc(L("Löschen", "Delete"))}</button>')
    return (f'<dialog class="dialog wide org-dialog karte-dialog" data-dialog><form method="dialog" class="form">{kopf}{rollen_teil}{kanten}'
            f'<div class="dialog-actions"><button class="btn btn-navy" value="ok">{esc(L("Übernehmen", "Apply"))}</button>'
            f'<button class="btn btn-line" value="cancel" formnovalidate>{esc(L("Abbrechen", "Cancel"))}</button>'
            f'<div class="org-dialog-mehr">{mehr}</div></div></form></dialog>'
            f'<dialog class="dialog" data-speichern><form method="dialog" class="form"><h2>{esc(L("Speichern", "Save"))}</h2>'
            f'<div class="field"><label for="{ORGANIGRAMME[name]["praefix"]}-bemerkung">{esc(L("Bemerkung zur Änderung", "Note on the change"))}</label>'
            f'<input id="{ORGANIGRAMME[name]["praefix"]}-bemerkung" maxlength="300"></div><div data-meldung></div>'
            f'<div class="dialog-actions"><button class="btn btn-navy" value="ok">{esc(L("Speichern", "Save"))}</button>'
            f'<button class="btn btn-line" value="cancel" formnovalidate>{esc(L("Abbrechen", "Cancel"))}</button></div></form></dialog>')


# Nur Institutionsflaggen, Wappen, Siegel, Standarten, Kronen und Logos (keine Bilder von Personen, Gebäuden oder Schreiben)
WAPPEN = {
    "i92158683d4a0cca4": "Wappen des Imperium Germanicum",
    "idbbec25dc54e06be": "Großes Wappen des Imperium Germanicum",
    "i05f85b1d8736e0f0": "Doppelkopfadler",
    "i4ee586247fc514c2": "Logo der Streitkräfte",
    "i2b32d4cb098dab2c": "Flagge der Streitkräfte",
    "i11aaca30dcc486be": "Siegel der Streitkräfte",
    "i15c0c0ea6780ad72": "Emblem des Kaisers",
    "ie6ecf3d509ef6fc3": "Emblem des Kaisers (Schloss Charlottenburg)",
    "if0978cec8f01efe8": "Standarte des Kaisers",
    "i2990580d50400cfc": "Krone des Kaisers",
    "i23c1241b7ac79d7f": "Krone der Kaiserin",
    "i7843be5e8c7b2235": "Krone der Hand des Kaisers",
    "i1493da48e15343da": "Kurfürstenhut",
    "ib7c33ba7d6bef700": "Emblem der Hand des Kaisers",
    "ie52e566a1afc77a5": "Standarte der Hand des Kaisers",
    "i0ed2170b7ed819f2": "Emblem des Senats",
    "i9aaec4e5a4cd55cd": "Emblem des Reichstags",
    "id9019adce22b0976": "Siegel des Reichsgerichtshofs",
    "iac7a254e9f22265b": "Emblem der Stabschefs",
    "i4dd5fb31eadc1d24": "Logo des Reichssicherheitsamts",
    "i416b7a1e6d04b155": "Siegel der Reichsbehörden",
    "icf5ad018407fe134": "Siegel des Kronkanzlers",
    "i5a9f8040f8005417": "Standarte des Kronkanzlers",
    "i6b2e0c7d41a95f38": "The Crown Estates",
    "i3c7a91e5d20b84f6": "Doppeladler auf Gold (grau)",
    "i8e14b6a0c9d357f2": "Doppeladler auf Gold (klassisch)",
    "i0315259ab08a3c08": "Amtswappen mit Krone",
    "i1daa69f889b1aabc": "Die Inquisition (Amtslogo)",
    "i9382f9cd71b52864": "Kaiserliches Reichssicherheitsamt (Amtslogo)",
    "i7fd139f88ee8c793": "Kaiserliche Polizeibehörde (Amtslogo)",
    "i3c9b6c716bb7200a": "Kaiserlicher Katastrophenschutz (Amtslogo)",
    "if0b7c255017e26e3": "Kaiserliche Zollverwaltung (Amtslogo)",
    "ibd0fa570bb4854a1": "Kaiserliches Schatz- und Währungsamt (Amtslogo)",
    "i373575476421cadb": "Die Reichsbehörden (Amtslogo)",
    "i42648ed6ea92d607": "Amtslogo des Kronkanzlers",
    "i2e330402e5d67b0a": "Emblem der Imperialen Charta",
    "i1ed8e9913dc91849": "Emblem des Etiketten-Guides",
}


def _bilder():
    """Wappen/Siegel für die Auswahl im Editor: nur Institutionsbilder, nicht Bilder von Personen."""
    try:
        with open(config.WEBSITE_DIR + "/_build/bilder.json", encoding="utf-8") as fh:
            alle = json.load(fh)
    except OSError:
        alle = {}
    return [(f"{i}-640", t) for i, t in WAPPEN.items() if not alle or i in alle]


def seite_html(request, name, modus, konto, csrf, version, rollen):
    lang = _lang(request)
    en = lang == "en"
    L = (lambda de, e: e if en else de)
    o = ORGANIGRAMME[name]
    p = o["praefix"]
    prefix = "/en" if en else ""
    basis_pfad = prefix + o["pfad"]
    titel = o["titel"][en]
    stand_datum = datetime.fromtimestamp(version["zeit"], timezone.utc).strftime("%d.%m.%Y")
    cfg = {"i18n": texte(name, lang), "lang": lang, "modus": modus, "stand": version["stand"], "basis": version["id"],
           "version": None, "info": basis_pfad + "info.json", "speichern": basis_pfad + "speichern",
           "csrf": csrf or "", "prefix": prefix, "stand_datum": stand_datum,
           "rollen": {r["id"]: r["name"] for r in rollen} if modus == "bearbeiten" else {}}
    if graph(name):
        cfg.update(arten=ARTEN, bilder="/assets/img/", sichtbar=SICHTBAR)
    cfg_json = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")

    krumen = "".join(f'<li><a href="{prefix}{u}">{esc(t[en])}</a></li>' for u, t in o["brotkrumen"])
    if modus == "bearbeiten":
        krumen += f'<li><a href="{basis_pfad}">{esc(titel)}</a></li>'
    aktuell_t = L("Bearbeiten", "Edit") if modus == "bearbeiten" else titel
    kopf = (f'<div class="page-head"><div class="wrap"><nav class="breadcrumb" aria-label="{L("Brotkrumen", "Breadcrumb")}"><ol>'
            f'<li><a href="{prefix}/">{L("Hauptseite", "Home")}</a></li>{krumen}<li><span aria-current="page">{esc(aktuell_t)}</span></li></ol></nav>'
            f'<span class="eyebrow">{esc(o["eyebrow"][en])}</span><h1>{esc(titel)}</h1>'
            f'<p class="wiki-intro rt-lead">{esc(o["lead"][en])}</p></div></div>')

    zoom = (f'<div class="karte-zoom"><button type="button" class="btn btn-line" data-zoom="in" aria-label="{L("Vergrößern", "Zoom in")}">+</button>'
            f'<button type="button" class="btn btn-line" data-zoom="out" aria-label="{L("Verkleinern", "Zoom out")}">−</button>'
            f'<button type="button" class="btn btn-line" data-zoom="fit">{L("Ganz zeigen", "Fit")}</button></div>')
    suche = (f'<form class="karte-suche field" role="search"><label class="sr-only" for="{p}-suche">{L("Suchen", "Search")}</label>'
             f'<input id="{p}-suche" type="search" list="{p}-liste" autocomplete="off" '
             f'placeholder="{L("Organ oder Amtsträger suchen", "Search body or office holder") if graph(name) else L("Amt oder Amtsträger suchen", "Search office or office holder")}">'
             f'<datalist id="{p}-liste"></datalist></form>')
    extra = ""
    if not graph(name):
        extra = (f'<button type="button" class="btn btn-line" data-alle="auf">{L("Alle aufklappen", "Expand all")}</button>'
                 f'<button type="button" class="btn btn-line" data-alle="zu">{L("Alle zuklappen", "Collapse all")}</button>')
    bild = f'<button type="button" class="btn btn-line" data-bild>{L("Als Bild herunterladen", "Download as image")}</button>'
    werkzeuge = ""
    if modus == "bearbeiten":
        neu = L("Neues Organ", "New body") if graph(name) else L("Neues Amt", "New office")
        werkzeuge = (f'<div class="org-werkzeuge"><span class="karte-stand" data-stand></span>'
                     f'<button type="button" class="btn btn-line" data-aktion="neu">{neu}</button>'
                     f'<button type="button" class="btn btn-line" data-aktion="undo" title="{L("Rückgängig", "Undo")}" disabled>↶</button>'
                     f'<button type="button" class="btn btn-line" data-aktion="redo" title="{L("Wiederholen", "Redo")}" disabled>↷</button>'
                     f'<button type="button" class="btn btn-navy" data-aktion="speichern" disabled>{L("Speichern", "Save")}</button></div>')
    wurzel_klasse = ("og og-cols karte-cols karte" if graph(name) else "org karte-cols karte") + (" is-editor" if modus == "bearbeiten" else "")
    wurzel = (f'<div class="{wurzel_klasse}" data-{p}><div class="karte-leiste">{zoom}{suche}{extra}{bild}{werkzeuge}</div>'
              f'<div class="karte-buehne"><div class="karte-flaeche org-flaeche" tabindex="0" aria-label="{esc(titel)}">'
              f'<p class="karte-laden">{L("Organigramm wird geladen …", "Loading chart …")}</p></div>'
              f'<div class="karte-info" aria-live="polite"></div></div>'
              f'<p class="karte-quelle">{L("Stand", "As of")} {stand_datum}. {L("Amtsträger live aus den Rollen unseres Discord-Servers.", "Office holders live from the roles on our Discord server.")}</p></div>')

    # Seitenleiste
    if graph(name):
        t = texte(name, lang)
        nav = (f'<nav class="aside-nav" aria-label="{L("Legende", "Legend")}"><h2>{L("Beziehungen", "Relations")}</h2><ul class="karte-legende">'
               + "".join(f'<li><button type="button" class="karte-legende-item" data-art="{a}" aria-pressed="{"true" if a in SICHTBAR else "false"}">{_swatch(a)}'
                         f'<span class="karte-legende-name">{esc(t["arten"][a]["aktiv"])}</span></button></li>' for a in ARTEN)
               + "</ul>"
               + f'<div class="karte-aktionen"><button type="button" class="btn btn-line btn-small" data-ebene="struktur">{L("Nur Struktur", "Structure only")}</button>'
               f'<button type="button" class="btn btn-line btn-small" data-ebene="alle">{L("Alle zeigen", "Show all")}</button></div>'
               f'<p class="karte-feldhinweis">{L("Ein Klick blendet eine Beziehungsart ein oder aus. Ein Klick auf ein Organ zeigt immer alle seine Beziehungen.", "Click to show or hide a type of relation. Clicking a body always shows all of its relations.")}</p></nav>')
        aside_klasse = "og-aside"
    else:
        nav = f'<nav class="aside-nav org-gliederung" aria-label="{L("Gliederung", "Structure")}"><h2>{L("Gliederung", "Structure")}</h2><div data-gliederung></div></nav>'
        aside_klasse = "org-aside"
    if modus == "bearbeiten":
        box = (f'<div class="aside-box"><p><strong>{L("Editor", "Editor")}</strong> <span class="karte-stand" data-stand></span></p>'
               f'<p>{L("Klick auf ein Organ öffnet es zum Bearbeiten; ziehen verschiebt es." if graph(name) else "Klick auf ein Amt öffnet es zum Bearbeiten.", "Click to edit." )}</p>'
               f'<div data-meldung-seite></div><a class="link-arrow" href="{basis_pfad}">{L("Zur Ansicht", "To the view")}</a></div>')
    elif konto and konto["admin"]:
        box = f'<div class="aside-box"><a class="btn btn-line" href="{basis_pfad}bearbeiten/">{L("Organigramm bearbeiten", "Edit chart")}</a></div>'
    else:
        box = ""
    aside = f'<aside class="{aside_klasse} wiki-aside karte-aside">{nav}{box}</aside>'

    fenster = (f'<dialog class="dialog wide karte-gebiet org-amt" data-amt aria-labelledby="{p}-amt-titel">'
               f'<div data-amt-inhalt tabindex="-1"></div><div class="dialog-actions"><span data-amt-link></span>'
               f'<button type="button" class="btn btn-line" data-amt-zu>{L("Schließen", "Close")}</button></div></dialog>')
    dialoge = _editor_dialog(name, lang, rollen, _bilder()) if modus == "bearbeiten" else ""

    inhalt = (f'{kopf}<div class="section wiki"><div class="wrap with-aside wiki-cols"><div class="wiki-main">{wurzel}</div>{aside}</div></div>'
              f'{fenster}{dialoge}<script type="application/json" id="{o["cfg"]}">{cfg_json}</script>')
    v = int(max(os.path.getmtime(f"{config.WEBSITE_DIR}/assets/{d}") for d in ("css/wiki.css", "js/" + o["js"])))   # neu laden, sobald die Dateien wechseln
    head = (f'<link rel="stylesheet" href="/assets/css/wiki.css?v={v}">\n<script src="/assets/js/{o["js"]}?v={v}" defer></script>')
    if modus == "bearbeiten":
        head += '\n<meta name="robots" content="noindex">'
    return seite(titel + (" – " + L("Bearbeiten", "Edit") if modus == "bearbeiten" else ""), inhalt, kopf=head,
                 # og-cols auf der ganzen Seite: Legende und Fenster liegen außerhalb der Grafik und brauchen die Farben der Beziehungsarten
                 body_klasse="wiki-page og-cols" if graph(name) else "wiki-page", konto=konto, csrf=csrf, pfad=request.path, lang=lang,
                 canonical=basis_pfad + ("bearbeiten/" if modus == "bearbeiten" else ""))


def _pfade(suffix):
    out = []
    for o in ORGANIGRAMME.values():
        out += [o["pfad"] + suffix, "/en" + o["pfad"] + suffix]
    return out


async def anzeige(request):
    name = _name(request)
    k = await anmeldung.konto(request)
    html_ = seite_html(request, name, "anzeigen", k, request.get("csrf"), aktuell(request.app["db"], name), [])
    return web.Response(text=html_, content_type="text/html")


@anmeldung.angemeldet(lambda k: k["admin"], "Organigramme bearbeiten dürfen nur Administratoren unseres Discord-Servers.")
async def editor(request):
    name = _name(request)
    rollen = await request.app["discord"].rollen_liste()
    html_ = seite_html(request, name, "bearbeiten", request["konto"], request["csrf"], aktuell(request.app["db"], name), rollen)
    return web.Response(text=html_, content_type="text/html", headers={"Cache-Control": "no-store"})


def _verwendete_rollen(name, stand):
    r = set()
    for k in stand["knoten"]:
        r.update(k["rollen"])
        r.update(x for x in (k["zusatz"], k["angehoerige"]) if x)
    return r


async def info(request):
    """Amtsträger (über Rollen oder per Dekret) mit Namen, Mitgliederzahlen je Rolle, Rollennamen.

    Wer nur über eine Mitgliederrolle (angehoerige) zählt, erscheint nicht mit Namen: im Staatsaufbau gar nicht (dort
    reichen die Zahlen), im Organigramm der Reichsverwaltung ohne ID und Namen, weil organigramm.js aus den Personen zählt."""
    name = _name(request)
    dc = request.app["discord"]
    stand = aktuell(request.app["db"], name)["stand"]
    alle = request.query.get("alle") == "1"
    rollen = await dc.rollen_liste()
    namen = {r["id"]: r["name"] for r in rollen}
    verwendet = _verwendete_rollen(name, stand)
    amtsrollen = {r for k in stand["knoten"] for r in k["rollen"]}
    mitgliedsrollen = {k["angehoerige"] for k in stand["knoten"] if k["angehoerige"]}
    nutzer = {n for k in stand["knoten"] for n in k["nutzer"]}
    mitglieder = await dc.mitglieder()
    titel_rollen = await dc.rollen_der_gruppe("Adelstitel")
    personen, anonym, zahlen = [], [], {}
    for m in mitglieder:
        for r in m["rollen"]:
            if r in mitgliedsrollen:
                zahlen[r] = zahlen.get(r, 0) + 1
        eigene = [r for r in m["rollen"] if r in verwendet]
        if m["id"] in nutzer or amtsrollen.intersection(m["rollen"]):
            personen.append({"id": m["id"], "name": m["name"], "rollen": eigene,
                             "titel": [namen[r] for r in m["rollen"] if r in titel_rollen and r in namen]})
        elif not graph(name) and mitgliedsrollen.intersection(m["rollen"]):
            anonym.append({"id": "", "name": "", "rollen": [r for r in eigene if r in mitgliedsrollen], "titel": []})
    personen.sort(key=lambda p: p["name"].lower())
    personen += anonym
    liste = rollen if alle else [r for r in rollen if r["id"] in verwendet]
    return web.json_response({"personen": personen, "zahlen": zahlen, "rollen": [{"id": r["id"], "name": r["name"]} for r in liste]},
                             headers={"Cache-Control": "no-store" if alle else "public, max-age=60"})


async def speichern(request):
    name = _name(request)
    k = await anmeldung.konto(request)
    if not k or not k["admin"]:
        return web.json_response({"ok": False, "fehler": "Nicht angemeldet oder keine Berechtigung."}, status=403)
    try:
        daten = await request.json()
    except ValueError:
        return web.json_response({"ok": False, "fehler": "Ungültige Anfrage."}, status=400)
    if not secrets.compare_digest(str(daten.get("csrf", "")), request["csrf"]):
        return web.json_response({"ok": False, "fehler": "Sitzung abgelaufen. Bitte lade die Seite neu."}, status=403)
    con = request.app["db"]
    cur = aktuell(con, name)
    if daten.get("basis") != cur["id"]:
        return web.json_response({"ok": False, "konflikt": True, "name": cur["autor_name"]})
    try:
        stand = pruefen(name, daten.get("stand"))
    except Ungueltig as e:
        return web.json_response({"ok": False, "fehler": str(e)})
    c = con.execute("INSERT INTO organigramm_versionen (name, stand, bemerkung, autor_id, autor_name, zeit) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, json.dumps(stand, ensure_ascii=False), _text(daten.get("bemerkung"), 300), k["id"], k["name"], int(time.time())))
    con.commit()
    bild.neu_erzeugen(name, ORGANIGRAMME[name]["pfad"])
    return web.json_response({"ok": True, "version": c.lastrowid, "stand": stand})


async def png(request):
    datei = bild.pfad(_name(request))
    if not os.path.exists(datei):
        raise web.HTTPNotFound()
    return web.FileResponse(datei, headers={"Cache-Control": "public, max-age=300"})


async def _bilder_beim_start(app):
    for name, o in ORGANIGRAMME.items():
        if not os.path.exists(bild.pfad(name)):
            bild.neu_erzeugen(name, o["pfad"], verzoegerung=3)


def registrieren(app):
    einrichten(app["db"])
    app.on_startup.append(_bilder_beim_start)
    for p in _pfade("organigramm.png"):
        app.router.add_get(p, png)
    for p in _pfade(""):
        app.router.add_get(p, anzeige)
    for p in _pfade("bearbeiten/"):
        app.router.add_get(p, editor)
    for p in _pfade("info.json"):
        app.router.add_get(p, info)
    for p in _pfade("speichern"):
        app.router.add_post(p, speichern)
