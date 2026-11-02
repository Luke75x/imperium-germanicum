# Rekonstruktion der Reichskarte (02.11.2026)

Der frühere Kartenstand (welches NUTS-3-Gebiet zu welchem Teilstaat gehört) war verloren. Erhalten war nur das alte
MapChart-Bild `assets/img/original/i74e21fe796eaa5e0.jpg` (3000 × 2325 px) im Website-Repo. Daraus wurde der Startstand gewonnen:

1. `projektionen.py`: Land/Meer-Maske des Bildes mit verschiedenen Projektionen verglichen. Am besten passt die
   Lambert-flächentreue Azimutalprojektion (10° O, 52° N, wie EPSG:3035) mit 98,7 % Übereinstimmung → `karte_daten/rekonstruktion/projektionen.json`.
2. `farben.py`: Mittlere Farbe jedes NUTS-3-Gebiets im alten Bild (Rand weggelassen, Legende ausgespart).
3. `zuordnen.py`: Farbe → Teilstaat (Legendenfarben); Gebiete unter der Legende über ihre Nachbarn geschätzt.
4. `glaetten_vorschau.py`: Unsichere Kleinstädte über ihre Nachbarn, Vergleichsbild alt/neu. Danach von Hand korrigiert:
   Bremen und Bremerhaven → Hansebund, Passau → Pfalz, Schaffhausen und Genf → Schweiz → `karte_daten/rekonstruktion/zuordnung_final.json`.
5. `../karte_bauen.py`: baut daraus `geo.json`, `bevoelkerung.json` und `startstand.json`.

Unsicher sind vor allem Gebiete in Nordfrankreich/Benelux, die im alten Bild unter der Legende lagen.
Die Skripte erwarten die Eurostat/GISCO-Rohdaten (siehe `karte_bauen.py`) und numpy, shapely, Pillow.
