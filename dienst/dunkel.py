"""Dunkelmodus des Schatzamt-Portals im Stil des iOS-Darkmode (seit 26.11.2026).

Einstellung: Mein Profil → Darstellung → „Erscheinungsbild“ (Schlüssel sa_hell: hell | dunkel | auto; Standard hell). „auto“ folgt dem Gerät
(prefers-color-scheme), dann steht alles in @media (prefers-color-scheme:dark).
Farben nach iOS: Hintergrund #000 (systemBackground), Flächen #1C1C1E / #2C2C2E / #3A3A3C (secondary/tertiary), Trennlinien rgba(84,84,88,.6),
Text #FFF / rgba(235,235,245,.6), Blau #0A84FF, Grün #30D158, Rot #FF453A, Orange #FF9F0A, Segmente rgba(118,118,128,.24) mit Pille #636366.
Glas (rp_glas-Variablen) wird zu dunklem Material.
Themen (themen.py): Marmor wird im Dunkeln schwarzer Marmor (statisch/marmor_dunkel.jpg, invertierte Textur); die übrigen Themen sind
„echte Materialien“ und bleiben, wie sie sind – auf deren Seiten gilt der Dunkelmodus nicht (schatzamt.ant).
Eingebunden in schatzamt.ant (nach rp_glas, themen und der persönlichen Darstellung). Rückfall: AKTIV = False + Neustart.
"""
AKTIV = True

GRUND, FLAECHE, FLAECHE2, FLAECHE3 = "#000", "#1c1c1e", "#2c2c2e", "#3a3a3c"
TEXT2 = "rgba(235,235,245,.6)"
TEXT3 = "rgba(235,235,245,.3)"
LINIE = "rgba(84,84,88,.6)"
BLAU, GRUEN, ROT, ORANGE = "#0a84ff", "#30d158", "#ff453a", "#ff9f0a"
SEGMENT, PILLE = "rgba(118,118,128,.24)", "#636366"

# Karten und Bausteine, die im hellen Design weiß sind
KARTEN = (".kennzahlen>div,.sa-karte,.pf-karte,.st-karte,.ts-karte,.rp-kachel,.rp-staat,.rp-massnahme,.pb-karte,details.sa-auf,.sa-erkl,.sa-schnell a,"
          ".sa-todo>div,.zf-kopf,.hinweis,.sa-pruef,.rs-block,.rt-karten a,.ts-tabs .ts-tabteil>.ts-karte,.sa-formular,.bk-daten,.ef-block,.ef-wahl label")


def _p(sel, bereich="html:root"):
    """Jeden Teil einer Selektorliste mit dem Bereich versehen."""
    return ",".join(f"{bereich} {s.strip()}" for s in sel.split(","))


CSS = f"""
html:root{{color-scheme:dark;--ink:#fff;--grau:{TEXT2};--linie:{LINIE};--hell:{FLAECHE2};--flaeche:{FLAECHE};--kopf:{FLAECHE};--akzent:{BLAU};--warn:{ORANGE};--ok:{GRUEN};--rot:{ROT};
 --glas:rgba(30,30,32,.72);--glas-kopf:rgba(30,30,32,.7);--glas-leiste:rgba(30,30,32,.78);--glas-blatt:rgba(28,28,30,.94);--glas-sheet:rgba(44,44,46,.97);--glas-dicht:{FLAECHE};
 --glas-rand:rgba(255,255,255,.07);--glas-linie:rgba(255,255,255,.08);--glas-schatten:0 10px 34px rgba(0,0,0,.55),0 1px 2px rgba(0,0,0,.4);--glas-licht:inset 0 1px 0 rgba(255,255,255,.06)}}
html:root body{{background:{GRUND};background-image:radial-gradient(1100px 620px at 12% -8%,rgba(10,132,255,.10),transparent 60%),radial-gradient(800px 600px at 50% 110%,rgba(10,132,255,.06),transparent 60%);color:#fff}}
/* Seitenleiste, Kopf, Tableiste */
html:root .gruppe-titel{{color:{TEXT2}}}
html:root .seite a.ein{{color:rgba(255,255,255,.88)}}
html:root .seite a.ein .icon{{color:{TEXT2}}}
html:root .seite a.ein:hover{{background:rgba(255,255,255,.07);color:#fff}}
html:root .seite a.ein.aktiv{{background:rgba(255,255,255,.13);color:#fff;box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}}
html:root .seite a.ein.aktiv .icon{{color:{BLAU}}}
html:root .seite .fuss{{border-top-color:rgba(255,255,255,.08)}}
html:root .tableiste a,html:root .tableiste button{{color:{TEXT2}}}
html:root .tableiste .aktiv{{color:#fff;background:rgba(255,255,255,.14);box-shadow:none}}
html:root .kopf input[type=search]{{background:rgba(118,118,128,.24);border-color:transparent;color:#fff}}
html:root .kopf input[type=search]:focus{{background:rgba(118,118,128,.32);border-color:{BLAU};box-shadow:0 0 0 3px rgba(10,132,255,.25)}}
html:root .knopf-rund{{color:#fff}}
html:root .knopf-rund:hover{{background:rgba(255,255,255,.1)}}
html:root .rp-ooc{{background:rgba(255,255,255,.1);color:#fff;border-color:rgba(255,255,255,.3)}}
html:root .schleier{{background:rgba(0,0,0,.5)}}
/* Segmente (Staatl./Privat, Reiter, Untertabs) wie iOS */
html:root .sa-modus,html:root .reiter,html:root .ts-nav,html:root .ef-seg{{background:{SEGMENT};border-color:transparent;box-shadow:none}}
html:root .sa-modus a,html:root .reiter a,html:root .ts-nav a{{color:{TEXT2}}}
html:root .sa-modus a.aktiv,html:root .sa-modus a.aktiv:hover,html:root .reiter a.aktiv,html:root .ts-nav a.aktiv{{color:#fff}}
html:root .reiter a.aktiv,html:root .ts-nav a.aktiv,html:root .sa-modus .pille,html:root .ef-seg input:checked+span{{background:{PILLE};color:#fff;box-shadow:0 3px 8px rgba(0,0,0,.35)}}
html:root .reiter a:hover,html:root .ts-nav a:hover{{background:rgba(255,255,255,.06);color:#fff}}
/* Karten */
{_p(KARTEN)}{{background:{FLAECHE};border-color:rgba(255,255,255,.06);box-shadow:0 1px 0 rgba(255,255,255,.04) inset,0 8px 24px rgba(0,0,0,.35);color:#fff}}
html:root .kz-links>div:has(a):hover,html:root .rp-kachel:hover,html:root .rp-staat:hover,html:root a.ts-karte:hover,html:root .sa-schnell a:hover{{background:{FLAECHE2};border-color:rgba(255,255,255,.08)}}
html:root .rp-chip,html:root .pb-chips a,html:root .hd-chips a{{background:{FLAECHE2};border-color:transparent;color:#fff}}
html:root .rp-chip.aktiv,html:root .pb-chips a.aktiv,html:root .hd-chips a.aktiv{{background:#fff;color:#000}}
/* Knöpfe: gefüllt weiß (wie die schwarzen Knöpfe im hellen Design), zweitrangig grau */
html:root .btn:not(.zweit):not(.gefahr),html:root button.btn:not(.zweit):not(.gefahr){{background:#fff;color:#000;border-color:transparent;box-shadow:0 4px 14px rgba(0,0,0,.4)}}
html:root .btn.zweit{{background:{FLAECHE2};color:#fff;border-color:transparent;box-shadow:none}}
html:root .btn.zweit:hover{{background:{FLAECHE3}}}
html:root .btn.gefahr{{background:{FLAECHE2};color:{ROT};border-color:transparent}}
/* Felder */
html:root input[type=text],html:root input[type=search],html:root input[type=number],html:root input[type=date],html:root input[type=password],html:root input[type=file],
html:root select,html:root textarea{{background:{FLAECHE2};border-color:rgba(255,255,255,.08);color:#fff}}
html:root main input:focus,html:root main select:focus,html:root main textarea:focus,html:root dialog input:focus,html:root dialog select:focus,html:root dialog textarea:focus{{
 background:{FLAECHE3};border-color:{BLAU};box-shadow:0 0 0 3px rgba(10,132,255,.25)}}
html:root input::placeholder,html:root textarea::placeholder{{color:{TEXT3}}}
html:root input[type=range],html:root input[type=checkbox],html:root input[type=radio]{{accent-color:{BLAU}}}
/* Tabellen, Überschriften, Texte */
html:root th{{background:transparent;color:{TEXT2}}}
html:root td,html:root th{{border-color:rgba(84,84,88,.45)}}
html:root tbody tr:hover td{{background:rgba(255,255,255,.03)}}
html:root h1,html:root h3{{color:#fff}}
html:root h2{{color:{TEXT2};border-color:rgba(84,84,88,.6)}}
html:root a{{color:{BLAU}}}
html:root .az,html:root .leer{{color:{TEXT2}}}
html:root hr{{border-color:{LINIE}}}
html:root code,html:root kbd{{background:{FLAECHE2};color:#fff}}
html:root .status{{background:rgba(255,255,255,.06)}}
html:root .meldung,html:root .ok-meldung{{background:{FLAECHE};color:#fff}}
/* Sheets/Dialoge */
html:root dialog,html:root dialog.rp-sheet{{background:{FLAECHE};color:#fff;box-shadow:0 24px 70px rgba(0,0,0,.7)}}
html:root dialog.rp-sheet::backdrop{{background:rgba(0,0,0,.6)}}
html:root .rp-sheet-kopf{{border-bottom-color:rgba(84,84,88,.6)}}
/* Diagramme: SVG-Texte und Achsen */
html:root main svg text{{fill:{TEXT2}}}
/* Ladeanzeige */
html:root .sk{{background:linear-gradient(90deg,{FLAECHE} 0,{FLAECHE2} 50%,{FLAECHE} 100%);background-size:200% 100%}}
/* Einführung (einfuehrung.py) */
html:root .ef-voll{{background:{GRUND};background-image:radial-gradient(1100px 620px at 12% -8%,rgba(10,132,255,.14),transparent 60%),radial-gradient(800px 600px at 50% 110%,rgba(10,132,255,.08),transparent 60%)}}
html:root .ef-punkt i[style*="#16171a"]{{background:{PILLE}!important}}
html:root .ef-spaeter{{background:{FLAECHE2};border-color:transparent;color:#fff}}
html:root .ef-fort i{{background:rgba(255,255,255,.12)}}
html:root .ef-punkt,html:root .ef-zeile,html:root .ef-zusammen li{{border-color:rgba(84,84,88,.45)}}
html:root .ef-wahl label:has(input:checked){{box-shadow:0 0 0 2.5px {BLAU},0 14px 38px rgba(0,0,0,.5)}}
html:root .ef-wahl b::after{{background-color:{FLAECHE2};border-color:rgba(255,255,255,.25)}}
html:root .ef-schalter i{{background:rgba(120,120,128,.32)}}
html:root .ef-schlicht{{background:radial-gradient(circle at 20% 0,rgba(10,132,255,.2),transparent 60%),{FLAECHE2}}}
html:root .ef-schlicht::before{{background:rgba(255,255,255,.1)}}html:root .ef-schlicht::after{{background:{FLAECHE3}}}
@media (max-width:560px){{html:root .ef-aktionen{{background:linear-gradient(transparent,{GRUND} 30%)}}}}
/* Weitere weiße Flächen aus den Modulen (gefunden per Prüfung aller Seiten) */
{_p(".blatt-kopf,.en-effekte div,.en-modul,.en-rueck,.ee-lage,.kr-fall,.kr-opt,.kr-banner,.kt-blatt,.kt-chip,.mw-staat,.rp-ac,.rp-fuell button,.rs-block,.rs-chips a,.rs-suche,"
     ".rt-lauf span,.rt-top li,.zf-live,.fz-wahl a,.v-ic,.wk-ausg,.kopf form.suche .sv,.kopf.suche-offen form.suche,.sv-liste,button.rp-storno,.hd-matrix td:first-child,.hd-matrix th:first-child,.kt-karte")}{{
 background:{FLAECHE};border-color:rgba(255,255,255,.08);color:#fff}}
html:root .kr-fall,html:root .en-rueck{{box-shadow:0 0 0 1px rgba(255,255,255,.35)}}
/* Umschalter */
html:root .ts-modus,html:root .ep-arten,html:root .st-leiste{{background:{SEGMENT};border-color:transparent}}
html:root .ts-modus a,html:root .ts-modus span,html:root .ep-arten button{{color:{TEXT2}}}
html:root .ts-modus .aktiv,html:root .ep-arten button[aria-pressed=true],html:root .st-leiste a.aktiv,html:root .rp-leiste a.aktiv,html:root .rw-unter a.aktiv{{background:{PILLE};color:#fff;border-color:transparent;box-shadow:0 3px 8px rgba(0,0,0,.35)}}
html:root .st-leiste a:hover,html:root .rs-chips a:hover{{background:rgba(255,255,255,.08);color:#fff}}
/* Elemente mit --ink als Fläche (im Dunkeln weiß) bekommen schwarze Schrift */
{_p(".ts-schritt>span,.rt-schritt>span,.kt-chip.an,.rt-lauf span.da,.status.rt-aktiv,.pf-ini,.ef-person .ini")}{{color:#000}}
/* Farbige Marken in iOS-Tönung */
html:root html.min .status,html.min:root .status{{background:rgba(118,118,128,.2)}}
html.min:root .s-ok.status{{background:rgba(48,209,88,.16)}}html.min:root .s-offen.status{{background:rgba(255,159,10,.16)}}html.min:root .s-nein.status{{background:rgba(255,69,58,.16)}}
html:root .wk-marke.bonus,html:root .wk-ausg.ja{{background:rgba(48,209,88,.14);border-color:rgba(48,209,88,.4);color:{GRUEN}}}
html:root .wk-marke.malus{{background:rgba(255,69,58,.14);border-color:rgba(255,69,58,.4);color:{ROT}}}
html:root .hb-top td{{background:rgba(48,209,88,.1)}}html:root .hb-low td{{background:rgba(255,159,10,.1)}}
html:root .ee-lage.not{{background:rgba(255,69,58,.14);border-color:{ROT};box-shadow:0 0 0 2px {ROT}}}
html:root .zf-stufe{{color:{ORANGE}}}html:root .zf-s1 .zf-stufe{{color:{ROT}}}html:root .zf-s4 .zf-stufe{{color:{GRUEN}}}
html:root .ee-lage .icon{{color:{GRUEN}}}
/* Mein Profil */
html:root .pf-zeile{{border-bottom-color:rgba(84,84,88,.45)}}
html:root .pf-schalter i{{background:rgba(120,120,128,.32)}}
html:root .pf-schalter input:checked+i{{background:{GRUEN}}}
html:root .pf-links a{{background:{FLAECHE2};border-color:transparent;color:#fff}}
html:root .pf-hinter{{background:repeating-linear-gradient(135deg,{FLAECHE2} 0 14px,{FLAECHE} 14px 28px)}}
"""

# Schwarzer Marmor für das Thema „marmor“ (Geld & Bank), wenn dunkel
MARMOR_DUNKEL = """
§{--th-tisch:radial-gradient(ellipse at 50% 40%,transparent 50%,rgba(0,0,0,.5)),MARMOR_D 0 0/1200px 1200px,#050505;
 --th-blatt:linear-gradient(rgba(10,10,10,.84),rgba(10,10,10,.84)),MARMOR_D 300px 200px/900px 900px,#0a0a0a;
 --th-blatt-rand:1px solid rgba(255,255,255,.55);--th-blatt-schatten:0 0 0 5px rgba(10,10,10,.95),0 0 0 6px rgba(255,255,255,.28),0 34px 80px rgba(0,0,0,.7);
 --th-titel-farbe:#fff;--th-zahl-farbe:#fff;--th-tab-linie:1.5px solid rgba(255,255,255,.7);
 --th-karte:#141414;--th-karte-hover:#1c1c1e;--th-karte-rand:1px solid rgba(255,255,255,.1);--th-karte-schatten:inset 0 2px 0 rgba(255,255,255,.85),0 8px 24px rgba(0,0,0,.5);
 --th-reiter:rgba(118,118,128,.24);--th-reiter-aktiv:#fff;--th-reiter-aktiv-text:#000;--th-knopf:#fff;--th-knopf-text:#000;--th-feld:#1c1c1e;--th-sheet:#141414;
 --th-marke-farbe:#fff;--th-marke-rand:1px solid rgba(255,255,255,.7);--th-marke-bg:rgba(10,10,10,.85);
 --th-nav:linear-gradient(rgba(12,12,12,.82),rgba(12,12,12,.82)),MARMOR_D 0 0/700px 700px,#0a0a0a;--th-nav-rand:1px solid rgba(255,255,255,.5);
 --th-nav-schatten:0 0 0 4px rgba(10,10,10,.92),0 0 0 5px rgba(255,255,255,.22),0 18px 44px rgba(0,0,0,.6);
 --th-nav-text:#fff;--th-nav-icon:rgba(235,235,245,.6);--th-nav-titel:rgba(235,235,245,.75);--th-nav-hover:rgba(255,255,255,.07);--th-nav-linie:rgba(255,255,255,.2)}
§ #inhalt{--ink:#fff;--grau:rgba(235,235,245,.6);--linie:rgba(84,84,88,.6);--akzent:#fff;--ok:#30d158;--rot:#ff453a}
§ #inhalt h2,§ #inhalt th{color:#fff;border-color:rgba(255,255,255,.7)}
§ #inhalt .sa-saldo,§ #inhalt .sa-saldo .sa-plus{color:#fff}
§ #inhalt a:not([class]){color:#fff}
§ #inhalt .status.s-ok{background:transparent;color:#fff;border-color:#fff}
§ #inhalt td{border-color:rgba(84,84,88,.5)}
§ #inhalt input[type=text],§ #inhalt input[type=search],§ #inhalt input[type=number],§ #inhalt select,§ #inhalt textarea{color:#fff}
§ body .sa-modus a.aktiv,§ body .sa-modus a.aktiv:hover{color:#000}
"""


def _logo_js():
    """Definiert window.saLogo(dunkel): tauscht das Schatzamt-Logo (Seitenleiste, Kopf, Einführung) gegen die Fassung für dunklen Grund
    (statisch/schatzamt-*-dunkel.png: Schwarz und Weiß getauscht, Rot und Gold echt) – statt eines Farbfilters."""
    import themen
    return ("<script>window.saLogo=window.saLogo||function(d){var U={kopf:'" + themen.statisch_url("schatzamt-kopf-dunkel.png") + "',kurz:'"
            + themen.statisch_url("schatzamt-kurz-dunkel.png") + "'};document.querySelectorAll('.seite .logo img,.kopf .logo img,.ef-kopf img').forEach(function(i){"
            "var o=i.getAttribute('data-hell');if(!o){if(!/\\/logo\\/schatzamt-(kopf|kurz)\\.png/.test(i.getAttribute('src')||''))return;o=i.getAttribute('src');i.setAttribute('data-hell',o)}"
            "i.src=d?U[/kurz/.test(o)?'kurz':'kopf']:o})};</script>")


def modus(con, k):
    import profil_sa
    if not k:
        return "hell"
    m = profil_sa.wert(con, k["id"], "sa_hell")
    return m if m in ("hell", "dunkel", "auto") else "hell"


def css(con, k, thema):
    """<style> für den Dunkelmodus (leer bei „hell“). thema = Name des Seitenthemas aus themen.py oder ''."""
    if not AKTIV:
        return ""
    m = modus(con, k)
    if m == "hell":
        return ""
    if thema and thema != "marmor":
        return ""          # Plantisch, Leitwarte … bleiben ihr Material
    inhalt = CSS
    if thema == "marmor":
        import themen
        inhalt = MARMOR_DUNKEL.replace("§", "html:root").replace("MARMOR_D", themen.MARMOR_DUNKEL_URL)
    if m == "auto":
        inhalt = "@media (prefers-color-scheme:dark){" + inhalt + "}"
    bed = "matchMedia('(prefers-color-scheme: dark)').matches" if m == "auto" else "true"
    farbe = ("<script>(function(){function setz(){var d=" + bed + ",m=document.querySelector('meta[name=theme-color]');if(m)m.content=d?'#000000':'#ffffff';saLogo(d)}"
             "if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setz);else setz();"
             + ("matchMedia('(prefers-color-scheme: dark)').addEventListener('change',setz);" if m == "auto" else "") + "})();</script>")
    return f'<style id="sa-dunkel">{inhalt}</style>{_logo_js()}{farbe}'


def vorschau_html(name):
    """Live-Umschaltung für ein Auswahlfeld/Radio-Gruppe `name` (hell/dunkel/auto): Vorschau-Style über media an/aus, gespeicherte Fassung (#sa-dunkel) aus."""
    return (f'<style id="sa-dunkel-vorschau" media="not all">{CSS}</style>' + _logo_js() +
            "<script>(function(){var v=document.getElementById('sa-dunkel-vorschau');"
            "function u(w){var alt=document.getElementById('sa-dunkel');if(alt)alt.media='not all';"
            "v.media=w==='dunkel'?'all':w==='auto'?'(prefers-color-scheme: dark)':'not all';"
            "var m=document.querySelector('meta[name=theme-color]'),d=w==='dunkel'||(w==='auto'&&matchMedia('(prefers-color-scheme: dark)').matches);if(m)m.content=d?'#000000':'#ffffff';saLogo(d)}"
            f"document.addEventListener('change',function(e){{if(e.target.name==='{name}')u(e.target.value)}})}})();</script>")
