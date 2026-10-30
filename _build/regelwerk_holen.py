"""Liest das Regelwerk aus dem Informationskanal des Discord-Servers und schreibt _build/regelwerk.json.

    python _build/regelwerk_holen.py

Quelle sind die Abschnitte „Richtlinien des Servers“ und „Zu welchem Zeitpunkt gilt die Rolle?“
(Bot-Nachrichten, Texte gepflegt in imperium-bot/info_kanal.py). Danach site.py neu bauen.
Braucht DISCORD_TOKEN in /root/.env.
"""
import json
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "regelwerk.json")
GUILD_ID = 1522685223014371479
INFO_KANAL = 1523117025952661597
TITEL_RICHTLINIEN = "Richtlinien des Servers"
TITEL_ROLLENSPIEL = "Zu welchem Zeitpunkt gilt die Rolle?"


def token():
    if os.environ.get("DISCORD_TOKEN"):
        return os.environ["DISCORD_TOKEN"]
    with open("/root/.env", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("DISCORD_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("DISCORD_TOKEN fehlt")


def api(path):
    req = urllib.request.Request("https://discord.com/api/v10" + path,
                                 headers={"Authorization": "Bot " + token(), "User-Agent": "DiscordBot (imperium, 1)"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    kanaele = {c["id"]: c["name"] for c in api(f"/guilds/{GUILD_ID}/channels")}

    def klartext(t):
        # Kanal-Erwähnungen <#id> → Kanalname ohne Emoji-Präfix („💬｜klatsch-und-tratsch“ → „klatsch-und-tratsch“)
        def kanal(m):
            name = kanaele.get(m.group(1), "")
            return "#" + name.split("｜", 1)[-1]
        return re.sub(r"<#(\d+)>", kanal, t).strip()

    embeds = {}
    for m in api(f"/channels/{INFO_KANAL}/messages?limit=50"):
        for e in m["embeds"]:
            if e.get("title"):
                embeds[e["title"]] = (m, e)
    if TITEL_RICHTLINIEN not in embeds or TITEL_ROLLENSPIEL not in embeds:
        raise SystemExit("Abschnitte im Informationskanal nicht gefunden")

    m, e = embeds[TITEL_RICHTLINIEN]
    regeln = []
    for absatz in e["description"].split("\n\n"):
        hit = re.match(r"\*\*(\d+)\.\*\*\s*(.*)", absatz.strip(), re.S)
        if hit:
            regeln.append({"n": hit.group(1), "text": klartext(hit.group(2))})
    m2, e2 = embeds[TITEL_ROLLENSPIEL]
    daten = {
        "quelle": f"https://discord.com/channels/{GUILD_ID}/{INFO_KANAL}",
        "stand": max(x["edited_timestamp"] or x["timestamp"] for x in (m, m2))[:10],
        "richtlinien": {"titel": e["title"], "regeln": regeln},
        "rollenspiel": {
            "titel": e2["title"],
            "herausgeber": (e2.get("author") or {}).get("name", ""),
            "absaetze": [klartext(a) for a in e2["description"].split("\n\n")],
            "felder": [{"name": f["name"], "text": klartext(f["value"])} for f in e2.get("fields", [])],
        },
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(daten, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"{len(regeln)} Regeln, {len(daten['rollenspiel']['felder'])} Felder → {OUT}")


if __name__ == "__main__":
    main()
