"""Digitaler Pass: der ausgestellte Pass als Ansicht zum Umblättern (Passheft) bzw. Umdrehen (Personalausweis).

- …/intern/mein-pass/            leitet auf /profil/dokumente/ (Profilbereich der Website, webseite.py)
- …/intern/pass/<id>/            Ansicht eines Passes: Inhaber selbst, außerdem Beamte mit Aktenzugriff (Verschluss beachtet)
- …/intern/pass-bild/<datei>     Wappenbilder aus pass_bilder/ (öffentlich, zwischengespeichert)
Seiten kommen aus passdruck.heft_seiten / karte_seiten (gleiches Aussehen wie die Druckvorlage). Blättern: Klick/Tippen auf die
rechte bzw. linke Hälfte, Wischen, Pfeiltasten, Knöpfe; unter 760 px Breite Einzelseitenmodus. Ungültige/abgelaufene Pässe tragen
einen Stempel. Menüpunkt „Mein Pass“ (Gruppe „Persönlich“) für jedes Konto mit Pass.
"""
import json
import os

from aiohttp import web

import amt
import anmeldung
import config
import meldewesen
import passdruck

esc = amt.esc
BASIS = amt.BASIS
BILDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pass_bilder")
_CON = None

STEMPEL = {"abgelaufen": "Abgelaufen", "ungueltig": "Ungültig", "fahndung": "Fahndung"}

# Rahmen im Design der Website (webseite.py): Seitenkopf mit Brotkrumen, schlichte Steuerung. Das Heft selbst liegt in einem
# Shadow-DOM (eigene Stile der Passseiten, damit sie die Website nicht beeinflussen und umgekehrt).
SEITE_CSS = """<style>
@font-face{font-family:SS3;src:url(/assets/fonts/source-sans-3.woff2) format("woff2");font-weight:400 700}
.page-head.kompakt{padding:clamp(18px,3vw,30px) 0 clamp(20px,3vw,30px)}
.page-head.kompakt .breadcrumb{margin-bottom:clamp(12px,2vw,20px)}
.page-head.kompakt h1{font-size:clamp(2rem,3.6vw,2.9rem);margin-bottom:8px}
.pd-meta{margin:0;color:var(--muted);font-size:.9375rem;display:flex;flex-wrap:wrap;gap:4px 18px}
.pd-meta b{font-weight:600}
.pd-meta .gueltig{color:var(--success)}.pd-meta .abgelaufen{color:var(--gold-600)}.pd-meta .ungueltig,.pd-meta .fahndung{color:var(--danger)}
.pd-flaeche{padding:clamp(20px,3.5vw,40px) 0 clamp(40px,6vw,72px)}
.pd-wahl{margin:0 0 clamp(20px,3vw,32px)}
.pd-host{display:block;width:100%}
.pd-steuer{display:flex;align-items:center;justify-content:center;gap:16px;margin-top:clamp(18px,3vw,28px);flex-wrap:wrap}
.pd-k{font:500 .875rem/1 var(--sans);letter-spacing:.02em;color:var(--ink);background:transparent;border:1px solid var(--rule-strong);
 border-radius:var(--radius);padding:10px 16px;cursor:pointer;transition:border-color .2s,background-color .2s}
.pd-k:hover:not(:disabled){border-color:var(--ink)}
.pd-k:disabled{opacity:.35;cursor:default}
.pd-stelle{min-width:16ch;text-align:center;font-size:.875rem;color:var(--muted);font-variant-numeric:tabular-nums}
.pd-stelle b{color:var(--ink);font-weight:600}
.pd-zusatz{text-align:center;margin:14px 0 0;font-size:.8125rem;color:var(--muted)}
.pd-zusatz button{background:none;border:0;padding:0;font:inherit;color:var(--ink);text-decoration:underline;text-underline-offset:3px;cursor:pointer}
</style>"""

BUCH_CSS = """
:host{display:block}
.buehne{position:relative;margin:0 auto;touch-action:pan-y;user-select:none;-webkit-user-select:none}
.skal{position:absolute;left:50%;top:0;perspective:2600px}
.buch{position:relative;width:250mm;height:88mm;transform-style:preserve-3d;transition:transform .9s cubic-bezier(.65,.05,.36,1)}
.schatten{position:absolute;left:125mm;top:3mm;width:125mm;height:85mm;border-radius:3mm;box-shadow:0 14px 34px rgba(10,15,39,.22);
 transition:left .9s cubic-bezier(.65,.05,.36,1),width .9s cubic-bezier(.65,.05,.36,1);transform:translateZ(-2px)}
.buch.offen .schatten{left:0;width:250mm}
.buch.hinten-zu .schatten{left:0;width:125mm}
.blatt{position:absolute;left:125mm;top:0;width:125mm;height:88mm;transform-origin:left center;transform-style:preserve-3d;
 transition:transform 1.05s cubic-bezier(.645,.045,.355,1);cursor:pointer}
.gesicht{position:absolute;inset:0;backface-visibility:hidden;-webkit-backface-visibility:hidden;overflow:hidden;border-radius:0 2.6mm 2.6mm 0}
.gesicht.rueck{transform:rotateY(180deg);border-radius:2.6mm 0 0 2.6mm}
.gesicht .seite{left:0!important;top:0}
.gesicht .seite:not(.umschlag),.karte-seite .karte{color:#1a1a1a}
.gesicht::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:0;transition:opacity .5s;
 background:linear-gradient(90deg,rgba(0,0,0,.28),rgba(0,0,0,0) 18%,rgba(0,0,0,0) 80%,rgba(255,255,255,.08))}
.gesicht.rueck::after{background:linear-gradient(270deg,rgba(0,0,0,.28),rgba(0,0,0,0) 18%)}
.blatt.dreht .gesicht::after{opacity:1}
.falz-schatten{position:absolute;inset:0;pointer-events:none;background:linear-gradient(90deg,rgba(0,0,0,.22),rgba(0,0,0,0) 7%)}
.gesicht.rueck .falz-schatten{background:linear-gradient(270deg,rgba(0,0,0,.22),rgba(0,0,0,0) 7%)}
.umschlag-glanz{position:absolute;top:19mm;left:50%;width:58mm;aspect-ratio:735/621;transform:translateX(-50%);pointer-events:none;
 -webkit-mask:var(--maske) center/contain no-repeat;mask:var(--maske) center/contain no-repeat;
 background:linear-gradient(105deg,transparent 35%,rgba(255,250,225,.85) 48%,transparent 60%) 0 0/300% 100%;mix-blend-mode:screen;
 animation:glanz 5.5s ease-in-out infinite}
@keyframes glanz{0%,30%{background-position:120% 0}70%,100%{background-position:-20% 0}}
.holo{position:absolute;inset:0;pointer-events:none;mix-blend-mode:soft-light;opacity:.9;
 background:linear-gradient(115deg,transparent 25%,rgba(255,80,200,.35) 38%,rgba(80,230,255,.35) 50%,rgba(255,240,90,.35) 62%,transparent 75%);
 background-size:320% 320%;background-position:var(--hx,50%) var(--hy,50%);transition:background-position .25s}
.stempel{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) rotate(-14deg);border:1.2mm solid #b3121f;color:#b3121f;
 font:700 9mm/1 "Liberation Sans",Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;padding:2mm 5mm;border-radius:2mm;
 background:rgba(255,255,255,.35);white-space:nowrap;opacity:.9;mix-blend-mode:multiply}
.karte3d{position:absolute;left:50%;top:0;width:85.6mm;height:54mm;perspective:1600px}
.karte-dreh{position:relative;width:100%;height:100%;transform-style:preserve-3d;transition:transform 1s cubic-bezier(.645,.045,.355,1);cursor:pointer}
.karte-neig{position:relative;width:100%;height:100%;transform-style:preserve-3d;transition:transform .2s ease-out}
.karte-dreh.um{transform:rotateY(180deg)}
.karte-seite{position:absolute;inset:0;backface-visibility:hidden;-webkit-backface-visibility:hidden;border-radius:3.2mm;overflow:hidden;
 box-shadow:0 12px 30px rgba(10,15,39,.22)}
.karte-seite.rueck{transform:rotateY(180deg)}
.karte-seite .karte{left:0!important;border-radius:3.2mm}
.mrz{font-family:"Liberation Mono","Courier New",Courier,monospace!important}
@media (prefers-reduced-motion:reduce){.buch,.blatt,.karte-dreh,.schatten{transition-duration:.01ms!important}.umschlag-glanz{animation:none}}
"""

JS = r"""
(function(){
const D = %s;
const host = document.querySelector(".pd-host"), R = host.shadowRoot;
if (!R) return;
const buehne = R.querySelector(".buehne"), skal = R.querySelector(".skal");
const PX = 96 / 25.4;
const zur = document.getElementById("zurueck"), vor = document.getElementById("weiter"), stelle = document.getElementById("pd-stelle");
let schritt = 0;
function anzeigen(liste) { stelle.innerHTML = "<b>" + (schritt + 1) + "</b> / " + liste.length + " · " + liste[schritt]; }
function holo(e) {
  const r = buehne.getBoundingClientRect();
  host.style.setProperty("--hx", (((e.clientX - r.left) / r.width) * 100) + "%%");
  host.style.setProperty("--hy", (((e.clientY - r.top) / r.height) * 100) + "%%");
}

if (D.art === "karte") {
  const dreh = R.querySelector(".karte-dreh"), neig = R.querySelector(".karte-neig");
  const W = 85.6 * PX, H = 54 * PX;
  function groesse() {
    const s = Math.max(.6, Math.min(1.9, (host.clientWidth - 8) / W, (innerHeight - 260) / H));
    skal.style.zoom = s; skal.style.transform = "translateX(-50%%)";
    buehne.style.height = (H * s + 8) + "px";
  }
  function zeigen() {
    dreh.classList.toggle("um", schritt === 1);
    zur.disabled = schritt === 0; vor.disabled = schritt === 1;
    anzeigen(["Vorderseite", "Rückseite"]);
  }
  dreh.addEventListener("click", () => { schritt = 1 - schritt; zeigen(); });
  zur.onclick = () => { schritt = 0; zeigen(); };
  vor.onclick = () => { schritt = 1; zeigen(); };
  addEventListener("keydown", e => { if (e.key === "ArrowRight") { schritt = 1; zeigen(); } if (e.key === "ArrowLeft") { schritt = 0; zeigen(); } });
  buehne.addEventListener("pointermove", e => {
    const r = buehne.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
    neig.style.transform = "rotateX(" + (-y * 8) + "deg) rotateY(" + (x * 10) + "deg)";
    holo(e);
  });
  buehne.addEventListener("pointerleave", () => { neig.style.transform = ""; });
  addEventListener("resize", groesse); groesse(); zeigen();
  return;
}

const buch = R.querySelector(".buch"), blaetter = [...R.querySelectorAll(".blatt")], N = blaetter.length;
const P = 125 * PX, H = 88 * PX;
const schmal = () => host.clientWidth < 700;
let einzel = schmal();
function maxSchritt() { return einzel ? 2 * N - 1 : N; }
function gedreht() { return einzel ? Math.floor((schritt + 1) / 2) : schritt; }
function groesse() {
  const neu = schmal();
  if (neu !== einzel) { schritt = neu ? Math.min(2 * schritt, 2 * N - 1) : Math.floor((schritt + 1) / 2); einzel = neu; }
  const breite = einzel ? P : 2 * P;
  const s = Math.max(.3, Math.min(1.15, (host.clientWidth - 8) / breite, (innerHeight - 240) / H));
  skal.style.zoom = s; skal.style.transform = "translateX(-125mm)";
  buehne.style.height = (H * s + 8) + "px";
  zeigen(false);
}
function zeigen(anim) {
  const g = gedreht();
  blaetter.forEach((b, k) => {
    const um = k < g, war = b.classList.contains("um");
    b.classList.toggle("um", um);
    const z = um ? (k + 1) * .7 : (N - k) * .7;
    b.style.transform = "translateZ(" + z + "px) rotateY(" + (um ? -180 : 0) + "deg)";
    if (anim !== false && war !== um) {
      b.classList.add("dreht"); b.style.zIndex = 50;
      clearTimeout(b._t); b._t = setTimeout(() => { b.classList.remove("dreht"); b.style.zIndex = um ? k + 1 : 2 * N - k; }, 1050);
    } else if (!b.classList.contains("dreht")) b.style.zIndex = um ? k + 1 : 2 * N - k;
  });
  let x;
  if (einzel) x = (schritt %% 2) ? P / 2 : -P / 2;
  else x = g === 0 ? -P / 2 : (g === N ? P / 2 : 0);
  buch.style.transform = "translateX(" + x + "px)";
  buch.classList.toggle("offen", g > 0 && g < N);
  buch.classList.toggle("hinten-zu", g === N);
  zur.disabled = schritt === 0; vor.disabled = schritt === maxSchritt();
  anzeigen(einzel ? D.einzel : D.doppel);
}
function geh(d) { const n = Math.max(0, Math.min(maxSchritt(), schritt + d)); if (n !== schritt) { schritt = n; zeigen(); } }
zur.onclick = () => geh(-1); vor.onclick = () => geh(1);
document.getElementById("zu-daten").onclick = () => { schritt = einzel ? 2 * N - 2 : N - 1; zeigen(); };
addEventListener("keydown", e => { if (e.key === "ArrowRight") geh(1); if (e.key === "ArrowLeft") geh(-1); });
let x0 = null, y0 = null;
buehne.addEventListener("pointerdown", e => { x0 = e.clientX; y0 = e.clientY; });
buehne.addEventListener("pointerup", e => {
  if (x0 === null) return;
  const dx = e.clientX - x0, dy = e.clientY - y0; x0 = null;
  if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) { geh(dx < 0 ? 1 : -1); return; }
  if (Math.abs(dx) < 8 && Math.abs(dy) < 8) {
    const r = buehne.getBoundingClientRect();
    geh(e.clientX > r.left + r.width / 2 ? 1 : -1);
  }
});
buehne.addEventListener("pointermove", holo);
addEventListener("resize", groesse);
groesse();
if (D.daten) { schritt = einzel ? 2 * N - 2 : N - 1; zeigen(false); }
})();
"""

def _bilder_url(text):
    """Für die Web-Ansicht: Wappen als URL statt data-URI, Lichtbild-Platzhalter ohne Druckhinweis."""
    for name in ("wappen_gold.png", "wappen.png"):
        text = text.replace(passdruck.bild(name), f"{BASIS}pass-bild/{name}")
    for alt in ("Lichtbild<br>hier einkleben<br>(30 × 38,5 mm)", "Lichtbild<br>einkleben<br>(22 × 28,5 mm)"):
        text = text.replace(alt, "Kein Lichtbild<br>hinterlegt")
    return text


def _darf(con, k, p):
    if not k:
        return False
    if p["konto_id"] == k["id"]:
        return True
    if amt.ist_beamter(k):
        a = con.execute("SELECT verschluss FROM amt_akten WHERE id=?", (p["akte_id"],)).fetchone()
        return not (a and a["verschluss"] and not amt.darf_verschluss(k))
    return False


def _gesicht(seite, rueck=False, extra=""):
    return f'<div class="gesicht{" rueck" if rueck else ""}">{seite}{extra}<div class="falz-schatten"></div></div>'


def ansicht_html(con, p, pfad, wahl, daten_zuerst=False):
    """(Titel, Inhalt, zusätzlicher head) der Dokumentansicht im Website-Rahmen.
    pfad = Brotkrumen [(Text, URL|None)], wahl = [(Pass-Zeile, URL)] weiterer Dokumente desselben Inhabers."""
    import webseite
    s_key, s_text = meldewesen.pass_status(p)
    d = passdruck.daten(con, p, True)
    if d["foto"]:   # über den Dienst ausliefern: die CSP der Website erlaubt keine Bilder von cdn.discordapp.com
        d["foto"] = f'{BASIS}pass-foto/{p["konto_id"]}'
    stempel = f'<div class="stempel">{esc(STEMPEL[s_key])}</div>' if s_key in STEMPEL else ""
    holo = '<div class="holo"></div>'
    stil = passdruck._css().split("}", 1)[1]   # Passseiten-Stile ohne @font-face (steht im Dokument)
    art_name = meldewesen.PASSARTEN[p["art"]][0]

    if p["art"] == "personalausweis":
        vorne, hinten = passdruck.karte_seiten(d)
        buehne = (f'<div class="buehne"><div class="skal karte3d"><div class="karte-neig"><div class="karte-dreh">'
                  f'<div class="karte-seite">{vorne}{holo}{stempel}</div><div class="karte-seite rueck">{hinten}</div></div></div></div></div>')
        knoepfe = ('<button class="pd-k" id="zurueck" type="button">← Vorderseite</button><span class="pd-stelle" id="pd-stelle"></span>'
                   '<button class="pd-k" id="weiter" type="button">Rückseite →</button>')
        zusatz = '<p class="pd-zusatz">Zum Umdrehen auf die Karte tippen.</p>'
        daten_js = {"art": "karte"}
    else:
        sei = passdruck.heft_seiten(d)
        glanz = f'<div class="umschlag-glanz" style="--maske:url({BASIS}pass-bild/wappen_gold.png)"></div>'
        blaetter = [(_gesicht(sei["vorne"], extra=glanz), _gesicht(sei["ersuchen"], True)),
                    (_gesicht(sei["visa_seite"]("r", 1)), _gesicht(sei["visa_seite"]("l", 2), True)),
                    (_gesicht(sei["visa_seite"]("r", 3)), _gesicht(sei["visa_seite"]("l", 4), True)),
                    (_gesicht(sei["daten"], extra=holo + stempel), _gesicht(sei["hinten"], True))]
        buehne = ('<div class="buehne"><div class="skal"><div class="buch"><div class="schatten"></div>'
                  + "".join(f'<div class="blatt">{a}{b}</div>' for a, b in blaetter) + '</div></div></div>')
        knoepfe = ('<button class="pd-k" id="zurueck" type="button">← Zurück</button><span class="pd-stelle" id="pd-stelle"></span>'
                   '<button class="pd-k" id="weiter" type="button">Weiter →</button>')
        zusatz = '<p class="pd-zusatz"><button id="zu-daten" type="button">Zur Personaldatenseite</button></p>'
        daten_js = {"art": "heft", "daten": daten_zuerst,
                    "doppel": ["Umschlag", "Ersuchen · Seite 1", "Seite 2 · Seite 3", "Seite 4 · Personaldaten", "Rückseite"],
                    "einzel": ["Umschlag", "Ersuchen", "Seite 1", "Seite 2", "Seite 3", "Seite 4", "Personaldaten", "Rückseite"]}

    wahl_html = ""
    if len(wahl) > 1:
        wahl_html = '<nav class="tabs pd-wahl" aria-label="Dokumente">' + "".join(
            f'<a href="{esc(u)}"{" aria-current=page" if a["id"] == p["id"] else ""}>{esc(meldewesen.PASSARTEN[a["art"]][0])}</a>'
            for a, u in wahl) + "</nav>"
    meta = (f'<p class="pd-meta"><span>Nr. <b>{esc(p["nummer"])}</b></span><span>{esc(p["inhaber"])}</span>'
            f'<span>gültig bis {meldewesen._datum(p["gueltig_bis"])}</span><span class="{s_key}">{esc(s_text)}</span></p>')
    host = (f'<div class="pd-host"><template shadowrootmode="open"><style>{stil}{BUCH_CSS}</style>{buehne}</template></div>')
    inhalt = (webseite.kopf(art_name, pfad).replace("</h1>", "</h1>" + meta, 1).replace('class="page-head"', 'class="page-head kompakt"', 1)
              + f'<section class="pd-flaeche"><div class="wrap">{wahl_html}{host}<div class="pd-steuer">{knoepfe}</div>{zusatz}</div></section>'
              + f"<script>{JS % json.dumps(daten_js)}</script>")
    return art_name, _bilder_url(inhalt), SEITE_CSS


async def ansicht(request):
    """Ansicht für Beamte (aus dem Passregister bzw. der Prüfseite); der Inhaber wird in sein Profil umgeleitet."""
    import webseite
    k = await anmeldung.konto(request)
    if not k:
        raise web.HTTPFound("/anmelden/?weiter=" + request.path_qs)
    con = request.app["db"]
    i = request.match_info["id"]
    p = con.execute("SELECT * FROM pw_paesse WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not p or not _darf(con, k, p):
        raise web.HTTPNotFound(text="Pass nicht gefunden.")
    if p["konto_id"] == k["id"]:
        raise web.HTTPFound(f'{webseite.PROFIL}dokumente/{p["id"]}/' + ("?seite=daten" if request.query.get("seite") == "daten" else ""))
    andere = con.execute("SELECT * FROM pw_paesse WHERE konto_id=? AND (status='gueltig' OR id=?) ORDER BY ausgestellt DESC",
                         (p["konto_id"], p["id"])).fetchall()
    pfad = [("Amtsseite", BASIS), ("Passregister", f"{meldewesen.PFAD}paesse/"), (p["nummer"], f'{meldewesen.PFAD}paesse/{p["id"]}/'),
            ("Digital", None)]
    titel, inhalt, head = ansicht_html(con, p, pfad, [(a, f'{BASIS}pass/{a["id"]}/') for a in andere], request.query.get("seite") == "daten")
    return webseite.antwort(titel, inhalt, head)


async def mein_pass(request):
    raise web.HTTPFound("/profil/dokumente/")


async def bild(request):
    name = request.match_info["name"]
    if name not in ("wappen.png", "wappen_gold.png"):
        raise web.HTTPNotFound()
    return web.FileResponse(os.path.join(BILDER, name), headers={"Cache-Control": "public, max-age=86400"})


def nav(k):
    if _CON is None or not k:
        return []
    hat = _CON.execute("SELECT 1 FROM pw_paesse WHERE konto_id=? LIMIT 1", (k["id"],)).fetchone()
    return [("mein-pass", "id-card", "Mein Pass", "mein-pass/")] if hat else []


def knopf(p):
    return f'<a class="btn zweit" href="{BASIS}pass/{p["id"]}/">{amt.ic("book-open")}Digital ansehen</a>'


def dm_zusatz(nr):
    return f"\nDein Pass digital zum Durchblättern: {config.SITE_URL}/profil/dokumente/"


def registrieren(app):
    global _CON
    _CON = app["db"]
    amt.ICONS.setdefault("book-open", '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>')
    amt.NAV_EXTRA.append(("Persönlich", nav))
    meldewesen.PASS_KNOEPFE.insert(0, knopf)
    meldewesen.DM_ZUSATZ.append(dm_zusatz)
    app.router.add_get(BASIS + "mein-pass/", mein_pass)
    app.router.add_get(BASIS + "pass/{id}/", ansicht)
    app.router.add_get(BASIS + "pass-bild/{name}", bild)
