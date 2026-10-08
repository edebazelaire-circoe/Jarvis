"""Évènements de conversation de l'API d'édition du Studio (handoff jarvis-interactive-presentation-studio, Slice 05).

Le **seul** traducteur « édition validée -> évènement canonique » : `system.presentation_studio.edit_committed`
(acteur `system`, instantané, diagnostique, contenu interdit) et, pour une panne (jamais un refus de l'appelant),
`system.failure` avec un `code`. Les attributs sont pris dans la liste blanche (`ATTRIBUTE_KEYS`) :
`presentation_id`, `variant_id`, `scene_id`, `op` (noms d'opération), `tier`, `source` (l'acteur `user`/`brain`),
`revision`, `status`, `code`. **Jamais** un titre, une valeur de contrôle ni l'intention d'une demande de source.

Une conversation est requise par l'enveloppe : celle qui a la parole (`conversation_id()`). Sans elle (édition de
l'interface hors de toute conversation), l'évènement n'est pas posé et `None` est rendu : l'appelant le dit (`event_recorded: false` sur sa ligne
`core.presentation_studio.edit_committed`). L'édition elle-même ne change pas.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from jarvis.core.conversation_event_emitter import PRODUCER_PRESENTATION_STUDIO, safe_error_class
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import utc_now


class StudioEditEvents:
    def __init__(self, sink: Any, conversation_id: Callable[[], str | None], *,
                 wall: Callable[[], datetime] = utc_now) -> None:
        self._sink, self._conversation_id, self._wall = sink, conversation_id, wall

    def committed(self, *, presentation_id: str, variant_id: str, revision: int, ops: Sequence[str], tier: str,
                  actor: str, status: str, scene_id: str | None = None, request_ids: Sequence[str] = ()) -> str | None:
        """Une édition validée. L'identité du fait est `(presentation, variante, révision)` ; une demande de source
        seule (la révision ne bouge pas) porte l'id de sa demande à la place."""

        key = str(revision) if not request_ids else request_ids[0]
        return self._record(T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED, (presentation_id, variant_id, key), {
            "presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
            "op": list(dict.fromkeys(ops)), "tier": tier, "source": actor, "revision": revision, "status": status})

    def failed(self, *, presentation_id: str, variant_id: str, code: str, revision: int | None = None) -> str | None:
        return self._record(T.SYSTEM_FAILURE, (presentation_id, variant_id, "edit_failed", code, str(revision or 0)),
                            {"presentation_id": presentation_id, "variant_id": variant_id, "code": safe_error_class(code),
                             "reason": "presentation_studio_edit"})

    def _record(self, event_type: T, source_ids: tuple[str, ...], attributes: dict[str, Any]) -> str | None:
        try:
            conversation = self._conversation_id()
        except Exception:  # noqa: BLE001 - argued silence: a failed conversation lookup is "no conversation", never an edit failure
            conversation = None
        if not conversation:
            return None  # reported by the caller: `event_recorded: false` on its `edit_committed` journal row
        clean = {key: value for key, value in attributes.items() if value is not None and value != ""}
        # A raising sink propagates: the edit service journals it (`event_failed`, warning) and the edit stands.
        return self._sink.record(event_type, producer=PRODUCER_PRESENTATION_STUDIO, conversation_id=conversation,
                                 source_ids=source_ids, occurred_at=self._wall(), attributes=clean)


class StudioPlaybackEvents(StudioEditEvents):
    """`system.presentation_studio.playback_changed` (Slice 12): a run's status word, never a title, phrase or cue.

    Attributes: `presentation_id`, `variant_id`, `status` (started, stopped, paused, resumed, detour, returned, ended,
    stage_failed, edit_committed), `role`, `depth` (auxiliary stack). Identity: `(run_id, sequence)`. Same rule as the edit
    event: no live conversation, nothing recorded (the diagnostic row of the command says so)."""

    def changed(self, *, presentation_id: str, variant_id: str | None, status: str, role: str | None, depth: int,
                run_id: str, seq: int) -> str | None:
        return self._record(T.SYSTEM_PRESENTATION_STUDIO_PLAYBACK_CHANGED, (run_id, str(seq)), {
            "presentation_id": presentation_id, "variant_id": variant_id, "status": status, "role": role, "depth": depth})
