"""Comparing Test Lab runs: per-metric deltas, assertion changes, and aggregates.

Binding contract: `docs/testlab.md` ("Comparison"). Pure and deterministic: no
clock, no randomness, no statistics dependency (the one aggregate that needs an
order statistic computes its own median, in five lines of stdlib). The same two
records always produce the same comparison, byte for byte.

**Comparability is a declaration property, not a wish.** Two runs are comparable
when they executed the SAME declaration on the SAME profile:

    diagnostic_id == diagnostic_id
    diagnostic_version == diagnostic_version
    diagnostic_fingerprint == diagnostic_fingerprint
    profile == profile

The fingerprint is the strict part and it is deliberate: it covers metrics,
units, directions, assertions, thresholds and the score contract (Slice 01), so
two runs that share it cannot disagree about what a metric means. Two runs of
"the same version" whose declaration was edited in place do not share it, and
their numbers are not the same numbers.

What is explicitly NOT an incomparability: different parameters, different
overrides, different code revision, different environment. Those are precisely
what an experiment varies — a sweep compares runs that differ by exactly one
parameter — so they are reported as `differences`, not as refusals.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from jarvis.testlab.diagnostics import (
    AssertionOutcome,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
)
from jarvis.testlab.outcomes import RunOutcomeClass, classify_run
from jarvis.testlab.runs import TERMINAL_STATUSES, TestRun
from jarvis.testlab.validation import fail

#: Percent change is rounded here; a delta keeps the raw arithmetic.
PERCENT_DECIMALS = 2


class MetricChange(StrEnum):
    #: Moved in the metric's declared good direction.
    BETTER = "better"
    #: Moved against it.
    WORSE = "worse"
    #: Identical value.
    UNCHANGED = "unchanged"
    #: Moved, with no direction to judge it by (`neutral`, or no declaration supplied).
    CHANGED = "changed"


class AssertionChange(StrEnum):
    UNCHANGED = "unchanged"
    #: Failed (or was missing) in the baseline and passes now.
    FIXED = "fixed"
    #: Passed in the baseline and fails (or is missing) now: an assertion nobody could
    #: evaluate is not a pass, so `passed -> missing` is a regression like `passed -> failed`.
    REGRESSED = "regressed"
    #: Recorded only in the candidate.
    APPEARED = "appeared"
    #: Recorded only in the baseline.
    DISAPPEARED = "disappeared"
    #: Both recorded, neither end a pass, and the outcome differs: `failed <-> missing`.
    #: Neither direction is an improvement or a regression — it is a move between two
    #: kinds of "not passing", and calling it either would be a judgement we cannot make.
    CHANGED = "changed"


class IncomparableReason(StrEnum):
    DIFFERENT_DIAGNOSTIC = "different_diagnostic"
    DIFFERENT_VERSION = "different_version"
    #: Same id and version, different `diagnostic_fingerprint`: the declaration was edited.
    DIFFERENT_DECLARATION = "different_declaration"
    DIFFERENT_PROFILE = "different_profile"
    METRIC_MISSING_IN_BASELINE = "metric_missing_in_baseline"
    METRIC_MISSING_IN_CANDIDATE = "metric_missing_in_candidate"
    #: One side measured a boolean and the other a number under the same name.
    DIFFERENT_VALUE_TYPE = "different_value_type"
    #: The two runs were judged by declarations that give this metric different units.
    DIFFERENT_UNIT = "different_unit"
    #: A run that is still `queued` or `running` has no evidence yet, so it compares to nothing.
    RUN_NOT_TERMINAL = "run_not_terminal"


@dataclass(frozen=True, slots=True)
class Incomparability:
    """One reason a pair, or one metric of a pair, cannot be read as a difference."""

    #: What it is about: a metric name, or `run` for the whole pair.
    subject: str
    reason: IncomparableReason
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "reason": self.reason.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class FieldDifference:
    """An input that differed between the two runs. Informational: this is what an experiment varies."""

    field: str
    baseline: Any
    candidate: Any

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "baseline": self.baseline, "candidate": self.candidate}


@dataclass(frozen=True, slots=True)
class MetricDelta:
    metric: str
    unit: str | None
    direction: str | None
    baseline: bool | int | float
    candidate: bool | int | float
    #: `candidate - baseline` for numbers; None for booleans.
    delta: float | None
    #: Relative change in percent; None for booleans and for a zero baseline.
    percent_change: float | None
    change: MetricChange

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "unit": self.unit, "direction": self.direction,
                "baseline": self.baseline, "candidate": self.candidate, "delta": self.delta,
                "percent_change": self.percent_change, "change": self.change.value}


@dataclass(frozen=True, slots=True)
class AssertionDelta:
    assertion_id: str
    blocking: bool
    baseline: str | None
    candidate: str | None
    change: AssertionChange

    def to_dict(self) -> dict[str, Any]:
        return {"assertion_id": self.assertion_id, "blocking": self.blocking, "baseline": self.baseline,
                "candidate": self.candidate, "change": self.change.value}


@dataclass(frozen=True, slots=True)
class RunComparison:
    """Baseline vs candidate: what moved, what changed verdict, and what cannot be read at all."""

    baseline_run_id: str
    candidate_run_id: str
    #: True when the two runs share diagnostic, version, declaration fingerprint and profile.
    comparable: bool
    baseline_outcome: RunOutcomeClass
    candidate_outcome: RunOutcomeClass
    metrics: tuple[MetricDelta, ...] = ()
    assertions: tuple[AssertionDelta, ...] = ()
    #: `(baseline, candidate, delta)` when both runs scored; None otherwise.
    score_delta: tuple[float, float, float] | None = None
    #: Inputs that differed (parameters, overrides, code, ...). Never an incomparability.
    differences: tuple[FieldDifference, ...] = ()
    incomparable: tuple[Incomparability, ...] = ()

    @property
    def regressions(self) -> tuple[str, ...]:
        """Blocking assertions that passed in the baseline and no longer do."""
        return tuple(item.assertion_id for item in self.assertions
                     if item.blocking and item.change is AssertionChange.REGRESSED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_run_id": self.baseline_run_id, "candidate_run_id": self.candidate_run_id,
            "comparable": self.comparable, "baseline_outcome": self.baseline_outcome.value,
            "candidate_outcome": self.candidate_outcome.value,
            "metrics": [item.to_dict() for item in self.metrics],
            "assertions": [item.to_dict() for item in self.assertions],
            "score_delta": None if self.score_delta is None else list(self.score_delta),
            "differences": [item.to_dict() for item in self.differences],
            "incomparable": [item.to_dict() for item in self.incomparable],
        }


# ------------------------------------------------------------- comparison

def _metric_index(spec: DiagnosticSpec | Mapping[str, MetricSpec] | None) -> Mapping[str, MetricSpec]:
    if spec is None:
        return {}
    if isinstance(spec, DiagnosticSpec):
        return spec.metric_index
    if isinstance(spec, Mapping) and all(isinstance(item, MetricSpec) for item in spec.values()):
        return spec
    raise fail("metrics must be a DiagnosticSpec, a name -> MetricSpec mapping, or None")


def _pair_incomparabilities(baseline: TestRun, candidate: TestRun) -> tuple[Incomparability, ...]:
    checks = (
        (baseline.diagnostic_id != candidate.diagnostic_id, IncomparableReason.DIFFERENT_DIAGNOSTIC,
         "the two runs executed different diagnostics"),
        (baseline.diagnostic_id == candidate.diagnostic_id
         and baseline.diagnostic_version != candidate.diagnostic_version, IncomparableReason.DIFFERENT_VERSION,
         "the two runs executed different versions of the diagnostic"),
        (baseline.diagnostic_id == candidate.diagnostic_id
         and baseline.diagnostic_version == candidate.diagnostic_version
         and baseline.diagnostic_fingerprint != candidate.diagnostic_fingerprint,
         IncomparableReason.DIFFERENT_DECLARATION,
         "the declaration changed between the two runs, so their metrics may not mean the same thing"),
        (baseline.profile is not candidate.profile, IncomparableReason.DIFFERENT_PROFILE,
         "the two runs used different execution profiles"),
        # A record the run has not finished writing carries no metrics and no verdict by
        # invariant, so it compares as "everything disappeared" unless it is flagged here.
        (baseline.status not in TERMINAL_STATUSES, IncomparableReason.RUN_NOT_TERMINAL,
         f"the baseline run is still {baseline.status.value} and has produced no evidence yet"),
        (candidate.status not in TERMINAL_STATUSES, IncomparableReason.RUN_NOT_TERMINAL,
         f"the candidate run is still {candidate.status.value} and has produced no evidence yet"),
    )
    return tuple(Incomparability("run", reason, detail) for failed, reason, detail in checks if failed)


def _change(direction: MetricDirection | None, baseline: float, candidate: float) -> MetricChange:
    if baseline == candidate:
        return MetricChange.UNCHANGED
    if direction is None or direction is MetricDirection.NEUTRAL:
        return MetricChange.CHANGED
    improved = candidate > baseline if direction is MetricDirection.HIGHER_BETTER else candidate < baseline
    return MetricChange.BETTER if improved else MetricChange.WORSE


def _metric_delta(name: str, spec: MetricSpec | None, baseline: Any, candidate: Any) -> MetricDelta:
    direction = spec.direction if spec is not None else None
    unit = spec.unit.value if spec is not None else None
    if type(baseline) is bool:
        # A boolean has no distance: only the direction can say whether it improved.
        change = _change(direction, float(baseline), float(candidate))
        return MetricDelta(name, unit, None if direction is None else direction.value, baseline, candidate,
                           None, None, change)
    delta = candidate - baseline
    percent = None if baseline == 0 else round(delta / abs(baseline) * 100, PERCENT_DECIMALS)
    return MetricDelta(name, unit, None if direction is None else direction.value, baseline, candidate,
                       delta, percent, _change(direction, baseline, candidate))


_ASSERTION_CHANGES: Mapping[tuple[bool, bool], AssertionChange] = MappingProxyType({
    (True, True): AssertionChange.UNCHANGED,
    (False, True): AssertionChange.FIXED,
    (True, False): AssertionChange.REGRESSED,
})


def _assertion_delta(assertion_id: str, blocking: bool, baseline: AssertionOutcome | None,
                     candidate: AssertionOutcome | None) -> AssertionDelta:
    values = (None if baseline is None else baseline.value, None if candidate is None else candidate.value)
    if baseline is None:
        change = AssertionChange.APPEARED
    elif candidate is None:
        change = AssertionChange.DISAPPEARED
    elif baseline is candidate:
        change = AssertionChange.UNCHANGED
    else:
        change = _ASSERTION_CHANGES.get(
            (baseline is AssertionOutcome.PASSED, candidate is AssertionOutcome.PASSED), AssertionChange.CHANGED)
    return AssertionDelta(assertion_id, blocking, values[0], values[1], change)


#: Run inputs whose difference is reported, in this order. Comparing runs that differ
#: in these is the point of an experiment, so none of them makes a pair incomparable.
_DIFFERENCE_FIELDS = ("parameters", "overrides", "code", "environment", "scenario_fingerprint", "sweep_id")


def _differences(baseline: TestRun, candidate: TestRun) -> tuple[FieldDifference, ...]:
    before, after = baseline.to_dict(), candidate.to_dict()
    return tuple(FieldDifference(name, before[name], after[name])
                 for name in _DIFFERENCE_FIELDS if before[name] != after[name])


def compare_runs(baseline: TestRun, candidate: TestRun, *,
                 metrics: DiagnosticSpec | Mapping[str, MetricSpec] | None = None,
                 candidate_metrics: DiagnosticSpec | Mapping[str, MetricSpec] | None = None) -> RunComparison:
    """Compare two runs of the same diagnostic. Direction awareness needs the declaration.

    `metrics` supplies the `MetricSpec`s (a `DiagnosticSpec` or a name -> spec map).
    Without them every move reads `changed` instead of `better` / `worse`: a delta with
    no direction is a number, not an improvement, and guessing one would be a lie.

    `candidate_metrics` gives the candidate's own declaration when it differs (comparing
    across versions). A metric the two declarations give different UNITS to is listed as
    incomparable instead of subtracted: 1500 ms and 1.5 s are not a 1498.5 regression.
    """
    if not isinstance(baseline, TestRun) or not isinstance(candidate, TestRun):
        raise fail("compare_runs takes two TestRun records")
    index = _metric_index(metrics)
    other = index if candidate_metrics is None else _metric_index(candidate_metrics)
    incomparable = list(_pair_incomparabilities(baseline, candidate))
    deltas: list[MetricDelta] = []
    for name in sorted(set(baseline.metrics) | set(candidate.metrics)):
        before, after = baseline.metrics.get(name), candidate.metrics.get(name)
        if before is None or after is None:
            reason = (IncomparableReason.METRIC_MISSING_IN_BASELINE if before is None
                      else IncomparableReason.METRIC_MISSING_IN_CANDIDATE)
            incomparable.append(Incomparability(name, reason, f"{name} was measured by only one of the two runs"))
            continue
        if (type(before) is bool) != (type(after) is bool):
            incomparable.append(Incomparability(name, IncomparableReason.DIFFERENT_VALUE_TYPE,
                                                f"{name} is a boolean in one run and a number in the other"))
            continue
        declared, declared_other = index.get(name), other.get(name)
        if declared is not None and declared_other is not None and declared.unit is not declared_other.unit:
            incomparable.append(Incomparability(name, IncomparableReason.DIFFERENT_UNIT,
                                                f"{name} is declared in different units by the two declarations"))
            continue
        deltas.append(_metric_delta(name, declared, before, after))
    before_results = {result.assertion_id: result for result in baseline.assertion_results}
    after_results = {result.assertion_id: result for result in candidate.assertion_results}
    assertions = tuple(
        _assertion_delta(
            assertion_id,
            (before_results.get(assertion_id) or after_results[assertion_id]).blocking,
            None if assertion_id not in before_results else before_results[assertion_id].outcome,
            None if assertion_id not in after_results else after_results[assertion_id].outcome)
        for assertion_id in sorted(set(before_results) | set(after_results)))
    score_delta = (None if baseline.score is None or candidate.score is None
                   else (baseline.score, candidate.score, candidate.score - baseline.score))
    return RunComparison(
        baseline_run_id=baseline.run_id, candidate_run_id=candidate.run_id,
        comparable=not any(item.subject == "run" for item in incomparable),
        baseline_outcome=classify_run(baseline).outcome, candidate_outcome=classify_run(candidate).outcome,
        metrics=tuple(deltas), assertions=assertions, score_delta=score_delta,
        differences=_differences(baseline, candidate), incomparable=tuple(incomparable))


def compare_against(baseline: TestRun, candidates: Iterable[TestRun], *,
                    metrics: DiagnosticSpec | Mapping[str, MetricSpec] | None = None) -> tuple[RunComparison, ...]:
    """One baseline against N candidates, in the order given (a sweep read against its first point)."""
    return tuple(compare_runs(baseline, candidate, metrics=metrics) for candidate in candidates)


# ------------------------------------------------------------- aggregates

def median(values: Sequence[float]) -> float:
    """Median of a non-empty sequence. Even count: the mean of the two middle values.

    Five lines instead of a dependency, and deterministic: the sort is total on
    finite numbers, which `check_metric_value` already guarantees.
    """
    if not values:
        raise fail("median needs at least one value")
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass(frozen=True, slots=True)
class MetricAggregate:
    """One metric over N runs. Booleans aggregate as 0/1, which makes `median` a majority."""

    metric: str
    unit: str | None
    direction: str | None
    count: int
    minimum: float
    maximum: float
    median: float

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "unit": self.unit, "direction": self.direction, "count": self.count,
                "minimum": self.minimum, "maximum": self.maximum, "median": self.median}


@dataclass(frozen=True, slots=True)
class RunAggregate:
    """N runs read at a glance: how they ended, and the spread of every metric."""

    run_ids: tuple[str, ...]
    outcomes: Mapping[str, int]
    metrics: tuple[MetricAggregate, ...] = ()
    score: MetricAggregate | None = None

    @property
    def count(self) -> int:
        return len(self.run_ids)

    def to_dict(self) -> dict[str, Any]:
        return {"run_ids": list(self.run_ids), "count": self.count, "outcomes": dict(self.outcomes),
                "metrics": [item.to_dict() for item in self.metrics],
                "score": None if self.score is None else self.score.to_dict()}


def _aggregate(name: str, spec: MetricSpec | None, values: list[float]) -> MetricAggregate:
    return MetricAggregate(name, None if spec is None else spec.unit.value,
                           None if spec is None else spec.direction.value, len(values),
                           min(values), max(values), median(values))


def aggregate_runs(runs: Iterable[TestRun], *,
                   metrics: DiagnosticSpec | Mapping[str, MetricSpec] | None = None) -> RunAggregate:
    """Median, min and max per metric over N runs, plus the outcome counts.

    A metric only some runs measured is aggregated over the runs that DID measure
    it, and `MetricAggregate.count` says how many those were: a spread computed
    over three of five runs must never look like a spread over five.
    """
    index = _metric_index(metrics)
    records = list(runs)
    if any(not isinstance(run, TestRun) for run in records):
        raise fail("aggregate_runs takes TestRun records")
    outcomes: dict[str, int] = {}
    values: dict[str, list[float]] = {}
    scores: list[float] = []
    for run in records:
        outcome = classify_run(run).outcome.value
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if run.score is not None:
            scores.append(run.score)
        for name, value in run.metrics.items():
            values.setdefault(name, []).append(float(value))
    return RunAggregate(
        run_ids=tuple(run.run_id for run in records),
        outcomes=MappingProxyType(dict(sorted(outcomes.items()))),
        metrics=tuple(_aggregate(name, index.get(name), values[name]) for name in sorted(values)),
        score=None if not scores else MetricAggregate(
            "score", MetricUnit.PERCENT.value, MetricDirection.HIGHER_BETTER.value, len(scores),
            min(scores), max(scores), median(scores)))
