"""HTML-Seiten des Dienstes im Rahmen der Website: Kopf, Navigation und Fußzeile kommen aus /var/www/imperium/404.html."""
import html
import os
import re

import config

_cache = (0, "")


def _vorlage():
    global _cache
    pfad = os.path.join(config.WEBROOT, "404.html")
    mtime = os.path.getmtime(pfad)
    if _cache[0] != mtime:
        with open(pfad, encoding="utf-8") as fh:
            text = fh.read()
        # relative Verweise gelten dank <base href="/"> der 404-Seite ab der Wurzel
        if '<base href="/">' not in text:
            text = text.replace("<head>", '<head>\n<base href="/">', 1)
        text = re.sub(r'<meta name="robots"[^>]*>', "", text)
        text = text.replace("</title>", "</title>\n<meta name=\"robots\" content=\"noindex\">", 1)
        _cache = (mtime, text)
    return _cache[1]


def seite(titel, inhalt):
    """Ganze Seite mit eigenem <title> und Inhalt in <main>."""
    text = _vorlage()
    text = re.sub(r"<title>.*?</title>", f"<title>{html.escape(titel)} – Imperium Germanicum</title>", text, 1, re.S)
    return re.sub(r'(<main id="inhalt"[^>]*>).*?(</main>)', lambda m: m.group(1) + inhalt + m.group(2), text, 1, re.S)


def hinweis(titel, text, knoepfe=(), eyebrow="Anmeldung", oben="", unten=""):
    """Einfache Hinweisseite im Stil der 404-Seite. text ist HTML; knoepfe: [(Beschriftung, Adresse, primär?)];
    oben/unten: zusätzliches HTML über der Überschrift bzw. unter den Knöpfen."""
    links = "".join(f'<a class="btn {"btn-navy" if prim else "btn-line"}" href="{html.escape(url)}">{html.escape(lbl)}</a>'
                    for lbl, url, prim in knoepfe)
    return seite(titel, f"""
<section class="notfound"><div class="wrap narrow">
  {oben}
  <span class="eyebrow">{html.escape(eyebrow)}</span>
  <h1>{html.escape(titel)}</h1>
  <p class="lead">{text}</p>
  <div class="hero-actions" style="justify-content:center">{links}</div>
  {unten}
</div></section>
""")
