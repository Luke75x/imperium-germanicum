"""Goldreserven der Teilstaaten und der Zentralbank.

Bestand in kg (gr_bestand je Stelle: 'ts-<sid>' Staatskasse eines Teilstaats, 'zentralbank' Reichsgoldreserve der Reichsgebiete);
jede Bewegung in gr_buchungen. Erstausstattung: werkzeuge/goldreserven.py (Goldbestände der Nationalbanken nach World Gold Council,
anteilig nach dem BIP-Anteil der Gebiete am jeweiligen Land).
Bewertung: kg × Goldpreis (€/kg, Einstellung „gold“) × Spielmaßstab (Kr je Mio. €, wie beim Steueraufkommen) – Gold ist Vermögen, kein Geld.
Handel nur mit der Zentralbank: Verkauf → Zentralbank zahlt den Gegenwert in Kronen auf die Staatskasse (Geldschöpfung, goldgedeckt),
Kauf → Staatskasse zahlt an die Zentralbank (Geld verlässt den Umlauf). Ankaufsabschlag/Verkaufsaufschlag je 1 % (Einstellung).
Berechtigt: Landesherr für die eigene Staatskasse (geld.regierte_staatskassen), Leitung des Schatzamts für alle; Goldpreis setzt die Leitung.
Seite /schatzamt/gold/ (öffentlich: Bestände, Wert, Golddeckung der Krone).
"""
import time

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa
from geld import mark

esc = amt.esc
PFAD = sa.PFAD

SCHEMA = """
CREATE TABLE IF NOT EXISTS gr_bestand (stelle TEXT PRIMARY KEY, name TEXT NOT NULL, kg REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS gr_buchungen (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, stelle TEXT NOT NULL, kg REAL NOT NULL,
    art TEXT NOT NULL, betrag INTEGER NOT NULL DEFAULT 0, preis_kg REAL NOT NULL DEFAULT 0, zweck TEXT NOT NULL DEFAULT '', autor_name TEXT NOT NULL);
"""
ARTEN = {"erstausstattung": "Erstausstattung", "verkauf": "Verkauf an die Zentralbank", "kauf": "Kauf von der Zentralbank"}


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def preis(con):
    return float(geld.einstellung(con, "gold")["preis_kg"])


def massstab(con):
    return float(str(geld.einstellung(con, "aufkommen")["massstab"]).replace(",", "."))


def wert(con, kg, faktor=1.0):
    """Gegenwert von kg Gold in Heller (Spielmaßstab)."""
    return int(round(kg * preis(con) * massstab(con) / 1e6 * 100 * faktor))


def bestand(con, stelle):
    r = con.execute("SELECT kg FROM gr_bestand WHERE stelle=?", (stelle,)).fetchone()
    return r["kg"] if r else 0.0


def _bewegen(con, stelle, name, kg, art, betrag, k, zweck=""):
    con.execute("INSERT INTO gr_bestand (stelle, name, kg) VALUES (?,?,?) ON CONFLICT(stelle) DO UPDATE SET kg=kg+excluded.kg", (stelle, name, kg))
    con.execute("INSERT INTO gr_buchungen (zeit, stelle, kg, art, betrag, preis_kg, zweck, autor_name) VALUES (?,?,?,?,?,?,?,?)",
                (int(time.time()), stelle, kg, art, betrag, preis(con), zweck, k["name"]))


def handeln(con, kasse, kg, verkaufen, k):
    """Verkauft (verkaufen=True) bzw. kauft kg Gold für die Staatskasse `kasse` (gk_konten-Zeile). Gibt den Betrag (Heller) zurück."""
    g = geld.einstellung(con, "gold")
    kg = round(kg, 3)
    if kg <= 0:
        raise geld.Fehler("Bitte eine Menge über 0 kg angeben.")
    zb = geld.sonder(con, "zentralbank")
    if verkaufen:
        if bestand(con, kasse["stelle"]) < kg:
            raise geld.Fehler(f"Nicht genug Gold: Bestand {bestand(con, kasse['stelle']):,.1f} kg.".replace(",", "X").replace(".", ",").replace("X", "."))
        betrag = wert(con, kg, 1 - float(g["abschlag"]) / 100)
        geld.buchen(con, zb["id"], kasse["id"], betrag, "goldverkauf", f"Verkauf von {kg:g} kg Gold an die Zentralbank", k, bezug="GOLD")
        _bewegen(con, kasse["stelle"], kasse["name"], -kg, "verkauf", betrag, k)
        _bewegen(con, "zentralbank", "Zentralbank des Reiches", kg, "kauf", betrag, k, f"Ankauf von {kasse['name']}")
    else:
        if bestand(con, "zentralbank") < kg:
            raise geld.Fehler("Die Zentralbank hält nicht genug Gold.")
        betrag = wert(con, kg, 1 + float(g["abschlag"]) / 100)
        geld.buchen(con, kasse["id"], zb["id"], betrag, "goldkauf", f"Kauf von {kg:g} kg Gold von der Zentralbank", k, bezug="GOLD")
        _bewegen(con, kasse["stelle"], kasse["name"], kg, "kauf", betrag, k)
        _bewegen(con, "zentralbank", "Zentralbank des Reiches", -kg, "verkauf", betrag, k, f"Abgabe an {kasse['name']}")
    geld.protokoll(con, k, "Goldverkauf" if verkaufen else "Goldkauf", f"{kasse['name']}: {kg:g} kg für {mark(betrag)}")
    return betrag


def _kg(x):
    return f"{x:,.1f} kg".replace(",", "X").replace(".", ",").replace("X", ".")


def _t(x):
    return f"{x / 1000:,.2f} t".replace(",", "X").replace(".", ",").replace("X", ".")


@sa.seite()
async def seite(request, k):
    con = request.app["db"]
    rows = con.execute("SELECT * FROM gr_bestand ORDER BY kg DESC").fetchall()
    gesamt = sum(r["kg"] for r in rows)
    menge = geld.geldmenge(con)
    gw = wert(con, gesamt)
    g = geld.einstellung(con, "gold")
    eigene = {r["stelle"]: r for r in geld.regierte_staatskassen(con, k)}
    if geld.ist_leitung(k):
        eigene.update({r["stelle"]: r for r in con.execute("SELECT * FROM gk_konten WHERE art='teilstaat'")})
    kz = [("Goldreserven gesamt", _t(gesamt)), ("Wert", mark(gw)), ("Golddeckung der Krone", f"{gw / menge * 100:.1f} %".replace(".", ",") if menge else "–"),
          ("Goldpreis", f"{preis(con):,.0f} € je kg".replace(",", "."))]
    zeilen = [(esc(r["name"]), _t(r["kg"]), mark(wert(con, r["kg"])), f"{r['kg'] / gesamt * 100:.1f} %".replace(".", ",") if gesamt else "–") for r in rows]
    handel = ""
    if eigene:
        opts = "".join(f'<option value="{r["id"]}">{esc(r["name"])} · {_kg(bestand(con, s))} · {mark(r["saldo"])}</option>' for s, r in sorted(eigene.items(), key=lambda x: x[1]["name"]))
        handel = (f'<h2>Gold handeln</h2><form class="sa-formular" method="post" action="{PFAD}gold/handeln">{amt.csrf_feld(request)}<div class="zeilen">'
                  f'<div><label for="ka">Staatskasse</label><select id="ka" name="kasse">{opts}</select></div>'
                  '<div><label for="kg">Menge (kg)</label><input type="text" id="kg" name="kg" required inputmode="decimal"></div>'
                  '<div><label for="ri">Geschäft</label><select id="ri" name="richtung"><option value="verkauf">An die Zentralbank verkaufen</option>'
                  '<option value="kauf">Von der Zentralbank kaufen</option></select></div></div>'
                  f'<p class="sa-hinweis">1 kg entspricht derzeit {mark(wert(con, 1))}. Die Zentralbank kauft mit {g["abschlag"]} % Abschlag an und verkauft mit '
                  f'{g["abschlag"]} % Aufschlag. Ein Verkauf bringt neues, goldgedecktes Geld in die Staatskasse.</p>'
                  f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Ausführen</button></div></form>')
    preisform = ""
    if geld.ist_leitung(k):
        preisform = (f'<h2>Goldpreis festsetzen</h2><form class="sa-leiste" method="post" action="{PFAD}gold/preis">{amt.csrf_feld(request)}'
                     f'<div><label for="p">€ je kg</label><input type="text" id="p" name="preis" value="{preis(con):.0f}"></div>'
                     f'<div><label for="a">Ab-/Aufschlag %</label><input type="text" id="a" name="abschlag" value="{esc(str(g["abschlag"]))}"></div>'
                     f'<button class="btn zweit" type="submit">Speichern</button></form>')
    bew = con.execute("SELECT * FROM gr_buchungen WHERE art!='erstausstattung' ORDER BY id DESC LIMIT 30").fetchall()
    inhalt = (f'<h1>{amt.ic("coins")} Goldreserven</h1>{amt.meldung(request)}'
              '<p class="az">Goldbestände der Teilstaaten und der Zentralbank (Reichsgoldreserve der unmittelbaren Reichsgebiete). '
              'Ausgangsbestand nach den Goldreserven der Nationalbanken, anteilig nach der Wirtschaftsleistung der Gebiete.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>{handel}'
              '<h2>Bestände</h2>' + amt.tabelle(["Halter", "Bestand", "Wert", "Anteil"], zeilen, "Noch keine Goldreserven.") + preisform
              + '<h2>Letzte Goldgeschäfte</h2>' + amt.tabelle(["Zeit", "Halter", "Menge", "Geschäft", "Betrag", "Durch"],
                                                            [(amt._zeit(b["zeit"]), esc(b["stelle"]), _kg(b["kg"]), esc(ARTEN.get(b["art"], b["art"])), mark(b["betrag"]),
                                                              esc(b["autor_name"])) for b in bew], "Noch keine Geschäfte."))
    return sa.ant(request, k, "Goldreserven", "sa-gold", inhalt)


async def handeln_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    kasse = geld.konto(con, form.get("kasse")) if str(form.get("kasse", "")).isdigit() else None
    erlaubt = {r["id"] for r in geld.regierte_staatskassen(con, k)} | ({kasse["id"]} if kasse and geld.ist_leitung(k) and kasse["art"] == "teilstaat" else set())
    if not kasse or kasse["id"] not in erlaubt:
        sa.weiter(f"{PFAD}gold/", "Über diese Staatskasse darfst du nicht verfügen.", True)
    try:
        roh = str(form.get("kg", "")).replace(" ", "")
        kg = float(roh.replace(".", "").replace(",", ".") if "," in roh else roh)
        betrag = handeln(con, kasse, kg, form.get("richtung") != "kauf", k)
        con.commit()
    except (ValueError, geld.Fehler) as e:
        con.rollback()
        sa.weiter(f"{PFAD}gold/", str(e) if isinstance(e, geld.Fehler) else "Bitte eine gültige Menge angeben.", True)
    sa.weiter(f"{PFAD}gold/", f"{kg:g} kg Gold {'verkauft' if form.get('richtung') != 'kauf' else 'gekauft'} für {mark(betrag)}.")


async def preis_post(request):
    k = await anmeldung.konto(request)
    if not geld.ist_leitung(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    try:
        p = float(str(form.get("preis", "")).replace(".", "").replace(",", "."))
        a = geld.prozent_lesen(form.get("abschlag"))
        assert 1000 <= p <= 10_000_000 and a is not None
    except (ValueError, AssertionError):
        sa.weiter(f"{PFAD}gold/", "Bitte einen gültigen Goldpreis und Abschlag angeben.", True)
    geld.einstellung_setzen(con, "gold", {"preis_kg": round(p), "abschlag": a if a != int(a) else int(a)}, k)
    con.commit()
    sa.weiter(f"{PFAD}gold/", "Goldpreis festgesetzt.")


def finanzen_html(con):
    gesamt = con.execute("SELECT SUM(kg) FROM gr_bestand").fetchone()[0] or 0
    if not gesamt:
        return ""
    menge = geld.geldmenge(con)
    return (f'<h2>Goldreserven</h2><p class="az">{_t(gesamt)} Gold im Wert von {mark(wert(con, gesamt))}; Golddeckung der Krone '
            f'{((wert(con, gesamt) / menge * 100) if menge else 0):.1f} %'.replace(".", ",") + f'. <a href="{PFAD}gold/">Einzelheiten</a></p>')


def registrieren(app):
    einrichten(app["db"])
    geld.BUCHUNGSART.update({"goldverkauf": "Goldverkauf an die Zentralbank", "goldkauf": "Goldkauf von der Zentralbank"})
    r = app.router
    r.add_get(PFAD + "gold/", seite)
    r.add_post(PFAD + "gold/handeln", handeln_post)
    r.add_post(PFAD + "gold/preis", preis_post)
