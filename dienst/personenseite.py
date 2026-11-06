"""Prüfseite pro Person: Ziel der QR-Codes auf Pässen und Meldebescheinigungen (Tab „Passprüfung“).

- /p/<Passnummer>              Kurzlink aus dem QR-Code eines Passes → …/intern/passpruefung/<Passnummer>/
- /p/BA-00013                  Kurzlink einer Meldebescheinigung   → …/intern/passpruefung/person/<Akten-ID>/
- …/intern/passpruefung/<nr>/  Prüfergebnis des gescannten Dokuments (groß, farbig) + Dokument digital (flach, ohne Umblättern)
                               + alle Infos zur Person: Personalien, Wohnsitz/Meldehistorie, alle Ausweisdokumente, Fahndungshinweise,
                               und je nach Recht des Prüfenden: Einbürgerungsakten und Vorgänge (Akten-Recht), Straf-/Ermittlungssachen
                               (nur Akten der eigenen Behörde, strafsachen.lesen_darf), Erwähnungen in Einsatzberichten (eigene Landespolizei),
                               Prüfprotokoll (Akten-Recht).
- …/intern/pass-foto/<konto>   Discord-Profilbild über den Dienst (die CSP der Website lässt fremde Bilder nicht zu)
Zugang: wer prüfen darf (meldewesen.darf_pruefen: Zoll, Polizei, Reichsverwaltung, Kanzler, Kaiser) oder Akten-Recht hat.
Der Inhaber selbst landet beim Scannen auf seinem digitalen Pass. Jeder Aufruf wird in pw_abfragen protokolliert („QR“).
Verschlussakten: ohne Verschlussrecht nur Prüfergebnis und Dokument, keine Personendaten.
"""
import json
import os
import re
import time

import aiohttp
from aiohttp import web

import amt
import anmeldung
import landespolizei
import meldewesen
import passdigital
import passdruck
import strafsachen

esc = amt.esc
BASIS = amt.BASIS
PRUEF = meldewesen.PRUEF
PASS_ABSCHNITT = []   # fn(request, konto, pass, status) -> HTML unter dem Dokument (zollwesen.py: Sichtvermerke)
_FOTOS = {}   # (konto_id, avatar-hash) -> (zeit, bytes)

URTEIL = {"gueltig": ("✓", "Dokument gültig"), "abgelaufen": ("!", "Dokument abgelaufen"), "ungueltig": ("✕", "Dokument ungültig"),
          "fahndung": ("✕", "Zur Fahndung ausgeschrieben"), "unbekannt": ("✕", "Nicht im Passregister")}
HINWEIS = {"gueltig": "Das Dokument ist im Passregister verzeichnet und gültig. Lichtbild und Person abgleichen.",
           "abgelaufen": "Das Dokument ist abgelaufen. Der Inhaber muss bei der Reichsverwaltung einen neuen Pass beantragen.",
           "fahndung": "Das Dokument ist als gestohlen gemeldet. Dokument sicherstellen, Personalien feststellen, Polizei verständigen.",
           "ungueltig": "Das Dokument ist ungültig und einzuziehen.",
           "unbekannt": "Diese Nummer ist im Passregister des Reiches nicht verzeichnet. Das Dokument ist als nicht echt zu behandeln."}

CSS = """<style>
.ps-urteil{display:flex;gap:16px;align-items:center;border-radius:14px;padding:16px 20px;margin:6px 0 20px;color:#fff;max-width:900px}
.ps-urteil i{font-style:normal;flex:none;width:46px;height:46px;border-radius:50%;background:rgba(255,255,255,.2);display:grid;place-items:center;font-size:24px;font-weight:700}
.ps-urteil b{display:block;font-size:21px;line-height:1.2}.ps-urteil span{display:block;font-size:14px;opacity:.92;margin-top:2px}
.ps-urteil.gueltig{background:#1d6b36}.ps-urteil.abgelaufen{background:#a86a12}.ps-urteil.ungueltig,.ps-urteil.fahndung,.ps-urteil.unbekannt{background:#a3141f}
.ps-kopf{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.5fr);gap:24px;align-items:start}
@media (max-width:1000px){.ps-kopf{grid-template-columns:minmax(0,1fr)}}
.ps-kopf>div{min-width:0}
.ps-person{display:flex;gap:16px;align-items:center;margin-bottom:12px}
.ps-person img,.ps-person .ohne{width:92px;height:92px;border-radius:14px;object-fit:cover;flex:none;background:#e9ebef;display:grid;place-items:center;color:#888;font-size:12px}
.ps-person .ps-name{font-size:22px;font-weight:650;line-height:1.25;color:var(--ink)}.ps-person p{margin:2px 0 0;color:var(--grau);font-size:14px}
.ps-dok{width:100%;min-height:40px}
.ps-fahndung{border:2px solid var(--rot);border-radius:12px;padding:12px 16px;margin:14px 0;color:var(--rot);font-weight:600}
.ps-klein{font-size:13px;color:var(--grau)}
</style>"""

DOK_CSS = """
.z{zoom:var(--z,1)}
.seite{position:relative!important;left:0!important;border-radius:2.6mm;box-shadow:0 6px 22px rgba(0,0,0,.18)}
.kartenreihe{display:flex;flex-wrap:wrap;gap:4mm}
.karte{position:relative!important;left:0!important;box-shadow:0 6px 22px rgba(0,0,0,.18)}
.stempel{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) rotate(-14deg);border:1.2mm solid #b3121f;color:#b3121f;
 font:700 8mm/1 "Liberation Sans",Arial,sans-serif;letter-spacing:.06em;text-transform:uppercase;padding:2mm 5mm;border-radius:2mm;
 background:rgba(255,255,255,.4);white-space:nowrap;z-index:5}
.seite,.karte{color:#1a1a1a}
"""

DOK_JS = """<script>(function(){
function passen(){document.querySelectorAll(".ps-dok").forEach(function(h){
 var r=h.shadowRoot;if(!r)return;var z=r.querySelector(".z");if(!z)return;
 var mm=96/25.4,w=h.clientWidth,art=h.dataset.art,s;
 if(art==="karte"){var k=85.6*mm;s=w>=2*k+15?Math.min(1.6,(w-16)/(2*k)):Math.min(1.6,w/k);}
 else{s=Math.min(1.5,w/(125*mm));}
 z.style.setProperty("--z",s);});}
addEventListener("resize",passen);passen();
if(document.fonts)document.fonts.ready.then(passen);})();</script>"""


def darf_sehen(k):
    return bool(k) and k["mitglied"] and (meldewesen.darf_pruefen(k) or amt.ist_beamter(k))


# ---------------------------------------------------------------- Dokument (flach)

def dokument(con, p, status):
    d = passdruck.daten(con, p, True)
    d["foto"] = f'{BASIS}pass-foto/{p["konto_id"]}' if d["foto"] else ""
    stempel = f'<div class="stempel">{esc(passdigital.STEMPEL[status])}</div>' if status in passdigital.STEMPEL else ""
    if p["art"] == "personalausweis":
        vorne, hinten = passdruck.karte_seiten(d)
        if stempel:
            vorne = vorne.replace('<div class="karte v">', '<div class="karte v">' + stempel, 1)
        innen, art = f'<div class="kartenreihe">{vorne}{hinten}</div>', "karte"
    else:
        innen, art = passdruck.heft_seiten(d)["daten"], "heft"
        if stempel:
            innen = innen[:-len("</div>")] + stempel + "</div>"
    stil = passdruck._css().split("}", 1)[1]   # ohne @font-face (wirkt im Shadow-DOM nicht; steht im Dokument)
    html_ = (f'<div class="ps-dok" data-art="{art}"><template shadowrootmode="open"><style>{stil}{DOK_CSS}</style>'
             f'<div class="z">{innen}</div></template></div>')
    return passdigital._bilder_url(html_)


# ---------------------------------------------------------------- Abschnitte

def _personalien(z):
    return amt.daten_tabelle([("Name (IC)", esc(z["ic_name"] or "– (nicht erfasst)")), ("Status", amt.akte_marke(z["status"])),
                              ("Geburtsdatum (IC)", esc(z["ic_geburt"] or "–")), ("Geschlecht", esc(z["geschlecht"] or "–")),
                              ("Fraktion", esc(z["fraktion"] or "–")), ("Gesellschaftsschicht", esc(z["schicht"] or "–")),
                              ("Berufliche Zugehörigkeit", esc(z["beruf"] or "–")), ("Beruf / Position", esc(z["position"] or "–")),
                              ("Discord-Name", esc(z["name"])), ("Discord-ID", esc(z["konto_id"]))])


def _wohnsitz(con, z):
    hist = con.execute("SELECT * FROM mw_meldungen WHERE akte_id=? ORDER BY id DESC", (z["id"],)).fetchall()
    if not hist:
        return '<p class="leer">Kein Wohnsitz gemeldet.</p>'
    ws = hist[0]
    aktuell = amt.daten_tabelle([("Wohnsitz", "Ausland (abgemeldet)" if ws["art"] == "abmeldung" else esc(ws["staat_name"])),
                                 ("Anschrift (IC)", esc(ws["anschrift"] or "–")), ("Gemeldet seit (IC)", esc(ws["gueltig_ab"] or "–"))])
    zeilen = [(esc(meldewesen.MELDEARTEN[m["art"]]), esc(m["staat_name"]), esc(m["anschrift"] or "–"), esc(m["gueltig_ab"] or "–"),
               amt._zeit(m["zeit"], False)) for m in hist]
    return aktuell + "<h3>Meldehistorie</h3>" + amt.tabelle(["Meldung", "Teilstaat", "Anschrift", "Gültig ab (IC)", "Erfasst"], zeilen)


def _paesse(con, konto_id, akte_id, k, aktiv_id=None):
    ps = con.execute("SELECT * FROM pw_paesse WHERE akte_id=? OR konto_id=? ORDER BY ausgestellt DESC", (akte_id, konto_id)).fetchall()
    if not ps:
        return '<p class="leer">Keine Ausweisdokumente ausgestellt.</p>', []
    fahndung = [p for p in ps if meldewesen.pass_status(p)[0] == "fahndung"]
    zeilen = []
    for p in ps:
        nr = f'<a class="mw-nr" href="{PRUEF}{esc(p["nummer"])}/">{esc(p["nummer"])}</a>' + (" ◂ gescannt" if p["id"] == aktiv_id else "")
        links = f'<a href="{BASIS}pass/{p["id"]}/">digital</a>'
        if amt.ist_beamter(k):
            links += f' · <a href="{meldewesen.PFAD}paesse/{p["id"]}/">Register</a>'
        zeilen.append((nr, esc(meldewesen.PASSARTEN[p["art"]][0]), meldewesen.pass_marke(p), amt._zeit(p["ausgestellt"], False),
                       meldewesen._datum(p["gueltig_bis"]), links))
    return amt.tabelle(["Nummer", "Art", "Stand", "Ausgestellt", "Gültig bis", "Ansehen"], zeilen), fahndung


def _verfahren(con, z):
    vs = con.execute("SELECT * FROM amt_verfahren WHERE konto_id=? ORDER BY id DESC", (z["konto_id"],)).fetchall()
    return amt.tabelle(["Aktenzeichen", "Name", "Stand", "Zuletzt"], [amt._verfahren_zeile(v) for v in vs], "Keine Einbürgerungsakten.")


def _strafsachen(con, k, z):
    rows = con.execute("SELECT DISTINCT a.*, b.rolle AS b_rolle FROM sa_akten a JOIN sa_beteiligte b ON b.akte_id=a.id "
                       "WHERE b.konto_id=? ORDER BY a.erstellt DESC", (z["konto_id"],)).fetchall()
    sichtbar = [a for a in rows if strafsachen.lesen_darf(k, a)]
    if not sichtbar:
        return ""
    zeilen = [(f'<a href="{strafsachen.ROOT}{strafsachen.ARTEN[a["art"]]["pfad"]}/{a["id"]}/">{esc(strafsachen.az(a))}</a>',
               esc(strafsachen.ARTEN[a["art"]]["einzel"]), esc(a["titel"]), esc(a["b_rolle"]),
               amt.status_marke(strafsachen.MARKE.get(a["status"], "neutral"), strafsachen.ARTEN[a["art"]]["status"].get(a["status"], a["status"])))
              for a in sichtbar]
    return "<h2>Straf- und Ermittlungssachen</h2>" + amt.tabelle(["Aktenzeichen", "Art", "Betreff", "Beteiligt als", "Stand"], zeilen)


def _einsatzberichte(con, k, z):
    name = (z["ic_name"] or "").strip()
    if len(name) < 4:
        return ""
    staaten = {s["id"]: s for s in landespolizei.staaten(con) if landespolizei.darf(k, s)}
    if not staaten:
        return ""
    rows = con.execute("SELECT * FROM lp_berichte WHERE personen LIKE ? OR sachverhalt LIKE ? ORDER BY erstellt DESC LIMIT 50",
                       (f"%{name}%", f"%{name}%")).fetchall()
    rows = [b for b in rows if b["staat"] in staaten]
    if not rows:
        return ""
    zeilen = [(f'<a href="{landespolizei._pfad(staaten[b["staat"]])}berichte/{b["id"]}/">{esc(landespolizei.az(b, staaten[b["staat"]]))}</a>',
               esc(b["titel"]), esc("Landespolizei " + staaten[b["staat"]]["kurz"]), esc(b["einsatz_zeit"] or "–"),
               esc(landespolizei.STATUS.get(b["status"], b["status"]))) for b in rows]
    return ("<h2>Erwähnungen in Einsatzberichten</h2><p class='ps-klein'>Namensgleiche Treffer in Einsatzberichten der Landespolizeien, "
            "auf die du Zugriff hast.</p>" + amt.tabelle(["Aktenzeichen", "Einsatz", "Dienststelle", "Zeit (IC)", "Stand"], zeilen))


def _protokoll(con, ps):
    ids = [p["id"] for p in ps]
    if not ids:
        return ""
    rows = con.execute(f"SELECT * FROM pw_abfragen WHERE pass_id IN ({','.join('?' * len(ids))}) ORDER BY id DESC LIMIT 15", ids).fetchall()
    zeilen = [(amt._zeit(r["zeit"]), esc(r["nummer"]), esc(r["name"]), esc(r["stelle"]), esc(r["ergebnis"])) for r in rows]
    return "<h2>Letzte Prüfungen</h2>" + amt.tabelle(["Zeit", "Nummer", "Geprüft von", "Dienststelle", "Ergebnis"], zeilen, "Noch keine Prüfungen.")


# ---------------------------------------------------------------- Seiten

def _rahmen(request, k, titel, inhalt):
    schrift = f'<style>@font-face{{font-family:SS3;src:url(data:font/woff2;base64,{amt._PDF_SCHRIFT});font-weight:200 900}}</style>'
    return web.Response(content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, "b-zoll" if request.query.get("von") == "zoll" else "passpruefung", schrift + meldewesen.CSS + CSS + inhalt + DOK_JS, k, request["csrf"]))


def _protokollieren(con, k, nummer, pass_id, ergebnis):
    con.execute("INSERT INTO pw_abfragen (zeit, konto_id, name, stelle, nummer, pass_id, ergebnis) VALUES (?,?,?,?,?,?,?)",
                (int(time.time()), k["id"], k["name"], meldewesen._stelle_von(k), nummer, pass_id, ergebnis + " (QR)"))
    con.commit()


def _seite(con, k, z, p, status, request=None):
    """Gesamte Prüfseite. z = Bürgerakte oder None, p = gescannter Pass oder None, status = Schlüssel aus URTEIL oder None."""
    zoll = request is not None and request.query.get("von") == "zoll"
    zurueck = f'<a href="{BASIS}bereich/zoll/">← Zur Grenzkontrolle</a>' if zoll else f'<a href="{PRUEF}">← Neue Prüfung</a>'
    teile = [f'<h1>{amt.ic("stamp" if zoll else "scan-search")} {"Grenzkontrolle" if zoll else "Passprüfung"}</h1>'
             f'<p class="az">{zurueck}</p>' + (amt.meldung(request) if request is not None else "")]
    if status:
        sym, text = URTEIL[status]
        zusatz = f' ({esc(p["grund"])})' if p is not None and status == "ungueltig" and p["grund"] else ""
        teile.append(f'<div class="ps-urteil {status}"><i>{sym}</i><div><b>{esc(text)}</b>'
                     f'<span>{esc(HINWEIS[status])}{zusatz}</span></div></div>')
    gesperrt = bool(z and z["verschluss"]) and not amt.darf_verschluss(k)
    konto_id = z["konto_id"] if z else (p["konto_id"] if p is not None else "")
    foto = con.execute("SELECT avatar FROM konten WHERE id=?", (konto_id,)).fetchone() if konto_id else None
    bild = (f'<img src="{BASIS}pass-foto/{esc(konto_id)}" alt="">' if foto and foto["avatar"] and not gesperrt else '<span class="ohne">kein Bild</span>')
    name = (z["ic_name"] or z["name"]) if z and not gesperrt else (p["inhaber"] if p is not None and not gesperrt else "Verschlusssache")
    unter = (f'{amt.STATUS_AKTE.get(z["status"], z["status"])} · Bürgerakte {amt.az_akte(z["id"])}' if z and not gesperrt
             else ("Inhaberakte gesperrt (Verschlusssache)" if gesperrt else "Keine Bürgerakte vorhanden"))
    if z and not gesperrt and amt.ist_beamter(k):
        unter = f'{amt.STATUS_AKTE.get(z["status"], z["status"])} · <a href="{BASIS}buerger/{z["id"]}/">Bürgerakte {amt.az_akte(z["id"])}</a>'
    else:
        unter = esc(unter)
    links = f'<div class="ps-person">{bild}<div><div class="ps-name">{esc(name)}</div><p>{unter}</p></div></div>'
    if z and not gesperrt:
        links += _personalien(z)
    rechts = ""
    if p is not None:
        rechts = (f'<h3 style="margin-top:0">{esc(meldewesen.PASSARTEN[p["art"]][0])} <span class="mw-nr">{esc(p["nummer"])}</span></h3>'
                  + dokument(con, p, status)
                  + f'<p class="ps-klein">Gültig bis {meldewesen._datum(p["gueltig_bis"])} · ausgestellt {amt._zeit(p["ausgestellt"], False)} · '
                  f'<a href="{BASIS}pass/{p["id"]}/">zum Durchblättern öffnen</a></p>')
    teile.append(f'<div class="ps-kopf"><div>{links}</div><div>{rechts}</div></div>')
    if request is not None:
        teile.extend(fn(request, k, p, status) for fn in PASS_ABSCHNITT)
    if gesperrt:
        teile.append('<div class="warnung">Die Akte des Inhabers steht unter Verschluss. Weitere Angaben nur für Kanzler und Kaiser.</div>')
        return "".join(teile)
    if z:
        tab, fahndung = _paesse(con, z["konto_id"], z["id"], k, p["id"] if p is not None else None)
        if fahndung:
            teile.append('<div class="ps-fahndung">Achtung: ' + ", ".join(
                f'{esc(meldewesen.PASSARTEN[f["art"]][0])} {esc(f["nummer"])}' for f in fahndung) + " zur Fahndung ausgeschrieben.</div>")
        teile.append("<h2>Wohnsitz</h2>" + _wohnsitz(con, z))
        teile.append("<h2>Ausweisdokumente</h2>" + tab)
        if amt.ist_beamter(k):
            teile.append("<h2>Einbürgerungsakten</h2>" + _verfahren(con, z))
        teile.append(_strafsachen(con, k, z))
        teile.append(_einsatzberichte(con, k, z))
        if amt.ist_beamter(k):
            ps = con.execute("SELECT id FROM pw_paesse WHERE akte_id=?", (z["id"],)).fetchall()
            teile.append(_protokoll(con, ps))
            teile.append("<h2>Vorgänge der Bürgerakte</h2>" + amt.eintraege_html(con, "akte", z["id"]))
    return "".join(teile)


async def _konto(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    return k


async def pass_pruefen(request):
    k = await _konto(request)
    con = request.app["db"]
    nr = "".join(c for c in request.match_info["nr"].upper() if c.isalnum())[:12]
    p = con.execute("SELECT * FROM pw_paesse WHERE nummer=?", (nr,)).fetchone()
    if p is not None and p["konto_id"] == k["id"] and not darf_sehen(k):
        raise web.HTTPFound(f'{BASIS}pass/{p["id"]}/')        # Inhaber scannt den eigenen Pass
    if not darf_sehen(k):
        return web.Response(status=403, content_type="text/html", text=anmeldung.hinweis(
            "Kein Zugang", "Die Prüfung von Ausweisdokumenten ist Zoll, Polizei und Reichsverwaltung vorbehalten.", [("Zur Hauptseite", "/", True)]))
    if p is None:
        _protokollieren(con, k, nr, None, "Nicht im Register")
        inhalt = (f'<h1>{amt.ic("scan-search")} Passprüfung</h1><p class="az"><a href="{PRUEF}">← Neue Prüfung</a></p>'
                  f'<div class="ps-urteil unbekannt"><i>✕</i><div><b>Nicht im Passregister</b><span>{esc(HINWEIS["unbekannt"])}</span></div></div>'
                  f'<p>Geprüfte Nummer: <span class="mw-nr">{esc(nr)}</span></p>')
        return _rahmen(request, k, "Passprüfung", inhalt)
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (p["akte_id"],)).fetchone()
    s, t = meldewesen.pass_status(p)
    if not z and s == "gueltig":
        s, t = "ungueltig", "Ungültig (Inhaberakte gelöscht)"
    _protokollieren(con, k, nr, p["id"], t)
    return _rahmen(request, k, f"Passprüfung {nr}", _seite(con, k, z, p, s, request))


async def person(request):
    k = await _konto(request)
    con = request.app["db"]
    i = request.match_info["id"]
    z = con.execute("SELECT * FROM amt_akten WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if z and z["konto_id"] == k["id"] and not darf_sehen(k):
        raise web.HTTPFound(f"{BASIS}mein-pass/")
    if not darf_sehen(k):
        return web.Response(status=403, content_type="text/html", text=anmeldung.hinweis(
            "Kein Zugang", "Diese Seite ist Zoll, Polizei und Reichsverwaltung vorbehalten.", [("Zur Hauptseite", "/", True)]))
    if not z:
        raise web.HTTPNotFound(text="Person nicht gefunden.")
    _protokollieren(con, k, amt.az_akte(z["id"]), None, "Personenseite")
    return _rahmen(request, k, f"Person {amt.az_akte(z['id'])}", _seite(con, k, z, None, None, request))


async def kurzlink(request):
    code = request.match_info["code"].upper().strip("/")
    m = re.fullmatch(r"BA-?0*(\d+)", code)
    if m:
        raise web.HTTPFound(f"{PRUEF}person/{m.group(1)}/" + (f"?{request.query_string}" if request.query_string else ""))
    nr = "".join(c for c in code if c.isalnum())[:12]
    raise web.HTTPFound(f"{PRUEF}{nr}/" + (f"?{request.query_string}" if request.query_string else ""))


async def foto(request):
    """Profilbild über den Dienst ausliefern (nur angemeldet, nur für Berechtigte oder den Inhaber)."""
    k = await anmeldung.konto(request)
    kid = request.match_info["konto"]
    if not k or not (k["id"] == kid or darf_sehen(k)):
        raise web.HTTPForbidden()
    con = request.app["db"]
    r = con.execute("SELECT avatar FROM konten WHERE id=?", (kid,)).fetchone()
    if not r or not r["avatar"]:
        raise web.HTTPNotFound()
    schl = (kid, r["avatar"])
    if schl not in _FOTOS or _FOTOS[schl][0] < time.time() - 86400:
        url = f"https://cdn.discordapp.com/avatars/{kid}/{r['avatar']}.png?size=512"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s, s.get(url) as resp:
                if resp.status != 200:
                    raise web.HTTPNotFound()
                _FOTOS[schl] = (time.time(), await resp.read())
        except aiohttp.ClientError:
            raise web.HTTPNotFound()
        if len(_FOTOS) > 300:
            _FOTOS.pop(next(iter(_FOTOS)))
    return web.Response(body=_FOTOS[schl][1], content_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


SCANNER_JS = r"""<script>(function(){
var B=%s,start=document.getElementById("qr-start"),box=document.getElementById("qr-box"),video=document.getElementById("qr-video"),
 txt=document.getElementById("qr-text"),cv=document.createElement("canvas"),ctx=cv.getContext("2d",{willReadFrequently:true}),stream=null,det=null,lauf=false;
function auswerten(w){
 try{var u=new URL(w,location.href);
  if(u.hostname===location.hostname||/(^|\.)imperiumgermanicum\.de$/.test(u.hostname)){if(u.pathname.indexOf("/p/")===0||u.pathname.indexOf(B)===0)return u.pathname+u.search}
 }catch(e){}
 var nr=String(w).toUpperCase().replace(/[^A-Z0-9]/g,"");
 if(/^[A-Z0-9]{9}$/.test(nr))return B+"passpruefung/"+nr+"/";
 return null}
function stop(){lauf=false;if(stream)stream.getTracks().forEach(function(t){t.stop()});stream=null}
function schleife(){
 if(!lauf)return;
 var p=det?det.detect(video).then(function(c){return c.length?c[0].rawValue:null}):Promise.resolve((function(){
  if(!video.videoWidth||!window.jsQR)return null;var w=Math.min(960,video.videoWidth),h=Math.round(video.videoHeight*w/video.videoWidth);
  cv.width=w;cv.height=h;ctx.drawImage(video,0,0,w,h);var d=ctx.getImageData(0,0,w,h),r=jsQR(d.data,w,h,{inversionAttempts:"dontInvert"});return r?r.data:null})());
 p.catch(function(){return null}).then(function(wert){
  if(wert){var ziel=auswerten(wert);
   if(ziel){if(start.dataset.von)ziel+=(ziel.indexOf("?")<0?"?":"&")+"von="+encodeURIComponent(start.dataset.von);stop();box.classList.add("treffer");txt.textContent="Erkannt – Prüfseite wird geöffnet …";location.href=ziel;return}
   txt.textContent="Kein Dokument des Reiches erkannt."}
  setTimeout(schleife,det?150:220)})}
function laden(){return new Promise(function(ok,f){if(window.jsQR)return ok();var s=document.createElement("script");s.src=B+"statisch/jsQR.js";s.onload=ok;s.onerror=f;document.head.appendChild(s)})}
start.addEventListener("click",function(){
 box.hidden=false;start.hidden=true;txt.textContent="Kamera wird gestartet …";
 if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){txt.textContent="Dieser Browser erlaubt keinen Kamerazugriff. Bitte die Passnummer eingeben oder den QR-Code mit der Kamera-App scannen.";return}
 navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"}},audio:false}).then(function(s){
  stream=s;video.srcObject=s;return video.play()}).then(function(){
  if("BarcodeDetector" in window){try{det=new BarcodeDetector({formats:["qr_code"]})}catch(e){det=null}}
  return det?null:laden()}).then(function(){lauf=true;txt.textContent="QR-Code des Dokuments ins Bild halten.";schleife()})
 .catch(function(e){txt.textContent="Kein Kamerazugriff ("+(e&&e.name||"Fehler")+"). Bitte Kamera erlauben oder die Passnummer eingeben."})});
document.getElementById("qr-stop").addEventListener("click",function(){stop();box.hidden=true;start.hidden=false});
addEventListener("pagehide",stop);
})();</script>"""

SCANNER_CSS = """<style>.qr-scan{margin:6px 0 18px}
#qr-box{max-width:460px;border:1px solid var(--linie);border-radius:14px;padding:12px;margin-top:4px}
#qr-box .rahmen-v{position:relative;border-radius:10px;overflow:hidden;background:#000;aspect-ratio:4/3}
#qr-box video{width:100%;height:100%;object-fit:cover;display:block}
#qr-box .ziel{position:absolute;inset:18%;border:3px solid rgba(255,255,255,.85);border-radius:14px;box-shadow:0 0 0 999px rgba(0,0,0,.35)}
#qr-box.treffer .ziel{border-color:#3bd16f}
#qr-box p{margin:10px 0}</style>"""


def scanner(request, k, von=""):
    """Scanner-Block für den Tab „Passprüfung“ (Hook meldewesen.PRUEF_ZUSATZ)."""
    return (SCANNER_CSS + f'<div class="qr-scan"><button class="btn" id="qr-start" type="button" data-von="{esc(von)}">{amt.ic("camera")}QR-Code scannen</button>'
            '<div id="qr-box" hidden><div class="rahmen-v"><video id="qr-video" playsinline muted></video><span class="ziel"></span></div>'
            '<p class="az" id="qr-text"></p><button class="btn zweit" id="qr-stop" type="button">Abbrechen</button></div></div>'
            + SCANNER_JS % json.dumps(BASIS))


async def jsqr(request):
    return web.FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "statisch", "jsQR.js"),
                            headers={"Cache-Control": "public, max-age=604800", "Content-Type": "application/javascript"})


def registrieren(app):
    amt.ICONS.setdefault("camera", '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>'
                                   '<circle cx="12" cy="13" r="3"/>')
    meldewesen.PRUEF_ZUSATZ.append(scanner)
    app.router.add_get(BASIS + "statisch/jsQR.js", jsqr)
    app.router.add_get("/p/{code}", kurzlink)
    app.router.add_get(PRUEF + "person/{id}/", person)
    app.router.add_get(PRUEF + "{nr}/", pass_pruefen)
    app.router.add_get(BASIS + "pass-foto/{konto}", foto)
