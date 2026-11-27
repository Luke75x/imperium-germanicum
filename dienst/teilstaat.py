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
amt.ICONS.setdefault("settings", '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>')
PFAD = sa.PFAD + "teilstaat/"
import wappen as _w
WAPPEN_DIR = _w.DIR   # <Karten-ID, z. B. s6>.png, Reihenfolge/Zuordnung siehe Memory teilstaat-wappen


def wappen_html(sid, name=""):
    """Wappen eines Teilstaats (Karten-ID wie „s6“) als <img> für Überschriften; leer, wenn noch kein Bild vorliegt."""
    sid = _w.datei(sid)
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
    return web.FileResponse(pfad, headers={"Cache-Control": "no-cache"})


def _zeile(klasse, symbol, text, zusatz="", link=None):
    """Eine Zeile „Auf einen Blick“: text (HTML), optional graue Zusatzzeile und ein Link (URL, Beschriftung)."""
    zus = f'<span class="az">{zusatz}</span>' if zusatz else ""
    lnk = f' <a href="{esc(link[0])}">{esc(link[1])}</a>' if link else ""
    return f'<div class="{klasse}">{amt.ic(symbol)}<span>{text}{lnk}{zus}</span></div>'


async def ueberblick(request, k, con, sid, kasse, kopf=True):
    """HTML des Reiters „Überblick“ eines Teilstaats (auch in der RP-Leitung: rpteilstaaten.py, dort kopf=False)."""
    import aufkommen
    import etatplan
    import entwicklung
    import notlage
    import verteidigung
    schl = "ts-" + sid
    monat = etatplan.monat_heute()
    liste = aufkommen.berechnen(con, periode=monat)
    x = next(y for y in liste if y["staat"] == sid)
    zuf = x["zufriedenheit_land"]
    q = x["quote"]
    abgabe = f'{etatplan._de(q)} %'
    rk = entwicklung.rueckhalt_fuer(con, liste, schl)
    import befugnisse
    sieht = {b: befugnisse.darf_sehen(con, k, sid, b) for b in befugnisse.BEREICHE}   # eingestellte Personen: nur Bereiche mit Befugnis
    kz = ([("Staatskasse", mark(kasse["saldo"]))] if sieht["finanzen"] else []) + ([("Etat im Monat", mark(x["summe"]))] if sieht["etat"] else []) + [("Abgabe an das Reich", abgabe)]

    # Handlungsbedarf
    z = []
    import krisen
    for f in (krisen.offene(con, schl) if sieht["krisen"] else []):   # offene Krisen zuerst: Handlungszwang
        kd = krisen.KRISEN[f["art"]]
        frist, knapp = krisen._frist_text(f["frist"])
        z.append(_zeile("warn", "triangle-alert", f'<b>{esc(kd["name"])}</b> ({esc(f["ausloeser"])}) – der Landesherr muss bis {esc(amt._zeit(f["frist"]))} reagieren ({esc(frist)}).',
                        f["text"], (sa.PFAD + f"krisen/?ziel={schl}", "Jetzt reagieren")))
    if rk and sieht["entwicklung"]:
        pf = {"steigend": "steigt", "fallend": "sinkt", "stabil": "bleibt stabil"}[rk["trend"]]
        z.append(_zeile("warn" if rk["wert"] < 55 else "", "users", f'<b>{esc(rk["text"])}</b> Bevölkerungszufriedenheit {etatplan._de(rk["wert"], 0)} / 100, in 3 Monaten voraussichtlich {etatplan._de(rk["prognose3"], 0)}; '
                        f'auf Dauer {pf} (bei gleichem Etat {etatplan._de(rk["langfristig"], 0)}).',
                        "; ".join(t["text"] for t in rk["gruende"]), (sa.PFAD + f"entwicklung/?ziel={schl}", "Einzelheiten")))
    eing, ent = etatplan.eingereicht(con, schl), etatplan.entwurf(con, schl)
    von, bis = etatplan.aenderungsperiode()
    ab = etatplan.monat_folgend()
    plan_link = (sa.PFAD + f"etatplanung/?ziel={schl}", "Etat planen") if etatplan.darf_aendern(con, k, schl) else None
    if not sieht["etat"]:
        pass
    elif eing:
        z.append(_zeile("ok", "check", f"<b>Etat für {esc(sa._monatsname(ab))} eingereicht</b>", f"Er gilt ab {esc(sa._monatsname(ab))}; die nächste Änderung ist in der nächsten Änderungsperiode möglich."))
    elif etatplan.in_aenderungsperiode():
        z.append(_zeile("warn", "triangle-alert", f"<b>Änderungsperiode läuft bis {esc(etatplan._tag(bis))}</b> – der Etat für {esc(sa._monatsname(ab))} ist noch nicht eingereicht.",
                        "Entwurf gespeichert, aber nicht eingereicht." if ent else "Es gibt noch keinen Entwurf. Ohne Einreichen bleibt der bisherige Etat.", plan_link))
    else:
        z.append(_zeile("", "clock", f"Nächste Änderungsperiode: <b>{esc(etatplan._tag(von))} bis {esc(etatplan._tag(bis))}</b>",
                        ("Ein Entwurf ist gespeichert." if ent else "Bis dahin lässt sich ein Entwurf vorbereiten."), plan_link))
    vtk = geld.stellenkonto(con, "vt-" + sid)
    in_not = False
    for r in ([kasse] + ([vtk] if vtk else [])) if sieht["finanzen"] else []:
        f = notlage.offener_fall(con, r["id"])
        if f:
            in_not = True
            z.append(_zeile("warn", "triangle-alert", f'<b>{esc(r["name"])} in der Haushaltsnotlage</b> (Stufe {f["stufe"]})', f'Kontostand {esc(mark(r["saldo"]))}',
                            (sa.PFAD + f"teilstaat/finanzen/?ziel={schl}#notlage", "Details")))
    if not in_not and sieht["finanzen"]:
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
                    [f"Entwicklung, Energie, Krisen", f"HDI <strong>{etatplan._de(x['entwicklung']['hdi'], 3)}</strong> · Zufriedenheit <strong>{etatplan._de(rk['wert'] if rk else zuf['neu'], 0)}</strong>"],
                    (f"{n_kr} offene Krise{'n' if n_kr != 1 else ''}" if n_kr else "Keine offene Krise") + " →"),
              karte("wallet", "Finanzen", sa.PFAD + f"teilstaat/finanzen/?ziel={schl}",
                    [f"Staatskasse: <strong>{esc(mark(kasse['saldo']))}</strong>"] + ([f"Verteidigungskasse: <strong>{esc(mark(vtk['saldo']))}</strong>"] if vtk else [])
                    + [f"Gold: <strong>{kg / 1000:,.1f} t</strong>".replace(",", "X").replace(".", ",").replace("X", ".")],
                    "Haushaltsnotlage" + (" – offen" if in_not else ": keine") + " →")]
    karten = [c for c, b in zip(karten, (sieht["etat"], sieht["entwicklung"] or sieht["energie"] or sieht["krisen"], sieht["finanzen"])) if b]
    if verteidigung.darf_sehen(con, k, sid) and vtk:
        karten.append(karte("shield", "Verteidigung", sa.PFAD + f"verteidigung/{sid}/",
                            [f"Einsatzbereitschaft: <strong>{'–' if b is None else etatplan._de(b, 0) + ' %'}</strong>", f"{kzv['einheiten']:,} Einheiten".replace(",", ".")], "Bestand und Beschaffung →"))
    gw, gs = (rk["wert"], rk["stufe"]) if rk else (zuf["neu"], zuf["stufe"])
    zuf_block = (f'<div class="zf-kopf {etatplan._zf_klasse(gw)}" style="margin:12px 0"><div><div class="zf-wert">{etatplan._de(gw, 0)} <small>/ 100</small></div>'
                 f'<div class="zf-stufe">{esc(gs)}</div></div><div class="zf-gross"><div class="zf-meta">Bevölkerungszufriedenheit (alles zusammen gerechnet)</div>'
                 f'{etatplan.zuf_balken(gw)}<div class="zf-skala"><span style="left:0%">0</span><span style="left:40%">40</span><span style="left:55%">55</span>'
                 f'<span style="left:70%">70</span><span style="left:85%">85</span><span style="left:100%">100</span></div>'
                 f'<div class="zf-meta"><a href="{sa.PFAD}etatverteilung/?ziel={schl}">Woraus sie besteht: Etat → Wirkung</a></div></div></div>')
    if not sieht["entwicklung"]:
        zuf_block = ""
    inhalt = ((kopf_mit_wappen(f'<h1>{amt.ic("flag")} {esc(x["name"])}</h1>', sid, x["name"]) + amt.meldung(request) if kopf else "") +
              f'<p class="az">Die Lage Ihres Teilstaats auf einen Blick. Die Reiter oben führen zu Etat, Land (Entwicklung, Energie, Krisen), Finanzen und Verteidigung.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              + etatplan.ZUF_CSS + zuf_block +
              (f'<h2>Auf einen Blick</h2><div class="sa-todo">{"".join(z)}</div>' if z else "") +
              (f'<h2>Bereiche</h2><div class="ts-karten">{"".join(karten)}</div>' if karten else
               '<p class="sa-hinweis">Für weitere Bereiche dieses Teilstaats haben Sie keine Befugnis. Befugnisse vergibt der Regent.</p>'))
    return inhalt


@sa.seite("ts")
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
    kasse = regiert[sid]
    inhalt = await ueberblick(request, k, con, sid, kasse)
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


def land_teile(request, k, con, sid, schl):
    """Abschnitte des Reiters „Land“ (Entwicklung, Energie, Krisen) – auch für die RP-Leitung."""
    import aufkommen
    import energie
    import entwicklung
    import etatplan
    import krisen
    liste = aufkommen.berechnen(con, periode=etatplan.monat_heute())
    ziele = etatplan.ziele(con, liste)
    n_kr = krisen.offene_anzahl(con, schl)
    import befugnisse
    sieht = lambda b: befugnisse.darf_sehen(con, k, sid, b)   # eingestellte Personen: nur Abschnitte mit Befugnis
    teile = ([("entwicklung", "users", "Entwicklung", entwicklung.rumpf(request, k, con, liste, schl, ziele, True), False)] if sieht("entwicklung") else []) + \
            ([("energie", "zap", "Energie", energie._seitenhtml(request, k, con, schl, True), False)] if sieht("energie") else []) + \
            ([("krisen", "triangle-alert", f"Krisen ({n_kr})" if n_kr else "Krisen", krisen.rumpf(request, k, con, schl, True), bool(n_kr))] if sieht("krisen") else [])
    if n_kr and teile and teile[-1][0] == "krisen":
        teile.insert(0, teile.pop())   # offene Krisen zuerst: Handlungszwang
    return teile


@sa.seite("ts")
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
    teile = land_teile(request, k, con, sid, schl)
    if not teile:
        return sa.ts_bereich(request, k, con, schl, "entwicklung")
    name = esc(kasse["name"].replace("Staatskasse ", ""))
    inhalt = (kopf_mit_wappen(f'<h1>{amt.ic("users")} Land · {name}</h1>', sid, name) + amt.meldung(request) +
              '<p class="az">Wie sich der Teilstaat langfristig entwickelt: Bevölkerung und Wirtschaft (Entwicklung), die Energieversorgung und Krisen, auf die der Landesherr reagieren muss. '
              'Alles folgt aus dem Etat; die Werte ändern sich nur allmählich.</p>' + _abschnitte(None, teile))
    return sa.ant(request, k, "Land", "sa-ts-land", inhalt)


def fin_teile(request, k, con, sid, kasse):
    """Abschnitte des Reiters „Finanzen“ (Kassen, Gold, Notlage, Umsätze) – auch für die RP-Leitung."""
    import aufkommen
    import etatplan
    import gold
    import notlage
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
    return teile


@sa.seite("ts")
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
    nein = sa.ts_bereich(request, k, con, schl, "finanzen")
    if nein is not None:
        return nein
    teile = fin_teile(request, k, con, sid, kasse)
    name = esc(kasse["name"].replace("Staatskasse ", ""))
    inhalt = (kopf_mit_wappen(f'<h1>{amt.ic("wallet")} Finanzen · {name}</h1>', sid, name) + amt.meldung(request) +
              '<p class="az">Das Geld des Teilstaats: Kassen, Abgabe an das Reich, Goldreserven, die Lage bei einem Minus und die letzten Buchungen.</p>' + _abschnitte(None, teile))
    return sa.ant(request, k, "Finanzen", "sa-ts-fin", inhalt)


def _regent_kopf(request, k):
    """(con, sid, kasse) des Teilstaats aus ?ziel=, den das Konto WIRKLICH regiert – sonst None."""
    con = request.app["db"]
    ziel = request.query.get("ziel", "") or ""
    regent = {r["stelle"][3:]: r for r in geld.regierte_staatskassen(con, k)}
    if not regent:
        return None
    sid = ziel[3:] if ziel.startswith("ts-") and ziel[3:] in regent else next(iter(regent))
    return con, sid, regent[sid], regent


def gehoert_zu(con, m, sid, vorhanden=None):
    """Erscheint die Schatzamts-Angehörige m unter den eingestellten Personen dieses Teilstaats?
    Ja, wenn sie dessen Fraktionsrolle trägt (vom Regenten für diesen Teilstaat eingestellt, z. B. Privatsekretärin Hauer: von der Hand des Kaisers in
    seiner Funktion als Regent von Pfalz-Bayern als Landesinspektorin eingestellt), wenn sie hier schon Befugnisse hat (damit man sie entziehen kann), oder – nur in Teilstaaten ohne eigene Fraktion, die der Kronkanzler
    verwaltet – wenn sie keinem Teilstaat angehört (vom Reich eingestellt). Personen eines anderen Teilstaats erscheinen nicht."""
    import befugnisse
    import karte
    import verteidigung
    if vorhanden is None:
        vorhanden = befugnisse.liste(con, sid)
    if m["id"] in vorhanden:
        return True
    eigene = verteidigung.staaten_von(con, m["rollen"])
    if sid in eigene:
        return True
    st = next((x for x in karte.aktuell(con)["stand"]["staaten"] if x["id"] == sid), None)
    return not eigene and bool(st) and not st.get("fraktion")


@sa.seite("staat")
async def einstellungen(request, k):
    """Mein Teilstaat → Einstellungen: der Regent gibt eingestellten Personen (Schatzamt) einzelne Befugnisse für diesen Teilstaat."""
    import befugnisse
    kp = _regent_kopf(request, k)
    if not kp:
        return sa.ant(request, k, "Einstellungen", "sa-ts-einst", f'<h1>{amt.ic("settings")} Einstellungen</h1><div class="hinweis">Die Einstellungen eines Teilstaats sind dem Regenten vorbehalten.</div>', 403)
    con, sid, kasse, regent = kp
    schl = "ts-" + sid
    name = esc(kasse["name"].replace("Staatskasse ", ""))
    vorhanden = befugnisse.liste(con, sid)
    alle_m = await request.app["discord"].mitglieder()
    vollm = {kid for kid, w in vorhanden.items() if befugnisse.VOLLMACHT in w}
    personen = sorted((m for m in alle_m if m["id"] in vollm or (befugnisse.SCHATZAMT_ROLLE in m["rollen"] and gehoert_zu(con, m, sid, vorhanden))),
                      key=lambda m: (m["id"] in vollm, m["name"].lower()))
    wahl = ""
    if len(regent) > 1:
        opt = "".join(f'<option value="{sa.PFAD}teilstaat/einstellungen/?ziel=ts-{esc(s_)}"{" selected" if s_ == sid else ""}>{esc(r["name"].replace("Staatskasse ", ""))}</option>' for s_, r in regent.items())
        wahl = f'<p><select aria-label="Teilstaat wählen" onchange="location.href=this.value">{opt}</select></p>'
    import verteidigung
    bloecke = []
    for m in personen:
        roh = vorhanden.get(m["id"], set())
        bev = m["id"] in vollm
        ist_sa = befugnisse.SCHATZAMT_ROLLE in m["rollen"]
        eigen = ist_sa and sid in verteidigung.staaten_von(con, m["rollen"])
        mein = befugnisse.wirksam(roh, eigen)
        zeilen = []
        for b, (t, le, be) in befugnisse.BEREICHE.items():
            def haken(recht, text, art):
                if not text:
                    return '<span class="az" style="margin:0">–</span>'
                return (f'<label class="sa-haken" style="margin:0"><input type="checkbox" name="recht" value="{recht}" data-b="{b}" data-art="{art}"'
                        f'{" checked" if recht in mein else ""}><span>{esc(text)}</span></label>')
            zeilen.append((f'<b>{esc(t)}</b>', haken(b + ":lesen", le, "l"), haken(b, be, "b")))
        stand = ("" if befugnisse.GESETZT in roh else
                 '<p class="sa-hinweis">Noch nicht festgelegt: es gilt der Grundzugang (Etat, Entwicklung, Energie und Krisen ansehen). Mit „Speichern“ gilt nur noch, was angehakt ist.</p>'
                 if eigen else "")
        if bev and not any(r in befugnisse.GUELTIG for r in roh):
            stand += '<p class="sa-hinweis">Bevollmächtigt, aber noch ohne Befugnisse: Haken setzen und speichern, damit die Person etwas sehen oder bearbeiten kann.</p>'
        marke = (' <span class="ts-marke">Bevollmächtigt' + ("" if ist_sa else " · nicht im Schatzamt") + "</span>") if bev else ""
        widerruf = (f'<button class="btn zweit" type="submit" formaction="{sa.PFAD}teilstaat/einstellungen/vollmacht" name="aktion" value="widerrufen" '
                    f'onclick="return confirm(\'Vollmacht von {esc(m["name"])} widerrufen? Alle Befugnisse in diesem Teilstaat entfallen.\')">{amt.ic("user-x")}Vollmacht widerrufen</button>') if bev else ""
        bloecke.append(f'<section class="ts-bef" id="bef-{esc(m["id"])}"><h3>{amt.ic("user")} {esc(m["name"])}{marke}</h3>{stand}'
                       f'<form method="post" action="{sa.PFAD}teilstaat/einstellungen/speichern">{amt.csrf_feld(request)}<input type="hidden" name="ziel" value="{esc(schl)}">'
                       f'<input type="hidden" name="person" value="{esc(m["id"])}">'
                       + amt.tabelle(["Bereich", "Ansehen", "Bearbeiten"], zeilen)
                       + f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button>'
                       f'<button class="btn zweit" type="submit" name="alle_entziehen" value="1" onclick="return confirm(\'Alle Befugnisse von {esc(m["name"])} in diesem Teilstaat entziehen?\')">{amt.ic("x")}Alles entziehen</button>{widerruf}</div></form></section>')
    js = ("<script>document.querySelectorAll('.ts-bef input[data-b]').forEach(function(i){i.addEventListener('change',function(){"
          "var f=i.form,b=i.getAttribute('data-b');if(i.getAttribute('data-art')==='b'&&i.checked){var l=f.querySelector('input[data-b=\"'+b+'\"][data-art=l]');if(l)l.checked=true}"
          "if(i.getAttribute('data-art')==='l'&&!i.checked){var x=f.querySelector('input[data-b=\"'+b+'\"][data-art=b]');if(x)x.checked=false}})})</script>")
    tab = ("".join(bloecke) + js if bloecke
           else '<p class="az">Für diesen Teilstaat ist noch niemand im Kaiserlichen Schatz- und Währungsamt eingestellt oder bevollmächtigt. Mit <code>/einstellen</code> in Discord stellen Sie Personen ein '
                'oder bevollmächtigen unten eine beliebige Person; hier geben Sie ihnen dann Befugnisse.</p>')
    tab = VOLLMACHT_CSS + '<h2>Eingestellte und bevollmächtigte Personen</h2>' + tab + _vollmacht_suche(request, schl, alle_m, {m["id"] for m in personen}, k)
    inhalt = (kopf_mit_wappen(f'<h1>{amt.ic("settings")} Einstellungen · {name}</h1>', sid, name) + amt.meldung(request) +
              '<p class="az">Hier legen Sie für jede im Schatz- und Währungsamt eingestellte Person einzeln fest, welche Bereiche Ihres Teilstaats sie ansehen und bearbeiten darf. '
              'Bearbeiten schließt Ansehen ein. Die Befugnisse gelten nur für diesen Teilstaat; Sie können sie jederzeit ändern oder entziehen. '
              'Ohne Befugnis sieht die Person den Bereich nicht. Über die Kassen selbst (Überweisungen) verfügt weiterhin nur der Regent.</p>' + wahl + tab)
    return sa.ant(request, k, "Einstellungen", "sa-ts-einst", inhalt)


amt.ICONS.setdefault("user-plus", '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" x2="19" y1="8" y2="14"/><line x1="22" x2="16" y1="11" y2="11"/>')
amt.ICONS.setdefault("user-x", '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="17" x2="22" y1="8" y2="13"/><line x1="22" x2="17" y1="8" y2="13"/>')
VOLLMACHT_CSS = ('<style>.ts-marke{display:inline-block;margin-left:8px;padding:2px 9px;border:1px solid var(--linie);border-radius:999px;font-size:12px;font-weight:500;vertical-align:middle}'
                 '.ts-vollmacht{margin-top:28px}</style>')


def _vollmacht_suche(request, schl, alle_m, gelistet, k):
    """Suchfeld „Person bevollmächtigen“: beliebige Discord-Nutzer per Name (oder ID) finden und bevollmächtigen."""
    q = (request.query.get("q") or "").strip()[:60]
    treffer = ""
    if q:
        ql = q.lower()
        gef = [m for m in alle_m if (ql in m["name"].lower() or q == m["id"]) and m["id"] not in gelistet and m["id"] != k["id"]]
        gef.sort(key=lambda m: (not m["name"].lower().startswith(ql), m["name"].lower()))
        zeilen = [(f'{amt.ic("user")} {esc(m["name"])}', '<span class="az" style="margin:0">Schatzamt</span>' if befugnisse_rolle(m) else "",
                   f'<form method="post" action="{sa.PFAD}teilstaat/einstellungen/vollmacht" style="margin:0">{amt.csrf_feld(request)}'
                   f'<input type="hidden" name="ziel" value="{esc(schl)}"><input type="hidden" name="person" value="{esc(m["id"])}">'
                   f'<button class="btn" type="submit" name="aktion" value="erteilen">{amt.ic("user-plus")}Bevollmächtigen</button></form>') for m in gef[:15]]
        treffer = (amt.tabelle(["Discord-Nutzer", "", ""], zeilen, f"Niemand gefunden für „{esc(q)}“ (bereits gelistete Personen erscheinen nicht).")
                   + (f'<p class="az">{len(gef) - 15} weitere Treffer – bitte genauer suchen.</p>' if len(gef) > 15 else ""))
    return ('<section class="ts-bef ts-vollmacht"><h2>' + amt.ic("user-plus") + ' Person bevollmächtigen</h2>'
            '<p class="az">Sie können jede Person unseres Discord-Servers für Ihren Teilstaat bevollmächtigen, auch ohne Einstellung im Schatz- und Währungsamt. '
            'Nach der Vollmacht legen Sie wie oben fest, welche Bereiche sie ansehen und bearbeiten darf – ohne Haken sieht sie nichts.</p>'
            f'<form class="sa-leiste" method="get" action="{sa.PFAD}teilstaat/einstellungen/"><input type="hidden" name="ziel" value="{esc(schl)}">'
            f'<div><label for="vm-q">Name suchen</label><input type="search" id="vm-q" name="q" value="{esc(q)}" placeholder="Discord-Name" autocomplete="off" required minlength="2"></div>'
            f'<button class="btn zweit" type="submit">{amt.ic("search")}Suchen</button></form>{treffer}</section>')


def befugnisse_rolle(m):
    import befugnisse
    return befugnisse.SCHATZAMT_ROLLE in m["rollen"]


@sa.seite("staat")
async def vollmacht(request, k):
    """Vollmacht erteilen oder widerrufen (nur der Regent des Teilstaats)."""
    import befugnisse
    form = await sa.formular(request)
    ziel = str(form.get("ziel", ""))
    con = request.app["db"]
    regent = {r["stelle"]: r for r in geld.regierte_staatskassen(con, k)}
    if ziel not in regent:
        raise web.HTTPForbidden(text="Nur der Regent des Teilstaats darf Vollmachten erteilen.")
    zurueck = f"{sa.PFAD}teilstaat/einstellungen/?ziel={ziel}"
    sid, person = ziel[3:], str(form.get("person", ""))
    m = next((x for x in await request.app["discord"].mitglieder() if x["id"] == person), None)
    land = regent[ziel]["name"].replace("Staatskasse ", "")
    if form.get("aktion") == "widerrufen":
        if not befugnisse.bevollmaechtigt(con, sid, person):
            sa.weiter(zurueck, "Diese Person ist nicht bevollmächtigt.", True)
        befugnisse.widerrufen(con, sid, person)
        name = m["name"] if m else person
        geld.protokoll(con, k, "Vollmacht", f"{ziel}: Vollmacht von {name} widerrufen")
        con.commit()
        sa.dm(request, person, f"🔒 **Vollmacht widerrufen** – {k['name']} hat deine Vollmacht für **{land}** im Schatzamt widerrufen.", art="vollmacht")
        sa.weiter(zurueck, f"Vollmacht von {name} widerrufen.")
    if not m:
        sa.weiter(zurueck, "Diese Person ist nicht (mehr) auf unserem Discord-Server.", True)
    if person == k["id"]:
        sa.weiter(zurueck, "Sie regieren diesen Teilstaat bereits selbst.", True)
    befugnisse.bevollmaechtigen(con, sid, person, k["name"])
    geld.protokoll(con, k, "Vollmacht", f'{ziel}: {m["name"]} bevollmächtigt')
    con.commit()
    sa.dm(request, person, f"🖋️ **Vollmacht erteilt** – {k['name']} hat dich für **{land}** im Schatzamt bevollmächtigt. "
                                            f"Welche Bereiche du ansehen und bearbeiten darfst, legt der Regent fest: {amt.config.SITE_URL}{sa.PFAD}", art="vollmacht")
    sa.weiter(zurueck + f"#bef-{person}", f'{m["name"]} ist bevollmächtigt. Jetzt die Befugnisse festlegen und speichern.')


@sa.seite("staat")
async def einstellungen_speichern(request, k):
    import befugnisse
    form = await sa.formular(request)
    ziel = str(form.get("ziel", ""))
    con = request.app["db"]
    regent = {r["stelle"] for r in geld.regierte_staatskassen(con, k)}
    if ziel not in regent:
        raise web.HTTPForbidden(text="Nur der Regent des Teilstaats darf Befugnisse vergeben.")
    person = str(form.get("person", ""))
    m = next((x for x in await request.app["discord"].mitglieder() if x["id"] == person), None)
    bev = bool(m) and befugnisse.bevollmaechtigt(con, ziel[3:], person)
    if not m or (befugnisse.SCHATZAMT_ROLLE not in m["rollen"] and not bev):
        sa.weiter(f"{sa.PFAD}teilstaat/einstellungen/?ziel={ziel}", "Diese Person ist weder im Schatz- und Währungsamt eingestellt noch bevollmächtigt.", True)
    rechte = [] if form.get("alle_entziehen") else [r for r in form.getall("recht", []) if r in befugnisse.GUELTIG]
    rechte += [r + ":lesen" for r in rechte if ":" not in r and befugnisse.BEREICHE[r][1] and r + ":lesen" not in rechte]   # Bearbeiten schließt Ansehen ein
    if rechte and not bev and not gehoert_zu(con, m, ziel[3:]):
        sa.weiter(f"{sa.PFAD}teilstaat/einstellungen/?ziel={ziel}", f'{m["name"]} ist für einen anderen Teilstaat eingestellt.', True)
    befugnisse.setzen(con, ziel[3:], person, rechte, k["name"])
    geld.protokoll(con, k, "Befugnisse", f'{ziel}: {m["name"]} → ' + (", ".join(befugnisse.recht_name(r) for r in sorted(rechte)) or "keine Befugnisse"))
    con.commit()
    sa.weiter(f"{sa.PFAD}teilstaat/einstellungen/?ziel={ziel}", f'Befugnisse von {m["name"]} gespeichert.')


async def statistiken_alt(request):
    raise web.HTTPFound(sa.PFAD + "statistiken/")   # die Statistiken sind jetzt öffentlich (etatplan.statistiken)


def registrieren(app):
    app.router.add_get(sa.PFAD + "wappen/{sid}.png", wappen)
    app.router.add_get(PFAD, seite)
    app.router.add_get(PFAD + "land/", land)
    app.router.add_get(PFAD + "finanzen/", finanzen)
    app.router.add_get(PFAD + "einstellungen/", einstellungen)
    app.router.add_post(PFAD + "einstellungen/speichern", einstellungen_speichern)
    app.router.add_post(PFAD + "einstellungen/vollmacht", vollmacht)
    app.router.add_get(PFAD + "statistiken/", statistiken_alt)
