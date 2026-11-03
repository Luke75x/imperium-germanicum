"""Ergänzt geo.json um Kartendetails (idempotent):  python karte_details.py

- kanten:  Grenzabschnitte zwischen benachbarten NUTS-3-Gebieten [[idA, idB, "Pfad"], …] (aus den Pfaden von geo.json,
           so passen sie zu den Flächen; die Seite zeichnet sie je nach Teilstaat als Staats- oder Kreisgrenze)
- mitte:   je Gebiet Schwerpunkt und Fläche in Kartenpixeln {id: [x, y, fläche]} (für Teilstaatsnamen)
- orte:    Städte [[Name, x, y, Rang]]; Rang 1 = Hauptstadt/Weltstadt … 3 = kleinere Stadt
- meere:   Gewässernamen [[Name, x, y, Drehung]]
- laender_namen: Landesnamen der Nachbarn [[Name, x, y]]
- netz:    Breiten-/Längenkreise als Pfade
Benötigt numpy, shapely.
"""
import json, os, re
import numpy as np
from shapely.geometry import Polygon, LineString, MultiLineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

HIER = os.path.dirname(os.path.abspath(__file__))
DATEI = os.path.join(HIER, "..", "karte_daten", "geo.json")
sx, sy, tx, ty = json.load(open(os.path.join(HIER, "..", "karte_daten", "rekonstruktion", "projektionen.json")))["laea"][1]
K = 3000 / 500


def laea(lon, lat, l0=10, p0=52):
    l, p = np.radians(np.asarray(lon, float) - l0), np.radians(np.asarray(lat, float)); p0 = np.radians(p0)
    q = np.sqrt(2 / (1 + np.sin(p0) * np.sin(p) + np.cos(p0) * np.cos(p) * np.cos(l)))
    return q * np.cos(p) * np.sin(l), q * (np.cos(p0) * np.sin(p) - np.sin(p0) * np.cos(p) * np.cos(l))


def xy(lat, lon):
    u, v = laea(lon, lat)
    return round(float((u * sx + tx) * K), 1), round(float((-v * sy + ty) * K), 1)


# Name, Breite, Länge, Rang
ORTE = [
    ("Berlin", 52.52, 13.40, 1), ("Wien", 48.21, 16.37, 1), ("Prag", 50.08, 14.43, 1), ("Bern", 46.95, 7.45, 1), ("Rom", 41.90, 12.50, 1),
    ("Paris", 48.86, 2.35, 1), ("London", 51.51, -0.13, 1), ("Warschau", 52.23, 21.01, 1), ("Budapest", 47.50, 19.04, 1),
    ("Brüssel", 50.85, 4.35, 1), ("Amsterdam", 52.37, 4.90, 1), ("Kopenhagen", 55.68, 12.57, 1), ("Madrid", 40.42, -3.70, 1),
    ("Ljubljana", 46.06, 14.51, 1), ("Zagreb", 45.81, 15.98, 1), ("Bratislava", 48.15, 17.11, 1), ("Vilnius", 54.69, 25.28, 1),
    ("Riga", 56.95, 24.11, 1), ("Belgrad", 44.79, 20.45, 1), ("Bukarest", 44.43, 26.10, 1), ("Athen", 37.98, 23.73, 1), ("Dublin", 53.35, -6.26, 1),
    ("Hamburg", 53.55, 9.99, 2), ("München", 48.14, 11.58, 2), ("Köln", 50.94, 6.96, 2), ("Frankfurt", 50.11, 8.68, 2), ("Stuttgart", 48.78, 9.18, 2),
    ("Dresden", 51.05, 13.74, 2), ("Hannover", 52.37, 9.73, 2), ("Nürnberg", 49.45, 11.08, 2), ("Leipzig", 51.34, 12.37, 2), ("Bremen", 53.08, 8.80, 2),
    ("Kiel", 54.32, 10.14, 2), ("Würzburg", 49.79, 9.95, 2), ("Mannheim", 49.49, 8.47, 2), ("Mainz", 50.00, 8.27, 2), ("Trier", 49.76, 6.64, 2),
    ("Aachen", 50.78, 6.08, 2), ("Königsberg", 54.71, 20.51, 2), ("Danzig", 54.35, 18.65, 2), ("Breslau", 51.11, 17.04, 2), ("Krakau", 50.06, 19.94, 2),
    ("Posen", 52.41, 16.93, 2), ("Stettin", 53.43, 14.55, 2), ("Brünn", 49.20, 16.61, 2), ("Salzburg", 47.80, 13.04, 2), ("Innsbruck", 47.27, 11.39, 2),
    ("Graz", 47.07, 15.44, 2), ("Zürich", 47.38, 8.54, 2), ("Genf", 46.20, 6.14, 2), ("Basel", 47.56, 7.59, 2), ("Mailand", 45.46, 9.19, 2),
    ("Venedig", 45.44, 12.32, 2), ("Turin", 45.07, 7.69, 2), ("Genua", 44.41, 8.93, 2), ("Bologna", 44.49, 11.34, 2), ("Florenz", 43.77, 11.26, 2),
    ("Neapel", 40.85, 14.27, 2), ("Palermo", 38.12, 13.36, 2), ("Bari", 41.12, 16.87, 2), ("Cagliari", 39.22, 9.12, 2), ("Triest", 45.65, 13.78, 2),
    ("Straßburg", 48.57, 7.75, 2), ("Lyon", 45.76, 4.84, 2), ("Marseille", 43.30, 5.37, 2), ("Lille", 50.63, 3.06, 2), ("Metz", 49.12, 6.18, 2),
    ("Luxemburg", 49.61, 6.13, 2), ("Rotterdam", 51.92, 4.48, 3), ("Antwerpen", 51.22, 4.40, 3), ("Gent", 51.05, 3.72, 3), ("Lüttich", 50.63, 5.57, 3),
    ("Münster", 51.96, 7.63, 3), ("Dortmund", 51.51, 7.47, 3), ("Düsseldorf", 51.23, 6.78, 3), ("Bonn", 50.74, 7.10, 3), ("Koblenz", 50.36, 7.59, 3),
    ("Kassel", 51.32, 9.50, 3), ("Göttingen", 51.54, 9.93, 3), ("Braunschweig", 52.27, 10.52, 3), ("Magdeburg", 52.13, 11.63, 3), ("Erfurt", 50.98, 11.03, 3),
    ("Rostock", 54.09, 12.10, 3), ("Lübeck", 53.87, 10.69, 3), ("Schwerin", 53.63, 11.41, 3), ("Flensburg", 54.78, 9.44, 3), ("Osnabrück", 52.28, 8.05, 3),
    ("Oldenburg", 53.14, 8.21, 3), ("Heidelberg", 49.40, 8.69, 3), ("Karlsruhe", 49.01, 8.40, 3), ("Freiburg", 47.99, 7.85, 3), ("Konstanz", 47.66, 9.18, 3),
    ("Ulm", 48.40, 9.99, 3), ("Augsburg", 48.37, 10.90, 3), ("Regensburg", 49.01, 12.10, 3), ("Passau", 48.57, 13.46, 3), ("Bamberg", 49.89, 10.89, 3),
    ("Bayreuth", 49.94, 11.58, 3), ("Linz", 48.31, 14.29, 3), ("Klagenfurt", 46.62, 14.31, 3), ("Bozen", 46.50, 11.35, 3), ("Trient", 46.07, 11.12, 3),
    ("Verona", 45.44, 10.99, 3), ("Padua", 45.41, 11.88, 3), ("Pilsen", 49.75, 13.38, 3), ("Ostrau", 49.84, 18.29, 3), ("Olmütz", 49.59, 17.25, 3),
    ("Görlitz", 51.15, 14.99, 3), ("Cottbus", 51.76, 14.33, 3), ("Chemnitz", 50.83, 12.92, 3), ("Lodz", 51.76, 19.46, 3), ("Thorn", 53.01, 18.60, 3),
    ("Luzern", 47.05, 8.31, 3), ("Lausanne", 46.52, 6.63, 3), ("St. Gallen", 47.42, 9.37, 3), ("Lugano", 46.00, 8.95, 3), ("Aosta", 45.74, 7.32, 3),
    ("Ravenna", 44.42, 12.20, 3), ("Ancona", 43.62, 13.52, 3), ("Pescara", 42.46, 14.21, 3), ("Foggia", 41.46, 15.54, 3), ("Tarent", 40.47, 17.24, 3),
    ("Reggio", 38.11, 15.65, 3), ("Catania", 37.50, 15.09, 3), ("Sassari", 40.73, 8.56, 3), ("Ajaccio", 41.93, 8.74, 3), ("Nancy", 48.69, 6.18, 3),
    ("Dijon", 47.32, 5.04, 3), ("Reims", 49.26, 4.03, 3), ("Nantes", 47.22, -1.55, 3), ("Bordeaux", 44.84, -0.58, 3), ("Toulouse", 43.60, 1.44, 3),
    ("Rijeka", 45.33, 14.44, 3), ("Split", 43.51, 16.44, 3), ("Maribor", 46.55, 15.65, 3), ("Debrecen", 47.53, 21.63, 3), ("Kaschau", 48.72, 21.26, 3),
    ("Malmö", 55.60, 13.00, 3), ("Aarhus", 56.16, 10.20, 3), ("Odense", 55.40, 10.39, 3), ("Birmingham", 52.49, -1.89, 3), ("Manchester", 53.48, -2.24, 3),
]
MEERE = [("Nordsee", 55.0, 3.5, 0), ("Ostsee", 55.2, 17.0, 0), ("Atlantischer Ozean", 46.0, -6.5, -25), ("Mittelmeer", 39.3, 4.0, 0),
         ("Tyrrhenisches Meer", 40.0, 12.0, -50), ("Ligurisches Meer", 43.6, 8.7, -20), ("Adriatisches Meer", 43.1, 15.8, 35),
         ("Ionisches Meer", 38.0, 18.8, 0), ("Ärmelkanal", 50.1, -2.0, -8), ("Golf von Biskaya", 45.2, -4.0, 40), ("Schwarzes Meer", 43.5, 31.5, 0),
         ("Ägäis", 38.8, 25.0, 0), ("Irische See", 53.7, -4.6, 80)]
LAENDER_NAMEN = [("Frankreich", 47.3, 2.5), ("Spanien", 40.0, -3.5), ("Vereinigtes Königreich", 53.0, -1.6), ("Irland", 53.2, -8.0),
                 ("Polen", 52.2, 19.5), ("Ungarn", 47.1, 19.3), ("Rumänien", 45.8, 25.0), ("Serbien", 44.0, 20.8), ("Kroatien", 45.3, 16.3),
                 ("Dänemark", 55.9, 9.5), ("Schweden", 57.5, 14.5), ("Litauen", 55.3, 23.9), ("Lettland", 56.8, 24.9), ("Weißrussland", 53.5, 28.0),
                 ("Ukraine", 49.5, 31.0), ("Russland", 56.5, 38.0), ("Griechenland", 39.5, 22.0), ("Bulgarien", 42.8, 25.3), ("Bosnien", 44.1, 17.8),
                 ("Nordmazedonien", 41.6, 21.7), ("Albanien", 41.1, 20.0), ("Slowakei", 48.7, 19.5), ("Portugal", 39.6, -8.0), ("Tunesien", 34.0, 9.5),
                 ("Algerien", 35.0, 3.0), ("Norwegen", 61.0, 9.0), ("Türkei", 39.5, 33.0), ("Moldau", 47.2, 28.5), ("Kosovo", 42.6, 20.9)]


def ringe(d):
    for teil in re.findall(r"M([^Z]+)Z", d):
        z = [float(v) for v in re.split(r"[ L]+", teil.strip())]
        yield list(zip(z[0::2], z[1::2]))


def poly(d):
    rs = [Polygon(r) for r in ringe(d) if len(r) >= 3]
    rs = [r if r.is_valid else r.buffer(0) for r in rs]
    # Löcher (even-odd) berücksichtigen: symmetrische Differenz aller Ringe
    g = rs[0] if rs else Polygon()
    for r in rs[1:]:
        g = g.symmetric_difference(r)
    return g


def pfad_linien(g):
    teile = []
    for l in ([g] if g.geom_type == "LineString" else getattr(g, "geoms", [])):
        if l.geom_type != "LineString" or l.length < 0.3:
            continue
        c = np.round(np.asarray(l.coords), 1)
        teile.append("M" + "L".join(f"{x:g} {y:g}" for x, y in c))
    return "".join(teile)


def main():
    geo = json.load(open(DATEI))
    ids = sorted(geo["gebiete"])
    polys = {i: poly(geo["gebiete"][i]["d"]) for i in ids}
    baum = STRtree([polys[i] for i in ids])
    kanten, mitte = [], {}
    for n, a in enumerate(ids):
        pa = polys[a]
        if pa.is_empty:
            continue
        rp = pa.representative_point() if pa.centroid.is_empty or not pa.contains(pa.centroid) else pa.centroid
        mitte[a] = [round(rp.x), round(rp.y), round(pa.area)]
        grenze = pa.boundary
        for j in baum.query(pa.buffer(1.0)):
            b = ids[j]
            if b <= a or polys[b].is_empty:
                continue
            gem = grenze.intersection(polys[b].buffer(0.8))
            if gem.is_empty:
                continue
            gem = unary_union(gem) if gem.geom_type != "LineString" else gem
            d = pfad_linien(gem)
            if d:
                kanten.append([a, b, d])
    netz = []
    for lat in range(30, 71, 5):
        pts = [xy(lat, lo) for lo in range(-25, 61, 2)]
        netz.append("M" + "L".join(f"{x:g} {y:g}" for x, y in pts))
    for lon in range(-20, 51, 5):
        pts = [xy(la, lon) for la in range(30, 72, 2)]
        netz.append("M" + "L".join(f"{x:g} {y:g}" for x, y in pts))
    geo.update(kanten=kanten, mitte=mitte, netz=netz,
               orte=[[n, *xy(la, lo), r] for n, la, lo, r in ORTE],
               meere=[[n, *xy(la, lo), rot] for n, la, lo, rot in MEERE],
               laender_namen=[[n, *xy(la, lo)] for n, la, lo in LAENDER_NAMEN])
    json.dump(geo, open(DATEI, "w"), ensure_ascii=False, separators=(",", ":"))
    print(len(kanten), "Grenzabschnitte,", len(mitte), "Mittelpunkte,", round(os.path.getsize(DATEI) / 1e6, 2), "MB")


main()
