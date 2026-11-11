"""Besoldung des Reiches: Besoldungsordnung, Zuordnung über Discord-Rollen, individuelle Einstufung, Lohnlauf, Gehaltsabrechnungen.

Besoldungsgruppen (bs_gruppen) mit Laufbahn und Grundgehalt (Monat). Zuordnung: Discord-Rolle → Gruppe + Zahlstelle (bs_rollen);
die Ränge „OR-n …“/„OF-n …“ werden beim ersten Aufruf automatisch ihrer Gruppe zugeordnet (danach frei änderbar). Es gilt die
höchste Gruppe aller Rollen eines Mitglieds. Individuell (bs_personen): andere Gruppe, „keine Besoldung“, Zulage, Zahlstelle.
Lohnlauf je Monat (bs_laeufe, eindeutig): Probelauf → Ausführen. Abzüge: Lohnsteuer (Stufentarif, steuern.lohnsteuer) und Sozialabgabe;
Netto an das Privatkonto, Sozialabgabe an die Reichsversicherungskasse, Lohnsteuer an die Reichskasse, Länderanteil an die Staatskasse
des Wohnsitzes. Es zahlt die Dienststelle (Zahlstelle „auto“ = dienststelle(): Behörde der Rollen, Kronkanzlei für den Kronkanzler, sonst
Reichskasse); die Behörden finanzieren das aus ihrem Etat (etat.py). Fehlbetrag der Reichskasse auf Wunsch durch Geldschöpfung. Abrechnungen (bs_abrechnungen) mit PDF, DM an jeden.
"""
import json
import re
import time
from datetime import date

from aiohttp import web

import amt
import anmeldung
import config
import geld
import schatzamt as sa
import steuern
from geld import mark

esc = amt.esc
PFAD = sa.PFAD

SCHEMA = """
CREATE TABLE IF NOT EXISTS bs_gruppen (schl TEXT PRIMARY KEY, name TEXT NOT NULL, laufbahn TEXT NOT NULL, grundgehalt INTEGER NOT NULL, rang INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS bs_rollen (rolle_id TEXT PRIMARY KEY, gruppe TEXT NOT NULL, zahlstelle TEXT NOT NULL DEFAULT 'auto');
CREATE TABLE IF NOT EXISTS bs_personen (konto_id TEXT PRIMARY KEY, gruppe TEXT NOT NULL DEFAULT '', zulage INTEGER NOT NULL DEFAULT 0,
    zulage_text TEXT NOT NULL DEFAULT '', zahlstelle TEXT NOT NULL DEFAULT '', bemerkung TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS bs_laeufe (id INTEGER PRIMARY KEY AUTOINCREMENT, periode TEXT NOT NULL UNIQUE, anzahl INTEGER NOT NULL,
    brutto INTEGER NOT NULL, lohnsteuer INTEGER NOT NULL, abgaben INTEGER NOT NULL, netto INTEGER NOT NULL, geschoepft INTEGER NOT NULL DEFAULT 0,
    zeit INTEGER NOT NULL, autor_name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bs_abrechnungen (id INTEGER PRIMARY KEY AUTOINCREMENT, lauf INTEGER NOT NULL, periode TEXT NOT NULL, konto_id TEXT NOT NULL,
    name TEXT NOT NULL, gruppe TEXT NOT NULL, gruppe_name TEXT NOT NULL, quelle TEXT NOT NULL, grundgehalt INTEGER NOT NULL, zulage INTEGER NOT NULL,
    zulage_text TEXT NOT NULL DEFAULT '', brutto INTEGER NOT NULL, lohnsteuer INTEGER NOT NULL, abgaben INTEGER NOT NULL, netto INTEGER NOT NULL,
    zahlstelle TEXT NOT NULL, staat TEXT NOT NULL DEFAULT '', laenderanteil INTEGER NOT NULL DEFAULT 0, zeit INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS bs_abrechnungen_k ON bs_abrechnungen (konto_id, periode);
CREATE TABLE IF NOT EXISTS bs_rueckstaende (id INTEGER PRIMARY KEY AUTOINCREMENT, lauf INTEGER NOT NULL, periode TEXT NOT NULL, konto_id TEXT NOT NULL,
    name TEXT NOT NULL, gruppe TEXT NOT NULL, gruppe_name TEXT NOT NULL, quelle TEXT NOT NULL, grundgehalt INTEGER NOT NULL, zulage INTEGER NOT NULL,
    zulage_text TEXT NOT NULL DEFAULT '', brutto INTEGER NOT NULL, lohnsteuer INTEGER NOT NULL, abgaben INTEGER NOT NULL, netto INTEGER NOT NULL,
    zahlstelle TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'offen', erstellt INTEGER NOT NULL, gezahlt INTEGER);
CREATE INDEX IF NOT EXISTS bs_rueckstaende_s ON bs_rueckstaende (status, zahlstelle);
CREATE TABLE IF NOT EXISTS bs_zuschlaege (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, art TEXT NOT NULL DEFAULT 'prozent', wert REAL NOT NULL DEFAULT 0,
    zahlstelle TEXT NOT NULL DEFAULT 'grund', rollen TEXT NOT NULL DEFAULT '[]', aktiv INTEGER NOT NULL DEFAULT 1, rang INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS bs_zuschlag_personen (zuschlag INTEGER NOT NULL, konto_id TEXT NOT NULL, PRIMARY KEY (zuschlag, konto_id));
"""

M = 100   # Heller je Krone
GRUPPEN = [
    ("OR-1", "Soldat / Wachtmeister", "Mannschaften & Unteroffiziere", 1500), ("OR-2", "Gefreiter / Hauptwachtmeister", "Mannschaften & Unteroffiziere", 1600),
    ("OR-3", "Obergefreiter", "Mannschaften & Unteroffiziere", 1700), ("OR-4", "Stabsgefreiter", "Mannschaften & Unteroffiziere", 1850),
    ("OR-5", "Unteroffizier / Meister", "Mannschaften & Unteroffiziere", 2000), ("OR-6", "Unterfeldwebel / Obermeister", "Mannschaften & Unteroffiziere", 2150),
    ("OR-7", "Feldwebel / Hauptmeister", "Mannschaften & Unteroffiziere", 2300), ("OR-8", "Oberfeldwebel", "Mannschaften & Unteroffiziere", 2500),
    ("OR-9", "Stabsfeldwebel", "Mannschaften & Unteroffiziere", 2700),
    ("OF-1", "Leutnant / Kommissar / Inspektor", "Offiziere & höherer Vollzugsdienst", 2900), ("OF-2", "Hauptmann / Hauptkommissar", "Offiziere & höherer Vollzugsdienst", 3200),
    ("OF-3", "Major", "Offiziere & höherer Vollzugsdienst", 3500), ("OF-4", "Oberstleutnant", "Offiziere & höherer Vollzugsdienst", 3900),
    ("OF-5", "Oberst", "Offiziere & höherer Vollzugsdienst", 4400), ("OF-6", "Generalmajor / Rat", "Offiziere & höherer Vollzugsdienst", 5000),
    ("OF-7", "Generalleutnant / Oberrat", "Offiziere & höherer Vollzugsdienst", 5700), ("OF-8", "General / Direktor", "Offiziere & höherer Vollzugsdienst", 6400),
    ("OF-9", "Generaloberst / Leitender Direktor", "Offiziere & höherer Vollzugsdienst", 7200), ("OF-10", "Generalfeldmarschall / Stabschef", "Offiziere & höherer Vollzugsdienst", 8200),
    ("OF-11", "Großmarschall / Oberbefehlshaber", "Offiziere & höherer Vollzugsdienst", 9500),
    ("A9", "Inspektor", "Reichsverwaltung", 2700), ("A11", "Amtmann", "Reichsverwaltung", 3200), ("A12", "Amtsrat", "Reichsverwaltung", 3500),
    ("A13", "Regierungsrat / Inquisitor", "Reichsverwaltung", 4000), ("A15", "Direktor / Konsul", "Reichsverwaltung", 4800),
    ("A16", "Ministerialrat", "Reichsverwaltung", 5400), ("B3", "Bürgermeister / Magistrat", "Reichsverwaltung", 5000),
    ("B6", "Generaldirektor / Gouverneur", "Reichsverwaltung", 7000), ("B8", "Generalgouverneur", "Reichsverwaltung", 7600),
    ("B9", "Ministerialdirektor", "Reichsverwaltung", 7800), ("B10", "Vizekönig", "Reichsverwaltung", 8500), ("B11", "Staatssekretär", "Reichsverwaltung", 9000),
    ("P1", "Abgeordneter (Diät)", "Politische Ämter & Justiz", 3000), ("P2", "Präsidium des Reichstags", "Politische Ämter & Justiz", 6000),
    ("P3", "Kurfürst", "Politische Ämter & Justiz", 7000), ("R2", "Reichsrichter", "Politische Ämter & Justiz", 6000),
    ("R4", "Oberster Reichsrichter", "Politische Ämter & Justiz", 8500),
    ("S1", "Hand des Kaisers", "Höchste Staatsämter", 10000), ("S2", "Kronkanzler", "Höchste Staatsämter", 12000),
    ("KRG", "Kaiserin (Apanage)", "Höchste Staatsämter", 12000), ("KR", "Krondotation des Souveräns", "Höchste Staatsämter", 25000),
]
ROLLEN = {   # Vorbelegung: Discord-Rolle → Besoldungsgruppe (Ränge OR/OF werden über den Rollennamen ergänzt)
    "1522685953054081054": "KR", "1535795611599638638": "KRG", "1522693216053235903": "S1", "1561856444913946664": "S2",
    "1522696237004881980": "P3", "1522699286406627348": "R4", "1522699549808787528": "R2", "1522700028739584000": "B6", "1555987375287574609": "A13",
    "1522701497413144776": "P2", "1528931629819494454": "P1", "1526348059984789504": "A9", "1525947356049309788": "B10", "1525947448776986665": "B8",
    "1525947612639793253": "B6", "1555971841888223242": "B3", "1525948431267532860": "B3", "1555972124215353445": "B6", "1526341106755960912": "B11",
    "1555985280203231322": "B9", "1526342162952884304": "A16", "1526341196081791076": "A15", "1526342268691419278": "A9", "1555985146392617061": "A12",
    "1555985042180669541": "A11", "1522702617833246822": "B6", "1522702883215249631": "A15", "1522707672808292586": "OF-11",
    "1522721092127555666": "OF-10", "1522912530446684190": "OF-10", "1522913031456034938": "OF-10", "1522913765035606086": "B6",
    "1557335971966750780": "B6", "1557188989729906708": "B6", "1557179488444620890": "B6", "1526343002966986882": "OR-1", "1526343128997695528": "OR-1",
    "1526343421386690663": "OR-1", "1526343577481904379": "A9", "1557800373861753002": "OR-1", "1557187375006875758": "OR-1", "1557187293100515328": "OR-1",
}
RANG = re.compile(r"^(OR|OF)-(\d{1,2})\b")


def einrichten(con):
    con.executescript(SCHEMA)
    con.execute("CREATE TABLE IF NOT EXISTS bs_meta (schl TEXT PRIMARY KEY, wert TEXT NOT NULL)")
    if "uebersprungen" not in {r[1] for r in con.execute("PRAGMA table_info(bs_laeufe)")}:
        con.execute("ALTER TABLE bs_laeufe ADD COLUMN uebersprungen TEXT NOT NULL DEFAULT '[]'")
    if "nachzahlung" not in {r[1] for r in con.execute("PRAGMA table_info(bs_abrechnungen)")}:
        con.execute("ALTER TABLE bs_abrechnungen ADD COLUMN nachzahlung INTEGER NOT NULL DEFAULT 0")
    for tab in ("bs_abrechnungen", "bs_rueckstaende"):
        if "kronsteuer" not in {r[1] for r in con.execute(f"PRAGMA table_info({tab})")}:
            con.execute(f"ALTER TABLE {tab} ADD COLUMN kronsteuer INTEGER NOT NULL DEFAULT 0")
        if "posten" not in {r[1] for r in con.execute(f"PRAGMA table_info({tab})")}:
            con.execute(f"ALTER TABLE {tab} ADD COLUMN posten TEXT NOT NULL DEFAULT ''")   # JSON: [[Bezeichnung, Heller], …]
    if "zahlstelle_schl" not in {r[1] for r in con.execute("PRAGMA table_info(bs_abrechnungen)")}:
        con.execute("ALTER TABLE bs_abrechnungen ADD COLUMN zahlstelle_schl TEXT NOT NULL DEFAULT ''")
    if not con.execute("SELECT 1 FROM bs_gruppen LIMIT 1").fetchone():
        for i, (s, n, l, g) in enumerate(GRUPPEN):
            con.execute("INSERT INTO bs_gruppen (schl, name, laufbahn, grundgehalt, rang) VALUES (?,?,?,?,?)", (s, n, l, g * M, i))
        for r, g in ROLLEN.items():
            con.execute("INSERT OR IGNORE INTO bs_rollen (rolle_id, gruppe, zahlstelle) VALUES (?,?,'auto')", (r, g))
    if not con.execute("SELECT 1 FROM bs_meta WHERE schl='zahlstelle_auto'").fetchone():
        # 07.11.2026: Die Behörden zahlen ihre Mitarbeiter selbst – bisherige Vorgabe „Reichskasse“ wird „nach Dienststelle“
        con.execute("UPDATE bs_rollen SET zahlstelle='auto' WHERE zahlstelle='reichskasse'")
        con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('zahlstelle_auto', '1')")
    if not con.execute("SELECT 1 FROM bs_meta WHERE schl='zuschlaege'").fetchone():
        # 07.11.2026: Zuschläge auf Amtspositionen. Vorgaben: Stabschefs 20 % (Reichsverteidigungskasse), Oberbefehlshaber 15 % (Reichsverteidigungskasse),
        # Privatsekretär Seiner Majestät 20 % für den Kronkanzler (Crown Estates); der Kronkanzler erhält sein Grundgehalt aus der Reichskasse.
        for i, (n, art, w, z, rl) in enumerate((
                ("Stabschef", "prozent", 20, "verteidigung", ["1522721092127555666", "1522912530446684190", "1522913031456034938"]),
                ("Oberbefehlshaber", "prozent", 15, "verteidigung", ["1522707672808292586"]),
                ("Privatsekretär Seiner Majestät", "prozent", 20, "crown_estates", [amt.ROLLE_KANZLER]))):
            con.execute("INSERT INTO bs_zuschlaege (name, art, wert, zahlstelle, rollen, rang) VALUES (?,?,?,?,?,?)", (n, art, w, z, json.dumps(rl), i))
        con.execute("UPDATE bs_rollen SET zahlstelle='reichskasse' WHERE rolle_id=? AND zahlstelle='auto'", (amt.ROLLE_KANZLER,))
        con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('zuschlaege', '1')")
    if not con.execute("SELECT 1 FROM bs_meta WHERE schl='nebenaemter'").fetchone():
        # 07.11.2026: Weitere Ämter neben der höchsten Besoldungsgruppe (Fall Ernst-August VI.: Hand des Kaisers + Kurfürst + Präsidium) – Zuschlag
        # in Höhe der Hälfte des Grundgehalts des Amtes, fester Betrag aus der Reichskasse; wer das Amt bereits als Grundgehalt bezieht, erhält ihn nicht.
        rang = (con.execute("SELECT MAX(rang) FROM bs_zuschlaege").fetchone()[0] or 0) + 1
        for i, (n, rolle, gruppe) in enumerate((("Kurfürst", "1522696237004881980", "P3"), ("Präsidium des Reichstags", "1522701497413144776", "P2"))):
            gg = con.execute("SELECT grundgehalt FROM bs_gruppen WHERE schl=?", (gruppe,)).fetchone()
            if gg:
                con.execute("INSERT INTO bs_zuschlaege (name, art, wert, zahlstelle, rollen, rang) VALUES (?,?,?,?,?,?)",
                            (n, "betrag", float(gg[0] // 2), "reichskasse", json.dumps([rolle]), rang + i))
        con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('nebenaemter', '1')")
    if not con.execute("SELECT 1 FROM bs_meta WHERE schl='nebenamt_regel'").fetchone():
        # Die Einzel-Zuschläge Kurfürst/Präsidium gehen in der allgemeinen Nebenamt-Regel auf (gleiche Beträge) – abschalten, sonst doppelt
        con.execute("UPDATE bs_zuschlaege SET aktiv=0 WHERE name IN ('Kurfürst', 'Präsidium des Reichstags')")
        con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('nebenamt_regel', '1')")
    if not con.execute("SELECT 1 FROM bs_meta WHERE schl='crown'").fetchone():
        # 07.11.2026: Der Monarch (Imperator Rex, Imperatrix Regina) wird aus den Crown Estates des Kaisers bezahlt
        for r in ("1522685953054081054", "1535795611599638638"):
            con.execute("INSERT INTO bs_rollen (rolle_id, gruppe, zahlstelle) VALUES (?, COALESCE((SELECT gruppe FROM bs_rollen WHERE rolle_id=?), 'KR'), 'crown_estates') "
                        "ON CONFLICT(rolle_id) DO UPDATE SET zahlstelle='crown_estates'", (r, r))
        con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('crown', '1')")
    if not con.execute("SELECT 1 FROM bs_meta WHERE schl='militaer'").fetchone():
        # 07.11.2026: Verteidigungsetat – Führungsstab aus der Reichsverteidigungskasse, Teilstreitkräfte aus der Kasse ihres Teilstaats
        import verteidigung
        for r in verteidigung.FUEHRUNGSSTAB:
            con.execute("UPDATE bs_rollen SET zahlstelle='verteidigung' WHERE rolle_id=? AND zahlstelle='auto'", (r,))
        for r in verteidigung.TEILSTREITKRAEFTE:
            con.execute("UPDATE bs_rollen SET zahlstelle='vt-land' WHERE rolle_id=? AND zahlstelle='auto'", (r,))
        con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('militaer', '1')")
    con.commit()


async def raenge_sichern(app, con):
    """Einmalig: alle Rangrollen „OR-n …“/„OF-n …“ der passenden Gruppe zuordnen."""
    if con.execute("SELECT 1 FROM bs_meta WHERE schl='raenge'").fetchone():
        return
    gruppen = {r["schl"] for r in con.execute("SELECT schl FROM bs_gruppen")}
    for r in await app["discord"].rollen_liste():
        m = RANG.match(r["name"])
        if m and f"{m.group(1)}-{int(m.group(2))}" in gruppen:
            con.execute("INSERT OR IGNORE INTO bs_rollen (rolle_id, gruppe) VALUES (?,?)", (r["id"], f"{m.group(1)}-{int(m.group(2))}"))
    con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('raenge', '1')")
    con.commit()


MILITAER_NICHT = re.compile(r"polizei|zoll|schutz|regierung", re.I)   # Ränge der Behörden, nicht des Militärs


async def militaer_sichern(app, con):
    """Einmalig: militärische Dienstgrade (OR-/OF-Rollen ohne Polizei/Zoll/Schutz/Regierung) zahlt die Verteidigungskasse ihres Teilstaats."""
    if con.execute("SELECT 1 FROM bs_meta WHERE schl='militaer_raenge'").fetchone():
        return
    for r in await app["discord"].rollen_liste():
        if RANG.match(r["name"]) and not MILITAER_NICHT.search(r["name"]):
            con.execute("UPDATE bs_rollen SET zahlstelle='vt-land' WHERE rolle_id=? AND zahlstelle='auto'", (r["id"],))
    con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('militaer_raenge', '1')")
    con.commit()


def gruppen(con):
    return {g["schl"]: g for g in con.execute("SELECT * FROM bs_gruppen ORDER BY rang, schl")}


def dienststelle(rollen):
    """Zahlstelle nach Dienststelle: Kronkanzlei für den Kronkanzler, sonst die Behörde der Rollen (amt.BEHOERDEN), sonst die Reichskasse."""
    rollen = set(rollen or ())
    if amt.ROLLE_KANZLER in rollen:
        return "kanzlei"
    for b in amt.BEHOERDEN:
        if rollen & set(b["rollen"]):
            return b["schl"]
    return "reichskasse"


def zahlstelle_auto(rolle, rollen, rollennamen=None):
    """„Nach Dienststelle“: entscheidend ist die Rolle, die das Gehalt begründet – Behördenrolle → diese Behörde, Kronkanzler → Kronkanzlei,
    Dienstgrad (OR/OF, z. B. Polizei- oder Zollrang) → Behörde der übrigen Rollen, sonst (Kaiser, Hof, Reichsverwaltung, Gerichte …) die
    Reichskasse. Ohne Rolle (individuelle Einstufung, nur Zulage) oder ohne Rollennamen: nach den Rollen (dienststelle)."""
    if rolle is None or rollennamen is None:
        return dienststelle(rollen)
    if rolle == amt.ROLLE_KANZLER:
        return "kanzlei"
    for b in amt.BEHOERDEN:
        if rolle in b["rollen"]:
            return b["schl"]
    if RANG.match(rollennamen.get(rolle, "")):
        return dienststelle(rollen)
    return "reichskasse"


def zahlstellen(con):
    out = [("auto", "Nach Dienststelle (Behörde zahlt)"), ("crown_estates", "Crown Estates des Kaisers (Monarch)"), ("vt-land", "Verteidigungskasse des Teilstaats (Militär, nach Fraktion)"),
           ("verteidigung", "Reichsverteidigungskasse (Führungsstab)"), ("reichskasse", "Reichskasse"), ("kanzlei", "Kronkanzlei")] + [(b["schl"], b["name"]) for b in amt.BEHOERDEN]
    out += [(r["stelle"], r["name"]) for r in con.execute("SELECT stelle, name FROM gk_konten WHERE art IN ('teilstaat','verteidigung') "
                                                          "AND stelle!='verteidigung' ORDER BY art, name")]
    return out


def einstufung(con, konto_id, rollen, rollennamen=None):
    """(Gruppe|None, Quelle, Zahlstelle, Zulage, Zulagentext) oder None, wenn keine Besoldung."""
    gs = gruppen(con)
    p = con.execute("SELECT * FROM bs_personen WHERE konto_id=?", (konto_id,)).fetchone()
    if p and p["gruppe"] == "-":
        return None
    zulage, ztext = (p["zulage"], p["zulage_text"]) if p else (0, "")
    r = None
    if p and p["gruppe"] in gs:
        g, quelle, zahl = gs[p["gruppe"]], "Individuelle Einstufung", "auto"
    else:
        kand = []
        for r in rollen:
            z = con.execute("SELECT * FROM bs_rollen WHERE rolle_id=?", (r,)).fetchone()
            if z and z["gruppe"] in gs:
                kand.append((gs[z["gruppe"]], r, z["zahlstelle"]))
        if konto_id == config.KAISER_ID and "KR" in gs:
            kand.append((gs["KR"], None, "crown_estates"))
        if not kand:
            if not zulage:
                return None
            g, quelle, zahl = None, "Nur Zulage", "auto"
        else:
            g, r, zahl = max(kand, key=lambda x: (x[0]["grundgehalt"], x[0]["rang"], x[2] == "verteidigung"))
            quelle = f"Rolle „{(rollennamen or {}).get(r, r)}“" if r else "Souverän"
    if p and p["zahlstelle"]:
        zahl = p["zahlstelle"]
    if zahl == "auto":
        zahl = zahlstelle_auto(r, rollen, rollennamen)
    elif zahl == "vt-land":
        import verteidigung
        zahl = verteidigung.zahlstelle_land(con, rollen)
    return g, quelle, zahl, zulage, ztext, (r if kand_rolle(p, gs) else None)


# ---------------------------------------------------------------- Nebenämter (07.11.2026, Nutzervorgabe „überall Zuschläge“)
# Wer Rollen aus mehreren Amtsbereichen trägt, erhält das Grundgehalt der höchsten Gruppe und für jeden WEITEREN Amtsbereich einen Zuschlag von
# NEBENAMT_SATZ % des Grundgehalts der höchsten Gruppe in diesem Bereich, gezahlt von der Kasse dieses Amtes. Innerhalb eines Bereichs zählt nur
# das höchste Amt (Dienstgrade sind aufsteigend, Verwaltungslaufbahnen ebenso; Abgeordneter + Präsidium = ein Reichstagsmandat).
NEBENAMT_SATZ = 50
AMTSBEREICHE = (("OR", "Dienstgrad"), ("OF", "Dienstgrad"), ("A", "Verwaltung"), ("B", "Verwaltung"), ("P1", "Reichstag"), ("P2", "Reichstag"),
                ("P3", "Kurfürst"), ("R", "Justiz"), ("S1", "Hand des Kaisers"), ("S2", "Kronkanzler"), ("KRG", "Monarch"), ("KR", "Monarch"))


def amtsbereich(schl):
    return next((b for pre, b in AMTSBEREICHE if schl.startswith(pre)), schl)


def nebenaemter(con, konto_id, rollen, g, rollennamen=None):
    """[(Bezeichnung, Betrag Heller, Zahlstelle-Schlüssel)] der Nebenamt-Zuschläge zum Grundgehalt der Gruppe g."""
    if not g:
        return []
    gs = gruppen(con)
    eingang = {}   # niedrigste Gruppe je Laufbahn (Eingangsamt)
    for gg in gs.values():
        if gg["laufbahn"] not in eingang or gg["rang"] < eingang[gg["laufbahn"]]["rang"]:
            eingang[gg["laufbahn"]] = gg
    gedeckt = set()   # Rollen mit eigenem Zuschlag (z. B. Oberbefehlshaber, Stabschef): deren Amtsbereich ist damit abgegolten
    for zu in zuschlaege(con):
        gedeckt |= set(zu["rollen"]) & set(rollen or ())
    ausgeschlossen = {amtsbereich(g["schl"])}
    best = {}
    for r in rollen or ():
        z = con.execute("SELECT * FROM bs_rollen WHERE rolle_id=?", (r,)).fetchone()
        if not z or z["gruppe"] not in gs:
            continue
        gg = gs[z["gruppe"]]
        b = amtsbereich(gg["schl"])
        if r in gedeckt:
            ausgeschlossen.add(b)
            continue
        name = (rollennamen or {}).get(r, "")
        if (rollennamen is not None and b in ("Dienstgrad", "Verwaltung") and eingang[gg["laufbahn"]]["schl"] == gg["schl"]
                and not RANG.match(name)):
            continue   # bloße Zugehörigkeit (Kaiserliches Heer, Reichsverwaltung, Kaiserliches Reichssicherheitsamt …) ist kein eigenes Amt
        if b not in best or (gg["grundgehalt"], gg["rang"]) > (best[b][0]["grundgehalt"], best[b][0]["rang"]):
            best[b] = (gg, r, z["zahlstelle"])
    for b in ausgeschlossen:
        best.pop(b, None)
    out = []
    for b, (gg, r, zahl) in sorted(best.items(), key=lambda t: -t[1][0]["grundgehalt"]):
        betrag = int(round(gg["grundgehalt"] * NEBENAMT_SATZ / 100))
        if betrag <= 0:
            continue
        if zahl == "auto":
            zahl = zahlstelle_auto(r, rollen, rollennamen)
        elif zahl == "vt-land":
            import verteidigung
            zahl = verteidigung.zahlstelle_land(con, rollen)
        name = (rollennamen or {}).get(r) or gg["name"]
        out.append((f'Nebenamt {name} ({gg["schl"]}, {NEBENAMT_SATZ} %)', betrag, zahl))
    return out


def kand_rolle(p, gs):
    """True, wenn das Grundgehalt aus einer Rolle stammt (nicht aus einer individuellen Einstufung)."""
    return not (p and p["gruppe"] in gs)


amt.ICONS.setdefault("plus", '<path d="M5 12h14"/><path d="M12 5v14"/>')
ROLLEN_MONARCH = ("1522685953054081054", "1535795611599638638")   # Imperator Rex, Imperatrix Regina – zahlen keine Kronsteuer


def zuschlaege(con, nur_aktiv=True):
    return [dict(r, rollen=json.loads(r["rollen"] or "[]")) for r in con.execute("SELECT * FROM bs_zuschlaege" + (" WHERE aktiv=1" if nur_aktiv else "") + " ORDER BY rang, id")]


def zuschlaege_von(con, konto_id, rollen, grund, quelle_rolle=None):
    """[(Zuschlag, Betrag in Heller)] der Amtspositionen des Kontos: über die Discord-Rollen oder die persönliche Zuordnung; Prozentzuschläge
    beziehen sich auf das Grundgehalt der Besoldungsgruppe `grund` (Heller)."""
    rollen = set(rollen or ())
    zugeordnet = {r["zuschlag"] for r in con.execute("SELECT zuschlag FROM bs_zuschlag_personen WHERE konto_id=?", (konto_id,))}
    out = []
    for z in zuschlaege(con):
        if quelle_rolle and quelle_rolle in z["rollen"] and z["id"] not in zugeordnet:
            continue   # Amt begründet bereits das Grundgehalt – kein Zuschlag für dasselbe Amt
        if z["id"] in zugeordnet or rollen & set(z["rollen"]):
            betrag = int(round(grund * float(z["wert"]) / 100)) if z["art"] == "prozent" else int(round(float(z["wert"])))
            if betrag > 0:
                out.append((z, betrag))
    return out


def _zahlstelle_aufloesen(con, z, rollen, grundzahl):
    if z == "grund":
        return grundzahl
    if z == "auto":
        return dienststelle(rollen)
    if z == "vt-land":
        import verteidigung
        return verteidigung.zahlstelle_land(con, rollen)
    return z


def berechnen_einzeln(con, konto_id, name, rollen, rollennamen=None):
    """Bezüge eines Kontos als Liste von Abrechnungsteilen, einer je Zahlstelle: das Grundgehalt der Besoldungsgruppe (mit individueller Zulage) und die
    Zuschläge der Amtspositionen. Lohnsteuer, Sozialabgabe und Kronsteuer werden auf die Summe berechnet und anteilig auf die Teile verteilt.
    Leere Liste, wenn keine Besoldung besteht."""
    e = einstufung(con, konto_id, rollen, rollennamen)
    if not e:
        return []
    g, quelle, zahl, zulage, ztext, qrolle = e
    grund = g["grundgehalt"] if g else 0
    teile = {zahl: {"grund": grund, "zulage": zulage, "texte": [ztext] if ztext else [], "namen": [],
                    "posten": ([["Grundgehalt " + (g["schl"] if g else ""), grund]] if grund else []) + ([["Zulage" + (f": {ztext}" if ztext else ""), zulage]] if zulage else [])}}
    for z, betrag in (zuschlaege_von(con, konto_id, rollen, grund, qrolle) if g else []):
        zs = _zahlstelle_aufloesen(con, z["zahlstelle"], rollen, zahl)
        t = teile.setdefault(zs, {"grund": 0, "zulage": 0, "texte": [], "namen": [], "posten": []})
        t["zulage"] += betrag
        bez = f'Zuschlag {z["name"]}' + (f' {float(z["wert"]):g} %'.replace(".", ",") if z["art"] == "prozent" else "")
        t["texte"].append(bez)
        t["namen"].append(z["name"])
        t["posten"].append([bez, betrag])
    for bez, betrag, zs in nebenaemter(con, konto_id, rollen, g, rollennamen):
        t = teile.setdefault(zs, {"grund": 0, "zulage": 0, "texte": [], "namen": [], "posten": []})
        t["zulage"] += betrag
        t["texte"].append(bez)
        t["namen"].append(bez.split(" (")[0])
        t["posten"].append([bez, betrag])
    gesamt = sum(t["grund"] + t["zulage"] for t in teile.values())
    if gesamt <= 0:
        return []
    lst = steuern.lohnsteuer(con, gesamt)
    abg = int(round(gesamt * float(geld.einstellung(con, "sozialabgabe")) / 100))
    monarch = konto_id == config.KAISER_ID or bool(set(rollen or ()) & set(ROLLEN_MONARCH))
    kst = 0 if monarch else int(round(gesamt * float(geld.einstellung(con, "kronsteuer")) / 100))
    out, rest = [], {"lst": lst, "abg": abg, "kst": kst}
    items = list(teile.items())          # Grundgehalts-Zahlstelle zuerst (Reihenfolge des Einfügens)
    for i, (zs, t) in enumerate(items):
        brutto = t["grund"] + t["zulage"]
        if brutto <= 0:
            continue
        if i == len(items) - 1:
            a, b, c = rest["lst"], rest["abg"], rest["kst"]
        else:
            a, b, c = (int(round(v * brutto / gesamt)) for v in (lst, abg, kst))
            rest["lst"] -= a; rest["abg"] -= b; rest["kst"] -= c
        haupt = i == 0
        out.append({"konto_id": konto_id, "name": name, "gruppe": (g["schl"] if g else "–") if haupt else "ZUS",
                    "gruppe_name": (g["name"] if g else "Zulage") if haupt else ", ".join(t["namen"]),
                    "quelle": quelle if haupt else "Amtsposition: " + ", ".join(t["namen"]),
                    "grundgehalt": t["grund"], "zulage": t["zulage"], "zulage_text": ", ".join(t["texte"]), "brutto": brutto, "lohnsteuer": a, "abgaben": b,
                    "kronsteuer": c, "netto": brutto - a - b - c, "zahlstelle": zs, "posten": t["posten"]})
    return out


async def berechnen(app, con):
    await raenge_sichern(app, con)
    await militaer_sichern(app, con)
    namen = {r["id"]: r["name"] for r in await app["discord"].rollen_liste()}
    out = []
    for m in await app["discord"].mitglieder():
        out.extend(berechnen_einzeln(con, m["id"], geld.anzeigename(con, m["id"], m["name"]), m["rollen"], namen))
    out.sort(key=lambda x: (-x["brutto"], x["name"].lower()))
    return out


def letzte_abrechnung(con, konto_id):
    return con.execute("SELECT * FROM bs_abrechnungen WHERE konto_id=? ORDER BY id DESC LIMIT 1", (konto_id,)).fetchone()


def tabelle_html(con):
    zeilen, lb = [], None
    for g in gruppen(con).values():
        zeilen.append((esc(g["laufbahn"]) if g["laufbahn"] != lb else "", f'<b>{esc(g["schl"])}</b>', esc(g["name"]), f'<span class="sa-betrag">{mark(g["grundgehalt"])}</span>'))
        lb = g["laufbahn"]
    return amt.tabelle(["Laufbahn", "Gruppe", "Bezeichnung", "Grundgehalt / Monat"], zeilen)


def zuschlag_tabelle_html(con):
    """Öffentliche Übersicht der Zuschläge auf Amtspositionen (Tarife & Sätze)."""
    zs = dict(zahlstellen(con))
    zeilen = [(esc(z["name"]), (f'{float(z["wert"]):g} % des Grundgehalts'.replace(".", ",") if z["art"] == "prozent" else mark(int(z["wert"])) + " im Monat"),
               esc("Kasse des Grundgehalts" if z["zahlstelle"] == "grund" else zs.get(z["zahlstelle"], z["zahlstelle"]))) for z in zuschlaege(con)]
    zeilen.append(("Nebenämter (jeder weitere Amtsbereich)", f"{NEBENAMT_SATZ} % des Grundgehalts des höchsten Amtes im Bereich", "Kasse dieses Amtes"))
    return ("<h2>Zuschläge auf Amtspositionen</h2>" + amt.tabelle(["Amtsposition", "Zuschlag", "Gezahlt von"], zeilen, "Keine Zuschläge.")
            + '<p class="az">Amtsbereiche: Dienstgrad (Militär und Vollzug), Verwaltung, Reichstag, Kurfürst, Justiz, Hand des Kaisers, Kronkanzler, Monarch. '
              'Innerhalb eines Bereichs zählt nur das höchste Amt; das höchste Amt insgesamt bestimmt das Grundgehalt.</p>')


def _monat(periode):
    return sa._monatsname(periode)


ABRECHNUNG_CSS = """<style>
.ab-kopf{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1mm 6mm;margin:2mm 0 3mm}
.ab-kopf div{border-bottom:.5pt solid #ccd0d6;padding:.8mm 0}
.ab-kopf small{display:block;color:#666;font-size:7.5pt;letter-spacing:.06em;text-transform:uppercase}
.ab-kopf b{font-size:9.5pt}
table.ab{width:100%;border-collapse:collapse;margin:1mm 0 3mm;font-size:9.5pt}
table.ab th{text-align:left;font-size:7.5pt;letter-spacing:.07em;text-transform:uppercase;color:#555;border-bottom:.8pt solid #000;padding:1mm}
table.ab td{padding:1mm;border-bottom:.4pt solid #dde0e5}
table.ab td.b,table.ab th.b{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
table.ab tr.summe td{border-top:.8pt solid #000;border-bottom:0;font-weight:700}
table.ab tr.abzug td.b{color:#7a1212}
.ab-netto{display:flex;justify-content:space-between;align-items:baseline;border:1.2pt solid #000;padding:2.2mm 4mm;margin:2mm 0 3mm;background:#f4f5f7}
.ab-netto span{font-size:9pt;letter-spacing:.08em;text-transform:uppercase}
.ab-netto b{font-size:17pt}
.ab-hinweis{font-size:8.5pt;color:#555;margin:1.5mm 0}
</style>"""


def abrechnung_stelle(con, a):
    """(Logo-Schlüssel, Name) der zahlenden Stelle für den Briefkopf: Behörden mit eigenem Logo, Kronkanzlei, Schatzamt (Reichskasse);
    sonst das allgemeine Logo der Reichsbehörden mit dem Namen der Kasse."""
    schl = a["zahlstelle_schl"] if "zahlstelle_schl" in a.keys() else ""
    if not schl:   # ältere Abrechnungen: nur der Kassenname gespeichert
        schl = next((s for s, n in zahlstellen(con) if n == a["zahlstelle"]), "")
    if schl == "kanzlei":
        return ("kanzler", "Kronkanzlei")
    if schl == "reichskasse":
        return geld.STELLE
    if any(b["schl"] == schl for b in amt.BEHOERDEN):
        return amt.stelle_behoerde(schl)
    return ("reichsbehoerden", a["zahlstelle"] or "Die Reichsbehörden")


def _prozent(teil, ganz):
    return f"{teil / ganz * 100:,.1f} %".replace(",", "X").replace(".", ",").replace("X", ".") if ganz else "–"


def abrechnung_html(a, con=None):
    """Gehaltsabrechnung als HTML (Seite und PDF): Kopfdaten, Bezüge, Abzüge, Auszahlungsbetrag, Jahreswerte und Hinweise."""
    keys = a.keys()
    posten = json.loads(a["posten"]) if "posten" in keys and a["posten"] else []
    if not posten:
        posten = ([["Grundgehalt " + a["gruppe"], a["grundgehalt"]]] if a["grundgehalt"] else []) + ([[a["zulage_text"] or "Zulage", a["zulage"]]] if a["zulage"] else [])
    kontonr = ""
    if con is not None:
        r = con.execute("SELECT nummer FROM gk_konten WHERE art='privat' AND inhaber_id=?", (a["konto_id"],)).fetchone()
        kontonr = geld.nummer_anzeige(r["nummer"]) if r else ""
    kopf = [("Name", a["name"]), ("Abrechnungsmonat", _monat(a["periode"]) + (" · Nachzahlung" if a["nachzahlung"] else "")),
            ("Besoldungsgruppe", f'{a["gruppe"]} · {a["gruppe_name"]}' if a["gruppe"] != "ZUS" else a["gruppe_name"]), ("Grundlage", a["quelle"]),
            ("Zahlende Stelle", a["zahlstelle_name"] if "zahlstelle_name" in keys else a["zahlstelle"]), ("Auszahlung auf Konto", kontonr or "Privatkonto"),
            ("Ausgezahlt am", amt._zeit(a["zeit"], False)), ("Abrechnung Nr.", f'LL-{a["periode"]}-{a["id"]}')]
    kopf_html = '<div class="ab-kopf">' + "".join(f'<div><small>{esc(k)}</small><b>{esc(v)}</b></div>' for k, v in kopf) + '</div>'
    bez = "".join(f'<tr><td>{esc(b)}</td><td class="b">{mark(v)}</td></tr>' for b, v in posten)
    bez += f'<tr class="summe"><td>Bruttobezüge</td><td class="b">{mark(a["brutto"])}</td></tr>'
    abz = f'<tr class="abzug"><td>Lohnsteuer <span class="az">({_prozent(a["lohnsteuer"], a["brutto"])} des Bruttos)</span></td><td class="b">− {mark(a["lohnsteuer"])}</td></tr>'
    abz += f'<tr class="abzug"><td>Sozialabgabe, Reichsversicherung <span class="az">({_prozent(a["abgaben"], a["brutto"])})</span></td><td class="b">− {mark(a["abgaben"])}</td></tr>'
    if a["kronsteuer"]:
        abz += f'<tr class="abzug"><td>Kronsteuer, Crown Estates des Kaisers <span class="az">({_prozent(a["kronsteuer"], a["brutto"])})</span></td><td class="b">− {mark(a["kronsteuer"])}</td></tr>'
    abz += f'<tr class="summe"><td>Abzüge gesamt</td><td class="b">− {mark(a["lohnsteuer"] + a["abgaben"] + a["kronsteuer"])}</td></tr>'
    html = (ABRECHNUNG_CSS + kopf_html
            + f'<table class="ab"><thead><tr><th>Bezüge</th><th class="b">Betrag</th></tr></thead><tbody>{bez}</tbody></table>'
            + f'<table class="ab"><thead><tr><th>Abzüge</th><th class="b">Betrag</th></tr></thead><tbody>{abz}</tbody></table>'
            + f'<div class="ab-netto"><span>Auszahlungsbetrag (netto)</span><b>{mark(a["netto"])}</b></div>')
    hinweise = []
    if a["laenderanteil"]:
        hinweise.append(f'Von der Lohnsteuer gehen {mark(a["laenderanteil"])} als Länderanteil an {a["staat"]}; für Sie entsteht dadurch kein weiterer Abzug.')
    if con is not None:
        jahr = a["periode"][:4]
        j = con.execute("SELECT SUM(brutto) b, SUM(lohnsteuer) l, SUM(abgaben) s, SUM(kronsteuer) k, SUM(netto) n FROM bs_abrechnungen WHERE konto_id=? AND periode>=? AND periode<=?",
                        (a["konto_id"], jahr + "-01", a["periode"])).fetchone()
        html += (f'<table class="ab"><thead><tr><th>Aufgelaufen {esc(jahr)} bis {esc(_monat(a["periode"]))}</th><th class="b">Brutto</th><th class="b">Lohnsteuer</th>'
                 '<th class="b">Sozialabgabe</th>' + ('<th class="b">Kronsteuer</th>' if j["k"] else "") + '<th class="b">Netto</th></tr></thead><tbody>'
                 f'<tr><td>Alle Abrechnungen des Jahres</td><td class="b">{mark(j["b"] or 0)}</td><td class="b">{mark(j["l"] or 0)}</td><td class="b">{mark(j["s"] or 0)}</td>'
                 + (f'<td class="b">{mark(j["k"] or 0)}</td>' if j["k"] else "") + f'<td class="b"><b>{mark(j["n"] or 0)}</b></td></tr></tbody></table>')
        andere = con.execute("SELECT * FROM bs_abrechnungen WHERE konto_id=? AND periode=? AND id!=? ORDER BY id", (a["konto_id"], a["periode"], a["id"])).fetchall()
        if andere:
            html += ('<table class="ab"><thead><tr><th>Weitere Abrechnungen dieses Monats (Zuschläge anderer Kassen)</th><th>Zahlende Stelle</th><th class="b">Netto</th></tr></thead><tbody>'
                     + "".join(f'<tr><td>{esc(o["gruppe_name"] if o["gruppe"] == "ZUS" else o["gruppe"] + " · " + o["gruppe_name"])}</td><td>{esc(o["zahlstelle"])}</td><td class="b">{mark(o["netto"])}</td></tr>' for o in andere)
                     + f'<tr class="summe"><td colspan="2">Gesamtauszahlung des Monats</td><td class="b">{mark(a["netto"] + sum(o["netto"] for o in andere))}</td></tr></tbody></table>')
    hinweise.append("Die Besoldung richtet sich nach der Besoldungsordnung des Reiches; Sätze und Zuschläge sind unter „Tarife & Sätze“ im Schatzamt-Portal einsehbar.")
    return html + "".join(f'<p class="ab-hinweis">{esc(h)}</p>' for h in hinweise)


# ---------------------------------------------------------------- Bürger

@sa.seite("mitglied")
async def mein_gehalt(request, k):
    con = request.app["db"]
    namen = {r["id"]: r["name"] for r in await request.app["discord"].rollen_liste()}
    await raenge_sichern(request.app, con)
    teile = berechnen_einzeln(con, k["id"], k["name"], k["rollen"], namen)
    rows = con.execute("SELECT * FROM bs_abrechnungen WHERE konto_id=? ORDER BY id DESC", (k["id"],)).fetchall()
    if teile:
        x = teile[0]
        zsn = dict(zahlstellen(con))
        summe_t = lambda f: sum(t[f] for t in teile)
        posten = [("Besoldungsgruppe", f'{esc(x["gruppe"])} · {esc(x["gruppe_name"])}'), ("Grundlage", esc(x["quelle"])), ("Grundgehalt", mark(x["grundgehalt"]))]
        for t in teile:
            if t["zulage"]:
                posten.append(((t["zulage_text"] or "Zulage") + f' (gezahlt von {zsn.get(t["zahlstelle"], t["zahlstelle"])})', mark(t["zulage"])))
        posten += [("Brutto gesamt", f'<b>{mark(summe_t("brutto"))}</b>'), ("Lohnsteuer", "− " + mark(summe_t("lohnsteuer"))), ("Sozialabgabe", "− " + mark(summe_t("abgaben")))]
        if summe_t("kronsteuer"):
            posten.append(("Kronsteuer (Crown Estates)", "− " + mark(summe_t("kronsteuer"))))
        posten.append(("Voraussichtlich netto", f'<b>{mark(summe_t("netto"))}</b>'))
        einst = (amt.daten_tabelle(posten) + '<p class="sa-hinweis">Die Auszahlung erfolgt mit dem monatlichen Lohnlauf des Schatzamts.'
                 + (" Grundgehalt und Zuschläge kommen aus verschiedenen Kassen und erscheinen als getrennte Abrechnungen." if len(teile) > 1 else "") + '</p>')
    else:
        einst = '<p class="leer">Du erhältst derzeit keine Besoldung aus dem Reichshaushalt.</p>'
    zs_namen = dict(zahlstellen(con))
    offen = con.execute("SELECT * FROM bs_rueckstaende WHERE konto_id=? AND status='offen' ORDER BY periode", (k["id"],)).fetchall()
    einbehalt = "".join(f'<div class="warnung">{amt.ic("triangle-alert")} <b>Gehalt {esc(_monat(r["periode"]))} einbehalten:</b> {mark(r["netto"])} netto konnten nicht '
                        f'ausgezahlt werden, weil die Zahlstelle „{esc(zs_namen.get(r["zahlstelle"], r["zahlstelle"]))}“ nicht gedeckt war (Haushaltsnotlage). '
                        'Die Nachzahlung erfolgt automatisch, sobald die Kasse wieder im Plus ist.</div>' for r in offen)
    jahr = str(date.today().year)
    summe = [r for r in rows if r["periode"].startswith(jahr)]
    zeilen = [(f'<a href="{PFAD}gehalt/{r["id"]}/">{esc(_monat(r["periode"]))}</a>' + (" <span class=\"az\">(Nachzahlung)</span>" if r["nachzahlung"] else ""),
               esc(r["gruppe"]), mark(r["brutto"]), mark(r["lohnsteuer"]),
               mark(r["abgaben"]), f'<b>{mark(r["netto"])}</b>') for r in rows]
    inhalt = (f'<h1>{amt.ic("banknote")} Gehalt</h1>{amt.meldung(request)}{einbehalt}'
              f'<div class="kennzahlen"><div><b>{mark(sum(r["brutto"] for r in summe))}</b>Brutto {jahr}</div>'
              f'<div><b>{mark(sum(r["netto"] for r in summe))}</b>Netto {jahr}</div><div><b>{mark(sum(r["lohnsteuer"] for r in summe))}</b>Lohnsteuer {jahr}</div></div>'
              f'<h2>Aktuelle Einstufung</h2>{einst}<h2>Gehaltsabrechnungen</h2>'
              + amt.tabelle(["Monat", "Gruppe", "Brutto", "Lohnsteuer", "Sozialabgabe", "Netto"], zeilen, "Noch keine Gehaltsabrechnungen."))
    return sa.ant(request, k, "Gehalt", "sa-gehalt", inhalt)


def _abrechnung(con, i):
    a = con.execute("SELECT * FROM bs_abrechnungen WHERE id=?", (i,)).fetchone() if str(i).isdigit() else None
    if not a:
        raise web.HTTPNotFound(text="Abrechnung nicht gefunden.")
    return a


@sa.seite("mitglied")
async def abrechnung(request, k):
    con = request.app["db"]
    a = _abrechnung(con, request.match_info["id"])
    if a["konto_id"] != k["id"] and not geld.ist_beamter(k):
        raise web.HTTPNotFound()
    inhalt = (f'<h1>{amt.ic("banknote")} Gehaltsabrechnung {esc(_monat(a["periode"]))}</h1><p class="az"><a href="{PFAD}gehalt/">← Gehalt</a></p>'
              + abrechnung_html(a, con) + f'<p><a class="btn zweit" href="{PFAD}gehalt/{a["id"]}/pdf">{amt.ic("file-down")}Als PDF</a></p>')
    return sa.ant(request, k, "Gehaltsabrechnung", "sa-gehalt", inhalt)


async def abrechnung_pdf(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    con = request.app["db"]
    a = _abrechnung(con, request.match_info["id"])
    if a["konto_id"] != k["id"] and not geld.ist_beamter(k):
        raise web.HTTPNotFound()
    stelle = abrechnung_stelle(con, a)
    inhalt = f'<h1>Gehaltsabrechnung</h1><p class="az">{esc(a["name"])} · {esc(_monat(a["periode"]))}</p>' + abrechnung_html(a, con)
    return await amt._pdf_antwort(request, f"gehaltsabrechnung-{a['periode']}-{a['id']}", "Gehaltsabrechnung", inhalt, stelle=stelle,
                                  az=f"LL-{a['periode']}-{a['id']}", einstufung="", doktyp="Gehaltsabrechnung · Besoldung",
                                  unterzeile=f"{stelle[1]} – Besoldungsstelle", bearbeiter="Kaiserliches Schatz- und Währungsamt, Besoldungsstelle",
                                  qr_url=f"{config.SITE_URL}{PFAD}gehalt/{a['id']}/")


# ---------------------------------------------------------------- Verwaltung: Besoldungsordnung

@sa.seite("leitung")
async def verwaltung(request, k):
    con = request.app["db"]
    await raenge_sichern(request.app, con)
    rollen = await request.app["discord"].rollen_liste()
    namen = {r["id"]: r["name"] for r in rollen}
    mit = sorted(await request.app["discord"].mitglieder(), key=lambda m: m["name"].lower())
    mitnamen = {m["id"]: m["name"] for m in mit}
    gs = gruppen(con)
    zs = dict(zahlstellen(con))
    c = amt.csrf_feld(request)
    reiter = request.query.get("reiter", "gruppen")
    tabs = '<p class="reiter">' + " ".join(f'<a href="?reiter={s}" class="{"aktiv" if s == reiter else ""}">{t}</a>' for s, t in
                                          [("gruppen", "Besoldungsordnung"), ("rollen", "Rollenzuordnung"), ("zuschlaege", "Zuschläge"), ("personen", "Individuelle Einstufung")]) + "</p>"
    gopts = lambda sel="": "".join(f'<option value="{esc(s)}"{" selected" if s == sel else ""}>{esc(s)} · {esc(g["name"])} ({mark(g["grundgehalt"])})</option>' for s, g in gs.items())
    zopts = lambda sel="auto": "".join(f'<option value="{esc(s)}"{" selected" if s == sel else ""}>{esc(n)}</option>' for s, n in zs.items())
    if reiter == "zuschlaege":
        zopt_g = lambda sel: (f'<option value="grund"{" selected" if sel == "grund" else ""}>Wie das Grundgehalt</option>' + zopts(sel))
        ropts = lambda sel: "".join(f'<option value="{r["id"]}"{" selected" if r["id"] in sel else ""}>{esc(r["name"])}</option>' for r in rollen)
        mopts = "".join(f'<option value="{m["id"]}">{esc(m["name"])}</option>' for m in mit)

        def formular(z=None):
            z = z or {"id": "", "name": "", "art": "prozent", "wert": 10, "zahlstelle": "grund", "rollen": [], "aktiv": 1}
            wert = f'{float(z["wert"]):g}'.replace(".", ",") if z["art"] == "prozent" else mark(int(z["wert"]), einheit=False)
            return (f'<form class="sa-formular" method="post" action="{PFAD}amt/besoldung/zuschlag">{c}<input type="hidden" name="id" value="{z["id"]}"><div class="zeilen">'
                    f'<div><label>Bezeichnung der Amtsposition</label><input type="text" name="name" value="{esc(z["name"])}" required maxlength="60"></div>'
                    f'<div><label>Art</label><select name="art"><option value="prozent"{" selected" if z["art"] == "prozent" else ""}>Prozent des Grundgehalts</option>'
                    f'<option value="betrag"{" selected" if z["art"] == "betrag" else ""}>Fester Betrag (Kr/Monat)</option></select></div>'
                    f'<div><label>Wert (% bzw. Kr)</label><input type="text" name="wert" value="{esc(wert)}" required></div>'
                    f'<div><label>Gezahlt von</label><select name="zahlstelle">{zopt_g(z["zahlstelle"])}</select></div></div>'
                    f'<div><label>Discord-Rollen dieser Amtsposition (Mehrfachauswahl)</label><select name="rollen" multiple size="6">{ropts(set(z["rollen"]))}</select></div>'
                    f'<label><input type="checkbox" name="aktiv" value="1"{" checked" if z["aktiv"] else ""}> aktiv</label>'
                    f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button>'
                    + (f'<button class="btn zweit gefahr" name="loeschen" value="1" type="submit" onclick="return confirm(\'Zuschlag löschen?\')">Löschen</button>' if z["id"] else "")
                    + '</div></form>')
        blöcke = []
        for z in zuschlaege(con, nur_aktiv=False):
            pers = con.execute("SELECT konto_id FROM bs_zuschlag_personen WHERE zuschlag=?", (z["id"],)).fetchall()
            pz = "".join(f'<form method="post" action="{PFAD}amt/besoldung/zuschlag-person" style="display:inline">{c}<input type="hidden" name="id" value="{z["id"]}">'
                         f'<input type="hidden" name="konto" value="{p["konto_id"]}"><input type="hidden" name="loeschen" value="1">'
                         f'<button class="btn zweit klein" type="submit">{esc(mitnamen.get(p["konto_id"], p["konto_id"]))} ✕</button></form> ' for p in pers)
            satz = f'{float(z["wert"]):g} %'.replace(".", ",") if z["art"] == "prozent" else mark(int(z["wert"]))
            blöcke.append(f'<details class="sa-auf"><summary>{esc(z["name"])} · {satz} · von {esc(zs.get(z["zahlstelle"], "dem Grundgehalts-Zahler") if z["zahlstelle"] != "grund" else "dem Grundgehalts-Zahler")}'
                          f'{"" if z["aktiv"] else " · inaktiv"}</summary>{formular(z)}'
                          f'<h3>Persönlich zugeordnet</h3><p>{pz or "<span class=\"az\">Niemand persönlich zugeordnet.</span>"}</p>'
                          f'<form class="sa-leiste" method="post" action="{PFAD}amt/besoldung/zuschlag-person">{c}<input type="hidden" name="id" value="{z["id"]}">'
                          f'<div><label>Person ergänzen</label><select name="konto">{mopts}</select></div>'
                          f'<button class="btn zweit" type="submit">Zuordnen</button></form></details>')
        # Vorschau: wer bekommt welche Zuschläge
        vor = []
        for m in mit:
            e = einstufung(con, m["id"], m["rollen"], namen)
            if not e or not e[0]:
                continue
            for z, b in zuschlaege_von(con, m["id"], m["rollen"], e[0]["grundgehalt"], e[5]):
                vor.append((esc(m["name"]), esc(z["name"]), mark(b), esc(zs.get(_zahlstelle_aufloesen(con, z["zahlstelle"], m["rollen"], e[2]), z["zahlstelle"]))))
            for bez, b, zst in nebenaemter(con, m["id"], m["rollen"], e[0], namen):
                vor.append((esc(m["name"]), esc(bez), mark(b), esc(zs.get(zst, zst))))
        teil = ('<p class="az">Zuschläge gibt es auf Amtspositionen: Wer eine der Rollen einer Amtsposition trägt (oder ihr persönlich zugeordnet ist), erhält zum Grundgehalt '
                'seiner höchsten Besoldungsgruppe den Zuschlag – als Prozentsatz des Grundgehalts oder als fester Betrag. Jeder Zuschlag hat seine eigene zahlende Kasse '
                '(z. B. Crown Estates oder Reichsverteidigungskasse). Der Kaiser bezieht das Kaisergehalt als Grundgehalt und die Zuschläge seiner übrigen Positionen.</p>'
                f'<p class="az"><b>Nebenämter (automatisch):</b> Trägt jemand Ämter aus mehreren Amtsbereichen (Dienstgrad, Verwaltung, Reichstag, Kurfürst, Justiz, '
                f'Hand des Kaisers, Kronkanzler, Monarch), gibt es für jeden weiteren Bereich {NEBENAMT_SATZ} % des Grundgehalts des höchsten Amtes in diesem Bereich, '
                'gezahlt von der Kasse dieses Amtes. Innerhalb eines Bereichs zählt nur das höchste Amt.</p>'
                + "".join(blöcke) + f'<details class="sa-auf"><summary>{amt.ic("plus")}Neue Amtsposition mit Zuschlag</summary>{formular()}</details>'
                + '<h2>Aktuelle Zuschläge</h2>' + amt.tabelle(["Person", "Amtsposition", "Zuschlag / Monat", "Gezahlt von"], vor, "Derzeit erhält niemand einen Zuschlag."))
    elif reiter == "rollen":
        rows = con.execute("SELECT * FROM bs_rollen").fetchall()
        rows = sorted(rows, key=lambda r: (-(gs[r["gruppe"]]["grundgehalt"] if r["gruppe"] in gs else 0), namen.get(r["rolle_id"], "")))
        zeilen = [(esc(namen.get(r["rolle_id"], "unbekannte Rolle " + r["rolle_id"])), f'{esc(r["gruppe"])} · {esc(gs[r["gruppe"]]["name"]) if r["gruppe"] in gs else "?"}',
                   esc(zs.get(r["zahlstelle"], r["zahlstelle"])),
                   f'<form method="post" action="{PFAD}amt/besoldung/rolle">{c}<input type="hidden" name="rolle" value="{r["rolle_id"]}">'
                   f'<button class="btn zweit gefahr" name="loeschen" value="1" type="submit">Entfernen</button></form>') for r in rows]
        ropts = "".join(f'<option value="{r["id"]}">{esc(r["name"])}</option>' for r in rollen)
        teil = (f'<form class="sa-formular" method="post" action="{PFAD}amt/besoldung/rolle">{c}<div class="zeilen">'
                f'<div><label for="r">Discord-Rolle</label><select id="r" name="rolle">{ropts}</select></div>'
                f'<div><label for="g">Besoldungsgruppe</label><select id="g" name="gruppe">{gopts()}</select></div>'
                f'<div><label for="z">Zahlstelle</label><select id="z" name="zahlstelle">{zopts()}</select></div></div>'
                f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Zuordnen</button></div></form>'
                '<p class="sa-hinweis">Hat ein Mitglied mehrere besoldete Rollen, gilt die höchste Gruppe.</p>'
                + amt.tabelle(["Rolle", "Besoldungsgruppe", "Zahlstelle", ""], zeilen, "Keine Zuordnungen."))
    elif reiter == "personen":
        rows = con.execute("SELECT * FROM bs_personen").fetchall()
        zeilen = [(esc(mitnamen.get(p["konto_id"], p["konto_id"])), "Keine Besoldung" if p["gruppe"] == "-" else (esc(p["gruppe"]) or "nach Rolle"),
                   mark(p["zulage"]) + (f' <span class="az">{esc(p["zulage_text"])}</span>' if p["zulage_text"] else ""), esc(zs.get(p["zahlstelle"], "nach Rolle")),
                   esc(p["bemerkung"]), f'<form method="post" action="{PFAD}amt/besoldung/person">{c}<input type="hidden" name="konto" value="{p["konto_id"]}">'
                   f'<button class="btn zweit gefahr" name="loeschen" value="1" type="submit">Entfernen</button></form>') for p in rows]
        mopts = "".join(f'<option value="{m["id"]}">{esc(m["name"])}</option>' for m in mit)
        teil = (f'<form class="sa-formular" method="post" action="{PFAD}amt/besoldung/person">{c}<div class="zeilen">'
                f'<div><label for="m">Mitglied</label><select id="m" name="konto">{mopts}</select></div>'
                f'<div><label for="g2">Besoldungsgruppe</label><select id="g2" name="gruppe"><option value="">nach Rolle</option><option value="-">keine Besoldung</option>{gopts()}</select></div>'
                '<div><label for="zl">Zulage (Kr/Monat)</label><input type="text" id="zl" name="zulage" value="0"></div>'
                '<div><label for="zt">Zulage für</label><input type="text" id="zt" name="zulage_text" maxlength="60"></div>'
                f'<div><label for="z2">Zahlstelle</label><select id="z2" name="zahlstelle"><option value="">nach Rolle</option>{zopts("")}</select></div>'
                '<div><label for="b">Bemerkung</label><input type="text" id="b" name="bemerkung" maxlength="120"></div></div>'
                f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button></div></form>'
                + amt.tabelle(["Mitglied", "Gruppe", "Zulage", "Zahlstelle", "Bemerkung", ""], zeilen, "Keine individuellen Einstufungen."))
    else:
        zeilen, lb = [], None
        for g in gs.values():
            benutzt = con.execute("SELECT COUNT(*) FROM bs_rollen WHERE gruppe=?", (g["schl"],)).fetchone()[0]
            zeilen.append((esc(g["laufbahn"]) if g["laufbahn"] != lb else "", f'<b>{esc(g["schl"])}</b>', esc(g["name"]),
                           f'<span class="sa-betrag">{mark(g["grundgehalt"])}</span>', benutzt,
                           f'<form method="post" action="{PFAD}amt/besoldung/gruppe">{c}<input type="hidden" name="schl" value="{esc(g["schl"])}">'
                           f'<button class="btn zweit gefahr" name="loeschen" value="1" type="submit"{" disabled" if benutzt else ""}>Löschen</button></form>'))
            lb = g["laufbahn"]
        laufbahnen = "".join(f"<option>{esc(l)}</option>" for l in dict.fromkeys(g["laufbahn"] for g in gs.values()))
        teil = (f'<form class="sa-formular" method="post" action="{PFAD}amt/besoldung/gruppe">{c}<div class="zeilen">'
                '<div><label for="s">Kürzel (neu oder bestehend)</label><input type="text" id="s" name="schl" required maxlength="10"></div>'
                '<div><label for="n">Bezeichnung</label><input type="text" id="n" name="name" required maxlength="60"></div>'
                f'<div><label for="l">Laufbahn</label><input type="text" id="l" name="laufbahn" list="lb" required maxlength="60"><datalist id="lb">{laufbahnen}</datalist></div>'
                '<div><label for="gg">Grundgehalt (Kr/Monat)</label><input type="text" id="gg" name="grundgehalt" required></div></div>'
                f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Gruppe speichern</button></div></form>'
                + amt.tabelle(["Laufbahn", "Gruppe", "Bezeichnung", "Grundgehalt", "Rollen", ""], zeilen))
    inhalt = (f'<h1>{amt.ic("users")} Besoldung & Lohnlauf</h1>{amt.meldung(request)}'
              f'<p class="aktionen"><a class="btn" href="{PFAD}amt/lohnlauf/">{amt.ic("banknote")}Zum Lohnlauf</a></p>{tabs}{teil}')
    return sa.ant(request, k, "Besoldung", "sa-amt-besoldung", inhalt)


async def _leitung(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    return k, await sa.formular(request), request.app["db"]


async def zuschlag_speichern(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await request.post()
    if not secrets_ok(request, form):
        raise web.HTTPForbidden(text="Ungültige Anfrage (Sitzung abgelaufen?). Bitte Seite neu laden.")
    con = request.app["db"]
    pfad = f"{PFAD}amt/besoldung/?reiter=zuschlaege"
    zid = int(form["id"]) if str(form.get("id", "")).isdigit() else None
    if form.get("loeschen") and zid:
        z = con.execute("SELECT name FROM bs_zuschlaege WHERE id=?", (zid,)).fetchone()
        con.execute("DELETE FROM bs_zuschlag_personen WHERE zuschlag=?", (zid,))
        con.execute("DELETE FROM bs_zuschlaege WHERE id=?", (zid,))
        geld.protokoll(con, k, "Zuschlag gelöscht", z["name"] if z else str(zid))
        con.commit()
        sa.weiter(pfad, "Zuschlag gelöscht.")
    name, art = sa._f(form, "name", 60), form.get("art")
    roh = str(form.get("wert", "")).strip()
    if art == "prozent":
        wert = geld.prozent_lesen(roh)
    else:
        wert = geld.betrag_lesen(roh)
    zahlstelle = str(form.get("zahlstelle", "grund"))
    if not name or art not in ("prozent", "betrag") or not wert or (zahlstelle != "grund" and zahlstelle not in dict(zahlstellen(con))):
        sa.weiter(pfad, "Bitte Bezeichnung, Art, Wert (größer 0) und zahlende Kasse angeben.", True)
    rollen = sorted(set(str(r) for r in form.getall("rollen", []) if str(r).isdigit()))
    aktiv = 1 if form.get("aktiv") == "1" else 0
    if zid:
        con.execute("UPDATE bs_zuschlaege SET name=?, art=?, wert=?, zahlstelle=?, rollen=?, aktiv=? WHERE id=?", (name, art, float(wert), zahlstelle, json.dumps(rollen), aktiv, zid))
    else:
        rang = (con.execute("SELECT MAX(rang) FROM bs_zuschlaege").fetchone()[0] or 0) + 1
        con.execute("INSERT INTO bs_zuschlaege (name, art, wert, zahlstelle, rollen, aktiv, rang) VALUES (?,?,?,?,?,?,?)", (name, art, float(wert), zahlstelle, json.dumps(rollen), aktiv, rang))
    geld.protokoll(con, k, "Zuschlag gespeichert", f'{name}: {wert:g} {"%" if art == "prozent" else "Heller"}, zahlende Kasse {zahlstelle}, {len(rollen)} Rolle(n)')
    con.commit()
    sa.weiter(pfad, f"Zuschlag „{name}“ gespeichert; er gilt ab dem nächsten Lohnlauf.")


async def zuschlag_person(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await request.post()
    if not secrets_ok(request, form):
        raise web.HTTPForbidden(text="Ungültige Anfrage (Sitzung abgelaufen?). Bitte Seite neu laden.")
    con = request.app["db"]
    pfad = f"{PFAD}amt/besoldung/?reiter=zuschlaege"
    zid, kid = form.get("id", ""), str(form.get("konto", ""))
    if not str(zid).isdigit() or not kid.isdigit() or not con.execute("SELECT 1 FROM bs_zuschlaege WHERE id=?", (int(zid),)).fetchone():
        sa.weiter(pfad, "Ungültige Angaben.", True)
    if form.get("loeschen"):
        con.execute("DELETE FROM bs_zuschlag_personen WHERE zuschlag=? AND konto_id=?", (int(zid), kid))
    else:
        con.execute("INSERT OR IGNORE INTO bs_zuschlag_personen (zuschlag, konto_id) VALUES (?,?)", (int(zid), kid))
    geld.protokoll(con, k, "Zuschlag-Zuordnung", f"Zuschlag {zid}, Konto {kid}: {'entfernt' if form.get('loeschen') else 'zugeordnet'}")
    con.commit()
    sa.weiter(pfad, "Gespeichert.")


def secrets_ok(request, form):
    import secrets
    return secrets.compare_digest(str(form.get("csrf", "")), request["csrf"])


async def gruppe_speichern(request):
    k, form, con = await _leitung(request)
    pfad = f"{PFAD}amt/besoldung/?reiter=gruppen"
    schl = sa._f(form, "schl", 10).upper()
    if form.get("loeschen"):
        if con.execute("SELECT 1 FROM bs_rollen WHERE gruppe=? UNION SELECT 1 FROM bs_personen WHERE gruppe=?", (schl, schl)).fetchone():
            sa.weiter(pfad, "Die Gruppe ist noch zugeordnet.", True)
        con.execute("DELETE FROM bs_gruppen WHERE schl=?", (schl,))
        geld.protokoll(con, k, "Besoldungsgruppe gelöscht", schl)
        con.commit()
        sa.weiter(pfad, f"Gruppe {schl} gelöscht.")
    name, lb, gg = sa._f(form, "name", 60), sa._f(form, "laufbahn", 60), geld.betrag_lesen(form.get("grundgehalt"))
    if not schl or not name or not lb or not gg:
        sa.weiter(pfad, "Bitte Kürzel, Bezeichnung, Laufbahn und Grundgehalt angeben.", True)
    alt = con.execute("SELECT * FROM bs_gruppen WHERE schl=?", (schl,)).fetchone()
    rang = alt["rang"] if alt else (con.execute("SELECT MAX(rang) FROM bs_gruppen").fetchone()[0] or 0) + 1
    con.execute("INSERT INTO bs_gruppen (schl, name, laufbahn, grundgehalt, rang) VALUES (?,?,?,?,?) ON CONFLICT(schl) DO UPDATE SET "
                "name=excluded.name, laufbahn=excluded.laufbahn, grundgehalt=excluded.grundgehalt", (schl, name, lb, gg, rang))
    geld.protokoll(con, k, "Besoldungsgruppe gespeichert", f"{schl} {name}: {mark(gg)}" + (f" (vorher {mark(alt['grundgehalt'])})" if alt else " (neu)"))
    con.commit()
    sa.weiter(pfad, f"Gruppe {schl} gespeichert.")


async def rolle_speichern(request):
    k, form, con = await _leitung(request)
    pfad = f"{PFAD}amt/besoldung/?reiter=rollen"
    rolle = "".join(c for c in str(form.get("rolle", "")) if c.isdigit())[:25]
    if form.get("loeschen"):
        con.execute("DELETE FROM bs_rollen WHERE rolle_id=?", (rolle,))
        geld.protokoll(con, k, "Rollenzuordnung entfernt", rolle)
        con.commit()
        sa.weiter(pfad, "Zuordnung entfernt.")
    g, z = str(form.get("gruppe", "")), str(form.get("zahlstelle", "auto"))
    if not rolle or g not in gruppen(con) or z not in dict(zahlstellen(con)):
        sa.weiter(pfad, "Bitte Rolle, Gruppe und Zahlstelle wählen.", True)
    con.execute("INSERT INTO bs_rollen (rolle_id, gruppe, zahlstelle) VALUES (?,?,?) ON CONFLICT(rolle_id) DO UPDATE SET gruppe=excluded.gruppe, "
                "zahlstelle=excluded.zahlstelle", (rolle, g, z))
    geld.protokoll(con, k, "Rolle zugeordnet", f"{rolle} → {g} ({z})")
    con.commit()
    sa.weiter(pfad, "Rolle zugeordnet.")


async def person_speichern(request):
    k, form, con = await _leitung(request)
    pfad = f"{PFAD}amt/besoldung/?reiter=personen"
    kid = "".join(c for c in str(form.get("konto", "")) if c.isdigit())[:25]
    if form.get("loeschen"):
        con.execute("DELETE FROM bs_personen WHERE konto_id=?", (kid,))
        geld.protokoll(con, k, "Individuelle Einstufung entfernt", kid)
        con.commit()
        sa.weiter(pfad, "Einstufung entfernt.")
    g = str(form.get("gruppe", ""))
    z = str(form.get("zahlstelle", ""))
    zulage = geld.betrag_lesen(form.get("zulage", "0"), null_erlaubt=True)
    if not kid or (g not in ("", "-") and g not in gruppen(con)) or (z and z not in dict(zahlstellen(con))) or zulage is None:
        sa.weiter(pfad, "Bitte Eingaben prüfen.", True)
    con.execute("INSERT INTO bs_personen (konto_id, gruppe, zulage, zulage_text, zahlstelle, bemerkung) VALUES (?,?,?,?,?,?) ON CONFLICT(konto_id) DO UPDATE SET "
                "gruppe=excluded.gruppe, zulage=excluded.zulage, zulage_text=excluded.zulage_text, zahlstelle=excluded.zahlstelle, bemerkung=excluded.bemerkung",
                (kid, g, zulage, sa._f(form, "zulage_text", 60), z, sa._f(form, "bemerkung", 120)))
    geld.protokoll(con, k, "Individuelle Einstufung", f"{kid}: Gruppe {g or 'nach Rolle'}, Zulage {mark(zulage)}")
    con.commit()
    sa.weiter(pfad, "Einstufung gespeichert.")


# ---------------------------------------------------------------- Lohnlauf

def _bedarf(con, liste):
    """{Zahlstelle: (Konto, benötigt)} – was die Zahlstelle abgibt (bei der Reichskasse bleibt die Lohnsteuer im Haus)."""
    out = {}
    for x in liste:
        r = geld.stellenkonto(con, x["zahlstelle"]) or geld.sonder(con, "reichskasse")
        bedarf = (x["netto"] + x["abgaben"] + (0 if r["stelle"] == "crown_estates" else x.get("kronsteuer", 0))   # Kronsteuer bleibt bei den Crown Estates im Haus
                  + (0 if r["stelle"] == "reichskasse" else x["lohnsteuer"]))
        out.setdefault(r["id"], [r, 0])[1] += bedarf
    return out


def _auszahlen(con, x, periode, lauf, k, bezug, zs, nachzahlung=False):
    """Zahlt eine Abrechnung aus: Netto aufs Privatkonto, Sozialabgabe, Lohnsteuer, Länderanteil; schreibt die Abrechnung."""
    kasse = geld.sonder(con, "reichskasse")
    sozial = geld.sonder(con, "sozialkasse")
    quelle = geld.stellenkonto(con, x["zahlstelle"]) or kasse
    privat = geld.privatkonto(con, x["konto_id"])
    zweck = f"Besoldung {_monat(periode)} · {x['gruppe']}" + (" (Nachzahlung)" if nachzahlung else "")
    geld.buchen(con, quelle["id"], privat["id"], x["netto"], "gehalt", zweck, k, bezug=bezug, minus=True)
    if x["abgaben"]:
        geld.buchen(con, quelle["id"], sozial["id"], x["abgaben"], "sozialabgabe", f"Sozialabgabe {x['name']} {_monat(periode)}", k, bezug=bezug, minus=True)
    if x["lohnsteuer"] and quelle["id"] != kasse["id"]:
        geld.buchen(con, quelle["id"], kasse["id"], x["lohnsteuer"], "lohnsteuer", f"Lohnsteuer {x['name']} {_monat(periode)}", k, bezug=bezug, minus=True)
    if x.get("kronsteuer") and quelle["stelle"] != "crown_estates":
        geld.buchen(con, quelle["id"], geld.sonder(con, "crown_estates")["id"], x["kronsteuer"], "kronsteuer", f"Kronsteuer {x['name']} {_monat(periode)}", k, bezug=bezug, minus=True)
    staat, anteil = steuern.laenderanteil_buchen(con, x["konto_id"], x["lohnsteuer"], k, bezug) if x["lohnsteuer"] else (None, 0)
    cur = con.execute("INSERT INTO bs_abrechnungen (lauf, periode, konto_id, name, gruppe, gruppe_name, quelle, grundgehalt, zulage, zulage_text, brutto, "
                      "lohnsteuer, abgaben, netto, zahlstelle, staat, laenderanteil, zeit, nachzahlung, kronsteuer, posten, zahlstelle_schl) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (lauf, periode, x["konto_id"], x["name"], x["gruppe"], x["gruppe_name"], x["quelle"], x["grundgehalt"], x["zulage"], x["zulage_text"],
                       x["brutto"], x["lohnsteuer"], x["abgaben"], x["netto"], zs.get(x["zahlstelle"], x["zahlstelle"]), staat["name"] if staat else "", anteil,
                       int(time.time()), 1 if nachzahlung else 0, x.get("kronsteuer", 0),
                       x["posten"] if isinstance(x.get("posten"), str) else json.dumps(x.get("posten") or [], ensure_ascii=False), x["zahlstelle"]))
    return cur.lastrowid


def nachzahlen(con, k=None):
    """Zahlt einbehaltene Gehälter (bs_rueckstaende) nach, sobald die Zahlstelle wieder im Plus ist und den Betrag deckt (kein Dispo, älteste zuerst,
    je Zahlstelle bis die Mittel enden). Gibt [{konto_id, periode, netto, zahlstelle}] der Nachgezahlten zurück."""
    k = k or {"id": "", "name": "Kaiserliches Schatz- und Währungsamt (automatisch)"}
    kasse = geld.sonder(con, "reichskasse")
    zs = dict(zahlstellen(con))
    out = []
    for (stelle,) in con.execute("SELECT DISTINCT zahlstelle FROM bs_rueckstaende WHERE status='offen'").fetchall():
        quelle = geld.stellenkonto(con, stelle) or kasse
        for rs in con.execute("SELECT * FROM bs_rueckstaende WHERE zahlstelle=? AND status='offen' ORDER BY periode, id", (stelle,)).fetchall():
            quelle = geld.konto(con, quelle["id"])
            bedarf = (rs["netto"] + rs["abgaben"] + (0 if quelle["stelle"] == "crown_estates" else rs["kronsteuer"])
                      + (0 if quelle["id"] == kasse["id"] else rs["lohnsteuer"]))
            if quelle["saldo"] < bedarf:
                break
            x = dict(rs)
            aid = _auszahlen(con, x, rs["periode"], rs["lauf"], k, f"NZ-{rs['periode']}", zs, nachzahlung=True)
            con.execute("UPDATE bs_rueckstaende SET status='gezahlt', gezahlt=? WHERE id=?", (int(time.time()), rs["id"]))
            con.execute("UPDATE bs_laeufe SET anzahl=anzahl+1, brutto=brutto+?, lohnsteuer=lohnsteuer+?, abgaben=abgaben+?, netto=netto+? WHERE id=?",
                        (rs["brutto"], rs["lohnsteuer"], rs["abgaben"], rs["netto"], rs["lauf"]))
            geld.protokoll(con, k, "Gehalt nachgezahlt", f'{rs["name"]}: {_monat(rs["periode"])}, netto {mark(rs["netto"])} aus {zs.get(stelle, stelle)}')
            out.append({"konto_id": rs["konto_id"], "periode": rs["periode"], "netto": rs["netto"], "zahlstelle": zs.get(stelle, stelle), "abrechnung": aid})
    con.commit()
    return out


def rueckstand(con, stelle):
    """(Anzahl, Netto-Summe) der offenen Gehaltsrückstände einer Zahlstelle."""
    r = con.execute("SELECT COUNT(*) n, COALESCE(SUM(netto),0) s FROM bs_rueckstaende WHERE status='offen' AND zahlstelle=?", (stelle,)).fetchone()
    return r["n"], r["s"]


def lohnlauf_buchen(con, liste, periode, k, schoepfen=False):
    """Bucht den Lohnlauf (Liste aus berechnen()) für `periode`; wirft geld.Fehler bei fehlender Deckung. Gibt die Lauf-ID zurück."""
    kasse = geld.sonder(con, "reichskasse")
    zb = geld.sonder(con, "zentralbank")
    geschoepft = 0
    ungedeckt = {}
    for r, bedarf in _bedarf(con, liste).values():
        r = geld.konto(con, r["id"])
        if r["saldo"] < bedarf:
            if r["id"] == kasse["id"] and schoepfen:
                geschoepft = bedarf - r["saldo"]
                geld.buchen(con, zb["id"], kasse["id"], geschoepft, "geldschoepfung", f"Deckung Lohnlauf {_monat(periode)}", k)
            elif r["id"] == kasse["id"]:
                raise geld.Fehler(f'Die Zahlstelle {r["name"]} ist nicht gedeckt (benötigt {mark(bedarf)}, vorhanden {mark(r["saldo"])}).')
            else:
                ungedeckt[r["id"]] = r["name"]   # Haushaltsnotlage: Gehälter dieser Zahlstelle entfallen
    uebersprungen = [{"konto_id": x["konto_id"], "name": x["name"], "zahlstelle": ungedeckt[(geld.stellenkonto(con, x["zahlstelle"]) or kasse)["id"]],
                      "netto": x["netto"]} for x in liste if (geld.stellenkonto(con, x["zahlstelle"]) or kasse)["id"] in ungedeckt]
    uebersprungen_voll = [x for x in liste if (geld.stellenkonto(con, x["zahlstelle"]) or kasse)["id"] in ungedeckt]
    liste = [x for x in liste if (geld.stellenkonto(con, x["zahlstelle"]) or kasse)["id"] not in ungedeckt]
    cur = con.execute("INSERT INTO bs_laeufe (periode, anzahl, brutto, lohnsteuer, abgaben, netto, geschoepft, zeit, autor_name, uebersprungen) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (periode, len(liste), sum(x["brutto"] for x in liste), sum(x["lohnsteuer"] for x in liste), sum(x["abgaben"] for x in liste),
                       sum(x["netto"] for x in liste), geschoepft, int(time.time()), k["name"], json.dumps(uebersprungen, ensure_ascii=False)))
    lauf, bezug = cur.lastrowid, f"LL-{periode}"
    zs = dict(zahlstellen(con))
    for x in liste:
        _auszahlen(con, x, periode, lauf, k, bezug, zs)
    for x in uebersprungen_voll:   # einbehaltene Gehälter: Rückstand, wird nachgezahlt, sobald die Zahlstelle wieder im Plus ist
        con.execute("INSERT INTO bs_rueckstaende (lauf, periode, konto_id, name, gruppe, gruppe_name, quelle, grundgehalt, zulage, zulage_text, brutto, lohnsteuer, "
                    "abgaben, netto, zahlstelle, erstellt, kronsteuer, posten) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (lauf, periode, x["konto_id"], x["name"], x["gruppe"], x["gruppe_name"], x["quelle"], x["grundgehalt"], x["zulage"], x["zulage_text"],
                     x["brutto"], x["lohnsteuer"], x["abgaben"], x["netto"], x["zahlstelle"], int(time.time()), x.get("kronsteuer", 0),
                     json.dumps(x.get("posten") or [], ensure_ascii=False)))
    geld.protokoll(con, k, "Lohnlauf", f"{_monat(periode)}: {len(liste)} Abrechnungen, netto {mark(sum(x['netto'] for x in liste))}"
                                       + (f", Geldschöpfung {mark(geschoepft)}" if geschoepft else "")
                                       + (f"; {len(uebersprungen)} Gehälter einbehalten, Nachzahlung bei Deckung (Zahlstelle nicht gedeckt: {', '.join(sorted(set(u['zahlstelle'] for u in uebersprungen)))})"
                                          if uebersprungen else ""))
    con.commit()
    return lauf


@sa.seite("leitung")
async def lohnlauf(request, k):
    con = request.app["db"]
    periode = request.query.get("periode", date.today().strftime("%Y-%m"))[:7]
    probe = ""
    if request.query.get("probe"):
        schon = con.execute("SELECT * FROM bs_laeufe WHERE periode=?", (periode,)).fetchone()
        liste = await berechnen(request.app, con)
        zs = dict(zahlstellen(con))
        summen = {s: sum(x[s] for x in liste) for s in ("brutto", "lohnsteuer", "abgaben", "kronsteuer", "netto")}
        deckung = _bedarf(con, liste)
        dz = [(esc(r["name"]), mark(b), mark(r["saldo"]), amt.status_marke("ok", "gedeckt") if r["saldo"] >= b else
               amt.status_marke("nein", f"fehlen {mark(b - r['saldo'])}" + ("" if r["stelle"] == "reichskasse" else " – Gehälter werden einbehalten")))
              for r, b in deckung.values()]
        knopf = ""
        if schon:
            knopf = f'<div class="warnung">Für {esc(_monat(periode))} wurde bereits ein Lohnlauf ausgeführt.</div>'
        elif liste:
            knopf = (f'<form method="post" action="{PFAD}amt/lohnlauf/">{amt.csrf_feld(request)}<input type="hidden" name="periode" value="{esc(periode)}">'
                     '<label><input type="checkbox" name="schoepfen" value="1"> Fehlbetrag der Reichskasse durch Geldschöpfung der Zentralbank decken</label>'
                     f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Lohnlauf {esc(_monat(periode))} ausführen ({len(liste)} Abrechnungen)</button></div></form>')
        probe = (f'<h2>Probelauf {esc(_monat(periode))}</h2>'
                 f'<div class="kennzahlen"><div><b>{len(liste)}</b>Empfänger</div><div><b>{mark(summen["brutto"])}</b>Brutto</div>'
                 f'<div><b>{mark(summen["lohnsteuer"])}</b>Lohnsteuer</div><div><b>{mark(summen["abgaben"])}</b>Sozialabgaben</div><div><b>{mark(summen["kronsteuer"])}</b>Kronsteuer</div><div><b>{mark(summen["netto"])}</b>Netto</div></div>'
                 '<h3>Deckung der Zahlstellen</h3>' + amt.tabelle(["Zahlstelle", "Benötigt", "Guthaben", ""], dz, "–") + knopf
                 + '<h3>Abrechnungen</h3>' + amt.tabelle(["Name", "Gruppe", "Grundlage", "Brutto", "Lohnsteuer", "Sozialabg.", "Kronsteuer", "Netto", "Zahlstelle"],
                                                        [(esc(x["name"]), esc(x["gruppe"]), esc(x["quelle"]), mark(x["brutto"]), mark(x["lohnsteuer"]), mark(x["abgaben"]),
                                                          mark(x["kronsteuer"]) if x["kronsteuer"] else "–", f'<b>{mark(x["netto"])}</b>', esc(zs.get(x["zahlstelle"], x["zahlstelle"]))) for x in liste],
                                                        "Niemand hat Anspruch auf Besoldung (Rollenzuordnung prüfen)."))
    laeufe = con.execute("SELECT * FROM bs_laeufe ORDER BY id DESC LIMIT 36").fetchall()
    inhalt = (f'<h1>{amt.ic("banknote")} Lohnlauf</h1><p class="az"><a href="{PFAD}amt/besoldung/">← Besoldungsordnung</a></p>{amt.meldung(request)}'
              '<p class="az">Zahlt die Besoldung für einen Monat an alle Mitglieder mit besoldeter Rolle oder individueller Einstufung. Je Monat ist nur ein Lauf möglich.</p>'
              f'<form class="sa-leiste" method="get"><input type="hidden" name="probe" value="1"><div><label for="p">Monat</label>'
              f'<input type="month" id="p" name="periode" value="{esc(periode)}" required></div>'
              f'<button class="btn zweit" type="submit">{amt.ic("search")}Probelauf</button></form>{probe}'
              '<h2>Bisherige Lohnläufe</h2>' + amt.tabelle(["Monat", "Empfänger", "Brutto", "Lohnsteuer", "Sozialabgaben", "Netto", "Geschöpft", "Ausgeführt"],
                                                          [(f'<a href="{PFAD}amt/lohnlauf/{l["id"]}/">{esc(_monat(l["periode"]))}</a>', l["anzahl"], mark(l["brutto"]),
                                                            mark(l["lohnsteuer"]), mark(l["abgaben"]), mark(l["netto"]), mark(l["geschoepft"]),
                                                            f'{amt._zeit(l["zeit"])} · {esc(l["autor_name"])}') for l in laeufe], "Noch kein Lohnlauf."))
    return sa.ant(request, k, "Lohnlauf", "sa-amt-besoldung", inhalt)


def dm_text(a):
    """Nachricht an den Empfänger einer Gehaltsabrechnung (mit Link zur Abrechnung und zum PDF)."""
    return (f"Gehaltsabrechnung {_monat(a['periode'])} ({a['zahlstelle']}):\nBrutto {mark(a['brutto'])} · Lohnsteuer {mark(a['lohnsteuer'])} · Sozialabgabe "
            f"{mark(a['abgaben'])}" + (f" · Kronsteuer {mark(a['kronsteuer'])}" if a["kronsteuer"] else "") + f"\nAuszahlung: {mark(a['netto'])} auf dein Konto.\n"
            f"Abrechnung und PDF: {config.SITE_URL}{PFAD}gehalt/{a['id']}/")


async def _nachzahlung_melden(app, nz):
    for z in nz:
        try:
            await app["discord"].dm(z["konto_id"], f"Dein einbehaltenes Gehalt für {_monat(z['periode'])} wurde nachgezahlt: {mark(z['netto'])} netto von „{z['zahlstelle']}“ "
                                                   f"auf dein Konto.\n{config.SITE_URL}{PFAD}gehalt/")
        except Exception:
            pass


async def lohnlauf_ausfuehren(request):
    k, form, con = await _leitung(request)
    periode = str(form.get("periode", ""))[:7]
    pfad = f"{PFAD}amt/lohnlauf/?probe=1&periode={periode}"
    if not re.fullmatch(r"\d{4}-\d{2}", periode):
        sa.weiter(pfad, "Ungültiger Monat.", True)
    if con.execute("SELECT 1 FROM bs_laeufe WHERE periode=?", (periode,)).fetchone():
        sa.weiter(pfad, "Für diesen Monat wurde bereits ein Lohnlauf ausgeführt.", True)
    liste = await berechnen(request.app, con)
    if not liste:
        sa.weiter(pfad, "Keine Empfänger.", True)
    try:
        lauf = lohnlauf_buchen(con, liste, periode, k, bool(form.get("schoepfen")))
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(pfad, str(e), True)
    for a in con.execute("SELECT * FROM bs_abrechnungen WHERE lauf=?", (lauf,)).fetchall():
        sa.dm(request, a["konto_id"], dm_text(a))
    uebersprungen = json.loads(con.execute("SELECT uebersprungen FROM bs_laeufe WHERE id=?", (lauf,)).fetchone()[0] or "[]")
    for u in uebersprungen:
        sa.dm(request, u["konto_id"], f"Dein Gehalt für {_monat(periode)} wurde einbehalten: Die Kasse „{u['zahlstelle']}“ ist nicht gedeckt "
                                      f"(Haushaltsnotlage). Es wird automatisch nachgezahlt, sobald die Kasse wieder im Plus ist.")
    nz = nachzahlen(con)   # frühere Rückstände, falls die Zahlstelle inzwischen wieder gedeckt ist
    await _nachzahlung_melden(request.app, nz)
    sa.weiter(f"{PFAD}amt/lohnlauf/{lauf}/", f"Lohnlauf {_monat(periode)} ausgeführt: {len(liste) - len(uebersprungen)} Abrechnungen"
              + (f", {len(uebersprungen)} Gehälter einbehalten (Nachzahlung bei Deckung)" if uebersprungen else "")
              + (f", {len(nz)} frühere Gehälter nachgezahlt." if nz else "."))


@sa.seite("leitung")
async def lauf_seite(request, k):
    con = request.app["db"]
    l = con.execute("SELECT * FROM bs_laeufe WHERE id=?", (request.match_info["id"],)).fetchone() if request.match_info["id"].isdigit() else None
    if not l:
        raise web.HTTPNotFound()
    rows = con.execute("SELECT * FROM bs_abrechnungen WHERE lauf=? ORDER BY brutto DESC", (l["id"],)).fetchall()
    rueck = con.execute("SELECT * FROM bs_rueckstaende WHERE lauf=? ORDER BY status DESC, name", (l["id"],)).fetchall()
    zsn = dict(zahlstellen(con))
    warn = ('<div class="warnung">' + amt.ic("triangle-alert") + f' <b>{len(rueck)} Gehälter einbehalten</b>, weil die Zahlstelle nicht gedeckt war (Haushaltsnotlage); '
            'sie werden automatisch nachgezahlt, sobald die Kasse wieder im Plus ist: '
            + esc(", ".join(f'{r["name"]} ({zsn.get(r["zahlstelle"], r["zahlstelle"])}) – ' + ("nachgezahlt" if r["status"] == "gezahlt" else "offen") for r in rueck))
            + '</div>') if rueck else ""
    inhalt = (warn + f'<h1>{amt.ic("banknote")} Lohnlauf {esc(_monat(l["periode"]))}</h1><p class="az"><a href="{PFAD}amt/lohnlauf/">← Lohnlauf</a> · '
              f'ausgeführt {amt._zeit(l["zeit"])} von {esc(l["autor_name"])}</p>{amt.meldung(request)}'
              f'<div class="kennzahlen"><div><b>{l["anzahl"]}</b>Empfänger</div><div><b>{mark(l["brutto"])}</b>Brutto</div><div><b>{mark(l["lohnsteuer"])}</b>Lohnsteuer</div>'
              f'<div><b>{mark(l["abgaben"])}</b>Sozialabgaben</div><div><b>{mark(l["netto"])}</b>Netto</div><div><b>{mark(l["geschoepft"])}</b>Geschöpft</div></div>'
              + amt.tabelle(["Name", "Gruppe", "Brutto", "Lohnsteuer", "Sozialabg.", "Netto", "Länderanteil", "Zahlstelle"],
                            [(f'<a href="{PFAD}gehalt/{a["id"]}/">{esc(a["name"])}</a>', esc(a["gruppe"]), mark(a["brutto"]), mark(a["lohnsteuer"]), mark(a["abgaben"]),
                              f'<b>{mark(a["netto"])}</b>', (mark(a["laenderanteil"]) + " · " + esc(a["staat"])) if a["laenderanteil"] else "–", esc(a["zahlstelle"])) for a in rows]))
    return sa.ant(request, k, "Lohnlauf", "sa-amt-besoldung", inhalt)


def registrieren(app):
    einrichten(app["db"])
    r = app.router
    r.add_get(PFAD + "gehalt/", mein_gehalt)
    r.add_get(PFAD + "gehalt/{id}/", abrechnung)
    r.add_get(PFAD + "gehalt/{id}/pdf", abrechnung_pdf)
    r.add_get(PFAD + "amt/besoldung/", verwaltung)
    r.add_post(PFAD + "amt/besoldung/gruppe", gruppe_speichern)
    r.add_post(PFAD + "amt/besoldung/rolle", rolle_speichern)
    r.add_post(PFAD + "amt/besoldung/zuschlag", zuschlag_speichern)
    r.add_post(PFAD + "amt/besoldung/zuschlag-person", zuschlag_person)
    r.add_post(PFAD + "amt/besoldung/person", person_speichern)
    r.add_get(PFAD + "amt/lohnlauf/", lohnlauf)
    r.add_post(PFAD + "amt/lohnlauf/", lohnlauf_ausfuehren)
    r.add_get(PFAD + "amt/lohnlauf/{id}/", lauf_seite)
