"""RP-Leitung: „Die Teilstaaten“ (/schatzamt/rp/teilstaaten/).

Die RP-Leitung wählt zuerst einen Teilstaat aus und sieht dann alles von ihm: Überblick, Etat (nur Ansicht), Land (Entwicklung, Energie, Krisen), Finanzen (Kassen, Gold, Notlage,
Umsätze) und die Stammdaten. Die Reiter Überblick/Land/Finanzen sind dieselben Abschnitte wie bei „Mein Teilstaat“ (teilstaat.ueberblick, land_teile, fin_teile).
Stammdaten = die allgemeinen Felder des Teilstaats auf der Reichskarte (Name, Hauptstadt, Farben, Muster, Fraktionsrolle). Jedes Feld hat „Editieren“; eine Änderung wird
als neue Kartenversion gespeichert (karte.neue_version, geprüft mit karte.pruefen), im Geld-Protokoll vermerkt und benennt bei einer Umbenennung die Staatskasse um.
Verwandt: Memory „rp-teilstaaten“.
"""
import copy
import re

from aiohttp import web

import amt
import anmeldung
import etatplan
import geld
import karte
import schatzamt as sa
import teilstaat
from geld import mark

esc = amt.esc
PFAD = sa.PFAD + "rp/teilstaaten/"

CSS = """<style>
.rt-wahl{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin:12px 0 18px}
.rt-karten{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px;margin:14px 0}
.rt-karten a{display:flex;align-items:center;gap:10px;border:1px solid var(--linie);border-radius:12px;padding:10px 12px;color:var(--ink);text-decoration:none;background:#fff}
.rt-karten a:hover{background:var(--hell)}
.rt-karten img{height:38px;width:auto;max-width:34px;object-fit:contain}
.rt-felder{width:100%;border-collapse:collapse;margin:8px 0}
.rt-felder td,.rt-felder th{padding:9px 8px;border-bottom:1px solid #eef0f2;text-align:left;vertical-align:top}
.rt-felder th{width:200px;font-weight:600;color:var(--grau)}
.rt-ed summary{cursor:pointer;display:inline-block;padding:3px 10px;border:1px solid var(--linie);border-radius:999px;font-size:13px;margin-left:8px}
.rt-ed[open] summary{background:var(--hell)}
.rt-ed form{display:flex;flex-wrap:wrap;gap:8px;align-items:end;margin:10px 0 2px}
.rt-farbe{display:inline-block;width:16px;height:16px;border-radius:4px;border:1px solid #0003;vertical-align:-3px;margin-right:6px}
</style>"""

FELDER = [("name", "Name"), ("hauptstadt", "Hauptstadt"), ("farbe", "Farbe"), ("farbe2", "Zweitfarbe"), ("muster", "Muster"), ("fraktion", "Fraktionsrolle (Discord-ID)")]
MUSTER_NAMEN = {"voll": "Einfarbig", "streifen": "Streifen", "karo": "Karo", "punkte": "Punkte"}


def _ohne_links(html):
    """Links in die IC-Seiten (Mein Teilstaat) führen für die RP-Leitung ins Leere: Text bleibt, Link entfällt."""
    html = re.sub(r'<a class="ts-karte" href="/schatzamt/[^"]*">(.*?)</a>', r'<div class="ts-karte">\1</div>', html, flags=re.S)
    return re.sub(r'<a href="/schatzamt/[^"]*">(.*?)</a>', r'\1', html, flags=re.S)


def _staat(con, sid):
    return next((s for s in karte.aktuell(con)["stand"]["staaten"] if s["id"] == sid and not geld.ist_reichsgebiet(s)), None)


def _stammdaten(request, con, s):
    sid = s["id"]
    n_geb = sum(1 for g, v in karte.aktuell(con)["stand"]["gebiete"].items() if v == sid)
    wert = {"name": esc(s["name"]), "hauptstadt": esc((s.get("hauptstadt") or {}).get("name", "–")),
            "farbe": f'<span class="rt-farbe" style="background:{esc(s["farbe"])}"></span>{esc(s["farbe"])}',
            "farbe2": f'<span class="rt-farbe" style="background:{esc(s["farbe2"])}"></span>{esc(s["farbe2"])}',
            "muster": esc(MUSTER_NAMEN.get(s["muster"], s["muster"])), "fraktion": esc(s.get("fraktion") or "– (kein Landesherr, Kronkanzler verwaltet)")}
    roh = {"name": s["name"], "hauptstadt": (s.get("hauptstadt") or {}).get("name", ""), "farbe": s["farbe"], "farbe2": s["farbe2"], "muster": s["muster"], "fraktion": s.get("fraktion") or ""}

    def eingabe(f):
        if f in ("farbe", "farbe2"):
            return f'<input type="color" name="wert" value="{esc(roh[f])}" aria-label="Farbe">'
        if f == "muster":
            return '<select name="wert" aria-label="Muster">' + "".join(f'<option value="{m}"{" selected" if m == roh[f] else ""}>{n}</option>' for m, n in MUSTER_NAMEN.items()) + "</select>"
        return f'<input name="wert" value="{esc(roh[f])}" maxlength="120" aria-label="Neuer Wert" style="min-width:260px">'
    zeilen = "".join(
        f'<tr><th>{esc(n)}</th><td>{wert[f]}<details class="rt-ed"><summary>Editieren</summary>'
        f'<form method="post" action="{PFAD}feld">{amt.csrf_feld(request)}<input type="hidden" name="sid" value="{esc(sid)}"><input type="hidden" name="feld" value="{f}">'
        f'{eingabe(f)}<button class="btn" type="submit">Speichern</button></form></details></td></tr>' for f, n in FELDER)
    fest = (f'<tr><th>Kennung</th><td>{esc(sid)}</td></tr><tr><th>Gebiete auf der Karte</th><td>{n_geb}</td></tr>'
            f'<tr><th>Staatskasse</th><td>{esc(geld.stellenkonto(con, "ts-" + sid)["name"])}</td></tr>')
    return ('<p class="az">Die allgemeinen Felder des Teilstaats auf der Reichskarte. Mit „Editieren“ ändert die RP-Leitung ein Feld; die Änderung wird als neue Kartenversion '
            'gespeichert und im Protokoll vermerkt. Gebiete und Gebäude bearbeitet man im Karteneditor.</p>'
            f'<table class="rt-felder"><tbody>{zeilen}{fest}</tbody></table>')


def _etat_tab(con, liste, x, sid, schl):
    import entwicklung
    pool = x["pool_land"] or 1
    zeilen = [(esc(etatplan.NAMEN[kat]), mark(b), f'{etatplan._de(b / pool * 100)} %') for kat, _ in etatplan.KATEGORIEN for b in [x["verteilung_land"].get(kat, 0)]]
    g = entwicklung.rueckhalt_fuer(con, liste, schl)
    return (etatplan.CSS + etatplan.WK_CSS + etatplan.ZUF_CSS
            + '<p class="az">Geltender Etat des Teilstaats im laufenden Monat (nur Ansicht). Planen und Einreichen übernimmt der Landesherr.</p>'
            + f'<div class="kennzahlen"><div><b>{esc(mark(x["summe"]))}</b>Etat im Monat</div><div><b>{esc(mark(x["reich"]))}</b>Abgabe an das Reich ({etatplan._de(x["quote"])} %)</div>'
              f'<div><b>{esc(mark(x["pool_land"]))}</b>Ausgabenbudget</div><div><b>{etatplan._de(etatplan.haushaltsfuehrung(liste, schl))} %</b>Haushaltsführung (Rücklage)</div></div>'
            + amt.tabelle(["Politikfeld", "Betrag", "Anteil am Ausgabenbudget"], zeilen, "Kein Etat.")
            + etatplan.wirkung_html(x["wirkung_land"], x["summe_basis"], x["land"], False)
            + etatplan.zuf_html(x["zufriedenheit_land"], etatplan.zuf_verlauf(con, schl), False, g=g))


@sa.seite("rp")
async def seite(request, k):
    import aufkommen
    con = request.app["db"]
    staaten = sorted((s for s in karte.aktuell(con)["stand"]["staaten"] if not geld.ist_reichsgebiet(s)), key=lambda s: s["name"])
    ziel = request.query.get("ziel", "")
    s = next((x for x in staaten if "ts-" + x["id"] == ziel), None)
    auswahl = "".join(f'<option value="ts-{esc(x["id"])}"{" selected" if s and x["id"] == s["id"] else ""}>{esc(x["name"])}</option>' for x in staaten)
    wahl = (f'<form class="rt-wahl" method="get"><div><label for="rt-ziel">Teilstaat wählen</label><select id="rt-ziel" name="ziel" onchange="this.form.submit()">'
            f'{"" if s else "<option value=\"\" selected>– bitte auswählen –</option>"}{auswahl}</select></div><noscript><button class="btn zweit" type="submit">Anzeigen</button></noscript></form>')
    if not s:
        karten = "".join(f'<a href="{PFAD}?ziel=ts-{esc(x["id"])}">{teilstaat.wappen_html(x["id"], x["name"]) or "<span></span>"}<b>{esc(x["name"])}</b></a>' for x in staaten)
        inhalt = (CSS + f'<h1>{amt.ic("flag")} Die Teilstaaten</h1>{amt.meldung(request)}'
                  '<p class="az">Zuerst einen Teilstaat wählen, danach sieht die RP-Leitung alles von ihm: Überblick, Etat, Land, Finanzen und die Stammdaten (editierbar).</p>' + wahl
                  + f'<div class="rt-karten">{karten}</div>')
        return sa.ant(request, k, "Die Teilstaaten", "sa-rp-teilstaaten", inhalt)
    sid, schl = s["id"], "ts-" + s["id"]
    kasse = geld.stellenkonto(con, schl)
    liste = aufkommen.berechnen(con, periode=etatplan.monat_heute())
    x = next(y for y in liste if y["staat"] == sid)
    ueber = _ohne_links(await teilstaat.ueberblick(request, k, con, sid, kasse, kopf=False))
    land = _ohne_links(teilstaat._abschnitte(None, teilstaat.land_teile(request, k, con, sid, schl)))
    fin = _ohne_links(teilstaat._abschnitte(None, teilstaat.fin_teile(request, k, con, sid, kasse)))
    teile = [("ueberblick", "Überblick", ueber), ("etat", "Etat", _ohne_links(_etat_tab(con, liste, x, sid, schl))), ("land", "Land", land), ("finanzen", "Finanzen", fin),
             ("stammdaten", "Stammdaten", _stammdaten(request, con, s))]
    inhalt = (CSS + teilstaat.kopf_mit_wappen(f'<h1>{amt.ic("flag")} {esc(s["name"])}</h1>', sid, s["name"]) + amt.meldung(request) + wahl + sa.untertabs(teile))
    return sa.ant(request, k, "Die Teilstaaten", "sa-rp-teilstaaten", inhalt)


async def feld(request):
    k = await anmeldung.konto(request)
    if not sa.ist_rp(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    sid, f, wert = str(form.get("sid", "")), str(form.get("feld", "")), str(form.get("wert", "")).strip()
    s = _staat(con, sid)
    ziel = f"{PFAD}?ziel=ts-{sid}"
    if not s or f not in dict(FELDER):
        raise web.HTTPNotFound()
    ziel_stammdaten = ziel
    stand = copy.deepcopy(karte.aktuell(con)["stand"])
    e = next(x for x in stand["staaten"] if x["id"] == sid)
    alt = {"hauptstadt": (e.get("hauptstadt") or {}).get("name", "")}.get(f, e.get(f, ""))
    if f == "hauptstadt":
        if not e.get("hauptstadt"):
            sa.weiter(ziel_stammdaten, "Dieser Teilstaat hat noch keine Hauptstadt auf der Karte; sie wird im Karteneditor gesetzt.", True)
        e["hauptstadt"]["name"] = wert
    elif f == "fraktion":
        e["fraktion"] = re.sub(r"\D", "", wert)
    else:
        e[f] = wert
    try:
        sauber = karte.pruefen(stand)
    except karte.Ungueltig as ex:
        sa.weiter(ziel_stammdaten, str(ex), True)
    neu = next(x for x in sauber["staaten"] if x["id"] == sid)
    text = f'RP-Leitung: {dict(FELDER)[f]} von {s["name"]} geändert ({alt or "–"} → {wert or "–"})'
    karte.neue_version(con, sauber, text, k)
    if f == "name":   # Staatskasse folgt dem Namen (wie geld.teilstaaten_sichern)
        import landespolizei
        con.execute("UPDATE gk_konten SET name=? WHERE stelle=?", ("Staatskasse " + landespolizei._kurzname(neu["name"]), "ts-" + sid))
    geld.protokoll(con, k, "Teilstaat bearbeitet", text)
    con.commit()
    sa.weiter(ziel_stammdaten, f"{dict(FELDER)[f]} gespeichert.")


def registrieren(app):
    app.router.add_get(PFAD, seite)
    app.router.add_post(PFAD + "feld", feld)
