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

Emplacement : sous le dépôt (`<dépôt>/retours-utilisateur`) pour le JARVIS
quotidien, qui ne fixe pas `JARVIS_DATA_ROOT` ; quand `JARVIS_DATA_ROOT` est
fixé (bac à sable, worktree, essai isolé), sous cette racine
(`<JARVIS_DATA_ROOT>/retours-utilisateur`), pour qu'un démarrage isolé ne crée
jamais rien dans l'arbre de travail du dépôt. Produit installé (`jarvis/installation.py`) :
toujours sous la racine de données du produit (`%LOCALAPPDATA%/CIRCOE/Jarvis/data/retours-utilisateur`),
jamais dans le dossier du programme.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
import time

from jarvis.data_root import DATA_ROOT_ENV, resolve_data_root
from jarvis.installation import PRODUCT_HOME_LABEL, detect_installation

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


def feedback_base(project_root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Racine qui porte `retours-utilisateur` : `JARVIS_DATA_ROOT` s'il est fixé, sinon la racine de données du
    produit installé, sinon le dépôt (emplacement historique du développement)."""

    env = os.environ if environ is None else environ
    raw = env.get(DATA_ROOT_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    if detect_installation(env).installed:
        return resolve_data_root(env)
    return project_root


def feedback_session_dir(project_root: Path, *, now: float | None = None) -> Path:
    """Créer le dossier de retours de la session et l'exposer à l'environnement."""

    directory = feedback_base(project_root) / FEEDBACK_ROOT_NAME / str(launched_at(now))
    directory.mkdir(parents=True, exist_ok=True)
    os.environ[FEEDBACK_DIR_ENV] = str(directory)
    return directory


def feedback_dir_label(directory: Path, environ: Mapping[str, str] | None = None) -> str:
    """Étiquette du dossier pour le journal, sans chemin d'utilisateur (comme le bloc `installation` de `/v1/health`).

    `%LOCALAPPDATA%/CIRCOE/Jarvis/data` (produit installé), `<JARVIS_DATA_ROOT>` ou `<dépôt>`, suivi de
    `retours-utilisateur/<lancement>`.
    """

    env = os.environ if environ is None else environ
    if env.get(DATA_ROOT_ENV, "").strip():
        base = f"<{DATA_ROOT_ENV}>"
    elif detect_installation(env).installed:
        base = PRODUCT_HOME_LABEL + "\\data"
    else:
        base = "<dépôt>"
    return f"{base}/{FEEDBACK_ROOT_NAME}/{Path(directory).name}"
