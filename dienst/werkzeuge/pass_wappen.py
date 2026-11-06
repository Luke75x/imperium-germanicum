"""Erzeugt aus dem Kaiserwappen der Website (gelber Grund, schwarzer Rahmen) die Wappenbilder der Passdruckvorlagen:
pass_bilder/wappen.png (farbig, freigestellt) und pass_bilder/wappen_gold.png (einfarbig gold wie eine Prägung, für Umschläge).

Freistellen: Flood-Fill vom Rand des gelben Feldes aus (nur zusammenhängendes Gelb wird durchsichtig, das Gelb im Schild bleibt).
Aufruf: .venv/bin/python werkzeuge/pass_wappen.py
"""
import asyncio
import base64
import os

from playwright.async_api import async_playwright

HIER = os.path.dirname(os.path.abspath(__file__))
QUELLE = "/root/imperium_germanicum/assets/img/original/if0978cec8f01efe8.jpg"
ZIEL = os.path.join(HIER, "..", "pass_bilder")
SCHILD = "[0.40, 0.38, 0.60, 0.78]"   # Kasten (Anteile des Ausschnitts): gelbe Flächen mit Schwerpunkt darin = Schildgrund, bleiben

JS = r"""
async (src) => {
  const img = new Image(); img.src = src; await img.decode();
  const W = img.naturalWidth, R = Math.round(W * 0.085), S = W - 2 * R;     // innerhalb des schwarzen Rahmens
  const c = document.createElement("canvas"); c.width = S; c.height = S;
  const x = c.getContext("2d"); x.drawImage(img, R, R, S, S, 0, 0, S, S);
  const d = x.getImageData(0, 0, S, S), p = d.data;
  const gr = [p[0], p[1], p[2]];
  const nah = (i) => { const a = p[i] - gr[0], b = p[i + 1] - gr[1], e = p[i + 2] - gr[2]; return a * a + b * b + e * e < 70 * 70; };
  const weg = new Uint8Array(S * S), st = [];
  for (let i = 0; i < S; i++) st.push(i, (S - 1) * S + i, i * S, i * S + S - 1);
  while (st.length) {
    const q = st.pop();
    if (weg[q] || !nah(q * 4)) continue;
    weg[q] = 1;
    const u = q % S, v = (q / S) | 0;
    if (u > 0) st.push(q - 1); if (u < S - 1) st.push(q + 1); if (v > 0) st.push(q - S); if (v < S - 1) st.push(q + S);
  }
  // eingeschlossene gelbe Flächen (zwischen Greifen und Schild): Komponenten ab MIN Pixeln entfernen, außer der Schildfläche
  // (Schwerpunkt im Kasten SCHILD – der gelbe Grund neben dem Adler im Schild)
  const komp = new Int32Array(S * S).fill(-1), groesse = [], mitte = [];
  for (let q0 = 0; q0 < S * S; q0++) {
    if (weg[q0] || komp[q0] >= 0 || !nah(q0 * 4)) continue;
    const id = groesse.length; let n = 0, sx = 0, sy = 0; const s2 = [q0];
    while (s2.length) {
      const q = s2.pop();
      if (komp[q] >= 0 || weg[q] || !nah(q * 4)) continue;
      komp[q] = id; n++;
      const u = q % S, v = (q / S) | 0; sx += u; sy += v;
      if (u > 0) s2.push(q - 1); if (u < S - 1) s2.push(q + 1); if (v > 0) s2.push(q - S); if (v < S - 1) s2.push(q + S);
    }
    groesse.push(n); mitte.push([sx / n / S, sy / n / S]);
  }
  const [sx0, sy0, sx1, sy1] = SCHILD;
  const schild = new Set(mitte.map(([u, v], i) => (u > sx0 && u < sx1 && v > sy0 && v < sy1) ? i : -1));
  const info = groesse.map((n, i) => [i, n]).filter(([i, n]) => n > MIN).map(([i, n]) => [n, mitte[i].map(z => z.toFixed(2)).join("/"), schild.has(i)]);
  for (let q = 0; q < S * S; q++) if (komp[q] >= 0 && groesse[komp[q]] > MIN && !schild.has(komp[q])) weg[q] = 1;
  let x0 = S, y0 = S, x1 = 0, y1 = 0;
  for (let q = 0; q < S * S; q++) {
    if (weg[q]) { p[q * 4 + 3] = 0; continue; }
    const u = q % S, v = (q / S) | 0;
    x0 = Math.min(x0, u); x1 = Math.max(x1, u); y0 = Math.min(y0, v); y1 = Math.max(y1, v);
  }
  // Kantenpixel neben entferntem Gelb halbtransparent (weicher Rand)
  for (let q = 0; q < S * S; q++) {
    if (weg[q]) continue;
    const u = q % S, v = (q / S) | 0;
    if ((u > 0 && weg[q - 1]) || (u < S - 1 && weg[q + 1]) || (v > 0 && weg[q - S]) || (v < S - 1 && weg[q + S])) p[q * 4 + 3] = 150;
  }
  x.putImageData(d, 0, 0);
  const w = x1 - x0 + 1, h = y1 - y0 + 1;
  const aus = (fn) => {
    const o = document.createElement("canvas"); o.width = w; o.height = h;
    const ox = o.getContext("2d"); ox.drawImage(c, x0, y0, w, h, 0, 0, w, h);
    if (fn) { const od = ox.getImageData(0, 0, w, h); fn(od.data); ox.putImageData(od, 0, 0); }
    return o.toDataURL("image/png");
  };
  const gold = (q) => {
    for (let i = 0; i < q.length; i += 4) {
      if (!q[i + 3]) continue;
      const L = (0.3 * q[i] + 0.59 * q[i + 1] + 0.11 * q[i + 2]) / 255;
      // dunkle Linien = kräftiges Gold, helle Flächen = schwache Prägung
      const a = Math.max(0, Math.min(1, (0.8 - L) / 0.5));
      q[i] = 222 - 30 * L; q[i + 1] = 184 - 20 * L; q[i + 2] = 96 - 10 * L; q[i + 3] = Math.round(q[i + 3] * a);
    }
  };
  return [aus(null), aus(gold), w, h, info];
}
"""


async def main():
    os.makedirs(ZIEL, exist_ok=True)
    with open(QUELLE, "rb") as f:
        src = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        farbig, gold, w, h, info = await pg.evaluate(JS.replace("SCHILD", SCHILD).replace("MIN", "1500"), src)
        print("gelbe Flächen (id, Pixel, Schild):", info)
        await b.close()
    for name, url in (("wappen.png", farbig), ("wappen_gold.png", gold)):
        with open(os.path.join(ZIEL, name), "wb") as f:
            f.write(base64.b64decode(url.split(",", 1)[1]))
    print("Wappen", w, "x", h, "→", ZIEL)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(HIER, ".."))
    import bild  # noqa: F401  setzt PLAYWRIGHT_BROWSERS_PATH
    asyncio.run(main())
