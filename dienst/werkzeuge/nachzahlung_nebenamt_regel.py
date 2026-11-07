"""Einmalige Nachzahlung der allgemeinen Nebenamt-Zuschläge (besoldung.nebenaemter) für einen bereits gebuchten Lohnlauf – ohne Benachrichtigung.

Anlass (07.11.2026): Die Nebenamt-Regel kam nach dem Lohnlauf November 2026. Nachgezahlt wird je Person, die im Monat schon eine Abrechnung hat, jeder
Nebenamt-Posten, der nicht schon abgerechnet wurde (Ernst-Augusts bereits nachgezahlte Einzel-Zuschläge Kurfürst/Präsidium zählen als abgerechnet).
Abzüge: Lohnsteuer = Tarif(bisheriges Brutto + Nachzahlung) − Tarif(bisheriges Brutto), also zum heutigen Grenzsteuersatz; Sozialabgabe und Kronsteuer nach Satz
(Monarchen ohne Kronsteuer, Teile aus den Crown Estates ohne Kronsteuerbuchung). Je Zahlstelle eine Abrechnung (nachzahlung=1, Bezug NZ-<Monat>).
Sperre über gk_protokoll.

Aufruf:  .venv/bin/python werkzeuge/nachzahlung_nebenamt_regel.py [--db PFAD] [--periode 2026-11] [--ausfuehren]
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--db")
ap.add_argument("--periode", default="2026-11")
ap.add_argument("--ausfuehren", action="store_true")
a = ap.parse_args()
if a.db:
    config.DB = a.db

import db  # noqa: E402
import discord_api  # noqa: E402
import besoldung  # noqa: E402
import geld  # noqa: E402
import steuern  # noqa: E402
from geld import mark  # noqa: E402

SPERRE = "Nachzahlung Nebenamt-Regel"
K = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}
ALT = {"Zuschlag Kurfürst": "Kurfürst", "Zuschlag Präsidium des Reichstags": "Reichstag"}   # frühere Einzel-Zuschläge → Amtsbereich


def bereich_des_postens(bez, gs):
    if bez in ALT:
        return ALT[bez]
    if bez.startswith("Nebenamt ") and "(" in bez:
        schl = bez.rsplit("(", 1)[1].split(",")[0].strip()
        return besoldung.amtsbereich(schl) if schl in gs else None
    return None


async def main():
    con = db.verbinden()
    lauf = con.execute("SELECT * FROM bs_laeufe WHERE periode=?", (a.periode,)).fetchone()
    if not lauf:
        sys.exit(f"Kein Lohnlauf für {a.periode}.")
    if con.execute("SELECT 1 FROM gk_protokoll WHERE aktion=? AND text LIKE ?", (SPERRE, f"{a.periode}%")).fetchone():
        sys.exit("Bereits ausgeführt.")
    gs = besoldung.gruppen(con)
    zs = dict(besoldung.zahlstellen(con))
    satz_abg = float(geld.einstellung(con, "sozialabgabe")) / 100
    satz_kst = float(geld.einstellung(con, "kronsteuer")) / 100
    d = discord_api.Discord()
    await d.start()
    try:
        namen = {r["id"]: r["name"] for r in await d.rollen_liste()}
        mitglieder = await d.mitglieder()
    finally:
        await d.stop()
    plan = []
    for m in mitglieder:
        alt = con.execute("SELECT * FROM bs_abrechnungen WHERE konto_id=? AND periode=?", (m["id"], a.periode)).fetchall()
        if not alt:
            continue
        e = besoldung.einstufung(con, m["id"], m["rollen"], namen)
        if not e or not e[0]:
            continue
        bezahlt = {bereich_des_postens(p[0], gs) for r in alt for p in json.loads(r["posten"] or "[]")} - {None}
        neu = [(bez, betrag, zst) for bez, betrag, zst in besoldung.nebenaemter(con, m["id"], m["rollen"], e[0], namen)
               if bereich_des_postens(bez, gs) not in bezahlt]
        if not neu:
            continue
        alt_brutto = sum(r["brutto"] for r in alt)
        brutto = sum(b for _, b, _ in neu)
        lst = steuern.lohnsteuer(con, alt_brutto + brutto) - steuern.lohnsteuer(con, alt_brutto)   # Grenzsteuersatz nach heutigem Tarif
        monarch = m["id"] == config.KAISER_ID or bool(set(m["rollen"]) & set(besoldung.ROLLEN_MONARCH))
        abg = int(round(brutto * satz_abg))
        kst = 0 if monarch else int(round(brutto * satz_kst))
        name = geld.anzeigename(con, m["id"], m["name"])
        teile = {}
        for bez, betrag, zst in neu:
            teile.setdefault(zst, []).append([bez, betrag])
        rest = {"lst": lst, "abg": abg, "kst": kst}
        for i, (zst, posten) in enumerate(teile.items()):
            b = sum(p[1] for p in posten)
            if i == len(teile) - 1:
                l_, a_, k_ = rest["lst"], rest["abg"], rest["kst"]
            else:
                l_, a_, k_ = (int(round(v * b / brutto)) for v in (lst, abg, kst))
                rest["lst"] -= l_; rest["abg"] -= a_; rest["kst"] -= k_
            namen_p = ", ".join(p[0].split(" (")[0].replace("Nebenamt ", "") for p in posten)
            plan.append({"konto_id": m["id"], "name": name, "gruppe": "ZUS", "gruppe_name": "Nebenamt: " + namen_p, "quelle": "Nebenamt: " + namen_p,
                         "grundgehalt": 0, "zulage": b, "zulage_text": ", ".join(p[0] for p in posten), "brutto": b, "lohnsteuer": l_, "abgaben": a_,
                         "kronsteuer": k_, "netto": b - l_ - a_ - k_, "zahlstelle": zst, "posten": posten})
    for x in plan:
        print(f'{x["name"][:32]:32} {zs.get(x["zahlstelle"], x["zahlstelle"])[:28]:28} brutto {mark(x["brutto"]):>14} LSt {mark(x["lohnsteuer"]):>12} '
              f'SozA {mark(x["abgaben"]):>10} KrSt {mark(x["kronsteuer"]):>10} netto {mark(x["netto"]):>14} | {x["zulage_text"]}')
    print("Summe brutto", mark(sum(x["brutto"] for x in plan)), "netto", mark(sum(x["netto"] for x in plan)))
    if not a.ausfuehren or not plan:
        print("Probelauf – nichts gebucht.")
        return
    ids = []
    for x in plan:
        ids.append(besoldung._auszahlen(con, x, a.periode, lauf["id"], K, f"NZ-{a.periode}", zs, nachzahlung=True))
        con.execute("UPDATE bs_laeufe SET anzahl=anzahl+1, brutto=brutto+?, lohnsteuer=lohnsteuer+?, abgaben=abgaben+?, netto=netto+? WHERE id=?",
                    (x["brutto"], x["lohnsteuer"], x["abgaben"], x["netto"], lauf["id"]))
    geld.protokoll(con, K, SPERRE, f"{a.periode}: {len(plan)} Nachzahlungen, brutto {mark(sum(x['brutto'] for x in plan))} (ohne Benachrichtigung)")
    con.commit()
    print("Gebucht (keine DM):", ids)


asyncio.run(main())
