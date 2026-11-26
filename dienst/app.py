"""Imperium-Dienst: dynamischer Teil von imperiumgermanicum.de hinter nginx (127.0.0.1:8090).

Module: anmeldung (Discord-OAuth), organigramme (Staatsaufbau, Reichsverwaltung), karte (Reichskarte). Weitere Module
(Vorschläge, interne Bereiche) registrieren ihre Routen hier und nutzen anmeldung.konto / anmeldung.angemeldet.
"""
import logging

from aiohttp import web

import anmeldung
import config
import db
import amt
import amtshilfe
import bereiche
import discord_api
import karte
import landespolizei
import lichtbild
import kartei
import meldewesen
import passdruck
import passdigital
import personenseite
import webseite
import zollwesen
import schatzamt
import steuern
import besoldung
import aufkommen
import gold
import etat
import verteidigung
import notlage
import etatplan
import teilstaat
import entwicklung
import energie
import handel
import krisen
import bankkarte
import rpleitung
import organigramme
import post
import strafsachen
import reichstag
import privatbesitz
import suche
import rpstell
import rpteilstaaten
import geld_api


@web.middleware
async def frisch(request, handler):
    """Alle sehen sofort den aktuellen Stand: Antworten ohne eigene Cache-Regel werden nicht zwischengespeichert
    (Seiten und Daten: no-store; Dateien: no-cache, d. h. kurz beim Server nachfragen, 304 wenn unverändert)."""
    resp = await handler(request)
    if isinstance(resp, web.StreamResponse) and not resp.prepared and "Cache-Control" not in resp.headers:
        art = resp.content_type or ""
        resp.headers["Cache-Control"] = "no-store" if art.startswith(("text/", "application/json")) else "no-cache"
    return resp


def erstellen():
    app = web.Application(client_max_size=2 * 1024 * 1024, middlewares=[frisch, bankkarte.pin_sperre])
    app["db"] = db.verbinden()
    app["discord"] = dc = discord_api.Discord()
    app.on_startup.append(dc.start)
    app.on_cleanup.append(dc.stop)
    app.add_routes(anmeldung.routes)
    organigramme.registrieren(app)
    karte.registrieren(app)
    reichstag.registrieren(app)
    amt.registrieren(app)
    post.registrieren(app)
    bereiche.registrieren(app)
    strafsachen.registrieren(app)
    landespolizei.registrieren(app)
    amtshilfe.registrieren(app)
    meldewesen.registrieren(app)
    kartei.registrieren(app)
    lichtbild.registrieren(app)
    passdruck.registrieren(app)
    passdigital.registrieren(app)
    personenseite.registrieren(app)
    webseite.registrieren(app)
    zollwesen.registrieren(app)
    schatzamt.registrieren(app)
    steuern.registrieren(app)
    besoldung.registrieren(app)
    aufkommen.registrieren(app)
    gold.registrieren(app)
    etat.registrieren(app)
    verteidigung.registrieren(app)
    notlage.registrieren(app)
    etatplan.registrieren(app)
    import befugnisse
    befugnisse.einrichten(app["db"])
    teilstaat.registrieren(app)
    import teilstaaten_info
    teilstaaten_info.registrieren(app)
    entwicklung.registrieren(app)
    energie.registrieren(app)
    handel.registrieren(app)
    krisen.registrieren(app)
    bankkarte.registrieren(app)
    privatbesitz.registrieren(app)
    suche.registrieren(app)
    rpstell.registrieren(app)
    rpteilstaaten.registrieren(app)
    geld_api.registrieren(app)
    rpleitung.registrieren(app)
    import benachrichtigung
    import profil_sa
    benachrichtigung.registrieren(app)
    profil_sa.registrieren(app)
    import einfuehrung
    einfuehrung.registrieren(app)   # „Lass uns dein Erlebnis anpassen“ nach dem ersten Anmelden
    import regierung
    import generalkonsulat
    regierung.registrieren(app)
    generalkonsulat.registrieren(app)
    regierung.registrieren_ministerien(app)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    web.run_app(erstellen(), host=config.HOST, port=config.PORT, access_log=None)
