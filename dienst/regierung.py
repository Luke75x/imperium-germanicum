"""Die Reichsregierung: eigener Webauftritt unter /regierung/ (nginx: /regierung/ → Dienst), losgelöst vom Design der Hauptseite.

Gestaltung wie Amtsseite/Schatzamt (amt.CSS + rp_glas): Seitenleiste mit Logo „Die Reichsregierung“, Kopfzeile mit Pfad und Suche,
Tab-Leiste am Handy. Funktioniert auch ohne Anmeldung (Gastansicht mit „Anmelden“ statt Konto-Box).
Aufbau nach bundesregierung.de:
  /regierung/                     Startseite: Top-Meldung, Newsroom, Die Reichsregierung im Überblick, Die Ressorts, Hinweise der Ressorts
  /regierung/aktuelles/           alle Meldungen (eigene Pressemitteilungen + Meldungen der Ressorts über QUELLEN), Filter nach Art
  /regierung/aktuelles/<id>/      Meldung der Reichsregierung
  /regierung/reichsregierung/     Souverän, Kronkanzler, Kabinett (Leitungen der Reichsbehörden, Namen aus Discord)
  /regierung/ressorts/            alle Reichsbehörden (Daten aus _build/reichsbehoerden.py der Website), /ressorts/<schl>/ Steckbrief
                                  mit Link zum eigenen Webauftritt (Generalkonsulat, Schatzamt) bzw. zur Seite auf der Website
  /regierung/suche/               Suche über Meldungen, Ressorts und die Suchquellen der Ressorts (SUCHE)
  /regierung/intern/              Redaktion (Pressemitteilungen, Reden, Kabinettsbeschlüsse): Kaiser, Kronkanzler, OOC-Admins
Ressorts mit eigenem Webauftritt hängen sich ein (generalkonsulat.py): rahmen(..., portal=…) mit eigener Navigation und Logo,
QUELLEN (Meldungen für den Newsroom), HINWEISE (Kästen auf der Startseite), SUCHE (Treffer für die Suche).
Tabelle regierung_meldungen.
"""
import html
import importlib.util
import json
import os
import re
import secrets
import time
from datetime import datetime

from aiohttp import web

import amt
import anmeldung
import bereiche
import config

esc = html.escape
PFAD = "/regierung/"
LOGO_ORDNER = os.path.join(config.HIER, "amt_logos")
LOGOS_ERLAUBT = {"regierung", "generalkonsulat", "kanzler", "reichsbehoerden", "schatzamt"}
ROLLE_SOUVERAEN = "1522685953054081054"
MELDUNGSARTEN = {"pressemitteilung": "Pressemitteilung", "artikel": "Artikel", "rede": "Rede", "kabinett": "Kabinettsbeschluss"}
# Ressorts mit eigenem Webauftritt (Schlüssel aus reichsbehoerden.py → Pfad)
WEBAUFTRITTE = {"generalkonsulat": PFAD + "generalkonsulat/", "schatzamt": "/schatzamt/"}
# Leitungsrollen je Ressort (Namen im Kabinett); was fehlt, erscheint ohne Namen
LEITUNG_ROLLEN = {"kanzlei": [amt.ROLLE_KANZLER], "generalkonsulat": ["1522702617833246822"]}
for _b in amt.BEHOERDEN:
    if _b["leitung"]:
        LEITUNG_ROLLEN.setdefault(_b["schl"], _b["leitung"])
QUELLEN = []    # fn(con) -> [{titel, kurz, art, zeit, url, quelle}]
HINWEISE = []   # fn(con) -> HTML für die Startseite
SUCHE = []      # fn(con, q) -> [(Art, Titel, URL)]

amt.ICONS.setdefault("globe", '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>')
amt.ICONS.setdefault("newspaper", '<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/>'
                      '<path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/>')
amt.ICONS.setdefault("building", '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/>'
                     '<path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>')
amt.ICONS.setdefault("info", '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>')
amt.ICONS.setdefault("log-in", '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" x2="3" y1="12" y2="12"/>')
amt.ICONS.setdefault("life-buoy", '<circle cx="12" cy="12" r="10"/><path d="m4.93 4.93 4.24 4.24"/><path d="m14.83 9.17 4.24-4.24"/><path d="m14.83 14.83 4.24 4.24"/>'
                     '<path d="m9.17 14.83-4.24 4.24"/><circle cx="12" cy="12" r="4"/>')
amt.ICONS.setdefault("wallet", '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/>'
                     '<path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>')
ic = amt.ic

SCHEMA = """
CREATE TABLE IF NOT EXISTS regierung_meldungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, titel TEXT NOT NULL, art TEXT NOT NULL DEFAULT 'pressemitteilung', kurz TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'entwurf', autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '',
    erstellt INTEGER NOT NULL, veroeffentlicht INTEGER);
"""

# Inhaltsbausteine im Stil der Amtsseite (Variablen aus amt.CSS: --ink --grau --linie --hell --kopf --akzent --r --ok --warn --rot)
CSS = """<style>
.rg-krumen{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:13.5px;color:var(--grau);min-width:0}
.rg-krumen a{color:var(--grau);text-decoration:none}.rg-krumen a:hover{color:var(--ink)}
.rg-krumen span[aria-current]{color:var(--ink);font-weight:600}
@media(max-width:800px){.rg-krumen{display:none}}
.rg-kopf{margin:0 0 20px}.rg-kopf .rg-art{display:block;margin-bottom:6px}
.rg-lead{font-size:16.5px;color:#454a52;max-width:760px;margin:8px 0 0}
.rg-art{font:600 11.5px/1.2 var(--schrift);letter-spacing:.08em;text-transform:uppercase;color:var(--akzent)}
.rg-datum{font-size:13px;color:var(--grau)}
.rg-held{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);border-radius:calc(var(--r) + 4px);overflow:hidden;background:var(--kopf);color:#fff;
 text-decoration:none;margin:0 0 30px;box-shadow:0 12px 34px -18px rgba(16,24,40,.55)}
.rg-held .rg-held-text{padding:clamp(22px,4vw,40px)}
.rg-held .rg-art{color:#f2c94c}
main .rg-held h2,main .rg-held .rg-held-text h2{border:0!important;color:#fff!important;font-size:clamp(22px,3vw,30px)!important;line-height:1.2!important;margin:10px 0 12px!important;padding:0!important;text-transform:none!important;letter-spacing:-.01em!important;font-weight:650!important;display:block!important}
.rg-held p{color:rgba(255,255,255,.82);margin:0 0 16px;font-size:15.5px}.rg-held .rg-datum{color:rgba(255,255,255,.65)}
.rg-held .rg-held-bild{display:grid;place-items:center;background:radial-gradient(circle at 50% 40%,rgba(255,255,255,.14),transparent 65%);padding:24px}
.rg-held .rg-held-bild img{width:min(100%,260px);height:auto;filter:brightness(0) invert(1);opacity:.92}
@media(max-width:800px){.rg-held{grid-template-columns:1fr}.rg-held .rg-held-bild{display:none}}
.rg-abschnitt{margin:0 0 34px}
.rg-abschnitt>h2{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.rg-abschnitt>h2{flex-wrap:wrap}.rg-abschnitt>h2 a{font-size:13.5px;font-weight:500;text-decoration:none;white-space:nowrap;margin-left:auto}
.rg-karten{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,250px),1fr));gap:14px}
.rg-karte{display:flex;flex-direction:column;gap:6px;border:1px solid var(--linie);border-radius:var(--r);padding:16px 18px;color:var(--ink);text-decoration:none;
 background:#fff;transition:border-color .15s,box-shadow .15s,transform .15s}
a.rg-karte:hover{border-color:#c6ccd6;box-shadow:0 8px 22px -14px rgba(16,24,40,.35);transform:translateY(-1px)}
.rg-karte h3{margin:0;font-size:16.5px;line-height:1.3}.rg-karte p{margin:0;color:#50555d;font-size:14px;flex:1}
.rg-karte .rg-logo{height:40px;width:auto;max-width:100%;object-fit:contain;object-position:left;margin-bottom:4px}
.rg-karte .rg-ic{width:40px;height:40px;border-radius:10px;display:grid;place-items:center;background:var(--hell);color:var(--akzent)}
.rg-mehr{font-size:13.5px;font-weight:600;color:var(--akzent);text-decoration:none;display:inline-flex;gap:6px;align-items:center}
.rg-mehr .icon{width:15px;height:15px}
.rg-liste{list-style:none;margin:0;padding:0;border-top:1px solid var(--linie)}
.rg-liste li{border-bottom:1px solid var(--linie);padding:11px 0;display:flex;gap:14px;justify-content:space-between;align-items:baseline;flex-wrap:wrap}
.rg-liste a{color:var(--ink);text-decoration:none;font-weight:500}.rg-liste a:hover{color:var(--akzent)}
.rg-schnell{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
.rg-schnell a{border:1px solid var(--linie);border-radius:999px;padding:6px 14px;font-size:13.5px;color:var(--ink);text-decoration:none;background:#fff}
.rg-schnell a:hover,.rg-schnell a.aktiv{border-color:var(--kopf);background:var(--kopf);color:#fff}
.rg-person{display:flex;gap:14px;align-items:center;border:1px solid var(--linie);border-radius:var(--r);padding:14px 16px;background:#fff}
.rg-person .avatar{width:46px;height:46px;font-size:15px}
.rg-person b{display:block;font-size:15.5px}.rg-person small{display:block;color:var(--grau);font-size:13px}
.rg-text{max-width:760px;font-size:15.5px}.rg-text p{margin:0 0 1em;white-space:pre-line}
.rg-daten{display:grid;grid-template-columns:minmax(0,200px) minmax(0,1fr);border-top:1px solid var(--linie);margin:0 0 22px;max-width:860px}
.rg-daten dt,.rg-daten dd{margin:0;padding:9px 0;border-bottom:1px solid var(--linie)}.rg-daten dt{color:var(--grau);padding-right:14px}
@media(max-width:560px){.rg-daten{grid-template-columns:1fr}.rg-daten dt{border:0;padding-bottom:0}}
.rg-tab{width:100%;border-collapse:collapse;font-size:14.5px;margin:0 0 20px}
.rg-tab th,.rg-tab td{text-align:left;padding:9px 10px 9px 0;border-bottom:1px solid var(--linie);vertical-align:top}
.rg-tab th{font-weight:600;color:var(--grau);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
@media(max-width:700px){.rg-tab thead{display:none}.rg-tab tr{display:block;border-bottom:1px solid var(--linie);padding:8px 0}.rg-tab td{display:block;border:0;padding:2px 0}}
.rg-form{display:grid;gap:14px;max-width:760px;margin:0 0 24px}
.rg-form label{display:grid;gap:5px;font-weight:600;font-size:13.5px;color:#3d4148}
.rg-form input,.rg-form select,.rg-form textarea{font:inherit;font-weight:400;font-size:15px;padding:9px 11px;border:1px solid var(--linie);background:#fff;color:var(--ink);
 border-radius:8px;width:100%;box-sizing:border-box}
.rg-form textarea{min-height:130px;resize:vertical}.rg-zwei{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:640px){.rg-zwei{grid-template-columns:1fr}.rg-form input,.rg-form select,.rg-form textarea{font-size:16px}}
.rg-check{display:flex!important;gap:8px;align-items:center;font-weight:400!important}.rg-check input{width:auto}
.rg-knoepfe{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.rg-ok{border:1px solid var(--linie);border-left:4px solid var(--ok);background:var(--hell);padding:10px 14px;margin:0 0 16px;border-radius:8px}
.rg-ok.fehler{border-left-color:var(--rot)}
.rg-fuss{margin-top:48px;padding-top:16px;border-top:1px solid var(--linie);display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--grau)}
.rg-fuss a{color:var(--grau);text-decoration:none}.rg-fuss a:hover{color:var(--ink)}
@media(max-width:800px){.rg-fuss{margin-bottom:calc(var(--tab) + 28px)}}
.rg-anmelden{display:flex;align-items:center;gap:10px;padding:10px 10px 2px}
</style>"""


# ---------------------------------------------------------------- Rechte, Daten

def ist_redaktion(k):
    return bool(k) and bool(k["mitglied"]) and bereiche._alle(k)


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


_RB = {"zeit": None, "mod": None}


def ressorts():
    """Reichsbehörden aus dem Website-Repo (_build/reichsbehoerden.py, reine Daten), bei Änderung neu geladen."""
    pfad = os.path.join(config.WEBSITE_DIR, "_build", "reichsbehoerden.py")
    try:
        m = os.path.getmtime(pfad)
        if m != _RB["zeit"]:
            spec = importlib.util.spec_from_file_location("reichsbehoerden_daten", pfad)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _RB.update(zeit=m, mod=mod)
    except Exception:
        if _RB["mod"] is None:
            return [], {}
    mod = _RB["mod"]
    return mod.alle(), getattr(mod, "GRUPPEN", {})


def ressort_url(b):
    return WEBAUFTRITTE.get(b["schl"]) or ("/" + b.get("seite", f"informationen/die-reichsbehoerden/{b['schl']}/").lstrip("/"))


def datum(ts, uhr=False):
    if not ts:
        return "–"
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y, %H:%M Uhr" if uhr else "%d.%m.%Y")


def absatz(t):
    return "".join(f"<p>{esc(a)}</p>" for a in re.split(r"\n\s*\n", (t or "").strip()) if a.strip())


def opt(werte, aktuell):
    return "".join(f'<option value="{esc(str(w))}"{" selected" if str(w) == str(aktuell) else ""}>{esc(t)}</option>' for w, t in werte)


def csrf_feld(request):
    return f'<input type="hidden" name="csrf" value="{esc(request.get("csrf", ""))}">'


async def post_pruefen(request, pruefung=None):
    k = await anmeldung.konto(request)
    if not k or not k["mitglied"]:
        raise web.HTTPForbidden(text="Bitte anmelden.")
    if pruefung and not pruefung(k):
        raise web.HTTPForbidden(text="Dafür fehlt dir die Berechtigung.")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), str(request.get("csrf", ""))):
        raise web.HTTPForbidden(text="Sitzung abgelaufen – bitte neu laden.")
    return k, form


def weiter(url, m=None, f=None):
    from urllib.parse import quote
    zus = (f"m={quote(m)}" if m else "") + (f"f={quote(f)}" if f else "")
    raise web.HTTPSeeOther(url + (("&" if "?" in url else "?") + zus if zus else ""))


async def konto_oder_login(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    return k


async def namen_mit_rollen(request, rollen):
    try:
        return sorted(m["name"] for m in await request.app["discord"].mitglieder() if set(rollen) & set(m["rollen"]))
    except Exception:
        return []


def kopf(titel, lead="", art=""):
    return (f'<div class="rg-kopf">{f"<span class=rg-art>{esc(art)}</span>" if art else ""}<h1>{esc(titel)}</h1>'
            f'{f"<p class=rg-lead>{lead}</p>" if lead else ""}</div>')


# ---------------------------------------------------------------- Rahmen

def _gruppen_regierung(k):
    g = [("Reichsregierung", [("r-start", "house", "Startseite", ""), ("r-aktuelles", "newspaper", "Aktuelles", "aktuelles/"),
                              ("r-regierung", "landmark", "Die Reichsregierung", "reichsregierung/"), ("r-ressorts", "building", "Die Ressorts", "ressorts/")]),
         ("Webauftritte der Ressorts", [("r-gk", "globe", "Generalkonsulat", "generalkonsulat/"), ("r-sa", "wallet", "Schatzamt", "/schatzamt/")]),
         ("Service", [("r-suche", "search", "Suche", "suche/")])]
    if ist_redaktion(k):
        g[2][1].append(("r-intern", "pencil", "Redaktion", "intern/"))
    return g


PORTAL_REGIERUNG = {"basis": PFAD, "logo": "regierung", "name": "Die Reichsregierung", "start": "Reichsregierung",
                    "haupt": [("r-start", "house", "Start", ""), ("r-aktuelles", "newspaper", "Aktuelles", "aktuelles/"),
                              ("r-regierung", "landmark", "Regierung", "reichsregierung/"), ("r-ressorts", "building", "Ressorts", "ressorts/")]}


def rahmen(request, k, titel, aktiv, inhalt, portal=None, krumen=None, q="", status=200):
    """Ganze Seite im Stil der Amtsseite. portal: {basis, logo, name, start, gruppen, haupt, suche_url}; ohne → Reichsregierung.
    krumen: [(Text, URL oder None)] nach dem Portalnamen."""
    p = dict(PORTAL_REGIERUNG, gruppen=_gruppen_regierung(k)) if portal is None else portal
    basis = p["basis"]

    def ziel(pfad):
        return pfad if pfad.startswith("/") else basis + pfad

    def ein(schl, sym, text, pfad):
        cur = ' aria-current="page"' if schl == aktiv else ""
        return f'<a class="ein{" aktiv" if schl == aktiv else ""}" href="{ziel(pfad)}"{cur}>{ic(sym)}<span>{esc(text)}</span></a>'

    nav = "".join(f'<div class="gruppe"><p class="gruppe-titel">{esc(t)}</p>{"".join(ein(*e) for e in es)}</div>' for t, es in p["gruppen"])
    haupt = p["haupt"][:4]
    im_menue = aktiv not in {e[0] for e in haupt}
    tabs = "".join(f'<a href="{ziel(pf)}" class="{"aktiv" if s == aktiv else ""}"{" aria-current=page" if s == aktiv else ""}>{ic(sym)}<span>{esc(t)}</span></a>'
                   for s, sym, t, pf in haupt)
    tabs += (f'<button type="button" id="menue-auf" class="{"aktiv" if im_menue else ""}" aria-controls="menue" aria-expanded="false">'
             f'{ic("layout-grid")}<span>Menü</span></button>')
    kr = [(p["start"], basis)] + list(krumen or ([] if aktiv.endswith("start") else [(titel, None)]))
    krumen_html = '<nav class="rg-krumen" aria-label="Pfad">' + " › ".join(
        f'<a href="{esc(u)}">{esc(t)}</a>' if u else f'<span aria-current="page">{esc(t)}</span>' for t, u in kr) + "</nav>"
    such_url = p.get("suche_url", PFAD + "suche/")
    suche = (f'<form class="suche" action="{such_url}" method="get" role="search">{ic("search")}'
             f'<input type="search" name="q" value="{esc(q)}" placeholder="Suchen …" aria-label="Suchen"></form>'
             f'<button class="knopf-rund such-auf" type="button" aria-label="Suche öffnen" aria-expanded="false">{ic("search")}</button>')
    if k:
        konto = (f'<div class="konto-box"><span class="avatar" aria-hidden="true">{esc(amt._initialen(k["name"]))}</span>'
                 f'<span class="konto-text"><b>{esc(k["name"])}</b><small>{esc(p["name"])}</small></span>'
                 f'<form method="post" action="/abmelden/"><input type="hidden" name="csrf" value="{esc(request.get("csrf", ""))}"><input type="hidden" name="weiter" value="{basis}">'
                 f'<button class="knopf-rund" type="submit" title="Abmelden" aria-label="Abmelden">{ic("log-out")}</button></form></div>')
    else:
        konto = f'<a class="ein" href="/anmelden/?weiter={esc(request.path_qs)}">{ic("log-in")}<span>Mit Discord anmelden</span></a>'
    m, f = request.query.get("m"), request.query.get("f")
    note = (f'<div class="rg-ok">{esc(m)}</div>' if m else "") + (f'<div class="rg-ok fehler">{esc(f)}</div>' if f else "")
    import rp_glas
    import profil_sa
    glas = rp_glas.CSS if rp_glas.GLAS else ""
    glas_js = rp_glas.JS if rp_glas.GLAS else ""
    if k:
        glas += profil_sa.darstellung_css(request.app["db"], k)
        if amt.ist_ooc_admin(k):
            suche = (rp_glas.ooc_pille() if rp_glas.GLAS else "") + suche
    fuss = ('<footer class="rg-fuss"><span>© Imperium Germanicum – Die Reichsregierung</span><a href="/">imperiumgermanicum.de</a>'
            '<a href="/impressum/">Impressum</a><a href="/datenschutz/">Datenschutz</a><a href="/kontakt/">Kontakt</a></footer>')
    seite = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#ffffff"><title>{esc(titel)} – {esc(p["name"])}</title><style>{amt.CSS}</style>
<script>document.documentElement.className="min"</script></head>
<body><div class="ladebalken" aria-hidden="true"></div>
<div class="app">
<aside class="seite" id="menue" aria-label="Navigation">
<div class="blatt-kopf"><b>Menü</b><button class="knopf-rund" type="button" id="menue-zu" aria-label="Menü schließen">{ic("x")}</button></div>
<a class="logo" href="{basis}" title="{esc(p["name"])}"><img src="{PFAD}logo/{p["logo"]}-kopf.png" alt="{esc(p["name"])}"></a>
<div class="gruppen">{nav}</div>
<div class="fuss"><a class="ein" href="/">{ic("house")}<span>Zur Website</span></a>{konto}</div>
</aside>
<div class="spalte">
<header class="kopf"><a class="logo" href="{basis}" title="{esc(p["name"])}"><img src="{PFAD}logo/{p["logo"]}-kurz.png" alt="{esc(p["name"])}"></a>{krumen_html}<span class="raum"></span>{suche}</header>
<main id="inhalt">{CSS}{glas}{note}{inhalt}{fuss}{glas_js}</main>
</div></div>
<div class="schleier" id="schleier"></div>
<nav class="tableiste" aria-label="Schnellzugriff">{tabs}</nav>
<script>{amt.JS % json.dumps(basis)}</script></body></html>"""
    return web.Response(status=status, text=seite, content_type="text/html", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- Meldungen (eigene + Ressorts)

def _eigene(con):
    return [{"titel": m["titel"], "kurz": m["kurz"], "art": MELDUNGSARTEN.get(m["art"], "Meldung"), "zeit": m["veroeffentlicht"],
             "url": f"{PFAD}aktuelles/{m['id']}/", "quelle": "Reichsregierung", "schl": m["art"]}
            for m in con.execute("SELECT * FROM regierung_meldungen WHERE status='veroeffentlicht' ORDER BY veroeffentlicht DESC LIMIT 200")]


def alle_meldungen(con):
    out = _eigene(con)
    for q in QUELLEN:
        try:
            out += q(con)
        except Exception:
            pass
    return sorted(out, key=lambda x: x["zeit"] or 0, reverse=True)


def _karte(m):
    return (f'<a class="rg-karte" href="{esc(m["url"])}"><span class="rg-art">{esc(m["art"])} · {esc(m["quelle"])}</span><h3>{esc(m["titel"])}</h3>'
            f'<p>{esc(m["kurz"])}</p><span class="rg-datum">{datum(m["zeit"])}</span></a>')


# ---------------------------------------------------------------- Seiten

async def logo(request):
    name = request.match_info["name"]
    if name.rsplit("-", 1)[0] not in LOGOS_ERLAUBT and name not in LOGOS_ERLAUBT:
        raise web.HTTPNotFound()
    pfad = os.path.join(LOGO_ORDNER, name + ".png")
    if not os.path.isfile(pfad):
        raise web.HTTPNotFound()
    return web.FileResponse(pfad, headers={"Cache-Control": "no-cache"})


async def ohne_schraegstrich(request):
    raise web.HTTPMovedPermanently(PFAD)


async def start(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    ms = alle_meldungen(con)
    if ms:
        t = ms[0]
        held = (f'<a class="rg-held" href="{esc(t["url"])}"><div class="rg-held-text"><span class="rg-art">{esc(t["art"])} · {esc(t["quelle"])}</span>'
                f'<h2>{esc(t["titel"])}</h2><p>{esc(t["kurz"])}</p><span class="rg-datum">{datum(t["zeit"])}</span></div>'
                f'<div class="rg-held-bild"><img src="{PFAD}logo/regierung-kurz.png" alt=""></div></a>')
    else:
        held = (f'<div class="rg-held"><div class="rg-held-text"><span class="rg-art">Imperium Germanicum</span><h2>Willkommen bei der Reichsregierung</h2>'
                '<p>Hier informieren der Kronkanzler und die Reichsbehörden über ihre Arbeit: Pressemitteilungen, Beschlüsse, Reden und die Webauftritte der Ressorts.</p></div>'
                f'<div class="rg-held-bild"><img src="{PFAD}logo/regierung-kurz.png" alt=""></div></div>')
    schnell = (f'<div class="rg-schnell"><a href="{PFAD}aktuelles/?art=pressemitteilung">Pressemitteilungen</a>'
               f'<a href="{PFAD}aktuelles/?art=kabinett">Kabinettsbeschlüsse</a><a href="{PFAD}aktuelles/?art=rede">Reden</a>'
               f'<a href="{PFAD}aktuelles/?quelle=Generalkonsulat">Aus dem Generalkonsulat</a></div>')
    rest = ms[1:7]
    newsroom = (f'<section class="rg-abschnitt"><h2>Newsroom <a href="{PFAD}aktuelles/">Alle Meldungen</a></h2>{schnell}'
                + (f'<div class="rg-karten">{"".join(_karte(m) for m in rest)}</div>' if rest else '<p class="leer">Weitere Meldungen folgen.</p>') + "</section>")
    souv = await namen_mit_rollen(request, [ROLLE_SOUVERAEN])
    kanzler = await namen_mit_rollen(request, [amt.ROLLE_KANZLER])
    person = lambda n, amt_: (f'<div class="rg-person"><span class="avatar" aria-hidden="true">{esc(amt._initialen(n))}</span>'
                              f'<span><b>{esc(n)}</b><small>{esc(amt_)}</small></span></div>')
    personen = "".join(person(n, "Der Souverän – Imperator Rex") for n in souv) + "".join(person(n, "Der Kronkanzler") for n in kanzler)
    regierung = (f'<section class="rg-abschnitt"><h2>Die Reichsregierung im Überblick <a href="{PFAD}reichsregierung/">Zum Kabinett</a></h2>'
                 f'<div class="rg-karten">{personen or "<p class=leer>Keine Angaben.</p>"}</div></section>')
    alle, gruppen = ressorts()
    karten = "".join(_ressort_karte(b) for b in alle if b["schl"] in WEBAUFTRITTE or b["gruppe"] in ("kanzlei", "sicherheit", "verwaltung"))
    ressorts_html = f'<section class="rg-abschnitt"><h2>Die Ressorts <a href="{PFAD}ressorts/">Alle Ressorts</a></h2><div class="rg-karten">{karten}</div></section>'
    hinweise = ""
    for h in HINWEISE:
        try:
            hinweise += h(con)
        except Exception:
            pass
    return rahmen(request, k, "Startseite", "r-start", held + hinweise + newsroom + regierung + ressorts_html)


def _ressort_karte(b):
    eigen = b["schl"] in WEBAUFTRITTE
    bild = (f'<img class="rg-logo" src="{PFAD}logo/{b["schl"]}-kopf.png" alt="">' if b["schl"] in LOGOS_ERLAUBT
            else f'<span class="rg-ic">{ic("landmark")}</span>')
    return (f'<a class="rg-karte" href="{PFAD}ressorts/{esc(b["schl"])}/">{bild}<h3>{esc(b["name"])}</h3><p>{esc(b.get("lead", ""))}</p>'
            f'<span class="rg-mehr">{"Eigener Webauftritt" if eigen else "Steckbrief"} {ic("arrow-right")}</span></a>')


async def aktuelles(request):
    k = await anmeldung.konto(request)
    ms = alle_meldungen(request.app["db"])
    art, quelle = request.query.get("art", ""), request.query.get("quelle", "")
    if art in MELDUNGSARTEN:
        ms = [m for m in ms if m.get("schl") == art or m["art"] == MELDUNGSARTEN[art]]
    if quelle:
        ms = [m for m in ms if m["quelle"] == quelle]
    quellen = sorted({m["quelle"] for m in alle_meldungen(request.app["db"])})
    filt = ('<div class="rg-schnell">' + f'<a href="{PFAD}aktuelles/" class="{"" if art or quelle else "aktiv"}">Alle</a>'
            + "".join(f'<a href="?art={a}" class="{"aktiv" if a == art else ""}">{t}</a>' for a, t in MELDUNGSARTEN.items())
            + "".join(f'<a href="?quelle={esc(q)}" class="{"aktiv" if q == quelle else ""}">{esc(q)}</a>' for q in quellen if q != "Reichsregierung") + "</div>")
    inhalt = (f'<div class="rg-karten">{"".join(_karte(m) for m in ms)}</div>' if ms else '<p class="leer">Keine Meldungen.</p>')
    return rahmen(request, k, "Aktuelles", "r-aktuelles",
                  kopf("Aktuelles", "Pressemitteilungen, Kabinettsbeschlüsse und Reden der Reichsregierung sowie Meldungen der Ressorts.", "Newsroom") + filt + inhalt)


async def meldung(request):
    k = await anmeldung.konto(request)
    m = request.app["db"].execute("SELECT * FROM regierung_meldungen WHERE id=?", (request.match_info["id"],)).fetchone()
    if not m or (m["status"] != "veroeffentlicht" and not ist_redaktion(k)):
        raise web.HTTPNotFound(text="Meldung nicht gefunden.")
    art = MELDUNGSARTEN.get(m["art"], "Meldung")
    entwurf = '<div class="hinweis">Entwurf – noch nicht veröffentlicht.</div>' if m["status"] != "veroeffentlicht" else ""
    bearb = f'<p><a class="btn zweit" href="{PFAD}intern/{m["id"]}/">{ic("pencil")}Bearbeiten</a></p>' if ist_redaktion(k) else ""
    inhalt = (kopf(m["titel"], esc(m["kurz"]), art) + entwurf + f'<p class="rg-datum">{datum(m["veroeffentlicht"] or m["erstellt"], True)} · Reichsregierung</p>'
              f'<div class="rg-text">{absatz(m["text"])}</div>' + bearb)
    return rahmen(request, k, m["titel"], "r-aktuelles", inhalt, krumen=[("Aktuelles", PFAD + "aktuelles/"), (m["titel"], None)])


async def reichsregierung(request):
    k = await anmeldung.konto(request)
    alle, _ = ressorts()
    souv = await namen_mit_rollen(request, [ROLLE_SOUVERAEN])
    zeilen = []
    for b in alle:
        rollen = LEITUNG_ROLLEN.get(b["schl"])
        namen = await namen_mit_rollen(request, rollen) if rollen else []
        zeilen.append(f'<tr><td><a href="{PFAD}ressorts/{esc(b["schl"])}/">{esc(b["name"])}</a></td><td>{esc(b.get("leitung", ""))}</td>'
                      f'<td>{esc(", ".join(namen)) if namen else ("<span class=leerwert>unbesetzt</span>" if rollen else "–")}</td></tr>')
    inhalt = (kopf("Die Reichsregierung", "Der Souverän ernennt den Kronkanzler. Der Kronkanzler leitet die Reichsverwaltung und führt die Reichsbehörden; "
                   "ihre Leiterinnen und Leiter bilden das Kabinett.", "Staatsaufbau")
              + '<section class="rg-abschnitt"><h2>Der Souverän</h2><div class="rg-karten">'
              + ("".join(f'<div class="rg-person"><span class="avatar">{esc(amt._initialen(n))}</span><span><b>{esc(n)}</b><small>Imperator Rex</small></span></div>' for n in souv)
                 or '<p class="leer">–</p>') + '</div></section>'
              + '<section class="rg-abschnitt"><h2>Das Kabinett</h2><table class="rg-tab"><thead><tr><th>Ressort</th><th>Leitung</th><th>Amtsinhaber</th></tr></thead>'
              f'<tbody>{"".join(zeilen)}</tbody></table></section>')
    return rahmen(request, k, "Die Reichsregierung", "r-regierung", inhalt)


async def ressorts_liste(request):
    k = await anmeldung.konto(request)
    alle, gruppen = ressorts()
    teile = []
    for g, gname in gruppen.items():
        bs = [b for b in alle if b["gruppe"] == g]
        if bs:
            teile.append(f'<section class="rg-abschnitt"><h2>{esc(gname)}</h2><div class="rg-karten">{"".join(_ressort_karte(b) for b in bs)}</div></section>')
    return rahmen(request, k, "Die Ressorts", "r-ressorts",
                  kopf("Die Ressorts", f"{len(alle)} Behörden und Ämter bilden die Reichsverwaltung. Einige haben einen eigenen Webauftritt.", "Reichsverwaltung") + "".join(teile))


async def ressort(request):
    k = await anmeldung.konto(request)
    alle, gruppen = ressorts()
    b = next((x for x in alle if x["schl"] == request.match_info["schl"]), None)
    if not b:
        raise web.HTTPNotFound(text="Ressort nicht gefunden.")
    rollen = LEITUNG_ROLLEN.get(b["schl"])
    namen = await namen_mit_rollen(request, rollen) if rollen else []
    daten = [("Gliederung", gruppen.get(b["gruppe"], "")), ("Leitung", b.get("leitung", "–"))]
    if rollen:
        daten.append(("Amtsinhaber", ", ".join(namen) or "unbesetzt"))
    if b.get("gebaeude"):
        g = b["gebaeude"]
        daten.append(("Dienstsitz", g.get("name", "") + (", " + g["ort"] if g.get("ort") else ", Berlin")))
    if b.get("nachgeordnet"):
        daten.append(("Nachgeordnet", ", ".join(b["nachgeordnet"])))
    if b.get("zusammen"):
        daten.append(("Zusammenarbeit", ", ".join(b["zusammen"])))
    dl = '<dl class="rg-daten">' + "".join(f"<dt>{esc(a)}</dt><dd>{esc(w)}</dd>" for a, w in daten) + "</dl>"
    aufgaben = ("<h2>Aufgaben</h2><ul class='rg-text'>" + "".join(f"<li>{esc(a)}</li>" for a in b.get("aufgaben", [])) + "</ul>") if b.get("aufgaben") else ""
    if b["schl"] in WEBAUFTRITTE:
        knopf = f'<p><a class="btn" href="{WEBAUFTRITTE[b["schl"]]}">{ic("globe")}Offizieller Webauftritt: {esc(b["kurz"] if b.get("kurz") else b["name"])}</a></p>'
    else:
        knopf = f'<p><a class="btn zweit" href="{ressort_url(b)}">{ic("external-link")}Seite auf imperiumgermanicum.de</a></p>'
    bild = f'<img src="{PFAD}logo/{b["schl"]}-kopf.png" alt="" style="height:56px;width:auto;margin:0 0 14px">' if b["schl"] in LOGOS_ERLAUBT else ""
    return rahmen(request, k, b["name"], "r-ressorts", bild + kopf(b["name"], esc(b.get("lead", "")), "Ressort") + knopf + dl + aufgaben,
                  krumen=[("Die Ressorts", PFAD + "ressorts/"), (b.get("kurz") or b["name"], None)])


async def suche(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    q = (request.query.get("q") or "").strip()[:80]
    treffer = []
    if len(q) >= 2:
        ql = q.lower()
        treffer += [(m["art"] + " · " + m["quelle"], m["titel"], m["url"]) for m in alle_meldungen(con) if ql in (m["titel"] + " " + m["kurz"]).lower()]
        alle, _ = ressorts()
        treffer += [("Ressort", b["name"], f'{PFAD}ressorts/{b["schl"]}/') for b in alle if ql in (b["name"] + " " + b.get("lead", "")).lower()]
        for s in SUCHE:
            try:
                treffer += s(con, q)
            except Exception:
                pass
        gesehen, eindeutig = set(), []
        for t in treffer:
            if t[2] not in gesehen:
                gesehen.add(t[2])
                eindeutig.append(t)
        treffer = eindeutig
    form = (f'<form class="rg-form" action="{PFAD}suche/" style="grid-template-columns:1fr auto;align-items:end">'
            f'<label>Suchbegriff<input type="search" name="q" value="{esc(q)}" autofocus></label><button class="btn" type="submit">{ic("search")}Suchen</button></form>')
    if not q:
        erg = ""
    elif treffer:
        erg = f'<p>{len(treffer)} Treffer für „{esc(q)}“</p><ul class="rg-liste">' + "".join(
            f'<li><a href="{esc(u)}">{esc(t)}</a><span class="rg-art">{esc(a)}</span></li>' for a, t, u in treffer) + "</ul>"
    else:
        erg = f'<p class="leer">Keine Treffer für „{esc(q)}“.</p>'
    return rahmen(request, k, "Suche", "r-suche", kopf("Suche") + form + erg, q=q)


# ---------------------------------------------------------------- Redaktion

async def intern(request):
    k = await konto_oder_login(request)
    if not ist_redaktion(k):
        raise web.HTTPForbidden(text="Nur für die Redaktion der Reichsregierung (Kaiser, Kronkanzler).")
    ms = request.app["db"].execute("SELECT * FROM regierung_meldungen ORDER BY COALESCE(veroeffentlicht, erstellt) DESC").fetchall()
    tab = ('<table class="rg-tab"><thead><tr><th>Titel</th><th>Art</th><th>Stand</th><th>Datum</th></tr></thead><tbody>' + "".join(
        f'<tr><td><a href="{PFAD}intern/{m["id"]}/">{esc(m["titel"])}</a></td><td>{esc(MELDUNGSARTEN.get(m["art"], ""))}</td>'
        f'<td>{"<span class=\'status s-ok\'>Veröffentlicht</span>" if m["status"] == "veroeffentlicht" else "<span class=\'status s-neutral\'>Entwurf</span>"}</td>'
        f'<td>{datum(m["veroeffentlicht"] or m["erstellt"])}</td></tr>' for m in ms) + "</tbody></table>") if ms else '<p class="leer">Noch keine Meldungen.</p>'
    return rahmen(request, k, "Redaktion", "r-intern", kopf("Redaktion", "Pressemitteilungen, Kabinettsbeschlüsse und Reden der Reichsregierung.", "Intern")
                  + f'<p><a class="btn" href="{PFAD}intern/neu/">{ic("file-plus")}Neue Meldung</a></p>' + tab)


async def intern_meldung(request):
    k = await konto_oder_login(request)
    if not ist_redaktion(k):
        raise web.HTTPForbidden(text="Nur für die Redaktion der Reichsregierung.")
    i = request.match_info.get("id")
    m = request.app["db"].execute("SELECT * FROM regierung_meldungen WHERE id=?", (i,)).fetchone() if i else None
    if i and not m:
        raise web.HTTPNotFound()
    w = lambda f, d="": (m[f] if m else d)
    form = (f'<form class="rg-form" method="post" action="{PFAD}intern/{i + "/" if i else "neu/"}">{csrf_feld(request)}'
            f'<label>Titel<input name="titel" maxlength="160" required value="{esc(w("titel"))}"></label>'
            f'<label>Art<select name="art">{opt(MELDUNGSARTEN.items(), w("art", "pressemitteilung"))}</select></label>'
            f'<label>Kurztext (Teaser)<input name="kurz" maxlength="300" value="{esc(w("kurz"))}"></label>'
            f'<label>Text (Absätze mit Leerzeile trennen)<textarea name="text" style="min-height:300px" maxlength="20000">{esc(w("text"))}</textarea></label>'
            '<div class="rg-knoepfe"><button class="btn" name="aktion" value="veroeffentlichen" type="submit">Veröffentlichen</button>'
            '<button class="btn zweit" name="aktion" value="entwurf" type="submit">Als Entwurf speichern</button></div></form>')
    if m:
        form += (f'<form method="post" action="{PFAD}intern/{m["id"]}/loeschen" onsubmit="return confirm(\'Meldung löschen?\')">{csrf_feld(request)}'
                 f'<button class="btn gefahr" type="submit">{ic("trash-2")}Löschen</button></form>')
    titel = m["titel"] if m else "Neue Meldung"
    return rahmen(request, k, titel, "r-intern", kopf(titel, "", "Redaktion") + form, krumen=[("Redaktion", PFAD + "intern/"), (titel, None)])


async def intern_speichern(request):
    k, form = await post_pruefen(request, ist_redaktion)
    con = request.app["db"]
    i = request.match_info.get("id")
    m = con.execute("SELECT * FROM regierung_meldungen WHERE id=?", (i,)).fetchone() if i else None
    titel = (form.get("titel") or "").strip()[:160]
    if not titel:
        weiter(request.path, f="Titel fehlt.")
    art = form.get("art") if form.get("art") in MELDUNGSARTEN else "pressemitteilung"
    werte = (titel, art, (form.get("kurz") or "").strip()[:300], (form.get("text") or "").strip()[:20000])
    jetzt = int(time.time())
    if m:
        con.execute("UPDATE regierung_meldungen SET titel=?, art=?, kurz=?, text=? WHERE id=?", werte + (m["id"],))
        mid = m["id"]
    else:
        mid = con.execute("INSERT INTO regierung_meldungen (titel, art, kurz, text, autor_id, autor_name, erstellt) VALUES (?,?,?,?,?,?,?)",
                          werte + (k["id"], k["name"], jetzt)).lastrowid
    if form.get("aktion") == "veroeffentlichen":
        con.execute("UPDATE regierung_meldungen SET status='veroeffentlicht', veroeffentlicht=COALESCE(veroeffentlicht, ?) WHERE id=?", (jetzt, mid))
    else:
        con.execute("UPDATE regierung_meldungen SET status='entwurf', veroeffentlicht=NULL WHERE id=?", (mid,))
    con.commit()
    weiter(f"{PFAD}intern/{mid}/", "Gespeichert.")


async def intern_loeschen(request):
    k, _ = await post_pruefen(request, ist_redaktion)
    con = request.app["db"]
    con.execute("DELETE FROM regierung_meldungen WHERE id=?", (request.match_info["id"],))
    con.commit()
    weiter(f"{PFAD}intern/", "Gelöscht.")


def registrieren(app):
    einrichten(app["db"])
    r = app.router
    r.add_get("/regierung", ohne_schraegstrich)
    r.add_get(PFAD, start)
    r.add_get(PFAD + "logo/{name}.png", logo)
    r.add_get(PFAD + "aktuelles/", aktuelles)
    r.add_get(PFAD + "aktuelles/{id:\\d+}/", meldung)
    r.add_get(PFAD + "reichsregierung/", reichsregierung)
    r.add_get(PFAD + "ressorts/", ressorts_liste)
    r.add_get(PFAD + "ressorts/{schl}/", ressort)
    r.add_get(PFAD + "suche/", suche)
    r.add_get(PFAD + "intern/", intern)
    r.add_get(PFAD + "intern/neu/", intern_meldung)
    r.add_post(PFAD + "intern/neu/", intern_speichern)
    r.add_get(PFAD + "intern/{id:\\d+}/", intern_meldung)
    r.add_post(PFAD + "intern/{id:\\d+}/", intern_speichern)
    r.add_post(PFAD + "intern/{id:\\d+}/loeschen", intern_loeschen)
