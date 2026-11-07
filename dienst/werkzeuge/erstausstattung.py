"""Einmalige Erstausstattung der Staatskassen durch die Zentralbank (07.11.2026).

Schlüssel (seit der Neuberechnung): Betrag = Sockel 20.000 M
                                    + Fläche (km²) × 1 M × Stärkefaktor
                                    + BIP (Mio. €) × 0,10 M
Stärkefaktor = BIP pro Kopf des Teilstaats ÷ Reichsdurchschnitt, begrenzt auf 0,5 … 2,0 (Wirtschaftsstärke).
Flächen und Einwohner aus der Reichskarte (geo.json, bevoelkerung.json), BIP aus karte_daten/bip.json (werkzeuge/karte_bip.py, Eurostat).
Die unmittelbar vom Reich verwalteten Gebiete (geld.REICHSGEBIETE) gehen ohne Sockel an die Reichskasse.

Aufruf:  .venv/bin/python werkzeuge/erstausstattung.py                 Plan anzeigen
         .venv/bin/python werkzeuge/erstausstattung.py --ausfuehren    erstmalige Ausstattung (Sperre: Protokoll „Erstausstattung“)
         .venv/bin/python werkzeuge/erstausstattung.py --neuberechnen  Differenz zur bereits gebuchten Ausstattung nachbuchen
                                                                       (Schöpfung bzw. Vernichtung; Sperre: „Erstausstattung neu berechnet“)
Ursprünglich (erste Fassung) galt: Sockel 20.000 M + 2 M je km², ohne BIP.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db  # noqa: E402
import geld  # noqa: E402
import karte  # noqa: E402

DATEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "karte_daten")
SOCKEL = 20000 * 100        # Pfennig
JE_KM2 = 1 * 100            # Pfennig
JE_MIO_BIP = 10             # Pfennig (0,10 M je Mio. € BIP)
FAKTOR = (0.5, 2.0)
AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}


def kennzahlen(con):
    a = karte.aktuell(con)
    zu = a["stand"]["gebiete"]
    geo = json.load(open(os.path.join(DATEN, "geo.json")))["gebiete"]
    bev = json.load(open(os.path.join(DATEN, "bevoelkerung.json")))
    bip = json.load(open(os.path.join(DATEN, "bip.json")))
    st = {}
    for g, sid in zu.items():
        x = st.setdefault(sid, {"km2": 0.0, "ew": 0, "bip": 0.0})
        x["km2"] += geo.get(g, {}).get("a") or 0
        x["ew"] += bev.get(g, [0])[0]
        x["bip"] += bip.get(g, [0])[0]
    schnitt = sum(x["bip"] for x in st.values()) / sum(x["ew"] for x in st.values())
    return a["stand"]["staaten"], st, schnitt


def plan(con):
    staaten, st, schnitt = kennzahlen(con)
    out = []
    for s in staaten:
        x = st.get(s["id"], {"km2": 0, "ew": 0, "bip": 0})
        faktor = min(FAKTOR[1], max(FAKTOR[0], (x["bip"] / x["ew"]) / schnitt if x["ew"] else 1))
        flaeche = round(x["km2"] * JE_KM2 * faktor)
        wirtschaft = round(x["bip"] * JE_MIO_BIP)
        reich = geld.ist_reichsgebiet(s)
        konto = geld.sonder(con, "reichskasse") if reich else geld.stellenkonto(con, "ts-" + s["id"])
        betrag = round(((0 if reich else SOCKEL) + flaeche + wirtschaft) / 100) * 100   # auf ganze Mark
        text = ("" if reich else f"Sockel {geld.mark(SOCKEL)} + ") + (
            f"Fläche {round(x['km2']):,} km² × {geld.mark(JE_KM2)} × Stärke {faktor:.2f} (BIP/Kopf {x['bip'] * 1e6 / max(x['ew'], 1):,.0f} €) "
            f"+ BIP {round(x['bip']):,} Mio. € × {geld.mark(JE_MIO_BIP)}").replace(",", "·").replace(".", ",").replace("·", ".")
        out.append({"konto": konto, "name": s["name"], "km2": round(x["km2"]), "bip": round(x["bip"]), "faktor": faktor,
                    "betrag": betrag, "text": text})
    return sorted(out, key=lambda x: -x["betrag"]), schnitt


def main():
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    geld.einrichten(con)
    geld.teilstaaten_sichern(con)
    p, schnitt = plan(con)
    bisher = {r["an"]: r["s"] for r in con.execute("SELECT an, SUM(CASE WHEN art='geldschoepfung' THEN betrag ELSE -betrag END) s "
                                                    "FROM (SELECT an, betrag, art FROM gk_buchungen WHERE bezug='ERSTAUSSTATTUNG' "
                                                    "UNION ALL SELECT von, betrag, art FROM gk_buchungen WHERE bezug='ERSTAUSSTATTUNG' AND art='geldvernichtung') GROUP BY an")}
    print(f"Reichsdurchschnitt BIP/Kopf: {schnitt * 1e6:,.0f} €")
    for x in p:
        alt = bisher.get(x["konto"]["id"], 0)
        print(f"{x['name'][:36]:36} Stärke {x['faktor']:.2f} → {geld.mark(x['betrag']):>16}   bisher {geld.mark(alt):>16}   Δ {geld.mark(x['betrag'] - alt, True):>15}")
    print("Summe neu:", geld.mark(sum(x["betrag"] for x in p)), " bisher:", geld.mark(sum(bisher.values())))
    zb = geld.sonder(con, "zentralbank")
    if "--ausfuehren" in sys.argv:
        if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion='Erstausstattung'").fetchone():
            print("Bereits ausgeführt – abgebrochen.")
            return
        for x in p:
            geld.buchen(con, zb["id"], x["konto"]["id"], x["betrag"], "geldschoepfung", f"Erstausstattung {x['name']}: {x['text']}"[:200], AMT,
                        bezug="ERSTAUSSTATTUNG")
        geld.protokoll(con, AMT, "Erstausstattung", f"Einmalige Geldschöpfung für {len(p)} Kassen, zusammen {geld.mark(sum(x['betrag'] for x in p))}")
    elif "--neuberechnen" in sys.argv:
        if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion='Erstausstattung neu berechnet'").fetchone():
            print("Neuberechnung bereits gebucht – abgebrochen.")
            return
        for x in p:
            d = x["betrag"] - bisher.get(x["konto"]["id"], 0)
            zweck = f"Neuberechnung Erstausstattung {x['name']}: {x['text']}"[:200]
            if d > 0:
                geld.buchen(con, zb["id"], x["konto"]["id"], d, "geldschoepfung", zweck, AMT, bezug="ERSTAUSSTATTUNG")
            elif d < 0:
                geld.buchen(con, x["konto"]["id"], zb["id"], -d, "geldvernichtung", zweck, AMT, bezug="ERSTAUSSTATTUNG")
        geld.protokoll(con, AMT, "Erstausstattung neu berechnet",
                       f"Schlüssel: Sockel {geld.mark(SOCKEL)} + km² × {geld.mark(JE_KM2)} × Wirtschaftsstärke (BIP/Kopf ÷ Reichsschnitt, "
                       f"{FAKTOR[0]}–{FAKTOR[1]}) + BIP (Mio. €) × {geld.mark(JE_MIO_BIP)}; neu zusammen {geld.mark(sum(x['betrag'] for x in p))}")
    else:
        return
    con.commit()
    print("Gebucht. Geldmenge:", geld.mark(geld.geldmenge(con)), "· Summe aller Salden:", con.execute("SELECT SUM(saldo) FROM gk_konten").fetchone()[0])


if __name__ == "__main__":
    main()
