"""Landespolizeien: je Teilstaat eine eigene interne Seite unter der Kaiserlichen Polizeibehörde (…/intern/bereich/polizei/land/<sid>/).

Teilstaaten kommen aus der aktuellen Reichskarte (karte.aktuell): jeder Teilstaat mit Fraktionsrolle hat eine Landespolizei. Eigene
Polizeirollen je Teilstaat gibt es im Discord nicht; ein Beamter gehört zur Landespolizei, wenn er die Rolle „Kaiserliche Polizeibehörde“
UND die Fraktionsrolle des Teilstaats trägt. Der Dienstgrad wird aus den Rollen „OF-…/OR-… Polizei…“ gelesen.

Rechte (siehe darf/pruefer/leitung):
- Ansehen, Einsatzberichte schreiben, Vermerke, Pinnwand: Beamte der Landespolizei; reichsweit Generaldirektor der Polizei,
  Kronkanzler, Kaiser.
- Eigenen Bericht ändern, solange er nicht geprüft ist: Verfasser.
- Berichte prüfen/zurückgeben, jederzeit ändern, fremde Pinnwand-Mitteilungen löschen: OF-8 Polizeidirektor (Stellvertretung) und Leitung.
- Berichte löschen (mit Grund, Löschprotokoll) und Löschprotokoll sehen: OF-9 Leitender Polizeidirektor des Teilstaats und reichsweite Leitung.
Tabellen: lp_berichte, lp_eintraege, lp_loeschungen; Pinnwand in bereich_mitteilungen mit bereich = "polizei-<sid>".
"""
import re
import secrets
import time
from datetime import datetime

from aiohttp import web

import amt
import anmeldung
import bereiche
import karte

esc = amt.esc
BASIS = amt.BASIS
ROLLE_POLIZEI = amt.ROLLE_POLIZEI
ROLLE_GD = "1557335971966750780"      # Generaldirektor der Polizei (reichsweit)
ROLLE_LPD = "1557189875164385290"     # OF-9 Leitender Polizeidirektor → Leitung der Landespolizei
ROLLE_PD = "1557189964108664902"      # OF-8 Polizeidirektor → Stellvertretung (prüfen, moderieren)
DIENSTGRAD = re.compile(r"^(OF|OR)-\d+ .*Polizei")
TITEL = {"Großherzogtum", "Herzogtum", "Fürstentum", "Königreich", "Landgrafschaft", "Markgrafschaft", "Gouvernement",
         "Generalgouvernement", "Fürstbistum"}
KUERZEL = {"s1": "PFB", "s3": "HSB", "s5": "FRK", "s6": "HOL", "s8": "SWW", "s9": "HST", "s10": "TSB", "s11": "APU", "s13": "HAN",
           "s15": "LAU", "s16": "MAE", "s18": "SLO", "s19": "WWU", "s20": "BAD"}
EINSATZARTEN = ["Streife", "Personenkontrolle", "Verkehrskontrolle", "Verkehrsunfall", "Festnahme", "Durchsuchung", "Ruhestörung",
                "Körperverletzung", "Diebstahl / Raub", "Sachbeschädigung", "Gefahrenabwehr", "Großlage / Veranstaltung", "Amtshilfe", "Sonstiges"]
STATUS = {"eingereicht": "Eingereicht", "zurueckgegeben": "Zurückgegeben", "geprueft": "Geprüft"}
MARKE = {"eingereicht": "offen", "zurueckgegeben": "nein", "geprueft": "ok"}
SEITE = 40
MAX_PRO_STUNDE = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS lp_berichte (
    id INTEGER PRIMARY KEY AUTOINCREMENT, staat TEXT NOT NULL, jahr INTEGER NOT NULL, nr INTEGER NOT NULL,
    titel TEXT NOT NULL, einsatzart TEXT NOT NULL DEFAULT '', einsatz_zeit TEXT NOT NULL DEFAULT '', ort TEXT NOT NULL DEFAULT '',
    beamte TEXT NOT NULL DEFAULT '', personen TEXT NOT NULL DEFAULT '', sachverhalt TEXT NOT NULL DEFAULT '', massnahmen TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'eingereicht', verfasser_id TEXT NOT NULL, verfasser_name TEXT NOT NULL,
    pruefer_name TEXT NOT NULL DEFAULT '', geprueft INTEGER, erstellt INTEGER NOT NULL, aktualisiert INTEGER NOT NULL,
    UNIQUE (staat, jahr, nr));
CREATE INDEX IF NOT EXISTS lp_berichte_staat ON lp_berichte (staat, status);
CREATE TABLE IF NOT EXISTS lp_eintraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bericht_id INTEGER NOT NULL REFERENCES lp_berichte(id) ON DELETE CASCADE, zeit INTEGER NOT NULL,
    art TEXT NOT NULL, text TEXT NOT NULL, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS lp_eintraege_b ON lp_eintraege (bericht_id);
CREATE TABLE IF NOT EXISTS lp_loeschungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, staat TEXT NOT NULL, az TEXT NOT NULL, titel TEXT NOT NULL, verfasser_name TEXT NOT NULL,
    grund TEXT NOT NULL, autor_id TEXT NOT NULL, autor_name TEXT NOT NULL, zeit INTEGER NOT NULL);
"""

amt.ICONS.update({
    "clipboard-list": '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
                      '<path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/>',
    "map-pin": '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
    "undo-2": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"/>',
})
amt.FELDNAMEN.update({"einsatzart": "Einsatzart", "einsatz_zeit": "Einsatzzeit (IC)", "ort": "Einsatzort", "beamte": "Beteiligte Beamte",
                      "personen": "Betroffene Personen", "massnahmen": "Maßnahmen"})
amt._ART_ICON[0:0] = [("geprüft", "check", "ok"), ("zurückgegeben", "undo-2", "rot"), ("eingereicht", "file-plus", "ok")]

_CON = None
_CACHE = {"id": None, "staaten": []}


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Teilstaaten und Rechte

def _kurzname(name):
    teile = name.split()
    return " ".join(teile[1:]) if len(teile) > 1 and teile[0] in TITEL else name


def staaten(con=None):
    """Teilstaaten mit Landespolizei (aus der aktuellen Kartenversion, zwischengespeichert bis zur nächsten Version)."""
    con = con or _CON
    vid = con.execute("SELECT MAX(id) FROM karte_versionen").fetchone()[0]
    if vid != _CACHE["id"]:
        liste = []
        for s in karte.aktuell(con)["stand"]["staaten"]:
            fr = s.get("fraktion") or ""
            if not fr or fr in karte.ROLLEN_AEMTER:   # ohne eigene Fraktionsrolle (oder nur Amtsrolle als Platzhalter) keine Zuordnung möglich
                continue
            kurz = _kurzname(s["name"])
            liste.append({"id": s["id"], "name": s["name"], "kurz": kurz, "fraktion": fr, "farbe": s["farbe"],
                          "kuerzel": KUERZEL.get(s["id"]) or re.sub(r"[^A-Z]", "", kurz.upper())[:3] or s["id"].upper()})
        liste.sort(key=lambda s: s["kurz"].lower())
        _CACHE.update(id=vid, staaten=liste)
    return _CACHE["staaten"]


def staat(con, sid):
    s = next((s for s in staaten(con) if s["id"] == sid), None)
    if not s:
        raise web.HTTPNotFound(text="Landespolizei nicht gefunden.")
    return s


def reichsweit(k):
    return bool(k) and (bereiche._alle(k) or ROLLE_GD in k["rollen"])


def mitglied(rollen, s):
    return ROLLE_POLIZEI in rollen and s["fraktion"] in rollen


def darf(k, s):
    return bool(k) and k["mitglied"] and (reichsweit(k) or mitglied(k["rollen"], s))


def leitung(k, s):
    return darf(k, s) and (reichsweit(k) or ROLLE_LPD in k["rollen"])


def pruefer(k, s):
    return leitung(k, s) or (darf(k, s) and ROLLE_PD in k["rollen"])


def eigene(k):
    return [s for s in staaten() if k and mitglied(k["rollen"], s)]


def nav_unter(k, schl):
    """Untertabs im Polizei-Tab: die Landespolizei(en), denen das Konto selbst angehört."""
    if schl != "polizei" or _CON is None:
        return []
    return [("lp-" + s["id"], "Landespolizei " + s["kurz"], f'bereich/polizei/land/{s["id"]}/') for s in eigene(k)]


def az(b, s=None):
    s = s or next((x for x in staaten() if x["id"] == b["staat"]), {"kuerzel": b["staat"].upper()})
    return f'POL-{s["kuerzel"]}-{b["jahr"]}-{b["nr"]:04d}'


def _pfad(s):
    return f'{BASIS}bereich/polizei/land/{s["id"]}/'


def _dienstgrad(rollen_ids, rollen):
    grade = [(rollen[r]["position"], rollen[r]["name"]) for r in rollen_ids if r in rollen and DIENSTGRAD.match(rollen[r]["name"])]
    return max(grade)[1] if grade else ""


# ---------------------------------------------------------------- Rahmen

async def _konto(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    s = staat(request.app["db"], request.match_info["sid"])
    if not darf(k, s):
        raise web.HTTPForbidden(text="Diese Landespolizei ist ihren Beamten vorbehalten (Rolle „Kaiserliche Polizeibehörde“ und Fraktionsrolle des Teilstaats).")
    return k, s


async def _form(request):
    k, s = await _konto(request)
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    return k, s, form


def _reiter(k, s, aktiv):
    p = _pfad(s)
    teile = [("uebersicht", "Übersicht", ""), ("berichte", "Einsatzberichte", "berichte/"), ("neu", "Neuer Bericht", "berichte/neu/")]
    if leitung(k, s):
        teile.append(("protokoll", "Löschprotokoll", "loeschprotokoll/"))
    teile.append(("amtshilfe", "Amtshilfe", f'../../../../amtshilfe/?ansicht=ausgang&stelle=lp-{s["id"]}'))
    return '<p class="reiter lp-reiter">' + " ".join(f'<a href="{p}{u}" class="{"aktiv" if x == aktiv else ""}">{esc(t)}</a>' for x, t, u in teile) + "</p>"


CSS = """<style>
.lp-pfad{margin:0 0 4px;font-size:13.5px;color:var(--grau)}.lp-pfad a{color:var(--grau)}
.lp-reiter{border-bottom:0;background:var(--hell);border-radius:8px;padding:2px 12px}
.lp-karten{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin:12px 0 4px}
.lp-karte{display:flex;gap:12px;align-items:center;border:1px solid var(--linie);border-radius:var(--r);padding:12px 14px;color:var(--ink);text-decoration:none;min-width:0}
a.lp-karte:hover{border-color:var(--akzent);background:#f9fbfe}
.lp-karte i{width:10px;align-self:stretch;border-radius:4px;flex:none}
.lp-karte b{display:block;font-weight:600;line-height:1.3}.lp-karte small{display:block;color:var(--grau);font-size:12.5px}
.lp-karte.zu{color:var(--grau);background:#fafafa}.lp-karte.zu .icon{margin-left:auto;color:#a0a3a9}
.lp-karte.eigen{border-color:var(--ink)}
.lp-text{white-space:pre-wrap;word-break:break-word}
.mitteilung{border-bottom:1px solid #ddd;padding:12px 0}.mitteilung h3{margin:0;font-size:16px}.mitteilung form{margin-top:8px}
</style>"""


def _seite(request, k, s, titel, aktiv, inhalt):
    import strafsachen
    kopf = (strafsachen.untertabs(k, "polizei", "lp-" + s["id"])
            + f'<p class="lp-pfad"><a href="{BASIS}bereich/polizei/">Kaiserliche Polizeibehörde</a> › Landespolizei</p>'
            + f'<h1>{amt.ic("siren")} Landespolizei {esc(s["kurz"])}</h1>{amt.meldung(request)}{_reiter(k, s, aktiv)}')
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(f'{titel} – Landespolizei {s["kurz"]}', "b-polizei", CSS + kopf + inhalt, k, request["csrf"]))


def _marke(b):
    return amt.status_marke(MARKE.get(b["status"], "neutral"), STATUS.get(b["status"], b["status"]))


# ---------------------------------------------------------------- Übersicht im Polizei-Tab (Hook in bereiche.bereich)

async def polizei_zusatz(request, k):
    con = request.app["db"]
    mit = await request.app["discord"].mitglieder()
    liste = staaten(con)
    offen = dict(con.execute("SELECT staat, COUNT(*) FROM lp_berichte WHERE status!='geprueft' GROUP BY staat").fetchall())
    karten = []
    for s in liste:
        n = sum(1 for m in mit if mitglied(m["rollen"], s))
        o = offen.get(s["id"], 0)
        info = (f'{n} Beamter' if n == 1 else f'{n} Beamte') + ((f' · {o} offener Bericht' if o == 1 else f' · {o} offene Berichte') if darf(k, s) else "")
        inner = f'<i style="background:{esc(s["farbe"])}"></i><span><b>{esc(s["kurz"])}</b><small>{info}</small></span>'
        if darf(k, s):
            karten.append(f'<a class="lp-karte{" eigen" if mitglied(k["rollen"], s) else ""}" href="{_pfad(s)}">{inner}</a>')
        else:
            karten.append(f'<div class="lp-karte zu" title="Nur für Beamte dieses Teilstaats">{inner}{amt.ic("lock")}</div>')
    html_ = (CSS + '<h2>Landespolizeien der Teilstaaten</h2><p class="az">Jeder Teilstaat führt eine eigene Landespolizei. '
             'Zugang haben Beamte mit der Rolle der Polizeibehörde und der Fraktionsrolle des Teilstaats.</p>'
             f'<div class="lp-karten">{"".join(karten) or "<p class=leer>Keine Teilstaaten mit Fraktionsrolle.</p>"}</div>')
    if reichsweit(k):
        ohne = [m for m in mit if ROLLE_POLIZEI in m["rollen"] and not any(mitglied(m["rollen"], s) for s in liste)]
        if ohne:
            html_ += (f'<p class="az">Ohne Teilstaat (keine passende Fraktionsrolle): '
                      + ", ".join(esc(m["name"]) for m in sorted(ohne, key=lambda m: m["name"].lower())) + "</p>")
    return html_


# ---------------------------------------------------------------- Übersicht der Landespolizei

async def uebersicht(request):
    k, s = await _konto(request)
    con = request.app["db"]
    pfad = _pfad(s)
    rollen = await request.app["discord"].server_rollen()
    mit = [m for m in await request.app["discord"].mitglieder() if mitglied(m["rollen"], s)]

    def rang(m):
        return (0 if ROLLE_LPD in m["rollen"] else 1 if ROLLE_PD in m["rollen"] else 2,
                -max([rollen[r]["position"] for r in m["rollen"] if r in rollen and DIENSTGRAD.match(rollen[r]["name"])] or [0]), m["name"].lower())
    mit.sort(key=rang)
    zeilen = []
    for m in mit:
        z = con.execute("SELECT ic_name FROM amt_akten WHERE konto_id=?", (m["id"],)).fetchone()
        adr = con.execute("SELECT adresse FROM post_adressen WHERE konto_id=? AND aktuell=1", (m["id"],)).fetchone()
        fkt = (amt.status_marke("neutral", "Leitung") if ROLLE_LPD in m["rollen"] else amt.status_marke("neutral", "Stellvertretung") if ROLLE_PD in m["rollen"] else "")
        mail = f'<a href="{BASIS}postfach/neu/?an={esc(adr["adresse"])}">{esc(adr["adresse"])}</a>' if adr else "–"
        zeilen.append((esc(m["name"]) + (" " + fkt if fkt else ""), esc((z["ic_name"] if z else "") or "–"),
                       esc(_dienstgrad(m["rollen"], rollen) or "–"), mail))
    st = dict(con.execute("SELECT status, COUNT(*) FROM lp_berichte WHERE staat=? GROUP BY status", (s["id"],)).fetchall())
    monat = datetime.now(amt.BERLIN).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    neu_m = con.execute("SELECT COUNT(*) FROM lp_berichte WHERE staat=? AND erstellt>=?", (s["id"], monat)).fetchone()[0]
    zahlen = "".join(f"<div><b>{n}</b>{esc(t)}</div>" for t, n in [("Beamte", len(mit)), ("Zu prüfen", st.get("eingereicht", 0)),
                                                                   ("Zurückgegeben", st.get("zurueckgegeben", 0)), ("Berichte diesen Monat", neu_m)])
    msgs = con.execute("SELECT * FROM bereich_mitteilungen WHERE bereich=? ORDER BY zeit DESC LIMIT 50", ("polizei-" + s["id"],)).fetchall()
    pin = "".join(
        f'<div class="mitteilung"><h3>{esc(m["titel"])}</h3><p class="az">{esc(m["autor_name"])} · {amt._zeit(m["zeit"])}</p>'
        f'<div class="lp-text">{esc(m["text"])}</div>'
        + (f'<form method="post" action="{pfad}mitteilung/{m["id"]}/loeschen">{amt.csrf_feld(request)}'
           f'<button class="btn zweit gefahr" type="submit">{amt.ic("trash-2")}Löschen</button></form>'
           if m["autor_id"] == k["id"] or pruefer(k, s) else "") + "</div>" for m in msgs) or '<p class="leer">Keine Mitteilungen.</p>'
    letzte = con.execute("SELECT * FROM lp_berichte WHERE staat=? ORDER BY aktualisiert DESC LIMIT 5", (s["id"],)).fetchall()
    inhalt = (f'<div class="kennzahlen">{zahlen}</div>'
              f'<h2>Zuletzt bearbeitete Einsatzberichte</h2>'
              + amt.tabelle(["Aktenzeichen", "Titel", "Stand", "Verfasser", "Zuletzt"],
                            [(f'<a href="{pfad}berichte/{b["id"]}/">{az(b, s)}</a>', esc(b["titel"]), _marke(b), esc(b["verfasser_name"]),
                              amt._zeit(b["aktualisiert"], False)) for b in letzte], "Noch keine Einsatzberichte.")
              + f'<div class="aktionen"><a class="btn" href="{pfad}berichte/neu/">{amt.ic("plus")}Neuer Einsatzbericht</a></div>'
              f'<h2>Pinnwand</h2>'
              f'<form method="post" action="{pfad}mitteilung">{amt.csrf_feld(request)}'
              f'<div><label for="t">Titel</label><input type="text" id="t" name="titel" maxlength="120" style="width:100%" required></div>'
              f'<div style="margin-top:8px"><label for="x">Mitteilung an die Landespolizei</label><textarea id="x" name="text" maxlength="4000" required></textarea></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("pencil")}Veröffentlichen</button></div></form>'
              f'{pin}<h2>Beamte ({len(mit)})</h2>'
              + amt.tabelle(["Discord-Name", "Name (IC)", "Dienstgrad", "E-Mail"], zeilen, "Keine Beamten mit Polizei- und Fraktionsrolle gefunden."))
    return _seite(request, k, s, "Übersicht", "uebersicht", inhalt)


async def mitteilung(request):
    k, s, form = await _form(request)
    con = request.app["db"]
    ziel = _pfad(s)
    titel = " ".join(str(form.get("titel", "")).split())[:120]
    text = str(form.get("text", "")).replace("\r\n", "\n").strip()[:4000]
    if not titel or not text:
        amt._umleiten(ziel, "Titel und Mitteilung dürfen nicht leer sein.", True)
    if con.execute("SELECT COUNT(*) FROM bereich_mitteilungen WHERE autor_id=? AND zeit>?", (k["id"], time.time() - 3600)).fetchone()[0] >= MAX_PRO_STUNDE:
        amt._umleiten(ziel, "Zu viele Mitteilungen in der letzten Stunde.", True)
    con.execute("INSERT INTO bereich_mitteilungen (bereich, autor_id, autor_name, titel, text, zeit) VALUES (?,?,?,?,?,?)",
                ("polizei-" + s["id"], k["id"], k["name"], titel, text, int(time.time())))
    con.commit()
    amt._umleiten(ziel, "Mitteilung veröffentlicht.")


async def mitteilung_loeschen(request):
    k, s, _ = await _form(request)
    con = request.app["db"]
    mid = request.match_info["id"]
    z = con.execute("SELECT * FROM bereich_mitteilungen WHERE id=? AND bereich=?", (mid, "polizei-" + s["id"])).fetchone() if mid.isdigit() else None
    if not z:
        raise web.HTTPNotFound()
    if z["autor_id"] != k["id"] and not pruefer(k, s):
        raise web.HTTPForbidden(text="Nur der Autor oder die Leitung kann die Mitteilung löschen.")
    con.execute("DELETE FROM bereich_mitteilungen WHERE id=?", (z["id"],))
    con.commit()
    amt._umleiten(_pfad(s), "Mitteilung gelöscht.")


# ---------------------------------------------------------------- Einsatzberichte

def _bericht(con, s, i):
    b = con.execute("SELECT * FROM lp_berichte WHERE id=? AND staat=?", (i, s["id"])).fetchone() if str(i).isdigit() else None
    if not b:
        raise web.HTTPNotFound(text="Einsatzbericht nicht gefunden.")
    return b


def _darf_aendern(k, s, b):
    return pruefer(k, s) or (b["verfasser_id"] == k["id"] and b["status"] != "geprueft")


def _eintrag(con, bid, art, text, k=None):
    con.execute("INSERT INTO lp_eintraege (bericht_id, zeit, art, text, autor_id, autor_name) VALUES (?,?,?,?,?,?)",
                (bid, int(time.time()), art, text, k["id"] if k else None, k["name"] if k else "System"))


def _t(form, feld, n):
    return " ".join(str(form.get(feld, "")).split())[:n]


def _block(form, feld, n):
    return str(form.get(feld, "")).replace("\r\n", "\n").strip()[:n]


FELDER = [("titel", 160), ("einsatzart", 60), ("einsatz_zeit", 80), ("ort", 120), ("beamte", 400), ("personen", 400)]
BLOECKE = [("sachverhalt", 8000), ("massnahmen", 4000)]


def _werte(form):
    w = {f: _t(form, f, n) for f, n in FELDER}
    w.update({f: _block(form, f, n) for f, n in BLOECKE})
    return w


def _formular(request, k, s, ziel, b=None, knopf="Bericht einreichen"):
    g = (lambda f: b[f]) if b else (lambda f: k["name"] if f == "beamte" else "")
    feld = amt._feld
    t = lambda fid, name, n, extra="": f'<input type="text" id="{fid}" name="{name}" value="{esc(g(name))}" maxlength="{n}"{extra}>'
    arten = "".join(f'<option{" selected" if a == g("einsatzart") else ""}>{esc(a)}</option>' for a in EINSATZARTEN)
    import strafsachen
    return (f'<form class="formular" method="post" action="{ziel}">{amt.csrf_feld(request)}'
            '<fieldset><legend>Einsatz</legend><div class="felder">'
            + feld("ti", "Kurzbezeichnung", t("ti", "titel", 160, " required")).replace('class="feld"', 'class="feld breit"')
            + feld("ea", "Einsatzart", f'<select id="ea" name="einsatzart">{arten}</select>')
            + feld("ez", "Datum / Uhrzeit (IC)", t("ez", "einsatz_zeit", 80))
            + feld("or", "Einsatzort", t("or", "ort", 120)).replace('class="feld"', 'class="feld breit"')
            + feld("be", "Beteiligte Beamte", t("be", "beamte", 400), "Namen durch Komma trennen.").replace('class="feld"', 'class="feld breit"')
            + feld("pe", "Betroffene Personen", t("pe", "personen", 400, ' list="personen"'), "Name aus der Bürgerakte, mehrere durch Komma.").replace('class="feld"', 'class="feld breit"')
            + '</div></fieldset><fieldset><legend>Bericht</legend><div class="felder">'
            + feld("sv", "Sachverhalt", f'<textarea id="sv" name="sachverhalt" maxlength="8000" style="min-height:180px" required>{esc(g("sachverhalt"))}</textarea>').replace('class="feld"', 'class="feld breit"')
            + feld("ma", "Getroffene Maßnahmen", f'<textarea id="ma" name="massnahmen" maxlength="4000">{esc(g("massnahmen"))}</textarea>').replace('class="feld"', 'class="feld breit"')
            + f'</div></fieldset><datalist id="personen">{strafsachen._personen(request.app["db"])}</datalist>'
            f'<div class="formular-fuss"><a class="btn zweit" href="{_pfad(s)}berichte/{str(b["id"]) + "/" if b else ""}">Abbrechen</a>'
            f'<button class="btn" type="submit">{amt.ic("check")}{knopf}</button></div></form>')


async def liste(request):
    k, s = await _konto(request)
    con = request.app["db"]
    pfad = _pfad(s)
    q, st = request.query.get("q", "").strip()[:80], request.query.get("status", "")
    seite = int(request.query["seite"]) if request.query.get("seite", "").isdigit() and int(request.query["seite"]) > 0 else 1
    wo, par = ["staat=?"], [s["id"]]
    if st in STATUS:
        wo.append("status=?")
        par.append(st)
    elif st == "mein":
        wo.append("verfasser_id=?")
        par.append(k["id"])
    if q:
        wo.append("(titel LIKE ? OR einsatzart LIKE ? OR ort LIKE ? OR beamte LIKE ? OR personen LIKE ? OR verfasser_name LIKE ? "
                  "OR ('POL-' || ? || '-' || jahr || '-' || printf('%04d', nr)) LIKE ?)")
        par += [f"%{q}%"] * 6 + [s["kuerzel"], f"%{q}%"]
    gesamt = con.execute(f"SELECT COUNT(*) FROM lp_berichte WHERE {' AND '.join(wo)}", par).fetchone()[0]
    rows = con.execute(f"SELECT * FROM lp_berichte WHERE {' AND '.join(wo)} ORDER BY aktualisiert DESC LIMIT ? OFFSET ?",
                       par + [SEITE, (seite - 1) * SEITE]).fetchall()
    zeilen = [(f'<a href="{pfad}berichte/{b["id"]}/">{az(b, s)}</a>', esc(b["titel"]), esc(b["einsatzart"] or "–"), _marke(b),
               esc(b["verfasser_name"]), amt._zeit(b["aktualisiert"], False)) for b in rows]
    opt = '<option value="">Alle</option>' + f'<option value="mein"{" selected" if st == "mein" else ""}>Meine Berichte</option>' + "".join(
        f'<option value="{x}"{" selected" if x == st else ""}>{esc(t)}</option>' for x, t in STATUS.items())
    basis = f"?q={esc(q)}&amp;status={esc(st)}"
    nav_ = (f'<a href="{basis}&amp;seite={seite - 1}">← Zurück</a>' if seite > 1 else "") + \
           (f'<a href="{basis}&amp;seite={seite + 1}">Weiter →</a>' if seite * SEITE < gesamt else "")
    inhalt = (f'<p class="az">{gesamt} Einsatzberichte</p>'
              f'<form class="zeile" method="get"><div><label for="q">Suche (Az., Titel, Ort, Personen, Beamte)</label><input type="search" id="q" name="q" value="{esc(q)}"></div>'
              f'<div><label for="st">Stand</label><select id="st" name="status">{opt}</select></div>'
              f'<button class="btn" type="submit">{amt.ic("search")}Suchen</button></form>'
              + amt.tabelle(["Aktenzeichen", "Titel", "Einsatzart", "Stand", "Verfasser", "Zuletzt"], zeilen, "Keine Einsatzberichte gefunden.")
              + f'<div class="seiten">{nav_}</div>')
    return _seite(request, k, s, "Einsatzberichte", "berichte", inhalt)


async def neu(request):
    k, s = await _konto(request)
    inhalt = '<h2>Neuer Einsatzbericht</h2>' + _formular(request, k, s, f'{_pfad(s)}berichte/neu')
    return _seite(request, k, s, "Neuer Einsatzbericht", "neu", inhalt)


async def neu_speichern(request):
    k, s, form = await _form(request)
    con = request.app["db"]
    w = _werte(form)
    if not w["titel"] or not w["sachverhalt"]:
        amt._umleiten(f'{_pfad(s)}berichte/neu/', "Kurzbezeichnung und Sachverhalt sind Pflicht.", True)
    if con.execute("SELECT COUNT(*) FROM lp_berichte WHERE verfasser_id=? AND erstellt>?", (k["id"], time.time() - 3600)).fetchone()[0] >= MAX_PRO_STUNDE:
        amt._umleiten(f'{_pfad(s)}berichte/', "Zu viele Berichte in der letzten Stunde.", True)
    jahr = datetime.now(amt.BERLIN).year
    nr = (con.execute("SELECT MAX(nr) FROM lp_berichte WHERE staat=? AND jahr=?", (s["id"], jahr)).fetchone()[0] or 0) + 1
    jetzt = int(time.time())
    sp = {"staat": s["id"], "jahr": jahr, "nr": nr, **w, "status": "eingereicht", "verfasser_id": k["id"], "verfasser_name": k["name"],
          "erstellt": jetzt, "aktualisiert": jetzt}
    i = con.execute(f"INSERT INTO lp_berichte ({', '.join(sp)}) VALUES ({', '.join('?' * len(sp))})", list(sp.values())).lastrowid
    _eintrag(con, i, "Bericht eingereicht", "Einsatzbericht angelegt und zur Prüfung eingereicht.", k)
    con.commit()
    amt._umleiten(f'{_pfad(s)}berichte/{i}/', "Einsatzbericht eingereicht.")


def _ansicht(request, k, s, b, con, druck=False):
    pfad = f'{_pfad(s)}berichte/{b["id"]}/'
    csrf = amt.csrf_feld(request)
    stamm = [("Aktenzeichen", az(b, s)), ("Stand", _marke(b)), ("Einsatzart", esc(b["einsatzart"] or "–")),
             ("Datum / Uhrzeit (IC)", esc(b["einsatz_zeit"] or "–")), ("Einsatzort", esc(b["ort"] or "–")),
             ("Beteiligte Beamte", esc(b["beamte"] or "–")), ("Betroffene Personen", esc(b["personen"] or "–")),
             ("Verfasser", f'{esc(b["verfasser_name"])} · {amt._zeit(b["erstellt"])}')]
    if b["geprueft"]:
        stamm.append(("Geprüft", f'{esc(b["pruefer_name"])} · {amt._zeit(b["geprueft"])}'))
    h = (f'<h2>{esc(b["titel"])}</h2>' + amt.daten_tabelle(stamm)
         + f'<h2>Sachverhalt</h2><div class="lp-text">{esc(b["sachverhalt"] or "–")}</div>'
         + f'<h2>Getroffene Maßnahmen</h2><div class="lp-text">{esc(b["massnahmen"] or "–")}</div>')
    es = con.execute("SELECT * FROM lp_eintraege WHERE bericht_id=? ORDER BY id DESC", (b["id"],)).fetchall()
    h += "<h2>Verlauf</h2>" + amt.verlauf_html(es, "Keine Einträge.")
    if druck:
        return h
    h += (f'<form method="post" action="{pfad}vermerk">{csrf}<label for="vm">Vermerk hinzufügen</label><textarea id="vm" name="text" maxlength="4000" required></textarea>'
          f'<div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("notebook-pen")}Vermerk speichern</button></div></form>')
    if pruefer(k, s):
        h += (f'<h2>Prüfung</h2><form method="post" action="{pfad}pruefen">{csrf}'
              f'<label for="pv">Begründung (Pflicht beim Zurückgeben)</label><textarea id="pv" name="text" maxlength="2000"></textarea>'
              f'<div class="aktionen">'
              + (f'<button class="btn" type="submit" name="ergebnis" value="geprueft">{amt.ic("check")}Als geprüft abzeichnen</button>' if b["status"] != "geprueft" else "")
              + f'<button class="btn zweit" type="submit" name="ergebnis" value="zurueckgegeben">{amt.ic("undo-2")}Zur Überarbeitung zurückgeben</button>'
              '</div></form>')
    akt = ""
    if _darf_aendern(k, s, b):
        akt += f'<a class="btn zweit" href="{pfad}bearbeiten/">{amt.ic("pencil")}Bearbeiten</a>'
    akt += f'<a class="btn zweit" href="{pfad}pdf">{amt.ic("file-down")}PDF</a>'
    if leitung(k, s):
        akt += f'<a class="btn zweit gefahr" href="{pfad}loeschen/">{amt.ic("trash-2")}Löschen</a>'
    akt += f'<a class="btn zweit" href="{_pfad(s)}berichte/">{amt.ic("arrow-left")}Zur Liste</a>'
    return h + f'<div class="aktionen">{akt}</div>'


async def ansicht(request):
    k, s = await _konto(request)
    con = request.app["db"]
    b = _bericht(con, s, request.match_info["id"])
    return _seite(request, k, s, az(b, s), "berichte", _ansicht(request, k, s, b, con))


async def pdf(request):
    k, s = await _konto(request)
    con = request.app["db"]
    b = _bericht(con, s, request.match_info["id"])
    inhalt = f'<h1>Einsatzbericht {az(b, s)}</h1><p class="az">Landespolizei {esc(s["kurz"])} · Kaiserliche Polizeibehörde</p>' + _ansicht(request, k, s, b, con, True)
    return await amt._pdf_antwort(request, az(b, s), f"Einsatzbericht {az(b, s)}", inhalt, stelle=amt.stelle_behoerde("polizei"),
                                  az=az(b, s), doktyp="Einsatzbericht", unterzeile="Landespolizei " + s["kurz"])


async def bearbeiten_seite(request):
    k, s = await _konto(request)
    con = request.app["db"]
    b = _bericht(con, s, request.match_info["id"])
    if not _darf_aendern(k, s, b):
        raise web.HTTPForbidden(text="Geprüfte Berichte kann nur die Leitung ändern; fremde Berichte nur Leitung und Stellvertretung.")
    hinweis = ('<p class="az">Nach dem Speichern wird der Bericht erneut zur Prüfung eingereicht.</p>'
               if b["status"] == "zurueckgegeben" and b["verfasser_id"] == k["id"] else "")
    inhalt = f'<h2>{az(b, s)} bearbeiten</h2>{hinweis}' + _formular(request, k, s, f'{_pfad(s)}berichte/{b["id"]}/bearbeiten', b, "Speichern")
    return _seite(request, k, s, "Bericht bearbeiten", "berichte", inhalt)


async def bearbeiten(request):
    k, s, form = await _form(request)
    con = request.app["db"]
    b = _bericht(con, s, request.match_info["id"])
    if not _darf_aendern(k, s, b):
        raise web.HTTPForbidden(text="Keine Berechtigung, diesen Bericht zu ändern.")
    w = _werte(form)
    w["titel"] = w["titel"] or b["titel"]
    w["sachverhalt"] = w["sachverhalt"] or b["sachverhalt"]
    aend = [f"{f}: „{b[f][:80]}“ → „{v[:80]}“" for f, v in w.items() if b[f] != v and f not in ("sachverhalt", "massnahmen")]
    aend += [f"{amt.FELDNAMEN.get(f, f)} geändert" for f in ("sachverhalt", "massnahmen") if b[f] != w[f]]
    neu_status = "eingereicht" if b["status"] == "zurueckgegeben" and b["verfasser_id"] == k["id"] else b["status"]
    if not aend and neu_status == b["status"]:
        amt._umleiten(f'{_pfad(s)}berichte/{b["id"]}/', "Keine Änderung.")
    con.execute(f"UPDATE lp_berichte SET {', '.join(f + '=?' for f in w)}, status=?, aktualisiert=? WHERE id=?",
                list(w.values()) + [neu_status, int(time.time()), b["id"]])
    if aend:
        _eintrag(con, b["id"], "Bericht geändert", "\n".join(aend), k)
    if neu_status != b["status"]:
        _eintrag(con, b["id"], "Erneut eingereicht", "Nach Überarbeitung erneut zur Prüfung eingereicht.", k)
    con.commit()
    amt._umleiten(f'{_pfad(s)}berichte/{b["id"]}/', "Bericht gespeichert.")


async def vermerk(request):
    k, s, form = await _form(request)
    con = request.app["db"]
    b = _bericht(con, s, request.match_info["id"])
    text = _block(form, "text", 4000)
    if not text:
        amt._umleiten(f'{_pfad(s)}berichte/{b["id"]}/', "Der Vermerk ist leer.", True)
    _eintrag(con, b["id"], "Vermerk", text, k)
    con.execute("UPDATE lp_berichte SET aktualisiert=? WHERE id=?", (int(time.time()), b["id"]))
    con.commit()
    amt._umleiten(f'{_pfad(s)}berichte/{b["id"]}/', "Vermerk gespeichert.")


async def pruefen(request):
    k, s, form = await _form(request)
    con = request.app["db"]
    b = _bericht(con, s, request.match_info["id"])
    if not pruefer(k, s):
        raise web.HTTPForbidden(text="Prüfen dürfen nur Polizeidirektor und Leitender Polizeidirektor des Teilstaats.")
    erg, text = str(form.get("ergebnis", "")), _block(form, "text", 2000)
    ziel = f'{_pfad(s)}berichte/{b["id"]}/'
    jetzt = int(time.time())
    if erg == "geprueft" and b["status"] != "geprueft":
        con.execute("UPDATE lp_berichte SET status='geprueft', pruefer_name=?, geprueft=?, aktualisiert=? WHERE id=?", (k["name"], jetzt, jetzt, b["id"]))
        _eintrag(con, b["id"], "Geprüft", text or "Bericht geprüft und abgezeichnet.", k)
        msg = "Bericht als geprüft abgezeichnet."
    elif erg == "zurueckgegeben":
        if not text:
            amt._umleiten(ziel, "Bitte begründen, was überarbeitet werden soll.", True)
        con.execute("UPDATE lp_berichte SET status='zurueckgegeben', pruefer_name='', geprueft=NULL, aktualisiert=? WHERE id=?", (jetzt, b["id"]))
        _eintrag(con, b["id"], "Zurückgegeben", text, k)
        msg = "Bericht zur Überarbeitung zurückgegeben."
        if b["verfasser_id"] != k["id"]:
            await request.app["discord"].dm(b["verfasser_id"], f'Dein Einsatzbericht {az(b, s)} („{b["titel"]}“) wurde von {k["name"]} zur Überarbeitung '
                                                               f'zurückgegeben: {text[:500]}\nhttps://imperiumgermanicum.de{ziel}')
    else:
        amt._umleiten(ziel, "Keine Änderung.")
    con.commit()
    amt._umleiten(ziel, msg)


async def loeschen_seite(request):
    k, s = await _konto(request)
    con = request.app["db"]
    b = _bericht(con, s, request.match_info["id"])
    if not leitung(k, s):
        raise web.HTTPForbidden(text="Löschen darf nur der Leitende Polizeidirektor des Teilstaats.")
    pfad = f'{_pfad(s)}berichte/{b["id"]}/'
    inhalt = (f'<h2>{az(b, s)} löschen</h2><div class="warnung">Der Einsatzbericht „{esc(b["titel"])}“ wird mit seinem Verlauf endgültig entfernt. '
              f'Im Löschprotokoll der Landespolizei bleiben Aktenzeichen, Titel, Grund und wer gelöscht hat.</div>'
              f'<form method="post" action="{pfad}loeschen">{amt.csrf_feld(request)}<label for="gr">Grund (Pflicht)</label>'
              f'<textarea id="gr" name="grund" maxlength="1000" required></textarea>'
              f'<div class="aktionen"><a class="btn zweit" href="{pfad}">Abbrechen</a><button class="btn gefahr" type="submit">{amt.ic("trash-2")}Endgültig löschen</button></div></form>')
    return _seite(request, k, s, "Bericht löschen", "berichte", inhalt)


async def loeschen(request):
    k, s, form = await _form(request)
    con = request.app["db"]
    b = _bericht(con, s, request.match_info["id"])
    if not leitung(k, s):
        raise web.HTTPForbidden(text="Löschen darf nur der Leitende Polizeidirektor des Teilstaats.")
    grund = _block(form, "grund", 1000)
    if not grund:
        amt._umleiten(f'{_pfad(s)}berichte/{b["id"]}/loeschen/', "Bitte einen Grund angeben.", True)
    con.execute("INSERT INTO lp_loeschungen (staat, az, titel, verfasser_name, grund, autor_id, autor_name, zeit) VALUES (?,?,?,?,?,?,?,?)",
                (s["id"], az(b, s), b["titel"], b["verfasser_name"], grund, k["id"], k["name"], int(time.time())))
    con.execute("DELETE FROM lp_eintraege WHERE bericht_id=?", (b["id"],))
    con.execute("DELETE FROM lp_berichte WHERE id=?", (b["id"],))
    con.commit()
    amt._umleiten(f'{_pfad(s)}berichte/', f"Einsatzbericht {az(b, s)} gelöscht.")


async def loeschprotokoll(request):
    k, s = await _konto(request)
    if not leitung(k, s):
        raise web.HTTPForbidden(text="Das Löschprotokoll sieht nur die Leitung.")
    rows = request.app["db"].execute("SELECT * FROM lp_loeschungen WHERE staat=? ORDER BY zeit DESC LIMIT 200", (s["id"],)).fetchall()
    zeilen = [(esc(r["az"]), esc(r["titel"]), esc(r["verfasser_name"]), f'<span class="lp-text">{esc(r["grund"])}</span>',
               f'{esc(r["autor_name"])}<br>{amt._zeit(r["zeit"])}') for r in rows]
    inhalt = '<h2>Gelöschte Einsatzberichte</h2>' + amt.tabelle(["Aktenzeichen", "Titel", "Verfasser", "Grund", "Gelöscht von"], zeilen, "Nichts gelöscht.")
    return _seite(request, k, s, "Löschprotokoll", "protokoll", inhalt)


def registrieren(app):
    global _CON
    _CON = app["db"]
    einrichten(app["db"])
    bereiche.ZUSATZ["polizei"] = polizei_zusatz
    p = BASIS + "bereich/polizei/land/{sid}/"
    app.router.add_get(p, uebersicht)
    app.router.add_post(p + "mitteilung", mitteilung)
    app.router.add_post(p + "mitteilung/{id}/loeschen", mitteilung_loeschen)
    app.router.add_get(p + "berichte/", liste)
    app.router.add_get(p + "berichte/neu/", neu)
    app.router.add_post(p + "berichte/neu", neu_speichern)
    app.router.add_get(p + "berichte/{id}/", ansicht)
    app.router.add_get(p + "berichte/{id}/pdf", pdf)
    app.router.add_get(p + "berichte/{id}/bearbeiten/", bearbeiten_seite)
    app.router.add_post(p + "berichte/{id}/bearbeiten", bearbeiten)
    app.router.add_post(p + "berichte/{id}/vermerk", vermerk)
    app.router.add_post(p + "berichte/{id}/pruefen", pruefen)
    app.router.add_get(p + "berichte/{id}/loeschen/", loeschen_seite)
    app.router.add_post(p + "berichte/{id}/loeschen", loeschen)
    app.router.add_get(p + "loeschprotokoll/", loeschprotokoll)
