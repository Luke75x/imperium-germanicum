"""Staatshaushalt der simulierten Bevölkerung im Echtmaßstab (1 Krone = Wechselkurs €, Vorgabe 1,21 €).

Einnahmen: Jeden Monat zahlt die Bevölkerung jedes Teilstaats Steuern: BIP (Mio. €, karte_daten/bip.json) ÷ 12 × Steuerquote (24 %),
umgerechnet in Kronen zum Wechselkurs. Verteilung wie in einem Bundesstaat: Reichsanteil (43 % ≈ Bund + EU) an die Reichskasse,
Rest (57 % ≈ Länder + Gemeinden) an die Staatskasse; die Freien Reichsgebiete (geld.ist_reichsgebiet) sind kein Teilstaat, sondern das
Reich selbst – dort erhält die Reichskasse alles.
Ausgaben: Pflichtausgaben (Soziales, Verteidigung, Infrastruktur, Bildung, Verwaltung der nicht spielenden Bevölkerung) als Quote der
Einnahmen (Vorgabe 97 %) gehen zurück an die Volkswirtschaft; die übrigen 3 % sind der frei verfügbare Spielraum für Reich und Landesherren.
Gegenkonto ist das Sonderkonto „volkswirtschaft“ (außerhalb des Geldumlaufs). Läuft automatisch einmal je Kalendermonat
(Hintergrundaufgabe, abschaltbar), sonst über /schatzamt/amt/aufkommen/. Tabellen: ak_laeufe (je Monat eindeutig), ak_posten (je Teilstaat).
nachbuchen() bringt einen schon gebuchten Monat auf die aktuellen Sätze (Differenzbuchungen; z. B. Umstellung auf den Echtmaßstab).
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
    for tab, spalte in (("ak_laeufe", "ausgaben"), ("ak_posten", "ausgaben_reich"), ("ak_posten", "ausgaben_land")):
        if spalte not in {r[1] for r in con.execute(f"PRAGMA table_info({tab})")}:
            con.execute(f"ALTER TABLE {tab} ADD COLUMN {spalte} INTEGER NOT NULL DEFAULT 0")
    con.commit()


def kronen_je_mio_euro(con):
    return 1e6 / geld.wechselkurs(con)


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
    """Monatlicher Haushalt je Teilstaat (Heller): Einnahmen summe/reich/land und Pflichtausgaben ausgaben_reich/ausgaben_land."""
    p = p or geld.einstellung(con, "aufkommen")
    quote, anteil, aq = float(p["steuerquote"]) / 100, float(p["reichsanteil"]) / 100, float(p.get("ausgabenquote", 97)) / 100
    kr = kronen_je_mio_euro(con)
    out = []
    for s, bip, ew in staaten_bip(con):
        summe = int(round(bip / 12 * quote * kr * 100))
        reich_direkt = geld.ist_reichsgebiet(s)
        reich = summe if reich_direkt else int(round(summe * anteil))
        land = summe - reich
        out.append({"staat": s["id"], "name": s["name"], "reichsgebiet": reich_direkt, "bip": bip, "ew": ew, "summe": summe, "reich": reich, "land": land,
                    "ausgaben_reich": int(round(reich * aq)), "ausgaben_land": int(round(land * aq)),
                    "kasse": None if reich_direkt else geld.stellenkonto(con, "ts-" + s["id"])})
    return sorted(out, key=lambda x: -x["summe"])


def _buchen_posten(con, x, k, monat, bezug, faktor=1):
    """Bucht Einnahmen und Pflichtausgaben eines Teilstaats (faktor −1 = Gegenbuchung bei Differenzen)."""
    vw, kasse = geld.sonder(con, "volkswirtschaft"), geld.sonder(con, "reichskasse")
    paare = [(kasse, x["reich"], x["ausgaben_reich"], "Reich" if x.get("reichsgebiet") else "Reichsanteil")]
    if x["kasse"]:
        paare.append((x["kasse"], x["land"], x["ausgaben_land"], "Landesanteil"))
    for ziel, ein, aus, was in paare:
        for betrag, art, text, von, an in ((ein, "steueraufkommen", f"Steueraufkommen {monat}: {x['name']} ({was})", vw, ziel),
                                           (aus, "staatsausgaben", f"Pflichtausgaben {monat}: {x['name']} ({was})", ziel, vw)):
            if betrag > 0:
                v, a = (von, an) if faktor > 0 else (an, von)
                geld.buchen(con, v["id"], a["id"], betrag, art, text + ("" if faktor > 0 else " – Berichtigung"), k, bezug=bezug, minus=True)


def ausfuehren(con, periode, k):
    """Bucht Einnahmen und Pflichtausgaben eines Monats (einmalig je Monat). Gibt die Lauf-ID zurück oder None, wenn schon gebucht."""
    if con.execute("SELECT 1 FROM ak_laeufe WHERE periode=?", (periode,)).fetchone():
        return None
    geld.teilstaaten_sichern(con)
    p = dict(geld.einstellung(con, "aufkommen"), wechselkurs=geld.einstellung(con, "wechselkurs"))
    liste = berechnen(con, p)
    cur = con.execute("INSERT INTO ak_laeufe (periode, summe, reich, laender, ausgaben, parameter, zeit, autor_name) VALUES (?,?,?,?,?,?,?,?)",
                      (periode, sum(x["summe"] for x in liste), sum(x["reich"] for x in liste), sum(x["land"] for x in liste),
                       sum(x["ausgaben_reich"] + x["ausgaben_land"] for x in liste), json.dumps(p), int(time.time()), k["name"]))
    lauf, monat = cur.lastrowid, sa._monatsname(periode)
    for x in liste:
        _buchen_posten(con, x, k, monat, f"AK-{periode}")
        con.execute("INSERT INTO ak_posten (lauf, staat, name, bip, summe, reich, land, ausgaben_reich, ausgaben_land) VALUES (?,?,?,?,?,?,?,?,?)",
                    (lauf, x["staat"], x["name"], x["bip"], x["summe"], x["reich"], x["land"], x["ausgaben_reich"], x["ausgaben_land"]))
    geld.protokoll(con, k, "Staatshaushalt", f"{monat}: Einnahmen {mark(sum(x['summe'] for x in liste))}, Pflichtausgaben "
                                             f"{mark(sum(x['ausgaben_reich'] + x['ausgaben_land'] for x in liste))}")
    con.commit()
    return lauf


def nachbuchen(con, periode, k):
    """Bringt einen bereits gebuchten Monat auf die aktuellen Sätze: bucht je Teilstaat die Differenz zu den gespeicherten Posten."""
    l = con.execute("SELECT * FROM ak_laeufe WHERE periode=?", (periode,)).fetchone()
    if not l:
        return ausfuehren(con, periode, k)
    alt = {r["staat"]: r for r in con.execute("SELECT * FROM ak_posten WHERE lauf=?", (l["id"],))}
    p = dict(geld.einstellung(con, "aufkommen"), wechselkurs=geld.einstellung(con, "wechselkurs"))
    liste = berechnen(con, p)
    monat = sa._monatsname(periode)
    for x in liste:
        a = alt.get(x["staat"])
        d = dict(x)
        for f in ("reich", "land", "ausgaben_reich", "ausgaben_land"):
            d[f] = x[f] - (a[f] if a else 0)
        plus = {f: max(0, d[f]) for f in ("reich", "land", "ausgaben_reich", "ausgaben_land")}
        minus = {f: max(0, -d[f]) for f in ("reich", "land", "ausgaben_reich", "ausgaben_land")}
        _buchen_posten(con, dict(x, **plus), k, monat, f"AK-{periode}")
        if any(minus.values()):
            _buchen_posten(con, dict(x, **minus), k, monat, f"AK-{periode}", faktor=-1)
        if a:
            con.execute("UPDATE ak_posten SET bip=?, summe=?, reich=?, land=?, ausgaben_reich=?, ausgaben_land=? WHERE id=?",
                        (x["bip"], x["summe"], x["reich"], x["land"], x["ausgaben_reich"], x["ausgaben_land"], a["id"]))
        else:
            con.execute("INSERT INTO ak_posten (lauf, staat, name, bip, summe, reich, land, ausgaben_reich, ausgaben_land) VALUES (?,?,?,?,?,?,?,?,?)",
                        (l["id"], x["staat"], x["name"], x["bip"], x["summe"], x["reich"], x["land"], x["ausgaben_reich"], x["ausgaben_land"]))
    con.execute("UPDATE ak_laeufe SET summe=?, reich=?, laender=?, ausgaben=?, parameter=? WHERE id=?",
                (sum(x["summe"] for x in liste), sum(x["reich"] for x in liste), sum(x["land"] for x in liste),
                 sum(x["ausgaben_reich"] + x["ausgaben_land"] for x in liste), json.dumps(p), l["id"]))
    geld.protokoll(con, k, "Staatshaushalt nachgebucht", f"{monat} auf die aktuellen Sätze gebracht: Einnahmen {mark(sum(x['summe'] for x in liste))}")
    con.commit()
    return l["id"]


async def automatik(app):
    """Hintergrund: einmal je Kalendermonat automatisch buchen (Einstellung „automatisch“)."""
    await asyncio.sleep(20)
    while True:
        try:
            con = app["db"]
            if geld.einstellung(con, "aufkommen").get("automatisch"):
                periode = date.today().strftime("%Y-%m")
                if ausfuehren(con, periode, SYSTEM):
                    log.info("Staatshaushalt %s automatisch gebucht", periode)
        except Exception:
            log.exception("Staatshaushalt: automatischer Lauf fehlgeschlagen")
        await asyncio.sleep(1800)


# ---------------------------------------------------------------- Seiten

def _gebiet(sid, name):
    return name + " (Reich)" if geld.ist_reichsgebiet({"id": sid, "name": name}) else name


def summen(liste):
    s = lambda f: sum(x[f] for x in liste)
    return {"ein": s("summe"), "reich": s("reich"), "land": s("land"), "aus_reich": s("ausgaben_reich"), "aus_land": s("ausgaben_land")}


def prognose_html(con, liste, besoldung):
    s = summen(liste)
    frei_reich = s["reich"] - s["aus_reich"]
    saldo = frei_reich - besoldung
    kz = [("Steuereinnahmen je Monat", s["ein"]), ("davon Reich", s["reich"]), ("Pflichtausgaben des Reiches", s["aus_reich"]),
          ("Frei verfügbar (Reich)", frei_reich), ("Besoldung (Abfluss)", besoldung), ("Überschuss des Reiches" if saldo >= 0 else "Defizit des Reiches", saldo),
          ("Frei verfügbar (Teilstaaten)", s["land"] - s["aus_land"]), ("Reichskasse heute", geld.sonder(con, "reichskasse")["saldo"])]
    return '<div class="kennzahlen">' + "".join(f"<div><b>{mark(v)}</b>{esc(t)}</div>" for t, v in kz) + "</div>"


@sa.seite("leitung")
async def seite(request, k):
    import besoldung
    con = request.app["db"]
    p = geld.einstellung(con, "aufkommen")
    liste = berechnen(con, p)
    try:
        abfluss = sum(x["netto"] + x["abgaben"] for x in await besoldung.berechnen(request.app, con))
    except Exception:
        abfluss = 0
    periode = date.today().strftime("%Y-%m")
    gebucht = con.execute("SELECT * FROM ak_laeufe WHERE periode=?", (periode,)).fetchone()
    knopf = (f'<p class="hinweis">Der Haushalt für {esc(sa._monatsname(periode))} ist gebucht.</p>' if gebucht else
             f'<form method="post" action="{PFAD}amt/aufkommen/buchen">{amt.csrf_feld(request)}<div class="aktionen">'
             f'<button class="btn" type="submit">{amt.ic("check")}Haushalt {esc(sa._monatsname(periode))} jetzt buchen</button></div></form>')
    eur = lambda h: f'{h / 100 * geld.wechselkurs(con) / 1e9:,.2f} Mrd. €'.replace(",", "X").replace(".", ",").replace("X", ".")
    zeilen = [(esc(_gebiet(x["staat"], x["name"])), f'{x["bip"]:,.0f}'.replace(",", "."), f'{(x["bip"] * 1e6 / x["ew"] if x["ew"] else 0):,.0f} €'.replace(",", "."),
               geld.mark_kurz(x["summe"]), geld.mark_kurz(x["reich"]), geld.mark_kurz(x["land"]) if x["kasse"] else "– (alles ans Reich)",
               geld.mark_kurz(x["land"] - x["ausgaben_land"]) if x["kasse"] else "–") for x in liste]
    laeufe = con.execute("SELECT * FROM ak_laeufe ORDER BY id DESC LIMIT 24").fetchall()
    c = amt.csrf_feld(request)
    s = summen(liste)
    inhalt = (f'<h1>{amt.ic("chart-column")} Staatshaushalt</h1>{amt.meldung(request)}'
              f'<p class="az">Einnahmen aus der Wirtschaftsleistung der Bevölkerung (BIP je Teilstaat, Eurostat) im Echtmaßstab: 1 Kr = '
              f'{esc(str(geld.einstellung(con, "wechselkurs")))} €. Monatlich: BIP ÷ 12 × Steuerquote, Pflichtausgaben als Quote der Einnahmen. '
              f'Einnahmen im Jahr: {eur(s["ein"] * 12)}.</p>'
              + prognose_html(con, liste, abfluss) + knopf
              + f'<h2>Stellschrauben</h2><form class="sa-formular" method="post" action="{PFAD}amt/aufkommen/">{c}<div class="zeilen">'
              f'<div><label for="q">Steuerquote (% des BIP)</label><input type="text" id="q" name="steuerquote" value="{esc(str(p["steuerquote"]))}"></div>'
              f'<div><label for="r">Reichsanteil (%)</label><input type="text" id="r" name="reichsanteil" value="{esc(str(p["reichsanteil"]))}"></div>'
              f'<div><label for="a">Pflichtausgaben (% der Einnahmen)</label><input type="text" id="a" name="ausgabenquote" value="{esc(str(p.get("ausgabenquote", 97)))}"></div>'
              f'<div><label for="w">Wechselkurs (€ je Krone)</label><input type="text" id="w" name="wechselkurs" value="{esc(str(geld.einstellung(con, "wechselkurs")))}"></div></div>'
              f'<label><input type="checkbox" name="automatisch" value="1"{" checked" if p.get("automatisch") else ""}> Jeden Monat automatisch buchen</label>'
              f'<div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("check")}Speichern</button></div></form>'
              '<p class="sa-hinweis">Richtwerte Deutschland: Steuerquote rund 24 % des BIP; Verteilung etwa 43 % Bund/EU, 57 % Länder und Gemeinden. '
              'Die Pflichtausgaben bilden Sozialleistungen, Verteidigung, Infrastruktur, Bildung und Verwaltung für die Bevölkerung ab; '
              'was übrig bleibt, steht Reich und Landesherren frei zur Verfügung.</p>'
              '<h2>Haushalt je Gebiet (Monat)</h2><p class="sa-hinweis">Die Freien Reichsgebiete sind kein Teilstaat, sondern das Reich selbst: '
              'ihre Einnahmen gehen vollständig an die Reichskasse.</p>' + amt.tabelle(["Gebiet", "BIP (Mio. €)", "BIP je Einwohner", "Einnahmen", "Reich", "Teilstaat",
                                                                    "Teilstaat frei"], zeilen)
              + '<h2>Gebuchte Monate</h2>' + amt.tabelle(["Monat", "Einnahmen", "Reich", "Teilstaaten", "Pflichtausgaben", "Gebucht"],
                                                         [(esc(sa._monatsname(l["periode"])), geld.mark_kurz(l["summe"]), geld.mark_kurz(l["reich"]),
                                                           geld.mark_kurz(l["laender"]), geld.mark_kurz(l["ausgaben"]),
                                                           f'{amt._zeit(l["zeit"])} · {esc(l["autor_name"])}') for l in laeufe], "Noch kein Monat gebucht."))
    return sa.ant(request, k, "Staatshaushalt", "sa-amt-aufkommen", inhalt)


async def speichern(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    q, r, a = (geld.prozent_lesen(form.get(n)) for n in ("steuerquote", "reichsanteil", "ausgabenquote"))
    try:
        w = float(str(form.get("wechselkurs", "")).replace(",", "."))
    except ValueError:
        w = 0
    if q is None or r is None or a is None or not 0.01 <= w <= 1000:
        sa.weiter(f"{PFAD}amt/aufkommen/", "Bitte gültige Werte angeben.", True)
    ganz = lambda x: int(x) if x == int(x) else x
    geld.einstellung_setzen(con, "aufkommen", {"steuerquote": ganz(q), "reichsanteil": ganz(r), "ausgabenquote": ganz(a),
                                                "automatisch": form.get("automatisch") == "1"}, k)
    geld.einstellung_setzen(con, "wechselkurs", f"{w:g}".replace(".", ","), k)
    con.commit()
    sa.weiter(f"{PFAD}amt/aufkommen/", "Gespeichert; die Sätze gelten ab dem nächsten gebuchten Monat.")


async def buchen(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    await sa.formular(request)
    con = request.app["db"]
    periode = date.today().strftime("%Y-%m")
    lauf = ausfuehren(con, periode, k)
    sa.weiter(f"{PFAD}amt/aufkommen/", f"Haushalt {sa._monatsname(periode)} gebucht." if lauf else "Dieser Monat ist bereits gebucht.", not lauf)


def finanzen_html(con):
    """Für die staatliche Seite „Reichsfinanzen“: letzter gebuchter Monat je Teilstaat."""
    l = con.execute("SELECT * FROM ak_laeufe ORDER BY id DESC LIMIT 1").fetchone()
    if not l:
        return ""
    posten = con.execute("SELECT * FROM ak_posten WHERE lauf=? ORDER BY summe DESC", (l["id"],)).fetchall()
    return (f'<h2>Staatshaushalt · {esc(sa._monatsname(l["periode"]))}</h2>'
            f'<p class="az">Steuereinnahmen {mark(l["summe"])} (Reich {mark(l["reich"])}, Teilstaaten {mark(l["laender"])}); '
            f'Pflichtausgaben {mark(l["ausgaben"])}</p>'
            + amt.tabelle(["Gebiet", "Einnahmen", "an das Reich", "an den Teilstaat", "frei verfügbar (Teilstaat)"],
                          [(esc(_gebiet(x["staat"], x["name"])), geld.mark_kurz(x["summe"]), geld.mark_kurz(x["reich"]), geld.mark_kurz(x["land"]) if x["land"] else "–",
                            geld.mark_kurz(x["land"] - x["ausgaben_land"]) if x["land"] else "–") for x in posten]))


def registrieren(app):
    einrichten(app["db"])
    geld.einrichten(app["db"])   # Sonderkonto „volkswirtschaft“
    geld.BUCHUNGSART["staatsausgaben"] = "Pflichtausgaben (simuliert)"
    app.router.add_get(PFAD + "amt/aufkommen/", seite)
    app.router.add_post(PFAD + "amt/aufkommen/", speichern)
    app.router.add_post(PFAD + "amt/aufkommen/buchen", buchen)

    async def start(app_):
        app_["aufkommen_aufgabe"] = asyncio.get_event_loop().create_task(automatik(app_))

    async def stopp(app_):
        app_["aufkommen_aufgabe"].cancel()
    app.on_startup.append(start)
    app.on_cleanup.append(stopp)
