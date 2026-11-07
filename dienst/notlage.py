"""Haushaltsnotlage: Folgen, wenn eine Staats-, Verteidigungs- oder Behördenkasse ins Minus rutscht (/schatzamt/notlagen/, staatlich).

Überwacht werden Kassen der Kontoarten teilstaat (Staatskasse), verteidigung (Reichsverteidigungs- und Verteidigungskassen der
Teilstaaten) und behoerde (Behörden, Reichskanzlei). Die Reichskasse selbst ist ausgenommen.

Dispo: Diese Kassen dürfen für Beschaffungen, Zuführungen und Überweisungen (DISPO_ARTEN) bis zu „dispo_monate“ Monatsreferenzen ins Minus
(Staatskasse: Landesanteil des Monats, Verteidigungskasse: Verteidigungsetat des Monats, Behörde: Monatsetat). Alle anderen Zahlungen
brauchen Deckung. Ein Lohnlauf zahlt nur aus gedeckten Zahlstellen (besoldung.lohnlauf_buchen) – Gehälter einer Kasse im Minus werden
einbehalten (bs_rueckstaende) und automatisch nachgezahlt, sobald die Zahlstelle wieder im Plus ist und den Betrag deckt (besoldung.nachzahlen).

Stufen (je offener Fall, nl_faelle; Prüfung stündlich im Hintergrund und über die Seite):
 1  Haushaltsnotlage: Meldung, Markierung, keine Ausgaben mehr (auch kein Dispo), Gehälter dieser Zahlstelle werden einbehalten
    und nachgezahlt, sobald die Kasse wieder im Plus ist.
 2  Strafzinsen: je Kalendermonat Leitzins + „aufschlag“ Punkte p. a. auf das Minus an die Reichskasse.
 3  nach „ausgleich_tage“ Tagen (oder Minus > 1 Monatsreferenz): Teilstaat: Zwangsausgleich aus eigenen Mitteln (Verteidigungskasse:
    zuerst Staatskasse, dann Goldreserven des Teilstaats zum Ankaufskurs der Zentralbank) und Reichsabgabe +„abgabe_plus“ Punkte;
    Behörde/Reichsverteidigung: das Reich muss entscheiden (Meldung an den Kanzler).
 4  nach „zwang_tage“ Tagen: Zwangsverwaltung – Landesherr/Generalstab/Leitung verlieren die Verfügung, Kanzler und Schatzamt verwalten.
Das Reich zahlt nicht für das Minus eines Teilstaats: Reichskasse und Zentralbank buchen nichts auf Konten im Minus (hilfe_pruefen).
Der Fall endet, sobald die Kasse wieder im Plus ist. Tabellen: nl_faelle, nl_ereignisse.
"""
import asyncio
import json
import logging
import math
import time
from datetime import datetime

from aiohttp import web

import amt
import anmeldung
import bereiche
import geld
import schatzamt as sa
from geld import mark

esc = amt.esc
PFAD = sa.PFAD + "notlagen/"
log = logging.getLogger("notlage")
SYSTEM = {"id": "", "name": "Kaiserliches Schatz- und Währungsamt (automatisch)"}
UEBERWACHT = ("teilstaat", "verteidigung", "behoerde")
DISPO_ARTEN = ("ruestung", "verteidigungsetat", "ueberweisung")
HILFE_ARTEN = ("korrektur", "zuweisung", "geldschoepfung", "ueberweisung")
STUFEN = {1: "Haushaltsnotlage", 2: "Strafzinsen", 3: "Zwangsausgleich / Reichsaufsicht", 4: "Zwangsverwaltung"}

geld.VORGABEN.setdefault("notlage", {"dispo_monate": 1, "aufschlag": 5, "ausgleich_tage": 30, "zwang_tage": 180, "abgabe_plus": 10, "automatisch": True})
geld.BUCHUNGSART.update({"strafzins": "Strafzinsen (Haushaltsnotlage)", "zwangsausgleich": "Zwangsausgleich (Haushaltsnotlage)"})
amt.ICONS.setdefault("triangle-alert", '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>')

SCHEMA = """
CREATE TABLE IF NOT EXISTS nl_faelle (id INTEGER PRIMARY KEY AUTOINCREMENT, konto_id INTEGER NOT NULL, stelle TEXT NOT NULL, name TEXT NOT NULL,
    seit INTEGER NOT NULL, ende INTEGER, stufe INTEGER NOT NULL DEFAULT 1, minus_max INTEGER NOT NULL DEFAULT 0, zinsen INTEGER NOT NULL DEFAULT 0,
    ausgleich INTEGER NOT NULL DEFAULT 0, gold_kg REAL NOT NULL DEFAULT 0, zwang INTEGER NOT NULL DEFAULT 0, zwang_seit INTEGER,
    letzte_zins TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS nl_faelle_k ON nl_faelle (konto_id, ende);
CREATE TABLE IF NOT EXISTS nl_ereignisse (id INTEGER PRIMARY KEY AUTOINCREMENT, fall INTEGER NOT NULL, zeit INTEGER NOT NULL, art TEXT NOT NULL, text TEXT NOT NULL);
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def _leitzins(con):
    return float(str(geld.einstellung(con, "leitzins")).replace(",", "."))


def einstellungen(con):
    return dict(geld.VORGABEN["notlage"], **geld.einstellung(con, "notlage"))


# ---------------------------------------------------------------- Zustand

def offener_fall(con, konto_id):
    return con.execute("SELECT * FROM nl_faelle WHERE konto_id=? AND ende IS NULL", (konto_id,)).fetchone()


def offene(con):
    """{Konto-ID: offener Fall}."""
    return {f["konto_id"]: f for f in con.execute("SELECT * FROM nl_faelle WHERE ende IS NULL")}


def zwang(con, stelle):
    """Steht die Kasse unter Zwangsverwaltung?"""
    return bool(con.execute("SELECT 1 FROM nl_faelle WHERE stelle=? AND ende IS NULL AND zwang=1", (stelle,)).fetchone())


def verfuegung_gesperrt(con, k, stelle):
    """Zwangsverwaltung: nur Kanzler, Kaiser und Schatzamt-Leitung verfügen noch über die Kasse."""
    if not zwang(con, stelle):
        return False
    return not (bereiche._alle(k) or amt.ROLLE_KANZLER in k["rollen"] or geld.ist_leitung(k))


def zuschlaege(con):
    """{Teilstaat-ID: Punkte Reichsabgabe-Zuschlag} für Teilstaaten in Stufe ≥ 3 (Staats- oder Verteidigungskasse)."""
    plus = float(einstellungen(con)["abgabe_plus"])
    out = {}
    for f in con.execute("SELECT stelle FROM nl_faelle WHERE ende IS NULL AND stufe>=3 AND (stelle LIKE 'ts-%' OR stelle LIKE 'vt-%')"):
        out[f["stelle"][3:]] = plus
    return out


def monatsreferenz(con, r, liste=None):
    """Monatliche Bezugsgröße der Kasse (Heller) für Dispo und Eskalation."""
    import aufkommen
    import etat
    st = r["stelle"]
    if r["art"] == "behoerde":
        return etat.etats(con).get(st, 0)
    liste = liste if liste is not None else aufkommen.berechnen(con)
    if st == "verteidigung":
        return sum(x["vert_reich"] for x in liste)
    for x in liste:
        if x["staat"] == st[3:]:
            return x["land"] if st.startswith("ts-") else x["vert_land"]
    return 0


def dispo_limit(con, r, liste=None):
    return int(monatsreferenz(con, r, liste) * float(einstellungen(con)["dispo_monate"]))


def dispo_erlaubt(con, kv, betrag, art):
    """Darf die Zahlung die Kasse in den Dispo führen? Nur Ausgaben aus DISPO_ARTEN, nur aus einer Kasse im Plus."""
    if art not in DISPO_ARTEN or kv["art"] not in UEBERWACHT or kv["saldo"] < 0:
        return False
    return kv["saldo"] - betrag >= -dispo_limit(con, kv)


def fehlertext(kv):
    if kv["art"] in UEBERWACHT and kv["saldo"] < 0:
        return (f'Haushaltsnotlage: {kv["name"]} ist im Minus ({mark(kv["saldo"])}) – bis zum Ausgleich sind keine Ausgaben möglich.')
    return f'Keine ausreichende Deckung auf {kv["name"]} (verfügbar {mark(kv["saldo"])}).'


def hilfe_pruefen(con, kv, ka, art):
    """Das Reich zahlt nicht für das Minus eines Teilstaats: keine Hilfsbuchungen von Reichskasse/Zentralbank auf Konten im Minus."""
    if kv and ka and kv["stelle"] in ("reichskasse", "zentralbank") and ka["art"] in ("teilstaat", "verteidigung") and ka["stelle"] != "verteidigung" \
            and art in HILFE_ARTEN and (ka["saldo"] < 0 or offener_fall(con, ka["id"])):
        raise geld.Fehler(f'Das Reich zahlt nicht für das Minus eines Teilstaats: {ka["name"]} gleicht es selbst aus (Einnahmen, Goldreserven).')


def banner(con, r):
    """Warnhinweis (HTML) für eine Kasse in der Haushaltsnotlage, sonst ''."""
    f = offener_fall(con, r["id"]) if r else None
    if not f:
        return ""
    tage = int((time.time() - f["seit"]) // 86400)
    return (f'<div class="warnung">{amt.ic("triangle-alert")} <b>Haushaltsnotlage</b> (Stufe {f["stufe"]}: {esc(STUFEN[f["stufe"]])}) seit {tage} Tagen – '
            f'Minus {mark(-r["saldo"])}. Keine Ausgaben, Gehälter aus dieser Kasse werden einbehalten und bei Ausgleich nachgezahlt'
            + (", Zwangsverwaltung durch Kanzler und Schatzamt" if f["zwang"] else "") + f'. <a href="{PFAD}">Einzelheiten</a></div>')


# ---------------------------------------------------------------- Prüfung und Eskalation

def _ereignis(con, fall, jetzt, art, text, ereignisse, konto):
    con.execute("INSERT INTO nl_ereignisse (fall, zeit, art, text) VALUES (?,?,?,?)", (fall, jetzt, art, text[:400]))
    ereignisse.append((konto, text))


def _zins(con, r, f, e, jetzt, ereignisse):
    dt = datetime.fromtimestamp(jetzt)
    periode = dt.strftime("%Y-%m")
    erster = int(datetime(dt.year, dt.month, 1).timestamp())
    if f["letzte_zins"] == periode or f["seit"] >= erster or r["saldo"] >= 0:
        return
    satz = _leitzins(con) + float(e["aufschlag"])
    zins = int(round(-r["saldo"] * satz / 100 / 12))
    if zins <= 0:
        return
    monat = sa._monatsname(periode)
    geld.buchen(con, r["id"], geld.sonder(con, "reichskasse")["id"], zins, "strafzins", f"Strafzinsen Haushaltsnotlage {monat} ({satz:g} % p. a.)",
                SYSTEM, bezug=f'NL-{f["id"]}', minus=True)
    con.execute("UPDATE nl_faelle SET zinsen=zinsen+?, letzte_zins=?, stufe=MAX(stufe,2) WHERE id=?", (zins, periode, f["id"]))
    _ereignis(con, f["id"], jetzt, "zins", f'Strafzinsen {monat}: {mark(zins)} ({satz:g} % p. a. auf das Minus) an die Reichskasse', ereignisse, r)


def _ausgleich(con, r, f, e, jetzt, ereignisse):
    """Teilstaat gleicht das Minus selbst aus: Verteidigungskasse zuerst aus der Staatskasse, dann aus Gold der Staatskasse (Verkauf an die Zentralbank)."""
    import gold
    st = r["stelle"]
    sid = st[3:]
    staatskasse = geld.stellenkonto(con, "ts-" + sid)
    if not staatskasse:
        return
    need = -geld.konto(con, r["id"])["saldo"]
    aus_kasse = erloes = 0
    kg = 0.0
    if st.startswith("vt-"):
        n = min(need, max(0, geld.konto(con, staatskasse["id"])["saldo"]))
        if n > 0:
            geld.buchen(con, staatskasse["id"], r["id"], n, "zwangsausgleich", "Zwangsausgleich aus der Staatskasse", SYSTEM, bezug=f'NL-{f["id"]}')
            aus_kasse, need = n, need - n
    if need > 0:
        bestand = gold.bestand(con, "ts-" + sid)
        je_kg = gold.wert(con, 1, 1 - float(geld.einstellung(con, "gold")["abschlag"]) / 100)
        if bestand > 0 and je_kg > 0:
            kg = round(min(bestand, math.ceil(need / je_kg * 1000) / 1000), 3)
            erloes = gold.handeln(con, geld.konto(con, staatskasse["id"]), kg, True, SYSTEM)
            if st.startswith("vt-"):
                n = min(need, max(0, geld.konto(con, staatskasse["id"])["saldo"]))
                if n > 0:
                    geld.buchen(con, staatskasse["id"], r["id"], n, "zwangsausgleich", "Zwangsausgleich aus Goldverkauf", SYSTEM, bezug=f'NL-{f["id"]}')
    if aus_kasse or kg:
        rest = max(0, -geld.konto(con, r["id"])["saldo"])
        con.execute("UPDATE nl_faelle SET ausgleich=ausgleich+?, gold_kg=gold_kg+? WHERE id=?", (aus_kasse + (erloes if not st.startswith("vt-") else min(erloes, need)), kg, f["id"]))
        _ereignis(con, f["id"], jetzt, "ausgleich",
                  "Zwangsausgleich: " + (f"{mark(aus_kasse)} aus der Staatskasse" if aus_kasse else "") + (" und " if aus_kasse and kg else "")
                  + (f"{kg:g} kg Gold verkauft (Erlös {mark(erloes)})" if kg else "") + (f". Restliches Minus {mark(rest)}." if rest else ". Das Minus ist ausgeglichen."),
                  ereignisse, r)
    elif need > 0:
        _ereignis(con, f["id"], jetzt, "ausgleich", f"Zwangsausgleich nicht möglich: weder Mittel in der Staatskasse noch Gold. Minus {mark(need)}.", ereignisse, r)


def _eskalieren(con, r, f, e, jetzt, ereignisse):
    tage = (jetzt - f["seit"]) / 86400
    minus = -r["saldo"]
    if minus > f["minus_max"]:
        con.execute("UPDATE nl_faelle SET minus_max=? WHERE id=?", (minus, f["id"]))
    _zins(con, r, f, e, jetzt, ereignisse)
    f = offener_fall(con, r["id"])
    teilstaat = r["stelle"].startswith(("ts-", "vt-"))
    if f["stufe"] < 3 and (tage >= float(e["ausgleich_tage"]) or minus > monatsreferenz(con, r)):
        con.execute("UPDATE nl_faelle SET stufe=3 WHERE id=?", (f["id"],))
        _ereignis(con, f["id"], jetzt, "stufe",
                  (f'Stufe 3: Zwangsausgleich aus eigenen Mitteln und Reichsabgabe +{float(e["abgabe_plus"]):g} Punkte, solange das Minus besteht.'
                   if teilstaat else 'Stufe 3: Reichsaufsicht – Kanzler und Schatzamt entscheiden über Zuweisung oder Kürzung des Etats.'), ereignisse, r)
        f = offener_fall(con, r["id"])
    if f["stufe"] >= 3 and teilstaat:
        _ausgleich(con, r, f, e, jetzt, ereignisse)
        r2 = geld.konto(con, r["id"])
        if r2["saldo"] >= 0:
            _schliessen(con, r2, offener_fall(con, r["id"]), jetzt, ereignisse)
            return
    if not f["zwang"] and tage >= float(e["zwang_tage"]):
        con.execute("UPDATE nl_faelle SET stufe=4, zwang=1, zwang_seit=? WHERE id=?", (jetzt, f["id"]))
        _ereignis(con, f["id"], jetzt, "zwang", "Stufe 4: Zwangsverwaltung – Landesherr, Generalstab und Behördenleitung verlieren die Verfügung über die Kasse; "
                                                "Kanzler und Schatzamt verwalten sie bis zum Ausgleich.", ereignisse, r)


def _schliessen(con, r, f, jetzt, ereignisse):
    tage = int((jetzt - f["seit"]) // 86400)
    con.execute("UPDATE nl_faelle SET ende=? WHERE id=?", (jetzt, f["id"]))
    _ereignis(con, f["id"], jetzt, "beendet",
              f'Haushaltsnotlage beendet nach {tage} Tagen (Strafzinsen insgesamt {mark(f["zinsen"])}). Die Kasse ist wieder im Plus.', ereignisse, r)
    geld.protokoll(con, SYSTEM, "Haushaltsnotlage beendet", f'{r["name"]} nach {tage} Tagen')


def pruefen(con, jetzt=None):
    """Prüft alle überwachten Kassen: Fälle eröffnen/schließen, eskalieren. Gibt [(Kasse, Meldungstext)] für Benachrichtigungen zurück."""
    jetzt = jetzt or int(time.time())
    e = einstellungen(con)
    ereignisse = []
    for r in con.execute("SELECT * FROM gk_konten WHERE art IN ('teilstaat','verteidigung','behoerde') ORDER BY id").fetchall():
        f = offener_fall(con, r["id"])
        if r["saldo"] >= 0:
            if f:
                _schliessen(con, r, f, jetzt, ereignisse)
            continue
        if not f:
            cur = con.execute("INSERT INTO nl_faelle (konto_id, stelle, name, seit, minus_max) VALUES (?,?,?,?,?)", (r["id"], r["stelle"], r["name"], jetzt, -r["saldo"]))
            f = con.execute("SELECT * FROM nl_faelle WHERE id=?", (cur.lastrowid,)).fetchone()
            _ereignis(con, f["id"], jetzt, "eroeffnet",
                      f'Haushaltsnotlage: {r["name"]} ist im Minus ({mark(r["saldo"])}). Keine Ausgaben mehr, Gehälter aus dieser Kasse werden einbehalten (Nachzahlung bei Ausgleich); '
                      f'ab dem nächsten Monat Strafzinsen. Ausgleich: Einnahmen' + (", Goldreserven." if r["stelle"].startswith(("ts-", "vt-")) else "."), ereignisse, r)
            geld.protokoll(con, SYSTEM, "Haushaltsnotlage eröffnet", f'{r["name"]}: Minus {mark(-r["saldo"])}')
        _eskalieren(con, r, f, e, jetzt, ereignisse)
    con.commit()
    return ereignisse


async def empfaenger(app, con, r):
    """Konto-IDs, die über eine Meldung zur Kasse informiert werden: Landesherr/Generalstab, Behördenleitung, Führungsstab sowie Kanzler und Kaiser."""
    import verteidigung
    ids = set()
    try:
        mitglieder = await app["discord"].mitglieder()
    except Exception:
        return ids
    st = r["stelle"]
    for m in mitglieder:
        k = {"id": m["id"], "name": m["name"], "rollen": m["rollen"], "mitglied": True, "admin": False}
        ok = m["id"] == amt.config.KAISER_ID or amt.ROLLE_KANZLER in m["rollen"]
        if not ok and st.startswith("ts-"):
            ok = r["id"] in {x["id"] for x in geld.regierte_staatskassen(con, k, mit_zwang=True)}
        elif not ok and st.startswith("vt-"):
            ok = verteidigung.darf_geraet(con, k, st[3:], mit_zwang=True)
        elif not ok and st == "verteidigung":
            ok = verteidigung.ist_fuehrungsstab(k)
        elif not ok and r["art"] == "behoerde":
            b = next((b for b in amt.BEHOERDEN if b["schl"] == st), None)
            ok = bool(b and set(b["leitung"]) & set(m["rollen"]))
        if ok:
            ids.add(m["id"])
    return ids


async def melden(app, con, ereignisse):
    for r, text in ereignisse:
        try:
            for kid in await empfaenger(app, con, r):
                await app["discord"].dm(kid, f"⚠ Haushaltsnotlage – {r['name']}\n{text}\n{amt.config.SITE_URL}{PFAD}")
        except Exception:
            log.exception("Meldung zur Haushaltsnotlage fehlgeschlagen")


async def nachzahlungen(app, con):
    """Zahlt einbehaltene Gehälter nach, sobald die Zahlstelle wieder im Plus ist (besoldung.nachzahlen), und benachrichtigt die Empfänger."""
    import besoldung
    nz = besoldung.nachzahlen(con)
    await besoldung._nachzahlung_melden(app, nz)
    return nz


async def automatik(app):
    await asyncio.sleep(90)
    while True:
        try:
            con = app["db"]
            if einstellungen(con).get("automatisch"):
                await melden(app, con, pruefen(con))
                await nachzahlungen(app, con)
        except Exception:
            log.exception("Haushaltsnotlage: Prüfung fehlgeschlagen")
        await asyncio.sleep(3600)


# ---------------------------------------------------------------- Seite

def sichtbare_konten(con, k):
    """None = alle Kassen; sonst Menge der Konto-IDs, die das Konto einsehen darf (eigene Staats-, Verteidigungs- und Behördenkassen)."""
    import verteidigung
    if bereiche._alle(k) or geld.ist_beamter(k):
        return None
    ids = {r["id"] for r in geld.regierte_staatskassen(con, k, mit_zwang=True)}
    ids |= {r["id"] for r in geld.verfuegbare_konten(con, k) if r["art"] == "behoerde"}
    s = verteidigung.sicht(con, k)
    if s["alle"]:
        ids |= {r["id"] for r in con.execute("SELECT id FROM gk_konten WHERE art='verteidigung'")}
    else:
        for sid in s["sids"]:
            v = geld.stellenkonto(con, "vt-" + sid)
            if v:
                ids.add(v["id"])
    return ids


def _naechster_schritt(f, e, jetzt):
    tage = (jetzt - f["seit"]) / 86400
    if f["zwang"]:
        return "Zwangsverwaltung bis zum Ausgleich"
    if f["stufe"] < 3:
        return f'Zwangsausgleich in {max(0, math.ceil(float(e["ausgleich_tage"]) - tage))} Tagen (früher bei Minus über einer Monatsreferenz)'
    return f'Zwangsverwaltung in {max(0, math.ceil(float(e["zwang_tage"]) - tage))} Tagen'


@sa.seite("staat")
async def seite(request, k):
    con = request.app["db"]
    e = einstellungen(con)
    ids = sichtbare_konten(con, k)
    jetzt = int(time.time())
    faelle = [f for f in con.execute("SELECT * FROM nl_faelle WHERE ende IS NULL ORDER BY seit") if ids is None or f["konto_id"] in ids]
    alt = [f for f in con.execute("SELECT * FROM nl_faelle WHERE ende IS NOT NULL ORDER BY ende DESC LIMIT 20") if ids is None or f["konto_id"] in ids]
    zeilen = []
    for f in faelle:
        r = geld.konto(con, f["konto_id"])
        import besoldung
        n_rs, s_rs = besoldung.rueckstand(con, f["stelle"])
        zeilen.append((esc(f["name"]), f'{int((jetzt - f["seit"]) // 86400)} Tage', f'<b class="sa-minus">{geld.mark_kurz(r["saldo"])}</b>',
                       amt.status_marke("nein" if f["stufe"] >= 3 else "warn", f'Stufe {f["stufe"]}: {STUFEN[f["stufe"]]}'), geld.mark_kurz(f["zinsen"]),
                       (f"{geld.mark_kurz(s_rs)} <span class=\"az\">({n_rs})</span>" if n_rs else "–"),
                       (geld.mark_kurz(f["ausgleich"]) + (f' <span class="az">· {f["gold_kg"]:g} kg Gold</span>' if f["gold_kg"] else "")) if f["ausgleich"] else "–",
                       esc(_naechster_schritt(f, e, jetzt))))
    status = (f'<p class="sa-status ok">{amt.ic("check")}Keine Kasse im Minus.</p>' if not faelle else
              f'<p class="sa-status">{amt.ic("triangle-alert")}{len(faelle)} Kasse(n) in der Haushaltsnotlage.</p>')
    kz = [("Kassen in Notlage", str(len(faelle))), ("Minus gesamt", mark(sum(-geld.konto(con, f["konto_id"])["saldo"] for f in faelle))),
          ("Strafzinsen bisher", mark(sum(f["zinsen"] for f in faelle))), ("Zwangsverwaltungen", str(sum(1 for f in faelle if f["zwang"])))]
    leitzins = _leitzins(con)
    erkl = ('<div class="sa-erkl"><b>Was passiert bei einem Minus?</b><ol>'
            f'<li>Kassen von Teilstaaten, Behörden und der Verteidigung dürfen für Beschaffungen und Zuführungen bis zu <b>{float(e["dispo_monate"]):g} Monat(e)</b> '
            'ihrer Einnahmen bzw. ihres Etats überziehen (Dispo). Gehälter werden nur bei Deckung gezahlt.</li>'
            '<li><b>Stufe 1 – Haushaltsnotlage:</b> Meldung an die Verantwortlichen, keine Ausgaben mehr, <b>die Gehälter dieser Kasse werden einbehalten</b>, '
            'auch das Militär einer Verteidigungskasse im Minus wird nicht bezahlt – <b>sobald die Kasse wieder im Plus ist, werden sie nachgezahlt</b>.</li>'
            f'<li><b>Stufe 2 – Strafzinsen:</b> jeden Monat {leitzins + float(e["aufschlag"]):g} % p. a. (Leitzins + {float(e["aufschlag"]):g} Punkte) auf das Minus an die Reichskasse.</li>'
            f'<li><b>Stufe 3</b> nach {e["ausgleich_tage"]} Tagen oder bei Minus über einem Monat: Ein <b>Teilstaat gleicht es selbst aus</b> – die Verteidigungskasse aus '
            'der Staatskasse, danach durch <b>Verkauf seiner Goldreserven</b> – und zahlt '
            f'<b>{float(e["abgabe_plus"]):g} Punkte mehr Reichsabgabe</b>. Das Reich zahlt nicht für ein Minus.</li>'
            f'<li><b>Stufe 4</b> nach {e["zwang_tage"]} Tagen: <b>Zwangsverwaltung</b> – Landesherr, Generalstab und Leitung verlieren die Verfügung, Kanzler und Schatzamt '
            'verwalten die Kasse bis zum Ausgleich.</li></ol></div>')
    # Überziehungsrahmen der sichtbaren Kassen
    import aufkommen
    liste = aufkommen.berechnen(con)
    rahmen = []
    for r in con.execute("SELECT * FROM gk_konten WHERE art IN ('teilstaat','verteidigung','behoerde') ORDER BY art, name"):
        if ids is not None and r["id"] not in ids:
            continue
        limit = dispo_limit(con, r, liste)
        if not limit and r["saldo"] >= 0:
            continue
        genutzt = max(0, -r["saldo"])
        rahmen.append((esc(r["name"]), geld.mark_kurz(r["saldo"]), geld.mark_kurz(limit), geld.mark_kurz(genutzt) if genutzt else "–",
                       amt.status_marke("nein", "Notlage") if r["saldo"] < 0 else amt.status_marke("ok", "im Plus")))
    ereig = con.execute("SELECT e.*, f.name FROM nl_ereignisse e JOIN nl_faelle f ON f.id=e.fall ORDER BY e.id DESC LIMIT 60").fetchall()
    fall_konto = {f["id"]: f["konto_id"] for f in con.execute("SELECT id, konto_id FROM nl_faelle")}
    ereig = [x for x in ereig if ids is None or fall_konto.get(x["fall"]) in ids][:30]
    leitung = geld.ist_leitung(k)
    c = amt.csrf_feld(request)
    feld = lambda i, n, t, v: f'<div><label for="{i}">{t}</label><input type="text" id="{i}" name="{n}" value="{esc(str(v))}"></div>'
    stell = ""
    if leitung:
        stell = (f'<details class="sa-auf"><summary>{amt.ic("pencil")}Sätze ändern und Prüfung auslösen</summary>'
                 f'<form class="sa-formular" method="post" action="{PFAD}saetze">{c}<div class="zeilen">'
                 + feld("d", "dispo_monate", "Dispo (Monate der Einnahmen/des Etats)", e["dispo_monate"]) + feld("a", "aufschlag", "Strafzins-Aufschlag (Punkte)", e["aufschlag"])
                 + feld("t", "ausgleich_tage", "Zwangsausgleich nach (Tagen)", e["ausgleich_tage"]) + feld("z", "zwang_tage", "Zwangsverwaltung nach (Tagen)", e["zwang_tage"])
                 + feld("p", "abgabe_plus", "Reichsabgabe-Zuschlag (Punkte)", e["abgabe_plus"])
                 + f'</div><label><input type="checkbox" name="automatisch" value="1"{" checked" if e.get("automatisch") else ""}> Automatisch stündlich prüfen</label>'
                 f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button></div></form>'
                 f'<form method="post" action="{PFAD}pruefen">{c}<div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("search")}Jetzt prüfen</button></div></form></details>')
    inhalt = (f'<h1>{amt.ic("triangle-alert")} Haushaltsnotlagen</h1>{amt.meldung(request)}'
              '<p class="az">Folgen, wenn eine Staats-, Verteidigungs- oder Behördenkasse ins Minus rutscht.</p>' + status
              + f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>' + erkl
              + ('<h2>Offene Fälle</h2>' + amt.tabelle(["Kasse", "Seit", "Minus", "Stufe", "Strafzinsen", "Lohnrückstand", "Ausgleich", "Nächster Schritt"], zeilen, klasse="sa-haushalt") if zeilen else "")
              + f'<details class="sa-auf"><summary>{amt.ic("wallet")}Überziehungsrahmen ({len(rahmen)} Kassen)</summary>'
              + amt.tabelle(["Kasse", "Saldo", "Dispo", "Überzogen", ""], rahmen, "Keine Kassen.", klasse="sa-haushalt") + '</details>'
              + f'<details class="sa-auf"><summary>{amt.ic("clock")}Verlauf ({len(ereig)} Ereignisse, {len(alt)} beendete Fälle)</summary>'
              + amt.tabelle(["Zeit", "Kasse", "Ereignis"], [(amt._zeit(x["zeit"]), esc(x["name"]), esc(x["text"])) for x in ereig], "Noch keine Ereignisse.") + '</details>' + stell)
    return sa.ant(request, k, "Haushaltsnotlagen", "sa-notlage", inhalt)


async def saetze_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    try:
        w = {n: float(str(form.get(n, "")).replace(",", ".")) for n in ("dispo_monate", "aufschlag", "ausgleich_tage", "zwang_tage", "abgabe_plus")}
        assert 0 <= w["dispo_monate"] <= 12 and 0 <= w["aufschlag"] <= 50 and 1 <= w["ausgleich_tage"] <= 365 and w["ausgleich_tage"] <= w["zwang_tage"] <= 3650 \
            and 0 <= w["abgabe_plus"] <= 50
    except (ValueError, AssertionError):
        sa.weiter(PFAD, "Bitte gültige Werte angeben (Zwangsverwaltung nicht vor dem Zwangsausgleich).", True)
    ganz = lambda x: int(x) if x == int(x) else x
    geld.einstellung_setzen(con, "notlage", {**{n: ganz(v) for n, v in w.items()}, "automatisch": form.get("automatisch") == "1"}, k)
    con.commit()
    sa.weiter(PFAD, "Gespeichert.")


async def pruefen_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    await sa.formular(request)
    con = request.app["db"]
    ereignisse = pruefen(con)
    await melden(request.app, con, ereignisse)
    nz = await nachzahlungen(request.app, con)
    sa.weiter(PFAD, f"Prüfung abgeschlossen: {len(ereignisse)} Ereignis(se)" + (f", {len(nz)} einbehaltene Gehälter nachgezahlt." if nz else "."))


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get(PFAD, seite)
    app.router.add_post(PFAD + "saetze", saetze_post)
    app.router.add_post(PFAD + "pruefen", pruefen_post)

    async def start(app_):
        app_["notlage_aufgabe"] = asyncio.get_event_loop().create_task(automatik(app_))

    async def stopp(app_):
        app_["notlage_aufgabe"].cancel()
    app.on_startup.append(start)
    app.on_cleanup.append(stopp)
