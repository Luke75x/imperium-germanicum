"""Reichshaushalt: Etat je Behörde und Haushaltsjahr (…/intern/haushalt/).

Sichtbar und bearbeitbar NUR für Kaiser, Kronkanzler und den Staatssekretär für Finanzen und Wirtschaft (ROLLE_FINANZEN, Discord-Rolle
wird nachgetragen; solange leer, haben nur Kaiser und Kronkanzler Zugang). Die Behörden selbst sehen ihren Etat nicht.

Haushaltsjahr: Entwurf → festgestellt. Im Entwurf sind Ansätze frei änderbar; nach der Feststellung nur noch per Nachtrag mit Begründung.
Buchungen (Kassenanordnungen KA-JJJJ-NNNN) sind Ausgaben oder Einnahmen einer Behörde. Eine Ausgabe über den verfügbaren Ansatz hinaus
ist eine überplanmäßige Ausgabe und braucht eine Begründung. Buchungen werden nicht gelöscht, sondern storniert (mit Grund).
Beträge in Pfennig (INTEGER), Anzeige in Mark. Tabellen: hh_jahre, hh_ansaetze, hh_buchungen, hh_protokoll.
"""
import re
import secrets
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation

from aiohttp import web

import amt
import anmeldung
import bereiche

esc = amt.esc
BASIS = amt.BASIS
PFAD = BASIS + "haushalt/"
ROLLE_FINANZEN = ""   # Staatssekretär für Finanzen und Wirtschaft – Rollen-ID folgt
MAX_BETRAG = 10 ** 15   # Pfennig

SCHEMA = """
CREATE TABLE IF NOT EXISTS hh_jahre (
    jahr INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'entwurf', festgestellt INTEGER, festgestellt_von TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS hh_ansaetze (
    jahr INTEGER NOT NULL, stelle TEXT NOT NULL, betrag INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (jahr, stelle));
CREATE TABLE IF NOT EXISTS hh_buchungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, jahr INTEGER NOT NULL, nr INTEGER NOT NULL, stelle TEXT NOT NULL, art TEXT NOT NULL,
    betrag INTEGER NOT NULL, zweck TEXT NOT NULL, empfaenger TEXT NOT NULL DEFAULT '', datum TEXT NOT NULL DEFAULT '',
    ueberplan INTEGER NOT NULL DEFAULT 0, begruendung TEXT NOT NULL DEFAULT '', storniert INTEGER, storno_grund TEXT NOT NULL DEFAULT '',
    storno_von TEXT NOT NULL DEFAULT '', autor_id TEXT NOT NULL, autor_name TEXT NOT NULL, zeit INTEGER NOT NULL, UNIQUE (jahr, nr));
CREATE INDEX IF NOT EXISTS hh_buchungen_js ON hh_buchungen (jahr, stelle);
CREATE TABLE IF NOT EXISTS hh_protokoll (
    id INTEGER PRIMARY KEY AUTOINCREMENT, jahr INTEGER NOT NULL, stelle TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL, art TEXT NOT NULL,
    text TEXT NOT NULL, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS hh_protokoll_js ON hh_protokoll (jahr, stelle);
"""

amt.ICONS.update({
    "landmark-coins": '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>',
})
amt._ART_ICON[0:0] = [("ansatz", "pencil", ""), ("nachtrag", "pencil", "rot"), ("festgestellt", "check", "ok"), ("ausgabe", "landmark-coins", ""),
                      ("einnahme", "landmark-coins", "ok"), ("storno", "undo-2", "rot")]


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def darf(k):
    return bool(k) and k["mitglied"] and (bereiche._alle(k) or (bool(ROLLE_FINANZEN) and ROLLE_FINANZEN in k["rollen"]))


def stellen():
    return [{"id": "kanzlei", "name": "Kronkanzlei"}, {"id": "rv", "name": "Reichsverwaltung"}] + \
           [{"id": b["schl"], "name": b["name"]} for b in amt.BEHOERDEN]


def _stelle(sid):
    s = next((s for s in stellen() if s["id"] == sid), None)
    if not s:
        raise web.HTTPNotFound(text="Behörde nicht gefunden.")
    return s


def mark(pf, vorzeichen=False):
    neg = pf < 0
    m, p = divmod(abs(pf), 100)
    t = f"{m:,}".replace(",", ".") + f",{p:02d} M"
    return ("−" if neg else "+" if vorzeichen and pf > 0 else "") + t


def betrag_lesen(s):
    """'1.234,56', '1234.56', '1234' … → Pfennig (None bei Unsinn)."""
    s = re.sub(r"[\sℳM]|Mark", "", str(s or ""))
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    pf = int((d * 100).to_integral_value())
    return pf if 0 <= pf <= MAX_BETRAG else None


def az(b):
    return f'KA-{b["jahr"]}-{b["nr"]:04d}'


def nav(k):
    return [("haushalt", "landmark-coins", "Haushalt", "haushalt/")] if darf(k) else []


def _jahr_status(con, jahr):
    z = con.execute("SELECT * FROM hh_jahre WHERE jahr=?", (jahr,)).fetchone()
    return z


def _summen(con, jahr):
    """stelle -> {ansatz, ausgaben, einnahmen, ueberplan}."""
    d = {s["id"]: {"ansatz": 0, "ausgaben": 0, "einnahmen": 0, "ueberplan": 0} for s in stellen()}
    for r in con.execute("SELECT stelle, betrag FROM hh_ansaetze WHERE jahr=?", (jahr,)):
        d.setdefault(r["stelle"], {"ansatz": 0, "ausgaben": 0, "einnahmen": 0, "ueberplan": 0})["ansatz"] = r["betrag"]
    for r in con.execute("SELECT stelle, art, SUM(betrag) s, SUM(ueberplan) u FROM hh_buchungen WHERE jahr=? AND storniert IS NULL GROUP BY stelle, art", (jahr,)):
        e = d.setdefault(r["stelle"], {"ansatz": 0, "ausgaben": 0, "einnahmen": 0, "ueberplan": 0})
        e["ausgaben" if r["art"] == "ausgabe" else "einnahmen"] = r["s"] or 0
        if r["art"] == "ausgabe":
            e["ueberplan"] = r["u"] or 0
    return d


def _protokoll(con, jahr, stelle, art, text, k):
    con.execute("INSERT INTO hh_protokoll (jahr, stelle, zeit, art, text, autor_id, autor_name) VALUES (?,?,?,?,?,?,?)",
                (jahr, stelle, int(time.time()), art, text, k["id"], k["name"]))


# ---------------------------------------------------------------- Rahmen

async def _konto(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    return k


def _kein(request, k):
    return web.Response(status=403, content_type="text/html", text=amt.rahmen(
        "Kein Zugang", "haushalt", '<div class="warnung">Der Reichshaushalt ist dem Kaiser, dem Kronkanzler und dem Staatssekretär für Finanzen '
                                   'und Wirtschaft vorbehalten.</div>', k, request["csrf"]))


async def _form(request):
    k = await _konto(request)
    if not darf(k):
        raise web.HTTPForbidden(text="Kein Zugang zum Reichshaushalt.")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    return k, form


def _jahr(request):
    j = request.match_info.get("jahr", "")
    if not j.isdigit() or not 1900 <= int(j) <= 2200:
        raise web.HTTPNotFound()
    return int(j)


CSS = """<style>.hh-zahl{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.hh-balken{height:8px;border-radius:4px;background:var(--hell);overflow:hidden;min-width:80px}.hh-balken i{display:block;height:100%;background:var(--ink)}
.hh-balken.ueber i{background:var(--rot)}.hh-text{white-space:pre-wrap;word-break:break-word}.hh-storno td{color:var(--grau)}.hh-storno .hh-zahl{text-decoration:line-through}
.kennzahlen.hh-kz b{font-size:20px!important;white-space:nowrap}</style>"""


def _seite(request, k, titel, inhalt):
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, "haushalt", CSS + inhalt, k, request["csrf"]))


def _balken(ausg, ansatz):
    if not ansatz:
        return '<div class="hh-balken ueber"><i style="width:100%"></i></div>' if ausg else "–"
    p = ausg * 100 / ansatz
    return (f'<div class="hh-balken{" ueber" if p > 100 else ""}" title="{p:.0f} %"><i style="width:{min(p, 100):.1f}%"></i></div>'
            f'<small>{p:.0f} %</small>')


def _status_marke(z):
    return amt.status_marke("ok", "Festgestellt") if z and z["status"] == "festgestellt" else amt.status_marke("offen", "Entwurf")


# ---------------------------------------------------------------- Seiten

async def start(request):
    k = await _konto(request)
    if not darf(k):
        return _kein(request, k)
    raise web.HTTPFound(f"{PFAD}{datetime.now(amt.BERLIN).year}/")


def _jahr_uebersicht(con, jahr, z, druck=False):
    s = _summen(con, jahr)
    zeilen, ges = [], {"ansatz": 0, "ausgaben": 0, "einnahmen": 0}
    for st in stellen():
        e = s[st["id"]]
        for x in ges:
            ges[x] += e[x]
        verf = e["ansatz"] - e["ausgaben"]
        name = esc(st["name"]) if druck else f'<a href="{PFAD}{jahr}/{st["id"]}/">{esc(st["name"])}</a>'
        zeilen.append((name, f'<span class="hh-zahl">{mark(e["ansatz"])}</span>', f'<span class="hh-zahl">{mark(e["ausgaben"])}</span>',
                       f'<span class="hh-zahl">{mark(e["einnahmen"])}</span>',
                       f'<span class="hh-zahl{" s-nein" if verf < 0 else ""}">{mark(verf)}</span>', _balken(e["ausgaben"], e["ansatz"])))
    zeilen.append(("<b>Reichshaushalt gesamt</b>", *[f'<b class="hh-zahl">{mark(ges[x])}</b>' for x in ("ansatz", "ausgaben", "einnahmen")],
                   f'<b class="hh-zahl">{mark(ges["ansatz"] - ges["ausgaben"])}</b>', _balken(ges["ausgaben"], ges["ansatz"])))
    zahlen = "".join(f"<div><b>{v}</b>{esc(t)}</div>" for t, v in [
        ("Haushaltsvolumen", mark(ges["ansatz"])), ("Ausgaben", mark(ges["ausgaben"])), ("Einnahmen", mark(ges["einnahmen"])),
        ("Saldo (Einnahmen − Ausgaben)", mark(ges["einnahmen"] - ges["ausgaben"], True))])
    return (f'<div class="kennzahlen hh-kz">{zahlen}</div><h2>Einzelpläne der Behörden</h2>'
            + amt.tabelle(["Behörde", "Ansatz", "Ausgaben", "Einnahmen", "Verfügbar", "Auslastung"], zeilen)
            )


async def jahr_seite(request):
    k = await _konto(request)
    if not darf(k):
        return _kein(request, k)
    con, jahr = request.app["db"], _jahr(request)
    z = _jahr_status(con, jahr)
    vorh = {r[0] for r in con.execute("SELECT jahr FROM hh_jahre")} | {jahr, datetime.now(amt.BERLIN).year, datetime.now(amt.BERLIN).year + 1}
    wahl = " ".join(f'<a href="{PFAD}{j}/" class="{"aktiv" if j == jahr else ""}">{j}</a>' for j in sorted(vorh))
    csrf = amt.csrf_feld(request)
    fest = ""
    if not z or z["status"] != "festgestellt":
        fest = (f'<form method="post" action="{PFAD}{jahr}/feststellen" class="hh-fest">{csrf}<p class="az">Mit der Feststellung wird der Haushaltsplan '
                'verbindlich; Ansätze ändern sich danach nur noch per Nachtrag mit Begründung.</p>'
                f'<button class="btn" type="submit">{amt.ic("check")}Haushaltsplan {jahr} feststellen</button></form>')
    prot = con.execute("SELECT * FROM hh_protokoll WHERE jahr=? ORDER BY id DESC LIMIT 15", (jahr,)).fetchall()
    namen = {s["id"]: s["name"] for s in stellen()}
    prot = [dict(p, text=(f'{namen.get(p["stelle"], p["stelle"])}: ' if p["stelle"] else "") + p["text"]) for p in prot]
    inhalt = (f'<h1>{amt.ic("landmark-coins")} Reichshaushalt {jahr}</h1><p class="az">Haushaltsplan · {_status_marke(z)}'
              + (f' am {amt._zeit(z["festgestellt"], False)} durch {esc(z["festgestellt_von"])}' if z and z["festgestellt"] else "") + "</p>"
              + amt.meldung(request) + f'<p class="reiter">{wahl}</p>' + _jahr_uebersicht(con, jahr, z)
              + f'<div class="aktionen"><a class="btn zweit" href="{PFAD}{jahr}/pdf">{amt.ic("file-down")}Haushaltsplan als PDF</a></div>'
              + fest + '<h2>Letzte Vorgänge</h2>' + amt.verlauf_html(prot, "Noch keine Vorgänge."))
    return _seite(request, k, f"Reichshaushalt {jahr}", inhalt)


async def jahr_pdf(request):
    k = await _konto(request)
    if not darf(k):
        raise web.HTTPForbidden()
    con, jahr = request.app["db"], _jahr(request)
    z = _jahr_status(con, jahr)
    inhalt = (CSS + f'<h1>Haushaltsplan des Reiches {jahr}</h1><p class="az">{"Festgestellt" if z and z["status"] == "festgestellt" else "Entwurf"} · '
              f'Stand {amt._zeit(int(time.time()))}</p>' + _jahr_uebersicht(con, jahr, z, True))
    return await amt._pdf_antwort(request, f"haushaltsplan-{jahr}", f"Haushaltsplan {jahr}", inhalt)


async def feststellen(request):
    k, _ = await _form(request)
    con, jahr = request.app["db"], _jahr(request)
    z = _jahr_status(con, jahr)
    if z and z["status"] == "festgestellt":
        amt._umleiten(f"{PFAD}{jahr}/", "Bereits festgestellt.", True)
    jetzt = int(time.time())
    con.execute("INSERT INTO hh_jahre (jahr, status, festgestellt, festgestellt_von) VALUES (?, 'festgestellt', ?, ?) "
                "ON CONFLICT(jahr) DO UPDATE SET status='festgestellt', festgestellt=excluded.festgestellt, festgestellt_von=excluded.festgestellt_von",
                (jahr, jetzt, k["name"]))
    ges = sum(e["ansatz"] for e in _summen(con, jahr).values())
    _protokoll(con, jahr, "", "Festgestellt", f"Haushaltsplan {jahr} festgestellt, Volumen {mark(ges)}.", k)
    con.commit()
    amt._umleiten(f"{PFAD}{jahr}/", f"Haushaltsplan {jahr} festgestellt.")


async def stelle_seite(request):
    k = await _konto(request)
    if not darf(k):
        return _kein(request, k)
    con, jahr = request.app["db"], _jahr(request)
    st = _stelle(request.match_info["stelle"])
    z = _jahr_status(con, jahr)
    festg = bool(z and z["status"] == "festgestellt")
    e = _summen(con, jahr)[st["id"]]
    p = f'{PFAD}{jahr}/{st["id"]}/'
    csrf = amt.csrf_feld(request)
    verf = e["ansatz"] - e["ausgaben"]
    zahlen = "".join(f"<div><b>{v}</b>{esc(t)}</div>" for t, v in [
        ("Ansatz", mark(e["ansatz"])), ("Ausgaben", mark(e["ausgaben"])), ("Einnahmen", mark(e["einnahmen"])), ("Verfügbar", mark(verf)),
        ("davon überplanmäßig", mark(e["ueberplan"]))])
    buch = con.execute("SELECT * FROM hh_buchungen WHERE jahr=? AND stelle=? ORDER BY id DESC", (jahr, st["id"])).fetchall()
    zeilen = []
    for b in buch:
        storno = "" if b["storniert"] else (
            f'<details><summary class="btn zweit klein">{amt.ic("undo-2")}Storno</summary><form method="post" action="{p}buchung/{b["id"]}/storno">{csrf}'
            f'<input type="text" name="grund" maxlength="300" placeholder="Grund (Pflicht)" required>'
            f'<button class="btn zweit gefahr" type="submit">Stornieren</button></form></details>')
        zeilen.append((az(b), esc(b["datum"] or amt._zeit(b["zeit"], False)), "Ausgabe" if b["art"] == "ausgabe" else "Einnahme",
                       esc(b["zweck"]) + (f'<br><small>an/von: {esc(b["empfaenger"])}</small>' if b["empfaenger"] else "")
                       + (f'<br>{amt.status_marke("nein", "überplanmäßig")} <small>{esc(b["begruendung"])}</small>' if b["ueberplan"] else "")
                       + (f'<br>{amt.status_marke("neutral", "storniert")} <small>{esc(b["storno_grund"])} ({esc(b["storno_von"])})</small>' if b["storniert"] else ""),
                       f'<span class="hh-zahl">{mark(-b["betrag"] if b["art"] == "ausgabe" else b["betrag"], True)}</span>',
                       f'<small>{esc(b["autor_name"])}</small>{storno}'))
    tabelle = amt.tabelle(["Kassenanordnung", "Datum", "Art", "Zweck", "Betrag", "Angewiesen"], zeilen, "Noch keine Buchungen.")
    # Storno-Zeilen grau
    for b in buch:
        if b["storniert"]:
            tabelle = tabelle.replace(f'<tr><td data-l="Kassenanordnung">{az(b)}', f'<tr class="hh-storno"><td data-l="Kassenanordnung">{az(b)}', 1)
    f = amt._feld
    ansatz_form = (f'<h2>{"Nachtrag zum Ansatz" if festg else "Ansatz festlegen"}</h2>'
                   f'<form class="formular" method="post" action="{p}ansatz">{csrf}<div class="felder">'
                   + f("an", "Neuer Ansatz (Mark)", f'<input type="text" id="an" name="betrag" inputmode="decimal" value="{mark(e["ansatz"])[:-2]}" required>')
                   + f("ab", "Begründung" + (" (Pflicht)" if festg else ""), f'<input type="text" id="ab" name="begruendung" maxlength="300"{" required" if festg else ""}>')
                   + f'</div><div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}{"Nachtrag buchen" if festg else "Ansatz speichern"}</button></div></form>')
    buch_form = (f'<h2>Kassenanordnung erfassen</h2><form class="formular" method="post" action="{p}buchung">{csrf}<div class="felder">'
                 + f("ba", "Art", '<select id="ba" name="art"><option value="ausgabe">Ausgabe</option><option value="einnahme">Einnahme</option></select>')
                 + f("bb", "Betrag (Mark)", '<input type="text" id="bb" name="betrag" inputmode="decimal" placeholder="z. B. 1.250,00" required>')
                 + f("bz", "Zweck", '<input type="text" id="bz" name="zweck" maxlength="200" required>').replace('class="feld"', 'class="feld breit"')
                 + f("be", "Empfänger / Einzahler", '<input type="text" id="be" name="empfaenger" maxlength="160">')
                 + f("bd", "Datum (IC)", '<input type="text" id="bd" name="datum" maxlength="40">')
                 + f("bu", "Begründung bei überplanmäßiger Ausgabe", '<input type="text" id="bu" name="begruendung" maxlength="300">',
                     f"Nur nötig, wenn die Ausgabe den verfügbaren Betrag ({mark(verf)}) übersteigt.").replace('class="feld"', 'class="feld breit"')
                 + f'</div><div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Anweisen</button></div></form>')
    prot = con.execute("SELECT * FROM hh_protokoll WHERE jahr=? AND stelle=? ORDER BY id DESC", (jahr, st["id"])).fetchall()
    inhalt = (f'<p class="zurueck"><a href="{PFAD}{jahr}/">{amt.ic("arrow-left")}Reichshaushalt {jahr}</a></p>'
              f'<h1>{amt.ic("landmark-coins")} Einzelplan: {esc(st["name"])}</h1><p class="az">Haushaltsjahr {jahr} · {_status_marke(z)}</p>'
              + amt.meldung(request) + f'<div class="kennzahlen hh-kz">{zahlen}</div>'
              + f'<p>{_balken(e["ausgaben"], e["ansatz"])}</p>'
              + '<h2>Buchungen</h2>' + tabelle + buch_form + ansatz_form
              + '<style>details summary.klein{padding:4px 10px;font-size:13px;margin-top:4px}details form{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}</style>'
              + '<h2>Verlauf</h2>' + amt.verlauf_html(prot, "Noch keine Vorgänge."))
    return _seite(request, k, f'{st["name"]} {jahr}', inhalt)


async def ansatz(request):
    k, form = await _form(request)
    con, jahr = request.app["db"], _jahr(request)
    st = _stelle(request.match_info["stelle"])
    p = f'{PFAD}{jahr}/{st["id"]}/'
    neu = betrag_lesen(form.get("betrag"))
    if neu is None:
        amt._umleiten(p, "Ungültiger Betrag.", True)
    z = _jahr_status(con, jahr)
    festg = bool(z and z["status"] == "festgestellt")
    begr = amt._text(form, "begruendung", 300)
    if festg and not begr:
        amt._umleiten(p, "Ein Nachtrag braucht eine Begründung.", True)
    alt = _summen(con, jahr)[st["id"]]["ansatz"]
    if neu == alt:
        amt._umleiten(p, "Keine Änderung.")
    con.execute("INSERT INTO hh_ansaetze (jahr, stelle, betrag) VALUES (?,?,?) ON CONFLICT(jahr, stelle) DO UPDATE SET betrag=excluded.betrag",
                (jahr, st["id"], neu))
    _protokoll(con, jahr, st["id"], "Nachtrag" if festg else "Ansatz", f"„{mark(alt)}“ → „{mark(neu)}“" + (f"\n{begr}" if begr else ""), k)
    con.commit()
    amt._umleiten(p, "Nachtrag gebucht." if festg else "Ansatz gespeichert.")


async def buchung(request):
    k, form = await _form(request)
    con, jahr = request.app["db"], _jahr(request)
    st = _stelle(request.match_info["stelle"])
    p = f'{PFAD}{jahr}/{st["id"]}/'
    art = str(form.get("art", ""))
    betrag = betrag_lesen(form.get("betrag"))
    zweck = amt._text(form, "zweck", 200)
    if art not in ("ausgabe", "einnahme") or not betrag or not zweck:
        amt._umleiten(p, "Art, Betrag (größer 0) und Zweck sind Pflicht.", True)
    e = _summen(con, jahr)[st["id"]]
    begr = amt._text(form, "begruendung", 300)
    ueber = art == "ausgabe" and e["ausgaben"] + betrag > e["ansatz"]
    if ueber and not begr:
        amt._umleiten(p, f"Überplanmäßige Ausgabe: verfügbar sind nur {mark(e['ansatz'] - e['ausgaben'])}. Bitte begründen.", True)
    nr = (con.execute("SELECT MAX(nr) FROM hh_buchungen WHERE jahr=?", (jahr,)).fetchone()[0] or 0) + 1
    con.execute("INSERT INTO hh_buchungen (jahr, nr, stelle, art, betrag, zweck, empfaenger, datum, ueberplan, begruendung, autor_id, autor_name, zeit) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (jahr, nr, st["id"], art, betrag, zweck, amt._text(form, "empfaenger", 160),
                                                       amt._text(form, "datum", 40), betrag if ueber else 0, begr if ueber else "", k["id"], k["name"], int(time.time())))
    nummer = az({"jahr": jahr, "nr": nr})
    _protokoll(con, jahr, st["id"], "Ausgabe" if art == "ausgabe" else "Einnahme",
               f"{nummer}: {mark(betrag)} – {zweck}" + (f"\nÜberplanmäßig: {begr}" if ueber else ""), k)
    con.commit()
    amt._umleiten(p, f"Kassenanordnung {nummer} angewiesen.")


async def storno(request):
    k, form = await _form(request)
    con, jahr = request.app["db"], _jahr(request)
    st = _stelle(request.match_info["stelle"])
    p = f'{PFAD}{jahr}/{st["id"]}/'
    i = request.match_info["id"]
    b = con.execute("SELECT * FROM hh_buchungen WHERE id=? AND jahr=? AND stelle=?", (i, jahr, st["id"])).fetchone() if i.isdigit() else None
    if not b:
        raise web.HTTPNotFound()
    grund = amt._text(form, "grund", 300)
    if b["storniert"] or not grund:
        amt._umleiten(p, "Bereits storniert oder Grund fehlt.", True)
    con.execute("UPDATE hh_buchungen SET storniert=?, storno_grund=?, storno_von=? WHERE id=?", (int(time.time()), grund, k["name"], b["id"]))
    _protokoll(con, jahr, st["id"], "Storno", f"{az(b)} ({mark(b['betrag'])}) storniert: {grund}", k)
    con.commit()
    amt._umleiten(p, f"{az(b)} storniert.")


def registrieren(app):
    einrichten(app["db"])
    amt.NAV_EXTRA.append(("Finanzen", nav))
    app.router.add_get(PFAD, start)
    app.router.add_get(PFAD + "{jahr}/", jahr_seite)
    app.router.add_get(PFAD + "{jahr}/pdf", jahr_pdf)
    app.router.add_post(PFAD + "{jahr}/feststellen", feststellen)
    app.router.add_get(PFAD + "{jahr}/{stelle}/", stelle_seite)
    app.router.add_post(PFAD + "{jahr}/{stelle}/ansatz", ansatz)
    app.router.add_post(PFAD + "{jahr}/{stelle}/buchung", buchung)
    app.router.add_post(PFAD + "{jahr}/{stelle}/buchung/{id}/storno", storno)
