"""Independent Task09 adversarial review; no provider or production mutation."""
from dataclasses import FrozenInstanceError, replace
import inspect
import json

import pytest

from jarvis.domain.front_brain_hints import (
    FrontBrainHintRequest, FrontBrainHintValue, FrontBrainHintResult,
    HintAnalysisStatus, decode_front_brain_hint, encode_front_brain_hint,
)
from jarvis.domain.reflex_policy import ReflexAction, decide_reflex
from jarvis.domain.speech_presentation import SpeechSource, SpeechDependency
from jarvis.domain.v2 import SpeechPriority
from jarvis.domain.voice_events import UserCommitSource
from jarvis.domain.voice_frontend import VoiceContext, VoiceContextMessage, VoiceContextRole, VoiceCorrelation
from jarvis.domain.voice_state import VoiceUserRecord
from jarvis.ports.front_brain import FrontBrainAnalyzer
from jarvis.runtime.front_brain_hints import (
    FrontBrainHintConsumer, HintConsumptionDisposition, HintIgnoreReason,
)


def input_b():
    return VoiceUserRecord(VoiceCorrelation("session-B", provider_input_id="input-B", source_correlation_id="source-B"),
                           "transcript-B", 2, "Provisional B", committed=False)


def context_a():
    return SpeechSource("core-turn-A", "source-A", "core-turn-A", 1,
                        (SpeechDependency("work-A", "source-A"),))


def request():
    return FrontBrainHintRequest("request-B", input_b(), None, context_a(), VoiceContext(revision=4),
                                 "analysis-admission", "configuration-1", 100)


def available(value=None, *, request_id="request-B", received=80):
    return FrontBrainHintResult(request_id, HintAnalysisStatus.AVAILABLE,
                                value or FrontBrainHintValue(suggested_action=ReflexAction.SPEAK), received)


@pytest.mark.parametrize("fragment", [
    '"confidence":0.2,"confidence":0.9',
    '"confidence":NaN', '"confidence":Infinity', '"confidence":-Infinity',
    '"confidence":1e999', '"confidence":-1e999',
    '"confidence":{"nested":1e999}',
    '"confidence":{"nested":0.2,"nested":0.3}',
    '"confidence":true', '"confidence":[]',
], ids=["duplicate", "nan", "infinity", "negative_infinity", "overflow", "negative_overflow",
        "nested_overflow", "nested_duplicate", "boolean", "array"])
def test_model_json_rejects_ambiguous_or_nonfinite_values(fragment):
    raw = json.dumps(encode_front_brain_hint(FrontBrainHintValue()))
    raw = raw.replace('"confidence": null', fragment)
    with pytest.raises(ValueError):
        decode_front_brain_hint(raw)


@pytest.mark.parametrize("patch", [
    {"schema_version": True}, {"schema_version": 2}, {"suggested_action": "execute"},
    {"urgency": 3}, {"likely_backend_needed": 1}, {"intent_hypothesis": {"text": "run"}},
    {"request_id": "model-selected"}, {"deadline_monotonic_ns": 999999},
    {"tool": "shell"}, {"speech": "Say these words"},
])
def test_model_value_cannot_expand_shape_or_claim_app_authority(patch):
    payload = {**encode_front_brain_hint(FrontBrainHintValue()), **patch}
    with pytest.raises(ValueError):
        decode_front_brain_hint(json.dumps(payload))


def test_missing_field_and_null_are_distinct_and_unknowns_roundtrip():
    value = FrontBrainHintValue()
    payload = encode_front_brain_hint(value)
    assert decode_front_brain_hint(json.dumps(payload)) == value
    assert all(item is None for key, item in payload.items() if key != "schema_version")
    del payload["confidence"]
    with pytest.raises(ValueError):
        decode_front_brain_hint(json.dumps(payload))


@pytest.mark.parametrize("field", ["confidence", "addressed_confidence"])
def test_huge_finite_json_integer_is_a_validation_rejection_not_overflow(field):
    raw = json.dumps(encode_front_brain_hint(FrontBrainHintValue()))
    raw = raw.replace(f'"{field}": null', f'"{field}":' + "9" * 512)
    with pytest.raises(ValueError):
        decode_front_brain_hint(raw)


def test_provisional_b_can_use_a_as_context_without_inventing_b_origin():
    selected = request()
    assert selected.origin_source is None
    assert selected.context_source == context_a()
    assert selected.input.correlation.turn_id is None and not selected.input.committed
    with pytest.raises(ValueError, match="origin"):
        replace(selected, origin_source=context_a())
    with pytest.raises(FrozenInstanceError):
        selected.origin_source = context_a()


def test_request_aggregate_bound_counts_input_and_selected_history():
    selected = request()
    full_input = replace(selected.input, text="b" * 8192)
    boundary = VoiceContext(messages=(VoiceContextMessage(VoiceContextRole.USER, "a" * 8192),))
    assert replace(selected, input=full_input, context=boundary).origin_source is None
    overflow = replace(boundary, messages=boundary.messages + (VoiceContextMessage(VoiceContextRole.USER, "x"),))
    with pytest.raises(ValueError):
        replace(selected, input=full_input, context=overflow)
    with pytest.raises(ValueError):
        replace(selected, context=VoiceContext(messages=tuple(VoiceContextMessage(VoiceContextRole.USER, "x") for _ in range(9))))


@pytest.mark.parametrize("value", [True, -1, 1.5, float("inf"), 2**63])
def test_process_local_deadline_is_strict(value):
    with pytest.raises(ValueError):
        replace(request(), deadline_monotonic_ns=value)


def test_port_has_only_analysis_and_no_execution_handle():
    signature = inspect.signature(FrontBrainAnalyzer.analyze)
    assert list(signature.parameters) == ["self", "request"]
    public_methods = {name for name, value in vars(FrontBrainAnalyzer).items() if callable(value) and not name.startswith("_")}
    assert public_methods == {"analyze"}


def consume(consumer, result=None, **changes):
    args = dict(current_input=input_b(), current_origin_source=None,
                current_context_source=context_a(), current_configuration_id="configuration-1",
                current_admission_id="analysis-admission", source_complete=True,
                invalidated_dependencies=(), now_monotonic_ns=90)
    args.update(changes)
    return consumer.consume(result or available(), **args)


@pytest.mark.parametrize("now", [100, 101, 100000])
def test_received_before_deadline_is_expired_when_consumed_later(now):
    consumer = FrontBrainHintConsumer()
    consumer.expect(request())
    result = available(received=80)
    decision = consume(consumer, result, now_monotonic_ns=now)
    assert decision.reason is HintIgnoreReason.EXPIRED
    assert decision.value is None
    assert consumer.expect(request()) is False
    assert consume(consumer, result, now_monotonic_ns=90).reason is HintIgnoreReason.DUPLICATE
    with pytest.raises(ValueError):
        consumer.expect(replace(request(), deadline_monotonic_ns=1000))


def test_current_hint_before_deadline_is_accepted_once():
    consumer = FrontBrainHintConsumer()
    assert consumer.expect(request()) is True
    decision = consume(consumer, now_monotonic_ns=99)
    assert decision.disposition is HintConsumptionDisposition.ACCEPTED
    assert decision.value.suggested_action is ReflexAction.SPEAK
    assert consume(consumer).reason is HintIgnoreReason.DUPLICATE


@pytest.mark.parametrize("change, expected", [
    ({"current_input": replace(input_b(), revision=3)}, HintIgnoreReason.INPUT_CHANGED),
    ({"current_input": replace(input_b(), text="Different B")}, HintIgnoreReason.INPUT_CHANGED),
    ({"current_input": replace(input_b(), correlation=replace(input_b().correlation, session_id="new-session"))}, HintIgnoreReason.SESSION_CHANGED),
    ({"current_configuration_id": "configuration-2"}, HintIgnoreReason.CONFIGURATION_CHANGED),
    ({"current_admission_id": None}, HintIgnoreReason.ADMISSION_REVOKED),
    ({"current_admission_id": "different-admission"}, HintIgnoreReason.ADMISSION_REVOKED),
    ({"source_complete": False}, HintIgnoreReason.SOURCE_INCOMPLETE),
    ({"current_context_source": replace(context_a(), intent_epoch=2)}, HintIgnoreReason.CONTEXT_CHANGED),
    ({"current_origin_source": SpeechSource("core-B", "source-B", "core-B", 2)}, HintIgnoreReason.ORIGIN_CHANGED),
    ({"invalidated_dependencies": (SpeechDependency("work-A", "source-A"),)}, HintIgnoreReason.DEPENDENCY_REVOKED),
], ids=["revision", "text", "session", "configuration", "revoked", "admission_changed", "gap", "context", "origin", "dependency"])
def test_old_hint_cannot_cross_current_application_evidence(change, expected):
    consumer = FrontBrainHintConsumer()
    consumer.expect(request())
    decision = consume(consumer, **change)
    assert decision.reason is expected
    assert decision.disposition is HintConsumptionDisposition.IGNORED and decision.value is None


def test_commit_invalidates_provisional_hint_even_with_identical_text_and_revision():
    consumer = FrontBrainHintConsumer()
    consumer.expect(request())
    final = replace(input_b(), correlation=replace(input_b().correlation, turn_id="canonical-B"),
                    committed=True, commit_source=UserCommitSource.PROVIDER)
    assert final.text == input_b().text and final.revision == input_b().revision
    assert consume(consumer, current_input=final).reason is HintIgnoreReason.INPUT_CHANGED


def test_wrong_request_result_does_not_consume_the_new_expectation():
    consumer = FrontBrainHintConsumer()
    consumer.expect(request())
    newer = replace(request(), request_id="new-request", input=replace(input_b(), revision=3))
    consumer.expect(newer)
    assert consume(consumer).reason is HintIgnoreReason.REQUEST_MISMATCH
    decision = consume(consumer, available(request_id="new-request"), current_input=newer.input)
    assert decision.disposition is HintConsumptionDisposition.ACCEPTED


def test_revocation_cannot_be_undone_by_registering_the_same_request():
    consumer = FrontBrainHintConsumer()
    consumer.expect(request())
    consumer.invalidate(HintIgnoreReason.ADMISSION_REVOKED)
    assert consumer.expect(request()) is False
    assert consume(consumer).reason is HintIgnoreReason.DUPLICATE


def test_other_work_generation_does_not_revoke_current_hint():
    consumer = FrontBrainHintConsumer()
    consumer.expect(request())
    decision = consume(consumer, invalidated_dependencies=(SpeechDependency("work-A", "older-source"),))
    assert decision.disposition is HintConsumptionDisposition.ACCEPTED
    assert consumer._expected.origin_source is None
    assert consumer._expected.context_source == context_a()


@pytest.mark.parametrize("action", [ReflexAction.WAIT, ReflexAction.BACKCHANNEL, ReflexAction.PREAMBLE])
def test_silence_or_preamble_advice_cannot_block_a_ready_direct_answer(action):
    consumer = FrontBrainHintConsumer()
    consumer.expect(request())
    advice = FrontBrainHintValue(suggested_action=action, confidence=1, urgency=SpeechPriority.HIGH)
    decision = consume(consumer, available(advice), useful_ready=True)
    assert decision.reason is HintIgnoreReason.USEFUL_CONTENT_READY and decision.value is None
    actual = decide_reflex(text="Compare the prices", enabled=True, admitted=True, user_speaking=False,
        useful_ready=True, work_confirmed=False, work_terminal=False, noticeable_wait=True,
        already_used=False, stale=False)
    assert actual.action is ReflexAction.SPEAK


@pytest.mark.parametrize("action", [ReflexAction.PREAMBLE, ReflexAction.DELEGATE])
def test_action_advice_neither_attests_work_nor_executes_or_commits(action):
    consumer = FrontBrainHintConsumer()
    original = request()
    consumer.expect(original)
    advice = FrontBrainHintValue(suggested_action=action, likely_backend_needed=True, addressed_confidence=1)
    decision = consume(consumer, available(advice))
    assert decision.value == advice
    assert consumer._expected == original and not original.input.committed
    assert original.origin_source is None
    # Independent Task06 authority still sees no confirmed work.
    actual = decide_reflex(text="Compare the prices", enabled=True, admitted=True, user_speaking=False,
        useful_ready=False, work_confirmed=False, work_terminal=False, noticeable_wait=True,
        already_used=False, stale=False)
    assert actual.action is ReflexAction.WAIT and actual.reason == "work_unconfirmed"
    assert list(inspect.signature(FrontBrainHintConsumer).parameters) == ["diagnostics"]
    assert not any(hasattr(consumer, name) for name in ("submit_turn", "submit_job", "speak", "call_tool", "commit"))


@pytest.mark.parametrize("status", [status for status in HintAnalysisStatus if status is not HintAnalysisStatus.AVAILABLE])
def test_unavailability_is_not_model_wait(status):
    consumer = FrontBrainHintConsumer()
    consumer.expect(request())
    decision = consume(consumer, FrontBrainHintResult("request-B", status, None, 80))
    assert decision.reason is HintIgnoreReason.ANALYSIS_UNAVAILABLE
    assert decision.analysis_status is status and decision.value is None
