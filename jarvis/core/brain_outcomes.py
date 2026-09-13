"""Durable public backend outcomes, independent of execution and heard history."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from jarvis.domain.speech_presentation import (
    BackendOutcome, OutcomeKind, OutcomeStatus, SpeechDependency, SpeechSource, speech_id,
)
from jarvis.domain.v2 import ProtocolEnvelope, utc_now
from jarvis.ports.v2 import DiagnosticSink, EventSink, StateRepository

BRAIN_OUTCOME_AVAILABLE = "brain.outcome.available"


def stable_identity(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class BrainOutcomeService:
    """Core alone writes outcomes. Reads neither authorize jobs nor request speech."""

    def __init__(self, repository: StateRepository, events: EventSink, diagnostics: DiagnosticSink) -> None:
        self.repository = repository
        self.events = events
        self.diagnostics = diagnostics

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
            self.diagnostics.emit("core.brain.outcome_retained", "public outcome retained", data={
                "conversation_id": conversation_id, "correlation_id": correlation_id,
                "outcome_id": stored.id, "kind": stored.kind.value, "status": stored.status.value})
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
