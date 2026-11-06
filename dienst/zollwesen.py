"""Zollwesen: Grenzkontrolle im Tab „Zoll“ und Sichtvermerke (Stempel) in Pässen.

- Tab Zoll (…/intern/bereich/zoll/, Hook bereiche.ZUSATZ["zoll"]): QR-Scanner (personenseite.scanner, Ziel mit ?von=zoll),
  Passnummer-Eingabe (…/bereich/zoll/grenze?nr=), zuletzt gesetzte Stempel.
- Prüfseite …/intern/passpruefung/<nr>/ (Hook personenseite.PASS_ABSCHNITT): Sichtvermerke des Passes als Stempelbilder,
  für Zoll (und Kanzler/Kaiser/Admins OOC) das Formular „Stempel setzen“: Einreise, Ausreise, Durchreise, Visum (mit Gültigkeit, Zweck).
  POST …/passpruefung/<nr>/stempel, Löschen …/stempel/<id>/loeschen (eigener Stempel binnen 24 h, Zoll-Leitung, Kanzler/Kaiser).
- Nur gültige Passhefte (kein Personalausweis). Jeder Stempel/jede Löschung steht im Pass-Verlauf (pw_eintraege).
- Darstellung: stempel_html() – SVG mit Doppelrahmen, Reichsadler (Maske pass_bilder/stempel_adler.png aus werkzeuge/stempel_adler.py),
  Art, Datum, Grenzübergangsstelle, Stempelnummer des Beamten; Tintenstruktur per SVG-Filter, leicht gedreht. Erscheint im digitalen
  Pass und in der Druckvorlage auf den Sichtvermerkseiten 1–4 (je 4 Stempel, bei mehr die neuesten 16).
Tabelle zv_stempel.
"""
import hashlib
import secrets
import re
import time
from datetime import date, datetime
from urllib.parse import quote

from aiohttp import web

import amt
import anmeldung
import bereiche
import meldewesen

esc = amt.esc
BASIS = amt.BASIS
PRUEF = meldewesen.PRUEF
ZOLL = BASIS + "bereich/zoll/"

SCHEMA = """
CREATE TABLE IF NOT EXISTS zv_stempel (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pass_id INTEGER NOT NULL, art TEXT NOT NULL, ort TEXT NOT NULL, datum TEXT NOT NULL,
    gueltig_bis TEXT NOT NULL DEFAULT '', zweck TEXT NOT NULL DEFAULT '', bemerkung TEXT NOT NULL DEFAULT '',
    beamter_id TEXT NOT NULL, beamter_name TEXT NOT NULL, zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS zv_stempel_p ON zv_stempel (pass_id);
"""

# Art -> (Beschriftung auf dem Stempel, Anzeigename, Tintenfarbe)
ARTEN = {"einreise": ("EINREISE", "Einreise", "#1d4f9c"), "ausreise": ("AUSREISE", "Ausreise", "#a3141f"),
         "durchreise": ("DURCHREISE", "Durchreise", "#1f6b3a"), "visum": ("VISUM", "Visum", "#5b2d86")}
ZWECKE = ["Tourismus", "Besuch", "Geschäftsreise", "Arbeit", "Studium", "Diplomatisch", "Durchreise", "Sonstiges"]
HEFTE = ("reisepass", "dienstpass", "vorlaeufig", "fremdenpass")
PRO_SEITE, SEITEN = 4, 4
# Mittelpunkte der Stempelfelder auf einer Sichtvermerkseite (mm, Seite 125 × 88)
FELDER = [(34, 34), (92, 32), (35, 66), (93, 64)]


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def _zoll():
    return next(b for b in amt.BEHOERDEN if b["schl"] == "zoll")


def darf_stempeln(k):
    return bool(k) and k["mitglied"] and (bereiche._alle(k) or bereiche.darf(k, _zoll()))


def darf_loeschen(k, s):
    if bereiche._alle(k) or bereiche.leitung(k, _zoll()):
        return True
    return s["beamter_id"] == k["id"] and s["zeit"] > time.time() - 86400


def stempel_nr(konto_id):
    """Feste dreistellige Stempelnummer je Beamter (wie die Nummer eines Dienststempels)."""
    return int(hashlib.sha1(str(konto_id).encode()).hexdigest(), 16) % 900 + 100


def stempel_fuer(con, pass_id):
    return con.execute("SELECT * FROM zv_stempel WHERE pass_id=? ORDER BY id", (pass_id,)).fetchall()


def _kurz(text, n):
    text = (text or "").upper()
    return text if len(text) <= n else text[:n - 1].rstrip() + "."


def stempel_svg(s, maske_url, breite_mm=46):
    """Ein Stempel als SVG (Tinte in der Farbe der Art, Struktur per Filter)."""
    titel, _, farbe = ARTEN.get(s["art"], ARTEN["einreise"])
    i = s["id"]
    if s["art"] == "visum":
        zeile2 = f'BIS {s["gueltig_bis"]}'
        zeile3 = _kurz(f'{s["zweck"]} · {s["ort"]}', 32)
    else:
        zeile2 = s["datum"]
        zeile3 = _kurz(s["ort"], 30)
    hoehe = breite_mm * 250 / 380
    return (
        f'<svg class="zv-stempel" viewBox="0 0 380 250" style="width:{breite_mm}mm;height:{hoehe:.1f}mm;color:{farbe}" '
        f'xmlns="http://www.w3.org/2000/svg" aria-label="{esc(ARTEN.get(s["art"], ARTEN["einreise"])[1])} {esc(s["datum"])}">'
        f'<defs><filter id="zvt{i}" x="-4%" y="-4%" width="108%" height="108%">'
        f'<feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="{i % 97}" result="n"/>'
        f'<feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -2.2 2.0" result="a"/>'
        f'<feComposite in="SourceGraphic" in2="a" operator="in" result="s"/>'
        f'<feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="{(i * 7) % 89}" result="w"/>'
        f'<feDisplacementMap in="s" in2="w" scale="4" xChannelSelector="R" yChannelSelector="G"/></filter>'
        f'<mask id="zvm{i}" maskUnits="userSpaceOnUse" x="0" y="0" width="380" height="250" style="mask-type:alpha">'
        f'<image href="{maske_url}" x="22" y="64" width="106" height="124" preserveAspectRatio="xMidYMid meet"/></mask></defs>'
        f'<g filter="url(#zvt{i})" fill="currentColor" stroke="currentColor" font-family="SS3,\'Liberation Sans\',Arial,sans-serif">'
        f'<rect x="5" y="5" width="370" height="240" rx="16" fill="none" stroke-width="7"/>'
        f'<rect x="16" y="16" width="348" height="218" rx="9" fill="none" stroke-width="2"/>'
        f'<text x="190" y="45" text-anchor="middle" font-size="21" font-weight="700" letter-spacing="4" stroke="none">IMPERIUM GERMANICUM</text>'
        f'<line x1="16" y1="57" x2="364" y2="57" stroke-width="2"/>'
        f'<rect x="22" y="64" width="106" height="124" mask="url(#zvm{i})" stroke="none"/>'
        f'<text x="142" y="102" font-size="{34 if len(titel) < 9 else 28}" font-weight="800" letter-spacing="3" stroke="none">{esc(titel)}</text>'
        f'<text x="142" y="148" font-size="{38 if s["art"] != "visum" else 30}" font-weight="700" stroke="none">{esc(zeile2)}</text>'
        f'<text x="142" y="180" font-size="15.5" letter-spacing="1" stroke="none"'
        + (' textLength="214" lengthAdjust="spacingAndGlyphs"' if len(zeile3) > 19 else "") + f'>{esc(zeile3)}</text>'
        f'<line x1="16" y1="197" x2="364" y2="197" stroke-width="2"/>'
        f'<text x="190" y="225" text-anchor="middle" font-size="15" letter-spacing="2.4" stroke="none">'
        f'KAIS. ZOLLVERWALTUNG · STEMPEL {stempel_nr(s["beamter_id"])}</text></g></svg>')


def seiten_stempel(stempel, seite):
    """Stempel, die auf Sichtvermerkseite `seite` (1–4) gehören: die neuesten 16, ältester zuerst, je 4 pro Seite."""
    letzte = list(stempel)[-PRO_SEITE * SEITEN:]
    return [(i % PRO_SEITE, s) for i, s in enumerate(letzte) if i // PRO_SEITE + 1 == seite]


def stempel_auf_seite(stempel, seite, maske_url):
    """HTML der Stempel für eine Sichtvermerkseite (absolut positioniert, leicht versetzt und gedreht)."""
    out = []
    for feld, s in seiten_stempel(stempel, seite):
        cx, cy = FELDER[feld]
        dx, dy, rot = (s["id"] * 37) % 9 - 4, (s["id"] * 53) % 7 - 3, (s["id"] * 29) % 19 - 9
        out.append(f'<div style="position:absolute;left:{cx - 23 + dx}mm;top:{cy - 15 + dy}mm;transform:rotate({rot}deg);'
                   f'opacity:.9;mix-blend-mode:multiply;z-index:3">{stempel_svg(s, maske_url)}</div>')
    return "".join(out)


# ---------------------------------------------------------------- Prüfseite: Sichtvermerke + Formular

CSS = """<style>
.zv-raster{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:18px;margin:10px 0 6px}
.zv-karte{border:1px solid var(--linie);border-radius:12px;padding:14px;background:#fbf8fb}
.zv-karte .zv-bild{display:flex;justify-content:center;padding:4px 0 8px}
.zv-karte .zv-bild svg{width:100%!important;height:auto!important;max-width:240px;mix-blend-mode:multiply}
.zv-karte p{margin:2px 0;font-size:13px;color:var(--grau)}
.zv-karte form{margin-top:8px}
.zv-form{border:1px solid var(--linie);border-radius:12px;padding:16px 18px;margin:12px 0 8px;max-width:760px}
.zv-form .zeilen{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.zv-arten{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 12px}
.zv-arten label{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--linie);border-radius:999px;padding:6px 12px;cursor:pointer;font-weight:600}
.zv-arten input{accent-color:var(--ink)}
.zv-visum[hidden]{display:none}
</style>"""


def _heute():
    return date.today().strftime("%d.%m.%Y")


def _orte(con, k):
    import landespolizei
    namen = [s["name"] for s in landespolizei.staaten(con)]
    frueher = [r[0] for r in con.execute("SELECT ort FROM zv_stempel GROUP BY ort ORDER BY MAX(id) DESC LIMIT 30")]
    letzter = con.execute("SELECT ort FROM zv_stempel WHERE beamter_id=? ORDER BY id DESC LIMIT 1", (k["id"],)).fetchone()
    return list(dict.fromkeys(frueher + namen)), (letzter[0] if letzter else "")


def abschnitt(request, k, p, status):
    """Hook für personenseite: Sichtvermerke des gescannten Passes und (für Zoll) das Stempel-Formular."""
    if p is None or p["art"] not in HEFTE:
        return ""
    con = request.app["db"]
    st = stempel_fuer(con, p["id"])
    maske = f"{BASIS}pass-bild/stempel_adler.png"
    von = "?von=zoll" if request.query.get("von") == "zoll" else ""
    karten = []
    for s in reversed(st):
        loeschen = ""
        if darf_stempeln(k) and darf_loeschen(k, s):
            loeschen = (f'<form method="post" action="{PRUEF}{esc(p["nummer"])}/stempel/{s["id"]}/loeschen{von}">{amt.csrf_feld(request)}'
                        f'<button class="btn zweit gefahr" type="submit">{amt.ic("trash-2")}Stempel entfernen</button></form>')
        zusatz = f' · {esc(s["zweck"])} bis {esc(s["gueltig_bis"])}' if s["art"] == "visum" else ""
        karten.append(f'<div class="zv-karte"><div class="zv-bild">{stempel_svg(s, maske)}</div>'
                      f'<p><b>{esc(ARTEN[s["art"]][1])}</b> · {esc(s["datum"])} · {esc(s["ort"])}{zusatz}</p>'
                      f'<p>{esc(s["beamter_name"])} · Stempel {stempel_nr(s["beamter_id"])} · erfasst {amt._zeit(s["zeit"])}</p>'
                      + (f'<p>{esc(s["bemerkung"])}</p>' if s["bemerkung"] else "") + loeschen + "</div>")
    teile = [CSS, f'<h2>Sichtvermerke ({len(st)})</h2>']
    if darf_stempeln(k):
        if status != "gueltig":
            teile.append('<div class="warnung">Dieser Pass ist nicht gültig. Es dürfen keine Sichtvermerke gestempelt werden.</div>')
        else:
            orte, letzter = _orte(con, k)
            arten = "".join(f'<label><input type="radio" name="art" value="{a}"{" checked" if a == "einreise" else ""}> '
                            f'<span style="color:{f}">●</span> {esc(n)}</label>' for a, (_, n, f) in ARTEN.items())
            teile.append(
                f'<form class="zv-form" method="post" action="{PRUEF}{esc(p["nummer"])}/stempel{von}">{amt.csrf_feld(request)}'
                f'<b>Stempel setzen</b><div class="zv-arten">{arten}</div><div class="zeilen">'
                f'<div><label for="zv-ort">Grenzübergangsstelle</label><input type="text" id="zv-ort" name="ort" list="zv-orte" required maxlength="60" '
                f'value="{esc(letzter)}" style="width:100%"><datalist id="zv-orte">{"".join(f"<option value={chr(34)}{esc(o)}{chr(34)}>" for o in orte)}</datalist></div>'
                f'<div><label for="zv-datum">Datum (IC)</label><input type="text" id="zv-datum" name="datum" required pattern="\\d{{2}}\\.\\d{{2}}\\.\\d{{4}}" '
                f'value="{_heute()}" placeholder="TT.MM.JJJJ" style="width:100%"></div>'
                f'<div class="zv-visum" hidden><label for="zv-bis">Visum gültig bis</label><input type="text" id="zv-bis" name="gueltig_bis" '
                f'pattern="\\d{{2}}\\.\\d{{2}}\\.\\d{{4}}" placeholder="TT.MM.JJJJ" style="width:100%"></div>'
                f'<div class="zv-visum" hidden><label for="zv-zweck">Zweck</label><select id="zv-zweck" name="zweck" style="width:100%">'
                + "".join(f"<option>{esc(z)}</option>" for z in ZWECKE) + '</select></div>'
                f'<div style="grid-column:1/-1"><label for="zv-bem">Bemerkung (intern, optional)</label><input type="text" id="zv-bem" name="bemerkung" maxlength="200" style="width:100%"></div>'
                f'</div><div class="aktionen"><button class="btn" type="submit">{amt.ic("stamp")}Stempeln</button></div></form>'
                '<script>(function(){var f=document.querySelector(".zv-form");if(!f)return;function w(){var v=f.querySelector("input[name=art]:checked").value==="visum";'
                'f.querySelectorAll(".zv-visum").forEach(function(d){d.hidden=!v});f.querySelector("#zv-bis").required=v}'
                'f.addEventListener("change",w);w()})();</script>')
    teile.append(f'<div class="zv-raster">{"".join(karten)}</div>' if karten else '<p class="leer">Noch keine Sichtvermerke in diesem Pass.</p>')
    return "".join(teile)


# ---------------------------------------------------------------- Aktionen

def _zurueck(nr, von, text, fehler=False):
    q = ("?von=zoll&" if von == "zoll" else "?") + "m=" + quote(text) + ("&f=1" if fehler else "")
    raise web.HTTPSeeOther(f"{PRUEF}{nr}/{q}")


def _datum_ok(text):
    try:
        datetime.strptime(text, "%d.%m.%Y")
        return True
    except ValueError:
        return False


async def _post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    if not darf_stempeln(k):
        raise web.HTTPForbidden(text="Stempeln darf nur die Zollverwaltung.")
    nr = "".join(c for c in request.match_info["nr"].upper() if c.isalnum())[:12]
    p = request.app["db"].execute("SELECT * FROM pw_paesse WHERE nummer=?", (nr,)).fetchone()
    if not p:
        raise web.HTTPNotFound(text="Pass nicht gefunden.")
    return k, form, nr, p, request.query.get("von", "")


async def stempeln(request):
    k, form, nr, p, von = await _post(request)
    con = request.app["db"]
    if p["art"] not in HEFTE:
        _zurueck(nr, von, "In einen Personalausweis kann nicht gestempelt werden.", True)
    if meldewesen.pass_status(p)[0] != "gueltig":
        _zurueck(nr, von, "Der Pass ist nicht gültig – kein Stempel gesetzt.", True)
    art = str(form.get("art", ""))
    ort = " ".join(str(form.get("ort", "")).split())[:60]
    datum = str(form.get("datum", "")).strip()
    bis = str(form.get("gueltig_bis", "")).strip() if art == "visum" else ""
    zweck = str(form.get("zweck", "")) if art == "visum" else ""
    bem = " ".join(str(form.get("bemerkung", "")).split())[:200]
    if art not in ARTEN or not ort or not _datum_ok(datum):
        _zurueck(nr, von, "Bitte Art, Grenzübergangsstelle und ein Datum (TT.MM.JJJJ) angeben.", True)
    if art == "visum" and (not _datum_ok(bis) or zweck not in ZWECKE):
        _zurueck(nr, von, "Für ein Visum bitte Gültigkeit (TT.MM.JJJJ) und Zweck angeben.", True)
    con.execute("INSERT INTO zv_stempel (pass_id, art, ort, datum, gueltig_bis, zweck, bemerkung, beamter_id, beamter_name, zeit) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", (p["id"], art, ort, datum, bis, zweck, bem, k["id"], k["name"], int(time.time())))
    text = f"{ARTEN[art][1]} am {datum} · {ort}" + (f" · {zweck}, gültig bis {bis}" if art == "visum" else "")
    meldewesen._eintrag(con, p["id"], "Sichtvermerk", text, k)
    con.commit()
    _zurueck(nr, von, f"Stempel gesetzt: {text}.")


async def loeschen(request):
    k, form, nr, p, von = await _post(request)
    con = request.app["db"]
    sid = request.match_info["sid"]
    s = con.execute("SELECT * FROM zv_stempel WHERE id=? AND pass_id=?", (sid, p["id"])).fetchone() if sid.isdigit() else None
    if not s:
        raise web.HTTPNotFound(text="Stempel nicht gefunden.")
    if not darf_loeschen(k, s):
        _zurueck(nr, von, "Eigene Stempel können nur binnen 24 Stunden entfernt werden, sonst nur durch die Leitung.", True)
    con.execute("DELETE FROM zv_stempel WHERE id=?", (s["id"],))
    meldewesen._eintrag(con, p["id"], "Sichtvermerk entfernt",
                        f'{ARTEN[s["art"]][1]} vom {s["datum"]} · {s["ort"]} (gestempelt von {s["beamter_name"]})', k)
    con.commit()
    _zurueck(nr, von, "Stempel entfernt.")


# ---------------------------------------------------------------- Tab Zoll: Grenzkontrolle

async def zoll_zusatz(request, k):
    import personenseite
    con = request.app["db"]
    rows = con.execute("SELECT s.*, p.nummer, p.inhaber FROM zv_stempel s JOIN pw_paesse p ON p.id=s.pass_id "
                       "ORDER BY s.id DESC LIMIT 15").fetchall()
    zeilen = [(amt._zeit(r["zeit"]), f'<a class="mw-nr" href="{PRUEF}{esc(r["nummer"])}/?von=zoll">{esc(r["nummer"])}</a>', esc(r["inhaber"]),
               f'<span style="color:{ARTEN[r["art"]][2]};font-weight:600">{esc(ARTEN[r["art"]][1])}</span>', esc(r["datum"]), esc(r["ort"]),
               esc(r["beamter_name"])) for r in rows]
    return (meldewesen.CSS + '<h2>Grenzkontrolle</h2>'
            '<p class="az">Pass scannen oder Passnummer eingeben: Gültigkeit prüfen und Sichtvermerke (Einreise, Ausreise, Durchreise, Visum) stempeln.</p>'
            + personenseite.scanner(request, k, von="zoll")
            + f'<form class="zeile" method="get" action="{ZOLL}grenze"><div><label for="zv-nr">Passnummer</label>'
            '<input type="search" id="zv-nr" name="nr" maxlength="12" autocomplete="off" autocapitalize="characters" class="mw-nr" required></div>'
            f'<button class="btn" type="submit">{amt.ic("search")}Pass aufrufen</button></form>'
            '<h3>Zuletzt gestempelt</h3>'
            + amt.tabelle(["Zeit", "Pass", "Inhaber", "Vermerk", "Datum (IC)", "Grenzübergang", "Beamter"], zeilen, "Noch keine Stempel gesetzt."))


async def grenze(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    nr = "".join(c for c in request.query.get("nr", "").upper() if c.isalnum())[:12]
    if not nr:
        raise web.HTTPFound(ZOLL)
    raise web.HTTPFound(f"{PRUEF}{nr}/?von=zoll")


def registrieren(app):
    import personenseite
    einrichten(app["db"])
    amt.ICONS.setdefault("stamp", '<path d="M5 22h14"/><path d="M19.27 13.73A2.5 2.5 0 0 0 17.5 13h-11A2.5 2.5 0 0 0 4 15.5V17a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1.5c0-.66-.26-1.3-.73-1.77Z"/>'
                                  '<path d="M14 13V8.5C14 7 15 7 15 5a3 3 0 0 0-3-3c-1.69 0-3 1-3 3s1 2 1 3.5V13"/>')
    bereiche.ZUSATZ["zoll"] = zoll_zusatz
    personenseite.PASS_ABSCHNITT.append(abschnitt)
    app.router.add_get(ZOLL + "grenze", grenze)
    app.router.add_post(PRUEF + "{nr}/stempel", stempeln)
    app.router.add_post(PRUEF + "{nr}/stempel/{sid}/loeschen", loeschen)
