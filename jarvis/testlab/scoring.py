"""Computing the declared score of a run: a synthesis of the metrics, never a verdict.

Binding contract: `docs/testlab.md` ("Scoring"). Pure: the score is a function
of the diagnostic's `ScoreContract` and the run's measured metrics, nothing else.

Two rules make the score safe to show next to a verdict:

- **The score never decides the status.** `complete_run` derives `passed` /
  `failed` / `errored` from the blocking assertions alone; the score is written
  beside that decision. A run with score 100 whose blocking assertion failed is
  `failed`, and a run with score 0 whose blocking assertions all passed is
  `passed`. Both are proven by test.
- **A score is all-or-nothing.** If any metric a component names was not
  measured, the score is `None`. A weighted mean over the components that
  happened to be measured is not the declared synthesis, and it would let a
  diagnostic that measured half of what it promised look comparable to one that
  measured everything. The missing metrics are reported in the breakdown, and
  the run itself already reads `inconclusive` through its assertions.

Where it runs: the SUPERVISOR, from the worker's metrics and the declaration the
run was queued against. Slice 05 made the worker measurement-only, so a worker
that could send a score would be sending a judgement it has no declaration to
justify; `WorkerResult` therefore carries no score at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jarvis.testlab.diagnostics import (
    SCORE_MAX,
    SCORE_MIN,
    MetricValue,
    ScoreComponent,
    ScoreContract,
    ScoreMethod,
)
from jarvis.testlab.validation import fail

#: Decimals kept in a component score and in the run score. Enough to separate
#: two runs that differ by a millisecond on a multi-second scale, short enough
#: that the stored number is stable and readable in canonical JSON.
SCORE_DECIMALS = 4


@dataclass(frozen=True, slots=True)
class ComponentScore:
    """One component of a weighted mean: what was measured and what it scored."""

    metric: str
    weight: float
    value: float
    #: 0..100 after the linear worst -> best mapping and the clamp.
    score: float
    #: True when the measured value was outside `[worst, best]` and the mapping clamped it.
    clamped: bool

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "weight": self.weight, "value": self.value, "score": self.score,
                "clamped": self.clamped}


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Why a run scored what it scored, component by component.

    `score` is None exactly when the contract declares no score (`method` is
    `none`) or when `missing` is not empty.
    """

    method: ScoreMethod
    score: float | None
    components: tuple[ComponentScore, ...] = ()
    #: Declared component metrics the run did not measure, sorted.
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method.value, "score": self.score,
                "components": [item.to_dict() for item in self.components], "missing": list(self.missing)}


def component_score(component: ScoreComponent, value: MetricValue) -> tuple[float, bool]:
    """Linear `worst` (0) -> `best` (100) mapping of one measured value, clamped to 0..100.

    Returns `(score, clamped)`. The direction is carried by which side `best` is
    on, which `DiagnosticSpec` already checked against the metric's
    `MetricDirection`, so a `lower_better` metric has `best < worst` and the
    mapping is decreasing without any special case here.
    """
    if not isinstance(component, ScoreComponent):
        raise fail("component_score takes a ScoreComponent")
    if type(value) is bool or not isinstance(value, (int, float)):
        # A boolean metric is refused as a component by `DiagnosticSpec`; reaching this
        # means the metrics and the declaration disagree, which is never scored silently.
        raise fail(f"score component {component.metric} needs a numeric measurement")
    ratio = (float(value) - component.worst) / (component.best - component.worst)
    raw = ratio * SCORE_MAX
    clamped = min(max(raw, SCORE_MIN), SCORE_MAX)
    return round(clamped, SCORE_DECIMALS), clamped != raw


def score_breakdown(contract: ScoreContract, metrics: Mapping[str, Any]) -> ScoreBreakdown:
    """The declared synthesis of one run's metrics, with the reason when there is none."""
    if not isinstance(contract, ScoreContract):
        raise fail("score_breakdown takes a ScoreContract")
    if not isinstance(metrics, Mapping):
        raise fail("score_breakdown takes a metrics mapping")
    if contract.method is ScoreMethod.NONE:
        return ScoreBreakdown(contract.method, None)
    if contract.method is not ScoreMethod.WEIGHTED_MEAN:  # pragma: no cover - the enum has two members
        raise fail(f"score method {contract.method.value} has no implementation")
    scored: list[ComponentScore] = []
    missing: list[str] = []
    for component in contract.components:
        value = metrics.get(component.metric)
        if value is None:
            missing.append(component.metric)
            continue
        score, clamped = component_score(component, value)
        scored.append(ComponentScore(component.metric, component.weight, float(value), score, clamped))
    if missing:
        # Deliberate: a partial mean is not the declared synthesis (see the module docstring).
        return ScoreBreakdown(contract.method, None, tuple(scored), tuple(sorted(missing)))
    total = sum(item.weight for item in scored)
    weighted = sum(item.score * item.weight for item in scored)
    return ScoreBreakdown(contract.method, round(weighted / total, SCORE_DECIMALS), tuple(scored), ())


def compute_score(contract: ScoreContract, metrics: Mapping[str, Any]) -> float | None:
    """The run score, or None when the contract declares none or a component was not measured."""
    return score_breakdown(contract, metrics).score
