"""Slice 05 with real worker processes: isolation, crash, timeout, cancel, tree kill.

Bounded on purpose (this host has little free RAM): every test starts ONE worker
process, except the tree-kill test which also starts one grandchild. Timeouts are
seconds, not minutes, and every supervisor is closed in a `finally`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from jarvis.testlab.capture import identity_fragments
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.jobs import (
    FAILURE_CANCELLED,
    FAILURE_RESULT_CONTRADICTS_SPEC,
    FAILURE_RUNNER_FAILED,
    FAILURE_RUNNER_UNAVAILABLE,
    FAILURE_RUN_TIMEOUT,
    FAILURE_WORKER_CRASHED,
    STDERR_LOG_ARTIFACT,
    WORKER_LOG_ARTIFACT,
)
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.redaction import REDACTED
from jarvis.testlab.runs import CodeIdentity, RunStatus
from jarvis.testlab.selftest import (
    CHILD_PID_FILE,
    FIXTURE_CREDENTIAL,
    SELFTEST_DIAGNOSTIC_ID,
    SelfTestMode,
    write_selftest_catalog,
)
from jarvis.testlab.supervisor import SETTINGS_FILE_NAME, RunRequest, RunSupervisor, SupervisorPolicy

T0 = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
#: Real interpreter startup plus the catalog load. Generous, still seconds.
STARTUP_TIMEOUT_S = 45.0


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
    return CodeIdentity("5" * 40, False)


def build(tmp_path: Path, *, max_duration_s: float = 30.0, cancel_grace_s: float = 3.0,
          keep_scratch: bool = False, catalog_root: Path | None = None, settings_path: Path | None = None):
    """A supervisor with the real subprocess launcher and the fixture catalog."""
    root = catalog_root if catalog_root is not None else write_selftest_catalog(
        tmp_path / "catalog", max_duration_s=max_duration_s)
    store = FilesystemTestRunStore(tmp_path / "store")
    policy = SupervisorPolicy(max_concurrent_runs=1, startup_timeout_s=STARTUP_TIMEOUT_S,
                              heartbeat_timeout_s=30.0, cancel_grace_s=cancel_grace_s, poll_interval_s=0.05,
                              keep_scratch=keep_scratch, maintenance=MaintenancePolicy(enabled=False))
    supervisor = RunSupervisor(store=store, work_root=tmp_path / "work", catalog_root=root, policy=policy,
                               settings_path=settings_path, clock=_clock(), nonce=_nonce(), code_probe=_code,
                               environment={"os": "windows", "python_version": "3.14.6"})
    return supervisor, store


def request(mode: SelfTestMode | str = SelfTestMode.MEASURE, **parameters) -> RunRequest:
    return RunRequest(diagnostic_id=SELFTEST_DIAGNOSTIC_ID, profile=ProfileName.VIRTUAL,
                      parameters={"mode": SelfTestMode(mode).value, **parameters})


def artifact_text(store: FilesystemTestRunStore, run_id: str, path: str) -> str:
    return store.read_artifact(run_id, path).decode("utf-8")


async def test_a_real_worker_runs_to_a_passed_run(tmp_path):
    """One process: queue -> running -> passed, with its log and report stored."""
    supervisor, store = build(tmp_path)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(request())
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.PASSED, run.failure
    assert dict(run.metrics)["selftest.value"] == 0
    paths = [ref.path for ref in run.artifacts]
    assert {"config_snapshot.json", WORKER_LOG_ARTIFACT, "selftest-report.json"} <= set(paths)
    log = artifact_text(store, run_id, WORKER_LOG_ARTIFACT)
    assert "selftest done" in log
    # The roots the runner received are inside the run scratch, never the live runtime,
    # and the stored log carries no user name, host name or home path.
    assert str(Path("work") / run_id / "runtime") in log
    assert not [fragment for fragment in identity_fragments() if fragment in log]
    assert not (tmp_path / "work" / run_id).exists()  # the scratch is removed with the run


async def test_a_real_worker_that_dies_without_a_result_still_ends_terminal(tmp_path):
    """One process, killed from inside with a hard exit: no result file, no orphan run."""
    supervisor, store = build(tmp_path)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(request(SelfTestMode.CRASH))
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_WORKER_CRASHED
    assert "3" in run.failure.detail
    assert run.finished_at is not None


async def test_a_real_worker_that_raises_reports_a_runner_failure_with_its_stderr(tmp_path):
    supervisor, store = build(tmp_path)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(request(SelfTestMode.ERROR))
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_RUNNER_FAILED
    assert STDERR_LOG_ARTIFACT in [ref.path for ref in run.artifacts]
    stderr, log = (artifact_text(store, run_id, path) for path in (STDERR_LOG_ARTIFACT, WORKER_LOG_ARTIFACT))
    assert "RuntimeError" in stderr
    # The runner printed a credential to both channels; neither stored artifact carries it.
    for text in (stderr, log):
        assert "credential probe" in text
        assert "BEARERTOKEN" not in text
        assert FIXTURE_CREDENTIAL not in text
        assert REDACTED in text


async def test_a_real_run_over_its_declared_budget_is_timed_out(tmp_path):
    """The declared `max_duration_s` is the bound; the worker stops itself on it."""
    supervisor, store = build(tmp_path, max_duration_s=2.0)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(request(SelfTestMode.SLEEP, sleep_ms=60000))
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.TIMED_OUT
    assert run.failure.code == FAILURE_RUN_TIMEOUT


async def test_a_real_run_stops_cooperatively_when_cancelled(tmp_path):
    supervisor, store = build(tmp_path)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(request(SelfTestMode.SLEEP, sleep_ms=60000))
        await _until_started(supervisor, run_id)
        assert await supervisor.cancel(run_id) is True
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.CANCELLED
    assert run.failure.code == FAILURE_CANCELLED
    assert "killed its process tree" not in run.failure.detail


async def test_a_real_worker_that_ignores_the_stop_is_killed_with_its_children(tmp_path):
    """Two processes: the worker and one grandchild it started. Neither survives the kill."""
    supervisor, store = build(tmp_path, cancel_grace_s=1.0, keep_scratch=True)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(request(SelfTestMode.SPAWN_CHILD, sleep_ms=60000))
        child_pid = await _child_pid(tmp_path / "work" / run_id)
        assert _alive(child_pid)
        await supervisor.cancel(run_id)
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.CANCELLED
    assert "killed its process tree" in run.failure.detail
    for _ in range(50):
        if not _alive(child_pid):
            break
        await asyncio.sleep(0.1)
    assert not _alive(child_pid), "the grandchild outlived the run"


async def test_a_real_result_contradicting_the_declaration_is_refused(tmp_path):
    supervisor, store = build(tmp_path)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(request(SelfTestMode.UNDECLARED_METRIC))
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_RESULT_CONTRADICTS_SPEC
    assert dict(run.metrics) == {}


async def test_a_reserved_runner_of_the_official_catalog_fails_the_run_structurally(tmp_path):
    """The real catalog, whose seed runners are reserved until Slice 06."""
    supervisor, store = _official(tmp_path)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(RunRequest(diagnostic_id="voice.self_echo", profile=ProfileName.VIRTUAL))
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_RUNNER_UNAVAILABLE
    assert "runner_not_registered" in run.failure.detail


def _official(tmp_path: Path):
    """A supervisor on the shipped catalog (no fixture manifest), in a private store."""
    store = FilesystemTestRunStore(tmp_path / "official-store")
    policy = SupervisorPolicy(max_concurrent_runs=1, startup_timeout_s=STARTUP_TIMEOUT_S, heartbeat_timeout_s=30.0,
                              cancel_grace_s=3.0, poll_interval_s=0.05, maintenance=MaintenancePolicy(enabled=False))
    supervisor = RunSupervisor(store=store, work_root=tmp_path / "official-work", policy=policy,
                               clock=_clock(), nonce=_nonce(), code_probe=_code,
                               environment={"os": "windows", "python_version": "3.14.6"})
    return supervisor, store


async def test_a_real_runner_cannot_write_its_own_verdict_or_reach_another_run(tmp_path):
    """The runner gets an artifact-only facade: it measures, the supervisor judges (S1)."""
    supervisor, store = build(tmp_path)
    await supervisor.start()
    try:
        first = await supervisor.wait(await supervisor.submit(request()), timeout_s=90)
        run_id = await supervisor.submit(request(SelfTestMode.FORGE))
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert first.status is RunStatus.PASSED, first.failure
    assert run.status is RunStatus.FAILED, run.failure  # the real measurement, not the forged one
    assert dict(run.metrics)["selftest.value"] == 500
    log = artifact_text(store, run_id, WORKER_LOG_ARTIFACT)
    assert "record methods reachable from the context: none" in log
    assert "exposes a store attribute: False" in log
    assert store.get_run(first.run_id).status is RunStatus.PASSED  # the other run was untouchable


async def test_a_real_run_copies_the_settings_and_never_writes_the_permanent_one(tmp_path):
    settings = tmp_path / SETTINGS_FILE_NAME
    settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    before = settings.read_bytes()
    supervisor, store = build(tmp_path, keep_scratch=True, settings_path=settings)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(request())
        run = await supervisor.wait(run_id, timeout_s=90)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.PASSED, run.failure
    assert settings.read_bytes() == before
    copy = tmp_path / "work" / run_id / "runtime" / SETTINGS_FILE_NAME
    assert json.loads(copy.read_text(encoding="utf-8")) == {"theme": "dark"}
    assert copy != settings


# ----------------------------------------------------------------- helpers

async def _until_started(supervisor: RunSupervisor, run_id: str) -> None:
    for _ in range(int(STARTUP_TIMEOUT_S * 10)):
        run = await supervisor.status(run_id)
        if run.status is not RunStatus.QUEUED:
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the run never started")


async def _child_pid(scratch: Path) -> int:
    path = scratch / CHILD_PID_FILE
    for _ in range(int(STARTUP_TIMEOUT_S * 10)):
        if path.exists():
            return int(path.read_text(encoding="utf-8"))
        await asyncio.sleep(0.1)
    raise AssertionError("the worker never spawned its child")


def _alive(pid: int) -> bool:
    import os

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE
