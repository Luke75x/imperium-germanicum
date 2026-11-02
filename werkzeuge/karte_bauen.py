"""Baut die Kartendaten der Reichskarte aus Eurostat-Daten (einmalig bzw. bei neuer NUTS-Fassung).

    python karte_bauen.py <rohordner> <ausrichtung.json> <zuordnung.json>

<rohordner>: NUTS_RG_10M_2021_4326_LEVL_3.geojson, CNTR_RG_10M_2020_4326.geojson (GISCO),
             bev.json (Eurostat demo_r_pjanaggr3), flaeche.json (Eurostat reg_area3).
<ausrichtung.json>: Parameter der Lambert-flächentreuen Azimutalprojektion (10° O, 52° N), angepasst an die alte
             MapChart-Karte (i74e21fe796eaa5e0.jpg, 3000 × 2325 px), damit Karte und Bild denselben Ausschnitt haben.
<zuordnung.json>: NUTS-ID → Teilstaat-Kürzel, aus den Farben der alten Karte gewonnen (Neuaufbau 02.11.2026).
Schreibt karte_daten/geo.json, karte_daten/bevoelkerung.json und karte_daten/startstand.json.
"""
import json, os, sys
import numpy as np
from shapely.geometry import shape, box, mapping
from shapely.ops import transform

ROH, AUSR, ZUORD = sys.argv[1:4]
ZIEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "karte_daten")
BREITE, HOEHE = 3000, 2325
R_ERDE = 6371.0088
sx, sy, tx, ty = json.load(open(AUSR))["laea"][1]
K = BREITE / 500


def laea(lon, lat, l0=10, p0=52):
    l, p = np.radians(np.asarray(lon) - l0), np.radians(np.asarray(lat)); p0 = np.radians(p0)
    q = np.sqrt(2 / (1 + np.sin(p0) * np.sin(p) + np.cos(p0) * np.cos(p) * np.cos(l)))
    return q * np.cos(p) * np.sin(l), q * (np.cos(p0) * np.sin(p) - np.sin(p0) * np.cos(p) * np.cos(l))


def auf_karte(x, y, z=None):
    u, v = laea(x, y)
    return (u * sx + tx) * K, (-v * sy + ty) * K


RAND = box(-300, -300, BREITE + 300, HOEHE + 300)


def pfad(g):
    """Geometrie (Kartenkoordinaten) → SVG-Pfad, 0,1 px genau."""
    teile = []
    polys = [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))
    for p in polys:
        if p.geom_type != "Polygon" or p.area < 0.05:
            continue
        for ring in [p.exterior] + list(p.interiors):
            c = np.round(np.asarray(ring.coords)[:-1], 1)
            if len(c) < 3:
                continue
            s = "M" + "L".join(f"{x:g} {y:g}" for x, y in c) + "Z"
            teile.append(s)
    return "".join(teile)


LAENDER = {"AT": "Österreich", "BE": "Belgien", "BG": "Bulgarien", "CH": "Schweiz", "CY": "Zypern", "CZ": "Tschechien", "DE": "Deutschland",
           "DK": "Dänemark", "EE": "Estland", "EL": "Griechenland", "ES": "Spanien", "FI": "Finnland", "FR": "Frankreich", "HR": "Kroatien",
           "HU": "Ungarn", "IE": "Irland", "IS": "Island", "IT": "Italien", "LI": "Liechtenstein", "LT": "Litauen", "LU": "Luxemburg",
           "LV": "Lettland", "ME": "Montenegro", "MK": "Nordmazedonien", "MT": "Malta", "NL": "Niederlande", "NO": "Norwegen", "PL": "Polen",
           "PT": "Portugal", "RO": "Rumänien", "RS": "Serbien", "SE": "Schweden", "SI": "Slowenien", "SK": "Slowakei", "AL": "Albanien",
           "UK": "Vereinigtes Königreich", "TR": "Türkei"}

# Statistik (JSON-stat): letzter Wert je Gebiet
def jsonstat(datei):
    d = json.load(open(datei))
    dims = d["id"]; groesse = d["size"]
    geo_i = d["dimension"]["geo"]["category"]["index"]; zeit_i = d["dimension"]["time"]["category"]["index"]
    geo_pos, zeit_pos = dims.index("geo"), dims.index("time")
    schritt = [int(np.prod(groesse[i + 1:])) for i in range(len(groesse))]
    out = {}
    for g, gi in geo_i.items():
        for t, ti in sorted(zeit_i.items(), key=lambda x: x[1]):
            v = d["value"].get(str(gi * schritt[geo_pos] + ti * schritt[zeit_pos]))
            if v is not None:
                out[g] = (v, int(t[:4]))
    return out


bev = jsonstat(os.path.join(ROH, "bev.json"))
flaeche = jsonstat(os.path.join(ROH, "flaeche.json"))
zu = json.load(open(ZUORD))

nuts = json.load(open(os.path.join(ROH, "NUTS_RG_10M_2021_4326_LEVL_3.geojson")))
gebiete, abgedeckt = {}, []
for f in nuts["features"]:
    pr = f["properties"]; nid = pr["NUTS_ID"]
    if nid not in zu or pr["CNTR_CODE"] == "TR":
        continue
    roh = shape(f["geometry"]).buffer(0)
    g = transform(auf_karte, roh).buffer(0).intersection(RAND)
    if g.is_empty:
        continue
    g = g.simplify(0.35, preserve_topology=True)
    eq = transform(lambda x, y, z=None: laea(x, y), roh)       # flächentreu → km²
    a = flaeche.get(nid, (eq.area * R_ERDE ** 2, 0))[0]
    gebiete[nid] = {"d": pfad(g), "n": pr["NAME_LATN"], "c": pr["CNTR_CODE"], "a": round(a)}
    abgedeckt.append(roh)

# Hintergrund: Länder ohne NUTS-Gebiete in der Karte (Russland, Belarus, Ukraine, Balkan, Nordafrika …)
cn = json.load(open(os.path.join(ROH, "CNTR_RG_10M_2020_4326.geojson")))
nuts_laender = {g["c"] for g in gebiete.values()}
hintergrund = []
for f in cn["features"]:
    code = f["properties"]["CNTR_ID"]
    if code in nuts_laender or code == "EL" and "EL" in nuts_laender:
        continue
    g = transform(auf_karte, shape(f["geometry"]).buffer(0)).buffer(0).intersection(RAND)
    if not g.is_empty:
        hintergrund.append(pfad(g.simplify(0.6, preserve_topology=True)))

laender = {c: LAENDER.get(c, c) for c in sorted(nuts_laender)}
geo = {"breite": BREITE, "hoehe": HOEHE, "projektion": "LAEA 10°O 52°N, Ausschnitt der alten Karte", "quelle": "© EuroGeographics für die Verwaltungsgrenzen (GISCO, NUTS 2021)",
       "laender": laender, "hintergrund": [h for h in hintergrund if h], "gebiete": gebiete}
os.makedirs(ZIEL, exist_ok=True)
json.dump(geo, open(os.path.join(ZIEL, "geo.json"), "w"), ensure_ascii=False, separators=(",", ":"))
json.dump({k: [int(v[0]), v[1]] for k, v in bev.items() if k in gebiete}, open(os.path.join(ZIEL, "bevoelkerung.json"), "w"), separators=(",", ":"))

# Teilstaaten der alten Karte (Farben aus der Legende, Fraktionsrollen vom Discord-Server)
STAATEN = [("pfalz", "Erzherzogtum Pfalz", "#000000", "voll", "#ffffff", "1522932375376367647"),
           ("frei", "Freie Reichsgebiete", "#3c6ccc", "streifen", "#ffffff", ""),
           ("hanse", "Freier Hansebund", "#fccce4", "voll", "#ffffff", "1538552989952778352"),
           ("wuerzburg", "Fürstbistum Würzburg", "#cab2d6", "voll", "#ffffff", ""),
           ("franken", "Fürstentum Franken", "#baa087", "voll", "#ffffff", "1528925001644904529"),
           ("holstein", "Fürstentum Holstein", "#be3202", "voll", "#ffffff", "1526303193468895263"),
           ("venedig", "Generalgouvernement Venedig", "#72b28d", "voll", "#ffffff", ""),
           ("schwaben", "Großherzogtum Schwaben-Württemberg", "#ff7f00", "voll", "#ffffff", "1522932665076940880"),
           ("stuhl", "Heiliger Stuhl", "#4d014c", "voll", "#ffffff", "1522705410069631017"),
           ("tirol", "Herzogtum Tirol-Salzburg", "#b3de6a", "voll", "#ffffff", "1522933099954962583"),
           ("apulien", "Königreich Apulien", "#ffffff", "karo", "#cc3c3c", ""),
           ("boehmen", "Königreich Böhmen", "#f4a682", "voll", "#ffffff", ""),
           ("hannover", "Königreich Hannover", "#d6ac0c", "streifen", "#54543c", "1522933243349827585"),
           ("schweiz", "Königreich Schweiz", "#cc3433", "voll", "#ffffff", ""),
           ("lausitz", "Landgrafschaft Lausitz", "#fedbc7", "voll", "#ffffff", "1528926325677621339"),
           ("maehren", "Markgrafschaft Mähren", "#cb503e", "voll", "#ffffff", "1528925623869767902"),
           ("berlin", "Reichshauptstadt Groß-Berlin", "#9c3c0c", "punkte", "#0c0c0c", ""),
           ("longinus", "St. Longinus Orden", "#ffff33", "voll", "#ffffff", "1522932967473942588"),
           ("westerwald", "Westerwälder Union", "#01665e", "voll", "#ffffff", "1522932481639321651")]
kurz_zu_id = {k: f"s{i + 1}" for i, (k, *_r) in enumerate(STAATEN)}
stand = {"staaten": [{"id": kurz_zu_id[k], "name": n, "farbe": f, "muster": m, "farbe2": f2, "fraktion": fr} for k, n, f, m, f2, fr in STAATEN],
         "gebiete": {g: kurz_zu_id[s] for g, s in sorted(zu.items()) if s and g in gebiete}, "namen": {}}
json.dump(stand, open(os.path.join(ZIEL, "startstand.json"), "w"), ensure_ascii=False, indent=1)
print(len(gebiete), "Gebiete,", len(hintergrund), "Hintergrundflächen,", len(stand["gebiete"]), "zugeordnet,",
      round(os.path.getsize(os.path.join(ZIEL, "geo.json")) / 1e6, 2), "MB geo.json,", len([g for g in gebiete if g in bev]), "mit Einwohnerzahl")
