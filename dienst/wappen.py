"""Teilstaat-Wappen: Dateien wappen_staaten/<Karten-ID>.png (z. B. s6.png), Route /schatzamt/wappen/<sid>.png (teilstaat.py). Siehe Memory teilstaat-wappen.
klein() = Mini-Wappen für Tabellenzeilen; gross() = Wappen neben Überschriften (siehe teilstaat.kopf_mit_wappen)."""
import html
import os

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wappen_staaten")
URL = "/schatzamt/wappen/"
ALIAS = {"s2": "reich"}   # die Reichsunmittelbaren Territorien (Karten-ID s2) sind das Reich: Reichswappen


def datei(sid):
    sid = str(sid or "")
    if sid.startswith("ts-"):
        sid = sid[3:]
    return ALIAS.get(sid, sid)


def vorhanden(sid):
    sid = datei(sid)
    return bool(sid) and str(sid).isalnum() and os.path.isfile(os.path.join(DIR, f"{sid}.png"))


def klein(sid, name="", hoehe=18):
    """<img> in Tabellenhöhe (leer, wenn es kein Wappen gibt). sid: Karten-ID „s6“ oder Zielschlüssel „ts-s6“."""
    sid = datei(sid)
    if not vorhanden(sid):
        return ""
    return (f'<img src="{URL}{sid}.png" alt="" title="Wappen {html.escape(name)}" loading="lazy" '
            f'style="height:{hoehe}px;width:auto;max-width:{hoehe}px;object-fit:contain;vertical-align:-4px;margin-right:7px">')


def kasse(r, hoehe=20):
    """Icon einer Kasse (Konto-Zeile r): Teilstaats-/Verteidigungskassen = Wappen, Reichskasse und Reichsverteidigung = Reichswappen, Behördenkassen = Behördenlogo."""
    stelle = (r["stelle"] or "") if r["stelle"] is not None else ""
    if stelle[:3] in ("ts-", "vt-"):
        return klein(stelle, r["name"], hoehe)
    if stelle in ("reichskasse", "verteidigung"):
        return klein("reich", r["name"], hoehe)
    if r["art"] == "behoerde" and stelle:
        import amt
        for n in (stelle, {"kanzlei": "kanzler"}.get(stelle, stelle)):
            if os.path.isfile(os.path.join(amt.LOGO_ORDNER, n + "-kurz.png")):
                return (f'<img src="{amt.BASIS}logo/{n}-kurz.png" alt="" loading="lazy" title="{html.escape(r["name"])}" '
                        f'style="height:{hoehe}px;width:auto;max-width:{hoehe + 6}px;object-fit:contain;vertical-align:-4px;margin-right:7px">')
    return ""
