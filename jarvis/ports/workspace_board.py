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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from jarvis.domain.workspace_board import Board, BoardConversationBinding, BrainLifecycle, JarvisSession

if TYPE_CHECKING:  # type only: the Board port does not depend on the Context domain at runtime
    from jarvis.domain.session_activity import ActivityDraft
    from jarvis.domain.session_context import SessionContext


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

    async def list_sessions(self, *, limit: int, before: JarvisSession | None = None) -> Sequence[JarvisSession]:
        """Historique des Sessions, la plus récente d'abord, au plus `limit` (`GET /v1/sessions`).

        `before` : dernière Session de la page précédente (pagination par clé
        `(started_at, jarvis_session_id)`, inspection du workspace)."""
        ...

    async def list_bindings(self, jarvis_session_id: str) -> Sequence[BoardConversationBinding]: ...

    async def list_bindings_of_board(self, board_id: str, *, limit: int) -> Sequence[BoardConversationBinding]:
        """Liaisons d'un Board dans toutes les Sessions, la plus récente d'abord, au plus `limit`."""
        ...

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
        contexts: Sequence[SessionContext] = (),
        activity: Sequence[ActivityDraft] = (),
    ) -> None:
        """Écrit atomiquement les Sessions, Boards, Contexts de Session et liaisons modifiés.

        `contexts` (Slice 03 session-context) : Contexts endormis et nés avec la
        transition (nouvelle Session) ; refus du domaine `SessionContextError`.
        `activity` (Slice 04) : événements du ledger d'activité de la transition,
        ajoutés **dans la même transaction**, après les lignes.
        """
        ...


#: `host_state` porté par le `BoardError` d'une activation ratée : l'hôte n'a
#: rien changé (refus codé, hôte injoignable), ou on ne sait pas (délai,
#: réponse illisible : il a peut-être basculé, Core rétablit alors l'ancien).
HOST_UNCHANGED = "unchanged"
HOST_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BoardActivation:
    """Réponse de l'hôte à une activation (Slice 04b) : ce que Core enregistre.

    `agent_cli` / `agent_session_id` : le CLI réel de la liaison activée et
    son identifiant de reprise (`None` tant qu'aucun tour n'a tourné).
    `previous_conversation_id` / `previous_lifecycle` : l'agent rétrogradé par
    cette activation et ce qu'il est devenu (`background_running` s'il
    travaille, `suspended` sinon) ; `None` quand rien n'a été rétrogradé
    (cible déjà foreground, ou foreground encore non lié).
    """

    agent_cli: str
    agent_session_id: str | None = None
    previous_conversation_id: str | None = None
    previous_lifecycle: BrainLifecycle | None = None


class BoardBrainHost(Protocol):
    """Hôte des processus d'agent, un par liaison (06 section B).

    Aucune méthode n'annule du travail : l'activation rétrograde l'ancien
    foreground **dans le même geste** (suspendu s'il est inactif, gardé vivant
    `background_running` s'il a des sous-agents). Il n'y a donc pas de
    `demote` séparé : Core ne retire jamais la parole à un agent sans en
    nommer un autre. Implémentation : `ControlCenterBoardHost`
    (`jarvis/adapters/control_center_brain.py`), qui appelle
    `POST /api/agent/bindings/activate`.
    """

    async def activate(self, binding: BoardConversationBinding) -> BoardActivation:
        """Rend l'agent de `binding` foreground (démarre, reprend ou garde son CLI).

        Lève `BoardError(board_activation_failed)` (ou le refus de l'hôte,
        `session_closed`, `invalid_binding`) en cas d'échec : Core abandonne
        alors la bascule sans rien valider.
        """
        ...
