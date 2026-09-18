"""The Test Lab run supervisor: from a request to a persisted, isolated, observable TestRun.

Binding contract: `docs/testlab.md` ("Supervisor and workers"). Locked decision
13: runs execute in supervised isolated workers, never inside the Control Center
process. This module owns everything that is not process mechanics
(`jarvis.testlab.worker_launcher`) or execution (`jarvis.testlab.worker`):

- it persists the queued record before it returns a run id, so a run always
  exists as evidence, including one refused by the permission gate;
- it reserves the declared capabilities of a profile so two runs never contend
  for the provider, a device or the human;
- it applies run-local overrides to a COPY of the settings, inside a per-run
  scratch directory, and never writes the permanent settings file (READINESS
  B4.2);
- it bounds every run: startup, heartbeat, declared duration, cancel grace, then
  a tree kill. A run never stays `running`, whatever the worker does;
- it derives the verdict itself, from the worker's metrics, and refuses to store
  a completed run that `check_run_against_spec` contradicts;
- it computes the declared score (`jarvis.testlab.scoring`) from those metrics,
  because the score belongs where the declaration is; the worker never sends one
  and the score never changes the verdict;
- it adopts the runs of a supervisor that died, and schedules the store upkeep
  Slice 02 left unscheduled.

Everything the operator needs to see is emitted through the injected
`DiagnosticSink`: submission, the wait for a resource, the start with its pid,
progress heartbeats, and every terminal state with its duration and failure code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
import secrets
import shutil
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.conversation_events import to_event_time
from jarvis.ports.v2 import DiagnosticSink
from jarvis.runtime.crash_guard import describe_exit_code
from jarvis.testlab._diagnostics import SafeDiagnostics
from jarvis.testlab._fs import (
    EntryLock,
    check_path_budget,
    default_max_path_chars,
    is_link,
    write_atomic,
)
from jarvis.testlab.capture import (
    ConfigSnapshot,
    EnvironmentCapture,
    TestLabCaptureError,
    build_config_snapshot,
    capture_code_identity,
    capture_environment,
    failure_detail,
    redact_evidence,
    store_config_snapshot,
)
from jarvis.testlab.catalog import DEFAULT_CATALOG_ROOT, Catalog, CatalogEntry, load_catalog
from jarvis.testlab.diagnostics import (
    AssertionResult,
    DiagnosticSpec,
    ParameterSpec,
    check_parameter_value,
    evaluate_assertion,
    resolve_parameters,
)
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.jobs import (
    CANCEL_FILE_NAME,
    DATA_DIR_NAME,
    FAILURE_CANCELLED,
    FAILURE_DEVICE_CONTENTION,
    FAILURE_DEVICE_CONTENTION_DURING_RUN,
    FAILURE_HUMAN_PRESENCE_MISSING,
    FAILURE_LIVE_OPT_IN_MISSING,
    FAILURE_PERMISSION_DENIED,
    FAILURE_RESOURCE_WAIT_TIMEOUT,
    FAILURE_RESULT_CONTRADICTS_SPEC,
    FAILURE_RESULT_INVALID,
    FAILURE_RUN_ABANDONED,
    FAILURE_RUN_CONCLUDED_OUT_OF_BAND,
    FAILURE_RUN_TIMEOUT,
    FAILURE_SUPERVISOR_FAULT,
    FAILURE_SUPERVISOR_STOPPED,
    FAILURE_WORKER_ACTIVE_ELSEWHERE,
    FAILURE_WORKER_CRASHED,
    FAILURE_WORKER_LOST,
    FAILURE_WORKER_SPAWN_FAILED,
    FAILURE_WORKER_STARTUP_TIMEOUT,
    FAILURE_WORKER_UNRESPONSIVE,
    HEARTBEAT_FILE_NAME,
    JOB_FILE_NAME,
    RESULT_FILE_NAME,
    RUNTIME_DIR_NAME,
    STDERR_LOG_ARTIFACT,
    STDERR_LOG_NAME,
    WORKER_FILE_NAME,
    WORKER_LOCK_NAME,
    WORKER_LOG_ARTIFACT,
    WORKER_LOG_NAME,
    WorkerJob,
    WorkerResult,
    WorkerStatus,
    worker_failure,
)
from jarvis.testlab.maintenance import MaintenancePolicy, MaintenanceReport, run_maintenance_pass
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES, PrimitiveRegistry, ScenarioContext, check_scenario
from jarvis.testlab.devices import (
    DeviceContentionDetector,
    DeviceLease,
    DeviceLeaseBusy,
    default_contention_detector,
    needs_device,
)
from jarvis.testlab.hardware.prompts import GUIDED_OPT_IN_ENV, guided_opt_in
from jarvis.testlab.live.session import LIVE_OPT_IN_ENV, live_opt_in
from jarvis.testlab.profiles import (
    Capability,
    PermissionDecision,
    PROVIDER_CAPABILITIES,
    ProfileName,
    ResourceGrant,
    check_profile_permission,
)
from jarvis.testlab.runs import (
    ArtifactKind,
    ArtifactRef,
    CodeIdentity,
    RunFailure,
    RunStatus,
    TERMINAL_STATUSES,
    TestRun,
    complete_run,
    check_run_against_spec,
    transition_run,
)
from jarvis.testlab.scenarios import Scenario
from jarvis.testlab.scoring import compute_score
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.store import MAX_PAGE_LIMIT, RunQuery, TestLabStoreError, TestRunStore
from jarvis.testlab.validation import TestLabError, canonical_json, decode_json_document
from jarvis.testlab.worker_launcher import SubprocessWorkerLauncher, WorkerLauncher, WorkerProcess

#: Repository root, the working directory a worker is started in.
REPO_ROOT = Path(__file__).resolve().parents[2]
#: Settings file a run copies (never writes): `<runtime>/control-center-settings.json`.
SETTINGS_FILE_NAME = "control-center-settings.json"
JOB_TMP_PREFIX = ".job-"

#: Extra time `aclose` allows, past the cancel grace, for a killed worker to be reaped.
_SHUTDOWN_GRACE_S = 20.0

SUPERVISOR_REQUEST_INVALID = "testlab_supervisor_request_invalid"
SUPERVISOR_STOPPED = "testlab_supervisor_stopped"
SUPERVISOR_UNKNOWN_RUN = "testlab_supervisor_unknown_run"
SUPERVISOR_WORK_ROOT_BUSY = "testlab_supervisor_work_root_busy"

#: One supervisor per work root, enforced by an OS lock the kernel releases on death.
WORK_ROOT_LOCK_NAME = ".supervisor.lock"
#: Slice 08: the cross-supervisor audio device lease. Two work roots (two worktrees)
#: pointed at the same path exclude each other; the default keeps it inside the work
#: root, where it only excludes this supervisor from itself, which reservation already
#: does. An operator who runs two work roots on one workstation gives them one path.
DEVICE_LEASE_NAME = ".device.lock"
#: Profiles whose runs can legitimately produce an audio clip.
AUDIO_CAPABLE_PROFILES = frozenset({ProfileName.AUDIO, ProfileName.HARDWARE_AUTO, ProfileName.HARDWARE_GUIDED})

#: Provider credentials removed from a worker environment unless the profile declares a
#: provider capability. They are set to "" rather than dropped, because
#: `jarvis.environment.load_project_environment` fills MISSING names from `.env`.
PROVIDER_ENV_NAMES = ("OPENAI_API_KEY", "OPENAI_ORGANIZATION", "OPENAI_PROJECT", "ANTHROPIC_API_KEY",
                      "GOOGLE_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY", "ELEVENLABS_API_KEY")
#: Environment names a worker must never inherit: they would point it at the live runtime.
INHERITED_ENV_OVERRIDES = ("JARVIS_CORE_TOKEN_FILE",)

#: A missing result file: the worker died before writing one.
RESULT_MISSING = "missing"
#: Supervisor reasons that say nothing about the measurement: a complete result written
#: just before one of these fired is the truth, and the fault was a false alarm.
LIVENESS_REASONS = frozenset({FAILURE_WORKER_STARTUP_TIMEOUT, FAILURE_WORKER_UNRESPONSIVE})

#: Worker failure code -> terminal status. Everything else is `errored`.
TERMINAL_BY_FAILURE: Mapping[str, RunStatus] = {
    FAILURE_RUN_TIMEOUT: RunStatus.TIMED_OUT,
    FAILURE_CANCELLED: RunStatus.CANCELLED,
}


class SupervisorError(TestLabError):
    """A request the supervisor refuses outright, before any record exists."""


def _redact_log(text: str) -> bytes:
    """Redacted bytes of a captured log, ready to be stored as an artifact."""
    return redact_evidence(text).encode("utf-8", errors="replace")


# ------------------------------------------------------------------ inputs

@dataclass(frozen=True, slots=True)
class RunRequest:
    """What a caller asks for. `grant` is what the caller authorizes, not what it wants."""

    diagnostic_id: str
    profile: ProfileName
    #: None: the latest published version. The resolved version is recorded in the run.
    version: int | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    #: Run-local setting overrides; every name must be in the manifest `override_allowlist`.
    overrides: Mapping[str, Any] = field(default_factory=dict)
    #: Replaces the manifest scenario. Checked against this diagnostic and profile before queuing.
    scenario: Scenario | None = None
    bundle_id: str | None = None
    sweep_id: str | None = None
    parent_run_id: str | None = None
    grant: ResourceGrant = field(default_factory=ResourceGrant)
    #: Slice 08: let this run store `audio_clip` artifacts. Three conditions, all
    #: required: the caller asks here, the profile is one that can produce audio
    #: (`audio`, `hardware:*`), and the supervisor's own store allows audio. Off by
    #: default, because raw audio is the one artifact kind that can carry a voice.
    allow_audio_artifacts: bool = False


@dataclass(frozen=True, slots=True)
class SupervisorPolicy:
    """Bounds the supervisor enforces. Every wait here has a deadline it cannot outlive."""

    #: Runs executing at once, whatever their resources.
    max_concurrent_runs: int = 2
    #: How long a queued run may wait for its capabilities before it is refused.
    max_queue_wait_s: float = 600.0
    #: Spawn to first heartbeat. Exceeded: `worker_startup_timeout`.
    startup_timeout_s: float = 60.0
    #: Silence of a started worker. Exceeded: `worker_unresponsive`.
    heartbeat_timeout_s: float = 30.0
    #: Grace between a cooperative stop and the forced tree kill.
    cancel_grace_s: float = 5.0
    #: How often the supervisor looks at the worker's heartbeat and deadlines.
    poll_interval_s: float = 0.2
    #: Operator cap over the profile's declared `max_duration_s` (None: the declaration decides).
    max_run_duration_s: float | None = None
    #: Keep the run scratch after the run (debugging). Off: it is removed with the run.
    keep_scratch: bool = False
    maintenance: MaintenancePolicy = field(default_factory=MaintenancePolicy)
    #: Wait for a dead worker's lock during adoption; a live worker holds it forever.
    adopt_lock_timeout_s: float = 1.0
    #: Wait for the work-root lock at `start()`; another live supervisor holds it forever.
    work_root_lock_s: float = 1.0
    #: Slice 08: how often a run holding an audio device re-checks that the live Jarvis has
    #: not come back. It bounds how long the two could overlap; it cannot prevent the overlap.
    device_probe_interval_s: float = 1.0


@dataclass(frozen=True, slots=True)
class AdoptionReport:
    """What `start()` found left behind by a previous supervisor.

    `reaped` counts only runs whose terminal record was actually written. A run the
    store refused is in `failed` with the refusal code, never in `reaped`: a report
    that claims a run was finished when it is still `running` is worse than no report.
    """

    #: Runs made terminal, with the failure code used. The write succeeded.
    reaped: tuple[tuple[str, str], ...] = ()
    #: Runs whose worker lock is still held: another supervisor owns them, untouched.
    active_elsewhere: tuple[str, ...] = ()
    #: Runs finished from a `result.json` the dead supervisor never persisted.
    recovered: tuple[str, ...] = ()
    #: (run_id, store error code) for a run adoption could not make terminal.
    failed: tuple[tuple[str, str], ...] = ()
    #: Scratch directories removed because no non-terminal run referenced them.
    scratch_removed: int = 0

    @property
    def total(self) -> int:
        return len(self.reaped) + len(self.active_elsewhere) + len(self.failed) + self.scratch_removed


# ----------------------------------------------------------- internal state

class _Adoption(StrEnum):
    """What adoption did with one run left behind."""

    #: Made terminal with a structured failure, and the write succeeded.
    REAPED = "reaped"
    #: Finished from the result file its supervisor never persisted.
    RECOVERED = "recovered"
    #: A live worker still holds it: left alone.
    ACTIVE = "active"
    #: The terminal write was refused; the run is still not terminal.
    FAILED = "failed"


@dataclass(slots=True)
class _Pending:
    """One accepted run waiting for its resources, or being executed."""

    run_id: str
    entry: CatalogEntry
    profile: ProfileName
    capabilities: frozenset[Capability]
    parameters: Mapping[str, Any]
    overrides: Mapping[str, Any]
    scenario: Scenario | None
    settings: Mapping[str, Any]
    max_duration_s: float
    queued_at: float
    #: Slice 08: whether this run's worker store may write `audio_clip` artifacts.
    allow_audio: bool = False
    #: Loop time from which this run has been genuinely blocked (no free slot, or a
    #: capability held). None while it has not been evaluated yet — a run that never got
    #: a chance to start, because an upkeep pass held the start gate, accrues no queue wait.
    blocked_since: float | None = None


@dataclass(slots=True)
class _Active:
    pending: _Pending
    scratch: Path
    worker: WorkerProcess | None = None
    stop_reason: str | None = None
    #: One English line saying WHY, when the code alone is not enough (Slice 08's
    #: device contention names what was seen holding the device).
    stop_detail: str | None = None
    stop_at: float | None = None
    cancel_requested: bool = False
    #: True once THIS supervisor wrote the terminal record. A terminal record without
    #: it means something else concluded the run (see `_report_out_of_band`).
    concluded: bool = False

    @property
    def run_id(self) -> str:
        return self.pending.run_id


@dataclass(slots=True)
class _Supervision:
    """What watching one worker established."""

    result: WorkerResult | None
    #: Why there is no result (`RESULT_MISSING`, `unreadable`, `invalid`, ...), else None.
    result_problem: str | None
    exit_code: int | None
    stop_reason: str | None
    stop_detail: str | None
    killed: bool
    stderr_tail: str
    started: bool


class RunSupervisor:
    """Submit, watch, cancel and persist Test Lab runs executed in worker processes."""

    def __init__(self, *, store: TestRunStore, work_root: Path, catalog: Catalog | None = None,
                 catalog_root: Path = DEFAULT_CATALOG_ROOT,
                 policy: SupervisorPolicy = SupervisorPolicy(), launcher: WorkerLauncher | None = None,
                 repo_root: Path = REPO_ROOT, settings_path: Path | None = None,
                 primitives: PrimitiveRegistry = DEFAULT_PRIMITIVES, diagnostics: DiagnosticSink | None = None,
                 clock: Any = None, nonce: Any = None, code_probe: Any = None,
                 environment: Mapping[str, Any] | None = None, base_environ: Mapping[str, str] | None = None,
                 max_path_chars: int | None | object = ...,
                 contention: DeviceContentionDetector | None = None,
                 device_lease_path: Path | None | object = ...) -> None:
        self._store = store
        self._catalog_root = Path(catalog_root)
        #: Supervisor and worker resolve implementation names with the same registry, so a run
        #: is queued against exactly the declaration the worker will execute.
        self._catalog = catalog if catalog is not None else load_catalog(
            self._catalog_root, implementations=catalog_implementations())
        self._work_root = Path(work_root)
        self._policy = policy
        self._launcher = launcher if launcher is not None else SubprocessWorkerLauncher()
        self._repo_root = Path(repo_root)
        self._settings_path = settings_path
        self._primitives = primitives
        self._diagnostics = SafeDiagnostics(diagnostics)
        self._clock = clock if clock is not None else _utc_now
        self._nonce = nonce if nonce is not None else (lambda: secrets.token_hex(8))
        self._code_probe = code_probe if code_probe is not None else (lambda: capture_code_identity(self._repo_root))
        self._environment = environment
        self._base_environ = dict(base_environ if base_environ is not None else os.environ)
        self.max_path_chars: int | None = default_max_path_chars() if max_path_chars is ... else max_path_chars
        self._pending: list[_Pending] = []
        self._active: dict[str, _Active] = {}
        self._reserved: set[Capability] = set()
        self._finished: dict[str, asyncio.Event] = {}
        self._wake = asyncio.Event()
        self._start_gate = asyncio.Lock()
        self._dispatcher: asyncio.Task[None] | None = None
        self._maintainer: asyncio.Task[None] | None = None
        self._work_lock: EntryLock | None = None
        self._closing = False
        # Slice 08 (READINESS B9). The detector reads the LIVE runtime root — the one the
        # workstation Jarvis publishes its heartbeat in — never the per-run scratch, which
        # is empty of its signals by construction and would always read "free".
        self._contention = contention if contention is not None else default_contention_detector(
            self._live_runtime_root())
        lease = (self._work_root / DEVICE_LEASE_NAME) if device_lease_path is ... else device_lease_path
        self._device_lease = DeviceLease(Path(lease)) if lease is not None else None

    # -------------------------------------------------------------- lifecycle

    async def start(self) -> AdoptionReport:
        """Take the work root, reap what a previous supervisor left, then begin dispatching.

        Called before any `submit`. Adoption never leaves a run `running`: either
        a result file finishes it, or it is made terminal with a structured failure.
        One work root has one supervisor: a second one refuses to start rather than
        reap runs whose worker has not yet taken its lock.
        """
        self._take_work_root()
        report = await self._adopt_orphans()
        self._diagnostics.emit("testlab.supervisor.started", "Test Lab supervisor started",
                               reaped=len(report.reaped), recovered=len(report.recovered),
                               active_elsewhere=len(report.active_elsewhere),
                               scratch_removed=report.scratch_removed)
        if self._dispatcher is None:
            self._dispatcher = asyncio.create_task(self._dispatch_loop(), name="testlab-supervisor-dispatch")
        if self._maintainer is None and self._policy.maintenance.enabled:
            self._maintainer = asyncio.create_task(self._maintenance_loop(), name="testlab-supervisor-maintenance")
        return report

    async def aclose(self) -> None:
        """Stop dispatching, stop every running worker, and make its run terminal."""
        self._closing = True
        self._wake.set()
        for task in (self._dispatcher, self._maintainer):
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in (self._dispatcher, self._maintainer) if task is not None),
                             return_exceptions=True)
        self._dispatcher = self._maintainer = None
        for pending in list(self._pending):
            self._pending.remove(pending)
            await self._refuse(pending, RunStatus.CANCELLED,
                               worker_failure(FAILURE_SUPERVISOR_STOPPED, "the supervisor stopped while queued"))
        running = list(self._active.values())
        for active in running:
            active.cancel_requested = True
            self._request_stop(active, FAILURE_CANCELLED)
        waits = [self._finished.setdefault(active.run_id, asyncio.Event()).wait() for active in running]
        if waits:
            try:
                # Bounded: the watch loop kills each worker one cancel grace after the marker,
                # so this can only be reached if the kill itself is stuck.
                await asyncio.wait_for(asyncio.gather(*waits, return_exceptions=True),
                                       timeout=self._policy.cancel_grace_s + _SHUTDOWN_GRACE_S)
            except asyncio.TimeoutError:
                self._diagnostics.emit("testlab.supervisor.stop_timeout",
                                       "Test Lab supervisor stopped with workers still exiting", level="warning",
                                       runs=len(self._active))
                for active in running:
                    if active.worker is not None:
                        await active.worker.kill_tree()
        self._release_work_root()
        self._diagnostics.emit("testlab.supervisor.stopped", "Test Lab supervisor stopped")

    def _take_work_root(self) -> None:
        """Hold the work root for this supervisor's lifetime (idempotent).

        Two supervisors on one work root are not supported: there is a window
        between `queued -> running` and the worker taking its own lock in which the
        second would see a live run as abandoned and reap it. The lock is an OS lock,
        so a supervisor that dies releases it and the next one starts normally.
        """
        if self._work_lock is not None:
            return
        self._work_root.mkdir(parents=True, exist_ok=True)
        lock = EntryLock(self._work_root / WORK_ROOT_LOCK_NAME, "Test Lab work root", self._policy.work_root_lock_s)
        try:
            lock.__enter__()
        except TestLabStoreError as exc:
            raise SupervisorError(SUPERVISOR_WORK_ROOT_BUSY,
                                  "another supervisor is using this work root") from exc
        self._work_lock = lock

    def _release_work_root(self) -> None:
        lock, self._work_lock = self._work_lock, None
        if lock is not None:
            lock.__exit__(None, None, None)

    async def __aenter__(self) -> RunSupervisor:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ----------------------------------------------------------------- submit

    async def submit(self, request: RunRequest) -> str:
        """Persist a queued run and return its id. A refused run is persisted too, as `errored`.

        Raises `SupervisorError` only when no honest record could be written at
        all (unknown diagnostic, unsupported profile, invalid parameters, no git
        identity): there is then no declaration to judge the run by.
        """
        if self._closing:
            raise SupervisorError(SUPERVISOR_STOPPED, "the supervisor is stopping")
        if not isinstance(request, RunRequest):
            raise SupervisorError(SUPERVISOR_REQUEST_INVALID, "submit takes a RunRequest")
        entry = self._describe(request)
        spec = entry.diagnostic
        availability = self._availability(entry, request.profile)
        scenario = request.scenario if request.scenario is not None else entry.manifest.scenario
        parameters, overrides = self._resolve_inputs(entry, request, scenario)
        settings = self._settings_document(overrides)
        snapshot = _snapshot(settings)
        code = await self._code_identity()
        created_at = self._clock()
        run_id = format_run_id(created_at, self._nonce())
        try:
            run = TestRun(
                run_id=run_id, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                profile=request.profile, status=RunStatus.QUEUED, created_at=created_at, code=code,
                config_fingerprint=snapshot.fingerprint, diagnostic_fingerprint=spec.fingerprint(),
                parameters=parameters, overrides=overrides, environment=self._environment_facts(),
                bundle_id=request.bundle_id, sweep_id=request.sweep_id, parent_run_id=request.parent_run_id,
                scenario_id=None if scenario is None else scenario.scenario_id,
                scenario_fingerprint=None if scenario is None else scenario.fingerprint())
        except TestLabError as exc:
            raise SupervisorError(SUPERVISOR_REQUEST_INVALID, exc.detail) from None
        run = await asyncio.to_thread(self._store.create_run, run)
        run = await self._store_snapshot(run, snapshot)
        self._diagnostics.emit("testlab.run.queued", f"Test Lab run {run_id} queued", run_id=run_id,
                               diagnostic=spec.diagnostic_id, version=spec.version, profile=request.profile.value,
                               requires=sorted(item.value for item in availability.requires))
        decision = check_profile_permission(entry.diagnostic.profiles[request.profile], request.grant)
        if not decision.allowed:
            await self._refuse_run(run, RunStatus.ERRORED,
                                   worker_failure(FAILURE_PERMISSION_DENIED, _denial_detail(decision)))
            return run_id
        self._finished.setdefault(run_id, asyncio.Event())
        self._pending.append(_Pending(
            run_id=run_id, entry=entry, profile=request.profile, capabilities=availability.requires,
            parameters=parameters, overrides=overrides, scenario=scenario, settings=settings,
            max_duration_s=self._run_budget(availability.cost.max_duration_s),
            allow_audio=self._audio_allowed(request),
            queued_at=asyncio.get_running_loop().time()))
        self._wake.set()
        return run_id

    async def status(self, run_id: str) -> TestRun:
        """The stored record, whatever its state."""
        return await asyncio.to_thread(self._store.get_run, run_id)

    async def cancel(self, run_id: str, *, reason: str | None = None) -> bool:
        """Ask a run to stop. Queued: terminal at once. Running: cooperative, then killed.

        Returns False when this supervisor does not hold the run: unknown id, run
        already terminal, or a run another supervisor is executing.
        """
        for pending in list(self._pending):
            if pending.run_id == run_id:
                self._pending.remove(pending)
                await self._refuse(pending, RunStatus.CANCELLED, worker_failure(
                    FAILURE_CANCELLED, failure_detail(reason or "cancelled while queued")))
                return True
        active = self._active.get(run_id)
        if active is not None:
            if not active.cancel_requested:
                active.cancel_requested = True
                self._request_stop(active, FAILURE_CANCELLED)
                self._diagnostics.emit("testlab.run.cancelling", f"Test Lab run {run_id} asked to stop",
                                       run_id=run_id, grace_s=self._policy.cancel_grace_s)
            return True
        return False

    async def wait(self, run_id: str, *, timeout_s: float | None = None) -> TestRun:
        """Await the terminal record of a run this supervisor queued or is executing."""
        event = self._finished.get(run_id)
        if event is not None and not event.is_set():
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
        run = await self.status(run_id)
        if run.status not in TERMINAL_STATUSES and event is None:
            raise SupervisorError(SUPERVISOR_UNKNOWN_RUN, f"run {run_id} is not supervised here")
        return run

    @property
    def catalog(self) -> Catalog:
        """The declarations this supervisor resolves runs against (Slice 07 sweeps read it)."""
        return self._catalog

    @property
    def policy(self) -> SupervisorPolicy:
        return self._policy

    @property
    def clock(self) -> Any:
        """The injected UTC clock, so a caller minting related ids uses the same time source."""
        return self._clock

    @property
    def nonce(self) -> Any:
        """The injected id nonce source (same reason as `clock`)."""
        return self._nonce

    @property
    def active_run_ids(self) -> tuple[str, ...]:
        return tuple(self._active)

    @property
    def pending_run_ids(self) -> tuple[str, ...]:
        return tuple(pending.run_id for pending in self._pending)

    @property
    def reserved_capabilities(self) -> frozenset[Capability]:
        return frozenset(self._reserved)

    # ------------------------------------------------------------- resolution

    def _describe(self, request: RunRequest) -> CatalogEntry:
        try:
            return self._catalog.describe(request.diagnostic_id, request.version)
        except TestLabError as exc:
            raise SupervisorError(SUPERVISOR_REQUEST_INVALID, exc.detail) from None

    def _availability(self, entry: CatalogEntry, profile: ProfileName) -> Any:
        try:
            return entry.resources_and_cost(profile)
        except TestLabError as exc:
            raise SupervisorError(SUPERVISOR_REQUEST_INVALID, exc.detail) from None

    def _resolve_inputs(self, entry: CatalogEntry, request: RunRequest,
                        scenario: Scenario | None) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        """Effective parameters and run-local setting overrides.

        Setting overrides may only name a setting the manifest allowlists. They come
        from the scenario's `parameter.override` prelude (the only place a scenario may
        change configuration) and from `RunRequest.overrides`; the same name with two
        different values is a refusal, never a silent precedence rule.
        """
        spec = entry.diagnostic
        allowlist: Mapping[str, ParameterSpec] = {item.name: item for item in entry.manifest.override_allowlist}
        declared = {item.name for item in spec.parameters}
        supplied = dict(request.parameters)
        overrides: dict[str, Any] = {}
        for name, value in dict(request.overrides).items():
            if name not in allowlist:
                raise SupervisorError(SUPERVISOR_REQUEST_INVALID,
                                      f"overrides.{name} is not in the manifest override allowlist")
            try:
                overrides[name] = check_parameter_value(allowlist[name], value, f"overrides.{name}")
            except TestLabError as exc:
                raise SupervisorError(SUPERVISOR_REQUEST_INVALID, exc.detail) from None
        if scenario is not None:
            try:
                checked = check_scenario(scenario, primitives=self._primitives, profiles=(request.profile,),
                                         context=ScenarioContext.for_diagnostic(spec,
                                                                                entry.manifest.override_allowlist))
            except TestLabError as exc:
                raise SupervisorError(SUPERVISOR_REQUEST_INVALID, exc.detail) from None
            for name, value in checked.overrides.items():
                target = supplied if name in declared else overrides
                if name in target and target[name] != value:
                    raise SupervisorError(SUPERVISOR_REQUEST_INVALID,
                                          f"{name} is overridden by both the request and the scenario prelude")
                target[name] = value
        try:
            return resolve_parameters(spec.parameters, supplied), overrides
        except TestLabError as exc:
            raise SupervisorError(SUPERVISOR_REQUEST_INVALID, exc.detail) from None

    def _run_budget(self, declared_s: float) -> float:
        cap = self._policy.max_run_duration_s
        return declared_s if cap is None else min(declared_s, cap)

    async def _code_identity(self) -> CodeIdentity:
        try:
            code = await self._code_probe()
        except TestLabCaptureError as exc:
            raise SupervisorError(SUPERVISOR_REQUEST_INVALID,
                                  f"the code identity of this run cannot be captured ({exc.code})") from None
        if not isinstance(code, CodeIdentity):
            raise SupervisorError(SUPERVISOR_REQUEST_INVALID, "the code probe must return a CodeIdentity")
        return code

    def _environment_facts(self) -> Mapping[str, Any]:
        if self._environment is None:
            capture: EnvironmentCapture = capture_environment()
            self._environment = capture.facts
        return self._environment

    async def _store_snapshot(self, run: TestRun, snapshot: ConfigSnapshot) -> TestRun:
        """Commit the redacted configuration snapshot of a queued run as its first artifact."""
        try:
            ref = await asyncio.to_thread(store_config_snapshot, self._store, run.run_id, snapshot)
        except TestLabStoreError as exc:
            # Captured: the run keeps its `config_fingerprint`, so the configuration is still
            # comparable; only the readable copy is missing, and the refusal says why.
            self._diagnostics.emit("testlab.run.snapshot_refused",
                                   f"Test Lab run {run.run_id} configuration snapshot not stored", level="warning",
                                   run_id=run.run_id, code=exc.code)
            return run
        return await asyncio.to_thread(self._store.update_run, replace(run, artifacts=(ref,)), expected=run)

    def _settings_document(self, overrides: Mapping[str, Any]) -> Mapping[str, Any]:
        """The settings the run will use: the permanent file's content plus the run-local overrides.

        The permanent file is only ever READ. When it does not exist the run starts
        from an empty document, which is the normal first-run state.
        """
        document: dict[str, Any] = {}
        path = self._settings_path
        if path is not None:
            try:
                loaded = json.loads(Path(path).read_text(encoding="utf-8-sig"))
                document = dict(loaded) if isinstance(loaded, dict) else {}
            except FileNotFoundError:
                document = {}  # intentional: no settings file is the normal first-run state
            except (OSError, ValueError, UnicodeError) as exc:
                raise SupervisorError(SUPERVISOR_REQUEST_INVALID,
                                      f"the settings file cannot be read ({type(exc).__name__})") from exc
        return apply_overrides(document, overrides)

    # -------------------------------------------------------------- dispatch

    async def _dispatch_loop(self) -> None:
        while not self._closing:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._next_delay())
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self._expire_pending()
                await self._start_ready()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Captured deliberately, and loudly. An unforeseen fault in one pass used
                # to end the dispatcher task with nothing in the log: every queued run then
                # waited forever, `wait()` timed out, and nothing said why. The loop
                # survives the pass, the fault is emitted at `error`, and the next wake
                # tries again — a stuck queue is a worse failure than a repeated one.
                self._diagnostics.emit("testlab.supervisor.dispatch_failed",
                                       "Test Lab dispatch pass failed", level="error",
                                       error=type(exc).__name__, code=getattr(exc, "code", None),
                                       detail=str(exc)[:200],
                                       pending=len(self._pending), active=len(self._active))
                await asyncio.sleep(self._policy.poll_interval_s)

    def _next_delay(self) -> float:
        blocked = [pending.blocked_since for pending in self._pending if pending.blocked_since is not None]
        if not blocked:
            return 60.0
        loop = asyncio.get_running_loop()
        return max(0.05, self._policy.max_queue_wait_s - (loop.time() - min(blocked)))

    async def _expire_pending(self) -> None:
        """Refuse a run that has been genuinely blocked for too long.

        Only blocked time counts. A run that never got a chance to start (an upkeep
        pass held the start gate) has no `blocked_since` and can never expire: the
        supervisor's own slowness is not the caller's fault.
        """
        loop = asyncio.get_running_loop()
        for pending in list(self._pending):
            if pending.blocked_since is None:
                continue
            waited = loop.time() - pending.blocked_since
            if waited > self._policy.max_queue_wait_s:
                self._pending.remove(pending)
                await self._refuse(pending, RunStatus.ERRORED, worker_failure(
                    FAILURE_RESOURCE_WAIT_TIMEOUT,
                    f"waited {waited:.0f} s for {_capability_names(pending.capabilities)} without them freeing up"))

    async def _start_ready(self) -> None:
        """Start every pending run whose resources are free (FIFO, a blocked head never blocks the rest).

        While the start gate is held (a run is starting, or an upkeep pass is running)
        nothing is evaluated and nothing accrues queue-wait time; the holder wakes the
        dispatcher when it releases the gate.
        """
        if self._start_gate.locked():
            return
        loop = asyncio.get_running_loop()
        for pending in list(self._pending):
            if self._closing:
                return
            if len(self._active) >= self._policy.max_concurrent_runs:
                pending.blocked_since = pending.blocked_since or loop.time()
                continue
            if pending.capabilities & self._reserved:
                pending.blocked_since = pending.blocked_since or loop.time()
                self._diagnostics.emit("testlab.run.waiting", f"Test Lab run {pending.run_id} waits for a resource",
                                       run_id=pending.run_id,
                                       requires=sorted(item.value for item in pending.capabilities),
                                       reserved=sorted(item.value for item in self._reserved))
                continue
            # Slice 08: the two external gates, both BEFORE the reservation. A run that
            # fails one is refused outright rather than queued again: neither a live
            # conversation nor a missing opt-in is something waiting will change.
            refusal = await self._gate_or_fault(pending)
            if refusal is not None:
                self._pending.remove(pending)
                await self._refuse(pending, RunStatus.ERRORED, refusal)
                continue
            self._pending.remove(pending)
            self._reserved |= pending.capabilities
            active = _Active(pending, self._work_root / pending.run_id)
            self._active[pending.run_id] = active
            asyncio.create_task(self._execute(active), name=f"testlab-run-{pending.run_id}")

    def _live_runtime_root(self) -> Path:
        """The LIVE runtime directory, where the workstation Jarvis publishes its voice signals.

        Derived from the settings path when one was given (`control-center-settings.json`
        lives in the runtime root, which is how the Control Center finds it) and from the
        repository otherwise. Never from `JARVIS_RUNTIME_DIR`: a worker's environment
        points at its own scratch, and a supervisor that inherited one would probe an
        empty directory and cheerfully report the microphone free.
        """
        if self._settings_path is not None:
            return Path(self._settings_path).parent
        return self._repo_root / "runtime"

    @property
    def contention(self) -> DeviceContentionDetector:
        """The device-contention detector this supervisor gates on (Slice 10 exposes it)."""
        return self._contention

    # ---------------------------------------------------- external gates (08)

    async def _gate_or_fault(self, pending: _Pending) -> RunFailure | None:
        """`_external_gate`, with a gate that BREAKS turned into a refusal of that run.

        The gate calls an injected `DeviceContentionDetector` (Slice 10 composes one),
        so an exception here is code we do not control. Letting it escape ended the
        dispatch pass: the run kept its place in the queue with no `blocked_since`, so
        `max_queue_wait_s` never applied to it and NOTHING would ever make it terminal.
        A queued run nobody will ever finish is worse than a refused one, and a
        supervisor fault must not be recorded against the worker.
        """
        try:
            return await self._external_gate(pending)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._diagnostics.emit("testlab.run.gate_failed",
                                   f"Test Lab could not evaluate the resource gates for {pending.run_id}",
                                   level="error", run_id=pending.run_id, error=type(exc).__name__,
                                   code=getattr(exc, "code", None), detail=str(exc)[:200])
            return worker_failure(FAILURE_SUPERVISOR_FAULT, failure_detail(
                f"the supervisor could not evaluate this run's resource gates ({type(exc).__name__}); "
                "nothing was started, and no device or provider was taken"))

    async def _external_gate(self, pending: _Pending) -> RunFailure | None:
        """Refuse a device or provider run the workstation cannot safely give it.

        Both checks belong HERE, in the reservation path, and not in a runner:
        a runner runs in another process that has already been spawned, and by then
        the microphone would be a fraction of a second from being opened. The
        supervisor is the only place that can decline before anything is started.

        Order matters: everything that only OBSERVES runs first, and the one step that
        TAKES something — the device lease — runs last. A lease taken before a later
        refusal would leak, because only `_release` gives it back and a refused run
        never becomes active.
        """
        if pending.capabilities & PROVIDER_CAPABILITIES and not live_opt_in(self._base_environ):
            return worker_failure(FAILURE_LIVE_OPT_IN_MISSING, failure_detail(
                f"a run that calls a real provider needs the explicit opt-in {LIVE_OPT_IN_ENV}=1 in the "
                "supervisor's environment; it is not set, so nothing was called and nothing was spent"))
        # Slice 09: a guided run spends a PERSON's attention, and a prompt nobody is
        # there to see times out into `inconclusive` after burning the whole run budget.
        # The declared `human_presence` capability says the diagnostic needs a human; this
        # says one is at the keyboard right now, and nothing derives or defaults it.
        if Capability.HUMAN_PRESENCE in pending.capabilities and not guided_opt_in(self._base_environ):
            return worker_failure(FAILURE_HUMAN_PRESENCE_MISSING, failure_detail(
                f"a guided run needs a human present: set {GUIDED_OPT_IN_ENV}=1 in the supervisor's "
                "environment when somebody is at this workstation and ready to follow the prompts"))
        if not needs_device(pending.capabilities):
            return None
        report = await asyncio.to_thread(self._contention.detect)
        self._diagnostics.emit("testlab.device.probed", f"Test Lab probed the audio devices for {pending.run_id}",
                               level="info" if report.available else "warning", run_id=pending.run_id,
                               state=report.state.value, holder=report.holder)
        if not report.available:
            return worker_failure(FAILURE_DEVICE_CONTENTION, failure_detail(report.reason()))
        if self._device_lease is not None:
            try:
                await asyncio.to_thread(self._device_lease.acquire)
            except DeviceLeaseBusy as exc:
                return worker_failure(FAILURE_DEVICE_CONTENTION, failure_detail(exc.detail))
        return None

    def _check_contention_during(self, active: _Active) -> RunFailure | None:
        """Has the live Jarvis taken the device back while this run was executing?

        Bounded by the poll interval, and that is the honest limit of it: nothing
        here can stop Jarvis from starting, only notice quickly and stop the run.
        The measurement is void either way — a run that shared the microphone with a
        live conversation measured both of them.
        """
        if not needs_device(active.pending.capabilities):
            return None
        report = self._contention.detect()
        if report.available:
            return None
        return worker_failure(FAILURE_DEVICE_CONTENTION_DURING_RUN, failure_detail(
            f"the audio devices were taken while the run was executing: {report.reason()}"))

    def _audio_allowed(self, request: RunRequest) -> bool:
        """May this run store `audio_clip` artifacts? All three conditions, or no.

        Asked for by the caller, possible on this profile, and permitted by the store
        this supervisor writes through. The last one is what makes the opt-in real: a
        store built with `allow_audio=False` refuses the write whatever the job says.
        """
        if not request.allow_audio_artifacts or request.profile not in AUDIO_CAPABLE_PROFILES:
            return False
        limits = getattr(self._store, "limits", None)
        return bool(getattr(limits, "allow_audio", False))

    # --------------------------------------------------------------- execute

    async def _execute(self, active: _Active) -> None:
        pending = active.pending
        run_id = pending.run_id
        started_at = self._clock()
        supervision: _Supervision | None = None
        failure: RunFailure | None = None
        try:
            async with self._start_gate:
                stored = await asyncio.to_thread(self._store.get_run, run_id)
                await asyncio.to_thread(self._store.update_run,
                                        transition_run(stored, RunStatus.RUNNING, at=started_at), expected=stored)
                job = await asyncio.to_thread(self._prepare_scratch, active)
                worker = await self._launcher.launch(job, environ=self._worker_environment(active),
                                                     cwd=self._repo_root)
                active.worker = worker
                _write_worker_file(active.scratch, run_id, worker.pid)
                if active.cancel_requested:
                    # Cancelled between reservation and launch: the marker could not be
                    # written yet, so write it now rather than wait for the grace to expire.
                    self._request_stop(active, FAILURE_CANCELLED)
            # The start gate is free again: a pending run that the dispatcher skipped while
            # this one was starting must be looked at now, not at the next idle timeout.
            self._wake.set()
            self._diagnostics.emit("testlab.run.started", f"Test Lab run {run_id} started", run_id=run_id,
                                   pid=worker.pid, max_duration_s=pending.max_duration_s)
            supervision = await self._supervise(active)
        except (TestLabError, OSError, ValueError) as exc:
            failure = worker_failure(FAILURE_WORKER_SPAWN_FAILED,
                                     failure_detail(f"{type(exc).__name__}: {getattr(exc, 'detail', exc)}"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The backstop for everything supervision itself can raise — today, an
            # injected contention detector failing on the mid-run probe. Without it the
            # task died with "Task exception was never retrieved" on stderr, no
            # diagnostic at any level, and the run concluded `worker_result_invalid`:
            # a supervisor fault recorded against the worker. Loud, and its own code.
            self._diagnostics.emit("testlab.run.supervision_failed",
                                   f"Test Lab supervision of run {run_id} failed", level="error",
                                   run_id=run_id, error=type(exc).__name__,
                                   code=getattr(exc, "code", None), detail=str(exc)[:200])
            failure = worker_failure(FAILURE_SUPERVISOR_FAULT, failure_detail(
                f"the supervisor failed while watching this run ({type(exc).__name__}); "
                "the measurement, if any, is not trustworthy"))
        finally:
            try:
                await self._conclude(active, supervision, failure)
            finally:
                # Synchronous, so a cancellation of this task still frees the resources and
                # wakes the dispatcher. A run whose conclusion was interrupted stays
                # `running` in the store and is finished by the next `start()` adoption.
                self._release(active)

    async def _conclude(self, active: _Active, supervision: _Supervision | None,
                        failure: RunFailure | None) -> None:
        """Stop what is left of the worker and persist the terminal state. Never raises."""
        run_id = active.run_id
        try:
            if active.worker is not None:
                if active.worker.returncode is None:
                    await active.worker.kill_tree()
                # `aclose` releases the containment handle, which also removes anything the
                # worker started and left behind (see `worker_launcher`).
                await active.worker.aclose()
            await self._persist_terminal(active, supervision, failure)
        except Exception as exc:
            # Captured: the run is already over. Losing the diagnostic is better than losing
            # the loop, and the adoption pass finishes the record on the next start.
            self._diagnostics.emit("testlab.run.conclude_failed", f"Test Lab run {run_id} could not be concluded",
                                   level="error", run_id=run_id, error=type(exc).__name__,
                                   code=getattr(exc, "code", None))

    def _release(self, active: _Active) -> None:
        """Free the reservation, forget the run, remove its scratch and wake every waiter."""
        self._reserved -= active.pending.capabilities
        if self._device_lease is not None and needs_device(active.pending.capabilities):
            self._device_lease.release()
        self._active.pop(active.run_id, None)
        self._cleanup_scratch(active.scratch)
        self._finished.setdefault(active.run_id, asyncio.Event()).set()
        self._wake.set()

    async def _supervise(self, active: _Active) -> _Supervision:
        """Watch one worker until it exits, killing it when a bound is crossed."""
        policy = self._policy
        loop = asyncio.get_running_loop()
        worker = active.worker
        assert worker is not None  # set by _execute before this is called
        heartbeat = active.scratch / HEARTBEAT_FILE_NAME
        spawned = loop.time()
        started: float | None = None
        last_beat = spawned
        last_probe = spawned
        seen = 0.0
        waiter = asyncio.ensure_future(worker.wait())
        killed = False
        try:
            while True:
                done, _ = await asyncio.wait({waiter}, timeout=policy.poll_interval_s)
                if done:
                    break
                now = loop.time()
                stamp = _mtime(heartbeat)
                if stamp is not None and stamp > seen:
                    seen, last_beat = stamp, now
                    if started is None:
                        started = now
                        self._diagnostics.emit("testlab.run.progress", f"Test Lab run {active.run_id} is running",
                                               run_id=active.run_id, pid=worker.pid,
                                               elapsed_s=round(now - spawned, 1))
                # Probed from SPAWN, not from the first heartbeat: the reservation is
                # already held while the worker starts, and on a loaded host that window
                # is `startup_timeout_s` (60 s by default) during which the live Jarvis
                # could come back unnoticed. The worker has opened nothing yet, so this
                # is the cheapest moment to give the devices back.
                if (active.stop_reason is None and needs_device(active.pending.capabilities)
                        and now - last_probe >= policy.device_probe_interval_s):
                    last_probe = now
                    contention = await asyncio.to_thread(self._check_contention_during, active)
                    if contention is not None:
                        # The live Jarvis came back while we held the device. Stop at once,
                        # politely first: the measurement is void either way, and a run that
                        # keeps the microphone is exactly what B9 forbids.
                        self._diagnostics.emit("testlab.device.contended",
                                               f"Test Lab run {active.run_id} lost the audio devices",
                                               level="warning", run_id=active.run_id,
                                               started=started is not None)
                        self._request_stop(active, contention.code, contention.detail)
                if started is None:
                    # A stop asked for during startup is acted on here: the worker may not
                    # be able to read the cancel marker yet, so the grace is what ends it.
                    if active.stop_at is not None and now - active.stop_at > policy.cancel_grace_s:
                        killed = True
                        break
                    if now - spawned > policy.startup_timeout_s:
                        active.stop_reason = active.stop_reason or FAILURE_WORKER_STARTUP_TIMEOUT
                        killed = True
                        break
                    continue
                if active.stop_reason is None and now - started > active.pending.max_duration_s:
                    active.stop_reason, active.stop_at = FAILURE_RUN_TIMEOUT, now
                    self._diagnostics.emit("testlab.run.timeout", f"Test Lab run {active.run_id} exceeded its budget",
                                           level="warning", run_id=active.run_id,
                                           max_duration_s=active.pending.max_duration_s)
                if now - last_beat > policy.heartbeat_timeout_s:
                    active.stop_reason = active.stop_reason or FAILURE_WORKER_UNRESPONSIVE
                    killed = True
                    break
                if active.stop_at is not None and now - active.stop_at > policy.cancel_grace_s:
                    killed = True
                    break
        finally:
            if killed:
                await worker.kill_tree()
            exit_code = await _exit_code(waiter)
            if not waiter.done():
                waiter.cancel()
        await asyncio.sleep(0)  # let the stderr pump drain the last lines before reading the tail
        # Read the result AFTER the exit and the kill: a worker that measured just before a
        # heartbeat lapsed has written it by now, and losing those metrics would be a defect.
        result, problem = _read_result(active.scratch, active.run_id)
        return _Supervision(result=result, result_problem=problem, exit_code=exit_code,
                            stop_reason=active.stop_reason, stop_detail=active.stop_detail,
                            killed=killed, stderr_tail=worker.stderr_tail(),
                            started=started is not None)

    def _request_stop(self, active: _Active, reason: str, detail: str | None = None) -> None:
        """Write the cooperative stop marker the worker polls on its heartbeat tick."""
        if active.stop_reason is None:
            active.stop_detail = detail
        active.stop_reason = active.stop_reason or reason
        if active.stop_at is None:
            active.stop_at = asyncio.get_running_loop().time()
        try:
            (active.scratch / CANCEL_FILE_NAME).write_text(
                json.dumps({"run_id": active.run_id, "reason": reason}), encoding="utf-8")
        except OSError as exc:
            # Captured: without the marker the worker cannot stop politely, so the grace
            # will simply expire into the forced kill. The run still ends terminal.
            self._diagnostics.emit("testlab.run.stop_marker_failed",
                                   f"Test Lab run {active.run_id} could not be asked to stop politely",
                                   level="warning", run_id=active.run_id, error=type(exc).__name__)

    # --------------------------------------------------------------- persist

    async def _persist_terminal(self, active: _Active, supervision: _Supervision | None,
                                failure: RunFailure | None) -> None:
        run_id = active.run_id
        stored = await asyncio.to_thread(self._store.get_run, run_id)
        if stored.status in TERMINAL_STATUSES:
            if active.concluded:
                return  # this supervisor already concluded it: a second call is a no-op
            await self._report_out_of_band(active, stored)
            return
        refs = await asyncio.to_thread(self._store_logs, active, supervision)
        finished_at = self._terminal_time(stored)
        if failure is None and supervision is not None:
            status, failure, result = _outcome(supervision)
        else:
            status, result = RunStatus.ERRORED, None
        measured = result if result is not None and result.status is WorkerStatus.MEASURED else None
        if measured is not None and (status is None or supervision is None
                                     or supervision.stop_reason in LIVENESS_REASONS):
            # A complete measurement means the run produced its evidence. A liveness fault
            # around it (silent heartbeat, startup bound) was a false alarm: the metrics decide.
            if await self._store_measured(active, stored, measured, refs, finished_at):
                return
        status = status or RunStatus.ERRORED
        failure = failure or worker_failure(FAILURE_RESULT_INVALID, "the worker ended without a usable result")
        updated = replace(transition_run(stored, status, at=finished_at, failure=failure),
                          artifacts=_merge_refs(stored.artifacts, (*refs, *(measured.artifacts if measured else ()))))
        updated = self._with_evidence(updated, measured, active)
        await asyncio.to_thread(self._store.update_run, updated, expected=stored)
        active.concluded = True
        self._emit_terminal(run_id, status, failure, metrics=len(updated.metrics))

    def _with_evidence(self, run: TestRun, result: WorkerResult | None, active: _Active) -> TestRun:
        """Attach a measurement to a run the supervisor stopped, without changing its status.

        A run killed on its deadline may still have measured something. The status stays
        the supervisor's (`timed_out` reads `timed_out`), but the metrics are evidence and
        are kept — when the declaration accepts them, which `check_run_against_spec` decides.
        """
        if result is None or not result.metrics:
            return run
        try:
            # No score: the declared synthesis of a run the supervisor stopped would compare
            # partial evidence with complete evidence (docs/testlab.md, "Scoring").
            enriched = replace(run, metrics=result.metrics, join_ids=result.join_ids)
            check_run_against_spec(enriched, active.pending.entry.diagnostic)
            return enriched
        except TestLabError as exc:
            # Captured: partial evidence the declaration refuses is dropped, not stored. The
            # terminal status is already correct; the reason the metrics went is recorded.
            self._diagnostics.emit("testlab.run.partial_metrics_dropped",
                                   f"Test Lab run {run.run_id} partial measurements refused", level="warning",
                                   run_id=run.run_id, code=exc.code)
            return run

    async def _store_measured(self, active: _Active, stored: TestRun, result: WorkerResult,
                              refs: tuple[ArtifactRef, ...], finished_at: datetime) -> bool:
        """Derive the verdict from the metrics, then refuse anything the declaration contradicts.

        Returns False when the measurement is not usable at all AND the caller has a
        supervisor reason to fall back to; a contradicted measurement of an otherwise
        finished run is stored as `errored`/`result_contradicts_spec`.
        """
        spec = active.pending.entry.diagnostic
        artifacts = _merge_refs(stored.artifacts, (*refs, *result.artifacts))
        try:
            # The score is computed HERE, from the declaration the run was queued against:
            # the worker measures and never judges (docs/testlab.md, "Scoring").
            completed = complete_run(replace(stored, join_ids=result.join_ids), at=finished_at,
                                     assertion_results=derive_assertion_results(spec, result.metrics),
                                     metrics=result.metrics, score=compute_score(spec.score, result.metrics),
                                     artifacts=artifacts)
            check_run_against_spec(completed, spec)
        except TestLabError as exc:
            if active.stop_reason is not None:
                return False  # the supervisor's own reason is the honest outcome
            failure = worker_failure(FAILURE_RESULT_CONTRADICTS_SPEC, failure_detail(exc.detail))
            refused = replace(transition_run(stored, RunStatus.ERRORED, at=finished_at, failure=failure),
                              artifacts=artifacts)
            await asyncio.to_thread(self._store.update_run, refused, expected=stored)
            active.concluded = True
            self._emit_terminal(stored.run_id, RunStatus.ERRORED, failure)
            return True
        await asyncio.to_thread(self._store.update_run, completed, expected=stored)
        active.concluded = True
        self._emit_terminal(stored.run_id, completed.status, None, score=completed.score)
        return True

    async def _report_out_of_band(self, active: _Active, stored: TestRun) -> None:
        """A terminal record this supervisor never wrote: something concluded the run behind it.

        The store forbids rewriting a terminal record (Slice 02 update rule), so the
        correction is attempted and its refusal is reported with the incident: an
        operator must see that a stored verdict did not come from the supervisor.
        """
        failure = worker_failure(FAILURE_RUN_CONCLUDED_OUT_OF_BAND,
                                 "a terminal record appeared that this supervisor did not write")
        refusal = None
        try:
            await asyncio.to_thread(self._store.update_run,
                                    transition_run(stored, RunStatus.ERRORED, at=self._terminal_time(stored),
                                                   failure=failure), expected=stored)
        except TestLabError as exc:
            refusal = exc.code
        self._diagnostics.emit("testlab.run.concluded_out_of_band",
                               f"Test Lab run {active.run_id} was concluded by something other than its supervisor",
                               level="error", run_id=active.run_id, code=FAILURE_RUN_CONCLUDED_OUT_OF_BAND,
                               stored_status=stored.status.value, correction_refused=refusal)

    def _terminal_time(self, run: TestRun) -> datetime:
        """A terminal time that is never before the run started.

        Clocks are injected and a supervisor adopting another's run may read a time
        earlier than the one that started it. `TestRun` refuses `finished_at` before
        `started_at`, which used to turn adoption into a swallowed write failure, so
        the time is clamped up to the floor rather than the record being lost.
        """
        now = self._clock()
        floor = run.started_at or run.created_at
        return now if now >= floor else floor

    def _emit_terminal(self, run_id: str, status: RunStatus, failure: RunFailure | None, **extra: Any) -> None:
        level = "info" if status in (RunStatus.PASSED, RunStatus.FAILED) else "warning"
        self._diagnostics.emit("testlab.run.finished", f"Test Lab run {run_id} is {status.value}", level=level,
                               run_id=run_id, status=status.value,
                               failure=None if failure is None else failure.code, **extra)

    def _store_logs(self, active: _Active, supervision: _Supervision | None) -> tuple[ArtifactRef, ...]:
        """Commit the worker log and the stderr tail as bounded, redacted artifacts."""
        refs: list[ArtifactRef] = []
        sources = ((active.scratch / WORKER_LOG_NAME, WORKER_LOG_ARTIFACT, None),
                   (active.scratch / STDERR_LOG_NAME, STDERR_LOG_ARTIFACT,
                    None if supervision is None else supervision.stderr_tail))
        for path, name, fallback in sources:
            text = _read_text(path)
            if not text and fallback:
                text = fallback
            if not text:
                continue
            try:
                refs.append(self._store.put_artifact(active.run_id, name, kind=ArtifactKind.WORKER_LOG,
                                                     media_type="text/plain", data=_redact_log(text)))
            except TestLabStoreError as exc:
                # Captured: evidence, not the run. The terminal record is written either way.
                self._diagnostics.emit("testlab.run.artifact_refused", f"Test Lab run {active.run_id} log not stored",
                                       level="warning", run_id=active.run_id, artifact=name, code=exc.code)
        return tuple(refs)

    # ------------------------------------------------------------- refusals

    async def _refuse(self, pending: _Pending, status: RunStatus, failure: RunFailure) -> None:
        try:
            run = await asyncio.to_thread(self._store.get_run, pending.run_id)
            await self._refuse_run(run, status, failure)
        except TestLabError as exc:
            self._diagnostics.emit("testlab.run.refusal_failed", f"Test Lab run {pending.run_id} refusal not stored",
                                   level="error", run_id=pending.run_id, code=exc.code)
        finally:
            self._finished.setdefault(pending.run_id, asyncio.Event()).set()

    async def _refuse_run(self, run: TestRun, status: RunStatus, failure: RunFailure) -> None:
        updated = transition_run(run, status, at=self._terminal_time(run), failure=failure)
        await asyncio.to_thread(self._store.update_run, updated, expected=run)
        self._emit_terminal(run.run_id, status, failure)
        self._finished.setdefault(run.run_id, asyncio.Event()).set()

    # -------------------------------------------------------------- scratch

    def _prepare_scratch(self, active: _Active) -> WorkerJob:
        """Build the per-run scratch: runtime and data roots, the settings copy and the job file."""
        pending = active.pending
        scratch = active.scratch
        check_path_budget(scratch / RUNTIME_DIR_NAME / SETTINGS_FILE_NAME, f"run {pending.run_id}",
                          self.max_path_chars)
        self._make_scratch(scratch, pending.run_id)
        (scratch / RUNTIME_DIR_NAME / SETTINGS_FILE_NAME).write_text(
            json.dumps(pending.settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        job = WorkerJob(
            run_id=pending.run_id, diagnostic_id=pending.entry.diagnostic_id,
            diagnostic_version=pending.entry.version,
            diagnostic_fingerprint=pending.entry.diagnostic.fingerprint(), profile=pending.profile,
            implementation=pending.entry.profiles[pending.profile].implementation.name,
            store_root=str(_store_root(self._store)), scratch_root=str(scratch),
            catalog_root=str(self._catalog_root),
            parameters=pending.parameters, overrides=pending.overrides, scenario=pending.scenario,
            max_duration_s=pending.max_duration_s, allow_audio=pending.allow_audio)
        write_atomic(scratch, JOB_FILE_NAME, canonical_json(job.to_dict()).encode("utf-8"),
                     label=f"run {pending.run_id}", tmp_prefix=JOB_TMP_PREFIX, max_path_chars=self.max_path_chars,
                     replace=replace_with_retry)
        return job

    def _make_scratch(self, scratch: Path, run_id: str) -> None:
        """Create the run's directories, never through a link.

        A run id is used once, so anything already sitting at that path is a leftover
        or a trap: a junction planted at `<run>/runtime` would send the settings copy
        and the job file outside the scratch, before the worker's own guard can run.
        The leftover is removed (a link is removed, never followed, like the Slice 02
        store's sweep), the directories are created fresh, and each one is re-checked.
        """
        if is_link(self._work_root):
            raise SupervisorError(SUPERVISOR_REQUEST_INVALID, "the work root is a link")
        if scratch.exists() or is_link(scratch):
            shutil.rmtree(scratch, ignore_errors=True)
            if scratch.exists() or is_link(scratch):
                raise SupervisorError(SUPERVISOR_REQUEST_INVALID,
                                      f"run {run_id}: its scratch directory already exists and cannot be replaced")
        directories = (scratch, scratch / RUNTIME_DIR_NAME, scratch / DATA_DIR_NAME)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=False)
        for directory in directories:
            if is_link(directory):
                raise SupervisorError(SUPERVISOR_REQUEST_INVALID,
                                      f"run {run_id}: a link appeared inside its scratch directory")

    def _worker_environment(self, active: _Active) -> Mapping[str, str]:
        """The child's environment: run-local roots, no live token, no provider key it may not use."""
        return worker_environment(self._base_environ, active.scratch,
                                  allow_providers=bool(active.pending.capabilities & PROVIDER_CAPABILITIES))

    def _cleanup_scratch(self, scratch: Path) -> None:
        if self._policy.keep_scratch:
            return
        try:
            shutil.rmtree(scratch, ignore_errors=True)
        except OSError:
            # intentional: a scratch directory left behind is removed by the next
            # `start()` adoption sweep, which owns orphan scratch cleanup.
            pass

    # -------------------------------------------------------------- adoption

    async def _adopt_orphans(self) -> AdoptionReport:
        """Finish every run a previous supervisor left, and report exactly what happened to each."""
        found: dict[str, list] = {kind: [] for kind in ("reaped", "elsewhere", "recovered", "failed")}
        known: set[str] = set()
        for run in await asyncio.to_thread(self._list_unfinished):
            known.add(run.run_id)
            outcome, code = await self._adopt_one(run)
            if outcome is _Adoption.ACTIVE:
                found["elsewhere"].append(run.run_id)
            elif outcome is _Adoption.FAILED:
                found["failed"].append((run.run_id, code))
            else:
                found["reaped"].append((run.run_id, code))
                if outcome is _Adoption.RECOVERED:
                    found["recovered"].append(run.run_id)
        return AdoptionReport(tuple(found["reaped"]), tuple(found["elsewhere"]), tuple(found["recovered"]),
                              tuple(found["failed"]), self._remove_orphan_scratch(known))

    def _list_unfinished(self) -> tuple[TestRun, ...]:
        found: list[TestRun] = []
        cursor: str | None = None
        while True:
            page = self._store.list_runs(RunQuery(statuses=frozenset({RunStatus.QUEUED, RunStatus.RUNNING}),
                                                  limit=MAX_PAGE_LIMIT, after_run_id=cursor))
            found.extend(page.runs)
            cursor = page.next_cursor
            if cursor is None:
                return tuple(found)

    async def _adopt_one(self, run: TestRun) -> tuple[_Adoption, str]:
        """Finish one run left by a dead supervisor, and say what actually happened to it.

        The worker lock is the liveness test: the OS releases it when the holder
        dies, so acquiring it proves no worker is running this id. A held lock is
        never forced and the process behind it is never killed by pid (pids are
        reused); the run is reported as `active_elsewhere` instead. A run the store
        refused is reported `failed` with the refusal code, never as reaped.
        """
        scratch = self._work_root / run.run_id
        try:
            with EntryLock(scratch / WORKER_LOCK_NAME, f"run {run.run_id}", self._policy.adopt_lock_timeout_s):
                result, _ = _read_result(scratch, run.run_id)
        except TestLabStoreError:
            self._diagnostics.emit("testlab.run.active_elsewhere",
                                   f"Test Lab run {run.run_id} still has a live worker", level="warning",
                                   run_id=run.run_id, code=FAILURE_WORKER_ACTIVE_ELSEWHERE)
            return _Adoption.ACTIVE, FAILURE_WORKER_ACTIVE_ELSEWHERE
        entry = self._entry_or_none(run)
        if result is not None and run.status is RunStatus.RUNNING and entry is not None:
            supervision = _Supervision(result, result_problem=None, exit_code=None, stop_reason=None,
                                       stop_detail=None,
                                       killed=False, stderr_tail="", started=True)
            await self._conclude(_Active(_orphan_pending(run, entry), scratch), supervision, None)
            stored = await asyncio.to_thread(self._store.get_run, run.run_id)
            self._cleanup_scratch(scratch)
            if stored.status in TERMINAL_STATUSES:
                return _Adoption.RECOVERED, stored.failure.code if stored.failure else stored.status.value
            return _Adoption.FAILED, "conclusion_not_stored"
        code = FAILURE_WORKER_LOST if run.status is RunStatus.RUNNING else FAILURE_RUN_ABANDONED
        failure = worker_failure(code, "no worker holds this run and the supervisor that queued it is gone")
        try:
            await self._refuse_run(run, RunStatus.ERRORED, failure)
        except TestLabError as exc:
            # Captured, and reported as `failed`: a report that claimed this run was
            # reaped while it is still `running` is what hid this defect the first time.
            self._diagnostics.emit("testlab.run.adoption_failed", f"Test Lab run {run.run_id} could not be reaped",
                                   level="error", run_id=run.run_id, code=exc.code)
            return _Adoption.FAILED, exc.code
        self._cleanup_scratch(scratch)
        return _Adoption.REAPED, code

    def _entry_or_none(self, run: TestRun) -> CatalogEntry | None:
        try:
            return self._catalog.describe(run.diagnostic_id, run.diagnostic_version)
        except TestLabError:
            return None  # the declaration is gone from this catalog; the run is reaped instead

    def _remove_orphan_scratch(self, known: Iterable[str]) -> int:
        """Remove scratch directories of runs that are no longer active anywhere."""
        keep = set(known)
        removed = 0
        try:
            entries = list(os.scandir(self._work_root))
        except FileNotFoundError:
            return 0  # intentional: nothing ever ran here
        except OSError:
            return 0
        for entry in entries:
            if entry.name in keep or not entry.is_dir(follow_symlinks=False):
                continue
            shutil.rmtree(entry.path, ignore_errors=True)
            removed += 1
        return removed

    # ------------------------------------------------------------ maintenance

    async def _maintenance_loop(self) -> None:
        while not self._closing:
            await asyncio.sleep(self._policy.maintenance.interval_s)
            await self.maintain()

    async def maintain(self) -> MaintenanceReport | None:
        """One upkeep pass, or None when a run is active (upkeep never races a writer).

        The pass holds the start gate, so a run submitted meanwhile starts as soon as
        the pass ends — which is why a sweep must stay short. The dispatcher is woken
        on the way out, so that run never waits for the idle poll.
        """
        policy = self._policy.maintenance
        if not policy.enabled or self._active or self._start_gate.locked():
            return None
        try:
            async with self._start_gate:
                if self._active:
                    return None
                report = await asyncio.to_thread(run_maintenance_pass, self._store, policy, now=self._clock(),
                                                 active_run_ids=(*self._active, *self.pending_run_ids))
        finally:
            self._wake.set()
        self._diagnostics.emit("testlab.maintenance.pass", "Test Lab store upkeep pass", swept=report.swept,
                               deleted=len(report.retention.deleted) if report.retention else 0,
                               skipped_active=len(report.skipped_active), sweep_error=report.sweep_error)
        return report


# ---------------------------------------------------------------- helpers

def _utc_now() -> datetime:
    return to_event_time(datetime.now(timezone.utc))


def _snapshot(settings: Mapping[str, Any]) -> ConfigSnapshot:
    try:
        return build_config_snapshot(settings)
    except TestLabError as exc:
        raise SupervisorError(SUPERVISOR_REQUEST_INVALID,
                              f"the effective configuration cannot be snapshotted ({exc.code})") from None


def apply_overrides(document: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Run-local settings: `document` plus each override, addressed by its dotted name.

    A name that already exists as a top-level key sets that key (flat keys with a dot
    in them are how `control-center-settings.json` names voice settings today); any
    other dotted name descends, creating the objects it needs. The input document is
    never modified: this returns a new one, which is what gets written to the COPY.
    """
    result = json.loads(json.dumps(dict(document)))
    for name, value in overrides.items():
        if name in result or "." not in name:
            result[name] = value
            continue
        head, *rest = name.split(".")
        target = result
        for segment in [head, *rest[:-1]]:
            nested = target.get(segment)
            if not isinstance(nested, dict):
                nested = {}
                target[segment] = nested
            target = nested
        target[rest[-1]] = value
    return result


def worker_environment(base: Mapping[str, str], scratch: Path, *, allow_providers: bool) -> dict[str, str]:
    """The environment of one worker: run-local roots, no live token, provider keys gated.

    `JARVIS_RUNTIME_DIR` and `JARVIS_DATA_ROOT` are the seam READINESS B4.2 named:
    `V2Settings.load()` resolves them, so every path the worker derives lands in the
    run scratch. The worker refuses to start if they do not (`check_isolation`).
    """
    environ = dict(base)
    for name in INHERITED_ENV_OVERRIDES:
        environ.pop(name, None)
    environ["JARVIS_RUNTIME_DIR"] = str(Path(scratch) / RUNTIME_DIR_NAME)
    environ["JARVIS_DATA_ROOT"] = str(Path(scratch) / DATA_DIR_NAME)
    environ["JARVIS_TESTLAB_RUN_SCRATCH"] = str(scratch)
    environ["JARVIS_TESTLAB_WORKER"] = "1"
    environ["PYTHONIOENCODING"] = "utf-8"
    if not allow_providers:
        environ["JARVIS_TESTLAB_NO_PROVIDERS"] = "1"
        for name in PROVIDER_ENV_NAMES:
            environ[name] = ""
    return environ


def derive_assertion_results(spec: DiagnosticSpec, metrics: Mapping[str, Any]) -> tuple[AssertionResult, ...]:
    """Every declared assertion, evaluated against the reported metrics.

    The worker never sends results: they are derived here, from the declaration the
    run was queued against, so a verdict cannot be forged by a runner.
    """
    index = spec.metric_index
    return tuple(evaluate_assertion(assertion, index[assertion.metric], metrics.get(assertion.metric))
                 for assertion in spec.assertions)


def _denial_detail(decision: PermissionDecision) -> str:
    return failure_detail("refused by the resource grant: "
                   + ", ".join(denial.reason.value + (f" {denial.capability.value}" if denial.capability else "")
                               for denial in decision.denials))


def _capability_names(capabilities: Iterable[Capability]) -> str:
    names = sorted(item.value for item in capabilities)
    return ", ".join(names) if names else "a free slot"


def _outcome(supervision: _Supervision) -> tuple[RunStatus | None, RunFailure | None, WorkerResult | None]:
    """Terminal status and failure of a finished worker. The supervisor's own reason wins.

    A run the supervisor timed out is `timed_out` even if the worker managed to
    write another code, so the record says what actually stopped the run. The
    result is always returned with it: even a stopped run's measurements are
    evidence (`_with_evidence`), and a liveness fault around a complete
    measurement is a false alarm (`LIVENESS_REASONS`).
    """
    result = supervision.result
    if supervision.stop_reason is not None:
        status = TERMINAL_BY_FAILURE.get(supervision.stop_reason, RunStatus.ERRORED)
        detail = supervision.stop_detail or (
            "the supervisor stopped this run" + (" and killed its process tree" if supervision.killed else ""))
        return status, worker_failure(supervision.stop_reason, detail), result
    if result is not None:
        if result.status is WorkerStatus.MEASURED:
            return None, None, result  # the status comes from the assertions, in `_store_measured`
        failure = result.failure or worker_failure(FAILURE_RESULT_INVALID, "a failed result carries no failure")
        return TERMINAL_BY_FAILURE.get(failure.code, RunStatus.ERRORED), failure, None
    if supervision.result_problem not in (None, RESULT_MISSING):
        return RunStatus.ERRORED, worker_failure(
            FAILURE_RESULT_INVALID, f"the worker's result file is {supervision.result_problem}"), None
    return RunStatus.ERRORED, worker_failure(
        FAILURE_WORKER_CRASHED, f"the worker exited without a result ({_exit_label(supervision.exit_code)})"), None


def _exit_label(code: int | None) -> str:
    """English description of a worker exit, from the canonical decoder's facts.

    `describe_exit_code` owns the NTSTATUS table and the native-crash rule, but its
    label is French; failure details are English, so only its facts are used here.
    """
    if code is None:
        return "no exit code"
    described = describe_exit_code(code)
    status = described.get("ntstatus")
    signal_name = described.get("signal")
    parts = [f"exit code {code}"]
    if status:
        parts.append(f"NTSTATUS {status}")
    if signal_name:
        parts.append(f"signal {signal_name}")
    if described.get("native_crash"):
        parts.append("native crash")
    return ", ".join(parts)


def _merge_refs(stored: tuple[ArtifactRef, ...], added: Iterable[ArtifactRef]) -> tuple[ArtifactRef, ...]:
    """Stored references first (they may never be removed), then new paths, once each."""
    merged = {ref.path: ref for ref in stored}
    for ref in added:
        merged.setdefault(ref.path, ref)
    return tuple(merged.values())


def _read_result(scratch: Path, run_id: str) -> tuple[WorkerResult | None, str | None]:
    """The run's result, or why there is none. A corrupt file is never "no result".

    `(result, None)` when it decodes; `(None, problem)` otherwise, where `problem` is
    one of `RESULT_MISSING`, `unreadable`, `invalid` or `for another run`. The caller
    turns anything but `missing` into `worker_result_invalid`: a truncated or edited
    result is a defect to see, not a crash to infer.
    """
    try:
        text = (Path(scratch) / RESULT_FILE_NAME).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None, RESULT_MISSING  # a worker that died before writing has no result: that is the answer
    except (OSError, UnicodeError):
        return None, "unreadable"
    try:
        result = WorkerResult.from_dict(decode_json_document(text))
    except TestLabError:
        return None, "invalid"
    return (result, None) if result.run_id == run_id else (None, "for another run")


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""  # intentional: a missing log is normal (a worker that never started)


def _mtime(path: Path) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None  # intentional: no heartbeat yet is the normal state before the worker starts


async def _exit_code(waiter: asyncio.Future[int]) -> int | None:
    try:
        return await asyncio.wait_for(asyncio.shield(waiter), timeout=5.0)
    except (asyncio.TimeoutError, asyncio.CancelledError, ProcessLookupError):
        return None


def _write_worker_file(scratch: Path, run_id: str, pid: int) -> None:
    try:
        (Path(scratch) / WORKER_FILE_NAME).write_text(
            json.dumps({"run_id": run_id, "pid": pid, "supervisor_pid": os.getpid()}), encoding="utf-8")
    except OSError:
        # intentional: the pid file is for a human reading the scratch. Liveness is decided
        # by the worker lock, which the OS maintains, not by this file.
        pass


def _store_root(store: TestRunStore) -> Path:
    root = getattr(store, "root", None)
    if root is None:
        raise SupervisorError(SUPERVISOR_REQUEST_INVALID,
                              "the run store has no root directory; a worker cannot open it")
    return Path(root)


def _orphan_pending(run: TestRun, entry: CatalogEntry) -> _Pending:
    """A pending record rebuilt from a stored run, to conclude it from its result file."""
    return _Pending(run_id=run.run_id, entry=entry, profile=run.profile, capabilities=frozenset(),
                    parameters=run.parameters, overrides=run.overrides, scenario=None, settings={},
                    max_duration_s=1.0, queued_at=0.0)
