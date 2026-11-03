# Imperium-Bot

Discord-Bot des Imperium Germanicum (discord.py). Wiederhergestellt am 02.11.2026 aus den Angaben der Website
(github.com/Luke75x/imperium-germanicum), da der ursprüngliche Code nicht gesichert war.

## Module
- `info_kanal.py`: `/info-kanal` (Admins) schreibt „Richtlinien des Servers“ und „Zu welchem Zeitpunkt gilt die Rolle?“
  in den Informationskanal und übernimmt das Regelwerk danach auf die Website (`regelwerk_holen.py` + `deploy.sh`).
- `gesetzblatt.py`: neuer Beitrag im Reichsgesetzblatt-Forum → DM an den Kaiser → nach Bestätigung auf die Website.
  Erst aktiv, wenn `GESETZBLATT_FORUM` und `KAISER_ID` in `config.py` gesetzt sind.
- `zollamt.py`: Kaiserliches Zollamt. Beitritt → Visum-Embed in Thread „Erteilte Aufenthaltsvisen“, Austritt → „Aufenthaltvisum
  abgelaufen“ in Thread „Abgelaufene Aufenthaltsvisen“, `/einbürgern @Person` (nur Rolle Zollverwaltung) → Modal mit IC-Name →
  6 Rollen, Umbenennung, Embed in Thread „Erfolgreiche Einbürgerungen“. IDs in `config.py`. Braucht den Members-Intent.
- `ticket.py`: Ticketsystem der Einwanderungsbehörde. Das Panel (Nachricht 1565507299345436713, Auswahlmenü `einreise-panel`)
  öffnet ein Modal (IC-Name, Geschichte, Vorstellung) → privater Thread `einreise-<name>` mit den Antworten, Antragsteller und
  Zollverwaltung; Knopf „Ticket schließen“ archiviert und sperrt. Ein offenes Ticket pro Person, Bedienelemente persistent.
- `audienz.py`: Betritt der Kaiser den Sprachkanal Audienzzimmer (1523025487847227402), kommt eine DM „Generalaudienz öffnen?“
  mit Ja/Nein. Ja → Embed „Generalaudienz“ (Bilder in `sicherung/`) in den News-Kanal 1522995542047723581.
- `antrag.py`: `/antrag` (Reichstags-Rollen) → Modal (Betreff, Antragstext, Begründung) → Imperium-Dienst legt den Antrag an
  (siehe `reichstag.py` im Dienst) und veröffentlicht ihn im Anträge-Kanal.
- `serverantrag.py`: `/serverantrag` (jeder Nutzer) → Modal (Ereignis, Beschreibung, betroffene Charaktere, Zeitpunkt) → Embed in
  📄｜anträge 1567217562477928528 mit Knöpfen Akzeptieren/Abweisen (Abweisen mit optionaler Begründung); der Antragsteller bekommt
  zu jeder Entscheidung eine DM. Entscheiden darf, wer den Kanal sehen kann. Persistent, ohne Datenbank (Antragsteller-ID im Footer).
- `haft.py`: `/entlassen` (vorzeitig, zuständige Stelle), `/u-haft` und `/haft` (Rolle Reichsgerichtshof), `/krs-haft` (Reichssicherheitsamt). Alle Rollen weg + Häftling bzw. KRS-Häftling,
  nach Ablauf kommen die Rollen zurück (bei `/haft` bleiben die Auszeichnungsrollen bis einschließlich des Trenners, „rollen-nach-haft: Nein“ gibt nichts zurück,
  Dauer optional = unbefristet). Fälle in `haft.db` (nicht im Repo), Ablauf prüft ein Hintergrundlauf alle 30 s; Haftrolle von Hand entfernen = vorzeitige
  Entlassung. Log jeder Ausführung und jedes Endes in den Thread `HAFT_LOG`.
- `newsflash.py`: `/newsflash [deckblatt] [artikelbild]` öffnet ein Formular (Zeitungsname, Schlagzeile, Verfasser optional, Inhalt) → Zeitungsartikel in 📰｜news (Zeitungskopf mit automatischem Datum und optionalem Deckblatt-Bild, darunter Schlagzeile, Verfasserzeile, Text, optionales Artikelbild). Landesherren und Admins sofort; Staatsbürger ohne Landesherr müssen
  einmalig freigeschaltet werden (erste Meldung = Antrag im Prüf-Thread, Knopf „Freischalten und veröffentlichen“); Treffer der Filterliste
  `newsflash_filter.txt` (jederzeit editierbar) gehen vor der Veröffentlichung in den Prüf-Thread. DM an den Verfasser bei jeder Entscheidung.
  Daten in `newsflash.db`, Deckblätter wartender Meldungen in `newsflash_bilder/` (beides nicht im Repo).
- `einstellen.py` + `dienstgrade.py`: `/einstellen person institution dienstgrad` (Landesherren, Kaiser). Institutionen und Dienstgrade stammen aus der Dienstgrad-Tabelle
  (Beschluss im Reichsgesetzblatt) und den Discord-Rollen: Marine, Heer, Luftwaffe, Reichssicherheitsamt, Polizei, Zoll, Katastrophenschutz (Inquisition hat keine Rollen).
  Bis OF-5 sofort; ab OF-6 Antrag mit Knöpfen im Genehmigungs-Thread, nur der Kaiser entscheidet. Einstellung = Institutionsrolle + „Abteilungen“ + Dienstgrad + Gruppenrolle,
  Beförderung ersetzt die alten Dienstgrad-Rollen der Institution. Log jeder Ausführung im Personal-Log-Thread. Dienstgrade ändern sich in `dienstgrade.py` (RAENGE).

## Betrieb
- Geheimnisse: `/root/.env` (`DISCORD_TOKEN`, `DISCORD_CLIENT_SECRET`), nicht im Repo.
- Website-Repo: `/root/imperium_germanicum`, Webroot `/var/www/imperium`.
- Einrichten: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, `apt install poppler-utils`.
- Dienst: `cp imperium-bot.service /etc/systemd/system/ && systemctl enable --now imperium-bot`
- Log: `journalctl -u imperium-bot -f`

## Sicherung
`sicherung/info_kanal_sicherung.json` enthält alle Nachrichten des Informationskanals (Stand 02.11.2026: Willkommen,
Richtlinien, Rollenspiel, Informationen und Links, Server-Abonnements, Einladung) samt Link-Knöpfen,
`sicherung/banner/` die Banner-Bilder dazu.
