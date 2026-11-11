"""Amtshilfe: förmliche Ersuchen zwischen den Dienststellen (…/intern/amtshilfe/).

Die Unterbehörden sehen gegenseitig nichts (strikte Trennung). Braucht eine Stelle etwas von einer anderen (Auskunft, Akteneinsicht,
Personal, Vollzugshilfe …), stellt sie ein Amtshilfeersuchen. Die ersuchte Stelle prüft und entscheidet: gewährt, teilweise gewährt
oder abgelehnt, jeweils mit Antwort bzw. Begründung. Die Antwort ist der einzige Weg, auf dem Inhalte die Stelle wechseln.

Dienststellen: Kronkanzlei (Kronkanzler, Kaiser), Reichsverwaltung (Akten-Rolle, wie amt.ist_beamter), jede Reichsbehörde aus amt.BEHOERDEN, jede Landespolizei.
Sehen: nur Angehörige der ersuchenden und der ersuchten Stelle; Kaiser und Kronkanzler sehen alle Ersuchen.
Stellen: Angehörige der ersuchenden Stelle. Zurückziehen: Antragsteller oder Entscheider der ersuchenden Stelle, solange offen.
Entscheiden: Entscheider der ersuchten Stelle (Leitungsrollen der Behörde; Landespolizei: OF-9/OF-8 und Generaldirektor;
ohne festgelegte Leitung jedes Mitglied). Schriftwechsel (Rückfragen, Vermerke): beide Seiten.
Tabellen: ah_ersuchen, ah_eintraege. Aktenzeichen AH-JJJJ-NNNN.
"""
import secrets
import time
from datetime import date, datetime

from aiohttp import web

import amt
import anmeldung
import bereiche
import landespolizei

esc = amt.esc
BASIS = amt.BASIS
PFAD = BASIS + "amtshilfe/"
ARTEN = ["Auskunft über eine Person", "Akteneinsicht", "Übermittlung von Unterlagen / Beweismitteln", "Personelle Unterstützung",
         "Vollzugshilfe (Festnahme, Durchsuchung, Sicherstellung)", "Fachliche Stellungnahme", "Sonstiges"]
DRINGLICHKEIT = {"normal": "Normal", "eilig": "Eilig", "sofort": "Sofort (Gefahr im Verzug)"}
STATUS = {"eingegangen": "Eingegangen", "bearbeitung": "In Bearbeitung", "gewaehrt": "Gewährt", "teilweise": "Teilweise gewährt",
          "abgelehnt": "Abgelehnt", "zurueckgezogen": "Zurückgezogen"}
MARKE = {"eingegangen": "offen", "bearbeitung": "offen", "gewaehrt": "ok", "teilweise": "ok", "abgelehnt": "nein", "zurueckgezogen": "neutral"}
OFFEN = ("eingegangen", "bearbeitung")
MAX_PRO_STUNDE = 15
SEITE = 40

SCHEMA = """
CREATE TABLE IF NOT EXISTS ah_ersuchen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, jahr INTEGER NOT NULL, nr INTEGER NOT NULL,
    von TEXT NOT NULL, von_name TEXT NOT NULL, an TEXT NOT NULL, an_name TEXT NOT NULL,
    art TEXT NOT NULL, betreff TEXT NOT NULL, bezug TEXT NOT NULL DEFAULT '', person TEXT NOT NULL DEFAULT '',
    begruendung TEXT NOT NULL, dringlichkeit TEXT NOT NULL DEFAULT 'normal', frist TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'eingegangen', antwort TEXT NOT NULL DEFAULT '',
    antragsteller_id TEXT NOT NULL, antragsteller_name TEXT NOT NULL,
    bearbeiter_id TEXT NOT NULL DEFAULT '', bearbeiter_name TEXT NOT NULL DEFAULT '',
    entscheider_name TEXT NOT NULL DEFAULT '', entschieden INTEGER,
    erstellt INTEGER NOT NULL, aktualisiert INTEGER NOT NULL, UNIQUE (jahr, nr));
CREATE INDEX IF NOT EXISTS ah_ersuchen_von ON ah_ersuchen (von, status);
CREATE INDEX IF NOT EXISTS ah_ersuchen_an ON ah_ersuchen (an, status);
CREATE TABLE IF NOT EXISTS ah_eintraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ersuchen_id INTEGER NOT NULL, zeit INTEGER NOT NULL, art TEXT NOT NULL, text TEXT NOT NULL,
    autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '', seite TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS ah_eintraege_e ON ah_eintraege (ersuchen_id);
"""

amt.ICONS.update({
    "handshake": '<path d="m11 17 2 2a1 1 0 1 0 3-3"/><path d="m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.88-3.88a3 3 0 0 0-4.24 0l-.88.88a1 1 0 1 1-3-3l2.81-2.81a5.79 5.79 0 0 1 7.06-.87l.47.28a2 2 0 0 0 1.42.25L21 4"/>'
                 '<path d="m21 3 1 11h-2"/><path d="M3 3 2 14l6.5 6.5a1 1 0 1 0 3-3"/><path d="M3 4h8"/>',
    "send": '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
})
amt._ART_ICON[0:0] = [("gewährt", "check", "ok"), ("abgelehnt", "x", "rot"), ("zurückgezogen", "undo-2", ""), ("ersuchen gestellt", "send", "ok"),
                      ("übernommen", "user-check", ""), ("schriftwechsel", "notebook-pen", "blau")]

_CON = None


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Dienststellen und Rechte

def stellen(con=None):
    """Alle Dienststellen: Kronkanzlei (Kronkanzler, Kaiser), Reichsverwaltung, Reichsbehörden, Landespolizeien."""
    st = [{"id": "kanzlei", "name": "Kronkanzlei", "art": "kanzlei"}, {"id": "rv", "name": "Reichsverwaltung", "art": "rv"}]
    st += [{"id": b["schl"], "name": b["name"], "art": "behoerde", "b": b} for b in amt.BEHOERDEN]
    st += [{"id": "lp-" + s["id"], "name": "Landespolizei " + s["kurz"], "art": "lp", "s": s} for s in landespolizei.staaten(con or _CON)]
    return st


def stelle(sid, con=None):
    return next((s for s in stellen(con) if s["id"] == sid), None)


def angehoerig(rollen, st):
    rollen = set(rollen)
    if st["art"] == "kanzlei":
        return amt.ROLLE_KANZLER in rollen
    if st["art"] == "rv":
        return amt.ROLLE_AKTEN in rollen and not (amt.ROLLEN_AKTEN_NIE & rollen)
    if st["art"] == "behoerde":
        return bool(set(st["b"]["rollen"]) & rollen)
    return landespolizei.mitglied(rollen, st["s"])


def entscheider_rollen(rollen, st):
    rollen = set(rollen)
    if not angehoerig(rollen, st):
        return False
    if st["art"] == "behoerde" and st["b"]["leitung"]:
        return bool(set(st["b"]["leitung"]) & rollen)
    if st["art"] == "lp":
        return bool({landespolizei.ROLLE_LPD, landespolizei.ROLLE_PD} & rollen)
    return True


def alle(k):
    return bereiche._alle(k)


def meine(k, con=None):
    """Dienststellen, denen das Konto angehört (der Kaiser handelt über die Kronkanzlei). Kaiser und Kronkanzler sehen und entscheiden
    darüber hinaus alle Ersuchen (Reiter „Alle Ersuchen“)."""
    if not k or not k["mitglied"]:
        return []
    return [s for s in stellen(con) if angehoerig(k["rollen"], s) or (s["art"] == "kanzlei" and alle(k))]


def entscheider(k, st):
    return alle(k) or entscheider_rollen(k["rollen"], st) or (st["art"] == "lp" and landespolizei.ROLLE_GD in k["rollen"])


def seite(k, e, con=None):
    """'an' (ersuchte Stelle), 'von' (ersuchende Stelle) oder None aus Sicht des Kontos."""
    ids = {s["id"] for s in meine(k, con)}
    if e["an"] in ids:
        return "an"
    if e["von"] in ids:
        return "von"
    return None


def az(e):
    return f'AH-{e["jahr"]}-{e["nr"]:04d}'


def _marke(e):
    m = amt.status_marke(MARKE.get(e["status"], "neutral"), STATUS.get(e["status"], e["status"]))
    if e["status"] in OFFEN and e["frist"] and e["frist"] < date.today().isoformat():
        m += " " + amt.status_marke("nein", "Frist überschritten")
    if e["status"] in OFFEN and e["dringlichkeit"] != "normal":
        m += " " + amt.status_marke("nein", DRINGLICHKEIT[e["dringlichkeit"]].split(" ")[0])
    return m


def _frist(f):
    try:
        return date.fromisoformat(f).strftime("%d.%m.%Y")
    except ValueError:
        return "–"


def nav(k):
    return [("amtshilfe", "handshake", "Amtshilfe", "amtshilfe/")] if meine(k) else []


def offen_eingang(con, k):
    ids = [s["id"] for s in meine(k, con) if entscheider(k, s)]
    if not ids:
        return 0
    return con.execute(f"SELECT COUNT(*) FROM ah_ersuchen WHERE status IN ('eingegangen','bearbeitung') AND an IN ({','.join('?' * len(ids))})",
                       ids).fetchone()[0]


# ---------------------------------------------------------------- Rahmen

async def _konto(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    if not meine(k, request.app["db"]):
        return k, None
    return k, True


def _kein_zugang(request, k):
    return web.Response(status=403, content_type="text/html", text=amt.rahmen(
        "Kein Zugang", "amtshilfe", '<div class="warnung">Amtshilfe steht nur Angehörigen einer Dienststelle offen.</div>', k, request["csrf"]))


async def _form(request):
    k, ok = await _konto(request)
    if not ok:
        raise web.HTTPForbidden(text="Amtshilfe steht nur Angehörigen einer Dienststelle offen.")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    return k, form


def _ersuchen(con, k, i):
    e = con.execute("SELECT * FROM ah_ersuchen WHERE id=?", (i,)).fetchone() if str(i).isdigit() else None
    if not e:
        raise web.HTTPNotFound(text="Ersuchen nicht gefunden.")
    if not alle(k) and not seite(k, e, con):
        raise web.HTTPForbidden(text="Dieses Ersuchen betrifft keine deiner Dienststellen.")
    return e


def _reiter(k, aktiv, n_ein=0):
    teile = [("eingang", "Eingang" + (f" ({n_ein})" if n_ein else ""), "?ansicht=eingang"), ("ausgang", "Ausgang", "?ansicht=ausgang")]
    if alle(k):
        teile.append(("alle", "Alle Ersuchen", "?ansicht=alle"))
    teile.append(("neu", "Neues Ersuchen", "neu/"))
    return '<p class="reiter">' + " ".join(f'<a href="{PFAD}{u}" class="{"aktiv" if x == aktiv else ""}">{esc(t)}</a>' for x, t, u in teile) + "</p>"


CSS = """<style>.ah-text{white-space:pre-wrap;word-break:break-word}.ah-weg{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:15px;margin:4px 0 14px}
.ah-weg b{border:1px solid var(--linie);border-radius:8px;padding:4px 10px;font-weight:600}.ah-antwort{border:1px solid var(--linie);border-left:4px solid var(--ink);border-radius:8px;padding:12px 14px;margin:10px 0}</style>"""


def _seite(request, k, titel, aktiv, inhalt, n_ein=0):
    kopf = f'<h1>{amt.ic("handshake")} Amtshilfe</h1>{amt.meldung(request)}{_reiter(k, aktiv, n_ein)}'
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, "amtshilfe", CSS + kopf + inhalt, k, request["csrf"]))


def _eintrag(con, eid, art, text, k=None, seite_=""):
    con.execute("INSERT INTO ah_eintraege (ersuchen_id, zeit, art, text, autor_id, autor_name, seite) VALUES (?,?,?,?,?,?,?)",
                (eid, int(time.time()), art, text, k["id"] if k else None, k["name"] if k else "System", seite_))


async def _benachrichtigen(request, st, text, ausser=None):
    """DM an die Entscheider einer Dienststelle (höchstens 8; ohne festgelegte Leitung niemand, um Massen-DMs zu vermeiden)."""
    if st["art"] == "rv" or (st["art"] == "behoerde" and not st["b"]["leitung"]):
        return
    ziel = [m for m in await request.app["discord"].mitglieder() if m["id"] != ausser and entscheider_rollen(m["rollen"], st)][:8]
    for m in ziel:
        await request.app["discord"].dm(m["id"], text)


# ---------------------------------------------------------------- Seiten

async def liste(request):
    k, ok = await _konto(request)
    if not ok:
        return _kein_zugang(request, k)
    con = request.app["db"]
    ansicht = request.query.get("ansicht", "eingang")
    if ansicht not in ("eingang", "ausgang", "alle") or (ansicht == "alle" and not alle(k)):
        ansicht = "eingang"
    eigene = meine(k, con)
    st_filter = request.query.get("stelle", "")
    ids = [s["id"] for s in eigene if not st_filter or s["id"] == st_filter]
    status = request.query.get("status", "offen")
    wo, par = [], []
    if ansicht != "alle":
        wo.append(f"{'an' if ansicht == 'eingang' else 'von'} IN ({','.join('?' * len(ids)) or 'NULL'})")
        par += ids
    elif st_filter:
        wo.append("(an=? OR von=?)")
        par += [st_filter, st_filter]
    if status == "offen":
        wo.append("status IN ('eingegangen','bearbeitung')")
    elif status in STATUS:
        wo.append("status=?")
        par.append(status)
    q = request.query.get("q", "").strip()[:80]
    if q:
        wo.append("(betreff LIKE ? OR person LIKE ? OR bezug LIKE ? OR von_name LIKE ? OR an_name LIKE ? OR ('AH-' || jahr || '-' || printf('%04d', nr)) LIKE ?)")
        par += [f"%{q}%"] * 6
    w = " WHERE " + " AND ".join(wo) if wo else ""
    sn = int(request.query["seite"]) if request.query.get("seite", "").isdigit() and int(request.query["seite"]) > 0 else 1
    gesamt = con.execute(f"SELECT COUNT(*) FROM ah_ersuchen{w}", par).fetchone()[0]
    rows = con.execute(f"SELECT * FROM ah_ersuchen{w} ORDER BY (status IN ('eingegangen','bearbeitung')) DESC, "
                       f"(dringlichkeit='sofort') DESC, (dringlichkeit='eilig') DESC, aktualisiert DESC LIMIT ? OFFSET ?",
                       par + [SEITE, (sn - 1) * SEITE]).fetchall()
    gegen = "von_name" if ansicht == "eingang" else "an_name"
    kopf = ["Aktenzeichen", "Betreff", "Ersuchende Stelle" if ansicht == "eingang" else "Ersuchte Stelle", "Stand", "Frist", "Zuletzt"]
    if ansicht == "alle":
        kopf[2] = "Von → An"
    zeilen = [(f'<a href="{PFAD}{e["id"]}/">{az(e)}</a>', esc(e["betreff"]),
               esc(f'{e["von_name"]} → {e["an_name"]}' if ansicht == "alle" else e[gegen]), _marke(e),
               _frist(e["frist"]) if e["frist"] else "–", amt._zeit(e["aktualisiert"], False)) for e in rows]
    st_opt = '<option value="">Alle meine Stellen</option>' + "".join(
        f'<option value="{esc(s["id"])}"{" selected" if s["id"] == st_filter else ""}>{esc(s["name"])}</option>' for s in eigene)
    stat_opt = "".join(f'<option value="{x}"{" selected" if x == status else ""}>{esc(t)}</option>'
                       for x, t in [("offen", "Offen"), ("", "Alle")] + list(STATUS.items()))
    basis = f"?ansicht={ansicht}&amp;stelle={esc(st_filter)}&amp;status={esc(status)}&amp;q={esc(q)}"
    nav_ = (f'<a href="{basis}&amp;seite={sn - 1}">← Zurück</a>' if sn > 1 else "") + \
           (f'<a href="{basis}&amp;seite={sn + 1}">Weiter →</a>' if sn * SEITE < gesamt else "")
    erkl = {"eingang": "Ersuchen anderer Stellen an deine Dienststelle(n).", "ausgang": "Ersuchen, die deine Dienststelle(n) gestellt haben.",
            "alle": "Alle Ersuchen im Reich (Kaiser und Kronkanzler)."}[ansicht]
    inhalt = (f'<p class="az">{erkl} {gesamt} Treffer.</p>'
              f'<form class="zeile" method="get"><input type="hidden" name="ansicht" value="{ansicht}">'
              f'<div><label for="q">Suche</label><input type="search" id="q" name="q" value="{esc(q)}" placeholder="Az., Betreff, Person"></div>'
              f'<div><label for="sf">Dienststelle</label><select id="sf" name="stelle">{st_opt}</select></div>'
              f'<div><label for="ss">Stand</label><select id="ss" name="status">{stat_opt}</select></div>'
              f'<button class="btn" type="submit">{amt.ic("search")}Filtern</button></form>'
              + amt.tabelle(kopf, zeilen, "Keine Ersuchen.") + f'<div class="seiten">{nav_}</div>')
    return _seite(request, k, "Amtshilfe", ansicht, inhalt, offen_eingang(con, k))


async def neu(request):
    k, ok = await _konto(request)
    if not ok:
        return _kein_zugang(request, k)
    con = request.app["db"]
    eigene = meine(k, con)
    vorwahl = request.query.get("von", "")
    von = "".join(f'<option value="{esc(s["id"])}"{" selected" if s["id"] == vorwahl else ""}>{esc(s["name"])}</option>' for s in eigene)
    an = '<option value="">– bitte wählen –</option>' + "".join(
        f'<option value="{esc(s["id"])}"{" selected" if s["id"] == request.query.get("an") else ""}>{esc(s["name"])}</option>' for s in stellen(con))
    arten = "".join(f"<option>{esc(a)}</option>" for a in ARTEN)
    dr = "".join(f'<option value="{x}">{esc(t)}</option>' for x, t in DRINGLICHKEIT.items())
    f = amt._feld
    breit = lambda h: h.replace('class="feld"', 'class="feld breit"')
    import strafsachen
    inhalt = ('<p class="az">Die ersuchte Stelle entscheidet in eigener Zuständigkeit. Begründe, wofür die Hilfe benötigt wird; '
              'ohne Begründung wird ein Ersuchen regelmäßig abgelehnt.</p>'
              f'<form class="formular" method="post" action="{PFAD}neu">{amt.csrf_feld(request)}'
              '<fieldset><legend>Dienstweg</legend><div class="felder">'
              + f("von", "Ersuchende Stelle", f'<select id="von" name="von" required>{von}</select>')
              + f("an", "Ersuchte Stelle", f'<select id="an" name="an" required>{an}</select>')
              + '</div></fieldset><fieldset><legend>Ersuchen</legend><div class="felder">'
              + breit(f("be", "Betreff", '<input type="text" id="be" name="betreff" maxlength="160" required>'))
              + f("ar", "Art der Amtshilfe", f'<select id="ar" name="art">{arten}</select>')
              + f("dr", "Dringlichkeit", f'<select id="dr" name="dringlichkeit">{dr}</select>')
              + f("fr", "Erbetene Erledigung bis", f'<input type="date" id="fr" name="frist" min="{date.today().isoformat()}">', "Freiwillig.")
              + f("bz", "Eigenes Aktenzeichen (Bezug)", '<input type="text" id="bz" name="bezug" maxlength="80" placeholder="z. B. POL-HSB-2026-0004">')
              + breit(f("pe", "Betroffene Person", '<input type="text" id="pe" name="person" maxlength="200" list="personen">', "Falls das Ersuchen eine Person betrifft."))
              + breit(f("bg", "Sachverhalt und Begründung", '<textarea id="bg" name="begruendung" maxlength="6000" style="min-height:160px" required></textarea>'))
              + f'</div></fieldset><datalist id="personen">{strafsachen._personen(con)}</datalist>'
              f'<div class="formular-fuss"><a class="btn zweit" href="{PFAD}?ansicht=ausgang">Abbrechen</a>'
              f'<button class="btn" type="submit">{amt.ic("send")}Ersuchen stellen</button></div></form>')
    return _seite(request, k, "Neues Amtshilfeersuchen", "neu", inhalt)


def _t(form, feld, n):
    return " ".join(str(form.get(feld, "")).split())[:n]


def _block(form, feld, n):
    return str(form.get(feld, "")).replace("\r\n", "\n").strip()[:n]


async def neu_speichern(request):
    k, form = await _form(request)
    con = request.app["db"]
    von, an = stelle(str(form.get("von", "")), con), stelle(str(form.get("an", "")), con)
    ziel = f"{PFAD}neu/"
    if not von or von["id"] not in {s["id"] for s in meine(k, con)}:
        amt._umleiten(ziel, "Für diese ersuchende Stelle kannst du nicht handeln.", True)
    if not an:
        amt._umleiten(ziel, "Bitte die ersuchte Stelle wählen.", True)
    if an["id"] == von["id"]:
        amt._umleiten(ziel, "Eine Stelle kann sich nicht selbst um Amtshilfe ersuchen.", True)
    betreff, begr = _t(form, "betreff", 160), _block(form, "begruendung", 6000)
    if not betreff or not begr:
        amt._umleiten(ziel, "Betreff und Begründung sind Pflicht.", True)
    if con.execute("SELECT COUNT(*) FROM ah_ersuchen WHERE antragsteller_id=? AND erstellt>?", (k["id"], time.time() - 3600)).fetchone()[0] >= MAX_PRO_STUNDE:
        amt._umleiten(PFAD, "Zu viele Ersuchen in der letzten Stunde.", True)
    art = _t(form, "art", 80)
    art = art if art in ARTEN else "Sonstiges"
    dr = str(form.get("dringlichkeit", "normal"))
    dr = dr if dr in DRINGLICHKEIT else "normal"
    frist = str(form.get("frist", ""))[:10]
    try:
        date.fromisoformat(frist)
    except ValueError:
        frist = ""
    jahr = datetime.now(amt.BERLIN).year
    nr = (con.execute("SELECT MAX(nr) FROM ah_ersuchen WHERE jahr=?", (jahr,)).fetchone()[0] or 0) + 1
    jetzt = int(time.time())
    sp = {"jahr": jahr, "nr": nr, "von": von["id"], "von_name": von["name"], "an": an["id"], "an_name": an["name"], "art": art,
          "betreff": betreff, "bezug": _t(form, "bezug", 80), "person": _t(form, "person", 200), "begruendung": begr,
          "dringlichkeit": dr, "frist": frist, "antragsteller_id": k["id"], "antragsteller_name": k["name"], "erstellt": jetzt, "aktualisiert": jetzt}
    i = con.execute(f"INSERT INTO ah_ersuchen ({', '.join(sp)}) VALUES ({', '.join('?' * len(sp))})", list(sp.values())).lastrowid
    e = dict(sp, id=i)
    _eintrag(con, i, "Ersuchen gestellt", f'{von["name"]} ersucht {an["name"]} um Amtshilfe ({art}).', k, "von")
    con.commit()
    await _benachrichtigen(request, an, f'Neues Amtshilfeersuchen {az(e)} an {an["name"]} von {von["name"]}: „{betreff}“'
                                        f'{" – " + DRINGLICHKEIT[dr].upper() if dr != "normal" else ""}\nhttps://imperiumgermanicum.de{PFAD}{i}/', k["id"])
    amt._umleiten(f"{PFAD}{i}/", f"Ersuchen {az(e)} an {an['name']} gestellt.")


def _ansicht(request, k, e, con, druck=False):
    p = f'{PFAD}{e["id"]}/'
    csrf = amt.csrf_feld(request)
    sd = seite(k, e, con)
    an = stelle(e["an"], con)
    darf_ent = an is not None and entscheider(k, an) and (sd == "an" or alle(k))
    offen = e["status"] in OFFEN
    stamm = [("Aktenzeichen", az(e)), ("Stand", _marke(e)), ("Art", esc(e["art"])), ("Dringlichkeit", esc(DRINGLICHKEIT.get(e["dringlichkeit"], "–"))),
             ("Erbetene Erledigung bis", _frist(e["frist"]) if e["frist"] else "–"), ("Bezug (Az. der ersuchenden Stelle)", esc(e["bezug"] or "–")),
             ("Betroffene Person", esc(e["person"] or "–")), ("Gestellt", f'{esc(e["antragsteller_name"])} · {amt._zeit(e["erstellt"])}'),
             ("Sachbearbeitung", esc(e["bearbeiter_name"] or "– (noch nicht übernommen)"))]
    if e["entschieden"]:
        stamm.append(("Entschieden", f'{esc(e["entscheider_name"])} · {amt._zeit(e["entschieden"])}'))
    h = (f'<h2>{esc(e["betreff"])}</h2><div class="ah-weg"><b>{esc(e["von_name"])}</b>{amt.ic("arrow-right")}<b>{esc(e["an_name"])}</b></div>'
         + amt.daten_tabelle(stamm) + f'<h2>Sachverhalt und Begründung</h2><div class="ah-text">{esc(e["begruendung"])}</div>')
    if e["status"] in ("gewaehrt", "teilweise", "abgelehnt"):
        h += (f'<h2>{"Begründung der Ablehnung" if e["status"] == "abgelehnt" else "Antwort der ersuchten Stelle"}</h2>'
              f'<div class="ah-antwort"><p class="az">{esc(e["an_name"])} · {STATUS[e["status"]]}</p><div class="ah-text">{esc(e["antwort"])}</div></div>')
    es = con.execute("SELECT * FROM ah_eintraege WHERE ersuchen_id=? ORDER BY id DESC", (e["id"],)).fetchall()
    h += "<h2>Schriftwechsel und Verlauf</h2>" + amt.verlauf_html(es, "Keine Einträge.")
    if druck:
        return h
    if offen and (sd or alle(k)):
        h += (f'<form method="post" action="{p}vermerk">{csrf}<label for="vm">Rückfrage / Mitteilung an die {"ersuchende" if sd == "an" else "ersuchte"} Stelle</label>'
              f'<textarea id="vm" name="text" maxlength="4000" required></textarea>'
              f'<div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("notebook-pen")}Zum Schriftwechsel</button></div></form>')
    if offen and darf_ent:
        h += (f'<h2>Entscheidung</h2><form method="post" action="{p}entscheiden">{csrf}'
              f'<label for="aw">Antwort bzw. Begründung (Pflicht). Bei Gewährung: die erbetene Auskunft, Unterlagen oder Zusage.</label>'
              f'<textarea id="aw" name="antwort" maxlength="8000" style="min-height:140px" required></textarea>'
              f'<div class="aktionen"><button class="btn" type="submit" name="ergebnis" value="gewaehrt">{amt.ic("check")}Gewähren</button>'
              f'<button class="btn zweit" type="submit" name="ergebnis" value="teilweise">{amt.ic("check")}Teilweise gewähren</button>'
              f'<button class="btn zweit gefahr" type="submit" name="ergebnis" value="abgelehnt">{amt.ic("x")}Ablehnen</button></div></form>')
    akt = ""
    if offen and sd == "an" and e["bearbeiter_id"] != k["id"]:
        akt += (f'<form method="post" action="{p}uebernehmen" style="display:inline">{csrf}'
                f'<button class="btn zweit" type="submit">{amt.ic("user-check")}Sachbearbeitung übernehmen</button></form>')
    if offen and (sd == "von" or alle(k)) and (e["antragsteller_id"] == k["id"] or alle(k) or entscheider(k, stelle(e["von"], con) or {"art": "rv"})):
        akt += (f'<form method="post" action="{p}zurueckziehen" style="display:inline">{csrf}'
                f'<button class="btn zweit gefahr" type="submit">{amt.ic("undo-2")}Ersuchen zurückziehen</button></form>')
    akt += f'<a class="btn zweit" href="{p}pdf">{amt.ic("file-down")}PDF</a><a class="btn zweit" href="{PFAD}">{amt.ic("arrow-left")}Zur Liste</a>'
    return h + f'<div class="aktionen">{akt}</div>'


async def ansicht(request):
    k, ok = await _konto(request)
    if not ok:
        return _kein_zugang(request, k)
    con = request.app["db"]
    e = _ersuchen(con, k, request.match_info["id"])
    aktiv = {"an": "eingang", "von": "ausgang"}.get(seite(k, e, con), "alle")
    return _seite(request, k, az(e), aktiv, _ansicht(request, k, e, con))


async def pdf(request):
    k, ok = await _konto(request)
    if not ok:
        raise web.HTTPForbidden()
    con = request.app["db"]
    e = _ersuchen(con, k, request.match_info["id"])
    inhalt = f'<h1>Amtshilfeersuchen {az(e)}</h1><p class="az">{esc(e["von_name"])} an {esc(e["an_name"])}</p>' + _ansicht(request, k, e, con, True)
    von = stelle(e["von"], con) or {"art": "rv", "name": e["von_name"]}
    logo = {"kanzlei": amt.STELLE_KANZLER, "rv": amt.STELLE_REICHSBEHOERDEN, "lp": amt.stelle_behoerde("polizei")}.get(von["art"]) \
        or amt.stelle_behoerde(von["id"])
    unter = von["name"] if von["art"] in ("lp", "rv") else ""
    return await amt._pdf_antwort(request, az(e), f"Amtshilfeersuchen {az(e)}", inhalt, stelle=logo, az=az(e),
                                  doktyp="Amtshilfeersuchen", unterzeile=unter)


async def vermerk(request):
    k, form = await _form(request)
    con = request.app["db"]
    e = _ersuchen(con, k, request.match_info["id"])
    text = _block(form, "text", 4000)
    if not text or e["status"] not in OFFEN:
        amt._umleiten(f'{PFAD}{e["id"]}/', "Leer oder Ersuchen bereits abgeschlossen.", True)
    sd = seite(k, e, con) or ""
    wer = e["an_name"] if sd == "an" else e["von_name"] if sd == "von" else "Kanzlei"
    _eintrag(con, e["id"], "Schriftwechsel", f"[{wer}] {text}", k, sd)
    con.execute("UPDATE ah_ersuchen SET aktualisiert=? WHERE id=?", (int(time.time()), e["id"]))
    con.commit()
    link = f'https://imperiumgermanicum.de{PFAD}{e["id"]}/'
    if sd == "an" and e["antragsteller_id"] != k["id"]:
        await request.app["discord"].dm(e["antragsteller_id"], f'Rückfrage von {e["an_name"]} zu Amtshilfeersuchen {az(e)} („{e["betreff"]}“): {text[:400]}\n{link}')
    elif sd == "von" and e["bearbeiter_id"] and e["bearbeiter_id"] != k["id"]:
        await request.app["discord"].dm(e["bearbeiter_id"], f'Neue Mitteilung von {e["von_name"]} zu Amtshilfeersuchen {az(e)}: {text[:400]}\n{link}')
    amt._umleiten(f'{PFAD}{e["id"]}/', "Zum Schriftwechsel genommen.")


async def uebernehmen(request):
    k, _ = await _form(request)
    con = request.app["db"]
    e = _ersuchen(con, k, request.match_info["id"])
    if e["status"] not in OFFEN or seite(k, e, con) != "an":
        raise web.HTTPForbidden(text="Übernehmen kann nur die ersuchte Stelle, solange das Ersuchen offen ist.")
    con.execute("UPDATE ah_ersuchen SET status='bearbeitung', bearbeiter_id=?, bearbeiter_name=?, aktualisiert=? WHERE id=?",
                (k["id"], k["name"], int(time.time()), e["id"]))
    _eintrag(con, e["id"], "Übernommen", f'Sachbearbeitung übernommen durch {k["name"]}.', k, "an")
    con.commit()
    amt._umleiten(f'{PFAD}{e["id"]}/', "Sachbearbeitung übernommen.")


async def entscheiden(request):
    k, form = await _form(request)
    con = request.app["db"]
    e = _ersuchen(con, k, request.match_info["id"])
    an = stelle(e["an"], con)
    if not an or not entscheider(k, an) or not (seite(k, e, con) == "an" or alle(k)):
        raise web.HTTPForbidden(text="Entscheiden darf nur die Leitung der ersuchten Stelle.")
    if e["status"] not in OFFEN:
        amt._umleiten(f'{PFAD}{e["id"]}/', "Das Ersuchen ist bereits abgeschlossen.", True)
    erg, antwort = str(form.get("ergebnis", "")), _block(form, "antwort", 8000)
    if erg not in ("gewaehrt", "teilweise", "abgelehnt"):
        raise web.HTTPBadRequest()
    if not antwort:
        amt._umleiten(f'{PFAD}{e["id"]}/', "Antwort bzw. Begründung ist Pflicht.", True)
    jetzt = int(time.time())
    con.execute("UPDATE ah_ersuchen SET status=?, antwort=?, entscheider_name=?, entschieden=?, aktualisiert=?, "
                "bearbeiter_id=CASE WHEN bearbeiter_id='' THEN ? ELSE bearbeiter_id END, bearbeiter_name=CASE WHEN bearbeiter_name='' THEN ? ELSE bearbeiter_name END WHERE id=?",
                (erg, antwort, k["name"], jetzt, jetzt, k["id"], k["name"], e["id"]))
    _eintrag(con, e["id"], "Abgelehnt" if erg == "abgelehnt" else STATUS[erg], f'{e["an_name"]}: {STATUS[erg]}.', k, "an")
    con.commit()
    await request.app["discord"].dm(e["antragsteller_id"], f'Dein Amtshilfeersuchen {az(e)} („{e["betreff"]}“) an {e["an_name"]} wurde entschieden: '
                                                           f'{STATUS[erg]}.\nhttps://imperiumgermanicum.de{PFAD}{e["id"]}/')
    amt._umleiten(f'{PFAD}{e["id"]}/', f"Ersuchen {STATUS[erg].lower()}.")


async def zurueckziehen(request):
    k, _ = await _form(request)
    con = request.app["db"]
    e = _ersuchen(con, k, request.match_info["id"])
    von = stelle(e["von"], con)
    if e["status"] not in OFFEN or not (alle(k) or (seite(k, e, con) == "von" and (e["antragsteller_id"] == k["id"] or (von and entscheider(k, von))))):
        raise web.HTTPForbidden(text="Zurückziehen kann nur der Antragsteller oder die Leitung der ersuchenden Stelle, solange offen.")
    con.execute("UPDATE ah_ersuchen SET status='zurueckgezogen', aktualisiert=? WHERE id=?", (int(time.time()), e["id"]))
    _eintrag(con, e["id"], "Zurückgezogen", f'{e["von_name"]} hat das Ersuchen zurückgezogen.', k, "von")
    con.commit()
    amt._umleiten(f'{PFAD}{e["id"]}/', "Ersuchen zurückgezogen.")


def registrieren(app):
    global _CON
    _CON = app["db"]
    einrichten(app["db"])
    amt.NAV_EXTRA.append(("Dienste", nav))
    app.router.add_get(PFAD, liste)
    app.router.add_get(PFAD + "neu/", neu)
    app.router.add_post(PFAD + "neu", neu_speichern)
    app.router.add_get(PFAD + "{id}/", ansicht)
    app.router.add_get(PFAD + "{id}/pdf", pdf)
    app.router.add_post(PFAD + "{id}/vermerk", vermerk)
    app.router.add_post(PFAD + "{id}/uebernehmen", uebernehmen)
    app.router.add_post(PFAD + "{id}/entscheiden", entscheiden)
    app.router.add_post(PFAD + "{id}/zurueckziehen", zurueckziehen)
