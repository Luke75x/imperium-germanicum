"""Portal des Kaiserlichen Schatz- und Währungsamts unter /schatzamt/ (nginx → Dienst) – Stil der Amtsseite (amt.rahmen mit portal=…),
erreichbar für alle angemeldeten Nutzer.

Für alle (Mitglieder): Übersicht, Konto & Umsätze (Kontoauszug, PDF), Überweisen (mit Prüfschritt, Empfängersuche, Umsatz- und
Überweisungssteuer), Steuern & Gebühren (eigene Bescheide, bezahlen, PDF), Gehalt (Abrechnungen, PDF), Gewerbe (Anmeldung,
Gewerbekonto), Tarife & Sätze. Nur mit staatlichem Zugriff (Umschalter „Staatl.“): Reichsfinanzen, Goldreserven.
Für das Schatzamt (geld.ist_beamter / ist_leitung): Verwaltung (Kennzahlen), Konten (Suche, Sperre, Korrekturbuchung),
Geldpolitik (Geldschöpfung/-vernichtung, Leitzins), Gewerberegister (Anträge), Protokoll; Steuern → steuern.py, Besoldung → besoldung.py.
"""
import asyncio
import functools
import re
import secrets
import time
from datetime import date, datetime
from urllib.parse import quote, urlsplit

from aiohttp import web

import amt
import anmeldung
import bereiche
import geld
import meldewesen
from geld import mark, nummer_anzeige

esc = amt.esc
PFAD = "/schatzamt/"
BRANCHEN = ["Handel", "Handwerk", "Landwirtschaft", "Gastronomie & Beherbergung", "Verkehr & Logistik", "Bank & Versicherung",
            "Medien & Verlag", "Bau", "Industrie & Rüstung", "Dienstleistung", "Kunst & Kultur", "Sonstiges"]

amt.ICONS.update({
    "wallet": '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/>'
              '<path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    "receipt": '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17.5v-11"/>',
    "banknote": '<rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
    "store": '<path d="m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7"/><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>'
             '<path d="M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4"/><path d="M2 7h20"/>',
    "coins": '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>',
    "chart-column": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "arrow-right-left": '<path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/>',
    "percent": '<line x1="19" x2="5" y1="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
})

CSS = """<style>
.kennzahlen{grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}
.kennzahlen b{white-space:nowrap;font-size:22px;overflow:hidden;text-overflow:ellipsis}
@media (max-width:520px){.kennzahlen{grid-template-columns:repeat(2,minmax(0,1fr))}html .kennzahlen b{font-size:19px!important;letter-spacing:-.01em}}
.sa-saldo{font-size:34px;font-weight:700;letter-spacing:-.01em;line-height:1.1;margin:4px 0}
.anker:target{background:#fff3b0;box-shadow:0 0 0 4px #fff3b0;border-radius:3px;scroll-margin-top:90px}
.sa-plus{color:var(--ok)}.sa-minus{color:var(--rot)}
.sa-nr{font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.04em}
.sa-karten{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px;margin:12px 0 4px}
.sa-karte{border:1px solid var(--linie);border-radius:12px;padding:16px 18px;background:#fff}
.sa-karte small{display:block;color:var(--grau);font-size:12px;letter-spacing:.06em;text-transform:uppercase}
.sa-karte .sa-name{font-weight:650;font-size:16px;margin-top:2px}
.sa-karte .sa-aktionen{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.sa-betrag{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.sa-pruef{border:1px solid var(--linie);border-radius:12px;padding:18px 20px;max-width:620px;margin:12px 0}
.sa-pruef .sa-saldo{font-size:28px}
.sa-formular{max-width:760px}
.sa-formular .zeilen{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-bottom:10px}
.sa-formular label{display:block}
.sa-formular input[type=text],.sa-formular input[type=password],.sa-formular input[type=search],.sa-formular select,.sa-formular textarea{width:100%}
.sa-hinweis{color:var(--grau);font-size:13.5px}
.sa-leiste{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin:6px 0 10px}
.sa-leiste>div{min-width:150px}
table.liste td.sa-betrag,table.liste th.sa-betrag{text-align:right}
.sa-modus{display:flex;border:1px solid var(--ink);border-radius:999px;padding:2px;margin:0 8px 12px;background:#fff}
.sa-modus a{flex:1;text-align:center;padding:5px 10px;border-radius:999px;font-size:13px;font-weight:600;letter-spacing:.02em;color:var(--ink);text-decoration:none}
.sa-modus a:hover{background:var(--hell)}
.sa-modus a.rp{flex:0 0 auto;padding:5px 8px;font-size:10.5px;font-weight:500;letter-spacing:.08em;opacity:.45}
.sa-modus a.rp:hover,.sa-modus a.rp.aktiv{opacity:1}
.sa-haken{display:flex;gap:8px;align-items:center;margin:6px 0;font-size:14px}.sa-haken input{width:auto}
.sa-modus a.aktiv,.sa-modus a.aktiv:hover{background:var(--ink);color:#fff}
.kopf .sa-modus{display:none;margin:0 0 0 4px}
@media (max-width:800px){.kopf .sa-modus{display:flex}.kopf .sa-modus a{padding:5px 9px;font-size:12.5px}}
.sa-karte.sa-mein{border-color:var(--ink);box-shadow:0 0 0 1px var(--ink)}
.sa-werte{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:10px 0 0;font-size:13.5px}
.sa-werte dt{color:var(--grau)}.sa-werte dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
.sa-zusatz{margin:2px 0 0}
.sa-rot{color:var(--rot);font-weight:600}
.sa-inline{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0}
.sa-inline input[type=number]{width:80px}
.btn.klein{padding:5px 10px;font-size:13px}
.sa-bereich{margin:0 0 14px}
.sa-bereich-kopf{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin:0 0 6px}
.sa-bereich-name{display:flex;gap:8px;align-items:center;font-size:12.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--grau)}
.sa-bereich-name .icon{width:16px;height:16px}
.sa-bereich select{padding:4px 8px;font-size:13.5px;max-width:100%}
.sa-bereich .reiter{flex-wrap:nowrap;overflow-x:auto;gap:4px 20px;margin:0;scrollbar-width:thin}
.sa-bereich .reiter a{white-space:nowrap;padding:9px 2px}
.sa-todo{display:grid;gap:8px;margin:12px 0 6px}
.sa-todo>div{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--linie);border-radius:12px;padding:10px 14px;background:#fff;font-size:14px}
.sa-todo>div.warn{border-color:var(--ink);box-shadow:0 0 0 1px var(--ink)}
.sa-todo .icon{width:18px;height:18px;flex:none;margin-top:1px}
.sa-todo b{font-weight:650}
.sa-todo .az{display:block;margin-top:2px}
.sa-spalten{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:0 24px;align-items:start}
.sa-schnell{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin:14px 0 6px}
.sa-schnell a{display:grid;grid-template-columns:auto 1fr;column-gap:10px;align-items:center;border:1px solid var(--linie);border-radius:12px;
 padding:12px 14px;color:var(--ink);text-decoration:none;background:#fff}
.sa-schnell a:hover{border-color:var(--ink)}
.sa-schnell a .icon{grid-row:span 2}
.sa-schnell a span{color:var(--grau);font-size:12.5px}
.sa-erkl{border:1px solid var(--linie);border-radius:12px;padding:14px 18px;margin:16px 0;background:var(--hell);font-size:14px}
.sa-erkl ol{margin:6px 0 0;padding-left:20px}.sa-erkl li{margin:4px 0}
.sa-status{display:flex;gap:8px;align-items:center;margin:8px 0;color:var(--grau)}
.sa-status.ok{color:var(--ok)}
details.sa-auf{border:1px solid var(--linie);border-radius:12px;padding:0 16px;margin:16px 0;background:#fff}
details.sa-auf>summary{cursor:pointer;padding:12px 0;font-weight:600;display:flex;gap:8px;align-items:center;list-style:none}
details.sa-auf>summary::-webkit-details-marker{display:none}
details.sa-auf>summary::after{content:"+";margin-left:auto;font-size:18px;color:var(--grau)}
details.sa-auf[open]>summary::after{content:"–"}
details.sa-auf[open]{padding-bottom:12px}
table.sa-haushalt td:nth-child(n+2),table.sa-haushalt th:nth-child(n+2){text-align:right;white-space:nowrap}
@media (max-width:800px){
 html table.liste.sa-haushalt tr{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px 10px;padding:10px 12px}
 html table.liste.sa-haushalt td{display:block;width:auto;padding:0;border:0;text-align:left;white-space:normal;font-size:13.5px}
 html table.liste.sa-haushalt td:first-child{grid-column:1/-1;font-weight:650;font-size:15px}
 html table.liste.sa-haushalt td:first-child::before{display:none}
 html table.liste.sa-haushalt td::before{font-size:11px}
}
</style>"""


# ---------------------------------------------------------------- Rahmen, Rechte, Hilfen

# ---- Modus „Staatl.“ / „Privat“ (Umschalter unter dem Logo; Cookie, nur für Konten mit staatlichem Zugriff)
MODUS_COOKIE = "sa_modus"
PRIVATARTEN = ("privat", "gewerbe")
NUR_PRIVAT = ("sa-steuern", "sa-gehalt", "sa-gewerbe", "sa-bankkarte", "sa-besitz")     # Seiten, die nur die Privatperson betreffen
NUR_STAAT = ("sa-finanzen", "sa-gold", "sa-etats", "sa-staatshaushalt", "sa-verteidigung", "sa-notlage", "sa-etatverteilung", "sa-etatplanung", "sa-entwicklung", "sa-krisen", "sa-teilstaat", "sa-reich", "sa-handel")                     # staatliche Information: nur mit staatlichem Zugriff einsehbar


def hat_kassen(con, k):
    """Staatliche Kassen in eigener Verfügung oder Schatzamt: Zugang zu Kassen, Etats, Staatshaushalt, Reichsfinanzen, Gold."""
    if not k or not k["mitglied"]:
        return False
    if "_sa_kassen" not in k:
        k["_sa_kassen"] = geld.ist_beamter(k) or any(r["art"] not in PRIVATARTEN for r in geld.verfuegbare_konten(con, k))
    return k["_sa_kassen"]


def hat_verteidigung(con, k):
    """Sieht etwas aus dem Bereich Verteidigung (Führungsstab/Kaiser/Kanzler alles, Militär und Landesherren ihren Teilstaat)."""
    import verteidigung
    return bool(k) and k["mitglied"] and verteidigung.sicht(con, k)["irgendwas"]


def hat_staat(con, k):
    """Staatlicher Zugriff irgendeiner Art – nur dann gibt es den Umschalter Staatl./Privat."""
    return hat_kassen(con, k) or hat_verteidigung(con, k)


def ist_rp(k):
    """Server- und RP-Leitung (Discord-Administratoren): dritte Ansicht „RP“."""
    return bool(k) and bool(k["mitglied"]) and bool(k["admin"])


def modus(request, k):
    """'staat', 'privat' oder 'rp' (gewählt per Umschalter, gespeichert im Cookie; ohne Zugriff immer 'privat')."""
    if "sa_modus" not in request:
        c = request.cookies.get(MODUS_COOKIE)
        if c == "rp" and ist_rp(k):
            request["sa_modus"] = "rp"
        elif c == "staat" and hat_staat(request.app["db"], k):
            request["sa_modus"] = "staat"
        else:
            request["sa_modus"] = "privat"
    return request["sa_modus"]


def konten_im_modus(con, k, m):
    """Verfügbare Konten des Modus: privat = Privat- und Gewerbekonten, staat = alle übrigen (Kassen, Behörden, Teilstaaten)."""
    return [r for r in geld.verfuegbare_konten(con, k) if (r["art"] in PRIVATARTEN) == (m == "privat")]


def _umschalter(m, aktiv, staat=True, rp=False):
    def a(wert, text, klasse="", titel=""):
        ziel = PFAD + "modus/" + wert
        if aktiv and aktiv not in ("sa-start", "sa-konto", "sa-ueberweisen", "sa-tarife", "sa-etatuebersicht"):
            ziel += "?weiter=" + quote(PFAD)
        kl = (klasse + (" aktiv" if m == wert else "")).strip()
        return (f'<a href="{ziel}" class="{kl}"{" aria-current=true" if m == wert else ""}' + (f' title="{titel}" aria-label="{titel}"' if titel else "") + f'>{text}</a>')
    return ('<nav class="sa-modus" aria-label="Ansicht">' + (a("staat", "Staatl.") if staat else "") + a("privat", "Privat")
            + (a("rp", "RP", "rp", "RP-Leitung") if rp else "") + '</nav>')


async def modus_setzen(request):
    m = {"staat": "staat", "rp": "rp"}.get(request.match_info["m"], "privat")
    if m == "rp" and not ist_rp(await anmeldung.konto(request)):
        m = "privat"
    u = urlsplit(request.query.get("weiter") or request.headers.get("Referer") or PFAD)
    ziel = u.path if u.path.startswith(PFAD) and not u.path.startswith(PFAD + "modus/") else PFAD
    if ziel != PFAD and u.query:   # Kontowahl (?konto=) gilt nur im alten Modus, Meldungen nicht wiederholen
        rest = "&".join(x for x in u.query.split("&") if x.split("=")[0] not in ("konto", "von", "m", "f"))
        ziel += "?" + rest if rest else ""
    r = web.HTTPSeeOther(ziel)
    r.set_cookie(MODUS_COOKIE, m, max_age=365 * 86400, path=PFAD, samesite="Lax", httponly=True, secure=amt.config.SITE_URL.startswith("https"))
    raise r


# ---------------------------------------------------------------- Haushalt: Reiter „Mein Teilstaat“ und „Reichshaushalt“

def _regierte(con, k):
    """{Teilstaat-ID: Staatskasse} der Teilstaaten, die das Konto regiert (je Anfrage zwischengespeichert)."""
    if not k or not k["mitglied"]:
        return {}
    if "_sa_regiert" not in k:
        import karte
        staaten = karte.aktuell(con)["stand"]["staaten"]
        eigene = karte.fraktionen(set(k["rollen"]), staaten)
        own = {x["id"] for x in staaten if x.get("fraktion") in eigene}   # der eigene Teilstaat steht vorn, dann alphabetisch
        rs = sorted(geld.regierte_staatskassen(con, k), key=lambda r: (r["stelle"][3:] not in own, r["name"]))
        k["_sa_regiert"] = {r["stelle"][3:]: r for r in rs}
    return k["_sa_regiert"]


def _ts_url(tab, sid, regiert):
    z = "ts-" + sid
    return PFAD + {"start": f"teilstaat/?ziel={z}", "etat": f"etatverteilung/?ziel={z}", "entw": f"entwicklung/?ziel={z}", "krisen": f"krisen/?ziel={z}", "plan": f"etatplanung/?ziel={z}", "vt": f"verteidigung/{sid}/",
                   "notlage": f"notlagen/?bereich={z}", "kasse": f"konto/?konto={regiert[sid]['id']}"}[tab]


def _teilstaat_tabs(con, k, sid):
    import etatplan
    import verteidigung
    import krisen
    n_kr = krisen.offene_anzahl(con, "ts-" + sid)
    tabs = [("start", "Überblick"), ("etat", "Etat"), ("entw", "Entwicklung"), ("krisen", f"Krisen ({n_kr})" if n_kr else "Krisen")]
    if etatplan.darf_aendern(con, k, "ts-" + sid):
        tabs.append(("plan", "Etat planen"))
    if verteidigung.darf_sehen(con, k, sid):
        tabs.append(("vt", "Verteidigung"))
    return tabs + [("notlage", "Haushaltsnotlage"), ("kasse", "Kasse & Umsätze")]


def _reich_tabs(con, k):
    import etatplan
    tabs = [("haushalt", "Staatshaushalt", "haushalt/"), ("etat", "Etatverteilung", "etatverteilung/?ziel=reich"), ("entw", "Entwicklung", "entwicklung/?ziel=reich"), ("krisen", "Krisen", "krisen/?ziel=reich")]
    if etatplan.darf_aendern(con, k, "reich"):
        tabs.append(("plan", "Etat planen", "etatplanung/?ziel=reich"))
    tabs += [("etats", "Etats der Behörden", "etats/"), ("finanzen", "Reichsfinanzen", "finanzen/"), ("gold", "Goldreserven", "gold/"),
             ("notlage", "Haushaltsnotlagen", "notlagen/?bereich=reich")]
    if hat_verteidigung(con, k):
        tabs.append(("vt", "Verteidigung", "verteidigung/"))
    return tabs


def _reiter_kontext(request, k, con, aktiv):
    """(Bereich, Teilstaat-ID, Reiter) der aktuellen Seite: Bereich 'ts' = Mein Teilstaat, 'reich' = Reichshaushalt; None = Seite gehört zu keinem Bereich."""
    if aktiv not in ("sa-teilstaat", "sa-etatverteilung", "sa-etatplanung", "sa-entwicklung", "sa-krisen", "sa-verteidigung", "sa-notlage", "sa-konto",
                     "sa-staatshaushalt", "sa-finanzen", "sa-etats", "sa-gold"):
        return None
    regiert = _regierte(con, k)
    q = request.query
    ziel = q.get("ziel", "")
    if aktiv == "sa-teilstaat":
        sid = ziel[3:] if ziel.startswith("ts-") and ziel[3:] in regiert else next(iter(regiert), None)
        return ("ts", sid, "start") if sid else None
    if aktiv in ("sa-etatverteilung", "sa-etatplanung", "sa-entwicklung", "sa-krisen"):
        tab = {"sa-etatverteilung": "etat", "sa-etatplanung": "plan", "sa-entwicklung": "entw", "sa-krisen": "krisen"}[aktiv]
        if ziel.startswith("ts-") and ziel[3:] in regiert:
            return "ts", ziel[3:], tab
        if ziel == "reich" or (ziel.startswith("ts-") and ziel[3:] not in regiert):
            return "reich", None, tab
        return ("ts", next(iter(regiert)), tab) if regiert else ("reich", None, tab)
    if aktiv == "sa-verteidigung":
        sid = request.match_info.get("sid", "")
        return ("ts", sid, "vt") if sid in regiert else ("reich", None, "vt")
    if aktiv == "sa-notlage":
        b = q.get("bereich", "")
        if b.startswith("ts-") and b[3:] in regiert:
            return "ts", b[3:], "notlage"
        if b == "reich" or not regiert:
            return "reich", None, "notlage"
        return ("reich", None, "notlage") if (geld.ist_leitung(k) or amt.ROLLE_KANZLER in k["rollen"]) else ("ts", next(iter(regiert)), "notlage")
    if aktiv == "sa-konto":
        r = _konto_waehlen(con, k, request)[0]   # das angezeigte Konto: Staats- oder Verteidigungskasse eines regierten Teilstaats → Reiter „Kasse & Umsätze“
        sid = (r["stelle"] or "")[3:] if r and (r["stelle"] or "")[:3] in ("ts-", "vt-") else ""
        return ("ts", sid, "kasse") if sid in regiert else None
    return "reich", None, {"sa-staatshaushalt": "haushalt", "sa-finanzen": "finanzen", "sa-etats": "etats", "sa-gold": "gold"}[aktiv]


def reiter_html(request, k, con, aktiv):
    """(HTML der Reiterleiste, Schlüssel für die Seitenleiste). Alles zu einem Haushalt – Teilstaat oder Reich – liegt hinter einem Eintrag der Seitenleiste."""
    if not k or not k["mitglied"]:
        return "", aktiv
    ctx = _reiter_kontext(request, k, con, aktiv)
    if not ctx:
        return "", aktiv
    bereich, sid, tab = ctx
    if bereich == "reich" and not hat_kassen(con, k):
        return "", aktiv   # Militär ohne Kasse: kein Reichshaushalt, die Seitenleiste führt direkt zu „Verteidigung“
    if bereich == "ts":
        regiert = _regierte(con, k)
        links = "".join(f'<a href="{esc(_ts_url(t, sid, regiert))}"{" class=aktiv aria-current=page" if t == tab else ""}>{esc(n)}</a>' for t, n in _teilstaat_tabs(con, k, sid))
        wahl = ""
        if len(regiert) > 1:
            opt = "".join(f'<option value="{esc(_ts_url(tab, s_, regiert))}"{" selected" if s_ == sid else ""}>{esc(r["name"].replace("Staatskasse ", ""))}</option>'
                          for s_, r in regiert.items())
            wahl = f'<select aria-label="Teilstaat wählen" onchange="location.href=this.value">{opt}</select>'
        else:
            wahl = f'<b>{esc(regiert[sid]["name"].replace("Staatskasse ", ""))}</b>'
        kopf = f'<span class="sa-bereich-name">{amt.ic("flag")}Mein Teilstaat</span>{wahl}'
        schl = "sa-teilstaat"
    else:
        links = "".join(f'<a href="{PFAD}{u}"{" class=aktiv aria-current=page" if t == tab else ""}>{esc(n)}</a>' for t, n, u in _reich_tabs(con, k))
        kopf = f'<span class="sa-bereich-name">{amt.ic("landmark")}Reichshaushalt</span>'
        schl = "sa-reich"
    banner = ""
    if bereich == "ts" and tab != "krisen":
        import krisen
        banner = krisen.banner_html(con, "ts-" + sid)   # offene Krise: Handlungszwang
    return f'<div class="sa-bereich"><div class="sa-bereich-kopf">{kopf}</div><nav class="reiter" aria-label="Bereich">{links}</nav></div>{banner}', schl


def nav(k, m="privat", schalter=False, aktiv="", con=None):
    if m == "rp":
        mein = [("sa-rp", "layout-dashboard", "Lagebild", "rp/"), ("sa-rp-faelle", "folder-open", "Fälle", "rp/faelle/"),
                ("sa-rp-konten", "search", "Konten & Personen", "rp/konten/"), ("sa-rp-protokoll", "scroll-text", "Protokoll", "rp/protokoll/")]
        gruppen = [("RP-Leitung", mein),
                   ("Konfiguration", [("sa-rp-foerder", "package", "Förderstätten", "rp/foerderstaetten/"), ("sa-rp-handel", "percent", "Handel: Waren & Regeln", "rp/handel/"),
                                      ("sa-rp-besitz", "car", "Besitzkatalog & Kosten", "rp/besitz/")]),
                   ("Hilfsmittel", [("sa-amt-bankkarten", "credit-card", "Bankkarten", "amt/bankkarten/"),
                                                          ("sa-amt-geld", "coins", "Geldpolitik", "amt/geldpolitik/"),
                                                          ("sa-amt-tarife", "percent", "Sätze festlegen", "amt/tarife/")])]
    elif m == "staat":
        kassen = con is None or hat_kassen(con, k)
        vt = con is None or hat_verteidigung(con, k)
        mein = [("sa-start", "layout-dashboard", "Übersicht", "")]
        if kassen:
            mein += [("sa-konto", "wallet", "Kassen & Umsätze", "konto/"), ("sa-ueberweisen", "arrow-right-left", "Überweisen", "ueberweisen/")]
        regiert = con is None or bool(_regierte(con, k))
        # Alles zu einem Haushalt liegt hinter einem Eintrag (Reiter oben auf der Seite): Mein Teilstaat, Reichshaushalt; Verteidigung nur für das Militär ohne Kasse
        haushalt = [e for e, ok in ((("sa-teilstaat", "flag", "Mein Teilstaat", "teilstaat/"), regiert),
                                    (("sa-reich", "landmark", "Reichshaushalt", "haushalt/"), kassen),
                                    (("sa-handel", "package", "Handel", "handel/"), kassen),
                                    (("sa-verteidigung", "shield", "Verteidigung", "verteidigung/"), vt and not kassen)) if ok]
        gruppen = [("Staatliche Kassen" if kassen else "Dienstlich", mein), ("Haushalt", haushalt),
                   ("Information", [("sa-etatuebersicht", "chart-pie", "Etatübersicht", "etatuebersicht/"), ("sa-tarife", "percent", "Tarife & Sätze", "tarife/")])]
        gruppen = [g for g in gruppen if g[1]]
        mein = mein + [e for e in haushalt if e[0] in ("sa-teilstaat", "sa-reich", "sa-verteidigung")][:4 - len(mein)]
    else:
        mein = [("sa-start", "layout-dashboard", "Übersicht", ""), ("sa-konto", "wallet", "Konto & Umsätze", "konto/"),
                ("sa-ueberweisen", "arrow-right-left", "Überweisen", "ueberweisen/"), ("sa-steuern", "receipt", "Steuern & Gebühren", "steuern/"),
                ("sa-gehalt", "banknote", "Gehalt", "gehalt/"), ("sa-gewerbe", "store", "Gewerbe", "gewerbe/"),
                ("sa-besitz", "car", "Besitz", "besitz/")]
        gruppen = [("Bankkarte", [("sa-bankkarte", "credit-card", "Bankkarte & PIN", "bankkarte/")]), ("Mein Geld", mein),
                   ("Information", [("sa-etatuebersicht", "chart-pie", "Etatübersicht", "etatuebersicht/"), ("sa-tarife", "percent", "Tarife & Sätze", "tarife/")])]
    if m == "rp":
        pass
    elif m == "staat" and geld.ist_beamter(k):
        amtl = [("sa-amt", "landmark", "Verwaltung", "amt/"), ("sa-amt-konten", "wallet", "Konten", "amt/konten/"),
                ("sa-amt-steuern", "receipt", "Steuerverwaltung", "amt/steuern/"), ("sa-amt-gewerbe", "store", "Gewerberegister", "amt/gewerbe/"),
                ("sa-amt-bankkarten", "credit-card", "Bankkarten", "amt/bankkarten/")]
        if geld.ist_leitung(k):
            amtl += [("sa-amt-besoldung", "users", "Besoldung & Lohnlauf", "amt/besoldung/"), ("sa-amt-geld", "coins", "Geldpolitik", "amt/geldpolitik/"),
                     ("sa-amt-tarife", "percent", "Sätze festlegen", "amt/tarife/")]
        amtl.append(("sa-amt-protokoll", "scroll-text", "Protokoll", "amt/protokoll/"))
        gruppen.append(("Schatzamt", amtl))
    weiter = []
    if k["mitglied"]:
        weiter.append(("post", "mail", "Postfach", amt.BASIS + "postfach/"))
    if anmeldung._amt_zugang(k):
        weiter.append(("amtsseite", "layout-grid", "Amtsseite", amt.BASIS))
    weiter.append(("profil", "users", "Mein Profil", "/profil/"))
    gruppen.append(("Weiteres", weiter))
    out = {"basis": PFAD, "gruppen": gruppen, "haupt": mein[:4], "logo": geld.STELLE, "name": "Schatzamt"}
    if schalter:
        out["unter_logo"] = out["kopf_zusatz"] = _umschalter(m, aktiv, hat_staat(con, k) if con is not None else True, ist_rp(k))
    return out


_KZ = re.compile(r'<div><b>(−?)([\d.]+),(\d\d) Kr</b>')


def _kennzahlen_kurz(html_):
    """Beträge in Kennzahl-Kacheln kürzen (sonst ragen große Summen über den Rand); voller Betrag als Tooltip."""
    def ersetzen(m):
        pf = int(m.group(2).replace(".", "") + m.group(3)) * (-1 if m.group(1) else 1)
        return f'<div title="{mark(pf)}"><b>{geld.mark_kurz(pf)}</b>'
    return _KZ.sub(ersetzen, html_)


def ant(request, k, titel, aktiv, inhalt, status=200):
    schalter = hat_staat(request.app["db"], k) or ist_rp(k)
    m = modus(request, k)
    if aktiv.startswith("sa-rp"):
        m = "rp"
    elif m == "rp" and aktiv.startswith("sa-amt"):
        pass                 # Hilfsmittel der RP-Leitung bleiben in der RP-Ansicht
    elif schalter and (aktiv.startswith("sa-amt") or aktiv in NUR_STAAT):
        m = "staat"          # Verwaltungsseiten gehören immer zur staatlichen Ansicht
    elif aktiv in NUR_PRIVAT:
        m = "privat"
    reiter, nav_aktiv = reiter_html(request, k, request.app["db"], aktiv)   # Reiter Teilstaat / Reichshaushalt; die Seitenleiste markiert den Bereich
    portal = nav(k, m, schalter, nav_aktiv, request.app["db"])
    if k["mitglied"]:
        import suche
        portal["suche"] = suche.leiste(request.query.get("q", "") if aktiv == "sa-suche" else "")
    return web.Response(status=status, content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, nav_aktiv, CSS + _kennzahlen_kurz(reiter + inhalt), k, request["csrf"], portal=portal))


def seite(recht=None):
    """Dekorator: Anmeldung nötig; recht = 'mitglied' | 'staat' (staatlicher Zugriff, hat_staat) | 'beamter' | 'leitung'.
    Handler bekommt (request, konto)."""
    def deko(h):
        @functools.wraps(h)
        async def inner(request):
            k = await anmeldung.konto(request)
            if not k:
                raise web.HTTPFound("/anmelden/?weiter=" + quote(request.path_qs))
            ok = {"mitglied": k["mitglied"], "beamter": geld.ist_beamter(k), "leitung": geld.ist_leitung(k), "rp": ist_rp(k)}.get(recht, True)
            if recht == "staat":
                ok = hat_kassen(request.app["db"], k)
            elif recht == "verteidigung":
                ok = hat_verteidigung(request.app["db"], k)
            if not ok:
                text = {"mitglied": "Diese Funktion steht nur Mitgliedern unseres Discord-Servers zur Verfügung.",
                        "staat": "Dieser Bereich ist staatlich und nur für Amtsträger mit Verfügung über eine staatliche Kasse einsehbar.",
                        "verteidigung": "Der Bereich Verteidigung ist dem Militär (für den eigenen Teilstaat), den Landesherren, dem Führungsstab, "
                                        "dem Kanzler und dem Kaiser vorbehalten.",
                        "rp": "Dieser Bereich ist der Server- und RP-Leitung vorbehalten.",
                        "beamter": "Dieser Bereich ist dem Kaiserlichen Schatz- und Währungsamt vorbehalten.",
                        "leitung": "Dieser Bereich ist der Leitung des Schatz- und Währungsamts vorbehalten."}[recht]
                return ant(request, k, "Kein Zugang", "", f'<h1>Kein Zugang</h1><div class="warnung">{esc(text)}</div>', 403)
            return await h(request, k)
        return inner
    return deko


async def formular(request):
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), request["csrf"]):
        raise web.HTTPForbidden(text="Ungültige Anfrage (Sitzung abgelaufen?). Bitte Seite neu laden.")
    return form


def weiter(pfad, text, fehler=False):
    raise web.HTTPSeeOther(pfad + ("&" if "?" in pfad else "?") + "m=" + quote(text) + ("&f=1" if fehler else ""))


def dm(request, konto_id, text):
    if konto_id:
        asyncio.get_event_loop().create_task(request.app["discord"].dm(konto_id, text))


def betrag_html(pf, vorzeichen=True, kurz=False):
    """Betrag farbig; kurz=True kürzt große Beträge (ab 1 Mio. Kr, z. B. „11,70 Mrd. Kr“) mit vollem Betrag als Tooltip."""
    klasse = "sa-plus" if pf > 0 else "sa-minus" if pf < 0 else ""
    if kurz and abs(pf) >= 100 * 10 ** 6:
        return f'<span class="{klasse}" title="{mark(pf, vorzeichen)}">{geld.mark_kurz(pf)}</span>'
    return f'<span class="{klasse}">{mark(pf, vorzeichen)}</span>'


def werte_html(paare):
    """Kompakte Liste Bezeichnung → Wert für Karten (statt breiter Tabelle)."""
    return '<dl class="sa-werte">' + "".join(f"<dt>{esc(t)}</dt><dd>{v}</dd>" for t, v in paare) + "</dl>"


def konto_kurz(r):
    return f'{esc(r["name"])} <span class="sa-nr az">{nummer_anzeige(r["nummer"])}</span>' if r else "–"


def _f(form, feld, n=200):
    return " ".join(str(form.get(feld, "")).split())[:n]


def umsatz_zeilen(con, konto_id, buchungen, verwaltung=False):
    namen = {}

    def gegen(i):
        if i is None:
            return "–"
        if i not in namen:
            r = geld.konto(con, i)
            namen[i] = (r["name"], r["nummer"]) if r else ("?", "")
        n, nr = namen[i]
        link = f'{PFAD}amt/konten/{i}/' if verwaltung else None
        name = f'<a href="{link}">{esc(n)}</a>' if link else esc(n)
        return f'{name}<br><span class="sa-nr az">{nummer_anzeige(nr)}</span>'

    zeilen = []
    for b in buchungen:
        ein = b["an"] == konto_id
        betrag = b["betrag"] if ein else -b["betrag"]
        saldo = b["saldo_an"] if ein else b["saldo_von"]
        zeilen.append((amt._zeit(b["zeit"]), gegen(b["von"] if ein else b["an"]), esc(geld.BUCHUNGSART.get(b["art"], b["art"])),
                       esc(b["zweck"]) + (f' <span class="az">· {esc(b["bezug"])}</span>' if b["bezug"] else ""),
                       f'<span class="sa-betrag">{betrag_html(betrag)}</span>',
                       f'<span class="sa-betrag az">{mark(saldo) if saldo is not None else "–"}</span>'))
    return zeilen


def umsaetze(con, konto_id, limit=50, von=None, bis=None, q=""):
    wo, args = ["(von=? OR an=?)"], [konto_id, konto_id]
    if von:
        wo.append("zeit>=?"); args.append(von)
    if bis:
        wo.append("zeit<?"); args.append(bis)
    if q:
        wo.append("(zweck LIKE ? OR bezug LIKE ?)"); args += [f"%{q}%", f"%{q}%"]
    return con.execute(f"SELECT * FROM gk_buchungen WHERE {' AND '.join(wo)} ORDER BY id DESC LIMIT ?", args + [limit]).fetchall()


UMSATZ_KOPF = ["Zeit", "Auftraggeber / Empfänger", "Art", "Verwendungszweck", "Betrag", "Saldo danach"]


def _monat_grenzen(m):
    """'2026-11' → (ts_start, ts_ende) oder (None, None)."""
    try:
        d = datetime.strptime(m, "%Y-%m")
    except (TypeError, ValueError):
        return None, None
    n = datetime(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return int(d.timestamp()), int(n.timestamp())


def _monate(con, konto_id):
    rows = con.execute("SELECT DISTINCT strftime('%Y-%m', zeit, 'unixepoch', 'localtime') m FROM gk_buchungen WHERE von=? OR an=? ORDER BY m DESC",
                       (konto_id, konto_id)).fetchall()
    return [r["m"] for r in rows]


def _monatsname(m):
    namen = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
    try:
        j, mo = m.split("-")
        return f"{namen[int(mo) - 1]} {j}"
    except (ValueError, IndexError):
        return m


def _konto_waehlen(con, k, request):
    """Gewähltes eigenes Konto (?konto=ID) aus den verfügbaren Konten des Modus (Staatl./Privat), sonst das erste davon."""
    konten = konten_im_modus(con, k, modus(request, k))
    i = request.query.get("konto", "")
    r = next((x for x in konten if str(x["id"]) == i), None) or (konten[0] if konten else None)
    return r, konten


def _konto_auswahl(konten, aktiv, pfad):
    if len(konten) < 2:
        return ""
    return ('<p class="reiter">' + " ".join(
        f'<a href="{pfad}?konto={r["id"]}" class="{"aktiv" if r["id"] == aktiv["id"] else ""}">{esc(r["name"])}</a>' for r in konten) + "</p>")


# ---------------------------------------------------------------- Bürger: Übersicht

@seite()
async def uebersicht(request, k):
    import steuern
    import besoldung
    con = request.app["db"]
    if not k["mitglied"]:
        return ant(request, k, "Übersicht", "sa-start", f'<h1>{amt.ic("landmark")} {esc(geld.NAME)}</h1>'
                   '<div class="warnung">Ein Konto beim Schatzamt können nur Mitglieder unseres Discord-Servers eröffnen.</div>')
    if modus(request, k) == "rp":
        raise web.HTTPFound(PFAD + "rp/")
    if modus(request, k) == "staat":
        return _uebersicht_staat(request, k, con)
    p = geld.privatkonto(con, k["id"], k=k)
    konten = konten_im_modus(con, k, "privat")
    offen = steuern.offene_bescheide(con, [r["id"] for r in konten if r["art"] in ("privat", "gewerbe")])
    summe_offen = sum(steuern.offen(b) for b in offen)
    letzte = besoldung.letzte_abrechnung(con, k["id"])
    kz = [("Kontostand", mark(p["saldo"])), ("Offene Steuern & Gebühren", mark(summe_offen)),
          ("Letztes Gehalt (netto)", mark(letzte["netto"]) if letzte else "–"), ("Leitzins", f'{geld.einstellung(con, "leitzins")} %')]
    inhalt = (f'<h1>{amt.ic("landmark")} Guten Tag, {esc(geld.anzeigename(con, k["id"], k["name"]))}</h1>'
              f'<p class="az">Ihre Konten beim Kaiserlichen Schatz- und Währungsamt</p>{amt.meldung(request)}'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              f'<h2>Meine Konten</h2><div class="sa-karten">{_karten(konten)}</div>'
              + ("<h2>Offene Steuern & Gebühren</h2>" + steuern.bescheid_tabelle(con, offen, f"{PFAD}steuern/") if offen else "")
              + f'<h2>Letzte Umsätze</h2>' + amt.tabelle(UMSATZ_KOPF, umsatz_zeilen(con, p["id"], umsaetze(con, p["id"], 8)), "Noch keine Umsätze.")
              + f'<p><a href="{PFAD}konto/">Alle Umsätze und Kontoauszüge →</a></p>')
    return ant(request, k, "Übersicht", "sa-start", inhalt)


def _uebersicht_staat(request, k, con):
    """Staatliche Ansicht: nur die Kassen, über die die Person dienstlich verfügt (Behörden, Staatskassen, Reichskasse …);
    Militär ohne eigene Kasse sieht hier den Verteidigungsbereich seines Teilstaats."""
    if not hat_kassen(con, k):
        return _uebersicht_militaer(request, k, con)
    konten = konten_im_modus(con, k, "staat")
    kz = [("Guthaben der Kassen", mark(sum(r["saldo"] for r in konten))), ("Kassen in Verfügung", str(len(konten))),
          ("Leitzins", f'{geld.einstellung(con, "leitzins")} %')]
    if geld.ist_beamter(k):
        kz.append(("Geldmenge im Umlauf", mark(geld.geldmenge(con))))
    letzte = ""
    if konten:
        r = konten[0]
        letzte = (f'<h2>Letzte Umsätze · {esc(r["name"])}</h2>'
                  + amt.tabelle(UMSATZ_KOPF, umsatz_zeilen(con, r["id"], umsaetze(con, r["id"], 8)), "Noch keine Umsätze.")
                  + f'<p><a href="{PFAD}konto/">Alle Kassen, Umsätze und Kontoauszüge →</a></p>')
    leer = ('<div class="hinweis">Ihnen ist keine staatliche Kasse zur Verfügung zugewiesen.'
            + (" Die Verwaltung des Schatzamts finden Sie in der Navigation." if geld.ist_beamter(k) else "") + "</div>")
    zusatz = _kassen_zusatz(con, konten)
    gruppen = [("Reich", [r for r in konten if r["art"] == "sonder"]), ("Behörden", [r for r in konten if r["art"] == "behoerde"]),
               ("Teilstaaten", [r for r in konten if r["art"] == "teilstaat"]), ("Verteidigung", [r for r in konten if r["art"] == "verteidigung"])]
    kassen = "".join(f'<h2>{esc(t)}</h2><div class="sa-karten">{_karten(rs, zusatz)}</div>' for t, rs in gruppen if rs) or leer
    schnell = (f'<div class="sa-schnell">'
               + (f'<a href="{PFAD}teilstaat/">{amt.ic("flag")}<b>Mein Teilstaat</b><span>Etat, Kassen, Verteidigung, Notlage</span></a>' if _regierte(con, k) else "")
               + f'<a href="{PFAD}etats/">{amt.ic("landmark")}<b>Etats der Behörden</b><span>Kassenstand, Etat, Personalkosten</span></a>'
               + (f'<a href="{PFAD}verteidigung/">{amt.ic("shield")}<b>Verteidigung</b><span>Etats, Militärgerät, Einsatzbereitschaft</span></a>'
                  if hat_verteidigung(con, k) else "")
               +                f'<a href="{PFAD}haushalt/">{amt.ic("chart-column")}<b>Staatshaushalt</b><span>Steuern und Reichsabgabe der Teilstaaten</span></a>'
               f'<a href="{PFAD}finanzen/">{amt.ic("chart-column")}<b>Reichsfinanzen</b><span>Geldmenge, Reichskasse, Staatskassen</span></a></div>')
    inhalt = (f'<h1>{amt.ic("landmark")} Staatliche Kassen</h1>'
              f'<p class="az">Dienstliche Ansicht für {esc(geld.anzeigename(con, k["id"], k["name"]))} – Ihr privates Konto sehen Sie unter „Privat“.</p>'
              f'{amt.meldung(request)}<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              + schnell + kassen + letzte)
    return ant(request, k, "Staatliche Kassen", "sa-start", inhalt)


def _uebersicht_militaer(request, k, con):
    """Staatliche Übersicht für Militär ohne eigene Kasse: Verweis auf den Verteidigungsbereich des eigenen Teilstaats."""
    import verteidigung
    s = verteidigung.sicht(con, k)
    karten = "".join(f'<a href="{PFAD}verteidigung/{esc(sid)}/">{amt.ic("shield")}<b>Verteidigung {esc(name)}</b>'
                     '<span>Etat, Personal, Gerät, Einsatzbereitschaft</span></a>' for sid, name in verteidigung.namen(con, s["sids"]))
    if s["reich"] and not s["sids"]:
        karten += f'<a href="{PFAD}verteidigung/">{amt.ic("shield")}<b>Reichsverteidigung</b><span>Etat und Führungsstab</span></a>'
    inhalt = (f'<h1>{amt.ic("shield")} Dienstliche Ansicht</h1>'
              f'<p class="az">{esc(geld.anzeigename(con, k["id"], k["name"]))} – Sie sehen den Verteidigungsbereich '
              + ("Ihres Teilstaats" if s["sids"] else "des Reiches") + '. Ihr privates Konto sehen Sie unter „Privat“.</p>'
              f'{amt.meldung(request)}<div class="sa-schnell">{karten}'
              f'<a href="{PFAD}verteidigung/katalog/">{amt.ic("wrench")}<b>Gerätekatalog</b><span>Preise und Instandhaltung</span></a></div>')
    return ant(request, k, "Dienstliche Ansicht", "sa-start", inhalt)


def _kassen_zusatz(con, konten):
    """{Konto-ID: kurze Zusatzzeile} – Monatsetat bei Behörden, Reichsabgabe bei Staatskassen."""
    import aufkommen
    import etat
    out = {}
    if any(r["art"] == "behoerde" for r in konten):
        e = etat.etats(con)
        for r in konten:
            if r["art"] == "behoerde" and e.get(r["stelle"]):
                out[r["id"]] = f'Etat / Monat {geld.mark_kurz(e[r["stelle"]])}'
    if any(r["art"] == "teilstaat" for r in konten):
        import notlage
        q, qt = aufkommen.abgabequoten_beide(aufkommen.staaten_bip(con), geld.einstellung(con, "aufkommen"), zuschlag=notlage.zuschlaege(con))
        for r in konten:
            if r["art"] == "teilstaat" and r["stelle"][3:] in q:
                sid = r["stelle"][3:]
                out[r["id"]] = (f'Reichsabgabe {q[sid]:.1f} % der Steuereinnahmen'
                                + (f' (ohne Obergrenze {qt[sid]:.1f} %)' if qt[sid] > q[sid] + 0.05 else "")).replace(".", ",")
    if any(r["art"] == "verteidigung" for r in konten):
        import verteidigung
        etat = verteidigung._etat_monat(con)
        for r in konten:
            if r["art"] == "verteidigung":
                out[r["id"]] = f'Verteidigungsetat {geld.mark_kurz(etat.get(r["stelle"], 0))} je Monat'
    import notlage
    for kid, f in notlage.offene(con).items():
        if any(r["id"] == kid for r in konten):
            out[kid] = f'⚠ Haushaltsnotlage seit {int((time.time() - f["seit"]) // 86400)} Tagen (Stufe {f["stufe"]})'
    return out


def _karten(konten, zusatz=None):
    zusatz = zusatz or {}
    return "".join(
        f'<div class="sa-karte"><small>{esc(geld.art_name(r))}</small><div class="sa-name">{esc(r["name"])}</div>'
        f'<div class="sa-nr az">{nummer_anzeige(r["nummer"])}</div><div class="sa-saldo">{betrag_html(r["saldo"], False, kurz=True)}</div>'
        + (f'<p class="az sa-zusatz{" sa-rot" if zusatz[r["id"]].startswith("⚠") else ""}">{esc(zusatz[r["id"]])}</p>' if r["id"] in zusatz else "")
        + (f'<p class="az" style="color:var(--rot)">Gesperrt{": " + esc(r["sperrgrund"]) if r["sperrgrund"] else ""}</p>' if r["gesperrt"] else "")
        + f'<div class="sa-aktionen"><a class="btn" href="{PFAD}ueberweisen/?von={r["id"]}">{amt.ic("arrow-right-left")}Überweisen</a>'
        f'<a class="btn zweit" href="{PFAD}konto/?konto={r["id"]}">{amt.ic("wallet")}Umsätze</a></div></div>' for r in konten)


# ---------------------------------------------------------------- Bürger: Konto & Umsätze

@seite("mitglied")
async def konto_seite(request, k):
    con = request.app["db"]
    r, konten = _konto_waehlen(con, k, request)
    if not r:
        return ant(request, k, "Kassen & Umsätze", "sa-konto", f'<h1>{amt.ic("wallet")} Kassen & Umsätze</h1>'
                   '<div class="hinweis">Ihnen ist keine staatliche Kasse zur Verfügung zugewiesen. Für das eigene Konto oben auf „Privat“ umschalten.</div>')
    m = request.query.get("monat", "")
    q = " ".join(request.query.get("q", "").split())[:60]
    von, bis = _monat_grenzen(m)
    bs = umsaetze(con, r["id"], 500, von, bis, q)
    ein = sum(b["betrag"] for b in bs if b["an"] == r["id"])
    aus = sum(b["betrag"] for b in bs if b["von"] == r["id"])
    monate = "".join(f'<option value="{x}"{" selected" if x == m else ""}>{_monatsname(x)}</option>' for x in _monate(con, r["id"]))
    titel = "Kassen & Umsätze" if modus(request, k) == "staat" else "Konto & Umsätze"
    inhalt = (f'<h1>{amt.ic("wallet")} {titel}</h1>{amt.meldung(request)}' + _konto_auswahl(konten, r, f"{PFAD}konto/")
              + f'<div class="sa-karte" style="max-width:520px"><small>{esc(geld.art_name(r))}</small><div class="sa-name">{esc(r["name"])}</div>'
              f'<div class="sa-nr az">{nummer_anzeige(r["nummer"])} · eröffnet {amt._zeit(r["eroeffnet"], False)}</div>'
              f'<div class="sa-saldo">{betrag_html(r["saldo"], False)}</div></div>'
              f'<form class="sa-leiste" method="get"><input type="hidden" name="konto" value="{r["id"]}">'
              f'<div><label for="m">Zeitraum</label><select id="m" name="monat"><option value="">Alle</option>{monate}</select></div>'
              f'<div><label for="q">Verwendungszweck</label><input type="search" id="q" name="q" value="{esc(q)}"></div>'
              f'<button class="btn zweit" type="submit">{amt.ic("search")}Filtern</button>'
              f'<a class="btn zweit" href="{PFAD}konto/{r["id"]}/pdf?monat={esc(m)}">{amt.ic("file-down")}Kontoauszug (PDF)</a></form>'
              f'<p class="az">{len(bs)} Buchungen · Eingänge {mark(ein)} · Ausgänge {mark(aus)}</p>'
              + amt.tabelle(UMSATZ_KOPF, umsatz_zeilen(con, r["id"], bs), "Keine Umsätze im gewählten Zeitraum."))
    return ant(request, k, titel, "sa-konto", inhalt)


@seite()
async def kontoauszug_pdf(request, k):
    con = request.app["db"]
    i = request.match_info["id"]
    r = geld.konto(con, i) if i.isdigit() else None
    if not r or not geld.darf_einsehen(con, k, r):
        raise web.HTTPNotFound(text="Konto nicht gefunden.")
    m = request.query.get("monat", "")
    von, bis = _monat_grenzen(m)
    bs = list(reversed(umsaetze(con, r["id"], 2000, von, bis)))
    zeitraum = _monatsname(m) if von else "alle Buchungen"
    anfang = (bs[0]["saldo_an"] - bs[0]["betrag"] if bs[0]["an"] == r["id"] else bs[0]["saldo_von"] + bs[0]["betrag"]) if bs else r["saldo"]
    ende = (bs[-1]["saldo_an"] if bs[-1]["an"] == r["id"] else bs[-1]["saldo_von"]) if bs else r["saldo"]
    inhalt = (f'<h1>Kontoauszug</h1><p class="az">{esc(r["name"])} · {nummer_anzeige(r["nummer"])} · {esc(zeitraum)}</p>'
              + amt.daten_tabelle([("Kontoinhaber", esc(r["name"])), ("Kontonummer", nummer_anzeige(r["nummer"])), ("Kontoart", esc(geld.art_name(r))),
                                   ("Zeitraum", esc(zeitraum)), ("Anfangssaldo", mark(anfang)), ("Endsaldo", mark(ende))])
              + "<h2>Buchungen</h2>" + amt.tabelle(UMSATZ_KOPF, umsatz_zeilen(con, r["id"], bs), "Keine Buchungen im Zeitraum."))
    return await amt._pdf_antwort(request, f"kontoauszug-{r['nummer']}" + (f"-{m}" if von else ""), "Kontoauszug", inhalt,
                                  stelle=geld.STELLE, az=nummer_anzeige(r["nummer"]), einstufung="", doktyp="Kontoauszug",
                                  qr_url=f"{amt.config.SITE_URL}{PFAD}konto/")


# ---------------------------------------------------------------- Bürger: Überweisen

def _steuern_ueberweisung(con, kv, ka, betrag):
    """(zusätzliche Überweisungssteuer des Auftraggebers, enthaltene Umsatzsteuer beim Gewerbe-Empfänger)."""
    ust, ueb = 0, 0
    if ka["art"] == "gewerbe" and kv["inhaber_id"] != ka["inhaber_id"]:
        s = float(geld.einstellung(con, "umsatzsteuer") or 0)
        ust = round(betrag * s / (100 + s)) if s else 0
    if kv["art"] == "privat" and ka["art"] in ("privat", "gewerbe"):
        s = float(geld.einstellung(con, "ueberweisungssteuer") or 0)
        ueb = round(betrag * s / 100) if s else 0
    return ueb, ust


@seite("mitglied")
async def ueberweisen_seite(request, k):
    con = request.app["db"]
    konten = konten_im_modus(con, k, modus(request, k))
    von = request.query.get("von", "")
    an = request.query.get("an", "")
    q = " ".join(request.query.get("q", "").split())[:60]
    treffer = ""
    if q:
        rows = con.execute("SELECT * FROM gk_konten WHERE (name LIKE ? OR nummer LIKE ?) AND art!='sonder' ORDER BY art, name LIMIT 30",
                           (f"%{q}%", f"%{q.replace(' ', '').upper()}%")).fetchall()
        rows += [r for r in con.execute("SELECT * FROM gk_konten WHERE art='sonder' AND stelle NOT IN ('zentralbank','volkswirtschaft') AND name LIKE ?", (f"%{q}%",))]
        treffer = "<h2>Suchergebnis</h2>" + amt.tabelle(
            ["Empfänger", "Kontonummer", "Kontoart", ""],
            [(esc(r["name"]), f'<span class="sa-nr">{nummer_anzeige(r["nummer"])}</span>', esc(geld.art_name(r)),
              f'<a class="btn zweit" href="{PFAD}ueberweisen/?an={r["nummer"]}&von={esc(von)}">Übernehmen</a>') for r in rows],
            "Kein Konto gefunden.")
    opts = "".join(f'<option value="{r["id"]}"{" selected" if str(r["id"]) == von else ""}>{esc(r["name"])} · {mark(r["saldo"])}</option>' for r in konten)
    if not konten:
        return ant(request, k, "Überweisen", "sa-ueberweisen", f'<h1>{amt.ic("arrow-right-left")} Überweisen</h1>'
                   '<div class="hinweis">Ihnen ist keine staatliche Kasse zur Verfügung zugewiesen. Für das eigene Konto oben auf „Privat“ umschalten.</div>')
    inhalt = (f'<h1>{amt.ic("arrow-right-left")} Überweisen</h1>{amt.meldung(request)}'
              f'<form class="sa-formular" method="post" action="{PFAD}ueberweisen/pruefen">{amt.csrf_feld(request)}<div class="zeilen">'
              f'<div><label for="von">Von Konto</label><select id="von" name="von">{opts}</select></div>'
              f'<div><label for="an">Empfänger (Kontonummer)</label><input type="text" id="an" name="an" required value="{esc(nummer_anzeige(an) if an else "")}" '
              'placeholder="IG00 0000 0000 0000" class="sa-nr" autocomplete="off"></div>'
              '<div><label for="b">Betrag in Kronen</label><input type="text" id="b" name="betrag" required inputmode="decimal" placeholder="0,00"></div>'
              '</div><div><label for="z">Verwendungszweck</label><input type="text" id="z" name="zweck" maxlength="140" required></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("arrow-right")}Weiter zur Prüfung</button></div></form>'
              f'<h2>Empfänger suchen</h2><form class="sa-leiste" method="get"><input type="hidden" name="von" value="{esc(von)}">'
              f'<div><label for="q">Name oder Kontonummer</label><input type="search" id="q" name="q" value="{esc(q)}"></div>'
              f'<button class="btn zweit" type="submit">{amt.ic("search")}Suchen</button></form>{treffer}'
              '<p class="sa-hinweis">Zahlungen an Gewerbekonten enthalten die Umsatzsteuer; sie wird dem Gewerbe automatisch abgezogen. '
              f'Sätze siehe <a href="{PFAD}tarife/">Tarife & Sätze</a>.</p>')
    return ant(request, k, "Überweisen", "sa-ueberweisen", inhalt)


def _ueberweisung_lesen(con, k, form):
    konten = {r["id"]: r for r in geld.verfuegbare_konten(con, k)}
    kv = konten.get(int(form.get("von", 0) or 0)) if str(form.get("von", "")).isdigit() else None
    ka = geld.nach_nummer(con, form.get("an", ""))
    betrag = geld.betrag_lesen(form.get("betrag", ""))
    zweck = _f(form, "zweck", 140)
    if not kv:
        return None, "Bitte ein eigenes Konto als Auftraggeber wählen."
    if not ka or ka["stelle"] in geld.AUSSEN:
        return None, "Die Kontonummer ist ungültig oder unbekannt (Prüfziffer prüfen)."
    if not betrag:
        return None, "Bitte einen gültigen Betrag angeben."
    if not zweck:
        return None, "Bitte einen Verwendungszweck angeben."
    if kv["id"] == ka["id"]:
        return None, "Auftraggeber und Empfänger sind dasselbe Konto."
    return (kv, ka, betrag, zweck), None


@seite("mitglied")
async def ueberweisen_pruefen(request, k):
    con = request.app["db"]
    form = await formular(request)
    daten, fehler = _ueberweisung_lesen(con, k, form)
    if fehler:
        weiter(f"{PFAD}ueberweisen/?von={esc(str(form.get('von', '')))}", fehler, True)
    kv, ka, betrag, zweck = daten
    ueb, ust = _steuern_ueberweisung(con, kv, ka, betrag)
    gesamt = betrag + ueb
    warn = '<div class="warnung">Die Deckung reicht nicht aus.</div>' if kv["saldo"] < gesamt else ""
    zeilen = [("Von", konto_kurz(kv)), ("An", konto_kurz(ka) + f' <span class="az">({esc(geld.art_name(ka))})</span>'), ("Betrag", mark(betrag)),
              ("Verwendungszweck", esc(zweck))]
    if ueb:
        zeilen.append(("Überweisungssteuer", mark(ueb) + " (zusätzlich)"))
    if ust:
        zeilen.append(("Darin enthaltene Umsatzsteuer", mark(ust) + " (trägt der Empfänger)"))
    zeilen.append(("Belastung gesamt", f"<b>{mark(gesamt)}</b>"))
    versteckt = "".join(f'<input type="hidden" name="{n}" value="{esc(str(form.get(n, "")))}">' for n in ("von", "an", "betrag", "zweck"))
    inhalt = (f'<h1>{amt.ic("arrow-right-left")} Überweisung prüfen</h1><div class="sa-pruef">{amt.daten_tabelle(zeilen)}{warn}'
              f'<form method="post" action="{PFAD}ueberweisen/">{amt.csrf_feld(request)}{versteckt}<div class="aktionen">'
              f'<button class="btn" type="submit"{" disabled" if warn else ""}>{amt.ic("check")}Jetzt überweisen</button>'
              f'<a class="btn zweit" href="{PFAD}ueberweisen/?von={kv["id"]}">Abbrechen</a></div></form></div>')
    return ant(request, k, "Überweisung prüfen", "sa-ueberweisen", inhalt)


@seite("mitglied")
async def ueberweisen(request, k):
    con = request.app["db"]
    form = await formular(request)
    daten, fehler = _ueberweisung_lesen(con, k, form)
    if fehler:
        weiter(f"{PFAD}ueberweisen/", fehler, True)
    kv, ka, betrag, zweck = daten
    ueb, ust = _steuern_ueberweisung(con, kv, ka, betrag)
    kasse = geld.sonder(con, "reichskasse")
    try:
        if kv["saldo"] < betrag + ueb:
            raise geld.Fehler(f'Keine ausreichende Deckung (verfügbar {mark(kv["saldo"])}).')
        bid = geld.buchen(con, kv["id"], ka["id"], betrag, "ueberweisung", zweck, k)
        if ueb:
            geld.buchen(con, kv["id"], kasse["id"], ueb, "ueberweisungssteuer", f"Überweisungssteuer zu Buchung {bid}", k, bezug=f"B{bid}")
        if ust:
            geld.buchen(con, ka["id"], kasse["id"], ust, "umsatzsteuer", f"Umsatzsteuer aus Zahlung von {kv['name']}", k, bezug=f"B{bid}", minus=True)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        weiter(f"{PFAD}ueberweisen/?von={kv['id']}", str(e), True)
    if ka["inhaber_id"]:
        dm(request, ka["inhaber_id"], f"Zahlungseingang auf {ka['name']} ({nummer_anzeige(ka['nummer'])}): {mark(betrag)} von {kv['name']}.\n"
                                      f"Verwendungszweck: {zweck}\n{amt.config.SITE_URL}{PFAD}konto/")
    weiter(f"{PFAD}konto/?konto={kv['id']}", f"{mark(betrag)} an {ka['name']} überwiesen.")


# ---------------------------------------------------------------- Bürger: Gewerbe

@seite("mitglied")
async def gewerbe_seite(request, k):
    import landespolizei
    con = request.app["db"]
    eigene = con.execute("SELECT g.*, k.nummer, k.saldo FROM gk_gewerbe g LEFT JOIN gk_konten k ON k.id=g.konto WHERE g.inhaber_id=? ORDER BY g.id DESC",
                         (k["id"],)).fetchall()
    zeilen = [(esc(g["name"]), esc(g["branche"]), esc(g["sitz"] or "–"), _gewerbe_marke(g),
               f'<span class="sa-nr">{nummer_anzeige(g["nummer"])}</span>' if g["nummer"] else "–", mark(g["saldo"]) if g["nummer"] else "–",
               (f'<form method="post" action="{PFAD}gewerbe/{g["id"]}/abmelden" onsubmit="return confirm(\'Gewerbe abmelden? Das Guthaben geht auf dein Privatkonto.\')">'
                f'{amt.csrf_feld(request)}<button class="btn zweit gefahr" type="submit">Abmelden</button></form>') if g["status"] == "aktiv" else esc(g["grund"]))
              for g in eigene]
    staaten = "".join(f"<option>{esc(s['name'])}</option>" for s in landespolizei.staaten(con))
    inhalt = (f'<h1>{amt.ic("store")} Gewerbe</h1>{amt.meldung(request)}'
              '<p class="az">Mit einer Gewerbeanmeldung erhältst du nach Genehmigung durch das Schatzamt ein eigenes Gewerbekonto. '
              'Zahlungen an Gewerbe enthalten Umsatzsteuer; je Steuerlauf fällt Gewerbesteuer an.</p>'
              + amt.tabelle(["Gewerbe", "Branche", "Sitz", "Stand", "Kontonummer", "Saldo", ""], zeilen, "Du hast noch kein Gewerbe angemeldet.")
              + f'<h2>Gewerbe anmelden</h2><form class="sa-formular" method="post" action="{PFAD}gewerbe/">{amt.csrf_feld(request)}<div class="zeilen">'
              '<div><label for="n">Name des Gewerbes</label><input type="text" id="n" name="name" required maxlength="80"></div>'
              f'<div><label for="b">Branche</label><select id="b" name="branche">{"".join(f"<option>{esc(b)}</option>" for b in BRANCHEN)}</select></div>'
              f'<div><label for="s">Sitz (Teilstaat)</label><select id="s" name="sitz"><option value="">–</option>{staaten}</select></div></div>'
              '<div><label for="t">Beschreibung (IC)</label><textarea id="t" name="beschreibung" maxlength="1000" required></textarea></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("send")}Anmeldung einreichen</button></div></form>')
    return ant(request, k, "Gewerbe", "sa-gewerbe", inhalt)


def _gewerbe_marke(g):
    return amt.status_marke({"aktiv": "ok", "beantragt": "offen", "abgelehnt": "nein"}.get(g["status"], "neutral"),
                            {"aktiv": "Aktiv", "beantragt": "Beantragt", "abgelehnt": "Abgelehnt", "abgemeldet": "Abgemeldet"}.get(g["status"], g["status"]))


@seite("mitglied")
async def gewerbe_anmelden(request, k):
    con = request.app["db"]
    form = await formular(request)
    name, branche, sitz, text = _f(form, "name", 80), _f(form, "branche", 60), _f(form, "sitz", 80), str(form.get("beschreibung", "")).strip()[:1000]
    if not name or branche not in BRANCHEN or not text:
        weiter(f"{PFAD}gewerbe/", "Bitte Name, Branche und Beschreibung angeben.", True)
    if con.execute("SELECT 1 FROM gk_gewerbe WHERE inhaber_id=? AND status='beantragt'", (k["id"],)).fetchone():
        weiter(f"{PFAD}gewerbe/", "Es liegt bereits ein offener Antrag vor.", True)
    con.execute("INSERT INTO gk_gewerbe (inhaber_id, inhaber_name, name, branche, sitz, beschreibung, zeit) VALUES (?,?,?,?,?,?,?)",
                (k["id"], geld.anzeigename(con, k["id"], k["name"]), name, branche, sitz, text, int(time.time())))
    geld.protokoll(con, k, "Gewerbe beantragt", f"{name} ({branche})")
    con.commit()
    weiter(f"{PFAD}gewerbe/", "Gewerbeanmeldung eingereicht. Das Schatzamt entscheidet in Kürze.")


async def _gewerbe_schliessen(request, con, g, k, grund):
    r = geld.konto(con, g["konto"]) if g["konto"] else None
    if r and r["saldo"] > 0:
        p = geld.privatkonto(con, g["inhaber_id"])
        geld.buchen(con, r["id"], p["id"], r["saldo"], "ueberweisung", f"Auflösung Gewerbekonto {g['name']}", k, minus=True)
    if r:
        con.execute("UPDATE gk_konten SET gesperrt=1, sperrgrund='Gewerbe abgemeldet' WHERE id=?", (r["id"],))
    con.execute("UPDATE gk_gewerbe SET status='abgemeldet', grund=?, entschieden=?, entschieden_von=? WHERE id=?",
                (grund, int(time.time()), k["name"], g["id"]))
    geld.protokoll(con, k, "Gewerbe abgemeldet", f"{g['name']}: {grund}")
    con.commit()


@seite("mitglied")
async def gewerbe_abmelden(request, k):
    con = request.app["db"]
    await formular(request)
    g = con.execute("SELECT * FROM gk_gewerbe WHERE id=? AND inhaber_id=? AND status='aktiv'", (request.match_info["id"], k["id"])).fetchone()
    if not g:
        raise web.HTTPNotFound(text="Gewerbe nicht gefunden.")
    await _gewerbe_schliessen(request, con, g, k, "Vom Inhaber abgemeldet")
    weiter(f"{PFAD}gewerbe/", f"{g['name']} abgemeldet; das Guthaben wurde auf dein Privatkonto übertragen.")


# ---------------------------------------------------------------- Information: Tarife, Reichsfinanzen

def tarife_html(con):
    import besoldung
    e = lambda s: geld.einstellung(con, s)
    stufen, unten = [], 0
    for bis, satz in e("lohnsteuer")["stufen"]:
        stufen.append((f"{mark(unten)} – {mark(bis) if bis else 'darüber'}", f"{satz} %"))
        unten = bis or unten
    v, g, ak = e("vermoegensteuer"), e("gewerbesteuer"), e("aufkommen")
    saetze = [("Währung", f'Krone (Kr) zu 100 Heller · 1 Kr = {e("wechselkurs")} €'),
              ("Staatshaushalt der Bevölkerung", f'Steuern {ak["steuerquote"]} % des BIP je Teilstaat (Echtmaßstab); Reichsabgabe je Teilstaat '
                                                 f'nach Bevölkerung, Einkommen pro Kopf und Fläche (im Schnitt {ak["reichsanteil"]} %, '
                                                 f'mindestens {ak.get("quote_min", 20)} %, höchstens {ak.get("quote_max", 33)} % des Etats), Rest an den Teilstaat; Pflichtausgaben {ak.get("ausgabenquote", 97)} % der Einnahmen (monatlich)'),
              ("Verteidigungsetat", (lambda vt: 'Anteil am Ausgabenbudget bestimmen Reich und Teilstaaten in der Etatverteilung (Vorgabe: '
                                                  f'{float(vt["quote_bip"]):g}'.replace(".", ",") + f' % des BIP, davon {vt["anteil_reich"]} % an das Reich/Führungsstab); '
                                                  'der Anteil der Teilstaaten fließt in deren Verteidigungskasse (Militär, Gerät)')(e("verteidigung"))),
              ("Haushaltsnotlage", (lambda n: f'Kassen von Teilstaaten, Behörden und Verteidigung dürfen bis zu {n["dispo_monate"]:g} Monat(e) überziehen; im Minus werden die '
                                              f'Gehälter der Kasse einbehalten (und bei Ausgleich nachgezahlt), es fallen Strafzinsen (Leitzins + {n["aufschlag"]:g} Punkte) an, nach {n["ausgleich_tage"]} Tagen gleichen Teilstaaten '
                                              f'aus Gold aus (Reichsabgabe +{n["abgabe_plus"]:g} Punkte), nach {n["zwang_tage"]} Tagen Zwangsverwaltung')(
                  __import__("notlage").einstellungen(con))),
              ("Sozialabgabe (Reichsversicherung)", f'{e("sozialabgabe")} % des Bruttogehalts'),
              ("Kronsteuer", f'{e("kronsteuer")} % des Bruttogehalts (Quellenabzug im Lohnlauf) an die Crown Estates des Kaisers, aus denen der Monarch bezahlt wird; '
                             f'dazu {str(e("kronsteuer_bevoelkerung")).replace(".", ",")} Kr je Einwohner und Monat der Bevölkerung. Die Monarchen selbst zahlen keine Kronsteuer'),
              ("Länderanteil", f'{e("laenderanteil")} % von Lohn- und Kopfsteuer an den Wohnsitz-Teilstaat'),
              ("Kopfsteuer", f'{mark(e("kopfsteuer"))} je Steuerlauf und Staatsbürger'),
              ("Vermögensteuer", f'{v["satz"]} % des Guthabens über {mark(v["freibetrag"])} je Steuerlauf'),
              ("Gewerbesteuer", f'{mark(g["grund"])} + {g["satz"]} % der Eingänge je Steuerlauf'),
              ("Umsatzsteuer", f'{e("umsatzsteuer")} % (im Preis enthalten) bei Zahlungen an Gewerbe'),
              ("Überweisungssteuer", f'{e("ueberweisungssteuer")} % auf private Überweisungen'),
              ("Säumniszuschlag", f'{e("saeumnis")} % je Mahnstufe · Zahlungsfrist {e("frist_tage")} Tage'),
              ("Privatbesitz", __import__("privatbesitz").tarif_text(con)),
              ("Leitzins", f'{e("leitzins")} %')]
    geb = [(esc(geld.GEBUEHR_NAMEN.get(s, s)), mark(b)) for s, b in e("gebuehren").items()]
    return ("<h2>Lohnsteuer (Stufentarif auf das Monatsbrutto)</h2>" + amt.tabelle(["Einkommensstufe", "Grenzsteuersatz"], stufen)
            + "<h2>Steuern und Abgaben</h2>" + amt.daten_tabelle(saetze)
            + "<h2>Verwaltungsgebühren</h2>" + amt.tabelle(["Leistung", "Gebühr"], geb)
            + "<h2>Besoldungsordnung</h2>" + besoldung.tabelle_html(con) + besoldung.zuschlag_tabelle_html(con))


@seite()
async def tarife(request, k):
    con = request.app["db"]
    inhalt = (f'<h1>{amt.ic("percent")} Tarife & Sätze</h1><p class="az">Geltende Steuersätze, Gebühren und Besoldung des Reiches. '
              'Festgesetzt vom Kaiserlichen Schatz- und Währungsamt.</p>' + tarife_html(con))
    return ant(request, k, "Tarife & Sätze", "sa-tarife", inhalt)


@seite("staat")
async def finanzen(request, k):
    import aufkommen
    import gold
    con = request.app["db"]
    seit = int(time.time()) - 30 * 86400
    kasse = geld.sonder(con, "reichskasse")
    ein = con.execute("SELECT art, SUM(betrag) s FROM gk_buchungen WHERE an=? AND zeit>=? GROUP BY art ORDER BY s DESC", (kasse["id"], seit)).fetchall()
    aus = con.execute("SELECT art, SUM(betrag) s FROM gk_buchungen WHERE von=? AND zeit>=? GROUP BY art ORDER BY s DESC", (kasse["id"], seit)).fetchall()
    verteilung = con.execute("SELECT art, COUNT(*) n, SUM(saldo) s FROM gk_konten WHERE art!='sonder' GROUP BY art").fetchall()
    staaten = con.execute("SELECT name, saldo FROM gk_konten WHERE art='teilstaat' ORDER BY name").fetchall()
    kz = [("Geldmenge im Umlauf", mark(geld.geldmenge(con))), ("Reichskasse", mark(kasse["saldo"])),
          ("Reichsversicherung", mark(geld.sonder(con, "sozialkasse")["saldo"])), ("Leitzins", f'{geld.einstellung(con, "leitzins")} %'),
          ("Wechselkurs", f'1 Kr = {geld.einstellung(con, "wechselkurs")} €')]
    inhalt = (f'<h1>{amt.ic("chart-column")} Reichsfinanzen</h1><p class="az">Staatliche Übersicht über Geldmenge und Reichskasse '
              '(Einnahmen und Ausgaben der letzten 30 Tage).</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              '<h2>Einnahmen der Reichskasse</h2>' + amt.tabelle(["Art", "Summe"], [(esc(geld.BUCHUNGSART.get(r["art"], r["art"])), mark(r["s"])) for r in ein], "Keine Einnahmen.")
              + '<h2>Ausgaben der Reichskasse</h2>' + amt.tabelle(["Art", "Summe"], [(esc(geld.BUCHUNGSART.get(r["art"], r["art"])), mark(r["s"])) for r in aus], "Keine Ausgaben.")
              + '<h2>Verteilung der Geldmenge</h2>' + amt.tabelle(["Kontoart", "Konten", "Guthaben"],
                                                                  [(esc(geld.KONTOART[r["art"]][0]), r["n"], mark(r["s"])) for r in verteilung])
              + '<h2>Staatskassen der Teilstaaten</h2>' + amt.tabelle(["Teilstaat", "Guthaben"], [(esc(r["name"]), mark(r["saldo"])) for r in staaten], "Keine Staatskassen.")
              + gold.finanzen_html(con) + aufkommen.finanzen_html(con))
    return ant(request, k, "Reichsfinanzen", "sa-finanzen", inhalt)


# ---------------------------------------------------------------- Verwaltung: Übersicht

@seite("beamter")
async def amt_uebersicht(request, k):
    import steuern
    con = request.app["db"]
    n = lambda sql, *a: con.execute(sql, a).fetchone()[0] or 0
    seit = int(time.time()) - 30 * 86400
    kasse = geld.sonder(con, "reichskasse")
    kz = [("Geldmenge", mark(geld.geldmenge(con))), ("Reichskasse", mark(kasse["saldo"])),
          ("Konten", n("SELECT COUNT(*) FROM gk_konten WHERE art IN ('privat','gewerbe')")),
          ("Steuereinnahmen 30 Tage", mark(n("SELECT SUM(betrag) FROM gk_buchungen WHERE an=? AND zeit>=? AND art IN "
                                              "('steuer','lohnsteuer','umsatzsteuer','ueberweisungssteuer','gebuehr','pfaendung')", kasse["id"], seit))),
          ("Offene Bescheide", n("SELECT COUNT(*) FROM st_bescheide WHERE status='offen'")),
          ("Überfällig", n("SELECT COUNT(*) FROM st_bescheide WHERE status='offen' AND faellig<?", date.today().isoformat())),
          ("Gewerbeanträge", n("SELECT COUNT(*) FROM gk_gewerbe WHERE status='beantragt'"))]
    gross = con.execute("SELECT * FROM gk_buchungen WHERE zeit>=? ORDER BY betrag DESC LIMIT 10", (seit,)).fetchall()
    zeilen = []
    for b in gross:
        zeilen.append((amt._zeit(b["zeit"]), konto_kurz(geld.konto(con, b["von"])) if b["von"] else "–", konto_kurz(geld.konto(con, b["an"])) if b["an"] else "–",
                       esc(geld.BUCHUNGSART.get(b["art"], b["art"])), f'<span class="sa-betrag">{mark(b["betrag"])}</span>'))
    rollen_hinweis = ("" if geld._behoerde()["rollen"] else
                      '<div class="hinweis">Für das Schatzamt sind noch keine Discord-Rollen hinterlegt – bis dahin verwalten Kanzler und Kaiser.</div>')
    inhalt = (f'<h1>{amt.ic("landmark")} Verwaltung</h1><p class="az">{esc(geld.NAME)} · Zentralbank und Finanzverwaltung des Reiches</p>'
              f'{amt.meldung(request)}{rollen_hinweis}<div class="kennzahlen">{"".join(f"<div><b>{esc(str(v))}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              + "<h2>Überfällige Bescheide</h2>" + steuern.bescheid_tabelle(con, con.execute(
                  "SELECT * FROM st_bescheide WHERE status='offen' AND faellig<? ORDER BY faellig LIMIT 15", (date.today().isoformat(),)).fetchall(),
                  f"{PFAD}amt/steuern/", leer="Keine überfälligen Bescheide.")
              + "<h2>Größte Buchungen (30 Tage)</h2>" + amt.tabelle(["Zeit", "Von", "An", "Art", "Betrag"], zeilen, "Keine Buchungen."))
    return ant(request, k, "Verwaltung", "sa-amt", inhalt)


# ---------------------------------------------------------------- Verwaltung: Konten

@seite("beamter")
async def amt_konten(request, k):
    con = request.app["db"]
    geld.teilstaaten_sichern(con)
    art = request.query.get("art", "")
    q = " ".join(request.query.get("q", "").split())[:60]
    wo, args = ["1=1"], []
    if art in geld.KONTOART:
        wo.append("art=?"); args.append(art)
    if q:
        wo.append("(name LIKE ? OR nummer LIKE ? OR inhaber_id=?)"); args += [f"%{q}%", f"%{q.replace(' ', '').upper()}%", q]
    rows = con.execute(f"SELECT * FROM gk_konten WHERE {' AND '.join(wo)} ORDER BY art='privat', art, name LIMIT 300", args).fetchall()
    arten = "".join(f'<option value="{a}"{" selected" if a == art else ""}>{esc(n)}</option>' for a, (n, _) in geld.KONTOART.items())
    zeilen = [(f'<a href="{PFAD}amt/konten/{r["id"]}/">{esc(r["name"])}</a>', f'<span class="sa-nr">{nummer_anzeige(r["nummer"])}</span>',
               esc(geld.art_name(r)), f'<span class="sa-betrag">{betrag_html(r["saldo"], False)}</span>',
               amt.status_marke("nein", "Gesperrt") if r["gesperrt"] else "") for r in rows]
    inhalt = (f'<h1>{amt.ic("wallet")} Konten</h1>{amt.meldung(request)}<form class="sa-leiste" method="get">'
              f'<div><label for="a">Kontoart</label><select id="a" name="art"><option value="">Alle</option>{arten}</select></div>'
              f'<div><label for="q">Name, Nummer oder Discord-ID</label><input type="search" id="q" name="q" value="{esc(q)}"></div>'
              f'<button class="btn zweit" type="submit">{amt.ic("search")}Suchen</button></form>'
              + amt.tabelle(["Konto", "Kontonummer", "Art", "Saldo", ""], zeilen, "Keine Konten gefunden."))
    return ant(request, k, "Konten", "sa-amt-konten", inhalt)


@seite("beamter")
async def amt_konto(request, k):
    con = request.app["db"]
    i = request.match_info["id"]
    r = geld.konto(con, i) if i.isdigit() else None
    if not r:
        raise web.HTTPNotFound(text="Konto nicht gefunden.")
    pfad = f"{PFAD}amt/konten/{r['id']}/"
    info = [("Kontoinhaber", esc(r["name"])), ("Kontonummer", f'<span class="sa-nr">{nummer_anzeige(r["nummer"])}</span>'), ("Kontoart", esc(geld.art_name(r))),
            ("Saldo", betrag_html(r["saldo"], False)), ("Eröffnet", amt._zeit(r["eroeffnet"])),
            ("Stand", amt.status_marke("nein", "Gesperrt: " + (r["sperrgrund"] or "ohne Angabe")) if r["gesperrt"] else amt.status_marke("ok", "Aktiv"))]
    if r["inhaber_id"]:
        info.insert(1, ("Discord-ID", esc(r["inhaber_id"])))
    aktionen = ""
    if r["stelle"] not in geld.AUSSEN:
        if r["gesperrt"]:
            aktionen += (f'<form method="post" action="{pfad}entsperren">{amt.csrf_feld(request)}<button class="btn zweit" type="submit">'
                         f'{amt.ic("lock-open")}Sperre aufheben</button></form>')
        else:
            aktionen += (f'<form class="sa-leiste" method="post" action="{pfad}sperren">{amt.csrf_feld(request)}'
                         '<div><label for="g">Sperrgrund</label><input type="text" id="g" name="grund" required maxlength="120"></div>'
                         f'<button class="btn zweit gefahr" type="submit">{amt.ic("lock")}Konto sperren</button></form>')
        if geld.ist_leitung(k):
            aktionen += (f'<h2>Korrekturbuchung</h2><form class="sa-formular" method="post" action="{pfad}korrektur">{amt.csrf_feld(request)}<div class="zeilen">'
                         '<div><label for="r">Richtung</label><select id="r" name="richtung"><option value="gut">Gutschrift</option><option value="last">Lastschrift</option></select></div>'
                         '<div><label for="gk">Gegenkonto</label><select id="gk" name="gegen"><option value="reichskasse">Reichskasse</option>'
                         '<option value="zentralbank">Zentralbank (Geldschöpfung/-vernichtung)</option></select></div>'
                         '<div><label for="kb">Betrag in Kronen</label><input type="text" id="kb" name="betrag" required></div></div>'
                         '<div><label for="kg">Begründung</label><input type="text" id="kg" name="grund" required maxlength="160"></div>'
                         f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("pencil")}Buchen</button></div></form>')
    bs = umsaetze(con, r["id"], 200)
    inhalt = (f'<h1>{amt.ic("wallet")} {esc(r["name"])}</h1><p class="az"><a href="{PFAD}amt/konten/">← Alle Konten</a></p>{amt.meldung(request)}'
              + amt.daten_tabelle(info) + aktionen
              + f'<h2>Umsätze</h2><p><a class="btn zweit" href="{PFAD}konto/{r["id"]}/pdf">{amt.ic("file-down")}Kontoauszug (PDF)</a></p>'
              + amt.tabelle(UMSATZ_KOPF, umsatz_zeilen(con, r["id"], bs, True), "Keine Umsätze."))
    return ant(request, k, r["name"], "sa-amt-konten", inhalt)


async def _amt_konto_post(request, recht="beamter"):
    k = await anmeldung.konto(request)
    if not k or not (geld.ist_leitung(k) if recht == "leitung" else geld.ist_beamter(k)):
        raise web.HTTPForbidden(text="Kein Zugang.")
    form = await formular(request)
    con = request.app["db"]
    r = geld.konto(con, request.match_info["id"]) if request.match_info["id"].isdigit() else None
    if not r or r["stelle"] in geld.AUSSEN:
        raise web.HTTPNotFound(text="Konto nicht gefunden.")
    return k, form, con, r, f"{PFAD}amt/konten/{r['id']}/"


async def amt_sperren(request):
    k, form, con, r, pfad = await _amt_konto_post(request)
    grund = _f(form, "grund", 120)
    con.execute("UPDATE gk_konten SET gesperrt=1, sperrgrund=? WHERE id=?", (grund, r["id"]))
    geld.protokoll(con, k, "Konto gesperrt", f'{r["nummer"]} ({r["name"]}): {grund}')
    con.commit()
    if r["inhaber_id"]:
        dm(request, r["inhaber_id"], f"Das Schatzamt hat dein Konto {r['name']} ({nummer_anzeige(r['nummer'])}) gesperrt. Grund: {grund}")
    weiter(pfad, "Konto gesperrt.")


async def amt_entsperren(request):
    k, form, con, r, pfad = await _amt_konto_post(request)
    con.execute("UPDATE gk_konten SET gesperrt=0, sperrgrund='' WHERE id=?", (r["id"],))
    geld.protokoll(con, k, "Sperre aufgehoben", f'{r["nummer"]} ({r["name"]})')
    con.commit()
    weiter(pfad, "Sperre aufgehoben.")


async def amt_korrektur(request):
    k, form, con, r, pfad = await _amt_konto_post(request, "leitung")
    betrag, grund = geld.betrag_lesen(form.get("betrag")), _f(form, "grund", 160)
    gegen = geld.sonder(con, "zentralbank" if form.get("gegen") == "zentralbank" else "reichskasse")
    if not betrag or not grund:
        weiter(pfad, "Bitte Betrag und Begründung angeben.", True)
    try:
        if form.get("richtung") == "last":
            geld.buchen(con, r["id"], gegen["id"], betrag, "korrektur", grund, k, minus=True)
        else:
            geld.buchen(con, gegen["id"], r["id"], betrag, "korrektur", grund, k)
        geld.protokoll(con, k, "Korrekturbuchung", f'{"Lastschrift" if form.get("richtung") == "last" else "Gutschrift"} {mark(betrag)} '
                                                   f'{r["nummer"]} ({r["name"]}) gegen {gegen["name"]}: {grund}')
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        weiter(pfad, str(e), True)
    weiter(pfad, "Korrekturbuchung ausgeführt.")


# ---------------------------------------------------------------- Verwaltung: Geldpolitik

@seite("leitung")
async def amt_geldpolitik(request, k):
    con = request.app["db"]
    ziele = geld.verfuegbare_konten(con, k)
    ziele = [geld.sonder(con, "reichskasse"), geld.sonder(con, "sozialkasse")] + [r for r in con.execute(
        "SELECT * FROM gk_konten WHERE art IN ('behoerde','teilstaat') ORDER BY art, name")]
    opts = "".join(f'<option value="{r["id"]}">{esc(r["name"])} · {mark(r["saldo"])}</option>' for r in ziele)
    verlauf = con.execute("SELECT strftime('%Y-%m', zeit, 'unixepoch', 'localtime') m, "
                          "SUM(CASE WHEN art='geldschoepfung' OR (art='korrektur' AND von=?) THEN betrag ELSE 0 END) plus, "
                          "SUM(CASE WHEN art='geldvernichtung' OR (art='korrektur' AND an=?) THEN betrag ELSE 0 END) minus "
                          "FROM gk_buchungen WHERE von=? OR an=? GROUP BY m ORDER BY m DESC LIMIT 24",
                          *[(geld.sonder(con, "zentralbank")["id"],) * 4]).fetchall()
    zb = geld.sonder(con, "zentralbank")["id"]
    letzte = con.execute("SELECT * FROM gk_buchungen WHERE (von=? OR an=?) ORDER BY id DESC LIMIT 20", (zb, zb)).fetchall()
    inhalt = (f'<h1>{amt.ic("coins")} Geldpolitik</h1>{amt.meldung(request)}'
              f'<div class="kennzahlen"><div><b>{mark(geld.geldmenge(con))}</b>Geldmenge im Umlauf</div>'
              f'<div><b>{esc(str(geld.einstellung(con, "leitzins")))} %</b>Leitzins</div></div>'
              '<p class="sa-hinweis">Geld entsteht ausschließlich durch Geldschöpfung der Zentralbank und vergeht durch Geldvernichtung. '
              'Jede Maßnahme wird mit Begründung protokolliert.</p>'
              f'<h2>Geldschöpfung</h2><form class="sa-formular" method="post" action="{PFAD}amt/geldpolitik/schoepfung">{amt.csrf_feld(request)}<div class="zeilen">'
              f'<div><label for="z">Zielkonto</label><select id="z" name="ziel">{opts}</select></div>'
              '<div><label for="b">Betrag in Kronen</label><input type="text" id="b" name="betrag" required></div></div>'
              '<div><label for="g">Begründung</label><input type="text" id="g" name="grund" required maxlength="160"></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("coins")}Geld schöpfen</button></div></form>'
              f'<h2>Geldvernichtung</h2><form class="sa-formular" method="post" action="{PFAD}amt/geldpolitik/vernichtung">{amt.csrf_feld(request)}<div class="zeilen">'
              f'<div><label for="q">Quellkonto</label><select id="q" name="ziel">{opts}</select></div>'
              '<div><label for="b2">Betrag in Kronen</label><input type="text" id="b2" name="betrag" required></div></div>'
              '<div><label for="g2">Begründung</label><input type="text" id="g2" name="grund" required maxlength="160"></div>'
              f'<div class="aktionen"><button class="btn zweit gefahr" type="submit">{amt.ic("trash-2")}Geld vernichten</button></div></form>'
              f'<h2>Leitzins</h2><form class="sa-leiste" method="post" action="{PFAD}amt/geldpolitik/leitzins">{amt.csrf_feld(request)}'
              f'<div><label for="lz">Leitzins in %</label><input type="text" id="lz" name="leitzins" value="{esc(str(geld.einstellung(con, "leitzins")))}"></div>'
              f'<button class="btn zweit" type="submit">Festsetzen</button></form>'
              '<h2>Entwicklung</h2>' + amt.tabelle(["Monat", "Geschöpft", "Vernichtet", "Saldo"],
                                                   [(_monatsname(v["m"]), mark(v["plus"]), mark(v["minus"]), betrag_html(v["plus"] - v["minus"])) for v in verlauf], "Noch keine Maßnahmen.")
              + '<h2>Letzte Maßnahmen</h2>' + amt.tabelle(UMSATZ_KOPF, umsatz_zeilen(con, zb, letzte, True), "Noch keine Maßnahmen."))
    return ant(request, k, "Geldpolitik", "sa-amt-geld", inhalt)


async def _leitung_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden(text="Kein Zugang.")
    return k, await formular(request), request.app["db"]


async def amt_schoepfung(request):
    k, form, con = await _leitung_post(request)
    z = geld.konto(con, form.get("ziel")) if str(form.get("ziel", "")).isdigit() else None
    betrag, grund = geld.betrag_lesen(form.get("betrag")), _f(form, "grund", 160)
    vernichten = request.path.endswith("vernichtung")
    if not z or z["art"] not in ("sonder", "behoerde", "teilstaat") or z["stelle"] in geld.AUSSEN or not betrag or not grund:
        weiter(f"{PFAD}amt/geldpolitik/", "Bitte Konto, Betrag und Begründung angeben.", True)
    zb = geld.sonder(con, "zentralbank")
    try:
        if vernichten:
            geld.buchen(con, z["id"], zb["id"], betrag, "geldvernichtung", grund, k)
        else:
            geld.buchen(con, zb["id"], z["id"], betrag, "geldschoepfung", grund, k)
        geld.protokoll(con, k, "Geldvernichtung" if vernichten else "Geldschöpfung", f'{mark(betrag)} {"von" if vernichten else "an"} {z["name"]}: {grund}')
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        weiter(f"{PFAD}amt/geldpolitik/", str(e), True)
    weiter(f"{PFAD}amt/geldpolitik/", f'{mark(betrag)} {"vernichtet" if vernichten else "geschöpft"}.')


async def amt_leitzins(request):
    k, form, con = await _leitung_post(request)
    p = geld.prozent_lesen(form.get("leitzins"))
    if p is None:
        weiter(f"{PFAD}amt/geldpolitik/", "Bitte einen Prozentwert zwischen 0 und 100 angeben.", True)
    geld.einstellung_setzen(con, "leitzins", f"{p:.2f}".rstrip("0").rstrip(".").replace(".", ","), k)
    con.commit()
    weiter(f"{PFAD}amt/geldpolitik/", "Leitzins festgesetzt.")


# ---------------------------------------------------------------- Verwaltung: Gewerberegister, Protokoll

@seite("beamter")
async def amt_gewerbe(request, k):
    con = request.app["db"]
    status = request.query.get("status", "beantragt")
    rows = con.execute("SELECT g.*, k.nummer, k.saldo FROM gk_gewerbe g LEFT JOIN gk_konten k ON k.id=g.konto "
                       + ("WHERE g.status=? " if status else "") + "ORDER BY g.id DESC LIMIT 300", ((status,) if status else ())).fetchall()
    reiter = '<p class="reiter">' + " ".join(f'<a href="?status={s}" class="{"aktiv" if s == status else ""}">{t}</a>' for s, t in
                                            [("beantragt", "Anträge"), ("aktiv", "Aktiv"), ("abgelehnt", "Abgelehnt"), ("abgemeldet", "Abgemeldet"), ("", "Alle")]) + "</p>"
    zeilen = []
    for g in rows:
        akt = ""
        if g["status"] == "beantragt":
            akt = (f'<form class="sa-leiste" method="post" action="{PFAD}amt/gewerbe/{g["id"]}/entscheiden">{amt.csrf_feld(request)}'
                   '<input type="text" name="grund" placeholder="Begründung (bei Ablehnung)" maxlength="160">'
                   f'<button class="btn" name="ja" value="1" type="submit">{amt.ic("check")}Genehmigen</button>'
                   f'<button class="btn zweit gefahr" name="ja" value="0" type="submit">Ablehnen</button></form>')
        elif g["status"] == "aktiv":
            akt = (f'<form method="post" action="{PFAD}amt/gewerbe/{g["id"]}/abmelden">{amt.csrf_feld(request)}'
                   '<input type="text" name="grund" placeholder="Grund" required maxlength="160"> '
                   '<button class="btn zweit gefahr" type="submit">Von Amts wegen abmelden</button></form>')
        zeilen.append((f'<b>{esc(g["name"])}</b><br><span class="az">{esc(g["beschreibung"][:160])}</span>', esc(g["inhaber_name"]), esc(g["branche"]),
                       esc(g["sitz"] or "–"), _gewerbe_marke(g) + (f'<br><span class="sa-nr az">{nummer_anzeige(g["nummer"])}</span>' if g["nummer"] else ""),
                       amt._zeit(g["zeit"], False), akt or esc(g["grund"])))
    inhalt = (f'<h1>{amt.ic("store")} Gewerberegister</h1>{amt.meldung(request)}{reiter}'
              + amt.tabelle(["Gewerbe", "Inhaber", "Branche", "Sitz", "Stand", "Angemeldet", ""], zeilen, "Keine Einträge."))
    return ant(request, k, "Gewerberegister", "sa-amt-gewerbe", inhalt)


async def amt_gewerbe_entscheiden(request):
    k = await anmeldung.konto(request)
    if not geld.ist_beamter(k):
        raise web.HTTPForbidden()
    form = await formular(request)
    con = request.app["db"]
    g = con.execute("SELECT * FROM gk_gewerbe WHERE id=? AND status='beantragt'", (request.match_info["id"],)).fetchone()
    if not g:
        raise web.HTTPNotFound()
    grund = _f(form, "grund", 160)
    if form.get("ja") == "1":
        r = geld._anlegen(con, "gewerbe", g["name"], inhaber_id=g["inhaber_id"])
        con.execute("UPDATE gk_gewerbe SET status='aktiv', konto=?, entschieden=?, entschieden_von=?, grund=? WHERE id=?",
                    (r["id"], int(time.time()), k["name"], grund, g["id"]))
        geld.protokoll(con, k, "Gewerbe genehmigt", f'{g["name"]} → {r["nummer"]}')
        con.commit()
        dm(request, g["inhaber_id"], f"Deine Gewerbeanmeldung „{g['name']}“ wurde genehmigt. Gewerbekonto: {nummer_anzeige(r['nummer'])}\n"
                                     f"{amt.config.SITE_URL}{PFAD}gewerbe/")
        weiter(f"{PFAD}amt/gewerbe/", f"{g['name']} genehmigt.")
    if not grund:
        weiter(f"{PFAD}amt/gewerbe/", "Bitte eine Begründung für die Ablehnung angeben.", True)
    con.execute("UPDATE gk_gewerbe SET status='abgelehnt', grund=?, entschieden=?, entschieden_von=? WHERE id=?", (grund, int(time.time()), k["name"], g["id"]))
    geld.protokoll(con, k, "Gewerbe abgelehnt", f'{g["name"]}: {grund}')
    con.commit()
    dm(request, g["inhaber_id"], f"Deine Gewerbeanmeldung „{g['name']}“ wurde abgelehnt. Begründung: {grund}")
    weiter(f"{PFAD}amt/gewerbe/", f"{g['name']} abgelehnt.")


async def amt_gewerbe_abmelden(request):
    k = await anmeldung.konto(request)
    if not geld.ist_beamter(k):
        raise web.HTTPForbidden()
    form = await formular(request)
    con = request.app["db"]
    g = con.execute("SELECT * FROM gk_gewerbe WHERE id=? AND status='aktiv'", (request.match_info["id"],)).fetchone()
    if not g:
        raise web.HTTPNotFound()
    await _gewerbe_schliessen(request, con, g, k, "Von Amts wegen: " + _f(form, "grund", 160))
    dm(request, g["inhaber_id"], f"Dein Gewerbe „{g['name']}“ wurde vom Schatzamt abgemeldet. Grund: {_f(form, 'grund', 160)}")
    weiter(f"{PFAD}amt/gewerbe/?status=aktiv", f"{g['name']} abgemeldet.")


@seite("beamter")
async def amt_protokoll(request, k):
    con = request.app["db"]
    rows = con.execute("SELECT * FROM gk_protokoll ORDER BY id DESC LIMIT 500").fetchall()
    inhalt = (f'<h1>{amt.ic("scroll-text")} Protokoll</h1><p class="az">Alle Maßnahmen der Verwaltung (die letzten 500).</p>'
              + amt.tabelle(["Zeit", "Bearbeiter", "Maßnahme", "Details"], [(amt._zeit(r["zeit"]), esc(r["name"]), esc(r["aktion"]), esc(r["text"])) for r in rows],
                            "Noch keine Einträge."))
    return ant(request, k, "Protokoll", "sa-amt-protokoll", inhalt)


# ---------------------------------------------------------------- Registrierung

async def behoerde_zusatz(request, k):
    """Oberhalb der Pinnwand im Behörden-Tab „Schatzamt“ der Amtsseite: Verweis ins Portal."""
    return (f'<p class="aktionen"><a class="btn" href="{PFAD}amt/">{amt.ic("landmark")}Zur Verwaltung im Schatzamt-Portal</a>'
            f'<a class="btn zweit" href="{PFAD}">{amt.ic("wallet")}Portal für Bürger</a></p>')


def registrieren(app):
    bereiche.ZUSATZ["schatzamt"] = behoerde_zusatz
    con = app["db"]
    geld.einrichten(con)
    geld.teilstaaten_sichern(con)
    r = app.router
    r.add_get(PFAD, uebersicht)
    r.add_get(PFAD + "modus/{m}", modus_setzen)
    r.add_get(PFAD + "konto/", konto_seite)
    r.add_get(PFAD + "konto/{id}/pdf", kontoauszug_pdf)
    r.add_get(PFAD + "ueberweisen/", ueberweisen_seite)
    r.add_post(PFAD + "ueberweisen/pruefen", ueberweisen_pruefen)
    r.add_post(PFAD + "ueberweisen/", ueberweisen)
    r.add_get(PFAD + "gewerbe/", gewerbe_seite)
    r.add_post(PFAD + "gewerbe/", gewerbe_anmelden)
    r.add_post(PFAD + "gewerbe/{id}/abmelden", gewerbe_abmelden)
    r.add_get(PFAD + "tarife/", tarife)
    r.add_get(PFAD + "finanzen/", finanzen)
    r.add_get(PFAD + "amt/", amt_uebersicht)
    r.add_get(PFAD + "amt/konten/", amt_konten)
    r.add_get(PFAD + "amt/konten/{id}/", amt_konto)
    r.add_post(PFAD + "amt/konten/{id}/sperren", amt_sperren)
    r.add_post(PFAD + "amt/konten/{id}/entsperren", amt_entsperren)
    r.add_post(PFAD + "amt/konten/{id}/korrektur", amt_korrektur)
    r.add_get(PFAD + "amt/geldpolitik/", amt_geldpolitik)
    r.add_post(PFAD + "amt/geldpolitik/schoepfung", amt_schoepfung)
    r.add_post(PFAD + "amt/geldpolitik/vernichtung", amt_schoepfung)
    r.add_post(PFAD + "amt/geldpolitik/leitzins", amt_leitzins)
    r.add_get(PFAD + "amt/gewerbe/", amt_gewerbe)
    r.add_post(PFAD + "amt/gewerbe/{id}/entscheiden", amt_gewerbe_entscheiden)
    r.add_post(PFAD + "amt/gewerbe/{id}/abmelden", amt_gewerbe_abmelden)
    r.add_get(PFAD + "amt/protokoll/", amt_protokoll)
