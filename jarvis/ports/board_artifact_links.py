"""Port des liens Board-artifact (handoff board-memory-workspace-inspector, Slice 02, R2).

Table `board_artifact_links` (v8) sur la connexion partagée de l'état
(adaptateur `jarvis.adapters.sqlite_board_artifact_links`). Le lien
automatique `active_board` n'y passe pas : il est écrit par
`ArtifactRepository.create_artifact`, dans la transaction de l'Artifact.
Contrat : `docs/artifacts.md` › *Board links*.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from jarvis.domain.board_artifact_links import BoardArtifactLink, BoardArtifactLinkOrigin
from jarvis.domain.session_activity import ActivityDraft, ActivityEvent


class BoardArtifactLinkStore(Protocol):
    """Erreurs de règle : `BoardError(board_not_found | invalid_board)`, `ArtifactError(artifact_not_found)`.
    Stockage : `BoardStoreError` / `BoardStoreUnavailable`."""

    async def link(self, board_id: str, artifact_id: str, *, now: datetime,
                   origin: BoardArtifactLinkOrigin = BoardArtifactLinkOrigin.EXPLICIT,
                   activity: Sequence[ActivityDraft] = ()) -> tuple[BoardArtifactLink, bool, tuple[ActivityEvent, ...]]:
        """Pose le lien (idempotent) ; rend `(lien, créé, événements)`. Un lien existant garde son
        origine et sa date, et `activity` n'est alors **pas** écrit (rien n'a changé)."""
        ...

    async def unlink(self, board_id: str, artifact_id: str, *,
                     activity: Sequence[ActivityDraft] = ()) -> tuple[bool, tuple[ActivityEvent, ...]]:
        """Retire le lien ; `(False, ())` s'il n'existait pas (rien n'est écrit)."""
        ...

    async def links_of_board(self, board_id: str, *, limit: int,
                             before: BoardArtifactLink | None = None) -> Sequence[BoardArtifactLink]:
        """Liens du Board, du plus récent au plus ancien ; `before` : dernier lien de la page précédente."""
        ...

    async def count_links(self, board_id: str) -> int: ...

    async def boards_of_artifact(self, artifact_id: str, *, limit: int) -> Sequence[BoardArtifactLink]:
        """Liens d'un Artifact, du plus ancien au plus récent."""
        ...
