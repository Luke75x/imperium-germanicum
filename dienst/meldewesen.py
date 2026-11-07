"""Pass- und Meldewesen der Reichsverwaltung (…/intern/meldewesen/, Passprüfung unter …/intern/passpruefung/).

Melderegister: Jede Bürgerakte hat einen Wohnsitz (Teilstaat der aktuellen Reichskarte + Anschrift IC). Meldungen sind Anmeldung,
Ummeldung (Umzug zwischen Teilstaaten) und Abmeldung ins Ausland; der aktuelle Wohnsitz ist die jüngste Meldung. Meldebescheinigung als PDF.
Passregister: Reisepass, Personalausweis, Dienstpass, vorläufiger Reisepass (nur Staatsbürger) und Fremdenpass (nur Nicht-Staatsbürger).
Ein neuer Pass derselben Art ersetzt den alten (wird ungültig). Ungültigkeitserklärung mit Grund; „Diebstahl“ schreibt den Pass zur
Fahndung aus. Abgelaufen ist ein Pass, dessen Gültigkeitsdatum (OOC) vorbei ist.

Rechte: Lesen wie die Akten (amt.ist_leser), Melden/Ausstellen/Ungültig erklären wie Akten schreiben (amt.ist_beamter).
Passprüfung (nur Nummer → gültig/ungültig, Inhaber, Gültigkeit): Zoll, Polizei (inkl. Landespolizeien), Reichsverwaltung, Kaiser, Kanzler.
Jede Prüfung wird protokolliert (pw_abfragen), das Protokoll sieht die Reichsverwaltung.
Tabellen: mw_meldungen, pw_paesse, pw_eintraege, pw_abfragen. Akten unter Verschluss bleiben für Unbefugte gesperrt.
"""
import secrets
import time
from datetime import date

from aiohttp import web

import amt
import qr
import anmeldung
import bereiche
import karte

esc = amt.esc
BASIS = amt.BASIS
PFAD = BASIS + "meldewesen/"
PRUEF = BASIS + "passpruefung/"
MELDEARTEN = {"anmeldung": "Anmeldung", "ummeldung": "Ummeldung", "abmeldung": "Abmeldung ins Ausland"}
# schl: (Name, Präfix der Passnummer, Gültigkeit in Jahren, nur Staatsbürger?)
PASSARTEN = {"reisepass": ("Reisepass", "R", 10, True), "personalausweis": ("Personalausweis", "L", 10, True),
             "dienstpass": ("Dienstpass", "D", 6, True), "vorlaeufig": ("Vorläufiger Reisepass", "V", 1, True),
             "fremdenpass": ("Fremdenpass", "F", 2, False)}
GRUENDE = ["Verlust gemeldet", "Diebstahl gemeldet (Fahndung)", "Eingezogen", "Verlust der Staatsbürgerschaft", "Beschädigt / unbrauchbar", "Sonstiges"]
ERSETZT = "Durch neuen Pass ersetzt"
ZEICHEN = "CFGHJKLMNPRTVWXYZ0123456789"
SEITE = 50
AUSGESTELLT = []    # fn(request, con, akte, art, passnummer, konto) nach Ausstellung eines Passes (steuern.py: Gebühr)
PRUEF_ZUSATZ = []   # fn(request, konto) -> HTML über dem Eingabefeld der Passprüfung (personenseite.py: QR-Scanner)
DM_ZUSATZ = []      # fn(passnummer) -> Text, wird an die DM bei Ausstellung angehängt (passdigital.py: Link)
PASS_KNOEPFE = []   # fn(pass, con) -> HTML, weitere Knöpfe in der Pass-Ansicht (passdruck.py: Druckvorlagen)

SCHEMA = """
CREATE TABLE IF NOT EXISTS mw_meldungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, akte_id INTEGER NOT NULL, art TEXT NOT NULL, staat TEXT NOT NULL, staat_name TEXT NOT NULL,
    anschrift TEXT NOT NULL DEFAULT '', gueltig_ab TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS mw_meldungen_a ON mw_meldungen (akte_id);
CREATE TABLE IF NOT EXISTS pw_paesse (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nummer TEXT NOT NULL UNIQUE, akte_id INTEGER NOT NULL, konto_id TEXT NOT NULL,
    inhaber TEXT NOT NULL, geburt TEXT NOT NULL DEFAULT '', art TEXT NOT NULL, ausgestellt INTEGER NOT NULL, gueltig_bis TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'gueltig', grund TEXT NOT NULL DEFAULT '', ungueltig_zeit INTEGER, bemerkung TEXT NOT NULL DEFAULT '',
    autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS pw_paesse_a ON pw_paesse (akte_id);
CREATE TABLE IF NOT EXISTS pw_eintraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pass_id INTEGER NOT NULL, zeit INTEGER NOT NULL, art TEXT NOT NULL, text TEXT NOT NULL,
    autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS pw_eintraege_p ON pw_eintraege (pass_id);
CREATE TABLE IF NOT EXISTS pw_abfragen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, konto_id TEXT NOT NULL, name TEXT NOT NULL, stelle TEXT NOT NULL,
    nummer TEXT NOT NULL, pass_id INTEGER, ergebnis TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS pw_abfragen_p ON pw_abfragen (pass_id);
"""

amt.ICONS.update({
    "id-card": '<path d="M16 10h2"/><path d="M16 14h2"/><path d="M6.17 15a3 3 0 0 1 5.66 0"/><circle cx="9" cy="11" r="2"/><rect x="2" y="5" width="20" height="14" rx="2"/>',
    "scan-search": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
                   '<circle cx="12" cy="12" r="3"/><path d="m16 16-1.9-1.9"/>',
    "home": '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
})
amt._ART_ICON[0:0] = [("pass ausgestellt", "id-card", "ok"), ("pass ungültig", "x", "rot"), ("wohnsitz", "home", "")]


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Hilfen

def staaten(con):
    return [{"id": s["id"], "name": s["name"]} for s in sorted(karte.aktuell(con)["stand"]["staaten"], key=lambda s: s["name"].lower())]


def wohnsitz(con, akte_id):
    return con.execute("SELECT * FROM mw_meldungen WHERE akte_id=? ORDER BY id DESC LIMIT 1", (akte_id,)).fetchone()


def pass_status(p):
    """(Schlüssel, Text) – gueltig, abgelaufen, fahndung, ungueltig."""
    if p["status"] != "gueltig":
        return ("fahndung", "Zur Fahndung ausgeschrieben") if p["grund"].startswith("Diebstahl") else ("ungueltig", "Ungültig")
    if p["gueltig_bis"] < date.today().isoformat():
        return "abgelaufen", "Abgelaufen"
    return "gueltig", "Gültig"


def pass_marke(p):
    s, t = pass_status(p)
    return amt.status_marke({"gueltig": "ok", "abgelaufen": "offen"}.get(s, "nein"), t)


def _datum(iso):
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso or "–"


def _nummer(con, praefix):
    while True:
        n = praefix + "".join(secrets.choice(ZEICHEN) for _ in range(8))
        if not con.execute("SELECT 1 FROM pw_paesse WHERE nummer=?", (n,)).fetchone():
            return n


def _eintrag(con, pid, art, text, k):
    con.execute("INSERT INTO pw_eintraege (pass_id, zeit, art, text, autor_id, autor_name) VALUES (?,?,?,?,?,?)",
                (pid, int(time.time()), art, text, k["id"], k["name"]))


def darf_pruefen(k):
    if not k or not k["mitglied"]:
        return False
    if amt.ist_beamter(k) or bereiche._alle(k):
        return True
    return any(bereiche.darf(k, b) for b in amt.BEHOERDEN if b["schl"] in ("zoll", "polizei"))


def _stelle_von(k):
    if bereiche._alle(k):
        return "Reichskanzlei"
    for b in amt.BEHOERDEN:
        if b["schl"] in ("zoll", "polizei") and bereiche.darf(k, b):
            return b["name"]
    return "Reichsverwaltung"


def nav_akten(k):
    return [("meldewesen", "id-card", "Pass- und Meldewesen", "meldewesen/")] if amt.ist_leser(k) else []


def nav_dienste(k):
    return [("passpruefung", "scan-search", "Passprüfung", "passpruefung/")] if darf_pruefen(k) else []


CSS = """<style>.mw-text{white-space:pre-wrap;word-break:break-word}
.mw-pass{border:1px solid var(--linie);border-radius:12px;padding:16px 18px;margin:12px 0;max-width:560px}
.mw-pass.gueltig{border-left:6px solid var(--ok)}.mw-pass.abgelaufen{border-left:6px solid var(--warn)}.mw-pass.ungueltig,.mw-pass.fahndung{border-left:6px solid var(--rot)}
.mw-pass h3{margin:0 0 4px;font-size:18px}.mw-pass .nr{font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.08em}
.mw-gross{font-size:22px;font-weight:700;margin:4px 0 10px}
.mw-nr{font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.06em}</style>"""


def _reiter(aktiv):
    teile = [("register", "Melderegister", ""), ("paesse", "Passregister", "paesse/"), ("abfragen", "Abfrageprotokoll", "abfragen/")]
    return '<p class="reiter">' + " ".join(f'<a href="{PFAD}{u}" class="{"aktiv" if x == aktiv else ""}">{esc(t)}</a>' for x, t, u in teile) + "</p>"


def _seite(request, titel, aktiv, inhalt):
    kopf = f'<h1>{amt.ic("id-card")} Pass- und Meldewesen</h1>{amt.meldung(request)}{_reiter(aktiv)}'
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, "meldewesen", CSS + kopf + inhalt, request["konto"], request["csrf"]))


def _akte_link(a, gesperrt):
    if gesperrt:
        return f'<a href="{BASIS}buerger/{a["id"]}/">{amt.az_akte(a["id"])}</a>', amt._verschluss_marke()
    return f'<a href="{BASIS}buerger/{a["id"]}/">{amt.az_akte(a["id"])}</a>', esc(a["ic_name"] or a["name"])


# ---------------------------------------------------------------- Melderegister

REGISTER_SQL = ("SELECT a.id, a.name, a.ic_name, a.status, m.art AS m_art, m.staat, m.staat_name, m.anschrift, m.gueltig_ab, m.zeit AS m_zeit "
                "FROM amt_akten a LEFT JOIN mw_meldungen m ON m.id=(SELECT MAX(id) FROM mw_meldungen WHERE akte_id=a.id)")


@amt._beamter
async def register(request):
    con = request.app["db"]
    sa, _ = amt.sperren(con, request["konto"])
    rows = con.execute(REGISTER_SQL).fetchall()
    st = staaten(con)
    gemeldet = [r for r in rows if r["m_art"] and r["m_art"] != "abmeldung"]
    n_paesse = con.execute("SELECT COUNT(*) FROM pw_paesse WHERE status='gueltig' AND gueltig_bis>=?", (date.today().isoformat(),)).fetchone()[0]
    n_fahndung = con.execute("SELECT COUNT(*) FROM pw_paesse WHERE status!='gueltig' AND grund LIKE 'Diebstahl%'").fetchone()[0]
    ohne = [r for r in rows if not r["m_art"] and r["status"] == "staatsbuerger"]
    zahlen = "".join(f"<div><b>{n}</b>{esc(t)}</div>" for t, n in [
        ("Gemeldete Einwohner", len(gemeldet)), ("Staatsbürger ohne Wohnsitz", len(ohne)),
        ("Im Ausland gemeldet", sum(1 for r in rows if r["m_art"] == "abmeldung")), ("Gültige Pässe", n_paesse), ("Pässe in Fahndung", n_fahndung)])
    wahl = request.query.get("staat", "")
    if wahl:
        if wahl == "ohne":
            treffer, titel = ohne, "Staatsbürger ohne gemeldeten Wohnsitz"
        elif wahl == "ausland":
            treffer, titel = [r for r in rows if r["m_art"] == "abmeldung"], "Im Ausland gemeldet"
        else:
            treffer = [r for r in gemeldet if r["staat"] == wahl]
            titel = "Einwohner: " + next((s["name"] for s in st if s["id"] == wahl), wahl)
        zeilen = [(*_akte_link(r, r["id"] in sa), "–" if r["id"] in sa else esc(r["anschrift"] or "–"),
                   "–" if r["id"] in sa else esc(r["gueltig_ab"] or amt._zeit(r["m_zeit"], False) if r["m_zeit"] else "–"), amt.akte_marke(r["status"]))
                  for r in sorted(treffer, key=lambda r: (r["ic_name"] or r["name"]).lower())]
        inhalt = (f'<p class="zurueck"><a href="{PFAD}">{amt.ic("arrow-left")}Alle Teilstaaten</a></p><h2>{esc(titel)} ({len(treffer)})</h2>'
                  + amt.tabelle(["Bürgerakte", "Name", "Anschrift (IC)", "Gemeldet seit", "Status"], zeilen, "Niemand gemeldet."))
        return _seite(request, titel, "register", inhalt)
    je = {}
    for r in gemeldet:
        je[r["staat"]] = je.get(r["staat"], 0) + 1
    zeilen = [(f'<a href="?staat={esc(s["id"])}">{esc(s["name"])}</a>', str(je.get(s["id"], 0))) for s in st]
    zeilen += [(f'<a href="?staat=ausland"><i>Ausland</i></a>', str(sum(1 for r in rows if r["m_art"] == "abmeldung"))),
               (f'<a href="?staat=ohne"><i>Staatsbürger ohne Wohnsitz</i></a>', str(len(ohne)))]
    letzte = con.execute("SELECT m.*, a.ic_name, a.name FROM mw_meldungen m JOIN amt_akten a ON a.id=m.akte_id ORDER BY m.id DESC LIMIT 10").fetchall()
    lz = [(amt._zeit(m["zeit"]), *_akte_link({"id": m["akte_id"], "ic_name": m["ic_name"], "name": m["name"]}, m["akte_id"] in sa),
           esc(MELDEARTEN.get(m["art"], m["art"])), "–" if m["akte_id"] in sa else esc(m["staat_name"]), esc(m["autor_name"])) for m in letzte]
    inhalt = (f'<div class="kennzahlen">{zahlen}</div>'
              '<p class="az">Wohnsitze werden in der Bürgerakte gemeldet (Abschnitt „Melde- und Passwesen“). Ein Umzug in einen anderen Teilstaat ist eine Ummeldung.</p>'
              '<h2>Einwohner je Teilstaat</h2>' + amt.tabelle(["Teilstaat", "Gemeldete Einwohner"], zeilen)
              + '<h2>Letzte Meldungen</h2>' + amt.tabelle(["Zeit", "Bürgerakte", "Name", "Meldung", "Teilstaat", "Beamter"], lz, "Noch keine Meldungen."))
    return _seite(request, "Melderegister", "register", inhalt)


# ---------------------------------------------------------------- Abschnitt in der Bürgerakte

def akte_abschnitt(request, con, z, schreiben):
    p = f'{BASIS}buerger/{z["id"]}/'
    ws = wohnsitz(con, z["id"])
    meldungen = con.execute("SELECT * FROM mw_meldungen WHERE akte_id=? ORDER BY id DESC", (z["id"],)).fetchall()
    paesse = con.execute("SELECT * FROM pw_paesse WHERE akte_id=? ORDER BY id DESC", (z["id"],)).fetchall()
    if ws and ws["art"] != "abmeldung":
        aktuell = f'{esc(ws["staat_name"])}' + (f' · {esc(ws["anschrift"])}' if ws["anschrift"] else "")
    elif ws:
        aktuell = "Im Ausland (abgemeldet)"
    else:
        aktuell = '<span class="s-offen">Kein Wohnsitz gemeldet</span>'
    import lichtbild
    h = (f'<h2>Melde- und Passwesen</h2>' + lichtbild.abschnitt(request, con, z, schreiben) + amt.daten_tabelle([("Aktueller Wohnsitz", aktuell)])
         + amt.tabelle(["Meldung", "Teilstaat", "Anschrift (IC)", "Gültig ab (IC)", "Erfasst"],
                       [(esc(MELDEARTEN.get(m["art"], m["art"])), esc(m["staat_name"]), esc(m["anschrift"] or "–"), esc(m["gueltig_ab"] or "–"),
                         f'{esc(m["autor_name"])} · {amt._zeit(m["zeit"], False)}') for m in meldungen], "Keine Meldungen.")
         + amt.tabelle(["Passnummer", "Art", "Ausgestellt", "Gültig bis", "Stand"],
                       [(f'<a class="mw-nr" href="{PFAD}paesse/{x["id"]}/">{esc(x["nummer"])}</a>', esc(PASSARTEN[x["art"]][0]),
                         amt._zeit(x["ausgestellt"], False), _datum(x["gueltig_bis"]), pass_marke(x)) for x in paesse], "Keine Pässe ausgestellt."))
    akt = f'<a class="btn zweit" href="{p}meldebescheinigung">{amt.ic("file-down")}Meldebescheinigung</a>' if ws else ""
    if schreiben:
        st = "".join(f'<option value="{esc(s["id"])}"{" selected" if ws and ws["staat"] == s["id"] else ""}>{esc(s["name"])}</option>' for s in staaten(con))
        arten = "".join(f'<option value="{x}"{" selected" if (x == "anmeldung") == (not ws) and x != "abmeldung" else ""}>{esc(t)}</option>'
                        for x, t in MELDEARTEN.items())
        buerger = z["status"] == "staatsbuerger"
        pa = "".join(f'<option value="{x}">{esc(v[0])} ({v[2]} Jahre)</option>' for x, v in PASSARTEN.items() if v[3] == buerger)
        f = amt._feld
        h += (f'<details class="mw-form"><summary class="btn zweit">{amt.ic("home")}Wohnsitz melden</summary>'
              f'<form class="formular" method="post" action="{p}meldung">{amt.csrf_feld(request)}<div class="felder">'
              + f("ma", "Art der Meldung", f'<select id="ma" name="art">{arten}</select>')
              + f("ms", "Teilstaat", f'<select id="ms" name="staat">{st}</select>', "Bei Abmeldung ins Ausland ohne Bedeutung.")
              + f("mn", "Anschrift (IC)", '<input type="text" id="mn" name="anschrift" maxlength="160" placeholder="Straße, Ort">')
              + f("mg", "Gültig ab (IC-Datum)", '<input type="text" id="mg" name="gueltig_ab" maxlength="40">')
              + f'</div><div class="formular-fuss"><button class="btn" type="submit">{amt.ic("check")}Meldung erfassen</button></div></form></details>'
              f'<details class="mw-form"><summary class="btn zweit">{amt.ic("id-card")}Pass ausstellen</summary>')
        if not z["ic_name"]:
            h += '<p class="warnung">Ohne IC-Namen in den Stammdaten kann kein Pass ausgestellt werden.</p></details>'
        else:
            h += (f'<form class="formular" method="post" action="{p}pass">{amt.csrf_feld(request)}'
                  + ('' if buerger else '<p class="az">Kein Staatsbürger: nur ein Fremdenpass ist möglich.</p>')
                  + '<div class="felder">' + f("pa", "Passart", f'<select id="pa" name="art">{pa}</select>',
                                               "Ein gültiger Pass derselben Art wird dabei ungültig (ersetzt).")
                  + f("pb", "Bemerkung", '<input type="text" id="pb" name="bemerkung" maxlength="200">')
                  + f'</div><div class="formular-fuss"><button class="btn" type="submit">{amt.ic("id-card")}Pass ausstellen</button></div></form></details>')
        h += '<style>details.mw-form{display:inline-block;margin:10px 8px 0 0;vertical-align:top}details.mw-form[open]{display:block}details.mw-form summary{list-style:none;display:inline-flex}details.mw-form summary::-webkit-details-marker{display:none}details.mw-form[open] summary{margin-bottom:8px}</style>'
    return h + (f'<div class="aktionen" style="display:inline-flex">{akt}</div>' if akt else "")


def _akte(con, k, i):
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (i,)).fetchone() if str(i).isdigit() else None
    if not z:
        raise web.HTTPNotFound(text="Akte nicht gefunden.")
    if z["verschluss"] and not amt.darf_verschluss(k):
        raise web.HTTPForbidden(text="Die Akte steht unter Verschluss.")
    return z


async def meldung(request):
    k, form = await amt._post(request)
    con = request.app["db"]
    z = _akte(con, k, request.match_info["id"])
    ziel = f'{BASIS}buerger/{z["id"]}/'
    art = str(form.get("art", ""))
    if art not in MELDEARTEN:
        raise web.HTTPBadRequest()
    alt = wohnsitz(con, z["id"])
    if art == "abmeldung":
        sid, sname = "ausland", "Ausland"
        if not alt or alt["art"] == "abmeldung":
            amt._umleiten(ziel, "Abmelden kann nur, wer im Reich gemeldet ist.", True)
    else:
        s = next((s for s in staaten(con) if s["id"] == str(form.get("staat", ""))), None)
        if not s:
            amt._umleiten(ziel, "Bitte einen Teilstaat wählen.", True)
        sid, sname = s["id"], s["name"]
        if art == "ummeldung" and (not alt or alt["art"] == "abmeldung"):
            art = "anmeldung"
        if art == "anmeldung" and alt and alt["art"] != "abmeldung":
            art = "ummeldung"
    anschrift, ab = amt._text(form, "anschrift", 160), amt._text(form, "gueltig_ab", 40)
    con.execute("INSERT INTO mw_meldungen (akte_id, art, staat, staat_name, anschrift, gueltig_ab, zeit, autor_id, autor_name) VALUES (?,?,?,?,?,?,?,?,?)",
                (z["id"], art, sid, sname, anschrift, ab, int(time.time()), k["id"], k["name"]))
    von = f' (vorher: {alt["staat_name"]})' if alt and art != "anmeldung" else ""
    amt.eintrag(con, "akte", z["id"], "Wohnsitz: " + MELDEARTEN[art], f'{sname}{" · " + anschrift if anschrift else ""}{von}', k["id"], k["name"])
    con.execute("UPDATE amt_akten SET aktualisiert=? WHERE id=?", (int(time.time()), z["id"]))
    con.commit()
    amt._umleiten(ziel, f"{MELDEARTEN[art]} erfasst.")


async def pass_ausstellen(request):
    k, form = await amt._post(request)
    con = request.app["db"]
    z = _akte(con, k, request.match_info["id"])
    ziel = f'{BASIS}buerger/{z["id"]}/'
    art = str(form.get("art", ""))
    if art not in PASSARTEN:
        raise web.HTTPBadRequest()
    name, praefix, jahre, nur_buerger = PASSARTEN[art]
    if not z["ic_name"]:
        amt._umleiten(ziel, "Ohne IC-Namen kann kein Pass ausgestellt werden.", True)
    if nur_buerger != (z["status"] == "staatsbuerger"):
        amt._umleiten(ziel, f"Ein {name} wird nur an {'Staatsbürger' if nur_buerger else 'Nicht-Staatsbürger'} ausgestellt.", True)
    heute = date.today()
    try:
        bis = heute.replace(year=heute.year + jahre)
    except ValueError:   # 29. Februar
        bis = heute.replace(year=heute.year + jahre, day=28)
    jetzt = int(time.time())
    for alt in con.execute("SELECT * FROM pw_paesse WHERE akte_id=? AND art=? AND status='gueltig'", (z["id"], art)).fetchall():
        con.execute("UPDATE pw_paesse SET status='ungueltig', grund=?, ungueltig_zeit=? WHERE id=?", (ERSETZT, jetzt, alt["id"]))
        _eintrag(con, alt["id"], "Pass ungültig", ERSETZT + ".", k)
    nr = _nummer(con, praefix)
    pid = con.execute("INSERT INTO pw_paesse (nummer, akte_id, konto_id, inhaber, geburt, art, ausgestellt, gueltig_bis, bemerkung, autor_id, autor_name) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (nr, z["id"], z["konto_id"], z["ic_name"], z["ic_geburt"], art, jetzt, bis.isoformat(),
                                                         amt._text(form, "bemerkung", 200), k["id"], k["name"])).lastrowid
    _eintrag(con, pid, "Pass ausgestellt", f"{name} Nr. {nr}, gültig bis {bis.strftime('%d.%m.%Y')}.", k)
    amt.eintrag(con, "akte", z["id"], "Pass ausgestellt", f"{name} Nr. {nr}, gültig bis {bis.strftime('%d.%m.%Y')}.", k["id"], k["name"])
    con.commit()
    await request.app["discord"].dm(z["konto_id"], f"Die Reichsverwaltung hat dir einen {name} ausgestellt.\nPassnummer: {nr}\n"
                                                   f"Inhaber: {z['ic_name']}\nGültig bis: {bis.strftime('%d.%m.%Y')}\n"
                                                   "Bitte bewahre die Nummer gut auf; bei Verlust oder Diebstahl melde dich bei der Reichsverwaltung."
                                                   + "".join(fn(nr) for fn in DM_ZUSATZ))
    for fn in AUSGESTELLT:
        fn(request, con, z, art, nr, k)
    amt._umleiten(ziel, f"{name} {nr} ausgestellt.")


@amt._beamter
async def meldebescheinigung(request):
    con = request.app["db"]
    k = request["konto"]
    z = _akte(con, k, request.match_info["id"])
    ws = wohnsitz(con, z["id"])
    if not ws:
        raise web.HTTPNotFound(text="Kein Wohnsitz gemeldet.")
    hist = con.execute("SELECT * FROM mw_meldungen WHERE akte_id=? ORDER BY id", (z["id"],)).fetchall()
    inhalt = (f'<h1>Meldebescheinigung</h1><p class="az">Reichsverwaltung · Melderegister · {amt.az_akte(z["id"])}</p>'
              '<p>Hiermit wird bescheinigt, dass die nachstehend bezeichnete Person im Melderegister des Imperium Germanicum wie folgt erfasst ist.</p>'
              + amt.daten_tabelle([("Name (IC)", esc(z["ic_name"] or z["name"])), ("Geburtsdatum (IC)", esc(z["ic_geburt"] or "–")),
                                   ("Status", amt.akte_marke(z["status"])),
                                   ("Wohnsitz", "Ausland (abgemeldet)" if ws["art"] == "abmeldung" else esc(ws["staat_name"])),
                                   ("Anschrift (IC)", esc(ws["anschrift"] or "–")), ("Gemeldet seit (IC)", esc(ws["gueltig_ab"] or "–"))])
              + '<h2>Meldehistorie</h2>' + amt.tabelle(["Meldung", "Teilstaat", "Anschrift", "Gültig ab"],
                                                       [(esc(MELDEARTEN[m["art"]]), esc(m["staat_name"]), esc(m["anschrift"] or "–"), esc(m["gueltig_ab"] or "–")) for m in hist]))
    return await amt._pdf_antwort(request, "meldebescheinigung-" + amt.az_akte(z["id"]), "Meldebescheinigung", inhalt,
                                  stelle=amt.STELLE_REICHSBEHOERDEN, az=amt.az_akte(z["id"]), einstufung="",
                                  doktyp="Amtliche Bescheinigung", unterzeile="Reichsverwaltung · Meldebehörde",
                                  qr_url=qr.kurzlink(amt.az_akte(z["id"])))


# ---------------------------------------------------------------- Passregister

@amt._beamter
async def paesse(request):
    con = request.app["db"]
    sa, _ = amt.sperren(con, request["konto"])
    q, st = request.query.get("q", "").strip()[:80], request.query.get("status", "")
    rows = con.execute("SELECT * FROM pw_paesse ORDER BY id DESC").fetchall()
    if q:
        ql = q.lower()
        rows = [p for p in rows if ql in p["nummer"].lower() or (p["akte_id"] not in sa and ql in p["inhaber"].lower())]
    if st:
        rows = [p for p in rows if pass_status(p)[0] == st]
    sn = int(request.query["seite"]) if request.query.get("seite", "").isdigit() and int(request.query["seite"]) > 0 else 1
    gesamt = len(rows)
    rows = rows[(sn - 1) * SEITE: sn * SEITE]
    zeilen = [(f'<a class="mw-nr" href="{PFAD}paesse/{p["id"]}/">{esc(p["nummer"])}</a>', esc(PASSARTEN[p["art"]][0]),
               amt._verschluss_marke() if p["akte_id"] in sa else esc(p["inhaber"]), amt._zeit(p["ausgestellt"], False), _datum(p["gueltig_bis"]),
               pass_marke(p)) for p in rows]
    opt = "".join(f'<option value="{x}"{" selected" if x == st else ""}>{t}</option>' for x, t in
                  [("", "Alle"), ("gueltig", "Gültig"), ("abgelaufen", "Abgelaufen"), ("fahndung", "In Fahndung"), ("ungueltig", "Ungültig")])
    basis = f"?q={esc(q)}&amp;status={esc(st)}"
    nav_ = (f'<a href="{basis}&amp;seite={sn - 1}">← Zurück</a>' if sn > 1 else "") + \
           (f'<a href="{basis}&amp;seite={sn + 1}">Weiter →</a>' if sn * SEITE < gesamt else "")
    inhalt = (f'<p class="az">{gesamt} Pässe. Ausgestellt wird in der Bürgerakte.</p>'
              f'<form class="zeile" method="get"><div><label for="q">Suche</label><input type="search" id="q" name="q" value="{esc(q)}" placeholder="Passnummer, Inhaber"></div>'
              f'<div><label for="st">Stand</label><select id="st" name="status">{opt}</select></div>'
              f'<button class="btn" type="submit">{amt.ic("search")}Suchen</button></form>'
              + amt.tabelle(["Passnummer", "Art", "Inhaber (IC)", "Ausgestellt", "Gültig bis", "Stand"], zeilen, "Keine Pässe gefunden.")
              + f'<div class="seiten">{nav_}</div>')
    return _seite(request, "Passregister", "paesse", inhalt)


def _pass(con, k, i):
    p = con.execute("SELECT * FROM pw_paesse WHERE id=?", (i,)).fetchone() if str(i).isdigit() else None
    if not p:
        raise web.HTTPNotFound(text="Pass nicht gefunden.")
    a = con.execute("SELECT verschluss FROM amt_akten WHERE id=?", (p["akte_id"],)).fetchone()
    if a and a["verschluss"] and not amt.darf_verschluss(k):
        raise web.HTTPForbidden(text="Die Akte des Inhabers steht unter Verschluss.")
    return p, a is not None


def _pass_daten(p, akte_da):
    s, _t = pass_status(p)
    daten = [("Passnummer", f'<span class="mw-nr">{esc(p["nummer"])}</span>'), ("Art", esc(PASSARTEN[p["art"]][0])), ("Stand", pass_marke(p)),
             ("Inhaber (IC)", esc(p["inhaber"])), ("Geburtsdatum (IC)", esc(p["geburt"] or "–")),
             ("Bürgerakte", f'<a href="{BASIS}buerger/{p["akte_id"]}/">{amt.az_akte(p["akte_id"])}</a>' if akte_da else "– (Akte gelöscht)"),
             ("Ausgestellt", f'{amt._zeit(p["ausgestellt"], False)} · Reichsverwaltung · {esc(p["autor_name"])}'), ("Gültig bis", _datum(p["gueltig_bis"]))]
    if p["status"] != "gueltig":
        daten.append(("Ungültig seit", f'{amt._zeit(p["ungueltig_zeit"])} · {esc(p["grund"])}'))
    if p["bemerkung"]:
        daten.append(("Bemerkung", esc(p["bemerkung"])))
    return amt.daten_tabelle(daten)


@amt._beamter
async def pass_ansicht(request):
    con, k = request.app["db"], request["konto"]
    p, akte_da = _pass(con, k, request.match_info["id"])
    s, _ = pass_status(p)
    verlauf = con.execute("SELECT * FROM pw_eintraege WHERE pass_id=? ORDER BY id DESC", (p["id"],)).fetchall()
    abfr = con.execute("SELECT * FROM pw_abfragen WHERE pass_id=? ORDER BY id DESC LIMIT 50", (p["id"],)).fetchall()
    h = (f'<h2>{esc(PASSARTEN[p["art"]][0])} <span class="mw-nr">{esc(p["nummer"])}</span></h2>' + _pass_daten(p, akte_da)
         + '<h2>Verlauf</h2>' + amt.verlauf_html(verlauf, "Keine Einträge.")
         + '<h2>Prüfungen durch Zoll und Polizei</h2>'
         + amt.tabelle(["Zeit", "Beamter", "Dienststelle", "Ergebnis"], [(amt._zeit(a["zeit"]), esc(a["name"]), esc(a["stelle"]), esc(a["ergebnis"])) for a in abfr],
                       "Noch nie geprüft."))
    if amt.ist_beamter(k) and p["status"] == "gueltig":
        gr = "".join(f"<option>{esc(g)}</option>" for g in GRUENDE)
        h += (f'<h2>Für ungültig erklären</h2><form method="post" action="{PFAD}paesse/{p["id"]}/ungueltig">{amt.csrf_feld(request)}'
              f'<div class="felder">{amt._feld("ug", "Grund", f"<select id=ug name=grund>{gr}</select>", "Bei Diebstahl wird der Pass zur Fahndung ausgeschrieben; Zoll und Polizei sehen das bei der Prüfung.")}'
              f'{amt._feld("ub", "Vermerk", "<input type=text id=ub name=text maxlength=300>")}</div>'
              f'<div class="aktionen"><button class="btn gefahr" type="submit">{amt.ic("x")}Pass für ungültig erklären</button></div></form>')
    h += f'<div class="aktionen">{"".join(fn(p, con) for fn in PASS_KNOEPFE)}<a class="btn zweit" href="{PFAD}paesse/{p["id"]}/pdf">{amt.ic("file-down")}PDF</a><a class="btn zweit" href="{PFAD}paesse/">{amt.ic("arrow-left")}Zum Passregister</a></div>'
    return _seite(request, "Pass " + p["nummer"], "paesse", h)


@amt._beamter
async def pass_pdf(request):
    con, k = request.app["db"], request["konto"]
    p, akte_da = _pass(con, k, request.match_info["id"])
    verlauf = con.execute("SELECT * FROM pw_eintraege WHERE pass_id=? ORDER BY id DESC", (p["id"],)).fetchall()
    inhalt = (f'<h1>Passregisterauszug</h1><p class="az">Reichsverwaltung · Passregister · {esc(p["nummer"])}</p>'
              + _pass_daten(p, akte_da) + "<h2>Verlauf</h2>" + amt.verlauf_html(verlauf, "Keine Einträge."))
    return await amt._pdf_antwort(request, "pass-" + p["nummer"], "Passregisterauszug " + p["nummer"], inhalt,
                                  stelle=amt.STELLE_REICHSBEHOERDEN, az=p["nummer"], doktyp="Registerauszug",
                                  unterzeile="Reichsverwaltung · Passbehörde")


async def pass_ungueltig(request):
    k, form = await amt._post(request)
    con = request.app["db"]
    p, _ = _pass(con, k, request.match_info["id"])
    ziel = f'{PFAD}paesse/{p["id"]}/'
    if p["status"] != "gueltig":
        amt._umleiten(ziel, "Der Pass ist bereits ungültig.", True)
    grund = str(form.get("grund", ""))
    if grund not in GRUENDE:
        raise web.HTTPBadRequest()
    text = amt._text(form, "text", 300)
    con.execute("UPDATE pw_paesse SET status='ungueltig', grund=?, ungueltig_zeit=? WHERE id=?", (grund, int(time.time()), p["id"]))
    _eintrag(con, p["id"], "Pass ungültig", grund + (f": {text}" if text else "."), k)
    amt.eintrag(con, "akte", p["akte_id"], "Pass ungültig", f'{PASSARTEN[p["art"]][0]} Nr. {p["nummer"]}: {grund}' + (f" – {text}" if text else ""), k["id"], k["name"])
    con.commit()
    amt._umleiten(ziel, "Pass für ungültig erklärt" + (" und zur Fahndung ausgeschrieben." if grund.startswith("Diebstahl") else "."))


@amt._beamter
async def abfragen(request):
    con = request.app["db"]
    rows = con.execute("SELECT * FROM pw_abfragen ORDER BY id DESC LIMIT 300").fetchall()
    zeilen = [(amt._zeit(a["zeit"]), esc(a["name"]), esc(a["stelle"]),
               f'<a class="mw-nr" href="{PFAD}paesse/{a["pass_id"]}/">{esc(a["nummer"])}</a>' if a["pass_id"] else f'<span class="mw-nr">{esc(a["nummer"])}</span>',
               esc(a["ergebnis"])) for a in rows]
    inhalt = ('<p class="az">Jede Passprüfung durch Zoll, Polizei oder Reichsverwaltung wird hier festgehalten (die letzten 300).</p>'
              + amt.tabelle(["Zeit", "Beamter", "Dienststelle", "Passnummer", "Ergebnis"], zeilen, "Noch keine Prüfungen."))
    return _seite(request, "Abfrageprotokoll", "abfragen", inhalt)


# ---------------------------------------------------------------- Passprüfung (Zoll, Polizei)

async def passpruefung(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    if not darf_pruefen(k):
        return web.Response(status=403, content_type="text/html", text=amt.rahmen(
            "Kein Zugang", "passpruefung", '<div class="warnung">Die Passprüfung ist Zoll, Polizei und Reichsverwaltung vorbehalten.</div>', k, request["csrf"]))
    con = request.app["db"]
    nr = "".join(c for c in request.query.get("nr", "").upper() if c.isalnum())[:12]
    erg = ""
    if nr:
        p = con.execute("SELECT * FROM pw_paesse WHERE nummer=?", (nr,)).fetchone()
        if not p:
            ergebnis, erg = "Nicht im Register", (
                f'<div class="mw-pass fahndung"><h3>Kein Pass mit dieser Nummer</h3><p class="mw-gross nr">{esc(nr)}</p>'
                '<p>Die Nummer ist im Passregister des Reiches nicht verzeichnet. Das Dokument ist als <b>nicht echt</b> zu behandeln.</p></div>')
        else:
            a = con.execute("SELECT verschluss FROM amt_akten WHERE id=?", (p["akte_id"],)).fetchone()
            s, t = pass_status(p)
            if not a and s == "gueltig":
                s, t = "ungueltig", "Ungültig (Inhaberakte gelöscht)"
            gesperrt = bool(a and a["verschluss"]) and not amt.darf_verschluss(k)
            ergebnis = t
            hinweis = {"gueltig": "Das Dokument ist gültig.",
                       "abgelaufen": "Das Dokument ist abgelaufen. Der Inhaber muss bei der Reichsverwaltung einen neuen Pass beantragen.",
                       "fahndung": "Das Dokument ist als gestohlen gemeldet. <b>Dokument sicherstellen, Personalien feststellen, Polizei verständigen.</b>",
                       "ungueltig": f'Das Dokument ist ungültig ({esc(p["grund"])}) und einzuziehen.'}[s]
            daten = [("Art", esc(PASSARTEN[p["art"]][0])), ("Gültig bis", _datum(p["gueltig_bis"]))]
            if not gesperrt:
                daten[1:1] = [("Inhaber (IC)", esc(p["inhaber"])), ("Geburtsdatum (IC)", esc(p["geburt"] or "–"))]
            erg = (f'<div class="mw-pass {s}"><h3>{esc(t)}</h3><p class="mw-gross nr">{esc(p["nummer"])}</p>{amt.daten_tabelle(daten)}'
                   + ('<p class="az">Inhaberdaten gesperrt (Verschlusssache).</p>' if gesperrt else "") + f'<p>{hinweis}</p>'
                   f'<p><a class="btn zweit" href="{PRUEF}{esc(p["nummer"])}/">Alle Infos zur Person und Dokument ansehen</a></p></div>')
        con.execute("INSERT INTO pw_abfragen (zeit, konto_id, name, stelle, nummer, pass_id, ergebnis) VALUES (?,?,?,?,?,?,?)",
                    (int(time.time()), k["id"], k["name"], _stelle_von(k), nr, p["id"] if p else None, ergebnis))
        con.commit()
    inhalt = (CSS + f'<h1>{amt.ic("scan-search")} Passprüfung</h1>'
              '<p class="az">Abgleich eines Ausweisdokuments mit dem Passregister. Jede Prüfung wird mit Name und Dienststelle protokolliert.</p>'
              + "".join(fn(request, k) for fn in PRUEF_ZUSATZ) +
              f'<form class="zeile" method="get"><div><label for="nr">Passnummer</label><input type="search" id="nr" name="nr" value="{esc(nr)}" '
              'maxlength="12" autocomplete="off" autocapitalize="characters" class="mw-nr" required></div>'
              f'<button class="btn" type="submit">{amt.ic("search")}Prüfen</button></form>{erg}')
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen("Passprüfung", "passpruefung", inhalt, k, request["csrf"]))


def registrieren(app):
    einrichten(app["db"])
    amt.NAV_EXTRA.append(("Akten", nav_akten))
    amt.NAV_EXTRA.append(("Dienste", nav_dienste))
    amt.AKTE_ZUSATZ.append(akte_abschnitt)
    app.router.add_get(PFAD, register)
    app.router.add_get(PFAD + "paesse/", paesse)
    app.router.add_get(PFAD + "paesse/{id}/", pass_ansicht)
    app.router.add_get(PFAD + "paesse/{id}/pdf", pass_pdf)
    app.router.add_post(PFAD + "paesse/{id}/ungueltig", pass_ungueltig)
    app.router.add_get(PFAD + "abfragen/", abfragen)
    app.router.add_get(PRUEF, passpruefung)
    app.router.add_post(BASIS + "buerger/{id}/meldung", meldung)
    app.router.add_post(BASIS + "buerger/{id}/pass", pass_ausstellen)
    app.router.add_get(BASIS + "buerger/{id}/meldebescheinigung", meldebescheinigung)
