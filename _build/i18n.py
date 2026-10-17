"""Erzeugt aus den deutschen Seiten die englische Variante (Verzeichnis /en/).

Die Texte stehen in _build/en.json (Schlüssel = deutscher Text bzw. innerer HTML-Block,
Wert = englische Übersetzung). Fehlt ein Eintrag, bleibt der deutsche Text stehen und
der Schlüssel landet in _build/en_missing.json.
"""
import json
import os
import re

from bs4 import BeautifulSoup, NavigableString, Tag

HERE = os.path.dirname(os.path.abspath(__file__))
DICT_FILE = os.path.join(HERE, "en.json")
MISSING_FILE = os.path.join(HERE, "en_missing.json")

try:
    with open(DICT_FILE, encoding="utf-8") as fh:
        DICT = json.load(fh)
except FileNotFoundError:
    DICT = {}

MISSING = {}

INLINE = {"a", "strong", "em", "b", "i", "span", "br", "sup", "sub", "small", "abbr", "time", "u", "mark",
          "cite", "q", "svg", "img", "wbr"}
SKIP = {"script", "style", "svg", "head", "html", "body", "title"}
TEXT_ATTRS = ("alt", "aria-label", "title", "placeholder", "data-caption")
FILTER_ATTRS = ("data-issuer", "data-doc-filter")
URL_ATTRS = ("href", "src", "srcset", "data-full", "action")

URL_RE_CACHE = {}


def _norm_urls(html_text):
    return re.sub(r'(href|src)="(?!https?:|mailto:|#|tel:)(?:\.\./)*(?:\./)?', r'\1="@/', html_text)


def _tokenize(el):
    """Innerer HTML eines Elements mit svg/img durch Platzhalter ersetzt."""
    store = []
    clone = BeautifulSoup(el.decode_contents(), "html.parser")
    for tag in clone.find_all(["svg", "img"]):
        store.append(str(tag))
        tag.replace_with(NavigableString(f"[[{len(store) - 1}]]"))
    text = re.sub(r"\s+", " ", clone.decode_contents().strip())
    return _norm_urls(text), store


def _lookup(key):
    if key in DICT and DICT[key]:
        return DICT[key]
    MISSING[key] = ""
    return None


def _tr_plain(text):
    """Übersetzt einen einfachen Attribut- oder Titeltext."""
    t = text.strip()
    if not t or not re.search(r"[A-Za-zÄÖÜäöüß]", t):
        return text
    hit = _lookup(re.sub(r"\s+", " ", t))
    return hit if hit else text


def _is_unit(el):
    if el.name in SKIP:
        return False
    if not any(isinstance(c, NavigableString) and c.strip() for c in el.children):
        return False
    return not any(isinstance(d, Tag) and d.name not in INLINE and d.parent.name != "svg" and not _in_svg(d)
                   for d in el.descendants)


def _in_svg(tag):
    return any(p.name == "svg" for p in tag.parents)


def _translate_units(soup, prefix):
    done = set()
    for el in list(soup.find_all(True)):
        if el.name in SKIP or id(el) in done:
            continue
        if any(p.name in ("script", "style", "svg", "head", "title") for p in el.parents):
            continue
        if any(id(p) in done for p in el.parents):
            continue
        if not _is_unit(el):
            continue
        key, store = _tokenize(el)
        if not re.search(r"[A-Za-zÄÖÜäöüß]{2}", re.sub(r"\[\[\d+\]\]|<[^>]+>", "", key)):
            continue
        hit = _lookup(key)
        if not hit:
            continue
        val = re.sub(r"\[\[(\d+)\]\]", lambda m: store[int(m.group(1))], hit)
        val = val.replace('="@/', '="' + prefix).replace('href=""', 'href="./"')
        el.clear()
        for node in list(BeautifulSoup(val, "html.parser").contents):
            el.append(node)
        for d in el.descendants:
            done.add(id(d))
        done.add(id(el))


def _fix_url(value, prefix):
    pat = r"(^|,\s*)" + re.escape(prefix) + r"(assets/|api/)"
    return re.sub(pat, lambda m: m.group(1) + "../" + prefix + m.group(2), value)


def to_english(doc, path, depth, site_url):
    prefix = "../" * depth
    soup = BeautifulSoup(doc, "html.parser")

    _translate_units(soup, prefix)

    for el in soup.find_all(True):
        for a in TEXT_ATTRS:
            if el.has_attr(a):
                el[a] = _tr_plain(el[a])
        for a in FILTER_ATTRS:
            if el.has_attr(a) and el[a] != "alle":
                el[a] = _tr_plain(el[a])
        if el.name == "meta" and el.get("name") in ("description", "twitter:title") or \
                (el.name == "meta" and el.get("property") in ("og:title", "og:description")):
            el["content"] = _tr_plain(el["content"])
        for a in URL_ATTRS:
            if el.has_attr(a) and isinstance(el[a], str):
                el[a] = _fix_url(el[a], prefix)

    title = soup.find("title")
    if title and title.string:
        title.string = _tr_plain(title.string)

    html_tag = soup.find("html")
    html_tag["lang"] = "en"
    for m in soup.find_all("meta", property="og:locale"):
        m["content"] = "en_US"
    canon = soup.find("link", rel="canonical")
    en_url = f"{site_url}/en/{path}"
    if canon:
        canon["href"] = en_url
    for m in soup.find_all("meta", property="og:url"):
        m["content"] = en_url
    for inp in soup.find_all("input", attrs={"name": "lang"}):
        inp["value"] = "en"

    out = str(soup)
    root_up = "../" * (depth + 1)
    out = out.replace("@@LANG_DE@@", root_up + path if path else root_up)
    out = out.replace("@@LANG_EN@@", "./")
    out = out.replace('data-lang="en"', 'data-lang="en" aria-current="true"')
    return out


def report():
    with open(MISSING_FILE, "w", encoding="utf-8") as fh:
        json.dump(MISSING, fh, ensure_ascii=False, indent=0)
    return len(MISSING)
