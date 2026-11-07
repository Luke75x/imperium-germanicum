"""Staatshaushalt der simulierten Bevölkerung im Echtmaßstab (1 Krone = Wechselkurs €, Vorgabe 1,21 €).

Einnahmen: Jeden Monat zahlt die Bevölkerung jedes Teilstaats Steuern: BIP (Mio. €, karte_daten/bip.json) ÷ 12 × Steuerquote (24 %),
umgerechnet in Kronen zum Wechselkurs. Reichsabgabe: Jeder Teilstaat führt einen eigenen Prozentsatz seiner Steuereinnahmen an das Reich ab
(abgabequoten): Index aus Bevölkerung, Einkommen pro Kopf und Fläche (je Wurzel des Verhältnisses zum Durchschnitt, gewichtet,
Vorgabe 40/40/20), so normiert, dass das Reich im Schnitt den „Reichsanteil“ (43 %) erhält, begrenzt auf quote_min…quote_max (20–65 %).
Rest an die Staatskasse; die Freien Reichsgebiete (geld.ist_reichsgebiet) sind kein Teilstaat, sondern das
Reich selbst – dort erhält die Reichskasse alles.
Ausgaben: Pflichtausgaben (Soziales, Verteidigung, Infrastruktur, Bildung, Verwaltung der nicht spielenden Bevölkerung) als Quote der
Einnahmen (Vorgabe 97 %) gehen zurück an die Volkswirtschaft; die übrigen 3 % sind der frei verfügbare Spielraum für Reich und Landesherren.
Gegenkonto ist das Sonderkonto „volkswirtschaft“ (außerhalb des Geldumlaufs). Läuft automatisch einmal je Kalendermonat
(Hintergrundaufgabe, abschaltbar), sonst über /schatzamt/haushalt/ (für alle mit staatlichem Zugriff lesbar, Stellschrauben nur Leitung). Tabellen: ak_laeufe (je Monat eindeutig), ak_posten (je Teilstaat).
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
    for tab, spalte, typ in (("ak_laeufe", "ausgaben", "INTEGER"), ("ak_posten", "ausgaben_reich", "INTEGER"), ("ak_posten", "ausgaben_land", "INTEGER"),
                             ("ak_posten", "quote", "REAL"), ("ak_posten", "vert_reich", "INTEGER"), ("ak_posten", "vert_land", "INTEGER")):
        if spalte not in {r[1] for r in con.execute(f"PRAGMA table_info({tab})")}:
            con.execute(f"ALTER TABLE {tab} ADD COLUMN {spalte} {typ} NOT NULL DEFAULT 0")
    con.commit()


def kronen_je_mio_euro(con):
    return 1e6 / geld.wechselkurs(con)


_GEO = None
VORGABE_GEWICHTE = {"bevoelkerung": 40, "einkommen": 40, "flaeche": 20}


def _flaechen():
    global _GEO
    if _GEO is None:
        _GEO = {g: (v.get("a") or 0) for g, v in json.load(open(os.path.join(DATEN, "geo.json")))["gebiete"].items()}
    return _GEO


def staaten_bip(con):
    """[(Teilstaat, BIP Mio. €, Einwohner, Fläche km²)] der aktuellen Reichskarte."""
    import karte
    a = karte.aktuell(con)
    bip = json.load(open(os.path.join(DATEN, "bip.json")))
    bev = json.load(open(os.path.join(DATEN, "bevoelkerung.json")))
    fl = _flaechen()
    summe = {}
    for g, sid in a["stand"]["gebiete"].items():
        x = summe.setdefault(sid, [0.0, 0, 0.0])
        x[0] += bip.get(g, [0])[0]
        x[1] += bev.get(g, [0])[0]
        x[2] += fl.get(g, 0)
    return [(s, *summe.get(s["id"], [0, 0, 0])) for s in a["stand"]["staaten"]]


def abgabequoten(daten, p, summen_heller=None):
    """{Teilstaat-ID: Reichsabgabe in %} – Index aus Bevölkerung, Einkommen pro Kopf und Fläche (Wurzel des Verhältnisses zum
    Durchschnitt der Teilstaaten bzw. zum BIP/Kopf des ganzen Reiches), gewichtet; normiert auf den Reichsanteil als nach Einnahmen
    gewichteten Durchschnitt; begrenzt auf quote_min…quote_max. Freie Reichsgebiete: 100 %."""
    w = dict(VORGABE_GEWICHTE, **(p.get("gewichte") or {}))
    wsum = sum(float(x) for x in w.values()) or 1
    lo, hi = float(p.get("quote_min", 20)), float(p.get("quote_max", 65))
    basis = float(p["reichsanteil"])
    ts = [(s, bip, ew, km) for s, bip, ew, km in daten if not geld.ist_reichsgebiet(s)]
    if not ts:
        return {}
    ew_d = sum(x[2] for x in ts) / len(ts) or 1
    km_d = sum(x[3] for x in ts) / len(ts) or 1
    gesamt_ew = sum(x[2] for x in daten) or 1
    kopf_d = sum(x[1] for x in daten) / gesamt_ew or 1
    idx = {}
    for s, bip, ew, km in ts:
        kopf = (bip / ew) / kopf_d if ew else 1
        idx[s["id"]] = (float(w["bevoelkerung"]) * (ew / ew_d) ** .5 + float(w["einkommen"]) * kopf ** .5
                        + float(w["flaeche"]) * (km / km_d) ** .5) / wsum
    gew = summen_heller or {s["id"]: bip for s, bip, ew, km in ts}
    faktor = basis
    for _ in range(30):   # normieren, sodass der gewichtete Schnitt (nach Begrenzung) dem Reichsanteil entspricht
        q = {i: min(hi, max(lo, faktor * x)) for i, x in idx.items()}
        schnitt = sum(q[i] * gew.get(i, 0) for i in q) / (sum(gew.get(i, 0) for i in q) or 1)
        if abs(schnitt - basis) < 1e-6 or not schnitt:
            break
        faktor *= basis / schnitt
    out = {i: round(v, 1) for i, v in q.items()}
    out.update({s["id"]: 100.0 for s, *_ in daten if geld.ist_reichsgebiet(s)})
    return out


def berechnen(con, p=None):
    """Monatlicher Haushalt je Teilstaat (Heller): Einnahmen summe/reich/land, Pflichtausgaben ausgaben_reich/ausgaben_land und
    Verteidigungsetat vert_reich/vert_land (wird aus den Pflichtausgaben abgezweigt: verteidigung.py)."""
    import verteidigung
    p = p or geld.einstellung(con, "aufkommen")
    v = verteidigung.einstellungen(con)
    quote, aq = float(p["steuerquote"]) / 100, float(p.get("ausgabenquote", 97)) / 100
    kr = kronen_je_mio_euro(con)
    daten = staaten_bip(con)
    quoten = abgabequoten(daten, p)
    out = []
    for s, bip, ew, km in daten:
        summe = int(round(bip / 12 * quote * kr * 100))
        reich_direkt = geld.ist_reichsgebiet(s)
        q = quoten.get(s["id"], float(p["reichsanteil"]))
        reich = summe if reich_direkt else int(round(summe * q / 100))
        land = summe - reich
        aus_r, aus_l = int(round(reich * aq)), int(round(land * aq))
        vert = int(round(bip / 12 * float(v["quote_bip"]) / 100 * kr * 100))
        vr = min(aus_r, int(round(vert * float(v["anteil_reich"]) / 100)))
        vl = 0 if reich_direkt else min(aus_l, vert - int(round(vert * float(v["anteil_reich"]) / 100)))
        out.append({"staat": s["id"], "name": s["name"], "reichsgebiet": reich_direkt, "bip": bip, "ew": ew, "km2": km, "quote": q,
                    "summe": summe, "reich": reich, "land": land, "ausgaben_reich": aus_r - vr, "ausgaben_land": aus_l - vl,
                    "vert_reich": vr, "vert_land": vl,
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
    # Verteidigungsetat: Reichsanteil an die Reichsverteidigungskasse, Landesanteil an die Verteidigungskasse des Teilstaats
    vt = [(kasse, geld.stellenkonto(con, "verteidigung"), x.get("vert_reich", 0), "Reich")]
    if x["kasse"]:
        vt.append((x["kasse"], geld.stellenkonto(con, "vt-" + x["staat"]), x.get("vert_land", 0), "Teilstaat"))
    for von, an, betrag, was in vt:
        if betrag > 0 and an:
            v, a = (von, an) if faktor > 0 else (an, von)
            geld.buchen(con, v["id"], a["id"], betrag, "verteidigungsetat", f"Verteidigungsetat {monat}: {x['name']} ({was})"
                        + ("" if faktor > 0 else " – Berichtigung"), k, bezug=bezug, minus=True)


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
        con.execute("INSERT INTO ak_posten (lauf, staat, name, bip, summe, reich, land, ausgaben_reich, ausgaben_land, quote, vert_reich, vert_land) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (lauf, x["staat"], x["name"], x["bip"], x["summe"], x["reich"], x["land"], x["ausgaben_reich"], x["ausgaben_land"], x["quote"],
                     x["vert_reich"], x["vert_land"]))
    geld.protokoll(con, k, "Staatshaushalt", f"{monat}: Einnahmen {mark(sum(x['summe'] for x in liste))}, Pflichtausgaben "
                                             f"{mark(sum(x['ausgaben_reich'] + x['ausgaben_land'] for x in liste))}, Verteidigung "
                                             f"{mark(sum(x['vert_reich'] + x['vert_land'] for x in liste))}")
    con.commit()
    import verteidigung
    verteidigung.instandhaltung(con, periode, k)   # Instandhaltung des Militärgeräts im selben Monat
    return lauf


def verteidigung_einbuchen(con, periode, k):
    """Für einen schon gebuchten Monat ohne Verteidigungsetat: zweigt den Etat nachträglich aus den Pflichtausgaben ab
    (Berichtigung der Pflichtausgaben, dann Kasse → Verteidigungskasse). Reich/Teilstaat-Aufteilung der Einnahmen bleibt unverändert."""
    import verteidigung
    l = con.execute("SELECT * FROM ak_laeufe WHERE periode=?", (periode,)).fetchone()
    if not l:
        return 0
    v = verteidigung.einstellungen(con)
    kr = kronen_je_mio_euro(con)
    monat, summe = sa._monatsname(periode), 0
    for a in con.execute("SELECT * FROM ak_posten WHERE lauf=? AND vert_reich=0 AND vert_land=0", (l["id"],)).fetchall():
        rd = geld.ist_reichsgebiet({"id": a["staat"], "name": a["name"]})
        vert = int(round(a["bip"] / 12 * float(v["quote_bip"]) / 100 * kr * 100))
        vr = min(a["ausgaben_reich"], int(round(vert * float(v["anteil_reich"]) / 100)))
        vl = 0 if rd else min(a["ausgaben_land"], vert - int(round(vert * float(v["anteil_reich"]) / 100)))
        x = {"staat": a["staat"], "name": a["name"], "reichsgebiet": rd, "kasse": None if rd else geld.stellenkonto(con, "ts-" + a["staat"]),
             "reich": 0, "land": 0, "ausgaben_reich": 0, "ausgaben_land": 0, "vert_reich": 0, "vert_land": 0}
        _buchen_posten(con, dict(x, ausgaben_reich=vr, ausgaben_land=vl), k, monat, f"AK-{periode}", faktor=-1)
        _buchen_posten(con, dict(x, vert_reich=vr, vert_land=vl), k, monat, f"AK-{periode}")
        con.execute("UPDATE ak_posten SET ausgaben_reich=ausgaben_reich-?, ausgaben_land=ausgaben_land-?, vert_reich=?, vert_land=? WHERE id=?",
                    (vr, vl, vr, vl, a["id"]))
        summe += vr + vl
    con.execute("UPDATE ak_laeufe SET ausgaben=ausgaben-? WHERE id=?", (summe, l["id"]))
    geld.protokoll(con, k, "Verteidigungsetat nachgebucht", f"{monat}: {mark(summe)} aus den Pflichtausgaben an die Verteidigungskassen")
    con.commit()
    return summe


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
        for f in ("reich", "land", "ausgaben_reich", "ausgaben_land", "vert_reich", "vert_land"):
            d[f] = x[f] - (a[f] if a else 0)
        plus = {f: max(0, d[f]) for f in ("reich", "land", "ausgaben_reich", "ausgaben_land", "vert_reich", "vert_land")}
        minus = {f: max(0, -d[f]) for f in ("reich", "land", "ausgaben_reich", "ausgaben_land", "vert_reich", "vert_land")}
        _buchen_posten(con, dict(x, **plus), k, monat, f"AK-{periode}")
        if any(minus.values()):
            _buchen_posten(con, dict(x, **minus), k, monat, f"AK-{periode}", faktor=-1)
        if a:
            con.execute("UPDATE ak_posten SET bip=?, summe=?, reich=?, land=?, ausgaben_reich=?, ausgaben_land=?, quote=?, vert_reich=?, vert_land=? WHERE id=?",
                        (x["bip"], x["summe"], x["reich"], x["land"], x["ausgaben_reich"], x["ausgaben_land"], x["quote"], x["vert_reich"], x["vert_land"], a["id"]))
        else:
            con.execute("INSERT INTO ak_posten (lauf, staat, name, bip, summe, reich, land, ausgaben_reich, ausgaben_land, quote, vert_reich, vert_land) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (l["id"], x["staat"], x["name"], x["bip"], x["summe"], x["reich"], x["land"], x["ausgaben_reich"], x["ausgaben_land"], x["quote"],
                     x["vert_reich"], x["vert_land"]))
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
    return {"ein": s("summe"), "reich": s("reich"), "land": s("land"), "aus_reich": s("ausgaben_reich"), "aus_land": s("ausgaben_land"),
            "vert_reich": s("vert_reich"), "vert_land": s("vert_land")}


def _zahl(x):
    return f"{x:,.0f}".replace(",", ".")


def _ew(x):
    return f'{x / 1e6:,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".") + " Mio." if x >= 1e5 else _zahl(x)


def _pz(x):
    return f"{x:.1f} %".replace(".", ",")


def lage(con, liste, besoldung_reich=0):
    """Monatliche Haushaltslage des Reiches (Heller): Einnahmen, Pflichtausgaben, Etats der Behörden, Besoldung über die Reichskasse."""
    import etat
    s = summen(liste)
    frei_reich = s["reich"] - s["aus_reich"] - s["vert_reich"]
    etats = sum(etat.etats(con).values()) // 12
    return {"ein": s["ein"], "reich": s["reich"], "frei_reich": frei_reich, "etats": etats, "besoldung": besoldung_reich,
            "saldo": frei_reich - etats - besoldung_reich, "frei_land": s["land"] - s["aus_land"] - s["vert_land"],
            "verteidigung": s["vert_reich"] + s["vert_land"]}


def prognose_html(con, liste, besoldung_reich=0):
    l = lage(con, liste, besoldung_reich)
    kz = [("Steuereinnahmen im Monat", l["ein"]), ("davon an das Reich", l["reich"]), ("Reich frei verfügbar¹", l["frei_reich"]),
          ("Etats der Behörden (1/12)", l["etats"]), ("Besoldung über die Reichskasse", l["besoldung"]),
          ("Überschuss des Reiches" if l["saldo"] >= 0 else "Defizit des Reiches", l["saldo"]),
          ("Teilstaaten frei verfügbar¹", l["frei_land"]), ("Verteidigungsetat (Reich + Teilstaaten)", l["verteidigung"]),
          ("Reichskasse heute", geld.sonder(con, "reichskasse")["saldo"])]
    return '<div class="kennzahlen">' + "".join(f"<div><b>{mark(v)}</b>{esc(t)}</div>" for t, v in kz) + "</div>"


def tabelle_html(liste):
    """Reichsabgabe je Teilstaat: Kennzahlen, Abgabequote, Einnahmen, Anteil Reich/Teilstaat."""
    zeilen = []
    for x in sorted(liste, key=lambda x: (not x["reichsgebiet"], -x["summe"])):
        kopf = x["bip"] * 1e6 / x["ew"] if x["ew"] else 0
        quote = ('<b>100 %</b> <span class="az">Reich</span>' if x["reichsgebiet"] else f'<b>{_pz(x["quote"])}</b>')
        zeilen.append((esc(_gebiet(x["staat"], x["name"])), _ew(x["ew"]), f"{_zahl(kopf)} €", f'{_zahl(x["km2"])} km²', quote,
                       geld.mark_kurz(x["summe"]), geld.mark_kurz(x["reich"]), geld.mark_kurz(x["land"]) if x["land"] else "–",
                       geld.mark_kurz(x["land"] - x["ausgaben_land"] - x["vert_land"]) if x["land"] else "–"))
    return amt.tabelle(["Gebiet", "Einwohner", "BIP je Kopf", "Fläche", "Reichsabgabe", "Steuern / Monat", "an das Reich", "bleibt dem Teilstaat",
                        "davon frei¹"], zeilen, klasse="sa-haushalt")


def erklaerung_html(p):
    w = dict(VORGABE_GEWICHTE, **(p.get("gewichte") or {}))
    return ('<div class="sa-erkl"><b>So entsteht die Reichsabgabe</b><ol>'
            f'<li>Jeder Teilstaat nimmt im Monat <b>{esc(str(p["steuerquote"]))} %</b> seiner Wirtschaftsleistung (BIP ÷ 12) an Steuern ein.</li>'
            f'<li>Davon führt er einen eigenen Prozentsatz an das Reich ab. Er richtet sich nach <b>Bevölkerung ({w["bevoelkerung"]} %)</b>, '
            f'<b>Einkommen pro Kopf ({w["einkommen"]} %)</b> und <b>Fläche ({w["flaeche"]} %)</b> im Vergleich zum Durchschnitt: '
            'große, reiche und weitläufige Teilstaaten zahlen einen höheren Satz.</li>'
            f'<li>Im Schnitt erhält das Reich <b>{esc(str(p["reichsanteil"]))} %</b>; kein Teilstaat zahlt weniger als '
            f'{esc(str(p.get("quote_min", 20)))} % oder mehr als {esc(str(p.get("quote_max", 65)))} %. Die Freien Reichsgebiete sind das Reich selbst.</li>'
            f'<li>¹ Pflichtausgaben für die Bevölkerung ({esc(str(p.get("ausgabenquote", 97)))} %) sind abgezogen – ein Teil davon ist als '
            f'<a href="{PFAD}verteidigung/">Verteidigungsetat</a> zweckgebunden; der Rest steht Reich und Landesherren frei zur Verfügung. '
            'Aus dem Anteil des Reiches werden die Etats der Behörden bezahlt, die Behörden zahlen davon ihre Mitarbeiter.</li></ol></div>')


@sa.seite("staat")
async def seite(request, k):
    import besoldung
    con = request.app["db"]
    p = geld.einstellung(con, "aufkommen")
    liste = berechnen(con, p)
    try:
        besoldung_reich = sum(x["brutto"] for x in await besoldung.berechnen(request.app, con) if x["zahlstelle"] == "reichskasse")
    except Exception:
        besoldung_reich = 0
    periode = date.today().strftime("%Y-%m")
    gebucht = con.execute("SELECT * FROM ak_laeufe WHERE periode=?", (periode,)).fetchone()
    eur = lambda h: f'{h / 100 * geld.wechselkurs(con) / 1e9:,.1f} Mrd. €'.replace(",", "X").replace(".", ",").replace("X", ".")
    leitung = geld.ist_leitung(k)
    c = amt.csrf_feld(request)
    w = dict(VORGABE_GEWICHTE, **(p.get("gewichte") or {}))
    status = (f'<p class="sa-status ok">{amt.ic("check")}Der Haushalt für {esc(sa._monatsname(periode))} ist gebucht.</p>' if gebucht else
              f'<p class="sa-status">{amt.ic("clock")}Der Haushalt für {esc(sa._monatsname(periode))} ist noch nicht gebucht'
              + (' – er wird automatisch gebucht.' if p.get("automatisch") else '.') + '</p>')
    if leitung and not gebucht:
        status += (f'<form method="post" action="{PFAD}haushalt/buchen">{c}<div class="aktionen">'
                   f'<button class="btn" type="submit">{amt.ic("check")}Haushalt {esc(sa._monatsname(periode))} jetzt buchen</button></div></form>')
    feld = lambda i, n, t, v: f'<div><label for="{i}">{t}</label><input type="text" id="{i}" name="{n}" value="{esc(str(v))}"></div>'
    stell = ""
    if leitung:
        stell = (f'<details class="sa-auf"><summary>{amt.ic("pencil")}Stellschrauben ändern</summary>'
                 f'<form class="sa-formular" method="post" action="{PFAD}haushalt/">{c}'
                 '<h3>Einnahmen und Ausgaben</h3><div class="zeilen">'
                 + feld("q", "steuerquote", "Steuerquote (% des BIP)", p["steuerquote"])
                 + feld("a", "ausgabenquote", "Pflichtausgaben (% der Einnahmen)", p.get("ausgabenquote", 97))
                 + feld("w", "wechselkurs", "Wechselkurs (€ je Krone)", geld.einstellung(con, "wechselkurs"))
                 + '</div><h3>Reichsabgabe der Teilstaaten</h3><div class="zeilen">'
                 + feld("r", "reichsanteil", "Durchschnitt an das Reich (%)", p["reichsanteil"])
                 + feld("mi", "quote_min", "Mindestens (%)", p.get("quote_min", 20)) + feld("ma", "quote_max", "Höchstens (%)", p.get("quote_max", 65))
                 + '</div><div class="zeilen">'
                 + feld("gb", "g_bevoelkerung", "Gewicht Bevölkerung", w["bevoelkerung"]) + feld("ge", "g_einkommen", "Gewicht Einkommen pro Kopf", w["einkommen"])
                 + feld("gf", "g_flaeche", "Gewicht Fläche", w["flaeche"])
                 + f'</div><label><input type="checkbox" name="automatisch" value="1"{" checked" if p.get("automatisch") else ""}> Jeden Monat automatisch buchen</label>'
                 f'<p class="sa-hinweis">Richtwerte Deutschland: Steuerquote rund 24 % des BIP, davon etwa 43 % an Bund und EU. Änderungen gelten ab dem nächsten gebuchten Monat.</p>'
                 f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button></div></form></details>')
    laeufe = con.execute("SELECT * FROM ak_laeufe ORDER BY id DESC LIMIT 24").fetchall()
    inhalt = (f'<h1>{amt.ic("chart-column")} Staatshaushalt</h1>{amt.meldung(request)}'
              f'<p class="az">Monatliche Steuereinnahmen aus der Wirtschaftsleistung der Bevölkerung – im Jahr {eur(summen(liste)["ein"] * 12)} '
              f'(1 Kr = {esc(str(geld.einstellung(con, "wechselkurs")))} €).</p>'
              + status + prognose_html(con, liste, besoldung_reich) + erklaerung_html(p)
              + '<h2>Reichsabgabe der Teilstaaten</h2>' + tabelle_html(liste) + stell
              + f'<details class="sa-auf"><summary>{amt.ic("clock")}Gebuchte Monate ({len(laeufe)})</summary>'
              + amt.tabelle(["Monat", "Einnahmen", "Reich", "Teilstaaten", "Pflichtausgaben", "Gebucht"],
                            [(esc(sa._monatsname(l["periode"])), geld.mark_kurz(l["summe"]), geld.mark_kurz(l["reich"]),
                              geld.mark_kurz(l["laender"]), geld.mark_kurz(l["ausgaben"]),
                              f'{amt._zeit(l["zeit"])} · {esc(l["autor_name"])}') for l in laeufe], "Noch kein Monat gebucht.") + '</details>')
    return sa.ant(request, k, "Staatshaushalt", "sa-staatshaushalt", inhalt)


async def speichern(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    werte = {n: geld.prozent_lesen(form.get(n)) for n in ("steuerquote", "reichsanteil", "ausgabenquote", "quote_min", "quote_max",
                                                          "g_bevoelkerung", "g_einkommen", "g_flaeche")}
    try:
        w = float(str(form.get("wechselkurs", "")).replace(",", "."))
    except ValueError:
        w = 0
    if any(v is None for v in werte.values()) or not 0.01 <= w <= 1000 or werte["quote_min"] > werte["reichsanteil"] or werte["quote_max"] < werte["reichsanteil"] \
            or not (werte["g_bevoelkerung"] + werte["g_einkommen"] + werte["g_flaeche"]):
        sa.weiter(f"{PFAD}haushalt/", "Bitte gültige Werte angeben (Mindestens ≤ Durchschnitt ≤ Höchstens, mindestens ein Gewicht über 0).", True)
    ganz = lambda x: int(x) if x == int(x) else x
    geld.einstellung_setzen(con, "aufkommen", {
        "steuerquote": ganz(werte["steuerquote"]), "reichsanteil": ganz(werte["reichsanteil"]), "ausgabenquote": ganz(werte["ausgabenquote"]),
        "quote_min": ganz(werte["quote_min"]), "quote_max": ganz(werte["quote_max"]),
        "gewichte": {"bevoelkerung": ganz(werte["g_bevoelkerung"]), "einkommen": ganz(werte["g_einkommen"]), "flaeche": ganz(werte["g_flaeche"])},
        "automatisch": form.get("automatisch") == "1"}, k)
    geld.einstellung_setzen(con, "wechselkurs", f"{w:g}".replace(".", ","), k)
    con.commit()
    sa.weiter(f"{PFAD}haushalt/", "Gespeichert; die Sätze gelten ab dem nächsten gebuchten Monat.")


async def buchen(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    await sa.formular(request)
    con = request.app["db"]
    periode = date.today().strftime("%Y-%m")
    lauf = ausfuehren(con, periode, k)
    sa.weiter(f"{PFAD}haushalt/", f"Haushalt {sa._monatsname(periode)} gebucht." if lauf else "Dieser Monat ist bereits gebucht.", not lauf)


def finanzen_html(con):
    """Für die staatliche Seite „Reichsfinanzen“: letzter gebuchter Monat je Teilstaat."""
    l = con.execute("SELECT * FROM ak_laeufe ORDER BY id DESC LIMIT 1").fetchone()
    if not l:
        return ""
    return (f'<h2>Staatshaushalt · {esc(sa._monatsname(l["periode"]))}</h2>'
            f'<p class="az">Steuereinnahmen {mark(l["summe"])} – davon Reich {mark(l["reich"])}, Teilstaaten {mark(l["laender"])}; '
            f'Pflichtausgaben {mark(l["ausgaben"])}. <a href="{PFAD}haushalt/">Reichsabgabe je Teilstaat →</a></p>')


def registrieren(app):
    einrichten(app["db"])
    geld.einrichten(app["db"])   # Sonderkonto „volkswirtschaft“
    geld.BUCHUNGSART["staatsausgaben"] = "Pflichtausgaben (simuliert)"
    app.router.add_get(PFAD + "haushalt/", seite)
    app.router.add_post(PFAD + "haushalt/", speichern)
    app.router.add_post(PFAD + "haushalt/buchen", buchen)

    async def alt(request):   # alte Adresse
        raise web.HTTPMovedPermanently(PFAD + "haushalt/")
    app.router.add_get(PFAD + "amt/aufkommen/", alt)

    async def start(app_):
        app_["aufkommen_aufgabe"] = asyncio.get_event_loop().create_task(automatik(app_))

    async def stopp(app_):
        app_["aufkommen_aufgabe"].cancel()
    app.on_startup.append(start)
    app.on_cleanup.append(stopp)
