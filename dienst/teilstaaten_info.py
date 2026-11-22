"""Öffentliche Teilstaaten-Ansicht: /informationen/die-teilstaaten/ (Menü „Informationen“ der Website, auch /en/…).

Aus der RP-Leitungssicht (rpteilstaaten.py) abgeleitet: zuerst das Auswahlmenü (Teilstaat wählen, dazu Wappenkarten), danach die Steckbriefe. Kein Login nötig.
Stufen (Entscheidung: nur Statistiken und Allgemeines sind öffentlich, alles Geld-, Militär- und Krisenbezogene bleibt in Mein Teilstaat):
- ÖFFENTLICH: Wappen, Name, Hauptstadt, Regent, Farben, Gebiete, Fläche, Einwohner, Bevölkerungsdichte, BIP, BIP pro Kopf, HDI, Lebenserwartung, Akademikerquote.
- ANGESTELLTE (Angehörige des Kaiserlichen Schatz- und Währungsamts, ob vom Reich oder einem Regenten eingestellt; dazu Regenten, Kronkanzler, Kaiser, Beamte,
  RP-Leitung): zusätzlich Etat im Monat, Abgabe an das Reich, Verteilung auf die Politikfelder und die Energieversorgung (ohne Kassenstände).
NICHT in dieser Ansicht (nur in „Mein Teilstaat“ für den Regenten und Befugte): Kassen, Gold, Umsätze, Notlage, Krisen, Zufriedenheit, Verteidigung/Militär, Stammdaten-Bearbeitung.
"""
import html

from aiohttp import web

import anmeldung
import befugnisse
import energie
import etatplan
import geld
import karte
import teilstaat
from geld import mark_kurz
from seiten import seite

esc = html.escape
PFAD = "/informationen/die-teilstaaten/"

CSS = """<style>
.ts-wahl{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin:6px 0 22px}
.ts-wahl label{display:block;font:600 .8rem var(--sans);color:var(--muted);margin-bottom:4px}
.ts-wahl select{min-height:44px;font-size:16px;min-width:min(100%,340px);padding:8px 12px}
.ts-karten{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin:10px 0 0}
.ts-karten a{display:flex;align-items:center;gap:12px;border:1px solid var(--rule);padding:12px 14px;color:var(--ink);text-decoration:none;background:var(--white)}
.ts-karten a:hover{border-color:var(--ink)}.ts-karten a[aria-current]{border-color:var(--ink);box-shadow:0 0 0 1px var(--ink)}
.ts-karten img{height:42px;width:auto;max-width:38px;object-fit:contain}
.ts-karten b{font:600 .95rem var(--sans)}
.ts-kopf{display:flex;align-items:center;gap:18px;margin:6px 0 18px}.ts-kopf h2{margin:0}.ts-kopf img{height:84px;width:auto;filter:drop-shadow(0 1px 3px rgba(0,0,0,.3))}
.ts-zahlen{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px;margin:0 0 24px}
.ts-zahlen div{background:var(--white);border:1px solid var(--rule);padding:14px 16px;font:.85rem var(--sans);color:var(--muted)}
.ts-zahlen b{display:block;font:600 1.5rem/1.2 var(--serif);color:var(--ink)}
.ts-tab{width:100%;border-collapse:collapse;margin:8px 0 22px;font:.95rem var(--sans)}
.ts-tab th,.ts-tab td{padding:9px 8px;border-bottom:1px solid var(--rule);text-align:left}.ts-tab td:last-child,.ts-tab th:last-child{text-align:right}
.ts-farbe{display:inline-block;width:16px;height:16px;border:1px solid #0003;vertical-align:-3px;margin-right:6px}
.ts-hinweis{border:1px solid var(--rule);border-left:4px solid var(--flag);background:var(--paper);padding:12px 16px;margin:18px 0;font:.9rem var(--sans)}
@media(max-width:600px){.ts-kopf img{height:60px}.ts-zahlen{grid-template-columns:repeat(2,1fr)}.ts-zahlen b{font-size:1.2rem}}
</style>"""


def _zahl(x, nachkomma=0):
    return f"{x:,.{nachkomma}f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def _regent(request, s):
    """Name des Regenten: Landesherr mit der Fraktionsrolle des Teilstaats (sonst „Kronkanzler verwaltet“)."""
    f = s.get("fraktion")
    if not f:
        return "Der Kronkanzler verwaltet den Teilstaat"
    namen = [m["name"] for m in await request.app["discord"].mitglieder() if f in m["rollen"] and karte.ROLLE_LANDESHERR in m["rollen"]]
    return ", ".join(namen) if namen else "Zurzeit unbesetzt"


def _eingestellt(con, k):
    """Sieht die erweiterte Ansicht: Schatzamts-Angestellte, Regenten, Amtsträger mit Kassenzugang, Kronkanzler/Kaiser, RP-Leitung."""
    import schatzamt as sa
    return bool(k) and bool(k["mitglied"]) and (befugnisse.ist_schatzamt(k) or sa.hat_kassen(con, k) or sa.ist_rp(k))


def _steckbrief(con, s, x, regent, erweitert):
    sid, schl = s["id"], "ts-" + s["id"]
    n_geb = sum(1 for g, v in karte.aktuell(con)["stand"]["gebiete"].items() if v == sid)
    ent = x["entwicklung"]
    ew, bip = x["ew"], x["bip"]   # BIP in Mio. €
    akad = ent["zustand"]["akademiker"]["neu"]
    zahlen = [("Einwohner", _zahl(ew)), ("Fläche", f'{_zahl(x["km2"])} km²'), ("Bevölkerungsdichte", f'{_zahl(ew / x["km2"], 0)} je km²' if x["km2"] else "–"),
              ("Wirtschaftsleistung (BIP)", f'{_zahl(bip / 1000, 1)} Mrd. €'), ("BIP pro Kopf", f'{_zahl(bip * 1e6 / ew, 0)} €' if ew else "–"),
              ("Entwicklungsindex (HDI)", _zahl(ent["hdi"], 3)), ("Lebenserwartung", f'{_zahl(ent["lebenserwartung"], 1)} Jahre'), ("Akademikerquote", f'{_zahl(akad, 1)} %')]
    kz = "".join(f"<div><b>{esc(w)}</b>{esc(t)}</div>" for t, w in zahlen)
    allg = [("Hauptstadt", esc((s.get("hauptstadt") or {}).get("name", "–"))), ("Regent", esc(regent)),
            ("Farben", f'<span class="ts-farbe" style="background:{esc(s["farbe"])}"></span><span class="ts-farbe" style="background:{esc(s["farbe2"])}"></span>'),
            ("Gebiete auf der Reichskarte", str(n_geb))]
    out = (f'<div class="ts-kopf">{teilstaat.wappen_html(sid, s["name"])}<h2>{esc(s["name"])}</h2></div>'
           f'<div class="ts-zahlen">{kz}</div>'
           '<h3>Allgemeines</h3><table class="ts-tab"><tbody>' + "".join(f"<tr><th>{t}</th><td>{w}</td></tr>" for t, w in allg) + "</tbody></table>")
    if erweitert:
        pool = x["pool_land"] or 1
        zeilen = "".join(f'<tr><td>{esc(etatplan.NAMEN[kat])}</td><td>{esc(mark_kurz(b))}</td><td>{etatplan._de(b / pool * 100)} %</td></tr>'
                         for kat, _ in etatplan.KATEGORIEN for b in [x["verteilung_land"].get(kat, 0)])
        b = energie.bilanz(con, schl)
        out += ('<h3>Haushalt (für Angestellte)</h3>'
                f'<div class="ts-zahlen"><div><b>{esc(mark_kurz(x["summe"]))}</b>Etat im Monat</div><div><b>{etatplan._de(x["quote"])} %</b>Abgabe an das Reich</div>'
                f'<div><b>{esc(mark_kurz(x["pool_land"]))}</b>Ausgabenbudget</div></div>'
                '<table class="ts-tab"><thead><tr><th>Politikfeld</th><th>Betrag</th><th>Anteil</th></tr></thead><tbody>' + zeilen + "</tbody></table>"
                '<h3>Energie (für Angestellte)</h3>'
                f'<div class="ts-zahlen"><div><b>{etatplan._de(b["v_ges"] * 100, 0)} %</b>Versorgung</div><div><b>{etatplan._de(b["erneuerbar"], 0)} %</b>Erneuerbar-Anteil</div>'
                f'<div><b>{energie.gwh_text(b["angebot"])}</b>Erzeugung im Monat</div><div><b>{energie.gwh_text(b["bedarf"])}</b>Bedarf im Monat</div></div>')
    return out


async def seite_teilstaaten(request):
    import aufkommen
    con = request.app["db"]
    k = await anmeldung.konto(request)
    en = request.path.startswith("/en/")
    staaten = sorted((s for s in karte.aktuell(con)["stand"]["staaten"] if not geld.ist_reichsgebiet(s)), key=lambda s: s["name"])
    wahl_id = request.query.get("staat", "")
    s = next((x for x in staaten if x["id"] == wahl_id), None)
    basis = ("/en" if en else "") + PFAD
    karten = "".join(f'<a href="{basis}?staat={esc(x["id"])}"{" aria-current=\"page\"" if s and x["id"] == s["id"] else ""}>{teilstaat.wappen_html(x["id"], x["name"]) or "<span></span>"}<b>{esc(x["name"])}</b></a>' for x in staaten)
    erweitert = _eingestellt(con, k)
    if s:
        liste = aufkommen.berechnen(con, periode=etatplan.monat_heute())
        x = next(y for y in liste if y["staat"] == s["id"])
        karte_html = _steckbrief(con, s, x, await _regent(request, s), erweitert)
    else:
        karte_html = '<p class="lead">Wähle unten einen Teilstaat, um seinen Steckbrief zu sehen: Wappen, Regent, Bevölkerung, Wirtschaft und Entwicklung.</p>'
    hinweis = ("" if erweitert else '<div class="ts-hinweis">Hier stehen die öffentlichen Angaben. Angestellte des Kaiserlichen Schatz- und Währungsamts sehen nach der Anmeldung zusätzlich Etat und Energieversorgung.</div>')
    krumen = '<li><a href="/">Hauptseite</a></li><li><a href="/informationen/">Informationen</a></li><li><span aria-current="page">Die Teilstaaten</span></li>'
    kopf = ('<div class="page-head"><div class="wrap"><nav class="breadcrumb" aria-label="Brotkrumen"><ol>' + krumen + '</ol></nav>'
            '<span class="eyebrow">Staatsaufbau</span><h1>Die Teilstaaten</h1></div></div>')
    inhalt = kopf + f'<div class="section"><div class="wrap">{karte_html}{hinweis}<h3>Alle Teilstaaten</h3><div class="ts-karten">{karten}</div></div></div>'
    return web.Response(text=seite("Die Teilstaaten", inhalt, kopf=CSS, konto=k, csrf=request.get("csrf", ""), pfad=request.path, lang="en" if en else "de"),
                        content_type="text/html", headers={"Cache-Control": "no-store"})


def registrieren(app):
    app.router.add_get(PFAD, seite_teilstaaten)
    app.router.add_get("/en" + PFAD, seite_teilstaaten)
