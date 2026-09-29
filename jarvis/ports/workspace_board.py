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


class BoardStoreError(RuntimeError):
    """Une ligne stockée est illisible ou contredit ses colonnes clés (Slice 02).

    Distinct de `BoardError` (une demande refusée par une règle) : c'est un
    fichier abîmé, rendu 500 par le protocole et jamais « réparé » par le
    magasin, qui est un état canonique.
    """

    #: Code stable rendu par le protocole (500).
    code = "board_store_unreadable"

    def __init__(self, table: str, key: str, reason: str) -> None:
        super().__init__(f"{table} row {key!r} is unreadable: {reason}")
        self.table = table
        self.key = key


class BoardStoreUnavailable(BoardStoreError):
    """SQLite a refusé l'opération (`sqlite3.Error` : base verrouillée, E/S).

    Un dépôt déjà fermé n'arrive pas ici : `SQLiteStateRepository` lève
    `RuntimeError` (« state repository is not initialized ») avant toute
    requête SQLite, et cette erreur remonte telle quelle.

    Levée par l'adaptateur à la place de toute `sqlite3.Error` qui n'est pas
    déjà une règle métier (`BoardError`) : les appelants n'ont qu'une famille
    d'échecs de stockage à attraper, et la cause SQLite reste dans le message.
    """

    code = "board_store_failed"

    def __init__(self, operation: str, reason: str) -> None:
        RuntimeError.__init__(self, f"board store {operation} failed: {reason}")
        self.table = "board_store"
        self.key = operation


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

    Le dépôt ne décide rien : la migration vers le Board `default`
    (`ensure_default`, 06 section H) et toutes les gardes appartiennent à
    `BoardService` (`jarvis/core/board_service.py`), qui n'appelle ce port
    qu'avec des valeurs déjà produites par les transitions du domaine.
    """

    async def get_board(self, board_id: str) -> Board | None: ...

    async def list_boards(self, *, include_archived: bool = False) -> Sequence[Board]: ...

    async def save_board(self, board: Board) -> None: ...

    async def insert_board_if_empty(self, board: Board) -> bool:
        """Insère `board` seulement si aucun Board n'existe, atomiquement (Slice 02).

        Clé d'idempotence de la migration vers le Board `default` (06 section
        H) : rend vrai si cet appel l'a inséré.
        """
        ...

    async def get_session(self, jarvis_session_id: str) -> JarvisSession | None: ...

    async def current_session(self) -> JarvisSession | None:
        """La Session ouverte, s'il y en a une (au plus une)."""
        ...

    async def save_session(self, session: JarvisSession) -> None: ...

    async def list_sessions(self, *, limit: int) -> Sequence[JarvisSession]:
        """Historique des Sessions, la plus récente d'abord, au plus `limit` (`GET /v1/sessions`)."""
        ...

    async def list_bindings(self, jarvis_session_id: str) -> Sequence[BoardConversationBinding]: ...

    async def save_binding(self, binding: BoardConversationBinding) -> None: ...

    async def binding_by_conversation(self, conversation_id: str) -> BoardConversationBinding | None:
        """La liaison qui porte cette conversation Core (routage, porte de parole, attribution d'alertes)."""
        ...

    async def list_live_bindings(self) -> Sequence[BoardConversationBinding]:
        """Liaisons `foreground` ou `background_running`, **toutes Sessions confondues**.

        Pour la suspension automatique et la remise à zéro au redémarrage du
        Control Center : un CLI d'une Session close peut encore tourner.
        """
        ...

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
