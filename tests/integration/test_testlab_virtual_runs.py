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
    """No version means the latest, which is v2 since the expectation metrics were published.

    The shipped scenario carries no `expect.*` step, so both expectation measurements are
    0 and the situation's own four measurements are unchanged from v1.
    """
    run, _store = await run_seed(tmp_path, "speech.stale_supersession")
    assert run.status is RunStatus.PASSED, run.failure
    assert run.diagnostic_version == 2
    assert dict(run.metrics) == {"speech.superseded_count": 1, "speech.stale_delivered_count": 0,
                                 "speech.latest_intent_delivered": True, "speech.stale_wait_ms": 28000,
                                 "scenario.expectations_declared": 0, "scenario.expectations_failed_count": 0}
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


# ------------------------------- the published v2 of speech.stale_supersession

#: A Conversation Event type a run really records, so `count_min=99` is unmet on evidence
#: that exists rather than on a type nothing ever emits.
RECORDED_EVENT = "user.transcript.accepted"


def _scenario_with_unmet_expectation():
    """The shipped stale-supersession scenario plus one `expect.event` nothing can satisfy."""
    from jarvis.testlab.catalog import load_catalog
    from jarvis.testlab.scenarios import Scenario, ScenarioStep
    from jarvis.testlab.selftest import catalog_implementations

    shipped = load_catalog(implementations=catalog_implementations()).describe(
        "speech.stale_supersession").manifest.scenario
    return Scenario("stale_ack_35_9s_with_expectation",
                    title="The shipped stale situation, with an event expectation",
                    description="The converted incident scenario plus an expectation the run cannot meet.",
                    steps=(*shipped.steps,
                           ScenarioStep("expect.event", {"at_ms": 36000, "event": RECORDED_EVENT,
                                                         "count_min": 99})),
                    provenance=shipped.provenance)


async def test_the_published_v2_turns_an_unmet_expectation_into_a_verdict_and_v1_cannot(tmp_path):
    """End to end proof of the Slice 04 promotion path, through real workers.

    Two runs of the SAME scenario on the SAME implementation, differing only by the
    declaration they are judged against:

    - no explicit version resolves to the latest, v2, which declares
      `scenario.expectations_failed_count` and a blocking assertion on it, so the unmet
      expectation is a measured 1 and the run is `failed` — a product verdict;
    - pinned to v1, which declares neither, the same unmet expectation cannot be
      expressed, so the run is `errored` / `scenario_expectation_unmet`, read as
      `inconclusive` — "could not measure", by design.

    Nothing else in the suite proves a published version bump actually changes what a
    run can conclude.
    """
    from jarvis.testlab.outcomes import RunOutcomeClass, classify_run

    scenario = _scenario_with_unmet_expectation()
    supervisor, _store = build(tmp_path)
    await supervisor.start()
    try:
        latest_id = await supervisor.submit(RunRequest(diagnostic_id="speech.stale_supersession",
                                                       profile=ProfileName.VIRTUAL, scenario=scenario))
        latest = await supervisor.wait(latest_id, timeout_s=WAIT_S)
        pinned_id = await supervisor.submit(RunRequest(diagnostic_id="speech.stale_supersession",
                                                       profile=ProfileName.VIRTUAL, version=1, scenario=scenario))
        pinned = await supervisor.wait(pinned_id, timeout_s=WAIT_S)
    finally:
        await supervisor.aclose()

    # A request without a version targets the latest published declaration.
    assert latest.diagnostic_version == 2
    assert latest.status is RunStatus.FAILED, latest.failure
    assert classify_run(latest).outcome is RunOutcomeClass.FAILED
    assert dict(latest.metrics)["scenario.expectations_failed_count"] == 1
    assert dict(latest.metrics)["scenario.expectations_declared"] == 1
    outcomes = {result.assertion_id: result.outcome.value for result in latest.assertion_results}
    assert outcomes["scenario_expectations_met"] == "failed"
    # v2 keeps every v1 measurement, and the situation itself still behaved.
    assert outcomes["no_stale_delivery"] == "passed" and outcomes["latest_intent_wins"] == "passed"
    assert dict(latest.metrics)["speech.stale_wait_ms"] == 28000

    # The same scenario judged by v1 cannot express the expectation: inconclusive, not failed.
    assert pinned.diagnostic_version == 1
    assert pinned.status is RunStatus.ERRORED
    assert pinned.failure.code == "scenario_expectation_unmet"
    assert classify_run(pinned).outcome is RunOutcomeClass.INCONCLUSIVE
    assert "expect.event" in pinned.failure.detail
