"""Entwicklung: langfristige Wirkung der Investitionen (Etatverteilung) auf Bevölkerung, Wirtschaft und Stimmung – modular.

Aufbau
- Jeder Haushalt (Teilstaat „ts-<sid>“, das Reich „reich“ = Freie Reichsgebiete) hat einen Zustand aus Indikatoren (ep_zustand, je gebuchtem Monat).
- Ein MODUL (Eintrag in MODULE) gehört zu einem oder mehreren Politikfeldern und besteht aus
    · Indikatoren: Zielwert aus der Erfüllung E = Anteil ÷ Richtwert der Politikfelder, mit Trägheit (der Wert nähert sich dem Ziel nur langsam);
    · Wirkungen: aus den (neuen) Indikatorwerten Effekte auf drei Hebel:
        bev_pp  = Bevölkerungswachstum in Prozentpunkten je Monat (wirkt kumulativ auf die Einwohnerzahl, Faktor bev_faktor),
        kopf_pct = BIP pro Kopf in Prozent (Niveaueffekt, Faktor kopf_faktor),
        zuf_pt  = Punkte auf den Zufriedenheitsindex (etatplan.zufriedenheit, Parameter extra).
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

def _wirk_gesundheit(z):
    g = z["gesundheit"]
    pp = 0.008 * (g - NEUTRAL)
    jahr = pp * 12
    return [{"hebel": "bev_pp", "wert": pp, "titel": "Gesundheitsniveau",
             "text": f'Bevölkerung {"wächst" if pp >= 0 else "schrumpft"} um {_de(abs(jahr))} % pro Jahr' if abs(jahr) >= 0.05 else "Bevölkerung unverändert"}]


def _wirk_bildung(z):
    b, a, h = z["bildung"], z["akademiker"], z["handwerk"]
    out = [{"hebel": "kopf_pct", "wert": _clamp(0.20 * (b - NEUTRAL), -8, 8), "titel": "Bildungsniveau",
            "text": "Qualifizierte Arbeitskräfte erhöhen die Wirtschaftsleistung pro Kopf" if b >= NEUTRAL else "Schlecht ausgebildete Arbeitskräfte drücken die Wirtschaftsleistung pro Kopf"}]
    if a > 38:
        out.append({"hebel": "kopf_pct", "wert": -min(8.0, 0.5 * (a - 38)), "titel": "Zu viele Akademiker",
                    "text": f"Akademikeranteil {_de(a)} %: Überqualifikation, die Wirtschaft braucht mehr Handwerk und Facharbeit"})
    elif a < 18:
        out.append({"hebel": "kopf_pct", "wert": -min(5.0, 0.35 * (18 - a)), "titel": "Zu wenige Akademiker",
                    "text": f"Akademikeranteil {_de(a)} %: es fehlen Forscher, Ärzte und Ingenieure, Innovation stockt"})
    if h < 38:
        out.append({"hebel": "kopf_pct", "wert": -min(6.0, 0.4 * (38 - h)), "titel": "Handwerkermangel",
                    "text": f"Nur {_de(h)} % Handwerker und Facharbeiter: Betriebe finden keine Fachkräfte"})
    if a > 40:
        out.append({"hebel": "zuf_pt", "wert": -min(3.0, 0.15 * (a - 40)), "titel": "Akademiker ohne Stelle",
                    "text": "Viele Hochqualifizierte finden keine passende Arbeit, das drückt die Stimmung"})
    return out


def _wirk_sicherheit(z):
    s, u = z["sicherheit"], z["ueberwachung"]
    out = []
    if s < 75:
        out.append({"hebel": "kopf_pct", "wert": -min(6.0, 0.12 * (75 - s)), "titel": "Hohe Kriminalität",
                    "text": "Kriminalität schreckt Investoren ab und verursacht Schäden"})
    elif s > NEUTRAL:
        out.append({"hebel": "kopf_pct", "wert": min(1.5, 0.06 * (s - NEUTRAL)), "titel": "Sichere Städte",
                    "text": "Sicherheit zieht Investitionen und Touristen an"})
    if u > 25:
        out.append({"hebel": "kopf_pct", "wert": -min(4.0, 0.07 * (u - 25)), "titel": "Überwachungsstaat",
                    "text": "Ein Klima der Kontrolle hemmt Gründungen, Forschung und Kultur"})
    if s < 60:
        out.append({"hebel": "zuf_pt", "wert": -min(8.0, 0.2 * (60 - s)), "titel": "Bürger fühlen sich unsicher",
                    "text": "Zu wenig Polizei und Justiz: die Bevölkerung fürchtet Verbrechen"})
    if u > 30:
        out.append({"hebel": "zuf_pt", "wert": -min(8.0, 0.18 * (u - 30)), "titel": "Bürger fühlen sich überwacht",
                    "text": "Zu viel Kontrolle: die Bevölkerung fühlt sich bevormundet und beobachtet"})
    return out


MODULE = [
    {"id": "gesundheit", "name": "Gesundheit und Bevölkerung", "icon": "users", "kategorien": ("gesundheit", "umwelt", "soziales"),
     "beschreibung": "Das Gesundheitsniveau (Gesundheitswesen 80 %, Umwelt 10 %, Arbeit und Soziales 10 %) bestimmt die Lebenserwartung und das "
                     "Bevölkerungswachstum. Mehr Einwohner bedeuten mehr Steueraufkommen und eine höhere Reichsabgabe.",
     "indikatoren": [
         {"id": "gesundheit", "name": "Gesundheitsniveau", "einheit": "Punkte", "start": NEUTRAL, "traeg": 0.18,
          "ziel": lambda E, z: 0.80 * _t(E, "gesundheit") + 0.10 * _t(E, "umwelt") + 0.10 * _t(E, "soziales")}],
     "wirkungen": _wirk_gesundheit},
    {"id": "bildung", "name": "Bildung und Arbeitsmarkt", "icon": "file-text", "kategorien": ("bildung", "forschung", "industrie"),
     "beschreibung": "Bildung (85 %) und Forschung (15 %) bestimmen das Bildungsniveau und damit das BIP pro Kopf. Die Bildungsausgaben legen auch fest, wie viele "
                     "Menschen studieren: zu viele Akademiker bedeuten zu wenige Handwerker und Facharbeiter (die Industrie fragt sie nach), zu wenige bremsen die Innovation.",
     "indikatoren": [
         {"id": "bildung", "name": "Bildungsniveau", "einheit": "Punkte", "start": NEUTRAL, "traeg": 0.10,
          "ziel": lambda E, z: 0.85 * _t(E, "bildung") + 0.15 * _t(E, "forschung")},
         {"id": "akademiker", "name": "Akademikeranteil", "einheit": "%", "start": 26.0, "traeg": 0.09,
          "ziel": lambda E, z: _clamp(8 + 18 * E.get("bildung", 1.0), 5, 60)},
         {"id": "handwerk", "name": "Handwerker und Facharbeiter", "einheit": "%", "start": 48.0, "traeg": 0.09,
          "ziel": lambda E, z: _clamp(48 - 0.7 * (z["akademiker"] - 26) + 8 * (E.get("industrie", 1.0) - 1), 10, 70)}],
     "wirkungen": _wirk_bildung},
    {"id": "sicherheit", "name": "Innere Sicherheit", "icon": "shield", "kategorien": ("innere_sicherheit", "soziales"),
     "beschreibung": "Innere Sicherheit (75 %) und Arbeit und Soziales (25 %) bestimmen das Sicherheitsgefühl und die Kriminalitätsrate. Zu wenig Sicherheit: die Bürger "
                     "fühlen sich unsicher. Weit über dem Richtwert wächst der Überwachungsgrad: die Bürger fühlen sich überwacht und bevormundet.",
     "indikatoren": [
         {"id": "sicherheit", "name": "Sicherheitsgefühl", "einheit": "Punkte", "start": NEUTRAL, "traeg": 0.25,
          "ziel": lambda E, z: 0.75 * _t(E, "innere_sicherheit") + 0.25 * _t(E, "soziales")},
         {"id": "ueberwachung", "name": "Überwachungsgrad", "einheit": "Punkte", "start": 0.0, "traeg": 0.30,
          "ziel": lambda E, z: _clamp(60 * (E.get("innere_sicherheit", 1.0) - 1.2), 0, 100)}],
     "wirkungen": _wirk_sicherheit},
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


def entwickeln(con, schl, anteile, richt, periode, kopf_ratio=1.0):
    """Zustand eines Haushalts im Monat `periode` bei dieser Verteilung. Rückgabe: {"zustand": {id: {alt, ziel, neu}}, "effekte": [...], "bev_pp", "bev_faktor",
    "kopf_pct", "kopf_faktor", "zuf_pt", "hdi", "lebenserwartung", "kriminalitaet"}."""
    E = erfuellung(anteile, richt)
    alt = zustand_vor(con, schl, periode)
    neu, zust = dict(alt), {}
    for m in MODULE:
        for i in m["indikatoren"]:
            ziel = i["ziel"](E, neu)
            n = alt[i["id"]] + (ziel - alt[i["id"]]) * i["traeg"]
            neu[i["id"]] = n
            zust[i["id"]] = {"alt": alt[i["id"]], "ziel": ziel, "neu": n}
    effekte = []
    for m in MODULE:
        for e in m["wirkungen"](neu):
            effekte.append(dict(e, modul=m["id"]))
    bev_pp = sum(e["wert"] for e in effekte if e["hebel"] == "bev_pp")
    kopf = _clamp(sum(e["wert"] for e in effekte if e["hebel"] == "kopf_pct"), *KOPF_GRENZEN)
    zuf = sum(e["wert"] for e in effekte if e["hebel"] == "zuf_pt")
    bev = _clamp(alt["bev_faktor"] * (1 + bev_pp / 100), *BEV_GRENZEN)
    einkommen = _clamp(70 + 25 * math.log2(max(0.05, kopf_ratio * (1 + kopf / 100))), 0, 100)
    hdi = (neu["gesundheit"] + neu["bildung"] + einkommen) / 300
    return {"zustand": zust, "effekte": effekte, "bev_pp": bev_pp, "bev_faktor": bev, "bev_faktor_alt": alt["bev_faktor"], "kopf_pct": kopf,
            "kopf_faktor": 1 + kopf / 100, "zuf_pt": zuf, "hdi": hdi, "lebenserwartung": 55 + 0.35 * neu["gesundheit"],
            "kriminalitaet": 3500 * math.exp((NEUTRAL - neu["sicherheit"]) / 40), "einkommen_index": einkommen}


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
        details["reich"] = entwickeln(con, "reich", liste[0]["plan_reich"], liste[0]["richt_reich"], periode, ratio)
    for x in liste:
        if x["reichsgebiet"] or not x.get("plan_land"):
            continue
        ratio = (x["bip"] / x["ew"] / ref) if x["ew"] else 1.0
        details["ts-" + x["staat"]] = entwickeln(con, "ts-" + x["staat"], x["plan_land"], x["richt_land"], periode, ratio)
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
        einheit = {"bev_pp": "% Bev. p. a.", "kopf_pct": "% BIP/Kopf", "zuf_pt": "Pkt. Zufriedenheit"}[e["hebel"]]
        wert = e["wert"] * (12 if e["hebel"] == "bev_pp" else 1)
        zeilen.append(f'<div class="{"plus" if e["wert"] > 0 else "minus"}"><b>{_vz(wert, einheit)}</b><span><em>{esc(e["titel"])}.</em> {esc(e["text"])}</span></div>')
    return f'<div class="en-effekte">{"".join(zeilen)}</div>' if zeilen else f'<p class="sa-hinweis">{esc(leer)}</p>'


def kurz_html(d, link=None):
    """Kurzfassung für die Etatseiten: die stärksten Wirkungen."""
    kz = (f'<b>HDI {_de(d["hdi"], 3)}</b> · Lebenserwartung {_de(d["lebenserwartung"], 0)} Jahre · Bevölkerung {_vz((d["bev_faktor"] - 1) * 100)} gegenüber der Karte'
          f' · BIP pro Kopf {_vz(d["kopf_pct"])}')
    return (f'<h2>{amt.ic("users")} Entwicklung</h2><p class="az">Langfristige Wirkung der Investitionen. {kz}.'
            + (f' <a href="{esc(link)}">Alle Einzelheiten →</a>' if link else "") + f'</p>{effekte_html(d)}')


def tabelle(liste, ziel_liste, pfad, markiert=""):
    """Öffentlich: HDI, Bevölkerungswachstum und Auffälligkeiten je Haushalt (ohne Beträge)."""
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
        zeilen.append((d["hdi"], f'<tr{" class=fokus" if s == markiert else ""}><td><a href="{pfad}?ziel={esc(s)}">{esc(n)}</a></td>'
                                 f'<td class="num">{_de(d["hdi"], 3)}</td><td class="num">{_vz(d["bev_pp"] * 12)}</td>'
                                 f'<td class="num">{esc(", ".join(flags)) if flags else "–"}</td></tr>'))
    return ('<p class="zf-meta">HDI aus Gesundheit, Bildung und Einkommen. Bevölkerungswachstum pro Jahr bei der heutigen Gesundheitsversorgung.</p>'
            '<table class="zf-tab"><thead><tr><th>Haushalt</th><th class="num">HDI</th><th class="num">Wachstum</th><th class="num">Auffällig</th></tr></thead><tbody>'
            + "".join(z for _, z in sorted(zeilen, key=lambda t: -t[0])) + '</tbody></table>')


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
    kz2 = [("Bevölkerung gegenüber der Karte", _vz((ew / ew0 - 1) * 100 if ew0 else 0)), ("BIP pro Kopf durch Investitionen", _vz(d["kopf_pct"])),
           ("Straftaten je 100.000 Einwohner", f'{d["kriminalitaet"]:,.0f}'.replace(",", ".")), ("Zufriedenheit", f'{_de(zuf["neu"], 0)} / 100')]
    kz_html = lambda xs: f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in xs)}</div>'
    module = "".join(
        f'<div class="en-modul"><h3>{amt.ic(m["icon"])}{esc(m["name"])}</h3><p>{esc(m["beschreibung"])}</p>'
        + "".join(_indikator_zeile(i, d["zustand"][i["id"]]) for i in m["indikatoren"])
        + effekte_html({"effekte": [e for e in d["effekte"] if e["modul"] == m["id"]]}, "Keine besondere Wirkung.") + '</div>' for m in MODULE)
    vl = verlauf(con, ziel)
    zeilen = [(sa._monatsname(p), _de(v.get("gesundheit", NEUTRAL)), _de(v.get("bildung", NEUTRAL)), _de(v.get("akademiker", 26)) + " %", _de(v.get("handwerk", 48)) + " %",
               _de(v.get("sicherheit", NEUTRAL)), _de(v.get("ueberwachung", 0)), _vz((v.get("bev_faktor", 1) - 1) * 100)) for p, v in reversed(vl)]
    gewaehlt = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(n)}</option>' for s, n in ziele)
    inhalt = (CSS + f'<h1>{amt.ic("users")} Entwicklung · {esc(name)}</h1>{amt.meldung(request)}'
              '<p class="az">Die Investitionen in die Politikfelder wirken langfristig auf Bevölkerung, Wirtschaft und Stimmung. Die Werte folgen der Etatverteilung nur '
              'allmählich: ein Monat mit hohen oder niedrigen Ausgaben ändert wenig, dauerhafte Weichenstellungen viel.</p>'
              f'<form class="sa-leiste" method="get"><div><label for="zl">Haushalt</label><select id="zl" name="ziel" onchange="this.form.submit()">{gewaehlt}</select></div></form>'
              + kz_html(kz) + kz_html(kz2) + f'<h2>Was gerade wirkt</h2>{effekte_html(d)}'
              + f'<h2>Die Bereiche im Einzelnen</h2><p class="sa-hinweis">Der Strich markiert den neutralen Wert bei der Vorgabe-Verteilung, der Pfeil die Richtung zum Zielwert.</p>{module}'
              + f'<details class="sa-auf"><summary>{amt.ic("clock")}Verlauf ({len(zeilen)} Monate)</summary>'
              + amt.tabelle(["Monat", "Gesundheit", "Bildung", "Akademiker", "Handwerker", "Sicherheit", "Überwachung", "Bevölkerung"], zeilen,
                            "Noch kein gebuchter Monat mit Entwicklung.", klasse="sa-haushalt") + '</details>'
              + f'<p><a href="{sa.PFAD}etatplanung/?ziel={esc(ziel)}">Etat planen →</a></p>')
    return sa.ant(request, k, "Entwicklung", "sa-entwicklung", inhalt)


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get(PFAD, seite)
