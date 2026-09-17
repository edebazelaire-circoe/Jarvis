"""Durable public backend outcomes, independent of execution and heard history."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from jarvis.core.conversation_event_emitter import (
    PRODUCER_BRAIN_OUTCOMES, NullConversationEventEmitter, journal_ref, journal_trace,
)
from jarvis.domain.conversation_events import ConversationEventType
from jarvis.domain.speech_presentation import (
    BackendOutcome, OutcomeKind, OutcomeStatus, SpeechDependency, SpeechSource, speech_id,
)
from jarvis.domain.v2 import ProtocolEnvelope, utc_now
from jarvis.ports.v2 import ConversationEventRecorder, DiagnosticSink, EventSink, StateRepository

BRAIN_OUTCOME_AVAILABLE = "brain.outcome.available"
OUTCOME_RETAINED_KIND = "core.brain.outcome_retained"
#: Same outcome, observation kind matured (speech_result -> turn/work result).
#: Its own kind so the `brain.message.published` trace join matches one line only.
OUTCOME_MATURED_KIND = "core.brain.outcome_matured"


def stable_identity(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class BrainOutcomeService:
    """Core alone writes outcomes. Reads neither authorize jobs nor request speech."""

    def __init__(self, repository: StateRepository, events: EventSink, diagnostics: DiagnosticSink,
                 conversation_events: ConversationEventRecorder | None = None) -> None:
        self.repository = repository
        self.events = events
        self.diagnostics = diagnostics
        self.conversation_events = conversation_events or NullConversationEventEmitter()

    async def known_conversation(self, conversation_id: str) -> None:
        speech_id(conversation_id, "conversation_id")
        if await self.repository.get_conversation(conversation_id) is None:
            raise KeyError("unknown conversation")

    async def source(self, conversation_id: str, correlation_id: str, work_id: str | None = None) -> SpeechSource | None:
        source = await self.repository.get_brain_source(conversation_id, correlation_id)
        if source is not None and work_id:
            source = replace(source, dependencies=(SpeechDependency(work_id, correlation_id),))
        return source

    async def context(self, conversation_id: str) -> dict:
        await self.known_conversation(conversation_id)
        current = await self.repository.get_current_brain_source(conversation_id)
        invalidated = await self.repository.list_invalidated_brain_dependencies(conversation_id)
        return {"schema_version": 1, "conversation_id": conversation_id,
                "current_speech_source": current.to_payload() if current else None,
                "invalidated_dependencies": [item.to_payload() for item in invalidated[:256]],
                "source_complete": len(invalidated) <= 256}

    async def retain(self, *, conversation_id: str, correlation_id: str, work_id: str | None,
                     text: str, kind: OutcomeKind, status: OutcomeStatus = OutcomeStatus.COMPLETED,
                     dependency_known: bool = True) -> BackendOutcome | None:
        if not text.strip():
            return None
        source = await self.source(conversation_id, correlation_id, work_id if dependency_known else None)
        outcome_id = "outcome-" + stable_identity(conversation_id, correlation_id, work_id, status.value, text)
        existing = await self.repository.get_brain_outcome(conversation_id, outcome_id)
        if existing is not None:
            # The first observation owns provenance. Later work-name reuse
            # cannot reattribute this immutable result to a new dependency.
            source = existing.source
        outcome = BackendOutcome(
            id=outcome_id,
            conversation_id=conversation_id, source=source, work_id=work_id, text=text,
            created_at=utc_now(), kind=kind, status=status,
        )
        try:
            try:
                stored, changed = await self.repository.save_brain_outcome(outcome)
            except ValueError:
                # Concurrent observations may both have read no version while
                # ownership changed from ambiguous to known. The repository
                # remains strict: rejoin only this exact content/origin race,
                # then submit the persisted winner's source for validation.
                winner = await self.repository.get_brain_outcome(conversation_id, outcome_id)
                if winner is None or not self._same_origin_observation(winner, outcome):
                    raise
                stored, changed = await self.repository.save_brain_outcome(replace(outcome, source=winner.source))
        except Exception as exc:
            self.diagnostics.emit("core.brain.outcome_persistence_failed", "public outcome persistence failed", level="error",
                                  data={"conversation_id": conversation_id, "correlation_id": correlation_id,
                                        "outcome_id": outcome.id, "code": "brain_outcome_persistence_failed",
                                        "error_class": type(exc).__name__})
            raise
        if changed:
            # `brain.message.published`: first retention of a public outcome only.
            # A replayed observation or a later kind maturation (speech result
            # confirmed as turn/work result) is not a new message. Fact time = retention.
            # The maturation is journaled under its own kind (still naming the
            # event id): the event's trace_ref join matches the retention line only.
            source_ids = (correlation_id, stored.id)
            if existing is None:
                event_id = self.conversation_events.record(
                    ConversationEventType.BRAIN_MESSAGE_PUBLISHED, producer=PRODUCER_BRAIN_OUTCOMES,
                    conversation_id=conversation_id, source_ids=source_ids, occurred_at=stored.created_at,
                    correlation_id=correlation_id, outcome_id=stored.id, work_id=stored.work_id, content=stored.text,
                    attributes={"kind": stored.kind.value, "status": stored.status.value},
                    trace_ref=journal_trace(OUTCOME_RETAINED_KIND, "correlation_id", "outcome_id"))
            else:
                event_id = self.conversation_events.derive_event_id(
                    ConversationEventType.BRAIN_MESSAGE_PUBLISHED, producer=PRODUCER_BRAIN_OUTCOMES,
                    conversation_id=conversation_id, source_ids=source_ids)
            self.diagnostics.emit(OUTCOME_RETAINED_KIND if existing is None else OUTCOME_MATURED_KIND,
                                  "public outcome retained" if existing is None else "public outcome kind matured", data={
                "conversation_id": conversation_id, "correlation_id": correlation_id,
                "outcome_id": stored.id, "kind": stored.kind.value, "status": stored.status.value,
                **journal_ref(event_id)})
            await self.events.publish(ProtocolEnvelope(
                message_type=BRAIN_OUTCOME_AVAILABLE, conversation_id=conversation_id, correlation_id=correlation_id,
                payload={"schema_version": 1, "outcome": stored.to_payload()},
            ))
        return stored

    @staticmethod
    def _same_origin_observation(first: BackendOutcome, later: BackendOutcome) -> bool:
        if any(getattr(first, name) != getattr(later, name) for name in ("id", "conversation_id", "work_id", "text", "status")):
            return False
        if first.source is None or later.source is None:
            return first.source == later.source
        if replace(first.source, dependencies=()) != replace(later.source, dependencies=()):
            return False
        expected = (SpeechDependency(first.work_id, first.source.correlation_id),) if first.work_id else ()
        return first.source.dependencies in ((), expected) and later.source.dependencies in ((), expected)

    async def get(self, conversation_id: str, outcome_id: str) -> BackendOutcome:
        await self.known_conversation(conversation_id)
        speech_id(outcome_id, "outcome_id")
        outcome = await self.repository.get_brain_outcome(conversation_id, outcome_id)
        if outcome is None:
            raise KeyError("unknown outcome")
        return outcome

    async def list(self, conversation_id: str, *, limit: int = 32) -> dict:
        await self.known_conversation(conversation_id)
        outcomes = await self.repository.list_brain_outcomes(conversation_id, limit=limit)
        return {"schema_version": 1, "conversation_id": conversation_id,
                "outcomes": [outcome.to_payload() for outcome in outcomes]}
