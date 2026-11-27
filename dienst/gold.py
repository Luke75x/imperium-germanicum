"""Goldreserven des Reiches, der Teilstaaten und der Zentralbank.

Bestand in kg (gr_bestand je Stelle: 'reichskasse' Gold des Reiches – dazu gehören die Reichsunmittelbaren Territorien, die kein Teilstaat sind –,
'ts-<sid>' Staatskasse eines Teilstaats, 'zentralbank' Ankäufe der Zentralbank);
jede Bewegung in gr_buchungen. Erstausstattung: werkzeuge/goldreserven.py (Goldbestände der Nationalbanken nach World Gold Council,
anteilig nach dem BIP-Anteil der Gebiete am jeweiligen Land).
Bewertung: kg × Goldpreis (€/kg, Einstellung „gold“) ÷ Wechselkurs (Echtmaßstab) – Gold ist Vermögen, kein Geld.
Handel nur mit der Zentralbank: Verkauf → Zentralbank zahlt den Gegenwert in Kronen auf die Staatskasse (Geldschöpfung, goldgedeckt),
Kauf → Staatskasse zahlt an die Zentralbank (Geld verlässt den Umlauf). Ankaufsabschlag/Verkaufsaufschlag je 1 % (Einstellung).
Berechtigt: Landesherr für die eigene Staatskasse (geld.regierte_staatskassen), Leitung des Schatzamts für alle und die Reichskasse;
Goldpreis setzt die Leitung.
RP-Leitung: Gold zwischen Teilstaaten/Reichskasse übertragen (umbuchen, Art „umbuchung“, ohne Geld) – Stellschrauben → Gold und Die Teilstaaten → Finanzen.
Seite /schatzamt/gold/ (staatlich – nur mit staatlichem Zugriff, sa.hat_staat: Bestände, Wert, Golddeckung der Krone).
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
amt.ICONS.setdefault("arrow-right-left", '<path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/>')

SCHEMA = """
CREATE TABLE IF NOT EXISTS gr_bestand (stelle TEXT PRIMARY KEY, name TEXT NOT NULL, kg REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS gr_buchungen (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit INTEGER NOT NULL, stelle TEXT NOT NULL, kg REAL NOT NULL,
    art TEXT NOT NULL, betrag INTEGER NOT NULL DEFAULT 0, preis_kg REAL NOT NULL DEFAULT 0, zweck TEXT NOT NULL DEFAULT '', autor_name TEXT NOT NULL);
"""
ARTEN = {"erstausstattung": "Erstausstattung", "verkauf": "Verkauf an die Zentralbank", "kauf": "Kauf von der Zentralbank", "umbuchung": "Umbuchung"}


def handelbar(con, k):
    """Kassen, für die das Konto Gold handeln darf: regierte Staatskassen; Leitung: alle Staatskassen und die Reichskasse."""
    out = {r["stelle"]: r for r in geld.regierte_staatskassen(con, k)}
    import befugnisse
    for sid in befugnisse.sids(con, k, "finanzen"):   # eingestellte Personen mit Befugnis „Finanzen bearbeiten“ (Mein Teilstaat → Einstellungen)
        r = geld.stellenkonto(con, "ts-" + sid)
        if r and not __import__("notlage").verfuegung_gesperrt(con, k, r["stelle"]):
            out[r["stelle"]] = r
    if geld.ist_leitung(k):
        out.update({r["stelle"]: r for r in con.execute("SELECT * FROM gk_konten WHERE art='teilstaat'")})
        out["reichskasse"] = geld.sonder(con, "reichskasse")
    return out


def einrichten(con):
    con.executescript(SCHEMA)
    con.commit()


def preis(con):
    return float(geld.einstellung(con, "gold")["preis_kg"])


def massstab(con):
    """Kronen je Mio. € (Echtmaßstab über den Wechselkurs)."""
    return 1e6 / geld.wechselkurs(con)


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


def halter(con):
    """{Stelle: Name} aller Goldhalter, zwischen denen die RP-Leitung umbuchen kann: Reichskasse und die Staatskassen der Teilstaaten."""
    out = {"reichskasse": geld.sonder(con, "reichskasse")["name"]}
    out.update({r["stelle"]: r["name"] for r in con.execute("SELECT stelle, name FROM gk_konten WHERE art='teilstaat' AND stelle LIKE 'ts-%' ORDER BY name")})
    return out


def umbuchen(con, von, nach, kg, grund, k):
    """RP-Leitung: überträgt kg Gold von Stelle `von` an Stelle `nach` (ohne Geld, kein Handel mit der Zentralbank)."""
    h = halter(con)
    kg = round(kg, 3)
    if von not in h or nach not in h:
        raise geld.Fehler("Unbekannte Kasse.")
    if von == nach:
        raise geld.Fehler("Absender und Empfänger müssen verschieden sein.")
    if kg <= 0:
        raise geld.Fehler("Bitte eine Menge über 0 kg angeben.")
    if bestand(con, von) < kg - 1e-9:
        raise geld.Fehler(f"Nicht genug Gold: {h[von]} hält {_kg(bestand(con, von))}.")
    grund = (grund or "").strip()[:200]
    _bewegen(con, von, h[von], -kg, "umbuchung", 0, k, f"An {h[nach]}" + (f": {grund}" if grund else ""))
    _bewegen(con, nach, h[nach], kg, "umbuchung", 0, k, f"Von {h[von]}" + (f": {grund}" if grund else ""))
    geld.protokoll(con, k, "Goldtransfer", f"RP-Leitung: {kg:g} kg Gold von {h[von]} an {h[nach]}" + (f" ({grund})" if grund else ""))


def transfer_html(request, con, von=None, zurueck=None):
    """Formular „Gold übertragen“ (nur RP-Leitung): zwischen Teilstaaten bzw. Reichskasse; von = vorbelegte Stelle."""
    h = halter(con)
    def opts(sel):
        return "".join(f'<option value="{esc(st)}"{" selected" if st == sel else ""}>{esc(n.replace("Staatskasse ", ""))} · {_kg(bestand(con, st))}</option>' for st, n in h.items())
    leer = '<option value="" selected disabled>Bitte wählen</option>'
    zur = f'<input type="hidden" name="zurueck" value="{esc(zurueck)}">' if zurueck else ""
    return (f'<h2>{amt.ic("arrow-right-left")} Gold übertragen</h2>'
            '<p class="az">RP-Eingriff: Gold zwischen Teilstaaten (oder der Reichskasse) umbuchen, z. B. nach einem Vertrag, einer Reparation oder einer Korrektur. '
            'Es fließt kein Geld; beide Seiten sehen die Umbuchung in ihren Goldgeschäften.</p>'
            f'<form class="sa-formular" method="post" action="{PFAD}gold/transfer">{amt.csrf_feld(request)}{zur}<div class="zeilen">'
            f'<div><label for="gt-von">Von</label><select id="gt-von" name="von" required>{"" if von else leer}{opts(von)}</select></div>'
            f'<div><label for="gt-nach">An</label><select id="gt-nach" name="nach" required>{leer}{opts(None)}</select></div>'
            '<div><label for="gt-kg">Menge (kg)</label><input type="text" id="gt-kg" name="kg" required inputmode="decimal"></div>'
            '<div><label for="gt-grund">Grund (optional)</label><input type="text" id="gt-grund" name="grund" maxlength="200"></div></div>'
            f'<div class="aktionen"><button class="btn" type="submit" onclick="return confirm(\'Gold jetzt übertragen?\')">{amt.ic("check")}Übertragen</button></div></form>')


async def transfer_post(request):
    k = await anmeldung.konto(request)
    if not sa.ist_rp(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    z = str(form.get("zurueck", ""))
    back = z if z.startswith(PFAD + "rp/") and "\n" not in z and "\r" not in z else sa.RP_STELL + "#gold"
    try:
        roh = str(form.get("kg", "")).replace(" ", "")
        kg = float(roh.replace(".", "").replace(",", ".") if "," in roh else roh)
        umbuchen(con, str(form.get("von", "")), str(form.get("nach", "")), kg, str(form.get("grund", "")), k)
        con.commit()
    except (ValueError, geld.Fehler) as e:
        con.rollback()
        sa.weiter(back, str(e) if isinstance(e, geld.Fehler) else "Bitte eine gültige Menge angeben.", True)
    h = halter(con)
    sa.weiter(back, f'{_kg(kg)} Gold von {h[form["von"]]} an {h[form["nach"]]} übertragen.')


def _kg(x):
    return f"{x:,.1f} kg".replace(",", "X").replace(".", ",").replace("X", ".")


def _t(x):
    return f"{x / 1000:,.2f} t".replace(",", "X").replace(".", ",").replace("X", ".")


def rp_html(request, con):
    """Goldpreis und Auf-/Abschlag für die RP-Leitungssicht."""
    g = geld.einstellung(con, "gold")
    form = (f'<h2>Goldpreis festsetzen</h2><form class="sa-leiste" method="post" action="{PFAD}gold/preis">{amt.csrf_feld(request)}'
                 f'<div><label for="p">€ je kg</label><input type="text" id="p" name="preis" value="{preis(con):.0f}"></div>'
                 f'<div><label for="a">Ab-/Aufschlag %</label><input type="text" id="a" name="abschlag" value="{esc(str(g["abschlag"]))}"></div>'
                 f'<button class="btn zweit" type="submit">Speichern</button></form>')
    return form + transfer_html(request, con)


@sa.seite("staat")
async def seite(request, k):
    con = request.app["db"]
    regiert = sa._regierte(con, k)
    ziel = request.query.get("ziel", "")
    if ziel.startswith("ts-") and ziel[3:] in regiert:
        eigener = ziel[3:]
    elif not sa.hat_kassen(con, k) and regiert:
        eigener = next(iter(regiert))   # ohne Reichskassen-Zugriff nur der eigene Teilstaat
    else:
        eigener = None
    if eigener:
        sa.zur_finanz_seite(request, k, con, "ts-" + eigener, "gold")
        return _teilstaat_seite(request, k, con, eigener, regiert[eigener])
    rows = con.execute("SELECT * FROM gr_bestand ORDER BY kg DESC").fetchall()
    gesamt = sum(r["kg"] for r in rows)
    menge = geld.geldmenge(con)
    gw = wert(con, gesamt)
    g = geld.einstellung(con, "gold")
    eigene = handelbar(con, k)   # Seite ist ohnehin nur staatlich (sa.seite("staat"))
    kz = [("Goldreserven gesamt", _t(gesamt)), ("Wert", mark(gw)), ("Golddeckung der Krone", f"{gw / menge * 100:.1f} %".replace(".", ",") if menge else "–"),
          ("Goldpreis", f"{preis(con):,.0f} € je kg".replace(",", "."))]
    zeilen = [(f'<span class="anker" id="g-{esc(r["stelle"])}">{esc(r["name"])}</span>', _t(r["kg"]), mark(wert(con, r["kg"])), f"{r['kg'] / gesamt * 100:.1f} %".replace(".", ",") if gesamt else "–") for r in rows]
    handel = ""
    if eigene:
        opts = "".join(f'<option value="{r["id"]}">{esc(r["name"])} · {_kg(bestand(con, s))} · {mark(r["saldo"])}</option>' for s, r in sorted(eigene.items(), key=lambda x: x[1]["name"]))
        handel = (f'<h2>Gold handeln</h2><form class="sa-formular" method="post" action="{PFAD}gold/handeln">{amt.csrf_feld(request)}<div class="zeilen">'
                  f'<div><label for="ka">Kasse</label><select id="ka" name="kasse">{opts}</select></div>'
                  '<div><label for="kg">Menge (kg)</label><input type="text" id="kg" name="kg" required inputmode="decimal"></div>'
                  '<div><label for="ri">Geschäft</label><select id="ri" name="richtung"><option value="verkauf">An die Zentralbank verkaufen</option>'
                  '<option value="kauf">Von der Zentralbank kaufen</option></select></div></div>'
                  f'<p class="sa-hinweis">1 kg entspricht derzeit {mark(wert(con, 1))}. Die Zentralbank kauft mit {g["abschlag"]} % Abschlag an und verkauft mit '
                  f'{g["abschlag"]} % Aufschlag. Ein Verkauf bringt neues, goldgedecktes Geld in die Kasse.</p>'
                  f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Ausführen</button></div></form>')
    preisform = ""
    namen = {r["stelle"]: r["name"] for r in rows}
    bew = con.execute("SELECT * FROM gr_buchungen WHERE art!='erstausstattung' ORDER BY id DESC LIMIT 30").fetchall()
    inhalt = (f'<h1>{amt.ic("coins")} Goldreserven</h1>{amt.meldung(request)}'
              '<p class="az">Goldbestände des Reiches (Reichskasse, einschließlich der Reichsunmittelbaren Territorien), der Teilstaaten und der Zentralbank. '
              'Ausgangsbestand nach den Goldreserven der Nationalbanken, anteilig nach der Wirtschaftsleistung der Gebiete.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>{handel}'
              '<h2>Bestände</h2>' + amt.tabelle(["Halter", "Bestand", "Wert", "Anteil"], zeilen, "Noch keine Goldreserven.") + preisform
              + '<h2>Letzte Goldgeschäfte</h2>' + amt.tabelle(["Zeit", "Halter", "Menge", "Geschäft", "Betrag", "Durch"],
                                                            [(amt._zeit(b["zeit"]), esc(namen.get(b["stelle"], b["stelle"])), _kg(b["kg"]), esc(ARTEN.get(b["art"], b["art"])), mark(b["betrag"]),
                                                              esc(b["autor_name"])) for b in bew], "Noch keine Geschäfte."))
    return sa.ant(request, k, "Goldreserven", "sa-gold", inhalt)


def _teilstaat_seite(request, k, con, sid, kasse):
    return sa.ant(request, k, "Goldreserven", "sa-gold", teilstaat_rumpf(request, k, con, sid, kasse, False))


def teilstaat_rumpf(request, k, con, sid, kasse, eingebettet=True):
    """Goldreserven bei Mein Teilstaat (Seite „Finanzen“): nur der Bestand und die Geschäfte des eigenen Teilstaats."""
    stelle = "ts-" + sid
    kg = bestand(con, stelle)
    menge = geld.geldmenge(con)
    g = geld.einstellung(con, "gold")
    kz = [("Goldreserven", _t(kg)), ("Wert", mark(wert(con, kg))), ("Goldpreis", f"{preis(con):,.0f} € je kg".replace(",", ".")), ("Kassenstand", mark(kasse["saldo"]))]
    handel = ""
    if stelle in handelbar(con, k):
        handel = (f'<h2>Gold handeln</h2><form class="sa-formular" method="post" action="{PFAD}gold/handeln">{amt.csrf_feld(request)}'
                  f'<input type="hidden" name="kasse" value="{kasse["id"]}"><input type="hidden" name="ziel" value="{esc(stelle)}"><div class="zeilen">'
                  '<div><label for="kg">Menge (kg)</label><input type="text" id="kg" name="kg" required inputmode="decimal"></div>'
                  '<div><label for="ri">Geschäft</label><select id="ri" name="richtung"><option value="verkauf">An die Zentralbank verkaufen</option>'
                  '<option value="kauf">Von der Zentralbank kaufen</option></select></div></div>'
                  f'<p class="sa-hinweis">1 kg entspricht derzeit {mark(wert(con, 1))}. Die Zentralbank kauft mit {g["abschlag"]} % Abschlag an und verkauft mit '
                  f'{g["abschlag"]} % Aufschlag. Ein Verkauf bringt neues, goldgedecktes Geld in die Staatskasse.</p>'
                  f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Ausführen</button></div></form>')
    bew = con.execute("SELECT * FROM gr_buchungen WHERE stelle=? ORDER BY id DESC LIMIT 30", (stelle,)).fetchall()
    inhalt = (("" if eingebettet else f'<h1>{amt.ic("coins")} Goldreserven</h1>{amt.meldung(request)}')
              + f'<p class="az">Goldreserven von {esc(kasse["name"].replace("Staatskasse ", ""))}. Andere Teilstaaten und das Reich sind hier nicht einsehbar.</p>'
              f'<div class="kennzahlen">{"".join(f"<div><b>{esc(v)}</b>{esc(t)}</div>" for t, v in kz)}</div>{handel}'
              '<h2>Goldgeschäfte und Buchungen</h2>' + amt.tabelle(["Zeit", "Menge", "Geschäft", "Betrag", "Durch"],
                  [(amt._zeit(b["zeit"]), _kg(b["kg"]), esc(ARTEN.get(b["art"], b["art"])), mark(b["betrag"]), esc(b["autor_name"])) for b in bew], "Noch keine Goldgeschäfte."))
    return inhalt


async def handeln_post(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con = request.app["db"]
    kasse = geld.konto(con, form.get("kasse")) if str(form.get("kasse", "")).isdigit() else None
    ts_ziel = str(form.get("ziel", "")).startswith("ts-") and str(form["ziel"])[3:].isalnum()
    back = f"{PFAD}teilstaat/finanzen/?ziel={form['ziel']}" if ts_ziel else f"{PFAD}gold/"
    erlaubt = {r["id"] for r in handelbar(con, k).values() if r}
    if not kasse or kasse["id"] not in erlaubt:
        sa.weiter(back, "Über diese Kasse darfst du nicht verfügen.", True)
    try:
        roh = str(form.get("kg", "")).replace(" ", "")
        kg = float(roh.replace(".", "").replace(",", ".") if "," in roh else roh)
        betrag = handeln(con, kasse, kg, form.get("richtung") != "kauf", k)
        con.commit()
    except (ValueError, geld.Fehler) as e:
        con.rollback()
        sa.weiter(back, str(e) if isinstance(e, geld.Fehler) else "Bitte eine gültige Menge angeben.", True)
    sa.weiter(back, f"{kg:g} kg Gold {'verkauft' if form.get('richtung') != 'kauf' else 'gekauft'} für {mark(betrag)}.")


async def preis_post(request):
    k = await anmeldung.konto(request)
    if not sa.ist_rp(k):
        raise web.HTTPForbidden()
    form = await sa.formular(request)
    con = request.app["db"]
    try:
        p = float(str(form.get("preis", "")).replace(".", "").replace(",", "."))
        a = geld.prozent_lesen(form.get("abschlag"))
        assert 1000 <= p <= 10_000_000 and a is not None
    except (ValueError, AssertionError):
        sa.weiter(sa.RP_STELL, "Bitte einen gültigen Goldpreis und Abschlag angeben.", True)
    geld.einstellung_setzen(con, "gold", {"preis_kg": round(p), "abschlag": a if a != int(a) else int(a)}, k)
    con.commit()
    sa.weiter(sa.RP_STELL, "Goldpreis festgesetzt.")


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
    r.add_post(PFAD + "gold/transfer", transfer_post)
