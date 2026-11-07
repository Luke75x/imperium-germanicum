"""Start des Verteidigungsetats (einmalig, 07.11.2026): legt die Verteidigungskassen an und bucht für den bereits gebuchten
Monat November 2026 den Verteidigungsetat nach (aufkommen.verteidigung_einbuchen: aus den Pflichtausgaben abgezweigt, die freien Mittel
bleiben gleich). Gerätebestände beginnen leer; die Instandhaltung läuft ab Dezember mit dem Staatshaushalt.
Sperre: Protokoll „Verteidigungsetat nachgebucht“. Aufruf: .venv/bin/python werkzeuge/verteidigung_start.py [DB-Pfad] [--ausfuehren]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config  # noqa: E402

if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
    config.DB = sys.argv[1]
import aufkommen  # noqa: E402
import besoldung  # noqa: E402
import db  # noqa: E402
import geld  # noqa: E402
import verteidigung  # noqa: E402

AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}
PERIODE = "2026-11"


def main():
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    aufkommen.einrichten(con)
    verteidigung.einrichten(con)
    verteidigung.kassen_sichern(con)
    besoldung.einrichten(con)
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion='Verteidigungsetat nachgebucht'").fetchone():
        sys.exit("Bereits ausgeführt.")
    if "--ausfuehren" not in sys.argv:
        print("Probelauf – Kassen angelegt; mit --ausfuehren den November nachbuchen.")
        return
    summe = aufkommen.verteidigung_einbuchen(con, PERIODE, AMT)
    print("Verteidigungsetat November nachgebucht:", geld.mark(summe))
    for r in con.execute("SELECT name, saldo FROM gk_konten WHERE art='verteidigung' ORDER BY saldo DESC"):
        print(f"  {r['name']:45} {geld.mark(r['saldo']):>26}")


if __name__ == "__main__":
    main()
