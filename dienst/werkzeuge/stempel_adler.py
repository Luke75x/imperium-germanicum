"""Erzeugt aus dem Reichsadler-Wappen (werkzeuge/stempel_grundlage/reichsadler.webp) die Stempelmaske pass_bilder/stempel_adler.png:
weiß mit Deckkraft = „Tinte“ (Gelb und Weiß durchsichtig, Linien voll, Flächen etwas heller), eingefärbt wird per CSS/SVG-Maske.
Aufruf: .venv/bin/python werkzeuge/stempel_adler.py
"""
import asyncio
import base64
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, ".."))
import bild  # noqa: F401,E402  setzt PLAYWRIGHT_BROWSERS_PATH
from playwright.async_api import async_playwright  # noqa: E402

QUELLE = os.path.join(HIER, "stempel_grundlage", "reichsadler.webp")
ZIEL = os.path.join(HIER, "..", "pass_bilder", "stempel_adler.png")
BREITE = 380

JS = r"""
async ([src, B]) => {
  const img = new Image(); img.src = src; await img.decode();
  const H = Math.round(img.naturalHeight * B / img.naturalWidth);
  const c = document.createElement("canvas"); c.width = B; c.height = H;
  const x = c.getContext("2d"); x.drawImage(img, 0, 0, B, H);
  const d = x.getImageData(0, 0, B, H), p = d.data;
  for (let i = 0; i < p.length; i += 4) {
    if (!p[i + 3]) continue;
    const L = (0.3 * p[i] + 0.59 * p[i + 1] + 0.11 * p[i + 2]) / 255;
    let a = L < 0.26 ? 1 : L < 0.40 ? 0.66 : Math.max(0, Math.min(1, (0.80 - L) / 0.38));
    p[i] = p[i + 1] = p[i + 2] = 255; p[i + 3] = Math.round(255 * a * p[i + 3] / 255);
  }
  x.putImageData(d, 0, 0);
  return c.toDataURL("image/png");
}
"""


async def main():
    with open(QUELLE, "rb") as f:
        src = "data:image/webp;base64," + base64.b64encode(f.read()).decode()
    async with async_playwright() as p:
        b = await p.chromium.launch()
        url = await (await b.new_page()).evaluate(JS, [src, BREITE])
        await b.close()
    with open(ZIEL, "wb") as f:
        f.write(base64.b64decode(url.split(",", 1)[1]))
    print("Stempelmaske →", os.path.abspath(ZIEL))


if __name__ == "__main__":
    asyncio.run(main())
