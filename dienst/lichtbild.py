"""Eigenes Lichtbild je Bürgerakte (für Pässe, Druckvorlagen, digitalen Pass und Prüfseite).

Beamte mit Schreibrecht laden in der Bürgerakte (Abschnitt Melde- und Passwesen) ein Bild hoch. Es wird im Browser verkleinert,
serverseitig mit Pillow auf das Passbildformat 35:45 zugeschnitten (Mitte, leicht nach oben versetzt) und als JPEG in mw_lichtbilder
gespeichert. Hat eine Akte ein Lichtbild, hat es Vorrang vor dem Discord-Profilbild; ohne Lichtbild bleibt alles wie bisher.

Routen:
- POST …/intern/buerger/<id>/lichtbild       hochladen bzw. entfernen (Feld loeschen=1)
- GET  …/intern/lichtbild/<akte_id>.jpg       Bild (Berechtigte wie Passprüfung/Akten, der Inhaber selbst; Verschluss beachtet)
"""
import base64
import io
import time

from aiohttp import web

import amt
import anmeldung

esc = amt.esc
BASIS = amt.BASIS
BREITE, HOEHE = 700, 900   # 35:45
MAX_BYTES = 1_800_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS mw_lichtbilder (
    akte_id INTEGER PRIMARY KEY, bild BLOB NOT NULL, zeit INTEGER NOT NULL, autor_id TEXT, autor_name TEXT NOT NULL DEFAULT '');
"""


def _zeile(con, akte_id):
    if not akte_id:
        return None
    return con.execute("SELECT akte_id, zeit, autor_name FROM mw_lichtbilder WHERE akte_id=?", (akte_id,)).fetchone()


def url(con, akte_id, konto_id=""):
    """Bild-URL für Webseiten: eigenes Lichtbild, sonst Discord-Profilbild über den Dienst, sonst ""."""
    r = _zeile(con, akte_id)
    if r:
        return f'{BASIS}lichtbild/{r["akte_id"]}.jpg?v={r["zeit"]}'
    if konto_id:
        k = con.execute("SELECT avatar FROM konten WHERE id=?", (konto_id,)).fetchone()
        if k and k["avatar"]:
            return f'{BASIS}pass-foto/{konto_id}'
    return ""


def daten_uri(con, akte_id):
    """Lichtbild als data-URI (für Druckvorlagen) oder ""."""
    r = con.execute("SELECT bild FROM mw_lichtbilder WHERE akte_id=?", (akte_id,)).fetchone() if akte_id else None
    return "data:image/jpeg;base64," + base64.b64encode(r["bild"]).decode() if r else ""


def vorhanden(con, akte_id):
    return _zeile(con, akte_id) is not None


def _aufbereiten(roh):
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(roh))
        im.load()
    except Exception:
        return None
    im = ImageOps.exif_transpose(im).convert("RGB")
    w, h = im.size
    if w < 80 or h < 80:
        return None
    ziel = BREITE / HOEHE
    if w / h > ziel:                       # zu breit: mittig beschneiden
        nw = int(h * ziel)
        box = ((w - nw) // 2, 0, (w - nw) // 2 + nw, h)
    else:                                  # zu hoch: oben etwas mehr behalten (Gesicht)
        nh = int(w / ziel)
        oben = int((h - nh) * 0.3)
        box = (0, oben, w, oben + nh)
    im = im.crop(box)
    if im.size[0] > BREITE:
        im = im.resize((BREITE, HOEHE), Image.LANCZOS)
    aus = io.BytesIO()
    im.save(aus, "JPEG", quality=88, optimize=True)
    return aus.getvalue()


async def hochladen(request):
    import meldewesen
    k, form = await amt._post(request)
    con = request.app["db"]
    z = meldewesen._akte(con, k, request.match_info["id"])
    ziel = f'{BASIS}buerger/{z["id"]}/'
    if form.get("loeschen"):
        if vorhanden(con, z["id"]):
            con.execute("DELETE FROM mw_lichtbilder WHERE akte_id=?", (z["id"],))
            amt.eintrag(con, "akte", z["id"], "Lichtbild", "Lichtbild entfernt.", k["id"], k["name"])
            con.commit()
        amt._umleiten(ziel, "Lichtbild entfernt.")
    datei = form.get("bild")
    if not hasattr(datei, "file"):
        amt._umleiten(ziel, "Bitte eine Bilddatei auswählen.", True)
    roh = datei.file.read(MAX_BYTES + 1)
    if len(roh) > MAX_BYTES:
        amt._umleiten(ziel, "Das Bild ist zu groß (höchstens 1,8 MB).", True)
    bild = _aufbereiten(roh)
    if not bild:
        amt._umleiten(ziel, "Die Datei ist kein lesbares Bild (JPEG, PNG oder WebP, mindestens 80 × 80 Pixel).", True)
    neu = not vorhanden(con, z["id"])
    con.execute("INSERT OR REPLACE INTO mw_lichtbilder (akte_id, bild, zeit, autor_id, autor_name) VALUES (?,?,?,?,?)",
                (z["id"], bild, int(time.time()), k["id"], k["name"]))
    amt.eintrag(con, "akte", z["id"], "Lichtbild", "Lichtbild hinterlegt." if neu else "Lichtbild ersetzt.", k["id"], k["name"])
    con.execute("UPDATE amt_akten SET aktualisiert=? WHERE id=?", (int(time.time()), z["id"]))
    con.commit()
    amt._umleiten(ziel, "Lichtbild gespeichert. Es erscheint ab sofort auf allen Pässen dieser Person.")


async def anzeigen(request):
    import meldewesen
    k = await anmeldung.konto(request)
    i = request.match_info["id"]
    con = request.app["db"]
    a = con.execute("SELECT konto_id, verschluss FROM amt_akten WHERE id=?", (i,)).fetchone() if i.isdigit() else None
    if not k or not a:
        raise web.HTTPNotFound()
    inhaber = a["konto_id"] == k["id"]
    berechtigt = amt.ist_leser(k) or (k["mitglied"] and meldewesen.darf_pruefen(k))
    if not inhaber and (not berechtigt or (a["verschluss"] and not amt.darf_verschluss(k))):
        raise web.HTTPForbidden()
    r = con.execute("SELECT bild FROM mw_lichtbilder WHERE akte_id=?", (i,)).fetchone()
    if not r:
        raise web.HTTPNotFound()
    return web.Response(body=r["bild"], content_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


JS = """<script>(function(){
var f=document.getElementById("lb-form");if(!f)return;
var inp=f.querySelector("input[type=file]"),vor=document.getElementById("lb-vorschau"),knopf=f.querySelector("button[type=submit]"),blob=null;
inp.addEventListener("change",function(){blob=null;var d=inp.files&&inp.files[0];if(!d)return;
 var img=new Image(),u=URL.createObjectURL(d);img.onload=function(){
  var s=Math.min(1,1600/Math.max(img.width,img.height)),c=document.createElement("canvas");
  c.width=Math.round(img.width*s);c.height=Math.round(img.height*s);c.getContext("2d").drawImage(img,0,0,c.width,c.height);
  c.toBlob(function(b){blob=b;vor.src=URL.createObjectURL(b);vor.hidden=false;URL.revokeObjectURL(u)},"image/jpeg",.9)};
 img.onerror=function(){vor.hidden=true};img.src=u});
f.addEventListener("submit",function(e){if(!blob)return;e.preventDefault();var fd=new FormData(f);fd.set("bild",blob,"lichtbild.jpg");
 knopf.disabled=true;fetch(f.action,{method:"POST",body:fd,credentials:"same-origin"}).then(function(r){if(r.redirected){location.href=r.url}else{knopf.disabled=false;alert("Hochladen fehlgeschlagen ("+r.status+").")}}).catch(function(){knopf.disabled=false;f.submit()})});
})();</script>"""

CSS = """<style>.lb{display:flex;gap:16px;align-items:flex-start;margin:6px 0 18px;flex-wrap:wrap}
.lb-bild{width:105px;height:135px;border:1px solid var(--linie);border-radius:6px;object-fit:cover;background:#f3f3f3;flex:none}
.lb-leer{width:105px;height:135px;border:1px dashed var(--linie);border-radius:6px;display:grid;place-items:center;text-align:center;font-size:12px;color:#888;flex:none;padding:6px}
.lb-text{flex:1;min-width:220px}.lb-text p{margin:0 0 8px}
#lb-vorschau{width:70px;height:90px;object-fit:cover;border-radius:4px;border:1px solid var(--linie);margin-top:8px}
.lb form{margin:0}.lb .aktionen{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}</style>"""


def abschnitt(request, con, z, schreiben):
    """Lichtbild-Block für die Bürgerakte (in meldewesen.akte_abschnitt)."""
    r = _zeile(con, z["id"])
    hat_avatar = bool(z["konto_id"]) and bool(con.execute("SELECT 1 FROM konten WHERE id=? AND avatar<>''", (z["konto_id"],)).fetchone())
    if r:
        bild = f'<img class="lb-bild" src="{url(con, z["id"])}" alt="Lichtbild">'
        stand = f'Eigenes Lichtbild · hinterlegt {amt._zeit(r["zeit"], False)} von {esc(r["autor_name"])} · wird auf allen Pässen verwendet'
    elif hat_avatar:
        bild = f'<img class="lb-bild" src="{BASIS}pass-foto/{esc(z["konto_id"])}" alt="Discord-Profilbild">'
        stand = "Kein eigenes Lichtbild – die Pässe zeigen das Discord-Profilbild der Person."
    else:
        bild = '<span class="lb-leer">Kein Lichtbild</span>'
        stand = ("Kein Lichtbild. Ein Discord-Profilbild steht erst zur Verfügung, wenn sich die Person auf der Website angemeldet hat – "
                 "bis dahin hier ein eigenes Lichtbild hinterlegen.")
    h = f'{CSS}<div class="lb">{bild}<div class="lb-text"><p><b>Lichtbild</b><br><span class="az">{stand}</span></p>'
    if schreiben:
        p = f'{BASIS}buerger/{z["id"]}/lichtbild'
        h += (f'<form id="lb-form" method="post" action="{p}" enctype="multipart/form-data">{amt.csrf_feld(request)}'
              '<input type="file" name="bild" accept="image/jpeg,image/png,image/webp" required>'
              '<img id="lb-vorschau" alt="" hidden>'
              f'<div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("camera")}{"Lichtbild ersetzen" if r else "Lichtbild hochladen"}</button></div>'
              '<p class="az" style="margin-top:6px">Wird automatisch auf Passbildformat (35 × 45) zugeschnitten. Das Gesicht sollte mittig sein.</p></form>')
        if r:
            h += (f'<form method="post" action="{p}">{amt.csrf_feld(request)}<input type="hidden" name="loeschen" value="1">'
                  f'<div class="aktionen"><button class="btn zweit" type="submit">{amt.ic("x")}Lichtbild entfernen</button></div></form>')
        h += JS
    return h + '</div></div>'


def registrieren(app):
    app["db"].executescript(SCHEMA)
    app["db"].commit()
    amt.ICONS.setdefault("camera", '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>'
                                   '<circle cx="12" cy="13" r="3"/>')
    app.router.add_post(BASIS + "buerger/{id}/lichtbild", hochladen)
    app.router.add_get(BASIS + "lichtbild/{id}.jpg", anzeigen)
