"""Dossier de retours utilisateur de la session JARVIS en cours.

Les retours constatés en usage réel sont rangés par lancement de JARVIS :
`retours-utilisateur/<lancement>/`, où `<lancement>` est l'heure de démarrage
du Control Center en secondes Unix. Les dossiers se trient donc d'eux-mêmes,
et les fiches d'une même session restent ensemble.

Le Control Center fixe ce dossier au démarrage et le publie dans
`JARVIS_FEEDBACK_DIR` : le brain Claude et ses sous-agents en héritent, et la
consigne système leur dit d'écrire là. Une valeur déjà présente dans
l'environnement est respectée, pour qu'un lanceur commun impose la même
session à tous ses processus.
"""

from __future__ import annotations

import os
from pathlib import Path
import time

FEEDBACK_ROOT_NAME = "retours-utilisateur"
LAUNCHED_AT_ENV = "JARVIS_LAUNCHED_AT"
FEEDBACK_DIR_ENV = "JARVIS_FEEDBACK_DIR"


def launched_at(now: float | None = None) -> int:
    """Heure de lancement de la session, en secondes Unix, fixée une fois pour toutes."""

    raw = os.environ.get(LAUNCHED_AT_ENV, "").strip()
    if raw.isdigit():
        return int(raw)
    stamp = int(time.time() if now is None else now)
    os.environ[LAUNCHED_AT_ENV] = str(stamp)
    return stamp


def feedback_session_dir(project_root: Path, *, now: float | None = None) -> Path:
    """Créer le dossier de retours de la session et l'exposer à l'environnement."""

    directory = project_root / FEEDBACK_ROOT_NAME / str(launched_at(now))
    directory.mkdir(parents=True, exist_ok=True)
    os.environ[FEEDBACK_DIR_ENV] = str(directory)
    return directory
