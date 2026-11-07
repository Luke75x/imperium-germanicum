"""Umstellung des Staatshaushalts auf den Echtmaßstab (1 Kr = Wechselkurs €), einmalig am 07.11.2026.

1. Kassenreserven: Jede Kasse erhält als Reserve ein Monatsaufkommen ihres Anteils (Reichskasse: Reichsanteil aller Teilstaaten +
   Reichsgebiete; Staatskasse: Landesanteil). Gebucht wird die Differenz zur bisherigen Erstausstattung (Geldschöpfung, bezug ERSTAUSSTATTUNG).
2. Bereits gebuchte Monate des Staatshaushalts (aufkommen.nachbuchen) werden auf die Echtwerte samt Pflichtausgaben gebracht.
Sperre gegen Wiederholung: Protokoll „Erstausstattung Echtmaßstab“.
Aufruf: .venv/bin/python werkzeuge/echtmassstab.py [DB-Pfad] [--ausfuehren]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config  # noqa: E402

if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
    config.DB = sys.argv[1]
import aufkommen  # noqa: E402
import db  # noqa: E402
import geld  # noqa: E402

AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}


def main():
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    geld.einrichten(con)
    aufkommen.einrichten(con)
    liste = aufkommen.berechnen(con)
    ziel = {geld.sonder(con, "reichskasse")["id"]: ("Reichskasse", sum(x["reich"] for x in liste))}
    for x in liste:
        if x["kasse"]:
            ziel[x["kasse"]["id"]] = (x["kasse"]["name"], x["land"])
    bisher = {}
    for b in con.execute("SELECT * FROM gk_buchungen WHERE bezug='ERSTAUSSTATTUNG'"):
        if b["art"] == "geldschoepfung":
            bisher[b["an"]] = bisher.get(b["an"], 0) + b["betrag"]
        elif b["art"] == "geldvernichtung":
            bisher[b["von"]] = bisher.get(b["von"], 0) - b["betrag"]
    for kid, (name, soll) in sorted(ziel.items(), key=lambda x: -x[1][1]):
        print(f"{name[:40]:40} Reserve {geld.mark_kurz(soll):>16}   bisher {geld.mark_kurz(bisher.get(kid, 0)):>16}")
    print("Reserven zusammen:", geld.mark_kurz(sum(v[1] for v in ziel.values())))
    if "--ausfuehren" not in sys.argv:
        return
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion='Erstausstattung Echtmaßstab'").fetchone():
        print("Bereits umgestellt – abgebrochen.")
        return
    zb = geld.sonder(con, "zentralbank")
    for kid, (name, soll) in ziel.items():
        d = soll - bisher.get(kid, 0)
        if d > 0:
            geld.buchen(con, zb["id"], kid, d, "geldschoepfung", f"Kassenreserve Echtmaßstab: {name} = ein Monatsaufkommen", AMT, bezug="ERSTAUSSTATTUNG")
        elif d < 0:
            geld.buchen(con, kid, zb["id"], -d, "geldvernichtung", f"Kassenreserve Echtmaßstab: {name} = ein Monatsaufkommen", AMT, bezug="ERSTAUSSTATTUNG", minus=True)
    geld.protokoll(con, AMT, "Erstausstattung Echtmaßstab", f"Kassenreserven = ein Monatsaufkommen, zusammen {geld.mark(sum(v[1] for v in ziel.values()))}; "
                                                          f"Wechselkurs 1 Kr = {geld.einstellung(con, 'wechselkurs')} €")
    con.commit()
    for (periode,) in con.execute("SELECT periode FROM ak_laeufe ORDER BY periode").fetchall():
        aufkommen.nachbuchen(con, periode, AMT)
        print("Haushalt nachgebucht:", periode)
    print("Fertig. Geldmenge:", geld.mark_kurz(geld.geldmenge(con)), "· Reichskasse:", geld.mark_kurz(geld.sonder(con, "reichskasse")["saldo"]),
          "· Summe aller Salden:", con.execute("SELECT SUM(saldo) FROM gk_konten").fetchone()[0])


if __name__ == "__main__":
    main()
