"""Seiten des Dienstes im Design der öffentlichen Website (für normale Nutzer, unabhängig von der Amtsseite).

Kopf (Topbar mit Profilmenü, Hauptnavigation) und Fuß werden aus der ausgelieferten Startseite /var/www/imperium/index.html
übernommen (bei Änderung der Datei neu eingelesen), dazu <base href="/">, damit die relativen Links der Website stimmen.
Profilbereich (nginx: /profil/ → Dienst):
- /profil/                    Mein Profil: Discord-Konto, eigene Angaben aus der Bürgerakte, Wohnsitz, Verweise
- /profil/dokumente/          Meine Dokumente: eigene Pässe und Ausweise als Karten
- /profil/dokumente/<id>/     ein eigenes Dokument digital (passdigital.ansicht_html, Umblättern/Umdrehen)
"""
import html
import os
import re

from aiohttp import web

import amt
import anmeldung
import meldewesen

esc = html.escape
STARTSEITE = "/var/www/imperium/index.html"
PROFIL = "/profil/"
_CACHE = {"mtime": None}

CSS = """<style>
.pf-raster{display:grid;grid-template-columns:minmax(0,300px) minmax(0,1fr);gap:clamp(24px,4vw,56px);align-items:start}
@media (max-width:860px){.pf-raster{grid-template-columns:minmax(0,1fr)}}
.pf-karte{border:1px solid var(--rule);background:var(--white);padding:24px;border-radius:var(--radius)}
.pf-bild{width:96px;height:96px;border-radius:50%;object-fit:cover;display:block;background:var(--navy-100)}
.pf-initialen{width:96px;height:96px;border-radius:50%;display:grid;place-items:center;background:var(--navy-900);color:#fff;font:600 1.75rem/1 var(--serif)}
.pf-karte h2{font-size:1.5rem;margin:16px 0 2px}
.pf-karte .pf-klein{color:var(--muted);font-size:.875rem;margin:0}
.pf-links{list-style:none;margin:20px 0 0;padding:0;border-top:1px solid var(--rule)}
.pf-links li{border-bottom:1px solid var(--rule)}
.pf-links a,.pf-links button{display:flex;justify-content:space-between;align-items:center;width:100%;padding:12px 0;color:var(--ink);text-decoration:none;
 background:none;border:0;font:inherit;cursor:pointer;text-align:left}
.pf-links a:hover,.pf-links button:hover{color:var(--gold-600)}
.pf-links small{color:var(--muted)}
.pf-titel{font-size:clamp(1.3rem,2vw,1.55rem);margin:0 0 14px}
.pf-daten{display:grid;grid-template-columns:minmax(0,220px) minmax(0,1fr);margin:0 0 36px;border-top:1px solid var(--rule)}
.pf-daten dt,.pf-daten dd{margin:0;padding:11px 0;border-bottom:1px solid var(--rule)}
.pf-daten dt{color:var(--muted);font-size:.9375rem;padding-right:16px}
@media (max-width:520px){.pf-daten{grid-template-columns:minmax(0,1fr)}.pf-daten dt{border-bottom:0;padding-bottom:0}.pf-daten dd{padding-top:2px}}
.pf-hinweis{color:var(--muted);border-left:2px solid var(--gold-500);padding:4px 0 4px 14px;margin:0 0 36px}
.pf-doks{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px;margin:0 0 40px}
.pf-dok{display:block;border:1px solid var(--rule);background:var(--white);color:var(--ink);text-decoration:none;border-radius:var(--radius);
 transition:border-color .2s}
.pf-dok:hover{border-color:var(--rule-strong)}
.pf-dok .pf-vorschau{aspect-ratio:125/88;display:grid;place-items:center;position:relative;overflow:hidden;border-bottom:1px solid var(--rule)}
.pf-dok .pf-vorschau img{width:38%;height:auto}
.pf-dok .pf-vorschau span{position:absolute;bottom:9%;left:0;right:0;text-align:center;font:400 .6875rem/1 var(--serif);letter-spacing:.3em;text-transform:uppercase}
.pf-dok .pf-vorschau.karte{background:linear-gradient(135deg,#e6f1ec,#eef0f7 55%,#f3ecef)}
.pf-dok .pf-vorschau.karte i{position:absolute;inset:16% 12%;border:1px solid #9cc0b0;border-radius:6px;background:rgba(255,255,255,.35)}
.pf-dok .pf-text{padding:14px 16px 16px}
.pf-dok strong{display:block;font:500 1.25rem/1.2 var(--serif)}
.pf-dok .pf-nr{font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.06em;font-size:.875rem;color:var(--muted)}
.pf-dok .pf-stand{display:flex;justify-content:space-between;gap:8px;margin-top:10px;font-size:.875rem;color:var(--muted)}
.pf-ok{color:var(--success)}.pf-warn{color:var(--gold-600)}.pf-rot{color:var(--danger)}
.pf-alt{font-size:.9375rem;color:var(--muted)}
.pf-alt td,.pf-alt th{padding:8px 16px 8px 0;border-bottom:1px solid var(--rule);text-align:left;font-weight:400}
</style>"""


def _chrome():
    """(head-Teile, Seitenanfang bis vor <main>, Fußbereich) aus der Startseite der Website."""
    try:
        mt = os.path.getmtime(STARTSEITE)
    except OSError:
        mt = None
    if mt != _CACHE["mtime"]:
        try:
            h = open(STARTSEITE, encoding="utf-8").read()
            kopf = h[h.find("<head"):h.find("</head>")]
            teile = re.findall(r'<script>\(function\(\)\{try\{var t=localStorage.*?</script>|<link rel="(?:icon|apple-touch-icon|preload|stylesheet)"[^>]*>'
                               r'|<script src="assets/js/site\.js[^"]*" defer></script>', kopf, re.S)
            b = h.find(">", h.find("<body")) + 1
            anfang = h[b:h.find("<main")].replace(' aria-current="page"', "")
            fuss = h[h.find("<footer"):h.find("</footer>") + len("</footer>")]
            _CACHE.update(mtime=mt, head="\n".join(teile), anfang=anfang, fuss=fuss)
        except (OSError, ValueError):
            _CACHE.update(mtime=mt, head='<link rel="stylesheet" href="assets/css/site.css">', anfang="", fuss="")
    return _CACHE["head"], _CACHE["anfang"], _CACHE["fuss"]


def seite(titel, inhalt, extra_head=""):
    head, anfang, fuss = _chrome()
    return (f'<!doctype html><html lang="de"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><base href="/">'
            f'<title>{esc(titel)} – Imperium Germanicum</title><meta name="robots" content="noindex,nofollow">'
            f'<meta name="theme-color" content="#12183c">{head}{CSS}{extra_head}</head>'
            f'<body>{anfang}<main id="inhalt" tabindex="-1">{inhalt}</main>{fuss}</body></html>')


def kopf(titel, pfad, lead=""):
    """Seitenkopf mit Brotkrumen. pfad = [(Text, URL oder None)]."""
    kr = "".join(f'<li><a href="{esc(u)}">{esc(t)}</a></li>' if u else f'<li><span aria-current="page">{esc(t)}</span></li>' for t, u in pfad)
    return (f'<div class="page-head"><div class="wrap"><nav class="breadcrumb" aria-label="Brotkrumen"><ol>{kr}</ol></nav>'
            f'<h1>{esc(titel)}</h1>{f"<p class=lead>{lead}</p>" if lead else ""}</div></div>')


def antwort(titel, inhalt, extra_head=""):
    return web.Response(text=seite(titel, inhalt, extra_head), content_type="text/html", headers={"Cache-Control": "no-store"})


async def _konto(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    return k


def _initialen(name):
    t = [x for x in (name or "?").split() if x]
    return ((t[0][0] + (t[-1][0] if len(t) > 1 else "")) if t else "?").upper()


def _stand(p):
    s, t = meldewesen.pass_status(p)
    return {"gueltig": "pf-ok", "abgelaufen": "pf-warn"}.get(s, "pf-rot"), t


# ---------------------------------------------------------------- Mein Profil

async def profil(request):
    k = await _konto(request)
    con = request.app["db"]
    z = con.execute("SELECT * FROM amt_akten WHERE konto_id=? ORDER BY id DESC LIMIT 1", (k["id"],)).fetchone()
    n_doks = con.execute("SELECT COUNT(*) FROM pw_paesse WHERE konto_id=? AND status='gueltig'", (k["id"],)).fetchone()[0]
    bild = (f'<img class="pf-bild" src="{amt.BASIS}pass-foto/{esc(k["id"])}" alt="">' if k["avatar"]
            else f'<span class="pf-initialen" aria-hidden="true">{esc(_initialen(k["name"]))}</span>')
    import anmeldung as _a
    links = [(f"{PROFIL}dokumente/", "Meine Dokumente", f"{n_doks} gültig" if n_doks else "")]
    if k["mitglied"]:
        links.append((f"{amt.BASIS}postfach/", "Postfach", ""))
    if _a._amt_zugang(k):
        links.append((amt.BASIS, "Amtsseite", ""))
    li = "".join(f'<li><a href="{esc(u)}">{esc(t)}<small>{esc(z_)}</small></a></li>' for u, t, z_ in links)
    li += (f'<li><form method="post" action="/abmelden/"><input type="hidden" name="csrf" value="{esc(request["csrf"])}">'
           '<input type="hidden" name="weiter" value="/"><button type="submit">Abmelden</button></form></li>')
    karte = (f'<div class="pf-karte">{bild}<h2>{esc(k["name"])}</h2>'
             f'<p class="pf-klein">Über Discord angemeldet{" · Mitglied des Servers" if k["mitglied"] else ""}</p><ul class="pf-links">{li}</ul></div>')

    if z:
        daten = [("Name im Spiel", z["ic_name"] or "– noch nicht erfasst"), ("Status", amt.STATUS_AKTE.get(z["status"], z["status"])),
                 ("Geburtsdatum", z["ic_geburt"] or "–"), ("Geschlecht", z["geschlecht"] or "–"), ("Fraktion", z["fraktion"] or "–"),
                 ("Gesellschaftsschicht", z["schicht"] or "–"), ("Beruf / Position", z["position"] or z["beruf"] or "–"),
                 ("Aktenzeichen", amt.az_akte(z["id"]))]
        ws = meldewesen.wohnsitz(con, z["id"])
        if ws:
            daten.insert(4, ("Wohnsitz", "Ausland" if ws["art"] == "abmeldung" else ws["staat_name"]))
            if ws["anschrift"] and ws["art"] != "abmeldung":
                daten.insert(5, ("Anschrift", ws["anschrift"]))
        rechts = ('<h2 class="pf-titel">Meine Angaben im Reich</h2><dl class="pf-daten">'
                  + "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in daten) + "</dl>"
                  '<p class="pf-hinweis">Diese Angaben stammen aus deiner Bürgerakte bei der Reichsverwaltung. '
                  'Für Änderungen wende dich an die Reichsverwaltung.</p>')
    else:
        rechts = ('<h2 class="pf-titel">Meine Angaben im Reich</h2>'
                  '<p class="pf-hinweis">Für dich ist noch keine Bürgerakte angelegt. Sie entsteht mit der Einbürgerung oder Einreise '
                  'über die Reichsverwaltung.</p>')
    inhalt = (kopf("Mein Profil", [("Hauptseite", "/"), ("Mein Profil", None)])
              + f'<section class="section" style="padding-top:clamp(32px,5vw,64px)"><div class="wrap"><div class="pf-raster">'
              f'<div>{karte}</div><div>{rechts}</div></div></div></section>')
    return antwort("Mein Profil", inhalt)


# ---------------------------------------------------------------- Meine Dokumente

def _dok_karte(p):
    import passdruck
    kl, text = _stand(p)
    art = meldewesen.PASSARTEN[p["art"]][0]
    if p["art"] == "personalausweis":
        vorschau = '<div class="pf-vorschau karte"><i></i><span style="color:#2f5546">Personalausweis</span></div>'
    else:
        farbe = passdruck.HEFT.get(p["art"], passdruck.HEFT["reisepass"])[0]
        vorschau = (f'<div class="pf-vorschau" style="background:{farbe};color:{passdruck.GOLD}">'
                    f'<img src="{amt.BASIS}pass-bild/wappen_gold.png" alt=""><span>{esc(passdruck.HEFT[p["art"]][4])}</span></div>')
    return (f'<a class="pf-dok" href="{PROFIL}dokumente/{p["id"]}/">{vorschau}<div class="pf-text"><strong>{esc(art)}</strong>'
            f'<span class="pf-nr">{esc(p["nummer"])}</span><div class="pf-stand"><span class="{kl}">{esc(text)}</span>'
            f'<span>bis {meldewesen._datum(p["gueltig_bis"])}</span></div></div></a>')


async def dokumente(request):
    k = await _konto(request)
    con = request.app["db"]
    ps = con.execute("SELECT * FROM pw_paesse WHERE konto_id=? ORDER BY ausgestellt DESC", (k["id"],)).fetchall()
    aktuell = [p for p in ps if p["status"] == "gueltig"]
    frueher = [p for p in ps if p["status"] != "gueltig"]
    if aktuell:
        teil = '<div class="pf-doks">' + "".join(_dok_karte(p) for p in aktuell) + "</div>"
    else:
        teil = ('<p class="pf-hinweis">Für dich sind noch keine Ausweisdokumente ausgestellt. Pässe und Personalausweise stellt die '
                'Reichsverwaltung aus.</p>')
    if frueher:
        teil += ('<h2 class="pf-titel">Frühere Dokumente</h2><table class="pf-alt"><thead><tr><th>Art</th><th>Nummer</th><th>Stand</th></tr></thead><tbody>'
                 + "".join(f'<tr><td><a href="{PROFIL}dokumente/{p["id"]}/">{esc(meldewesen.PASSARTEN[p["art"]][0])}</a></td>'
                           f'<td>{esc(p["nummer"])}</td><td>{esc(_stand(p)[1])}{": " + esc(p["grund"]) if p["grund"] else ""}</td></tr>'
                           for p in frueher) + "</tbody></table>")
    inhalt = (kopf("Meine Dokumente", [("Hauptseite", "/"), ("Mein Profil", PROFIL), ("Meine Dokumente", None)],
                   "Deine Ausweisdokumente des Imperium Germanicum, digital zum Ansehen. Die Prüfung durch Zoll und Polizei erfolgt über den QR-Code.")
              + f'<section class="section" style="padding-top:clamp(32px,5vw,64px)"><div class="wrap">{teil}</div></section>')
    return antwort("Meine Dokumente", inhalt)


async def dokument(request):
    import passdigital
    k = await _konto(request)
    con = request.app["db"]
    i = request.match_info["id"]
    p = con.execute("SELECT * FROM pw_paesse WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not p or p["konto_id"] != k["id"]:
        raise web.HTTPNotFound(text="Dokument nicht gefunden.")
    pfad = [("Hauptseite", "/"), ("Mein Profil", PROFIL), ("Meine Dokumente", f"{PROFIL}dokumente/"), (meldewesen.PASSARTEN[p["art"]][0], None)]
    andere = con.execute("SELECT * FROM pw_paesse WHERE konto_id=? AND (status='gueltig' OR id=?) ORDER BY ausgestellt DESC",
                         (k["id"], p["id"])).fetchall()
    titel, inhalt, head = passdigital.ansicht_html(con, p, pfad, [(a, f"{PROFIL}dokumente/{a['id']}/") for a in andere],
                                                   request.query.get("seite") == "daten")
    return antwort(titel, inhalt, head)


def registrieren(app):
    app.router.add_get(PROFIL, profil)
    app.router.add_get(PROFIL + "dokumente/", dokumente)
    app.router.add_get(PROFIL + "dokumente/{id}/", dokument)
