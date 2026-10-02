"""Contrat pur de la mémoire libre d'un Board (handoff board-memory-workspace-inspector, Slice 01).

La **mémoire de Board** est un dossier de fichiers libres que les agents
organisent eux-mêmes : aucun schéma interne imposé, aucun fichier obligatoire.
Seule convention : `summary.md` à la racine, s'il existe, est le condensé lu
à l'hydratation (Slice 03). Elle est distincte :

- des champs structurés du `Board` (`jarvis/domain/workspace_board.py`),
  métadonnées de gestion validées et bornées ;
- du `SessionContext` (`jarvis/domain/session_context.py`), espace cognitif de
  l'agent actif dans **une** Session ; la mémoire de Board survit aux Sessions.

Ce module fixe trois choses, sans aucune E/S (le disque : Slice 02) :

- l'emplacement, **relatif** à la racine de données et dérivé du seul
  `board_id` validé : `boards/<board_id>/memory` (`board_memory_root`). Un
  client ne passe jamais de chemin absolu ni de racine ;
- `BoardMemoryPath`, chemin POSIX relatif **dans** `memory/`, validé de sorte
  qu'aucune valeur acceptée ne sorte de la racine ni ne désigne deux fichiers
  différents selon le système ;
- les codes d'erreur stables des opérations de mémoire et leur statut HTTP.

Contrat : `docs/boards.md` › *Board memory*.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
import re
from types import MappingProxyType

from jarvis.domain._checks import check_prefixed_id, preview
from jarvis.domain.workspace_board import BOARD_ID_PREFIX, DEFAULT_BOARD_ID, BoardError, BoardErrorCode

#: Dossier des Boards sous la racine de données, puis dossier de la mémoire.
BOARDS_DIR = "boards"
MEMORY_DIR = "memory"
#: Condensé conventionnel de la mémoire (facultatif), lu par l'hydratation.
MEMORY_SUMMARY_NAME = "summary.md"
#: Longueur maximale d'un chemin relatif dans `memory/` (R4). Avec une racine
#: de données raisonnable, le chemin complet reste sous la limite Windows que
#: vérifie `safe_folders` au moment de l'E/S.
MAX_MEMORY_PATH_CHARS = 240
#: Octets lus ou écrits au plus par appel (R4).
MAX_MEMORY_IO_BYTES = 256 * 1024

# Noms réservés de Windows, avec ou sans extension, quelle que soit la casse :
# `nul.txt` ouvre le périphérique, pas un fichier.
_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"{dev}{n}" for dev in ("com", "lpt") for n in (*"123456789", "¹", "²", "³")}
)
# Interdits dans un nom Windows (en plus du NUL et des caractères de contrôle).
_FORBIDDEN_CHARS = frozenset('<>:"|?*')
_DRIVE = re.compile(r"[A-Za-z]:")
_ANY_SEPARATOR = re.compile(r"[/\\]")


class BoardMemoryErrorCode(StrEnum):
    """Motif stable d'un refus d'opération de mémoire ; voyage en HTTP/MCP.

    Les refus sur le Board lui-même restent des `BoardErrorCode`
    (`board_not_found`, `board_archived`, `invalid_board`).
    """

    #: Chemin mal formé : vide, segment vide ou `.`, antislash, caractère interdit
    #: ou de contrôle, nom réservé Windows, trop long, pas une chaîne.
    MEMORY_PATH_INVALID = "memory_path_invalid"
    #: Chemin qui sortirait de `memory/` : absolu, lecteur, UNC, segment `..`.
    MEMORY_PATH_ESCAPE = "memory_path_escape"
    MEMORY_NOT_FOUND = "memory_not_found"
    #: Création sur un chemin déjà occupé.
    MEMORY_EXISTS = "memory_exists"
    #: Écriture conditionnelle (`expected_sha256`) sur un fichier qui a changé,
    #: ou fichier là où un dossier est attendu (et inversement).
    MEMORY_CONFLICT = "memory_conflict"
    #: Lecture ou écriture au-delà de `MAX_MEMORY_IO_BYTES`.
    MEMORY_TOO_LARGE = "memory_too_large"
    #: Fichier binaire ou pas en UTF-8 : listé avec sa taille, jamais lu.
    MEMORY_NOT_TEXT = "memory_not_text"


#: Statut HTTP que les routes (Slice 04) rendent pour chaque code.
MEMORY_HTTP_STATUS: Mapping[BoardMemoryErrorCode, int] = MappingProxyType({
    BoardMemoryErrorCode.MEMORY_PATH_INVALID: 400,
    BoardMemoryErrorCode.MEMORY_PATH_ESCAPE: 400,
    BoardMemoryErrorCode.MEMORY_NOT_FOUND: 404,
    BoardMemoryErrorCode.MEMORY_EXISTS: 409,
    BoardMemoryErrorCode.MEMORY_CONFLICT: 409,
    BoardMemoryErrorCode.MEMORY_TOO_LARGE: 413,
    BoardMemoryErrorCode.MEMORY_NOT_TEXT: 415,
})


class BoardMemoryError(ValueError):
    """Refus nommé d'une opération de mémoire ; même forme que `BoardError`."""

    def __init__(self, code: BoardMemoryErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = BoardMemoryErrorCode(code)
        self.status = MEMORY_HTTP_STATUS[self.code]


def _invalid(message: str) -> BoardMemoryError:
    return BoardMemoryError(BoardMemoryErrorCode.MEMORY_PATH_INVALID, message)


def _escape(message: str) -> BoardMemoryError:
    return BoardMemoryError(BoardMemoryErrorCode.MEMORY_PATH_ESCAPE, message)


# ------------------------------------------------------------------ emplacement


def check_memory_board_id(board_id: object) -> None:
    """`default` ou `board_` + segment de chemin sûr ; `invalid_board` sinon.

    Plus strict que `Board` (qui accepte tout identifiant imprimable préfixé) :
    l'id devient un nom de dossier, il ne peut porter ni `/`, ni `..`, ni
    majuscule (NTFS ignore la casse).
    """

    if board_id == DEFAULT_BOARD_ID:
        return
    check_prefixed_id(lambda message: BoardError(BoardErrorCode.INVALID_BOARD, message),
                      "board_id", board_id, BOARD_ID_PREFIX)


def board_memory_root(board_id: str) -> PurePosixPath:
    """`boards/<board_id>/memory`, **relatif** à la racine de données ; l'adaptateur le joint."""

    check_memory_board_id(board_id)
    return PurePosixPath(BOARDS_DIR, board_id, MEMORY_DIR)


# ------------------------------------------------------------------ chemin


def _check_segment(segment: str, raw: str) -> None:
    if segment in ("", "."):
        raise _invalid(f"memory path has an empty or '.' segment: {preview(raw)}")
    if any(ch in _FORBIDDEN_CHARS or not ch.isprintable() for ch in segment):
        raise _invalid(f"memory path holds a control or forbidden character (<>:\"|?*): {preview(raw)}")
    # Windows retire point et espace finaux : `a.` et `a` seraient le même fichier.
    if segment != segment.strip() or segment.endswith("."):
        raise _invalid(f"memory path segment must not start or end with a space or end with '.': {preview(raw)}")
    if segment.split(".", 1)[0].casefold() in _RESERVED_STEMS:
        raise _invalid(f"memory path uses a reserved Windows name: {preview(raw)}")


@dataclass(frozen=True, slots=True)
class BoardMemoryPath:
    """Chemin POSIX relatif dans `memory/` d'un Board ; jamais la racine elle-même.

    `parse` est la seule entrée depuis le fil. Une valeur construite est sûre à
    joindre sous `board_memory_root` : pas de sortie, pas d'alias Windows.
    Les liens et jonctions sur disque restent le travail de `safe_folders`.
    """

    value: str

    def __post_init__(self) -> None:
        raw = self.value
        if not isinstance(raw, str):
            raise _invalid(f"memory path must be a string, got {preview(raw)}")
        if not raw:
            raise _invalid("memory path must not be empty")
        if len(raw) > MAX_MEMORY_PATH_CHARS:
            raise _invalid(f"memory path exceeds {MAX_MEMORY_PATH_CHARS} characters ({len(raw)})")
        # Sortie d'abord, quel que soit le séparateur : `..\x` ou `\\hôte` est une
        # tentative de sortie, pas une faute de frappe.
        if raw.startswith(("/", "\\")) or _DRIVE.match(raw):
            raise _escape(f"memory path must be relative to the Board memory, got {preview(raw)}")
        if ".." in _ANY_SEPARATOR.split(raw):
            raise _escape(f"memory path must not contain '..': {preview(raw)}")
        if "\\" in raw:
            raise _invalid(f"memory path uses '/' as separator, never a backslash: {preview(raw)}")
        for segment in raw.split("/"):
            _check_segment(segment, raw)

    @classmethod
    def parse(cls, raw: object) -> BoardMemoryPath:
        return cls(raw)  # type: ignore[arg-type]

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.value.split("/"))

    @property
    def name(self) -> str:
        return self.parts[-1]

    @property
    def parent(self) -> BoardMemoryPath | None:
        """Le dossier parent, ou `None` pour une entrée à la racine de `memory/`."""

        parts = self.parts
        return None if len(parts) == 1 else BoardMemoryPath("/".join(parts[:-1]))

    @property
    def is_summary(self) -> bool:
        return self.value == MEMORY_SUMMARY_NAME

    def locator(self, board_id: str) -> PurePosixPath:
        """`boards/<board_id>/memory/<path>`, relatif à la racine de données."""

        return board_memory_root(board_id).joinpath(*self.parts)

    def __str__(self) -> str:
        return self.value
