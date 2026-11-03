"""Mittlere Farbe jedes NUTS-3-Gebiets in der alten Karte (LAEA, an die Karte angepasst)."""
import json, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
S = sys.argv[1]
im = np.asarray(Image.open("/root/imperium_germanicum/assets/img/original/i74e21fe796eaa5e0.jpg").convert("RGB")).astype(float)
H0, W0 = im.shape[:2]
sx, sy, tx, ty = json.load(open(S + "/werkzeug/projektionen.json"))["laea"][1]
k = W0 / 500
def laea(lon, lat, l0=10, p0=52):
    l, p = np.radians(np.asarray(lon) - l0), np.radians(np.asarray(lat)); p0 = np.radians(p0)
    q = np.sqrt(2 / (1 + np.sin(p0) * np.sin(p) + np.cos(p0) * np.cos(p) * np.cos(l)))
    return q * np.cos(p) * np.sin(l), q * (np.cos(p0) * np.sin(p) - np.sin(p0) * np.cos(p) * np.cos(l))
def bild(lon, lat):
    x, y = laea(lon, lat); return (x * sx + tx) * k, (-y * sy + ty) * k
legende = (slice(int(0.055 * H0), int(0.68 * H0)), slice(int(0.055 * W0), int(0.385 * W0)))
nuts = json.load(open(S + "/geo_roh/NUTS_RG_10M_2021_4326_LEVL_3.geojson"))
out = {}
for f in nuts["features"]:
    g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    ringe = []
    for p in polys:
        r = np.array(p[0]); x, y = bild(r[:, 0], r[:, 1]); ringe.append((x, y))
    xs = np.concatenate([r[0] for r in ringe]); ys = np.concatenate([r[1] for r in ringe])
    x0, x1, y0, y1 = int(max(xs.min(), 0)), int(min(xs.max() + 1, W0)), int(max(ys.min(), 0)), int(min(ys.max() + 1, H0))
    if x1 - x0 < 2 or y1 - y0 < 2:
        continue
    m = Image.new("L", (x1 - x0, y1 - y0), 0); d = ImageDraw.Draw(m)
    for x, y in ringe:
        d.polygon(list(zip((x - x0).tolist(), (y - y0).tolist())), fill=255)
    voll = np.asarray(m) > 0
    ero = np.asarray(m.filter(ImageFilter.MinFilter(7))) > 0   # Rand weg (Grenzlinien, Ungenauigkeit)
    mask = ero if ero.sum() >= 12 else voll
    lm = np.zeros((H0, W0), bool); lm[legende] = True
    mask = mask & ~lm[y0:y1, x0:x1]
    if mask.sum() < 3:
        continue
    px = im[y0:y1, x0:x1][mask]
    out[f["properties"]["NUTS_ID"]] = {"n": f["properties"]["NAME_LATN"], "c": f["properties"]["CNTR_CODE"],
                                       "mittel": px.mean(0).round(1).tolist(), "px": int(mask.sum()),
                                       "std": px.std(0).mean().round(1).item()}
json.dump(out, open(S + "/werkzeug/farben.json", "w"), ensure_ascii=False)
print(len(out), "Gebiete im Bild")
for i in ["FR101", "FR714", "DE300", "DEA23", "DE212", "ITF47", "ITI43", "CH011", "CZ010", "CZ064", "PL911", "NL329", "BE100", "ES300", "DK011", "HU110", "AT323", "SI041", "HR031", "LT011", "SK010", "DEF07", "DE600", "DE929", "ITH35", "DE264", "DED2C", "ITG12", "FRM01", "DEB34", "DE254", "DEB1A"]:
    if i in out: print(i, out[i]["n"][:22], out[i]["mittel"], "std", out[i]["std"], "px", out[i]["px"])
