"""Lädt OpenFreeMap-Vektorkacheln (Stufe 8, OpenStreetMap-Daten) für Europa nach ofm/ (im aktuellen Ordner); danach karte_infra.py <ne> <ordner-mit-ofm> ausführen.
Die Kartenversion V steht im TileJSON https://tiles.openfreemap.org/planet."""
import math, os, sys, time, requests
from concurrent.futures import ThreadPoolExecutor
V = "20261101_080013_pt"
Z = 8
def tile(lon, lat):
    n = 2 ** Z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y
x0, y1 = tile(-12, 34); x1, y0 = tile(32, 62)
todo = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
print(len(todo), "Kacheln", flush=True)
s = requests.Session(); s.headers["User-Agent"] = "ImperiumGermanicumKarte/1.0 (luke.bongers2807@gmail.com)"
def hol(t):
    x, y = t
    f = f"ofm/{Z}_{x}_{y}.pbf"
    if os.path.exists(f):
        return 1
    for v in range(6):
        try:
            r = s.get(f"https://tiles.openfreemap.org/planet/{V}/{Z}/{x}/{y}.pbf", timeout=30)
            if r.status_code == 200:
                open(f + ".tmp", "wb").write(r.content); os.replace(f + ".tmp", f); return 1
            if r.status_code == 404:
                open(f, "wb").write(b""); return 1
        except Exception:
            pass
        time.sleep(2 + v * 3)
    return 0
n = 0
with ThreadPoolExecutor(6) as ex:
    for ok in ex.map(hol, todo):
        n += ok
        if n % 100 == 0: print(n, flush=True)
print("FERTIG", n, flush=True)
