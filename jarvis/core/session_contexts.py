"""Adoption idempotente du Context par défaut d'une Session (handoff session-context-recording, Slice 02).

Décision D-CTX : une Session ouverte d'avant les Contexts reçoit **un**
Context actif `adopted`, sans historique fabriqué. La migration SQL v5 ne le
fait pas (l'identifiant et l'horloge viennent de Python, et une migration ne
porte jamais de donnée produit) : c'est `ensure_context`, appelé au démarrage
par `SessionManager` (sous son verrou) puis à chaque accès (bloc de chaque
tour), ce qui réessaie une adoption ratée.

Idempotent et sûr en concurrence : l'insertion est conditionnelle et atomique
(`ContextRepository.insert_adopted_if_absent`), et l'index unique
`idx_one_adopted_session_context` interdit une seconde adoption même entre
deux processus. Le dossier du Context n'est pas créé ici : `SessionManager`
le crée par le port `ContextWorkspaceStore`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from jarvis.domain.session_context import (
    SessionContext, SessionContextError, SessionContextErrorCode, adopt_context, check_contexts,
)
from jarvis.domain.workspace_board import JarvisSession
from jarvis.ports.session_context import ContextRepository


@dataclass(frozen=True, slots=True)
class EnsuredContext:
    """Résultat de `ensure_context` : à journaliser par l'appelant (adopté ou déjà là)."""

    context: SessionContext
    adopted: bool


async def ensure_context(
    repository: ContextRepository, session: JarvisSession, *, now: datetime,
) -> EnsuredContext | None:
    """Garantit un Context actif à une Session ouverte ; `None` pour une Session close.

    - Session close : rien n'est créé (une Session close n'a aucun actif) ;
    - Session ouverte qui a déjà des Contexts : rend l'actif, sans écrire ;
      un ensemble incohérent (aucun actif) lève `context_conflict` ;
    - Session ouverte sans Context : insère un `adopted` actif, une seule fois.
    """

    if not session.is_open:
        return None
    existing = check_contexts(session, await repository.list_contexts(session.jarvis_session_id))
    if existing:
        return EnsuredContext(context=next(c for c in existing if c.is_active), adopted=False)
    candidate = adopt_context(session, (), now=now).active
    if await repository.insert_adopted_if_absent(candidate):
        return EnsuredContext(context=candidate, adopted=True)
    # Rien inséré : un autre démarrage l'a adoptée entre la lecture et
    # l'insertion, ou la Session s'est close entre-temps (rien à garantir).
    active = await repository.active_context(session.jarvis_session_id)
    if active is None:
        if not await repository.session_is_open(session.jarvis_session_id):
            return None
        raise SessionContextError(
            SessionContextErrorCode.CONTEXT_CONFLICT,
            f"session {session.jarvis_session_id} was not adopted and has no active context",
        )
    return EnsuredContext(context=active, adopted=False)
