from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from jarvis.domain.front_brain_hints import (
    FrontBrainHintRequest, FrontBrainHintResult, FrontBrainHintValue, HintAnalysisStatus,
    decode_front_brain_hint, encode_front_brain_hint,
)
from jarvis.domain.reflex_policy import ReflexAction, decide_reflex
from jarvis.domain.speech_presentation import SpeechDependency, SpeechSource
from jarvis.domain.v2 import SpeechPriority
from jarvis.domain.voice_events import UserCommitSource
from jarvis.domain.voice_frontend import VoiceContext, VoiceContextMessage, VoiceContextRole, VoiceCorrelation
from jarvis.domain.voice_state import VoiceUserRecord
from jarvis.ports.front_brain import FrontBrainAnalyzer
from jarvis.runtime.front_brain_hints import FrontBrainHintConsumer, HintConsumptionDisposition as Disposition, HintIgnoreReason as Reason
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from tests.fakes.front_brain import FakeFrontBrainAnalyzer


def request(**changes):
    source_a = SpeechSource("core-turn-A", "correlation-A", "intent-A", 7)
    values = dict(request_id="request-B", input=VoiceUserRecord(
        VoiceCorrelation(session_id="frontend-B", turn_id="canonical-turn-B"), "transcript-B", 2, "Private provisional B"),
        origin_source=None, context_source=source_a, context=VoiceContext(revision=88),
        analysis_admission_id="admitted-analysis", configuration_id="config-1", deadline_monotonic_ns=100)
    return FrontBrainHintRequest(**{**values, **changes})


def consume(consumer, expected, result=None, **changes):
    current = dict(current_input=expected.input, current_origin_source=expected.origin_source,
                   current_context_source=expected.context_source, current_configuration_id=expected.configuration_id,
                   current_admission_id=expected.analysis_admission_id, source_complete=True,
                   invalidated_dependencies=(), now_monotonic_ns=50)
    result = result or FrontBrainHintResult(expected.request_id, HintAnalysisStatus.AVAILABLE,
                                            FrontBrainHintValue(suggested_action=ReflexAction.SPEAK), 10)
    return consumer.consume(result, **{**current, **changes})


@pytest.mark.parametrize("action", [None, *ReflexAction])
def test_strict_value_roundtrip_nullable_suggestions(action):
    value = FrontBrainHintValue(action, "maybe a question", 0.5, 1, None, SpeechPriority.HIGH)
    assert decode_front_brain_hint(json.dumps(encode_front_brain_hint(value))) == value
    assert FrontBrainHintValue().suggested_action is None
    assert "maybe a question" not in repr(value)


@pytest.mark.parametrize("field,value", [("confidence", True), ("confidence", float("nan")),
    ("addressed_confidence", float("inf")), ("confidence", -0.1), ("confidence", 1.1),
    ("confidence", "0.5"), ("likely_backend_needed", 1), ("intent_hypothesis", "x" * 513),
    ("suggested_action", "speak"), ("urgency", 40)],
    ids=["bool-confidence", "nan", "inf", "negative", "over-one", "string", "int-bool", "long-hypothesis", "untyped-action", "untyped-priority"])
def test_value_rejects_invalid_types_and_ranges(field, value):
    with pytest.raises(ValueError):
        FrontBrainHintValue(**{field: value})


@pytest.mark.parametrize("raw", [
    '{"confidence":0.5,"confidence":0.6}', '{"extra":{"x":1,"x":2}}',
    '{"confidence":NaN}', '{"confidence":Infinity}', '{"confidence":1e999}',
    '[]', 'null', '{}', '{"schema_version":true}', '["' + "x" * 8200 + '"]',
    '{"schema_version":1,"tool":{"name":"delete"}}', "[" * 4000 + "]" * 4000,
], ids=["duplicate", "nested-duplicate", "nan", "infinity", "overflow", "array", "null", "missing", "boolean-version", "oversize", "executable", "depth"])
def test_raw_json_is_strict_before_schema_validation(raw):
    with pytest.raises(ValueError):
        decode_front_brain_hint(raw)


@pytest.mark.parametrize("field,value", [("schema_version", 2), ("confidence", {}), ("urgency", "HIGH"),
                                       ("suggested_action", "invented"), ("extra", None)])
def test_value_json_rejects_wrong_shape_and_enum(field, value):
    payload = encode_front_brain_hint(FrontBrainHintValue())
    payload[field] = value
    with pytest.raises(ValueError):
        decode_front_brain_hint(json.dumps(payload))


def test_request_bounds_are_aggregate_and_sources_keep_distinct_namespaces():
    original = request()
    assert original.origin_source is None and original.context_source.turn_id == "core-turn-A"
    assert original.input.correlation.turn_id == "canonical-turn-B"
    # A canonical commit is not a fabricated Core turn. Explicit linkage uses
    # correlation, never equality of Core and canonical turn IDs.
    linked = replace(original.input, correlation=replace(original.input.correlation, source_correlation_id="correlation-B"))
    source_b = SpeechSource("different-core-B", "correlation-B", "intent-B", 8)
    assert request(input=linked, origin_source=source_b).origin_source == source_b
    with pytest.raises(ValueError):
        request(input=linked, origin_source=original.context_source)
    with pytest.raises(ValueError):
        request(context=VoiceContext(messages=tuple(VoiceContextMessage(VoiceContextRole.USER, "x") for _ in range(9))))
    large = replace(original.input, text="x" * 8192)
    request(input=large, context=VoiceContext(messages=(VoiceContextMessage(VoiceContextRole.USER, "x" * 8192),)))
    with pytest.raises(ValueError):
        request(input=large, context=VoiceContext(messages=(VoiceContextMessage(VoiceContextRole.USER, "x" * 8192), VoiceContextMessage(VoiceContextRole.USER, "x"))))
    with pytest.raises(FrozenInstanceError):
        original.request_id = "changed"


@pytest.mark.parametrize("role", ["tool", "user", None, 1])
def test_request_rejects_untyped_or_unknown_context_role(role):
    with pytest.raises(ValueError, match="roles must be typed"):
        request(context=VoiceContext(messages=(VoiceContextMessage(role, "selected content"),)))


@pytest.mark.parametrize("role", list(VoiceContextRole))
def test_request_preserves_supported_context_roles(role):
    assert request(context=VoiceContext(messages=(VoiceContextMessage(role, "selected content"),))).context.messages[0].role is role


@pytest.mark.parametrize("status", list(HintAnalysisStatus))
def test_result_distinguishes_available_from_unavailable(status):
    value = FrontBrainHintValue() if status is HintAnalysisStatus.AVAILABLE else None
    FrontBrainHintResult("request", status, value, 0)
    with pytest.raises(ValueError):
        FrontBrainHintResult("request", status, None if value else FrontBrainHintValue(), 0)


def test_available_without_action_is_not_wait():
    expected = request()
    consumer = FrontBrainHintConsumer()
    consumer.expect(expected)
    result = FrontBrainHintResult(expected.request_id, HintAnalysisStatus.AVAILABLE, FrontBrainHintValue(intent_hypothesis="maybe"), 10)
    consumed = consume(consumer, expected, result)
    assert consumed.disposition is Disposition.NO_SUGGESTION
    assert consumed.value.suggested_action is None


@pytest.mark.parametrize("now,received", [(100, 10), (101, 10), (50, 100)])
def test_deadline_is_exclusive_at_consumption_not_only_receipt(now, received):
    expected = request()
    consumer = FrontBrainHintConsumer()
    consumer.expect(expected)
    result = FrontBrainHintResult(expected.request_id, HintAnalysisStatus.AVAILABLE, FrontBrainHintValue(ReflexAction.SPEAK), received)
    assert consume(consumer, expected, result, now_monotonic_ns=now).reason is Reason.EXPIRED


def test_same_request_does_not_rearm_consumption_or_change_deadline():
    expected = request()
    consumer = FrontBrainHintConsumer()
    assert consumer.expect(expected)
    assert consume(consumer, expected).disposition is Disposition.ACCEPTED
    assert not consumer.expect(expected)
    assert consume(consumer, expected).reason is Reason.DUPLICATE
    with pytest.raises(ValueError):
        consumer.expect(replace(expected, deadline_monotonic_ns=200))
    consumer.invalidate()
    assert not consumer.expect(expected)
    assert consume(consumer, expected).reason is Reason.DUPLICATE


@pytest.mark.parametrize("change,reason", [
    ({"current_configuration_id": "config-2"}, Reason.CONFIGURATION_CHANGED),
    ({"current_admission_id": None}, Reason.ADMISSION_REVOKED),
    ({"source_complete": False}, Reason.SOURCE_INCOMPLETE),
    ({"current_context_source": None}, Reason.CONTEXT_CHANGED),
])
def test_current_analysis_binding_is_required(change, reason):
    expected = request()
    consumer = FrontBrainHintConsumer()
    consumer.expect(expected)
    assert consume(consumer, expected, **change).reason is reason


def test_revision_commit_and_session_changes_reject_old_hint():
    expected = request()
    changes = [replace(expected.input, revision=3),
               replace(expected.input, committed=True, commit_source=UserCommitSource.APPLICATION),
               replace(expected.input, correlation=replace(expected.input.correlation, session_id="frontend-C"))]
    for current_input in changes:
        consumer = FrontBrainHintConsumer()
        consumer.expect(expected)
        assert consume(consumer, expected, current_input=current_input).disposition is Disposition.IGNORED


def test_exact_dependency_revocation_and_unrelated_context_revision():
    expected = request(context_source=SpeechSource("core-A", "corr-A", "intent-A", 7, (SpeechDependency("work", "corr-A"),)))
    consumer = FrontBrainHintConsumer()
    consumer.expect(expected)
    # Revision 99 instead of 88 may describe audio/progress; not hint-source equality.
    current = replace(expected, context=replace(expected.context, revision=99))
    assert consume(consumer, current, invalidated_dependencies=(SpeechDependency("work", "other"),)).disposition is Disposition.ACCEPTED
    consumer.expect(replace(expected, request_id="new"))
    assert consume(consumer, replace(expected, request_id="new"), invalidated_dependencies=(SpeechDependency("work", "corr-A"),)).reason is Reason.DEPENDENCY_REVOKED


async def test_slow_fake_result_cannot_replace_latest_expectation():
    gate = asyncio.Event()
    fake = FakeFrontBrainAnalyzer(value=FrontBrainHintValue(ReflexAction.DELEGATE), status=HintAnalysisStatus.AVAILABLE, gate=gate, clock_ns=lambda: 20)
    assert isinstance(fake, FrontBrainAnalyzer)
    old = request()
    consumer = FrontBrainHintConsumer()
    consumer.expect(old)
    task = asyncio.create_task(fake.analyze(old))
    try:
        await asyncio.wait_for(fake.started.wait(), 1)
        latest = replace(old, request_id="new", input=replace(old.input, revision=3, text="new snapshot"))
        consumer.expect(latest)
        gate.set()
        assert consume(consumer, latest, await asyncio.wait_for(task, 1)).reason is Reason.REQUEST_MISMATCH
        assert consumer.expected_request_id == latest.request_id
        assert consume(consumer, latest).disposition is Disposition.ACCEPTED
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_fake_cancellation_cleanup_and_bounded_inventory():
    gate = asyncio.Event()
    fake = FakeFrontBrainAnalyzer(gate=gate)
    task = asyncio.create_task(fake.analyze(request()))
    await asyncio.wait_for(fake.started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert fake.active_count == 0 and fake.cancelled_count == 1
    gate.set()
    for index in range(40):
        await fake.analyze(request(request_id=f"request-{index}"))
    assert len(fake.requests) == 32 and fake.active_count == 0


@pytest.mark.parametrize("status", [status for status in HintAnalysisStatus if status is not HintAnalysisStatus.AVAILABLE])
async def test_unavailable_fake_is_not_wait_or_a_direct_response_dependency(status):
    expected = request()
    consumer = FrontBrainHintConsumer()
    consumer.expect(expected)
    result = await FakeFrontBrainAnalyzer(status=status).analyze(expected)
    consumed = consume(consumer, expected, result, useful_ready=True)
    assert consumed.reason is Reason.ANALYSIS_UNAVAILABLE and consumed.value is None
    assert decide_reflex(text="Question utile", enabled=True, admitted=True, user_speaking=False,
                         useful_ready=True, work_confirmed=False, work_terminal=False,
                         noticeable_wait=False, already_used=False, stale=False).action is ReflexAction.SPEAK


@pytest.mark.parametrize("action", [ReflexAction.WAIT, ReflexAction.PREAMBLE, ReflexAction.BACKCHANNEL])
def test_hint_does_not_hold_ready_content(action):
    expected = request()
    consumer = FrontBrainHintConsumer()
    consumer.expect(expected)
    result = FrontBrainHintResult(expected.request_id, HintAnalysisStatus.AVAILABLE, FrontBrainHintValue(action), 10)
    assert consume(consumer, expected, result, useful_ready=True).reason is Reason.USEFUL_CONTENT_READY


def test_advisory_consumer_has_no_mutation_or_execution_capability(tmp_path):
    journal = RuntimeJournal(tmp_path)
    expected = request()
    original = expected.input
    for action in (ReflexAction.PREAMBLE, ReflexAction.DELEGATE):
        consumer = FrontBrainHintConsumer(journal)
        consumer.expect(expected)
        result = FrontBrainHintResult(expected.request_id, HintAnalysisStatus.AVAILABLE,
                                      FrontBrainHintValue(action, "PRIVATE_HYPOTHESIS", 1, 1, True, SpeechPriority.IMMEDIATE), 10)
        assert consume(consumer, expected, result).value.suggested_action is action
        assert expected.input == original and not original.committed
        # A confident PREAMBLE does not create Task06's missing work evidence.
        decision = decide_reflex(text="Question utile", enabled=True, admitted=True, user_speaking=False,
                                 useful_ready=False, work_confirmed=False, work_terminal=False,
                                 noticeable_wait=True, already_used=False, stale=False)
        assert decision.action is ReflexAction.WAIT and decision.reason == "work_unconfirmed"
    rows = read_jsonl_tail(journal.trace_path)
    assert [row["kind"] for row in rows] == ["voice.hint.expected", "voice.hint.consumed"] * 2
    assert all(row["level"] == "info" for row in rows)
    assert "PRIVATE_" not in json.dumps(rows) and "Private provisional" not in json.dumps(rows)
    assert read_jsonl_tail(journal.error_path) == []
