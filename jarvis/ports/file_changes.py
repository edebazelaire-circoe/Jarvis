"""Port : prévenir quand un fichier change, sans sondage."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Protocol

ChangeCallback = Callable[[str], None]


def normalize(path: str) -> str:
    """Forme comparable d'un chemin : absolu, séparateurs et casse du système."""

    return os.path.normcase(os.path.abspath(path))


class FileChangeNotifierPort(Protocol):
    """Surveille des dossiers ; appelle `callback(chemin normalisé)` dans la boucle asyncio donnée."""

    def watch(self, directory: str) -> bool: ...

    def keep_only(self, directories: set[str]) -> None: ...

    def close(self) -> None: ...


NotifierFactory = Callable[[asyncio.AbstractEventLoop, ChangeCallback], FileChangeNotifierPort]
