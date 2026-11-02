"""Aufrufe der Build- und Deploy-Skripte der Website (laufen mit der Python-Umgebung des Bots)."""
import asyncio
import os

import config


async def ausfuehren(*befehl):
    """Startet einen Befehl im Website-Ordner; gibt (ok, letzte Ausgabezeilen) zurück."""
    umgebung = dict(os.environ, PATH=config.VENV_BIN + os.pathsep + os.environ.get("PATH", ""))
    proc = await asyncio.create_subprocess_exec(
        *befehl, cwd=config.WEBSITE_DIR, env=umgebung,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    ausgabe, _ = await proc.communicate()
    text = ausgabe.decode("utf-8", "replace").strip()
    return proc.returncode == 0, "\n".join(text.splitlines()[-15:])


async def regelwerk_holen():
    return await ausfuehren("python3", "_build/regelwerk_holen.py")


async def gesetzblatt_aufnehmen(ordner):
    return await ausfuehren("python3", "_build/gesetzblatt.py", ordner)


async def deploy():
    return await ausfuehren("bash", "deploy.sh")
