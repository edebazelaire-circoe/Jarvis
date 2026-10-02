"""Lien Board-artifact (handoff board-memory-workspace-inspector, Slice 02, R2).

« Cet Artifact appartient à / sert ce Board. » Relation canonique entre un
Board et un Artifact du registre (table `board_artifact_links`, migration v8
de `jarvis.sqlite3`) ; `Board.artifact_refs` reste une liste de références
opaques héritée, sans lien avec cette table.

Deux origines :

- `active_board` : posé par le magasin à la création d'un Artifact, dans la
  même transaction, vers le Board actif de la Session ouverte ;
- `explicit` : lien sémantique demandé (UI, MCP, Slice 05).

Pur : aucune E/S. Contrat : `docs/artifacts.md` › *Board links*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from jarvis.domain._checks import check_aware, preview
from jarvis.domain.artifacts import check_artifact_id
from jarvis.domain.workspace_board import BoardError, BoardErrorCode

#: Liens rendus au plus par lecture (un Board peut en avoir davantage : pagination).
MAX_BOARD_LINK_LIMIT = 500
DEFAULT_BOARD_LINK_LIMIT = 100


class BoardArtifactLinkOrigin(StrEnum):
    #: Lien automatique à la création de l'Artifact (Board actif de la Session ouverte).
    ACTIVE_BOARD = "active_board"
    #: Lien demandé explicitement.
    EXPLICIT = "explicit"


def check_link_board_id(board_id: object) -> None:
    """Identifiant de Board non vide et imprimable ; l'existence est vérifiée par le magasin."""

    if not isinstance(board_id, str) or not board_id or len(board_id) > 128 or not board_id.isprintable():
        raise BoardError(BoardErrorCode.INVALID_BOARD, f"board_id must be a short printable id, got {preview(board_id)}")


def check_link_limit(limit: object) -> int:
    if type(limit) is not int or not 1 <= limit <= MAX_BOARD_LINK_LIMIT:
        raise BoardError(BoardErrorCode.INVALID_BOARD, f"limit must be in 1..{MAX_BOARD_LINK_LIMIT}, got {preview(limit)}")
    return limit


@dataclass(frozen=True, slots=True)
class BoardArtifactLink:
    board_id: str
    artifact_id: str
    origin: BoardArtifactLinkOrigin
    linked_at: datetime

    def __post_init__(self) -> None:
        check_link_board_id(self.board_id)
        check_artifact_id(self.artifact_id)
        if not isinstance(self.origin, BoardArtifactLinkOrigin):
            raise BoardError(BoardErrorCode.INVALID_BOARD, f"origin must be a BoardArtifactLinkOrigin, got "
                                                           f"{preview(self.origin)}")
        check_aware(lambda m: BoardError(BoardErrorCode.INVALID_BOARD, m), "linked_at", self.linked_at)

    def to_payload(self) -> dict[str, str]:
        return {"board_id": self.board_id, "artifact_id": self.artifact_id, "origin": self.origin.value,
                "linked_at": self.linked_at.isoformat()}
