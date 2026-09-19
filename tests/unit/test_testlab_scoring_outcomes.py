""""Could not measure" has its own shape: the outcome classification (docs/testlab.md, "Outcomes").

Every terminal shape a Slice 05/06/07 run can reach is classified here, so a caller
(Slice 10/11) answers "passed / failed / could not measure / refused" from the record,
never from prose.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.testlab.jobs import (
    FAILURE_CANCELLED,
    FAILURE_CODES,
    FAILURE_MEASUREMENT_UNAVAILABLE,
    FAILURE_PERMISSION_DENIED,
    FAILURE_RUNNER_FAILED,
    FAILURE_RUN_TIMEOUT,
    FAILURE_SCENARIO_EXPECTATION_UNMET,
    FAILURE_WORKER_CRASHED,
)
from jarvis.testlab.outcomes import (
    FAILURE_OUTCOMES,
    NO_VERDICT_OUTCOMES,
    RunOutcomeClass,
    classify_run,
    outcome_of,
)
from jarvis.testlab.runs import (
    FAILURE_ASSERTIONS_INCONCLUSIVE,
    TERMINAL_STATUSES,
    RunFailure,
    RunStatus,
    complete_run,
    transition_run,
)
from jarvis.testlab.scoring import compute_score
from jarvis.testlab.supervisor import derive_assertion_results
from jarvis.testlab.validation import TestLabError
from tests.fakes.testlab import at, queued_run, self_echo_spec

PASSING = {"barge_in.false_count": 0, "output.stopped": True, "speech.ready_to_play_ms": 300}


def running():
    return transition_run(queued_run(), RunStatus.RUNNING, at=at(10))


def concluded(metrics):
    spec = self_echo_spec()
    return complete_run(running(), at=at(900), assertion_results=derive_assertion_results(spec, metrics),
                        metrics=metrics, score=compute_score(spec.score, metrics))


def stopped(status, code, detail="because"):
    return transition_run(running(), status, at=at(900), failure=RunFailure(code, detail))


# ------------------------------------------------- the five terminal shapes

def test_a_run_whose_blocking_assertions_passed_reads_passed():
    summary = classify_run(concluded(PASSING))
    assert (summary.outcome, summary.conclusive) == (RunOutcomeClass.PASSED, True)
    assert summary.failed_assertions == () and summary.measured is True


def test_a_run_with_a_failed_blocking_assertion_reads_failed_and_names_it():
    summary = classify_run(concluded({**PASSING, "barge_in.false_count": 2}))
    assert summary.outcome is RunOutcomeClass.FAILED
    assert summary.failed_assertions == ("no_false_barge_in",)
    assert summary.conclusive is True


def test_a_run_that_could_not_measure_a_blocking_metric_reads_inconclusive():
    """Slice 06's missing join: `errored` / `assertions_inconclusive`."""
    run = concluded({"barge_in.false_count": 0})
    summary = classify_run(run)
    assert run.status is RunStatus.ERRORED and run.failure.code == FAILURE_ASSERTIONS_INCONCLUSIVE
    assert summary.outcome is RunOutcomeClass.INCONCLUSIVE
    assert summary.missing_assertions == ("output_stops",)
    assert summary.conclusive is False


def test_a_stimulus_the_stack_never_answered_also_reads_inconclusive_but_keeps_its_own_code():
    """Slice 06's unanswered onset, now `measurement_unavailable`: same outcome, different cause."""
    summary = classify_run(stopped(RunStatus.ERRORED, FAILURE_MEASUREMENT_UNAVAILABLE))
    assert summary.outcome is RunOutcomeClass.INCONCLUSIVE
    assert summary.failure_code == FAILURE_MEASUREMENT_UNAVAILABLE
    other = classify_run(concluded({"barge_in.false_count": 0}))
    assert other.outcome is summary.outcome and other.failure_code != summary.failure_code


def test_a_run_the_lab_declined_reads_refused():
    summary = classify_run(transition_run(queued_run(), RunStatus.ERRORED, at=at(900),
                                          failure=RunFailure(FAILURE_PERMISSION_DENIED, "no grant")))
    assert summary.outcome is RunOutcomeClass.REFUSED
    assert summary.measured is False


def test_a_worker_that_died_reads_crashed():
    assert classify_run(stopped(RunStatus.ERRORED, FAILURE_WORKER_CRASHED)).outcome is RunOutcomeClass.CRASHED


def test_an_unforeseen_runner_exception_reads_crashed_not_inconclusive():
    """A defect of ours must never be shown as a diagnostic that honestly could not measure."""
    assert classify_run(stopped(RunStatus.ERRORED, FAILURE_RUNNER_FAILED)).outcome is RunOutcomeClass.CRASHED


def test_a_cancelled_run_reads_cancelled():
    assert classify_run(stopped(RunStatus.CANCELLED, FAILURE_CANCELLED)).outcome is RunOutcomeClass.CANCELLED


def test_a_timed_out_run_reads_inconclusive():
    run = stopped(RunStatus.TIMED_OUT, FAILURE_RUN_TIMEOUT)
    assert classify_run(run).outcome is RunOutcomeClass.INCONCLUSIVE


def test_an_unmet_scenario_expectation_reads_inconclusive():
    summary = classify_run(stopped(RunStatus.ERRORED, FAILURE_SCENARIO_EXPECTATION_UNMET))
    assert summary.outcome is RunOutcomeClass.INCONCLUSIVE


@pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.RUNNING])
def test_a_run_still_going_reads_pending(status):
    run = queued_run() if status is RunStatus.QUEUED else running()
    assert classify_run(run).outcome is RunOutcomeClass.PENDING


# --------------------------------------------------------------- the table

def test_every_failure_code_the_lab_can_produce_is_classified():
    """A code nobody mapped would read `crashed`; the table must never rely on that fallback."""
    assert (FAILURE_CODES | {FAILURE_ASSERTIONS_INCONCLUSIVE}) <= set(FAILURE_OUTCOMES)


def test_an_unknown_failure_code_reads_crashed_rather_than_a_measurement():
    assert outcome_of(RunStatus.ERRORED, "a_code_from_the_future") is RunOutcomeClass.CRASHED
    assert outcome_of(RunStatus.ERRORED, None) is RunOutcomeClass.CRASHED


def test_no_verdict_outcomes_are_exactly_the_non_conclusive_ones():
    assert NO_VERDICT_OUTCOMES == set(RunOutcomeClass) - {RunOutcomeClass.PASSED, RunOutcomeClass.FAILED}


def test_every_terminal_status_classifies_without_needing_prose():
    for status in TERMINAL_STATUSES:
        assert isinstance(outcome_of(status, FAILURE_CANCELLED), RunOutcomeClass)


def test_the_classification_never_invents_a_status():
    """Slice 01 forbids a new `RunStatus`; the outcome is derived, and the status is unchanged."""
    run = concluded(PASSING)
    summary = classify_run(run)
    assert summary.status is run.status
    assert summary.to_dict()["status"] == "passed" and summary.to_dict()["outcome"] == "passed"


def test_the_summary_is_json_ready_for_a_caller():
    document = classify_run(concluded({**PASSING, "barge_in.false_count": 2})).to_dict()
    assert document["outcome"] == "failed" and document["verdict"] == "failed"
    assert document["failed_assertions"] == ["no_false_barge_in"] and document["measured"] is True


@pytest.mark.parametrize("bad", ["passed", None, 3])
def test_outcome_of_takes_a_run_status(bad):
    with pytest.raises(TestLabError, match="RunStatus"):
        outcome_of(bad, None)


def test_classify_run_takes_a_test_run():
    with pytest.raises(TestLabError, match="TestRun"):
        classify_run({"status": "passed"})


def test_a_score_is_reported_beside_the_outcome_and_never_as_one():
    run = concluded(PASSING)
    assert classify_run(run).score == run.score
    assert classify_run(replace(run, score=0.0)).outcome is RunOutcomeClass.PASSED
