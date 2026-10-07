"""Registre borné des intentions d'interface publiées par Jarvis (Tool Brain, Slice 4).

Contrat : `docs/tool-brain-contracts.md` §11. Core est le seul propriétaire : il date et identifie l'intention,
la rattache au tour en cours (`correlation_id`) et la garde en mémoire, **bornée** (un oubli est préférable à
une croissance sans fin : une intention n'a de sens que pour le tour qui la porte). Ce registre ne décide rien
et n'exécute rien ; le Tool Brain (S5/S6) la lit. Le fait est publié une fois comme évènement
`brain.ui_intent.published` (jamais le contenu : seulement `kind`, `timing`, `ref_count`, `paragraph`).
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime
from typing import Callable

from jarvis.domain.ui_intent import UiIntent, UiIntentDraft

#: Intentions retenues par conversation ; au-delà, les plus anciennes sont oubliées (comptées).
MAX_INTENTS_PER_CONVERSATION = 64
MAX_CONVERSATIONS = 32
#: Intentions acceptées par tour : un tour qui en publie des dizaines ne guide plus rien.
MAX_INTENTS_PER_TURN = 8


class UiIntentRefused(ValueError):
    """Refus attribué (`code`) : `too_many_intents`. Le message ne contient jamais le contenu refusé."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UiIntentRegistry:
    def __init__(self, *, clock: Callable[[], datetime], id_factory: Callable[[], str] | None = None) -> None:
        self._clock = clock
        self._new_id = id_factory or (lambda: f"uiintent-{uuid.uuid4().hex[:16]}")
        self._by_conversation: dict[str, deque[UiIntent]] = {}
        self.forgotten = 0

    def publish(self, conversation_id: str, correlation_id: str, draft: UiIntentDraft) -> UiIntent:
        queue = self._by_conversation.get(conversation_id)
        if queue is None:
            while len(self._by_conversation) >= MAX_CONVERSATIONS:
                evicted = self._by_conversation.pop(next(iter(self._by_conversation)))
                self.forgotten += len(evicted)
            queue = self._by_conversation[conversation_id] = deque()
        if sum(1 for item in queue if item.correlation_id == correlation_id) >= MAX_INTENTS_PER_TURN:
            raise UiIntentRefused("too_many_intents", f"at most {MAX_INTENTS_PER_TURN} UI intents per turn")
        intent = UiIntent(self._new_id(), conversation_id, correlation_id, draft, self._clock())
        queue.append(intent)
        while len(queue) > MAX_INTENTS_PER_CONVERSATION:
            queue.popleft()
            self.forgotten += 1
        return intent

    def list(self, conversation_id: str, *, correlation_id: str | None = None) -> tuple[UiIntent, ...]:
        """Intentions retenues, de la plus ancienne à la plus récente, éventuellement d'un seul tour."""

        return tuple(item for item in self._by_conversation.get(conversation_id, ())
                     if correlation_id is None or item.correlation_id == correlation_id)


__all__ = ["MAX_INTENTS_PER_CONVERSATION", "MAX_INTENTS_PER_TURN", "UiIntentRefused", "UiIntentRegistry"]
