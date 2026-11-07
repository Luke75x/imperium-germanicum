"""Etats der Reichsbehörden (/schatzamt/etats/, staatlich).

Die Behörden bekommen ihr Geld vom Reich: Haushaltszuweisungen aus der Reichskasse (Buchungsart „zuweisung“, bezug ETAT-JJJJ) auf ihr
Behördenkonto. Davon zahlen sie ihre Mitarbeiter (Lohnlauf, Zahlstelle „nach Dienststelle“ – besoldung.dienststelle).
Jahresetat je Stelle in der Einstellung „etats“ (Heller/Jahr). Vorgabe = Größenordnung der vergleichbaren deutschen Bundesbehörden
(Haushalt 2025) × 2,4 (Wirtschaftskraft des Reiches) ÷ Wechselkurs: Polizei (Bundespolizei + BKA) 11,7 Mrd. Kr, Zoll 6,9 Mrd.,
Katastrophenschutz (BBK + THW) 1,6 Mrd., Reichssicherheitsamt (BfV + BND) 3,4 Mrd., Inquisition 0,5 Mrd., Schatzamt 3,0 Mrd.,
Reichskanzlei 1,0 Mrd. Erstausstattung einmalig über werkzeuge/behoerden_etat.py. Zuweisen und Etat ändern: Leitung des Schatzamts
(dazu Kanzler/Kaiser).
"""
import time
from datetime import date

from aiohttp import web

import amt
import anmeldung
import geld
import notlage
import schatzamt as sa
from geld import mark

esc = amt.esc
PFAD = sa.PFAD
MRD = 100 * 10 ** 9
VORGABE = {"kanzlei": 1.0, "polizei": 11.7, "zoll": 6.9, "katastrophenschutz": 1.6, "krs": 3.4, "inquisition": 0.5, "schatzamt": 3.0}
geld.VORGABEN.setdefault("etats", {s: int(v * MRD) for s, v in VORGABE.items()})


def stellen():
    """[(Schlüssel, Name)] aller Stellen mit Etat: Reichskanzlei und Reichsbehörden."""
    return [("kanzlei", "Reichskanzlei")] + [(b["schl"], b["name"]) for b in amt.BEHOERDEN]


def etats(con):
    e = geld.einstellung(con, "etats")
    return {s: int(e.get(s, 0)) for s, _ in stellen()}


def zugewiesen(con, jahr=None):
    """{Konto-ID: Summe der Haushaltszuweisungen im Jahr}."""
    jahr = jahr or date.today().year
    von, bis = int(time.mktime((jahr, 1, 1, 0, 0, 0, 0, 0, -1))), int(time.mktime((jahr + 1, 1, 1, 0, 0, 0, 0, 0, -1)))
    return {r["an"]: r["s"] for r in con.execute("SELECT an, SUM(betrag) s FROM gk_buchungen WHERE art='zuweisung' AND zeit>=? AND zeit<? GROUP BY an",
                                                 (von, bis))}


def zuweisen(con, stelle, betrag, zweck, k, bezug=None):
    """Haushaltszuweisung aus der Reichskasse an die Stelle (Behörde/Reichskanzlei)."""
    ziel = geld.stellenkonto(con, stelle)
    if not ziel or ziel["art"] != "behoerde":
        raise geld.Fehler("Unbekannte Stelle.")
    kasse = geld.sonder(con, "reichskasse")
    if kasse["saldo"] < betrag:
        raise geld.Fehler(f'Die Reichskasse ist nicht gedeckt (verfügbar {mark(kasse["saldo"])}).')
    geld.buchen(con, kasse["id"], ziel["id"], betrag, "zuweisung", zweck, k, bezug=bezug or f"ETAT-{date.today().year}")
    geld.protokoll(con, k, "Haushaltszuweisung", f'{ziel["name"]}: {mark(betrag)} – {zweck}')
    return ziel


async def personalkosten(app, con):
    """{Zahlstelle: (Anzahl, Brutto je Monat)} nach dem aktuellen Stand der Besoldung (None, wenn Discord nicht erreichbar)."""
    import besoldung
    try:
        liste = await besoldung.berechnen(app, con)
    except Exception:
        return None
    out = {}
    for x in liste:
        n, b = out.get(x["zahlstelle"], (0, 0))
        out[x["zahlstelle"]] = (n + 1, b + x["brutto"])
    return out


def _monate(saldo, kosten):
    if not kosten:
        return "–"
    if saldo <= 0:
        return "erschöpft"
    m = saldo / kosten
    if m >= 1200:
        return "über 100 Jahre"
    return f"{m:,.0f} Monate".replace(",", ".") if m >= 24 else f"{m:,.1f} Monate".replace(".", ",")


@sa.seite("staat")
async def seite(request, k):
    con = request.app["db"]
    e = etats(con)
    zu = zugewiesen(con)
    pk = await personalkosten(request.app, con)
    jahr = date.today().year
    eigene = {r["id"] for r in geld.verfuegbare_konten(con, k)}
    karten, summe_kasse, summe_pk = [], 0, 0
    for schl, name in stellen():
        r = geld.stellenkonto(con, schl)
        if not r:
            continue
        n, kosten = (pk or {}).get(schl, (0, 0))
        summe_kasse += r["saldo"]
        summe_pk += kosten
        ist_mein = r["id"] in eigene
        zeilen = [("Jahresetat", geld.mark_kurz(e.get(schl, 0))), (f"Zugewiesen {jahr}", geld.mark_kurz(zu.get(r["id"], 0))),
                  ("Personalkosten / Monat", (f'{mark(kosten)}<br><span class="az">{n} Besoldete</span>' if n else "keine Besoldeten") if pk is not None else "–"),
                  ("Reicht für", _monate(r["saldo"], kosten) if pk is not None else "–")]
        karten.append(
            f'<div class="sa-karte{" sa-mein" if ist_mein else ""}"><small>{"In Ihrer Verfügung" if ist_mein else "Behördenkasse"}</small>'
            f'<div class="sa-name">{esc(name)}</div><div class="sa-saldo">{sa.betrag_html(r["saldo"], False, kurz=True)}</div>'
            + (f'<p class="az sa-zusatz sa-rot">⚠ Haushaltsnotlage seit {int((time.time() - f["seit"]) // 86400)} Tagen</p>' if (f := notlage.offener_fall(con, r["id"])) else "")
            + sa.werte_html(zeilen)
            + (f'<div class="sa-aktionen"><a class="btn zweit" href="{PFAD}konto/?konto={r["id"]}">{amt.ic("wallet")}Umsätze</a></div>' if ist_mein else "")
            + '</div>')
    kz = [("Etats gesamt / Jahr", mark(sum(e.values()))), ("In den Behördenkassen", mark(summe_kasse)),
          ("Personalkosten / Monat", mark(summe_pk) if pk is not None else "–"), (f"Zugewiesen {jahr}", mark(sum(zu.get(geld.stellenkonto(con, s)["id"], 0) for s, _ in stellen())))]
    verwaltung = ""
    if geld.ist_leitung(k):
        c = amt.csrf_feld(request)
        opts = "".join(f'<option value="{esc(s)}">{esc(n)}</option>' for s, n in stellen())
        felder = "".join(f'<div><label for="e-{esc(s)}">{esc(n)}</label><input type="text" id="e-{esc(s)}" name="{esc(s)}" '
                         f'value="{esc(mark(e.get(s, 0), einheit=False))}" inputmode="decimal"></div>' for s, n in stellen())
        verwaltung = (f'<h2>Haushaltszuweisung</h2><form class="sa-formular" method="post" action="{PFAD}etats/zuweisen">{c}<div class="zeilen">'
                      f'<div><label for="st">An</label><select id="st" name="stelle">{opts}</select></div>'
                      '<div><label for="bz">Betrag in Kronen</label><input type="text" id="bz" name="betrag" required inputmode="decimal"></div></div>'
                      f'<div><label for="zw">Zweck</label><input type="text" id="zw" name="zweck" maxlength="140" value="Haushaltszuweisung {jahr}" required></div>'
                      f'<p class="sa-hinweis">Geht aus der Reichskasse ({mark(geld.sonder(con, "reichskasse")["saldo"])}) an die Behördenkasse.</p>'
                      f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("arrow-right-left")}Zuweisen</button></div></form>'
                      f'<details class="sa-auf"><summary>{amt.ic("pencil")}Jahresetats ändern</summary>'
                      f'<form class="sa-formular" method="post" action="{PFAD}etats/">{c}<p class="sa-hinweis">Beträge in Kronen je Jahr. '
                      'Der Etat ist der Plan; Geld fließt erst mit einer Zuweisung.</p>'
                      f'<div class="zeilen">{felder}</div><div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button></div></form></details>')
    inhalt = (f'<h1>{amt.ic("landmark")} Etats der Behörden</h1>{amt.meldung(request)}'
              '<p class="az">Die Behörden erhalten ihr Geld vom Reich (Haushaltszuweisungen aus der Reichskasse) und zahlen davon ihre Mitarbeiter. '
              'Die Etats orientieren sich an vergleichbaren deutschen Bundesbehörden, hochgerechnet auf die Wirtschaftskraft des Reiches.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>'
              f'<div class="sa-karten">{"".join(karten)}</div>' + verwaltung)
    return sa.ant(request, k, "Etats der Behörden", "sa-etats", inhalt)


async def zuweisen_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    betrag = geld.betrag_lesen(form.get("betrag", ""))
    zweck = " ".join(str(form.get("zweck", "")).split())[:140]
    if not betrag or not zweck or form.get("stelle") not in dict(stellen()):
        sa.weiter(f"{PFAD}etats/", "Bitte Stelle, Betrag und Zweck angeben.", True)
    try:
        ziel = zuweisen(con, form["stelle"], betrag, zweck, k)
        con.commit()
    except geld.Fehler as e:
        con.rollback()
        sa.weiter(f"{PFAD}etats/", str(e), True)
    sa.weiter(f"{PFAD}etats/", f"{mark(betrag)} an {ziel['name']} zugewiesen.")


async def etats_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    neu = {}
    for s, n in stellen():
        roh = str(form.get(s, "")).strip()
        b = 0 if roh in ("", "0") else geld.betrag_lesen(roh)
        if b is None:
            sa.weiter(f"{PFAD}etats/", f"Ungültiger Betrag bei {n}.", True)
        neu[s] = b
    geld.einstellung_setzen(con, "etats", neu, k)
    con.commit()
    sa.weiter(f"{PFAD}etats/", "Jahresetats gespeichert.")


def registrieren(app):
    r = app.router
    r.add_get(PFAD + "etats/", seite)
    r.add_post(PFAD + "etats/", etats_post)
    r.add_post(PFAD + "etats/zuweisen", zuweisen_post)
