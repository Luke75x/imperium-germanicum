"""Etatverteilung: Reich und Teilstaaten bestimmen, wie ihr Ausgabenbudget auf elf Politikfelder verteilt wird (/schatzamt/etatverteilung/).

Etat (Steueraufkommen im Monat) eines Teilstaats = Abgabe an das Reich (nicht beeinflussbar, Reichsabgabe nach Bevölkerung, Einkommen und Fläche)
+ Landesanteil. Vom Landesanteil gehen „ausgabenquote“ % (Vorgabe 97 %) als Ausgabenbudget in die Politikfelder, der Rest ist die Rücklage der
Staatskasse. Das Ausgabenbudget verteilt der Teilstaat selbst in Prozent auf die Kategorien (Summe 100 %). Das Reich verteilt sein Ausgabenbudget
(Reichsanteil aller Steuern einschließlich der Freien Reichsgebiete) genauso.
Wirkung: Der Anteil „Verteidigung“ ist echtes Geld – er fließt jeden Monat in die Verteidigungskasse (Teilstaat) bzw. Reichsverteidigungskasse
(aufkommen.berechnen, verteidigung.py). Die übrigen Kategorien sind simulierte Ausgaben der Bevölkerung (Gegenkonto „Volkswirtschaft“); sie werden je
Haushaltsmonat in ep_verteilung festgehalten.
Vorgabe, solange nichts gespeichert ist: Verteidigung aus der alten Regel (Einstellung „verteidigung“: Anteil am BIP), der Rest nach VORGABE_GEWICHT.
Änderungen gelten ab dem nächsten gebuchten Monat. Rechte: Teilstaat – Landesherr (geld.regierte_staatskassen, nicht unter Zwangsverwaltung),
Reich – Schatzamt-Leitung, Kanzler, Kaiser; ansehen darf jeder mit staatlichem Zugriff. Tabellen: ep_plaene, ep_log, ep_verteilung.
"""
import json
import time

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark

esc = amt.esc
PFAD = sa.PFAD + "etatverteilung/"

KATEGORIEN = [("innere_sicherheit", "Innere Sicherheit"), ("forschung", "Forschung"), ("gesundheit", "Gesundheitswesen"), ("industrie", "Industrie"),
              ("kultur", "Kultur"), ("verteidigung", "Verteidigung"), ("soziales", "Arbeit und Soziales"), ("umwelt", "Umwelt"),
              ("transport", "Transportwesen"), ("bildung", "Bildung"), ("landwirtschaft", "Landwirtschaft")]
NAMEN = dict(KATEGORIEN)
# Vorgabe für alle Kategorien außer Verteidigung (Richtwerte eines Staatshaushalts), Summe 100
VORGABE_GEWICHT = {"soziales": 41, "gesundheit": 14, "bildung": 12, "transport": 8, "innere_sicherheit": 5, "forschung": 5, "industrie": 5,
                   "umwelt": 4, "kultur": 3, "landwirtschaft": 3}

amt.ICONS.setdefault("chart-pie", '<path d="M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055-.998.398-.998.95v8a1 1 0 0 0 1 1z"/>'
                                  '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>')

SCHEMA = """
CREATE TABLE IF NOT EXISTS ep_plaene (schl TEXT NOT NULL, kategorie TEXT NOT NULL, anteil REAL NOT NULL, PRIMARY KEY (schl, kategorie));
CREATE TABLE IF NOT EXISTS ep_log (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, schl TEXT NOT NULL, autor_id TEXT NOT NULL DEFAULT '',
    autor_name TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ep_verteilung (lauf INTEGER NOT NULL, schl TEXT NOT NULL, kategorie TEXT NOT NULL, betrag INTEGER NOT NULL,
    PRIMARY KEY (lauf, schl, kategorie));
"""


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- Verteilung

def vorgabe(verteidigung_prozent):
    """Vorgabe-Verteilung in Prozent: gegebener Verteidigungsanteil, der Rest nach VORGABE_GEWICHT."""
    v = max(0.0, min(100.0, float(verteidigung_prozent)))
    rest = 100.0 - v
    out = {k: VORGABE_GEWICHT[k] * rest / 100.0 for k, _ in KATEGORIEN if k != "verteidigung"}
    out["verteidigung"] = v
    return {k: out[k] for k, _ in KATEGORIEN}


def runden100(anteile):
    """Prozentwerte auf eine Nachkommastelle runden, sodass sie genau 100,0 ergeben (Rest bei der größten Nicht-Verteidigungs-Kategorie)."""
    out = {k: round(float(v), 1) for k, v in anteile.items()}
    rest = round(100.0 - sum(out.values()), 1)
    if rest:
        ziel = max((k for k in out if k != "verteidigung"), key=lambda k: out[k])
        out[ziel] = round(out[ziel] + rest, 1)
    return out


def angepasst(con, schl):
    return bool(con.execute("SELECT 1 FROM ep_plaene WHERE schl=?", (schl,)).fetchone())


def plan(con, schl, vorgabe_verteidigung=0.0):
    """Verteilung (Kategorie → Prozent des Ausgabenbudgets) für 'reich' oder 'ts-<sid>'; gespeichert oder Vorgabe."""
    rows = {r["kategorie"]: float(r["anteil"]) for r in con.execute("SELECT kategorie, anteil FROM ep_plaene WHERE schl=?", (schl,))}
    if len(rows) == len(KATEGORIEN):
        return {k: rows[k] for k, _ in KATEGORIEN}
    return vorgabe(vorgabe_verteidigung)


def verteilung(pool, anteile):
    """Beträge (Heller) je Kategorie aus Ausgabenbudget und Prozenten; Summe = pool (Rundungsrest bei der größten Nicht-Verteidigungs-Kategorie)."""
    out = {k: int(round(pool * float(anteile.get(k, 0)) / 100.0)) for k, _ in KATEGORIEN}
    rest = pool - sum(out.values())
    if rest and pool:
        ziel = max((k for k, _ in KATEGORIEN if k != "verteidigung"), key=lambda k: out[k])
        out[ziel] += rest
    return out


def aktuelle(con, schl, liste):
    """Aktuell geltende Verteilung in Prozent (gespeichert oder Vorgabe, wie sie berechnet wird); liste = aufkommen.berechnen()."""
    if angepasst(con, schl):
        return plan(con, schl, 0.0)
    if schl == "reich":
        pool = sum(x["pool_reich"] for x in liste)
        return {kat: (sum(x["verteilung_reich"].get(kat, 0) for x in liste) / pool * 100 if pool else 0) for kat, _ in KATEGORIEN}
    x = next((x for x in liste if "ts-" + x["staat"] == schl), None)
    return {kat: (x["verteilung_land"].get(kat, 0) / x["pool_land"] * 100 if x and x["pool_land"] else 0) for kat, _ in KATEGORIEN}


def speichern(con, schl, werte, k, alt=None):
    """Speichert eine Verteilung (Prozent je Kategorie, Summe 100) und protokolliert die Änderung."""
    alt = alt or plan(con, schl, 0.0)
    con.execute("DELETE FROM ep_plaene WHERE schl=?", (schl,))
    for kat, _ in KATEGORIEN:
        con.execute("INSERT INTO ep_plaene (schl, kategorie, anteil) VALUES (?,?,?)", (schl, kat, round(float(werte[kat]), 2)))
    aend = [f'{NAMEN[kat]} {alt[kat]:.1f} % → {float(werte[kat]):.1f} %'.replace(".", ",") for kat, _ in KATEGORIEN if abs(alt[kat] - float(werte[kat])) >= 0.05]
    _log(con, schl, k, "Verteilung geändert: " + ("; ".join(aend) if aend else "unverändert"))


def zuruecksetzen(con, schl, k):
    con.execute("DELETE FROM ep_plaene WHERE schl=?", (schl,))
    _log(con, schl, k, "Verteilung auf die Vorgabe zurückgesetzt")


def _log(con, schl, k, text):
    con.execute("INSERT INTO ep_log (zeit, schl, autor_id, autor_name, text) VALUES (?,?,?,?,?)",
                (int(time.time()), schl, k["id"] if k else "", k["name"] if k else "System", text[:600]))
    geld.protokoll(con, k, "Etatverteilung", f'{schl}: {text}'[:600])


def verteilung_speichern(con, lauf, x):
    """Hält die Verteilung eines Haushaltsmonats fest (aus aufkommen.berechnen: verteilung_reich/verteilung_land je Posten)."""
    for schl, ver in (("reich", x.get("verteilung_reich")), ("ts-" + x["staat"], x.get("verteilung_land"))):
        for kat, betrag in (ver or {}).items():
            con.execute("INSERT OR REPLACE INTO ep_verteilung (lauf, schl, kategorie, betrag) VALUES (?,?,?,?)", (lauf, schl, kat, int(betrag)))


# ---------------------------------------------------------------- Rechte

def darf_aendern(con, k, schl):
    if not k or not k["mitglied"]:
        return False
    if schl == "reich":
        return geld.ist_leitung(k)
    return any(r["stelle"] == schl for r in geld.regierte_staatskassen(con, k))


def ziele(con, liste):
    """[(schl, Name)]: Reich und alle Teilstaaten (ohne Freie Reichsgebiete)."""
    return [("reich", "Reich")] + [("ts-" + x["staat"], x["name"]) for x in sorted(liste, key=lambda x: x["name"]) if not x["reichsgebiet"]]


# ---------------------------------------------------------------- Seite

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]   # validierte Kategorienfolge (Slots 1–8)
CSS = """<style>
.ep-raster{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:28px;align-items:start;margin:14px 0}
@media (max-width:900px){.ep-raster{grid-template-columns:1fr}}
.ep-torte{position:relative;max-width:380px;margin:0 auto;width:100%}
.ep-torte svg{width:100%;height:auto;display:block;overflow:visible}
.ep-torte path{stroke:#fff;stroke-width:2;transition:opacity .15s,transform .15s;cursor:pointer;outline:0}
.ep-torte path:focus-visible{stroke:var(--ink);stroke-width:3}
.ep-torte.hat-fokus path:not(.fokus){opacity:.35}
.ep-tipp{position:absolute;pointer-events:none;background:var(--ink);color:#fff;border-radius:8px;padding:7px 10px;font-size:13px;line-height:1.35;
 white-space:nowrap;z-index:5;opacity:0;transition:opacity .1s;transform:translate(-50%,-110%)}
.ep-tipp.an{opacity:1}
.ep-tab{width:100%;border-collapse:collapse;font-size:14px}
.ep-tab th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--grau);font-weight:600;text-align:left;padding:6px 8px;border-bottom:1px solid var(--linie)}
.ep-tab td{padding:6px 8px;border-bottom:1px solid #eef0f2;vertical-align:middle}
.ep-tab td:first-child{white-space:nowrap}
.ep-tab tr.fokus td{background:var(--hell)}
.ep-tab td.num,.ep-tab th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ep-farbe{display:inline-block;width:14px;height:14px;border-radius:4px;vertical-align:-2px;margin-right:8px}
.ep-farbe.schraffur{background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.75) 0 2px,transparent 2px 5px)}
.ep-fest td{color:var(--grau)}
.ep-tab input[type=number]{width:84px;text-align:right;padding:4px 6px}
.ep-tab input[type=range]{width:120px;vertical-align:middle;accent-color:var(--ink)}
.ep-summe{display:flex;gap:10px;align-items:center;margin:10px 0;font-weight:600}
.ep-summe.falsch{color:var(--rot)}.ep-summe.richtig{color:var(--ok)}
.ep-hinweis{margin:8px 0}
.ep-vergleich td,.ep-vergleich th{font-size:12.5px;padding:5px 6px;text-align:right;white-space:nowrap}
.ep-vergleich td:first-child,.ep-vergleich th:first-child{text-align:left}
.ep-scroll{overflow-x:auto}
@media (max-width:800px){
 .ep-raster>div{min-width:0}
 .ep-torte{max-width:300px}
 .ep-tab input[type=range]{display:none}
 .ep-tab th:nth-child(3),.ep-tab td:nth-child(3){display:none}
 .ep-tab td:first-child{white-space:normal}
 .ep-tab input[type=number]{width:70px}
 .ep-tab th,.ep-tab td{padding:6px 4px}
 .ep-tab th.num{white-space:normal;font-size:10.5px}
}
</style>"""

JS = r"""
(function(){
var D=JSON.parse(document.getElementById("ep-daten").textContent);
var farben=D.farben, svgNS="http://www.w3.org/2000/svg";
var torte=document.getElementById("ep-torte"), svg=torte.querySelector("svg"), tipp=document.getElementById("ep-tipp");
function de(h){return (h/100).toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})+" Kr"}
function kurz(h){var k=h/100,a=Math.abs(k);
 if(a>=1e12)return (k/1e12).toLocaleString("de-DE",{maximumFractionDigits:2})+" Bio. Kr";
 if(a>=1e9)return (k/1e9).toLocaleString("de-DE",{maximumFractionDigits:2})+" Mrd. Kr";
 if(a>=1e6)return (k/1e6).toLocaleString("de-DE",{maximumFractionDigits:2})+" Mio. Kr";
 return de(h)}
function pz(x){return x.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})+" %"}
var felder=[].slice.call(document.querySelectorAll("input[type=number][data-kat]"));
var regler=[].slice.call(document.querySelectorAll("input[type=range][data-kat]"));
function scheiben(){
 var s=[];
 D.fest_vorn.forEach(function(f){s.push(f)});
 D.kategorien.forEach(function(k,i){
  var f=felder.filter(function(e){return e.dataset.kat===k.id})[0];
  var p=f?(parseFloat(String(f.value).replace(",","."))||0):k.anteil;
  s.push({id:k.id,name:k.name,betrag:Math.round(D.pool*p/100),farbe:k.farbe,schraffur:k.schraffur,anteil:p});
 });
 D.fest_hinten.forEach(function(f){s.push(f)});
 return s}
function pfad(a0,a1,r){var x0=100+r*Math.sin(a0),y0=100-r*Math.cos(a0),x1=100+r*Math.sin(a1),y1=100-r*Math.cos(a1),gross=(a1-a0)>Math.PI?1:0;
 return "M100,100 L"+x0+","+y0+" A"+r+","+r+" 0 "+gross+" 1 "+x1+","+y1+" Z"}
function zeichnen(){
 var s=scheiben(), gesamt=D.gesamt||1, w=0;
 while(svg.firstChild)svg.removeChild(svg.firstChild);
 var defs=document.createElementNS(svgNS,"defs");
 s.forEach(function(x,i){if(x.schraffur){var p=document.createElementNS(svgNS,"pattern");p.setAttribute("id","hs"+i);p.setAttribute("width","7");p.setAttribute("height","7");
  p.setAttribute("patternUnits","userSpaceOnUse");p.setAttribute("patternTransform","rotate(45)");
  var r=document.createElementNS(svgNS,"rect");r.setAttribute("width","7");r.setAttribute("height","7");r.setAttribute("fill",x.farbe);p.appendChild(r);
  var l=document.createElementNS(svgNS,"rect");l.setAttribute("width","2.6");l.setAttribute("height","7");l.setAttribute("fill","#fff");l.setAttribute("opacity",".75");p.appendChild(l);defs.appendChild(p)}});
 svg.appendChild(defs);
 var ges=s.reduce(function(a,x){return a+x.betrag},0)||1;
 s.forEach(function(x,i){
  var a0=w/ges*2*Math.PI;w+=x.betrag;var a1=w/ges*2*Math.PI;
  if(x.betrag<=0)return;
  var el=document.createElementNS(svgNS,"path");
  if(a1-a0>=2*Math.PI-1e-6){el=document.createElementNS(svgNS,"circle");el.setAttribute("cx","100");el.setAttribute("cy","100");el.setAttribute("r","96");
   el.setAttribute("style","stroke:#fff;stroke-width:2;cursor:pointer")}
  else el.setAttribute("d",pfad(a0,a1,96));
  el.setAttribute("fill",x.schraffur?"url(#hs"+i+")":x.farbe);
  el.setAttribute("tabindex","0");el.dataset.id=x.id;
  el.setAttribute("aria-label",x.name+": "+pz(x.betrag/gesamt*100)+" des Etats, "+de(x.betrag));
  el.addEventListener("mousemove",function(e){zeigen(x,e)});el.addEventListener("mouseleave",weg);
  el.addEventListener("focus",function(){fokus(x.id,true);var b=el.getBBox();zeigenAn(x,b.x+b.width/2,b.y+b.height/2)});el.addEventListener("blur",weg);
  svg.appendChild(el)});
 s.forEach(function(x){var z=document.querySelector('[data-zeile="'+x.id+'"]');if(!z)return;
  var b=z.querySelector(".ep-betrag"),a=z.querySelector(".ep-anteil-gesamt");if(b)b.textContent=kurz(x.betrag);b&&b.setAttribute("title",de(x.betrag));
  if(a)a.textContent=pz(x.betrag/gesamt*100)});
 summe()}
function zeigen(x,e){var r=torte.getBoundingClientRect();zeigenAn(x,(e.clientX-r.left)/r.width*200,(e.clientY-r.top)/r.height*200);fokus(x.id,true)}
function zeigenAn(x,px,py){var gesamt=D.gesamt||1;tipp.innerHTML="<b>"+x.name+"</b><br>"+pz(x.betrag/gesamt*100)+" des Etats · "+de(x.betrag);
 tipp.style.left=(px/200*100)+"%";tipp.style.top=(py/200*100)+"%";tipp.classList.add("an")}
function weg(){tipp.classList.remove("an");fokus(null,false)}
function fokus(id,an){torte.classList.toggle("hat-fokus",!!an);[].forEach.call(svg.querySelectorAll("[data-id]"),function(p){p.classList.toggle("fokus",an&&p.dataset.id===id)});
 [].forEach.call(document.querySelectorAll("[data-zeile]"),function(z){z.classList.toggle("fokus",an&&z.dataset.zeile===id)})}
function summe(){var o=document.getElementById("ep-summe");if(!o||!felder.length)return;
 var s=felder.reduce(function(a,f){return a+(parseFloat(String(f.value).replace(",","."))||0)},0), rest=Math.round((100-s)*10)/10;
 var ok=Math.abs(100-s)<=0.05;o.className="ep-summe "+(ok?"richtig":"falsch");
 o.querySelector("span").textContent=ok?"Summe 100 % – bereit zum Speichern":"Summe "+pz(s)+(rest>0?" – es fehlen "+pz(rest):" – "+pz(-rest)+" zu viel");
 var b=document.getElementById("ep-speichern");if(b)b.disabled=!ok;
 var m=document.getElementById("ep-min");if(m){var v=felder.filter(function(f){return f.dataset.kat==="verteidigung"})[0];
  var pv=v?(parseFloat(String(v.value).replace(",","."))||0):0, bet=D.pool*pv/100;m.style.display=bet<D.vt_min?"block":"none"}}
felder.forEach(function(f){f.addEventListener("input",function(){
 var g=document.getElementById("ep-r-"+f.dataset.kat);if(g)g.value=parseFloat(String(f.value).replace(",","."))||0;zeichnen()})});
regler.forEach(function(r){r.addEventListener("input",function(){var n=document.getElementById("ep-n-"+r.dataset.kat);if(n)n.value=r.value;zeichnen()})});
[].forEach.call(document.querySelectorAll("[data-zeile]"),function(z){
 z.addEventListener("mouseenter",function(){fokus(z.dataset.zeile,true)});z.addEventListener("mouseleave",function(){fokus(null,false)})});
var norm=document.getElementById("ep-normieren");
if(norm)norm.addEventListener("click",function(){var n=felder,s=n.reduce(function(a,f){return a+(parseFloat(String(f.value).replace(",","."))||0)},0);
 if(!s)return;var neu=n.map(function(f){return Math.round((parseFloat(String(f.value).replace(",","."))||0)/s*1000)/10}),d=Math.round((100-neu.reduce(function(a,b){return a+b},0))*10)/10;
 var gr=0;neu.forEach(function(v,i){if(v>neu[gr])gr=i});neu[gr]=Math.round((neu[gr]+d)*10)/10;
 n.forEach(function(f,i){f.value=neu[i];var r=document.getElementById("ep-r-"+f.dataset.kat);if(r)r.value=neu[i]});zeichnen()});
zeichnen()})();
"""


def _de(x, stellen=1):
    return f"{x:.{stellen}f}".replace(".", ",")


@sa.seite("staat")
async def seite(request, k):
    import aufkommen
    import verteidigung
    con = request.app["db"]
    liste = aufkommen.berechnen(con)
    ziel_liste = ziele(con, liste)
    gueltig = {s for s, _ in ziel_liste}
    eigene = [r["stelle"] for r in geld.regierte_staatskassen(con, k)]
    ziel = request.query.get("ziel", "")
    if ziel not in gueltig:
        ziel = next((s for s in eigene if s in gueltig), "reich")
    name = dict(ziel_liste)[ziel]
    pk = await verteidigung.personalkosten(request.app, con)
    if ziel == "reich":
        gesamt = sum(x["reich"] for x in liste)
        pool = sum(x["pool_reich"] for x in liste)
        ruecklage = gesamt - pool
        betraege = {kat: sum(x["verteilung_reich"].get(kat, 0) for x in liste) for kat, _ in KATEGORIEN}
        fest_vorn = []
        vt_stelle = "verteidigung"
        vt_ih = 0
    else:
        x = next(x for x in liste if "ts-" + x["staat"] == ziel)
        gesamt, pool, ruecklage = x["summe"], x["pool_land"], x["land"] - x["pool_land"]
        betraege = x["verteilung_land"]
        fest_vorn = [{"id": "abgabe", "name": "Abgabe an das Reich", "betrag": x["reich"], "farbe": "#3a3a3a", "schraffur": False}]
        vt_stelle = "vt-" + x["staat"]
        vt_ih = verteidigung.kennzahlen(con, vt_stelle)["instandhaltung"]
    anteile = aktuelle(con, ziel, liste)
    anteile = runden100(anteile)
    darf = darf_aendern(con, k, ziel)
    n_pers, kosten = (pk or {}).get(vt_stelle, (0, 0))
    vt_min = kosten + vt_ih if pk is not None else 0
    kat_daten = [{"id": kat, "name": NAMEN[kat], "anteil": anteile[kat], "farbe": PALETTE[i % len(PALETTE)], "schraffur": i >= len(PALETTE)}
                 for i, (kat, _) in enumerate(KATEGORIEN)]
    fest_hinten = [{"id": "ruecklage", "name": "Rücklage der Staatskasse" if ziel != "reich" else "Rücklage der Reichskasse",
                    "betrag": ruecklage, "farbe": "#c4c6cb", "schraffur": False}]
    daten = {"gesamt": gesamt, "pool": pool, "vt_min": vt_min, "kategorien": kat_daten, "fest_vorn": fest_vorn, "fest_hinten": fest_hinten, "farben": PALETTE}
    c = amt.csrf_feld(request)
    zeilen = []
    for f in fest_vorn:
        zeilen.append(f'<tr class="ep-fest" data-zeile="{f["id"]}"><td><span class="ep-farbe" style="background:{f["farbe"]}"></span>{esc(f["name"])}</td>'
                      f'<td class="num">–</td><td class="num ep-anteil-gesamt">{_de(f["betrag"] / gesamt * 100 if gesamt else 0)} %</td>'
                      f'<td class="num"><span title="{mark(f["betrag"])}">{geld.mark_kurz(f["betrag"])}</span></td></tr>')
    for i, kd in enumerate(kat_daten):
        kat = kd["id"]
        farbe = f'<span class="ep-farbe{" schraffur" if kd["schraffur"] else ""}" style="background-color:{kd["farbe"]}"></span>'
        wert = f'{anteile[kat]:.1f}'
        if darf:
            anteil_zelle = (f'<input type="range" id="ep-r-{kat}" data-kat="{kat}" min="0" max="100" step="0.1" value="{wert}" aria-label="{esc(NAMEN[kat])} Regler"> '
                            f'<input type="number" id="ep-n-{kat}" name="k_{kat}" data-kat="{kat}" min="0" max="100" step="0.1" value="{wert}" aria-label="{esc(NAMEN[kat])} in Prozent"> %')
        else:
            anteil_zelle = f'{_de(anteile[kat])} %'
        zeilen.append(f'<tr data-zeile="{kat}"><td>{farbe}{esc(NAMEN[kat])}</td><td class="num">{anteil_zelle}</td>'
                      f'<td class="num ep-anteil-gesamt">{_de(betraege[kat] / gesamt * 100 if gesamt else 0)} %</td>'
                      f'<td class="num"><span class="ep-betrag" title="{mark(betraege[kat])}">{geld.mark_kurz(betraege[kat])}</span></td></tr>')
    for f in fest_hinten:
        zeilen.append(f'<tr class="ep-fest" data-zeile="{f["id"]}"><td><span class="ep-farbe" style="background:{f["farbe"]}"></span>{esc(f["name"])}</td>'
                      f'<td class="num">–</td><td class="num ep-anteil-gesamt">{_de(f["betrag"] / gesamt * 100 if gesamt else 0)} %</td>'
                      f'<td class="num"><span title="{mark(f["betrag"])}">{geld.mark_kurz(f["betrag"])}</span></td></tr>')
    tabelle = ('<table class="ep-tab"><thead><tr><th>Kategorie</th><th class="num">Anteil am Ausgabenbudget</th><th class="num">Anteil am Etat</th>'
               f'<th class="num">Betrag / Monat</th></tr></thead><tbody>{"".join(zeilen)}</tbody></table>')
    if darf:
        form_in = (f'<form method="post" action="{PFAD}speichern" id="ep-form">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">{tabelle}'
                   '<div class="ep-summe" id="ep-summe"><span></span></div>'
                   f'<div class="warnung ep-hinweis" id="ep-min" style="display:none">{amt.ic("triangle-alert")} Dieser Verteidigungsanteil deckt nicht einmal die Gehälter und die '
                   f'Instandhaltung des Militärs ({mark(vt_min)} im Monat). Die Gehälter werden dann einbehalten, die Einsatzbereitschaft sinkt.</div>'
                   f'<div class="aktionen"><button class="btn" type="submit" id="ep-speichern">{amt.ic("check")}Verteilung speichern</button>'
                   f'<button class="btn zweit" type="button" id="ep-normieren">Auf 100 % bringen</button></div></form>'
                   + (f'<form method="post" action="{PFAD}zuruecksetzen" onsubmit="return confirm(\'Auf die Vorgabe zurücksetzen?\')">{c}<input type="hidden" name="ziel" value="{esc(ziel)}">'
                      f'<div class="aktionen"><button class="btn zweit" type="submit">Auf Vorgabe zurücksetzen</button></div></form>' if angepasst(con, ziel) else ""))
        rechte = '<p class="sa-hinweis">Sie dürfen die Verteilung dieses Haushalts ändern. Änderungen gelten ab dem nächsten gebuchten Monat.</p>'
    else:
        form_in = tabelle
        rechte = ('<p class="sa-hinweis">Nur Ansicht – ändern darf die Verteilung ' + ("das Reich (Kanzler, Kaiser, Schatzamt-Leitung)." if ziel == "reich" else
                  "der Landesherr dieses Teilstaats.") + '</p>')
    gewaehlt = "".join(f'<option value="{esc(s)}"{" selected" if s == ziel else ""}>{esc(n)}{" (Ihr Teilstaat)" if s in eigene else ""}</option>' for s, n in ziel_liste)
    erkl = ('<div class="sa-erkl"><b>Wie ist der Etat aufgebaut?</b><ol>'
            + ('<li>Der Etat des Reiches ist sein Anteil an allen Steuern: die <b>Abgaben der Teilstaaten</b> und das gesamte Aufkommen der Freien Reichsgebiete.</li>'
               if ziel == "reich" else
               '<li>Der Etat ist das Steueraufkommen des Teilstaats im Monat. Ein Teil davon ist die <b>Abgabe an das Reich</b>; sie richtet sich nach Bevölkerung, '
               'Einkommen und Fläche und lässt sich <b>nicht beeinflussen</b>.</li>')
            + '<li>Vom eigenen Anteil bleibt eine <b>Rücklage</b> in der Kasse (freie Mittel, nicht änderbar); der große Rest ist das <b>Ausgabenbudget</b>.</li>'
            '<li>Das Ausgabenbudget verteilt ' + ("das Reich" if ziel == "reich" else "der Teilstaat") + ' in Prozent auf die elf Kategorien. '
            '<b>Verteidigung ist echtes Geld</b>: dieser Anteil fließt jeden Monat in die '
            + ("Reichsverteidigungskasse (Führungsstab)" if ziel == "reich" else "Verteidigungskasse (Gehälter des Militärs, Instandhaltung und Kauf von Gerät)")
            + '. Die übrigen Kategorien sind Ausgaben für die Bevölkerung.</li></ol></div>')
    kz = [("Etat im Monat", mark(gesamt)), ("Ausgabenbudget", mark(pool)), ("Rücklage", mark(ruecklage)),
          ("Verteidigung", mark(betraege["verteidigung"]))]
    # Vergleich aller Haushalte
    kopf = "".join(f'<th title="{esc(NAMEN[kat])}">{esc(NAMEN[kat][:11])}</th>' for kat, _ in KATEGORIEN)
    vz = []
    for s, n in ziel_liste:
        if s == "reich":
            ver = {kat: sum(x["verteilung_reich"].get(kat, 0) for x in liste) for kat, _ in KATEGORIEN}
            pl = sum(x["pool_reich"] for x in liste)
        else:
            x2 = next(x for x in liste if "ts-" + x["staat"] == s)
            ver, pl = x2["verteilung_land"], x2["pool_land"]
        vz.append(f'<tr><td><a href="{PFAD}?ziel={esc(s)}">{esc(n)}</a></td>' + "".join(f'<td>{_de(ver[kat] / pl * 100 if pl else 0)}</td>' for kat, _ in KATEGORIEN) + '</tr>')
    verlauf = con.execute("SELECT * FROM ep_log WHERE schl=? ORDER BY id DESC LIMIT 15", (ziel,)).fetchall()
    inhalt = (CSS + f'<h1>{amt.ic("chart-pie")} Etatverteilung · {esc(name)}</h1>{amt.meldung(request)}'
              '<p class="az">Wie viel vom Ausgabenbudget fließt in welches Politikfeld? Das Tortendiagramm zeigt den gesamten Monatsetat.</p>'
              f'<form class="sa-leiste" method="get"><div><label for="zl">Haushalt</label><select id="zl" name="ziel" onchange="this.form.submit()">{gewaehlt}</select></div>'
              f'<noscript><button class="btn zweit" type="submit">Anzeigen</button></noscript></form>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              + rechte + erkl
              + f'<div class="ep-raster"><div class="ep-torte" id="ep-torte"><svg viewBox="0 0 200 200" role="img" aria-label="Tortendiagramm des Etats {esc(name)}"></svg>'
                '<div class="ep-tipp" id="ep-tipp"></div></div><div>' + form_in + '</div></div>'
              + f'<script type="application/json" id="ep-daten">{json.dumps(daten, ensure_ascii=False).replace("</", "<\\/")}</script><script>{JS}</script>'
              + f'<details class="sa-auf"><summary>{amt.ic("chart-column")}Vergleich aller Haushalte (Anteile am Ausgabenbudget in %)</summary><div class="ep-scroll">'
                f'<table class="liste ep-vergleich"><thead><tr><th>Haushalt</th>{kopf}</tr></thead><tbody>{"".join(vz)}</tbody></table></div></details>'
              + f'<details class="sa-auf"><summary>{amt.ic("clock")}Änderungen ({len(verlauf)})</summary>'
              + amt.tabelle(["Zeit", "Durch", "Änderung"], [(amt._zeit(v["zeit"]), esc(v["autor_name"]), esc(v["text"])) for v in verlauf], "Noch keine Änderungen.") + '</details>')
    return sa.ant(request, k, "Etatverteilung", "sa-etatverteilung", inhalt)


def _lesen(form):
    werte = {}
    for kat, _ in KATEGORIEN:
        roh = str(form.get("k_" + kat, "")).replace(",", ".").strip()
        try:
            v = float(roh)
        except ValueError:
            return None
        if not 0 <= v <= 100:
            return None
        werte[kat] = v
    return werte if abs(sum(werte.values()) - 100.0) <= 0.05 else None


async def speichern_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    ziel = str(form.get("ziel", ""))
    if not (ziel == "reich" or ziel.startswith("ts-")) or not darf_aendern(con, k, ziel):
        raise web.HTTPForbidden(text="Die Verteilung dieses Haushalts dürfen Sie nicht ändern.")
    werte = _lesen(form)
    if werte is None:
        sa.weiter(f"{PFAD}?ziel={ziel}", "Bitte für alle elf Kategorien Prozentwerte angeben, die zusammen 100 % ergeben.", True)
    import aufkommen
    speichern(con, ziel, werte, k, alt=runden100(aktuelle(con, ziel, aufkommen.berechnen(con))))
    con.commit()
    sa.weiter(f"{PFAD}?ziel={ziel}", "Verteilung gespeichert; sie gilt ab dem nächsten gebuchten Monat.")


async def zuruecksetzen_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    ziel = str(form.get("ziel", ""))
    if not (ziel == "reich" or ziel.startswith("ts-")) or not darf_aendern(con, k, ziel):
        raise web.HTTPForbidden(text="Die Verteilung dieses Haushalts dürfen Sie nicht ändern.")
    zuruecksetzen(con, ziel, k)
    con.commit()
    sa.weiter(f"{PFAD}?ziel={ziel}", "Auf die Vorgabe zurückgesetzt.")


def registrieren(app):
    einrichten(app["db"])
    app.router.add_get(PFAD, seite)
    app.router.add_post(PFAD + "speichern", speichern_post)
    app.router.add_post(PFAD + "zuruecksetzen", zuruecksetzen_post)
