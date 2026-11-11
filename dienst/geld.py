"""Geldsystem des Reiches – Kern: Konten, Buchungen, Einstellungen, Rechte, Protokoll.

Währung: Krone (Kr), 1 Kr = 100 Heller, intern Heller (INTEGER); Kurs 1 Kr = 1,21 € (Einstellung „wechselkurs“). Kontonummern IBAN-artig „IG“ + 2 Prüfziffern (mod 97) + 4-stellige Kontoart + 8-stellige Nummer.
Kontoarten: privat (je Discord-Konto), gewerbe (genehmigte Gewerbe), behoerde (je amt.BEHOERDEN + Reichskanzlei), teilstaat (je
Teilstaat der Reichskarte), sonder (zentralbank, reichskasse, sozialkasse).
Geldschöpfung: nur über das Konto „zentralbank“, das als einziges ins Minus gehen darf – Geldmenge im Umlauf = −Saldo der Zentralbank.
buchen() ist atomar (kein await zwischen Prüfung und Schreiben; SQLite-Transaktion) und schreibt gk_buchungen + Salden.
Rechte: Schatzamt-Beamte = Rollen der Behörde „schatzamt“ (amt.BEHOERDEN, Rollen folgen) + Kronkanzler/Kaiser (+ Admins OOC);
Leitung = Leitungsrollen + Kronkanzler/Kaiser. Einstellungen (Steuersätze, Tarife, Gebühren …) als JSON in gk_einstellungen mit Vorgaben.
"""
import json
import re
import time
from decimal import Decimal, InvalidOperation

import amt
import bereiche

esc = amt.esc
NAME = "Kaiserliches Schatz- und Währungsamt"
STELLE = ("schatzamt", NAME)
MAX_BETRAG = 10 ** 17   # Heller (1 Billiarde Kronen) – Echtmaßstab: Staatshaushalte in Milliarden
KONTOART = {"privat": ("Privatkonto", 1000), "gewerbe": ("Gewerbekonto", 2000), "behoerde": ("Behördenkonto", 3000),
            "teilstaat": ("Staatskasse", 4000), "verteidigung": ("Verteidigungskasse", 5000), "sonder": ("Sonderkonto", 9000)}
SONDER = {"zentralbank": "Zentralbank des Reiches", "reichskasse": "Reichskasse", "sozialkasse": "Reichsversicherungskasse",
          "volkswirtschaft": "Volkswirtschaft (simulierte Bevölkerung)", "crown_estates": "Crown Estates des Kaisers"}
AUSSEN = ("zentralbank", "volkswirtschaft")   # Gegenkonten außerhalb des Geldumlaufs, dürfen ins Minus
BUCHUNGSART = {"ueberweisung": "Überweisung", "gehalt": "Gehalt", "lohnsteuer": "Lohnsteuer", "sozialabgabe": "Sozialabgabe",
               "steuer": "Steuerzahlung", "gebuehr": "Gebühr", "laenderanteil": "Länderanteil", "umsatzsteuer": "Umsatzsteuer",
               "ueberweisungssteuer": "Überweisungssteuer", "geldschoepfung": "Geldschöpfung", "geldvernichtung": "Geldvernichtung",
               "korrektur": "Korrekturbuchung", "pfaendung": "Pfändung", "startguthaben": "Startguthaben", "erstattung": "Erstattung",
               "zuweisung": "Haushaltszuweisung", "steueraufkommen": "Steueraufkommen der Bevölkerung",
               "umbuchung": "Umbuchung", "kronsteuer": "Kronsteuer", "verteidigungsetat": "Verteidigungsetat", "ruestung": "Rüstungsbeschaffung",
               "instandhaltung": "Instandhaltung (Militärgerät)", "ruestung_erloes": "Erlös aus Ausmusterung", "handel": "Handel"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS gk_konten (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nummer TEXT NOT NULL UNIQUE, art TEXT NOT NULL, name TEXT NOT NULL,
    inhaber_id TEXT NOT NULL DEFAULT '', stelle TEXT NOT NULL DEFAULT '', saldo INTEGER NOT NULL DEFAULT 0,
    gesperrt INTEGER NOT NULL DEFAULT 0, sperrgrund TEXT NOT NULL DEFAULT '', eroeffnet INTEGER NOT NULL, notiz TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS gk_konten_i ON gk_konten (inhaber_id, art);
CREATE INDEX IF NOT EXISTS gk_konten_s ON gk_konten (stelle);
CREATE TABLE IF NOT EXISTS gk_buchungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, von INTEGER, an INTEGER, betrag INTEGER NOT NULL, art TEXT NOT NULL,
    zweck TEXT NOT NULL DEFAULT '', bezug TEXT NOT NULL DEFAULT '', autor_id TEXT NOT NULL DEFAULT '', autor_name TEXT NOT NULL DEFAULT '',
    saldo_von INTEGER, saldo_an INTEGER);
CREATE INDEX IF NOT EXISTS gk_buchungen_v ON gk_buchungen (von, zeit);
CREATE INDEX IF NOT EXISTS gk_buchungen_a ON gk_buchungen (an, zeit);
CREATE TABLE IF NOT EXISTS gk_einstellungen (schl TEXT PRIMARY KEY, wert TEXT NOT NULL, geaendert INTEGER, von TEXT);
CREATE TABLE IF NOT EXISTS gk_protokoll (
    id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, konto_id TEXT NOT NULL, name TEXT NOT NULL, aktion TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gk_gewerbe (
    id INTEGER PRIMARY KEY AUTOINCREMENT, konto INTEGER, inhaber_id TEXT NOT NULL, inhaber_name TEXT NOT NULL, name TEXT NOT NULL,
    branche TEXT NOT NULL, sitz TEXT NOT NULL DEFAULT '', beschreibung TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'beantragt',
    grund TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL, entschieden_von TEXT NOT NULL DEFAULT '', entschieden INTEGER);
"""

# Vorgaben (alle in Heller bzw. Prozent); vom Schatzamt unter „Tarife & Sätze“ änderbar.
VORGABEN = {
    "lohnsteuer": {"stufen": [[100000, 0], [300000, 10], [600000, 20], [None, 30]]},   # Grenzsteuersätze auf das Monatsbrutto
    "sozialabgabe": 5,              # % des Bruttos an die Reichsversicherungskasse
    "kronsteuer": 2,                # % des Bruttos an die Crown Estates des Kaisers (Quellenabzug im Lohnlauf; Monarchen selbst ausgenommen)
    "kronsteuer_bevoelkerung": 0.005,   # Kr je Einwohner und Monat der simulierten Bevölkerung an die Crown Estates (Staatshaushalt)
    "laenderanteil": 25,            # % von Lohn- und Kopfsteuer an die Staatskasse des Wohnsitz-Teilstaats
    "kopfsteuer": 2000,             # je Steuerlauf und Staatsbürger
    "vermoegensteuer": {"satz": 1, "freibetrag": 1000000},
    "gewerbesteuer": {"grund": 5000, "satz": 3},          # Grundbetrag + % der Eingänge im Zeitraum
    "umsatzsteuer": 10,             # % (im Kaufpreis enthalten) bei Zahlungen an Gewerbekonten
    "ueberweisungssteuer": 0,       # % auf private Überweisungen (zahlt der Auftraggeber zusätzlich)
    "saeumnis": 5,                  # % Säumniszuschlag je Mahnstufe
    "frist_tage": 14,               # Zahlungsfrist für Bescheide
    "startguthaben": 0,             # bei Kontoeröffnung aus der Zentralbank
    "leitzins": "2,0",
    "gold": {"preis_kg": 95000, "abschlag": 1},
    "wechselkurs": "1,21",          # € je Krone
    "aufkommen": {"steuerquote": 24, "reichsanteil": 43, "quote_min": 20, "quote_max": 33, "ausgabenquote": 97, "automatisch": True},
    "privatbesitz": {"grunderwerbsteuer": 5, "zulassung": 1, "verkaufsabschlag": 10, "pfaendung_nach": 3, "pfaendung_abschlag": 30, "max_je_person": 60,
                     "automatisch": True},   # Privatbesitz (privatbesitz.py): Erwerbsteuer %, Händlerabschlag %, Pfändung nach n Monaten Rückstand
    "gebuehren": {"reisepass": 5000, "personalausweis": 2500, "dienstpass": 0, "vorlaeufig": 2000, "fremdenpass": 4000,
                  "visum": 3000, "meldebescheinigung": 500, "zeitungsartikel": 1200},
}
GEBUEHR_NAMEN = {"reisepass": "Reisepass", "personalausweis": "Personalausweis", "dienstpass": "Dienstpass",
                 "vorlaeufig": "Vorläufiger Reisepass", "fremdenpass": "Fremdenpass", "visum": "Visum (Sichtvermerk)",
                 "meldebescheinigung": "Meldebescheinigung", "zeitungsartikel": "Zeitungsartikel (Newsflash)"}


class Fehler(Exception):
    """Fachlicher Fehler (Deckung, Sperre …) – Text wird dem Nutzer angezeigt."""


# ---------------------------------------------------------------- Einrichten

def einrichten(con):
    con.executescript(SCHEMA)
    for schl, name in SONDER.items():
        _anlegen(con, "sonder", name, stelle=schl)
    _anlegen(con, "behoerde", "Reichskanzlei", stelle="kanzlei")
    for b in amt.BEHOERDEN:
        _anlegen(con, "behoerde", b["name"], stelle=b["schl"])
    con.commit()


REICHSGEBIETE = {"s2"}   # Freie Reichsgebiete = das Reich selbst (kein Teilstaat): alles läuft über die Reichskasse, keine Staatskasse


def ist_reichsgebiet(s):
    """True für die Freien Reichsgebiete der Reichskarte (Staat-Eintrag als dict oder Teilstaat-ID). Sie sind kein Teilstaat,
    sondern das Reich selbst: keine Staatskasse, keine Reich/Land-Teilung, Einnahmen und Bestände gehören der Reichskasse."""
    import karte
    if isinstance(s, str):
        return s in REICHSGEBIETE
    return s.get("id") in REICHSGEBIETE or s.get("name") == karte.REICHSGEBIETE


def teilstaaten_sichern(con):
    """Staatskassen für alle Teilstaaten der aktuellen Reichskarte (außer den unmittelbar vom Reich verwalteten Gebieten)."""
    import karte
    import landespolizei
    for s in karte.aktuell(con)["stand"]["staaten"]:
        if not ist_reichsgebiet(s):
            _anlegen(con, "teilstaat", "Staatskasse " + landespolizei._kurzname(s["name"]), stelle="ts-" + s["id"])
    con.commit()


def _anlegen(con, art, name, inhaber_id="", stelle=""):
    if stelle:
        r = con.execute("SELECT * FROM gk_konten WHERE stelle=? AND art=?", (stelle, art)).fetchone()
        if r:
            return r
    cur = con.execute("INSERT INTO gk_konten (nummer, art, name, inhaber_id, stelle, eroeffnet) VALUES ('',?,?,?,?,?)",
                      (art, name, inhaber_id, stelle, int(time.time())))
    i = cur.lastrowid
    con.execute("UPDATE gk_konten SET nummer=? WHERE id=?", (kontonummer(KONTOART[art][1], i), i))
    return con.execute("SELECT * FROM gk_konten WHERE id=?", (i,)).fetchone()


# ---------------------------------------------------------------- Beträge, Nummern

def mark(pf, vorzeichen=False, einheit=True):
    pf = int(pf or 0)
    neg = pf < 0
    m, p = divmod(abs(pf), 100)
    t = f"{m:,}".replace(",", ".") + f",{p:02d}" + (" Kr" if einheit else "")
    return ("−" if neg else "+" if vorzeichen and pf > 0 else "") + t


def mark_kurz(pf):
    """Kompakt für Kennzahlen: ab 10.000 Kr ohne Heller, ab 1 Mio. als „2,82 Mio. Kr“."""
    m = int(pf or 0) / 100
    a = abs(m)
    if a >= 1e12:
        zahl, zusatz = f"{m / 1e12:.2f}", " Bio."
    elif a >= 1e9:
        zahl, zusatz = f"{m / 1e9:.2f}", " Mrd."
    elif a >= 1e6:
        zahl, zusatz = f"{m / 1e6:.2f}", " Mio."
    elif a >= 1e4:
        zahl, zusatz = f"{round(m):,}".replace(",", "."), ""
        return ("−" if m < 0 else "") + zahl.lstrip("-") + " Kr"
    else:
        return mark(pf)
    return ("−" if m < 0 else "") + zahl.lstrip("-").replace(".", ",") + zusatz + " Kr"


def wechselkurs(con):
    """€ je Krone (Echtmaßstab)."""
    return float(str(einstellung(con, "wechselkurs")).replace(",", "."))


def betrag_lesen(s, null_erlaubt=False):
    """'1.234,56', '1234.56', '1234' … → Heller (None bei Unsinn oder ≤ 0)."""
    s = re.sub(r"\s|Kronen|Krone|Kr\.?", "", str(s or ""))
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    pf = int((d * 100).to_integral_value())
    return pf if (0 if null_erlaubt else 1) <= pf <= MAX_BETRAG else None


def prozent_lesen(s):
    try:
        d = Decimal(str(s).replace(",", ".").replace("%", "").strip())
    except InvalidOperation:
        return None
    return float(d) if 0 <= d <= 100 else None


def kontonummer(code, i):
    rumpf = f"{code:04d}{i:08d}"
    pruef = 98 - int(rumpf + "1816" + "00") % 97     # I=18, G=16 (wie bei der IBAN)
    return f"IG{pruef:02d}{rumpf}"


def nummer_gueltig(n):
    n = re.sub(r"\s", "", str(n or "")).upper()
    if not re.fullmatch(r"IG\d{14}", n):
        return None
    return n if int(n[4:] + "1816" + n[2:4]) % 97 == 1 else None


def nummer_anzeige(n):
    return " ".join(n[i:i + 4] for i in range(0, len(n), 4))


# ---------------------------------------------------------------- Konten

def konto(con, i):
    return con.execute("SELECT * FROM gk_konten WHERE id=?", (i,)).fetchone()


def sonder(con, schl):
    return con.execute("SELECT * FROM gk_konten WHERE art='sonder' AND stelle=?", (schl,)).fetchone()


def stellenkonto(con, stelle):
    """Konto einer Stelle: 'reichskasse', 'kanzlei', Behörden-Schlüssel, 'ts-<sid>'."""
    r = con.execute("SELECT * FROM gk_konten WHERE stelle=? ORDER BY (art='sonder') DESC LIMIT 1", (stelle,)).fetchone()
    if r is None and stelle.startswith("ts-") and not ist_reichsgebiet(stelle[3:]):
        teilstaaten_sichern(con)
        r = con.execute("SELECT * FROM gk_konten WHERE stelle=?", (stelle,)).fetchone()
    if r is None and (stelle == "verteidigung" or (stelle.startswith("vt-") and not ist_reichsgebiet(stelle[3:]))):
        import verteidigung
        verteidigung.kassen_sichern(con)
        r = con.execute("SELECT * FROM gk_konten WHERE stelle=?", (stelle,)).fetchone()
    return r


def anzeigename(con, konto_id, fallback=""):
    z = con.execute("SELECT ic_name, name FROM amt_akten WHERE konto_id=? ORDER BY id DESC LIMIT 1", (konto_id,)).fetchone()
    if z and z["ic_name"]:
        return z["ic_name"]
    r = con.execute("SELECT name FROM konten WHERE id=?", (konto_id,)).fetchone()
    return (r["name"] if r else "") or fallback or konto_id


def privatkonto(con, konto_id, anlegen=True, k=None):
    """Privatkonto eines Discord-Kontos (wird bei Bedarf eröffnet, ggf. mit Startguthaben)."""
    r = con.execute("SELECT * FROM gk_konten WHERE art='privat' AND inhaber_id=?", (konto_id,)).fetchone()
    if r or not anlegen:
        if r:
            name = anzeigename(con, konto_id, r["name"])
            if name != r["name"]:
                con.execute("UPDATE gk_konten SET name=? WHERE id=?", (name, r["id"]))
                con.commit()
                r = konto(con, r["id"])
        return r
    r = _anlegen(con, "privat", anzeigename(con, konto_id), inhaber_id=konto_id)
    start = einstellung(con, "startguthaben")
    if start:
        buchen(con, sonder(con, "zentralbank")["id"], r["id"], start, "startguthaben", "Startguthaben bei Kontoeröffnung")
    protokoll(con, k or {"id": konto_id, "name": r["name"]}, "Konto eröffnet", f'{r["nummer"]} ({r["name"]})')
    con.commit()
    return konto(con, r["id"])


def nach_nummer(con, nummer):
    n = nummer_gueltig(nummer)
    return con.execute("SELECT * FROM gk_konten WHERE nummer=?", (n,)).fetchone() if n else None


def art_name(r):
    if r["art"] == "sonder":
        return "Sonderkonto"
    return KONTOART[r["art"]][0]


# ---------------------------------------------------------------- Buchen

def buchen(con, von, an, betrag, art, zweck="", k=None, bezug="", minus=False, commit=False):
    """Bucht betrag (Heller) von Konto-ID `von` auf `an` (None = außerhalb, z. B. Geldvernichtung). Wirft Fehler bei fehlender
    Deckung oder Sperre. Gibt die Buchungs-ID zurück."""
    betrag = int(betrag)
    if betrag <= 0:
        raise Fehler("Der Betrag muss größer als 0 sein.")
    kv = konto(con, von) if von else None
    ka = konto(con, an) if an else None
    if von and not kv or an and not ka:
        raise Fehler("Konto nicht gefunden.")
    if von and an and von == an:
        raise Fehler("Auftraggeber- und Empfängerkonto sind gleich.")
    if kv and ka and kv["stelle"] in ("reichskasse", "zentralbank"):
        import notlage
        notlage.hilfe_pruefen(con, kv, ka, art)   # das Reich zahlt nicht für das Minus eines Teilstaats
    if kv and k and k.get("id") and art in ("ueberweisung", "steuer", "gebuehr") and kv["art"] in ("privat", "gewerbe") and kv["inhaber_id"] == k["id"]:
        import bankkarte   # ohne gültige Bankkarte keine selbst veranlasste Geldbewegung
        if not bankkarte.karte_gueltig(con, k["id"]):
            raise Fehler("Ohne gültige Bankkarte sind keine Geldbewegungen möglich. Beantrage eine Karte im Schatzamt-Portal unter „Bankkarte“.")
    if kv:
        if kv["gesperrt"] and art in ("ueberweisung", "steuer", "gebuehr"):
            raise Fehler(f'Das Konto {nummer_anzeige(kv["nummer"])} ist gesperrt' + (f': {kv["sperrgrund"]}' if kv["sperrgrund"] else "."))
        if not minus and kv["stelle"] not in AUSSEN and kv["saldo"] < betrag:
            import notlage
            if not notlage.dispo_erlaubt(con, kv, betrag, art):   # Dispo für Staats-, Verteidigungs- und Behördenkassen
                raise Fehler(notlage.fehlertext(kv))
    if ka and ka["gesperrt"] and art == "ueberweisung":
        raise Fehler("Das Empfängerkonto ist gesperrt und kann keine Überweisungen empfangen.")
    if kv:
        con.execute("UPDATE gk_konten SET saldo=saldo-? WHERE id=?", (betrag, von))
    if ka:
        con.execute("UPDATE gk_konten SET saldo=saldo+? WHERE id=?", (betrag, an))
    sv = konto(con, von)["saldo"] if von else None
    sa = konto(con, an)["saldo"] if an else None
    cur = con.execute("INSERT INTO gk_buchungen (zeit, von, an, betrag, art, zweck, bezug, autor_id, autor_name, saldo_von, saldo_an) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (int(time.time()), von, an, betrag, art, zweck[:200], bezug, k["id"] if k else "", k["name"] if k else "System", sv, sa))
    if commit:
        con.commit()
    return cur.lastrowid


def geldmenge(con):
    """Geld im Umlauf = Guthaben aller Konten außer Zentralbank und Volkswirtschaft (= −Saldo dieser beiden)."""
    return -sum(sonder(con, s)["saldo"] for s in AUSSEN)


# ---------------------------------------------------------------- Einstellungen, Protokoll

def einstellung(con, schl):
    r = con.execute("SELECT wert FROM gk_einstellungen WHERE schl=?", (schl,)).fetchone()
    return json.loads(r["wert"]) if r else json.loads(json.dumps(VORGABEN[schl]))


def einstellung_setzen(con, schl, wert, k):
    alt = einstellung(con, schl)
    con.execute("INSERT INTO gk_einstellungen (schl, wert, geaendert, von) VALUES (?,?,?,?) "
                "ON CONFLICT(schl) DO UPDATE SET wert=excluded.wert, geaendert=excluded.geaendert, von=excluded.von",
                (schl, json.dumps(wert), int(time.time()), k["name"]))
    if alt != wert:
        protokoll(con, k, "Satz geändert", f"{schl}: {json.dumps(alt, ensure_ascii=False)} → {json.dumps(wert, ensure_ascii=False)}")


def protokoll(con, k, aktion, text):
    con.execute("INSERT INTO gk_protokoll (zeit, konto_id, name, aktion, text) VALUES (?,?,?,?,?)",
                (int(time.time()), k["id"] if k else "", k["name"] if k else "System", aktion, text[:1000]))


# ---------------------------------------------------------------- Rechte

def _behoerde():
    return next(b for b in amt.BEHOERDEN if b["schl"] == "schatzamt")


def ist_beamter(k):
    """Mitarbeiter des Schatzamts (Rollen der Behörde) sowie Kronkanzler/Kaiser (+ Admins OOC)."""
    return bool(k) and k["mitglied"] and bereiche.darf(k, _behoerde())


def ist_leitung(k):
    return bool(k) and k["mitglied"] and bereiche.leitung(k, _behoerde())


def verfuegbare_konten(con, k):
    """Konten, über die das Konto verfügen (überweisen) darf: eigenes Privatkonto, eigene Gewerbe, Konten der Behörden mit
    Leitungsrecht, Reichskanzlei für den Kronkanzler; Leitung des Schatzamts zusätzlich Reichskasse und Sozialkasse."""
    out = []
    p = privatkonto(con, k["id"]) if k["mitglied"] else privatkonto(con, k["id"], anlegen=False)
    if p:
        out.append(p)
    out += con.execute("SELECT * FROM gk_konten WHERE art='gewerbe' AND inhaber_id=? ORDER BY name", (k["id"],)).fetchall()
    import notlage
    for b in amt.BEHOERDEN:
        if bereiche.leitung(k, b) and (b["leitung"] or bereiche._alle(k)) and not notlage.verfuegung_gesperrt(con, k, b["schl"]):
            r = stellenkonto(con, b["schl"])
            if r:
                out.append(r)
    if amt.ROLLE_KANZLER in k["rollen"] or bereiche._alle(k):
        out.append(stellenkonto(con, "kanzlei"))
    if k["id"] == amt.config.KAISER_ID:   # Crown Estates: Kronvermögen des Kaisers
        out.append(sonder(con, "crown_estates"))
    out += regierte_staatskassen(con, k)
    import verteidigung
    out += verteidigung.verfuegbare(con, k)
    if ist_leitung(k):
        out += [sonder(con, "reichskasse"), sonder(con, "sozialkasse")]
    seen, res = set(), []
    for r in out:
        if r and r["id"] not in seen:
            seen.add(r["id"])
            res.append(r)
    return res


def regierte_staatskassen(con, k, mit_zwang=False):
    """Staatskassen der Teilstaaten, die das Konto regiert (wie auf der Reichskarte: Fraktionsrolle + Landesherr oder Amtsrolle;
    Teilstaaten ohne eigene Fraktion verwaltet der Kronkanzler)."""
    import karte
    rollen = set(k["rollen"])
    regent = karte.ROLLE_LANDESHERR in rollen or bool(rollen & set(karte.ROLLEN_AEMTER))
    kanzler = amt.ROLLE_KANZLER in rollen or bereiche._alle(k)
    out = []
    staaten = karte.aktuell(con)["stand"]["staaten"]
    eigene = karte.fraktionen(rollen, staaten)
    for s in staaten:
        if ist_reichsgebiet(s):
            continue
        f = s["fraktion"]
        import notlage
        if not mit_zwang and notlage.zwang(con, "ts-" + s["id"]):   # Zwangsverwaltung: nur Kronkanzler/Kaiser verfügen
            if kanzler:
                r = stellenkonto(con, "ts-" + s["id"])
                if r:
                    out.append(r)
            continue
        if (f and f in eigene and (regent or f in karte.ROLLEN_AEMTER)) or ((not f or karte.regent_fehlt(f)) and kanzler):   # ohne Regent: Kronkanzler/Kaiser
            r = stellenkonto(con, "ts-" + s["id"])
            if r:
                out.append(r)
    return out


def darf_einsehen(con, k, r):
    return ist_beamter(k) or any(x["id"] == r["id"] for x in verfuegbare_konten(con, k))
