"""Synthetic Conversation Events and store wiring for store tests; never used by production."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis.adapters.sqlite_conversation_events import SQLiteConversationEventStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.domain.conversation_events import (
    ConversationEvent, ConversationEventType, EventShape, derive_conversation_event_id, event_actor, event_shape,
    event_visibility,
)

BASE = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
_SPAN_FIELD = {"brain.work": "work_id", "mouth.speech": "speech_id", "subagent": "task_id"}


def make_event(event_type: ConversationEventType, source: str, *, conversation_id: str = "conv-a", ms: int = 0,
               producer: str = "test.producer", **fields) -> ConversationEvent:
    """Valid event with every id the type requires derived from `source`."""
    at = BASE + timedelta(milliseconds=ms)
    kind = event_type.value
    fields.setdefault("correlation_id", f"corr-{source}")
    if kind.startswith(("user.", "brain.turn.accepted")):
        fields.setdefault("turn_id", f"turn-{source}")
    if kind == "brain.message.published":
        fields.setdefault("outcome_id", f"outcome-{source}")
    if kind in ("user.transcript.accepted", "brain.message.published", "brain.speech.requested"):
        fields.setdefault("content", f"text {source}")
    if kind.startswith(("mouth.speech", "brain.speech")):
        fields.setdefault("speech_id", f"speech-{source}")
    if kind.startswith("brain.work"):
        fields.setdefault("work_id", f"work-{source}")
    if kind.startswith("subagent"):
        fields.setdefault("task_id", f"task-{source}")
    shape = event_shape(event_type)
    if shape is not EventShape.INSTANT:
        prefix = next((p for p in _SPAN_FIELD if kind.startswith(p)), None)
        fields.setdefault("span_id", fields[_SPAN_FIELD[prefix]] if prefix else f"call-{source}")
        if shape is EventShape.SPAN_OPEN:
            fields.setdefault("started_at", at)
        else:
            fields.setdefault("ended_at", at)
    if kind.startswith(("tool.", "system.", "brain.turn.failed")):
        fields.pop("content", None)
    return ConversationEvent(
        event_id=derive_conversation_event_id(producer=producer, event_type=event_type,
                                              conversation_id=conversation_id, source_ids=(source,)),
        event_type=event_type, actor=event_actor(event_type), conversation_id=conversation_id, producer=producer,
        visibility=event_visibility(event_type), occurred_at=at, **fields)


class RecordingDiagnostics:
    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[tuple[str, str, str, dict]] = []
        self.fail = fail

    def emit(self, kind, message, *, level="info", data=None):
        if self.fail:
            raise OSError("diagnostic sink unavailable")
        self.entries.append((kind, message, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [entry[0] for entry in self.entries]


class MutableClock:
    def __init__(self, now: datetime = BASE) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


async def open_store(path: Path, *, diagnostics=None, clock=None) -> tuple[SQLiteStateRepository, SQLiteConversationEventStore]:
    state = SQLiteStateRepository(path)
    await state.initialize()
    kwargs = {"diagnostics": diagnostics}
    if clock is not None:
        kwargs["clock"] = clock
    return state, SQLiteConversationEventStore(state, **kwargs)
