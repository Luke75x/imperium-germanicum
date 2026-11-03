"""Ergänzt geo.json / geo_fein.json um Verkehrswege und Bauwerke (nach karte_welt.py ausführen, idempotent):
    python karte_infra.py <ne-ordner> [<osm-ordner>]
<osm-ordner> enthält entweder Overpass-Kacheln (mw_*.json, rail_*.json) oder OpenFreeMap-Vektorkacheln (ofm/8_<x>_<y>.pbf, braucht mapbox-vector-tile)

- (strassen / bahn: Autobahnen und Bahnstrecken wurden am 04.11.2026 von der Karte entfernt, siehe main().)
  Quelle: OpenStreetMap (Overpass-Kacheln mit mw_*.json / rail_*.json) falls vorhanden, sonst Natural Earth (nur Straßen).
- bauwerke: Gebäude, die auf der Website genannt werden [[Name, x, y, Zeile 2, Rang]] (Koordinaten von Hand, siehe BAUWERKE).
"""
import glob, json, os, re, sys
import numpy as np
import shapefile
import shapely
from shapely.geometry import LineString, MultiLineString, box, shape
from shapely.ops import linemerge, unary_union

NE = sys.argv[1]
OSM = sys.argv[2] if len(sys.argv) > 2 else None
HIER = os.path.dirname(os.path.abspath(__file__))
ZIEL = os.path.join(HIER, "..", "karte_daten")
W, ZELLE = 40000, 1600
FENSTER = box(-14, 30, 40, 66)


def merc(c):
    c = np.asarray(c, float)
    lon, lat = c[:, 0], np.clip(c[:, 1], -85, 85)
    return np.column_stack([(lon + 180) / 360 * W, (0.5 - np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) / (2 * np.pi)) * W])


def xy(lon, lat):
    p = merc([[lon, lat]])[0]
    return round(float(p[0]), 1), round(float(p[1]), 1)


def pfade(linien, nd=1):
    teile = []
    for l in linien:
        if l.is_empty or l.length < 0.5:
            continue
        c = np.round(np.asarray(l.coords), nd)
        teile.append("M" + "L".join(f"{x:g} {y:g}" for x, y in c))
    return teile


def bloecke(teile):
    gr = {}
    for d in teile:
        z = np.array([float(v) for v in re.findall(r"-?\d+\.?\d*", d)])
        x0, x1, y0, y1 = z[0::2].min(), z[0::2].max(), z[1::2].min(), z[1::2].max()
        g = gr.setdefault((int((x0 + x1) / 2 // ZELLE), int((y0 + y1) / 2 // ZELLE)), [x0, y0, x1, y1, []])
        g[0], g[1], g[2], g[3] = min(g[0], x0), min(g[1], y0), max(g[2], x1), max(g[3], y1)
        g[4].append(d)
    return [[int(g[0]), int(g[1]), int(g[2]) + 1, int(g[3]) + 1, "".join(g[4])] for g in gr.values()]


def verbinden(linien):
    """Kachelstücke zu langen Linienzügen verbinden (weniger Teilpfade, bessere Vereinfachung)."""
    if not linien:
        return []
    m = linemerge(MultiLineString([l for l in linien if l.geom_type == 'LineString']))
    return [m] if m.geom_type == "LineString" else list(m.geoms)


def ausduennen(linien, tol, raster=1.0, minl=0):
    """Vereinfachen und doppelte Fahrbahnen (Hin-/Rückrichtung) zusammenfallen lassen."""
    gesehen, out = set(), []
    for l in linien:
        s = l.simplify(tol, preserve_topology=False)
        if s.is_empty or s.length < max(tol, minl):
            continue
        c = np.asarray(s.coords)
        mid = s.interpolate(0.5, normalized=True)
        schluessel = (round(mid.x / (raster * 3)), round(mid.y / (raster * 3)), round(s.length / (raster * 6)))
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        out.append(s)
    return out


def osm_linien(praefix):
    out = []
    for f in sorted(glob.glob(os.path.join(OSM, praefix + "_*.json"))):
        for e in json.load(open(f)).get("elements", []):
            g = e.get("geometry")
            if e.get("type") == "way" and g and len(g) > 1:
                out.append(LineString(merc([[p["lon"], p["lat"]] for p in g])))
    return out


def ofm_linien(ordner):
    """Autobahnen und Bahnstrecken aus OpenFreeMap-Vektorkacheln (Stufe 8; OpenStreetMap-Daten)."""
    import mapbox_vector_tile
    mw, bahn = [], []
    for f in sorted(glob.glob(os.path.join(ordner, "ofm", "8_*.pbf"))):
        b = open(f, "rb").read()
        if not b:
            continue
        _z, tx, ty = os.path.basename(f)[:-4].split("_")
        tx, ty = int(tx), int(ty)
        t = mapbox_vector_tile.decode(b, default_options={"y_coord_down": True}).get("transportation")
        if not t:
            continue
        ext = t.get("extent", 4096)
        for ft in t["features"]:
            k = ft["properties"].get("class")
            ziel = mw if k == "motorway" else bahn if k == "rail" and ft["properties"].get("subclass") == "rail" else None
            if ziel is None:
                continue
            g = ft["geometry"]
            teile = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
            for l in teile:
                if len(l) > 1:
                    ziel.append(LineString([(round((tx + px / ext) / 256 * W, 2), round((ty + py / ext) / 256 * W, 2)) for px, py in l]))
    return mw, bahn


def ne_strassen():
    sf = shapefile.Reader(os.path.join(NE, "ne_roads", "ne_10m_roads.shp"), encoding="utf-8")
    out = []
    for r in sf.iterShapeRecords():
        if r.record["type"] != "Major Highway":
            continue
        g = shape(r.shape.__geo_interface__).intersection(FENSTER)
        if g.is_empty:
            continue
        for l in ([g] if g.geom_type == "LineString" else list(g.geoms)):
            out.append(LineString(merc(np.asarray(l.coords))))
    return out


BAUWERKE = [
    # Name, Zeile 2, Länge, Breite
    ("Reichstagsgebäude", "Sitz des Reichstags", 13.3763, 52.5186),
    ("Herrenhausgebäude", "Sitz des Senats", 13.3809, 52.5101),
    ("Kammergerichtsgebäude", "Sitz des Reichsgerichtshofs", 13.3537, 52.4896),
    ("Bendlerblock", "Sitz des Oberkommandos und der Stabschefs", 13.3657, 52.5070),
    ("Hauptquartier des KRS", "Sitz des Reichssicherheitsamts", 13.3745, 52.5329),
    ("Berliner Schloss", "Arbeitssitz des Souveräns und der Hand des Kaisers", 13.4010, 52.5175),
    ("Schloss Charlottenburg", "Private Residenz des Souveräns", 13.2959, 52.5207),
    ("Schloss Mannheim", "Besuch der Delegation", 8.4619, 49.4833),
    ("Jesuitenkirche Mannheim", "Besuch der Delegation", 8.4627, 49.4877),
]


def main():
    kern = json.load(open(os.path.join(ZIEL, "geo.json")))
    fein = json.load(open(os.path.join(ZIEL, "geo_fein.json")))
    bahn = []
    if OSM and glob.glob(os.path.join(OSM, "ofm", "8_*.pbf")):
        mw, bahn = ofm_linien(OSM)
        quelle = "OpenStreetMap-Mitwirkende (ODbL)"
    elif OSM and glob.glob(os.path.join(OSM, "mw_*.json")):
        mw = osm_linien("mw")
        quelle = "OpenStreetMap-Mitwirkende (ODbL)"
    else:
        mw = ne_strassen()
        quelle = "Natural Earth"
    if not bahn and OSM and glob.glob(os.path.join(OSM, "rail_*.json")):
        bahn = osm_linien("rail")
    mw, bahn = verbinden(mw), verbinden(bahn)
    print(len(mw), "Straßenzüge,", len(bahn), "Bahnzüge, Quelle:", quelle)
    # Straßen und Bahnstrecken sind seit 04.11.2026 von der Karte entfernt (Wunsch des Nutzers): hier werden nur noch die Bauwerke geschrieben
    for d in (kern, fein):
        d.pop("strassen", None)
        d.pop("bahn", None)
    kern["bauwerke"] = [[n, *xy(lo, la), z, 1] for n, z, lo, la in BAUWERKE]
    kern["quelle_infra"] = quelle
    for name, d in (("geo.json", kern), ("geo_fein.json", fein)):
        p = os.path.join(ZIEL, name)
        json.dump(d, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
        print(name, round(os.path.getsize(p) / 1e6, 2), "MB")


main()
