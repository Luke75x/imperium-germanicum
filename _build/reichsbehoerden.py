"""Die Reichsbehörden: Stammdaten für die Website (site.py baut daraus die Seiten) und für die Reichskarte (Imperium-Dienst liest reichsbehoerden.json).

`python3 reichsbehoerden.py` schreibt reichsbehoerden.json neu (nach jeder Änderung hier ausführen, danach site.py/deploy.sh).

Aufbau: das Kronkanzleramt an der Spitze, darunter die Behörden für Sicherheit und Ordnung (Generaldirektoren) und die Reichsämter (Staatssekretäre),
angelehnt an die Gliederung der deutschen Bundesregierung. Jede Behörde hat eine eigene Seite und ein Dienstgebäude auf der Reichskarte.

Felder: schl (Schlüssel, zugleich Seitenname und Gebäudetyp auf der Karte), name, kurz, gruppe (kanzlei | sicherheit | amt), leitung (Amtsbezeichnung),
lead (Einleitung), aufgaben, gebaeude {name, text, lon, lat} (oder "bestand": Name eines schon auf der Karte vorhandenen Gebäudes), nachgeordnet,
zusammen (Zusammenarbeit), seite (bereits vorhandene eigene Seite statt der generierten), amt (Schlüssel in amt.BEHOERDEN des Dienstes).
"""
import json
import os

KANZLEI = {
    "schl": "kanzlei", "name": "Das Kronkanzleramt", "kurz": "Kronkanzleramt", "gruppe": "kanzlei",
    "leitung": "Der Kronkanzler", "seite": "informationen/die-reichsbehoerden/der-kanzler/",
    "lead": "Das Kronkanzleramt ist die Zentrale der Reichsverwaltung. Hier laufen die Fäden zwischen dem Souverän und allen Reichsbehörden zusammen.",
    "aufgaben": [
        "Dient dem Kronkanzler als Privatsekretär des Souveräns und überbringt den Willen der Krone an die Behörden.",
        "Koordiniert die Arbeit der Reichsämter und der Behörden für Sicherheit und Ordnung und bereitet die Entscheidungen des Kronkanzlers vor.",
        "Führt die Aufsicht über das Reichssicherheitsamt, den gemeinsamen Nachrichtendienst des Reiches.",
        "Verwaltet den kaiserlichen Kronbesitz und die Schatzkammer Seiner Majestät.",
    ],
    "gebaeude": {"name": "Kronkanzleramt", "text": "Sitz des Kronkanzleramts und des Kronkanzlers", "lon": 13.3693, "lat": 52.5199},
    "nachgeordnet": ["Kaiserliches Reichssicherheitsamt (Nachrichtendienst)"],
}

BEHOERDEN = [
    # ---------------- Sicherheit und Ordnung (Generaldirektoren)
    {"schl": "krs", "name": "Kaiserliches Reichssicherheitsamt", "kurz": "KRS", "gruppe": "sicherheit", "leitung": "Generaldirektor des KRS",
     "seite": "informationen/reichssicherheitsamt/", "amt": "krs",
     "lead": "Der reichsweite und übergeordnete Nachrichtendienst, verantwortlich für den Erhalt der inneren und äußeren Sicherheit.",
     "aufgaben": ["Beschafft und wertet Informationen aus und warnt Krone, Senat und Behörden vor Gefahren, ehe sie entstehen."],
     "bestand": "Hauptquartier des KRS"},
    {"schl": "polizei", "name": "Kaiserliche Polizeibehörde", "kurz": "Polizei", "gruppe": "sicherheit", "leitung": "Generaldirektor der Polizei", "amt": "polizei",
     "lead": "Die Polizei wahrt im gesamten Reichsgebiet die öffentliche Sicherheit und Ordnung und schützt Leib, Leben und Eigentum der Untertanen.",
     "aufgaben": ["Verfolgt Straftaten im ganzen Reichsgebiet und führt die Ermittlungen gemeinsam mit der Inquisition.",
                  "Vollstreckt die Urteile des Reichsgerichtshofs und leistet den übrigen Reichsbehörden Amtshilfe.",
                  "Arbeitet mit den Landespolizeien der Teilstaaten zusammen, deren Hoheit sie achtet."],
     "gebaeude": {"name": "Reichspolizeipräsidium", "text": "Hauptsitz der Kaiserlichen Polizeibehörde", "lon": 13.3858, "lat": 52.4844},
     "nachgeordnet": ["Die Landespolizeien (Amtshilfe und Fahndung)"], "zusammen": ["Inquisition", "Reichsamt des Innern"]},
    {"schl": "zoll", "name": "Kaiserliche Zollverwaltung", "kurz": "Zoll", "gruppe": "sicherheit", "leitung": "Generaldirektor des Zolls", "amt": "zoll",
     "lead": "Der Zoll wacht über den Waren- und Güterverkehr an den Grenzen des Reiches und sichert damit die Einnahmen der Krone.",
     "aufgaben": ["Erhebt Zölle und Abgaben und überwacht Ein- und Ausfuhr.",
                  "Sichert die Außengrenzen des Reiches und unterstützt das Reichsamt für Einwanderung bei der Kontrolle der Einreise.",
                  "Bekämpft Schmuggel und Schwarzhandel gemeinsam mit der Polizei."],
     "gebaeude": {"name": "Zollhaus an der Oberbaumbrücke", "text": "Hauptsitz der Kaiserlichen Zollverwaltung", "lon": 13.4455, "lat": 52.5015},
     "zusammen": ["Kaiserliches Schatz- und Währungsamt", "Reichsamt für Einwanderung und Staatsangehörigkeit"]},
    {"schl": "katastrophenschutz", "name": "Kaiserlicher Katastrophenschutz", "kurz": "KKS", "gruppe": "sicherheit", "leitung": "Generaldirektor des KKS", "amt": "katastrophenschutz",
     "lead": "Der Katastrophenschutz bereitet das Reich auf große Schadenslagen vor, lenkt im Ernstfall die Hilfe und schützt die Bevölkerung vor Naturgewalten und Unglücken.",
     "aufgaben": ["Plant und übt den Ernstfall und hält die Warnsysteme des Reiches bereit.",
                  "Lenkt bei Großschadenslagen die Hilfe der Teilstaaten.",
                  "Ihm untersteht die Reichsfeuerwehr, die Brandschutz und technische Hilfe leistet und bei Bränden, Unglücken und Notlagen allerorts zur Rettung bereitsteht."],
     "gebaeude": {"name": "Reichsleitstelle des Katastrophenschutzes", "text": "Hauptsitz des Kaiserlichen Katastrophenschutzes", "lon": 13.3517, "lat": 52.5490},
     "nachgeordnet": ["Die Reichsfeuerwehr"], "zusammen": ["Reichsamt für Gesundheit", "Reichsamt für Umwelt und Naturschutz"]},
    {"schl": "inquisition", "name": "Die Inquisition (Staatsanwaltschaft)", "kurz": "Inquisition", "gruppe": "sicherheit", "leitung": "Oberster Inquisitor", "amt": "inquisition",
     "lead": "Die Inquisition ist die Staatsanwaltschaft des Reiches: Sie erhebt Anklage im Namen der Krone und wacht über die Rechtmäßigkeit der Ermittlungen.",
     "aufgaben": ["Leitet die Ermittlungen schwerer Straftaten und erhebt Anklage vor den Gerichten des Reiches.",
                  "Prüft Haftbefehle und überwacht den Vollzug der Untersuchungshaft.",
                  "Stellt Anträge an den Reichsgerichtshof und vertritt die Anklage in Verfahren von reichsweiter Bedeutung."],
     "gebaeude": {"name": "Strafjustizgebäude Moabit", "text": "Sitz der Inquisition", "lon": 13.3447, "lat": 52.5273},
     "zusammen": ["Kaiserliche Polizeibehörde", "Reichsjustizamt", "Der Reichsgerichtshof"]},

    # ---------------- Reichsämter (Staatssekretäre)
    {"schl": "auswaertiges", "name": "Reichsamt für auswärtige Angelegenheiten", "kurz": "Auswärtiges", "gruppe": "amt", "leitung": "Staatssekretär für auswärtige Angelegenheiten",
     "lead": "Das Reichsamt für auswärtige Angelegenheiten vertritt das Reich gegenüber fremden Mächten und Gemeinschaften und pflegt die Verbindungen zu befreundeten Staaten.",
     "aufgaben": ["Führt den diplomatischen Verkehr des Reiches und bereitet Verträge und Abkommen vor.",
                  "Betreut die Untertanen des Reiches im Ausland und stellt ihnen Schutz und Beistand.",
                  "Unterhält das Kaiserliche Generalkonsulat, dem die Konsuln unterstehen; der Souverän ernennt und entlässt die Konsuln."],
     "gebaeude": {"name": "Auswärtiges Amt", "text": "Sitz des Reichsamts für auswärtige Angelegenheiten und des Generalkonsulats", "lon": 13.3965, "lat": 52.5136},
     "nachgeordnet": ["Kaiserliches Generalkonsulat", "Die Konsulate des Reiches"], "zusammen": ["Reichsamt für Verteidigung", "Reichsamt für Wirtschaft und Energie"]},
    {"schl": "inneres", "name": "Reichsamt des Innern", "kurz": "Inneres", "gruppe": "amt", "leitung": "Staatssekretär des Innern",
     "lead": "Das Reichsamt des Innern ordnet die innere Verwaltung des Reiches und führt die Register, auf die sich Untertanen und Behörden gleichermaßen stützen.",
     "aufgaben": ["Führt das Melde- und das Passwesen und gibt die Pässe des Reiches aus.",
                  "Ordnet die Verwaltungsorganisation der Reichsbehörden und der Reichsvertretung.",
                  "Hält Verbindung zu den Landesherren in Fragen der inneren Ordnung und achtet dabei deren Hoheit."],
     "gebaeude": {"name": "Reichsinnenamt Alt-Moabit", "text": "Sitz des Reichsamts des Innern", "lon": 13.3606, "lat": 52.5232},
     "zusammen": ["Kaiserliche Polizeibehörde", "Kaiserlicher Katastrophenschutz", "Reichsamt für Einwanderung und Staatsangehörigkeit"]},
    {"schl": "justiz", "name": "Reichsjustizamt", "kurz": "Justiz", "gruppe": "amt", "leitung": "Staatssekretär der Justiz",
     "lead": "Das Reichsjustizamt sorgt für ein einheitliches Recht im Reich und für die Ordnung der Gerichtsbarkeit.",
     "aufgaben": ["Bereitet Gesetze und Verordnungen des Reiches auf und prüft sie auf ihre Vereinbarkeit mit der Imperialen Charta.",
                  "Führt das Gesetzblatt und macht Erlasse und Gesetze amtlich bekannt.",
                  "Ordnet Strafvollzug und Haftwesen und beaufsichtigt die Gefängnisse des Reiches."],
     "gebaeude": {"name": "Reichsjustizamt Mohrenstraße", "text": "Sitz des Reichsjustizamts", "lon": 13.3857, "lat": 52.5112},
     "zusammen": ["Der Reichsgerichtshof", "Inquisition", "Der Senat"]},
    {"schl": "schatzamt", "name": "Kaiserliches Schatz- und Währungsamt", "kurz": "Schatzamt", "gruppe": "amt", "leitung": "Staatssekretär des Schatzamts", "amt": "schatzamt",
     "lead": "Das Schatzamt verwaltet das Geld des Reiches: die Währung, die Reichskasse und die Steuern.",
     "aufgaben": ["Führt die Zentralbank, die Reichskasse und die Konten der Untertanen und Behörden.",
                  "Setzt Steuern, Gebühren und die Besoldung der Reichsbeamten fest und treibt sie ein.",
                  "Verwaltet die Goldreserven und bereitet den Reichshaushalt vor."],
     "gebaeude": {"name": "Detlev-Rohwedder-Haus", "text": "Sitz des Kaiserlichen Schatz- und Währungsamts", "lon": 13.3826, "lat": 52.5084},
     "zusammen": ["Kaiserliche Zollverwaltung", "Reichsamt für Wirtschaft und Energie"]},
    {"schl": "wirtschaft", "name": "Reichsamt für Wirtschaft und Energie", "kurz": "Wirtschaft", "gruppe": "amt", "leitung": "Staatssekretär für Wirtschaft und Energie",
     "lead": "Das Reichsamt für Wirtschaft und Energie fördert Handel und Gewerbe und sorgt für eine sichere Versorgung des Reiches mit Rohstoffen und Energie.",
     "aufgaben": ["Ordnet den Handel zwischen Reich und Teilstaaten und genehmigt Gewerbe.",
                  "Überwacht die Rohstoffvorkommen und Förderstätten des Reiches.",
                  "Sichert die Versorgung mit Energie und Treibstoff."],
     "gebaeude": {"name": "Haus der Wirtschaft", "text": "Sitz des Reichsamts für Wirtschaft und Energie", "lon": 13.4000, "lat": 52.5130},
     "zusammen": ["Kaiserliches Schatz- und Währungsamt", "Reichsamt für Landwirtschaft und Ernährung"]},
    {"schl": "arbeit", "name": "Reichsamt für Arbeit und Soziales", "kurz": "Arbeit und Soziales", "gruppe": "amt", "leitung": "Staatssekretär für Arbeit und Soziales",
     "lead": "Das Reichsamt für Arbeit und Soziales wacht über Arbeit, Auskommen und soziale Sicherheit der Untertanen.",
     "aufgaben": ["Ordnet das Arbeitsrecht und den Schutz der Arbeitnehmer.",
                  "Führt die Reichsversicherung und verwaltet die Sozialkasse des Reiches.",
                  "Berät die Teilstaaten in Fragen der Fürsorge."],
     "gebaeude": {"name": "Reichsarbeitsamt Wilhelmstraße", "text": "Sitz des Reichsamts für Arbeit und Soziales", "lon": 13.3818, "lat": 52.5156},
     "zusammen": ["Kaiserliches Schatz- und Währungsamt", "Reichsamt für Gesundheit"]},
    {"schl": "landwirtschaft", "name": "Reichsamt für Landwirtschaft und Ernährung", "kurz": "Landwirtschaft", "gruppe": "amt", "leitung": "Staatssekretär für Landwirtschaft und Ernährung",
     "lead": "Das Reichsamt für Landwirtschaft und Ernährung steht dem Bauernstand bei und sichert, dass das Reich satt wird.",
     "aufgaben": ["Fördert Ackerbau, Viehzucht, Forst und Fischerei.",
                  "Sichert die Versorgung mit Getreide und anderen Nahrungsmitteln und führt die Vorratshaltung des Reiches.",
                  "Wacht über die Güte der Lebensmittel."],
     "gebaeude": {"name": "Reichslandwirtschaftsamt", "text": "Sitz des Reichsamts für Landwirtschaft und Ernährung", "lon": 13.3817, "lat": 52.5142},
     "zusammen": ["Reichsamt für Wirtschaft und Energie", "Reichsamt für Umwelt und Naturschutz"]},
    {"schl": "verteidigung", "name": "Reichsamt für Verteidigung", "kurz": "Verteidigung", "gruppe": "amt", "leitung": "Staatssekretär für Verteidigung",
     "lead": "Das Reichsamt für Verteidigung verwaltet das, was die Streitkräfte brauchen, ohne sie selbst zu führen: Haushalt, Beschaffung und Liegenschaften.",
     "aufgaben": ["Verwaltet die Verteidigungsetats des Reiches und bereitet die Beschaffung von Gerät vor.",
                  "Führt die Liegenschaften der Streitkräfte.",
                  "Hält die Verbindung zu den Stabschefs, denen die Führung der Truppe vorbehalten bleibt."],
     "bestand": "Bendlerblock", "nachgeordnet": ["Die Stabschefs (Führungsstab der Streitkräfte)"], "zusammen": ["Reichsamt für auswärtige Angelegenheiten", "Kaiserliches Schatz- und Währungsamt"]},
    {"schl": "gesundheit", "name": "Reichsamt für Gesundheit", "kurz": "Gesundheit", "gruppe": "amt", "leitung": "Staatssekretär für Gesundheit",
     "lead": "Das Reichsamt für Gesundheit wacht über die Gesundheit der Untertanen und über die Versorgung mit Arzneien.",
     "aufgaben": ["Ordnet das Heilwesen, die Ärzteschaft und die Apotheken.",
                  "Bekämpft Seuchen und leitet Impfungen.",
                  "Hält Vorräte an Arzneien und Medizintechnik für den Ernstfall bereit."],
     "gebaeude": {"name": "Reichsgesundheitsamt Friedrichstraße", "text": "Sitz des Reichsamts für Gesundheit", "lon": 13.3875, "lat": 52.5236},
     "zusammen": ["Kaiserlicher Katastrophenschutz", "Reichsamt für Arbeit und Soziales"]},
    {"schl": "verkehr", "name": "Reichsamt für Verkehr", "kurz": "Verkehr", "gruppe": "amt", "leitung": "Staatssekretär für Verkehr",
     "lead": "Das Reichsamt für Verkehr verbindet das Reich: Straße, Schiene, Wasserweg und Luft.",
     "aufgaben": ["Plant und unterhält die Reichsstraßen, Bahnstrecken und Wasserwege.",
                  "Ordnet den Verkehr zu Wasser und in der Luft und die Zulassung der Fahrzeuge.",
                  "Stimmt die Verkehrsplanung mit den Teilstaaten ab."],
     "gebaeude": {"name": "Reichsbehörde für Verkehr und Transportwesen", "text": "Sitz des Reichsamts für Verkehr", "lon": 9.9937, "lat": 53.5511},
     "zusammen": ["Reichsamt für Wirtschaft und Energie", "Reichsamt für Umwelt und Naturschutz"]},
    {"schl": "umwelt", "name": "Reichsamt für Umwelt und Naturschutz", "kurz": "Umwelt", "gruppe": "amt", "leitung": "Staatssekretär für Umwelt und Naturschutz",
     "lead": "Das Reichsamt für Umwelt und Naturschutz bewahrt Wälder, Gewässer und Luft des Reiches für kommende Geschlechter.",
     "aufgaben": ["Schützt Naturlandschaften, Gewässer und die Artenvielfalt.",
                  "Überwacht Abfälle, Abwässer und Emissionen der Gewerbe.",
                  "Berät die Teilstaaten in Fragen des Klima- und Hochwasserschutzes."],
     "gebaeude": {"name": "Reichsumweltamt Stresemannstraße", "text": "Sitz des Reichsamts für Umwelt und Naturschutz", "lon": 13.3818, "lat": 52.5057},
     "zusammen": ["Kaiserlicher Katastrophenschutz", "Reichsamt für Landwirtschaft und Ernährung"]},
    {"schl": "bildung", "name": "Reichsamt für Bildung und Forschung", "kurz": "Bildung und Forschung", "gruppe": "amt", "leitung": "Staatssekretär für Bildung und Forschung",
     "lead": "Das Reichsamt für Bildung und Forschung fördert Schulen, Hochschulen und die Wissenschaft im Reich.",
     "aufgaben": ["Setzt Rahmen für das Schul- und Hochschulwesen, dessen Hoheit bei den Teilstaaten bleibt.",
                  "Fördert Forschungsvorhaben, auch solche, die Wirtschaft und Verteidigung zugutekommen.",
                  "Vergibt die Reichsstipendien."],
     "gebaeude": {"name": "Reichsbildungsamt Kapelle-Ufer", "text": "Sitz des Reichsamts für Bildung und Forschung", "lon": 13.3716, "lat": 52.5234},
     "zusammen": ["Reichsamt für Kultur und Medien", "Reichsamt für Wirtschaft und Energie"]},
    {"schl": "bauwesen", "name": "Reichsamt für Bauwesen und Wohnen", "kurz": "Bauwesen und Wohnen", "gruppe": "amt", "leitung": "Staatssekretär für Bauwesen und Wohnen",
     "lead": "Das Reichsamt für Bauwesen und Wohnen sorgt für Wohnraum und baut die Gebäude des Reiches.",
     "aufgaben": ["Führt das Grundbuch des Reiches und die Liegenschaften der Krone.",
                  "Ordnet das Bauwesen und die Denkmalpflege.",
                  "Fördert den Wohnungsbau und die Stadtentwicklung gemeinsam mit den Teilstaaten."],
     "gebaeude": {"name": "Reichsbauamt Krausenstraße", "text": "Sitz des Reichsamts für Bauwesen und Wohnen", "lon": 13.3925, "lat": 52.5086},
     "zusammen": ["Reichsamt für Umwelt und Naturschutz", "Kaiserliches Schatz- und Währungsamt"]},
    {"schl": "kultur", "name": "Reichsamt für Kultur und Medien", "kurz": "Kultur und Medien", "gruppe": "amt", "leitung": "Staatssekretär für Kultur und Medien",
     "lead": "Das Reichsamt für Kultur und Medien pflegt das Erbe des Reiches und die Freiheit der Presse.",
     "aufgaben": ["Unterhält die Museen, Archive und Denkmäler des Reiches.",
                  "Wacht über die Presse und die Zeitungen des Reiches, deren Veröffentlichung es gegen Gebühr zulässt.",
                  "Fördert Kunst, Theater und Musik."],
     "gebaeude": {"name": "Zeughaus", "text": "Sitz des Reichsamts für Kultur und Medien", "lon": 13.3969, "lat": 52.5177},
     "zusammen": ["Reichsamt für Bildung und Forschung"]},
    {"schl": "einwanderung", "name": "Reichsamt für Einwanderung und Staatsangehörigkeit", "kurz": "Einwanderung", "gruppe": "amt", "leitung": "Staatssekretär des Reichsamts für Einwanderung",
     "lead": "Das Reichsamt für Einwanderung erteilt Einwanderern das Visum, prüft ihre Gesuche und vollzieht die Einbürgerung in den Stand der Staatsbürger.",
     "aufgaben": ["Führt das Register der Staatsbürger.", "Beurkundet Ausbürgerung und Abreise.", "Arbeitet bei der Kontrolle der Einreise mit dem Zoll zusammen."],
     "gebaeude": {"name": "Flughafengebäude Tempelhof", "text": "Sitz des Reichsamts für Einwanderung und Staatsangehörigkeit", "lon": 13.4006, "lat": 52.4756},
     "zusammen": ["Kaiserliche Zollverwaltung", "Reichsamt des Innern"]},
    {"schl": "digital", "name": "Reichsamt für digitale Infrastruktur", "kurz": "Digitale Infrastruktur", "gruppe": "amt", "leitung": "Staatssekretär für digitale Infrastruktur",
     "lead": "Das Reichsamt für digitale Infrastruktur errichtet und unterhält die digitalen Einrichtungen des Reiches.",
     "aufgaben": ["Betreibt die Netzpräsenz, die Versammlungsräume des Reiches auf Discord und die Automaten der Krone.",
                  "Wacht über den Schutz der Daten aller Untertanen, damit das Reich ohne Verfolgung und ohne fremde Dienste auskommt."],
     "gebaeude": {"name": "Berliner Fernsehturm", "text": "Sitz des Reichsamts für digitale Infrastruktur", "lon": 13.4094, "lat": 52.5208},
     "zusammen": ["Reichsamt für Verkehr"]},
]

# Weitere Gebäudetypen der Karte (Reichsorgane, Krone, Sonstiges): (Schlüssel, Name, Gruppe)
WEITERE_TYPEN = [
    ("reichstag", "Der Reichstag", "organ"), ("senat", "Der Senat", "organ"), ("reichsgerichtshof", "Der Reichsgerichtshof", "organ"),
    ("krone", "Die Krone (Residenzen)", "krone"), ("sonstiges", "Sonstiges Gebäude", "sonst"),
]
GRUPPEN = {"kanzlei": "Kronkanzleramt", "sicherheit": "Sicherheit und Ordnung", "amt": "Reichsämter", "organ": "Reichsorgane", "krone": "Krone", "sonst": "Sonstiges"}
FARBEN = {"kanzlei": 0, "sicherheit": 1, "organ": 2, "krone": 4, "amt": 5, "sonst": 6}   # Farbfeld 0–7 der Karte (siehe wiki.css .bs-geb.t0–t7)

# Bisherige Bauwerke der Karte (Name → Typ), werden auf die neuen Gebäudetypen umgestellt
BESTAND_TYPEN = {
    "Reichstagsgebäude": "reichstag", "Herrenhausgebäude": "senat", "Kammergerichtsgebäude": "reichsgerichtshof", "Bendlerblock": "verteidigung",
    "Hauptquartier des KRS": "krs", "Berliner Schloss": "krone", "Schloss Charlottenburg": "krone", "Schloss Mannheim": "sonstiges", "Jesuitenkirche Mannheim": "sonstiges",
}
BESTAND_SEITEN = {"reichstag": "informationen/der-reichstag/", "senat": "informationen/der-senat/", "reichsgerichtshof": "informationen/der-reichsgerichtshof/",
                  "verteidigung": "informationen/die-stabschefs/"}


def alle():
    return [KANZLEI] + BEHOERDEN


def seite(b):
    """Pfad der Seite einer Behörde (eigene, bereits vorhandene Seite oder die erzeugte Unterseite)."""
    return b.get("seite") or f"informationen/die-reichsbehoerden/{b['schl']}/"


def exportieren():
    typen = [{"id": b["schl"], "name": b["name"].replace("Das ", "", 1) if b["schl"] == "kanzlei" else b["name"], "gruppe": b["gruppe"], "farbe": FARBEN[b["gruppe"]], "seite": "/" + seite(b)}
             for b in alle()]
    typen += [{"id": s, "name": n, "gruppe": g, "farbe": FARBEN[g], "seite": "/" + BESTAND_SEITEN[s] if s in BESTAND_SEITEN else ""} for s, n, g in WEITERE_TYPEN]
    gebaeude = [{"typ": b["schl"], **b["gebaeude"]} for b in alle() if b.get("gebaeude")]
    return {"gruppen": GRUPPEN, "typen": typen, "gebaeude": gebaeude, "bestand_typen": BESTAND_TYPEN, "bestand_seiten": {k: "/" + v for k, v in BESTAND_SEITEN.items()}}


if __name__ == "__main__":
    ziel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reichsbehoerden.json")
    with open(ziel, "w", encoding="utf-8") as fh:
        json.dump(exportieren(), fh, ensure_ascii=False, indent=1)
    print("geschrieben:", ziel)
