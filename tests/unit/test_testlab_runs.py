"""Conformance tests for the Test Lab TestRun record and state machine (docs/testlab.md, TestRun)."""

from __future__ import annotations

from dataclasses import replace
import itertools
import json

import pytest

from jarvis.testlab.diagnostics import AssertionOutcome, AssertionResult, evaluate_assertion
from jarvis.testlab.identity import format_bundle_id, format_run_id, format_sweep_id
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import (
    FAILURE_ASSERTIONS_INCONCLUSIVE,
    MAX_FAILURE_DETAIL_CHARS,
    RUN_TRANSITIONS,
    TERMINAL_STATUSES,
    TRANSITION_ILLEGAL,
    ArtifactKind,
    ArtifactRef,
    CodeIdentity,
    RunFailure,
    RunStatus,
    RunTransitionError,
    TestRun,
    can_transition,
    check_run_against_spec,
    check_transition,
    complete_run,
    transition_run,
)
from jarvis.testlab.validation import (
    FIELDS_MISMATCH,
    FORBIDDEN_PRIVATE_DATA,
    REFERENCE_INVALID,
    SCHEMA_UNSUPPORTED,
    ForbiddenCodeError,
    TestLabError,
    TestLabRedactionError,
)
from tests.fakes.testlab import ENVIRONMENT, NONCE, T0, at, queued_run, self_echo_spec

S = RunStatus
SPEC = self_echo_spec()
PASSING = {"barge_in.false_count": 0, "output.stopped": True, "speech.ready_to_play_ms": 1200}


def results_for(metrics: dict) -> tuple[AssertionResult, ...]:
    return tuple(evaluate_assertion(assertion, SPEC.metric_index[assertion.metric], metrics.get(assertion.metric))
                 for assertion in SPEC.assertions)


def artifact(path: str = "events/trace.jsonl", kind: ArtifactKind = ArtifactKind.EVENT_LOG) -> ArtifactRef:
    return ArtifactRef(kind, path, "application/x-ndjson", "d" * 64, 2048)


def finished_run(metrics: dict = PASSING, score: float | None = 42.5) -> TestRun:
    running = transition_run(queued_run(), S.RUNNING, at=at(10))
    return complete_run(running, at=at(900), assertion_results=results_for(metrics), metrics=metrics, score=score,
                        artifacts=(artifact(), artifact("config.json", ArtifactKind.CONFIG_SNAPSHOT)))


def wire(run: TestRun) -> dict:
    return json.loads(json.dumps(run.to_dict()))


# ---------------------------------------------------------- state machine

EXPECTED = {
    (S.QUEUED, S.RUNNING), (S.QUEUED, S.CANCELLED), (S.QUEUED, S.ERRORED),
    (S.RUNNING, S.PASSED), (S.RUNNING, S.FAILED), (S.RUNNING, S.ERRORED), (S.RUNNING, S.CANCELLED),
    (S.RUNNING, S.TIMED_OUT),
}


@pytest.mark.parametrize("current, target", list(itertools.product(RunStatus, RunStatus)))
def test_transition_table(current, target):
    legal = (current, target) in EXPECTED
    assert can_transition(current, target) is legal
    if legal:
        check_transition(current, target)
    else:
        with pytest.raises(RunTransitionError) as caught:
            check_transition(current, target)
        assert caught.value.code == TRANSITION_ILLEGAL


def test_terminal_statuses_have_no_exit():
    assert TERMINAL_STATUSES == {S.PASSED, S.FAILED, S.ERRORED, S.CANCELLED, S.TIMED_OUT}
    assert all(not RUN_TRANSITIONS[status] for status in TERMINAL_STATUSES)
    with pytest.raises(TestLabError):
        can_transition("queued", S.RUNNING)


def test_transition_run_sets_supplied_times():
    run = queued_run()
    running = transition_run(run, S.RUNNING, at=at(10))
    assert running.status is S.RUNNING and running.started_at == at(10) and running.finished_at is None
    timed_out = transition_run(running, S.TIMED_OUT, at=at(5000), failure=RunFailure("worker_timeout", "no result in 5 s"))
    assert timed_out.finished_at == at(5000) and timed_out.failure.code == "worker_timeout"
    cancelled = transition_run(run, S.CANCELLED, at=at(3))
    assert cancelled.started_at is None and cancelled.failure is None
    errored = transition_run(run, S.ERRORED, at=at(3), failure=RunFailure("worker_spawn_failed"))
    assert errored.started_at is None


def test_transition_run_refuses_illegal_or_derived_targets():
    run = queued_run()
    with pytest.raises(TestLabError):  # QA F8: a failure is never silently dropped
        transition_run(run, S.RUNNING, at=at(1), failure=RunFailure("worker_spawn_failed"))
    for target in (S.PASSED, S.FAILED):
        with pytest.raises(RunTransitionError):
            transition_run(transition_run(run, S.RUNNING, at=at(1)), target, at=at(2))
    with pytest.raises(RunTransitionError):
        transition_run(run, S.TIMED_OUT, at=at(1), failure=RunFailure("x"))
    with pytest.raises(RunTransitionError):
        transition_run(transition_run(run, S.CANCELLED, at=at(1)), S.RUNNING, at=at(2))
    with pytest.raises(TestLabError):  # errored needs a failure
        transition_run(run, S.ERRORED, at=at(1))
    with pytest.raises(TestLabError):  # time travel
        transition_run(transition_run(run, S.RUNNING, at=at(10)), S.CANCELLED, at=at(5))


# ------------------------------------------------------ blocking semantics

def test_blocking_pass_passes_even_with_non_blocking_failure_and_low_score():
    run = finished_run(score=0.0)
    assert run.status is S.PASSED
    assert {result.assertion_id: result.outcome for result in run.assertion_results}["ready_fast"] is AssertionOutcome.FAILED
    check_run_against_spec(run, SPEC)


def test_blocking_failure_fails_whatever_the_score():
    run = finished_run({**PASSING, "barge_in.false_count": 2, "speech.ready_to_play_ms": 100}, score=100.0)
    assert run.status is S.FAILED and run.failure is None
    check_run_against_spec(run, SPEC)


def test_missing_blocking_measurement_is_errored_not_passed():
    metrics = {"barge_in.false_count": 0, "speech.ready_to_play_ms": 100}
    run = finished_run(metrics)
    assert run.status is S.ERRORED and run.failure.code == FAILURE_ASSERTIONS_INCONCLUSIVE
    # The detail names the blocking assertion that had no measurement: an empty one made
    # this shape indistinguishable from any other "could not measure" without re-deriving.
    assert run.failure.detail == "no measurement for blocking assertion(s): output_stops"


def test_a_run_with_no_blocking_assertion_evaluated_says_so():
    run = complete_run(transition_run(queued_run(), S.RUNNING, at=at(10)), at=at(900), assertion_results=(),
                       metrics={})
    assert run.failure.code == FAILURE_ASSERTIONS_INCONCLUSIVE
    assert run.failure.detail == "the diagnostic evaluated no blocking assertion, so nothing could conclude"


def test_the_inconclusive_detail_abbreviates_a_long_list():
    from jarvis.testlab.diagnostics import AssertionOutcome, AssertionResult
    from jarvis.testlab.runs import MAX_NAMED_MISSING_ASSERTIONS, inconclusive_detail

    results = tuple(AssertionResult(f"a_{index:02d}", AssertionOutcome.MISSING, True) for index in range(12))
    detail = inconclusive_detail(results)
    assert detail.endswith(f"and {12 - MAX_NAMED_MISSING_ASSERTIONS} more")
    assert "a_00" in detail and "a_11" not in detail
    assert len(detail) <= MAX_FAILURE_DETAIL_CHARS


def test_status_cannot_contradict_assertions():
    passed = finished_run()
    failing = results_for({**PASSING, "barge_in.false_count": 1})
    with pytest.raises(TestLabError) as caught:
        replace(passed, assertion_results=failing)
    assert caught.value.code == REFERENCE_INVALID
    with pytest.raises(TestLabError):
        replace(passed, status=S.FAILED)
    with pytest.raises(TestLabError):
        replace(passed, assertion_results=())
    with pytest.raises(TestLabError):
        replace(passed, failure=RunFailure("x"))
    with pytest.raises(TestLabError):
        replace(passed, score=100.5)
    with pytest.raises(TestLabError):
        replace(queued_run(), metrics={"barge_in.false_count": 0})
    with pytest.raises(TestLabError):
        replace(queued_run(), score=1.0)


# ------------------------------------------------------------------ codec

def test_round_trip_dict_json_dict_is_stable():
    run = replace(finished_run(), bundle_id=format_bundle_id(T0, NONCE), sweep_id=format_sweep_id(T0, NONCE),
                  parent_run_id=format_run_id(at(-1000), NONCE), scenario_id="echo.interrupt_basic",
                  scenario_fingerprint="e" * 64, overrides={"voice.vad.silence_ms": 400},
                  join_ids={"session_id": "sess-1", "conversation_id": "conv-1"})
    payload = wire(run)
    decoded = TestRun.from_dict(payload)
    assert decoded == run
    assert wire(decoded) == payload
    assert json.dumps(payload, sort_keys=True) == json.dumps(wire(TestRun.from_dict(payload)), sort_keys=True)
    assert payload["schema"] == "jarvis.testlab.run" and payload["schema_version"] == 1
    assert payload["created_at"] == "2026-09-17T10:58:00.123Z"
    assert list(payload["join_ids"]) == ["conversation_id", "session_id"]
    assert hash(decoded) == hash(run)
    for status in (queued_run(), transition_run(queued_run(), S.RUNNING, at=at(1))):
        assert TestRun.from_dict(wire(status)) == status


@pytest.mark.parametrize("path", [(), ("code",), ("failure",), ("assertion_results", 0), ("artifacts", 0)])
def test_unknown_fields_are_rejected(path):
    run = replace(transition_run(transition_run(queued_run(), S.RUNNING, at=at(1)), S.TIMED_OUT, at=at(2),
                                 failure=RunFailure("worker_timeout")),
                  artifacts=(artifact(),), assertion_results=results_for(PASSING))
    payload = wire(run)
    target = payload
    for step in path:
        target = target[step]
    target["extra"] = True
    with pytest.raises(TestLabError) as caught:
        TestRun.from_dict(payload)
    assert caught.value.code == FIELDS_MISMATCH


def test_decode_rejects_bad_header_private_data_and_code():
    payload = wire(finished_run())
    for key, value in (("schema_version", 2), ("schema", "jarvis.testlab.diagnostic")):
        with pytest.raises(TestLabError) as caught:
            TestRun.from_dict({**payload, key: value})
        assert caught.value.code == SCHEMA_UNSUPPORTED
    with pytest.raises(TestLabRedactionError) as caught:
        TestRun.from_dict({**payload, "metrics": {**payload["metrics"], "llm.thinking_text": 3}})
    assert caught.value.code == FORBIDDEN_PRIVATE_DATA
    with pytest.raises(TestLabRedactionError):
        TestRun.from_dict({**payload, "overrides": {"openai.api_key": "sk-x"}})
    with pytest.raises(ForbiddenCodeError):
        TestRun.from_dict({**payload, "overrides": {"voice.label": "__import__('os')"}})
    with pytest.raises(TestLabError):
        TestRun.from_dict({**payload, "created_at": None})
    with pytest.raises(TestLabError):
        TestRun.from_dict({**payload, "status": "done"})
    with pytest.raises(TestLabError):
        TestRun.from_dict({**payload, "artifacts": {}})


@pytest.mark.parametrize("changes", [
    dict(run_id="tlr-20260917T105800124Z-0123456789abcdef"),  # created_at mismatch
    dict(run_id=format_sweep_id(T0, NONCE)),
    dict(diagnostic_version=0),
    dict(profile="virtual"),
    dict(code=("a" * 40, False)),
    dict(config_fingerprint="sha256:" + "c" * 64),
    dict(parent_run_id=format_run_id(T0, NONCE)),
    dict(scenario_id="echo.basic"),
    dict(scenario_fingerprint="e" * 64),
    dict(join_ids={"trace_id": "x"}),
    dict(join_ids={"session_id": " padded"}),
    dict(bundle_id=format_run_id(T0, NONCE)),
    dict(parameters={"Turns": 3}),
    dict(parameters={"turns": [3]}),
    dict(started_at=at(1)),
    dict(finished_at=at(1)),
])
def test_record_invariants(changes):
    with pytest.raises(TestLabError):
        queued_run(**changes)


@pytest.mark.parametrize("kwargs", [
    dict(path="/abs/trace.jsonl"), dict(path="../escape.json"), dict(path="a/../b"), dict(path="C:/x.json"),
    dict(path=".hidden"), dict(path="a//b"), dict(path="a\\b"), dict(path="trailing."), dict(path="/".join("a" * 9)),
    dict(media_type="JSON"), dict(sha256="d" * 63), dict(size_bytes=-1), dict(size_bytes=1.5), dict(kind="blob"),
])
def test_artifact_refs_are_safe_references(kwargs):
    values = dict(kind=ArtifactKind.REPORT, path="report.json", media_type="application/json", sha256="d" * 64,
                  size_bytes=10)
    values.update(kwargs)
    with pytest.raises(TestLabError):
        ArtifactRef(**values)


def test_duplicate_artifact_paths_and_results_are_rejected():
    run = finished_run()
    with pytest.raises(TestLabError):
        replace(run, artifacts=(artifact(), artifact()))
    with pytest.raises(TestLabError):
        replace(run, assertion_results=run.assertion_results + run.assertion_results[:1])


def test_code_identity_and_failure_validation():
    CodeIdentity("f" * 64, True)
    for revision, dirty in (("abc123", False), ("f" * 40, "no"), (None, False)):
        with pytest.raises(TestLabError):
            CodeIdentity(revision, dirty)
    for code, detail in (("Worker Timeout", None), ("timeout", ""), ("timeout", "x" * 513)):
        with pytest.raises(TestLabError):
            RunFailure(code, detail)


# ---------------------------------------------------------- spec conformance

def test_check_run_against_spec_failures():
    run = finished_run()
    other = self_echo_spec(version=2)
    with pytest.raises(TestLabError) as caught:
        check_run_against_spec(run, other)
    assert caught.value.code == REFERENCE_INVALID
    no_live = self_echo_spec(profiles={ProfileName.VIRTUAL: SPEC.profiles[ProfileName.VIRTUAL]})
    with pytest.raises(TestLabError):
        check_run_against_spec(replace(run, profile=ProfileName.LIVE), no_live)
    with pytest.raises(TestLabError):
        check_run_against_spec(replace(run, parameters={"turns": 3}), SPEC)
    with pytest.raises(TestLabError):
        check_run_against_spec(replace(run, parameters={**run.parameters, "turns": 99}), SPEC)
    with pytest.raises(TestLabError):
        check_run_against_spec(replace(run, metrics={**run.metrics, "undeclared.metric": 1}), SPEC)
    with pytest.raises(TestLabError):
        check_run_against_spec(replace(run, metrics={**run.metrics, "barge_in.false_count": 0.5}), SPEC)
    flipped = tuple(replace(result, blocking=not result.blocking) if result.assertion_id == "ready_fast" else result
                    for result in run.assertion_results)
    with pytest.raises(TestLabError):
        check_run_against_spec(replace(run, assertion_results=flipped), SPEC)
    with pytest.raises(TestLabError):
        check_run_against_spec(replace(run, assertion_results=run.assertion_results[:2]), SPEC)
    renamed = (replace(run.assertion_results[0], assertion_id="other"),) + run.assertion_results[1:]
    with pytest.raises(TestLabError):
        check_run_against_spec(replace(run, assertion_results=renamed), SPEC)


def test_testrun_is_not_collected_as_a_pytest_class():
    assert TestRun.__test__ is False
    assert TestLabError.__test__ is False


# -------------------------------------------------- QA rework regressions

def _forged(no_false_barge_in_observed, metrics: dict, results: tuple | None = None) -> TestRun:
    running = transition_run(queued_run(), S.RUNNING, at=at(10))
    forged = results or (
        AssertionResult("no_false_barge_in", AssertionOutcome.PASSED, True, no_false_barge_in_observed),
        AssertionResult("output_stops", AssertionOutcome.PASSED, True, True),
        AssertionResult("ready_fast", AssertionOutcome.PASSED, False, 100),
    )
    return complete_run(running, at=at(20), assertion_results=forged, metrics=metrics)


@pytest.mark.parametrize("observed, metrics", [
    (3, {"barge_in.false_count": 3, "output.stopped": True, "speech.ready_to_play_ms": 100}),  # F1a: PASSED 3 vs eq 0
    (0, {"barge_in.false_count": 3, "output.stopped": True, "speech.ready_to_play_ms": 100}),  # F1b: observed != metric
    (0, {}),  # F1c: passed with every result but no metrics
])
def test_forged_passed_run_is_rejected_against_spec(observed, metrics):
    run = _forged(observed, metrics)
    assert run.status is S.PASSED  # the record alone cannot know the spec
    with pytest.raises(TestLabError) as caught:
        check_run_against_spec(run, SPEC)
    assert caught.value.code == REFERENCE_INVALID


def test_boolean_observed_never_stands_in_for_a_number():
    metrics = {"barge_in.false_count": 1, "output.stopped": True, "speech.ready_to_play_ms": 100}
    results = (AssertionResult("no_false_barge_in", AssertionOutcome.FAILED, True, True),
               AssertionResult("output_stops", AssertionOutcome.PASSED, True, True),
               AssertionResult("ready_fast", AssertionOutcome.PASSED, False, 100))
    with pytest.raises(TestLabError):
        check_run_against_spec(_forged(None, metrics, results), SPEC)


def test_partial_results_of_an_errored_run_are_rederived_too():
    running = transition_run(queued_run(), S.RUNNING, at=at(10))
    lying = (AssertionResult("no_false_barge_in", AssertionOutcome.PASSED, True, 0),)
    run = replace(transition_run(running, S.TIMED_OUT, at=at(50), failure=RunFailure("worker_timeout")),
                  assertion_results=lying, metrics={"barge_in.false_count": 2})
    with pytest.raises(TestLabError):
        check_run_against_spec(run, SPEC)
    honest = replace(run, assertion_results=results_for({"barge_in.false_count": 2})[:1])
    check_run_against_spec(honest, SPEC)


def test_diagnostic_fingerprint_must_match_the_spec():
    run = finished_run()
    assert run.diagnostic_fingerprint == SPEC.fingerprint()
    check_run_against_spec(run, self_echo_spec(title="Reworded under the same version"))  # wording only
    edited = self_echo_spec(parameters=SPEC.parameters[:-1] + (replace(SPEC.parameters[-1], max_length=64),))
    with pytest.raises(TestLabError) as caught:
        check_run_against_spec(run, edited)
    assert caught.value.code == REFERENCE_INVALID
    for bad in ("sha256:" + "a" * 64, "A" * 64, None):
        with pytest.raises(TestLabError):
            queued_run(diagnostic_fingerprint=bad)


def test_environment_is_bounded_guarded_and_round_trips():
    run = finished_run()
    assert dict(run.environment) == dict(sorted(ENVIRONMENT.items()))
    assert TestRun.from_dict(wire(run)).environment == run.environment
    with pytest.raises(TypeError):
        run.environment["os"] = "linux"
    too_many = {f"host.fact_{index}": index for index in range(33)}
    for bad, error in (({"openai.api_key": "sk"}, TestLabRedactionError), ({"shell_command": "x"}, ForbiddenCodeError),
                       ({"Host": "x"}, TestLabError), ({"os": None}, TestLabError), ({"os": ["windows"]}, TestLabError),
                       ({"os": "__import__('os')"}, ForbiddenCodeError), (too_many, TestLabError)):
        with pytest.raises(error):
            queued_run(environment=bad)
    payload = wire(run)
    del payload["environment"]
    with pytest.raises(TestLabError) as caught:
        TestRun.from_dict(payload)
    assert caught.value.code == FIELDS_MISMATCH
