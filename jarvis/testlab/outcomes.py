"""What a terminal run means, in one word a caller can branch on.

Binding contract: `docs/testlab.md` ("Outcomes"). Pure: the outcome is derived
from `TestRun.status` and `RunFailure.code` alone, with a closed table. Nothing
here parses prose, and no new `RunStatus` is invented — Slice 01 forbids that,
and a status is what the state machine and the store enforce, while an outcome
is how a human or a caller reads the result.

The question this answers is the one Slices 10 to 12 need and the status alone
cannot: **passed, failed, could not measure, or refused?**

| Outcome | Means | Typical cause |
|---|---|---|
| `passed` | the product did what the diagnostic declared | every blocking assertion passed |
| `failed` | the product did NOT do what it declared | a blocking assertion failed |
| `inconclusive` | **could not measure**: no verdict was available | a metric was never measured, a stimulus was never answered, the run outlived its budget |
| `refused` | the Test Lab declined to run it; nothing was learned about the product | permission, a resource that never freed, an unavailable runner or catalog |
| `crashed` | the Test Lab itself broke around the run | the worker died, its result was unusable, the declaration refused it |
| `cancelled` | a caller (or the supervisor stopping) ended it | `cancel()`, shutdown |
| `pending` | not terminal yet | queued, running |

`inconclusive` and `crashed` are both "no verdict", and they are deliberately
separate: the first is a diagnostic that honestly says it could not measure (a
finding about the situation), the second is a defect of the lab (a finding about
us). The Slice 06 carry-over is exactly this distinction — a missing join ends
`errored`/`assertions_inconclusive` and an unanswered onset ends
`errored`/`measurement_unavailable`; both read `inconclusive`, and the failure
code, which is a stable identifier and not prose, still tells them apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from jarvis.testlab.diagnostics import AssertionOutcome, AssertionVerdict
from jarvis.testlab.jobs import (
    FAILURE_CANCELLED,
    FAILURE_CATALOG_UNAVAILABLE,
    FAILURE_COST_BUDGET_EXCEEDED,
    FAILURE_DEVICE_CONTENTION,
    FAILURE_DEVICE_CONTENTION_DURING_RUN,
    FAILURE_ISOLATION_VIOLATION,
    FAILURE_JOB_INVALID,
    FAILURE_LIVE_OPT_IN_MISSING,
    FAILURE_MEASUREMENT_UNAVAILABLE,
    FAILURE_PERMISSION_DENIED,
    FAILURE_RESOURCE_WAIT_TIMEOUT,
    FAILURE_RESULT_CONTRADICTS_SPEC,
    FAILURE_RESULT_INVALID,
    FAILURE_RUNNER_FAILED,
    FAILURE_RUNNER_UNAVAILABLE,
    FAILURE_RUN_ABANDONED,
    FAILURE_RUN_CONCLUDED_OUT_OF_BAND,
    FAILURE_RUN_TIMEOUT,
    FAILURE_SCENARIO_EXPECTATION_UNMET,
    FAILURE_SUPERVISOR_FAULT,
    FAILURE_SUPERVISOR_STOPPED,
    FAILURE_WORKER_ACTIVE_ELSEWHERE,
    FAILURE_WORKER_CRASHED,
    FAILURE_WORKER_LOST,
    FAILURE_WORKER_SPAWN_FAILED,
    FAILURE_WORKER_STARTUP_TIMEOUT,
    FAILURE_WORKER_UNRESPONSIVE,
)
from jarvis.testlab.runs import FAILURE_ASSERTIONS_INCONCLUSIVE, RunStatus, TestRun
from jarvis.testlab.validation import fail


class RunOutcomeClass(StrEnum):
    """How a caller reads a run. Derived, never stored as a status."""

    PASSED = "passed"
    FAILED = "failed"
    #: Could not measure: the run produced no usable verdict, and that is a finding.
    INCONCLUSIVE = "inconclusive"
    #: The Test Lab declined to execute it; nothing was learned about the product.
    REFUSED = "refused"
    #: The Test Lab itself broke around the run.
    CRASHED = "crashed"
    CANCELLED = "cancelled"
    #: Not terminal yet.
    PENDING = "pending"


#: Outcomes that carry no judgement of the product. A caller comparing runs must
#: exclude them rather than count them as failures.
NO_VERDICT_OUTCOMES = frozenset({RunOutcomeClass.INCONCLUSIVE, RunOutcomeClass.REFUSED, RunOutcomeClass.CRASHED,
                                 RunOutcomeClass.CANCELLED, RunOutcomeClass.PENDING})

#: `RunFailure.code` -> outcome, for the `errored` status. Closed: a code that is not
#: here reads `crashed`, because an unmapped failure is by definition one we did not
#: foresee, and a run we cannot explain must never read as a measurement.
FAILURE_OUTCOMES: Mapping[str, RunOutcomeClass] = MappingProxyType({
    # could not measure
    FAILURE_ASSERTIONS_INCONCLUSIVE: RunOutcomeClass.INCONCLUSIVE,
    FAILURE_MEASUREMENT_UNAVAILABLE: RunOutcomeClass.INCONCLUSIVE,
    FAILURE_SCENARIO_EXPECTATION_UNMET: RunOutcomeClass.INCONCLUSIVE,
    FAILURE_RUN_TIMEOUT: RunOutcomeClass.INCONCLUSIVE,
    #: Slice 08: the live Jarvis took the device back, or the money ran out, while the
    #: run was executing. Partial evidence, no verdict.
    FAILURE_DEVICE_CONTENTION_DURING_RUN: RunOutcomeClass.INCONCLUSIVE,
    FAILURE_COST_BUDGET_EXCEEDED: RunOutcomeClass.INCONCLUSIVE,
    # structural refusal: the lab declined before it could measure anything
    FAILURE_PERMISSION_DENIED: RunOutcomeClass.REFUSED,
    FAILURE_RESOURCE_WAIT_TIMEOUT: RunOutcomeClass.REFUSED,
    FAILURE_RUNNER_UNAVAILABLE: RunOutcomeClass.REFUSED,
    FAILURE_CATALOG_UNAVAILABLE: RunOutcomeClass.REFUSED,
    FAILURE_JOB_INVALID: RunOutcomeClass.REFUSED,
    FAILURE_ISOLATION_VIOLATION: RunOutcomeClass.REFUSED,
    FAILURE_WORKER_ACTIVE_ELSEWHERE: RunOutcomeClass.REFUSED,
    #: Slice 08 (READINESS B9): nothing was started, so nothing was learned — and
    #: refusing is the point: the laptop microphone belongs to the live conversation.
    FAILURE_DEVICE_CONTENTION: RunOutcomeClass.REFUSED,
    FAILURE_LIVE_OPT_IN_MISSING: RunOutcomeClass.REFUSED,
    # the lab broke
    FAILURE_WORKER_SPAWN_FAILED: RunOutcomeClass.CRASHED,
    FAILURE_WORKER_STARTUP_TIMEOUT: RunOutcomeClass.CRASHED,
    FAILURE_WORKER_UNRESPONSIVE: RunOutcomeClass.CRASHED,
    FAILURE_WORKER_CRASHED: RunOutcomeClass.CRASHED,
    FAILURE_WORKER_LOST: RunOutcomeClass.CRASHED,
    FAILURE_RUN_ABANDONED: RunOutcomeClass.CRASHED,
    FAILURE_RUN_CONCLUDED_OUT_OF_BAND: RunOutcomeClass.CRASHED,
    FAILURE_RESULT_INVALID: RunOutcomeClass.CRASHED,
    FAILURE_RESULT_CONTRADICTS_SPEC: RunOutcomeClass.CRASHED,
    FAILURE_RUNNER_FAILED: RunOutcomeClass.CRASHED,
    #: Slice 08: the supervisor's own gate or supervision loop raised.
    FAILURE_SUPERVISOR_FAULT: RunOutcomeClass.CRASHED,
    # a caller, or the supervisor, stopped it
    FAILURE_CANCELLED: RunOutcomeClass.CANCELLED,
    FAILURE_SUPERVISOR_STOPPED: RunOutcomeClass.CANCELLED,
})

#: Status -> outcome, where the status alone decides. `errored` is absent on purpose:
#: only its failure code can say what happened.
_STATUS_OUTCOMES: Mapping[RunStatus, RunOutcomeClass] = MappingProxyType({
    RunStatus.PASSED: RunOutcomeClass.PASSED,
    RunStatus.FAILED: RunOutcomeClass.FAILED,
    RunStatus.CANCELLED: RunOutcomeClass.CANCELLED,
    #: A run killed on its budget measured an unknown part of what it needed.
    RunStatus.TIMED_OUT: RunOutcomeClass.INCONCLUSIVE,
    RunStatus.QUEUED: RunOutcomeClass.PENDING,
    RunStatus.RUNNING: RunOutcomeClass.PENDING,
})


def outcome_of(status: RunStatus, failure_code: str | None) -> RunOutcomeClass:
    """The outcome of a `(status, failure code)` pair, without needing the record.

    The status decides wherever it can; `errored` is read from `FAILURE_OUTCOMES`,
    and an unmapped or absent code reads `crashed` (see the table's comment).
    """
    if not isinstance(status, RunStatus):
        raise fail("outcome_of takes a RunStatus")
    if failure_code is not None and not isinstance(failure_code, str):
        raise fail("outcome_of takes a failure code string or None")
    known = _STATUS_OUTCOMES.get(status)
    if known is not None:
        return known
    return FAILURE_OUTCOMES.get(failure_code or "", RunOutcomeClass.CRASHED)


@dataclass(frozen=True, slots=True)
class RunOutcomeSummary:
    """One run read as an outcome, with the facts that justify it.

    Everything here is derived from the stored record: a caller (CLI, HTTP API,
    UI) can answer "passed / failed / could not measure / refused" and show why,
    without parsing a failure detail.
    """

    run_id: str
    status: RunStatus
    outcome: RunOutcomeClass
    #: Stable failure code, or None for `passed` / `failed` / a non-terminal run.
    failure_code: str | None
    #: The blocking-assertion verdict the status was derived from.
    verdict: AssertionVerdict
    #: Blocking assertions that failed, sorted; the shortest honest answer to "what broke".
    failed_assertions: tuple[str, ...]
    #: Blocking assertions whose metric was never measured, sorted.
    missing_assertions: tuple[str, ...]
    #: True when the run recorded at least one metric.
    measured: bool
    score: float | None

    @property
    def conclusive(self) -> bool:
        """True when the run judged the product either way."""
        return self.outcome in (RunOutcomeClass.PASSED, RunOutcomeClass.FAILED)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "status": self.status.value, "outcome": self.outcome.value,
                "failure_code": self.failure_code, "verdict": self.verdict.value,
                "failed_assertions": list(self.failed_assertions),
                "missing_assertions": list(self.missing_assertions),
                "measured": self.measured, "score": self.score}


def classify_run(run: TestRun) -> RunOutcomeSummary:
    """Read one stored run as an outcome. Pure, total, and never raises on a valid record."""
    if not isinstance(run, TestRun):
        raise fail("classify_run takes a TestRun")
    failure_code = run.failure.code if run.failure is not None else None
    blocking = [result for result in run.assertion_results if result.blocking]
    return RunOutcomeSummary(
        run_id=run.run_id,
        status=run.status,
        outcome=outcome_of(run.status, failure_code),
        failure_code=failure_code,
        verdict=run.verdict,
        failed_assertions=tuple(sorted(result.assertion_id for result in blocking
                                       if result.outcome is AssertionOutcome.FAILED)),
        missing_assertions=tuple(sorted(result.assertion_id for result in blocking
                                        if result.outcome is AssertionOutcome.MISSING)),
        measured=bool(run.metrics),
        score=run.score,
    )
