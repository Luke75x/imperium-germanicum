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
.rp-fuell{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0 10px}
.rp-fuell button{border:1px dashed var(--linie);border-radius:999px;background:#fff;padding:2px 10px;font-size:12.5px;cursor:pointer;color:var(--grau)}
.rp-fuell button:hover{border-color:var(--ink);color:var(--ink)}
.rp-massnahme{border:1px solid var(--linie);border-radius:14px;padding:14px 16px;margin:12px 0 18px}
.rp-massnahme .sa-leiste{margin:0 0 10px}
.rp-knoepfe{display:flex;flex-wrap:wrap;gap:8px}
.rp-knoepfe .rp-kachel{flex:1 1 150px;padding:10px 12px}
.rp-knoepfe .btn .icon{margin-right:6px}
.rp-filter{display:flex;flex-wrap:wrap;gap:8px;align-items:end;margin:10px 0 14px}
.rp-filter>div{display:flex;flex-direction:column;gap:3px}
.rp-seiten{display:flex;gap:10px;align-items:center;margin:12px 0}
button.rp-storno{border:1px solid var(--linie);border-radius:999px;background:#fff;padding:2px 10px;font-size:12.5px;cursor:pointer;white-space:nowrap}
button.rp-storno:hover{border-color:var(--rot);color:var(--rot)}
/* Autovervollständigung der Kontofelder */
.rp-ac-feld{position:relative}
.rp-ac{position:absolute;left:0;right:0;z-index:30;margin-top:4px;background:#fff;border:1px solid var(--linie);border-radius:12px;box-shadow:0 12px 32px #0002;overflow:hidden;max-height:300px;overflow-y:auto}
.rp-ac button{display:flex;align-items:center;gap:8px;width:100%;border:0;background:none;padding:9px 12px;text-align:left;font:inherit;font-size:14px;cursor:pointer;color:var(--ink)}
.rp-ac button small{margin-left:auto;color:var(--grau);font-size:12px;white-space:nowrap}
.rp-ac button:hover,.rp-ac button.an{background:var(--hell)}
.rp-ac img{height:18px;width:auto;max-width:18px}
/* Leitstand */
.rp-staaten{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:10px;margin:10px 0 22px}
.rp-staat{display:flex;gap:10px;align-items:center;border:1px solid var(--linie);border-radius:14px;padding:10px 12px;color:var(--ink);text-decoration:none;background:#fff;min-width:0}
.rp-staat:hover{border-color:var(--ink)}
.rp-staat img{height:36px;width:30px;object-fit:contain;flex:none}
.rp-staat b{display:block;font-size:13.5px;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rp-staat span{min-width:0}
.rp-staat.warn{border-color:var(--rot);box-shadow:inset 3px 0 0 var(--rot)}
.rp-marken{display:flex;flex-wrap:wrap;gap:4px;margin-top:3px}
.rp-marken i{font-style:normal;font-size:11px;line-height:1;padding:3px 7px;border-radius:999px;background:var(--hell);color:var(--grau)}
.rp-marken i.rot{background:#fbeaea;color:var(--rot)}
.rp-spalten{display:grid;grid-template-columns:1fr;gap:0 28px}
@media (min-width:1100px){.rp-spalten{grid-template-columns:1fr 1fr}}
.rp-spalten>section{min-width:0}
/* Wappenleiste (Die Teilstaaten) */
.rp-leiste{display:flex;gap:6px;overflow-x:auto;scrollbar-width:thin;padding:4px 2px 10px;margin:6px 0 10px;scroll-snap-type:x proximity}
.rp-leiste a{flex:none;display:flex;flex-direction:column;align-items:center;gap:4px;width:84px;padding:8px 4px;border:1px solid transparent;border-radius:12px;color:var(--grau);text-decoration:none;font-size:11.5px;line-height:1.2;text-align:center;scroll-snap-align:start}
.rp-leiste a:hover{background:var(--hell);color:var(--ink)}
.rp-leiste a.aktiv{border-color:var(--ink);color:var(--ink);font-weight:600;background:#fff}
.rp-leiste img{height:34px;width:30px;object-fit:contain}
/* Kacheln (Maßnahmen, Konfiguration) */
.rp-raster{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px;margin:10px 0 16px}
.rp-kachel{display:flex;flex-direction:column;align-items:flex-start;gap:6px;text-align:left;border:1px solid var(--linie);border-radius:14px;background:#fff;padding:14px;cursor:pointer;font:inherit;color:var(--ink);text-decoration:none;min-width:0}
.rp-kachel:hover{border-color:var(--ink)}
.rp-kachel .icon{width:22px;height:22px}
.rp-kachel b{font-size:14.5px}
.rp-kachel small{color:var(--grau);font-size:12.5px;line-height:1.35}
.rp-kachel.gefahr .icon{color:var(--rot)}
.rp-kachel[disabled]{opacity:.45;cursor:not-allowed}
/* Sheets (Dialoge) */
dialog.rp-sheet{border:0;border-radius:18px;padding:0;width:calc(100% - 32px);max-width:600px;box-shadow:0 24px 70px #0004;color:var(--ink)}
dialog.rp-sheet::backdrop{background:#0006}
.rp-sheet-kopf{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--linie)}
.rp-sheet-titel{font-size:16px;color:var(--ink);display:flex;align-items:center;gap:8px}
dialog.rp-sheet:focus,dialog.rp-sheet:focus-visible{outline:none}
.rp-sheet-inhalt{padding:12px 18px 18px;max-height:min(72vh,720px);overflow:auto}
.rp-sheet-inhalt .sa-formular{margin:0}
@media (max-width:800px){dialog.rp-sheet{margin:auto 0 0;width:100%;max-width:100%;border-radius:18px 18px 0 0;max-height:88vh}
 .rp-sheet-inhalt{max-height:calc(88vh - 60px);padding-bottom:calc(18px + env(safe-area-inset-bottom))}}
.rp-vorschau{border:1px solid var(--linie);border-radius:12px;padding:10px 14px;margin:8px 0 12px;background:var(--hell)}
</style>"""

FUELL_JS = """<script>(function(){
document.addEventListener("click",function(e){var b=e.target.closest(".rp-fuell button");if(b){e.preventDefault();
 var i=document.getElementById(b.getAttribute("data-feld"));if(i){i.value=b.getAttribute("data-wert");i.dispatchEvent(new Event("change"))}return}
 var o=e.target.closest("[data-sheet]");if(o){e.preventDefault();var d=document.getElementById(o.getAttribute("data-sheet"));if(d&&d.showModal){d.showModal();var f=d.querySelector("input:not([type=hidden]),textarea,select");if(f&&!f.value)f.focus()}return}
 var z=e.target.closest("[data-zu]");if(z){e.preventDefault();var dd=z.closest("dialog");if(dd)dd.close();return}
 if(e.target.tagName==="DIALOG"&&e.target.classList.contains("rp-sheet")){var r=e.target.getBoundingClientRect();if(e.clientY<r.top||e.clientY>r.bottom||e.clientX<r.left||e.clientX>r.right)e.target.close()}
 if(!e.target.closest(".rp-ac-feld"))document.querySelectorAll(".rp-ac").forEach(function(a){a.hidden=true})});
var h=(location.hash||"").slice(1),d=h?document.getElementById(h):null;if(d&&d.tagName==="DIALOG"&&d.showModal)d.showModal();
document.querySelectorAll("dialog[data-auf]").forEach(function(x){if(x.showModal)x.showModal()});
var f=document.getElementById("rp-mfall"),t=document.getElementById("rp-mtitel");if(f&&t){var u=function(){t.hidden=f.value!=="neu"};f.onchange=u;u()}
var T=null;
function zeige(inp){var box=inp.parentNode.querySelector(".rp-ac"),q=inp.value.trim();if(!box)return;if(q.length<2){box.hidden=true;return}
 clearTimeout(T);T=setTimeout(function(){fetch("/schatzamt/rp/konten.json?q="+encodeURIComponent(q),{credentials:"same-origin"}).then(function(r){return r.json()}).then(function(l){
  box.innerHTML="";l.forEach(function(x,n){var b=document.createElement("button");b.type="button";b.innerHTML=x.s+"<span></span><small></small>";b.querySelector("span").textContent=x.n;b.querySelector("small").textContent=x.a+" · "+x.nr;
   b.onmousedown=function(ev){ev.preventDefault();inp.value=x.w;box.hidden=true};box.appendChild(b)});box.hidden=!l.length})},140)}
document.addEventListener("input",function(e){if(e.target.classList&&e.target.classList.contains("rp-konto"))zeige(e.target)});
document.addEventListener("keydown",function(e){var inp=e.target;if(!inp.classList||!inp.classList.contains("rp-konto"))return;var box=inp.parentNode.querySelector(".rp-ac");if(!box||box.hidden)return;
 var bs=[].slice.call(box.querySelectorAll("button")),n=bs.findIndex(function(b){return b.classList.contains("an")});
 if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();if(n>=0)bs[n].classList.remove("an");n=(n+(e.key==="ArrowDown"?1:-1)+bs.length)%bs.length;bs[n].classList.add("an")}
 else if(e.key==="Enter"&&n>=0){e.preventDefault();bs[n].onmousedown(e)}else if(e.key==="Escape"){box.hidden=true}});
})();</script>"""

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
    """Früher: <datalist> mit allen Konten. Ersetzt durch die Autovervollständigung (rp/konten.json); bleibt leer, damit alte Aufrufe nichts ausgeben."""
    return ""


def _konto_liste_alt(con):
    opt = "".join(f'<option value="{esc(r["name"])}" label="{esc(geld.art_name(r))} {esc(nummer_anzeige(r["nummer"]))}">'
                  for r in con.execute("SELECT * FROM gk_konten WHERE stelle NOT IN ('zentralbank','volkswirtschaft') ORDER BY art, name"))
    return f'<datalist id="rp-konten">{opt}</datalist>'


def konto_feld(fid, name, bez, wert="", pflicht=True, vorschlaege=()):
    """Eingabefeld für ein Konto; vorschlaege = [(Kennung, Anzeigename)] (die Beteiligten des Falls) als Knöpfe zum Einsetzen."""
    fuell = ""
    if vorschlaege:
        fuell = '<div class="rp-fuell">' + "".join(f'<button type="button" data-feld="{fid}" data-wert="{esc(w)}">{esc(n)}</button>' for w, n in vorschlaege) + "</div>"
    return (f'<div class="rp-ac-feld"><label for="{fid}">{esc(bez)}</label><input type="text" id="{fid}" name="{name}" class="rp-konto" autocomplete="off" spellcheck="false"'
            f'{" required" if pflicht else ""} value="{esc(wert)}" placeholder="Name, Kontonummer oder Discord-ID"><div class="rp-ac" role="listbox" hidden></div>{fuell}</div>')


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
    if text and r["inhaber_id"] and not request.get("rp_vorschau"):
        sa.dm(request, r["inhaber_id"], text[:1500], art="rp")


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


def teilstaaten_lage(con):
    """Je Teilstaat: offene Krisen, Haushaltsnotlage, Kasse im Minus, gesperrte Kasse (für den Leitstand)."""
    import handel
    import krisen
    import notlage
    out = []
    for schl, name in handel.halter(con).items():
        if schl == "reich":
            continue
        sid = schl[3:]
        kassen = con.execute("SELECT * FROM gk_konten WHERE stelle IN (?,?)", (schl, "vt-" + sid)).fetchall()
        out.append({"sid": sid, "schl": schl, "name": name, "krisen": krisen.offene_anzahl(con, schl),
                    "notlage": any(notlage.offener_fall(con, r["id"]) for r in kassen),
                    "minus": any(r["saldo"] < 0 for r in kassen), "gesperrt": any(r["gesperrt"] for r in kassen)})
    return sorted(out, key=lambda x: (-(x["krisen"] + 2 * x["notlage"] + x["minus"] + x["gesperrt"]), x["name"]))


def staaten_raster(con):
    import wappen
    kacheln = []
    for x in teilstaaten_lage(con):
        m = []
        if x["krisen"]:
            m.append(f'<i class="rot">{x["krisen"]} Krise{"n" if x["krisen"] != 1 else ""}</i>')
        if x["notlage"]:
            m.append('<i class="rot">Notlage</i>')
        if x["minus"]:
            m.append('<i class="rot">Kasse im Minus</i>')
        if x["gesperrt"]:
            m.append('<i class="rot">Kasse gesperrt</i>')
        ziel = "#land" if x["krisen"] else ("#finanzen" if m else "")
        kacheln.append(f'<a class="rp-staat{" warn" if m else ""}" href="{PFAD}teilstaaten/?ziel={esc(x["schl"])}{ziel}">'
                       f'{wappen.klein(x["sid"], x["name"], 36) or amt.ic("flag")}<span><b>{esc(x["name"])}</b>'
                       f'<span class="rp-marken">{"".join(m) or "<i>ruhig</i>"}</span></span></a>')
    return f'<div class="rp-staaten">{"".join(kacheln)}</div>'


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
    gz = [(f'<a href="{PFAD}buchung/{b["id"]}/">#{b["id"]}</a>', f'{nm(b["von"])} → {nm(b["an"])}<br><small class="az">{esc(b["zweck"])}</small>',
           f'<span class="sa-betrag">{mark(b["betrag"])}</span>',
           amt.status_marke("ok", "storniert") if b["id"] in storniert else f'<a class="rp-chip" href="{PFAD}buchung/{b["id"]}/">{amt.ic("rotate-ccw")}Storno</a>')
          for b in gross]
    neu = con.execute("SELECT * FROM gk_konten WHERE art IN ('privat','gewerbe') AND eroeffnet>=? ORDER BY id DESC LIMIT 8", (seit,)).fetchall()
    nz = [(amt._zeit(r["eroeffnet"]), _konto_link(r), mark(r["saldo"])) for r in neu]
    faelle_ = con.execute("SELECT * FROM rp_faelle WHERE status='offen' ORDER BY id DESC LIMIT 8").fetchall()
    fz = [(f'<a href="{PFAD}fall/{f["id"]}/">{esc(f["titel"])}</a>', ", ".join(esc(b["name"]) for b in beteiligte(con, f["id"])[:3]) or "–", amt._zeit(f["erstellt"]))
          for f in faelle_]
    inhalt = (_kopf(request, "RP-Leitung · Lagebild", "layout-dashboard",
                    '<p class="az">Eingriffe der Server- und RP-Leitung in das Geldsystem. Alles wird doppelt gebucht und protokolliert.</p>')
              + f'<div class="kennzahlen rp-kzl">{kacheln}</div>'
              + f'<div class="aktionen"><a class="btn" href="{PFAD}faelle/?neu=1">{amt.ic("plus")}Neuer Fall</a>'
                f'<a class="btn zweit" href="{PFAD}konten/">{amt.ic("search")}Konto suchen</a><a class="btn zweit" href="{PFAD}protokoll/">{amt.ic("scroll-text")}Protokoll</a></div>'
              + '<h2>Teilstaaten</h2><p class="az">Auffällige zuerst. Ein Klick öffnet den Teilstaat beim passenden Reiter.</p>' + staaten_raster(con)
              + '<div class="rp-spalten"><section><h2>Handlungsbedarf · offene Fälle</h2>'
              + amt.tabelle(["Fall", "Beteiligte", "Eröffnet"], fz, "Keine offenen Fälle.")
              + '</section><section><h2>Bewegungen · größte Überweisungen (7 Tage)</h2>'
              + amt.tabelle(["Nr.", "Von → An", "Betrag", ""], gz, "Keine Überweisungen.")
              + '<h2>Neue Konten (7 Tage)</h2>' + amt.tabelle(["Eröffnet", "Konto", "Saldo"], nz, "Keine neuen Konten.") + '</section></div>')
    return sa.ant(request, k, "RP-Leitung", "sa-rp", inhalt)


def _sheet(id_, titel, inhalt, symbol="plus", auf=False):
    """Dialog („Sheet“): am Handy von unten, am Desktop mittig."""
    return (f'<dialog class="rp-sheet" id="{id_}"{" data-auf" if auf else ""} aria-label="{esc(titel)}"><div class="rp-sheet-kopf"><b class="rp-sheet-titel">{amt.ic(symbol)}{esc(titel)}</b>'
            f'<button class="knopf-rund" type="button" data-zu aria-label="Schließen">{amt.ic("x")}</button></div><div class="rp-sheet-inhalt">{inhalt}</div></dialog>')


def neuer_fall_sheet(request, auf=False):
    form = (f'<form class="sa-formular" method="post" action="{PFAD}fall/neu">{amt.csrf_feld(request)}'
            '<div><label for="t">Titel</label><input type="text" id="t" name="titel" required maxlength="120" placeholder="z. B. Überfall auf die Reichsbank"></div>'
            '<div><label for="b">Beschreibung</label><textarea id="b" name="beschreibung" rows="4" maxlength="2000"></textarea></div>'
            f'{konto_feld("nb", "konto", "Beteiligtes Konto (optional)", pflicht=False)}'
            f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Fall eröffnen</button></div></form>')
    return _sheet("rp-neu", "Neuen Fall eröffnen", form, "folder-open", auf)


@sa.seite("rp")
async def faelle(request, k):
    import handel
    con = request.app["db"]
    q = request.query
    stand = q.get("stand", "offen") if q.get("stand") in ("offen", "erledigt", "alle") else ("alle" if q.get("alle") else "offen")
    such = " ".join(q.get("q", "").split())[:80]
    staat = q.get("staat", "")
    mein = q.get("mein") == "1"
    staaten = {s_: n for s_, n in handel.halter(con).items() if s_ != "reich"}
    wo, arg = [], []
    if stand != "alle":
        wo.append("status=?"); arg.append(stand)
    if such:
        wo.append("(lower(titel) LIKE lower(?) OR lower(beschreibung) LIKE lower(?) OR id IN (SELECT b.fall_id FROM rp_beteiligte b JOIN gk_konten g ON g.id=b.konto_id WHERE lower(g.name) LIKE lower(?)))")
        arg += [f"%{such}%"] * 3
    if staat in staaten:
        wo.append("id IN (SELECT b.fall_id FROM rp_beteiligte b JOIN gk_konten g ON g.id=b.konto_id WHERE g.stelle IN (?,?))"); arg += [staat, "vt-" + staat[3:]]
    if mein:
        wo.append("autor_id=?"); arg.append(k["id"])
    rows = con.execute("SELECT * FROM rp_faelle" + (" WHERE " + " AND ".join(wo) if wo else "") + " ORDER BY id DESC LIMIT 200", arg).fetchall()
    zeilen = [(f'<a href="{PFAD}fall/{f["id"]}/">{esc(f["titel"])}</a>', amt.status_marke("offen" if f["status"] == "offen" else "ok",
                                                                                           "Offen" if f["status"] == "offen" else "Abgeschlossen"),
               ", ".join(esc(b["name"]) for b in beteiligte(con, f["id"])[:4]) or "–",
               amt._zeit(f["erstellt"]), esc(f["autor_name"])) for f in rows]
    sel = lambda name, opts, wert: (f'<select name="{name}" onchange="this.form.submit()">'
                                    + "".join(f'<option value="{esc(v)}"{" selected" if v == wert else ""}>{esc(t)}</option>' for v, t in opts) + "</select>")
    filt = (f'<form class="rp-filter" method="get" action="{PFAD}faelle/">'
            f'<div><label>Stand</label>{sel("stand", [("offen", "Offen"), ("erledigt", "Abgeschlossen"), ("alle", "Alle")], stand)}</div>'
            f'<div><label>Teilstaat</label>{sel("staat", [("", "Alle")] + list(staaten.items()), staat)}</div>'
            f'<div><label>Eröffnet von</label>{sel("mein", [("", "allen"), ("1", "mir")], "1" if mein else "")}</div>'
            f'<div><label for="fq">Suche (Titel, Beschreibung, Beteiligte)</label><input type="search" id="fq" name="q" value="{esc(such)}"></div>'
            f'<button class="btn zweit" type="submit">{amt.ic("search")}Filtern</button></form>')
    inhalt = (_kopf(request, "Fälle", "folder-open")
              + f'<div class="aktionen"><button class="btn" type="button" data-sheet="rp-neu">{amt.ic("plus")}Neuer Fall</button></div>'
              + filt + amt.tabelle(["Fall", "Stand", "Beteiligte", "Eröffnet", "Von"], zeilen, "Keine Fälle zu diesem Filter.")
              + '<span id="neu"></span>' + neuer_fall_sheet(request, auf=q.get("neu") == "1") + FUELL_JS
              + '<script>if(location.hash==="#neu"){var d=document.getElementById("rp-neu");if(d&&d.showModal)d.showModal()}</script>')
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
# (Art, Titel, Kurzbeschreibung, Icon, gefährlich)
MASSNAHMEN = [("raub", "Raub / Diebstahl", "Geld gegen den Willen des Opfers bewegen", "hand-coins", True),
              ("einziehen", "Beschlagnahme", "Geld einziehen, z. B. an die Reichskasse", "gavel", True),
              ("strafe", "Geldstrafe", "Bußgeld an die Reichskasse", "scale", True),
              ("rueckgabe", "Rückgabe / Entschädigung", "Geld auszahlen", "undo-2", False),
              ("sperren", "Konto sperren", "Keine Ausgaben mehr, Karte mitsperren", "lock", True),
              ("freigeben", "Konto freigeben", "Sperre aufheben", "lock-open", False),
              ("storno", "Buchung stornieren", "Eine Buchung vollständig zurückbuchen", "rotate-ccw", True),
              ("notiz", "Notiz", "Im Verlauf festhalten", "sticky-note", False)]


def _formulare(request, con, fid, abgeschlossen, vor=None, bet=()):
    """Maßnahmen des Falls als Kacheln; jede öffnet ein Sheet mit dem Formular. vor = {"konto", "aktion", "buchung"}: Hauptfeld vorausfüllen, Sheet öffnen."""
    vor = vor or {}
    c = amt.csrf_feld(request)
    act = f'{PFAD}fall/{fid}/aktion'
    vs = [(kennung(con, b), b["name"]) for b in bet]
    mit = ('<div><label>Mitteilung an den Betroffenen (optional, per DM)</label><input type="text" name="mitteilung" maxlength="400" '
           'placeholder="z. B. Dein Konto wurde wegen eines Vorfalls gesperrt."></div>')

    def kf(fid_, name, bez, pflicht=True, art=""):
        wert = vor.get("konto", "") if HAUPTFELD.get(art) == fid_ else ""
        return konto_feld(fid_, name, bez, wert, pflicht, vs)

    betrag = '<div><label>Betrag in Kronen</label><input type="text" name="betrag" inputmode="decimal"></div>'
    alles = '<label class="sa-haken"><input type="checkbox" name="alles" value="1"> gesamtes Guthaben</label>'
    grund = lambda v: f'<div><label>Grund / Verwendungszweck</label><input type="text" name="grund" maxlength="160" placeholder="{esc(v)}"></div>'
    minus = '<label class="sa-haken"><input type="checkbox" name="minus" value="1"> Konto darf dabei ins Minus gehen</label>'
    felder = {
        "raub": ("Ohne Täterkonto verlässt die Beute den Umlauf (Zentralbank).",
                 kf("r1", "opfer", "Opfer (Konto der Bank, Kasse, Person …)", art="raub") + kf("r2", "ziel", "Täter (Konto, leer = Beute außer Landes)", pflicht=False) + betrag + alles),
        "einziehen": ("Standardmäßig an die Reichskasse, sonst an ein Konto (z. B. Rückgabe an das Opfer).",
                      kf("e1", "konto", "Konto, von dem eingezogen wird", art="einziehen") + kf("e2", "ziel_konto", "Empfänger (leer = Reichskasse)", pflicht=False)
                      + betrag + alles + grund("Beschlagnahme") + minus),
        "rueckgabe": ("Aus der Reichskasse, per Geldschöpfung oder von einem anderen Konto.",
                      kf("g1", "konto", "Empfänger", art="rueckgabe") + betrag
                      + '<div><label>Quelle</label><select name="quelle"><option value="reichskasse">Reichskasse</option>'
                        '<option value="zentralbank">Zentralbank (Geldschöpfung)</option><option value="konto">Anderes Konto …</option></select></div>'
                      + kf("g2", "quelle_konto", "Quellkonto (nur bei „Anderes Konto“)", pflicht=False) + grund("Entschädigung")),
        "strafe": ("Bußgeld zugunsten der Reichskasse (oder eines Kontos).",
                   kf("s1", "konto", "Konto des Schuldigen", art="strafe") + kf("s2", "ziel_konto", "Empfänger (leer = Reichskasse)", pflicht=False)
                   + betrag + alles + grund("Geldstrafe") + minus),
        "sperren": ("Gesperrte Konten können keine Überweisungen, Steuern oder Gebühren auslösen; Gutschriften sind weiter möglich.",
                    kf("k1", "konto", "Konto", art="sperren") + grund("Ermittlungen der RP-Leitung")
                    + '<label class="sa-haken"><input type="checkbox" name="person" value="1" checked> alle Konten der Person (Privat und Gewerbe)</label>'
                    + '<label class="sa-haken"><input type="checkbox" name="karte" value="1" checked> Bankkarte mitsperren</label>'),
        "freigeben": ("Hebt die Sperre auf (auf Wunsch samt Bankkarte).", kf("f1", "konto", "Konto", art="freigeben")
                      + '<label class="sa-haken"><input type="checkbox" name="person" value="1" checked> alle Konten der Person</label>'
                      + '<label class="sa-haken"><input type="checkbox" name="karte" value="1" checked> Bankkarte freigeben</label>'),
        "storno": ("Jede Buchung nur einmal. Schneller: auf der Kontoseite „Storno“ in der Umsatzzeile.",
                   f'<div><label>Nummer der Buchung</label><input type="text" name="buchung" required inputmode="numeric" placeholder="z. B. 1234" value="{esc(vor.get("buchung", ""))}"></div>'
                   + grund("Storno")),
        "notiz": ("Hält etwas im Verlauf des Falls fest.", '<div><label>Text</label><textarea name="text" rows="3" maxlength="500" required></textarea></div>'),
    }
    kacheln, sheets = [], []
    for art, titel, kurz_, symbol, gefahr in MASSNAHMEN:
        hilfe, f = felder[art]
        knopf = "Speichern" if art == "notiz" else "Prüfen"
        kacheln.append(f'<button type="button" class="rp-kachel{" gefahr" if gefahr else ""}" data-sheet="m-{art}">{amt.ic(symbol)}<b>{esc(titel)}</b><small>{esc(kurz_)}</small></button>')
        sheets.append(_sheet(f"m-{art}", titel, f'<form class="sa-formular" method="post" action="{act}">{c}<input type="hidden" name="aktion" value="{art}">'
                                                 f'<p class="sa-hinweis">{esc(hilfe)}</p>{f}{mit if art != "notiz" else ""}'
                                                 f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}{knopf}</button>'
                                                 f'<button class="btn zweit" type="button" data-zu>Abbrechen</button></div></form>', symbol, auf=vor.get("aktion") == art))
    hinweis = ('<p class="az">Gebucht wird erst nach einer Vorschau mit den neuen Salden.</p>' if not abgeschlossen else
               '<p class="hinweis">Der Fall ist abgeschlossen. Maßnahmen sind trotzdem möglich; besser den Fall wieder öffnen.</p>')
    return hinweis + f'<div class="rp-raster">{"".join(kacheln)}</div>' + "".join(sheets)


def _beteiligte_html(request, con, f, bet):
    c = amt.csrf_feld(request)
    act = f'{PFAD}fall/{f["id"]}/beteiligte'
    chips = "".join(f'<span class="rp-chip"><a href="{PFAD}konto/{b["id"]}/">{konto_symbol(b)}{esc(b["name"])}</a>'
                    f'<form method="post" action="{act}">{c}<input type="hidden" name="weg" value="{b["id"]}">'
                    f'<button class="rp-weg" type="submit" title="Aus dem Fall entfernen" aria-label="{esc(b["name"])} aus dem Fall entfernen">×</button></form></span>' for b in bet)
    chips += f'<button type="button" class="rp-chip" data-sheet="rp-bet">{amt.ic("plus")}Konto hinzufügen</button>'
    neu = _sheet("rp-bet", "Beteiligtes Konto hinzufügen", f'<form class="sa-formular" method="post" action="{act}">{c}'
                 f'{konto_feld("bt", "konto", "Konto")}<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Hinzufügen</button></div></form>')
    return ('<h2>Beteiligte</h2><p class="az">Sie stehen in jeder Maßnahme als Vorschlag bereit; jede Maßnahme fügt die betroffenen Konten selbst hinzu.</p>'
            + f'<div class="rp-chips">{chips}</div>' + neu)


def _fall_seite(request, k, con, f, extra=""):
    offen = f["status"] == "offen"
    bet = beteiligte(con, f["id"])
    q = request.query
    vor = {"aktion": q.get("aktion", ""), "buchung": q.get("buchung", "") if q.get("buchung", "").isdigit() else ""}
    r = geld.konto(con, int(q["konto"])) if q.get("konto", "").isdigit() else (bet[0] if len(bet) == 1 else None)
    if r:
        vor["konto"] = kennung(con, r)
    if extra:
        vor["aktion"] = ""   # Vorschau offen: kein zweites Sheet
    inhalt = (_kopf(request, f["titel"], "folder-open")
              + amt.daten_tabelle([("Stand", amt.status_marke("offen" if offen else "ok", "Offen" if offen else "Abgeschlossen")),
                                   ("Eröffnet", f'{amt._zeit(f["erstellt"])} von {esc(f["autor_name"])}'),
                                   ("Beschreibung", esc(f["beschreibung"]).replace("\n", "<br>") or "–")])
              + _beteiligte_html(request, con, f, bet)
              + f'<h2>Maßnahmen</h2>{_formulare(request, con, f["id"], not offen, vor, bet)}'
              + f'<form method="post" action="{PFAD}fall/{f["id"]}/status" style="margin-top:14px">{amt.csrf_feld(request)}'
                f'<button class="btn zweit" type="submit">{amt.ic("check")}{"Fall abschließen" if offen else "Fall wieder öffnen"}</button></form>'
              + '<h2>Verlauf</h2>' + amt.tabelle(["Zeit", "Aktion", "Einzelheiten", "Von"], _aktionsliste(con, f["id"]), "Noch kein Verlauf.")
              + extra + FUELL_JS)
    return sa.ant(request, k, f["titel"], "sa-rp-faelle", inhalt)


@sa.seite("rp")
async def fall(request, k):
    con = request.app["db"]
    i = request.match_info["id"]
    f = con.execute("SELECT * FROM rp_faelle WHERE id=?", (int(i),)).fetchone() if i.isdigit() else None
    if not f:
        raise web.HTTPNotFound(text="Fall nicht gefunden.")
    return _fall_seite(request, k, con, f)


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


def _vorschau(request, con, k, f, form):
    """Führt die Maßnahme probehalber aus (ohne DM) und macht alles rückgängig. Gibt (Text, [(Konto, vorher, Änderung, nachher)]) zurück; wirft geld.Fehler."""
    con.commit()
    max_b = con.execute("SELECT COALESCE(MAX(id),0) FROM gk_buchungen").fetchone()[0]
    request["rp_vorschau"] = True
    try:
        text = ausfuehren(request, con, k, f, form)
        delta = {}
        for b in con.execute("SELECT * FROM gk_buchungen WHERE id>?", (max_b,)):
            if b["von"]:
                delta[b["von"]] = delta.get(b["von"], 0) - b["betrag"]
            if b["an"]:
                delta[b["an"]] = delta.get(b["an"], 0) + b["betrag"]
        zeilen = []
        for i, d in delta.items():
            r = geld.konto(con, i)
            if r and r["stelle"] not in ("zentralbank", "volkswirtschaft"):
                zeilen.append((r, r["saldo"] - d, d, r["saldo"]))
        return text, zeilen
    finally:
        con.rollback()
        request["rp_vorschau"] = False


async def fall_aktion(request):
    k, form, con, f = await _post(request)
    pfad = f"{PFAD}fall/{f['id']}/"
    art = str(form.get("aktion", ""))
    if art != "notiz" and form.get("bestaetigt") != "1":
        try:
            text, zeilen = _vorschau(request, con, k, f, form)
        except geld.Fehler as e:
            sa.weiter(pfad, str(e), True)
        tz = [(_konto_link(r), sa.betrag_html(v, False), sa.betrag_html(d), sa.betrag_html(n, False)) for r, v, d, n in zeilen]
        versteckt = "".join(f'<input type="hidden" name="{esc(n)}" value="{esc(str(w))}">' for n, w in form.items() if n not in ("csrf", "bestaetigt"))
        titel = dict((a, t) for a, t, *_ in MASSNAHMEN).get(art, "Maßnahme")
        inhalt = (f'<p class="az">So würde gebucht. Noch ist nichts geschehen.</p><div class="rp-vorschau">{esc(text)}</div>'
                  + (amt.tabelle(["Konto", "Saldo vorher", "Änderung", "Saldo nachher"], tz) if tz else "")
                  + (f'<p class="az">Mitteilung per DM: „{esc(str(form.get("mitteilung")))}“</p>' if str(form.get("mitteilung", "")).strip() else "")
                  + f'<form method="post" action="{pfad}aktion">{amt.csrf_feld(request)}{versteckt}<input type="hidden" name="bestaetigt" value="1">'
                    f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Bestätigen und ausführen</button>'
                    f'<a class="btn zweit" href="{pfad}">Abbrechen</a></div></form>')
        return _fall_seite(request, k, con, f, _sheet("rp-vorschau", "Vorschau: " + titel, inhalt, "circle-alert", auf=True))
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


def _suche_konten(con, q, limit=60):
    n = geld.nummer_gueltig(q)
    return con.execute("SELECT * FROM gk_konten WHERE nummer=? OR inhaber_id=? OR lower(name) LIKE lower(?) OR lower(stelle)=lower(?) "
                       "ORDER BY (lower(name) LIKE lower(?)) DESC, art, name LIMIT ?", (n or "", q, f"%{q}%", q, f"{q}%", limit)).fetchall()


async def konten_json(request):
    """Vorschläge für die Kontofelder: [{w: Eingabe, n: Name, a: Art, nr: Nummer, s: Symbol-HTML}]."""
    k = await anmeldung.konto(request)
    if not ist_rp(k):
        raise web.HTTPForbidden()
    con = request.app["db"]
    q = " ".join(request.query.get("q", "").split())[:80]
    rows = [r for r in _suche_konten(con, q, 12) if r["stelle"] not in ("zentralbank", "volkswirtschaft")] if len(q) >= 2 else []
    return web.json_response([{"w": kennung(con, r), "n": r["name"], "a": geld.art_name(r), "nr": nummer_anzeige(r["nummer"]), "s": konto_symbol(r, 18)} for r in rows],
                             headers={"Cache-Control": "no-store"})


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
        ergebnis = amt.tabelle(["Konto", "Art", "Nummer", "Saldo", "Stand"], [zeile(r) for r in _suche_konten(con, q)], "Kein Konto gefunden.")
    if request.query.get("nur"):   # Live-Suche: nur das Ergebnis
        return web.Response(text=ergebnis, content_type="text/html", headers={"Cache-Control": "no-store"})
    live = ('<script>(function(){var i=document.getElementById("q"),e=document.getElementById("rp-ergebnis"),t;if(!i||!e)return;'
            'i.addEventListener("input",function(){clearTimeout(t);var v=i.value.trim();t=setTimeout(function(){if(v.length<2)return;'
            f'fetch("{PFAD}konten/?nur=1&q="+encodeURIComponent(v),{{credentials:"same-origin"}}).then(function(r){{return r.text()}}).then(function(h){{e.innerHTML=h;'
            f'try{{history.replaceState(null,"","{PFAD}konten/?q="+encodeURIComponent(v))}}catch(x){{}}}})}},200)}})}})();</script>')
    inhalt = (_kopf(request, "Konten & Personen", "search")
              + f'<form class="sa-leiste" method="get" action="{PFAD}konten/"><div><label for="q">Name, Kontonummer oder Discord-ID – Treffer erscheinen beim Tippen</label>'
                f'<input type="search" id="q" name="q" value="{esc(q)}" autocomplete="off"{"" if filt else " autofocus"}></div><button class="btn" type="submit">{amt.ic("search")}Suchen</button></form>'
              + chips + f'<div id="rp-ergebnis">{ergebnis}</div>' + live)
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
        akte = con.execute("SELECT id FROM amt_akten WHERE konto_id=?", (r["inhaber_id"],)).fetchone()
        if akte:
            info.append(("Bürgerakte", f'<a href="{amt.BASIS}buerger/{akte["id"]}/">{esc(amt.az_akte(akte["id"]))}</a>'))
        try:
            besitz = con.execute("SELECT k.name FROM pb_besitz b JOIN pb_katalog k ON k.id=b.katalog_id WHERE b.inhaber_id=? AND b.status='aktiv' ORDER BY k.kategorie",
                                 (r["inhaber_id"],)).fetchall()
        except Exception:
            besitz = []
        if besitz:
            info.append(("Privatbesitz", esc(", ".join(b["name"] for b in besitz))))
    fl = con.execute("SELECT f.* FROM rp_beteiligte b JOIN rp_faelle f ON f.id=b.fall_id WHERE b.konto_id=? ORDER BY f.id DESC", (r["id"],)).fetchall()
    if fl:
        info.append(("Fälle", " · ".join(f'<a href="{PFAD}fall/{f["id"]}/">{esc(f["titel"])}</a>' + ("" if f["status"] == "offen" else " (abgeschlossen)") for f in fl)))
    sperr = ("freigeben", "lock-open", "Freigeben") if r["gesperrt"] else ("sperren", "lock", "Sperren")
    kn = [("einziehen", "gavel", "Beschlagnahme"), ("strafe", "scale", "Geldstrafe"), ("raub", "hand-coins", "Raub (als Opfer)"),
          ("rueckgabe", "undo-2", "Rückgabe / Entschädigung"), sperr, ("notiz", "sticky-note", "Nur in den Fall aufnehmen")]
    knoepfe = "".join(f'<button class="rp-kachel{" gefahr" if a in ("einziehen", "strafe", "raub", "sperren") else ""}" type="submit" name="aktion" value="{a}">'
                      f'{amt.ic(s)}<b>{esc(t)}</b></button>' for a, s, t in kn)
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
    r.add_get(PFAD + "konten.json", konten_json)
    r.add_get(PFAD + "konto/{id}/", konto)
    r.add_get(PFAD + "konto/{id}/fall", konto_zu_fall)
    r.add_post(PFAD + "konto/{id}/fall", konto_massnahme)
    r.add_post(PFAD + "massnahme", massnahme)
    r.add_get(PFAD + "buchung/{id}/", buchung)
    r.add_get(PFAD + "protokoll/", protokoll)
