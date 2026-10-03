# Imperium Germanicum – Website

Statische, schnelle Website (HTML/CSS/JS) mit PHP-Formularverarbeitung. Keine Cookies, kein Tracking, keine externen Dienste.

## Veröffentlichen
1. Den gesamten Ordnerinhalt **ohne** `_build/` per FTP in das Wurzelverzeichnis des Webspace laden (Apache + PHP ≥ 8.0).
2. In `api/config.php` die Absenderadresse auf eine E-Mail-Adresse **der eigenen Domain** setzen.
3. In `_build/site.py` die Konstante `SITE_URL` auf die echte Domain setzen und neu erzeugen (siehe unten).
4. Die `.htaccess` leitet alle alten Jimdo-Adressen (`/der-souverän/`, `/about/`, `/j/privacy` …) dauerhaft auf die neuen Seiten um.

## Inhalte ändern
Alle Texte stehen in `_build/site.py` (Seiten), `_build/etikette.py` (Etiketten-Guide) und `_build/charta.json` (Charta).
Danach im Projektordner ausführen:

```
python _build/site.py
```

Neue Bilder in `assets/img/original/` ablegen und einmalig `python _build/bilder.py` ausführen (benötigt `pip install pillow`).
Die Bild-ID (Dateiname ohne Endung) kann dann in `site.py` verwendet werden.

## Lokale Vorschau
```
python -m http.server 8000
```
und `http://localhost:8000` öffnen. (Formulare benötigen einen PHP-Server.)
