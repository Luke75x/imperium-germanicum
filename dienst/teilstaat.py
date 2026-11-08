"""Mein Teilstaat (/schatzamt/teilstaat/): Überblick über alles, was ein Landesherr für seinen Teilstaat braucht – Handlungsbedarf (Etat einreichen,
Haushaltsnotlage, Militär), Kassen, geltender Etat, Reichsabgabe, letzte Umsätze. Die übrigen Reiter (Etat, Etat planen, Verteidigung, Haushaltsnotlage,
Kasse & Umsätze) sind bestehende Seiten, die dieselbe Reiterleiste tragen (schatzamt.reiter_html); die Seitenleiste hat nur den Eintrag „Mein Teilstaat“.
Sichtbar für alle, die einen Teilstaat regieren (geld.regierte_staatskassen); mehrere Teilstaaten (Kanzler) wählt man oben aus.
"""
import amt
import geld
import schatzamt as sa
from geld import mark

esc = amt.esc
PFAD = sa.PFAD + "teilstaat/"


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

    # Kassen
    kassen = [kasse] + ([vtk] if vtk else [])
    zusatz = sa._kassen_zusatz(con, [kasse])

    # Geltender Etat
    anteile = etatplan.runden100(etatplan.aktuelle(con, schl, liste, monat))
    betr = x["verteilung_land"]
    zeilen = [("Abgabe an das Reich", "–", geld.mark_kurz(x["reich"]))]
    v, r_zeile = etatplan.zeilenwerte(anteile, x["rl_satz_land"])   # Politikfelder und Rücklage als Zeilen, zusammen 100 % des eigenen Etats
    zeilen += [(esc(etatplan.NAMEN[kat]), f'{etatplan._de(v[kat])} %', geld.mark_kurz(betr[kat])) for kat, _ in etatplan.KATEGORIEN]
    rl = x["land"] - x["pool_land"]
    zeilen.append(("Rücklage der Staatskasse" if rl >= 0 else "Rücklage (Entnahme aus der Staatskasse)", f'{etatplan._de(r_zeile)} %', geld.mark_kurz(rl)))
    etat = amt.tabelle(["Posten", "Anteil am eigenen Etat", "Betrag / Monat"], zeilen, klasse="sa-haushalt")

    umsatz = amt.tabelle(sa.UMSATZ_KOPF, sa.umsatz_zeilen(con, kasse["id"], sa.umsaetze(con, kasse["id"], 6)), "Noch keine Umsätze.")
    inhalt = (f'<h1>{amt.ic("flag")} {esc(x["name"])}</h1>{amt.meldung(request)}'
              f'<p class="az">Alles zum eigenen Teilstaat an einem Ort. Oben wechseln Sie zwischen Etat, Etat planen, Verteidigung, Haushaltsnotlage und Kasse.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              f'<h2>Auf einen Blick</h2><div class="sa-todo">{"".join(z)}</div>'
              f'<div class="sa-spalten"><div><h2>Kassen</h2><div class="sa-karten">{sa._karten(kassen, zusatz)}</div></div>'
              f'<div><h2>Reichsabgabe</h2><p class="sa-hinweis">Der Teilstaat gibt <b>{esc(abgabe)}</b> seines Steueraufkommens an das Reich ab ({esc(mark(x["reich"]))} im Monat), höchstens '
              f'{esc(str(geld.einstellung(con, "aufkommen").get("quote_max", 33)))} %'
              + (f'. Ohne diese Obergrenze wären es <b>{etatplan._de(x["quote_theorie"])} %</b> ({esc(mark(x["reich_theorie"]))}).' if q + 0.05 < x["quote_theorie"] else ".")
              + f' Die Berechnung steht unter <a href="{sa.PFAD}haushalt/">Reichshaushalt</a>.</p></div></div>'
              f'<h2>Geltender Etat im {esc(sa._monatsname(monat))}</h2>{etat}'
              f'<p><a href="{sa.PFAD}etatverteilung/?ziel={schl}">Diagramm, Boni und Mali, Zufriedenheit →</a></p>'
              f'<h2>Letzte Umsätze · {esc(kasse["name"])}</h2>{umsatz}<p><a href="{sa.PFAD}konto/?konto={kasse["id"]}">Alle Umsätze und Kontoauszüge →</a></p>')
    return sa.ant(request, k, "Mein Teilstaat", "sa-teilstaat", inhalt)


def registrieren(app):
    app.router.add_get(PFAD, seite)
