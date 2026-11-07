"""Einmaliger Lohnlauf für einen Monat außerhalb der Weboberfläche (07.11.2026: November 2026).

Berechnet die Besoldung wie die Seite „Lohnlauf“ (Discord-Rollen, Zuschläge, Kronsteuer), bucht sie (besoldung.lohnlauf_buchen) und schickt jedem
Empfänger die Nachricht mit Link zur Abrechnung samt PDF. Je Monat nur ein Lauf (bs_laeufe.periode eindeutig).
Aufruf: .venv/bin/python werkzeuge/lohnlauf_einmalig.py [DB-Pfad] [--ausfuehren] [--monat JJJJ-MM] [--ohne-dm]
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config  # noqa: E402

if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
    config.DB = sys.argv[1]
import besoldung  # noqa: E402
import db  # noqa: E402
import discord_api  # noqa: E402
import geld  # noqa: E402

AMT = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt"}


async def main():
    monat = sys.argv[sys.argv.index("--monat") + 1] if "--monat" in sys.argv else "2026-11"
    con = db.verbinden()
    con.execute("PRAGMA busy_timeout=10000")
    besoldung.einrichten(con)
    if con.execute("SELECT 1 FROM bs_laeufe WHERE periode=?", (monat,)).fetchone():
        sys.exit(f"Für {monat} wurde bereits ein Lohnlauf ausgeführt.")
    d = discord_api.Discord()
    await d.start()
    app = {"discord": d, "db": con}
    liste = await besoldung.berechnen(app, con)
    z = geld.mark
    print(f"{len(liste)} Abrechnungen für {len({x['konto_id'] for x in liste})} Personen · brutto {z(sum(x['brutto'] for x in liste))} · netto {z(sum(x['netto'] for x in liste))}")
    for r, bedarf in besoldung._bedarf(con, liste).values():
        r = geld.konto(con, r["id"])
        print(f"  Zahlstelle {r['name'][:42]:42} benötigt {z(bedarf):>20} · Guthaben {z(r['saldo']):>24} {'gedeckt' if r['saldo'] >= bedarf else 'NICHT GEDECKT – Gehälter werden einbehalten'}")
    if "--ausfuehren" not in sys.argv:
        print("Probelauf – mit --ausfuehren buchen.")
        await d.session.close()
        return
    lauf = besoldung.lohnlauf_buchen(con, liste, monat, AMT, False)
    l = con.execute("SELECT * FROM bs_laeufe WHERE id=?", (lauf,)).fetchone()
    print(f"Lohnlauf {monat} gebucht: {l['anzahl']} Abrechnungen, brutto {z(l['brutto'])}, netto {z(l['netto'])}, Lohnsteuer {z(l['lohnsteuer'])}, Sozialabgaben {z(l['abgaben'])}")
    if "--ohne-dm" not in sys.argv:
        n = 0
        for a in con.execute("SELECT * FROM bs_abrechnungen WHERE lauf=? AND nachzahlung=0", (lauf,)).fetchall():
            try:
                await d.dm(a["konto_id"], besoldung.dm_text(a))
                n += 1
            except Exception as e:
                print("  DM fehlgeschlagen:", a["name"], e)
        print(f"{n} Nachrichten verschickt.")
    await d.session.close()


if __name__ == "__main__":
    asyncio.run(main())
