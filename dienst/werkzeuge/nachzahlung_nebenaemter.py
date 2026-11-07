"""Einmalige Nachzahlung der Nebenamt-Zuschläge (Kurfürst, Präsidium des Reichstags) für einen bereits gebuchten Lohnlauf.

Anlass (07.11.2026): Die Zuschläge wurden nach dem Lohnlauf November 2026 eingeführt; SKM Ernst-August VI. erhielt im November nur S1.
Berechnet je Person die heutigen Bezüge (berechnen_einzeln) und zahlt nur die Zuschläge „Kurfürst“ / „Präsidium des Reichstags“ nach, die im Monat
noch nicht abgerechnet wurden. Abzüge als Differenz: Lohnsteuer/Sozialabgabe/Kronsteuer auf die Gesamtbezüge minus das bereits Abgezogene.
Gebucht als Nachzahlung (bs_abrechnungen.nachzahlung=1, Bezug NZ-<Monat>) mit DM an den Empfänger. Sperre über gk_protokoll.

Aufruf:  .venv/bin/python werkzeuge/nachzahlung_nebenaemter.py [--db PFAD] [--periode 2026-11] [--konto ID ...] [--ausfuehren]
Ohne --ausfuehren nur Probelauf.
"""
import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--db")
ap.add_argument("--periode", default="2026-11")
ap.add_argument("--konto", nargs="*", default=["204339783999160321"])
ap.add_argument("--ausfuehren", action="store_true")
ap.add_argument("--ohne-dm", action="store_true")
a = ap.parse_args()
if a.db:
    config.DB = a.db

import db  # noqa: E402
import discord_api  # noqa: E402
import besoldung  # noqa: E402
import geld  # noqa: E402
from geld import mark  # noqa: E402

ZUSCHLAEGE = ("Kurfürst", "Präsidium des Reichstags")
SPERRE = "Nachzahlung Nebenamt-Zuschläge"
K = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}


async def main():
    con = db.verbinden()
    lauf = con.execute("SELECT * FROM bs_laeufe WHERE periode=?", (a.periode,)).fetchone()
    if not lauf:
        sys.exit(f"Kein Lohnlauf für {a.periode}.")
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion=? AND text LIKE ?", (SPERRE, f"%{a.periode}%")).fetchone():
        sys.exit("Bereits ausgeführt.")
    d = discord_api.Discord()
    await d.start()
    try:
        namen = {r["id"]: r["name"] for r in await d.rollen_liste()}
        mitglieder = {m["id"]: m for m in await d.mitglieder()}
        zs = dict(besoldung.zahlstellen(con))
        plan = []
        for kid in a.konto:
            m = mitglieder[kid]
            teile = besoldung.berechnen_einzeln(con, kid, geld.anzeigename(con, kid, m["name"]), m["rollen"], namen)
            alt = con.execute("SELECT * FROM bs_abrechnungen WHERE konto_id=? AND periode=?", (kid, a.periode)).fetchall()
            schon = {p[0] for r in alt for p in json.loads(r["posten"] or "[]")}
            nach = [p for t in teile for p in t["posten"] if any(p[0] == "Zuschlag " + z for z in ZUSCHLAEGE) and p[0] not in schon]
            if not nach:
                print(m["name"], ": nichts nachzuzahlen")
                continue
            ges = sum(t["brutto"] for t in teile)
            ges_lst, ges_abg, ges_kst = (sum(t[f] for t in teile) for f in ("lohnsteuer", "abgaben", "kronsteuer"))
            alt_lst, alt_abg, alt_kst = (sum(r[f] for r in alt) for f in ("lohnsteuer", "abgaben", "kronsteuer"))
            brutto = sum(p[1] for p in nach)
            lst, abg, kst = ges_lst - alt_lst, ges_abg - alt_abg, ges_kst - alt_kst
            # nur der Anteil der Abzüge, der auf die nachgezahlten Zuschläge entfällt (falls sich sonst etwas geändert hat, nicht mitnehmen)
            neu_brutto = ges - sum(r["brutto"] for r in alt)
            if neu_brutto != brutto and neu_brutto > 0:
                f = brutto / neu_brutto
                lst, abg, kst = int(round(lst * f)), int(round(abg * f)), int(round(kst * f))
            x = {"konto_id": kid, "name": teile[0]["name"], "gruppe": "ZUS", "gruppe_name": ", ".join(p[0].replace("Zuschlag ", "") for p in nach),
                 "quelle": "Amtsposition: " + ", ".join(p[0].replace("Zuschlag ", "") for p in nach), "grundgehalt": 0, "zulage": brutto,
                 "zulage_text": ", ".join(p[0] for p in nach), "brutto": brutto, "lohnsteuer": lst, "abgaben": abg, "kronsteuer": kst,
                 "netto": brutto - lst - abg - kst, "zahlstelle": "reichskasse", "posten": nach}
            plan.append(x)
            print(f'{x["name"]}: brutto {mark(brutto)} ({x["zulage_text"]}), Lohnsteuer {mark(lst)}, Sozialabgabe {mark(abg)}, '
                  f'Kronsteuer {mark(kst)}, netto {mark(x["netto"])}')
        if not a.ausfuehren or not plan:
            print("Probelauf – nichts gebucht." if plan else "")
            return
        nz = []
        for x in plan:
            aid = besoldung._auszahlen(con, x, a.periode, lauf["id"], K, f"NZ-{a.periode}", zs, nachzahlung=True)
            con.execute("UPDATE bs_laeufe SET anzahl=anzahl+1, brutto=brutto+?, lohnsteuer=lohnsteuer+?, abgaben=abgaben+?, netto=netto+? WHERE id=?",
                        (x["brutto"], x["lohnsteuer"], x["abgaben"], x["netto"], lauf["id"]))
            nz.append((x, aid))
        geld.protokoll(con, K, SPERRE, f"{a.periode}: " + "; ".join(f'{x["name"]} netto {mark(x["netto"])}' for x, _ in nz))
        con.commit()
        print("Gebucht:", [aid for _, aid in nz])
        if not a.ohne_dm:
            for x, aid in nz:
                await d.dm(x["konto_id"], f"Nachzahlung für {besoldung._monat(a.periode)}: Zuschläge {x['gruppe_name']} – {mark(x['brutto'])} brutto, "
                                          f"{mark(x['netto'])} netto aus der Reichskasse auf dein Konto.\n"
                                          f"{config.SITE_URL}{besoldung.PFAD}gehalt/{aid}/")
    finally:
        await d.stop()


asyncio.run(main())
