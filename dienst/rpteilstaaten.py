"""RP-Leitung: „Die Teilstaaten“ (/schatzamt/rp/teilstaaten/).

Die RP-Leitung wählt zuerst einen Teilstaat aus und sieht dann alles von ihm: Überblick, Etat (nur Ansicht), Land (Entwicklung, Energie, Krisen), Finanzen (Kassen, Gold, Notlage,
Umsätze), Kassen (→ RP-Kontoseite), Konfiguration (Förderstätten, Kraftwerke, Handelssperre des Teilstaats) und die Stammdaten. Die Reiter Überblick/Land/Finanzen sind dieselben Abschnitte wie bei „Mein Teilstaat“ (teilstaat.ueberblick, land_teile, fin_teile).
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


# IC-Links der Abschnitte (Mein Teilstaat) → Ziele in der RP-Ansicht: Unterseiten des Teilstaats werden zu Reitern dieser Seite,
# Konten zur RP-Kontoseite (mit Maßnahmen), Überweisen entfällt. Übrige Links (Verteidigung, Energiemarkt, Veredelung …) bleiben und öffnen die IC-Seite.
_REITER = [(r"teilstaat/land/", "land"), (r"teilstaat/finanzen/", "finanzen"), (r"teilstaat/einstellungen/", "stammdaten"), (r"teilstaat/", "ueberblick"),
           (r"etatverteilung/", "etat"), (r"etatplanung/", "etat"), (r"entwicklung/", "land"), (r"energie/\?", "land"), (r"krisen/", "land"),
           (r"gold/", "finanzen"), (r"notlagen/", "finanzen")]


def _links_umleiten(html):
    html = re.sub(r'<a [^>]*href="/schatzamt/ueberweisen/[^"]*"[^>]*>.*?</a>', "", html, flags=re.S)
    html = re.sub(r'href="/schatzamt/konto/\?konto=(\d+)[^"]*"', r'href="/schatzamt/rp/konto/\1/" title="RP-Kontoseite mit Maßnahmen"', html)
    for muster, tab in _REITER:
        html = re.sub(r'href="/schatzamt/' + muster + r'[^"#]*(#[^"]*)?"', f'href="#{tab}"', html)
    return html




# Links auf #Reiter innerhalb der Seite schalten den Reiter um (die Reiterleiste reagiert sonst nur auf eigene Klicks)
REITER_JS = """<script>document.addEventListener("click",function(e){var a=e.target.closest('a[href^="#"]');if(!a||a.closest(".ts-nav"))return;
var id=a.getAttribute("href").slice(1),el=document.getElementById("t-"+id)||document.getElementById(id);if(!el)return;e.preventDefault();var k=[];
for(var n=el;n;n=n.parentElement){if(n.classList&&n.classList.contains("ts-tabteil"))k.unshift(n.id.slice(2))}
k.forEach(function(t){var l=document.querySelector('.ts-nav a[data-t="'+t+'"]');if(l)l.click()});el.scrollIntoView({behavior:"smooth",block:"start"})});</script>"""


def _kassen_tab(con, sid):
    import rpleitung
    rows = con.execute("SELECT * FROM gk_konten WHERE stelle IN (?,?) OR stelle LIKE ? ORDER BY art, name", ("ts-" + sid, "vt-" + sid, f"%-{sid}-%")).fetchall()
    z = [(rpleitung._konto_link(r), esc(geld.art_name(r)), f'<span class="sa-nr">{geld.nummer_anzeige(r["nummer"])}</span>', sa.betrag_html(r["saldo"], False),
          amt.status_marke("nein", "Gesperrt") if r["gesperrt"] else amt.status_marke("ok", "Aktiv")) for r in rows]
    return ('<p class="az">Kassen des Teilstaats. Ein Klick öffnet die RP-Kontoseite: Umsätze, Storno je Buchung und Maßnahmen (Beschlagnahme, Sperre …) im Rahmen eines Falls.</p>'
            + amt.tabelle(["Kasse", "Art", "Nummer", "Saldo", "Stand"], z, "Keine Kassen gefunden."))


def _konfig_tab(con, sid, name):
    """Alles, was die RP-Leitung für diesen Teilstaat einstellt – auf einen Blick, mit Sprung in die jeweilige Konfiguration."""
    import energie
    import handel
    schl = "ts-" + sid
    P = sa.PFAD + "rp/"
    pfeil = amt.ic("arrow-right")
    besitzer = handel.gebiet_besitzer(con)
    fz = []
    for ls in handel.lagerstaetten(con):
        a = handel.verteilung_lagerstaette(con, ls, besitzer).get(schl, 0)
        if a >= 0.005:
            fz.append((f'<a href="{P}foerderstaetten/?rohstoff={esc(ls["ressource"])}">{esc(ls["name"])}</a>', esc(handel.RESNAME.get(ls["ressource"], ls["ressource"])),
                       f'{a * 100:.0f} %', f'{ls["menge"]:,}'.replace(",", ".")))
    typen = {t: n for t, n, *_ in energie.TYPEN}
    kw = {}
    for r in energie.kraftwerke(con, schl):
        x = kw.setdefault(r["typ"], [0, 0.0])
        x[0] += 1
        x[1] += r["gwh"]
    kz = [(esc(typen.get(t, t)), str(n), energie.gwh_text(g)) for t, (n, g) in sorted(kw.items(), key=lambda x: -x[1][1])]
    sp = handel.sperre(con, schl)
    sperre = (amt.status_marke("nein", "Handelssperre seit " + amt._zeit(sp["zeit"])) + (f' <span class="az">{esc(sp["grund"])}</span>' if sp["grund"] else "")
              if sp else amt.status_marke("ok", "keine Handelssperre"))
    return ('<p class="az">Was die RP-Leitung für ' + esc(name) + ' eingestellt hat. Geändert wird in der jeweiligen Konfiguration (Pfeil).</p>'
            + f'<h2>Förderstätten <a class="az" href="{P}foerderstaetten/" title="Förderstätten bearbeiten">{pfeil}</a></h2>'
            + amt.tabelle(["Förderstätte", "Rohstoff", "Anteil des Teilstaats", "Jahresförderung"], fz, "Keine Förderstätte in diesem Teilstaat.")
            + f'<h2>Kraftwerke <a class="az" href="{P}energie/" title="Energie: Sätze & Anlagen">{pfeil}</a></h2>'
            + amt.tabelle(["Art", "Anlagen", "Leistung je Monat"], kz, "Keine Kraftwerke.")
            + f'<h2>Handel <a class="az" href="{P}handel/" title="Handel: Waren & Regeln">{pfeil}</a></h2><p>{sperre}</p>'
            + f'<h2>Weitere Konfiguration</h2><p class="az"><a href="{P}stellschrauben/">Stellschrauben</a> (Haushalt, Gold, Notlage, Verteidigung, Behördenetats) · '
              f'<a href="{P}besitz/">Besitzkatalog</a> · <a href="{sa.PFAD}verteidigung/katalog/">Gerätekatalog</a> · '
              f'<a href="{P}protokoll/?staat={esc(schl)}">Protokoll zu diesem Teilstaat</a></p>')


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
    import rpleitung
    import wappen
    leiste = ('<nav class="rp-leiste" aria-label="Teilstaat wählen">'
              + "".join(f'<a href="{PFAD}?ziel=ts-{esc(x["id"])}"{" class=aktiv aria-current=page" if s and x["id"] == s["id"] else ""}>'
                        f'{wappen.klein(x["id"], x["name"], 34) or amt.ic("flag")}<span>{esc(x["name"])}</span></a>' for x in staaten) + "</nav>"
              + '<script>(function(){var a=document.querySelector(".rp-leiste a.aktiv");if(a){var n=a.parentNode;n.scrollLeft=a.offsetLeft-n.clientWidth/2+a.offsetWidth/2}})()</script>')
    wahl = rpleitung.CSS + leiste
    if not s:
        inhalt = (CSS + f'<h1>{amt.ic("flag")} Die Teilstaaten</h1>{amt.meldung(request)}'
                  '<p class="az">Zuerst einen Teilstaat wählen, danach sieht die RP-Leitung alles von ihm: Überblick, Etat, Land, Finanzen, Kassen, Konfiguration und die Stammdaten (editierbar).</p>'
                  + rpleitung.CSS + rpleitung.staaten_raster(con)
                  )
        return sa.ant(request, k, "Die Teilstaaten", "sa-rp-teilstaaten", inhalt)
    sid, schl = s["id"], "ts-" + s["id"]
    kasse = geld.stellenkonto(con, schl)
    liste = aufkommen.berechnen(con, periode=etatplan.monat_heute())
    x = next(y for y in liste if y["staat"] == sid)
    ueber = _links_umleiten(await teilstaat.ueberblick(request, k, con, sid, kasse, kopf=False))
    land = _links_umleiten(teilstaat._abschnitte(None, teilstaat.land_teile(request, k, con, sid, schl)))
    fin = _links_umleiten(teilstaat._abschnitte(None, teilstaat.fin_teile(request, k, con, sid, kasse)))
    import gold
    fin += '<section class="rs-block">' + gold.transfer_html(request, con, von=schl, zurueck=f"{PFAD}?ziel={schl}#finanzen") + '</section>'
    teile = [("ueberblick", "Überblick", ueber), ("etat", "Etat", _links_umleiten(_etat_tab(con, liste, x, sid, schl))), ("land", "Land", land), ("finanzen", "Finanzen", fin),
             ("kassen", "Kassen", _kassen_tab(con, sid)), ("konfiguration", "Konfiguration", _konfig_tab(con, sid, s["name"])),
             ("stammdaten", "Stammdaten", _stammdaten(request, con, s))]
    inhalt = (CSS + teilstaat.kopf_mit_wappen(f'<h1>{amt.ic("flag")} {esc(s["name"])}</h1>', sid, s["name"]) + amt.meldung(request) + wahl + sa.untertabs(teile)
              + REITER_JS)
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
