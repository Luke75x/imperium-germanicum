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
REIHEN = [175, 193, 211]      # Radien der Sitzreihen im Plenum (3 Reihen; je Delegation 2 Spalten x 3 Reihen)
SPALTEN = BLOCK // 3
FAECHER = (185.0, 355.0)      # Winkelbereich des Plenums (Grad, 0 = rechts, gegen den Uhrzeigersinn; 270 = unten)
MITTE = (500, 170)             # Mittelpunkt der Rundung (Rednerpult)
SITZ_R = 6

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
    """Die BLOCK Plätze der Delegation i: SPALTEN Spalten x 3 Reihen als Keil; (Reihe, Winkel in Grad, Radius), innen links beginnend."""
    w0, w1 = FAECHER
    spalten = n_bloecke * SPALTEN
    out = []
    for c in range(SPALTEN):
        w = w0 + (i * SPALTEN + c + 0.5) * (w1 - w0) / spalten
        for reihe, r in enumerate(REIHEN):
            out.append((reihe, w, r))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


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


def _pol(r, grad):
    cx, cy = MITTE
    return cx + r * math.cos(math.radians(grad)), cy - r * math.sin(math.radians(grad))


def _bogen(anzahl, r, mitte_grad, abstand_px=17.5):
    """Winkel (Grad) von anzahl gleichmäßig verteilten Sitzen auf dem Radius r, um mitte_grad zentriert, Abstand abstand_px."""
    schritt = math.degrees(abstand_px / r)
    return [mitte_grad + (k - (anzahl - 1) / 2) * schritt for k in range(anzahl)]


def svg():
    cx, cy = MITTE
    teile = []
    # --- Plenum: Keile (2 Spalten x 3 Reihen) je Delegation
    for i, d in enumerate(DELEGATIONEN):
        kreise = []
        for j, (reihe, w, r) in enumerate(_block_sitze(i, len(DELEGATIONEN))):
            x, y = _pol(r, w)
            haupt = j == 0
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
    # --- Mitte oben: Thron, Präsidium (Schreibtisch + 1 Sitz), Rednerpult
    teile.append(f'<g class="bank" data-bank="thron">{_kreis(cx, cy - 128, "sz sz-thron", "Thron: Seine Majestät der Kaiser", r=14)}</g>')
    teile.append(f'<rect class="pult" x="{cx - 28}" y="{cy - 96}" width="56" height="11" rx="3"><title>Präsidiumstisch</title></rect>')
    teile.append(f'<g class="bank" data-bank="praesidium">{_kreis(cx, cy - 72, "sz sz-praesidium", "Präsidium: Der Präsident des Reichstags", r=SITZ_R + 1.5)}</g>')
    teile.append(f'<rect class="pult" x="{cx - 10}" y="{cy - 34}" width="20" height="14" rx="3"><title>Rednerpult</title></rect>')
    # --- Reichsverwaltungsbank (links oben): zwei gekrümmte Reihen zu je 9, vorn der Kronkanzler außen am Gang
    kreise = []
    for zeile, stellen in enumerate(VERWALTUNG):
        r = 112 + zeile * 20
        for stelle, grad in zip(stellen, _bogen(len(stellen), r, 140)):
            x, y = _pol(r, grad)
            kreise.append(_kreis(x, y, "sz sz-verwaltung" + (" sz-haupt" if stelle["schl"] == "kanzlei" else ""), f'{stelle["titel"]} · {stelle["stelle"]}'))
    teile.append(f'<g class="bank" data-bank="verwaltung">{"".join(kreise)}</g>')
    # --- Senatsbank (rechts oben): zwei gekrümmte Reihen zu je 4
    kreise = []
    for zeile in range(2):
        r = 112 + zeile * 20
        for k, grad in enumerate(_bogen(KURFUERSTEN // 2, r, 40)):
            x, y = _pol(r, grad)
            kreise.append(_kreis(x, y, "sz sz-senat", f"Senatsbank: Kurfürst ({zeile * (KURFUERSTEN // 2) + k + 1} von {KURFUERSTEN})"))
    teile.append(f'<g class="bank" data-bank="senat">{"".join(kreise)}</g>')
    # --- Beschriftungen
    teile.append(f'<text class="tl" x="{cx - 118}" y="{cy - 142}" text-anchor="end">Reichsverwaltungsbank</text>')
    teile.append(f'<text class="tl" x="{cx + 118}" y="{cy - 142}">Senatsbank</text>')
    teile.append(f'<text class="tl" x="{cx}" y="{cy - 154}" text-anchor="middle">Thron</text>')
    teile.append(f'<text class="tl" x="{cx}" y="{cy + REIHEN[-1] + 30}" text-anchor="middle">Plenum der Teilstaaten</text>')
    return (f'<svg class="sz-plan" viewBox="240 0 520 {cy + REIHEN[-1] + 44}" role="group" aria-label="Sitzordnung des Reichstags" xmlns="http://www.w3.org/2000/svg">'
            + "".join(teile) + '</svg>')


def zahlen():
    plenum = len(DELEGATIONEN) * BLOCK
    verwaltung = sum(len(z) for z in VERWALTUNG)
    return {"plenum": plenum, "verwaltung": verwaltung, "senat": KURFUERSTEN, "thron": 1, "praesidium": 1,
            "gesamt": plenum + verwaltung + KURFUERSTEN + 2,
            "delegationen": sum(1 for d in DELEGATIONEN if d["art"] == "landesherr"),
            "vorgehalten": sum(1 for d in DELEGATIONEN if d["art"] == "gouvernement"),
            "frei": sum(1 for d in DELEGATIONEN if d["art"] == "frei")}
