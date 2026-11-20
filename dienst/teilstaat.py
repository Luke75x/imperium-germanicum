"""Mein Teilstaat (/schatzamt/teilstaat/): Überblick über alles, was ein Landesherr für seinen Teilstaat braucht – Handlungsbedarf (Etat einreichen,
Haushaltsnotlage, Militär), Kassen, geltender Etat, Reichsabgabe, letzte Umsätze. Die übrigen Reiter (Etat, Etat planen, Verteidigung, Haushaltsnotlage,
Kasse & Umsätze) sind bestehende Seiten, die dieselbe Reiterleiste tragen (schatzamt.reiter_html); die Seitenleiste hat nur den Eintrag „Mein Teilstaat“.
Sichtbar für alle, die einen Teilstaat regieren (geld.regierte_staatskassen); mehrere Teilstaaten (Kronkanzler) wählt man oben aus.
"""
from aiohttp import web

import amt
import geld
import schatzamt as sa
from geld import mark

import os

esc = amt.esc
PFAD = sa.PFAD + "teilstaat/"
WAPPEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wappen_staaten")   # <Karten-ID, z. B. s6>.png, Reihenfolge/Zuordnung siehe Memory teilstaat-wappen


def wappen_html(sid, name=""):
    """Wappen eines Teilstaats (Karten-ID wie „s6“) als <img> für Überschriften; leer, wenn noch kein Bild vorliegt."""
    if not sid or not os.path.isfile(os.path.join(WAPPEN_DIR, f"{sid}.png")):
        return ""
    return f'<img class="ts-wappen" src="{sa.PFAD}wappen/{esc(sid)}.png" alt="Wappen {esc(name)}" loading="lazy">'


WAPPEN_CSS = '<style>.ts-kopf{display:flex;align-items:center;gap:16px}.ts-kopf h1{margin:0}.ts-wappen{height:72px;width:auto;flex:none;filter:drop-shadow(0 1px 3px rgba(0,0,0,.35))}@media(max-width:520px){.ts-wappen{height:54px}}</style>'


def kopf_mit_wappen(h1, sid, name=""):
    w = wappen_html(sid, name)
    return WAPPEN_CSS + f'<div class="ts-kopf">{w}{h1}</div>' if w else h1


async def wappen(request):
    sid = request.match_info["sid"]
    pfad = os.path.join(WAPPEN_DIR, sid + ".png")
    if not sid.isalnum() or not os.path.isfile(pfad):
        raise web.HTTPNotFound()
    return web.FileResponse(pfad, headers={"Cache-Control": "public, max-age=86400"})


def _zeile(klasse, symbol, text, zusatz="", link=None):
    """Eine Zeile „Auf einen Blick“: text (HTML), optional graue Zusatzzeile und ein Link (URL, Beschriftung)."""
    zus = f'<span class="az">{zusatz}</span>' if zusatz else ""
    lnk = f' <a href="{esc(link[0])}">{esc(link[1])}</a>' if link else ""
    return f'<div class="{klasse}">{amt.ic(symbol)}<span>{text}{lnk}{zus}</span></div>'


@sa.seite("staat")
async def seite(request, k):
    import aufkommen
    import etatplan
    import entwicklung
    import notlage
    import verteidigung
    con = request.app["db"]
    regiert = sa._regierte(con, k)
    if not regiert:
        return sa.ant(request, k, "Mein Teilstaat", "sa-teilstaat",
                      f'<h1>{amt.ic("flag")} Mein Teilstaat</h1><div class="hinweis">Dieser Bereich ist für Landesherren: Etat, Kassen, Verteidigung und Haushaltsnotlage '
                      f'des eigenen Teilstaats. Ihnen ist kein Teilstaat zugeordnet. Den Haushalt des Reiches sehen Sie unter <a href="{sa.PFAD}haushalt/">Reichshaushalt</a>.</div>')
    ziel = request.query.get("ziel", "")
    sid = ziel[3:] if ziel.startswith("ts-") and ziel[3:] in regiert else next(iter(regiert))
    schl = "ts-" + sid
    kasse = regiert[sid]
    monat = etatplan.monat_heute()
    liste = aufkommen.berechnen(con, periode=monat)
    x = next(y for y in liste if y["staat"] == sid)
    zuf = x["zufriedenheit_land"]
    q = x["quote"]
    abgabe = f'{etatplan._de(q)} %'
    rk = entwicklung.rueckhalt_fuer(con, liste, schl)
    kz = [("Staatskasse", mark(kasse["saldo"])), ("Etat im Monat", mark(x["summe"])), ("Abgabe an das Reich", abgabe),
          ("Zufriedenheit", f'{etatplan._de(zuf["neu"], 0)} / 100')]
    if rk:
        kz.insert(0, ("Rückhalt beim Volk", f'{etatplan._de(rk["wert"], 0)} · {rk["stufe"]}'))

    # Handlungsbedarf
    z = []
    import krisen
    for f in krisen.offene(con, schl):   # offene Krisen zuerst: Handlungszwang
        kd = krisen.KRISEN[f["art"]]
        frist, knapp = krisen._frist_text(f["frist"])
        z.append(_zeile("warn", "triangle-alert", f'<b>{esc(kd["name"])}</b> ({esc(f["ausloeser"])}) – der Landesherr muss bis {esc(amt._zeit(f["frist"]))} reagieren ({esc(frist)}).',
                        f["text"], (sa.PFAD + f"krisen/?ziel={schl}", "Jetzt reagieren")))
    if rk:
        pf = {"steigend": "steigt", "fallend": "sinkt", "stabil": "bleibt stabil"}[rk["trend"]]
        z.append(_zeile("warn" if rk["wert"] < 55 else "", "users", f'<b>{esc(rk["text"])}</b> Rückhalt {etatplan._de(rk["wert"], 0)} / 100, in 3 Monaten voraussichtlich {etatplan._de(rk["prognose3"], 0)}; '
                        f'auf Dauer {pf} (bei gleichem Etat {etatplan._de(rk["langfristig"], 0)}).',
                        "; ".join(t["text"] for t in rk["gruende"]), (sa.PFAD + f"entwicklung/?ziel={schl}", "Einzelheiten")))
    eing, ent = etatplan.eingereicht(con, schl), etatplan.entwurf(con, schl)
    von, bis = etatplan.aenderungsperiode()
    ab = etatplan.monat_folgend()
    plan_link = (sa.PFAD + f"etatplanung/?ziel={schl}", "Etat planen") if etatplan.darf_aendern(con, k, schl) else None
    if eing:
        z.append(_zeile("ok", "check", f"<b>Etat für {esc(sa._monatsname(ab))} eingereicht</b>", f"Er gilt ab {esc(sa._monatsname(ab))}; die nächste Änderung ist in der nächsten Änderungsperiode möglich."))
    elif etatplan.in_aenderungsperiode():
        z.append(_zeile("warn", "triangle-alert", f"<b>Änderungsperiode läuft bis {esc(etatplan._tag(bis))}</b> – der Etat für {esc(sa._monatsname(ab))} ist noch nicht eingereicht.",
                        "Entwurf gespeichert, aber nicht eingereicht." if ent else "Es gibt noch keinen Entwurf. Ohne Einreichen bleibt der bisherige Etat.", plan_link))
    else:
        z.append(_zeile("", "clock", f"Nächste Änderungsperiode: <b>{esc(etatplan._tag(von))} bis {esc(etatplan._tag(bis))}</b>",
                        ("Ein Entwurf ist gespeichert." if ent else "Bis dahin lässt sich ein Entwurf vorbereiten."), plan_link))
    vtk = geld.stellenkonto(con, "vt-" + sid)
    in_not = False
    for r in [kasse] + ([vtk] if vtk else []):
        f = notlage.offener_fall(con, r["id"])
        if f:
            in_not = True
            z.append(_zeile("warn", "triangle-alert", f'<b>{esc(r["name"])} in der Haushaltsnotlage</b> (Stufe {f["stufe"]})', f'Kontostand {esc(mark(r["saldo"]))}',
                            (sa.PFAD + f"notlagen/?bereich={schl}", "Details")))
    if not in_not:
        z.append(_zeile("ok", "check", "Keine Kasse im Minus."))
    if verteidigung.darf_sehen(con, k, sid) and vtk:
        kzv = verteidigung.kennzahlen(con, "vt-" + sid)
        b = kzv["bereitschaft"]
        z.append(_zeile("warn" if b is not None and b < 50 else "", "shield",
                        f'Militär: Einsatzbereitschaft <b>{"–" if b is None else etatplan._de(b, 0) + " %"}</b>, {kzv["einheiten"]:,} Einheiten'.replace(",", "."),
                        f'Etat {esc(geld.mark_kurz(x["vert_land"]))} im Monat · Instandhaltung {esc(geld.mark_kurz(kzv["instandhaltung"]))}', (sa.PFAD + f"verteidigung/{sid}/", "Verteidigung")))

    # Bereiche: jede Karte führt zu einem Reiter und nennt, was dort wichtig ist
    vtk = geld.stellenkonto(con, "vt-" + sid)
    kassen = [kasse] + ([vtk] if vtk else [])
    n_kr = len(krisen.offene(con, schl))
    import gold
    kg = gold.bestand(con, schl)

    def karte(symbol, titel, url, zeilen, fuss="", warn=False):
        return (f'<a class="ts-karte" href="{esc(url)}"><b class="ts-kt">{amt.ic(symbol)}{esc(titel)}</b>'
                + "".join(f"<p>{t}</p>" for t in zeilen) + (f'<small>{fuss}</small>' if fuss else "") + '</a>')
    ab_text = ("Etat eingereicht" if eing else "Änderungsperiode läuft" if etatplan.in_aenderungsperiode() else "Entwurf möglich")
    karten = [karte("chart-pie", "Etat", sa.PFAD + f"etatverteilung/?ziel={schl}",
                    [f"Etat im Monat: <strong>{esc(geld.mark_kurz(x['summe']))}</strong>", f"Abgabe an das Reich: <strong>{esc(abgabe)}</strong>",
                     f"{x['wirkung_land']['boni']} Boni · {x['wirkung_land']['mali']} Mali"], esc(ab_text) + " →"),
              karte("users", "Land", sa.PFAD + f"teilstaat/land/?ziel={schl}",
                    [f"Entwicklung, Energie, Krisen", f"HDI <strong>{etatplan._de(x['entwicklung']['hdi'], 3)}</strong> · Zufriedenheit <strong>{etatplan._de(zuf['neu'], 0)}</strong>"],
                    (f"{n_kr} offene Krise{'n' if n_kr != 1 else ''}" if n_kr else "Keine offene Krise") + " →"),
              karte("wallet", "Finanzen", sa.PFAD + f"teilstaat/finanzen/?ziel={schl}",
                    [f"Staatskasse: <strong>{esc(mark(kasse['saldo']))}</strong>"] + ([f"Verteidigungskasse: <strong>{esc(mark(vtk['saldo']))}</strong>"] if vtk else [])
                    + [f"Gold: <strong>{kg / 1000:,.1f} t</strong>".replace(",", "X").replace(".", ",").replace("X", ".")],
                    "Haushaltsnotlage" + (" – offen" if in_not else ": keine") + " →")]
    if verteidigung.darf_sehen(con, k, sid) and vtk:
        karten.append(karte("shield", "Verteidigung", sa.PFAD + f"verteidigung/{sid}/",
                            [f"Einsatzbereitschaft: <strong>{'–' if b is None else etatplan._de(b, 0) + ' %'}</strong>", f"{kzv['einheiten']:,} Einheiten".replace(",", ".")], "Bestand und Beschaffung →"))
    inhalt = (kopf_mit_wappen(f'<h1>{amt.ic("flag")} {esc(x["name"])}</h1>', sid, x["name"]) + amt.meldung(request) +
              f'<p class="az">Die Lage Ihres Teilstaats auf einen Blick. Die Reiter oben führen zu Etat, Land (Entwicklung, Energie, Krisen), Finanzen und Verteidigung.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              f'<h2>Auf einen Blick</h2><div class="sa-todo">{"".join(z)}</div>'
              f'<h2>Bereiche</h2><div class="ts-karten">{"".join(karten)}</div>')
    return sa.ant(request, k, "Mein Teilstaat", "sa-teilstaat", inhalt)


def _kopf(request, k):
    """(con, regiert, sid, schl, kasse) – oder None, wenn kein Teilstaat regiert wird."""
    con = request.app["db"]
    regiert = sa._regierte(con, k)
    if not regiert:
        return None
    ziel = request.query.get("ziel", "")
    sid = ziel[3:] if ziel.startswith("ts-") and ziel[3:] in regiert else next(iter(regiert))
    return con, regiert, sid, "ts-" + sid, regiert[sid]


def _abschnitte(nav, teile):
    """Untertabs einer gebündelten Seite: teile = [(Name, Symbol, Titel, HTML, Markierung)]."""
    return sa.untertabs([(a, t, h.replace("<h2", "<h3").replace("</h2>", "</h3>"), w) for a, _, t, h, w in teile])


@sa.seite("staat")
async def land(request, k):
    """Reiter „Land“: Entwicklung, Energie und Krisen eines Teilstaats auf einer Seite."""
    import aufkommen
    import energie
    import entwicklung
    import etatplan
    import krisen
    kp = _kopf(request, k)
    if not kp:
        raise web.HTTPFound(PFAD)
    con, regiert, sid, schl, kasse = kp
    liste = aufkommen.berechnen(con, periode=etatplan.monat_heute())
    ziele = etatplan.ziele(con, liste)
    n_kr = krisen.offene_anzahl(con, schl)
    teile = [("entwicklung", "users", "Entwicklung", entwicklung.rumpf(request, k, con, liste, schl, ziele, True), False),
             ("energie", "zap", "Energie", energie._seitenhtml(request, k, con, schl, True), False),
             ("krisen", "triangle-alert", f"Krisen ({n_kr})" if n_kr else "Krisen", krisen.rumpf(request, k, con, schl, True), bool(n_kr))]
    if n_kr:
        teile.insert(0, teile.pop())   # offene Krisen zuerst: Handlungszwang
    name = esc(kasse["name"].replace("Staatskasse ", ""))
    inhalt = (kopf_mit_wappen(f'<h1>{amt.ic("users")} Land · {name}</h1>', sid, name) + amt.meldung(request) +
              '<p class="az">Wie sich der Teilstaat langfristig entwickelt: Bevölkerung und Wirtschaft (Entwicklung), die Energieversorgung und Krisen, auf die der Landesherr reagieren muss. '
              'Alles folgt aus dem Etat; die Werte ändern sich nur allmählich.</p>' + _abschnitte(None, teile))
    return sa.ant(request, k, "Land", "sa-ts-land", inhalt)


@sa.seite("staat")
async def finanzen(request, k):
    """Reiter „Finanzen“: Kassen, Reichsabgabe, Goldreserven, Haushaltsnotlage und letzte Umsätze eines Teilstaats."""
    import aufkommen
    import etatplan
    import gold
    import notlage
    kp = _kopf(request, k)
    if not kp:
        raise web.HTTPFound(PFAD)
    con, regiert, sid, schl, kasse = kp
    liste = aufkommen.berechnen(con, periode=etatplan.monat_heute())
    x = next(y for y in liste if y["staat"] == sid)
    q = x["quote"]
    vtk = geld.stellenkonto(con, "vt-" + sid)
    kassen = [kasse] + ([vtk] if vtk else [])
    kassen_html = (f'<h3>Kassen</h3><div class="sa-karten">{sa._karten(kassen, sa._kassen_zusatz(con, [kasse]))}</div>'
                   f'<h3>Reichsabgabe</h3><p class="sa-hinweis">Der Teilstaat gibt <b>{esc(etatplan._de(q))} %</b> seines Steueraufkommens an das Reich ab ({esc(mark(x["reich"]))} im Monat), höchstens '
                   f'{esc(str(geld.einstellung(con, "aufkommen").get("quote_max", 33)))} %'
                   + (f'. Ohne diese Obergrenze wären es <b>{etatplan._de(x["quote_theorie"])} %</b> ({esc(mark(x["reich_theorie"]))}).' if q + 0.05 < x["quote_theorie"] else ".")
                   + f' Die Berechnung steht unter <a href="{sa.PFAD}haushalt/">Reichshaushalt</a>.</p>')
    in_not = any(notlage.offener_fall(con, r["id"]) for r in kassen)
    umsatz = (f'<h3>Letzte Umsätze · {esc(kasse["name"])}</h3>' + amt.tabelle(sa.UMSATZ_KOPF, sa.umsatz_zeilen(con, kasse["id"], sa.umsaetze(con, kasse["id"], 8)), "Noch keine Umsätze.")
              + f'<p><a href="{sa.PFAD}konto/?konto={kasse["id"]}">Alle Umsätze und Kontoauszüge →</a></p>')
    teile = [("kassen", "wallet", "Kassen", kassen_html, False),
             ("gold", "coins", "Gold", gold.teilstaat_rumpf(request, k, con, sid, kasse), False),
             ("notlage", "triangle-alert", "Notlage", notlage.rumpf_teilstaat(request, k, con, sid), in_not),
             ("umsaetze", "file-text", "Umsätze", umsatz, False)]
    name = esc(kasse["name"].replace("Staatskasse ", ""))
    inhalt = (kopf_mit_wappen(f'<h1>{amt.ic("wallet")} Finanzen · {name}</h1>', sid, name) + amt.meldung(request) +
              '<p class="az">Das Geld des Teilstaats: Kassen, Abgabe an das Reich, Goldreserven, die Lage bei einem Minus und die letzten Buchungen.</p>' + _abschnitte(None, teile))
    return sa.ant(request, k, "Finanzen", "sa-ts-fin", inhalt)


def registrieren(app):
    app.router.add_get(sa.PFAD + "wappen/{sid}.png", wappen)
    app.router.add_get(PFAD, seite)
    app.router.add_get(PFAD + "land/", land)
    app.router.add_get(PFAD + "finanzen/", finanzen)
