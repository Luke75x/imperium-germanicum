"""Energiesystem: Angebot (Kraftwerke), Bedarf (Bevölkerung, Industrie, Veredelung, Militär), Versorgungslage und ihre Folgen – je Haushalt (Teilstaat „ts-<sid>“ und Reich „reich“ = Freie Reichsgebiete).

Einheit: GWh je Monat.

Bedarf (Sätze nur in der RP-Leitungsansicht: /schatzamt/rp/energie/)
  · Bevölkerung: pauschal Einwohner × kWh je Kopf und Monat (Haushalte, Heizung, Alltag).
  · Industrie: BIP (Mio. €, monatlich) × GWh je Mio. € – die Grundlast der Wirtschaft.
  · Veredelung: jede Veredelung im Handel (Stahl, Aluminium, Treibstoff) verbraucht Energie je Tonne; sie wird nur ausgeführt, solange der Teilstaat
    noch freie Energie hat, und zählt im laufenden Monat zum Bedarf.
  · Militär: wenige MWh je Gerät und Monat (Instandhaltung); bei Unterversorgung sinkt zusätzlich die Einsatzbereitschaft (verteidigung.instandhaltung).
Angebot: Kraftwerke (Tabelle en_kraftwerke). Beim ersten Zugriff bekommt jeder Haushalt seine reale Stromerzeugung als Grundausstattung (karte_daten/energie.json,
  erzeugt von werkzeuge/energie_grundausstattung.py aus Eurostat und Kraftwerksregistern; ohne Kernkraft, ohne Reserve – ein Defizit ist der reale Wert des Gebiets). Ausbau: Landesherren (Reich: Schatzamt-Leitung) bauen Kraftwerke sofort aus (keine Bauzeit). Bau und Instandhaltung zahlt der INDUSTRIE-ETAT des Haushalts:
  die Instandhaltung (je erzeugter GWh) jeden Monat, der Bau als monatliche Rate über „bau_monate“ Monate. Diese Lasten verringern, was der Industrie-Etat für die Industrie
  selbst übrig lässt (entwicklung.entwickeln: ind_faktor), und die „verfügbaren“ Mittel der Industrie-Scheibe im Tortendiagramm (etatplan). Es wird nur gebaut, solange die Lasten
  den Industrie-Etat nicht übersteigen. Stilllegung sowie alle Sätze ändert nur die RP-Leitung (/schatzamt/rp/energie/).
Veredelungs-Boni (monatlich, aus dem Lager des Haushalts): Treibstoff steigert die Energieerzeugung (bis +100 %), Aluminium die Effizienz der Industrie (bis +100 %, d. h. weniger
  Energiebedarf), Stahl senkt die Preise für Militärgerät (bis −10 %). Bonus = Lagerbestand ÷ Richtmenge (feste Tonnenzahl für 100 %, Sätze richt_*, Vorgabe 100.000 t), höchstens 100 %. Zum Monatswechsel
  wird die Richtmenge aus dem Lager verbraucht (monatswechsel), danach ist der Bonus weg; Überschuss darüber bleibt. Herstellen und Zukaufen (Handel) füllen das Lager, Verkaufen leert es.
Energiemarkt (/schatzamt/energie/markt/): Haushalte mit Überschuss bieten GWh zu einem selbst gesetzten Preis an; Haushalte mit Versorgung unter „kauf_unter“ % kaufen,
  höchstens ihren Fehlbetrag, in Prozent des Angebots (mehrere Käufer teilen sich ein Angebot, bis es leer ist), aus der Staats- bzw. Reichskasse an die Kasse des Verkäufers. Angebote und Käufe gelten nur für den laufenden Monat.
Versorgung bei Knappheit: zuerst die Bevölkerung, dann das Militär, zuletzt Industrie und Veredelung.
Folgen (entwicklung.entwickeln ruft wirkungen_fuer): Unterversorgung der Bevölkerung senkt die Zufriedenheit, mangelnde Gesamtversorgung verschiebt die Zielwerte der
  Infrastruktur (Wasser, Müll, Straßen) nach unten, fehlende Energie für die Industrie das Industrieniveau und das BIP pro Kopf. Fossile Kraftwerke belasten das Klima (CO₂).
Statistik: Monatswerte (en_monat, beim Buchen des Haushaltsmonats), Verlauf, Vergleich aller Haushalte. Reiter „Energie“ bei „Mein Teilstaat“ und im Reichshaushalt.
Tabellen: en_kraftwerke, en_monat, en_nutzung.
"""
import asyncio
import json
import logging
import math
import time

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa

esc = amt.esc
log = logging.getLogger("energie")
PFAD = sa.PFAD + "energie/"
RPE = sa.PFAD + "rp/energie/"

amt.ICONS.setdefault("zap", '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>')
geld.BUCHUNGSART.setdefault("energie", "Energieausbau")
geld.BUCHUNGSART.setdefault("energiehandel", "Energiehandel")

geld.VORGABEN.setdefault("energie", {
    "haushalt_kwh": 318,          # kWh je Einwohner und Monat (Eurostat 2023: Inlandsnachfrage ohne Industrieanteil, bezogen auf die Einwohner des Spielgebiets)
    "industrie_gwh_je_mio": 0.0494,  # GWh je Mio. € BIP (Eurostat 2023: Industrieanteil der Inlandsnachfrage, bezogen auf das BIP)
    "mil_mwh_je_geraet": 8,       # MWh je Militärgerät und Monat
    "ver_stahl": 2.0, "ver_aluminium": 15.0, "ver_treibstoff": 0.6,   # MWh je Tonne Erzeugnis (Veredelung)
    "zuf_max": 45, "infra_max": 60, "ind_max": 70,   # größte Abzüge (Zufriedenheit in Punkten, Zielwerte der Indikatoren, Industrie)
    "bau_faktor": 100,            # % der Baukosten
    "instand_faktor": 100,        # % der Instandhaltungssätze (Kr je erzeugter GWh, siehe INSTAND)
    "bau_monate": 24,             # Monate, über die der Bau aus dem Industrie-Etat gezahlt wird
    "kauf_unter": 60,             # Versorgung in %, unter der am Energiemarkt gekauft werden darf
    "richt_treibstoff": 100000, "richt_aluminium": 100000, "richt_stahl": 100000,   # Tonnen im Lager für 100 % Bonus (und Verbrauch je Monatswechsel)
})
SAETZE = [("haushalt_kwh", "Verbrauch je Einwohner (kWh/Monat)"), ("industrie_gwh_je_mio", "Industrie (GWh je Mio. € BIP)"), ("mil_mwh_je_geraet", "Militärgerät (MWh/Monat je Gerät)"),
          ("ver_stahl", "Veredelung Stahl (MWh/t)"), ("ver_aluminium", "Veredelung Aluminium (MWh/t)"),
          ("ver_treibstoff", "Veredelung Treibstoff (MWh/t)"), ("zuf_max", "Höchstabzug Zufriedenheit (Punkte)"), ("infra_max", "Höchstabzug Infrastruktur (Punkte)"),
          ("ind_max", "Höchstabzug Industrie (Punkte)"), ("bau_faktor", "Baukosten (% der Tabelle)"), ("instand_faktor", "Instandhaltung (% der Tabelle)"),
          ("bau_monate", "Bau: Zahlung aus dem Industrie-Etat über (Monate)"), ("kauf_unter", "Zukauf am Markt erlaubt unter Versorgung (%)"),
          ("richt_treibstoff", "Treibstoff für 100 % Bonus (t)"), ("richt_aluminium", "Aluminium für 100 % Bonus (t)"), ("richt_stahl", "Stahl für 100 % Bonus (t)")]
BONUSWAREN = [("treibstoff", "Treibstoff"), ("aluminium", "Aluminium"), ("stahl", "Stahl")]
BONUS_MAX = {"treibstoff": 100.0, "aluminium": 100.0, "stahl": 10.0}   # % bei vollem Bonus: Energieerzeugung +, Effizienz der Industrie +, Preise für Militärgerät −
VEREDELUNG = {"stahl": "ver_stahl", "aluminium": "ver_aluminium", "treibstoff": "ver_treibstoff"}

# Jedes Kraftwerk hat eine feste Leistung (Schlüssel, Name, Leistung je Anlage in GWh/Monat, Preis je Anlage in Mio. Kr – hohe Preise, keine Bauzeit –, Klima-Gewicht)
TYPEN = [("kohle", "Kohlekraftwerk", 320, 9600, 1.00), ("gas", "Gaskraftwerk", 200, 4000, 0.55), ("oel", "Ölkraftwerk", 45, 900, 0.80), ("kern", "Kernkraftwerk", 800, 88000, 0.03),
         ("wasser", "Wasserkraftwerk", 35, 2450, 0.0), ("wind", "Windpark", 22, 660, 0.0), ("solar", "Solarpark", 9, 225, 0.0), ("biomasse", "Biomassekraftwerk", 10, 350, 0.25)]
TYP = {t[0]: t for t in TYPEN}
# Instandhaltung in Kr je erzeugter GWh und Monat (Richtwerte für Betrieb und Wartung der Anlagen; Grundlage der Lasten auf den Industrie-Etat)
# Fossile und Kernkraftwerke braucht ein Bodenerzvorkommen im Gebiet (Förderung laut Handel/Lagerstätten): Rohstoff-Schlüssel und Name. Uran gibt es noch nirgends.
ANFORDERUNG = {"kohle": ("braunkohle", "Braunkohle"), "gas": ("erdgas", "Erdgas"), "oel": ("erdoel", "Erdöl"), "kern": ("uran", "Uran")}
INSTAND = {"kohle": 9000, "gas": 5000, "oel": 8000, "kern": 12000, "wasser": 3000, "wind": 6000, "solar": 4500, "biomasse": 15000}
FARBEN = ["#6b7280", "#eb6834", "#8b5a2b", "#e34948", "#2a78d6", "#1baf7a", "#eda100", "#008300"]
FOSSIL = ("kohle", "gas", "oel")
KLIMA_NEUTRAL = 0.3375   # gewichteter Klima-Anteil der Standardmischung
SCHEMA = """
CREATE TABLE IF NOT EXISTS en_kraftwerke (id INTEGER PRIMARY KEY AUTOINCREMENT, schl TEXT NOT NULL, typ TEXT NOT NULL, gwh REAL NOT NULL, ab TEXT NOT NULL DEFAULT '',
    bezahlt INTEGER NOT NULL DEFAULT 0, von TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS en_kw_s ON en_kraftwerke (schl);
CREATE TABLE IF NOT EXISTS en_monat (periode TEXT NOT NULL, schl TEXT NOT NULL, angebot REAL NOT NULL, bev REAL NOT NULL, ind REAL NOT NULL, mil REAL NOT NULL,
    ver REAL NOT NULL, v_hh REAL NOT NULL, v_ind REAL NOT NULL, v_ges REAL NOT NULL, ew INTEGER NOT NULL DEFAULT 0, mix TEXT NOT NULL DEFAULT '', PRIMARY KEY (periode, schl));
CREATE TABLE IF NOT EXISTS en_nutzung (id INTEGER PRIMARY KEY AUTOINCREMENT, periode TEXT NOT NULL, schl TEXT NOT NULL, art TEXT NOT NULL, gwh REAL NOT NULL,
    text TEXT NOT NULL DEFAULT '', autor TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS en_nu_s ON en_nutzung (schl, periode);
CREATE TABLE IF NOT EXISTS en_lauf (periode TEXT PRIMARY KEY, zeit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS en_raten (id INTEGER PRIMARY KEY AUTOINCREMENT, schl TEXT NOT NULL, text TEXT NOT NULL, gesamt INTEGER NOT NULL, offen INTEGER NOT NULL,
    rate INTEGER NOT NULL, zuletzt TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS en_angebote (id INTEGER PRIMARY KEY AUTOINCREMENT, periode TEXT NOT NULL, schl TEXT NOT NULL, menge REAL NOT NULL, rest REAL NOT NULL,
    preis INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'offen', autor TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS en_an_p ON en_angebote (periode, status);
CREATE TABLE IF NOT EXISTS en_geschaefte (id INTEGER PRIMARY KEY AUTOINCREMENT, periode TEXT NOT NULL, angebot INTEGER NOT NULL, verkaeufer TEXT NOT NULL, kaeufer TEXT NOT NULL,
    menge REAL NOT NULL, preis INTEGER NOT NULL, summe INTEGER NOT NULL, autor TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS en_ge_p ON en_geschaefte (periode, verkaeufer, kaeufer);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.execute("DELETE FROM en_kraftwerke WHERE von='Erstausstattung'")   # frühere erfundene Erstausstattung (mit Reserve und Kernkraft) – wird real neu angelegt
    con.commit()


def einstellungen(con):
    return dict(geld.VORGABEN["energie"], **geld.einstellung(con, "energie"))


def _de(x, st=1):
    return f"{x:,.{st}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def ueberschuss_pz(b):
    """Überschuss in % des Bedarfs als HTML „(+X %)“ – nur bei Überschuss, sonst leer."""
    if b["bedarf"] <= 0 or b["frei"] <= 0.0005 * b["bedarf"]:
        return ""
    return f' <small>(+{_de(b["frei"] / b["bedarf"] * 100, 0)} %)</small>'


def gwh_text(x):
    """GWh, ab 10.000 als TWh."""
    return f"{_de(x / 1000, 1)} TWh" if abs(x) >= 10000 else f"{_de(x, 0 if abs(x) >= 100 else 1)} GWh"


# ---------------------------------------------------------------- Bevölkerung, Bedarf

_ZB = {"t": 0.0, "d": None}


def _staaten(con):
    if time.time() - _ZB["t"] > 120 or _ZB["d"] is None:
        import aufkommen
        _ZB["d"] = aufkommen.staaten_bip(con)
        _ZB["t"] = time.time()
    return _ZB["d"]


def bevoelkerung(con, schl, periode):
    """(Einwohner, BIP in Mio. € je Jahr) des Haushalts im Monat: Werte der Karte × Bevölkerungsfaktor der Entwicklung (letzter gebuchter Stand)."""
    import entwicklung
    ew = bip = 0.0
    for s, b, e, km in _staaten(con):
        if (schl == "reich" and geld.ist_reichsgebiet(s)) or schl == "ts-" + s["id"]:
            ew += e
            bip += b
    f = entwicklung.zustand_vor(con, schl, periode).get("bev_faktor", 1.0)
    return ew * f, bip * f


def _mil_einheiten(con, schl):
    stelle = "verteidigung" if schl == "reich" else "vt-" + schl[3:]
    try:
        r = con.execute("SELECT COALESCE(SUM(anzahl),0) n FROM vt_bestand WHERE stelle=?", (stelle,)).fetchone()
        return int(r["n"] or 0)
    except Exception:
        return 0


def veredelung_verbrauch(con, schl, periode):
    r = con.execute("SELECT COALESCE(SUM(gwh),0) g FROM en_nutzung WHERE schl=? AND periode=? AND art='veredelung'", (schl, periode)).fetchone()
    return float(r["g"] or 0)


def _name(con, schl):
    import handel
    return handel.halter(con).get(schl, schl)


# ---------------------------------------------------------------- Kraftwerke

_GRUND = {"t": 0.0, "d": None}


def grundausstattung():
    """{schl: {Träger: GWh je Monat}} der realen Stromerzeugung (karte_daten/energie.json)."""
    import os
    pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "karte_daten", "energie.json")
    try:
        m = os.path.getmtime(pfad)
        if _GRUND["d"] is None or _GRUND["t"] != m:
            _GRUND["d"] = json.load(open(pfad, encoding="utf-8"))["erzeugung_gwh_monat"]
            _GRUND["t"] = m
    except (OSError, ValueError, KeyError):
        log.warning("energie.json fehlt – keine Grundausstattung")
        return {}
    return _GRUND["d"]


def sichern(con, schl, periode=None):
    """Grundausstattung: die reale Stromerzeugung des Gebiets (einmalig je Haushalt; Gebiete ohne Eintrag erzeugen nichts)."""
    if con.execute("SELECT 1 FROM en_kraftwerke WHERE schl=? LIMIT 1", (schl,)).fetchone():
        return
    eintrag = grundausstattung().get(schl, {})
    for typ, gwh in eintrag.items():
        if typ in TYP and gwh > 0:
            con.execute("INSERT INTO en_kraftwerke (schl, typ, gwh, ab, von, zeit) VALUES (?,?,?,?,?,?)", (schl, typ, round(gwh, 3), "", "Grundausstattung (real)", int(time.time())))
    if eintrag:
        con.commit()


def kraftwerke(con, schl):
    return con.execute("SELECT * FROM en_kraftwerke WHERE schl=? ORDER BY typ, id", (schl,)).fetchall()


def angebot(con, schl, periode):
    """Erzeugung im Monat: Kraftwerke, die in Betrieb sind (Bauende erreicht) – {typ: GWh}."""
    sichern(con, schl, periode)
    out = {}
    for r in kraftwerke(con, schl):
        if not r["ab"] or r["ab"] <= periode:
            out[r["typ"]] = out.get(r["typ"], 0.0) + float(r["gwh"])
    return out


# ---------------------------------------------------------------- Bilanz

_CACHE = {}
_WECHSEL = {"p": ""}


def boni_berechnen(con, schl, basis_bedarf, s):
    """{Ware: {lager, richt, anteil}}: Bonus-Anteil 0–1 = Lagerbestand ÷ Richtmenge (feste Tonnenzahl für 100 %)."""
    import handel
    lag = handel.lager(con, schl)
    out = {}
    for w, _n in BONUSWAREN:
        richt = max(1.0, float(s["richt_" + w]))
        st = float(lag.get(w, 0))
        out[w] = {"lager": st, "richt": richt, "anteil": max(0.0, min(1.0, st / richt))}
    return out


def stahl_preisbonus(con, schl):
    """Preissenkung für Militärgerät in % durch Stahl im Lager (0 bis 10)."""
    try:
        return BONUS_MAX["stahl"] * bilanz(con, schl)["boni"]["stahl"]["anteil"]
    except Exception:
        return 0.0


def monatswechsel(con):
    """Einmal je Monat: Die Richtmenge der Boni-Erzeugnisse wird aus dem Lager verbraucht (der Bonus ist weg, Überschuss bleibt). Der allererste Lauf verbraucht nichts."""
    import etatplan
    p = etatplan.monat_heute()
    if _WECHSEL["p"] == p:
        return
    _WECHSEL["p"] = p
    if con.execute("SELECT 1 FROM en_lauf WHERE periode=?", (p,)).fetchone():
        return
    erster = con.execute("SELECT 1 FROM en_lauf LIMIT 1").fetchone() is None
    con.execute("INSERT INTO en_lauf (periode, zeit) VALUES (?,?)", (p, int(time.time())))
    if not erster:
        import handel
        s = einstellungen(con)
        for schl in handel.halter(con):
            lag = handel.lager(con, schl)
            for w, _n in BONUSWAREN:
                nehmen = int(min(float(lag.get(w, 0)), float(s["richt_" + w])))
                if nehmen > 0:
                    handel.lager_aendern(con, schl, w, -nehmen)
    con.commit()
    leeren()


def leeren():
    _CACHE.clear()


def bilanz(con, schl, periode=None, frisch=False):
    """Energiebilanz eines Haushalts im Monat. Verteilung bei Knappheit: Bevölkerung → Militär → Industrie und Veredelung."""
    import etatplan
    periode = periode or etatplan.monat_heute()
    z = _CACHE.get((schl, periode))
    if z and not frisch and time.time() - z[0] < 20:
        return z[1]
    s = einstellungen(con)
    ew, bip = bevoelkerung(con, schl, periode)
    mix = angebot(con, schl, periode)
    erz_roh = sum(mix.values())
    zukauf, verkauf = markt_fluesse(con, schl, periode)
    reserviert = reservierte_menge(con, schl, periode)
    hh = ew * float(s["haushalt_kwh"]) / 1e6
    ind_roh = bip / 12 * float(s["industrie_gwh_je_mio"])
    n_mil = _mil_einheiten(con, schl)
    mil = n_mil * float(s["mil_mwh_je_geraet"]) / 1000
    boni = boni_berechnen(con, schl, hh + ind_roh + mil, s)
    erz = erz_roh * (1 + BONUS_MAX["treibstoff"] / 100 * boni["treibstoff"]["anteil"])   # Treibstoff: Energiegewinnung effizienter
    ind = ind_roh / (1 + BONUS_MAX["aluminium"] / 100 * boni["aluminium"]["anteil"])     # Aluminium: Industrie effizienter
    S = erz + zukauf - verkauf
    ver = veredelung_verbrauch(con, schl, periode)
    rest = S
    g_hh = min(rest, hh); rest -= g_hh
    g_mil = min(rest, mil); rest -= g_mil
    g_ind = min(rest, ind + ver)
    bedarf = hh + ind + mil + ver
    v = lambda g, b: (g / b) if b > 1e-9 else 1.0
    fossil = sum(mix.get(t, 0) for t in FOSSIL)
    klima = sum(mix.get(t, 0) * TYP[t][4] for t in mix) / erz_roh if erz_roh else 0.0
    b = {"periode": periode, "schl": schl, "ew": ew, "bip": bip, "hh": hh, "ind": ind, "mil": mil, "ver": ver, "bedarf": bedarf, "angebot": S, "mix": mix,
         "v_hh": v(g_hh, hh), "v_mil": v(g_mil, mil), "v_ind": v(g_ind, ind + ver), "v_ges": min(1.0, v(S, bedarf)), "frei": S - bedarf, "n_mil": n_mil,
         "erzeugung": erz, "erzeugung_roh": erz_roh, "boni": boni, "zukauf": zukauf, "verkauf": verkauf, "reserviert": reserviert, "frei_ver": S - bedarf - reserviert,
         "markt_frei": max(0.0, erz - verkauf - bedarf - reserviert),
         "fossil": fossil / erz_roh * 100 if erz_roh else 0.0, "erneuerbar": sum(mix.get(t, 0) for t in ("wasser", "wind", "solar", "biomasse")) / erz_roh * 100 if erz_roh else 0.0,
         "klima": klima, "einstellung": s}
    _CACHE[(schl, periode)] = (time.time(), b)
    return b


STUFEN = [("gut", "Gut versorgt", 85), ("moderat", "Moderate Versorgung", 60), ("mangel", "Energiemangel", 15), ("not", "Energienot", 0)]
# Stärke der Mali (Anteil der Höchstabzüge) je Versorgungswert in %: Stufen 100–85 gut, 84–60 moderat, 59–15 Mangel, 14–0 Energienot
_STAERKE = [(85, 0.0), (84, 0.10), (60, 0.35), (59, 0.45), (15, 0.85), (14, 1.0), (0, 1.0)]


def stufe(v):
    """(Schlüssel, Name) der Versorgungsstufe zu einem Versorgungswert 0–1."""
    p = round(v * 100)   # wie angezeigt: ganze Prozent
    for schl, name, ab in STUFEN:
        if p >= ab or ab == 0:
            return schl, name
    return STUFEN[-1][:2]


def staerke(v):
    """Stärke der Mali 0–1 zu einem Versorgungswert 0–1 (stückweise linear)."""
    p = max(0.0, min(100.0, float(round(v * 100))))
    if p >= _STAERKE[0][0]:
        return 0.0
    for (p1, s1), (p2, s2) in zip(_STAERKE, _STAERKE[1:]):
        if p2 <= p <= p1:
            return s2 + (s1 - s2) * (p - p2) / (p1 - p2) if p1 != p2 else s1
    return 1.0


def lage(b):
    """(Stufe, Text) der Versorgung (gut | moderat | mangel | not)."""
    st, name = stufe(b["v_ges"])
    return st, f'{name} ({_de(b["v_ges"] * 100, 0)} %)'


# ---------------------------------------------------------------- Folgen (entwicklung.entwickeln)

def wirkungen_fuer(con, schl, periode):
    """(Effekte, Verschiebungen) wie krisen.wirkungen_fuer: Mali nach Versorgungsstufe (Versorgung ≥ 85 % ohne Folgen)."""
    try:
        b = bilanz(con, schl, periode)
    except Exception:
        log.exception("Energiebilanz von %s nicht berechenbar", schl)
        return [], {}
    s = b["einstellung"]
    effekte, shift = [], {}
    st, name = stufe(b["v_ges"])
    sv = staerke(b["v_ges"])
    if sv > 0:
        zuf = -float(s["zuf_max"]) * max(sv, staerke(b["v_hh"]))   # fehlt die Bevölkerung selbst, wiegt das schwerer
        effekte.append({"hebel": "zuf_pt", "wert": zuf, "titel": name, "modul": "energie",
                        "text": f'Versorgung {_de(b["v_ges"] * 100, 0)} %: Stromausfälle und Kurzarbeit drücken die Stimmung'})
        shift["wasser"] = shift["muell"] = shift["strassen"] = -float(s["infra_max"]) * sv
        shift["industrie"] = -float(s["ind_max"]) * sv
        effekte.append({"hebel": "kopf_pct", "wert": -min(10.0, float(s["ind_max"]) / 7 * sv), "titel": name + ": Industrie", "modul": "energie",
                        "text": "Die Produktion läuft nur eingeschränkt, das Einkommen je Kopf sinkt"})
        if st == "not":
            effekte.append({"hebel": "bev_pp", "wert": -0.15, "titel": "Energienot: Abwanderung", "modul": "energie", "text": "Menschen verlassen das Land"})
    shift["co2"] = 30.0 * (b["klima"] - KLIMA_NEUTRAL)   # fossile Erzeugung belastet das Klima, saubere entlastet es
    return effekte, shift


# ---------------------------------------------------------------- Veredelung (handel.veredeln)

def veredelung_gwh(con, produkt, menge):
    s = einstellungen(con)
    return float(s.get(VEREDELUNG.get(produkt, ""), 0)) * float(menge) / 1000


def veredelung_pruefen(con, schl, produkt, menge):
    """Reicht die freie Energie des Monats? Gibt den Bedarf in GWh zurück oder wirft geld.Fehler."""
    gwh = veredelung_gwh(con, produkt, menge)
    if gwh <= 0:
        return 0.0
    b = bilanz(con, schl, frisch=True)
    if gwh > max(0.0, b["frei_ver"]) + 1e-9:
        raise geld.Fehler(f'Zu wenig Energie für die Veredelung: benötigt {gwh_text(gwh)}, frei sind in diesem Monat {gwh_text(max(0.0, b["frei_ver"]))}.')
    return gwh


def veredelung_buchen(con, schl, gwh, text, k):
    import etatplan
    if gwh > 0:
        con.execute("INSERT INTO en_nutzung (periode, schl, art, gwh, text, autor, zeit) VALUES (?,?,?,?,?,?,?)",
                    (etatplan.monat_heute(), schl, "veredelung", gwh, text[:200], k["name"] if k else "System", int(time.time())))
        leeren()


def hinweis_html(con):
    s = einstellungen(con)
    return (f'Das Lager gibt Boni bis Monatsende (<a href="{PFAD}">Energie</a>). Energie je Tonne: Stahl {_de(float(s["ver_stahl"]), 1)} MWh, '
            f'Aluminium {_de(float(s["ver_aluminium"]), 1)} MWh, Treibstoff {_de(float(s["ver_treibstoff"]), 1)} MWh.')


# ---------------------------------------------------------------- Militär (verteidigung.instandhaltung)

def mil_versorgung(con, schl):
    """Anteil der Energieversorgung des Militärs (0–1) im laufenden Monat."""
    try:
        return bilanz(con, schl)["v_mil"]
    except Exception:
        return 1.0


# ---------------------------------------------------------------- Monatswerte (aufkommen.ausfuehren)

def speichern(con, periode, liste):
    """Hält die Energiebilanz aller Haushalte des gebuchten Monats fest."""
    import json
    schl_liste = ["reich"] + ["ts-" + x["staat"] for x in liste if not x["reichsgebiet"]]
    for schl in schl_liste:
        try:
            b = bilanz(con, schl, periode, frisch=True)
        except Exception:
            log.exception("Energiemonat %s/%s nicht speicherbar", periode, schl)
            continue
        con.execute("INSERT OR REPLACE INTO en_monat (periode, schl, angebot, bev, ind, mil, ver, v_hh, v_ind, v_ges, ew, mix) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (periode, schl, b["angebot"], b["hh"], b["ind"], b["mil"], b["ver"], b["v_hh"], b["v_ind"], b["v_ges"], int(b["ew"]), json.dumps(b["mix"])))
    for r in con.execute("SELECT * FROM en_raten WHERE offen>0 AND zuletzt<>?", (periode,)).fetchall():   # die Monatsrate des Baus ist beglichen
        con.execute("UPDATE en_raten SET offen=?, zuletzt=? WHERE id=?", (max(0, r["offen"] - r["rate"]), periode, r["id"]))
    leeren()


# ---------------------------------------------------------------- Ausbau und Stilllegung

def baukosten(con, typ, anzahl):
    s = einstellungen(con)
    return int(round(anzahl * TYP[typ][3] * 1e6 * 100 * float(s["bau_faktor"]) / 100))   # Heller


def lasten(con, schl, periode=None):
    """Monatliche Lasten der Kraftwerke auf den Industrie-Etat (Heller): Instandhaltung und Raten laufender Bauten."""
    import etatplan
    s = einstellungen(con)
    mix = angebot(con, schl, periode or etatplan.monat_heute())
    instand = int(round(sum(g * INSTAND.get(t, 0) for t, g in mix.items()) * float(s["instand_faktor"]) / 100 * 100))
    raten = sum(min(r["rate"], r["offen"]) for r in con.execute("SELECT rate, offen FROM en_raten WHERE schl=? AND offen>0", (schl,)))
    return {"instand": instand, "raten": int(raten), "summe": instand + int(raten)}


_IND = {}


def industrie_betrag(con, schl):
    """Industrie-Etat des Haushalts im laufenden Monat (Heller): Politikfeld „Industrie“ der Etatverteilung (Reich: Summe über alle Teilstaaten)."""
    import aufkommen
    import etatplan
    z = _IND.get(schl)
    if z and time.time() - z[0] < 20:
        return z[1]
    liste = aufkommen.berechnen(con, periode=etatplan.monat_heute())
    if schl == "reich":
        b = sum(x["verteilung_reich"].get("industrie", 0) for x in liste)
    else:
        x = next((y for y in liste if "ts-" + y["staat"] == schl), None)
        b = (x["verteilung_land"] or {}).get("industrie", 0) if x else 0
    _IND[schl] = (time.time(), int(b))
    return int(b)


def industrie_faktor(con, schl, periode, betrag):
    """Anteil des Industrie-Etats, der der Industrie selbst bleibt (1 = keine Lasten): wirkt in entwicklung.entwickeln auf die Industrie-Investitionen."""
    try:
        last = lasten(con, schl, periode)["summe"]
    except Exception:
        log.exception("Lasten von %s nicht berechenbar", schl)
        return 1.0
    if last <= 0:
        return 1.0
    return max(0.0, 1.0 - last / betrag) if betrag > 0 else 0.0


_FOERD = {"t": 0.0, "d": {}}


def baubar(con, schl, typ):
    """(ja/nein, Grund): Wind, Solar, Wasser und Biomasse lassen sich überall bauen; die übrigen brauchen das passende Bodenerzvorkommen im Gebiet."""
    if typ not in ANFORDERUNG:
        return True, ""
    import handel
    if time.time() - _FOERD["t"] > 60:
        _FOERD["d"], _FOERD["t"] = handel.foerderung(con), time.time()
    res, name = ANFORDERUNG[typ]
    if _FOERD["d"].get(schl, {}).get(res, 0) > 0:
        return True, ""
    return False, f"kein {name}vorkommen"


def ausbauen(con, schl, typ, anzahl, k):
    """Baut `anzahl` Kraftwerke sofort. Bezahlt wird aus dem Industrie-Etat: als monatliche Rate über „bau_monate“ Monate, zusätzlich zur Instandhaltung."""
    if typ not in TYP:
        raise geld.Fehler("Bitte ein Kraftwerk wählen.")
    if not 1 <= anzahl <= 100:
        raise geld.Fehler("Bitte eine Anzahl zwischen 1 und 100 angeben.")
    ok, grund = baubar(con, schl, typ)
    if not ok:
        raise geld.Fehler(f'{TYP[typ][1]} lässt sich hier nicht bauen: {grund} im Gebiet.')
    s = einstellungen(con)
    preis = baukosten(con, typ, anzahl)
    gwh = anzahl * TYP[typ][2]
    rate = -(-preis // max(1, int(s["bau_monate"])))
    neu_instand = int(round(gwh * INSTAND.get(typ, 0) * float(s["instand_faktor"]) / 100 * 100))
    sichern(con, schl)
    etat, last = industrie_betrag(con, schl), lasten(con, schl)["summe"]
    if last + rate + neu_instand > etat:
        raise geld.Fehler(f'Der Industrie-Etat reicht nicht: {anzahl} × {TYP[typ][1]} brauchen {geld.mark(rate + neu_instand)} im Monat (Rate und Instandhaltung), '
                          f'frei sind {geld.mark(max(0, etat - last))}.')
    con.execute("INSERT INTO en_kraftwerke (schl, typ, gwh, ab, bezahlt, von, zeit) VALUES (?,?,?,?,?,?,?)", (schl, typ, gwh, "", preis, k["name"], int(time.time())))
    con.execute("INSERT INTO en_raten (schl, text, gesamt, offen, rate, zeit) VALUES (?,?,?,?,?,?)", (schl, f"{anzahl} × {TYP[typ][1]}", preis, preis, rate, int(time.time())))
    geld.protokoll(con, k, "Energie: Ausbau", f"{_name(con, schl)}: {anzahl} × {TYP[typ][1]} ({gwh_text(gwh)}/Monat), Preis {geld.mark(preis)} aus dem Industrie-Etat, Rate {geld.mark(rate)}")
    _IND.clear()
    leeren()
    return preis, rate


# ---------------------------------------------------------------- Energiemarkt

def markt_fluesse(con, schl, periode):
    """(Zukauf, Verkauf) in GWh im Monat."""
    r = con.execute("SELECT COALESCE(SUM(CASE WHEN kaeufer=? THEN menge END),0) z, COALESCE(SUM(CASE WHEN verkaeufer=? THEN menge END),0) v "
                    "FROM en_geschaefte WHERE periode=?", (schl, schl, periode)).fetchone()
    return float(r["z"]), float(r["v"])


def reservierte_menge(con, schl, periode):
    r = con.execute("SELECT COALESCE(SUM(rest),0) m FROM en_angebote WHERE schl=? AND periode=? AND status='offen'", (schl, periode)).fetchone()
    return float(r["m"])


def kauf_erlaubt(b):
    return round(b["v_ges"] * 100) < float(b["einstellung"]["kauf_unter"])


def angebote(con, periode=None):
    import etatplan
    return con.execute("SELECT * FROM en_angebote WHERE periode=? AND status='offen' AND rest>0.0001 ORDER BY preis, id", (periode or etatplan.monat_heute(),)).fetchall()


def anbieten(con, schl, menge, preis, k):
    """Bietet Überschuss (GWh) zu `preis` Heller je GWh an; die Menge ist bis zum Verkauf oder Rückzug reserviert."""
    import etatplan
    if menge <= 0 or preis <= 0:
        raise geld.Fehler("Bitte Menge und Preis angeben.")
    if preis > 10 ** 14:
        raise geld.Fehler("Der Preis ist zu hoch.")
    b = bilanz(con, schl, frisch=True)
    if menge > b["markt_frei"] + 1e-9:
        raise geld.Fehler(f'Nur {gwh_text(b["markt_frei"])} Überschuss sind frei verkäuflich.')
    con.execute("INSERT INTO en_angebote (periode, schl, menge, rest, preis, autor, zeit) VALUES (?,?,?,?,?,?,?)", (etatplan.monat_heute(), schl, menge, menge, int(preis), k["name"], int(time.time())))
    geld.protokoll(con, k, "Energie: Angebot", f"{_name(con, schl)} bietet {gwh_text(menge)} zu {geld.mark(int(preis))} je GWh an")
    leeren()


def zurueckziehen(con, angebot, schl, k):
    a = con.execute("SELECT * FROM en_angebote WHERE id=?", (angebot,)).fetchone()
    if not a or a["schl"] != schl or a["status"] != "offen":
        raise geld.Fehler("Dieses Angebot gibt es nicht (mehr).")
    con.execute("UPDATE en_angebote SET status='zurueck' WHERE id=?", (angebot,))
    leeren()


def kaufen(con, angebot, schl, prozent, k):
    """Kauft `prozent` % der Menge eines Angebots für den laufenden Monat; das Angebot bleibt offen, bis nichts mehr übrig ist (auch mehrere Käufer).
    Gibt (Summe, Verkäufer-Name, GWh) zurück."""
    import etatplan
    import handel
    a = con.execute("SELECT * FROM en_angebote WHERE id=?", (angebot,)).fetchone()
    if not a or a["status"] != "offen" or a["periode"] != etatplan.monat_heute() or a["rest"] <= 1e-6:
        raise geld.Fehler("Dieses Angebot gibt es nicht mehr.")
    if a["schl"] == schl:
        raise geld.Fehler("Eigene Angebote lassen sich nicht kaufen.")
    rest_pz = a["rest"] / a["menge"] * 100
    if prozent <= 0 or prozent > rest_pz + 1e-6:
        raise geld.Fehler(f'Bitte einen Anteil bis {_de(rest_pz, 1)} % angeben (so viel vom Angebot ist noch frei).')
    b = bilanz(con, schl, frisch=True)
    if not kauf_erlaubt(b):
        raise geld.Fehler(f'Zukaufen dürfen nur Haushalte mit einer Versorgung unter {_de(float(b["einstellung"]["kauf_unter"]), 0)} %.')
    menge = a["rest"] if prozent >= rest_pz - 1e-6 else a["menge"] * prozent / 100
    fehl = max(0.0, b["bedarf"] - b["angebot"])
    if menge > fehl + 1e-9:
        raise geld.Fehler(f'Ihr Fehlbetrag ({gwh_text(fehl)}) entspricht höchstens {_de(fehl / a["menge"] * 100, 1)} % dieses Angebots.')
    summe = int(round(menge * a["preis"]))
    von, an = handel.kasse(con, schl), handel.kasse(con, a["schl"])
    if von["saldo"] < summe:
        raise geld.Fehler(f'Die {von["name"]} ist nicht gedeckt: {_de(prozent, 1)} % ({gwh_text(menge)}) kosten {geld.mark(summe)}.')
    if summe > 0:
        geld.buchen(con, von["id"], an["id"], summe, "energiehandel", f"Energie: {gwh_text(menge)} zu {geld.mark(a['preis'])} je GWh", k, bezug=f"ENERGIE-MARKT-{angebot}")
    rest = max(0.0, a["rest"] - menge)
    con.execute("UPDATE en_angebote SET rest=?, status=? WHERE id=?", (rest, "offen" if rest > 1e-6 else "verkauft", angebot))
    con.execute("INSERT INTO en_geschaefte (periode, angebot, verkaeufer, kaeufer, menge, preis, summe, autor, zeit) VALUES (?,?,?,?,?,?,?,?,?)",
                (a["periode"], angebot, a["schl"], schl, menge, a["preis"], summe, k["name"], int(time.time())))
    geld.protokoll(con, k, "Energie: Kauf", f"{_name(con, schl)} kauft von {_name(con, a['schl'])}: {_de(prozent, 1)} % ({gwh_text(menge)}) für {geld.mark(summe)}")
    leeren()
    return summe, _name(con, a["schl"]), menge


# ---------------------------------------------------------------- Seite

CSS = """<style>
.kennzahlen b small{font-size:13px;font-weight:500;color:var(--grau,#666)}
.ee-bar{display:flex;height:22px;border-radius:7px;overflow:hidden;background:var(--hell,#eee);margin:8px 0}
.ee-bar i{display:block;height:100%}
.ee-leg{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px;margin:4px 0 12px}.ee-leg span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;background:var(--c);margin-right:6px}
.ee-lage{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--linie);border-radius:12px;padding:12px 16px;margin:12px 0;background:#fff}
.ee-lage .icon{width:20px;height:20px;flex:none;margin-top:2px}.ee-lage.moderat{border-color:#eda100}.ee-lage.mangel{border-color:#c0392b}.ee-lage.not{border-color:#c0392b;box-shadow:0 0 0 2px #c0392b;background:#fdf1f0}
.ee-diagramm{width:100%;height:auto;max-height:260px}.ee-diagramm text{font-size:11px;fill:var(--grau,#666)}
.ee-form{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end;margin:10px 0}.ee-form div{display:flex;flex-direction:column;gap:3px}
.ee-tab td:nth-child(n+2){text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
</style>"""


def _ziele(con):
    import handel
    h = handel.halter(con)
    return [("reich", "Das Reich")] + sorted([(s, n) for s, n in h.items() if s != "reich"], key=lambda x: x[1])


def _balken(teile):
    """Gestapelter Balken: [(Name, Wert, Farbe)]."""
    summe = sum(w for _, w, _ in teile) or 1
    bar = "".join(f'<i style="width:{w / summe * 100:.2f}%;background:{c}" title="{esc(n)}: {_de(w / summe * 100, 1)} %"></i>' for n, w, c in teile if w > 0)
    leg = "".join(f'<span style="--c:{c}">{esc(n)} {_de(w / summe * 100, 1)} %</span>' for n, w, c in teile if w > 0)
    return f'<div class="ee-bar" role="img">{bar}</div><div class="ee-leg">{leg}</div>'


def _verlauf_svg(zeilen):
    """Liniendiagramm Angebot und Bedarf (GWh) der gebuchten Monate: zeilen = [(Monat, angebot, bedarf)] aufsteigend."""
    if len(zeilen) < 2:
        return ""
    w, h, l, r, t, u = 640, 220, 56, 14, 14, 30
    hoch = max(max(a, b) for _, a, b in zeilen) * 1.08 or 1
    x = lambda i: l + (w - l - r) * i / (len(zeilen) - 1)
    y = lambda v: t + (h - t - u) * (1 - v / hoch)
    pfad = lambda idx, farbe, dash="": (f'<polyline fill="none" stroke="{farbe}" stroke-width="2.4" {dash} points="' + " ".join(f"{x(i):.1f},{y(z[idx]):.1f}" for i, z in enumerate(zeilen)) + '"/>')
    achse = "".join(f'<line x1="{l}" x2="{w - r}" y1="{y(hoch * f):.1f}" y2="{y(hoch * f):.1f}" stroke="#ddd"/><text x="{l - 6}" y="{y(hoch * f) + 4:.1f}" text-anchor="end">{gwh_text(hoch * f)}</text>' for f in (0, .5, 1))
    ticks = "".join(f'<text x="{x(i):.1f}" y="{h - 8}" text-anchor="middle">{esc(z[0][2:])}</text>' for i, z in enumerate(zeilen) if i % max(1, len(zeilen) // 6) == 0)
    return (f'<svg class="ee-diagramm" viewBox="0 0 {w} {h}" role="img" aria-label="Energieangebot und Bedarf im Verlauf">{achse}{ticks}'
            f'{pfad(1, "#1baf7a")}{pfad(2, "#e34948", "stroke-dasharray=\"6 4\"")}</svg>'
            f'<div class="ee-leg"><span style="--c:#1baf7a">Angebot</span><span style="--c:#e34948">Bedarf</span></div>')


class Roh(str):
    """Bereits maskierter HTML-Text (kz setzt ihn unverändert ein)."""


def _auf(titel, inhalt, symbol="clock"):
    return f'<details class="sa-auf"><summary>{amt.ic(symbol)}{esc(titel)}</summary>{inhalt}</details>'


def _seitenhtml(request, k, con, ziel):
    import etatplan
    import entwicklung
    b = bilanz(con, ziel, frisch=True)
    name = dict(_ziele(con))[ziel]
    stufe_, text = lage(b)
    darf = etatplan.darf_aendern(con, k, ziel)
    kz = lambda xs: f'<div class="kennzahlen">{"".join(f"<div><b>{v if isinstance(v, Roh) else esc(v)}</b>{esc(t)}</div>" for t, v in xs)}</div>'
    kennz = [("Versorgung", Roh(f'{_de(b["v_ges"] * 100, 0)} %{ueberschuss_pz(b)}')), ("Erzeugung", gwh_text(b["erzeugung"])), ("Bedarf", gwh_text(b["bedarf"])),
             ("Überschuss" if b["frei"] >= 0 else "Fehlbetrag", gwh_text(abs(b["frei"]))), ("Erneuerbare", f'{_de(b["erneuerbar"], 0)} %')]
    if b["boni"]["treibstoff"]["anteil"] > 0:
        kennz.append(("Treibstoff-Bonus", f'+{_de(b["boni"]["treibstoff"]["anteil"] * BONUS_MAX["treibstoff"], 0)} %'))
    if b["zukauf"] > 0:
        kennz.append(("Zugekauft", gwh_text(b["zukauf"])))
    if b["verkauf"] > 0:
        kennz.append(("Verkauft", gwh_text(b["verkauf"])))
    kopf = kz(kennz)
    symbol = "check" if stufe_ == "gut" else "triangle-alert"
    folgen = []
    ef, shift = wirkungen_fuer(con, ziel, b["periode"])
    for e in ef:
        folgen.append(f'<li><b>{esc(e["titel"])}</b> ({_de(e["wert"], 1)} {"Punkte" if e["hebel"] == "zuf_pt" else "%"})</li>')
    for i, t in (("wasser", "Infrastruktur"), ("industrie", "Industrie")):
        if shift.get(i, 0) < -0.05:
            folgen.append(f'<li><b>{t}</b> ({_de(shift[i], 0)} Punkte Zielwert)</li>')
    lage_html = f'<div class="ee-lage {stufe_}">{amt.ic(symbol)}<div><b>{esc(text)}</b>' + (f'<ul>{"".join(folgen)}</ul>' if folgen else "") + '</div></div>'
    # Bedarf
    verbr = [("Bevölkerung", b["hh"], b["v_hh"], "#2a78d6"), ("Militär", b["mil"], b["v_mil"], "#6250d6"), ("Industrie", b["ind"], b["v_ind"], "#eb6834"), ("Veredelung", b["ver"], b["v_ind"], "#eda100")]
    zeilen = [(esc(n), gwh_text(w), f'{_de(v * 100, 0)} %') for n, w, v, _ in verbr if w > 0]
    bedarf_html = _balken([(n, w, c) for n, w, _, c in verbr]) + amt.tabelle(["Verbraucher", "Bedarf", "Versorgt"], zeilen, klasse="ee-tab")
    # Erzeugung
    mix_teile = [(TYP[t][1], b["mix"].get(t, 0), FARBEN[i]) for i, (t, *_r) in enumerate(TYPEN)]
    kw = [(esc(TYP[t][1]), gwh_text(g), f'{_de(g / b["angebot"] * 100, 0)} %') for t, g in sorted(b["mix"].items(), key=lambda x: -x[1]) if g > 0 and b["angebot"]]
    ausbau = ""
    if darf:
        opt = "".join(f'<option value="{t}"{"" if baubar(con, ziel, t)[0] else " disabled"}>{esc(n)} – {gwh_text(g)}/Monat, {_de(p * float(b["einstellung"]["bau_faktor"]) / 100 / 1000, 1)} Mrd. Kr'
                      f'{"" if baubar(con, ziel, t)[0] else " (nicht verfügbar: " + baubar(con, ziel, t)[1] + ")"}</option>' for t, n, g, p, _ in TYPEN)
        ausbau = (f'<h3>Kraftwerke bauen</h3><form class="ee-form" method="post" action="{PFAD}ausbau">{amt.csrf_feld(request)}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                  f'<div><label for="ea-t">Kraftwerk</label><select id="ea-t" name="typ">{opt}</select></div>'
                  '<div><label for="ea-n">Anzahl</label><input id="ea-n" name="anzahl" type="number" min="1" max="100" value="1" required></div>'
                  f'<button class="btn" type="submit">{amt.ic("zap")}Bauen</button></form>'
                  f'<p class="sa-hinweis">Bezahlt aus dem Industrie-Etat, in {int(b["einstellung"]["bau_monate"])} Monatsraten.</p>')
    etat, ls = industrie_betrag(con, ziel), lasten(con, ziel)
    etat_html = (f'<p class="sa-hinweis">Industrie-Etat {geld.mark_kurz(etat)} im Monat: Die Kraftwerke binden {geld.mark_kurz(ls["summe"])} '
                 f'(Instandhaltung {geld.mark_kurz(ls["instand"])}, Bauraten {geld.mark_kurz(ls["raten"])}), frei {geld.mark_kurz(max(0, etat - ls["summe"]))}.</p>')
    n_ang = len(angebote(con))
    markt_link = f'<p><a href="{PFAD}markt/?ziel={esc(ziel)}">{amt.ic("arrow-right-left")}Energiemarkt ({n_ang} Angebot{"e" if n_ang != 1 else ""})</a></p>'
    mix_html = _balken(mix_teile) + amt.tabelle(["Kraftwerk", "Erzeugung", "Anteil"], kw, "Keine Kraftwerke.", klasse="ee-tab") + etat_html + ausbau + markt_link
    # Veredelungs-Boni des Monats
    wirkung = {"treibstoff": ("Energieerzeugung", "+"), "aluminium": ("Effizienz der Industrie", "+"), "stahl": ("Preise für Militärgerät", "−")}
    bz = [(esc(n), f'{_de(b["boni"][w]["lager"], 0)} t', f'{_de(b["boni"][w]["richt"], 0)} t', f'{wirkung[w][1]}{_de(b["boni"][w]["anteil"] * BONUS_MAX[w], 0)} % {wirkung[w][0]}')
          for w, n in BONUSWAREN]
    boni_html = ("<h2>Veredelung</h2>" + amt.tabelle(["Erzeugnis", "Im Lager", "Richtmenge", "Bonus diesen Monat"], bz, klasse="ee-tab")
                 + f'<p><a href="{sa.PFAD}handel/veredelung/?ziel={esc(ziel)}">{amt.ic("arrow-right-left")}Veredeln und handeln</a></p>')
    # Veredelung des Monats (nur wenn etwas veredelt wurde)
    nutz = con.execute("SELECT * FROM en_nutzung WHERE schl=? AND periode=? ORDER BY id DESC LIMIT 30", (ziel, b["periode"])).fetchall()
    nutz_html = ""
    if nutz:
        nutz_html = "<h2>Veredelung in diesem Monat</h2>" + amt.tabelle(["Vorgang", "Energie", "Von"], [(esc(r["text"] or r["art"]), gwh_text(r["gwh"]), esc(r["autor"])) for r in nutz], klasse="ee-tab")
    # Verlauf (eingeklappt)
    vl = con.execute("SELECT * FROM en_monat WHERE schl=? ORDER BY periode DESC LIMIT 24", (ziel,)).fetchall()
    diag = _verlauf_svg([(r["periode"], r["angebot"], r["bev"] + r["ind"] + r["mil"] + r["ver"]) for r in reversed(vl)])
    vz = [(esc(sa._monatsname(r["periode"])), gwh_text(r["angebot"]), gwh_text(r["bev"] + r["ind"] + r["mil"] + r["ver"]), f'{_de(r["v_ges"] * 100, 0)} %') for r in vl]
    verlauf_html = _auf(f"Verlauf ({len(vl)} Monate)", diag + amt.tabelle(["Monat", "Erzeugung", "Bedarf", "Versorgung"], vz, "Noch kein gebuchter Monat.", klasse="ee-tab"))
    # Vergleich (eingeklappt)
    reihen = []
    for s, n in _ziele(con):
        c = bilanz(con, s)
        reihen.append((c["v_ges"], s, n, c))
    reihen.sort(key=lambda r: (r[0], r[2]))
    vgl = [(f'<a href="{PFAD}?ziel={esc(s)}">{esc(n)}</a>', gwh_text(c["bedarf"]), gwh_text(c["angebot"]), f'{_de(v * 100, 0)} %{ueberschuss_pz(c)}', f'{_de(c["erneuerbar"], 0)} %') for v, s, n, c in reihen]
    vgl_html = _auf("Vergleich aller Haushalte", amt.tabelle(["Haushalt", "Bedarf", "Erzeugung", "Versorgung", "Erneuerbare"], vgl, klasse="ee-tab"), "landmark")
    s_ = b["einstellung"]
    info = _auf("So funktioniert es",
                '<p class="sa-hinweis">Die Bevölkerung verbraucht pauschal Energie, Industrie und Veredelung brauchen sie, das Militär nur wenig. Bei Knappheit wird zuerst die Bevölkerung versorgt, '
                'dann das Militär, zuletzt Industrie und Veredelung. Versorgung 100–85 %: gut, ohne Folgen. 84–60 %: moderat, leichte Mali. 59–15 %: Energiemangel, deutliche Mali. '
                '14–0 %: Energienot, stärkste Mali und Abwanderung. Mali treffen Zufriedenheit, Infrastruktur und Industrie. Fossile Kraftwerke belasten das Klima. '
                f'Veredelung: Stahl {_de(float(s_["ver_stahl"]), 1)}, Aluminium {_de(float(s_["ver_aluminium"]), 1)}, Treibstoff {_de(float(s_["ver_treibstoff"]), 1)} MWh je Tonne – '
                'sie läuft nur, solange noch Energie frei ist. Veredelte Erzeugnisse im Lager geben bis zum Monatsende Boni (Treibstoff: bis +100 % Energie, Aluminium: bis +100 % Effizienz der Industrie, Stahl: bis −10 % Rüstungspreise); '
                'die Richtmenge verbraucht der Monatswechsel, Überschuss lässt sich verkaufen, Zukauf zählt genauso. Bau und Instandhaltung der Kraftwerke zahlt der Industrie-Etat (er bleibt dann der Industrie selbst entzogen). Kohle-, Gas-, Öl- und Kernkraftwerke brauchen ein Vorkommen (Braunkohle, Erdgas, Erdöl, Uran) im Gebiet. Überschüsse lassen sich am Energiemarkt verkaufen; '
                'wer unter 60 % versorgt ist, darf dort zukaufen. Stilllegungen und Sätze legt die RP-Leitung fest.</p>', "info" if "info" in amt.ICONS else "clock")
    gewaehlt = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(n)}</option>' for s, n in _ziele(con))
    return (entwicklung.CSS + CSS + f'<h1>{amt.ic("zap")} Energie · {esc(name)}</h1>{amt.meldung(request)}'
            f'<form class="sa-leiste" method="get"><div><label for="zl">Haushalt</label><select id="zl" name="ziel" onchange="this.form.submit()">{gewaehlt}</select></div></form>'
            + kopf + lage_html + "<h2>Bedarf</h2>" + bedarf_html + "<h2>Erzeugung</h2>" + mix_html + boni_html + nutz_html + verlauf_html + vgl_html + info)


@sa.seite("staat")
async def markt(request, k):
    import etatplan
    con = request.app["db"]
    ziel = _ziel(request, k, con)
    b = bilanz(con, ziel, frisch=True)
    darf = etatplan.darf_aendern(con, k, ziel)
    namen = dict(_ziele(con))
    erlaubt = kauf_erlaubt(b)
    fehl = max(0.0, b["bedarf"] - b["angebot"])
    kz = lambda xs: f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in xs)}</div>'
    kopf = kz([("Versorgung", f'{_de(b["v_ges"] * 100, 0)} %'), ("Zu verkaufen", gwh_text(b["markt_frei"])), ("Fehlbetrag", gwh_text(fehl))])
    zeilen = []
    for a in angebote(con):
        kauf = "–"
        if darf and erlaubt and a["schl"] != ziel and fehl > 0.0001:
            maxpz = min(a["rest"], fehl) / a["menge"] * 100
            kauf = (f'<form class="sa-inline" method="post" action="{PFAD}kaufen">{amt.csrf_feld(request)}<input type="hidden" name="ziel" value="{esc(ziel)}"><input type="hidden" name="angebot" value="{a["id"]}">'
                    f'<input name="prozent" inputmode="decimal" size="6" placeholder="% (max. {_de(maxpz, 1)})" aria-label="Anteil am Angebot in Prozent" required> <button class="btn zweit klein" type="submit">Kaufen</button></form>')
        elif a["schl"] == ziel and darf:
            kauf = (f'<form class="sa-inline" method="post" action="{PFAD}zurueck">{amt.csrf_feld(request)}<input type="hidden" name="ziel" value="{esc(ziel)}"><input type="hidden" name="angebot" value="{a["id"]}">'
                    '<button class="btn zweit klein" type="submit">Zurückziehen</button></form>')
        frei = a["rest"] / a["menge"] * 100
        zeilen.append((esc(namen.get(a["schl"], a["schl"])), gwh_text(a["menge"]), f'{_de(frei, 1)} % ({gwh_text(a["rest"])})', geld.mark(a["preis"]), kauf))
    tabelle = amt.tabelle(["Anbieter", "Angebot", "Noch frei", "Preis je GWh", "Anteil kaufen"], zeilen, "Zurzeit gibt es keine Angebote.")
    anbieten_html = ""
    if darf and b["markt_frei"] > 0.0001:
        anbieten_html = (f'<h2>Überschuss anbieten</h2><form class="ee-form" method="post" action="{PFAD}anbieten">{amt.csrf_feld(request)}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                         f'<div><label for="m-m">Menge (GWh, höchstens {_de(b["markt_frei"], 1)})</label><input id="m-m" name="menge" inputmode="decimal" required></div>'
                         '<div><label for="m-p">Preis je GWh (Kr)</label><input id="m-p" name="preis" inputmode="decimal" required></div>'
                         f'<button class="btn" type="submit">Anbieten</button></form>')
    hinweis = ""
    if darf and not erlaubt and fehl > 0:
        hinweis = f'<p class="sa-hinweis">Zukaufen dürfen nur Haushalte mit einer Versorgung unter {_de(float(b["einstellung"]["kauf_unter"]), 0)} %.</p>'
    ge = con.execute("SELECT * FROM en_geschaefte WHERE periode=? ORDER BY id DESC LIMIT 30", (b["periode"],)).fetchall()
    ge_html = _auf("Geschäfte in diesem Monat", amt.tabelle(["Zeit", "Verkäufer", "Käufer", "Menge", "Summe"], [(esc(amt._zeit(g["zeit"])), esc(namen.get(g["verkaeufer"], "")), esc(namen.get(g["kaeufer"], "")),
                                                                                                                    gwh_text(g["menge"]), geld.mark(g["summe"])) for g in ge], "Noch keine Geschäfte."))
    gewaehlt = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(n)}</option>' for s, n in _ziele(con))
    inhalt = (CSS + f'<h1>{amt.ic("arrow-right-left")} Energiemarkt · {esc(namen[ziel])}</h1>{amt.meldung(request)}'
              f'<form class="sa-leiste" method="get"><div><label for="zl">Haushalt</label><select id="zl" name="ziel" onchange="this.form.submit()">{gewaehlt}</select></div></form>'
              + kopf + hinweis + "<h2>Angebote</h2>" + tabelle + anbieten_html + ge_html + f'<p><a href="{PFAD}?ziel={esc(ziel)}">Zurück zu Energie</a></p>')
    return sa.ant(request, k, "Energiemarkt", "sa-energie", inhalt)


def _ziel(request, k, con):
    z = request.query.get("ziel", "")
    gueltig = {s for s, _ in _ziele(con)}
    if z in gueltig:
        return z
    regiert = sa._regierte(con, k)
    return "ts-" + next(iter(regiert)) if regiert else "reich"


@sa.seite("staat")
async def seite(request, k):
    con = request.app["db"]
    ziel = _ziel(request, k, con)
    return sa.ant(request, k, "Energie", "sa-energie", _seitenhtml(request, k, con, ziel))


async def _post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    return k, await sa.formular(request), request.app["db"]


def _zahl(s):
    try:
        return float(str(s).replace(".", "").replace(",", ".") if "," in str(s) else str(s))
    except ValueError:
        return 0.0


def _anzahl(s):
    try:
        return int(str(s).strip())
    except ValueError:
        return 0


def _recht(con, k, form):
    z = str(form.get("ziel", ""))
    import etatplan
    if z not in {s for s, _ in _ziele(con)} or not etatplan.darf_aendern(con, k, z):
        raise web.HTTPForbidden(text="Für diesen Haushalt dürfen Sie keine Kraftwerke bauen.")
    return z


async def ausbau_post(request):
    k, form, con = await _post(request)
    z = _recht(con, k, form)
    back = f"{PFAD}?ziel={z}"
    try:
        preis, rate = ausbauen(con, z, str(form.get("typ", "")), _anzahl(form.get("anzahl")), k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(back, str(e), True)
    sa.weiter(back, f"Gebaut für {geld.mark(preis)}, aus dem Industrie-Etat in Raten von {geld.mark(rate)} im Monat.")


async def anbieten_post(request):
    k, form, con = await _post(request)
    z = _recht(con, k, form)
    back = f"{PFAD}markt/?ziel={z}"
    try:
        preis = geld.betrag_lesen(form.get("preis", "")) or 0
        anbieten(con, z, _zahl(form.get("menge")), preis, k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(back, str(e), True)
    sa.weiter(back, "Angebot eingestellt.")


async def kaufen_post(request):
    k, form, con = await _post(request)
    z = _recht(con, k, form)
    back = f"{PFAD}markt/?ziel={z}"
    try:
        pz = _zahl(form.get("prozent"))
        summe, wer, menge = kaufen(con, _anzahl(form.get("angebot")), z, pz, k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(back, str(e), True)
    sa.weiter(back, f"Gekauft von {wer}: {gwh_text(menge)} für {geld.mark(summe)}.")


async def zurueck_post(request):
    k, form, con = await _post(request)
    z = _recht(con, k, form)
    back = f"{PFAD}markt/?ziel={z}"
    try:
        zurueckziehen(con, _anzahl(form.get("angebot")), z, k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(back, str(e), True)
    sa.weiter(back, "Angebot zurückgezogen.")


async def stilllegen_post(request):
    k, form, con = await _post(request)
    if not sa.ist_rp(k):
        raise web.HTTPForbidden(text="Stilllegungen ordnet die RP-Leitung an.")
    z = str(form.get("ziel", ""))
    if z not in {s for s, _ in _ziele(con)}:
        raise web.HTTPForbidden()
    back = RPE
    try:
        stilllegen(con, z, str(form.get("typ", "")), _anzahl(form.get("anzahl")), k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(back, str(e), True)
    sa.weiter(back, "Vom Netz genommen.")


async def saetze_post(request):
    k, form, con = await _post(request)
    if not sa.ist_rp(k):
        raise web.HTTPForbidden()
    neu = {}
    for n, _t in SAETZE:
        v = _zahl(form.get(n))
        if not (0 < v <= 1e7) or (n in ("zuf_max", "infra_max", "ind_max", "kauf_unter") and v > 100) or (n == "bau_faktor" and v > 1000):
            sa.weiter(RPE, f"Bitte gültige Werte angeben ({dict(SAETZE)[n]}).", True)
        neu[n] = int(v) if v == int(v) else v
    geld.einstellung_setzen(con, "energie", neu, k)
    con.commit()
    leeren()
    sa.weiter(RPE, "Sätze gespeichert.")


@sa.seite("rp")
async def rp_energie(request, k):
    """Sätze und Stilllegungen – nur in der RP-Leitungssicht."""
    con = request.app["db"]
    s = einstellungen(con)
    c = amt.csrf_feld(request)
    felder = "".join(f'<div><label for="s-{n}">{esc(t)}</label><input id="s-{n}" name="{n}" value="{esc(str(s[n]).replace(".", ","))}" inputmode="decimal" required></div>' for n, t in SAETZE)
    opt_ziel = "".join(f'<option value="{esc(z)}">{esc(n)}</option>' for z, n in _ziele(con))
    opt_typ = "".join(f'<option value="{t}">{esc(n)} ({gwh_text(g)}/Monat)</option>' for t, n, g, _p, _k in TYPEN)
    zeilen = []
    for z, n in _ziele(con):
        b = bilanz(con, z)
        zeilen.append((f'<a href="{PFAD}?ziel={esc(z)}">{esc(n)}</a>', gwh_text(b["bedarf"]), gwh_text(b["angebot"]), f'{_de(b["v_ges"] * 100, 0)} %'))
    inhalt = (CSS + f'<h1>{amt.ic("zap")} Energie · Konfiguration</h1>{amt.meldung(request)}'
              f'<h2>Sätze</h2><form class="ee-form" method="post" action="{PFAD}saetze">{c}{felder}<button class="btn" type="submit">{amt.ic("check")}Speichern</button></form>'
              f'<h2>Kraftwerke stilllegen</h2><form class="ee-form" method="post" action="{PFAD}stilllegen">{c}'
              f'<div><label for="rs-z">Haushalt</label><select id="rs-z" name="ziel">{opt_ziel}</select></div>'
              f'<div><label for="rs-t">Kraftwerk</label><select id="rs-t" name="typ">{opt_typ}</select></div>'
              '<div><label for="rs-g">Anzahl</label><input id="rs-g" name="anzahl" type="number" min="1" value="1" required></div>'
              '<button class="btn zweit" type="submit">Stilllegen</button></form>'
              + _auf("Lage aller Haushalte", amt.tabelle(["Haushalt", "Bedarf", "Erzeugung", "Versorgung"], zeilen, klasse="ee-tab"), "landmark"))
    return sa.ant(request, k, "Energie: Konfiguration", "sa-rp-energie", inhalt)


async def _automatik(app):
    while True:
        try:
            monatswechsel(app["db"])
        except Exception:
            log.exception("Monatswechsel der Veredelungs-Boni fehlgeschlagen")
        await asyncio.sleep(60)


def registrieren(app):
    einrichten(app["db"])
    try:
        monatswechsel(app["db"])
    except Exception:
        log.exception("Monatswechsel beim Start fehlgeschlagen")

    async def start(app_):
        app_["energie_aufgabe"] = asyncio.get_event_loop().create_task(_automatik(app_))

    async def stopp(app_):
        app_["energie_aufgabe"].cancel()
    app.on_startup.append(start)
    app.on_cleanup.append(stopp)
    app.router.add_get(PFAD, seite)
    app.router.add_get(RPE, rp_energie)
    app.router.add_get(PFAD + "markt/", markt)
    app.router.add_post(PFAD + "anbieten", anbieten_post)
    app.router.add_post(PFAD + "kaufen", kaufen_post)
    app.router.add_post(PFAD + "zurueck", zurueck_post)
    app.router.add_post(PFAD + "ausbau", ausbau_post)
    app.router.add_post(PFAD + "stilllegen", stilllegen_post)
    app.router.add_post(PFAD + "saetze", saetze_post)
