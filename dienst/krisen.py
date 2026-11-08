"""Krisen und Handlungszwang: Wenn die Lage in einem Teilstaat kippt, bricht eine Krise aus und der Landesherr muss reagieren (/schatzamt/krisen/).

Ablauf
- Beim Buchen des Haushaltsmonats (aufkommen.ausfuehren → pruefen) wertet jede Krisenart (KRISEN) die neue Lage eines Teilstaats aus (Zufriedenheit und die Indikatoren der
  Entwicklung). Ist der Auslöser erfüllt und gibt es noch keinen offenen Fall dieser Art, wird ein Fall mit Frist (Tage) eröffnet; der Landesherr bekommt eine Nachricht.
- Der Landesherr wählt eine Reaktion (Maßnahme). Sie kostet Geld aus der Staatskasse (Anteil am monatlichen Landesetat), hat eine Erfolgsaussicht (aus der Lage, bei der
  Entscheidung angezeigt) und Folgen: Wirkungen auf Zufriedenheit, BIP pro Kopf, Bevölkerungswachstum oder Indikatoren der Entwicklung über mehrere Monate (kr_wirkungen,
  wirken ab dem nächsten Haushaltsmonat in entwicklung.entwickeln), bei Misserfolg schwächere oder schädliche. Manche Reaktionen ziehen eine Folgekrise nach sich (folge).
- Handlungszwang: Reagiert der Landesherr nicht bis zur Frist, eskaliert der Fall (automatik, alle 10 Minuten): die Eskalationswirkungen treten ein, oft mit Folgekrise.
- Fälle klingen von selbst ab, wenn der Auslöser beim nächsten Haushaltsmonat nicht mehr erfüllt ist und noch niemand reagiert hat.
Erweitern: eine neue Krisenart ist ein Eintrag in KRISEN (Auslöser, Stufe, Text, Optionen, Eskalation); Optionen sind kleine Wörterbücher (siehe _o).
Tabellen: kr_faelle, kr_wirkungen. Hebel der Wirkungen: zuf_pt, kopf_pct, bev_pp, ind:<Indikator> (verschiebt den Zielwert des Indikators).
"""
import asyncio
import logging
import random
import time

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark

log = logging.getLogger("krisen")
esc = amt.esc
PFAD = sa.PFAD + "krisen/"
geld.BUCHUNGSART["krisenmassnahme"] = "Krisenmaßnahme (Staatskasse)"
MAX_OFFEN = 3   # gleichzeitig offene Krisen je Teilstaat

SCHEMA = """
CREATE TABLE IF NOT EXISTS kr_faelle (id INTEGER PRIMARY KEY AUTOINCREMENT, schl TEXT NOT NULL, art TEXT NOT NULL, stufe INTEGER NOT NULL DEFAULT 1,
    beginn INTEGER NOT NULL, frist INTEGER NOT NULL, periode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'offen', ausloeser TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '',
    reaktion TEXT NOT NULL DEFAULT '', erfolg INTEGER, reaktion_zeit INTEGER, ergebnis TEXT NOT NULL DEFAULT '', kosten INTEGER NOT NULL DEFAULT 0, autor TEXT NOT NULL DEFAULT '',
    gemeldet INTEGER NOT NULL DEFAULT 0, erinnert INTEGER NOT NULL DEFAULT 0, folge_art TEXT NOT NULL DEFAULT '', folge_ab TEXT NOT NULL DEFAULT '', folge_erledigt INTEGER NOT NULL DEFAULT 0,
    eskaliert_gemeldet INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kr_wirkungen (id INTEGER PRIMARY KEY AUTOINCREMENT, fall INTEGER NOT NULL, schl TEXT NOT NULL, hebel TEXT NOT NULL, wert REAL NOT NULL,
    ab TEXT NOT NULL, bis TEXT NOT NULL, titel TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '');
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- Definition der Krisenarten

def _w(hebel, wert, monate, titel, text=""):
    return {"hebel": hebel, "wert": wert, "monate": monate, "titel": titel, "text": text}


def _o(id_, name, text, kosten, erfolg, ok, fehl, t_ok, t_fehl, folge=None):
    """Eine Reaktion: kosten = % des monatlichen Landesetats, erfolg(c) = Erfolgswahrscheinlichkeit (0–1) aus der Lage c, ok/fehl = Wirkungen (_w), folge = (Krisenart, Monate)
    bei Misserfolg (oder 'immer' bei ok)."""
    return {"id": id_, "name": name, "text": text, "kosten": kosten, "erfolg": erfolg, "ok": ok, "fehl": fehl, "t_ok": t_ok, "t_fehl": t_fehl, "folge": folge}


def _stufe(c, grenzen):
    """1, 2, 3 je nach Wert gegen absteigende Grenzen (…, …): Wert unter grenzen[0] → 2 usw."""
    return 1 + sum(1 for g in grenzen if c < g)


KRISEN = {
    "aufstand": {
        "name": "Bürgeraufstand", "frist_tage": 5, "stufen": ["Unruhen", "Aufstand", "Bürgerkrieg droht"],
        "ausloeser": lambda c: c["zuf"] < 50,
        "stufe": lambda c: 1 + (c["zuf"] < 40) + (c["zuf"] < 25),
        "beschreibung": lambda c: f"Die Zufriedenheit ist auf {c['zuf']:.0f} gefallen. Die Menschen gehen auf die Straße.",
        "optionen": [
            _o("verhandeln", "Verhandeln und Zugeständnisse machen", "Der Landesherr empfängt Vertreter der Aufständischen und kommt ihnen entgegen.", 1.5,
               lambda c: _clamp(0.25 + 0.016 * (c["zuf"] - 15), 0.1, 0.9),
               [_w("zuf_pt", 5, 4, "Zugeständnisse", "Die Bürger fühlen sich gehört"), _w("ind:ueberwachung", -6, 4, "Weniger Kontrolle")],
               [_w("zuf_pt", -2, 3, "Gescheiterte Verhandlungen", "Die Aufständischen fühlen sich hingehalten")],
               "Die Verhandlungen waren erfolgreich: Die Proteste ebben ab, die Stimmung bessert sich.", "Die Verhandlungen scheitern, die Proteste gehen weiter.", ("aufstand", 1)),
            _o("sozialprogramm", "Soziales Notprogramm auflegen", "Lebensmittel, Arbeit und Zuschüsse für die Unzufriedenen: das kostet, beruhigt aber.", 4.0,
               lambda c: _clamp(0.8 - 0.004 * max(0, 50 - c["zuf"]), 0.4, 0.9),
               [_w("zuf_pt", 4, 6, "Notprogramm", "Hilfen kommen an"), _w("ind:ernaehrung", 4, 3, "Lebensmittelhilfen")],
               [_w("zuf_pt", 1, 3, "Teilweise Wirkung", "Die Hilfen kommen nicht überall an")],
               "Das Notprogramm greift: Die Lage beruhigt sich spürbar.", "Das Programm greift nur teilweise, die Unruhe bleibt."),
            _o("militaer", "Militär einsetzen", "Die Truppe schlägt den Aufstand nieder. Das geht schnell, hinterlässt aber Verbitterung und einen Überwachungsstaat.", 0.5,
               lambda c: _clamp(0.45 + 0.004 * (c.get("bereitschaft", 50) - 50), 0.2, 0.8),
               [_w("zuf_pt", -4, 6, "Verbitterung", "Die Bevölkerung nimmt dem Landesherrn die Gewalt übel"), _w("ind:ueberwachung", 15, 6, "Ausnahmezustand")],
               [_w("zuf_pt", -8, 6, "Blutvergießen", "Der Einsatz endet im Chaos"), _w("bev_pp", -0.05, 3, "Flucht aus dem Land"), _w("kopf_pct", -2, 3, "Plünderungen")],
               "Der Aufstand ist niedergeschlagen. Ruhe herrscht, aber unter dem Druck des Ausnahmezustands.", "Der Einsatz scheitert blutig: Plünderungen, Flucht und Hass.", ("ueberwachung", 3)),
        ],
        "eskalation": [_w("zuf_pt", -8, 6, "Aufstand außer Kontrolle", "Niemand reagiert, die Lage eskaliert"), _w("kopf_pct", -3, 4, "Plünderungen und Streiks"), _w("bev_pp", -0.1, 4, "Flucht aus dem Land")],
        "t_eskalation": "Der Landesherr hat nicht reagiert: Der Aufstand gerät außer Kontrolle, es kommt zu Plünderungen und Flucht.", "folge_eskalation": ("aufstand", 1),
    },
    "hunger": {
        "name": "Hungerunruhen", "frist_tage": 7, "stufen": ["Lebensmittelknappheit", "Hunger", "Hungersnot"],
        "ausloeser": lambda c: c["z"]["ernaehrung"] < 45,
        "stufe": lambda c: 1 + (c["z"]["ernaehrung"] < 35) + (c["z"]["ernaehrung"] < 25),
        "beschreibung": lambda c: f"Die Ernährungssicherheit ist auf {c['z']['ernaehrung']:.0f} gesunken. Die Menschen hungern und plündern Lager.",
        "optionen": [
            _o("nahrungshilfe", "Nahrungsmittelhilfe verteilen", "Der Staat kauft Lebensmittel auf und verteilt sie.", 3.0, lambda c: 0.85,
               [_w("ind:ernaehrung", 15, 3, "Nahrungsmittelhilfe"), _w("zuf_pt", 2, 3, "Die Hilfe kommt an")], [_w("ind:ernaehrung", 5, 2, "Hilfe verteilt sich schlecht")],
               "Die Verteilung klappt: Die Not lässt nach.", "Die Hilfe verteilt sich schlecht, nur wenige profitieren."),
            _o("import", "Lebensmittel importieren", "Zusätzliche Einfuhren füllen die Lager, wenn die Lieferwege funktionieren.", 2.0,
               lambda c: _clamp(0.8 - 0.006 * max(0, c["z"]["engpass"] - 20), 0.3, 0.85), [_w("ind:ernaehrung", 10, 3, "Importe")], [_w("zuf_pt", -1, 2, "Importware bleibt aus")],
               "Die Importe kommen an und stabilisieren die Versorgung.", "Die Lieferungen bleiben in Engpässen stecken."),
            _o("rationierung", "Rationierung und Beschlagnahmung", "Vorräte werden beschlagnahmt und streng zugeteilt. Hart, aber billig.", 0.0, lambda c: 0.6,
               [_w("ind:ernaehrung", 8, 4, "Rationierung"), _w("zuf_pt", -4, 4, "Murren über die Zuteilung")], [_w("zuf_pt", -6, 4, "Unruhen in den Schlangen"), _w("kopf_pct", -1, 3, "Schwarzmarkt")],
               "Die Zuteilung funktioniert, die Menschen murren aber.", "Die Zuteilung bricht zusammen, in den Schlangen kommt es zu Gewalt."),
        ],
        "eskalation": [_w("bev_pp", -0.2, 4, "Hungersnot", "Menschen verhungern oder fliehen"), _w("zuf_pt", -6, 4, "Hunger"), _w("kopf_pct", -2, 3, "Geschwächte Arbeitskräfte")],
        "t_eskalation": "Der Landesherr hat nicht reagiert: Die Hungersnot fordert Opfer.", "folge_eskalation": None,
    },
    "seuche": {
        "name": "Seuchenausbruch", "frist_tage": 5, "stufen": ["Krankheitswelle", "Seuche", "Epidemie"],
        "ausloeser": lambda c: c["z"]["wasser"] < 45 or c["z"]["gesundheit"] < 50,
        "stufe": lambda c: 1 + (min(c["z"]["wasser"], c["z"]["gesundheit"]) < 40) + (min(c["z"]["wasser"], c["z"]["gesundheit"]) < 30),
        "beschreibung": lambda c: f"Wasserversorgung {c['z']['wasser']:.0f}, Gesundheitsniveau {c['z']['gesundheit']:.0f}: Eine Seuche breitet sich aus.",
        "optionen": [
            _o("notfallprogramm", "Notfallprogramm Gesundheit", "Zusätzliche Ärzte, Medikamente und Lazarette.", 3.0, lambda c: 0.8, [_w("ind:gesundheit", 12, 3, "Notfallprogramm")],
               [_w("ind:gesundheit", 4, 2, "Zu spät und zu wenig")], "Die Ärzte bekommen die Lage in den Griff.", "Die Hilfe kommt zu spät und reicht nicht."),
            _o("quarantaene", "Quarantäne verhängen", "Ganze Viertel werden abgeriegelt. Das bremst die Seuche, aber auch die Wirtschaft.", 1.0, lambda c: 0.6,
               [_w("ind:gesundheit", 8, 3, "Quarantäne"), _w("kopf_pct", -2, 2, "Wirtschaft steht still"), _w("ind:ueberwachung", 5, 3, "Kontrollen")], [_w("bev_pp", -0.1, 2, "Seuche breitet sich aus")],
               "Die Quarantäne bremst die Seuche.", "Die Quarantäne wird umgangen, die Seuche breitet sich aus."),
            _o("wasserwerke", "Wasserwerke notinstandsetzen", "Die Ursache bekämpfen: sauberes Trinkwasser.", 4.0, lambda c: 0.85, [_w("ind:wasser", 15, 4, "Wasserwerke repariert")],
               [_w("ind:wasser", 5, 2, "Teilreparatur")], "Das Trinkwasser ist wieder sauber.", "Die Reparatur gelingt nur teilweise."),
        ],
        "eskalation": [_w("bev_pp", -0.3, 4, "Seuche wütet", "Viele sterben"), _w("zuf_pt", -5, 4, "Angst vor Ansteckung"), _w("kopf_pct", -2, 3, "Arbeitsausfälle")],
        "t_eskalation": "Der Landesherr hat nicht reagiert: Die Seuche wütet ungehindert.", "folge_eskalation": None,
    },
    "streik": {
        "name": "Streiks und Fachkräfteprotest", "frist_tage": 7, "stufen": ["Warnstreiks", "Streikwelle", "Generalstreik"],
        "ausloeser": lambda c: c["z"]["handwerk"] < 33 or c["z"]["akademiker"] > 46,
        "stufe": lambda c: 1 + (c["z"]["handwerk"] < 28 or c["z"]["akademiker"] > 50) + (c["z"]["handwerk"] < 23 or c["z"]["akademiker"] > 54),
        "beschreibung": lambda c: f"Handwerker und Facharbeiter: {c['z']['handwerk']:.0f} %, Akademikeranteil: {c['z']['akademiker']:.0f} %. Betriebe und Beschäftigte protestieren.",
        "optionen": [
            _o("ausbildung", "Ausbildungsoffensive", "Berufsschulen und Lehrstellen ausbauen.", 2.0, lambda c: 0.75,
               [_w("ind:handwerk", 5, 6, "Ausbildungsoffensive"), _w("ind:akademiker", -2, 6, "Mehr Lehrlinge")], [_w("ind:handwerk", 1, 3, "Schleppender Start")],
               "Die Offensive kommt in Gang: Mehr Menschen entscheiden sich für das Handwerk.", "Die Offensive kommt nur schleppend in Gang."),
            _o("anwerben", "Fachkräfte anwerben", "Handwerker aus dem Ausland ins Land holen.", 1.5, lambda c: 0.65, [_w("ind:handwerk", 4, 4, "Angeworbene Fachkräfte"), _w("zuf_pt", -1, 4, "Skepsis gegen Zuwanderer")],
               [_w("zuf_pt", -2, 3, "Anwerbung gescheitert", "Kaum jemand kommt, die Kritik wächst")], "Die Anwerbung ist erfolgreich.", "Die Anwerbung scheitert."),
            _o("loehne", "Lohn- und Tarifzugeständnisse", "Die Streikenden bekommen, was sie fordern.", 3.0, lambda c: 0.8, [_w("zuf_pt", 3, 4, "Höhere Löhne"), _w("kopf_pct", -0.5, 3, "Höhere Lohnkosten")],
               [_w("zuf_pt", 1, 2, "Zu wenig, zu spät")], "Die Streiks enden.", "Das Angebot reicht den Streikenden nicht."),
        ],
        "eskalation": [_w("kopf_pct", -4, 3, "Streiks legen die Wirtschaft lahm"), _w("zuf_pt", -3, 3, "Streikbedingte Not")],
        "t_eskalation": "Der Landesherr hat nicht reagiert: Die Streiks legen die Wirtschaft lahm.", "folge_eskalation": None,
    },
    "kriminalitaet": {
        "name": "Kriminalitätswelle", "frist_tage": 7, "stufen": ["Anstieg der Kriminalität", "Kriminalitätswelle", "Gesetzlosigkeit"],
        "ausloeser": lambda c: c["z"]["sicherheit"] < 45,
        "stufe": lambda c: 1 + (c["z"]["sicherheit"] < 35) + (c["z"]["sicherheit"] < 25),
        "beschreibung": lambda c: f"Das Sicherheitsgefühl ist auf {c['z']['sicherheit']:.0f} gefallen: Raub, Gewalt und Bandenkriminalität nehmen zu.",
        "optionen": [
            _o("polizei", "Polizei verstärken", "Mehr Streifen, mehr Gerichte, mehr Gefängnisse.", 3.0, lambda c: 0.75, [_w("ind:sicherheit", 10, 4, "Verstärkte Polizei"), _w("ind:ueberwachung", 5, 4, "Mehr Kontrollen")],
               [_w("ind:sicherheit", 3, 2, "Polizei überfordert")], "Die Straßen werden wieder sicherer.", "Die Polizei ist überfordert."),
            _o("buergerwehr", "Bürgerwehren dulden", "Die Bürger schützen sich selbst. Das kostet nichts, birgt aber Risiken.", 0.0, lambda c: 0.5,
               [_w("ind:sicherheit", 6, 4, "Bürgerwehren"), _w("zuf_pt", -2, 4, "Selbstjustiz")], [_w("zuf_pt", -5, 4, "Selbstjustiz eskaliert", "Bürgerwehren schlagen auf Unschuldige ein")],
               "Die Bürgerwehren schrecken Täter ab.", "Die Bürgerwehren geraten außer Kontrolle.", ("aufstand", 2)),
            _o("sozialprojekte", "Soziale Projekte gegen Perspektivlosigkeit", "Jugendarbeit, Arbeit und Wohnungen: langsamer, aber nachhaltig.", 3.0, lambda c: 0.7,
               [_w("ind:sicherheit", 5, 6, "Sozialprojekte"), _w("zuf_pt", 2, 6, "Perspektiven")], [_w("ind:sicherheit", 1, 3, "Projekte kommen nicht an")],
               "Die Projekte zeigen Wirkung.", "Die Projekte erreichen die Gefährdeten nicht."),
        ],
        "eskalation": [_w("kopf_pct", -3, 3, "Verbrechenswelle"), _w("zuf_pt", -5, 4, "Angst auf den Straßen")],
        "t_eskalation": "Der Landesherr hat nicht reagiert: Die Kriminalität eskaliert.", "folge_eskalation": None,
    },
    "ueberwachung": {
        "name": "Proteste gegen den Überwachungsstaat", "frist_tage": 7, "stufen": ["Kritik", "Proteste", "Massenproteste"],
        "ausloeser": lambda c: c["z"]["ueberwachung"] > 50,
        "stufe": lambda c: 1 + (c["z"]["ueberwachung"] > 60) + (c["z"]["ueberwachung"] > 75),
        "beschreibung": lambda c: f"Der Überwachungsgrad liegt bei {c['z']['ueberwachung']:.0f}: Die Bürger fühlen sich beobachtet und demonstrieren für ihre Freiheit.",
        "optionen": [
            _o("lockern", "Überwachung lockern", "Kontrollen abbauen. Das beruhigt, lässt aber die Sicherheit etwas sinken.", 0.0, lambda c: 0.85,
               [_w("ind:ueberwachung", -15, 4, "Weniger Kontrolle"), _w("ind:sicherheit", -4, 4, "Weniger Polizeipräsenz")], [_w("ind:ueberwachung", -5, 3, "Halbherzig gelockert")],
               "Die Lockerung beruhigt die Lage.", "Die Lockerung wirkt halbherzig, die Proteste gehen weiter."),
            _o("dialog", "Dialog und Öffentlichkeitsarbeit", "Der Landesherr erklärt und wirbt um Verständnis.", 1.0, lambda c: 0.5, [_w("zuf_pt", 3, 3, "Dialog")], [_w("zuf_pt", -2, 2, "Leere Worte")],
               "Der Dialog entspannt die Lage.", "Die Bürger empfinden die Worte als leer."),
            _o("durchgreifen", "Hart durchgreifen", "Demonstrationen werden verboten und aufgelöst.", 0.5, lambda c: 0.55, [_w("zuf_pt", -4, 4, "Verbote"), _w("ind:ueberwachung", 5, 4, "Noch mehr Kontrolle")],
               [_w("zuf_pt", -8, 6, "Gewaltsame Auflösungen")], "Die Proteste verstummen vorerst.", "Das Vorgehen provoziert noch mehr Widerstand.", ("aufstand", 2)),
        ],
        "eskalation": [_w("zuf_pt", -6, 4, "Wachsender Zorn"), _w("kopf_pct", -2, 3, "Gründer wandern ab")],
        "t_eskalation": "Der Landesherr hat nicht reagiert: Die Proteste wachsen.", "folge_eskalation": None,
    },
    "engpass": {
        "name": "Versorgungskrise durch Lieferengpässe", "frist_tage": 7, "stufen": ["Engpässe", "Versorgungskrise", "Zusammenbruch der Lieferketten"],
        "ausloeser": lambda c: c["z"]["engpass"] > 55,
        "stufe": lambda c: 1 + (c["z"]["engpass"] > 65) + (c["z"]["engpass"] > 80),
        "beschreibung": lambda c: f"Die Lieferengpässe haben {c['z']['engpass']:.0f} Punkte erreicht: Waren bleiben aus, Betriebe stehen still.",
        "optionen": [
            _o("transportprogramm", "Notfall-Transportprogramm", "Extra Züge, Schiffe und Konvois.", 3.0, lambda c: 0.8, [_w("ind:engpass", -20, 3, "Notfall-Transportprogramm")],
               [_w("ind:engpass", -6, 2, "Programm läuft schleppend an")], "Die Waren fließen wieder.", "Das Programm läuft nur schleppend an."),
            _o("rationierung", "Güter rationieren", "Knappe Güter werden zugeteilt.", 0.0, lambda c: 0.7, [_w("ind:engpass", -10, 3, "Rationierung"), _w("zuf_pt", -4, 3, "Murren")],
               [_w("zuf_pt", -6, 3, "Schwarzmarkt und Hamsterkäufe")], "Die Zuteilung stabilisiert die Lage.", "Hamsterkäufe und Schwarzmarkt verschärfen die Lage."),
            _o("zoll", "Zollerleichterungen", "Einfuhren werden beschleunigt und vergünstigt.", 1.0, lambda c: 0.6, [_w("ind:engpass", -8, 4, "Zollerleichterungen")],
               [_w("kopf_pct", -1, 2, "Zolleinnahmen fehlen")], "Die Einfuhren beleben den Markt.", "Die Erleichterungen verpuffen."),
        ],
        "eskalation": [_w("kopf_pct", -4, 3, "Produktionsstillstand"), _w("zuf_pt", -3, 3, "Leere Regale")],
        "t_eskalation": "Der Landesherr hat nicht reagiert: Die Lieferketten brechen weiter zusammen.", "folge_eskalation": None,
    },
    "umwelt": {
        "name": "Umweltkatastrophe", "frist_tage": 7, "stufen": ["Umweltalarm", "Umweltkatastrophe", "Ökologischer Kollaps"],
        "ausloeser": lambda c: c["z"]["co2"] > 85,
        "stufe": lambda c: 1 + (c["z"]["co2"] > 92) + (c["z"]["co2"] > 97),
        "beschreibung": lambda c: f"Die CO₂-Belastung ist auf {c['z']['co2']:.0f} gestiegen: Smog, Fischsterben und Ernteschäden.",
        "optionen": [
            _o("sanierung", "Umweltsanierung", "Filter, Aufforstung und Entgiftung.", 4.0, lambda c: 0.8, [_w("ind:co2", -15, 4, "Sanierung")], [_w("ind:co2", -5, 2, "Sanierung stockt")],
               "Die Sanierung zeigt Wirkung.", "Die Sanierung stockt."),
            _o("auflagen", "Strenge Industrieauflagen", "Schmutzige Betriebe müssen drosseln oder schließen.", 0.5, lambda c: 0.65, [_w("ind:co2", -8, 4, "Auflagen"), _w("kopf_pct", -2, 4, "Industrie gedrosselt")],
               [_w("kopf_pct", -2, 3, "Auflagen werden umgangen")], "Die Auflagen senken die Belastung.", "Die Auflagen werden umgangen."),
            _o("vertuschen", "Verharmlosen und abwiegeln", "Nichts tun und Beruhigungsparolen ausgeben. Die Belastung bleibt.", 0.0, lambda c: 1.0, [_w("zuf_pt", -3, 3, "Vertuschung durchschaut")],
               [], "Die Bürger durchschauen die Parolen.", ""),
        ],
        "eskalation": [_w("ind:gesundheit", -8, 4, "Umweltkatastrophe"), _w("bev_pp", -0.15, 4, "Vergiftete Böden und Gewässer"), _w("zuf_pt", -4, 4, "Katastrophenstimmung")],
        "t_eskalation": "Der Landesherr hat nicht reagiert: Die Umweltkatastrophe vergiftet das Land.", "folge_eskalation": None,
    },
}


# ---------------------------------------------------------------- Zeitrechnung und Lage

def _monat_plus(periode, n):
    j, m = (int(t) for t in periode.split("-"))
    i = j * 12 + (m - 1) + n
    return f"{i // 12}-{i % 12 + 1:02d}"


def lage_aus(zuf, z, bereitschaft=None):
    """Lage eines Teilstaats für Auslöser und Erfolgsaussicht: Zufriedenheit zuf und Indikatorwerte z."""
    return {"zuf": zuf, "z": z, "bereitschaft": 50 if bereitschaft is None else bereitschaft}


def lage_aktuell(con, schl):
    """Zuletzt gebuchte Lage eines Haushalts (für die Entscheidung)."""
    import entwicklung
    import etatplan
    z = entwicklung.zustand_vor(con, schl, "9999-99")
    zu = etatplan.zuf_letzte(con, schl)
    bereit = None
    if schl.startswith("ts-"):
        import verteidigung
        try:
            bereit = verteidigung.kennzahlen(con, "vt-" + schl[3:])["bereitschaft"]
        except Exception:
            bereit = None
    return lage_aus(80.0 if zu is None else zu, z, bereit)


# ---------------------------------------------------------------- Fälle

def offene(con, schl=None):
    if schl:
        return con.execute("SELECT * FROM kr_faelle WHERE schl=? AND status='offen' ORDER BY frist", (schl,)).fetchall()
    return con.execute("SELECT * FROM kr_faelle WHERE status='offen' ORDER BY frist").fetchall()


def offene_anzahl(con, schl):
    try:
        return con.execute("SELECT COUNT(*) FROM kr_faelle WHERE schl=? AND status='offen'", (schl,)).fetchone()[0]
    except Exception:
        return 0


def offene_arten(con, schl):
    try:
        return [r["art"] for r in con.execute("SELECT art FROM kr_faelle WHERE schl=? AND status='offen'", (schl,))]
    except Exception:
        return []


def _eroeffnen(con, schl, art, c, periode, stufe_plus=0):
    d = KRISEN[art]
    stufe = min(3, d["stufe"](c) + stufe_plus)
    jetzt = int(time.time())
    cur = con.execute("INSERT INTO kr_faelle (schl, art, stufe, beginn, frist, periode, ausloeser, text) VALUES (?,?,?,?,?,?,?,?)",
                      (schl, art, stufe, jetzt, jetzt + d["frist_tage"] * 86400, periode, d["stufen"][stufe - 1], d["beschreibung"](c)))
    geld.protokoll(con, None, "Krise ausgebrochen", f'{schl}: {d["name"]} ({d["stufen"][stufe - 1]}), Frist {d["frist_tage"]} Tage')
    return cur.lastrowid


def pruefen(con, periode, liste):
    """Beim Buchen des Haushaltsmonats: neue Krisen eröffnen, abgeklungene schließen, Folgekrisen auslösen (liste = aufkommen.berechnen mit x["entwicklung"])."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='kr_faelle'").fetchone():
        return 0   # Tabelle noch nicht angelegt (Werkzeuge außerhalb des Dienstes)
    neu = 0
    for x in liste:
        d = x.get("entwicklung")
        zf = x.get("zufriedenheit_land")
        if x.get("reichsgebiet") or not d or not zf:
            continue
        schl = "ts-" + x["staat"]
        z = {i: v["neu"] for i, v in d["zustand"].items()}
        c = lage_aus(zf["neu"], z)
        for art, kd in KRISEN.items():
            trifft = kd["ausloeser"](c)
            offen = con.execute("SELECT id FROM kr_faelle WHERE schl=? AND art=? AND status='offen'", (schl, art)).fetchone()
            if offen and not trifft:
                con.execute("UPDATE kr_faelle SET status='abgeklungen', ergebnis=? WHERE id=?", ("Die Lage hat sich von selbst beruhigt.", offen["id"]))
                continue
            if trifft and not offen:
                if con.execute("SELECT COUNT(*) FROM kr_faelle WHERE schl=? AND status='offen'", (schl,)).fetchone()[0] >= MAX_OFFEN:
                    continue   # nicht mehr als MAX_OFFEN Krisen gleichzeitig: die übrigen brechen aus, sobald Platz ist (Reihenfolge in KRISEN = Dringlichkeit)
                letzte = con.execute("SELECT MAX(beginn) b FROM kr_faelle WHERE schl=? AND art=?", (schl, art)).fetchone()["b"]
                if letzte and time.time() - letzte < 20 * 86400:
                    continue   # nicht sofort wieder dieselbe Krise
                _eroeffnen(con, schl, art, c, periode)
                neu += 1
        # Folgekrisen früherer Reaktionen
        for f in con.execute("SELECT * FROM kr_faelle WHERE schl=? AND folge_art!='' AND folge_erledigt=0 AND folge_ab<=?", (schl, periode)).fetchall():
            con.execute("UPDATE kr_faelle SET folge_erledigt=1 WHERE id=?", (f["id"],))
            kd = KRISEN.get(f["folge_art"])
            if kd and kd["ausloeser"](c) and not con.execute("SELECT 1 FROM kr_faelle WHERE schl=? AND art=? AND status='offen'", (schl, f["folge_art"])).fetchone():
                _eroeffnen(con, schl, f["folge_art"], c, periode, stufe_plus=1)
                neu += 1
    return neu


# ---------------------------------------------------------------- Wirkungen

def _wirkungen_anlegen(con, fall, schl, liste, periode, titel_praefix=""):
    ab = _monat_plus(periode, 1)
    for w in liste:
        con.execute("INSERT INTO kr_wirkungen (fall, schl, hebel, wert, ab, bis, titel, text) VALUES (?,?,?,?,?,?,?,?)",
                    (fall, schl, w["hebel"], w["wert"], ab, _monat_plus(ab, int(w["monate"]) - 1), titel_praefix + w["titel"], w["text"]))


def wirkungen_fuer(con, schl, periode):
    """(Effekte, Verschiebungen) aller im Monat `periode` laufenden Krisenwirkungen eines Haushalts für entwicklung.entwickeln:
    Effekte = [{hebel, wert, titel, text}] für zuf_pt/kopf_pct/bev_pp, Verschiebungen = {Indikator: Summe der Zielwert-Verschiebung}."""
    try:
        rows = con.execute("SELECT * FROM kr_wirkungen WHERE schl=? AND ab<=? AND bis>=?", (schl, periode, periode)).fetchall()
    except Exception:
        return [], {}
    effekte, shift = [], {}
    for r in rows:
        if r["hebel"].startswith("ind:"):
            shift[r["hebel"][4:]] = shift.get(r["hebel"][4:], 0.0) + float(r["wert"])
        else:
            effekte.append({"hebel": r["hebel"], "wert": float(r["wert"]), "titel": r["titel"], "text": r["text"] or "Folge einer Krise bzw. der getroffenen Maßnahmen", "modul": "krise"})
    return effekte, shift


def _wirk_text(w):
    h, v, m = w["hebel"], w["wert"], int(w["monate"])
    if h.startswith("ind:"):
        import entwicklung
        name = entwicklung.INDIKATOREN.get(h[4:], {}).get("name", h[4:])
        what = f"{name} {v:+.0f} Punkte"
    elif h == "zuf_pt":
        what = f"Zufriedenheit {v:+.0f} Punkte"
    elif h == "kopf_pct":
        what = f"BIP pro Kopf {v:+.1f} %"
    else:
        what = f"Bevölkerung {v * 12:+.1f} % pro Jahr"
    return f'{what.replace(".", ",").replace("-", "−")} ({m} Monat{"e" if m != 1 else ""})'


# ---------------------------------------------------------------- Reaktion und Eskalation

def kosten_von(con, schl, opt):
    import aufkommen
    liste = aufkommen.berechnen(con)
    x = next((y for y in liste if "ts-" + y["staat"] == schl), None)
    return int(round((x["land"] if x else 0) * opt["kosten"] / 100.0))


def reagieren(con, k, fall_id, option_id, periode):
    """Führt die Reaktion des Landesherrn aus (Kosten, Erfolg, Wirkungen). Gibt den Ergebnistext zurück; wirft geld.Fehler."""
    import etatplan
    f = con.execute("SELECT * FROM kr_faelle WHERE id=?", (fall_id,)).fetchone()
    if not f or f["status"] != "offen":
        raise geld.Fehler("Dieser Fall ist nicht mehr offen.")
    kd = KRISEN[f["art"]]
    opt = next((o for o in kd["optionen"] if o["id"] == option_id), None)
    if not opt:
        raise geld.Fehler("Unbekannte Maßnahme.")
    kasse = geld.stellenkonto(con, f["schl"])
    kosten = kosten_von(con, f["schl"], opt)
    if kosten > 0:
        if etatplan.kasse_frei(con, kasse) < kosten:
            raise geld.Fehler(f"Die Staatskasse hat nicht genug freie Mittel: benötigt {mark(kosten)}, frei {mark(etatplan.kasse_frei(con, kasse))}.")
        geld.buchen(con, kasse["id"], geld.sonder(con, "volkswirtschaft")["id"], kosten, "krisenmassnahme", f'{kd["name"]}: {opt["name"]}', k, bezug=f"KR-{fall_id}")
    c = lage_aktuell(con, f["schl"])
    p = float(opt["erfolg"](c))
    erfolg = random.Random(f"{fall_id}:{option_id}").random() < p
    _wirkungen_anlegen(con, fall_id, f["schl"], opt["ok"] if erfolg else opt["fehl"], periode)
    text = opt["t_ok"] if erfolg else (opt["t_fehl"] or "Die Maßnahme zeigt keine Wirkung.")
    folge = opt.get("folge")
    folge_art, folge_ab = "", ""
    if folge and (not erfolg or option_id == "militaer"):
        folge_art, folge_ab = folge[0], _monat_plus(periode, 1 + int(folge[1]))
    con.execute("UPDATE kr_faelle SET status='beantwortet', reaktion=?, erfolg=?, reaktion_zeit=?, ergebnis=?, kosten=?, autor=?, folge_art=?, folge_ab=? WHERE id=?",
                (option_id, 1 if erfolg else 0, int(time.time()), text, kosten, k["name"] if k else "", folge_art, folge_ab, fall_id))
    geld.protokoll(con, k, "Krisenreaktion", f'{f["schl"]}: {kd["name"]} → {opt["name"]} ({"Erfolg" if erfolg else "Misserfolg"}), Kosten {mark(kosten)}')
    return ("Erfolg: " if erfolg else "Misserfolg: ") + text


def eskalieren(con, f, periode):
    kd = KRISEN[f["art"]]
    _wirkungen_anlegen(con, f["id"], f["schl"], kd["eskalation"], periode)
    fo = kd.get("folge_eskalation")
    con.execute("UPDATE kr_faelle SET status='eskaliert', ergebnis=?, folge_art=?, folge_ab=? WHERE id=?",
                (kd["t_eskalation"], fo[0] if fo else "", _monat_plus(periode, 1 + int(fo[1])) if fo else "", f["id"]))
    geld.protokoll(con, None, "Krise eskaliert", f'{f["schl"]}: {kd["name"]} – keine Reaktion bis zur Frist')


# ---------------------------------------------------------------- Benachrichtigung und Hintergrundaufgabe

def _teilstaat_name(con, schl):
    r = geld.stellenkonto(con, schl)
    return (r["name"] if r else schl).replace("Staatskasse ", "")


async def _melden(app, con, f, text):
    import notlage
    try:
        kasse = geld.stellenkonto(con, f["schl"])
        for kid in await notlage.empfaenger(app, con, kasse):
            await app["discord"].dm(kid, text)
    except Exception:
        log.exception("Krisenmeldung fehlgeschlagen")


async def takt(app):
    import etatplan
    con = app["db"]
    jetzt = int(time.time())
    for f in con.execute("SELECT * FROM kr_faelle WHERE status='offen' AND gemeldet=0").fetchall():
        kd = KRISEN[f["art"]]
        con.execute("UPDATE kr_faelle SET gemeldet=1 WHERE id=?", (f["id"],))
        con.commit()
        await _melden(app, con, f, f"⚠ Krise in {_teilstaat_name(con, f['schl'])}: {kd['name']} ({f['ausloeser']})\n{f['text']}\n"
                                   f"Der Landesherr muss bis {amt._zeit(f['frist'])} reagieren, sonst eskaliert die Lage.\n{amt.config.SITE_URL}{PFAD}?ziel={f['schl']}")
    for f in con.execute("SELECT * FROM kr_faelle WHERE status='offen' AND erinnert=0 AND frist-?<172800 AND frist>?", (jetzt, jetzt)).fetchall():
        con.execute("UPDATE kr_faelle SET erinnert=1 WHERE id=?", (f["id"],))
        con.commit()
        await _melden(app, con, f, f"⏰ Frist läuft ab: {KRISEN[f['art']]['name']} in {_teilstaat_name(con, f['schl'])} – bis {amt._zeit(f['frist'])} reagieren!\n"
                                   f"{amt.config.SITE_URL}{PFAD}?ziel={f['schl']}")
    for f in con.execute("SELECT * FROM kr_faelle WHERE status='offen' AND frist<?", (jetzt,)).fetchall():
        eskalieren(con, f, etatplan.monat_heute())
        con.commit()
        await _melden(app, con, f, f"🔥 Krise eskaliert: {KRISEN[f['art']]['name']} in {_teilstaat_name(con, f['schl'])}\n{KRISEN[f['art']]['t_eskalation']}\n{amt.config.SITE_URL}{PFAD}?ziel={f['schl']}")


async def automatik(app):
    await asyncio.sleep(150)
    while True:
        try:
            await takt(app)
        except Exception:
            log.exception("Krisen: Takt fehlgeschlagen")
        await asyncio.sleep(600)


# ---------------------------------------------------------------- Anzeige

CSS = """<style>
.kr-fall{border:1px solid var(--ink);border-radius:12px;padding:14px 18px;margin:14px 0;background:#fff;box-shadow:0 0 0 1px var(--ink)}
.kr-fall.zu{border-color:var(--linie);box-shadow:none}
.kr-kopf{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;justify-content:space-between}
.kr-kopf h3{margin:0;font-size:17px}
.kr-frist{font-weight:650}.kr-frist.knapp{color:var(--rot)}
.kr-warn{color:var(--grau);font-size:13.5px;margin:8px 0}
.kr-opt{border:1px solid var(--linie);border-radius:10px;padding:10px 14px;margin:10px 0;background:#fff}
.kr-opt h4{margin:0 0 2px;font-size:15px;display:flex;flex-wrap:wrap;gap:4px 12px;justify-content:space-between}
.kr-opt p{margin:2px 0 6px;font-size:13.5px;color:var(--grau)}
.kr-opt ul{margin:4px 0 8px;padding-left:18px;font-size:13px}
.kr-opt .plus{color:var(--ok)}.kr-opt .minus{color:var(--rot)}
.kr-meta{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px;color:var(--grau);margin:4px 0}.kr-meta b{color:var(--ink)}
.kr-banner{display:flex;gap:10px;align-items:center;border:1px solid var(--ink);border-radius:12px;padding:10px 14px;margin:0 0 12px;background:#fff;box-shadow:0 0 0 1px var(--ink);font-size:14px}
.kr-banner .icon{width:18px;height:18px;flex:none}
</style>"""


def banner_html(con, schl):
    """Hinweis über jeder Seite des Teilstaats, solange ein Fall offen ist (Handlungszwang)."""
    fs = offene(con, schl)
    if not fs:
        return ""
    f = fs[0]
    kd = KRISEN[f["art"]]
    return (f'<div class="kr-banner">{amt.ic("triangle-alert")}<span><b>{esc(kd["name"])}</b> ({esc(f["ausloeser"])})'
            + (f' und {len(fs) - 1} weitere Krise{"n" if len(fs) > 2 else ""}' if len(fs) > 1 else "")
            + f' – der Landesherr muss bis <b>{esc(amt._zeit(f["frist"]))}</b> reagieren. <a href="{PFAD}?ziel={esc(schl)}">Jetzt reagieren</a></span></div>')


def _frist_text(frist):
    rest = frist - int(time.time())
    if rest <= 0:
        return "Frist abgelaufen", True
    tage, std = rest // 86400, (rest % 86400) // 3600
    return (f"noch {tage} Tag{'e' if tage != 1 else ''} {std} Std." if tage else f"noch {std} Std. {(rest % 3600) // 60} Min."), rest < 2 * 86400


def _fall_html(con, k, f, darf, request, lage):
    import etatplan
    kd = KRISEN[f["art"]]
    offen = f["status"] == "offen"
    frist, knapp = _frist_text(f["frist"])
    c = amt.csrf_feld(request)
    kopf = (f'<div class="kr-kopf"><h3>{amt.ic("triangle-alert")} {esc(kd["name"])} – {esc(f["ausloeser"])}</h3>'
            + (f'<span class="kr-frist{" knapp" if knapp else ""}">Frist bis {esc(amt._zeit(f["frist"]))} · {esc(frist)}</span>' if offen else
               f'<span class="az">{esc({"beantwortet": "Beantwortet", "eskaliert": "Eskaliert", "abgeklungen": "Abgeklungen"}[f["status"]])} · {esc(amt._zeit(f["beginn"]))}</span>') + '</div>'
            f'<p>{esc(f["text"])}</p>')
    if not offen:
        opt = next((o for o in kd["optionen"] if o["id"] == f["reaktion"]), None)
        zeile = (f'<p class="kr-meta"><span>Reaktion: <b>{esc(opt["name"]) if opt else "keine"}</b></span>' + (f'<span>Kosten: <b>{esc(mark(f["kosten"]))}</b></span>' if f["kosten"] else "")
                 + (f'<span>von {esc(f["autor"])}</span>' if f["autor"] else "") + f'</p><p class="az">{esc(f["ergebnis"])}</p>')
        return f'<div class="kr-fall zu">{kopf}{zeile}</div>'
    esk = "; ".join(_wirk_text(w) for w in kd["eskalation"])
    html = [f'<div class="kr-fall">{kopf}<p class="kr-warn">{amt.ic("clock")} Reagiert der Landesherr nicht bis zur Frist, eskaliert der Fall: {esc(kd["t_eskalation"].replace("Der Landesherr hat nicht reagiert: ", ""))} Folgen: {esc(esk)}.</p>']
    kasse = geld.stellenkonto(con, f["schl"])
    frei = etatplan.kasse_frei(con, kasse) if kasse else 0
    for o in kd["optionen"]:
        kosten = kosten_von(con, f["schl"], o)
        p = float(o["erfolg"](lage))
        ok = "".join(f'<li class="{"plus" if w["wert"] * (-1 if w["hebel"] == "ind:ueberwachung" or w["hebel"] in ("ind:engpass", "ind:co2") else 1) > 0 else "minus"}">{esc(_wirk_text(w))}</li>' for w in o["ok"])
        fehl = "".join(f'<li>{esc(_wirk_text(w))}</li>' for w in o["fehl"]) or '<li>keine Wirkung</li>'
        folge = (f'<p class="az">Kann eine Folgekrise nach sich ziehen: {esc(KRISEN[o["folge"][0]]["name"])}.</p>' if o.get("folge") else "")
        if darf:
            if kosten > frei:
                knopf = f'<span class="az">Nicht möglich: die Staatskasse hat nur {esc(mark(frei))} frei.</span>'
            else:
                knopf = (f'<form method="post" action="{PFAD}reagieren" onsubmit="return confirm(\'Maßnahme „{esc(o["name"])}“ jetzt beschließen? Sie lässt sich nicht zurücknehmen.\')">{c}'
                         f'<input type="hidden" name="fall" value="{f["id"]}"><input type="hidden" name="option" value="{esc(o["id"])}">'
                         f'<button class="btn" type="submit">{amt.ic("check")}Maßnahme beschließen</button></form>')
        else:
            knopf = ""
        html.append(f'<div class="kr-opt"><h4><span>{esc(o["name"])}</span><span class="kr-meta"><span>Kosten <b>{esc(mark(kosten)) if kosten else "keine"}</b></span>'
                    f'<span>Erfolgsaussicht <b>{p * 100:.0f} %</b></span></span></h4><p>{esc(o["text"])}</p>'
                    f'<b>Bei Erfolg</b><ul>{ok}</ul><b>Bei Misserfolg</b><ul>{fehl}</ul>{folge}{knopf}</div>')
    html.append("</div>")
    return "".join(html)


@sa.seite("staat")
async def seite(request, k):
    import etatplan
    con = request.app["db"]
    regiert = sa._regierte(con, k)
    ziel = request.query.get("ziel", "")
    alle = ziel == "reich" or (not ziel and not regiert)
    if not alle and not (ziel.startswith("ts-") and ziel[3:]):
        ziel = "ts-" + next(iter(regiert))
    if alle:
        faelle = con.execute("SELECT * FROM kr_faelle ORDER BY CASE status WHEN 'offen' THEN 0 ELSE 1 END, beginn DESC LIMIT 80").fetchall()
        zeilen = []
        for f in faelle:
            kd = KRISEN[f["art"]]
            frist, knapp = _frist_text(f["frist"]) if f["status"] == "offen" else ("", False)
            zeilen.append((f'<a href="{PFAD}?ziel={esc(f["schl"])}">{esc(_teilstaat_name(con, f["schl"]))}</a>', esc(kd["name"]), esc(f["ausloeser"]),
                           amt.status_marke("nein" if knapp else "warn", f"offen · {frist}") if f["status"] == "offen" else esc({"beantwortet": "beantwortet", "eskaliert": "eskaliert", "abgeklungen": "abgeklungen"}[f["status"]]),
                           esc(amt._zeit(f["beginn"], False))))
        n_offen = sum(1 for f in faelle if f["status"] == "offen")
        inhalt = (CSS + f'<h1>{amt.ic("triangle-alert")} Krisen im Reich</h1><p class="az">Alle Teilstaaten im Überblick. Reagieren muss der jeweilige Landesherr.</p>{amt.meldung(request)}'
                  f'<p class="sa-status{"" if n_offen else " ok"}">{amt.ic("triangle-alert" if n_offen else "check")}{n_offen} offene Krise{"n" if n_offen != 1 else ""}.</p>'
                  + amt.tabelle(["Teilstaat", "Krise", "Stufe", "Stand", "Beginn"], zeilen, "Noch keine Krisen."))
        return sa.ant(request, k, "Krisen", "sa-krisen", inhalt)
    sid = ziel[3:]
    faelle = con.execute("SELECT * FROM kr_faelle WHERE schl=? ORDER BY CASE status WHEN 'offen' THEN 0 ELSE 1 END, beginn DESC LIMIT 40", (ziel,)).fetchall()
    darf = etatplan.darf_aendern(con, k, ziel)
    lage = lage_aktuell(con, ziel)
    name = _teilstaat_name(con, ziel)
    offene_html = "".join(_fall_html(con, k, f, darf, request, lage) for f in faelle if f["status"] == "offen")
    hist = [f for f in faelle if f["status"] != "offen"]
    wirk = con.execute("SELECT * FROM kr_wirkungen WHERE schl=? AND bis>=? ORDER BY ab", (ziel, etatplan.monat_heute())).fetchall()
    wirk_html = amt.tabelle(["Wirkung", "Von", "Bis", "Auswirkung"], [(esc(w["titel"]), esc(sa._monatsname(w["ab"])), esc(sa._monatsname(w["bis"])),
                                                                      esc(_wirk_text({"hebel": w["hebel"], "wert": w["wert"], "monate": 1}).replace(" (1 Monat)", ""))) for w in wirk],
                            "Keine laufenden Wirkungen.")
    inhalt = (CSS + f'<h1>{amt.ic("triangle-alert")} Krisen · {esc(name)}</h1><p class="az">Wenn die Lage kippt, muss der Landesherr handeln. Jede Maßnahme kostet Geld, '
              'hat eine Erfolgsaussicht und prägt die Entwicklung der nächsten Monate. Wer nicht reagiert, dem eskaliert die Krise.</p>' + amt.meldung(request)
              + (offene_html or f'<p class="sa-status ok">{amt.ic("check")}Keine offene Krise.</p>')
              + ("" if darf else '<p class="sa-hinweis">Nur Ansicht – reagieren darf der Landesherr dieses Teilstaats.</p>')
              + f'<h2>Laufende Wirkungen</h2>{wirk_html}'
              + f'<details class="sa-auf"><summary>{amt.ic("clock")}Frühere Krisen ({len(hist)})</summary>' + "".join(_fall_html(con, k, f, darf, request, lage) for f in hist) + '</details>'
              + '<div class="sa-erkl"><b>Wann bricht eine Krise aus?</b><ul>'
              '<li><b>Bürgeraufstand</b>: Zufriedenheit unter 50</li><li><b>Hungerunruhen</b>: Ernährungssicherheit unter 45</li><li><b>Seuche</b>: Wasserversorgung unter 45 oder Gesundheitsniveau unter 50</li>'
              '<li><b>Streiks</b>: Handwerker unter 33 % oder Akademiker über 46 %</li><li><b>Kriminalitätswelle</b>: Sicherheitsgefühl unter 45</li>'
              '<li><b>Proteste gegen Überwachung</b>: Überwachungsgrad über 50</li><li><b>Versorgungskrise</b>: Lieferengpässe über 55</li><li><b>Umweltkatastrophe</b>: CO₂-Belastung über 85</li></ul>'
              'Geprüft wird beim Buchen des Haushaltsmonats. Die Werte stehen im Reiter „Entwicklung“.</div>')
    return sa.ant(request, k, "Krisen", "sa-krisen", inhalt)


async def reagieren_post(request):
    import etatplan
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    try:
        fall = int(form.get("fall", ""))
    except ValueError:
        raise web.HTTPBadRequest()
    f = con.execute("SELECT * FROM kr_faelle WHERE id=?", (fall,)).fetchone()
    if not f:
        raise web.HTTPNotFound()
    if not etatplan.darf_aendern(con, k, f["schl"]):
        raise web.HTTPForbidden(text="Auf diese Krise darf nur der Landesherr des Teilstaats reagieren.")
    try:
        text = reagieren(con, k, fall, str(form.get("option", "")), etatplan.monat_heute())
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(f"{PFAD}?ziel={f['schl']}", str(e), True)
    sa.weiter(f"{PFAD}?ziel={f['schl']}", text)


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get(PFAD, seite)
    app.router.add_post(PFAD + "reagieren", reagieren_post)

    async def start(app_):
        app_["krisen_aufgabe"] = asyncio.get_event_loop().create_task(automatik(app_))

    async def stopp(app_):
        app_["krisen_aufgabe"].cancel()
    app.on_startup.append(start)
    app.on_cleanup.append(stopp)
