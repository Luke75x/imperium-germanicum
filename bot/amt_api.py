"""Meldungen an die Amtsseite der Reichsbehörden (Imperium-Dienst, /informationen/die-reichsbehoerden/intern/).
Fehler werden nur protokolliert: Der Dienst darf Einreise und Einbürgerung nie blockieren."""
import logging

import aiohttp

import config

log = logging.getLogger("imperium-bot.amt")
BASIS = "http://127.0.0.1:8090/intern-api/amt/"


async def melden(pfad: str, daten: dict) -> bool:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.post(BASIS + pfad, json=daten, headers={"X-Bot-Token": config.env("DISCORD_TOKEN")}) as r:
                if r.status != 200:
                    raise aiohttp.ClientError(f"HTTP {r.status}")
        return True
    except (aiohttp.ClientError, ValueError, OSError):
        log.exception("Amtsseite nicht erreichbar (%s)", pfad)
        return False
