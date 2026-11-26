"""Anmeldung über Discord (OAuth2).

    GET  /anmelden/?weiter=/pfad/   → Weiterleitung zu Discord (bzw. Statusseite, wenn schon angemeldet)
    GET  /anmelden/rueckruf         → Rückkehr von Discord, legt Konto und Sitzung an
    POST /abmelden/                 → Sitzung beenden (Formular mit csrf)
    GET  /anmelden/status           → JSON für Seiten-Skripte: angemeldet, Konto, csrf

Andere Module holen das Konto mit `konto(request)` bzw. verlangen es mit `@angemeldet(...)`.
"""
import functools
import html
import logging
import secrets
import time

from aiohttp import web

import config
import db
import discord_api
from seiten import hinweis

log = logging.getLogger("anmeldung")
routes = web.RouteTableDef()


def _weiter(ziel):
    """Nur Pfade dieser Website als Ziel zulassen (keine offenen Weiterleitungen)."""
    if not ziel or not ziel.startswith("/") or ziel.startswith("//") or "\\" in ziel:
        return "/"
    return ziel


def _cookie(resp, name, wert, max_age):
    resp.set_cookie(name, wert, max_age=max_age, path="/", secure=True, httponly=True, samesite="Lax")


async def konto(request):
    """Konto der aktuellen Sitzung (Rollen höchstens alle paar Minuten neu von Discord) oder None."""
    if "konto" in request:
        return request["konto"]
    con = request.app["db"]
    k, csrf = db.sitzung_laden(con, request.cookies.get(config.SITZUNG_COOKIE))
    if k and time.time() - k["aktualisiert"] > config.ROLLEN_AKTUALISIEREN_MIN * 60:
        try:
            neu = await request.app["discord"].konto_neu(k["id"])
            db.konto_speichern(con, neu)
            k.update(neu)
        except discord_api.DiscordFehler as e:
            log.warning("Rollenabgleich für %s fehlgeschlagen: %s", k["id"], e)
    request["konto"], request["csrf"] = k, csrf
    return k


def angemeldet(pruefung=lambda k: k["mitglied"], verweigert="Dafür fehlen dir die nötigen Rollen auf unserem Discord-Server."):
    """Dekorator: ohne Anmeldung → /anmelden/, ohne Berechtigung → Hinweisseite (403)."""
    def deko(handler):
        @functools.wraps(handler)
        async def inner(request):
            k = await konto(request)
            if not k:
                raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
            if not pruefung(k):
                return web.Response(status=403, content_type="text/html",
                                    text=hinweis("Kein Zugang", html.escape(verweigert), [("Zur Hauptseite", "/", True)]))
            return await handler(request)
        return inner
    return deko


@routes.get("/anmelden/")
async def anmelden(request):
    ziel = _weiter(request.query.get("weiter"))
    k = await konto(request)
    if k:
        return web.Response(content_type="text/html", text=_status_seite(k, request["csrf"], ziel))
    state = secrets.token_urlsafe(24)
    resp = web.HTTPFound(discord_api.autorisieren_url(state))
    _cookie(resp, config.STATE_COOKIE, f"{state}|{ziel}", config.STATE_MINUTEN * 60)
    raise resp


@routes.get("/anmelden/rueckruf")
async def rueckruf(request):
    gespeichert = request.cookies.get(config.STATE_COOKIE, "")
    state, _, ziel = gespeichert.partition("|")
    nochmal = [("Erneut anmelden", "/anmelden/?weiter=" + _weiter(ziel), True), ("Zur Hauptseite", "/", False)]

    if request.query.get("error"):   # z. B. „Abbrechen“ bei Discord
        resp = web.Response(content_type="text/html", text=hinweis(
            "Anmeldung abgebrochen", "Die Anmeldung über Discord wurde nicht abgeschlossen.", nochmal))
        resp.del_cookie(config.STATE_COOKIE, path="/")
        return resp
    if not state or not secrets.compare_digest(state, request.query.get("state", "")) or not request.query.get("code"):
        return web.Response(status=400, content_type="text/html", text=hinweis(
            "Anmeldung abgelaufen", "Der Anmeldevorgang ist abgelaufen oder ungültig. Bitte versuche es noch einmal.", nochmal))

    dc = request.app["discord"]
    try:
        k = await dc.konto(await dc.nutzer_aus_code(request.query["code"]))
    except discord_api.DiscordFehler as e:
        log.warning("Anmeldung fehlgeschlagen: %s", e)
        return web.Response(status=502, content_type="text/html", text=hinweis(
            "Anmeldung fehlgeschlagen", "Discord hat die Anmeldung nicht bestätigt. Bitte versuche es gleich noch einmal.", nochmal))

    con = request.app["db"]
    db.konto_speichern(con, k)
    db.anmeldung_vermerken(con, k["id"])
    log.info("Anmeldung: %s (%s), Mitglied=%s, Admin=%s", k["name"], k["id"], k["mitglied"], k["admin"])

    if not k["mitglied"]:
        resp = web.Response(status=403, content_type="text/html", text=hinweis(
            "Kein Mitglied des Servers",
            f"Hallo {html.escape(k['name'])}, du bist nicht Mitglied unseres Discord-Servers. "
            "Die Anmeldung steht nur Mitgliedern offen.",
            [("Zum Discord-Server", "https://discord.gg/cbD4E7yXJp", True), ("Zur Hauptseite", "/", False)]))
    else:
        resp = web.HTTPFound(_weiter(ziel))
        _cookie(resp, config.SITZUNG_COOKIE, db.sitzung_anlegen(con, k["id"]), config.SITZUNG_TAGE * 86400)
    resp.del_cookie(config.STATE_COOKIE, path="/")
    if isinstance(resp, web.HTTPException):
        raise resp
    return resp


@routes.post("/abmelden/")
async def abmelden(request):
    form = await request.post()
    k = await konto(request)
    if k and not secrets.compare_digest(request["csrf"], form.get("csrf", "")):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    db.sitzung_beenden(request.app["db"], request.cookies.get(config.SITZUNG_COOKIE))
    resp = web.HTTPSeeOther(_weiter(form.get("weiter")))
    resp.del_cookie(config.SITZUNG_COOKIE, path="/")
    raise resp


def _amt_zugang(k):
    """Hat das Konto auf der Amtsseite mehr als nur das Persönliche (Akten, Behörden, Dienste)? Für das Profilmenü der Website."""
    try:
        import amt
        return k["mitglied"] and any(t != "Persönlich" and es for t, es in amt.nav_gruppen(k))
    except Exception:
        return False


@routes.get("/anmelden/status")
async def status(request):
    k = await konto(request)
    daten = {"angemeldet": bool(k), "anmelden": "/anmelden/"}
    if k:
        daten.update({"id": k["id"], "name": k["name"], "avatar": k["avatar"], "rollen": k["rollen"],
                      "admin": k["admin"], "csrf": request["csrf"], "amt": _amt_zugang(k)})
    return web.json_response(daten, headers={"Cache-Control": "no-store"})


def _status_seite(k, csrf, ziel):
    rolle = "Administrator" if k["admin"] else "Mitglied"
    return hinweis(
        "Angemeldet", f'Du bist als <strong>{html.escape(k["name"])}</strong> ({rolle}) über Discord angemeldet.',
        [("Weiter", ziel, True)],
        unten=f"""<form method="post" action="/abmelden/" style="margin-top:1rem">
    <input type="hidden" name="csrf" value="{html.escape(csrf)}">
    <input type="hidden" name="weiter" value="/">
    <button class="btn btn-line" type="submit">Abmelden</button>
  </form>""")
