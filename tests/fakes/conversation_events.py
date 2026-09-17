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


def assert_drill_down_joins_one_line(events, entries, trace_path: Path, *, private: str = "PRIVATE") -> None:
    """Slice 04: the Control Center drill-down of each stored event finds its one journal line.

    `entries` (journal dicts from several processes) are written interleaved with
    torn fragments into one `trace.jsonl`, as the live file is; each stored event
    is resolved from its own `trace_ref` only, and no projection carries `private`.
    """
    import json
    from datetime import datetime, timezone

    from jarvis.domain.conversation_events import ConversationActor
    from jarvis.runtime.conversation_event_trace import TraceNotApplicable, drill_down

    now = datetime.now(timezone.utc).isoformat()
    with trace_path.open("w", encoding="utf-8") as handle:
        for index, entry in enumerate(entries):
            handle.write(json.dumps({"ts": entry.get("ts") or now, **entry}, ensure_ascii=False, default=str) + "\n")
            if index % 3 == 0:
                handle.write('{"ts": "' + now + '", "kind": "voice.speech.started", "data": {"conv\n')
    for event in events:
        if event.actor is ConversationActor.USER:
            try:
                drill_down(event, trace_path)
            except TraceNotApplicable:
                continue
            raise AssertionError("user events must have no drill-down")
        body = drill_down(event, trace_path)
        assert private not in json.dumps(body, ensure_ascii=False), event.event_type
        if event.trace_ref is None:
            assert body["status"] == "no_trace_ref", event.event_type
            continue
        assert body["status"] == "found", (event.event_type, body["scan"])
        [entry] = body["scan"]["entries"]
        assert entry["data"]["conversation_event_id"] == event.event_id and not body["scan"]["truncated"]


# -- Slice 06: projections (transcript, export, search) ----------------------------

def transcript_scenario(conversation_id: str = "conv-t") -> list[ConversationEvent]:
    """A conversation exercising every transcript rule, in scrambled store order.

    Interrupted speech overlapping a sub-agent span, a reflex, a multi-line user
    turn, a tool span, duplicate Brain publications (collapsed), a failed and a
    never-played speech, turn and system failures, an open speech the next day.
    """
    from datetime import timedelta

    T = ConversationEventType
    voice, core_brain, outcomes = "voice.speech_scheduler", "core.brain_service", "core.brain_outcomes"
    c = dict(conversation_id=conversation_id)

    def speech(kind, source, ms, speech_id, **fields):
        if kind is not T.MOUTH_SPEECH_QUEUED:
            fields.setdefault("span_id", speech_id)
        return make_event(kind, source, ms=ms, producer=voice, speech_id=speech_id,
                          correlation_id=fields.pop("correlation_id", "c1"), **c, **fields)

    events = [
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", ms=0, producer="core.voice_admission", correlation_id="c1",
                   content="Jarvis, prépare le dossier de vol de Paul.", **c),
        make_event(T.BRAIN_TURN_ACCEPTED, "c1", ms=200, producer=core_brain, correlation_id="c1", **c),
        make_event(T.BRAIN_WORK_STARTED, "w1", ms=400, producer=core_brain, correlation_id="c1", work_id="work-1",
                   span_id="work-1", content="Recherche des vols", **c),
        make_event(T.SUBAGENT_STARTED, "t1", ms=600, producer="control_center.agent_tasks", correlation_id=None,
                   task_id="task-1", span_id="task-1", content="Rassemble les vols",
                   attributes={"subagent_type": "flight-finder", "model": "claude-sonnet-5"}, **c),
        make_event(T.BRAIN_SPEECH_REQUESTED, "r1", ms=900, producer=core_brain, correlation_id="c1", speech_id="sp1",
                   content="Je regarde tous les vols de la semaine.", **c),
        speech(T.MOUTH_SPEECH_STARTED, "sp1", 1000, "sp1", content="Je regarde tous les vols de la semaine."),
        speech(T.MOUTH_SPEECH_INTERRUPTED, "sp1", 2400, "sp1", started_at=BASE + timedelta(milliseconds=1000),
               attributes={"played_ms": 1400, "reason": "user_barge_in", "status": "cancelled"}),
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "u2", ms=2500, producer="core.voice_admission", correlation_id="c2",
                   content="Seulement celui de lundi.\nEt vite, s'il te plaît.", **c),
        make_event(T.MOUTH_REFLEX_STARTED, "x1", ms=2600, producer=voice, correlation_id="c2", content="D'accord.", **c),
        make_event(T.TOOL_CALL_STARTED, "call-7", ms=2700, producer="voice.realtime_audio", correlation_id=None,
                   span_id="call-7", attributes={"tool_name": "get_time", "arguments_redacted": True}, **c),
        make_event(T.TOOL_CALL_FINISHED, "call-7", ms=3000, producer="voice.realtime_audio", correlation_id=None,
                   span_id="call-7", attributes={"tool_name": "get_time", "status": "ok", "duration_ms": 300}, **c),
        make_event(T.BRAIN_MESSAGE_PUBLISHED, "o1", ms=4000, producer=outcomes, correlation_id="c1", outcome_id="o1",
                   content="Le vol de Paul part lundi à 9 h.", **c),
        make_event(T.BRAIN_MESSAGE_PUBLISHED, "o2", ms=4100, producer=outcomes, correlation_id="c1", outcome_id="o2",
                   content="Le vol de Paul part lundi à 9 h.", **c),
        make_event(T.BRAIN_MESSAGE_PUBLISHED, "o3", ms=4200, producer=outcomes, correlation_id="c2", outcome_id="o3",
                   content="Rien d'autre à signaler.", **c),
        speech(T.MOUTH_SPEECH_QUEUED, "sp2", 4250, "sp2"),
        speech(T.MOUTH_SPEECH_STARTED, "sp2", 4300, "sp2", content="Le vol de Paul part lundi à 9 h."),
        speech(T.MOUTH_SPEECH_COMPLETED, "sp2", 6300, "sp2", attributes={"status": "completed"}),
        speech(T.MOUTH_SPEECH_STARTED, "sp3", 6500, "sp3", content="Je vérifie la météo."),
        speech(T.MOUTH_SPEECH_FAILED, "sp3", 6800, "sp3",
               attributes={"code": "speech_speak_failed", "error_class": "RuntimeError"}),
        speech(T.MOUTH_SPEECH_SUPERSEDED, "sp4", 6900, "sp4", content="Autre annonce jamais dite.",
               attributes={"reason": "superseded_on_arrival"}),
        make_event(T.BRAIN_TURN_FAILED, "c3", ms=7000, producer=core_brain, correlation_id="c3",
                   attributes={"code": "brain_backend_exception", "error_class": "ConnectionResetError"}, **c),
        make_event(T.SYSTEM_FAILURE, "c4", ms=7100, producer="voice.realtime_audio", correlation_id="c4",
                   attributes={"code": "brain_turn_rejected", "reason": "http_error"}, **c),
        make_event(T.BRAIN_WORK_COMPLETED, "w1", ms=9000, producer=core_brain, correlation_id="c1", work_id="work-1",
                   span_id="work-1", **c),
        make_event(T.SUBAGENT_FINISHED, "t1", ms=95000, producer="control_center.agent_tasks", correlation_id=None,
                   task_id="task-1", span_id="task-1", started_at=BASE + timedelta(milliseconds=600),
                   attributes={"status": "completed", "tokens": 1234, "tool_uses": 5, "duration_ms": 94400}, **c),
        speech(T.MOUTH_SPEECH_STARTED, "sp5", 86_400_000 + 5000, "sp5", correlation_id="c5",
               content="Bonjour, nouvelle journée."),
    ]
    order = [5, 0, 17, 3, 12, 1, 22, 8, 14, 2, 19, 6, 11, 23, 4, 9, 16, 21, 7, 13, 24, 10, 18, 15, 20]
    assert sorted(order) == list(range(len(events)))
    return [events[i] for i in order]
