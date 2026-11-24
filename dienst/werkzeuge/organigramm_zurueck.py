"""Ein Organigramm auf eine frühere Version zurücksetzen (legt sie als neue, jüngste Version an; nichts wird gelöscht) und das Bild neu erzeugen.

    .venv/bin/python werkzeuge/organigramm_zurueck.py <name> <version-id>
    z. B.  .venv/bin/python werkzeuge/organigramm_zurueck.py staatsaufbau 17   (Stand vor der Reichsregierung nach Charta VI, 24.11.2026)

Versionen anzeigen:  .venv/bin/python werkzeuge/organigramm_zurueck.py <name>
"""
import asyncio
import os
import sqlite3
import sys
import time

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WURZEL)
os.chdir(WURZEL)
import bild  # noqa: E402
import organigramme  # noqa: E402

con = sqlite3.connect(os.path.join(WURZEL, "daten", "dienst.db"))
name = sys.argv[1]
if len(sys.argv) < 3:
    for i, z, a, b in con.execute("SELECT id, zeit, autor_name, bemerkung FROM organigramm_versionen WHERE name=? ORDER BY id DESC LIMIT 15", (name,)):
        print(i, time.strftime("%d.%m.%Y %H:%M", time.localtime(z)), a, "–", b)
    sys.exit()
ziel = int(sys.argv[2])
row = con.execute("SELECT stand FROM organigramm_versionen WHERE name=? AND id=?", (name, ziel)).fetchone()
if not row:
    sys.exit("Version nicht gefunden.")
con.execute("INSERT INTO organigramm_versionen (name, stand, bemerkung, autor_id, autor_name, zeit) VALUES (?,?,?,?,?,?)",
            (name, row[0], f"Zurückgesetzt auf Version {ziel}", None, "Systempflege", int(time.time())))
con.commit()
asyncio.run(bild.erzeugen(name, organigramme.ORGANIGRAMME[name]["pfad"]))
print(f"{name}: Version {ziel} ist wieder aktiv, Bild neu erzeugt.")
