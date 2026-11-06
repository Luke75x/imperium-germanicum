"""Untertabs der Reichsbehörden (amt.BEHOERDEN): je Behörde ein Bereich mit Pinnwand (Mitteilungen) und Mitarbeiterliste.

Wer den Untertab sieht, bestimmen die Discord-Rollen der Behörde (amt.BEHOERDEN[..]["rollen"]); Kanzler und Kaiser
sehen alle. Löschen fremder Mitteilungen: Leitung (Rollen in "leitung"), Kanzler, Kaiser. Tabelle bereich_mitteilungen.
Neue Behörde: Eintrag in amt.BEHOERDEN, Logo-Text in amt_logos_liste.py, Logos mit werkzeuge/amt_logos.py erzeugen.
"""
import secrets
import time

from aiohttp import web

import amt
import anmeldung
import post

esc = amt.esc
BASIS = amt.BASIS
MAX_PRO_STUNDE = 20
ZUSATZ = {}   # schl -> async fn(request, konto) -> HTML, wird unter der Überschrift der Behörde eingefügt (z. B. Landespolizeien)

SCHEMA = """
CREATE TABLE IF NOT EXISTS bereich_mitteilungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bereich TEXT NOT NULL, autor_id TEXT NOT NULL, autor_name TEXT NOT NULL,
    titel TEXT NOT NULL, text TEXT NOT NULL, zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS bereich_mitteilungen_b ON bereich_mitteilungen (bereich, zeit);
"""

amt.ICONS.update({
    "siren": '<path d="M7 18v-6a5 5 0 1 1 10 0v6"/><path d="M5 21a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-1a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2z"/>'
             '<path d="M21 12h1"/><path d="M18.5 4.5 18 5"/><path d="M2 12h1"/><path d="M12 2v1"/><path d="m4.929 4.929.707.707"/><path d="M12 12v6"/>',
    "life-buoy": '<circle cx="12" cy="12" r="10"/><path d="m4.93 4.93 4.24 4.24"/><path d="m14.83 9.17 4.24-4.24"/>'
                 '<path d="m14.83 14.83 4.24 4.24"/><path d="m9.17 14.83-4.24 4.24"/><circle cx="12" cy="12" r="4"/>',
    "scale": '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
             '<path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
})


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def _alle(k):
    """Sieht alles: Kaiser und Kanzler, dazu die Serveradministratoren – diese nur OOC (Hinweis auf jeder Seite, amt.ist_ooc_admin)."""
    return bool(k) and (k["id"] == amt.config.KAISER_ID or amt.ROLLE_KANZLER in k["rollen"] or amt.ist_ooc_admin(k))


def darf(k, b):
    return _alle(k) or bool(set(b["rollen"]) & set(k["rollen"]))


def leitung(k, b):
    return _alle(k) or bool(set(b["leitung"]) & set(k["rollen"]))


def sichtbar(k):
    """Behörden, deren Untertab das Konto sieht."""
    return [b for b in amt.BEHOERDEN if darf(k, b)] if k else []


def _behoerde(request):
    for b in amt.BEHOERDEN:
        if b["schl"] == request.match_info["schl"]:
            return b
    raise web.HTTPNotFound(text="Behörde nicht gefunden.")


def _pruefen(handler):
    """Anmeldung und Rolle der Behörde nötig."""
    async def inner(request):
        k = await anmeldung.konto(request)
        if not k:
            raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
        b = _behoerde(request)
        if not k["mitglied"] or not darf(k, b):
            return web.Response(status=403, content_type="text/html", text=amt.rahmen(
                "Kein Zugang", "b-" + b["schl"], '<div class="warnung">Dieser Bereich ist den Mitarbeitern der Behörde vorbehalten.</div>', k, request["csrf"]))
        return await handler(request, k, b)
    return inner


@_pruefen
async def bereich(request, k, b):
    con = request.app["db"]
    pfad = f'{BASIS}bereich/{b["schl"]}/'
    mit = [m for m in await request.app["discord"].mitglieder() if set(m["rollen"]) & set(b["rollen"])]
    mit.sort(key=lambda m: (not (set(m["rollen"]) & set(b["leitung"])), m["name"].lower()))
    zeilen = []
    for m in mit:
        z = con.execute("SELECT ic_name FROM amt_akten WHERE konto_id=?", (m["id"],)).fetchone()
        adr = con.execute("SELECT adresse FROM post_adressen WHERE konto_id=? AND aktuell=1", (m["id"],)).fetchone()
        mail = f'<a href="{BASIS}postfach/neu/?an={esc(adr["adresse"])}">{esc(adr["adresse"])}</a>' if adr else "–"
        zeilen.append((esc(m["name"]) + (" " + amt.status_marke("neutral", "Leitung") if set(m["rollen"]) & set(b["leitung"]) else ""),
                       esc((z["ic_name"] if z else "") or "–"), mail))
    msgs = con.execute("SELECT * FROM bereich_mitteilungen WHERE bereich=? ORDER BY zeit DESC LIMIT 50", (b["schl"],)).fetchall()
    kopf = "".join(
        f'<div class="mitteilung"><h3>{esc(m["titel"])}</h3><p class="az">{esc(m["autor_name"])} · {amt._zeit(m["zeit"])}</p>'
        f'<div style="white-space:pre-wrap;word-break:break-word">{esc(m["text"])}</div>'
        + (f'<form method="post" action="{pfad}mitteilung/{m["id"]}/loeschen">{amt.csrf_feld(request)}'
           f'<button class="btn zweit gefahr" type="submit">{amt.ic("trash-2")}Löschen</button></form>'
           if m["autor_id"] == k["id"] or leitung(k, b) else "") + "</div>" for m in msgs) or '<p class="leer">Keine Mitteilungen.</p>'
    import strafsachen
    inhalt = (strafsachen.untertabs(k, b["schl"], "b-" + b["schl"]) + f'<h1>{amt.ic(b["icon"])} {esc(b["name"])}</h1>{amt.meldung(request)}'
              + (await ZUSATZ[b["schl"]](request, k) if b["schl"] in ZUSATZ else "")
              + f'<h2>Pinnwand</h2>'
              f'<form method="post" action="{pfad}mitteilung">{amt.csrf_feld(request)}'
              f'<div><label for="t">Titel</label><input type="text" id="t" name="titel" maxlength="120" style="width:100%" required></div>'
              f'<div style="margin-top:8px"><label for="x">Mitteilung an die Behörde</label><textarea id="x" name="text" maxlength="4000" required></textarea></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("pencil")}Veröffentlichen</button></div></form>'
              f'<style>.mitteilung{{border-bottom:1px solid #ddd;padding:12px 0}}.mitteilung h3{{margin:0;font-size:16px}}.mitteilung form{{margin-top:8px}}</style>'
              f'{kopf}<h2>Mitarbeiter ({len(mit)})</h2>'
              + amt.tabelle(["Discord-Name", "Name (IC)", "E-Mail"], zeilen, "Keine Mitarbeiter gefunden."))
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(b["name"], "b-" + b["schl"], inhalt, k, request["csrf"]))


async def _form(request, handler_b):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + BASIS)
    b = _behoerde(request)
    if not k["mitglied"] or not darf(k, b):
        raise web.HTTPForbidden(text="Dafür fehlen dir die nötigen Rollen.")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    return k, b, form


async def mitteilung(request):
    k, b, form = await _form(request, None)
    con = request.app["db"]
    ziel = f'{BASIS}bereich/{b["schl"]}/'
    titel = " ".join(str(form.get("titel", "")).split())[:120]
    text = str(form.get("text", "")).replace("\r\n", "\n").strip()[:4000]
    if not titel or not text:
        amt._umleiten(ziel, "Titel und Mitteilung dürfen nicht leer sein.", True)
    if con.execute("SELECT COUNT(*) FROM bereich_mitteilungen WHERE autor_id=? AND zeit>?", (k["id"], time.time() - 3600)).fetchone()[0] >= MAX_PRO_STUNDE:
        amt._umleiten(ziel, "Zu viele Mitteilungen in der letzten Stunde.", True)
    con.execute("INSERT INTO bereich_mitteilungen (bereich, autor_id, autor_name, titel, text, zeit) VALUES (?,?,?,?,?,?)",
                (b["schl"], k["id"], k["name"], titel, text, int(time.time())))
    con.commit()
    amt._umleiten(ziel, "Mitteilung veröffentlicht.")


async def loeschen(request):
    k, b, _form_ = await _form(request, None)
    con = request.app["db"]
    mid = request.match_info["id"]
    z = con.execute("SELECT * FROM bereich_mitteilungen WHERE id=? AND bereich=?", (mid, b["schl"])).fetchone() if mid.isdigit() else None
    if not z:
        raise web.HTTPNotFound()
    if z["autor_id"] != k["id"] and not leitung(k, b):
        raise web.HTTPForbidden(text="Nur der Autor oder die Leitung kann die Mitteilung löschen.")
    con.execute("DELETE FROM bereich_mitteilungen WHERE id=?", (z["id"],))
    con.commit()
    amt._umleiten(f'{BASIS}bereich/{b["schl"]}/', "Mitteilung gelöscht.")


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get(BASIS + "bereich/{schl}/", bereich)
    app.router.add_post(BASIS + "bereich/{schl}/mitteilung", mitteilung)
    app.router.add_post(BASIS + "bereich/{schl}/mitteilung/{id}/loeschen", loeschen)
