"""Erstausstattung der Goldreserven (einmalig, 07.11.2026).

Goldbestände der Nationalbanken (World Gold Council, Stand Ende 2024, Tonnen) werden auf die Gebiete der Reichskarte verteilt:
Anteil eines Gebiets = BIP des Gebiets ÷ BIP des ganzen Landes (Eurostat nama_10r_3gdp, NUTS 0; für Länder ohne Eurostat-Wert
siehe LAND_BIP). Summe je Teilstaat → gr_bestand 'ts-<sid>'; Freie Reichsgebiete (= Reich) → Reichskasse
(bis 07.11.2026 bei der Zentralbank, umgebucht mit werkzeuge/reichsgebiete_reich.py).
Aufruf: .venv/bin/python werkzeuge/goldreserven.py [--ausfuehren]
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db  # noqa: E402
import geld  # noqa: E402
import gold  # noqa: E402
import karte  # noqa: E402

DATEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "karte_daten")
TONNEN = {"DE": 3351.5, "IT": 2451.8, "FR": 2437.0, "NL": 612.5, "CH": 1040.0, "BE": 227.4, "AT": 280.0, "CZ": 51.1, "PL": 448.2,
          "LU": 2.2, "SI": 3.2, "HR": 0.0, "LI": 0.0, "RU": 2335.9}
LAND_BIP = {"RU": 1_850_000}   # Mio. € (Russland 2023, grob); CH/LI: ganz im Reich → Summe der Gebiete
URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10r_3gdp?format=JSON&unit=MIO_EUR&time=2023"
AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}


def land_bip():
    with urllib.request.urlopen(URL, timeout=120) as r:
        d = json.load(r)
    inv = {v: k for k, v in d["dimension"]["geo"]["category"]["index"].items()}
    out = {inv[int(p)]: v for p, v in d["value"].items() if len(inv[int(p)]) == 2 and v}
    out.update(LAND_BIP)
    return out


def plan(con):
    a = karte.aktuell(con)
    zu = a["stand"]["gebiete"]
    bip = json.load(open(os.path.join(DATEN, "bip.json")))
    national = land_bip()
    im_reich = {}
    for g in zu:
        im_reich[g[:2]] = im_reich.get(g[:2], 0) + bip.get(g, [0])[0]
    kg = {}
    for g, sid in zu.items():
        land = g[:2]
        basis = max(national.get(land) or 0, im_reich[land])   # ganz im Reich (CH, LI) oder Schätzung über Landeswert → höchstens 100 %
        anteil = bip.get(g, [0])[0] / basis if basis else 0
        kg[sid] = kg.get(sid, 0) + TONNEN.get(land, 0) * 1000 * anteil
    out = []
    for s in a["stand"]["staaten"]:
        if geld.ist_reichsgebiet(s):   # Freie Reichsgebiete = Reich: Bestand der Reichskasse
            out.append(("reichskasse", "Reichskasse", s["name"], kg.get(s["id"], 0)))
        else:
            k = geld.stellenkonto(con, "ts-" + s["id"])
            out.append((k["stelle"], k["name"], s["name"], kg.get(s["id"], 0)))
    return sorted(out, key=lambda x: -x[3])


def main():
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    gold.einrichten(con)
    p = plan(con)
    for stelle, name, staat, kg in p:
        print(f"{staat[:36]:36} {kg / 1000:>9,.2f} t   Wert {geld.mark(gold.wert(con, kg)):>16}")
    print(f"Gesamt {sum(x[3] for x in p) / 1000:,.1f} t, Wert {geld.mark(gold.wert(con, sum(x[3] for x in p)))}")
    if "--ausfuehren" not in sys.argv:
        return
    if con.execute("SELECT 1 FROM gr_buchungen WHERE art='erstausstattung'").fetchone():
        print("Bereits ausgestattet – abgebrochen.")
        return
    for stelle, name, staat, kg in p:
        gold._bewegen(con, stelle, name, round(kg, 1), "erstausstattung", 0, AMT, f"Goldreserve {staat}")
    geld.protokoll(con, AMT, "Goldreserven", f"Erstausstattung {sum(x[3] for x in p) / 1000:,.1f} t nach den Reserven der Nationalbanken (anteilig BIP)")
    con.commit()
    print("Gebucht.")


if __name__ == "__main__":
    main()
