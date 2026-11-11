"""Privatwirtschaft: Privatbesitz (Fahrzeuge, Immobilien, Sonstiges) mit laufenden Kosten.

Spieler können Güter aus einem Katalog (pb_katalog, Richtpreise in €, ÷ Wechselkurs = Kronen) erwerben und besitzen sie als pb_besitz.
Besitz gehört einer Person (Discord-Konto) und steht in einem Teilstaat (Standort / Zulassung).

**Kauf** (Seite /schatzamt/besitz/): vom Privatkonto an die Volkswirtschaft (Händler, Art privatkauf) plus Erwerbsteuer an die Staatskasse des
Standorts (Immobilien: Grunderwerbsteuer, Fahrzeuge: Zulassungsgebühr; Freie Reichsgebiete → Reichskasse). Wie bei Überweisungen ist eine gültige
Bankkarte nötig. **Laufende Kosten** je Monat (Hintergrundaufgabe, pb_laeufe sperrt Wiederholung je Monat, erster Lauf im Monat nach dem Kauf):
Steuer (Kfz-/Grundsteuer, an die Staatskasse des Standorts), Versicherung und Unterhalt (an die Volkswirtschaft); Bemessung = aktueller Wert
(Katalogpreis × Wertentwicklung p. a., mindestens 5 %). **Zahlungsrückstand:** reicht das Privatkonto nicht, wächst der Rückstand (rueckstand,
rueck_steuer, rueck_monate) und der Eigentümer bekommt eine Nachricht; nach `pfaendung_nach` Monaten pfändet der Staat das Gut zum Pfändungswert
(Wert − `pfaendung_abschlag` %), tilgt damit den Rückstand und zahlt einen Rest an den Eigentümer aus. **Verkauf** an den Händler zum Wert abzüglich
`verkaufsabschlag` % – nur wenn der Erlös den Rückstand deckt.
Der Katalog (Preise, Kostensätze, Wertentwicklung, neue Güter) und die Sätze sind unter /schatzamt/amt/besitz/ von der Leitung des Schatzamts
änderbar. Sätze in Einstellung „privatbesitz“ (geld.VORGABEN).
"""
import asyncio
import logging
import time
from datetime import date

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark

log = logging.getLogger("privatbesitz")
esc = amt.esc
PFAD = sa.PFAD

amt.ICONS.setdefault("car", '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"/>'
                     '<circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>')
amt.ICONS.setdefault("key-round", '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"/>'
                                  '<circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>')

SCHEMA = """
CREATE TABLE IF NOT EXISTS pb_katalog (id INTEGER PRIMARY KEY AUTOINCREMENT, schl TEXT NOT NULL UNIQUE, kategorie TEXT NOT NULL, name TEXT NOT NULL,
    beschreibung TEXT NOT NULL DEFAULT '', preis INTEGER NOT NULL, steuer REAL NOT NULL, versicherung REAL NOT NULL, unterhalt REAL NOT NULL,
    wert REAL NOT NULL DEFAULT 0, aktiv INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS pb_besitz (id INTEGER PRIMARY KEY AUTOINCREMENT, inhaber_id TEXT NOT NULL, inhaber_name TEXT NOT NULL, katalog_id INTEGER NOT NULL,
    bezeichnung TEXT NOT NULL DEFAULT '', standort TEXT NOT NULL DEFAULT '', standort_name TEXT NOT NULL DEFAULT '', kaufpreis INTEGER NOT NULL, kauf_zeit INTEGER NOT NULL,
    ab_periode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'aktiv', rueckstand INTEGER NOT NULL DEFAULT 0, rueck_steuer INTEGER NOT NULL DEFAULT 0,
    rueck_monate INTEGER NOT NULL DEFAULT 0, ende_zeit INTEGER, ende_betrag INTEGER);
CREATE INDEX IF NOT EXISTS pb_besitz_inhaber ON pb_besitz (inhaber_id, status);
CREATE TABLE IF NOT EXISTS pb_vorgaenge (id INTEGER PRIMARY KEY AUTOINCREMENT, besitz_id INTEGER NOT NULL, zeit INTEGER NOT NULL, art TEXT NOT NULL,
    betrag INTEGER NOT NULL DEFAULT 0, text TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS pb_laeufe (id INTEGER PRIMARY KEY AUTOINCREMENT, periode TEXT NOT NULL UNIQUE, anzahl INTEGER NOT NULL, summe INTEGER NOT NULL,
    steuer INTEGER NOT NULL, rueckstaende INTEGER NOT NULL, gepfaendet INTEGER NOT NULL, zeit INTEGER NOT NULL, autor_name TEXT NOT NULL);
"""

KATEGORIEN = {"fahrzeug": "Fahrzeuge", "immobilie": "Immobilien", "sonstiges": "Sonstiges"}
ICON = {"fahrzeug": "car", "immobilie": "house", "sonstiges": "key-round"}

# (Kategorie, Schlüssel, Name, Beschreibung, Richtpreis €, Steuer % p. a., Versicherung % p. a., Unterhalt % p. a., Wertentwicklung % p. a.)
KATALOG = [
    ("fahrzeug", "motorrad", "Motorrad", "Straßenmotorrad, 600–900 ccm.", 12000, 0.6, 1.5, 5, -9),
    ("fahrzeug", "kleinwagen", "Kleinwagen", "Fünftürer für Stadt und Land.", 18000, 0.5, 1.4, 5, -11),
    ("fahrzeug", "limousine", "Limousine (Mittelklasse)", "Viertürige Reiselimousine.", 38000, 0.6, 1.5, 4.5, -12),
    ("fahrzeug", "oberklasse", "Limousine (Oberklasse)", "Repräsentationsfahrzeug mit Chauffeurausstattung.", 95000, 0.8, 1.6, 4, -14),
    ("fahrzeug", "gelaendewagen", "Geländewagen", "Allradfahrzeug für Land- und Forstwirtschaft, Jagd und Rettung.", 55000, 0.9, 1.5, 4.5, -11),
    ("fahrzeug", "transporter", "Kleintransporter", "Kastenwagen bis 3,5 t für Handwerk und Handel.", 36000, 0.7, 1.8, 6, -13),
    ("fahrzeug", "lkw", "Lastkraftwagen", "Sattelzugmaschine mit Auflieger, 40 t.", 140000, 1.1, 2.2, 7, -12),
    ("fahrzeug", "traktor", "Traktor", "Ackerschlepper, 150 PS.", 95000, 0.2, 1.0, 4, -6),
    ("fahrzeug", "motorboot", "Motorboot", "Sportboot mit Kajüte, Liegeplatz nicht inbegriffen.", 70000, 0.5, 2.0, 7, -8),
    ("fahrzeug", "segeljacht", "Segeljacht", "Hochseetaugliche Yacht, 12 m.", 260000, 0.5, 2.0, 8, -6),
    ("fahrzeug", "flugzeug", "Leichtflugzeug", "Einmotoriges Sportflugzeug, 4 Sitze.", 320000, 0.8, 3.0, 8, -5),
    ("fahrzeug", "hubschrauber", "Hubschrauber", "Leichter Turbinenhubschrauber.", 1_100_000, 1.0, 3.5, 9, -5),
    ("immobilie", "wohnung", "Eigentumswohnung", "Etagenwohnung, ca. 80 m².", 190_000, 0.35, 0.25, 1.2, 1.5),
    ("immobilie", "reihenhaus", "Reihenhaus", "Reihenmittelhaus mit kleinem Garten.", 320_000, 0.35, 0.3, 1.3, 1.5),
    ("immobilie", "einfamilienhaus", "Einfamilienhaus", "Freistehendes Haus, ca. 150 m², Grundstück 600 m².", 480_000, 0.35, 0.3, 1.3, 1.5),
    ("immobilie", "villa", "Villa", "Repräsentative Stadtvilla mit großem Park.", 1_900_000, 0.4, 0.35, 1.5, 1.8),
    ("immobilie", "bauernhof", "Bauernhof", "Hofstelle mit Wirtschaftsgebäuden und 30 ha Land.", 950_000, 0.3, 0.3, 1.5, 1.2),
    ("immobilie", "ackerland", "Ackerland (10 ha)", "Unbebaute Nutzfläche.", 160_000, 0.25, 0.0, 0.3, 2.5),
    ("immobilie", "laden", "Ladenlokal", "Geschäftsraum in Innenstadtlage.", 620_000, 0.5, 0.3, 1.6, 1.0),
    ("immobilie", "lagerhalle", "Lagerhalle", "Gewerbehalle mit Rampe, 1.200 m².", 850_000, 0.5, 0.3, 1.6, 1.0),
    ("immobilie", "gutshof", "Gutshof", "Herrenhaus mit Nebengebäuden und Park.", 3_200_000, 0.4, 0.4, 1.8, 1.0),
    ("immobilie", "schloss", "Schloss / Burg", "Historischer Adelssitz, denkmalgeschützt.", 7_500_000, 0.4, 0.5, 2.2, 0.5),
    ("sonstiges", "kunst", "Kunstsammlung", "Gemälde und Skulpturen, versichert und klimatisiert gelagert.", 400_000, 0.0, 0.8, 0.6, 3.0),
    ("sonstiges", "schmuck", "Schmuck- und Juwelensammlung", "Edelsteine und Goldschmuck im Tresor.", 250_000, 0.0, 1.0, 0.4, 2.0),
    ("sonstiges", "oldtimer", "Oldtimer-Sammlung", "Drei gepflegte Klassiker mit H-Kennzeichen.", 300_000, 0.3, 1.4, 2.5, 4.0),
    ("sonstiges", "weingut", "Weingut-Beteiligung", "Anteil an Rebfläche und Kellerei.", 600_000, 0.2, 0.6, 3.0, 1.0),
    ("sonstiges", "jagd", "Jagdrevier (Pacht)", "Gepachtetes Revier mit Jagdhütte.", 180_000, 0.3, 0.5, 2.5, 0.0),
]
VOR_ART = {"kauf": "Kauf", "kosten": "Laufende Kosten", "rueckstand": "Zahlungsrückstand", "verkauf": "Verkauf", "pfaendung": "Pfändung", "mahnung": "Mahnung"}
MIN_WERT = 0.05


def einrichten(con):
    con.executescript(SCHEMA)
    for kat, schl, name, text, preis, st, vs, un, we in KATALOG:
        con.execute("INSERT OR IGNORE INTO pb_katalog (schl, kategorie, name, beschreibung, preis, steuer, versicherung, unterhalt, wert) VALUES (?,?,?,?,?,?,?,?,?)",
                    (schl, kat, name, text, preis, st, vs, un, we))
    con.commit()


def cfg(con):
    return geld.einstellung(con, "privatbesitz")


# ---------------------------------------------------------------- Rechnen

def preis_kr(con, kat):
    """Richtpreis in Heller (€ ÷ Wechselkurs)."""
    return int(round(kat["preis"] / geld.wechselkurs(con) * 100))


def alter_monate(b, jetzt=None):
    return max(0.0, ((jetzt or time.time()) - b["kauf_zeit"]) / (30.4375 * 86400))


def wert(con, b, kat):
    """Aktueller Wert in Heller: Kaufpreis × (1 + Wertentwicklung)^Jahre, mindestens 5 % des Kaufpreises."""
    f = max(MIN_WERT, (1 + kat["wert"] / 100) ** (alter_monate(b) / 12))
    return int(round(b["kaufpreis"] * f))


def kosten(con, b, kat):
    """Monatliche Fixkosten in Heller: {'steuer', 'versicherung', 'unterhalt', 'summe'} (Bemessung = aktueller Wert)."""
    w = wert(con, b, kat)
    s, v, u = (int(round(w * kat[x] / 100 / 12)) for x in ("steuer", "versicherung", "unterhalt"))
    return {"steuer": s, "versicherung": v, "unterhalt": u, "summe": s + v + u}


def steuerkasse(con, sid):
    if not sid or geld.ist_reichsgebiet(sid):
        return geld.sonder(con, "reichskasse")
    return geld.stellenkonto(con, "ts-" + sid) or geld.sonder(con, "reichskasse")


def erwerbsatz(con, kat):
    c = cfg(con)
    return float(c["grunderwerbsteuer"] if kat["kategorie"] == "immobilie" else c["zulassung"] if kat["kategorie"] == "fahrzeug" else 0)


def naechste_periode(heute=None):
    h = heute or date.today()
    return f"{h.year + (h.month == 12)}-{(h.month % 12) + 1:02d}"


def standorte(con):
    import karte
    out = []
    for s in karte.aktuell(con)["stand"]["staaten"]:
        reich = geld.ist_reichsgebiet(s)
        out.append((s["id"], s["name"] + (" (Reich)" if reich else "")))
    return sorted(out, key=lambda x: x[1])


def _vorgang(con, bid, art, betrag, text):
    con.execute("INSERT INTO pb_vorgaenge (besitz_id, zeit, art, betrag, text) VALUES (?,?,?,?,?)", (bid, int(time.time()), art, int(betrag), text[:300]))


def titel(b, kat):
    return f'{kat["name"]} „{b["bezeichnung"]}“' if b["bezeichnung"] else kat["name"]


# ---------------------------------------------------------------- Vorgänge

def kaufen(con, k, kat_id, bezeichnung, standort):
    """Erwirbt ein Gut aus dem Katalog für das Privatkonto. Wirft geld.Fehler."""
    c = cfg(con)
    kat = con.execute("SELECT * FROM pb_katalog WHERE id=? AND aktiv=1", (kat_id,)).fetchone()
    if not kat:
        raise geld.Fehler("Dieses Gut ist nicht (mehr) im Angebot.")
    orte = dict(standorte(con))
    if standort not in orte:
        raise geld.Fehler("Bitte einen Standort wählen.")
    import bankkarte
    if not bankkarte.karte_gueltig(con, k["id"]):
        raise geld.Fehler("Ohne gültige Bankkarte sind keine Geldbewegungen möglich. Beantrage eine Karte im Schatzamt-Portal unter „Bankkarte“.")
    if con.execute("SELECT COUNT(*) FROM pb_besitz WHERE inhaber_id=? AND status='aktiv'", (k["id"],)).fetchone()[0] >= int(c["max_je_person"]):
        raise geld.Fehler(f'Du besitzt bereits {c["max_je_person"]} Güter – mehr sind nicht zulässig.')
    p = geld.privatkonto(con, k["id"])
    if p["gesperrt"]:
        raise geld.Fehler("Dein Konto ist gesperrt.")
    preis = preis_kr(con, kat)
    erw = int(round(preis * erwerbsatz(con, kat) / 100))
    if p["saldo"] < preis + erw:
        raise geld.Fehler(f"Dein Guthaben reicht nicht: Kaufpreis {mark(preis)}" + (f" + {'Grunderwerbsteuer' if kat['kategorie'] == 'immobilie' else 'Zulassung'} {mark(erw)}" if erw else "")
                          + f" = {mark(preis + erw)}, verfügbar {mark(p['saldo'])}.")
    bez = " ".join(str(bezeichnung or "").split())[:60]
    cur = con.execute("INSERT INTO pb_besitz (inhaber_id, inhaber_name, katalog_id, bezeichnung, standort, standort_name, kaufpreis, kauf_zeit, ab_periode) VALUES (?,?,?,?,?,?,?,?,?)",
                      (k["id"], geld.anzeigename(con, k["id"], k["name"]), kat["id"], bez, standort, orte[standort], preis, int(time.time()), naechste_periode()))
    bid = cur.lastrowid
    b = con.execute("SELECT * FROM pb_besitz WHERE id=?", (bid,)).fetchone()
    geld.buchen(con, p["id"], geld.sonder(con, "volkswirtschaft")["id"], preis, "privatkauf", f"Kauf {titel(b, kat)}", k, bezug=f"BESITZ-{bid}")
    if erw:
        geld.buchen(con, p["id"], steuerkasse(con, standort)["id"], erw, "erwerbsteuer",
                    f"{'Grunderwerbsteuer' if kat['kategorie'] == 'immobilie' else 'Zulassungsgebühr'} {titel(b, kat)} ({orte[standort]})", k, bezug=f"BESITZ-{bid}")
    _vorgang(con, bid, "kauf", preis + erw, f"Kauf für {mark(preis)}" + (f" zzgl. {mark(erw)} Erwerbsteuer/Gebühr" if erw else "") + f", Standort {orte[standort]}")
    geld.protokoll(con, k, "Besitz erworben", f"{titel(b, kat)} für {mark(preis)}")
    return b, kat, preis, erw


def _tilgen(con, b, k, erloes):
    """Rückstand aus einem Erlös (Volkswirtschaft zahlt) tilgen; gibt den Rest für den Eigentümer zurück (kann negativ sein)."""
    if b["rueck_steuer"] > 0:
        geld.buchen(con, geld.sonder(con, "volkswirtschaft")["id"], steuerkasse(con, b["standort"])["id"], b["rueck_steuer"], "privatsteuer",
                    f"Steuerrückstand BESITZ-{b['id']} aus Erlös", k, bezug=f"BESITZ-{b['id']}", minus=True)
    return erloes - b["rueckstand"]


def verkaufen(con, k, besitz_id):
    b = con.execute("SELECT * FROM pb_besitz WHERE id=? AND inhaber_id=? AND status='aktiv'", (besitz_id, k["id"])).fetchone()
    if not b:
        raise geld.Fehler("Gut nicht gefunden.")
    kat = con.execute("SELECT * FROM pb_katalog WHERE id=?", (b["katalog_id"],)).fetchone()
    erloes = int(round(wert(con, b, kat) * (1 - float(cfg(con)["verkaufsabschlag"]) / 100)))
    if erloes < b["rueckstand"]:
        raise geld.Fehler(f"Der Erlös ({mark(erloes)}) deckt den Rückstand ({mark(b['rueckstand'])}) nicht. Gleiche den Rückstand zuerst über dein Konto aus.")
    p = geld.privatkonto(con, k["id"])
    rest = _tilgen(con, b, k, erloes)
    if rest > 0:
        geld.buchen(con, geld.sonder(con, "volkswirtschaft")["id"], p["id"], rest, "privatverkauf", f"Verkauf {titel(b, kat)}", k, bezug=f"BESITZ-{b['id']}", minus=True)
    con.execute("UPDATE pb_besitz SET status='verkauft', ende_zeit=?, ende_betrag=?, rueckstand=0, rueck_steuer=0 WHERE id=?", (int(time.time()), rest, b["id"]))
    _vorgang(con, b["id"], "verkauf", erloes, f"Verkauf für {mark(erloes)}" + (f", davon {mark(b['rueckstand'])} Rückstand getilgt" if b["rueckstand"] else ""))
    geld.protokoll(con, k, "Besitz verkauft", f"{titel(b, kat)} für {mark(erloes)}")
    return b, kat, erloes, rest


def _pfaenden(con, b, kat, nachrichten):
    c = cfg(con)
    erloes = int(round(wert(con, b, kat) * (1 - float(c["pfaendung_abschlag"]) / 100)))
    rest = _tilgen(con, b, None, erloes)
    p = geld.privatkonto(con, b["inhaber_id"], anlegen=False)
    if rest > 0 and p:
        geld.buchen(con, geld.sonder(con, "volkswirtschaft")["id"], p["id"], rest, "pfaendung", f"Pfändungserlös {titel(b, kat)} nach Abzug des Rückstands", None,
                    bezug=f"BESITZ-{b['id']}", minus=True)
    con.execute("UPDATE pb_besitz SET status='gepfaendet', ende_zeit=?, ende_betrag=?, rueckstand=0, rueck_steuer=0 WHERE id=?", (int(time.time()), max(rest, 0), b["id"]))
    _vorgang(con, b["id"], "pfaendung", erloes, f"Pfändung nach {b['rueck_monate']} Monaten Rückstand: Erlös {mark(erloes)}, Rückstand {mark(b['rueckstand'])}"
                                             + (f", Rest {mark(rest)} an den Eigentümer" if rest > 0 else ", Fehlbetrag abgeschrieben"))
    nachrichten.append((b["inhaber_id"], f"⚖️ **Pfändung:** Dein Gut **{titel(b, kat)}** wurde wegen {b['rueck_monate']} Monaten Zahlungsrückstand vom Staat gepfändet "
                                         f"(Erlös {mark(erloes)}, Rückstand {mark(b['rueckstand'])}"
                                         + (f", Rest {mark(rest)} auf dein Konto)." if rest > 0 else ").")))


def lauf(con, periode, k=None):
    """Bucht die laufenden Kosten aller Güter für `periode` (JJJJ-MM) einmalig. Gibt (Zeile, Nachrichten) zurück, None wenn der Monat schon gebucht ist."""
    if con.execute("SELECT 1 FROM pb_laeufe WHERE periode=?", (periode,)).fetchone():
        return None
    c = cfg(con)
    vw = geld.sonder(con, "volkswirtschaft")
    nachrichten, anzahl, summe, steuer, rueck, gepf = [], 0, 0, 0, 0, 0
    for b in con.execute("SELECT * FROM pb_besitz WHERE status='aktiv' AND ab_periode<=? ORDER BY id", (periode,)).fetchall():
        kat = con.execute("SELECT * FROM pb_katalog WHERE id=?", (b["katalog_id"],)).fetchone()
        kost = kosten(con, b, kat)
        offen, offen_st = b["rueckstand"] + kost["summe"], b["rueck_steuer"] + kost["steuer"]
        p = geld.privatkonto(con, b["inhaber_id"], anlegen=False)
        anzahl += 1
        try:
            if p and p["saldo"] >= offen:
                if offen_st:
                    geld.buchen(con, p["id"], steuerkasse(con, b["standort"])["id"], offen_st, "privatsteuer",
                                f"{'Grundsteuer' if kat['kategorie'] == 'immobilie' else 'Kfz-/Gutsteuer'} {titel(b, kat)} {periode}", k, bezug=f"BESITZ-{b['id']}")
                if offen - offen_st:
                    geld.buchen(con, p["id"], vw["id"], offen - offen_st, "privatkosten", f"Versicherung und Unterhalt {titel(b, kat)} {periode}", k, bezug=f"BESITZ-{b['id']}")
                con.execute("UPDATE pb_besitz SET rueckstand=0, rueck_steuer=0, rueck_monate=0 WHERE id=?", (b["id"],))
                _vorgang(con, b["id"], "kosten", offen, f"{periode}: Steuer {mark(kost['steuer'])}, Versicherung {mark(kost['versicherung'])}, Unterhalt {mark(kost['unterhalt'])}"
                                                        + (f"; Rückstand {mark(b['rueckstand'])} ausgeglichen" if b["rueckstand"] else ""))
                summe += kost["summe"]
                steuer += kost["steuer"]
            else:
                monate = b["rueck_monate"] + 1
                con.execute("UPDATE pb_besitz SET rueckstand=?, rueck_steuer=?, rueck_monate=? WHERE id=?", (offen, offen_st, monate, b["id"]))
                _vorgang(con, b["id"], "rueckstand", offen, f"{periode}: Kosten {mark(kost['summe'])} nicht bezahlt, Rückstand jetzt {mark(offen)} ({monate}. Monat)")
                rueck += kost["summe"]
                b = con.execute("SELECT * FROM pb_besitz WHERE id=?", (b["id"],)).fetchone()
                if monate >= int(c["pfaendung_nach"]):
                    _pfaenden(con, b, kat, nachrichten)
                    gepf += 1
                else:
                    nachrichten.append((b["inhaber_id"], f"⚠️ **Zahlungsrückstand:** Die laufenden Kosten für **{titel(b, kat)}** ({mark(kost['summe'])}/Monat) konnten für {periode} "
                                                         f"nicht abgebucht werden. Rückstand: {mark(offen)}. Wird er bis zum {int(c['pfaendung_nach'])}. Monat nicht ausgeglichen, "
                                                         f"pfändet der Staat das Gut. Details: {amt.config.SITE_URL}{PFAD}besitz/{b['id']}/"))
        except geld.Fehler as e:
            log.warning("Besitz %s: %s", b["id"], e)
    cur = con.execute("INSERT INTO pb_laeufe (periode, anzahl, summe, steuer, rueckstaende, gepfaendet, zeit, autor_name) VALUES (?,?,?,?,?,?,?,?)",
                      (periode, anzahl, summe, steuer, rueck, gepf, int(time.time()), k["name"] if k else "System"))
    geld.protokoll(con, k, "Besitzkosten-Lauf", f"{periode}: {anzahl} Güter, gebucht {mark(summe)} (davon Steuer {mark(steuer)}), Rückstände {mark(rueck)}, {gepf} gepfändet")
    con.commit()
    return con.execute("SELECT * FROM pb_laeufe WHERE id=?", (cur.lastrowid,)).fetchone(), nachrichten


async def _senden(app, nachrichten):
    for konto_id, text in nachrichten:
        try:
            await app["discord"].dm(konto_id, text)
        except Exception:
            log.exception("Besitz: Nachricht an %s nicht zugestellt", konto_id)


async def automatik(app):
    """Hintergrund: einmal je Kalendermonat die laufenden Kosten buchen (Einstellung „automatisch“)."""
    await asyncio.sleep(40)
    while True:
        try:
            con = app["db"]
            if cfg(con).get("automatisch"):
                erg = lauf(con, date.today().strftime("%Y-%m"))
                if erg:
                    log.info("Besitzkosten %s automatisch gebucht", erg[0]["periode"])
                    await _senden(app, erg[1])
        except Exception:
            log.exception("Besitz: automatischer Lauf fehlgeschlagen")
        await asyncio.sleep(1800)


# ---------------------------------------------------------------- Seiten (Bürger)

CSS = """<style>
.pb-karten{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin:12px 0}
.pb-karte{border:1px solid var(--linie);border-radius:10px;padding:12px 14px;background:#fff}
.pb-karte h3{margin:0 0 4px;font-size:15px;display:flex;gap:8px;align-items:center}
.pb-karte .az{margin:0 0 8px}
.pb-vorschau{margin:8px 0 0;padding:10px 12px;border:1px dashed var(--linie);border-radius:8px;font-size:14px;background:#fafafa}
.pb-vorschau:empty{display:none}
.pb-warn{color:#b3261e;font-weight:600}
</style>"""


def _p(x):
    """Prozentangabe mit Vorzeichen und Dezimalkomma, z. B. „+1,5 % p. a.“."""
    return f"{x:+g}".replace(".", ",") + " % p. a."


def _g(x):
    return f"{x:g}".replace(".", ",")


def _stand(b):
    if b["status"] == "verkauft":
        return amt.status_marke("neutral", "Verkauft")
    if b["status"] == "gepfaendet":
        return amt.status_marke("nein", "Gepfändet")
    if b["rueck_monate"]:
        return amt.status_marke("nein", f"Rückstand ({b['rueck_monate']}. Monat)")
    return amt.status_marke("ok", "Bezahlt")


@sa.seite("mitglied")
async def seite(request, k):
    con = request.app["db"]
    c = cfg(con)
    eigene = con.execute("SELECT b.*, k.name AS kname, k.kategorie, k.steuer, k.versicherung, k.unterhalt, k.wert AS kwert FROM pb_besitz b JOIN pb_katalog k ON k.id=b.katalog_id "
                         "WHERE b.inhaber_id=? AND b.status='aktiv' ORDER BY b.id DESC", (k["id"],)).fetchall()
    zeilen, gesamt_wert, gesamt_kosten, gesamt_rueck = [], 0, 0, 0
    for b in eigene:
        kat = {"steuer": b["steuer"], "versicherung": b["versicherung"], "unterhalt": b["unterhalt"], "wert": b["kwert"]}
        w, ko = wert(con, b, kat), kosten(con, b, kat)
        gesamt_wert += w
        gesamt_kosten += ko["summe"]
        gesamt_rueck += b["rueckstand"]
        zeilen.append((f'<span class="anker" id="b{b["id"]}"><a href="{PFAD}besitz/{b["id"]}/">{amt.ic(ICON[b["kategorie"]])} {esc(b["bezeichnung"] or b["kname"])}</a></span>'
                       + (f'<br><small class="az">{esc(b["kname"])}</small>' if b["bezeichnung"] else ""),
                       esc(KATEGORIEN[b["kategorie"]]), esc(b["standort_name"]), mark(w), mark(ko["summe"]), _stand(b),
                       f'<form method="post" action="{PFAD}besitz/{b["id"]}/verkaufen" onsubmit="return confirm(\'Gut verkaufen? Der Händler zahlt {c["verkaufsabschlag"]} % unter Wert.\')">'
                       f'{amt.csrf_feld(request)}<button class="btn zweit" type="submit">Verkaufen</button></form>'))
    kz = [("Güter", str(len(eigene))), ("Gesamtwert", mark(gesamt_wert)), ("Fixkosten je Monat", mark(gesamt_kosten)), ("Rückstand", mark(gesamt_rueck))]
    p = geld.privatkonto(con, k["id"])
    katalog = con.execute("SELECT * FROM pb_katalog WHERE aktiv=1 ORDER BY CASE kategorie WHEN 'fahrzeug' THEN 0 WHEN 'immobilie' THEN 1 ELSE 2 END, preis").fetchall()
    gruppen = {}
    for kat in katalog:
        pr = preis_kr(con, kat)
        erw = int(round(pr * erwerbsatz(con, kat) / 100))
        mon = kosten(con, {"kaufpreis": pr, "kauf_zeit": time.time()}, kat)["summe"]
        gruppen.setdefault(kat["kategorie"], []).append(
            f'<option value="{kat["id"]}" data-preis="{pr}" data-erw="{erw}" data-monat="{mon}" data-art="{esc(KATEGORIEN[kat["kategorie"]])}">{esc(kat["name"])} – {mark(pr)}</option>')
    opts = "".join(f'<optgroup label="{esc(KATEGORIEN[g])}">{"".join(o)}</optgroup>' for g, o in gruppen.items())
    orte = standorte(con)
    standort_opts = "".join(f'<option value="{esc(s)}">{esc(n)}</option>' for s, n in orte)
    tab_kat = ""
    for g, label in KATEGORIEN.items():
        rows = []
        for kat in (x for x in katalog if x["kategorie"] == g):
            pr = preis_kr(con, kat)
            ko = kosten(con, {"kaufpreis": pr, "kauf_zeit": time.time()}, kat)
            rows.append((f'{esc(kat["name"])}<br><small class="az">{esc(kat["beschreibung"])}</small>', mark(pr), mark(ko["summe"]),
                         _p(kat["wert"])))
        tab_kat += f"<h3>{esc(label)}</h3>" + amt.tabelle(["Gut", "Preis", "Kosten je Monat", "Wertentwicklung"], rows)
    js = ("<script>(function(){var s=document.getElementById('pb-gut'),v=document.getElementById('pb-vorschau');if(!s)return;"
          "function f(n){return (n/100).toLocaleString('de-DE',{minimumFractionDigits:2,maximumFractionDigits:2})+' Kr'}"
          "function u(){var o=s.options[s.selectedIndex];if(!o||!o.dataset.preis){v.textContent='';return}var p=+o.dataset.preis,e=+o.dataset.erw,m=+o.dataset.monat;"
          "v.innerHTML='<b>Kaufpreis:</b> '+f(p)+(e?' · <b>'+(o.dataset.art==='Immobilien'?'Grunderwerbsteuer':'Zulassung')+':</b> '+f(e):'')+' · <b>Gesamt:</b> '+f(p+e)+'<br><b>Laufende Kosten:</b> ca. '+f(m)+' je Monat (Steuer, Versicherung, Unterhalt)'}"
          "s.addEventListener('change',u);u()})()</script>")
    kaufform = (f'<h2>Gut erwerben</h2><form class="sa-formular" method="post" action="{PFAD}besitz/kaufen">{amt.csrf_feld(request)}<div class="zeilen">'
                f'<div><label for="pb-gut">Gut</label><select id="pb-gut" name="gut" required>{opts}</select></div>'
                f'<div><label for="pb-ort">Standort / Zulassung</label><select id="pb-ort" name="standort" required>{standort_opts}</select></div>'
                '<div><label for="pb-bez">Bezeichnung (optional)</label><input type="text" id="pb-bez" name="bezeichnung" maxlength="60" placeholder="z. B. Kennzeichen oder Name"></div></div>'
                f'<div class="pb-vorschau" id="pb-vorschau" aria-live="polite"></div>'
                f'<p class="sa-hinweis">Die Zahlung erfolgt von deinem Privatkonto (verfügbar: {mark(p["saldo"])}). Steuer und Zulassung gehen an die Staatskasse des Standorts, '
                f'der Rest an den Händler. Die laufenden Kosten werden ab dem Folgemonat jeweils zum Monatswechsel von deinem Konto abgebucht.</p>'
                f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Kaufen</button></div></form>{js}')
    inhalt = (f'<h1>{amt.ic("car")} Privatbesitz</h1>{amt.meldung(request)}'
              '<p class="az">Fahrzeuge, Immobilien und weitere Güter im Privatbesitz. Für jedes Gut fallen <b>laufende Kosten</b> an – Kfz- bzw. Grundsteuer, Versicherung und Unterhalt –, '
              f'die zum Monatswechsel von deinem Privatkonto abgebucht werden. Reicht das Guthaben nicht, wächst ein Rückstand; nach {c["pfaendung_nach"]} Monaten pfändet der Staat das Gut.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              + amt.tabelle(["Gut", "Art", "Standort", "Wert", "Kosten je Monat", "Stand", ""], zeilen, "Du besitzt noch nichts.") + kaufform
              + "<h2>Angebot</h2>" + tab_kat)
    return sa.ant(request, k, "Privatbesitz", "sa-besitz", CSS + inhalt)


@sa.seite("mitglied")
async def kaufen_post(request, k):
    con = request.app["db"]
    form = await sa.formular(request)
    try:
        b, kat, preis, erw = kaufen(con, k, int(form.get("gut", 0) or 0), form.get("bezeichnung"), str(form.get("standort", "")))
        con.commit()
    except (geld.Fehler, ValueError) as e:
        con.rollback()
        sa.weiter(f"{PFAD}besitz/", str(e) if isinstance(e, geld.Fehler) else "Bitte ein Gut wählen.", True)
    sa.weiter(f"{PFAD}besitz/{b['id']}/", f"{titel(b, kat)} erworben für {mark(preis)}" + (f" (zzgl. {mark(erw)})." if erw else "."))


@sa.seite("mitglied")
async def verkaufen_post(request, k):
    con = request.app["db"]
    await sa.formular(request)
    try:
        b, kat, erloes, rest = verkaufen(con, k, int(request.match_info["id"]))
        con.commit()
    except (geld.Fehler, ValueError) as e:
        con.rollback()
        sa.weiter(f"{PFAD}besitz/", str(e) if isinstance(e, geld.Fehler) else "Gut nicht gefunden.", True)
    sa.weiter(f"{PFAD}besitz/", f"{titel(b, kat)} verkauft für {mark(erloes)}; {mark(max(rest, 0))} auf dein Konto.")


@sa.seite("mitglied")
async def detail(request, k):
    con = request.app["db"]
    b = con.execute("SELECT * FROM pb_besitz WHERE id=?", (request.match_info["id"],)).fetchone()
    if not b or (b["inhaber_id"] != k["id"] and not geld.ist_beamter(k)):
        raise web.HTTPNotFound(text="Gut nicht gefunden.")
    kat = con.execute("SELECT * FROM pb_katalog WHERE id=?", (b["katalog_id"],)).fetchone()
    aktiv = b["status"] == "aktiv"
    w, ko = wert(con, b, kat), kosten(con, b, kat)
    c = cfg(con)
    paare = [("Gut", esc(kat["name"]) + f' <small class="az">{esc(KATEGORIEN[kat["kategorie"]])}</small>'), ("Bezeichnung", esc(b["bezeichnung"] or "–")),
             ("Eigentümer", esc(b["inhaber_name"])), ("Standort", esc(b["standort_name"])), ("Erworben", amt._zeit(b["kauf_zeit"]) + f" für {mark(b['kaufpreis'])}"), ("Stand", _stand(b))]
    if aktiv:
        paare += [("Aktueller Wert", mark(w) + f' <small class="az">({_p(kat["wert"])})</small>'),
                  ("Steuer je Monat", mark(ko["steuer"])), ("Versicherung je Monat", mark(ko["versicherung"])), ("Unterhalt je Monat", mark(ko["unterhalt"])),
                  ("Fixkosten gesamt", f"<b>{mark(ko['summe'])}</b> je Monat" + (f" · erster Abzug zum Monat {esc(b['ab_periode'])}" if b["ab_periode"] > date.today().strftime("%Y-%m") else ""))]
        if b["rueckstand"]:
            paare.append(("Rückstand", f'<span class="pb-warn">{mark(b["rueckstand"])}</span> – Pfändung im {int(c["pfaendung_nach"])}. Monat des Rückstands (jetzt {b["rueck_monate"]}.)'))
    else:
        paare.append(("Beendet", amt._zeit(b["ende_zeit"] or 0) + (f' – Auszahlung {mark(b["ende_betrag"])}' if b["ende_betrag"] else "")))
    verl = con.execute("SELECT * FROM pb_vorgaenge WHERE besitz_id=? ORDER BY id DESC LIMIT 60", (b["id"],)).fetchall()
    aktion = ""
    if aktiv and b["inhaber_id"] == k["id"]:
        aktion = (f'<form method="post" action="{PFAD}besitz/{b["id"]}/verkaufen" onsubmit="return confirm(\'Gut verkaufen?\')">{amt.csrf_feld(request)}'
                  f'<button class="btn zweit" type="submit">Verkaufen (ca. {mark(int(w * (1 - float(c["verkaufsabschlag"]) / 100)))})</button></form>')
    inhalt = (f'<p><a href="{PFAD}besitz/">{amt.ic("arrow-left")} Privatbesitz</a></p><h1>{amt.ic(ICON[kat["kategorie"]])} {esc(titel(b, kat))}</h1>{amt.meldung(request)}'
              + amt.daten_tabelle(paare) + aktion + "<h2>Verlauf</h2>"
              + amt.tabelle(["Zeit", "Vorgang", "Betrag", "Text"], [(amt._zeit(v["zeit"]), esc(VOR_ART.get(v["art"], v["art"])), mark(v["betrag"]), esc(v["text"])) for v in verl], "Noch keine Vorgänge."))
    return sa.ant(request, k, titel(b, kat), "sa-besitz", CSS + inhalt)


# ---------------------------------------------------------------- Seiten (Verwaltung durch die Leitung)

def _zahl(form, feld, lo, hi):
    x = float(str(form.get(feld, "")).replace(".", "").replace(",", ".") if "," in str(form.get(feld, "")) else str(form.get(feld, "")))
    if not lo <= x <= hi:
        raise ValueError(feld)
    return x


@sa.seite("leitung")
async def verwaltung(request, k):
    con = request.app["db"]
    c = cfg(con)
    kat = con.execute("SELECT * FROM pb_katalog ORDER BY kategorie, preis").fetchall()
    zeilen = []
    for x in kat:
        f = f'f{x["id"]}'
        zeilen.append((f'{esc(x["name"])}<br><small class="az">{esc(KATEGORIEN[x["kategorie"]])}</small>',
                       f'<form method="post" action="{PFAD}amt/besitz/artikel" class="sa-leiste">{amt.csrf_feld(request)}<input type="hidden" name="id" value="{x["id"]}">'
                       f'<input type="text" name="preis" value="{x["preis"]}" size="9" aria-label="Preis in €"> '
                       f'<input type="text" name="steuer" value="{x["steuer"]:g}" size="4" aria-label="Steuer %"> '
                       f'<input type="text" name="versicherung" value="{x["versicherung"]:g}" size="4" aria-label="Versicherung %"> '
                       f'<input type="text" name="unterhalt" value="{x["unterhalt"]:g}" size="4" aria-label="Unterhalt %"> '
                       f'<input type="text" name="wert" value="{x["wert"]:g}" size="4" aria-label="Wertentwicklung %"> '
                       f'<label><input type="checkbox" name="aktiv" value="1"{" checked" if x["aktiv"] else ""}> im Angebot</label> '
                       f'<button class="btn zweit" type="submit" id="{f}">Speichern</button></form>'))
    ein = (f'<form class="sa-formular" method="post" action="{PFAD}amt/besitz/saetze">{amt.csrf_feld(request)}<div class="zeilen">'
           f'<div><label>Grunderwerbsteuer % (Immobilien)</label><input type="text" name="grunderwerbsteuer" value="{c["grunderwerbsteuer"]:g}"></div>'
           f'<div><label>Zulassungsgebühr % (Fahrzeuge)</label><input type="text" name="zulassung" value="{c["zulassung"]:g}"></div>'
           f'<div><label>Verkaufsabschlag % (Händler)</label><input type="text" name="verkaufsabschlag" value="{c["verkaufsabschlag"]:g}"></div>'
           f'<div><label>Pfändung nach … Monaten Rückstand</label><input type="text" name="pfaendung_nach" value="{int(c["pfaendung_nach"])}"></div>'
           f'<div><label>Pfändungsabschlag % auf den Wert</label><input type="text" name="pfaendung_abschlag" value="{c["pfaendung_abschlag"]:g}"></div>'
           f'<div><label>Höchstzahl Güter je Person</label><input type="text" name="max_je_person" value="{int(c["max_je_person"])}"></div>'
           f'<div><label><input type="checkbox" name="automatisch" value="1"{" checked" if c.get("automatisch") else ""}> Kosten automatisch zum Monatswechsel buchen</label></div></div>'
           f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Sätze speichern</button></div></form>')
    neu = (f'<form class="sa-formular" method="post" action="{PFAD}amt/besitz/neu">{amt.csrf_feld(request)}<div class="zeilen">'
           '<div><label>Name</label><input type="text" name="name" required maxlength="60"></div>'
           f'<div><label>Art</label><select name="kategorie">{"".join(f"<option value={g}>{esc(n)}</option>" for g, n in KATEGORIEN.items())}</select></div>'
           '<div><label>Preis (€)</label><input type="text" name="preis" required></div>'
           '<div><label>Steuer % p. a.</label><input type="text" name="steuer" value="0,5"></div><div><label>Versicherung % p. a.</label><input type="text" name="versicherung" value="1"></div>'
           '<div><label>Unterhalt % p. a.</label><input type="text" name="unterhalt" value="2"></div><div><label>Wertentwicklung % p. a.</label><input type="text" name="wert" value="0"></div></div>'
           '<div><label>Beschreibung</label><input type="text" name="beschreibung" maxlength="200"></div>'
           f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Gut anlegen</button></div></form>')
    laeufe = con.execute("SELECT * FROM pb_laeufe ORDER BY id DESC LIMIT 12").fetchall()
    st = con.execute("SELECT COUNT(*) n, SUM(rueckstand) r FROM pb_besitz WHERE status='aktiv'").fetchone()
    periode = date.today().strftime("%Y-%m")
    lauf_form = (f'<form method="post" action="{PFAD}amt/besitz/lauf" onsubmit="return confirm(\'Kosten für {periode} jetzt buchen?\')">{amt.csrf_feld(request)}'
                 f'<button class="btn zweit" type="submit"{" disabled" if con.execute("SELECT 1 FROM pb_laeufe WHERE periode=?", (periode,)).fetchone() else ""}>Kostenlauf {periode} jetzt ausführen</button></form>')
    inhalt = (f'<h1>{amt.ic("car")} Besitzkatalog &amp; Kosten</h1>{amt.meldung(request)}'
              f'<div class="kennzahlen"><div><b>{st["n"]}</b>Güter im Besitz</div><div><b>{mark(st["r"] or 0)}</b>offene Rückstände</div></div>'
              '<p class="az">Preise in €, umgerechnet zum Wechselkurs. Sätze in % p. a. vom aktuellen Wert. Reihenfolge der Felder: Preis · Steuer · Versicherung · Unterhalt · Wertentwicklung.</p>'
              "<h2>Sätze</h2>" + ein + "<h2>Katalog</h2>" + amt.tabelle(["Gut", "Preis und Sätze"], zeilen) + "<h2>Neues Gut</h2>" + neu
              + "<h2>Kostenläufe</h2>" + lauf_form
              + amt.tabelle(["Monat", "Güter", "Gebucht", "davon Steuer", "Rückstände", "Gepfändet", "Zeit"],
                            [(esc(l["periode"]), str(l["anzahl"]), mark(l["summe"]), mark(l["steuer"]), mark(l["rueckstaende"]), str(l["gepfaendet"]), amt._zeit(l["zeit"])) for l in laeufe],
                            "Noch kein Lauf."))
    return sa.ant(request, k, "Besitzkatalog", "sa-amt-besitz", CSS + inhalt)


def _leitung_pruefen(k):
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()


async def artikel_post(request):
    k = await anmeldung.konto(request)
    _leitung_pruefen(k)
    form = await sa.formular(request)
    con = request.app["db"]
    try:
        con.execute("UPDATE pb_katalog SET preis=?, steuer=?, versicherung=?, unterhalt=?, wert=?, aktiv=? WHERE id=?",
                    (int(_zahl(form, "preis", 1, 10 ** 10)), _zahl(form, "steuer", 0, 20), _zahl(form, "versicherung", 0, 20), _zahl(form, "unterhalt", 0, 40),
                     _zahl(form, "wert", -50, 50), 1 if form.get("aktiv") else 0, int(form.get("id", 0))))
        geld.protokoll(con, k, "Besitzkatalog geändert", f"Gut {form.get('id')}")
        con.commit()
    except (ValueError, TypeError):
        sa.weiter(f"{PFAD}amt/besitz/", "Bitte gültige Zahlen angeben.", True)
    sa.weiter(f"{PFAD}amt/besitz/", "Gut gespeichert.")


async def neu_post(request):
    k = await anmeldung.konto(request)
    _leitung_pruefen(k)
    form = await sa.formular(request)
    con = request.app["db"]
    name = sa._f(form, "name", 60)
    try:
        assert name and form.get("kategorie") in KATEGORIEN
        schl = "x" + str(int(time.time()))
        con.execute("INSERT INTO pb_katalog (schl, kategorie, name, beschreibung, preis, steuer, versicherung, unterhalt, wert) VALUES (?,?,?,?,?,?,?,?,?)",
                    (schl, form["kategorie"], name, sa._f(form, "beschreibung", 200), int(_zahl(form, "preis", 1, 10 ** 10)), _zahl(form, "steuer", 0, 20),
                     _zahl(form, "versicherung", 0, 20), _zahl(form, "unterhalt", 0, 40), _zahl(form, "wert", -50, 50)))
        geld.protokoll(con, k, "Besitzkatalog erweitert", name)
        con.commit()
    except (ValueError, TypeError, AssertionError):
        sa.weiter(f"{PFAD}amt/besitz/", "Bitte Name, Art und gültige Zahlen angeben.", True)
    sa.weiter(f"{PFAD}amt/besitz/", f"{name} angelegt.")


async def saetze_post(request):
    k = await anmeldung.konto(request)
    _leitung_pruefen(k)
    form = await sa.formular(request)
    con = request.app["db"]
    try:
        neu = {"grunderwerbsteuer": _zahl(form, "grunderwerbsteuer", 0, 30), "zulassung": _zahl(form, "zulassung", 0, 30), "verkaufsabschlag": _zahl(form, "verkaufsabschlag", 0, 90),
               "pfaendung_nach": int(_zahl(form, "pfaendung_nach", 1, 24)), "pfaendung_abschlag": _zahl(form, "pfaendung_abschlag", 0, 90),
               "max_je_person": int(_zahl(form, "max_je_person", 1, 1000)), "automatisch": bool(form.get("automatisch"))}
    except (ValueError, TypeError):
        sa.weiter(f"{PFAD}amt/besitz/", "Bitte gültige Zahlen angeben.", True)
    geld.einstellung_setzen(con, "privatbesitz", neu, k)
    con.commit()
    sa.weiter(f"{PFAD}amt/besitz/", "Sätze gespeichert.")


async def lauf_post(request):
    k = await anmeldung.konto(request)
    _leitung_pruefen(k)
    await sa.formular(request)
    erg = lauf(request.app["db"], date.today().strftime("%Y-%m"), k)
    if not erg:
        sa.weiter(f"{PFAD}amt/besitz/", "Dieser Monat ist bereits gebucht.", True)
    await _senden(request.app, erg[1])
    sa.weiter(f"{PFAD}amt/besitz/", f"Kostenlauf {erg[0]['periode']}: {erg[0]['anzahl']} Güter, {mark(erg[0]['summe'])} gebucht.")


def tarif_text(con):
    c = cfg(con)
    return (f'Grunderwerbsteuer {_g(c["grunderwerbsteuer"])} % beim Kauf von Immobilien, Zulassungsgebühr {_g(c["zulassung"])} % bei Fahrzeugen; laufend monatlich Kfz-/Grundsteuer, '
            f'Versicherung und Unterhalt je nach Gut (Katalog unter Besitz); Händler kauft mit {_g(c["verkaufsabschlag"])} % Abschlag zurück; Pfändung nach {int(c["pfaendung_nach"])} Monaten Rückstand')


def registrieren(app):
    einrichten(app["db"])
    geld.BUCHUNGSART.update({"privatkauf": "Kauf (Privatbesitz)", "privatverkauf": "Verkauf (Privatbesitz)", "privatkosten": "Versicherung und Unterhalt (Besitz)",
                             "privatsteuer": "Kfz-/Grundsteuer (Besitz)", "erwerbsteuer": "Grunderwerbsteuer / Zulassung"})
    r = app.router
    r.add_get(PFAD + "besitz/", seite)
    r.add_post(PFAD + "besitz/kaufen", kaufen_post)
    r.add_get(PFAD + "besitz/{id:\\d+}/", detail)
    r.add_post(PFAD + "besitz/{id:\\d+}/verkaufen", verkaufen_post)
    r.add_get(PFAD + "amt/besitz/", verwaltung)
    r.add_post(PFAD + "amt/besitz/artikel", artikel_post)
    r.add_post(PFAD + "amt/besitz/neu", neu_post)
    r.add_post(PFAD + "amt/besitz/saetze", saetze_post)
    r.add_post(PFAD + "amt/besitz/lauf", lauf_post)

    async def start(app_):
        app_["besitz_aufgabe"] = asyncio.get_event_loop().create_task(automatik(app_))

    async def stopp(app_):
        app_["besitz_aufgabe"].cancel()
    app.on_startup.append(start)
    app.on_cleanup.append(stopp)
