import json, sys
from collections import Counter
import numpy as np
from shapely.geometry import shape
from PIL import Image, ImageDraw
S = sys.argv[1]
z = json.load(open(S + "/werkzeug/zuordnung.json")); zu = z["zu"]
farben = json.load(open(S + "/werkzeug/farben.json"))
nuts = json.load(open(S + "/geo_roh/NUTS_RG_10M_2021_4326_LEVL_3.geojson"))
geo = {f["properties"]["NUTS_ID"]: shape(f["geometry"]).buffer(0) for f in nuts["features"] if f["properties"]["NUTS_ID"] in zu}
nb = {k: [j for j in geo if j != k and geo[k].buffer(0.02).intersects(geo[j])] for k in z["unsicher"] if k in geo}
geaendert = []
for k in z["unsicher"]:
    if k not in geo or farben.get(k, {}).get("px", 0) > 400: continue
    c = Counter(zu[j] for j in nb[k])
    neu = c.most_common(1)[0][0]
    if neu != zu[k]: geaendert.append((k, farben[k]["n"][:20], zu[k], neu)); zu[k] = neu
print("geglättet:", geaendert)
json.dump(zu, open(S + "/werkzeug/zuordnung_final.json", "w"), ensure_ascii=False)
F = {"pfalz": (0, 0, 0), "frei": (120, 150, 215), "hanse": (252, 204, 228), "wuerzburg": (202, 178, 214), "franken": (186, 160, 135),
     "holstein": (190, 50, 2), "venedig": (114, 178, 141), "schwaben": (255, 127, 0), "stuhl": (77, 1, 76), "tirol": (178, 221, 105),
     "apulien": (224, 150, 150), "boehmen": (244, 166, 130), "hannover": (199, 167, 13), "schweiz": (204, 52, 51), "lausitz": (254, 219, 199),
     "maehren": (203, 80, 62), "berlin": (137, 46, 2), "longinus": (255, 255, 51), "westerwald": (1, 102, 94), "": (209, 219, 221)}
sx, sy, tx, ty = json.load(open(S + "/werkzeug/projektionen.json"))["laea"][1]
W0, H0 = 3000, 2325; k = W0 / 500
def laea(lon, lat, l0=10, p0=52):
    l, p = np.radians(np.asarray(lon) - l0), np.radians(np.asarray(lat)); p0 = np.radians(p0)
    q = np.sqrt(2 / (1 + np.sin(p0) * np.sin(p) + np.cos(p0) * np.cos(p) * np.cos(l)))
    return q * np.cos(p) * np.sin(l), q * (np.cos(p0) * np.sin(p) - np.sin(p0) * np.cos(p) * np.cos(l))
img = Image.new("RGB", (W0, H0), (209, 229, 240)); d = ImageDraw.Draw(img)
cn = json.load(open(S + "/geo_roh/CNTR_RG_10M_2020_4326.geojson"))
def ringe(g):
    for p in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
        r = np.array(p[0]); x, y = laea(r[:, 0], r[:, 1]); yield list(zip(((x * sx + tx) * k).tolist(), ((-y * sy + ty) * k).tolist()))
for f in cn["features"]:
    for r in ringe(f["geometry"]): d.polygon(r, fill=(209, 219, 221))
for f in nuts["features"]:
    i = f["properties"]["NUTS_ID"]
    if i in zu:
        for r in ringe(f["geometry"]): d.polygon(r, fill=F[zu[i]], outline=(255, 255, 255) if zu[i] else None)
alt = Image.open("/root/imperium_germanicum/assets/img/original/i74e21fe796eaa5e0.jpg").convert("RGB")
neben = Image.new("RGB", (1400, 543)); neben.paste(alt.resize((700, 543)), (0, 0)); neben.paste(img.resize((700, 543)), (700, 0))
neben.save(S + "/werkzeug/vergleich.png"); img.crop((1000, 0, 2600, 1300)).resize((1200, 975)).save(S + "/werkzeug/rekonstruktion_mitte.png")
