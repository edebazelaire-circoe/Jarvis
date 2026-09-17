"""Conformance tests for the Conversation Event contract (docs/conversation-events.md)."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random

import pytest

from jarvis.domain.conversation_events import (
    ATTRIBUTE_KEYS, CONVERSATION_EVENT_SCHEMA_VERSION, EVENT_FIELDS, MAX_ATTRIBUTE_LIST_ITEMS,
    MAX_ATTRIBUTE_TEXT_CHARS, MAX_ATTRIBUTES, MAX_CONTENT_CHARS, MAX_PAYLOAD_DEPTH, SPAN_OPENER, ConversationActor,
    ConversationEvent, ConversationEventConflictError, ConversationEventError, ConversationEventRedactionError,
    ConversationEventType, ConversationVisibility, EventShape, TraceRef, TraceSource,
    decode_conversation_event, derive_conversation_event_id, encode_conversation_event, event_actor,
    event_shape, event_visibility, is_duplicate_event, is_forbidden_key, reconstruct_conversation,
    to_event_time, trace_entry_matches, unsequenced_order_key, validate_conversation_event,
)

T = ConversationEventType
FIXTURE = Path(__file__).parents[1] / "fixtures" / "conversation_events" / "overlapping_conversation.json"
BASE = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
CONV = "conv-demo"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fixture_events() -> list[ConversationEvent]:
    return [decode_conversation_event(row["event"]) for row in load_fixture()["events"]]


def fixture_payload(event_type: ConversationEventType) -> dict:
    return copy.deepcopy(next(row["event"] for row in load_fixture()["events"] if row["event"]["event_type"] == event_type.value))


def make(event_type: ConversationEventType, *, ms: int = 0, source: str = "src-1", **kw) -> ConversationEvent:
    at = BASE + timedelta(milliseconds=ms)
    shape = event_shape(event_type)
    if shape is EventShape.SPAN_OPEN:
        kw.setdefault("started_at", at)
    elif shape is EventShape.SPAN_CLOSE:
        kw.setdefault("ended_at", at)
    return ConversationEvent(
        event_id=derive_conversation_event_id(producer="test.producer", event_type=event_type,
                                              conversation_id=CONV, source_ids=(source,)),
        event_type=event_type, actor=event_actor(event_type), conversation_id=CONV, producer="test.producer",
        visibility=event_visibility(event_type), occurred_at=at, **kw)


def as_rows(items) -> list[dict]:
    fmt = lambda v: None if v is None else v.strftime("%Y-%m-%dT%H:%M:%S.") + f"{v.microsecond // 1000:03d}Z"
    return [{"actor": i.actor.value, "event_type": i.event_type.value, "status": i.status,
             "started_at": fmt(i.started_at), "ended_at": fmt(i.ended_at), "text": i.text,
             "anomalies": list(i.anomalies)} for i in items]


# ------------------------------------------------------------- vocabulary

def test_vocabulary_is_closed_and_consistent():
    assert {a.value for a in ConversationActor} == {"user", "mouth", "brain", "subagent", "tool", "system"}
    for event_type in ConversationEventType:
        assert event_type.value.split(".")[0] == event_actor(event_type).value
        event_shape(event_type)
        event_visibility(event_type)
    closes = {t for t in ConversationEventType if event_shape(t) is EventShape.SPAN_CLOSE}
    assert set(SPAN_OPENER) == closes
    assert all(event_shape(opener) is EventShape.SPAN_OPEN for opener in SPAN_OPENER.values())


# ---------------------------------------------------------------- fixture

def test_fixture_event_ids_are_derived_from_source_identity():
    for row in load_fixture()["events"]:
        event = row["event"]
        assert event["event_id"] == derive_conversation_event_id(
            producer=event["producer"], event_type=T(event["event_type"]),
            conversation_id=event["conversation_id"], source_ids=tuple(row["source_ids"]))


def test_fixture_round_trips_exactly():
    for row in load_fixture()["events"]:
        decoded = decode_conversation_event(row["event"])
        encoded = encode_conversation_event(decoded)
        assert encoded == row["event"]
        assert json.loads(json.dumps(encoded)) == row["event"]
        assert decode_conversation_event(encoded) == decoded


def test_fixture_covers_every_actor():
    assert {e.actor for e in fixture_events()} == set(ConversationActor) - {ConversationActor.SYSTEM}


# --------------------------------------------------------------- identity

def test_event_id_is_deterministic_and_position_independent():
    kwargs = dict(producer="voice.speech_scheduler", event_type=T.MOUTH_SPEECH_STARTED, conversation_id=CONV)
    first = derive_conversation_event_id(**kwargs, source_ids=("speech-1",))
    assert first == derive_conversation_event_id(**kwargs, source_ids=("speech-1",))
    assert first.startswith("cev-") and len(first) == 68
    assert first != derive_conversation_event_id(**kwargs, source_ids=("speech-2",))
    assert first != derive_conversation_event_id(**{**kwargs, "event_type": T.MOUTH_SPEECH_COMPLETED}, source_ids=("speech-1",))
    assert first != derive_conversation_event_id(**{**kwargs, "producer": "core.brain_service"}, source_ids=("speech-1",))
    # Tuple boundaries are part of identity: ("a", "b") is not ("a,b",).
    assert (derive_conversation_event_id(**kwargs, source_ids=("a", "b"))
            != derive_conversation_event_id(**kwargs, source_ids=("a,b",)))


@pytest.mark.parametrize("source_ids", [(), ("",), [" x"], ("x",) * 9, (" padded ",)])
def test_event_id_derivation_rejects_invalid_source_ids(source_ids):
    with pytest.raises(ConversationEventError, match="source_ids"):
        derive_conversation_event_id(producer="p", event_type=T.SYSTEM_FAILURE, conversation_id=CONV, source_ids=source_ids)


def test_duplicate_identical_is_noop_and_different_payload_conflicts():
    event = make(T.SYSTEM_FAILURE, attributes={"code": "brain_turn_transport_error"})
    assert is_duplicate_event(event, decode_conversation_event(encode_conversation_event(event))) is True
    assert is_duplicate_event(event, make(T.SYSTEM_FAILURE, source="other")) is False
    with pytest.raises(ConversationEventConflictError, match="different payload"):
        is_duplicate_event(event, replace(event, attributes={"code": "other"}))


def test_retry_must_reuse_fact_time_not_emission_time():
    # occurred_at is when the fact happened. A producer retry that stamps the
    # emission time instead turns a harmless replay into a conflict.
    fact = make(T.USER_TRANSCRIPT_ACCEPTED, ms=0, correlation_id="c-1", turn_id="t-1", content="Bonjour.")
    assert is_duplicate_event(fact, replace(fact)) is True
    with pytest.raises(ConversationEventConflictError):
        is_duplicate_event(fact, replace(fact, occurred_at=BASE + timedelta(seconds=3)))


def test_events_hash_by_identity_and_attributes_are_read_only():
    event = make(T.SYSTEM_FAILURE, attributes={"code": "x", "reason": ["a", "b"]})
    assert hash(event) == hash(decode_conversation_event(encode_conversation_event(event)))
    assert len({event, decode_conversation_event(encode_conversation_event(event))}) == 1
    assert event.attributes["reason"] == ("a", "b")
    with pytest.raises(TypeError):
        event.attributes["reasoning"] = "leaked after construction"


def test_unsequenced_order_is_time_then_event_id():
    a, b = make(T.SYSTEM_FAILURE, source="a"), make(T.SYSTEM_FAILURE, source="b")
    later = make(T.SYSTEM_FAILURE, source="c", ms=1)
    ordered = sorted([later, b, a], key=unsequenced_order_key)
    assert ordered[-1] is later
    assert [e.event_id for e in ordered[:2]] == sorted([a.event_id, b.event_id])


def test_to_event_time_normalizes_to_utc_milliseconds():
    local = datetime(2026, 9, 16, 12, 0, 0, 123987, tzinfo=timezone(timedelta(hours=2)))
    assert to_event_time(local) == datetime(2026, 9, 16, 10, 0, 0, 123000, tzinfo=timezone.utc)
    with pytest.raises(ConversationEventError):
        to_event_time(datetime(2026, 9, 16))


# ------------------------------------------------------ invalid payloads

@pytest.mark.parametrize("mutate, message", [
    (lambda p: p.pop("conversation_id"), "missing field"),
    (lambda p: p.update(extra=1), "unknown field"),
    (lambda p: p.update(schema_version=2), "schema_version"),
    (lambda p: p.update(schema_version="1"), "schema_version"),
    (lambda p: p.update(schema_version=True), "schema_version"),
    (lambda p: p.update(actor="jarvis"), "actor is not in the vocabulary"),
    (lambda p: p.update(actor="brain"), "actor for user.transcript.accepted must be user"),
    (lambda p: p.update(event_type="user.said"), "event_type is not in the vocabulary"),
    (lambda p: p.update(visibility="diagnostic"), "visibility for user.transcript.accepted"),
    (lambda p: p.update(event_id="evt-1"), "event_id must match"),
    (lambda p: p.update(parent_event_id=p["event_id"]), "parent_event_id must differ"),
    (lambda p: p.update(turn_id=None), "turn_id is required"),
    (lambda p: p.update(correlation_id=""), "correlation_id must be a nonempty"),
    (lambda p: p.update(session_id=42), "session_id must be a nonempty"),
    (lambda p: p.update(content=None), "content is required"),
    (lambda p: p.update(content="   "), "nonblank"),
    (lambda p: p.update(content="x" * (MAX_CONTENT_CHARS + 1)), "content exceeds"),
    (lambda p: p.update(producer="Voice Runtime"), "producer"),
    (lambda p: p.update(occurred_at="2026-09-16T10:00:00+00:00"), "occurred_at must be UTC ISO-8601"),
    (lambda p: p.update(occurred_at="2026-09-16T10:00:00.000"), "occurred_at must be UTC ISO-8601"),
    (lambda p: p.update(occurred_at="2026-02-30T10:00:00.000Z"), "not a valid calendar time"),
    (lambda p: p.update(occurred_at=None), "occurred_at is required"),
    (lambda p: p.update(started_at=p["occurred_at"]), "is instant"),
    (lambda p: p.update(span_id="s"), "is instant"),
    (lambda p: p.update(attributes=[]), "attributes must be an object"),
    (lambda p: p.update(trace_ref={"source": "runtime_journal", "journal_kind": "x.y"}), "trace_ref must have exactly"),
    (lambda p: p.update(trace_ref={"source": "logs", "journal_kind": "x.y", "join_keys": []}), "trace_ref.source"),
    (lambda p: p.update(trace_ref={"source": "runtime_journal", "journal_kind": "x.y", "join_keys": ["speech_id"]}),
     "names speech_id, which is not set"),
    (lambda p: p.update(trace_ref={"source": "runtime_journal", "journal_kind": "x.y", "join_keys": ["output_id"]}),
     "join_keys must be distinct names"),
    (lambda p: p.update(trace_ref={"source": "runtime_journal", "journal_kind": None, "join_keys": []}), "journal_kind"),
    (lambda p: p.update(trace_ref={"source": "agent_task", "journal_kind": None, "join_keys": ["turn_id"]}), "agent_task"),
])
def test_invalid_payloads_fail_with_precise_messages(mutate, message):
    payload = fixture_payload(T.USER_TRANSCRIPT_ACCEPTED)
    mutate(payload)
    with pytest.raises(ConversationEventError, match=message):
        validate_conversation_event(payload)


def test_non_object_payload_is_rejected():
    with pytest.raises(ConversationEventError, match="JSON object"):
        decode_conversation_event([])


@pytest.mark.parametrize("event_type, mutate, message", [
    (T.MOUTH_SPEECH_INTERRUPTED, lambda p: p.update(started_at="2026-09-16T10:00:03.000Z"), "span ends before it starts"),
    (T.MOUTH_SPEECH_INTERRUPTED, lambda p: p.update(ended_at="2026-09-16T10:00:03.000Z"), "ended_at must equal occurred_at"),
    (T.MOUTH_SPEECH_INTERRUPTED, lambda p: p.update(span_id=None), "span_id is required"),
    (T.MOUTH_SPEECH_INTERRUPTED, lambda p: p.update(span_id="speech-other"), "span_id for mouth.speech.interrupted must equal speech_id"),
    (T.MOUTH_SPEECH_STARTED, lambda p: p.update(ended_at=p["occurred_at"]), "opens a span"),
    (T.MOUTH_SPEECH_STARTED, lambda p: p.update(started_at="2026-09-16T10:00:00.000Z"), "opens a span"),
    (T.SUBAGENT_STARTED, lambda p: p.update(task_id=None), "task_id is required"),
    (T.BRAIN_TURN_ACCEPTED, lambda p: p.update(content="hidden text"), "content must be null"),
    (T.TOOL_CALL_STARTED, lambda p: p.update(content="get_time(tz=Paris)"), "content must be null"),
    (T.TOOL_CALL_STARTED, lambda p: p.update(trace_ref={"source": "runtime_journal", "journal_kind": "tool.call",
                                                         "join_keys": ["session_id"]}), "conversation_event_id only"),
    (T.BRAIN_MESSAGE_PUBLISHED, lambda p: p.update(outcome_id=None), "outcome_id is required"),
])
def test_shape_rules_per_event_type(event_type, mutate, message):
    payload = fixture_payload(event_type)
    mutate(payload)
    with pytest.raises(ConversationEventError, match=message):
        validate_conversation_event(payload)


def test_constructor_rejects_non_utc_and_sub_millisecond_times():
    with pytest.raises(ConversationEventError, match="must be UTC"):
        replace(make(T.SYSTEM_FAILURE), occurred_at=BASE.astimezone(timezone(timedelta(hours=2))))
    with pytest.raises(ConversationEventError, match="millisecond precision"):
        replace(make(T.SYSTEM_FAILURE), occurred_at=BASE + timedelta(microseconds=1))
    with pytest.raises(ConversationEventError, match="timezone-aware"):
        replace(make(T.SYSTEM_FAILURE), occurred_at=datetime(2026, 9, 16))
    with pytest.raises(ConversationEventError, match="event_type is not in the vocabulary"):
        replace(make(T.SYSTEM_FAILURE), event_type="system.failure")


def _fields(event: ConversationEvent) -> dict:
    return {name: getattr(event, name) for name in EVENT_FIELDS}


def test_error_messages_never_echo_private_values():
    payload = fixture_payload(T.USER_TRANSCRIPT_ACCEPTED)
    payload["producer"] = "SECRET-CONTENT-MARKER"
    with pytest.raises(ConversationEventError) as caught:
        validate_conversation_event(payload)
    assert "SECRET-CONTENT-MARKER" not in str(caught.value)


# ------------------------------------------------------------- redaction

@pytest.mark.parametrize("key", [
    "reasoning", "thinking", "thoughts", "chain_of_thought", "chainOfThought", "scratchpad", "audio", "pcm_bytes",
    "raw_audio", "system_prompt", "prompt", "api_key", "apiKey", "access_token", "secret", "password",
    "authorization", "arguments", "raw_arguments", "tool_input", "input", "thinking-signature",
])
def test_forbidden_keys_are_detected(key):
    assert is_forbidden_key(key)


@pytest.mark.parametrize("key", ["tokens", "tool_uses", "arguments_redacted", "played_ms", "status", "summary_length"])
def test_safe_keys_are_not_flagged(key):
    assert not is_forbidden_key(key)


@pytest.mark.parametrize("mutate, path", [
    (lambda p: p.update(reasoning="because"), "event.reasoning"),
    (lambda p: p.update(chain_of_thought=["step"]), "event.chain_of_thought"),
    (lambda p: p["attributes"].update(thinking="hidden"), "event.attributes.thinking"),
    (lambda p: p["attributes"].update(arguments={"q": "x"}), "event.attributes.arguments"),
    (lambda p: p["attributes"].update(status={"nested": {"system_prompt": "x"}}), "event.attributes.status.nested.system_prompt"),
    (lambda p: p["attributes"].update(status=[{"api_key": "k"}]), r"event.attributes.status\[0\].api_key"),
    (lambda p: p.update(trace_ref={"source": "runtime_journal", "journal_kind": "a.b", "join_keys": [], "raw_audio": "UklGR"}),
     "event.trace_ref.raw_audio"),
])
def test_forbidden_fields_are_rejected_at_any_depth(mutate, path):
    payload = fixture_payload(T.USER_TRANSCRIPT_ACCEPTED)
    mutate(payload)
    with pytest.raises(ConversationEventRedactionError, match=path):
        validate_conversation_event(payload)


def test_raw_bytes_are_rejected_on_construction_and_decode():
    with pytest.raises(ConversationEventRedactionError, match="raw bytes"):
        make(T.SYSTEM_FAILURE, attributes={"code": b"\x00\x01"})
    payload = fixture_payload(T.USER_TRANSCRIPT_ACCEPTED)
    payload["attributes"]["code"] = bytearray(b"RIFF")
    with pytest.raises(ConversationEventRedactionError, match="raw bytes"):
        validate_conversation_event(payload)


def test_constructor_applies_redaction_too():
    with pytest.raises(ConversationEventRedactionError, match="attributes.reasoning"):
        make(T.SYSTEM_FAILURE, attributes={"reasoning": "x"})


def test_agent_event_stream_is_never_a_valid_source():
    for kind in ("agent.event", "agent.event.thinking"):
        with pytest.raises(ConversationEventRedactionError, match="agent.event"):
            TraceRef(TraceSource.RUNTIME_JOURNAL, kind, ())
    assert not any(t.value.startswith("agent.") for t in ConversationEventType)


def test_attributes_outside_allowlist_are_rejected():
    with pytest.raises(ConversationEventError, match="not in the allowlist"):
        make(T.SYSTEM_FAILURE, attributes={"summary": "x"})


@pytest.mark.parametrize("event_type, extra", [
    (T.BRAIN_TURN_FAILED, {"correlation_id": "c-1"}),
    (T.SYSTEM_FAILURE, {}),
])
def test_failures_never_carry_free_text(event_type, extra):
    # core.brain.turn_failed carries a raw error string: only code/error_class may travel.
    with pytest.raises(ConversationEventError, match="content must be null"):
        make(event_type, content="RuntimeError: backend exploded", **extra)
    assert make(event_type, attributes={"code": "brain_backend_failed", "error_class": "RuntimeError"}, **extra)


# --------------------------------------------------------- input hygiene

SURROGATE = "a\ud800b"


@pytest.mark.parametrize("build", [
    lambda: make(T.MOUTH_REFLEX_STARTED, correlation_id="c-1", content=SURROGATE),
    lambda: make(T.SYSTEM_FAILURE, attributes={"reason": SURROGATE}),
    lambda: make(T.SYSTEM_FAILURE, attributes={"reason": ["ok", SURROGATE]}),
    lambda: make(T.SYSTEM_FAILURE, correlation_id=SURROGATE),
    lambda: make(T.SYSTEM_FAILURE, attributes={SURROGATE: 1}),
    lambda: make(T.SYSTEM_FAILURE, source=SURROGATE),
    lambda: derive_conversation_event_id(producer="p", event_type=T.SYSTEM_FAILURE, conversation_id=SURROGATE,
                                         source_ids=("x",)),
])
def test_lone_surrogates_raise_contract_error(build):
    with pytest.raises(ConversationEventError):
        build()


def test_lone_surrogate_in_decoded_payload_and_unknown_field_name():
    payload = fixture_payload(T.USER_TRANSCRIPT_ACCEPTED)
    payload["content"] = SURROGATE
    with pytest.raises(ConversationEventError, match="lone surrogate"):
        validate_conversation_event(payload)
    payload = fixture_payload(T.USER_TRANSCRIPT_ACCEPTED)
    payload[SURROGATE] = 1
    with pytest.raises(ConversationEventError) as caught:
        validate_conversation_event(payload)
    str(caught.value).encode("utf-8")  # the message itself stays encodable


@pytest.mark.parametrize("depth", [MAX_PAYLOAD_DEPTH + 1, 5000])
def test_deep_nesting_raises_contract_error_not_recursion_error(depth):
    nested: object = "leaf"
    for _ in range(depth):
        nested = {"reason": nested}
    payload = fixture_payload(T.USER_TRANSCRIPT_ACCEPTED)
    payload["attributes"] = {"status": nested}
    with pytest.raises(ConversationEventError, match="nesting exceeds"):
        validate_conversation_event(payload)


def test_cyclic_payload_raises_contract_error():
    cyclic: list = []
    cyclic.append(cyclic)
    payload = fixture_payload(T.USER_TRANSCRIPT_ACCEPTED)
    payload["attributes"] = {"status": cyclic}
    with pytest.raises(ConversationEventError, match="nesting exceeds"):
        validate_conversation_event(payload)


# ------------------------------------------------------------------ bounds

@pytest.mark.parametrize("attributes, message", [
    ({"reason": "x" * (MAX_ATTRIBUTE_TEXT_CHARS + 1)}, "exceeds 512 characters"),
    ({"reason": ["x"] * (MAX_ATTRIBUTE_LIST_ITEMS + 1)}, "exceeds 16 items"),
    ({"reason": [["nested"]]}, "must be a JSON scalar"),
    ({"reason": {"k": "v"}}, "must be a JSON scalar"),
    ({"revision": float("nan")}, "finite"),
    ({"revision": 2**60}, "integer exceeds"),
    ({key: "x" * 200 for key in sorted(ATTRIBUTE_KEYS)[:MAX_ATTRIBUTES]}, "encoded bytes"),
])
def test_attribute_bounds(attributes, message):
    with pytest.raises(ConversationEventError, match=message):
        make(T.SYSTEM_FAILURE, attributes=attributes)


def test_attribute_key_count_bound():
    assert len(ATTRIBUTE_KEYS) > MAX_ATTRIBUTES
    with pytest.raises(ConversationEventError, match=f"exceed {MAX_ATTRIBUTES} keys"):
        make(T.SYSTEM_FAILURE, attributes={key: 1 for key in sorted(ATTRIBUTE_KEYS)[:MAX_ATTRIBUTES + 1]})


def test_opaque_identifier_bound():
    with pytest.raises(ConversationEventError, match="correlation_id"):
        make(T.SYSTEM_FAILURE, correlation_id="c" * 257)
    assert make(T.SYSTEM_FAILURE, correlation_id="c" * 256).correlation_id


def test_content_at_bound_is_accepted():
    event = make(T.MOUTH_REFLEX_STARTED, correlation_id="c-1", content="é" * MAX_CONTENT_CHARS)
    assert len(event.content) == MAX_CONTENT_CHARS


# ---------------------------------------------------------- reconstruction

def test_fresh_consumer_reconstructs_overlapping_conversation_from_shuffled_events():
    document = load_fixture()
    events = fixture_events()
    random.Random(7).shuffle(events)
    assert as_rows(reconstruct_conversation(events)) == document["expected_timeline"]
    assert as_rows(reconstruct_conversation(events, include_diagnostic=False)) == document["expected_public_transcript"]


def test_reconstruction_shows_overlap_rather_than_chat_order():
    items = {(i.event_type, i.span_id): i for i in reconstruct_conversation(fixture_events())}
    ack = items[(T.MOUTH_SPEECH_STARTED, "speech-ack-1")]
    subagent = items[(T.SUBAGENT_STARTED, "task-7")]
    work = items[(T.BRAIN_WORK_STARTED, "work-tests")]
    second = items[(T.MOUTH_SPEECH_STARTED, "speech-2")]
    assert ack.status == "interrupted" and ack.ended_at > subagent.started_at  # speech overlaps sub-agent start
    assert work.started_at <= subagent.started_at and subagent.ended_at <= work.ended_at  # nested spans
    assert subagent.started_at < second.started_at < second.ended_at < subagent.ended_at
    assert items[(T.MOUTH_SPEECH_STARTED, "speech-3")].ended_at is None


def test_reconstruction_is_idempotent_over_duplicates():
    events = fixture_events()
    assert reconstruct_conversation(events + events[:5]) == reconstruct_conversation(events)


def test_reconstruction_keeps_first_copy_of_conflicting_duplicate():
    events = fixture_events()
    tampered = replace(events[0], content="Autre chose.")
    items = reconstruct_conversation(events + [tampered])
    first = next(i for i in items if i.item_id == events[0].event_id)
    assert first.text == events[0].content
    assert first.anomalies == (f"conflicting_duplicate:{events[0].event_id}",)
    with pytest.raises(ConversationEventConflictError):
        is_duplicate_event(events[0], tampered)


def test_reconstruction_raises_only_for_bad_input_types_or_mixed_conversations():
    other = ConversationEvent(**{**_fields(make(T.SYSTEM_FAILURE)), "conversation_id": "conv-other"})
    with pytest.raises(ConversationEventError, match="several conversations"):
        reconstruct_conversation([make(T.SYSTEM_FAILURE), other])
    with pytest.raises(ConversationEventError, match="ConversationEvent values only"):
        reconstruct_conversation([encode_conversation_event(make(T.SYSTEM_FAILURE))])


COMMON = dict(span_id="s-1", speech_id="s-1", correlation_id="c-1")


def test_duplicate_closes_keep_earliest_and_record_anomaly():
    opened = make(T.MOUTH_SPEECH_STARTED, **COMMON)
    completed = make(T.MOUTH_SPEECH_COMPLETED, ms=5, source="a", **COMMON)
    interrupted = make(T.MOUTH_SPEECH_INTERRUPTED, ms=6, source="b", **COMMON)
    item, = reconstruct_conversation([interrupted, opened, completed])
    assert (item.status, item.ended_at) == ("completed", completed.ended_at)
    assert item.event_ids == (opened.event_id, completed.event_id)
    assert item.anomalies == (f"duplicate_span_close:{interrupted.event_id}",)


def test_duplicate_opens_keep_earliest_and_record_anomaly():
    early = make(T.MOUTH_SPEECH_STARTED, ms=1, source="a", **COMMON)
    late = make(T.MOUTH_SPEECH_STARTED, ms=2, source="b", **COMMON)
    item, = reconstruct_conversation([late, early])
    assert (item.item_id, item.status, item.ended_at) == (early.event_id, "open", None)
    assert item.anomalies == (f"duplicate_span_open:{late.event_id}",)


def test_close_before_open_is_clamped_and_recorded():
    opened = make(T.MOUTH_SPEECH_STARTED, ms=10, **COMMON)
    closed = make(T.MOUTH_SPEECH_COMPLETED, ms=5, **COMMON)
    item, = reconstruct_conversation([opened, closed])
    assert item.started_at == item.ended_at == opened.started_at
    assert item.anomalies == (f"close_before_open:{closed.event_id}",)


def test_conflict_on_an_extra_span_event_lands_on_its_owner_item():
    early = make(T.MOUTH_SPEECH_STARTED, ms=1, source="a", **COMMON)
    late = make(T.MOUTH_SPEECH_STARTED, ms=2, source="b", **COMMON)
    item, = reconstruct_conversation([early, late, replace(late, content="Autre.")])
    assert item.anomalies == (f"duplicate_span_open:{late.event_id}", f"conflicting_duplicate:{late.event_id}")


def test_speech_failure_closes_the_mouth_span():
    assert SPAN_OPENER[T.MOUTH_SPEECH_FAILED] is T.MOUTH_SPEECH_STARTED
    failure = {"code": "speech_speak_failed", "error_class": "RuntimeError"}
    item, = reconstruct_conversation([make(T.MOUTH_SPEECH_STARTED, **COMMON),
                                      make(T.MOUTH_SPEECH_FAILED, ms=40, attributes=failure, **COMMON)])
    assert (item.status, item.visibility) == ("failed", ConversationVisibility.PUBLIC)
    lone, = reconstruct_conversation([make(T.MOUTH_SPEECH_FAILED, ms=40, **COMMON)])
    assert lone.visibility is ConversationVisibility.DIAGNOSTIC
    assert reconstruct_conversation([make(T.MOUTH_SPEECH_FAILED, ms=40, **COMMON)], include_diagnostic=False) == ()


def test_close_without_open_is_rendered_from_its_own_times():
    common = dict(span_id="s-9", speech_id="s-9", correlation_id="c-9")
    expired, = reconstruct_conversation([make(T.MOUTH_SPEECH_EXPIRED, ms=500, **common)])
    assert (expired.status, expired.started_at, expired.ended_at) == ("expired", expired.ended_at, BASE + timedelta(milliseconds=500))
    late, = reconstruct_conversation([make(T.SUBAGENT_FAILED, ms=900, span_id="t-1", task_id="t-1", started_at=BASE)])
    assert (late.status, late.started_at) == ("failed", BASE)


def test_empty_input_reconstructs_to_empty_conversation():
    assert reconstruct_conversation([]) == ()


# ------------------------------------------------------------- correlation

def test_events_join_by_correlation_ids_across_actors():
    events = fixture_events()
    first_turn = [e for e in events if e.correlation_id == "voice-source-1"]
    assert {e.actor for e in first_turn} == {ConversationActor.USER, ConversationActor.BRAIN, ConversationActor.MOUTH}
    by_speech = {e.event_type for e in events if e.speech_id == "speech-ack-1"}
    assert by_speech == {T.BRAIN_SPEECH_REQUESTED, T.MOUTH_SPEECH_QUEUED, T.MOUTH_SPEECH_STARTED, T.MOUTH_SPEECH_INTERRUPTED}
    work = next(e for e in events if e.event_type is T.BRAIN_WORK_STARTED)
    subagent = [e for e in events if e.task_id == "task-7"]
    assert all(e.parent_event_id == work.event_id and e.work_id == work.work_id for e in subagent)
    user_turns = {e.turn_id for e in events if e.actor is ConversationActor.USER}
    assert user_turns == {e.turn_id for e in events if e.event_type is T.BRAIN_TURN_ACCEPTED}


def test_trace_ref_joins_real_runtime_journal_shapes():
    events = {(e.event_type, e.span_id or e.speech_id or e.correlation_id): e for e in fixture_events()}
    interrupted = events[(T.MOUTH_SPEECH_INTERRUPTED, "speech-ack-1")]
    # Shape emitted by SpeechScheduler._trace(SPEECH_INTERRUPTED, ...) with _fields(request).
    line = {"ts": "2026-09-16T10:00:02.450123+00:00", "kind": "voice.speech.interrupted", "level": "warning",
            "message": "Speech interrupted",
            "data": {"conversation_id": CONV, "session_id": "voice-session-1", "speech_id": "speech-ack-1",
                     "correlation_id": "voice-source-1", "work_id": None, "kind": "ack", "priority": "normal",
                     "output_id": "output-1", "status": "cancelled", "played_ms": 1200}}
    assert trace_entry_matches(interrupted, line)
    assert not trace_entry_matches(interrupted, {**line, "kind": "voice.speech.completed"})
    assert not trace_entry_matches(interrupted, {**line, "data": {**line["data"], "speech_id": "speech-2"}})
    # Once instrumented (Slice 03), the carried event id decides.
    assert trace_entry_matches(interrupted, {**line, "data": {"conversation_event_id": interrupted.event_id}})
    assert not trace_entry_matches(interrupted, {**line, "data": {**line["data"], "conversation_event_id": "cev-" + "0" * 64}})
    submitted = events[(T.USER_TRANSCRIPT_ACCEPTED, "voice-source-2")]
    # Shape emitted by realtime_audio `voice.brain_turn_submitted` (the source live traces actually contain).
    voice_line = {"kind": "voice.brain_turn_submitted", "data": {
        "conversation_id": CONV, "session_id": "voice-session-1", "correlation_id": "voice-source-2",
        "addressing": "addressed", "provider_item_id": "item-2", "interrupted_speech_id": "speech-ack-1",
        "turn_id": "brain-turn-2", "revision": 8, "duplicate": False}}
    assert trace_entry_matches(submitted, voice_line)
    admitted = events[(T.USER_TRANSCRIPT_ACCEPTED, "voice-source-1")]
    core_line = {"kind": "core.voice.turn_admitted", "data": {"conversation_id": CONV, "correlation_id": "voice-source-1",
                                                               "session_id": "voice-session-1", "turn_id": "brain-turn-1"}}
    assert trace_entry_matches(admitted, core_line)


def test_outcome_id_disambiguates_several_outcome_lines_per_correlation():
    message = next(e for e in fixture_events() if e.event_type is T.BRAIN_MESSAGE_PUBLISHED)
    # brain_outcomes.py retains work_result and turn_result under one correlation_id.
    lines = [{"kind": "core.brain.outcome_retained",
              "data": {"conversation_id": CONV, "correlation_id": "voice-source-1", "outcome_id": outcome_id,
                       "kind": kind, "status": "completed"}}
             for outcome_id, kind in (("outcome-work-tests", "work_result"), ("outcome-turn-1", "turn_result"))]
    assert [trace_entry_matches(message, line) for line in lines] == [True, False]


def test_trace_ref_without_keys_joins_only_by_event_id():
    tool = next(e for e in fixture_events() if e.event_type is T.TOOL_CALL_STARTED)
    assert not trace_entry_matches(tool, {"kind": "tool.call", "data": {"call_id": "call-1"}})
    assert trace_entry_matches(tool, {"kind": "tool.call", "data": {"conversation_event_id": tool.event_id}})
    assert not trace_entry_matches(make(T.SYSTEM_FAILURE), {"kind": "x.y", "data": {}})
    subagent = next(e for e in fixture_events() if e.event_type is T.SUBAGENT_STARTED)
    assert subagent.trace_ref == TraceRef(TraceSource.AGENT_TASK, None, ("task_id",))
    with pytest.raises(ConversationEventError, match="runtime_journal"):
        trace_entry_matches(subagent, {"kind": "agent.subagent.started", "data": {}})


def test_schema_version_constant_matches_wire():
    assert CONVERSATION_EVENT_SCHEMA_VERSION == 1
    assert all(row["event"]["schema_version"] == 1 for row in load_fixture()["events"])
    assert set(load_fixture()["events"][0]["event"]) == set(EVENT_FIELDS)
    assert ConversationVisibility.PUBLIC.value == "public"
