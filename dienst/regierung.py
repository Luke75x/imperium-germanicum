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
import organigramme

esc = html.escape
PFAD = "/regierung/"
LOGO_ORDNER = os.path.join(config.HIER, "amt_logos")
LOGO_SCHLUESSEL = {"kanzlei": "kanzler"}
RUNDE_LOGOS = {"crownestates"}   # quadratische/runde Logos ohne Schriftzug daneben: im Kopf mit Namen, in Karten größer   # Ministerium → Logodatei, wenn der Name abweicht


def logo_von(schl):
    """Logoschlüssel eines Ministeriums, wenn es ein Amtslogo gibt (amt_logos/<schl>-kopf.png), sonst None."""
    n = LOGO_SCHLUESSEL.get(schl, schl)
    return n if os.path.isfile(os.path.join(LOGO_ORDNER, n + "-kopf.png")) else None
ROLLE_SOUVERAEN = "1522685953054081054"
MELDUNGSARTEN = {"pressemitteilung": "Pressemitteilung", "artikel": "Artikel", "rede": "Rede", "kabinett": "Kabinettsbeschluss"}
# Ressorts mit eigenem Webauftritt (Schlüssel aus reichsbehoerden.py → Pfad)
WEBAUFTRITTE = {"generalkonsulat": PFAD + "generalkonsulat/", "schatzamt": "/schatzamt/"}
# Leitungsrollen je Ressort (Namen im Kabinett); was fehlt, erscheint ohne Namen
# Reichsamt für die Kronstatthalterschaft (Reichsvertretung): geleitet vom Privatsekretär des Souveräns (= Kronkanzler), dort „Reichskronkommissar“;
# untersteht unmittelbar dem Souverän. Bekommt der Reichskronkommissar eine eigene Discord-Rolle, hier eintragen.
LEITUNG_ROLLEN = {"kanzlei": [amt.ROLLE_KANZLER], "generalkonsulat": ["1522702617833246822"], "kronstatthalterschaft": [amt.ROLLE_KANZLER]}
for _b in amt.BEHOERDEN:
    if _b["leitung"]:
        LEITUNG_ROLLEN.setdefault(_b["schl"], _b["leitung"])
LEITUNG_BILDER = os.path.join(config.HIER, "leitung_bilder")   # Porträts: <schl>.(png|webp|jpg) – souveraen, kanzlei, generalkonsulat, polizei …
BILD_ENDUNGEN = (".png", ".webp", ".jpg", ".jpeg")
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
.rg-held .rg-held-bild img{width:min(100%,210px);height:auto;background:#f7f8fa;padding:20px 24px;border-radius:18px;box-shadow:0 14px 34px -14px rgba(0,0,0,.55),inset 0 1px 0 #fff;box-sizing:content-box}
.rg-held .rg-knoepfe{margin-top:6px}
html:root .rg-held .btn{background:#fff;color:var(--kopf);border-color:#fff}
html:root .rg-held .btn.zweit{background:transparent;color:#fff;border-color:rgba(255,255,255,.45);box-shadow:none}

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
.rg-karte .rg-logo.rund{height:58px}
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
.rg-gruppe{font-size:13px;font-weight:650;letter-spacing:.06em;text-transform:uppercase;color:var(--grau);margin:22px 0 10px}
.rg-knoepfe .btn.zweit{color:var(--ink)}
.rg-leit{margin:46px 0}
html:root main .rg-leit h2.rg-leit-titel{border:0;padding:0;margin:0 0 26px;text-align:center;font-size:clamp(22px,2.6vw,30px);font-weight:500;letter-spacing:-.01em;
 text-transform:none;color:var(--ink);display:block}
.rg-leit-buehne{position:relative;display:grid;grid-template-columns:minmax(0,430px) minmax(0,1fr);align-items:end;min-height:300px}
.rg-leit-buehne::before{content:"";position:absolute;left:0;right:0;bottom:0;height:56%;background:rgba(22,23,26,.06);border-radius:var(--r);
 border:1px solid var(--glas-rand,var(--linie))}
.rg-leit-bild{position:relative;z-index:1;display:flex;justify-content:center;align-items:flex-end;line-height:0;padding:0 10px}
.rg-leit-bild img{max-height:470px;max-width:100%;width:auto;display:block;object-fit:contain;filter:drop-shadow(0 10px 18px rgba(16,24,40,.18))}
.rg-silhouette{width:72%;max-width:300px;height:auto;fill:#c9ced6}
.rg-leit-links{position:relative;z-index:1;display:grid;grid-template-columns:repeat(2,max-content);gap:18px 46px;align-content:center;align-self:end;
 min-height:56%;padding:34px clamp(18px,4vw,60px)}
.rg-leit-links a{display:inline-flex;gap:8px;align-items:center;color:var(--ink);text-decoration:none;font-weight:650;font-size:15.5px}
.rg-leit-links a .icon{color:var(--grau);transition:transform .2s}.rg-leit-links a:hover{color:var(--akzent)}.rg-leit-links a:hover .icon{transform:translateX(3px);color:var(--akzent)}
.rg-leit-paar-raster{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin:46px 0}
.rg-leit-paar{margin:0;display:flex;flex-direction:column}.rg-leit-paar .rg-leit-buehne{flex:1}
.rg-leit-paar .rg-leit-buehne{grid-template-columns:minmax(0,46%) minmax(0,1fr);min-height:260px}
.rg-leit-paar .rg-leit-bild img{max-height:360px}
.rg-leit-paar .rg-leit-links{grid-template-columns:max-content;gap:9px;padding:20px 20px}
@media(min-width:701px){.rg-leit-paar .rg-leit-links{min-height:74%}.rg-leit-paar .rg-leit-buehne::before{height:74%}}
html:root main .rg-leit-paar h2.rg-leit-titel{font-size:clamp(19px,1.9vw,24px);margin-bottom:18px}
@media(max-width:900px){.rg-leit-paar-raster{grid-template-columns:1fr;gap:40px}}
@media(max-width:700px){
 .rg-leit-buehne,.rg-leit-paar .rg-leit-buehne{grid-template-columns:1fr;min-height:0}
 .rg-leit-buehne::before{height:auto;top:42%}
 .rg-leit-bild img{max-height:300px}.rg-silhouette{width:55%}
 .rg-leit-links,.rg-leit-paar .rg-leit-links{grid-template-columns:1fr;gap:12px;padding:20px 22px 24px;min-height:0}
}
.rg-fuss{margin-top:48px;padding-top:16px;border-top:1px solid var(--linie);display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--grau)}
.rg-fuss a{color:var(--grau);text-decoration:none}.rg-fuss a:hover{color:var(--ink)}
@media(max-width:800px){.rg-fuss{margin-bottom:calc(var(--tab) + 28px)}}
.rg-anmelden{display:flex;align-items:center;gap:10px;padding:10px 10px 2px}
</style>"""


# ---------------------------------------------------------------- Rechte, Daten

def ist_redaktion(k):
    return bool(k) and bool(k["mitglied"]) and bereiche._alle(k)


def einrichten(con):
    os.makedirs(LEITUNG_BILDER, exist_ok=True)
    con.executescript(LEBENSLAUF_SCHEMA)
    _fz_einrichten(con)
    con.executescript(SCHEMA)
    if "ressort" not in [r[1] for r in con.execute("PRAGMA table_info(regierung_meldungen)")]:
        con.execute("ALTER TABLE regierung_meldungen ADD COLUMN ressort TEXT NOT NULL DEFAULT ''")
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
    url, anker = (url.split("#", 1) + [""])[:2]          # Meldung vor den Anker, sonst kommt sie nie an
    raise web.HTTPSeeOther(url + (("&" if "?" in url else "?") + zus if zus else "") + (f"#{anker}" if anker else ""))


async def konto_oder_login(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    return k


def ic_name(con, konto_id, discord_name):
    """Echter Name im Spiel (IC) aus der Bürgerakte; ohne Eintrag der Discord-Name."""
    try:
        r = con.execute("SELECT ic_name FROM amt_akten WHERE konto_id=?", (konto_id,)).fetchone()
    except Exception:
        r = None
    return (r[0] or "").strip() if r and (r[0] or "").strip() else discord_name


async def namen_mit_rollen(request, rollen):
    """IC-Namen aller Träger der Rollen (Bürgerakte), sonst Discord-Name."""
    return [n for _, n in await mitglieder_mit_rollen(request, rollen)]


def kopf(titel, lead="", art=""):
    return (f'<div class="rg-kopf"><h1>{esc(titel)}</h1>'
            f'{f"<p class=rg-lead>{lead}</p>" if lead else ""}</div>')


# ---------------------------------------------------------------- Rahmen (Website-Aufbau: Meta-Leiste, Kopf, Navigation, Fuß)

RAHMEN_CSS = """<style>
html:root body{padding-bottom:0}
.rw-wrap{width:100%;max-width:1180px;margin:0 auto;padding:0 clamp(16px,3vw,32px);box-sizing:border-box}
.rw-meta{background:var(--kopf);color:rgba(255,255,255,.78);font-size:13px}
.rw-meta .rw-wrap{display:flex;align-items:center;gap:16px;min-height:38px}
.rw-meta a,.rw-meta button{color:rgba(255,255,255,.82);text-decoration:none;background:none;border:0;font:inherit;cursor:pointer;padding:0;display:inline-flex;gap:6px;align-items:center}
.rw-meta a:hover,.rw-meta button:hover{color:#fff}.rw-meta .icon{width:15px;height:15px}
.rw-meta .rw-raum{flex:1}.rw-meta form{margin:0;display:inline}
.rw-meta .rw-ooc{background:#f2c94c;color:#1b1b1b;border-radius:999px;padding:1px 9px;font-weight:700;font-size:11px;letter-spacing:.06em}
.rw-kopf{background:var(--glas-dicht,rgba(255,255,255,.86));-webkit-backdrop-filter:var(--glas-blur,blur(14px));backdrop-filter:var(--glas-blur,blur(14px));
 border-bottom:1px solid var(--glas-linie,var(--linie))}
.rw-kopf .rw-wrap{display:flex;align-items:center;gap:18px;min-height:92px}
.rw-logo{line-height:0;flex:none}.rw-logo img{height:58px;width:auto;max-width:min(62vw,340px);object-fit:contain;object-position:left}
.rw-name{display:flex;align-items:center;gap:12px;text-decoration:none;color:var(--ink)}.rw-name img{height:58px;width:auto}
.rw-name b{font-size:19px;line-height:1.2;font-weight:600;max-width:340px}
.rw-rund img{height:72px;width:72px;border-radius:50%}
.rw-kopf .rw-raum{flex:1}
.rw-suche{display:flex;align-items:center;position:relative;margin:0}.rw-suche .icon{position:absolute;left:12px;color:#8b8f96;pointer-events:none}
.rw-suche input{width:260px;border:1px solid var(--linie);border-radius:999px;padding:9px 14px 9px 38px;font:inherit;font-size:14px;background:rgba(255,255,255,.7)}
.rw-menue{all:unset;cursor:pointer;width:44px;height:44px;border-radius:50%;place-items:center;display:none}
.rw-nav{position:sticky;top:0;z-index:20;background:var(--glas-kopf,rgba(255,255,255,.8));-webkit-backdrop-filter:var(--glas-blur,blur(14px));backdrop-filter:var(--glas-blur,blur(14px));
 border-bottom:1px solid var(--glas-linie,var(--linie));box-shadow:0 6px 18px -14px rgba(16,24,40,.25)}
.rw-nav .rw-wrap{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}
.rw-nav a{padding:14px 14px 12px;color:#3a3e45;text-decoration:none;font-weight:500;font-size:15px;white-space:nowrap;border-bottom:3px solid transparent}
.rw-nav a:hover{color:var(--ink)}.rw-nav a.aktiv{color:var(--ink);border-bottom-color:var(--akzent);font-weight:650}
.rw-unter{margin:18px 0 0}
.rw-unter .rw-wrap{display:flex}
.rw-unter nav{display:inline-flex;gap:4px;padding:4px;background:rgba(22,23,26,.05);border-radius:999px;max-width:100%;overflow-x:auto;scrollbar-width:none}
.rw-unter a{padding:7px 15px;border-radius:999px;color:var(--grau);text-decoration:none;white-space:nowrap;font-size:14px}
.rw-unter a:hover{background:rgba(255,255,255,.6);color:var(--ink)}
.rw-unter a.aktiv{background:#fff;color:var(--ink);font-weight:600;box-shadow:0 2px 8px rgba(16,24,40,.12),inset 0 1px 0 #fff}
.rw-krumen{margin-top:16px;font-size:13px;color:var(--grau);display:flex;flex-wrap:wrap;gap:6px}
.rw-krumen a{color:var(--grau);text-decoration:none}.rw-krumen a:hover{color:var(--ink)}.rw-krumen span[aria-current]{color:var(--ink)}
main.rw-main{max-width:1180px;margin:0 auto;padding:22px clamp(16px,3vw,32px) 56px;box-sizing:border-box;animation:none}
.rw-fuss{background:var(--kopf);color:rgba(255,255,255,.72);font-size:14px;margin-top:20px}
.rw-fuss .rw-spalten{display:grid;grid-template-columns:1.2fr 2fr 1fr;gap:32px;padding-top:40px;padding-bottom:28px}
.rw-fuss h3{color:#fff;font-size:12px;letter-spacing:.1em;text-transform:uppercase;margin:0 0 12px;font-weight:650}
.rw-fuss ul{list-style:none;margin:0;padding:0}.rw-fuss li{padding:3px 0}
.rw-fuss .rw-min{columns:2;column-gap:24px}
.rw-fuss a{color:rgba(255,255,255,.78);text-decoration:none}.rw-fuss a:hover{color:#fff}
.rw-fuss img{height:46px;width:auto;filter:brightness(0) invert(1);opacity:.92;margin-bottom:10px}
.rw-fuss .rw-unten{border-top:1px solid rgba(255,255,255,.14);padding-top:14px;padding-bottom:18px;display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12.5px}
@media(max-width:860px){
 .rw-kopf .rw-wrap{min-height:70px;gap:10px}.rw-logo img,.rw-name img{height:44px}.rw-name b{font-size:16px}
 .rw-suche{display:none}.rw-menue{display:grid}
 .rw-kopf.offen .rw-suche{display:flex;position:absolute;left:12px;right:12px;top:calc(100% + 6px);z-index:30}.rw-kopf{position:relative}
 .rw-kopf.offen .rw-suche input{width:100%;font-size:16px;box-shadow:0 10px 30px -10px rgba(16,24,40,.4);background:#fff}
 .rw-fuss .rw-spalten{grid-template-columns:1fr}.rw-fuss .rw-min{columns:1}
 .rw-meta .rw-weg{display:none}
}
</style>"""

MODAL_CSS = """<style>
dialog.rw-modal{border:1px solid var(--glas-rand,var(--linie));border-radius:22px;padding:0;width:min(640px,calc(100vw - 24px));max-height:calc(100vh - 40px);
 background:var(--glas-sheet,#fff);-webkit-backdrop-filter:var(--glas-blur,none);backdrop-filter:var(--glas-blur,none);box-shadow:0 30px 80px -20px rgba(16,24,40,.45);color:var(--ink)}
dialog.rw-modal::backdrop{background:rgba(15,17,21,.32);-webkit-backdrop-filter:blur(5px);backdrop-filter:blur(5px)}
dialog.rw-modal[open]{animation:rw-auf .28s cubic-bezier(.2,.9,.3,1.2) both}
@keyframes rw-auf{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}
.rw-modal-kopf{display:flex;align-items:center;gap:12px;padding:16px 18px 12px 22px;border-bottom:1px solid var(--glas-linie,var(--linie))}
.rw-modal-kopf h2{margin:0;padding:0;border:0;font-size:18px;flex:1;text-transform:none;letter-spacing:0;color:var(--ink)}
.rw-modal-inhalt{padding:18px 22px 22px;overflow:auto;max-height:calc(100vh - 140px)}
.rw-modal-inhalt .rg-form,.rw-modal-inhalt .gk-form{margin:0}
@media(max-width:640px){dialog.rw-modal{margin:auto auto 0;width:100vw;max-width:100vw;border-radius:22px 22px 0 0;max-height:92vh}}
@media(prefers-reduced-motion:reduce){dialog.rw-modal[open]{animation:none}}
</style>"""


def modal(mid, titel, inhalt):
    """Dialogfenster (statt Aufklappen). Öffnen mit modal_knopf(mid, …); schließt per ×, Esc oder Klick daneben."""
    return (f'<dialog class="rw-modal" id="{esc(mid)}" aria-labelledby="{esc(mid)}-t"><div class="rw-modal-kopf"><h2 id="{esc(mid)}-t">{esc(titel)}</h2>'
            f'<button class="knopf-rund" type="button" data-modal-zu aria-label="Schließen">{ic("x")}</button></div>'
            f'<div class="rw-modal-inhalt">{inhalt}</div></dialog>')


def modal_knopf(mid, text, symbol="pencil", klasse="btn zweit"):
    return f'<button type="button" class="{klasse}" data-modal-auf="{esc(mid)}">{ic(symbol)}{esc(text)}</button>'


RAHMEN_JS = """<script>(function(){
document.addEventListener('click',function(e){var a=e.target.closest('[data-modal-auf]');if(a){var d=document.getElementById(a.dataset.modalAuf);
if(d&&d.showModal){d.showModal();var f=d.querySelector('input:not([type=hidden]),textarea,select');if(f)f.focus()}return}
var z=e.target.closest('[data-modal-zu]');if(z){z.closest('dialog').close();return}
if(e.target.tagName==='DIALOG'&&e.target.classList.contains('rw-modal')){var r=e.target.getBoundingClientRect();
if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close()}});
var mq=/[?&]modal=([a-z-]+)/.exec(location.search);if(mq){var md=document.getElementById(mq[1]);if(md&&md.showModal)md.showModal()}
if(/[?&]f=/.test(location.search)){var o=document.querySelector('dialog.rw-modal[data-bei-fehler]');if(o&&o.showModal)o.showModal()}var b=document.querySelector('.rw-menue'),k=document.querySelector('.rw-kopf');if(b&&k)b.addEventListener('click',function(){
k.classList.toggle('offen');var i=k.querySelector('.rw-suche input');if(i&&k.classList.contains('offen'))i.focus()});
var a=document.querySelector('.rw-nav a.aktiv');if(a&&a.scrollIntoView)a.scrollIntoView({block:'nearest',inline:'center'});
addEventListener('pageshow',function(e){if(e.persisted)location.reload()});
/* Selbstheilung: alte, im Browser gespeicherte 301 von /regierung/ (erste Fassung) einmalig am Cache vorbei überschreiben */
try{if(!localStorage.getItem('rg-heil-1')){fetch('/regierung/',{cache:'reload',credentials:'same-origin'}).then(function(r){if(!r.redirected&&r.ok){fetch('/regierung',{cache:'reload',credentials:'same-origin'});localStorage.setItem('rg-heil-1','1');var n=performance.getEntriesByType?performance.getEntriesByType('navigation')[0]:null;if(n&&n.redirectCount>0&&location.pathname==='/regierung/generalkonsulat/'&&!location.search&&!/generalkonsulat/.test(document.referrer))location.replace('/regierung/')}})}}catch(e){}})()</script>"""


def _nav_regierung(k):
    nav = [("Startseite", "", [("r-start", "Startseite", "")]), ("Regierungsfahrzeuge", "fahrzeuge/", [("r-fahrzeuge", "Regierungsfahrzeuge", "fahrzeuge/")]),
           ("Aktuelles", "aktuelles/", [("r-aktuelles", "Aktuelles", "aktuelles/")]),
           ("Die Reichsregierung", "reichsregierung/", [("r-regierung", "Die Reichsregierung", "reichsregierung/")]),
           ("Organigramm", "organigramm/", [("r-organigramm", "Organigramm", "organigramm/")]),
           ("Ministerien", "ministerien/", [("r-ministerien", "Ministerien", "ministerien/")])]
    if ist_redaktion(k):
        nav.append(("Redaktion", "intern/", [("r-intern", "Redaktion", "intern/")]))
    return nav


def portal_regierung(k):
    return {"basis": PFAD, "logo": "regierung", "name": "Die Reichsregierung", "start": "Reichsregierung", "nav": _nav_regierung(k)}


def rahmen(request, k, titel, aktiv, inhalt, portal=None, krumen=None, q="", status=200, cache="no-store"):
    """Ganze Seite. portal: {basis, logo (Logoschlüssel oder None), name, start, nav: [(Text, URL, [(Schlüssel, Text, URL)])], suche_url};
    ohne portal → Startseite der Reichsregierung. Unterpunkte (zweite Ebene) erscheinen, wenn der aktive Hauptpunkt mehr als einen hat."""
    p = portal or portal_regierung(k)
    basis = p["basis"]
    ziel = lambda u: u if u.startswith("/") else basis + u
    nav_html, unter = "", ""
    for text, url, kinder in p["nav"]:
        an = any(s == aktiv for s, _, _ in kinder)
        nav_html += f'<a href="{ziel(url)}" class="{"aktiv" if an else ""}"{" aria-current=page" if an else ""}>{esc(text)}</a>'
        if an and len(kinder) > 1:
            unter = ('<div class="rw-unter"><div class="rw-wrap"><nav aria-label="Unterbereich">' + "".join(
                f'<a href="{ziel(u)}" class="{"aktiv" if s == aktiv else ""}">{esc(t)}</a>' for s, t, u in kinder) + "</nav></div></div>")
    unterseite = basis != PFAD
    kr = ([("Die Reichsregierung", PFAD)] if unterseite else []) + [(p["start"], basis)] + list(
        krumen if krumen is not None else ([] if aktiv.endswith("start") else [(titel, None)]))
    krumen_html = "" if (aktiv.endswith("start") and not krumen and not unterseite) else (
        '<div class="rw-wrap"><nav class="rw-krumen" aria-label="Pfad">' + " › ".join(
            f'<a href="{esc(u)}">{esc(t)}</a>' if u else f'<span aria-current="page">{esc(t)}</span>' for t, u in kr) + "</nav></div>")
    if p.get("logo") and p["logo"] in RUNDE_LOGOS:
        marke = f'<a class="rw-name rw-rund" href="{basis}"><img src="{PFAD}logo/{p["logo"]}-kopf.png" alt=""><b>{esc(p["name"])}</b></a>'
    elif p.get("logo"):
        marke = f'<a class="rw-logo" href="{basis}" title="{esc(p["name"])}"><img src="{PFAD}logo/{p["logo"]}-kopf.png" alt="{esc(p["name"])}"></a>'
    else:
        marke = f'<a class="rw-name" href="{basis}"><img src="{PFAD}logo/regierung-kurz.png" alt=""><b>{esc(p["name"])}</b></a>'
    such_url = p.get("suche_url", PFAD + "suche/")
    if k:
        konto = (f'<span class="rw-weg">{esc(k["name"])}</span><form method="post" action="/abmelden/"><input type="hidden" name="csrf" value="{esc(request.get("csrf", ""))}">'
                 f'<input type="hidden" name="weiter" value="{basis}"><button type="submit">{ic("log-out")}Abmelden</button></form>')
    else:
        konto = f'<a href="/anmelden/?weiter={esc(request.path_qs)}">{ic("log-in")}Anmelden</a>'
    ooc = '<span class="rw-ooc" title="Zugriff als Serveradministrator – rein OOC">OOC</span>' if k and amt.ist_ooc_admin(k) else ""
    links = (f'<a href="{PFAD}">{ic("arrow-left")}Die Reichsregierung</a>' if unterseite else '<span class="rw-weg">Imperium Germanicum</span>')
    meta = (f'<div class="rw-meta"><div class="rw-wrap">{links}<span class="rw-raum"></span>{ooc}'
            f'<a class="rw-weg" href="/">imperiumgermanicum.de</a>{konto}</div></div>')
    kopf_html = (f'<header class="rw-kopf"><div class="rw-wrap">{marke}<span class="rw-raum"></span>'
                 f'<form class="rw-suche" action="{such_url}" role="search">{ic("search")}<input type="search" name="q" value="{esc(q)}" placeholder="Suchen …" aria-label="Suchen"></form>'
                 f'<button class="rw-menue" type="button" aria-label="Suche öffnen">{ic("search")}</button></div></header>')
    nav = f'<nav class="rw-nav" aria-label="Hauptnavigation"><div class="rw-wrap">{nav_html}</div></nav>'
    alle, _ = ressorts()
    minis = "".join(f'<li><a href="{ministerium_url(b)}">{esc(b.get("kurz") or b["name"])}</a></li>' for b in alle)
    fuss = (f'<footer class="rw-fuss"><div class="rw-wrap rw-spalten"><div><img src="{PFAD}logo/regierung-kopf.png" alt="Die Reichsregierung">'
            '<p style="margin:0">Der Kronkanzler und die Reichsbehörden des Imperium Germanicum.</p></div>'
            f'<div><h3>Ministerien</h3><ul class="rw-min">{minis}</ul></div>'
            f'<div><h3>Service</h3><ul><li><a href="{PFAD}aktuelles/">Aktuelles</a></li><li><a href="{PFAD}reichsregierung/">Die Reichsregierung</a></li>'
            f'<li><a href="{PFAD}suche/">Suche</a></li><li><a href="/">imperiumgermanicum.de</a></li><li><a href="/kontakt/">Kontakt</a></li></ul></div></div>'
            '<div class="rw-wrap rw-unten"><span>© Imperium Germanicum – Die Reichsregierung</span><a href="/impressum/">Impressum</a>'
            '<a href="/datenschutz/">Datenschutz</a></div></footer>')
    m, f = request.query.get("m"), request.query.get("f")
    note = (f'<div class="rg-ok">{esc(m)}</div>' if m else "") + (f'<div class="rg-ok fehler">{esc(f)}</div>' if f else "")
    import rp_glas
    import profil_sa
    glas = rp_glas.CSS if rp_glas.GLAS else ""
    if k:
        glas += profil_sa.darstellung_css(request.app["db"], k)
    seite = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#1f2f45"><title>{esc(titel)} – {esc(p["name"])}</title><link rel="icon" type="image/png" sizes="256x256" href="{PFAD}logo/regierungsicon.png"><link rel="apple-touch-icon" href="{PFAD}logo/regierungsapple.png"><style>{amt.CSS}</style>{glas}{CSS}{RAHMEN_CSS}{MODAL_CSS}</head>
<body>{meta}{kopf_html}{nav}{unter}{krumen_html}
<main class="rw-main" id="inhalt">{note}{inhalt}</main>{fuss}{RAHMEN_JS}</body></html>"""
    return web.Response(status=status, text=seite, content_type="text/html", headers={"Cache-Control": cache})


# ---------------------------------------------------------------- Leitung: Porträt-Block (nach dem Vorbild „Außenminister …“ des Auswärtigen Amts)

SILHOUETTE = ('<svg class="rg-silhouette" viewBox="0 0 300 380" aria-hidden="true"><circle cx="150" cy="118" r="70"/>'
              '<path d="M18 380c0-92 58-152 132-152s132 60 132 152Z"/></svg>')


def bild_datei(name):
    for e in BILD_ENDUNGEN:
        p = os.path.join(LEITUNG_BILDER, name + e)
        if os.path.isfile(p):
            return p
    return None


def bild_url(name):
    p = bild_datei(name)
    return f"{PFAD}bild/{name}?v={int(os.path.getmtime(p))}" if p else None


async def bild(request):
    name = request.match_info["name"]
    p = bild_datei(name) if re.fullmatch(r"[a-z]+", name) else None
    if not p:
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "no-cache"})


def ohne_artikel(t):
    return re.sub(r"^(Der|Die|Das)\s+", "", t or "")


def leitung_titel(amt_, namen, nur_name=False):
    """„Generalkonsul Max Mustermann“ bzw. „Generalkonsul – zurzeit unbesetzt“. Trägt der Discord-Name die Amtsbezeichnung schon
    („Kronkanzler Falkenheim“) oder ist nur_name gesetzt (Souverän: „SKKM Alexander IX.“), steht nur der Name da."""
    a = ohne_artikel(amt_)
    if not namen:
        return f"{a} – zurzeit unbesetzt"
    erstes = a.split()[0].lower() if a else ""
    if nur_name or all(erstes and erstes in n.lower() for n in namen):
        return ", ".join(namen)
    return f"{a} {', '.join(namen)}"


def leitung_block(titel, bildname, links, paar=False):
    """Überschrift, Porträt (freigestellt, ragt über ein graues Band) und Links im Band. links = [(Text, URL)]."""
    url = bild_url(bildname)
    bild_html = f'<img src="{url}" alt="">' if url else SILHOUETTE
    li = "".join(f'<a href="{esc(u)}">{esc(t)}{ic("arrow-right")}</a>' for t, u in links)
    return (f'<section class="rg-leit{" rg-leit-paar" if paar else ""}"><h2 class="rg-leit-titel">{esc(titel)}</h2>'
            f'<div class="rg-leit-buehne"><div class="rg-leit-bild">{bild_html}</div><nav class="rg-leit-links">{li}</nav></div></section>')


# ---------------------------------------------------------------- Meldungen (eigene + Ministerien mit eigenem Webauftritt)

def _eigene(con):
    alle, _ = ressorts()
    namen = {b["schl"]: b.get("kurz") or b["name"] for b in alle}
    out = []
    for m in con.execute("SELECT * FROM regierung_meldungen WHERE status='veroeffentlicht' ORDER BY veroeffentlicht DESC LIMIT 300"):
        r = m["ressort"] or ""
        out.append({"titel": m["titel"], "kurz": m["kurz"], "art": MELDUNGSARTEN.get(m["art"], "Meldung"), "zeit": m["veroeffentlicht"],
                    "url": f"{PFAD}{r}/meldungen/{m['id']}/" if r else f"{PFAD}aktuelles/{m['id']}/", "quelle": namen.get(r, "Reichsregierung") if r else "Reichsregierung",
                    "schl": m["art"], "ressort": r})
    return out


def alle_meldungen(con):
    out = _eigene(con)
    for q in QUELLEN:
        try:
            out += q(con)
        except Exception:
            pass
    return sorted(out, key=lambda x: x["zeit"] or 0, reverse=True)


def _karte(m):
    return (f'<a class="rg-karte" href="{esc(m["url"])}"><h3>{esc(m["titel"])}</h3>'
            f'<p>{esc(m["kurz"])}</p><span class="rg-datum">{datum(m["zeit"])}</span></a>')


# ---------------------------------------------------------------- Seiten der Reichsregierung

async def logo(request):
    name = request.match_info["name"]
    if not re.fullmatch(r"[a-z]+(-kopf|-kurz)?", name):
        raise web.HTTPNotFound()
    pfad = os.path.join(LOGO_ORDNER, name + ".png")
    if not os.path.isfile(pfad):
        raise web.HTTPNotFound()
    return web.FileResponse(pfad, headers={"Cache-Control": "no-cache"})


def umleiten(url):
    """Nur vorübergehende, nie gespeicherte Weiterleitungen: eine 301 ohne Cache-Regel behalten Browser für immer
    (so blieb /regierung/ → /regierung/generalkonsulat/ aus der ersten Fassung hängen)."""
    raise web.HTTPFound(url, headers={"Cache-Control": "no-store"})


async def ohne_schraegstrich(request):
    umleiten(PFAD)


def ministerium_url(b):
    return f'{PFAD}{b["schl"]}/'


def _ministerium_karte(b, klein=False):
    lg = logo_von(b["schl"])
    bild = (f'<img class="rg-logo{" rund" if lg in RUNDE_LOGOS else ""}" src="{PFAD}logo/{lg}-kopf.png" alt="">' if lg
            else f'<span class="rg-ic">{ic("landmark")}</span>')
    lead = "" if klein else f'<p>{esc(b.get("lead", ""))}</p>'
    return (f'<a class="rg-karte" href="{ministerium_url(b)}">{bild}<h3>{esc(b["name"])}</h3>{lead}'
            f'<span class="rg-mehr">Zum Ministerium {ic("arrow-right")}</span></a>')


async def start(request):
    """Startseite: Einstieg in alle Ministerien, dazu Aktuelles und die Regierung."""
    k = await anmeldung.konto(request)
    con = request.app["db"]
    alle, gruppen = ressorts()
    held = ('<div class="rg-held"><div class="rg-held-text"><h2>Die Reichsregierung</h2>'
            '<p>Der Kronkanzler und die Reichsbehörden: Hier finden Sie alle Ministerien des Reiches mit ihren eigenen Seiten, '
            'dazu Pressemitteilungen, Kabinettsbeschlüsse und Reden.</p>'
            f'<div class="rg-knoepfe"><a class="btn" href="#ministerien">{ic("landmark")}Alle Ministerien</a>'
            f'<a class="btn zweit" href="{PFAD}fahrzeuge/">{ic("flag")}Regierungsfahrzeuge</a>'
            f'<a class="btn zweit" href="{PFAD}aktuelles/">{ic("newspaper")}Aktuelles</a></div></div>'
            f'<div class="rg-held-bild"><img src="{PFAD}logo/kanzler-kurz.png" alt=""></div></div>')
    hinweise = ""
    for h in HINWEISE:
        try:
            hinweise += h(con)
        except Exception:
            pass
    teile = []
    for g, gname in gruppen.items():
        bs = [b for b in alle if b["gruppe"] == g]
        if bs:
            teile.append(f'<h3 class="rg-gruppe">{esc(gname)}</h3><div class="rg-karten">{"".join(_ministerium_karte(b) for b in bs)}</div>')
    ministerien = f'<section class="rg-abschnitt" id="ministerien"><h2>Die Ministerien</h2>{"".join(teile)}</section>'
    ms = alle_meldungen(con)[:6]
    newsroom = (f'<section class="rg-abschnitt"><h2>Aktuelles <a href="{PFAD}aktuelles/">Alle Meldungen</a></h2>'
                + (f'<div class="rg-karten">{"".join(_karte(m) for m in ms)}</div>' if ms else '<p class="leer">Noch keine Meldungen.</p>') + "</section>")
    souv = await namen_mit_rollen(request, [ROLLE_SOUVERAEN])
    kanzler = await namen_mit_rollen(request, [amt.ROLLE_KANZLER])
    regierung = ('<div class="rg-leit-paar-raster">'
                 + leitung_block(leitung_titel("Der Souverän", souv), "souveraen",
                                 [("Der Souverän", "/der-souveraen/")], paar=True)
                 + leitung_block(leitung_titel("Kronkanzler", kanzler), "kanzlei",
                                 [("Das Kronkanzleramt", PFAD + "kanzlei/"), ("Die Reichsregierung", PFAD + "reichsregierung/"),
                                  ("Kabinettsbeschlüsse", PFAD + "aktuelles/?art=kabinett"), ("Pressemitteilungen", PFAD + "aktuelles/?art=pressemitteilung"),
                                  ("Reden", PFAD + "aktuelles/?art=rede")], paar=True)
                 + "</div>")
    return rahmen(request, k, "Startseite", "r-start", held + hinweise + regierung + ministerien + newsroom, cache="private, no-cache")


def _person(n, amt_):
    return (f'<div class="rg-person"><span class="avatar" aria-hidden="true">{esc(amt._initialen(n))}</span>'
            f'<span><b>{esc(n)}</b><small>{esc(amt_)}</small></span></div>')


async def ministerien(request):
    k = await anmeldung.konto(request)
    alle, gruppen = ressorts()
    teile = []
    for g, gname in gruppen.items():
        bs = [b for b in alle if b["gruppe"] == g]
        if bs:
            teile.append(f'<section class="rg-abschnitt"><h2>{esc(gname)}</h2><div class="rg-karten">{"".join(_ministerium_karte(b) for b in bs)}</div></section>')
    return rahmen(request, k, "Ministerien", "r-ministerien",
                  kopf("Die Ministerien", f"{len(alle)} Behörden und Ämter bilden die Reichsverwaltung. Jedes Ministerium hat hier seine eigene Seite.", "Reichsverwaltung") + "".join(teile))


async def aktuelles(request):
    k = await anmeldung.konto(request)
    alle_m = alle_meldungen(request.app["db"])
    art, quelle = request.query.get("art", ""), request.query.get("quelle", "")
    ms = alle_m
    if art in MELDUNGSARTEN:
        ms = [m for m in ms if m.get("schl") == art or m["art"] == MELDUNGSARTEN[art]]
    if quelle:
        ms = [m for m in ms if m["quelle"] == quelle]
    quellen = sorted({m["quelle"] for m in alle_m})
    filt = ('<div class="rg-schnell">' + f'<a href="{PFAD}aktuelles/" class="{"" if art or quelle else "aktiv"}">Alle</a>'
            + "".join(f'<a href="?art={a}" class="{"aktiv" if a == art else ""}">{t}</a>' for a, t in MELDUNGSARTEN.items())
            + "".join(f'<a href="?quelle={esc(q)}" class="{"aktiv" if q == quelle else ""}">{esc(q)}</a>' for q in quellen if q != "Reichsregierung") + "</div>")
    inhalt = (f'<div class="rg-karten">{"".join(_karte(m) for m in ms)}</div>' if ms else '<p class="leer">Keine Meldungen.</p>')
    return rahmen(request, k, "Aktuelles", "r-aktuelles",
                  kopf("Aktuelles", "Pressemitteilungen, Kabinettsbeschlüsse und Reden der Reichsregierung und aller Ministerien.", "Newsroom") + filt + inhalt)


def _meldung_html(m, k, bearb_url):
    art = MELDUNGSARTEN.get(m["art"], "Meldung")
    entwurf = '<div class="hinweis">Entwurf – noch nicht veröffentlicht.</div>' if m["status"] != "veroeffentlicht" else ""
    bearb = f'<p><a class="btn zweit" href="{bearb_url}">{ic("pencil")}Bearbeiten</a></p>' if bearb_url else ""
    return (kopf(m["titel"], esc(m["kurz"]), art) + entwurf + f'<p class="rg-datum">{datum(m["veroeffentlicht"] or m["erstellt"], True)}</p>'
            f'<div class="rg-text">{absatz(m["text"])}</div>' + bearb)


async def meldung(request):
    k = await anmeldung.konto(request)
    m = request.app["db"].execute("SELECT * FROM regierung_meldungen WHERE id=?", (request.match_info["id"],)).fetchone()
    if not m or (m["status"] != "veroeffentlicht" and not ist_redaktion(k)):
        raise web.HTTPNotFound(text="Meldung nicht gefunden.")
    if m["ressort"]:
        umleiten(f'{PFAD}{m["ressort"]}/meldungen/{m["id"]}/')
    return rahmen(request, k, m["titel"], "r-aktuelles", _meldung_html(m, k, f'{PFAD}intern/{m["id"]}/' if ist_redaktion(k) else ""),
                  krumen=[("Aktuelles", PFAD + "aktuelles/"), (m["titel"], None)])


# ---------------------------------------------------------------- Organigramm der Reichsverwaltung (wiedergegeben aus organigramme.py, kein Absprung zur Hauptseite)

ORG_CSS = """<style>
.rgo-tab-rahmen{overflow-x:auto;margin:6px 0 26px}
.rgo-tab{width:100%;border-collapse:collapse;font-size:15px;min-width:560px}
.rgo-tab th,.rgo-tab td{text-align:left;vertical-align:top;padding:11px 14px 11px 0;border:0;border-bottom:1px solid var(--linie)}
.rgo-tab thead th{font-size:13px;color:var(--grau);font-weight:600;border-bottom:1px solid var(--ink)}
.rgo-tab tbody th{font-weight:650;white-space:nowrap}
</style>"""


async def organigramm(request):
    """Organigramm der Reichsverwaltung, hier selbst wiedergegeben (interaktiv, Daten aus organigramme.py), dazu der Aufbau in Säulen."""
    k = await anmeldung.konto(request)
    alle, _ = ressorts()
    vt = next((b for b in alle if b["gruppe"] == "vertretung"), None)
    saeulen = [
        ("Der Souverän", "Seine Majestät", "Steht an der Spitze des Reiches. Ihm unterstehen unmittelbar das Kronkanzleramt und das Reichsamt für die Kronstatthalterschaft."),
        ("Die Kanzlei", "Der Kronkanzler", "Bindeglied zwischen dem Souverän und der Verwaltung; Kronbesitz und Schatzkammer seiner Majestät."),
        ("Die Reichsbehörden", "Generaldirektoren, Staatssekretäre und der Generalkonsul", "Reichsweite Aufgaben in Sicherheit, Ordnung und Verwaltung sowie der auswärtige Dienst. Sie unterstehen dem Kronkanzler."),
    ]
    if vt:
        saeulen.append(("Die Reichsvertretung", f'{vt.get("leitung", "")}; Vizekönige, Generalgouverneure, Gouverneure, Magistrate und Bürgermeister',
                        f'{vt["name"]}: Vertretung des Souveräns in Teilstaaten und Städten ohne eigenen Regenten. Untersteht unmittelbar dem Souverän.'))
    tab = ('<div class="rgo-tab-rahmen"><table class="rgo-tab"><thead><tr><th>Säule</th><th>Leitung</th><th>Aufgabe</th></tr></thead><tbody>'
           + "".join(f'<tr><th scope="row">{esc(n)}</th><td>{esc(l)}</td><td>{esc(t)}</td></tr>' for n, l, t in saeulen) + "</tbody></table></div>")
    inhalt = (ORG_CSS + kopf("Organigramm der Reichsverwaltung",
                             "Alle Ämter und Behörden der Reichsverwaltung mit ihren gegenwärtigen Amtsträgern. An der Spitze steht der Souverän; "
                             "ihm unterstehen das Kronkanzleramt mit den Reichsbehörden und das Reichsamt für die Kronstatthalterschaft. "
                             "Das Organigramm lässt sich zoomen und durchsuchen; ein Klick auf ein Amt nennt Amtsträger, Aufgaben und alle Beziehungen.")
              + f'<section class="rg-abschnitt">{organigramme.einbettung(request, "verwaltung", k)}</section>'
              f'<section class="rg-abschnitt"><h2>Aufbau der Reichsverwaltung</h2>{tab}</section>')
    return rahmen(request, k, "Organigramm", "r-organigramm", inhalt)


# ---------------------------------------------------------------- Reichskabinett (Aufbau wie bundesregierung.de/…/bundeskabinett)

KAB_CSS = """<style>
.kb-raster{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,250px),1fr));gap:18px;margin:8px 0 30px}
.kb-karte{display:flex;flex-direction:column;border:1px solid var(--linie);border-radius:var(--r);background:#fff;overflow:hidden;transition:box-shadow .2s,transform .2s}
.kb-karte:hover{box-shadow:0 14px 30px -18px rgba(16,24,40,.45);transform:translateY(-2px)}
.kb-bild{display:block;aspect-ratio:1/1;background:transparent;overflow:hidden;position:relative;border-bottom:1px solid var(--linie)}
.kb-bild img{display:block;width:100%;height:100%;object-fit:cover;object-position:center top}
.kb-bild .rg-silhouette{position:absolute;left:50%;bottom:-8%;transform:translateX(-50%);width:52%}
.kb-text{padding:14px 16px 16px;display:flex;flex-direction:column;gap:6px;flex:1}
.kb-text h3{margin:0;font-size:17px;line-height:1.3}.kb-text h3 a{color:var(--ink);text-decoration:none}.kb-text h3 a:hover{color:var(--akzent)}
.kb-text a.kb-link{color:var(--akzent);text-decoration:none;font-size:14px;font-weight:600;display:inline-flex;gap:6px;align-items:center}
.kb-text a.kb-link .icon{width:15px;height:15px}.kb-text a.kb-link:hover{text-decoration:underline}
.kb-amt{color:#3d4148;font-size:14px}
.kb-person{display:grid;grid-template-columns:minmax(0,340px) minmax(0,1fr);gap:clamp(20px,4vw,48px);align-items:start}
.kb-person .kb-bild{aspect-ratio:4/5;border-radius:var(--r);border:0}.kb-person .kb-bild img{object-position:center top}
@media(max-width:760px){.kb-person{grid-template-columns:1fr}.kb-person .kb-bild{max-width:340px}}
</style>"""

LEBENSLAUF_SCHEMA = """CREATE TABLE IF NOT EXISTS regierung_lebenslauf (
    konto_id TEXT PRIMARY KEY, text TEXT NOT NULL DEFAULT '', aktualisiert INTEGER NOT NULL, autor_name TEXT NOT NULL DEFAULT '');"""


async def mitglieder_mit_rollen(request, rollen):
    """[(Konto-ID, IC-Name)] aller Träger der Rollen; IC-Name aus der Bürgerakte, sonst Discord-Name."""
    try:
        con = request.app["db"]
        return sorted(((m["id"], ic_name(con, m["id"], m["name"])) for m in await request.app["discord"].mitglieder() if set(rollen) & set(m["rollen"])),
                      key=lambda x: x[1])
    except Exception:
        return []


async def kabinett_liste(request):
    """[(konto_id, name, amt, ministerium)] in Ressortfolge: Kronkanzler zuerst, dann die Reichsbehörden wie in reichsbehoerden.py."""
    alle, _ = ressorts()
    out, gesehen = [], set()
    for b in alle:
        rollen = LEITUNG_ROLLEN.get(b["schl"])
        if not rollen:
            continue
        for kid, name in await mitglieder_mit_rollen(request, rollen):
            if (kid, b["schl"]) in gesehen:
                continue
            gesehen.add((kid, b["schl"]))
            amt_ = "Kronkanzler" if b["schl"] == "kanzlei" else ohne_artikel(b.get("leitung", "Leitung"))
            out.append((kid, name, amt_, b))
    return out


def _kb_bild(b):
    url = bild_url(b["schl"])
    return f'<img src="{url}" alt="Porträtbild">' if url else SILHOUETTE


async def reichsregierung(request):
    k = await anmeldung.konto(request)
    kab = await kabinett_liste(request)
    kanzler = next((n for _, n, _, b in kab if b["schl"] == "kanzlei"), None)
    kanzler_id = next((i for i, _, _, b in kab if b["schl"] == "kanzlei"), None)
    weitere = len({i for i, _, _, b in kab if b["schl"] != "kanzlei" and i != kanzler_id})
    personen = {}   # eine Karte je Person, mehrere Ämter zusammengefasst
    for kid, name, amt_, b in kab:
        personen.setdefault(kid, [name, [], []])
        personen[kid][1].append(amt_)
        personen[kid][2].append(b)
    einleitung = (f"Die aktuelle Reichsregierung besteht aus {esc(leitung_titel('Kronkanzler', [kanzler])) if kanzler else 'dem Kronkanzler'} sowie {weitere} "
                  f"{'Leiterin oder Leiter' if weitere == 1 else 'Leiterinnen und Leitern'} der Reichsbehörden. Gemeinsam bilden sie das Reichskabinett. "
                  "Hier finden Sie ihre Lebensläufe sowie Informationen zu den jeweiligen Ministerien.")
    karten = "".join(
        f'<article class="kb-karte"><a class="kb-bild" href="{PFAD}reichsregierung/{kid}/" aria-hidden="true" tabindex="-1">{_kb_bild(b)}</a>'
        f'<div class="kb-text"><h3><a href="{PFAD}reichsregierung/{kid}/">{esc(name)}</a></h3><span class="kb-amt">{esc(" und ".join(aemter_))}</span>'
        f'<a class="kb-link" href="{PFAD}reichsregierung/{kid}/#lebenslauf">{ic("arrow-right")}Lebenslauf</a>'
        + "".join(f'<a class="kb-link" href="{ministerium_url(b)}">{ic("arrow-right")}{esc(b["name"])}</a>' for b in bs) + '</div></article>'
        for kid, (name, aemter_, bs) in personen.items() for b in bs[:1])
    alle, _ = ressorts()
    besetzt = {b["schl"] for _, _, _, b in kab}
    frei = [b for b in alle if LEITUNG_ROLLEN.get(b["schl"]) and b["schl"] not in besetzt]
    frei_html = ("<h2>Zurzeit unbesetzt</h2><ul class=\"rg-liste\">" + "".join(
        f'<li><a href="{ministerium_url(b)}">{esc(b["name"])}</a><span class="rg-datum">{esc(b.get("leitung", ""))}</span></li>' for b in frei) + "</ul>") if frei else ""
    inhalt = (KAB_CSS + kopf("Reichskabinett", einleitung, "Die Reichsregierung")
              + f'<section class="rg-abschnitt"><h2>Das Reichskabinett</h2><div class="kb-raster">{karten or "<p class=leer>Keine Angaben.</p>"}</div>{frei_html}</section>'
              + f'<section class="rg-abschnitt"><h2>Mehr zum Reichskabinett</h2><ul class="rg-liste"><li><a href="{PFAD}ministerien/">Alle Ministerien</a></li>'
              f'<li><a href="{PFAD}aktuelles/?art=kabinett">Kabinettsbeschlüsse</a></li><li><a href="/der-souveraen/">Der Souverän</a></li></ul></section>')
    return rahmen(request, k, "Reichskabinett", "r-regierung", inhalt)


def _darf_lebenslauf(k, kid):
    return bool(k) and bool(k["mitglied"]) and (k["id"] == kid or ist_redaktion(k))


async def kabinett_person(request):
    k = await anmeldung.konto(request)
    kid = request.match_info["id"]
    aemter = [(n, a, b) for i, n, a, b in await kabinett_liste(request) if i == kid]
    if not aemter:
        raise web.HTTPNotFound(text="Kein Mitglied des Reichskabinetts.")
    name, _, b0 = aemter[0]
    con = request.app["db"]
    lv = con.execute("SELECT * FROM regierung_lebenslauf WHERE konto_id=?", (kid,)).fetchone()
    text = absatz(lv["text"]) if lv and lv["text"].strip() else '<p class="leer">Der Lebenslauf wird noch ergänzt.</p>'
    aemter_html = "".join(f'<li><a href="{ministerium_url(b)}">{esc(b["name"])}</a><span class="rg-datum">{esc(a)}</span></li>' for _, a, b in aemter)
    bearb = ""
    if _darf_lebenslauf(k, kid):
        bearb = ('<p style="margin-top:18px">' + modal_knopf("lv-modal", "Lebenslauf bearbeiten") + "</p>"
                 + modal("lv-modal", "Lebenslauf bearbeiten",
                         f'<form class="rg-form" method="post" action="{PFAD}reichsregierung/{kid}/lebenslauf">{csrf_feld(request)}'
                         f'<label>Lebenslauf (Absätze mit Leerzeile trennen)<textarea name="text" style="min-height:300px" maxlength="12000">{esc(lv["text"] if lv else "")}</textarea></label>'
                         f'<div class="rg-knoepfe"><button class="btn" type="submit">{ic("check")}Speichern</button>'
                         '<button class="btn zweit" type="button" data-modal-zu>Abbrechen</button></div></form>'))
    stand = f'<p class="rg-datum">Stand: {datum(lv["aktualisiert"])}</p>' if lv and lv["text"].strip() else ""
    inhalt = (KAB_CSS + f'<div class="kb-person"><div class="kb-bild">{_kb_bild(b0)}</div><div>'
              + kopf(name, " · ".join(esc(a) for _, a, _ in aemter), "Reichskabinett")
              + f'<h2>Ämter</h2><ul class="rg-liste">{aemter_html}</ul>'
              + f'<h2 id="lebenslauf">Lebenslauf</h2><div class="rg-text">{text}</div>{stand}{bearb}</div></div>')
    return rahmen(request, k, name, "r-regierung", inhalt, krumen=[("Reichskabinett", PFAD + "reichsregierung/"), (name, None)])


async def kabinett_lebenslauf(request):
    kid = request.match_info["id"]
    k, form = await post_pruefen(request, lambda k: _darf_lebenslauf(k, kid))
    con = request.app["db"]
    con.execute("INSERT INTO regierung_lebenslauf (konto_id, text, aktualisiert, autor_name) VALUES (?,?,?,?) "
                "ON CONFLICT(konto_id) DO UPDATE SET text=excluded.text, aktualisiert=excluded.aktualisiert, autor_name=excluded.autor_name",
                (kid, (form.get("text") or "").strip()[:12000], int(time.time()), k["name"]))
    con.commit()
    weiter(f"{PFAD}reichsregierung/{kid}/#lebenslauf", "Lebenslauf gespeichert.")


async def suche(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    q = (request.query.get("q") or "").strip()[:80]
    treffer = []
    if len(q) >= 2:
        ql = q.lower()
        treffer += [(m["art"] + " · " + m["quelle"], m["titel"], m["url"]) for m in alle_meldungen(con) if ql in (m["titel"] + " " + m["kurz"]).lower()]
        alle, _ = ressorts()
        treffer += [("Ministerium", b["name"], ministerium_url(b)) for b in alle if ql in (b["name"] + " " + b.get("lead", "") + " " + " ".join(b.get("aufgaben", []))).lower()]
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
            f'<li><a href="{esc(u)}">{esc(t)}</a></li>' for a, t, u in treffer) + "</ul>"
    else:
        erg = f'<p class="leer">Keine Treffer für „{esc(q)}“.</p>'
    return rahmen(request, k, "Suche", "r-suche", kopf("Suche") + form + erg, q=q)


# ---------------------------------------------------------------- Unterseite je Ministerium (/regierung/<schl>/)

def darf_schreiben(k, ressort):
    """Redaktion eines Ministeriums: Kaiser, Kronkanzler, OOC-Admins und die Leitung des Ministeriums."""
    if ist_redaktion(k):
        return True
    return bool(k) and bool(k["mitglied"]) and bool(ressort) and bool(set(LEITUNG_ROLLEN.get(ressort, [])) & set(k["rollen"]))


def _ministerium(request):
    alle, gruppen = ressorts()
    b = next((x for x in alle if x["schl"] == request.match_info["schl"]), None)
    if not b:
        raise web.HTTPNotFound(text="Ministerium nicht gefunden.")
    return b, gruppen


def portal_ministerium(b, k):
    s = b["schl"]
    nav = [("Übersicht", "", [("m-start", "Übersicht", "")]), ("Aufgaben", "aufgaben/", [("m-aufgaben", "Aufgaben", "aufgaben/")]),
           ("Meldungen", "meldungen/", [("m-meldungen", "Meldungen", "meldungen/")])]
    if darf_schreiben(k, s):
        nav.append(("Redaktion", "redaktion/", [("m-redaktion", "Redaktion", "redaktion/")]))
    return {"basis": f"{PFAD}{s}/", "logo": logo_von(s), "name": b["name"], "start": b.get("kurz") or b["name"], "nav": nav}


def _meldungen_von(con, s, alle=False):
    return con.execute("SELECT * FROM regierung_meldungen WHERE ressort=?" + ("" if alle else " AND status='veroeffentlicht'")
                       + " ORDER BY COALESCE(veroeffentlicht, erstellt) DESC LIMIT 200", (s,)).fetchall()


def _mkarte(b, m):
    return (f'<a class="rg-karte" href="{PFAD}{b["schl"]}/meldungen/{m["id"]}/">'
            f'<h3>{esc(m["titel"])}</h3><p>{esc(m["kurz"])}</p><span class="rg-datum">{datum(m["veroeffentlicht"])}</span></a>')


async def ministerium_start(request):
    k = await anmeldung.konto(request)
    b, gruppen = _ministerium(request)
    con = request.app["db"]
    rollen = LEITUNG_ROLLEN.get(b["schl"])
    namen = await namen_mit_rollen(request, rollen) if rollen else []
    bild = f'<img src="{PFAD}logo/kanzler-kurz.png" alt="">'
    knopf = ""
    if b["schl"] in WEBAUFTRITTE and not WEBAUFTRITTE[b["schl"]].startswith(PFAD):
        knopf = f'<div class="rg-knoepfe"><a class="btn" href="{WEBAUFTRITTE[b["schl"]]}">{ic("arrow-right")}Zum Portal: {esc(b.get("kurz") or b["name"])}</a></div>'
    held = (f'<div class="rg-held"><div class="rg-held-text"><h2>{esc(b["name"])}</h2>'
            f'<p>{esc(b.get("lead", ""))}</p>{knopf}</div><div class="rg-held-bild">{bild}</div></div>')
    kurz = b.get("kurz") or b["name"]
    basis = f'{PFAD}{b["schl"]}/'
    leitung = leitung_block(leitung_titel(b.get("leitung", "Leitung"), namen), b["schl"],
                            [(f"Die Leitung des Amtes", basis + "aufgaben/#leitung"), ("Reden", basis + "meldungen/?art=rede"),
                             ("Pressemitteilungen", basis + "meldungen/?art=pressemitteilung"), ("Aufgaben und Organisation", basis + "aufgaben/")])
    ms = _meldungen_von(con, b["schl"])[:3]
    meld = (f'<section class="rg-abschnitt"><h2>Meldungen <a href="{PFAD}{b["schl"]}/meldungen/">Alle Meldungen</a></h2>'
            + (f'<div class="rg-karten">{"".join(_mkarte(b, m) for m in ms)}</div>' if ms else '<p class="leer">Noch keine Meldungen.</p>') + "</section>")
    auf = b.get("aufgaben", [])
    aufgaben = (f'<section class="rg-abschnitt"><h2>Aufgaben <a href="{PFAD}{b["schl"]}/aufgaben/">Mehr erfahren</a></h2><ul class="rg-text">'
                + "".join(f"<li>{esc(a)}</li>" for a in auf[:4]) + "</ul></section>") if auf else ""
    return rahmen(request, k, b["name"], "m-start", held + leitung + aufgaben + meld, portal=portal_ministerium(b, k), krumen=[])


async def ministerium_aufgaben(request):
    k = await anmeldung.konto(request)
    b, gruppen = _ministerium(request)
    rollen = LEITUNG_ROLLEN.get(b["schl"])
    namen = await namen_mit_rollen(request, rollen) if rollen else []
    daten = [("Gliederung", gruppen.get(b["gruppe"], "")), ("Leitung", b.get("leitung", "–"))]
    if b.get("untersteht"):
        daten.append(("Untersteht", b["untersteht"]))
    if rollen:
        daten.append(("Amtsinhaber", ", ".join(namen) or "unbesetzt"))
    if b.get("gebaeude"):
        g = b["gebaeude"]
        daten.append(("Dienstsitz", g.get("name", "") + (", " + g["ort"] if g.get("ort") else ", Berlin")))
    elif b.get("bestand"):
        daten.append(("Dienstsitz", b["bestand"] + ", Berlin"))
    if b.get("nachgeordnet"):
        daten.append(("Nachgeordnet", ", ".join(b["nachgeordnet"])))
    if b.get("zusammen"):
        daten.append(("Zusammenarbeit", ", ".join(b["zusammen"])))
    dl = '<dl class="rg-daten" id="leitung">' + "".join(f"<dt>{esc(a)}</dt><dd>{esc(w)}</dd>" for a, w in daten) + "</dl>"
    aufgaben = ("<h2>Aufgaben</h2><ul class='rg-text'>" + "".join(f"<li>{esc(a)}</li>" for a in b.get("aufgaben", [])) + "</ul>") if b.get("aufgaben") else ""
    if b.get("aemter"):
        aufgaben += (ORG_CSS + '<h2 id="aemter">Die Ämter</h2><div class="rgo-tab-rahmen"><table class="rgo-tab"><thead><tr><th>Amt</th><th>Zuständigkeit</th><th>Anrede</th></tr></thead><tbody>'
                     + "".join(f'<tr><th scope="row">{esc(a)}</th><td>{esc(z)}</td><td>{esc(r)}</td></tr>' for a, z, r in b["aemter"]) + "</tbody></table></div>")
    web_link = f'<p><a class="btn zweit" href="/{b["seite"].lstrip("/")}">{ic("external-link")}Auch auf imperiumgermanicum.de</a></p>' if b.get("seite") else ""
    return rahmen(request, k, "Aufgaben", "m-aufgaben", kopf("Aufgaben und Organisation", esc(b.get("lead", "")), b.get("kurz") or b["name"]) + dl + aufgaben + web_link,
                  portal=portal_ministerium(b, k))


async def ministerium_meldungen(request):
    k = await anmeldung.konto(request)
    b, _ = _ministerium(request)
    ms = _meldungen_von(request.app["db"], b["schl"])
    art = request.query.get("art", "")
    if art in MELDUNGSARTEN:
        ms = [m for m in ms if m["art"] == art]
    filt = ('<div class="rg-schnell">' + f'<a href="?" class="{"" if art else "aktiv"}">Alle</a>'
            + "".join(f'<a href="?art={a}" class="{"aktiv" if a == art else ""}">{t}</a>' for a, t in MELDUNGSARTEN.items()) + "</div>")
    inhalt = filt + (f'<div class="rg-karten">{"".join(_mkarte(b, m) for m in ms)}</div>' if ms else '<p class="leer">Keine Meldungen.</p>')
    return rahmen(request, k, "Meldungen", "m-meldungen", kopf("Meldungen", "", b.get("kurz") or b["name"]) + inhalt, portal=portal_ministerium(b, k))


async def ministerium_meldung(request):
    k = await anmeldung.konto(request)
    b, _ = _ministerium(request)
    m = request.app["db"].execute("SELECT * FROM regierung_meldungen WHERE id=? AND ressort=?", (request.match_info["id"], b["schl"])).fetchone()
    if not m or (m["status"] != "veroeffentlicht" and not darf_schreiben(k, b["schl"])):
        raise web.HTTPNotFound(text="Meldung nicht gefunden.")
    bearb = f'{PFAD}{b["schl"]}/redaktion/{m["id"]}/' if darf_schreiben(k, b["schl"]) else ""
    return rahmen(request, k, m["titel"], "m-meldungen", _meldung_html(m, k, bearb), portal=portal_ministerium(b, k),
                  krumen=[("Meldungen", f'{PFAD}{b["schl"]}/meldungen/'), (m["titel"], None)])


# ---------------------------------------------------------------- Redaktion (Reichsregierung: /intern/, Ministerium: /<schl>/redaktion/)

def _redaktion_liste(ms, basis):
    if not ms:
        return '<p class="leer">Noch keine Meldungen.</p>'
    return ('<table class="rg-tab"><thead><tr><th>Titel</th><th>Art</th><th>Stand</th><th>Datum</th></tr></thead><tbody>' + "".join(
        f'<tr><td><a href="{basis}{m["id"]}/">{esc(m["titel"])}</a></td><td>{esc(MELDUNGSARTEN.get(m["art"], ""))}</td>'
        f'<td>{"<span class=\'status s-ok\'>Veröffentlicht</span>" if m["status"] == "veroeffentlicht" else "<span class=\'status s-neutral\'>Entwurf</span>"}</td>'
        f'<td>{datum(m["veroeffentlicht"] or m["erstellt"])}</td></tr>' for m in ms) + "</tbody></table>")


def _redaktion_form(request, m, aktion, loeschen):
    w = lambda f, d="": (m[f] if m else d)
    form = (f'<form class="rg-form" method="post" action="{aktion}">{csrf_feld(request)}'
            f'<label>Titel<input name="titel" maxlength="160" required value="{esc(w("titel"))}"></label>'
            f'<label>Art<select name="art">{opt(MELDUNGSARTEN.items(), w("art", "pressemitteilung"))}</select></label>'
            f'<label>Kurztext (Teaser)<input name="kurz" maxlength="300" value="{esc(w("kurz"))}"></label>'
            f'<label>Text (Absätze mit Leerzeile trennen)<textarea name="text" style="min-height:300px" maxlength="20000">{esc(w("text"))}</textarea></label>'
            '<div class="rg-knoepfe"><button class="btn" name="aktion" value="veroeffentlichen" type="submit">Veröffentlichen</button>'
            '<button class="btn zweit" name="aktion" value="entwurf" type="submit">Als Entwurf speichern</button></div></form>')
    if m:
        form += (f'<form method="post" action="{loeschen}" onsubmit="return confirm(\'Meldung löschen?\')">{csrf_feld(request)}'
                 f'<button class="btn gefahr" type="submit">{ic("trash-2")}Löschen</button></form>')
    return form


def _speichern(con, k, form, m, ressort):
    titel = (form.get("titel") or "").strip()[:160]
    if not titel:
        return None
    art = form.get("art") if form.get("art") in MELDUNGSARTEN else "pressemitteilung"
    werte = (titel, art, (form.get("kurz") or "").strip()[:300], (form.get("text") or "").strip()[:20000])
    jetzt = int(time.time())
    if m:
        con.execute("UPDATE regierung_meldungen SET titel=?, art=?, kurz=?, text=? WHERE id=?", werte + (m["id"],))
        mid = m["id"]
    else:
        mid = con.execute("INSERT INTO regierung_meldungen (titel, art, kurz, text, autor_id, autor_name, erstellt, ressort) VALUES (?,?,?,?,?,?,?,?)",
                          werte + (k["id"], k["name"], jetzt, ressort)).lastrowid
    if form.get("aktion") == "veroeffentlichen":
        con.execute("UPDATE regierung_meldungen SET status='veroeffentlicht', veroeffentlicht=COALESCE(veroeffentlicht, ?) WHERE id=?", (jetzt, mid))
    else:
        con.execute("UPDATE regierung_meldungen SET status='entwurf', veroeffentlicht=NULL WHERE id=?", (mid,))
    con.commit()
    return mid


async def intern(request):
    k = await konto_oder_login(request)
    if not ist_redaktion(k):
        raise web.HTTPForbidden(text="Nur für die Redaktion der Reichsregierung (Kaiser, Kronkanzler).")
    ms = request.app["db"].execute("SELECT * FROM regierung_meldungen WHERE ressort='' ORDER BY COALESCE(veroeffentlicht, erstellt) DESC").fetchall()
    return rahmen(request, k, "Redaktion", "r-intern", kopf("Redaktion", "Pressemitteilungen, Kabinettsbeschlüsse und Reden der Reichsregierung. "
                                                            "Meldungen eines Ministeriums schreibt dessen Leitung auf der Seite des Ministeriums.", "Intern")
                  + f'<p><a class="btn" href="{PFAD}intern/neu/">{ic("file-plus")}Neue Meldung</a></p>' + _redaktion_liste(ms, PFAD + "intern/"))


async def intern_meldung(request):
    k = await konto_oder_login(request)
    if not ist_redaktion(k):
        raise web.HTTPForbidden(text="Nur für die Redaktion der Reichsregierung.")
    i = request.match_info.get("id")
    m = request.app["db"].execute("SELECT * FROM regierung_meldungen WHERE id=? AND ressort=''", (i,)).fetchone() if i else None
    if i and not m:
        raise web.HTTPNotFound()
    titel = m["titel"] if m else "Neue Meldung"
    form = _redaktion_form(request, m, f'{PFAD}intern/{i + "/" if i else "neu/"}', f'{PFAD}intern/{i}/loeschen')
    return rahmen(request, k, titel, "r-intern", kopf(titel, "", "Redaktion") + form, krumen=[("Redaktion", PFAD + "intern/"), (titel, None)])


async def intern_speichern(request):
    k, form = await post_pruefen(request, ist_redaktion)
    con = request.app["db"]
    i = request.match_info.get("id")
    m = con.execute("SELECT * FROM regierung_meldungen WHERE id=? AND ressort=''", (i,)).fetchone() if i else None
    mid = _speichern(con, k, form, m, "")
    if mid is None:
        weiter(request.path, f="Titel fehlt.")
    weiter(f"{PFAD}intern/{mid}/", "Gespeichert.")


async def intern_loeschen(request):
    k, _ = await post_pruefen(request, ist_redaktion)
    con = request.app["db"]
    con.execute("DELETE FROM regierung_meldungen WHERE id=? AND ressort=''", (request.match_info["id"],))
    con.commit()
    weiter(f"{PFAD}intern/", "Gelöscht.")


async def m_redaktion(request):
    k = await konto_oder_login(request)
    b, _ = _ministerium(request)
    if not darf_schreiben(k, b["schl"]):
        raise web.HTTPForbidden(text="Nur für die Leitung dieses Ministeriums.")
    basis = f'{PFAD}{b["schl"]}/redaktion/'
    return rahmen(request, k, "Redaktion", "m-redaktion", kopf("Redaktion", "Meldungen dieses Ministeriums. Veröffentlichte Meldungen erscheinen auch unter Aktuelles der Reichsregierung.",
                                                                b.get("kurz") or b["name"])
                  + f'<p><a class="btn" href="{basis}neu/">{ic("file-plus")}Neue Meldung</a></p>' + _redaktion_liste(_meldungen_von(request.app["db"], b["schl"], True), basis),
                  portal=portal_ministerium(b, k))


async def m_redaktion_meldung(request):
    k = await konto_oder_login(request)
    b, _ = _ministerium(request)
    if not darf_schreiben(k, b["schl"]):
        raise web.HTTPForbidden(text="Nur für die Leitung dieses Ministeriums.")
    i = request.match_info.get("id")
    m = request.app["db"].execute("SELECT * FROM regierung_meldungen WHERE id=? AND ressort=?", (i, b["schl"])).fetchone() if i else None
    if i and not m:
        raise web.HTTPNotFound()
    basis = f'{PFAD}{b["schl"]}/redaktion/'
    titel = m["titel"] if m else "Neue Meldung"
    return rahmen(request, k, titel, "m-redaktion", kopf(titel, "", "Redaktion") + _redaktion_form(request, m, f'{basis}{i + "/" if i else "neu/"}', f'{basis}{i}/loeschen'),
                  portal=portal_ministerium(b, k), krumen=[("Redaktion", basis), (titel, None)])


async def m_redaktion_speichern(request):
    b, _ = _ministerium(request)
    k, form = await post_pruefen(request, lambda k: darf_schreiben(k, b["schl"]))
    con = request.app["db"]
    i = request.match_info.get("id")
    m = con.execute("SELECT * FROM regierung_meldungen WHERE id=? AND ressort=?", (i, b["schl"])).fetchone() if i else None
    if i and not m:
        raise web.HTTPNotFound()
    mid = _speichern(con, k, form, m, b["schl"])
    if mid is None:
        weiter(request.path, f="Titel fehlt.")
    weiter(f'{PFAD}{b["schl"]}/redaktion/{mid}/', "Gespeichert.")


async def m_redaktion_loeschen(request):
    b, _ = _ministerium(request)
    k, _ = await post_pruefen(request, lambda k: darf_schreiben(k, b["schl"]))
    con = request.app["db"]
    con.execute("DELETE FROM regierung_meldungen WHERE id=? AND ressort=?", (request.match_info["id"], b["schl"]))
    con.commit()
    weiter(f'{PFAD}{b["schl"]}/redaktion/', "Gelöscht.")


async def alt_ressorts(request):
    umleiten(PFAD + "ministerien/")


async def alt_ressort(request):
    umleiten(f'{PFAD}{request.match_info["schl"]}/')


# ---------------------------------------------------------------- Regierungsfahrzeuge (Flugbereitschaft, Fahrbereitschaft) in 3D

DREI_D = os.path.join(config.HIER, "statisch", "three")
DREI_D_DATEIEN = {"three.module.min.js", "OrbitControls.js", "RoomEnvironment.js", "fahrzeug.js", "LICENSE-three.txt"}
# Typ → (Bezeichnung, Gruppe, Einsatz, Beschreibung, Datenblatt, Kennungsvorsilbe). Angelehnt an Flugbereitschaft der Luftwaffe und Fahrbereitschaft der Bundesregierung.
KATALOG = {
    "a350": ("Airbus A350-900 ACJ", "Flugbereitschaft", "Langstrecke · Staatsbesuche",
             "Das Flaggschiff der Flugbereitschaft für Staatsbesuche und Langstreckenreisen: Besprechungsraum, Ruhebereich, gesicherte Kommunikation und Platz für Delegation und Presse.",
             [("Länge", "66,8 m"), ("Spannweite", "64,75 m"), ("Reichweite", "ca. 15.000 km"), ("Triebwerke", "2 × Rolls-Royce Trent XWB"), ("Kabine", "VIP-Ausstattung, rund 140 Plätze")], "10+0"),
    "a330": ("Airbus A330-200 (VIP)", "Flugbereitschaft", "Langstrecke · große Delegationen",
             "Bewährter Großraumjet für lange Reisen mit großer Delegation.",
             [("Länge", "58,8 m"), ("Spannweite", "60,3 m"), ("Reichweite", "ca. 13.400 km"), ("Triebwerke", "2 Mantelstromtriebwerke"), ("Kabine", "VIP-Ausstattung")], "11+0"),
    "a321": ("Airbus A321LR", "Flugbereitschaft", "Mittelstrecke",
             "Schmalrumpfjet mit großer Reichweite für Reisen innerhalb Europas und zu benachbarten Kontinenten.",
             [("Länge", "44,5 m"), ("Spannweite", "35,8 m"), ("Reichweite", "ca. 7.400 km"), ("Triebwerke", "2 Mantelstromtriebwerke"), ("Kabine", "VIP- und Delegationsbereich")], "15+0"),
    "a319": ("Airbus A319CJ", "Flugbereitschaft", "Kurz- und Mittelstrecke",
             "Kompakter Regierungsjet für kleinere Delegationen auf kurzen und mittleren Strecken.",
             [("Länge", "33,8 m"), ("Spannweite", "35,8 m"), ("Reichweite", "ca. 11.000 km"), ("Triebwerke", "2 × CFM56"), ("Kabine", "VIP-Ausstattung")], "16+0"),
    "global": ("Bombardier Global 7500", "Flugbereitschaft", "Langstrecke · kleine Delegationen",
               "Großraum-Geschäftsreiseflugzeug mit sehr großer Reichweite für Leitungsreisen mit kleiner Begleitung.",
               [("Länge", "33,8 m"), ("Spannweite", "31,7 m"), ("Reichweite", "ca. 14.000 km"), ("Triebwerke", "2 Mantelstromtriebwerke (Heck)"), ("Kabine", "rund 14 Plätze, vier Bereiche")], "14+0"),
    "h225": ("Eurocopter AS532 Cougar", "Flugbereitschaft", "Hubschrauber · Pendelflüge",
             "Zweimotoriger Transporthubschrauber der Super-Puma-Familie, wie ihn die Flugbereitschaft für Pendelflüge zwischen den Dienstsitzen nutzt.",
             [("Länge", "18,7 m (mit Rotor)"), ("Rotordurchmesser", "15,6 m"), ("Reichweite", "ca. 800 km"), ("Triebwerke", "2 Wellenturbinen"), ("Kabine", "VIP-Ausstattung, bis 12 Plätze")], "82+"),
    "sklasse": ("Mercedes-Benz S 680 Guard", "Fahrbereitschaft", "Geschützte Limousine",
                "Gepanzerte Staatslimousine der höchsten zivilen Schutzklasse für die Leitung, mit Standarten auf den Kotflügeln.",
                [("Länge", "5,47 m"), ("Schutzklasse", "VR10"), ("Antrieb", "V12, Allrad"), ("Gewicht", "ca. 4,2 t"), ("Sitze", "4")], "IG-R 1"),
    "a8": ("Audi A8 L Security", "Fahrbereitschaft", "Geschützte Limousine",
           "Gepanzerte Langversion für Leitung und Staatsgäste.",
           [("Länge", "5,45 m"), ("Schutzklasse", "VR10"), ("Antrieb", "V8, Allrad"), ("Gewicht", "ca. 4 t"), ("Sitze", "4")], "IG-R 2"),
    "bmw7": ("BMW 7er Protection", "Fahrbereitschaft", "Geschützte Limousine",
             "Sonderschutz-Limousine für Leitung und Staatssekretäre.",
             [("Länge", "5,39 m"), ("Schutzklasse", "VR9"), ("Antrieb", "V8, Allrad"), ("Gewicht", "ca. 3,5 t"), ("Sitze", "4")], "IG-R 3"),
    "vklasse": ("Mercedes-Benz V-Klasse", "Fahrbereitschaft", "Delegation · Begleitung",
                "Großraumlimousine für Delegationen, Gäste und Begleitpersonal.",
                [("Länge", "5,14 m"), ("Sitze", "7–8"), ("Antrieb", "Diesel, Automatik"), ("Einsatz", "Delegationsfahrten")], "IG-R 5"),
    "sprinter": ("Mercedes-Benz Sprinter", "Fahrbereitschaft", "Begleitfahrzeug · Technik",
                 "Begleit- und Technikfahrzeug für Kolonnen, Gepäck und Funktechnik.",
                 [("Länge", "5,93 m"), ("Höhe", "2,6 m"), ("Sitze", "bis 9"), ("Einsatz", "Kolonne, Technik, Gepäck")], "IG-R 7"),
}
# 3D-Modelle (Sketchfab, CC BY 4.0, verändert: Lackierung ersetzt/ergänzt) – Titel, Urheber, Modell-ID
MODELL_QUELLEN = {
    "a350": ("airbus a350", "1883", "1232147f25c942beb2a36997596b9dc3"), "a330": ("airbus a330", "1883", "9f40c75533df4faf9de1854fb36add80"),
    "a321": ("Generic Airbus A321", "barengdoc13", "59065f1ccd78433ebe24b5005eface73"), "a319": ("A319 plane", "gregoirebonnin", "8cc47f95310b4932b7cf71ecb4436811"),
    "global": ("Bombardier_Global_7500", "mhmdshwatahmdmhdy9", "08c977705e4b473bb0539b32a86a6c27"),
    "h225": ("AS332 Super Puma \"old\"", "arthur80cristian", "caea6ddba5ed457d960a75cb4ef2e7c9"),
    "sklasse": ("Mersedes-Benz s65 w222", "BlackSnow02", "f42d9d13b0404b5b9a2302a4c590a94d"), "a8": ("Audi A8 Custom 2018", "everhard", "cd094d03f7684809900a929a9c88c8db"),
    "bmw7": ("BMW 7-series (F01)", "BlackSnow02", "0806c39847ae42e5996917f50527dda0"), "vklasse": ("Mercedes Benz V Class", "Car2022", "61583f5c172f4e25a963e52e1e67c11a"),
    "sprinter": ("2019 Mercedes-Benz Sprinter", "tonielpro520", "5788a290ddb5483fbbd5831aeef829a1"),
}
# Persönliche Standarte der Leitung auf den Kotflügel-Fahnen (sonst allgemeine Adler-Fahne)
STANDARTEN = {"kanzlei": "/assets/img/i5a9f8040f8005417-640.webp"}   # Standarte des Kronkanzlers
FLUG_TYPEN = {"a350", "a330", "a321", "a319", "global", "h225"}
# Hausfarbe je Ministerium (Bauch, Leitwerk, Winglets der Flugzeuge)
AKZENTE = {"kanzlei": "#1f2f45", "crownestates": "#3b2a4d", "krs": "#2b2f36", "polizei": "#1d4f91", "zoll": "#2e6b45",
           "katastrophenschutz": "#b85a00", "inquisition": "#6b1f24", "generalkonsulat": "#1f3a6e", "schatzamt": "#7a5a12", "heroldsamt": "#5a2a2a"}
# Behördenlackierung der Straßenfahrzeuge (sonst Schwarz mit Standarten)
SONDER = {"polizei": {"grund": "#eef0f3", "streifen": "#1d4f91", "zweit": "#9cc3f0", "text": "POLIZEI", "licht": "#1e5bff"},
          "zoll": {"grund": "#eef0f3", "streifen": "#2e6b45", "zweit": "#9fd1b1", "text": "ZOLL", "licht": "#1e5bff"},
          "katastrophenschutz": {"grund": "#f4f5f7", "streifen": "#e07000", "zweit": "#1f3a8a", "text": "KATASTROPHENSCHUTZ", "licht": "#1e5bff"}}

FZ_CSS = """<style>
.fz-raster{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,210px),1fr));gap:14px;margin:0 0 30px}
.fz-kachel{display:flex;flex-direction:column;align-items:flex-start;gap:10px;min-height:132px;border:1px solid var(--linie);border-radius:var(--r);padding:16px 18px;
 background:#fff;color:var(--ink);text-decoration:none;position:relative;transition:transform .2s,box-shadow .2s,border-color .2s}
a.fz-kachel:hover{transform:translateY(-2px);box-shadow:0 14px 30px -18px rgba(16,24,40,.45);border-color:#c6ccd6}
.fz-kachel img{height:46px;width:auto;max-width:calc(100% - 34px);object-fit:contain;object-position:left}
.fz-kachel b{font-size:14.5px;line-height:1.3}.fz-kachel small{color:var(--grau);font-size:12.5px;margin-top:auto}
.fz-kachel.leer{opacity:.45;filter:grayscale(1);background:transparent}
.fz-kachel .fz-zahl{position:absolute;top:12px;right:12px;background:var(--kopf);color:#fff;border-radius:999px;font-size:11.5px;font-weight:700;padding:2px 9px}
.fz-buehne{position:relative;height:min(62vh,560px);min-height:340px;border-radius:calc(var(--r) + 6px);overflow:hidden;background-color:#dfe4ea;
 background:radial-gradient(120% 90% at 50% 12%,#f7f9fb 0%,#dfe5ec 55%,#c3ccd8 100%);border:1px solid var(--glas-rand,var(--linie))}
.fz-buehne canvas{display:block;width:100%!important;height:100%!important;touch-action:none;cursor:grab}
.fz-buehne:not(.fertig)::after{content:"Modell wird gebaut …";position:absolute;inset:0;display:grid;place-items:center;color:var(--grau);font-size:14px}
.fz-leiste{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 0}
.fz-leiste button{all:unset;cursor:pointer;padding:7px 14px;border-radius:999px;font-size:13.5px;background:rgba(22,23,26,.05);color:#3a3e45}
.fz-leiste button:hover{background:rgba(22,23,26,.1)}.fz-leiste button[aria-pressed=true]{background:var(--kopf);color:#fff}
.fz-wahl{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
.fz-wahl a{border:1px solid var(--linie);border-radius:999px;padding:6px 14px;font-size:13.5px;color:var(--ink);text-decoration:none;background:#fff}
.fz-wahl a.aktiv{background:var(--kopf);border-color:var(--kopf);color:#fff}
.fz-raster2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,340px);gap:28px;margin-top:24px}
@media(max-width:900px){.fz-raster2{grid-template-columns:1fr}.fz-buehne{height:52vh}}
.fz-hinweis{font-size:12px;color:var(--grau);margin-top:8px}
</style>"""


def _fz_einrichten(con):
    con.executescript("""CREATE TABLE IF NOT EXISTS regierung_fahrzeuge (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ressort TEXT NOT NULL, typ TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', kennung TEXT NOT NULL DEFAULT '',
        erstellt INTEGER NOT NULL, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');""")
    con.commit()


def _fz_kennung(con, typ):
    vor = KATALOG[typ][5]
    n = con.execute("SELECT COUNT(*) FROM regierung_fahrzeuge WHERE typ=?", (typ,)).fetchone()[0] + 1
    return f"{vor}{n}" if typ in FLUG_TYPEN else f"{vor}{n:02d}"


def _modell_version(typ):
    p = os.path.join(DREI_D, "modelle", typ + ".glb")
    return int(os.path.getmtime(p)) if os.path.isfile(p) else 0


def _modell_nachweis(typ):
    q = MODELL_QUELLEN.get(typ)
    if not q:
        return ""
    titel, urheber, uid = q
    return (f'<p class="fz-hinweis">3D-Modell: „{esc(titel)}“ von {esc(urheber)} (sketchfab.com/3d-models/{esc(uid)}), Lizenz CC BY 4.0 '
            '(creativecommons.org/licenses/by/4.0), verändert: Lackierung und Beschriftung ersetzt.</p>')


async def drei_d(request):
    """three.js, Lader und Modelle aus statisch/three/ (nur .js/.glb/.txt, keine Pfade nach außen)."""
    name = request.match_info["datei"]
    if not re.fullmatch(r"(?:[a-z]+/)?[A-Za-z0-9_.-]+\.(?:js|glb|txt)", name) or ".." in name:
        raise web.HTTPNotFound()
    pfad = os.path.join(DREI_D, name)
    if not os.path.isfile(pfad):
        raise web.HTTPNotFound()
    art = {"glb": "model/gltf-binary", "js": "text/javascript", "txt": "text/plain"}[name.rsplit(".", 1)[1]]
    return web.FileResponse(pfad, headers={"Cache-Control": "no-cache", "Content-Type": art})


def _fz_typ_optionen():
    teile = []
    for gruppe in ("Flugbereitschaft", "Fahrbereitschaft"):
        teile.append(f'<optgroup label="{gruppe}">' + "".join(f'<option value="{t}">{esc(v[0])} – {esc(v[2])}</option>'
                                                              for t, v in KATALOG.items() if v[1] == gruppe) + "</optgroup>")
    return "".join(teile)


async def fahrzeuge(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    alle, gruppen = ressorts()
    anzahl = dict(con.execute("SELECT ressort, COUNT(*) FROM regierung_fahrzeuge GROUP BY ressort").fetchall())
    teile = []
    for g, gname in gruppen.items():
        bs = [b for b in alle if b["gruppe"] == g]
        if not bs:
            continue
        kacheln = ""
        for b in bs:
            lg, n = logo_von(b["schl"]), anzahl.get(b["schl"], 0)
            bild = f'<img src="{PFAD}logo/{lg}-kopf.png" alt="">' if lg else f'<img src="{PFAD}logo/regierung-kurz.png" alt="">'
            if n:
                kacheln += (f'<a class="fz-kachel" href="{PFAD}fahrzeuge/{b["schl"]}/">{bild}<b>{esc(b["name"])}</b>'
                            f'<span class="fz-zahl">{n}</span><small>{"1 Fahrzeug" if n == 1 else f"{n} Fahrzeuge"} · in 3D ansehen</small></a>')
            else:
                kacheln += f'<div class="fz-kachel leer">{bild}<b>{esc(b["name"])}</b><small>Kein Fahrzeug festgelegt</small></div>'
        teile.append(f'<h3 class="rg-gruppe">{esc(gname)}</h3><div class="fz-raster">{kacheln}</div>')
    verwaltung = ""
    if ist_redaktion(k):
        liste = con.execute("SELECT * FROM regierung_fahrzeuge ORDER BY ressort, erstellt").fetchall()
        namen = {b["schl"]: b["name"] for b in alle}
        zeilen = "".join(
            f'<tr><td>{esc(namen.get(f["ressort"], f["ressort"]))}</td><td>{esc(KATALOG.get(f["typ"], ("?",))[0])}</td><td>{esc(f["kennung"])}</td><td>{esc(f["name"] or "–")}</td>'
            f'<td><form method="post" action="{PFAD}fahrzeuge/{f["id"]}/entfernen" onsubmit="return confirm(\'Fahrzeug entfernen?\')">{csrf_feld(request)}'
            f'<button class="btn gefahr" type="submit">{ic("trash-2")}Entfernen</button></form></td></tr>' for f in liste)
        verwaltung = (f'<section class="rg-abschnitt" id="festlegen"><h2>Fahrzeuge verwalten (Kronkanzler)</h2>'
                      + f'<p>{modal_knopf("fz-modal", "Fahrzeug festlegen", "file-plus", "btn")}</p>'
                      + '<dialog class="rw-modal" id="fz-modal" data-bei-fehler aria-labelledby="fz-modal-t"><div class="rw-modal-kopf"><h2 id="fz-modal-t">Fahrzeug festlegen</h2>'
                      + f'<button class="knopf-rund" type="button" data-modal-zu aria-label="Schließen">{ic("x")}</button></div><div class="rw-modal-inhalt">'
                      f'<form class="rg-form" method="post" action="{PFAD}fahrzeuge/festlegen">{csrf_feld(request)}'
                      f'<div class="rg-zwei"><label>Ministerium<select name="ressort" required>{opt([(b["schl"], b["name"]) for b in alle], request.query.get("ressort", ""))}</select></label>'
                      f'<label>Fahrzeug<select name="typ" required>{_fz_typ_optionen()}</select></label></div>'
                      '<div class="rg-zwei"><label>Taufname (optional, z. B. für Flugzeuge)<input name="name" maxlength="60" placeholder="z. B. Otto von Bismarck"></label>'
                      '<label>Kennung (leer = automatisch)<input name="kennung" maxlength="20" placeholder="z. B. 10+01 oder IG-R 101"></label></div>'
                      f'<div class="rg-knoepfe"><button class="btn" type="submit">{ic("check")}Festlegen</button>'
                      '<button class="btn zweit" type="button" data-modal-zu>Abbrechen</button></div></form></div></dialog>'
                      + (f'<table class="rg-tab"><thead><tr><th>Ministerium</th><th>Fahrzeug</th><th>Kennung</th><th>Taufname</th><th></th></tr></thead><tbody>{zeilen}</tbody></table>' if liste else "")
                      + "</section>")
    inhalt = (FZ_CSS + kopf("Regierungsfahrzeuge", "Flugbereitschaft und Fahrbereitschaft der Reichsregierung. Wählen Sie ein Ministerium, um seine Fahrzeuge in 3D anzusehen – "
                                                   "angeklickt werden können alle Ministerien, denen der Kronkanzler ein Fahrzeug zugewiesen hat.", "Flug- und Fahrbereitschaft")
              + "".join(teile) + verwaltung)
    return rahmen(request, k, "Regierungsfahrzeuge", "r-fahrzeuge", inhalt)


async def fahrzeug_ansicht(request):
    k = await anmeldung.konto(request)
    con = request.app["db"]
    alle, _ = ressorts()
    b = next((x for x in alle if x["schl"] == request.match_info["schl"]), None)
    fz = con.execute("SELECT * FROM regierung_fahrzeuge WHERE ressort=? ORDER BY erstellt", (b["schl"],)).fetchall() if b else []
    if not b or not fz:
        raise web.HTTPNotFound(text="Für dieses Ministerium ist kein Regierungsfahrzeug festgelegt.")
    wahl = request.query.get("fz", "")   # nicht „f“: das wertet rahmen() als Fehlermeldung aus
    f = next((x for x in fz if str(x["id"]) == wahl), fz[0])
    typ = KATALOG.get(f["typ"], KATALOG["sklasse"])
    wahlleiste = ('<div class="fz-wahl">' + "".join(f'<a href="?fz={x["id"]}" class="{"aktiv" if x["id"] == f["id"] else ""}">{esc(KATALOG.get(x["typ"], ("?",))[0])}'
                                                    f'{" · " + esc(x["kennung"]) if x["kennung"] else ""}</a>' for x in fz) + "</div>") if len(fz) > 1 else ""
    daten = {"typ": f["typ"], "kennung": f["kennung"], "name": f["name"], "behoerde": b["name"], "akzent": AKZENTE.get(b["schl"], "#1f2f45"),
             "sonder": SONDER.get(b["schl"]) if f["typ"] not in FLUG_TYPEN else None, "adler": f"{PFAD}logo/kanzler-kurz.png",
             "basis": f"{PFAD}3d/", "v": _modell_version(f["typ"]), "standarte": STANDARTEN.get(b["schl"], "")}
    v = int(os.path.getmtime(os.path.join(DREI_D, "fahrzeug.js")))
    buehne = (f'<div class="fz-buehne" id="fz-buehne" aria-label="3D-Ansicht: {esc(typ[0])}"></div>'
              '<div class="fz-leiste"><button type="button" data-ansicht="schraeg">Schräg</button><button type="button" data-ansicht="seite">Seite</button>'
              '<button type="button" data-ansicht="vorne">Vorne</button><button type="button" data-ansicht="oben">Oben</button>'
              '<button type="button" id="fz-dreh" aria-pressed="true">Drehen</button></div>'
              '<p class="fz-hinweis">Ziehen zum Drehen, Mausrad oder zwei Finger zum Zoomen. Die Lackierung des Ministeriums wird auf das Modell aufgebracht.</p>'
              + _modell_nachweis(f["typ"]) +
              f'<script type="application/json" id="fz-daten">{json.dumps(daten).replace("</", "<\\/")}</script>'
              f'<script type="importmap">{{"imports":{{"three":"{PFAD}3d/three.module.min.js"}}}}</script>'
              f'<script type="module" src="{PFAD}3d/fahrzeug.js?v={v}"></script>')
    blatt = ([("Ministerium", b["name"]), ("Fahrzeug", typ[0]), ("Bereich", f"{typ[1]} · {typ[2]}")] + ([("Kennung", f["kennung"])] if f["kennung"] else [])
             + ([("Taufname", f["name"])] if f["name"] else []) + list(typ[4]) + [("Festgelegt", f"{datum(f['erstellt'])} durch {f['autor_name']}")])
    dl = '<dl class="rg-daten">' + "".join(f"<dt>{esc(a)}</dt><dd>{esc(w)}</dd>" for a, w in blatt) + "</dl>"
    inhalt = (FZ_CSS + kopf(typ[0], esc(typ[3]), b.get("kurz") or b["name"]) + wahlleiste
              + f'<div class="fz-raster2"><div>{buehne}</div><div><h2 style="margin-top:0">Datenblatt</h2>{dl}'
              + (f'<p><a class="btn zweit" href="{PFAD}fahrzeuge/?ressort={b["schl"]}&modal=fz-modal#festlegen">{ic("pencil")}Fahrzeuge verwalten</a></p>' if ist_redaktion(k) else "")
              + f'<p><a class="btn zweit" href="{ministerium_url(b)}">{ic("landmark")}Zum Ministerium</a></p></div></div>')
    return rahmen(request, k, typ[0], "r-fahrzeuge", inhalt, krumen=[("Regierungsfahrzeuge", PFAD + "fahrzeuge/"), (b.get("kurz") or b["name"], None)])


async def fahrzeug_festlegen(request):
    k, form = await post_pruefen(request, ist_redaktion)
    con = request.app["db"]
    alle, _ = ressorts()
    ressort, typ = form.get("ressort", ""), form.get("typ", "")
    if ressort not in {b["schl"] for b in alle} or typ not in KATALOG:
        weiter(PFAD + "fahrzeuge/?modal=fz-modal", f="Bitte Ministerium und Fahrzeug wählen.")
    if con.execute("SELECT COUNT(*) FROM regierung_fahrzeuge WHERE ressort=?", (ressort,)).fetchone()[0] >= 12:
        weiter(PFAD + "fahrzeuge/?modal=fz-modal", f="Höchstens 12 Fahrzeuge je Ministerium.")
    kennung = (form.get("kennung") or "").strip()[:20] or _fz_kennung(con, typ)
    con.execute("INSERT INTO regierung_fahrzeuge (ressort, typ, name, kennung, erstellt, autor_id, autor_name) VALUES (?,?,?,?,?,?,?)",
                (ressort, typ, (form.get("name") or "").strip()[:60], kennung, int(time.time()), k["id"], k["name"]))
    con.commit()
    weiter(f"{PFAD}fahrzeuge/{ressort}/", f"{KATALOG[typ][0]} festgelegt.")


async def fahrzeug_entfernen(request):
    k, _ = await post_pruefen(request, ist_redaktion)
    con = request.app["db"]
    con.execute("DELETE FROM regierung_fahrzeuge WHERE id=?", (request.match_info["id"],))
    con.commit()
    weiter(PFAD + "fahrzeuge/", "Fahrzeug entfernt.")


def registrieren(app):
    einrichten(app["db"])
    r = app.router
    r.add_get("/regierung", ohne_schraegstrich)
    r.add_get(PFAD, start)
    r.add_get(PFAD + "logo/{name}.png", logo)
    r.add_get(PFAD + "bild/{name}", bild)
    r.add_get(PFAD + "3d/{datei:.+}", drei_d)
    r.add_get(PFAD + "fahrzeuge/", fahrzeuge)
    r.add_post(PFAD + "fahrzeuge/festlegen", fahrzeug_festlegen)
    r.add_post(PFAD + "fahrzeuge/{id:\\d+}/entfernen", fahrzeug_entfernen)
    r.add_get(PFAD + "fahrzeuge/{schl:[a-z]+}/", fahrzeug_ansicht)
    r.add_get(PFAD + "aktuelles/", aktuelles)
    r.add_get(PFAD + "aktuelles/{id:\\d+}/", meldung)
    r.add_get(PFAD + "reichsregierung/", reichsregierung)
    r.add_get(PFAD + "reichsregierung/{id:[0-9a-z]+}/", kabinett_person)
    r.add_post(PFAD + "reichsregierung/{id:[0-9a-z]+}/lebenslauf", kabinett_lebenslauf)
    r.add_get(PFAD + "ministerien/", ministerien)
    r.add_get(PFAD + "organigramm/", organigramm)
    r.add_get(PFAD + "ressorts/", alt_ressorts)
    r.add_get(PFAD + "ressorts/{schl}/", alt_ressort)
    r.add_get(PFAD + "suche/", suche)
    r.add_get(PFAD + "intern/", intern)
    r.add_get(PFAD + "intern/neu/", intern_meldung)
    r.add_post(PFAD + "intern/neu/", intern_speichern)
    r.add_get(PFAD + "intern/{id:\\d+}/", intern_meldung)
    r.add_post(PFAD + "intern/{id:\\d+}/", intern_speichern)
    r.add_post(PFAD + "intern/{id:\\d+}/loeschen", intern_loeschen)


def registrieren_ministerien(app):
    """Unterseiten aller Ministerien ohne eigenes Modul. Erst NACH den Ministerien mit eigenem Modul (generalkonsulat) aufrufen,
    sonst fängt /regierung/{schl}/ deren Seiten ab."""
    r = app.router
    s = PFAD + "{schl:[a-z]+}/"
    r.add_get(s, ministerium_start)
    r.add_get(s + "aufgaben/", ministerium_aufgaben)
    r.add_get(s + "meldungen/", ministerium_meldungen)
    r.add_get(s + "meldungen/{id:\\d+}/", ministerium_meldung)
    r.add_get(s + "redaktion/", m_redaktion)
    r.add_get(s + "redaktion/neu/", m_redaktion_meldung)
    r.add_post(s + "redaktion/neu/", m_redaktion_speichern)
    r.add_get(s + "redaktion/{id:\\d+}/", m_redaktion_meldung)
    r.add_post(s + "redaktion/{id:\\d+}/", m_redaktion_speichern)
    r.add_post(s + "redaktion/{id:\\d+}/loeschen", m_redaktion_loeschen)
