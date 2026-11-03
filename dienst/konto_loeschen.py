"""Löscht ein Konto samt Sitzungen (Löschwunsch laut Datenschutzerklärung).

    .venv/bin/python konto_loeschen.py <discord-nutzer-id>
"""
import sys

import db

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    n = db.konto_loeschen(db.verbinden(), sys.argv[1])
    print("Konto gelöscht." if n else "Kein Konto mit dieser ID.")
