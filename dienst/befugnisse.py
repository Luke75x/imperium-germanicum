"""Befugnisse für eingestellte Personen eines Teilstaats (Mein Teilstaat → Einstellungen).

Der Regent (Landesherr mit der Fraktionsrolle des Teilstaats, Kronkanzler/Kaiser bei Teilstaaten ohne Regent) gibt Angehörigen des Kaiserlichen
Schatz- und Währungsamts einzeln für jeden Bereich SEINES Teilstaats das Recht zum Ansehen („<bereich>:lesen“) und/oder Bearbeiten („<bereich>“):
  etat          Etat ansehen / planen und einreichen                     (etatplan.darf_aendern(…, "etat"), etatplan._seite)
  entwicklung   Entwicklung ansehen (nur Ansicht)                        (entwicklung.seite, Reiter Land)
  energie       Energie ansehen / Kraftwerke bauen, Energiemarkt         (energie.py, darf_aendern(…, "energie"))
  krisen        Krisen ansehen / auf Krisen reagieren                    (krisen.py, darf_aendern(…, "krisen"))
  handel        Lager/Angebote ansehen / kaufen, anbieten, veredeln      (handel.py: darf / lese_halter)
  finanzen      Kassen, Reichsabgabe, Gold, Notlage, Umsätze / Gold handeln (teilstaat.finanzen, gold.handelbar, geld.darf_einsehen)
  verteidigung  Bestand ansehen / beschaffen und ausmustern              (verteidigung.sicht / regierte)
Bearbeiten schließt Ansehen ein. Die Rechte gelten nur für diesen Teilstaat; Regent bleibt nur, wer regiert (geld.regierte_staatskassen). Tabelle ts_befugnisse.

Grundzugang: Solange der Regent für eine Person des EIGENEN Teilstaats (Fraktionsrolle) noch nichts gespeichert hat, darf sie Etat, Entwicklung, Energie
und Krisen ansehen (STANDARD_LESEN, früherer Grundzugang). Sobald der Regent ihre Befugnisse speichert (Markierung „_gesetzt“), gilt nur noch, was er
angehakt hat – auch das Ansehen lässt sich so entziehen.
Prüfung: befugt(con, k, sid, recht), sids(con, k, recht=None), darf_sehen(con, k, sid, bereich) (Regent/Leitung/RP immer).
"""
import time

SCHATZAMT_ROLLE = "1574139894765195337"   # Rolle „Kaiserliches Schatz- und Währungsamt“ (Bot: dienstgrade.INSTITUTIONEN["schatzamt"])

# Bereich: (Titel, Ansehen – Beschreibung oder None, Bearbeiten – Beschreibung oder None)
BEREICHE = {
    "etat": ("Etat", "Geltenden Etat und Planung ansehen", "Etat planen, Rücklage festlegen und einreichen"),
    "entwicklung": ("Entwicklung", "Bevölkerung, Wirtschaft und Zufriedenheit ansehen", None),
    "energie": ("Energie", "Versorgung, Kraftwerke und Energiemarkt ansehen", "Kraftwerke bauen und stilllegen, Strom kaufen und anbieten"),
    "krisen": ("Krisen", "Offene Krisen und laufende Wirkungen ansehen", "Auf Krisen reagieren (Maßnahmen zahlt die Staatskasse)"),
    "handel": ("Handel", "Lager, Vorkommen, Angebote und Handelsbuch ansehen", "Waren und Gerät kaufen, anbieten, zurückziehen und veredeln"),
    "finanzen": ("Finanzen", "Kassen, Reichsabgabe, Gold, Notlage und Umsätze ansehen", "Gold kaufen und verkaufen"),
    "verteidigung": ("Verteidigung", "Militärgerät, Bestand und Verteidigungskasse ansehen", "Militärgerät beschaffen und ausmustern"),
}
STANDARD_LESEN = ("etat", "entwicklung", "energie", "krisen")   # Grundzugang im eigenen Teilstaat, solange der Regent nichts gespeichert hat
GESETZT = "_gesetzt"


def _gueltig():
    out = set()
    for b, (_, le, be) in BEREICHE.items():
        if le:
            out.add(b + ":lesen")
        if be:
            out.add(b)
    return out


GUELTIG = _gueltig()


def recht_name(r):
    b = r.split(":")[0]
    t = BEREICHE.get(b, (b,))[0]
    return f"{t} ansehen" if r.endswith(":lesen") else f"{t} bearbeiten"


SCHEMA = """
CREATE TABLE IF NOT EXISTS ts_befugnisse (
    sid TEXT NOT NULL, konto_id TEXT NOT NULL, recht TEXT NOT NULL, von TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL,
    PRIMARY KEY (sid, konto_id, recht));
"""


def einrichten(con):
    con.executescript(SCHEMA)
    # Umstellung 23.11.2026: „energie“ umfasste Kraftwerke UND Handel – Handel ist jetzt ein eigener Bereich
    if not con.execute("SELECT 1 FROM ts_befugnisse WHERE recht IN ('handel', ?) LIMIT 1", (GESETZT,)).fetchone():
        con.execute("INSERT OR IGNORE INTO ts_befugnisse (sid, konto_id, recht, von, zeit) SELECT sid, konto_id, 'handel', von, zeit FROM ts_befugnisse WHERE recht='energie'")
    con.commit()


def ist_schatzamt(k):
    return bool(k) and SCHATZAMT_ROLLE in k["rollen"]


def wirksam(roh, eigen):
    """Wirksame Rechte aus den gespeicherten Zeilen `roh` (Menge) – eigen: Teilstaat der eigenen Fraktionsrolle (Grundzugang)."""
    out = {r for r in roh if r in GUELTIG}
    out |= {r + ":lesen" for r in list(out) if ":" not in r and BEREICHE[r][1]}   # Bearbeiten schließt Ansehen ein
    if eigen and GESETZT not in roh:
        out |= {b + ":lesen" for b in STANDARD_LESEN}
    return out


def _alle(con, k):
    """{sid: wirksame Rechte} des Kontos (je Anfrage zwischengespeichert)."""
    if not k or not k["mitglied"] or not ist_schatzamt(k):
        return {}
    if "_bef" not in k:
        import verteidigung
        roh = {}
        for r in con.execute("SELECT sid, recht FROM ts_befugnisse WHERE konto_id=?", (k["id"],)):
            roh.setdefault(r["sid"], set()).add(r["recht"])
        eigene = verteidigung.staaten_von(con, k["rollen"])
        out = {}
        for sid in set(roh) | eigene:
            w = wirksam(roh.get(sid, set()), sid in eigene)
            if w:
                out[sid] = w
        k["_bef"] = out
    return k["_bef"]


def befugt(con, k, sid, recht):
    """Hat das Konto dieses Recht für den Teilstaat (Karten-ID wie „s13“)? recht = „etat“ (bearbeiten) oder „etat:lesen“. Nur Angehörige des Schatzamts zählen."""
    return recht in _alle(con, k).get(sid, ())


def sids(con, k, recht=None):
    """Teilstaat-IDs, für die das Konto irgendein (oder genau dieses) Recht hat."""
    return {s for s, w in _alle(con, k).items() if recht is None or recht in w}


def zugang_sids(con, k):
    """Teilstaaten, in denen eine eingestellte Person „Mein Teilstaat“ sieht: alle mit mindestens einem wirksamen Recht."""
    return sids(con, k)


def darf_sehen(con, k, sid, bereich):
    """Darf das Konto diesen Bereich des Teilstaats ansehen? Regent, Schatzamt-Leitung und RP-Leitung immer; eingestellte Personen nur mit Befugnis."""
    if not k or not k["mitglied"]:
        return False
    import geld
    if bool(k["admin"]) or geld.ist_leitung(k) or any(r["stelle"] == "ts-" + sid for r in geld.regierte_staatskassen(con, k, mit_zwang=True)):
        return True
    return befugt(con, k, sid, bereich + ":lesen")


def liste(con, sid):
    """{konto_id: {recht,…}} der gespeicherten Befugnisse eines Teilstaats (roh, mit „_gesetzt“)."""
    out = {}
    for r in con.execute("SELECT konto_id, recht FROM ts_befugnisse WHERE sid=?", (sid,)):
        out.setdefault(r["konto_id"], set()).add(r["recht"])
    return out


def setzen(con, sid, konto_id, rechte, von):
    """Ersetzt die Rechte der Person für den Teilstaat durch `rechte` (leer = alle entziehen, auch den Grundzugang)."""
    con.execute("DELETE FROM ts_befugnisse WHERE sid=? AND konto_id=?", (sid, konto_id))
    jetzt = int(time.time())
    for r in set(rechte) & GUELTIG | {GESETZT}:
        con.execute("INSERT INTO ts_befugnisse (sid, konto_id, recht, von, zeit) VALUES (?,?,?,?,?)", (sid, konto_id, r, von, jetzt))
    con.commit()
