"""Einheitliche Behördenlogos für alle Ministerien der Reichsregierung (Nutzervorgabe 25.11.2026: gleiche Schrift, gleiche Größe).

Erzeugt mit transparentem Hintergrund:
  amt_logos/<schl>-pool.png  – für die Logo-Übersicht auf /regierung/: alle Bilder gleich hoch (Platz für 3 Zeilen), Inhalt senkrecht
                               mittig. Bei gleicher Anzeigehöhe ist die Schrift überall gleich groß.
  amt_logos/<schl>-kopf.png / -kurz.png – nur für Ministerien in NEU_KOPF (bisher ohne Logo bzw. auf Wunsch neu im Einheitsstil).
Aufbau wie werkzeuge/amt_logos.py (Adler, Balken schwarz/gold, Source Sans 3). Die Reichsvertretung trägt statt des Adlers ihr Wappen.
    .venv/bin/python werkzeuge/pool_logos.py
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

GRUND = os.path.join(HIER, "logo_grundlage")
AUS = os.path.join(WURZEL, "amt_logos")
WAPPEN = {"kronstatthalterschaft": "/var/www/imperium/assets/img/original/i3c7a91e5d20b84f6.png"}

# Ministerium (Schlüssel aus reichsbehoerden.py) -> Zeilen im Logo
ZEILEN = {
    "kanzlei": ["Das", "Kronkanzleramt"],
    "crownestates": ["Crown", "Estates"],
    "kronstatthalterschaft": ["Reichsamt für die", "Kronstatthalterschaft"],
    "krs": ["Kaiserliches", "Reichssicherheitsamt"],
    "polizei": ["Kaiserliche", "Polizeibehörde"],
    "zoll": ["Kaiserliche", "Zollverwaltung"],
    "katastrophenschutz": ["Kaiserlicher", "Katastrophenschutz"],
    "inquisition": ["Kaiserliche", "Großinquisition"],
    "generalkonsulat": ["Kaiserliches", "Generalkonsulat"],
    "schatzamt": ["Kaiserliches Schatz-", "und Währungsamt"],
    "heroldsamt": ["Heroldsamt"],
    "inneres": ["Reichsbehörde für", "Innere", "Angelegenheiten"],
    "forschung": ["Reichsamt für", "Forschung"],
    "gesundheit": ["Reichsamt für das", "Gesundheitswesen"],
    "verkehr": ["Reichsamt für das", "Verkehrs- und", "Transportwesen"],
    "arbeit": ["Reichsamt für das", "Arbeits- und", "Sozialwesen"],
    "einwanderung": ["Reichsamt für", "Migration und", "Einwanderung"],
    "zentralbank": ["Zentralbank"],
    "reichskasse": ["Reichskasse"],
}
# Diese bekommen auch Kopf- und Kurzform im Einheitsstil (die übrigen behalten ihre bestehenden Logos)
NEU_KOPF = ["crownestates", "kronstatthalterschaft", "heroldsamt", "inneres", "forschung", "gesundheit", "verkehr", "arbeit",
            "einwanderung", "zentralbank", "reichskasse"]
POOL_HOEHE = 3 * 100 + 26   # Platz für drei Zeilen


def _b64(pfad):
    with open(pfad, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def html(schl, form):
    zeilen = ZEILEN[schl]
    kurz = form == "kurz"
    bild = WAPPEN.get(schl) or os.path.join(GRUND, "adler.png")
    balken = max(186, len(zeilen) * 100 + 26)
    text = "" if kurz else '<div class="t">' + "<br>".join(zeilen) + "</div>"
    hoehe = f"height:{POOL_HOEHE}px;" if form == "pool" else ""
    return f"""<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:SS;src:url(data:font/woff2;base64,{_b64(os.path.join(GRUND, "source-sans-3.woff2"))});font-weight:200 900}}
html,body{{margin:0;background:transparent}}
#l{{display:inline-flex;align-items:center;{hoehe}padding:0 {0 if kurz else 30}px 0 0}}
#i{{display:inline-flex;align-items:flex-start}}
img{{width:206px;height:186px;display:block;margin-top:6px;object-fit:contain}}
.b{{width:28px;height:{balken}px;margin:6px 0 0 44px;background:linear-gradient(#000 0 58%,#fc0 58% 100%);flex:none}}
.t{{font:400 94px/100px SS;color:#000;margin:13px 0 0 57px;white-space:nowrap;letter-spacing:-.5px}}
</style><div id="l"><div id="i"><img src="data:image/png;base64,{_b64(bild)}"><div class="b"></div>{text}</div></div>"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 2400, "height": 900})
        for schl in ZEILEN:
            for form in ["pool"] + (["kopf", "kurz"] if schl in NEU_KOPF else []):
                await pg.set_content(html(schl, form))
                await pg.evaluate("document.fonts.ready")
                ziel = os.path.join(AUS, f"{schl}-{form}.png")
                await (await pg.query_selector("#l")).screenshot(path=ziel, omit_background=True)
                print("geschrieben", ziel)
        await b.close()


asyncio.run(main())
