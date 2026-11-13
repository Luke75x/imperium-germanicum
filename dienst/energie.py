"""Energiesystem: Angebot (Kraftwerke), Bedarf (Bevölkerung, Industrie, Veredelung, Militär), Versorgungslage und ihre Folgen – je Haushalt (Teilstaat „ts-<sid>“ und Reich „reich“ = Freie Reichsgebiete).

Einheit: GWh je Monat.

Bedarf (Sätze unter /schatzamt/energie/, Reich-Ansicht, für die Schatzamt-Leitung und die RP-Leitung einstellbar)
  · Bevölkerung: pauschal Einwohner × kWh je Kopf und Monat (Haushalte, Heizung, Alltag).
  · Industrie: BIP (Mio. €, monatlich) × GWh je Mio. € – die Grundlast der Wirtschaft.
  · Veredelung: jede Veredelung im Handel (Stahl, Aluminium, Treibstoff) verbraucht Energie je Tonne; sie wird nur ausgeführt, solange der Teilstaat
    noch freie Energie hat, und zählt im laufenden Monat zum Bedarf.
  · Militär: wenige MWh je Gerät und Monat (Instandhaltung); bei Unterversorgung sinkt zusätzlich die Einsatzbereitschaft (verteidigung.instandhaltung).
Angebot: Kraftwerke (Tabelle en_kraftwerke). Beim ersten Zugriff bekommt jeder Haushalt Kraftwerke mit einem Strommix (Vorgabe oder Landesart) und einer Reserve
  über dem Bedarf. Landesherren (Reich: Schatzamt-Leitung) bauen aus (bezahlt aus der Staats- bzw. Reichskasse an die Volkswirtschaft, Bauzeit je Typ) oder legen still.
Versorgung bei Knappheit: zuerst die Bevölkerung, dann das Militär, zuletzt Industrie und Veredelung.
Folgen (entwicklung.entwickeln ruft wirkungen_fuer): Unterversorgung der Bevölkerung senkt die Zufriedenheit, mangelnde Gesamtversorgung verschiebt die Zielwerte der
  Infrastruktur (Wasser, Müll, Straßen) nach unten, fehlende Energie für die Industrie das Industrieniveau und das BIP pro Kopf. Fossile Kraftwerke belasten das Klima (CO₂).
Statistik: Monatswerte (en_monat, beim Buchen des Haushaltsmonats), Verlauf, Vergleich aller Haushalte. Reiter „Energie“ bei „Mein Teilstaat“ und im Reichshaushalt.
Tabellen: en_kraftwerke, en_monat, en_nutzung.
"""
import logging
import time

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa

esc = amt.esc
log = logging.getLogger("energie")
PFAD = sa.PFAD + "energie/"

amt.ICONS.setdefault("zap", '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>')
geld.BUCHUNGSART.setdefault("energie", "Energieausbau")

geld.VORGABEN.setdefault("energie", {
    "haushalt_kwh": 450,          # kWh je Einwohner und Monat
    "industrie_gwh_je_mio": 0.18,  # GWh je Mio. € BIP (monatliches BIP)
    "mil_mwh_je_geraet": 8,       # MWh je Militärgerät und Monat
    "reserve_start": 12,          # % Reserve der Erstausstattung über dem Bedarf
    "ver_stahl": 2.0, "ver_aluminium": 15.0, "ver_treibstoff": 0.6,   # MWh je Tonne Erzeugnis (Veredelung)
    "zuf_max": 45, "infra_max": 60, "ind_max": 70,   # größte Abzüge (Zufriedenheit in Punkten, Zielwerte der Indikatoren, Industrie)
    "bau_faktor": 100,            # % der Baukosten
})
SAETZE = [("haushalt_kwh", "Verbrauch je Einwohner (kWh/Monat)"), ("industrie_gwh_je_mio", "Industrie (GWh je Mio. € BIP)"), ("mil_mwh_je_geraet", "Militärgerät (MWh/Monat je Gerät)"),
          ("reserve_start", "Reserve der Erstausstattung (%)"), ("ver_stahl", "Veredelung Stahl (MWh/t)"), ("ver_aluminium", "Veredelung Aluminium (MWh/t)"),
          ("ver_treibstoff", "Veredelung Treibstoff (MWh/t)"), ("zuf_max", "Höchstabzug Zufriedenheit (Punkte)"), ("infra_max", "Höchstabzug Infrastruktur (Punkte)"),
          ("ind_max", "Höchstabzug Industrie (Punkte)"), ("bau_faktor", "Baukosten (% der Tabelle)")]
VEREDELUNG = {"stahl": "ver_stahl", "aluminium": "ver_aluminium", "treibstoff": "ver_treibstoff"}

# (Schlüssel, Name, Baukosten Mio. Kr je GWh/Monat Leistung, Bauzeit in Monaten, Klima-Gewicht, Farbfeld)
TYPEN = [("kohle", "Kohlekraftwerk", 6.0, 4, 1.00), ("gas", "Gaskraftwerk", 4.0, 3, 0.55), ("oel", "Ölkraftwerk", 4.0, 3, 0.80), ("kern", "Kernkraftwerk", 22.0, 8, 0.03),
         ("wasser", "Wasserkraftwerk", 14.0, 6, 0.0), ("wind", "Windpark", 6.0, 3, 0.0), ("solar", "Solarpark", 5.0, 2, 0.0), ("biomasse", "Biomassekraftwerk", 7.0, 3, 0.25)]
TYP = {t[0]: t for t in TYPEN}
FARBEN = ["#6b7280", "#eb6834", "#8b5a2b", "#e34948", "#2a78d6", "#1baf7a", "#eda100", "#008300"]
FOSSIL = ("kohle", "gas", "oel")
KLIMA_NEUTRAL = 0.3375   # gewichteter Klima-Anteil der Standardmischung
# Strommix der Erstausstattung in % (Standard; einzelne Länder weichen ab, Treffer über Teile des Namens)
MIX = {"kohle": 18, "gas": 22, "oel": 3, "kern": 9, "wasser": 7, "wind": 22, "solar": 14, "biomasse": 5}
MIX_LAND = {"schweiz": {"kohle": 0, "gas": 5, "oel": 2, "kern": 20, "wasser": 55, "wind": 3, "solar": 10, "biomasse": 5},
            "böhmen": {"kohle": 45, "gas": 8, "oel": 2, "kern": 25, "wasser": 4, "wind": 3, "solar": 8, "biomasse": 5},
            "venedig": {"kohle": 0, "gas": 40, "oel": 5, "kern": 0, "wasser": 15, "wind": 10, "solar": 25, "biomasse": 5},
            "apulien": {"kohle": 0, "gas": 35, "oel": 5, "kern": 0, "wasser": 0, "wind": 25, "solar": 28, "biomasse": 7},
            "berlin": {"kohle": 10, "gas": 45, "oel": 3, "kern": 0, "wasser": 0, "wind": 10, "solar": 22, "biomasse": 10}}

SCHEMA = """
CREATE TABLE IF NOT EXISTS en_kraftwerke (id INTEGER PRIMARY KEY AUTOINCREMENT, schl TEXT NOT NULL, typ TEXT NOT NULL, gwh REAL NOT NULL, ab TEXT NOT NULL DEFAULT '',
    bezahlt INTEGER NOT NULL DEFAULT 0, von TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS en_kw_s ON en_kraftwerke (schl);
CREATE TABLE IF NOT EXISTS en_monat (periode TEXT NOT NULL, schl TEXT NOT NULL, angebot REAL NOT NULL, bev REAL NOT NULL, ind REAL NOT NULL, mil REAL NOT NULL,
    ver REAL NOT NULL, v_hh REAL NOT NULL, v_ind REAL NOT NULL, v_ges REAL NOT NULL, ew INTEGER NOT NULL DEFAULT 0, mix TEXT NOT NULL DEFAULT '', PRIMARY KEY (periode, schl));
CREATE TABLE IF NOT EXISTS en_nutzung (id INTEGER PRIMARY KEY AUTOINCREMENT, periode TEXT NOT NULL, schl TEXT NOT NULL, art TEXT NOT NULL, gwh REAL NOT NULL,
    text TEXT NOT NULL DEFAULT '', autor TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS en_nu_s ON en_nutzung (schl, periode);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def einstellungen(con):
    return dict(geld.VORGABEN["energie"], **geld.einstellung(con, "energie"))


def _de(x, st=1):
    return f"{x:,.{st}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def gwh_text(x):
    """GWh, ab 10.000 als TWh."""
    return f"{_de(x / 1000, 1)} TWh" if abs(x) >= 10000 else f"{_de(x, 0 if abs(x) >= 100 else 1)} GWh"


def _monat_plus(periode, n):
    import etatplan
    for _ in range(n):
        periode = etatplan._folgemonat(periode)
    return periode


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

def _land_mix(name):
    n = (name or "").lower()
    for teil, m in MIX_LAND.items():
        if teil in n:
            return m
    return MIX


def sichern(con, schl, periode=None):
    """Erstausstattung: Kraftwerke mit Reserve über dem Bedarf (einmalig je Haushalt)."""
    if con.execute("SELECT 1 FROM en_kraftwerke WHERE schl=? LIMIT 1", (schl,)).fetchone():
        return
    import etatplan
    periode = periode or etatplan.monat_heute()
    s = einstellungen(con)
    ew, bip = bevoelkerung(con, schl, periode)
    bedarf = (ew * float(s["haushalt_kwh"]) / 1e6 + bip / 12 * float(s["industrie_gwh_je_mio"]) + _mil_einheiten(con, schl) * float(s["mil_mwh_je_geraet"]) / 1000)
    ziel = bedarf * (1 + float(s["reserve_start"]) / 100)
    mix = _land_mix(_name(con, schl))
    for typ, anteil in mix.items():
        if anteil > 0 and ziel > 0:
            con.execute("INSERT INTO en_kraftwerke (schl, typ, gwh, ab, von, zeit) VALUES (?,?,?,?,?,?)", (schl, typ, round(ziel * anteil / 100, 3), "", "Erstausstattung", int(time.time())))
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
    S = sum(mix.values())
    hh = ew * float(s["haushalt_kwh"]) / 1e6
    ind = bip / 12 * float(s["industrie_gwh_je_mio"])
    n_mil = _mil_einheiten(con, schl)
    mil = n_mil * float(s["mil_mwh_je_geraet"]) / 1000
    ver = veredelung_verbrauch(con, schl, periode)
    rest = S
    g_hh = min(rest, hh); rest -= g_hh
    g_mil = min(rest, mil); rest -= g_mil
    g_ind = min(rest, ind + ver)
    bedarf = hh + ind + mil + ver
    v = lambda g, b: (g / b) if b > 1e-9 else 1.0
    fossil = sum(mix.get(t, 0) for t in FOSSIL)
    klima = sum(mix.get(t, 0) * TYP[t][4] for t in mix) / S if S else 0.0
    b = {"periode": periode, "schl": schl, "ew": ew, "bip": bip, "hh": hh, "ind": ind, "mil": mil, "ver": ver, "bedarf": bedarf, "angebot": S, "mix": mix,
         "v_hh": v(g_hh, hh), "v_mil": v(g_mil, mil), "v_ind": v(g_ind, ind + ver), "v_ges": min(1.0, v(S, bedarf)), "frei": S - (hh + ind + mil + ver), "n_mil": n_mil,
         "fossil": fossil / S * 100 if S else 0.0, "erneuerbar": sum(mix.get(t, 0) for t in ("wasser", "wind", "solar", "biomasse")) / S * 100 if S else 0.0,
         "klima": klima, "einstellung": s}
    _CACHE[(schl, periode)] = (time.time(), b)
    return b


def lage(b):
    """(Stufe, Text): ok | knapp | mangel | ausfall"""
    if b["v_ges"] >= 0.999:
        return "ok", "Die Energieversorgung ist gesichert."
    if b["angebot"] <= 0:
        return "ausfall", "Totalausfall: Es wird keine Energie erzeugt."
    if b["v_hh"] < 0.999:
        return "mangel", "Energiemangel: Auch die Bevölkerung wird nicht mehr voll versorgt."
    return "knapp", "Energie ist knapp: Industrie und Veredelung werden gedrosselt."


# ---------------------------------------------------------------- Folgen (entwicklung.entwickeln)

def wirkungen_fuer(con, schl, periode):
    """(Effekte, Verschiebungen) wie krisen.wirkungen_fuer: Mali bei nicht gedecktem Energiebedarf."""
    try:
        b = bilanz(con, schl, periode)
    except Exception:
        log.exception("Energiebilanz von %s nicht berechenbar", schl)
        return [], {}
    s = b["einstellung"]
    effekte, shift = [], {}
    d_hh, d_ind, d_ges = 1 - b["v_hh"], 1 - b["v_ind"], 1 - b["v_ges"]
    if d_ges > 0.001:
        zuf = -min(float(s["zuf_max"]), float(s["zuf_max"]) * d_hh + 0.3 * float(s["zuf_max"]) * d_ind)
        if zuf < -0.05:
            effekte.append({"hebel": "zuf_pt", "wert": zuf, "titel": "Energiemangel", "modul": "energie",
                            "text": f'Die Bevölkerung wird zu {_de(b["v_hh"] * 100, 0)} %, die Industrie zu {_de(b["v_ind"] * 100, 0)} % mit Energie versorgt: Stromausfälle und Kurzarbeit'})
        shift["wasser"] = shift["muell"] = shift["strassen"] = -min(float(s["infra_max"]), float(s["infra_max"]) * d_ges)
        shift["industrie"] = -min(float(s["ind_max"]), float(s["ind_max"]) * d_ind)
        kopf = -min(10.0, float(s["ind_max"]) / 10 * d_ind)
        if kopf < -0.05:
            effekte.append({"hebel": "kopf_pct", "wert": kopf, "titel": "Energiemangel in der Industrie", "modul": "energie",
                            "text": "Ohne ausreichend Energie steht die Produktion still, das Einkommen je Kopf sinkt"})
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
    if gwh > max(0.0, b["frei"]) + 1e-9:
        raise geld.Fehler(f'Zu wenig Energie für die Veredelung: benötigt {gwh_text(gwh)}, frei sind in diesem Monat {gwh_text(max(0.0, b["frei"]))}. '
                          f'Unter „Energie“ lassen sich Kraftwerke ausbauen.')
    return gwh


def veredelung_buchen(con, schl, gwh, text, k):
    import etatplan
    if gwh > 0:
        con.execute("INSERT INTO en_nutzung (periode, schl, art, gwh, text, autor, zeit) VALUES (?,?,?,?,?,?,?)",
                    (etatplan.monat_heute(), schl, "veredelung", gwh, text[:200], k["name"] if k else "System", int(time.time())))
        leeren()


def hinweis_html(con):
    s = einstellungen(con)
    return (f'Energiebedarf je Tonne: Stahl {_de(float(s["ver_stahl"]), 1)} MWh, Aluminium {_de(float(s["ver_aluminium"]), 1)} MWh, '
            f'Treibstoff {_de(float(s["ver_treibstoff"]), 1)} MWh. Veredelt wird nur, solange der Teilstaat noch freie Energie hat (<a href="{PFAD}">Energie</a>).')


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


# ---------------------------------------------------------------- Ausbau und Stilllegung

def baukosten(con, typ, gwh):
    s = einstellungen(con)
    return int(round(gwh * TYP[typ][2] * 1e6 * 100 * float(s["bau_faktor"]) / 100))   # Heller


def ausbauen(con, schl, typ, gwh, k):
    import etatplan
    import handel
    if typ not in TYP:
        raise geld.Fehler("Bitte einen Kraftwerkstyp wählen.")
    if not 0.1 <= gwh <= 200000:
        raise geld.Fehler("Die Leistung muss zwischen 0,1 und 200.000 GWh je Monat liegen.")
    kosten = baukosten(con, typ, gwh)
    kc = handel.kasse(con, schl)
    if kc["saldo"] < kosten:
        raise geld.Fehler(f'Die {kc["name"]} ist nicht gedeckt: Der Bau kostet {geld.mark(kosten)}.')
    sichern(con, schl)
    geld.buchen(con, kc["id"], geld.sonder(con, "volkswirtschaft")["id"], kosten, "energie", f"Bau {TYP[typ][1]} ({gwh:g} GWh/Monat)", k, bezug=f"ENERGIE-{schl}")
    ab = _monat_plus(etatplan.monat_heute(), TYP[typ][3])
    con.execute("INSERT INTO en_kraftwerke (schl, typ, gwh, ab, bezahlt, von, zeit) VALUES (?,?,?,?,?,?,?)", (schl, typ, gwh, ab, kosten, k["name"], int(time.time())))
    geld.protokoll(con, k, "Energie: Ausbau", f"{_name(con, schl)}: {TYP[typ][1]} {gwh:g} GWh/Monat für {geld.mark(kosten)}, in Betrieb ab {ab}")
    leeren()
    return kosten, ab


def stilllegen(con, schl, typ, gwh, k):
    """Nimmt Leistung eines Typs vom Netz (zuerst im Bau befindliche Anlagen verschont: nur Anlagen in Betrieb, ältere zuerst). Keine Erstattung."""
    import etatplan
    if typ not in TYP or gwh <= 0:
        raise geld.Fehler("Bitte Typ und Leistung angeben.")
    sichern(con, schl)
    heute = etatplan.monat_heute()
    rest = gwh
    laufend = [r for r in kraftwerke(con, schl) if r["typ"] == typ and (not r["ab"] or r["ab"] <= heute)]
    if sum(r["gwh"] for r in laufend) + 1e-9 < gwh:
        raise geld.Fehler(f'Es sind nur {gwh_text(sum(r["gwh"] for r in laufend))} {TYP[typ][1]} in Betrieb.')
    for r in laufend:
        if rest <= 1e-9:
            break
        nehmen = min(rest, r["gwh"])
        if nehmen >= r["gwh"] - 1e-9:
            con.execute("DELETE FROM en_kraftwerke WHERE id=?", (r["id"],))
        else:
            con.execute("UPDATE en_kraftwerke SET gwh=? WHERE id=?", (round(r["gwh"] - nehmen, 3), r["id"]))
        rest -= nehmen
    geld.protokoll(con, k, "Energie: Stilllegung", f"{_name(con, schl)}: {TYP[typ][1]} {gwh:g} GWh/Monat")
    leeren()


# ---------------------------------------------------------------- Seite

CSS = """<style>
.ee-bar{display:flex;height:22px;border-radius:7px;overflow:hidden;background:var(--hell,#eee);margin:8px 0}
.ee-bar i{display:block;height:100%}
.ee-leg{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px;margin:4px 0 12px}.ee-leg span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;background:var(--c);margin-right:6px}
.ee-lage{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--linie);border-radius:12px;padding:12px 16px;margin:12px 0;background:#fff}
.ee-lage .icon{width:20px;height:20px;flex:none;margin-top:2px}.ee-lage.knapp{border-color:#eda100}.ee-lage.mangel,.ee-lage.ausfall{border-color:#c0392b;box-shadow:0 0 0 1px #c0392b}
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


def _seitenhtml(request, k, con, ziel):
    import etatplan
    import entwicklung
    b = bilanz(con, ziel, frisch=True)
    name = dict(_ziele(con))[ziel]
    stufe, text = lage(b)
    darf = etatplan.darf_aendern(con, k, ziel)
    kz = lambda xs: f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in xs)}</div>'
    kopf = kz([("Versorgung", f'{_de(b["v_ges"] * 100, 0)} %'), ("Angebot", gwh_text(b["angebot"])), ("Bedarf", gwh_text(b["bedarf"])),
               ("Reserve" if b["frei"] >= 0 else "Fehlbetrag", gwh_text(abs(b["frei"]))), ("Erneuerbare", f'{_de(b["erneuerbar"], 0)} %'),
               ("Verbrauch je Kopf", f'{_de(b["bedarf"] * 1e6 / b["ew"], 0) if b["ew"] else "–"} kWh/Monat')])
    symbol = {"ok": "check", "knapp": "triangle-alert", "mangel": "triangle-alert", "ausfall": "triangle-alert"}[stufe]
    folgen = []
    ef, shift = wirkungen_fuer(con, ziel, b["periode"])
    for e in ef:
        folgen.append(f'<li><b>{esc(e["titel"])}</b>: {esc(e["text"])} ({_de(e["wert"], 1)} {"Punkte" if e["hebel"] == "zuf_pt" else "%"})</li>')
    for i, t in (("wasser", "Infrastruktur"), ("industrie", "Industrie")):
        if shift.get(i, 0) < -0.05:
            folgen.append(f'<li><b>{t}</b>: Zielwert {_de(shift[i], 0)} Punkte durch fehlende Energie</li>')
    lage_html = (f'<div class="ee-lage {stufe}">{amt.ic(symbol)}<div><b>{esc(text)}</b>'
                 + (f'<ul>{"".join(folgen)}</ul>' if folgen else '<p class="sa-hinweis">Keine Mali: Bevölkerung, Infrastruktur und Industrie sind ausreichend versorgt.</p>')
                 + '</div></div>')
    # Bedarf
    verbr = [("Bevölkerung", b["hh"], b["v_hh"], "#2a78d6"), ("Militär", b["mil"], b["v_mil"], "#6250d6"), ("Industrie", b["ind"], b["v_ind"], "#eb6834"), ("Veredelung (laufender Monat)", b["ver"], b["v_ind"], "#eda100")]
    zeilen = [(esc(n), gwh_text(w), f'{_de(w / b["bedarf"] * 100, 1) if b["bedarf"] else "0"} %', f'{_de(v * 100, 0)} %') for n, w, v, _ in verbr]
    bedarf_html = (_balken([(n, w, c) for n, w, _, c in verbr]) + amt.tabelle(["Verbraucher", "Bedarf", "Anteil", "Versorgt"], zeilen, klasse="ee-tab")
                   + '<p class="sa-hinweis">Bei Knappheit wird zuerst die Bevölkerung versorgt, dann das Militär, zuletzt Industrie und Veredelung.</p>')
    # Mix
    mix_teile = [(TYP[t][1], b["mix"].get(t, 0), FARBEN[i]) for i, (t, *_r) in enumerate(TYPEN)]
    kw = []
    heute = b["periode"]
    for r in kraftwerke(con, ziel):
        betrieb = not r["ab"] or r["ab"] <= heute
        kw.append((esc(TYP[r["typ"]][1]), gwh_text(r["gwh"]), "in Betrieb" if betrieb else f'im Bau, ab {esc(r["ab"])}', esc(r["von"] or "–")))
    ausbau = ""
    if darf:
        opt = "".join(f'<option value="{t}">{esc(n)} (Bauzeit {z} Mon.)</option>' for t, n, c, z, _ in TYPEN)
        ausbau = (f'<h3>Ausbau</h3><form class="ee-form" method="post" action="{PFAD}ausbau">{amt.csrf_feld(request)}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                  f'<div><label for="ea-t">Kraftwerk</label><select id="ea-t" name="typ">{opt}</select></div>'
                  '<div><label for="ea-g">Leistung (GWh je Monat)</label><input id="ea-g" name="gwh" inputmode="decimal" required></div>'
                  f'<button class="btn" type="submit">{amt.ic("zap")}Bauen</button></form>'
                  '<p class="sa-hinweis">Baukosten je GWh/Monat: ' + ", ".join(f'{esc(n)} {_de(c * float(b["einstellung"]["bau_faktor"]) / 100, 1)} Mio. Kr' for t, n, c, z, _ in TYPEN)
                  + '. Bezahlt aus der Staats- bzw. Reichskasse an die Volkswirtschaft.</p>'
                  f'<h3>Stilllegen</h3><form class="ee-form" method="post" action="{PFAD}stilllegen">{amt.csrf_feld(request)}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                  f'<div><label for="es-t">Kraftwerk</label><select id="es-t" name="typ">{opt}</select></div>'
                  '<div><label for="es-g">Leistung (GWh je Monat)</label><input id="es-g" name="gwh" inputmode="decimal" required></div>'
                  f'<button class="btn zweit" type="submit">Stilllegen</button></form><p class="sa-hinweis">Stillgelegte Leistung wird nicht erstattet.</p>')
    mix_html = (_balken(mix_teile) + f'<p class="sa-hinweis">Fossile Erzeugung {_de(b["fossil"], 0)} %. Der Mix wirkt auf die CO₂-Belastung '
                f'(Umwelt): {"belastend" if b["klima"] > KLIMA_NEUTRAL + 0.02 else "entlastend" if b["klima"] < KLIMA_NEUTRAL - 0.02 else "neutral"}.</p>'
                + amt.tabelle(["Kraftwerk", "Leistung", "Stand", "Gebaut von"], kw, "Keine Kraftwerke.", klasse="ee-tab") + ausbau)
    # Veredelung des Monats
    nutz = con.execute("SELECT * FROM en_nutzung WHERE schl=? AND periode=? ORDER BY id DESC LIMIT 30", (ziel, heute)).fetchall()
    nutz_html = amt.tabelle(["Zeit", "Vorgang", "Energie", "Von"], [(esc(amt._zeit(r["zeit"])), esc(r["text"] or r["art"]), gwh_text(r["gwh"]), esc(r["autor"])) for r in nutz],
                            "In diesem Monat wurde nichts veredelt.", klasse="ee-tab")
    # Verlauf
    vl = con.execute("SELECT * FROM en_monat WHERE schl=? ORDER BY periode DESC LIMIT 24", (ziel,)).fetchall()
    diag = _verlauf_svg([(r["periode"], r["angebot"], r["bev"] + r["ind"] + r["mil"] + r["ver"]) for r in reversed(vl)])
    vz = [(esc(sa._monatsname(r["periode"])), gwh_text(r["angebot"]), gwh_text(r["bev"] + r["ind"] + r["mil"] + r["ver"]), f'{_de(r["v_ges"] * 100, 0)} %', f'{_de(r["v_hh"] * 100, 0)} %',
           f'{_de(r["v_ind"] * 100, 0)} %') for r in vl]
    verlauf_html = diag + amt.tabelle(["Monat", "Angebot", "Bedarf", "Versorgung", "Bevölkerung", "Industrie"], vz, "Noch kein gebuchter Monat mit Energiebilanz.", klasse="ee-tab")
    # Vergleich
    reihen = []
    for s, n in _ziele(con):
        c = bilanz(con, s)
        reihen.append((c["v_ges"], s, n, c))
    reihen.sort(key=lambda r: (r[0], r[2]))
    vgl = [(f'<a href="{PFAD}?ziel={esc(s)}">{esc(n)}</a>', f'{_de(c["ew"] / 1e6, 2)} Mio.', gwh_text(c["bedarf"]), gwh_text(c["angebot"]), f'{_de(v * 100, 0)} %',
            f'{_de(c["erneuerbar"], 0)} %', f'{_de(c["bedarf"] * 1e6 / c["ew"], 0) if c["ew"] else "–"} kWh') for v, s, n, c in reihen]
    summe_a = sum(r[3]["angebot"] for r in reihen)
    summe_b = sum(r[3]["bedarf"] for r in reihen)
    vgl_html = (amt.tabelle(["Haushalt", "Einwohner", "Bedarf", "Angebot", "Versorgung", "Erneuerbare", "je Kopf"], vgl, klasse="ee-tab")
                + f'<p class="sa-hinweis">Das Reich insgesamt: Angebot {gwh_text(summe_a)}, Bedarf {gwh_text(summe_b)} ({_de(min(100, summe_a / summe_b * 100) if summe_b else 100, 0)} % gedeckt).</p>')
    saetze = ""
    if geld.ist_leitung(k) or sa.ist_rp(k):
        s = b["einstellung"]
        felder = "".join(f'<div><label for="s-{n}">{esc(t)}</label><input id="s-{n}" name="{n}" value="{esc(str(s[n]).replace(".", ","))}" inputmode="decimal" required></div>' for n, t in SAETZE)
        saetze = (f'<details class="sa-auf"><summary>{amt.ic("wrench")}Sätze (Schatzamt-Leitung)</summary><form class="ee-form" method="post" action="{PFAD}saetze">'
                  f'{amt.csrf_feld(request)}<input type="hidden" name="ziel" value="{esc(ziel)}">{felder}<button class="btn" type="submit">Speichern</button></form></details>')
    gewaehlt = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(n)}</option>' for s, n in _ziele(con))
    return (entwicklung.CSS + CSS + f'<h1>{amt.ic("zap")} Energie · {esc(name)}</h1>{amt.meldung(request)}'
            '<p class="az">Die Bevölkerung verbraucht pauschal Energie, die Industrie und jede Veredelung brauchen sie, das Militär nur wenig. Reicht die Erzeugung nicht, '
            'sinken Zufriedenheit, Infrastruktur und Industrie.</p>'
            f'<form class="sa-leiste" method="get"><div><label for="zl">Haushalt</label><select id="zl" name="ziel" onchange="this.form.submit()">{gewaehlt}</select></div></form>'
            + kopf + lage_html + "<h2>Bedarf</h2>" + bedarf_html + "<h2>Erzeugung</h2>" + mix_html + "<h2>Veredelung in diesem Monat</h2>" + nutz_html
            + f'<p class="sa-hinweis">{hinweis_html(con)}</p>' + "<h2>Verlauf</h2>" + verlauf_html + "<h2>Vergleich der Haushalte</h2>" + vgl_html + saetze)


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


def _recht(con, k, form):
    import etatplan
    z = str(form.get("ziel", ""))
    if z not in {s for s, _ in _ziele(con)} or not etatplan.darf_aendern(con, k, z):
        raise web.HTTPForbidden(text="Für diesen Haushalt dürfen Sie keine Kraftwerke ändern.")
    return z


async def ausbau_post(request):
    k, form, con = await _post(request)
    z = _recht(con, k, form)
    back = f"{PFAD}?ziel={z}"
    try:
        kosten, ab = ausbauen(con, z, str(form.get("typ", "")), _zahl(form.get("gwh")), k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(back, str(e), True)
    sa.weiter(back, f"Der Bau kostet {geld.mark(kosten)}; die Anlage geht ab {ab} in Betrieb.")


async def stilllegen_post(request):
    k, form, con = await _post(request)
    z = _recht(con, k, form)
    back = f"{PFAD}?ziel={z}"
    try:
        stilllegen(con, z, str(form.get("typ", "")), _zahl(form.get("gwh")), k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(back, str(e), True)
    sa.weiter(back, "Die Leistung wurde vom Netz genommen.")


async def saetze_post(request):
    k, form, con = await _post(request)
    if not (geld.ist_leitung(k) or sa.ist_rp(k)):
        raise web.HTTPForbidden()
    neu = {}
    for n, _t in SAETZE:
        v = _zahl(form.get(n))
        if not (0 < v <= 1e7) or (n in ("zuf_max", "infra_max", "ind_max") and v > 100) or (n == "bau_faktor" and v > 1000):
            sa.weiter(f'{PFAD}?ziel={form.get("ziel", "reich")}', f"Bitte gültige Werte angeben ({dict(SAETZE)[n]}).", True)
        neu[n] = int(v) if v == int(v) else v
    geld.einstellung_setzen(con, "energie", neu, k)
    con.commit()
    leeren()
    sa.weiter(f'{PFAD}?ziel={form.get("ziel", "reich")}', "Sätze gespeichert.")


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get(PFAD, seite)
    app.router.add_post(PFAD + "ausbau", ausbau_post)
    app.router.add_post(PFAD + "stilllegen", stilllegen_post)
    app.router.add_post(PFAD + "saetze", saetze_post)
