#!/bin/bash
# Prüft, ob die Reichskarte lädt (Seite, Geodaten über nginx und über den Dienst).
# Schlägt das zweimal hintereinander fehl, wird der Dienst neu gestartet. Gedacht für einen systemd-Timer alle 2 Minuten
# (Units: imperium-karte-pruefung.service/.timer im Repo-Hauptordner; NICHT eingerichtet, siehe README).
H=imperiumgermanicum.de
ZUSTAND=/run/imperium-karte-pruefung
C=(curl -fsS -m 25 -o /dev/null --resolve $H:443:127.0.0.1 -H "Accept-Encoding: gzip")
seite=$(curl -fsS -m 15 --resolve $H:443:127.0.0.1 https://$H/karte/ 2>/dev/null)
fehler=""
[ -n "$seite" ] || fehler="Seite /karte/ nicht erreichbar"
if [ -z "$fehler" ]; then
  stat=$(echo "$seite" | grep -o '"geo": "[^"]*"' | head -1 | cut -d'"' -f4)
  alt=$(echo "$seite" | grep -o '"geoAlt": "[^"]*"' | head -1 | cut -d'"' -f4)
  [ -n "$stat" ] && { "${C[@]}" "https://$H$stat" || fehler="Geodatei $stat nicht abrufbar"; }
  [ -n "$alt" ] && { "${C[@]}" "https://$H$alt" || fehler="Geodatei $alt nicht abrufbar"; }
fi
if [ -z "$fehler" ]; then rm -f "$ZUSTAND"; echo "Karte ok"; exit 0; fi
n=$(( $(cat "$ZUSTAND" 2>/dev/null || echo 0) + 1 )); echo $n > "$ZUSTAND"
logger -t imperium-karte-pruefung "Fehler $n: $fehler"; echo "Fehler $n: $fehler"
if [ "$n" -ge 2 ]; then
  logger -t imperium-karte-pruefung "Dienst wird neu gestartet"
  systemctl restart imperium-dienst; rm -f "$ZUSTAND"
fi
