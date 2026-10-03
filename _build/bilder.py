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

# Favicons und Vorschaubild für soziale Netzwerke aus dem Reichswappen
LOGO = os.path.join(SRC, "i92158683d4a0cca4.png")
NAVY = (18, 24, 60)
GOLD = (201, 164, 58)
logo = Image.open(LOGO).convert("RGBA")
bbox = logo.getbbox()
logo = logo.crop(bbox)

ico = logo.copy()
ico.save(os.path.join(ROOT, "assets", "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])
logo.resize((32, 32), Image.LANCZOS).save(os.path.join(ROOT, "assets", "favicon-32.png"))

touch = Image.new("RGBA", (180, 180), NAVY + (255,))
small = logo.resize((150, round(logo.height * 150 / logo.width)), Image.LANCZOS)
touch.alpha_composite(small, ((180 - small.width) // 2, (180 - small.height) // 2))
touch.convert("RGB").save(os.path.join(ROOT, "assets", "apple-touch-icon.png"))

from PIL import ImageDraw
og = Image.new("RGBA", (1200, 630), NAVY + (255,))
d = ImageDraw.Draw(og)
d.rectangle((18, 18, 1181, 611), outline=GOLD + (110,), width=2)
d.rectangle((28, 28, 1171, 601), outline=GOLD + (50,), width=1)
big = logo.resize((480, round(logo.height * 480 / logo.width)), Image.LANCZOS)
og.alpha_composite(big, ((1200 - big.width) // 2, (630 - big.height) // 2))
og.convert("RGB").save(os.path.join(ROOT, "assets", "og-image.jpg"), quality=88)
print("Favicons und OG-Bild erzeugt")
