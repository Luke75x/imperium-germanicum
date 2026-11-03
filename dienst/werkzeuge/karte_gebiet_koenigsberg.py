"""Ergänzt das Kaliningrader Gebiet („Königsberg“, Russland) als eigenes Gebiet RU001 der Reichskarte:  python karte_gebiet_koenigsberg.py

Hintergrund: Die NUTS-Daten (Eurostat) enthalten keine Gebiete außerhalb der EU, deshalb war Königsberg nur ein grauer Teil der Landebene
und ließ sich weder einem Teilstaat zuweisen noch anklicken. Das Skript nimmt den Landring der Exklave aus karte_daten/geo.json und
geo_fein.json, füllt die schmalen Lücken zu den Nachbargebieten (Polen, Litauen), schneidet die Nachbarn heraus und schreibt:
  geo.json / geo_fein.json:  gebiete (RU001), mitte, kanten (gemeinsame Grenzen zu den Nachbargebieten), laender (RU)
  bevoelkerung.json:         Einwohner (Volkszählung 2021: 1 029 966; nicht von Eurostat)
Die Zuordnung zu einem Teilstaat und der Name „Königsberg“ stehen im Stand der Karte (karte_versionen), nicht hier.
Läuft nur einmal (bricht ab, wenn RU001 schon existiert). Benötigt shapely (nicht im venv des Dienstes; z. B. eigenes venv: pip install shapely numpy).
Sicherungen der alten Dateien: *.vor-koenigsberg im Ordner karte_daten.
"""
import json
import os
import re
import shutil
import sys

from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union, linemerge

HIER = os.path.dirname(os.path.abspath(__file__))
DATEN = os.path.join(HIER, "..", "karte_daten")
GID, NAME, LAND, FLAECHE, EINWOHNER, JAHR = "RU001", "Kaliningrad", "RU", 15125, 1029966, 2021
FENSTER = box(22100, 12550, 22560, 12800)    # Umgebung der Exklave (Weltkoordinaten)
KERN = (22178, 12596, 22538, 12778)          # Rahmen des Landrings der Exklave
LUECKE = 14                                  # Lücken bis zu dieser Breite zu den Nachbargebieten werden geschlossen


def ringe(d):
    for t in re.findall(r"M([^Z]+)Z", d):
        z = [float(x) for x in re.split(r"[ L]+", t.strip())]
        yield list(zip(z[0::2], z[1::2]))


def fmt(v):
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def pfad(g, mind=0.5):
    teile = []
    for p in ([g] if g.geom_type == "Polygon" else list(g.geoms)):
        if p.geom_type != "Polygon" or p.area < mind:
            continue
        for ring in [p.exterior] + list(p.interiors):
            c = list(ring.coords)[:-1]
            teile.append("M" + "L".join(f"{fmt(x)} {fmt(y)}" for x, y in c) + "Z")
    return "".join(teile)


def linien(g):
    return [x for x in ([g] if g.geom_type == "LineString" else list(getattr(g, "geoms", []))) if x.geom_type == "LineString" and x.length > 0]


def pfad_lin(g):
    return "".join("M" + "L".join(f"{fmt(x)} {fmt(y)}" for x, y in l.coords) for l in linien(g))


def landring(geo):
    """Der Landring der Exklave (größter Ring im Kernrahmen)."""
    best = None
    for ch in geo["land"]:
        if ch[2] < KERN[0] or ch[0] > KERN[2] or ch[3] < KERN[1] or ch[1] > KERN[3]:
            continue
        for r in ringe(ch[4]):
            p = Polygon(r) if len(r) > 2 else None
            if p is not None and p.bounds[0] >= KERN[0] - 3 and p.bounds[2] <= KERN[2] + 3 and p.bounds[1] >= KERN[1] - 3 and p.bounds[3] <= KERN[3] + 3:
                if best is None or p.area > best.area:
                    best = p
    if best is None:
        sys.exit("Landring der Exklave nicht gefunden.")
    return best.buffer(0)


def main():
    gpfad, fpfad, bpfad = (os.path.join(DATEN, n) for n in ("geo.json", "geo_fein.json", "bevoelkerung.json"))
    geo, fein, bev = (json.load(open(p, encoding="utf-8")) for p in (gpfad, fpfad, bpfad))
    if GID in geo["gebiete"]:
        sys.exit(f"{GID} existiert schon.")
    for p in (gpfad, fpfad, bpfad):
        shutil.copy(p, p + ".vor-koenigsberg")

    ergebnis = {}
    for name, ebene in (("grob", geo), ("fein", fein)):
        ring = landring(geo if name == "grob" else fein)
        def nachbar_pfad(k):
            return geo["gebiete"][k]["d"] if name == "grob" else fein["gebiete"][k]
        nb = {}
        for k, v in geo["gebiete"].items():
            b = v["b"]
            if b[2] < FENSTER.bounds[0] or b[0] > FENSTER.bounds[2] or b[3] < FENSTER.bounds[1] or b[1] > FENSTER.bounds[3]:
                continue
            nb[k] = unary_union([Polygon(r).buffer(0) for r in ringe(nachbar_pfad(k)) if len(r) > 2])
        U = unary_union(list(nb.values()))
        luecke = ring.buffer(LUECKE).intersection(U.buffer(LUECKE)).difference(U)
        neu = unary_union([ring, luecke]).difference(U)
        teile = [p for p in ([neu] if neu.geom_type == "Polygon" else list(neu.geoms)) if p.geom_type == "Polygon"]
        neu = MultiPolygon([p for p in teile if p.area > 6]) if len([p for p in teile if p.area > 6]) > 1 else max(teile, key=lambda p: p.area)
        kanten = []
        for k, g in nb.items():
            gem = neu.boundary.intersection(g.boundary.buffer(0.05))
            if gem.is_empty:
                continue
            lin = linien(gem)
            if lin:
                d = pfad_lin(linemerge(lin) if len(lin) > 1 else lin[0])
                if d:
                    kanten.append([GID, k, d])
        ergebnis[name] = (neu, kanten)
        print(name, "Fläche", round(neu.area), "Kanten", [(k[1], len(k[2])) for k in kanten])

    grob_neu, grob_kanten = ergebnis["grob"]
    fein_neu, fein_kanten = ergebnis["fein"]
    rp = grob_neu.centroid if grob_neu.contains(grob_neu.centroid) else grob_neu.representative_point()
    geo["gebiete"][GID] = {"b": [round(v) for v in grob_neu.bounds], "d": pfad(grob_neu), "n": NAME, "c": LAND, "a": FLAECHE}
    geo["mitte"][GID] = [round(rp.x), round(rp.y), round(grob_neu.area)]
    geo["kanten"].extend(grob_kanten)
    geo["laender"].setdefault(LAND, "Russland")
    fein["gebiete"][GID] = pfad(fein_neu, 0.2)
    fein["kanten"].extend(fein_kanten)
    bev[GID] = [EINWOHNER, JAHR]
    for p, daten in ((gpfad, geo), (fpfad, fein), (bpfad, bev)):
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(daten, fh, ensure_ascii=False, separators=(",", ":"))
    print("geschrieben:", GID, "mitte", geo["mitte"][GID])


if __name__ == "__main__":
    main()
