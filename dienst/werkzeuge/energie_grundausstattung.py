"""Grundausstattung des Energiesystems aus realen Daten erzeugen (karte_daten/energie.json). Aufruf: .venv/bin/python werkzeuge/energie_grundausstattung.py [DB-Pfad]

Nichts wird erfunden: Jeder Teilstaat (und das Reich = Freie Reichsgebiete) erhält die Stromerzeugung, die auf seinem Gebiet real stattfindet – auch wenn sie seinen
Bedarf nicht deckt. Kernkraft wird nicht übernommen (im Spiel gibt es noch keine).

Verfahren
 1. Nationale Bruttostromerzeugung je Energieträger 2023 (Eurostat nrg_bal_peh, GEP) für die EU-Länder des Spielgebiets.
 2. Verteilung auf die Regionen (NUTS 3) im Verhältnis der Leistung der realen Kraftwerke des jeweiligen Energieträgers dort (World Resources Institute, Global Power
    Plant Database 1.3, Standorte mit Koordinaten; Punkt-in-Fläche auf den Regionen der Reichskarte). Für Wind, Solar, Wasser und Biomasse in Deutschland: alle im Register
    verzeichneten Anlagen (Open Power System Data, renewable_power_plants_DE, Stand 2020, Leistung je NUTS-3-Region). Gibt es für einen Träger im Land kein Kraftwerk in der Datenbank
    (z. B. verstreute Kleinanlagen), wird nach der Einwohnerzahl der Regionen verteilt.
 3. Länder ohne Eurostat-Zahlen (Schweiz, Kaliningrad): Erzeugung der Kraftwerke der Datenbank selbst (berichtete bzw. geschätzte Jahreserzeugung).
 4. Bedarf: Stromverbrauch (Eurostat nrg_cb_e: Inlandsnachfrage, Industrieanteil am Endverbrauch) je Einwohner und je Mio. € BIP; die Werte stehen als Kalibrierung in der Datei.
Zuordnung der Träger: Kohle (feste fossile Brennstoffe, Torf, Ölschiefer, Kuppelgase), Gas, Öl, Wasser (ohne Pumpspeicher), Wind, Solar, Biomasse (feste Biomasse, Biogas,
flüssige Biokraftstoffe, Abfall). Geothermie, Gezeiten und Kernkraft entfallen.
"""
import csv
import io
import json
import math
import os
import re
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config  # noqa: E402

if len(sys.argv) > 1:
    config.DB = sys.argv[1]
import db  # noqa: E402
import karte  # noqa: E402

DATEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "karte_daten")
JAHR = "2023"
EU = ["DE", "IT", "AT", "CZ", "PL", "HR", "SI", "BE", "FR", "LU", "NL"]
ISO3 = {"DEU": "DE", "ITA": "IT", "AUT": "AT", "CZE": "CZ", "POL": "PL", "HRV": "HR", "SVN": "SI", "BEL": "BE", "FRA": "FR", "LUX": "LU", "NLD": "NL", "CHE": "CH",
        "RUS": "RU", "LIE": "LI"}
GPPD = "https://wri-dataportal-prod.s3.amazonaws.com/manual/global_power_plant_database_v_1_3.zip"
OPSD_DE = "https://data.open-power-system-data.org/renewable_power_plants/2020-08-25/renewable_power_plants_DE.csv"
OPSD_TRAEGER = {"Wind": "wind", "Solar": "solar", "Hydro": "wasser", "Bioenergy": "biomasse"}
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
TYPEN = ["kohle", "gas", "oel", "wasser", "wind", "solar", "biomasse"]
EUROSTAT_TRAEGER = {"kohle": ["C0000X0350-0370", "C0350-0370", "P1000", "S2000"], "gas": ["G3000"], "oel": ["O4000XBIO"], "wasser": ["RA100"], "wind": ["RA300"],
                    "solar": ["RA410", "RA420"], "biomasse": ["R5110-5150_W6000RI", "R5160", "R5290", "R5300", "W6210", "W6100_6220"]}
GPPD_TRAEGER = {"Coal": "kohle", "Gas": "gas", "Cogeneration": "gas", "Oil": "oel", "Petcoke": "oel", "Hydro": "wasser", "Wind": "wind", "Solar": "solar", "Biomass": "biomasse",
                "Waste": "biomasse"}


def holen(url):
    req = urllib.request.Request(url, headers={"User-Agent": "imperium-energie/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def jsonstat(url):
    d = json.loads(holen(url))
    dims = d["id"]
    pos = {k: list(d["dimension"][k]["category"]["index"].keys()) if isinstance(d["dimension"][k]["category"]["index"], dict) else d["dimension"][k]["category"]["index"] for k in dims}
    gr = d["size"]
    werte = d["value"]
    out = {}
    for flach, w in werte.items():
        i = int(flach)
        koord = {}
        for k, n in reversed(list(zip(dims, gr))):
            koord[k] = pos[k][i % n]
            i //= n
        out[tuple(koord[k] for k in dims)] = w
    return dims, out


def eurostat_erzeugung():
    """{Land: {Träger: GWh im Jahr}} nach Eurostat nrg_bal_peh (Bruttostromerzeugung)."""
    geo = "".join(f"&geo={g}" for g in EU)
    dims, w = jsonstat(f"{EUROSTAT}nrg_bal_peh?format=JSON&lang=EN&time={JAHR}&unit=GWH&nrg_bal=GEP{geo}")
    gi, si = dims.index("geo"), dims.index("siec")
    roh = {(k[gi], k[si]): v for k, v in w.items()}
    out = {}
    for land in EU:
        out[land] = {t: sum(roh.get((land, c), 0.0) or 0.0 for c in codes) for t, codes in EUROSTAT_TRAEGER.items()}
    return out


def eurostat_verbrauch():
    geo = "".join(f"&geo={g}" for g in EU)
    dims, w = jsonstat(f"{EUROSTAT}nrg_cb_e?format=JSON&lang=EN&time={JAHR}&unit=GWH&siec=E7000{geo}")
    gi, bi = dims.index("geo"), dims.index("nrg_bal")
    roh = {(k[gi], k[bi]): v for k, v in w.items()}
    return {land: {b: roh.get((land, b)) for b in ("ID", "FC", "FC_IND_E")} for land in EU}


def kraftwerke():
    z = zipfile.ZipFile(io.BytesIO(holen(GPPD)))
    name = next(n for n in z.namelist() if n.endswith(".csv"))
    out = []
    for r in csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8")):
        land = ISO3.get(r["country"])
        t = GPPD_TRAEGER.get(r["primary_fuel"])
        if not land or not t:
            continue
        try:
            mw, lat, lon = float(r["capacity_mw"]), float(r["latitude"]), float(r["longitude"])
        except ValueError:
            continue
        gen = None
        for j in ("2019", "2018", "2017"):
            if r.get(f"generation_gwh_{j}"):
                gen = float(r[f"generation_gwh_{j}"])
                break
        if gen is None and r.get("estimated_generation_gwh_2017"):
            gen = float(r["estimated_generation_gwh_2017"])
        out.append({"land": land, "typ": t, "mw": mw, "lat": lat, "lon": lon, "gwh": gen or 0.0, "name": r["name"]})
    return out


def opsd_de(flaechen, gueltig):
    """{Träger: {Region: MW}} aller deutschen Erneuerbaren-Anlagen (Datei wird zwischengespeichert in $ENERGIE_CACHE oder /tmp)."""
    pfad = os.path.join(os.environ.get("ENERGIE_CACHE", "/tmp"), "renewable_power_plants_DE.csv")
    if not os.path.exists(pfad):
        req = urllib.request.Request(OPSD_DE, headers={"User-Agent": "imperium-energie/1.0"})
        with urllib.request.urlopen(req, timeout=600) as r, open(pfad + ".neu", "wb") as fh:
            while True:
                blk = r.read(1 << 20)
                if not blk:
                    break
                fh.write(blk)
        os.replace(pfad + ".neu", pfad)
    out = {t: {} for t in OPSD_TRAEGER.values()}
    ohne = 0
    with open(pfad, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            t = OPSD_TRAEGER.get(r["energy_source_level_2"])
            if not t or not r["electrical_capacity"]:
                continue
            g = r["nuts_3_region"]
            if g not in gueltig:   # NUTS-Stand 2016 weicht in wenigen Kreisen ab: dann über die Koordinaten
                g = None
                if r["lon"] and r["lat"]:
                    x, y = welt_xy(float(r["lat"]), float(r["lon"]))
                    for k, (bb, rs) in flaechen.items():
                        if k[:2] == "DE" and bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3] and innen(x, y, rs):
                            g = k
                            break
            if not g:
                ohne += 1
                continue
            out[t][g] = out[t].get(g, 0.0) + float(r["electrical_capacity"])
    print("Deutschland (Erneuerbare): Anlagen ohne Region:", ohne)
    return out


def welt_xy(lat, lon, breite=40000):
    x = (lon + 180) / 360 * breite
    y = (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * breite
    return x, y


def ringe(d):
    out = []
    for teil in re.findall(r"M[^M]*", d):
        zahlen = [float(z) for z in re.findall(r"-?\d+(?:\.\d+)?", teil)]
        pts = list(zip(zahlen[0::2], zahlen[1::2]))
        if len(pts) >= 3:
            out.append(pts)
    return out


def innen(x, y, rs):
    """Gerade-ungerade-Regel über alle Ringe (Löcher inklusive)."""
    n = 0
    for pts in rs:
        j = len(pts) - 1
        for i, (xi, yi) in enumerate(pts):
            xj, yj = pts[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                n += 1
            j = i
    return n % 2 == 1


def main():
    con = db.verbinden()
    stand = karte.aktuell(con)["stand"]
    besitzer = dict(stand["gebiete"])                       # Region → Teilstaat-ID
    geo = json.load(open(os.path.join(DATEN, "geo.json")))
    bev = json.load(open(os.path.join(DATEN, "bevoelkerung.json")))
    bip = json.load(open(os.path.join(DATEN, "bip.json")))
    flaechen = {}
    for g, v in geo["gebiete"].items():
        rs = ringe(v["d"])
        if rs:
            flaechen[g] = (v["b"], rs)
    es_gen, es_ver = eurostat_erzeugung(), eurostat_verbrauch()
    anlagen = kraftwerke()
    print(len(anlagen), "Kraftwerke der Datenbank im Spielgebiet und Umgebung")
    # Kraftwerke den Regionen zuordnen (Prüfung zuerst nach Land, dann Umriss der Region)
    de_ee = opsd_de(flaechen, set(bev))
    nach_land = {}
    for a in anlagen:
        x, y = welt_xy(a["lat"], a["lon"])
        a["region"] = None
        for g, (bb, rs) in flaechen.items():
            if g[:2] != a["land"]:
                continue
            if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3] and innen(x, y, rs):
                a["region"] = g
                break
        nach_land.setdefault(a["land"], []).append(a)
    # Erzeugung je Region und Träger (GWh/Jahr)
    gen = {}
    belegt = {}
    for land, liste in nach_land.items():
        regionen_land = [g for g in bev if g[:2] == land]
        if land in es_gen:
            for t in TYPEN:
                gesamt = es_gen[land][t]
                gw = [(a["region"], a["mw"]) for a in liste if a["typ"] == t and a["region"]]
                if land == "DE" and t in de_ee:
                    gw = list(de_ee[t].items())
                s = sum(m for _, m in gw)
                if gesamt <= 0:
                    continue
                if s > 0:
                    for g, m in gw:
                        gen.setdefault(g, {}).setdefault(t, 0.0)
                        gen[g][t] += gesamt * m / s
                else:
                    belegt.setdefault(land, []).append(t)
                    pe = sum(bev[g][0] for g in regionen_land) or 1
                    for g in regionen_land:
                        gen.setdefault(g, {}).setdefault(t, 0.0)
                        gen[g][t] += gesamt * bev[g][0] / pe
        else:   # Schweiz, Kaliningrad: Erzeugung der Kraftwerke selbst
            for a in liste:
                if a["region"] and a["gwh"] > 0:
                    gen.setdefault(a["region"], {}).setdefault(a["typ"], 0.0)
                    gen[a["region"]][a["typ"]] += a["gwh"]
    # Teilstaaten
    out = {}
    for g, tt in gen.items():
        sid = besitzer.get(g)
        if not sid:
            continue
        schl = "reich" if sid == "s2" else "ts-" + sid
        for t, v in tt.items():
            out.setdefault(schl, {})
            out[schl][t] = out[schl].get(t, 0.0) + v / 12   # GWh je Monat
    out = {s: {t: round(v, 2) for t, v in sorted(tt.items()) if v > 0} for s, tt in out.items()}
    # Bedarf kalibrieren
    pop = {l: sum(v[0] for g, v in bev.items() if g[:2] == l) for l in EU}
    bipn = {l: sum(v[0] for g, v in bip.items() if g[:2] == l) for l in EU}
    ID = sum(es_ver[l]["ID"] or 0 for l in EU)
    anteil_ind = sum(es_ver[l]["FC_IND_E"] or 0 for l in EU) / (sum(es_ver[l]["FC"] or 0 for l in EU) or 1)
    kal = {"jahr": JAHR, "industrieanteil": round(anteil_ind, 4), "haushalt_kwh": round((1 - anteil_ind) * ID / sum(pop.values()) / 12 * 1e6, 1),
           "industrie_gwh_je_mio": round(anteil_ind * ID / sum(bipn.values()), 5), "inlandsnachfrage_gwh": round(ID)}
    ergebnis = {"quelle": "Eurostat nrg_bal_peh / nrg_cb_e (" + JAHR + "); WRI Global Power Plant Database 1.3 (Standorte)", "kalibrierung": kal,
                "ohne_kraftwerke_nach_einwohnern": belegt, "erzeugung_gwh_monat": out}
    with open(os.path.join(DATEN, "energie.json"), "w", encoding="utf-8") as fh:
        json.dump(ergebnis, fh, ensure_ascii=False, indent=1)
    namen = {s["id"]: s["name"] for s in stand["staaten"]}
    for schl, tt in sorted(out.items(), key=lambda x: namen.get(x[0][3:], x[0])):
        summe = sum(tt.values())
        print(f'{namen.get(schl[3:], schl):32} {summe:9.0f} GWh/Monat  ' + " ".join(f"{t}:{v / summe * 100:.0f}%" for t, v in tt.items()))
    print(kal)
    print("Fallback nach Einwohnern:", belegt)


if __name__ == "__main__":
    main()
