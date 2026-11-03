"""Bild eines Organigramms (organigramm.png, u. a. auf der Startseite) mit einem Browser auf dem Server erzeugen.

Ruft die Anzeige-Seite auf und löst „Als Bild herunterladen“ aus, d. h. das Bild zeichnet dasselbe Skript wie im Browser
der Besucher. Läuft beim Start (falls das Bild fehlt) und nach jedem Speichern im Hintergrund.
Browser: Playwright-Chromium in .browser (PLAYWRIGHT_BROWSERS_PATH), Seite über nginx auf 127.0.0.1.
"""
import asyncio
import logging
import os

import config

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(config.HIER, ".browser"))
from playwright.async_api import async_playwright  # noqa: E402

log = logging.getLogger("bild")
ORDNER = os.path.join(config.HIER, "daten", "bilder")
_laeuft = {}


def pfad(name):
    return os.path.join(ORDNER, name + ".png")


async def erzeugen(name, seite):
    os.makedirs(ORDNER, exist_ok=True)
    host = config.SITE_URL.split("://", 1)[1]
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=[f"--host-resolver-rules=MAP {host} 127.0.0.1"])
        try:
            pg = await browser.new_page(viewport={"width": 1440, "height": 1000})
            await pg.goto(config.SITE_URL + seite, wait_until="networkidle", timeout=60000)
            await pg.wait_for_selector(".org-knoten", timeout=30000)
            async with pg.expect_download(timeout=60000) as dl:
                await pg.click("[data-bild]")
            tmp = pfad(name) + ".neu"
            await (await dl.value).save_as(tmp)
            os.replace(tmp, pfad(name))
            log.info("Bild %s erzeugt (%d kB)", name, os.path.getsize(pfad(name)) // 1024)
        finally:
            await browser.close()


def neu_erzeugen(name, seite, verzoegerung=5):
    """Im Hintergrund (neu) erzeugen; mehrere Aufrufe kurz hintereinander ergeben nur einen Durchlauf."""
    alt = _laeuft.get(name)
    if alt and not alt.done():
        alt.cancel()

    async def lauf():
        await asyncio.sleep(verzoegerung)
        try:
            await erzeugen(name, seite)
        except Exception as e:   # Bild ist Beiwerk: Fehler nur protokollieren
            log.warning("Bild %s fehlgeschlagen: %s", name, e)
    _laeuft[name] = asyncio.get_running_loop().create_task(lauf())
