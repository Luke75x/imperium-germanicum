"""Verteidigung: Verteidigungsetats des Reiches und der Teilstaaten, Militärgerät (Katalog, Bestand, Beschaffung, Instandhaltung).

Kassen (Kontoart „verteidigung“): Reichsverteidigungskasse (stelle „verteidigung“) und je Teilstaat eine Verteidigungskasse
(„vt-<sid>“; die Freien Reichsgebiete sind das Reich und haben keine eigene).
Geldquelle: Der Staatshaushalt (aufkommen.py) zweigt jeden Monat einen Teil der Pflichtausgaben als Verteidigungsetat ab –
Vorgabe 2 % des BIP (NATO-Ziel). Davon gehen „anteil_reich“ % (Vorgabe 5 %) aus der Reichskasse an die Reichsverteidigungskasse,
der Rest des Teilstaats aus seiner Staatskasse an seine Verteidigungskasse. Zusätzlich kann ein Landesherr aus der Staatskasse zuführen.
Besoldung (besoldung.py): Führungsstab (Oberbefehlshaber, Stabschefs) aus der Reichsverteidigungskasse (Zahlstelle „verteidigung“),
alle anderen militärischen Ämter (Teilstreitkräfte, militärische Dienstgrade) aus der Verteidigungskasse ihres Teilstaats
(Zahlstelle „vt-land“, Teilstaat über die Fraktionsrolle; ohne Teilstaat: Reichsverteidigungskasse).
Militärgerät: Katalog (vt_katalog, Richtpreise in € → Kronen zum Wechselkurs, Instandhaltung in % des Preises je Jahr),
Bestand je Teilstaat (vt_bestand, mit Einsatzbereitschaft 0–100 %), Beschaffung (Kasse → Volkswirtschaft/Rüstungsindustrie),
Ausmusterung (Restwert zurück), monatliche Instandhaltung (vt_laeufe; reicht das Geld nicht, sinkt die Einsatzbereitschaft,
bei voller Bezahlung steigt sie wieder). Vorgänge in vt_vorgaenge.
Rechte: Reichsverteidigungskasse – Führungsstab, Kanzler/Kaiser, Leitung des Schatzamts; Teilstaat – Landesherr (wie Staatskasse),
Leitung des Schatzamts. Katalog und Sätze: Leitung des Schatzamts und Führungsstab. Seiten unter /schatzamt/verteidigung/ (staatlich).
"""
import json
import time
from datetime import date

from aiohttp import web

import amt
import anmeldung
import bereiche
import geld
import schatzamt as sa
from geld import mark

esc = amt.esc
PFAD = sa.PFAD + "verteidigung/"
SYSTEM = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt (automatisch)"}

ROLLE_OBERBEFEHLSHABER = "1522707672808292586"
FUEHRUNGSSTAB = {ROLLE_OBERBEFEHLSHABER: "Oberbefehlshaber", "1522721092127555666": "Stabschef des Heeres",
                 "1522912530446684190": "Stabschef der Marine", "1522913031456034938": "Stabschef der Luftwaffe"}
TEILSTREITKRAEFTE = {"1526343002966986882": "Kaiserliches Heer", "1526343128997695528": "Kaiserliche Luftwaffe",
                     "1526343421386690663": "Kaiserliche Marine"}

geld.VORGABEN.setdefault("verteidigung", {"quote_bip": 2.0, "anteil_reich": 5, "restwert": 10, "verfall": 15, "erholung": 5})

amt.ICONS.setdefault("shield", '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 '
                               '6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>')
amt.ICONS.setdefault("wrench", '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 '
                               '2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>')

# Richtpreise (Größenordnung, Stand 2024/25, ohne Gewähr): (Schlüssel, Name, Kategorie, Mio. €, Instandhaltung % p. a., Besatzung)
# Marine: Flugzeugträger ≈ großer Träger mit Katapulten (ohne Luftgeschwader), Kreuzer/Zerstörer ≈ große Lenkwaffenschiffe,
# Amphibisches Mehrzweckkampfschiff ≈ Hubschrauberträger mit Docklandeschiff; Schlachtschiff: heute ohne Vorbild, angenommene Größenordnung.
KATALOG = [
    ("kpz", "Kampfpanzer", "Heer", 29, 6, 4), ("spz", "Schützenpanzer", "Heer", 17, 6, 9),
    ("tpz", "Radschützen- und Transportpanzer", "Heer", 10, 5, 11), ("pzh", "Panzerhaubitze", "Heer", 17, 5, 5),
    ("rak", "Raketenartilleriesystem", "Heer", 20, 5, 3), ("pio", "Pionierpanzer / Brückenleger", "Heer", 15, 5, 3),
    ("lkw", "Geschützter Lastkraftwagen", "Heer", 0.6, 8, 2), ("gw", "Geländewagen", "Heer", 0.15, 8, 1),
    ("flak_m", "Flugabwehr-Feuereinheit, mittlere Reichweite", "Luftverteidigung", 150, 4, 30),
    ("flak_g", "Flugabwehr-Feuereinheit, große Reichweite", "Luftverteidigung", 1000, 4, 90),
    ("flak_n", "Flugabwehrkanonenpanzer (Nahbereich)", "Luftverteidigung", 15, 6, 3),
    ("kfz", "Kampfflugzeug", "Luftwaffe", 110, 7, 1), ("tfz", "Transportflugzeug", "Luftwaffe", 180, 6, 4),
    ("khs", "Kampfhubschrauber", "Luftwaffe", 50, 8, 2), ("ths", "Transporthubschrauber", "Luftwaffe", 80, 8, 4),
    ("drohne", "Aufklärungs- und Kampfdrohne", "Luftwaffe", 30, 6, 0),
    ("traeger", "Flugzeugträger", "Marine", 10000, 4, 2000), ("schlachtschiff", "Schlachtschiff", "Marine", 6000, 4, 1200),
    ("kreuzer", "Kreuzer", "Marine", 3000, 3, 400), ("zerstoerer", "Zerstörer", "Marine", 2000, 3, 300),
    ("amphib", "Amphibisches Mehrzweckkampfschiff", "Marine", 900, 3, 450),
    ("fregatte", "Fregatte", "Marine", 1800, 3, 120), ("korvette", "Korvette", "Marine", 500, 3, 60),
    ("uboot", "U-Boot", "Marine", 1000, 3, 30), ("minen", "Minenabwehrboot", "Marine", 150, 4, 40),
    ("versorger", "Einsatzgruppenversorger", "Marine", 600, 3, 150),
    ("kaserne", "Kaserne / Liegenschaft", "Infrastruktur", 250, 2, 0), ("depot", "Munitions- und Materialdepot", "Infrastruktur", 80, 2, 0),
    ("ausr", "Persönliche Ausrüstung (je 100 Soldaten)", "Ausrüstung", 2, 10, 0),
    ("mun", "Munitionspaket (Grundbeladung eines Bataillons)", "Ausrüstung", 25, 0, 0),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS vt_katalog (schl TEXT PRIMARY KEY, name TEXT NOT NULL, kategorie TEXT NOT NULL, preis INTEGER NOT NULL,
    instandhaltung REAL NOT NULL DEFAULT 0, besatzung INTEGER NOT NULL DEFAULT 0, aktiv INTEGER NOT NULL DEFAULT 1, rang INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS vt_bestand (stelle TEXT NOT NULL, typ TEXT NOT NULL, anzahl INTEGER NOT NULL DEFAULT 0,
    bereitschaft REAL NOT NULL DEFAULT 100, PRIMARY KEY (stelle, typ));
CREATE TABLE IF NOT EXISTS vt_vorgaenge (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, stelle TEXT NOT NULL, typ TEXT NOT NULL DEFAULT '',
    art TEXT NOT NULL, anzahl INTEGER NOT NULL DEFAULT 0, betrag INTEGER NOT NULL DEFAULT 0, text TEXT NOT NULL DEFAULT '', autor_name TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS vt_vorgaenge_s ON vt_vorgaenge (stelle, id);
CREATE TABLE IF NOT EXISTS vt_laeufe (periode TEXT PRIMARY KEY, summe INTEGER NOT NULL, bezahlt INTEGER NOT NULL, zeit INTEGER NOT NULL, autor_name TEXT NOT NULL);
"""
ARTEN = {"beschaffung": "Beschaffung", "ausmusterung": "Ausmusterung", "instandhaltung": "Instandhaltung", "zufuehrung": "Zuführung"}


def einrichten(con):
    """Legt fehlende Katalogeinträge an (neue Typen kommen so auch in bestehende Kataloge) und hält die Reihenfolge aktuell;
    bereits angepasste Preise und Sätze bleiben unberührt."""
    con.executescript(SCHEMA)
    kurs = geld.wechselkurs(con)
    for i, (s, n, kat, mio, ih, bes) in enumerate(KATALOG):
        con.execute("INSERT OR IGNORE INTO vt_katalog (schl, name, kategorie, preis, instandhaltung, besatzung, rang) VALUES (?,?,?,?,?,?,?)",
                    (s, n, kat, int(round(mio * 1e6 / kurs)) * 100, ih, bes, i))
        con.execute("UPDATE vt_katalog SET rang=? WHERE schl=?", (i, s))
    con.commit()


def einstellungen(con):
    return dict(geld.VORGABEN["verteidigung"], **geld.einstellung(con, "verteidigung"))


# ---------------------------------------------------------------- Kassen und Rechte

def kassen_sichern(con):
    """Reichsverteidigungskasse und eine Verteidigungskasse je Teilstaat der aktuellen Karte (ohne Freie Reichsgebiete)."""
    import karte
    import landespolizei
    geld._anlegen(con, "verteidigung", "Reichsverteidigungskasse", stelle="verteidigung")
    for s in karte.aktuell(con)["stand"]["staaten"]:
        if not geld.ist_reichsgebiet(s):
            geld._anlegen(con, "verteidigung", "Verteidigungskasse " + landespolizei._kurzname(s["name"]), stelle="vt-" + s["id"])
    con.commit()


def reichskasse(con):
    return geld.stellenkonto(con, "verteidigung")


def ist_fuehrungsstab(k):
    return bool(k) and k["mitglied"] and bool(set(k["rollen"]) & set(FUEHRUNGSSTAB))


def darf_reich(k):
    return bool(k) and k["mitglied"] and (ist_fuehrungsstab(k) or geld.ist_leitung(k) or bereiche._alle(k))


def darf_katalog(k):
    return bool(k) and k["mitglied"] and (ist_fuehrungsstab(k) or geld.ist_leitung(k))


def regierte(con, k):
    """Teilstaat-IDs, deren Verteidigungskasse das Konto führt (wie die Staatskasse; Leitung des Schatzamts: alle)."""
    if geld.ist_leitung(k):
        return {r["stelle"][3:] for r in con.execute("SELECT stelle FROM gk_konten WHERE art='verteidigung' AND stelle LIKE 'vt-%'")}
    return {r["stelle"][3:] for r in geld.regierte_staatskassen(con, k)}


def darf_land(con, k, sid):
    return bool(k) and k["mitglied"] and sid in regierte(con, k)


def verfuegbare(con, k):
    """Verteidigungskassen in der Verfügung des Kontos (für geld.verfuegbare_konten)."""
    if not k or not k["mitglied"]:
        return []
    out = [reichskasse(con)] if darf_reich(k) else []
    for sid in sorted({r["stelle"][3:] for r in geld.regierte_staatskassen(con, k)}):
        r = geld.stellenkonto(con, "vt-" + sid)
        if r:
            out.append(r)
    return [r for r in out if r]


def staat_von(con, rollen):
    """Teilstaat-ID der Fraktionsrolle unter den Rollen (oder None)."""
    import karte
    rollen = set(rollen or ())
    for s in karte.aktuell(con)["stand"]["staaten"]:
        if s.get("fraktion") and s["fraktion"] in rollen and not geld.ist_reichsgebiet(s):
            return s["id"]
    return None


def zahlstelle_land(con, rollen):
    """Zahlstelle für militärische Ämter: Verteidigungskasse des Teilstaats (Fraktionsrolle), sonst die Reichsverteidigungskasse."""
    sid = staat_von(con, rollen)
    return "vt-" + sid if sid else "verteidigung"


# ---------------------------------------------------------------- Katalog, Bestand

def katalog(con, nur_aktiv=False):
    return {r["schl"]: r for r in con.execute("SELECT * FROM vt_katalog" + (" WHERE aktiv=1" if nur_aktiv else "") + " ORDER BY rang, name")}


def bestand(con, stelle):
    kat = katalog(con)
    out = []
    for r in con.execute("SELECT * FROM vt_bestand WHERE stelle=? AND anzahl>0", (stelle,)):
        t = kat.get(r["typ"])
        if t:
            out.append({"typ": r["typ"], "name": t["name"], "kategorie": t["kategorie"], "anzahl": r["anzahl"], "bereitschaft": r["bereitschaft"],
                        "wert": r["anzahl"] * t["preis"], "instandhaltung": instandhaltung_monat(t, r["anzahl"]), "besatzung": r["anzahl"] * t["besatzung"]})
    return sorted(out, key=lambda x: (kat[x["typ"]]["rang"], x["name"]))


def instandhaltung_monat(t, anzahl):
    return int(round(anzahl * t["preis"] * float(t["instandhaltung"]) / 100 / 12))


def kennzahlen(con, stelle):
    b = bestand(con, stelle)
    wert = sum(x["wert"] for x in b)
    return {"wert": wert, "instandhaltung": sum(x["instandhaltung"] for x in b), "besatzung": sum(x["besatzung"] for x in b),
            "bereitschaft": (sum(x["bereitschaft"] * x["wert"] for x in b) / wert) if wert else None, "einheiten": sum(x["anzahl"] for x in b)}


def _vorgang(con, stelle, art, k, typ="", anzahl=0, betrag=0, text=""):
    con.execute("INSERT INTO vt_vorgaenge (zeit, stelle, typ, art, anzahl, betrag, text, autor_name) VALUES (?,?,?,?,?,?,?,?)",
                (int(time.time()), stelle, typ, art, anzahl, betrag, text[:300], k["name"] if k else "System"))


def beschaffen(con, stelle, typ, anzahl, k):
    """Kauft `anzahl` Einheiten aus dem Katalog für die Verteidigungskasse `stelle` (vt-<sid>). Gibt den Preis (Heller) zurück."""
    t = katalog(con, True).get(typ)
    if not t:
        raise geld.Fehler("Unbekanntes oder nicht mehr beschaffbares Gerät.")
    if not 1 <= anzahl <= 100000:
        raise geld.Fehler("Bitte eine Anzahl zwischen 1 und 100.000 angeben.")
    kasse = geld.stellenkonto(con, stelle)
    preis = t["preis"] * anzahl
    if kasse["saldo"] < preis:
        raise geld.Fehler(f'Die {kasse["name"]} ist nicht gedeckt: benötigt {mark(preis)}, vorhanden {mark(kasse["saldo"])}.')
    vw = geld.sonder(con, "volkswirtschaft")
    geld.buchen(con, kasse["id"], vw["id"], preis, "ruestung", f'Beschaffung: {anzahl} × {t["name"]}', k, bezug="RUESTUNG")
    alt = con.execute("SELECT * FROM vt_bestand WHERE stelle=? AND typ=?", (stelle, typ)).fetchone()
    n_alt, b_alt = (alt["anzahl"], alt["bereitschaft"]) if alt else (0, 100.0)
    bereit = (n_alt * b_alt + anzahl * 100.0) / (n_alt + anzahl)
    con.execute("INSERT INTO vt_bestand (stelle, typ, anzahl, bereitschaft) VALUES (?,?,?,?) ON CONFLICT(stelle, typ) DO UPDATE SET "
                "anzahl=excluded.anzahl, bereitschaft=excluded.bereitschaft", (stelle, typ, n_alt + anzahl, round(bereit, 2)))
    _vorgang(con, stelle, "beschaffung", k, typ, anzahl, preis, f'{anzahl} × {t["name"]} zu je {mark(t["preis"])}')
    geld.protokoll(con, k, "Rüstungsbeschaffung", f'{kasse["name"]}: {anzahl} × {t["name"]} für {mark(preis)}')
    return preis


def ausmustern(con, stelle, typ, anzahl, k):
    """Mustert `anzahl` Einheiten aus; der Restwert (Einstellung „restwert“ % des Preises × Einsatzbereitschaft) geht an die Kasse."""
    t = katalog(con).get(typ)
    r = con.execute("SELECT * FROM vt_bestand WHERE stelle=? AND typ=?", (stelle, typ)).fetchone()
    if not t or not r or not 1 <= anzahl <= r["anzahl"]:
        raise geld.Fehler("So viele Einheiten sind nicht im Bestand.")
    erloes = int(round(t["preis"] * anzahl * float(einstellungen(con)["restwert"]) / 100 * r["bereitschaft"] / 100))
    kasse = geld.stellenkonto(con, stelle)
    if erloes > 0:
        geld.buchen(con, geld.sonder(con, "volkswirtschaft")["id"], kasse["id"], erloes, "ruestung_erloes",
                    f'Ausmusterung: {anzahl} × {t["name"]} (Restwert)', k, bezug="RUESTUNG", minus=True)
    con.execute("UPDATE vt_bestand SET anzahl=anzahl-? WHERE stelle=? AND typ=?", (anzahl, stelle, typ))
    _vorgang(con, stelle, "ausmusterung", k, typ, anzahl, erloes, f'{anzahl} × {t["name"]} ausgemustert, Restwert {mark(erloes)}')
    geld.protokoll(con, k, "Ausmusterung", f'{kasse["name"]}: {anzahl} × {t["name"]}, Erlös {mark(erloes)}')
    return erloes


def instandhaltung(con, periode, k=None):
    """Monatliche Instandhaltung aller Bestände (einmal je Monat). Reicht die Kasse nicht, wird anteilig bezahlt und die
    Einsatzbereitschaft sinkt (Einstellung „verfall“ Prozentpunkte bei 0 % bezahlt); bei voller Zahlung steigt sie („erholung“)."""
    if con.execute("SELECT 1 FROM vt_laeufe WHERE periode=?", (periode,)).fetchone():
        return None
    e = einstellungen(con)
    k = k or SYSTEM
    vw = geld.sonder(con, "volkswirtschaft")
    summe = bezahlt = 0
    monat = sa._monatsname(periode)
    for (stelle,) in con.execute("SELECT DISTINCT stelle FROM vt_bestand WHERE anzahl>0").fetchall():
        b = bestand(con, stelle)
        kosten = sum(x["instandhaltung"] for x in b)
        if not kosten:
            continue
        kasse = geld.stellenkonto(con, stelle)
        zahlung = min(kosten, max(0, kasse["saldo"]))
        anteil = zahlung / kosten
        if zahlung > 0:
            geld.buchen(con, kasse["id"], vw["id"], zahlung, "instandhaltung", f"Instandhaltung Militärgerät {monat}", k, bezug=f"IH-{periode}")
        for x in b:
            neu = x["bereitschaft"] + float(e["erholung"]) if anteil >= 1 else x["bereitschaft"] - (1 - anteil) * float(e["verfall"])
            con.execute("UPDATE vt_bestand SET bereitschaft=? WHERE stelle=? AND typ=?", (round(min(100.0, max(0.0, neu)), 2), stelle, x["typ"]))
        _vorgang(con, stelle, "instandhaltung", k, "", 0, zahlung,
                 f"Instandhaltung {monat}: {mark(zahlung)} von {mark(kosten)}" + ("" if anteil >= 1 else " – Einsatzbereitschaft sinkt"))
        summe += kosten
        bezahlt += zahlung
    con.execute("INSERT INTO vt_laeufe (periode, summe, bezahlt, zeit, autor_name) VALUES (?,?,?,?,?)", (periode, summe, bezahlt, int(time.time()), k["name"]))
    con.commit()
    return summe, bezahlt


async def personalkosten(app, con):
    """{Zahlstelle: (Anzahl, Brutto je Monat)} – wie etat.personalkosten."""
    import etat
    return await etat.personalkosten(app, con)


# ---------------------------------------------------------------- Seiten

def _zahl_de(x):
    return f"{float(x):g}".replace(".", ",")


def _pz(x):
    return "–" if x is None else f"{x:.0f} %"


def _bereit_marke(x):
    if x is None:
        return '<span class="az">kein Gerät</span>'
    klasse = "ok" if x >= 80 else "warn" if x >= 50 else "nein"
    return amt.status_marke(klasse, _pz(x))


def _etat_monat(con):
    """{stelle: Verteidigungsetat je Monat (Heller)} nach dem aktuellen Staatshaushalt."""
    import aufkommen
    out = {"verteidigung": 0}
    for x in aufkommen.berechnen(con):
        out["verteidigung"] += x["vert_reich"]
        if x["vert_land"]:
            out["vt-" + x["staat"]] = x["vert_land"]
    return out


@sa.seite("staat")
async def uebersicht(request, k):
    con = request.app["db"]
    kassen_sichern(con)
    e = einstellungen(con)
    etat = _etat_monat(con)
    pk = await personalkosten(request.app, con)
    rk = reichskasse(con)
    zeilen, s_kasse, s_wert, s_ih, s_pk = [], 0, 0, 0, 0
    eigene = regierte(con, k)
    for r in con.execute("SELECT * FROM gk_konten WHERE art='verteidigung' AND stelle LIKE 'vt-%' ORDER BY name").fetchall():
        sid = r["stelle"][3:]
        kz = kennzahlen(con, r["stelle"])
        n, kosten = (pk or {}).get(r["stelle"], (0, 0))
        s_kasse += r["saldo"]; s_wert += kz["wert"]; s_ih += kz["instandhaltung"]; s_pk += kosten
        name = esc(r["name"].replace("Verteidigungskasse ", ""))
        zeilen.append((f'<a href="{PFAD}{esc(sid)}/">{name}</a>' + (" ·&nbsp;<b>Ihr Teilstaat</b>" if sid in eigene and not geld.ist_leitung(k) else ""),
                       geld.mark_kurz(r["saldo"]), geld.mark_kurz(etat.get(r["stelle"], 0)),
                       (f'{geld.mark_kurz(kosten)} <span class="az">({n})</span>' if n else "–") if pk is not None else "–",
                       geld.mark_kurz(kz["instandhaltung"]) if kz["instandhaltung"] else "–", geld.mark_kurz(kz["wert"]) if kz["wert"] else "–",
                       _bereit_marke(kz["bereitschaft"])))
    n_r, pk_r = (pk or {}).get("verteidigung", (0, 0))
    kzs = [("Verteidigungsetat / Monat", mark(sum(etat.values()))), ("Reichsverteidigungskasse", mark(rk["saldo"])),
           ("Verteidigungskassen der Teilstaaten", mark(s_kasse)), ("Militärisches Personal / Monat", mark(s_pk + pk_r) if pk is not None else "–"),
           ("Gerätewert gesamt", mark(s_wert)), ("Instandhaltung / Monat", mark(s_ih))]
    reich = ('<div class="sa-karte" style="max-width:560px"><small>Reich · Führungsstab</small><div class="sa-name">Reichsverteidigungskasse</div>'
             f'<div class="sa-saldo">{sa.betrag_html(rk["saldo"], False, kurz=True)}</div>'
             + sa.werte_html([("Etat / Monat", geld.mark_kurz(etat.get("verteidigung", 0))),
                              ("Besoldung Führungsstab / Monat", (f'{mark(pk_r)}<br><span class="az">{n_r} Besoldete</span>' if n_r else "keine Besoldeten") if pk is not None else "–"),
                              ("Zahlt", "Oberbefehlshaber und Stabschefs")])
             + (f'<div class="sa-aktionen"><a class="btn zweit" href="{sa.PFAD}konto/?konto={rk["id"]}">{amt.ic("wallet")}Umsätze</a></div>' if darf_reich(k) else "")
             + '</div>')
    erkl = ('<div class="sa-erkl"><b>So ist die Verteidigung finanziert</b><ol>'
            f'<li>Jeden Monat werden <b>{_zahl_de(e["quote_bip"])} % der Wirtschaftsleistung</b> (BIP ÷ 12) als Verteidigungsetat bereitgestellt – '
            'aus den Pflichtausgaben, die freien Mittel von Reich und Teilstaaten bleiben gleich.</li>'
            f'<li><b>{_zahl_de(e["anteil_reich"])} %</b> davon erhält das Reich (Reichsverteidigungskasse). Daraus wird der <b>Führungsstab</b> bezahlt: '
            'Oberbefehlshaber und Stabschefs von Heer, Marine und Luftwaffe.</li>'
            '<li>Den Rest erhält jeder Teilstaat für sich (Verteidigungskasse). Daraus werden <b>alle anderen militärischen Ämter</b> seines Teilstaats '
            'bezahlt (Zuordnung über die Fraktionsrolle) sowie <b>Instandhaltung und Kauf von Militärgerät</b>.</li>'
            '<li>Ein Landesherr kann seiner Verteidigungskasse zusätzlich Geld aus der Staatskasse zuführen. Wird die Instandhaltung nicht bezahlt, '
            'sinkt die Einsatzbereitschaft des Geräts.</li></ol></div>')
    stell = ""
    if geld.ist_leitung(k):
        c = amt.csrf_feld(request)
        feld = lambda i, n, t, v: f'<div><label for="{i}">{t}</label><input type="text" id="{i}" name="{n}" value="{esc(str(v))}"></div>'
        stell = (f'<details class="sa-auf"><summary>{amt.ic("pencil")}Sätze ändern</summary><form class="sa-formular" method="post" action="{PFAD}saetze">{c}'
                 '<div class="zeilen">' + feld("q", "quote_bip", "Verteidigungsetat (% des BIP)", e["quote_bip"])
                 + feld("a", "anteil_reich", "Anteil des Reiches (%)", e["anteil_reich"]) + feld("r", "restwert", "Restwert bei Ausmusterung (%)", e["restwert"])
                 + feld("v", "verfall", "Bereitschaftsverlust ohne Instandhaltung (Punkte)", e["verfall"])
                 + feld("h", "erholung", "Bereitschaftsgewinn bei Instandhaltung (Punkte)", e["erholung"]) + '</div>'
                 '<p class="sa-hinweis">Richtwert: NATO-Ziel 2 % des BIP. Änderungen gelten ab dem nächsten gebuchten Monat.</p>'
                 f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button></div></form></details>')
    inhalt = (f'<h1>{amt.ic("shield")} Verteidigung</h1>{amt.meldung(request)}'
              '<p class="az">Verteidigungsetats des Reiches und der Teilstaaten, militärisches Personal und Gerät.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kzs)}</div>'
              f'<div class="sa-schnell"><a href="{PFAD}katalog/">{amt.ic("wrench")}<b>Gerätekatalog</b><span>Preise und Instandhaltung</span></a></div>'
              + erkl + '<h2>Reich</h2>' + reich
              + '<h2>Teilstaaten</h2>' + amt.tabelle(["Teilstaat", "Kasse", "Etat / Monat", "Personal / Monat", "Instandhaltung / Monat", "Gerätewert",
                                                      "Einsatzbereitschaft"], zeilen, "Keine Teilstaaten.", klasse="sa-haushalt") + stell)
    return sa.ant(request, k, "Verteidigung", "sa-verteidigung", inhalt)


@sa.seite("staat")
async def land(request, k):
    con = request.app["db"]
    sid = request.match_info["sid"]
    kasse = geld.stellenkonto(con, "vt-" + sid)
    if not kasse or kasse["art"] != "verteidigung":
        raise web.HTTPNotFound(text="Teilstaat nicht gefunden.")
    stelle = kasse["stelle"]
    darf = darf_land(con, k, sid)
    kz = kennzahlen(con, stelle)
    b = bestand(con, stelle)
    pk = await personalkosten(request.app, con)
    n, kosten = (pk or {}).get(stelle, (0, 0))
    etat = _etat_monat(con).get(stelle, 0)
    name = kasse["name"].replace("Verteidigungskasse ", "")
    kzs = [("Verteidigungskasse", mark(kasse["saldo"])), ("Etat / Monat", mark(etat)),
           (f"Personal / Monat ({n} Besoldete)", (mark(kosten) if n else "–") if pk is not None else "–"),
           ("Instandhaltung / Monat", mark(kz["instandhaltung"])), ("Gerätewert", mark(kz["wert"])),
           ("Einsatzbereitschaft", _pz(kz["bereitschaft"]))]
    frei = etat - (kosten if pk is not None else 0) - kz["instandhaltung"]
    c = amt.csrf_feld(request)
    zeilen = []
    for x in b:
        aus = ""
        if darf:
            aus = (f'<form class="sa-inline" method="post" action="{PFAD}{esc(sid)}/ausmustern" onsubmit="return confirm(\'Wirklich ausmustern?\')">{c}'
                   f'<input type="hidden" name="typ" value="{esc(x["typ"])}"><input type="number" name="anzahl" min="1" max="{x["anzahl"]}" value="1" '
                   f'aria-label="Anzahl"><button class="btn zweit klein" type="submit">Ausmustern</button></form>')
        zeilen.append((esc(x["name"]), esc(x["kategorie"]), f'{x["anzahl"]:,}'.replace(",", "."), geld.mark_kurz(x["wert"]),
                       geld.mark_kurz(x["instandhaltung"]), _bereit_marke(x["bereitschaft"])) + ((aus,) if darf else ()))
    kopf = ["Gerät", "Kategorie", "Anzahl", "Wert", "Instandhaltung / Monat", "Bereitschaft"] + (["Ausmustern"] if darf else [])
    aktionen = ""
    if darf:
        kat = katalog(con, True)
        gruppen = {}
        for t in kat.values():
            gruppen.setdefault(t["kategorie"], []).append(t)
        opts = "".join(f'<optgroup label="{esc(g)}">' + "".join(
            f'<option value="{esc(t["schl"])}" data-preis="{t["preis"]}">{esc(t["name"])} · {geld.mark_kurz(t["preis"])}</option>' for t in ts) + "</optgroup>"
            for g, ts in gruppen.items())
        staatskasse = geld.stellenkonto(con, "ts-" + sid)
        aktionen = (f'<h2>Gerät beschaffen</h2><form class="sa-formular" method="post" action="{PFAD}{esc(sid)}/beschaffen" id="vt-kauf">{c}<div class="zeilen">'
                    f'<div><label for="ty">Gerät</label><select id="ty" name="typ">{opts}</select></div>'
                    '<div><label for="an">Anzahl</label><input type="number" id="an" name="anzahl" min="1" max="100000" value="1" required></div></div>'
                    f'<p class="sa-hinweis" id="vt-summe">Preis wird aus der Verteidigungskasse ({mark(kasse["saldo"])}) bezahlt.</p>'
                    f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Beschaffen</button>'
                    f'<a class="btn zweit" href="{PFAD}katalog/">Katalog ansehen</a></div></form>'
                    '<script>(function(){var f=document.getElementById("vt-kauf");if(!f)return;var s=f.querySelector("select"),a=f.querySelector("[name=anzahl]"),'
                    'o=document.getElementById("vt-summe"),k=' + json.dumps(kasse["saldo"]) + ';function z(h){return (h/100).toLocaleString("de-DE",'
                    '{minimumFractionDigits:2,maximumFractionDigits:2})+" Kr"}function u(){var p=+s.options[s.selectedIndex].dataset.preis*(+a.value||0);'
                    'o.textContent="Gesamtpreis "+z(p)+" – Verteidigungskasse "+z(k)+(p>k?" (nicht gedeckt)":"");}s.onchange=a.oninput=u;u();'
                    'f.onsubmit=function(){return confirm(o.textContent+". Jetzt beschaffen?")}})()</script>')
        if staatskasse:
            aktionen += (f'<h2>Aus der Staatskasse zuführen</h2><form class="sa-leiste" method="post" action="{PFAD}{esc(sid)}/zufuehren">{c}'
                         '<div><label for="zb">Betrag in Kronen</label><input type="text" id="zb" name="betrag" required inputmode="decimal"></div>'
                         f'<button class="btn zweit" type="submit">{amt.ic("arrow-right-left")}Zuführen</button></form>'
                         f'<p class="sa-hinweis">Staatskasse {esc(name)}: {mark(staatskasse["saldo"])}.</p>')
    vorg = con.execute("SELECT * FROM vt_vorgaenge WHERE stelle=? ORDER BY id DESC LIMIT 30", (stelle,)).fetchall()
    inhalt = (f'<p class="zurueck"><a href="{PFAD}">{amt.ic("arrow-left")}Verteidigung</a></p>'
              f'<h1>{amt.ic("shield")} Verteidigung · {esc(name)}</h1>{amt.meldung(request)}'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kzs)}</div>'
              + (f'<p class="sa-status{" ok" if frei >= 0 else ""}">{amt.ic("check" if frei >= 0 else "clock")}'
                 + (f"Nach Personal und Instandhaltung bleiben vom Monatsetat {mark(frei)} für Beschaffungen."
                    if frei >= 0 else f"Personal und Instandhaltung übersteigen den Monatsetat um {mark(-frei)}.") + '</p>')
              + '<h2>Bestand</h2>' + amt.tabelle(kopf, zeilen, "Noch kein Militärgerät beschafft.")
              + (f'<p class="sa-hinweis">Benötigtes Personal laut Gerät: {kz["besatzung"]:,} Soldaten.</p>'.replace(",", ".") if kz["besatzung"] else "")
              + aktionen
              + f'<details class="sa-auf"><summary>{amt.ic("clock")}Vorgänge ({len(vorg)})</summary>'
              + amt.tabelle(["Zeit", "Vorgang", "Betrag", "Beschreibung", "Durch"],
                            [(amt._zeit(v["zeit"]), esc(ARTEN.get(v["art"], v["art"])), mark(v["betrag"]), esc(v["text"]), esc(v["autor_name"])) for v in vorg],
                            "Noch keine Vorgänge.") + '</details>'
              + (f'<p><a href="{sa.PFAD}konto/?konto={kasse["id"]}">Umsätze der Verteidigungskasse →</a></p>' if darf else ""))
    return sa.ant(request, k, f"Verteidigung {name}", "sa-verteidigung", inhalt)


@sa.seite("staat")
async def katalog_seite(request, k):
    con = request.app["db"]
    kat = katalog(con)
    gruppen = {}
    for t in kat.values():
        gruppen.setdefault(t["kategorie"], []).append(t)
    tabellen = "".join(
        f'<h2>{esc(g)}</h2>' + amt.tabelle(["Gerät", "Preis je Einheit", "Instandhaltung / Jahr", "Instandhaltung / Monat", "Besatzung", ""],
                                           [(esc(t["name"]), geld.mark_kurz(t["preis"]), f'{t["instandhaltung"]:g} %'.replace(".", ","),
                                             geld.mark_kurz(instandhaltung_monat(t, 1)), str(t["besatzung"]) if t["besatzung"] else "–",
                                             "" if t["aktiv"] else amt.status_marke("nein", "nicht beschaffbar")) for t in ts], klasse="sa-haushalt")
        for g, ts in gruppen.items())
    bearbeiten = ""
    if darf_katalog(k):
        opts = "".join(f'<option value="{esc(t["schl"])}" data-preis="{esc(mark(t["preis"], einheit=False))}" data-ih="{t["instandhaltung"]:g}" '
                       f'data-aktiv="{t["aktiv"]}">{esc(t["kategorie"])} · {esc(t["name"])}</option>' for t in kat.values())
        bearbeiten = (f'<details class="sa-auf"><summary>{amt.ic("pencil")}Katalog bearbeiten</summary>'
                      f'<form class="sa-formular" method="post" action="{PFAD}katalog/" id="vt-kat">{amt.csrf_feld(request)}<div class="zeilen">'
                      f'<div><label for="kt">Gerät</label><select id="kt" name="schl">{opts}</select></div>'
                      '<div><label for="kp">Preis je Einheit (Kr)</label><input type="text" id="kp" name="preis" required></div>'
                      '<div><label for="ki">Instandhaltung (% je Jahr)</label><input type="text" id="ki" name="instandhaltung" required></div></div>'
                      '<label><input type="checkbox" id="ka" name="aktiv" value="1"> beschaffbar</label>'
                      f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button></div></form></details>'
                      '<script>(function(){var s=document.getElementById("kt");if(!s)return;function u(){var o=s.options[s.selectedIndex].dataset;'
                      'document.getElementById("kp").value=o.preis;document.getElementById("ki").value=o.ih;document.getElementById("ka").checked=o.aktiv==="1"}'
                      's.onchange=u;u()})()</script>')
    inhalt = (f'<p class="zurueck"><a href="{PFAD}">{amt.ic("arrow-left")}Verteidigung</a></p>'
              f'<h1>{amt.ic("wrench")} Gerätekatalog</h1>{amt.meldung(request)}'
              '<p class="az">Richtpreise in der Größenordnung vergleichbarer Systeme (Stand 2024/25), umgerechnet in Kronen. '
              'Die Instandhaltung wird monatlich aus der Verteidigungskasse des Teilstaats bezahlt.</p>' + bearbeiten + tabellen)
    return sa.ant(request, k, "Gerätekatalog", "sa-verteidigung", inhalt)


async def _post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    return k, await sa.formular(request), request.app["db"]


def _anzahl(form):
    try:
        return int(str(form.get("anzahl", "")).strip())
    except ValueError:
        return 0


async def beschaffen_post(request):
    k, form, con = await _post(request)
    sid = request.match_info["sid"]
    if not darf_land(con, k, sid):
        raise web.HTTPForbidden(text="Über diese Verteidigungskasse darfst du nicht verfügen.")
    try:
        preis = beschaffen(con, "vt-" + sid, str(form.get("typ", "")), _anzahl(form), k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(f"{PFAD}{sid}/", str(e), True)
    sa.weiter(f"{PFAD}{sid}/", f"Beschafft für {mark(preis)}.")


async def ausmustern_post(request):
    k, form, con = await _post(request)
    sid = request.match_info["sid"]
    if not darf_land(con, k, sid):
        raise web.HTTPForbidden(text="Über diese Verteidigungskasse darfst du nicht verfügen.")
    try:
        erloes = ausmustern(con, "vt-" + sid, str(form.get("typ", "")), _anzahl(form), k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(f"{PFAD}{sid}/", str(e), True)
    sa.weiter(f"{PFAD}{sid}/", f"Ausgemustert, Restwert {mark(erloes)}.")


async def zufuehren_post(request):
    k, form, con = await _post(request)
    sid = request.match_info["sid"]
    staatskasse = geld.stellenkonto(con, "ts-" + sid)
    if not darf_land(con, k, sid) or not staatskasse:
        raise web.HTTPForbidden(text="Über diese Kassen darfst du nicht verfügen.")
    betrag = geld.betrag_lesen(form.get("betrag", ""))
    if not betrag:
        sa.weiter(f"{PFAD}{sid}/", "Bitte einen gültigen Betrag angeben.", True)
    ziel = geld.stellenkonto(con, "vt-" + sid)
    try:
        if staatskasse["saldo"] < betrag:
            raise geld.Fehler(f'Die Staatskasse ist nicht gedeckt (verfügbar {mark(staatskasse["saldo"])}).')
        geld.buchen(con, staatskasse["id"], ziel["id"], betrag, "verteidigungsetat", "Zuführung aus der Staatskasse", k, bezug="ZUFUEHRUNG")
        _vorgang(con, ziel["stelle"], "zufuehrung", k, "", 0, betrag, "Zuführung aus der Staatskasse")
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(f"{PFAD}{sid}/", str(e), True)
    sa.weiter(f"{PFAD}{sid}/", f"{mark(betrag)} der Verteidigungskasse zugeführt.")


async def katalog_post(request):
    k, form, con = await _post(request)
    if not darf_katalog(k):
        raise web.HTTPForbidden()
    schl = str(form.get("schl", ""))
    t = katalog(con).get(schl)
    preis = geld.betrag_lesen(form.get("preis", ""))
    try:
        ih = float(str(form.get("instandhaltung", "")).replace(",", "."))
    except ValueError:
        ih = -1
    if not t or not preis or not 0 <= ih <= 100:
        sa.weiter(f"{PFAD}katalog/", "Bitte gültigen Preis und Instandhaltungssatz angeben.", True)
    aktiv = 1 if form.get("aktiv") == "1" else 0
    con.execute("UPDATE vt_katalog SET preis=?, instandhaltung=?, aktiv=? WHERE schl=?", (preis, ih, aktiv, schl))
    geld.protokoll(con, k, "Gerätekatalog geändert", f'{t["name"]}: {mark(t["preis"])} → {mark(preis)}, {t["instandhaltung"]:g} % → {ih:g} %, '
                                                    f'{"beschaffbar" if aktiv else "nicht beschaffbar"}')
    con.commit()
    sa.weiter(f"{PFAD}katalog/", f'{t["name"]} gespeichert.')


async def saetze_post(request):
    k, form, con = await _post(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    werte = {n: geld.prozent_lesen(form.get(n)) for n in ("quote_bip", "anteil_reich", "restwert", "verfall", "erholung")}
    if any(v is None for v in werte.values()) or werte["quote_bip"] > 20:
        sa.weiter(PFAD, "Bitte gültige Werte angeben (Verteidigungsetat höchstens 20 % des BIP).", True)
    geld.einstellung_setzen(con, "verteidigung", {n: (int(v) if v == int(v) else v) for n, v in werte.items()}, k)
    con.commit()
    sa.weiter(PFAD, "Gespeichert; die Sätze gelten ab dem nächsten gebuchten Monat.")


def registrieren(app):
    einrichten(app["db"])
    kassen_sichern(app["db"])
    r = app.router
    r.add_get(PFAD, uebersicht)
    r.add_post(PFAD + "saetze", saetze_post)
    r.add_get(PFAD + "katalog/", katalog_seite)
    r.add_post(PFAD + "katalog/", katalog_post)
    r.add_get(PFAD + "{sid}/", land)
    r.add_post(PFAD + "{sid}/beschaffen", beschaffen_post)
    r.add_post(PFAD + "{sid}/ausmustern", ausmustern_post)
    r.add_post(PFAD + "{sid}/zufuehren", zufuehren_post)
