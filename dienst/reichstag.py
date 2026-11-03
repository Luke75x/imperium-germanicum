"""Reichstag: Anträge, Sitzungen, Tagesordnung, Abstimmungsverhalten und Archiv.

    GET  /informationen/der-reichstag/intern/               Übersicht (Mitglieder des Reichstags)
    GET  …/intern/sitzung/<id>/                             Sitzung mit Tagesordnung, Abstimmung (Präsidium bearbeitet)
    GET  …/intern/antrag/<id>/                              Antrag mit Verlauf
    GET  …/intern/sitzungen/ | antraege/ | archiv/ | abstimmungsverhalten/   Reiter der Ansicht
    GET  …/intern/abgeordnete/<id>/                         Abstimmungsverhalten einer Person
    POST …/intern/sitzung-anlegen | sitzung/<id>/aktion | tagesordnung | abstimmung        (Präsidium)
    POST /intern-api/reichstag/antrag                       nur lokal (nginx leitet das nicht weiter): Bot-Befehl /antrag

Anträge reichen Abgeordnete mit /antrag im Discord ein (Bot → intern-api). Sitzungen werden im Anträge-Kanal angekündigt
(die Nachricht wird bei Änderungen der Tagesordnung aktualisiert); das Ergebnis einer beendeten Sitzung geht in den Beschlüsse-Kanal.
"""
import html
import logging
import re
import secrets
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiohttp import web

import anmeldung
import config
from seiten import seite

log = logging.getLogger("reichstag")
esc = html.escape
BERLIN = ZoneInfo("Europe/Berlin")

ROLLE_REICHSTAG = "1522700666856800447"
ROLLE_ABGEORDNETER = "1528931629819494454"
ROLLE_PRAESIDIUM = "1522701497413144776"
ROLLE_LANDESHERR = "1522701576295415969"
ROLLEN_MITGLIED = {ROLLE_REICHSTAG, ROLLE_ABGEORDNETER, ROLLE_PRAESIDIUM, ROLLE_LANDESHERR}
KANAL_ANTRAEGE = 1537203584289210479    # 📨｜anträge: Anträge und Sitzungsankündigungen
KANAL_BESCHLUESSE = 1548649707780313118  # 📁｜beschlüsse: Ergebnisse der Sitzungen
ERSTE_SITZUNG = 3                        # Sitzung 1 und 2 sind schon gehalten (siehe Beschlüsse-Kanal)
BASIS = "/informationen/der-reichstag/intern/"

STIMMEN = {"ja": "Ja", "nein": "Nein", "enthaltung": "Enthaltung", "abwesend": "Abwesend"}
ANTRAG_STATUS = {"eingebracht": "Eingebracht", "tagesordnung": "Auf der Tagesordnung", "angenommen": "Angenommen",
                 "abgelehnt": "Abgelehnt", "zurueckgezogen": "Zurückgezogen"}
SITZUNG_STATUS = {"angekuendigt": "Angekündigt", "laeuft": "Läuft", "beendet": "Beendet", "abgesagt": "Abgesagt"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS reichstag_sitzungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nummer INTEGER NOT NULL, titel TEXT NOT NULL, termin INTEGER NOT NULL,
    ort TEXT NOT NULL DEFAULT '', bemerkung TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'angekuendigt',
    erstellt_von TEXT NOT NULL, erstellt INTEGER NOT NULL, nachricht TEXT);
CREATE TABLE IF NOT EXISTS reichstag_antraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, titel TEXT NOT NULL, text TEXT NOT NULL, begruendung TEXT NOT NULL DEFAULT '',
    einreicher_id TEXT NOT NULL, einreicher_name TEXT NOT NULL, erstellt INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'eingebracht');
CREATE TABLE IF NOT EXISTS reichstag_tagesordnung (
    sitzung_id INTEGER NOT NULL REFERENCES reichstag_sitzungen(id), antrag_id INTEGER NOT NULL REFERENCES reichstag_antraege(id),
    position INTEGER NOT NULL, ergebnis TEXT, PRIMARY KEY (sitzung_id, antrag_id));
CREATE TABLE IF NOT EXISTS reichstag_stimmen (
    sitzung_id INTEGER NOT NULL, antrag_id INTEGER NOT NULL, konto_id TEXT NOT NULL, name TEXT NOT NULL, stimme TEXT NOT NULL,
    PRIMARY KEY (sitzung_id, antrag_id, konto_id));
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Rechte und Hilfen

def ist_mitglied(k):
    return bool(k) and (k["admin"] or bool(ROLLEN_MITGLIED & set(k["rollen"])))


def ist_praesidium(k):
    return bool(k) and (k["admin"] or ROLLE_PRAESIDIUM in k["rollen"])


def _basis(request):
    return ("/en" if request.path.startswith("/en/") else "") + BASIS


def _zeit(ts, mit_uhr=True):
    d = datetime.fromtimestamp(ts, BERLIN)
    return d.strftime("%d.%m.%Y, %H:%M Uhr" if mit_uhr else "%d.%m.%Y")


def _termin_lesen(text):
    try:
        return int(datetime.strptime(text, "%Y-%m-%dT%H:%M").replace(tzinfo=BERLIN).timestamp())
    except ValueError:
        return None


def _bereinigt(text, maximum):
    return " ".join(str(text or "").split()) if maximum <= 200 else str(text or "").strip()[:maximum]


async def _formular(request, pruefung):
    """Konto + Formulardaten mit gültigem csrf; wirft sonst die passende HTTP-Antwort."""
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + _basis(request))
    form = await request.post()
    if not pruefung(k):
        raise web.HTTPForbidden(text="Dafür fehlen dir die nötigen Rollen.")
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    return k, form


def _zaehlen(con, sitzung_id, antrag_id):
    z = dict.fromkeys(STIMMEN, 0)
    for r in con.execute("SELECT stimme, COUNT(*) n FROM reichstag_stimmen WHERE sitzung_id = ? AND antrag_id = ? GROUP BY stimme",
                         (sitzung_id, antrag_id)):
        z[r["stimme"]] = r["n"]
    return z


def _ergebnis_text(e):
    return {"angenommen": "Antrag angenommen", "abgelehnt": "Antrag abgelehnt", "vertagt": "Antrag vertagt",
            "zurueckgezogen": "Antrag zurückgezogen"}.get(e, "offen")


# ---------------------------------------------------------------- Discord

async def _sitzung_ankuendigen(app, sid, neu=False):
    """Schreibt oder aktualisiert die Ankündigung der Sitzung im Anträge-Kanal."""
    con, dc = app["db"], app["discord"]
    s = con.execute("SELECT * FROM reichstag_sitzungen WHERE id = ?", (sid,)).fetchone()
    top = con.execute("""SELECT a.id, a.titel FROM reichstag_tagesordnung t JOIN reichstag_antraege a ON a.id = t.antrag_id
                         WHERE t.sitzung_id = ? ORDER BY t.position""", (sid,)).fetchall()
    zeilen = [f"**{i}.** [{esc(a['titel'])}]({config.SITE_URL}{BASIS}antrag/{a['id']}/) (Antrag Nr. {a['id']})" for i, a in enumerate(top, 1)]
    beschr = f"**Termin:** <t:{s['termin']}:F> (<t:{s['termin']}:R>)\n"
    if s["ort"]:
        beschr += f"**Ort:** {s['ort']}\n"
    if s["bemerkung"]:
        beschr += f"\n{s['bemerkung']}\n"
    beschr += "\n**Tagesordnung**\n" + ("\n".join(zeilen) if zeilen else "_Noch keine Anträge auf der Tagesordnung._")
    if s["status"] == "abgesagt":
        beschr = "**Die Sitzung wurde abgesagt.**\n\n" + beschr
    embed = {"title": f"{s['nummer']}. Sitzung des Reichstages – {s['titel']}"[:256], "description": beschr[:4000], "color": 0x2E4A7D,
             "footer": {"text": "Der Reichstag des Imperium Germanicum"}, "url": f"{config.SITE_URL}{BASIS}sitzung/{sid}/"}
    if neu or not s["nachricht"]:
        inhalt = f"ACHTUNG <@&{ROLLE_LANDESHERR}> <@&{ROLLE_ABGEORDNETER}>\nEine Sitzung des Reichstages wurde angekündigt."
        mid = await dc.senden(KANAL_ANTRAEGE, {"content": inhalt, "embeds": [embed],
                                               "allowed_mentions": {"roles": [ROLLE_LANDESHERR, ROLLE_ABGEORDNETER]}})
        if mid:
            con.execute("UPDATE reichstag_sitzungen SET nachricht = ? WHERE id = ?", (mid, sid))
            con.commit()
    else:
        await dc.senden(KANAL_ANTRAEGE, {"embeds": [embed]}, nachricht=s["nachricht"])


async def _ergebnisse_melden(app, sid):
    con = app["db"]
    s = con.execute("SELECT * FROM reichstag_sitzungen WHERE id = ?", (sid,)).fetchone()
    bloecke = []
    for t in con.execute("""SELECT t.*, a.titel FROM reichstag_tagesordnung t JOIN reichstag_antraege a ON a.id = t.antrag_id
                            WHERE t.sitzung_id = ? ORDER BY t.position""", (sid,)):
        z = _zaehlen(con, sid, t["antrag_id"])
        bloecke.append(f"{t['titel']}\n{z['ja']}x Ja\n{z['nein']}x Nein\n{z['enthaltung']}x Enthaltung\n{_ergebnis_text(t['ergebnis'])}")
    kopf = f"Ergebnis der {s['nummer']}. Sitzung des Reichstages:\n\n"
    text = kopf + ("\n\n\n".join(bloecke) if bloecke else "Es wurden keine Anträge behandelt.")
    text += f"\n\n{config.SITE_URL}{BASIS}sitzung/{sid}/"
    while text:
        stueck, text = text[:1900], text[1900:]
        await app["discord"].senden(KANAL_BESCHLUESSE, {"content": stueck, "allowed_mentions": {"parse": []}})


# ---------------------------------------------------------------- Seiten

STIL = """<style>
.rt-nav{display:flex;flex-wrap:nowrap;gap:4px;margin:22px 0 0;border-bottom:1px solid var(--rule);overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.rt-nav::-webkit-scrollbar{display:none}
.rt-nav a{padding:12px 16px;font:600 .9rem var(--sans);color:var(--muted);text-decoration:none;border-bottom:3px solid transparent;margin-bottom:-1px;white-space:nowrap}
.rt-nav a:hover{color:var(--ink)}
.rt-nav a[aria-current]{color:var(--ink);border-bottom-color:var(--flag)}
.rt-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:0 0 30px}
.rt-stat{background:var(--white);border:1px solid var(--rule);padding:16px 18px;text-decoration:none;color:var(--ink)}
.rt-stat strong{display:block;font:600 2rem/1.1 var(--serif)}
.rt-stat span{font:.8125rem var(--sans);color:var(--muted)}
.rt-card{background:var(--white);border:1px solid var(--rule);padding:20px 22px;margin:0 0 18px}
.rt-card h2,.rt-card h3{margin-top:0}
.rt-sec{margin:34px 0 12px;font-size:1.3rem}
.rt-meta{display:flex;flex-wrap:wrap;gap:6px 22px;margin:0 0 12px;font:.9375rem var(--sans);color:var(--muted)}
.rt-meta b{color:var(--ink);font-weight:600}
.rt-badge{display:inline-block;padding:2px 9px;font:600 .72rem var(--sans);letter-spacing:.06em;text-transform:uppercase;border:1px solid var(--rule-strong);color:var(--muted);white-space:nowrap}
.rt-badge.ok{color:var(--success);background:var(--success-bg);border-color:transparent}
.rt-badge.nein{color:var(--danger);background:var(--danger-bg);border-color:transparent}
.rt-badge.aktiv{color:var(--ink);background:var(--flag);border-color:transparent}
.rt-top{list-style:none;margin:0;padding:0;counter-reset:top}
.rt-top li{display:grid;grid-template-columns:2.2em 1fr auto;gap:4px 12px;align-items:start;padding:12px 0;border-top:1px solid var(--rule);counter-increment:top}
.rt-top li:first-child{border-top:0}
.rt-top li::before{content:counter(top);font:600 1.3rem var(--serif);color:var(--muted)}
.rt-top .titel{font-weight:600}
.rt-top .zahlen{grid-column:2/4;font:.875rem var(--sans);color:var(--muted)}
.rt-top .werkzeug{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
.rt-panel{border:1px solid var(--rule);background:var(--paper);margin:0 0 18px}
.rt-panel>summary{cursor:pointer;padding:12px 18px;font:600 .95rem var(--sans)}
.rt-panel[open]>summary{border-bottom:1px solid var(--rule)}
.rt-panel>.rt-inhalt{padding:16px 18px}
.rt-filter{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
.rt-filter a{padding:5px 12px;border:1px solid var(--rule-strong);text-decoration:none;color:var(--ink);font:.875rem var(--sans)}
.rt-filter a[aria-current]{background:var(--ink);color:var(--paper)}
.form-inline{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0}
.rt-text{white-space:pre-line}
@media(max-width:700px){
.rt-stats{grid-template-columns:repeat(2,1fr);gap:10px}
.rt-stat{padding:12px 14px}.rt-stat strong{font-size:1.6rem}
.rt-card{padding:16px 16px}
.rt-top li{grid-template-columns:1.8em 1fr}.rt-top .werkzeug{grid-column:2;justify-content:flex-start}
.rt-top .werkzeug .btn{min-height:44px;min-width:44px}
.rt-stack thead{display:none}
.rt-stack table,.rt-stack tbody,.rt-stack tr,.rt-stack td{display:block;width:100%}
.rt-stack tr{border:1px solid var(--rule);background:var(--white);margin:0 0 12px;padding:6px 0}
.rt-stack td{border:0!important;padding:6px 14px;display:grid;grid-template-columns:7em minmax(0,1fr);gap:8px;overflow-wrap:anywhere}
.rt-stack td::before{content:attr(data-label);font:600 .7rem var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);padding-top:3px}
.rt-stack td[data-label=""]::before{content:none}.rt-stack td[data-label=""]{grid-template-columns:1fr}
.rt-panel select,.rt-card select,.rt-stack select,.form-inline select,.field select,.field input,.field textarea{min-height:44px;font-size:16px}
.rt-panel .btn,.rt-card .btn,.rt-stack .btn,.form-inline .btn{min-height:44px}
.form-inline{width:100%}.form-inline select{flex:1 1 12em;min-width:0}
.rt-filter a{padding:10px 14px}
}
</style>"""

TABS = (("", "Übersicht"), ("sitzungen/", "Sitzungen"), ("antraege/", "Anträge"), ("archiv/", "Archiv"), ("abstimmungsverhalten/", "Abstimmungsverhalten"))


def _rahmen(request, titel, eyebrow, inhalt, aktiv=None, brot=(), lead=""):
    """aktiv: Pfad des Reiters (siehe TABS); brot: weitere Brotkrumen [(Text, Adresse)] vor der Seite."""
    basis = _basis(request)
    krumen = '<li><a href="/">Hauptseite</a></li><li><a href="/informationen/der-reichstag/">Der Reichstag</a></li>'
    if aktiv == "":
        krumen += '<li><span aria-current="page">Interne Sitzungen</span></li>'
    else:
        krumen += f'<li><a href="{basis}">Interne Sitzungen</a></li>' + "".join(f'<li><a href="{u}">{esc(t)}</a></li>' for t, u in brot)
        krumen += f'<li><span aria-current="page">{esc(titel)}</span></li>'
    reiter = "".join(f'<a href="{basis}{p}"' + (' aria-current="page"' if p == aktiv else "") + f">{t}</a>" for p, t in TABS)
    kopf = (f'<div class="page-head"><div class="wrap"><nav class="breadcrumb" aria-label="Brotkrumen"><ol>{krumen}</ol></nav>'
            f'<span class="eyebrow">{esc(eyebrow)}</span><h1>{esc(titel)}</h1>'
            + (f'<p class="wiki-intro rt-lead">{lead}</p>' if lead else "")
            + f'<nav class="rt-nav" aria-label="Bereiche">{reiter}</nav></div></div>')
    meldung = {"ok": '<div class="form-status ok" role="status">Gespeichert.</div>',
               "fehler": '<div class="form-status err" role="status">Das ging nicht: ' + esc(request.query.get("t", "ungültige Eingabe")) + "</div>"
               }.get(request.query.get("m"), "")
    return web.Response(text=seite(titel, kopf + f'<div class="section"><div class="wrap">{meldung}{inhalt}</div></div>',
                                   konto=request["konto"], csrf=request["csrf"], pfad=request.path,
                                   kopf='<meta name="robots" content="noindex">' + STIL),
                        content_type="text/html", headers={"Cache-Control": "no-store"})


def _form(request, aktion, inhalt, klasse="form"):
    return (f'<form method="post" action="{_basis(request)}{aktion}" class="{klasse}">'
            f'<input type="hidden" name="csrf" value="{esc(request["csrf"])}">{inhalt}</form>')


def _tabelle(kopf, zeilen, leer="Keine Einträge."):
    if not zeilen:
        return f'<p class="callout">{esc(leer)}</p>'
    def beschriften(zeile):   # jede Zelle bekommt ihre Spaltenüberschrift (für die gestapelte Darstellung am Handy)
        i = iter(kopf)
        return re.sub(r"<td>", lambda m: f'<td data-label="{esc(re.sub("<[^>]+>", "", next(i, "")))}">', zeile)
    return ('<div class="table-scroll rt-stack"><table class="styles-table is-grid"><thead><tr>' + "".join(f"<th>{k}</th>" for k in kopf)
            + "</tr></thead><tbody>" + "".join(f"<tr>{beschriften(z)}</tr>" for z in zeilen) + "</tbody></table></div>")


def _td(*zellen):
    return "".join(f"<td>{z}</td>" for z in zellen)


def _panel(titel, inhalt, offen=False):
    return f'<details class="rt-panel"{" open" if offen else ""}><summary>{titel}</summary><div class="rt-inhalt">{inhalt}</div></details>'


def _badge(text, art=""):
    return f'<span class="rt-badge {art}">{esc(text)}</span>'


def _antrag_badge(status):
    return _badge(ANTRAG_STATUS[status], {"angenommen": "ok", "abgelehnt": "nein", "tagesordnung": "aktiv"}.get(status, ""))


def _sitzung_badge(status):
    return _badge(SITZUNG_STATUS[status], {"laeuft": "aktiv", "beendet": "ok", "abgesagt": "nein"}.get(status, ""))


def _ergebnis_badge(e):
    return _badge(_ergebnis_text(e).replace("Antrag ", "").capitalize() if e else "Offen", {"angenommen": "ok", "abgelehnt": "nein"}.get(e, ""))


def _top_liste(con, request, sid, werkzeug=False):
    """Tagesordnung einer Sitzung als nummerierte Liste (werkzeug: Knöpfe für das Präsidium)."""
    basis = _basis(request)
    punkte = []
    for t in con.execute("""SELECT t.*, a.titel, a.einreicher_name FROM reichstag_tagesordnung t JOIN reichstag_antraege a ON a.id = t.antrag_id
                            WHERE t.sitzung_id = ? ORDER BY t.position""", (sid,)):
        z = _zaehlen(con, sid, t["antrag_id"])
        zahlen = (f'{z["ja"]} Ja · {z["nein"]} Nein · {z["enthaltung"]} Enthaltung · {z["abwesend"]} abwesend'
                  if t["ergebnis"] else f'Antrag Nr. {t["antrag_id"]} · eingereicht von {esc(t["einreicher_name"])}')
        knoepfe = ""
        if werkzeug and not t["ergebnis"]:
            knoepfe = "".join(_form(request, "tagesordnung", f'<input type="hidden" name="sitzung" value="{sid}"><input type="hidden" name="antrag" value="{t["antrag_id"]}">'
                                    f'<button class="btn btn-line btn-small" name="aktion" value="{w}" title="{b}">{s}</button>', "form-inline")
                              for w, b, s in (("hoch", "Nach oben", "↑"), ("runter", "Nach unten", "↓"), ("weg", "Von der Tagesordnung entfernen", "Entfernen")))
        punkte.append(f'<li><div class="titel"><a href="{basis}antrag/{t["antrag_id"]}/">{esc(t["titel"])}</a> {_ergebnis_badge(t["ergebnis"]) if t["ergebnis"] else ""}</div>'
                      f'<div class="werkzeug">{knoepfe}</div><div class="zahlen">{zahlen}</div></li>')
    return f'<ol class="rt-top">{"".join(punkte)}</ol>' if punkte else '<p class="callout">Noch keine Anträge auf der Tagesordnung.</p>'


def _sitzung_form(request):
    return _form(request, "sitzung-anlegen", """
<div class="field"><label for="titel">Titel</label><input id="titel" name="titel" maxlength="100" value="Ordentliche Sitzung" required></div>
<div class="field"><label for="termin">Termin (Uhrzeit nach deutscher Zeit)</label><input id="termin" name="termin" type="datetime-local" required></div>
<div class="field"><label for="ort">Ort</label><input id="ort" name="ort" maxlength="100" value="🏯｜Plenarsaal"></div>
<div class="field"><label for="bem">Bemerkung (optional)</label><textarea id="bem" name="bemerkung" maxlength="1000" rows="3"></textarea></div>
<button class="btn btn-navy" type="submit">Sitzung ankündigen</button>
<p class="form-note">Die Ankündigung erscheint im Discord-Kanal der Anträge und benachrichtigt Landesherren und Abgeordnete.</p>""")


def _zuweisen(request, antrag_id, kommende):
    ziele = "".join(f'<option value="{s["id"]}">{s["nummer"]}. Sitzung ({_zeit(s["termin"], False)})</option>' for s in kommende)
    return _form(request, "tagesordnung", f'<input type="hidden" name="antrag" value="{antrag_id}"><input type="hidden" name="aktion" value="hinzu">'
                 f'<select name="sitzung" aria-label="Sitzung">{ziele}</select><button class="btn btn-navy btn-small">Zur Tagesordnung</button>', "form-inline")


MITGLIEDS_HINWEIS = "Die internen Sitzungen stehen den Mitgliedern des Reichstags offen (Abgeordnete, Landesherren, Präsidium)."


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def uebersicht(request):
    con, basis, k = request.app["db"], _basis(request), request["konto"]
    praes = ist_praesidium(k)
    kommende = con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('angekuendigt', 'laeuft') ORDER BY termin").fetchall()
    offene = con.execute("SELECT * FROM reichstag_antraege WHERE status = 'eingebracht' ORDER BY id").fetchall()
    beendet = con.execute("SELECT COUNT(*) FROM reichstag_sitzungen WHERE status = 'beendet'").fetchone()[0]
    angenommen = con.execute("SELECT COUNT(*) FROM reichstag_antraege WHERE status = 'angenommen'").fetchone()[0]
    stat = (f'<div class="rt-stats"><a class="rt-stat" href="{basis}sitzungen/"><strong>{len(kommende)}</strong><span>kommende Sitzungen</span></a>'
            f'<a class="rt-stat" href="{basis}antraege/?status=eingebracht"><strong>{len(offene)}</strong><span>Anträge im Eingang</span></a>'
            f'<a class="rt-stat" href="{basis}archiv/"><strong>{beendet}</strong><span>beendete Sitzungen</span></a>'
            f'<a class="rt-stat" href="{basis}antraege/?status=angenommen"><strong>{angenommen}</strong><span>angenommene Anträge</span></a></div>')
    inhalt = stat
    if kommende:
        s = kommende[0]
        inhalt += (f'<h2 class="rt-sec">Nächste Sitzung</h2><div class="rt-card"><h3><a href="{basis}sitzung/{s["id"]}/">{s["nummer"]}. Sitzung – {esc(s["titel"])}</a> {_sitzung_badge(s["status"])}</h3>'
                   f'<p class="rt-meta"><span><b>Termin</b> {_zeit(s["termin"])}</span>' + (f'<span><b>Ort</b> {esc(s["ort"])}</span>' if s["ort"] else "") + "</p>"
                   + (f'<p>{esc(s["bemerkung"])}</p>' if s["bemerkung"] else "") + "<h4>Tagesordnung</h4>" + _top_liste(con, request, s["id"])
                   + f'<p><a class="btn btn-line btn-small" href="{basis}sitzung/{s["id"]}/">Zur Sitzung</a></p></div>')
    else:
        inhalt += '<h2 class="rt-sec">Nächste Sitzung</h2><p class="callout">Zurzeit ist keine Sitzung angekündigt.</p>'
    zeilen = [_td(f'<a href="{basis}antrag/{a["id"]}/"><strong>Nr. {a["id"]}</strong> {esc(a["titel"])}</a>', esc(a["einreicher_name"]), _zeit(a["erstellt"], False),
                  _zuweisen(request, a["id"], kommende) if (praes and kommende) else "") for a in offene]
    inhalt += (f'<h2 class="rt-sec">Anträge im Eingang</h2>' + _tabelle(["Antrag", "Eingereicht von", "Eingang", "Tagesordnung" if praes else ""], zeilen, "Es liegen keine unbehandelten Anträge vor.")
               + '<p>Anträge reichen Abgeordnete im Discord mit dem Befehl <code>/antrag</code> ein.</p>')
    if praes:
        inhalt += f'<p><a class="btn btn-navy" href="{basis}sitzungen/#neu">Sitzung ankündigen</a></p>'
    return _rahmen(request, "Interne Sitzungen", "Für Mitglieder des Reichstages", inhalt, aktiv="",
                   lead="Sitzungen des Reichstags, eingebrachte Anträge und ihre Tagesordnung.")


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def sitzungen_seite(request):
    con, basis, k = request.app["db"], _basis(request), request["konto"]
    inhalt = '<h2 class="rt-sec" style="margin-top:0">Kommende Sitzungen</h2>'
    kommende = con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('angekuendigt', 'laeuft') ORDER BY termin").fetchall()
    for s in kommende:
        inhalt += (f'<div class="rt-card"><h3><a href="{basis}sitzung/{s["id"]}/">{s["nummer"]}. Sitzung – {esc(s["titel"])}</a> {_sitzung_badge(s["status"])}</h3>'
                   f'<p class="rt-meta"><span><b>Termin</b> {_zeit(s["termin"])}</span>' + (f'<span><b>Ort</b> {esc(s["ort"])}</span>' if s["ort"] else "") + "</p>"
                   + _top_liste(con, request, s["id"]) + "</div>")
    if not kommende:
        inhalt += '<p class="callout">Zurzeit ist keine Sitzung angekündigt.</p>'
    if ist_praesidium(k):
        inhalt += f'<div id="neu">{_panel("Neue Sitzung ankündigen", _sitzung_form(request), offen=True)}</div>'
    vergangene = [_td(f'<a href="{basis}sitzung/{s["id"]}/"><strong>{s["nummer"]}. Sitzung</strong></a> {esc(s["titel"])}', _zeit(s["termin"], False), _sitzung_badge(s["status"]))
                  for s in con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('beendet', 'abgesagt') ORDER BY termin DESC LIMIT 10")]
    inhalt += '<h2 class="rt-sec">Zuletzt</h2>' + _tabelle(["Sitzung", "Datum", "Stand"], vergangene, "Noch keine Sitzung beendet.") + f'<p><a href="{basis}archiv/">Zum Archiv</a></p>'
    return _rahmen(request, "Sitzungen", "Reichstag", inhalt, aktiv="sitzungen/")


FILTER = (("", "Alle"), ("eingebracht", "Im Eingang"), ("tagesordnung", "Auf der Tagesordnung"), ("angenommen", "Angenommen"), ("abgelehnt", "Abgelehnt"), ("zurueckgezogen", "Zurückgezogen"))


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def antraege_seite(request):
    con, basis, k = request.app["db"], _basis(request), request["konto"]
    wahl = request.query.get("status", "")
    wahl = wahl if wahl in ANTRAG_STATUS else ""
    kommende = con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('angekuendigt', 'laeuft') ORDER BY termin").fetchall()
    filt = "".join(f'<a href="{basis}antraege/' + (f"?status={w}" if w else "") + '"' + (' aria-current="page"' if w == wahl else "") + f">{b}</a>" for w, b in FILTER)
    zeilen = []
    for a in con.execute("SELECT * FROM reichstag_antraege " + ("WHERE status = ? " if wahl else "") + "ORDER BY id DESC", (wahl,) if wahl else ()):
        zuw = _zuweisen(request, a["id"], kommende) if (ist_praesidium(k) and a["status"] == "eingebracht" and kommende) else ""
        zeilen.append(_td(f'<a href="{basis}antrag/{a["id"]}/"><strong>Nr. {a["id"]}</strong> {esc(a["titel"])}</a>', esc(a["einreicher_name"]),
                          _zeit(a["erstellt"], False), _antrag_badge(a["status"]) + (f"<br>{zuw}" if zuw else "")))
    inhalt = (f'<div class="rt-filter">{filt}</div>' + _tabelle(["Antrag", "Eingereicht von", "Eingang", "Stand"], zeilen, "Keine Anträge in dieser Ansicht.")
              + '<p>Anträge reichen Abgeordnete im Discord mit dem Befehl <code>/antrag</code> ein.</p>')
    return _rahmen(request, "Anträge", "Reichstag", inhalt, aktiv="antraege/")


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def antrag_seite(request):
    con, basis = request.app["db"], _basis(request)
    a = con.execute("SELECT * FROM reichstag_antraege WHERE id = ?", (request.match_info["id"],)).fetchone() if request.match_info["id"].isdigit() else None
    if not a:
        raise web.HTTPNotFound()
    inhalt = (f'<div class="rt-card"><p class="rt-meta"><span><b>Stand</b> {_antrag_badge(a["status"])}</span><span><b>Eingereicht von</b> {esc(a["einreicher_name"])}</span>'
              f'<span><b>Eingang</b> {_zeit(a["erstellt"])}</span></p><h3>Antragstext</h3><div class="rt-text">{esc(a["text"])}</div>'
              + (f'<h3 style="margin-top:20px">Begründung</h3><div class="rt-text">{esc(a["begruendung"])}</div>' if a["begruendung"] else "") + "</div>")
    zeilen = []
    for t in con.execute("""SELECT t.*, s.nummer, s.termin FROM reichstag_tagesordnung t JOIN reichstag_sitzungen s ON s.id = t.sitzung_id
                            WHERE t.antrag_id = ? ORDER BY s.termin""", (a["id"],)):
        z = _zaehlen(con, t["sitzung_id"], a["id"])
        zeilen.append(_td(f'<a href="{basis}sitzung/{t["sitzung_id"]}/">{t["nummer"]}. Sitzung</a>', _zeit(t["termin"], False),
                          f'{z["ja"]} Ja · {z["nein"]} Nein · {z["enthaltung"]} Enth. · {z["abwesend"]} abw.' if t["ergebnis"] else "–", _ergebnis_badge(t["ergebnis"])))
    inhalt += '<h2 class="rt-sec">Verlauf</h2>' + _tabelle(["Sitzung", "Datum", "Abstimmung", "Ergebnis"], zeilen, "Der Antrag wurde noch keiner Sitzung zugeordnet.")
    return _rahmen(request, f"Antrag Nr. {a['id']}: {a['titel']}", "Antrag", inhalt, aktiv="antraege/", brot=[("Anträge", basis + "antraege/")])


async def _abgeordnete(request):
    """Stimmberechtigte (Mitglieder mit einer Reichstags-Rolle), nach Namen sortiert."""
    return sorted((m for m in await request.app["discord"].mitglieder() if ROLLEN_MITGLIED & set(m["rollen"])), key=lambda m: m["name"].lower())


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def sitzung_seite(request):
    con, basis, k = request.app["db"], _basis(request), request["konto"]
    sid = request.match_info["id"]
    s = con.execute("SELECT * FROM reichstag_sitzungen WHERE id = ?", (sid,)).fetchone() if sid.isdigit() else None
    if not s:
        raise web.HTTPNotFound()
    praes = ist_praesidium(k)
    offen = s["status"] in ("angekuendigt", "laeuft")
    top = con.execute("SELECT * FROM reichstag_tagesordnung WHERE sitzung_id = ? ORDER BY position", (s["id"],)).fetchall()
    inhalt = (f'<div class="rt-card"><p class="rt-meta"><span><b>Stand</b> {_sitzung_badge(s["status"])}</span><span><b>Termin</b> {_zeit(s["termin"])}</span>'
              + (f'<span><b>Ort</b> {esc(s["ort"])}</span>' if s["ort"] else "") + "</p>" + (f'<div class="rt-text">{esc(s["bemerkung"])}</div>' if s["bemerkung"] else ""))
    if praes and offen:
        knoepfe = ""
        if s["status"] == "angekuendigt":
            knoepfe += '<button class="btn btn-navy btn-small" name="aktion" value="eroeffnen">Sitzung eröffnen</button>'
        if s["status"] == "laeuft":
            knoepfe += '<button class="btn btn-navy btn-small" name="aktion" value="beenden">Sitzung beenden und Ergebnis verkünden</button>'
        knoepfe += '<button class="btn btn-line btn-small" name="aktion" value="absagen">Sitzung absagen</button>'
        inhalt += '<div style="margin-top:14px">' + _form(request, f"sitzung/{s['id']}/aktion", knoepfe, "form-inline") + "</div>"
    inhalt += "</div>"

    inhalt += '<h2 class="rt-sec">Tagesordnung</h2><div class="rt-card">' + _top_liste(con, request, s["id"], werkzeug=praes and offen) + "</div>"
    if praes and offen:
        frei = con.execute("SELECT id, titel FROM reichstag_antraege WHERE status = 'eingebracht' ORDER BY id").fetchall()
        if frei:
            inhalt += _panel("Antrag zur Tagesordnung hinzufügen", _form(
                request, "tagesordnung", f'<input type="hidden" name="sitzung" value="{s["id"]}"><input type="hidden" name="aktion" value="hinzu">'
                '<select name="antrag" aria-label="Antrag">' + "".join(f'<option value="{a["id"]}">Nr. {a["id"]} – {esc(a["titel"][:80])}</option>' for a in frei)
                + '</select><button class="btn btn-navy btn-small">Hinzufügen</button>', "form-inline"))

    if praes and s["status"] == "laeuft":
        voters = await _abgeordnete(request)
        titel = {a["id"]: a["titel"] for a in con.execute("SELECT id, titel FROM reichstag_antraege")}
        panels = ""
        for t in top:
            if t["ergebnis"]:
                continue
            zeilen = "".join(f'<tr><td>{esc(m["name"])}</td><td><select name="s_{m["id"]}" aria-label="Stimme von {esc(m["name"])}"><option value="">–</option>'
                             + "".join(f'<option value="{w}">{b}</option>' for w, b in STIMMEN.items()) + "</select></td></tr>" for m in voters)
            aid = t["antrag_id"]
            panels += _panel(f'Abstimmung: {esc(titel[aid])}', _form(
                request, "abstimmung", f'<input type="hidden" name="sitzung" value="{s["id"]}"><input type="hidden" name="antrag" value="{aid}">'
                f'<div class="table-scroll"><table class="styles-table is-grid"><thead><tr><th>Abgeordnete/r</th><th>Stimme</th></tr></thead><tbody>{zeilen}</tbody></table></div>'
                f'<div class="field"><label for="erg-{aid}">Ergebnis</label><select id="erg-{aid}" name="ergebnis">'
                '<option value="auto">Nach den Stimmen (mehr Ja als Nein = angenommen)</option><option value="vertagt">Vertagt</option>'
                '<option value="zurueckgezogen">Antrag zurückgezogen</option></select></div>'
                '<button class="btn btn-navy" type="submit">Abstimmung speichern</button>'), offen=len(top) == 1)
        if panels:
            inhalt += '<h2 class="rt-sec">Abstimmungen erfassen</h2>' + panels

    fertig = [t for t in top if t["ergebnis"]]
    if fertig:
        stimmen = {(r["antrag_id"], r["konto_id"]): r["stimme"] for r in con.execute("SELECT * FROM reichstag_stimmen WHERE sitzung_id = ?", (s["id"],))}
        namen = {r["konto_id"]: r["name"] for r in con.execute("SELECT DISTINCT konto_id, name FROM reichstag_stimmen WHERE sitzung_id = ?", (s["id"],))}
        kopf = ["Abgeordnete/r"] + [f'Nr. {t["antrag_id"]}' for t in fertig]
        zeilen = [_td(f'<a href="{basis}abgeordnete/{kid}/">{esc(n)}</a>', *[STIMMEN.get(stimmen.get((t["antrag_id"], kid)), "–") for t in fertig])
                  for kid, n in sorted(namen.items(), key=lambda x: x[1].lower())]
        inhalt += '<h2 class="rt-sec">Abstimmungsverhalten dieser Sitzung</h2>' + _tabelle(kopf, zeilen)
    return _rahmen(request, f"{s['nummer']}. Sitzung – {s['titel']}", "Sitzung des Reichstages", inhalt, aktiv="sitzungen/", brot=[("Sitzungen", basis + "sitzungen/")])


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def archiv(request):
    con, basis = request.app["db"], _basis(request)
    zeilen = []
    for s in con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('beendet', 'abgesagt') ORDER BY termin DESC"):
        erg = [f'{esc(t["titel"])} {_ergebnis_badge(t["ergebnis"])}'
               for t in con.execute("""SELECT t.ergebnis, a.titel FROM reichstag_tagesordnung t JOIN reichstag_antraege a ON a.id = t.antrag_id
                                       WHERE t.sitzung_id = ? ORDER BY t.position""", (s["id"],)) if t["ergebnis"]]
        zeilen.append(_td(f'<a href="{basis}sitzung/{s["id"]}/"><strong>{s["nummer"]}. Sitzung</strong></a><br>{esc(s["titel"])}', _zeit(s["termin"], False),
                          _badge("Abgesagt", "nein") if s["status"] == "abgesagt" else ("<br>".join(erg) or "keine Anträge behandelt")))
    inhalt = '<h2 class="rt-sec" style="margin-top:0">Beendete Sitzungen</h2>' + _tabelle(["Sitzung", "Datum", "Behandelte Anträge"], zeilen, "Noch keine Sitzung beendet.")
    antr = [_td(f'<a href="{basis}antrag/{a["id"]}/"><strong>Nr. {a["id"]}</strong> {esc(a["titel"])}</a>', esc(a["einreicher_name"]), _antrag_badge(a["status"]))
            for a in con.execute("SELECT * FROM reichstag_antraege WHERE status IN ('angenommen', 'abgelehnt', 'zurueckgezogen') ORDER BY id DESC")]
    inhalt += '<h2 class="rt-sec">Entschiedene Anträge</h2>' + _tabelle(["Antrag", "Eingereicht von", "Stand"], antr, "Noch kein Antrag entschieden.")
    inhalt += f'<p><a class="btn btn-line" href="{basis}abstimmungsverhalten/">Abstimmungsverhalten der Abgeordneten</a></p>'
    return _rahmen(request, "Archiv", "Reichstag", inhalt, aktiv="archiv/")


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def verhalten_seite(request):
    con, basis = request.app["db"], _basis(request)
    zeilen = []
    for r in con.execute("""SELECT konto_id, MAX(name) name, SUM(stimme='ja') ja, SUM(stimme='nein') nein, SUM(stimme='enthaltung') enth,
                                   SUM(stimme='abwesend') abw FROM reichstag_stimmen GROUP BY konto_id ORDER BY name COLLATE NOCASE"""):
        zeilen.append(_td(f'<a href="{basis}abgeordnete/{r["konto_id"]}/">{esc(r["name"])}</a>', str(r["ja"]), str(r["nein"]), str(r["enth"]), str(r["abw"])))
    inhalt = (_tabelle(["Abgeordnete/r", "Ja", "Nein", "Enthaltung", "Abwesend"], zeilen, "Noch keine Abstimmung erfasst.")
              + '<p class="form-note">Gezählt werden alle erfassten Abstimmungen beendeter und laufender Sitzungen.</p>')
    return _rahmen(request, "Abstimmungsverhalten", "Reichstag", inhalt, aktiv="abstimmungsverhalten/")


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def abgeordneter_seite(request):
    con, basis = request.app["db"], _basis(request)
    kid = request.match_info["id"]
    rows = con.execute("""SELECT st.*, s.nummer, s.termin, a.titel, t.ergebnis FROM reichstag_stimmen st
                          JOIN reichstag_sitzungen s ON s.id = st.sitzung_id JOIN reichstag_antraege a ON a.id = st.antrag_id
                          JOIN reichstag_tagesordnung t ON t.sitzung_id = st.sitzung_id AND t.antrag_id = st.antrag_id
                          WHERE st.konto_id = ? ORDER BY s.termin DESC, t.position""", (kid,)).fetchall()
    if not rows:
        raise web.HTTPNotFound()
    zeilen = [_td(f'<a href="{basis}sitzung/{r["sitzung_id"]}/">{r["nummer"]}. Sitzung</a>', _zeit(r["termin"], False),
                  f'<a href="{basis}antrag/{r["antrag_id"]}/">{esc(r["titel"])}</a>', f'<strong>{STIMMEN[r["stimme"]]}</strong>', _ergebnis_badge(r["ergebnis"]))
              for r in rows]
    eigene = [_td(f'<a href="{basis}antrag/{a["id"]}/">Nr. {a["id"]} {esc(a["titel"])}</a>', _antrag_badge(a["status"]))
              for a in con.execute("SELECT * FROM reichstag_antraege WHERE einreicher_id = ? ORDER BY id DESC", (kid,))]
    inhalt = ('<h2 class="rt-sec" style="margin-top:0">Abstimmungen</h2>' + _tabelle(["Sitzung", "Datum", "Antrag", "Stimme", "Ergebnis"], zeilen)
              + '<h2 class="rt-sec">Eingereichte Anträge</h2>' + _tabelle(["Antrag", "Stand"], eigene, "Keine Anträge eingereicht."))
    return _rahmen(request, rows[0]["name"], "Abstimmungsverhalten", inhalt, aktiv="abstimmungsverhalten/", brot=[("Abstimmungsverhalten", basis + "abstimmungsverhalten/")])


# ---------------------------------------------------------------- Aktionen (Präsidium)

def _zurueck(request, ziel, ok=True, grund=""):
    q = "?m=ok" if ok else "?m=fehler&t=" + quote(grund)
    raise web.HTTPSeeOther(_basis(request) + ziel + q)


async def sitzung_anlegen(request):
    k, form = await _formular(request, ist_praesidium)
    titel, ort, bem = _bereinigt(form.get("titel"), 100), _bereinigt(form.get("ort"), 100), _bereinigt(form.get("bemerkung"), 1000)
    termin = _termin_lesen(str(form.get("termin", "")))
    if not titel or termin is None:
        _zurueck(request, "sitzungen/", False, "Titel und Termin fehlen")
    con = request.app["db"]
    nummer = max((con.execute("SELECT MAX(nummer) FROM reichstag_sitzungen").fetchone()[0] or ERSTE_SITZUNG - 1) + 1, ERSTE_SITZUNG)
    cur = con.execute("INSERT INTO reichstag_sitzungen (nummer, titel, termin, ort, bemerkung, erstellt_von, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (nummer, titel, termin, ort, bem, k["id"], int(time.time())))
    con.commit()
    await _sitzung_ankuendigen(request.app, cur.lastrowid, neu=True)
    _zurueck(request, f"sitzung/{cur.lastrowid}/")


async def sitzung_aktion(request):
    k, form = await _formular(request, ist_praesidium)
    con = request.app["db"]
    sid = request.match_info["id"]
    s = con.execute("SELECT * FROM reichstag_sitzungen WHERE id = ?", (sid,)).fetchone() if sid.isdigit() else None
    aktion = form.get("aktion")
    if not s:
        raise web.HTTPNotFound()
    ziel = f"sitzung/{s['id']}/"
    if aktion == "eroeffnen" and s["status"] == "angekuendigt":
        con.execute("UPDATE reichstag_sitzungen SET status = 'laeuft' WHERE id = ?", (s["id"],))
    elif aktion in ("beenden", "absagen") and s["status"] in ("angekuendigt", "laeuft"):
        if aktion == "beenden" and s["status"] != "laeuft":
            _zurueck(request, ziel, False, "Die Sitzung ist noch nicht eröffnet")
        for t in con.execute("SELECT * FROM reichstag_tagesordnung WHERE sitzung_id = ? AND ergebnis IS NULL", (s["id"],)).fetchall():
            if aktion == "beenden":   # nicht behandelt → vertagt
                con.execute("UPDATE reichstag_tagesordnung SET ergebnis = 'vertagt' WHERE sitzung_id = ? AND antrag_id = ?", (s["id"], t["antrag_id"]))
            else:                     # abgesagt → Anträge zurück in den Eingang, Zeile entfällt
                con.execute("DELETE FROM reichstag_tagesordnung WHERE sitzung_id = ? AND antrag_id = ?", (s["id"], t["antrag_id"]))
            con.execute("UPDATE reichstag_antraege SET status = 'eingebracht' WHERE id = ?", (t["antrag_id"],))
        con.execute("UPDATE reichstag_sitzungen SET status = ? WHERE id = ?", ("beendet" if aktion == "beenden" else "abgesagt", s["id"]))
        con.commit()
        if aktion == "beenden":
            await _ergebnisse_melden(request.app, s["id"])
        await _sitzung_ankuendigen(request.app, s["id"])
        _zurueck(request, ziel)
    else:
        _zurueck(request, ziel, False, "Aktion nicht möglich")
    con.commit()
    await _sitzung_ankuendigen(request.app, s["id"])
    _zurueck(request, ziel)


async def tagesordnung(request):
    k, form = await _formular(request, ist_praesidium)
    con = request.app["db"]
    sid, aid, aktion = str(form.get("sitzung", "")), str(form.get("antrag", "")), form.get("aktion")
    s = con.execute("SELECT * FROM reichstag_sitzungen WHERE id = ?", (sid,)).fetchone() if sid.isdigit() else None
    a = con.execute("SELECT * FROM reichstag_antraege WHERE id = ?", (aid,)).fetchone() if aid.isdigit() else None
    if not s or not a or s["status"] not in ("angekuendigt", "laeuft"):
        _zurueck(request, "", False, "Sitzung oder Antrag nicht gefunden")
    ziel = f"sitzung/{s['id']}/"
    t = con.execute("SELECT * FROM reichstag_tagesordnung WHERE sitzung_id = ? AND antrag_id = ?", (s["id"], a["id"])).fetchone()
    if aktion == "hinzu":
        if a["status"] != "eingebracht":
            _zurueck(request, ziel, False, "Der Antrag ist schon auf einer Tagesordnung oder entschieden")
        pos = (con.execute("SELECT MAX(position) FROM reichstag_tagesordnung WHERE sitzung_id = ?", (s["id"],)).fetchone()[0] or 0) + 1
        con.execute("INSERT OR REPLACE INTO reichstag_tagesordnung (sitzung_id, antrag_id, position) VALUES (?, ?, ?)", (s["id"], a["id"], pos))
        con.execute("UPDATE reichstag_antraege SET status = 'tagesordnung' WHERE id = ?", (a["id"],))
    elif aktion == "weg" and t and not t["ergebnis"]:
        con.execute("DELETE FROM reichstag_tagesordnung WHERE sitzung_id = ? AND antrag_id = ?", (s["id"], a["id"]))
        con.execute("DELETE FROM reichstag_stimmen WHERE sitzung_id = ? AND antrag_id = ?", (s["id"], a["id"]))
        con.execute("UPDATE reichstag_antraege SET status = 'eingebracht' WHERE id = ?", (a["id"],))
    elif aktion in ("hoch", "runter") and t:
        folge = [r["antrag_id"] for r in con.execute("SELECT antrag_id FROM reichstag_tagesordnung WHERE sitzung_id = ? ORDER BY position", (s["id"],))]
        i, j = folge.index(a["id"]), folge.index(a["id"]) + (-1 if aktion == "hoch" else 1)
        if 0 <= j < len(folge):
            folge[i], folge[j] = folge[j], folge[i]
        for n, antrag_id in enumerate(folge, 1):
            con.execute("UPDATE reichstag_tagesordnung SET position = ? WHERE sitzung_id = ? AND antrag_id = ?", (n, s["id"], antrag_id))
    else:
        _zurueck(request, ziel, False, "Aktion nicht möglich")
    con.commit()
    await _sitzung_ankuendigen(request.app, s["id"])
    _zurueck(request, ziel)


async def abstimmung(request):
    k, form = await _formular(request, ist_praesidium)
    con = request.app["db"]
    sid, aid = str(form.get("sitzung", "")), str(form.get("antrag", ""))
    t = con.execute("SELECT t.*, s.status FROM reichstag_tagesordnung t JOIN reichstag_sitzungen s ON s.id = t.sitzung_id WHERE t.sitzung_id = ? AND t.antrag_id = ?",
                    (sid, aid)).fetchone() if sid.isdigit() and aid.isdigit() else None
    if not t or t["status"] != "laeuft" or t["ergebnis"]:
        _zurueck(request, "", False, "Abstimmung nicht möglich (Sitzung eröffnet?)")
    ziel = f"sitzung/{t['sitzung_id']}/"
    namen = {m["id"]: m["name"] for m in await request.app["discord"].mitglieder()}
    con.execute("DELETE FROM reichstag_stimmen WHERE sitzung_id = ? AND antrag_id = ?", (t["sitzung_id"], t["antrag_id"]))
    for feld, wert in form.items():
        if feld.startswith("s_") and wert in STIMMEN and feld[2:] in namen:
            con.execute("INSERT INTO reichstag_stimmen VALUES (?, ?, ?, ?, ?)", (t["sitzung_id"], t["antrag_id"], feld[2:], namen[feld[2:]], wert))
    z = _zaehlen(con, t["sitzung_id"], t["antrag_id"])
    wahl = form.get("ergebnis", "auto")
    if wahl in ("vertagt", "zurueckgezogen"):
        ergebnis = wahl
    elif z["ja"] + z["nein"] == 0:
        con.rollback()
        _zurueck(request, ziel, False, "Es sind keine Ja- oder Nein-Stimmen eingetragen")
    else:
        ergebnis = "angenommen" if z["ja"] > z["nein"] else "abgelehnt"
    con.execute("UPDATE reichstag_tagesordnung SET ergebnis = ? WHERE sitzung_id = ? AND antrag_id = ?", (ergebnis, t["sitzung_id"], t["antrag_id"]))
    con.execute("UPDATE reichstag_antraege SET status = ? WHERE id = ?", ("eingebracht" if ergebnis == "vertagt" else ergebnis, t["antrag_id"]))
    con.commit()
    _zurueck(request, ziel)


# ---------------------------------------------------------------- Anträge aus dem Discord (Bot-Befehl /antrag)

async def api_antrag(request):
    """Nur vom Bot auf demselben Rechner aufgerufen (mit dem Bot-Token); nginx leitet diesen Pfad nicht weiter."""
    if not secrets.compare_digest(request.headers.get("X-Bot-Token", ""), request.app["discord"].bot_token):
        raise web.HTTPForbidden()
    d = await request.json()
    titel, text, grund = _bereinigt(d.get("titel"), 150), str(d.get("text") or "").strip()[:2500], str(d.get("begruendung") or "").strip()[:1000]
    dc, con = request.app["discord"], request.app["db"]
    try:
        k = await dc.konto_neu(str(d.get("konto_id", "")))
    except Exception:
        return web.json_response({"ok": False, "fehler": "Konto nicht gefunden."})
    if not ist_mitglied(k):
        return web.json_response({"ok": False, "fehler": "Anträge können nur Abgeordnete und Landesherren des Reichstags einreichen."})
    if not titel or not text:
        return web.json_response({"ok": False, "fehler": "Titel und Antragstext sind nötig."})
    cur = con.execute("INSERT INTO reichstag_antraege (titel, text, begruendung, einreicher_id, einreicher_name, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                      (titel, text, grund, k["id"], k["name"], int(time.time())))
    con.commit()
    nr, url = cur.lastrowid, f"{config.SITE_URL}{BASIS}antrag/{cur.lastrowid}/"
    embed = {"title": f"Antrag Nr. {nr}: {titel}"[:256], "description": text, "color": 0x2E4A7D, "url": url,
             "author": {"name": k["name"]}, "footer": {"text": "Antrag an den Reichstag"}}
    if grund:
        embed["fields"] = [{"name": "Begründung", "value": grund}]
    await dc.senden(KANAL_ANTRAEGE, {"embeds": [embed], "allowed_mentions": {"parse": []}})
    for m in await dc.mitglieder():
        if ROLLE_PRAESIDIUM in m["rollen"] and m["id"] != k["id"]:
            await dc.dm(m["id"], f"**Neuer Antrag an den Reichstag** (Nr. {nr}) von {k['name']}:\n**{titel}**\n{url}")
    return web.json_response({"ok": True, "id": nr, "url": url})


def registrieren(app):
    einrichten(app["db"])
    for p in ("", "/en"):
        b = p + BASIS
        app.router.add_get(b, uebersicht)
        app.router.add_get(b + "archiv/", archiv)
        app.router.add_get(b + "sitzungen/", sitzungen_seite)
        app.router.add_get(b + "antraege/", antraege_seite)
        app.router.add_get(b + "abstimmungsverhalten/", verhalten_seite)
        app.router.add_get(b + "sitzung/{id}/", sitzung_seite)
        app.router.add_get(b + "antrag/{id}/", antrag_seite)
        app.router.add_get(b + "abgeordnete/{id}/", abgeordneter_seite)
        app.router.add_post(b + "sitzung-anlegen", sitzung_anlegen)
        app.router.add_post(b + "sitzung/{id}/aktion", sitzung_aktion)
        app.router.add_post(b + "tagesordnung", tagesordnung)
        app.router.add_post(b + "abstimmung", abstimmung)
    app.router.add_post("/intern-api/reichstag/antrag", api_antrag)
