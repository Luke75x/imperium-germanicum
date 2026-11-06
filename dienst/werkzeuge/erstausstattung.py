"""Einmalige Erstausstattung der Staatskassen durch die Zentralbank nach Territorium (07.11.2026).

Schlüssel: Sockelbetrag je Teilstaat + Betrag je km² Fläche (Flächen aus der Reichskarte: Summe der Gebiete je Teilstaat).
Die unmittelbar vom Reich verwalteten Gebiete (geld.REICHSGEBIETE, „Freie Reichsgebiete“) gehen ohne Sockel an die Reichskasse.
Läuft nur einmal (Sperre über gk_protokoll „Erstausstattung“). Aufruf: .venv/bin/python werkzeuge/erstausstattung.py [--ausfuehren]
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db  # noqa: E402
import geld  # noqa: E402
import karte  # noqa: E402

SOCKEL = 20000 * 100     # Pfennig
JE_KM2 = 2 * 100         # Pfennig
AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}


def plan(con):
    a = karte.aktuell(con)
    zu = a["stand"]["gebiete"]
    geo = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "karte_daten", "geo.json")))["gebiete"]
    flaeche = {}
    for gid, g in geo.items():
        if zu.get(gid):
            flaeche[zu[gid]] = flaeche.get(zu[gid], 0) + (g.get("a") or 0)
    out = []
    for s in a["stand"]["staaten"]:
        km2 = round(flaeche.get(s["id"], 0))
        if s["id"] in geld.REICHSGEBIETE:
            out.append((geld.sonder(con, "reichskasse"), s["name"], km2, km2 * JE_KM2))
        else:
            out.append((geld.stellenkonto(con, "ts-" + s["id"]), s["name"], km2, SOCKEL + km2 * JE_KM2))
    return sorted(out, key=lambda x: -x[3])


def main():
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    geld.einrichten(con)
    geld.teilstaaten_sichern(con)
    p = plan(con)
    for konto, name, km2, betrag in p:
        print(f"{name[:40]:40} {km2:>9,} km² → {geld.mark(betrag):>18}  ({konto['name']})")
    print("Summe:", geld.mark(sum(x[3] for x in p)))
    if "--ausfuehren" not in sys.argv:
        return
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion='Erstausstattung'").fetchone():
        print("Bereits ausgeführt – abgebrochen.")
        return
    zb = geld.sonder(con, "zentralbank")
    for konto, name, km2, betrag in p:
        sockel = "" if konto["stelle"] == "reichskasse" else f"Sockel {geld.mark(SOCKEL)} + "
        geld.buchen(con, zb["id"], konto["id"], betrag, "geldschoepfung",
                    f"Erstausstattung nach Territorium: {name}, {sockel}{km2:,} km² × {geld.mark(JE_KM2)}".replace(",", "."), AMT, bezug="ERSTAUSSTATTUNG")
    geld.protokoll(con, AMT, "Erstausstattung", f"Einmalige Geldschöpfung nach Territorium für {len(p)} Kassen, zusammen "
                                               f"{geld.mark(sum(x[3] for x in p))} (Sockel {geld.mark(SOCKEL)} je Teilstaat + {geld.mark(JE_KM2)} je km²)")
    con.commit()
    print("Ausgeführt. Geldmenge:", geld.mark(geld.geldmenge(con)), "· Summe aller Salden:", con.execute("SELECT SUM(saldo) FROM gk_konten").fetchone()[0])


if __name__ == "__main__":
    main()
