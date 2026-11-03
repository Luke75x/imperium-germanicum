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
  - Regent = Landesherr mit der Fraktionsrolle des Teilstaats; ohne Fraktionsrolle verwaltet der Kanzler.
  - Gebietsnamen im Rollenspiel: Regenten beantragen (`POST /karte/antrag`, DM an den Kanzler), der Kanzler entscheidet auf
    `/karte/antraege/` (DM an den Antragsteller) oder setzt Namen direkt (`POST /karte/gebietsname`).
  - Versionen in `karte_versionen`, Anträge in `karte_antraege`. Startstand aus der alten Karte rekonstruiert
    (`werkzeuge/karte_rekonstruktion/LIESMICH.md`), Geodaten von `werkzeuge/karte_bauen.py` (Eurostat/GISCO, © EuroGeographics).
- `karte_bild.py`: zeichnet `karte.png` mit Pillow (Muster, Legende wie die alte Karte), beim Start und nach jeder Version.
- `bild.py`: erzeugt `organigramm.png` mit Playwright-Chromium (`.browser/`), beim Start und nach jedem Speichern.
- Seiten nutzen Kopf/Fußzeile aus `/var/www/imperium/404.html` (`seiten.py`), mit Anmelden/Abmelden in der Kopfleiste.

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
