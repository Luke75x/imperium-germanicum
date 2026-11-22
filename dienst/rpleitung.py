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
from urllib.parse import quote

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark, nummer_anzeige

esc = amt.esc
PFAD = sa.PFAD + "rp/"
# Lucide-Icons (ISC-Lizenz) für die Maßnahmen
amt.ICONS.setdefault("rotate-ccw", '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>')
amt.ICONS.setdefault("hand-coins", '<path d="M11 15h2a2 2 0 1 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 17"/>'
                     '<path d="m7 21 1.6-1.4c.3-.4.8-.6 1.4-.6h4c1.1 0 2.1-.4 2.8-1.2l4.6-4.4a2 2 0 0 0-2.75-2.91l-4.2 3.9"/>'
                     '<path d="m2 16 6 6"/><circle cx="16" cy="9" r="2.9"/><circle cx="6" cy="5" r="3"/>')
amt.ICONS.setdefault("sticky-note", '<path d="M16 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8Z"/><path d="M15 3v4a2 2 0 0 0 2 2h4"/>')
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
CREATE TABLE IF NOT EXISTS rp_beteiligte (
    fall_id INTEGER NOT NULL, konto_id INTEGER NOT NULL, seit INTEGER NOT NULL, PRIMARY KEY (fall_id, konto_id));
"""

CSS = """<style>
.rp-kzl>div{position:relative}
.rp-kzl>div:has(a):hover{border-color:var(--ink);background:var(--hell)}
.rp-kzl a{color:inherit;text-decoration:none}
.rp-kzl a::after{content:"";position:absolute;inset:0;border-radius:inherit}
.rp-kzl a .icon{width:14px;height:14px;vertical-align:-2px;margin-left:4px;opacity:.55}
.rp-chips{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 10px}
.rp-chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--linie);border-radius:999px;padding:4px 12px;font-size:13.5px;background:#fff;color:var(--ink);text-decoration:none;cursor:pointer;font:inherit;font-size:13.5px}
.rp-chip:hover{border-color:var(--ink)}
.rp-chip.aktiv{background:var(--ink);color:#fff;border-color:var(--ink)}
.rp-chip img{height:18px;width:auto}
.rp-chip form{display:inline;margin:0}
.rp-chip .rp-weg{border:0;background:none;padding:0 0 0 2px;cursor:pointer;color:var(--grau);font-size:15px;line-height:1}
.rp-chip .rp-weg:hover{color:var(--rot)}
.rp-fuell{display:flex;flex-wrap:wrap;gap:5px;margin:4px 0 0}
.rp-fuell button{border:1px dashed var(--linie);border-radius:999px;background:#fff;padding:2px 10px;font-size:12.5px;cursor:pointer;color:var(--grau)}
.rp-fuell button:hover{border-color:var(--ink);color:var(--ink)}
.rp-massnahme{border:1px solid var(--linie);border-radius:14px;padding:14px 16px;margin:12px 0 18px}
.rp-massnahme .sa-leiste{margin:0 0 10px}
.rp-knoepfe{display:flex;flex-wrap:wrap;gap:8px}
.rp-knoepfe .btn .icon{margin-right:6px}
.rp-filter{display:flex;flex-wrap:wrap;gap:8px;align-items:end;margin:10px 0 14px}
.rp-filter>div{display:flex;flex-direction:column;gap:3px}
.rp-seiten{display:flex;gap:10px;align-items:center;margin:12px 0}
button.rp-storno{border:1px solid var(--linie);border-radius:999px;background:#fff;padding:2px 10px;font-size:12.5px;cursor:pointer;white-space:nowrap}
button.rp-storno:hover{border-color:var(--rot);color:var(--rot)}
</style>"""

FUELL_JS = """<script>document.addEventListener("click",function(e){var b=e.target.closest(".rp-fuell button");if(!b)return;e.preventDefault();
var i=document.getElementById(b.getAttribute("data-feld"));if(i){i.value=b.getAttribute("data-wert");i.dispatchEvent(new Event("input"))}});
(function(){var f=document.getElementById("rp-mfall"),t=document.getElementById("rp-mtitel");if(!f||!t)return;function u(){t.hidden=f.value!=="neu"}f.onchange=u;u()})();</script>"""

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


def konto_feld(fid, name, bez, wert="", pflicht=True, vorschlaege=()):
    """Eingabefeld für ein Konto; vorschlaege = [(Kennung, Anzeigename)] (die Beteiligten des Falls) als Knöpfe zum Einsetzen."""
    fuell = ""
    if vorschlaege:
        fuell = '<div class="rp-fuell">' + "".join(f'<button type="button" data-feld="{fid}" data-wert="{esc(w)}">{esc(n)}</button>' for w, n in vorschlaege) + "</div>"
    return (f'<div><label for="{fid}">{esc(bez)}</label><input type="text" id="{fid}" name="{name}" list="rp-konten" autocomplete="off"'
            f'{" required" if pflicht else ""} value="{esc(wert)}" placeholder="Name, Kontonummer oder Discord-ID">{fuell}</div>')


def kennung(con, r):
    """Eindeutige Eingabe für ein Konto: der Name, wenn er nur einmal vorkommt, sonst die Kontonummer."""
    n = con.execute("SELECT COUNT(*) n FROM gk_konten WHERE lower(name)=lower(?)", (r["name"],)).fetchone()["n"]
    return r["name"] if n == 1 else nummer_anzeige(r["nummer"])


def beteiligen(con, fid, r):
    """Konto als Beteiligten des Falls vermerken (Sonderkonten wie Zentralbank und Reichskasse nicht)."""
    if fid and r and r["art"] != "sonder":
        con.execute("INSERT OR IGNORE INTO rp_beteiligte (fall_id, konto_id, seit) VALUES (?,?,?)", (fid, r["id"], int(time.time())))


def beteiligte(con, fid):
    return con.execute("SELECT k.* FROM rp_beteiligte b JOIN gk_konten k ON k.id=b.konto_id WHERE b.fall_id=? ORDER BY b.seit", (fid,)).fetchall()


def konto_symbol(r, hoehe=18):
    """Wappen bei Kassen eines Teilstaats (ts-/vt-), sonst ein Icon nach Kontoart."""
    import wappen
    w = wappen.kasse(r, hoehe)
    if w:
        return w
    return amt.ic({"privat": "user", "gewerbe": "store"}.get(r["art"], "landmark"))


def stornierte(con):
    """Nummern aller bereits stornierten Buchungen."""
    import re
    return {int(m.group(1)) for (t,) in con.execute("SELECT text FROM rp_aktionen WHERE art='storno'") for m in [re.match(r"Storno der Buchung #(\d+):", t)] if m}


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
        beteiligen(con, fid, opfer)
        beteiligen(con, fid, ziel)
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
        beteiligen(con, fid, r)
        beteiligen(con, fid, ziel)
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
        beteiligen(con, fid, r)
        beteiligen(con, fid, quelle)
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
        for x in ziele:
            beteiligen(con, fid, x)
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
                beteiligen(con, fid, geld.konto(con, i))
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
    return f'{CSS}<h1>{amt.ic(icon)} {esc(titel)}</h1>{amt.meldung(request)}{zusatz}'


def _aktionsliste(con, fall_id=None, limit=100):
    wo, arg = ("WHERE fall_id=?", (fall_id,)) if fall_id else ("", ())
    rows = con.execute(f"SELECT * FROM rp_aktionen {wo} ORDER BY id DESC LIMIT {int(limit)}", arg).fetchall()
    out = []
    for a in rows:
        b = f' <span class="az">· <a href="{PFAD}buchung/{a["buchung_id"]}/">Buchung #{a["buchung_id"]}</a></span>' if a["buchung_id"] else ""
        fall = f'<a href="{PFAD}fall/{a["fall_id"]}/">Fall&nbsp;{a["fall_id"]}</a>' if a["fall_id"] and not fall_id else ("–" if not fall_id else None)
        z = [amt._zeit(a["zeit"]), esc(AKTIONEN.get(a["art"], a["art"])), esc(a["text"]) + b, esc(a["autor_name"])]
        if fall_id is None:
            z.insert(1, fall)
        out.append(z)
    return out


def _konto_link(r):
    return f'<a href="{PFAD}konto/{r["id"]}/">{konto_symbol(r)}{esc(r["name"])}</a>'


# Filterlisten der Kontensuche (Kacheln im Lagebild führen hierher)
FILTER = {"gesperrt": "Gesperrte Konten", "minus": "Kassen im Minus", "karten": "Gesperrte Bankkarten", "notlage": "Haushaltsnotlagen"}


def _filter_konten(con, f):
    """[(Konto, Zusatztext)] zum Filter."""
    import notlage
    if f == "gesperrt":
        return [(r, r["sperrgrund"] or "ohne Angabe") for r in con.execute("SELECT * FROM gk_konten WHERE gesperrt=1 ORDER BY art, name")]
    if f == "minus":
        return [(r, "") for r in con.execute("SELECT * FROM gk_konten WHERE saldo<0 AND stelle NOT IN ('zentralbank','volkswirtschaft') ORDER BY saldo")]
    if f == "karten":
        out = []
        for c in con.execute("SELECT * FROM bk_karten WHERE status='gesperrt' ORDER BY id DESC"):
            r = con.execute("SELECT * FROM gk_konten WHERE inhaber_id=? AND art='privat' ORDER BY id LIMIT 1", (c["konto_id"],)).fetchone()
            if r:
                out.append((r, f'Karte …{c["nummer"][-4:]}' + (f' · {c["sperrgrund"]}' if c["sperrgrund"] else "")))
        return out
    if f == "notlage":
        out = []
        for r in con.execute("SELECT * FROM gk_konten WHERE art IN ('teilstaat','verteidigung','behoerde') ORDER BY name"):
            n = notlage.offener_fall(con, r["id"])
            if n:
                out.append((r, f'Notlage seit {amt._zeit(n["seit"])}, Stufe {n["stufe"]}'))
        return out
    return []


@sa.seite("rp")
async def lagebild(request, k):
    con = request.app["db"]
    summe = con.execute("SELECT COALESCE(SUM(saldo),0) s FROM gk_konten").fetchone()["s"]
    offen = con.execute("SELECT COUNT(*) n FROM rp_faelle WHERE status='offen'").fetchone()["n"]
    pfeil = amt.ic("chevron-right")
    kz = [(mark(geld.geldmenge(con)), "Geldmenge", sa.PFAD + "amt/geldpolitik/"), ("stimmig" if summe == 0 else mark(summe), "Summenprobe (alle Salden)", None),
          (str(offen), "Offene Fälle", PFAD + "faelle/")]
    kz += [(str(len(_filter_konten(con, f))), t, f"{PFAD}konten/?filter={f}") for f, t in FILTER.items()]
    kacheln = "".join(f'<div><b>{esc(v)}</b>' + (f'<a href="{u}">{esc(t)}{pfeil}</a>' if u else esc(t)) + '</div>' for v, t, u in kz)
    seit = int(time.time()) - 7 * 86400
    gross = con.execute("SELECT * FROM gk_buchungen WHERE art='ueberweisung' AND zeit>=? ORDER BY betrag DESC LIMIT 8", (seit,)).fetchall()
    storniert = stornierte(con)

    def nm(i):
        r = geld.konto(con, i) if i else None
        return _konto_link(r) if r else "–"
    gz = [(amt._zeit(b["zeit"]), f'<a href="{PFAD}buchung/{b["id"]}/">#{b["id"]}</a>', nm(b["von"]), nm(b["an"]), esc(b["zweck"]),
           f'<span class="sa-betrag">{mark(b["betrag"])}</span>',
           amt.status_marke("ok", "storniert") if b["id"] in storniert else f'<a class="rp-chip" href="{PFAD}buchung/{b["id"]}/">{amt.ic("rotate-ccw")}Storno</a>')
          for b in gross]
    neu = con.execute("SELECT * FROM gk_konten WHERE art IN ('privat','gewerbe') AND eroeffnet>=? ORDER BY id DESC LIMIT 8", (seit,)).fetchall()
    nz = [(amt._zeit(r["eroeffnet"]), _konto_link(r), esc(geld.art_name(r)), mark(r["saldo"])) for r in neu]
    faelle = con.execute("SELECT * FROM rp_faelle WHERE status='offen' ORDER BY id DESC LIMIT 6").fetchall()
    fz = [(f'<a href="{PFAD}fall/{f["id"]}/">{esc(f["titel"])}</a>', amt._zeit(f["erstellt"]), esc(f["autor_name"])) for f in faelle]
    inhalt = (_kopf(request, "RP-Leitung · Lagebild", "layout-dashboard",
                    '<p class="az">Eingriffe der Server- und RP-Leitung in das Geldsystem. Alles wird doppelt gebucht und protokolliert.</p>')
              + f'<div class="kennzahlen rp-kzl">{kacheln}</div>'
              + f'<div class="aktionen"><a class="btn" href="{PFAD}faelle/#neu">{amt.ic("folder-open")}Neuen Fall eröffnen</a>'
                f'<a class="btn zweit" href="{PFAD}konten/">{amt.ic("search")}Konto suchen</a></div>'
              + '<h2>Offene Fälle</h2>' + amt.tabelle(["Fall", "Eröffnet", "Von"], fz, "Keine offenen Fälle.")
              + '<h2>Größte Überweisungen der letzten 7 Tage</h2>'
              + amt.tabelle(["Zeit", "Nr.", "Von", "An", "Zweck", "Betrag", ""], gz, "Keine Überweisungen.")
              + '<h2>Neue Konten (7 Tage)</h2>' + amt.tabelle(["Eröffnet", "Konto", "Art", "Saldo"], nz, "Keine neuen Konten.")
              + '<h2>Letzte Aktionen</h2>' + amt.tabelle(["Zeit", "Fall", "Aktion", "Einzelheiten", "Von"], _aktionsliste(con, None, 8), "Noch keine Aktionen.")
              + f'<p class="az"><a href="{PFAD}protokoll/">Vollständiges Protokoll</a></p>')
    return sa.ant(request, k, "RP-Leitung", "sa-rp", inhalt)


@sa.seite("rp")
async def faelle(request, k):
    con = request.app["db"]
    alle = request.query.get("alle")
    rows = con.execute("SELECT * FROM rp_faelle " + ("" if alle else "WHERE status='offen' ") + "ORDER BY id DESC LIMIT 200").fetchall()
    zeilen = [(f'<a href="{PFAD}fall/{f["id"]}/">{esc(f["titel"])}</a>', amt.status_marke("offen" if f["status"] == "offen" else "ok",
                                                                                           "Offen" if f["status"] == "offen" else "Abgeschlossen"),
               ", ".join(esc(b["name"]) for b in beteiligte(con, f["id"])[:4]) or "–",
               amt._zeit(f["erstellt"]), esc(f["autor_name"])) for f in rows]
    inhalt = (_kopf(request, "Fälle", "folder-open")
              + amt.tabelle(["Fall", "Stand", "Beteiligte", "Eröffnet", "Von"], zeilen, "Keine Fälle.")
              + f'<p class="az"><a href="{PFAD}faelle/{"" if alle else "?alle=1"}">{"Nur offene Fälle" if alle else "Auch abgeschlossene Fälle anzeigen"}</a></p>'
              + f'<h2 id="neu">Neuen Fall eröffnen</h2><form class="sa-formular" method="post" action="{PFAD}fall/neu">{amt.csrf_feld(request)}'
                '<div><label for="t">Titel</label><input type="text" id="t" name="titel" required maxlength="120" placeholder="z. B. Überfall auf die Reichsbank"></div>'
                '<div><label for="b">Beschreibung</label><textarea id="b" name="beschreibung" rows="4" maxlength="2000"></textarea></div>'
                f'{konto_liste(con)}{konto_feld("nb", "konto", "Beteiligtes Konto (optional)", pflicht=False)}'
                f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Fall eröffnen</button></div></form>')
    return sa.ant(request, k, "Fälle", "sa-rp-faelle", inhalt)


def _fall_anlegen(con, k, titel, beschreibung="", konto=None):
    cur = con.execute("INSERT INTO rp_faelle (titel, beschreibung, erstellt, autor_id, autor_name) VALUES (?,?,?,?,?)",
                      (titel, beschreibung[:2000].strip(), int(time.time()), k["id"], k["name"]))
    aktion_schreiben(con, k, cur.lastrowid, "eroeffnet", titel)
    beteiligen(con, cur.lastrowid, konto)
    return cur.lastrowid


async def fall_neu(request):
    k = await anmeldung.konto(request)
    if not ist_rp(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    titel = sa._f(form, "titel", 120)
    if not titel:
        sa.weiter(PFAD + "faelle/", "Bitte einen Titel angeben.", True)
    r = None
    if str(form.get("konto", "")).strip():
        try:
            r = konto_finden(con, form.get("konto"))
        except geld.Fehler as e:
            sa.weiter(PFAD + "faelle/", str(e), True)
    fid = _fall_anlegen(con, k, titel, str(form.get("beschreibung", "")), r)
    con.commit()
    sa.weiter(f"{PFAD}fall/{fid}/", "Fall eröffnet.")


# Hauptfeld jeder Maßnahme (wird aus ?konto= vorausgefüllt)
HAUPTFELD = {"raub": "r1", "einziehen": "e1", "rueckgabe": "g1", "strafe": "s1", "sperren": "k1", "freigeben": "f1"}


def _formulare(request, con, fid, abgeschlossen, vor=None, bet=()):
    """Maßnahmen des Falls; vor = {"konto": Kennung, "aktion": art, "buchung": Nr.}: Hauptfeld vorausfüllen, passende Maßnahme aufklappen."""
    vor = vor or {}
    c = amt.csrf_feld(request)
    act = f'{PFAD}fall/{fid}/aktion'
    vs = [(kennung(con, b), b["name"]) for b in bet]
    mit = ('<div><label>Mitteilung an den Betroffenen (optional, per DM)</label><input type="text" name="mitteilung" maxlength="400" '
           'placeholder="z. B. Dein Konto wurde wegen eines Vorfalls gesperrt."></div>')

    def kf(fid_, name, bez, pflicht=True, art=""):
        wert = vor.get("konto", "") if HAUPTFELD.get(art) == fid_ else ""
        return konto_feld(fid_, name, bez, wert, pflicht, vs)

    def box(titel, hilfe, felder, knopf, art, gefahr=False, symbol="check"):
        auf = " open" if vor.get("aktion") == art else ""
        return (f'<details class="sa-auf" id="m-{art}"{auf}><summary>{amt.ic(symbol)}{esc(titel)}</summary><form class="sa-formular" method="post" action="{act}">{c}'
                f'<input type="hidden" name="aktion" value="{art}"><p class="sa-hinweis">{esc(hilfe)}</p>{felder}{mit if art != "notiz" else ""}'
                f'<div class="aktionen"><button class="btn{" zweit gefahr" if gefahr else ""}" type="submit">{esc(knopf)}</button></div></form></details>')
    betrag = '<div><label>Betrag in Kronen</label><input type="text" name="betrag" inputmode="decimal"></div>'
    alles = '<label class="sa-haken"><input type="checkbox" name="alles" value="1"> gesamtes Guthaben</label>'
    grund = lambda v: f'<div><label>Grund / Verwendungszweck</label><input type="text" name="grund" maxlength="160" placeholder="{esc(v)}"></div>'
    minus = '<label class="sa-haken"><input type="checkbox" name="minus" value="1"> Konto darf dabei ins Minus gehen</label>'
    out = [
        box("Raub / Diebstahl buchen", "Geld wechselt gegen den Willen des Opfers den Besitzer. Ohne Täterkonto verlässt die Beute den Umlauf (Zentralbank).",
            kf("r1", "opfer", "Opfer (Konto der Bank, Kasse, Person …)", art="raub") + kf("r2", "ziel", "Täter (Konto, leer = Beute außer Landes)", pflicht=False)
            + betrag + alles, "Raub buchen", "raub", True, "hand-coins"),
        box("Beschlagnahme", "Zieht Geld ein – standardmäßig an die Reichskasse, sonst an ein Konto (z. B. Rückgabe an das Opfer).",
            kf("e1", "konto", "Konto, von dem eingezogen wird", art="einziehen") + kf("e2", "ziel_konto", "Empfänger (leer = Reichskasse)", pflicht=False)
            + betrag + alles + grund("Beschlagnahme") + minus, "Einziehen", "einziehen", True, "gavel"),
        box("Rückgabe / Entschädigung", "Zahlt Geld auf ein Konto – aus der Reichskasse, per Geldschöpfung oder von einem anderen Konto.",
            kf("g1", "konto", "Empfänger", art="rueckgabe") + betrag
            + '<div><label>Quelle</label><select name="quelle"><option value="reichskasse">Reichskasse</option>'
              '<option value="zentralbank">Zentralbank (Geldschöpfung)</option><option value="konto">Anderes Konto …</option></select></div>'
            + kf("g2", "quelle_konto", "Quellkonto (nur bei „Anderes Konto“)", pflicht=False) + grund("Entschädigung"), "Auszahlen", "rueckgabe", symbol="undo-2"),
        box("Geldstrafe", "Bußgeld zugunsten der Reichskasse (oder eines Kontos).",
            kf("s1", "konto", "Konto des Schuldigen", art="strafe") + kf("s2", "ziel_konto", "Empfänger (leer = Reichskasse)", pflicht=False)
            + betrag + alles + grund("Geldstrafe") + minus, "Strafe buchen", "strafe", True, "scale"),
        box("Konto sperren", "Gesperrte Konten können keine Überweisungen, Steuern oder Gebühren auslösen; Gutschriften sind weiter möglich.",
            kf("k1", "konto", "Konto", art="sperren") + grund("Ermittlungen der RP-Leitung")
            + '<label class="sa-haken"><input type="checkbox" name="person" value="1" checked> alle Konten der Person (Privat und Gewerbe)</label>'
            + '<label class="sa-haken"><input type="checkbox" name="karte" value="1" checked> Bankkarte mitsperren</label>', "Sperren", "sperren", True, "lock"),
        box("Konto freigeben", "Hebt die Sperre auf (auf Wunsch samt Bankkarte).", kf("f1", "konto", "Konto", art="freigeben")
            + '<label class="sa-haken"><input type="checkbox" name="person" value="1" checked> alle Konten der Person</label>'
            + '<label class="sa-haken"><input type="checkbox" name="karte" value="1" checked> Bankkarte freigeben</label>', "Freigeben", "freigeben", symbol="lock-open"),
        box("Buchung stornieren", "Bucht eine einzelne Buchung vollständig zurück. Jede Buchung nur einmal. Schneller: auf der Kontoseite „Storno“ in der Umsatzzeile.",
            f'<div><label>Nummer der Buchung</label><input type="text" name="buchung" required inputmode="numeric" placeholder="z. B. 1234" value="{esc(vor.get("buchung", ""))}"></div>'
            + grund("Storno"), "Stornieren", "storno", True, "rotate-ccw"),
        box("Notiz", "Hält etwas im Verlauf des Falls fest.", '<div><label>Text</label><textarea name="text" rows="3" maxlength="500" required></textarea></div>',
            "Speichern", "notiz", symbol="sticky-note"),
    ]
    return "".join(out)


def _beteiligte_html(request, con, f, bet):
    c = amt.csrf_feld(request)
    act = f'{PFAD}fall/{f["id"]}/beteiligte'
    chips = "".join(f'<span class="rp-chip"><a href="{PFAD}konto/{b["id"]}/">{konto_symbol(b)}{esc(b["name"])}</a>'
                    f'<form method="post" action="{act}">{c}<input type="hidden" name="weg" value="{b["id"]}">'
                    f'<button class="rp-weg" type="submit" title="Aus dem Fall entfernen" aria-label="{esc(b["name"])} aus dem Fall entfernen">×</button></form></span>' for b in bet)
    neu = (f'<details class="sa-auf"><summary>{amt.ic("plus")}Beteiligtes Konto hinzufügen</summary><form class="sa-leiste" method="post" action="{act}">{c}'
           f'{konto_feld("bt", "konto", "Konto")}<button class="btn zweit" type="submit">Hinzufügen</button></form></details>')
    return ('<h2>Beteiligte</h2><p class="az">Konten dieses Falls. Sie stehen in jeder Maßnahme als Vorschlag zum Einsetzen bereit; '
            'jede Maßnahme fügt die betroffenen Konten selbst hinzu.</p>'
            + (f'<div class="rp-chips">{chips}</div>' if bet else '<p class="leer">Noch keine Beteiligten.</p>') + neu)


@sa.seite("rp")
async def fall(request, k):
    con = request.app["db"]
    i = request.match_info["id"]
    f = con.execute("SELECT * FROM rp_faelle WHERE id=?", (int(i),)).fetchone() if i.isdigit() else None
    if not f:
        raise web.HTTPNotFound(text="Fall nicht gefunden.")
    offen = f["status"] == "offen"
    bet = beteiligte(con, f["id"])
    q = request.query
    vor = {"aktion": q.get("aktion", ""), "buchung": q.get("buchung", "") if q.get("buchung", "").isdigit() else ""}
    r = geld.konto(con, int(q["konto"])) if q.get("konto", "").isdigit() else (bet[0] if len(bet) == 1 else None)
    if r:
        vor["konto"] = kennung(con, r)
    inhalt = (_kopf(request, f["titel"], "folder-open")
              + amt.daten_tabelle([("Stand", amt.status_marke("offen" if offen else "ok", "Offen" if offen else "Abgeschlossen")),
                                   ("Eröffnet", f'{amt._zeit(f["erstellt"])} von {esc(f["autor_name"])}'),
                                   ("Beschreibung", esc(f["beschreibung"]).replace("\n", "<br>") or "–")])
              + _beteiligte_html(request, con, f, bet)
              + f'<h2>Maßnahmen</h2>{konto_liste(con)}{_formulare(request, con, f["id"], not offen, vor, bet)}'
              + f'<form method="post" action="{PFAD}fall/{f["id"]}/status" style="margin-top:14px">{amt.csrf_feld(request)}'
                f'<button class="btn zweit" type="submit">{amt.ic("check")}{"Fall abschließen" if offen else "Fall wieder öffnen"}</button></form>'
              + '<h2>Verlauf</h2>' + amt.tabelle(["Zeit", "Aktion", "Einzelheiten", "Von"], _aktionsliste(con, f["id"]), "Noch kein Verlauf.")
              + FUELL_JS)
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


async def fall_beteiligte(request):
    k, form, con, f = await _post(request)
    pfad = f"{PFAD}fall/{f['id']}/"
    weg = str(form.get("weg", ""))
    if weg.isdigit():
        con.execute("DELETE FROM rp_beteiligte WHERE fall_id=? AND konto_id=?", (f["id"], int(weg)))
        con.commit()
        sa.weiter(pfad, "Aus dem Fall entfernt.")
    try:
        r = konto_finden(con, form.get("konto"))
    except geld.Fehler as e:
        sa.weiter(pfad, str(e), True)
    if r["art"] == "sonder":
        sa.weiter(pfad, "Sonderkonten werden nicht als Beteiligte geführt.", True)
    beteiligen(con, f["id"], r)
    con.commit()
    sa.weiter(pfad, f'{r["name"]} ist jetzt beteiligt.')


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
    filt = request.query.get("filter", "")
    filt = filt if filt in FILTER else ""
    chips = '<div class="rp-chips">' + "".join(f'<a class="rp-chip{" aktiv" if f == filt else ""}" href="{PFAD}konten/{"" if f == filt else "?filter=" + f}">{esc(t)}</a>'
                                               for f, t in FILTER.items()) + "</div>"

    def zeile(r, zusatz=""):
        return (_konto_link(r), esc(geld.art_name(r)), f'<span class="sa-nr">{nummer_anzeige(r["nummer"])}</span>', sa.betrag_html(r["saldo"], False),
                (amt.status_marke("nein", "Gesperrt") if r["gesperrt"] else amt.status_marke("ok", "Aktiv")) + (f' <span class="az">{esc(zusatz)}</span>' if zusatz else ""))
    ergebnis = ""
    if filt:
        zeilen = [zeile(r, z) for r, z in _filter_konten(con, filt)]
        ergebnis = f'<h2>{esc(FILTER[filt])}</h2>' + amt.tabelle(["Konto", "Art", "Nummer", "Saldo", "Stand"], zeilen, "Keine Einträge.")
    elif q:
        n = geld.nummer_gueltig(q)
        rows = con.execute("SELECT * FROM gk_konten WHERE nummer=? OR inhaber_id=? OR lower(name) LIKE lower(?) OR lower(stelle)=lower(?) ORDER BY art, name LIMIT 60",
                           (n or "", q, f"%{q}%", q)).fetchall()
        ergebnis = amt.tabelle(["Konto", "Art", "Nummer", "Saldo", "Stand"], [zeile(r) for r in rows], "Kein Konto gefunden.")
    inhalt = (_kopf(request, "Konten & Personen", "search")
              + f'<form class="sa-leiste" method="get" action="{PFAD}konten/"><div><label for="q">Name, Kontonummer oder Discord-ID</label>'
                f'<input type="text" id="q" name="q" value="{esc(q)}"{"" if filt else " autofocus"}></div><button class="btn" type="submit">{amt.ic("search")}Suchen</button></form>'
              + chips + ergebnis)
    return sa.ant(request, k, "Konten & Personen", "sa-rp-konten", inhalt)


def _massnahme_form(request, con, r, knoepfe, extra=""):
    """Formular „Maßnahme“: Fall wählen (oder neu) und Knopf der Maßnahme drücken → Fall mit vorausgefülltem Konto."""
    offen = con.execute("SELECT id, titel FROM rp_faelle WHERE status='offen' ORDER BY id DESC LIMIT 30").fetchall()
    eigene = {x["fall_id"] for x in con.execute("SELECT fall_id FROM rp_beteiligte WHERE konto_id=?", (r["id"],))} if r else set()
    offen = sorted(offen, key=lambda f: (f["id"] not in eigene, -f["id"]))
    opts = "".join(f'<option value="{f["id"]}">{esc(f["titel"])}{" · beteiligt" if f["id"] in eigene else ""}</option>' for f in offen)
    opts += '<option value="neu">+ Neuer Fall …</option>'
    vorgabe = f'RP-Ereignis: {r["name"]}' if r else "RP-Ereignis"
    ziel = f'{PFAD}konto/{r["id"]}/fall' if r else f'{PFAD}massnahme'
    return (f'<form class="rp-massnahme" id="rp-massnahme" method="post" action="{ziel}">{amt.csrf_feld(request)}{extra}'
            f'<div class="sa-leiste"><div><label for="rp-mfall">Im Rahmen von Fall</label><select id="rp-mfall" name="fall">{opts}</select></div>'
            f'<div id="rp-mtitel"><label for="rp-mt">Titel des neuen Falls</label><input type="text" id="rp-mt" name="titel" maxlength="120" placeholder="{esc(vorgabe)}"></div></div>'
            f'<div class="rp-knoepfe">{knoepfe}</div></form>')


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
        andere = [x for x in konten_der_person(con, r) if x["id"] != r["id"]]
        if andere:
            info.append(("Weitere Konten", " · ".join(_konto_link(x) for x in andere)))
    fl = con.execute("SELECT f.* FROM rp_beteiligte b JOIN rp_faelle f ON f.id=b.fall_id WHERE b.konto_id=? ORDER BY f.id DESC", (r["id"],)).fetchall()
    if fl:
        info.append(("Fälle", " · ".join(f'<a href="{PFAD}fall/{f["id"]}/">{esc(f["titel"])}</a>' + ("" if f["status"] == "offen" else " (abgeschlossen)") for f in fl)))
    sperr = ("freigeben", "lock-open", "Freigeben") if r["gesperrt"] else ("sperren", "lock", "Sperren")
    kn = [("einziehen", "gavel", "Beschlagnahme"), ("strafe", "scale", "Geldstrafe"), ("raub", "hand-coins", "Raub (als Opfer)"),
          ("rueckgabe", "undo-2", "Rückgabe / Entschädigung"), sperr, ("notiz", "sticky-note", "Nur in den Fall aufnehmen")]
    knoepfe = "".join(f'<button class="btn zweit" type="submit" name="aktion" value="{a}">{amt.ic(s)}{esc(t)}</button>' for a, s, t in kn)
    massnahme = '<h2>Maßnahme</h2>' + _massnahme_form(request, con, r, knoepfe)
    bs = sa.umsaetze(con, r["id"], 100)
    storniert = stornierte(con)

    def storno(b):
        if b["id"] in storniert:
            return amt.status_marke("ok", "storniert")
        return f'<button class="rp-storno" type="submit" form="rp-massnahme" name="storno" value="{b["id"]}" title="Diese Buchung im gewählten Fall stornieren">Storno</button>'
    zeilen = [(f'<a href="{PFAD}buchung/{b["id"]}/">#{b["id"]}</a>',) + z + (storno(b),) for b, z in zip(bs, sa.umsatz_zeilen(con, r["id"], bs, False))]
    inhalt = (_kopf(request, r["name"], "search") + amt.daten_tabelle(info) + massnahme
              + '<h2>Umsätze</h2><p class="az">„Storno“ bucht die Zeile im oben gewählten Fall zurück (nach Bestätigung im Fall).</p>'
              + amt.tabelle(["Nr."] + sa.UMSATZ_KOPF + [""], zeilen, "Keine Umsätze.") + FUELL_JS)
    return sa.ant(request, k, r["name"], "sa-rp-konten", inhalt)


async def _massnahme_weiter(request, r):
    """Fall wählen/anlegen, Konto beteiligen und in den Fall springen (Maßnahme aufgeklappt, Konto bzw. Buchung eingesetzt)."""
    k = await anmeldung.konto(request)
    if not ist_rp(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    f = str(form.get("fall", ""))
    if f == "neu":
        titel = sa._f(form, "titel", 120) or (f'RP-Ereignis: {r["name"]}' if r else "RP-Ereignis")
        fid = _fall_anlegen(con, k, titel, "", r)
    elif f.isdigit() and con.execute("SELECT 1 FROM rp_faelle WHERE id=?", (int(f),)).fetchone():
        fid = int(f)
        beteiligen(con, fid, r)
    else:
        raise web.HTTPSeeOther(PFAD + "faelle/")
    con.commit()
    storno = str(form.get("storno", "") or form.get("buchung", ""))
    aktion = "storno" if storno.isdigit() else str(form.get("aktion", ""))
    aktion = aktion if aktion in AKTIONEN else ""
    teile = [f"konto={r['id']}"] if r else []
    if aktion:
        teile.append("aktion=" + aktion)
    if aktion == "storno":
        teile.append("buchung=" + storno)
    raise web.HTTPSeeOther(f"{PFAD}fall/{fid}/" + ("?" + "&".join(teile) if teile else "") + (f"#m-{aktion}" if aktion else ""))


async def konto_massnahme(request):
    i = request.match_info["id"]
    r = geld.konto(request.app["db"], int(i)) if i.isdigit() else None
    if not r:
        raise web.HTTPNotFound()
    await _massnahme_weiter(request, r)


async def massnahme(request):
    await _massnahme_weiter(request, None)


async def konto_zu_fall(request):
    """Ältere Verknüpfung (GET): in den Fall springen, Konto eingesetzt."""
    k = await anmeldung.konto(request)
    if not ist_rp(k):
        raise web.HTTPForbidden()
    f = request.query.get("fall", "")
    i = request.match_info["id"]
    raise web.HTTPSeeOther(f"{PFAD}fall/{int(f)}/?konto={i}" if f.isdigit() and i.isdigit() else PFAD + "faelle/")


@sa.seite("rp")
async def buchung(request, k):
    con = request.app["db"]
    i = request.match_info["id"]
    b = con.execute("SELECT * FROM gk_buchungen WHERE id=?", (int(i),)).fetchone() if i.isdigit() else None
    if not b:
        raise web.HTTPNotFound(text="Buchung nicht gefunden.")
    von, an = (geld.konto(con, x) if x else None for x in (b["von"], b["an"]))
    info = [("Nummer", f'#{b["id"]}'), ("Zeit", amt._zeit(b["zeit"])), ("Von", _konto_link(von) if von else "außerhalb"), ("An", _konto_link(an) if an else "außerhalb"),
            ("Betrag", f'<span class="sa-betrag">{mark(b["betrag"])}</span>'), ("Art", esc(geld.BUCHUNGSART.get(b["art"], b["art"]))), ("Verwendungszweck", esc(b["zweck"]) or "–")]
    if b["id"] in stornierte(con):
        aktion = '<p class="hinweis">Diese Buchung wurde bereits storniert.</p>'
    else:
        knopf = f'<button class="btn zweit gefahr" type="submit" name="storno" value="{b["id"]}">{amt.ic("rotate-ccw")}Stornieren …</button>'
        aktion = ('<h2>Stornieren</h2><p class="az">Fall wählen; dort wird die Buchung nach Prüfung zurückgebucht.</p>'
                  + _massnahme_form(request, con, von or an, knopf))
    inhalt = _kopf(request, f'Buchung #{b["id"]}', "receipt") + amt.daten_tabelle(info) + aktion + FUELL_JS
    return sa.ant(request, k, f'Buchung #{b["id"]}', "sa-rp-konten", inhalt)


# ---------------------------------------------------------------- Protokoll (gemeinsam: Fälle und Konfiguration)

KONFIG_AKTIONEN = ("Satz geändert", "Teilstaat bearbeitet", "Handel: Förderstätte angelegt", "Handel: Förderstätte gelöscht", "Handel: Förderstätte geändert",
                   "Handel: Richtpreis geändert", "Handel: Sätze geändert", "Handelssperre aufgehoben", "Handelssperre verhängt", "Besitzkatalog geändert",
                   "Besitzkatalog erweitert", "Gerätekatalog geändert", "Energie: Storno")
BEREICHE = {"": "Alles", "rp": "Fälle der RP-Leitung", "konfig": "Konfiguration", "sonst": "Übriges Geldsystem"}
JE_SEITE = 100


@sa.seite("rp")
async def protokoll(request, k):
    import re
    import handel
    con = request.app["db"]
    q = request.query
    bereich = q.get("bereich", "") if q.get("bereich", "") in BEREICHE else ""
    such = " ".join(q.get("q", "").split())[:80]
    staat = q.get("staat", "")
    tage = q.get("tage", "")
    seite_ = max(1, int(q["seite"])) if q.get("seite", "").isdigit() else 1
    staaten = handel.halter(con)
    wo, arg = [], []
    platz = ",".join("?" * len(KONFIG_AKTIONEN))
    if bereich == "rp":
        wo.append("aktion LIKE 'RP-Leitung:%'")
    elif bereich == "konfig":
        wo.append(f"aktion IN ({platz})"); arg += KONFIG_AKTIONEN
    elif bereich == "sonst":
        wo.append(f"aktion NOT LIKE 'RP-Leitung:%' AND aktion NOT IN ({platz})"); arg += KONFIG_AKTIONEN
    if such:
        wo.append("(lower(text) LIKE lower(?) OR lower(name) LIKE lower(?) OR lower(aktion) LIKE lower(?))"); arg += [f"%{such}%"] * 3
    if staat in staaten and staat != "reich":
        wo.append("lower(text) LIKE lower(?)"); arg.append(f"%{staaten[staat]}%")
    if tage.isdigit():
        wo.append("zeit>=?"); arg.append(int(time.time()) - int(tage) * 86400)
    sql = " FROM gk_protokoll" + (" WHERE " + " AND ".join(wo) if wo else "")
    gesamt = con.execute("SELECT COUNT(*) n" + sql, arg).fetchone()["n"]
    rows = con.execute("SELECT *" + sql + f" ORDER BY id DESC LIMIT {JE_SEITE} OFFSET {(seite_ - 1) * JE_SEITE}", arg).fetchall()

    def text(t):
        m = re.match(r"Fall (\d+): (.*)", t, re.S)
        h = esc(m.group(2) if m else t)
        h = re.sub(r"Buchung #(\d+)", lambda x: f'<a href="{PFAD}buchung/{x.group(1)}/">Buchung #{x.group(1)}</a>', h)
        return (f'<a href="{PFAD}fall/{m.group(1)}/">Fall {m.group(1)}</a> · ' if m else "") + h
    zeilen = [(amt._zeit(r["zeit"]), esc(r["aktion"].replace("RP-Leitung: ", "")), text(r["text"]), esc(r["name"])) for r in rows]
    sel = lambda name, opts, wert: (f'<select name="{name}" onchange="this.form.submit()">'
                                    + "".join(f'<option value="{esc(v)}"{" selected" if v == wert else ""}>{esc(t)}</option>' for v, t in opts) + "</select>")
    filt = (f'<form class="rp-filter" method="get" action="{PFAD}protokoll/">'
            f'<div><label>Bereich</label>{sel("bereich", BEREICHE.items(), bereich)}</div>'
            f'<div><label>Teilstaat</label>{sel("staat", [("", "Alle")] + [(s, n) for s, n in staaten.items() if s != "reich"], staat)}</div>'
            f'<div><label>Zeitraum</label>{sel("tage", [("", "Gesamter Zeitraum"), ("1", "Letzte 24 Stunden"), ("7", "Letzte 7 Tage"), ("30", "Letzte 30 Tage")], tage)}</div>'
            f'<div><label for="pq">Suche (Text, Person, Aktion)</label><input type="search" id="pq" name="q" value="{esc(such)}"></div>'
            f'<button class="btn zweit" type="submit">{amt.ic("search")}Filtern</button></form>')
    seiten = -(-gesamt // JE_SEITE)

    def link(n):
        p = {x: q[x] for x in ("bereich", "q", "staat", "tage") if q.get(x)}
        p["seite"] = str(n)
        return f'{PFAD}protokoll/?' + "&".join(f"{a}={quote(b)}" for a, b in p.items())
    blaettern = ""
    if seiten > 1:
        blaettern = ('<div class="rp-seiten">' + (f'<a class="btn zweit" href="{link(seite_ - 1)}">{amt.ic("arrow-left")}Neuer</a>' if seite_ > 1 else "")
                     + f'<span class="az">Seite {seite_} von {seiten} · {gesamt} Einträge</span>'
                     + (f'<a class="btn zweit" href="{link(seite_ + 1)}">Älter{amt.ic("arrow-right")}</a>' if seite_ < seiten else "") + "</div>")
    inhalt = (_kopf(request, "Protokoll", "scroll-text", '<p class="az">Alles in einer Zeitleiste: Maßnahmen in Fällen, Änderungen an der Konfiguration '
                    '(Stellschrauben, Handel, Förderstätten, Besitz, Gerätekatalog, Stammdaten der Teilstaaten) und das übrige Geldsystem. Neueste zuerst.</p>')
              + filt + amt.tabelle(["Zeit", "Aktion", "Einzelheiten", "Von"], zeilen, "Keine Einträge zu diesem Filter.") + blaettern)
    return sa.ant(request, k, "Protokoll", "sa-rp-protokoll", inhalt)


def registrieren(app):
    einrichten(app["db"])
    r = app.router
    r.add_get(PFAD, lagebild)
    r.add_get(PFAD + "faelle/", faelle)
    r.add_post(PFAD + "fall/neu", fall_neu)
    r.add_get(PFAD + "fall/{id}/", fall)
    r.add_post(PFAD + "fall/{id}/aktion", fall_aktion)
    r.add_post(PFAD + "fall/{id}/status", fall_status)
    r.add_post(PFAD + "fall/{id}/beteiligte", fall_beteiligte)
    r.add_get(PFAD + "konten/", konten)
    r.add_get(PFAD + "konto/{id}/", konto)
    r.add_get(PFAD + "konto/{id}/fall", konto_zu_fall)
    r.add_post(PFAD + "konto/{id}/fall", konto_massnahme)
    r.add_post(PFAD + "massnahme", massnahme)
    r.add_get(PFAD + "buchung/{id}/", buchung)
    r.add_get(PFAD + "protokoll/", protokoll)
