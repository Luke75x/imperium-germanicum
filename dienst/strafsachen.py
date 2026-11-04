"""Strafsachen: Ermittlungsakten des Kaiserlichen Reichssicherheitsamts (KRS) und Strafverfahren der Inquisition (Staatsanwaltschaft).

Ablauf: KRS legt eine Ermittlungsakte an (Beteiligte, Beweismittel, Vermerke), ermittelt und gibt sie an die Inquisition ab. Dabei
entsteht automatisch ein verknüpftes Strafverfahren (Beteiligte werden übernommen, Mitteilung auf der Pinnwand der Inquisition).
Die Inquisition prüft, erhebt Anklage, setzt die Hauptverhandlung an, erfasst Urteil, Strafe und Haft und markiert die Rechtskraft.
Alles wird in einem Aktenprotokoll festgehalten. Akten können als „Geheim“ eingestuft werden (nur Leitung, Bearbeiter, Ersteller,
Kanzler/Admins/Kaiser). Es gibt Suche, Statistik und PDF-Export. Rechte siehe lesen_darf()/schreiben_darf().
Tabellen: sa_akten, sa_beteiligte, sa_beweise, sa_eintraege, sa_anhaenge (Dateien in daten/anhaenge, Zufallsnamen, nur Download). Seiten unter …/intern/sachen/<ermittlung|strafverfahren>/.
Haft wird nur erfasst (Beginn/Ende/Ort); Discord-Rollen (z. B. KRS-Häftling) werden nicht automatisch gesetzt.
"""
import hashlib
import os
import shutil
import secrets
import time
from urllib.parse import quote
from datetime import datetime

from aiohttp import web

import amt
import anmeldung
import bereiche
import config

esc = amt.esc
BASIS = amt.BASIS
ROOT = BASIS + "sachen/"

ARTEN = {
    "ermittlung": {"behoerde": "krs", "praefix": "KRS", "titel": "Ermittlungsakten", "einzel": "Ermittlungsakte", "icon": "file-search", "pfad": "ermittlung",
                   "status": {"eingegangen": "Eingegangen", "ermittlung": "In Ermittlung", "abgegeben": "An Inquisition abgegeben",
                              "eingestellt": "Eingestellt", "abgeschlossen": "Abgeschlossen"},
                   "offen": ("eingegangen", "ermittlung")},
    "strafverfahren": {"behoerde": "inquisition", "praefix": "INQ", "titel": "Strafverfahren", "einzel": "Strafverfahren", "icon": "gavel", "pfad": "strafverfahren",
                       "status": {"pruefung": "In Prüfung", "angeklagt": "Anklage erhoben", "verhandlung": "Hauptverhandlung",
                                  "urteil": "Urteil ergangen", "rechtskraeftig": "Rechtskräftig", "eingestellt": "Eingestellt"},
                       "offen": ("pruefung", "angeklagt", "verhandlung", "urteil")},
}
PFAD_ART = {a["pfad"]: k for k, a in ARTEN.items()}
BETEILIGTE = ["Beschuldigter", "Zeuge", "Geschädigter", "Hinweisgeber", "Verteidiger", "Sonstiger"]
MARKE = {"eingegangen": "offen", "ermittlung": "offen", "pruefung": "offen", "angeklagt": "offen", "verhandlung": "offen", "urteil": "offen",
         "abgegeben": "ok", "abgeschlossen": "ok", "rechtskraeftig": "ok", "eingestellt": "neutral"}
SEITE = 40
ANHANG_ORDNER = os.path.join(config.HIER, "daten", "anhaenge")   # nicht im Repo (daten/ ist ausgenommen), Dateien unter Zufallsnamen
ANHANG_MAX = 10 * 1024 * 1024
ANHANG_PRO_AKTE = 30
# Endung -> (Content-Type, Prüfung der Dateikennung); angeboten wird immer nur der Download (attachment, nosniff)
ANHANG_TYPEN = {
    "pdf": ("application/pdf", lambda b: b.startswith(b"%PDF")), "png": ("image/png", lambda b: b.startswith(b"\x89PNG")),
    "jpg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")), "jpeg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "gif": ("image/gif", lambda b: b.startswith(b"GIF8")), "webp": ("image/webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
    "txt": ("text/plain; charset=utf-8", lambda b: b"\x00" not in b),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", lambda b: b.startswith(b"PK\x03\x04")),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", lambda b: b.startswith(b"PK\x03\x04")),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sa_akten (
    id INTEGER PRIMARY KEY AUTOINCREMENT, art TEXT NOT NULL, jahr INTEGER NOT NULL, nr INTEGER NOT NULL,
    titel TEXT NOT NULL, beschreibung TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, geheim INTEGER NOT NULL DEFAULT 0,
    tatbestand TEXT NOT NULL DEFAULT '', tatzeit TEXT NOT NULL DEFAULT '', tatort TEXT NOT NULL DEFAULT '',
    bearbeiter_id TEXT NOT NULL DEFAULT '', bearbeiter_name TEXT NOT NULL DEFAULT '', verknuepft_id INTEGER,
    termin TEXT NOT NULL DEFAULT '', gericht TEXT NOT NULL DEFAULT '', urteil TEXT NOT NULL DEFAULT '', strafe TEXT NOT NULL DEFAULT '',
    haft_von TEXT NOT NULL DEFAULT '', haft_bis TEXT NOT NULL DEFAULT '', haft_ort TEXT NOT NULL DEFAULT '',
    ersteller_id TEXT NOT NULL, ersteller_name TEXT NOT NULL, erstellt INTEGER NOT NULL, aktualisiert INTEGER NOT NULL, abgeschlossen INTEGER,
    UNIQUE (art, jahr, nr));
CREATE TABLE IF NOT EXISTS sa_beteiligte (
    id INTEGER PRIMARY KEY AUTOINCREMENT, akte_id INTEGER NOT NULL REFERENCES sa_akten(id) ON DELETE CASCADE, rolle TEXT NOT NULL,
    name TEXT NOT NULL, konto_id TEXT NOT NULL DEFAULT '', notiz TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sa_beweise (
    id INTEGER PRIMARY KEY AUTOINCREMENT, akte_id INTEGER NOT NULL REFERENCES sa_akten(id) ON DELETE CASCADE, bezeichnung TEXT NOT NULL,
    beschreibung TEXT NOT NULL DEFAULT '', fundort TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL, autor_name TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sa_eintraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, akte_id INTEGER NOT NULL REFERENCES sa_akten(id) ON DELETE CASCADE, zeit INTEGER NOT NULL,
    art TEXT NOT NULL, text TEXT NOT NULL, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sa_anhaenge (
    id INTEGER PRIMARY KEY AUTOINCREMENT, akte_id INTEGER NOT NULL REFERENCES sa_akten(id) ON DELETE CASCADE, beweis_id INTEGER,
    dateiname TEXT NOT NULL, typ TEXT NOT NULL, groesse INTEGER NOT NULL, sha256 TEXT NOT NULL, speicher TEXT NOT NULL,
    zeit INTEGER NOT NULL, autor_id TEXT NOT NULL, autor_name TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS sa_anh_akte ON sa_anhaenge (akte_id);
CREATE INDEX IF NOT EXISTS sa_akten_art ON sa_akten (art, status);
CREATE INDEX IF NOT EXISTS sa_bet_akte ON sa_beteiligte (akte_id);
CREATE INDEX IF NOT EXISTS sa_bew_akte ON sa_beweise (akte_id);
CREATE INDEX IF NOT EXISTS sa_ein_akte ON sa_eintraege (akte_id);
"""

amt.ICONS.update({
    "file-search": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><circle cx="11.5" cy="14.5" r="2.5"/><path d="M13.3 16.3 15 18"/>',
    "gavel": '<path d="m14.5 12.5-8 8a2.119 2.119 0 1 1-3-3l8-8"/><path d="m16 16 6-6"/><path d="m8 8 6-6"/><path d="m9 7 8 8"/><path d="m21 11-8-8"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
})


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Rechte

def _behoerde(schl):
    return next(b for b in amt.BEHOERDEN if b["schl"] == schl)


def _mitglied_von(k, schl):
    return bool(k) and bool(set(_behoerde(schl)["rollen"]) & set(k["rollen"]))


def _leitung(k, art):
    return bereiche.leitung(k, _behoerde(ARTEN[art]["behoerde"]))


def az(a):
    return f'{ARTEN[a["art"]]["praefix"]}-{a["jahr"]}-{a["nr"]:04d}'


def lesen_darf(k, a):
    """Darf das Konto die Akte sehen (a = Zeile, oder nur die Art als Zeichenkette für „irgendwelche Akten dieser Art“)?"""
    if not k or not k["mitglied"]:
        return False
    art = a if isinstance(a, str) else a["art"]
    krs, inq, alle = _mitglied_von(k, "krs"), _mitglied_von(k, "inquisition"), bereiche._alle(k)
    if art == "ermittlung":
        ok = alle or krs or (inq and (isinstance(a, str) or a["status"] == "abgegeben" or a["verknuepft_id"]))
    else:
        ok = alle or krs or inq
    if ok and not isinstance(a, str) and a["geheim"]:
        ok = alle or _leitung(k, art) or k["id"] in (a["bearbeiter_id"], a["ersteller_id"])
    return bool(ok)


def schreiben_darf(k, art):
    return bool(k) and k["mitglied"] and (bereiche._alle(k) or _mitglied_von(k, ARTEN[art]["behoerde"]))


def nav(k):
    """Navigationseinträge (Schlüssel, Symbol, Text, Pfad) der Strafsachen, die das Konto sehen darf."""
    return [("s-" + a, v["icon"], v["titel"], f'sachen/{v["pfad"]}/') for a, v in ARTEN.items() if lesen_darf(k, a)]


# ---------------------------------------------------------------- Hilfen

def _eintrag(con, akte_id, art, text, k=None):
    con.execute("INSERT INTO sa_eintraege (akte_id, zeit, art, text, autor_id, autor_name) VALUES (?,?,?,?,?,?)",
                (akte_id, int(time.time()), art, text, k["id"] if k else None, k["name"] if k else "System"))


def _neue_akte(con, art, titel, k, status, **felder):
    jahr = datetime.fromtimestamp(time.time(), amt.BERLIN).year
    nr = (con.execute("SELECT MAX(nr) FROM sa_akten WHERE art=? AND jahr=?", (art, jahr)).fetchone()[0] or 0) + 1
    jetzt = int(time.time())
    spalten = {"art": art, "jahr": jahr, "nr": nr, "titel": titel, "status": status, "ersteller_id": k["id"], "ersteller_name": k["name"],
               "erstellt": jetzt, "aktualisiert": jetzt, **felder}
    cur = con.execute(f"INSERT INTO sa_akten ({', '.join(spalten)}) VALUES ({', '.join('?' * len(spalten))})", list(spalten.values()))
    return cur.lastrowid


def _akte(con, art, i):
    a = con.execute("SELECT * FROM sa_akten WHERE id=? AND art=?", (i, art)).fetchone() if str(i).isdigit() else None
    if not a:
        raise web.HTTPNotFound(text="Akte nicht gefunden.")
    return a


def _kontext(request):
    art = PFAD_ART.get(request.match_info["art"])
    if not art:
        raise web.HTTPNotFound()
    return art


async def _konto(request, art, schreiben=False, akte_id=None):
    """(Konto, Akte oder None); prüft Anmeldung und Rechte."""
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    a = _akte(request.app["db"], art, akte_id) if akte_id is not None else None
    if not lesen_darf(k, a if a is not None else art) or (schreiben and not schreiben_darf(k, art)):
        raise web.HTTPForbidden(text="Dafür fehlen dir die nötigen Rollen." if not schreiben else "Keine Schreibberechtigung für diese Akten.")
    return k, a


async def _form(request, art, akte_id):
    k, a = await _konto(request, art, True, akte_id)
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    return k, a, form


def _t(form, feld, n):
    return " ".join(str(form.get(feld, "")).split())[:n]


def _block(form, feld, n):
    return str(form.get(feld, "")).replace("\r\n", "\n").strip()[:n]


def _seite(request, titel, art, inhalt):
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, "s-" + art, inhalt, request["konto"], request["csrf"]))


def _marke(a):
    return amt.status_marke(MARKE.get(a["status"], "neutral"), ARTEN[a["art"]]["status"].get(a["status"], a["status"])) + \
        (" " + amt.status_marke("nein", "Geheim") if a["geheim"] else "")


def _reiter(art, aktiv):
    p = ARTEN[art]["pfad"]
    teile = [("liste", ARTEN[art]["titel"], ""), ("neu", "Neue Akte" if art == "ermittlung" else "Neues Verfahren", "neu/"), ("statistik", "Statistik", "statistik/")]
    return '<p class="reiter">' + " ".join(f'<a href="{ROOT}{p}/{u}" class="{"aktiv" if s == aktiv else ""}">{esc(t)}</a>' for s, t, u in teile) + "</p>"


# ---------------------------------------------------------------- Liste, Neu, Statistik

async def liste(request):
    art = _kontext(request)
    k, _ = await _konto(request, art)
    con, v = request.app["db"], ARTEN[art]
    q, st = request.query.get("q", "").strip()[:80], request.query.get("status", "")
    seite = int(request.query["seite"]) if request.query.get("seite", "").isdigit() and int(request.query["seite"]) > 0 else 1
    wo, par = ["art=?"], [art]
    if st in v["status"]:
        wo.append("status=?")
        par.append(st)
    if st == "offen":
        wo.append(f"status IN ({','.join('?' * len(v['offen']))})")
        par += list(v["offen"])
    if q:
        wo.append("(titel LIKE ? OR tatbestand LIKE ? OR bearbeiter_name LIKE ? OR (? || '-' || jahr || '-' || printf('%04d', nr)) LIKE ? "
                  "OR id IN (SELECT akte_id FROM sa_beteiligte WHERE name LIKE ? OR konto_id=?))")
        par += [f"%{q}%"] * 3 + [v["praefix"], f"%{q}%", f"%{q}%", q]
    rows = [a for a in con.execute(f"SELECT * FROM sa_akten WHERE {' AND '.join(wo)} ORDER BY aktualisiert DESC", par) if lesen_darf(k, a)]
    gesamt = len(rows)
    rows = rows[(seite - 1) * SEITE: seite * SEITE]
    zeilen = []
    for a in rows:
        bs = ", ".join(r["name"] for r in con.execute("SELECT name FROM sa_beteiligte WHERE akte_id=? AND rolle='Beschuldigter' LIMIT 3", (a["id"],)))
        zeilen.append((f'<a href="{ROOT}{v["pfad"]}/{a["id"]}/">{az(a)}</a>', esc(a["titel"]), esc(bs or "–"), _marke(a),
                       esc(a["bearbeiter_name"] or "–"), amt._zeit(a["aktualisiert"], False)))
    opt = '<option value="">Alle</option><option value="offen"%s>Nur offene</option>' % (" selected" if st == "offen" else "") + "".join(
        f'<option value="{s}"{" selected" if s == st else ""}>{esc(t)}</option>' for s, t in v["status"].items())
    basis = f"?q={esc(q)}&amp;status={esc(st)}"
    nav_ = (f'<a href="{basis}&amp;seite={seite - 1}">← Zurück</a>' if seite > 1 else "") + \
           (f'<a href="{basis}&amp;seite={seite + 1}">Weiter →</a>' if seite * SEITE < gesamt else "")
    inhalt = (f'<h1>{amt.ic(v["icon"])} {v["titel"]}</h1><p class="az">{gesamt} Akten sichtbar</p>{amt.meldung(request)}{_reiter(art, "liste") if schreiben_darf(k, art) else ""}'
              f'<form class="zeile" method="get"><div><label for="q">Suche (Aktenzeichen, Titel, Beteiligte, Tatbestand)</label><input type="search" id="q" name="q" value="{esc(q)}"></div>'
              f'<div><label for="st">Stand</label><select id="st" name="status">{opt}</select></div>'
              f'<button class="btn" type="submit">{amt.ic("search")}Suchen</button></form>'
              + amt.tabelle(["Aktenzeichen", "Titel", "Beschuldigte", "Stand", "Bearbeiter", "Zuletzt"], zeilen, "Keine Akten gefunden.")
              + f'<div class="seiten">{nav_}</div>')
    return _seite(request, v["titel"], art, inhalt)


async def neu(request):
    art = _kontext(request)
    k, _ = await _konto(request, art, True)
    v = ARTEN[art]
    inhalt = (f'<h1>{amt.ic(v["icon"])} {"Neue Ermittlungsakte" if art == "ermittlung" else "Neues Strafverfahren"}</h1>{amt.meldung(request)}{_reiter(art, "neu")}'
              f'<form method="post" action="{ROOT}{v["pfad"]}/neu/speichern">{amt.csrf_feld(request)}'
              f'<div><label for="t">Titel / Bezeichnung des Vorgangs</label><input type="text" id="t" name="titel" maxlength="160" style="width:100%" required></div>'
              f'<div style="margin-top:8px"><label for="tb">Tatbestand / Vorwurf</label><input type="text" id="tb" name="tatbestand" maxlength="160" list="tatbestaende" style="width:100%"></div>'
              f'<datalist id="tatbestaende">{_tatbestaende(request.app["db"])}</datalist>'
              f'<div style="margin-top:8px;display:flex;gap:12px;flex-wrap:wrap"><div><label for="tz">Tatzeit (IC)</label><input type="text" id="tz" name="tatzeit" maxlength="80"></div>'
              f'<div><label for="to">Tatort</label><input type="text" id="to" name="tatort" maxlength="120"></div></div>'
              f'<div style="margin-top:8px"><label for="b">Beschreibung / Sachverhalt</label><textarea id="b" name="beschreibung" maxlength="8000" style="min-height:160px"></textarea></div>'
              f'<div style="margin-top:8px"><label style="display:inline"><input type="checkbox" name="geheim" value="1"> Als „Geheim“ einstufen (nur Leitung, Bearbeiter, Ersteller)</label></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Akte anlegen</button></div></form>')
    return _seite(request, "Neue Akte", art, inhalt)


def _tatbestaende(con):
    return "".join(f'<option value="{esc(r[0])}">' for r in con.execute("SELECT DISTINCT tatbestand FROM sa_akten WHERE tatbestand!='' ORDER BY tatbestand LIMIT 200"))


async def neu_speichern(request):
    art = _kontext(request)
    k, _, form = await _form(request, art, None)
    con, v = request.app["db"], ARTEN[art]
    titel = _t(form, "titel", 160)
    if not titel:
        amt._umleiten(f'{ROOT}{v["pfad"]}/neu/', "Bitte einen Titel angeben.", True)
    status = "eingegangen" if art == "ermittlung" else "pruefung"
    i = _neue_akte(con, art, titel, k, status, tatbestand=_t(form, "tatbestand", 160), tatzeit=_t(form, "tatzeit", 80), tatort=_t(form, "tatort", 120),
                   beschreibung=_block(form, "beschreibung", 8000), geheim=1 if form.get("geheim") == "1" else 0,
                   bearbeiter_id=k["id"], bearbeiter_name=k["name"])
    _eintrag(con, i, "Akte angelegt", f"{v['einzel']} angelegt.", k)
    con.commit()
    amt._umleiten(f'{ROOT}{v["pfad"]}/{i}/', "Akte angelegt.")


async def statistik(request):
    art = _kontext(request)
    k, _ = await _konto(request, art)
    con, v = request.app["db"], ARTEN[art]
    alle = [a for a in con.execute("SELECT * FROM sa_akten WHERE art=?", (art,)) if lesen_darf(k, a)]
    st = {}
    tb, monate = {}, {}
    for a in alle:
        st[a["status"]] = st.get(a["status"], 0) + 1
        tb[a["tatbestand"] or "Nicht erfasst"] = tb.get(a["tatbestand"] or "Nicht erfasst", 0) + 1
        m = datetime.fromtimestamp(a["erstellt"], amt.BERLIN).strftime("%Y-%m")
        monate[m] = monate.get(m, 0) + 1
    offen = sum(n for s, n in st.items() if s in v["offen"])
    kz = [("Akten gesamt", len(alle)), ("Offen", offen)] + [(v["status"][s], st.get(s, 0)) for s in v["status"]]
    zahlen = "".join(f"<div><b>{n}</b>{esc(t)}</div>" for t, n in kz)
    inhalt = (f'<h1>{amt.ic(v["icon"])} {v["titel"]}: Statistik</h1>{_reiter(art, "statistik") if schreiben_darf(k, art) else ""}<div class="kennzahlen">{zahlen}</div>'
              f'<h2>Nach Tatbestand</h2>{amt._balken(sorted(tb.items(), key=lambda x: -x[1])[:15])}'
              f'<h2>Neue Akten pro Monat</h2>{amt._balken([(f"{m[5:]}/{m[:4]}", n) for m, n in sorted(monate.items())[-12:]])}')
    if art == "strafverfahren":
        haft = [a for a in alle if a["haft_von"] and not a["haft_bis"]]
        inhalt += f'<h2>Laufende Haft</h2><p>{len(haft)} Verfahren mit erfasstem Haftbeginn und ohne Haftende.</p>'
    return _seite(request, "Statistik", art, inhalt)


# ---------------------------------------------------------------- Akte

def _ansicht(request, k, a, con):
    art, v = a["art"], ARTEN[a["art"]]
    pfad = f'{ROOT}{v["pfad"]}/{a["id"]}/'
    w = schreiben_darf(k, art)
    csrf = amt.csrf_feld(request)
    stamm = [("Aktenzeichen", az(a)), ("Stand", _marke(a)), ("Tatbestand / Vorwurf", esc(a["tatbestand"] or "–")),
             ("Tatzeit (IC) / Tatort", esc(" · ".join(x for x in (a["tatzeit"], a["tatort"]) if x) or "–")),
             ("Bearbeiter", esc(a["bearbeiter_name"] or "–")), ("Angelegt", f'{amt._zeit(a["erstellt"])} von {esc(a["ersteller_name"])}'),
             ("Zuletzt geändert", amt._zeit(a["aktualisiert"]))]
    if a["verknuepft_id"]:
        o = con.execute("SELECT * FROM sa_akten WHERE id=?", (a["verknuepft_id"],)).fetchone()
        if o and lesen_darf(k, o):
            stamm.append(("Verknüpfte Akte", f'<a href="{ROOT}{ARTEN[o["art"]]["pfad"]}/{o["id"]}/">{az(o)}</a> ({esc(o["titel"])})'))
    html_ = f'<h1>{amt.ic(v["icon"])} {az(a)}</h1><p class="az">{esc(a["titel"])}</p>{amt.meldung(request)}' + amt.daten_tabelle(stamm)
    if a["beschreibung"]:
        html_ += f'<h2>Sachverhalt</h2><div style="white-space:pre-wrap;word-break:break-word">{esc(a["beschreibung"])}</div>'
    if art == "strafverfahren":
        html_ += "<h2>Verfahren</h2>" + amt.daten_tabelle([
            ("Gericht", esc(a["gericht"] or "–")), ("Hauptverhandlung", esc(a["termin"] or "–")), ("Urteil", f'<span style="white-space:pre-wrap">{esc(a["urteil"] or "–")}</span>'),
            ("Strafe / Maßnahme", esc(a["strafe"] or "–")), ("Haft", esc(" bis ".join(x for x in (a["haft_von"], a["haft_bis"]) if x) + (f' ({a["haft_ort"]})' if a["haft_ort"] else "") or "–"))])
    # Beteiligte
    bs = con.execute("SELECT * FROM sa_beteiligte WHERE akte_id=? ORDER BY id", (a["id"],)).fetchall()
    zeilen = [(esc(b["rolle"]), esc(b["name"]), esc(b["konto_id"] or "–"), esc(b["notiz"] or "–"),
               (f'<form method="post" action="{pfad}beteiligte/{b["id"]}/entfernen" style="margin:0">{csrf}<button class="btn zweit gefahr" type="submit" aria-label="Entfernen">{amt.ic("x")}</button></form>' if w else ""))
              for b in bs]
    html_ += "<h2>Beteiligte</h2>" + amt.tabelle(["Rolle", "Name", "Discord-ID", "Notiz", ""], zeilen, "Keine Beteiligten erfasst.")
    if w:
        rolle_opt = "".join(f"<option>{r}</option>" for r in BETEILIGTE)
        html_ += (f'<form class="zeile" method="post" action="{pfad}beteiligte">{csrf}<div><label>Rolle</label><select name="rolle">{rolle_opt}</select></div>'
                  f'<div><label>Name</label><input type="text" name="name" maxlength="100" list="personen" required></div>'
                  f'<div><label>Discord-ID (optional)</label><input type="text" name="konto_id" maxlength="25" pattern="[0-9]*"></div>'
                  f'<div><label>Notiz</label><input type="text" name="notiz" maxlength="200"></div>'
                  f'<button class="btn zweit" type="submit">{amt.ic("plus")}Hinzufügen</button></form>'
                  f'<datalist id="personen">{_personen(con)}</datalist>')
    # Beweismittel
    be = con.execute("SELECT * FROM sa_beweise WHERE akte_id=? ORDER BY id", (a["id"],)).fetchall()
    zeilen = [(f'BM-{b["id"]}', esc(b["bezeichnung"]), f'<span style="white-space:pre-wrap">{esc(b["beschreibung"] or "–")}</span>', esc(b["fundort"] or "–"),
               amt._zeit(b["zeit"], False) + "<br>" + esc(b["autor_name"])) for b in be]
    html_ += "<h2>Beweismittel</h2>" + amt.tabelle(["Nr.", "Bezeichnung", "Beschreibung", "Fundort / Quelle", "Erfasst"], zeilen, "Keine Beweismittel erfasst.")
    if w:
        html_ += (f'<form class="zeile" method="post" action="{pfad}beweis">{csrf}<div><label>Bezeichnung</label><input type="text" name="bezeichnung" maxlength="120" required></div>'
                  f'<div><label>Fundort / Quelle</label><input type="text" name="fundort" maxlength="160"></div>'
                  f'<div style="flex:1;min-width:240px"><label>Beschreibung</label><input type="text" name="beschreibung" maxlength="1000" style="width:100%"></div>'
                  f'<button class="btn zweit" type="submit">{amt.ic("plus")}Erfassen</button></form>')
    # Dateianhänge
    an = con.execute("SELECT * FROM sa_anhaenge WHERE akte_id=? ORDER BY id", (a["id"],)).fetchall()
    zeilen = [(f'AN-{x["id"]}', f'<a href="{pfad}anhang/{x["id"]}">{esc(x["dateiname"])}</a>', f'{_groesse(x["groesse"])}',
               f'<small title="{x["sha256"]}">{x["sha256"][:16]}…</small>', f'BM-{x["beweis_id"]}' if x["beweis_id"] else "–",
               amt._zeit(x["zeit"], False) + "<br>" + esc(x["autor_name"]),
               (f'<form method="post" action="{pfad}anhang/{x["id"]}/loeschen" style="margin:0">{csrf}<button class="btn zweit gefahr" type="submit" aria-label="Löschen">{amt.ic("trash-2")}</button></form>'
                if w and (_leitung(k, art) or x["autor_id"] == k["id"]) else "")) for x in an]
    html_ += "<h2>Dateianhänge</h2>" + amt.tabelle(["Nr.", "Datei", "Größe", "SHA-256", "Zu", "Hochgeladen", ""], zeilen, "Keine Anhänge.")
    if w:
        bm_opt = '<option value="">(Akte allgemein)</option>' + "".join(f'<option value="{b["id"]}">BM-{b["id"]} {esc(b["bezeichnung"])}</option>' for b in be)
        html_ += (f'<form class="zeile" method="post" action="{pfad}anhang" enctype="multipart/form-data">{csrf}'
                  f'<div><label>Datei (höchstens {ANHANG_MAX // 1048576} MB; {", ".join(ANHANG_TYPEN)})</label><input type="file" name="datei" required></div>'
                  f'<div><label>Zuordnen zu</label><select name="beweis">{bm_opt}</select></div>'
                  f'<button class="btn zweit" type="submit">{amt.ic("plus")}Hochladen</button></form>')
    # Protokoll
    es = con.execute("SELECT * FROM sa_eintraege WHERE akte_id=? ORDER BY id DESC", (a["id"],)).fetchall()
    html_ += "<h2>Aktenprotokoll</h2>" + amt.tabelle(["Zeit", "Art", "Eintrag", "Von"], [
        (amt._zeit(e["zeit"]), esc(e["art"]), f'<span style="white-space:pre-wrap">{esc(e["text"])}</span>', esc(e["autor_name"] or "System")) for e in es], "Keine Einträge.")
    if w:
        html_ += (f'<form method="post" action="{pfad}vermerk">{csrf}<label for="vm">Vermerk hinzufügen</label><textarea id="vm" name="text" maxlength="4000" required></textarea>'
                  f'<div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("pencil")}Vermerk speichern</button></div></form>')
        # Aktionen
        st_opt = "".join(f'<option value="{s}"{" selected" if s == a["status"] else ""}>{esc(t)}</option>' for s, t in v["status"].items() if not (art == "ermittlung" and s == "abgegeben"))
        html_ += f'<h2>Bearbeitung</h2><form class="zeile" method="post" action="{pfad}status">{csrf}<div><label>Stand ändern</label><select name="status">{st_opt}</select></div><button class="btn" type="submit">{amt.ic("check")}Übernehmen</button></form>'
        html_ += (f'<form class="zeile" method="post" action="{pfad}bearbeiten">{csrf}'
                  f'<div><label>Titel</label><input type="text" name="titel" value="{esc(a["titel"])}" maxlength="160"></div>'
                  f'<div><label>Tatbestand</label><input type="text" name="tatbestand" value="{esc(a["tatbestand"])}" maxlength="160" list="tatbestaende"></div>'
                  f'<div><label>Tatzeit (IC)</label><input type="text" name="tatzeit" value="{esc(a["tatzeit"])}" maxlength="80"></div>'
                  f'<div><label>Tatort</label><input type="text" name="tatort" value="{esc(a["tatort"])}" maxlength="120"></div>'
                  f'<div><label>Bearbeiter</label><select name="bearbeiter">{_bearbeiter_opt(request, a)}</select></div>'
                  f'<datalist id="tatbestaende">{_tatbestaende(con)}</datalist>'
                  f'<div style="flex:1;min-width:100%"><label>Sachverhalt</label><textarea name="beschreibung" maxlength="8000">{esc(a["beschreibung"])}</textarea></div>'
                  f'<button class="btn zweit" type="submit">{amt.ic("pencil")}Stammdaten ändern</button></form>')
        if art == "strafverfahren":
            html_ += (f'<form class="zeile" method="post" action="{pfad}verfahren">{csrf}'
                      f'<div><label>Gericht</label><input type="text" name="gericht" value="{esc(a["gericht"])}" maxlength="120"></div>'
                      f'<div><label>Hauptverhandlung (Termin)</label><input type="text" name="termin" value="{esc(a["termin"])}" maxlength="80"></div>'
                      f'<div><label>Strafe / Maßnahme</label><input type="text" name="strafe" value="{esc(a["strafe"])}" maxlength="200"></div>'
                      f'<div><label>Haft von</label><input type="text" name="haft_von" value="{esc(a["haft_von"])}" maxlength="40"></div>'
                      f'<div><label>Haft bis</label><input type="text" name="haft_bis" value="{esc(a["haft_bis"])}" maxlength="40"></div>'
                      f'<div><label>Haftort</label><input type="text" name="haft_ort" value="{esc(a["haft_ort"])}" maxlength="120"></div>'
                      f'<div style="flex:1;min-width:100%"><label>Urteil</label><textarea name="urteil" maxlength="4000">{esc(a["urteil"])}</textarea></div>'
                      f'<button class="btn zweit" type="submit">{amt.ic("gavel")}Verfahrensdaten speichern</button></form>')
        akt = ""
        if art == "ermittlung" and a["status"] in ("eingegangen", "ermittlung") and not a["verknuepft_id"]:
            akt += (f'<form method="post" action="{pfad}abgeben" style="display:inline">{csrf}<button class="btn" type="submit">{amt.ic("send")}An die Inquisition abgeben (Strafverfahren eröffnen)</button></form> ')
        if _leitung(k, art):
            akt += (f'<form method="post" action="{pfad}geheim" style="display:inline">{csrf}<input type="hidden" name="wert" value="{0 if a["geheim"] else 1}">'
                    f'<button class="btn zweit" type="submit">{amt.ic("lock-open" if a["geheim"] else "lock")}{"Geheimhaltung aufheben" if a["geheim"] else "Als Geheim einstufen"}</button></form> ')
        if akt:
            html_ += f'<div class="aktionen">{akt}</div>'
    html_ += f'<div class="aktionen"><a class="btn zweit" href="{pfad}pdf">{amt.ic("file-down")}PDF</a><a class="btn zweit" href="{ROOT}{v["pfad"]}/">{amt.ic("arrow-left")}Zur Liste</a></div>'
    return html_


def _groesse(n):
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, round(n / 1024))} kB"


def _personen(con):
    namen = [r[0] for r in con.execute("SELECT DISTINCT CASE WHEN ic_name!='' THEN ic_name ELSE name END FROM amt_akten ORDER BY 1 LIMIT 1500")]
    return "".join(f'<option value="{esc(n)}">' for n in namen)


def _bearbeiter_opt(request, a):
    # nur der aktuelle Bearbeiter sowie „mir zuweisen“; die Mitgliederliste lädt bereichs-spezifisch die Pinnwand-Seite
    k = request["konto"]
    o = '<option value="">(unverändert)</option>'
    if a["bearbeiter_id"] != k["id"]:
        o += f'<option value="{esc(k["id"])}">Mir zuweisen ({esc(k["name"])})</option>'
    return o


async def akte(request):
    art = _kontext(request)
    k, a = await _konto(request, art, False, request.match_info["id"])
    return _seite(request, az(a), art, _ansicht(request, k, a, request.app["db"]))


async def akte_pdf(request):
    art = _kontext(request)
    k, a = await _konto(request, art, False, request.match_info["id"])
    con = request.app["db"]
    request["konto"] = k
    inhalt = _ansicht(request, k, a, con)
    # Formulare und Knöpfe fürs PDF entfernen
    import re
    inhalt = re.sub(r"<form.*?</form>", "", inhalt, flags=re.S)
    inhalt = re.sub(r'<div class="aktionen">.*?</div>', "", inhalt, flags=re.S)
    inhalt = re.sub(r"<datalist.*?</datalist>", "", inhalt, flags=re.S)
    return await amt._pdf_antwort(request, az(a), f"{ARTEN[art]['einzel']} {az(a)}", inhalt)


# ---------------------------------------------------------------- Aktionen

def _fertig(request, a, text, fehler=False):
    amt._umleiten(f'{ROOT}{ARTEN[a["art"]]["pfad"]}/{a["id"]}/', text, fehler)


def _beruehren(con, a):
    con.execute("UPDATE sa_akten SET aktualisiert=? WHERE id=?", (int(time.time()), a["id"]))


async def _aktion(request):
    art = _kontext(request)
    return art, *(await _form(request, art, request.match_info["id"]))


async def status_setzen(request):
    art, k, a, form = await _aktion(request)
    con, neu = request.app["db"], str(form.get("status", ""))
    if neu not in ARTEN[art]["status"] or (art == "ermittlung" and neu == "abgegeben") or neu == a["status"]:
        _fertig(request, a, "Keine Änderung.")
    ende = int(time.time()) if neu not in ARTEN[art]["offen"] else None
    con.execute("UPDATE sa_akten SET status=?, abgeschlossen=?, aktualisiert=? WHERE id=?", (neu, ende, int(time.time()), a["id"]))
    _eintrag(con, a["id"], "Stand", f'„{ARTEN[art]["status"][a["status"]]}“ → „{ARTEN[art]["status"][neu]}“', k)
    con.commit()
    _fertig(request, a, "Stand geändert.")


async def bearbeiten(request):
    art, k, a, form = await _aktion(request)
    con = request.app["db"]
    neu = {"titel": _t(form, "titel", 160) or a["titel"], "tatbestand": _t(form, "tatbestand", 160), "tatzeit": _t(form, "tatzeit", 80),
           "tatort": _t(form, "tatort", 120), "beschreibung": _block(form, "beschreibung", 8000)}
    aend = [f"{f}: „{a[f][:60]}“ → „{w[:60]}“" for f, w in neu.items() if a[f] != w and f != "beschreibung"]
    if a["beschreibung"] != neu["beschreibung"]:
        aend.append("Sachverhalt geändert")
    if str(form.get("bearbeiter", "")) == k["id"]:
        con.execute("UPDATE sa_akten SET bearbeiter_id=?, bearbeiter_name=? WHERE id=?", (k["id"], k["name"], a["id"]))
        aend.append(f"Bearbeiter: {k['name']}")
    if not aend:
        _fertig(request, a, "Keine Änderung.")
    con.execute("UPDATE sa_akten SET titel=?, tatbestand=?, tatzeit=?, tatort=?, beschreibung=?, aktualisiert=? WHERE id=?",
                (*neu.values(), int(time.time()), a["id"]))
    _eintrag(con, a["id"], "Stammdaten geändert", "\n".join(aend), k)
    con.commit()
    _fertig(request, a, "Gespeichert.")


async def verfahren_speichern(request):
    art, k, a, form = await _aktion(request)
    if art != "strafverfahren":
        raise web.HTTPNotFound()
    con = request.app["db"]
    f = ("gericht", "termin", "strafe", "haft_von", "haft_bis", "haft_ort")
    neu = {x: _t(form, x, 200) for x in f}
    neu["urteil"] = _block(form, "urteil", 4000)
    aend = [f"{x}: „{a[x][:60]}“ → „{w[:60]}“" for x, w in neu.items() if a[x] != w]
    if not aend:
        _fertig(request, a, "Keine Änderung.")
    con.execute(f"UPDATE sa_akten SET {', '.join(x + '=?' for x in neu)}, aktualisiert=? WHERE id=?", (*neu.values(), int(time.time()), a["id"]))
    _eintrag(con, a["id"], "Verfahrensdaten", "\n".join(aend), k)
    con.commit()
    _fertig(request, a, "Verfahrensdaten gespeichert.")


async def beteiligte_hinzu(request):
    art, k, a, form = await _aktion(request)
    con = request.app["db"]
    rolle, name = _t(form, "rolle", 30), _t(form, "name", 100)
    kid = "".join(c for c in str(form.get("konto_id", "")) if c.isdigit())[:25]
    if rolle not in BETEILIGTE or not name:
        _fertig(request, a, "Rolle und Name sind nötig.", True)
    con.execute("INSERT INTO sa_beteiligte (akte_id, rolle, name, konto_id, notiz) VALUES (?,?,?,?,?)", (a["id"], rolle, name, kid, _t(form, "notiz", 200)))
    _eintrag(con, a["id"], "Beteiligter", f"{rolle}: {name}", k)
    _beruehren(con, a)
    con.commit()
    _fertig(request, a, "Beteiligter hinzugefügt.")


async def beteiligte_weg(request):
    art, k, a, _form_ = await _aktion(request)
    con, bid = request.app["db"], request.match_info["bid"]
    b = con.execute("SELECT * FROM sa_beteiligte WHERE id=? AND akte_id=?", (bid, a["id"])).fetchone() if bid.isdigit() else None
    if b:
        con.execute("DELETE FROM sa_beteiligte WHERE id=?", (b["id"],))
        _eintrag(con, a["id"], "Beteiligter entfernt", f'{b["rolle"]}: {b["name"]}', k)
        _beruehren(con, a)
        con.commit()
    _fertig(request, a, "Beteiligter entfernt.")


async def beweis(request):
    art, k, a, form = await _aktion(request)
    con = request.app["db"]
    bez = _t(form, "bezeichnung", 120)
    if not bez:
        _fertig(request, a, "Bezeichnung fehlt.", True)
    cur = con.execute("INSERT INTO sa_beweise (akte_id, bezeichnung, beschreibung, fundort, zeit, autor_name) VALUES (?,?,?,?,?,?)",
                      (a["id"], bez, _t(form, "beschreibung", 1000), _t(form, "fundort", 160), int(time.time()), k["name"]))
    _eintrag(con, a["id"], "Beweismittel", f"BM-{cur.lastrowid}: {bez}", k)
    _beruehren(con, a)
    con.commit()
    _fertig(request, a, "Beweismittel erfasst.")


async def vermerk(request):
    art, k, a, form = await _aktion(request)
    con = request.app["db"]
    text = _block(form, "text", 4000)
    if not text:
        _fertig(request, a, "Leerer Vermerk.", True)
    _eintrag(con, a["id"], "Vermerk", text, k)
    _beruehren(con, a)
    con.commit()
    _fertig(request, a, "Vermerk gespeichert.")


async def geheim(request):
    art, k, a, form = await _aktion(request)
    if not _leitung(k, art):
        raise web.HTTPForbidden(text="Nur die Leitung kann die Geheimhaltung ändern.")
    con, wert = request.app["db"], 1 if form.get("wert") == "1" else 0
    con.execute("UPDATE sa_akten SET geheim=?, aktualisiert=? WHERE id=?", (wert, int(time.time()), a["id"]))
    _eintrag(con, a["id"], "Geheimhaltung", "Als Geheim eingestuft." if wert else "Geheimhaltung aufgehoben.", k)
    con.commit()
    _fertig(request, a, "Geheimhaltung geändert.")


async def abgeben(request):
    """Ermittlungsakte an die Inquisition abgeben: legt das verknüpfte Strafverfahren an."""
    art, k, a, _form_ = await _aktion(request)
    if art != "ermittlung" or a["status"] not in ("eingegangen", "ermittlung") or a["verknuepft_id"]:
        _fertig(request, a, "Die Akte kann nicht (mehr) abgegeben werden.", True)
    con = request.app["db"]
    vid = _neue_akte(con, "strafverfahren", a["titel"], k, "pruefung", tatbestand=a["tatbestand"], tatzeit=a["tatzeit"], tatort=a["tatort"],
                     beschreibung=a["beschreibung"], geheim=a["geheim"], verknuepft_id=a["id"], bearbeiter_id="", bearbeiter_name="")
    for b in con.execute("SELECT * FROM sa_beteiligte WHERE akte_id=?", (a["id"],)).fetchall():
        con.execute("INSERT INTO sa_beteiligte (akte_id, rolle, name, konto_id, notiz) VALUES (?,?,?,?,?)", (vid, b["rolle"], b["name"], b["konto_id"], b["notiz"]))
    v = con.execute("SELECT * FROM sa_akten WHERE id=?", (vid,)).fetchone()
    for x in con.execute("SELECT * FROM sa_anhaenge WHERE akte_id=?", (a["id"],)).fetchall():
        quelle = os.path.join(ANHANG_ORDNER, x["speicher"])
        if os.path.isfile(quelle):
            neu_name = secrets.token_hex(16)
            shutil.copyfile(quelle, os.path.join(ANHANG_ORDNER, neu_name))
            con.execute("INSERT INTO sa_anhaenge (akte_id, beweis_id, dateiname, typ, groesse, sha256, speicher, zeit, autor_id, autor_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (vid, None, x["dateiname"], x["typ"], x["groesse"], x["sha256"], neu_name, x["zeit"], x["autor_id"], x["autor_name"]))
    con.execute("UPDATE sa_akten SET status='abgegeben', verknuepft_id=?, aktualisiert=? WHERE id=?", (vid, int(time.time()), a["id"]))
    _eintrag(con, a["id"], "Abgabe", f"An die Inquisition abgegeben; Strafverfahren {az(v)} eröffnet.", k)
    _eintrag(con, vid, "Eröffnet", f"Aus Ermittlungsakte {az(a)} des KRS übernommen (Beteiligte übernommen; Beweismittel in der Ermittlungsakte).", k)
    con.execute("INSERT INTO bereich_mitteilungen (bereich, autor_id, autor_name, titel, text, zeit) VALUES ('inquisition',?,?,?,?,?)",
                (k["id"], "System (KRS-Abgabe)", f"Neue Abgabe: {az(a)} → {az(v)}", f'Das KRS hat „{a["titel"]}“ an die Inquisition abgegeben. Strafverfahren {az(v)} wurde eröffnet.', int(time.time())))
    con.commit()
    amt._umleiten(f'{ROOT}strafverfahren/{vid}/', f"Abgegeben, Strafverfahren {az(v)} eröffnet.")


def _dateiname(roh):
    name = os.path.basename(str(roh or "").replace("\\", "/"))
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*\x7f')
    return name.strip(". ")[:120] or "datei"


async def anhang_hoch(request):
    art = _kontext(request)
    k, a = await _konto(request, art, True, request.match_info["id"])
    con = request.app["db"]
    ziel = f'{ROOT}{ARTEN[art]["pfad"]}/{a["id"]}/'
    if con.execute("SELECT COUNT(*) FROM sa_anhaenge WHERE akte_id=?", (a["id"],)).fetchone()[0] >= ANHANG_PRO_AKTE:
        amt._umleiten(ziel, f"Höchstens {ANHANG_PRO_AKTE} Anhänge je Akte.", True)
    os.makedirs(ANHANG_ORDNER, exist_ok=True)
    felder, tmp, groesse, sha, kopf, name = {}, None, 0, hashlib.sha256(), b"", ""
    try:
        reader = await request.multipart()
        while True:
            teil = await reader.next()
            if teil is None:
                break
            if teil.name in ("csrf", "beweis"):
                felder[teil.name] = (await teil.text())[:60]
            elif teil.name == "datei" and teil.filename:
                if not secrets.compare_digest(felder.get("csrf", ""), request["csrf"]):
                    raise web.HTTPForbidden(text="Ungültige Anfrage.")
                name = _dateiname(teil.filename)
                tmp = os.path.join(ANHANG_ORDNER, "tmp-" + secrets.token_hex(8))
                with open(tmp, "wb") as fh:
                    while True:
                        stueck = await teil.read_chunk(65536)
                        if not stueck:
                            break
                        groesse += len(stueck)
                        if groesse > ANHANG_MAX:
                            raise ValueError(f"Die Datei ist größer als {ANHANG_MAX // 1048576} MB.")
                        if len(kopf) < 4096:
                            kopf += stueck[:4096 - len(kopf)]
                        sha.update(stueck)
                        fh.write(stueck)
        if not tmp or not groesse:
            raise ValueError("Keine Datei übermittelt.")
        endung = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        typ = ANHANG_TYPEN.get(endung)
        if not typ or not typ[1](kopf):
            raise ValueError("Dateityp nicht erlaubt oder Inhalt passt nicht zur Endung (erlaubt: " + ", ".join(ANHANG_TYPEN) + ").")
        beweis = felder.get("beweis", "")
        bid = int(beweis) if beweis.isdigit() and con.execute("SELECT 1 FROM sa_beweise WHERE id=? AND akte_id=?", (beweis, a["id"])).fetchone() else None
        speicher = secrets.token_hex(16)
        os.replace(tmp, os.path.join(ANHANG_ORDNER, speicher))
        tmp = None
        cur = con.execute("INSERT INTO sa_anhaenge (akte_id, beweis_id, dateiname, typ, groesse, sha256, speicher, zeit, autor_id, autor_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (a["id"], bid, name, endung, groesse, sha.hexdigest(), speicher, int(time.time()), k["id"], k["name"]))
        _eintrag(con, a["id"], "Anhang", f"AN-{cur.lastrowid}: {name} ({_groesse(groesse)}, SHA-256 {sha.hexdigest()[:16]}…)" + (f", zu BM-{bid}" if bid else ""), k)
        _beruehren(con, a)
        con.commit()
    except ValueError as e:
        amt._umleiten(ziel, str(e), True)
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    amt._umleiten(ziel, "Anhang hochgeladen.")


def _anhang(con, a, aid):
    x = con.execute("SELECT * FROM sa_anhaenge WHERE id=? AND akte_id=?", (aid, a["id"])).fetchone() if str(aid).isdigit() else None
    if not x:
        raise web.HTTPNotFound(text="Anhang nicht gefunden.")
    return x


async def anhang_laden(request):
    art = _kontext(request)
    k, a = await _konto(request, art, False, request.match_info["id"])
    x = _anhang(request.app["db"], a, request.match_info["aid"])
    pfad = os.path.join(ANHANG_ORDNER, x["speicher"])
    if not os.path.isfile(pfad):
        raise web.HTTPNotFound(text="Die Datei fehlt auf dem Server.")
    return web.FileResponse(pfad, headers={
        "Content-Type": ANHANG_TYPEN.get(x["typ"], ("application/octet-stream",))[0],
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(x['dateiname'])}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox"})


async def anhang_weg(request):
    art, k, a, _form_ = await _aktion(request)
    con = request.app["db"]
    x = _anhang(con, a, request.match_info["aid"])
    if not (_leitung(k, art) or x["autor_id"] == k["id"]):
        raise web.HTTPForbidden(text="Nur der Hochladende oder die Leitung kann Anhänge löschen.")
    con.execute("DELETE FROM sa_anhaenge WHERE id=?", (x["id"],))
    if not con.execute("SELECT 1 FROM sa_anhaenge WHERE speicher=?", (x["speicher"],)).fetchone():
        try:
            os.remove(os.path.join(ANHANG_ORDNER, x["speicher"]))
        except FileNotFoundError:
            pass
    _eintrag(con, a["id"], "Anhang gelöscht", f'AN-{x["id"]}: {x["dateiname"]} (SHA-256 {x["sha256"][:16]}…)', k)
    _beruehren(con, a)
    con.commit()
    _fertig(request, a, "Anhang gelöscht.")


def registrieren(app):
    einrichten(app["db"])
    r, p = app.router, ROOT + "{art}/"
    r.add_get(p, liste)
    r.add_get(p + "neu/", neu)
    r.add_post(p + "neu/speichern", neu_speichern)
    r.add_get(p + "statistik/", statistik)
    r.add_get(p + "{id}/", akte)
    r.add_get(p + "{id}/pdf", akte_pdf)
    for n, h in (("status", status_setzen), ("bearbeiten", bearbeiten), ("verfahren", verfahren_speichern), ("beteiligte", beteiligte_hinzu),
                 ("beweis", beweis), ("vermerk", vermerk), ("geheim", geheim), ("abgeben", abgeben)):
        r.add_post(p + "{id}/" + n, h)
    r.add_post(p + "{id}/beteiligte/{bid}/entfernen", beteiligte_weg)
    r.add_post(p + "{id}/anhang", anhang_hoch)
    r.add_get(p + "{id}/anhang/{aid}", anhang_laden)
    r.add_post(p + "{id}/anhang/{aid}/loeschen", anhang_weg)
