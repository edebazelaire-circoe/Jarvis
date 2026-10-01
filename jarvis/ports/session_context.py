"""Port du magasin des Contexts de Session (handoff session-context-recording, Slice 02).

Couture distincte de `BoardRepository` (`jarvis/ports/workspace_board.py`) :
un Context n'a aucune clé `board_id` (D06), et ce port reste petit. Même
fichier, même connexion et même verrou que les Boards
(`SQLiteStateRepository.run_serialized`), donc les deux magasins se
sérialisent l'un l'autre.

Les valeurs sont celles de `jarvis.domain.session_context` ; les règles (un
seul actif par Session ouverte, rien dans une Session close, adoption unique)
sont appliquées par les transitions du domaine **avant** l'appel, et le
fichier les garantit aussi (index uniques partiels, gardes SQL). Contrat :
`docs/session-context.md` › *Persistence*.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jarvis.domain.session_activity import ActivityDraft
from jarvis.domain.session_context import SessionContext
from jarvis.ports.workspace_board import BoardStoreError, BoardStoreUnavailable


class ContextStoreError(BoardStoreError):
    """Ligne `session_contexts` illisible, ou qui contredit ses colonnes clés.

    Sous-classe de `BoardStoreError` : un appelant qui attrape déjà les
    échecs du magasin des Boards (protocole, 500) attrape aussi celui-ci.
    Jamais « réparée » : la base est un état canonique.
    """

    code = "context_store_unreadable"


class ContextStoreUnavailable(BoardStoreUnavailable):
    """SQLite a refusé l'opération (verrou, E/S) ; la cause SQLite reste dans le message."""

    code = "context_store_failed"

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(operation, reason)
        # Même forme que `BoardStoreUnavailable`, nommée pour ce magasin.
        self.args = (f"context store {operation} failed: {reason}",)
        self.table = "session_contexts"


class ContextRepository(Protocol):
    """Magasin durable des Contexts. Ne décide rien : il écrit des valeurs déjà validées.

    Lecture : `None` / tuple vide quand rien n'existe. Erreurs de règle :
    `SessionContextError` (code du domaine) ; erreurs de stockage :
    `ContextStoreError` / `ContextStoreUnavailable`.
    """

    async def get_context(self, context_id: str) -> SessionContext | None: ...

    async def list_contexts(self, jarvis_session_id: str) -> Sequence[SessionContext]:
        """Tous les Contexts de la Session, du plus ancien au plus récent (`created_at`, puis id)."""
        ...

    async def active_context(self, jarvis_session_id: str) -> SessionContext | None:
        """Le Context actif de la Session, s'il y en a un (au plus un, garanti par le fichier)."""
        ...

    async def commit_contexts(self, changed: Sequence[SessionContext], *,
                              activity: Sequence[ActivityDraft] = ()) -> None:
        """Écrit `changed` (le `ContextTransition.changed` du domaine) en **une** transaction,
        avec les événements `activity` du ledger (Slice 04).

        Tout ou rien. Refus : deuxième actif dans une Session
        (`context_conflict`), identité d'une ligne existante modifiée
        (`context_conflict`), Context actif dans une Session close
        (`session_closed`), Session inconnue (`invalid_context`).
        """
        ...

    async def insert_adopted_if_absent(self, context: SessionContext, *,
                                       activity: Sequence[ActivityDraft] = ()) -> bool:
        """Insère le Context `adopted` seulement si sa Session est ouverte et n'a aucun Context.

        `activity` n'est écrite que si l'insertion a lieu (même transaction).

        Atomique ; rend vrai si cet appel l'a inséré. Clé d'idempotence de
        `ensure_context` (`jarvis/core/session_contexts.py`).
        """
        ...

    async def session_is_open(self, jarvis_session_id: str) -> bool:
        """La Session existe et est ouverte (relu quand une adoption n'a rien inséré)."""
        ...


# ------------------------------------------------------------------ dossier de travail (Slice 03)

#: Codes stables des échecs de dossier (`jarvis/adapters/context_workspace.py`).
WORKSPACE_UNSAFE = "context_workspace_unsafe"
WORKSPACE_FAILED = "context_workspace_failed"


class ContextWorkspaceError(RuntimeError):
    """Dossier de Context refusé (`context_workspace_unsafe`) ou non créé (`context_workspace_failed`)."""

    def __init__(self, code: str, path: Path, reason: str) -> None:
        super().__init__(f"{code}: {path}: {reason}")
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class ContextWorkspace:
    #: Chemin absolu du dossier, sous la racine résolue.
    path: Path
    #: Vrai si cet appel a créé au moins un composant (dont le dossier final).
    created: bool


class ContextWorkspaceStore(Protocol):
    """Les dossiers des Contexts sur disque, sous la racine de données (adaptateur : `FileContextWorkspaces`).

    Couture de Core (Slice 03) : `SessionManager` ne touche jamais le système
    de fichiers lui-même. Chaque méthode lève `ContextWorkspaceError` (code
    stable) ou `SessionContextError(invalid_context)` pour un id invalide.
    """

    def sessions_root(self) -> Path:
        """`<data_root>/sessions`, absolu : ce que le cerveau reçoit en `--add-dir`."""
        ...

    def expected_path(self, jarvis_session_id: str, context_id: str) -> Path:
        """Chemin absolu du dossier, sans accès disque (pour dire où il aurait dû être)."""
        ...

    def ensure(self, jarvis_session_id: str, context_id: str) -> ContextWorkspace: ...

    def read_summary(self, workspace: Path, max_bytes: int) -> tuple[str, bool]:
        """`(texte, coupé)` de `summary.md`, borné en octets ; `("", False)` s'il manque."""
        ...

    def write_handoff(self, workspace: Path, text: str) -> Path:
        """Écrit `handoff.md` atomiquement dans le dossier ; rend son chemin."""
        ...
