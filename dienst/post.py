"""Internes Postfach und persönliche Einstellungen (Reiter „Postfach“ und „Einstellungen“ der Amtsseite).

Jeder Spieler (jedes Mitglied des Discord-Servers) hat eine interne Adresse: <Initial des Vornamens>.<Nachname>@<Institution>.ig,
z. B. a.falkenheim@staatskanzlei.ig. Name = IC-Name aus der Bürgerakte, sonst der Discord-Anzeigename. Die Institution folgt der
höchsten passenden Rolle in INSTITUTIONEN, sonst DEFAULT_INSTITUTION. Ändert sich Name oder Institution, bekommt der Spieler
eine neue aktuelle Adresse; alte Adressen bleiben als Alias zustellbar. Mails gibt es nur intern (zwischen .ig-Adressen).
Zugang: jedes Servermitglied mit Discord-Anmeldung (anders als die Aktenbereiche der Amtsseite).
Tabellen: post_adressen, post_nachrichten, post_empfaenger, nutzer_einstellungen.
"""
import asyncio
import logging
import re
import secrets
import time
import unicodedata

from aiohttp import web

import amt
import anmeldung
import config

log = logging.getLogger("post")
esc = amt.esc
BASIS = amt.BASIS
CON = None   # Datenbankverbindung (für das Zählzeichen in der Navigation)

# Reihenfolge = Vorrang bei mehreren Rollen. (Rolle, Domain ohne „.ig“, Anzeigename)
INSTITUTIONEN = ([(amt.ROLLE_KANZLER, "staatskanzlei", "Staatskanzlei")]
                 + [(r, b["domain"], b["name"]) for b in amt.BEHOERDEN for r in b["rollen"]]
                 + [("1522701497413144776", "reichstag", "Reichstag"), ("1528931629819494454", "reichstag", "Reichstag")])
DEFAULT_INSTITUTION = ("reich", "Reich")
MAX_EMPFAENGER = 10
MAX_PRO_STUNDE = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS post_adressen (
    adresse TEXT PRIMARY KEY, konto_id TEXT NOT NULL, aktuell INTEGER NOT NULL DEFAULT 1, angelegt INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS post_adressen_konto ON post_adressen (konto_id, aktuell);
CREATE TABLE IF NOT EXISTS post_nachrichten (
    id INTEGER PRIMARY KEY AUTOINCREMENT, absender_id TEXT NOT NULL, absender_adresse TEXT NOT NULL, absender_name TEXT NOT NULL DEFAULT '',
    betreff TEXT NOT NULL, text TEXT NOT NULL, zeit INTEGER NOT NULL, geloescht INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS post_nachrichten_abs ON post_nachrichten (absender_id, zeit);
CREATE TABLE IF NOT EXISTS post_empfaenger (
    nachricht_id INTEGER NOT NULL REFERENCES post_nachrichten(id) ON DELETE CASCADE, konto_id TEXT NOT NULL, adresse TEXT NOT NULL,
    gelesen INTEGER NOT NULL DEFAULT 0, geloescht INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (nachricht_id, konto_id));
CREATE INDEX IF NOT EXISTS post_empfaenger_konto ON post_empfaenger (konto_id, geloescht, gelesen);
CREATE TABLE IF NOT EXISTS nutzer_einstellungen (
    konto_id TEXT NOT NULL, schluessel TEXT NOT NULL, wert TEXT NOT NULL, PRIMARY KEY (konto_id, schluessel));
"""

amt.ICONS.update({
    "mail": '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    "sliders-horizontal": '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/>'
                          '<line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/>'
                          '<line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
    "send": '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/>'
            '<path d="m21.854 2.147-10.94 10.939"/>',
    "reply": '<polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
})


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Adressen

def _slug(text):
    text = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9-]", "", text).strip("-")


def adresse_aus_name(name, domain):
    """„Alexander Falkenheim“ + „staatskanzlei“ → a.falkenheim@staatskanzlei.ig (nur ein Wort: Wort@…)."""
    teile = [t for t in re.split(r"[\s|/,]+", name.strip()) if _slug(t)]
    if not teile:
        return None
    if len(teile) == 1:
        lokal = _slug(teile[0])
    else:
        lokal = _slug(teile[0])[0] + "." + _slug(teile[-1])
    return f"{lokal[:40]}@{domain}.ig"


def institution(rollen):
    rollen = set(rollen)
    for rolle, domain, anzeige in INSTITUTIONEN:
        if rolle in rollen:
            return domain, anzeige
    return DEFAULT_INSTITUTION


def _ic_name(con, konto_id):
    z = con.execute("SELECT ic_name FROM amt_akten WHERE konto_id=?", (konto_id,)).fetchone()
    return (z["ic_name"] if z else "") or ""


def adresse_sichern(con, konto_id, anzeigename, rollen):
    """Stellt sicher, dass das Konto seine aktuelle Adresse hat; gibt sie zurück (None, wenn aus dem Namen nichts wird)."""
    wunsch = adresse_aus_name(_ic_name(con, konto_id) or anzeigename, institution(rollen)[0])
    if not wunsch:
        return None
    jetzt = con.execute("SELECT adresse FROM post_adressen WHERE konto_id=? AND aktuell=1", (konto_id,)).fetchone()
    if jetzt and (jetzt["adresse"] == wunsch or re.sub(r"\d+@", "@", jetzt["adresse"]) == wunsch):
        return jetzt["adresse"]
    lokal, domain = wunsch.split("@")
    kandidat, n = wunsch, 1
    while True:
        z = con.execute("SELECT konto_id FROM post_adressen WHERE adresse=?", (kandidat,)).fetchone()
        if z is None or z["konto_id"] == konto_id:
            break
        n += 1
        kandidat = f"{lokal}{n}@{domain}"
    con.execute("UPDATE post_adressen SET aktuell=0 WHERE konto_id=?", (konto_id,))
    con.execute("INSERT INTO post_adressen (adresse, konto_id, aktuell, angelegt) VALUES (?,?,1,?) "
                "ON CONFLICT(adresse) DO UPDATE SET aktuell=1", (kandidat, konto_id, int(time.time())))
    con.commit()
    return kandidat


def meine_adresse(con, k):
    return adresse_sichern(con, k["id"], k["name"], k["rollen"])


async def abgleich(app):
    """Adressen für alle Servermitglieder anlegen bzw. an Namen/Rollen anpassen."""
    con = app["db"]
    n = 0
    for m in await app["discord"].mitglieder():
        if adresse_sichern(con, m["id"], m["name"], m["rollen"]):
            n += 1
    log.info("Adressabgleich: %d Mitglieder", n)


async def abgleich_schleife(app):
    await asyncio.sleep(20)
    while True:
        try:
            await abgleich(app)
        except Exception:
            log.exception("Adressabgleich fehlgeschlagen")
        await asyncio.sleep(900)


async def _start(app):
    app["post_task"] = asyncio.create_task(abgleich_schleife(app))


async def _stop(app):
    app["post_task"].cancel()


# ---------------------------------------------------------------- Einstellungen / Zähler

def einstellung(con, konto_id, schluessel, standard=""):
    z = con.execute("SELECT wert FROM nutzer_einstellungen WHERE konto_id=? AND schluessel=?", (konto_id, schluessel)).fetchone()
    return z["wert"] if z else standard


def einstellung_setzen(con, konto_id, schluessel, wert):
    con.execute("INSERT INTO nutzer_einstellungen (konto_id, schluessel, wert) VALUES (?,?,?) "
                "ON CONFLICT(konto_id, schluessel) DO UPDATE SET wert=excluded.wert", (konto_id, schluessel, wert))


def ungelesen(k):
    """Anzahl ungelesener Mails (für das Zählzeichen in der Navigation)."""
    if CON is None or not k:
        return 0
    return CON.execute("SELECT COUNT(*) FROM post_empfaenger WHERE konto_id=? AND gelesen=0 AND geloescht=0", (k["id"],)).fetchone()[0]


# ---------------------------------------------------------------- Seiten

def mitglied(handler):
    return anmeldung.angemeldet()(handler)


def _ant(request, titel, aktiv, inhalt):
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, aktiv, inhalt, request["konto"], request["csrf"]))


async def _form(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + BASIS)
    if not k["mitglied"]:
        raise web.HTTPForbidden(text="Nur für Mitglieder des Servers.")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage.")
    return k, form


def _reiter(aktiv):
    punkte = [("eingang", "Eingang", "postfach/"), ("gesendet", "Gesendet", "postfach/gesendet/"), ("neu", "Neue Nachricht", "postfach/neu/")]
    return '<p class="reiter">' + " ".join(f'<a href="{BASIS}{p}" class="{"aktiv" if s == aktiv else ""}">{esc(t)}</a>' for s, t, p in punkte) + "</p>"


def _kopf(request, k):
    adr = meine_adresse(request.app["db"], k)
    return f'<p class="az">Deine Adresse: <b>{esc(adr or "–")}</b></p>' + amt.meldung(request)


@mitglied
async def eingang(request):
    con, k = request.app["db"], request["konto"]
    rows = con.execute("""SELECT n.id, n.absender_name, n.absender_adresse, n.betreff, n.zeit, e.gelesen FROM post_empfaenger e
        JOIN post_nachrichten n ON n.id=e.nachricht_id WHERE e.konto_id=? AND e.geloescht=0 ORDER BY n.zeit DESC LIMIT 200""", (k["id"],)).fetchall()
    zeilen = [(f'{"<b>" if not r["gelesen"] else ""}{esc(r["absender_name"] or r["absender_adresse"])}<br><small>{esc(r["absender_adresse"])}</small>{"</b>" if not r["gelesen"] else ""}',
               f'<a href="{BASIS}postfach/{r["id"]}/">{"<b>" if not r["gelesen"] else ""}{esc(r["betreff"])}{"</b>" if not r["gelesen"] else ""}</a>',
               amt._zeit(r["zeit"])) for r in rows]
    inhalt = (f'<h1>{amt.ic("mail")} Postfach</h1>{_kopf(request, k)}{_reiter("eingang")}'
              + amt.tabelle(["Von", "Betreff", "Eingegangen"], zeilen, "Keine Nachrichten."))
    return _ant(request, "Postfach", "post", inhalt)


@mitglied
async def gesendet(request):
    con, k = request.app["db"], request["konto"]
    rows = con.execute("SELECT * FROM post_nachrichten WHERE absender_id=? AND geloescht=0 ORDER BY zeit DESC LIMIT 200", (k["id"],)).fetchall()
    zeilen = []
    for r in rows:
        an = ", ".join(e["adresse"] for e in con.execute("SELECT adresse FROM post_empfaenger WHERE nachricht_id=?", (r["id"],)))
        zeilen.append((esc(an), f'<a href="{BASIS}postfach/{r["id"]}/">{esc(r["betreff"])}</a>', amt._zeit(r["zeit"])))
    inhalt = (f'<h1>{amt.ic("mail")} Postfach</h1>{_kopf(request, k)}{_reiter("gesendet")}'
              + amt.tabelle(["An", "Betreff", "Gesendet"], zeilen, "Noch nichts gesendet."))
    return _ant(request, "Gesendet", "post", inhalt)


def _adressbuch(con):
    rows = con.execute("""SELECT a.adresse, k.name FROM post_adressen a LEFT JOIN konten k ON k.id=a.konto_id
                          WHERE a.aktuell=1 ORDER BY a.adresse LIMIT 3000""").fetchall()
    return "".join(f'<option value="{esc(r["adresse"])}">{esc(r["name"] or "")}</option>' for r in rows)


@mitglied
async def neu(request):
    con, k = request.app["db"], request["konto"]
    an, betreff, text = request.query.get("an", ""), request.query.get("betreff", ""), ""
    if request.query.get("antwort", "").isdigit():
        n = _sichtbar(con, k, int(request.query["antwort"]))
        if n:
            an = n["absender_adresse"]
            betreff = n["betreff"] if n["betreff"].lower().startswith("re:") else "Re: " + n["betreff"]
            text = "\n\n" + "\n".join("> " + z for z in n["text"].splitlines()[:30])
    inhalt = (f'<h1>{amt.ic("mail")} Postfach</h1>{_kopf(request, k)}{_reiter("neu")}'
              f'<form method="post" action="{BASIS}postfach/senden">{amt.csrf_feld(request)}'
              f'<div><label for="an">An (mehrere mit Komma trennen, höchstens {MAX_EMPFAENGER})</label>'
              f'<input type="text" id="an" name="an" value="{esc(an)}" list="adressbuch" style="width:100%" autocomplete="off" required></div>'
              f'<datalist id="adressbuch">{_adressbuch(con)}</datalist>'
              f'<div style="margin-top:8px"><label for="bt">Betreff</label><input type="text" id="bt" name="betreff" value="{esc(betreff)}" maxlength="200" style="width:100%" required></div>'
              f'<div style="margin-top:8px"><label for="tx">Nachricht</label><textarea id="tx" name="text" maxlength="10000" style="min-height:200px" required>{esc(text)}</textarea></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("send")}Senden</button></div></form>')
    return _ant(request, "Neue Nachricht", "post", inhalt)


def _sichtbar(con, k, nid):
    """Nachricht, wenn das Konto Absender oder Empfänger ist (und sie nicht gelöscht hat), sonst None."""
    n = con.execute("SELECT * FROM post_nachrichten WHERE id=?", (nid,)).fetchone()
    if not n:
        return None
    if n["absender_id"] == k["id"] and not n["geloescht"]:
        return n
    e = con.execute("SELECT 1 FROM post_empfaenger WHERE nachricht_id=? AND konto_id=? AND geloescht=0", (nid, k["id"])).fetchone()
    return n if e else None


@mitglied
async def lesen(request):
    con, k = request.app["db"], request["konto"]
    nid = int(request.match_info["id"]) if request.match_info["id"].isdigit() else 0
    n = _sichtbar(con, k, nid)
    if not n:
        raise web.HTTPNotFound(text="Nachricht nicht gefunden.")
    con.execute("UPDATE post_empfaenger SET gelesen=1 WHERE nachricht_id=? AND konto_id=?", (nid, k["id"]))
    con.commit()
    an = ", ".join(e["adresse"] for e in con.execute("SELECT adresse FROM post_empfaenger WHERE nachricht_id=?", (nid,)))
    von = f'{esc(n["absender_name"])} &lt;{esc(n["absender_adresse"])}&gt;' if n["absender_name"] else esc(n["absender_adresse"])
    inhalt = (f'<h1>{esc(n["betreff"])}</h1>{amt.meldung(request)}'
              + amt.daten_tabelle([("Von", von), ("An", esc(an)), ("Datum", amt._zeit(n["zeit"]))])
              + f'<div style="white-space:pre-wrap;word-break:break-word;margin:16px 0">{esc(n["text"])}</div>'
              f'<div class="aktionen"><a class="btn" href="{BASIS}postfach/neu/?antwort={nid}">{amt.ic("reply")}Antworten</a>'
              f'<form method="post" action="{BASIS}postfach/{nid}/loeschen" style="display:inline">{amt.csrf_feld(request)}'
              f'<button class="btn gefahr" type="submit">{amt.ic("trash-2")}Löschen</button></form>'
              f'<a class="btn zweit" href="{BASIS}postfach/">{amt.ic("arrow-left")}Zurück</a></div>')
    return _ant(request, n["betreff"], "post", inhalt)


async def loeschen(request):
    k, _form_ = await _form(request)
    con = request.app["db"]
    nid = int(request.match_info["id"]) if request.match_info["id"].isdigit() else 0
    con.execute("UPDATE post_empfaenger SET geloescht=1 WHERE nachricht_id=? AND konto_id=?", (nid, k["id"]))
    con.execute("UPDATE post_nachrichten SET geloescht=1 WHERE id=? AND absender_id=?", (nid, k["id"]))
    con.commit()
    amt._umleiten(BASIS + "postfach/", "Nachricht gelöscht.")


def _empfaenger(con, roh):
    """(Liste (konto_id, adresse), Fehlertext)"""
    teile = [t.strip().lower() for t in re.split(r"[,;\s]+", roh) if t.strip()]
    if not teile:
        return [], "Bitte mindestens einen Empfänger angeben."
    if len(teile) > MAX_EMPFAENGER:
        return [], f"Höchstens {MAX_EMPFAENGER} Empfänger."
    ergebnis, gesehen = [], set()
    for adr in teile:
        z = con.execute("SELECT konto_id FROM post_adressen WHERE adresse=?", (adr,)).fetchone()
        if not z:
            return [], f"Unbekannte Adresse: {adr}"
        if z["konto_id"] not in gesehen:
            gesehen.add(z["konto_id"])
            ergebnis.append((z["konto_id"], adr))
    return ergebnis, None


async def senden(request):
    k, form = await _form(request)
    con = request.app["db"]
    ziel = BASIS + "postfach/neu/"
    absender = meine_adresse(con, k)
    if not absender:
        amt._umleiten(ziel, "Aus deinem Namen lässt sich keine Adresse bilden.", True)
    betreff = " ".join(str(form.get("betreff", "")).split())[:200]
    text = str(form.get("text", "")).replace("\r\n", "\n").strip()[:10000]
    if not betreff or not text:
        amt._umleiten(ziel, "Betreff und Nachricht dürfen nicht leer sein.", True)
    empf, fehler = _empfaenger(con, str(form.get("an", "")))
    if fehler:
        amt._umleiten(ziel, fehler, True)
    if con.execute("SELECT COUNT(*) FROM post_nachrichten WHERE absender_id=? AND zeit>?", (k["id"], time.time() - 3600)).fetchone()[0] >= MAX_PRO_STUNDE:
        amt._umleiten(ziel, f"Zu viele Nachrichten in der letzten Stunde (höchstens {MAX_PRO_STUNDE}).", True)
    sig = einstellung(con, k["id"], "signatur")
    if sig:
        text += "\n\n-- \n" + sig
    cur = con.execute("INSERT INTO post_nachrichten (absender_id, absender_adresse, absender_name, betreff, text, zeit) VALUES (?,?,?,?,?,?)",
                      (k["id"], absender, _ic_name(con, k["id"]) or k["name"], betreff, text, int(time.time())))
    nid = cur.lastrowid
    con.executemany("INSERT INTO post_empfaenger (nachricht_id, konto_id, adresse) VALUES (?,?,?)", [(nid, kid, adr) for kid, adr in empf])
    con.commit()
    for kid, _adr in empf:
        if kid != k["id"] and einstellung(con, kid, "dm") == "1":
            asyncio.create_task(request.app["discord"].dm(
                kid, f"📬 Neue interne Nachricht von {absender}: „{betreff}“\n{config.SITE_URL}{BASIS}postfach/{nid}/"))
    amt._umleiten(BASIS + "postfach/gesendet/", "Nachricht gesendet.")


@mitglied
async def einstellungen(request):
    con, k = request.app["db"], request["konto"]
    adr = meine_adresse(con, k)
    alias = [r["adresse"] for r in con.execute("SELECT adresse FROM post_adressen WHERE konto_id=? AND aktuell=0 ORDER BY angelegt", (k["id"],))]
    ic_name = _ic_name(con, k["id"])
    inst = institution(k["rollen"])[1]
    konto = amt.daten_tabelle([("Discord-Name", esc(k["name"])), ("Name (IC)", esc(ic_name or "– (noch keine Bürgerakte)")),
                               ("Institution", esc(inst)), ("E-Mail-Adresse", f"<b>{esc(adr or '–')}</b>"),
                               ("Frühere Adressen (weiter zustellbar)", esc(", ".join(alias) or "–"))])
    inhalt = (f'<h1>{amt.ic("sliders-horizontal")} Einstellungen</h1><p class="az">Persönliche Einstellungen</p>{amt.meldung(request)}'
              f'<h2>Konto</h2>{konto}'
              f'<p class="az">Die Adresse folgt deinem IC-Namen (sonst dem Discord-Namen) und deiner Institution: Initial des Vornamens, Nachname, @Institution.ig.</p>'
              f'<h2>Darstellung</h2><div id="design"><style>#design label{{font-size:15px;color:inherit;margin:6px 0}}</style><label><input type="radio" name="modus" value="auto"> Automatisch (Minimalistisch)</label>'
              f'<label><input type="radio" name="modus" value="std"> Standard</label>'
              f'<label><input type="radio" name="modus" value="min"> Minimalistisch</label></div>'
              f'<p class="az">Gilt für diesen Browser.</p>'
              f'<form method="post" action="{BASIS}einstellungen/speichern">{amt.csrf_feld(request)}<h2>Postfach</h2>'
              f'<div><label for="sig">Signatur (wird unter neue Nachrichten gesetzt)</label>'
              f'<textarea id="sig" name="signatur" maxlength="300" style="min-height:70px">{esc(einstellung(con, k["id"], "signatur"))}</textarea></div>'
              f'<p><label style="display:inline"><input type="checkbox" name="dm" value="1"{" checked" if einstellung(con, k["id"], "dm") == "1" else ""}> '
              f'Bei neuen Nachrichten per Discord-Direktnachricht benachrichtigen</label></p>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button></div></form>'
              '<script>(function(){var m;try{m=localStorage.getItem("amtModus")}catch(e){}if(m!=="min"&&m!=="std")m="auto";'
              'document.querySelectorAll("#design input").forEach(function(i){i.checked=i.value===m;i.addEventListener("change",function(){'
              'var v=i.value;try{if(v==="auto")localStorage.removeItem("amtModus");else localStorage.setItem("amtModus",v)}catch(e){}'
              'document.documentElement.className=v==="std"?"std":"min"})})})()</script>')
    return _ant(request, "Einstellungen", "einstellungen", inhalt)


async def einstellungen_speichern(request):
    k, form = await _form(request)
    con = request.app["db"]
    einstellung_setzen(con, k["id"], "signatur", str(form.get("signatur", "")).replace("\r\n", "\n").strip()[:300])
    einstellung_setzen(con, k["id"], "dm", "1" if form.get("dm") == "1" else "0")
    con.commit()
    amt._umleiten(BASIS + "einstellungen/", "Einstellungen gespeichert.")


def registrieren(app):
    global CON
    CON = app["db"]
    einrichten(CON)
    app.on_startup.append(_start)
    app.on_cleanup.append(_stop)
    r = app.router
    r.add_get(BASIS + "postfach/", eingang)
    r.add_get(BASIS + "postfach/gesendet/", gesendet)
    r.add_get(BASIS + "postfach/neu/", neu)
    r.add_post(BASIS + "postfach/senden", senden)
    r.add_get(BASIS + "postfach/{id}/", lesen)
    r.add_post(BASIS + "postfach/{id}/loeschen", loeschen)
    r.add_get(BASIS + "einstellungen/", einstellungen)
    r.add_post(BASIS + "einstellungen/speichern", einstellungen_speichern)
