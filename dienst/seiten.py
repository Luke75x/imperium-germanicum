"""HTML-Seiten des Dienstes im Rahmen der Website: Kopf, Navigation und Fußzeile kommen aus /var/www/imperium/404.html."""
import html
import os
import re
import time

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


def _konto_html(konto, csrf, pfad):
    """Konto in der Kopfleiste (Stil .topbar .wiki-user aus wiki.css)."""
    if not konto:
        return (f'<span class="wiki-user"><a href="/anmelden/?weiter={html.escape(pfad)}">'
                '<span class="lbl">Anmelden</span></a></span>')
    return (f'<span class="wiki-user"><span><span class="lbl">{html.escape(konto["name"])}</span></span>'
            f'<form method="post" action="/abmelden/"><input type="hidden" name="csrf" value="{html.escape(csrf)}">'
            f'<input type="hidden" name="weiter" value="{html.escape(pfad)}"><button type="submit">Abmelden</button></form></span>')


def seite(titel, inhalt, kopf="", body_klasse="", konto=None, csrf="", pfad=None, lang="de", canonical=None):
    """Ganze Seite mit eigenem <title> und Inhalt in <main>.
    kopf: zusätzliche Einträge im <head>; pfad: zeigt das Konto in der Kopfleiste (Anmelden/Abmelden)."""
    text = _vorlage()
    text = re.sub(r"<title>.*?</title>", lambda m: f"<title>{html.escape(titel)} – Imperium Germanicum</title>", text, 1, re.S)
    if pfad is not None and "wiki.css" not in kopf:   # Kopfleiste mit Konto (.wiki-user) ist in wiki.css gestaltet
        kopf += f'\n<link rel="stylesheet" href="/assets/css/wiki.css?v={int(time.time() // 86400)}">'
    if kopf:
        text = text.replace("</head>", kopf + "\n</head>", 1)
    if canonical:
        text = re.sub(r'<link rel="canonical" href="[^"]*">', lambda m: f'<link rel="canonical" href="{config.SITE_URL}{canonical}">', text, 1)
    if lang != "de":
        text = text.replace('<html lang="de">', f'<html lang="{lang}">', 1)
    if body_klasse:
        text = text.replace("<body>", f'<body class="{body_klasse}">', 1)
    if pfad is not None:
        text = text.replace('<div class="topbar-tools">', '<div class="topbar-tools">' + _konto_html(konto, csrf, pfad), 1)
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
