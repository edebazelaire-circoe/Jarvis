"""Sweep orchestration: fan-out, partial failure, cancellation, and the persisted record.

The supervisor is stubbed here (a real one costs a worker process per point); the real
fan-out through real workers is `tests/integration/test_testlab_sweep_runs.py`.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from jarvis.testlab.catalog import Catalog
from jarvis.testlab.diagnostics import ParameterSpec, ParameterType
from jarvis.testlab.filesystem_sweep_store import FilesystemSweepStore
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.manifests import CatalogLock, DiagnosticManifest, lock_entry_for
from jarvis.testlab.outcomes import RunOutcomeClass
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import CodeIdentity, RunFailure, RunStatus, TestRun, complete_run, transition_run
from jarvis.testlab.scoring import compute_score
from jarvis.testlab.selftest import SELFTEST_DIAGNOSTIC_ID, catalog_implementations, selftest_manifest
from jarvis.testlab.supervisor import SupervisorError, SupervisorPolicy, derive_assertion_results
from jarvis.testlab.sweep_runner import SUMMARY_NOTE, SweepPolicy, SweepRunner, build_sweep_summary
from jarvis.testlab.sweeps import SweepError, SweepSpec, SweepStatus, SweepTarget, SweptParameter
from tests.fakes.testlab import CONFIG, ENVIRONMENT, REVISION, T0

ALLOWLIST = (ParameterSpec("voice.echo_guard_ms", ParameterType.INT, 400, minimum=0, maximum=5000),)


def catalog(override_allowlist=()) -> Catalog:
    manifest = DiagnosticManifest(selftest_manifest().diagnostic, override_allowlist)
    return Catalog.build([(manifest.relative_path, manifest)], CatalogLock((lock_entry_for(manifest),)),
                         primitives=DEFAULT_PRIMITIVES, implementations=catalog_implementations())


class StubSupervisor:
    """A supervisor that records submissions and concludes each run from its `value` parameter.

    It mimics exactly what the real one guarantees to a sweep: a run id per submit, a
    terminal record per wait, a concurrency bound, and a cancel that ends a run.
    """

    def __init__(self, *, entries=None, refuse=(), hang=(), max_concurrent_runs=2):
        self._catalog = catalog(entries or ())
        self.policy = SupervisorPolicy(max_concurrent_runs=max_concurrent_runs)
        self.submissions: list = []
        self.records: dict[str, TestRun] = {}
        self.cancelled: list[str] = []
        self.in_flight = 0
        self.peak_in_flight = 0
        self._refuse = set(refuse)
        self._hang = set(hang)
        self._release: dict[str, asyncio.Event] = {}
        self._counter = 0

    # the seams `SweepRunner` uses
    @property
    def catalog(self) -> Catalog:
        return self._catalog

    def clock(self):
        self._counter += 1
        return T0 + timedelta(milliseconds=self._counter)

    def nonce(self) -> str:
        return f"{len(self.submissions):016x}"

    async def submit(self, request) -> str:
        value = request.parameters.get("value")
        if value in self._refuse:
            raise SupervisorError("testlab_supervisor_request_invalid", f"value {value} is refused by this stub")
        self.submissions.append(request)
        created = self.clock()
        run_id = format_run_id(created, f"{len(self.submissions):016x}")
        spec = self._catalog.describe(request.diagnostic_id).diagnostic
        queued = TestRun(run_id=run_id, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                         profile=request.profile, status=RunStatus.QUEUED, created_at=created,
                         code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                         diagnostic_fingerprint=spec.fingerprint(),
                         parameters={"mode": "measure", "value": value if value is not None else 0,
                                     "sleep_ms": request.parameters.get("sleep_ms", 0)},
                         overrides=dict(request.overrides), environment=ENVIRONMENT, sweep_id=request.sweep_id)
        self.records[run_id] = queued
        self._release[run_id] = asyncio.Event()
        return run_id

    async def wait(self, run_id: str, *, timeout_s=None) -> TestRun:
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            queued = self.records[run_id]
            if queued.parameters.get("value") in self._hang:
                await asyncio.wait_for(self._release[run_id].wait(), timeout=timeout_s)
            await asyncio.sleep(0)
            self.records[run_id] = self._conclude(queued)
            return self.records[run_id]
        finally:
            self.in_flight -= 1

    def _conclude(self, queued: TestRun) -> TestRun:
        spec = self._catalog.describe(queued.diagnostic_id).diagnostic
        running = transition_run(queued, RunStatus.RUNNING, at=self.clock())
        if queued.run_id in self.cancelled:
            return transition_run(running, RunStatus.CANCELLED, at=self.clock(),
                                  failure=RunFailure("cancelled_by_caller", "asked to stop"))
        metrics = {"selftest.value": int(queued.parameters["value"]), "selftest.elapsed_ms": 5}
        return complete_run(running, at=self.clock(), assertion_results=derive_assertion_results(spec, metrics),
                            metrics=metrics, score=compute_score(spec.score, metrics))

    async def status(self, run_id: str) -> TestRun:
        return self.records[run_id]

    async def cancel(self, run_id: str, *, reason=None) -> bool:
        self.cancelled.append(run_id)
        self._release[run_id].set()
        return True


def runner(tmp_path, supervisor, **policy):
    store = FilesystemSweepStore(tmp_path / "store")
    return SweepRunner(supervisor=supervisor, store=store, policy=SweepPolicy(**policy)), store


def sweep(**changes) -> SweepSpec:
    values = dict(diagnostic_id=SELFTEST_DIAGNOSTIC_ID, profile=ProfileName.VIRTUAL,
                  swept=(SweptParameter("value", SweepTarget.PARAMETER, (0, 1, 2)),))
    values.update(changes)
    return SweepSpec(**values)


# --------------------------------------------------------------- fan-out

async def test_a_sweep_runs_every_point_once_and_records_them(tmp_path):
    supervisor = StubSupervisor()
    sweeper, store = runner(tmp_path, supervisor)
    record = await sweeper.run(sweep())
    assert record.status is SweepStatus.COMPLETED and len(record.points) == 3
    assert [len(point.runs) for point in record.points] == [1, 1, 1]
    assert [point.point.values["value"] for point in record.points] == [0, 1, 2]
    # value 0 passes the blocking assertion, 1 and 2 fail it: the sweep reports both.
    assert record.outcome_counts() == {"failed": 2, "passed": 1}
    assert store.get_sweep(record.sweep_id) == record


async def test_every_run_of_a_sweep_shares_its_sweep_id(tmp_path):
    supervisor = StubSupervisor()
    sweeper, _store = runner(tmp_path, supervisor)
    record = await sweeper.run(sweep())
    assert {request.sweep_id for request in supervisor.submissions} == {record.sweep_id}
    assert all(supervisor.records[run_id].sweep_id == record.sweep_id for run_id in record.run_ids)


async def test_repetitions_run_each_point_several_times(tmp_path):
    supervisor = StubSupervisor()
    sweeper, _store = runner(tmp_path, supervisor)
    record = await sweeper.run(sweep(swept=(SweptParameter("value", SweepTarget.PARAMETER, (0, 1)),), repetitions=3))
    assert [len(point.runs) for point in record.points] == [3, 3]
    assert len(record.run_ids) == 6


async def test_the_fan_out_never_exceeds_the_supervisor_concurrency(tmp_path):
    supervisor = StubSupervisor(max_concurrent_runs=2)
    sweeper, _store = runner(tmp_path, supervisor, max_in_flight=8)
    await sweeper.run(sweep(swept=(SweptParameter("value", SweepTarget.PARAMETER, tuple(range(6))),)))
    assert supervisor.peak_in_flight <= 2


async def test_a_swept_override_reaches_the_request_as_a_run_local_override(tmp_path):
    supervisor = StubSupervisor(entries=ALLOWLIST)
    sweeper, _store = runner(tmp_path, supervisor)
    await sweeper.run(sweep(swept=(SweptParameter("voice.echo_guard_ms", SweepTarget.OVERRIDE, (100, 200)),)))
    assert [dict(request.overrides) for request in supervisor.submissions] == [
        {"voice.echo_guard_ms": 100}, {"voice.echo_guard_ms": 200}]


# ------------------------------------------------------- partial failure

async def test_a_point_that_cannot_be_submitted_does_not_abandon_the_sweep(tmp_path):
    supervisor = StubSupervisor(refuse={1})
    sweeper, store = runner(tmp_path, supervisor)
    record = await sweeper.run(sweep())
    assert record.status is SweepStatus.COMPLETED
    failed = [point for point in record.points if point.failure is not None]
    assert [point.point.values["value"] for point in failed] == [1]
    assert failed[0].failure.code == "sweep_failed" and "refused by this stub" in failed[0].failure.detail
    assert sum(len(point.runs) for point in record.points) == 2
    assert store.get_sweep(record.sweep_id).points[1].failure is not None


async def test_a_failing_point_is_a_result_not_an_error(tmp_path):
    """A blocking assertion that fails is the product's verdict; the sweep records it and moves on."""
    supervisor = StubSupervisor()
    sweeper, _store = runner(tmp_path, supervisor)
    record = await sweeper.run(sweep())
    assert record.points[1].runs[0].outcome is RunOutcomeClass.FAILED
    assert record.points[1].failure is None


# --------------------------------------------------------- cancellation

async def test_cancelling_a_sweep_stops_it_and_keeps_what_ran(tmp_path):
    supervisor = StubSupervisor(hang={1}, max_concurrent_runs=1)
    sweeper, store = runner(tmp_path, supervisor, max_in_flight=1)
    task = asyncio.create_task(sweeper.run(sweep()))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if supervisor.in_flight and len(supervisor.submissions) == 2:
            break
    sweep_id = sweeper.active_sweep_ids[0]
    assert await sweeper.cancel(sweep_id) is True
    record = await asyncio.wait_for(task, timeout=10)
    assert record.status is SweepStatus.CANCELLED and record.finished_at is not None
    assert len(record.run_ids) == 2  # the first point ran, the second was cancelled, the third never started
    assert record.points[2].runs == ()
    assert store.get_sweep(sweep_id).status is SweepStatus.CANCELLED


async def test_cancelling_an_unknown_sweep_says_so(tmp_path):
    sweeper, _store = runner(tmp_path, StubSupervisor())
    assert await sweeper.cancel("tls-20260917T105800123Z-ffffffffffffffff") is False


# ----------------------------------------------------------- refusals

async def test_an_invalid_sweep_raises_before_any_record_exists(tmp_path):
    sweeper, store = runner(tmp_path, StubSupervisor())
    with pytest.raises(SweepError):
        await sweeper.run(sweep(swept=(SweptParameter("not.declared", SweepTarget.PARAMETER, (1, 2)),)))
    assert store.list_sweeps().sweeps == ()


async def test_a_sweep_of_an_unknown_diagnostic_raises(tmp_path):
    sweeper, _store = runner(tmp_path, StubSupervisor())
    with pytest.raises(SweepError, match="testlab_sweep_invalid"):
        await sweeper.run(sweep(diagnostic_id="voice.nothing_here"))


async def test_run_takes_a_sweep_spec(tmp_path):
    sweeper, _store = runner(tmp_path, StubSupervisor())
    with pytest.raises(SweepError, match="SweepSpec"):
        await sweeper.run({"diagnostic_id": SELFTEST_DIAGNOSTIC_ID})


# -------------------------------------------------------------- summary

async def test_the_summary_aggregates_every_point_and_names_the_best(tmp_path):
    supervisor = StubSupervisor()
    sweeper, store = runner(tmp_path, supervisor, max_in_flight=2)
    record = await sweeper.run(sweep(repetitions=2))
    summary = store.get_sweep_summary(record.sweep_id)
    assert summary["schema"] == "jarvis.testlab.sweep_summary"
    assert [point["label"] for point in summary["points"]] == ["value=0", "value=1", "value=2"]
    assert summary["points"][0]["aggregate"]["count"] == 2
    # `selftest.value` is lower_better, so point 0 (value 0) is the best.
    best = {item["metric"]: item["point"] for item in summary["best_points"]}
    assert best["selftest.value"] == 0
    assert summary["note"] == SUMMARY_NOTE


async def test_the_summary_compares_each_point_to_the_first(tmp_path):
    sweeper, store = runner(tmp_path, StubSupervisor())
    record = await sweeper.run(sweep())
    summary = store.get_sweep_summary(record.sweep_id)
    assert summary["points"][0]["comparison_to_baseline"] is None
    comparison = summary["points"][2]["comparison_to_baseline"]
    assert comparison["comparable"] is True
    delta = next(item for item in comparison["metrics"] if item["metric"] == "selftest.value")
    assert (delta["delta"], delta["change"]) == (2, "worse")


async def test_the_summary_is_rebuildable_from_stored_records(tmp_path):
    """Pure given its inputs: a caller rebuilds it later from the record and the runs."""
    supervisor = StubSupervisor()
    sweeper, store = runner(tmp_path, supervisor)
    record = await sweeper.run(sweep())
    rebuilt = build_sweep_summary(record, supervisor.records,
                                  catalog().describe(SELFTEST_DIAGNOSTIC_ID).diagnostic)
    assert rebuilt == dict(store.get_sweep_summary(record.sweep_id))
    assert rebuilt["note"] == SUMMARY_NOTE


async def test_a_summary_of_a_sweep_that_measured_nothing_still_stores(tmp_path):
    """Every point refused: no baseline, no best value, and still a readable document."""
    supervisor = StubSupervisor(refuse={0, 1, 2})
    sweeper, store = runner(tmp_path, supervisor)
    record = await sweeper.run(sweep())
    summary = store.get_sweep_summary(record.sweep_id)
    assert summary["baseline_run_id"] is None and summary["best_points"] == []
    assert all(point["failure"] is not None for point in summary["points"])


async def test_a_sweep_never_writes_a_permanent_setting(tmp_path):
    """The sweep reports; the human decides. The settings file it swept over is untouched."""
    settings = tmp_path / "control-center-settings.json"
    settings.write_text('{"voice.echo_guard_ms": 400}\n', encoding="utf-8")
    before = settings.read_bytes()
    supervisor = StubSupervisor(entries=ALLOWLIST)
    sweeper, store = runner(tmp_path, supervisor)
    record = await sweeper.run(sweep(swept=(SweptParameter("voice.echo_guard_ms", SweepTarget.OVERRIDE,
                                                           (100, 200, 300)),)))
    assert settings.read_bytes() == before
    summary = store.get_sweep_summary(record.sweep_id)
    assert summary["note"] == SUMMARY_NOTE
    # Every swept value travelled as a run-local override, never as a settings write.
    assert all(request.overrides for request in supervisor.submissions)
