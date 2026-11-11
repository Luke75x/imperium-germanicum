"""Gebühren für den Discord-Bot (nur lokal, Header X-Bot-Token): POST /intern-api/geld/gebuehr.

Der Bot (newsflash.py) lässt Zeitungsartikel 12 Kr (Einstellung „gebuehren“ → „zeitungsartikel“, in Heller, unter „Sätze festlegen“ in der RP-Leitungssicht änderbar)
kosten. JSON: {"aktion": "pruefen" | "buchen" | "erstatten", "konto_id": Discord-ID, "art": "zeitungsartikel", "zweck": Text, "bezug": Text, "betrag": Heller (nur erstatten)}.
Antwort: {"ok": bool, "betrag": Heller, "saldo": Heller, "fehler": Text}. Buchung Privatkonto → Reichskasse (Art „gebuehr“), Erstattung Reichskasse → Privatkonto
(Art „erstattung“). Die Gebühr braucht keine Bankkarte (der Auftrag kommt nicht vom Konto selbst); gesperrte Konten und fehlendes Guthaben lehnen ab.
"""
import secrets

from aiohttp import web

import geld
from geld import mark

BOT = {"id": "", "name": "Newsflash (Discord-Bot)"}


async def gebuehr(request):
    if not secrets.compare_digest(request.headers.get("X-Bot-Token", ""), request.app["discord"].bot_token):
        raise web.HTTPForbidden()
    d = await request.json()
    con = request.app["db"]
    art = str(d.get("art", ""))
    betrag = int(geld.einstellung(con, "gebuehren").get(art, 0) or 0)
    if art not in geld.GEBUEHR_NAMEN or not str(d.get("konto_id", "")).isdigit():
        return web.json_response({"ok": False, "fehler": "Ungültige Anfrage."}, status=400)
    p = geld.privatkonto(con, str(d["konto_id"]))
    antwort = {"ok": False, "betrag": betrag, "saldo": p["saldo"], "fehler": ""}
    zweck = " ".join(str(d.get("zweck", "")).split())[:150]
    bezug = str(d.get("bezug", ""))[:40]
    aktion = d.get("aktion")
    try:
        if aktion == "pruefen":
            if p["gesperrt"]:
                raise geld.Fehler("Dein Konto ist gesperrt.")
            if p["saldo"] < betrag:
                raise geld.Fehler(f"Dein Guthaben reicht nicht: Die Gebühr beträgt {mark(betrag)}, verfügbar sind {mark(p['saldo'])}.")
        elif aktion == "buchen":
            if betrag > 0:
                geld.buchen(con, p["id"], geld.sonder(con, "reichskasse")["id"], betrag, "gebuehr", f"{geld.GEBUEHR_NAMEN[art]}: {zweck}", BOT, bezug=bezug)
            con.commit()
            antwort["saldo"] = geld.konto(con, p["id"])["saldo"]
        elif aktion == "erstatten":
            summe = int(d.get("betrag", 0) or 0)
            if summe > 0:
                geld.buchen(con, geld.sonder(con, "reichskasse")["id"], p["id"], summe, "erstattung", f"Erstattung {geld.GEBUEHR_NAMEN[art]}: {zweck}", BOT, bezug=bezug, minus=True)
            con.commit()
            antwort["saldo"] = geld.konto(con, p["id"])["saldo"]
        else:
            return web.json_response({"ok": False, "fehler": "Unbekannte Aktion."}, status=400)
        antwort["ok"] = True
    except geld.Fehler as e:
        con.rollback()
        antwort["fehler"] = str(e)
    return web.json_response(antwort)


def einrichten(con):
    """Neue Gebührenart in eine schon gespeicherte Gebührenliste aufnehmen (sonst fehlt sie unter „Sätze festlegen“)."""
    import json
    r = con.execute("SELECT wert FROM gk_einstellungen WHERE schl='gebuehren'").fetchone()
    if r:
        w = json.loads(r["wert"])
        neu = {s: b for s, b in geld.VORGABEN["gebuehren"].items() if s not in w}
        if neu:
            w.update(neu)
            con.execute("UPDATE gk_einstellungen SET wert=? WHERE schl='gebuehren'", (json.dumps(w),))
            con.commit()


def registrieren(app):
    einrichten(app["db"])
    app.router.add_post("/intern-api/geld/gebuehr", gebuehr)
