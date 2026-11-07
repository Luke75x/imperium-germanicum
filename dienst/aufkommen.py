"""Steueraufkommen der (nicht spielenden, simulierten) Bevölkerung – laufende Staatseinnahmen nach Wirtschaftsleistung.

Jeden Monat zahlt die Bevölkerung jedes Teilstaats Steuern: BIP (Mio. €, karte_daten/bip.json) ÷ 12 × Steuerquote × Spielmaßstab.
Verteilung wie in einem Bundesstaat: Reichsanteil (Vorgabe 43 % ≈ Bund + EU) an die Reichskasse, Rest (57 % ≈ Länder + Gemeinden)
an die Staatskasse des Teilstaats; in den unmittelbaren Reichsgebieten (geld.REICHSGEBIETE) erhält das Reich beides.
Vorgaben angelehnt an Deutschland: Steuerquote 24 % des BIP, Maßstab 1,35 M je Mio. € echtem Steueraufkommen (so deckt der
Reichsanteil die Besoldung mit kleinem Überschuss). Gegenkonto ist das Sonderkonto „volkswirtschaft“ (außerhalb des Geldumlaufs).
Läuft automatisch einmal je Kalendermonat (Hintergrundaufgabe, abschaltbar), sonst über /schatzamt/amt/aufkommen/.
Tabellen: ak_laeufe (je Monat eindeutig), ak_posten (je Teilstaat).
"""
import asyncio
import json
import logging
import os
import time
from datetime import date

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark

esc = amt.esc
PFAD = sa.PFAD
log = logging.getLogger("aufkommen")
DATEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "karte_daten")
SYSTEM = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt (automatisch)"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ak_laeufe (id INTEGER PRIMARY KEY AUTOINCREMENT, periode TEXT NOT NULL UNIQUE, summe INTEGER NOT NULL,
    reich INTEGER NOT NULL, laender INTEGER NOT NULL, parameter TEXT NOT NULL, zeit INTEGER NOT NULL, autor_name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ak_posten (id INTEGER PRIMARY KEY AUTOINCREMENT, lauf INTEGER NOT NULL, staat TEXT NOT NULL, name TEXT NOT NULL,
    bip REAL NOT NULL, summe INTEGER NOT NULL, reich INTEGER NOT NULL, land INTEGER NOT NULL);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def _zahl(s):
    return float(str(s).replace(",", "."))


def staaten_bip(con):
    """[(Teilstaat, BIP Mio. €, Einwohner)] der aktuellen Reichskarte."""
    import karte
    a = karte.aktuell(con)
    bip = json.load(open(os.path.join(DATEN, "bip.json")))
    bev = json.load(open(os.path.join(DATEN, "bevoelkerung.json")))
    summe = {}
    for g, sid in a["stand"]["gebiete"].items():
        x = summe.setdefault(sid, [0.0, 0])
        x[0] += bip.get(g, [0])[0]
        x[1] += bev.get(g, [0])[0]
    return [(s, summe.get(s["id"], [0, 0])[0], summe.get(s["id"], [0, 0])[1]) for s in a["stand"]["staaten"]]


def berechnen(con, p=None):
    """Monatliches Aufkommen je Teilstaat: [{staat, name, bip, summe, reich, land, kasse}] (Pfennig)."""
    p = p or geld.einstellung(con, "aufkommen")
    quote, massstab, anteil = float(p["steuerquote"]) / 100, _zahl(p["massstab"]), float(p["reichsanteil"]) / 100
    out = []
    for s, bip, ew in staaten_bip(con):
        summe = int(round(bip / 12 * quote * massstab * 100))
        reich_direkt = s["id"] in geld.REICHSGEBIETE
        reich = summe if reich_direkt else int(round(summe * anteil))
        out.append({"staat": s["id"], "name": s["name"], "bip": bip, "ew": ew, "summe": summe, "reich": reich, "land": summe - reich,
                    "kasse": None if reich_direkt else geld.stellenkonto(con, "ts-" + s["id"])})
    return sorted(out, key=lambda x: -x["summe"])


def ausfuehren(con, periode, k):
    """Bucht das Aufkommen eines Monats (einmalig je Monat). Gibt die Lauf-ID zurück oder None, wenn schon gebucht."""
    if con.execute("SELECT 1 FROM ak_laeufe WHERE periode=?", (periode,)).fetchone():
        return None
    geld.teilstaaten_sichern(con)
    p = geld.einstellung(con, "aufkommen")
    liste = berechnen(con, p)
    vw, kasse = geld.sonder(con, "volkswirtschaft"), geld.sonder(con, "reichskasse")
    cur = con.execute("INSERT INTO ak_laeufe (periode, summe, reich, laender, parameter, zeit, autor_name) VALUES (?,?,?,?,?,?,?)",
                      (periode, sum(x["summe"] for x in liste), sum(x["reich"] for x in liste), sum(x["land"] for x in liste),
                       json.dumps(p), int(time.time()), k["name"]))
    lauf, bezug, monat = cur.lastrowid, f"AK-{periode}", sa._monatsname(periode)
    for x in liste:
        if x["reich"]:
            geld.buchen(con, vw["id"], kasse["id"], x["reich"], "steueraufkommen", f"Steueraufkommen {monat}: {x['name']} (Reichsanteil)", k, bezug=bezug)
        if x["land"] and x["kasse"]:
            geld.buchen(con, vw["id"], x["kasse"]["id"], x["land"], "steueraufkommen", f"Steueraufkommen {monat}: {x['name']} (Landesanteil)", k, bezug=bezug)
        con.execute("INSERT INTO ak_posten (lauf, staat, name, bip, summe, reich, land) VALUES (?,?,?,?,?,?,?)",
                    (lauf, x["staat"], x["name"], x["bip"], x["summe"], x["reich"], x["land"]))
    geld.protokoll(con, k, "Steueraufkommen", f"{monat}: {mark(sum(x['summe'] for x in liste))} "
                                              f"(Reich {mark(sum(x['reich'] for x in liste))}, Teilstaaten {mark(sum(x['land'] for x in liste))})")
    con.commit()
    return lauf


async def automatik(app):
    """Hintergrund: einmal je Kalendermonat automatisch buchen (Einstellung „automatisch“)."""
    await asyncio.sleep(20)
    while True:
        try:
            con = app["db"]
            if geld.einstellung(con, "aufkommen").get("automatisch"):
                periode = date.today().strftime("%Y-%m")
                if ausfuehren(con, periode, SYSTEM):
                    log.info("Steueraufkommen %s automatisch gebucht", periode)
        except Exception:
            log.exception("Steueraufkommen: automatischer Lauf fehlgeschlagen")
        await asyncio.sleep(1800)


# ---------------------------------------------------------------- Seiten

def prognose_html(con, liste, besoldung_netto):
    reich = sum(x["reich"] for x in liste)
    kasse = geld.sonder(con, "reichskasse")["saldo"]
    saldo = reich - besoldung_netto
    return (f'<div class="kennzahlen"><div><b>{mark(sum(x["summe"] for x in liste))}</b>Aufkommen je Monat</div>'
            f'<div><b>{mark(reich)}</b>davon Reich</div><div><b>{mark(sum(x["land"] for x in liste))}</b>davon Teilstaaten</div>'
            f'<div><b>{mark(besoldung_netto)}</b>Besoldung (Abfluss) je Monat</div>'
            f'<div><b>{mark(saldo)}</b>{"Überschuss" if saldo >= 0 else "Defizit"} des Reiches je Monat</div>'
            f'<div><b>{mark(kasse)}</b>Reichskasse heute</div></div>')


@sa.seite("leitung")
async def seite(request, k):
    import besoldung
    con = request.app["db"]
    p = geld.einstellung(con, "aufkommen")
    liste = berechnen(con, p)
    try:
        bes = await besoldung.berechnen(request.app, con)
        abfluss = sum(x["netto"] + x["abgaben"] for x in bes)
    except Exception:
        abfluss = 0
    periode = date.today().strftime("%Y-%m")
    gebucht = con.execute("SELECT * FROM ak_laeufe WHERE periode=?", (periode,)).fetchone()
    knopf = (f'<p class="hinweis">Das Aufkommen für {esc(sa._monatsname(periode))} ist gebucht.</p>' if gebucht else
             f'<form method="post" action="{PFAD}amt/aufkommen/buchen">{amt.csrf_feld(request)}<div class="aktionen">'
             f'<button class="btn" type="submit">{amt.ic("check")}Aufkommen {esc(sa._monatsname(periode))} jetzt buchen</button></div></form>')
    zeilen = [(esc(x["name"]), f'{x["bip"]:,.0f}'.replace(",", "."), f'{(x["bip"] * 1e6 / x["ew"] if x["ew"] else 0):,.0f} €'.replace(",", "."),
               mark(x["summe"]), mark(x["reich"]), mark(x["land"]) if x["kasse"] else "– (Reichsgebiet)") for x in liste]
    laeufe = con.execute("SELECT * FROM ak_laeufe ORDER BY id DESC LIMIT 24").fetchall()
    c = amt.csrf_feld(request)
    inhalt = (f'<h1>{amt.ic("chart-column")} Steueraufkommen der Bevölkerung</h1>{amt.meldung(request)}'
              '<p class="az">Laufende Steuereinnahmen aus der Wirtschaftsleistung der Bevölkerung (BIP je Teilstaat, Eurostat). '
              'Monatlich: BIP ÷ 12 × Steuerquote × Spielmaßstab; Aufteilung zwischen Reich und Teilstaat wie in einem Bundesstaat.</p>'
              + prognose_html(con, liste, abfluss) + knopf
              + f'<h2>Stellschrauben</h2><form class="sa-formular" method="post" action="{PFAD}amt/aufkommen/">{c}<div class="zeilen">'
              f'<div><label for="q">Steuerquote (% des BIP)</label><input type="text" id="q" name="steuerquote" value="{esc(str(p["steuerquote"]))}"></div>'
              f'<div><label for="m">Spielmaßstab (M je Mio. € Aufkommen)</label><input type="text" id="m" name="massstab" value="{esc(str(p["massstab"]))}"></div>'
              f'<div><label for="r">Reichsanteil (%)</label><input type="text" id="r" name="reichsanteil" value="{esc(str(p["reichsanteil"]))}"></div></div>'
              f'<label><input type="checkbox" name="automatisch" value="1"{" checked" if p.get("automatisch") else ""}> Jeden Monat automatisch buchen</label>'
              f'<div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("check")}Speichern</button></div></form>'
              '<p class="sa-hinweis">Richtwerte Deutschland: Steuerquote rund 24 % des BIP; Verteilung etwa 43 % Bund/EU, 57 % Länder und Gemeinden. '
              'Eine höhere Steuerquote oder ein größerer Maßstab erhöhen alle Einnahmen; der Reichsanteil verschiebt Geld zwischen Reich und Teilstaaten.</p>'
              '<h2>Aufkommen je Teilstaat (Monat)</h2>' + amt.tabelle(["Teilstaat", "BIP (Mio. €)", "BIP je Einwohner", "Aufkommen", "Reich", "Teilstaat"], zeilen)
              + '<h2>Gebuchte Monate</h2>' + amt.tabelle(["Monat", "Aufkommen", "Reich", "Teilstaaten", "Gebucht"],
                                                         [(esc(sa._monatsname(l["periode"])), mark(l["summe"]), mark(l["reich"]), mark(l["laender"]),
                                                           f'{amt._zeit(l["zeit"])} · {esc(l["autor_name"])}') for l in laeufe], "Noch kein Monat gebucht."))
    return sa.ant(request, k, "Steueraufkommen", "sa-amt-aufkommen", inhalt)


async def speichern(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    q, r = geld.prozent_lesen(form.get("steuerquote")), geld.prozent_lesen(form.get("reichsanteil"))
    try:
        m = _zahl(form.get("massstab", ""))
    except ValueError:
        m = -1
    if q is None or r is None or not 0 < m <= 1000:
        sa.weiter(f"{PFAD}amt/aufkommen/", "Bitte gültige Werte angeben.", True)
    ganz = lambda x: int(x) if x == int(x) else x
    geld.einstellung_setzen(con, "aufkommen", {"steuerquote": ganz(q), "massstab": f"{m:g}".replace(".", ","), "reichsanteil": ganz(r),
                                                "automatisch": form.get("automatisch") == "1"}, k)
    con.commit()
    sa.weiter(f"{PFAD}amt/aufkommen/", "Stellschrauben gespeichert; sie gelten ab dem nächsten gebuchten Monat.")


async def buchen(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    await sa.formular(request)
    con = request.app["db"]
    periode = date.today().strftime("%Y-%m")
    lauf = ausfuehren(con, periode, k)
    sa.weiter(f"{PFAD}amt/aufkommen/", f"Steueraufkommen {sa._monatsname(periode)} gebucht." if lauf else "Dieser Monat ist bereits gebucht.", not lauf)


def finanzen_html(con):
    """Für die öffentliche Seite „Reichsfinanzen“: letzter gebuchter Monat je Teilstaat."""
    l = con.execute("SELECT * FROM ak_laeufe ORDER BY id DESC LIMIT 1").fetchone()
    if not l:
        return ""
    posten = con.execute("SELECT * FROM ak_posten WHERE lauf=? ORDER BY summe DESC", (l["id"],)).fetchall()
    return (f'<h2>Steueraufkommen der Bevölkerung · {esc(sa._monatsname(l["periode"]))}</h2>'
            f'<p class="az">Zusammen {mark(l["summe"])}: Reich {mark(l["reich"])}, Teilstaaten {mark(l["laender"])}</p>'
            + amt.tabelle(["Teilstaat", "Aufkommen", "an das Reich", "an den Teilstaat"],
                          [(esc(x["name"]), mark(x["summe"]), mark(x["reich"]), mark(x["land"]) if x["land"] else "–") for x in posten]))


def registrieren(app):
    einrichten(app["db"])
    geld.einrichten(app["db"])   # Sonderkonto „volkswirtschaft“
    app.router.add_get(PFAD + "amt/aufkommen/", seite)
    app.router.add_post(PFAD + "amt/aufkommen/", speichern)
    app.router.add_post(PFAD + "amt/aufkommen/buchen", buchen)

    async def start(app_):
        app_["aufkommen_aufgabe"] = asyncio.get_event_loop().create_task(automatik(app_))

    async def stopp(app_):
        app_["aufkommen_aufgabe"].cancel()
    app.on_startup.append(start)
    app.on_cleanup.append(stopp)
