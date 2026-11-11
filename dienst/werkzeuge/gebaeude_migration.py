"""Gebäude der Reichskarte auf die Behördentypen umstellen und die Dienstgebäude der Reichsbehörden setzen (einmalig, idempotent):

    .venv/bin/python werkzeuge/gebaeude_migration.py [--ausfuehren]

1. Die bisherigen Bauwerke aus geo.json (Reichstag, Herrenhaus, Kammergericht, Bendlerblock, KRS, Schlösser …) werden als Gebäude der Karte (stand.gebaeude)
   mit dem passenden Typ übernommen (Zuordnung: _build/reichsbehoerden.py → BESTAND_TYPEN).
2. Die Dienstgebäude der Reichsbehörden (reichsbehoerden.json → gebaeude, Koordinaten Länge/Breite) kommen dazu.
Gebäude mit gleichem Namen werden nicht doppelt angelegt. Ohne --ausfuehren nur Vorschau. Speichert eine neue Kartenversion.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db  # noqa: E402
import karte  # noqa: E402


def merc(lon, lat):
    w = karte.GEO["breite"]
    return round((lon + 180) / 360 * w, 1), round((0.5 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi)) * w, 1)


def main():
    con = db.verbinden()
    stand = karte.aktuell(con)["stand"]
    d = karte.reichsbehoerden()
    typen = {t["id"] for t in karte.gebaeude_typen()}
    liste = list(stand.get("gebaeude") or [])
    namen = {g["name"] for g in liste}
    nr = max([int(g["id"][1:]) for g in liste] + [0])
    neu = []
    for name, x, y, text, _rang in karte.GEO.get("bauwerke", []):
        typ = d["bestand_typen"].get(name, "sonstiges")
        if name not in namen and typ in typen:
            neu.append({"typ": typ, "name": name, "text": text, "x": x, "y": y})
    # bereits von der RP-Leitung gesetzte Gebäude dem neuen Typ zuordnen (nicht doppelt anlegen)
    vorhanden = {g["typ"]: g for g in liste}
    for g in liste:
        if g["typ"] == "behoerde" and "Verkehr" in g["name"]:
            g["typ"] = "verkehr"
            g["text"] = g.get("text") or "Sitz des Reichsamts für Verkehr"
            print(f'  ~ {g["id"]} {g["name"]}: Typ verkehr')
    vorhanden = {g["typ"]: g for g in liste}
    for g in d["gebaeude"]:   # das Kanzleramt heißt auf der Karte wie auf der Website
        b = vorhanden.get(g["typ"])
        if b and g["typ"] == "kanzlei" and b["name"] != g["name"]:
            print(f'  ~ {b["id"]} {b["name"]} → {g["name"]}')
            b["name"], b["text"] = g["name"], g.get("text", b.get("text", ""))
    for g in d["gebaeude"]:
        if g["typ"] in vorhanden:
            continue
        if g["name"] not in namen and g["typ"] in typen:
            x, y = merc(g["lon"], g["lat"])
            neu.append({"typ": g["typ"], "name": g["name"], "text": g.get("text", ""), "x": x, "y": y})
    for g in neu:
        nr += 1
        liste.append({"id": f"b{nr}", **g})
        print(f'  + b{nr} {g["typ"]:18} {g["name"]}')
    print(f"{len(neu)} neue Gebäude, gesamt {len(liste)}")
    if "--ausfuehren" in sys.argv and neu:
        stand["gebaeude"] = liste
        v = karte.neue_version(con, karte.pruefen(stand), "Gebäude: bisherige Bauwerke auf Behördentypen umgestellt, Dienstgebäude der Reichsbehörden gesetzt", {"id": "", "name": "System"})
        print("Kartenversion", v)


if __name__ == "__main__":
    main()
