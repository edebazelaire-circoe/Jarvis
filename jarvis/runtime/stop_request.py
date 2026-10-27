"""Demande d'arrêt propre d'un rôle lancé par le lanceur du produit (Slice 07, `docs/product-install.md` › *Launcher*).

« Quitter JARVIS » ne tue plus Core ni le Control Center d'emblée (revue m6) : le lanceur donne à chacun, par
`JARVIS_STOP_REQUEST_FILE`, le chemin d'un fichier de demande ; le rôle le surveille et, quand il apparaît, sort de sa
boucle principale par son chemin normal (`finally` : serveur arrêté, Core arrêté, sessions fermées, jeton effacé).
Le lanceur attend `STOP_GRACE_S`, puis seulement arrête de force (`terminate`, puis le Job Object).

Sans la variable (développement, `supervisor_v2.py`), rien ne change : le rôle attend comme avant.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping
import os
from pathlib import Path
from typing import Any

STOP_REQUEST_ENV = "JARVIS_STOP_REQUEST_FILE"
POLL_S = 0.5


def stop_request_path(environ: Mapping[str, str] | None = None) -> Path | None:
    raw = str((os.environ if environ is None else environ).get(STOP_REQUEST_ENV) or "").strip()
    return Path(raw) if raw else None


async def wait_for_stop_request(path: Path, *, poll_s: float = POLL_S) -> None:
    """Rend la main quand le fichier de demande existe (le lanceur l'écrit ; il l'efface avant chaque lancement)."""

    while not path.exists():
        await asyncio.sleep(poll_s)


async def run_until_stop_requested(main: Awaitable[Any], path: Path | None, *, poll_s: float = POLL_S) -> bool:
    """Attend `main` ; avec `path`, s'arrête aussi à la demande. Vrai si l'arrêt a été demandé. Une exception de `main`
    remonte telle quelle ; la tâche restante est annulée et attendue (aucune tâche orpheline)."""

    work = asyncio.ensure_future(main)
    if path is None:
        await work
        return False
    watcher = asyncio.ensure_future(wait_for_stop_request(path, poll_s=poll_s))
    try:
        done, _pending = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (work, watcher):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, watcher, return_exceptions=True)
    if work in done:
        work.result()  # re-raises the main loop's own failure
        return False
    return True
