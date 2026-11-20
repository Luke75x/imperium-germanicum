"""Teilstaat-Wappen: Dateien wappen_staaten/<Karten-ID>.png (z. B. s6.png), Route /schatzamt/wappen/<sid>.png (teilstaat.py). Siehe Memory teilstaat-wappen.
klein() = Mini-Wappen für Tabellenzeilen; gross() = Wappen neben Überschriften (siehe teilstaat.kopf_mit_wappen)."""
import html
import os

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wappen_staaten")
URL = "/schatzamt/wappen/"


def vorhanden(sid):
    return bool(sid) and str(sid).isalnum() and os.path.isfile(os.path.join(DIR, f"{sid}.png"))


def klein(sid, name="", hoehe=18):
    """<img> in Tabellenhöhe (leer, wenn es kein Wappen gibt). sid: Karten-ID „s6“ oder Zielschlüssel „ts-s6“."""
    sid = str(sid or "")
    if sid.startswith("ts-"):
        sid = sid[3:]
    if not vorhanden(sid):
        return ""
    return (f'<img src="{URL}{sid}.png" alt="" title="Wappen {html.escape(name)}" loading="lazy" '
            f'style="height:{hoehe}px;width:auto;max-width:{hoehe}px;object-fit:contain;vertical-align:-4px;margin-right:7px">')
