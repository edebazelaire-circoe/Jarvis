"""Slice 05 supervisor policy: queueing, reservation, bounds, adoption, upkeep.

These tests never start a process: the launcher is a seam, and a fake worker
plays the worker's half of the file protocol (heartbeat file, result file, exit
code). Real processes are exercised in `tests/integration/test_testlab_worker.py`.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time

import pytest

from jarvis.testlab._fs import EntryLock
from jarvis.testlab.capture import CONFIG_SNAPSHOT_PATH
from jarvis.testlab.catalog import Catalog, load_catalog
from jarvis.testlab.diagnostics import ParameterSpec, ParameterType
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.implementations import registered
from jarvis.testlab.jobs import (
    CANCEL_FILE_NAME,
    FAILURE_CANCELLED,
    FAILURE_PERMISSION_DENIED,
    FAILURE_RESOURCE_WAIT_TIMEOUT,
    FAILURE_RESULT_CONTRADICTS_SPEC,
    FAILURE_RESULT_INVALID,
    FAILURE_RUN_ABANDONED,
    FAILURE_RUN_TIMEOUT,
    FAILURE_WORKER_CRASHED,
    FAILURE_WORKER_LOST,
    FAILURE_WORKER_SPAWN_FAILED,
    FAILURE_WORKER_STARTUP_TIMEOUT,
    FAILURE_WORKER_UNRESPONSIVE,
    HEARTBEAT_FILE_NAME,
    RESULT_FILE_NAME,
    RUNTIME_DIR_NAME,
    WORKER_LOCK_NAME,
    WorkerJob,
    WorkerResult,
    WorkerStatus,
    worker_failure,
)
from jarvis.testlab.maintenance import MaintenancePolicy, run_maintenance_pass
from jarvis.testlab.manifests import CatalogLock, DiagnosticManifest, lock_entry_for
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES
from jarvis.testlab.profiles import Capability, CostBounds, ProfileName, ProfileSpec, ResourceGrant
from jarvis.testlab.retention import TestLabRetentionPolicy
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.runners import RunArtifacts, RunContext
from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun, complete_run, transition_run
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.selftest import (
    SELFTEST_DIAGNOSTIC_ID,
    SelfTestMode,
    catalog_implementations,
    selftest_manifest,
    selftest_spec,
    write_selftest_catalog,
)
from jarvis.testlab.store import TestLabStoreError
from jarvis.testlab.supervisor import (
    SETTINGS_FILE_NAME,
    RunRequest,
    RunSupervisor,
    SupervisorError,
    SupervisorPolicy,
    _exit_label,
    apply_overrides,
    derive_assertion_results,
    worker_environment,
)

T0 = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
REVISION = "5" * 40
FAST = SupervisorPolicy(startup_timeout_s=0.6, heartbeat_timeout_s=0.6, cancel_grace_s=0.3, poll_interval_s=0.02,
                        max_queue_wait_s=60.0, maintenance=MaintenancePolicy(enabled=False))
PASSING_METRICS = {"selftest.value": 0, "selftest.elapsed_ms": 4}


# ------------------------------------------------------------------ doubles

class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.events]


class FakeWorker:
    """The worker's half of the protocol, without a process.

    Behaviours: `measure` (beat, write a result, exit 0), `no_result` (beat, exit 3),
    `silent` (never beats), `frozen` (beats once then stops), `polite` (beats and
    stops on the cancel marker), `hang` (beats forever, ignores the marker),
    `measure_then_frozen` / `measure_then_hang` (a complete measurement written just
    before a liveness fault or a deadline), `corrupt_result` (an unreadable result file).
    """

    def __init__(self, job: WorkerJob, behaviour: str, result: WorkerResult | None = None) -> None:
        self.job = job
        self.behaviour = behaviour
        self.result = result
        self.pid = 4242
        self.returncode: int | None = None
        self.killed = False
        self.closed = False
        self._code = 0
        self._done = asyncio.Event()
        self._task = asyncio.create_task(self._live(), name=f"fake-worker-{job.run_id}")

    @property
    def scratch(self) -> Path:
        return Path(self.job.scratch_root)

    def _beat(self) -> None:
        (self.scratch / HEARTBEAT_FILE_NAME).write_text(json.dumps({"pid": self.pid}), encoding="utf-8")

    def _write_result(self, result: WorkerResult) -> None:
        (self.scratch / RESULT_FILE_NAME).write_text(json.dumps(result.to_dict()), encoding="utf-8")

    async def _live(self) -> None:
        try:
            if self.behaviour == "silent":
                await asyncio.sleep(30)
                return
            self._beat()
            if self.behaviour == "corrupt_result":
                (self.scratch / RESULT_FILE_NAME).write_text("{ truncated", encoding="utf-8")
                self._code = 3
                return
            if self.behaviour.startswith("measure"):
                self._write_result(self.result or WorkerResult(self.job.run_id, WorkerStatus.MEASURED,
                                                               metrics=PASSING_METRICS))
                if self.behaviour == "measure":
                    return
            if self.behaviour == "no_result":
                self._code = 3
                return
            if self.behaviour in ("frozen", "measure_then_frozen"):
                await asyncio.sleep(30)
                return
            while True:
                await asyncio.sleep(0.02)
                self._beat()
                if self.behaviour == "polite" and (self.scratch / CANCEL_FILE_NAME).exists():
                    self._write_result(WorkerResult(self.job.run_id, WorkerStatus.FAILED,
                                                    failure=worker_failure(FAILURE_CANCELLED, "asked to stop")))
                    return
        finally:
            self.returncode = self._code
            self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        return self.returncode or 0

    async def kill_tree(self) -> None:
        self.killed = True
        self._task.cancel()
        self._code = -1
        self.returncode = -1
        self._done.set()

    def stderr_tail(self) -> str:
        return "fake worker stderr"

    async def aclose(self) -> None:
        self.closed = True
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


class FakeLauncher:
    def __init__(self, behaviour: str = "measure", result: WorkerResult | None = None) -> None:
        self.behaviour = behaviour
        self.result = result
        self.workers: list[FakeWorker] = []
        self.environs: list[dict] = []

    async def launch(self, job, *, environ, cwd) -> FakeWorker:
        self.environs.append(dict(environ))
        result = self.result and replace(self.result, run_id=job.run_id)
        worker = FakeWorker(job, self.behaviour, result)
        self.workers.append(worker)
        return worker


class RefusingLauncher(FakeLauncher):
    async def launch(self, job, *, environ, cwd):
        raise OSError("no process today")


def measured(metrics: dict) -> WorkerResult:
    return WorkerResult("tlr-20260917T120000000Z-" + "0" * 16, WorkerStatus.MEASURED, metrics=metrics)


# ----------------------------------------------------------------- fixtures

def _clock(offset_ms: int = 0):
    state = {"n": offset_ms}

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
    return CodeIdentity(REVISION, False)


def build(tmp_path: Path, *, policy: SupervisorPolicy = FAST, launcher=None, catalog=None,
          settings_path: Path | None = None, sink=None, max_duration_s: float = 60.0,
          override_allowlist: tuple[ParameterSpec, ...] = (), clock_offset_ms: int = 0,
          base_environ: dict[str, str] | None = None):
    catalog_root = write_selftest_catalog(tmp_path / "catalog", max_duration_s=max_duration_s,
                                          override_allowlist=override_allowlist)
    store = FilesystemTestRunStore(tmp_path / "store")
    launcher = launcher if launcher is not None else FakeLauncher()
    supervisor = RunSupervisor(store=store, work_root=tmp_path / "work", catalog_root=catalog_root,
                               catalog=catalog, policy=policy, launcher=launcher, settings_path=settings_path,
                               diagnostics=sink, clock=_clock(clock_offset_ms), nonce=_nonce(), code_probe=_code,
                               environment={"os": "windows", "python_version": "3.14.6"},
                               base_environ=base_environ)
    return supervisor, store, launcher


def request(**changes) -> RunRequest:
    values = dict(diagnostic_id=SELFTEST_DIAGNOSTIC_ID, profile=ProfileName.VIRTUAL,
                  parameters={"mode": SelfTestMode.MEASURE.value})
    values.update(changes)
    return RunRequest(**values)


async def run_once(supervisor: RunSupervisor, **changes) -> TestRun:
    run_id = await supervisor.submit(request(**changes))
    return await supervisor.wait(run_id, timeout_s=10)


async def until_active(supervisor: RunSupervisor, count: int = 1) -> None:
    for _ in range(500):
        if len(supervisor.active_run_ids) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no run started")


async def until_launched(launcher: FakeLauncher, count: int = 1) -> None:
    """A run is `active` as soon as it is reserved; its worker exists a few awaits later."""
    for _ in range(500):
        if len(launcher.workers) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no worker launched")


def _with(policy: SupervisorPolicy, **changes) -> SupervisorPolicy:
    return replace(policy, **changes)


# ------------------------------------------------------------- happy path

async def test_queue_running_terminal_happy_path(tmp_path):
    sink = RecordingSink()
    supervisor, store, launcher = build(tmp_path, sink=sink)
    async with supervisor:
        run_id = await supervisor.submit(request())
        queued = await supervisor.status(run_id)
        assert queued.status is RunStatus.QUEUED
        assert [ref.path for ref in queued.artifacts] == [CONFIG_SNAPSHOT_PATH]
        run = await supervisor.wait(run_id, timeout_s=10)
    assert run.status is RunStatus.PASSED
    assert dict(run.metrics) == PASSING_METRICS
    assert {result.assertion_id for result in run.assertion_results} == {"value_is_zero", "quick_enough"}
    assert run.started_at is not None and run.finished_at is not None
    assert {"testlab.run.queued", "testlab.run.started", "testlab.run.finished"} <= set(sink.kinds())
    assert launcher.workers[0].closed


async def test_the_verdict_is_derived_from_the_metrics_not_sent_by_the_worker(tmp_path):
    write_selftest_catalog(tmp_path / "catalog")
    spec = load_catalog(tmp_path / "catalog", implementations=catalog_implementations()).describe(
        SELFTEST_DIAGNOSTIC_ID).diagnostic
    results = derive_assertion_results(spec, {"selftest.value": 2})
    assert [(item.assertion_id, item.outcome.value) for item in results] == [
        ("value_is_zero", "failed"), ("quick_enough", "missing")]


async def test_a_failing_metric_makes_the_run_failed(tmp_path):
    supervisor, _, _ = build(tmp_path, launcher=FakeLauncher(
        "measure", measured({"selftest.value": 3, "selftest.elapsed_ms": 1})))
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.FAILED
    assert run.verdict.value == "failed"


# --------------------------------------------------------------- failures

async def test_a_worker_that_exits_without_a_result_is_errored(tmp_path):
    supervisor, _, _ = build(tmp_path, launcher=FakeLauncher("no_result"))
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_WORKER_CRASHED
    assert "3" in run.failure.detail


async def test_a_worker_that_never_starts_is_errored_on_the_startup_bound(tmp_path):
    supervisor, _, launcher = build(tmp_path, launcher=FakeLauncher("silent"))
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_WORKER_STARTUP_TIMEOUT
    assert launcher.workers[0].killed


async def test_a_worker_that_stops_beating_is_errored_and_killed(tmp_path):
    supervisor, _, launcher = build(tmp_path, launcher=FakeLauncher("frozen"))
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_WORKER_UNRESPONSIVE
    assert launcher.workers[0].killed


async def test_a_run_over_its_declared_budget_is_timed_out(tmp_path):
    supervisor, _, launcher = build(tmp_path, launcher=FakeLauncher("hang"), max_duration_s=0.2)
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.TIMED_OUT
    assert run.failure.code == FAILURE_RUN_TIMEOUT
    assert launcher.workers[0].killed


async def test_a_launcher_failure_is_a_terminal_run_not_an_exception(tmp_path):
    supervisor, _, _ = build(tmp_path, launcher=RefusingLauncher())
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_WORKER_SPAWN_FAILED


async def test_a_result_contradicting_the_declaration_is_refused(tmp_path):
    supervisor, _, _ = build(tmp_path, launcher=FakeLauncher("measure", measured({"selftest.unknown": 1})))
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_RESULT_CONTRADICTS_SPEC
    assert dict(run.metrics) == {}


# ------------------------------------------------------------ cancellation

async def test_cancel_is_cooperative_first(tmp_path):
    supervisor, _, launcher = build(tmp_path, launcher=FakeLauncher("polite"))
    async with supervisor:
        run_id = await supervisor.submit(request())
        await until_launched(launcher)
        assert await supervisor.cancel(run_id) is True
        run = await supervisor.wait(run_id, timeout_s=10)
    assert run.status is RunStatus.CANCELLED
    assert run.failure.code == FAILURE_CANCELLED
    assert launcher.workers[0].killed is False


async def test_cancel_falls_back_to_the_tree_kill(tmp_path):
    supervisor, _, launcher = build(tmp_path, launcher=FakeLauncher("hang"))
    async with supervisor:
        run_id = await supervisor.submit(request())
        await until_launched(launcher)
        await supervisor.cancel(run_id)
        run = await supervisor.wait(run_id, timeout_s=10)
    assert run.status is RunStatus.CANCELLED
    assert launcher.workers[0].killed is True
    assert "killed its process tree" in run.failure.detail


async def test_cancel_of_a_queued_run_is_immediate(tmp_path):
    supervisor, _, launcher = build(tmp_path, policy=_with(FAST, max_concurrent_runs=1),
                                    launcher=FakeLauncher("hang"))
    async with supervisor:
        first = await supervisor.submit(request())
        second = await supervisor.submit(request())
        await until_active(supervisor)
        assert await supervisor.cancel(second) is True
        assert (await supervisor.status(second)).status is RunStatus.CANCELLED
        assert len(launcher.workers) == 1
        await supervisor.cancel(first)
        await supervisor.wait(first, timeout_s=10)


async def test_cancel_of_an_unknown_run_says_so(tmp_path):
    supervisor, _, _ = build(tmp_path)
    async with supervisor:
        assert await supervisor.cancel("tlr-20260101T000000000Z-" + "0" * 16) is False


# -------------------------------------------------------------- resources

#: Slice 08: a provider reservation now also needs the explicit live opt-in. These two
#: tests are about RESERVATION, so they carry it; the opt-in itself is tested in
#: `tests/unit/test_testlab_devices.py`.
LIVE_ENVIRON = {"JARVIS_TESTLAB_LIVE": "1", "OPENAI_API_KEY": "test-key"}


def _live_catalog() -> Catalog:
    """A catalog whose only profile is `live`, so its runs declare a provider capability."""
    base = selftest_manifest()
    live = ProfileSpec(ProfileName.LIVE, "testlab.selftest.live", CostBounds(30, 0.25),
                       frozenset({Capability.REALTIME_PROVIDER}))
    manifest = DiagnosticManifest(replace(base.diagnostic, profiles={ProfileName.LIVE: live}))
    registry = catalog_implementations().with_entries(
        (registered("testlab.selftest.live", ProfileName.LIVE, object),))
    return Catalog.build([(manifest.relative_path, manifest)], CatalogLock((lock_entry_for(manifest),)),
                         primitives=DEFAULT_PRIMITIVES, implementations=registry)


async def test_two_runs_never_hold_the_same_declared_resource(tmp_path):
    sink = RecordingSink()
    supervisor, _, launcher = build(tmp_path, catalog=_live_catalog(), launcher=FakeLauncher("hang"),
                                    policy=_with(FAST, max_concurrent_runs=4), sink=sink,
                                    base_environ=LIVE_ENVIRON)
    grant = ResourceGrant(frozenset({Capability.REALTIME_PROVIDER}), max_cost_usd=1)
    async with supervisor:
        first = await supervisor.submit(request(profile=ProfileName.LIVE, grant=grant))
        second = await supervisor.submit(request(profile=ProfileName.LIVE, grant=grant))
        await until_active(supervisor)
        await asyncio.sleep(0.1)
        assert supervisor.active_run_ids == (first,)
        assert supervisor.pending_run_ids == (second,)
        assert supervisor.reserved_capabilities == frozenset({Capability.REALTIME_PROVIDER})
        assert (await supervisor.status(second)).status is RunStatus.QUEUED
        await supervisor.cancel(first)
        await supervisor.wait(first, timeout_s=10)
        await until_launched(launcher, 2)
        assert supervisor.active_run_ids == (second,)
        await supervisor.cancel(second)
        await supervisor.wait(second, timeout_s=10)
    assert "testlab.run.waiting" in sink.kinds()


async def test_virtual_runs_do_not_contend_but_respect_the_concurrency_bound(tmp_path):
    supervisor, _, _ = build(tmp_path, launcher=FakeLauncher("hang"), policy=_with(FAST, max_concurrent_runs=2))
    async with supervisor:
        ids = [await supervisor.submit(request()) for _ in range(3)]
        await until_active(supervisor, 2)
        await asyncio.sleep(0.1)
        assert len(supervisor.active_run_ids) == 2
        assert supervisor.pending_run_ids == (ids[2],)
        assert supervisor.reserved_capabilities == frozenset()
        for run_id in ids:
            await supervisor.cancel(run_id)
        for run_id in ids:
            await supervisor.wait(run_id, timeout_s=10)


async def test_a_run_that_waits_too_long_for_a_resource_is_refused(tmp_path):
    supervisor, _, _ = build(tmp_path, launcher=FakeLauncher("hang"),
                             policy=_with(FAST, max_concurrent_runs=1, max_queue_wait_s=0.1))
    async with supervisor:
        first = await supervisor.submit(request())
        second = await supervisor.submit(request())
        run = await supervisor.wait(second, timeout_s=10)
        assert run.status is RunStatus.ERRORED
        assert run.failure.code == FAILURE_RESOURCE_WAIT_TIMEOUT
        await supervisor.cancel(first)
        await supervisor.wait(first, timeout_s=10)


async def test_a_denied_grant_is_persisted_and_never_started(tmp_path):
    supervisor, _, launcher = build(tmp_path, catalog=_live_catalog(), base_environ=LIVE_ENVIRON)
    async with supervisor:
        run_id = await supervisor.submit(request(profile=ProfileName.LIVE))
        run = await supervisor.status(run_id)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_PERMISSION_DENIED
    assert "capability_missing realtime_provider" in run.failure.detail
    assert "cost_budget_exceeded" in run.failure.detail
    assert launcher.workers == []
    assert [ref.path for ref in run.artifacts] == [CONFIG_SNAPSHOT_PATH]


async def test_an_unsupported_request_is_refused_without_a_record(tmp_path):
    supervisor, store, _ = build(tmp_path)
    async with supervisor:
        with pytest.raises(SupervisorError):
            await supervisor.submit(request(diagnostic_id="voice.nothing"))
        with pytest.raises(SupervisorError):
            await supervisor.submit(request(profile=ProfileName.LIVE))
        with pytest.raises(SupervisorError):
            await supervisor.submit(request(parameters={"mode": "not_a_mode"}))
    assert store.list_runs().runs == ()


# -------------------------------------------------------------- overrides

def _allowlist() -> tuple[ParameterSpec, ...]:
    return (ParameterSpec("voice.turn_mode", ParameterType.ENUM, "auto", choices=("auto", "manual")),)


async def test_run_local_overrides_never_touch_the_permanent_settings(tmp_path):
    settings = tmp_path / SETTINGS_FILE_NAME
    settings.write_text(json.dumps({"voice.turn_mode": "auto", "theme": "dark"}), encoding="utf-8")
    before = settings.read_bytes()
    supervisor, _, launcher = build(tmp_path, settings_path=settings, override_allowlist=_allowlist(),
                                    launcher=FakeLauncher("hang"))
    async with supervisor:
        run_id = await supervisor.submit(request(overrides={"voice.turn_mode": "manual"}))
        await until_launched(launcher)
        copy = tmp_path / "work" / run_id / RUNTIME_DIR_NAME / SETTINGS_FILE_NAME
        assert json.loads(copy.read_text(encoding="utf-8")) == {"voice.turn_mode": "manual", "theme": "dark"}
        environ = launcher.environs[0]
        assert environ["JARVIS_RUNTIME_DIR"] == str(tmp_path / "work" / run_id / RUNTIME_DIR_NAME)
        assert environ["OPENAI_API_KEY"] == ""
        await supervisor.cancel(run_id)
        run = await supervisor.wait(run_id, timeout_s=10)
    assert settings.read_bytes() == before
    assert dict(run.overrides) == {"voice.turn_mode": "manual"}


async def test_an_override_outside_the_allowlist_is_refused(tmp_path):
    supervisor, _, _ = build(tmp_path, override_allowlist=_allowlist())
    async with supervisor:
        with pytest.raises(SupervisorError, match="override allowlist"):
            await supervisor.submit(request(overrides={"voice.other_mode": "x"}))
        with pytest.raises(SupervisorError):
            await supervisor.submit(request(overrides={"voice.turn_mode": "shouting"}))


async def test_scenario_prelude_overrides_reach_the_run(tmp_path):
    scenario = Scenario("selftest_prelude", (
        ScenarioStep("parameter.override", {"at_ms": 0, "parameter": "voice.turn_mode", "value": "manual"}),
        ScenarioStep("parameter.override", {"at_ms": 0, "parameter": "value", "value": 0}),
        ScenarioStep("time.wait", {"at_ms": 10}),
    ))
    supervisor, _, _ = build(tmp_path, override_allowlist=_allowlist(), launcher=FakeLauncher("hang"))
    async with supervisor:
        run_id = await supervisor.submit(request(scenario=scenario))
        run = await supervisor.status(run_id)
        assert dict(run.overrides) == {"voice.turn_mode": "manual"}
        assert run.parameters["value"] == 0
        assert run.scenario_id == "selftest_prelude"
        assert run.scenario_fingerprint == scenario.fingerprint()
        await supervisor.cancel(run_id)
        await supervisor.wait(run_id, timeout_s=10)


async def test_an_override_given_twice_with_two_values_is_refused(tmp_path):
    scenario = Scenario("selftest_prelude", (
        ScenarioStep("parameter.override", {"at_ms": 0, "parameter": "voice.turn_mode", "value": "manual"}),
        ScenarioStep("time.wait", {"at_ms": 10}),
    ))
    supervisor, _, _ = build(tmp_path, override_allowlist=_allowlist())
    async with supervisor:
        with pytest.raises(SupervisorError, match="overridden by both"):
            await supervisor.submit(request(scenario=scenario, overrides={"voice.turn_mode": "auto"}))


def test_apply_overrides_never_mutates_the_source_document():
    document = {"voice.turn_mode": "auto", "nested": {"kept": 1}}
    result = apply_overrides(document, {"voice.turn_mode": "manual", "nested.added": 2, "flat": 3})
    assert result == {"voice.turn_mode": "manual", "nested": {"kept": 1, "added": 2}, "flat": 3}
    assert document == {"voice.turn_mode": "auto", "nested": {"kept": 1}}


def test_worker_environment_gates_provider_credentials(tmp_path):
    base = {"OPENAI_API_KEY": "secret", "JARVIS_CORE_TOKEN_FILE": "C:/runtime/core.token", "PATH": "x"}
    closed = worker_environment(base, tmp_path / "scratch", allow_providers=False)
    assert closed["OPENAI_API_KEY"] == ""
    assert closed["JARVIS_TESTLAB_NO_PROVIDERS"] == "1"
    assert "JARVIS_CORE_TOKEN_FILE" not in closed
    assert closed["JARVIS_DATA_ROOT"] == str(tmp_path / "scratch" / "data")
    assert closed["JARVIS_TESTLAB_RUN_SCRATCH"] == str(tmp_path / "scratch")
    opened = worker_environment(base, tmp_path / "scratch", allow_providers=True)
    assert opened["OPENAI_API_KEY"] == "secret"
    assert "JARVIS_TESTLAB_NO_PROVIDERS" not in opened


# --------------------------------------------------------------- adoption

async def _abandoned(tmp_path: Path, *, running: bool, result: WorkerResult | None = None) -> str:
    """A run left in the store by a supervisor that died: no dispatcher ever ran."""
    supervisor, store, _ = build(tmp_path)
    run_id = await supervisor.submit(request())
    scratch = tmp_path / "work" / run_id
    scratch.mkdir(parents=True, exist_ok=True)
    if running:
        stored = store.get_run(run_id)
        store.update_run(transition_run(stored, RunStatus.RUNNING, at=T0 + timedelta(milliseconds=100)),
                         expected=stored)
    if result is not None:
        (scratch / RESULT_FILE_NAME).write_text(json.dumps(replace(result, run_id=run_id).to_dict()),
                                                encoding="utf-8")
    return run_id


async def test_a_queued_run_left_by_a_dead_supervisor_is_reaped(tmp_path):
    run_id = await _abandoned(tmp_path, running=False)
    supervisor, store, _ = build(tmp_path, clock_offset_ms=1000)
    report = await supervisor.start()
    await supervisor.aclose()
    run = store.get_run(run_id)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_RUN_ABANDONED
    assert (run_id, FAILURE_RUN_ABANDONED) in report.reaped


async def test_a_running_run_with_a_result_file_is_recovered(tmp_path):
    run_id = await _abandoned(tmp_path, running=True, result=measured(PASSING_METRICS))
    supervisor, store, _ = build(tmp_path, clock_offset_ms=1000)
    report = await supervisor.start()
    await supervisor.aclose()
    run = store.get_run(run_id)
    assert run.status is RunStatus.PASSED
    assert run_id in report.recovered
    assert dict(run.metrics) == PASSING_METRICS
    assert not (tmp_path / "work" / run_id).exists()


async def test_a_running_run_without_a_result_is_never_left_running(tmp_path):
    run_id = await _abandoned(tmp_path, running=True)
    supervisor, store, _ = build(tmp_path, clock_offset_ms=1000)
    await supervisor.start()
    await supervisor.aclose()
    run = store.get_run(run_id)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_WORKER_LOST
    assert not (tmp_path / "work" / run_id).exists()


async def test_a_run_whose_worker_still_holds_the_lock_is_left_alone(tmp_path):
    run_id = await _abandoned(tmp_path, running=True)
    scratch = tmp_path / "work" / run_id
    with EntryLock(scratch / WORKER_LOCK_NAME, f"run {run_id}", 1.0):
        supervisor, store, _ = build(tmp_path, policy=_with(FAST, adopt_lock_timeout_s=0.1),
                                     clock_offset_ms=1000)
        report = await supervisor.start()
        await supervisor.aclose()
        assert report.active_elsewhere == (run_id,)
        assert store.get_run(run_id).status is RunStatus.RUNNING
        assert scratch.exists()


async def test_orphan_scratch_directories_are_removed(tmp_path):
    stale = tmp_path / "work" / ("tlr-20260101T000000000Z-" + "0" * 16)
    stale.mkdir(parents=True)
    supervisor, _, _ = build(tmp_path)
    report = await supervisor.start()
    await supervisor.aclose()
    assert report.scratch_removed == 1
    assert not stale.exists()


# ------------------------------------------------------------ maintenance

async def test_maintenance_is_skipped_while_a_run_is_active(tmp_path):
    policy = _with(FAST, maintenance=MaintenancePolicy(enabled=True, interval_s=3600))
    supervisor, _, _ = build(tmp_path, policy=policy, launcher=FakeLauncher("hang"))
    async with supervisor:
        run_id = await supervisor.submit(request())
        await until_active(supervisor)
        assert await supervisor.maintain() is None
        await supervisor.cancel(run_id)
        await supervisor.wait(run_id, timeout_s=10)
        assert await supervisor.maintain() is not None


async def test_maintenance_sweeps_leftovers_and_applies_retention(tmp_path):
    retention = TestLabRetentionPolicy(enabled=True, max_runs=1)
    policy = _with(FAST, maintenance=MaintenancePolicy(enabled=True, interval_s=3600, stale_temporary_s=0,
                                                       retention=retention))
    supervisor, store, _ = build(tmp_path, policy=policy)
    async with supervisor:
        first = await run_once(supervisor)
        second = await run_once(supervisor)
        leftover = store.runs_dir / second.run_id / ".artifact-0123456789abcdef.tmp"
        leftover.write_bytes(b"crash leftover")
        report = await supervisor.maintain()
    assert report.swept >= 1
    assert not leftover.exists()
    assert report.retention.deleted == (first.run_id,)
    assert {run.run_id for run in store.list_runs().runs} == {second.run_id}


async def test_retention_never_deletes_a_run_the_caller_names_active(tmp_path):
    """Belt and braces: even from a stale usage snapshot, a named active run leaves the plan."""
    supervisor, store, _ = build(tmp_path)
    async with supervisor:
        first = await run_once(supervisor)
        second = await run_once(supervisor)
    policy = MaintenancePolicy(enabled=True, retention=TestLabRetentionPolicy(enabled=True, max_runs=1))
    report = run_maintenance_pass(store, policy, now=T0 + timedelta(seconds=10),
                                  active_run_ids=(first.run_id,))
    assert report.skipped_active == (first.run_id,)
    assert report.retention.deleted == ()
    assert {run.run_id for run in store.list_runs().runs} == {first.run_id, second.run_id}


# ------------------------------------------------- rework: record integrity (S1)

class ConcludingLauncher(FakeLauncher):
    """A worker whose runner concludes the run itself, behind the supervisor's back."""

    def __init__(self, store: FilesystemTestRunStore) -> None:
        super().__init__("measure")
        self._store = store

    async def launch(self, job, *, environ, cwd):
        stored = self._store.get_run(job.run_id)
        forged = complete_run(stored, at=stored.started_at + timedelta(milliseconds=1),
                              assertion_results=derive_assertion_results(
                                  selftest_spec(), {"selftest.value": 0, "selftest.elapsed_ms": 1}),
                              metrics={"selftest.value": 0, "selftest.elapsed_ms": 1})
        self._store.update_run(forged, expected=stored)
        return await super().launch(job, environ=environ, cwd=cwd)


async def test_a_run_concluded_out_of_band_is_reported_as_an_incident(tmp_path):
    sink = RecordingSink()
    store = FilesystemTestRunStore(tmp_path / "store")
    catalog_root = write_selftest_catalog(tmp_path / "catalog")
    supervisor = RunSupervisor(store=store, work_root=tmp_path / "work", catalog_root=catalog_root, policy=FAST,
                               launcher=ConcludingLauncher(store), diagnostics=sink, clock=_clock(),
                               nonce=_nonce(), code_probe=_code, environment={"os": "windows"})
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.PASSED  # the forged record stands: a terminal record is immutable
    incidents = [(level, data) for kind, level, data in sink.events
                 if kind == "testlab.run.concluded_out_of_band"]
    assert len(incidents) == 1
    level, data = incidents[0]
    assert level == "error"
    assert data["code"] == "run_concluded_out_of_band"
    assert data["correction_refused"] == "testlab_transition_illegal"


def test_a_runner_context_exposes_artifacts_only(tmp_path):
    """The facade is the whole store access a runner gets (S1): no record, no other run."""
    store = FilesystemTestRunStore(tmp_path / "store")
    facade = RunArtifacts(store, "tlr-20260917T120000000Z-" + "0" * 16)
    for name in ("update_run", "delete_run", "create_run", "list_runs", "get_run", "storage_usage"):
        assert not hasattr(facade, name), name
    assert sorted(name for name in vars(type(facade)) if not name.startswith("_")) == [
        "list", "open", "put", "read", "run_id"]


# ------------------------------------------------- rework: maintenance race (S2)

async def test_a_submit_during_an_upkeep_pass_starts_as_soon_as_it_ends(tmp_path):
    """A pass holds the start gate; waiting for it must not count as queue wait (S2)."""
    policy = _with(FAST, max_queue_wait_s=0.3,
                   maintenance=MaintenancePolicy(enabled=True, interval_s=3600, stale_temporary_s=0))
    supervisor, store, _ = build(tmp_path, policy=policy)
    sweeping = asyncio.Event()
    original = store.remove_stale_temporaries

    def slow_sweep(*, older_than_s):
        sweeping.set()
        time.sleep(1.0)  # far longer than max_queue_wait_s
        return original(older_than_s=older_than_s)

    store.remove_stale_temporaries = slow_sweep
    async with supervisor:
        pass_task = asyncio.create_task(supervisor.maintain())
        await _until_set(sweeping)
        started = time.monotonic()
        run = await run_once(supervisor)
        elapsed = time.monotonic() - started
        assert await pass_task is not None
    assert run.status is RunStatus.PASSED, run.failure
    assert elapsed < 5


async def _until_set(event: asyncio.Event) -> None:
    for _ in range(500):
        if event.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the sweep never started")


# ---------------------------------------------------- rework: adoption (S3)

async def test_adoption_clamps_a_terminal_time_that_would_precede_the_start(tmp_path):
    """The adopting supervisor's clock is behind the one that started the run (S3)."""
    run_id = await _abandoned(tmp_path, running=True)
    supervisor, store, _ = build(tmp_path)  # this clock starts at T0+1ms; the run started at T0+100ms
    report = await supervisor.start()
    await supervisor.aclose()
    run = store.get_run(run_id)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_WORKER_LOST
    assert run.finished_at == run.started_at  # clamped up to the floor, never refused
    assert report.reaped == ((run_id, FAILURE_WORKER_LOST),)
    assert report.failed == ()


async def test_adoption_reports_a_run_it_could_not_make_terminal(tmp_path):
    run_id = await _abandoned(tmp_path, running=True)
    supervisor, store, _ = build(tmp_path, clock_offset_ms=1000)

    def refusing_update(updated, *, expected):
        raise TestLabStoreError("testlab_store_io", "disk on fire")

    store.update_run = refusing_update
    report = await supervisor.start()
    await supervisor.aclose()
    assert report.reaped == ()
    assert report.failed == ((run_id, "testlab_store_io"),)
    assert store.get_run(run_id).status is RunStatus.RUNNING


# ------------------------------------------- rework: link in the scratch (S4)

@pytest.mark.skipif(os.name != "nt", reason="a junction is a Windows link type")
async def test_a_junction_planted_in_the_scratch_is_replaced_not_followed(tmp_path):
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    fixed = T0 + timedelta(milliseconds=1)
    run_id = format_run_id(fixed, "0" * 16)
    scratch = tmp_path / "work" / run_id
    scratch.mkdir(parents=True)
    _winapi.CreateJunction(str(outside), str(scratch / RUNTIME_DIR_NAME))
    assert (scratch / RUNTIME_DIR_NAME).is_junction()
    settings = tmp_path / SETTINGS_FILE_NAME
    settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    supervisor, _, launcher = build(tmp_path, settings_path=settings, launcher=FakeLauncher("hang"),
                                    policy=_with(FAST, keep_scratch=True))
    supervisor._clock = lambda: fixed
    supervisor._nonce = lambda: "0" * 16
    async with supervisor:
        submitted = await supervisor.submit(request())
        assert submitted == run_id
        await until_launched(launcher)
        assert list(outside.iterdir()) == []  # nothing was written through the junction
        assert (scratch / RUNTIME_DIR_NAME / SETTINGS_FILE_NAME).is_file()
        assert not (scratch / RUNTIME_DIR_NAME).is_junction()
        await supervisor.cancel(submitted)
        await supervisor.wait(submitted, timeout_s=10)


# ----------------------------------- rework: a measurement is never lost (6)

async def test_a_measurement_written_before_a_heartbeat_lapse_is_kept(tmp_path):
    supervisor, _, launcher = build(tmp_path, launcher=FakeLauncher("measure_then_frozen"))
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.PASSED, run.failure
    assert dict(run.metrics) == PASSING_METRICS
    assert launcher.workers[0].killed  # the liveness fault still ended the process


async def test_a_timed_out_run_keeps_its_measurements_but_stays_timed_out(tmp_path):
    supervisor, _, _ = build(tmp_path, launcher=FakeLauncher("measure_then_hang"), max_duration_s=0.2)
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.TIMED_OUT
    assert run.failure.code == FAILURE_RUN_TIMEOUT
    assert dict(run.metrics) == PASSING_METRICS
    assert run.assertion_results == ()  # a verdict belongs to a run that finished
    # Slice 07: no score either. A synthesis over partial evidence would be comparable
    # with a complete one, which it is not (docs/testlab.md, "Scoring").
    assert run.score is None


async def test_partial_measurements_the_declaration_refuses_are_dropped(tmp_path):
    sink = RecordingSink()
    supervisor, _, _ = build(tmp_path, sink=sink, max_duration_s=0.2,
                             launcher=FakeLauncher("measure_then_hang", measured({"selftest.unknown": 1})))
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.TIMED_OUT
    assert dict(run.metrics) == {}
    assert "testlab.run.partial_metrics_dropped" in sink.kinds()


# ------------------------------- rework: a corrupt result is not a crash (7)

async def test_a_corrupt_result_file_is_reported_as_an_invalid_result(tmp_path):
    supervisor, _, _ = build(tmp_path, launcher=FakeLauncher("corrupt_result"))
    async with supervisor:
        run = await run_once(supervisor)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_RESULT_INVALID
    assert "invalid" in run.failure.detail


def test_an_exit_description_is_english_and_keeps_the_decoder_facts():
    assert _exit_label(None) == "no exit code"
    assert _exit_label(3) == "exit code 3"
    crash = _exit_label(-1073741819)
    assert "0xC0000005" in crash and "native crash" in crash
    assert all(word not in crash.lower() for word in ("sortie", "crash natif"))


# --------------------------- rework: one supervisor per work root (8)

async def test_a_second_supervisor_refuses_the_same_work_root(tmp_path):
    first, store, _ = build(tmp_path)
    second, _, _ = build(tmp_path, clock_offset_ms=5000)
    await first.start()
    try:
        with pytest.raises(SupervisorError, match="work root"):
            await second.start()
    finally:
        await first.aclose()
    await second.start()  # the lock goes with the supervisor that held it
    await second.aclose()


def test_no_attribute_of_a_run_context_reaches_the_record(tmp_path):
    """Walk the context and the facade: no attribute is an object that can write a record (S1)."""
    store = FilesystemTestRunStore(tmp_path / "store")
    facade = RunArtifacts(store, "tlr-20260917T120000000Z-" + "0" * 16)
    context = RunContext(run_id=facade.run_id, diagnostic=selftest_spec(), profile=ProfileName.VIRTUAL,
                         parameters={}, overrides={}, scenario=None, runtime_dir=tmp_path,
                         data_root=tmp_path, artifacts=facade, cancelled=asyncio.Event(), deadline=0.0,
                         log=lambda message: None)
    seen = []
    for holder in (context, facade):
        names = getattr(holder, "__slots__", None) or vars(holder)
        for name in names:
            value = getattr(holder, name, None)
            seen.append(name)
            assert not hasattr(value, "update_run"), f"{name} reaches update_run"
            assert not hasattr(value, "delete_run"), f"{name} reaches delete_run"
    assert "artifacts" in seen and "_put" in seen  # the walk really visited both objects
    assert not hasattr(facade, "_store")
