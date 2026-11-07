"""Besoldung des Reiches: Besoldungsordnung, Zuordnung über Discord-Rollen, individuelle Einstufung, Lohnlauf, Gehaltsabrechnungen.

Besoldungsgruppen (bs_gruppen) mit Laufbahn und Grundgehalt (Monat). Zuordnung: Discord-Rolle → Gruppe + Zahlstelle (bs_rollen);
die Ränge „OR-n …“/„OF-n …“ werden beim ersten Aufruf automatisch ihrer Gruppe zugeordnet (danach frei änderbar). Es gilt die
höchste Gruppe aller Rollen eines Mitglieds. Individuell (bs_personen): andere Gruppe, „keine Besoldung“, Zulage, Zahlstelle.
Lohnlauf je Monat (bs_laeufe, eindeutig): Probelauf → Ausführen. Abzüge: Lohnsteuer (Stufentarif, steuern.lohnsteuer) und Sozialabgabe;
Netto an das Privatkonto, Sozialabgabe an die Reichsversicherungskasse, Lohnsteuer an die Reichskasse, Länderanteil an die Staatskasse
des Wohnsitzes. Es zahlt die Dienststelle (Zahlstelle „auto“ = dienststelle(): Behörde der Rollen, Reichskanzlei für den Kanzler, sonst
Reichskasse); die Behörden finanzieren das aus ihrem Etat (etat.py). Fehlbetrag der Reichskasse auf Wunsch durch Geldschöpfung. Abrechnungen (bs_abrechnungen) mit PDF, DM an jeden.
"""
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
    ("S1", "Hand des Kaisers", "Höchste Staatsämter", 10000), ("S2", "Kanzler", "Höchste Staatsämter", 12000),
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
    if not con.execute("SELECT 1 FROM bs_gruppen LIMIT 1").fetchone():
        for i, (s, n, l, g) in enumerate(GRUPPEN):
            con.execute("INSERT INTO bs_gruppen (schl, name, laufbahn, grundgehalt, rang) VALUES (?,?,?,?,?)", (s, n, l, g * M, i))
        for r, g in ROLLEN.items():
            con.execute("INSERT OR IGNORE INTO bs_rollen (rolle_id, gruppe, zahlstelle) VALUES (?,?,'auto')", (r, g))
    if not con.execute("SELECT 1 FROM bs_meta WHERE schl='zahlstelle_auto'").fetchone():
        # 07.11.2026: Die Behörden zahlen ihre Mitarbeiter selbst – bisherige Vorgabe „Reichskasse“ wird „nach Dienststelle“
        con.execute("UPDATE bs_rollen SET zahlstelle='auto' WHERE zahlstelle='reichskasse'")
        con.execute("INSERT INTO bs_meta (schl, wert) VALUES ('zahlstelle_auto', '1')")
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
    """Zahlstelle nach Dienststelle: Reichskanzlei für den Kanzler, sonst die Behörde der Rollen (amt.BEHOERDEN), sonst die Reichskasse."""
    rollen = set(rollen or ())
    if amt.ROLLE_KANZLER in rollen:
        return "kanzlei"
    for b in amt.BEHOERDEN:
        if rollen & set(b["rollen"]):
            return b["schl"]
    return "reichskasse"


def zahlstelle_auto(rolle, rollen, rollennamen=None):
    """„Nach Dienststelle“: entscheidend ist die Rolle, die das Gehalt begründet – Behördenrolle → diese Behörde, Kanzler → Reichskanzlei,
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
    out = [("auto", "Nach Dienststelle (Behörde zahlt)"), ("vt-land", "Verteidigungskasse des Teilstaats (Militär, nach Fraktion)"),
           ("verteidigung", "Reichsverteidigungskasse (Führungsstab)"), ("reichskasse", "Reichskasse"), ("kanzlei", "Reichskanzlei")] + [(b["schl"], b["name"]) for b in amt.BEHOERDEN]
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
            kand.append((gs["KR"], None, "reichskasse"))
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
    return g, quelle, zahl, zulage, ztext


def berechnen_einzeln(con, konto_id, name, rollen, rollennamen=None):
    e = einstufung(con, konto_id, rollen, rollennamen)
    if not e:
        return None
    g, quelle, zahl, zulage, ztext = e
    grund = g["grundgehalt"] if g else 0
    brutto = grund + zulage
    if brutto <= 0:
        return None
    lst = steuern.lohnsteuer(con, brutto)
    abg = int(round(brutto * float(geld.einstellung(con, "sozialabgabe")) / 100))
    return {"konto_id": konto_id, "name": name, "gruppe": g["schl"] if g else "–", "gruppe_name": g["name"] if g else "Zulage",
            "quelle": quelle, "grundgehalt": grund, "zulage": zulage, "zulage_text": ztext, "brutto": brutto, "lohnsteuer": lst,
            "abgaben": abg, "netto": brutto - lst - abg, "zahlstelle": zahl}


async def berechnen(app, con):
    await raenge_sichern(app, con)
    await militaer_sichern(app, con)
    namen = {r["id"]: r["name"] for r in await app["discord"].rollen_liste()}
    out = []
    for m in await app["discord"].mitglieder():
        x = berechnen_einzeln(con, m["id"], geld.anzeigename(con, m["id"], m["name"]), m["rollen"], namen)
        if x:
            out.append(x)
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


def _monat(periode):
    return sa._monatsname(periode)


def abrechnung_html(a):
    zeilen = [("Zeitraum", esc(_monat(a["periode"]))), ("Name", esc(a["name"])), ("Besoldungsgruppe", f'{esc(a["gruppe"])} · {esc(a["gruppe_name"])}'),
              ("Grundlage", esc(a["quelle"])), ("Zahlstelle", esc(a["zahlstelle_name"] if "zahlstelle_name" in a.keys() else a["zahlstelle"]))]
    posten = [("Grundgehalt", mark(a["grundgehalt"]))]
    if a["zulage"]:
        posten.append((f'Zulage{": " + a["zulage_text"] if a["zulage_text"] else ""}', mark(a["zulage"])))
    posten += [("<b>Bruttobezüge</b>", f'<b>{mark(a["brutto"])}</b>'), ("Lohnsteuer", "− " + mark(a["lohnsteuer"])),
               ("Sozialabgabe (Reichsversicherung)", "− " + mark(a["abgaben"])), ("<b>Auszahlung (netto)</b>", f'<b>{mark(a["netto"])}</b>')]
    if a["laenderanteil"]:
        posten.append((f'davon Länderanteil der Lohnsteuer an {esc(a["staat"])}', mark(a["laenderanteil"])))
    return amt.daten_tabelle(zeilen) + "<h2>Bezüge und Abzüge</h2>" + amt.tabelle(["Posten", "Betrag"], posten)


# ---------------------------------------------------------------- Bürger

@sa.seite("mitglied")
async def mein_gehalt(request, k):
    con = request.app["db"]
    namen = {r["id"]: r["name"] for r in await request.app["discord"].rollen_liste()}
    await raenge_sichern(request.app, con)
    x = berechnen_einzeln(con, k["id"], k["name"], k["rollen"], namen)
    rows = con.execute("SELECT * FROM bs_abrechnungen WHERE konto_id=? ORDER BY id DESC", (k["id"],)).fetchall()
    if x:
        einst = (amt.daten_tabelle([("Besoldungsgruppe", f'{esc(x["gruppe"])} · {esc(x["gruppe_name"])}'), ("Grundlage", esc(x["quelle"])),
                                    ("Brutto", mark(x["brutto"])), ("Lohnsteuer", "− " + mark(x["lohnsteuer"])), ("Sozialabgabe", "− " + mark(x["abgaben"])),
                                    ("Voraussichtlich netto", f'<b>{mark(x["netto"])}</b>')])
                 + '<p class="sa-hinweis">Die Auszahlung erfolgt mit dem monatlichen Lohnlauf des Schatzamts.</p>')
    else:
        einst = '<p class="leer">Du erhältst derzeit keine Besoldung aus dem Reichshaushalt.</p>'
    jahr = str(date.today().year)
    summe = [r for r in rows if r["periode"].startswith(jahr)]
    zeilen = [(f'<a href="{PFAD}gehalt/{r["id"]}/">{esc(_monat(r["periode"]))}</a>', esc(r["gruppe"]), mark(r["brutto"]), mark(r["lohnsteuer"]),
               mark(r["abgaben"]), f'<b>{mark(r["netto"])}</b>') for r in rows]
    inhalt = (f'<h1>{amt.ic("banknote")} Gehalt</h1>{amt.meldung(request)}'
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
              + abrechnung_html(a) + f'<p><a class="btn zweit" href="{PFAD}gehalt/{a["id"]}/pdf">{amt.ic("file-down")}Als PDF</a></p>')
    return sa.ant(request, k, "Gehaltsabrechnung", "sa-gehalt", inhalt)


async def abrechnung_pdf(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    con = request.app["db"]
    a = _abrechnung(con, request.match_info["id"])
    if a["konto_id"] != k["id"] and not geld.ist_beamter(k):
        raise web.HTTPNotFound()
    inhalt = f'<h1>Gehaltsabrechnung</h1><p class="az">{esc(a["name"])} · {esc(_monat(a["periode"]))}</p>' + abrechnung_html(a)
    return await amt._pdf_antwort(request, f"gehaltsabrechnung-{a['periode']}", "Gehaltsabrechnung", inhalt, stelle=geld.STELLE,
                                  az=f"LL-{a['periode']}-{a['id']}", einstufung="", doktyp="Gehaltsabrechnung",
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
                                          [("gruppen", "Besoldungsordnung"), ("rollen", "Rollenzuordnung"), ("personen", "Individuelle Einstufung")]) + "</p>"
    gopts = lambda sel="": "".join(f'<option value="{esc(s)}"{" selected" if s == sel else ""}>{esc(s)} · {esc(g["name"])} ({mark(g["grundgehalt"])})</option>' for s, g in gs.items())
    zopts = lambda sel="auto": "".join(f'<option value="{esc(s)}"{" selected" if s == sel else ""}>{esc(n)}</option>' for s, n in zs.items())
    if reiter == "rollen":
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
        bedarf = x["netto"] + x["abgaben"] + (0 if r["stelle"] == "reichskasse" else x["lohnsteuer"])
        out.setdefault(r["id"], [r, 0])[1] += bedarf
    return out


def lohnlauf_buchen(con, liste, periode, k, schoepfen=False):
    """Bucht den Lohnlauf (Liste aus berechnen()) für `periode`; wirft geld.Fehler bei fehlender Deckung. Gibt die Lauf-ID zurück."""
    kasse = geld.sonder(con, "reichskasse")
    zb = geld.sonder(con, "zentralbank")
    geschoepft = 0
    for r, bedarf in _bedarf(con, liste).values():
        r = geld.konto(con, r["id"])
        if r["saldo"] < bedarf:
            if r["id"] == kasse["id"] and schoepfen:
                geschoepft = bedarf - r["saldo"]
                geld.buchen(con, zb["id"], kasse["id"], geschoepft, "geldschoepfung", f"Deckung Lohnlauf {_monat(periode)}", k)
            else:
                raise geld.Fehler(f'Die Zahlstelle {r["name"]} ist nicht gedeckt (benötigt {mark(bedarf)}, vorhanden {mark(r["saldo"])}).')
    cur = con.execute("INSERT INTO bs_laeufe (periode, anzahl, brutto, lohnsteuer, abgaben, netto, geschoepft, zeit, autor_name) VALUES (?,?,?,?,?,?,?,?,?)",
                      (periode, len(liste), sum(x["brutto"] for x in liste), sum(x["lohnsteuer"] for x in liste), sum(x["abgaben"] for x in liste),
                       sum(x["netto"] for x in liste), geschoepft, int(time.time()), k["name"]))
    lauf, bezug = cur.lastrowid, f"LL-{periode}"
    sozial = geld.sonder(con, "sozialkasse")
    zs = dict(zahlstellen(con))
    for x in liste:
        quelle = geld.stellenkonto(con, x["zahlstelle"]) or kasse
        privat = geld.privatkonto(con, x["konto_id"])
        zweck = f"Besoldung {_monat(periode)} · {x['gruppe']}"
        geld.buchen(con, quelle["id"], privat["id"], x["netto"], "gehalt", zweck, k, bezug=bezug, minus=True)
        if x["abgaben"]:
            geld.buchen(con, quelle["id"], sozial["id"], x["abgaben"], "sozialabgabe", f"Sozialabgabe {x['name']} {_monat(periode)}", k, bezug=bezug, minus=True)
        if x["lohnsteuer"] and quelle["id"] != kasse["id"]:
            geld.buchen(con, quelle["id"], kasse["id"], x["lohnsteuer"], "lohnsteuer", f"Lohnsteuer {x['name']} {_monat(periode)}", k, bezug=bezug, minus=True)
        staat, anteil = steuern.laenderanteil_buchen(con, x["konto_id"], x["lohnsteuer"], k, bezug) if x["lohnsteuer"] else (None, 0)
        con.execute("INSERT INTO bs_abrechnungen (lauf, periode, konto_id, name, gruppe, gruppe_name, quelle, grundgehalt, zulage, zulage_text, brutto, "
                    "lohnsteuer, abgaben, netto, zahlstelle, staat, laenderanteil, zeit) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (lauf, periode, x["konto_id"], x["name"], x["gruppe"], x["gruppe_name"], x["quelle"], x["grundgehalt"], x["zulage"], x["zulage_text"],
                     x["brutto"], x["lohnsteuer"], x["abgaben"], x["netto"], zs.get(x["zahlstelle"], x["zahlstelle"]), staat["name"] if staat else "", anteil, int(time.time())))
    geld.protokoll(con, k, "Lohnlauf", f"{_monat(periode)}: {len(liste)} Abrechnungen, netto {mark(sum(x['netto'] for x in liste))}"
                                       + (f", Geldschöpfung {mark(geschoepft)}" if geschoepft else ""))
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
        summen = {s: sum(x[s] for x in liste) for s in ("brutto", "lohnsteuer", "abgaben", "netto")}
        deckung = _bedarf(con, liste)
        dz = [(esc(r["name"]), mark(b), mark(r["saldo"]), amt.status_marke("ok", "gedeckt") if r["saldo"] >= b else amt.status_marke("nein", f"fehlen {mark(b - r['saldo'])}"))
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
                 f'<div><b>{mark(summen["lohnsteuer"])}</b>Lohnsteuer</div><div><b>{mark(summen["abgaben"])}</b>Sozialabgaben</div><div><b>{mark(summen["netto"])}</b>Netto</div></div>'
                 '<h3>Deckung der Zahlstellen</h3>' + amt.tabelle(["Zahlstelle", "Benötigt", "Guthaben", ""], dz, "–") + knopf
                 + '<h3>Abrechnungen</h3>' + amt.tabelle(["Name", "Gruppe", "Grundlage", "Brutto", "Lohnsteuer", "Sozialabg.", "Netto", "Zahlstelle"],
                                                        [(esc(x["name"]), esc(x["gruppe"]), esc(x["quelle"]), mark(x["brutto"]), mark(x["lohnsteuer"]), mark(x["abgaben"]),
                                                          f'<b>{mark(x["netto"])}</b>', esc(zs.get(x["zahlstelle"], x["zahlstelle"]))) for x in liste],
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
        sa.dm(request, a["konto_id"], f"Gehaltsabrechnung {_monat(periode)} (Kaiserliches Schatz- und Währungsamt):\nBrutto {mark(a['brutto'])} · Lohnsteuer "
                                      f"{mark(a['lohnsteuer'])} · Sozialabgabe {mark(a['abgaben'])}\nAuszahlung: {mark(a['netto'])} auf dein Konto.\n"
                                      f"{config.SITE_URL}{PFAD}gehalt/{a['id']}/")
    sa.weiter(f"{PFAD}amt/lohnlauf/{lauf}/", f"Lohnlauf {_monat(periode)} ausgeführt: {len(liste)} Abrechnungen.")


@sa.seite("leitung")
async def lauf_seite(request, k):
    con = request.app["db"]
    l = con.execute("SELECT * FROM bs_laeufe WHERE id=?", (request.match_info["id"],)).fetchone() if request.match_info["id"].isdigit() else None
    if not l:
        raise web.HTTPNotFound()
    rows = con.execute("SELECT * FROM bs_abrechnungen WHERE lauf=? ORDER BY brutto DESC", (l["id"],)).fetchall()
    inhalt = (f'<h1>{amt.ic("banknote")} Lohnlauf {esc(_monat(l["periode"]))}</h1><p class="az"><a href="{PFAD}amt/lohnlauf/">← Lohnlauf</a> · '
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
    r.add_post(PFAD + "amt/besoldung/person", person_speichern)
    r.add_get(PFAD + "amt/lohnlauf/", lohnlauf)
    r.add_post(PFAD + "amt/lohnlauf/", lohnlauf_ausfuehren)
    r.add_get(PFAD + "amt/lohnlauf/{id}/", lauf_seite)
