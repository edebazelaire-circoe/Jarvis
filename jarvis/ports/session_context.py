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
from typing import Protocol

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
        RuntimeError.__init__(self, f"context store {operation} failed: {reason}")
        self.table = "session_contexts"
        self.key = operation


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

    async def commit_contexts(self, changed: Sequence[SessionContext]) -> None:
        """Écrit `changed` (le `ContextTransition.changed` du domaine) en **une** transaction.

        Tout ou rien. Refus : deuxième actif dans une Session
        (`context_conflict`), identité d'une ligne existante modifiée
        (`context_conflict`), Context actif dans une Session close
        (`session_closed`), Session inconnue (`invalid_context`).
        """
        ...

    async def insert_adopted_if_absent(self, context: SessionContext) -> bool:
        """Insère le Context `adopted` seulement si sa Session est ouverte et n'a aucun Context.

        Atomique ; rend vrai si cet appel l'a inséré. Clé d'idempotence de
        `ensure_context` (`jarvis/core/session_contexts.py`).
        """
        ...
