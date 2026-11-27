"""Erzeugt optimierte WebP-Varianten (640 / 1280 px) aller Bilder in assets/img/original.
Aufruf:  python _build/bilder.py
"""
import json, os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "img", "original")
OUT = os.path.join(ROOT, "assets", "img")
SIZES = (640, 1280)

meta = {}
for name in sorted(os.listdir(SRC)):
    stem, _ = os.path.splitext(name)
    im = Image.open(os.path.join(SRC, name))
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    meta[stem] = {"file": name, "w": im.width, "h": im.height}
    for size in SIZES:
        target = os.path.join(OUT, f"{stem}-{size}.webp")
        if os.path.exists(target):
            continue
        copy = im.copy()
        if copy.width > size:
            copy = copy.resize((size, round(copy.height * size / copy.width)), Image.LANCZOS)
        copy.save(target, "WEBP", quality=82, method=6)

with open(os.path.join(os.path.dirname(__file__), "bilder.json"), "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=1)
print(f"{len(meta)} Bilder verarbeitet")

# Favicons, Vorschaubild und Wasserzeichen aus dem Reichswappen (seit 27.11.2026: Greifenwappen in Navy)
LOGO = os.path.join(SRC, "ibeaf46b6d63d94cd.png")
NAVY = (1, 37, 71)
logo = Image.open(LOGO).convert("RGBA")
logo = logo.crop(logo.getbbox())


def quadrat(bild, seite, rand=0, grund=(0, 0, 0, 0)):
    q = Image.new("RGBA", (seite, seite), grund)
    f = (seite - 2 * rand) / max(bild.size)
    k = bild.resize((round(bild.width * f), round(bild.height * f)), Image.LANCZOS)
    q.alpha_composite(k, ((seite - k.width) // 2, (seite - k.height) // 2))
    return q


def weiss(bild):
    w = Image.new("RGBA", bild.size, (255, 255, 255, 0))
    w.putalpha(bild.getchannel("A"))
    return w


quadrat(logo, 256).save(os.path.join(ROOT, "assets", "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])
quadrat(logo, 32).save(os.path.join(ROOT, "assets", "favicon-32.png"))
touch = quadrat(logo, 180, 18, (255, 255, 255, 255))
touch.convert("RGB").save(os.path.join(ROOT, "assets", "apple-touch-icon.png"))

og = Image.new("RGBA", (1200, 630), (255, 255, 255, 255))
gross = quadrat(logo, 470)
og.alpha_composite(gross, ((1200 - 470) // 2, (630 - 470) // 2))
og.convert("RGB").save(os.path.join(ROOT, "assets", "og-image.jpg"), quality=88)

# Wasserzeichen am Seitenrand (wie auf royal.uk): Navy bzw. Weiß mit sehr geringer Deckkraft
for name, farbe, deckung in (("wappen-wz-hell.webp", logo, .055), ("wappen-wz-dunkel.webp", weiss(logo), .05)):
    wz = farbe.resize((640, round(640 * logo.height / logo.width)), Image.LANCZOS)
    wz.putalpha(wz.getchannel("A").point(lambda a: int(a * deckung)))
    wz.save(os.path.join(OUT, name), "WEBP", quality=80, method=6)
print("Favicons, OG-Bild und Wasserzeichen erzeugt")
