"""Nimmt einen Eintrag aus dem Reichsgesetzblatt (Discord-Forum) in die Seite „Neue Erlasse und Gesetze“ auf.

Aufruf (vom Bot, nachdem der Kaiser per DM bestätigt hat):
    python _build/gesetzblatt.py <ordner>

<ordner> enthält eintrag.json ({id, titel, art, text, datum, dateien: [Dateiname], links: [URL]}) und die Dateien.
Die Dateien landen in assets/gesetzblatt/<id>/, die erste PDF-Seite (bzw. das erste Bild) wird Vorschaubild
(assets/img/original, danach bilder.py). Die Einträge stehen in _build/gesetzblatt.json, site.py zeigt sie
vor den älteren Erlassen. Erneuter Aufruf mit derselben id ersetzt den Eintrag.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "gesetzblatt.json")
BILDER = (".png", ".jpg", ".jpeg", ".webp")


def vorschau(eid, ordner, dateien):
    iid = "i" + hashlib.sha1(f"gesetzblatt-{eid}".encode()).hexdigest()[:16]
    ziel = os.path.join(ROOT, "assets", "img", "original")
    for name in os.listdir(ziel):
        if name.startswith(iid):
            os.remove(os.path.join(ziel, name))
    for stem in (f"{iid}-640.webp", f"{iid}-1280.webp"):
        if os.path.exists(os.path.join(ROOT, "assets", "img", stem)):
            os.remove(os.path.join(ROOT, "assets", "img", stem))
    for name in dateien:
        quelle = os.path.join(ordner, name)
        if name.lower().endswith(".pdf"):
            subprocess.run(["pdftoppm", "-png", "-f", "1", "-l", "1", "-scale-to", "1600", "-singlefile",
                            quelle, os.path.join(ziel, iid)], check=True)
            return iid
        if name.lower().endswith(BILDER):
            shutil.copy(quelle, os.path.join(ziel, iid + os.path.splitext(name)[1].lower()))
            return iid
    return None


def main(ordner):
    with open(os.path.join(ordner, "eintrag.json"), encoding="utf-8") as fh:
        e = json.load(fh)
    eid = str(e["id"])
    ablage = os.path.join(ROOT, "assets", "gesetzblatt", eid)
    shutil.rmtree(ablage, ignore_errors=True)
    os.makedirs(ablage)
    for name in e["dateien"]:
        shutil.copy(os.path.join(ordner, name), os.path.join(ablage, name))
    iid = vorschau(eid, ordner, e["dateien"])
    if iid:
        subprocess.run([sys.executable, os.path.join(HERE, "bilder.py")], check=True)

    eintraege = json.load(open(DATA, encoding="utf-8")) if os.path.exists(DATA) else []
    eintraege = [x for x in eintraege if x["id"] != eid]
    eintraege.append({"id": eid, "titel": e["titel"], "art": e["art"], "text": e.get("text", ""), "datum": e["datum"],
                      "dateien": [f"gesetzblatt/{eid}/{n}" for n in e["dateien"]], "links": e["links"], "vorschau": iid})
    eintraege.sort(key=lambda x: x["datum"])
    with open(DATA, "w", encoding="utf-8") as fh:
        json.dump(eintraege, fh, ensure_ascii=False, indent=1)
    print(f"Eintrag {eid} aufgenommen ({len(eintraege)} im Reichsgesetzblatt)")


if __name__ == "__main__":
    main(sys.argv[1])
