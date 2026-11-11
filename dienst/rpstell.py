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


@sa.seite("rp")
async def seite(request, k):
    con = request.app["db"]
    chips = '<div class="rs-chips">' + "".join(f'<a href="#{i}">{esc(n)}</a>' for i, n, _ in ABSCHNITTE) + "</div>"
    bloecke = "".join(f'<section class="rs-block" id="{i}">{f(request, con)}</section>' for i, _, f in ABSCHNITTE)
    weitere = ('<p class="az">Weitere Konfiguration: '
               f'<a href="{PFAD}rp/foerderstaetten/">Förderstätten</a> · <a href="{PFAD}rp/handel/">Handel: Waren &amp; Regeln</a> · '
               f'<a href="{PFAD}rp/besitz/">Besitzkatalog</a> · <a href="{PFAD}amt/tarife/">Sätze festlegen (Steuern, Gebühren, Besoldungsabzüge)</a> · '
               f'<a href="{PFAD}verteidigung/katalog/">Gerätekatalog</a></p>')
    inhalt = (f'<h1>{amt.ic("pencil")} Stellschrauben</h1>{amt.meldung(request)}'
              '<p class="az">RP-Konfiguration: Alle Werte, mit denen das Spiel eingestellt wird. Änderungen gelten, wenn nicht anders vermerkt, ab dem nächsten gebuchten Monat '
              'und werden im Protokoll festgehalten. Im IC-Bereich sind diese Werte nur lesbar.</p>' + weitere + chips + bloecke)
    return sa.ant(request, k, "Stellschrauben", "sa-rp-stell", CSS + inhalt)


def registrieren(app):
    app.router.add_get(sa.RP_STELL, seite)
