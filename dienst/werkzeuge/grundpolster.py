"""Einmaliges Grundpolster (administrativ, 07.11.2026).

Wer zum Zeitpunkt der Ausführung eine der unten genannten Discord-Rollen trägt, erhält einmalig ein Grundpolster auf das Privatkonto
(Geldschöpfung der Zentralbank, Buchungsart startguthaben, bezug GRUNDPOLSTER). Wer später eine Rolle erhält, bekommt nichts.
Trägt jemand mehrere Posten, werden die Beträge addiert; jeder Posten (Zeile der Liste) zählt je Person einmal, auch wenn mehrere seiner
Rollen dazugehören. Jede Auszahlung wird in gp_vergabe festgehalten. Sperre gegen Wiederholung: Protokoll „Grundpolster vergeben“.
Aufruf: .venv/bin/python werkzeuge/grundpolster.py [DB-Pfad] [--ausfuehren]
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config  # noqa: E402

if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
    config.DB = sys.argv[1]
import db  # noqa: E402
import discord_api  # noqa: E402
import geld  # noqa: E402

AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}
SPERRE = "Grundpolster vergeben"
K = 100   # Kronen → Heller

# (Bezeichnung, Betrag in Kronen, [Rollennamen])
POSTEN = [
    ("König", 5_000_000, ["König"]), ("Erzherzog", 2_000_000, ["Erzherzog"]), ("Großherzog", 1_000_000, ["Großherzog"]), ("Herzog", 900_000, ["Herzog"]),
    ("Landgraf / Pfalzgraf / Markgraf", 800_000, ["Landgraf", "Pfalzgraf", "Markgraf"]), ("Reichsfürst / Fürst", 700_000, ["Reichsfürst", "Fürst"]),
    ("Prinz / Graf", 600_000, ["Prinz", "Graf"]), ("Baron", 500_000, ["Baron"]), ("Freiherr", 400_000, ["Freiherr"]),
    ("Mannschaften", 1_000, ["Mannschaften"]), ("Unteroffiziere", 1_500, ["Unteroffiziere"]), ("Offiziere", 3_000, ["Offiziersränge"]),
    ("Generalstab", 4_000, ["Generalstab"]),
    ("Stabschef (Führungsstab)", 5_000, ["Stabschef des Heeres", "Stabschef der Marine", "Stabschef der Luftwaffe"]),
    ("Titel im Heiligen Stuhl", 2_000, ["Papst", "Kardinal", "Erzbischof", "Bischof", "Weihbischof", "Priester"]),
    ("Generalkonsulat", 2_000, ["Generalkonsulat", "Generalkonsul", "Konsul"]),
    ("Reichsverwaltung (bis Generaldirektor)", 1_000, ["Reichsverwaltung", "Generaldirektor", "Ministerialdirektor", "Ministerialrat", "Direktor", "Inspektor",
                                                      "Amtsrat", "Amtsmann"]),
    ("Bürgermeister", 2_000, ["Bürgermeister"]), ("Magistrat", 2_500, ["Magistrat"]), ("Gouverneur", 3_000, ["Gouverneur"]),
    ("Generalgouverneur", 3_500, ["Generalgouverneur"]), ("Vizekönig", 4_000, ["Vizekönig"]), ("Kronkanzler", 10_000, ["Kronkanzler"]),
    ("Reichstag", 3_000, ["Reichstag"]), ("Reichsgerichtshof", 3_000, ["Reichsgerichtshof", "Oberster Reichsrichter", "Reichsrichter"]),
    ("Kurfürst", 5_000, ["Kurfürst"]), ("Hand des Kaisers", 7_000, ["Hand des Kaisers"]), ("Kaiser / Kaiserin", 10_000, ["Imperator Rex", "Imperatrix Regina"]),
]


async def laden():
    d = discord_api.Discord()
    await d.start()
    rollen = await d.rollen_liste()
    mitglieder = await d.mitglieder()
    await d.session.close()
    return rollen, mitglieder


def berechnen(rollen, mitglieder):
    ids = {}
    for r in rollen:
        ids.setdefault(r["name"], []).append(r["id"])
    fehlt = sorted({n for _, _, ns in POSTEN for n in ns if n not in ids})
    posten_ids = [(b, w, {i for n in ns for i in ids.get(n, [])}) for b, w, ns in POSTEN]
    out = []
    for m in mitglieder:
        r = set(m["rollen"])
        treffer = [(b, w) for b, w, ri in posten_ids if r & ri]
        if treffer:
            out.append({"konto_id": m["id"], "name": m["name"], "posten": treffer, "betrag": sum(w for _, w in treffer) * K})
    return sorted(out, key=lambda x: -x["betrag"]), fehlt


def main():
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    geld.einrichten(con)
    con.execute("CREATE TABLE IF NOT EXISTS gp_vergabe (konto_id TEXT PRIMARY KEY, name TEXT NOT NULL, betrag INTEGER NOT NULL, posten TEXT NOT NULL, zeit INTEGER NOT NULL)")
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion=?", (SPERRE,)).fetchone():
        sys.exit(f"Bereits ausgeführt (Protokoll „{SPERRE}“).")
    rollen, mitglieder = asyncio.run(laden())
    liste, fehlt = berechnen(rollen, mitglieder)
    if fehlt:
        print("ACHTUNG – Rollen nicht gefunden:", ", ".join(fehlt))
    for x in liste:
        print(f"{geld.mark(x['betrag']):>20}  {x['name'][:34]:34} " + " + ".join(f"{b} {w:,}".replace(",", ".") for b, w in x["posten"]))
    summe = sum(x["betrag"] for x in liste)
    print(f"\n{len(liste)} Personen, Summe {geld.mark(summe)}; Geldmenge heute {geld.mark(geld.geldmenge(con))}")
    if "--ausfuehren" not in sys.argv:
        print("Probelauf – mit --ausfuehren einzahlen.")
        return
    zb = geld.sonder(con, "zentralbank")
    for x in liste:
        privat = geld.privatkonto(con, x["konto_id"])
        zweck = "Einmaliges Grundpolster: " + ", ".join(b for b, _ in x["posten"])
        geld.buchen(con, zb["id"], privat["id"], x["betrag"], "startguthaben", zweck[:190], AMT, bezug="GRUNDPOLSTER")
        con.execute("INSERT INTO gp_vergabe (konto_id, name, betrag, posten, zeit) VALUES (?,?,?,?,?)",
                    (x["konto_id"], x["name"], x["betrag"], json.dumps(x["posten"], ensure_ascii=False), int(time.time())))
    geld.protokoll(con, AMT, SPERRE, f"{len(liste)} Personen, zusammen {geld.mark(summe)} (Geldschöpfung der Zentralbank)")
    con.commit()
    print("Eingezahlt. Geldmenge jetzt", geld.mark(geld.geldmenge(con)))


if __name__ == "__main__":
    main()
