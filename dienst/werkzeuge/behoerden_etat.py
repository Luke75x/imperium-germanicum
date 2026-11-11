"""Erstausstattung der Behördenkassen (einmalig, 07.11.2026): Jede Reichsbehörde und die Kronkanzlei erhalten ihren Jahresetat
(etat.VORGABE, Größenordnung der vergleichbaren deutschen Bundesbehörden × 2,4 ÷ Wechselkurs) als Haushaltszuweisung aus der
Reichskasse (Buchungsart zuweisung, bezug ETAT-2026). Die Etats werden als Einstellung „etats“ festgeschrieben.
Sperre: Protokoll „Erstausstattung Behördenetats“.
Aufruf: .venv/bin/python werkzeuge/behoerden_etat.py [DB-Pfad] [--ausfuehren]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config  # noqa: E402

if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
    config.DB = sys.argv[1]
import db  # noqa: E402
import etat  # noqa: E402
import geld  # noqa: E402

AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}
SPERRE = "Erstausstattung Behördenetats"


def main():
    los = "--ausfuehren" in sys.argv
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    geld.einrichten(con)
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion=?", (SPERRE,)).fetchone():
        sys.exit(f"Bereits ausgeführt (Protokoll „{SPERRE}“).")
    e = {s: int(v * etat.MRD) for s, v in etat.VORGABE.items()}
    for s, n in etat.stellen():
        print(f"{n:45} {geld.mark(e.get(s, 0)):>28}")
    print(f"{'Summe':45} {geld.mark(sum(e.values())):>28}")
    print("Reichskasse vorher:", geld.mark(geld.sonder(con, "reichskasse")["saldo"]))
    if not los:
        print("Probelauf – mit --ausfuehren buchen.")
        return
    geld.einstellung_setzen(con, "etats", e, AMT)
    for s, n in etat.stellen():
        if e.get(s):
            etat.zuweisen(con, s, e[s], "Erstausstattung: Jahresetat 2026", AMT, bezug="ETAT-2026")
    geld.protokoll(con, AMT, SPERRE, f"{len(e)} Stellen, zusammen {geld.mark(sum(e.values()))} aus der Reichskasse")
    con.commit()
    print("Gebucht. Reichskasse nachher:", geld.mark(geld.sonder(con, "reichskasse")["saldo"]))


if __name__ == "__main__":
    main()
