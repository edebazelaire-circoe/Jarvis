"""Évènement de conversation du graphe de variantes (handoff jarvis-interactive-presentation-studio, Slice 16).

Le **seul** traducteur « le graphe a changé -> évènement canonique » : `system.presentation_studio.variant_changed` (acteur
`system`, instantané, diagnostique, contenu interdit ; producteur `core.presentation_studio`). Attributs pris dans la liste
blanche (`ATTRIBUTE_KEYS`) : `presentation_id`, `variant_id`, `variant_number`, `op` (`created`, `switched`, `renamed`,
`archived`, `restored`), `source` (l'acteur `user` / `brain`), `revision`, `count` (nombre de variantes touchées par un
archivage ou une restauration), `status`. **Jamais** un titre ni une raison de création : ce sont des contenus
d'utilisateur (non fiables), ils restent dans les documents.

Sans conversation (l'interface agit hors de toute conversation) l'évènement n'est pas posé et `None` est rendu ; l'appelant
le dit dans sa ligne de journal (`event_recorded: false`). L'opération elle-même ne change pas.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from jarvis.core.conversation_event_emitter import PRODUCER_PRESENTATION_STUDIO
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import utc_now

#: Les opérations du graphe qui produisent un évènement (jeu fermé, repris par la documentation).
VARIANT_OPS = ("created", "switched", "renamed", "archived", "restored")


class StudioVariantEvents:
    def __init__(self, sink: Any, conversation_id: Callable[[], str | None], *,
                 wall: Callable[[], datetime] = utc_now) -> None:
        self._sink, self._conversation_id, self._wall = sink, conversation_id, wall

    def changed(self, *, presentation_id: str, variant_id: str, op: str, actor: str, revision: int,
                variant_number: int | None = None, count: int | None = None) -> str | None:
        if op not in VARIANT_OPS:
            raise ValueError(f"unknown variant op {op!r}")
        try:
            conversation = self._conversation_id()
        except Exception:  # noqa: BLE001 - argued silence: a failed conversation lookup is "no conversation", never an operation failure
            conversation = None
        if not conversation:
            return None
        attributes = {"presentation_id": presentation_id, "variant_id": variant_id, "op": op, "source": actor,
                      "revision": revision, "variant_number": variant_number, "count": count, "status": "applied"}
        clean = {key: value for key, value in attributes.items() if value is not None and value != ""}
        # A raising sink propagates: the graph service journals it (`event_failed`, warning) and the operation stands.
        return self._sink.record(T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED, producer=PRODUCER_PRESENTATION_STUDIO,
                                 conversation_id=conversation,
                                 source_ids=(presentation_id, variant_id, op, str(revision)),
                                 occurred_at=self._wall(), attributes=clean)
