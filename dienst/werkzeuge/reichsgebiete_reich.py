"""Freie Reichsgebiete dem Reich zurechnen (einmalig, 07.11.2026).

Die Freien Reichsgebiete sind kein Teilstaat, sondern das Reich selbst (geld.ist_reichsgebiet). Geld: Sie hatten nie eine eigene
Staatskasse – Erstausstattung, Steueraufkommen und Pflichtausgaben liefen schon über die Reichskasse; das Werkzeug prüft das und
überführt ein etwa doch vorhandenes Konto „ts-<sid>“ samt Saldo per Buchung (art umbuchung, bezug REICHSGEBIETE) in die Reichskasse.
Gold: Der Ausgangsbestand der Freien Reichsgebiete lag als „Reichsgoldreserve“ bei der Zentralbank; er wird mit zwei Goldbuchungen
(art umbuchung) in den Bestand der Reichskasse umgebucht. Keine Geldbewegung. Sperre: Protokoll „Reichsgebiete dem Reich zugerechnet“.
Aufruf: .venv/bin/python werkzeuge/reichsgebiete_reich.py [DB-Pfad] [--ausfuehren]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config  # noqa: E402

if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
    config.DB = sys.argv[1]
import db  # noqa: E402
import geld  # noqa: E402
import gold  # noqa: E402
import karte  # noqa: E402

AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}
SPERRE = "Reichsgebiete dem Reich zugerechnet"


def main():
    los = "--ausfuehren" in sys.argv
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    geld.einrichten(con)
    gold.einrichten(con)
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion=?", (SPERRE,)).fetchone():
        sys.exit("Bereits ausgeführt (Protokoll „%s“)." % SPERRE)
    rk = geld.sonder(con, "reichskasse")
    gebiete = [s for s in karte.aktuell(con)["stand"]["staaten"] if geld.ist_reichsgebiet(s)]
    print("Freie Reichsgebiete auf der Karte:", ", ".join(f'{s["id"]} {s["name"]}' for s in gebiete) or "keine")
    schritte = []
    # 1. Eigene Konten der Reichsgebiete (sollte es nicht geben)
    for s in gebiete:
        for r in con.execute("SELECT * FROM gk_konten WHERE stelle=?", ("ts-" + s["id"],)).fetchall():
            n = con.execute("SELECT COUNT(*) FROM gk_buchungen WHERE von=? OR an=?", (r["id"], r["id"])).fetchone()[0]
            schritte.append(f'Konto {r["nummer"]} „{r["name"]}“: Saldo {geld.mark(r["saldo"])}, {n} Buchungen → Saldo an die Reichskasse, Konto bleibt als Altkonto')
            if los and r["saldo"]:
                v, a = (r, rk) if r["saldo"] > 0 else (rk, r)
                geld.buchen(con, v["id"], a["id"], abs(r["saldo"]), "umbuchung", f'Überführung in die Reichskasse: {s["name"]} sind kein Teilstaat',
                            AMT, bezug="REICHSGEBIETE", minus=True)
            if los:
                con.execute("UPDATE gk_konten SET name=? WHERE id=?", (r["name"] + " (aufgelöst, jetzt Reichskasse)", r["id"]))
    # 2. Gold der Reichsgebiete: Erstausstattung bei der Zentralbank → Reichskasse
    kg = con.execute("SELECT COALESCE(SUM(kg),0) FROM gr_buchungen WHERE stelle='zentralbank' AND art='erstausstattung'").fetchone()[0]
    kg = round(min(kg, gold.bestand(con, "zentralbank")), 3)
    if kg > 0:
        schritte.append(f"Gold {kg:,.1f} kg: Zentralbank (Reichsgoldreserve der Freien Reichsgebiete) → Reichskasse")
        if los:
            zweck = "Freie Reichsgebiete sind das Reich: Ausgangsbestand von der Zentralbank in die Reichskasse"
            gold._bewegen(con, "zentralbank", "Zentralbank des Reiches", -kg, "umbuchung", 0, AMT, zweck)
            gold._bewegen(con, "reichskasse", rk["name"], kg, "umbuchung", 0, AMT, zweck)
    print("\n".join(schritte) or "Nichts zu überführen.")
    print("Geldmenge:", geld.mark(geld.geldmenge(con)), "· Reichskasse:", geld.mark(geld.sonder(con, "reichskasse")["saldo"]))
    if not los:
        print("Probelauf – mit --ausfuehren buchen.")
        return
    geld.protokoll(con, AMT, SPERRE, "; ".join(schritte) or "Keine eigenen Bestände der Freien Reichsgebiete vorhanden.")
    con.commit()
    print("Gebucht.", time.strftime("%d.%m.%Y %H:%M"))


if __name__ == "__main__":
    main()
