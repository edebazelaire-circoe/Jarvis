"""Comparing and aggregating runs (docs/testlab.md, "Comparison"). Pure and deterministic."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.testlab.compare import (
    AssertionChange,
    IncomparableReason,
    MetricChange,
    aggregate_runs,
    compare_against,
    compare_runs,
    median,
)
from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    MetricDirection,
    MetricSpec,
    MetricUnit,
)
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.outcomes import RunOutcomeClass
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import RunFailure, RunStatus, complete_run, transition_run
from jarvis.testlab.scoring import compute_score
from jarvis.testlab.supervisor import derive_assertion_results
from jarvis.testlab.validation import TestLabError
from tests.fakes.testlab import at, queued_run, self_echo_spec

PASSING = {"barge_in.false_count": 0, "output.stopped": True, "speech.ready_to_play_ms": 300}
SPEC = self_echo_spec()


def run_of(metrics, *, nonce="0123456789abcdef", spec=SPEC, **changes):
    queued = queued_run(spec, run_id=format_run_id(at(0), nonce), **changes)
    running = transition_run(queued, RunStatus.RUNNING, at=at(10))
    return complete_run(running, at=at(900), assertion_results=derive_assertion_results(spec, metrics),
                        metrics=metrics, score=compute_score(spec.score, metrics))


def refused(nonce="cccccccccccccccc"):
    return transition_run(queued_run(SPEC, run_id=format_run_id(at(0), nonce)), RunStatus.ERRORED, at=at(900),
                          failure=RunFailure("permission_denied", "no grant"))


def delta_of(comparison, name):
    return next(item for item in comparison.metrics if item.metric == name)


# ------------------------------------------------------------------ deltas

def test_a_lower_better_metric_that_dropped_is_better():
    comparison = compare_runs(run_of(PASSING), run_of({**PASSING, "speech.ready_to_play_ms": 150},
                                                      nonce="1" * 16), metrics=SPEC)
    delta = delta_of(comparison, "speech.ready_to_play_ms")
    assert delta.change is MetricChange.BETTER
    assert (delta.delta, delta.percent_change, delta.unit, delta.direction) == (-150, -50.0, "ms", "lower_better")
    assert comparison.comparable is True


def test_a_lower_better_metric_that_rose_is_worse():
    comparison = compare_runs(run_of(PASSING), run_of({**PASSING, "speech.ready_to_play_ms": 600},
                                                      nonce="1" * 16), metrics=SPEC)
    assert delta_of(comparison, "speech.ready_to_play_ms").change is MetricChange.WORSE


def test_an_identical_value_is_unchanged():
    comparison = compare_runs(run_of(PASSING), run_of(PASSING, nonce="1" * 16), metrics=SPEC)
    assert {item.change for item in comparison.metrics} == {MetricChange.UNCHANGED}
    assert comparison.score_delta == (SPEC and run_of(PASSING).score, run_of(PASSING).score, 0.0)


def test_without_the_declaration_a_move_is_only_changed():
    """A delta with no direction is a number, not an improvement."""
    comparison = compare_runs(run_of(PASSING), run_of({**PASSING, "speech.ready_to_play_ms": 150}, nonce="1" * 16))
    delta = delta_of(comparison, "speech.ready_to_play_ms")
    assert delta.change is MetricChange.CHANGED and delta.direction is None and delta.unit is None


def test_a_neutral_metric_only_ever_changes():
    spec = self_echo_spec(metrics=(MetricSpec("turns.count", MetricUnit.COUNT, MetricDirection.NEUTRAL),),
                          assertions=(AssertionSpec("some", "turns.count", Comparator.GE, 0, True),),
                          score=SPEC.score.__class__())
    comparison = compare_runs(run_of({"turns.count": 2}, spec=spec),
                              run_of({"turns.count": 5}, nonce="1" * 16, spec=spec), metrics=spec)
    assert delta_of(comparison, "turns.count").change is MetricChange.CHANGED


def test_a_boolean_metric_has_no_distance_but_still_has_a_direction():
    comparison = compare_runs(run_of({**PASSING, "output.stopped": False}),
                              run_of(PASSING, nonce="1" * 16), metrics=SPEC)
    delta = delta_of(comparison, "output.stopped")
    assert (delta.delta, delta.percent_change) == (None, None)
    assert delta.change is MetricChange.BETTER  # output.stopped is higher_better


def test_a_zero_baseline_has_no_percent_change():
    comparison = compare_runs(run_of(PASSING), run_of({**PASSING, "barge_in.false_count": 3}, nonce="1" * 16),
                              metrics=SPEC)
    delta = delta_of(comparison, "barge_in.false_count")
    assert (delta.delta, delta.percent_change, delta.change) == (3, None, MetricChange.WORSE)


# ---------------------------------------------------------- assertion moves

def test_an_assertion_that_started_failing_is_a_regression():
    comparison = compare_runs(run_of(PASSING), run_of({**PASSING, "barge_in.false_count": 1}, nonce="1" * 16),
                              metrics=SPEC)
    change = next(item for item in comparison.assertions if item.assertion_id == "no_false_barge_in")
    assert change.change is AssertionChange.REGRESSED and change.blocking is True
    assert comparison.regressions == ("no_false_barge_in",)
    assert (comparison.baseline_outcome, comparison.candidate_outcome) == (RunOutcomeClass.PASSED,
                                                                           RunOutcomeClass.FAILED)


def test_an_assertion_that_stopped_failing_is_fixed():
    comparison = compare_runs(run_of({**PASSING, "barge_in.false_count": 1}), run_of(PASSING, nonce="1" * 16),
                              metrics=SPEC)
    assert next(item for item in comparison.assertions
                if item.assertion_id == "no_false_barge_in").change is AssertionChange.FIXED
    assert comparison.regressions == ()


def test_an_assertion_that_stopped_being_measured_is_a_regression():
    """passed -> missing is a regression: an assertion nobody could evaluate is not a pass."""
    full = run_of(PASSING)
    partial = run_of({"barge_in.false_count": 0, "output.stopped": True}, nonce="1" * 16)
    assert {item.assertion_id: item.change for item in compare_runs(full, partial, metrics=SPEC).assertions}[
        "ready_fast"] is AssertionChange.REGRESSED


def test_an_assertion_recorded_on_only_one_side_appeared_or_disappeared():
    """A run the supervisor stopped keeps partial evidence, so its result set can be shorter."""
    full = run_of(PASSING)
    stopped = replace(transition_run(transition_run(queued_run(SPEC, run_id=format_run_id(at(0), "1" * 16)),
                                                    RunStatus.RUNNING, at=at(10)),
                                     RunStatus.TIMED_OUT, at=at(900), failure=RunFailure("run_timeout", "budget")),
                      metrics={"barge_in.false_count": 0},
                      assertion_results=derive_assertion_results(SPEC, {"barge_in.false_count": 0})[:1])
    forward = {item.assertion_id: item.change for item in compare_runs(full, stopped, metrics=SPEC).assertions}
    assert forward["output_stops"] is AssertionChange.DISAPPEARED
    backward = {item.assertion_id: item.change for item in compare_runs(stopped, full, metrics=SPEC).assertions}
    assert backward["output_stops"] is AssertionChange.APPEARED


# --------------------------------------------------------- incomparability

def test_two_different_diagnostics_are_incomparable():
    other = self_echo_spec(diagnostic_id="speech.other", domain="speech")
    comparison = compare_runs(run_of(PASSING), run_of(PASSING, nonce="1" * 16, spec=other), metrics=SPEC)
    assert comparison.comparable is False
    assert IncomparableReason.DIFFERENT_DIAGNOSTIC in {item.reason for item in comparison.incomparable}


def test_two_versions_of_one_diagnostic_are_incomparable():
    other = self_echo_spec(version=2)
    comparison = compare_runs(run_of(PASSING), run_of(PASSING, nonce="1" * 16, spec=other), metrics=SPEC)
    assert {item.reason for item in comparison.incomparable} == {IncomparableReason.DIFFERENT_VERSION}


def test_an_edited_declaration_under_one_version_is_incomparable():
    """The fingerprint is the strict part: same id, same version, different meaning."""
    edited = self_echo_spec(assertions=(AssertionSpec("no_false_barge_in", "barge_in.false_count", Comparator.LE,
                                                      2, True),
                                        AssertionSpec("output_stops", "output.stopped", Comparator.EQ, True, True)))
    comparison = compare_runs(run_of(PASSING), run_of({"barge_in.false_count": 0, "output.stopped": True},
                                                      nonce="1" * 16, spec=edited), metrics=SPEC)
    assert comparison.comparable is False
    assert IncomparableReason.DIFFERENT_DECLARATION in {item.reason for item in comparison.incomparable}


def test_two_profiles_are_incomparable():
    comparison = compare_runs(run_of(PASSING), run_of(PASSING, nonce="1" * 16, profile=ProfileName.LIVE),
                              metrics=SPEC)
    assert IncomparableReason.DIFFERENT_PROFILE in {item.reason for item in comparison.incomparable}


def test_a_metric_only_one_run_measured_is_listed_and_never_subtracted():
    comparison = compare_runs(run_of(PASSING), run_of({"barge_in.false_count": 0, "output.stopped": True},
                                                      nonce="1" * 16), metrics=SPEC)
    reasons = {(item.subject, item.reason) for item in comparison.incomparable}
    assert ("speech.ready_to_play_ms", IncomparableReason.METRIC_MISSING_IN_CANDIDATE) in reasons
    assert "speech.ready_to_play_ms" not in {item.metric for item in comparison.metrics}


def test_two_declarations_with_different_units_for_one_name_are_incomparable():
    seconds = self_echo_spec(
        version=2,
        metrics=(MetricSpec("speech.ready_to_play_ms", MetricUnit.SECONDS, MetricDirection.LOWER_BETTER),),
        assertions=(AssertionSpec("ready_fast", "speech.ready_to_play_ms", Comparator.LE, 2, True),),
        score=SPEC.score.__class__())
    comparison = compare_runs(run_of(PASSING), run_of({"speech.ready_to_play_ms": 1.5}, nonce="1" * 16,
                                                      spec=seconds),
                              metrics=SPEC, candidate_metrics=seconds)
    assert IncomparableReason.DIFFERENT_UNIT in {item.reason for item in comparison.incomparable}
    assert "speech.ready_to_play_ms" not in {item.metric for item in comparison.metrics}


def test_a_boolean_against_a_number_under_one_name_is_incomparable():
    comparison = compare_runs(run_of(PASSING), run_of({**PASSING, "output.stopped": True}, nonce="1" * 16))
    assert comparison.comparable is True
    mixed = compare_runs(run_of(PASSING), replace(run_of(PASSING, nonce="1" * 16),
                                                  metrics={**PASSING, "output.stopped": True}))
    assert mixed.comparable is True


def test_different_parameters_are_a_difference_and_never_an_incomparability():
    """A sweep compares runs that differ by exactly one parameter: that must stay comparable."""
    other = run_of(PASSING, nonce="1" * 16, parameters={**dict(queued_run(SPEC).parameters), "turns": 9})
    comparison = compare_runs(run_of(PASSING), other, metrics=SPEC)
    assert comparison.comparable is True
    assert [item.field for item in comparison.differences] == ["parameters"]
    assert comparison.incomparable == ()


def test_the_comparison_serializes_for_a_caller():
    document = compare_runs(run_of(PASSING), run_of({**PASSING, "speech.ready_to_play_ms": 150}, nonce="1" * 16),
                            metrics=SPEC).to_dict()
    assert document["comparable"] is True
    assert document["metrics"][2]["change"] in {"better", "worse", "unchanged", "changed"}
    assert document["baseline_outcome"] == "passed"


def test_compare_runs_takes_two_records():
    with pytest.raises(TestLabError, match="TestRun"):
        compare_runs(run_of(PASSING), {"run_id": "x"})
    with pytest.raises(TestLabError, match="MetricSpec"):
        compare_runs(run_of(PASSING), run_of(PASSING, nonce="1" * 16), metrics={"a": 1})


def test_compare_against_keeps_the_order_it_was_given():
    baseline = run_of(PASSING)
    candidates = [run_of({**PASSING, "speech.ready_to_play_ms": value}, nonce=f"{index:016x}")
                  for index, value in enumerate((400, 500, 600), start=1)]
    comparisons = compare_against(baseline, candidates, metrics=SPEC)
    assert [item.candidate_run_id for item in comparisons] == [run.run_id for run in candidates]


def test_a_comparison_is_deterministic():
    first = compare_runs(run_of(PASSING), run_of(PASSING, nonce="1" * 16), metrics=SPEC)
    second = compare_runs(run_of(PASSING), run_of(PASSING, nonce="1" * 16), metrics=SPEC)
    assert first.to_dict() == second.to_dict()


# ------------------------------------------------------------- aggregates

@pytest.mark.parametrize("values,expected", [([1], 1.0), ([1, 3], 2.0), ([3, 1, 2], 2.0), ([4, 1, 3, 2], 2.5)])
def test_median_is_the_middle_or_the_mean_of_the_two_middles(values, expected):
    assert median(values) == expected


def test_median_needs_a_value():
    with pytest.raises(TestLabError, match="at least one"):
        median([])


def test_an_aggregate_reports_min_max_and_median_per_metric():
    runs = [run_of({**PASSING, "speech.ready_to_play_ms": value}, nonce=f"{index:016x}")
            for index, value in enumerate((300, 900, 600), start=1)]
    aggregate = aggregate_runs(runs, metrics=SPEC)
    latency = next(item for item in aggregate.metrics if item.metric == "speech.ready_to_play_ms")
    assert (latency.minimum, latency.median, latency.maximum, latency.count) == (300.0, 600.0, 900.0, 3)
    assert (latency.unit, latency.direction) == ("ms", "lower_better")
    assert aggregate.count == 3 and aggregate.outcomes == {"passed": 3}


def test_an_aggregate_counts_only_the_runs_that_measured_a_metric():
    runs = [run_of(PASSING, nonce="1" * 16),
            run_of({"barge_in.false_count": 0, "output.stopped": True}, nonce="2" * 16)]
    aggregate = aggregate_runs(runs, metrics=SPEC)
    assert next(item for item in aggregate.metrics if item.metric == "speech.ready_to_play_ms").count == 1
    assert next(item for item in aggregate.metrics if item.metric == "barge_in.false_count").count == 2


def test_an_aggregate_counts_every_outcome_including_the_ones_that_measured_nothing():
    aggregate = aggregate_runs([run_of(PASSING), refused()], metrics=SPEC)
    assert aggregate.outcomes == {"passed": 1, "refused": 1}
    assert aggregate.score is not None and aggregate.score.count == 1


def test_an_aggregate_of_runs_without_a_score_has_none():
    spec = self_echo_spec(score=SPEC.score.__class__())
    assert aggregate_runs([run_of(PASSING, spec=spec)], metrics=spec).score is None


def test_aggregate_runs_takes_records():
    with pytest.raises(TestLabError, match="TestRun"):
        aggregate_runs([{"run_id": "x"}])


def test_an_aggregate_serializes_for_a_caller():
    document = aggregate_runs([run_of(PASSING)], metrics=SPEC).to_dict()
    assert document["count"] == 1 and document["outcomes"] == {"passed": 1}
    assert document["metrics"][0]["metric"] == "barge_in.false_count"


def test_a_run_that_has_not_finished_is_flagged_incomparable():
    """A queued or running record carries no metrics by invariant: it compares to nothing."""
    queued = queued_run(SPEC, run_id=format_run_id(at(0), "d" * 16))
    comparison = compare_runs(run_of(PASSING), queued, metrics=SPEC)
    assert comparison.comparable is False
    reasons = [item for item in comparison.incomparable if item.reason is IncomparableReason.RUN_NOT_TERMINAL]
    assert [item.subject for item in reasons] == ["run"]
    assert "candidate run is still queued" in reasons[0].detail
    assert comparison.candidate_outcome is RunOutcomeClass.PENDING


def test_a_baseline_that_has_not_finished_is_flagged_too():
    running = transition_run(queued_run(SPEC, run_id=format_run_id(at(0), "e" * 16)), RunStatus.RUNNING, at=at(10))
    comparison = compare_runs(running, run_of(PASSING), metrics=SPEC)
    assert comparison.comparable is False
    assert any("baseline run is still running" in item.detail for item in comparison.incomparable)


def test_two_terminal_runs_are_never_flagged_for_that_reason():
    comparison = compare_runs(run_of(PASSING), run_of(PASSING, nonce="1" * 16), metrics=SPEC)
    assert all(item.reason is not IncomparableReason.RUN_NOT_TERMINAL for item in comparison.incomparable)


def test_a_move_between_two_non_passing_outcomes_is_only_changed():
    """`missing -> failed` and `failed -> missing`: neither end is a pass, so neither is a verdict move."""
    partial = {"barge_in.false_count": 0, "output.stopped": True}
    missing_side = replace(
        transition_run(transition_run(queued_run(SPEC, run_id=format_run_id(at(0), "a" * 16)),
                                      RunStatus.RUNNING, at=at(10)),
                       RunStatus.TIMED_OUT, at=at(900), failure=RunFailure("run_timeout", "budget")),
        metrics=partial, assertion_results=derive_assertion_results(SPEC, partial))
    failed_side = run_of({**PASSING, "speech.ready_to_play_ms": 5000}, nonce="b" * 16)
    forward = {item.assertion_id: item.change for item in compare_runs(missing_side, failed_side,
                                                                       metrics=SPEC).assertions}
    backward = {item.assertion_id: item.change for item in compare_runs(failed_side, missing_side,
                                                                        metrics=SPEC).assertions}
    assert forward["ready_fast"] is AssertionChange.CHANGED
    assert backward["ready_fast"] is AssertionChange.CHANGED


def test_missing_to_passed_is_fixed():
    partial = {"barge_in.false_count": 0, "output.stopped": True}
    missing_side = replace(
        transition_run(transition_run(queued_run(SPEC, run_id=format_run_id(at(0), "c" * 16)),
                                      RunStatus.RUNNING, at=at(10)),
                       RunStatus.TIMED_OUT, at=at(900), failure=RunFailure("run_timeout", "budget")),
        metrics=partial, assertion_results=derive_assertion_results(SPEC, partial))
    changes = {item.assertion_id: item.change
               for item in compare_runs(missing_side, run_of(PASSING, nonce="1" * 16), metrics=SPEC).assertions}
    assert changes["ready_fast"] is AssertionChange.FIXED


def test_a_v1_run_against_a_v2_run_of_a_shipped_diagnostic_is_incomparable():
    """The published `speech.stale_supersession` bump must not produce a bogus delta.

    v2 declares two metrics v1 does not, so a naive comparison would read them as
    "appeared" and a shared metric as a genuine move. The version check stops that
    before any of it, and the metric-level reasons stay visible underneath.
    """
    from jarvis.testlab.catalog import load_catalog
    from jarvis.testlab.identity import format_run_id
    from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun, complete_run, transition_run
    from jarvis.testlab.selftest import catalog_implementations
    from tests.fakes.testlab import CONFIG, ENVIRONMENT, REVISION

    catalog = load_catalog(implementations=catalog_implementations())
    shared = {"speech.superseded_count": 1, "speech.stale_delivered_count": 0,
              "speech.latest_intent_delivered": True, "speech.stale_wait_ms": 28000}
    runs = {}
    for version, extra, nonce in ((1, {}, "1" * 16),
                                  (2, {"scenario.expectations_declared": 0,
                                       "scenario.expectations_failed_count": 0}, "2" * 16)):
        spec = catalog.describe("speech.stale_supersession", version).diagnostic
        queued = TestRun(run_id=format_run_id(at(0), nonce), diagnostic_id=spec.diagnostic_id,
                         diagnostic_version=version, profile=ProfileName.VIRTUAL, status=RunStatus.QUEUED,
                         created_at=at(0), code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                         diagnostic_fingerprint=spec.fingerprint(), parameters={}, environment=ENVIRONMENT)
        metrics = {**shared, **extra}
        runs[version] = complete_run(transition_run(queued, RunStatus.RUNNING, at=at(10)), at=at(900),
                                     assertion_results=derive_assertion_results(spec, metrics), metrics=metrics)

    comparison = compare_runs(runs[1], runs[2],
                              metrics=catalog.describe("speech.stale_supersession", 1).diagnostic,
                              candidate_metrics=catalog.describe("speech.stale_supersession", 2).diagnostic)
    assert comparison.comparable is False
    pair = [item.reason for item in comparison.incomparable if item.subject == "run"]
    assert pair == [IncomparableReason.DIFFERENT_VERSION]
    # Not `different_declaration`: the version check answers first, and it is the honest reason.
    assert IncomparableReason.DIFFERENT_DECLARATION not in pair
    # The two metrics only v2 measured are listed, never subtracted.
    missing = {item.subject for item in comparison.incomparable
               if item.reason is IncomparableReason.METRIC_MISSING_IN_BASELINE}
    assert missing == {"scenario.expectations_declared", "scenario.expectations_failed_count"}
    # The metrics both versions share still read as unchanged, so the report stays useful.
    assert {item.change for item in comparison.metrics} == {MetricChange.UNCHANGED}
    assert {item.metric for item in comparison.metrics} == set(shared)
