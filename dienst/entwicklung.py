"""Entwicklung: langfristige Wirkung der Investitionen (Etatverteilung) auf Bevölkerung, Wirtschaft und Stimmung – modular.

Aufbau
- Jeder Haushalt (Teilstaat „ts-<sid>“, das Reich „reich“ = Freie Reichsgebiete) hat einen Zustand aus Indikatoren (ep_zustand, je gebuchtem Monat).
- Ein MODUL (Eintrag in MODULE) gehört zu einem oder mehreren Politikfeldern und besteht aus
    · Indikatoren: Zielwert aus der Erfüllung E = Anteil ÷ Richtwert der Politikfelder, mit Trägheit (der Wert nähert sich dem Ziel nur langsam);
    · Wirkungen: aus den (neuen) Indikatorwerten Effekte auf drei Hebel:
        bev_pp  = Bevölkerungswachstum in Prozentpunkten je Monat (wirkt kumulativ auf die Einwohnerzahl, Faktor bev_faktor),
        kopf_pct = BIP pro Kopf in Prozent (Niveaueffekt, Faktor kopf_faktor),
        zuf_pt  = Punkte auf den Zufriedenheitsindex (etatplan.zufriedenheit, Parameter extra),
        ruestung_pct = Preis von Militärgütern in % (Forschung, Lieferketten; verteidigung.beschaffen über ruestung_faktor).
  Ein neues Modul = ein neuer Eintrag in MODULE (Indikatoren und eine Funktion wirkungen(z) → Liste von Effekten); sonst nichts.
- Neutral: Bei der Vorgabe-Verteilung (E = 1) sind alle Indikatoren auf ihrem Startwert und alle Effekte 0 – die Wirtschaft ändert sich erst, wenn ein Haushalt
  von der Vorgabe abweicht. Faktoren sind begrenzt (BEV_GRENZEN, KOPF_GRENZEN).
- aufkommen.berechnen rechnet zweimal: erst ohne Entwicklung (Pläne, Richtwerte), dann mit den hier berechneten Faktoren (Einwohner × bev_faktor,
  BIP × bev_faktor × kopf_faktor, Zufriedenheit + zuf_pt). Gespeichert wird beim Buchen des Haushaltsmonats (speichern). Der Zustand „vor dem Monat“
  ist der zuletzt gespeicherte Stand eines früheren Monats – Neuberechnungen desselben Monats ändern also nichts doppelt.
Seite: /schatzamt/entwicklung/ (Reiter „Entwicklung“); öffentlich: Tabelle in der Etatübersicht.
"""
import math
import sqlite3

import amt
import geld
import schatzamt as sa

esc = amt.esc
PFAD = sa.PFAD + "entwicklung/"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ep_zustand (periode TEXT NOT NULL, schl TEXT NOT NULL, schluessel TEXT NOT NULL, wert REAL NOT NULL,
    PRIMARY KEY (periode, schl, schluessel));
"""

BEV_GRENZEN = (0.80, 1.40)      # Einwohner im Vergleich zur Karte
KOPF_GRENZEN = (-15.0, 12.0)    # BIP pro Kopf in % gegenüber der Karte
RUESTUNG_GRENZEN = (-30.0, 45.0)   # Preis von Militärgütern in % gegenüber dem Katalogpreis
NEUTRAL = 100.0 * (1 - math.exp(-1.6))   # Teilnote bei Erfüllung 1,0 (≈ 79,8)


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def _t(E, kat):
    import etatplan
    return etatplan.zuf_teilnote(E.get(kat, 1.0))


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _de(x, st=1):
    import etatplan
    return etatplan._de(x, st)


def _vz(x, einheit="%", st=1):
    return f'{"+" if x > 0.05 else "−" if x < -0.05 else "±"}{_de(abs(x), st)} {einheit}'


# ---------------------------------------------------------------- Module
# Reihenfolge = Rechenreihenfolge: spätere Indikatoren dürfen die schon berechneten neuen Werte früherer lesen (z). Wirkungen (E = Erfüllung je Politikfeld) bekommen
# die neuen Indikatorwerte z und einen Kontext ctx (zuf = letzte Zufriedenheit). Hebel: bev_pp, kopf_pct, zuf_pt, ruestung_pct (Preis von Militärgütern in %).

def _w(titel, hebel, wert, text):
    return {"hebel": hebel, "wert": wert, "titel": titel, "text": text}


def _wirk_infrastruktur(z, ctx):
    w, m, st = z["wasser"], z["muell"], z["strassen"]
    out = [_w("Straßen und Brücken", "kopf_pct", _clamp(0.10 * (st - NEUTRAL), -5, 3),
              "Gut instand gehaltene Straßen und Brücken sparen Zeit und Kosten" if st >= NEUTRAL else "Marode Straßen und Brücken verteuern jeden Transport")]
    if w < 65:
        out.append(_w("Schlechte Wasserversorgung", "zuf_pt", -min(6.0, 0.2 * (65 - w)), "Trinkwasser und Abwasser: Bürger klagen über Ausfälle und Qualität"))
    if w < 50:
        out.append(_w("Seuchengefahr", "bev_pp", -min(0.2, 0.01 * (50 - w)), "Verschmutztes Wasser: Krankheitswellen kosten Menschenleben"))
    if m < 65:
        out.append(_w("Müllprobleme", "zuf_pt", -min(5.0, 0.15 * (65 - m)), "Müll türmt sich in den Straßen, Ungeziefer und Gestank"))
    return out


def _wirk_transport(z, ctx):
    t, e = z["transport"], z["engpass"]
    out = [_w("Handel", "kopf_pct", _clamp(0.12 * (t - NEUTRAL), -6, 4),
              "Gute Verkehrswege beleben den Handel" if t >= NEUTRAL else "Schwache Verkehrswege behindern den Handel"),
           _w("Verkehr im Alltag", "zuf_pt", _clamp(0.10 * (t - NEUTRAL), -5, 1), "Pendler, Bahnen, Busse und Staus prägen die Stimmung")]
    if e > 20:
        out.append(_w("Lieferengpässe", "kopf_pct", -min(6.0, 0.15 * (e - 20)), "Die Produktion stockt, weil Material und Waren nicht ankommen"))
        out.append(_w("Leere Regale", "zuf_pt", -min(4.0, 0.10 * (e - 20)), "Händler können nicht liefern, die Bevölkerung merkt es im Alltag"))
        out.append(_w("Lieferketten", "ruestung_pct", min(10.0, 0.2 * (e - 20)), "Lieferengpässe verteuern auch Rüstungsgüter"))
    return out


def _wirk_umwelt(z, ctx):
    c = z["co2"]
    out = []
    if c > 70:
        out.append(_w("Klimaschäden", "kopf_pct", -min(5.0, 0.12 * (c - 70)), "Dürren, Überschwemmungen und Ernteschäden belasten die Wirtschaft"))
        out.append(_w("Smog und Luftverschmutzung", "zuf_pt", -min(5.0, 0.15 * (c - 70)), "Die Bevölkerung leidet unter schlechter Luft"))
    elif c < 35:
        out.append(_w("Saubere Umwelt", "kopf_pct", min(1.5, 0.05 * (35 - c)), "Saubere Luft und Landschaft ziehen Fachkräfte an"))
        out.append(_w("Lebensqualität", "zuf_pt", min(2.0, 0.06 * (35 - c)), "Die Bevölkerung schätzt die Natur und die frische Luft"))
    return out


def _wirk_landwirtschaft(z, ctx):
    e = z["ernaehrung"]
    out = []
    if e < 60:
        out.append(_w("Hunger", "zuf_pt", -min(8.0, 0.25 * (60 - e)), "Lebensmittel sind knapp und teuer, die Menschen hungern"))
        out.append(_w("Hungersnot", "bev_pp", -min(0.25, 0.012 * (60 - e)), "Unterernährung kostet Menschenleben"))
        out.append(_w("Geschwächte Arbeitskräfte", "kopf_pct", -min(3.0, 0.08 * (60 - e)), "Hungernde Menschen arbeiten weniger"))
    elif e > NEUTRAL:
        out.append(_w("Überschüsse", "kopf_pct", min(1.0, 0.04 * (e - NEUTRAL)), "Agrarüberschüsse lassen sich exportieren"))
    return out


def _wirk_gesundheit(z, ctx):
    g = z["gesundheit"]
    pp = 0.008 * (g - NEUTRAL)
    jahr = pp * 12
    return [_w("Gesundheitsniveau", "bev_pp", pp,
               f'Bevölkerung {"wächst" if pp >= 0 else "schrumpft"} um {_de(abs(jahr))} % pro Jahr' if abs(jahr) >= 0.05 else "Bevölkerung unverändert")]


def _wirk_sicherheit(z, ctx):
    s, u = z["sicherheit"], z["ueberwachung"]
    out = []
    if s < 75:
        out.append(_w("Hohe Kriminalität", "kopf_pct", -min(6.0, 0.12 * (75 - s)), "Kriminalität schreckt Investoren ab und verursacht Schäden"))
    elif s > NEUTRAL:
        out.append(_w("Sichere Städte", "kopf_pct", min(1.5, 0.06 * (s - NEUTRAL)), "Sicherheit zieht Investitionen und Touristen an"))
    if u > 25:
        out.append(_w("Überwachungsstaat", "kopf_pct", -min(4.0, 0.07 * (u - 25)), "Ein Klima der Kontrolle hemmt Gründungen, Forschung und Kultur"))
    if s < 60:
        out.append(_w("Bürger fühlen sich unsicher", "zuf_pt", -min(8.0, 0.2 * (60 - s)), "Zu wenig Polizei und Justiz: die Bevölkerung fürchtet Verbrechen"))
    if u > 30:
        out.append(_w("Bürger fühlen sich überwacht", "zuf_pt", -min(8.0, 0.18 * (u - 30)), "Zu viel Kontrolle: die Bevölkerung fühlt sich bevormundet und beobachtet"))
    return out


def _wirk_bildung(z, ctx):
    b, a, h = z["bildung"], z["akademiker"], z["handwerk"]
    out = [_w("Bildungsniveau", "kopf_pct", _clamp(0.20 * (b - NEUTRAL), -8, 8),
              "Qualifizierte Arbeitskräfte erhöhen die Wirtschaftsleistung pro Kopf" if b >= NEUTRAL else "Schlecht ausgebildete Arbeitskräfte drücken die Wirtschaftsleistung pro Kopf")]
    if a > 38:
        out.append(_w("Zu viele Akademiker", "kopf_pct", -min(8.0, 0.5 * (a - 38)), f"Akademikeranteil {_de(a)} %: Überqualifikation, die Wirtschaft braucht mehr Handwerk und Facharbeit"))
    elif a < 18:
        out.append(_w("Zu wenige Akademiker", "kopf_pct", -min(5.0, 0.35 * (18 - a)), f"Akademikeranteil {_de(a)} %: es fehlen Forscher, Ärzte und Ingenieure, Innovation stockt"))
    if h < 38:
        out.append(_w("Handwerkermangel", "kopf_pct", -min(6.0, 0.4 * (38 - h)), f"Nur {_de(h)} % Handwerker und Facharbeiter: Betriebe finden keine Fachkräfte"))
    if a > 40:
        out.append(_w("Akademiker ohne Stelle", "zuf_pt", -min(3.0, 0.15 * (a - 40)), "Viele Hochqualifizierte finden keine passende Arbeit, das drückt die Stimmung"))
    return out


def _wirk_forschung(z, ctx):
    f = z["forschung"]
    return [_w("Innovation", "kopf_pct", _clamp(0.12 * (f - NEUTRAL), -5, 5),
               "Neue Verfahren und Erfindungen steigern die Produktivität" if f >= NEUTRAL else "Der technische Rückstand bremst die Produktivität"),
            _w("Rüstungsforschung", "ruestung_pct", _clamp(-0.6 * (f - NEUTRAL), -25, 35),
               "Gute Forschung macht Militärgüter günstiger" if f >= NEUTRAL else "Schwache Forschung verteuert Militärgüter: veraltete Technik, Abhängigkeit vom Ausland")]


def _wirk_industrie(z, ctx):
    i = z["industrie"]
    return [_w("Industrieproduktion", "kopf_pct", _clamp(0.35 * (i - NEUTRAL), -10, 10),
               "Eine starke Industrie erhöht das gesamte BIP" if i >= NEUTRAL else "Eine schwache Industrie senkt das gesamte BIP")]


def _wirk_kultur(z, ctx):
    k, t = z["kultur"], z["tourismus"]
    return [_w("Tourismus", "kopf_pct", _clamp(0.10 * (t - NEUTRAL), -4, 5),
               "Besucher bringen Einnahmen in Hotels, Gastronomie und Handel" if t >= NEUTRAL else "Wenige Besucher: Hotels, Gastronomie und Handel verdienen weniger"),
            _w("Kulturelles Leben", "zuf_pt", _clamp(0.12 * (k - NEUTRAL), -5, 3), "Theater, Museen und Feste prägen die Stimmung" if k >= NEUTRAL else "Das Land wirkt trist: kaum Kultur und Feste")]


def _wirk_bevoelkerung(z, ctx):
    zu = ctx.get("zuf", 80.0)
    if zu < 45:
        return [_w("Abwanderung", "bev_pp", -min(0.2, 0.01 * (45 - zu)), "Unzufriedene Menschen verlassen das Land")]
    if zu > 85:
        return [_w("Zuzug", "bev_pp", 0.03, "Das Land gilt als lebenswert, Menschen ziehen zu")]
    return []


def _ind(id_, name, einheit, start, traeg, ziel):
    return {"id": id_, "name": name, "einheit": einheit, "start": start, "traeg": traeg, "ziel": ziel}


MODULE = [
    {"id": "infrastruktur", "name": "Infrastruktur", "icon": "house", "kategorien": ("infrastruktur", "umwelt", "transport"),
     "beschreibung": "Wasserversorgung und Wasseraufbereitung, Müllentsorgung, Straßenmeisterei, Brücken: alles, was ein Land am Laufen hält. Verfall bleibt lange unbemerkt, "
                     "wirkt dann aber auf Gesundheit, Umwelt, Verkehr, Tourismus und Stimmung.",
     "indikatoren": [
         _ind("wasser", "Wasserversorgung", "Punkte", NEUTRAL, 0.15, lambda E, z: 0.75 * _t(E, "infrastruktur") + 0.25 * _t(E, "umwelt")),
         _ind("muell", "Müllentsorgung", "Punkte", NEUTRAL, 0.15, lambda E, z: 0.80 * _t(E, "infrastruktur") + 0.20 * _t(E, "umwelt")),
         _ind("strassen", "Straßen und Brücken", "Punkte", NEUTRAL, 0.12, lambda E, z: 0.80 * _t(E, "infrastruktur") + 0.20 * _t(E, "transport"))],
     "wirkungen": _wirk_infrastruktur},
    {"id": "transport", "name": "Transport und Handel", "icon": "arrow-right-left", "kategorien": ("transport", "infrastruktur", "industrie"),
     "beschreibung": "Bahnen, Häfen und Verkehrswege (80 %, dazu der Zustand der Straßen 20 %) bestimmen den Handel. Fehlt Transportkapazität für die Industrie, entstehen "
                     "Lieferengpässe: Produktion und Versorgung stocken, sogar Rüstungsgüter werden teurer.",
     "indikatoren": [
         _ind("transport", "Transportniveau", "Punkte", NEUTRAL, 0.15, lambda E, z: 0.80 * _t(E, "transport") + 0.20 * z["strassen"]),
         _ind("engpass", "Lieferengpässe", "Punkte", 0.0, 0.25, lambda E, z: _clamp(100 * (1 + 0.5 * (E.get("industrie", 1.0) - 1) - z["transport"] / NEUTRAL), 0, 100))],
     "wirkungen": _wirk_transport},
    {"id": "umwelt", "name": "Umwelt und Klima", "icon": "circle-alert", "kategorien": ("umwelt", "industrie", "transport", "landwirtschaft"),
     "beschreibung": "Die CO₂-Belastung steigt mit Industrie, Verkehr und Landwirtschaft und sinkt mit Investitionen in die Umwelt; Müll verschlechtert sie. Hohe Belastung "
                     "senkt das Gesundheitsniveau, belastet das Klima und die Stimmung.",
     "indikatoren": [
         _ind("co2", "CO₂-Belastung", "Punkte", 50.0, 0.12,
              lambda E, z: _clamp(50 + 22 * (E.get("industrie", 1.0) - 1) + 8 * (E.get("transport", 1.0) - 1) + 6 * (E.get("landwirtschaft", 1.0) - 1)
                                  - 45 * (E.get("umwelt", 1.0) - 1) + 0.35 * (NEUTRAL - z["muell"]), 0, 100))],
     "wirkungen": _wirk_umwelt},
    {"id": "landwirtschaft", "name": "Landwirtschaft und Ernährung", "icon": "file-check", "kategorien": ("landwirtschaft", "transport", "soziales"),
     "beschreibung": "Die Ernährungssicherheit hängt vor allem von der Landwirtschaft ab, dazu von Transport (Verteilung) und Sozialausgaben. Lieferengpässe und Umweltschäden "
                     "verschlechtern sie. Unter 60 Punkten herrscht Hunger.",
     "indikatoren": [
         _ind("ernaehrung", "Ernährungssicherheit", "Punkte", NEUTRAL, 0.20,
              lambda E, z: _clamp(0.70 * _t(E, "landwirtschaft") + 0.15 * z["transport"] + 0.15 * _t(E, "soziales")
                                  - 0.3 * max(0, z["engpass"] - 20) - 0.2 * max(0, z["co2"] - 70), 0, 100))],
     "wirkungen": _wirk_landwirtschaft},
    {"id": "gesundheit", "name": "Gesundheit", "icon": "shield-check", "kategorien": ("gesundheit", "soziales", "umwelt", "infrastruktur", "landwirtschaft"),
     "beschreibung": "Das Gesundheitsniveau besteht zu 55 % aus dem Gesundheitswesen, dazu Sozialausgaben (8 %), Trinkwasser (10 %), Ernährung (12 %) und Umwelt (15 %: "
                     "hohe CO₂-Belastung macht krank). Es bestimmt die Lebenserwartung und das Bevölkerungswachstum.",
     "indikatoren": [
         _ind("gesundheit", "Gesundheitsniveau", "Punkte", NEUTRAL, 0.18,
              lambda E, z: _clamp(0.55 * _t(E, "gesundheit") + 0.08 * _t(E, "soziales") + 0.10 * z["wasser"] + 0.12 * z["ernaehrung"]
                                  + 0.15 * (NEUTRAL - 0.8 * (z["co2"] - 50)), 0, 100))],
     "wirkungen": _wirk_gesundheit},
    {"id": "sicherheit", "name": "Innere Sicherheit", "icon": "shield", "kategorien": ("innere_sicherheit", "soziales"),
     "beschreibung": "Innere Sicherheit (75 %) und Arbeit und Soziales (25 %) bestimmen das Sicherheitsgefühl und die Kriminalitätsrate. Zu wenig Sicherheit: die Bürger "
                     "fühlen sich unsicher. Weit über dem Richtwert wächst der Überwachungsgrad: die Bürger fühlen sich überwacht und bevormundet.",
     "indikatoren": [
         _ind("sicherheit", "Sicherheitsgefühl", "Punkte", NEUTRAL, 0.25, lambda E, z: 0.75 * _t(E, "innere_sicherheit") + 0.25 * _t(E, "soziales")),
         _ind("ueberwachung", "Überwachungsgrad", "Punkte", 0.0, 0.30, lambda E, z: _clamp(60 * (E.get("innere_sicherheit", 1.0) - 1.2), 0, 100))],
     "wirkungen": _wirk_sicherheit},
    {"id": "bildung", "name": "Bildung und Arbeitsmarkt", "icon": "file-text", "kategorien": ("bildung", "forschung", "industrie"),
     "beschreibung": "Bildung (85 %) und Forschung (15 %) bestimmen das Bildungsniveau und damit das BIP pro Kopf. Die Bildungsausgaben legen auch fest, wie viele "
                     "Menschen studieren: zu viele Akademiker bedeuten zu wenige Handwerker und Facharbeiter (die Industrie fragt sie nach), zu wenige bremsen die Innovation.",
     "indikatoren": [
         _ind("bildung", "Bildungsniveau", "Punkte", NEUTRAL, 0.10, lambda E, z: 0.85 * _t(E, "bildung") + 0.15 * _t(E, "forschung")),
         _ind("akademiker", "Akademikeranteil", "%", 26.0, 0.09, lambda E, z: _clamp(8 + 18 * E.get("bildung", 1.0), 5, 60)),
         _ind("handwerk", "Handwerker und Facharbeiter", "%", 48.0, 0.09,
              lambda E, z: _clamp(48 - 0.7 * (z["akademiker"] - 26) + 8 * (E.get("industrie", 1.0) - 1), 10, 70))],
     "wirkungen": _wirk_bildung},
    {"id": "forschung", "name": "Forschung und Technik", "icon": "search", "kategorien": ("forschung", "bildung"),
     "beschreibung": "Forschung (80 %, dazu das Bildungsniveau 20 %) bestimmt den Stand der Technik. Er steigert die Produktivität und macht Militärgüter günstiger "
                     "(Beschaffungspreise der Verteidigung); bei schwacher Forschung werden sie teurer.",
     "indikatoren": [_ind("forschung", "Innovationsniveau", "Punkte", NEUTRAL, 0.08, lambda E, z: 0.80 * _t(E, "forschung") + 0.20 * z["bildung"])],
     "wirkungen": _wirk_forschung},
    {"id": "industrie", "name": "Industrie und Wirtschaft", "icon": "chart-column", "kategorien": ("industrie", "forschung", "transport"),
     "beschreibung": "Die Industrie (70 %, dazu Forschung und Transport je 15 %) bestimmt das gesamte BIP. Sie verbraucht aber Umwelt (CO₂), braucht Handwerker "
                     "und überlastet bei schwachem Verkehrsnetz die Lieferwege.",
     "indikatoren": [_ind("industrie", "Industrieniveau", "Punkte", NEUTRAL, 0.10, lambda E, z: 0.70 * _t(E, "industrie") + 0.15 * _t(E, "forschung") + 0.15 * z["transport"])],
     "wirkungen": _wirk_industrie},
    {"id": "kultur", "name": "Kultur und Tourismus", "icon": "landmark", "kategorien": ("kultur", "bildung"),
     "beschreibung": "Das Kulturangebot (85 %, dazu Bildung 15 %) macht ein Land lebenswert. Der Tourismus hängt außerdem von Sicherheit, Sauberkeit (Müll, CO₂) und "
                     "Straßen ab; Überwachung schreckt Besucher ab.",
     "indikatoren": [
         _ind("kultur", "Kulturniveau", "Punkte", NEUTRAL, 0.12, lambda E, z: 0.85 * _t(E, "kultur") + 0.15 * _t(E, "bildung")),
         _ind("tourismus", "Attraktivität für Touristen", "Punkte", NEUTRAL, 0.15,
              lambda E, z: _clamp(0.40 * z["kultur"] + 0.15 * z["sicherheit"] + 0.15 * z["muell"] + 0.15 * z["strassen"]
                                  + 0.15 * (NEUTRAL - 0.8 * (z["co2"] - 50)) - 0.3 * max(0, z["ueberwachung"] - 30), 0, 100))],
     "wirkungen": _wirk_kultur},
    {"id": "energie", "name": "Energieversorgung", "icon": "zap", "kategorien": (),
     "beschreibung": "Fehlende Energie senkt Zufriedenheit, Infrastruktur und Industrie.",
     "indikatoren": [], "wirkungen": lambda z, ctx: []},
    {"id": "bevoelkerung", "name": "Bevölkerungswachstum und Schwund", "icon": "users", "kategorien": (),
     "beschreibung": "Die Einwohnerzahl ändert sich jeden Monat um die Summe aus Gesundheit, Wasserversorgung, Hunger und der Stimmung (Abwanderung bei Unzufriedenheit, "
                     "Zuzug bei großer Zufriedenheit). Mehr Einwohner bedeuten mehr Steueraufkommen und eine höhere Reichsabgabe.",
     "indikatoren": [], "wirkungen": _wirk_bevoelkerung},
]
INDIKATOREN = {i["id"]: i for m in MODULE for i in m["indikatoren"]}


# ---------------------------------------------------------------- Zustand

def start_zustand():
    z = {i: d["start"] for i, d in INDIKATOREN.items()}
    z["bev_faktor"] = 1.0
    return z


def zustand_vor(con, schl, periode):
    """Gespeicherter Zustand des letzten Monats vor `periode` (oder der Startzustand)."""
    z = start_zustand()
    try:
        r = con.execute("SELECT MAX(periode) p FROM ep_zustand WHERE schl=? AND periode<?", (schl, periode)).fetchone()
        if r and r["p"]:
            for x in con.execute("SELECT schluessel, wert FROM ep_zustand WHERE schl=? AND periode=?", (schl, r["p"])):
                z[x["schluessel"]] = float(x["wert"])
    except sqlite3.OperationalError:   # Tabelle noch nicht angelegt (Werkzeuge außerhalb des Dienstes): Startzustand
        pass
    return z


def erfuellung(anteile, richt):
    """E je Politikfeld = Anteil ÷ Richtwert (1 = Vorgabe)."""
    return {k: (float(anteile.get(k, 0)) / float(richt[k]) if float(richt.get(k, 0)) >= 0.05 else 1.0) for k in anteile}


def _schritt(alt, E, ctx):
    """Ein Monat Entwicklung (rein, ohne Datenbank): (neuer Zustand, {id: {alt, ziel, neu}}, Effekte, Summen {bev_pp, kopf, zuf, ruestung})."""
    neu, zust = dict(alt), {}
    shift = ctx.get("shift", {})   # Verschiebung der Zielwerte durch laufende Krisenmaßnahmen (krisen.wirkungen_fuer)
    for m in MODULE:
        for i in m["indikatoren"]:
            ziel = _clamp(i["ziel"](E, neu) + shift.get(i["id"], 0.0), 0, 100)
            n = alt[i["id"]] + (ziel - alt[i["id"]]) * i["traeg"]
            neu[i["id"]] = n
            zust[i["id"]] = {"alt": alt[i["id"]], "ziel": ziel, "neu": n}
    effekte = []
    for m in MODULE:
        for e in m["wirkungen"](neu, ctx):
            effekte.append(dict(e, modul=m["id"]))
    effekte += ctx.get("extra", [])   # Wirkungen von Krisen und Krisenmaßnahmen
    summen = {"bev_pp": sum(e["wert"] for e in effekte if e["hebel"] == "bev_pp"),
              "kopf": _clamp(sum(e["wert"] for e in effekte if e["hebel"] == "kopf_pct"), *KOPF_GRENZEN),
              "zuf": sum(e["wert"] for e in effekte if e["hebel"] == "zuf_pt"),
              "ruestung": _clamp(sum(e["wert"] for e in effekte if e["hebel"] == "ruestung_pct"), *RUESTUNG_GRENZEN)}
    return neu, zust, effekte, summen


def entwickeln(con, schl, anteile, richt, periode, kopf_ratio=1.0, ind_faktor=1.0):
    """Zustand eines Haushalts im Monat `periode` bei dieser Verteilung. Rückgabe: {"zustand": {id: {alt, ziel, neu}}, "effekte": [...], "bev_pp", "bev_faktor",
    "kopf_pct", "kopf_faktor", "zuf_pt", "hdi", "lebenserwartung", "kriminalitaet"}."""
    import etatplan
    E = erfuellung(anteile, richt)
    if "industrie" in E:
        E["industrie"] *= ind_faktor   # Kraftwerke (Instandhaltung, Bauraten) zahlt der Industrie-Etat: Er bleibt der Industrie selbst nicht mehr
    alt = zustand_vor(con, schl, periode)
    zu = etatplan.zuf_letzte(con, schl)
    import krisen
    ex, shift = krisen.wirkungen_fuer(con, schl, periode)
    import energie
    ex_en, shift_en = energie.wirkungen_fuer(con, schl, periode)   # Mali bei nicht gedecktem Energiebedarf
    ex = ex + ex_en
    for i_, v_ in shift_en.items():
        shift[i_] = shift.get(i_, 0.0) + v_
    neu, zust, effekte, sm = _schritt(alt, E, {"zuf": 80.0 if zu is None else zu, "shift": shift, "extra": ex})
    bev = _clamp(alt["bev_faktor"] * (1 + sm["bev_pp"] / 100), *BEV_GRENZEN)
    einkommen = _clamp(70 + 25 * math.log2(max(0.05, kopf_ratio * (1 + sm["kopf"] / 100))), 0, 100)
    hdi = (neu["gesundheit"] + neu["bildung"] + einkommen) / 300
    return {"zustand": zust, "effekte": effekte, "bev_pp": sm["bev_pp"], "bev_faktor": bev, "bev_faktor_alt": alt["bev_faktor"], "kopf_pct": sm["kopf"],
            "kopf_faktor": 1 + sm["kopf"] / 100, "zuf_pt": sm["zuf"], "ruestung_pct": sm["ruestung"], "hdi": hdi, "lebenserwartung": 55 + 0.35 * neu["gesundheit"],
            "kriminalitaet": 3500 * math.exp((NEUTRAL - neu["sicherheit"]) / 40), "einkommen_index": einkommen, "kopf_ratio": kopf_ratio}


# ---------------------------------------------------------------- Rückhalt beim Volk (Gesamtbild)
# Wie steht die Bevölkerung voraussichtlich zu ihrem Landesherrn (Reich: zur Reichsregierung)? Gewichteter Wert 0–100 aus sechs Teilen; nur Anzeige, ohne eigene Folgen.
# Prognose: derselbe Etat, die Entwicklung läuft 3 Monate bzw. 4 Jahre weiter (Indikatoren folgen ihren Zielwerten, die Zufriedenheit mit ihrer Trägheit).

RUECKHALT_STUFEN = [(85, "Verehrt", "Das Volk verehrt seinen Landesherrn."), (70, "Starker Rückhalt", "Das Volk steht hinter seinem Landesherrn."),
                    (55, "Gespalten", "Das Volk ist über seinen Landesherrn gespalten."), (40, "Unbeliebt", "Das Volk murrt gegen seinen Landesherrn."),
                    (25, "Offene Kritik", "Es gibt Proteste und offene Kritik am Landesherrn."), (0, "Aufstand droht", "Das Volk steht kurz vor dem Aufstand gegen seinen Landesherrn.")]
HAUSHALT_PUNKTE = {0: 80, 1: 55, 2: 40, 3: 25, 4: 10}
# (Schlüssel, Name, Gewicht, Neutralwert, Text bei Plus, Text bei Minus)
RUECKHALT_TEILE = [("zufriedenheit", "Allgemeine Zufriedenheit", 0.45, NEUTRAL, "Die Bürger sind insgesamt zufrieden", "Die Bürger sind insgesamt unzufrieden"),
                   ("wohlstand", "Wohlstand", 0.15, 70.0, "Die Wirtschaft floriert", "Die Wirtschaft schwächelt"),
                   ("versorgung", "Versorgung", 0.15, NEUTRAL, "Gesundheit, Nahrung und Wasser sind gut gesichert", "Gesundheit, Nahrung und Wasser sind schlecht gesichert"),
                   ("sicherheit", "Sicherheit und Freiheit", 0.10, NEUTRAL, "Die Bürger fühlen sich sicher und frei", "Die Bürger fühlen sich unsicher oder überwacht"),
                   ("bevoelkerung", "Bevölkerungsentwicklung", 0.05, 70.0, "Das Land wächst", "Das Land schrumpft"),
                   ("haushalt", "Haushaltslage", 0.10, 80.0, "Die Staatsfinanzen sind geordnet", "Die Staatskasse steckt in der Haushaltsnotlage")]


def rueckhalt_stufe(wert):
    return next((n, t) for g, n, t in RUECKHALT_STUFEN if wert >= g)


def haushalt_stufe(con, schl):
    """Haushaltsnotlage des Teilstaats (0 = keine, 1–3 Stufen, 4 = Zwangsverwaltung); das Reich hat keine."""
    if not schl.startswith("ts-"):
        return 0
    import notlage
    stufe = 0
    for stelle in ("ts-" + schl[3:], "vt-" + schl[3:]):
        r = geld.stellenkonto(con, stelle)
        f = notlage.offener_fall(con, r["id"]) if r else None
        if f:
            stufe = max(stufe, 4 if f["zwang"] else min(3, int(f["stufe"])))
    return stufe


def rueckhalt_aus(st, zuf, kopf_pct, bev_pp, stufe):
    """Rückhalt aus einem Zustand: {"wert", "teile": [{schluessel, name, score, gewicht, beitrag, text}]}; beitrag = Abweichung vom Neutralzustand in Punkten."""
    scores = {"zufriedenheit": zuf, "wohlstand": _clamp(70 + 3 * kopf_pct, 0, 100),
              "versorgung": _clamp(0.4 * st["gesundheit"] + 0.4 * st["ernaehrung"] + 0.2 * st["wasser"], 0, 100),
              "sicherheit": _clamp(st["sicherheit"] - 0.6 * max(0.0, st["ueberwachung"] - 20), 0, 100),
              "bevoelkerung": _clamp(70 + 12 * bev_pp * 12, 0, 100), "haushalt": HAUSHALT_PUNKTE[stufe]}
    teile, wert = [], 0.0
    for k, name, g, neutral, plus, minus in RUECKHALT_TEILE:
        sc = scores[k]
        beitrag = (sc - neutral) * g
        wert += sc * g
        if sc >= neutral + 3:
            text = plus
        elif sc <= neutral - 15:
            text = minus
        else:   # nur leichte Abweichung: nicht „unzufrieden“ sagen, wenn der Wert noch gut ist
            text = f'{name} liegt {"etwas über" if sc >= neutral else "etwas unter"} dem Normalwert'
        teile.append({"schluessel": k, "name": name, "score": sc, "gewicht": g, "beitrag": beitrag, "text": text})
    return {"wert": _clamp(wert, 0, 100), "teile": teile}


def rueckhalt(con, schl, d, zuf, anteile, richt):
    """Rückhalt jetzt, in drei Monaten und auf Dauer (bei gleichbleibendem Etat). d = Entwicklung des Haushalts (entwickeln), zuf = Zufriedenheit (etatplan.zufriedenheit)."""
    import etatplan
    stufe = haushalt_stufe(con, schl)
    st = {i: v["neu"] for i, v in d["zustand"].items()}
    st["bev_faktor"] = d["bev_faktor"]
    jetzt = rueckhalt_aus(st, zuf["neu"], d["kopf_pct"], d["bev_pp"], stufe)
    E = erfuellung(anteile, richt)
    z_basis = etatplan.zuf_ziel(anteile, richt)[0]
    z, werte = zuf["neu"], {}
    for monat in range(1, 49):
        st, _, _, sm = _schritt(st, E, {"zuf": z})
        z = z + (_clamp(z_basis + sm["zuf"], 0, 100) - z) * etatplan.ZUF_TRAEGHEIT
        if monat in (3, 48):
            werte[monat] = rueckhalt_aus(st, z, sm["kopf"], sm["bev_pp"], stufe)
    r3, rl = werte[3], werte[48]
    stufe_name, text = rueckhalt_stufe(jetzt["wert"])
    delta = rl["wert"] - jetzt["wert"]
    gruende = sorted(jetzt["teile"], key=lambda t: -abs(t["beitrag"]))
    return {"wert": jetzt["wert"], "stufe": stufe_name, "text": text, "teile": jetzt["teile"], "prognose3": r3["wert"], "langfristig": rl["wert"],
            "trend": "steigend" if delta > 2 else "fallend" if delta < -2 else "stabil", "haushalt_stufe": stufe,
            "gruende": [t for t in gruende if abs(t["beitrag"]) >= 0.5][:3]}


def rueckhalt_fuer(con, liste, schl):
    """Rückhalt eines Haushalts (ts-<sid> | reich) aus aufkommen.berechnen; im Posten zwischengespeichert."""
    if schl == "reich":
        x = liste[0]
        d, zuf, anteile, richt = x["entwicklung_reich"], x["zufriedenheit_reich"], x["plan_reich"], x["richt_reich"]
    else:
        x = next((y for y in liste if "ts-" + y["staat"] == schl), None)
        if not x or not x.get("entwicklung"):
            return None
        d, zuf, anteile, richt = x["entwicklung"], x["zufriedenheit_land"], x["plan_land"], x["richt_land"]
    if "_rueckhalt" not in x:
        x["_rueckhalt"] = rueckhalt(con, schl, d, zuf, anteile, richt)
    return x["_rueckhalt"]


def berechne(con, liste, periode):
    """Entwicklung aller Haushalte aus einer Liste von aufkommen.berechnen (ohne Entwicklung: enthält plan_land/richt_land, plan_reich/richt_reich).
    Rückgabe {"faktoren": {schl: {"bev", "kopf", "zuf_pt"}}, "details": {schl: entwickeln(...)}}."""
    import etatplan
    periode = periode or etatplan.naechster_lauf(con)
    ew_ges = sum(x["ew"] for x in liste) or 1
    ref = sum(x["bip"] for x in liste) / ew_ges     # Mio. € je Einwohner (ganzes Reich)
    details = {}
    rd = [x for x in liste if x["reichsgebiet"]]
    if liste:
        ew_r = sum(x["ew"] for x in rd) or 1
        ratio = (sum(x["bip"] for x in rd) / ew_r) / ref if rd else 1.0
        import energie
        ind_reich = sum(x["verteilung_reich"].get("industrie", 0) for x in liste)
        details["reich"] = entwickeln(con, "reich", liste[0]["plan_reich"], liste[0]["richt_reich"], periode, ratio,
                                      energie.industrie_faktor(con, "reich", periode, ind_reich))
    for x in liste:
        if x["reichsgebiet"] or not x.get("plan_land"):
            continue
        ratio = (x["bip"] / x["ew"] / ref) if x["ew"] else 1.0
        import energie
        details["ts-" + x["staat"]] = entwickeln(con, "ts-" + x["staat"], x["plan_land"], x["richt_land"], periode, ratio,
                                                 energie.industrie_faktor(con, "ts-" + x["staat"], periode, (x["verteilung_land"] or {}).get("industrie", 0)))
    faktoren = {s: {"bev": d["bev_faktor"], "kopf": d["kopf_faktor"], "zuf_pt": d["zuf_pt"]} for s, d in details.items()}
    return {"faktoren": faktoren, "details": details}


def speichern(con, periode, liste):
    """Hält den Zustand des gebuchten Monats fest (aus aufkommen.berechnen: x["entwicklung"], liste[0]["entwicklung_reich"])."""
    ds = {}
    if liste and liste[0].get("entwicklung_reich"):
        ds["reich"] = liste[0]["entwicklung_reich"]
    for x in liste:
        if x.get("entwicklung"):
            ds["ts-" + x["staat"]] = x["entwicklung"]
    for schl, d in ds.items():
        for i, v in d["zustand"].items():
            con.execute("INSERT OR REPLACE INTO ep_zustand (periode, schl, schluessel, wert) VALUES (?,?,?,?)", (periode, schl, i, round(v["neu"], 4)))
        con.execute("INSERT OR REPLACE INTO ep_zustand (periode, schl, schluessel, wert) VALUES (?,?,?,?)", (periode, schl, "bev_faktor", round(d["bev_faktor"], 6)))
        con.execute("INSERT OR REPLACE INTO ep_zustand (periode, schl, schluessel, wert) VALUES (?,?,?,?)", (periode, schl, "ruestung_pct", round(d["ruestung_pct"], 4)))


def ruestung_faktor(con, stelle):
    """Preisfaktor für Militärgüter einer Verteidigungskasse (vt-<sid> bzw. verteidigung = Reich) aus dem zuletzt gebuchten Stand: Forschung und Lieferketten."""
    schl = "reich" if stelle == "verteidigung" else "ts-" + stelle[3:] if stelle.startswith("vt-") else None
    if not schl:
        return 1.0
    try:
        r = con.execute("SELECT wert FROM ep_zustand WHERE schl=? AND schluessel='ruestung_pct' ORDER BY periode DESC LIMIT 1", (schl,)).fetchone()
    except sqlite3.OperationalError:
        return 1.0
    return 1.0 + float(r["wert"]) / 100 if r else 1.0


def verlauf(con, schl, n=12):
    """[(Periode, {Schlüssel: Wert})] der letzten gebuchten Monate, älteste zuerst."""
    ps = [r["periode"] for r in con.execute("SELECT DISTINCT periode FROM ep_zustand WHERE schl=? ORDER BY periode DESC LIMIT ?", (schl, n))][::-1]
    out = []
    for p in ps:
        out.append((p, {r["schluessel"]: float(r["wert"]) for r in con.execute("SELECT schluessel, wert FROM ep_zustand WHERE schl=? AND periode=?", (schl, p))}))
    return out


# ---------------------------------------------------------------- Anzeige

CSS = """<style>
.en-modul{border:1px solid var(--linie);border-radius:12px;padding:12px 16px;margin:12px 0;background:#fff}
.en-modul h3{margin:0 0 2px;display:flex;gap:8px;align-items:center;font-size:15px}.en-modul h3 .icon{width:17px;height:17px}
.en-modul>p{margin:2px 0 8px;font-size:13px;color:var(--grau)}
.en-ind{display:grid;grid-template-columns:minmax(120px,170px) 1fr minmax(100px,150px);gap:4px 14px;align-items:center;margin:8px 0;font-size:14px}
.en-bar{position:relative;height:10px;border-radius:6px;background:var(--hell,#eee);overflow:visible}
.en-bar i{position:absolute;left:0;top:0;bottom:0;border-radius:6px;background:var(--ink)}
.en-bar b{position:absolute;top:-3px;width:2px;height:16px;background:var(--grau)}
.en-ind small{color:var(--grau);text-align:right}
.en-rueck{border:1px solid var(--ink);border-radius:12px;padding:14px 18px;margin:14px 0;background:#fff;box-shadow:0 0 0 1px var(--ink)}
.en-rueck-kopf{display:flex;flex-wrap:wrap;gap:6px 22px;align-items:flex-end}
.en-rueck-wert{font-size:38px;font-weight:700;line-height:1}.en-rueck-wert small{font-size:15px;font-weight:500;color:var(--grau)}
.en-rueck-stufe{font-weight:650;font-size:16px}
.en-rueck-zeit{display:flex;gap:18px;margin:10px 0 4px;font-size:13.5px;color:var(--grau);flex-wrap:wrap}.en-rueck-zeit b{color:var(--ink);font-size:17px;display:block}
.en-rueck-teile{display:grid;gap:5px;margin:10px 0 0}
.en-teil{display:grid;grid-template-columns:minmax(120px,190px) 1fr 74px;gap:10px;align-items:center;font-size:13.5px}
.en-teil .en-bar{height:8px}.en-teil small{text-align:right;color:var(--grau)}
.en-teil.plus small{color:var(--ok)}.en-teil.minus small{color:var(--rot)}
.en-effekte{display:grid;gap:6px;margin:8px 0}
.en-effekte div{display:flex;gap:10px;align-items:baseline;border:1px solid var(--linie);border-radius:10px;padding:8px 12px;background:#fff;font-size:14px}
.en-effekte b{min-width:92px;text-align:right;font-variant-numeric:tabular-nums}
.en-effekte .plus b{color:var(--ok)}.en-effekte .minus b{color:var(--rot)}
.en-effekte span{color:var(--grau);font-size:13px}.en-effekte em{font-style:normal;font-weight:600}
@media (max-width:600px){.en-ind{grid-template-columns:1fr 1fr}.en-ind .en-bar{grid-column:1/-1;order:3}}
</style>"""


def _indikator_zeile(i, v):
    wert, ziel = v["neu"], v["ziel"]
    skala = 100 if i["einheit"] != "%" else 60
    pf = lambda x: f"{_clamp(x / skala * 100, 0, 100):.1f}"
    pfeil = "▲" if ziel > wert + 0.3 else "▼" if ziel < wert - 0.3 else "●"
    return (f'<div class="en-ind"><span>{esc(i["name"])}</span><div class="en-bar" role="img" aria-label="{esc(i["name"])} {_de(wert)} {esc(i["einheit"])}">'
            f'<i style="width:{pf(wert)}%"></i><b style="left:{pf(i["start"])}%" title="Neutral (Vorgabe-Verteilung)"></b></div>'
            f'<small><b>{_de(wert)} {esc(i["einheit"])}</b> {pfeil} Ziel {_de(ziel, 0)}</small></div>')


def effekte_html(d, leer="Keine besonderen Wirkungen: die Investitionen liegen im Normalbereich."):
    zeilen = []
    for e in sorted(d["effekte"], key=lambda e: -abs(e["wert"])):
        if abs(e["wert"]) < 0.05:
            continue
        einheit = {"bev_pp": "% Bev. p. a.", "kopf_pct": "% BIP/Kopf", "zuf_pt": "Pkt. Zufriedenheit", "ruestung_pct": "% Rüstungspreis"}[e["hebel"]]
        wert = e["wert"] * (12 if e["hebel"] == "bev_pp" else 1)
        zeilen.append(f'<div class="{"plus" if e["wert"] > 0 else "minus"}"><b>{_vz(wert, einheit)}</b><span><em>{esc(e["titel"])}.</em> {esc(e["text"])}</span></div>')
    return f'<div class="en-effekte">{"".join(zeilen)}</div>' if zeilen else f'<p class="sa-hinweis">{esc(leer)}</p>'


def _pfeil(r):
    return {"steigend": "▲ steigend", "fallend": "▼ fallend", "stabil": "● stabil"}[r["trend"]]


def rueckhalt_html(r, reich=False):
    """Die Karte „Rückhalt beim Volk“: Wert, Stufe, Prognose, Teile und wichtigste Gründe."""
    if not r:
        return ""
    wer = "der Reichsregierung" if reich else "des Landesherrn"
    text = r["text"].replace("seinen Landesherrn", "die Reichsregierung").replace("seinem Landesherrn", "der Reichsregierung") if reich else r["text"]
    teile = "".join(
        f'<div class="en-teil {"plus" if t["beitrag"] > 0.4 else "minus" if t["beitrag"] < -0.4 else ""}"><span>{esc(t["name"])} <span class="az">({_de(t["gewicht"] * 100, 0)} %)</span></span>'
        f'<div class="en-bar" role="img" aria-label="{esc(t["name"])} {_de(t["score"], 0)} von 100"><i style="width:{_clamp(t["score"], 0, 100):.1f}%"></i></div>'
        f'<small>{_de(t["score"], 0)}</small></div>' for t in r["teile"])
    gruende = "".join(f'<li>{"▲" if t["beitrag"] > 0 else "▼"} {esc(t["text"])}</li>' for t in r["gruende"])
    return (f'<div class="en-rueck"><div class="en-rueck-kopf"><div><div class="en-rueck-wert">{_de(r["wert"], 0)}<small> / 100</small></div>'
            f'<div class="en-rueck-stufe">{esc(r["stufe"])}</div></div><div><b>Rückhalt beim Volk {wer}</b><br><span class="az">{esc(text)}</span></div></div>'
            f'<div class="en-rueck-zeit"><span>Jetzt<b>{_de(r["wert"], 0)}</b></span><span>in 3 Monaten<b>{_de(r["prognose3"], 0)}</b></span>'
            f'<span>auf Dauer, bei gleichem Etat<b>{_de(r["langfristig"], 0)}</b></span><span>Tendenz<b>{esc(_pfeil(r))}</b></span></div>'
            + (f'<ul class="sa-hinweis" style="margin:8px 0 0;padding:0;list-style:none">{gruende}</ul>' if gruende else "")
            + f'<details class="sa-auf" style="margin:10px 0 0"><summary>{amt.ic("chart-column")}Woraus der Rückhalt besteht</summary><div class="en-rueck-teile">{teile}</div></details></div>')


def kurz_html(d, link=None, r=None, reich=False):
    """Kurzfassung für die Etatseiten: die stärksten Wirkungen."""
    kz = (f'<b>HDI {_de(d["hdi"], 3)}</b> · Lebenserwartung {_de(d["lebenserwartung"], 0)} Jahre · Bevölkerungswachstum {_vz(d["bev_pp"] * 12)} pro Jahr'
          f' · BIP pro Kopf {_vz(d["kopf_pct"])} · Militärgüter {_vz(d["ruestung_pct"])}')
    return (CSS + f'<h2>{amt.ic("users")} Entwicklung</h2>{rueckhalt_html(r, reich)}<p class="az">Langfristige Wirkung der Investitionen. {kz}.'
            + (f' <a href="{esc(link)}">Alle Einzelheiten →</a>' if link else "") + f'</p>{effekte_html(d)}')


def rk_text(con, liste, schl):
    r = rueckhalt_fuer(con, liste, schl) if con is not None else None
    return f'{_de(r["wert"], 0)} · {esc(r["stufe"])}' if r else "–"


def tabelle(liste, ziel_liste, pfad, markiert="", con=None):
    """Öffentlich: HDI, Bevölkerungswachstum, Rückhalt beim Volk und Auffälligkeiten je Haushalt (ohne Beträge)."""
    zeilen = []
    for s, n in ziel_liste:
        if s == "reich":
            d, n = liste[0].get("entwicklung_reich"), "Freie Reichsgebiete (Reich)"
        else:
            d = next((x.get("entwicklung") for x in liste if "ts-" + x["staat"] == s), None)
        if not d:
            continue
        flags = []
        z = d["zustand"]
        if z["sicherheit"]["neu"] < 60:
            flags.append("unsicher")
        if z["ueberwachung"]["neu"] > 30:
            flags.append("überwacht")
        if z["akademiker"]["neu"] > 38:
            flags.append("Akademikerüberschuss")
        if z["handwerk"]["neu"] < 38:
            flags.append("Handwerkermangel")
        if z["gesundheit"]["neu"] < 55:
            flags.append("Gesundheitskrise")
        if z["ernaehrung"]["neu"] < 50:
            flags.append("Hunger")
        if z["co2"]["neu"] > 75:
            flags.append("Umweltbelastung")
        if z["engpass"]["neu"] > 40:
            flags.append("Lieferengpässe")
        if min(z["wasser"]["neu"], z["muell"]["neu"], z["strassen"]["neu"]) < 50:
            flags.append("Infrastruktur marode")
        if con is not None:
            import krisen
            flags += [f'Krise: {krisen.KRISEN[a]["name"]}' for a in krisen.offene_arten(con, s)]
        zeilen.append((d["hdi"], f'<tr{" class=fokus" if s == markiert else ""}><td><a href="{pfad}?ziel={esc(s)}">{esc(n)}</a></td>'
                                 f'<td class="num">{_de(d["hdi"], 3)}</td><td class="num">{_vz(d["bev_pp"] * 12)}</td>'
                                 f'<td class="num">{rk_text(con, liste, s)}</td>'
                                 f'<td class="num" style="white-space:normal;max-width:240px">{esc(", ".join(flags)) if flags else "–"}</td></tr>'))
    return ('<p class="zf-meta">HDI aus Gesundheit, Bildung und Einkommen. Bevölkerungswachstum pro Jahr bei der heutigen Gesundheitsversorgung.</p>'
            '<div style="overflow-x:auto"><table class="zf-tab"><thead><tr><th>Haushalt</th><th class="num">HDI</th><th class="num">Wachstum</th><th class="num" title="Wie steht die Bevölkerung voraussichtlich zu ihrem Landesherrn">Rückhalt</th><th class="num">Auffällig</th></tr></thead><tbody>'
            + "".join(z for _, z in sorted(zeilen, key=lambda t: -t[0])) + '</tbody></table></div>')


def _gewaehlt(request, k, con, liste):
    import etatplan
    regiert = sa._regierte(con, k)
    ziele = etatplan.ziele(con, liste)
    gueltig = {s for s, _ in ziele}
    ziel = request.query.get("ziel", "")
    if ziel not in gueltig:
        ziel = "ts-" + next(iter(regiert)) if regiert else "reich"
    return ziel, ziele


@sa.seite("staat")
async def seite(request, k):
    import aufkommen
    import etatplan
    con = request.app["db"]
    periode = etatplan.monat_heute()
    liste = aufkommen.berechnen(con, periode=periode)
    ziel, ziele = _gewaehlt(request, k, con, liste)
    name = dict(ziele)[ziel]
    if ziel == "reich":
        d = liste[0]["entwicklung_reich"]
        ew, ew0 = sum(x["ew"] for x in liste if x["reichsgebiet"]), sum(x["ew_karte"] for x in liste if x["reichsgebiet"])
        bip, bip0 = sum(x["bip"] for x in liste if x["reichsgebiet"]), sum(x["bip_karte"] for x in liste if x["reichsgebiet"])
        zuf = liste[0]["zufriedenheit_reich"]
    else:
        x = next(y for y in liste if "ts-" + y["staat"] == ziel)
        d, ew, ew0, bip, bip0, zuf = x["entwicklung"], x["ew"], x["ew_karte"], x["bip"], x["bip_karte"], x["zufriedenheit_land"]
    kopf = bip * 1e6 / ew if ew else 0
    kz = [("Einwohner", f'{ew:,}'.replace(",", ".")), ("BIP pro Kopf", f'{kopf:,.0f} €'.replace(",", ".")), ("HDI", _de(d["hdi"], 3)),
          ("Lebenserwartung", f'{_de(d["lebenserwartung"], 1)} Jahre')]
    kz2 = [("Bevölkerungswachstum pro Jahr", _vz(d["bev_pp"] * 12)), ("Bevölkerung gegenüber der Karte", _vz((ew / ew0 - 1) * 100 if ew0 else 0)),
           ("BIP pro Kopf durch Investitionen", _vz(d["kopf_pct"])), ("Preise für Militärgüter", _vz(d["ruestung_pct"])),
           ("Straftaten je 100.000 Einwohner", f'{d["kriminalitaet"]:,.0f}'.replace(",", ".")), ("Zufriedenheit", f'{_de(zuf["neu"], 0)} / 100')]
    kz_html = lambda xs: f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in xs)}</div>'
    rk = rueckhalt_fuer(con, liste, ziel)
    module = "".join(
        f'<div class="en-modul"><h3>{amt.ic(m["icon"])}{esc(m["name"])}</h3><p>{esc(m["beschreibung"])}</p>'
        + "".join(_indikator_zeile(i, d["zustand"][i["id"]]) for i in m["indikatoren"])
        + effekte_html({"effekte": [e for e in d["effekte"] if e["modul"] == m["id"]]}, "Keine besondere Wirkung.") + '</div>' for m in MODULE)
    vl = verlauf(con, ziel)
    zeilen = [(sa._monatsname(p), _de(v.get("gesundheit", NEUTRAL)), _de(v.get("bildung", NEUTRAL)), _de(v.get("akademiker", 26)) + " %", _de(v.get("handwerk", 48)) + " %",
               _de(v.get("sicherheit", NEUTRAL)), _de(v.get("ueberwachung", 0)), _de(v.get("co2", 50)), _de(v.get("ernaehrung", NEUTRAL)), _de(v.get("engpass", 0)),
               _vz((v.get("bev_faktor", 1) - 1) * 100)) for p, v in reversed(vl)]
    gewaehlt = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(n)}</option>' for s, n in ziele)
    inhalt = (CSS + f'<h1>{amt.ic("users")} Entwicklung · {esc(name)}</h1>{amt.meldung(request)}'
              '<p class="az">Die Investitionen in die Politikfelder wirken langfristig auf Bevölkerung, Wirtschaft und Stimmung. Die Werte folgen der Etatverteilung nur '
              'allmählich: ein Monat mit hohen oder niedrigen Ausgaben ändert wenig, dauerhafte Weichenstellungen viel.</p>'
              f'<form class="sa-leiste" method="get"><div><label for="zl">Haushalt</label><select id="zl" name="ziel" onchange="this.form.submit()">{gewaehlt}</select></div></form>'
              + rueckhalt_html(rk, ziel == "reich") + kz_html(kz) + kz_html(kz2) + f'<h2>Was gerade wirkt</h2>{effekte_html(d)}'
              + f'<h2>Die Bereiche im Einzelnen</h2><p class="sa-hinweis">Der Strich markiert den neutralen Wert bei der Vorgabe-Verteilung, der Pfeil die Richtung zum Zielwert.</p>{module}'
              + f'<details class="sa-auf"><summary>{amt.ic("clock")}Verlauf ({len(zeilen)} Monate)</summary>'
              + amt.tabelle(["Monat", "Gesundheit", "Bildung", "Akademiker", "Handwerker", "Sicherheit", "Überwachung", "CO₂", "Ernährung", "Engpässe", "Bevölkerung"], zeilen,
                            "Noch kein gebuchter Monat mit Entwicklung.", klasse="sa-haushalt") + '</details>'
              + f'<p><a href="{sa.PFAD}etatplanung/?ziel={esc(ziel)}">Etat planen →</a></p>')
    return sa.ant(request, k, "Entwicklung", "sa-entwicklung", inhalt)


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get(PFAD, seite)
