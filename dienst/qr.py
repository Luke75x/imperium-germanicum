"""QR-Codes für Pässe und amtliche Dokumente (Bibliothek segno, reines Python).

Pässe und Meldebescheinigungen tragen Kurzlinks …/p/<Passnummer> bzw. …/p/<BA-Aktenzeichen> (nginx leitet /p/ an den Dienst,
passpruefung_qr.py leitet weiter auf die Prüfseite). Sonstige PDFs verlinken direkt auf ihre Seite in der Amtsseite.
"""
import io

import segno

import config


def kurzlink(code):
    return f"{config.SITE_URL}/p/{code}"


def svg(text, groesse_mm, farbe="#000", fehler="m"):
    """QR-Code als Inline-SVG (feste Größe in mm, ohne Hintergrund, 1 Modul Rand)."""
    q = segno.make(text, error=fehler, micro=False)
    buf = io.BytesIO()
    q.save(buf, kind="svg", xmldecl=False, svgns=True, nl=False, dark=farbe, light=None, border=1, omitsize=True, svgclass="qr-svg")
    return buf.getvalue().decode().replace("<svg ", f'<svg style="width:{groesse_mm}mm;height:{groesse_mm}mm;display:block" ', 1)
