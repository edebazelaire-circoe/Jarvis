"""The declared score is a synthesis of the metrics and never a verdict (docs/testlab.md, "Scoring")."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    MetricDirection,
    MetricSpec,
    MetricUnit,
    ScoreComponent,
    ScoreContract,
    ScoreMethod,
)
from jarvis.testlab.runs import RunStatus, complete_run, transition_run
from jarvis.testlab.scoring import SCORE_DECIMALS, component_score, compute_score, score_breakdown
from jarvis.testlab.supervisor import derive_assertion_results
from jarvis.testlab.validation import TestLabError
from tests.fakes.testlab import at, queued_run, self_echo_spec

#: `speech.ready_to_play_ms` is `lower_better` with best 200, worst 2000 in the shared spec.
LOWER = ScoreComponent("speech.ready_to_play_ms", 1, 200, 2000)
HIGHER = ScoreComponent("quality.ratio", 1, 1.0, 0.0)


def contract(*components: ScoreComponent) -> ScoreContract:
    return ScoreContract(ScoreMethod.WEIGHTED_MEAN, components)


# ------------------------------------------------------------ the mapping

@pytest.mark.parametrize("value,expected", [
    (200, 100.0),      # best
    (2000, 0.0),       # worst
    (1100, 50.0),      # midpoint
    (650, 75.0),
])
def test_a_lower_better_component_maps_worst_to_zero_and_best_to_a_hundred(value, expected):
    assert component_score(LOWER, value) == (expected, False)


@pytest.mark.parametrize("value,expected", [(0.0, 0.0), (1.0, 100.0), (0.25, 25.0)])
def test_a_higher_better_component_maps_the_other_way(value, expected):
    assert component_score(HIGHER, value) == (expected, False)


@pytest.mark.parametrize("value,expected", [(0, 100.0), (-5000, 100.0), (9000, 0.0)])
def test_a_value_outside_best_and_worst_is_clamped_and_says_so(value, expected):
    score, clamped = component_score(LOWER, value)
    assert (score, clamped) == (expected, True)


def test_a_boolean_measurement_is_never_scored():
    """`DiagnosticSpec` already refuses a boolean component; reaching one here is a contradiction."""
    with pytest.raises(TestLabError, match="numeric measurement"):
        component_score(LOWER, True)


def test_component_score_takes_a_score_component():
    with pytest.raises(TestLabError, match="ScoreComponent"):
        component_score("speech.ready_to_play_ms", 1)  # type: ignore[arg-type]


# ------------------------------------------------------------ the synthesis

def test_the_weighted_mean_weights_each_component():
    breakdown = score_breakdown(contract(replace(LOWER, weight=3), replace(HIGHER, weight=1)),
                                {"speech.ready_to_play_ms": 1100, "quality.ratio": 1.0})
    assert [item.score for item in breakdown.components] == [50.0, 100.0]
    assert breakdown.score == round((50.0 * 3 + 100.0 * 1) / 4, SCORE_DECIMALS) == 62.5
    assert breakdown.missing == ()


def test_one_component_is_just_its_own_score():
    assert compute_score(contract(LOWER), {"speech.ready_to_play_ms": 650}) == 75.0


def test_a_none_contract_scores_nothing():
    breakdown = score_breakdown(ScoreContract(), {"speech.ready_to_play_ms": 200})
    assert (breakdown.method, breakdown.score, breakdown.components) == (ScoreMethod.NONE, None, ())


def test_a_missing_component_metric_makes_the_whole_score_null():
    """A partial mean is not the declared synthesis; the missing names say why there is no score."""
    breakdown = score_breakdown(contract(LOWER, HIGHER), {"speech.ready_to_play_ms": 200})
    assert breakdown.score is None
    assert breakdown.missing == ("quality.ratio",)
    assert [item.metric for item in breakdown.components] == ["speech.ready_to_play_ms"]


def test_the_breakdown_serializes_for_a_caller():
    document = score_breakdown(contract(LOWER), {"speech.ready_to_play_ms": 1100}).to_dict()
    assert document["method"] == "weighted_mean" and document["score"] == 50.0
    assert document["components"][0] == {"metric": "speech.ready_to_play_ms", "weight": 1, "value": 1100.0,
                                         "score": 50.0, "clamped": False}


@pytest.mark.parametrize("bad", [("not a contract", {}), (contract(LOWER), "not a mapping")])
def test_score_breakdown_refuses_the_wrong_inputs(bad):
    with pytest.raises(TestLabError):
        score_breakdown(*bad)


# ------------------------------------- the score never changes the verdict

def metrics(**changes):
    values = {"barge_in.false_count": 0, "output.stopped": True, "speech.ready_to_play_ms": 300}
    values.update(changes)
    return values


def finished(values):
    spec = self_echo_spec()
    running = transition_run(queued_run(spec), RunStatus.RUNNING, at=at(10))
    return complete_run(running, at=at(900), assertion_results=derive_assertion_results(spec, values),
                        metrics=values, score=compute_score(spec.score, values)), spec


def test_a_perfect_score_cannot_rescue_a_failed_blocking_assertion():
    """`speech.ready_to_play_ms` is the ONLY scored metric, so a run can fail with score 100."""
    run, _spec = finished(metrics(**{"barge_in.false_count": 3, "speech.ready_to_play_ms": 200}))
    assert run.score == 100.0
    assert run.status is RunStatus.FAILED


def test_the_worst_possible_score_cannot_spoil_a_passing_run():
    run, _spec = finished(metrics(**{"speech.ready_to_play_ms": 9000}))
    assert run.score == 0.0
    assert run.status is RunStatus.PASSED


def test_forcing_a_score_onto_a_stored_run_changes_no_status():
    """The status is derived from the assertions alone; rewriting the score cannot move it."""
    run, _spec = finished(metrics())
    for forced in (0.0, 100.0, None):
        assert replace(run, score=forced).status is RunStatus.PASSED


def test_a_score_out_of_range_is_refused_by_the_record():
    run, _spec = finished(metrics())
    with pytest.raises(TestLabError, match="score"):
        replace(run, score=100.5)


def test_an_unmeasured_scored_metric_leaves_the_run_inconclusive_and_unscored():
    """The two "could not measure" signals agree: no score, and an errored run."""
    spec = self_echo_spec()
    values = {"barge_in.false_count": 0, "output.stopped": True}
    run, _spec = finished(values)
    assert run.score is None
    assert run.status is RunStatus.PASSED  # the scored metric carries a NON-blocking assertion
    blocking_missing = {"barge_in.false_count": 0}
    missing_run = complete_run(transition_run(queued_run(spec), RunStatus.RUNNING, at=at(10)), at=at(900),
                               assertion_results=derive_assertion_results(spec, blocking_missing),
                               metrics=blocking_missing, score=compute_score(spec.score, blocking_missing))
    assert missing_run.status is RunStatus.ERRORED and missing_run.score is None


def test_the_shipped_seed_contract_scores_a_real_measurement():
    """`voice.queue_latency` declares the only `weighted_mean` contract in the catalog."""
    from jarvis.testlab.catalog import load_catalog
    from jarvis.testlab.selftest import catalog_implementations

    spec = load_catalog(implementations=catalog_implementations()).describe("voice.queue_latency").diagnostic
    assert spec.score.method is ScoreMethod.WEIGHTED_MEAN
    # queue_free 100..3000 best..worst, first audio 200..4000; 1550 and 2100 are both midpoints.
    assert compute_score(spec.score, {"speech.queue_free_to_started_ms": 1550,
                                      "speech.started_to_first_audio_ms": 2100}) == 50.0
    assert compute_score(spec.score, {"speech.queue_free_to_started_ms": 0}) is None


def test_a_neutral_metric_is_never_a_component():
    """Guard on the declaration, not on the scorer: a component must be scorable."""
    with pytest.raises(TestLabError, match="numeric metric"):
        self_echo_spec(score=contract(ScoreComponent("output.stopped", 1, 1, 0)))
    with pytest.raises(TestLabError, match="contradict the metric direction"):
        self_echo_spec(score=contract(ScoreComponent("speech.ready_to_play_ms", 1, 2000, 200)))


def test_a_declared_contract_only_references_declared_metrics():
    spec = self_echo_spec(
        metrics=(MetricSpec("latency.ms", MetricUnit.MS, MetricDirection.LOWER_BETTER),),
        assertions=(AssertionSpec("fast", "latency.ms", Comparator.LE, 100, True),),
        score=contract(ScoreComponent("latency.ms", 2, 10, 500)))
    assert compute_score(spec.score, {"latency.ms": 255}) == pytest.approx(50.0, abs=0.2)
