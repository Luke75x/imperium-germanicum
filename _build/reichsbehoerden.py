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
    "nachgeordnet": ["Crown Estates", "Kaiserliches Reichssicherheitsamt (Nachrichtendienst)"],
}

# Gliederung nach dem Organigramm der Reichsverwaltung (Stand 13.11.2026): Kronkanzleramt (Crown Estates), darunter die Reichsbehörden; Ämter hängen an ihrer Behörde (nachgeordnet).
BEHOERDEN = [{'schl': 'crownestates',
  'name': 'Crown Estates',
  'kurz': 'Crown Estates',
  'gruppe': 'kanzlei',
  'leitung': 'Verwalter der Crown Estates',
  'lead': 'Die Crown Estates verwalten den kaiserlichen Kronbesitz. Sie sind dem Kronkanzleramt unmittelbar nachgeordnet.',
  'aufgaben': ['Verwaltet den kaiserlichen Kronbesitz und die Liegenschaften der Krone.', 'Berichtet dem Kronkanzler über Bestand und Erträge.'],
  'bestand': 'Kronkanzleramt',
  'zusammen': ['Das Kronkanzleramt']},
 {'schl': 'krs',
  'name': 'Kaiserliches Reichssicherheitsamt',
  'kurz': 'KRS',
  'gruppe': 'sicherheit',
  'leitung': 'Generaldirektor des KRS',
  'seite': 'informationen/reichssicherheitsamt/',
  'amt': 'krs',
  'lead': 'Der reichsweite und übergeordnete Nachrichtendienst, verantwortlich für den Erhalt der inneren und äußeren Sicherheit.',
  'aufgaben': ['Beschafft und wertet Informationen aus und warnt Krone, Senat und Behörden vor Gefahren, ehe sie entstehen.'],
  'bestand': 'Hauptquartier des KRS',
  'zusammen': ['Kaiserliche Polizeibehörde', 'Das Kronkanzleramt']},
 {'schl': 'polizei',
  'name': 'Kaiserliche Polizeibehörde',
  'kurz': 'Polizei',
  'gruppe': 'sicherheit',
  'leitung': 'Generaldirektor der Polizei',
  'amt': 'polizei',
  'lead': 'Die Polizei wahrt im gesamten Reichsgebiet die öffentliche Sicherheit und Ordnung und schützt Leib, Leben und Eigentum der Untertanen.',
  'aufgaben': ['Verfolgt Straftaten im ganzen Reichsgebiet und führt die Ermittlungen gemeinsam mit der Inquisition.',
               'Vollstreckt die Urteile des Reichsgerichtshofs und leistet den übrigen Reichsbehörden Amtshilfe.',
               'Arbeitet mit den Landespolizeien der Teilstaaten zusammen, deren Hoheit sie achtet.'],
  'gebaeude': {'name': 'Reichspolizeipräsidium', 'text': 'Hauptsitz der Kaiserlichen Polizeibehörde', 'lon': 13.3858, 'lat': 52.4844},
  'nachgeordnet': ['Die Landespolizeien (Amtshilfe und Fahndung)', 'Reichsbehörde für Innere Angelegenheiten'],
  'zusammen': ['Kaiserliche Großinquisition', 'Reichsbehörde für Innere Angelegenheiten']},
 {'schl': 'zoll',
  'name': 'Kaiserliche Zollverwaltung',
  'kurz': 'Zoll',
  'gruppe': 'sicherheit',
  'leitung': 'Generaldirektor des Zolls',
  'amt': 'zoll',
  'lead': 'Der Zoll wacht über den Waren- und Güterverkehr an den Grenzen des Reiches und sichert damit die Einnahmen der Krone.',
  'aufgaben': ['Erhebt Zölle und Abgaben und überwacht Ein- und Ausfuhr.',
               'Sichert die Außengrenzen des Reiches und unterstützt das Reichsamt für Migration und Einwanderung bei der Kontrolle der Einreise.',
               'Bekämpft Schmuggel und Schwarzhandel gemeinsam mit der Polizei.'],
  'gebaeude': {'name': 'Zollhaus an der Oberbaumbrücke', 'text': 'Hauptsitz der Kaiserlichen Zollverwaltung', 'lon': 13.4455, 'lat': 52.5015},
  'zusammen': ['Kaiserliches Schatz- und Währungsamt', 'Reichsamt für Migration und Einwanderung'],
  'nachgeordnet': ['Reichsamt für Migration und Einwanderung']},
 {'schl': 'katastrophenschutz',
  'name': 'Kaiserlicher Katastrophenschutz',
  'kurz': 'KKS',
  'gruppe': 'sicherheit',
  'leitung': 'Generaldirektor des KKS',
  'amt': 'katastrophenschutz',
  'lead': 'Der Katastrophenschutz bereitet das Reich auf große Schadenslagen vor, lenkt im Ernstfall die Hilfe und schützt die Bevölkerung vor Naturgewalten und '
          'Unglücken.',
  'aufgaben': ['Plant und übt den Ernstfall und hält die Warnsysteme des Reiches bereit.',
               'Lenkt bei Großschadenslagen die Hilfe der Teilstaaten.',
               'Ihm untersteht die Reichsfeuerwehr, die Brandschutz und technische Hilfe leistet und bei Bränden, Unglücken und Notlagen allerorts zur Rettung '
               'bereitsteht.'],
  'gebaeude': {'name': 'Reichsleitstelle des Katastrophenschutzes', 'text': 'Hauptsitz des Kaiserlichen Katastrophenschutzes', 'lon': 13.3517, 'lat': 52.549},
  'nachgeordnet': ['Die Reichsfeuerwehr'],
  'zusammen': ['Reichsamt für das Gesundheitswesen', 'Reichsbehörde für Innere Angelegenheiten']},
 {'schl': 'inquisition',
  'name': 'Kaiserliche Großinquisition',
  'kurz': 'Großinquisition',
  'gruppe': 'sicherheit',
  'leitung': 'Oberster Inquisitor',
  'amt': 'inquisition',
  'lead': 'Die Großinquisition ist die Staatsanwaltschaft des Reiches: Sie erhebt Anklage im Namen der Krone und wacht über die Rechtmäßigkeit der Ermittlungen.',
  'aufgaben': ['Leitet die Ermittlungen schwerer Straftaten und erhebt Anklage vor den Gerichten des Reiches.',
               'Prüft Haftbefehle und überwacht den Vollzug der Untersuchungshaft.',
               'Stellt Anträge an den Reichsgerichtshof und vertritt die Anklage in Verfahren von reichsweiter Bedeutung.'],
  'gebaeude': {'name': 'Strafjustizgebäude Moabit', 'text': 'Sitz der Inquisition', 'lon': 13.3447, 'lat': 52.5273},
  'zusammen': ['Kaiserliche Polizeibehörde', 'Der Reichsgerichtshof']},
 {'schl': 'generalkonsulat',
  'name': 'Kaiserliches Generalkonsulat',
  'kurz': 'Generalkonsulat',
  'gruppe': 'verwaltung',
  'leitung': 'Generalkonsul',
  'lead': 'Das Generalkonsulat vertritt das Reich und seine Untertanen in der Fremde und pflegt die Verbindungen zu befreundeten Staaten und Gemeinschaften.',
  'aufgaben': ['Vertritt das Reich und seine Untertanen im Ausland und stellt ihnen Schutz und Beistand.',
               'Unterhält die Konsulate des Reiches; der Souverän ernennt und entlässt die Konsuln, der Kronkanzler verwaltet sie in seinem Namen.',
               'Führt den diplomatischen Verkehr der Konsulate und bereitet Verträge und Abkommen vor.'],
  'gebaeude': {'name': 'Auswärtiges Amt', 'text': 'Sitz des Kaiserlichen Generalkonsulats', 'lon': 13.3965, 'lat': 52.5136},
  'nachgeordnet': ['Die Konsulate des Reiches'],
  'zusammen': ['Das Kronkanzleramt']},
 {'schl': 'schatzamt',
  'name': 'Kaiserliches Schatz- und Währungsamt',
  'kurz': 'Schatzamt',
  'gruppe': 'verwaltung',
  'leitung': 'Staatssekretär des Schatzamts',
  'amt': 'schatzamt',
  'lead': 'Das Schatzamt verwaltet das Geld des Reiches: die Währung, die Reichskasse und die Steuern.',
  'aufgaben': ['Führt die Zentralbank, die Reichskasse und die Konten der Untertanen und Behörden.',
               'Setzt Steuern, Gebühren und die Besoldung der Reichsbeamten fest und treibt sie ein.',
               'Verwaltet die Goldreserven und bereitet den Reichshaushalt vor.'],
  'gebaeude': {'name': 'Detlev-Rohwedder-Haus', 'text': 'Sitz des Kaiserlichen Schatz- und Währungsamts', 'lon': 13.3826, 'lat': 52.5084},
  'zusammen': ['Kaiserliche Zollverwaltung', 'Reichskasse'],
  'nachgeordnet': ['Zentralbank', 'Reichskasse']},
 {'schl': 'heroldsamt',
  'name': 'Heroldsamt',
  'kurz': 'Heroldsamt',
  'gruppe': 'verwaltung',
  'leitung': 'Oberherold',
  'lead': 'Das Heroldsamt hütet die Wappen, Standarten und Siegel des Reiches und wacht über ihre rechtmäßige Führung.',
  'aufgaben': ['Führt die Wappenrolle des Reiches und prüft die Führung von Wappen, Standarten und Siegeln.',
               'Berät Krone und Behörden in Fragen von Zeremoniell, Rangfolge und Hoheitszeichen.',
               'Entwirft und beglaubigt die Hoheitszeichen der Reichsbehörden.'],
  'gebaeude': {'name': 'Zeughaus', 'text': 'Sitz des Heroldsamts', 'lon': 13.3969, 'lat': 52.5177},
  'zusammen': ['Das Kronkanzleramt']},
 {'schl': 'inneres',
  'name': 'Reichsbehörde für Innere Angelegenheiten',
  'kurz': 'Innere Angelegenheiten',
  'gruppe': 'amt',
  'leitung': 'Staatssekretär für Innere Angelegenheiten',
  'lead': 'Die Reichsbehörde für Innere Angelegenheiten ordnet die innere Verwaltung des Reiches und führt die Register, auf die sich Untertanen und Behörden '
          'gleichermaßen stützen. Sie ist der Kaiserlichen Polizeibehörde zugeordnet.',
  'aufgaben': ['Führt das Melde- und das Passwesen und gibt die Pässe des Reiches aus.',
               'Ordnet die Verwaltungsorganisation der Reichsbehörden und der Reichsvertretung.',
               'Hält Verbindung zu den Landesherren in Fragen der inneren Ordnung und achtet dabei deren Hoheit.'],
  'gebaeude': {'name': 'Reichsinnenamt Alt-Moabit', 'text': 'Sitz des Reichsamts des Innern', 'lon': 13.3606, 'lat': 52.5232},
  'zusammen': ['Kaiserliche Polizeibehörde', 'Kaiserlicher Katastrophenschutz'],
  'nachgeordnet': ['Reichsamt für Forschung',
                   'Reichsamt für das Gesundheitswesen',
                   'Reichsamt für das Verkehrs- und Transportwesen',
                   'Reichsamt für das Arbeits- und Sozialwesen']},
 {'schl': 'forschung',
  'name': 'Reichsamt für Forschung',
  'kurz': 'Forschung',
  'gruppe': 'amt',
  'leitung': 'Staatssekretär für Forschung',
  'lead': 'Das Reichsamt für Forschung fördert die Wissenschaft im Reich.',
  'aufgaben': ['Fördert Forschungsvorhaben, auch solche, die Wirtschaft und Verteidigung zugutekommen.',
               'Setzt Rahmen für die Forschung, deren Hoheit bei den Teilstaaten bleibt.',
               'Vergibt die Reichsstipendien.'],
  'gebaeude': {'name': 'Reichsforschungsamt Kapelle-Ufer', 'text': 'Sitz des Reichsamts für Forschung', 'lon': 13.3716, 'lat': 52.5234},
  'zusammen': ['Reichsbehörde für Innere Angelegenheiten', 'Reichsamt für das Gesundheitswesen']},
 {'schl': 'gesundheit',
  'name': 'Reichsamt für das Gesundheitswesen',
  'kurz': 'Gesundheit',
  'gruppe': 'amt',
  'leitung': 'Staatssekretär für Gesundheit',
  'lead': 'Das Reichsamt für Gesundheit wacht über die Gesundheit der Untertanen und über die Versorgung mit Arzneien.',
  'aufgaben': ['Ordnet das Heilwesen, die Ärzteschaft und die Apotheken.',
               'Bekämpft Seuchen und leitet Impfungen.',
               'Hält Vorräte an Arzneien und Medizintechnik für den Ernstfall bereit.'],
  'gebaeude': {'name': 'Reichsgesundheitsamt Friedrichstraße', 'text': 'Sitz des Reichsamts für Gesundheit', 'lon': 13.3875, 'lat': 52.5236},
  'zusammen': ['Kaiserlicher Katastrophenschutz', 'Reichsamt für das Arbeits- und Sozialwesen']},
 {'schl': 'verkehr',
  'name': 'Reichsamt für das Verkehrs- und Transportwesen',
  'kurz': 'Verkehr und Transport',
  'gruppe': 'amt',
  'leitung': 'Staatssekretär für das Verkehrs- und Transportwesen',
  'lead': 'Das Reichsamt für das Verkehrs- und Transportwesen verbindet das Reich: Straße, Schiene, Wasserweg und Luft.',
  'aufgaben': ['Plant und unterhält die Reichsstraßen, Bahnstrecken und Wasserwege.',
               'Ordnet den Verkehr zu Wasser und in der Luft und die Zulassung der Fahrzeuge.',
               'Stimmt die Verkehrsplanung mit den Teilstaaten ab.'],
  'gebaeude': {'name': 'Reichsbehörde für Verkehr und Transportwesen', 'text': 'Sitz des Reichsamts für Verkehr', 'lon': 9.9937, 'lat': 53.5511},
  'zusammen': ['Reichsbehörde für Innere Angelegenheiten', 'Reichsamt für Forschung']},
 {'schl': 'arbeit',
  'name': 'Reichsamt für das Arbeits- und Sozialwesen',
  'kurz': 'Arbeit und Soziales',
  'gruppe': 'amt',
  'leitung': 'Staatssekretär für das Arbeits- und Sozialwesen',
  'lead': 'Das Reichsamt für das Arbeits- und Sozialwesen wacht über Arbeit, Auskommen und soziale Sicherheit der Untertanen.',
  'aufgaben': ['Ordnet das Arbeitsrecht und den Schutz der Arbeitnehmer.',
               'Führt die Reichsversicherung und verwaltet die Sozialkasse des Reiches.',
               'Berät die Teilstaaten in Fragen der Fürsorge.'],
  'gebaeude': {'name': 'Reichsarbeitsamt Wilhelmstraße', 'text': 'Sitz des Reichsamts für Arbeit und Soziales', 'lon': 13.3818, 'lat': 52.5156},
  'zusammen': ['Kaiserliches Schatz- und Währungsamt', 'Reichsamt für das Gesundheitswesen']},
 {'schl': 'einwanderung',
  'name': 'Reichsamt für Migration und Einwanderung',
  'kurz': 'Migration und Einwanderung',
  'gruppe': 'amt',
  'leitung': 'Staatssekretär des Reichsamts für Migration und Einwanderung',
  'lead': 'Das Reichsamt für Migration und Einwanderung erteilt Einwanderern das Visum, prüft ihre Gesuche und vollzieht die Einbürgerung in den Stand der Staatsbürger. '
          'Es ist der Kaiserlichen Zollverwaltung zugeordnet.',
  'aufgaben': ['Führt das Register der Staatsbürger.', 'Beurkundet Ausbürgerung und Abreise.', 'Arbeitet bei der Kontrolle der Einreise mit dem Zoll zusammen.'],
  'gebaeude': {'name': 'Flughafengebäude Tempelhof', 'text': 'Sitz des Reichsamts für Migration und Einwanderung', 'lon': 13.4006, 'lat': 52.4756},
  'zusammen': ['Kaiserliche Zollverwaltung', 'Reichsbehörde für Innere Angelegenheiten']},
 {'schl': 'zentralbank',
  'name': 'Zentralbank',
  'kurz': 'Zentralbank',
  'gruppe': 'amt',
  'leitung': 'Präsident der Zentralbank',
  'lead': 'Die Zentralbank steuert die Währung des Reiches und führt die Konten der Untertanen und Behörden. Sie ist dem Kaiserlichen Schatz- und Währungsamt '
          'nachgeordnet.',
  'aufgaben': ['Sichert die Währung des Reiches und führt die Konten.', 'Verwaltet die Goldreserven gemeinsam mit dem Schatzamt.'],
  'bestand': 'Detlev-Rohwedder-Haus',
  'zusammen': ['Kaiserliches Schatz- und Währungsamt', 'Reichskasse']},
 {'schl': 'reichskasse',
  'name': 'Reichskasse',
  'kurz': 'Reichskasse',
  'gruppe': 'amt',
  'leitung': 'Reichskassenverwalter',
  'lead': 'Die Reichskasse verwahrt die Einnahmen des Reiches und zahlt dessen Ausgaben. Sie ist dem Kaiserlichen Schatz- und Währungsamt nachgeordnet.',
  'aufgaben': ['Verwahrt die Einnahmen aus Steuern, Zöllen und Abgaben.', 'Zahlt Besoldung und Etats der Reichsbehörden aus.'],
  'bestand': 'Detlev-Rohwedder-Haus',
  'zusammen': ['Kaiserliches Schatz- und Währungsamt', 'Zentralbank']}]

# Weitere Gebäudetypen der Karte (Reichsorgane, Krone, Sonstiges): (Schlüssel, Name, Gruppe)
WEITERE_TYPEN = [
    ("reichstag", "Der Reichstag", "organ"), ("senat", "Der Senat", "organ"), ("reichsgerichtshof", "Der Reichsgerichtshof", "organ"),
    ("krone", "Die Krone (Residenzen)", "krone"), ("sonstiges", "Sonstiges Gebäude", "sonst"),
]
GRUPPEN = {"kanzlei": "Kronkanzleramt", "sicherheit": "Sicherheit und Ordnung", "verwaltung": "Verwaltung und Finanzen", "amt": "Nachgeordnete Ämter", "organ": "Reichsorgane", "krone": "Krone", "sonst": "Sonstiges"}
FARBEN = {"kanzlei": 0, "sicherheit": 1, "verwaltung": 3, "organ": 2, "krone": 4, "amt": 5, "sonst": 6}   # Farbfeld 0–7 der Karte (siehe wiki.css .bs-geb.t0–t7)

# Bisherige Bauwerke der Karte (Name → Typ), werden auf die neuen Gebäudetypen umgestellt
BESTAND_TYPEN = {
    "Reichstagsgebäude": "reichstag", "Herrenhausgebäude": "senat", "Kammergerichtsgebäude": "reichsgerichtshof", "Bendlerblock": "sonstiges",
    "Hauptquartier des KRS": "krs", "Berliner Schloss": "krone", "Schloss Charlottenburg": "krone", "Schloss Mannheim": "sonstiges", "Jesuitenkirche Mannheim": "sonstiges",
}
BESTAND_SEITEN = {"reichstag": "informationen/der-reichstag/", "senat": "informationen/der-senat/", "reichsgerichtshof": "informationen/der-reichsgerichtshof/"}


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
