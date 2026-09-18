"""Device contention (READINESS B9), the audio-artifact opt-in and the live opt-in gate.

Nothing here opens a device or calls a provider: the detector reads files, and the
supervisor gates are exercised with a fake launcher. The whole point of the Slice is
that these refusals happen BEFORE anything is opened, so a test that had to open
something would be testing the wrong thing.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from jarvis.runtime.control_center import VOICE_HEARTBEAT_MAX_AGE_S
from jarvis.testlab.catalog import Catalog
from jarvis.testlab.devices import (
    HEARTBEAT_MAX_AGE_S,
    VOICE_HEARTBEAT_FILE,
    VOICE_RUNTIME_FILE,
    VOICE_STATE_FILE,
    ContentionEvidence,
    ContentionState,
    DeviceContentionDetector,
    DeviceLease,
    DeviceLeaseBusy,
    LiveVoiceRuntimeProbe,
    default_contention_detector,
    needs_device,
)
from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
    ParameterSpec,
    ParameterType,
)
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.jobs import (
    FAILURE_DEVICE_CONTENTION,
    FAILURE_DEVICE_CONTENTION_DURING_RUN,
    FAILURE_LIVE_OPT_IN_MISSING,
)
from jarvis.testlab.manifests import CatalogLock, DiagnosticManifest, lock_entry_for
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES
from jarvis.testlab.outcomes import RunOutcomeClass, classify_run
from jarvis.testlab.profiles import Capability, CostBounds, ProfileName, ProfileSpec, ResourceGrant
from jarvis.testlab.runs import RunStatus
from jarvis.testlab.store import ArtifactWriteLimits
from jarvis.testlab.supervisor import RunRequest, RunSupervisor, SupervisorPolicy
from tests.unit.test_testlab_supervisor import FakeLauncher, _clock, _code, _nonce

pytestmark = pytest.mark.asyncio

LIVE_ENVIRON = {"JARVIS_TESTLAB_LIVE": "1", "OPENAI_API_KEY": "test-key"}
NOW = 1_800_000_000.0


# ------------------------------------------------------------- the detector

def _runtime(tmp_path: Path, *, heartbeat: object = None, state: str | None = None,
             runtime: dict | None = None) -> Path:
    root = tmp_path / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    if heartbeat is not None:
        (root / VOICE_HEARTBEAT_FILE).write_text(f"{heartbeat}\n", encoding="utf-8")
    if state is not None:
        (root / VOICE_STATE_FILE).write_text(f"{state}\n", encoding="utf-8")
    if runtime is not None:
        (root / VOICE_RUNTIME_FILE).write_text(json.dumps(runtime), encoding="utf-8")
    return root


def _probe(root: Path, *, now: float = NOW) -> ContentionEvidence:
    return LiveVoiceRuntimeProbe(root, clock=lambda: now).probe()


async def test_the_liveness_window_is_the_one_the_control_center_already_uses():
    """Duplicated, not imported (the Test Lab may not import aiohttp), so it is pinned."""
    assert HEARTBEAT_MAX_AGE_S == VOICE_HEARTBEAT_MAX_AGE_S


async def test_a_runtime_directory_with_no_heartbeat_reads_free(tmp_path):
    evidence = _probe(_runtime(tmp_path))
    assert evidence.state is ContentionState.FREE
    assert "ever been written" in evidence.detail


async def test_a_fresh_heartbeat_reads_busy_and_names_the_architecture(tmp_path):
    root = _runtime(tmp_path, heartbeat=NOW - 1.0,
                    runtime={"architecture": "continuous_brain", "runtime_state": "active", "ts": NOW})
    evidence = _probe(root)
    assert evidence.state is ContentionState.BUSY
    assert "continuous_brain" in evidence.detail and "active" in evidence.detail


async def test_a_stale_heartbeat_reads_free_and_says_how_stale(tmp_path):
    evidence = _probe(_runtime(tmp_path, heartbeat=NOW - 3600, state="idle"))
    assert evidence.state is ContentionState.FREE
    assert "3600" in evidence.detail


async def test_a_stale_heartbeat_with_a_recent_non_idle_state_still_reads_busy(tmp_path):
    """A crash mid-sentence leaves `speaking` behind; treating that as free would steal the device."""
    root = _runtime(tmp_path, state="speaking")
    # The clock is the state file's own mtime plus five seconds, so the state is fresh;
    # the heartbeat is written an hour behind THAT clock, which is what a crash leaves.
    now = (root / VOICE_STATE_FILE).stat().st_mtime + 5
    (root / VOICE_HEARTBEAT_FILE).write_text(f"{now - 3600}\n", encoding="utf-8")
    evidence = _probe(root, now=now)
    assert evidence.state is ContentionState.BUSY
    assert "speaking" in evidence.detail


async def test_a_garbled_heartbeat_reads_unknown_not_free(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    (root / VOICE_HEARTBEAT_FILE).write_text("not-a-timestamp", encoding="utf-8")
    evidence = _probe(root)
    assert evidence.state is ContentionState.UNKNOWN


async def test_the_detector_is_fail_closed(tmp_path):
    """One busy decides; one unknown is enough to refuse; only unanimous free frees."""
    def probe(state: ContentionState):
        class Probe:
            source = f"p_{state.value}"

            def probe(self):
                return ContentionEvidence(self.source, state, f"stated {state.value}")
        return Probe()

    free, busy, unknown = probe(ContentionState.FREE), probe(ContentionState.BUSY), probe(ContentionState.UNKNOWN)
    assert DeviceContentionDetector((free, free)).detect().state is ContentionState.FREE
    assert DeviceContentionDetector((free, unknown)).detect().state is ContentionState.UNKNOWN
    assert DeviceContentionDetector((free, unknown, busy)).detect().state is ContentionState.BUSY
    assert not DeviceContentionDetector((free, unknown)).detect().available


async def test_a_probe_that_raises_makes_the_detector_more_careful_never_less():
    class Broken:
        source = "broken"

        def probe(self):
            raise RuntimeError("no")

    report = DeviceContentionDetector((Broken(),)).detect()
    assert report.state is ContentionState.UNKNOWN and not report.available
    assert "raised" in report.evidence[0].detail and "RuntimeError" in report.evidence[0].detail


async def test_the_report_reason_is_one_actionable_line(tmp_path):
    report = default_contention_detector(_runtime(tmp_path, heartbeat=NOW)).detect()
    assert report.state is ContentionState.BUSY
    assert report.holder and report.holder in report.reason()
    assert report.to_dict()["state"] == "busy"


async def test_needs_device_covers_exactly_the_two_device_capabilities():
    assert needs_device({Capability.AUDIO_INPUT_DEVICE})
    assert needs_device({Capability.AUDIO_OUTPUT_DEVICE})
    assert not needs_device({Capability.REALTIME_PROVIDER, Capability.HUMAN_PRESENCE})
    assert not needs_device(())


# ---------------------------------------------------------------- the lease

async def test_the_device_lease_excludes_a_second_holder(tmp_path):
    path = tmp_path / ".device.lock"
    first, second = DeviceLease(path), DeviceLease(path)
    first.acquire()
    try:
        assert first.held
        with pytest.raises(DeviceLeaseBusy):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
    assert not second.held


async def test_releasing_an_unheld_lease_is_harmless(tmp_path):
    lease = DeviceLease(tmp_path / ".device.lock")
    lease.release()
    assert not lease.held


# ------------------------------------------------------- the supervisor gates

def _device_spec(profile: ProfileName, requires: frozenset[Capability], *, cost_usd: float = 0.0) -> DiagnosticSpec:
    return DiagnosticSpec(
        diagnostic_id="voice.device_probe", version=1, title="Device probe fixture", domain="voice",
        profiles={profile: ProfileSpec(profile, f"testlab.scenario.{_impl(profile)}",
                                       CostBounds(60, cost_usd), requires)},
        parameters=(ParameterSpec("count", ParameterType.INT, default=1, minimum=0, maximum=4),),
        metrics=(MetricSpec("probe.count", MetricUnit.COUNT, MetricDirection.NEUTRAL),),
        assertions=(AssertionSpec("counted", "probe.count", Comparator.GE, 0, blocking=True),))


def _impl(profile: ProfileName) -> str:
    return {ProfileName.AUDIO: "audio", ProfileName.LIVE: "live",
            ProfileName.HARDWARE_AUTO: "hardware_auto", ProfileName.HARDWARE_GUIDED: "hardware_guided"}[profile]


def _catalog(spec: DiagnosticSpec) -> Catalog:
    from jarvis.testlab.selftest import catalog_implementations

    manifest = DiagnosticManifest(spec)
    return Catalog.build([(manifest.relative_path, manifest)], CatalogLock((lock_entry_for(manifest),)),
                         primitives=DEFAULT_PRIMITIVES, implementations=catalog_implementations())


async def until_finished(supervisor: RunSupervisor, run_id: str):
    return await supervisor.wait(run_id, timeout_s=30)


def jobs_of(launcher: FakeLauncher) -> list:
    return [worker.job for worker in launcher.workers]


def _supervisor(tmp_path: Path, spec: DiagnosticSpec, *, detector=None, base_environ=None,
                allow_audio: bool = False, lease: Path | None | object = ..., behaviour: str = "measure"):
    store = FilesystemTestRunStore(tmp_path / "store", limits=ArtifactWriteLimits(allow_audio=allow_audio))
    launcher = FakeLauncher(behaviour)
    supervisor = RunSupervisor(
        store=store, work_root=tmp_path / "work", catalog=_catalog(spec),
        catalog_root=tmp_path / "catalog", policy=SupervisorPolicy(poll_interval_s=0.02, startup_timeout_s=5,
                                                                   heartbeat_timeout_s=5, cancel_grace_s=1,
                                                                   max_queue_wait_s=5),
        launcher=launcher, settings_path=None, diagnostics=None, clock=_clock(0), nonce=_nonce(),
        code_probe=_code, environment={"os": "windows", "python_version": "3.14.6"},
        base_environ=base_environ, contention=detector, device_lease_path=lease)
    return supervisor, store, launcher


class _Detector:
    """A detector double whose answer a test flips mid-run."""

    def __init__(self, state: ContentionState = ContentionState.FREE) -> None:
        self.state = state
        self.calls = 0

    def detect(self):
        from jarvis.testlab.devices import ContentionReport

        self.calls += 1
        evidence = ContentionEvidence("double", self.state, f"the double states {self.state.value}")
        holder = "the Jarvis voice runtime" if self.state is ContentionState.BUSY else None
        return ContentionReport(self.state, holder, (evidence,))


AUDIO_DEVICE = frozenset({Capability.AUDIO_INPUT_DEVICE, Capability.AUDIO_OUTPUT_DEVICE})
DEVICE_GRANT = ResourceGrant(AUDIO_DEVICE, max_cost_usd=0)


async def test_a_held_device_is_refused_before_any_worker_is_spawned(tmp_path):
    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=_Detector(ContentionState.BUSY))
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
        run = await until_finished(supervisor, run_id)
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_DEVICE_CONTENTION
    assert "held" in run.failure.detail and "Jarvis voice runtime" in run.failure.detail
    assert classify_run(run).outcome is RunOutcomeClass.REFUSED
    assert jobs_of(launcher) == [], "no worker may be spawned for a refused device run"
    assert supervisor.reserved_capabilities == frozenset(), "a refused run reserves nothing"


async def test_an_unknown_device_state_is_refused_too(tmp_path):
    """Not knowing whether the user is talking to Jarvis is not a licence to take the microphone."""
    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=_Detector(ContentionState.UNKNOWN))
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
        run = await until_finished(supervisor, run_id)
    assert run.failure.code == FAILURE_DEVICE_CONTENTION
    assert "unknown availability" in run.failure.detail
    assert jobs_of(launcher) == []


async def test_a_free_device_starts_the_run_and_probes_again_while_it_executes(tmp_path):
    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    detector = _Detector(ContentionState.FREE)
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=detector)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
        run = await until_finished(supervisor, run_id)
    assert jobs_of(launcher), "a free device must let the run start"
    assert detector.calls >= 1
    assert run.status in (RunStatus.PASSED, RunStatus.FAILED, RunStatus.ERRORED)


async def test_contention_appearing_mid_run_stops_it_as_inconclusive(tmp_path):
    """The live Jarvis came back. The run is stopped, and what it measured is not a verdict."""
    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    detector = _Detector(ContentionState.FREE)
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=detector, behaviour="hang")
    supervisor._policy = _with_probe(supervisor.policy)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
        for _ in range(500):
            if supervisor.active_run_ids:
                break
            await asyncio.sleep(0.01)
        detector.state = ContentionState.BUSY
        run = await until_finished(supervisor, run_id)
    assert run.failure is not None
    assert run.failure.code == FAILURE_DEVICE_CONTENTION_DURING_RUN
    assert "taken while the run was executing" in run.failure.detail
    assert classify_run(run).outcome is RunOutcomeClass.INCONCLUSIVE


def _with_probe(policy: SupervisorPolicy) -> SupervisorPolicy:
    from dataclasses import replace

    return replace(policy, device_probe_interval_s=0.0)


async def test_a_second_supervisor_sharing_the_lease_path_is_refused(tmp_path):
    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    lease = tmp_path / "shared.device.lock"
    held = DeviceLease(lease)
    held.acquire()
    try:
        supervisor, _, launcher = _supervisor(tmp_path / "b", spec, detector=_Detector(ContentionState.FREE),
                                              lease=lease)
        async with supervisor:
            run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
            run = await until_finished(supervisor, run_id)
    finally:
        held.release()
    assert run.failure.code == FAILURE_DEVICE_CONTENTION
    assert "another Test Lab supervisor" in run.failure.detail
    assert jobs_of(launcher) == []


# --------------------------------------------------------- the live opt-in

PROVIDER = frozenset({Capability.REALTIME_PROVIDER})
PROVIDER_GRANT = ResourceGrant(PROVIDER, max_cost_usd=1.0)


async def test_a_live_run_without_the_opt_in_is_refused_and_calls_nothing(tmp_path):
    spec = _device_spec(ProfileName.LIVE, PROVIDER, cost_usd=0.5)
    supervisor, _, launcher = _supervisor(tmp_path, spec, base_environ={})
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.LIVE, grant=PROVIDER_GRANT))
        run = await until_finished(supervisor, run_id)
    assert run.failure.code == FAILURE_LIVE_OPT_IN_MISSING
    assert "JARVIS_TESTLAB_LIVE=1" in run.failure.detail
    assert "nothing was spent" in run.failure.detail
    assert classify_run(run).outcome is RunOutcomeClass.REFUSED
    assert jobs_of(launcher) == []


async def test_the_budget_gate_refuses_before_the_opt_in_is_even_consulted(tmp_path):
    """Money first: a declared cost the grant does not cover never reaches the reservation path."""
    spec = _device_spec(ProfileName.LIVE, PROVIDER, cost_usd=5.0)
    supervisor, _, launcher = _supervisor(tmp_path, spec, base_environ=LIVE_ENVIRON)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.LIVE,
                                                    grant=ResourceGrant(PROVIDER, max_cost_usd=1.0)))
        run = await until_finished(supervisor, run_id)
    assert run.failure.code == "permission_denied"
    assert "cost_budget_exceeded" in run.failure.detail
    assert classify_run(run).outcome is RunOutcomeClass.REFUSED
    assert jobs_of(launcher) == []


async def test_a_live_run_with_the_opt_in_and_the_budget_starts(tmp_path):
    spec = _device_spec(ProfileName.LIVE, PROVIDER, cost_usd=0.5)
    supervisor, _, launcher = _supervisor(tmp_path, spec, base_environ=LIVE_ENVIRON)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.LIVE, grant=PROVIDER_GRANT))
        await until_finished(supervisor, run_id)
    assert jobs_of(launcher)


async def test_a_device_run_never_consults_the_live_opt_in(tmp_path):
    """The two gates are independent: an audio run needs no provider and no opt-in."""
    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=_Detector(ContentionState.FREE), base_environ={})
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
        await until_finished(supervisor, run_id)
    assert jobs_of(launcher)


# ------------------------------------------------------- the audio artifact opt-in

async def test_the_job_carries_no_audio_opt_in_unless_all_three_conditions_hold(tmp_path):
    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)

    async def submitted(*, asked: bool, store_allows: bool, profile: ProfileName = ProfileName.AUDIO) -> bool:
        target = _device_spec(profile, AUDIO_DEVICE if profile is ProfileName.AUDIO else PROVIDER,
                              cost_usd=0.0 if profile is ProfileName.AUDIO else 0.5)
        supervisor, _, launcher = _supervisor(tmp_path / f"{asked}-{store_allows}-{profile.value}", target,
                                              detector=_Detector(ContentionState.FREE),
                                              base_environ=LIVE_ENVIRON, allow_audio=store_allows)
        grant = DEVICE_GRANT if profile is ProfileName.AUDIO else PROVIDER_GRANT
        async with supervisor:
            run_id = await supervisor.submit(RunRequest("voice.device_probe", profile, grant=grant,
                                                        allow_audio_artifacts=asked))
            await until_finished(supervisor, run_id)
        return jobs_of(launcher)[0].allow_audio

    assert await submitted(asked=True, store_allows=True) is True
    assert await submitted(asked=False, store_allows=True) is False
    assert await submitted(asked=True, store_allows=False) is False
    # A `live` run declares no device and produces no clip: the profile decides too.
    assert await submitted(asked=True, store_allows=True, profile=ProfileName.LIVE) is False
    del spec


async def test_a_refused_provider_run_never_takes_the_device_lease(tmp_path):
    """The lease is the one thing the gate TAKES, so it is taken last.

    A `hardware:guided` profile may declare a provider AND devices. Acquiring the
    lease before the opt-in check would leak it: only `_release` gives it back, and a
    refused run never becomes active.
    """
    requires = AUDIO_DEVICE | frozenset({Capability.REALTIME_PROVIDER, Capability.HUMAN_PRESENCE})
    spec = _device_spec(ProfileName.HARDWARE_GUIDED, requires, cost_usd=0.1)
    lease = tmp_path / "shared.device.lock"
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=_Detector(ContentionState.FREE),
                                          base_environ={}, lease=lease)
    grant = ResourceGrant(requires, max_cost_usd=1.0)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.HARDWARE_GUIDED, grant=grant))
        run = await until_finished(supervisor, run_id)
    assert run.failure.code == FAILURE_LIVE_OPT_IN_MISSING
    assert jobs_of(launcher) == []
    # Free for anyone else: nothing was taken.
    other = DeviceLease(lease)
    other.acquire()
    other.release()


# ------------------------------------- rework: "we could not look" is never "free"

async def test_an_oversized_heartbeat_reads_unknown_not_free(tmp_path):
    """QA repro: a 100 KiB `.voice_heartbeat` used to read free/available."""
    from jarvis.testlab.devices import MAX_SIGNAL_BYTES

    root = tmp_path / "runtime"
    root.mkdir()
    (root / VOICE_HEARTBEAT_FILE).write_bytes(b"x" * (MAX_SIGNAL_BYTES + 1))
    report = default_contention_detector(root).detect()
    assert report.state is ContentionState.UNKNOWN and not report.available
    assert "could not be read" in report.evidence[0].detail


async def test_a_heartbeat_that_is_a_directory_reads_unknown_not_free(tmp_path):
    """QA repro: `.voice_heartbeat` as a DIRECTORY used to read free/available."""
    root = tmp_path / "runtime"
    root.mkdir()
    (root / VOICE_HEARTBEAT_FILE).mkdir()
    report = default_contention_detector(root).detect()
    assert report.state is ContentionState.UNKNOWN and not report.available


@pytest.mark.skipif(os.name != "nt", reason="byte-range locking is the Windows mechanism here")
async def test_a_locked_heartbeat_reads_unknown_not_free(tmp_path):
    """A file another process holds is the absence of evidence, not evidence of absence."""
    import msvcrt

    root = tmp_path / "runtime"
    root.mkdir()
    path = root / VOICE_HEARTBEAT_FILE
    path.write_text(f"{NOW}\n", encoding="utf-8")
    handle = os.open(path, os.O_RDWR)
    try:
        msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        report = default_contention_detector(root).detect()
    finally:
        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        os.close(handle)
    assert report.state is ContentionState.UNKNOWN and not report.available


async def test_a_runtime_root_that_does_not_exist_reads_unknown(tmp_path):
    """A missing directory is a configuration error, not an observation that nobody is speaking."""
    report = default_contention_detector(tmp_path / "never-created").detect()
    assert report.state is ContentionState.UNKNOWN and not report.available
    assert "does not exist" in report.evidence[0].detail


async def test_an_unreadable_state_file_reads_unknown_even_with_no_heartbeat(tmp_path):
    """The hole was in every signal, not only the heartbeat."""
    root = tmp_path / "runtime"
    root.mkdir()
    (root / VOICE_STATE_FILE).mkdir()
    report = default_contention_detector(root).detect()
    assert report.state is ContentionState.UNKNOWN and not report.available


async def test_a_busy_heartbeat_still_wins_over_an_unreadable_state_file(tmp_path):
    """Order matters: anything that positively says BUSY beats "we could not look"."""
    root = _runtime(tmp_path, heartbeat=NOW - 1.0)
    (root / VOICE_STATE_FILE).mkdir()
    evidence = _probe(root)
    assert evidence.state is ContentionState.BUSY


# -------------------------------------------- rework: a gate or supervision fault

class _RaisingDetector:
    """A detector that breaks. Slice 10 is what will inject one, so this is the moment."""

    def __init__(self, *, fail_after: int = 0) -> None:
        self.calls = 0
        self.fail_after = fail_after

    def detect(self):
        self.calls += 1
        if self.calls > self.fail_after:
            raise RuntimeError("the injected detector exploded")
        return _Detector(ContentionState.FREE).detect()


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, dict(data or {})))

    def kinds(self, level: str | None = None) -> list[str]:
        return [kind for kind, item, _data in self.events if level is None or item == level]


async def test_a_gate_that_raises_refuses_that_run_instead_of_queueing_it_forever(tmp_path):
    """QA repro (a): the run used to sit `queued` with no `blocked_since`, so nothing
    could ever refuse or expire it. A queued run nobody will finish is worse than a
    refused one, and it is a SUPERVISOR fault, so it never wears the worker's code."""
    from jarvis.testlab.jobs import FAILURE_SUPERVISOR_FAULT

    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    sink = RecordingSink()
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=_RaisingDetector())
    supervisor._diagnostics = _safe(sink)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
        run = await until_finished(supervisor, run_id)
        assert supervisor.pending_run_ids == () and supervisor.active_run_ids == ()
    assert run.status is RunStatus.ERRORED
    assert run.failure.code == FAILURE_SUPERVISOR_FAULT
    assert "could not evaluate this run's resource gates" in run.failure.detail
    assert "no device or provider was taken" in run.failure.detail
    assert classify_run(run).outcome is RunOutcomeClass.CRASHED
    assert jobs_of(launcher) == []
    assert "testlab.run.gate_failed" in sink.kinds("error")


async def test_a_mid_run_detector_fault_is_a_supervisor_fault_not_the_workers(tmp_path):
    """QA repro (b): the `_execute` task died with nothing in the log and the run was
    recorded `worker_result_invalid` — a supervisor fault blamed on the worker."""
    from jarvis.testlab.jobs import FAILURE_SUPERVISOR_FAULT

    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    sink = RecordingSink()
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=_RaisingDetector(fail_after=1),
                                          behaviour="hang")
    supervisor._diagnostics = _safe(sink)
    supervisor._policy = _with_probe(supervisor.policy)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
        run = await until_finished(supervisor, run_id)
        assert supervisor.active_run_ids == ()
    assert run.failure.code == FAILURE_SUPERVISOR_FAULT
    assert "failed while watching this run" in run.failure.detail
    assert classify_run(run).outcome is RunOutcomeClass.CRASHED
    assert "testlab.run.supervision_failed" in sink.kinds("error")
    assert jobs_of(launcher), "the worker WAS started; the fault came afterwards"
    assert supervisor.reserved_capabilities == frozenset(), "a faulted run still frees its resources"


async def test_no_run_can_stay_non_terminal_after_a_gate_or_execute_fault(tmp_path):
    """The invariant behind both repros: whatever breaks, every submitted run ends."""
    from jarvis.testlab.runs import TERMINAL_STATUSES

    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    for index, detector in enumerate((_RaisingDetector(), _RaisingDetector(fail_after=1))):
        supervisor, store, _ = _supervisor(tmp_path / f"case{index}", spec, detector=detector, behaviour="hang")
        supervisor._policy = _with_probe(supervisor.policy)
        async with supervisor:
            run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
            run = await until_finished(supervisor, run_id)
        assert run.status in TERMINAL_STATUSES, (index, run.status)
        assert store.get_run(run_id).status in TERMINAL_STATUSES


def _safe(sink):
    from jarvis.testlab._diagnostics import SafeDiagnostics

    return SafeDiagnostics(sink)


async def test_contention_during_the_startup_window_is_caught_before_the_first_heartbeat(tmp_path):
    """The reservation is held from spawn, so the probe runs from spawn.

    A `silent` worker never beats, which is exactly the startup window: up to
    `startup_timeout_s` (60 s by default) during which the devices were reserved and,
    before this rework, nobody looked.
    """
    import time
    from dataclasses import replace as _replace

    spec = _device_spec(ProfileName.AUDIO, AUDIO_DEVICE)
    detector = _Detector(ContentionState.FREE)
    supervisor, _, launcher = _supervisor(tmp_path, spec, detector=detector, behaviour="silent")
    supervisor._policy = _replace(supervisor.policy, device_probe_interval_s=0.0, startup_timeout_s=30.0,
                                  cancel_grace_s=0.1, poll_interval_s=0.02)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.device_probe", ProfileName.AUDIO, grant=DEVICE_GRANT))
        for _ in range(500):
            if supervisor.active_run_ids:
                break
            await asyncio.sleep(0.01)
        detector.state = ContentionState.BUSY
        started = time.monotonic()
        run = await until_finished(supervisor, run_id)
    assert run.failure.code == FAILURE_DEVICE_CONTENTION_DURING_RUN
    assert time.monotonic() - started < 25.0, "it must not wait for the startup timeout"
    assert jobs_of(launcher), "the worker was spawned; it simply had not beaten yet"
