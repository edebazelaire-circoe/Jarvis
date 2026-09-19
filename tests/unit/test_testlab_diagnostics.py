"""Conformance tests for Test Lab diagnostic declarations (docs/testlab.md, Diagnostics)."""

from __future__ import annotations

import copy
from dataclasses import replace
import json

import pytest

from jarvis.testlab.diagnostics import (
    AssertionOutcome,
    AssertionResult,
    AssertionSpec,
    AssertionVerdict,
    Comparator,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
    ParameterSpec,
    ParameterType,
    ScoreComponent,
    ScoreContract,
    ScoreMethod,
    assertions_verdict,
    check_metric_value,
    evaluate_assertion,
    resolve_parameters,
)
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.validation import (
    FIELDS_MISMATCH,
    FORBIDDEN_CODE,
    FORBIDDEN_PRIVATE_DATA,
    PARAMETER_INVALID,
    REFERENCE_INVALID,
    SCHEMA_UNSUPPORTED,
    ForbiddenCodeError,
    TestLabError,
    TestLabRedactionError,
)
from tests.fakes.testlab import live_profile, self_echo_spec, virtual_profile


def wire(spec: DiagnosticSpec) -> dict:
    return json.loads(json.dumps(spec.to_dict()))


# ------------------------------------------------------------------ spec

def test_spec_round_trip_is_stable():
    spec = self_echo_spec()
    payload = wire(spec)
    decoded = DiagnosticSpec.from_dict(payload)
    assert decoded == spec
    assert wire(decoded) == payload
    assert decoded.fingerprint() == spec.fingerprint()
    assert payload["schema"] == "jarvis.testlab.diagnostic" and payload["schema_version"] == 1
    assert [profile["name"] for profile in payload["profiles"]] == ["virtual", "live", "hardware:guided"]
    assert hash(decoded) == hash(spec)


def test_fingerprint_changes_with_the_semantics():
    spec = self_echo_spec()
    changed = (
        self_echo_spec(assertions=(AssertionSpec("no_false_barge_in", "barge_in.false_count", Comparator.LE, 1, True),)),
        self_echo_spec(version=2),
        self_echo_spec(profiles={ProfileName.VIRTUAL: virtual_profile()}),
        self_echo_spec(score=ScoreContract()),
        self_echo_spec(parameters=spec.parameters[:1]),
    )
    assert len({spec.fingerprint(), *(other.fingerprint() for other in changed)}) == 1 + len(changed)


def test_fingerprint_ignores_cosmetic_wording():
    spec = self_echo_spec()
    reworded = self_echo_spec(
        title="Reworded title", description="Reworded description.",
        metrics=tuple(replace(metric, description="Explained.") for metric in spec.metrics),
        assertions=tuple(replace(assertion, description="Explained.") for assertion in spec.assertions),
        parameters=tuple(replace(parameter, description="Explained.") for parameter in spec.parameters),
    )
    assert reworded != spec
    assert reworded.fingerprint() == spec.fingerprint()


def test_profiles_are_read_only_and_keyed_by_name():
    spec = self_echo_spec()
    assert spec.profiles[ProfileName.LIVE] == live_profile()
    with pytest.raises(TypeError):
        spec.profiles[ProfileName.AUDIO] = virtual_profile()
    with pytest.raises(TestLabError) as caught:
        self_echo_spec(profiles={ProfileName.LIVE: virtual_profile()})
    assert caught.value.code == REFERENCE_INVALID
    with pytest.raises(TestLabError):
        self_echo_spec(profiles={})


@pytest.mark.parametrize("path", [(), ("profiles", 0), ("profiles", 0, "cost"), ("parameters", 0), ("metrics", 0),
                                  ("assertions", 0), ("score",), ("score", "components", 0)])
def test_unknown_fields_are_rejected_at_every_level(path):
    payload = wire(self_echo_spec())
    target = payload
    for step in path:
        target = target[step]
    target["surprise"] = 1
    with pytest.raises(TestLabError) as caught:
        DiagnosticSpec.from_dict(payload)
    assert caught.value.code == FIELDS_MISMATCH


def test_missing_field_and_schema_header_are_rejected():
    payload = wire(self_echo_spec())
    del payload["description"]
    with pytest.raises(TestLabError) as caught:
        DiagnosticSpec.from_dict(payload)
    assert caught.value.code == FIELDS_MISMATCH
    for key, value in (("schema_version", 2), ("schema_version", "1"), ("schema", "jarvis.testlab.run")):
        payload = wire(self_echo_spec())
        payload[key] = value
        with pytest.raises(TestLabError) as caught:
            DiagnosticSpec.from_dict(payload)
        assert caught.value.code == SCHEMA_UNSUPPORTED
    with pytest.raises(TestLabError):
        DiagnosticSpec.from_dict([payload])


def test_private_data_is_rejected_before_shape():
    payload = wire(self_echo_spec())
    payload["metrics"][0]["reasoning"] = "hidden"
    with pytest.raises(TestLabRedactionError) as caught:
        DiagnosticSpec.from_dict(payload)
    assert caught.value.code == FORBIDDEN_PRIVATE_DATA
    assert "hidden" not in str(caught.value)


@pytest.mark.parametrize("changes", [
    dict(domain="speech"),
    dict(domain="Voice"),
    dict(diagnostic_id="voice"),
    dict(version=0),
    dict(title=" padded "),
    dict(title="x" * 121),
    dict(description=""),
    dict(metrics=()),
    dict(metrics=[MetricSpec("a.b", MetricUnit.MS, MetricDirection.NEUTRAL)]),
    dict(assertions=()),
    dict(assertions=(AssertionSpec("ready_fast", "speech.ready_to_play_ms", Comparator.LE, 800, False),)),
    dict(assertions=(AssertionSpec("unknown", "not.declared", Comparator.EQ, 0, True),)),
    dict(assertions=(AssertionSpec("bool_numeric", "output.stopped", Comparator.EQ, 1, True),)),
    dict(assertions=(AssertionSpec("bool_ordering", "output.stopped", Comparator.GE, True, True),)),
    dict(assertions=(AssertionSpec("numeric_bool", "barge_in.false_count", Comparator.EQ, False, True),)),
    dict(assertions=(AssertionSpec("dup", "barge_in.false_count", Comparator.EQ, 0, True),
                     AssertionSpec("dup", "barge_in.false_count", Comparator.EQ, 1, True))),
    dict(score=ScoreContract(ScoreMethod.WEIGHTED_MEAN, (ScoreComponent("output.stopped", 1, 1, 0),))),
    dict(score=ScoreContract(ScoreMethod.WEIGHTED_MEAN, (ScoreComponent("not.declared", 1, 1, 0),))),
    dict(score=ScoreContract(ScoreMethod.WEIGHTED_MEAN, (ScoreComponent("speech.ready_to_play_ms", 1, 2000, 200),))),
    dict(parameters=(ParameterSpec("turns", ParameterType.INT, 1), ParameterSpec("turns", ParameterType.INT, 2))),
    dict(schema_version=2),
])
def test_cross_references_and_fields_are_validated(changes):
    with pytest.raises(TestLabError):
        self_echo_spec(**changes)


def _one_metric_spec(unit: MetricUnit, comparator: Comparator, threshold) -> DiagnosticSpec:
    metric = MetricSpec("x.value_measure", unit, MetricDirection.LOWER_BETTER)
    return self_echo_spec(metrics=(metric,), score=ScoreContract(),
                          assertions=(AssertionSpec("a", metric.name, comparator, threshold, True),))


@pytest.mark.parametrize("unit, comparator, threshold", [
    (MetricUnit.COUNT, Comparator.EQ, 0.5),  # integral unit, fractional threshold
    (MetricUnit.COUNT, Comparator.LE, -1),
    (MetricUnit.CHARS, Comparator.GE, 2.5),
    (MetricUnit.RATIO, Comparator.LE, 5),  # ratio is 0..1
    (MetricUnit.RATIO, Comparator.GE, -0.1),
    (MetricUnit.PERCENT, Comparator.LT, 101),
    (MetricUnit.MS, Comparator.EQ, 800),  # eq/ne only on exact units
    (MetricUnit.RATIO, Comparator.EQ, 0.3),
    (MetricUnit.PERCENT, Comparator.NE, 100),
])
def test_thresholds_must_fit_the_unit(unit, comparator, threshold):
    with pytest.raises(TestLabError) as caught:
        _one_metric_spec(unit, comparator, threshold)
    assert caught.value.code == REFERENCE_INVALID


@pytest.mark.parametrize("unit, comparator, threshold", [
    (MetricUnit.COUNT, Comparator.EQ, 0), (MetricUnit.CHARS, Comparator.NE, 3), (MetricUnit.RATIO, Comparator.LE, 1),
    (MetricUnit.PERCENT, Comparator.GE, 99.5), (MetricUnit.MS, Comparator.LT, 12.5), (MetricUnit.DB, Comparator.GT, -60),
])
def test_thresholds_that_fit_the_unit(unit, comparator, threshold):
    assert _one_metric_spec(unit, comparator, threshold).assertions[0].threshold == threshold


@pytest.mark.parametrize("choices", [("ok", "__import__('os')"), ("ok", "eval(x)")])
def test_enum_choices_pass_the_value_code_heuristic(choices):
    with pytest.raises(ForbiddenCodeError):
        ParameterSpec("mode", ParameterType.ENUM, "ok", choices=choices)


@pytest.mark.parametrize("choices", [("text", "audio"), ("idle", "thinking", "speaking"), ("virtual", "audio", "live"),
                                     ("prompt", "silent")])
def test_enum_choices_are_values_not_names(choices):
    assert ParameterSpec("mode", ParameterType.ENUM, choices[0], choices=choices).choices == choices


def test_metric_names_must_be_unique_and_not_private():
    metric = MetricSpec("barge_in.false_count", MetricUnit.COUNT, MetricDirection.LOWER_BETTER)
    with pytest.raises(TestLabError):
        self_echo_spec(metrics=(*self_echo_spec().metrics, metric))
    with pytest.raises(TestLabRedactionError):
        MetricSpec("llm.reasoning", MetricUnit.CHARS, MetricDirection.NEUTRAL)
    with pytest.raises(TestLabError):
        MetricSpec("latency", "ms", MetricDirection.LOWER_BETTER)


def test_score_contract_shape():
    with pytest.raises(TestLabError):
        ScoreContract(ScoreMethod.NONE, (ScoreComponent("a.b", 1, 1, 0),))
    with pytest.raises(TestLabError):
        ScoreContract(ScoreMethod.WEIGHTED_MEAN, ())
    for weight, best, worst in ((0, 1, 0), (-1, 1, 0), (1, 1, 1), (1001, 1, 0), (1, float("nan"), 0)):
        with pytest.raises(TestLabError):
            ScoreComponent("a.b", weight, best, worst)
    assert self_echo_spec(score=ScoreContract()).to_dict()["score"] == {"method": "none", "components": []}


# ------------------------------------------------------------ parameters

def test_resolve_parameters_merges_defaults_and_normalizes():
    spec = self_echo_spec()
    resolved = resolve_parameters(spec.parameters, {"echo.level_db": -12, "mode": "half"})
    assert dict(resolved) == {"aec": True, "echo.level_db": -12.0, "label": "baseline", "mode": "half", "turns": 3}
    assert type(resolved["echo.level_db"]) is float
    assert list(resolved) == sorted(resolved)
    with pytest.raises(TypeError):
        resolved["turns"] = 4  # read-only


@pytest.mark.parametrize("supplied", [
    {"unknown": 1},
    {"turns": 0}, {"turns": 21}, {"turns": 2.0}, {"turns": True}, {"turns": "3"},
    {"echo.level_db": 1}, {"echo.level_db": float("nan")}, {"echo.level_db": None},
    {"aec": 1}, {"aec": "true"},
    {"mode": "simplex"}, {"mode": 1},
    {"label": "x" * 33}, {"label": 5},
])
def test_parameter_violations_share_a_stable_code(supplied):
    with pytest.raises(TestLabError) as caught:
        resolve_parameters(self_echo_spec().parameters, supplied)
    assert caught.value.code == PARAMETER_INVALID


def test_parameter_values_and_keys_cannot_carry_code_or_private_data():
    params = self_echo_spec().parameters
    with pytest.raises(ForbiddenCodeError) as caught:
        resolve_parameters(params, {"label": "__import__('os')"})
    assert caught.value.code == FORBIDDEN_CODE
    with pytest.raises(ForbiddenCodeError):
        resolve_parameters(params, {"shell_command": "dir"})
    with pytest.raises(TestLabRedactionError):
        resolve_parameters(params, {"api_key": "sk-1"})
    with pytest.raises(TestLabError):
        resolve_parameters(params, {"label": {"nested": 1}})
    with pytest.raises(TestLabError):
        resolve_parameters(params, [("turns", 3)])


@pytest.mark.parametrize("kwargs", [
    dict(name="Turns", type=ParameterType.INT, default=1),
    dict(name="script", type=ParameterType.STR, default="x"),
    dict(name="n", type="int", default=1),
    dict(name="n", type=ParameterType.INT, default=1, minimum=5, maximum=1),
    dict(name="n", type=ParameterType.INT, default=1, minimum=0.5),
    dict(name="n", type=ParameterType.INT, default=0, minimum=1),
    dict(name="n", type=ParameterType.BOOL, default=True, minimum=0),
    dict(name="n", type=ParameterType.ENUM, default="a"),
    dict(name="n", type=ParameterType.ENUM, default="a", choices=("a", "a")),
    dict(name="n", type=ParameterType.ENUM, default="c", choices=("a", "b")),
    dict(name="n", type=ParameterType.ENUM, default="a", choices=["a"]),
    dict(name="n", type=ParameterType.STR, default="a", choices=("a",)),
    dict(name="n", type=ParameterType.STR, default="a", max_length=0),
    dict(name="n", type=ParameterType.INT, default=1, max_length=4),
])
def test_parameter_spec_validation(kwargs):
    with pytest.raises(TestLabError):
        ParameterSpec(**kwargs)


def test_parameter_spec_round_trip():
    for parameter in self_echo_spec().parameters:
        assert ParameterSpec.from_dict(json.loads(json.dumps(parameter.to_dict()))) == parameter


# ------------------------------------------------------ metrics/assertions

@pytest.mark.parametrize("unit, good, bad", [
    (MetricUnit.COUNT, 3, [-1, 1.5, True]),
    (MetricUnit.CHARS, 0, [-2, "3"]),
    (MetricUnit.RATIO, 0.5, [1.01, -0.1]),
    (MetricUnit.PERCENT, 100, [100.5]),
    (MetricUnit.BOOLEAN, False, [0, "false"]),
    (MetricUnit.MS, -3.5, [float("inf"), None]),
])
def test_metric_values_fit_their_unit(unit, good, bad):
    metric = MetricSpec("m.x", unit, MetricDirection.NEUTRAL)
    check_metric_value(metric, good, "metrics.m.x")
    for value in bad:
        with pytest.raises(TestLabError):
            check_metric_value(metric, value, "metrics.m.x")


@pytest.mark.parametrize("unit, comparator, threshold, value, outcome", [
    (MetricUnit.MS, Comparator.LT, 800, 799, AssertionOutcome.PASSED),
    (MetricUnit.MS, Comparator.LT, 800, 800, AssertionOutcome.FAILED),
    (MetricUnit.MS, Comparator.LE, 800, 800.0, AssertionOutcome.PASSED),
    (MetricUnit.MS, Comparator.GT, 1, 1, AssertionOutcome.FAILED),
    (MetricUnit.MS, Comparator.GE, 1, 1, AssertionOutcome.PASSED),
    (MetricUnit.MS, Comparator.LE, 800, None, AssertionOutcome.MISSING),
    (MetricUnit.COUNT, Comparator.EQ, 0, 0, AssertionOutcome.PASSED),
    (MetricUnit.COUNT, Comparator.NE, 0, 0, AssertionOutcome.FAILED),
    (MetricUnit.CHARS, Comparator.EQ, 12, 13, AssertionOutcome.FAILED),
])
def test_evaluate_assertion(unit, comparator, threshold, value, outcome):
    metric = MetricSpec("speech.ready_to_play_ms", unit, MetricDirection.LOWER_BETTER)
    assertion = AssertionSpec("ready", metric.name, comparator, threshold, True)
    result = evaluate_assertion(assertion, metric, value)
    assert result.outcome is outcome and result.blocking and result.observed == value


def test_evaluate_assertion_checks_its_inputs():
    spec = self_echo_spec()
    assertion = spec.assertion_index["output_stops"]
    assert evaluate_assertion(assertion, spec.metric_index["output.stopped"], True).outcome is AssertionOutcome.PASSED
    with pytest.raises(TestLabError):
        evaluate_assertion(assertion, spec.metric_index["output.stopped"], 1)
    with pytest.raises(TestLabError) as caught:
        evaluate_assertion(assertion, spec.metric_index["barge_in.false_count"], 0)
    assert caught.value.code == REFERENCE_INVALID


def _result(outcome: AssertionOutcome, blocking: bool) -> AssertionResult:
    return AssertionResult(f"a_{outcome.value}_{blocking}".lower(), outcome, blocking,
                           None if outcome is AssertionOutcome.MISSING else 1)


@pytest.mark.parametrize("results, verdict", [
    ([(AssertionOutcome.PASSED, True)], AssertionVerdict.PASSED),
    ([(AssertionOutcome.PASSED, True), (AssertionOutcome.FAILED, False)], AssertionVerdict.PASSED),
    ([(AssertionOutcome.PASSED, True), (AssertionOutcome.MISSING, False)], AssertionVerdict.PASSED),
    ([(AssertionOutcome.FAILED, True), (AssertionOutcome.MISSING, True)], AssertionVerdict.FAILED),
    ([(AssertionOutcome.PASSED, True), (AssertionOutcome.MISSING, True)], AssertionVerdict.INCONCLUSIVE),
    ([(AssertionOutcome.PASSED, False)], AssertionVerdict.INCONCLUSIVE),
    ([], AssertionVerdict.INCONCLUSIVE),
])
def test_blocking_assertions_decide_the_verdict(results, verdict):
    assert assertions_verdict([_result(*item) for item in results]) is verdict


def test_assertion_result_shape():
    with pytest.raises(TestLabError):
        AssertionResult("a", AssertionOutcome.MISSING, True, 3)
    with pytest.raises(TestLabError):
        AssertionResult("a", AssertionOutcome.PASSED, True)
    with pytest.raises(TestLabError):
        AssertionResult("a", AssertionOutcome.PASSED, "yes", 1)
    result = AssertionResult("a", AssertionOutcome.FAILED, False, 2.5)
    assert AssertionResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result
    with pytest.raises(TestLabError):
        AssertionResult.from_dict({**result.to_dict(), "score": 1})


def test_spec_decode_does_not_mutate_payload():
    payload = wire(self_echo_spec())
    before = copy.deepcopy(payload)
    DiagnosticSpec.from_dict(payload)
    assert payload == before


def test_replace_revalidates():
    spec = self_echo_spec()
    with pytest.raises(TestLabError):
        replace(spec, domain="speech")
