"""Orchestrating a parameter sweep: fan out isolated runs, report, never decide.

Binding contract: `docs/testlab.md` ("Sweeps"). This is the I/O half of
`jarvis.testlab.sweeps`: it resolves the declaration through the catalog,
expands the points, submits one ordinary `RunRequest` per run, and writes what
happened. Every run is a normal supervised, isolated run — a sweep adds no
execution path of its own, which is what keeps its results comparable with a
single run's.

Four properties the orchestration owes its caller:

- **Bounded fan-out.** Submission is windowed (`SweepPolicy.max_in_flight`,
  clamped to the supervisor's `max_concurrent_runs`). Submitting every point at
  once would not run them faster — the supervisor bounds concurrency anyway —
  but it WOULD make every queued run accrue blocked time against
  `max_queue_wait_s` and expire as `resource_wait_timeout`. A sweep that refused
  its own points would be an experiment ruined by its own dispatcher.
- **Partial failure is a result, not an abort.** A point whose run errored,
  timed out or could not even be submitted is recorded with its outcome, and the
  sweep carries on. One unusable point is data; losing the other twenty is not.
- **Visible progress.** Every finished run emits a diagnostic with the point
  label, the outcome, `completed/total` and the elapsed seconds, and the sweep
  record on disk is rewritten at the same moment. A long sweep is never a silent
  process, and a crashed orchestrator leaves the points it had already run.
- **Nothing permanent is written.** The sweep reads the settings file exactly as
  a single run does (through the supervisor, which copies it into the run
  scratch) and has no write path to it. The summary names the best point per
  metric and stops there: applying it is a human decision.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from jarvis.ports.v2 import DiagnosticSink
from jarvis.testlab._diagnostics import SafeDiagnostics
from jarvis.testlab.capture import failure_detail
from jarvis.testlab.compare import RunAggregate, aggregate_runs, compare_runs
from jarvis.testlab.diagnostics import MetricDirection
from jarvis.testlab.identity import TESTLAB_SCHEMA_VERSION, format_sweep_id
from jarvis.testlab.outcomes import RunOutcomeClass, classify_run
from jarvis.testlab.profiles import ResourceGrant
from jarvis.testlab.runs import RunFailure, TestRun
from jarvis.testlab.store import SweepStore, TestLabStoreError
from jarvis.testlab.supervisor import RunRequest, RunSupervisor, SupervisorError
from jarvis.testlab.sweeps import (
    SWEEP_INVALID,
    SWEEP_SUMMARY_SCHEMA,
    SweepError,
    SweepPoint,
    SweepPointResult,
    SweepRecord,
    SweepRunOutcome,
    SweepSpec,
    SweepStatus,
    check_sweep_spec,
    sweep_failure,
)
from jarvis.testlab.validation import TestLabError, format_time

#: What the summary says, in one sentence, next to the best point of every metric.
SUMMARY_NOTE = ("A sweep reports; it never writes a winning value into permanent Jarvis settings. "
                "Every value here was applied run-locally, to an isolated copy.")


@dataclass(frozen=True, slots=True)
class SweepPolicy:
    """Bounds the orchestrator enforces on top of the supervisor's own."""

    #: Runs submitted at once. Clamped down to the supervisor's `max_concurrent_runs`,
    #: because a run queued behind a full supervisor accrues blocked time it can expire on.
    max_in_flight: int = 2
    #: How long the sweep waits for one run's terminal record. The supervisor bounds the
    #: run itself; this only bounds the WAIT, so a sweep can never hang on one point.
    run_timeout_s: float = 900.0


@dataclass(slots=True)
class _Progress:
    """Mutable state of one sweep in flight."""

    record: SweepRecord
    points: tuple[SweepPoint, ...]
    runs: dict[int, list[SweepRunOutcome]]
    failures: dict[int, RunFailure]
    active: set[str]
    total: int
    completed: int = 0
    cancelled: bool = False


class SweepRunner:
    """Run a `SweepSpec` through a `RunSupervisor`, persisting the record as it goes."""

    def __init__(self, *, supervisor: RunSupervisor, store: SweepStore, policy: SweepPolicy = SweepPolicy(),
                 diagnostics: DiagnosticSink | None = None, clock: Any = None, nonce: Any = None) -> None:
        self._supervisor = supervisor
        self._store = store
        self._policy = policy
        self._diagnostics = SafeDiagnostics(diagnostics)
        self._clock = clock if clock is not None else supervisor.clock
        self._nonce = nonce if nonce is not None else supervisor.nonce
        self._in_flight: dict[str, _Progress] = {}

    @property
    def active_sweep_ids(self) -> tuple[str, ...]:
        return tuple(self._in_flight)

    # ------------------------------------------------------------------ run

    async def run(self, spec: SweepSpec, *, grant: ResourceGrant = ResourceGrant()) -> SweepRecord:
        """Execute every point of the sweep and return the final record.

        Raises `SweepError` only when no honest record could be written at all (an
        unknown diagnostic, an unsupported profile, a value the declaration refuses):
        there is then nothing to record the experiment against. Everything that can
        happen afterwards — a refused run, a crashed worker, a cancelled sweep — is
        persisted in the record instead.
        """
        if not isinstance(spec, SweepSpec):
            raise SweepError(SWEEP_INVALID, "run takes a SweepSpec")
        entry = self._describe(spec)
        points = check_sweep_spec(spec, entry.diagnostic, entry.manifest.override_allowlist)
        created_at = self._clock()
        record = SweepRecord(sweep_id=format_sweep_id(created_at, self._nonce()), created_at=created_at, spec=spec,
                             status=SweepStatus.RUNNING, diagnostic_version=entry.version,
                             diagnostic_fingerprint=entry.diagnostic.fingerprint(),
                             points=tuple(SweepPointResult(point) for point in points))
        progress = _Progress(record=record, points=points, runs={index: [] for index in range(len(points))},
                             failures={}, active=set(), total=len(points) * spec.repetitions)
        self._in_flight[record.sweep_id] = progress
        try:
            await asyncio.to_thread(self._store.put_sweep, record)
            self._diagnostics.emit("testlab.sweep.started", f"Test Lab sweep {record.sweep_id} started",
                                   sweep_id=record.sweep_id, diagnostic=spec.diagnostic_id, version=entry.version,
                                   profile=spec.profile.value, points=len(points), runs=progress.total,
                                   in_flight=self._window())
            await self._execute(progress, spec, grant)
            return await self._finish(progress, spec, entry.diagnostic)
        finally:
            self._in_flight.pop(record.sweep_id, None)

    async def cancel(self, sweep_id: str) -> bool:
        """Stop a sweep this runner is executing: no further point starts, in-flight runs are cancelled.

        Returns False when this runner does not hold that sweep (unknown id, or
        already finished). The points already executed stay in the record.
        """
        progress = self._in_flight.get(sweep_id)
        if progress is None:
            return False
        progress.cancelled = True
        self._diagnostics.emit("testlab.sweep.cancelling", f"Test Lab sweep {sweep_id} asked to stop",
                               sweep_id=sweep_id, active_runs=len(progress.active),
                               completed=progress.completed, total=progress.total)
        for run_id in sorted(progress.active):
            await self._supervisor.cancel(run_id, reason=f"sweep {sweep_id} cancelled")
        return True

    # ------------------------------------------------------------ execution

    def _describe(self, spec: SweepSpec) -> Any:
        try:
            return self._supervisor.catalog.describe(spec.diagnostic_id, spec.version)
        except TestLabError as exc:
            raise SweepError(SWEEP_INVALID, exc.detail) from None

    def _window(self) -> int:
        """In-flight submissions, never more than the supervisor will execute at once."""
        return max(1, min(self._policy.max_in_flight, self._supervisor.policy.max_concurrent_runs))

    async def _execute(self, progress: _Progress, spec: SweepSpec, grant: ResourceGrant) -> None:
        gate = asyncio.Semaphore(self._window())
        tasks = [asyncio.create_task(self._one(progress, spec, grant, point, repetition, gate),
                                     name=f"testlab-sweep-{progress.record.sweep_id}-{point.index}-{repetition}")
                 for point in progress.points for repetition in range(spec.repetitions)]
        await asyncio.gather(*tasks, return_exceptions=False)

    async def _one(self, progress: _Progress, spec: SweepSpec, grant: ResourceGrant, point: SweepPoint,
                   repetition: int, gate: asyncio.Semaphore) -> None:
        """Submit, wait for and record one run. Never raises: a failed point is a result."""
        async with gate:
            if progress.cancelled:
                return  # a point the cancel reached before it started simply has no run
            started = asyncio.get_running_loop().time()
            run_id: str | None = None
            try:
                run_id = await self._supervisor.submit(RunRequest(
                    diagnostic_id=spec.diagnostic_id, profile=spec.profile, version=progress.record.diagnostic_version,
                    parameters=point.parameters, overrides=point.overrides, scenario=spec.scenario,
                    sweep_id=progress.record.sweep_id, grant=grant))
                progress.active.add(run_id)
                run = await self._supervisor.wait(run_id, timeout_s=self._policy.run_timeout_s)
            except (SupervisorError, TestLabStoreError) as exc:
                # Captured: one point that could not run is evidence, not a reason to abandon
                # the other points. The refusal is recorded against this point and reported.
                await self._record_point_failure(progress, point, exc, run_id)
                return
            except asyncio.TimeoutError:
                run = await self._read_or_none(run_id)
                if run is None:
                    await self._record_point_failure(
                        progress, point,
                        SweepError(SWEEP_INVALID, f"run {run_id} did not finish within "
                                                  f"{self._policy.run_timeout_s:.0f}s and cannot be read"), run_id)
                    return
            finally:
                if run_id is not None:
                    progress.active.discard(run_id)
        await self._record_run(progress, point, repetition, run, asyncio.get_running_loop().time() - started)

    async def _read_or_none(self, run_id: str | None) -> TestRun | None:
        if run_id is None:
            return None
        try:
            return await self._supervisor.status(run_id)
        except TestLabError:
            return None  # intentional: the caller turns "no record" into a recorded point failure

    async def _record_run(self, progress: _Progress, point: SweepPoint, repetition: int, run: TestRun,
                          elapsed_s: float) -> None:
        summary = classify_run(run)
        progress.runs[point.index].append(SweepRunOutcome(run.run_id, run.status, summary.outcome,
                                                          summary.failure_code, run.score))
        progress.completed += 1
        level = "info" if summary.outcome in (RunOutcomeClass.PASSED, RunOutcomeClass.FAILED) else "warning"
        self._diagnostics.emit(
            "testlab.sweep.run_finished",
            f"Test Lab sweep {progress.record.sweep_id}: {progress.completed}/{progress.total} "
            f"({point.label or 'base'}) is {summary.outcome.value}", level=level,
            sweep_id=progress.record.sweep_id, run_id=run.run_id, point=point.index, label=point.label,
            repetition=repetition, outcome=summary.outcome.value, status=run.status.value,
            failure=summary.failure_code, score=run.score, completed=progress.completed, total=progress.total,
            elapsed_s=round(elapsed_s, 2))
        await self._persist(progress)

    async def _record_point_failure(self, progress: _Progress, point: SweepPoint, exc: Exception,
                                    run_id: str | None) -> None:
        failure = sweep_failure(failure_detail(f"{getattr(exc, 'code', type(exc).__name__)}: "
                                               f"{getattr(exc, 'detail', exc)}"))
        progress.failures[point.index] = failure
        progress.completed += 1
        self._diagnostics.emit("testlab.sweep.point_failed",
                               f"Test Lab sweep {progress.record.sweep_id}: point {point.index} could not run",
                               level="error", sweep_id=progress.record.sweep_id, point=point.index,
                               label=point.label, run_id=run_id, code=failure.code, detail=failure.detail,
                               completed=progress.completed, total=progress.total)
        await self._persist(progress)

    def _results(self, progress: _Progress) -> tuple[SweepPointResult, ...]:
        return tuple(SweepPointResult(point, tuple(progress.runs[point.index]), progress.failures.get(point.index))
                     for point in progress.points)

    async def _persist(self, progress: _Progress) -> None:
        """Rewrite the sweep record. A write failure never stops the sweep; it is reported."""
        progress.record = replace(progress.record, points=self._results(progress))
        try:
            await asyncio.to_thread(self._store.put_sweep, progress.record)
        except TestLabStoreError as exc:
            # Captured: the runs themselves are already durable in the run store, so the
            # experiment survives; only the progress log is behind, and the refusal says why.
            self._diagnostics.emit("testlab.sweep.record_not_stored",
                                   f"Test Lab sweep {progress.record.sweep_id} progress not stored", level="warning",
                                   sweep_id=progress.record.sweep_id, code=exc.code)

    async def _finish(self, progress: _Progress, spec: SweepSpec, diagnostic: Any) -> SweepRecord:
        finished_at = self._clock()
        status = SweepStatus.CANCELLED if progress.cancelled else SweepStatus.COMPLETED
        record = replace(progress.record, points=self._results(progress), status=status,
                         finished_at=max(finished_at, progress.record.created_at))
        progress.record = record
        try:
            await asyncio.to_thread(self._store.put_sweep, record)
        except TestLabStoreError as exc:
            self._diagnostics.emit("testlab.sweep.record_not_stored",
                                   f"Test Lab sweep {record.sweep_id} final record not stored", level="error",
                                   sweep_id=record.sweep_id, code=exc.code)
        await self._store_summary(record, diagnostic)
        self._diagnostics.emit("testlab.sweep.finished", f"Test Lab sweep {record.sweep_id} is {status.value}",
                               level="info" if status is SweepStatus.COMPLETED else "warning",
                               sweep_id=record.sweep_id, status=status.value, points=len(record.points),
                               runs=len(record.run_ids), outcomes=dict(record.outcome_counts()))
        return record

    # -------------------------------------------------------------- summary

    async def _store_summary(self, record: SweepRecord, diagnostic: Any) -> None:
        try:
            runs = await self._collect(record)
            document = build_sweep_summary(record, runs, diagnostic)
            await asyncio.to_thread(self._store.put_sweep_summary, record.sweep_id, document)
        except (TestLabError, TestLabStoreError) as exc:
            # Captured: the summary is a convenience derived from records that are all
            # durable. Losing it must not lose the sweep; the refusal names the reason.
            self._diagnostics.emit("testlab.sweep.summary_not_stored",
                                   f"Test Lab sweep {record.sweep_id} summary not stored", level="warning",
                                   sweep_id=record.sweep_id, code=getattr(exc, "code", type(exc).__name__))

    async def _collect(self, record: SweepRecord) -> Mapping[str, TestRun]:
        """The stored record of every run of the sweep, by run id. A vanished one is skipped."""
        found: dict[str, TestRun] = {}
        for run_id in record.run_ids:
            run = await self._read_or_none(run_id)
            if run is not None:
                found[run_id] = run
        return found


# ------------------------------------------------------------------ summary

def build_sweep_summary(record: SweepRecord, runs: Mapping[str, TestRun], diagnostic: Any) -> dict[str, Any]:
    """The readable summary artifact: per-point aggregates, deltas to the first point, best values.

    Pure given its inputs, so it can be rebuilt from a stored sweep and its runs at any
    time. It NAMES the best point for every directed metric and stops there: nothing here
    is applied, and `SUMMARY_NOTE` says so in the document itself.
    """
    metrics = getattr(diagnostic, "metric_index", {})
    aggregates: dict[int, RunAggregate] = {}
    points: list[dict[str, Any]] = []
    baseline = _first_conclusive(record, runs)
    for result in record.points:
        point_runs = [runs[run_id] for run_id in result.run_ids if run_id in runs]
        aggregate = aggregate_runs(point_runs, metrics=metrics)
        aggregates[result.point.index] = aggregate
        candidate = _first_conclusive_of(point_runs)
        comparison = (compare_runs(baseline, candidate, metrics=metrics).to_dict()
                      if baseline is not None and candidate is not None and candidate.run_id != baseline.run_id
                      else None)
        points.append({"index": result.point.index, "label": result.point.label,
                       "values": dict(result.point.values), "aggregate": aggregate.to_dict(),
                       "failure": None if result.failure is None else result.failure.to_dict(),
                       "comparison_to_baseline": comparison})
    return {
        "schema": SWEEP_SUMMARY_SCHEMA,
        "schema_version": TESTLAB_SCHEMA_VERSION,
        "sweep_id": record.sweep_id,
        "diagnostic_id": record.spec.diagnostic_id,
        "diagnostic_version": record.diagnostic_version,
        "diagnostic_fingerprint": record.diagnostic_fingerprint,
        "profile": record.spec.profile.value,
        "status": record.status.value,
        "created_at": format_time(record.created_at),
        "finished_at": format_time(record.finished_at),
        "swept": [axis.to_dict() for axis in record.spec.swept],
        "repetitions": record.spec.repetitions,
        "outcomes": dict(record.outcome_counts()),
        "baseline_run_id": None if baseline is None else baseline.run_id,
        "points": points,
        "best_points": _best_points(aggregates, metrics),
        "note": SUMMARY_NOTE,
    }


def _first_conclusive(record: SweepRecord, runs: Mapping[str, TestRun]) -> TestRun | None:
    return _first_conclusive_of([runs[run_id] for run_id in record.run_ids if run_id in runs])


def _first_conclusive_of(runs: Sequence[TestRun]) -> TestRun | None:
    """The first run that actually measured something; a refused run is no baseline."""
    for run in runs:
        if run.metrics:
            return run
    return None


def _best_points(aggregates: Mapping[int, RunAggregate], metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """For every directed metric, which point had the best median. Named, never applied."""
    best: list[dict[str, Any]] = []
    for name in sorted({item.metric for aggregate in aggregates.values() for item in aggregate.metrics}):
        spec = metrics.get(name)
        if spec is None or spec.direction is MetricDirection.NEUTRAL:
            continue
        medians = [(aggregate_item.median, index) for index, aggregate in aggregates.items()
                   for aggregate_item in aggregate.metrics if aggregate_item.metric == name]
        if not medians:
            continue
        chosen = (max if spec.direction is MetricDirection.HIGHER_BETTER else min)(medians)
        best.append({"metric": name, "direction": spec.direction.value, "point": chosen[1], "median": chosen[0]})
    return best
