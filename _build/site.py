"""Statischer Seitengenerator für die Website des Imperium Germanicum.

Aufruf (im Projektordner):
    python _build/bilder.py   # nur nach neuen Bildern in assets/img/original
    python _build/site.py     # erzeugt alle HTML-Seiten, sitemap.xml und robots.txt

Alle Inhalte stehen in dieser Datei (Seitenfunktionen), in etikette.py und charta.json.
"""
import html
import json
import os
import re

import etikette

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SITE_URL = "https://imperiumgermanicum.de"  # bei Domainwechsel anpassen (Canonical, Sitemap, OG)
YEAR = 2026

with open(os.path.join(HERE, "bilder.json"), encoding="utf-8") as fh:
    IMAGES = json.load(fh)

INSTAGRAM = "https://www.instagram.com/das_imperium_germanicum?igsh=MWs5dWJwdXdzYXgyZQ=="
YOUTUBE = "https://youtube.com/@imperiumgermanicum?si=9u5nQkK9O9SOq-6q"
EMAIL = "das.imperium.germanicum@gmail.com"

LOGO = "i92158683d4a0cca4"

esc = html.escape

# ---------------------------------------------------------------------------
# Icons (eigene, schlichte Strichgrafiken)
# ---------------------------------------------------------------------------

ICONS = {
    "arrow": '<path d="M3 8h10M9 4l4 4-4 4"/>',
    "chev": '<path d="M3 6l5 5 5-5"/>',
    "zoom": '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14M7 5v4M5 7h4"/>',
    "close": '<path d="M3 3l10 10M13 3L3 13"/>',
    "prev": '<path d="M10 3L5 8l5 5"/>',
    "next": '<path d="M6 3l5 5-5 5"/>',
    "print": '<path d="M4 6V2h8v4M4 12H2V7h12v5h-2M4 10h8v4H4z"/>',
    "link": '<path d="M7 9a3 3 0 004.2 0l2-2a3 3 0 00-4.2-4.2l-.8.8M9 7a3 3 0 00-4.2 0l-2 2a3 3 0 004.2 4.2l.8-.8"/>',
    "search": '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/>',
    "ext": '<path d="M9 2h5v5M14 2L7 9M12 10v4H2V4h4"/>',
    "mail": '<rect x="1.5" y="3" width="13" height="10" rx="1"/><path d="M2 4l6 5 6-5"/>',
    "insta": '<rect x="2" y="2" width="12" height="12" rx="3.5"/><circle cx="8" cy="8" r="2.8"/><circle cx="11.6" cy="4.4" r=".6" fill="currentColor"/>',
    "yt": '<rect x="1.5" y="3.5" width="13" height="9" rx="2.5"/><path d="M6.8 6v4l3.4-2z" fill="currentColor"/>',
    "download": '<path d="M8 2v8M4.5 6.5L8 10l3.5-3.5M2 13h12"/>',
}


def icon(name):
    return (f'<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


# ---------------------------------------------------------------------------
# Bilder
# ---------------------------------------------------------------------------

class Ctx:
    """Hält das relative Präfix der gerade gerenderten Seite."""
    prefix = ""


def u(path):
    """Relativer Link zu einem Seitenpfad (z. B. 'kontakt/')."""
    return (Ctx.prefix + path) or "./"


def asset(path):
    return Ctx.prefix + "assets/" + path


def img(iid, alt, sizes="100vw", cls="", eager=False, extra=""):
    m = IMAGES[iid]
    w, h = m["w"], m["h"]
    w1280 = min(w, 1280)
    h1280 = round(h * w1280 / w)
    srcset = ""
    if w > 640:
        srcset = (f' srcset="{asset(f"img/{iid}-640.webp")} 640w, '
                  f'{asset(f"img/{iid}-1280.webp")} {w1280}w" sizes="{sizes}"')
    loading = 'fetchpriority="high"' if eager else 'loading="lazy"'
    c = f' class="{cls}"' if cls else ""
    return (f'<img src="{asset(f"img/{iid}-1280.webp")}"{srcset} width="{w1280}" height="{h1280}" '
            f'alt="{esc(alt)}" {loading} decoding="async"{c}{extra}>')


def original(iid):
    return asset("img/original/" + IMAGES[iid]["file"])


def zoom_link(iid, inner, caption="", group="", cls="zoom"):
    g = f' data-gallery="{group}"' if group else ""
    return (f'<a class="{cls}" href="{original(iid)}" data-lightbox data-full="{asset(f"img/{iid}-1280.webp")}"'
            f' data-caption="{esc(caption)}"{g}>{inner}'
            f'<span class="zoom-hint">{icon("zoom")}</span>'
            f'<span class="sr-only"> – Bild vergrößern</span></a>')


def figure(iid, caption="", alt=None, cls="", sizes="(min-width: 900px) 50vw, 100vw", group="", frame=True, zoom=True):
    alt = alt if alt is not None else caption
    inner = img(iid, alt, sizes)
    if zoom:
        inner = zoom_link(iid, inner, caption, group, cls="zoom frame" if frame else "zoom")
    elif frame:
        inner = f'<span class="frame">{inner}</span>'
    cap = f"<figcaption>{esc(caption)}</figcaption>" if caption else ""
    return f'<figure class="figure {cls}">{inner}{cap}</figure>'


def emblem(iid, caption="", alt=None, sizes="(min-width: 900px) 360px, 70vw"):
    return figure(iid, caption, alt, cls="emblem", sizes=sizes, frame=False, zoom=False)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

INSTITUTIONEN = [
    # pfad, kurzname, titel, beschreibung, emblem
    ("informationen/imperiale-charta/", "Imperiale Charta", "Imperiale Charta",
     "Die Verfassung des Imperium Germanicum", "i2e330402e5d67b0a"),
    ("informationen/etiketten-guide/", "Etiketten-Guide", "Der Etiketten-Guide",
     "Eine Anleitung zur Einhaltung der Etikette und Höflichkeit innerhalb des Reiches", "i1ed8e9913dc91849"),
    ("informationen/hand-des-kaisers/", "Hand des Kaisers", "Die Hand des Kaisers",
     "Erfahre mehr über den zweiten Mann im Staat", "i87afe1585055e89f"),
    ("informationen/der-senat/", "Der Senat", "Der kaiserliche Senat",
     "Erfahre mehr über das höchste exekutive Gremium im Reich", "i14d08011977ebcfa"),
    ("informationen/der-reichstag/", "Der Reichstag", "Der Reichstag",
     "Erfahre mehr über die legislative Versammlung aller Teilstaaten des Imperium Germanicum", "ifc5f3f77d4236032"),
    ("informationen/der-reichsgerichtshof/", "Der Reichsgerichtshof", "Der Reichsgerichtshof",
     "Erfahre mehr über das höchste Gericht des Imperium Germanicums", "i0d34f4c1f760e0b3"),
    ("informationen/die-stabschefs/", "Die Stabschefs", "Die Stabschefs der kaiserlichen Streitkräfte",
     "Erfahre mehr über die gemeinsamen Stabschefs der Teilstaaten über das Militär des Imperium Germanicum",
     "i95c5a2d03728088a"),
    ("informationen/reichssicherheitsamt/", "Reichssicherheitsamt", "Kaiserliches Reichssicherheitsamt",
     "Erfahre mehr über das KRS als gemeinsamen übergeordneten Nachrichten- und Sicherheitsdienst der Teilstaaten des Reiches",
     "idf73bcf2259c33f2"),
]

NAV = [
    ("", "Hauptseite"),
    ("informationen/", "Informationen"),
    ("der-souveraen/", "Der Souverän"),
    ("die-bildergalerie/", "Die Bildergalerie"),
    ("neue-erlasse-und-gesetze/", "Neue Erlasse und Gesetze"),
]


def nav_html(current):
    items = []
    for path, label in NAV:
        cur = ' aria-current="page"' if current == path else ""
        if path == "informationen/":
            section = current.startswith("informationen/")
            sub = []
            for p, short, _t, desc, emb in INSTITUTIONEN:
                c = ' aria-current="page"' if current == p else ""
                sub.append(
                    f'<li><a href="{u(p)}"{c}>{img(emb, "", "44px")}'
                    f'<span><strong>{esc(short)}</strong><small>{esc(desc)}</small></span></a></li>')
            items.append(
                f'<li class="has-sub{" is-section" if section else ""}">'
                f'<div class="nav-parent"><a href="{u(path)}"{cur}>{label}</a>'
                f'<button class="nav-toggle-sub" type="button" aria-expanded="false" aria-controls="subnav-info">'
                f'<span class="sr-only">Untermenü {label} öffnen</span>{icon("chev")}</button></div>'
                f'<div class="subnav" id="subnav-info"><div class="subnav-head"><span>Staatsaufbau</span>'
                f'<a class="link-arrow" href="{u(path)}">Alle Institutionen {icon("arrow")}</a></div>'
                f'<ul>{"".join(sub)}</ul></div></li>')
        else:
            items.append(f'<li><a href="{u(path)}"{cur}>{label}</a></li>')
    cur = ' aria-current="page"' if current == "kontakt/" else ""
    items.append(f'<li class="nav-cta"><a href="{u("kontakt/")}"{cur}>Kontakt</a></li>')
    return f'<nav class="nav-main" id="nav-main" aria-label="Hauptnavigation"><ul>{"".join(items)}</ul></nav>'


def header(current):
    return f"""
<a class="skip-link" href="#inhalt">Zum Inhalt springen</a>
<div class="progress" aria-hidden="true"></div>
<div class="topbar">
  <div class="wrap">
    <span class="topbar-note">Das interaktive Rollenspiel – für Monarchie-, Adels-, Militär- und Geschichtsliebhaber</span>
    <div class="topbar-links">
      <a href="{INSTAGRAM}" rel="noopener" target="_blank">{icon("insta")}Instagram</a>
      <a href="{YOUTUBE}" rel="noopener" target="_blank">{icon("yt")}YouTube</a>
      <a href="mailto:{EMAIL}">{icon("mail")}E-Mail</a>
    </div>
  </div>
</div>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="{u("")}" aria-label="Imperium Germanicum – zur Hauptseite">
      {img(LOGO, "", "56px", eager=True)}
      <span class="brand-text"><span class="brand-name">Imperium Germanicum</span><span class="brand-sub">Das Rollenspiel</span></span>
    </a>
    <button class="menu-button" type="button" aria-expanded="false" aria-controls="nav-main"><span class="bars"><i></i></span><span class="menu-label">Menü</span></button>
    {nav_html(current)}
  </div>
</header>"""


CROWNS = [
    ("i2990580d50400cfc", "Kaiserliche Staatskrone", "Krone seiner Majestät dem Kaiser"),
    ("i23c1241b7ac79d7f", "", "Krone ihrer Majestät der Kaiserin"),
    ("i7843be5e8c7b2235", "", "Krone seiner kaiserlichen und königlichen Hoheit der Hand des Kaisers"),
]


def crowns():
    figs = []
    for iid, title, cap in CROWNS:
        t = f"<strong>{title}</strong>" if title else ""
        figs.append(f'<figure>{img(iid, cap, "(min-width: 720px) 230px, 180px")}<figcaption>{t}{cap}</figcaption></figure>')
    return f"""
<section class="crowns" aria-labelledby="kronen-titel">
  <div class="wrap">
    <div class="section-head center">
      <div class="ornament center"><i></i></div>
      <h2 id="kronen-titel">Die Kronen des Reiches</h2>
    </div>
    <div class="grid">{"".join(figs)}</div>
  </div>
</section>"""


def address_html():
    return """Imperium Germanicum<br>Das Rollenspiel<br>Kaiser-Wilhelm-Straße 45<br>67054 Ludwigshafen am Rhein<br>Deutschland"""


def footer():
    staat = "".join(f'<li><a href="{u(p)}">{esc(s)}</a></li>' for p, s, *_ in INSTITUTIONEN)
    main = "".join(f'<li><a href="{u(p)}">{l}</a></li>' for p, l in NAV) + f'<li><a href="{u("kontakt/")}">Kontakt</a></li>'
    return f"""
<footer class="site-footer">
  <div class="wrap footer-main">
    <div class="footer-brand">
      {img(LOGO, "", "72px")}
      <span class="brand-name">Imperium Germanicum</span>
      <span>Ein fiktiver Staatenbund in Europa – das interaktive Rollenspiel.</span>
      <address>{address_html()}</address>
    </div>
    <div>
      <h2>Navigation</h2>
      <ul>{main}</ul>
    </div>
    <div>
      <h2>Staatsaufbau</h2>
      <ul>{staat}</ul>
    </div>
    <div>
      <h2>Kontakt</h2>
      <ul class="social">
        <li><a href="mailto:{EMAIL}">{icon("mail")}{EMAIL}</a></li>
        <li><a href="{INSTAGRAM}" rel="noopener" target="_blank">{icon("insta")}das_imperium_germanicum</a></li>
        <li><a href="{YOUTUBE}" rel="noopener" target="_blank">{icon("yt")}Imperium Germanicum</a></li>
      </ul>
    </div>
  </div>
  <div class="footer-legal">
    <div class="wrap">
      <span>© {YEAR} Imperium Germanicum – Das Rollenspiel</span>
      <ul>
        <li><a href="{u("impressum/")}">Impressum</a></li>
        <li><a href="{u("datenschutz/")}">Datenschutz</a></li>
        <li><a href="{u("datenschutz/")}#cookies">Cookie-Richtlinie</a></li>
        <li><a href="{u("sitemap/")}">Sitemap</a></li>
        <li><a href="{u("gewaehrleistung/")}">Gesetzliche Gewährleistung</a></li>
        <li><a href="{u("widerruf/")}">Vertrag widerrufen</a></li>
      </ul>
    </div>
  </div>
</footer>"""


def breadcrumb(crumbs):
    if not crumbs:
        return ""
    parts = [f'<li><a href="{u("")}">Hauptseite</a></li>']
    for i, (path, label) in enumerate(crumbs):
        if i == len(crumbs) - 1:
            parts.append(f'<li><span aria-current="page">{esc(label)}</span></li>')
        else:
            parts.append(f'<li><a href="{u(path)}">{esc(label)}</a></li>')
    return f'<nav class="breadcrumb" aria-label="Brotkrumen"><ol>{"".join(parts)}</ol></nav>'


def page_head(crumbs, title, eyebrow="", lead="", dark=False):
    e = f'<span class="eyebrow">{esc(eyebrow)}</span>' if eyebrow else ""
    l = f'<p class="lead">{lead}</p>' if lead else ""
    return f"""
<div class="page-head{" dark" if dark else ""}">
  <div class="wrap">
    {breadcrumb(crumbs)}
    {e}
    <h1>{title}</h1>
    {l}
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Seitenrahmen
# ---------------------------------------------------------------------------

PAGES = []  # (pfad, priorität) für die sitemap.xml


def render(path, title, description, body, current=None, robots="index,follow", in_sitemap=True,
           og_image="og-image.jpg", jsonld=None, show_crowns=True):
    depth = path.count("/")
    Ctx.prefix = "../" * depth
    current = path if current is None else current
    full_title = "Imperium Germanicum – Das interaktive Rollenspiel" if path == "" else f"{title} – Imperium Germanicum"
    canonical = f"{SITE_URL}/{path}"
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    doc = f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{canonical}">
<meta name="theme-color" content="#12183c">
<meta property="og:type" content="website">
<meta property="og:locale" content="de_DE">
<meta property="og:site_name" content="Imperium Germanicum">
<meta property="og:title" content="{esc(full_title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE_URL}/assets/{og_image}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{asset("favicon.ico")}" sizes="any">
<link rel="icon" href="{asset("favicon-32.png")}" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="{asset("apple-touch-icon.png")}">
<link rel="preload" href="{asset("fonts/eb-garamond.woff2")}" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{asset("fonts/source-sans-3.woff2")}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{asset("css/site.css")}">
<script src="{asset("js/site.js")}" defer></script>
{ld}
</head>
<body>
{header(current)}
<main id="inhalt" tabindex="-1">
{body}
</main>
{crowns() if show_crowns else ""}
{footer()}
</body>
</html>
"""
    doc = re.sub(r"\n\s*\n", "\n", doc)
    out_dir = os.path.join(ROOT, path)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)
    if in_sitemap:
        PAGES.append(path)


def card(path, title, desc, emb, cta, index=""):
    idx = f'<span class="card-index">{index}</span>' if index else ""
    return f"""
<article class="card reveal">
  <div class="card-media">{img(emb, "", "(min-width: 1000px) 190px, 40vw")}</div>
  <div class="card-body">
    {idx}
    <h3><a href="{u(path)}">{esc(title)}</a></h3>
    <p>{esc(desc)}</p>
    <span class="link-arrow">{cta} {icon("arrow")}</span>
  </div>
</article>"""


def aside_staatsaufbau(current):
    links = "".join(
        f'<li><a href="{u(p)}"{" aria-current=\"page\"" if p == current else ""}>{esc(t)}</a></li>'
        for p, _s, t, *_ in INSTITUTIONEN)
    return f"""
<aside class="aside-nav" aria-label="Staatsaufbau">
  <h2>Staatsaufbau</h2>
  <ul><li><a href="{u("informationen/")}">Übersicht</a></li>{links}</ul>
  <div class="aside-box">
    <p>Interesse geweckt? Werde ein Teil des Imperium Germanicum.</p>
    <a class="link-arrow" href="{u("kontakt/")}">Melde dich zum Dienst {icon("arrow")}</a>
  </div>
</aside>"""


def person(iid, role, name, detail="", link=None, horizontal=False, alt=None):
    d = f'<span class="detail">{detail}</span>' if detail else ""
    l = ""
    if link:
        l = f'<a class="ext" href="{link[0]}" rel="noopener" target="_blank">{icon("insta")}{esc(link[1])}</a>'
    portrait = zoom_link(iid, img(iid, alt or name, "(min-width: 760px) 300px, 100vw"),
                         f"{role}: {name}" if role else name, "personen", cls="zoom portrait")
    return f"""
<figure class="person{" horizontal" if horizontal else ""} reveal">
  {portrait}
  <figcaption><span class="role">{role}</span><span class="name">{name}</span>{d}{l}</figcaption>
</figure>"""


def paras(*texts):
    return "".join(f"<p>{t}</p>" for t in texts)


# ---------------------------------------------------------------------------
# Seiten
# ---------------------------------------------------------------------------

def page_home():
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Imperium Germanicum – Das Rollenspiel",
        "url": SITE_URL + "/",
        "logo": f"{SITE_URL}/assets/img/{LOGO}-640.webp",
        "email": EMAIL,
        "address": {"@type": "PostalAddress", "streetAddress": "Kaiser-Wilhelm-Straße 45",
                    "postalCode": "67054", "addressLocality": "Ludwigshafen am Rhein", "addressCountry": "DE"},
        "sameAs": [INSTAGRAM.split("?")[0], YOUTUBE.split("?")[0]],
    }
    Ctx.prefix = ""
    overview = [
        ("informationen/imperiale-charta/", "Die Imperiale Charta", "Die Verfassung des Imperium Germanicum",
         "ib9634bff3a382755", "Verfassung lesen"),
        ("informationen/etiketten-guide/", "Der Etiketten-Guide",
         "Eine Anleitung zur Einhaltung der Etikette und Höflichkeit innerhalb des Reiches", "idc5356a6b49c7ad5",
         "Guide lesen"),
        ("informationen/hand-des-kaisers/", "Die Hand des Kaisers", "Erfahre mehr über den zweiten Mann im Staat",
         "id00b4acc3f5d8ad8", "Kartei lesen"),
        ("informationen/der-senat/", "Der kaiserliche Senat",
         "Erfahre mehr über das höchste exekutive Gremium im Reich", "i921660718e056bad", "Kartei lesen"),
    ]
    cards = "".join(card(p, t, d, e, c, f"{i:02d}") for i, (p, t, d, e, c) in enumerate(overview, 1))
    body = f"""
<section class="hero on-dark" aria-labelledby="hero-titel">
  <div class="wrap">
    <div>
      <span class="eyebrow">Für Monarchie-, Adels-, Militär- und Geschichtsliebhaber</span>
      <h1 id="hero-titel">Das interaktive <em>Rollenspiel</em></h1>
      <p class="lead">Das Imperium Germanicum ist ein fiktiver Staatenbund in Europa, basierend auf den Grenzen des früheren Heiligen Römischen Reiches, es stellt eine alternative Gegenwart dar, in der das Heilige Römische Reich die Jahre überdauert hat und sich bis in die heutige Zeit weiterentwickelt hat.</p>
      <div class="hero-actions">
        <a class="btn btn-gold" href="{u("kontakt/")}">Melde dich zum Dienst {icon("arrow")}</a>
        <a class="btn btn-line" href="{u("informationen/imperiale-charta/")}">Die Imperiale Charta</a>
      </div>
    </div>
    <figure class="hero-seal">
      {img("idbbec25dc54e06be", "Großes Wappen des Imperium Germanicum", "(min-width: 900px) 460px, 300px", eager=True)}
    </figure>
  </div>
</section>

<section class="facts" aria-label="Das Reich in Zahlen">
  <div class="wrap">
    <dl>
      <div><dt>Hoheitsgebiet</dt><dd>1.205.000 km²</dd></div>
      <div><dt>Staatsbürger</dt><dd>217.000.000</dd></div>
      <div><dt>Kurfürsten im Senat</dt><dd>9</dd></div>
      <div><dt>Amtszeit des Kaisers</dt><dd>1 Jahr</dd></div>
    </dl>
  </div>
</section>

<section class="section" aria-labelledby="reich-titel">
  <div class="wrap split wide-left top">
    <div class="prose reveal">
      <span class="eyebrow">Das Reich</span>
      <h2 id="reich-titel">Das Resultat dieser Entwicklung ist das Imperium Germanicum.</h2>
      {paras(
        "Das Imperium Germanicum besteht wie schon sein historisches Vorbild aus unzähligen kleineren Staaten, darunter verschiedene Fürstentümer, Königreiche, Herzogtümer und andere Gebietskörperschaften.",
        "Sehr weit oben in der Hierarchie befinden sich die 9 Kurfürsten welche die 9 Landesoberhäupter der wichtigsten Teilstaaten des Reiches sind, sie bilden den sogenannten kaiserlichen Senat.",
        "Eine der wichtigsten Aufgaben des Senats ist die Wahl des Souveräns und Staatsoberhaupts des Imperium Germanicum, des Kaisers.",
        "Der Kaiser wird für 1 Jahr aus einem der 9 Kurfürsten gewählt und eine Wiederwahl ist unbegrenzt möglich.",
      )}
      <p><strong>Haben diese Informationen dein Interesse geweckt?</strong><br>Schau dich gerne auf unserer Website um und werde ein Teil des Imperium Germanicum.</p>
      <a class="link-arrow" href="{u("informationen/")}">Zum Staatsaufbau {icon("arrow")}</a>
    </div>
    <div class="reveal">
      {figure("i7e284b3dc2b8cebd", "Staatsaufbau des Imperium Germanicum", "Schaubild zum Staatsaufbau des Imperium Germanicum: Souverän, Senat, Reichstag, Reichsgerichtshof und Staatsbürger", group="start")}
    </div>
  </div>
</section>

<section class="section paper" aria-labelledby="gebiet-titel">
  <div class="wrap split wide-right">
    <div class="reveal">
      {figure("i77eeb0ab8a9e395a", "Hoheitsgebiet des Imperium Germanicum mit seinen Teilstaaten", "Karte des Hoheitsgebiets des Imperium Germanicum in Mittel- und Südeuropa mit farbig markierten Teilstaaten", group="start")}
    </div>
    <div class="prose reveal">
      <span class="eyebrow">Mittel- und Südeuropa</span>
      <h2 id="gebiet-titel">Hoheitsgebiet des Imperium Germanicum</h2>
      {paras(
        "Das Imperium Germanicum befindet sich in Mittel- und Südeuropa und umfasst ein Hoheitsgebiet von 1.205.000 km².",
        "Das Königreich Apulien ist aufgrund der Personalunion des Kaiserthrons mit dem Königsthron de facto ein Teil des Imperiums, sowie der Heilige Stuhl in dessen Gebiet seine Heiligkeit der Papst eine besondere Stellung innehat, jedoch seine Majestät der Kaiser die militärische und zivile Verwaltung kontrolliert.",
        "Das Imperium Germanicum ist zudem als teilzentralisierter Bundesstaat organisiert.",
        "Das Imperium besteht aus vielen Teilstaaten unterschiedlicher Größe, welche ihre inneren Angelegenheiten zumeist selbst bestimmen.",
        "Hier gilt die von der Charta vorgeschriebene Regel, dass das Reichsrecht das Landesrecht bricht, wenn es Differenzen zwischen Gesetzen gibt.",
        "Das gesamte Imperium Germanicum umfasst daher 217.000.000 Staatsbürger.",
        "9 der Teilstaaten des Imperiums sind sogenannte Kurfürstentümer deren jeweiliges Landesoberhaupt als Kurfürst einen Sitz im Senat, dem exekutiven Organ des Imperiums innehat.",
        "Alle anderen Landesoberhäupter haben mit ihrer jeweiligen Delegation einen Sitz im Reichstag, dem legislativen Organ des Imperiums.",
      )}
    </div>
  </div>
</section>

<section class="section" aria-labelledby="ueberblick-titel">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Institutionen &amp; Verfassung</span>
      <h2 id="ueberblick-titel">Ein kleiner Überblick</h2>
      <p class="lead">Ein kleiner Vorgeschmack auf einige unserer zahlreichen Institutionen und die Verfassung des Reiches</p>
    </div>
    <div class="card-grid cols-4">{cards}</div>
  </div>
</section>

<section class="section navy on-dark" aria-labelledby="souveraen-titel">
  <div class="wrap split wide-right">
    <div class="reveal">{emblem("ie6ecf3d509ef6fc3", "", "Emblem des Kaisers: Schloss Charlottenburg mit dem Schriftzug Der Kaiser")}</div>
    <div class="prose reveal">
      <span class="eyebrow">Staatsoberhaupt</span>
      <h2 id="souveraen-titel">Der Souverän</h2>
      {paras(
        "Der Souverän ist das offizielle Staatsoberhaupt des Imperium Germanicums, Amtsträger, Offiziere und Richter schwören ihm die Treue.",
        "Der Souverän ernennt und entlässt die Beamten und Richter sowie Konsule des Reiches und bestellt sie nach Belieben ein, außerdem besitzt der Souverän die Möglichkeit Verurteilte zu begnadigen und über Dekrete gewisse Entscheidungen temporär ohne den Senat zu treffen.",
        "Der Souverän ist der höchste Repräsentant des Reiches und genießt als solcher die höchste Würde, der Souverän hat immer das Recht angehört zu werden.",
      )}
      <div class="hero-actions" style="margin-top:28px">
        <a class="btn btn-gold" href="{u("der-souveraen/")}">Seine Majestät Alexander IX. {icon("arrow")}</a>
      </div>
    </div>
  </div>
</section>"""
    render("", "Hauptseite",
           "Das Imperium Germanicum ist ein fiktiver Staatenbund in Europa – das interaktive Rollenspiel für Monarchie-, Adels-, Militär- und Geschichtsliebhaber.",
           body, jsonld=jsonld)


def page_informationen():
    Ctx.prefix = "../"
    cards = "".join(card(p, t, d, e, "Mehr erfahren", f"{i:02d}") for i, (p, _s, t, d, e) in enumerate(INSTITUTIONEN, 1))
    body = page_head([("informationen/", "Staatsaufbau")], "Staatsaufbau", "Die Verfassung und Institutionen",
                     "Das Imperium Germanicum verfügt über eine eigene Verfassung, die sogenannte „Imperiale Charta“, über einen Etiketten-Guide und viele staatliche Institutionen.") + f"""
<section class="section">
  <div class="wrap">
    <div class="section-head">
      <p class="lead">Hier erhältst du einen Überblick und Informationen über alle staatlichen Institutionen die im Auftrag seiner Majestät tätig sind.</p>
    </div>
    <div class="card-grid cols-4">{cards}</div>
  </div>
</section>"""
    render("informationen/", "Staatsaufbau",
           "Überblick über die Verfassung und alle staatlichen Institutionen des Imperium Germanicum: Charta, Etikette, Senat, Reichstag, Reichsgerichtshof, Stabschefs und KRS.",
           body)


def institution_page(path, short, title, eyebrow, description, article):
    Ctx.prefix = "../../"
    body = page_head([("informationen/", "Staatsaufbau"), (path, short)], title, eyebrow) + f"""
<div class="section">
  <div class="wrap with-aside">
    <article class="article">{article()}</article>
    {aside_staatsaufbau(path)}
  </div>
</div>"""
    render(path, title, description, body)


def seat(eyebrow_txt, text, figs):
    return f"""
<section class="seat">
  <span class="eyebrow">{eyebrow_txt}</span>
  <div class="prose">{text}</div>
  <div class="figure-row" style="margin-top:28px">{figs}</div>
</section>"""


def page_reichsgerichtshof():
    def article():
        return f"""
<div class="intro-grid">
  {emblem("id9019adce22b0976", "Siegel des Reichsgerichtshofs", sizes="260px")}
  <div class="prose">
    {paras(
      "Der Reichsgerichtshof ist das oberste Organ der Justiz des Imperium Germanicum und entscheidet über Fragen der Auslegung der imperialen Charta und über Angelegenheiten der ordentlichen Gerichtsbarkeit.",
      "Der Reichsgerichtshof besteht aus insgesamt 5 Reichsrichtern von denen einer als Oberster Reichsrichter den Vorsitz über die Institution hat.",
      "Die Entscheidungen des Gerichtshofs können die aller anderen Gerichte innerhalb des Imperium Germanicum aufheben und sind generell von keiner anderen Institution anfechtbar, lediglich das Gericht selbst kann seine Entscheidungen rückgängig machen.",
    )}
  </div>
</div>
<section class="seat">
  <span class="eyebrow">Sitz der Institution</span>
  <div class="split wide-right">
    {figure("i6f65a8b46410acd8", "Kammergerichtsgebäude")}
    <div class="prose"><p>Der Reichsgerichtshof hat seinen Sitz im Kammergerichtsgebäude in der Reichshauptstadt Groß-Berlin.</p></div>
  </div>
</section>"""
    institution_page("informationen/der-reichsgerichtshof/", "Der Reichsgerichtshof", "Der Reichsgerichtshof",
                     "Judikative des Reiches",
                     "Der Reichsgerichtshof ist das oberste Organ der Justiz des Imperium Germanicum mit Sitz im Kammergerichtsgebäude in Groß-Berlin.",
                     article)


def page_reichstag():
    def article():
        return f"""
<div class="intro-grid">
  {emblem("i9aaec4e5a4cd55cd", "", "Emblem des Reichstags", sizes="260px")}
  <div class="prose">
    {paras(
      "Der Reichstag des Imperium Germanicum ist die legislative Versammlung aller Oberhäupter der Teilstaaten oder ihrer Abgesandten.",
      "Der Reichstag stimmt über potenzielle Gesetze und Regelungen ab und sendet seine Beschlüsse weiter an den Senat, der dann ebenfalls erneut über den Antrag abstimmt.",
      "Den Vorsitz im Reichstag führt der Sprecher, welcher die Sitzungen einberuft, leitet und beendet, außerdem bestimmt er den Termin der nächsten Sitzung.",
      "Das Amt des Sprechers rotiert unter den Abgeordneten alle 3 Monate.",
    )}
  </div>
</div>
<h2>Der Vorsitzende des Reichstags</h2>
<div class="people lead-person">
  {person("i9d0229d8e970308f", "Der Vorsitzende des Reichstags", "Seine (königliche) Majestät Ernst August VI.",
          "König und Kurfürst von Hannover und Braunschweig-Lüneburg", horizontal=True)}
</div>
<section class="seat">
  <span class="eyebrow">Sitz der Institution</span>
  <div class="split wide-right">
    {figure("i1230b12d712ff174", "Reichstagsgebäude")}
    <div class="prose"><p>Das Reichstagsgebäude in der Reichshauptstadt Groß-Berlin ist Sitz der Institution und beherbergt unter anderem auch die Büros des Vorsitzenden und seines Stabes.</p></div>
  </div>
</section>"""
    institution_page("informationen/der-reichstag/", "Der Reichstag", "Der Reichstag", "Legislative des Reiches",
                     "Der Reichstag ist die legislative Versammlung aller Oberhäupter der Teilstaaten des Imperium Germanicum.",
                     article)


def page_senat():
    def article():
        return f"""
<div class="intro-grid">
  {emblem("i0ed2170b7ed819f2", "", "Emblem des kaiserlichen Senats", sizes="260px")}
  <div class="prose">
    {paras(
      "Der kaiserliche Senat ist der exekutive Arm des Imperium Germanicum, er setzt sich zusammen aus den 9 Kurfürsten des Reiches welche zusammen mit seiner Majestät dem Kaiser das Reich führen.",
      "Der Senat berät ähnlich wie eine legislative Kammer über Gesetze ist aber auch für deren Ausführung verantwortlich, zusätzlich stimmt er nochmals über die im Reichstag entschiedenen Gesetze ab.",
      "Alle vom Senat bewilligten Gesetze benötigen zu ihrer Gültigkeit die Unterschrift von seiner Majestät dem Kaiser.",
    )}
  </div>
</div>
<h2>Der gegenwärtige Senat</h2>
<div class="people">
  {person("i58014e5ae3821616", "Westerwälder Union", "Alexander IX. König der Westerwälder Union",
          "Amtierender Kaiser des Imperium Germanicum",
          ("https://www.instagram.com/westwood.union?igsh=MTd2MHZ2YW8ybXh3cQ==", "Westerwälder Union"))}
  {person("i84112a7b91aca791", "Erzherzogtum Kurpfalz", "Karl V. Erzherzog von der Pfalz",
          "Amtierende Hand des Kaisers",
          ("https://www.instagram.com/kurfurstvonderpfalz?igsh=MWljYWx3eHd3amdhMA==", "Erzherzogtum Kurpfalz"))}
  {person("if31e3be67eeb014f", "Königreich Hannover", "Ernst August VI. König von Hannover und Braunschweig-Lüneburg",
          "Amtierender Vorsitzender des Reichstags",
          ("https://www.instagram.com/zelastprussian?igsh=MWE5M3VwdXFvN3hxOA==", "Königreich Hannover"))}
</div>
<section class="seat">
  <span class="eyebrow">Sitz der Institution</span>
  <div class="split wide-right">
    {figure("ifaa30c71d018e2fa", "Herrenhausgebäude")}
    <div class="prose">{paras("Der Senat versammelt sich für seine Sitzungen im Herrenhausgebäude in der Reichshauptstadt Groß-Berlin.", "Hier unterhalten auch alle Kurfürsten ein kleines Arbeitsbüro.")}</div>
  </div>
</section>"""
    institution_page("informationen/der-senat/", "Der Senat", "Der kaiserliche Senat", "Exekutive des Reiches",
                     "Der kaiserliche Senat ist der exekutive Arm des Imperium Germanicum und besteht aus den 9 Kurfürsten des Reiches.",
                     article)


def page_stabschefs():
    def article():
        return f"""
<div class="intro-grid">
  {emblem("iac7a254e9f22265b", "", "Emblem der gemeinsamen Stabschefs", sizes="260px")}
  <div class="prose">
    {paras(
      "Die gemeinsamen Stabschefs sind ein administratives Führungsgremium welches direkt von seiner Majestät mit der gesamten Führung und Organisation aller militärischen Kräfte innerhalb des Reiches betraut ist.",
      "Seine Majestät erwählt zusammen mit dem Senat die fähigsten Stabsoffiziere im Generalsrang unabhängig aus welchem Gliederstaat des Reiches sie kommen.",
      "So wird gewährleistet, dass jeder Staat die Möglichkeit hat an der gesamten militärischen Führung des Reiches mitzuwirken.",
    )}
  </div>
</div>
<div class="figure-row" style="margin-top:48px">
  {figure("i2b32d4cb098dab2c", "Flagge der Streitkräfte seiner Majestät", group="stab")}
  {figure("i11aaca30dcc486be", "Siegel der Streitkräfte seiner Majestät", group="stab")}
</div>
<h2>Das gegenwärtige Oberkommando</h2>
<div class="people">
  {person("i8245accc77cfed2f", "Oberbefehlshaber der kaiserlichen Streitkräfte", "Seine Majestät Kaiser Alexander IX.")}
  {person("i4579c94137db377a", "Stabschef der kaiserlichen Armee", "Generalfeldmarschall Graf von Dalberg")}
  {person("i9fc0edcf27633997", "Stabschef der kaiserlichen Marine", "Großadmiral Stahmer")}
  {person("i5fe69306faeb9ee2", "Stabschef der kaiserlichen Luftwaffe", "Generalfeldmarschall Graf von Baden")}
  {person("ic006686fc0a537eb", "Stabschef der kaiserlichen Nachrichtendienste", "Generalfeldmarschall Ritter von Bielicki")}
</div>
<section class="seat">
  <span class="eyebrow">Sitz des Oberkommandos</span>
  <div class="split wide-right">
    {figure("i1761387adfe28b04", "Bendlerblock")}
    <div class="prose"><p>Der Bendlerblock in der Reichshauptstadt Groß-Berlin ist Sitz des kaiserlichen Oberkommandos und operatives Verwaltungszentrum für alle militärischen Angelegenheiten des Imperium Germanicum.</p></div>
  </div>
</section>"""
    institution_page("informationen/die-stabschefs/", "Die Stabschefs", "Die gemeinsamen Stabschefs",
                     "Gremium der führenden Generale und Admirale aus allen Gliederstaaten",
                     "Die gemeinsamen Stabschefs führen und organisieren alle militärischen Kräfte des Imperium Germanicum – Sitz im Bendlerblock, Groß-Berlin.",
                     article)


def page_hand():
    def article():
        return f"""
<div class="intro-grid">
  {emblem("ib7c33ba7d6bef700", "", "Emblem der Hand des Kaisers", sizes="260px")}
  <div>
    <span class="eyebrow">Reichsombudsmann</span>
    <h2 style="margin-top:0">Karl V.</h2>
    <p class="titleblock">Seine kaiserliche und königliche Hoheit Kurfürst Karl V. von Gottes Gnaden Hand des Kaisers, Reichsombudsmann des Imperium Germanicum, Pfalzgraf bei Rhein, Herzog in Ober- und Niederbaiern, Erzschatzmeister des Senats, Fürst zu Mörs, Marquis zu Bergen und Zoom, Graf zu Veldenz, Sponheim, der Mark und Ravensberg, Herr zu Ravenstein.</p>
    <div class="prose">
    {paras(
      "Karl V. ist seit dem 13.10.2018 der Kurfürst von der Pfalz und wurde am 22.05.2026 von seiner Majestät dem Kaiser zu dessen Hand ernannt und ist somit der zweithöchste Amtsträger des Reiches, zuvor war er als Reichsombudsmann temporäres Staatsoberhaupt des Imperium Germanicum.",
      "Er ist einer der 9 Kurfürsten und gehört der Fraktion Kurpfalz an.",
      "Seine kaiserliche und königliche Hoheit ist eine wahre Frohnatur und stets auf der Suche nach dem Kontakt zum Volk, er beherrscht ausschließlich die deutsche Sprache und übt sich derweil in Englisch und Französisch.",
    )}
    </div>
  </div>
</div>
<div class="figure-row" style="margin-top:48px">
  {figure("ie52e566a1afc77a5", "Standarte seiner kaiserlichen und königlichen Hoheit der Hand des Kaisers", group="hand")}
  {figure("if8e3805d30e84d07", "Seine kaiserliche und königliche Hoheit Karl V.", group="hand")}
</div>
<section class="seat">
  <span class="eyebrow">Arbeitssitz &amp; Residenz</span>
  <div class="prose">{paras(
    "Der Arbeitssitz der Senatsverwaltung der Regierung seiner Majestät, welcher die Hand des Kaisers vorsteht befindet sich im Berliner Schloss in der Reichshauptstadt.",
    "Die private Residenz seiner kaiserlichen und königlichen Hoheit befindet sich jedoch in seiner Funktion als Kurfürst von der Pfalz im Schloss Mannheim.")}</div>
  <div class="figure-row" style="margin-top:28px">
    {figure("ie5894868af0372d8", "Schloss Mannheim", group="hand-sitz")}
    {figure("i020a6de4455d21a6", "Berliner Schloss", group="hand-sitz")}
  </div>
</section>"""
    institution_page("informationen/hand-des-kaisers/", "Hand des Kaisers", "Die Hand des Kaisers", "Reichsombudsmann",
                     "Karl V., Kurfürst von der Pfalz, ist als Hand des Kaisers und Reichsombudsmann der zweithöchste Amtsträger des Imperium Germanicum.",
                     article)


def page_krs():
    def article():
        return f"""
<div class="intro-grid">
  {emblem("i4dd5fb31eadc1d24", "Logo des KRS", sizes="260px")}
  <div class="prose">
    {paras(
      "Das kaiserliche Reichssicherheitsamt kurz KRS ist der reichsweite und übergeordnete Nachrichtendienst des Imperium Germanicum.",
      "Das KRS ist für den Erhalt der inneren und äußeren Sicherheit verantwortlich und sorgt dafür, dass Probleme direkt an der Wurzel angepackt werden oder erst gar nicht entstehen.",
      "Um seine Fähigkeiten ordentlich auszuführen sind dem KRS durch den Senat weitreichende Kompetenzen zugesprochen worden, welche in erster Linie der Informationsbeschaffung und Auswertung dienen.",
    )}
  </div>
</div>
<h2>Leiter der Reichsbehörde ist:</h2>
<div class="people lead-person">
  {person("iabde83341bd4fd94", "Generaldirektor", "Generalfeldmarschall Ritter von Bielicki",
          "Generaldirektor des kaiserlichen Reichssicherheitsamts und Vorsitzender des Rates der Geheimdienst-Chefs", horizontal=True)}
</div>
<section class="seat">
  <span class="eyebrow">Sitz der Institution</span>
  <div class="split wide-right">
    {figure("id95204a0ee5b49e1", "Hauptquartier des KRS")}
    <div class="prose"><p>Das Kaiserliche Reichssicherheitsamt hat seinen Sitz in der Reichshauptstadt Groß-Berlin im Gebäude des Hauptquartiers des KRS, von dort aus werden die Missionen und Operationen des KRS koordiniert.</p></div>
  </div>
</section>"""
    institution_page("informationen/reichssicherheitsamt/", "Reichssicherheitsamt", "Kaiserliches Reichssicherheitsamt",
                     "Nachrichtendienst des Imperium Germanicum",
                     "Das Kaiserliche Reichssicherheitsamt (KRS) ist der reichsweite und übergeordnete Nachrichtendienst des Imperium Germanicum.",
                     article)


ROMAN = re.compile(r"^(?:B )?([IVX]+)\.\s+(.+)$")
PAR = re.compile(r"^(\d+)§\.$")


def strip_b(t):
    return t[2:] if t.startswith("B ") else t


def charta_parts():
    with open(os.path.join(HERE, "charta.json"), encoding="utf-8") as fh:
        rows = [r[1] for r in json.load(fh) if r[0] == "p"]
    parts = [{"num": "", "title": "Präambel", "id": "praeambel", "intro": [], "articles": []}]
    cur_art = None
    for row in rows[1:]:  # erste Zeile = "Präambel"
        m = ROMAN.match(row)
        if m:
            parts.append({"num": m.group(1), "title": m.group(2).strip(), "id": "abschnitt-" + m.group(1).lower(),
                          "intro": [], "articles": []})
            cur_art = None
            continue
        m = PAR.match(row)
        if m:
            cur_art = {"n": m.group(1), "lines": []}
            parts[-1]["articles"].append(cur_art)
            continue
        if cur_art is None:
            parts[-1]["intro"].append(strip_b(row))
        else:
            cur_art["lines"].append(row)
    return parts


def render_article_body(part_num, art):
    lines = art["lines"]
    out = []
    i = 0
    # Kriegsrecht § 4: Aufzählung der Befugnisse
    if part_num == "VII" and art["n"] == "4":
        intro, items, tail = lines[0], lines[1:-1], lines[-1]
        lis = "".join(f"<li>{esc(strip_b(x))}</li>" for x in items)
        return f"<p>{esc(intro)}</p><ol class=\"alpha\">{lis}</ol><p>{esc(tail)}</p>"
    while i < len(lines):
        line = lines[i]
        if line.endswith(":") and i + 1 < len(lines) and lines[i + 1].startswith("B ") and line in ("Souverän:", "Gemahlin:"):
            groups = []
            while i < len(lines) and lines[i] in ("Souverän:", "Gemahlin:"):
                label = lines[i][:-1]
                i += 1
                vals = []
                while i < len(lines) and lines[i].startswith("B "):
                    vals.append(lines[i][2:].strip())
                    i += 1
                groups.append((label, vals))
            if all(len(v) == 3 for _, v in groups):
                rows = "".join(f"<tr><th scope=\"row\">{l}</th>{''.join(f'<td>{esc(x)}</td>' for x in v)}</tr>" for l, v in groups)
                out.append('<div class="table-scroll"><table class="styles-table"><thead><tr><th></th><th>Langform</th>'
                           f'<th>Kurzform</th><th>Briefkürzel</th></tr></thead><tbody>{rows}</tbody></table></div>')
            else:
                dl = "".join(f"<dt>{l}</dt><dd>{esc(' '.join(v))}</dd>" for l, v in groups)
                out.append(f'<dl class="titles">{dl}</dl>')
            continue
        if line.startswith("B „"):
            out.append(f'<blockquote class="oath">{esc(line[2:])}</blockquote>')
        else:
            out.append(f"<p>{esc(strip_b(line))}</p>")
        i += 1
    return "".join(out)


def page_charta():
    Ctx.prefix = "../../"
    parts = charta_parts()
    toc, sections = [], []
    for p in parts:
        label = p["num"] or "–"
        toc.append(f'<li><a href="#{p["id"]}"><span>{label}</span>{esc(p["title"])}</a></li>')
        if not p["num"]:
            sections.append(f"""
<section class="doc-part preamble" id="{p["id"]}">
  <header><span class="num">Präambel</span><h2>Präambel</h2></header>
  {"".join(f"<p>{esc(x)}</p>" for x in p["intro"])}
</section>""")
            continue
        arts = []
        for a in p["articles"]:
            aid = f'{p["id"]}-par-{a["n"]}'
            arts.append(f'<div class="article-par" id="{aid}"><div class="par"><a href="#{aid}" title="Link zu diesem Paragraphen">§ {a["n"]}</a></div>'
                        f'<div class="body">{render_article_body(p["num"], a)}</div></div>')
        sections.append(f"""
<section class="doc-part" id="{p["id"]}">
  <header><span class="num">Abschnitt {p["num"]}</span><h2>{esc(p["title"])}</h2></header>
  {"".join(arts)}
</section>""")
    body = page_head([("informationen/", "Staatsaufbau"), ("informationen/imperiale-charta/", "Imperiale Charta")],
                     "Die Imperiale Charta", "Die Verfassung und Satzung des Imperium Germanicum") + f"""
<div class="section">
  <div class="wrap with-aside left">
    <aside class="aside-nav toc" aria-label="Inhaltsverzeichnis der Charta">
      <h2>Inhalt</h2>
      <ol>{"".join(toc)}</ol>
      <div class="doc-tools">
        <button class="btn btn-line" type="button" data-print>{icon("print")}Drucken</button>
      </div>
    </aside>
    <article class="doc" data-progress>{"".join(sections)}</article>
  </div>
</div>"""
    render("informationen/imperiale-charta/", "Die Imperiale Charta",
           "Die Imperiale Charta – Verfassung und Satzung des Imperium Germanicum: Grundrechte, Reich und Gliederstaaten, Reichstag, Senat, Souverän, Rechtsprechung und Kriegsrecht.",
           body)


def title_card(t, idx):
    has_w = any(r[2] for r in t["anrede"])
    head = "<tr><th>Anrede</th><th>Männlich (M)</th>" + ("<th>Weiblich (W)</th>" if has_w else "") + "</tr>"
    rows = []
    for label, m, w in t["anrede"]:
        cells = f"<td>{esc(m or '–')}</td>" + (f"<td>{esc(w or '–')}</td>" if has_w else "")
        rows.append(f'<tr><th scope="row">{label}</th>{cells}</tr>')
    zus = f' <span style="font-style:italic;font-weight:400">{esc(t["zusatz"])}</span>' if t.get("zusatz") else ""
    search = " ".join([t["name"], t.get("zusatz", "")] + [x or "" for r in t["anrede"] for x in r]).lower()
    remarks = "".join(f"<p>{esc(p)}</p>" for p in t["bemerkung"])
    return f"""
<article class="title-card" data-search="{esc(search)}">
  <header><h3>{esc(t["name"]).replace("/", "/<wbr>")}{zus}</h3><span class="rank">Nr. {idx:02d}</span></header>
  <div class="table-scroll"><table class="styles-table"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>
  <div class="remark"><h4>Bemerkung</h4>{remarks}</div>
</article>"""


def page_etikette():
    Ctx.prefix = "../../"
    groups = []
    for g in etikette.GRUPPEN:
        cards = "".join(title_card(t, i) for i, t in enumerate(g["titel"], 1))
        groups.append(f"""
<section class="guide-group" id="{g["id"]}" data-group="{g["id"]}">
  <h2>{g["name"]} <small>{len(g["titel"])} Titel</small></h2>
  {cards}
</section>""")
    rang = "".join(f"<li>{esc(x)}</li>" for x in etikette.RANGLISTE)
    regeln = "".join(f"<li><span>{esc(x)}</span></li>" for x in etikette.VERHALTENSREGELN)
    body = page_head([("informationen/", "Staatsaufbau"), ("informationen/etiketten-guide/", "Etiketten-Guide")],
                     "Etiketten-Guide", "Benimmregeln und Höflichkeitsetikette") + f"""
<div class="section" style="padding-top:clamp(36px,5vw,64px)">
  <div class="wrap">
    <section class="split top" aria-labelledby="praeambel">
      <div>
        <span class="eyebrow">Präambel</span>
        <h2 id="praeambel">Allgemein gültig im gesamten Reichsgebiet</h2>
      </div>
      <div class="prose">{"".join(f"<p>{esc(p)}</p>" for p in etikette.PRAEAMBEL)}</div>
    </section>

    <div class="guide-controls" role="region" aria-label="Titel filtern">
      <div class="tabs" role="group" aria-label="Kategorie">
        <button type="button" data-filter="alle" aria-pressed="true">Alle</button>
        <button type="button" data-filter="amtstitel" aria-pressed="false">Amtstitel</button>
        <button type="button" data-filter="adelstitel" aria-pressed="false">Adelstitel</button>
        <button type="button" data-filter="kirchentitel" aria-pressed="false">Kirchentitel</button>
        <button type="button" data-filter="regeln" aria-pressed="false">Verhaltensregeln &amp; Rangliste</button>
      </div>
      <label class="search"><span class="sr-only">Titel oder Anrede suchen</span>{icon("search")}<input type="search" placeholder="Titel oder Anrede suchen …" data-guide-search></label>
    </div>

    {"".join(groups)}
    <p class="no-results" hidden data-no-results>Kein Titel entspricht deiner Suche.</p>

    <section class="guide-group" id="verhaltensregeln" data-group="regeln">
      <h2>Allgemeine Verhaltensregeln</h2>
      <ol class="rules-list">{regeln}</ol>
    </section>

    <section class="guide-group" id="rangliste" data-group="regeln">
      <h2>Rangliste der Titel</h2>
      <p class="prose" style="color:var(--muted)">{esc(etikette.RANGLISTE_HINWEIS)}</p>
      <ol class="ranklist">{rang}<li class="final">{esc(etikette.RANGLISTE_SCHLUSS)}</li></ol>
    </section>
  </div>
</div>"""
    render("informationen/etiketten-guide/", "Etiketten-Guide",
           "Der Etiketten-Guide des Imperium Germanicum: korrekte Anrede aller Amts-, Adels- und Kirchentitel, Verhaltensregeln und die Rangliste der Titel.",
           body)


def page_souveraen():
    Ctx.prefix = "../"
    body = page_head([("der-souveraen/", "Der Souverän")], "Der Souverän", "Staatsoberhaupt des Imperium Germanicum") + f"""
<section class="section">
  <div class="wrap">
    <div class="split wide-right top">
      <div>{emblem("i15c0c0ea6780ad72", "", "Emblem des Kaisers: Schloss Charlottenburg mit dem Schriftzug Der Kaiser", "(min-width: 900px) 420px, 70vw")}</div>
      <div>
        <span class="eyebrow">Seine kaiserliche und königliche Majestät</span>
        <h2>Alexander IX.</h2>
        <p class="titleblock">Seine kaiserliche und königliche Majestät Alexander IX. von Gottes Gnaden, Kaiser des Imperium Germanicum, König der Westerwälder Union, König von Apulien, Erzherzog von Österreich und Fürst von Sayen-Wittgenstein-Sayen ist der Souverän und somit Staatsoberhaupt des Imperium Germanicum.</p>
        <div class="prose">
        {paras(
          "Alexander IX. wurde am 10.05.2004 in Hachenburg der Hauptstadt der Westerwälder Union geboren, seit dem 16.01.2024 ist er König der Westerwälder Union und wurde am 14.05.2026 vom Senat für 1 Jahr zum Kaiser und Oberbefehlshaber der Streitkräfte gewählt.",
          "Er ist selbst einer der 9 Kurfürsten des Reiches und gehört der Fraktion der Westerwälder Union an.",
          "Seine Majestät zeichnet sich vor allem durch ein ruhiges und besonnenes Charakterbild aus, er besitzt aber auch exzentrische Marotten zum Beispiel müssen Kaltgetränke stets mit Eis serviert werden, vorzugsweise Eiskugeln.",
          "Außerdem legt seine Majestät viel Wert auf eine strikte Einhaltung der protokollarischen Etikette.",
          "Seine Majestät beherrschen die deutsche Sprache und etwas gebrochen auch die englische Sprache, er übt im Augenblick die italienische Sprache.",
        )}
        </div>
      </div>
    </div>
  </div>
</section>

<section class="section paper">
  <div class="wrap split">
    <div class="prose reveal">
      <span class="eyebrow">Ex Officio</span>
      <h2>Kaiser, König und Erzherzog</h2>
      {paras(
        "Ex Officio ist der Souverän nicht nur Kaiser des Imperium Germanicum, sondern in Personalunion auch König von Apulien.",
        "Das Königreich Apulien ist de jure ein selbständiger Staat de facto aber durch Verwaltung und Militär an das Reich gebunden.",
        "Außerdem ist der Souverän zusätzlich Ex Officio der Erzherzog von Österreich wobei Österreich vom Status nicht wie das Königreich Apulien ein eigener Staat unter kaiserlicher Kontrolle ist sondern dem Reich voll angehört.",
        "Aus der Kombination aus Kaiserthron, Königsthron und der Würde des Erzherzogs ergibt sich auch der Titel (kaiserliche und königliche Majestät).",
      )}
    </div>
    <div class="reveal">{figure("if0978cec8f01efe8", "Standarte von seiner Majestät dem Kaiser", group="kaiser")}</div>
  </div>
</section>

<section class="section">
  <div class="wrap">
    <div class="figure-row">
      {figure("iceaef15058c1dbef", "Seine Majestät Alexander IX.", group="kaiser")}
      {figure("i50101bc1effeb76a", "Seine Majestät Alexander IX. in Uniform", group="kaiser")}
    </div>
    <section class="seat">
      <span class="eyebrow">Arbeitssitz &amp; Residenz</span>
      <div class="prose">{paras(
        "Der Arbeitssitz seiner Majestät befindet sich zusammen mit der Senatsverwaltung im Berliner Schloss.",
        "Die private Residenz des Souveräns befindet sich jedoch im Schloss Charlottenburg, welches sich ebenfalls in der Reichshauptstadt befindet.")}</div>
      <div class="figure-row" style="margin-top:28px">
        {figure("if3da36451cad23de", "Schloss Charlottenburg", group="kaiser-sitz")}
        {figure("icb9cbf1ec35c85a0", "Berliner Schloss", group="kaiser-sitz")}
      </div>
    </section>
  </div>
</section>"""
    render("der-souveraen/", "Der Souverän",
           "Seine kaiserliche und königliche Majestät Alexander IX. – Souverän und Staatsoberhaupt des Imperium Germanicum.",
           body)


GALERIE = [
    ("i9611b2162cb65868", "Gruppenbild der Delegation des Imperium Germanicum"),
    ("ia72bbdd30ccf609d", "Begegnung auf dem Veranstaltungsgelände"),
    ("i8f4063a0ea9a2c3e", "Delegation des Imperium Germanicum auf der Tribüne"),
    ("ifa9408b48efb5f32", "Zwei Offiziere in Paradeuniform"),
    ("i16f33c19c3f505e0", "Offizier in Marineuniform im Park"),
    ("i5562f02357154c89", "Rast der Delegation im Park"),
    ("ic4cd2cb0fe11cb4e", "Picknick unter Bäumen"),
    ("i598a1c25c91b4caf", "Prozession durch den Park"),
    ("i64375105f8c51018", "Besuch in der Jesuitenkirche"),
    ("i2033223ba41d9585", "Zwei Offiziere im Gespräch"),
    ("i303bb1dce8e4b1e0", "Vor dem Schloss Mannheim"),
    ("ice8d7f0a7d7954d1", "Am Altar der Jesuitenkirche"),
]


def page_galerie():
    Ctx.prefix = "../"
    items = "".join(
        zoom_link(iid, img(iid, alt, "(min-width: 1000px) 33vw, (min-width: 640px) 50vw, 100vw"), alt, "animagic", cls="")
        for iid, alt in GALERIE)
    body = page_head([("die-bildergalerie/", "Die Bildergalerie")],
                     "Bildergalerie von Events an denen das Imperium Germanicum teilgenommen hat", "Die Bildergalerie") + f"""
<section class="section">
  <div class="wrap">
    <header class="event-head">
      <h2>Animagic Mannheim 2026</h2>
      <p>{len(GALERIE)} Aufnahmen · Zum Vergrößern anklicken</p>
    </header>
    <div class="gallery">{items}</div>
  </div>
</section>"""
    render("die-bildergalerie/", "Die Bildergalerie",
           "Bildergalerie von Events, an denen das Imperium Germanicum teilgenommen hat – Animagic Mannheim 2026.",
           body)


ERLASSE = [
    ("id3ff45f26d0a5a7a", "Der Senat", "Gesetz zur Regelung der Vertretung des Fürstbischofs"),
    ("ic64ca73d2815ac89", "Die Hand des Kaisers", "Anerkennung der Souveränität des Sparneeber Volksbundes"),
    ("ic991fcf91eecc87e", "Der Kaiser", "Ausschluss des Fürstbischofs von Würzburg aus dem Senat"),
    ("i6ab255bcf6db1305", "Der Kaiser", "Anteilnahme an Ritter von Bielicki"),
    ("i1590e3b4d5499409", "Der Kaiser", "Einberufung einer Sondersitzung des Senats"),
    ("iacb99eb0987f14e7", "Der Reichsombudsmann", "Ablaufprotokoll 31.07. – 02.08.2026"),
    ("ifafac72683d714f3", "Der Kaiser", "Schreiben an Ludwig Maximilian II. von Schwaben-Württemberg"),
    ("i0a8ea9e5702e3bc7", "Die Hand des Kaisers", "Ernennung einer neuen Hand des Kurfürsten"),
    ("i953888c53fa0e8c1", "Der Kaiser", "Kaiserliche Ermittlungsvollmacht"),
    ("id3756a9395326e35", "Der Kaiser", "Trauerbekundung zum Tod seiner königlichen Hoheit Ludwig Maximilian II."),
    ("i8be3a14e6b0afe0b", "Der Kaiser", "Entbindung des Stabschefs der kaiserlichen Luftwaffe"),
    ("i2c7db5c81c53148c", "Der Kaiser", "Erklärung an die Untertanen und Mandatsträger des Imperiums"),
    ("id735ce1001148587", "Der Kaiser", "Aberkennung der Kurwürde des Herzogtums Tirol und Salzburg"),
]


def page_erlasse():
    Ctx.prefix = "../"
    issuers = []
    for _, iss, _ in ERLASSE:
        if iss not in issuers:
            issuers.append(iss)
    btns = '<button type="button" data-doc-filter="alle" aria-pressed="true">Alle</button>' + "".join(
        f'<button type="button" data-doc-filter="{esc(i)}" aria-pressed="false">{esc(i)}</button>' for i in issuers)
    cards = []
    for n, (iid, iss, title) in enumerate(ERLASSE, 1):
        cap = f"{iss} – {title}"
        inner = (f'<span class="sheet">{img(iid, cap, "(min-width: 1000px) 25vw, (min-width: 520px) 50vw, 100vw")}</span>'
                 f'<span class="meta"><strong>{esc(iss)}</strong><span>Nr. {n:02d}</span></span>'
                 f'<span style="display:block;font:500 1.125rem/1.3 var(--serif);margin-top:6px">{esc(title)}</span>')
        cards.append(f'<a class="doc-card reveal" href="{original(iid)}" data-lightbox data-full="{asset(f"img/{iid}-1280.webp")}" '
                     f'data-caption="{esc(cap)}" data-gallery="erlasse" data-issuer="{esc(iss)}">{inner}</a>')
    body = page_head([("neue-erlasse-und-gesetze/", "Neue Erlasse und Gesetze")], "Wirksame Beschlüsse",
                     "Neue Erlasse und Gesetze",
                     "Gesetze, Erlasse und Bekanntmachungen des Souveräns, des Senats und der Hand des Kaisers im Wortlaut.") + f"""
<section class="section">
  <div class="wrap">
    <header class="event-head">
      <h2>2026</h2>
      <div class="tabs" role="group" aria-label="Nach Aussteller filtern">{btns}</div>
    </header>
    <div class="docs">{"".join(cards)}</div>
  </div>
</section>"""
    render("neue-erlasse-und-gesetze/", "Neue Erlasse und Gesetze",
           "Wirksame Beschlüsse des Imperium Germanicum: Gesetze, Erlasse und Bekanntmachungen des Jahres 2026.",
           body)


def contact_card():
    return f"""
<aside class="contact-card on-dark">
  <span class="eyebrow">Anschrift</span>
  <h2>Imperium Germanicum</h2>
  <address>{address_html()}</address>
  <ul class="contact-list">
    <li><span>E-Mail</span><a href="mailto:{EMAIL}">{EMAIL}</a></li>
    <li><span>Insta</span><a href="{INSTAGRAM}" rel="noopener" target="_blank">das_imperium_germanicum</a></li>
    <li><span>YouTube</span><a href="{YOUTUBE}" rel="noopener" target="_blank">Imperium Germanicum</a></li>
  </ul>
</aside>"""


def form_common(kind):
    return (f'<input type="hidden" name="formular" value="{kind}">'
            '<input type="hidden" name="ts" value="" data-ts>'
            '<div class="hp" aria-hidden="true"><label>Website <input type="text" name="website" tabindex="-1" autocomplete="off"></label></div>')


def page_kontakt():
    Ctx.prefix = "../"
    body = page_head([("kontakt/", "Kontakt")], "Melde dich zum Dienst!", "Kontakt",
                     f'Klicke <a href="{INSTAGRAM}" rel="noopener" target="_blank"><strong>HIER</strong></a> um auf den offiziellen Instagram-Account des Imperium Germanicum zu gelangen.') + f"""
<section class="section">
  <div class="wrap split wide-left top">
    <div>
      <form class="form" action="{u("api/formular.php")}" method="post" novalidate data-ajax-form>
        {form_common("kontakt")}
        <div class="row-2">
          <div class="field"><label for="f-name">Name <span class="req">*</span></label><input id="f-name" name="name" type="text" autocomplete="name" required maxlength="120"></div>
          <div class="field"><label for="f-email">E-Mail <span class="req">*</span></label><input id="f-email" name="email" type="email" autocomplete="email" required maxlength="200"></div>
        </div>
        <div class="field"><label for="f-msg">Deine Nachricht für mich <span class="req">*</span></label><textarea id="f-msg" name="nachricht" required maxlength="5000"></textarea></div>
        <p class="form-note">Es gilt unsere <a href="{u("datenschutz/")}">Datenschutzerklärung</a>.</p>
        <p class="form-note"><strong>Hinweis:</strong> Bitte die mit * gekennzeichneten Felder ausfüllen.</p>
        <div class="form-status" role="status" aria-live="polite" hidden></div>
        <div><button class="btn btn-navy" type="submit">Nachricht senden {icon("arrow")}</button></div>
      </form>
    </div>
    {contact_card()}
  </div>
</section>"""
    render("kontakt/", "Melde dich zum Dienst!",
           "Kontakt zum Imperium Germanicum – melde dich zum Dienst per Formular, E-Mail, Instagram oder YouTube.",
           body)


def thanks_page(path, crumbs, title, text, back):
    Ctx.prefix = "../" * path.count("/")
    body = page_head(crumbs, title) + f"""
<section class="section"><div class="wrap narrow prose">
  <p class="lead">{text}</p>
  <a class="btn btn-navy" href="{u(back[0])}">{back[1]} {icon("arrow")}</a>
</div></section>"""
    render(path, title, text, body, robots="noindex,follow", in_sitemap=False)


def page_sitemap():
    Ctx.prefix = "../"
    sub = "".join(f'<li><a href="{u(p)}">{esc(s)}</a></li>' for p, s, *_ in INSTITUTIONEN)
    items = [
        ("", "Hauptseite", ""),
        ("informationen/", "Informationen", f"<ul>{sub}</ul>"),
        ("der-souveraen/", "Der Souverän", ""),
        ("die-bildergalerie/", "Die Bildergalerie", ""),
        ("neue-erlasse-und-gesetze/", "Neue Erlasse und Gesetze", ""),
        ("kontakt/", "Kontakt", ""),
        ("impressum/", "Impressum", ""),
        ("datenschutz/", "Datenschutz", ""),
        ("gewaehrleistung/", "Gesetzliche Gewährleistung", ""),
        ("widerruf/", "Vertrag widerrufen", ""),
    ]
    lis = "".join(f'<li><a href="{u(p)}">{l}</a>{s}</li>' for p, l, s in items)
    body = page_head([("sitemap/", "Sitemap")], "Sitemap") + f"""
<section class="section"><div class="wrap narrow"><ul class="sitemap-list">{lis}</ul></div></section>"""
    render("sitemap/", "Sitemap", "Übersicht aller Seiten der Website des Imperium Germanicum.", body)


def page_impressum():
    Ctx.prefix = "../"
    body = page_head([("impressum/", "Impressum")], "Impressum") + f"""
<section class="section"><div class="wrap narrow legal">
  <h2 style="margin-top:0">Angaben gemäß § 5 DDG</h2>
  <p>{address_html()}</p>
  <h2>Kontakt</h2>
  <p>E-Mail: <a href="mailto:{EMAIL}">{EMAIL}</a><br>
  Instagram: <a href="{INSTAGRAM}" rel="noopener" target="_blank">das_imperium_germanicum</a><br>
  YouTube: <a href="{YOUTUBE}" rel="noopener" target="_blank">Imperium Germanicum</a></p>
  <h2>Hinweis zum Inhalt</h2>
  <p>Das Imperium Germanicum ist ein fiktiver Staatenbund und ein interaktives Rollenspiel. Sämtliche dargestellten Institutionen, Ämter, Titel, Erlasse und Gesetze sind Teil dieses Rollenspiels und haben keine rechtliche Wirkung außerhalb davon.</p>
  <h2>Haftung für Links</h2>
  <p>Diese Website enthält Links zu externen Websites Dritter (z.&nbsp;B. Instagram, YouTube), auf deren Inhalte wir keinen Einfluss haben. Für die Inhalte der verlinkten Seiten ist stets der jeweilige Anbieter oder Betreiber verantwortlich.</p>
</div></section>"""
    render("impressum/", "Impressum", "Impressum der Website des Imperium Germanicum – Das Rollenspiel.", body,
           robots="noindex,follow")


def page_datenschutz():
    Ctx.prefix = "../"
    body = page_head([("datenschutz/", "Datenschutz")], "Datenschutzerklärung") + f"""
<section class="section"><div class="wrap narrow legal">
  <h2 style="margin-top:0">1. Verantwortlicher</h2>
  <p>{address_html()}<br>E-Mail: <a href="mailto:{EMAIL}">{EMAIL}</a></p>

  <h2>2. Aufruf der Website (Server-Logfiles)</h2>
  <p>Beim Aufruf dieser Website verarbeitet unser Hosting-Anbieter technisch notwendige Daten (IP-Adresse, Datum und Uhrzeit, aufgerufene Seite, Browsertyp und Betriebssystem), um die Website auszuliefern und ihre Sicherheit zu gewährleisten. Rechtsgrundlage ist unser berechtigtes Interesse gemäß Art. 6 Abs. 1 S. 1 lit. f DSGVO. Die Daten werden nach kurzer Zeit gelöscht, sofern sie nicht zur Aufklärung von Missbrauch benötigt werden.</p>

  <h2>3. Kontaktformular und Widerrufsformular</h2>
  <p>Wenn du uns über ein Formular schreibst, verarbeiten wir deine Angaben (Name, E-Mail-Adresse, Nachricht bzw. Widerrufsangaben), um deine Anfrage zu bearbeiten. Rechtsgrundlage ist Art. 6 Abs. 1 S. 1 lit. b bzw. lit. f DSGVO. Die Angaben werden per E-Mail an uns übermittelt und gelöscht, sobald sie für die Bearbeitung nicht mehr erforderlich sind.</p>

  <h2>Spamschutz</h2>
  <p>Zum Schutz unserer Formulare vor automatisierten Programmen („Bots“) setzen wir ausschließlich serverseitige Prüfungen ein (ein für Menschen unsichtbares Prüffeld, eine Mindest-Ausfüllzeit und eine Begrenzung der Anfragen pro Stunde). Dafür wird die IP-Adresse kurzzeitig in anonymisierter (gehashter) Form auf unserem Server gespeichert und nach spätestens einer Stunde gelöscht. Es werden keine Daten an Dritte wie Google übermittelt. Rechtsgrundlage ist unser berechtigtes Interesse gemäß Art. 6 Abs. 1 S. 1 lit. f DSGVO.</p>

  <h2 id="cookies">4. Cookie-Richtlinie</h2>
  <p>Diese Website setzt keine Cookies und verwendet keine Analyse- oder Tracking-Dienste. Eine Einwilligung ist daher nicht erforderlich.</p>

  <h2>5. Schriftarten</h2>
  <p>Die verwendeten Schriftarten (EB Garamond, Source Sans 3) werden lokal von unserem Server geladen. Es findet keine Verbindung zu Servern Dritter statt.</p>

  <h2>6. Externe Links</h2>
  <p>Unsere Website verlinkt auf unsere Auftritte bei Instagram und YouTube. Erst wenn du einen solchen Link anklickst, werden Daten an den jeweiligen Anbieter übertragen; es gelten dann dessen Datenschutzbestimmungen.</p>

  <h2>7. Deine Rechte</h2>
  <p>Du hast das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18), Datenübertragbarkeit (Art. 20) und Widerspruch (Art. 21 DSGVO). Außerdem kannst du dich bei einer Datenschutz-Aufsichtsbehörde beschweren.</p>
  <p style="color:var(--muted)">Stand: Oktober {YEAR}</p>
</div></section>"""
    render("datenschutz/", "Datenschutz", "Datenschutzerklärung und Cookie-Richtlinie der Website des Imperium Germanicum.",
           body, robots="noindex,follow")


def page_gewaehrleistung():
    Ctx.prefix = "../"
    body = page_head([("gewaehrleistung/", "Gesetzliche Gewährleistung")], "Gesetzliche Gewährleistung") + """
<section class="section"><div class="wrap narrow legal">
  <p class="lead" style="margin-top:0">Mindestens zwei Jahre gesetzliche Gewährleistung der Vertragsmäßigkeit für Waren, die in der Europäischen Union verkauft werden.</p>
  <p>Verbraucherinnen und Verbraucher können ihre Rechte im Rahmen des gesetzlichen Gewährleistungsrechts geltend machen, z.&nbsp;B. wenn die Waren</p>
  <ul><li>nicht der Beschreibung entsprechen,</li><li>nicht bestimmungsgemäß funktionieren.</li></ul>
  <p>Verkäufer haften für jede Vertragswidrigkeit, die zum Zeitpunkt der Lieferung der Waren bestand und innerhalb des Zeitraums der gesetzlichen Gewährleistung erkennbar wird. Verkäufer müssen in solchen Fällen Folgendes anbieten:</p>
  <ul><li>kostenlose Nachbesserung oder kostenlose Ersatzlieferung,</li><li>in bestimmten Fällen eine Preisminderung oder eine vollständige Erstattung des Kaufpreises.</li></ul>
  <p>In einigen Ländern gilt ein längerer Zeitraum für die gesetzliche Gewährleistung. Für gebrauchte Waren kann ein kürzerer Zeitraum gelten, jedoch nicht weniger als ein Jahr. Für weitere Informationen zu Ihren Rechten in einem bestimmten Land besuchen Sie <a href="https://europa.eu/youreurope/garantien" rel="noopener" target="_blank">europa.eu/youreurope/garantien</a> oder fragen Sie den Verkäufer.</p>
  <h2>Was ist zu tun, wenn Sie vertragswidrige Waren erhalten?</h2>
  <ul><li>Melden Sie dem Verkäufer das Problem so bald wie möglich.</li><li>Legen Sie einen Kaufnachweis vor, z.&nbsp;B. die Quittung, Rechnung oder einen Kontoauszug.</li></ul>
  <p>Verkäufer und Hersteller können auch gewerbliche Garantien gewähren, die unabhängig von der gesetzlichen Gewährleistung gelten. Diese GARAN-Kennzeichnung zeigt beispielsweise, dass der Hersteller eine gewerbliche Haltbarkeitsgarantie ohne zusätzliche Kosten gewährt, die die gesamte Ware abdeckt.</p>
</div></section>"""
    render("gewaehrleistung/", "Gesetzliche Gewährleistung", "Informationen zur gesetzlichen Gewährleistung in der Europäischen Union.",
           body, robots="noindex,follow")


def page_widerruf():
    Ctx.prefix = "../"
    body = page_head([("widerruf/", "Vertrag widerrufen")], "Vertrag widerrufen", "",
                     "Online geschlossene Verträge können innerhalb von 14 Tagen widerrufen werden. Bitte das untenstehende Formular ausfüllen. Eine Eingangsbestätigung wird umgehend per E-Mail versendet.") + f"""
<section class="section"><div class="wrap narrow">
  <form class="form" action="{u("api/formular.php")}" method="post" novalidate data-ajax-form>
    {form_common("widerruf")}
    <div class="field"><label for="w-name">Name <span class="req">*</span></label><input id="w-name" name="name" type="text" autocomplete="name" placeholder="z. B. Maria Mustermann" required maxlength="120"></div>
    <div class="field"><label for="w-id">Bestell- oder Buchungsnummer <span class="req">*</span></label><input id="w-id" name="vertrag" type="text" placeholder="z. B. 1042" required maxlength="80"><span class="hint">Dies ist in der Bestellbestätigung zu finden.</span></div>
    <div class="field"><label for="w-email">E-Mail-Adresse <span class="req">*</span></label><input id="w-email" name="email" type="email" autocomplete="email" placeholder="z. B. maria@example.com" required maxlength="200"><span class="hint">Die Eingangsbestätigung wird an diese Adresse gesendet.</span></div>
    <div class="field"><label for="w-items">Welche Artikel sollen widerrufen werden?</label><input id="w-items" name="artikel" type="text" placeholder="z. B. Blaues T-Shirt oder Artikel #3" maxlength="500"><span class="hint">Leer lassen, um den gesamten Vertrag zu widerrufen. Um nur einen Teil der Bestellung zu widerrufen, die Artikel hier angeben.</span></div>
    <div class="field"><label for="w-reason">Grund des Widerrufs (optional)</label><textarea id="w-reason" name="grund" placeholder="z. B. Artikel kam beschädigt an, Meinung geändert …" maxlength="3000" style="min-height:120px"></textarea></div>
    <p class="callout" style="margin:0">Ein Klick auf die Schaltfläche unten erklärt verbindlich den Widerruf des oben angegebenen Vertrags. Dieser Schritt kann nicht rückgängig gemacht werden.</p>
    <p class="form-note">Alle mit * markierten Felder sind Pflichtfelder.</p>
    <div class="form-status" role="status" aria-live="polite" hidden></div>
    <div><button class="btn btn-navy" type="submit">Vertrag jetzt widerrufen</button></div>
  </form>
</div></section>"""
    render("widerruf/", "Vertrag widerrufen", "Online geschlossene Verträge innerhalb von 14 Tagen widerrufen.", body,
           robots="noindex,follow")


def page_404():
    Ctx.prefix = ""
    # 404 wird von beliebiger Tiefe aus geladen -> absolute Pfade über <base>
    body = f"""
<section class="notfound"><div class="wrap narrow">
  {img(LOGO, "", "140px")}
  <span class="eyebrow">Fehler 404</span>
  <h1>Diese Seite wurde nicht gefunden.</h1>
  <p class="lead">Die angeforderte Seite existiert nicht oder wurde verschoben.</p>
  <div class="hero-actions" style="justify-content:center">
    <a class="btn btn-navy" href="{u("")}">Zur Hauptseite</a>
    <a class="btn btn-line" href="{u("sitemap/")}">Sitemap</a>
  </div>
</div></section>"""
    render("", "Seite nicht gefunden", "Diese Seite wurde nicht gefunden.", body, current="404", robots="noindex",
           in_sitemap=False, show_crowns=False)
    src = os.path.join(ROOT, "index.html")
    with open(src, encoding="utf-8") as fh:
        doc = fh.read()
    doc = doc.replace("<head>", '<head>\n<base href="/">', 1)
    with open(os.path.join(ROOT, "404.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)


def write_meta_files():
    urls = "".join(f"<url><loc>{SITE_URL}/{p}</loc></url>\n" for p in PAGES)
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    with open(os.path.join(ROOT, "robots.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"User-agent: *\nDisallow: /api/\nDisallow: /_build/\n\nSitemap: {SITE_URL}/sitemap.xml\n")


def main():
    page_404()          # zuerst, da es index.html kurzzeitig belegt
    page_home()
    page_informationen()
    page_charta()
    page_etikette()
    page_hand()
    page_senat()
    page_reichstag()
    page_reichsgerichtshof()
    page_stabschefs()
    page_krs()
    page_souveraen()
    page_galerie()
    page_erlasse()
    page_kontakt()
    thanks_page("kontakt/danke/", [("kontakt/", "Kontakt"), ("kontakt/danke/", "Nachricht gesendet")],
                "Vielen Dank für deine Nachricht!",
                "Deine Nachricht ist bei uns eingegangen. Wir melden uns so bald wie möglich bei dir.",
                ("", "Zur Hauptseite"))
    page_sitemap()
    page_impressum()
    page_datenschutz()
    page_gewaehrleistung()
    page_widerruf()
    thanks_page("widerruf/danke/", [("widerruf/", "Vertrag widerrufen"), ("widerruf/danke/", "Widerruf eingegangen")],
                "Widerruf eingegangen",
                "Dein Widerruf ist bei uns eingegangen. Eine Eingangsbestätigung wurde an deine E-Mail-Adresse gesendet.",
                ("", "Zur Hauptseite"))
    write_meta_files()
    print(f"{len(PAGES)} Seiten erzeugt.")


if __name__ == "__main__":
    main()
