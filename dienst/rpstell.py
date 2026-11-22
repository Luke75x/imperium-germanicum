"""Stellschrauben in der RP-Leitungsansicht (/schatzamt/rp/stellschrauben/).

Alles, was das Spiel einstellt (Steuer- und Abgabequoten, Wechselkurs, Goldpreis, Notlagen-Sätze, Verteidigungssätze, Behördenetats) ist OOC-Konfiguration und
steht nur hier – nicht in den IC-Ansichten (Staatl./Privat). Jeder Abschnitt kommt aus dem Modul, dem die Einstellung gehört (`rp_html(request, con)` in
aufkommen, gold, notlage, verteidigung, etat); die POST-Routen bleiben dort und leiten hierher zurück. Weitere Konfiguration: rp/foerderstaetten,
rp/handel, rp/besitz (Modul privatbesitz/handel), amt/tarife (Sätze festlegen, steuern.py).
"""
import amt
import aufkommen
import etat
import gold
import notlage
import schatzamt as sa
import verteidigung

esc = amt.esc
PFAD = sa.PFAD

ABSCHNITTE = [("haushalt", "Staatshaushalt", aufkommen.rp_html), ("gold", "Gold", gold.rp_html), ("notlage", "Haushaltsnotlage", notlage.rp_html),
              ("verteidigung", "Verteidigung", verteidigung.rp_html), ("etats", "Behördenetats", etat.rp_html)]

CSS = """<style>
.rs-chips{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 18px}
.rs-chips a{padding:7px 14px;border:1px solid var(--linie);border-radius:999px;color:var(--ink);text-decoration:none;font-size:14px;background:#fff}
.rs-chips a:hover{background:var(--hell)}
.rs-block{border:1px solid var(--linie);border-radius:12px;padding:4px 20px 18px;margin:0 0 18px;background:#fff;scroll-margin-top:80px}
.rs-block h2{margin-top:16px}
</style>"""


amt.ICONS.setdefault("pickaxe", '<path d="M14.531 12.469 6.619 20.38a1 1 0 1 1-3-3l7.912-7.912"/><path d="M15.686 4.314A12.5 12.5 0 0 0 5.461 2.958 1 1 0 0 0 5.58 4.71a22 22 0 0 1 6.318 3.393"/>'
                     '<path d="M17.7 3.7a1 1 0 0 0-1.4 0l-4.6 4.6a1 1 0 0 0 0 1.4l2.6 2.6a1 1 0 0 0 1.4 0l4.6-4.6a1 1 0 0 0 0-1.4z"/>'
                     '<path d="M19.686 8.314a12.501 12.501 0 0 1 1.356 10.225 1 1 0 0 1-1.751-.119 22 22 0 0 0-3.393-6.319"/>')
amt.ICONS.setdefault("ship", '<path d="M12 10.189V14"/><path d="M12 2v3"/><path d="M19 13V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6"/>'
                     '<path d="M19.38 20A11.6 11.6 0 0 0 21 14l-8.188-3.639a2 2 0 0 0-1.624 0L3 14a11.6 11.6 0 0 0 2.81 7.76"/>'
                     '<path d="M2 21c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1s1.2 1 2.5 1c2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>')

KONFIG_URL = PFAD + "rp/konfiguration/"


def _zahl(con, sql):
    try:
        return con.execute(sql).fetchone()[0]
    except Exception:
        return 0


@sa.seite("rp")
async def uebersicht(request, k):
    """Alle Konfigurationsseiten der RP-Leitung als Kacheln mit den wichtigsten Kennzahlen."""
    import rpleitung
    con = request.app["db"]
    kacheln = [
        ("sliders-horizontal", "Stellschrauben", "Steuer- und Abgabequoten, Wechselkurs, Goldpreis, Notlage, Verteidigung, Behördenetats", "5 Bereiche", PFAD + "rp/stellschrauben/"),
        ("percent", "Steuer- & Gebührensätze", "Lohnsteuer, Sozialabgaben, Gebühren, Besoldungsabzüge", "", PFAD + "amt/tarife/"),
        ("pickaxe", "Förderstätten", "Lagerstätten und Jahresmengen je Rohstoff", f'{_zahl(con, "SELECT COUNT(*) FROM hd_lagerstaetten")} Förderstätten', PFAD + "rp/foerderstaetten/"),
        ("ship", "Handel: Waren & Regeln", "Richtpreise, Sätze, Handelssperren",
         f'{_zahl(con, "SELECT COUNT(*) FROM hd_waren WHERE aktiv=1")} Waren aktiv · {_zahl(con, "SELECT COUNT(*) FROM hd_sperren")} Sperren', PFAD + "rp/handel/"),
        ("zap", "Energie: Sätze & Anlagen", "Sätze des Energiesystems, Kraftwerke stilllegen", f'{_zahl(con, "SELECT COUNT(*) FROM en_kraftwerke")} Kraftwerke', PFAD + "rp/energie/"),
        ("car", "Besitzkatalog & Kosten", "Fahrzeuge und Immobilien, Preise, Kostenlauf", f'{_zahl(con, "SELECT COUNT(*) FROM pb_katalog")} Einträge', PFAD + "rp/besitz/"),
        ("wrench", "Gerätekatalog", "Militärgerät: Preise und Instandhaltung", f'{_zahl(con, "SELECT COUNT(*) FROM vt_katalog")} Geräte', PFAD + "verteidigung/katalog/"),
        ("coins", "Geldpolitik", "Geldschöpfung und -vernichtung, Zentralbank", "", PFAD + "amt/geldpolitik/"),
    ]
    raster = "".join(f'<a class="rp-kachel" href="{u}">{amt.ic(i)}<b>{esc(t)}</b><small>{esc(d)}</small>' + (f'<small><b>{esc(z)}</b></small>' if z else "") + "</a>"
                     for i, t, d, z, u in kacheln)
    inhalt = (rpleitung.CSS + f'<h1>{amt.ic("layout-grid")} Konfiguration</h1>{amt.meldung(request)}'
              '<p class="az">Alle Werte, mit denen das Spiel eingestellt wird. Änderungen stehen im '
              f'<a href="{PFAD}rp/protokoll/?bereich=konfig">Protokoll (Bereich Konfiguration)</a>. Was einen einzelnen Teilstaat betrifft, zeigt auch dessen Reiter „Konfiguration“ '
              f'unter <a href="{PFAD}rp/teilstaaten/">Die Teilstaaten</a>.</p>'
              f'<div class="rp-raster">{raster}</div>')
    return sa.ant(request, k, "Konfiguration", "sa-rp-konfig", inhalt)


@sa.seite("rp")
async def seite(request, k):
    con = request.app["db"]
    chips = '<div class="rs-chips">' + "".join(f'<a href="#{i}">{esc(n)}</a>' for i, n, _ in ABSCHNITTE) + "</div>"
    bloecke = "".join(f'<section class="rs-block" id="{i}">{f(request, con)}</section>' for i, _, f in ABSCHNITTE)
    inhalt = (f'<h1>{amt.ic("sliders-horizontal")} Stellschrauben</h1>{amt.meldung(request)}'
              '<p class="az">RP-Konfiguration: Alle Werte, mit denen das Spiel eingestellt wird. Änderungen gelten, wenn nicht anders vermerkt, ab dem nächsten gebuchten Monat '
              'und werden im Protokoll festgehalten. Im IC-Bereich sind diese Werte nur lesbar. Weitere Einstellungen: '
              f'<a href="{KONFIG_URL}">Konfiguration</a>.</p>' + chips + bloecke)
    return sa.ant(request, k, "Stellschrauben", "sa-rp-stell", CSS + inhalt)


def registrieren(app):
    app.router.add_get(sa.RP_STELL, seite)
    app.router.add_get(KONFIG_URL, uebersicht)
