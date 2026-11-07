"""RP-Leitung – dritte Ansicht des Schatzamt-Portals (/schatzamt/rp/).

Zugang: Discord-Administratoren (k["admin"], Mitglied) – das ist die Server- und RP-Leitung. Der Umschalter unter dem Logo zeigt dafür
neben „Staatl.“ und „Privat“ einen kleinen, unauffälligen Knopf „RP“.

Zweck: Greift ein Spieler im Rollenspiel zu kriminellen Mitteln (Bankraub, Unterschlagung, Betrug …) oder braucht die Welt einen Eingriff
von außen, hat die RP-Leitung die Mittel, das im Geldsystem nachzuvollziehen – sauber gebucht (doppelte Buchführung), protokolliert
und für das Schatzamt nachvollziehbar.

* Lagebild: Geldmenge, Summenprobe (alle Salden = 0), gesperrte Konten/Karten, Konten im Minus, Haushaltsnotlagen, größte Überweisungen
  der letzten 7 Tage, neue Konten, offene Fälle.
* Fallakten (rp_faelle, rp_aktionen): jedes RP-Ereignis ist ein Fall mit Verlauf. Aus dem Fall heraus: Raub/Diebstahl, Beschlagnahme,
  Rückgabe/Entschädigung, Geldstrafe, Konto (oder alle Konten einer Person) sperren/freigeben samt Bankkarte, Buchung stornieren, Notiz.
  Auf Wunsch geht eine DM an den Betroffenen.
* Konten: Suche nach Name, Kontonummer oder Discord-ID; Kontoansicht mit Umsätzen und Sperre.
* Protokoll: alle Aktionen der RP-Leitung.
Buchungsart „rp_ereignis“: umgeht weder Doppelbuchung noch Gegenkonto; Beute „außer Landes“ geht auf die Zentralbank (Geld verlässt den
Umlauf), Entschädigung/Rückgabe kann aus Reichskasse oder per Geldschöpfung kommen.
"""
import time

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark, nummer_anzeige

esc = amt.esc
PFAD = sa.PFAD + "rp/"
ART = "rp_ereignis"
geld.BUCHUNGSART.setdefault(ART, "RP-Ereignis (RP-Leitung)")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rp_faelle (
    id INTEGER PRIMARY KEY AUTOINCREMENT, titel TEXT NOT NULL, beschreibung TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'offen',
    erstellt INTEGER NOT NULL, autor_id TEXT NOT NULL, autor_name TEXT NOT NULL, abgeschlossen INTEGER);
CREATE TABLE IF NOT EXISTS rp_aktionen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fall_id INTEGER, zeit INTEGER NOT NULL, art TEXT NOT NULL, text TEXT NOT NULL,
    buchung_id INTEGER, autor_id TEXT NOT NULL, autor_name TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS rp_aktionen_f ON rp_aktionen (fall_id, zeit);
"""

AKTIONEN = {"raub": "Raub / Diebstahl", "einziehen": "Beschlagnahme", "rueckgabe": "Rückgabe / Entschädigung", "strafe": "Geldstrafe",
            "sperren": "Konto sperren", "freigeben": "Konto freigeben", "storno": "Buchung stornieren", "notiz": "Notiz",
            "eroeffnet": "Fall eröffnet", "status": "Status"}


def ist_rp(k):
    return sa.ist_rp(k)


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Hilfen

def konto_finden(con, text):
    """Konto aus Name, Kontonummer, Discord-ID oder Stellenschlüssel (z. B. „reichskasse“, „ts-baden“)."""
    t = " ".join(str(text or "").split())
    if not t:
        raise geld.Fehler("Bitte ein Konto angeben.")
    r = geld.nach_nummer(con, t)
    if r:
        return r
    if t.isdigit() and len(t) >= 15:
        r = geld.privatkonto(con, t, anlegen=False)
        if r:
            return r
    r = con.execute("SELECT * FROM gk_konten WHERE stelle=? AND stelle!=''", (t.lower(),)).fetchone()
    if r:
        return r
    for sql, arg in (("SELECT * FROM gk_konten WHERE lower(name)=lower(?) ORDER BY id", t),
                     ("SELECT * FROM gk_konten WHERE lower(name) LIKE lower(?) ORDER BY id", f"%{t}%")):
        rows = con.execute(sql, (arg,)).fetchall()
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            namen = ", ".join(f'{x["name"]} ({nummer_anzeige(x["nummer"])})' for x in rows[:5])
            raise geld.Fehler(f"„{t}“ ist nicht eindeutig: {namen}. Bitte die Kontonummer verwenden.")
    raise geld.Fehler(f"Kein Konto zu „{t}“ gefunden.")


def konto_liste(con):
    """<datalist> mit allen Konten zur Eingabehilfe."""
    opt = "".join(f'<option value="{esc(r["name"])}" label="{esc(geld.art_name(r))} {esc(nummer_anzeige(r["nummer"]))}">'
                  for r in con.execute("SELECT * FROM gk_konten WHERE stelle NOT IN ('zentralbank','volkswirtschaft') ORDER BY art, name"))
    return f'<datalist id="rp-konten">{opt}</datalist>'


def konto_feld(fid, name, bez, wert="", pflicht=True):
    return (f'<div><label for="{fid}">{esc(bez)}</label><input type="text" id="{fid}" name="{name}" list="rp-konten" autocomplete="off"'
            f'{" required" if pflicht else ""} value="{esc(wert)}" placeholder="Name, Kontonummer oder Discord-ID"></div>')


def kurz(r):
    return f'{r["name"]} ({nummer_anzeige(r["nummer"])})'


def aktion_schreiben(con, k, fall, art, text, buchung=None):
    con.execute("INSERT INTO rp_aktionen (fall_id, zeit, art, text, buchung_id, autor_id, autor_name) VALUES (?,?,?,?,?,?,?)",
                (fall, int(time.time()), art, text[:600], buchung, k["id"], k["name"]))
    geld.protokoll(con, k, "RP-Leitung: " + AKTIONEN.get(art, art), (f"Fall {fall}: " if fall else "") + text)


def benachrichtigen(request, r, text):
    if text and r["inhaber_id"]:
        sa.dm(request, r["inhaber_id"], text[:1500])


def konten_der_person(con, r):
    """Alle Privat- und Gewerbekonten desselben Inhabers (bei Kassen nur das Konto selbst)."""
    if r["inhaber_id"]:
        return con.execute("SELECT * FROM gk_konten WHERE inhaber_id=? AND art IN ('privat','gewerbe')", (r["inhaber_id"],)).fetchall()
    return [r]


def _betrag(form, r, feld="betrag"):
    """Betrag aus dem Formular; „alles“ nimmt das gesamte positive Guthaben."""
    if form.get("alles"):
        if r["saldo"] <= 0:
            raise geld.Fehler(f'{r["name"]} hat kein Guthaben.')
        return r["saldo"]
    b = geld.betrag_lesen(form.get(feld, ""))
    if not b:
        raise geld.Fehler("Bitte einen gültigen Betrag angeben.")
    return b


def _grund(form, vorgabe):
    return sa._f(form, "grund", 160) or vorgabe


# ---------------------------------------------------------------- Ausführung der Aktionen

def ausfuehren(request, con, k, fall, form):
    """Führt die gewählte Aktion eines Falls aus. Gibt die Rückmeldung zurück; wirft geld.Fehler."""
    art = form.get("aktion", "")
    titel = fall["titel"] if fall else "RP-Ereignis"
    fid = fall["id"] if fall else None
    nachricht = sa._f(form, "mitteilung", 400)
    zweck = lambda t: f"{t} – {titel}"[:200]
    if art == "raub":
        opfer = konto_finden(con, form.get("opfer"))
        if opfer["stelle"] in geld.AUSSEN:
            raise geld.Fehler("Dieses Konto kann nicht beraubt werden.")
        betrag = _betrag(form, opfer)
        if (form.get("ziel") or "").strip():
            ziel = konto_finden(con, form.get("ziel"))
            ziel_txt = kurz(ziel)
        else:
            ziel, ziel_txt = geld.sonder(con, "zentralbank"), "Beute außer Landes (Geld verlässt den Umlauf)"
        bid = geld.buchen(con, opfer["id"], ziel["id"], betrag, ART, zweck("Raub/Diebstahl"), k, bezug=f"RP-{fid or 0}")
        text = f'{mark(betrag)} von {kurz(opfer)} → {ziel_txt}'
        aktion_schreiben(con, k, fid, art, text, bid)
        benachrichtigen(request, opfer, nachricht)
        return "Raub gebucht: " + text
    if art in ("einziehen", "strafe"):
        r = konto_finden(con, form.get("konto"))
        if r["stelle"] in geld.AUSSEN:
            raise geld.Fehler("Dieses Konto kann nicht belastet werden.")
        betrag = _betrag(form, r)
        if form.get("ziel_konto", "").strip():
            ziel = konto_finden(con, form.get("ziel_konto"))
        else:
            ziel = geld.sonder(con, "reichskasse")
        grund = _grund(form, "Beschlagnahme" if art == "einziehen" else "Geldstrafe")
        bid = geld.buchen(con, r["id"], ziel["id"], betrag, ART, zweck(grund), k, bezug=f"RP-{fid or 0}", minus=bool(form.get("minus")))
        text = f'{AKTIONEN[art]}: {mark(betrag)} von {kurz(r)} → {kurz(ziel)} ({grund})'
        aktion_schreiben(con, k, fid, art, text, bid)
        benachrichtigen(request, r, nachricht)
        return text
    if art == "rueckgabe":
        r = konto_finden(con, form.get("konto"))
        if r["stelle"] in geld.AUSSEN:
            raise geld.Fehler("Dieses Konto kann nicht begünstigt werden.")
        betrag = geld.betrag_lesen(form.get("betrag", ""))
        if not betrag:
            raise geld.Fehler("Bitte einen gültigen Betrag angeben.")
        quelle_txt = form.get("quelle", "reichskasse")
        if quelle_txt == "konto":
            quelle = konto_finden(con, form.get("quelle_konto"))
        else:
            quelle = geld.sonder(con, "zentralbank" if quelle_txt == "zentralbank" else "reichskasse")
        grund = _grund(form, "Rückgabe / Entschädigung")
        bid = geld.buchen(con, quelle["id"], r["id"], betrag, ART, zweck(grund), k, bezug=f"RP-{fid or 0}",
                          minus=quelle["stelle"] in geld.AUSSEN or bool(form.get("minus")))
        text = f'Rückgabe/Entschädigung: {mark(betrag)} von {kurz(quelle)} → {kurz(r)} ({grund})'
        aktion_schreiben(con, k, fid, art, text, bid)
        benachrichtigen(request, r, nachricht)
        return text
    if art in ("sperren", "freigeben"):
        r = konto_finden(con, form.get("konto"))
        if r["stelle"] in geld.AUSSEN:
            raise geld.Fehler("Dieses Konto kann nicht gesperrt werden.")
        ziele = konten_der_person(con, r) if form.get("person") else [r]
        grund = _grund(form, "Ermittlungen der RP-Leitung")
        for x in ziele:
            if art == "sperren":
                con.execute("UPDATE gk_konten SET gesperrt=1, sperrgrund=? WHERE id=?", (grund[:120], x["id"]))
            else:
                con.execute("UPDATE gk_konten SET gesperrt=0, sperrgrund='' WHERE id=?", (x["id"],))
        karte = ""
        if form.get("karte") and r["inhaber_id"]:
            import bankkarte
            if art == "sperren":
                con.execute("UPDATE bk_karten SET status='gesperrt', sperrgrund=? WHERE konto_id=? AND status='aktiv'", (grund[:120], r["inhaber_id"]))
            else:
                con.execute("UPDATE bk_karten SET status='aktiv', sperrgrund='', fehlversuche=0, gesperrt_bis=0 WHERE konto_id=? AND status='gesperrt'",
                            (r["inhaber_id"],))
            karte = " samt Bankkarte"
        text = f'{"Gesperrt" if art == "sperren" else "Freigegeben"}{karte}: ' + ", ".join(kurz(x) for x in ziele) + (f" ({grund})" if art == "sperren" else "")
        aktion_schreiben(con, k, fid, art, text)
        benachrichtigen(request, r, nachricht)
        return text
    if art == "storno":
        if not str(form.get("buchung", "")).strip().lstrip("#").isdigit():
            raise geld.Fehler("Bitte die Nummer der Buchung angeben.")
        b = con.execute("SELECT * FROM gk_buchungen WHERE id=?", (int(str(form["buchung"]).strip().lstrip("#")),)).fetchone()
        if not b:
            raise geld.Fehler("Buchung nicht gefunden.")
        if con.execute("SELECT 1 FROM rp_aktionen WHERE art='storno' AND text LIKE ?", (f"Storno der Buchung #{b['id']}:%",)).fetchone():
            raise geld.Fehler("Diese Buchung wurde bereits storniert.")
        grund = _grund(form, "Storno")
        bid = geld.buchen(con, b["an"], b["von"], b["betrag"], ART, zweck(f"Storno Buchung #{b['id']}: {grund}"), k, bezug=f"RP-{fid or 0}", minus=True)
        namen = lambda i: kurz(geld.konto(con, i)) if i else "außerhalb"
        text = f'Storno der Buchung #{b["id"]}: {mark(b["betrag"])} zurück von {namen(b["an"])} an {namen(b["von"])} ({grund})'
        aktion_schreiben(con, k, fid, art, text, bid)
        for i in (b["von"], b["an"]):
            if i:
                benachrichtigen(request, geld.konto(con, i), nachricht)
        return text
    if art == "notiz":
        text = sa._f(form, "text", 500)
        if not text:
            raise geld.Fehler("Bitte eine Notiz eingeben.")
        aktion_schreiben(con, k, fid, art, text)
        return "Notiz gespeichert."
    raise geld.Fehler("Unbekannte Aktion.")


# ---------------------------------------------------------------- Seiten

def _kopf(request, titel, icon, zusatz=""):
    return f'<h1>{amt.ic(icon)} {esc(titel)}</h1>{amt.meldung(request)}{zusatz}'


def _aktionsliste(con, fall_id=None, limit=100):
    wo, arg = ("WHERE fall_id=?", (fall_id,)) if fall_id else ("", ())
    rows = con.execute(f"SELECT * FROM rp_aktionen {wo} ORDER BY id DESC LIMIT {int(limit)}", arg).fetchall()
    out = []
    for a in rows:
        b = f' <span class="az">· Buchung #{a["buchung_id"]}</span>' if a["buchung_id"] else ""
        fall = f'<a href="{PFAD}fall/{a["fall_id"]}/">Fall {a["fall_id"]}</a>' if a["fall_id"] and not fall_id else ("–" if not fall_id else None)
        z = [amt._zeit(a["zeit"]), esc(AKTIONEN.get(a["art"], a["art"])), esc(a["text"]) + b, esc(a["autor_name"])]
        if fall_id is None:
            z.insert(1, fall)
        out.append(z)
    return out


@sa.seite("rp")
async def lagebild(request, k):
    con = request.app["db"]
    import notlage
    summe = con.execute("SELECT COALESCE(SUM(saldo),0) s FROM gk_konten").fetchone()["s"]
    gesperrt = con.execute("SELECT COUNT(*) n FROM gk_konten WHERE gesperrt=1").fetchone()["n"]
    minus = con.execute("SELECT COUNT(*) n FROM gk_konten WHERE saldo<0 AND stelle NOT IN ('zentralbank','volkswirtschaft')").fetchone()["n"]
    karten = con.execute("SELECT COUNT(*) n FROM bk_karten WHERE status='gesperrt'").fetchone()["n"]
    offen = con.execute("SELECT COUNT(*) n FROM rp_faelle WHERE status='offen'").fetchone()["n"]
    notlagen = sum(1 for r in con.execute("SELECT * FROM gk_konten WHERE art IN ('teilstaat','verteidigung','behoerde')") if notlage.offener_fall(con, r["id"]))
    kz = [("Geldmenge", mark(geld.geldmenge(con))), ("Summenprobe (alle Salden)", "stimmig" if summe == 0 else mark(summe)),
          ("Offene Fälle", str(offen)), ("Gesperrte Konten", str(gesperrt)), ("Gesperrte Bankkarten", str(karten)),
          ("Kassen im Minus", str(minus)), ("Haushaltsnotlagen", str(notlagen))]
    seit = int(time.time()) - 7 * 86400
    gross = con.execute("SELECT * FROM gk_buchungen WHERE art='ueberweisung' AND zeit>=? ORDER BY betrag DESC LIMIT 8", (seit,)).fetchall()

    def nm(i):
        r = geld.konto(con, i) if i else None
        return f'<a href="{PFAD}konto/{r["id"]}/">{esc(r["name"])}</a>' if r else "–"
    gz = [(amt._zeit(b["zeit"]), f'#{b["id"]}', nm(b["von"]), nm(b["an"]), esc(b["zweck"]), f'<span class="sa-betrag">{mark(b["betrag"])}</span>') for b in gross]
    neu = con.execute("SELECT * FROM gk_konten WHERE art IN ('privat','gewerbe') AND eroeffnet>=? ORDER BY id DESC LIMIT 8", (seit,)).fetchall()
    nz = [(amt._zeit(r["eroeffnet"]), f'<a href="{PFAD}konto/{r["id"]}/">{esc(r["name"])}</a>', esc(geld.art_name(r)), mark(r["saldo"])) for r in neu]
    faelle = con.execute("SELECT * FROM rp_faelle WHERE status='offen' ORDER BY id DESC LIMIT 6").fetchall()
    fz = [(f'<a href="{PFAD}fall/{f["id"]}/">{esc(f["titel"])}</a>', amt._zeit(f["erstellt"]), esc(f["autor_name"])) for f in faelle]
    inhalt = (_kopf(request, "RP-Leitung · Lagebild", "layout-dashboard",
                    '<p class="az">Eingriffe der Server- und RP-Leitung in das Geldsystem. Alles wird doppelt gebucht und protokolliert.</p>')
              + f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              + f'<div class="aktionen"><a class="btn" href="{PFAD}faelle/#neu">{amt.ic("folder-open")}Neuen Fall eröffnen</a>'
                f'<a class="btn zweit" href="{PFAD}konten/">{amt.ic("search")}Konto suchen</a></div>'
              + '<h2>Offene Fälle</h2>' + amt.tabelle(["Fall", "Eröffnet", "Von"], fz, "Keine offenen Fälle.")
              + '<h2>Größte Überweisungen der letzten 7 Tage</h2>'
              + amt.tabelle(["Zeit", "Nr.", "Von", "An", "Zweck", "Betrag"], gz, "Keine Überweisungen.")
              + '<h2>Neue Konten (7 Tage)</h2>' + amt.tabelle(["Eröffnet", "Konto", "Art", "Saldo"], nz, "Keine neuen Konten.")
              + '<h2>Letzte Aktionen</h2>' + amt.tabelle(["Zeit", "Fall", "Aktion", "Einzelheiten", "Von"], _aktionsliste(con, None, 8), "Noch keine Aktionen."))
    return sa.ant(request, k, "RP-Leitung", "sa-rp", inhalt)


@sa.seite("rp")
async def faelle(request, k):
    con = request.app["db"]
    alle = request.query.get("alle")
    rows = con.execute("SELECT * FROM rp_faelle " + ("" if alle else "WHERE status='offen' ") + "ORDER BY id DESC LIMIT 200").fetchall()
    zeilen = [(f'<a href="{PFAD}fall/{f["id"]}/">{esc(f["titel"])}</a>', amt.status_marke("offen" if f["status"] == "offen" else "ok",
                                                                                           "Offen" if f["status"] == "offen" else "Abgeschlossen"),
               amt._zeit(f["erstellt"]), esc(f["autor_name"])) for f in rows]
    inhalt = (_kopf(request, "Fälle", "folder-open")
              + amt.tabelle(["Fall", "Stand", "Eröffnet", "Von"], zeilen, "Keine Fälle.")
              + f'<p class="az"><a href="{PFAD}faelle/{"" if alle else "?alle=1"}">{"Nur offene Fälle" if alle else "Auch abgeschlossene Fälle anzeigen"}</a></p>'
              + f'<h2 id="neu">Neuen Fall eröffnen</h2><form class="sa-formular" method="post" action="{PFAD}fall/neu">{amt.csrf_feld(request)}'
                '<div><label for="t">Titel</label><input type="text" id="t" name="titel" required maxlength="120" placeholder="z. B. Überfall auf die Reichsbank"></div>'
                '<div><label for="b">Beschreibung</label><textarea id="b" name="beschreibung" rows="4" maxlength="2000"></textarea></div>'
                f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Fall eröffnen</button></div></form>')
    return sa.ant(request, k, "Fälle", "sa-rp-faelle", inhalt)


async def fall_neu(request):
    k = await anmeldung.konto(request)
    if not ist_rp(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    titel = sa._f(form, "titel", 120)
    if not titel:
        sa.weiter(PFAD + "faelle/", "Bitte einen Titel angeben.", True)
    cur = con.execute("INSERT INTO rp_faelle (titel, beschreibung, erstellt, autor_id, autor_name) VALUES (?,?,?,?,?)",
                      (titel, str(form.get("beschreibung", ""))[:2000].strip(), int(time.time()), k["id"], k["name"]))
    aktion_schreiben(con, k, cur.lastrowid, "eroeffnet", titel)
    con.commit()
    sa.weiter(f"{PFAD}fall/{cur.lastrowid}/", "Fall eröffnet.")


def _formulare(request, con, fid, abgeschlossen):
    c = amt.csrf_feld(request)
    act = f'{PFAD}fall/{fid}/aktion'
    mit = ('<div><label>Mitteilung an den Betroffenen (optional, per DM)</label><input type="text" name="mitteilung" maxlength="400" '
           'placeholder="z. B. Dein Konto wurde wegen eines Vorfalls gesperrt."></div>')

    def box(titel, hilfe, felder, knopf, art, gefahr=False):
        return (f'<details class="sa-auf"><summary>{esc(titel)}</summary><form class="sa-formular" method="post" action="{act}">{c}'
                f'<input type="hidden" name="aktion" value="{art}"><p class="sa-hinweis">{esc(hilfe)}</p>{felder}{mit if art != "notiz" else ""}'
                f'<div class="aktionen"><button class="btn{" zweit gefahr" if gefahr else ""}" type="submit">{esc(knopf)}</button></div></form></details>')
    betrag = '<div><label>Betrag in Kronen</label><input type="text" name="betrag" inputmode="decimal"></div>'
    alles = '<label class="sa-haken"><input type="checkbox" name="alles" value="1"> gesamtes Guthaben</label>'
    grund = lambda v: f'<div><label>Grund / Verwendungszweck</label><input type="text" name="grund" maxlength="160" placeholder="{esc(v)}"></div>'
    minus = '<label class="sa-haken"><input type="checkbox" name="minus" value="1"> Konto darf dabei ins Minus gehen</label>'
    out = [
        box("Raub / Diebstahl buchen", "Geld wechselt gegen den Willen des Opfers den Besitzer. Ohne Täterkonto verlässt die Beute den Umlauf (Zentralbank).",
            konto_feld("r1", "opfer", "Opfer (Konto der Bank, Kasse, Person …)") + konto_feld("r2", "ziel", "Täter (Konto, leer = Beute außer Landes)", pflicht=False)
            + betrag + alles, "Raub buchen", "raub", True),
        box("Beschlagnahme", "Zieht Geld ein – standardmäßig an die Reichskasse, sonst an ein Konto (z. B. Rückgabe an das Opfer).",
            konto_feld("e1", "konto", "Konto, von dem eingezogen wird") + konto_feld("e2", "ziel_konto", "Empfänger (leer = Reichskasse)", pflicht=False)
            + betrag + alles + grund("Beschlagnahme") + minus, "Einziehen", "einziehen", True),
        box("Rückgabe / Entschädigung", "Zahlt Geld auf ein Konto – aus der Reichskasse, per Geldschöpfung oder von einem anderen Konto.",
            konto_feld("g1", "konto", "Empfänger") + betrag
            + '<div><label>Quelle</label><select name="quelle"><option value="reichskasse">Reichskasse</option>'
              '<option value="zentralbank">Zentralbank (Geldschöpfung)</option><option value="konto">Anderes Konto …</option></select></div>'
            + konto_feld("g2", "quelle_konto", "Quellkonto (nur bei „Anderes Konto“)", pflicht=False) + grund("Entschädigung"), "Auszahlen", "rueckgabe"),
        box("Geldstrafe", "Bußgeld zugunsten der Reichskasse (oder eines Kontos).",
            konto_feld("s1", "konto", "Konto des Schuldigen") + konto_feld("s2", "ziel_konto", "Empfänger (leer = Reichskasse)", pflicht=False)
            + betrag + alles + grund("Geldstrafe") + minus, "Strafe buchen", "strafe", True),
        box("Konto sperren", "Gesperrte Konten können keine Überweisungen, Steuern oder Gebühren auslösen; Gutschriften sind weiter möglich.",
            konto_feld("k1", "konto", "Konto") + grund("Ermittlungen der RP-Leitung")
            + '<label class="sa-haken"><input type="checkbox" name="person" value="1" checked> alle Konten der Person (Privat und Gewerbe)</label>'
            + '<label class="sa-haken"><input type="checkbox" name="karte" value="1" checked> Bankkarte mitsperren</label>', "Sperren", "sperren", True),
        box("Konto freigeben", "Hebt die Sperre auf (auf Wunsch samt Bankkarte).", konto_feld("f1", "konto", "Konto")
            + '<label class="sa-haken"><input type="checkbox" name="person" value="1" checked> alle Konten der Person</label>'
            + '<label class="sa-haken"><input type="checkbox" name="karte" value="1" checked> Bankkarte freigeben</label>', "Freigeben", "freigeben"),
        box("Buchung stornieren", "Bucht eine einzelne Buchung vollständig zurück (Nummer siehe Umsätze/Lagebild). Jede Buchung nur einmal.",
            '<div><label>Nummer der Buchung</label><input type="text" name="buchung" required inputmode="numeric" placeholder="z. B. 1234"></div>'
            + grund("Storno"), "Stornieren", "storno", True),
        box("Notiz", "Hält etwas im Verlauf des Falls fest.", '<div><label>Text</label><textarea name="text" rows="3" maxlength="500" required></textarea></div>',
            "Speichern", "notiz"),
    ]
    return "".join(out)


@sa.seite("rp")
async def fall(request, k):
    con = request.app["db"]
    i = request.match_info["id"]
    f = con.execute("SELECT * FROM rp_faelle WHERE id=?", (int(i),)).fetchone() if i.isdigit() else None
    if not f:
        raise web.HTTPNotFound(text="Fall nicht gefunden.")
    offen = f["status"] == "offen"
    inhalt = (_kopf(request, f["titel"], "folder-open", f'<p class="az"><a href="{PFAD}faelle/">← Alle Fälle</a></p>')
              + amt.daten_tabelle([("Stand", amt.status_marke("offen" if offen else "ok", "Offen" if offen else "Abgeschlossen")),
                                   ("Eröffnet", f'{amt._zeit(f["erstellt"])} von {esc(f["autor_name"])}'),
                                   ("Beschreibung", esc(f["beschreibung"]).replace("\n", "<br>") or "–")])
              + f'<h2>Maßnahmen</h2>{konto_liste(con)}{_formulare(request, con, f["id"], not offen)}'
              + f'<form method="post" action="{PFAD}fall/{f["id"]}/status" style="margin-top:14px">{amt.csrf_feld(request)}'
                f'<button class="btn zweit" type="submit">{amt.ic("check")}{"Fall abschließen" if offen else "Fall wieder öffnen"}</button></form>'
              + '<h2>Verlauf</h2>' + amt.tabelle(["Zeit", "Aktion", "Einzelheiten", "Von"], _aktionsliste(con, f["id"]), "Noch kein Verlauf."))
    return sa.ant(request, k, f["titel"], "sa-rp-faelle", inhalt)


async def _post(request):
    k = await anmeldung.konto(request)
    if not ist_rp(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    i = request.match_info.get("id", "")
    f = con.execute("SELECT * FROM rp_faelle WHERE id=?", (int(i),)).fetchone() if i.isdigit() else None
    if i and not f:
        raise web.HTTPNotFound()
    return k, form, con, f


async def fall_aktion(request):
    k, form, con, f = await _post(request)
    pfad = f"{PFAD}fall/{f['id']}/"
    try:
        text = ausfuehren(request, con, k, f, form)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(pfad, str(e), True)
    sa.weiter(pfad, text[:300])


async def fall_status(request):
    k, form, con, f = await _post(request)
    neu = "erledigt" if f["status"] == "offen" else "offen"
    con.execute("UPDATE rp_faelle SET status=?, abgeschlossen=? WHERE id=?", (neu, int(time.time()) if neu == "erledigt" else None, f["id"]))
    aktion_schreiben(con, k, f["id"], "status", "Fall abgeschlossen" if neu == "erledigt" else "Fall wieder geöffnet")
    con.commit()
    sa.weiter(f"{PFAD}fall/{f['id']}/", "Fall abgeschlossen." if neu == "erledigt" else "Fall wieder geöffnet.")


@sa.seite("rp")
async def konten(request, k):
    con = request.app["db"]
    q = " ".join(request.query.get("q", "").split())
    zeilen = []
    if q:
        n = geld.nummer_gueltig(q)
        rows = con.execute("SELECT * FROM gk_konten WHERE nummer=? OR inhaber_id=? OR lower(name) LIKE lower(?) OR lower(stelle)=lower(?) ORDER BY art, name LIMIT 60",
                           (n or "", q, f"%{q}%", q)).fetchall()
        for r in rows:
            zeilen.append((f'<a href="{PFAD}konto/{r["id"]}/">{esc(r["name"])}</a>', esc(geld.art_name(r)), f'<span class="sa-nr">{nummer_anzeige(r["nummer"])}</span>',
                           sa.betrag_html(r["saldo"], False), amt.status_marke("nein", "Gesperrt") if r["gesperrt"] else amt.status_marke("ok", "Aktiv")))
    inhalt = (_kopf(request, "Konten & Personen", "search")
              + f'<form class="sa-leiste" method="get" action="{PFAD}konten/"><div><label for="q">Name, Kontonummer oder Discord-ID</label>'
                f'<input type="text" id="q" name="q" value="{esc(q)}" autofocus></div><button class="btn" type="submit">{amt.ic("search")}Suchen</button></form>'
              + (amt.tabelle(["Konto", "Art", "Nummer", "Saldo", "Stand"], zeilen, "Kein Konto gefunden.") if q else ""))
    return sa.ant(request, k, "Konten & Personen", "sa-rp-konten", inhalt)


@sa.seite("rp")
async def konto(request, k):
    con = request.app["db"]
    i = request.match_info["id"]
    r = geld.konto(con, int(i)) if i.isdigit() else None
    if not r:
        raise web.HTTPNotFound(text="Konto nicht gefunden.")
    karte = con.execute("SELECT * FROM bk_karten WHERE konto_id=? ORDER BY id DESC LIMIT 1", (r["inhaber_id"],)).fetchone() if r["inhaber_id"] else None
    info = [("Kontoinhaber", esc(r["name"])), ("Kontonummer", f'<span class="sa-nr">{nummer_anzeige(r["nummer"])}</span>'), ("Kontoart", esc(geld.art_name(r))),
            ("Saldo", sa.betrag_html(r["saldo"], False)),
            ("Stand", amt.status_marke("nein", "Gesperrt: " + (r["sperrgrund"] or "ohne Angabe")) if r["gesperrt"] else amt.status_marke("ok", "Aktiv"))]
    if r["inhaber_id"]:
        info.insert(1, ("Discord-ID", esc(r["inhaber_id"])))
        info.append(("Bankkarte", esc({"aktiv": "aktiv", "gesperrt": "gesperrt", "ersetzt": "ersetzt"}.get(karte["status"], karte["status"]) + f' · …{karte["nummer"][-4:]}')
                     if karte else "keine"))
    offen = con.execute("SELECT id, titel FROM rp_faelle WHERE status='offen' ORDER BY id DESC LIMIT 30").fetchall()
    opts = "".join(f'<option value="{f["id"]}">{esc(f["titel"])}</option>' for f in offen)
    if offen:
        # Schnellzugriff: Aktion im Rahmen eines offenen Falls
        schnell = (f'<h2>Maßnahme im Rahmen eines Falls</h2><form class="sa-leiste" method="get" action="{PFAD}konto/{r["id"]}/fall">'
                   f'<div><label for="ff">Fall</label><select id="ff" name="fall">{opts}</select></div>'
                   f'<button class="btn zweit" type="submit">{amt.ic("folder-open")}Fall öffnen</button></form>')
    else:
        schnell = f'<p class="az"><a href="{PFAD}faelle/#neu">Fall eröffnen</a>, um Maßnahmen zu buchen.</p>'
    bs = sa.umsaetze(con, r["id"], 100)
    inhalt = (_kopf(request, r["name"], "search", f'<p class="az"><a href="{PFAD}konten/">← Suche</a></p>') + amt.daten_tabelle(info) + schnell
              + '<h2>Umsätze</h2>' + amt.tabelle(["Nr."] + sa.UMSATZ_KOPF, [(f'#{b["id"]}',) + z for b, z in zip(bs, sa.umsatz_zeilen(con, r["id"], bs, False))], "Keine Umsätze."))
    return sa.ant(request, k, r["name"], "sa-rp-konten", inhalt)


async def konto_zu_fall(request):
    k = await anmeldung.konto(request)
    if not ist_rp(k):
        raise web.HTTPForbidden()
    f = request.query.get("fall", "")
    raise web.HTTPSeeOther(f"{PFAD}fall/{int(f)}/" if f.isdigit() else PFAD + "faelle/")


@sa.seite("rp")
async def protokoll(request, k):
    con = request.app["db"]
    inhalt = (_kopf(request, "RP-Protokoll", "scroll-text", '<p class="az">Alle Eingriffe der RP-Leitung, neueste zuerst.</p>')
              + amt.tabelle(["Zeit", "Fall", "Aktion", "Einzelheiten", "Von"], _aktionsliste(con, None, 300), "Noch keine Aktionen."))
    return sa.ant(request, k, "RP-Protokoll", "sa-rp-protokoll", inhalt)


def registrieren(app):
    einrichten(app["db"])
    r = app.router
    r.add_get(PFAD, lagebild)
    r.add_get(PFAD + "faelle/", faelle)
    r.add_post(PFAD + "fall/neu", fall_neu)
    r.add_get(PFAD + "fall/{id}/", fall)
    r.add_post(PFAD + "fall/{id}/aktion", fall_aktion)
    r.add_post(PFAD + "fall/{id}/status", fall_status)
    r.add_get(PFAD + "konten/", konten)
    r.add_get(PFAD + "konto/{id}/", konto)
    r.add_get(PFAD + "konto/{id}/fall", konto_zu_fall)
    r.add_get(PFAD + "protokoll/", protokoll)
