"""Liquid-Glass-Gestaltung der RP-Ansicht (/schatzamt/rp/ und alles, was im RP-Modus angezeigt wird).

Angelehnt an iOS „Liquid Glass“: schwebende, durchscheinende Ebenen für Seitenleiste, Kopf, Tableiste und Sheets (Blur + Sättigung, heller Lichtrand,
weicher Schatten), große Radien, Kapsel-Knöpfe, ein Segment-Umschalter mit gleitender Glaspille und weiche Federbewegungen. Die Farben bleiben die des
Portals (--ink, --akzent, --rot …); nur Flächen, Ränder, Schatten und Formen ändern sich. Inhaltskarten bekommen keinen Blur (Leistung), nur Glanz.

Eingebunden von schatzamt.ant, wenn die Seite im RP-Modus erscheint. Alle Regeln mit `html:root` vorn, damit sie die Grundregeln (auch html.min) schlagen.
SCHNELL ZURÜCK: GLAS = False + systemctl restart imperium-dienst.
"""
GLAS = True

CSS = """<style id="rp-glas">
html:root{--glas:rgba(255,255,255,.62);--glas-dicht:rgba(255,255,255,.8);--glas-rand:rgba(255,255,255,.75);--glas-linie:rgba(22,23,26,.07);
 --glas-schatten:0 10px 34px rgba(16,24,40,.08),0 1px 2px rgba(16,24,40,.05);--glas-licht:inset 0 1px 0 rgba(255,255,255,.9),inset 0 -1px 0 rgba(255,255,255,.25);
 --glas-blur:saturate(180%) blur(22px);--feder:cubic-bezier(.2,.9,.25,1.12);--weich:cubic-bezier(.2,.8,.2,1)}
html:root body{background:#f4f5f7;background-image:radial-gradient(1100px 620px at 12% -8%,rgba(31,78,140,.07),transparent 60%),
 radial-gradient(900px 560px at 100% 0%,rgba(22,23,26,.05),transparent 55%),radial-gradient(800px 600px at 50% 110%,rgba(31,78,140,.05),transparent 60%);background-attachment:fixed}

/* ---- Glas-Ebenen: Seitenleiste (Desktop schwebend), Kopf, Tableiste ---- */
@media (min-width:801px){
 html:root .seite{position:sticky;top:12px;height:calc(100vh - 24px);margin:12px 0 12px 12px;border-radius:24px;border:1px solid var(--glas-rand);
  background:var(--glas);-webkit-backdrop-filter:var(--glas-blur);backdrop-filter:var(--glas-blur);box-shadow:var(--glas-schatten),var(--glas-licht)}
 html:root .kopf{margin:12px 12px 0 16px;border-radius:22px;border:1px solid var(--glas-rand);top:12px;min-height:60px;padding:10px 14px 10px 20px;
  background:rgba(255,255,255,.55);-webkit-backdrop-filter:var(--glas-blur);backdrop-filter:var(--glas-blur);box-shadow:var(--glas-schatten),var(--glas-licht)}
}
html:root .seite a.ein{border-radius:12px;transition:background .2s var(--weich),transform .2s var(--weich)}
html:root .seite a.ein:hover{background:rgba(255,255,255,.6)}
html:root .seite a.ein.aktiv{background:rgba(255,255,255,.92);box-shadow:0 2px 10px rgba(16,24,40,.08),inset 0 1px 0 #fff;color:var(--ink)}
html:root .seite a.ein:active{transform:scale(.98)}
html:root .seite .fuss{border-top-color:var(--glas-linie)}
html:root .kopf input[type=search]{background:rgba(255,255,255,.55);border-color:var(--glas-rand);box-shadow:inset 0 1px 2px rgba(16,24,40,.06)}
html:root .kopf input[type=search]:focus{background:rgba(255,255,255,.92)}
html:root .knopf-rund{transition:background .2s,transform .2s var(--feder)}
html:root .knopf-rund:hover{background:rgba(255,255,255,.7)}
html:root .knopf-rund:active{transform:scale(.92)}

@media (max-width:800px){
 html:root .kopf{background:rgba(255,255,255,.58);-webkit-backdrop-filter:var(--glas-blur);backdrop-filter:var(--glas-blur);border-bottom:1px solid var(--glas-linie)}
 html:root body{padding-bottom:calc(var(--tab) + 24px + env(safe-area-inset-bottom))}
 html:root .tableiste{left:12px;right:12px;bottom:calc(10px + env(safe-area-inset-bottom));height:var(--tab);padding:0 6px;border-radius:30px;
  border:1px solid var(--glas-rand);background:rgba(255,255,255,.6);-webkit-backdrop-filter:var(--glas-blur);backdrop-filter:var(--glas-blur);
  box-shadow:0 12px 36px rgba(16,24,40,.16),var(--glas-licht)}
 html:root .tableiste a,html:root .tableiste button{border-radius:24px;margin:6px 0;transition:background .2s var(--weich)}
 html:root .tableiste .aktiv{color:var(--ink);background:rgba(255,255,255,.85);box-shadow:0 2px 8px rgba(16,24,40,.08),inset 0 1px 0 #fff}
 html:root .seite{background:rgba(255,255,255,.78);-webkit-backdrop-filter:var(--glas-blur);backdrop-filter:var(--glas-blur);border-radius:28px 28px 0 0;
  box-shadow:0 -12px 40px rgba(16,24,40,.18),var(--glas-licht)}
 html:root .blatt-kopf{background:transparent}
 html:root .schleier{background:rgba(15,17,21,.22);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px)}
}

/* ---- Segment-Umschalter Staatl./Privat/RP: Glasspur mit gleitender Pille ---- */
html:root .sa-modus{position:relative;border:1px solid var(--glas-rand);background:rgba(22,23,26,.06);box-shadow:inset 0 1px 2px rgba(16,24,40,.08);padding:3px;isolation:isolate}
html:root .sa-modus a{position:relative;z-index:1;transition:color .25s var(--weich)}
html:root .sa-modus a:hover{background:transparent}
html:root .sa-modus a.aktiv,html:root .sa-modus a.aktiv:hover{background:transparent;color:var(--ink)}
html:root .sa-modus .pille{position:absolute;z-index:0;top:3px;bottom:3px;border-radius:999px;background:#fff;box-shadow:0 2px 8px rgba(16,24,40,.14),inset 0 1px 0 #fff;
 transition:left .38s var(--feder),width .38s var(--feder)}
html:root .sa-modus a.rp{opacity:.6}
html:root .sa-modus a.rp.aktiv{opacity:1}

/* ---- OOC-Pille im Kopf statt Banner ---- */
html:root .rp-ooc{flex:none;display:inline-flex;align-items:center;gap:6px;margin-right:8px;padding:5px 11px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.12em;
 color:var(--ink);background:rgba(255,255,255,.7);border:1px dashed rgba(22,23,26,.35);cursor:help}
html:root .rp-ooc::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--warn)}

/* ---- Inhalt: Karten mit Glanz, Kapsel-Knöpfe ---- */
html:root main{max-width:1180px}
html:root .kennzahlen div,html:root .rp-staat,html:root .rp-kachel,html:root .rp-massnahme,html:root .rp-chip,html:root .rp-leiste a.aktiv,html:root .ts-tabs .ts-tabteil>.ts-karte,
html:root details.sa-auf,html:root .rs-block,html:root .rt-karten a{background:var(--glas-dicht);border:1px solid var(--glas-rand);box-shadow:var(--glas-schatten),var(--glas-licht)}
html:root .kennzahlen div{border-radius:20px}
html:root .rp-staat,html:root .rp-kachel,html:root .rp-massnahme{border-radius:20px}
html:root .rp-kzl>div:has(a):hover,html:root .rp-staat:hover,html:root .rp-kachel:hover,html:root .rp-chip:hover{border-color:var(--glas-rand);background:#fff;box-shadow:0 14px 40px rgba(16,24,40,.12),var(--glas-licht);transform:translateY(-1px)}
html:root .kennzahlen div,html:root .rp-staat,html:root .rp-kachel,html:root .rp-chip{transition:transform .25s var(--feder),box-shadow .25s var(--weich),background .2s}
html:root .rp-staat:active,html:root .rp-kachel:active,html:root .rp-chip:active,html:root .btn:active{transform:scale(.97)}
html:root .rp-staat.warn{border-color:rgba(155,28,28,.35);box-shadow:inset 3px 0 0 var(--rot),var(--glas-schatten)}
html:root .rp-marken i{background:rgba(22,23,26,.06)}
html:root .rp-marken i.rot{background:rgba(155,28,28,.1)}
html:root .rp-leiste a{border-radius:16px}
html:root .rp-leiste a:hover{background:rgba(255,255,255,.6)}
html:root .btn,html:root button.btn{border-radius:999px;padding:9px 18px;transition:transform .2s var(--feder),box-shadow .2s,background .2s,filter .2s;
 box-shadow:0 4px 14px rgba(16,24,40,.16),inset 0 1px 0 rgba(255,255,255,.18)}
html:root .btn.zweit{background:rgba(255,255,255,.75);border-color:var(--glas-rand);box-shadow:var(--glas-schatten),var(--glas-licht);color:var(--ink)}
html:root .btn.zweit:hover{background:#fff}
html:root .btn.gefahr{background:rgba(255,255,255,.75);color:var(--rot)}
html:root input[type=text],html:root input[type=search],html:root input[type=number],html:root select,html:root textarea{border-radius:12px;background:rgba(255,255,255,.8);
 border-color:rgba(22,23,26,.1);transition:border-color .2s,box-shadow .2s,background .2s}
html:root main input:focus,html:root main select:focus,html:root main textarea:focus,html:root dialog input:focus,html:root dialog textarea:focus,html:root dialog select:focus{background:#fff}
html:root .hinweis{border-radius:16px;background:rgba(255,255,255,.7);border:1px solid var(--glas-rand)}
html:root .status{backdrop-filter:none}
html:root .ts-nav a,html:root .reiter a{transition:background .2s,color .2s}
html:root .ts-nav{border-bottom:0;gap:6px;padding:4px;background:rgba(22,23,26,.05);border-radius:999px;display:inline-flex;max-width:100%;margin:14px 0 18px}
html:root .ts-nav a{border:0;border-radius:999px;margin:0;padding:7px 15px;background:transparent}
html:root .ts-nav a.aktiv{background:#fff;color:var(--ink);box-shadow:0 2px 8px rgba(16,24,40,.12),inset 0 1px 0 #fff}
html:root .ts-nav a:hover{background:rgba(255,255,255,.6)}
html:root table:not(.daten){background:transparent}
html:root .rp-ac{border-radius:16px;background:rgba(255,255,255,.86);-webkit-backdrop-filter:var(--glas-blur);backdrop-filter:var(--glas-blur);border-color:var(--glas-rand)}

/* ---- Sheets ---- */
html:root dialog.rp-sheet{background:rgba(255,255,255,.9);-webkit-backdrop-filter:var(--glas-blur);backdrop-filter:var(--glas-blur);border:1px solid var(--glas-rand);
 border-radius:28px;box-shadow:0 30px 80px rgba(16,24,40,.28),var(--glas-licht)}
html:root dialog.rp-sheet::backdrop{background:rgba(15,17,21,.22);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}
html:root dialog.rp-sheet[open]{animation:rp-auf .42s var(--feder) both}
@keyframes rp-auf{from{opacity:0;transform:translateY(18px) scale(.97)}to{opacity:1;transform:none}}
html:root .rp-sheet-kopf{border-bottom-color:var(--glas-linie)}
@media (max-width:800px){
 html:root dialog.rp-sheet{border-radius:28px 28px 0 0;border-bottom:0}
 html:root dialog.rp-sheet[open]{animation:rp-hoch .42s var(--feder) both}
 html:root .rp-sheet-kopf{position:relative;padding-top:20px}
 html:root .rp-sheet-kopf::before{content:"";position:absolute;top:7px;left:50%;width:38px;height:5px;margin-left:-19px;border-radius:3px;background:rgba(22,23,26,.18)}
}
@keyframes rp-hoch{from{transform:translateY(100%)}to{transform:none}}

@media (prefers-reduced-motion:reduce){html:root dialog.rp-sheet[open]{animation:none}html:root .sa-modus .pille{transition:none}}
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){
 html:root .seite,html:root .kopf,html:root .tableiste,html:root dialog.rp-sheet{background:rgba(255,255,255,.96)}}
</style>"""

# Gleitende Pille im Segment-Umschalter (je Umschalter; folgt dem aktiven Eintrag, auch beim Antippen vor dem Seitenwechsel)
JS = """<script>(function(){document.querySelectorAll(".sa-modus").forEach(function(n){if(n.querySelector(".pille"))return;var p=document.createElement("span");p.className="pille";n.insertBefore(p,n.firstChild);
function setze(a,ohne){if(!a){p.style.width="0";return}if(ohne)p.style.transition="none";p.style.left=a.offsetLeft+"px";p.style.width=a.offsetWidth+"px";if(ohne){p.offsetWidth;p.style.transition=""}}
setze(n.querySelector("a.aktiv"),true);n.querySelectorAll("a").forEach(function(a){a.addEventListener("click",function(){n.querySelectorAll("a").forEach(function(x){x.classList.remove("aktiv")});a.classList.add("aktiv");setze(a)})});
addEventListener("resize",function(){setze(n.querySelector("a.aktiv"),true)})})})();</script>"""


def ooc_pille():
    import amt
    return f'<span class="rp-ooc" title="{amt.esc("Du siehst diese Seite als Serveradministrator mit vollem Zugriff. Dieser Zugriff ist rein OOC und verleiht kein Amt im Spiel.")}">OOC</span>'
