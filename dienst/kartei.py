"""Mitgliederkartei der Reichsverwaltung (Amtsseite, nur Kaiser und Kronkanzler; Server-Admins OOC wie überall auf der Amtsseite).

* Mitglieder = Discord-Mitglieder mit einer Rolle aus der Rollengruppe „Reichsverwaltung“ (Trenner amt.ROLLE_AKTEN, inkl. Sammelrolle),
  einer Behördenrolle (amt.BEHOERDEN) oder einer Rolle des Schatzamts (Schatzamt, Reichsinspektor).
* Ebenen: Kronkanzlei, Reichsbehörden, Reichsverwaltung (Laufbahn), Landesverwaltung (Ämter der Teilstaaten, amt.ROLLEN_AKTEN_NIE).
* Liste: Karteikarten mit Registerbuchstaben, Live-Filter (Text, Ebene, Behörde), Sortierung Name/Rang; im Hintergrund das Logo „Die Reichsbehörden“.
* Karteikarte je Person: Dienstverhältnis (Ämter, Behörden, Dienstgrad, Besoldung), Personalien (Bürgerakte), Kontakt, Dokumente,
  Befugnisse in Teilstaaten, Tätigkeit (Zähler + letzte Vorgänge) und Personalvermerke (Tabelle kartei_vermerke, nur Kaiser/Kronkanzler).
"""
import secrets
import time
from html import escape as esc

from aiohttp import web

import amt
import anmeldung
import config

BASIS = amt.BASIS
PFAD = BASIS + "kartei/"
ROLLE_SAMMEL = "1526348059984789504"             # Sammelrolle „Reichsverwaltung“
ROLLEN_SCHATZAMT = {"1574139894765195337": "schatzamt", "1574139896011030680": "schatzamt"}   # Schatzamt, Reichsinspektor
EBENEN = [("kanzlei", "Kronkanzlei"), ("behoerden", "Reichsbehörden"), ("verwaltung", "Reichsverwaltung"), ("land", "Landesverwaltung")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS kartei_vermerke (id INTEGER PRIMARY KEY AUTOINCREMENT, konto_id TEXT NOT NULL, zeit INTEGER NOT NULL,
    text TEXT NOT NULL, autor_id TEXT NOT NULL, autor_name TEXT NOT NULL);
"""

amt.ICONS.setdefault("contact", '<path d="M16 2v2"/><path d="M7 22v-2a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v2"/><path d="M8 2v2"/>'
                                '<circle cx="12" cy="11" r="3"/><rect x="3" y="4" width="18" height="18" rx="2"/>')


def darf(k):
    return bool(k) and k["mitglied"] and (k["id"] in amt.ZUGANG_IDS or bool(set(k["rollen"]) & amt.ROLLEN_ZUGANG) or amt.ist_ooc_admin(k))


def nav(k):
    return [("kartei", "contact", "Mitgliederkartei", "kartei/")] if darf(k) else []


# ---------------------------------------------------------------- Daten

async def _rollen(app):
    """{id: {name, position}} und die Rollen-IDs der Gruppe „Reichsverwaltung“."""
    roh = await app["discord"]._rollen_roh()
    namen = {r["id"]: {"name": r["name"], "pos": r["position"]} for r in roh}
    gruppe, drin = set(), False
    for r in roh:
        if "━" in r["name"]:
            drin = r["id"] == amt.ROLLE_AKTEN
        elif drin:
            gruppe.add(r["id"])
    return namen, gruppe


def _behoerden_von(rollen):
    rs = set(rollen)
    out = [(b, bool(rs & set(b["leitung"]))) for b in amt.BEHOERDEN if rs & set(b["rollen"])]
    if rs & set(ROLLEN_SCHATZAMT) and not any(b["schl"] == "schatzamt" for b, _ in out):
        out.append((next(b for b in amt.BEHOERDEN if b["schl"] == "schatzamt"), False))
    return out


def _ebenen(rollen, gruppe):
    rs = set(rollen)
    e = []
    if amt.ROLLE_KANZLER in rs:
        e.append("kanzlei")
    if _behoerden_von(rollen):
        e.append("behoerden")
    if rs & (gruppe - amt.ROLLEN_AKTEN_NIE - {amt.ROLLE_KANZLER}):
        e.append("verwaltung")
    if rs & amt.ROLLEN_AKTEN_NIE:
        e.append("land")
    return e


async def mitglieder(app):
    """Alle Mitglieder der Reichsverwaltung als Dicts (ohne Datenbankabfragen außer Akte/Lichtbild/Anmeldung)."""
    con = app["db"]
    namen, gruppe = await _rollen(app)
    relevant = gruppe | {r for b in amt.BEHOERDEN for r in b["rollen"]} | set(ROLLEN_SCHATZAMT)
    import lichtbild
    out = []
    for m in await app["discord"].mitglieder():
        rs = [r for r in m["rollen"] if r in namen]
        if not set(rs) & relevant:
            continue
        aemter = sorted((r for r in rs if r in relevant and r != ROLLE_SAMMEL), key=lambda r: -namen[r]["pos"])
        akte = con.execute("SELECT * FROM amt_akten WHERE konto_id=?", (m["id"],)).fetchone()
        kt = con.execute("SELECT angemeldet FROM konten WHERE id=?", (m["id"],)).fetchone()
        fraktion = next((namen[r]["name"] for r in sorted(rs, key=lambda r: -namen[r]["pos"]) if _ist_fraktion(namen, r)), "")
        rang = next((namen[r]["name"] for r in sorted(rs, key=lambda r: -namen[r]["pos"]) if namen[r]["name"][:3] in ("OF-", "OR-")), "")
        out.append({"id": m["id"], "discord": m["name"], "name": (akte["ic_name"] if akte and akte["ic_name"] else m["name"]),
                    "akte": akte, "rollen": rs, "aemter": [namen[r]["name"] for r in aemter],
                    "amt": namen[aemter[0]]["name"] if aemter else "Reichsverwaltung", "pos": namen[aemter[0]]["pos"] if aemter else 0,
                    "behoerden": _behoerden_von(rs), "ebenen": _ebenen(rs, gruppe), "fraktion": fraktion, "rang": rang,
                    "foto": lichtbild.url(con, akte["id"], m["id"]) if akte else lichtbild.url(con, 0, m["id"]),
                    "angemeldet": kt["angemeldet"] if kt else None})
    return out, namen


_FRAKTIONEN = None


def _ist_fraktion(namen, r):
    """Rolle liegt in der Gruppe „Fraktionen“ (ohne Sammelrollen)."""
    return r in (_FRAKTIONEN or set())


async def _fraktionen_laden(app):
    global _FRAKTIONEN
    _FRAKTIONEN = await app["discord"].rollen_der_gruppe("Fraktionen") - {"1522931993661407363"}   # „Imperium Germanicum“ ist keine Fraktion


# ---------------------------------------------------------------- Darstellung

CSS = """<style>
.kartei{position:relative;isolation:isolate}
.kartei-logo{position:sticky;top:calc(50vh - 110px);height:0;z-index:-1;pointer-events:none}
.kartei-logo img{display:block;margin:0 auto;width:min(760px,88%);opacity:.06}
.kartei .kennzahlen{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))!important}
.kt-leiste{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin:6px 0 16px}
.kt-leiste .f-suche{flex:1 1 240px}.kt-leiste input[type=search]{width:100%}
.kt-chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px}
.kt-chip{border:1px solid var(--linie);background:#fff;border-radius:999px;padding:6px 12px;font:inherit;font-size:13px;cursor:pointer;color:var(--ink)}
.kt-chip.an{background:var(--ink);color:#fff;border-color:var(--ink)}
.kt-chip i{font-style:normal;opacity:.6;margin-left:4px}
.kt-register{font-size:12px;font-weight:700;letter-spacing:.12em;color:var(--grau);margin:18px 0 8px;display:flex;align-items:center;gap:10px}
.kt-register::after{content:"";flex:1;height:1px;background:var(--linie)}
.kt-raster{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.kt-karte{position:relative;display:flex;gap:12px;padding:16px 14px 14px;border:1px solid var(--linie);border-radius:6px 18px 18px 18px;background:#fff;
 color:var(--ink);text-decoration:none;min-width:0;margin-top:10px}
.kt-karte::before{content:attr(data-reiter);position:absolute;left:-1px;top:-19px;height:18px;padding:2px 10px 0;font-size:10.5px;font-weight:700;letter-spacing:.08em;
 color:var(--grau);background:inherit;border:1px solid var(--linie);border-bottom:0;border-radius:8px 8px 0 0}
.kt-karte:hover{border-color:var(--ink)}
.kt-foto{width:58px;height:74px;border-radius:6px;object-fit:cover;background:#eef0f2;flex:none;display:grid;place-items:center;font-weight:700;color:var(--grau);font-size:18px}
.kt-text{min-width:0;flex:1}
.kt-text b{display:block;font-size:15px;line-height:1.25}
.kt-text .kt-amt{display:block;font-size:13px;color:var(--ink);margin-top:2px}
.kt-text small{display:block;color:var(--grau);font-size:12px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kt-marken{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.kt-marken span{font-size:11px;border:1px solid var(--linie);border-radius:999px;padding:1px 8px;color:var(--grau);white-space:nowrap}
.kt-marken span.ltg{border-color:var(--ink);color:var(--ink);font-weight:600}
.kt-marken span.warn{border-color:#e7b4b4;color:#a33;background:#fdf3f3}
.kt-leer{display:none}
/* Karteikarte (Detail) */
.kt-blatt{position:relative;isolation:isolate;border:1px solid var(--linie);border-radius:8px 22px 22px 22px;background:#fff;padding:22px;margin-top:22px}
.kt-blatt>.kartei-logo{z-index:0}.kt-blatt>*:not(.kartei-logo){position:relative;z-index:1}
.kt-zahlen div.null{opacity:.5}
.kt-frueher{display:block;margin-top:4px;font-size:12px;color:var(--grau)}
.kt-kopf{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap}
.kt-kopf .kt-foto{width:105px;height:135px;font-size:30px}
.kt-kopf h1{margin:0 0 4px}
.kt-kopf .kt-amt{font-size:15px}
.kt-spalten{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:0 28px}
.kt-zahlen{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:8px 0 6px}
.kt-zahlen div{border:1px solid var(--linie);border-radius:12px;padding:10px 12px;background:rgba(255,255,255,.7)}
.kt-zahlen b{display:block;font-size:20px}.kt-zahlen span{font-size:12px;color:var(--grau)}
.kt-vermerk{border-left:3px solid var(--ink);padding:6px 12px;margin:10px 0;background:rgba(255,255,255,.6)}
.kt-vermerk p{margin:0;white-space:pre-wrap;word-break:break-word}.kt-vermerk small{color:var(--grau)}
.kt-vermerk form{display:inline}.kt-vermerk button{border:0;background:none;color:var(--grau);cursor:pointer;font:inherit;font-size:12px;text-decoration:underline;padding:0}
html:root .kt-karte,html:root .kt-blatt{background:var(--glas-blatt,#fff);border-color:var(--glas-rand,var(--linie));box-shadow:var(--glas-schatten,none),var(--glas-licht,0 0 #0000)}
html:root .kt-karte::before{background:var(--glas-dicht,#fff);border-color:var(--glas-rand,var(--linie))}
html:root .kt-karte:hover{background:#fff;transform:translateY(-1px)}
html:root .kt-karte{transition:transform .25s var(--feder,ease),box-shadow .25s,background .2s}
@media (max-width:520px){.kt-raster{grid-template-columns:1fr}.kt-blatt{padding:16px}.kt-kopf .kt-foto{width:84px;height:108px}.kt-spalten{grid-template-columns:1fr}}
</style>"""

JS = """<script>(function(){var q=document.getElementById('kt-q'),chips=[].slice.call(document.querySelectorAll('.kt-chip')),
 beh=document.getElementById('kt-beh'),sort=document.getElementById('kt-sort'),raster=document.getElementById('kt-liste'),
 karten=[].slice.call(raster.querySelectorAll('.kt-karte')),leer=document.getElementById('kt-nichts'),zahl=document.getElementById('kt-zahl'),ebene='';
function norm(s){return (s||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')}
function zeichnen(){var t=norm(q.value).split(/\\s+/).filter(Boolean),b=beh.value,n=0,s=sort.value;
 var sicht=karten.filter(function(k){var h=k.dataset.such,ok=t.every(function(w){return h.indexOf(w)>=0});
  if(ebene&&k.dataset.ebenen.split(' ').indexOf(ebene)<0)ok=false;if(b&&k.dataset.beh.split(' ').indexOf(b)<0)ok=false;return ok});
 sicht.sort(s==='rang'?function(a,b){return b.dataset.pos-a.dataset.pos||a.dataset.name.localeCompare(b.dataset.name,'de')}
  :function(a,b){return a.dataset.name.localeCompare(b.dataset.name,'de')});
 raster.textContent='';var buch='',grid=null;
 sicht.forEach(function(k){var l=s==='rang'?k.dataset.ebene1:k.dataset.name.charAt(0).toUpperCase();
  if(s!=='rang')l='';if(l!==buch||!grid){buch=l;if(l){var h=document.createElement('div');h.className='kt-register';h.textContent=l;raster.appendChild(h)}
   grid=document.createElement('div');grid.className='kt-raster';raster.appendChild(grid)}grid.appendChild(k);n++});
 leer.style.display=n?'none':'block';zahl.textContent=n;
 try{localStorage.setItem('ktSort',s)}catch(e){}}
chips.forEach(function(c){c.addEventListener('click',function(){chips.forEach(function(x){x.classList.remove('an')});c.classList.add('an');ebene=c.dataset.ebene;zeichnen()})});
q.addEventListener('input',zeichnen);beh.addEventListener('change',zeichnen);sort.addEventListener('change',zeichnen);
try{var gs=localStorage.getItem('ktSort');if(gs)sort.value=gs}catch(e){}
document.querySelector('.kt-leiste').addEventListener('submit',function(e){e.preventDefault()});
zeichnen()})()</script>"""


def _css():
    return CSS.replace("__LOGO__", BASIS + "logo/reichsbehoerden.png")


def _initialen(n):
    return amt._initialen(n or "?")


def _foto(m, gross=False):
    if m["foto"]:
        return f'<img class="kt-foto" src="{esc(m["foto"])}" alt="" loading="lazy">'
    return f'<span class="kt-foto" aria-hidden="true">{esc(_initialen(m["name"]))}</span>'


def _zeit(ts, uhr=False):
    return amt._zeit(ts, uhr) if ts else "–"


def _karte(m):
    beh = " ".join(b["schl"] for b, _ in m["behoerden"])
    marken = "".join(f'<span class="{"ltg" if l else ""}">{esc(b["kurz"])}{" · Leitung" if l else ""}</span>' for b, l in m["behoerden"])
    if not m["akte"]:
        marken += '<span class="warn">ohne Bürgerakte</span>'
    if m["fraktion"]:
        marken += f'<span>{esc(m["fraktion"])}</span>'
    reiter = (m["name"][:1].upper() + " · ") + (amt.az_akte(m["akte"]["id"]) if m["akte"] else "OHNE AKTE")
    unter = (f'Discord: {m["discord"]}' if m["discord"] != m["name"] else "IC-Name nicht erfasst")
    such = " ".join([m["name"], m["discord"], m["amt"], " ".join(m["aemter"]), m["fraktion"], m["rang"], reiter, m["id"],
                     " ".join(b["kurz"] + " " + b["name"] for b, _ in m["behoerden"])])
    import unicodedata
    such = "".join(c for c in unicodedata.normalize("NFD", such.lower()) if unicodedata.category(c) != "Mn")
    ebene1 = dict(EBENEN).get(m["ebenen"][0], "Reichsverwaltung") if m["ebenen"] else "Reichsverwaltung"
    return (f'<a class="kt-karte" href="{PFAD}{esc(m["id"])}/" data-reiter="{esc(reiter)}" data-name="{esc(m["name"])}" data-pos="{m["pos"]}"'
            f' data-ebenen="{" ".join(m["ebenen"])}" data-ebene1="{esc(ebene1)}" data-beh="{esc(beh)}" data-such="{esc(such)}">'
            f'{_foto(m)}<span class="kt-text"><b>{esc(m["name"])}</b><span class="kt-amt">{esc(m["amt"])}</span>'
            f'<small>{esc(unter)}</small><span class="kt-marken">{marken}</span></span></a>')


def _rahmen(request, titel, inhalt, status=200):
    return web.Response(status=status, content_type="text/html", headers={"Cache-Control": "no-store"},
                        text=amt.rahmen(titel, "kartei", _css() + inhalt, request["konto"], request["csrf"]))


def _pruefen(handler):
    async def inner(request):
        k = await anmeldung.konto(request)
        if not k:
            raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
        if not darf(k):
            return _rahmen(request, "Kein Zugang", '<div class="warnung">Die Mitgliederkartei ist dem Kaiser und dem Kronkanzler vorbehalten.</div>', 403)
        if _FRAKTIONEN is None:
            try:
                await _fraktionen_laden(request.app)
            except Exception:
                pass
        return await handler(request, k)
    return inner


@_pruefen
async def liste(request, k):
    con = request.app["db"]
    ms, _ = await mitglieder(request.app)
    import besoldung
    zahl_ebene = {e: sum(1 for m in ms if e in m["ebenen"]) for e, _ in EBENEN}
    ohne_akte = sum(1 for m in ms if not m["akte"])
    nie = sum(1 for m in ms if not m["angemeldet"])
    try:
        namen = {r["id"]: r["name"] for r in await request.app["discord"].rollen_liste()}
        brutto = sum(t["brutto"] for m in ms for t in besoldung.berechnen_einzeln(con, m["id"], m["name"], m["rollen"], namen))
        import geld
        bez = geld.mark(brutto)
    except Exception:
        bez = "–"
    kz = [("Mitglieder", len(ms)), ("Reichsbehörden", zahl_ebene["behoerden"]), ("Landesverwaltung", zahl_ebene["land"]),
          ("Ohne Bürgerakte", ohne_akte), ("Nie auf der Website", nie), ("Bezüge im Monat (brutto)", bez)]
    chips = f'<button type="button" class="kt-chip an" data-ebene="">Alle<i>{len(ms)}</i></button>' + "".join(
        f'<button type="button" class="kt-chip" data-ebene="{e}">{esc(t)}<i>{zahl_ebene[e]}</i></button>' for e, t in EBENEN if zahl_ebene[e])
    behs = "".join(f'<option value="{b["schl"]}">{esc(b["kurz"])}</option>' for b in amt.BEHOERDEN
                   if any(b["schl"] == x["schl"] for m in ms for x, _ in m["behoerden"]))
    inhalt = (f'<div class="kartei"><div class="kartei-logo" aria-hidden="true"><img src="{BASIS}logo/reichsbehoerden.png" alt=""></div>'
              f'<h1>{amt.ic("contact")} Mitgliederkartei</h1><p class="az">Reichsverwaltung · Personal der Reichsbehörden, der Laufbahnen und der Landesverwaltung · '
              f'Vertraulich – nur Kaiser und Kronkanzler</p>{amt.meldung(request)}'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(str(v))}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              f'<form class="kt-leiste" role="search"><div class="f-suche"><label for="kt-q">Kartei durchsuchen</label>'
              f'<input type="search" id="kt-q" placeholder="Name, Amt, Dienstgrad, Fraktion, Aktenzeichen …" autocomplete="off"></div>'
              f'<div><label for="kt-beh">Behörde</label><select id="kt-beh"><option value="">Alle</option>{behs}</select></div>'
              f'<div><label for="kt-sort">Ordnung</label><select id="kt-sort"><option value="name">Alphabetisch</option><option value="rang">Nach Ebene und Rang</option></select></div></form>'
              f'<div class="kt-chips" role="group" aria-label="Ebene">{chips}</div>'
              f'<p class="az"><span id="kt-zahl">{len(ms)}</span> Karteikarten</p>'
              f'<div id="kt-liste">{"".join(_karte(m) for m in sorted(ms, key=lambda m: m["name"].lower()))}</div>'
              f'<p class="leer" id="kt-nichts" style="display:none">Keine Karteikarte passt zur Suche.</p></div>' + JS)
    return _rahmen(request, "Mitgliederkartei", inhalt)


def _zaehlen(con, sql, *a):
    try:
        return con.execute(sql, a).fetchone()[0]
    except Exception:
        return 0


@_pruefen
async def karte(request, k):
    con = request.app["db"]
    kid = request.match_info["id"]
    ms, namen = await mitglieder(request.app)
    m = next((x for x in ms if x["id"] == kid), None)
    if not m:
        raise web.HTTPNotFound(text="Keine Karteikarte – die Person gehört nicht (mehr) zur Reichsverwaltung.")
    import besoldung
    import geld
    import meldewesen
    a = m["akte"]
    pfad = f"{PFAD}{kid}/"
    # Dienstverhältnis
    rn = {r: v["name"] for r, v in namen.items()}
    try:
        teile = besoldung.berechnen_einzeln(con, kid, m["name"], m["rollen"], rn)
    except Exception:
        teile = []
    letzte = besoldung.letzte_abrechnung(con, kid)
    stellen = dict(besoldung.zahlstellen(con))
    dienst = [("Amt", esc(m["amt"])), ("Alle Ämter und Rollen", esc(", ".join(m["aemter"]) or "–")),
              ("Behörden", ", ".join(f'<a href="{BASIS}bereich/{b["schl"]}/">{esc(b["name"])}</a>' + (" " + amt.status_marke("neutral", "Leitung") if l else "")
                                     for b, l in m["behoerden"]) or "–"),
              ("Dienstgrad", esc(m["rang"] or "–")), ("Ebene", esc(", ".join(dict(EBENEN)[e] for e in m["ebenen"]) or "–"))]
    if teile:
        h = teile[0]
        dienst += [("Besoldungsgruppe", esc(f'{h["gruppe"]} – {h["gruppe_name"]}')), ("Grundlage", esc(h["quelle"])),
                   ("Bezüge im Monat", f'{geld.mark(sum(t["brutto"] for t in teile))} brutto · {geld.mark(sum(t["netto"] for t in teile))} netto'),
                   ("Zahlstelle", esc(", ".join(stellen.get(t["zahlstelle"], t["zahlstelle"]) for t in teile)))]
    else:
        dienst.append(("Besoldung", "Keine Besoldung"))
    if letzte:
        dienst.append(("Letzte Abrechnung", f'{esc(letzte["periode"])} · {geld.mark(letzte["netto"])} netto'))
    # Personalien
    if a:
        ws = meldewesen.wohnsitz(con, a["id"])
        pers = [("Bürgerakte", f'<a href="{BASIS}buerger/{a["id"]}/">{amt.az_akte(a["id"])}</a> ' + amt.akte_marke(a["status"])),
                ("Name (IC)", esc(a["ic_name"] or "– (nicht erfasst)")), ("Geburtsdatum (IC)", esc(a["ic_geburt"] or "–")),
                ("Geschlecht", esc(a["geschlecht"] or "–")), ("Fraktion", esc(a["fraktion"] or m["fraktion"] or "–")),
                ("Gesellschaftsschicht", esc(a["schicht"] or "–")), ("Position laut Akte", esc(a["position"] or "–")),
                ("Wohnsitz", esc((ws["staat_name"] + (" · " + ws["anschrift"] if ws["anschrift"] else "")) if ws and ws["art"] != "abmeldung"
                                 else "Im Ausland" if ws else "Nicht gemeldet"))]
        if a["verschluss"]:
            pers.insert(1, ("Verschluss", amt.status_marke("rot", "Akte unter Verschluss")))
    else:
        pers = [("Bürgerakte", '<span class="s-offen">Keine Bürgerakte vorhanden</span>'), ("Fraktion (Discord)", esc(m["fraktion"] or "–"))]
    # Kontakt
    adr = con.execute("SELECT adresse, aktuell FROM post_adressen WHERE konto_id=? ORDER BY aktuell DESC, angelegt DESC", (kid,)).fetchall()
    alt_adr = [x["adresse"] for x in adr if not x["aktuell"]]
    kontakt = [("E-Mail", (" · ".join(f'<a href="{BASIS}postfach/neu/?an={esc(x["adresse"])}">{esc(x["adresse"])}</a>' for x in adr if x["aktuell"]) or "–")
                + (f'<span class="kt-frueher" title="{esc(", ".join(alt_adr))}">Früher: {esc(", ".join(alt_adr))}</span>' if alt_adr else "")),
               ("Discord-Name", esc(m["discord"])), ("Discord-ID", esc(kid)), ("Letzte Anmeldung (Website)", _zeit(m["angemeldet"], True))]
    # Dokumente
    paesse = con.execute("SELECT * FROM pw_paesse WHERE konto_id=? ORDER BY id DESC", (kid,)).fetchall()
    dok = amt.tabelle(["Passnummer", "Art", "Gültig bis", "Stand"],
                      [(f'<a class="mw-nr" href="{meldewesen.PFAD}paesse/{p["id"]}/">{esc(p["nummer"])}</a>', esc(meldewesen.PASSARTEN.get(p["art"], (p["art"],))[0]),
                        meldewesen._datum(p["gueltig_bis"]), meldewesen.pass_marke(p)) for p in paesse], "Keine Pässe ausgestellt.")
    # Befugnisse
    import befugnisse
    st = {s["id"]: s["name"] for s in meldewesen.staaten(con)}
    bef = {}
    for r in con.execute("SELECT * FROM ts_befugnisse WHERE konto_id=? AND recht NOT LIKE '\\_%' ESCAPE '\\'", (kid,)):
        bef.setdefault((r["sid"], r["von"]), []).append(befugnisse.BEREICHE.get(r["recht"].split(":")[0], (r["recht"],))[0])
    befz = [(esc(st.get(s, s)), esc(", ".join(sorted(set(v)))), esc(von)) for (s, von), v in sorted(bef.items())]
    # Tätigkeit
    z = [("Aktenvorgänge", _zaehlen(con, "SELECT COUNT(*) FROM amt_eintraege WHERE autor_id=?", kid)),
         ("Passvorgänge", _zaehlen(con, "SELECT COUNT(*) FROM pw_eintraege WHERE autor_id=?", kid)),
         ("Zollstempel", _zaehlen(con, "SELECT COUNT(*) FROM zv_stempel WHERE beamter_id=?", kid)),
         ("Amtshilfe", _zaehlen(con, "SELECT COUNT(*) FROM ah_eintraege WHERE autor_id=?", kid)),
         ("Strafsachen", _zaehlen(con, "SELECT COUNT(*) FROM sa_eintraege WHERE autor_id=?", kid)),
         ("Polizeiberichte", _zaehlen(con, "SELECT COUNT(*) FROM lp_eintraege WHERE autor_id=?", kid)),
         ("Pinnwand", _zaehlen(con, "SELECT COUNT(*) FROM bereich_mitteilungen WHERE autor_id=?", kid)),
         ("Post gesendet", _zaehlen(con, "SELECT COUNT(*) FROM post_nachrichten WHERE absender_id=?", kid))]
    sa_, sk = amt.sperren(con, k)
    verf = {r["id"] for r in con.execute("SELECT id, konto_id FROM amt_verfahren") if r["konto_id"] in sk}
    letzte_v = [{"zeit": e["zeit"], "art": e["art"], "text": "" if (e["ziel"] == "akte" and e["ziel_id"] in sa_) or (e["ziel"] == "verfahren" and e["ziel_id"] in verf)
                 else amt.kurztext(e["text"], 200), "autor_name": e["autor_name"], "ziel": e["ziel"], "ziel_id": e["ziel_id"]}
                for e in con.execute("SELECT * FROM amt_eintraege WHERE autor_id=? ORDER BY id DESC LIMIT 8", (kid,))]
    link = lambda e: (f'{BASIS}{"buerger" if e["ziel"] == "akte" else "verfahren"}/{e["ziel_id"]}/',
                      amt.az_akte(e["ziel_id"]) if e["ziel"] == "akte" else "Verfahren " + str(e["ziel_id"]))
    # Vermerke
    vm = con.execute("SELECT * FROM kartei_vermerke WHERE konto_id=? ORDER BY id DESC", (kid,)).fetchall()
    vermerke = "".join(
        f'<div class="kt-vermerk"><p>{esc(v["text"])}</p><small>{esc(v["autor_name"])} · {_zeit(v["zeit"], True)}'
        + (f' · <form method="post" action="{pfad}vermerk/{v["id"]}/loeschen">{amt.csrf_feld(request)}<button type="submit">Löschen</button></form>'
           if v["autor_id"] == k["id"] or k["id"] in amt.ZUGANG_IDS else "") + '</small></div>' for v in vm) or '<p class="leer">Keine Personalvermerke.</p>'
    reiter = amt.az_akte(a["id"]) if a else "ohne Bürgerakte"
    marken = "".join(f'<span class="{"ltg" if l else ""}">{esc(b["kurz"])}{" · Leitung" if l else ""}</span>' for b, l in m["behoerden"])
    inhalt = (f'<p class="zurueck"><a href="{PFAD}">{amt.ic("arrow-left")}Mitgliederkartei</a></p>{amt.meldung(request)}'
              f'<article class="kt-blatt"><div class="kartei-logo" aria-hidden="true"><img src="{BASIS}logo/reichsbehoerden.png" alt=""></div><div class="kt-kopf">{_foto(m)}<div><p class="az" style="margin:0 0 4px">Karteikarte · {esc(reiter)}</p>'
              f'<h1>{esc(m["name"])}</h1><div class="kt-amt">{esc(m["amt"])}</div><div class="kt-marken">{marken}</div></div></div>'
              f'<div class="kt-spalten"><div><h2>Dienstverhältnis</h2>{amt.daten_tabelle(dienst)}</div>'
              f'<div><h2>Personalien</h2>{amt.daten_tabelle(pers)}<h2>Kontakt</h2>{amt.daten_tabelle(kontakt)}</div></div>'
              f'<h2>Tätigkeit</h2><div class="kt-zahlen">{"".join(f'<div class="{"" if n else "null"}"><b>{n}</b><span>{esc(t)}</span></div>' for t, n in z)}</div>'
              + (f'<h3>Letzte Aktenvorgänge</h3>{amt.verlauf_html(letzte_v, link=link)}' if letzte_v else "")
              + f'<div class="kt-spalten"><div><h2>Dokumente</h2>{dok}</div>'
              f'<div><h2>Befugnisse in Teilstaaten</h2>{amt.tabelle(["Teilstaat", "Befugnisse", "Erteilt von"], befz, "Keine Befugnisse erteilt.")}</div></div>'
              f'<h2>Personalvermerke</h2>{vermerke}'
              f'<h2>Vermerk anlegen</h2><p class="az">Nur für Kaiser und Kronkanzler sichtbar. Die Person selbst sieht ihre Karteikarte nicht.</p>'
              f'<form method="post" action="{pfad}vermerk">{amt.csrf_feld(request)}<textarea name="text" maxlength="3000" required style="width:100%;min-height:110px"></textarea>'
              f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("pencil")}Vermerk speichern</button></div></form></article>')
    return _rahmen(request, f"Karteikarte {m['name']}", inhalt)


async def _post(request):
    k = await anmeldung.konto(request)
    if not k or not darf(k):
        raise web.HTTPForbidden(text="Kein Zugang.")
    form = await request.post()
    if not secrets.compare_digest(str(form.get("csrf", "")), str(request.get("csrf", ""))):
        raise web.HTTPForbidden(text="Sitzung abgelaufen – bitte neu laden.")
    return k, form


async def vermerk(request):
    k, form = await _post(request)
    kid = request.match_info["id"]
    text = (form.get("text") or "").strip()[:3000]
    if text:
        con = request.app["db"]
        con.execute("INSERT INTO kartei_vermerke (konto_id, zeit, text, autor_id, autor_name) VALUES (?,?,?,?,?)",
                    (kid, int(time.time()), text, k["id"], k["name"]))
        con.commit()
    raise web.HTTPSeeOther(f"{PFAD}{kid}/?m=Vermerk+gespeichert")


async def vermerk_loeschen(request):
    k, _ = await _post(request)
    kid, vid = request.match_info["id"], request.match_info["vid"]
    con = request.app["db"]
    v = con.execute("SELECT * FROM kartei_vermerke WHERE id=? AND konto_id=?", (vid, kid)).fetchone()
    if v and (v["autor_id"] == k["id"] or k["id"] in amt.ZUGANG_IDS):
        con.execute("DELETE FROM kartei_vermerke WHERE id=?", (vid,))
        con.commit()
    raise web.HTTPSeeOther(f"{PFAD}{kid}/?m=Vermerk+gel%C3%B6scht")


def registrieren(app):
    app["db"].executescript(SCHEMA)
    app["db"].commit()
    amt.NAV_EXTRA.append(("Akten", nav))
    app.router.add_get(PFAD, liste)
    app.router.add_get(PFAD + "{id:\\d+}/", karte)
    app.router.add_post(PFAD + "{id:\\d+}/vermerk", vermerk)
    app.router.add_post(PFAD + "{id:\\d+}/vermerk/{vid:\\d+}/loeschen", vermerk_loeschen)
