"""Ports des Boards de travail et des Sessions (handoff board-session, Slice 01).

Deux coutures, sans implémentation ici :

- `BoardRepository` : persistance durable des Boards, Sessions et liaisons,
  possédée par Core (`jarvis.sqlite3`, migration v3 — Slice 02) ;
- `BoardBrainHost` : ce que Core demande au Control Center, qui possède les
  processus d'agent (`BoardBrainPool`, Slice 04a). Core décide ; l'hôte
  exécute et rapporte l'identifiant de reprise.

Les valeurs échangées sont celles de `jarvis.domain.workspace_board` ; les
règles (Session close immuable, un seul foreground, Board actif non
archivable) sont appliquées par les fonctions de transition du domaine avant
tout appel à ces ports. Contrat canonique : `docs/boards.md`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jarvis.domain.workspace_board import Board, BoardConversationBinding, JarvisSession


class BoardRepository(Protocol):
    """Magasin durable des Boards, Sessions et liaisons.

    Lecture : `None` quand l'objet n'existe pas ; c'est l'appelant qui lève
    `board_not_found` / `session_not_found`. Écriture : `save_*` remplace la
    ligne par sa clé. `commit_switch` écrit en **une seule transaction** tout ce
    qu'une bascule ou une nouvelle Session change (06 section D) : soit tout,
    soit rien.

    Une Session close ne doit jamais être réécrite : l'implémentation refuse
    une sauvegarde qui toucherait une ligne déjà `closed` (garde SQL
    `WHERE status='open'`) et lève `BoardError(session_closed)`.
    """

    async def get_board(self, board_id: str) -> Board | None: ...

    async def list_boards(self, *, include_archived: bool = False) -> Sequence[Board]: ...

    async def save_board(self, board: Board) -> None: ...

    async def get_session(self, jarvis_session_id: str) -> JarvisSession | None: ...

    async def current_session(self) -> JarvisSession | None:
        """La Session ouverte, s'il y en a une (au plus une)."""
        ...

    async def save_session(self, session: JarvisSession) -> None: ...

    async def list_bindings(self, jarvis_session_id: str) -> Sequence[BoardConversationBinding]: ...

    async def save_binding(self, binding: BoardConversationBinding) -> None: ...

    async def commit_switch(
        self,
        *,
        sessions: Sequence[JarvisSession],
        boards: Sequence[Board],
        bindings: Sequence[BoardConversationBinding],
    ) -> None:
        """Écrit atomiquement les Sessions, Boards et liaisons modifiés."""
        ...


class BoardBrainHost(Protocol):
    """Hôte des processus d'agent, un par liaison (06 section B).

    Aucune de ces méthodes n'annule du travail : rétrograder un agent qui a
    des sous-agents en cours le garde vivant (`background_running`).
    """

    async def activate(self, binding: BoardConversationBinding) -> str | None:
        """Rend l'agent de `binding` foreground (démarre, reprend ou garde son CLI).

        Rend l'`agent_session_id` à enregistrer sur la liaison, ou `None` si
        encore inconnu. Lève en cas d'échec : Core abandonne alors la bascule
        sans rien valider.
        """
        ...

    async def demote(self, binding: BoardConversationBinding) -> None:
        """Retire l'autorité de parole ; suspend si inactif, garde si travail en cours."""
        ...
