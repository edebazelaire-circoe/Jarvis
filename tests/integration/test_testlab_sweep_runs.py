"""Slice 07 end to end: a real sweep, through a real supervisor and real worker processes.

Bounded on purpose (this host has little free RAM): at most two concurrent workers, two
or three points per sweep, and the voice stack is mounted only by the one test that has
to prove the `virtual` profile really sweeps. The cheaper cases use the `selftest.worker`
FIXTURE diagnostic, which is a real subprocess without the voice stack.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from jarvis.testlab.diagnostics import ParameterSpec, ParameterType
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.filesystem_sweep_store import FilesystemSweepStore
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.outcomes import RunOutcomeClass
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import CodeIdentity, RunStatus
from jarvis.testlab.scoring import compute_score
from jarvis.testlab.selftest import SELFTEST_DIAGNOSTIC_ID, write_selftest_catalog
from jarvis.testlab.store import RunQuery
from jarvis.testlab.supervisor import RunSupervisor, SupervisorPolicy
from jarvis.testlab.sweep_runner import SUMMARY_NOTE, SweepPolicy, SweepRunner
from jarvis.testlab.sweeps import SweepSpec, SweepStatus, SweepTarget, SweptParameter

T0 = datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc)
#: Real interpreter startup plus the catalog load (and, for the virtual seed, the voice stack import).
STARTUP_TIMEOUT_S = 90.0
WAIT_S = 300.0
ECHO_GUARD = ParameterSpec("voice.echo_guard_ms", ParameterType.INT, 400, minimum=0, maximum=5000)


def _clock():
    state = {"n": 0}

    def now() -> datetime:
        state["n"] += 1
        return T0 + timedelta(milliseconds=state["n"])

    return now


def _nonce():
    state = {"n": 0}

    def next_nonce() -> str:
        state["n"] += 1
        return f"{state['n']:016x}"

    return next_nonce


async def _code():
    return CodeIdentity("7" * 40, False)


def build(tmp_path: Path, *, catalog_root: Path | None = None, max_concurrent_runs: int = 2,
          settings_path: Path | None = None):
    """A supervisor with the real subprocess launcher, plus the sweep store beside its run store."""
    store = FilesystemTestRunStore(tmp_path / "store")
    policy = SupervisorPolicy(max_concurrent_runs=max_concurrent_runs, startup_timeout_s=STARTUP_TIMEOUT_S,
                              heartbeat_timeout_s=90.0, cancel_grace_s=20.0, poll_interval_s=0.05,
                              maintenance=MaintenancePolicy(enabled=False))
    kwargs = {} if catalog_root is None else {"catalog_root": catalog_root}
    supervisor = RunSupervisor(store=store, work_root=tmp_path / "work", policy=policy, clock=_clock(),
                               nonce=_nonce(), code_probe=_code, settings_path=settings_path,
                               environment={"os": "windows", "python_version": "3.14.6"}, **kwargs)
    return supervisor, store, FilesystemSweepStore(tmp_path / "store")


def sweeper(supervisor, sweep_store, *, max_in_flight: int = 2) -> SweepRunner:
    return SweepRunner(supervisor=supervisor, store=sweep_store,
                       policy=SweepPolicy(max_in_flight=max_in_flight, run_timeout_s=WAIT_S))


async def test_a_small_virtual_sweep_fans_out_over_real_workers(tmp_path):
    """Two points of `voice.queue_latency`, two real workers, one shared sweep id."""
    supervisor, store, sweep_store = build(tmp_path, max_concurrent_runs=2)
    spec = SweepSpec(diagnostic_id="voice.queue_latency", profile=ProfileName.VIRTUAL,
                     parameters={"speech.request_count": 1},
                     swept=(SweptParameter("brain.result_delay_ms", SweepTarget.PARAMETER, (100, 400)),),
                     title="brain thinking time")
    await supervisor.start()
    try:
        record = await sweeper(supervisor, sweep_store).run(spec)
    finally:
        await supervisor.aclose()

    assert record.status is SweepStatus.COMPLETED
    assert record.outcome_counts() == {"passed": 2}
    assert len(record.run_ids) == 2
    # The store's own sweep filter finds exactly this sweep's runs.
    listed = store.list_runs(RunQuery(sweep_id=record.sweep_id, limit=50))
    assert sorted(run.run_id for run in listed.runs) == sorted(record.run_ids)
    assert {run.parameters["brain.result_delay_ms"] for run in listed.runs} == {100, 400}
    # The score is computed by the SUPERVISOR from the shipped `weighted_mean` contract:
    # the stored number is exactly the declared synthesis of the stored metrics.
    spec_declaration = supervisor.catalog.describe("voice.queue_latency").diagnostic
    assert all(run.score == compute_score(spec_declaration.score, run.metrics) for run in listed.runs)
    assert all(run.score is not None and 0.0 <= run.score <= 100.0 for run in listed.runs)

    stored = sweep_store.get_sweep(record.sweep_id)
    assert stored == record and stored.spec.title == "brain thinking time"
    summary = sweep_store.get_sweep_summary(record.sweep_id)
    assert [point["label"] for point in summary["points"]] == ["brain.result_delay_ms=100",
                                                               "brain.result_delay_ms=400"]
    assert summary["points"][1]["comparison_to_baseline"]["comparable"] is True
    assert summary["note"] == SUMMARY_NOTE
    # The end-to-end metric is dominated by the swept brain time, which is the point of the sweep.
    by_delay = {run.parameters["brain.result_delay_ms"]: run.metrics for run in listed.runs}
    assert by_delay[400]["user_turn.end_to_first_audio_ms"] >= 400


async def test_a_sweep_keeps_going_when_one_point_fails(tmp_path):
    """A failing point is a result: the sweep records it and runs the rest (fixture diagnostic)."""
    catalog_root = write_selftest_catalog(tmp_path / "catalog")
    supervisor, store, sweep_store = build(tmp_path, catalog_root=catalog_root, max_concurrent_runs=2)
    spec = SweepSpec(diagnostic_id=SELFTEST_DIAGNOSTIC_ID, profile=ProfileName.VIRTUAL,
                     swept=(SweptParameter("value", SweepTarget.PARAMETER, (0, 3)),))
    await supervisor.start()
    try:
        record = await sweeper(supervisor, sweep_store).run(spec)
    finally:
        await supervisor.aclose()

    assert record.status is SweepStatus.COMPLETED
    assert record.outcome_counts() == {"failed": 1, "passed": 1}
    assert [point.runs[0].outcome for point in record.points] == [RunOutcomeClass.PASSED, RunOutcomeClass.FAILED]
    assert all(point.failure is None for point in record.points)
    failing = store.get_run(record.points[1].run_ids[0])
    assert failing.status is RunStatus.FAILED and failing.metrics["selftest.value"] == 3


async def test_a_sweep_can_be_cancelled_and_keeps_what_already_ran(tmp_path):
    """Cancel stops further points and ends the in-flight ones; the record says `cancelled`."""
    catalog_root = write_selftest_catalog(tmp_path / "catalog", max_duration_s=300)
    supervisor, _store, sweep_store = build(tmp_path, catalog_root=catalog_root, max_concurrent_runs=1)
    runner = sweeper(supervisor, sweep_store, max_in_flight=1)
    spec = SweepSpec(diagnostic_id=SELFTEST_DIAGNOSTIC_ID, profile=ProfileName.VIRTUAL,
                     parameters={"mode": "sleep"},
                     swept=(SweptParameter("sleep_ms", SweepTarget.PARAMETER, (120000, 1, 2)),))
    await supervisor.start()
    try:
        task = asyncio.create_task(runner.run(spec))
        sweep_id = await _until_active(runner)
        await _until_running(supervisor)
        assert await runner.cancel(sweep_id) is True
        record = await asyncio.wait_for(task, timeout=WAIT_S)
    finally:
        await supervisor.aclose()

    assert record.status is SweepStatus.CANCELLED and record.finished_at is not None
    assert len(record.run_ids) == 1  # only the first point ever started
    assert record.points[0].runs[0].outcome is RunOutcomeClass.CANCELLED
    assert record.points[1].runs == () and record.points[2].runs == ()
    assert sweep_store.get_sweep(sweep_id).status is SweepStatus.CANCELLED


async def test_a_sweep_never_writes_the_permanent_settings_file(tmp_path):
    """Locked decision 9, proven against a real settings file: the sweep reports, a human decides."""
    settings = tmp_path / "control-center-settings.json"
    settings.write_text(json.dumps({"voice.echo_guard_ms": 400}, indent=2) + "\n", encoding="utf-8")
    before = settings.read_bytes()
    catalog_root = write_selftest_catalog(tmp_path / "catalog", override_allowlist=(ECHO_GUARD,))
    supervisor, store, sweep_store = build(tmp_path, catalog_root=catalog_root, max_concurrent_runs=2,
                                           settings_path=settings)
    spec = SweepSpec(diagnostic_id=SELFTEST_DIAGNOSTIC_ID, profile=ProfileName.VIRTUAL,
                     swept=(SweptParameter("voice.echo_guard_ms", SweepTarget.OVERRIDE, (100, 900)),))
    await supervisor.start()
    try:
        record = await sweeper(supervisor, sweep_store).run(spec)
    finally:
        await supervisor.aclose()

    assert record.status is SweepStatus.COMPLETED and record.outcome_counts() == {"passed": 2}
    assert settings.read_bytes() == before, "a sweep must never write the permanent settings file"
    overrides = {frozenset(store.get_run(run_id).overrides.items()) for run_id in record.run_ids}
    assert overrides == {frozenset({("voice.echo_guard_ms", 100)}), frozenset({("voice.echo_guard_ms", 900)})}
    assert sweep_store.get_sweep_summary(record.sweep_id)["note"] == SUMMARY_NOTE


async def _until_active(runner: SweepRunner) -> str:
    for _ in range(2000):
        if runner.active_sweep_ids:
            return runner.active_sweep_ids[0]
        await asyncio.sleep(0.01)
    raise AssertionError("the sweep never became active")


async def _until_running(supervisor: RunSupervisor) -> None:
    for _ in range(int(STARTUP_TIMEOUT_S * 20)):
        if supervisor.active_run_ids:
            run = await supervisor.status(supervisor.active_run_ids[0])
            if run.status is RunStatus.RUNNING:
                return
        await asyncio.sleep(0.05)
    raise AssertionError("no run of the sweep ever started")
