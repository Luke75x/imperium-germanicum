"""Einführung beim ersten Besuch im Schatzamt: „Lass uns dein Erlebnis anpassen“ (/schatzamt/willkommen/, seit 26.11.2026).

Nur im Schatzamt (Nutzervorgabe: nicht nach dem Login, nicht woanders). bankkarte.pin_sperre ruft pruefen() bei jedem HTML-GET im Schatzamt – noch vor der
Bank-PIN: Hat das Konto keinen Eintrag „einfuehrung“, zählt es als erster Besuch, außer es hat schon eine Bankkarte mit PIN (war also schon im
Schatzamt → still „fertig“). Erster Besuch → einfuehrung=offen und Weiterleitung hierher, danach an das eigentliche Ziel (?weiter=).
Schritte (ein Formular, Umschalten per JavaScript; ohne JavaScript steht alles untereinander):
  1. Willkommen  2. Aussehen (Themenbasiertes Design oder Schlicht)  3. Glas & Bewegung (Transparenz mit Vorschau, Bewegung, Dichte, ggf. Startansicht)
  4. Benachrichtigungen (Discord-DMs je Art)  5. Fertig.
Gespeichert wird erst am Ende in dieselben Schlüssel wie „Mein Profil“ im Schatzamt (profil_sa: sa_*, benachrichtigung: dm_*), dazu einfuehrung=fertig.
„Später“ speichert nur einfuehrung=fertig. Erneut aufrufen: Mein Profil → Darstellung → „Einführung erneut ansehen“.
"""
import html
import json
from urllib.parse import quote

from aiohttp import web

import amt
import anmeldung
import benachrichtigung as bn
import geld
import post
import profil_sa
import schatzamt as sa

PFAD = sa.PFAD + "willkommen/"
esc = html.escape


def offen(con, kid):
    """Einführung vorgemerkt und noch nicht abgeschlossen/übersprungen (bestehende Konten haben keinen Eintrag → nie offen)."""
    return post.einstellung(con, kid, "einfuehrung", "") == "offen"


def pruefen(request, con, k):
    """Middleware-Teil (bankkarte.pin_sperre): beim ersten Schatzamt-Besuch auf die Einführung umleiten."""
    if (not k or not k["mitglied"] or request.method != "GET" or request.path.startswith(PFAD)
            or "text/html" not in request.headers.get("Accept", "") or request.query.get("nur")):
        return
    w = post.einstellung(con, k["id"], "einfuehrung", "")
    if w == "fertig":
        return
    if not w:
        if con.execute("SELECT 1 FROM bk_karten WHERE konto_id=? AND pin_hash!=''", (k["id"],)).fetchone():
            post.einstellung_setzen(con, k["id"], "einfuehrung", "fertig")   # kennt das Schatzamt schon
            con.commit()
            return
        vormerken(con, k["id"])
    raise web.HTTPFound(ziel_url(request.path_qs))


def vormerken(con, kid):
    """Neues Konto: Einführung beim nächsten Seitenaufruf zeigen."""
    post.einstellung_setzen(con, kid, "einfuehrung", "offen")
    con.commit()


def ziel_url(weiter):
    return PFAD + "?weiter=" + quote(weiter or sa.PFAD, safe="/")


def _weiter(w):
    w = str(w or sa.PFAD)
    return w if w.startswith(sa.PFAD) and not w.startswith(PFAD) else sa.PFAD


CSS = """<style>
.ef{padding:clamp(8px,3vw,32px) 0 clamp(24px,5vw,56px)}
.ef-karte{position:relative;max-width:660px;margin:0 auto;background:var(--paper,#fbf9f4);border:1px solid var(--rule,#ddd5c3);box-shadow:0 30px 80px -30px rgba(18,24,60,.35),0 2px 6px rgba(18,24,60,.06);
 overflow:hidden;color:var(--ink,#161a2e)}
.ef-karte::before{content:"";position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,#000 0 33.3%,#d00 33.3% 66.6%,#ffcc21 66.6%)}
.ef-fort{display:flex;gap:6px;padding:22px 32px 0}
.ef-fort i{flex:1;height:3px;border-radius:2px;background:var(--rule,#ddd5c3);overflow:hidden;position:relative}
.ef-fort i::after{content:"";position:absolute;inset:0;background:var(--gold-500,#c9a43a);transform:scaleX(0);transform-origin:left;transition:transform .45s cubic-bezier(.2,.8,.2,1)}
.ef-fort i.an::after{transform:none}
.ef-buehne{position:relative;transition:height .4s cubic-bezier(.2,.8,.2,1)}
.ef-schritt{padding:26px 32px 30px}
.js .ef-schritt{position:absolute;inset:0 0 auto;opacity:0;visibility:hidden;transform:translateX(40px);transition:opacity .35s ease,transform .45s cubic-bezier(.2,.8,.2,1),visibility 0s .45s}
.js .ef-schritt.zurueck{transform:translateX(-40px)}
.js .ef-schritt.aktiv{position:relative;opacity:1;visibility:visible;transform:none;transition:opacity .35s ease .08s,transform .45s cubic-bezier(.2,.8,.2,1) .04s,visibility 0s}
.ef-augen{display:block;font:600 11.5px/1 var(--sans,system-ui);letter-spacing:.16em;text-transform:uppercase;color:var(--gold-600,#9a7618);margin:0 0 10px}
html:root .ef h1,html:root .ef h2{text-transform:none;letter-spacing:0;border:0;padding:0;font-family:var(--serif,Georgia,serif);font-weight:500;color:var(--ink,#161a2e);margin:0 0 8px;line-height:1.15}
html:root .ef h1{font-size:clamp(30px,5vw,40px)}
html:root .ef h2{font-size:clamp(24px,4vw,30px)}
html:root .ef .btn-navy{background:var(--navy-900,#12183c);color:#fff}
.ef p.lead{color:var(--muted,#646778);font-size:16.5px;line-height:1.55;margin:0 0 6px}
.ef-person{display:flex;align-items:center;gap:14px;margin:4px 0 22px}
.ef-person img,.ef-person .ini{width:60px;height:60px;border-radius:50%;object-fit:cover;flex:none;box-shadow:0 0 0 3px var(--paper,#fff),0 0 0 4px var(--gold-500,#c9a43a)}
.ef-person .ini{display:grid;place-items:center;background:var(--navy-900,#12183c);color:#fff;font:600 21px/1 var(--sans,system-ui)}
.ef-person b{display:block;font-size:17px}
.ef-person small{color:var(--muted,#646778);font-size:13.5px}
.ef-liste{list-style:none;margin:18px 0 0;padding:0;display:grid;gap:10px}
.ef-liste li{display:flex;gap:12px;align-items:flex-start;font-size:15px;color:var(--ink-2,#3a3e52)}
.ef-liste li span{flex:none;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;border:1px solid var(--rule-strong,#bfb294);font:600 12px/1 var(--sans,system-ui);color:var(--gold-700,#7a5c12)}
.ef-aktionen{display:flex;gap:10px;justify-content:space-between;align-items:center;margin-top:26px;flex-wrap:wrap}
.ef-aktionen .rechts{display:flex;gap:10px;margin-left:auto}
.ef-leise{background:none;border:0;color:var(--muted,#646778);font:inherit;font-size:14px;cursor:pointer;padding:8px 4px;text-decoration:underline;text-underline-offset:3px}
.ef-leise:hover{color:var(--ink,#161a2e)}
.ef .btn{cursor:pointer;border:1px solid transparent;font:600 14.5px/1 var(--sans,system-ui);padding:13px 20px}
.ef .btn-line{background:transparent;border-color:var(--rule-strong,#bfb294);color:var(--ink,#161a2e)}
/* Auswahlkarten */
.ef-wahl{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:20px 0 4px}
.ef-wahl label{position:relative;display:block;border:1.5px solid var(--rule,#ddd5c3);background:var(--white,#fff);padding:12px 12px 14px;cursor:pointer;transition:border-color .2s,box-shadow .2s,transform .2s}
.ef-wahl label:hover{transform:translateY(-2px);box-shadow:0 10px 24px -12px rgba(18,24,60,.3)}
.ef-wahl input{position:absolute;opacity:0;pointer-events:none}
.ef-wahl label:has(input:checked){border-color:var(--navy-700,#2b3570);box-shadow:0 0 0 3px rgba(43,53,112,.14)}
.ef-wahl label:has(input:focus-visible){outline:2px solid var(--gold-500,#c9a43a);outline-offset:2px}
.ef-wahl b{display:flex;align-items:center;justify-content:space-between;font-size:15.5px;margin:12px 0 3px}
.ef-wahl b::after{content:"";width:18px;height:18px;border-radius:50%;border:1.5px solid var(--rule-strong,#bfb294);box-sizing:border-box;transition:all .2s}
.ef-wahl label:has(input:checked) b::after{border:5px solid var(--navy-700,#2b3570)}
.ef-wahl small{display:block;color:var(--muted,#646778);font-size:13px;line-height:1.4}
.ef-mini{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;height:84px}
.ef-mini div{position:relative;border-radius:3px;overflow:hidden;box-shadow:inset 0 0 0 1px rgba(0,0,0,.12)}
.ef-mini .pt{background:radial-gradient(circle at 50% 22%,#c0291c 0 3px,transparent 3.5px),linear-gradient(rgba(70,74,40,.2) 1px,transparent 1px) 0 0/10px 10px,linear-gradient(90deg,rgba(70,74,40,.2) 1px,transparent 1px) 0 0/10px 10px,#e6dcb8}
.ef-mini .lw{background:linear-gradient(90deg,#c62828 0 33%,#1d7a3c 33% 66%,#1f4e8c 66%) left 6px bottom 8px/calc(100% - 12px) 3px no-repeat,#1a1f22}
.ef-mini .lw::after{content:"60,6";position:absolute;left:7px;top:12px;font:700 15px/1 ui-monospace,Menlo,monospace;color:#ffb547;text-shadow:0 0 6px rgba(255,170,40,.6)}
.ef-mini .ko{background:linear-gradient(90deg,transparent 8px,rgba(185,40,40,.5) 8px 9px,transparent 9px),repeating-linear-gradient(transparent 0 9px,rgba(60,100,170,.25) 9px 10px),#f6efdc}
.ef-mini .tr{background:linear-gradient(160deg,#fcf1bd,#e6c35a 35%,#bf972f 60%,#f6e39a) center 60%/70% 34% no-repeat,repeating-linear-gradient(90deg,rgba(255,255,255,.3) 0 1px,transparent 1px 3px),#cfd4d9}
.ef-schlicht{height:84px;border-radius:3px;background:radial-gradient(circle at 20% 0,rgba(31,78,140,.12),transparent 60%),#eef0f3;position:relative;box-shadow:inset 0 0 0 1px rgba(0,0,0,.08)}
.ef-schlicht::before{content:"";position:absolute;left:8px;top:8px;bottom:8px;width:26%;border-radius:8px;background:rgba(255,255,255,.75);box-shadow:0 4px 12px rgba(16,24,40,.08)}
.ef-schlicht::after{content:"";position:absolute;left:36%;right:8px;top:8px;height:38%;border-radius:8px;background:#fff;box-shadow:0 4px 12px rgba(16,24,40,.08)}
.ef-namen{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:5px;font-size:10.5px;color:var(--muted,#646778);text-align:center}
/* Zeilen mit Regler/Umschalter */
.ef-zeile{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 0;border-bottom:1px solid var(--rule,#ddd5c3)}
.ef-zeile:last-child{border-bottom:0}
.ef-zeile>div:first-child{min-width:0}
.ef-zeile b{display:block;font-size:15px;font-weight:600}
.ef-zeile small{display:block;color:var(--muted,#646778);font-size:13px;line-height:1.4}
.ef-seg{display:inline-flex;flex:none;border:1px solid var(--rule-strong,#bfb294);border-radius:999px;padding:3px;background:var(--white,#fff)}
.ef-seg label{position:relative;cursor:pointer}
.ef-seg input{position:absolute;opacity:0;pointer-events:none}
.ef-seg span{display:block;padding:7px 14px;border-radius:999px;font-size:13.5px;font-weight:600;color:var(--muted,#646778);transition:background .2s,color .2s}
.ef-seg input:checked+span{background:var(--navy-900,#12183c);color:#fff}
.ef-seg input:focus-visible+span{outline:2px solid var(--gold-500,#c9a43a)}
.ef-regler{display:flex;align-items:center;gap:10px;flex:none;width:min(240px,50%)}
.ef-regler input{flex:1;accent-color:var(--navy-700,#2b3570)}
.ef-regler output{width:34px;text-align:right;font-variant-numeric:tabular-nums;font-size:13px;color:var(--muted,#646778)}
.ef-glas{position:relative;height:92px;border-radius:14px;margin:18px 0 6px;overflow:hidden;
 background:radial-gradient(circle at 18% 30%,#c62828 0 18px,transparent 19px),radial-gradient(circle at 46% 70%,#1f4e8c 0 22px,transparent 23px),radial-gradient(circle at 80% 35%,#c9a43a 0 20px,transparent 21px),
 repeating-linear-gradient(135deg,#e9ecf2 0 12px,#f6f7f9 12px 24px)}
.ef-glas div{position:absolute;inset:14px 16%;border-radius:16px;border:1px solid rgba(255,255,255,.75);display:grid;place-items:center;font-size:13px;color:#3a3e52;
 box-shadow:0 10px 30px rgba(16,24,40,.12),inset 0 1px 0 rgba(255,255,255,.9);background:rgba(255,255,255,.62);-webkit-backdrop-filter:saturate(180%) blur(14px);backdrop-filter:saturate(180%) blur(14px);transition:background .15s}
.ef-schalter{position:relative;flex:none;width:46px;height:28px}
.ef-schalter input{position:absolute;inset:0;opacity:0;margin:0;cursor:pointer;z-index:1}
.ef-schalter i{position:absolute;inset:0;border-radius:999px;background:var(--rule,#d9dce1);transition:background .2s}
.ef-schalter i::after{content:"";position:absolute;top:3px;left:3px;width:22px;height:22px;border-radius:50%;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.2);transition:transform .25s cubic-bezier(.2,.9,.25,1.12)}
.ef-schalter input:checked+i{background:var(--navy-700,#2b3570)}
.ef-schalter input:checked+i::after{transform:translateX(18px)}
.ef-schalter input:focus-visible+i{outline:2px solid var(--gold-500,#c9a43a);outline-offset:2px}
.ef-gruppe{margin:18px 0 0;font:600 11px/1 var(--sans,system-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--gold-700,#7a5c12)}
/* Fertig */
.ef-haken{width:64px;height:64px;border-radius:50%;display:grid;place-items:center;background:var(--success-bg,#eef4ec);color:var(--success,#2f6b3a);margin:0 0 16px}
.ef-haken svg{width:32px;height:32px;stroke-dasharray:30;stroke-dashoffset:30}
.ef-schritt.aktiv .ef-haken svg{animation:ef-haken .6s ease .35s forwards}
@keyframes ef-haken{to{stroke-dashoffset:0}}
.ef-zusammen{list-style:none;padding:0;margin:16px 0 0;display:grid;gap:6px;font-size:14.5px;color:var(--ink-2,#3a3e52)}
.ef-zusammen li::before{content:"✓  ";color:var(--success,#2f6b3a);font-weight:700}
.ef-hinweis{font-size:13.5px;color:var(--muted,#646778);margin-top:16px}
@media (max-width:560px){.ef-schritt{padding:22px 20px 24px}.ef-fort{padding:18px 20px 0}.ef-wahl{grid-template-columns:1fr}.ef-zeile{flex-wrap:wrap}.ef-regler{width:100%}
 .ef-aktionen .rechts{width:100%}.ef-aktionen .rechts .btn{flex:1;text-align:center}}
@media (prefers-reduced-motion:reduce){.js .ef-schritt,.ef-buehne,.ef-fort i::after{transition:none!important}.ef-schritt.aktiv .ef-haken svg{animation:none;stroke-dashoffset:0}}
</style>"""

JS = """<script>(function(){var f=document.getElementById('ef'),S=[].slice.call(f.querySelectorAll('.ef-schritt')),F=[].slice.call(f.querySelectorAll('.ef-fort i')),
B=f.querySelector('.ef-buehne'),n=0;document.documentElement.classList.add('js');
function hoehe(){B.style.height=S[n].offsetHeight+'px'}
function zeige(i){var alt=n;n=Math.max(0,Math.min(S.length-1,i));if(n===S.length-1)zusammen();S.forEach(function(s,j){s.classList.toggle('aktiv',j===n);s.classList.toggle('zurueck',j<n)});
 F.forEach(function(x,j){x.classList.toggle('an',j<=n-1)});hoehe();if(n!==alt){var h=S[n].querySelector('h1,h2');if(h){h.setAttribute('tabindex','-1');h.focus({preventScroll:true})}}
 var r=f.getBoundingClientRect();if(r.top<90)scrollTo({top:scrollY+r.top-110,behavior:'smooth'})}
f.addEventListener('click',function(e){var b=e.target.closest('[data-geh]');if(!b)return;e.preventDefault();zeige(n+(+b.getAttribute('data-geh')))});
f.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target.tagName!=='BUTTON'&&n<S.length-1){e.preventDefault();zeige(n+1)}});
var r=f.querySelector('[name=sa_glas]'),o=f.querySelector('#ef-glas-wert'),g=f.querySelector('.ef-glas div');
function glas(){var t=r.value/100;o.textContent=r.value;g.style.background='rgba(255,255,255,'+Math.max(.12,1-(1-.62)*t*2).toFixed(3)+')'}
if(r){r.addEventListener('input',glas);glas()}
function wert(name){var x=f.querySelector('[name='+name+']:checked');return x?x.value:''}
function zusammen(){var l=[],t=wert('sa_thema')==='an';l.push(t?'Themenbasiertes Design – jeder Bereich im Look seines Arbeitsplatzes':'Schlichtes Glas-Design');
 l.push('Glas-Transparenz '+r.value+' von 100');l.push(wert('sa_bewegung')==='ruhig'?'Ruhige Darstellung ohne Animationen':'Animationen an');
 if(wert('sa_dichte')==='kompakt')l.push('Kompakte Ansicht');
 var d=f.querySelectorAll('.ef-dm input:checked').length,a=f.querySelectorAll('.ef-dm input').length;l.push(d?d+' von '+a+' Benachrichtigungen per Discord':'Keine Benachrichtigungen per Discord');
 f.querySelector('.ef-zusammen').innerHTML=l.map(function(x){return '<li>'+x.replace(/</g,'&lt;')+'</li>'}).join('')}
if(window.ResizeObserver){var ro=new ResizeObserver(hoehe);S.forEach(function(s){ro.observe(s)})}else addEventListener('resize',hoehe);
zeige(0)})();</script>"""


def _seg(name, opts, wert):
    return '<div class="ef-seg" role="radiogroup">' + "".join(
        f'<label><input type="radio" name="{name}" value="{v}"{" checked" if v == wert else ""}><span>{esc(t)}</span></label>' for v, t in opts) + "</div>"


def _zeile(titel, text, feld):
    return f'<div class="ef-zeile"><div><b>{esc(titel)}</b><small>{esc(text)}</small></div>{feld}</div>'


def _aktionen(zurueck=True, weiter="Weiter", ueberspringen=False):
    links = ('<button class="ef-leise" type="submit" name="spaeter" value="1" formnovalidate>Später</button>' if ueberspringen else
             '<button class="ef-leise" type="button" data-geh="-1">Zurück</button>' if zurueck else "<span></span>")
    return f'<div class="ef-aktionen">{links}<div class="rechts"><button class="btn btn-navy" type="button" data-geh="1">{esc(weiter)}</button></div></div>'


def seite_html(request, k):
    con = request.app["db"]
    kid = k["id"]
    w = lambda s: profil_sa.wert(con, kid, s)
    weiter = _weiter(request.query.get("weiter"))
    vorname = k["name"]
    bild = (f'<img src="{amt.BASIS}pass-foto/{esc(kid)}" alt="">' if k.get("avatar")
            else f'<span class="ini">{esc("".join(t[:1] for t in vorname.split()[:2]).upper() or "?")}</span>')
    t = int(w("sa_glas")) if w("sa_glas").isdigit() else 50
    regent = bool(geld.regierte_staatskassen(con, k)) or amt.ROLLE_KANZLER in k["rollen"]
    arten = [a for a in bn.ARTEN if not a[4] and (a[5] != "Teilstaat" or regent)]
    gruppen = {}
    for a in arten:
        gruppen.setdefault(a[5], []).append(a)
    dm = "".join(f'<p class="ef-gruppe">{esc(g)}</p>' + "".join(
        _zeile(titel, text, f'<label class="ef-schalter"><input type="checkbox" name="dm_{schl}" value="1"{" checked" if bn.an(con, kid, schl) else ""} aria-label="{esc(titel)}"><i></i></label>')
        for schl, titel, text, *_ in liste) for g, liste in gruppen.items())
    start = ""
    if sa.hat_staat(con, k):
        start = _zeile("Startansicht im Schatzamt", "Was du beim Öffnen des Schatzamts zuerst siehst.",
                       _seg("sa_start", [("zuletzt", "Zuletzt"), ("staat", "Staatl."), ("privat", "Privat")], w("sa_start")))
    thema = w("sa_thema") != "aus"
    schritte = [
        # 1 Willkommen
        f'''<section class="ef-schritt aktiv"><span class="ef-augen">Willkommen im Schatzamt</span>
<div class="ef-person">{bild}<div><b>{esc(vorname)}</b><small>Schön, dass du zum ersten Mal hier bist.</small></div></div>
<h1>Lass uns dein Erlebnis anpassen</h1>
<p class="lead">Drei kurze Fragen, dann kann es losgehen. Alles lässt sich später unter <i>Mein Profil</i> ändern.</p>
<ul class="ef-liste"><li><span>1</span>Wie das Schatzamt aussehen soll</li><li><span>2</span>Glas, Bewegung und Dichte</li><li><span>3</span>Worüber dich der Bot auf Discord informiert</li></ul>
{_aktionen(weiter="Los geht’s", ueberspringen=True)}</section>''',
        # 2 Aussehen
        f'''<section class="ef-schritt"><span class="ef-augen">Schritt 1 von 3 · Aussehen</span>
<h2>Wie soll es aussehen?</h2>
<p class="lead">Im Schatzamt kann jeder Bereich wie sein echter Arbeitsplatz aussehen – oder überall gleich und schlicht.</p>
<div class="ef-wahl">
<label><input type="radio" name="sa_thema" value="an"{" checked" if thema else ""}>
<div class="ef-mini"><div class="pt"></div><div class="lw"></div><div class="ko"></div><div class="tr"></div></div>
<div class="ef-namen"><span>Plantisch</span><span>Leitwarte</span><span>Kontor</span><span>Tresor</span></div>
<b>Themenbasiert</b><small>Verteidigung als Plantisch, Energie als Leitwarte, Handel als Kontor … mit Umbau-Animation beim Wechsel.</small></label>
<label><input type="radio" name="sa_thema" value="aus"{"" if thema else " checked"}>
<div class="ef-schlicht"></div><div class="ef-namen"><span></span><span></span><span></span><span></span></div>
<b>Schlicht</b><small>Überall das helle Glas-Design – ruhig und einheitlich.</small></label>
</div>
{_aktionen()}</section>''',
        # 3 Glas & Bewegung
        f'''<section class="ef-schritt"><span class="ef-augen">Schritt 2 von 3 · Darstellung</span>
<h2>Glas, Bewegung und Dichte</h2>
<p class="lead">Seitenleiste, Kopf und Fenster sind aus Glas. Wie durchsichtig darf es sein?</p>
<div class="ef-glas"><div>Glasfläche</div></div>
{_zeile("Transparenz", "0 = deckend weiß, 100 = sehr durchsichtig.",
        f'<div class="ef-regler"><input type="range" name="sa_glas" min="0" max="100" step="5" value="{t}" aria-label="Transparenz"><output id="ef-glas-wert">{t}</output></div>')}
{_zeile("Bewegung", "Federnde Animationen und Übergänge zwischen den Bereichen.", _seg("sa_bewegung", [("normal", "Normal"), ("ruhig", "Ruhig")], w("sa_bewegung")))}
{_zeile("Dichte", "Kompakt zeigt mehr Zeilen auf einmal.", _seg("sa_dichte", [("normal", "Normal"), ("kompakt", "Kompakt")], w("sa_dichte")))}
{start}
{_aktionen()}</section>''',
        # 4 Benachrichtigungen
        f'''<section class="ef-schritt"><span class="ef-augen">Schritt 3 von 3 · Benachrichtigungen</span>
<h2>Was soll dir der Bot schreiben?</h2>
<p class="lead">Der Bot kann dir bei wichtigen Ereignissen eine Direktnachricht auf Discord schicken. Mitteilungen der RP-Leitung kommen immer.</p>
<div class="ef-dm">{dm}</div>
{_aktionen(weiter="Fertig")}</section>''',
        # 5 Fertig
        f'''<section class="ef-schritt"><div class="ef-haken"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>
<span class="ef-augen">Alles bereit</span><h2>So ist es eingestellt</h2>
<ul class="ef-zusammen"><li>Deine Auswahl</li></ul>
<p class="ef-hinweis">Ändern kannst du alles jederzeit unter Weiteres → <i>Mein Profil</i> → Darstellung.</p>
<div class="ef-aktionen"><button class="ef-leise" type="button" data-geh="-1">Zurück</button><div class="rechts"><button class="btn btn-navy" type="submit">Speichern und loslegen</button></div></div></section>''',
    ]
    fort = "".join("<i></i>" for _ in range(len(schritte) - 1))
    inhalt = (CSS + f'''<section class="ef"><div class="wrap">
<form class="ef-karte" id="ef" method="post" action="{PFAD}">{amt.csrf_feld(request)}<input type="hidden" name="weiter" value="{esc(weiter)}">
<div class="ef-fort" aria-hidden="true">{fort}</div><div class="ef-buehne">{"".join(schritte)}</div></form></div></section>''' + JS)
    return inhalt


@sa.seite("mitglied")
async def seite(request, k):
    return sa.ant(request, k, "Willkommen", "sa-willkommen", seite_html(request, k))


async def speichern(request):
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/")
    form = await sa.formular(request)
    con, kid = request.app["db"], k["id"]
    weiter = _weiter(form.get("weiter"))
    if not form.get("spaeter"):
        g = str(form.get("sa_glas", "50"))
        post.einstellung_setzen(con, kid, "sa_glas", str(max(0, min(100, int(g)))) if g.isdigit() else "50")
        for s, erlaubt in (("sa_thema", ("an", "aus")), ("sa_bewegung", ("normal", "ruhig")), ("sa_dichte", ("normal", "kompakt")), ("sa_start", ("zuletzt", "staat", "privat"))):
            v = str(form.get(s, profil_sa.STANDARD[s]))
            post.einstellung_setzen(con, kid, s, v if v in erlaubt else profil_sa.STANDARD[s])
        regent = bool(geld.regierte_staatskassen(con, k)) or amt.ROLLE_KANZLER in k["rollen"]
        for schl, _t, _x, _s, pflicht, gruppe in bn.ARTEN:
            if pflicht or (gruppe == "Teilstaat" and not regent):
                continue
            post.einstellung_setzen(con, kid, bn._schluessel(schl), "1" if form.get("dm_" + schl) else "0")
    post.einstellung_setzen(con, kid, "einfuehrung", "fertig")
    con.commit()
    raise web.HTTPSeeOther(weiter)


def registrieren(app):
    app.router.add_get(PFAD, seite)
    app.router.add_post(PFAD, speichern)
