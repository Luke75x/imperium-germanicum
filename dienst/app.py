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
import meldewesen
import passdruck
import passdigital
import personenseite
import webseite
import organigramme
import post
import strafsachen
import reichstag


def erstellen():
    app = web.Application(client_max_size=2 * 1024 * 1024)
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
    passdruck.registrieren(app)
    passdigital.registrieren(app)
    personenseite.registrieren(app)
    webseite.registrieren(app)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    web.run_app(erstellen(), host=config.HOST, port=config.PORT, access_log=None)
