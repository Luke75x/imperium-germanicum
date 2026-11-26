"""Themenbasiertes Design des Schatzamt-Portals (seit 26.11.2026).

Jeder Bereich bekommt den Look seines „echten“ Arbeitsplatzes: Die Seite (#inhalt) wird zum Blatt, das auf einer thematischen Unterlage (body) liegt.
* plantisch   – Verteidigung, Gerätekatalog: Lagekarte (Raster, Höhenlinien, Kompassrose) auf dem Plantisch, Kennzahlen als angepinnte Marken.
* leitwarte   – Energie: Schalttafel einer Kraftwerks-Leitwarte, Kennzahlen als Leuchtanzeigen, Schilder, Sammelschiene.
* kontor      – Handel, Förderstätten: Hauptbuch (Linien, roter Rand) auf dem Kontor-Schreibtisch.
* katalog     – Privatbesitz / Gut erwerben: Exposé-Katalog mit Goldrahmen und Losnummern auf Samt.
* tresor      – Goldreserven: gebürsteter Stahl, Kennzahlen als Goldbarren.
* krisenstab  – Krisen: Lagemeldung im Lagezentrum mit Warnstreifen.
* planung     – Entwicklung: Planpause mit Millimeterraster auf der Schneidematte, Schriftfeld.
Mein Teilstaat → Land bündelt Entwicklung/Energie/Krisen: dort wechselt das Thema mit dem sichtbaren Untertab (:has()).

Ein-/Ausschalten: Mein Profil → Darstellung → „Themenbasiertes Design“ (Schlüssel sa_thema, Standard „an“; profil_sa.thema_an).
Eingebunden in schatzamt.ant nach rp_glas. Alle Regeln beginnen mit dem Bereich „§“ (html:root bzw. html:root:has(...)) und #inhalt, damit sie
die Glas-Regeln schlagen. SCHNELL ZURÜCK: AKTIV = False + systemctl restart imperium-dienst.
"""

AKTIV = True

# Seitenschlüssel (aktiv aus sa.ant) → Thema
SEITEN = {
    "sa-verteidigung": "plantisch", "sa-rp-katalog": "plantisch",
    "sa-energie": "leitwarte", "sa-rp-energie": "leitwarte",
    "sa-handel": "kontor", "sa-rp-handel": "kontor", "sa-rp-foerder": "kontor",
    "sa-besitz": "katalog", "sa-rp-besitz": "katalog",
    "sa-gold": "tresor",
    "sa-krisen": "krisenstab",
    "sa-entwicklung": "planung",
}
# Seiten mit Untertabs: Thema je sichtbarem Abschnitt
UNTERTABS = {"sa-ts-land": {"entwicklung": "planung", "energie": "leitwarte", "krisen": "krisenstab"}}

NAMEN = {"plantisch": "Plantisch (Verteidigung)", "leitwarte": "Leitwarte (Energie)", "kontor": "Handelskontor (Handel)",
         "katalog": "Exposé-Katalog (Privatbesitz)", "tresor": "Tresor (Goldreserven)", "krisenstab": "Lagezentrum (Krisen)", "planung": "Planungstisch (Entwicklung)"}

SCHREIBMASCHINE = '"Courier New",Courier,"Nimbus Mono PS","Liberation Mono",monospace'
SCHMAL = '"Arial Narrow","Roboto Condensed","Nimbus Sans Narrow","Helvetica Neue",Arial,sans-serif'
SERIF = 'Georgia,"Times New Roman","Liberation Serif",serif'
ANZEIGE = 'ui-monospace,"SF Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace'


def _svg(s):
    return "url(\"data:image/svg+xml," + s.replace("#", "%23").replace('"', "'").replace("\n", "") + "\")"


HOEHENLINIEN = _svg("""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420"><g fill="none" stroke="#7a5a2a" stroke-opacity=".2" stroke-width="1.2">
<path d="M120 200c40-70 160-80 210-30s20 130-60 140-190-40-150-110z"/><path d="M150 205c30-45 120-52 160-20s15 90-45 96-145-28-115-76z"/>
<path d="M185 208c20-24 75-28 100-10s8 50-28 54-90-16-72-44z"/><path d="M450 90c60-30 150 10 150 80s-90 110-160 80-50-140 10-160z"/>
<path d="M470 110c40-18 100 8 100 55s-60 72-105 52-35-92 5-107z"/><path d="M495 130c18-8 50 4 50 28s-30 36-52 26-18-46 2-54z"/>
<path d="M-20 360c120-40 260 30 380 0s220-60 300-20"/><path d="M-20 392c120-40 260 30 380 0s220-60 300-20"/></g></svg>""")

KOMPASS = _svg("""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-50 -50 100 100"><g fill="none" stroke="#3a3a28" stroke-width=".8"><circle r="44"/><circle r="40"/>
<path d="M0-44V-40M0 40V44M-44 0H-40M40 0H44M31 31l-3-3M-31-31l3 3M31-31l-3 3M-31 31l3-3"/></g>
<g fill="#3a3a28"><path d="M0-34 5 0 0 34-5 0z"/><path d="M-34 0 0-4 34 0 0 4z" opacity=".55"/></g><path d="M0-34 5 0H-5z" fill="#8f2a1c"/>
<text y="-20" font-size="9" text-anchor="middle" font-family="monospace" font-weight="700" fill="#3a3a28">N</text></svg>""")


def _schraube(pos):
    return f"radial-gradient(circle,#eef1ef 0 1.5px,#8d978f 2px 4px,#5c655f 4.5px 5.5px,transparent 6px) {pos}/14px 14px no-repeat"


SCHRAUBEN = ",".join(_schraube(p) for p in ("top 10px left 10px", "top 10px right 10px", "bottom 10px left 10px", "bottom 10px right 10px"))

# ---------------------------------------------------------------- gemeinsamer Aufbau (Unterlage, Blatt, Karten, Reiter, Knöpfe, Tabellen)

BASIS = """
§{background:var(--th-tisch);background-attachment:fixed;min-height:100%;--glas:rgba(255,255,255,.84);--glas-kopf:rgba(255,255,255,.8);--glas-leiste:rgba(255,255,255,.84);--glas-blatt:rgba(255,255,255,.92)}
§ body{background:transparent}
§ #inhalt{position:relative;width:auto;min-width:0;background:var(--th-blatt);border:var(--th-blatt-rand);border-radius:var(--th-radius);box-shadow:var(--th-blatt-schatten);
 margin:16px 12px 28px 16px;padding:26px 32px 56px;color:var(--ink);font-family:var(--th-text);background-clip:padding-box}
§ #inhalt::before{content:var(--th-marke);float:right;margin:-4px 0 10px 16px;font:700 10.5px/1 var(--th-marke-schrift);letter-spacing:.16em;text-transform:uppercase;
 color:var(--th-marke-farbe);border:var(--th-marke-rand);padding:6px 9px;border-radius:var(--th-marke-radius);transform:rotate(var(--th-marke-dreh));background:var(--th-marke-bg);white-space:nowrap}
§ #inhalt h1{font-family:var(--th-titel);letter-spacing:var(--th-titel-sperr);text-transform:var(--th-titel-gross);color:var(--th-titel-farbe)}
§ #inhalt h2,§ #inhalt .ts-tabteil>h3{font-family:var(--th-titel);color:var(--th-titel-farbe)}
§ #inhalt .kennzahlen>div,§ #inhalt .sa-karte,§ #inhalt .ts-karte,§ #inhalt .sa-erkl,§ #inhalt details.sa-auf,§ #inhalt .rp-kachel,§ #inhalt .pb-karte,
§ #inhalt .sa-schnell a,§ #inhalt .sa-todo>div,§ #inhalt .zf-kopf,§ #inhalt .ts-tabs .ts-tabteil>.ts-karte,§ #inhalt .hinweis,§ #inhalt .st-karte,§ #inhalt .rp-staat{
 background:var(--th-karte);border:var(--th-karte-rand);border-radius:var(--th-karte-radius);box-shadow:var(--th-karte-schatten)}
§ #inhalt .rp-kachel:hover,§ #inhalt .kz-links>div:has(a):hover,§ #inhalt a.ts-karte:hover,§ #inhalt .sa-schnell a:hover{background:var(--th-karte-hover);border:var(--th-karte-rand);box-shadow:var(--th-karte-schatten)}
§ #inhalt .kennzahlen b{font-family:var(--th-zahl);color:var(--th-zahl-farbe);font-weight:var(--th-zahl-gewicht)}
§ #inhalt .kennzahlen>div>span,§ #inhalt .kennzahlen>div>small{color:var(--grau)}
§ #inhalt th{font-family:var(--th-tab-kopf);color:var(--grau);border-bottom:var(--th-tab-linie)}
§ #inhalt td{border-bottom-color:var(--linie)}
§ #inhalt td.num,§ #inhalt .num{font-family:var(--th-ziffern)}
§ #inhalt .reiter,§ #inhalt .ts-nav{background:var(--th-reiter)}
§ #inhalt .reiter a,§ #inhalt .ts-nav a{color:var(--grau)}
§ #inhalt .reiter a.aktiv,§ #inhalt .ts-nav a.aktiv{background:var(--th-reiter-aktiv);color:var(--th-reiter-aktiv-text);box-shadow:0 2px 6px rgba(0,0,0,.18)}
§ #inhalt .btn:not(.zweit):not(.gefahr),§ #inhalt button.btn:not(.zweit):not(.gefahr){background:var(--th-knopf);color:var(--th-knopf-text);border-color:transparent}
§ #inhalt .btn.zweit,§ #inhalt .rp-chip,§ #inhalt .pb-chips a,§ #inhalt .hd-chips a{background:var(--th-karte);border:var(--th-karte-rand);color:var(--ink)}
§ #inhalt .rp-chip.aktiv,§ #inhalt .pb-chips a.aktiv,§ #inhalt .hd-chips a.aktiv{background:var(--th-reiter-aktiv);color:var(--th-reiter-aktiv-text);border-color:transparent}
§ #inhalt a:not([class]){color:var(--akzent)}
§ #inhalt input[type=text],§ #inhalt input[type=search],§ #inhalt input[type=number],§ #inhalt select,§ #inhalt textarea{background:var(--th-feld);border-color:var(--linie)}
§ #inhalt dialog.rp-sheet{background:var(--th-sheet);font-family:var(--th-text)}
§ #inhalt .az,§ #inhalt .sa-krumen{color:var(--grau)}
@media (max-width:800px){§ #inhalt{margin:8px 8px 20px;padding:18px 15px 40px}§ #inhalt::before{float:none;display:table;margin:0 0 12px auto;font-size:9.5px}}
"""

THEMEN = {
    # ------------------------------------------------ Verteidigung: Lagekarte auf dem Plantisch
    "plantisch": {
        "vars_body": f"""--th-tisch:radial-gradient(1200px 700px at 50% -10%,rgba(255,236,180,.16),transparent 65%),
 repeating-linear-gradient(90deg,rgba(0,0,0,.07) 0 2px,transparent 2px 7px,rgba(255,255,255,.02) 7px 8px,transparent 8px 13px),
 linear-gradient(180deg,#2f3a27,#1f271a);
 --th-blatt:{KOMPASS} right 26px bottom 22px/150px 150px no-repeat,{HOEHENLINIEN} 0 0/640px 420px,
 linear-gradient(rgba(70,74,40,.16) 1px,transparent 1px) -1px -1px/48px 48px,linear-gradient(90deg,rgba(70,74,40,.16) 1px,transparent 1px) -1px -1px/48px 48px,
 linear-gradient(rgba(70,74,40,.06) 1px,transparent 1px) -1px -1px/12px 12px,linear-gradient(90deg,rgba(70,74,40,.06) 1px,transparent 1px) -1px -1px/12px 12px,
 radial-gradient(ellipse at 30% 20%,#efe8cf,#e2d8b5 70%,#d6caa2);
 --th-blatt-rand:1px solid #a99c6e;--th-radius:3px;--th-blatt-schatten:0 2px 0 #c8bb8e,0 28px 70px rgba(0,0,0,.55),inset 0 0 60px rgba(120,96,40,.18);
 --th-text:inherit;--th-titel:{SCHMAL};--th-titel-sperr:.07em;--th-titel-gross:uppercase;--th-titel-farbe:#262a1a;
 --th-zahl:{SCHREIBMASCHINE};--th-zahl-farbe:#22261a;--th-zahl-gewicht:700;--th-ziffern:{SCHREIBMASCHINE};--th-tab-kopf:{SCHREIBMASCHINE};--th-tab-linie:2px solid #4a4a30;
 --th-karte:linear-gradient(180deg,#f8f3e0,#efe7cc);--th-karte-hover:#fbf7e8;--th-karte-rand:1px solid #b2a578;--th-karte-radius:2px;
 --th-karte-schatten:0 1px 0 rgba(255,255,255,.6) inset,0 6px 14px rgba(50,40,10,.22),0 1px 2px rgba(50,40,10,.2);
 --th-reiter:rgba(60,62,36,.13);--th-reiter-aktiv:#2f3a27;--th-reiter-aktiv-text:#efe8cf;--th-knopf:#3d4a2a;--th-knopf-text:#f3eed8;
 --th-feld:rgba(255,252,240,.85);--th-sheet:#f6f1dc;
 --th-marke:"Lagekarte · Nur für den Dienstgebrauch";--th-marke-schrift:{SCHREIBMASCHINE};--th-marke-farbe:rgba(150,30,24,.85);--th-marke-rand:2px solid rgba(150,30,24,.7);
 --th-marke-radius:3px;--th-marke-dreh:-2.5deg;--th-marke-bg:rgba(255,250,235,.35)""",
        "vars_inhalt": "--ink:#23271a;--grau:#5b5c44;--linie:rgba(74,74,48,.28);--akzent:#7a2a1a;--ok:#3d5a1e",
        "extra": """
§ #inhalt{padding-bottom:190px}
§ #inhalt .kennzahlen>div{position:relative;overflow:visible}
§ #inhalt .kennzahlen>div::before{content:"";position:absolute;top:-6px;left:50%;width:13px;height:13px;margin-left:-6px;border-radius:50%;z-index:2;
 background:radial-gradient(circle at 35% 30%,#ff9d8c,#c0291c 55%,#6a120b);box-shadow:1px 3px 3px rgba(0,0,0,.4)}
§ #inhalt .kennzahlen>div:nth-child(3n+1){transform:rotate(-.6deg)}§ #inhalt .kennzahlen>div:nth-child(3n+2){transform:rotate(.45deg)}
§ #inhalt .kennzahlen>div:nth-child(4n){transform:rotate(-.25deg)}
§ #inhalt .kennzahlen>div:nth-child(3n+2)::before{background:radial-gradient(circle at 35% 30%,#a9c3ff,#244b9c 55%,#0e2253)}
§ #inhalt h2{font-family:""" + SCHREIBMASCHINE + """;letter-spacing:.14em;color:#3a3a24;border-bottom:1px dashed rgba(74,74,48,.55);padding-bottom:6px}
§ #inhalt h1{font-weight:800;font-stretch:condensed}
§ #inhalt td{border-bottom:1px dashed rgba(74,74,48,.32)}
§ #inhalt tbody tr:hover td{background:rgba(255,250,230,.5)}
§ #inhalt .sa-saldo{font-family:""" + SCHREIBMASCHINE + """}
§ #inhalt .sa-erkl{background:repeating-linear-gradient(transparent 0 23px,rgba(74,74,48,.12) 23px 24px),#f7f1dc;font-family:""" + SCHREIBMASCHINE + """;font-size:13.5px}
""",
    },
    # ------------------------------------------------ Energie: Schalttafel einer Leitwarte
    "leitwarte": {
        "vars_body": f"""--th-tisch:radial-gradient(1200px 600px at 50% -10%,rgba(120,200,255,.13),transparent 60%),
 linear-gradient(rgba(255,255,255,.028) 1px,transparent 1px) 0 0/32px 32px,linear-gradient(90deg,rgba(255,255,255,.028) 1px,transparent 1px) 0 0/32px 32px,#151a1e;
 --th-blatt:{SCHRAUBEN},repeating-linear-gradient(90deg,rgba(255,255,255,.06) 0 1px,transparent 1px 3px),linear-gradient(180deg,#d3dcd4,#c3cdc5);
 --th-blatt-rand:4px solid #8f9b92;--th-radius:8px;--th-blatt-schatten:inset 0 2px 0 rgba(255,255,255,.55),inset 0 -2px 0 rgba(0,0,0,.08),0 30px 70px rgba(0,0,0,.6);
 --th-text:inherit;--th-titel:{SCHMAL};--th-titel-sperr:.05em;--th-titel-gross:uppercase;--th-titel-farbe:#1d2427;
 --th-zahl:{ANZEIGE};--th-zahl-farbe:#ffb547;--th-zahl-gewicht:600;--th-ziffern:{ANZEIGE};--th-tab-kopf:{ANZEIGE};--th-tab-linie:2px solid #2b3236;
 --th-karte:linear-gradient(180deg,#e2e8e2,#d6ddd7);--th-karte-hover:#e8ede8;--th-karte-rand:1px solid #95a299;--th-karte-radius:6px;
 --th-karte-schatten:inset 0 1px 0 rgba(255,255,255,.7),inset 0 -1px 0 rgba(0,0,0,.06),0 2px 4px rgba(0,0,0,.12);
 --th-reiter:rgba(29,36,39,.14);--th-reiter-aktiv:#1b2124;--th-reiter-aktiv-text:#ffb547;--th-knopf:#263034;--th-knopf-text:#e9efe9;
 --th-feld:#eef2ee;--th-sheet:#dfe6e0;
 --th-marke:"Leitwarte · Netzbetrieb";--th-marke-schrift:{ANZEIGE};--th-marke-farbe:#e7ede8;--th-marke-rand:1px solid #11161a;
 --th-marke-radius:3px;--th-marke-dreh:0deg;--th-marke-bg:linear-gradient(180deg,#39434a,#232b30)""",
        "vars_inhalt": "--ink:#1b2225;--grau:#4f5b55;--linie:rgba(43,50,54,.22);--akzent:#1f4e8c;--ok:#1d6b34",
        "extra": """
§ #inhalt h1::after{content:"";display:block;height:5px;width:min(380px,100%);margin-top:10px;border-radius:2px;
 background:linear-gradient(90deg,#c62828 0 33%,#1d7a3c 33% 66%,#1f4e8c 66%);box-shadow:0 1px 0 rgba(255,255,255,.6)}
§ #inhalt .kennzahlen>div{position:relative;background:linear-gradient(180deg,#232b2f,#141a1d);border:3px solid #66726b;border-radius:8px;
 box-shadow:inset 0 2px 10px rgba(0,0,0,.7),0 1px 0 rgba(255,255,255,.6),0 4px 10px rgba(0,0,0,.2)}
§ #inhalt .kennzahlen>div:hover,§ #inhalt .kz-links>div:has(a):hover{background:linear-gradient(180deg,#273035,#171d20)}
§ #inhalt .kennzahlen>div::after{content:"";position:absolute;top:9px;right:10px;width:7px;height:7px;border-radius:50%;background:#46e06e;box-shadow:0 0 6px 1px rgba(70,224,110,.75)}
§ #inhalt .kennzahlen b{text-shadow:0 0 10px rgba(255,170,40,.5);letter-spacing:.02em}
§ #inhalt .kennzahlen>div,§ #inhalt .kennzahlen>div *:not(b){color:#a8b6ad}
§ #inhalt .kennzahlen>div b *{color:inherit}
§ #inhalt h2,§ #inhalt .ts-tabteil>h3{display:table;background:linear-gradient(180deg,#39434a,#232b30);color:#e7ede8;padding:6px 11px;border-radius:3px;border:0;
 font:600 11.5px/1.2 """ + ANZEIGE + """;letter-spacing:.14em;text-transform:uppercase;box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 1px 0 rgba(255,255,255,.5)}
§ #inhalt .ee-bar{border:2px solid #232b30;border-radius:4px;box-shadow:inset 0 1px 3px rgba(0,0,0,.3)}
§ #inhalt .ee-lage,§ #inhalt .ee-lage.gut{background:#1b2124;color:#7cf09a;border:2px solid #66726b;font-family:""" + ANZEIGE + """}
§ #inhalt .ee-lage .icon{color:#46e06e}
""",
    },
    # ------------------------------------------------ Handel: Hauptbuch auf dem Kontor-Schreibtisch
    "kontor": {
        "vars_body": """--th-tisch:radial-gradient(1100px 650px at 45% -5%,rgba(255,214,150,.22),transparent 65%),
 repeating-linear-gradient(101deg,rgba(0,0,0,.09) 0 2px,transparent 2px 9px,rgba(255,255,255,.035) 9px 10px,transparent 10px 17px),
 repeating-linear-gradient(97deg,rgba(60,30,10,.15) 0 30px,transparent 30px 74px),linear-gradient(180deg,#6a4327,#4a2d18);
 --th-blatt:linear-gradient(90deg,transparent 46px,rgba(185,40,40,.42) 46px 47px,transparent 47px 50px,rgba(185,40,40,.42) 50px 51px,transparent 51px),
 repeating-linear-gradient(transparent 0 29px,rgba(60,100,170,.16) 29px 30px),radial-gradient(ellipse at 40% 20%,#fbf5e4,#f1e6c9 80%);
 --th-blatt-rand:1px solid #c9b183;--th-radius:2px;--th-blatt-schatten:0 1px 0 #e9dcb8,0 3px 0 #d8c69c,0 5px 0 #e9dcb8,0 30px 70px rgba(30,12,0,.55);
 --th-text:inherit;--th-titel:""" + SERIF + """;--th-titel-sperr:.01em;--th-titel-gross:none;--th-titel-farbe:#3a2914;
 --th-zahl:""" + SERIF + """;--th-zahl-farbe:#1f3a6e;--th-zahl-gewicht:700;--th-ziffern:""" + SERIF + """;--th-tab-kopf:""" + SERIF + """;--th-tab-linie:3px double #8a6d3b;
 --th-karte:#fffaf0;--th-karte-hover:#fffdf6;--th-karte-rand:1px solid #d3bf92;--th-karte-radius:3px;
 --th-karte-schatten:0 1px 2px rgba(60,30,0,.15),0 6px 14px rgba(60,30,0,.12);
 --th-reiter:rgba(90,58,34,.11);--th-reiter-aktiv:#5a3a22;--th-reiter-aktiv-text:#f6efdc;--th-knopf:#5a3a22;--th-knopf-text:#f6efdc;
 --th-feld:#fffcf3;--th-sheet:#fbf5e4;
 --th-marke:"Handelskontor · Hauptbuch";--th-marke-schrift:""" + SERIF + """;--th-marke-farbe:rgba(150,32,28,.85);--th-marke-rand:2px double rgba(150,32,28,.6);
 --th-marke-radius:999px;--th-marke-dreh:-3deg;--th-marke-bg:transparent""",
        "vars_inhalt": "--ink:#2e2213;--grau:#6e5b40;--linie:rgba(138,109,59,.28);--akzent:#1f3a6e;--ok:#2f6a2a",
        "extra": """
§ #inhalt{padding-left:72px}
§ #inhalt h1{font-weight:700;font-size:30px}
§ #inhalt h2{font-variant:small-caps;letter-spacing:.06em;font-size:16px;text-transform:none;color:#5a3a22;border-bottom:3px double #b59a64;padding-bottom:4px}
§ #inhalt th{font-variant:small-caps;letter-spacing:.05em;text-transform:none;font-size:13.5px}
§ #inhalt .kennzahlen>div{border-top:5px solid #8a6d3b}
§ #inhalt .kennzahlen b{font-size:27px}
@media (max-width:800px){§ #inhalt{padding-left:40px}§{--th-blatt:linear-gradient(90deg,transparent 22px,rgba(185,40,40,.42) 22px 23px,transparent 23px),
 repeating-linear-gradient(transparent 0 29px,rgba(60,100,170,.16) 29px 30px),#f8efd8}}
""",
    },
    # ------------------------------------------------ Privatbesitz: Exposé-Katalog auf Samt
    "katalog": {
        "vars_body": """--th-tisch:radial-gradient(900px 520px at 50% -6%,rgba(255,210,170,.22),transparent 65%),
 repeating-linear-gradient(135deg,rgba(255,255,255,.018) 0 2px,transparent 2px 5px),radial-gradient(circle at 50% 0,#5c2335,#2a0e17 75%) fixed;
 --th-blatt:linear-gradient(180deg,#fdfbf5,#f6f0e2);
 --th-blatt-rand:1px solid #c6a960;--th-radius:2px;--th-blatt-schatten:0 0 0 6px #fdfbf5,0 0 0 7px #c6a960,0 34px 80px rgba(0,0,0,.6);
 --th-text:inherit;--th-titel:""" + SERIF + """;--th-titel-sperr:.14em;--th-titel-gross:uppercase;--th-titel-farbe:#2a0e17;
 --th-zahl:""" + SERIF + """;--th-zahl-farbe:#8a6a1f;--th-zahl-gewicht:400;--th-ziffern:""" + SERIF + """;--th-tab-kopf:""" + SERIF + """;--th-tab-linie:1px solid #c6a960;
 --th-karte:#fff;--th-karte-hover:#fffdf8;--th-karte-rand:1px solid #e3d5b0;--th-karte-radius:2px;
 --th-karte-schatten:0 1px 2px rgba(42,14,23,.08),0 10px 24px rgba(42,14,23,.08);
 --th-reiter:rgba(42,14,23,.06);--th-reiter-aktiv:#2a0e17;--th-reiter-aktiv-text:#ead9a8;--th-knopf:#2a0e17;--th-knopf-text:#f3e6c0;
 --th-feld:#fffdf8;--th-sheet:#fdfbf5;
 --th-marke:"Katalog · Erwerbungen";--th-marke-schrift:""" + SERIF + """;--th-marke-farbe:#8a6a1f;--th-marke-rand:1px solid #c6a960;
 --th-marke-radius:0;--th-marke-dreh:0deg;--th-marke-bg:transparent""",
        "vars_inhalt": "--ink:#2a1a1f;--grau:#7a6a5e;--linie:rgba(198,169,96,.35);--akzent:#6d2236;--ok:#2f6a2a",
        "extra": """
§ #inhalt{margin-top:22px}
§ #inhalt h1{font-weight:400;font-size:28px}
§ #inhalt h1 .icon{color:#c6a960}
§ #inhalt h2{font-weight:400;letter-spacing:.18em;font-size:13px;color:#8a6a1f;border:0;text-align:center}
§ #inhalt h2::before,§ #inhalt h2::after{content:"";display:inline-block;width:40px;height:1px;background:#c6a960;vertical-align:middle;margin:0 12px}
§ #inhalt .pb-karten{counter-reset:los}
§ #inhalt .pb-karte{counter-increment:los;position:relative;padding-top:30px;outline:1px solid #efe5c8;outline-offset:-6px}
§ #inhalt .pb-karte::before{content:"Los " counter(los,decimal-leading-zero);position:absolute;top:12px;left:14px;font:400 10.5px/1 """ + SERIF + """;letter-spacing:.2em;text-transform:uppercase;color:#a88a3c}
§ #inhalt .pb-karte h3{font-family:""" + SERIF + """;font-weight:400;font-size:17px}
§ #inhalt .pb-karte .sa-werte b,§ #inhalt .pb-karte .sa-werte dd{font-family:""" + SERIF + """}
""",
    },
    # ------------------------------------------------ Goldreserven: Tresor
    "tresor": {
        "vars_body": """--th-tisch:repeating-radial-gradient(circle at 88% 26%,rgba(255,255,255,.035) 0 2px,transparent 2px 22px),
 radial-gradient(900px 600px at 88% 26%,rgba(255,255,255,.07),transparent 70%),linear-gradient(180deg,#252a30,#15181c);
 --th-blatt:""" + SCHRAUBEN + """,repeating-linear-gradient(90deg,rgba(255,255,255,.22) 0 1px,rgba(0,0,0,.018) 1px 3px),linear-gradient(170deg,#eef0f2,#d0d5da 60%,#c5cbd1);
 --th-blatt-rand:1px solid #8d969f;--th-radius:12px;--th-blatt-schatten:inset 0 1px 0 #fff,inset 0 -3px 8px rgba(0,0,0,.08),0 30px 70px rgba(0,0,0,.6);
 --th-text:inherit;--th-titel:""" + SCHMAL + """;--th-titel-sperr:.08em;--th-titel-gross:uppercase;--th-titel-farbe:#2c3238;
 --th-zahl:""" + SERIF + """;--th-zahl-farbe:#3a2a05;--th-zahl-gewicht:700;--th-ziffern:inherit;--th-tab-kopf:inherit;--th-tab-linie:2px solid #59626b;
 --th-karte:linear-gradient(180deg,#f4f6f7,#e3e7ea);--th-karte-hover:#f7f8f9;--th-karte-rand:1px solid #a7b0b8;--th-karte-radius:8px;
 --th-karte-schatten:inset 0 1px 0 #fff,0 3px 8px rgba(0,0,0,.14);
 --th-reiter:rgba(44,50,56,.1);--th-reiter-aktiv:#2c3238;--th-reiter-aktiv-text:#f0d77d;--th-knopf:#2c3238;--th-knopf-text:#f0d77d;
 --th-feld:#f8f9fa;--th-sheet:#eef0f2;
 --th-marke:"Tresor · Goldreserve";--th-marke-schrift:""" + SCHMAL + """;--th-marke-farbe:#3a2a05;--th-marke-rand:1px solid #9c7a1e;
 --th-marke-radius:3px;--th-marke-dreh:0deg;--th-marke-bg:linear-gradient(160deg,#fbeeb0,#e2bd4f 45%,#c9a031 70%,#f0d77d)""",
        "vars_inhalt": "--ink:#22272c;--grau:#58616a;--linie:rgba(89,98,107,.28);--akzent:#7a5a0e;--ok:#2f6a2a",
        "extra": """
§ #inhalt .kennzahlen>div{background:linear-gradient(160deg,#fcf1bd 0%,#e6c35a 32%,#bf972f 58%,#e9c964 80%,#f6e39a 100%);border:1px solid #9c7a1e;
 clip-path:polygon(5% 0,95% 0,100% 100%,0 100%);border-radius:0;padding-left:22px;padding-right:22px;
 box-shadow:inset 0 2px 0 rgba(255,255,255,.6),inset 0 -3px 0 rgba(120,80,0,.25)}
§ #inhalt .kennzahlen>div,§ #inhalt .kennzahlen>div *:not(b){color:#5a4510}
§ #inhalt .kennzahlen b{text-shadow:0 1px 0 rgba(255,245,200,.7)}
§ #inhalt h2{color:#4a525a;text-shadow:0 1px 0 #fff;letter-spacing:.12em}
""",
    },
    # ------------------------------------------------ Krisen: Lagemeldung im Lagezentrum
    "krisenstab": {
        "vars_body": """--th-tisch:repeating-linear-gradient(-45deg,#e0b000 0 16px,#18191d 16px 32px) top/100% 8px no-repeat,
 radial-gradient(1000px 420px at 50% 0,rgba(210,30,30,.26),transparent 70%),linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px) 0 0/28px 28px,#17181c;
 --th-blatt:repeating-linear-gradient(-45deg,#e0b000 0 14px,#1d1d1f 14px 28px) top/100% 8px no-repeat,linear-gradient(180deg,#fdfcf8,#f5f2ea);
 --th-blatt-rand:1px solid #cfcab9;--th-radius:4px;--th-blatt-schatten:0 30px 70px rgba(0,0,0,.6);
 --th-text:inherit;--th-titel:""" + SCHREIBMASCHINE + """;--th-titel-sperr:.04em;--th-titel-gross:uppercase;--th-titel-farbe:#1d1d1f;
 --th-zahl:""" + SCHREIBMASCHINE + """;--th-zahl-farbe:#1d1d1f;--th-zahl-gewicht:700;--th-ziffern:""" + SCHREIBMASCHINE + """;--th-tab-kopf:""" + SCHREIBMASCHINE + """;--th-tab-linie:2px solid #1d1d1f;
 --th-karte:#fff;--th-karte-hover:#fffdf7;--th-karte-rand:1px solid #d8d3c3;--th-karte-radius:3px;
 --th-karte-schatten:0 2px 6px rgba(0,0,0,.08);
 --th-reiter:rgba(29,29,31,.08);--th-reiter-aktiv:#9b1c1c;--th-reiter-aktiv-text:#fff;--th-knopf:#9b1c1c;--th-knopf-text:#fff;
 --th-feld:#fff;--th-sheet:#fdfcf8;
 --th-marke:"● Lagezentrum · Krisenstab";--th-marke-schrift:""" + SCHREIBMASCHINE + """;--th-marke-farbe:#fff;--th-marke-rand:0;
 --th-marke-radius:2px;--th-marke-dreh:0deg;--th-marke-bg:#9b1c1c""",
        "vars_inhalt": "--ink:#1d1d1f;--grau:#5e5b52;--linie:rgba(29,29,31,.16);--akzent:#9b1c1c",
        "extra": """
§ #inhalt{padding-top:34px}
§ #inhalt::before{animation:th-puls 2.2s ease-in-out infinite}
@keyframes th-puls{50%{box-shadow:0 0 0 4px rgba(155,28,28,.18)}}
§ #inhalt .kennzahlen>div,§ #inhalt details.sa-auf,§ #inhalt .ts-karte{box-shadow:inset 4px 0 0 #9b1c1c,0 2px 6px rgba(0,0,0,.08)}
§ #inhalt h2,§ #inhalt .ts-tabteil>h3{letter-spacing:.12em;font-size:13px;border-bottom:2px solid #1d1d1f;padding-bottom:5px}
""",
    },
    # ------------------------------------------------ Entwicklung: Planpause auf dem Zeichentisch
    "planung": {
        "vars_body": """--th-tisch:linear-gradient(rgba(255,255,255,.08) 1px,transparent 1px) 0 0/40px 40px,linear-gradient(90deg,rgba(255,255,255,.08) 1px,transparent 1px) 0 0/40px 40px,
 linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px) 0 0/8px 8px,linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px) 0 0/8px 8px,
 radial-gradient(1100px 600px at 50% -10%,rgba(255,255,255,.12),transparent 60%),#2c4e42;
 --th-blatt:linear-gradient(rgba(40,90,160,.15) 1px,transparent 1px) -1px -1px/40px 40px,linear-gradient(90deg,rgba(40,90,160,.15) 1px,transparent 1px) -1px -1px/40px 40px,
 linear-gradient(rgba(40,90,160,.06) 1px,transparent 1px) -1px -1px/8px 8px,linear-gradient(90deg,rgba(40,90,160,.06) 1px,transparent 1px) -1px -1px/8px 8px,#f3f7fb;
 --th-blatt-rand:1px solid #a9bfd8;--th-radius:1px;--th-blatt-schatten:0 26px 60px rgba(0,0,0,.45);
 --th-text:inherit;--th-titel:""" + SCHMAL + """;--th-titel-sperr:.1em;--th-titel-gross:uppercase;--th-titel-farbe:#1d3c6e;
 --th-zahl:""" + ANZEIGE + """;--th-zahl-farbe:#1d3c6e;--th-zahl-gewicht:600;--th-ziffern:""" + ANZEIGE + """;--th-tab-kopf:""" + SCHMAL + """;--th-tab-linie:1.5px solid #1d3c6e;
 --th-karte:rgba(255,255,255,.82);--th-karte-hover:#fff;--th-karte-rand:1px solid #9fb6d1;--th-karte-radius:1px;
 --th-karte-schatten:3px 3px 0 rgba(29,60,110,.12);
 --th-reiter:rgba(29,60,110,.08);--th-reiter-aktiv:#1d3c6e;--th-reiter-aktiv-text:#f3f7fb;--th-knopf:#1d3c6e;--th-knopf-text:#f3f7fb;
 --th-feld:#fff;--th-sheet:#f3f7fb;
 --th-marke:"Planungsamt · Entwicklungsplan";--th-marke-schrift:""" + SCHMAL + """;--th-marke-farbe:#1d3c6e;--th-marke-rand:1.5px solid #1d3c6e;
 --th-marke-radius:0;--th-marke-dreh:0deg;--th-marke-bg:rgba(255,255,255,.7)""",
        "vars_inhalt": "--ink:#14243f;--grau:#4a5f7c;--linie:rgba(29,60,110,.2);--akzent:#1d3c6e",
        "extra": """
§ #inhalt{padding-bottom:84px}
§ #inhalt::after{content:"Entwicklungsplan\\A Blatt 1 · M 1 : 100 000";white-space:pre;position:absolute;right:16px;bottom:14px;padding:7px 12px;
 border:1.5px solid #1d3c6e;background:rgba(255,255,255,.85);font:600 10px/1.5 """ + SCHMAL + """;letter-spacing:.14em;text-transform:uppercase;color:#1d3c6e}
§ #inhalt h2,§ #inhalt .ts-tabteil>h3{letter-spacing:.16em;font-size:12.5px;border-bottom:1.5px solid #1d3c6e;padding-bottom:4px}
§ #inhalt h2::before,§ #inhalt .ts-tabteil>h3::before{content:"▸ ";color:#c0392b}
§ #inhalt th{text-transform:uppercase;letter-spacing:.08em}
""",
    },
}


def _css_thema(name, bereich):
    t = THEMEN[name]
    css = f"§{{{t['vars_body']}}}§ #inhalt{{{t['vars_inhalt']}}}" + BASIS + t["extra"]
    return css.replace("§", bereich)


def css(aktiv):
    """<style> für die Seite (leer, wenn die Seite kein Thema hat)."""
    if not AKTIV:
        return ""
    if aktiv in SEITEN:
        inhalt = _css_thema(SEITEN[aktiv], "html:root")
    elif aktiv in UNTERTABS:
        inhalt = "".join(_css_thema(th, f"html:root:has(#t-{teil}:not([hidden]))") for teil, th in UNTERTABS[aktiv].items())
    else:
        return ""
    return f'<style id="sa-thema">{inhalt}</style>'
