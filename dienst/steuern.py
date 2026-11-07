"""Steuersystem des Schatzamts: Bescheide, Steuerlauf, Gebühren, Lohnsteuertarif.

Steuerarten: Kopfsteuer, Vermögensteuer, Gewerbesteuer (Steuerlauf), Lohnsteuer (Quellenabzug im Lohnlauf, besoldung.py),
Umsatz-/Überweisungssteuer (bei Zahlungen, schatzamt.py), Verwaltungsgebühren (automatisch bei Pass-Ausstellung und Visum,
Hooks meldewesen.AUSGESTELLT / zollwesen.GESTEMPELT), Bußgeld und sonstige Abgaben (Einzelbescheid).
Bescheid (st_bescheide, Az. ST-JJJJ-NNNN): offen → bezahlt | erlassen | storniert; Teilzahlungen; Mahnung (+ Säumniszuschlag je Stufe,
neue Frist); Pfändung (Einzug vom Konto, auch teilweise). Zahlungen gehen an die Reichskasse; bei Lohn- und Kopfsteuer geht der
Länderanteil an die Staatskasse des Wohnsitz-Teilstaats (Meldewesen). Steuerlauf mit Probelauf; je Konto, Steuerart und Zeitraum nur
ein Bescheid. Seiten: /schatzamt/steuern/ (eigene), /schatzamt/amt/steuern/ (Verwaltung), /schatzamt/amt/steuerlauf/, /schatzamt/amt/tarife/.
"""
import json
import time
from datetime import date, timedelta

from aiohttp import web

import amt
import anmeldung
import geld
import meldewesen
import schatzamt as sa
from geld import mark, nummer_anzeige

esc = amt.esc
PFAD = sa.PFAD
ARTEN = {"kopfsteuer": "Kopfsteuer", "vermoegensteuer": "Vermögensteuer", "gewerbesteuer": "Gewerbesteuer", "lohnsteuer": "Lohnsteuer",
         "gebuehr": "Verwaltungsgebühr", "bussgeld": "Bußgeld", "sonstige": "Sonstige Abgabe"}
LAUF_ARTEN = ("kopfsteuer", "vermoegensteuer", "gewerbesteuer")
LAENDERANTEIL = ("kopfsteuer", "lohnsteuer")
STATUS = {"offen": ("offen", "Offen"), "bezahlt": ("ok", "Bezahlt"), "erlassen": ("neutral", "Erlassen"), "storniert": ("neutral", "Storniert")}

SCHEMA = """
CREATE TABLE IF NOT EXISTS st_bescheide (
    id INTEGER PRIMARY KEY AUTOINCREMENT, jahr INTEGER NOT NULL, nr INTEGER NOT NULL, konto INTEGER NOT NULL, steuerart TEXT NOT NULL,
    periode TEXT NOT NULL DEFAULT '', betrag INTEGER NOT NULL, zuschlag INTEGER NOT NULL DEFAULT 0, bezahlt INTEGER NOT NULL DEFAULT 0,
    faellig TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'offen', grundlage TEXT NOT NULL DEFAULT '', mahnstufe INTEGER NOT NULL DEFAULT 0,
    lauf INTEGER, erstellt INTEGER NOT NULL, autor_name TEXT NOT NULL DEFAULT '', erledigt INTEGER, vermerk TEXT NOT NULL DEFAULT '',
    UNIQUE (jahr, nr));
CREATE INDEX IF NOT EXISTS st_bescheide_k ON st_bescheide (konto, status);
CREATE TABLE IF NOT EXISTS st_laeufe (
    id INTEGER PRIMARY KEY AUTOINCREMENT, periode TEXT NOT NULL, arten TEXT NOT NULL, anzahl INTEGER NOT NULL, summe INTEGER NOT NULL,
    eingezogen INTEGER NOT NULL, zeit INTEGER NOT NULL, autor_name TEXT NOT NULL);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def az(b):
    return f'ST-{b["jahr"]}-{b["nr"]:04d}'


def offen(b):
    return max(0, b["betrag"] + b["zuschlag"] - b["bezahlt"])


def offene_bescheide(con, konto_ids):
    if not konto_ids:
        return []
    return con.execute(f"SELECT * FROM st_bescheide WHERE status='offen' AND konto IN ({','.join('?' * len(konto_ids))}) ORDER BY faellig",
                       konto_ids).fetchall()


def _faellig(con, tage=None):
    return (date.today() + timedelta(days=int(tage if tage is not None else geld.einstellung(con, "frist_tage")))).isoformat()


def _d(iso):
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


# ---------------------------------------------------------------- Berechnung

def lohnsteuer(con, brutto):
    """Stufentarif: Grenzsteuersätze je Stufe auf das Monatsbrutto."""
    steuer, unten = 0, 0
    for bis, satz in geld.einstellung(con, "lohnsteuer")["stufen"]:
        oben = brutto if bis is None else min(brutto, bis)
        if oben > unten:
            steuer += (oben - unten) * float(satz) / 100
        if bis is None or brutto <= bis:
            break
        unten = bis
    return int(round(steuer))


def wohnsitz_staat(con, konto_id):
    """Teilstaat-ID des gemeldeten Wohnsitzes (Meldewesen) eines Discord-Kontos oder None."""
    z = con.execute("SELECT id FROM amt_akten WHERE konto_id=? ORDER BY id DESC LIMIT 1", (konto_id,)).fetchone()
    ws = meldewesen.wohnsitz(con, z["id"]) if z else None
    return ws["staat"] if ws and ws["art"] != "abmeldung" else None


def laenderanteil_buchen(con, konto_id, steuer, k, bezug):
    """Länderanteil von der Reichskasse an die Staatskasse des Wohnsitzes; gibt (Staatskasse, Betrag) zurück."""
    sid = wohnsitz_staat(con, konto_id)
    anteil = int(round(steuer * float(geld.einstellung(con, "laenderanteil")) / 100))
    if not sid or anteil <= 0:
        return None, 0
    ziel = geld.stellenkonto(con, "ts-" + sid)
    if not ziel:
        return None, 0
    geld.buchen(con, geld.sonder(con, "reichskasse")["id"], ziel["id"], anteil, "laenderanteil", f"Länderanteil {bezug}", k, bezug=bezug, minus=True)
    return ziel, anteil


# ---------------------------------------------------------------- Bescheide

def erstellen(con, konto, steuerart, betrag, grundlage, k, periode="", lauf=None, faellig=None, vermerk=""):
    if periode and con.execute("SELECT 1 FROM st_bescheide WHERE konto=? AND steuerart=? AND periode=? AND status!='storniert'",
                               (konto["id"], steuerart, periode)).fetchone():
        return None
    jahr = date.today().year
    nr = (con.execute("SELECT MAX(nr) FROM st_bescheide WHERE jahr=?", (jahr,)).fetchone()[0] or 0) + 1
    cur = con.execute("INSERT INTO st_bescheide (jahr, nr, konto, steuerart, periode, betrag, faellig, grundlage, lauf, erstellt, autor_name, vermerk) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (jahr, nr, konto["id"], steuerart, periode, int(betrag), faellig or _faellig(con), grundlage, lauf, int(time.time()),
                       k["name"] if k else "System", vermerk))
    return con.execute("SELECT * FROM st_bescheide WHERE id=?", (cur.lastrowid,)).fetchone()


def zahlen(con, b, k, von=None, betrag=None, art="steuer"):
    """Zahlt (einen Teil von) Bescheid b vom Konto `von` (Standard: Bescheidkonto). art 'pfaendung' ignoriert Sperren und zieht
    höchstens das Guthaben ein. Gibt den gezahlten Betrag zurück."""
    rest = offen(b)
    kv = geld.konto(con, von or b["konto"])
    if art == "pfaendung":
        betrag = min(rest, max(0, kv["saldo"]))
    else:
        betrag = min(rest, betrag or rest)
    if betrag <= 0:
        return 0
    kasse = geld.sonder(con, "reichskasse")
    geld.buchen(con, kv["id"], kasse["id"], betrag, "gebuehr" if b["steuerart"] == "gebuehr" and art != "pfaendung" else art,
                f'{ARTEN.get(b["steuerart"], b["steuerart"])} {b["periode"]}'.strip(), k, bezug=az(b))
    if b["steuerart"] in LAENDERANTEIL and kv["inhaber_id"]:
        laenderanteil_buchen(con, kv["inhaber_id"], betrag, k, az(b))
    neu = b["bezahlt"] + betrag
    fertig = neu >= b["betrag"] + b["zuschlag"]
    con.execute("UPDATE st_bescheide SET bezahlt=?, status=?, erledigt=? WHERE id=?",
                (neu, "bezahlt" if fertig else "offen", int(time.time()) if fertig else None, b["id"]))
    return betrag


def gebuehr_erheben(con, konto_id, schl, text, k):
    """Verwaltungsgebühr nach Gebührenordnung als Bescheid an das Privatkonto (0 M = gebührenfrei)."""
    betrag = int(geld.einstellung(con, "gebuehren").get(schl, 0) or 0)
    if betrag <= 0:
        return None
    konto = geld.privatkonto(con, konto_id)
    return erstellen(con, konto, "gebuehr", betrag, f"Gebühr nach der Gebührenordnung: {geld.GEBUEHR_NAMEN.get(schl, schl)} ({text})", k)


def bescheid_tabelle(con, rows, pfad, leer="Keine Bescheide.", verwaltung=False):
    zeilen = []
    heute = date.today().isoformat()
    for b in rows:
        kl, t = STATUS[b["status"]]
        marke = amt.status_marke("nein" if b["status"] == "offen" and b["faellig"] < heute else kl,
                                 "Überfällig" if b["status"] == "offen" and b["faellig"] < heute else t)
        z = [f'<a href="{pfad}{b["id"]}/">{az(b)}</a>', esc(ARTEN.get(b["steuerart"], b["steuerart"])) + (f' <span class="az">{esc(b["periode"])}</span>' if b["periode"] else "")]
        if verwaltung:
            r = geld.konto(con, b["konto"])
            z.append(f'<a href="{PFAD}amt/konten/{r["id"]}/">{esc(r["name"])}</a>' if r else "–")
        z += [f'<span class="sa-betrag">{mark(b["betrag"] + b["zuschlag"])}</span>', f'<span class="sa-betrag">{mark(offen(b))}</span>', _d(b["faellig"]),
              marke + (f' <span class="az">Mahnstufe {b["mahnstufe"]}</span>' if b["mahnstufe"] else "")]
        zeilen.append(z)
    kopf = ["Aktenzeichen", "Steuerart"] + (["Konto"] if verwaltung else []) + ["Betrag", "Offen", "Fällig", "Stand"]
    return amt.tabelle(kopf, zeilen, leer)


def _bescheid_html(con, b, request, k, verwaltung):
    r = geld.konto(con, b["konto"])
    zahlungen = con.execute("SELECT * FROM gk_buchungen WHERE bezug=? AND art IN ('steuer','gebuehr','pfaendung','bussgeld') ORDER BY id", (az(b),)).fetchall()
    daten = [("Aktenzeichen", az(b)), ("Steuerpflichtig", sa.konto_kurz(r)), ("Steuerart", esc(ARTEN.get(b["steuerart"], b["steuerart"]))),
             ("Zeitraum", esc(b["periode"] or "–")), ("Festgesetzter Betrag", mark(b["betrag"])),
             ("Säumniszuschläge", mark(b["zuschlag"]) + (f' (Mahnstufe {b["mahnstufe"]})' if b["mahnstufe"] else "")),
             ("Bereits gezahlt", mark(b["bezahlt"])), ("Noch offen", f"<b>{mark(offen(b))}</b>"), ("Fällig am", _d(b["faellig"])),
             ("Stand", amt.status_marke(*STATUS[b["status"]])), ("Festgesetzt", f'{amt._zeit(b["erstellt"])} · {esc(b["autor_name"])}')]
    if b["vermerk"]:
        daten.append(("Vermerk", esc(b["vermerk"])))
    return (amt.daten_tabelle(daten) + f'<h2>Berechnungsgrundlage</h2><p style="white-space:pre-wrap">{esc(b["grundlage"])}</p>'
            + "<h2>Zahlungen</h2>" + amt.tabelle(["Zeit", "Art", "Betrag"], [(amt._zeit(z["zeit"]), esc(geld.BUCHUNGSART.get(z["art"], z["art"])),
                                                                              mark(z["betrag"])) for z in zahlungen], "Noch keine Zahlungen."))


# ---------------------------------------------------------------- Bürger

@sa.seite("mitglied")
async def meine(request, k):
    con = request.app["db"]
    ids = [r["id"] for r in geld.verfuegbare_konten(con, k) if r["art"] in ("privat", "gewerbe")]
    rows = con.execute(f"SELECT * FROM st_bescheide WHERE konto IN ({','.join('?' * len(ids))}) ORDER BY status='offen' DESC, faellig DESC LIMIT 300",
                       ids).fetchall() if ids else []
    off = [b for b in rows if b["status"] == "offen"]
    jahr = date.today().year
    gezahlt = sum(b["bezahlt"] for b in rows if b["jahr"] == jahr)
    lohn = con.execute("SELECT SUM(lohnsteuer), SUM(abgaben) FROM bs_abrechnungen WHERE konto_id=? AND substr(periode,1,4)=?", (k["id"], str(jahr))).fetchone()
    kz = [("Offen", mark(sum(offen(b) for b in off))), (f"Gezahlt {jahr} (Bescheide)", mark(gezahlt)),
          (f"Lohnsteuer {jahr}", mark(lohn[0] or 0)), (f"Sozialabgaben {jahr}", mark(lohn[1] or 0))]
    inhalt = (f'<h1>{amt.ic("receipt")} Steuern & Gebühren</h1>{amt.meldung(request)}'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              '<h2>Offene Bescheide</h2>' + bescheid_tabelle(con, off, f"{PFAD}steuern/", "Keine offenen Bescheide – alles beglichen.")
              + '<h2>Alle Bescheide</h2>' + bescheid_tabelle(con, [b for b in rows if b["status"] != "offen"], f"{PFAD}steuern/", "Noch keine erledigten Bescheide.")
              + f'<p class="sa-hinweis">Lohnsteuer und Sozialabgaben werden direkt vom Gehalt einbehalten (siehe <a href="{PFAD}gehalt/">Gehalt</a>).</p>')
    return sa.ant(request, k, "Steuern & Gebühren", "sa-steuern", inhalt)


def _bescheid(con, i):
    b = con.execute("SELECT * FROM st_bescheide WHERE id=?", (i,)).fetchone() if str(i).isdigit() else None
    if not b:
        raise web.HTTPNotFound(text="Bescheid nicht gefunden.")
    return b


@sa.seite("mitglied")
async def mein_bescheid(request, k):
    con = request.app["db"]
    b = _bescheid(con, request.match_info["id"])
    r = geld.konto(con, b["konto"])
    if not geld.darf_einsehen(con, k, r):
        raise web.HTTPNotFound(text="Bescheid nicht gefunden.")
    zahlen_form = ""
    if b["status"] == "offen":
        zahlen_form = (f'<form method="post" action="{PFAD}steuern/{b["id"]}/bezahlen">{amt.csrf_feld(request)}<div class="aktionen">'
                       f'<button class="btn" type="submit">{amt.ic("check")}{mark(offen(b))} jetzt bezahlen</button>'
                       f'<span class="az">vom Konto {esc(r["name"])} (Guthaben {mark(r["saldo"])})</span></div></form>')
    inhalt = (f'<h1>{amt.ic("receipt")} Bescheid {az(b)}</h1><p class="az"><a href="{PFAD}steuern/">← Steuern & Gebühren</a></p>{amt.meldung(request)}'
              + zahlen_form + _bescheid_html(con, b, request, k, False)
              + f'<p><a class="btn zweit" href="{PFAD}steuern/{b["id"]}/pdf">{amt.ic("file-down")}Bescheid als PDF</a></p>')
    return sa.ant(request, k, f"Bescheid {az(b)}", "sa-steuern", inhalt)


async def bezahlen(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    await sa.formular(request)
    con = request.app["db"]
    b = _bescheid(con, request.match_info["id"])
    r = geld.konto(con, b["konto"])
    pfad = f"{PFAD}steuern/{b['id']}/"
    if not any(x["id"] == r["id"] for x in geld.verfuegbare_konten(con, k)) or b["status"] != "offen":
        sa.weiter(pfad, "Dieser Bescheid kann nicht bezahlt werden.", True)
    try:
        betrag = zahlen(con, b, k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(pfad, str(e), True)
    sa.weiter(pfad, f"{mark(betrag)} bezahlt. Vielen Dank.")


async def bescheid_pdf(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    con = request.app["db"]
    b = _bescheid(con, request.match_info["id"])
    r = geld.konto(con, b["konto"])
    if not geld.darf_einsehen(con, k, r):
        raise web.HTTPNotFound()
    hinweis = ("<h2>Zahlungsaufforderung</h2><p>Bitte zahlen Sie den offenen Betrag bis zum Fälligkeitstag über das Portal des Schatzamts "
               f"({amt.config.SITE_URL}{PFAD}steuern/). Bei Säumnis wird je Mahnstufe ein Säumniszuschlag von {geld.einstellung(con, 'saeumnis')} % "
               "erhoben; das Schatzamt kann den Betrag vom Konto einziehen.</p>") if b["status"] == "offen" else ""
    inhalt = f'<h1>{esc(ARTEN.get(b["steuerart"], "Steuer"))}bescheid</h1><p class="az">{az(b)} · {esc(r["name"])}</p>' + _bescheid_html(con, b, request, k, False) + hinweis
    request["konto"] = k
    return await amt._pdf_antwort(request, az(b), f"Bescheid {az(b)}", inhalt, stelle=geld.STELLE, az=az(b), einstufung="",
                                  doktyp="Steuerbescheid" if b["steuerart"] not in ("gebuehr", "bussgeld") else ARTEN[b["steuerart"]] + "nbescheid",
                                  qr_url=f"{amt.config.SITE_URL}{PFAD}steuern/{b['id']}/")


# ---------------------------------------------------------------- Verwaltung

@sa.seite("beamter")
async def amt_liste(request, k):
    con = request.app["db"]
    status = request.query.get("status", "offen")
    art = request.query.get("art", "")
    q = " ".join(request.query.get("q", "").split())[:60]
    wo, args = [], []
    if status == "ueberfaellig":
        wo.append("b.status='offen' AND b.faellig<?"); args.append(date.today().isoformat())
    elif status in STATUS:
        wo.append("b.status=?"); args.append(status)
    if art in ARTEN:
        wo.append("b.steuerart=?"); args.append(art)
    if q:
        wo.append("(k.name LIKE ? OR k.nummer LIKE ? OR ('ST-' || b.jahr || '-' || printf('%04d', b.nr)) LIKE ?)"); args += [f"%{q}%"] * 2 + [f"%{q.upper()}%"]
    rows = con.execute("SELECT b.* FROM st_bescheide b JOIN gk_konten k ON k.id=b.konto" + (" WHERE " + " AND ".join(wo) if wo else "")
                       + " ORDER BY b.faellig LIMIT 500", args).fetchall()
    summe = sum(offen(b) for b in rows)
    reiter = '<p class="reiter">' + " ".join(f'<a href="?status={s}" class="{"aktiv" if s == status else ""}">{t}</a>' for s, t in
                                            [("offen", "Offen"), ("ueberfaellig", "Überfällig"), ("bezahlt", "Bezahlt"), ("erlassen", "Erlassen"),
                                             ("storniert", "Storniert"), ("alle", "Alle")]) + "</p>"
    arten = "".join(f'<option value="{a}"{" selected" if a == art else ""}>{esc(n)}</option>' for a, n in ARTEN.items())
    mahnen = ""
    if status == "ueberfaellig" and rows:
        mahnen = (f'<form method="post" action="{PFAD}amt/steuern/mahnlauf">{amt.csrf_feld(request)}<button class="btn zweit" type="submit">'
                  f'{amt.ic("send")}Alle {len(rows)} überfälligen Bescheide mahnen</button></form>')
    inhalt = (f'<h1>{amt.ic("receipt")} Steuerverwaltung</h1>{amt.meldung(request)}'
              f'<p class="aktionen"><a class="btn" href="{PFAD}amt/steuern/neu/">{amt.ic("file-plus")}Einzelbescheid</a>'
              + (f'<a class="btn zweit" href="{PFAD}amt/steuerlauf/">{amt.ic("users")}Steuerlauf</a>' if geld.ist_leitung(k) else "") + '</p>'
              f'{reiter}<form class="sa-leiste" method="get"><input type="hidden" name="status" value="{esc(status)}">'
              f'<div><label for="a">Steuerart</label><select id="a" name="art"><option value="">Alle</option>{arten}</select></div>'
              f'<div><label for="q">Konto oder Aktenzeichen</label><input type="search" id="q" name="q" value="{esc(q)}"></div>'
              f'<button class="btn zweit" type="submit">{amt.ic("search")}Filtern</button></form>'
              f'<p class="az">{len(rows)} Bescheide · offen insgesamt {mark(summe)}</p>{mahnen}'
              + bescheid_tabelle(con, rows, f"{PFAD}amt/steuern/", verwaltung=True))
    return sa.ant(request, k, "Steuerverwaltung", "sa-amt-steuern", inhalt)


@sa.seite("beamter")
async def amt_neu(request, k):
    con = request.app["db"]
    an = request.query.get("an", "")
    arten = "".join(f'<option value="{a}">{esc(n)}</option>' for a, n in ARTEN.items() if a not in LAUF_ARTEN or True)
    inhalt = (f'<h1>{amt.ic("file-plus")} Einzelbescheid</h1>{amt.meldung(request)}'
              f'<form class="sa-formular" method="post" action="{PFAD}amt/steuern/neu/">{amt.csrf_feld(request)}<div class="zeilen">'
              f'<div><label for="an">Konto (Kontonummer)</label><input type="text" id="an" name="an" required class="sa-nr" value="{esc(an)}"></div>'
              f'<div><label for="art">Steuerart</label><select id="art" name="art">{arten}</select></div>'
              '<div><label for="b">Betrag in Kronen</label><input type="text" id="b" name="betrag" required></div>'
              '<div><label for="p">Zeitraum (optional)</label><input type="text" id="p" name="periode" maxlength="20" placeholder="z. B. 2026-11"></div>'
              f'<div><label for="f">Zahlungsfrist (Tage)</label><input type="text" id="f" name="frist" value="{geld.einstellung(con, "frist_tage")}"></div></div>'
              '<div><label for="g">Begründung / Berechnungsgrundlage</label><textarea id="g" name="grundlage" required maxlength="2000"></textarea></div>'
              '<div><label><input type="checkbox" name="einziehen" value="1"> Sofort vom Konto einziehen, soweit gedeckt</label></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Bescheid festsetzen</button></div></form>'
              '<p class="sa-hinweis">Bußgelder (z. B. aus Verfahren der Polizei oder Inquisition) werden ebenfalls als Einzelbescheid festgesetzt.</p>')
    return sa.ant(request, k, "Einzelbescheid", "sa-amt-steuern", inhalt)


async def amt_neu_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_beamter(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    r = geld.nach_nummer(con, form.get("an"))
    art, betrag = str(form.get("art", "")), geld.betrag_lesen(form.get("betrag"))
    grund = str(form.get("grundlage", "")).strip()[:2000]
    frist = int(form.get("frist")) if str(form.get("frist", "")).isdigit() else None
    if not r or r["art"] == "sonder" or art not in ARTEN or not betrag or not grund:
        sa.weiter(f"{PFAD}amt/steuern/neu/?an={esc(str(form.get('an', '')))}", "Bitte gültige Kontonummer, Steuerart, Betrag und Begründung angeben.", True)
    b = erstellen(con, r, art, betrag, grund, k, periode=sa._f(form, "periode", 20), faellig=_faellig(con, frist))
    if not b:
        sa.weiter(f"{PFAD}amt/steuern/neu/", "Für dieses Konto, diese Steuerart und diesen Zeitraum besteht bereits ein Bescheid.", True)
    eingezogen = 0
    if form.get("einziehen") == "1":
        eingezogen = zahlen(con, b, k, art="pfaendung")
    geld.protokoll(con, k, "Bescheid festgesetzt", f"{az(b)} {ARTEN[art]} {mark(betrag)} für {r['name']}" + (f", eingezogen {mark(eingezogen)}" if eingezogen else ""))
    con.commit()
    _dm_bescheid(request, r, b)
    sa.weiter(f"{PFAD}amt/steuern/{b['id']}/", f"Bescheid {az(b)} festgesetzt." + (f" {mark(eingezogen)} eingezogen." if eingezogen else ""))


def _dm_bescheid(request, r, b, text=None):
    if r["inhaber_id"]:
        sa.dm(request, r["inhaber_id"], text or (f"Das Kaiserliche Schatz- und Währungsamt hat einen Bescheid festgesetzt: {ARTEN.get(b['steuerart'])} "
                                                 f"{mark(b['betrag'])}, fällig am {_d(b['faellig'])} ({az(b)}).\n{amt.config.SITE_URL}{PFAD}steuern/{b['id']}/"))


@sa.seite("beamter")
async def amt_bescheid(request, k):
    con = request.app["db"]
    b = _bescheid(con, request.match_info["id"])
    p = f"{PFAD}amt/steuern/{b['id']}/"
    akt = ""
    if b["status"] == "offen":
        c = amt.csrf_feld(request)
        akt = (f'<h2>Maßnahmen</h2><div class="sa-leiste">'
               f'<form method="post" action="{p}einziehen">{c}<button class="btn" type="submit">{amt.ic("wallet")}Vom Konto einziehen (pfänden)</button></form>'
               f'<form method="post" action="{p}mahnen">{c}<button class="btn zweit" type="submit">{amt.ic("send")}Mahnen (+ {geld.einstellung(con, "saeumnis")} %)</button></form></div>'
               f'<form class="sa-leiste" method="post" action="{p}erlassen">{c}<div><label for="g">Begründung</label>'
               '<input type="text" id="g" name="grund" required maxlength="160"></div>'
               f'<button class="btn zweit" name="art" value="erlassen" type="submit">Erlassen</button>'
               + (f'<button class="btn zweit gefahr" name="art" value="storniert" type="submit">Stornieren</button>' if b["bezahlt"] == 0 else "") + '</form>')
    inhalt = (f'<h1>{amt.ic("receipt")} Bescheid {az(b)}</h1><p class="az"><a href="{PFAD}amt/steuern/">← Steuerverwaltung</a></p>{amt.meldung(request)}'
              + akt + _bescheid_html(con, b, request, k, True)
              + f'<p><a class="btn zweit" href="{PFAD}steuern/{b["id"]}/pdf">{amt.ic("file-down")}PDF</a></p>')
    return sa.ant(request, k, f"Bescheid {az(b)}", "sa-amt-steuern", inhalt)


async def _amt_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_beamter(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    b = _bescheid(con, request.match_info["id"])
    if b["status"] != "offen":
        sa.weiter(f"{PFAD}amt/steuern/{b['id']}/", "Der Bescheid ist bereits erledigt.", True)
    return k, form, con, b, f"{PFAD}amt/steuern/{b['id']}/"


def mahnen(con, b, k):
    zuschlag = int(round(b["betrag"] * float(geld.einstellung(con, "saeumnis")) / 100))
    con.execute("UPDATE st_bescheide SET mahnstufe=mahnstufe+1, zuschlag=zuschlag+?, faellig=? WHERE id=?", (zuschlag, _faellig(con), b["id"]))
    return zuschlag


async def amt_einziehen(request):
    k, form, con, b, p = await _amt_post(request)
    betrag = zahlen(con, b, k, art="pfaendung")
    geld.protokoll(con, k, "Pfändung", f"{az(b)}: {mark(betrag)} eingezogen")
    con.commit()
    r = geld.konto(con, b["konto"])
    if betrag:
        _dm_bescheid(request, r, b, f"Das Schatzamt hat {mark(betrag)} von deinem Konto {r['name']} eingezogen ({az(b)}, {ARTEN.get(b['steuerart'])}).")
    sa.weiter(p, f"{mark(betrag)} eingezogen." if betrag else "Kein Guthaben vorhanden – nichts eingezogen.", not betrag)


async def amt_mahnen(request):
    k, form, con, b, p = await _amt_post(request)
    z = mahnen(con, b, k)
    geld.protokoll(con, k, "Mahnung", f"{az(b)}: Mahnstufe {b['mahnstufe'] + 1}, Zuschlag {mark(z)}")
    con.commit()
    b = _bescheid(con, b["id"])
    _dm_bescheid(request, geld.konto(con, b["konto"]), b, f"Mahnung ({az(b)}, Stufe {b['mahnstufe']}): Bitte zahle {mark(offen(b))} bis {_d(b['faellig'])}. "
                                                          f"Säumniszuschlag {mark(z)}.\n{amt.config.SITE_URL}{PFAD}steuern/{b['id']}/")
    sa.weiter(p, f"Gemahnt, Säumniszuschlag {mark(z)}.")


async def amt_erlassen(request):
    k, form, con, b, p = await _amt_post(request)
    status = "storniert" if form.get("art") == "storniert" and b["bezahlt"] == 0 else "erlassen"
    grund = sa._f(form, "grund", 160)
    con.execute("UPDATE st_bescheide SET status=?, erledigt=?, vermerk=? WHERE id=?", (status, int(time.time()), f"{STATUS[status][1]}: {grund}", b["id"]))
    geld.protokoll(con, k, f"Bescheid {STATUS[status][1].lower()}", f"{az(b)}: {grund}")
    con.commit()
    sa.weiter(p, f"Bescheid {STATUS[status][1].lower()}.")


async def amt_mahnlauf(request):
    k = await anmeldung.konto(request)
    if not geld.ist_beamter(k):
        raise web.HTTPForbidden()
    await sa.formular(request)
    con = request.app["db"]
    rows = con.execute("SELECT * FROM st_bescheide WHERE status='offen' AND faellig<?", (date.today().isoformat(),)).fetchall()
    for b in rows:
        mahnen(con, b, k)
    geld.protokoll(con, k, "Mahnlauf", f"{len(rows)} Bescheide gemahnt")
    con.commit()
    for b in rows:
        b = _bescheid(con, b["id"])
        _dm_bescheid(request, geld.konto(con, b["konto"]), b, f"Mahnung ({az(b)}): Bitte zahle {mark(offen(b))} bis {_d(b['faellig'])}.\n"
                                                              f"{amt.config.SITE_URL}{PFAD}steuern/{b['id']}/")
    sa.weiter(f"{PFAD}amt/steuern/?status=offen", f"{len(rows)} Bescheide gemahnt.")


# ---------------------------------------------------------------- Steuerlauf

def steuerlauf_berechnen(con, arten, periode):
    """[(Konto, Steuerart, Betrag, Grundlage)] für den Lauf (ohne bereits veranlagte Konten)."""
    out = []
    schon = {(r["konto"], r["steuerart"]) for r in con.execute("SELECT konto, steuerart FROM st_bescheide WHERE periode=? AND status!='storniert'", (periode,))}
    if "kopfsteuer" in arten:
        betrag = int(geld.einstellung(con, "kopfsteuer"))
        for z in con.execute("SELECT DISTINCT konto_id FROM amt_akten WHERE status='staatsbuerger'"):
            if betrag > 0 and con.execute("SELECT 1 FROM konten WHERE id=?", (z["konto_id"],)).fetchone():
                r = geld.privatkonto(con, z["konto_id"])
                if (r["id"], "kopfsteuer") not in schon:
                    out.append((r, "kopfsteuer", betrag, f"Kopfsteuer für Staatsbürger, Zeitraum {periode}: {mark(betrag)}"))
    if "vermoegensteuer" in arten:
        v = geld.einstellung(con, "vermoegensteuer")
        for r in con.execute("SELECT * FROM gk_konten WHERE art IN ('privat','gewerbe') AND saldo>?", (v["freibetrag"],)):
            steuer = int(round((r["saldo"] - v["freibetrag"]) * float(v["satz"]) / 100))
            if steuer > 0 and (r["id"], "vermoegensteuer") not in schon:
                out.append((r, "vermoegensteuer", steuer, f"Guthaben {mark(r['saldo'])} − Freibetrag {mark(v['freibetrag'])} = "
                                                         f"{mark(r['saldo'] - v['freibetrag'])} × {v['satz']} % = {mark(steuer)}"))
    if "gewerbesteuer" in arten:
        g = geld.einstellung(con, "gewerbesteuer")
        letzte = con.execute("SELECT MAX(zeit) FROM st_laeufe WHERE arten LIKE '%gewerbesteuer%'").fetchone()[0] or int(time.time()) - 30 * 86400
        for r in con.execute("SELECT k.* FROM gk_konten k JOIN gk_gewerbe g ON g.konto=k.id WHERE g.status='aktiv'"):
            ein = con.execute("SELECT SUM(betrag) FROM gk_buchungen WHERE an=? AND zeit>=? AND art='ueberweisung'", (r["id"], letzte)).fetchone()[0] or 0
            steuer = int(g["grund"]) + int(round(ein * float(g["satz"]) / 100))
            if steuer > 0 and (r["id"], "gewerbesteuer") not in schon:
                out.append((r, "gewerbesteuer", steuer, f"Grundbetrag {mark(g['grund'])} + {g['satz']} % der Eingänge seit "
                                                       f"{amt._zeit(letzte, False)} ({mark(ein)}) = {mark(steuer)}"))
    return out


@sa.seite("leitung")
async def steuerlauf(request, k):
    con = request.app["db"]
    periode = " ".join(request.query.get("periode", date.today().strftime("%Y-%m")).split())[:20]
    arten = [a for a in LAUF_ARTEN if request.query.get(a)] if request.query.get("probe") else list(LAUF_ARTEN)
    probe = ""
    if request.query.get("probe"):
        liste = steuerlauf_berechnen(con, arten, periode)
        summe = sum(x[2] for x in liste)
        gedeckt = sum(1 for x in liste if x[0]["saldo"] >= x[2])
        versteckt = "".join(f'<input type="hidden" name="{a}" value="1">' for a in arten)
        probe = (f'<h2>Probelauf {esc(periode)}</h2><p class="az">{len(liste)} Bescheide · zusammen {mark(summe)} · {gedeckt} sofort gedeckt</p>'
                 + amt.tabelle(["Konto", "Steuerart", "Betrag", "Guthaben", "Grundlage"],
                               [(esc(r["name"]), esc(ARTEN[a]), mark(b), sa.betrag_html(r["saldo"], False), esc(g)) for r, a, b, g in liste[:400]],
                               "Keine Steuerpflichtigen – für diesen Zeitraum ist alles veranlagt.")
                 + (f'<form method="post" action="{PFAD}amt/steuerlauf/">{amt.csrf_feld(request)}<input type="hidden" name="periode" value="{esc(periode)}">'
                    f'{versteckt}<label><input type="checkbox" name="einziehen" value="1" checked> Gedeckte Beträge sofort einziehen</label>'
                    f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Steuerlauf ausführen ({len(liste)} Bescheide)</button></div></form>'
                    if liste else ""))
    laeufe = con.execute("SELECT * FROM st_laeufe ORDER BY id DESC LIMIT 30").fetchall()
    haken = "".join(f'<label style="display:inline-flex;gap:6px;margin-right:16px"><input type="checkbox" name="{a}" value="1"{" checked" if a in arten else ""}> {ARTEN[a]}</label>'
                    for a in LAUF_ARTEN)
    inhalt = (f'<h1>{amt.ic("users")} Steuerlauf</h1>{amt.meldung(request)}'
              '<p class="az">Veranlagt Kopf-, Vermögen- und Gewerbesteuer für einen Zeitraum. Zuerst wird ein Probelauf angezeigt.</p>'
              f'<form class="sa-formular" method="get"><input type="hidden" name="probe" value="1"><div class="zeilen">'
              f'<div><label for="p">Zeitraum</label><input type="text" id="p" name="periode" value="{esc(periode)}" required maxlength="20"></div></div>'
              f'<div>{haken}</div><div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("search")}Probelauf</button></div></form>{probe}'
              '<h2>Bisherige Steuerläufe</h2>' + amt.tabelle(["Zeit", "Zeitraum", "Steuerarten", "Bescheide", "Summe", "Sofort eingezogen", "Durch"],
                                                            [(amt._zeit(l["zeit"]), esc(l["periode"]), esc(", ".join(ARTEN[a] for a in json.loads(l["arten"]))),
                                                              l["anzahl"], mark(l["summe"]), mark(l["eingezogen"]), esc(l["autor_name"])) for l in laeufe], "Noch kein Steuerlauf."))
    return sa.ant(request, k, "Steuerlauf", "sa-amt-steuern", inhalt)


async def steuerlauf_ausfuehren(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    periode = sa._f(form, "periode", 20)
    arten = [a for a in LAUF_ARTEN if form.get(a)]
    if not periode or not arten:
        sa.weiter(f"{PFAD}amt/steuerlauf/", "Bitte Zeitraum und Steuerarten wählen.", True)
    liste = steuerlauf_berechnen(con, arten, periode)
    cur = con.execute("INSERT INTO st_laeufe (periode, arten, anzahl, summe, eingezogen, zeit, autor_name) VALUES (?,?,0,0,0,?,?)",
                      (periode, json.dumps(arten), int(time.time()), k["name"]))
    lauf = cur.lastrowid
    erstellt, summe, eingezogen = [], 0, 0
    for r, art, betrag, grund in liste:
        b = erstellen(con, r, art, betrag, grund, k, periode=periode, lauf=lauf)
        if not b:
            continue
        summe += betrag
        if form.get("einziehen") and geld.konto(con, r["id"])["saldo"] >= betrag:
            eingezogen += zahlen(con, b, k, art="steuer")
        erstellt.append((r, _bescheid(con, b["id"])))
    con.execute("UPDATE st_laeufe SET anzahl=?, summe=?, eingezogen=? WHERE id=?", (len(erstellt), summe, eingezogen, lauf))
    geld.protokoll(con, k, "Steuerlauf", f"{periode}: {len(erstellt)} Bescheide, {mark(summe)}, eingezogen {mark(eingezogen)}")
    con.commit()
    je = {}
    for r, b in erstellt:
        if r["inhaber_id"]:
            je.setdefault(r["inhaber_id"], []).append(b)
    for kid, bs in je.items():
        zeilen = "\n".join(f"• {ARTEN[b['steuerart']]} {mark(b['betrag'])} – {'bezahlt (eingezogen)' if b['status'] == 'bezahlt' else 'fällig ' + _d(b['faellig'])}" for b in bs)
        sa.dm(request, kid, f"Steuerlauf {periode} des Kaiserlichen Schatz- und Währungsamts:\n{zeilen}\n{amt.config.SITE_URL}{PFAD}steuern/")
    sa.weiter(f"{PFAD}amt/steuerlauf/", f"Steuerlauf {periode}: {len(erstellt)} Bescheide über {mark(summe)}, davon {mark(eingezogen)} sofort eingezogen.")


# ---------------------------------------------------------------- Sätze festlegen

@sa.seite("leitung")
async def tarife_bearbeiten(request, k):
    con = request.app["db"]
    e = lambda s: geld.einstellung(con, s)
    stufen = "\n".join(f"{mark(b, einheit=False) if b else '*'} {s}" for b, s in e("lohnsteuer")["stufen"])
    v, g = e("vermoegensteuer"), e("gewerbesteuer")
    feld = lambda n, label, wert, hilfe="": (f'<div><label for="{n}">{esc(label)}</label><input type="text" id="{n}" name="{n}" value="{esc(str(wert))}">'
                                            + (f'<span class="sa-hinweis">{esc(hilfe)}</span>' if hilfe else "") + "</div>")
    geb = "".join(feld("geb_" + s, f"Gebühr {geld.GEBUEHR_NAMEN.get(s, s)} (Kr)", mark(b, einheit=False)) for s, b in e("gebuehren").items())
    inhalt = (f'<h1>{amt.ic("percent")} Sätze festlegen</h1>{amt.meldung(request)}'
              f'<form class="sa-formular" method="post" action="{PFAD}amt/tarife/">{amt.csrf_feld(request)}'
              '<h2>Lohnsteuer</h2><label for="st">Stufen: je Zeile „Obergrenze Monatsbrutto in Kronen“ und „Grenzsteuersatz in %“, letzte Zeile mit * für „darüber“</label>'
              f'<textarea id="st" name="stufen" rows="5" class="sa-nr">{esc(stufen)}</textarea>'
              '<h2>Abgaben und Steuern</h2><div class="zeilen">'
              + feld("sozialabgabe", "Sozialabgabe (%)", e("sozialabgabe")) + feld("laenderanteil", "Länderanteil (%)", e("laenderanteil"))
              + feld("kopfsteuer", "Kopfsteuer je Lauf (Kr)", mark(e("kopfsteuer"), einheit=False))
              + feld("v_satz", "Vermögensteuer (%)", v["satz"]) + feld("v_frei", "Vermögensteuer Freibetrag (Kr)", mark(v["freibetrag"], einheit=False))
              + feld("g_grund", "Gewerbesteuer Grundbetrag (Kr)", mark(g["grund"], einheit=False)) + feld("g_satz", "Gewerbesteuer auf Eingänge (%)", g["satz"])
              + feld("umsatzsteuer", "Umsatzsteuer (%)", e("umsatzsteuer")) + feld("ueberweisungssteuer", "Überweisungssteuer (%)", e("ueberweisungssteuer"))
              + feld("saeumnis", "Säumniszuschlag je Mahnstufe (%)", e("saeumnis")) + feld("frist_tage", "Zahlungsfrist (Tage)", e("frist_tage"))
              + feld("startguthaben", "Startguthaben bei Kontoeröffnung (Kr)", mark(e("startguthaben"), einheit=False))
              + f'</div><h2>Verwaltungsgebühren</h2><div class="zeilen">{geb}</div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Sätze speichern</button></div></form>')
    return sa.ant(request, k, "Sätze festlegen", "sa-amt-tarife", inhalt)


async def tarife_speichern(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    pfad = f"{PFAD}amt/tarife/"
    fehler = []

    def pz(n):
        p = geld.prozent_lesen(form.get(n, ""))
        if p is None:
            fehler.append(n)
        return p if p is None or p != int(p) else int(p)

    def mk(n):
        b = geld.betrag_lesen(form.get(n, ""), null_erlaubt=True)
        if b is None:
            fehler.append(n)
        return b
    stufen = []
    for zeile in str(form.get("stufen", "")).splitlines():
        teile = zeile.split()
        if len(teile) != 2:
            continue
        bis = None if teile[0] == "*" else geld.betrag_lesen(teile[0])
        satz = geld.prozent_lesen(teile[1])
        if (bis is None and teile[0] != "*") or satz is None:
            fehler.append("stufen")
            break
        stufen.append([bis, satz if satz != int(satz) else int(satz)])
    if not stufen or stufen[-1][0] is not None or any(stufen[i][0] >= stufen[i + 1][0] for i in range(len(stufen) - 2)):
        fehler.append("stufen (aufsteigend, letzte Zeile *)")
    werte = {"sozialabgabe": pz("sozialabgabe"), "laenderanteil": pz("laenderanteil"), "kopfsteuer": mk("kopfsteuer"),
             "vermoegensteuer": {"satz": pz("v_satz"), "freibetrag": mk("v_frei")}, "gewerbesteuer": {"grund": mk("g_grund"), "satz": pz("g_satz")},
             "umsatzsteuer": pz("umsatzsteuer"), "ueberweisungssteuer": pz("ueberweisungssteuer"), "saeumnis": pz("saeumnis"),
             "startguthaben": mk("startguthaben"), "lohnsteuer": {"stufen": stufen},
             "gebuehren": {s: mk("geb_" + s) for s in geld.einstellung(con, "gebuehren")}}
    frist = str(form.get("frist_tage", "")).strip()
    if not frist.isdigit() or not 1 <= int(frist) <= 365:
        fehler.append("frist_tage")
    if fehler:
        sa.weiter(pfad, "Bitte die Eingaben prüfen: " + ", ".join(fehler), True)
    werte["frist_tage"] = int(frist)
    for s, w in werte.items():
        geld.einstellung_setzen(con, s, w, k)
    con.commit()
    sa.weiter(pfad, "Sätze gespeichert. Sie gelten ab sofort und sind unter „Tarife & Sätze“ öffentlich einsehbar.")


# ---------------------------------------------------------------- Gebühren-Hooks (Meldewesen, Zoll)

def nach_pass(request, con, z, art, nr, k):
    b = gebuehr_erheben(con, z["konto_id"], art, f"Nr. {nr}", k)
    if b:
        con.commit()
        _dm_bescheid(request, geld.konto(con, b["konto"]), b, f"Gebührenbescheid {az(b)}: {mark(b['betrag'])} für {meldewesen.PASSARTEN[art][0]} {nr}, "
                                                              f"fällig am {_d(b['faellig'])}.\n{amt.config.SITE_URL}{PFAD}steuern/{b['id']}/")


def nach_stempel(request, con, p, s, k):
    if s["art"] != "visum":
        return
    b = gebuehr_erheben(con, p["konto_id"], "visum", f"{s['zweck']}, gültig bis {s['gueltig_bis']}, Pass {p['nummer']}", k)
    if b:
        con.commit()
        _dm_bescheid(request, geld.konto(con, b["konto"]), b, f"Gebührenbescheid {az(b)}: {mark(b['betrag'])} für dein Visum, fällig am {_d(b['faellig'])}.\n"
                                                              f"{amt.config.SITE_URL}{PFAD}steuern/{b['id']}/")


def registrieren(app):
    import zollwesen
    einrichten(app["db"])
    amt.ICONS.setdefault("file-plus", '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M9 15h6"/><path d="M12 18v-6"/>')
    meldewesen.AUSGESTELLT.append(nach_pass)
    zollwesen.GESTEMPELT.append(nach_stempel)
    r = app.router
    r.add_get(PFAD + "steuern/", meine)
    r.add_get(PFAD + "steuern/{id}/", mein_bescheid)
    r.add_post(PFAD + "steuern/{id}/bezahlen", bezahlen)
    r.add_get(PFAD + "steuern/{id}/pdf", bescheid_pdf)
    r.add_get(PFAD + "amt/steuern/", amt_liste)
    r.add_get(PFAD + "amt/steuern/neu/", amt_neu)
    r.add_post(PFAD + "amt/steuern/neu/", amt_neu_post)
    r.add_post(PFAD + "amt/steuern/mahnlauf", amt_mahnlauf)
    r.add_get(PFAD + "amt/steuern/{id}/", amt_bescheid)
    r.add_post(PFAD + "amt/steuern/{id}/einziehen", amt_einziehen)
    r.add_post(PFAD + "amt/steuern/{id}/mahnen", amt_mahnen)
    r.add_post(PFAD + "amt/steuern/{id}/erlassen", amt_erlassen)
    r.add_get(PFAD + "amt/steuerlauf/", steuerlauf)
    r.add_post(PFAD + "amt/steuerlauf/", steuerlauf_ausfuehren)
    r.add_get(PFAD + "amt/tarife/", tarife_bearbeiten)
    r.add_post(PFAD + "amt/tarife/", tarife_speichern)
