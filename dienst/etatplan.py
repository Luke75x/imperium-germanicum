"""Etatverteilung: Reich und Teilstaaten bestimmen, wie ihr Ausgabenbudget auf elf Politikfelder verteilt wird (/schatzamt/etatverteilung/).

Rücklage (Spalte ep_fassungen.ruecklage, % des eigenen Steueranteils; NULL = Vorgabe 100 − ausgabenquote): plus = sparen (bleibt in der Staats- bzw.
Reichskasse), minus = entnehmen (Ausgabenbudget größer als der Steueranteil, Differenz aus der Kasse), höchstens bis zu den freien Mitteln
(kasse_frei: Kontostand − Besoldung des letzten Lohnlaufs aus dieser Kasse, beim Reich zusätzlich die Behörden-Etats). Kein Bonus/Malus fürs Sparen
oder Entnehmen; öffentlich als Haushaltsführung angezeigt.
Etat (Steueraufkommen im Monat) eines Teilstaats = Abgabe an das Reich (nicht beeinflussbar, Reichsabgabe nach Bevölkerung, Einkommen und Fläche)
+ Landesanteil. Vom Landesanteil gehen „ausgabenquote“ % (Vorgabe 97 %) als Ausgabenbudget in die Politikfelder, der Rest ist die Rücklage der
Staatskasse. Das Ausgabenbudget verteilt der Teilstaat selbst in Prozent auf die Kategorien (Summe 100 %). Das Reich verteilt sein Ausgabenbudget
(Reichsanteil aller Steuern einschließlich der Freien Reichsgebiete) genauso.
Wirkung: Der Anteil „Verteidigung“ ist echtes Geld – er fließt jeden Monat in die Verteidigungskasse (Teilstaat) bzw. Reichsverteidigungskasse
(aufkommen.berechnen, verteidigung.py). Die übrigen Kategorien sind simulierte Ausgaben der Bevölkerung (Gegenkonto „Volkswirtschaft“); sie werden je
Haushaltsmonat in ep_verteilung festgehalten.
Vorgabe, solange nichts gespeichert ist: Verteidigung aus der alten Regel (Einstellung „verteidigung“: Anteil am BIP), der Rest nach VORGABE_GEWICHT.
Änderungsperiode: In den letzten sieben Tagen eines Kalendermonats kann der Etat für den Folgemonat eingereicht werden. Davor lässt sich jederzeit ein
Entwurf speichern (ep_entwuerfe, ein Entwurf je Haushalt, beliebig oft änderbar, noch ohne Wirkung); „Etat einreichen“ schickt den zuletzt gespeicherten
Entwurf endgültig ab (ep_fassungen mit „ab“ = Folgemonat) und sperrt den Haushalt bis zur nächsten Änderungsperiode. Ein nicht eingereichter Entwurf gilt nicht:
es bleibt beim bisherigen Etat. Planung unter /schatzamt/etatplanung/, die Seite Etatverteilung zeigt nur den geltenden Etat. Rechte: Teilstaat – Landesherr (geld.regierte_staatskassen, nicht unter Zwangsverwaltung),
Reich – Schatzamt-Leitung, Kanzler, Kaiser; ansehen darf jeder mit staatlichem Zugriff. Tabellen: ep_fassungen, ep_entwuerfe, ep_log, ep_verteilung
(ep_plaene = alte, ungenutzte Einzeltabelle, nur noch Quelle der Übernahme).
"""
import calendar
import json
import math
import time
from datetime import date, timedelta

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark

esc = amt.esc
PFAD = sa.PFAD + "etatverteilung/"
PFAD_PLAN = sa.PFAD + "etatplanung/"

KATEGORIEN = [("innere_sicherheit", "Innere Sicherheit"), ("forschung", "Forschung"), ("gesundheit", "Gesundheitswesen"), ("industrie", "Industrie"),
              ("kultur", "Kultur"), ("verteidigung", "Verteidigung"), ("soziales", "Arbeit und Soziales"), ("umwelt", "Umwelt"),
              ("transport", "Transportwesen"), ("bildung", "Bildung"), ("landwirtschaft", "Landwirtschaft")]
NAMEN = dict(KATEGORIEN)
# Vorgabe für alle Kategorien außer Verteidigung (Richtwerte eines Staatshaushalts), Summe 100
VORGABE_GEWICHT = {"soziales": 41, "gesundheit": 14, "bildung": 12, "transport": 8, "innere_sicherheit": 5, "forschung": 5, "industrie": 5,
                   "umwelt": 4, "kultur": 3, "landwirtschaft": 3}

amt.ICONS.setdefault("chart-pie", '<path d="M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055-.998.398-.998.95v8a1 1 0 0 0 1 1z"/>'
                                  '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>')

amt.ICONS.setdefault("send", '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/>'
                              '<path d="m21.854 2.147-10.94 10.939"/>')

amt.ICONS.setdefault("scale", '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
                             '<path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>')

SCHEMA = """
CREATE TABLE IF NOT EXISTS ep_plaene (schl TEXT NOT NULL, kategorie TEXT NOT NULL, anteil REAL NOT NULL, PRIMARY KEY (schl, kategorie));
CREATE TABLE IF NOT EXISTS ep_fassungen (schl TEXT NOT NULL, ab TEXT NOT NULL, zeit INTEGER NOT NULL, vorgabe INTEGER NOT NULL DEFAULT 0,
    anteile TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (schl, ab));
CREATE TABLE IF NOT EXISTS ep_entwuerfe (schl TEXT PRIMARY KEY, zeit INTEGER NOT NULL, autor_id TEXT NOT NULL DEFAULT '', autor_name TEXT NOT NULL DEFAULT '',
    anteile TEXT NOT NULL, ruecklage REAL);
CREATE TABLE IF NOT EXISTS ep_log (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, schl TEXT NOT NULL, autor_id TEXT NOT NULL DEFAULT '',
    autor_name TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ep_zufriedenheit (lauf INTEGER NOT NULL, schl TEXT NOT NULL, wert REAL NOT NULL, ziel REAL NOT NULL,
    PRIMARY KEY (lauf, schl));
CREATE TABLE IF NOT EXISTS ep_verteilung (lauf INTEGER NOT NULL, schl TEXT NOT NULL, kategorie TEXT NOT NULL, betrag INTEGER NOT NULL,
    PRIMARY KEY (lauf, schl, kategorie));
"""


def einrichten(con):
    neu = not con.execute("SELECT 1 FROM sqlite_master WHERE name='ep_entwuerfe'").fetchone()
    con.executescript(SCHEMA)
    if "ruecklage" not in {r[1] for r in con.execute("PRAGMA table_info(ep_fassungen)")}:
        con.execute("ALTER TABLE ep_fassungen ADD COLUMN ruecklage REAL")   # Rücklage in % des eigenen Steueranteils (− = Entnahme); NULL = Vorgabe
    if not con.execute("SELECT 1 FROM ep_fassungen LIMIT 1").fetchone():
        # Übernahme der bisherigen Pläne: gelten von Anfang an, sperren nicht (zeit 0)
        alt = {}
        for r in con.execute("SELECT schl, kategorie, anteil FROM ep_plaene"):
            alt.setdefault(r["schl"], {})[r["kategorie"]] = float(r["anteil"])
        for schl, w in alt.items():
            if len(w) == len(KATEGORIEN):
                con.execute("INSERT INTO ep_fassungen (schl, ab, zeit, vorgabe, anteile) VALUES (?,?,0,0,?)", (schl, "0000-00", json.dumps(w)))
    if neu:
        # Nach der früheren Regel (jederzeit änderbar, gilt ab Folgemonat) vorgemerkte Fassungen werden Entwürfe: sie gelten erst, wenn sie in der Änderungsperiode eingereicht sind.
        for r in con.execute("SELECT * FROM ep_fassungen WHERE zeit>0 AND ab>?", (monat_heute(),)).fetchall():
            if not r["vorgabe"]:
                con.execute("INSERT OR IGNORE INTO ep_entwuerfe (schl, zeit, autor_id, autor_name, anteile, ruecklage) VALUES (?,?,?,?,?,?)",
                            (r["schl"], r["zeit"], "", "Übernahme", r["anteile"], r["ruecklage"]))
            con.execute("DELETE FROM ep_fassungen WHERE schl=? AND ab=?", (r["schl"], r["ab"]))
    con.commit()


# ---------------------------------------------------------------- Fassungen, Gültigkeit und Sperre

def _folgemonat(periode):
    j, m = (int(t) for t in periode.split("-"))
    return f"{j + (m == 12)}-{m % 12 + 1:02d}"


def heute():
    return date.today()


def monat_heute():
    return heute().strftime("%Y-%m")


def monat_folgend():
    """Monat, ab dem eine heute gespeicherte Änderung gilt."""
    return _folgemonat(monat_heute())


def naechster_lauf(con):
    """Nächster zu buchender Haushaltsmonat: der laufende, solange er nicht gebucht ist, sonst der folgende."""
    m = monat_heute()
    return _folgemonat(m) if con.execute("SELECT 1 FROM ak_laeufe WHERE periode=?", (m,)).fetchone() else m


def fassung(con, schl, periode=None):
    """Für den Monat geltende Fassung (Row) oder None (= Vorgabe)."""
    return con.execute("SELECT * FROM ep_fassungen WHERE schl=? AND ab<=? ORDER BY ab DESC LIMIT 1",
                       (schl, periode or naechster_lauf(con))).fetchone()


def vorgemerkt(con, schl):
    """Fassung, die erst in einem künftigen Monat gilt (nach dem laufenden Kalendermonat), oder None."""
    return con.execute("SELECT * FROM ep_fassungen WHERE schl=? AND ab>? ORDER BY ab DESC LIMIT 1", (schl, monat_heute())).fetchone()


def ruecklage_satz(con, schl, periode=None, entwurf=None):
    """Eigener Rücklagensatz der geltenden Fassung (% des eigenen Steueranteils, negativ = Entnahme aus der Kasse) oder None (Vorgabe)."""
    if entwurf and schl in entwurf:
        r = entwurf[schl].get("ruecklage")
        return None if r is None else float(r)
    f = fassung(con, schl, periode)
    return None if not f or f["vorgabe"] or f["ruecklage"] is None else float(f["ruecklage"])


def kasse_gebunden(con, kasse, reich=False):
    """Im Monat schon verplante Mittel einer Kasse: Besoldung des letzten Lohnlaufs aus dieser Kasse, beim Reich dazu die Etats der Behörden."""
    if not kasse:
        return 0
    lauf = con.execute("SELECT periode FROM bs_laeufe ORDER BY periode DESC LIMIT 1").fetchone()
    b = con.execute("SELECT COALESCE(SUM(brutto),0) FROM bs_abrechnungen WHERE periode=? AND zahlstelle=? AND nachzahlung=0",
                    (lauf["periode"], kasse["name"])).fetchone()[0] if lauf else 0
    if reich:
        import etat
        b += sum(etat.etats(con).values())
    return int(b)


def kasse_frei(con, kasse, reich=False):
    """Freie Mittel (Heller) einer Staats- bzw. der Reichskasse, die ein Etat entnehmen darf: Kontostand minus gebundene Mittel."""
    return max(0, int(kasse["saldo"]) - kasse_gebunden(con, kasse, reich)) if kasse else 0


def aenderungsperiode(d=None):
    """(Beginn, Ende) der Änderungsperiode im Monat von d: die letzten sieben Tage des Kalendermonats. In ihr wird der Etat für den Folgemonat eingereicht."""
    d = d or heute()
    ende = d.replace(day=calendar.monthrange(d.year, d.month)[1])
    return ende - timedelta(days=6), ende


def in_aenderungsperiode(d=None):
    d = d or heute()
    return aenderungsperiode(d)[0] <= d


def _tag(d):
    return d.strftime("%d.%m.%Y")


# ---------------------------------------------------------------- Verteilung

def vorgabe(verteidigung_prozent):
    """Vorgabe-Verteilung in Prozent: gegebener Verteidigungsanteil, der Rest nach VORGABE_GEWICHT."""
    v = max(0.0, min(100.0, float(verteidigung_prozent)))
    rest = 100.0 - v
    out = {k: VORGABE_GEWICHT[k] * rest / 100.0 for k, _ in KATEGORIEN if k != "verteidigung"}
    out["verteidigung"] = v
    return {k: out[k] for k, _ in KATEGORIEN}


def runden100(anteile):
    """Prozentwerte auf eine Nachkommastelle runden, sodass sie genau 100,0 ergeben (Rest bei der größten Nicht-Verteidigungs-Kategorie)."""
    out = {k: round(float(v), 1) for k, v in anteile.items()}
    rest = round(100.0 - sum(out.values()), 1)
    if rest:
        ziel = max((k for k in out if k != "verteidigung"), key=lambda k: out[k])
        out[ziel] = round(out[ziel] + rest, 1)
    return out


def angepasst(con, schl, periode=None):
    f = fassung(con, schl, periode)
    return bool(f and not f["vorgabe"])


def plan(con, schl, vorgabe_verteidigung=0.0, periode=None, entwurf=None):
    """Verteilung (Kategorie → Prozent des Ausgabenbudgets) für 'reich' oder 'ts-<sid>' im Monat periode (Vorgabe: nächster Lauf).
    entwurf = {schl: {"anteile": …, "ruecklage": …}} rechnet probeweise mit einem Entwurf statt der geltenden Fassung."""
    if entwurf and schl in entwurf:
        return {k: float(entwurf[schl]["anteile"][k]) for k, _ in KATEGORIEN}
    f = fassung(con, schl, periode)
    rows = json.loads(f["anteile"]) if f and not f["vorgabe"] else {}
    if len(rows) == len(KATEGORIEN):
        return {k: rows[k] for k, _ in KATEGORIEN}
    return vorgabe(vorgabe_verteidigung)


def verteilung(pool, anteile):
    """Beträge (Heller) je Kategorie aus Ausgabenbudget und Prozenten; Summe = pool (Rundungsrest bei der größten Nicht-Verteidigungs-Kategorie)."""
    out = {k: int(round(pool * float(anteile.get(k, 0)) / 100.0)) for k, _ in KATEGORIEN}
    rest = pool - sum(out.values())
    if rest and pool:
        ziel = max((k for k, _ in KATEGORIEN if k != "verteidigung"), key=lambda k: out[k])
        out[ziel] += rest
    return out


def aktuelle(con, schl, liste, periode=None):
    """Verteilung in Prozent im Monat periode (gespeichert oder Vorgabe, wie sie berechnet wird); liste = aufkommen.berechnen(con, periode=periode)."""
    if angepasst(con, schl, periode):
        return plan(con, schl, 0.0, periode)
    if schl == "reich":
        pool = sum(x["pool_reich"] for x in liste)
        return {kat: (sum(x["verteilung_reich"].get(kat, 0) for x in liste) / pool * 100 if pool else 0) for kat, _ in KATEGORIEN}
    x = next((x for x in liste if "ts-" + x["staat"] == schl), None)
    return {kat: (x["verteilung_land"].get(kat, 0) / x["pool_land"] * 100 if x and x["pool_land"] else 0) for kat, _ in KATEGORIEN}


def entwurf(con, schl):
    """Gespeicherter Entwurf des Haushalts (Row) oder None."""
    return con.execute("SELECT * FROM ep_entwuerfe WHERE schl=?", (schl,)).fetchone()


def entwurf_speichern(con, schl, werte, ruecklage, k):
    """Speichert (ersetzt) den Entwurf: beliebig oft, ohne Wirkung auf den Haushalt."""
    con.execute("INSERT OR REPLACE INTO ep_entwuerfe (schl, zeit, autor_id, autor_name, anteile, ruecklage) VALUES (?,?,?,?,?,?)",
                (schl, int(time.time()), k["id"] if k else "", k["name"] if k else "System",
                 json.dumps({kat: round(float(werte[kat]), 2) for kat, _ in KATEGORIEN}), None if ruecklage is None else round(float(ruecklage), 2)))
    _log(con, schl, k, "Entwurf gespeichert (noch nicht eingereicht)")


def eingereicht(con, schl):
    """Für den Folgemonat eingereichte Fassung (Row) oder None."""
    return con.execute("SELECT * FROM ep_fassungen WHERE schl=? AND ab=? AND zeit>0", (schl, monat_folgend())).fetchone()


def _aenderungstext(alt, neu, rl_alt, rl_neu):
    aend = [f'{NAMEN[kat]} {alt[kat]:.1f} % → {float(neu[kat]):.1f} %'.replace(".", ",") for kat, _ in KATEGORIEN if abs(alt[kat] - float(neu[kat])) >= 0.05]
    if rl_neu is not None and rl_alt is not None and abs(rl_neu - rl_alt) >= 0.05:
        aend.insert(0, f'Rücklage {rl_alt:+.1f} % → {rl_neu:+.1f} %'.replace(".", ",").replace("-", "−"))
    return "; ".join(aend) if aend else "unverändert"


def einreichen(con, schl, k, alt, rl_alt):
    """Reicht den zuletzt gespeicherten Entwurf endgültig als Etat für den Folgemonat ein. Gibt einen Fehlertext zurück oder None bei Erfolg.
    alt/rl_alt = bisher geltende Verteilung und Rücklage (für das Änderungsprotokoll)."""
    ab = monat_folgend()
    von, bis = aenderungsperiode()
    if not in_aenderungsperiode():
        return f"Der Etat kann nur in der Änderungsperiode eingereicht werden ({_tag(von)} bis {_tag(bis)})."
    if eingereicht(con, schl):
        return f"Der Etat für {sa._monatsname(ab)} wurde schon eingereicht."
    e = entwurf(con, schl)
    if not e:
        return "Es ist noch kein Entwurf gespeichert. Bitte zuerst „Entwurf speichern“."
    con.execute("INSERT OR REPLACE INTO ep_fassungen (schl, ab, zeit, vorgabe, anteile, ruecklage) VALUES (?,?,?,0,?,?)",
                (schl, ab, int(time.time()), e["anteile"], e["ruecklage"]))
    con.execute("DELETE FROM ep_entwuerfe WHERE schl=?", (schl,))
    _log(con, schl, k, f"Etat für {sa._monatsname(ab)} eingereicht: " + _aenderungstext(alt, json.loads(e["anteile"]), rl_alt, e["ruecklage"]))
    return None


def _log(con, schl, k, text):
    con.execute("INSERT INTO ep_log (zeit, schl, autor_id, autor_name, text) VALUES (?,?,?,?,?)",
                (int(time.time()), schl, k["id"] if k else "", k["name"] if k else "System", text[:600]))
    geld.protokoll(con, k, "Etatverteilung", f'{schl}: {text}'[:600])


def verteilung_speichern(con, lauf, x):
    """Hält die Verteilung eines Haushaltsmonats fest (aus aufkommen.berechnen: verteilung_reich/verteilung_land je Posten)."""
    for schl, ver in (("reich", x.get("verteilung_reich")), ("ts-" + x["staat"], x.get("verteilung_land"))):
        for kat, betrag in (ver or {}).items():
            con.execute("INSERT OR REPLACE INTO ep_verteilung (lauf, schl, kategorie, betrag) VALUES (?,?,?,?)", (lauf, schl, kat, int(betrag)))


# ---------------------------------------------------------------- Wirkungen (Boni und Mali)
# Richtwert je Kategorie = Vorgabe-Verteilung des Haushalts (vorgabe(): Verteidigung nach BIP-Regel, Rest nach VORGABE_GEWICHT).
# Erfüllung e = Anteil ÷ Richtwert. Unter „malus_ab“ greift der Malus (voll ab „malus_voll“), zwischen „bonus_ab“ und „bonus_bis“ der Bonus,
# darüber nimmt er bis „saettigung“ ab (Überversorgung bringt nichts, das Geld fehlt anderswo). Sind alle Kategorien mindestens bei „bonus_ab“,
# gibt es zusätzlich den Bonus „Ausgewogener Etat“. Ziel ist also ein ausgewogener Etat mit leichten Schwerpunkten.
# Hebel: einnahmen = Steueraufkommen des Gebiets in % (trifft Reichsabgabe und Landesanteil gleichermaßen; beim Reich das Aufkommen der
# Freien Reichsgebiete), ruecklage = Prozentpunkte des eigenen Anteils, die zusätzlich als Rücklage in der Kasse bleiben (negativ: Mehrausgaben),
# bereitschaft = Punkte Einsatzbereitschaft des Militärgeräts je Monat (Verteidigungskasse bzw. Reichsverteidigungskasse).
GRENZEN = {"malus_ab": 0.75, "malus_voll": 0.25, "bonus_ab": 0.9, "bonus_bis": 1.6, "saettigung": 2.4}
HEBEL = {"einnahmen": ("Steueraufkommen", "%"), "ruecklage": ("Rücklage", "Pp."), "bereitschaft": ("Einsatzbereitschaft", "Pkt./Monat")}
WIRKUNGEN = {
    "innere_sicherheit": ({"einnahmen": 0.3}, "Steuerehrlichkeit – weniger Betrug und Schwarzarbeit",
                          {"einnahmen": -2.5}, "Kriminalität und Schattenwirtschaft"),
    "forschung": ({"einnahmen": 0.6}, "Innovationen stärken die Wirtschaft",
                  {"einnahmen": -1.0}, "Abwanderung von Fachkräften und Unternehmen"),
    "gesundheit": ({"einnahmen": 0.3}, "Gesunde Bevölkerung, weniger Arbeitsausfall",
                   {"einnahmen": -2.0, "ruecklage": -0.5}, "Krankheitswellen: Arbeitsausfall und Notfallkosten"),
    "industrie": ({"einnahmen": 0.6}, "Wettbewerbsfähige Industrie",
                  {"einnahmen": -2.0}, "Deindustrialisierung und Betriebsschließungen"),
    "kultur": ({"einnahmen": 0.2}, "Tourismus und Ansehen des Landes",
               {"einnahmen": -0.5}, "Verödung der Städte, ausbleibender Tourismus"),
    "verteidigung": ({"bereitschaft": 2.0}, "Gut ausgestattete Truppe – Einsatzbereitschaft steigt",
                     {"bereitschaft": -6.0}, "Ersatzteilmangel und Ausbildungslücken – Einsatzbereitschaft sinkt"),
    "soziales": ({"einnahmen": 0.3}, "Sozialer Frieden und hohe Beschäftigung",
                 {"einnahmen": -3.0, "ruecklage": -0.5}, "Armut, Streiks und Unruhen; teure Notprogramme"),
    "umwelt": ({"ruecklage": 0.1}, "Weniger Schäden durch Unwetter und Verschmutzung",
               {"ruecklage": -0.8}, "Umweltschäden und teure Sanierungen"),
    "transport": ({"einnahmen": 0.4}, "Leistungsfähige Verkehrswege für den Handel",
                  {"einnahmen": -2.0}, "Marode Straßen, Brücken und Bahnen bremsen den Handel"),
    "bildung": ({"einnahmen": 0.3}, "Gut ausgebildete Arbeitskräfte",
                {"einnahmen": -1.5}, "Fachkräftemangel"),
    "landwirtschaft": ({"ruecklage": 0.15}, "Selbstversorgung mit Lebensmitteln",
                       {"ruecklage": -0.8}, "Teure Lebensmitteleinfuhren und Ernteausfälle"),
}
AUSGEWOGEN = ({"einnahmen": 0.5}, "Ausgewogener Etat: alle Politikfelder mindestens zu 90 % des Richtwerts versorgt")


def richtwerte(verteidigung_prozent):
    return vorgabe(verteidigung_prozent)


def _stufe(e):
    """(Stufe, Stärke 0…1) zur Erfüllung e."""
    g = GRENZEN
    if e < g["malus_ab"]:
        return "malus", min(1.0, (g["malus_ab"] - e) / (g["malus_ab"] - g["malus_voll"]))
    if e < g["bonus_ab"]:
        return "knapp", 0.0
    if e <= g["bonus_bis"]:
        return "bonus", 1.0
    if e < g["saettigung"]:
        return "bonus", (g["saettigung"] - e) / (g["saettigung"] - g["bonus_bis"])
    return "ueber", 0.0


def bewerten(anteile, richt):
    """Boni und Mali einer Verteilung (Prozent je Kategorie) gegenüber den Richtwerten.
    → {"zeilen": [{kat, anteil, richt, e, stufe, staerke, effekt}], "summe": {hebel: Wert}, "ausgewogen", "boni", "mali"}"""
    zeilen, summe = [], {h: 0.0 for h in HEBEL}
    for kat, _ in KATEGORIEN:
        a, r = float(anteile.get(kat, 0)), float(richt.get(kat, 0))
        bonus, _, malus, _ = WIRKUNGEN[kat]
        if r < 0.05:
            e, stufe, st = None, "knapp", 0.0
        else:
            e = a / r
            stufe, st = _stufe(e)
        quelle = bonus if stufe == "bonus" else malus if stufe == "malus" else {}
        effekt = {h: round(v * st, 3) for h, v in quelle.items()}
        for h, v in effekt.items():
            summe[h] += v
        zeilen.append({"kat": kat, "anteil": a, "richt": r, "e": e, "stufe": stufe, "staerke": st, "effekt": effekt})
    ausgewogen = all(z["e"] is None or z["e"] >= GRENZEN["bonus_ab"] for z in zeilen)
    if ausgewogen:
        for h, v in AUSGEWOGEN[0].items():
            summe[h] += v
    return {"zeilen": zeilen, "summe": {h: round(v, 3) for h, v in summe.items()}, "ausgewogen": ausgewogen,
            "boni": sum(1 for z in zeilen if z["stufe"] == "bonus" and z["staerke"] > 0),
            "mali": sum(1 for z in zeilen if z["stufe"] == "malus" and z["staerke"] > 0)}


def hebel_text(effekt):
    """'Steueraufkommen −2,5 %, Rücklage −0,5 Pp.'"""
    teile = []
    for h, v in effekt.items():
        if abs(v) < 0.0005:
            continue
        name, einheit = HEBEL[h]
        teile.append(f'{name} {"+" if v > 0 else "−"}{_de(abs(v), 2).rstrip("0").rstrip(",")} {einheit}')
    return ", ".join(teile)


def bereitschaft_wirkung(con, periode=None):
    """{Verteidigungskasse (Stelle): Punkte Einsatzbereitschaft je Monat} aus der Etatverteilung des Monats (für verteidigung.instandhaltung)."""
    import aufkommen
    out = {}
    for x in aufkommen.berechnen(con, periode=periode):
        out.setdefault("verteidigung", x["wirkung_reich"]["summe"]["bereitschaft"])
        if not x["reichsgebiet"] and x.get("wirkung_land"):
            out["vt-" + x["staat"]] = x["wirkung_land"]["summe"]["bereitschaft"]
    return out


# ---------------------------------------------------------------- Bevölkerungszufriedenheit (Index 0–100)
# Je Politikfeld eine Teilnote 0–100 aus der Erfüllung e (Anteil ÷ Richtwert): 100 × (1 − exp(−1,6 e)) – abnehmender Grenznutzen,
# Vorgabe-Verteilung (e = 1) ≈ 80. Index = gewichteter Schnitt nach ZUF_GEWICHTE (was die Bevölkerung im Alltag spürt).
# Trägheit: Die Stimmung bewegt sich je gebuchtem Monat nur um ZUF_TRAEGHEIT des Abstands zum Zielwert (ep_zufriedenheit je Haushaltsmonat).
# Wirkung auf das Steueraufkommen (zusätzlich zu den Boni/Mali der Felder): ab 85 Bonus, unter 55 Malus (bis −4 %).
ZUF_GEWICHTE = {"soziales": 24, "gesundheit": 20, "bildung": 12, "innere_sicherheit": 12, "kultur": 8, "umwelt": 8, "transport": 6,
                "landwirtschaft": 5, "industrie": 3, "forschung": 2, "verteidigung": 0}
ZUF_TRAEGHEIT = 0.5
ZUF_STUFEN = [(85, "Sehr zufrieden"), (70, "Zufrieden"), (55, "Gespalten"), (40, "Unzufrieden"), (0, "Unruhen")]
ZUF_WIRKUNG = {"bonus_ab": 85, "bonus": 0.5, "malus_ab": 55, "malus_je_punkt": 0.15, "malus_max": 4.0}


def zuf_teilnote(e):
    return 100.0 * (1 - math.exp(-1.6 * max(0.0, e)))


def zuf_ziel(anteile, richt):
    """(Zielwert, [(Kategorie, Teilnote, Gewicht)]) der Zufriedenheit für eine Verteilung."""
    teile, summe, gew = [], 0.0, 0.0
    for kat, _ in KATEGORIEN:
        g = ZUF_GEWICHTE.get(kat, 0)
        r = float(richt.get(kat, 0))
        if not g or r < 0.05:
            continue
        note = zuf_teilnote(float(anteile.get(kat, 0)) / r)
        teile.append((kat, note, g))
        summe += note * g
        gew += g
    return (summe / gew if gew else 0.0), teile


def zuf_stufe(wert):
    return next(n for grenze, n in ZUF_STUFEN if wert >= grenze)


def zuf_effekt(wert):
    """Wirkung des Index auf das Steueraufkommen in %."""
    w = ZUF_WIRKUNG
    if wert >= w["bonus_ab"]:
        return w["bonus"]
    if wert < w["malus_ab"]:
        return -min(w["malus_max"], (w["malus_ab"] - wert) * w["malus_je_punkt"])
    return 0.0


def zuf_letzte(con, schl):
    r = con.execute("SELECT wert FROM ep_zufriedenheit WHERE schl=? ORDER BY lauf DESC LIMIT 1", (schl,)).fetchone()
    return float(r["wert"]) if r else None


def zuf_verlauf(con, schl, n=12):
    return [(r["periode"], float(r["wert"])) for r in con.execute(
        "SELECT l.periode, z.wert FROM ep_zufriedenheit z JOIN ak_laeufe l ON l.id=z.lauf WHERE z.schl=? ORDER BY z.lauf DESC LIMIT ?", (schl, n))][::-1]


def zufriedenheit(con, schl, anteile, richt):
    """{"ziel", "alt", "neu", "stufe", "effekt", "teile"}: neu = Wert des nächsten gebuchten Monats (Trägheit gegenüber dem letzten Monat)."""
    ziel, teile = zuf_ziel(anteile, richt)
    alt = zuf_letzte(con, schl)
    neu = ziel if alt is None else alt + (ziel - alt) * ZUF_TRAEGHEIT
    return {"ziel": round(ziel, 1), "alt": None if alt is None else round(alt, 1), "neu": round(neu, 1), "stufe": zuf_stufe(neu),
            "effekt": round(zuf_effekt(neu), 3), "teile": teile}


def zuf_speichern(con, lauf, liste):
    """Hält die Zufriedenheit eines gebuchten Monats fest (aus aufkommen.berechnen)."""
    z = liste[0]["zufriedenheit_reich"] if liste else None
    if z:
        con.execute("INSERT OR REPLACE INTO ep_zufriedenheit (lauf, schl, wert, ziel) VALUES (?,?,?,?)", (lauf, "reich", z["neu"], z["ziel"]))
    for x in liste:
        if x.get("zufriedenheit_land"):
            z = x["zufriedenheit_land"]
            con.execute("INSERT OR REPLACE INTO ep_zufriedenheit (lauf, schl, wert, ziel) VALUES (?,?,?,?)", (lauf, "ts-" + x["staat"], z["neu"], z["ziel"]))


def zuf_reichsweit(liste):
    """Nach Einwohnern gewichteter Index des ganzen Reiches (Freie Reichsgebiete: Zufriedenheit des Reichsetats)."""
    s = ew = 0
    for x in liste:
        z = x["zufriedenheit_reich"] if x["reichsgebiet"] else x.get("zufriedenheit_land")
        if z:
            s += z["neu"] * x["ew"]
            ew += x["ew"]
    return s / ew if ew else 0.0


# ---------------------------------------------------------------- Rechte

def haushaltsfuehrung(liste, schl):
    """Tatsächliche Rücklage in % des eigenen Steueranteils (positiv = gespart, negativ = aus der Kasse entnommen)."""
    if schl == "reich":
        basis, pool = sum(x["reich"] for x in liste), sum(x["pool_reich"] for x in liste)
    else:
        x = next((x for x in liste if "ts-" + x["staat"] == schl), None)
        basis, pool = (x["land"], x["pool_land"]) if x else (0, 0)
    return (basis - pool) / basis * 100 if basis else 0.0


def _rl_text(pz, betrag, kassen_name, gedeckelt=False):
    if pz > 0.05:
        return f'Sparen: <b>{_de(pz)} %</b> ({esc(mark(betrag))}) bleiben im Monat in der {esc(kassen_name)}.'
    if pz < -0.05:
        return (f'Entnahme: <b>{_de(-pz)} %</b> ({esc(mark(-betrag))}) kommen im Monat zusätzlich aus der {esc(kassen_name)}.'
                + (' Begrenzt auf die freien Mittel der Kasse.' if gedeckelt else ''))
    return 'Ausgeglichen: der ganze Steueranteil wird ausgegeben.'


def darf_aendern(con, k, schl):
    if not k or not k["mitglied"]:
        return False
    if schl == "reich":
        return geld.ist_leitung(k)
    return any(r["stelle"] == schl for r in geld.regierte_staatskassen(con, k))


def ziele(con, liste):
    """[(schl, Name)]: Reich und alle Teilstaaten (ohne Freie Reichsgebiete)."""
    return [("reich", "Reich")] + [("ts-" + x["staat"], x["name"]) for x in sorted(liste, key=lambda x: x["name"]) if not x["reichsgebiet"]]


# ---------------------------------------------------------------- Seite

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]   # validierte Kategorienfolge (Slots 1–8)
CSS = """<style>
.ep-raster{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:28px;align-items:start;margin:14px 0}
@media (max-width:900px){.ep-raster{grid-template-columns:1fr}}
.ep-torte{position:relative;max-width:380px;margin:0 auto;width:100%}
.ep-torte svg{width:100%;height:auto;display:block;overflow:visible}
.ep-torte path{stroke:#fff;stroke-width:2;transition:opacity .15s,transform .15s;cursor:pointer;outline:0}
.ep-torte path:focus-visible{stroke:var(--ink);stroke-width:3}
.ep-torte.hat-fokus path:not(.fokus){opacity:.35}
.ep-tipp{position:absolute;pointer-events:none;background:var(--ink);color:#fff;border-radius:8px;padding:7px 10px;font-size:13px;line-height:1.35;
 white-space:nowrap;z-index:5;opacity:0;transition:opacity .1s;transform:translate(-50%,-110%)}
.ep-tipp.an{opacity:1}
.ep-tab{width:100%;border-collapse:collapse;font-size:14px}
.ep-tab th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--grau);font-weight:600;text-align:left;padding:6px 8px;border-bottom:1px solid var(--linie)}
.ep-tab td{padding:6px 8px;border-bottom:1px solid #eef0f2;vertical-align:middle}
.ep-tab td:first-child{white-space:nowrap}
.ep-tab tr.fokus td{background:var(--hell)}
.ep-tab td.num,.ep-tab th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ep-farbe{display:inline-block;width:14px;height:14px;border-radius:4px;vertical-align:-2px;margin-right:8px}
.ep-farbe.schraffur{background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.75) 0 2px,transparent 2px 5px)}
.ep-fest td{color:var(--grau)}
.ep-tab input[type=number]{width:84px;text-align:right;padding:4px 6px}
.ep-tab input[type=range]{width:120px;vertical-align:middle;accent-color:var(--ink)}
.ep-summe{display:flex;gap:10px;align-items:center;margin:10px 0;font-weight:600}
.ep-summe.falsch{color:var(--rot)}.ep-summe.richtig{color:var(--ok)}
.ep-hinweis{margin:8px 0}
.ep-einreichen{border-top:1px solid var(--linie,#e3e4e7);margin-top:14px;padding-top:10px;font-size:13.5px}
.ep-einreichen p{margin:0 0 8px}
.ep-hf{display:flex;gap:8px;align-items:center}.ep-hf .icon{width:16px;height:16px;flex:none}
.ep-rl{border:1px solid var(--linie,#e3e4e7);border-radius:10px;padding:12px 14px;margin:0 0 14px}
.ep-rl-kopf{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.ep-rl-titel{font-weight:600}
.ep-rl-feld{display:flex;align-items:center;gap:8px}
.ep-rl-feld input[type=range]{width:200px;accent-color:var(--ink)}
.ep-rl-feld input[type=number]{width:84px;text-align:right;padding:4px 6px}
.ep-rl-hilfe{font-size:12.5px;color:var(--grau);margin:6px 0}
.ep-rl-info{margin:6px 0;font-size:14px}
.ep-kasse{display:flex;gap:8px;align-items:flex-start;font-size:12.5px;color:var(--grau)}
.ep-kasse .icon{width:15px;height:15px;flex:none;margin-top:1px}
.ep-farbe-leer{background:transparent;border:1px dashed var(--grau)}
@media (max-width:600px){.ep-rl-feld{width:100%}.ep-rl-feld input[type=range]{flex:1;width:auto}}
.ep-vergleich td,.ep-vergleich th{font-size:12.5px;padding:5px 6px;text-align:right;white-space:nowrap}
.ep-vergleich td:first-child,.ep-vergleich th:first-child{text-align:left}
.ep-scroll{overflow-x:auto}
@media (max-width:800px){
 .ep-raster>div{min-width:0}
 .ep-torte{max-width:300px}
 .ep-tab input[type=range]{display:none}
 .ep-tab th:nth-child(3),.ep-tab td:nth-child(3){display:none}
 .ep-tab td:first-child{white-space:normal}
 .ep-tab input[type=number]{width:70px}
 .ep-tab th,.ep-tab td{padding:6px 4px}
 .ep-tab th.num{white-space:normal;font-size:10.5px}
}
</style>"""

JS = r"""
(function(){
var D=JSON.parse(document.getElementById("ep-daten").textContent);
var farben=D.farben, svgNS="http://www.w3.org/2000/svg";
var torte=document.getElementById("ep-torte"), svg=torte.querySelector("svg"), tipp=document.getElementById("ep-tipp");
function de(h){return (h/100).toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})+" Kr"}
function kurz(h){var k=h/100,a=Math.abs(k);
 if(a>=1e12)return (k/1e12).toLocaleString("de-DE",{maximumFractionDigits:2})+" Bio. Kr";
 if(a>=1e9)return (k/1e9).toLocaleString("de-DE",{maximumFractionDigits:2})+" Mrd. Kr";
 if(a>=1e6)return (k/1e6).toLocaleString("de-DE",{maximumFractionDigits:2})+" Mio. Kr";
 return de(h)}
function pz(x){return x.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})+" %"}
var felder=[].slice.call(document.querySelectorAll("input[type=number][data-kat]"));
var regler=[].slice.call(document.querySelectorAll("input[type=range][data-kat]"));
function scheiben(){
 var s=[];
 D.fest_vorn.forEach(function(f){s.push(f)});
 D.kategorien.forEach(function(k,i){
  var f=felder.filter(function(e){return e.dataset.kat===k.id})[0];
  var p=f?(parseFloat(String(f.value).replace(",","."))||0):k.anteil;
  s.push({id:k.id,name:k.name,betrag:Math.round(D.pool*p/100),farbe:k.farbe,schraffur:k.schraffur,anteil:p});
 });
 D.fest_hinten.forEach(function(f){s.push(f)});
 return s}
function pfad(a0,a1,r){var x0=100+r*Math.sin(a0),y0=100-r*Math.cos(a0),x1=100+r*Math.sin(a1),y1=100-r*Math.cos(a1),gross=(a1-a0)>Math.PI?1:0;
 return "M100,100 L"+x0+","+y0+" A"+r+","+r+" 0 "+gross+" 1 "+x1+","+y1+" Z"}
function rlRechnen(){var e=document.getElementById("ep-rl");if(!e||!D.rl)return;var R=D.rl;
 var r=parseFloat(String(e.value).replace(",","."));if(isNaN(r))r=0;
 var pool=Math.round(R.basis*Math.max(0,1-r/100-R.w/100)),ged=false;
 if(pool-R.basis>R.frei){pool=R.basis+R.frei;ged=true}
 var rl=R.basis-pool,p=R.basis?rl/R.basis*100:0;D.pool=pool;D.fest_hinten[0].betrag=Math.max(0,rl);
 function t(id,v){var o=document.getElementById(id);if(o)o.textContent=v}
 t("ep-kz-pool",kurz(pool));t("ep-kz-rl",kurz(Math.abs(rl)));t("ep-kz-rl-t",rl>=0?"Rücklage":"Entnahme aus der "+R.kasse);
 var z=document.getElementById("ep-entnahme-zeile");if(z)z.hidden=rl>=0;t("ep-entnahme-betrag",kurz(Math.max(0,-rl)));t("ep-entnahme-pz",pz(D.gesamt?Math.max(0,-rl)/D.gesamt*100:0));
 var i=document.getElementById("ep-rl-info");if(i)i.innerHTML=p>0.05?"Sparen: <b>"+pz(p)+"</b> ("+de(rl)+") bleiben im Monat in der "+R.kasse+".":
  p<-0.05?"Entnahme: <b>"+pz(-p)+"</b> ("+de(-rl)+") kommen im Monat zusätzlich aus der "+R.kasse+"."+(ged?" Begrenzt auf die freien Mittel der Kasse.":""):"Ausgeglichen: der ganze Steueranteil wird ausgegeben."}
function zeichnen(){
 rlRechnen();
 var s=scheiben(), gesamt=D.gesamt||1, w=0;
 while(svg.firstChild)svg.removeChild(svg.firstChild);
 var defs=document.createElementNS(svgNS,"defs");
 s.forEach(function(x,i){if(x.schraffur){var p=document.createElementNS(svgNS,"pattern");p.setAttribute("id","hs"+i);p.setAttribute("width","7");p.setAttribute("height","7");
  p.setAttribute("patternUnits","userSpaceOnUse");p.setAttribute("patternTransform","rotate(45)");
  var r=document.createElementNS(svgNS,"rect");r.setAttribute("width","7");r.setAttribute("height","7");r.setAttribute("fill",x.farbe);p.appendChild(r);
  var l=document.createElementNS(svgNS,"rect");l.setAttribute("width","2.6");l.setAttribute("height","7");l.setAttribute("fill","#fff");l.setAttribute("opacity",".75");p.appendChild(l);defs.appendChild(p)}});
 svg.appendChild(defs);
 var ges=s.reduce(function(a,x){return a+x.betrag},0)||1;
 s.forEach(function(x,i){
  var a0=w/ges*2*Math.PI;w+=x.betrag;var a1=w/ges*2*Math.PI;
  if(x.betrag<=0)return;
  var el=document.createElementNS(svgNS,"path");
  if(a1-a0>=2*Math.PI-1e-6){el=document.createElementNS(svgNS,"circle");el.setAttribute("cx","100");el.setAttribute("cy","100");el.setAttribute("r","96");
   el.setAttribute("style","stroke:#fff;stroke-width:2;cursor:pointer")}
  else el.setAttribute("d",pfad(a0,a1,96));
  el.setAttribute("fill",x.schraffur?"url(#hs"+i+")":x.farbe);
  el.setAttribute("tabindex","0");el.dataset.id=x.id;
  el.setAttribute("aria-label",x.name+": "+pz(x.betrag/gesamt*100)+" des Etats"+(D.nur_prozent?"":", "+de(x.betrag)));
  el.addEventListener("mousemove",function(e){zeigen(x,e)});el.addEventListener("mouseleave",weg);
  el.addEventListener("focus",function(){fokus(x.id,true);var b=el.getBBox();zeigenAn(x,b.x+b.width/2,b.y+b.height/2)});el.addEventListener("blur",weg);
  svg.appendChild(el)});
 s.forEach(function(x){var z=document.querySelector('[data-zeile="'+x.id+'"]');if(!z)return;
  var b=z.querySelector(".ep-betrag"),a=z.querySelector(".ep-anteil-gesamt");if(b)b.textContent=kurz(x.betrag);b&&b.setAttribute("title",de(x.betrag));
  if(a)a.textContent=pz(x.betrag/gesamt*100)});
 summe()}
function zeigen(x,e){var r=torte.getBoundingClientRect();zeigenAn(x,(e.clientX-r.left)/r.width*200,(e.clientY-r.top)/r.height*200);fokus(x.id,true)}
function zeigenAn(x,px,py){var gesamt=D.gesamt||1;tipp.innerHTML="<b>"+x.name+"</b><br>"+pz(x.betrag/gesamt*100)+" des Etats"+(D.nur_prozent?"":" · "+de(x.betrag));
 tipp.style.left=(px/200*100)+"%";tipp.style.top=(py/200*100)+"%";tipp.classList.add("an")}
function weg(){tipp.classList.remove("an");fokus(null,false)}
function fokus(id,an){torte.classList.toggle("hat-fokus",!!an);[].forEach.call(svg.querySelectorAll("[data-id]"),function(p){p.classList.toggle("fokus",an&&p.dataset.id===id)});
 [].forEach.call(document.querySelectorAll("[data-zeile]"),function(z){z.classList.toggle("fokus",an&&z.dataset.zeile===id)})}
function summe(){var o=document.getElementById("ep-summe");if(!o||!felder.length)return;
 var s=felder.reduce(function(a,f){return a+(parseFloat(String(f.value).replace(",","."))||0)},0), rest=Math.round((100-s)*10)/10;
 var ok=Math.abs(100-s)<=0.05;o.className="ep-summe "+(ok?"richtig":"falsch");
 o.querySelector("span").textContent=ok?"Summe 100 % – bereit zum Speichern":"Summe "+pz(s)+(rest>0?" – es fehlen "+pz(rest):" – "+pz(-rest)+" zu viel");
 var b=document.getElementById("ep-speichern");if(b)b.disabled=!ok;
 var m=document.getElementById("ep-min");if(m){var v=felder.filter(function(f){return f.dataset.kat==="verteidigung"})[0];
  var pv=v?(parseFloat(String(v.value).replace(",","."))||0):0, bet=D.pool*pv/100;m.style.display=bet<D.vt_min?"block":"none"}}
felder.forEach(function(f){f.addEventListener("input",function(){
 var g=document.getElementById("ep-r-"+f.dataset.kat);if(g)g.value=parseFloat(String(f.value).replace(",","."))||0;zeichnen()})});
regler.forEach(function(r){r.addEventListener("input",function(){var n=document.getElementById("ep-n-"+r.dataset.kat);if(n)n.value=r.value;zeichnen()})});
[].forEach.call(document.querySelectorAll("[data-zeile]"),function(z){
 z.addEventListener("mouseenter",function(){fokus(z.dataset.zeile,true)});z.addEventListener("mouseleave",function(){fokus(null,false)})});
(function(){var n=document.getElementById("ep-rl"),g=document.getElementById("ep-rl-r");
 if(n)n.addEventListener("input",function(){if(g)g.value=parseFloat(String(n.value).replace(",","."))||0;zeichnen()});
 if(g)g.addEventListener("input",function(){if(n)n.value=g.value;zeichnen()})})();
var norm=document.getElementById("ep-normieren");
if(norm)norm.addEventListener("click",function(){var n=felder,s=n.reduce(function(a,f){return a+(parseFloat(String(f.value).replace(",","."))||0)},0);
 if(!s)return;var neu=n.map(function(f){return Math.round((parseFloat(String(f.value).replace(",","."))||0)/s*1000)/10}),d=Math.round((100-neu.reduce(function(a,b){return a+b},0))*10)/10;
 var gr=0;neu.forEach(function(v,i){if(v>neu[gr])gr=i});neu[gr]=Math.round((neu[gr]+d)*10)/10;
 n.forEach(function(f,i){f.value=neu[i];var r=document.getElementById("ep-r-"+f.dataset.kat);if(r)r.value=neu[i]});zeichnen()});
zeichnen()})();
"""


def _de(x, stellen=1):
    return f"{x:.{stellen}f}".replace(".", ",")


# ---------------------------------------------------------------- Darstellung der Wirkungen

WK_CSS = """<style>
.ep-wk{margin:22px 0 8px}
.ep-wk h2{display:flex;align-items:center;gap:8px}
.ep-wk .kennzahlen small{display:block;color:var(--grau);font-size:12px;margin-top:2px}
.wk-plus{color:var(--ok)}.wk-minus{color:var(--rot)}
.wk-marke{display:inline-block;font-size:11.5px;font-weight:700;letter-spacing:.03em;padding:2px 8px;border-radius:999px;white-space:nowrap;
 border:1px solid var(--linie);color:var(--grau);background:#fff}
.wk-marke.bonus{background:#e7f6ee;border-color:#9ed4b5;color:#13663d}
.wk-marke.malus{background:#fdecec;border-color:#f0b3b3;color:#a32020}
.wk-ausg{padding:10px 14px;border-radius:10px;margin:10px 0;border:1px solid var(--linie);background:var(--hell)}
.wk-ausg.ja{border-color:#9ed4b5;background:#e7f6ee}
.ep-wk-tab td.wk-text small{display:block;color:var(--grau);font-size:12px;margin-top:2px}
.ep-wk-tab td.num{white-space:nowrap}
@media (max-width:800px){
 .ep-wk-tab thead{display:none}
 .ep-wk-tab tr{display:grid;grid-template-columns:1fr auto auto;gap:2px 10px;align-items:center;padding:8px 0;border-bottom:1px solid #eef0f2}
 .ep-tab.ep-wk-tab td{border:0!important;padding:0}
 .ep-wk-tab td:nth-child(2),.ep-wk-tab td:nth-child(3){display:none}
 .ep-wk-tab td:first-child{font-weight:600}
 .ep-wk-tab td.wk-text{grid-column:1/-1;font-size:13px}
 .ep-wk-tab td.wk-text small{font-size:11.5px}
}
</style>"""

PLAN_JS = r"""
(function(){var f=document.getElementById("ep-form");if(!f)return;
var start=new URLSearchParams(new FormData(f)).toString();
function geaendert(){return new URLSearchParams(new FormData(f)).toString()!==start}
var e=document.getElementById("ep-einreichen-form");
if(e)e.addEventListener("submit",function(ev){
 if(geaendert()){alert("Es gibt ungespeicherte Änderungen. Bitte zuerst „Entwurf speichern“ – eingereicht wird der gespeicherte Entwurf.");ev.preventDefault();return}
 if(!confirm("Etat jetzt endgültig einreichen? Danach lässt er sich bis zur nächsten Änderungsperiode nicht mehr ändern."))ev.preventDefault()});
var v=document.getElementById("ep-vorgabe");
if(v)v.addEventListener("click",function(){
 var R=JSON.parse(v.dataset.richt);
 Object.keys(R).forEach(function(k){var n=document.getElementById("ep-n-"+k),r=document.getElementById("ep-r-"+k);if(n){n.value=R[k];if(r)r.value=R[k];n.dispatchEvent(new Event("input",{bubbles:true}))}});
 var n=document.getElementById("ep-rl"),r=document.getElementById("ep-rl-r");if(n){n.value=v.dataset.rl;if(r)r.value=v.dataset.rl;n.dispatchEvent(new Event("input",{bubbles:true}))}});
})();
"""
WK_JS = r"""
(function(){
var D=JSON.parse(document.getElementById("ep-daten").textContent), W=D.wk; if(!W)return;
var G=W.grenzen;
function zahl(v,st){return v.toLocaleString("de-DE",{minimumFractionDigits:0,maximumFractionDigits:st===undefined?2:st})}
function vz(v,e){return (v>0?"+":v<0?"−":"±")+zahl(Math.abs(v))+" "+e}
function hebel(eff){var t=[];Object.keys(eff).forEach(function(h){var v=eff[h];if(Math.abs(v)<0.0005)return;t.push(W.hebel[h][0]+" "+vz(v,W.hebel[h][1]))});return t.join(", ")}
function stufe(e){if(e<G.malus_ab)return["malus",Math.min(1,(G.malus_ab-e)/(G.malus_ab-G.malus_voll))];if(e<G.bonus_ab)return["knapp",0];
 if(e<=G.bonus_bis)return["bonus",1];if(e<G.saettigung)return["bonus",(G.saettigung-e)/(G.saettigung-G.bonus_bis)];return["ueber",0]}
function kurz(h){var k=h/100,a=Math.abs(k),s=k<0?"−":"+";
 if(a>=1e9)return s+zahl(a/1e9)+" Mrd. Kr";if(a>=1e6)return s+zahl(a/1e6)+" Mio. Kr";return s+zahl(a,0)+" Kr"}
function anteile(){var o={};[].forEach.call(document.querySelectorAll("input[type=number][data-kat]"),function(f){o[f.dataset.kat]=parseFloat(String(f.value).replace(",","."))||0});
 D.kategorien.forEach(function(k){if(!(k.id in o))o[k.id]=k.anteil});return o}
function rechnen(){
 var a=anteile(),sum={einnahmen:0,ruecklage:0,bereitschaft:0},boni=0,mali=0,ausg=true;
 D.kategorien.forEach(function(k){
  var r=W.richt[k.id]||0,w=W.wirkungen[k.id],z=document.querySelector('[data-wk="'+k.id+'"]');if(!z)return;
  var e=null,st=["knapp",0];if(r>=0.05){e=a[k.id]/r;st=stufe(e)}
  if(e!==null&&e<G.bonus_ab)ausg=false;
  var q=st[0]==="bonus"?w[0]:st[0]==="malus"?w[2]:{},eff={};Object.keys(q).forEach(function(h){eff[h]=q[h]*st[1];sum[h]+=eff[h]});
  if(st[0]==="bonus"&&st[1]>0)boni++;if(st[0]==="malus"&&st[1]>0)mali++;
  z.querySelector(".wk-anteil").textContent=zahl(a[k.id],1)+" %";
  z.querySelector(".wk-e").textContent=e===null?"–":zahl(e*100,0)+" %";
  var m=z.querySelector(".wk-marke"),txt=z.querySelector(".wk-haupt");
  if(st[0]==="bonus"&&st[1]>0){m.className="wk-marke bonus";m.textContent=st[1]<1?"Bonus "+zahl(st[1]*100,0)+" %":"Bonus";txt.textContent=w[1]+": "+hebel(eff)+(st[1]<1?" (Überversorgung: Wirkung lässt nach)":"")}
  else if(st[0]==="malus"){m.className="wk-marke malus";m.textContent=st[1]<1?"Malus "+zahl(st[1]*100,0)+" %":"Malus";txt.textContent=w[3]+": "+hebel(eff)}
  else if(st[0]==="ueber"){m.className="wk-marke";m.textContent="Überversorgt";txt.textContent="Kein zusätzlicher Nutzen – das Geld fehlt in anderen Feldern."}
  else{m.className="wk-marke";m.textContent=e===null?"–":"Knapp";txt.textContent=e===null?"Kein Richtwert.":"Keine Wirkung – für den Bonus fehlen "+zahl(Math.max(0.1,Math.ceil((G.bonus_ab*r-a[k.id])*10-1e-9)/10),1)+" Prozentpunkte."}
 });
 if(ausg)Object.keys(W.ausgewogen[0]).forEach(function(h){sum[h]+=W.ausgewogen[0][h]});
 var ae=document.getElementById("wk-ausg");if(ae){ae.className="wk-ausg"+(ausg?" ja":"");ae.querySelector("span").textContent=ausg?
  "Ausgewogener Etat – zusätzlicher Bonus: "+hebel(W.ausgewogen[0])+".":"Kein ausgewogener Etat: Liegen alle Politikfelder bei mindestens "+zahl(G.bonus_ab*100,0)+" % ihres Richtwerts, gibt es zusätzlich "+hebel(W.ausgewogen[0])+"."}
 function setz(id,v,e,basis){var b=document.getElementById(id);if(!b)return;b.textContent=vz(Math.round(v*100)/100,e);b.className=v>0.0005?"wk-plus":v<-0.0005?"wk-minus":"";
  var s=document.getElementById(id+"-kr");if(s&&basis!==undefined)s.textContent=Math.abs(v)<0.0005?"keine Veränderung":"≈ "+kurz(basis*v/100)+" im Monat"}
 setz("wk-ein",sum.einnahmen,"%",W.basis_ein);setz("wk-rl",sum.ruecklage,"Pp.",W.basis_rl);setz("wk-vt",sum.bereitschaft,"Pkt.");
 var bl=document.getElementById("wk-bilanz");if(bl)bl.textContent=boni+" Boni · "+mali+" Mali";
}
[].forEach.call(document.querySelectorAll("input[data-kat]"),function(f){f.addEventListener("input",rechnen)});
var n=document.getElementById("ep-normieren");if(n)n.addEventListener("click",rechnen);
rechnen()})();
"""


def _vz(v, einheit):
    return f'{"+" if v > 0 else "−" if v < 0 else "±"}{_de(abs(v), 2).rstrip("0").rstrip(",")} {einheit}'


def wirkung_daten(richt, basis_ein, basis_rl):
    return {"richt": richt, "wirkungen": WIRKUNGEN, "grenzen": GRENZEN, "hebel": HEBEL, "ausgewogen": AUSGEWOGEN,
            "basis_ein": basis_ein, "basis_rl": basis_rl}


def wirkung_html(bew, basis_ein, basis_rl, reich=False):
    """Abschnitt „Auswirkungen“: Gesamtwirkung + Tabelle je Kategorie (WK_JS aktualisiert ihn live bei Eingaben)."""
    s = bew["summe"]

    def kachel(i, titel, v, einheit, basis=None):
        kl = "wk-plus" if v > 0.0005 else "wk-minus" if v < -0.0005 else ""
        unter = ""
        if basis is not None:
            unter = f'<small id="{i}-kr">{"keine Veränderung" if abs(v) < 0.0005 else "≈ " + ("+" if v > 0 else "−") + geld.mark_kurz(abs(int(basis * v / 100))) + " im Monat"}</small>'
        return f'<div><b id="{i}" class="{kl}">{_vz(v, einheit)}</b>{esc(titel)}{unter}</div>'

    kz = (kachel("wk-ein", "Steueraufkommen" + (" der Freien Reichsgebiete" if reich else ""), s["einnahmen"], "%", basis_ein)
          + kachel("wk-rl", "Rücklage der " + ("Reichskasse" if reich else "Staatskasse"), s["ruecklage"], "Pp.", basis_rl)
          + kachel("wk-vt", "Einsatzbereitschaft je Monat", s["bereitschaft"], "Pkt.")
          + f'<div><b id="wk-bilanz">{bew["boni"]} Boni · {bew["mali"]} Mali</b>Bilanz</div>')
    zeilen = []
    for z in bew["zeilen"]:
        kat = z["kat"]
        bonus, btext, malus, mtext = WIRKUNGEN[kat]
        if z["stufe"] == "bonus" and z["staerke"] > 0:
            marke = f'<span class="wk-marke bonus">Bonus{"" if z["staerke"] >= 1 else " " + _de(z["staerke"] * 100, 0) + " %"}</span>'
            haupt = f'{btext}: {hebel_text(z["effekt"])}' + ("" if z["staerke"] >= 1 else " (Überversorgung: Wirkung lässt nach)")
        elif z["stufe"] == "malus":
            marke = f'<span class="wk-marke malus">Malus{"" if z["staerke"] >= 1 else " " + _de(z["staerke"] * 100, 0) + " %"}</span>'
            haupt = f'{mtext}: {hebel_text(z["effekt"])}'
        elif z["stufe"] == "ueber":
            marke, haupt = '<span class="wk-marke">Überversorgt</span>', "Kein zusätzlicher Nutzen – das Geld fehlt in anderen Feldern."
        else:
            marke = f'<span class="wk-marke">{"–" if z["e"] is None else "Knapp"}</span>'
            haupt = ("Kein Richtwert." if z["e"] is None else
                     f'Keine Wirkung – für den Bonus fehlen {_de(max(0.1, math.ceil((GRENZEN["bonus_ab"] * z["richt"] - z["anteil"]) * 10 - 1e-9) / 10))} Prozentpunkte.')
        regel = f'Bonus ab {_de(GRENZEN["bonus_ab"] * z["richt"])} %: {hebel_text(bonus)} · Malus unter {_de(GRENZEN["malus_ab"] * z["richt"])} %: {hebel_text(malus)}'
        zeilen.append(f'<tr data-wk="{kat}"><td>{esc(NAMEN[kat])}</td><td class="num">{_de(z["richt"])} %</td><td class="num wk-anteil">{_de(z["anteil"])} %</td>'
                      f'<td class="num wk-e">{"–" if z["e"] is None else _de(z["e"] * 100, 0) + " %"}</td><td>{marke}</td>'
                      f'<td class="wk-text"><span class="wk-haupt">{esc(haupt)}</span><small>{esc(regel)}</small></td></tr>')
    g = GRENZEN
    ausg_text = (f'Ausgewogener Etat – zusätzlicher Bonus: {hebel_text(AUSGEWOGEN[0])}.' if bew["ausgewogen"] else
                 f'Kein ausgewogener Etat: Liegen alle Politikfelder bei mindestens {_de(g["bonus_ab"] * 100, 0)} % ihres Richtwerts, gibt es zusätzlich '
                 f'{hebel_text(AUSGEWOGEN[0])}.')
    return (WK_CSS + f'<section class="ep-wk" id="ep-wk"><h2>{amt.ic("scale")} Auswirkungen der Verteilung</h2>'
            '<p class="az">Jedes Politikfeld hat einen <b>Richtwert</b> (die Vorgabe-Verteilung). '
            f'Ab {_de(g["bonus_ab"] * 100, 0)} % des Richtwerts gibt es einen <b>Bonus</b>, unter {_de(g["malus_ab"] * 100, 0)} % einen <b>Malus</b> '
            f'(voll ab {_de(g["malus_voll"] * 100, 0)} %). Über {_de(g["bonus_bis"] * 100, 0)} % lässt der Bonus nach, ab {_de(g["saettigung"] * 100, 0)} % '
            'bringt mehr Geld nichts mehr. Am besten fährt ein <b>ausgewogener Etat</b> mit leichten Schwerpunkten. '
            'Die Wirkungen gelten jeweils im nächsten gebuchten Monat.</p>'
            f'<div class="kennzahlen">{kz}</div><div class="wk-ausg{" ja" if bew["ausgewogen"] else ""}" id="wk-ausg"><span>{esc(ausg_text)}</span></div>'
            '<div class="ep-scroll"><table class="ep-tab ep-wk-tab"><thead><tr><th>Politikfeld</th><th class="num">Richtwert</th><th class="num">Anteil</th>'
            f'<th class="num">Erfüllung</th><th>Stand</th><th>Wirkung</th></tr></thead><tbody>{"".join(zeilen)}</tbody></table></div></section>')


ZUF_CSS = """<style>
.zf{margin:22px 0 8px}
.zf h2{display:flex;align-items:center;gap:8px}
.zf-kopf{display:flex;flex-wrap:wrap;gap:18px;align-items:center;padding:16px 18px;border:1px solid var(--linie);border-radius:12px;background:var(--hell)}
.zf-wert{font-size:44px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
.zf-wert small{font-size:16px;color:var(--grau);font-weight:600}
.zf-stufe{font-weight:700;font-size:16px}
.zf-meta{color:var(--grau);font-size:13px;line-height:1.6}
.zf-balken{position:relative;height:10px;border-radius:999px;background:#e6e8eb;overflow:hidden;min-width:80px}
.zf-balken>i{position:absolute;left:0;top:0;bottom:0;border-radius:999px;background:var(--zf,#1baf7a)}
.zf-gross{flex:1 1 220px}
.zf-gross .zf-balken{height:14px}
.zf-skala{position:relative;height:14px;font-size:11px;color:var(--grau);margin-top:4px}
.zf-skala span{position:absolute;transform:translateX(-50%)}.zf-skala span:first-child{transform:none}.zf-skala span:last-child{transform:translateX(-100%)}
.zf-tab tr.fokus td{background:var(--hell);font-weight:600}
.zf-tab{width:100%;border-collapse:collapse;font-size:14px;margin-top:10px}
.zf-tab td,.zf-tab th{padding:6px 8px;border-bottom:1px solid #eef0f2;text-align:left}
.zf-tab th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--grau);font-weight:600}
.zf-tab td.num,.zf-tab th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.zf-tab td.bar{width:40%}
.zf-s5{--zf:#13873f}.zf-s4{--zf:#1baf7a}.zf-s3{--zf:#eda100}.zf-s2{--zf:#eb6834}.zf-s1{--zf:#d13b3b}
.zf-s5 .zf-stufe,.zf-s4 .zf-stufe{color:#13663d}.zf-s3 .zf-stufe{color:#8a5d00}.zf-s2 .zf-stufe,.zf-s1 .zf-stufe{color:#a32020}
.zf-verlauf{display:flex;align-items:flex-end;gap:3px;height:40px}
.zf-verlauf i{display:block;width:10px;background:var(--grau);opacity:.55;border-radius:2px 2px 0 0}
@media (max-width:800px){.zf-wert{font-size:36px}.zf-tab td.bar{width:30%}.zf-tab th:nth-child(4),.zf-tab td:nth-child(4){display:none}}
</style>"""

ZUF_JS = r"""
(function(){
var D=JSON.parse(document.getElementById("ep-daten").textContent),Z=D.zuf;if(!Z||!D.wk)return;
function zahl(v,s){return v.toLocaleString("de-DE",{minimumFractionDigits:s||0,maximumFractionDigits:s||0})}
function stufe(w){for(var i=0;i<Z.stufen.length;i++)if(w>=Z.stufen[i][0])return [Z.stufen[i][1],Z.stufen.length-i];return ["",1]}
function effekt(w){var x=Z.wirkung;if(w>=x.bonus_ab)return x.bonus;if(w<x.malus_ab)return -Math.min(x.malus_max,(x.malus_ab-w)*x.malus_je_punkt);return 0}
function rechnen(){
 var a={};[].forEach.call(document.querySelectorAll("input[type=number][data-kat]"),function(f){a[f.dataset.kat]=parseFloat(String(f.value).replace(",","."))||0});
 D.kategorien.forEach(function(k){if(!(k.id in a))a[k.id]=k.anteil});
 var s=0,g=0;Object.keys(Z.gewichte).forEach(function(k){var gw=Z.gewichte[k],r=D.wk.richt[k]||0;if(!gw||r<0.05)return;
  var n=100*(1-Math.exp(-1.6*Math.max(0,a[k]/r)));s+=n*gw;g+=gw;
  var z=document.querySelector('[data-zf="'+k+'"]');if(z){z.querySelector("i").style.width=n.toFixed(1)+"%";z.querySelector(".zf-note").textContent=zahl(n)}});
 var ziel=g?s/g:0,neu=Z.alt===null?ziel:Z.alt+(ziel-Z.alt)*Z.traegheit,st=stufe(neu),e=effekt(neu);
 var k=document.getElementById("zf-kopf");k.className="zf-kopf zf-s"+st[1];
 document.getElementById("zf-wert").innerHTML=zahl(neu)+" <small>/ 100</small>";document.getElementById("zf-stufe").textContent=st[0];
 document.getElementById("zf-bar").style.width=neu.toFixed(1)+"%";document.getElementById("zf-ziel").textContent=zahl(ziel);
 document.getElementById("zf-eff").textContent=Math.abs(e)<0.0005?"keine":(e>0?"+":"−")+Math.abs(e).toLocaleString("de-DE",{maximumFractionDigits:2})+" %";
}
[].forEach.call(document.querySelectorAll("input[data-kat]"),function(f){f.addEventListener("input",rechnen)});
var n=document.getElementById("ep-normieren");if(n)n.addEventListener("click",rechnen);
rechnen()})();
"""


def _zf_klasse(wert):
    return "zf-s" + str(len(ZUF_STUFEN) - next(i for i, (g, _) in enumerate(ZUF_STUFEN) if wert >= g))


def zuf_balken(wert):
    return f'<div class="zf-balken {_zf_klasse(wert)}" role="img" aria-label="{_de(wert, 0)} von 100"><i style="width:{min(100, max(0, wert)):.1f}%"></i></div>'


def zuf_daten(z):
    return {"gewichte": ZUF_GEWICHTE, "alt": z["alt"], "stufen": ZUF_STUFEN, "wirkung": ZUF_WIRKUNG, "traegheit": ZUF_TRAEGHEIT}


def zuf_html(z, verlauf, reich=False, interaktiv=True):
    """Abschnitt „Bevölkerungszufriedenheit“ (ZUF_JS aktualisiert Wert, Stufe und Teilnoten live)."""
    e = z["effekt"]
    eff = "keine" if abs(e) < 0.0005 else _vz(e, "%")
    hist = ""
    if verlauf:
        hist = ('<div><div class="zf-meta">Verlauf</div><div class="zf-verlauf" title="Gebuchte Monate">'
                + "".join(f'<i style="height:{max(4, w * 0.4):.0f}px" title="{esc(sa._monatsname(p))}: {_de(w, 0)}"></i>' for p, w in verlauf) + '</div></div>')
    kopf = (f'<div class="zf-kopf {_zf_klasse(z["neu"])}" id="zf-kopf"><div><div class="zf-wert" id="zf-wert">{_de(z["neu"], 0)} <small>/ 100</small></div>'
            f'<div class="zf-stufe" id="zf-stufe">{esc(z["stufe"])}</div></div>'
            f'<div class="zf-gross"><div class="zf-balken"><i id="zf-bar" style="width:{z["neu"]:.1f}%"></i></div>'
            '<div class="zf-skala"><span style="left:0%">0</span><span style="left:40%">40</span><span style="left:55%">55</span><span style="left:70%">70</span><span style="left:85%">85</span><span style="left:100%">100</span></div>'
            f'<div class="zf-meta">Zielwert bei dieser Verteilung: <b id="zf-ziel">{_de(z["ziel"], 0)}</b> · '
            f'letzter Monat: <b>{"–" if z["alt"] is None else _de(z["alt"], 0)}</b> · Wirkung auf das Steueraufkommen: <b id="zf-eff">{eff}</b></div></div>{hist}</div>')
    teile = "".join(f'<tr data-zf="{kat}"><td>{esc(NAMEN[kat])}</td><td class="bar">{zuf_balken(n)}</td><td class="num zf-note">{_de(n, 0)}</td>'
                    f'<td class="num">{g} %</td></tr>' for kat, n, g in sorted(z["teile"], key=lambda t: -t[2]))
    w = ZUF_WIRKUNG
    return (ZUF_CSS + f'<section class="zf" id="zf"><h2>{amt.ic("users")} Bevölkerungszufriedenheit</h2>'
            f'<p class="az">Wie zufrieden ist die Bevölkerung {"der Freien Reichsgebiete mit dem Reich" if reich else "mit ihrer Regierung"}? '
            'Der Index (0–100) ergibt sich aus den Investitionen in die Politikfelder, die die Menschen im Alltag spüren – vor allem Arbeit und Soziales, '
            'Gesundheit, Bildung und Innere Sicherheit. Die Stimmung ändert sich nicht sofort: je gebuchtem Monat legt sie die Hälfte des Weges zum Zielwert zurück. '
            f'Ab {w["bonus_ab"]} Punkten steigt das Steueraufkommen um {_de(w["bonus"])} %, unter {w["malus_ab"]} Punkten sinkt es '
            f'(je Punkt {_de(w["malus_je_punkt"], 2)} %, höchstens {_de(w["malus_max"])} %).</p>' + kopf
            + f'<details class="sa-auf"><summary>{amt.ic("chart-column")}Zusammensetzung des Index</summary>'
              '<table class="zf-tab"><thead><tr><th>Politikfeld</th><th>Teilnote</th><th class="num">Note</th><th class="num">Gewicht</th></tr></thead>'
              f'<tbody>{teile}</tbody></table><p class="zf-meta">Teilnote: 80 bei genau dem Richtwert, mehr Geld bringt immer weniger zusätzliche Zufriedenheit. '
              'Verteidigung zählt nicht.</p></details></section>')


def zuf_tabelle(liste, ziel_liste, pfad, markiert=""):
    """Zufriedenheit aller Haushalte (öffentlich)."""
    zeilen = []
    for s, n in ziel_liste:
        if s == "reich":
            z, n = liste[0]["zufriedenheit_reich"], "Freie Reichsgebiete (Reich)"
        else:
            z = next(x for x in liste if "ts-" + x["staat"] == s)["zufriedenheit_land"]
        zeilen.append((z["neu"], f'<tr{" class=fokus" if s == markiert else ""}><td><a href="{pfad}?ziel={esc(s)}">{esc(n)}</a></td><td class="bar">{zuf_balken(z["neu"])}</td>'
                                 f'<td class="num">{_de(z["neu"], 0)}</td><td class="num">{esc(z["stufe"])}</td></tr>'))
    reichsweit = zuf_reichsweit(liste)
    return (f'<p class="zf-meta">Im ganzen Reich (nach Einwohnern gewichtet): <b>{_de(reichsweit, 0)} / 100 – {esc(zuf_stufe(reichsweit))}</b></p>'
            '<table class="zf-tab"><thead><tr><th>Haushalt</th><th>Zufriedenheit</th><th class="num">Index</th><th class="num">Stimmung</th></tr></thead><tbody>'
            + "".join(z for _, z in sorted(zeilen, key=lambda t: -t[0])) + '</tbody></table>')


def hf_tabelle(liste, ziel_liste, pfad, markiert=""):
    """Öffentlich: wer spart, wer entnimmt aus seiner Kasse (nur Prozente des eigenen Steueranteils)."""
    zeilen = []
    for s, n in ziel_liste:
        hf = haushaltsfuehrung(liste, s)
        art = f'{_de(hf)} % gespart' if hf > 0.05 else f'{_de(-hf)} % entnommen' if hf < -0.05 else "ausgeglichen"
        zeilen.append((hf, f'<tr{" class=fokus" if s == markiert else ""}><td><a href="{pfad}?ziel={esc(s)}">{esc(n)}</a></td>'
                           f'<td class="num">{esc(art)}</td></tr>'))
    return ('<p class="zf-meta">Rücklage in Prozent des eigenen Steueranteils: plus = gespart, minus = zusätzlich aus der Kasse ausgegeben.</p>'
            '<table class="zf-tab"><thead><tr><th>Haushalt</th><th class="num">Rücklage</th></tr></thead><tbody>'
            + "".join(z for _, z in sorted(zeilen, key=lambda t: -t[0])) + '</tbody></table>')


def regeln_html():
    """Übersicht aller Boni und Mali (öffentlich)."""
    g = GRENZEN
    zeilen = [(esc(NAMEN[kat]), esc(f'{btext}: {hebel_text(b)}'), esc(f'{mtext}: {hebel_text(m)}')) for kat, (b, btext, m, mtext) in WIRKUNGEN.items()]
    zeilen.append(("<b>Ausgewogener Etat</b>", esc(f'Alle Felder mindestens {_de(g["bonus_ab"] * 100, 0)} % des Richtwerts: {hebel_text(AUSGEWOGEN[0])}'), "–"))
    return (f'<p class="az">Bonus ab {_de(g["bonus_ab"] * 100, 0)} % des Richtwerts eines Politikfelds, Malus unter {_de(g["malus_ab"] * 100, 0)} % '
            f'(voll ab {_de(g["malus_voll"] * 100, 0)} %); über {_de(g["bonus_bis"] * 100, 0)} % lässt der Bonus nach. „Steueraufkommen“ betrifft die '
            'Einnahmen des ganzen Gebiets (auch die Abgabe an das Reich), „Rücklage“ den frei verfügbaren Teil der Kasse, „Einsatzbereitschaft“ das Militärgerät.</p>'
            + amt.tabelle(["Politikfeld", "Bonus", "Malus"], zeilen))


async def _seite(request, k, planung):
    """planung=False: Etatverteilung (geltender Etat im laufenden Monat, nur Ansicht); planung=True: Etat planen (Entwurf und Einreichen für den Folgemonat)."""
    import aufkommen
    import verteidigung
    con = request.app["db"]
    ab = monat_folgend() if planung else monat_heute()   # Monat, den die Seite zeigt
    liste = aufkommen.berechnen(con, periode=ab)
    ziel_liste = ziele(con, liste)
    eigene = [r["stelle"] for r in geld.regierte_staatskassen(con, k)]
    if planung:
        ziel_liste = [(s, n) for s, n in ziel_liste if darf_aendern(con, k, s)]
        if not ziel_liste:
            return sa.ant(request, k, "Etat planen", "sa-etatplanung",
                          f'<h1>{amt.ic("pencil")} Etat planen</h1><p class="az">Den Etat planen und einreichen dürfen der Landesherr eines Teilstaats sowie für das Reich '
                          f'Kanzler, Kaiser und Schatzamt-Leitung. Den geltenden Etat sehen Sie unter <a href="{PFAD}">Etatverteilung</a>.</p>')
    gueltig = {s for s, _ in ziel_liste}
    ziel = request.query.get("ziel", "")
    if ziel not in gueltig:
        ziel = next((s for s in eigene if s in gueltig), ziel_liste[0][0] if planung else "reich")
    name = dict(ziel_liste)[ziel]
    ent = entwurf(con, ziel) if planung else None
    eing = eingereicht(con, ziel) if planung else None
    if ent and not eing:   # mit dem Entwurf rechnen: Wirkung, Zufriedenheit und Beträge gelten für den Entwurf
        liste = aufkommen.berechnen(con, periode=ab, entwurf={ziel: {"anteile": json.loads(ent["anteile"]), "ruecklage": ent["ruecklage"]}})
    pk = await verteidigung.personalkosten(request.app, con)
    if ziel == "reich":
        gesamt = sum(x["reich"] for x in liste)
        pool = sum(x["pool_reich"] for x in liste)
        ruecklage = gesamt - pool
        betraege = {kat: sum(x["verteilung_reich"].get(kat, 0) for x in liste) for kat, _ in KATEGORIEN}
        fest_vorn = []
        vt_stelle = "verteidigung"
        vt_ih = 0
        grenze_hinweis = ""
        bew, richt, zuf = liste[0]["wirkung_reich"], liste[0]["richt_reich"], liste[0]["zufriedenheit_reich"]
        basis_ein, basis_rl = sum(x["summe_basis"] for x in liste if x["reichsgebiet"]), gesamt
    else:
        x = next(x for x in liste if "ts-" + x["staat"] == ziel)
        gesamt, pool, ruecklage = x["summe"], x["pool_land"], x["land"] - x["pool_land"]
        betraege = x["verteilung_land"]
        fest_vorn = [{"id": "abgabe", "name": "Abgabe an das Reich", "betrag": x["reich"], "farbe": "#3a3a3a", "schraffur": False}]
        grenze_hinweis = (f'Die Abgabe an das Reich ist auf {_de(x["quote"])} % des Etats begrenzt. Ohne diese Obergrenze würde dieser Teilstaat '
                          f'{_de(x["quote_theorie"])} % abgeben ({mark(x["reich_theorie"])} im Monat, {mark(x["reich_theorie"] - x["reich"])} mehr).'
                          if x["quote_theorie"] > x["quote"] + 0.05 else "")
        vt_stelle = "vt-" + x["staat"]
        vt_ih = verteidigung.kennzahlen(con, vt_stelle)["instandhaltung"]
        bew, richt, basis_ein, basis_rl = x["wirkung_land"], x["richt_land"], x["summe_basis"], x["land"]
        zuf = x["zufriedenheit_land"]
    if ziel == "reich":
        kasse_rl, rl_satz, frei, deckel = geld.sonder(con, "reichskasse"), liste[0]["rl_satz_reich"], liste[0]["frei_reich_kasse"], liste[0]["gedeckelt_reich"]
    else:
        kasse_rl, rl_satz, frei, deckel = x["kasse"], x["rl_satz_land"], x["frei_land"], x["gedeckelt_land"]
    rl_w = bew["summe"]["ruecklage"]
    gebunden = kasse_gebunden(con, kasse_rl, ziel == "reich")
    kassen_name = "Reichskasse" if ziel == "reich" else "Staatskasse"
    anteile = runden100(json.loads(ent["anteile"]) if ent and not eing else aktuelle(con, ziel, liste, ab))
    berechtigt = darf_aendern(con, k, ziel)
    darf = planung and berechtigt and not eing
    in_per = in_aenderungsperiode()
    von, bis = aenderungsperiode()
    n_pers, kosten = (pk or {}).get(vt_stelle, (0, 0))
    vt_min = kosten + vt_ih if pk is not None else 0
    kat_daten = [{"id": kat, "name": NAMEN[kat], "anteil": anteile[kat], "farbe": PALETTE[i % len(PALETTE)], "schraffur": i >= len(PALETTE)}
                 for i, (kat, _) in enumerate(KATEGORIEN)]
    fest_hinten = [{"id": "ruecklage", "name": "Rücklage der Staatskasse" if ziel != "reich" else "Rücklage der Reichskasse",
                    "betrag": max(0, ruecklage), "farbe": "#c4c6cb", "schraffur": False}]
    daten = {"gesamt": gesamt, "pool": pool, "vt_min": vt_min, "kategorien": kat_daten, "fest_vorn": fest_vorn, "fest_hinten": fest_hinten, "farben": PALETTE,
             "wk": wirkung_daten(richt, basis_ein, basis_rl), "zuf": zuf_daten(zuf),
             "rl": {"basis": basis_rl, "w": rl_w, "frei": frei, "kasse": kassen_name}}
    c = amt.csrf_feld(request)
    zeilen = []
    for f in fest_vorn:
        zeilen.append(f'<tr class="ep-fest" data-zeile="{f["id"]}"><td><span class="ep-farbe" style="background:{f["farbe"]}"></span>{esc(f["name"])}</td>'
                      f'<td class="num">–</td><td class="num ep-anteil-gesamt">{_de(f["betrag"] / gesamt * 100 if gesamt else 0)} %</td>'
                      f'<td class="num"><span title="{mark(f["betrag"])}">{geld.mark_kurz(f["betrag"])}</span></td></tr>')
    for i, kd in enumerate(kat_daten):
        kat = kd["id"]
        farbe = f'<span class="ep-farbe{" schraffur" if kd["schraffur"] else ""}" style="background-color:{kd["farbe"]}"></span>'
        wert = f'{anteile[kat]:.1f}'
        if darf:
            anteil_zelle = (f'<input type="range" id="ep-r-{kat}" data-kat="{kat}" min="0" max="100" step="0.1" value="{wert}" aria-label="{esc(NAMEN[kat])} Regler"> '
                            f'<input type="number" id="ep-n-{kat}" name="k_{kat}" data-kat="{kat}" min="0" max="100" step="0.1" value="{wert}" aria-label="{esc(NAMEN[kat])} in Prozent"> %')
        else:
            anteil_zelle = f'{_de(anteile[kat])} %'
        zeilen.append(f'<tr data-zeile="{kat}"><td>{farbe}{esc(NAMEN[kat])}</td><td class="num">{anteil_zelle}</td>'
                      f'<td class="num ep-anteil-gesamt">{_de(betraege[kat] / gesamt * 100 if gesamt else 0)} %</td>'
                      f'<td class="num"><span class="ep-betrag" title="{mark(betraege[kat])}">{geld.mark_kurz(betraege[kat])}</span></td></tr>')
    for f in fest_hinten:
        zeilen.append(f'<tr class="ep-fest" data-zeile="{f["id"]}"><td><span class="ep-farbe" style="background:{f["farbe"]}"></span>{esc(f["name"])}</td>'
                      f'<td class="num">–</td><td class="num ep-anteil-gesamt">{_de(f["betrag"] / gesamt * 100 if gesamt else 0)} %</td>'
                      f'<td class="num"><span class="ep-betrag" title="{mark(f["betrag"])}">{geld.mark_kurz(f["betrag"])}</span></td></tr>')
    zeilen.append(f'<tr class="ep-fest ep-entnahme" id="ep-entnahme-zeile"{"" if ruecklage < 0 else " hidden"}><td><span class="ep-farbe ep-farbe-leer"></span>'
                  f'Entnahme aus der {kassen_name}</td><td class="num">–</td><td class="num" id="ep-entnahme-pz">{_de(-ruecklage / gesamt * 100 if gesamt else 0)} %</td>'
                  f'<td class="num"><span id="ep-entnahme-betrag">{geld.mark_kurz(max(0, -ruecklage))}</span></td></tr>')
    tabelle = ('<table class="ep-tab"><thead><tr><th>Kategorie</th><th class="num">Anteil am Ausgabenbudget</th><th class="num">Anteil am Etat</th>'
               f'<th class="num">Betrag / Monat</th></tr></thead><tbody>{"".join(zeilen)}</tbody></table>')
    rl_eff = (basis_rl - pool) / basis_rl * 100 if basis_rl else 0
    rl_wert = rl_satz if rl_satz is not None else liste[0]["rl_vorgabe"]
    kasse_info = (f'<div class="ep-kasse">{amt.ic("landmark")}<span>{esc(kassen_name)}: Kontostand <b>{esc(mark(kasse_rl["saldo"] if kasse_rl else 0))}</b>'
                  f' · im Monat gebunden {esc(mark(gebunden))} · <b>frei verfügbar {esc(mark(frei))}</b></span></div>')
    if darf:
        rl_feld = (f'<input type="range" id="ep-rl-r" min="-100" max="100" step="0.5" value="{max(-100, min(100, rl_wert)):.1f}" aria-label="Rücklage Regler"> '
                   f'<input type="number" id="ep-rl" name="ruecklage" min="-1000" max="100" step="0.1" value="{rl_wert:.1f}" aria-label="Rücklage in Prozent"> %')
    else:
        rl_feld = f'<b>{_vz(rl_wert, "%")}</b>'
    rl_block = (f'<div class="ep-rl"><div class="ep-rl-kopf"><span class="ep-rl-titel">Rücklage</span><span class="ep-rl-feld">{rl_feld}</span></div>'
                f'<p class="ep-rl-hilfe">In Prozent des eigenen Steueranteils ({esc(mark(basis_rl))}). <b>Plus</b> = sparen: das Geld bleibt in der {esc(kassen_name)}. '
                f'<b>Minus</b> = entnehmen: zusätzlich zum Monatsetat fließen freie Mittel der {esc(kassen_name)} in die Politikfelder.'
                + (f' Die Etatwirkung verschiebt die Rücklage um {_vz(rl_w, "Pp")}.' if rl_w else "") + '</p>'
                f'<p class="ep-rl-info" id="ep-rl-info">{_rl_text(rl_eff, basis_rl - pool, kassen_name, deckel)}</p>{kasse_info}</div>')
    if darf:
        form_in = (f'<form method="post" action="{PFAD_PLAN}entwurf" id="ep-form">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">{rl_block}{tabelle}'
                   '<div class="ep-summe" id="ep-summe"><span></span></div>'
                   f'<div class="warnung ep-hinweis" id="ep-min" style="display:none">{amt.ic("triangle-alert")} Dieser Verteidigungsanteil deckt nicht einmal die Gehälter und die '
                   f'Instandhaltung des Militärs ({mark(vt_min)} im Monat). Die Gehälter werden dann einbehalten, die Einsatzbereitschaft sinkt.</div>'
                   f'<div class="aktionen"><button class="btn zweit" type="submit" id="ep-speichern">{amt.ic("check")}Entwurf speichern</button>'
                   f'<button class="btn zweit" type="button" id="ep-normieren">Auf 100 % bringen</button>'
                   f'<button class="btn zweit" type="button" id="ep-vorgabe" data-richt="{esc(json.dumps(runden100(richt)))}" data-rl="{liste[0]["rl_vorgabe"]:.1f}">Auf Vorgabe setzen</button></div></form>')
        if in_per and ent:
            form_in += (f'<form method="post" action="{PFAD_PLAN}einreichen" id="ep-einreichen-form" class="ep-einreichen">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                        f'<p><b>Etat einreichen</b> – schickt den zuletzt gespeicherten Entwurf (vom {esc(amt._zeit(ent["zeit"]))}) endgültig ab. Er gilt dann ab '
                        f'<b>{esc(sa._monatsname(ab))}</b> und ist bis zur nächsten Änderungsperiode nicht mehr änderbar.</p>'
                        f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("send")}Etat einreichen</button></div></form>')
        elif in_per:
            form_in += f'<p class="ep-einreichen">Zum Einreichen zuerst einen Entwurf speichern.</p>'
        else:
            form_in += (f'<p class="ep-einreichen">{amt.ic("lock")} Einreichen ist nur in der Änderungsperiode möglich: <b>{esc(_tag(von))} bis {esc(_tag(bis))}</b>. '
                        'Bis dahin lässt sich der Entwurf beliebig oft speichern und ändern.</p>')
    else:
        form_in = rl_block + tabelle
    teile = []
    if planung:
        teile.append(f'{amt.ic("clock")} Planung des Etats für <b>{esc(sa._monatsname(ab))}</b>. Änderungsperiode: die letzten sieben Tage des Monats '
                     f'({esc(_tag(von))} bis {esc(_tag(bis))}); '
                     + ('<b>sie läuft jetzt</b>.' if in_per else 'sie beginnt am ' + esc(_tag(von)) + '.'))
        if eing:
            teile.append(f'{amt.ic("lock")} <b>Eingereicht</b> am {esc(amt._zeit(eing["zeit"]))}: Dieser Etat gilt ab {esc(sa._monatsname(ab))}. '
                         f'Bis zur nächsten Änderungsperiode lässt er sich nicht mehr ändern.')
        elif ent:
            teile.append(f'Entwurf gespeichert am {esc(amt._zeit(ent["zeit"]))} ({esc(ent["autor_name"])}) – <b>noch nicht eingereicht</b>, ohne Wirkung. '
                         'Die Tabelle zeigt den Entwurf.')
        else:
            teile.append('Noch kein Entwurf gespeichert; die Tabelle zeigt den bisher geltenden Etat. Wird in der Änderungsperiode nichts eingereicht, bleibt es dabei.')
    else:
        vm = vorgemerkt(con, ziel)
        teile.append(f'Der geltende Etat im {esc(sa._monatsname(ab))}. Änderungen werden in der <b>Änderungsperiode</b> (letzte sieben Tage des Monats, '
                     f'{esc(_tag(von))} bis {esc(_tag(bis))}) für den Folgemonat eingereicht.')
        if vm:
            teile.append(f'Für <b>{esc(sa._monatsname(vm["ab"]))}</b> ist ein neuer Etat eingereicht ({esc(amt._zeit(vm["zeit"]))}); bis dahin gilt dieser Etat.')
        if berechtigt:
            teile.append(f'<a class="btn zweit" href="{PFAD_PLAN}?ziel={esc(ziel)}">{amt.ic("pencil")}Etat planen</a>')
        else:
            teile.append('Nur Ansicht – ändern darf den Etat ' + ("das Reich (Kanzler, Kaiser, Schatzamt-Leitung)." if ziel == "reich" else "der Landesherr dieses Teilstaats."))
    if grenze_hinweis:
        teile.append(amt.ic("scale") + " " + grenze_hinweis)
    rechte = "".join(f'<p class="sa-hinweis">{t}</p>' for t in teile)
    gewaehlt = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(n)}{" (Ihr Teilstaat)" if s in eigene else ""}</option>' for s, n in ziel_liste)
    erkl = ('<div class="sa-erkl"><b>Wie ist der Etat aufgebaut?</b><ol>'
            + ('<li>Der Etat des Reiches ist sein Anteil an allen Steuern: die <b>Abgaben der Teilstaaten</b> und das gesamte Aufkommen der Freien Reichsgebiete.</li>'
               if ziel == "reich" else
               '<li>Der Etat ist das Steueraufkommen des Teilstaats im Monat. Ein Teil davon ist die <b>Abgabe an das Reich</b>; sie richtet sich nach Bevölkerung, '
               'Einkommen und Fläche und lässt sich <b>nicht beeinflussen</b>.</li>')
            + '<li>Vom eigenen Anteil bleibt die <b>Rücklage</b> in der Kasse; der Rest ist das <b>Ausgabenbudget</b>. Die Rücklage ist frei wählbar: '
            '<b>sparen</b> (plus) oder <b>entnehmen</b> (minus) – dann fließen zusätzlich freie Mittel der Kasse in die Politikfelder.</li>'
            '<li>Das Ausgabenbudget verteilt ' + ("das Reich" if ziel == "reich" else "der Teilstaat") + ' in Prozent auf die elf Kategorien. '
            '<b>Verteidigung ist echtes Geld</b>: dieser Anteil fließt jeden Monat in die '
            + ("Reichsverteidigungskasse (Führungsstab)" if ziel == "reich" else "Verteidigungskasse (Gehälter des Militärs, Instandhaltung und Kauf von Gerät)")
            + '. Die übrigen Kategorien sind Ausgaben für die Bevölkerung.</li></ol></div>')
    kz = [("Etat im Monat", mark(gesamt), ""), ("Ausgabenbudget", mark(pool), "ep-kz-pool"),
          ("Rücklage" if ruecklage >= 0 else f"Entnahme aus der {kassen_name}", mark(abs(ruecklage)), "ep-kz-rl"),
          ("Verteidigung", mark(betraege["verteidigung"]), "")]
    # Vergleich aller Haushalte
    kopf = "".join(f'<th title="{esc(NAMEN[kat])}">{esc(NAMEN[kat][:11])}</th>' for kat, _ in KATEGORIEN)
    vz = []
    for s, n in ziel_liste:
        if s == "reich":
            ver = {kat: sum(x["verteilung_reich"].get(kat, 0) for x in liste) for kat, _ in KATEGORIEN}
            pl = sum(x["pool_reich"] for x in liste)
        else:
            x2 = next(x for x in liste if "ts-" + x["staat"] == s)
            ver, pl = x2["verteilung_land"], x2["pool_land"]
        bw = liste[0]["wirkung_reich"] if s == "reich" else x2["wirkung_land"]
        vz.append(f'<tr><td><a href="{PFAD}?ziel={esc(s)}">{esc(n)}</a></td><td>{_vz(round(haushaltsfuehrung(liste, s), 1), "%")}</td>'
                  + "".join(f'<td>{_de(ver[kat] / pl * 100 if pl else 0)}</td>' for kat, _ in KATEGORIEN)
                  + f'<td>{bw["boni"]} / {bw["mali"]}</td><td>{_vz(bw["summe"]["einnahmen"], "%")}</td>'
                  + f'<td>{_de((liste[0]["zufriedenheit_reich"] if s == "reich" else x2["zufriedenheit_land"])["neu"], 0)}</td></tr>')
    verlauf = con.execute("SELECT * FROM ep_log WHERE schl=? ORDER BY id DESC LIMIT 15", (ziel,)).fetchall()
    titel = "Etat planen" if planung else "Etatverteilung"
    inhalt = (CSS + f'<h1>{amt.ic("pencil" if planung else "chart-pie")} {titel} · {esc(name)}</h1>{amt.meldung(request)}'
              f'<p class="az">Wie viel vom Ausgabenbudget fließt in welches Politikfeld? Das Tortendiagramm zeigt den gesamten Monatsetat im {esc(sa._monatsname(ab))}.</p>'
              f'<form class="sa-leiste" method="get"><div><label for="zl">Haushalt</label><select id="zl" name="ziel" onchange="this.form.submit()">{gewaehlt}</select></div>'
              f'<noscript><button class="btn zweit" type="submit">Anzeigen</button></noscript></form>'
              f'<div class="kennzahlen">{"".join(f'<div><b{f" id={i}" if i else ""}>{esc(v)}</b><span{f" id={i}-t" if i else ""}>{esc(t)}</span></div>' for t, v, i in kz)}</div>'
              + rechte + erkl
              + f'<div class="ep-raster"><div class="ep-torte" id="ep-torte"><svg viewBox="0 0 200 200" role="img" aria-label="Tortendiagramm des Etats {esc(name)}"></svg>'
                '<div class="ep-tipp" id="ep-tipp"></div></div><div>' + form_in + '</div></div>'
              + zuf_html(zuf, zuf_verlauf(con, ziel), ziel == "reich")
              + wirkung_html(bew, basis_ein, basis_rl, ziel == "reich")
              + f'<script type="application/json" id="ep-daten">{json.dumps(daten, ensure_ascii=False).replace("</", "<\\/")}</script><script>{JS}</script><script>{WK_JS}</script><script>{ZUF_JS}</script>' + (f'<script>{PLAN_JS}</script>' if darf else "")
              + ("" if planung else f'<details class="sa-auf"><summary>{amt.ic("chart-column")}Vergleich aller Haushalte (Anteile am Ausgabenbudget in %)</summary><div class="ep-scroll">'
                f'<table class="liste ep-vergleich"><thead><tr><th>Haushalt</th><th title="Rücklage in % des eigenen Steueranteils (− = Entnahme aus der Kasse)">Rücklage</th>{kopf}<th title="Boni / Mali">Boni/Mali</th><th title="Wirkung auf das Steueraufkommen">Aufkommen</th><th title="Bevölkerungszufriedenheit">Zufr.</th></tr></thead><tbody>{"".join(vz)}</tbody></table></div></details>')
              + f'<details class="sa-auf"><summary>{amt.ic("clock")}Änderungen ({len(verlauf)})</summary>'
              + amt.tabelle(["Zeit", "Durch", "Änderung"], [(amt._zeit(v["zeit"]), esc(v["autor_name"]), esc(v["text"])) for v in verlauf], "Noch keine Änderungen.") + '</details>')
    return sa.ant(request, k, titel, "sa-etatplanung" if planung else "sa-etatverteilung", inhalt)


@sa.seite("staat")
async def seite(request, k):
    return await _seite(request, k, False)


@sa.seite("staat")
async def planung_seite(request, k):
    return await _seite(request, k, True)


# ---------------------------------------------------------------- Öffentliche Etatübersicht (alle angemeldeten Nutzer, nur Prozente)

PFAD_OEFF = sa.PFAD + "etatuebersicht/"


def _torte_daten(x, liste, ziel):
    """Anteile (Promille-Einheiten statt Kronen) für das öffentliche Tortendiagramm."""
    if ziel == "reich":
        gesamt = sum(y["reich"] for y in liste)
        pool = sum(y["pool_reich"] for y in liste)
        ver = {kat: sum(y["verteilung_reich"].get(kat, 0) for y in liste) for kat, _ in KATEGORIEN}
        vorn, ruecklage = [], gesamt - pool
    else:
        gesamt, pool, ver = x["summe"], x["pool_land"], x["verteilung_land"]
        vorn, ruecklage = [("abgabe", "Abgabe an das Reich", x["reich"], "#3a3a3a")], x["land"] - x["pool_land"]
    n = lambda h: int(round(h / gesamt * 1_000_000)) if gesamt else 0
    kat = [{"id": k, "name": NAMEN[k], "anteil": ver[k] / pool * 100 if pool else 0, "farbe": PALETTE[i % len(PALETTE)], "schraffur": i >= len(PALETTE)}
           for i, (k, _) in enumerate(KATEGORIEN)]
    return {"gesamt": 1_000_000, "pool": n(pool), "vt_min": 0, "kategorien": kat, "nur_prozent": True, "farben": PALETTE,
            "fest_vorn": [{"id": i, "name": nm, "betrag": n(b), "farbe": f, "schraffur": False} for i, nm, b, f in vorn],
            "fest_hinten": [{"id": "ruecklage", "name": "Rücklage", "betrag": n(max(0, ruecklage)), "farbe": "#c4c6cb", "schraffur": False}]}


@sa.seite()
async def oeffentlich(request, k):
    import aufkommen
    con = request.app["db"]
    liste = aufkommen.berechnen(con, periode=monat_heute())
    ziel_liste = ziele(con, liste)
    gueltig = dict(ziel_liste)
    ziel = request.query.get("ziel", "")
    if ziel not in gueltig:
        eigene = [r["stelle"] for r in geld.regierte_staatskassen(con, k)]
        ziel = next((s for s in eigene if s in gueltig), "reich")
    x = None if ziel == "reich" else next(y for y in liste if "ts-" + y["staat"] == ziel)
    d = _torte_daten(x, liste, ziel)
    bew = liste[0]["wirkung_reich"] if ziel == "reich" else x["wirkung_land"]
    zuf = liste[0]["zufriedenheit_reich"] if ziel == "reich" else x["zufriedenheit_land"]
    zeilen = []
    for f in d["fest_vorn"]:
        zeilen.append(f'<tr class="ep-fest" data-zeile="{f["id"]}"><td><span class="ep-farbe" style="background:{f["farbe"]}"></span>{esc(f["name"])}</td>'
                      f'<td class="num">{_de(f["betrag"] / 10000)} %</td></tr>')
    stufen = {z["kat"]: z for z in bew["zeilen"]}
    for kd in d["kategorien"]:
        z = stufen[kd["id"]]
        marke = ('<span class="wk-marke bonus">Bonus</span>' if z["stufe"] == "bonus" and z["staerke"] > 0 else
                 '<span class="wk-marke malus">Malus</span>' if z["stufe"] == "malus" else "")
        zeilen.append(f'<tr data-zeile="{kd["id"]}"><td><span class="ep-farbe{" schraffur" if kd["schraffur"] else ""}" style="background-color:{kd["farbe"]}"></span>'
                      f'{esc(kd["name"])} {marke}</td><td class="num">{_de(kd["anteil"] * d["pool"] / 1_000_000)} %</td></tr>')
    for f in d["fest_hinten"]:
        zeilen.append(f'<tr class="ep-fest" data-zeile="{f["id"]}"><td><span class="ep-farbe" style="background:{f["farbe"]}"></span>{esc(f["name"])}</td>'
                      f'<td class="num">{_de(f["betrag"] / 10000)} %</td></tr>')
    auswahl = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(n)}</option>' for s, n in ziel_liste)
    e = bew["summe"]["einnahmen"]
    hf = haushaltsfuehrung(liste, ziel)
    kname = "Reichskasse" if ziel == "reich" else "Staatskasse"
    hf_text = (f'spart <b>{_de(hf)} %</b> des eigenen Steueranteils in die {kname}' if hf > 0.05 else
               f'entnimmt zusätzlich <b>{_de(-hf)} %</b> aus der {kname}' if hf < -0.05 else 'gibt den ganzen Steueranteil aus')
    lage = (f'<div class="wk-ausg ep-hf">{amt.ic("landmark")} <span><b>Haushaltsführung:</b> {"Das Reich" if ziel == "reich" else esc(gueltig[ziel])} {hf_text}.</span></div>'
            f'<div class="wk-ausg{" ja" if bew["ausgewogen"] else ""}"><b>{"Ausgewogener Etat" if bew["ausgewogen"] else "Etat mit Schwerpunkten"}</b> · '
            f'{bew["boni"]} Boni · {bew["mali"]} Mali · Wirkung auf das Steueraufkommen: '
            f'<b class="{"wk-plus" if e > 0 else "wk-minus" if e < 0 else ""}">{_vz(e, "%")}</b></div>'
            f'<div class="zf-kopf {_zf_klasse(zuf["neu"])}" style="margin:10px 0"><div><div class="zf-wert">{_de(zuf["neu"], 0)} <small>/ 100</small></div>'
            f'<div class="zf-stufe">{esc(zuf["stufe"])}</div></div><div class="zf-gross"><div class="zf-meta">Bevölkerungszufriedenheit'
            f'{" der Freien Reichsgebiete" if ziel == "reich" else ""}</div>{zuf_balken(zuf["neu"])}'
            '<div class="zf-skala"><span style="left:0%">0</span><span style="left:40%">40</span><span style="left:55%">55</span><span style="left:70%">70</span><span style="left:85%">85</span><span style="left:100%">100</span></div></div></div>')
    staatl = (f'<p class="sa-hinweis"><a href="{PFAD}?ziel={esc(ziel)}">Zur Etatverteilung mit Beträgen und Einstellungen</a></p>'
              if sa.hat_kassen(con, k) else "")
    inhalt = (CSS + WK_CSS + ZUF_CSS + f'<h1>{amt.ic("chart-pie")} Etatübersicht</h1>'
              f'<p class="az">Wofür geben Reich und Teilstaaten ihr Geld aus? Anteile am monatlichen Etat im {esc(sa._monatsname(monat_heute()))}.</p>'
              f'<form class="sa-leiste" method="get"><div><label for="zl">Haushalt</label><select id="zl" name="ziel" onchange="this.form.submit()">{auswahl}</select></div>'
              '<noscript><button class="btn zweit" type="submit">Anzeigen</button></noscript></form>' + lage
              + f'<div class="ep-raster"><div class="ep-torte" id="ep-torte"><svg viewBox="0 0 200 200" role="img" aria-label="Tortendiagramm des Etats {esc(gueltig[ziel])}"></svg>'
                '<div class="ep-tipp" id="ep-tipp"></div></div><div>'
                f'<table class="ep-tab"><thead><tr><th>Posten</th><th class="num">Anteil am Etat</th></tr></thead><tbody>{"".join(zeilen)}</tbody></table></div></div>'
              + f'<script type="application/json" id="ep-daten">{json.dumps(d, ensure_ascii=False).replace("</", "<\\/")}</script><script>{JS}</script>'
              + staatl
              + f'<h2>{amt.ic("landmark")} Haushaltsführung</h2>' + hf_tabelle(liste, ziel_liste, PFAD_OEFF, ziel)
              + f'<h2>{amt.ic("users")} Bevölkerungszufriedenheit im Reich</h2>' + zuf_tabelle(liste, ziel_liste, PFAD_OEFF, ziel)
              + f'<details class="sa-auf"><summary>{amt.ic("scale")}Wie wirkt sich die Verteilung aus?</summary>{regeln_html()}'
                '<p class="az"><b>Bevölkerungszufriedenheit:</b> Index 0–100 aus den Investitionen (Gewichte: '
              + ", ".join(f'{NAMEN[k]} {g} %' for k, g in sorted(ZUF_GEWICHTE.items(), key=lambda t: -t[1]) if g)
              + f'). Ab {ZUF_WIRKUNG["bonus_ab"]} Punkten +{_de(ZUF_WIRKUNG["bonus"])} % Steueraufkommen, unter {ZUF_WIRKUNG["malus_ab"]} Punkten bis zu '
                f'−{_de(ZUF_WIRKUNG["malus_max"])} %. Die Stimmung folgt einer neuen Verteilung nur allmählich.</p></details>')
    return sa.ant(request, k, "Etatübersicht", "sa-etatuebersicht", inhalt)


def _lesen(form):
    werte = {}
    for kat, _ in KATEGORIEN:
        roh = str(form.get("k_" + kat, "")).replace(",", ".").strip()
        try:
            v = float(roh)
        except ValueError:
            return None
        if not 0 <= v <= 100:
            return None
        werte[kat] = v
    return werte if abs(sum(werte.values()) - 100.0) <= 0.05 else None


def _rl_lesen(form):
    """Rücklagensatz aus dem Formular: Zahl −1000 … 100 oder None, wenn ungültig."""
    try:
        v = float(str(form.get("ruecklage", "")).replace(",", ".").strip())
    except ValueError:
        return None
    return v if -1000 <= v <= 100 else None


def _zugriff(con, k, ziel):
    if not k:
        raise web.HTTPFound("/anmelden/")
    if not (ziel == "reich" or ziel.startswith("ts-")) or not darf_aendern(con, k, ziel):
        raise web.HTTPForbidden(text="Den Etat dieses Haushalts dürfen Sie nicht planen.")


async def entwurf_post(request):
    k = await anmeldung.konto(request)
    form = await sa.formular(request)
    con = request.app["db"]
    ziel = str(form.get("ziel", ""))
    _zugriff(con, k, ziel)
    if eingereicht(con, ziel):
        sa.weiter(f"{PFAD_PLAN}?ziel={ziel}", "Der Etat ist schon eingereicht und bis zur nächsten Änderungsperiode nicht mehr änderbar.", True)
    werte = _lesen(form)
    if werte is None:
        sa.weiter(f"{PFAD_PLAN}?ziel={ziel}", "Bitte für alle elf Kategorien Prozentwerte angeben, die zusammen 100 % ergeben.", True)
    rl = _rl_lesen(form)
    if rl is None:
        sa.weiter(f"{PFAD_PLAN}?ziel={ziel}", "Bitte für die Rücklage einen Prozentwert zwischen −1000 und 100 angeben.", True)
    entwurf_speichern(con, ziel, werte, rl, k)
    con.commit()
    sa.weiter(f"{PFAD_PLAN}?ziel={ziel}", "Entwurf gespeichert. Er hat noch keine Wirkung – eingereicht wird in der Änderungsperiode.")


async def einreichen_post(request):
    import aufkommen
    k = await anmeldung.konto(request)
    form = await sa.formular(request)
    con = request.app["db"]
    ziel = str(form.get("ziel", ""))
    _zugriff(con, k, ziel)
    ab = monat_folgend()
    liste = aufkommen.berechnen(con, periode=ab)
    rl_alt = liste[0]["rl_satz_reich"] if ziel == "reich" else next((x["rl_satz_land"] for x in liste if "ts-" + x["staat"] == ziel), None)
    fehler = einreichen(con, ziel, k, runden100(aktuelle(con, ziel, liste, ab)), liste[0]["rl_vorgabe"] if rl_alt is None else rl_alt)
    if fehler:
        sa.weiter(f"{PFAD_PLAN}?ziel={ziel}", fehler, True)
    con.commit()
    sa.weiter(f"{PFAD_PLAN}?ziel={ziel}", f"Etat eingereicht; er gilt ab {sa._monatsname(ab)}.")


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get(PFAD, seite)
    app.router.add_get(PFAD_PLAN, planung_seite)
    app.router.add_get(PFAD_OEFF, oeffentlich)
    app.router.add_post(PFAD_PLAN + "entwurf", entwurf_post)
    app.router.add_post(PFAD_PLAN + "einreichen", einreichen_post)
