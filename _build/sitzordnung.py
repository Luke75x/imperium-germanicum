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
REIHEN = [170, 198, 226, 254, 282, 310]      # Radien der Sitzreihen im Plenum
MITTE = (500, 262)             # Mittelpunkt des Halbkreises
SITZ_R = 11

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

# Reichsverwaltungsbank: vorn der Kronkanzler und die Leiter der Behörden für Sicherheit und Ordnung sowie Verwaltung, hinten die übrigen Stellen
VORN = ["kanzlei", "polizei", "zoll", "katastrophenschutz", "krs", "inquisition", "schatzamt", "generalkonsulat", "heroldsamt"]
HINTEN = ["crownestates", "inneres", "forschung", "gesundheit", "verkehr", "arbeit", "einwanderung", "zentralbank", "reichskasse"]


def _behoerde(schl):
    if schl == "kanzlei":
        k = RB.KANZLEI
        return {"titel": "Kronkanzler", "stelle": k["kurz"], "schl": schl}
    b = next(x for x in RB.BEHOERDEN if x["schl"] == schl)
    return {"titel": b["leitung"], "stelle": b["name"], "schl": schl}


VERWALTUNG = [[_behoerde(s) for s in VORN], [_behoerde(s) for s in HINTEN]]
KURFUERSTEN = 8


def _block_sitze(i, n_bloecke):
    """Die BLOCK Plätze der Delegation i: ein Strahl (Keil) über alle Reihen, innen beginnend; (Reihe, Winkel, Radius)."""
    w = math.pi * (i + 0.5) / n_bloecke           # Winkel 0 = links, π = rechts
    return [(reihe, w, r) for reihe, r in enumerate(REIHEN)]


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


def svg():
    cx, cy = MITTE
    teile = []
    # --- Plenum
    for i, d in enumerate(DELEGATIONEN):
        block = [(w, reihe, r) for reihe, w, r in _block_sitze(i, len(DELEGATIONEN))]
        vorn = 0                                    # innerster Sitz = Landesherr
        kreise = []
        for j, (w, reihe, r) in enumerate(block):
            x, y = cx - r * math.cos(w), cy + r * math.sin(w)
            if d["art"] == "frei":
                label, kl = "Reservesitz für einen künftigen Teilstaat", "sz sz-frei"
            elif d["art"] == "gouvernement":
                label, kl = f'{d["name"]}: vorgehaltener Sitz ({"Gouverneur" if j == vorn else "Delegierter"}, unter Reichsvertretung)', "sz sz-vorgehalten"
            else:
                label, kl = f'{d["name"]}: {d["titel"] if j == vorn else "Delegierter"}', "sz sz-staat"
            if j == vorn:
                kl += " sz-haupt"
            kreise.append(_kreis(x, y, kl, label, farbe=d["farbe"] or None))
        teile.append(f'<g class="dl" data-d="{i}" data-art="{d["art"]}" tabindex="0" role="group" aria-label="{esc(d["name"])}">{"".join(kreise)}</g>')
    # --- Bühne: Thron und Präsidium
    teile.append(f'<g class="bank" data-bank="thron">{_kreis(cx, 70, "sz sz-thron", "Thron: Seine Majestät der Kaiser", r=22)}</g>')
    teile.append(f'<g class="bank" data-bank="praesidium">{_kreis(cx, 128, "sz sz-praesidium", "Präsidium: Der Präsident des Reichstags", r=SITZ_R + 1)}</g>')
    teile.append(f'<rect class="pult" x="{cx - 36}" y="150" width="72" height="14" rx="3"><title>Rednerpult</title></rect>')
    # --- Reichsverwaltungsbank (links), zwei Reihen zu je 9
    kreise = []
    for zeile, stellen in enumerate(VERWALTUNG):
        for j, s in enumerate(stellen):
            x, y = 70 + j * 33, 130 + zeile * 34
            kreise.append(_kreis(x, y, "sz sz-verwaltung" + (" sz-haupt" if s["schl"] == "kanzlei" else ""), f'{s["titel"]} · {s["stelle"]}'))
    teile.append(f'<g class="bank" data-bank="verwaltung">{"".join(kreise)}</g>')
    # --- Senatsbank (rechts), zwei Reihen zu je 4
    kreise = []
    for k in range(KURFUERSTEN):
        x, y = 740 + (k % 4) * 38, 140 + (k // 4) * 36
        kreise.append(_kreis(x, y, "sz sz-senat", f"Senatsbank: Kurfürst ({k + 1} von {KURFUERSTEN})"))
    teile.append(f'<g class="bank" data-bank="senat">{"".join(kreise)}</g>')
    # --- Beschriftungen
    teile.append('<text class="tl" x="70" y="104">Reichsverwaltungsbank</text>')
    teile.append('<text class="tl tl-r" x="880" y="104" text-anchor="end">Senatsbank</text>')
    teile.append(f'<text class="tl" x="{cx}" y="24" text-anchor="middle">Thron</text>')
    teile.append(f'<text class="tl" x="{cx}" y="190" text-anchor="middle">Präsidium &amp; Rednerpult</text>')
    teile.append(f'<text class="tl" x="{cx}" y="{cy + REIHEN[-1] + 44}" text-anchor="middle">Plenum der Teilstaaten</text>')
    return (f'<svg class="sz-plan" viewBox="0 0 1000 {cy + REIHEN[-1] + 60}" role="group" aria-label="Sitzordnung des Reichstags" xmlns="http://www.w3.org/2000/svg">'
            + "".join(teile) + '</svg>')


def zahlen():
    plenum = len(DELEGATIONEN) * BLOCK
    verwaltung = sum(len(z) for z in VERWALTUNG)
    return {"plenum": plenum, "verwaltung": verwaltung, "senat": KURFUERSTEN, "thron": 1, "praesidium": 1,
            "gesamt": plenum + verwaltung + KURFUERSTEN + 2,
            "delegationen": sum(1 for d in DELEGATIONEN if d["art"] == "landesherr"),
            "vorgehalten": sum(1 for d in DELEGATIONEN if d["art"] == "gouvernement"),
            "frei": sum(1 for d in DELEGATIONEN if d["art"] == "frei")}
