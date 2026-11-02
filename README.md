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
- Seiten nutzen Kopf/Fußzeile aus `/var/www/imperium/404.html` (`seiten.py`).

## Betrieb
- Geheimnisse in `/root/.env`: `DISCORD_TOKEN` (Bot) und `DISCORD_CLIENT_SECRET` (OAuth).
- Dienst: `imperium-dienst.service`, Log mit `journalctl -u imperium-dienst -f`
- nginx: `location ^~ /anmelden/` und `/abmelden/` in `/etc/nginx/sites-available/imperium-germanicum.conf`,
  Proxy-Header in `/etc/nginx/imperium-dienst-proxy.conf`
- Löschwunsch: `.venv/bin/python konto_loeschen.py <discord-id>`
- Einrichten: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
