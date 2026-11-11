# Imperium-Dienst

Dynamischer Teil von imperiumgermanicum.de (aiohttp, läuft hinter nginx auf 127.0.0.1:8090).
Neu aufgebaut am 02.11.2026, da der frühere „Wiki-Dienst“ nicht gesichert war.

## Module
- `anmeldung.py`: Anmeldung über Discord (OAuth2, Scope `identify`). Prüft die Mitgliedschaft auf dem Server
  und die Rollen per Bot-Token und speichert Konto + Sitzung in `daten/dienst.db` (SQLite).
  - `GET /anmelden/?weiter=/pfad/`: zu Discord bzw. Statusseite mit Abmelden-Knopf
  - `GET /anmelden/rueckruf`: Rückkehr von Discord (so im Developer Portal eingetragen)
  - `POST /abmelden/`: Formular mit `csrf` und `weiter`
  - `GET /anmelden/status`: JSON (`angemeldet`, `id`, `name`, `rollen`, `admin`, `csrf`) für Seiten-Skripte
  - Für neue Module: `await anmeldung.konto(request)` bzw. der Dekorator `@anmeldung.angemeldet(prüfung)`
- Cookies: `ig_sitzung` (30 Tage), `ig_anmeldung` (10 Minuten, Absicherung des Anmeldevorgangs).
  Das entspricht der Datenschutzerklärung der Website.
- `organigramme.py`: Organigramm des Reiches (`/informationen/organigramm/`, staatsaufbau.js) und der Reichsverwaltung
  (`/informationen/die-reichsbehoerden/organigramm/`, organigramm.js), jeweils auch unter `/en/…`.
  - `<pfad>`: Anzeige, `<pfad>bearbeiten/`: Editor (nur Server-Admins), `<pfad>info.json`: Amtsträger live aus Discord,
    `POST <pfad>speichern`: neuer Stand mit Konflikterkennung, `<pfad>organigramm.png`: Bild für die Startseite
  - Jeder gespeicherte Stand ist eine Zeile in `organigramm_versionen` (Autor, Bemerkung, Zeit); der jüngste gilt.
  - Startstand in `organigramme_start.py` (Neuaufbau 02.11.2026; der frühere Stand ist verloren).
  - Datenschutz: `info.json` nennt nur Amtsträger mit Namen; Mitglieder werden nur gezählt.
- `karte.py`: Reichskarte (`/karte/`, `/en/karte/`, karte.js) auf 1352 NUTS-3-Gebieten mit 19 Teilstaaten.
  - Anzeige mit Legende und Gebietsfenster (Regent, Einwohner, Fläche, Anteile), Editor `/karte/bearbeiten/` (nur Admins),
    `daten.json` (Stand), `info.json` (Einwohner, Regenten, eigene Rechte/Anträge), `geo.json`, `karte.png` (Startseite).
  - Regent = Landesherr mit der Fraktionsrolle des Teilstaats; ohne Fraktionsrolle verwaltet der Kronkanzler.
  - Gebietsnamen im Rollenspiel: Regenten beantragen (`POST /karte/antrag`, DM an den Kronkanzler), der Kronkanzler entscheidet auf
    `/karte/antraege/` (DM an den Antragsteller) oder setzt Namen direkt (`POST /karte/gebietsname`).
  - Versionen in `karte_versionen`, Anträge in `karte_antraege`. Startstand aus der alten Karte rekonstruiert
    (`werkzeuge/karte_rekonstruktion/LIESMICH.md`), Geodaten von `werkzeuge/karte_bauen.py` (Eurostat/GISCO, © EuroGeographics).
- `karte_bild.py`: zeichnet `karte.png` mit Pillow (Muster, Legende wie die alte Karte), beim Start und nach jeder Version.
- `bild.py`: erzeugt `organigramm.png` mit Playwright-Chromium (`.browser/`), beim Start und nach jedem Speichern.
- Seiten nutzen Kopf/Fußzeile aus `/var/www/imperium/404.html` (`seiten.py`), mit Anmelden/Abmelden in der Kopfleiste.
- `reichstag.py`: Reichstag (04.11.2026). Interne Ansicht `/informationen/der-reichstag/intern/` (auch /en) mit Reitern Übersicht · Sitzungen · Anträge (Filter) · Archiv · Abstimmungsverhalten: Sitzungen ankündigen, Anträge
  auf die Tagesordnung setzen/sortieren/entfernen, Sitzung eröffnen/beenden/absagen, Abstimmung je Abgeordnetem erfassen, Archiv mit
  Abstimmungsverhalten (`archiv/`, `abgeordnete/<id>/`, `sitzung/<id>/`, `antrag/<id>/`). Zugang: Rollen Reichstag/Abgeordneter/Präsidium/Landesherr
  (Konstanten oben im Modul), bearbeiten darf das Präsidium und Admins. Ankündigung im Kanal 📨｜anträge (wird bei Änderungen der
  Tagesordnung bearbeitet), Ergebnisse beim Beenden im Kanal 📁｜beschlüsse. Tabellen `reichstag_*`. Anträge kommen vom Bot-Befehl `/antrag`
  über `POST /intern-api/reichstag/antrag` (Header `X-Bot-Token`, nginx leitet den Pfad nicht weiter).
- Hauptstädte (04.11.2026): Jeder Teilstaat kann `hauptstadt: {name, x, y}` (Weltkoordinaten) im Stand tragen. Editor: Feld „Hauptstadt“ im Teilstaat-Dialog
  (Ortsname aus der Liste setzt die Lage, sonst Mitte des größten Teils) und Werkzeug „Hauptstadt“ (Teilstaat wählen, auf die Karte klicken). Anzeige:
  Stern mit fettem Namen ab Kartenstufe 3,4 (`bs-hs` in wiki.css), Zeile „Hauptstadt“ im Gebietsfenster, Stern auch in `karte.png` (`karte_bild.py`).
- Königsberg (04.11.2026): Das Kaliningrader Gebiet ist als Gebiet `RU001` (Name „Kaliningrad“, im Stand „Königsberg“, Land RU) Teil der Karte, weil die NUTS-Daten
  keine Gebiete außerhalb der EU enthalten. Erzeugt von `werkzeuge/karte_gebiet_koenigsberg.py` (braucht shapely; Sicherungen `karte_daten/*.vor-koenigsberg`,
  nicht im Repo). Einwohner 1 029 966 (Volkszählung 2021) statt Eurostat. Bei einem Neubau der Karte mit `karte_welt.py` muss das Skript danach erneut laufen.
- Zuverlässiges Laden der Karte (04.11.2026): Autobahnen und Bahnstrecken sind von der Karte entfernt (Daten, `karte.js`, Bild, Kontrollkästchen; Sicherungen
  `karte_daten/*.vor-verkehr`). Die Geodaten liefert nginx versioniert und vorverdichtet unter `/karte-daten/geo-<mtime>.json(.gz)` aus
  `/var/lib/imperium-karte` (legt der Dienst beim Start im Hintergrund an, alte Versionen werden gelöscht, nginx `location ^~ /karte-daten/` mit `gzip_static`),
  unabhängig vom Dienst. `karte.js` lädt mit bis zu 6 Versuchen abwechselnd statisch und über `/karte/geo.json` (Zeitlimit 60 s, wachsende Wartezeit), zeigt sonst
  Hinweis + „Erneut versuchen“ + Kartenbild. Die Route des Dienstes verdichtet nicht mehr im Request (blockierte früher den Dienst). `RestartSec=2`.
  `werkzeuge/karte_pruefung.sh` mit `imperium-karte-pruefung.service/.timer` prüft die Karte alle 2 Minuten und startet den Dienst nach zwei Fehlern neu; die Units sind im Repo,
  aber nicht eingerichtet (`cp imperium-karte-pruefung.* /etc/systemd/system/ && systemctl enable --now imperium-karte-pruefung.timer`).
- Handy-Darstellung (04.11.2026): Seiten des Dienstes lade `wiki.css` immer mit (`seiten.seite`, Kopfleiste mit Konto). Reichstag: Reiter scrollen einzeilig, Tabellen
  werden unter 700 px zu Karten (`rt-stack`, Spaltenüberschrift je Zelle per `data-label`), Auswahlfelder/Knöpfe mind. 44 px. `wiki.css`: größere Tippflächen in der
  Kopfleiste und im Karteneditor, ab 380 px ohne Kontoname in der Kopfleiste (sonst wird die Seite bei 320 px breiter als der Bildschirm). Geprüft per Playwright-Emulation
  (390/360/320 px, Touch) auf Überlauf, Tippflächen und Dialoge.

## Betrieb
- Geheimnisse in `/root/.env`: `DISCORD_TOKEN` (Bot) und `DISCORD_CLIENT_SECRET` (OAuth).
- Dienst: `imperium-dienst.service`, Log mit `journalctl -u imperium-dienst -f`
- nginx: `location ^~` für `/anmelden/`, `/abmelden/` und die vier Organigramm-Pfade sowie `/karte/` und `/en/karte/` in `/etc/nginx/sites-available/imperium-germanicum.conf`,
  Proxy-Header in `/etc/nginx/imperium-dienst-proxy.conf`
- Löschwunsch: `.venv/bin/python konto_loeschen.py <discord-id>`
- Einrichten: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`,
  danach `PLAYWRIGHT_BROWSERS_PATH=.browser .venv/bin/playwright install --with-deps chromium`

## Kartendetails (03.11.2026)
`werkzeuge/karte_details.py` ergänzt `karte_daten/geo.json` um `kanten` (Grenzabschnitte zwischen Gebieten), `mitte`, `orte`, `meere`, `laender_namen`, `netz`.
`karte.js` zeichnet daraus Staats-/Landes-/Kreisgrenzen und Namen (Teilstaaten, Orte nach Zoomstufe, Meere, Nachbarländer); `karte_bild.py` ebenso fürs Startseitenbild.
Organigramm: Auswahl der Wappen im Editor nur aus `organigramme.WAPPEN` (keine Personenbilder), mit Rasteransicht und Hover-Vorschau.

## Weltkarte (03.11.2026)
Die Karte ist jetzt eine Web-Mercator-Weltkarte (Welt 40000×40000 Einheiten). `werkzeuge/karte_welt.py` baut aus GISCO NUTS 1:1 Mio. und Natural Earth
`karte_daten/geo.json` (grob, sofort) und `geo_fein.json` (fein, wird ab Kartenstufe 5 nachgeladen; ersetzt Gebietspfade, Kanten, Land, Seen, Flüsse, Orte).
Kartenstufe in `karte.js` (`stufe()`) entspricht Kachelstufen; Orte/Länder/Meere tragen Natural-Earth-Mindeststufen. Rohdaten werden nicht im Repo gehalten
(Download siehe Kopf des Skripts). `karte_details.py` ist damit überholt. Regenten: nur höchster Titel; Zusatzämter (ROLLEN_AEMTER) bei Fraktionsrolle.

## Bauwerke (03.11.2026; Verkehrswege seit 04.11.2026 entfernt)
`werkzeuge/karte_ofm_holen.py` holt OpenFreeMap-Kacheln (OSM), `werkzeuge/karte_infra.py` schreibt daraus Autobahnen (`strassen`), Hauptstrecken (`bahn`) und die Bauwerke der Website (`bauwerke`, Liste BAUWERKE im Skript) in geo.json/geo_fein.json.
Reihenfolge nach Neubau der Karte: karte_welt.py → karte_infra.py. Quellenhinweis: © OpenStreetMap-Mitwirkende (ODbL). karte.js: Autobahnen ab Stufe 5,2, Bahn ab 5,8, Bauwerke ab 7,2 (Namen ab 8,6); ab Stufe 7,2 die feine Fassung; Linien mit butt/miter und optimizeSpeed (sonst ruckelt das Verschieben).
- `amt.py` + `amt_icons.py` (03.11.2026): Amtsseite der Reichsbehörden unter `/informationen/die-reichsbehoerden/intern/` (nginx `location ^~`, Backup
  `/root/imperium-germanicum.conf.bak-amt`). Eigenständige, schlichte Behördenoptik (eigenes CSS in `amt.py`, eigene Navigation, Lucide-Icons inline aus
  `amt_icons.py`, erzeugt mit `werkzeuge/lucide_icons.js`), nicht im Website-Rahmen. Zugang: Rollen Zollverwaltung/Kronkanzler und Admins (`ROLLEN_ZUGANG`).
  Seiten: Übersicht (Zur Bearbeitung, Kennzahlen, letzte Vorgänge), Bürgerakten (Suche, Filter, Akte mit Stammdaten, Vorgängen, Vermerken), Einbürgerungsakten
  (Phase I/II, Vermerke, Verfahren beenden). Tabellen `amt_akten` (BA-nnnnn, je Staatsbürger; Abgleich mit den Discord-Rollen beim Start und alle 15 Min),
  `amt_verfahren` (EB-jjjj-nnnn, je Einreiseverfahren), `amt_eintraege` (Vorgänge/Vermerke). Der Bot füllt sie über `/intern-api/amt/einreise|einbuergerung|ticket-geschlossen`
  (Header `X-Bot-Token`, nur lokal). Frühere Einbürgerungen vor dem 03.11.2026 haben nur die Bürgerakte, keine Einbürgerungsakte (Daten nicht vorhanden).
- Amtsseite, Ergänzung (03.11.2026): Zugang zusätzlich für die IDs 463089934765391872 (Kaiser), 1526348059984789504 und 1522693216053235903 (`ZUGANG_IDS`, gelten als Nutzer- oder Rollen-ID). Neu: Statistiken (`statistik/`: Fraktion, Schicht, Beruf, Ergebnisse, Einbürgerungen je Monat, Dauer),
  Bürgerakte löschen (`buerger/<id>/loeschen/`, Bestätigung per Aktenzeichen + Grund, optional Einbürgerungsakten mit; Protokoll in `amt_loeschungen`, Seite `protokoll/`; der Abgleich legt gelöschte Konten nicht neu an) und
  PDF-Export (`…/pdf` für Bürgerakte, Einbürgerungsakte, Statistiken; Playwright-Chromium aus `.browser`, A4, nacheinander).
- Amtsseite, Ergänzung 2 (03.11.2026): **Unter Verschluss** (`amt_akten.verschluss`): Kaiser (`config.KAISER_ID`) und Kronkanzler (Rolle 1561856444913946664) setzen/heben es in der Bürgerakte (`POST buerger/<id>/verschluss`, Eintrag in den Vorgängen).
  Alle anderen sehen die Akte nur als Zeile „Unter Verschluss“ in den Listen/Übersicht; Bürger- und Einbürgerungsakte (gilt für alle Verfahren der Person), PDF, Bearbeiten, Vermerk, Löschen, Verfahren beenden antworten mit 403 und „Sie haben keinen Zugang“.
  **Nur Lesezugriff** (`LESE_IDS`: Rolle 1522913765035606086, KRS): sieht alle nicht verschlossenen Akten, Statistiken und PDFs, aber keine Formulare/Knöpfe; alle POST-Routen prüfen `ist_beamter` (Schreibrecht).
- `privatbesitz.py` (11.11.2026): Privatwirtschaft – Fahrzeuge, Immobilien, Sonstiges aus einem Katalog (pb_katalog, Preise in €), Besitz pb_besitz, Seite `/schatzamt/besitz/`
  (privat), Verwaltung `/schatzamt/amt/besitz/` (Leitung). Laufende Kosten monatlich (Steuer → Staatskasse des Standorts, Versicherung/Unterhalt → Volkswirtschaft),
  Rückstand, Pfändung nach 3 Monaten; Einstellung „privatbesitz“. Details im Modulkopf.
- `suche.py` (11.11.2026): Stichwortsuche im Schatzamt-Portal (`/schatzamt/suche/`, Vorschläge per `&json=1`), Index je Konto nach Berechtigung; Suchleiste in der Kopfzeile
  (`amt.rahmen` portal["suche"]). Direktsprung bei klarem Treffer, z. B. „Goldreserve Pfalz-Bayern“ → `/schatzamt/gold/#g-ts-<sid>`.
