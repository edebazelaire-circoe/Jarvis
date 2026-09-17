"""Slice 06 end to end: the four seed diagnostics through a real supervisor and real workers.

Bounded on purpose (this host has little free RAM): `max_concurrent_runs=1`, one worker
process per test, and every run is parameterised down to the smallest shape that still
exercises its measurement. The failure paths, which would cost one process each, are
proven in `tests/integration/test_testlab_virtual_runners.py` instead.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.jobs import FAILURE_CANCELLED, FAILURE_RUN_TIMEOUT, WORKER_LOG_ARTIFACT
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import CodeIdentity, RunStatus
from jarvis.testlab.supervisor import RunRequest, RunSupervisor, SupervisorPolicy

T0 = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
#: Real interpreter startup plus the catalog load and the voice stack import.
STARTUP_TIMEOUT_S = 60.0
WAIT_S = 180


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
    return CodeIdentity("6" * 40, False)


def build(tmp_path: Path, *, max_run_duration_s: float | None = None, cancel_grace_s: float = 5.0):
    """A supervisor on the SHIPPED catalog with the real subprocess launcher."""
    store = FilesystemTestRunStore(tmp_path / "store")
    policy = SupervisorPolicy(max_concurrent_runs=1, startup_timeout_s=STARTUP_TIMEOUT_S, heartbeat_timeout_s=60.0,
                              cancel_grace_s=cancel_grace_s, poll_interval_s=0.05,
                              max_run_duration_s=max_run_duration_s, maintenance=MaintenancePolicy(enabled=False))
    supervisor = RunSupervisor(store=store, work_root=tmp_path / "work", policy=policy, clock=_clock(),
                               nonce=_nonce(), code_probe=_code,
                               environment={"os": "windows", "python_version": "3.14.6"})
    return supervisor, store


async def run_seed(tmp_path: Path, diagnostic_id: str, **parameters):
    """Submit one seed run and wait for its terminal record. Exactly one worker process."""
    supervisor, store = build(tmp_path)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(RunRequest(diagnostic_id=diagnostic_id, profile=ProfileName.VIRTUAL,
                                                    parameters=parameters))
        run = await supervisor.wait(run_id, timeout_s=WAIT_S)
    finally:
        await supervisor.aclose()
    return run, store


def _paths(run) -> set[str]:
    return {ref.path for ref in run.artifacts}


async def test_voice_self_echo_passes_in_a_real_worker(tmp_path):
    run, store = await run_seed(tmp_path, "voice.self_echo", **{"output.duration_ms": 1000,
                                                                "echo.candidate_count": 2})
    assert run.status is RunStatus.PASSED, run.failure
    metrics = dict(run.metrics)
    assert metrics["barge_in.false_confirmed_count"] == 0
    assert metrics["barge_in.rejected_count"] == 2
    assert metrics["output.completed"] is True
    assert metrics["output.played_ms"] >= 1000
    assert set(metrics) == {"barge_in.false_confirmed_count", "barge_in.rejected_count", "output.completed",
                            "output.played_ms"}
    assert {"trace.jsonl", WORKER_LOG_ARTIFACT} <= _paths(run)
    assert {result.assertion_id: result.outcome.value for result in run.assertion_results} == {
        "no_false_barge_in": "passed", "output_completes": "passed"}
    # The stored journal is the live runtime's, session shape included.
    trace = store.read_artifact(run.run_id, "trace.jsonl").decode("utf-8")
    assert '"voice.start"' in trace and '"voice.connecting"' in trace and '"voice.stop"' in trace
    assert f"{run.run_id}-s1" in trace


async def test_speech_payload_integrity_passes_in_a_real_worker(tmp_path):
    run, _store = await run_seed(tmp_path, "speech.payload_integrity", **{"speech.request_count": 2})
    assert run.status is RunStatus.PASSED, run.failure
    assert dict(run.metrics) == {"speech.scripted_count": 2, "speech.delivered_count": 2,
                                 "speech.payload_mismatch_count": 0, "speech.replayed_payload_count": 0,
                                 "speech.undelivered_count": 0}


async def test_speech_stale_supersession_replays_its_shipped_scenario_in_a_real_worker(tmp_path):
    run, _store = await run_seed(tmp_path, "speech.stale_supersession")
    assert run.status is RunStatus.PASSED, run.failure
    assert dict(run.metrics) == {"speech.superseded_count": 1, "speech.stale_delivered_count": 0,
                                 "speech.latest_intent_delivered": True, "speech.stale_wait_ms": 28000}
    assert run.scenario_id == "stale_ack_35_9s"


async def test_voice_queue_latency_passes_in_a_real_worker(tmp_path):
    run, _store = await run_seed(tmp_path, "voice.queue_latency", **{"speech.request_count": 1,
                                                                     "brain.result_delay_ms": 200})
    assert run.status is RunStatus.PASSED, run.failure
    metrics = dict(run.metrics)
    assert set(metrics) == {"speech.queue_free_to_started_ms", "speech.started_to_first_audio_ms",
                            "user_turn.end_to_first_audio_ms", "speech.delivered_count"}
    assert metrics["speech.delivered_count"] == 1
    assert metrics["user_turn.end_to_first_audio_ms"] >= 200  # the scripted brain's thinking time


async def test_a_cancelled_virtual_run_stops_cooperatively(tmp_path):
    """A cancel ends the run well before the forced kill: no tree kill in the failure detail."""
    supervisor, store = build(tmp_path, cancel_grace_s=30.0)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(RunRequest(
            diagnostic_id="voice.self_echo", profile=ProfileName.VIRTUAL,
            parameters={"output.duration_ms": 120000, "echo.candidate_count": 0}))
        await _until_running(supervisor, run_id)
        assert await supervisor.cancel(run_id) is True
        run = await supervisor.wait(run_id, timeout_s=WAIT_S)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.CANCELLED
    assert run.failure.code == FAILURE_CANCELLED
    assert "killed its process tree" not in run.failure.detail


async def test_a_virtual_run_over_its_budget_is_timed_out(tmp_path):
    """The operator cap bounds the run; the worker stops itself on it, cooperatively."""
    supervisor, store = build(tmp_path, max_run_duration_s=8.0, cancel_grace_s=30.0)
    await supervisor.start()
    try:
        run_id = await supervisor.submit(RunRequest(
            diagnostic_id="voice.self_echo", profile=ProfileName.VIRTUAL,
            parameters={"output.duration_ms": 120000, "echo.candidate_count": 0}))
        run = await supervisor.wait(run_id, timeout_s=WAIT_S)
    finally:
        await supervisor.aclose()
    assert run.status is RunStatus.TIMED_OUT
    assert run.failure.code == FAILURE_RUN_TIMEOUT
    assert "killed its process tree" not in run.failure.detail


async def _until_running(supervisor: RunSupervisor, run_id: str) -> None:
    """Wait for the worker to be measuring, not merely spawned."""
    for _ in range(int(STARTUP_TIMEOUT_S * 20)):
        run = await supervisor.status(run_id)
        if run.status is RunStatus.RUNNING:
            return
        if run.status is not RunStatus.QUEUED:
            raise AssertionError(f"the run left the queue as {run.status.value}: {run.failure}")
        await asyncio.sleep(0.05)
    raise AssertionError("the run never started")
