"""Druckvorlagen zum Ausschneiden und Laminieren für ausgestellte Pässe (Passregister, meldewesen.py).

…/intern/meldewesen/paesse/<id>/druck?bild=discord|leer liefert ein PDF in Originalgröße:
- Reisepass, Dienstpass, Vorläufiger Reisepass, Fremdenpass: Passheft im ICAO-Format 125 × 88 mm, Umschlag im britischen Stil
  (Reisepass dunkelblau, Dienstpass dunkelgrün, Fremdenpass grau; goldgeprägtes Kaiserwappen). Bogen 1 (A4 quer): Umschlag außen und
  innen (Ersuchen Seiner Majestät + Personaldatenseite mit MRZ), Bogen 2: Sichtvermerkseiten als Innenblatt.
- Personalausweis: Karte im Scheckkartenformat ID-1 (85,6 × 54 mm), Vorder- und Rückseite nebeneinander zum Falzen (A4 hoch).
Lichtbild: Discord-Profilbild des Inhabers oder ein leeres Feld zum Einkleben. Nur gültige Pässe; jeder Druck wird im Pass-Verlauf vermerkt.
Wappenbilder in pass_bilder/ (erzeugt von werkzeuge/pass_wappen.py aus dem Kaiserwappen der Website).
Jede Vorlage trägt in Kleinstschrift den Vermerk „Rollenspieldokument – kein amtliches Ausweisdokument“.
"""
import base64
import math
import os
import re
import time
import unicodedata
from datetime import date, datetime

from aiohttp import web

import amt
import meldewesen
import qr

esc = amt.esc
PFAD = meldewesen.PFAD
HIER = os.path.dirname(os.path.abspath(__file__))
STAAT = "IGM"   # Staatencode in der MRZ (frei gewählt, kein ISO-Code)
VERMERK = "Rollenspieldokument des Imperium Germanicum – kein amtliches Ausweisdokument"

# Art -> (Umschlagfarbe, Seitentönung, Linienfarbe, MRZ-Typ, Titel auf dem Umschlag, englischer Titel)
HEFT = {"reisepass": ("#1b2645", "#f4ebf2", "#b49ac2", "P<", "Reisepass", "Passport"),
        "vorlaeufig": ("#1b2645", "#f4ebf2", "#b49ac2", "PV", "Vorläufiger Reisepass", "Emergency Passport"),
        "dienstpass": ("#1d3a2d", "#ebf2ea", "#93b59d", "PS", "Dienstpass", "Service Passport"),
        "fremdenpass": ("#3a3f47", "#eceef1", "#a3abb8", "PF", "Fremdenpass", "Alien's Passport")}
GOLD = "#d8b866"


def _b64(name):
    with open(os.path.join(HIER, "pass_bilder", name), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


_BILDER = {}


def bild(name):
    if name not in _BILDER:
        _BILDER[name] = _b64(name)
    return _BILDER[name]


# ---------------------------------------------------------------- maschinenlesbare Zone (ICAO 9303)

def _mrz(text):
    text = unicodedata.normalize("NFKD", text.upper().replace("Ä", "AE").replace("Ö", "OE").replace("Ü", "UE").replace("ß", "SS"))
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"<+", "<", re.sub(r"[^A-Z0-9]", "<", text)).strip("<")


def pruefziffer(s):
    w = (7, 3, 1)
    def wert(c):
        return int(c) if c.isdigit() else (ord(c) - 55 if c.isalpha() else 0)
    return str(sum(wert(c) * w[i % 3] for i, c in enumerate(s)) % 10)


def _mrz_datum(text):
    """„28.07.1978“ oder ISO → JJMMTT; unbekannt → <<<<<<."""
    text = (text or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%y%m%d")
        except ValueError:
            pass
    return "<<<<<<"


def _mrz_name(name, laenge):
    """Nachname<<Vornamen (Heuristik: letztes Wort = Nachname; Ordnungszahlen wie „IX.“ bleiben beim Namen)."""
    teile = [t for t in re.split(r"\s+", name.strip()) if t]
    if len(teile) > 1 and not re.fullmatch(r"[IVXLC]+\.?", teile[-1]):
        n = _mrz(teile[-1]) + "<<" + _mrz(" ".join(teile[:-1]))
    else:
        n = _mrz(name)
    return (n + "<" * laenge)[:laenge]


def _sex(geschlecht):
    return {"Männlich": "M", "Weiblich": "F"}.get(geschlecht or "", "<")


def mrz_heft(typ, nr, name, geburt, geschlecht, bis):
    nr = (_mrz(nr) + "<" * 9)[:9]
    z1 = (typ + STAAT + _mrz_name(name, 39))[:44]
    gb, ab, opt = _mrz_datum(geburt), _mrz_datum(bis), "<" * 14
    teil = nr + pruefziffer(nr) + STAAT + gb + pruefziffer(gb) + _sex(geschlecht) + ab + pruefziffer(ab) + opt + pruefziffer(opt)
    gesamt = nr + pruefziffer(nr) + gb + pruefziffer(gb) + ab + pruefziffer(ab) + opt + pruefziffer(opt)
    return z1, teil + pruefziffer(gesamt)


def mrz_karte(nr, name, geburt, geschlecht, bis):
    nr = (_mrz(nr) + "<" * 9)[:9]
    z1 = ("ID" + STAAT + nr + pruefziffer(nr) + "<" * 15)[:30]
    gb, ab = _mrz_datum(geburt), _mrz_datum(bis)
    z2 = gb + pruefziffer(gb) + _sex(geschlecht) + ab + pruefziffer(ab) + STAAT + "<" * 11
    z2 += pruefziffer(z1[5:30] + z2[0:7] + z2[8:15] + z2[18:29])
    return z1, z2, _mrz_name(name, 30)


# ---------------------------------------------------------------- Sicherheitsmuster (Guilloche, Rosette)

def guilloche(w, h, farbe, zeilen=30, amp=2.2, perioden=4.0, staerke=0.11, phase=0.0):
    linien = []
    for i in range(zeilen):
        y0 = h * (i + 0.5) / zeilen
        pts = []
        for s in range(161):
            t = s / 160
            y = y0 + amp * math.sin(2 * math.pi * perioden * t + i * 0.42 + phase) + amp * 0.45 * math.sin(2 * math.pi * perioden * 2.6 * t - i * 0.31)
            pts.append(f"{w * t:.2f},{y:.2f}")
        linien.append(f'<polyline points="{" ".join(pts)}"/>')
    return (f'<svg class="muster" viewBox="0 0 {w} {h}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
            f'<g fill="none" stroke="{farbe}" stroke-width="{staerke}">{"".join(linien)}</g></svg>')


def rosette(r, farbe, n=40, staerke=0.12):
    el = "".join(f'<ellipse cx="0" cy="0" rx="{r}" ry="{r * 0.36:.2f}" transform="rotate({180 * i / n:.2f})"/>' for i in range(n))
    el += "".join(f'<circle r="{r * f:.2f}"/>' for f in (0.32, 0.62, 1.0))
    return (f'<svg class="rosette" viewBox="{-r - 1} {-r - 1} {2 * r + 2} {2 * r + 2}" xmlns="http://www.w3.org/2000/svg">'
            f'<g fill="none" stroke="{farbe}" stroke-width="{staerke}">{el}</g></svg>')


def _chip(farbe):
    """Symbol „elektronischer Pass“ (Chip) für den Umschlag."""
    return (f'<svg class="chip" viewBox="0 0 30 20" xmlns="http://www.w3.org/2000/svg"><g fill="none" stroke="{farbe}" stroke-width="1.3">'
            '<rect x="1" y="1" width="28" height="18" rx="1"/><path d="M1 7h8M21 7h8M1 13h8M21 13h8"/><circle cx="15" cy="10" r="4.2"/></g></svg>')


# ---------------------------------------------------------------- Bausteine

CSS = """
@font-face{font-family:SS3;src:url(data:font/woff2;base64,%s);font-weight:200 900}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-family:SS3,"Liberation Sans",Arial,sans-serif;color:#1a1a1a}
.bogen{position:relative;overflow:hidden;break-after:page}
.bogen:last-child{break-after:auto}
.quer{width:297mm;height:210mm}.hoch{width:210mm;height:297mm}
.bogen-kopf{position:absolute;left:23.5mm;right:23.5mm;top:5mm;font-size:8pt;color:#555;display:flex;justify-content:space-between;gap:8mm}
.bogen-kopf b{color:#000}
.anleitung{position:absolute;left:23.5mm;right:23.5mm;top:9.5mm;font-size:6.8pt;color:#444;display:flex;gap:8mm;align-items:flex-end;line-height:1.35}
.anleitung p{flex:1}.hoch .anleitung{top:auto;bottom:8mm;left:19.4mm;right:19.4mm;font-size:7.5pt}.hoch .bogen-kopf{left:19.4mm;right:19.4mm;top:8mm}
.mass{flex:none;text-align:center;font-size:6.5pt}
.mass i{display:block;width:50mm;height:2.2mm;border:.25mm solid #000;border-top:0;margin-bottom:.8mm}
.teil{position:absolute}
.zuschnitt{position:absolute;inset:0;overflow:hidden}
.marke{position:absolute;width:3mm;height:3mm;border-color:#888;border-style:solid;border-width:0}
.marke.lo{left:-3.5mm;top:-3.5mm;border-right-width:.2mm;border-bottom-width:.2mm}
.marke.ro{right:-3.5mm;top:-3.5mm;border-left-width:.2mm;border-bottom-width:.2mm}
.marke.lu{left:-3.5mm;bottom:-3.5mm;border-right-width:.2mm;border-top-width:.2mm}
.marke.ru{right:-3.5mm;bottom:-3.5mm;border-left-width:.2mm;border-top-width:.2mm}
.falz{position:absolute;top:-3.5mm;bottom:-3.5mm;border-left:.2mm dashed #888}
.falz span{position:absolute;top:-.3mm;left:1mm;font-size:5.5pt;color:#888;white-space:nowrap;transform:translateY(-100%%)}
.teil-titel{position:absolute;left:5mm;top:-.6mm;font-size:6.5pt;color:#666;transform:translateY(-100%%);white-space:nowrap}
.muster{position:absolute;inset:0;width:100%%;height:100%%}
.seite{position:absolute;top:0;width:125mm;height:88mm;overflow:hidden}
.seite.l{left:0}.seite.r{left:125mm}
/* Umschlag */
.umschlag{color:var(--gold)}
.umschlag .staat{position:absolute;top:9mm;left:0;right:0;text-align:center;font:400 12.5pt/1 "Liberation Serif",Georgia,serif;letter-spacing:.24em}
.umschlag .wappen{position:absolute;top:19mm;left:50%%;width:58mm;transform:translateX(-50%%)}
.umschlag .titel{position:absolute;top:69mm;left:0;right:0;text-align:center;font:400 13pt/1 "Liberation Serif",Georgia,serif;letter-spacing:.3em;text-transform:uppercase}
.umschlag .chip{position:absolute;top:76.5mm;left:50%%;width:8mm;transform:translateX(-50%%)}
.rueck .klein{position:absolute;bottom:6mm;left:0;right:0;text-align:center;font:400 6pt/1.4 "Liberation Serif",Georgia,serif;letter-spacing:.18em;opacity:.8}
/* Innenseiten */
.innen .wappen-f{position:absolute;top:8mm;left:50%%;width:26mm;transform:translateX(-50%%)}
.ersuchen{position:absolute;top:34mm;left:13mm;right:13mm;text-align:center;font:italic 400 9.6pt/1.5 "Liberation Serif",Georgia,serif;color:#2a2340}
.ersuchen .en{display:block;margin-top:2.6mm;font-size:7.4pt;color:#5a5070}
.innen .fuss{position:absolute;bottom:4mm;left:8mm;right:8mm;text-align:center;font-size:5.6pt;color:#6a6080;line-height:1.35}
.visa-kopf{position:absolute;top:5mm;left:7mm;right:7mm;display:flex;justify-content:space-between;font-size:7pt;letter-spacing:.14em;text-transform:uppercase;color:#5a5070}
.seitenzahl{position:absolute;bottom:4mm;font-size:7pt;color:#5a5070}.l .seitenzahl{left:7mm}.r .seitenzahl{right:7mm}
.rosette{position:absolute;opacity:.55}
.innen .rosette{width:70mm;left:27.5mm;top:16mm}
.innen .nr-loch{position:absolute;right:5mm;top:5mm;font:600 7pt/1 "Liberation Mono",monospace;color:#8a2030;letter-spacing:.12em}
/* Datenseite */
.daten-seite .kopf{position:absolute;top:4mm;left:5mm;right:5mm;display:flex;justify-content:space-between;align-items:baseline;border-bottom:.25mm solid #6d5c86;padding-bottom:1mm}
.daten-seite .kopf b{font-size:8.5pt;letter-spacing:.16em}
.daten-seite .kopf span{font-size:7pt;letter-spacing:.1em;text-transform:uppercase;color:#4a3d5e}
.foto{position:absolute;left:5mm;top:13mm;width:30mm;height:38.5mm;border:.2mm solid #6d5c86;background:#fff;overflow:hidden;display:grid;place-items:center}
.foto img{width:100%%;height:100%%;object-fit:cover;filter:grayscale(.15) contrast(1.05)}
.foto em{font-style:normal;font-size:6pt;color:#888;text-align:center;padding:2mm;line-height:1.3}
.geist{position:absolute;width:15mm;height:19mm;opacity:.28;filter:grayscale(1);overflow:hidden;border-radius:1mm}
.geist img{width:100%%;height:100%%;object-fit:cover}
.daten-seite .geist{right:6mm;top:39mm}
.qr-feld{position:absolute;background:rgba(255,255,255,.75);border-radius:.6mm}
.daten-seite .qr-feld{right:5.5mm;top:58.6mm}
.karte .qr-feld{right:3.5mm;top:3.8mm}
.felder{position:absolute;left:39mm;right:5mm;top:12.5mm;display:grid;grid-template-columns:1fr 1fr;column-gap:3mm;row-gap:1.15mm}
.feld{min-width:0}.feld.voll{grid-column:1/-1}
.feld i{display:block;font-style:normal;font-size:5.3pt;color:#5d4f72;line-height:1.15}
.feld b{display:block;font-size:8.6pt;font-weight:600;text-transform:uppercase;letter-spacing:.02em;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.feld b.nr{color:#8a2030;font-family:"Liberation Mono",monospace;letter-spacing:.08em}
.unterschrift{position:absolute;left:5mm;top:54mm;width:30mm}
.unterschrift i{display:block;font-style:normal;font-size:5.3pt;color:#5d4f72;border-top:.2mm solid #6d5c86;padding-top:.6mm;margin-top:6.5mm}
.mrz{position:absolute;left:4.5mm;right:4.5mm;font:400 3.72mm/1.28 "Liberation Mono","DejaVu Sans Mono",monospace;letter-spacing:0;color:#111;white-space:pre}
.daten-seite .mrz{bottom:4.2mm}
.vermerk{position:absolute;font-size:3.4pt;color:#7a6f8c;letter-spacing:.03em;white-space:nowrap}
.daten-seite .vermerk{left:5mm;bottom:1.2mm}
/* Ausweiskarte */
.karte{position:absolute;top:0;width:85.6mm;height:54mm;border-radius:3.2mm;overflow:hidden;background:linear-gradient(135deg,#e6f1ec,#eef0f7 55%%,#f3ecef)}
.karte.v{left:0}.karte.h{left:85.6mm}
.karte .kopf{position:absolute;top:2.2mm;left:4mm;right:4mm;display:flex;justify-content:space-between;align-items:center}
.karte .kopf b{font-size:6.4pt;letter-spacing:.16em;line-height:1.1}
.karte .kopf span{font-size:5pt;line-height:1.1;letter-spacing:.1em;text-transform:uppercase;color:#2f5546}
.karte .kopf img{height:6.5mm}.karte .kt{display:flex;flex-direction:column;gap:.7mm}.karte .kt b,.karte .kt span{display:block}
.karte .foto{left:3.5mm;top:11.5mm;width:22mm;height:28.5mm;border-color:#3b6a58}
.karte .felder{left:28.5mm;right:3.5mm;top:12.2mm;row-gap:.7mm}
.karte .feld i{font-size:4.4pt;color:#3b6a58}.karte .feld b{font-size:7pt}
.karte .geist{right:3.5mm;bottom:3.5mm;width:10mm;height:12.5mm}
.karte .unterschrift{left:28.5mm;top:43mm;width:38mm}.karte .unterschrift i{margin-top:4.2mm;border-color:#3b6a58;color:#3b6a58;font-size:4.4pt}
.karte .rosette{width:30mm;right:-9mm;top:24mm;opacity:.35}
.karte .mrz{bottom:2.6mm;left:3.6mm;right:3.6mm;font-size:3.55mm;line-height:1.2}
.karte .vermerk{left:4mm;top:1mm;font-size:3pt;color:#557}
.karte .rueck-felder{position:absolute;left:4mm;right:20mm;top:4mm;display:grid;grid-template-columns:1fr 1fr;column-gap:3mm;row-gap:.9mm}
.karte .rueck-felder .feld b{white-space:normal}
"""


def _css():
    return CSS % amt._PDF_SCHRIFT


def _schnitt(titel, falz=None):
    m = "".join(f'<i class="marke {x}"></i>' for x in ("lo", "ro", "lu", "ru"))
    f = f'<i class="falz" style="left:{falz}mm"><span>Falz</span></i>' if falz else ""
    return f'<span class="teil-titel">{esc(titel)}</span>{m}{f}'


def _feld(de, en, wert, voll=False, nr=False):
    return (f'<div class="feld{" voll" if voll else ""}"><i>{esc(de)} / {esc(en)}</i>'
            f'<b{" class=nr" if nr else ""}>{esc(wert or "–")}</b></div>')


def _foto(url, leer_text):
    if url:
        return f'<div class="foto"><img src="{esc(url)}" alt=""></div>'
    return f'<div class="foto"><em>{leer_text}</em></div>'


def _geist(url):
    return f'<div class="geist"><img src="{esc(url)}" alt=""></div>' if url else ""


def _anleitung(text):
    return (f'<div class="anleitung"><p>{text}</p><div class="mass"><i></i>Kontrollmaß 50 mm – bitte nachmessen</div></div>')


def _d(iso_oder_text):
    try:
        return date.fromisoformat(iso_oder_text).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return iso_oder_text or ""


# ---------------------------------------------------------------- Passheft

def heft_seiten(d):
    """Einzelseiten des Passhefts (HTML, je 125 × 88 mm): vorne, hinten, ersuchen, daten und visa(seite, nr)."""
    farbe, ton, linie, typ, titel, titel_en = HEFT[d["art"]]
    z1, z2 = mrz_heft(typ, d["nummer"], d["name"], d["geburt"], d["geschlecht"], d["bis"])
    nat = ("Fremder", "Alien") if d["art"] == "fremdenpass" else ("Imperium Germanicum", "")
    zusatz = {"dienstpass": " Der Inhaber reist in dienstlichem Auftrag des Reiches.",
              "fremdenpass": " Dieser Pass begründet keine Staatsangehörigkeit des Reiches.",
              "vorlaeufig": " Dieser vorläufige Pass gilt nur bis zum angegebenen Datum."}.get(d["art"], "")

    vorne = (f'<div class="seite r umschlag" style="background:{farbe};--gold:{GOLD}">'
             f'<div class="staat">IMPERIUM GERMANICUM</div><img class="wappen" src="{bild("wappen_gold.png")}" alt="">'
             f'<div class="titel">{esc(titel)}</div>{_chip(GOLD)}</div>')
    hinten = (f'<div class="seite l umschlag rueck" style="background:{farbe};--gold:{GOLD}">'
              '<div class="klein">REICHSVERWALTUNG · IM AUFTRAG SEINER MAJESTÄT</div></div>')
    ersuchen = (f'<div class="seite l innen" style="background:{ton}">{guilloche(125, 88, linie, 34)}{rosette(35, linie)}'
                f'<img class="wappen-f" src="{bild("wappen.png")}" alt=""><span class="nr-loch">{esc(d["nummer"])}</span>'
                '<p class="ersuchen">Seine Majestät der Kaiser des Imperium Germanicum ersucht im Namen des Reiches alle, die es angeht, '
                'dem Inhaber oder der Inhaberin dieses Passes die ungehinderte Reise zu gestatten und ihm oder ihr erforderlichenfalls '
                'jeden Schutz und Beistand zu gewähren.' + esc(zusatz) +
                '<span class="en">His Imperial Majesty requests and requires in the name of the Empire all those whom it may concern '
                'to allow the bearer to pass freely without let or hindrance, and to afford the bearer such assistance and protection '
                'as may be necessary.</span></p>'
                '<p class="fuss">Dieser Pass bleibt Eigentum des Reiches. Verlust oder Diebstahl ist unverzüglich der Reichsverwaltung '
                f'zu melden.<br>{esc(VERMERK)}</p></div>')
    daten = (f'<div class="seite r innen daten-seite" style="background:{ton}">{guilloche(125, 88, linie, 30, 1.8, 5.2, 0.1, 1.3)}'
             f'<div class="rosette" style="width:46mm;right:2mm;top:12mm">{rosette(30, linie)}</div>'
             f'<div class="kopf"><b>IMPERIUM GERMANICUM</b><span>{esc(titel)} · {esc(titel_en)}</span></div>'
             + _foto(d["foto"], "Lichtbild<br>hier einkleben<br>(30 × 38,5 mm)") + _geist(d["foto"])
             + '<div class="felder">'
             + _feld("Typ", "Type", typ.replace("<", "")) + _feld("Pass-Nr.", "Passport No.", d["nummer"], nr=True)
             + _feld("Name", "Name", d["name"], voll=True)
             + _feld("Staatsangehörigkeit", "Nationality", nat[0] if not nat[1] else f"{nat[0]} / {nat[1]}", voll=True)
             + _feld("Geburtsdatum", "Date of birth", d["geburt"]) + _feld("Geschlecht", "Sex", d["geschlecht_kurz"])
             + _feld("Wohnsitz", "Residence", d["wohnsitz"], voll=True)
             + _feld("Ausstellungsdatum", "Date of issue", d["ausgestellt"]) + _feld("Gültig bis", "Date of expiry", _d(d["bis"]))
             + _feld("Behörde", "Authority", "Reichsverwaltung") + _feld("Staatencode", "Code", STAAT)
             + '</div><div class="unterschrift"><i>Unterschrift des Inhabers / Holder\'s signature</i></div>'
             f'<div class="qr-feld">{qr.svg(d["qr"], 14)}</div>'
             f'<div class="mrz">{esc(z1)}\n{esc(z2)}</div><span class="vermerk">{esc(VERMERK)}</span></div>')

    def visa_seite(seite, nr):
        return (f'<div class="seite {seite} innen" style="background:{ton}">{guilloche(125, 88, linie, 30, 2.4, 3.4, 0.1, nr)}'
                f'<div class="rosette" style="width:60mm;left:32.5mm;top:14mm">{rosette(30, linie)}</div>'
                f'<div class="visa-kopf"><span>Sichtvermerke · Visas</span><span>Imperium Germanicum</span></div>'
                f'<span class="seitenzahl">{nr}</span></div>')

    def visa(nr_l, nr_r):
        return visa_seite("l", nr_l) + visa_seite("r", nr_r)

    return {"vorne": vorne, "hinten": hinten, "ersuchen": ersuchen, "daten": daten, "visa": visa, "visa_seite": visa_seite, "titel": titel}


def heft(d):
    s = heft_seiten(d)
    titel, vorne, hinten, ersuchen, daten, visa = s["titel"], s["vorne"], s["hinten"], s["ersuchen"], s["daten"], s["visa"]

    def teil(x, y, titel_teil, inhalt):
        return (f'<div class="teil" style="left:{x}mm;top:{y}mm;width:250mm;height:88mm">'
                f'<div class="zuschnitt">{inhalt}</div>{_schnitt(titel_teil, 125)}</div>')

    kopf = lambda n: (f'<div class="bogen-kopf"><span><b>Druckvorlage {esc(titel)} {esc(d["nummer"])}</b> · {esc(d["name"])}</span>'
                      f'<span>Bogen {n} von 2 · erstellt {esc(d["erstellt"])}</span></div>')
    b1 = (f'<section class="bogen quer">{kopf(1)}'
          + teil(23.5, 21, "A · Umschlag außen (Rückseite | Vorderseite)", hinten + vorne)
          + teil(23.5, 116, "B · Umschlag innen (Ersuchen | Personaldatenseite)", ersuchen + daten)
          + _anleitung("Mit 100 % („Tatsächliche Größe“, nicht „An Seite anpassen“) auf festem Papier (160–250 g) drucken. A und B an den "
                       "Schnittmarken ausschneiden, Rückseite an Rückseite kleben (B hinter A, Falzlinien deckungsgleich), mit Bogen 2 ebenso "
                       "verfahren. Laminieren, mittig falzen, Innenblatt einlegen und heften.") + '</section>')
    b2 = (f'<section class="bogen quer">{kopf(2)}'
          + teil(23.5, 21, "C · Innenblatt außen (Seite 4 | Seite 1)", visa(4, 1))
          + teil(23.5, 116, "D · Innenblatt innen (Seite 2 | Seite 3)", visa(2, 3))
          + _anleitung("C und D ausschneiden, Rückseite an Rückseite kleben (D hinter C, Falzlinien deckungsgleich), mittig falzen und "
                       "in den Umschlag aus Bogen 1 einlegen: nach dem Ersuchen folgen die Seiten 1 bis 4, am Ende die Personaldatenseite.")
          + '</section>')
    return b1 + b2, "@page{size:A4 landscape;margin:0}"


# ---------------------------------------------------------------- Personalausweis

def karte(d):
    vorne, hinten = karte_seiten(d)
    return _karte_bogen(d, vorne, hinten)


def karte_seiten(d):
    """Vorder- und Rückseite des Personalausweises (HTML, je 85,6 × 54 mm)."""
    z1, z2, z3 = mrz_karte(d["nummer"], d["name"], d["geburt"], d["geschlecht"], d["bis"])
    linie = "#8fb5a4"
    vorne = (f'<div class="karte v">{guilloche(85.6, 54, linie, 26, 1.4, 3.2, 0.09)}{rosette(20, linie)}'
             f'<div class="kopf"><div class="kt"><b>IMPERIUM GERMANICUM</b><span>Personalausweis · Identity card</span></div>'
             f'<img src="{bild("wappen.png")}" alt=""></div>'
             + _foto(d["foto"], "Lichtbild<br>einkleben<br>(22 × 28,5 mm)") + _geist(d["foto"])
             + '<div class="felder">'
             + _feld("Name", "Name", d["name"], voll=True)
             + _feld("Geburtsdatum", "Date of birth", d["geburt"]) + _feld("Ausweis-Nr.", "Card No.", d["nummer"], nr=True)
             + _feld("Staatsangehörigkeit", "Nationality", "Imperium Germanicum", voll=True)
             + _feld("Gültig bis", "Date of expiry", _d(d["bis"])) + _feld("Geschlecht", "Sex", d["geschlecht_kurz"])
             + '</div><div class="unterschrift"><i>Unterschrift / Signature</i></div></div>')
    hinten = (f'<div class="karte h">{guilloche(85.6, 54, linie, 26, 1.4, 2.6, 0.09, 2.1)}'
              f'<div class="qr-feld">{qr.svg(d["qr"], 14)}</div><div class="rueck-felder">'
              + _feld("Anschrift", "Address", d["anschrift"], voll=True)
              + _feld("Teilstaat", "State", d["wohnsitz"]) + _feld("Gesellschaftsschicht", "Estate", d["schicht"])
              + _feld("Ausgestellt am", "Date of issue", d["ausgestellt"]) + _feld("Behörde", "Authority", "Reichsverwaltung")
              + f'</div><span class="vermerk" style="top:auto;bottom:16.8mm">{esc(VERMERK)}</span>'
              f'<div class="mrz">{esc(z1)}\n{esc(z2)}\n{esc(z3)}</div></div>')
    return vorne, hinten


def _karte_bogen(d, vorne, hinten):
    kopf = (f'<div class="bogen-kopf"><span><b>Druckvorlage Personalausweis {esc(d["nummer"])}</b> · {esc(d["name"])}</span>'
            f'<span>erstellt {esc(d["erstellt"])}</span></div>')
    teil = (f'<div class="teil" style="left:19.4mm;top:40mm;width:171.2mm;height:54mm"><div class="zuschnitt" style="overflow:visible">'
            f'{vorne}{hinten}</div>{_schnitt("Vorderseite | Rückseite", 85.6)}</div>')
    zweit = (f'<div class="teil" style="left:19.4mm;top:130mm;width:171.2mm;height:54mm"><div class="zuschnitt" style="overflow:visible">'
             f'{vorne}{hinten}</div>{_schnitt("Ersatzexemplar", 85.6)}</div>')
    return (f'<section class="bogen hoch">{kopf}{teil}{zweit}'
            + _anleitung("Mit 100 % („Tatsächliche Größe“) drucken. Karte entlang der Außenkante ausschneiden (Ecken abrunden), an der "
                         "Falzlinie nach hinten falten und die Hälften zusammenkleben, sodass die Rückseite beim Umdrehen richtig herum "
                         "steht. Danach laminieren (Laminierfolie 80 × 110 mm oder Scheckkartengröße) und mit etwas Rand zuschneiden. "
                         "Das zweite Exemplar dient als Ersatz bei Fehldrucken.") + '</section>'), "@page{size:A4 portrait;margin:0}"


# ---------------------------------------------------------------- Route

def daten(con, p, mit_foto):
    akte = con.execute("SELECT * FROM amt_akten WHERE id=?", (p["akte_id"],)).fetchone()
    ws = meldewesen.wohnsitz(con, p["akte_id"])
    konto = con.execute("SELECT avatar FROM konten WHERE id=?", (p["konto_id"],)).fetchone()
    foto = ""
    if mit_foto and konto and konto["avatar"]:
        foto = f'https://cdn.discordapp.com/avatars/{p["konto_id"]}/{konto["avatar"]}.png?size=512'
    geschlecht = (akte["geschlecht"] if akte else "") or ""
    wohnsitz = ""
    if ws:
        wohnsitz = "Ausland" if ws["art"] == "abmeldung" else ws["staat_name"]
    return {"art": p["art"], "nummer": p["nummer"], "name": p["inhaber"], "geburt": p["geburt"], "bis": p["gueltig_bis"],
            "geschlecht": geschlecht, "geschlecht_kurz": {"Männlich": "M", "Weiblich": "W", "Divers": "D"}.get(geschlecht, "–"),
            "wohnsitz": wohnsitz, "anschrift": (ws["anschrift"] if ws and ws["art"] != "abmeldung" else "") or "",
            "schicht": (akte["schicht"] if akte else "") or "", "foto": foto,
            "ausgestellt": amt._zeit(p["ausgestellt"], False), "erstellt": amt._zeit(int(time.time())), "qr": qr.kurzlink(p["nummer"])}


@amt._beamter
async def druck(request):
    con, k = request.app["db"], request["konto"]
    p, _ = meldewesen._pass(con, k, request.match_info["id"])
    s, text = meldewesen.pass_status(p)
    if s != "gueltig":
        amt._umleiten(f'{PFAD}paesse/{p["id"]}/', f"Keine Druckvorlage: Der Pass ist {text.lower()}.", True)
    mit_foto = request.query.get("bild", "discord") != "leer"
    d = daten(con, p, mit_foto)
    inhalt, seite = karte(d) if p["art"] == "personalausweis" else heft(d)
    text_html = (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Druckvorlage {esc(p["nummer"])}</title>'
                 f'<style>{_css()}{seite}</style></head><body>{inhalt}</body></html>')
    from playwright.async_api import async_playwright
    import bild as _bild  # noqa: F401  setzt PLAYWRIGHT_BROWSERS_PATH
    async with amt._pdf_sperre:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                pg = await browser.new_page()
                await pg.set_content(text_html, wait_until="networkidle", timeout=20000)
                await pg.evaluate("document.fonts.ready")
                pdf = await pg.pdf(prefer_css_page_size=True, print_background=True)
            finally:
                await browser.close()
    meldewesen._eintrag(con, p["id"], "Druckvorlage", f'Druckvorlage erstellt ({"mit Discord-Bild" if mit_foto else "Lichtbild zum Einkleben"}).', k)
    con.commit()
    return web.Response(body=pdf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="druckvorlage-{p["nummer"]}.pdf"', "Cache-Control": "no-store"})


def knoepfe(p):
    """Knöpfe für die Pass-Ansicht (nur gültige Pässe der unterstützten Arten)."""
    if meldewesen.pass_status(p)[0] != "gueltig":
        return ""
    u = f'{PFAD}paesse/{p["id"]}/druck'
    return (f'<a class="btn zweit" href="{u}?bild=discord">{amt.ic("printer")}Druckvorlage (mit Profilbild)</a>'
            f'<a class="btn zweit" href="{u}?bild=leer">{amt.ic("printer")}Druckvorlage (Lichtbild einkleben)</a>')


def registrieren(app):
    amt.ICONS.setdefault("printer", '<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>'
                                    '<path d="M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6"/><rect x="6" y="14" width="12" height="8" rx="1"/>')
    meldewesen.PASS_KNOEPFE.append(knoepfe)
    app.router.add_get(PFAD + "paesse/{id}/druck", druck)
