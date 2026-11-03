"""Bild der Reichskarte (karte.png, u. a. auf der Startseite): Teilstaaten mit Mustern und Legende im Stil der alten Karte.

Zeichnet die SVG-Pfade aus geo.json mit Pillow (Ausschnitt 3000 × 2325 px wie die alte MapChart-Karte), Schriften der Website.
Läuft beim Start (falls das Bild fehlt) und nach jeder neuen Version im Hintergrund.
"""
import asyncio
import logging
import math
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


def _linien(d):
    for teil in d.split("M")[1:]:
        z = [float(x) for x in re.split(r"[ L]+", teil.strip())]
        yield list(zip(z[0::2], z[1::2]))


def _komponenten(geo, stand):
    """Zusammenhängende Teile je Teilstaat (über gemeinsame Grenzen): Fläche und Schwerpunkt (Kartenkoordinaten)."""
    zu, nb = stand["gebiete"], {}
    for a, b, _d in geo.get("kanten", []):
        if zu.get(a) == zu.get(b):
            nb.setdefault(a, []).append(b)
            nb.setdefault(b, []).append(a)
    gesehen, out = set(), []
    for gid, sid in zu.items():
        if gid in gesehen or gid not in geo.get("mitte", {}):
            continue
        stapel, c = [gid], {"staat": sid, "a": 0, "x": 0, "y": 0, "ids": []}
        gesehen.add(gid)
        while stapel:
            k = stapel.pop()
            m = geo["mitte"][k]
            c["ids"].append(m)
            c["a"] += m[2]; c["x"] += m[0] * m[2]; c["y"] += m[1] * m[2]
            for n in nb.get(k, []):
                if n not in gesehen and zu.get(n) == sid and n in geo["mitte"]:
                    gesehen.add(n); stapel.append(n)
        c["x"] /= c["a"]; c["y"] /= c["a"]
        nah = min(c["ids"], key=lambda m: (m[0] - c["x"]) ** 2 + (m[1] - c["y"]) ** 2)
        if ((nah[0] - c["x"]) ** 2 + (nah[1] - c["y"]) ** 2) ** 0.5 > c["a"] ** 0.5 * 0.12:
            c["x"], c["y"] = nah[0], nah[1]
        out.append(c)
    return sorted(out, key=lambda c: -c["a"])


class _Ausschnitt:
    """Abbildung Kartenkoordinaten → Bildpunkte (Ausschnitt um die Teilstaaten, Teilstaaten rechts der Legende)."""

    def __init__(self, geo, stand, B, H):
        xs, ys = [], []
        for gid in stand["gebiete"]:
            if gid in geo["gebiete"]:
                for r in _ringe(geo["gebiete"][gid]["d"]):
                    for x, y in r:
                        xs.append(x); ys.append(y)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        self.s = max((x1 - x0) * 1.1 / B, (y1 - y0) * 1.1 / H)
        self.vx = (x0 + x1) / 2 - B * self.s / 2 - B * self.s * 0.07
        self.vy = (y0 + y1) / 2 - H * self.s / 2
        self.B, self.H, self.W = B, H, geo["breite"]
        self.zt = math.log2(self.W / (B * self.s)) + math.log2(1300 / 256)    # Kartenstufe wie auf der Website

    def p(self, x, y):
        return ((x - self.vx) / self.s, (y - self.vy) / self.s)

    def ringe(self, d):
        for r in _ringe(d):
            yield [self.p(x, y) for x, y in r]

    def linien(self, d):
        for l in _linien(d):
            yield [self.p(x, y) for x, y in l]


def _details(bild, geo, stand, staaten, a):
    """Grenzen, Flüsse, Seen und Namen (wie auf der Karte der Website)."""
    B, H = bild.size
    d = ImageDraw.Draw(bild)
    quelle = "source-sans-3.woff2"
    for p in geo.get("seen", []):
        for r in a.ringe(p):
            if len(r) > 2:
                d.polygon(r, fill=MEER, outline=(126, 166, 196))
    for k, w, f in ((1, 4, (79, 147, 200)), (2, 3, (95, 158, 207)), (3, 2, (110, 170, 215))):
        dd = geo.get("fluesse", {}).get(str(k))
        if dd:
            for l in a.linien(dd):
                d.line(l, fill=f, width=w, joint="curve")
    ov = Image.new("RGBA", (B, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for l in a.linien(geo.get("grenzen", "")) if geo.get("grenzen") else []:
        od.line(l, fill=(110, 116, 132, 220), width=2)
    zu = stand["gebiete"]
    for ga, gb, dd in geo["kanten"]:
        if (zu.get(ga) or "") != (zu.get(gb) or ""):
            farbe, w = (16, 22, 46, 255), 4
        elif geo["gebiete"][ga]["c"] != geo["gebiete"][gb]["c"]:
            farbe, w = (75, 81, 99, 220), 2
        else:
            farbe, w = (29, 37, 64, 70), 1
        for l in a.linien(dd):
            od.line(l, fill=farbe, width=w, joint="curve")
    bild.paste(Image.alpha_composite(bild.convert("RGBA"), ov).convert("RGB"))
    d = ImageDraw.Draw(bild)
    belegt = []

    def frei(box):
        if box[2] < 0 or box[0] > B or box[3] < 0 or box[1] > H:
            return False
        for b in belegt:
            if box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1]:
                return False
        belegt.append(box)
        return True

    def halo(xy, t, font, fuell, rand, anker="mm", breite=4):
        d.text(xy, t, font=font, fill=fuell, anchor=anker, stroke_width=breite, stroke_fill=rand)

    # Orte: Hauptstädte zuerst (vor den Teilstaatsnamen), die übrigen danach, nur bis zur Stufe des Bildes
    def orte(haupt):
        for n, ox, oy, mz, rang in sorted(geo.get("orte", []), key=lambda o: (o[4], o[3])):
            if mz > a.zt - 0.4 or (rang == 1) != haupt:
                continue
            x, y = a.p(ox, oy)
            px, r = (36, 9) if rang == 1 else (31, 7) if rang == 2 else (28, 6)
            f = _schrift(quelle, px, 700 if rang == 1 else 600)
            w = d.textlength(n, font=f)
            if not frei((x - r, y - px / 2, x + r * 2.4 + w, y + px / 2)):
                continue
            d.ellipse([x - r, y - r, x + r, y + r], fill=(201, 164, 58) if rang == 1 else (16, 22, 46), outline=(16, 22, 46) if rang == 1 else (255, 255, 255), width=3)
            halo((x + r * 2, y), n, f, (16, 22, 46), (255, 255, 255), anker="lm", breite=4)

    orte(True)
    # Teilstaaten
    for c in _komponenten(geo, stand):
        st = staaten.get(c["staat"])
        x, y = a.p(c["x"], c["y"])
        if not st or (c["a"] ** 0.5) / a.s < 90:
            continue
        px = int(max(28, min(44, (c["a"] ** 0.5) / a.s * 0.12)))
        f = _schrift(quelle, px, 700)
        wort = st["name"].split(" ")
        m = (len(wort) + 1) // 2
        zeilen = [" ".join(wort[:m]), " ".join(wort[m:])] if len(st["name"]) > 14 and len(wort) > 1 else [st["name"]]
        w = max(d.textlength(t, font=f) for t in zeilen)
        h = len(zeilen) * px * 1.15
        if not frei((x - w / 2, y - h / 2, x + w / 2, y + h / 2)):
            continue
        r, g, b = _hex(st["farbe"])
        dunkel = st["muster"] == "voll" and (0.299 * r + 0.587 * g + 0.114 * b) < 140
        for i, t in enumerate(zeilen):
            halo((x, y - h / 2 + (i + 0.5) * px * 1.15), t, f, (255, 255, 255) if dunkel else (16, 22, 46),
                 (0, 0, 0) if dunkel else (255, 255, 255), breite=4)
    orte(False)
    # Länder und Meere
    for n, lx, ly, mn, mx, eigen in geo.get("laender_namen", []):
        if eigen or a.zt < mn + 0.3 or a.zt > mx + 1.5:
            continue
        x, y = a.p(lx, ly)
        f = _schrift(quelle, 34, 600)
        t = " ".join(n.upper())
        w = d.textlength(t, font=f)
        if frei((x - w / 2, y - 22, x + w / 2, y + 22)):
            halo((x, y), t, f, (138, 144, 156), (209, 219, 221), breite=3)
    for n, mx_, my_, rot, mn, mx in geo.get("meere", []):
        if a.zt < mn or a.zt > mx + 1:
            continue
        x, y = a.p(mx_, my_)
        f = _schrift(quelle, 38, 400)
        kachel = Image.new("RGBA", (int(d.textlength(n, font=f)) + 40, 70), (0, 0, 0, 0))
        if not frei((x - kachel.width / 2, y - 30, x + kachel.width / 2, y + 30)):
            continue
        ImageDraw.Draw(kachel).text((kachel.width / 2, 35), n, font=f, fill=(91, 134, 168, 255), anchor="mm")
        kachel = kachel.rotate(-rot, expand=True, resample=Image.BICUBIC)
        bild.paste(kachel, (int(x - kachel.width / 2), int(y - kachel.height / 2)), kachel)


def zeichnen(geo, stand, ziel=PFAD):
    B, H = 3000, 2325
    a = _Ausschnitt(geo, stand, B, H)
    bild = Image.new("RGB", (B, H), MEER)
    d = ImageDraw.Draw(bild)
    for p in geo["land"]:
        for r in a.ringe(p):
            if len(r) > 2:
                d.polygon(r, fill=LAND)
    staaten = {s["id"]: s for s in stand["staaten"]}
    je_staat = {}
    for gid, g in geo["gebiete"].items():
        sid = stand["gebiete"].get(gid)
        if sid in staaten:
            je_staat.setdefault(sid, []).append(g["d"])
        else:
            for r in a.ringe(g["d"]):
                if len(r) > 2:
                    d.polygon(r, fill=LAND, outline=LAND)
    for sid, pfade in je_staat.items():
        maske = Image.new("L", (B, H), 0)
        md = ImageDraw.Draw(maske)
        for p in pfade:
            for r in a.ringe(p):
                if len(r) > 2:
                    md.polygon(r, fill=255, outline=255)
        fuellung = _muster(staaten[sid], B, H)
        if isinstance(fuellung, tuple):
            bild.paste(fuellung, (0, 0, B, H), maske)
        else:
            bild.paste(fuellung, (0, 0), maske)

    _details(bild, geo, stand, staaten, a)
    d = ImageDraw.Draw(bild)

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
