"""Remplacement atomique d'un fichier, tolérant aux verrous brefs de Windows.

Sous Windows, `os.replace` échoue avec `PermissionError` (WinError 5 ou 32)
tant qu'un autre processus tient la cible ouverte sans `FILE_SHARE_DELETE` :
antivirus ou indexeur qui inspecte un fichier fraîchement écrit, lecteur qui
sonde au même instant. Le verrou dure quelques millisecondes ; on réessaie
donc, avec un délai croissant et borné, puis on relaie l'erreur.

Jamais de repli par écriture en place : un profil biométrique ou un modèle
à moitié écrit serait pire qu'une erreur claire. L'appelant garde son
fichier temporaire et décide quoi en faire (le supprimer, lever une erreur
codée).
"""

from __future__ import annotations

import os
from pathlib import Path
import time

#: Tentatives au plus, et délai initial doublé à chaque échec, plafonné :
#: au pire ≈ 1 s d'attente cumulée, invisible pour un enrôlement ou un
#: téléchargement, et bien plus long que le verrou d'un antivirus.
REPLACE_ATTEMPTS = 8
REPLACE_BACKOFF_S = 0.02
REPLACE_BACKOFF_MAX_S = 0.25


def replace_with_retry(source: Path, target: Path) -> None:
    """`os.replace(source, target)`, réessayé tant que Windows refuse l'accès.

    Seule `PermissionError` est réessayée ; toute autre `OSError` part
    aussitôt. Après la dernière tentative, la `PermissionError` est relayée
    telle quelle : `source` existe encore, `target` n'a pas changé.
    """

    delay = REPLACE_BACKOFF_S
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= REPLACE_ATTEMPTS:
                raise
            time.sleep(delay)
            delay = min(REPLACE_BACKOFF_MAX_S, delay * 2)
