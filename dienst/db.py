"""SQLite: Konten (Discord-Nutzer) und Sitzungen. Sitzungs-Tokens werden nur als SHA-256 gespeichert."""
import hashlib
import json
import os
import secrets
import sqlite3
import time

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS konten (
    id          TEXT PRIMARY KEY,      -- Discord-Nutzer-ID
    name        TEXT NOT NULL,         -- Anzeigename (Server-Spitzname, sonst globaler Name)
    avatar      TEXT,
    rollen      TEXT NOT NULL DEFAULT '[]',
    mitglied    INTEGER NOT NULL DEFAULT 0,
    admin       INTEGER NOT NULL DEFAULT 0,
    angemeldet  INTEGER NOT NULL,      -- letzte Anmeldung (Unix-Zeit)
    aktualisiert INTEGER NOT NULL      -- letzter Abgleich mit Discord
);
CREATE TABLE IF NOT EXISTS sitzungen (
    token_hash  TEXT PRIMARY KEY,
    konto_id    TEXT NOT NULL REFERENCES konten(id) ON DELETE CASCADE,
    csrf        TEXT NOT NULL,
    erstellt    INTEGER NOT NULL,
    laeuft_ab   INTEGER NOT NULL
);
"""


def verbinden():
    os.makedirs(os.path.dirname(config.DB), exist_ok=True)
    con = sqlite3.connect(config.DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def konto_speichern(con, k):
    jetzt = int(time.time())
    con.execute("""INSERT INTO konten (id, name, avatar, rollen, mitglied, admin, angemeldet, aktualisiert)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, avatar=excluded.avatar, rollen=excluded.rollen,
                     mitglied=excluded.mitglied, admin=excluded.admin, aktualisiert=excluded.aktualisiert""",
                (k["id"], k["name"], k["avatar"], json.dumps(k["rollen"]), int(k["mitglied"]), int(k["admin"]),
                 jetzt, jetzt))
    con.commit()


def anmeldung_vermerken(con, konto_id):
    con.execute("UPDATE konten SET angemeldet = ? WHERE id = ?", (int(time.time()), konto_id))
    con.commit()


def sitzung_anlegen(con, konto_id):
    token = secrets.token_urlsafe(32)
    jetzt = int(time.time())
    con.execute("INSERT INTO sitzungen VALUES (?, ?, ?, ?, ?)",
                (_hash(token), konto_id, secrets.token_urlsafe(24), jetzt, jetzt + config.SITZUNG_TAGE * 86400))
    con.execute("DELETE FROM sitzungen WHERE laeuft_ab < ?", (jetzt,))
    con.commit()
    return token


def sitzung_laden(con, token):
    """Gibt (Konto, CSRF-Token) zur Sitzung zurück oder (None, None)."""
    if not token:
        return None, None
    row = con.execute("""SELECT k.*, s.csrf FROM sitzungen s JOIN konten k ON k.id = s.konto_id
                         WHERE s.token_hash = ? AND s.laeuft_ab > ?""", (_hash(token), int(time.time()))).fetchone()
    if not row:
        return None, None
    konto = dict(row)
    konto["rollen"] = json.loads(konto["rollen"])
    konto["mitglied"], konto["admin"] = bool(konto["mitglied"]), bool(konto["admin"])
    return konto, konto.pop("csrf")


def sitzung_beenden(con, token):
    if token:
        con.execute("DELETE FROM sitzungen WHERE token_hash = ?", (_hash(token),))
        con.commit()


def konto_loeschen(con, konto_id):
    """Löscht Konto und alle Sitzungen (Auskunft/Löschung laut Datenschutzerklärung)."""
    cur = con.execute("DELETE FROM konten WHERE id = ?", (konto_id,))
    con.commit()
    return cur.rowcount
