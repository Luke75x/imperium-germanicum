"""Bild der Reichskarte (karte.png, u. a. auf der Startseite): Teilstaaten mit Mustern und Legende im Stil der alten Karte.

Zeichnet die SVG-Pfade aus geo.json mit Pillow (Ausschnitt 3000 × 2325 px wie die alte MapChart-Karte), Schriften der Website.
Läuft beim Start (falls das Bild fehlt) und nach jeder neuen Version im Hintergrund.
"""
import asyncio
import logging
import os
import re

from PIL import Image, ImageDraw, ImageFont

import config

log = logging.getLogger("karte_bild")
PFAD = os.path.join(config.HIER, "daten", "bilder", "karte.png")
SCHRIFTEN = os.path.join(config.WEBSITE_DIR, "assets", "fonts")
MEER, LAND, RAND = (209, 229, 240), (209, 219, 221), (255, 255, 255)
_lauf = None


def _hex(f):
    return tuple(int(f[i:i + 2], 16) for i in (1, 3, 5))


def _ringe(d):
    for teil in re.findall(r"M([^Z]+)Z", d):
        zahlen = [float(x) for x in re.split(r"[ L]+", teil.strip())]
        yield list(zip(zahlen[0::2], zahlen[1::2]))


def _muster(s, groesse=3000, hoehe=2325):
    """Füllbild für einen Teilstaat (einfarbig, Streifen 45°, Karo, Punkte)."""
    f1, f2 = _hex(s["farbe"]), _hex(s["farbe2"])
    if s["muster"] == "voll":
        return f1
    kachel = 16
    k = Image.new("RGB", (kachel, kachel), f1)
    d = ImageDraw.Draw(k)
    if s["muster"] == "streifen":
        for o in range(-kachel, kachel * 2, kachel // 2):
            d.line([(o, kachel), (o + kachel, 0)], fill=f2, width=3)
    elif s["muster"] == "karo":
        h = kachel // 2
        d.rectangle([0, 0, h - 1, h - 1], fill=f2); d.rectangle([h, h, kachel - 1, kachel - 1], fill=f2)
    else:
        d.ellipse([kachel / 2 - 3.5, kachel / 2 - 3.5, kachel / 2 + 3.5, kachel / 2 + 3.5], fill=f2)
    voll = Image.new("RGB", (groesse, hoehe))
    for x in range(0, groesse, kachel):
        for y in range(0, hoehe, kachel):
            voll.paste(k, (x, y))
    return voll


def _schrift(datei, groesse, gewicht):
    f = ImageFont.truetype(os.path.join(SCHRIFTEN, datei), groesse)
    try:
        f.set_variation_by_axes([gewicht])
    except OSError:
        pass
    return f


def zeichnen(geo, stand, ziel=PFAD):
    B, H = geo["breite"], geo["hoehe"]
    bild = Image.new("RGB", (B, H), MEER)
    d = ImageDraw.Draw(bild)
    for p in geo["hintergrund"]:
        for r in _ringe(p):
            if len(r) > 2:
                d.polygon(r, fill=LAND)
    staaten = {s["id"]: s for s in stand["staaten"]}
    je_staat = {}
    for gid, g in geo["gebiete"].items():
        sid = stand["gebiete"].get(gid)
        if sid in staaten:
            je_staat.setdefault(sid, []).append(g["d"])
        else:
            for r in _ringe(g["d"]):
                if len(r) > 2:
                    d.polygon(r, fill=LAND, outline=LAND)
    for sid, pfade in je_staat.items():
        maske = Image.new("L", (B, H), 0)
        md = ImageDraw.Draw(maske)
        for p in pfade:
            for r in _ringe(p):
                if len(r) > 2:
                    md.polygon(r, fill=255, outline=255)
        fuellung = _muster(staaten[sid], B, H)
        if isinstance(fuellung, tuple):
            bild.paste(fuellung, (0, 0, B, H), maske)
        else:
            bild.paste(fuellung, (0, 0), maske)

    # Legende oben links wie auf der alten Karte
    liste = sorted([s for s in stand["staaten"] if s["id"] in je_staat], key=lambda s: s["name"])
    titel, text = _schrift("source-sans-3.woff2", 44, 700), _schrift("source-sans-3.woff2", 40, 400)
    x0, y0, zeile = 200, 155, 66
    breite = max([d.textlength(s["name"], font=text) for s in liste] + [400]) + 200
    hoehe = 130 + zeile * len(liste)
    d.rounded_rectangle([x0, y0, x0 + breite, y0 + hoehe], radius=18, fill=(255, 255, 255), outline=(30, 30, 30), width=3)
    d.text((x0 + 60, y0 + 40), "Die Teilstaaten", font=titel, fill=(0, 0, 0))
    for i, s in enumerate(liste):
        y = y0 + 125 + i * zeile
        f = _muster(s, 46, 46)
        if isinstance(f, tuple):
            d.rectangle([x0 + 60, y, x0 + 105, y + 45], fill=f)
        else:
            bild.paste(f, (x0 + 60, y))
        d.rectangle([x0 + 60, y, x0 + 105, y + 45], outline=(120, 120, 120), width=1)
        d.text((x0 + 135, y + 22), s["name"], font=text, fill=(30, 30, 30), anchor="lm")
    d.text((B - 40, H - 30), "imperiumgermanicum.de", font=_schrift("source-sans-3.woff2", 30, 600), fill=(60, 60, 60), anchor="rs")
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    bild.save(ziel + ".neu.png", optimize=True)
    os.replace(ziel + ".neu.png", ziel)


def neu_erzeugen(geo, stand, verzoegerung=3):
    """Im Hintergrund neu zeichnen; mehrere Aufrufe kurz hintereinander ergeben nur einen Durchlauf."""
    global _lauf
    if _lauf and not _lauf.done():
        _lauf.cancel()

    async def lauf():
        await asyncio.sleep(verzoegerung)
        try:
            await asyncio.get_running_loop().run_in_executor(None, zeichnen, geo, stand)
            log.info("Kartenbild erzeugt")
        except Exception as e:   # Bild ist Beiwerk: Fehler nur protokollieren
            log.warning("Kartenbild fehlgeschlagen: %s", e)
    _lauf = asyncio.get_running_loop().create_task(lauf())
