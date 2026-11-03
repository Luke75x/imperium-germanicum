"""Baut die Weltkarte der Reichskarte (Web-Mercator wie bei Kartenkacheln):  python karte_welt.py <ne-ordner> <nuts_01m.geojson>

Quellen: Eurostat/GISCO NUTS 2021 (1:1 Mio.) für die 1352 Gebiete, Natural Earth (gemeinfrei) für Länder, Seen, Flüsse, Orte, Meere.
Schreibt karte_daten/geo.json (grob: sofort geladen) und karte_daten/geo_fein.json (fein: wird erst beim Hineinzoomen geladen).
Die Gebiets-IDs, Namen und Flächen stammen aus karte_daten/rekonstruktion/gebiete_meta.json. Benötigt numpy, shapely, pyshp.
Koordinaten: x/y in Kartenpixeln, Welt = 40000 × 40000 (1 Einheit ≈ 1 km am Äquator), Ursprung links oben bei 180°W / ~85°N.
"""
import glob, json, math, os, sys, time
import numpy as np
import shapefile
import shapely
from shapely.geometry import shape, box, MultiLineString, LineString, Polygon, MultiPolygon, mapping
from shapely.ops import unary_union, linemerge
from shapely.strtree import STRtree

NE, NUTS = sys.argv[1:3]
HIER = os.path.dirname(os.path.abspath(__file__))
ZIEL = os.path.join(HIER, "..", "karte_daten")
W = 40000
LAT_N, LAT_S = 82.0, -58.0
FENSTER = box(-32, 22, 80, 74)          # Ausschnitt, in dem die feine Ebene Länder/Flüsse/Provinzen enthält
t0 = time.time()


def log(*a):
    print(f"[{time.time() - t0:5.1f}s]", *a, flush=True)


def merc(c):
    c = np.asarray(c, float)
    lon, lat = c[:, 0], np.clip(c[:, 1], -85, 85)
    return np.column_stack([(lon + 180) / 360 * W, (0.5 - np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) / (2 * np.pi)) * W])


def proj(g):
    return shapely.transform(g, merc)


def mxy(lon, lat):
    p = merc([[lon, lat]])[0]
    return round(float(p[0]), 1), round(float(p[1]), 1)


def fmt(v, nd=1):
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def pfad_poly(g, mind=0.02, nd=1):
    teile = []
    for p in ([g] if g.geom_type == "Polygon" else [x for x in getattr(g, "geoms", []) if x.geom_type == "Polygon"]):
        if p.area < mind:
            continue
        for ring in [p.exterior] + list(p.interiors):
            c = np.asarray(ring.coords)[:-1]
            if len(c) >= 3:
                teile.append("M" + "L".join(f"{fmt(x, nd)} {fmt(y, nd)}" for x, y in c) + "Z")
    return "".join(teile)


def linien(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    out = []
    for x in getattr(g, "geoms", []):
        out += linien(x)
    return out


def pfad_lin(g, nd=1, minl=0.4):
    teile = []
    for l in linien(g):
        if l.length < minl:
            continue
        teile.append("M" + "L".join(f"{fmt(x, nd)} {fmt(y, nd)}" for x, y in np.asarray(l.coords)))
    return "".join(teile)


def lesen(name):
    sf = shapefile.Reader(glob.glob(os.path.join(NE, name, "*.shp"))[0], encoding="utf-8")
    felder = [f[0] for f in sf.fields[1:]]
    for sr in sf.iterShapeRecords():
        yield dict(zip(felder, sr.record)), shape(sr.shape.__geo_interface__)


WELT = box(-180, LAT_S, 180, LAT_N)


def begrenzen(g):
    return g.intersection(WELT) if not g.is_empty else g


# ---------------------------------------------------------------- Gebiete
meta = json.load(open(os.path.join(ZIEL, "rekonstruktion", "gebiete_meta.json")))
gebiete_meta, laender = meta["gebiete"], meta["laender"]
ids, roh = [], []
for f in json.load(open(NUTS))["features"]:
    i = f["properties"]["NUTS_ID"]
    if i in gebiete_meta:
        ids.append(i); roh.append(proj(shape(f["geometry"])))
roh = np.array(roh, dtype=object)
log(len(ids), "Gebiete, Koordinatenprüfung:", int(np.sum(~shapely.coverage_is_valid(roh))), "ungültig")
L0 = shapely.coverage_simplify(roh, 3.0)
L1 = shapely.coverage_simplify(roh, 0.35)
log("vereinfacht")


def kanten_von(geoms, tol):
    baum = STRtree(geoms)
    out = []
    for n, a in enumerate(geoms):
        for j in baum.query(a.buffer(tol)):
            if j <= n:
                continue
            gem = a.boundary.intersection(geoms[j].boundary)
            if gem.is_empty:
                continue
            lin = [l for l in linien(gem) if l.length > 0]
            if not lin:
                continue
            d = pfad_lin(linemerge(lin) if len(lin) > 1 else lin[0], minl=0.2)
            if d:
                out.append([ids[n], ids[j], d])
    return out


kanten0, kanten1 = kanten_von(list(L0), 0.3), kanten_von(list(L1), 0.3)
log(len(kanten0), len(kanten1), "Kanten")
mitte = {}
for i, g in zip(ids, L0):
    rp = g.centroid if g.contains(g.centroid) else g.representative_point()
    mitte[i] = [round(rp.x), round(rp.y), round(g.area)]
gebiete0 = {i: {"d": pfad_poly(g), "n": gebiete_meta[i]["n"], "c": gebiete_meta[i]["c"], "a": gebiete_meta[i]["a"]} for i, g in zip(ids, L0)}
gebiete1 = {i: pfad_poly(g, 0.01) for i, g in zip(ids, L1)}
nuts_union0 = unary_union(list(L0))
nuts_union1 = unary_union(list(L1))
nuts_codes = {gebiete_meta[i]["c"] for i in ids}
UMSCHREIBUNG = {"UK": "GB", "EL": "GR"}
nuts_iso = {UMSCHREIBUNG.get(c, c) for c in nuts_codes}
log("Gebiete fertig")

# ---------------------------------------------------------------- Länder (Natural Earth)
def land_ebene(name, tol, fenster=None):
    ohne_nuts, mit_nuts, namen = [], [], []
    for r, g in lesen(name):
        iso = r["ISO_A2_EH"] if r["ISO_A2_EH"] not in ("-99", "") else r["ISO_A2"]
        if r["ADMIN"] == "Antarctica":
            continue
        gg = begrenzen(g)
        if fenster is not None:
            gg = gg.intersection(fenster)
        if gg.is_empty:
            continue
        p = proj(gg).simplify(tol, preserve_topology=True)
        (mit_nuts if iso in nuts_iso else ohne_nuts).append((iso, r, p))
    return ohne_nuts, mit_nuts


def land_pfade(ohne, mit, nuts_union, tol_puffer, nd=1):
    teile = [p for _i, _r, p in ohne]
    if mit:
        rest = unary_union([p for _i, _r, p in mit]).difference(nuts_union.buffer(tol_puffer))
        teile += [x for x in (rest.geoms if hasattr(rest, "geoms") else [rest]) if x.area > 40]
    return [pfad_poly(g, 0.5, nd) for g in teile if not g.is_empty]


def grenzen_aus(ohne, nuts_union, puffer):
    """Ländergrenzen zwischen Ländern ohne Gebiete + zum Rand der Gebiete; Küste nicht."""
    polys = [p for _i, _r, p in ohne]
    baum = STRtree(polys)
    teile = []
    for n, a in enumerate(polys):
        for j in baum.query(a):
            if j <= n:
                continue
            gem = a.boundary.intersection(polys[j].boundary)
            if not gem.is_empty:
                teile.append(gem)
    land_ohne = unary_union(polys).buffer(puffer)
    teile.append(nuts_union.boundary.intersection(land_ohne))
    return unary_union(teile)


ohne0, mit0 = land_ebene("ne_50m_admin_0_countries", 2.0)
land0 = land_pfade(ohne0, mit0, nuts_union0, 6)
grenzen0 = pfad_lin(grenzen_aus(ohne0, nuts_union0, 2.5))
log("Land grob", len(land0))
ohne1, mit1 = land_ebene("ne_10m_admin_0_countries", 0.4, FENSTER)
land1 = land_pfade(ohne1, mit1, nuts_union1, 3)
grenzen1 = pfad_lin(grenzen_aus(ohne1, nuts_union1, 1.5))
log("Land fein", len(land1))

# Provinzen (Ebene 1) der Länder ohne Gebiete, nur im Fenster
prov = []
for r, g in lesen("ne_10m_admin_1_states_provinces"):
    iso = r["iso_a2"] if r["iso_a2"] not in ("-99", "") else ""
    if iso in nuts_iso or not g.intersects(FENSTER):
        continue
    gg = g.intersection(FENSTER)
    if not gg.is_empty:
        prov.append(proj(gg).simplify(0.5, preserve_topology=True))
land_fein_union = unary_union([p for _i, _r, p in ohne1]).buffer(1.5)
prov_lin = unary_union([p.boundary for p in prov]).difference(unary_union([p.boundary for _i, _r, p in ohne1]).buffer(1.2))
provinzen = pfad_lin(prov_lin, minl=0.6)
log("Provinzen")

# ---------------------------------------------------------------- Seen und Flüsse
def seen(rang_max, tol):
    out = []
    for name in ("ne_10m_lakes", "ne_10m_lakes_europe"):
        for r, g in lesen(name):
            if r["scalerank"] > rang_max:
                continue
            p = proj(begrenzen(g)).simplify(tol, preserve_topology=True)
            if not p.is_empty:
                out.append(pfad_poly(p, 2.0 if rang_max > 2 else 0.1))
    return [x for x in out if x]


seen0, seen1 = seen(2, 2.0), seen(9, 0.4)


def fluesse(tol, auswahl):
    out = {}
    for name in ("ne_10m_rivers_lake_centerlines", "ne_10m_rivers_europe"):
        for r, g in lesen(name):
            rang = int(r["scalerank"])
            if not auswahl(rang, name):
                continue
            if name.endswith("europe") and not g.intersects(FENSTER):
                continue
            g = proj(begrenzen(g)).simplify(tol, preserve_topology=True)
            d = pfad_lin(g, minl=0.6)
            if d:
                klasse = 1 if rang <= 4 else 2 if rang <= 6 else 3 if rang <= 9 else 4
                out.setdefault(klasse, []).append(d)
    return {k: "".join(v) for k, v in out.items()}


fluesse0 = fluesse(2.0, lambda rang, n: rang <= 5 and "europe" not in n)
fluesse1 = fluesse(0.4, lambda rang, n: not (rang <= 5 and "europe" not in n))
flussnamen = []
for r, g in lesen("ne_10m_rivers_lake_centerlines"):
    n = r["name_de"] or r["name"]
    if not n or int(r["scalerank"]) > 7 or r["featurecla"] != "River":
        continue
    p = proj(begrenzen(g))
    ls = max(linien(p), key=lambda l: l.length, default=None) if not p.is_empty else None
    if ls is None or ls.length < 60:
        continue
    a, b = ls.interpolate(0.5, normalized=True), ls.interpolate(0.46, normalized=True)
    c = ls.interpolate(0.54, normalized=True)
    w = math.degrees(math.atan2(c.y - b.y, c.x - b.x))
    w = w - 180 if w > 90 else w + 180 if w < -90 else w
    flussnamen.append([n, round(a.x, 1), round(a.y, 1), round(w), round(max(4.0, float(r["min_label"] or r["min_zoom"] or 5)), 1)])
log("Flüsse", len(flussnamen), "Namen")

# ---------------------------------------------------------------- Beschriftungen
manuell = json.load(open(os.path.join(HIER, "karte_orte.json"), encoding="utf-8"))
MANUELL_ZOOM = {1: 4.2, 2: 5.4, 3: 6.6}
orte_m = [[n, *mxy(lo, la), MANUELL_ZOOM[r], 1 if r == 1 else 2 if r == 2 else 3] for n, la, lo, r in manuell["orte"]]
orte_ne = []
for r, g in lesen("ne_10m_populated_places"):
    mz = float(r["MIN_ZOOM"] or 9)
    if mz > 8.5:
        continue
    kap = 1 if r["ADM0CAP"] == 1 else 2 if (r["POP_MAX"] or 0) >= 1_000_000 else 3
    x, y = mxy(r["LONGITUDE"], r["LATITUDE"])
    if r["LATITUDE"] < LAT_S or r["LATITUDE"] > LAT_N:
        continue
    orte_ne.append([r["NAME_DE"] or r["NAME"], x, y, round(mz, 1), kap])
pm = np.array([[o[1], o[2]] for o in orte_m])
orte_ne = [o for o in orte_ne if np.min(np.hypot(pm[:, 0] - o[1], pm[:, 1] - o[2])) > 14]
orte_alle = orte_m + orte_ne
orte0 = [o for o in orte_alle if o[3] <= 5.6]
orte1 = [o for o in orte_alle if o[3] > 5.6]

meere = []
for r, g in lesen("ne_10m_geography_marine_polys"):
    if r["featurecla"] in ("reef",) or not (r["name_de"] or r["name"]):
        continue
    p = proj(begrenzen(g))
    if p.is_empty:
        continue
    rp = p.representative_point()
    meere.append([r["name_de"] or r["name"], round(rp.x, 1), round(rp.y, 1), 0, float(r["min_label"] or 3), float(r["max_label"] or 10)])
meere += [[n, *mxy(lo, la), rot, 4.2, 9.0] for n, la, lo, rot in manuell["meere_extra"]]
laender_namen = []
for r, g in lesen("ne_10m_admin_0_countries"):
    if r["ADMIN"] == "Antarctica" or not r["NAME_DE"]:
        continue
    x, y = mxy(r["LABEL_X"], r["LABEL_Y"])
    laender_namen.append([r["NAME_DE"], x, y, float(r["MIN_LABEL"]), float(r["MAX_LABEL"]), 1 if r["ISO_A2_EH"] in nuts_iso else 0])
netz = []
for lat in range(-50, 81, 10):
    x0, y = mxy(-180, lat); x1, _ = mxy(180, lat)
    netz.append(f"M{x0:g} {y:g}L{x1:g} {y:g}")
for lon in range(-180, 181, 10):
    x, y0 = mxy(lon, LAT_N); _, y1 = mxy(lon, LAT_S)
    netz.append(f"M{x:g} {y0:g}L{x:g} {y1:g}")
x_min, y_min = mxy(-180, LAT_N); x_max, y_max = mxy(180, LAT_S)

kern = {"breite": W, "hoehe": W, "welt": [x_min, y_min, x_max, y_max], "projektion": "Web-Mercator",
        "quelle": "© EuroGeographics für die Verwaltungsgrenzen (GISCO, NUTS 2021), Natural Earth (gemeinfrei)",
        "laender": laender, "gebiete": gebiete0, "mitte": mitte, "kanten": kanten0,
        "land": land0, "grenzen": grenzen0, "seen": seen0, "fluesse": fluesse0, "flussnamen": flussnamen,
        "orte": orte0, "meere": meere, "laender_namen": laender_namen, "netz": netz}
fein = {"gebiete": gebiete1, "kanten": kanten1, "land": land1, "grenzen": grenzen1, "provinzen": provinzen,
        "seen": seen1, "fluesse": fluesse1, "orte": orte1}
for name, d in (("geo.json", kern), ("geo_fein.json", fein)):
    p = os.path.join(ZIEL, name)
    json.dump(d, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
    log(name, round(os.path.getsize(p) / 1e6, 2), "MB")
