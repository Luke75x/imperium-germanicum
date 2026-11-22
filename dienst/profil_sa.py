"""Mein Profil im Schatzamt-Portal (/schatzamt/profil/) – man bleibt im Portal (Navigation „Weiteres → Mein Profil“).

Reiter:
* Übersicht: Discord-Konto, Angaben aus der Bürgerakte, eigene Konten (ohne Salden – „Mein Geld“ ist mit der Bank-PIN geschützt), Bankkarte, Verweise.
* Darstellung: Transparenz der Glaselemente (0 = deckend … 100 = sehr durchsichtig), Unschärfe, Bewegung, Dichte, Startansicht (Staatl./Privat).
  Wirkt auf allen Seiten des Portals: schatzamt.ant hängt darstellung_css() an (CSS-Variablen aus rp_glas.py). Live-Vorschau beim Schieben.
* Benachrichtigungen: Discord-DMs des Bots je Art an/aus (benachrichtigung.ARTEN), Mindestbetrag für Zahlungseingänge, Ruhezeit, Test-Nachricht.
* Konto & Sicherheit: Bankkarte & PIN, Sitzungen (auf allen anderen Geräten abmelden), Abmelden.
Speicher: nutzer_einstellungen (post.einstellung/einstellung_setzen), Schlüssel sa_* und dm_*.
"""
import time

from aiohttp import web

import amt
import anmeldung
import benachrichtigung as bn
import config
import db
import geld
import post
import schatzamt as sa

esc = amt.esc
PFAD = sa.PFAD + "profil/"

STANDARD = {"sa_glas": "50", "sa_blur": "normal", "sa_bewegung": "normal", "sa_dichte": "normal", "sa_start": "zuletzt"}
BLUR = {"stark": 34, "normal": 22, "leicht": 10, "aus": 0}


def wert(con, kid, s):
    return post.einstellung(con, kid, s, STANDARD.get(s, ""))


def _alphas(t):
    """Transparenz t (0–100) → Deckkraft der Flächen. t = 50 ergibt genau die Werte aus rp_glas.py."""
    t = max(0, min(100, t)) / 100
    f = lambda voll, mitte: round(1 - (1 - mitte) * t * 2, 3)   # linear: t=0 → 1, t=.5 → mitte, t=1 → 2·mitte−1
    return {"glas": f(1, .62), "glas-kopf": f(1, .55), "glas-leiste": f(1, .6), "glas-blatt": f(1, .78), "glas-sheet": f(1, .9), "glas-dicht": f(1, .8)}


def vars_css(t, blur):
    a = _alphas(t)
    v = ";".join(f"--{n}:rgba(255,255,255,{max(.12, x)})" for n, x in a.items())
    b = BLUR.get(blur, 22)
    v += f';--glas-blur:{"none" if not b else f"saturate(180%) blur({b}px)"}'
    return f"html:root{{{v}}}"


def darstellung_css(con, k):
    """<style> mit den persönlichen Einstellungen (leer, wenn alles Standard ist)."""
    if not k:
        return ""
    t = wert(con, k["id"], "sa_glas")
    t = int(t) if t.isdigit() else 50
    blur, bew, dichte = wert(con, k["id"], "sa_blur"), wert(con, k["id"], "sa_bewegung"), wert(con, k["id"], "sa_dichte")
    css = []
    if t != 50 or blur != "normal":
        css.append(vars_css(t, blur))
    if bew == "ruhig":
        css.append("html:root *,html:root *::before,html:root *::after{animation:none!important;transition:none!important}")
    if dichte == "kompakt":
        css.append("html:root main{padding-top:18px}html:root th,html:root td{padding-top:6px!important;padding-bottom:6px!important}"
                   "html:root .kennzahlen div{padding:8px 12px}html:root .kennzahlen b{font-size:20px!important}html:root h2{margin-top:22px!important}"
                   "html:root .seite a.ein{padding-top:6px;padding-bottom:6px}html:root .rp-kachel,html:root .st-karte{padding:10px 12px}")
    return f'<style id="sa-persoenlich">{"".join(css)}</style>' if css else ""


def startmodus(con, k):
    """Gewählte Startansicht ('staat'/'privat') oder None (= zuletzt benutzte)."""
    if not k:
        return None
    m = wert(con, k["id"], "sa_start")
    return m if m in ("staat", "privat") else None


# ---------------------------------------------------------------- Seite

CSS = """<style>
.pf-kopf{display:flex;align-items:center;gap:16px;margin:4px 0 16px}
.pf-bild{width:64px;height:64px;border-radius:20px;object-fit:cover;flex:none;box-shadow:0 4px 14px rgba(16,24,40,.14)}
.pf-ini{width:64px;height:64px;border-radius:20px;display:grid;place-items:center;background:var(--ink);color:#fff;font:600 22px/1 var(--schrift);flex:none}
.pf-kopf h1{margin:0}
.pf-kopf p{margin:2px 0 0;color:var(--grau);font-size:14px}
.pf-raster{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:16px;margin:12px 0}
.pf-karte{border:1px solid var(--linie);border-radius:20px;background:#fff;padding:16px 18px}
.pf-karte h3{margin:0 0 10px;font-size:15.5px;display:flex;align-items:center;gap:8px}
.pf-karte h3 .icon{color:var(--grau)}
.pf-karte dl{display:grid;grid-template-columns:minmax(120px,40%) 1fr;gap:6px 14px;margin:0;font-size:14px}
.pf-karte dt{color:var(--grau)}
.pf-karte dd{margin:0;min-width:0;overflow-wrap:anywhere}
.pf-links{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.pf-links a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;color:var(--ink);text-decoration:none;border:1px solid var(--linie);background:rgba(255,255,255,.6)}
.pf-links a:hover{border-color:var(--ink)}
.pf-links small{margin-left:auto;color:var(--grau)}
.pf-zeile{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 0;border-bottom:1px solid #eef0f2}
.pf-zeile:last-child{border-bottom:0}
.pf-zeile>div:first-child{min-width:0}
.pf-zeile b{display:block;font-size:14.5px;font-weight:600}
.pf-zeile small{display:block;color:var(--grau);font-size:12.5px;line-height:1.4}
.pf-zeile select,.pf-zeile input[type=number]{flex:none;max-width:170px}
.pf-regler{display:flex;align-items:center;gap:10px;flex:none;width:min(260px,52%)}
.pf-regler input{flex:1;accent-color:var(--akzent)}
.pf-regler output{width:44px;text-align:right;font-variant-numeric:tabular-nums;font-size:13px;color:var(--grau)}
.pf-schalter{position:relative;flex:none;width:46px;height:28px}
.pf-schalter input{position:absolute;inset:0;opacity:0;margin:0;cursor:pointer;z-index:1}
.pf-schalter i{position:absolute;inset:0;border-radius:999px;background:#d9dce1;transition:background .2s}
.pf-schalter i::after{content:"";position:absolute;top:3px;left:3px;width:22px;height:22px;border-radius:50%;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.2);transition:transform .25s cubic-bezier(.2,.9,.25,1.12)}
.pf-schalter input:checked+i{background:var(--akzent)}
.pf-schalter input:checked+i::after{transform:translateX(18px)}
.pf-schalter input:disabled+i{opacity:.55}
.pf-schalter input:focus-visible+i{outline:2px solid var(--akzent);outline-offset:2px}
.pf-gruppe{margin:18px 0 2px;font-size:11.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#8b8f96}
.pf-ruhe{display:flex;align-items:center;gap:8px;flex:none}
.pf-vorschau{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:6px 0 4px}
.pf-vorschau div{height:54px;border-radius:16px;border:1px solid rgba(255,255,255,.75);display:grid;place-items:center;font-size:12px;color:var(--grau);
 box-shadow:0 10px 30px rgba(16,24,40,.08)}
.pf-vorschau .v1{background:var(--glas);-webkit-backdrop-filter:var(--glas-blur);backdrop-filter:var(--glas-blur)}
.pf-vorschau .v2{background:var(--glas-dicht)}
.pf-hinter{position:relative;border-radius:18px;padding:12px;background:repeating-linear-gradient(135deg,#e9ecf2 0 14px,#f6f7f9 14px 28px)}
@media (max-width:560px){.pf-zeile{flex-wrap:wrap}.pf-regler{width:100%}.pf-zeile select{max-width:none;width:100%}}
</style>"""


def _initialen(n):
    t = [x for x in str(n or "?").split() if x]
    return ((t[0][:1] + (t[-1][:1] if len(t) > 1 else "")) or "?").upper()


def _uebersicht(request, k, con):
    z = con.execute("SELECT * FROM amt_akten WHERE konto_id=? ORDER BY id DESC LIMIT 1", (k["id"],)).fetchone()
    if z:
        import meldewesen
        daten = [("Name im Spiel", z["ic_name"] or "– noch nicht erfasst"), ("Status", amt.STATUS_AKTE.get(z["status"], z["status"])),
                 ("Fraktion", z["fraktion"] or "–"), ("Beruf / Position", z["position"] or z["beruf"] or "–"), ("Aktenzeichen", amt.az_akte(z["id"]))]
        ws = meldewesen.wohnsitz(con, z["id"])
        if ws:
            daten.insert(2, ("Wohnsitz", "Ausland" if ws["art"] == "abmeldung" else ws["staat_name"]))
        akte = "<dl>" + "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in daten) + "</dl>"
    else:
        akte = '<p class="az">Für dich ist noch keine Bürgerakte angelegt. Sie entsteht mit der Einbürgerung über die Reichsverwaltung.</p>'
    konten = [r for r in geld.verfuegbare_konten(con, k) if r["art"] in ("privat", "gewerbe")]
    kz = "".join(f'<li><a href="{sa.PFAD}konto/?konto={r["id"]}">{amt.ic("wallet")}<span>{esc(r["name"])}</span>'
                 f'<small class="sa-nr">{geld.nummer_anzeige(r["nummer"])}</small></a></li>' for r in konten) or '<li class="az">Noch kein Konto.</li>'
    karte = con.execute("SELECT * FROM bk_karten WHERE konto_id=? ORDER BY id DESC LIMIT 1", (k["id"],)).fetchone()
    kt = ({"aktiv": "aktiv", "gesperrt": "gesperrt", "ersetzt": "ersetzt"}.get(karte["status"], karte["status"]) + f' · …{karte["nummer"][-4:]}') if karte else "keine Karte"
    links = [(sa.PFAD + "bankkarte/", "credit-card", "Bankkarte & PIN", kt), ("/profil/dokumente/", "file-text", "Meine Dokumente (Pässe)", "Website"),
             (amt.BASIS + "postfach/", "mail", "Postfach", "")]
    if anmeldung._amt_zugang(k):
        links.append((amt.BASIS, "layout-grid", "Amtsseite", ""))
    li = "".join(f'<li><a href="{esc(u)}">{amt.ic(i)}<span>{esc(t)}</span><small>{esc(z_)}</small></a></li>' for u, i, t, z_ in links)
    return ('<div class="pf-raster">'
            f'<section class="pf-karte"><h3>{amt.ic("book-user")}Angaben im Reich</h3>{akte}'
            '<p class="az" style="margin:10px 0 0;font-size:12.5px">Aus deiner Bürgerakte. Änderungen über die Reichsverwaltung.</p></section>'
            f'<section class="pf-karte"><h3>{amt.ic("wallet")}Meine Konten</h3><ul class="pf-links">{kz}</ul>'
            '<p class="az" style="margin:10px 0 0;font-size:12.5px">Kontostände siehst du unter „Mein Geld“ (mit Bank-PIN).</p></section>'
            f'<section class="pf-karte"><h3>{amt.ic("arrow-right")}Schnellzugriff</h3><ul class="pf-links">{li}</ul></section></div>')


def _zeile(titel, text, feld):
    return f'<div class="pf-zeile"><div><b>{esc(titel)}</b><small>{esc(text)}</small></div>{feld}</div>'


def _select(name, opts, wert_):
    return f'<select name="{name}" aria-label="{esc(name)}">' + "".join(f'<option value="{v}"{" selected" if v == wert_ else ""}>{esc(t)}</option>' for v, t in opts) + "</select>"


def _darstellung(request, k, con):
    w = lambda s: wert(con, k["id"], s)
    t = int(w("sa_glas")) if w("sa_glas").isdigit() else 50
    zeilen = [
        _zeile("Transparenz der Glasflächen", "0 = deckend weiß, 100 = sehr durchsichtig. Gilt für Seitenleiste, Kopf, Leiste am Handy, Karten und Fenster.",
               f'<div class="pf-regler"><input type="range" name="sa_glas" id="pf-glas" min="0" max="100" step="5" value="{t}" aria-label="Transparenz">'
               f'<output id="pf-glas-wert">{t}</output></div>'),
        _zeile("Unschärfe hinter Glas", "Wie stark der Inhalt hinter Glasflächen verschwimmt.",
               _select("sa_blur", [("stark", "Stark"), ("normal", "Normal"), ("leicht", "Leicht"), ("aus", "Aus")], w("sa_blur"))),
        _zeile("Bewegung", "Federnde Animationen beim Öffnen von Fenstern und Wechseln von Reitern.",
               _select("sa_bewegung", [("normal", "Normal"), ("ruhig", "Ruhig")], w("sa_bewegung"))),
        _zeile("Dichte", "Kompakt zeigt mehr Zeilen auf einmal (kleinere Abstände).",
               _select("sa_dichte", [("normal", "Normal"), ("kompakt", "Kompakt")], w("sa_dichte"))),
    ]
    if sa.hat_staat(con, k):
        zeilen.append(_zeile("Startansicht", "Welche Ansicht beim Öffnen des Schatzamts erscheint.",
                             _select("sa_start", [("zuletzt", "Zuletzt benutzte"), ("staat", "Staatl."), ("privat", "Privat")], w("sa_start"))))
    vorschau = ('<div class="pf-hinter"><div class="pf-vorschau"><div class="v1">Seitenleiste &amp; Kopf</div><div class="v2">Karte</div></div></div>')
    js = ("<script>(function(){var r=document.getElementById('pf-glas'),o=document.getElementById('pf-glas-wert'),f=r&&r.form,s=document.getElementById('pf-live');"
          "if(!r)return;if(!s){s=document.createElement('style');s.id='pf-live';document.head.appendChild(s)}"
          "var M={glas:.62,'glas-kopf':.55,'glas-leiste':.6,'glas-blatt':.78,'glas-sheet':.9,'glas-dicht':.8},B={stark:34,normal:22,leicht:10,aus:0};"
          "function u(){var t=r.value/100,v=[];o.textContent=r.value;for(var n in M){v.push('--'+n+':rgba(255,255,255,'+Math.max(.12,1-(1-M[n])*t*2).toFixed(3)+')')}"
          "var b=B[f.sa_blur.value];v.push('--glas-blur:'+(b?'saturate(180%) blur('+b+'px)':'none'));s.textContent='html:root{'+v.join(';')+'}'}"
          "r.addEventListener('input',u);f.sa_blur.addEventListener('change',u)})();</script>")
    return (f'<form class="pf-karte" method="post" action="{PFAD}speichern">{amt.csrf_feld(request)}<input type="hidden" name="teil" value="darstellung">'
            f'<h3>{amt.ic("sliders-horizontal")}Darstellung</h3>{vorschau}{"".join(zeilen)}'
            f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button>'
            f'<button class="btn zweit" type="submit" name="zuruecksetzen" value="1">Standard wiederherstellen</button></div></form>' + js)


def _benachrichtigungen(request, k, con):
    regent = bool(geld.regierte_staatskassen(con, k)) or amt.ROLLE_KANZLER in k["rollen"]
    gruppen = {}
    for schl, titel, text, std, pflicht, gruppe in bn.ARTEN:
        if gruppe == "Teilstaat" and not regent:
            continue
        an = bn.an(con, k["id"], schl)
        feld = (f'<label class="pf-schalter"><input type="checkbox" name="dm_{schl}" value="1"{" checked" if an else ""}{" disabled" if pflicht else ""} '
                f'aria-label="{esc(titel)}"><i></i></label>')
        zusatz = ""
        if schl == "eingang":
            ab = bn.einstellung(con, k["id"], "dm_eingang_ab", "0")
            zusatz = (f'<div class="pf-zeile"><div><b>… erst ab einem Betrag von</b><small>Kleinere Eingänge ohne Nachricht (0 = jeder).</small></div>'
                      f'<input type="number" name="dm_eingang_ab" min="0" step="1" value="{esc(ab)}" aria-label="Mindestbetrag in Kronen" style="width:140px"></div>')
        gruppen.setdefault(gruppe, []).append(_zeile(titel, text, feld) + zusatz)
    r = bn.ruhezeit(con, k["id"])
    stunden = [("", "–")] + [(str(h), f"{h:02d}:00") for h in range(24)]
    ruhe = _zeile("Ruhezeit", "Nachrichten in dieser Zeit kommen gesammelt danach (deutsche Zeit).",
                  f'<div class="pf-ruhe">{_select("dm_ruhe_von", stunden, str(r[0]) if r else "")}<span>bis</span>'
                  f'{_select("dm_ruhe_bis", stunden, str(r[1]) if r else "")}</div>')
    teile = "".join(f'<p class="pf-gruppe">{esc(g)}</p>' + "".join(z) for g, z in gruppen.items())
    return (f'<form class="pf-karte" method="post" action="{PFAD}speichern">{amt.csrf_feld(request)}<input type="hidden" name="teil" value="benachrichtigungen">'
            f'<h3>{amt.ic("mail")}Nachrichten des Bots</h3><p class="az" style="margin:0 0 4px">Der Discord-Bot schreibt dir eine Direktnachricht, wenn …</p>'
            f'{teile}<p class="pf-gruppe">Zeit</p>{ruhe}'
            f'<div class="aktionen"><button class="btn" type="submit">{amt.ic("check")}Speichern</button>'
            f'<button class="btn zweit" type="submit" formaction="{PFAD}test">Test-Nachricht senden</button></div>'
            '<p class="az" style="margin:10px 0 0;font-size:12.5px">Kommt nichts an? In Discord müssen Direktnachrichten von Servermitgliedern erlaubt sein.</p></form>')


def _sicherheit(request, k, con):
    n = con.execute("SELECT COUNT(*) FROM sitzungen WHERE konto_id=? AND laeuft_ab>?", (k["id"], int(time.time()))).fetchone()[0]
    c = amt.csrf_feld(request)
    return ('<div class="pf-raster">'
            f'<section class="pf-karte"><h3>{amt.ic("lock")}Anmeldung</h3>'
            + _zeile("Angemeldet über Discord", f'{k["name"]} · ID {k["id"]}', "")
            + _zeile("Aktive Sitzungen", f'{n} Gerät{"e" if n != 1 else ""} bzw. Browser mit deiner Anmeldung.',
                     f'<form method="post" action="{PFAD}abmelden-ueberall">{c}<button class="btn zweit" type="submit"{" disabled" if n < 2 else ""}>Andere abmelden</button></form>')
            + _zeile("Abmelden", "Nur auf diesem Gerät.", f'<form method="post" action="/abmelden/">{c}<input type="hidden" name="weiter" value="/">'
                                                         f'<button class="btn zweit gefahr" type="submit">Abmelden</button></form>')
            + "</section>"
            f'<section class="pf-karte"><h3>{amt.ic("credit-card")}Bankkarte & PIN</h3>'
            '<p class="az">Karte beantragen, sperren oder die PIN ändern. Ohne gültige Karte sind keine eigenen Überweisungen möglich.</p>'
            f'<div class="aktionen"><a class="btn zweit" href="{sa.PFAD}bankkarte/">{amt.ic("credit-card")}Zur Bankkarte</a></div></section></div>')


@sa.seite("mitglied")
async def seite(request, k):
    con = request.app["db"]
    bild = (f'<img class="pf-bild" src="{amt.BASIS}pass-foto/{esc(k["id"])}" alt="">' if k.get("avatar")
            else f'<span class="pf-ini" aria-hidden="true">{esc(_initialen(k["name"]))}</span>')
    kopf = (f'<div class="pf-kopf">{bild}<div><h1>{esc(k["name"])}</h1>'
            f'<p>Mein Profil · Einstellungen für das Schatzamt-Portal und die Nachrichten des Bots</p></div></div>{amt.meldung(request)}')
    teile = [("uebersicht", "Übersicht", _uebersicht(request, k, con)), ("darstellung", "Darstellung", _darstellung(request, k, con)),
             ("benachrichtigungen", "Benachrichtigungen", _benachrichtigungen(request, k, con)), ("sicherheit", "Konto & Sicherheit", _sicherheit(request, k, con))]
    hash_js = ('<script>addEventListener("hashchange",function(){var a=document.querySelector(\'.ts-nav a[data-t="\'+location.hash.slice(1)+\'"]\');'
               'if(a)a.click()})</script>')
    return sa.ant(request, k, "Mein Profil", "sa-profil", CSS + kopf + sa.untertabs(teile) + hash_js)


async def _post(request):
    k = await anmeldung.konto(request)
    if not k or not k["mitglied"]:
        raise web.HTTPFound("/anmelden/?weiter=" + PFAD)
    return k, await sa.formular(request), request.app["db"]


def _weiter(reiter, text):
    raise web.HTTPSeeOther(f"{PFAD}?m={__import__('urllib.parse').parse.quote(text)}#{reiter}")


async def speichern(request):
    k, form, con = await _post(request)
    teil = str(form.get("teil", ""))
    kid = k["id"]
    if teil == "darstellung":
        if form.get("zuruecksetzen"):
            con.execute("DELETE FROM nutzer_einstellungen WHERE konto_id=? AND schluessel LIKE 'sa\\_%' ESCAPE '\\'", (kid,))
            con.commit()
            _weiter("darstellung", "Darstellung auf Standard zurückgesetzt.")
        g = str(form.get("sa_glas", "50"))
        post.einstellung_setzen(con, kid, "sa_glas", str(max(0, min(100, int(g)))) if g.isdigit() else "50")
        for s, erlaubt in (("sa_blur", BLUR), ("sa_bewegung", ("normal", "ruhig")), ("sa_dichte", ("normal", "kompakt")), ("sa_start", ("zuletzt", "staat", "privat"))):
            v = str(form.get(s, STANDARD[s]))
            post.einstellung_setzen(con, kid, s, v if v in erlaubt else STANDARD[s])
        con.commit()
        _weiter("darstellung", "Darstellung gespeichert.")
    if teil == "benachrichtigungen":
        regent = bool(geld.regierte_staatskassen(con, k)) or amt.ROLLE_KANZLER in k["rollen"]
        for schl, _t, _x, _s, pflicht, gruppe in bn.ARTEN:
            if pflicht or (gruppe == "Teilstaat" and not regent):
                continue
            post.einstellung_setzen(con, kid, bn._schluessel(schl), "1" if form.get("dm_" + schl) else "0")
        ab = str(form.get("dm_eingang_ab", "0")).strip()
        post.einstellung_setzen(con, kid, "dm_eingang_ab", str(min(10 ** 9, int(ab))) if ab.isdigit() else "0")
        v, b = str(form.get("dm_ruhe_von", "")), str(form.get("dm_ruhe_bis", ""))
        ok = v.isdigit() and b.isdigit() and int(v) < 24 and int(b) < 24 and v != b
        post.einstellung_setzen(con, kid, "dm_ruhe_von", v if ok else "")
        post.einstellung_setzen(con, kid, "dm_ruhe_bis", b if ok else "")
        con.commit()
        _weiter("benachrichtigungen", "Benachrichtigungen gespeichert." + ("" if ok or not (v or b) else " Ruhezeit unvollständig – nicht gesetzt."))
    raise web.HTTPSeeOther(PFAD)


async def test(request):
    k, form, con = await _post(request)
    bn.vormerken(con, k["id"], "test", f"✅ Test-Nachricht aus deinem Profil im Schatzamt. So sehen Nachrichten des Bots aus.\n{config.SITE_URL}{PFAD}#benachrichtigungen")
    _weiter("benachrichtigungen", "Test-Nachricht ist unterwegs (kommt in wenigen Sekunden; Ruhezeit gilt für sie nicht).")


async def abmelden_ueberall(request):
    k, form, con = await _post(request)
    eigen = db._hash(request.cookies.get(config.SITZUNG_COOKIE, ""))
    n = con.execute("DELETE FROM sitzungen WHERE konto_id=? AND token_hash!=?", (k["id"], eigen)).rowcount
    con.commit()
    _weiter("sicherheit", f"Auf {n} anderen Gerät{'en' if n != 1 else ''} abgemeldet.")


def registrieren(app):
    r = app.router
    r.add_get(PFAD, seite)
    r.add_post(PFAD + "speichern", speichern)
    r.add_post(PFAD + "test", test)
    r.add_post(PFAD + "abmelden-ueberall", abmelden_ueberall)
