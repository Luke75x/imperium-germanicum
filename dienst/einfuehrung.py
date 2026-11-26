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
amt.ICONS.setdefault("palette", '<circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/>'
                    '<circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/>'
                    '<path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>')   # Lucide
amt.ICONS.setdefault("bell", '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>')   # Lucide
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
/* Vollbild: übernimmt die ganze Seite (Seitenleiste, Kopf und Tableiste liegen darunter und bleiben verborgen). Gestaltung wie das Schatzamt (rp_glas). */
html:root body{overflow:hidden}
html:root .seite,html:root .kopf,html:root .tableiste,html:root .ladebalken{visibility:hidden}
html:root main#inhalt{animation:none;transform:none}
.ef-voll{position:fixed;inset:0;z-index:300;overflow-y:auto;overscroll-behavior:contain;color:var(--ink);font-family:var(--schrift);
 background:#f4f5f7;background-image:radial-gradient(1100px 620px at 12% -8%,rgba(31,78,140,.10),transparent 60%),radial-gradient(900px 560px at 100% 0%,rgba(22,23,26,.06),transparent 55%),
 radial-gradient(800px 600px at 50% 110%,rgba(31,78,140,.08),transparent 60%);animation:ef-rein .5s cubic-bezier(.2,.8,.2,1) both}
.ef-voll.raus{animation:ef-raus .4s cubic-bezier(.5,0,.75,0) forwards}
@keyframes ef-rein{from{opacity:0;transform:scale(1.02)}}
@keyframes ef-raus{to{opacity:0;transform:scale(.98)}}
.ef{min-height:100%;display:flex;flex-direction:column;max-width:640px;margin:0 auto;padding:max(18px,env(safe-area-inset-top)) 24px max(24px,env(safe-area-inset-bottom))}
.ef-kopf{display:flex;align-items:center;gap:18px;min-height:52px}
.ef-kopf img{height:40px;width:auto;flex:none}
.ef-fort{flex:1;display:flex;gap:6px}
.ef-fort i{flex:1;height:5px;border-radius:999px;background:rgba(22,23,26,.08);overflow:hidden;position:relative}
.ef-fort i::after{content:"";position:absolute;inset:0;border-radius:inherit;background:var(--akzent);transform:scaleX(0);transform-origin:left;transition:transform .5s cubic-bezier(.2,.8,.2,1)}
.ef-fort i.an::after{transform:none}
.ef-spaeter{flex:none;border:0;background:rgba(255,255,255,.7);border:1px solid rgba(255,255,255,.8);box-shadow:0 2px 8px rgba(16,24,40,.06);border-radius:999px;
 padding:8px 15px;font:600 13.5px/1 var(--schrift);color:var(--grau);cursor:pointer;transition:background .2s,color .2s}
.ef-spaeter:hover{background:#fff;color:var(--ink)}
.ef-mitte{flex:1;display:flex;flex-direction:column;justify-content:center;padding:28px 0 8px}
.ef-buehne{position:relative;transition:height .45s cubic-bezier(.2,.8,.2,1)}
.ef-schritt{padding:4px 0 6px}
.js .ef-schritt{position:absolute;inset:0 0 auto;opacity:0;visibility:hidden;transform:translateX(48px);transition:opacity .3s ease,transform .5s cubic-bezier(.2,.9,.25,1.05),visibility 0s .5s}
.js .ef-schritt.zurueck{transform:translateX(-48px)}
.js .ef-schritt.aktiv{position:relative;opacity:1;visibility:visible;transform:none;transition:opacity .35s ease .08s,transform .5s cubic-bezier(.2,.9,.25,1.05) .04s,visibility 0s}
.ef-augen{display:block;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#8b8f96;margin:0 0 10px}
html:root .ef h1,html:root .ef h2{font-family:var(--schrift);font-weight:700;letter-spacing:-.025em;color:var(--ink);margin:0 0 10px;line-height:1.1;text-transform:none;border:0;padding:0}
html:root .ef h1{font-size:clamp(32px,6vw,44px)}
html:root .ef h2{font-size:clamp(27px,5vw,34px)}
.ef p.lead{color:var(--grau);font-size:17px;line-height:1.5;margin:0 0 4px}
.ef-person{display:flex;align-items:center;gap:14px;margin:0 0 26px}
.ef-person img,.ef-person .ini{width:64px;height:64px;border-radius:20px;object-fit:cover;flex:none;box-shadow:0 6px 18px rgba(16,24,40,.16)}
.ef-person .ini{display:grid;place-items:center;background:var(--ink);color:#fff;font-weight:600;font-size:22px}
.ef-person b{display:block;font-size:17px}
.ef-person small{color:var(--grau);font-size:14px}
/* Glas-Gruppen wie in Mein Profil */
.ef-block{margin:22px 0 0;background:rgba(255,255,255,.8);border:1px solid rgba(255,255,255,.85);border-radius:22px;padding:4px 18px;
 box-shadow:0 10px 34px rgba(16,24,40,.08),0 1px 2px rgba(16,24,40,.05),inset 0 1px 0 rgba(255,255,255,.9)}
.ef-punkt{display:flex;align-items:center;gap:14px;padding:13px 0;border-bottom:1px solid rgba(22,23,26,.07);font-size:15.5px}
.ef-punkt:last-child{border-bottom:0}
.ef-punkt i{flex:none;width:36px;height:36px;border-radius:11px;display:grid;place-items:center;color:#fff}
.ef-punkt i .icon{width:19px;height:19px}
.ef-punkt small{display:block;color:var(--grau);font-size:13px;margin-top:1px}
.ef-aktionen{display:flex;gap:10px;justify-content:flex-end;align-items:center;margin-top:28px}
.ef-aktionen .btn{font-size:15.5px;padding:13px 26px;min-width:130px;justify-content:center}
.ef-aktionen .btn.zurueck{margin-right:auto;min-width:0}
/* Auswahlkarten */
.ef-wahl{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:24px 0 0}
.ef-wahl label{position:relative;display:block;background:rgba(255,255,255,.8);border:1px solid rgba(255,255,255,.85);border-radius:22px;padding:12px 12px 16px;cursor:pointer;
 box-shadow:0 10px 34px rgba(16,24,40,.08),inset 0 1px 0 rgba(255,255,255,.9);transition:transform .25s cubic-bezier(.2,.9,.25,1.12),box-shadow .25s}
.ef-wahl label:hover{transform:translateY(-2px);box-shadow:0 16px 40px rgba(16,24,40,.12)}
.ef-wahl label:active{transform:scale(.98)}
.ef-wahl input{position:absolute;opacity:0;pointer-events:none}
.ef-wahl label:has(input:checked){box-shadow:0 0 0 2.5px var(--akzent),0 14px 38px rgba(31,78,140,.18)}
.ef-wahl label:has(input:focus-visible){outline:2px solid var(--akzent);outline-offset:3px}
.ef-wahl b{display:flex;align-items:center;justify-content:space-between;font-size:16px;margin:12px 4px 3px}
.ef-wahl b::after{content:"";width:22px;height:22px;border-radius:50%;border:1.5px solid #c7cbd2;box-sizing:border-box;transition:all .2s;background:#fff center/14px no-repeat}
.ef-wahl label:has(input:checked) b::after{border-color:var(--akzent);background-color:var(--akzent);
 background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12.5l4.5 4.5L19 7.5'/%3E%3C/svg%3E")}
.ef-wahl small{display:block;color:var(--grau);font-size:13px;line-height:1.4;margin:0 4px}
.ef-mini{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;height:92px;border-radius:14px;overflow:hidden}
.ef-mini div{position:relative;overflow:hidden}
.ef-mini .pt{background:radial-gradient(circle at 50% 22%,#c0291c 0 3px,transparent 3.5px),linear-gradient(rgba(70,74,40,.2) 1px,transparent 1px) 0 0/10px 10px,linear-gradient(90deg,rgba(70,74,40,.2) 1px,transparent 1px) 0 0/10px 10px,#e6dcb8}
.ef-mini .lw{background:linear-gradient(90deg,#c62828 0 33%,#1d7a3c 33% 66%,#1f4e8c 66%) left 6px bottom 9px/calc(100% - 12px) 3px no-repeat,#1a1f22}
.ef-mini .lw::after{content:"60,6";position:absolute;left:7px;top:13px;font:700 15px/1 ui-monospace,Menlo,monospace;color:#ffb547;text-shadow:0 0 6px rgba(255,170,40,.6)}
.ef-mini .ko{background:linear-gradient(90deg,transparent 8px,rgba(185,40,40,.5) 8px 9px,transparent 9px),repeating-linear-gradient(transparent 0 9px,rgba(60,100,170,.25) 9px 10px),#f6efdc}
.ef-mini .tr{background:linear-gradient(160deg,#fcf1bd,#e6c35a 35%,#bf972f 60%,#f6e39a) center 60%/70% 34% no-repeat,repeating-linear-gradient(90deg,rgba(255,255,255,.3) 0 1px,transparent 1px 3px),#cfd4d9}
.ef-schlicht{height:92px;border-radius:14px;background:radial-gradient(circle at 20% 0,rgba(31,78,140,.14),transparent 60%),#eceff3;position:relative}
.ef-schlicht::before{content:"";position:absolute;left:8px;top:8px;bottom:8px;width:26%;border-radius:10px;background:rgba(255,255,255,.8);box-shadow:0 4px 12px rgba(16,24,40,.08)}
.ef-schlicht::after{content:"";position:absolute;left:36%;right:8px;top:8px;height:40%;border-radius:10px;background:#fff;box-shadow:0 4px 12px rgba(16,24,40,.08)}
.ef-namen{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:6px;font-size:10.5px;color:#8b8f96;text-align:center}
/* Zeilen */
.ef-zeile{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 0;border-bottom:1px solid rgba(22,23,26,.07)}
.ef-zeile:last-child{border-bottom:0}
.ef-zeile>div:first-child{min-width:0}
.ef-zeile b{display:block;font-size:15px;font-weight:600}
.ef-zeile small{display:block;color:var(--grau);font-size:12.5px;line-height:1.4}
.ef-seg{display:inline-flex;flex:none;border-radius:999px;padding:3px;background:rgba(22,23,26,.07);box-shadow:inset 0 1px 2px rgba(16,24,40,.06)}
.ef-seg label{position:relative;cursor:pointer}
.ef-seg input{position:absolute;opacity:0;pointer-events:none}
.ef-seg span{display:block;padding:7px 14px;border-radius:999px;font-size:13.5px;font-weight:600;color:var(--grau);transition:background .25s,color .25s,box-shadow .25s}
.ef-seg input:checked+span{background:#fff;color:var(--ink);box-shadow:0 2px 8px rgba(16,24,40,.14)}
.ef-seg input:focus-visible+span{outline:2px solid var(--akzent)}
.ef-regler{display:flex;align-items:center;gap:10px;flex:none;width:min(240px,50%)}
.ef-regler input{flex:1;accent-color:var(--akzent)}
.ef-regler output{width:34px;text-align:right;font-variant-numeric:tabular-nums;font-size:13px;color:var(--grau)}
.ef-glas{position:relative;height:110px;border-radius:22px;margin:22px 0 0;overflow:hidden;box-shadow:inset 0 0 0 1px rgba(22,23,26,.05);
 background:radial-gradient(circle at 18% 30%,#c62828 0 20px,transparent 21px),radial-gradient(circle at 46% 72%,#1f4e8c 0 26px,transparent 27px),radial-gradient(circle at 82% 35%,#c9a43a 0 22px,transparent 23px),
 repeating-linear-gradient(135deg,#e9ecf2 0 12px,#f6f7f9 12px 24px)}
.ef-glas div{position:absolute;inset:16px 14%;border-radius:18px;border:1px solid rgba(255,255,255,.75);display:grid;place-items:center;font-size:13px;color:var(--grau);
 box-shadow:0 10px 30px rgba(16,24,40,.12),inset 0 1px 0 rgba(255,255,255,.9);background:rgba(255,255,255,.62);-webkit-backdrop-filter:saturate(180%) blur(16px);backdrop-filter:saturate(180%) blur(16px)}
.ef-schalter{position:relative;flex:none;width:50px;height:30px}
.ef-schalter input{position:absolute;inset:0;opacity:0;margin:0;cursor:pointer;z-index:1}
.ef-schalter i{position:absolute;inset:0;border-radius:999px;background:#d9dce1;transition:background .2s}
.ef-schalter i::after{content:"";position:absolute;top:3px;left:3px;width:24px;height:24px;border-radius:50%;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.2);transition:transform .3s cubic-bezier(.2,.9,.25,1.12)}
.ef-schalter input:checked+i{background:var(--ok)}
.ef-schalter input:checked+i::after{transform:translateX(20px)}
.ef-schalter input:focus-visible+i{outline:2px solid var(--akzent);outline-offset:2px}
.ef-gruppe{margin:20px 4px 8px;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#8b8f96}
.ef-gruppe+.ef-block{margin-top:0}
/* Fertig */
.ef-haken{width:76px;height:76px;border-radius:24px;display:grid;place-items:center;background:var(--ok);color:#fff;margin:0 0 20px;box-shadow:0 12px 30px rgba(29,107,52,.3);transform:scale(.6);opacity:0}
.ef-schritt.aktiv .ef-haken{animation:ef-pop .55s cubic-bezier(.2,.9,.25,1.3) .15s forwards}
@keyframes ef-pop{to{transform:none;opacity:1}}
.ef-haken svg{width:38px;height:38px;stroke-dasharray:30;stroke-dashoffset:30}
.ef-schritt.aktiv .ef-haken svg{animation:ef-haken .5s ease .5s forwards}
@keyframes ef-haken{to{stroke-dashoffset:0}}
.ef-zusammen{list-style:none;margin:0;padding:0}
.ef-zusammen li{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid rgba(22,23,26,.07);font-size:15px}
.ef-zusammen li:last-child{border-bottom:0}
.ef-zusammen li::before{content:"";flex:none;width:20px;height:20px;border-radius:50%;background:var(--ok) center/12px no-repeat;
 background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12.5l4.5 4.5L19 7.5'/%3E%3C/svg%3E")}
.ef-hinweis{font-size:13.5px;color:var(--grau);margin:16px 4px 0}
@media (max-width:560px){.ef{padding-left:18px;padding-right:18px}.ef-kopf img{height:34px}.ef-mitte{justify-content:flex-start;padding-top:22px}
 .ef-wahl{grid-template-columns:1fr}.ef-zeile:has(.ef-regler),.ef-zeile:has(.ef-seg){flex-wrap:wrap}.ef-regler{width:100%}.ef-block{padding:2px 14px}
 .ef-aktionen{position:sticky;bottom:0;padding:14px 0 4px;margin-top:20px;background:linear-gradient(transparent,#f4f5f7 30%)}.ef-aktionen .btn:not(.zurueck){flex:1}}
@media (prefers-reduced-motion:reduce){.ef-voll,.js .ef-schritt,.ef-buehne,.ef-fort i::after{animation:none!important;transition:none!important}
 .ef-schritt.aktiv .ef-haken,.ef-schritt.aktiv .ef-haken svg{animation:none;opacity:1;transform:none;stroke-dashoffset:0}}
</style>"""

JS = """<script>(function(){var f=document.getElementById('ef'),V=f.closest('.ef-voll');document.body.appendChild(V);   /* aus <main> lösen: dessen Animation (transform) würde position:fixed einsperren */
var S=[].slice.call(f.querySelectorAll('.ef-schritt')),F=[].slice.call(f.querySelectorAll('.ef-fort i')),
B=f.querySelector('.ef-buehne'),n=0;document.documentElement.classList.add('js');
function hoehe(){B.style.height=S[n].offsetHeight+'px'}
function zeige(i){var alt=n;n=Math.max(0,Math.min(S.length-1,i));if(n===S.length-1)zusammen();S.forEach(function(s,j){s.classList.toggle('aktiv',j===n);s.classList.toggle('zurueck',j<n)});
 F.forEach(function(x,j){x.classList.toggle('an',j<=n-1)});hoehe();V.scrollTo({top:0,behavior:'smooth'});
 if(n!==alt){var h=S[n].querySelector('h1,h2');if(h){h.setAttribute('tabindex','-1');h.focus({preventScroll:true})}}}
f.addEventListener('click',function(e){var b=e.target.closest('[data-geh]');if(!b)return;e.preventDefault();zeige(n+(+b.getAttribute('data-geh')))});
f.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target.tagName!=='BUTTON'&&n<S.length-1){e.preventDefault();zeige(n+1)}});
var fertig=false;f.addEventListener('submit',function(e){if(fertig)return;e.preventDefault();fertig=true;var sb=e.submitter;
 if(sb&&sb.name){var h=document.createElement('input');h.type='hidden';h.name=sb.name;h.value=sb.value;f.appendChild(h)}
 V.classList.add('raus');setTimeout(function(){f.submit()},matchMedia('(prefers-reduced-motion: reduce)').matches?0:380)});
var r=f.querySelector('[name=sa_glas]'),o=f.querySelector('#ef-glas-wert'),g=f.querySelector('.ef-glas div');
function glas(){var t=r.value/100;o.textContent=r.value;g.style.background='rgba(255,255,255,'+Math.max(.12,1-(1-.62)*t*2).toFixed(3)+')'}
if(r){r.addEventListener('input',glas);glas()}
function wert(name){var x=f.querySelector('[name='+name+']:checked');return x?x.value:''}
function zusammen(){var l=[],t=wert('sa_thema')==='an';l.push(t?'Themenbasiertes Design – jeder Bereich im Look seines Arbeitsplatzes':'Schlichtes Glas-Design');
 l.push({hell:'Helles Erscheinungsbild',dunkel:'Dunkelmodus',auto:'Hell oder dunkel wie dein Gerät'}[wert('sa_hell')]||'Helles Erscheinungsbild');l.push('Glas-Transparenz '+r.value+' von 100');l.push(wert('sa_bewegung')==='ruhig'?'Ruhige Darstellung ohne Animationen':'Animationen an');
 l.push(wert('sa_dichte')==='kompakt'?'Kompakte Ansicht':'Normale Abstände');
 var d=f.querySelectorAll('.ef-dm input:checked').length,a=f.querySelectorAll('.ef-dm input').length;l.push(d?d+' von '+a+' Benachrichtigungen per Discord':'Keine Benachrichtigungen per Discord');
 f.querySelector('.ef-zusammen').innerHTML=l.map(function(x){return '<li>'+x.replace(/</g,'&lt;')+'</li>'}).join('')}
if(window.ResizeObserver){var ro=new ResizeObserver(hoehe);S.forEach(function(s){ro.observe(s)})}else addEventListener('resize',hoehe);
zeige(0)})();</script>"""


def _seg(name, opts, wert):
    return '<div class="ef-seg" role="radiogroup">' + "".join(
        f'<label><input type="radio" name="{name}" value="{v}"{" checked" if v == wert else ""}><span>{esc(t)}</span></label>' for v, t in opts) + "</div>"


def _zeile(titel, text, feld):
    return f'<div class="ef-zeile"><div><b>{esc(titel)}</b><small>{esc(text)}</small></div>{feld}</div>'


def _aktionen(zurueck=True, weiter="Weiter"):
    links = '<button class="btn zweit zurueck" type="button" data-geh="-1">Zurück</button>' if zurueck else ""
    return f'<div class="ef-aktionen">{links}<button class="btn" type="button" data-geh="1">{esc(weiter)}</button></div>'


def _punkt(icon, farbe, titel, text):
    return f'<div class="ef-punkt"><i style="background:{farbe}">{amt.ic(icon)}</i><div>{esc(titel)}<small>{esc(text)}</small></div></div>'


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
    dm = "".join(f'<p class="ef-gruppe">{esc(g)}</p><div class="ef-block">' + "".join(
        _zeile(titel, text, f'<label class="ef-schalter"><input type="checkbox" name="dm_{schl}" value="1"{" checked" if bn.an(con, kid, schl) else ""} aria-label="{esc(titel)}"><i></i></label>')
        for schl, titel, text, *_ in liste) + "</div>" for g, liste in gruppen.items())
    start = ""
    if sa.hat_staat(con, k):
        start = _zeile("Startansicht", "Was du beim Öffnen des Schatzamts zuerst siehst.",
                       _seg("sa_start", [("zuletzt", "Zuletzt"), ("staat", "Staatl."), ("privat", "Privat")], w("sa_start")))
    thema = w("sa_thema") != "aus"
    schritte = [
        # 1 Willkommen
        f'''<section class="ef-schritt aktiv"><div class="ef-person">{bild}<div><b>{esc(vorname)}</b><small>Willkommen im Schatzamt</small></div></div>
<h1>Lass uns dein Erlebnis anpassen</h1>
<p class="lead">Drei kurze Fragen, dann kann es losgehen. Alles lässt sich später unter <i>Mein Profil</i> ändern.</p>
<div class="ef-block">{_punkt("palette", "#1f4e8c", "Aussehen", "Themenbasiert oder schlicht")}{_punkt("sliders-horizontal", "#16171a", "Glas, Bewegung und Dichte", "Wie durchsichtig, wie lebendig, wie dicht")}{_punkt("bell", "#1d6b34", "Benachrichtigungen", "Worüber dich der Bot auf Discord informiert")}</div>
{_aktionen(zurueck=False, weiter="Los geht’s")}</section>''',
        # 2 Aussehen
        f'''<section class="ef-schritt"><span class="ef-augen">Schritt 1 von 3</span>
<h2>Wie soll es aussehen?</h2>
<p class="lead">Jeder Bereich im Look seines echten Arbeitsplatzes – oder überall gleich und schlicht.</p>
<div class="ef-wahl">
<label><input type="radio" name="sa_thema" value="an"{" checked" if thema else ""}>
<div class="ef-mini"><div class="pt"></div><div class="lw"></div><div class="ko"></div><div class="tr"></div></div>
<div class="ef-namen"><span>Plantisch</span><span>Leitwarte</span><span>Kontor</span><span>Tresor</span></div>
<b>Themenbasiert</b><small>Verteidigung als Plantisch, Energie als Leitwarte, Handel als Kontor … mit Umbau-Animation beim Wechsel.</small></label>
<label><input type="radio" name="sa_thema" value="aus"{"" if thema else " checked"}>
<div class="ef-schlicht"></div><div class="ef-namen"><span>&nbsp;</span></div>
<b>Schlicht</b><small>Überall das helle Glas-Design – ruhig und einheitlich.</small></label>
</div>
{_aktionen()}</section>''',
        # 3 Glas & Bewegung
        f'''<section class="ef-schritt"><span class="ef-augen">Schritt 2 von 3</span>
<h2>Hell oder dunkel?</h2>
<p class="lead">Erscheinungsbild, Glas, Bewegung und Dichte – so, wie es dir angenehm ist.</p>
<div class="ef-glas"><div>Glasfläche</div></div>
<div class="ef-block">
{_zeile("Erscheinungsbild", "Hell, dunkel oder passend zum Gerät.", _seg("sa_hell", [("hell", "Hell"), ("dunkel", "Dunkel"), ("auto", "Auto")], w("sa_hell")))}
{_zeile("Transparenz", "0 = deckend weiß, 100 = sehr durchsichtig.",
        f'<div class="ef-regler"><input type="range" name="sa_glas" min="0" max="100" step="5" value="{t}" aria-label="Transparenz"><output id="ef-glas-wert">{t}</output></div>')}
{_zeile("Bewegung", "Federnde Animationen und Übergänge.", _seg("sa_bewegung", [("normal", "Normal"), ("ruhig", "Ruhig")], w("sa_bewegung")))}
{_zeile("Dichte", "Kompakt zeigt mehr Zeilen auf einmal.", _seg("sa_dichte", [("normal", "Normal"), ("kompakt", "Kompakt")], w("sa_dichte")))}
{start}</div>
{_aktionen()}</section>''',
        # 4 Benachrichtigungen
        f'''<section class="ef-schritt"><span class="ef-augen">Schritt 3 von 3</span>
<h2>Was soll dir der Bot schreiben?</h2>
<p class="lead">Direktnachrichten auf Discord bei wichtigen Ereignissen. Mitteilungen der RP-Leitung kommen immer.</p>
<div class="ef-dm">{dm}</div>
{_aktionen(weiter="Fertig")}</section>''',
        # 5 Fertig
        f'''<section class="ef-schritt"><div class="ef-haken"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>
<h2>Alles bereit</h2><p class="lead">So ist dein Schatzamt eingestellt:</p>
<div class="ef-block"><ul class="ef-zusammen"><li>Deine Auswahl</li></ul></div>
<p class="ef-hinweis">Ändern kannst du alles jederzeit unter Weiteres → <i>Mein Profil</i> → Darstellung.</p>
<div class="ef-aktionen"><button class="btn zweit zurueck" type="button" data-geh="-1">Zurück</button><button class="btn" type="submit">Loslegen</button></div></section>''',
    ]
    fort = "".join("<i></i>" for _ in range(len(schritte) - 1))
    logo = f'{amt.BASIS}logo/{geld.STELLE[0]}-kopf.png'
    import dunkel
    return (CSS + dunkel.vorschau_html("sa_hell") + f'''<div class="ef-voll" role="dialog" aria-modal="true" aria-label="Einführung"><form class="ef" id="ef" method="post" action="{PFAD}">{amt.csrf_feld(request)}
<input type="hidden" name="weiter" value="{esc(weiter)}">
<div class="ef-kopf"><img src="{logo}" alt="Kaiserliches Schatz- und Währungsamt"><div class="ef-fort" aria-hidden="true">{fort}</div>
<button class="ef-spaeter" type="submit" name="spaeter" value="1" formnovalidate>Später</button></div>
<div class="ef-mitte"><div class="ef-buehne">{"".join(schritte)}</div></div></form></div>''' + JS)


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
        for s, erlaubt in (("sa_thema", ("an", "aus")), ("sa_bewegung", ("normal", "ruhig")), ("sa_dichte", ("normal", "kompakt")), ("sa_start", ("zuletzt", "staat", "privat")), ("sa_hell", ("hell", "dunkel", "auto"))):
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
