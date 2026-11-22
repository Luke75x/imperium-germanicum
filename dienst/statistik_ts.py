"""Statistiken je Teilstaat (/schatzamt/statistiken/?staat=ts-<id>).

Öffentlich für alle angemeldeten Mitglieder wie die übrige Statistikseite (etatplan.statistiken): keine Salden einzelner Kassen.
Oben eine Wappenleiste („Alle Haushalte“ = der bisherige Vergleich, danach jeder Teilstaat). Für den gewählten Teilstaat:
Kennzahlen, Rang unter den Teilstaaten (Punktdiagramm), Etatverteilung (mit Schnitt aller Teilstaaten), Zufriedenheit je Politikfeld,
Entwicklung (Indikatoren, vorher → jetzt), Energie (Mix als gestapelter Balken, Bedarf und Angebot), Produktion, Steuern und Reichsabgabe,
Verläufe (Linien; wachsen mit jedem gebuchten Monat). Diagramme als Inline-SVG ohne Fremdbibliothek, Hover über <title>/Tooltip, jedes mit Tabellenansicht.
Farben: Werte des gewählten Teilstaats in --akzent, Vergleich grau, Kategorien (Energiemix) in etatplan.PALETTE (validierte Reihenfolge).
"""
import amt
import geld
import schatzamt as sa

esc = amt.esc
PFAD = sa.PFAD + "statistiken/"
NIEDRIG_GUT = {"engpass", "co2", "ueberwachung"}   # bei diesen Indikatoren ist weniger besser
ENERGIE_NAMEN = {"kohle": "Kohle", "gas": "Gas", "oel": "Öl", "kern": "Kernkraft", "wind": "Wind", "solar": "Solar", "wasser": "Wasserkraft", "biomasse": "Biomasse"}

CSS = """<style>
.st-leiste{display:flex;gap:6px;overflow-x:auto;scrollbar-width:thin;padding:4px 2px 10px;margin:8px 0 14px;scroll-snap-type:x proximity}
.st-leiste a{flex:none;display:flex;flex-direction:column;align-items:center;gap:4px;width:84px;padding:8px 4px;border:1px solid transparent;border-radius:16px;color:var(--grau);
 text-decoration:none;font-size:11.5px;line-height:1.2;text-align:center;scroll-snap-align:start}
.st-leiste a:hover{background:rgba(255,255,255,.6);color:var(--ink)}
.st-leiste a.aktiv{border-color:rgba(255,255,255,.75);color:var(--ink);font-weight:600;background:#fff;box-shadow:0 2px 10px rgba(16,24,40,.1)}
.st-leiste img,.st-leiste .icon{height:34px;width:30px;object-fit:contain}
.st-raster{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:16px;margin:12px 0}
.st-karte{border:1px solid var(--linie);border-radius:20px;background:#fff;padding:16px 18px 14px;min-width:0}
.st-karte h3{margin:0 0 2px;font-size:15.5px;display:flex;align-items:center;gap:8px}
.st-karte h3 .icon{width:18px;height:18px;color:var(--grau)}
.st-karte>p{margin:0 0 10px;font-size:13px;color:var(--grau)}
.st-karte.breit{grid-column:1/-1}
.st-svg{display:block;width:100%;height:auto;overflow:visible;font:12px var(--schrift)}
.st-svg text{fill:var(--ink)}
.st-svg .leise{fill:var(--grau)}
.st-svg .gitter{stroke:#e6e8eb;stroke-width:1}
.st-svg .spur{fill:#eef0f3}
.st-svg .wert{fill:var(--akzent)}
.st-svg .wert.schlecht{fill:#8c929b}
.st-svg .ref{stroke:var(--ink);stroke-width:2}
.st-svg .punkt{fill:#c3c8cf}
.st-svg .punkt.du{fill:var(--akzent);stroke:#fff;stroke-width:2}
.st-svg .linie{fill:none;stroke:var(--akzent);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.st-svg .flaeche{fill:var(--akzent);opacity:.1}
.st-svg [data-tipp]{cursor:default}
.st-svg [data-tipp]:hover{opacity:.82}
.st-legende{display:flex;flex-wrap:wrap;gap:6px 14px;margin:8px 0 0;font-size:12.5px;color:var(--grau)}
.st-legende i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.st-tab{margin-top:6px}
.st-tab summary{cursor:pointer;font-size:12.5px;color:var(--grau);list-style:none}
.st-tab summary::-webkit-details-marker{display:none}
.st-tab summary::before{content:"▸ "}
.st-tab[open] summary::before{content:"▾ "}
.st-tab table{font-size:13px}
.st-leer{font-size:13px;color:var(--grau);padding:18px 0;text-align:center;border:1px dashed var(--linie);border-radius:12px}
.st-k{display:none}
@media (max-width:800px){.st-g{display:none}.st-k{display:block}}
.st-tipp{position:fixed;z-index:60;pointer-events:none;background:rgba(22,23,26,.92);color:#fff;font-size:12.5px;line-height:1.35;padding:6px 10px;border-radius:10px;
 max-width:260px;opacity:0;transition:opacity .12s;box-shadow:0 6px 20px rgba(0,0,0,.2)}
.st-tipp.an{opacity:1}
</style>"""

# Tooltip für alle Diagrammelemente mit data-tipp (Maus und Tastatur)
JS = """<div class="st-tipp" id="st-tipp" role="tooltip"></div><script>(function(){var t=document.getElementById("st-tipp");if(!t)return;
function zeig(el,x,y){t.textContent=el.getAttribute("data-tipp");t.classList.add("an");var w=t.offsetWidth,h=t.offsetHeight;
 t.style.left=Math.max(8,Math.min(innerWidth-w-8,x-w/2))+"px";t.style.top=Math.max(8,y-h-12)+"px"}
document.addEventListener("mousemove",function(e){var el=e.target.closest&&e.target.closest("[data-tipp]");if(el)zeig(el,e.clientX,e.clientY);else t.classList.remove("an")});
document.addEventListener("focusin",function(e){var el=e.target.closest&&e.target.closest("[data-tipp]");if(!el)return;var r=el.getBoundingClientRect();zeig(el,r.left+r.width/2,r.top)});
document.addEventListener("focusout",function(){t.classList.remove("an")});addEventListener("scroll",function(){t.classList.remove("an")},{passive:true})})();</script>"""


def _de(x, st=1):
    import etatplan
    return etatplan._de(x, st)


def _zahl(x):
    return f"{x:,.0f}".replace(",", ".")


def _tabelle(kopf, zeilen):
    return f'<details class="st-tab"><summary>Als Tabelle</summary>{amt.tabelle(kopf, zeilen)}</details>'


def _karte(titel, symbol, text, inhalt, breit=False):
    return (f'<section class="st-karte{" breit" if breit else ""}"><h3>{amt.ic(symbol)}{esc(titel)}</h3>'
            + (f"<p>{esc(text)}</p>" if text else "") + inhalt + "</section>")


# ---------------------------------------------------------------- Diagramme (Inline-SVG)

def balken(zeilen, fmt, maximum=None, ref_name="", breite=560):
    """Waagrechte Balken: zeilen = [(Name, Wert, Referenz oder None, schlecht?)]. Referenz = senkrechter Strich (z. B. Schnitt aller Teilstaaten)."""
    if not zeilen:
        return '<div class="st-leer">Keine Daten.</div>'
    hoch = 26
    lab, rest, kurz_ = (150, 78, 26) if breite >= 440 else (112, 66, 15)
    m = maximum or max([max(w, r or 0) for _, w, r, _ in zeilen] + [1e-9])
    bw = breite - lab - rest
    h = len(zeilen) * hoch + 6
    out = [f'<svg class="st-svg" viewBox="0 0 {breite} {h}" role="img" aria-label="Balkendiagramm">']
    for i, (n, w, r, schlecht) in enumerate(zeilen):
        y = i * hoch + 4
        lw = max(0, min(1, w / m)) * bw
        tipp = f"{n}: {fmt(w)}" + (f" · {ref_name} {fmt(r)}" if r is not None and ref_name else "")
        out.append(f'<text x="{lab - 8}" y="{y + 14}" text-anchor="end">{esc(n if len(n) <= kurz_ else n[:kurz_ - 1] + "…")}</text>'
                   f'<rect class="spur" x="{lab}" y="{y + 4}" width="{bw}" height="12" rx="4"/>'
                   f'<rect class="wert{" schlecht" if schlecht else ""}" x="{lab}" y="{y + 4}" width="{max(lw, 2):.1f}" height="12" rx="4" tabindex="0" data-tipp="{esc(tipp)}"/>')
        if r is not None:
            rx = lab + max(0, min(1, r / m)) * bw
            out.append(f'<line class="ref" x1="{rx:.1f}" x2="{rx:.1f}" y1="{y + 1}" y2="{y + 19}"/>')
        out.append(f'<text x="{lab + bw + 8}" y="{y + 14}" class="leise">{esc(fmt(w))}</text>')
    out.append("</svg>")
    leg = (f'<div class="st-legende"><span><i style="background:var(--akzent)"></i>dieser Teilstaat</span>'
           f'<span><i style="background:var(--ink);width:2px;border-radius:0"></i>{esc(ref_name)}</span></div>') if ref_name else ""
    return "".join(out) + leg


def rangpunkte(reihen, breite=560):
    """Rang unter allen Teilstaaten: reihen = [(Kennzahl, [(Name, Wert, ist_du)], fmt, hoch_gut)]. Je Zeile eine Spur mit allen Teilstaaten als Punkte."""
    hoch = 44
    lab, rechts = (150, 96) if breite >= 440 else (122, 80)
    bw = breite - lab - rechts
    h = len(reihen) * hoch + 4
    out = [f'<svg class="st-svg" viewBox="0 0 {breite} {h}" role="img" aria-label="Rang unter den Teilstaaten">']
    for i, (titel, werte, fmt, hoch_gut) in enumerate(reihen):
        y = i * hoch + 22
        ws = [w for _, w, _ in werte]
        lo, hi = min(ws), max(ws)
        sp = (hi - lo) or 1
        sortiert = sorted(werte, key=lambda x: -x[1] if hoch_gut else x[1])
        rang = next((j + 1 for j, x in enumerate(sortiert) if x[2]), None)
        out.append(f'<text x="{lab - 10}" y="{y + 4}" text-anchor="end">{esc(titel)}</text><line class="gitter" x1="{lab}" x2="{lab + bw}" y1="{y}" y2="{y}"/>')
        du = None
        for n, w, ist in werte:
            x = lab + (w - lo) / sp * bw
            if ist:
                du = (x, n, w)
                continue
            out.append(f'<circle class="punkt" cx="{x:.1f}" cy="{y}" r="5" tabindex="0" data-tipp="{esc(n)}: {esc(fmt(w))}"/>')
        if du:
            x, n, w = du
            out.append(f'<circle class="punkt du" cx="{x:.1f}" cy="{y}" r="8" tabindex="0" data-tipp="{esc(n)}: {esc(fmt(w))}"/>'
                       f'<text x="{min(max(x, lab + 20), lab + bw - 20):.1f}" y="{y - 12}" text-anchor="middle" class="leise">{esc(fmt(w))}</text>')
        out.append(f'<text x="{lab + bw + 12}" y="{y + 4}"><tspan font-weight="600">Rang {rang}</tspan><tspan class="leise"> / {len(werte)}</tspan></text>')
    out.append("</svg>")
    return "".join(out) + ('<div class="st-legende"><span><i style="background:var(--akzent);border-radius:50%"></i>dieser Teilstaat</span>'
                           '<span><i style="background:#c3c8cf;border-radius:50%"></i>übrige Teilstaaten</span><span>links schwächster, rechts höchster Wert</span></div>')


def stapel(teile, fmt, breite=560):
    """Ein gestapelter Balken für Anteile am Ganzen: teile = [(Name, Wert, Farbe)] in fester Reihenfolge; Legende mit Werten darunter."""
    ges = sum(w for _, w, _ in teile) or 1
    out = [f'<svg class="st-svg" viewBox="0 0 {breite} 34" role="img" aria-label="Anteile">']
    x = 0.0
    for n, w, f in teile:
        bw = w / ges * breite
        if bw <= 0:
            continue
        out.append(f'<rect x="{x:.1f}" y="4" width="{max(bw - 2, 1):.1f}" height="24" rx="4" fill="{f}" tabindex="0" data-tipp="{esc(n)}: {esc(fmt(w))} ({_de(w / ges * 100)} %)"/>')
        if bw > (46 if breite >= 440 else 34):
            out.append(f'<text x="{x + bw / 2:.1f}" y="21" text-anchor="middle" style="fill:#fff;font-weight:600">{_de(w / ges * 100, 0)} %</text>')
        x += bw
    out.append("</svg>")
    leg = "".join(f'<span><i style="background:{f}"></i>{esc(n)} {esc(fmt(w))}</span>' for n, w, f in teile if w > 0)
    return "".join(out) + f'<div class="st-legende">{leg}</div>'


def linie(punkte, fmt, breite=560, hoehe=170):
    """Verlauf: punkte = [(Beschriftung, Wert)], älteste zuerst. Ab zwei Punkten eine Linie, sonst ein Hinweis."""
    if len(punkte) < 2:
        jetzt = f" Aktuell: {fmt(punkte[-1][1])}." if punkte else ""
        return f'<div class="st-leer">Der Verlauf erscheint ab dem zweiten gebuchten Monat.{esc(jetzt)}</div>'
    l, r, o, u = 56, 12, 14, 26
    ws = [w for _, w in punkte]
    lo, hi = min(ws), max(ws)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * .12
    lo, hi = lo - pad, hi + pad
    pw, ph = breite - l - r, hoehe - o - u
    X = lambda i: l + i / (len(punkte) - 1) * pw
    Y = lambda w: o + (1 - (w - lo) / (hi - lo)) * ph
    out = [f'<svg class="st-svg" viewBox="0 0 {breite} {hoehe}" role="img" aria-label="Verlauf">']
    for j in range(3):
        w = lo + (hi - lo) * j / 2
        out.append(f'<line class="gitter" x1="{l}" x2="{breite - r}" y1="{Y(w):.1f}" y2="{Y(w):.1f}"/><text x="{l - 6}" y="{Y(w) + 4:.1f}" text-anchor="end" class="leise">{esc(fmt(w))}</text>')
    pts = " ".join(f"{X(i):.1f},{Y(w):.1f}" for i, (_, w) in enumerate(punkte))
    out.append(f'<polygon class="flaeche" points="{l},{o + ph} {pts} {X(len(punkte) - 1):.1f},{o + ph}"/><polyline class="linie" points="{pts}"/>')
    schritt = max(1, len(punkte) // 6)
    for i, (b, w) in enumerate(punkte):
        out.append(f'<circle cx="{X(i):.1f}" cy="{Y(w):.1f}" r="4.5" fill="var(--akzent)" stroke="#fff" stroke-width="2" tabindex="0" data-tipp="{esc(b)}: {esc(fmt(w))}"/>')
        if i % schritt == 0 or i == len(punkte) - 1:
            out.append(f'<text x="{X(i):.1f}" y="{hoehe - 6}" text-anchor="middle" class="leise">{esc(b)}</text>')
    out.append("</svg>")
    return "".join(out)


def zwei(f, *a, breit=False, **kw):
    """Diagramm in zwei Fassungen: breit (Desktop) und schmal (Handy); CSS blendet je nach Bildschirm eine aus, damit die Schrift lesbar bleibt."""
    return f'<div class="st-g">{f(*a, breite=900 if breit else 460, **kw)}</div><div class="st-k">{f(*a, breite=360, **kw)}</div>'


# ---------------------------------------------------------------- Seite

def leiste(liste, aktiv):
    import wappen
    eintraege = [("", "Alle Haushalte", amt.ic("chart-column"))] + [("ts-" + x["staat"], x["name"], wappen.klein(x["staat"], x["name"], 34) or amt.ic("flag"))
                                                                    for x in sorted(liste, key=lambda x: x["name"]) if not x["reichsgebiet"]]
    links = "".join(f'<a href="{PFAD}{"?staat=" + esc(s) if s else ""}"{" class=aktiv aria-current=page" if s == aktiv else ""}>{w}<span>{esc(n)}</span></a>'
                    for s, n, w in eintraege)
    return (CSS + f'<nav class="st-leiste" aria-label="Statistik wählen">{links}</nav>'
            '<script>(function(){var a=document.querySelector(".st-leiste a.aktiv");if(a){var n=a.parentNode;n.scrollLeft=a.offsetLeft-n.clientWidth/2+a.offsetWidth/2}})()</script>')


def _monat(p):
    try:
        return sa._monatsname(p)
    except Exception:
        return p


def seite_html(con, liste, x):
    """HTML aller Diagramme für den Teilstaat x (Eintrag aus aufkommen.berechnen)."""
    import entwicklung
    import etatplan
    staaten = [y for y in liste if not y["reichsgebiet"] and y.get("entwicklung")]
    schl = "ts-" + x["staat"]
    d = x["entwicklung"]
    z = x["zufriedenheit_land"]
    ew = x["ew"] or 1

    # Kennzahlen
    kz = [(_zahl(x["ew"]), "Einwohner"), (_de(d["hdi"], 3), "Index menschlicher Entwicklung (HDI)"), (f'{_de(z["neu"])} / 100', f'Zufriedenheit · {z["stufe"]}'),
          (f'{_de(d["lebenserwartung"])} J.', "Lebenserwartung"), (entwicklung._vz(d["bev_pp"] * 12), "Bevölkerung im Jahr"),
          (_zahl(d["kriminalitaet"]), "Straftaten je 100.000 Ew."), (geld.mark_kurz(x["summe"]), "Etat im Monat"), (f'{_de(x["quote"])} %', "Abgabe an das Reich")]
    kopf = '<div class="kennzahlen">' + "".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for v, t in kz) + "</div>"

    # Rang
    def reihe(titel, f, fmt, hoch_gut=True):
        return (titel, [(y["name"], f(y), y["staat"] == x["staat"]) for y in staaten], fmt, hoch_gut)
    reihen = [reihe("HDI", lambda y: y["entwicklung"]["hdi"], lambda v: _de(v, 3)),
              reihe("Zufriedenheit", lambda y: y["zufriedenheit_land"]["neu"], lambda v: _de(v)),
              reihe("Lebenserwartung", lambda y: y["entwicklung"]["lebenserwartung"], lambda v: f"{_de(v)} J."),
              reihe("Kriminalität", lambda y: y["entwicklung"]["kriminalitaet"], _zahl, False),
              reihe("Etat je Einwohner", lambda y: y["summe"] / max(1, y["ew"]) / 100, lambda v: f"{_de(v, 0)} Kr"),
              reihe("Wachstum", lambda y: y["entwicklung"]["bev_pp"] * 12, lambda v: f"{_de(v, 2)} %")]
    rang = zwei(rangpunkte, reihen, breit=True)
    rang_tab = _tabelle(["Kennzahl", "Wert", "Schnitt aller Teilstaaten"],
                        [(esc(t), esc(fmt(next(w for _, w, du in ws if du))), esc(fmt(sum(w for _, w, _ in ws) / len(ws)))) for t, ws, fmt, _ in reihen])

    # Etatverteilung (Anteil am Ausgabenbudget) mit Schnitt aller Teilstaaten
    def anteile(y):
        p = y["pool_land"] or 1
        return {k: y["verteilung_land"].get(k, 0) / p * 100 for k, _ in etatplan.KATEGORIEN}
    eig = anteile(x)
    schnitt = {k: sum(anteile(y)[k] for y in staaten) / len(staaten) for k, _ in etatplan.KATEGORIEN}
    ez = sorted([(etatplan.NAMEN[k], eig[k], schnitt[k], False) for k, _ in etatplan.KATEGORIEN], key=lambda t: -t[1])
    etat = (zwei(balken, ez, lambda v: f"{_de(v)} %", ref_name="Schnitt aller Teilstaaten")
            + _tabelle(["Politikfeld", "Anteil", "Betrag im Monat", "Schnitt aller Teilstaaten"],
                       [(esc(n), f"{_de(v)} %", geld.mark_kurz(x["verteilung_land"].get(k, 0)), f"{_de(schnitt[k])} %")
                        for k, _ in etatplan.KATEGORIEN for n, v in [(etatplan.NAMEN[k], eig[k])]]))

    # Zufriedenheit je Politikfeld
    zt = sorted(((etatplan.NAMEN.get(k, k), w, None, w < 55) for k, w, g in z["teile"]), key=lambda t: -t[1])
    gew = {etatplan.NAMEN.get(k, k): g for k, w, g in z["teile"]}
    zuf = (zwei(balken, zt, lambda v: _de(v), maximum=100)
           + '<div class="st-legende"><span><i style="background:var(--akzent)"></i>zufrieden (ab 55)</span><span><i style="background:#8c929b"></i>unzufrieden</span></div>'
           + _tabelle(["Politikfeld", "Zufriedenheit", "Gewicht"], [(esc(n), _de(w), f"{gew.get(n, 0)} %") for n, w, _, _ in zt]))

    # Entwicklung: Indikatoren je Modul (0–100), Strich = Wert vor dem letzten Monat
    ez2, tab2 = [], []
    for m in entwicklung.MODULE:
        for ind in m["indikatoren"]:
            v = d["zustand"].get(ind["id"])
            if not v:
                continue
            schlecht = (v["neu"] > 50) if ind["id"] in NIEDRIG_GUT else (v["neu"] < 50)
            name = ind["name"] + (" ↓" if ind["id"] in NIEDRIG_GUT else "")
            ez2.append((name, v["neu"], v.get("alt"), schlecht))
            tab2.append((esc(m["name"]), esc(ind["name"]), _de(v.get("alt") or 0), _de(v["neu"]), _de(v.get("ziel") or 0)))
    entw = (zwei(balken, ez2, lambda v: _de(v), maximum=100, ref_name="Wert im Vormonat", breit=True)
            + '<div class="st-legende"><span>↓ = weniger ist besser</span><span><i style="background:#8c929b"></i>kritischer Bereich</span></div>'
            + _tabelle(["Bereich", "Indikator", "Vormonat", "Jetzt", "Zielwert"], tab2))

    # Energie
    import energie
    try:
        b = energie.bilanz(con, schl)
    except Exception:
        b = None
    if b:
        mix = sorted(b.get("mix", {}).items(), key=lambda t: -t[1])
        farben = etatplan.PALETTE
        reihenfolge = [k for k in ENERGIE_NAMEN if k in dict(mix)] + [k for k, _ in mix if k not in ENERGIE_NAMEN]
        teile = [(ENERGIE_NAMEN.get(k, k), dict(mix)[k], farben[i % len(farben)]) for i, k in enumerate(reihenfolge)]
        gwh = lambda v: energie.gwh_text(v)
        bedarf = [("Haushalte", b["hh"], None, False), ("Industrie", b["ind"], None, False), ("Militär", b["mil"], None, False),
                  ("Bedarf gesamt", b["bedarf"], None, False), ("Erzeugung", b["angebot"], None, b["angebot"] < b["bedarf"])]
        en = ('<p class="az" style="margin:0 0 4px">Erzeugung nach Energieträger (je Monat)</p>' + zwei(stapel, teile, gwh)
              + '<p class="az" style="margin:14px 0 4px">Bedarf und Erzeugung (je Monat)</p>' + zwei(balken, bedarf, gwh)
              + _tabelle(["Posten", "GWh je Monat"], [(esc(n), esc(gwh(w))) for n, w, _ in teile] + [(esc(n), esc(gwh(w))) for n, w, _, _ in bedarf]))
    else:
        en = '<div class="st-leer">Keine Energiedaten.</div>'

    # Produktion (letzter Lauf)
    import handel
    ws = handel.waren(con)
    per = con.execute("SELECT MAX(periode) p FROM hd_produktion WHERE schl=?", (schl,)).fetchone()["p"]
    prod = con.execute("SELECT ware, menge FROM hd_produktion WHERE schl=? AND periode=? AND menge>0 ORDER BY menge DESC", (schl, per)).fetchall() if per else []
    if prod:
        werte = [(ws[r["ware"]]["name"] if r["ware"] in ws else r["ware"], r["menge"] * (ws[r["ware"]]["preis"] if r["ware"] in ws else 0), r) for r in prod]
        werte = sorted(werte, key=lambda t: -t[1])[:12]
        pz = [(n, w / 100, None, False) for n, w, _ in werte]
        produktion = (f'<p class="az" style="margin:0 0 4px">Wert zum Richtpreis, {esc(_monat(per))} – die zwölf wichtigsten Waren</p>'
                      + zwei(balken, pz, lambda v: geld.mark_kurz(v * 100))
                      + _tabelle(["Ware", "Menge", "Wert zum Richtpreis"],
                                 [(esc(n), f'{_zahl(r["menge"])} {esc(ws[r["ware"]]["einheit"]) if r["ware"] in ws else ""}', geld.mark_kurz(w)) for n, w, r in werte]))
    else:
        produktion = '<div class="st-leer">Noch keine Produktion gebucht.</div>'

    # Steuern und Reichsabgabe
    steuern = (zwei(stapel, [("an das Reich", x["reich"], "var(--ink)"), ("beim Teilstaat", x["land"], "var(--akzent)")], geld.mark_kurz, breit=True)
               + '<p class="az" style="margin:14px 0 4px">Abgabequote im Vergleich</p>'
               + zwei(balken, sorted([(y["name"], y["quote"], None, False) for y in staaten], key=lambda t: -t[1]), lambda v: f"{_de(v)} %", breit=True)
               .replace(f'data-tipp="{esc(x["name"])}:', f'style="fill:var(--ink)" data-tipp="{esc(x["name"])} (dieser Teilstaat):')
               + '<div class="st-legende"><span><i style="background:var(--ink)"></i>dieser Teilstaat</span><span><i style="background:var(--akzent)"></i>übrige Teilstaaten</span></div>')

    # Verläufe
    stv = [(_monat(r["periode"]), r["summe"] / 100) for r in con.execute(
        "SELECT l.periode, p.summe FROM ak_posten p JOIN ak_laeufe l ON l.id=p.lauf WHERE p.staat=? ORDER BY l.periode", (x["staat"],))][-12:]
    zv = [(_monat(p), w) for p, w in etatplan.zuf_verlauf(con, schl)]
    ev = entwicklung.verlauf(con, schl)
    hdi_v = [(_monat(p), w["hdi"]) for p, w in ev if "hdi" in w]
    verl = ('<div class="st-raster">'
            + _karte("Steueraufkommen", "coins", "Einnahmen je gebuchtem Monat", zwei(linie, stv, lambda v: geld.mark_kurz(v * 100)))
            + _karte("Zufriedenheit", "users", "Bevölkerungszufriedenheit je Monat (0–100)", zwei(linie, zv, lambda v: _de(v)))
            + (_karte("HDI", "chart-column", "Index menschlicher Entwicklung je Monat", zwei(linie, hdi_v, lambda v: _de(v, 3))) if hdi_v else "")
            + "</div>")

    return (kopf
            + '<div class="st-raster">'
            + _karte("Rang unter den Teilstaaten", "chart-column", "Wo der Teilstaat im Vergleich aller Teilstaaten steht.", rang + rang_tab, breit=True)
            + _karte("Etatverteilung", "chart-pie", "Anteil der Politikfelder am Ausgabenbudget des laufenden Monats.", etat)
            + _karte("Zufriedenheit je Politikfeld", "users", f'Gesamt {_de(z["neu"])} / 100 ({z["stufe"]}).', zuf)
            + _karte("Entwicklung", "landmark", "Indikatoren von 0 bis 100; der Strich zeigt den Vormonat.", entw, breit=True)
            + _karte("Energie", "zap", "", en)
            + _karte("Produktion", "package", "", produktion)
            + _karte("Steuern und Reichsabgabe", "receipt", f'Steueraufkommen im Monat {geld.mark_kurz(x["summe"])}, davon {_de(x["quote"])} % an das Reich.', steuern, breit=True)
            + "</div><h2>Verläufe</h2>" + verl + JS)
