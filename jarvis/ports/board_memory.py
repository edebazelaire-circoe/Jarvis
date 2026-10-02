"""Port du magasin de mémoire de Board sur disque (handoff board-memory-workspace-inspector, Slice 02).

Adaptateur : `jarvis.adapters.board_memory_store.FileBoardMemoryStore`, sous
`<data_root>/boards/<board_id>/memory/`. Les chemins reçus sont des
`BoardMemoryPath` (Slice 01) ; les chemins rendus sont **relatifs** à
`memory/`, jamais absolus. Le magasin ne connaît pas les Boards : existence
et archivage (`board_not_found`, `board_archived`) sont vérifiés par le
service (Slices 04-05). Contrat : `docs/boards.md` › *Board memory*.

Refus d'une demande : `BoardMemoryError` (codes stables de
`jarvis.domain.board_memory`). Disque ou racine en défaut :
`BoardMemoryUnavailable` (500).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from jarvis.domain.board_memory import BoardMemoryPath

#: La racine `boards/<id>/memory` ou un dossier au-dessus est un lien, une
#: jonction ou un point d'analyse : rien n'est lu ni écrit à travers.
MEMORY_STORE_UNSAFE = "board_memory_unsafe"
#: Le système de fichiers a refusé (droits, verrou, disque plein...).
MEMORY_STORE_FAILED = "board_memory_failed"


class BoardMemoryUnavailable(RuntimeError):
    """Panne du magasin, pas une demande refusée ; la cause du système reste dans le message."""

    status = 500

    def __init__(self, code: str, path: str, reason: str) -> None:
        super().__init__(f"{code}: {path}: {reason}")
        self.code = code
        self.path = path


class MemoryEntryKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    #: Lien, jonction ou point d'analyse rangé là par un agent : listé, jamais suivi.
    LINK = "link"


class WriteMode(StrEnum):
    #: Refusé (`memory_exists`) si le chemin est occupé.
    CREATE = "create"
    #: Crée ou remplace le fichier entier.
    REPLACE = "replace"
    #: Ajoute à la fin (crée le fichier s'il manque).
    APPEND = "append"


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    #: Relatif à `memory/` (POSIX).
    path: str
    kind: MemoryEntryKind
    #: Octets d'un fichier ; `None` pour un dossier ou un lien.
    size: int | None
    modified_at: datetime
    #: Profondeur sous le dossier listé (1 = enfant direct) ; 0 hors d'un arbre.
    depth: int = 0


@dataclass(frozen=True, slots=True)
class MemoryTree:
    #: Dossier listé, relatif (`""` : la racine de `memory/`).
    path: str
    #: Parcours en profondeur, noms triés (casse ignorée) à chaque niveau.
    entries: tuple[MemoryEntry, ...]
    #: Vrai si la borne d'entrées a coupé la liste.
    truncated: bool
    #: Entrées non listées : nom qu'aucun `BoardMemoryPath` ne peut désigner, ou temporaire d'écriture.
    skipped: int = 0


@dataclass(frozen=True, slots=True)
class MemoryText:
    path: str
    text: str
    #: Octet de départ de `text` dans le fichier.
    offset: int
    #: Octet suivant `text` ; égal à `size` en fin de fichier.
    next_offset: int
    size: int
    #: SHA-256 hexadécimal du fichier entier (pour une écriture conditionnelle).
    sha256: str

    @property
    def eof(self) -> bool:
        return self.next_offset >= self.size


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    entry: MemoryEntry
    sha256: str
    #: Vrai si le fichier n'existait pas.
    created: bool


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    path: str
    #: Numéro de ligne (1 = première).
    line: int
    #: La ligne, bornée.
    preview: str


@dataclass(frozen=True, slots=True)
class MemorySearch:
    matches: tuple[MemoryMatch, ...]
    files_scanned: int
    #: Fichiers non lus : binaires, pas en UTF-8, ou trop gros.
    files_skipped: int
    #: Vrai si une borne (correspondances, fichiers, octets) a arrêté la recherche.
    truncated: bool


class BoardMemoryStore(Protocol):
    def memory_root_locator(self, board_id: str) -> str:
        """`boards/<board_id>/memory`, relatif à la racine de données ; aucun accès disque."""
        ...

    def tree(self, board_id: str, path: BoardMemoryPath | None = None, *, depth: int = 2,
             max_entries: int = 200) -> MemoryTree: ...

    def stat(self, board_id: str, path: BoardMemoryPath) -> MemoryEntry: ...

    def read(self, board_id: str, path: BoardMemoryPath, *, offset: int = 0, max_bytes: int = ...) -> MemoryText: ...

    def search(self, board_id: str, query: str, *, path: BoardMemoryPath | None = None,
               limit: int = 50) -> MemorySearch: ...

    def write(self, board_id: str, path: BoardMemoryPath, content: str, *, mode: WriteMode,
              expected_sha256: str | None = None) -> MemoryWrite: ...

    def mkdir(self, board_id: str, path: BoardMemoryPath) -> tuple[MemoryEntry, bool]: ...

    def move(self, board_id: str, source: BoardMemoryPath, target: BoardMemoryPath) -> MemoryEntry: ...

    def delete(self, board_id: str, path: BoardMemoryPath, *, recursive: bool = False) -> int:
        """Retire le fichier ou le dossier ; rend le nombre d'entrées retirées."""
        ...
