"""Stichwortsuche im Schatzamt-Portal (/schatzamt/suche/).

Man gibt Stichwörter ein („Goldreserve Pfalz-Bayern“) und gelangt zur passenden Seite – aber nur zu Seiten, die man auch einsehen darf:
Der Suchindex wird bei jeder Anfrage **für das jeweilige Konto** gebaut und enthält nur Einträge, für die die Rechte stimmen (dieselben Prüfungen
wie die Seiten selbst: staatlicher Zugriff `sa.hat_kassen`, Verteidigung `verteidigung.darf_sehen`, Landesherr `etatplan.darf_aendern`, Kassen
`geld.verfuegbare_konten`, Beamte/Leitung/RP). Was man nicht sehen darf, kommt in der Suche nicht vor und wird nicht verraten.

Quellen: feste Seiten des Portals, je Teilstaat und das Reich die Haushaltsseiten (Gold, Etat, Entwicklung, Krisen, Notlage, Verteidigung, Kasse),
Behörden-Etats, Handelswaren, eigene Konten, Güter, Gewerbe und Steuerbescheide.
Treffer: alle Suchwörter müssen vorkommen (Wortanfang oder Teilwort; Titel zählt mehr als Schlagwörter, Umlaute und Bindestriche egal).
Gibt es einen klaren Sieger – oder genau einen Treffer –, springt die Suche direkt dorthin, sonst zeigt sie die Trefferliste (`&liste=1` erzwingt sie).
`&json=1` liefert die ersten Treffer für die Vorschläge in der Kopfleiste (kein Sprung).
"""
import re
import unicodedata

from aiohttp import web

import amt
import anmeldung
import geld
import schatzamt as sa

esc = amt.esc
PFAD = sa.PFAD
SUCHE = PFAD + "suche/"
MAX_TREFFER = 40


def norm(s):
    """Kleinbuchstaben, Umlaute aufgelöst (ä→ae, ß→ss), Sonderzeichen zu Leerzeichen."""
    s = str(s or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class Eintrag:
    __slots__ = ("titel", "bereich", "url", "kw", "gewicht", "t_woerter", "k_woerter")

    def __init__(self, titel, bereich, url, kw="", gewicht=0):
        self.titel, self.bereich, self.url, self.kw, self.gewicht = titel, bereich, url, kw, gewicht
        self.t_woerter = norm(titel).split()
        self.k_woerter = norm(kw + " " + bereich).split()


def _treffer_wort(t, woerter):
    """Beste Wertung des Suchworts t gegen eine Wortliste: Wortgleichheit 10, Wortanfang 8, Wort ist Anfang von t (Plural) 6, Teilwort 5."""
    best = 0
    for w in woerter:
        if w == t:
            return 10
        if w.startswith(t):
            best = max(best, 8)
        elif len(w) >= 5 and t.startswith(w):
            best = max(best, 6)
        elif len(t) >= 3 and t in w:
            best = max(best, 5)
    return best


def bewerten(e, tokens):
    """Wertung eines Eintrags für alle Suchwörter, 0 = kein Treffer (jedes Wort muss vorkommen)."""
    gesamt = 0
    for t in tokens:
        im_titel = _treffer_wort(t, e.t_woerter)
        im_kw = _treffer_wort(t, e.k_woerter)
        if not im_titel and not im_kw:
            return 0
        gesamt += im_titel * 2 if im_titel else im_kw
    # kürzere Titel sind spezifischer
    return gesamt * 10 + e.gewicht - len(e.t_woerter)


# ---------------------------------------------------------------- Index

def _ts_liste(con):
    import karte
    out = []
    for s in karte.aktuell(con)["stand"]["staaten"]:
        if not geld.ist_reichsgebiet(s):
            out.append((s["id"], s["name"]))
    return sorted(out, key=lambda x: x[1])


def _eigene(con, k):
    """Eigene Güter, Gewerbe und Steuerbescheide als (Titel, Bereich, URL, Schlagwörter)."""
    out = []
    for r in con.execute("SELECT b.id, b.bezeichnung, b.status, k.name, k.kategorie FROM pb_besitz b JOIN pb_katalog k ON k.id=b.katalog_id "
                         "WHERE b.inhaber_id=? AND b.status='aktiv'", (k["id"],)).fetchall():
        out.append((r["bezeichnung"] or r["name"], "Mein Besitz", f"{PFAD}besitz/{r['id']}/", f"{r['name']} {r['kategorie']} besitz eigentum kosten", 2))
    for g in con.execute("SELECT id, name, branche FROM gk_gewerbe WHERE inhaber_id=? AND status='aktiv'", (k["id"],)).fetchall():
        out.append((g["name"], "Mein Gewerbe", PFAD + "gewerbe/", f"gewerbe {g['branche']} firma", 2))
    for b in con.execute("SELECT s.id, s.jahr, s.nr, s.steuerart, s.status FROM st_bescheide s JOIN gk_konten c ON c.id=s.konto WHERE c.inhaber_id=? "
                         "ORDER BY s.id DESC LIMIT 30", (k["id"],)).fetchall():
        az = f"ST-{b['jahr']}-{b['nr']:04d}"
        out.append((f"Steuerbescheid {az}", "Steuern & Gebühren", f"{PFAD}steuern/{b['id']}/", f"{b['steuerart']} bescheid {b['status']} {az}", 0))
    return out


def index(con, k):
    """Alle Einträge, die dieses Konto einsehen darf."""
    import etatplan
    import verteidigung
    E = []
    add = lambda *a, **kw: E.append(Eintrag(*a, **kw))
    mitglied = bool(k["mitglied"])
    kassen = sa.hat_kassen(con, k)
    beamter = geld.ist_beamter(k)
    leitung = geld.ist_leitung(k)

    # --- Privat: Konto, Zahlungsverkehr, Steuern, Gehalt, Gewerbe, Besitz
    if mitglied:
        add("Übersicht", "Mein Geld", PFAD, "start startseite privatkonto guthaben saldo kontostand")
        add("Konto & Umsätze", "Mein Geld", PFAD + "konto/", "kontoauszug buchungen umsaetze kontonummer iban guthaben pdf")
        add("Überweisen", "Mein Geld", PFAD + "ueberweisen/", "zahlung zahlen senden geld ueberweisung transfer")
        add("Steuern & Gebühren", "Mein Geld", PFAD + "steuern/", "bescheid steuerbescheid lohnsteuer kopfsteuer vermoegensteuer gewerbesteuer mahnung saeumnis finanzamt")
        add("Gehalt", "Mein Geld", PFAD + "gehalt/", "besoldung abrechnung lohn gehaltsabrechnung sold einkommen netto brutto")
        add("Gewerbe", "Mein Geld", PFAD + "gewerbe/", "gewerbeanmeldung firma unternehmen betrieb selbststaendig gewerbekonto")
        add("Besitz erwerben", "Privatwirtschaft", PFAD + "besitz/erwerben/", "kaufen fahrzeug auto immobilie haus wohnung villa schloss kaufpreis", 2)
        add("Besitz: Kosten & Regeln", "Privatwirtschaft", PFAD + "besitz/kosten/", "fixkosten laufende kosten steuer versicherung unterhalt pfaendung rueckstand regeln")
        add("Besitz (Fahrzeuge, Immobilien, Güter)", "Privatwirtschaft", PFAD + "besitz/",
            "privatbesitz privateigentum eigentum auto fahrzeug kfz motorrad boot yacht flugzeug haus wohnung immobilie grundstueck villa schloss kaufen verkaufen "
            "laufende kosten fixkosten versicherung unterhalt grundsteuer kfzsteuer pfaendung privatwirtschaft", 2)
        add("Bankkarte & PIN", "Mein Geld", PFAD + "bankkarte/", "karte pin bankkarte beantragen sperren entsperren ec girokarte")
        add("Etatübersicht", "Information", PFAD + "etatuebersicht/", "haushalt etat oeffentlich staatsausgaben tortendiagramm")
        add("Tarife & Sätze", "Information", PFAD + "tarife/", "steuersatz steuersaetze gebuehren lohnsteuer stufentarif sozialabgabe kronsteuer leitzins wechselkurs umsatzsteuer grunderwerbsteuer zulassung")
        add("Postfach", "Weiteres", amt.BASIS + "postfach/", "post nachrichten mail ig adresse")
        add("Mein Profil", "Weiteres", "/profil/", "profil einstellungen konto")
        if anmeldung._amt_zugang(k):
            add("Amtsseite", "Weiteres", amt.BASIS, "behoerden akten buerger verfahren")
        for e in _eigene(con, k):
            add(*e)

    # --- Eigene Konten
    if mitglied:
        for r in geld.verfuegbare_konten(con, k):
            add(r["name"], "Konto", f"{PFAD}konto/?konto={r['id']}", f"kasse konto umsaetze {r['nummer']} {geld.nummer_anzeige(r['nummer'])}", 1)

    # --- Staatlich: Kassen, Haushalt, Gold, Handel, Etats
    if kassen:
        add("Staatliche Kassen – Übersicht", "Staatl.", PFAD, "kassen uebersicht staat staatlich")
        add("Staatshaushalt (Reich)", "Reichshaushalt", PFAD + "haushalt/", "reichshaushalt einnahmen ausgaben steueraufkommen reichsabgabe bip haushalt", 2)
        add("Reichsfinanzen", "Reichshaushalt", PFAD + "finanzen/", "geldmenge zentralbank reichskasse geldschoepfung finanzen")
        add("Etats der Behörden", "Reichshaushalt", PFAD + "etats/", "behoerdenetat etat zuweisung haushaltsplan")
        add("Goldreserven – Reich und Teilstaaten", "Reichshaushalt", PFAD + "gold/", "gold goldreserve goldreserven goldpreis goldhandel zentralbank deckung barren tresor", 2)
        add("Haushaltsnotlagen", "Reichshaushalt", PFAD + "notlagen/?bereich=reich", "notlage dispo strafzinsen ueberschuldung zwangsverwaltung minus")
        add("Etatverteilung – Reich", "Reichshaushalt", PFAD + "etatverteilung/?ziel=reich", "etat verteilung torte kategorien prozent budget")
        add("Entwicklung – Reich", "Reichshaushalt", PFAD + "entwicklung/?ziel=reich", "bevoelkerung bip hdi bildung kriminalitaet akademiker entwicklung")
        add("Krisen – Reich", "Reichshaushalt", PFAD + "krisen/?ziel=reich", "krise handlungszwang eskalation lage")
        add("Handel", "Handel", PFAD + "handel/", "markt waren angebote kaufen verkaufen export import rohstoffe", 2)
        add("Handel – Lager", "Handel", PFAD + "handel/mein/", "lager bestand waren eigenes")
        add("Handel – Veredelung", "Handel", PFAD + "handel/veredelung/", "veredelung veredeln stahl aluminium treibstoff bonus")
        add("Handel – Verkaufen", "Handel", PFAD + "handel/verkaufen/", "verkaufen anbieten angebote")
        add("Handel – Rohstoffvorkommen", "Handel", PFAD + "handel/ressourcen/", "ressourcen rohstoffe lagerstaetten foerderung vorkommen")
        add("Handelsbuch", "Handel", PFAD + "handel/buch/", "geschaefte handelsbuch protokoll")
        add("Handel: Waren & Regeln", "Handel", PFAD + "handel/regeln/", "richtpreise preise regeln waren verderb herkunft")
        for r in con.execute("SELECT name, sektor FROM hd_waren WHERE aktiv=1").fetchall():
            add(f"Handel – {r['name']}", "Handelsware", PFAD + "handel/", f"{r['sektor']} ware angebot", 0)
        for b in amt.BEHOERDEN:
            add(f"Etat {b['name']}", "Behörde", PFAD + "etats/", "etat budget haushalt behoerde")
        for sid, name in _ts_liste(con):
            z = "ts-" + sid
            add(f"Goldreserven – {name}", "Gold", f"{PFAD}gold/#g-{z}", "gold goldreserve bestand tresor reserve", 3)
            add(f"Etatverteilung – {name}", "Teilstaat", f"{PFAD}etatverteilung/?ziel={z}", "etat verteilung torte budget kategorien")
            add(f"Entwicklung – {name}", "Teilstaat", f"{PFAD}entwicklung/?ziel={z}", "bevoelkerung bip hdi bildung kriminalitaet entwicklung")
            add(f"Krisen – {name}", "Teilstaat", f"{PFAD}krisen/?ziel={z}", "krise handlungszwang lage")
            add(f"Haushaltsnotlage – {name}", "Teilstaat", f"{PFAD}notlagen/?bereich={z}", "notlage dispo minus strafzinsen")
            if etatplan.darf_aendern(con, k, z):
                add(f"Etat planen – {name}", "Teilstaat", f"{PFAD}etatplanung/?ziel={z}", "etatplanung entwurf einreichen aendern", 1)
            if verteidigung.darf_sehen(con, k, sid):
                add(f"Verteidigung – {name}", "Verteidigung", f"{PFAD}verteidigung/{sid}/", "militaer armee heer marine luftwaffe geraet bestand beschaffung rueckstand", 2)
        regiert = sa._regierte(con, k)
        for sid, r in regiert.items():
            add(f"Mein Teilstaat – {r['name'].replace('Staatskasse ', '')}", "Teilstaat", f"{PFAD}teilstaat/?ziel=ts-{sid}", "landesherr ueberblick regierung teilstaat", 2)
    if sa.hat_verteidigung(con, k) and not kassen:
        add("Verteidigung", "Verteidigung", PFAD + "verteidigung/", "militaer armee geraet bestand")
    elif kassen and sa.hat_verteidigung(con, k):
        add("Verteidigung – Übersicht", "Verteidigung", PFAD + "verteidigung/", "militaer armee reichsverteidigung geraet katalog", 1)

    # --- Verwaltung
    if beamter:
        add("Verwaltung (Schatzamt)", "Schatzamt", PFAD + "amt/", "amt verwaltung schatzamt")
        add("Konten (Verwaltung)", "Schatzamt", PFAD + "amt/konten/", "kontoverwaltung sperren entsperren korrektur")
        add("Steuerverwaltung", "Schatzamt", PFAD + "amt/steuern/", "bescheide mahnlauf steuerlauf erlass einziehen")
        add("Gewerberegister", "Schatzamt", PFAD + "amt/gewerbe/", "gewerbeantraege genehmigen")
        add("Bankkarten (Verwaltung)", "Schatzamt", PFAD + "amt/bankkarten/", "karten pin sperre")
        add("Protokoll (Schatzamt)", "Schatzamt", PFAD + "amt/protokoll/", "log aenderungen historie")
    if leitung:
        add("Besoldung & Lohnlauf", "Schatzamt", PFAD + "amt/besoldung/", "gehaelter gruppen rollen zuschlaege lohnlauf")
        add("Geldpolitik", "Schatzamt", PFAD + "amt/geldpolitik/", "geldschoepfung geldvernichtung leitzins zentralbank")
    if mitglied and k["admin"]:
        add("Förderstätten anlegen & verwalten", "RP-Konfiguration", PFAD + "rp/foerderstaetten/", "foerderstaette lagerstaette rohstoffe foerderung ressourcen vorkommen anlegen bearbeiten", 2)
        add("Handel: Waren, Richtpreise, Sätze, Sperren", "RP-Konfiguration", PFAD + "rp/handel/", "handel konfiguration richtpreise waren saetze handelssperre embargo regeln", 1)
        add("Besitzkatalog & Kostenlauf", "RP-Konfiguration", PFAD + "rp/besitz/", "privatbesitz katalog fahrzeuge immobilien preise kostenlauf privatwirtschaft konfiguration", 1)
        add("Stellschrauben (Haushalt, Gold, Notlage, Verteidigung, Etats)", "RP-Konfiguration", PFAD + "rp/stellschrauben/",
            "stellschrauben konfiguration steuerquote wechselkurs reichsabgabe goldpreis notlage dispo verteidigungsetat behoerdenetats saetze einstellungen", 2)
        add("Sätze festlegen (Steuern, Gebühren)", "RP-Konfiguration", PFAD + "amt/tarife/", "tarife saetze steuersaetze gebuehren lohnsteuer sozialabgabe konfiguration", 1)
        add("RP-Lagebild", "RP-Leitung", PFAD + "rp/", "rp leitung lagebild")
        add("RP-Fälle", "RP-Leitung", PFAD + "rp/faelle/", "faelle untersuchungen")
        add("RP: Konten & Personen", "RP-Leitung", PFAD + "rp/konten/", "konten personen suche")
        add("RP-Protokoll", "RP-Leitung", PFAD + "rp/protokoll/", "log")
    return E


def suchen(con, k, q):
    """[(Wertung, Eintrag)] absteigend."""
    tokens = norm(q).split()
    if not tokens:
        return []
    res = []
    for e in index(con, k):
        w = bewerten(e, tokens)
        if w:
            res.append((w, e))
    res.sort(key=lambda x: (-x[0], x[1].titel))
    # Doppelte Ziele zusammenführen
    seen, out = set(), []
    for w, e in res:
        if (e.url, e.titel) not in seen:
            seen.add((e.url, e.titel))
            out.append((w, e))
    return out


def sieger(res):
    """Direkter Sprung, wenn es genau einen Treffer oder einen klaren Sieger gibt."""
    if len(res) == 1:
        return res[0][1]
    if len(res) > 1 and res[0][0] - res[1][0] >= 30:
        return res[0][1]
    return None


# ---------------------------------------------------------------- Seite

LEISTE_CSS = """<style>
.kopf form.suche .sv{position:absolute;left:0;right:0;top:calc(100% + 6px);background:#fff;border:1px solid var(--linie);border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.12);z-index:60;overflow:hidden;min-width:320px}
.kopf form.suche .sv[hidden]{display:none}
.kopf form.suche .sv a{display:block;padding:9px 14px;color:var(--ink);text-decoration:none;font-size:14px;line-height:1.3;border-bottom:1px solid #eef0f2}
.kopf form.suche .sv a:last-child{border-bottom:0}
.kopf form.suche .sv a small{display:block;color:var(--grau);font-size:12px}
.kopf form.suche .sv a:hover,.kopf form.suche .sv a.fokus{background:var(--hell)}
.kopf form.suche .sv p{margin:0;padding:10px 14px;color:var(--grau);font-size:13px}
</style>"""
LEISTE_JS = """<script>(function(){var f=document.querySelector("form.suche[data-sv]");if(!f)return;var i=f.querySelector("input[type=search]"),b=f.querySelector(".sv"),t,n=0,idx=-1;
function zu(){b.hidden=true;idx=-1}
function links(){return b.querySelectorAll("a")}
function setze(d){var l=links();if(!l.length)return;if(idx>=0)l[idx].classList.remove("fokus");idx=(idx+d+l.length)%l.length;l[idx].classList.add("fokus")}
i.addEventListener("input",function(){clearTimeout(t);var q=i.value.trim();if(q.length<2){zu();return}
 t=setTimeout(function(){var m=++n;fetch(f.action+"?json=1&q="+encodeURIComponent(q),{credentials:"same-origin"}).then(function(r){return r.json()}).then(function(j){if(m!==n)return;
  b.textContent="";idx=-1;if(!j.length){var p=document.createElement("p");p.textContent="Keine Treffer – oder keine Berechtigung.";b.appendChild(p)}
  j.forEach(function(x){var a=document.createElement("a");a.href=x.u;a.textContent=x.t;var s=document.createElement("small");s.textContent=x.o;a.appendChild(s);b.appendChild(a)});b.hidden=false}).catch(zu)},180)});
i.addEventListener("keydown",function(e){if(b.hidden)return;if(e.key==="ArrowDown"){e.preventDefault();setze(1)}else if(e.key==="ArrowUp"){e.preventDefault();setze(-1)}
 else if(e.key==="Enter"&&idx>=0){e.preventDefault();links()[idx].click()}else if(e.key==="Escape"){zu()}});
document.addEventListener("click",function(e){if(!f.contains(e.target))zu()});
addEventListener("keydown",function(e){if(e.key==="/"&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)){e.preventDefault();var k=document.querySelector(".kopf");if(k)k.classList.add("suche-offen");i.focus()}})})()</script>"""


def leiste(q=""):
    """Suchleiste für die Kopfzeile des Portals (amt.rahmen portal['suche'])."""
    return (LEISTE_CSS + f'<form class="suche" data-sv action="{SUCHE}" method="get" role="search">{amt.ic("search")}'
            f'<input type="search" name="q" value="{esc(q)}" placeholder="Suchen, z. B. Goldreserve Pfalz-Bayern" aria-label="Portal durchsuchen" autocomplete="off">'
            '<div class="sv" role="listbox" hidden></div></form>'
            f'<button class="knopf-rund such-auf" type="button" aria-label="Suche öffnen" aria-expanded="false">{amt.ic("search")}</button>' + LEISTE_JS)


@sa.seite()
async def seite(request, k):
    con = request.app["db"]
    q = request.query.get("q", "").strip()[:100]
    res = suchen(con, k, q)
    if request.query.get("json"):
        return web.json_response([{"t": e.titel, "o": e.bereich, "u": e.url} for _, e in res[:8]], headers={"Cache-Control": "no-store"})
    if q and not request.query.get("liste"):
        s = sieger(res)
        if s:
            raise web.HTTPFound(s.url)
    if not q:
        rows = ""
        hinweis = ('<p class="az">Gib ein oder mehrere Stichwörter ein – etwa <b>Goldreserve Pfalz-Bayern</b>, <b>Etat Polizei</b>, <b>Kfz-Steuer</b> oder <b>Villa kaufen</b>. '
                   'Die Suche findet nur, was du einsehen darfst. Tipp: Mit der Taste <b>/</b> springst du in die Suchleiste.</p>')
    else:
        rows = "".join(f'<li><a href="{esc(e.url)}"><b>{esc(e.titel)}</b><small>{esc(e.bereich)}</small></a></li>' for _, e in res[:MAX_TREFFER])
        rows = (f'<ul class="sv-liste">{rows}</ul>' + (f'<p class="az">Weitere Treffer ({len(res) - MAX_TREFFER}) – bitte die Suche eingrenzen.</p>' if len(res) > MAX_TREFFER else "")) if rows else \
            '<p class="leer">Keine Treffer. Entweder gibt es das nicht, oder du darfst es nicht einsehen. Versuche andere oder weniger Stichwörter.</p>'
        hinweis = f'<p class="az">{len(res)} Treffer für „{esc(q)}“.</p>' if res else ""
    css = ("<style>.sv-liste{list-style:none;margin:10px 0;padding:0;border:1px solid var(--linie);border-radius:12px;overflow:hidden;background:#fff}"
           ".sv-liste li{border-bottom:1px solid #eef0f2}.sv-liste li:last-child{border-bottom:0}"
           ".sv-liste a{display:block;padding:12px 16px;color:var(--ink);text-decoration:none}.sv-liste a:hover{background:var(--hell)}"
           ".sv-liste small{display:block;color:var(--grau);font-size:12px;letter-spacing:.04em;margin-top:2px}</style>")
    form = (f'<form class="sa-leiste" method="get" action="{SUCHE}"><div style="flex:1"><label for="sq">Stichwörter</label>'
            f'<input type="search" id="sq" name="q" value="{esc(q)}" style="width:100%" autofocus></div><input type="hidden" name="liste" value="1">'
            f'<button class="btn" type="submit">{amt.ic("search")}Suchen</button></form>')
    return sa.ant(request, k, "Suche", "sa-suche", css + f'<h1>{amt.ic("search")} Suche</h1>{form}{hinweis}{rows}')


def registrieren(app):
    app.router.add_get(SUCHE, seite)
