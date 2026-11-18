"""Sitzordnung des Reichstagsgebäudes (Plenarsaal) – Daten und SVG für /informationen/der-reichstag/sitzordnung/.

Aufbau (nach dem Vorbild der Sitzverteilung des Bundestags, angepasst):
- Thron: der Präsidiumstisch des Bundestags ist der Thron des Monarchen (1 Sitz). Davor das Präsidium (der Präsident des Reichstags, 1 Sitz).
- Reichsverwaltungsbank (links; im Bundestag die Regierungsbank): der Kronkanzler und die Leiter der Reichsbehörden (18 Sitze, keine zusätzlichen Ämter).
- Senatsbank (rechts; im Bundestag die Bundesratsbank, ohne deren vorderste Reihe): vorn je ein Sitz für die 9 Kurfürsten,
  dahinter die Delegationsplätze. Kronkanzler, Behördenleiter, Kurfürsten, Thron und Präsident sind Links auf ihre Seiten.
- Plenum (Halbkreis): je Landesherr eine Delegation von 6 Sitzen (Landesherr + 5), geordnet von West nach Ost (nach der Hauptstadt).
  Für die Teilstaaten unter Reichsvertretung (Gouvernement Baden, Generalgouvernement Venedig) sind Delegationen vorgehalten,
  dazu ein freier Reserveblock für künftige Teilstaaten. So bleibt die Raumform stabil, wenn ein Gebiet einen Landesherrn erhält.

Aufruf: sitzordnung.svg() liefert das SVG, sitzordnung.DELEGATIONEN die Daten für die Legende.
"""
import html
import json
import math
import os

import reichsbehoerden as RB

esc = html.escape
BLOCK = 6                      # Sitze je Delegation: Landesherr und 5 Delegierte

# ---- Geometrie: die echten Sitzkoordinaten der Sitzplan-Grafik des Bundestags (bundestag.de/parlament/plenum/sitzverteilung,
#   Koordinatensystem 822,87 x 608,04), abgelegt in sitzordnung_geometrie.json:
#   plenum = 630 Plätze (fünf Sektoren, 16 Reihen um das Rednerpult), regierung = 38 Plätze der Regierungsbank (links oben, der
#   große Platz ist der des Kanzlers), bundesrat = 36 Plätze der Bundesratsbank (rechts oben), vorstand = Präsident (Mitte) und
#   die beiden Plätze daneben. Der Präsidiumstisch ist der Thron; der Platz des Direktors entfällt.
GEO = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sitzordnung_geometrie.json"), encoding="utf-8"))
SITZ_R = 6
MITTE = (411.0, 196.0)         # Rednerpult-Seite: Mittelpunkt der Plenumsreihen
REIHE0, REIHE_SCHRITT = 87.5, 19.55
THRON = (403.04, 27.44, 16.0, 30.0)  # der Präsidiumstisch des Bundestags ist der Thron; den Platz des Direktors gibt es nicht
PULT = (404.59, 116.12, 14.0, 14.0)

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
RESERVE_ZUSATZ = 0             # eigene Reserveblöcke braucht es nicht: die übrigen Plätze des Saals bleiben frei

# Reichsverwaltungsbank (im Bundestag die Regierungsbank), Reihen von vorn (zum Plenum) nach hinten, jeweils von der Mitte nach außen:
#   vorn der Kronkanzler mit den Generaldirektoren der Behörden für Sicherheit und Ordnung, dahinter die übrigen Behörden, hinten die Reichsämter.
VERWALTUNG_REIHEN = [
    ["kanzlei", "krs", "polizei", "zoll", "katastrophenschutz"],
    ["inquisition", "schatzamt", "generalkonsulat", "heroldsamt", "crownestates", "inneres"],
    ["zentralbank", "reichskasse", "forschung", "gesundheit", "verkehr", "arbeit", "einwanderung"],
]                              # 5 + 6 + 7 = 18, wie im Bundestag die vorderste Reihe am kürzesten
# Senatsbank: die vorderste Reihe der Bundesratsbank (7 Plätze) entfällt; die zweite (9 Plätze) wird zur ersten Reihe mit je einem
#   eigenen Sitz für jeden der 9 Kurfürsten, von innen nach außen. Die Reihen dahinter sind die Plätze ihrer Delegationen.
#   (Name, Bezeichnung, Seite) – Seite relativ zur Website-Wurzel; ohne eigene Seite verweist der Sitz auf den Senat.
KURFUERSTEN_SITZE = [
    ("Alexander IX.", "König der Westerwälder Union, amtierender Kaiser", "der-souveraen/"),
    ("Karl V.", "Erzherzog von der Pfalz, Hand des Kaisers", "informationen/hand-des-kaisers/"),
    ("Ernst August VI.", "König von Hannover und Braunschweig-Lüneburg", "informationen/der-senat/#kf-hannover"),
] + [("", "", "informationen/der-senat/")] * 6
SENAT_WEG = 1                  # so viele vordere Reihen der Bundesratsbank werden nicht gezeichnet
SEITE_KAISER = "der-souveraen/"
SEITE_PRAESIDENT = "informationen/der-reichstag/"


def _behoerde(schl):
    if schl == "kanzlei":
        k = RB.KANZLEI
        return {"titel": "Kronkanzler", "stelle": k["kurz"], "schl": schl, "seite": RB.seite(k)}
    b = next(x for x in RB.BEHOERDEN if x["schl"] == schl)
    return {"titel": b["leitung"], "stelle": b["name"], "schl": schl, "seite": RB.seite(b)}


VERWALTUNG = [[_behoerde(x) for x in reihe] for reihe in VERWALTUNG_REIHEN]
KURFUERSTEN = len(KURFUERSTEN_SITZE)


def _reihe_von(x, y):
    return round((math.hypot(x - MITTE[0], y - MITTE[1]) - REIHE0) / REIHE_SCHRITT)


def plenum_belegung(anzahl):
    """Teilt die 630 Plätze: die `anzahl` vordersten (innerste Reihen, in der letzten nötigen Reihe die mittleren) gehen an die
    Delegationen, sortiert von links (Westen) nach rechts (Osten); der Rest bleibt frei. Liefert (delegationsplätze, freie)."""
    sitze = [(x, y, _reihe_von(x, y), math.degrees(math.atan2(y - MITTE[1], x - MITTE[0]))) for x, y in GEO["plenum"]]
    for i, (x, y, r, w) in enumerate(sitze):
        if w < -90:
            sitze[i] = (x, y, r, w + 360)        # links über die Waagerechte hinaus (bis 192°)
    sitze.sort(key=lambda t: (t[2], abs(t[3] - 90)))
    vorn, frei = sitze[:anzahl], sitze[anzahl:]
    # Keile wie die Fraktionen im Bundestag: je Reihe die Lage des Platzes von links nach rechts auf 0…1 umrechnen und danach
    # aufteilen – so bekommt jede Delegation in jeder Reihe etwa gleich viel Breite, die Blöcke laufen von vorn nach hinten.
    reihen = {}
    for t in vorn:
        reihen.setdefault(t[2], []).append(t)
    lage = {}
    for r, v in reihen.items():
        v.sort(key=lambda t: -t[3])
        for k, t in enumerate(v):
            lage[t] = (k + 0.5) / len(v)
    vorn.sort(key=lambda t: (lage[t], t[2]))
    return vorn, frei


def _delegationen():
    d = []
    for name, titel, farbe, _x, art in STAATEN:
        d.append({"name": name, "titel": titel, "farbe": farbe, "art": art})
    for i in range(RESERVE_ZUSATZ):
        d.append({"name": "Reserve", "titel": "", "farbe": "", "art": "frei"})
    return d


DELEGATIONEN = _delegationen()


def _kreis(x, y, klasse, label, attrs="", r=SITZ_R, farbe=None, link=None):
    """Ein Sitz; mit `link` (fertige URL) ist er anklickbar und führt auf die Seite der Person bzw. des Amts."""
    stil = f' style="--c:{farbe}"' if farbe else ""
    k = f'<circle class="{klasse}" cx="{x:.1f}" cy="{y:.1f}" r="{r}"{stil} data-l="{esc(label)}"{attrs}><title>{esc(label)}</title></circle>'
    return f'<a class="sz-link" href="{esc(link)}" aria-label="{esc(label)}">{k}</a>' if link else k


BOGEN = {"regierung": ((396.0, 540.0), 455.0), "bundesrat": ((396.0, 670.0), 588.0)}   # Bogenmittelpunkt, Radius der vordersten Reihe


def _bankreihen(punkte, bank, innen_rechts):
    """Reihen einer Bank, von vorn (zum Plenum) nach hinten; je Reihe vom innersten Platz (zur Saalmitte) nach außen.
    Die Bänke der Bundestag-Grafik sind Bögen um einen Punkt weit unter dem Saal, Reihenabstand 26,5."""
    (mx, my), r0 = BOGEN[bank]
    reihen = {}
    for p in punkte:
        reihen.setdefault(round((math.hypot(p[0] - mx, p[1] - my) - r0) / 26.5), []).append(p)
    return [sorted(v, key=lambda p: -p[0] if innen_rechts else p[0]) for _, v in sorted(reihen.items())]


def svg(u=lambda p: "/" + p):
    """u: wandelt einen Seitenpfad (relativ zur Website-Wurzel) in den Link der erzeugten Seite um (site.u)."""
    teile = []
    vorn, frei = plenum_belegung(len(DELEGATIONEN) * BLOCK)
    # --- Plenum: freie Plätze zuerst (liegen unter den Delegationen)
    teile.append('<g class="bank" data-bank="frei" aria-label="Freie Plätze">' + "".join(
        _kreis(x, y, "sz sz-frei", "Freier Platz: für Gäste, Beobachter und künftige Teilstaaten") for x, y, _r, _w in frei) + "</g>")
    for i, d in enumerate(DELEGATIONEN):
        block = vorn[i * BLOCK:(i + 1) * BLOCK]
        haupt_j = min(range(len(block)), key=lambda j: (block[j][2], -block[j][3]))      # vorderster Sitz = Landesherr
        kreise = []
        for j, (x, y, _r, _w) in enumerate(block):
            haupt = j == haupt_j
            if d["art"] == "gouvernement":
                label, kl = f'{d["name"]}: vorgehaltener Sitz ({"Gouverneur" if haupt else "Delegierter"}, unter Reichsvertretung)', "sz sz-vorgehalten"
            else:
                label, kl = f'{d["name"]}: {d["titel"] if haupt else "Delegierter"}', "sz sz-staat"
            if haupt:
                kl += " sz-haupt"
            kreise.append(_kreis(x, y, kl, label, farbe=d["farbe"] or None))
        teile.append(f'<g class="dl" data-d="{i}" data-art="{d["art"]}" tabindex="0" role="group" aria-label="{esc(d["name"])}">{"".join(kreise)}</g>')
    # --- Reichsverwaltungsbank (links oben, die Regierungsbank): Reihen von vorn, je Reihe von innen (rechts) nach außen
    reihen = _bankreihen([(x, y) for x, y, _r in GEO["regierung"]], "regierung", True)
    kreise = []
    for z, reihe in enumerate(reihen):
        for k, (x, y) in enumerate(reihe):
            if z < len(VERWALTUNG) and k < len(VERWALTUNG[z]):
                st = VERWALTUNG[z][k]
                kanzler = st["schl"] == "kanzlei"
                kreise.append(_kreis(x, y, "sz sz-verwaltung" + (" sz-haupt" if kanzler else ""), f'{st["titel"]} · {st["stelle"]}',
                                     r=8 if kanzler else SITZ_R, link=u(st["seite"])))
            else:
                kreise.append(_kreis(x, y, "sz sz-frei", "Reichsverwaltungsbank: freier Platz"))
    teile.append(f'<g class="bank" data-bank="verwaltung" aria-label="Reichsverwaltungsbank">{"".join(kreise)}</g>')
    # --- Senatsbank (rechts oben, die Bundesratsbank): vorderste Reihe entfällt, dann die Kurfürsten, dahinter ihre Delegationen
    reihen = _bankreihen([tuple(p) for p in GEO["bundesrat"]], "bundesrat", False)[SENAT_WEG:]
    kreise = []
    for k, (x, y) in enumerate(reihen[0]):
        name, bez, seite = KURFUERSTEN_SITZE[k]
        label = f"Senatsbank · Kurfürst {k + 1} von {KURFUERSTEN}: " + (f"{name}, {bez}" if name else "derzeit nicht vergeben")
        kreise.append(_kreis(x, y, "sz sz-senat" + ("" if name else " sz-offen"), label, link=u(seite)))
    for reihe in reihen[1:]:
        kreise += [_kreis(x, y, "sz sz-senat-del", "Senatsbank: Delegationsplatz der Kurfürsten") for x, y in reihe]
    teile.append(f'<g class="bank" data-bank="senat" aria-label="Senatsbank">{"".join(kreise)}</g>')
    # --- Mitte: Thron (der Präsidiumstisch), davor der Präsident mit den Plätzen daneben, Rednerpult
    tx, ty, tw, th = THRON
    lt = "Thron: Seine Majestät der Kaiser"
    teile.append(f'<g class="bank" data-bank="thron" aria-label="Thron"><a class="sz-link" href="{esc(u(SEITE_KAISER))}" aria-label="{lt}"><rect class="sz sz-thron" x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="3" data-l="{lt}"><title>{lt}</title></rect></a></g>')
    v = sorted(GEO["vorstand"], key=lambda p: -p[2])
    px, py, pr = v[0]
    teile.append(f'<g class="bank" data-bank="praesidium" aria-label="Präsidium">{_kreis(px, py, "sz sz-praesidium", "Präsidium: Der Präsident des Reichstags", r=pr, link=u(SEITE_PRAESIDENT))}'
                 + "".join(_kreis(x, y, "sz sz-frei", "Präsidium: freier Platz") for x, y, _r in v[1:]) + "</g>")
    tx, ty, tw, th = PULT
    teile.append(f'<rect class="pult" x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="2"><title>Rednerpult</title></rect>')
    return ('<svg class="sz-plan" viewBox="0 -14 822.87 622" role="group" aria-label="Sitzordnung des Reichstags" xmlns="http://www.w3.org/2000/svg">'
            + "".join(teile) + '</svg>')


def zahlen():
    plenum = len(GEO["plenum"])
    verwaltung = sum(len(z) for z in VERWALTUNG)          # besetzte Plätze; die Bank hat 38 Plätze
    senat_reihen = _bankreihen([tuple(p) for p in GEO["bundesrat"]], "bundesrat", False)[SENAT_WEG:]
    senat_del = sum(len(r) for r in senat_reihen[1:])
    belegt = len(DELEGATIONEN) * BLOCK
    saal = plenum + len(GEO["regierung"]) + sum(len(r) for r in senat_reihen) + 1 + len(GEO["vorstand"])
    besetzt = belegt + verwaltung + KURFUERSTEN + senat_del + 1 + 1
    return {"plenum": plenum, "verwaltung": verwaltung, "senat": KURFUERSTEN, "senat_delegation": senat_del, "thron": 1, "praesidium": 1,
            "delegationen": sum(1 for d in DELEGATIONEN if d["art"] == "landesherr"),
            "vorgehalten": sum(1 for d in DELEGATIONEN if d["art"] == "gouvernement"),
            "belegt": belegt, "frei": plenum - belegt, "saal": saal, "besetzt": besetzt, "frei_gesamt": saal - besetzt}
