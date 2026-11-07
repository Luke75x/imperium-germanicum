"""Crown Estates des Kaisers einrichten (einmalig, 07.11.2026).

Die Kronsteuer (Quellenabzug im Lohnlauf plus Kronsteuer der simulierten Bevölkerung im Staatshaushalt) fließt in die Crown Estates des
Kaisers (Sonderkonto „crown_estates“); aus ihnen wird der Monarch (Imperator Rex, Imperatrix Regina) bezahlt (besoldung: Zahlstelle
crown_estates). Dieses Werkzeug bucht
 1. die Ersteinlage aus der Reichskasse (Haushaltszuweisung, bezug CROWN-ERSTEINLAGE, Standard 1.000.000 Kr) und
 2. die Kronsteuer der Bevölkerung für den bereits gebuchten Haushaltsmonat November 2026 nach.
Sperre: Protokoll „Crown Estates eingerichtet“. Aufruf: .venv/bin/python werkzeuge/crown_estates.py [DB-Pfad] [--ausfuehren]
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

AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}
SPERRE = "Crown Estates eingerichtet"
EINLAGE = 1_000_000 * 100   # Heller
PERIODE = "2026-11"


def main():
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    geld.einrichten(con)
    aufkommen.einrichten(con)
    besoldung.einrichten(con)
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion=?", (SPERRE,)).fetchone():
        sys.exit("Bereits ausgeführt.")
    ce, rk = geld.sonder(con, "crown_estates"), geld.sonder(con, "reichskasse")
    print("Crown Estates:", ce["nummer"], geld.mark(ce["saldo"]), "| Reichskasse:", geld.mark(rk["saldo"]))
    print("Geplant: Ersteinlage", geld.mark(EINLAGE), "und Kronsteuer der Bevölkerung für", PERIODE)
    if "--ausfuehren" not in sys.argv:
        print("Probelauf – mit --ausfuehren buchen.")
        return
    geld.buchen(con, rk["id"], ce["id"], EINLAGE, "zuweisung", "Ersteinlage Crown Estates des Kaisers", AMT, bezug="CROWN-ERSTEINLAGE")
    kst = aufkommen.kronsteuer_buchen(con, PERIODE, AMT)
    geld.protokoll(con, AMT, SPERRE, f"Ersteinlage {geld.mark(EINLAGE)}, Kronsteuer {PERIODE} {geld.mark(kst)}")
    con.commit()
    print("Gebucht. Crown Estates jetzt:", geld.mark(geld.sonder(con, "crown_estates")["saldo"]))


if __name__ == "__main__":
    main()
