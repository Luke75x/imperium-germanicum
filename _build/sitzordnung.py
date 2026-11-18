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
ABSTAND = 20                   # Sitzabstand (wie im Plenarsaal: überall gleich dicht)
SITZ_R = 8
MITTE = (0, 0)                 # Rednerpult = Mittelpunkt des Plenums; das Plenum liegt als Halbrund darunter
PLENUM_R0 = 50                 # Radius der innersten Reihe; Reihen nach außen je ABSTAND, Sitze je Reihe ∝ Radius (gleich dicht)
PLENUM_REIHEN = 7
BANK_K = 400                   # Bänke: flache Bögen um einen Punkt weit unter dem Rednerpult (zum Plenum hin gewölbt, wie im Bundestag)
BANK_INNEN = 26                # Abstand der Bankreihen von der Mittelachse (Platz für Thron und Präsidium)

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
]
SENAT_REIHEN = [2, 3, 3]       # Senatsbank, von vorn nach hinten


def _behoerde(schl):
    if schl == "kanzlei":
        k = RB.KANZLEI
        return {"titel": "Kronkanzler", "stelle": k["kurz"], "schl": schl}
    b = next(x for x in RB.BEHOERDEN if x["schl"] == schl)
    return {"titel": b["leitung"], "stelle": b["name"], "schl": schl}


VERWALTUNG = [[_behoerde(x) for x in reihe] for reihe in VERWALTUNG_REIHEN]
KURFUERSTEN = sum(SENAT_REIHEN)


def plenum_sitze(gesamt):
    """Alle Plenumsplätze wie im Bundestag: Reihen mit gleichem Abstand, Sitze je Reihe ∝ Radius, jede Reihe von ganz links (180°)
    bis ganz rechts (360°). Nach dem Winkel sortiert; je BLOCK aufeinanderfolgende Plätze bilden einen Keil (eine Delegation)."""
    radien = [PLENUM_R0 + k * ABSTAND for k in range(PLENUM_REIHEN)]
    zahlen = [round(gesamt * r / sum(radien)) for r in radien]
    zahlen[-1] += gesamt - sum(zahlen)
    sitze = []
    for reihe, (r, n) in enumerate(zip(radien, zahlen)):
        for k in range(n):
            w = math.pi * k / (n - 1)                       # 0 = links, π = rechts (unten herum)
            sitze.append((w, reihe, r))
    sitze.sort(key=lambda t: (round(t[0], 6), t[1]))
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


def _bank(reihen_anzahl, seite):
    """Sitze einer Bank (links = -1, rechts = +1): Reihen von vorn nach hinten, je Reihe von der Mitte nach außen;
    flache Bögen um (0, BANK_K), die vorderste Reihe knapp über dem Rednerpult."""
    out = []
    for z, n in enumerate(reihen_anzahl):
        r = BANK_K + 46 + z * ABSTAND
        for k in range(n):
            x = seite * (BANK_INNEN + k * ABSTAND)
            out.append((x, BANK_K - math.sqrt(r * r - x * x), z, k))
    return out


def svg():
    teile = []
    # --- Plenum
    n = len(DELEGATIONEN)
    sitze = plenum_sitze(n * BLOCK)
    for i, d in enumerate(DELEGATIONEN):
        block = sitze[i * BLOCK:(i + 1) * BLOCK]
        haupt_j = min(range(BLOCK), key=lambda j: (block[j][1], block[j][0]))      # innerster Sitz = Landesherr
        kreise = []
        for j, (w, reihe, r) in enumerate(block):
            x, y = -r * math.cos(w), r * math.sin(w)
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
    # --- Reichsverwaltungsbank (links)
    kreise = []
    for x, y, z, k in _bank([len(r) for r in VERWALTUNG], -1):
        st = VERWALTUNG[z][k]
        kreise.append(_kreis(x, y, "sz sz-verwaltung" + (" sz-haupt" if st["schl"] == "kanzlei" else ""), f'{st["titel"]} · {st["stelle"]}'))
    teile.append(f'<g class="bank" data-bank="verwaltung">{"".join(kreise)}</g>')
    # --- Senatsbank (rechts)
    kreise = []
    for nr, (x, y, z, k) in enumerate(_bank(SENAT_REIHEN, 1), 1):
        kreise.append(_kreis(x, y, "sz sz-senat", f"Senatsbank: Kurfürst ({nr} von {KURFUERSTEN})"))
    teile.append(f'<g class="bank" data-bank="senat">{"".join(kreise)}</g>')
    # --- Mittelachse: Thron (wo im Bundestag der Direktor sitzt), Präsident am Präsidiumstisch, Rednerpult
    teile.append(f'<g class="bank" data-bank="thron">{_kreis(0, -128, "sz sz-thron", "Thron: Seine Majestät der Kaiser", r=11)}</g>')
    teile.append('<rect class="pult" x="-15" y="-106" width="30" height="8" rx="2"><title>Präsidiumstisch</title></rect>')
    teile.append(f'<g class="bank" data-bank="praesidium">{_kreis(0, -84, "sz sz-praesidium", "Präsidium: Der Präsident des Reichstags", r=SITZ_R + 1)}</g>')
    teile.append('<rect class="pult" x="-9" y="-30" width="18" height="12" rx="2"><title>Rednerpult</title></rect>')
    # --- Beschriftungen
    teile.append('<text class="tl" x="-36" y="-106" text-anchor="end">Reichsverwaltungsbank</text>')
    teile.append('<text class="tl" x="36" y="-106">Senatsbank</text>')
    teile.append('<text class="tl" x="0" y="-146" text-anchor="middle">Thron</text>')
    aussen = PLENUM_R0 + (PLENUM_REIHEN - 1) * ABSTAND + SITZ_R
    return (f'<svg class="sz-plan" viewBox="{-aussen - 12} -160 {2 * aussen + 24} {aussen + 160 + 12}" role="group" aria-label="Sitzordnung des Reichstags" xmlns="http://www.w3.org/2000/svg">'
            + "".join(teile) + '</svg>')


def zahlen():
    plenum = len(DELEGATIONEN) * BLOCK
    verwaltung = sum(len(z) for z in VERWALTUNG)
    return {"plenum": plenum, "verwaltung": verwaltung, "senat": KURFUERSTEN, "thron": 1, "praesidium": 1,
            "gesamt": plenum + verwaltung + KURFUERSTEN + 2,
            "delegationen": sum(1 for d in DELEGATIONEN if d["art"] == "landesherr"),
            "vorgehalten": sum(1 for d in DELEGATIONEN if d["art"] == "gouvernement"),
            "frei": sum(1 for d in DELEGATIONEN if d["art"] == "frei")}
