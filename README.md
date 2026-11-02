# Imperium-Bot

Discord-Bot des Imperium Germanicum (discord.py). Wiederhergestellt am 02.11.2026 aus den Angaben der Website
(github.com/Luke75x/imperium-germanicum), da der ursprüngliche Code nicht gesichert war.

## Module
- `info_kanal.py`: `/info-kanal` (Admins) schreibt „Richtlinien des Servers“ und „Zu welchem Zeitpunkt gilt die Rolle?“
  in den Informationskanal und übernimmt das Regelwerk danach auf die Website (`regelwerk_holen.py` + `deploy.sh`).
- `gesetzblatt.py`: neuer Beitrag im Reichsgesetzblatt-Forum → DM an den Kaiser → nach Bestätigung auf die Website.
  Erst aktiv, wenn `GESETZBLATT_FORUM` und `KAISER_ID` in `config.py` gesetzt sind.

## Betrieb
- Geheimnisse: `/root/.env` (`DISCORD_TOKEN`, `DISCORD_CLIENT_SECRET`), nicht im Repo.
- Website-Repo: `/root/imperium_germanicum`, Webroot `/var/www/imperium`.
- Einrichten: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, `apt install poppler-utils`.
- Dienst: `cp imperium-bot.service /etc/systemd/system/ && systemctl enable --now imperium-bot`
- Log: `journalctl -u imperium-bot -f`
