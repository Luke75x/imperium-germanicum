"""Sitzordnung des Reichstagsgebäudes (Plenarsaal) – Daten und SVG für /informationen/der-reichstag/sitzordnung/.

Aufbau (nach dem Vorbild der Sitzverteilung des Bundestags, angepasst):
- Thron: dort, wo im Bundestag der Direktor sitzt, sitzt der Monarch (1 Sitz). Daneben das Präsidium (der Präsident des Reichstags, 1 Sitz).
- Reichsverwaltungsbank (links; im Bundestag die Regierungsbank): der Kronkanzler und die Leiter der Reichsbehörden (18 Sitze, keine zusätzlichen Ämter).
- Senatsbank (rechts; im Bundestag die Bundesratsbank): 8 Plätze für die Kurfürsten.
- Plenum (Halbkreis): je Landesherr eine Delegation von 6 Sitzen (Landesherr + 5), geordnet von West nach Ost (nach der Hauptstadt).
  Für die Teilstaaten unter Reichsvertretung (Gouvernement Baden, Generalgouvernement Venedig) sind Delegationen vorgehalten,
  dazu ein freier Reserveblock für künftige Teilstaaten. So bleibt die Raumform stabil, wenn ein Gebiet einen Landesherrn erhält.

Aufruf: sitzordnung.svg() liefert das SVG, sitzordnung.DELEGATIONEN die Daten für die Legende.
"""
import html
import math

import reichsbehoerden as RB

esc = html.escape
BLOCK = 6                      # Sitze je Delegation: Landesherr und 5 Delegierte

# ---- Geometrie nach der Sitzplan-Grafik des Bundestags (bundestag.de/parlament/plenum/sitzverteilung, Koordinatensystem 822 x 608):
#   Plenum = konzentrische Reihen um das Rednerpult (MITTE), innerste Reihe Radius 87,5; fünf Sektoren, getrennt durch vier Gänge;
#   die Reihen reichen links und rechts etwas über die Waagerechte hinaus (−12° … 192°, Winkel mit y nach unten).
#   Bänke (Regierungs- und Bundesratsbank) = Bögen um Punkte weit unter dem Saal, vorderste Reihe zum Plenum hin.
#   Weil der Reichstag nur 148 statt rund 900 Plätze hat, sind die Sitze größer (Abstand ABSTAND statt 19,5) – die Form bleibt dieselbe.
ABSTAND = 29.0                 # Mittelpunktabstand benachbarter Sitze (Bundestag: 19,5); ergibt genau 6 volle Reihen = 120 Plätze
SITZ_R = 9
MITTE = (411.0, 196.0)         # Rednerpult = Mittelpunkt der Plenumsreihen
PLENUM_R0 = 87.5               # Radius der innersten Reihe
SEKTOREN = [(-11.9, 8.0), (13.0, 47.0), (51.8, 76.0), (81.0, 145.0), (149.8, 191.9)]   # Grad, zwischen ihnen die Gänge
BANK_LINKS = {"mitte": (396.0, 540.0), "reihen": [(455.0, 364.0), (481.5, 360.0), (508.0, 355.0)]}   # (Radius, x des innersten Sitzes)
BANK_RECHTS = {"mitte": (396.0, 670.0), "reihen": [(588.0, 459.0), (615.0, 464.0)]}
THRON = (390.0, 40.0)          # dort, wo im Bundestag der Direktor neben dem Präsidententisch sitzt
TISCH = (403.0, 27.0, 16.0, 30.0)
PRAESIDENT = (411.0, 77.0)
PULT = (403.0, 150.0, 16.0, 12.0)

# (Kurzname, Anrede des Oberhaupts, Farbe der Reichskarte, x der Hauptstadt = West→Ost, Art)
#   Art: "landesherr" = Delegation; "gouvernement" = unter Reichsvertretung, Delegation vorgehalten
STAATEN = [
    ("Freistaat Preußen", "Oberhaupt", "#b54a4a", 20754.0, "landesherr"),
    ("Königreich Schweiz", "König", "#cc3433", 20827.7, "landesherr"),
    ("Westerwälder Union", "König", "#01665e", 20884.2, "landesherr"),
    ("Gouvernement Baden", "Gouverneur", "#ffff00", 20933.2, "gouvernement"),
    ("Erzherzogtum Pfalz-Bayern", "Erzherzog", "#000000", 20941.2, "landesherr"),
    ("Großherzogtum Schwaben-Württemberg", "Großherzog", "#ff7f00", 21019.7, "landesherr"),
    ("Königreich Hannover", "König", "#d6ac0c", 21081.3, "landesherr"),
    ("Fürstbistum Würzburg", "Fürstbischof", "#cab2d6", 21105.7, "landesherr"),
    ("Fürstentum Holstein", "Fürst", "#be3202", 21126.8, "landesherr"),
    ("Freier Hansebund", "Oberhaupt", "#fccce4", 21112.9, "landesherr"),
    ("Fürstentum Franken", "Fürst", "#baa087", 21231.1, "landesherr"),
    ("Herzogtum Tirol-Salzburg", "Herzog", "#b3de6a", 21265.2, "landesherr"),
    ("Generalgouvernement Venedig", "Generalgouverneur", "#72b28d", 21368.8, "gouvernement"),
    ("Heiliger Stuhl", "Papst", "#4d014c", 21389.1, "landesherr"),
    ("Königreich Apulien", "König", "#1ec5e3", 21585.8, "landesherr"),
    ("Landgrafschaft Lausitz", "Landgraf", "#fedbc7", 21592.6, "landesherr"),
    ("Königreich Böhmen", "König", "#f4a682", 21602.7, "landesherr"),
    ("Markgrafschaft Mähren", "Markgraf", "#cb503e", 21846.4, "landesherr"),
    ("St. Longinus Orden", "Oberhaupt", "#ffff33", 22276.2, "landesherr"),
]
STAATEN.sort(key=lambda s: s[3])
RESERVE_ZUSATZ = 1             # freie Reserveblöcke am Ostende (künftige Teilstaaten)

# Reichsverwaltungsbank (im Bundestag die Regierungsbank), Reihen von vorn (zum Plenum) nach hinten, jeweils von der Mitte nach außen:
#   vorn der Kronkanzler mit den Generaldirektoren der Behörden für Sicherheit und Ordnung, dahinter die übrigen Behörden, hinten die Reichsämter.
VERWALTUNG_REIHEN = [
    ["kanzlei", "krs", "polizei", "zoll", "katastrophenschutz"],
    ["inquisition", "schatzamt", "generalkonsulat", "heroldsamt", "crownestates", "inneres"],
    ["zentralbank", "reichskasse", "forschung", "gesundheit", "verkehr", "arbeit", "einwanderung"],
]                              # 5 + 6 + 7 = 18, wie im Bundestag die vorderste Reihe am kürzesten
SENAT_REIHEN = [4, 4]          # Senatsbank, von vorn nach hinten


def _behoerde(schl):
    if schl == "kanzlei":
        k = RB.KANZLEI
        return {"titel": "Kronkanzler", "stelle": k["kurz"], "schl": schl}
    b = next(x for x in RB.BEHOERDEN if x["schl"] == schl)
    return {"titel": b["leitung"], "stelle": b["name"], "schl": schl}


VERWALTUNG = [[_behoerde(x) for x in reihe] for reihe in VERWALTUNG_REIHEN]
KURFUERSTEN = sum(SENAT_REIHEN)


def _reihe(r):
    """Sitzwinkel (Grad) einer Plenumsreihe mit Radius r: je Sektor so viele Sitze, wie mit ABSTAND hineinpassen, mittig verteilt."""
    out = []
    schritt = math.degrees(ABSTAND / r)
    for a0, a1 in SEKTOREN:
        n = int((a1 - a0) / schritt) + 1
        start = (a0 + a1) / 2 - (n - 1) * schritt / 2
        out += [start + k * schritt for k in range(n)]
    return out


def plenum_sitze(gesamt):
    """Plätze (Winkel, Reihe, Radius) von innen nach außen, bis `gesamt` erreicht ist; die äußerste Reihe wird von den Rändern her
    gekürzt. Sortiert von links (192°) nach rechts (−12°) – je BLOCK aufeinanderfolgende Plätze bilden eine Delegation (ein Keil)."""
    sitze, reihe = [], 0
    while len(sitze) < gesamt:
        r = PLENUM_R0 + reihe * ABSTAND
        winkel = _reihe(r)
        rest = gesamt - len(sitze)
        if len(winkel) > rest:            # äußerste Reihe kürzen: abwechselnd außen links und außen rechts weglassen
            winkel.sort()
            while len(winkel) > rest:
                winkel.pop(0 if (len(winkel) % 2) else -1)
        sitze += [(w, reihe, r) for w in winkel]
        reihe += 1
    sitze.sort(key=lambda t: (-round(t[0], 4), t[1]))
    return sitze


def _delegationen():
    d = []
    for name, titel, farbe, _x, art in STAATEN:
        d.append({"name": name, "titel": titel, "farbe": farbe, "art": art})
    for i in range(RESERVE_ZUSATZ):
        d.append({"name": "Reserve", "titel": "", "farbe": "", "art": "frei"})
    return d


DELEGATIONEN = _delegationen()


def _kreis(x, y, klasse, label, attrs="", r=SITZ_R, farbe=None):
    stil = f' style="--c:{farbe}"' if farbe else ""
    return f'<circle class="{klasse}" cx="{x:.1f}" cy="{y:.1f}" r="{r}"{stil} data-l="{esc(label)}"{attrs}><title>{esc(label)}</title></circle>'


def _bank(bank, anzahl, seite):
    """Sitze einer Bank auf den Bögen der Bundestag-Grafik: Reihe für Reihe von vorn, vom innersten Platz nach außen (seite −1 = links)."""
    px, py = bank["mitte"]
    out = []
    for z, ((r, x0), n) in enumerate(zip(bank["reihen"], anzahl)):
        y0 = py - math.sqrt(r * r - (x0 - px) ** 2)
        t0 = math.atan2(y0 - py, x0 - px)
        for k in range(n):
            t = t0 + seite * k * ABSTAND / r
            out.append((px + r * math.cos(t), py + r * math.sin(t), z, k))
    return out


def svg():
    teile = []
    cx, cy = MITTE
    xs, ys = [], []
    # --- Plenum
    sitze = plenum_sitze(len(DELEGATIONEN) * BLOCK)
    for i, d in enumerate(DELEGATIONEN):
        block = sitze[i * BLOCK:(i + 1) * BLOCK]
        haupt_j = min(range(len(block)), key=lambda j: (block[j][1], -block[j][0]))      # innerster Sitz = Landesherr
        kreise = []
        for j, (w, reihe, r) in enumerate(block):
            x, y = cx + r * math.cos(math.radians(w)), cy + r * math.sin(math.radians(w))
            xs.append(x); ys.append(y)
            haupt = j == haupt_j
            if d["art"] == "frei":
                label, kl = "Reservesitz für einen künftigen Teilstaat", "sz sz-frei"
            elif d["art"] == "gouvernement":
                label, kl = f'{d["name"]}: vorgehaltener Sitz ({"Gouverneur" if haupt else "Delegierter"}, unter Reichsvertretung)', "sz sz-vorgehalten"
            else:
                label, kl = f'{d["name"]}: {d["titel"] if haupt else "Delegierter"}', "sz sz-staat"
            if haupt:
                kl += " sz-haupt"
            kreise.append(_kreis(x, y, kl, label, farbe=d["farbe"] or None))
        teile.append(f'<g class="dl" data-d="{i}" data-art="{d["art"]}" tabindex="0" role="group" aria-label="{esc(d["name"])}">{"".join(kreise)}</g>')
    # --- Reichsverwaltungsbank (links, wie die Regierungsbank)
    kreise = []
    links = _bank(BANK_LINKS, [len(r) for r in VERWALTUNG], -1)
    for x, y, z, k in links:
        st = VERWALTUNG[z][k]
        xs.append(x); ys.append(y)
        kreise.append(_kreis(x, y, "sz sz-verwaltung" + (" sz-haupt" if st["schl"] == "kanzlei" else ""), f'{st["titel"]} · {st["stelle"]}'))
    teile.append(f'<g class="bank" data-bank="verwaltung">{"".join(kreise)}</g>')
    # --- Senatsbank (rechts, wie die Bundesratsbank)
    kreise = []
    rechts = _bank(BANK_RECHTS, SENAT_REIHEN, 1)
    for nr, (x, y, z, k) in enumerate(rechts, 1):
        xs.append(x); ys.append(y)
        kreise.append(_kreis(x, y, "sz sz-senat", f"Senatsbank: Kurfürst ({nr} von {KURFUERSTEN})"))
    teile.append(f'<g class="bank" data-bank="senat">{"".join(kreise)}</g>')
    # --- Mitte: Präsidententisch, Thron (Platz des Direktors), Präsident, Rednerpult
    tx, ty, tw, th = TISCH
    teile.append(f'<rect class="pult" x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="2"><title>Präsidiumstisch</title></rect>')
    teile.append(f'<g class="bank" data-bank="thron">{_kreis(THRON[0], THRON[1], "sz sz-thron", "Thron: Seine Majestät der Kaiser", r=SITZ_R + 2.5)}</g>')
    teile.append(f'<g class="bank" data-bank="praesidium">{_kreis(PRAESIDENT[0], PRAESIDENT[1], "sz sz-praesidium", "Präsidium: Der Präsident des Reichstags", r=SITZ_R + 1)}</g>')
    px_, py_, pw, ph = PULT
    teile.append(f'<rect class="pult" x="{px_}" y="{py_}" width="{pw}" height="{ph}" rx="2"><title>Rednerpult</title></rect>')
    # --- Beschriftungen an den äußeren Enden der Bänke
    lx, ly = min((p[0], p[1]) for p in links)
    teile.append(f'<text class="tl" x="{lx - 16:.0f}" y="{ly + 3:.0f}" text-anchor="end">Reichsverwaltungsbank</text>')
    rx_, ry_ = max((p[0], p[1]) for p in rechts)
    teile.append(f'<text class="tl" x="{rx_ + 16:.0f}" y="{ry_ + 3:.0f}">Senatsbank</text>')
    teile.append(f'<text class="tl" x="{THRON[0]:.0f}" y="{THRON[1] - 18:.0f}" text-anchor="middle">Thron</text>')
    x0, x1 = min(xs) - 150, max(xs) + 90
    y0, y1 = min(ys + [THRON[1] - 30]) - 8, max(ys) + 16
    return (f'<svg class="sz-plan" viewBox="{x0:.0f} {y0:.0f} {x1 - x0:.0f} {y1 - y0:.0f}" role="group" aria-label="Sitzordnung des Reichstags" xmlns="http://www.w3.org/2000/svg">'
            + "".join(teile) + '</svg>')


def zahlen():
    plenum = len(DELEGATIONEN) * BLOCK
    verwaltung = sum(len(z) for z in VERWALTUNG)
    return {"plenum": plenum, "verwaltung": verwaltung, "senat": KURFUERSTEN, "thron": 1, "praesidium": 1,
            "gesamt": plenum + verwaltung + KURFUERSTEN + 2,
            "delegationen": sum(1 for d in DELEGATIONEN if d["art"] == "landesherr"),
            "vorgehalten": sum(1 for d in DELEGATIONEN if d["art"] == "gouvernement"),
            "frei": sum(1 for d in DELEGATIONEN if d["art"] == "frei")}
