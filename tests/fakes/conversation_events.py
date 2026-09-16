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


def emitter_settled(emitter) -> bool:
    """Every enqueued event has an outcome (stored, duplicate, conflict or dropped)."""
    c = emitter.counters
    return c.enqueued == c.appended + c.duplicates + c.conflicts + c.dropped_store_error + c.dropped_shutdown


async def wait_emitter_settled(emitter, *, timeout_s: float = 5.0) -> None:
    import asyncio

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not emitter_settled(emitter):
        if loop.time() >= deadline:
            raise AssertionError(f"conversation event emitter never settled: {emitter.counters}")
        await asyncio.sleep(0.002)


def worst_case_ingest_batch(count: int = 32) -> list[ConversationEvent]:
    """Largest valid ingestion batch on the wire (`json.dumps` escapes non-ASCII).

    Every bounded field is at its limit with astral characters (1 code point,
    4 UTF-8 bytes, 12 escaped bytes): content 8192, every optional id 256, a
    64-char producer, a 96-char journal kind with all 8 join keys, and
    attributes filled up to the 4096 UTF-8 byte bound.
    """
    import json

    from jarvis.domain.conversation_events import MAX_ATTRIBUTES_JSON_BYTES, MAX_CONTENT_CHARS, TraceRef, TraceSource

    astral = "\U0001F600"
    ident = lambda tag: (tag + astral * 256)[:256]  # noqa: E731
    reason = astral * 512
    code = ""
    while len(json.dumps({"reason": [reason], "code": code + astral}, ensure_ascii=False,
                         separators=(",", ":")).encode()) <= MAX_ATTRIBUTES_JSON_BYTES and len(code) < 512:
        code += astral
    producer = "voice." + "p" * 58
    kind = "voice." + "k" * 90
    events = []
    for index in range(count):
        conversation_id = ident("c")
        speech = ident(f"s{index}")
        event_type = ConversationEventType.MOUTH_SPEECH_STARTED
        events.append(ConversationEvent(
            event_id=derive_conversation_event_id(producer=producer, event_type=event_type,
                                                  conversation_id=conversation_id, source_ids=(speech,)),
            event_type=event_type, actor=event_actor(event_type), conversation_id=conversation_id, producer=producer,
            visibility=event_visibility(event_type), occurred_at=BASE, started_at=BASE, span_id=speech,
            session_id=ident("se"), turn_id=ident("t"), correlation_id=ident("co"), task_id=ident("ta"),
            work_id=ident("w"), speech_id=speech, outcome_id=ident("o"), parent_event_id="cev-" + "a" * 64,
            trace_ref=TraceRef(TraceSource.RUNTIME_JOURNAL, kind, ("conversation_id", "session_id", "turn_id",
                                                                 "correlation_id", "task_id", "work_id",
                                                                 "speech_id", "outcome_id")),
            content=astral * MAX_CONTENT_CHARS, attributes={"reason": [reason], "code": code}))
    return events


# -- Slice 03b: out-of-process producers ------------------------------------------

class FakeEventTransport:
    """`CoreConversationEventTransport` double: scripted failures, then appended results."""

    def __init__(self) -> None:
        self.batches: list[tuple[ConversationEvent, ...]] = []
        self.failures: list[BaseException] = []
        self.hang = False
        self.closed = False

    async def post(self, events):
        import asyncio

        from jarvis.domain.conversation_event_store import AppendResult, AppendStatus

        if self.hang:
            await asyncio.Event().wait()
        if self.failures:
            raise self.failures.pop(0)
        batch = tuple(events)
        self.batches.append(batch)
        start = sum(len(item) for item in self.batches[:-1])
        return tuple(AppendResult(event.event_id, start + index + 1, AppendStatus.APPENDED)
                     for index, event in enumerate(batch))

    async def close(self) -> None:
        self.closed = True

    def sent(self) -> list[ConversationEvent]:
        return [event for batch in self.batches for event in batch]


def recording_forwarder(journal=None, **options):
    """A real forwarder that is never started: `record()` only queues, tests read `queued()`."""
    from jarvis.runtime.conversation_event_forwarder import ConversationEventForwarder

    return ConversationEventForwarder(transport=FakeEventTransport(), journal=journal, **options)


def queued(forwarder) -> list[ConversationEvent]:
    return list(forwarder._queue)


def journal_matches(event: ConversationEvent, entries) -> list:
    """Journal entries (`{kind, data}` mappings) that are trace evidence of `event`."""
    from jarvis.domain.conversation_events import trace_entry_matches

    return [entry for entry in entries if trace_entry_matches(event, entry)]


def assert_each_trace_ref_joins_one_line(events, entries) -> None:
    for event in events:
        if event.trace_ref is None:
            continue
        matches = journal_matches(event, entries)
        assert len(matches) == 1, (event.event_type, event.trace_ref, len(matches))
        assert matches[0]["data"]["conversation_event_id"] == event.event_id
