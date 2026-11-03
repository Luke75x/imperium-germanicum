import json, math, sys
import numpy as np
from PIL import Image, ImageDraw
S = sys.argv[1]; W = 500
im = Image.open("/root/imperium_germanicum/assets/img/original/i74e21fe796eaa5e0.jpg").convert("RGB")
H = round(W * im.size[1] / im.size[0])
a = np.asarray(im.resize((W, H)), dtype=np.int16)
land_bild = ~(np.abs(a - np.array([209, 229, 240])).sum(axis=2) < 18)
gueltig = np.ones_like(land_bild)
gueltig[int(0.055 * H):int(0.68 * H), int(0.055 * W):int(0.385 * W)] = False
gueltig[int(0.97 * H):, int(0.85 * W):] = False
cn = json.load(open(S + "/geo_roh/CNTR_RG_10M_2020_4326.geojson"))
roh = []
for f in cn["features"]:
    g = f["geometry"]
    for p in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
        r = np.array(p[0])
        if ((r[:, 0] > -25) & (r[:, 0] < 60) & (r[:, 1] > 25) & (r[:, 1] < 75)).any():
            roh.append(r)
R = math.radians
def mercator(lon, lat): return np.radians(lon), np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
def miller(lon, lat): return np.radians(lon), 1.25 * np.log(np.tan(np.pi / 4 + 0.4 * np.radians(lat)))
def equirect(lon, lat): return np.radians(lon), np.radians(lat)
def laea(lon, lat, l0=10, p0=52):
    l, p = np.radians(lon - l0), np.radians(lat); p0 = R(p0)
    k = np.sqrt(2 / (1 + np.sin(p0) * np.sin(p) + np.cos(p0) * np.cos(p) * np.cos(l)))
    return k * np.cos(p) * np.sin(l), k * (np.cos(p0) * np.sin(p) - np.sin(p0) * np.cos(p) * np.cos(l))
def gall(lon, lat): return np.radians(lon) / math.sqrt(2), (1 + math.sqrt(2) / 2) * np.tan(np.radians(lat) / 2)
def robinson(lon, lat):  # Näherung über Tabelle
    T = [(0,1,0),(5,.9986,.062),(10,.9954,.124),(15,.99,.186),(20,.9822,.248),(25,.973,.31),(30,.96,.372),(35,.9427,.434),(40,.9216,.4958),(45,.8962,.5571),(50,.8679,.6176),(55,.835,.6769),(60,.7986,.7346),(65,.7597,.7903),(70,.7186,.8435),(75,.6732,.8936),(80,.6213,.9394)]
    la = np.abs(lat); x = np.interp(la, [t[0] for t in T], [t[1] for t in T]); y = np.interp(la, [t[0] for t in T], [t[2] for t in T])
    return 0.8487 * x * np.radians(lon), 1.3523 * y * np.sign(lat)
def maske(proj, p):
    sx, sy, tx, ty = p
    m = Image.new("1", (W, H), 0); d = ImageDraw.Draw(m)
    for r in proj:
        x = r[0] * sx + tx; y = -r[1] * sy + ty
        if x.max() < 0 or x.min() > W or y.max() < 0 or y.min() > H: continue
        d.polygon(list(zip(x.tolist(), y.tolist())), fill=1)
    return np.asarray(m, dtype=bool)
def anpassen(name, f):
    proj = [f(r[:, 0], np.clip(r[:, 1], -85, 85)) for r in roh]
    # Start: Ausschnitt lon -6..26, lat 35..57 auf das Bild legen
    x0, _ = f(np.array([-6.0]), np.array([46.0])); x1, _ = f(np.array([26.0]), np.array([46.0]))
    _, y0 = f(np.array([10.0]), np.array([57.0])); _, y1 = f(np.array([10.0]), np.array([36.0]))
    sx = W / (x1[0] - x0[0]); sy = H / (y0[0] - y1[0])
    p = [sx, sy, -x0[0] * sx, y0[0] * sy]
    def g(q): m = maske(proj, q); return ((m == land_bild) & gueltig).sum() / gueltig.sum()
    best = (g(p), p); st = [0.1, 0.1, 30, 30]
    for _ in range(8):
        bes = True
        while bes:
            bes = False
            for i in range(4):
                for vz in (-1, 1):
                    q = list(best[1]); q[i] = q[i] * (1 + vz * st[i]) if i < 2 else q[i] + vz * st[i]
                    v = g(q)
                    if v > best[0]: best = (v, q); bes = True
        st = [s / 2 for s in st]
    print("%-10s %.4f  sy/sx=%.4f" % (name, best[0], best[1][1] / best[1][0]), flush=True)
    return best
erg = {}
for name, f in [("mercator", mercator), ("miller", miller), ("equirect", equirect), ("gall", gall), ("robinson", robinson), ("laea", laea)]:
    erg[name] = anpassen(name, f)
json.dump({k: v for k, v in erg.items()}, open(S + "/werkzeug/projektionen.json", "w"))
