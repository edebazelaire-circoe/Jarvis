"""Évènements de conversation du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S9).

Contrat : `docs/tool-brain-contracts.md` §17 et `docs/conversation-events.md` (acteur `tool_brain`). Ce module est le
**seul** traducteur « fait du Tool Brain -> évènement canonique » : réveil, état capturé, décision, lecture ciblée,
cycle de vie d'une action de la file, replanification, changement de propriétaire de l'écran. Il n'ajoute aucun
système de transcription : il écrit dans le journal de conversation de Core (`ConversationEventEmitter.record`), que la
chronologie existante lit déjà.

- **producteur** `core.tool_brain` : le Tool Brain tourne dans Core et écrit par l'émetteur de Core (la dénylist
  d'ingestion refuse donc ce producteur sur `POST /v1/conversation-events`, comme les autres producteurs Core). Le
  producteur fait partie de l'`event_id` : ne jamais le renommer ;
- **jamais de contenu** : les types l'interdisent, et seuls des attributs de la liste blanche sont posés (jamais les
  arguments d'un outil ni le raisonnement du décideur) ;
- **ids** : `span_id` = id de l'action pour son cycle de vie (`queued` ouvre, `cancelled|invalidated|completed|failed`
  ferme), `correlation_id` = tour utilisateur, `speech_id` = morceau de parole qui déclenche l'action, attribut
  `intent_id` = intention de Jarvis, `parent_event_id` = fait qui l'a causée (réveil -> état -> décision -> action ->
  issue). Les ids de décision et d'action portent un jeton de processus (`run_id`) : la file est éphémère et ses
  compteurs repartent de 1 à chaque démarrage, sans lui deux processus d'une même conversation se percuteraient ;
- **jamais d'effet sur le comportement** : une conversation inconnue, un émetteur absent ou en défaut = l'évènement est
  perdu et compté (`stats()`), la décision et l'exécution continuent.

Une conversation est requise par l'enveloppe. Un réveil sans conversation (changement de scène, tick) se rattache à la
dernière conversation vue par le Tool Brain ; sans aucune, l'évènement est ignoré et compté (`no_conversation`).
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Callable, Mapping

from jarvis.core.conversation_event_emitter import PRODUCER_TOOL_BRAIN, journal_trace, safe_error_class
from jarvis.domain.conversation_events import ConversationEventType as T, TraceRef
from jarvis.domain.v2 import utc_now

#: Évènement de queue de l'observateur de la file (`ToolBrainActionQueue.observe`).
QUEUED, RESCHEDULED, STARTED, FINISHED = "queued", "rescheduled", "started", "finished"

#: Statut final d'une action de la file -> évènement qui ferme son cycle de vie.
CLOSE_TYPE: Mapping[str, T] = {
    "done": T.TOOL_BRAIN_ACTION_COMPLETED, "scheduled": T.TOOL_BRAIN_ACTION_COMPLETED,
    "failed": T.TOOL_BRAIN_ACTION_FAILED, "invalidated": T.TOOL_BRAIN_ACTION_INVALIDATED,
    "cancelled": T.TOOL_BRAIN_ACTION_CANCELLED, "expired": T.TOOL_BRAIN_ACTION_CANCELLED,
    "superseded": T.TOOL_BRAIN_ACTION_CANCELLED,
}
#: Statuts dont l'exécuteur ou le balayage écrit une ligne `tool_brain.action.<statut>` dans le journal : seuls
#: ceux-là portent un `trace_ref` (jamais un renvoi vers une ligne qui n'existe pas).
JOURNALED_STATUSES = frozenset({"done", "scheduled", "failed", "invalidated"})

MAX_TEXT = 200


def new_run_id() -> str:
    """Jeton de processus : 6 hexa, distinct à chaque démarrage."""

    return secrets.token_hex(3)


class ToolBrainEvents:
    """Traducteur des faits du Tool Brain en évènements de conversation. Voir l'en-tête du module.

    `sink` : l'émetteur de Core (ou tout objet avec `record(...)` et `derive_event_id(...)`). Toutes les méthodes
    rendent l'id de l'évènement, ou `None` quand il n'a pas été enregistré ; aucune ne lève.
    """

    def __init__(self, sink: Any, *, wall: Callable[[], datetime] = utc_now, run_id: str | None = None,
                 producer: str = PRODUCER_TOOL_BRAIN) -> None:
        self._sink, self._wall, self._producer = sink, wall, producer
        self.run_id = run_id or new_run_id()
        self._conversation: str | None = None
        self._counter = 0
        self._stats = {"recorded": 0, "not_recorded": 0, "no_conversation": 0, "failed": 0}

    # ------------------------------------------------------------ ids

    def next_id(self, prefix: str) -> str:
        """Id local au processus (`<prefix>-<run>-<n>`), pour les faits qui n'ont pas d'id propre."""

        self._counter += 1
        return f"{prefix}-{self.run_id}-{self._counter:06d}"

    def note_conversation(self, conversation_id: str | None) -> None:
        if conversation_id:
            self._conversation = conversation_id

    @property
    def conversation_id(self) -> str | None:
        return self._conversation

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def event_id(self, event_type: T, conversation_id: str | None, *source_ids: str) -> str | None:
        """L'id que `record` donnerait à ce fait (pour un lien `parent_event_id` ou une ligne de journal)."""

        conversation = conversation_id or self._conversation
        if not conversation:
            return None
        try:
            return self._sink.derive_event_id(event_type, producer=self._producer, conversation_id=conversation,
                                              source_ids=tuple(source_ids))
        except Exception:  # noqa: BLE001 - argued silence: an id is a hint for a link, never a reason to fail
            return None

    # ------------------------------------------------------------ écriture

    def _record(self, event_type: T, conversation_id: str | None, source_ids: tuple[str, ...], *,
                attributes: Mapping[str, Any], at: datetime | None = None, **fields: Any) -> str | None:
        conversation = conversation_id or self._conversation
        if not conversation:
            self._stats["no_conversation"] += 1
            return None
        self.note_conversation(conversation_id)
        clean = {key: value for key, value in attributes.items() if value is not None and value != ""}
        fields = {key: value for key, value in fields.items() if value is not None}
        try:
            event_id = self._sink.record(event_type, producer=self._producer, conversation_id=conversation,
                                         source_ids=source_ids, occurred_at=at or self._wall(),
                                         attributes=clean, **fields)
        except Exception:  # noqa: BLE001 - capture, counted: observability never fails the decision cycle
            self._stats["failed"] += 1
            return None
        self._stats["recorded" if event_id else "not_recorded"] += 1
        return event_id

    # ------------------------------------------------------------ décision

    def wake(self, wake_id: str, *, wake_class: str, source: str, reasons: tuple[str, ...] = (),
             conversation_id: str | None = None, correlation_id: str | None = None,
             at: datetime | None = None) -> str | None:
        """Un réveil (ou une rafale coalescée) qui a mené à un cycle. `reason` = classe de réveil, `source` = `event|tick`."""

        return self._record(T.TOOL_BRAIN_WAKE_REQUESTED, conversation_id, (wake_id,), at=at, correlation_id=correlation_id,
                            attributes={"reason": wake_class, "source": source,
                                        "kind": ",".join(reasons)[:MAX_TEXT] or None})

    def snapshot(self, decision_id: str, *, revision: int | None, conversation_id: str | None = None,
                 correlation_id: str | None = None, parent: str | None = None) -> str | None:
        return self._record(T.TOOL_BRAIN_SNAPSHOT_CAPTURED, conversation_id, (decision_id,), parent_event_id=parent,
                            correlation_id=correlation_id,
                            attributes={"decision_id": decision_id, "revision": revision})

    def inspect(self, decision_id: str, index: int, read: str, *, ok: bool, code: str | None = None,
                conversation_id: str | None = None, correlation_id: str | None = None,
                parent: str | None = None) -> str | None:
        return self._record(T.TOOL_BRAIN_INSPECT_REQUESTED, conversation_id, (decision_id, f"i{index}"),
                            parent_event_id=parent, correlation_id=correlation_id,
                            attributes={"decision_id": decision_id, "tool_name": read[:60],
                                        "status": "ok" if ok else "refused", "code": code})

    def decision(self, decision_id: str, *, status: str, model: str = "", duration_ms: int | None = None,
                 actions: int = 0, rejected: int = 0, code: str | None = None, conversation_id: str | None = None,
                 correlation_id: str | None = None, parent: str | None = None) -> str | None:
        """La décision (réussie, dépassée ou en échec). Le raisonnement du décideur n'y est jamais."""

        return self._record(
            T.TOOL_BRAIN_DECISION_MADE, conversation_id, (decision_id,), parent_event_id=parent,
            correlation_id=correlation_id, trace_ref=self.journal_ref("tool_brain.decision"),
            attributes={"decision_id": decision_id, "status": status, "model": model[:80], "duration_ms": duration_ms,
                        "actions": actions, "rejected": rejected, "code": code})

    def replan(self, action_id: str, *, reason: str, code: str | None = None, suppressed: bool = False,
               conversation_id: str | None = None, correlation_id: str | None = None,
               parent: str | None = None) -> str | None:
        return self._record(T.TOOL_BRAIN_REPLAN_REQUESTED, conversation_id, (action_id,), parent_event_id=parent,
                            correlation_id=correlation_id,
                            attributes={"action_id": action_id, "reason": reason, "code": code,
                                        "status": "suppressed" if suppressed else "requested"})

    def ownership(self, owner: str, *, previous: str, reason: str, fallback: bool, mode: str) -> str | None:
        """Qui possède l'écran a changé (arbitre S8). `fallback` : le mode voulait déléguer, Jarvis garde l'écran."""

        return self._record(T.TOOL_BRAIN_OWNERSHIP_CHANGED, None, (self.next_id("own"),),
                            attributes={"owner": owner, "source": previous, "reason": reason, "fallback": fallback,
                                        "kind": mode,
                                        "status": "fallback" if fallback else "delegated" if owner == "tool_brain" else "direct"})

    # ------------------------------------------------------------ cycle de vie d'une action

    def action_event_id(self, status: str, record: Any) -> str | None:
        """L'id de l'évènement qui ferme (`status` final) ou ouvre (`queued`) l'action `record`."""

        event_type = T.TOOL_BRAIN_ACTION_QUEUED if status == QUEUED else CLOSE_TYPE.get(status)
        if event_type is None:
            return None
        return self.event_id(event_type, record.conversation_id, record.action_id)

    def decision_event_id(self, decision_id: str, conversation_id: str | None = None) -> str | None:
        return self.event_id(T.TOOL_BRAIN_DECISION_MADE, conversation_id, decision_id)

    @staticmethod
    def journal_ref(kind: str) -> TraceRef:
        return journal_trace(kind)

    def queue_change(self, kind: str, view: Any) -> str | None:
        """Observateur de la file : un changement d'état d'une action devient l'évènement de son cycle de vie."""

        record = view.record
        action_id, trigger = record.action_id, record.trigger
        common: dict[str, Any] = {"action_id": action_id, "tool_name": record.tool, "decision_id": record.decision_id,
                                  "intent_id": record.intent_id, "priority": record.priority}
        ids: dict[str, Any] = {"correlation_id": record.correlation_id, "speech_id": trigger.chunk_id}
        conversation = record.conversation_id
        queued_parent = self.event_id(T.TOOL_BRAIN_ACTION_QUEUED, conversation, action_id)
        if kind == QUEUED:
            ids["parent_event_id"] = self.decision_event_id(record.decision_id, conversation) if record.decision_id else None
            return self._record(T.TOOL_BRAIN_ACTION_QUEUED, conversation, (action_id,), span_id=action_id, **ids,
                                attributes={**common, "reason": record.reason_code or None, "kind": trigger.kind,
                                            "arguments_redacted": True})
        ids["parent_event_id"] = queued_parent
        if kind == RESCHEDULED:
            return self._record(T.TOOL_BRAIN_ACTION_RESCHEDULED, conversation, (action_id, f"r{view.reschedules}"),
                                **ids, attributes={**common, "kind": trigger.kind})
        if kind == STARTED:
            return self._record(T.TOOL_BRAIN_ACTION_STARTED, conversation, (action_id,), **ids, attributes=common)
        event_type = CLOSE_TYPE.get(view.status)
        if kind != FINISHED or event_type is None:
            return None
        detail = view.detail if isinstance(view.detail, Mapping) else {}
        revision = detail.get("revision")
        trace_ref = self.journal_ref(f"tool_brain.action.{view.status}") if view.status in JOURNALED_STATUSES else None
        return self._record(
            event_type, conversation, (action_id,), span_id=action_id, trace_ref=trace_ref, **ids,
            attributes={**common, "status": view.status, "code": (view.code or None) and str(view.code)[:80],
                        "revision": revision if type(revision) is int else None,
                        "error_class": safe_error_class(detail.get("error_class"))})


__all__ = ["CLOSE_TYPE", "FINISHED", "JOURNALED_STATUSES", "QUEUED", "RESCHEDULED", "STARTED", "ToolBrainEvents",
           "new_run_id"]
