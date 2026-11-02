import json, sys
import numpy as np
from shapely.geometry import shape
S = sys.argv[1]
farben = json.load(open(S + "/werkzeug/farben.json"))
P = {"pfalz": (0, 0, 0), "frei": (135, 164, 214), "hanse": (251, 204, 223), "wuerzburg": (202, 178, 214), "franken": (186, 160, 135),
     "holstein": (190, 50, 2), "venedig": (114, 178, 141), "schwaben": (255, 127, 0), "stuhl": (77, 1, 76), "tirol": (178, 221, 105),
     "apulien": (218, 148, 148), "boehmen": (244, 166, 130), "hannover": (198, 167, 14), "schweiz": (203, 53, 53), "lausitz": (252, 218, 199),
     "maehren": (203, 81, 63), "berlin": (141, 62, 30), "longinus": (255, 255, 51), "westerwald": (5, 102, 97),
     "": (209, 219, 221), "meer": (209, 229, 240)}
namen = list(P); proto = np.array([P[n] for n in namen], float)
zu, unsicher = {}, []
for k, v in farben.items():
    d = np.sqrt(((proto - np.array(v["mittel"])) ** 2).sum(1)); i = d.argmin()
    s = namen[i] if namen[i] != "meer" else ""
    zu[k] = s
    zweit = np.sort(d)[1]
    if d[i] > 30 or zweit - d[i] < 15:
        unsicher.append((k, v["n"][:24], v["c"], s, round(float(d[i])), namen[np.argsort(d)[1]], v["px"]))
# verdeckte/fehlende Gebiete: Nachbarn entscheiden
nuts = json.load(open(S + "/geo_roh/NUTS_RG_10M_2021_4326_LEVL_3.geojson"))
geo = {f["properties"]["NUTS_ID"]: shape(f["geometry"]).buffer(0) for f in nuts["features"]}
info = {f["properties"]["NUTS_ID"]: (f["properties"]["NAME_LATN"], f["properties"]["CNTR_CODE"]) for f in nuts["features"]}
im_bereich = [k for k, g in geo.items() if -12 < g.centroid.x < 32 and 34 < g.centroid.y < 60]
fehlend = [k for k in im_bereich if k not in zu]
print(len(im_bereich), "Gebiete im Kartenbereich,", len(fehlend), "ohne Farbe (verdeckt/außerhalb)")
for runde in range(30):
    neu = {}
    for k in fehlend:
        if k in zu: continue
        nb = [zu[j] for j in im_bereich if j in zu and j != k and geo[k].buffer(0.02).intersects(geo[j])]
        if nb:
            neu[k] = max(set(nb), key=nb.count)
    if not neu: break
    zu.update(neu)
geschaetzt = [k for k in fehlend if k in zu]
from collections import Counter
c = Counter(v for v in zu.values() if v)
print("Gebiete je Teilstaat:", dict(c))
print("geschätzt (verdeckt):", Counter((info[k][1], zu[k]) for k in geschaetzt))
print("unsicher:", len(unsicher))
for u in sorted(unsicher, key=lambda x: -x[4])[:45]: print("  ", u)
json.dump({"zu": {k: v for k, v in zu.items() if k in im_bereich}, "geschaetzt": geschaetzt, "unsicher": [u[0] for u in unsicher]},
          open(S + "/werkzeug/zuordnung.json", "w"), ensure_ascii=False)
