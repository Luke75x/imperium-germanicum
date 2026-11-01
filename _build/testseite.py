"""Neugestaltung der Website als Testfassung unter /testseite1/ (Auftrag Luke 2026-11-01).

Aufruf (im Projektordner):
    python3 _build/testseite.py

Die Inhalte kommen aus dem bestehenden Generator (site.py): dessen Seitenfunktionen werden mit eigenem
Seitenrahmen (Kopf, Fuß, Seitenkopf) neu gerendert; Startseite und die wichtigsten Unterseiten sind hier neu
aufgebaut. Ausgabe nach testseite1/ (DE) und testseite1/en/ (EN). Bilder, Schriften der alten Seite, site.js
und der Webdienst (Reichskarte, Organigramm, Formular-API) werden von der Hauptseite mitbenutzt (absolute
Pfade), eigenes Design in testseite1/assets/ (ts.css, ts.js, Schriften Cormorant Garamond + Inter).
Die Hauptseite bleibt unberührt; deploy.sh kopiert testseite1/ mit.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_spec = importlib.util.spec_from_file_location("igsite", os.path.join(HERE, "site.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)
import i18n  # noqa: E402

ROOT = os.path.dirname(HERE)
BASE = "testseite1"
OUT = os.path.join(ROOT, BASE)
Ctx, esc, icon, img, paras = S.Ctx, S.esc, S.icon, S.img, S.paras
SITE_URL = S.SITE_URL

# Englische Texte der Neugestaltung (zusätzlich zu en.json der Hauptseite)
TS_EN_FILE = os.path.join(HERE, "testseite_en.json")
if os.path.exists(TS_EN_FILE):
    with open(TS_EN_FILE, encoding="utf-8") as fh:
        i18n.DICT.update({k: v for k, v in json.load(fh).items() if v})


def _hash(rel):
    with open(os.path.join(OUT, "assets", rel), "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Pfade: Seiten der Testfassung relativ, alles Übrige von der Hauptseite (absolut)
# ---------------------------------------------------------------------------

# Bereiche des Webdienstes und der Hauptseite, die es in der Testfassung nicht gibt
EXTERN = ("karte/", "vorschlaege/", "api/", "anmelden", "informationen/organigramm/",
          "informationen/der-reichstag/intern/", "informationen/die-reichsbehoerden/organigramm/",
          "informationen/die-reichsbehoerden/intern/")


def u(path):
    if path.startswith(EXTERN):
        return "/" + path
    return (Ctx.prefix + path) or "./"


def asset(path):
    return "/assets/" + path


def ts_asset(path):
    """Eigene Dateien der Testfassung (testseite1/assets/)."""
    return Ctx.prefix + "assets/" + path


S.u = u
S.asset = asset

# ---------------------------------------------------------------------------
# Inhalte (ausschließlich von der bestehenden Website übernommen)
# ---------------------------------------------------------------------------

EMAIL, INSTAGRAM, YOUTUBE, LOGO = S.EMAIL, S.INSTAGRAM, S.YOUTUBE, S.LOGO
INSTITUTIONEN = S.INSTITUTIONEN

NAV = [
    ("das-imperium/", "Das Imperium"),
    ("informationen/", "Staatsaufbau"),
    ("der-souveraen/", "Der Souverän"),
    ("institutionen", "Institutionen"),
    ("dokumente/", "Dokumente"),
    ("die-bildergalerie/", "Medien"),
]

FACTS = [  # Startseite der Hauptseite
    ("1205000", "1.205.000", "km²", "Hoheitsgebiet"),
    ("217000000", "217.000.000", "", "Staatsbürger"),
    ("9", "9", "", "Kurfürsten im Senat"),
    ("1", "1", "Jahr", "Amtszeit des Kaisers"),
]

REICH_TEXT = [
    "Das Imperium Germanicum besteht wie schon sein historisches Vorbild aus unzähligen kleineren Staaten, darunter verschiedene Fürstentümer, Königreiche, Herzogtümer und andere Gebietskörperschaften.",
    "Sehr weit oben in der Hierarchie befinden sich die 9 Kurfürsten welche die 9 Landesoberhäupter der wichtigsten Teilstaaten des Reiches sind, sie bilden den sogenannten kaiserlichen Senat.",
    "Eine der wichtigsten Aufgaben des Senats ist die Wahl des Souveräns und Staatsoberhaupts des Imperium Germanicum, des Kaisers.",
    "Der Kaiser wird für 1 Jahr aus einem der 9 Kurfürsten gewählt und eine Wiederwahl ist unbegrenzt möglich.",
]
GEBIET_TEXT = [
    "Das Imperium Germanicum befindet sich in Mittel- und Südeuropa und umfasst ein Hoheitsgebiet von 1.205.000 km².",
    "Das Königreich Apulien ist aufgrund der Personalunion des Kaiserthrons mit dem Königsthron de facto ein Teil des Imperiums, sowie der Heilige Stuhl in dessen Gebiet seine Heiligkeit der Papst eine besondere Stellung innehat, jedoch seine Majestät der Kaiser die militärische und zivile Verwaltung kontrolliert.",
    "Das Imperium Germanicum ist zudem als teilzentralisierter Bundesstaat organisiert.",
    "Das Imperium besteht aus vielen Teilstaaten unterschiedlicher Größe, welche ihre inneren Angelegenheiten zumeist selbst bestimmen.",
    "Hier gilt die von der Charta vorgeschriebene Regel, dass das Reichsrecht das Landesrecht bricht, wenn es Differenzen zwischen Gesetzen gibt.",
    "Das gesamte Imperium Germanicum umfasst daher 217.000.000 Staatsbürger.",
    "9 der Teilstaaten des Imperiums sind sogenannte Kurfürstentümer deren jeweiliges Landesoberhaupt als Kurfürst einen Sitz im Senat, dem exekutiven Organ des Imperiums innehat.",
    "Alle anderen Landesoberhäupter haben mit ihrer jeweiligen Delegation einen Sitz im Reichstag, dem legislativen Organ des Imperiums.",
]
INTRO_LEAD = "Das Imperium Germanicum ist ein fiktiver Staatenbund in Europa, basierend auf den Grenzen des früheren Heiligen Römischen Reiches, es stellt eine alternative Gegenwart dar, in der das Heilige Römische Reich die Jahre überdauert hat und sich bis in die heutige Zeit weiterentwickelt hat."
SOUVERAEN_TEXT = [
    "Der Souverän ist das offizielle Staatsoberhaupt des Imperium Germanicums, Amtsträger, Offiziere und Richter schwören ihm die Treue.",
    "Der Souverän ernennt und entlässt die Beamten und Richter sowie Konsule des Reiches und bestellt sie nach Belieben ein, außerdem besitzt der Souverän die Möglichkeit Verurteilte zu begnadigen und über Dekrete gewisse Entscheidungen temporär ohne den Senat zu treffen.",
    "Der Souverän ist der höchste Repräsentant des Reiches und genießt als solcher die höchste Würde, der Souverän hat immer das Recht angehört zu werden.",
]
KAISER_TITEL = "Seine kaiserliche und königliche Majestät Alexander IX. von Gottes Gnaden, Kaiser des Imperium Germanicum, König der Westerwälder Union, König von Apulien, Erzherzog von Österreich und Fürst von Sayen-Wittgenstein-Sayen ist der Souverän und somit Staatsoberhaupt des Imperium Germanicum."
KAISER_FAKTEN = [
    ("Amt", "Kaiser des Imperium Germanicum und Oberbefehlshaber der Streitkräfte"),
    ("Gewählt", "Am 14.05.2026 vom Senat für 1 Jahr"),
    ("Kurfürst", "Fraktion der Westerwälder Union"),
    ("Arbeitssitz", "Berliner Schloss"),
    ("Residenz", "Schloss Charlottenburg"),
]

# Staatsaufbau: Texte und Angaben von den jeweiligen Seiten der Hauptseite
STRUKTUR = [
    {"id": "souveraen", "ebene": "Staatsoberhaupt", "art": "Staatsoberhaupt", "name": "Der Souverän",
     "bild": "i15c0c0ea6780ad72", "link": "der-souveraen/",
     "text": "Der Souverän ist das offizielle Staatsoberhaupt des Imperium Germanicums, Amtsträger, Offiziere und Richter schwören ihm die Treue.",
     "fakten": [("Amtsinhaber", "Seine Majestät Alexander IX."), ("Wahl", "Durch den Senat aus den 9 Kurfürsten"),
                ("Amtszeit", "1 Jahr, Wiederwahl unbegrenzt möglich")],
     "gefuege": ["Ernennt und entlässt die Beamten und Richter sowie Konsule des Reiches.",
                 "Unterzeichnet die vom Senat bewilligten Gesetze."]},
    {"id": "senat", "ebene": "Gewalten", "art": "Exekutive", "name": "Der kaiserliche Senat",
     "bild": "i0ed2170b7ed819f2", "link": "informationen/der-senat/",
     "text": "Der kaiserliche Senat ist der exekutive Arm des Imperium Germanicum, er setzt sich zusammen aus den 9 Kurfürsten des Reiches welche zusammen mit seiner Majestät dem Kaiser das Reich führen.",
     "fakten": [("Mitglieder", "Die 9 Kurfürsten des Reiches"), ("Sitz", "Herrenhausgebäude, Groß-Berlin")],
     "gefuege": ["Wählt den Kaiser aus den Reihen der Kurfürsten.",
                 "Stimmt nochmals über die im Reichstag entschiedenen Gesetze ab."]},
    {"id": "reichstag", "ebene": "Gewalten", "art": "Legislative", "name": "Der Reichstag",
     "bild": "i9aaec4e5a4cd55cd", "link": "informationen/der-reichstag/",
     "text": "Der Reichstag des Imperium Germanicum ist die legislative Versammlung aller Oberhäupter der Teilstaaten oder ihrer Abgesandten.",
     "fakten": [("Vorsitz", "Der Präsident, das Amt rotiert alle 3 Monate"), ("Sitz", "Reichstagsgebäude, Groß-Berlin")],
     "gefuege": ["Stimmt über potenzielle Gesetze und Regelungen ab und sendet seine Beschlüsse weiter an den Senat."]},
    {"id": "reichsgerichtshof", "ebene": "Gewalten", "art": "Judikative", "name": "Der Reichsgerichtshof",
     "bild": "id9019adce22b0976", "link": "informationen/der-reichsgerichtshof/",
     "text": "Der Reichsgerichtshof ist das oberste Organ der Justiz des Imperium Germanicum und entscheidet über Fragen der Auslegung der imperialen Charta und über Angelegenheiten der ordentlichen Gerichtsbarkeit.",
     "fakten": [("Mitglieder", "5 Reichsrichter, Vorsitz: Oberster Reichsrichter"), ("Sitz", "Kammergerichtsgebäude, Groß-Berlin")],
     "gefuege": ["Seine Entscheidungen können die aller anderen Gerichte innerhalb des Imperium Germanicum aufheben."]},
    {"id": "hand", "ebene": "Reich", "art": "Reichsombudsmann", "name": "Die Hand des Kaisers",
     "bild": "ib7c33ba7d6bef700", "link": "informationen/hand-des-kaisers/",
     "text": "Seit dem 15.10.2026 ist der König von Hannover vorübergehend die Hand des Kaisers und somit der zweithöchste Amtsträger des Reiches.",
     "fakten": [("Amtsinhaber", "Seine Majestät Ernst August VI."), ("Arbeitssitz", "Berliner Schloss")],
     "gefuege": ["Steht dem Arbeitssitz der Senatsverwaltung der Regierung seiner Majestät vor."]},
    {"id": "stabschefs", "ebene": "Reich", "art": "Oberkommando", "name": "Die gemeinsamen Stabschefs",
     "bild": "iac7a254e9f22265b", "link": "informationen/die-stabschefs/",
     "text": "Die gemeinsamen Stabschefs sind ein administratives Führungsgremium welches direkt von seiner Majestät mit der gesamten Führung und Organisation aller militärischen Kräfte innerhalb des Reiches betraut ist.",
     "fakten": [("Oberbefehlshaber", "Seine Majestät Kaiser Alexander IX."), ("Sitz", "Bendlerblock, Groß-Berlin")],
     "gefuege": ["Seine Majestät erwählt zusammen mit dem Senat die fähigsten Stabsoffiziere im Generalsrang."]},
    {"id": "krs", "ebene": "Reich", "art": "Nachrichtendienst", "name": "Kaiserliches Reichssicherheitsamt",
     "bild": "i4dd5fb31eadc1d24", "link": "informationen/reichssicherheitsamt/",
     "text": "Das kaiserliche Reichssicherheitsamt kurz KRS ist der reichsweite und übergeordnete Nachrichtendienst des Imperium Germanicum.",
     "fakten": [("Generaldirektor", "Generalfeldmarschall Ritter von Bielicki"), ("Sitz", "Hauptquartier des KRS, Groß-Berlin")],
     "gefuege": ["Dem KRS sind durch den Senat weitreichende Kompetenzen zugesprochen worden."]},
    {"id": "reichsbehoerden", "ebene": "Reich", "art": "Verwaltung", "name": "Die Reichsbehörden",
     "bild": "i416b7a1e6d04b155", "link": "informationen/die-reichsbehoerden/",
     "text": "Die Reichsbehörden sind alle Instanzen, die im gesamten Reichsgebiet tätig sind. Ihr Wirken erstreckt sich über das ganze Imperium Germanicum.",
     "fakten": [("Leitung", "Der Kanzler"), ("Gliederung", "Kanzlei, Reichsbehörden, Reichsvertretung")],
     "gefuege": ["Der Kanzler ist Bindeglied zwischen dem Souverän und der Verwaltung."]},
    {"id": "teilstaaten", "ebene": "Gliederung", "art": "Teilstaaten", "name": "Die Teilstaaten",
     "bild": "idbbec25dc54e06be", "link": "das-imperium/",
     "text": "Das Imperium besteht aus vielen Teilstaaten unterschiedlicher Größe, welche ihre inneren Angelegenheiten zumeist selbst bestimmen.",
     "fakten": [("Kurfürstentümer", "9, ihr Landesoberhaupt hat einen Sitz im Senat"),
                ("Übrige Teilstaaten", "Sitz im Reichstag mit ihrer Delegation")],
     "gefuege": ["Das Reichsrecht bricht das Landesrecht, wenn es Differenzen zwischen Gesetzen gibt."]},
]
EBENEN = [("Staatsoberhaupt", "Staatsoberhaupt"), ("Gewalten", "Die drei Gewalten"),
          ("Reich", "Ämter und Behörden des Reiches"), ("Gliederung", "Gliederung")]

GALERIE_EVENT = "Animagic Mannheim 2026"


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

ARROW = icon("arrow")


def kicker(num, text):
    n = f'<span class="tg-kicker__num">{num}</span>' if num else ""
    return f'<p class="tg-kicker">{n}<span>{text}</span></p>'


def btn(href, label, kind="primary", extra=""):
    return f'<a class="tg-btn tg-btn--{kind}" href="{href}"{extra}><span>{label}</span>{ARROW}</a>'


def more(href, label, extra=""):
    return f'<a class="tg-more" href="{href}"{extra}><span>{label}</span>{ARROW}</a>'


def photo(iid, alt, sizes, cls="", eager=False, parallax=False):
    """Großes Foto mit Bildmaske (Aufdecken beim Scrollen) und optional leichter Parallaxe."""
    p = " data-parallax" if parallax else ""
    return (f'<div class="tg-photo {cls}" data-mask><div class="tg-photo__in"{p}>'
            f'{img(iid, alt, sizes, eager=eager)}</div></div>')


def lines(*parts):
    return "".join(f'<span class="tg-line"><span>{p}</span></span>' for p in parts)


def seal(iid, size="64px", cls="tg-seal"):
    return img(iid, "", size, cls=cls)


def breadcrumb(crumbs):
    return S.breadcrumb(crumbs).replace('class="breadcrumb"', 'class="tg-crumbs"')


def page_head(crumbs, title, eyebrow="", lead="", dark=False, aside=""):
    e = kicker("", esc(eyebrow)) if eyebrow else ""
    l = f'<p class="tg-pagehead__lead">{lead}</p>' if lead else ""
    a = f'<div class="tg-pagehead__aside">{aside}</div>' if aside else ""
    return f"""
<header class="tg-pagehead{" has-aside" if aside else ""}">
  <div class="wrap">
    {breadcrumb(crumbs)}
    <div class="tg-pagehead__grid">
      <div>{e}<h1 class="tg-pagehead__title" data-reveal>{title}</h1>{l}</div>
      {a}
    </div>
  </div>
</header>"""


S.page_head = page_head


def aside_staatsaufbau(current):
    links = "".join(
        f'<li><a href="{u(p)}"{" aria-current=\"page\"" if p == current else ""}>{esc(t)}</a></li>'
        for p, _s, t, *_ in INSTITUTIONEN)
    return f"""
<aside class="aside-nav tg-aside" aria-label="Staatsaufbau">
  <h2>Staatsaufbau</h2>
  <ul><li><a href="{u("informationen/")}">Übersicht</a></li>{links}</ul>
  <div class="tg-aside__box">
    <p>Interesse geweckt? Werde ein Teil des Imperium Germanicum.</p>
    {more(u("kontakt/"), "Mitglied werden")}
  </div>
</aside>"""


S.aside_staatsaufbau = aside_staatsaufbau


# ---------------------------------------------------------------------------
# Kopf und Fuß
# ---------------------------------------------------------------------------

def inst_list(cls, current, with_desc=True):
    out = []
    for p, short, _t, desc, emb in INSTITUTIONEN:
        c = ' aria-current="page"' if current == p else ""
        d = f"<small>{esc(desc)}</small>" if with_desc else ""
        out.append(f'<li><a href="{u(p)}"{c}>{seal(emb, "40px")}<span><strong>{esc(short)}</strong>{d}</span></a></li>')
    return f'<ul class="{cls}">{"".join(out)}</ul>'


def section_of(current):
    if current.startswith(("informationen/imperiale-charta/", "informationen/etiketten-guide/", "regelwerk/",
                           "neue-erlasse-und-gesetze/")):
        return "dokumente/"
    if current != "informationen/" and current.startswith("informationen/"):
        return "institutionen"
    for path, _ in NAV:
        if path and current.startswith(path):
            return path
    return ""


def header(current):
    sec = section_of(current)
    items = []
    for path, label in NAV:
        if path == "institutionen":
            cur = ' class="is-current"' if sec == path else ""
            items.append(
                f'<li{cur}><button class="tg-nav__link tg-nav__toggle" type="button" aria-expanded="false" aria-controls="tg-mega">'
                f'{label}{icon("chev")}</button></li>')
        else:
            cur = ' aria-current="page"' if current == path else (' aria-current="true"' if sec == path else "")
            items.append(f'<li><a class="tg-nav__link" href="{u(path)}"{cur}>{label}</a></li>')
    mob = []
    for i, (path, label) in enumerate(NAV, 1):
        if path == "institutionen":
            mob.append(f'<li style="--i:{i}"><details class="tg-menu__group"><summary><span class="tg-menu__num">0{i}</span>{label}{icon("chev")}</summary>'
                       f'{inst_list("tg-menu__sub", current, with_desc=False)}</details></li>')
        else:
            mob.append(f'<li style="--i:{i}"><a href="{u(path)}"><span class="tg-menu__num">0{i}</span>{label}</a></li>')
    tools = f"""
      <span class="tg-lang" role="group" aria-label="Sprache">
        <a href="@@LANG_DE@@" lang="de" hreflang="de" data-lang="de" title="Deutsch">DE</a>
        <a href="@@LANG_EN@@" lang="en" hreflang="en" data-lang="en" title="English">EN</a>
      </span>
      <button class="theme-toggle tg-icon-btn" type="button" aria-label="Zwischen hellem und dunklem Design wechseln">{icon("sun")}{icon("moon")}</button>"""
    return f"""
<a class="skip-link" href="#inhalt">Zum Inhalt springen</a>
<div class="progress" aria-hidden="true"></div>
<header class="tg-header" data-header>
  <div class="tg-header__bar wrap">
    <a class="tg-brand" href="{u("")}" aria-label="Imperium Germanicum – zur Hauptseite">
      {img(LOGO, "", "44px", eager=True)}
      <span class="tg-brand__name">Imperium Germanicum</span>
    </a>
    <nav class="tg-nav" aria-label="Hauptnavigation"><ul>{"".join(items)}</ul></nav>
    <div class="tg-tools">
      {tools}
      <a class="tg-btn tg-btn--primary tg-btn--sm tg-header__cta" href="{u("kontakt/")}"><span>Mitglied werden</span></a>
      <button class="tg-burger" type="button" aria-expanded="false" aria-controls="tg-menu"><span class="tg-burger__bars" aria-hidden="true"><i></i><i></i></span><span class="tg-burger__label">Menü</span></button>
    </div>
  </div>
  <div class="tg-mega" id="tg-mega" hidden>
    <div class="wrap tg-mega__grid">
      <div class="tg-mega__intro">
        {kicker("", "Institutionen")}
        <p class="tg-mega__title">Die Organe und Behörden des Reiches</p>
        {more(u("informationen/") + "#institutionen", "Alle Institutionen")}
      </div>
      {inst_list("tg-mega__list", current)}
    </div>
  </div>
</header>
<div class="tg-menu" id="tg-menu" hidden>
  <nav class="tg-menu__inner wrap" aria-label="Menü">
    <ul class="tg-menu__list">{"".join(mob)}</ul>
    <div class="tg-menu__foot" style="--i:{len(NAV) + 1}">
      {btn(u("kontakt/"), "Mitglied werden")}
      <div class="tg-menu__tools">{tools.replace('class="theme-toggle tg-icon-btn"', 'class="theme-toggle tg-icon-btn" data-theme-alt')}</div>
    </div>
  </nav>
</div>"""


def footer():
    imp = "".join(f'<li><a href="{u(p)}">{l}</a></li>' for p, l in [
        ("das-imperium/", "Das Imperium"), ("informationen/", "Staatsaufbau"), ("der-souveraen/", "Der Souverän"),
        ("dokumente/", "Dokumente"), ("die-bildergalerie/", "Medien"), ("karte/", "Reichskarte"),
        ("informationen/organigramm/", "Organigramm")])
    inst = "".join(f'<li><a href="{u(p)}">{esc(s)}</a></li>' for p, s, *_ in INSTITUTIONEN if "charta" not in p and "etikette" not in p)
    docs = "".join(f'<li><a href="{u(p)}">{l}</a></li>' for p, l in [
        ("informationen/imperiale-charta/", "Imperiale Charta"), ("informationen/etiketten-guide/", "Etiketten-Guide"),
        ("regelwerk/", "Regelwerk"), ("neue-erlasse-und-gesetze/", "Erlasse und Gesetze")])
    return f"""
<footer class="tg-footer">
  <div class="wrap">
    <div class="tg-footer__top">
      <div class="tg-footer__brand">
        {img(LOGO, "", "72px")}
        <p class="tg-footer__name">Imperium Germanicum</p>
        <p>Ein fiktiver Staatenbund in Europa – das interaktive Rollenspiel.</p>
        {btn(u("kontakt/"), "Mitglied werden", "light")}
      </div>
      <div class="tg-footer__cols">
        <div><h2>Das Imperium</h2><ul>{imp}</ul></div>
        <div><h2>Institutionen</h2><ul>{inst}</ul></div>
        <div><h2>Dokumente</h2><ul>{docs}</ul></div>
        <div><h2>Kontakt</h2>
          <address>{S.address_html()}</address>
          <ul class="tg-footer__social">
            <li><a href="mailto:{EMAIL}">{icon("mail")}<span>E-Mail</span></a></li>
            <li><a href="{INSTAGRAM}" rel="noopener" target="_blank">{icon("insta")}<span>Instagram</span></a></li>
            <li><a href="{YOUTUBE}" rel="noopener" target="_blank">{icon("yt")}<span>YouTube</span></a></li>
            <li><a href="{u("vorschlaege/")}">{icon("arrow")}<span>Vorschläge</span></a></li>
          </ul>
        </div>
      </div>
    </div>
    <div class="tg-footer__legal">
      <span>© {S.YEAR} Imperium Germanicum – Das Rollenspiel</span>
      <ul>
        <li><a href="{u("impressum/")}">Impressum</a></li>
        <li><a href="{u("datenschutz/")}">Datenschutz</a></li>
        <li><a href="{u("datenschutz/")}#cookies">Cookie-Richtlinie</a></li>
        <li><a href="{u("sitemap/")}">Sitemap</a></li>
        <li><a href="{u("gewaehrleistung/")}">Gesetzliche Gewährleistung</a></li>
        <li><a href="{u("widerruf/")}">Vertrag widerrufen</a></li>
      </ul>
    </div>
    <p class="tg-footer__note">Testfassung der neuen Website. <a href="/">Zur aktuellen Website</a></p>
  </div>
</footer>"""


# ---------------------------------------------------------------------------
# Seitenrahmen
# ---------------------------------------------------------------------------

PAGES = []


def render(path, title, description, body, current=None, robots="index,follow", in_sitemap=True,
           og_image="og-image.jpg", jsonld=None, show_crowns=True, body_class=""):
    depth = path.count("/")
    Ctx.prefix = "../" * depth
    current = path if current is None else current
    full_title = "Imperium Germanicum – Das interaktive Rollenspiel" if path == "" else f"{title} – Imperium Germanicum"
    url = f"{SITE_URL}/{BASE}/{path}"
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    doc = f"""<!doctype html>
<html lang="de" class="no-js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="noindex,nofollow">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#14243A">
<script>(function(){{var d=document.documentElement;d.className=d.className.replace("no-js","js");try{{var t=localStorage.getItem("ig-theme");if(t!=="dark"&&t!=="light")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";d.setAttribute("data-theme",t)}}catch(e){{}}}})();</script>
<meta property="og:type" content="website">
<meta property="og:locale" content="de_DE">
<meta property="og:site_name" content="Imperium Germanicum">
<meta property="og:title" content="{esc(full_title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE_URL}/assets/{og_image}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/assets/favicon.ico" sizes="any">
<link rel="icon" href="/assets/favicon-32.png" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="preload" href="{ts_asset("fonts/cormorant-latin.woff2")}" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{ts_asset("fonts/inter-latin.woff2")}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/css/site.css?v={S.CSS_VERSION}">
<link rel="stylesheet" href="{ts_asset("css/ts.css")}?v={_hash("css/ts.css")}">
<script src="/assets/js/site.js?v={S.JS_VERSION}" defer></script>
<script src="{ts_asset("js/ts.js")}?v={_hash("js/ts.js")}" defer></script>
{ld}
</head>
<body class="tg {body_class}">
{header(current)}
<main id="inhalt" tabindex="-1">
{body}
</main>
{footer()}
</body>
</html>
"""
    doc = re.sub(r"\n\s*\n", "\n", doc)
    en_path = path if current != "404" else ""  # 404 gibt es nur deutsch
    de_doc = doc.replace("@@LANG_DE@@", "./").replace("@@LANG_EN@@", ("../" * depth) + "en/" + en_path)
    de_doc = de_doc.replace('data-lang="de"', 'data-lang="de" aria-current="true"')
    out_dir = os.path.join(OUT, path)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(de_doc)
    if current != "404":
        en_doc = i18n.to_english(doc, path, depth, f"{SITE_URL}/{BASE}")
        en_dir = os.path.join(OUT, "en", path)
        os.makedirs(en_dir, exist_ok=True)
        with open(os.path.join(en_dir, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(en_doc)
    if in_sitemap:
        PAGES.append(path)


S.render = render


# ---------------------------------------------------------------------------
# Wiederkehrende Abschnitte
# ---------------------------------------------------------------------------

def facts_band(num="02"):
    items = "".join(
        f'<div class="tg-facts__item" data-reveal><dt>{label}</dt>'
        f'<dd><span class="tg-facts__num" data-count="{raw}">{shown}</span>'
        f'{f"<span class=tg-facts__unit>{unit}</span>" if unit else ""}</dd></div>'
        for raw, shown, unit, label in FACTS)
    return f"""
<section class="tg-facts" aria-labelledby="zahlen-titel">
  <div class="wrap">
    <div class="tg-facts__head">
      {kicker(num, "Das Reich in Zahlen")}
      <h2 id="zahlen-titel" class="tg-h3">Ein Staatenbund in Mittel- und Südeuropa</h2>
    </div>
    <dl class="tg-facts__list">{items}</dl>
  </div>
</section>"""


def map_section(num="04", full=False):
    cap = "Hoheitsgebiet des Imperium Germanicum mit seinen Teilstaaten"
    fallback = (f'<a class="tg-map__fallback" href="{u("karte/")}"><img src="{u("karte/karte.png")}" width="3000" height="2250" '
                f'alt="Karte des Hoheitsgebiets des Imperium Germanicum in Mittel- und Südeuropa mit farbig markierten Teilstaaten" '
                f'loading="lazy" decoding="async"></a>')
    text = paras(*GEBIET_TEXT[:1], GEBIET_TEXT[3]) if not full else ""
    return f"""
<section class="tg-mapsec{" is-full" if full else ""}" id="karte" aria-labelledby="karte-titel">
  <div class="wrap">
    <div class="tg-mapsec__head">
      {kicker(num, "Reichskarte")}
      <h2 id="karte-titel" class="tg-h2">Das Hoheitsgebiet und seine Teilstaaten</h2>
      <div class="tg-mapsec__text">{text}<p class="tg-note">Wähle einen Teilstaat auf der Karte oder in der Liste.</p></div>
    </div>
    <div class="tg-mapsec__grid">
      <figure class="tg-map" data-map data-geo="/karte/geo.json" data-daten="/karte/daten.json" data-info="/karte/info.json">
        <div class="tg-map__stage" data-map-stage>{fallback}</div>
        <div class="tg-map__ctrl">
          <button type="button" class="tg-chip" data-map-reset hidden>Gesamtansicht</button>
        </div>
        <figcaption class="tg-map__cap"><span>{esc(cap)}</span><span class="tg-map__src">Kartengrundlage: Eurostat GISCO, © EuroGeographics</span></figcaption>
      </figure>
      <aside class="tg-map__side" aria-label="Teilstaaten">
        <div class="tg-map__panel" data-map-panel aria-live="polite">
          <p class="tg-map__hint">Das Hoheitsgebiet gliedert sich in Teilstaaten unterschiedlicher Größe. Ein Klick auf einen Teilstaat nennt Landesherrn, Fläche und Bevölkerung.</p>
        </div>
        <ul class="tg-map__list" data-map-list></ul>
        {more(u("karte/"), "Zur vollständigen Reichskarte")}
      </aside>
    </div>
  </div>
</section>"""


def structure_section(num="05", heading_level="h2"):
    tiers = []
    for key, label in EBENEN:
        nodes = [s for s in STRUKTUR if s["ebene"] == key]
        btns = "".join(
            f'<button class="tg-org__node" type="button" role="tab" id="org-tab-{s["id"]}" aria-controls="org-{s["id"]}" '
            f'aria-selected="{"true" if s["id"] == "souveraen" else "false"}" tabindex="{0 if s["id"] == "souveraen" else -1}" data-org="{s["id"]}">'
            f'{seal(s["bild"], "56px")}<span class="tg-org__art">{s["art"]}</span><span class="tg-org__name">{s["name"]}</span></button>'
            for s in nodes)
        tiers.append(f'<div class="tg-org__tier tg-org__tier--{key.lower()}"><p class="tg-org__label">{label}</p>'
                     f'<div class="tg-org__nodes">{btns}</div></div>')
    panels = []
    for s in STRUKTUR:
        facts = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in s["fakten"])
        gef = "".join(f"<li>{g}</li>" for g in s["gefuege"])
        panels.append(f"""
<div class="tg-org__panel" role="tabpanel" id="org-{s["id"]}" aria-labelledby="org-tab-{s["id"]}" data-org-panel{"" if s["id"] == "souveraen" else " data-hidden"}>
  {seal(s["bild"], "120px", "tg-org__panel-seal")}
  <p class="tg-org__panel-art">{s["art"]}</p>
  <h3 class="tg-h3">{s["name"]}</h3>
  <p>{s["text"]}</p>
  <dl class="tg-dl">{facts}</dl>
  <h4 class="tg-org__sub">Im Gefüge des Reiches</h4>
  <ul class="tg-org__rel">{gef}</ul>
  {more(u(s["link"]), "Mehr erfahren")}
</div>""")
    return f"""
<section class="tg-org" id="staatsaufbau" aria-labelledby="org-titel">
  <div class="wrap">
    <div class="tg-sechead">
      {kicker(num, "Staatsaufbau")}
      <{heading_level} id="org-titel" class="tg-h2">Die Ordnung des Reiches</{heading_level}>
      <p class="tg-sechead__lead">Souverän, Senat, Reichstag und Reichsgerichtshof bilden die Spitze des Reiches; Ämter und Behörden handeln in seinem Auftrag, die Teilstaaten bestimmen ihre inneren Angelegenheiten zumeist selbst.</p>
    </div>
    <div class="tg-org__grid">
      <div class="tg-org__chart" role="tablist" aria-label="Organe des Reiches" aria-orientation="vertical">{"".join(tiers)}</div>
      <div class="tg-org__panels">{"".join(panels)}</div>
    </div>
    <div class="tg-org__foot">
      <p>Wer wen wählt, ernennt, kontrolliert oder überstimmen kann, zeigt das interaktive Organigramm mit allen gegenwärtigen Amtsträgern.</p>
      {more(u("informationen/organigramm/"), "Zum interaktiven Organigramm")}
    </div>
  </div>
</section>"""


def erlasse_alle():
    """Alle Erlasse wie auf der Hauptseite: Reichsgesetzblatt (neueste zuerst), dann die älteren."""
    out = []
    n_alt = len(S.ERLASSE)
    for n, e in reversed(list(enumerate(S.GESETZBLATT, 1))):
        href = asset(e["dateien"][0]) if e["dateien"] else e["links"][0] if e["links"] else ""
        out.append({"nr": n_alt + n, "art": e["art"], "titel": e["titel"], "bild": e["vorschau"], "href": href,
                    "lightbox": False, "text": e.get("text", "")})
    for n, (iid, iss, title) in enumerate(S.ERLASSE, 1):
        out.append({"nr": n, "art": iss, "titel": title, "bild": iid, "href": S.original(iid), "lightbox": True, "text": ""})
    return out


def doc_link_attrs(e):
    if e["lightbox"]:
        return (f' data-lightbox data-full="{asset(f"img/{e["bild"]}-1280.webp")}" data-caption="{esc(e["art"])} – {esc(e["titel"])}"'
                f' data-gallery="erlasse"')
    return ' target="_blank" rel="noopener"'


def documents_section(num="08", limit=5):
    parts = S.charta_parts()
    n_par = sum(len(p.get("articles", [])) for p in parts)
    n_abs = sum(1 for p in parts if p["num"])
    main_docs = [
        ("informationen/imperiale-charta/", "Imperiale Charta", "Die Verfassung und Satzung des Imperium Germanicum",
         f"Präambel · {n_abs} Abschnitte · {n_par} Paragraphen", "i2e330402e5d67b0a"),
        ("informationen/etiketten-guide/", "Der Etiketten-Guide",
         "Eine Anleitung zur Einhaltung der Etikette und Höflichkeit innerhalb des Reiches", "Anreden, Titel und Rangfolge",
         "i1ed8e9913dc91849"),
        ("regelwerk/", "Das Regelwerk", "Die Richtlinien des Servers und die Regeln des Rollenspiels",
         "Richtlinien des Servers", LOGO),
    ]
    rows = "".join(f"""
<a class="tg-docrow" href="{u(p)}" data-reveal>
  {seal(emb, "72px")}
  <span class="tg-docrow__body"><span class="tg-docrow__title">{t}</span><span class="tg-docrow__desc">{d}</span><span class="tg-docrow__meta">{m}</span></span>
  <span class="tg-docrow__go">{ARROW}</span>
</a>""" for p, t, d, m, emb in main_docs)
    latest = "".join(f"""
<li><a href="{e["href"]}"{doc_link_attrs(e)}><span class="tg-gaz__nr">Nr. {e["nr"]:02d}</span><span class="tg-gaz__art">{esc(e["art"])}</span><span class="tg-gaz__title">{esc(e["titel"])}</span></a></li>"""
                     for e in erlasse_alle()[:limit])
    return f"""
<section class="tg-docs" aria-labelledby="dok-titel">
  <div class="wrap">
    <div class="tg-sechead">
      {kicker(num, "Charta und Dokumente")}
      <h2 id="dok-titel" class="tg-h2">Verfassung, Etikette und Gesetze im Wortlaut</h2>
    </div>
    <div class="tg-docs__grid">
      <div class="tg-docs__main">{rows}</div>
      <div class="tg-docs__gazette">
        <h3 class="tg-label">Erlasse und Gesetze</h3>
        <ol class="tg-gaz">{latest}</ol>
        {more(u("neue-erlasse-und-gesetze/"), "Alle Erlasse und Gesetze")}
      </div>
    </div>
  </div>
</section>"""


def join_section(num="09"):
    steps = [
        ("01", "Regelwerk lesen", "Die Richtlinien des Servers und die Regeln des Rollenspiels gelten für alle Mitglieder.",
         u("regelwerk/"), "Zum Regelwerk"),
        ("02", "Melde dich zum Dienst", "Schreib uns über das Kontaktformular, per E-Mail oder auf Instagram.",
         u("kontakt/"), "Zum Kontaktformular"),
        ("03", "Ideen einbringen", "Vorschläge für den Discord-Server, die Website oder das Rollenspiel reichst du mit deinem Discord-Konto ein.",
         u("vorschlaege/"), "Vorschlag einreichen"),
    ]
    items = "".join(f'<li data-reveal><span class="tg-steps__num">{n}</span><h3>{t}</h3><p>{d}</p>{more(h, l)}</li>'
                    for n, t, d, h, l in steps)
    return f"""
<section class="tg-join" aria-labelledby="join-titel">
  <div class="wrap">
    <div class="tg-join__head">
      {kicker(num, "Mitglied werden")}
      <h2 id="join-titel" class="tg-display tg-display--md">{lines("Deine Geschichte", "im Imperium beginnt hier.")}</h2>
      <div class="tg-join__cta">
        <p>Haben diese Informationen dein Interesse geweckt? Schau dich gerne auf unserer Website um und werde ein Teil des Imperium Germanicum.</p>
        <div class="tg-actions">{btn(u("kontakt/"), "Mitglied werden")}{btn(INSTAGRAM, "Instagram", "ghost", ' rel="noopener" target="_blank"')}</div>
      </div>
    </div>
    <ol class="tg-steps">{items}</ol>
  </div>
</section>"""


def crowns_section():
    figs = "".join(
        f'<figure data-reveal>{img(iid, cap, "(min-width: 720px) 220px, 160px")}<figcaption>{f"<strong>{t}</strong>" if t else ""}{cap}</figcaption></figure>'
        for iid, t, cap in S.CROWNS)
    return f"""
<section class="tg-crowns" aria-labelledby="kronen-titel">
  <div class="wrap">
    {kicker("", "Insignien")}
    <h2 id="kronen-titel" class="tg-h2">Die Kronen des Reiches</h2>
    <div class="tg-crowns__row">{figs}</div>
  </div>
</section>"""


# ---------------------------------------------------------------------------
# Seiten
# ---------------------------------------------------------------------------

WEGWEISER = [  # Fragen eines neuen Besuchers → passende Seite
    ("das-imperium/", "Was ist das Imperium?", "Ein fiktiver Staatenbund in Europa: Idee, Geschichte und Hoheitsgebiet.", "idbbec25dc54e06be"),
    ("informationen/", "Wer regiert das Reich?", "Souverän, Senat, Reichstag und Reichsgerichtshof im Überblick.", "i0ed2170b7ed819f2"),
    ("der-souveraen/", "Wer ist der Kaiser?", "Seine Majestät Alexander IX., Souverän und Staatsoberhaupt.", "i15c0c0ea6780ad72"),
    ("das-imperium/#karte", "Wo liegt das Reich?", "Die Teilstaaten auf der interaktiven Reichskarte.", "i416b7a1e6d04b155"),
    ("dokumente/", "Welche Regeln gelten?", "Imperiale Charta, Etikette, Regelwerk und aktuelle Erlasse.", "i2e330402e5d67b0a"),
    ("kontakt/", "Wie mache ich mit?", "Melde dich zum Dienst und werde ein Teil des Imperium Germanicum.", LOGO),
]


def wegweiser_section():
    items = "".join(f"""
<li data-reveal style="--d:{i * .04:.2f}s"><a class="tg-guide__item" href="{u(p)}">
  {seal(emb, "48px", "tg-guide__seal")}
  <span class="tg-guide__body"><span class="tg-guide__q">{q}</span><span class="tg-guide__a">{a}</span></span>
  <span class="tg-guide__go">{ARROW}</span>
</a></li>""" for i, (p, q, a, emb) in enumerate(WEGWEISER))
    return f"""
<section class="tg-guide" id="wegweiser" aria-labelledby="wegweiser-titel">
  <div class="wrap">
    <div class="tg-guide__head">
      {kicker("", "Wegweiser")}
      <h2 id="wegweiser-titel" class="tg-h3">Neu im Imperium? Hier findest du dich zurecht.</h2>
    </div>
    <ul class="tg-guide__list">{items}</ul>
  </div>
</section>"""


def onpage(links):
    """Sprungleiste „Auf dieser Seite“ (klebt unter dem Kopf, markiert den aktuellen Abschnitt)."""
    a = "".join(f'<a href="#{i}">{l}</a>' for i, l in links)
    return (f'<nav class="tg-onpage" aria-label="Auf dieser Seite" data-onpage><div class="wrap">'
            f'<span class="tg-onpage__label">Auf dieser Seite</span><div class="tg-onpage__links">{a}</div></div></nav>')


def glance(rows, title="Auf einen Blick"):
    dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows)
    return f'<aside class="tg-glance" aria-label="{title}"><p class="tg-label">{title}</p><dl class="tg-dl">{dl}</dl></aside>'


REICH_GLANCE = [
    ("Staatsform", "Teilzentralisierter Bundesstaat"),
    ("Staatsoberhaupt", "Kaiser Alexander IX."),
    ("Reichshauptstadt", "Groß-Berlin"),
    ("Hoheitsgebiet", "1.205.000 km²"),
    ("Staatsbürger", "217.000.000"),
    ("Kurfürsten im Senat", "9"),
    ("Amtszeit des Kaisers", "1 Jahr"),
]


def page_home():
    Ctx.prefix = ""
    hero_src = asset("img/original/" + S.IMAGES["if3da36451cad23de"]["file"])
    hero = f"""
<section class="tg-hero" aria-labelledby="hero-titel">
  <div class="wrap tg-hero__top">
    {kicker("", "Imperium Germanicum · Das interaktive Rollenspiel")}
    <h1 id="hero-titel" class="tg-display tg-hero__title">{lines("Ein Imperium.", "<em>Eine gemeinsame Geschichte.</em>")}</h1>
    <div class="tg-hero__aside">
      <p class="tg-hero__lead">Willkommen im Imperium Germanicum – einem fiktiven Staatenbund in einer alternativen europäischen Gegenwart, in der das Heilige Römische Reich die Jahre überdauert hat.</p>
      <div class="tg-actions">{btn(u("das-imperium/"), "Das Imperium entdecken")}{btn(u("kontakt/"), "Mitglied werden", "ghost")}</div>
    </div>
  </div>
  <figure class="tg-hero__media wrap">
    <div class="tg-photo tg-hero__photo" data-mask><div class="tg-photo__in" data-parallax>
      <img src="{asset("img/if3da36451cad23de-1280.webp")}" srcset="{asset("img/if3da36451cad23de-640.webp")} 640w, {asset("img/if3da36451cad23de-1280.webp")} 1280w, {hero_src} 1440w"
           sizes="(min-width: 1400px) 1360px, 100vw" width="1440" height="600" alt="Schloss Charlottenburg in Groß-Berlin" fetchpriority="high" decoding="async">
    </div></div>
    <figcaption class="tg-cap"><span>Schloss Charlottenburg, Groß-Berlin – private Residenz des Souveräns</span></figcaption>
  </figure>
</section>"""

    discover = f"""
<section class="tg-discover" aria-labelledby="reich-titel">
  <div class="wrap tg-discover__row">
    <div class="tg-discover__text" data-reveal>
      {kicker("01", "Das Reich")}
      <h2 id="reich-titel" class="tg-h2">Das Resultat dieser Entwicklung ist das Imperium Germanicum.</h2>
      {paras(*REICH_TEXT[1:])}
      <div class="tg-actions">{more(u("das-imperium/"), "Mehr über das Imperium")}{more(u("informationen/"), "Zum Staatsaufbau")}</div>
    </div>
    <figure class="tg-discover__media">
      {photo("icb9cbf1ec35c85a0", "Berliner Schloss", "(min-width: 900px) 50vw, 100vw")}
      <figcaption class="tg-cap"><span>Berliner Schloss – Arbeitssitz seiner Majestät und der Senatsverwaltung</span></figcaption>
    </figure>
  </div>
</section>"""

    inst = [x for x in INSTITUTIONEN if "charta" not in x[0] and "etikette" not in x[0]]
    rows = "".join(f"""
<li><a class="tg-index__row" href="{u(p)}">
  {seal(emb, "48px", "tg-index__seal")}
  <span class="tg-index__title">{esc(t)}</span><span class="tg-index__desc">{esc(d)}</span><span class="tg-index__go">{ARROW}</span>
</a></li>""" for p, _s, t, d, emb in inst)
    institutions = f"""
<section class="tg-inst" id="institutionen" aria-labelledby="inst-titel">
  <div class="wrap">
    <div class="tg-sechead tg-sechead--row">
      <div>{kicker("04", "Institutionen")}<h2 id="inst-titel" class="tg-h2">Im Auftrag seiner Majestät</h2></div>
      {more(u("informationen/") + "#institutionen", "Alle Institutionen")}
    </div>
    <ul class="tg-index tg-index--grid">{rows}</ul>
  </div>
</section>"""

    facts_dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in KAISER_FAKTEN)
    sovereign = f"""
<section class="tg-sov" aria-labelledby="sov-titel">
  <div class="wrap tg-sov__grid">
    <figure class="tg-sov__portrait">
      {photo("iceaef15058c1dbef", "Seine Majestät Alexander IX.", "(min-width: 900px) 34vw, 100vw")}
    </figure>
    <div class="tg-sov__text" data-reveal>
      {kicker("05", "Der Souverän")}
      <h2 id="sov-titel" class="tg-display tg-display--md">Alexander IX.</h2>
      <p class="tg-sov__title">{KAISER_TITEL}</p>
      <dl class="tg-dl tg-dl--light">{facts_dl}</dl>
      <div class="tg-actions">{btn(u("der-souveraen/"), "Zum Souverän", "light")}</div>
    </div>
  </div>
</section>"""

    body = hero + wegweiser_section() + facts_band("") + discover + map_section("02") + structure_section("03") + \
        institutions + sovereign + documents_section("06") + join_section("07")
    jsonld = {"@context": "https://schema.org", "@type": "Organization", "name": "Imperium Germanicum – Das Rollenspiel",
              "url": SITE_URL + "/", "email": EMAIL}
    render("", "Hauptseite",
           "Das Imperium Germanicum ist ein fiktiver Staatenbund in Europa – das interaktive Rollenspiel für Monarchie-, Adels-, Militär- und Geschichtsliebhaber.",
           body, jsonld=jsonld, body_class="is-home")


def page_imperium():
    Ctx.prefix = "../"
    body = page_head([("das-imperium/", "Das Imperium")], "Das Imperium", "Ein fiktiver Staatenbund in Europa",
                     INTRO_LEAD, aside=img("idbbec25dc54e06be", "Großes Wappen des Imperium Germanicum", "(min-width: 900px) 260px, 40vw", eager=True)) + \
        onpage([("reich", "Das Reich"), ("karte", "Reichskarte"), ("gebiet", "Hoheitsgebiet"), ("kronen-titel", "Die Kronen")]) + f"""
<section class="tg-section" id="reich">
  <div class="wrap tg-withbox">
    <div class="tg-prose" data-reveal>
      {kicker("01", "Das Reich")}
      <h2 class="tg-h2">Das Resultat dieser Entwicklung ist das Imperium Germanicum.</h2>
      {paras(*REICH_TEXT)}
    </div>
    {glance(REICH_GLANCE)}
  </div>
</section>
{map_section("02", full=True)}
<section class="tg-section" id="gebiet">
  <div class="wrap tg-withbox">
    <div class="tg-prose" data-reveal>
      {kicker("03", "Mittel- und Südeuropa")}
      <h2 class="tg-h2">Hoheitsgebiet des Imperium Germanicum</h2>
      {paras(*GEBIET_TEXT)}
    </div>
    <aside class="tg-glance">
      <p class="tg-label">Weiterlesen</p>
      <ul class="tg-glance__links">
        <li>{more(u("informationen/"), "Der Staatsaufbau")}</li>
        <li>{more(u("informationen/imperiale-charta/"), "Die Imperiale Charta")}</li>
        <li>{more(u("karte/"), "Die vollständige Reichskarte")}</li>
      </ul>
    </aside>
  </div>
</section>
{crowns_section()}"""
    render("das-imperium/", "Das Imperium",
           "Das Imperium Germanicum: ein fiktiver Staatenbund in Mittel- und Südeuropa – das Reich, sein Hoheitsgebiet und seine Teilstaaten.",
           body)


def page_informationen():
    Ctx.prefix = "../"
    rows = "".join(f"""
<li><a class="tg-index__row" href="{u(p)}">
  {seal(emb, "48px", "tg-index__seal")}
  <span class="tg-index__title">{esc(t)}</span><span class="tg-index__desc">{esc(d)}</span><span class="tg-index__go">{ARROW}</span>
</a></li>""" for p, _s, t, d, emb in INSTITUTIONEN)
    body = page_head([("informationen/", "Staatsaufbau")], "Staatsaufbau", "Die Verfassung und Institutionen",
                     "Das Imperium Germanicum verfügt über eine eigene Verfassung, die sogenannte „Imperiale Charta“, über einen Etiketten-Guide und viele staatliche Institutionen.") + \
        onpage([("staatsaufbau", "Die Ordnung des Reiches"), ("institutionen", "Alle Institutionen")]) + \
        structure_section("01") + f"""
<section class="tg-section tg-section--line" id="institutionen" aria-labelledby="alle-titel">
  <div class="wrap">
    <div class="tg-sechead">
      {kicker("02", "Institutionen")}
      <h2 id="alle-titel" class="tg-h2">Alle Institutionen</h2>
      <p class="tg-sechead__lead">Hier erhältst du einen Überblick und Informationen über alle staatlichen Institutionen die im Auftrag seiner Majestät tätig sind.</p>
    </div>
    <ul class="tg-index tg-index--grid">{rows}</ul>
  </div>
</section>"""
    render("informationen/", "Staatsaufbau",
           "Überblick über die Verfassung und alle staatlichen Institutionen des Imperium Germanicum: Charta, Etikette, Senat, Reichstag, Reichsgerichtshof, Stabschefs und KRS.",
           body)


def page_souveraen():
    Ctx.prefix = "../"
    facts_dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in KAISER_FAKTEN)
    bio = [
        "Alexander IX. wurde am 10.05.2004 in Hachenburg der Hauptstadt der Westerwälder Union geboren, seit dem 16.01.2024 ist er König der Westerwälder Union und wurde am 14.05.2026 vom Senat für 1 Jahr zum Kaiser und Oberbefehlshaber der Streitkräfte gewählt.",
        "Er ist selbst einer der 9 Kurfürsten des Reiches und gehört der Fraktion der Westerwälder Union an.",
        "Seine Majestät zeichnet sich vor allem durch ein ruhiges und besonnenes Charakterbild aus, er besitzt aber auch exzentrische Marotten zum Beispiel müssen Kaltgetränke stets mit Eis serviert werden, vorzugsweise Eiskugeln.",
        "Außerdem legt seine Majestät viel Wert auf eine strikte Einhaltung der protokollarischen Etikette.",
        "Seine Majestät beherrschen die deutsche Sprache und etwas gebrochen auch die englische Sprache, er übt im Augenblick die italienische Sprache.",
    ]
    exo = [
        "Ex Officio ist der Souverän nicht nur Kaiser des Imperium Germanicum, sondern in Personalunion auch König von Apulien.",
        "Das Königreich Apulien ist de jure ein selbständiger Staat de facto aber durch Verwaltung und Militär an das Reich gebunden.",
        "Außerdem ist der Souverän zusätzlich Ex Officio der Erzherzog von Österreich wobei Österreich vom Status nicht wie das Königreich Apulien ein eigener Staat unter kaiserlicher Kontrolle ist sondern dem Reich voll angehört.",
        "Aus der Kombination aus Kaiserthron, Königsthron und der Würde des Erzherzogs ergibt sich auch der Titel (kaiserliche und königliche Majestät).",
    ]
    body = f"""
<header class="tg-sovhead">
  <div class="wrap">
    {breadcrumb([("der-souveraen/", "Der Souverän")])}
    <div class="tg-sov__grid">
      <figure class="tg-sov__portrait">
        {S.zoom_link("iceaef15058c1dbef", photo("iceaef15058c1dbef", "Seine Majestät Alexander IX.", "(min-width: 900px) 34vw, 100vw", eager=True), "Seine Majestät Alexander IX.", "kaiser", cls="tg-zoom")}
      </figure>
      <div class="tg-sov__text">
        {kicker("", "Staatsoberhaupt des Imperium Germanicum")}
        <h1 class="tg-display tg-display--md">{lines("Alexander IX.")}</h1>
        <p class="tg-sov__title">{KAISER_TITEL}</p>
        <dl class="tg-dl tg-dl--light">{facts_dl}</dl>
      </div>
    </div>
  </div>
</header>
{onpage([("amt", "Das Amt"), ("lebenslauf", "Lebenslauf"), ("ex-officio", "Ex Officio"), ("sitz", "Arbeitssitz und Residenz"), ("kronen-titel", "Die Kronen")])}
<section class="tg-section">
  <div class="wrap tg-pair tg-pair--text">
    <div class="tg-prose" id="amt" data-reveal>
      {kicker("01", "Das Amt")}
      <h2 class="tg-h3">Der Souverän</h2>
      {paras(*SOUVERAEN_TEXT)}
    </div>
    <div class="tg-prose" id="lebenslauf" data-reveal>
      {kicker("02", "Seine Majestät")}
      <h2 class="tg-h3">Lebenslauf und Charakter</h2>
      {paras(*bio)}
    </div>
  </div>
</section>
<section class="tg-section tg-section--stone" id="ex-officio">
  <div class="wrap tg-twocol">
    <div class="tg-prose" data-reveal>
      {kicker("03", "Ex Officio")}
      <h2 class="tg-h3">Kaiser, König und Erzherzog</h2>
      {paras(*exo)}
    </div>
    <div data-reveal class="tg-twocol__fig">{S.figure("if0978cec8f01efe8", "Standarte von seiner Majestät dem Kaiser", group="kaiser")}</div>
  </div>
</section>
<section class="tg-section" id="sitz">
  <div class="wrap">
    <div class="tg-sechead">
      {kicker("04", "Arbeitssitz und Residenz")}
      <h2 class="tg-h3">Groß-Berlin</h2>
      <p class="tg-sechead__lead">Der Arbeitssitz seiner Majestät befindet sich zusammen mit der Senatsverwaltung im Berliner Schloss. Die private Residenz des Souveräns befindet sich jedoch im Schloss Charlottenburg, welches sich ebenfalls in der Reichshauptstadt befindet.</p>
    </div>
    <div class="tg-quad">
      <figure>{photo("icb9cbf1ec35c85a0", "Berliner Schloss", "(min-width: 900px) 25vw, 50vw")}<figcaption class="tg-cap"><span>Berliner Schloss – Arbeitssitz</span></figcaption></figure>
      <figure>{photo("if3da36451cad23de", "Schloss Charlottenburg", "(min-width: 900px) 25vw, 50vw")}<figcaption class="tg-cap"><span>Schloss Charlottenburg – Residenz</span></figcaption></figure>
      {S.figure("i50101bc1effeb76a", "Seine Majestät Alexander IX. in Uniform", group="kaiser", sizes="(min-width: 900px) 25vw, 50vw")}
      {S.figure("i15c0c0ea6780ad72", "Emblem des Kaisers", "Emblem des Kaisers: Schloss Charlottenburg mit dem Schriftzug Der Kaiser", group="kaiser", sizes="(min-width: 900px) 25vw, 50vw")}
    </div>
  </div>
</section>
{crowns_section()}"""
    render("der-souveraen/", "Der Souverän",
           "Seine kaiserliche und königliche Majestät Alexander IX. – Souverän und Staatsoberhaupt des Imperium Germanicum.",
           body)


def page_dokumente():
    Ctx.prefix = "../"
    body = page_head([("dokumente/", "Dokumente")], "Dokumente", "Charta, Etikette, Regelwerk und Gesetze",
                     "Die Verfassung des Reiches, die Regeln der Etikette und des Servers sowie alle Erlasse und Gesetze im Wortlaut.") + \
        documents_section("01", limit=8)
    render("dokumente/", "Dokumente",
           "Dokumente des Imperium Germanicum: Imperiale Charta, Etiketten-Guide, Regelwerk sowie Erlasse und Gesetze.", body)


def page_erlasse():
    Ctx.prefix = "../"
    alle = erlasse_alle()
    issuers = []
    for e in alle:
        if e["art"] not in issuers:
            issuers.append(e["art"])
    chips = '<button type="button" class="tg-chip" data-archive-filter="alle" aria-pressed="true">Alle</button>' + "".join(
        f'<button type="button" class="tg-chip" data-archive-filter="{esc(i)}" aria-pressed="false">{esc(i)}</button>' for i in issuers)
    cards = []
    for e in alle:
        sheet = img(e["bild"], f'{e["art"]} – {e["titel"]}', "(min-width: 1000px) 22vw, (min-width: 560px) 45vw, 90vw") \
            if e["bild"] else img(LOGO, "")
        cards.append(f"""
<li class="tg-arch__item" data-archive-item data-issuer-name="{esc(e["art"])}" data-search="{esc((e["titel"] + " " + e["art"] + " " + e["text"]).lower())}">
  <a href="{e["href"]}"{doc_link_attrs(e)}>
    <span class="tg-arch__sheet">{sheet}</span>
    <span class="tg-arch__meta"><span>Nr. {e["nr"]:02d}</span><span>2026</span></span>
    <span class="tg-arch__art">{esc(e["art"])}</span>
    <span class="tg-arch__title">{esc(e["titel"])}</span>
  </a>
</li>""")
    body = page_head([("dokumente/", "Dokumente"), ("neue-erlasse-und-gesetze/", "Erlasse und Gesetze")], "Neue Erlasse und Gesetze",
                     "Wirksame Beschlüsse",
                     "Gesetze, Erlasse und Bekanntmachungen des Souveräns, des Senats und der Hand des Kaisers im Wortlaut.") + f"""
<section class="tg-section tg-section--tight" data-archive>
  <div class="wrap">
    <div class="tg-arch__tools">
      <label class="tg-search"><span class="sr-only">Erlasse durchsuchen</span>{icon("search")}<input type="search" placeholder="Titel oder Aussteller suchen" data-archive-search autocomplete="off"></label>
      <div class="tg-chips" role="group" aria-label="Nach Aussteller filtern">{chips}</div>
    </div>
    <div class="tg-arch__year">
      <h2 class="tg-h3">2026</h2>
      <p class="tg-note" aria-live="polite"><span data-archive-count>{len(alle)}</span> / {len(alle)}</p>
    </div>
    <ul class="tg-arch">{"".join(cards)}</ul>
    <p class="tg-note" data-archive-empty hidden>Keine Dokumente gefunden.</p>
  </div>
</section>"""
    render("neue-erlasse-und-gesetze/", "Neue Erlasse und Gesetze",
           "Wirksame Beschlüsse des Imperium Germanicum: Gesetze, Erlasse und Bekanntmachungen des Jahres 2026.", body)


def page_galerie():
    Ctx.prefix = "../"
    items = []
    for iid, alt in S.GALERIE:
        m = S.IMAGES[iid]
        r = m["w"] / m["h"]
        inner = img(iid, alt, "(min-width: 1000px) 33vw, (min-width: 640px) 50vw, 100vw")
        items.append(f'<figure class="tg-gal__item" style="--r:{r:.3f}">'
                     f'{S.zoom_link(iid, inner, alt, "animagic", cls="tg-zoom")}<figcaption>{esc(alt)}</figcaption></figure>')
    body = page_head([("die-bildergalerie/", "Die Bildergalerie")],
                     "Bildergalerie von Events an denen das Imperium Germanicum teilgenommen hat", "Die Bildergalerie") + f"""
<section class="tg-section tg-section--tight">
  <div class="wrap">
    <div class="tg-arch__year">
      <h2 class="tg-h3">{GALERIE_EVENT}</h2>
      <p class="tg-note">{len(S.GALERIE)} Aufnahmen · Zum Vergrößern anklicken</p>
    </div>
    <div class="tg-gal">{"".join(items)}</div>
  </div>
</section>"""
    render("die-bildergalerie/", "Die Bildergalerie",
           "Bildergalerie von Events, an denen das Imperium Germanicum teilgenommen hat – Animagic Mannheim 2026.", body)


def page_404():
    Ctx.prefix = "../"
    body = f"""
<section class="tg-section"><div class="wrap tg-404">
  {img(LOGO, "", "120px")}
  {kicker("", "Fehler 404")}
  <h1 class="tg-h2">Diese Seite wurde nicht gefunden.</h1>
  <p>Die angeforderte Seite existiert nicht oder wurde verschoben.</p>
  <div class="tg-actions">{btn(u(""), "Zur Hauptseite")}{btn(u("sitemap/"), "Sitemap", "ghost")}</div>
</div></section>"""
    render("404/", "Seite nicht gefunden", "Diese Seite wurde nicht gefunden.", body, current="404", in_sitemap=False)


# Seiten der Hauptseite, die mit neuem Rahmen übernommen werden (Inhalt unverändert)
UEBERNOMMEN = ["page_charta", "page_etikette", "page_hand", "page_senat", "page_reichstag", "page_reichsgerichtshof",
               "page_stabschefs", "page_krs", "page_reichsbehoerden", "page_kanzler", "page_regelwerk", "page_kontakt",
               "page_sitemap", "page_impressum", "page_datenschutz", "page_gewaehrleistung", "page_widerruf"]


def main():
    i18n.MISSING.clear()
    page_home()
    page_imperium()
    page_informationen()
    page_souveraen()
    page_dokumente()
    page_erlasse()
    page_galerie()
    page_404()
    for name in UEBERNOMMEN:
        getattr(S, name)()
    S.thanks_page("kontakt/danke/", [("kontakt/", "Kontakt"), ("kontakt/danke/", "Nachricht gesendet")],
                  "Vielen Dank für deine Nachricht!",
                  "Deine Nachricht ist bei uns eingegangen. Wir melden uns so bald wie möglich bei dir.",
                  ("", "Zur Hauptseite"))
    with open(os.path.join(HERE, "testseite_en_missing.json"), "w", encoding="utf-8") as fh:
        json.dump(i18n.MISSING, fh, ensure_ascii=False, indent=0)
    print(f"{len(PAGES)} Seiten unter /{BASE}/ erzeugt (de + en); {len(i18n.MISSING)} fehlende englische Texte.")


if __name__ == "__main__":
    main()
