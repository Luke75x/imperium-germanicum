"""Portal des Kaiserlichen Schatz- und Währungsamts unter /schatzamt/ (nginx → Dienst) – Stil der Amtsseite (amt.rahmen mit portal=…),
erreichbar für alle angemeldeten Nutzer.

Für alle (Mitglieder): Übersicht, Konto & Umsätze (Kontoauszug, PDF), Überweisen (mit Prüfschritt, Empfängersuche, Umsatz- und
Überweisungssteuer), Steuern & Gebühren (eigene Bescheide, bezahlen, PDF), Gehalt (Abrechnungen, PDF), Gewerbe (Anmeldung,
Gewerbekonto), Tarife & Sätze, Reichsfinanzen (Transparenz).
Für das Schatzamt (geld.ist_beamter / ist_leitung): Verwaltung (Kennzahlen), Konten (Suche, Sperre, Korrekturbuchung),
Geldpolitik (Geldschöpfung/-vernichtung, Leitzins), Gewerberegister (Anträge), Protokoll; Steuern → steuern.py, Besoldung → besoldung.py.
"""
import asyncio
import functools
import secrets
import time
from datetime import date, datetime
from urllib.parse import quote

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
.kennzahlen b{white-space:nowrap;font-size:22px}
.sa-saldo{font-size:34px;font-weight:700;letter-spacing:-.01em;line-height:1.1;margin:4px 0}
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
.sa-formular input[type=text],.sa-formular input[type=search],.sa-formular select,.sa-formular textarea{width:100%}
.sa-hinweis{color:var(--grau);font-size:13.5px}
.sa-leiste{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin:6px 0 10px}
.sa-leiste>div{min-width:150px}
table.liste td.sa-betrag,table.liste th.sa-betrag{text-align:right}
</style>"""


# ---------------------------------------------------------------- Rahmen, Rechte, Hilfen

def nav(k):
    mein = [("sa-start", "layout-dashboard", "Übersicht", ""), ("sa-konto", "wallet", "Konto & Umsätze", "konto/"),
            ("sa-ueberweisen", "arrow-right-left", "Überweisen", "ueberweisen/"), ("sa-steuern", "receipt", "Steuern & Gebühren", "steuern/"),
            ("sa-gehalt", "banknote", "Gehalt", "gehalt/"), ("sa-gewerbe", "store", "Gewerbe", "gewerbe/")]
    gruppen = [("Mein Geld", mein),
               ("Information", [("sa-tarife", "percent", "Tarife & Sätze", "tarife/"), ("sa-finanzen", "chart-column", "Reichsfinanzen", "finanzen/")])]
    if geld.ist_beamter(k):
        amtl = [("sa-amt", "landmark", "Verwaltung", "amt/"), ("sa-amt-konten", "wallet", "Konten", "amt/konten/"),
                ("sa-amt-steuern", "receipt", "Steuerverwaltung", "amt/steuern/"), ("sa-amt-gewerbe", "store", "Gewerberegister", "amt/gewerbe/")]
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
    return {"basis": PFAD, "gruppen": gruppen, "haupt": mein[:4], "logo": geld.STELLE, "name": "Schatzamt"}


def ant(request, k, titel, aktiv, inhalt, status=200):
    return web.Response(status=status, content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, aktiv, CSS + inhalt, k, request["csrf"], portal=nav(k)))


def seite(recht=None):
    """Dekorator: Anmeldung nötig; recht = 'mitglied' | 'beamter' | 'leitung'. Handler bekommt (request, konto)."""
    def deko(h):
        @functools.wraps(h)
        async def inner(request):
            k = await anmeldung.konto(request)
            if not k:
                raise web.HTTPFound("/anmelden/?weiter=" + quote(request.path_qs))
            ok = {"mitglied": k["mitglied"], "beamter": geld.ist_beamter(k), "leitung": geld.ist_leitung(k)}.get(recht, True)
            if not ok:
                text = {"mitglied": "Diese Funktion steht nur Mitgliedern unseres Discord-Servers zur Verfügung.",
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


def betrag_html(pf, vorzeichen=True):
    return f'<span class="{"sa-plus" if pf > 0 else "sa-minus" if pf < 0 else ""}">{mark(pf, vorzeichen)}</span>'


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
    """Gewähltes eigenes Konto (?konto=ID) aus den verfügbaren Konten, sonst das Privatkonto."""
    konten = geld.verfuegbare_konten(con, k)
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
    p = geld.privatkonto(con, k["id"], k=k)
    konten = geld.verfuegbare_konten(con, k)
    offen = steuern.offene_bescheide(con, [r["id"] for r in konten if r["art"] in ("privat", "gewerbe")])
    summe_offen = sum(steuern.offen(b) for b in offen)
    letzte = besoldung.letzte_abrechnung(con, k["id"])
    kz = [("Kontostand", mark(p["saldo"])), ("Offene Steuern & Gebühren", mark(summe_offen)),
          ("Letztes Gehalt (netto)", mark(letzte["netto"]) if letzte else "–"), ("Leitzins", f'{geld.einstellung(con, "leitzins")} %')]
    karten = "".join(
        f'<div class="sa-karte"><small>{esc(geld.art_name(r))}</small><div class="sa-name">{esc(r["name"])}</div>'
        f'<div class="sa-nr az">{nummer_anzeige(r["nummer"])}</div><div class="sa-saldo">{betrag_html(r["saldo"], False)}</div>'
        + (f'<p class="az" style="color:var(--rot)">Gesperrt{": " + esc(r["sperrgrund"]) if r["sperrgrund"] else ""}</p>' if r["gesperrt"] else "")
        + f'<div class="sa-aktionen"><a class="btn" href="{PFAD}ueberweisen/?von={r["id"]}">{amt.ic("arrow-right-left")}Überweisen</a>'
        f'<a class="btn zweit" href="{PFAD}konto/?konto={r["id"]}">{amt.ic("wallet")}Umsätze</a></div></div>' for r in konten)
    bescheide = ""
    if offen:
        bescheide = "<h2>Offene Steuern & Gebühren</h2>" + steuern.bescheid_tabelle(con, offen, f"{PFAD}steuern/")
    inhalt = (f'<h1>{amt.ic("landmark")} Guten Tag, {esc(geld.anzeigename(con, k["id"], k["name"]))}</h1>'
              f'<p class="az">Ihre Konten beim Kaiserlichen Schatz- und Währungsamt</p>{amt.meldung(request)}'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              f'<h2>Meine Konten</h2><div class="sa-karten">{karten}</div>{bescheide}'
              f'<h2>Letzte Umsätze</h2>' + amt.tabelle(UMSATZ_KOPF, umsatz_zeilen(con, p["id"], umsaetze(con, p["id"], 8)), "Noch keine Umsätze.")
              + f'<p><a href="{PFAD}konto/">Alle Umsätze und Kontoauszüge →</a></p>')
    return ant(request, k, "Übersicht", "sa-start", inhalt)


# ---------------------------------------------------------------- Bürger: Konto & Umsätze

@seite("mitglied")
async def konto_seite(request, k):
    con = request.app["db"]
    r, konten = _konto_waehlen(con, k, request)
    m = request.query.get("monat", "")
    q = " ".join(request.query.get("q", "").split())[:60]
    von, bis = _monat_grenzen(m)
    bs = umsaetze(con, r["id"], 500, von, bis, q)
    ein = sum(b["betrag"] for b in bs if b["an"] == r["id"])
    aus = sum(b["betrag"] for b in bs if b["von"] == r["id"])
    monate = "".join(f'<option value="{x}"{" selected" if x == m else ""}>{_monatsname(x)}</option>' for x in _monate(con, r["id"]))
    inhalt = (f'<h1>{amt.ic("wallet")} Konto & Umsätze</h1>{amt.meldung(request)}' + _konto_auswahl(konten, r, f"{PFAD}konto/")
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
    return ant(request, k, "Konto & Umsätze", "sa-konto", inhalt)


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
    konten = geld.verfuegbare_konten(con, k)
    von = request.query.get("von", "")
    an = request.query.get("an", "")
    q = " ".join(request.query.get("q", "").split())[:60]
    treffer = ""
    if q:
        rows = con.execute("SELECT * FROM gk_konten WHERE (name LIKE ? OR nummer LIKE ?) AND art!='sonder' ORDER BY art, name LIMIT 30",
                           (f"%{q}%", f"%{q.replace(' ', '').upper()}%")).fetchall()
        rows += [r for r in con.execute("SELECT * FROM gk_konten WHERE art='sonder' AND stelle!='zentralbank' AND name LIKE ?", (f"%{q}%",))]
        treffer = "<h2>Suchergebnis</h2>" + amt.tabelle(
            ["Empfänger", "Kontonummer", "Kontoart", ""],
            [(esc(r["name"]), f'<span class="sa-nr">{nummer_anzeige(r["nummer"])}</span>', esc(geld.art_name(r)),
              f'<a class="btn zweit" href="{PFAD}ueberweisen/?an={r["nummer"]}&von={esc(von)}">Übernehmen</a>') for r in rows],
            "Kein Konto gefunden.")
    opts = "".join(f'<option value="{r["id"]}"{" selected" if str(r["id"]) == von else ""}>{esc(r["name"])} · {mark(r["saldo"])}</option>' for r in konten)
    inhalt = (f'<h1>{amt.ic("arrow-right-left")} Überweisen</h1>{amt.meldung(request)}'
              f'<form class="sa-formular" method="post" action="{PFAD}ueberweisen/pruefen">{amt.csrf_feld(request)}<div class="zeilen">'
              f'<div><label for="von">Von Konto</label><select id="von" name="von">{opts}</select></div>'
              f'<div><label for="an">Empfänger (Kontonummer)</label><input type="text" id="an" name="an" required value="{esc(nummer_anzeige(an) if an else "")}" '
              'placeholder="IG00 0000 0000 0000" class="sa-nr" autocomplete="off"></div>'
              '<div><label for="b">Betrag in Mark</label><input type="text" id="b" name="betrag" required inputmode="decimal" placeholder="0,00"></div>'
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
    if not ka or ka["stelle"] == "zentralbank":
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
    v, g = e("vermoegensteuer"), e("gewerbesteuer")
    saetze = [("Sozialabgabe (Reichsversicherung)", f'{e("sozialabgabe")} % des Bruttogehalts'),
              ("Länderanteil", f'{e("laenderanteil")} % von Lohn- und Kopfsteuer an den Wohnsitz-Teilstaat'),
              ("Kopfsteuer", f'{mark(e("kopfsteuer"))} je Steuerlauf und Staatsbürger'),
              ("Vermögensteuer", f'{v["satz"]} % des Guthabens über {mark(v["freibetrag"])} je Steuerlauf'),
              ("Gewerbesteuer", f'{mark(g["grund"])} + {g["satz"]} % der Eingänge je Steuerlauf'),
              ("Umsatzsteuer", f'{e("umsatzsteuer")} % (im Preis enthalten) bei Zahlungen an Gewerbe'),
              ("Überweisungssteuer", f'{e("ueberweisungssteuer")} % auf private Überweisungen'),
              ("Säumniszuschlag", f'{e("saeumnis")} % je Mahnstufe · Zahlungsfrist {e("frist_tage")} Tage'),
              ("Leitzins", f'{e("leitzins")} %')]
    geb = [(esc(geld.GEBUEHR_NAMEN.get(s, s)), mark(b)) for s, b in e("gebuehren").items()]
    return ("<h2>Lohnsteuer (Stufentarif auf das Monatsbrutto)</h2>" + amt.tabelle(["Einkommensstufe", "Grenzsteuersatz"], stufen)
            + "<h2>Steuern und Abgaben</h2>" + amt.daten_tabelle(saetze)
            + "<h2>Verwaltungsgebühren</h2>" + amt.tabelle(["Leistung", "Gebühr"], geb)
            + "<h2>Besoldungsordnung</h2>" + besoldung.tabelle_html(con))


@seite()
async def tarife(request, k):
    con = request.app["db"]
    inhalt = (f'<h1>{amt.ic("percent")} Tarife & Sätze</h1><p class="az">Geltende Steuersätze, Gebühren und Besoldung des Reiches. '
              'Festgesetzt vom Kaiserlichen Schatz- und Währungsamt.</p>' + tarife_html(con))
    return ant(request, k, "Tarife & Sätze", "sa-tarife", inhalt)


@seite()
async def finanzen(request, k):
    con = request.app["db"]
    seit = int(time.time()) - 30 * 86400
    kasse = geld.sonder(con, "reichskasse")
    ein = con.execute("SELECT art, SUM(betrag) s FROM gk_buchungen WHERE an=? AND zeit>=? GROUP BY art ORDER BY s DESC", (kasse["id"], seit)).fetchall()
    aus = con.execute("SELECT art, SUM(betrag) s FROM gk_buchungen WHERE von=? AND zeit>=? GROUP BY art ORDER BY s DESC", (kasse["id"], seit)).fetchall()
    verteilung = con.execute("SELECT art, COUNT(*) n, SUM(saldo) s FROM gk_konten WHERE art!='sonder' GROUP BY art").fetchall()
    staaten = con.execute("SELECT name, saldo FROM gk_konten WHERE art='teilstaat' ORDER BY name").fetchall()
    kz = [("Geldmenge im Umlauf", mark(geld.geldmenge(con))), ("Reichskasse", mark(kasse["saldo"])),
          ("Reichsversicherung", mark(geld.sonder(con, "sozialkasse")["saldo"])), ("Leitzins", f'{geld.einstellung(con, "leitzins")} %')]
    inhalt = (f'<h1>{amt.ic("chart-column")} Reichsfinanzen</h1><p class="az">Öffentliche Übersicht über Geldmenge und Reichskasse '
              '(Einnahmen und Ausgaben der letzten 30 Tage).</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              '<h2>Einnahmen der Reichskasse</h2>' + amt.tabelle(["Art", "Summe"], [(esc(geld.BUCHUNGSART.get(r["art"], r["art"])), mark(r["s"])) for r in ein], "Keine Einnahmen.")
              + '<h2>Ausgaben der Reichskasse</h2>' + amt.tabelle(["Art", "Summe"], [(esc(geld.BUCHUNGSART.get(r["art"], r["art"])), mark(r["s"])) for r in aus], "Keine Ausgaben.")
              + '<h2>Verteilung der Geldmenge</h2>' + amt.tabelle(["Kontoart", "Konten", "Guthaben"],
                                                                  [(esc(geld.KONTOART[r["art"]][0]), r["n"], mark(r["s"])) for r in verteilung])
              + '<h2>Staatskassen der Teilstaaten</h2>' + amt.tabelle(["Teilstaat", "Guthaben"], [(esc(r["name"]), mark(r["saldo"])) for r in staaten], "Keine Staatskassen."))
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
    if r["stelle"] != "zentralbank":
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
                         '<div><label for="kb">Betrag in Mark</label><input type="text" id="kb" name="betrag" required></div></div>'
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
    if not r or r["stelle"] == "zentralbank":
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
              '<div><label for="b">Betrag in Mark</label><input type="text" id="b" name="betrag" required></div></div>'
              '<div><label for="g">Begründung</label><input type="text" id="g" name="grund" required maxlength="160"></div>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("coins")}Geld schöpfen</button></div></form>'
              f'<h2>Geldvernichtung</h2><form class="sa-formular" method="post" action="{PFAD}amt/geldpolitik/vernichtung">{amt.csrf_feld(request)}<div class="zeilen">'
              f'<div><label for="q">Quellkonto</label><select id="q" name="ziel">{opts}</select></div>'
              '<div><label for="b2">Betrag in Mark</label><input type="text" id="b2" name="betrag" required></div></div>'
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
    if not z or z["art"] not in ("sonder", "behoerde", "teilstaat") or z["stelle"] == "zentralbank" or not betrag or not grund:
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
