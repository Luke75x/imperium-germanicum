"""Befugnisse für eingestellte Personen eines Teilstaats (Mein Teilstaat → Einstellungen).

Der Regent (Landesherr mit der Fraktionsrolle des Teilstaats, Kronkanzler/Kaiser bei Teilstaaten ohne Regent) kann Angehörigen des Kaiserlichen Schatz- und
Währungsamts einzelne Rechte für SEINEN Teilstaat geben: „etat“ (Etat planen und einreichen), „energie“ (Kraftwerke bauen, Handel), „verteidigung“ (Beschaffung und
Bestand der Verteidigungskasse). Die Rechte gelten nur für diesen Teilstaat; Regent bleibt nur, wer regiert (geld.regierte_staatskassen). Tabelle ts_befugnisse.
Prüfung: befugt(con, k, sid, recht), sids(con, k, recht=None). Eingebunden in etatplan.darf_aendern(…, recht), verteidigung.regierte/sicht, schatzamt._regierte/hat_kassen.
"""
import time

SCHATZAMT_ROLLE = "1574139894765195337"   # Rolle „Kaiserliches Schatz- und Währungsamt“ (Bot: dienstgrade.INSTITUTIONEN["schatzamt"])
RECHTE = {"etat": ("Etat planen und einreichen", "Die Etatverteilung des Teilstaats entwerfen und einreichen."),
          "energie": ("Kraftwerke bauen und Handel", "Kraftwerke bauen und stilllegen, Energiemarkt und Handel mit Waren und Gerät des Teilstaats."),
          "verteidigung": ("Verteidigung", "Militärgerät beschaffen und ausmustern, Bestand und Verteidigungskasse des Teilstaats.")}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ts_befugnisse (
    sid TEXT NOT NULL, konto_id TEXT NOT NULL, recht TEXT NOT NULL, von TEXT NOT NULL DEFAULT '', zeit INTEGER NOT NULL,
    PRIMARY KEY (sid, konto_id, recht));
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def ist_schatzamt(k):
    return bool(k) and SCHATZAMT_ROLLE in k["rollen"]


def befugt(con, k, sid, recht):
    """Hat das Konto dieses Recht für den Teilstaat (Karten-ID wie „s13“)? Nur Angehörige des Schatzamts zählen."""
    if not k or not ist_schatzamt(k) or recht not in RECHTE:
        return False
    return con.execute("SELECT 1 FROM ts_befugnisse WHERE sid=? AND konto_id=? AND recht=?", (sid, k["id"], recht)).fetchone() is not None


def sids(con, k, recht=None):
    """Teilstaat-IDs, für die das Konto mindestens (oder genau) dieses Recht hat."""
    if not k or not ist_schatzamt(k):
        return set()
    if "_bef" not in k:
        k["_bef"] = {}
        for r in con.execute("SELECT sid, recht FROM ts_befugnisse WHERE konto_id=?", (k["id"],)):
            k["_bef"].setdefault(r["recht"], set()).add(r["sid"])
    if recht:
        return set(k["_bef"].get(recht, ()))
    return set().union(*k["_bef"].values()) if k["_bef"] else set()


def zugang_sids(con, k):
    """Teilstaaten, in denen eine eingestellte Person „Mein Teilstaat“ sehen darf: der eigene (Fraktionsrolle) sowie alle mit einer Befugnis eines Regenten.
    Ansehen ist das Grundrecht jeder Schatzamts-Angehörigen; ändern darf sie nur, was der Regent ihr per Befugnis gibt."""
    if not k or not k["mitglied"] or not ist_schatzamt(k):
        return set()
    if "_bef_zugang" not in k:
        import verteidigung
        k["_bef_zugang"] = set(verteidigung.staaten_von(con, k["rollen"])) | sids(con, k)
    return k["_bef_zugang"]


def liste(con, sid):
    """{konto_id: {recht,…}} der Befugnisse eines Teilstaats."""
    out = {}
    for r in con.execute("SELECT konto_id, recht FROM ts_befugnisse WHERE sid=?", (sid,)):
        out.setdefault(r["konto_id"], set()).add(r["recht"])
    return out


def setzen(con, sid, konto_id, rechte, von):
    """Ersetzt die Rechte der Person für den Teilstaat durch `rechte` (leer = alle entziehen)."""
    con.execute("DELETE FROM ts_befugnisse WHERE sid=? AND konto_id=?", (sid, konto_id))
    for r in rechte:
        if r in RECHTE:
            con.execute("INSERT INTO ts_befugnisse (sid, konto_id, recht, von, zeit) VALUES (?,?,?,?,?)", (sid, konto_id, r, von, int(time.time())))
    con.commit()
