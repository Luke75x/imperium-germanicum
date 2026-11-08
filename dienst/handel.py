"""Handelssystem (/schatzamt/handel/): Reich und Teilstaaten verkaufen untereinander Waren aus den Ergebnissen ihres Etats.

Verkäuflich ist, was ein Etat tatsächlich hervorbringt (Kategorie → Waren):
  Gesundheitswesen → Arzneimittel, Impfstoffe, Medizintechnik, Spezialpharmazeutika
  Landwirtschaft   → Getreide, Obst und Gemüse, Fleisch, Milchprodukte, Ölsaaten, Zucker, Wein
  Industrie        → Rohstoffe (nur mit Vorkommen im eigenen Gebiet: Steinkohle, Braunkohle, Eisenerz, Bauxit, Kupfer, Erdöl, Erdgas, Salz,
                     Holz, Seltene Erden, Uran, Baustoffe) und veredelte Güter (Stahl, Aluminium, Treibstoff – aus Rohstoffen im Lager)
  Forschung        → Baupläne für Militärgerät, wenn Forschung es im eigenen Land günstiger gemacht hat (entwicklung.ruestung_faktor < 1);
                     der Käufer baut danach zum selben Preisfaktor (hd_lizenzen, verteidigung.beschaffen)
  Verteidigung     → Militärgerät aus dem eigenen Bestand (vt_bestand), nie mehr, als man besitzt
Nicht verkäuflich: Kultur, Innere Sicherheit, Arbeit und Soziales, Transportwesen, Bildung, Umwelt, Infrastruktur.

Erzeugung: Jeden Haushaltsmonat fließt ein Überschussanteil des jeweiligen Sektor-Etats (Einstellung „handel“: ueberschuss_*) in verkaufbare Waren
(`produktion`, einmal je Monat, Tabelle hd_produktion/hd_laeufe). Rohstoffe: Anteil des Industrie-Überschusses nach Reichhaltigkeit des Vorkommens
(hd_vorkommen, 0–100; 0 = keins, dann weder Förderung noch Verkauf als Rohstoff). Die Ware kommt ins Lager (hd_lager), verderbliche Ware verliert
monatlich einen Teil (hd_waren.verderb).
Markt: Angebote (hd_angebote) mit Preisgrenzen um den Richtpreis; die Ware ist beim Einstellen reserviert. Kauf = Zahlung von Kasse zu Kasse
(Staatskasse bzw. Reichskasse; Militär und Baupläne: Verteidigungskassen), Buchungsart „handel“, keine Überziehung. Jedes Geschäft steht im Handelsbuch
(hd_geschaefte). Handelssperren (hd_sperren) verhängt die Leitung des Schatzamts. Rechte wie beim Etat: Landesherr für den Teilstaat,
Schatzamt-Leitung für das Reich (etatplan.darf_aendern).
"""
import asyncio
import logging
import math
import time
from datetime import date

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark

esc = amt.esc
log = logging.getLogger("handel")
PFAD = sa.PFAD + "handel/"

amt.ICONS.setdefault("package", '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/>'
                                    '<path d="M12 22V12"/><path d="m3.29 7 8.71 5 8.71-5"/><path d="m7.5 4.27 9 5.15"/>')

geld.VORGABEN.setdefault("handel", {"ueberschuss_gesundheit": 5, "ueberschuss_landwirtschaft": 25, "ueberschuss_industrie": 20,
                                    "preis_min": 40, "preis_max": 250, "veredelung_kosten": 10})

SEKTOREN = [("gesundheit", "Gesundheit", "Arzneimittel und Medizintechnik"), ("landwirtschaft", "Landwirtschaft", "Lebensmittel"),
            ("industrie", "Industrie", "Rohstoffe und Industriegüter"), ("forschung", "Forschung", "Baupläne für Militärgerät"),
            ("verteidigung", "Militärgerät", "Gerät aus dem eigenen Bestand")]
SEKTORNAME = {s: n for s, n, _ in SEKTOREN}
NICHT_HANDELBAR = [("Kultur", "Kulturgüter und Ansehen lassen sich nicht liefern."), ("Innere Sicherheit", "Polizei und Justiz sind hoheitlich."),
                   ("Arbeit und Soziales", "Sozialleistungen sind kein Handelsgut."), ("Transportwesen", "Verkehrswege bleiben im Land."),
                   ("Bildung", "Bildung wirkt nur im eigenen Land."), ("Umwelt", "Umweltleistungen sind nicht übertragbar."),
                   ("Infrastruktur", "Wasser, Müll, Straßen und Brücken sind ortsgebunden.")]

# Rohstoffe: (Schlüssel, Name)
RESSOURCEN = [("steinkohle", "Steinkohle"), ("braunkohle", "Braunkohle"), ("eisenerz", "Eisenerz"), ("bauxit", "Bauxit"), ("kupfer", "Kupfererz"),
              ("erdoel", "Erdöl"), ("erdgas", "Erdgas"), ("salz", "Salz und Kali"), ("holz", "Holz"), ("seltene", "Seltene Erden und Lithium"),
              ("uran", "Uranerz"), ("stein", "Baustoffe")]
RESNAME = dict(RESSOURCEN)

# Waren: (Schlüssel, Name, Sektor, Einheit, Richtpreis in €, Anteil am Sektor-Überschuss %, Rohstoff, Verderb % je Monat)
WAREN = [
    ("arzneimittel", "Arzneimittel (Standardpräparate)", "gesundheit", "1.000 Packungen", 10000, 45, None, 3),
    ("impfstoffe", "Impfstoffe", "gesundheit", "1.000 Dosen", 25000, 20, None, 8),
    ("medtechnik", "Medizintechnik und Verbandsmaterial", "gesundheit", "Palette", 4000, 25, None, 0),
    ("spezialpharma", "Spezialpharmazeutika", "gesundheit", "100 Packungen", 60000, 10, None, 5),
    ("getreide", "Getreide", "landwirtschaft", "t", 250, 28, None, 1),
    ("gemuese", "Obst und Gemüse", "landwirtschaft", "t", 800, 20, None, 25),
    ("fleisch", "Fleisch und Wurstwaren", "landwirtschaft", "t", 3500, 20, None, 15),
    ("milch", "Milchprodukte", "landwirtschaft", "t", 900, 15, None, 30),
    ("oelsaaten", "Ölsaaten und Pflanzenöl", "landwirtschaft", "t", 600, 7, None, 2),
    ("zucker", "Zucker", "landwirtschaft", "t", 650, 5, None, 0),
    ("wein", "Wein", "landwirtschaft", "1.000 l", 2500, 5, None, 0),
    ("steinkohle", "Steinkohle", "industrie", "t", 110, 0, "steinkohle", 0),
    ("braunkohle", "Braunkohle", "industrie", "t", 60, 0, "braunkohle", 0),
    ("eisenerz", "Eisenerz", "industrie", "t", 110, 0, "eisenerz", 0),
    ("bauxit", "Bauxit", "industrie", "t", 55, 0, "bauxit", 0),
    ("kupfer", "Kupferkonzentrat", "industrie", "t", 4500, 0, "kupfer", 0),
    ("erdoel", "Erdöl", "industrie", "t", 550, 0, "erdoel", 0),
    ("erdgas", "Erdgas", "industrie", "1.000 m³", 350, 0, "erdgas", 0),
    ("salz", "Salz und Kali", "industrie", "t", 90, 0, "salz", 0),
    ("holz", "Rundholz", "industrie", "Festmeter", 90, 0, "holz", 0),
    ("seltene", "Seltene Erden und Lithium", "industrie", "t", 20000, 0, "seltene", 0),
    ("uran", "Uran-Konzentrat", "industrie", "t", 65000, 0, "uran", 0),
    ("stein", "Baustoffe (Kies, Kalk, Naturstein)", "industrie", "t", 15, 0, "stein", 0),
    ("stahl", "Stahl", "industrie", "t", 750, 0, None, 0),
    ("aluminium", "Aluminium", "industrie", "t", 2400, 0, None, 0),
    ("treibstoff", "Treibstoff (Diesel und Benzin)", "industrie", "t", 900, 0, None, 0),
]
# Veredelung: Erzeugnis → {Einsatzstoff: Menge je Tonne Erzeugnis}
REZEPTE = {"stahl": {"eisenerz": 1.6, "steinkohle": 0.7}, "aluminium": {"bauxit": 4.0}, "treibstoff": {"erdoel": 1.1}}

# Erste Annahme der Vorkommen (grob nach der Geologie der Regionen), 0–100; die Leitung kann sie unter „Ressourcen“ ändern.
VORKOMMEN = {
    "s1": {"erdgas": 25, "erdoel": 15, "salz": 55, "holz": 70, "stein": 80},
    "s2": {"steinkohle": 60, "braunkohle": 50, "eisenerz": 55, "kupfer": 30, "erdgas": 40, "salz": 50, "holz": 70, "stein": 60, "seltene": 15},
    "s3": {"erdgas": 35, "erdoel": 20, "salz": 30, "stein": 10},
    "s4": {"holz": 30, "stein": 50},
    "s5": {"eisenerz": 25, "holz": 55, "stein": 60},
    "s6": {"erdoel": 45, "erdgas": 30, "salz": 45, "stein": 20, "holz": 10},
    "s7": {"erdgas": 30, "salz": 40, "holz": 20, "stein": 40},
    "s8": {"eisenerz": 25, "erdoel": 5, "salz": 60, "holz": 60, "stein": 70},
    "s9": {"stein": 5},
    "s10": {"kupfer": 40, "eisenerz": 45, "erdgas": 5, "salz": 55, "holz": 80, "seltene": 35, "stein": 60},
    "s11": {"bauxit": 70, "erdoel": 10, "erdgas": 20, "salz": 70, "holz": 5, "stein": 85},
    "s12": {"steinkohle": 40, "braunkohle": 80, "eisenerz": 30, "kupfer": 15, "salz": 0, "holz": 60, "seltene": 45, "uran": 60, "stein": 55},
    "s13": {"steinkohle": 5, "braunkohle": 30, "eisenerz": 50, "erdoel": 50, "erdgas": 75, "salz": 85, "holz": 40, "stein": 45},
    "s14": {"eisenerz": 5, "salz": 60, "holz": 55, "stein": 70},
    "s15": {"braunkohle": 95, "kupfer": 25, "holz": 40, "seltene": 25, "stein": 25},
    "s16": {"steinkohle": 85, "eisenerz": 30, "erdoel": 25, "erdgas": 30, "holz": 55, "uran": 20, "stein": 55},
    "s17": {"stein": 10},
    "s18": {"salz": 10, "holz": 20, "stein": 15},
    "s19": {"steinkohle": 25, "braunkohle": 40, "eisenerz": 30, "salz": 20, "holz": 55, "stein": 80},
    "s20": {"erdoel": 25, "erdgas": 15, "salz": 35, "holz": 70, "seltene": 30, "stein": 60},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS hd_waren (schl TEXT PRIMARY KEY, name TEXT NOT NULL, sektor TEXT NOT NULL, einheit TEXT NOT NULL, preis INTEGER NOT NULL,
    anteil REAL NOT NULL DEFAULT 0, ressource TEXT, verderb REAL NOT NULL DEFAULT 0, aktiv INTEGER NOT NULL DEFAULT 1, rang INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS hd_vorkommen (schl TEXT NOT NULL, ressource TEXT NOT NULL, wert INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (schl, ressource));
CREATE TABLE IF NOT EXISTS hd_lager (schl TEXT NOT NULL, ware TEXT NOT NULL, menge INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (schl, ware));
CREATE TABLE IF NOT EXISTS hd_angebote (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, anbieter TEXT NOT NULL, ware TEXT NOT NULL,
    menge INTEGER NOT NULL, preis INTEGER NOT NULL, bereit REAL NOT NULL DEFAULT 100, unbegrenzt INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'offen', autor_name TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS hd_angebote_s ON hd_angebote (status, ware);
CREATE TABLE IF NOT EXISTS hd_geschaefte (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, ware TEXT NOT NULL, menge INTEGER NOT NULL,
    preis INTEGER NOT NULL, summe INTEGER NOT NULL, verkaeufer TEXT NOT NULL, kaeufer TEXT NOT NULL, autor_name TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS hd_lizenzen (schl TEXT NOT NULL, typ TEXT NOT NULL, faktor REAL NOT NULL, von TEXT NOT NULL, zeit INTEGER NOT NULL,
    preis INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (schl, typ));
CREATE TABLE IF NOT EXISTS hd_produktion (periode TEXT NOT NULL, schl TEXT NOT NULL, ware TEXT NOT NULL, menge INTEGER NOT NULL, PRIMARY KEY (periode, schl, ware));
CREATE TABLE IF NOT EXISTS hd_laeufe (periode TEXT PRIMARY KEY, zeit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS hd_sperren (schl TEXT PRIMARY KEY, zeit INTEGER NOT NULL, grund TEXT NOT NULL DEFAULT '', von TEXT NOT NULL DEFAULT '');
"""


def einrichten(con):
    con.executescript(SCHEMA)
    kurs = geld.wechselkurs(con)
    for i, (s, n, sek, einheit, eur, anteil, res, verderb) in enumerate(WAREN):
        con.execute("INSERT OR IGNORE INTO hd_waren (schl, name, sektor, einheit, preis, anteil, ressource, verderb, rang) VALUES (?,?,?,?,?,?,?,?,?)",
                    (s, n, sek, einheit, max(1, int(round(eur * 100 / kurs))), anteil, res, verderb, i))
        con.execute("UPDATE hd_waren SET rang=? WHERE schl=?", (i, s))
    for sid, werte in VORKOMMEN.items():
        for res, _ in RESSOURCEN:
            con.execute("INSERT OR IGNORE INTO hd_vorkommen (schl, ressource, wert) VALUES (?,?,?)",
                        ("reich" if sid == "s2" else "ts-" + sid, res, werte.get(res, 0)))
    con.commit()


def einstellungen(con):
    return dict(geld.VORGABEN["handel"], **geld.einstellung(con, "handel"))


# ---------------------------------------------------------------- Halter, Rechte, Kassen

def halter(con):
    """{schl: Name}: das Reich und alle Teilstaaten der aktuellen Karte (ohne Freie Reichsgebiete)."""
    import karte
    import landespolizei
    out = {"reich": "Das Reich"}
    for s in karte.aktuell(con)["stand"]["staaten"]:
        if not geld.ist_reichsgebiet(s):
            out["ts-" + s["id"]] = landespolizei._kurzname(s["name"])
    return out


def darf(con, k, schl):
    import etatplan
    return etatplan.darf_aendern(con, k, schl)


def meine_halter(con, k):
    return [s for s in halter(con) if darf(con, k, s)]


def kasse(con, schl):
    return geld.stellenkonto(con, "reichskasse" if schl == "reich" else schl)


def vt_stelle(schl):
    return "verteidigung" if schl == "reich" else "vt-" + schl[3:]


def vt_schl(stelle):
    return "reich" if stelle == "verteidigung" else "ts-" + stelle[3:]


def sperre(con, schl):
    return con.execute("SELECT * FROM hd_sperren WHERE schl=?", (schl,)).fetchone()


def verwalter(k):
    return geld.ist_leitung(k) or sa.ist_rp(k)


# ---------------------------------------------------------------- Waren, Lager, Preise

def waren(con, nur_aktiv=False):
    return {r["schl"]: r for r in con.execute("SELECT * FROM hd_waren" + (" WHERE aktiv=1" if nur_aktiv else "") + " ORDER BY rang")}


def vorkommen(con, schl):
    return {r["ressource"]: r["wert"] for r in con.execute("SELECT ressource, wert FROM hd_vorkommen WHERE schl=?", (schl,))}


def lager(con, schl):
    return {r["ware"]: r["menge"] for r in con.execute("SELECT ware, menge FROM hd_lager WHERE schl=? AND menge>0", (schl,))}


def lager_aendern(con, schl, ware, delta):
    con.execute("INSERT INTO hd_lager (schl, ware, menge) VALUES (?,?,?) ON CONFLICT(schl, ware) DO UPDATE SET menge=menge+?", (schl, ware, max(delta, 0), delta))
    if con.execute("SELECT menge FROM hd_lager WHERE schl=? AND ware=?", (schl, ware)).fetchone()["menge"] < 0:
        raise geld.Fehler("So viel ist nicht im Lager.")


def zahl(n):
    return f"{int(n):,}".replace(",", ".")


def katalog_vt(con):
    import verteidigung
    return verteidigung.katalog(con)


def info(con, ware, w=None, kat=None):
    """(Name, Einheit, Sektor) einer Ware oder eines virtuellen Guts ('mil:<typ>' Militärgerät, 'plan:<typ>' Bauplan)."""
    if ware.startswith("mil:") or ware.startswith("plan:"):
        kat = kat if kat is not None else katalog_vt(con)
        t = kat.get(ware.split(":", 1)[1])
        n = t["name"] if t else "?"
        return (n, "Stück", "verteidigung") if ware.startswith("mil:") else ("Bauplan: " + n, "Lizenz", "forschung")
    w = w if w is not None else waren(con)
    r = w.get(ware)
    return (r["name"], r["einheit"], r["sektor"]) if r else ("?", "", "")


PLAN_STUECK = ((100e6, 40), (1e9, 15), (float("inf"), 5))   # typische Abnahmemenge je Bauplan nach Preisklasse (Preis in €)


def plan_preis(con, typ, faktor):
    """Richtpreis eines Bauplans: Ersparnis je Stück × typische Abnahmemenge."""
    t = katalog_vt(con).get(typ)
    if not t:
        return 0
    eur = t["preis"] * geld.wechselkurs(con) / 100
    n = next(n for grenze, n in PLAN_STUECK if eur < grenze)
    return max(1, int(round(t["preis"] * (1 - faktor) * n)))


def richtpreis(con, ware, bereit=100.0, faktor=1.0):
    if ware.startswith("mil:"):
        t = katalog_vt(con).get(ware[4:])
        return max(1, int(round(t["preis"] * bereit / 100))) if t else 0
    if ware.startswith("plan:"):
        return plan_preis(con, ware[5:], faktor)
    r = waren(con).get(ware)
    return r["preis"] if r else 0


def lizenz_faktor(con, stelle, typ, eigen):
    """Preisfaktor für Militärgerät `typ` der Verteidigungskasse `stelle`: eigene Forschung oder gekaufter Bauplan, je nachdem was günstiger ist."""
    r = con.execute("SELECT faktor FROM hd_lizenzen WHERE schl=? AND typ=?", (vt_schl(stelle), typ)).fetchone()
    return min(eigen, r["faktor"]) if r else eigen


def eigener_faktor(con, schl):
    import entwicklung
    return entwicklung.ruestung_faktor(con, vt_stelle(schl))


# ---------------------------------------------------------------- Erzeugung

def kapazitaeten(con, periode):
    """{schl: {Ware: Menge}}: was Etat und Vorkommen in diesem Haushaltsmonat hervorbringen."""
    import aufkommen
    ver = {}
    reich = {}
    for x in aufkommen.berechnen(con, periode=periode):
        for kat, b in (x.get("verteilung_reich") or {}).items():
            reich[kat] = reich.get(kat, 0) + int(b)
        if not x.get("reichsgebiet") and x.get("verteilung_land"):
            ver["ts-" + x["staat"]] = {kat: int(b) for kat, b in x["verteilung_land"].items()}
    ver["reich"] = reich
    e = einstellungen(con)
    ws = waren(con, True)
    out = {}
    for schl in halter(con):
        v = ver.get(schl, {})
        vk = vorkommen(con, schl)
        summe = max(sum(vk.values()), 300)
        ind = v.get("industrie", 0) * float(e["ueberschuss_industrie"]) / 100
        o = {}
        for w in ws.values():
            if w["ressource"]:
                wert = ind * vk.get(w["ressource"], 0) / summe
            elif w["sektor"] in ("gesundheit", "landwirtschaft"):
                wert = v.get(w["sektor"], 0) * float(e["ueberschuss_" + w["sektor"]]) / 100 * w["anteil"] / 100
            else:
                continue
            n = int(wert // max(w["preis"], 1))
            if n > 0:
                o[w["schl"]] = n
        out[schl] = o
    return out


def produktion(con, periode):
    """Bucht die Erzeugung eines Haushaltsmonats ins Lager (einmal je Monat); verderbliche Ware im Lager verliert vorher ihren Anteil."""
    if con.execute("SELECT 1 FROM hd_laeufe WHERE periode=?", (periode,)).fetchone():
        return False
    kap = kapazitaeten(con, periode)
    ws = waren(con)
    for r in con.execute("SELECT schl, ware, menge FROM hd_lager WHERE menge>0").fetchall():
        w = ws.get(r["ware"])
        if w and w["verderb"] > 0:
            con.execute("UPDATE hd_lager SET menge=menge-? WHERE schl=? AND ware=?", (int(r["menge"] * w["verderb"] / 100), r["schl"], r["ware"]))
    for schl, o in kap.items():
        for ware, n in o.items():
            lager_aendern(con, schl, ware, n)
            con.execute("INSERT OR REPLACE INTO hd_produktion (periode, schl, ware, menge) VALUES (?,?,?,?)", (periode, schl, ware, n))
    con.execute("INSERT INTO hd_laeufe (periode, zeit) VALUES (?,?)", (periode, int(time.time())))
    geld.protokoll(con, None, "Handel: Erzeugung gebucht", f"Haushaltsmonat {periode}")
    con.commit()
    return True


def letzte_produktion(con, schl):
    r = con.execute("SELECT MAX(periode) p FROM hd_produktion WHERE schl=?", (schl,)).fetchone()
    p = r["p"] if r else None
    if not p:
        return None, {}
    return p, {x["ware"]: x["menge"] for x in con.execute("SELECT ware, menge FROM hd_produktion WHERE schl=? AND periode=?", (schl, p))}


async def automatik(app):
    await asyncio.sleep(120)
    while True:
        try:
            con = app["db"]
            m = date.today().strftime("%Y-%m")
            if con.execute("SELECT 1 FROM ak_laeufe WHERE periode=?", (m,)).fetchone():
                if produktion(con, m):
                    log.info("Handel: Erzeugung %s gebucht", m)
        except Exception:
            log.exception("Handel: Erzeugung fehlgeschlagen")
        await asyncio.sleep(1800)


# ---------------------------------------------------------------- Handel

def _grenzen(con, richt):
    e = einstellungen(con)
    return max(1, int(richt * float(e["preis_min"]) / 100)), max(1, int(richt * float(e["preis_max"]) / 100))


def _pruefe_handel(con, schl):
    s = sperre(con, schl)
    if s:
        raise geld.Fehler(f'Gegen {halter(con).get(schl, schl)} besteht eine Handelssperre' + (f': {s["grund"]}' if s["grund"] else "."))


def anbieten(con, schl, ware, menge, preis, k):
    """Stellt Ware (Lager), Militärgerät (Bestand) oder einen Bauplan ein. Ware und Gerät sind ab jetzt reserviert."""
    _pruefe_handel(con, schl)
    if preis < 1:
        raise geld.Fehler("Bitte einen Preis angeben.")
    bereit, unbegrenzt = 100.0, 0
    if ware.startswith("mil:"):
        typ = ware[4:]
        t = katalog_vt(con).get(typ)
        if not t or t["kategorie"] == "Infrastruktur":
            raise geld.Fehler("Dieses Gerät kann nicht verkauft werden (Liegenschaften bleiben im Land).")
        r = con.execute("SELECT * FROM vt_bestand WHERE stelle=? AND typ=?", (vt_stelle(schl), typ)).fetchone()
        if not r or r["anzahl"] < menge or menge < 1:
            raise geld.Fehler(f'Im Bestand sind nur {r["anzahl"] if r else 0} × {t["name"]} vorhanden – verkauft werden kann nur, was Sie besitzen.')
        bereit = float(r["bereitschaft"])
        richt = richtpreis(con, ware, bereit)
        con.execute("UPDATE vt_bestand SET anzahl=anzahl-? WHERE stelle=? AND typ=?", (menge, vt_stelle(schl), typ))
    elif ware.startswith("plan:"):
        typ = ware[5:]
        t = katalog_vt(con).get(typ)
        if not t or t["kategorie"] == "Infrastruktur":
            raise geld.Fehler("Für dieses Gut gibt es keinen Bauplan.")
        f = eigener_faktor(con, schl)
        if f > 0.99:
            raise geld.Fehler("Ein Bauplan ist nur verkäuflich, wenn die eigene Forschung das Gerät mindestens 1 % günstiger gemacht hat "
                              f"(derzeit {(f - 1) * 100:+.1f} %).".replace(".", ","))
        if con.execute("SELECT 1 FROM hd_angebote WHERE anbieter=? AND ware=? AND status='offen'", (schl, ware)).fetchone():
            raise geld.Fehler("Dieser Bauplan wird bereits angeboten.")
        richt, menge, unbegrenzt = richtpreis(con, ware, faktor=f), 1, 1
    else:
        w = waren(con, True).get(ware)
        if not w:
            raise geld.Fehler("Unbekannte Ware.")
        if w["ressource"] and vorkommen(con, schl).get(w["ressource"], 0) <= 0:
            raise geld.Fehler(f'{w["name"]} kann nur verkaufen, wer im eigenen Gebiet ein Vorkommen hat – dieses Gebiet hat keins.')
        if menge < 1:
            raise geld.Fehler("Bitte eine Menge angeben.")
        lager_aendern(con, schl, ware, -menge)
        richt = w["preis"]
    lo, hi = _grenzen(con, richt)
    if not lo <= preis <= hi:
        raise geld.Fehler(f"Der Preis muss zwischen {mark(lo)} und {mark(hi)} liegen (Richtpreis {mark(richt)}).")
    cur = con.execute("INSERT INTO hd_angebote (zeit, anbieter, ware, menge, preis, bereit, unbegrenzt, autor_name) VALUES (?,?,?,?,?,?,?,?)",
                      (int(time.time()), schl, ware, menge, preis, bereit, unbegrenzt, k["name"]))
    n = info(con, ware)[0]
    geld.protokoll(con, k, "Handel: Angebot", f'{halter(con).get(schl)}: {menge} × {n} zu {mark(preis)}')
    return cur.lastrowid


def zurueckziehen(con, angebot, schl, k):
    a = con.execute("SELECT * FROM hd_angebote WHERE id=? AND status='offen'", (angebot,)).fetchone()
    if not a or a["anbieter"] != schl:
        raise geld.Fehler("Angebot nicht gefunden.")
    if a["ware"].startswith("mil:"):
        _bestand_zufuegen(con, vt_stelle(schl), a["ware"][4:], a["menge"], a["bereit"])
    elif not a["ware"].startswith("plan:"):
        lager_aendern(con, schl, a["ware"], a["menge"])
    con.execute("UPDATE hd_angebote SET status='zurueck', menge=0 WHERE id=?", (angebot,))
    geld.protokoll(con, k, "Handel: Angebot zurückgezogen", f'{halter(con).get(schl)}: Angebot {angebot}')


def _bestand_zufuegen(con, stelle, typ, anzahl, bereit):
    alt = con.execute("SELECT * FROM vt_bestand WHERE stelle=? AND typ=?", (stelle, typ)).fetchone()
    n0, b0 = (alt["anzahl"], alt["bereitschaft"]) if alt else (0, 100.0)
    b = (n0 * b0 + anzahl * bereit) / (n0 + anzahl)
    con.execute("INSERT INTO vt_bestand (stelle, typ, anzahl, bereitschaft) VALUES (?,?,?,?) ON CONFLICT(stelle, typ) DO UPDATE SET "
                "anzahl=excluded.anzahl, bereitschaft=excluded.bereitschaft", (stelle, typ, n0 + anzahl, round(b, 2)))


def kaufen(con, angebot, kaeufer, menge, k):
    """Kauft `menge` aus Angebot `angebot` für den Halter `kaeufer`. Gibt (Summe, Beschreibung) zurück."""
    a = con.execute("SELECT * FROM hd_angebote WHERE id=? AND status='offen'", (angebot,)).fetchone()
    if not a:
        raise geld.Fehler("Das Angebot ist nicht mehr verfügbar.")
    verk = a["anbieter"]
    if verk == kaeufer:
        raise geld.Fehler("Eigene Angebote kann man nicht kaufen.")
    _pruefe_handel(con, kaeufer)
    _pruefe_handel(con, verk)
    ware = a["ware"]
    name = info(con, ware)[0]
    if a["unbegrenzt"]:
        menge = 1
    if not 1 <= menge <= a["menge"]:
        raise geld.Fehler(f'Bitte eine Menge zwischen 1 und {zahl(a["menge"])} angeben.')
    summe = menge * a["preis"]
    militaer = ware.startswith(("mil:", "plan:"))
    von = geld.stellenkonto(con, vt_stelle(kaeufer)) if militaer else kasse(con, kaeufer)
    an = geld.stellenkonto(con, vt_stelle(verk)) if militaer else kasse(con, verk)
    if not von or not an:
        raise geld.Fehler("Kasse nicht gefunden.")
    if von["saldo"] < summe:
        raise geld.Fehler(f'Die {von["name"]} ist nicht gedeckt: benötigt {mark(summe)}, vorhanden {mark(von["saldo"])}.')
    if ware.startswith("plan:"):
        typ = ware[5:]
        f = eigener_faktor(con, verk)
        if f > 0.99:
            raise geld.Fehler("Der Anbieter kann diesen Bauplan nicht mehr liefern (seine Forschungsvorteile sind weggefallen).")
        if lizenz_faktor(con, vt_stelle(kaeufer), typ, eigener_faktor(con, kaeufer)) <= f + 1e-9:
            raise geld.Fehler("Die eigene Fertigung ist bereits mindestens so günstig – der Bauplan brächte nichts.")
    bid = geld.buchen(con, von["id"], an["id"], summe, "handel", f'Handel: {menge} × {name}', k, bezug=f"HANDEL-{angebot}")
    if ware.startswith("mil:"):
        _bestand_zufuegen(con, vt_stelle(kaeufer), ware[4:], menge, a["bereit"])
    elif ware.startswith("plan:"):
        con.execute("INSERT INTO hd_lizenzen (schl, typ, faktor, von, zeit, preis) VALUES (?,?,?,?,?,?) ON CONFLICT(schl, typ) DO UPDATE SET "
                    "faktor=excluded.faktor, von=excluded.von, zeit=excluded.zeit, preis=excluded.preis", (kaeufer, typ, f, verk, int(time.time()), summe))
    else:
        lager_aendern(con, kaeufer, ware, menge)
    if not a["unbegrenzt"]:
        rest = a["menge"] - menge
        con.execute("UPDATE hd_angebote SET menge=?, status=? WHERE id=?", (rest, "offen" if rest else "verkauft", angebot))
    con.execute("INSERT INTO hd_geschaefte (zeit, ware, menge, preis, summe, verkaeufer, kaeufer, autor_name) VALUES (?,?,?,?,?,?,?,?)",
                (int(time.time()), ware, menge, a["preis"], summe, verk, kaeufer, k["name"]))
    h = halter(con)
    geld.protokoll(con, k, "Handel: Kauf", f'{h.get(kaeufer)} kauft von {h.get(verk)}: {menge} × {name} für {mark(summe)} (Buchung {bid})')
    return summe, name


def veredeln(con, schl, produkt, menge, k):
    rez = REZEPTE.get(produkt)
    w = waren(con, True).get(produkt)
    if not rez or not w or menge < 1:
        raise geld.Fehler("Bitte ein Erzeugnis und eine Menge angeben.")
    _pruefe_handel(con, schl)
    e = einstellungen(con)
    kosten = int(round(menge * w["preis"] * float(e["veredelung_kosten"]) / 100))
    kc = kasse(con, schl)
    if kosten > 0:
        if kc["saldo"] < kosten:
            raise geld.Fehler(f'Die {kc["name"]} ist nicht gedeckt: Energie und Löhne kosten {mark(kosten)}.')
        geld.buchen(con, kc["id"], geld.sonder(con, "volkswirtschaft")["id"], kosten, "handel", f'Veredelung: {menge} × {w["name"]}', k, bezug="VEREDELUNG")
    ws = waren(con)
    for stoff, je in rez.items():
        need = int(math.ceil(menge * je))
        try:
            lager_aendern(con, schl, stoff, -need)
        except geld.Fehler:
            raise geld.Fehler(f'Für {menge} {w["einheit"]} {w["name"]} fehlen {ws[stoff]["name"]} (benötigt {zahl(need)} {ws[stoff]["einheit"]}).')
    lager_aendern(con, schl, produkt, menge)
    geld.protokoll(con, k, "Handel: Veredelung", f'{halter(con).get(schl)}: {menge} × {w["name"]}, Kosten {mark(kosten)}')
    return kosten


# ---------------------------------------------------------------- Anzeige

CSS = """<style>
.hd-chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.hd-chips a{border:1px solid var(--linie);border-radius:999px;padding:4px 12px;font-size:13px;text-decoration:none;color:inherit}
.hd-chips a.aktiv{background:#111;color:#fff;border-color:#111}
.hd-matrix{overflow-x:auto}
.hd-matrix table{border-collapse:collapse;font-size:13px;min-width:900px}
.hd-matrix th,.hd-matrix td{border:1px solid var(--linie);padding:4px 7px;text-align:center}
.hd-matrix td:first-child,.hd-matrix th:first-child{text-align:left;position:sticky;left:0;background:#fff}
.hd-matrix td.n0{color:#aaa}
.hd-form{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin:6px 0 14px}
.hd-form label{display:block;font-size:12px;color:#666}
.hd-form input[type=number],.hd-form input[type=text]{width:130px}
.hd-form select{max-width:280px}
</style>"""


def _tabs(aktiv, ziel=""):
    z = f"?ziel={esc(ziel)}" if ziel else ""
    eintraege = [("markt", "Marktplatz", PFAD + z), ("mein", "Mein Handel", PFAD + "mein/" + z), ("ressourcen", "Ressourcen", PFAD + "ressourcen/"),
                 ("buch", "Handelsbuch", PFAD + "buch/"), ("regeln", "Waren & Regeln", PFAD + "regeln/")]
    return ('<nav class="reiter" aria-label="Handel">' + "".join(f'<a href="{u}"{" class=aktiv aria-current=page" if t == aktiv else ""}>{n}</a>' for t, n, u in eintraege) + "</nav>")


def _seite(request, k, titel, tab, inhalt, ziel=""):
    return sa.ant(request, k, titel, "sa-handel", CSS + f'<h1>{amt.ic("package")} Handel</h1>' + _tabs(tab, ziel) + amt.meldung(request) + inhalt)


def _ziel(con, k, request):
    """(Liste meiner Halter, gewählter Halter oder None)."""
    mine = meine_halter(con, k)
    z = request.query.get("ziel", "")
    return mine, (z if z in mine else (mine[0] if mine else None))


def _wahl(request, mine, ziel, pfad, namen):
    if len(mine) < 2:
        return f'<p class="sa-hinweis">Sie handeln für <b>{esc(namen.get(ziel, ""))}</b>.</p>' if ziel else ""
    opt = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(namen.get(s, s))}</option>' for s in mine)
    return (f'<form method="get" action="{pfad}" class="hd-form"><div><label for="hz">Ich handle für</label><select id="hz" name="ziel" onchange="this.form.submit()">{opt}</select></div></form>')


def _pk(p):
    return mark(p)


@sa.seite("staat")
async def markt(request, k):
    con = request.app["db"]
    namen = halter(con)
    mine, ziel = _ziel(con, k, request)
    sek = request.query.get("sektor", "")
    ws, kat = waren(con), katalog_vt(con)
    chips = ('<div class="hd-chips">' + f'<a href="{PFAD}?ziel={esc(ziel or "")}"{" class=aktiv" if not sek else ""}>Alle</a>'
             + "".join(f'<a href="{PFAD}?sektor={s}&ziel={esc(ziel or "")}"{" class=aktiv" if sek == s else ""}>{esc(n)}</a>' for s, n, _ in SEKTOREN) + "</div>")
    c = amt.csrf_feld(request)
    zeilen = []
    for a in con.execute("SELECT * FROM hd_angebote WHERE status='offen' ORDER BY ware, preis").fetchall():
        name, einheit, s_ = info(con, a["ware"], ws, kat)
        if sek and s_ != sek:
            continue
        richt = richtpreis(con, a["ware"], a["bereit"], eigener_faktor(con, a["anbieter"])) or 1
        abw = (a["preis"] / richt - 1) * 100
        kauf = "–"
        if ziel and a["anbieter"] == ziel:
            kauf = '<span class="az">eigenes Angebot</span>'
        elif ziel:
            feld = "" if a["unbegrenzt"] else f'<input type="number" name="menge" min="1" max="{a["menge"]}" value="1" aria-label="Menge" style="width:90px"> '
            kauf = (f'<form class="sa-inline" method="post" action="{PFAD}kaufen" onsubmit="return confirm(\'Verbindlich kaufen?\')">{c}'
                    f'<input type="hidden" name="ziel" value="{esc(ziel)}"><input type="hidden" name="angebot" value="{a["id"]}">{feld}'
                    f'<button class="btn klein" type="submit">Kaufen</button></form>')
        menge = "Lizenz (unbegrenzt)" if a["unbegrenzt"] else f'{zahl(a["menge"])} {esc(einheit)}' + (f' · Bereitschaft {a["bereit"]:.0f} %' if a["ware"].startswith("mil:") else "")
        zeilen.append((esc(name), esc(namen.get(a["anbieter"], a["anbieter"])), menge, _pk(a["preis"]), f'{abw:+.0f} %'.replace(".", ","), kauf))
    inhalt = (_wahl(request, mine, ziel, PFAD, namen) if mine else '<p class="sa-hinweis">Nur Ansicht – gehandelt wird durch Landesherren (Teilstaat) und die Leitung des Schatzamts (Reich).</p>')
    n_off = len(zeilen)
    umsatz = con.execute("SELECT COALESCE(SUM(summe),0) s, COUNT(*) n FROM hd_geschaefte WHERE zeit>?", (int(time.time()) - 30 * 86400,)).fetchone()
    kz = [("Offene Angebote", str(n_off)), ("Geschäfte (30 Tage)", str(umsatz["n"])), ("Handelsumsatz (30 Tage)", geld.mark_kurz(umsatz["s"]))]
    if ziel and kasse(con, ziel):
        kz.insert(0, ("Kasse", geld.mark_kurz(kasse(con, ziel)["saldo"])))
    inhalt += (f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>' + chips
               + amt.tabelle(["Ware", "Anbieter", "Angebot", "Preis je Einheit", "zum Richtpreis", "Kaufen"], zeilen, "Zurzeit gibt es keine Angebote."))
    inhalt += (f'<p class="sa-hinweis">Zahlung erfolgt sofort von Kasse zu Kasse ohne Überziehung. Militärgerät und Baupläne werden aus der Verteidigungskasse bezahlt.</p>')
    return _seite(request, k, "Handel – Marktplatz", "markt", inhalt, ziel or "")


def _opt(paare):
    return "".join(f'<option value="{esc(v)}">{esc(t)}</option>' for v, t in paare)


@sa.seite("staat")
async def mein(request, k):
    con = request.app["db"]
    namen = halter(con)
    mine, ziel = _ziel(con, k, request)
    if not ziel:
        return _seite(request, k, "Mein Handel", "mein", '<div class="hinweis">Handeln dürfen Landesherren für ihren Teilstaat und die Leitung des Schatzamts für das Reich.</div>')
    ws = waren(con)
    lg = lager(con, ziel)
    per, prod = letzte_produktion(con, ziel)
    vk = vorkommen(con, ziel)
    c = amt.csrf_feld(request)
    sp = sperre(con, ziel)
    out = _wahl(request, mine, ziel, PFAD + "mein/", namen)
    if sp:
        out += f'<div class="warnung">Handelssperre{": " + esc(sp["grund"]) if sp["grund"] else ""} – Sie können weder kaufen noch verkaufen.</div>'
    zeilen = []
    for w in ws.values():
        if not w["aktiv"]:
            continue
        m, p = lg.get(w["schl"], 0), prod.get(w["schl"], 0)
        if not m and not p:
            continue
        zeilen.append((esc(w["name"]), esc(SEKTORNAME[w["sektor"]]), f'{zahl(m)} {esc(w["einheit"])}', _pk(w["preis"]), geld.mark_kurz(m * w["preis"]),
                       f'{zahl(p)}' if p else "–", f'{w["verderb"]:g} %'.replace(".", ",") if w["verderb"] else "–"))
    out += ("<h2>Lager</h2>" + amt.tabelle(["Ware", "Bereich", "Bestand", "Richtpreis", "Wert", f"Erzeugt ({per or '–'})", "Verderb / Monat"], zeilen,
                                           "Das Lager ist leer. Waren entstehen jeden Haushaltsmonat aus den Ergebnissen des Etats.")
            + '<p class="sa-hinweis">Erzeugt wird ein Teil der Ausgaben für Gesundheit, Landwirtschaft und Industrie (Rohstoffe nach Vorkommen).</p>')
    hat = [f'{esc(RESNAME[r])} ({v})' for r, v in sorted(vk.items(), key=lambda x: -x[1]) if v > 0]
    fehlt = [esc(RESNAME[r]) for r, _ in RESSOURCEN if vk.get(r, 0) <= 0]
    out += (f'<h2>Vorkommen</h2><p>{", ".join(hat) if hat else "Keine nennenswerten Vorkommen."}</p>'
            + (f'<p class="az">Kein Vorkommen: {", ".join(fehlt)} – diese Rohstoffe können nicht verkauft, wohl aber eingekauft und weiterverarbeitet werden.</p>' if fehlt else ""))
    # Angebot einstellen
    opts = []
    for w in ws.values():
        if w["aktiv"] and lg.get(w["schl"], 0) > 0 and (not w["ressource"] or vk.get(w["ressource"], 0) > 0):
            opts.append((w["schl"], f'{w["name"]} (Lager {zahl(lg[w["schl"]])} {w["einheit"]}, Richtpreis {_pk(w["preis"])})'))
    if opts and not sp:
        out += (f'<h2>Waren anbieten</h2><form class="hd-form" method="post" action="{PFAD}anbieten">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                f'<div><label>Ware</label><select name="ware">{_opt(opts)}</select></div><div><label>Menge</label><input type="number" name="menge" min="1" value="1" required></div>'
                '<div><label>Preis je Einheit (Kr)</label><input type="text" name="preis" inputmode="decimal" required></div>'
                f'<button class="btn" type="submit">{amt.ic("check")}Anbieten</button></form>')
    kat = katalog_vt(con)
    stelle = vt_stelle(ziel)
    best = [r for r in con.execute("SELECT * FROM vt_bestand WHERE stelle=? AND anzahl>0", (stelle,)) if r["typ"] in kat and kat[r["typ"]]["kategorie"] != "Infrastruktur"]
    if best and not sp:
        o = [("mil:" + r["typ"], f'{kat[r["typ"]]["name"]} (Bestand {zahl(r["anzahl"])}, Bereitschaft {r["bereitschaft"]:.0f} %, Richtpreis {_pk(int(kat[r["typ"]]["preis"] * r["bereitschaft"] / 100))})') for r in best]
        out += (f'<h2>Militärgerät anbieten</h2><form class="hd-form" method="post" action="{PFAD}anbieten">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                f'<div><label>Gerät aus dem eigenen Bestand</label><select name="ware">{_opt(o)}</select></div><div><label>Anzahl</label><input type="number" name="menge" min="1" value="1" required></div>'
                '<div><label>Preis je Stück (Kr)</label><input type="text" name="preis" inputmode="decimal" required></div>'
                f'<button class="btn" type="submit">{amt.ic("check")}Anbieten</button></form>'
                '<p class="sa-hinweis">Das Gerät wird mit seiner Einsatzbereitschaft verkauft und ist ab dem Einstellen aus dem Bestand genommen; beim Zurückziehen kommt es zurück.</p>')
    f = eigener_faktor(con, ziel)
    if f <= 0.99 and not sp:
        o = [("plan:" + t["schl"], f'{t["name"]} (Richtpreis {_pk(plan_preis(con, t["schl"], f))})') for t in kat.values() if t["kategorie"] != "Infrastruktur"]
        out += (f'<h2>Baupläne anbieten</h2><p>Die Forschung hat Militärgerät auf {f * 100:.1f} % des Katalogpreises verbilligt ({(f - 1) * 100:+.1f} %). '
                f'Käufer fertigen danach zum selben Preisfaktor; der Bauplan bleibt bei Ihnen.</p>'.replace(".", ",")
                + f'<form class="hd-form" method="post" action="{PFAD}anbieten">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                  f'<div><label>Bauplan</label><select name="ware">{_opt(o)}</select></div><input type="hidden" name="menge" value="1">'
                  '<div><label>Preis (Kr)</label><input type="text" name="preis" inputmode="decimal" required></div>'
                  f'<button class="btn" type="submit">{amt.ic("check")}Anbieten</button></form>')
    else:
        out += f'<h2>Baupläne</h2><p class="az">Baupläne lassen sich verkaufen, sobald die eigene Forschung Militärgerät verbilligt hat (derzeit {(f - 1) * 100:+.1f} %).</p>'.replace(".", ",")
    # Veredelung
    ver = []
    for p, rez in REZEPTE.items():
        w = ws[p]
        txt = " + ".join(f'{str(je).replace(".", ",")} t {ws[s]["name"]}' for s, je in rez.items())
        ver.append((p, f'{w["name"]} (je t: {txt})'))
    if not sp:
        out += (f'<h2>Veredelung</h2><form class="hd-form" method="post" action="{PFAD}veredeln">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                f'<div><label>Erzeugnis</label><select name="produkt">{_opt(ver)}</select></div><div><label>Menge (t)</label><input type="number" name="menge" min="1" value="1" required></div>'
                f'<button class="btn zweit" type="submit">{amt.ic("wrench")}Veredeln</button></form>'
                f'<p class="sa-hinweis">Rohstoffe stammen aus dem Lager (auch eingekaufte). Energie und Löhne kosten {einstellungen(con)["veredelung_kosten"]} % des Richtpreises und gehen an die Volkswirtschaft.</p>')
    # eigene Angebote
    eig = []
    for a in con.execute("SELECT * FROM hd_angebote WHERE anbieter=? AND status='offen' ORDER BY id DESC", (ziel,)):
        n, e_, _ = info(con, a["ware"], ws, kat)
        eig.append((esc(n), "Lizenz" if a["unbegrenzt"] else f'{zahl(a["menge"])} {esc(e_)}', _pk(a["preis"]),
                    f'<form class="sa-inline" method="post" action="{PFAD}zurueck">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                    f'<input type="hidden" name="angebot" value="{a["id"]}"><button class="btn zweit klein" type="submit">Zurückziehen</button></form>'))
    out += "<h2>Meine Angebote</h2>" + amt.tabelle(["Ware", "Menge", "Preis", ""], eig, "Keine offenen Angebote.")
    liz = con.execute("SELECT * FROM hd_lizenzen WHERE schl=? ORDER BY zeit DESC", (ziel,)).fetchall()
    if liz:
        out += "<h2>Erworbene Baupläne</h2>" + amt.tabelle(["Gerät", "Preisfaktor", "Von", "Preis", "Seit"],
            [(esc(kat[x["typ"]]["name"]) if x["typ"] in kat else esc(x["typ"]), f'{x["faktor"] * 100:.1f} %'.replace(".", ","), esc(namen.get(x["von"], x["von"])), _pk(x["preis"]), amt._zeit(x["zeit"])) for x in liz])
    return _seite(request, k, "Mein Handel", "mein", out, ziel)


@sa.seite("staat")
async def ressourcen(request, k):
    con = request.app["db"]
    namen = halter(con)
    vk = {s: vorkommen(con, s) for s in namen}
    kopf = "".join(f"<th>{esc(n)}</th>" for _, n in RESSOURCEN)
    zeilen = ""
    for s, n in namen.items():
        zeilen += f"<tr><td>{esc(n)}</td>" + "".join(
            (f'<td style="background:rgba(0,0,0,{0.06 + v / 100 * 0.28:.2f})"><b>{v}</b></td>' if v > 0 else '<td class="n0">–</td>') for v in (vk[s].get(r, 0) for r, _ in RESSOURCEN)) + "</tr>"
    anz = "".join(f"<td>{sum(1 for s in namen if vk[s].get(r, 0) > 0)}</td>" for r, _ in RESSOURCEN)
    out = ('<p class="az">Reichhaltigkeit der Vorkommen im Gebiet (1–100; „–“ = kein Vorkommen). Ohne Vorkommen kann ein Rohstoff weder gefördert noch als Rohstoff verkauft '
           'werden. „Das Reich“ umfasst die Freien Reichsgebiete.</p>'
           f'<div class="hd-matrix"><table><thead><tr><th>Gebiet</th>{kopf}</tr></thead><tbody>{zeilen}<tr><td><i>Gebiete mit Vorkommen</i></td>{anz}</tr></tbody></table></div>')
    if verwalter(k):
        c = amt.csrf_feld(request)
        sel = request.query.get("bearbeiten", "")
        sel = sel if sel in namen else next(iter(namen))
        opt = "".join(f'<option value="{esc(s)}"{" selected" if s == sel else ""}>{esc(n)}</option>' for s, n in namen.items())
        felder = "".join(f'<div><label>{esc(n)}</label><input type="number" name="r_{r}" min="0" max="100" value="{vk[sel].get(r, 0)}"></div>' for r, n in RESSOURCEN)
        out += (f'<h2>Vorkommen festlegen</h2><form method="get" class="hd-form" action="{PFAD}ressourcen/"><div><label>Gebiet</label>'
                f'<select name="bearbeiten" onchange="this.form.submit()">{opt}</select></div></form>'
                f'<form method="post" action="{PFAD}ressourcen/" class="hd-form">{c}<input type="hidden" name="schl" value="{esc(sel)}">{felder}'
                f'<button class="btn" type="submit">{amt.ic("check")}Speichern</button></form>')
    return _seite(request, k, "Handel – Ressourcen", "ressourcen", out)


@sa.seite("staat")
async def buch(request, k):
    con = request.app["db"]
    namen = halter(con)
    ws, kat = waren(con), katalog_vt(con)
    z = [(amt._zeit(g["zeit"]), esc(info(con, g["ware"], ws, kat)[0]), zahl(g["menge"]), _pk(g["preis"]), _pk(g["summe"]),
          esc(namen.get(g["verkaeufer"], g["verkaeufer"])), esc(namen.get(g["kaeufer"], g["kaeufer"])))
         for g in con.execute("SELECT * FROM hd_geschaefte ORDER BY id DESC LIMIT 200")]
    return _seite(request, k, "Handel – Handelsbuch", "buch",
                  "<p class='az'>Alle abgeschlossenen Geschäfte, neueste zuerst.</p>" + amt.tabelle(["Zeit", "Ware", "Menge", "Preis", "Summe", "Verkäufer", "Käufer"], z, "Noch keine Geschäfte."))


@sa.seite("staat")
async def regeln(request, k):
    con = request.app["db"]
    c = amt.csrf_feld(request)
    e = einstellungen(con)
    kurs = geld.wechselkurs(con)
    out = ('<h2>Was verkauft werden darf</h2><ul>'
           '<li><b>Gesundheitswesen</b> → Arzneimittel, Impfstoffe, Medizintechnik, Spezialpharmazeutika</li>'
           '<li><b>Landwirtschaft</b> → Getreide, Obst und Gemüse, Fleisch, Milchprodukte, Ölsaaten, Zucker, Wein</li>'
           '<li><b>Industrie</b> → Rohstoffe (nur mit Vorkommen im eigenen Gebiet) sowie Stahl, Aluminium und Treibstoff aus dem Lager</li>'
           '<li><b>Forschung</b> → Baupläne für Militärgerät, das die eigene Forschung verbilligt hat; der Käufer fertigt zum selben Preisfaktor</li>'
           '<li><b>Verteidigung</b> → Militärgerät, aber nur aus dem eigenen Bestand (Liegenschaften ausgenommen)</li></ul>'
           '<h2>Nicht verkäuflich</h2><ul>' + "".join(f"<li><b>{esc(n)}</b> – {esc(t)}</li>" for n, t in NICHT_HANDELBAR) + "</ul>"
           f'<p class="az">Erzeugt wird jeden Haushaltsmonat ein Anteil der Ausgaben: Gesundheit {e["ueberschuss_gesundheit"]} %, Landwirtschaft {e["ueberschuss_landwirtschaft"]} %, '
           f'Industrie {e["ueberschuss_industrie"]} %. Angebotspreise dürfen {e["preis_min"]} % bis {e["preis_max"]} % des Richtpreises betragen.</p>')
    gruppen = {}
    for w in waren(con).values():
        gruppen.setdefault(w["sektor"], []).append(w)
    for s, n, t in SEKTOREN[:3]:
        z = []
        for w in gruppen.get(s, []):
            rez = REZEPTE.get(w["schl"])
            herk = (" + ".join(f'{str(je).replace(".", ",")} t {RESNAME.get(st, st)}' for st, je in rez.items()) + " (Veredelung)") if rez else (
                f'Vorkommen: {RESNAME[w["ressource"]]}' if w["ressource"] else f'{w["anteil"]:g} % des Überschusses'.replace(".", ","))
            if verwalter(k):
                pv = f'{w["preis"] / 100:.2f}'.replace(".", ",")
                form = (f'<form class="sa-inline" method="post" action="{PFAD}ware">{c}<input type="hidden" name="schl" value="{esc(w["schl"])}">'
                        f'<input type="text" name="preis" value="{pv}" size="9" aria-label="Richtpreis">'
                        f'<label><input type="checkbox" name="aktiv" value="1"{" checked" if w["aktiv"] else ""}> aktiv</label> <button class="btn zweit klein" type="submit">Speichern</button></form>')
            else:
                form = _pk(w["preis"])
            z.append((esc(w["name"]), esc(w["einheit"]), form, f'≈ {w["preis"] * kurs / 100:,.0f} €'.replace(",", "."), esc(herk), f'{w["verderb"]:g} %'.replace(".", ",") if w["verderb"] else "–"))
        out += f"<h2>{esc(n)}: {esc(t)}</h2>" + amt.tabelle(["Ware", "Einheit", "Richtpreis", "in Euro", "Herkunft", "Verderb / Monat"], z)
    if verwalter(k):
        out += (f'<h2>Sätze</h2><form class="hd-form" method="post" action="{PFAD}saetze">{c}'
                + "".join(f'<div><label>{t}</label><input type="text" name="{n}" value="{e[n]}" size="6"></div>' for n, t in
                          (("ueberschuss_gesundheit", "Überschuss Gesundheit %"), ("ueberschuss_landwirtschaft", "Überschuss Landwirtschaft %"),
                           ("ueberschuss_industrie", "Überschuss Industrie %"), ("preis_min", "Preis mind. % des Richtpreises"),
                           ("preis_max", "Preis höchstens %"), ("veredelung_kosten", "Veredelungskosten %")))
                + f'<button class="btn" type="submit">{amt.ic("check")}Speichern</button></form>')
        sp = con.execute("SELECT * FROM hd_sperren ORDER BY zeit DESC").fetchall()
        namen = halter(con)
        opt = "".join(f'<option value="{esc(s)}">{esc(n)}</option>' for s, n in namen.items())
        out += ("<h2>Handelssperren</h2>" + amt.tabelle(["Gebiet", "Grund", "Seit", ""],
                [(esc(namen.get(s["schl"], s["schl"])), esc(s["grund"]), amt._zeit(s["zeit"]),
                  f'<form class="sa-inline" method="post" action="{PFAD}sperre">{c}<input type="hidden" name="schl" value="{esc(s["schl"])}"><input type="hidden" name="aktion" value="aufheben">'
                  f'<button class="btn zweit klein" type="submit">Aufheben</button></form>') for s in sp], "Keine Sperren.")
                + f'<form class="hd-form" method="post" action="{PFAD}sperre">{c}<input type="hidden" name="aktion" value="verhaengen">'
                  f'<div><label>Gebiet</label><select name="schl">{opt}</select></div><div><label>Grund</label><input type="text" name="grund" size="30"></div>'
                  '<button class="btn zweit" type="submit">Handelssperre verhängen</button></form>')
    return _seite(request, k, "Handel – Waren & Regeln", "regeln", out)


# ---------------------------------------------------------------- Aktionen

async def _post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    return k, await sa.formular(request), request.app["db"]


def _int(s):
    try:
        return int(str(s).strip())
    except ValueError:
        return 0


def _halter_pruefen(con, k, form):
    z = str(form.get("ziel", ""))
    if z not in halter(con) or not darf(con, k, z):
        raise web.HTTPForbidden(text="Für dieses Gebiet dürfen Sie nicht handeln.")
    return z


async def anbieten_post(request):
    k, form, con = await _post(request)
    z = _halter_pruefen(con, k, form)
    back = f"{PFAD}mein/?ziel={z}"
    try:
        anbieten(con, z, str(form.get("ware", "")), _int(form.get("menge")), geld.betrag_lesen(form.get("preis", "")) or 0, k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(back, str(e), True)
    sa.weiter(back, "Angebot eingestellt.")


async def kaufen_post(request):
    k, form, con = await _post(request)
    z = _halter_pruefen(con, k, form)
    try:
        summe, name = kaufen(con, _int(form.get("angebot")), z, _int(form.get("menge")), k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(f"{PFAD}?ziel={z}", str(e), True)
    sa.weiter(f"{PFAD}?ziel={z}", f"Gekauft: {name} für {mark(summe)}.")


async def zurueck_post(request):
    k, form, con = await _post(request)
    z = _halter_pruefen(con, k, form)
    try:
        zurueckziehen(con, _int(form.get("angebot")), z, k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(f"{PFAD}mein/?ziel={z}", str(e), True)
    sa.weiter(f"{PFAD}mein/?ziel={z}", "Angebot zurückgezogen, die Ware ist wieder im Lager.")


async def veredeln_post(request):
    k, form, con = await _post(request)
    z = _halter_pruefen(con, k, form)
    try:
        kosten = veredeln(con, z, str(form.get("produkt", "")), _int(form.get("menge")), k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(f"{PFAD}mein/?ziel={z}", str(e), True)
    sa.weiter(f"{PFAD}mein/?ziel={z}", f"Veredelt; Kosten {mark(kosten)}.")


async def ressourcen_post(request):
    k, form, con = await _post(request)
    if not verwalter(k):
        raise web.HTTPForbidden()
    s = str(form.get("schl", ""))
    if s not in halter(con):
        raise web.HTTPNotFound()
    for r, _ in RESSOURCEN:
        v = max(0, min(100, _int(form.get("r_" + r))))
        con.execute("INSERT OR REPLACE INTO hd_vorkommen (schl, ressource, wert) VALUES (?,?,?)", (s, r, v))
    geld.protokoll(con, k, "Handel: Vorkommen geändert", f"{halter(con)[s]}")
    con.commit()
    sa.weiter(f"{PFAD}ressourcen/?bearbeiten={s}", "Vorkommen gespeichert.")


async def ware_post(request):
    k, form, con = await _post(request)
    if not verwalter(k):
        raise web.HTTPForbidden()
    w = waren(con).get(str(form.get("schl", "")))
    preis = geld.betrag_lesen(form.get("preis", ""))
    if not w or not preis:
        sa.weiter(PFAD + "regeln/", "Bitte einen gültigen Preis angeben.", True)
    con.execute("UPDATE hd_waren SET preis=?, aktiv=? WHERE schl=?", (preis, 1 if form.get("aktiv") == "1" else 0, w["schl"]))
    geld.protokoll(con, k, "Handel: Richtpreis geändert", f'{w["name"]}: {mark(w["preis"])} → {mark(preis)}')
    con.commit()
    sa.weiter(PFAD + "regeln/", f'{w["name"]} gespeichert.')


async def saetze_post(request):
    k, form, con = await _post(request)
    if not verwalter(k):
        raise web.HTTPForbidden()
    neu = {}
    for n in geld.VORGABEN["handel"]:
        v = geld.prozent_lesen(form.get(n)) if n != "preis_max" else None
        if n == "preis_max":
            try:
                v = float(str(form.get(n, "")).replace(",", "."))
            except ValueError:
                v = None
            v = v if v is not None and 100 <= v <= 1000 else None
        if v is None:
            sa.weiter(PFAD + "regeln/", "Bitte gültige Werte angeben (Prozent, Höchstpreis 100–1000 %).", True)
        neu[n] = int(v) if v == int(v) else v
    geld.einstellung_setzen(con, "handel", neu, k)
    con.commit()
    sa.weiter(PFAD + "regeln/", "Gespeichert.")


async def sperre_post(request):
    k, form, con = await _post(request)
    if not verwalter(k):
        raise web.HTTPForbidden()
    s = str(form.get("schl", ""))
    if s not in halter(con):
        raise web.HTTPNotFound()
    if form.get("aktion") == "aufheben":
        con.execute("DELETE FROM hd_sperren WHERE schl=?", (s,))
        geld.protokoll(con, k, "Handelssperre aufgehoben", halter(con)[s])
        msg = "Sperre aufgehoben."
    else:
        con.execute("INSERT OR REPLACE INTO hd_sperren (schl, zeit, grund, von) VALUES (?,?,?,?)", (s, int(time.time()), sa._f(form, "grund", 200), k["name"]))
        geld.protokoll(con, k, "Handelssperre verhängt", f'{halter(con)[s]}: {sa._f(form, "grund", 200)}')
        msg = "Handelssperre verhängt."
    con.commit()
    sa.weiter(PFAD + "regeln/", msg)


def registrieren(app):
    einrichten(app["db"])
    r = app.router
    r.add_get(PFAD, markt)
    r.add_get(PFAD + "mein/", mein)
    r.add_get(PFAD + "ressourcen/", ressourcen)
    r.add_get(PFAD + "buch/", buch)
    r.add_get(PFAD + "regeln/", regeln)
    r.add_post(PFAD + "anbieten", anbieten_post)
    r.add_post(PFAD + "kaufen", kaufen_post)
    r.add_post(PFAD + "zurueck", zurueck_post)
    r.add_post(PFAD + "veredeln", veredeln_post)
    r.add_post(PFAD + "ressourcen/", ressourcen_post)
    r.add_post(PFAD + "ware", ware_post)
    r.add_post(PFAD + "saetze", saetze_post)
    r.add_post(PFAD + "sperre", sperre_post)

    async def start(app_):
        app_["handel_aufgabe"] = asyncio.get_event_loop().create_task(automatik(app_))

    async def stopp(app_):
        app_["handel_aufgabe"].cancel()
    app.on_startup.append(start)
    app.on_cleanup.append(stopp)
