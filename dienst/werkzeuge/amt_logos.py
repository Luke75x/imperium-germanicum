"""Behördenlogos der Reichsbehörden (Amtsseite) erzeugen: amt_logos/<schlüssel>.png (Langform) und <schlüssel>-kurz.png.

Aufbau wie das Logo des Kronkanzlers (werkzeuge/logo_grundlage/): Reichsadler links, senkrechter Balken (oben schwarz, unten
Gold) und rechts der Behördenname in Source Sans 3. Formen: lang, -kopf (Kopfleiste), -kurz (Adler + Balken). Maße aus dem Kronkanzler-Logo (1280×800): Adler 193×174 px, Balken 28×470 px,
Schrift 94 px mit 100 px Zeilenabstand. Neue Behörde = Eintrag in amt.LOGOS (Schlüssel, Rolle, Zeilen) und Skript ausführen:
    .venv/bin/python werkzeuge/amt_logos.py
"""
import asyncio
import base64
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
sys.path.insert(0, WURZEL)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(WURZEL, ".browser"))
from playwright.async_api import async_playwright  # noqa: E402

import amt_logos_liste as liste  # noqa: E402

GRUND = os.path.join(HIER, "logo_grundlage")
AUS = os.path.join(WURZEL, "amt_logos")


def _b64(pfad):
    with open(pfad, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def html(zeilen, form):
    """form: 'lang' (wie das Kronkanzler-Logo, hoher Balken), 'kopf' (Balken so hoch wie der Text, für die Kopfleiste), 'kurz' (Adler + Balken)."""
    kurz = form == "kurz"
    hoehe = {"lang": 470, "kopf": max(186, len(zeilen) * 100 + 26), "kurz": 186}[form]
    adler, schrift = _b64(os.path.join(GRUND, "adler.png")), _b64(os.path.join(GRUND, "source-sans-3.woff2"))
    text = "" if kurz else '<div class="t">' + "<br>".join(zeilen) + "</div>"
    return f"""<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:SS;src:url(data:font/woff2;base64,{schrift});font-weight:200 900}}
body{{margin:0;background:#fff}}
#l{{display:inline-flex;align-items:flex-start;padding:0 {0 if kurz else 60}px 0 0;background:#fff}}
img{{width:206px;height:186px;display:block;margin-top:6px}}
.b{{width:28px;height:{hoehe}px;margin:{7 if form == 'lang' else 6}px 0 0 44px;background:linear-gradient(#000 0 58%,#fc0 58% 100%);flex:none}}
.t{{font:400 94px/100px SS;color:#000;margin:13px 0 0 57px;white-space:nowrap;letter-spacing:-.5px}}
</style><div id="l"><img src="data:image/png;base64,{adler}"><div class="b"></div>{text}</div>"""


async def main():
    os.makedirs(AUS, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 2400, "height": 900})
        for schl, zeilen in liste.ZEILEN.items():
            for form in ("lang", "kopf", "kurz"):
                await pg.set_content(html(zeilen, form))
                await pg.evaluate("document.fonts.ready")
                ziel = os.path.join(AUS, schl + ("" if form == "lang" else "-" + form) + ".png")
                await (await pg.query_selector("#l")).screenshot(path=ziel)
                print("geschrieben", ziel)
        await b.close()


asyncio.run(main())
