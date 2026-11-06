"""Bruttoinlandsprodukt je Gebiet (NUTS 3) für die Reichskarte: karte_daten/bip.json {code: [Mio. EUR, Jahr, geschätzt 0/1]}.

Quelle: Eurostat nama_10r_3gdp (BIP zu Marktpreisen, Mio. EUR), je Gebiet der neueste Wert aus 2023/2022/2021.
Gebiete ohne Eurostat-Wert (geänderte NUTS-Zuschnitte in Thüringen und den Niederlanden, Liechtenstein, Königsberg) werden
geschätzt: Einwohner × BIP pro Kopf des Landes (aus den übrigen Gebieten des Landes), ohne Landeswert × Durchschnitt aller Gebiete.
Aufruf: .venv/bin/python werkzeuge/karte_bip.py
"""
import json
import os
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
DATEN = os.path.join(HIER, "..", "karte_daten")
URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10r_3gdp?format=JSON&unit=MIO_EUR&time={}"


def laden():
    bip = {}
    for jahr in (2021, 2022, 2023):   # spätere Jahre überschreiben frühere
        with urllib.request.urlopen(URL.format(jahr), timeout=120) as r:
            d = json.load(r)
        inv = {v: k for k, v in d["dimension"]["geo"]["category"]["index"].items()}
        for pos, wert in d["value"].items():
            if wert is not None:
                bip[inv[int(pos)]] = [round(float(wert), 2), jahr, 0]
    return bip


def main():
    bip = laden()
    geo = json.load(open(os.path.join(DATEN, "geo.json")))["gebiete"]
    bev = json.load(open(os.path.join(DATEN, "bevoelkerung.json")))
    land_bip, land_ew = {}, {}
    for g in geo:
        if g in bip and g in bev:
            land_bip[g[:2]] = land_bip.get(g[:2], 0) + bip[g][0]
            land_ew[g[:2]] = land_ew.get(g[:2], 0) + bev[g][0]
    gesamt = sum(land_bip.values()) / sum(land_ew.values())
    out = {}
    for g in geo:
        if g in bip:
            out[g] = bip[g]
        elif g in bev:
            pro_kopf = land_bip[g[:2]] / land_ew[g[:2]] if land_ew.get(g[:2]) else gesamt
            out[g] = [round(bev[g][0] * pro_kopf, 2), 2023, 1]
    json.dump(out, open(os.path.join(DATEN, "bip.json"), "w"), separators=(",", ":"))
    print(f"{len(out)} Gebiete, davon geschätzt {sum(1 for v in out.values() if v[2])}; Durchschnitt {gesamt * 1e6:,.0f} € je Einwohner")


if __name__ == "__main__":
    main()
