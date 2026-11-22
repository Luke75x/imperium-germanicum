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
CREATE TABLE IF NOT EXISTS reichstag_vertreter (
    konto_id TEXT PRIMARY KEY, vertreter_id TEXT NOT NULL, vertreter_name TEXT NOT NULL, seit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reichstag_notizen (
    sitzung_id INTEGER NOT NULL, antrag_id INTEGER NOT NULL, konto_id TEXT NOT NULL, notiz TEXT NOT NULL,
    geaendert INTEGER NOT NULL, geaendert_von TEXT NOT NULL,
    PRIMARY KEY (sitzung_id, antrag_id, konto_id));
"""


def einrichten(con):
    con.executescript(SCHEMA)
    if "vertreter" not in [r[1] for r in con.execute("PRAGMA table_info(reichstag_stimmen)")]:
        con.execute("ALTER TABLE reichstag_stimmen ADD COLUMN vertreter TEXT NOT NULL DEFAULT ''")
    con.commit()


def _vertreter(con):
    """Aktuelle Vertretungen {Konto-ID des Abgeordneten: Name des Vertreters}."""
    return {r["konto_id"]: r["vertreter_name"] for r in con.execute("SELECT konto_id, vertreter_name FROM reichstag_vertreter")}


def _mit_vertreter(name_html, vertreter):
    return name_html + (f'<br><span class="az">Vertreten durch: {esc(vertreter)}</span>' if vertreter else "")


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


# ---------------------------------------------------------------- Seiten (Stil des Schatz- und Währungsamts: amt.rahmen mit Portal)

import amt

for _n, _d in {
    "calendar": '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    "file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "archive": '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h14a2 2 0 0 0 0-2"/><path d="M10 12h4"/>',
    "vote": '<path d="m9 12 2 2 4-4"/><path d="M5 7c0-1.1.9-2 2-2h10a2 2 0 0 1 2 2v12H5Z"/><path d="M22 19H2"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "landmark": '<path d="M3 22h18"/><path d="M6 18v-7"/><path d="M10 18v-7"/><path d="M14 18v-7"/><path d="M18 18v-7"/><path d="m12 2 9 5H3Z"/><path d="M3 7h18v2H3z"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "mail": '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    "layout-grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
}.items():
    amt.ICONS.setdefault(_n, _d)

STIL = """<style>
.seite .logo{padding:6px 14px 18px}.seite .logo img{max-height:none;width:100%;max-width:210px;margin:0 auto;object-position:center}
.rt-badge{display:inline-flex}
.status.rt-ok{color:var(--ok)}.status.rt-nein{color:var(--rot)}
.status.rt-aktiv{background:var(--ink);color:#fff;border-color:var(--ink)}
.rt-lauf{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:10px 0 4px;font-size:13px;color:var(--grau)}
.rt-lauf span{padding:3px 12px;border:1px solid var(--linie);border-radius:999px;background:#fff}
.rt-lauf span.da{background:var(--ink);color:#fff;border-color:var(--ink);font-weight:600}
.rt-lauf span.vorbei{color:var(--ink);border-color:var(--ink)}
.rt-lauf i{font-style:normal}
.rt-schritt{display:flex;gap:10px;align-items:center;margin:28px 0 8px;padding-top:4px;border-top:2px solid var(--ink)}
.rt-schritt>span{flex:none;width:26px;height:26px;border-radius:50%;background:var(--ink);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:13px;font-weight:700}
.rt-schritt h2{margin:10px 0 0;padding:0;border:0}
.rt-top{list-style:none;margin:8px 0;padding:0;counter-reset:top;display:grid;gap:10px}
.rt-top li{counter-increment:top;display:grid;grid-template-columns:2em 1fr auto;gap:2px 10px;align-items:start;border:1px solid var(--linie);border-radius:12px;padding:12px 16px;background:#fff}
.rt-top li::before{content:counter(top);font-size:20px;font-weight:650;color:var(--grau);grid-row:span 2}
.rt-top .titel{font-weight:600}
.rt-top .zahlen{grid-column:2/4;color:var(--grau);font-size:13.5px}
.rt-top .werkzeug{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.rt-top .werkzeug form{margin:0}
.rt-text{white-space:pre-line}
.rt-karte-text{margin:8px 0 0;font-size:14px;color:var(--grau)}
.sa-karte h3{margin:2px 0 6px;font-size:16px}
.rt-inline{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0}
.rt-inline select{max-width:100%}
.rt-leiste{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.rt-leiste form{margin:0}
table.liste textarea{min-height:44px;width:100%}
.rt-verhalten td:nth-child(n+2),.rt-verhalten th:nth-child(n+2){text-align:center}
@media (max-width:700px){.rt-top li{grid-template-columns:1.6em 1fr}.rt-top .werkzeug{grid-column:2;justify-content:flex-start}
.rt-top .werkzeug .btn,.rt-inline .btn,.rt-leiste .btn{min-height:44px}.rt-inline select,.rt-inline{width:100%}.rt-inline select{flex:1 1 12em}}
</style>"""


def _ic(name):
    return amt.ic(name)


def _tabelle(kopf, zeilen, leer="Keine Einträge.", klasse="liste"):
    if not zeilen:
        return f'<p class="az">{esc(leer)}</p>'

    def beschriften(zeile):   # jede Zelle bekommt ihre Spaltenüberschrift (gestapelte Darstellung am Handy)
        i = iter(kopf)
        return re.sub(r"<td>", lambda m: f'<td data-l="{esc(re.sub("<[^>]+>", "", next(i, "")))}">', zeile)
    return (f'<table class="{klasse}"><thead><tr>' + "".join(f"<th>{k}</th>" for k in kopf)
            + "</tr></thead><tbody>" + "".join(f"<tr>{beschriften(z)}</tr>" for z in zeilen) + "</tbody></table>")


def _td(*zellen):
    return "".join(f"<td>{z}</td>" for z in zellen)


def _panel(titel, inhalt, offen=False):
    return f'<details class="sa-auf"{" open" if offen else ""}><summary>{titel}</summary><div>{inhalt}</div></details>'


def _badge(text, art=""):
    return f'<span class="status rt-{art}">{esc(text)}</span>' if art else f'<span class="status">{esc(text)}</span>'


def _antrag_badge(status):
    return _badge(ANTRAG_STATUS[status], {"angenommen": "ok", "abgelehnt": "nein", "tagesordnung": "aktiv"}.get(status, ""))


def _sitzung_badge(status):
    return _badge(SITZUNG_STATUS[status], {"laeuft": "aktiv", "beendet": "ok", "abgesagt": "nein"}.get(status, ""))


def _ergebnis_badge(e):
    return _badge(_ergebnis_text(e).replace("Antrag ", "").capitalize() if e else "Offen", {"angenommen": "ok", "abgelehnt": "nein"}.get(e, ""))


def _schritt(nr, titel):
    return f'<div class="rt-schritt"><span>{nr}</span><h2>{esc(titel)}</h2></div>'


def _kennzahlen(paare):
    return '<div class="kennzahlen">' + "".join(f'<a href="{u}" style="text-decoration:none;color:inherit"><div><b>{z}</b>{esc(t)}</div></a>' for z, t, u in paare) + "</div>"


def _todo(eintraege):
    """Handlungsbedarf: [(warnung, Text, Zusatz)] – wie die Aufgabenliste der Schatzamt-Startseite."""
    if not eintraege:
        return '<div class="sa-todo"><div>' + _ic("check") + '<span><b>Nichts offen.</b><span class="az">Es gibt zurzeit nichts zu tun.</span></span></div></div>'
    return '<div class="sa-todo">' + "".join(
        f'<div class="{"warn" if w else ""}">{_ic("alert" if w else "clock")}<span><b>{t}</b><span class="az">{z}</span></span></div>' for w, t, z in eintraege) + "</div>"


def _form(request, aktion, inhalt, klasse="rt-inline"):
    return (f'<form method="post" action="{_basis(request)}{aktion}" class="{klasse}">'
            f'<input type="hidden" name="csrf" value="{esc(request["csrf"])}">{inhalt}</form>')


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
                                    f'<button class="btn zweit" name="aktion" value="{w}" title="{b}">{s}</button>')
                              for w, b, s in (("hoch", "Nach oben", "↑"), ("runter", "Nach unten", "↓"), ("weg", "Von der Tagesordnung entfernen", "Entfernen")))
        punkte.append(f'<li><div class="titel"><a href="{basis}antrag/{t["antrag_id"]}/">{esc(t["titel"])}</a> {_ergebnis_badge(t["ergebnis"]) if t["ergebnis"] else ""}</div>'
                      f'<div class="werkzeug">{knoepfe}</div><div class="zahlen">{zahlen}</div></li>')
    return f'<ol class="rt-top">{"".join(punkte)}</ol>' if punkte else '<p class="az">Noch keine Anträge auf der Tagesordnung.</p>'


def _sitzung_form(request):
    return _form(request, "sitzung-anlegen", """
<div class="felder">
<div class="feld"><label for="titel">Titel</label><input type="text" id="titel" name="titel" maxlength="100" value="Ordentliche Sitzung" required></div>
<div class="feld"><label for="termin">Termin (deutsche Zeit)</label><input type="datetime-local" id="termin" name="termin" required></div>
<div class="feld"><label for="ort">Ort</label><input type="text" id="ort" name="ort" maxlength="100" value="🏯｜Plenarsaal"></div>
<div class="feld breit"><label for="bem">Bemerkung (optional)</label><textarea id="bem" name="bemerkung" maxlength="1000" rows="3"></textarea></div></div>
<div class="formular-fuss"><button class="btn" type="submit">Sitzung ankündigen</button></div>
<p class="az">Die Ankündigung erscheint im Discord-Kanal der Anträge und benachrichtigt Landesherren und Abgeordnete.</p>""", "formular")


def _zuweisen(request, antrag_id, kommende):
    ziele = "".join(f'<option value="{s["id"]}">{s["nummer"]}. Sitzung ({_zeit(s["termin"], False)})</option>' for s in kommende)
    return _form(request, "tagesordnung", f'<input type="hidden" name="antrag" value="{antrag_id}"><input type="hidden" name="aktion" value="hinzu">'
                 f'<select name="sitzung" aria-label="Sitzung">{ziele}</select><button class="btn zweit">Auf die Tagesordnung</button>')


MITGLIEDS_HINWEIS = "Die internen Sitzungen stehen den Mitgliedern des Reichstags offen (Abgeordnete, Landesherren, Präsidium)."

LOGO = ("reichstag", "Der Reichstag")   # amt_logos/reichstag-kopf.png (Adler über „DER REICHSTAG“) und -kurz.png (nur Adler)


def _portal(request, k, aktiv):
    con, b = request.app["db"], _basis(request)
    haupt = [("rt-start", "layout-grid", "Übersicht", ""), ("rt-sitzungen", "calendar", "Sitzungen", "sitzungen/"),
             ("rt-antraege", "file-text", "Anträge", "antraege/"), ("rt-verhalten", "users", "Abgeordnete", "abgeordnete/")]
    gruppen = [("Reichstag", haupt + [("rt-archiv", "archive", "Archiv", "archiv/")])]
    if ist_praesidium(k):
        laufend = con.execute("SELECT id FROM reichstag_sitzungen WHERE status = 'laeuft' ORDER BY termin LIMIT 1").fetchone()
        eingang = con.execute("SELECT COUNT(*) FROM reichstag_antraege WHERE status = 'eingebracht'").fetchone()[0]
        pr = [("rt-neu", "plus", "Sitzung ankündigen", "sitzungen/#neu"),
              ("rt-eingang", "inbox", "Antragseingang" + (f" ({eingang})" if eingang else ""), "antraege/?status=eingebracht")]
        if laufend:
            pr.insert(0, ("rt-leitung", "vote", "Sitzungsleitung (läuft)", f"sitzung/{laufend['id']}/"))
        gruppen.append(("Präsidium", pr))
    weiter = []
    if k["mitglied"]:
        weiter.append(("post", "mail", "Postfach", amt.BASIS + "postfach/"))
    weiter += [("rt-info", "landmark", "Der Reichstag (Website)", "/informationen/der-reichstag/"), ("profil", "users", "Mein Profil", "/profil/")]
    gruppen.append(("Weiteres", weiter))
    return {"basis": b, "gruppen": gruppen, "haupt": haupt, "logo": LOGO, "name": "Reichstag"}


def _rahmen(request, titel, eyebrow, inhalt, aktiv="rt-start", brot=(), lead="", icon="landmark"):
    """aktiv: Schlüssel in der Seitenleiste (rt-…); brot: [(Text, Adresse)] zwischen „Reichstag“ und der Seite."""
    k, basis = request["konto"], _basis(request)
    portal = _portal(request, k, aktiv)
    krumen = [f'<a href="{basis}">Reichstag</a>'] + [f'<a href="{u}">{esc(t)}</a>' for t, u in brot]
    if aktiv != "rt-start" or brot:
        krumen.append(f'<span aria-current="page">{esc(titel)}</span>')
    kopf = ('<nav class="sa-krumen" aria-label="Pfad">' + " › ".join(krumen) + "</nav>") if len(krumen) > 1 else ""
    kopf += f'<h1>{_ic(icon)}{esc(titel)}</h1><p class="az">{esc(eyebrow)}{(" · " + esc(lead)) if lead else ""}</p>'
    meldung = {"ok": '<div class="hinweis" role="status">Gespeichert.</div>',
               "fehler": '<div class="hinweis fehler" role="status">Das ging nicht: ' + esc(request.query.get("t", "ungültige Eingabe")) + "</div>"
               }.get(request.query.get("m"), "")
    return web.Response(text=amt.rahmen(titel, aktiv, '<meta name="robots" content="noindex">' + __import__("schatzamt").CSS + STIL + kopf + meldung + inhalt, k, request["csrf"], portal=portal),
                        content_type="text/html", headers={"Cache-Control": "no-store"})


def _sitzung_karte(con, request, s):
    basis = _basis(request)
    return (f'<div class="sa-karte"><small>{_sitzung_badge(s["status"])}</small><h3><a href="{basis}sitzung/{s["id"]}/">{s["nummer"]}. Sitzung – {esc(s["titel"])}</a></h3>'
            + werte_html([("Termin", _zeit(s["termin"]))] + ([("Ort", esc(s["ort"]))] if s["ort"] else []))
            + (f'<p class="rt-karte-text">{esc(s["bemerkung"])}</p>' if s["bemerkung"] else "")
            + _top_liste(con, request, s["id"]) + f'<div class="sa-aktionen"><a class="btn zweit" href="{basis}sitzung/{s["id"]}/">Zur Sitzung</a></div></div>')


def werte_html(paare):
    return '<dl class="sa-werte">' + "".join(f"<dt>{esc(t)}</dt><dd>{v}</dd>" for t, v in paare) + "</dl>"


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def uebersicht(request):
    con, basis, k = request.app["db"], _basis(request), request["konto"]
    praes = ist_praesidium(k)
    kommende = con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('angekuendigt', 'laeuft') ORDER BY termin").fetchall()
    offene = con.execute("SELECT * FROM reichstag_antraege WHERE status = 'eingebracht' ORDER BY id").fetchall()
    beendet = con.execute("SELECT COUNT(*) FROM reichstag_sitzungen WHERE status = 'beendet'").fetchone()[0]
    angenommen = con.execute("SELECT COUNT(*) FROM reichstag_antraege WHERE status = 'angenommen'").fetchone()[0]
    inhalt = _kennzahlen([(len(kommende), "kommende Sitzungen", basis + "sitzungen/"), (len(offene), "Anträge im Eingang", basis + "antraege/?status=eingebracht"),
                          (beendet, "beendete Sitzungen", basis + "archiv/"), (angenommen, "angenommene Anträge", basis + "antraege/?status=angenommen")])
    # Handlungsbedarf
    todo = []
    for s in kommende:
        n = con.execute("SELECT COUNT(*) FROM reichstag_tagesordnung WHERE sitzung_id = ?", (s["id"],)).fetchone()[0]
        offen_top = con.execute("SELECT COUNT(*) FROM reichstag_tagesordnung WHERE sitzung_id = ? AND ergebnis IS NULL", (s["id"],)).fetchone()[0]
        link = f'<a href="{basis}sitzung/{s["id"]}/">{s["nummer"]}. Sitzung</a>'
        if s["status"] == "laeuft":
            todo.append((praes, f"{link} läuft" + (f" – {offen_top} Abstimmung(en) offen" if offen_top else ""),
                         "Abstimmungen erfassen und die Sitzung beenden." if praes else "Das Präsidium erfasst die Abstimmungen."))
        elif praes and not n:
            todo.append((True, f"{link} hat noch keine Tagesordnung", f"Termin {_zeit(s['termin'])} – Anträge zuweisen."))
        else:
            todo.append((False, f"{link} am {_zeit(s['termin'])}", f"{n} Tagesordnungspunkt(e)."))
    if praes and offene and kommende:
        todo.append((True, f'<a href="{basis}antraege/?status=eingebracht">{len(offene)} Antrag/Anträge im Eingang</a>', "Noch keiner Tagesordnung zugewiesen."))
    if praes and not kommende:
        todo.append((True, "Keine Sitzung angekündigt", f'<a href="{basis}sitzungen/#neu">Neue Sitzung ankündigen</a>'))
    inhalt += "<h2>Aktuell</h2>" + _todo(todo)
    if kommende:
        inhalt += "<h2>Nächste Sitzung</h2>" + f'<div class="sa-karten">{_sitzung_karte(con, request, kommende[0])}</div>'
    zeilen = [_td(f'<a href="{basis}antrag/{a["id"]}/"><strong>Nr. {a["id"]}</strong> {esc(a["titel"])}</a>', esc(a["einreicher_name"]), _zeit(a["erstellt"], False),
                  _zuweisen(request, a["id"], kommende) if (praes and kommende) else "") for a in offene]
    inhalt += ("<h2>Antragseingang</h2>" + _tabelle(["Antrag", "Eingereicht von", "Eingang", "Tagesordnung" if praes else ""], zeilen, "Es liegen keine unbehandelten Anträge vor.")
               + '<p class="az">Anträge reichen Abgeordnete im Discord mit dem Befehl <code>/antrag</code> ein.</p>')
    inhalt += ('<div class="sa-erkl"><b>So läuft eine Sitzung ab</b><ol><li>Anträge gehen per <code>/antrag</code> im Eingang ein.</li>'
               '<li>Das Präsidium kündigt eine Sitzung an und setzt Anträge auf die Tagesordnung.</li>'
               '<li>Das Präsidium eröffnet die Sitzung, erfasst je Antrag die Stimmen und macht Notizen.</li>'
               '<li>Beim Beenden wird das Ergebnis im Kanal der Beschlüsse verkündet; die Sitzung wandert ins Archiv.</li></ol></div>')
    return _rahmen(request, "Reichstag", "Interne Sitzungen für Mitglieder des Reichstages", inhalt, aktiv="rt-start", brot=(),
                   lead="Sitzungen, Anträge und Abstimmungen")


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def sitzungen_seite(request):
    con, basis, k = request.app["db"], _basis(request), request["konto"]
    kommende = con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('angekuendigt', 'laeuft') ORDER BY termin").fetchall()
    inhalt = "<h2>Kommende Sitzungen</h2>"
    inhalt += (f'<div class="sa-karten">{"".join(_sitzung_karte(con, request, s) for s in kommende)}</div>' if kommende
               else '<p class="az">Zurzeit ist keine Sitzung angekündigt.</p>')
    if ist_praesidium(k):
        inhalt += f'<div id="neu">{_panel("Neue Sitzung ankündigen", _sitzung_form(request), offen=not kommende)}</div>'
    vergangene = [_td(f'<a href="{basis}sitzung/{s["id"]}/"><strong>{s["nummer"]}. Sitzung</strong></a> {esc(s["titel"])}', _zeit(s["termin"], False), _sitzung_badge(s["status"]))
                  for s in con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('beendet', 'abgesagt') ORDER BY termin DESC LIMIT 10")]
    inhalt += "<h2>Zuletzt</h2>" + _tabelle(["Sitzung", "Datum", "Stand"], vergangene, "Noch keine Sitzung beendet.") + f'<p class="az"><a href="{basis}archiv/">Zum Archiv</a></p>'
    return _rahmen(request, "Sitzungen", "Reichstag", inhalt, aktiv="rt-sitzungen", icon="calendar")


FILTER = (("", "Alle"), ("eingebracht", "Im Eingang"), ("tagesordnung", "Auf der Tagesordnung"), ("angenommen", "Angenommen"), ("abgelehnt", "Abgelehnt"), ("zurueckgezogen", "Zurückgezogen"))


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def antraege_seite(request):
    con, basis, k = request.app["db"], _basis(request), request["konto"]
    wahl = request.query.get("status", "")
    wahl = wahl if wahl in ANTRAG_STATUS else ""
    kommende = con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('angekuendigt', 'laeuft') ORDER BY termin").fetchall()
    zahl = {r["status"]: r["n"] for r in con.execute("SELECT status, COUNT(*) n FROM reichstag_antraege GROUP BY status")}
    filt = "".join(f'<a href="{basis}antraege/' + (f"?status={w}" if w else "") + '"' + (' class="aktiv" aria-current="page"' if w == wahl else "")
                   + f">{b}{(' (' + str(zahl.get(w, 0)) + ')') if w else ''}</a>" for w, b in FILTER)
    zeilen = []
    for a in con.execute("SELECT * FROM reichstag_antraege " + ("WHERE status = ? " if wahl else "") + "ORDER BY id DESC", (wahl,) if wahl else ()):
        zuw = _zuweisen(request, a["id"], kommende) if (ist_praesidium(k) and a["status"] == "eingebracht" and kommende) else ""
        zeilen.append(_td(f'<a href="{basis}antrag/{a["id"]}/"><strong>Nr. {a["id"]}</strong> {esc(a["titel"])}</a>', esc(a["einreicher_name"]),
                          _zeit(a["erstellt"], False), _antrag_badge(a["status"]) + (f"<br>{zuw}" if zuw else "")))
    inhalt = (f'<div class="reiter">{filt}</div>' + _tabelle(["Antrag", "Eingereicht von", "Eingang", "Stand"], zeilen, "Keine Anträge in dieser Ansicht.")
              + '<p class="az">Anträge reichen Abgeordnete im Discord mit dem Befehl <code>/antrag</code> ein.</p>')
    return _rahmen(request, "Anträge", "Reichstag", inhalt, aktiv="rt-antraege", icon="file-text")


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def antrag_seite(request):
    con, basis = request.app["db"], _basis(request)
    a = con.execute("SELECT * FROM reichstag_antraege WHERE id = ?", (request.match_info["id"],)).fetchone() if request.match_info["id"].isdigit() else None
    if not a:
        raise web.HTTPNotFound()
    inhalt = (f'<p>{_antrag_badge(a["status"])}</p>' + f'<p class="az"><b>Eingereicht von</b> {esc(a["einreicher_name"])} &nbsp;·&nbsp; <b>Eingang</b> {_zeit(a["erstellt"])}</p>'
              + '<h2>Antragstext</h2><div class="rt-text">' + esc(a["text"]) + "</div>"
              + (f'<h2>Begründung</h2><div class="rt-text">{esc(a["begruendung"])}</div>' if a["begruendung"] else ""))
    zeilen = []
    for t in con.execute("""SELECT t.*, s.nummer, s.termin FROM reichstag_tagesordnung t JOIN reichstag_sitzungen s ON s.id = t.sitzung_id
                            WHERE t.antrag_id = ? ORDER BY s.termin""", (a["id"],)):
        z = _zaehlen(con, t["sitzung_id"], a["id"])
        zeilen.append(_td(f'<a href="{basis}sitzung/{t["sitzung_id"]}/">{t["nummer"]}. Sitzung</a>', _zeit(t["termin"], False),
                          f'{z["ja"]} Ja · {z["nein"]} Nein · {z["enthaltung"]} Enth. · {z["abwesend"]} abw.' if t["ergebnis"] else "–", _ergebnis_badge(t["ergebnis"])))
    inhalt += "<h2>Verlauf</h2>" + _tabelle(["Sitzung", "Datum", "Abstimmung", "Ergebnis"], zeilen, "Der Antrag wurde noch keiner Sitzung zugeordnet.")
    return _rahmen(request, f"Antrag Nr. {a['id']}: {a['titel']}", "Antrag", inhalt, aktiv="rt-antraege", brot=[("Anträge", basis + "antraege/")], icon="file-text")


async def _abgeordnete(request):
    """Stimmberechtigte (Mitglieder mit einer Reichstags-Rolle), nach Namen sortiert."""
    return sorted((m for m in await request.app["discord"].mitglieder() if ROLLEN_MITGLIED & set(m["rollen"])), key=lambda m: m["name"].lower())


LAUF = (("angekuendigt", "Angekündigt"), ("laeuft", "Läuft"), ("beendet", "Beendet"))


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
    titel = {a["id"]: a["titel"] for a in con.execute("SELECT id, titel FROM reichstag_antraege")}

    # Kopf: Stand, Termin, Ablauf
    pos = [w for w, _ in LAUF].index(s["status"]) if s["status"] in dict(LAUF) else -1
    if s["status"] == "abgesagt":
        lauf = f'<div class="rt-lauf"><span class="da">Abgesagt</span></div>'
    else:
        lauf = '<div class="rt-lauf">' + "<i>→</i>".join(f'<span class="{"da" if i == pos else "vorbei" if i < pos else ""}">{b}</span>' for i, (_, b) in enumerate(LAUF)) + "</div>"
    inhalt = lauf + f'<p class="az" style="margin:12px 0 0"><b>Termin</b> {_zeit(s["termin"])}' + (f' &nbsp;·&nbsp; <b>Ort</b> {esc(s["ort"])}' if s["ort"] else "") + "</p>"
    if s["bemerkung"]:
        inhalt += f'<p class="rt-text">{esc(s["bemerkung"])}</p>'

    n = 1
    # Sitzungsleitung
    if praes and offen:
        knoepfe = ""
        if s["status"] == "angekuendigt":
            knoepfe += '<button class="btn" name="aktion" value="eroeffnen">Sitzung eröffnen</button>'
        if s["status"] == "laeuft":
            knoepfe += '<button class="btn" name="aktion" value="beenden">Sitzung beenden und Ergebnis verkünden</button>'
        knoepfe += '<button class="btn zweit gefahr" name="aktion" value="absagen">Sitzung absagen</button>'
        inhalt += _schritt(n, "Sitzungsleitung") + '<div class="rt-leiste">' + _form(request, f"sitzung/{s['id']}/aktion", knoepfe) + "</div>"
        n += 1

    # Tagesordnung
    inhalt += _schritt(n, "Tagesordnung") + _top_liste(con, request, s["id"], werkzeug=praes and offen)
    n += 1
    if praes and offen:
        frei = con.execute("SELECT id, titel FROM reichstag_antraege WHERE status = 'eingebracht' ORDER BY id").fetchall()
        if frei:
            inhalt += _panel("Antrag zur Tagesordnung hinzufügen", _form(
                request, "tagesordnung", f'<input type="hidden" name="sitzung" value="{s["id"]}"><input type="hidden" name="aktion" value="hinzu">'
                '<select name="antrag" aria-label="Antrag">' + "".join(f'<option value="{a["id"]}">Nr. {a["id"]} – {esc(a["titel"][:80])}</option>' for a in frei)
                + '</select><button class="btn zweit">Hinzufügen</button>'))

    # Abstimmungen erfassen
    if praes and s["status"] == "laeuft":
        voters = await _abgeordnete(request)
        vt = _vertreter(con)
        panels = ""
        for t in top:
            if t["ergebnis"]:
                continue
            zeilen = "".join(f'<tr><td data-l="Abgeordnete/r">{_mit_vertreter(esc(m["name"]), vt.get(m["id"]))}</td><td data-l="Stimme"><select name="s_{m["id"]}" aria-label="Stimme von {esc(m["name"])}"><option value="">–</option>'
                             + "".join(f'<option value="{w}">{b}</option>' for w, b in STIMMEN.items()) + "</select></td></tr>" for m in voters)
            aid = t["antrag_id"]
            panels += _panel(f'Abstimmung: {esc(titel[aid])}', _form(
                request, "abstimmung", f'<input type="hidden" name="sitzung" value="{s["id"]}"><input type="hidden" name="antrag" value="{aid}">'
                f'<table class="liste"><thead><tr><th>Abgeordnete/r</th><th>Stimme</th></tr></thead><tbody>{zeilen}</tbody></table>'
                f'<div class="feld" style="margin:12px 0"><label for="erg-{aid}">Ergebnis</label><select id="erg-{aid}" name="ergebnis">'
                '<option value="auto">Nach den Stimmen (mehr Ja als Nein = angenommen)</option><option value="vertagt">Vertagt</option>'
                '<option value="zurueckgezogen">Antrag zurückgezogen</option></select></div>'
                '<button class="btn" type="submit">Abstimmung speichern</button>', "formular"), offen=len(top) == 1)
        if panels:
            inhalt += _schritt(n, "Abstimmungen erfassen") + panels
            n += 1

    # Notizen des Präsidiums
    if praes and top:
        voters = await _abgeordnete(request)
        vt = _vertreter(con)
        panels = ""
        for t in top:
            aid = t["antrag_id"]
            notizen = {r["konto_id"]: r["notiz"] for r in con.execute("SELECT konto_id, notiz FROM reichstag_notizen WHERE sitzung_id = ? AND antrag_id = ?", (s["id"], aid))}
            stm = {r["konto_id"]: r["stimme"] for r in con.execute("SELECT konto_id, stimme FROM reichstag_stimmen WHERE sitzung_id = ? AND antrag_id = ?", (s["id"], aid))}
            personen = {m["id"]: m["name"] for m in voters}
            for r in con.execute("SELECT konto_id, name FROM reichstag_stimmen WHERE sitzung_id = ? AND antrag_id = ?", (s["id"], aid)):
                personen.setdefault(r["konto_id"], r["name"])
            zeilen = "".join(f'<tr><td data-l="Abgeordnete/r">{_mit_vertreter(esc(nm), vt.get(kid))}</td><td data-l="Stimme">{STIMMEN.get(stm.get(kid), "–")}</td>'
                             f'<td data-l="Notiz"><textarea name="n_{esc(kid)}" rows="2" maxlength="1000" aria-label="Notiz zu {esc(nm)}">{esc(notizen.get(kid, ""))}</textarea></td></tr>'
                             for kid, nm in sorted(personen.items(), key=lambda x: x[1].lower()))
            panels += _panel(f'Notizen: {esc(titel[aid])}', _form(
                request, "notizen", f'<input type="hidden" name="sitzung" value="{s["id"]}"><input type="hidden" name="antrag" value="{aid}">'
                f'<table class="liste"><thead><tr><th>Abgeordnete/r</th><th>Stimme</th><th>Notiz (nur Präsidium)</th></tr></thead><tbody>{zeilen}</tbody></table>'
                '<div class="formular-fuss"><button class="btn" type="submit">Notizen speichern</button></div>', "formular"))
        inhalt += _schritt(n, "Notizen zum Abstimmungsverhalten") + '<p class="az">Diese Notizen sieht nur das Präsidium.</p>' + panels
        n += 1

    # Ergebnis
    fertig = [t for t in top if t["ergebnis"]]
    if fertig:
        stimmen = {(r["antrag_id"], r["konto_id"]): r["stimme"] for r in con.execute("SELECT * FROM reichstag_stimmen WHERE sitzung_id = ?", (s["id"],))}
        namen = {r["konto_id"]: r["name"] for r in con.execute("SELECT DISTINCT konto_id, name FROM reichstag_stimmen WHERE sitzung_id = ?", (s["id"],))}
        vert = {}
        for r in con.execute("SELECT konto_id, vertreter FROM reichstag_stimmen WHERE sitzung_id = ? AND vertreter != ''", (s["id"],)):
            vert.setdefault(r["konto_id"], r["vertreter"])
        kopf = ["Abgeordnete/r"] + [f'Nr. {t["antrag_id"]}' for t in fertig]
        zeilen = [_td(_mit_vertreter(f'<a href="{basis}abgeordnete/{kid}/">{esc(nm)}</a>', vert.get(kid)), *[STIMMEN.get(stimmen.get((t["antrag_id"], kid)), "–") for t in fertig])
                  for kid, nm in sorted(namen.items(), key=lambda x: x[1].lower())]
        inhalt += _schritt(n, "Abstimmungsverhalten dieser Sitzung") + _tabelle(kopf, zeilen)
    return _rahmen(request, f"{s['nummer']}. Sitzung – {s['titel']}", "Sitzung des Reichstages", inhalt, aktiv="rt-leitung" if (praes and s["status"] == "laeuft") else "rt-sitzungen",
                   brot=[("Sitzungen", basis + "sitzungen/")], icon="calendar")


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def archiv(request):
    con, basis = request.app["db"], _basis(request)
    zeilen = []
    for s in con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('beendet', 'abgesagt') ORDER BY termin DESC"):
        erg = [f'{esc(r["titel"])}: {_ergebnis_badge(r["ergebnis"])}' for r in con.execute(
            """SELECT a.titel, t.ergebnis FROM reichstag_tagesordnung t JOIN reichstag_antraege a ON a.id = t.antrag_id
               WHERE t.sitzung_id = ? AND t.ergebnis IS NOT NULL ORDER BY t.position""", (s["id"],))]
        zeilen.append(_td(f'<a href="{basis}sitzung/{s["id"]}/"><strong>{s["nummer"]}. Sitzung</strong></a><br>{esc(s["titel"])}', _zeit(s["termin"], False),
                          _badge("Abgesagt", "nein") if s["status"] == "abgesagt" else ("<br>".join(erg) or "keine Anträge behandelt")))
    inhalt = "<h2>Beendete Sitzungen</h2>" + _tabelle(["Sitzung", "Datum", "Behandelte Anträge"], zeilen, "Noch keine Sitzung beendet.")
    antr = [_td(f'<a href="{basis}antrag/{a["id"]}/"><strong>Nr. {a["id"]}</strong> {esc(a["titel"])}</a>', esc(a["einreicher_name"]), _antrag_badge(a["status"]))
            for a in con.execute("SELECT * FROM reichstag_antraege WHERE status IN ('angenommen', 'abgelehnt', 'zurueckgezogen') ORDER BY id DESC")]
    inhalt += "<h2>Entschiedene Anträge</h2>" + _tabelle(["Antrag", "Eingereicht von", "Stand"], antr, "Noch kein Antrag entschieden.")
    inhalt += f'<p><a class="btn zweit" href="{basis}abstimmungsverhalten/">Abstimmungsverhalten der Abgeordneten</a></p>'
    return _rahmen(request, "Archiv", "Reichstag", inhalt, aktiv="rt-archiv", icon="archive")


def _abg_reiter(request, aktiv):
    b = _basis(request)
    return ('<div class="reiter">' + "".join(f'<a href="{b}{p}"' + (' class="aktiv" aria-current="page"' if p == aktiv else "") + f">{t}</a>"
            for p, t in (("abgeordnete/", "Anwesenheit"), ("abstimmungsverhalten/", "Abstimmungsverhalten"))) + "</div>")


ROLLEN_NAMEN = ((ROLLE_PRAESIDIUM, "Präsidium"), (ROLLE_LANDESHERR, "Landesherr"), (ROLLE_ABGEORDNETER, "Abgeordnete/r"), (ROLLE_REICHSTAG, "Reichstag"))


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def abgeordnete_liste(request):
    """Alle Abgeordneten für die kommende Sitzung; bei einer ernannten Vertretung steht der Vertreter als Teilnehmer."""
    con, basis = request.app["db"], _basis(request)
    s = con.execute("SELECT * FROM reichstag_sitzungen WHERE status IN ('angekuendigt', 'laeuft') ORDER BY termin LIMIT 1").fetchone()
    voters = await _abgeordnete(request)
    vt = _vertreter(con)
    mit_stimmen = {r[0] for r in con.execute("SELECT DISTINCT konto_id FROM reichstag_stimmen")}
    zeilen, vertreten = [], 0
    for m in voters:
        rolle = next((n for r, n in ROLLEN_NAMEN if r in m["rollen"]), "")
        name = f'<a href="{basis}abgeordnete/{m["id"]}/">{esc(m["name"])}</a>' if m["id"] in mit_stimmen else esc(m["name"])
        v = vt.get(m["id"])
        vertreten += bool(v)
        zeilen.append(_td(name, esc(rolle), (f'<strong>{esc(v)}</strong>' if v else esc(m["name"])), _badge("Vertreten", "aktiv") if v else _badge("Persönlich")))
    if s:
        kopf = (f'<p class="az">Teilnehmer der <a href="{basis}sitzung/{s["id"]}/"><b>{s["nummer"]}. Sitzung</b></a> am {_zeit(s["termin"])} – '
                "bei einer Vertretung nimmt die ernannte Person teil.</p>")
    else:
        kopf = '<p class="az">Zurzeit ist keine Sitzung angekündigt. Die Liste zeigt den aktuellen Stand der Vertretungen.</p>'
    inhalt = (_abg_reiter(request, "abgeordnete/") + _kennzahlen([(len(voters), "Abgeordnete", "#liste"), (len(voters) - vertreten, "nehmen persönlich teil", "#liste"),
                                                                   (vertreten, "werden vertreten", "#liste")]) + kopf
              + '<div id="liste">' + _tabelle(["Abgeordnete/r", "Rolle", "Teilnahme", "Stand"], zeilen, "Keine Abgeordneten gefunden.") + "</div>"
              + '<p class="az">Eine Vertretung ernennen Abgeordnete im Discord mit <code>/vertreter</code>.</p>')
    return _rahmen(request, "Abgeordnete", "Teilnahme an der kommenden Sitzung", inhalt, aktiv="rt-verhalten", icon="users")


@anmeldung.angemeldet(ist_mitglied, MITGLIEDS_HINWEIS)
async def verhalten_seite(request):
    con, basis = request.app["db"], _basis(request)
    zeilen = []
    for r in con.execute("""SELECT konto_id, MAX(name) name, SUM(stimme='ja') ja, SUM(stimme='nein') nein, SUM(stimme='enthaltung') enth,
                                   SUM(stimme='abwesend') abw FROM reichstag_stimmen GROUP BY konto_id ORDER BY name COLLATE NOCASE"""):
        zeilen.append(_td(f'<a href="{basis}abgeordnete/{r["konto_id"]}/">{esc(r["name"])}</a>', str(r["ja"]), str(r["nein"]), str(r["enth"]), str(r["abw"])))
    inhalt = (_abg_reiter(request, "abstimmungsverhalten/") + _tabelle(["Abgeordnete/r", "Ja", "Nein", "Enthaltung", "Abwesend"], zeilen, "Noch keine Abstimmung erfasst.", "liste rt-verhalten")
              + '<p class="az">Gezählt werden alle erfassten Abstimmungen beendeter und laufender Sitzungen.</p>')
    return _rahmen(request, "Abstimmungsverhalten", "Reichstag", inhalt, aktiv="rt-verhalten", brot=[("Abgeordnete", basis + "abgeordnete/")], icon="users")


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
    praes = ist_praesidium(request["konto"])
    nz = {(r["sitzung_id"], r["antrag_id"]): r["notiz"] for r in con.execute("SELECT * FROM reichstag_notizen WHERE konto_id = ?", (kid,))} if praes else {}
    z = {w: sum(1 for r in rows if r["stimme"] == w) for w in STIMMEN}
    zeilen = [_td(f'<a href="{basis}sitzung/{r["sitzung_id"]}/">{r["nummer"]}. Sitzung</a>', _zeit(r["termin"], False),
                  f'<a href="{basis}antrag/{r["antrag_id"]}/">{esc(r["titel"])}</a>', f'<strong>{STIMMEN[r["stimme"]]}</strong>' + (f'<br><span class="az">Vertreten durch: {esc(r["vertreter"])}</span>' if r["vertreter"] else ""), _ergebnis_badge(r["ergebnis"]),
                  *([esc(nz.get((r["sitzung_id"], r["antrag_id"]), "")).replace("\n", "<br>")] if praes else []))
              for r in rows]
    eigene = [_td(f'<a href="{basis}antrag/{a["id"]}/">Nr. {a["id"]} {esc(a["titel"])}</a>', _antrag_badge(a["status"]))
              for a in con.execute("SELECT * FROM reichstag_antraege WHERE einreicher_id = ? ORDER BY id DESC", (kid,))]
    inhalt = (_kennzahlen([(z["ja"], "Ja", "#abstimmungen"), (z["nein"], "Nein", "#abstimmungen"), (z["enthaltung"], "Enthaltungen", "#abstimmungen"), (z["abwesend"], "abwesend", "#abstimmungen")])
              + '<h2 id="abstimmungen">Abstimmungen</h2>' + _tabelle(["Sitzung", "Datum", "Antrag", "Stimme", "Ergebnis"] + (["Notiz (Präsidium)"] if praes else []), zeilen)
              + "<h2>Eingereichte Anträge</h2>" + _tabelle(["Antrag", "Stand"], eigene, "Keine Anträge eingereicht."))
    return _rahmen(request, rows[0]["name"], "Abstimmungsverhalten", inhalt, aktiv="rt-verhalten", brot=[("Abgeordnete", basis + "abgeordnete/"), ("Abstimmungsverhalten", basis + "abstimmungsverhalten/")], icon="users")


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
    vt = _vertreter(con)
    for feld, wert in form.items():
        if feld.startswith("s_") and wert in STIMMEN and feld[2:] in namen:
            con.execute("INSERT INTO reichstag_stimmen (sitzung_id, antrag_id, konto_id, name, stimme, vertreter) VALUES (?, ?, ?, ?, ?, ?)",
                        (t["sitzung_id"], t["antrag_id"], feld[2:], namen[feld[2:]], wert, vt.get(feld[2:], "")))
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


async def notizen(request):
    k, form = await _formular(request, ist_praesidium)
    con = request.app["db"]
    sid, aid = str(form.get("sitzung", "")), str(form.get("antrag", ""))
    t = con.execute("SELECT 1 FROM reichstag_tagesordnung WHERE sitzung_id = ? AND antrag_id = ?", (sid, aid)).fetchone() if sid.isdigit() and aid.isdigit() else None
    if not t:
        _zurueck(request, "", False, "Tagesordnungspunkt nicht gefunden")
    ziel = f"sitzung/{sid}/"
    jetzt = int(time.time())
    for feld, wert in form.items():
        if not feld.startswith("n_"):
            continue
        kid, text = feld[2:], str(wert).strip()[:1000]
        if text:
            con.execute("INSERT OR REPLACE INTO reichstag_notizen VALUES (?, ?, ?, ?, ?, ?)", (sid, aid, kid, text, jetzt, k["name"]))
        else:
            con.execute("DELETE FROM reichstag_notizen WHERE sitzung_id = ? AND antrag_id = ? AND konto_id = ?", (sid, aid, kid))
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


async def api_vertreter(request):
    """Bot-Befehl /vertreter: Vertreter ernennen (vertreter_id) oder aufheben (leer). Nur lokal, mit Bot-Token."""
    if not secrets.compare_digest(request.headers.get("X-Bot-Token", ""), request.app["discord"].bot_token):
        raise web.HTTPForbidden()
    d = await request.json()
    dc, con = request.app["discord"], request.app["db"]
    try:
        k = await dc.konto_neu(str(d.get("konto_id", "")))
    except Exception:
        return web.json_response({"ok": False, "fehler": "Konto nicht gefunden."})
    if not ist_mitglied(k):
        return web.json_response({"ok": False, "fehler": "Einen Vertreter können nur Abgeordnete und Landesherren des Reichstags ernennen."})
    vid = str(d.get("vertreter_id") or "")
    alt = con.execute("SELECT * FROM reichstag_vertreter WHERE konto_id = ?", (k["id"],)).fetchone()
    if not vid:
        con.execute("DELETE FROM reichstag_vertreter WHERE konto_id = ?", (k["id"],))
        con.commit()
        return web.json_response({"ok": True, "aktion": "aufgehoben", "alt": alt["vertreter_name"] if alt else ""})
    if vid == k["id"]:
        return web.json_response({"ok": False, "fehler": "Du kannst dich nicht selbst vertreten."})
    person = next((m for m in await dc.mitglieder() if m["id"] == vid), None)
    if not person:
        return web.json_response({"ok": False, "fehler": "Diese Person ist kein Mitglied des Servers."})
    con.execute("INSERT OR REPLACE INTO reichstag_vertreter VALUES (?, ?, ?, ?)", (k["id"], vid, person["name"], int(time.time())))
    con.commit()
    await dc.dm(vid, f"**{k['name']}** hat dich zum Vertreter im Reichstag ernannt. Bei Sitzungen wird dein Name in der Anwesenheits- und Abstimmungsliste "
                     f"unter seinem/ihrem Namen als „Vertreten durch“ geführt.")
    return web.json_response({"ok": True, "aktion": "ernannt", "name": person["name"]})


async def pruefen_sitzordnung(request):
    """nginx auth_request für /informationen/der-reichstag/sitzordnung/ (vorerst versteckt): 204 nur für Kaiser und Kronkanzler,
    401 ohne Anmeldung (→ Anmeldung), sonst 403 (nginx zeigt dann 404). Nur lokal erreichbar."""
    import amt
    k = await anmeldung.konto(request)
    if not k:
        return web.Response(status=401)
    ok = k["id"] == config.KAISER_ID or amt.ROLLE_KANZLER in k["rollen"]
    return web.Response(status=204 if ok else 403)


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get("/intern-pruefen/sitzordnung", pruefen_sitzordnung)
    for p in ("", "/en"):
        b = p + BASIS
        app.router.add_get(b, uebersicht)
        app.router.add_get(b + "archiv/", archiv)
        app.router.add_get(b + "sitzungen/", sitzungen_seite)
        app.router.add_get(b + "antraege/", antraege_seite)
        app.router.add_get(b + "abstimmungsverhalten/", verhalten_seite)
        app.router.add_get(b + "sitzung/{id}/", sitzung_seite)
        app.router.add_get(b + "antrag/{id}/", antrag_seite)
        app.router.add_get(b + "abgeordnete/", abgeordnete_liste)
        app.router.add_get(b + "abgeordnete/{id}/", abgeordneter_seite)
        app.router.add_post(b + "sitzung-anlegen", sitzung_anlegen)
        app.router.add_post(b + "sitzung/{id}/aktion", sitzung_aktion)
        app.router.add_post(b + "tagesordnung", tagesordnung)
        app.router.add_post(b + "abstimmung", abstimmung)
        app.router.add_post(b + "notizen", notizen)
    app.router.add_post("/intern-api/reichstag/antrag", api_antrag)
    app.router.add_post("/intern-api/reichstag/vertreter", api_vertreter)
