"""Composition root of the Category 2 Test Lab: one place that builds the whole subsystem.

Binding contract: `docs/testlab.md` ("Native API, CLI and HTTP"). Slices 01-09 built
every piece and deliberately left them unwired: the run store took an injected root, the
supervisor took an injected work root, catalog root, settings path and diagnostics sink,
and nothing decided where any of them lived. This module decides, once, for the script,
the CLI (`python -m jarvis.testlab`) and the Control Center alike, so the three surfaces
cannot disagree about which store they are reading.

Layout, all under `<runtime>/testlab/` (gitignored, never `data/state/jarvis.sqlite3`)::

    <runtime>/testlab/runs/<run_id>/     run records and artifacts   (Slice 02)
    <runtime>/testlab/sweeps/<id>/       sweep records and summaries (Slice 07)
    <runtime>/testlab/bundles/<id>/      DiagnosticBundles           (Slice 03)
    <runtime>/testlab/locks/             per-entry writer locks (ids are prefixed, so
                                         runs, sweeps and bundles share this directory)
    <runtime>/testlab/work/              supervisor work root: one scratch per run, the
                                         work-root lock and the device lease (Slice 05)

The work root is a SEPARATE directory on purpose: `RunSupervisor` treats every directory
directly under it as a run scratch and removes the ones no live run claims, which would
delete `runs/` on the first `start()` if the two roots were the same path.

Nothing is created until first use. Building a `TestLab` reads no file and makes no
directory; the stores create theirs on the first write and the catalog is loaded on the
first access.

**Where a capability grant comes from.** Never from a request, and never from an HTTP
body or a CLI flag: a caller that can grant itself `realtime_provider` has no gate left.
The grant is read HERE, from the supervisor process's own environment, using the same
opt-in switches the supervisor already enforces in its reservation path
(`JARVIS_TESTLAB_LIVE`, `JARVIS_TESTLAB_GUIDED`) plus `JARVIS_TESTLAB_HARDWARE` for the
two device capabilities. Setting an environment variable for the process is the
operator's act, it is visible in the process that will spend the money or take the
microphone, and it gives the CLI and the Control Center the same authority by
construction. A caller may only NARROW the grant (`TestLabApi.submit_run(grant=...)`
intersects, it never widens).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import os
from pathlib import Path
from typing import Any

from jarvis.ports.v2 import DiagnosticSink
from jarvis.testlab.catalog import Catalog, DEFAULT_CATALOG_ROOT, load_catalog
from jarvis.testlab.devices import DeviceContentionDetector, default_contention_detector
from jarvis.testlab.filesystem_bundle_store import FilesystemBundleStore
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.filesystem_sweep_store import FilesystemSweepStore
from jarvis.testlab.hardware.prompts import GUIDED_OPT_IN_ENV, guided_opt_in
from jarvis.testlab.live.session import LIVE_OPT_IN_ENV, live_opt_in
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.profiles import MAX_PROFILE_COST_USD, Capability, ResourceGrant
from jarvis.testlab.retention import TestLabRetentionPolicy
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.store import ArtifactWriteLimits
from jarvis.testlab.supervisor import (
    AdoptionReport,
    REPO_ROOT,
    RunSupervisor,
    SETTINGS_FILE_NAME,
    SupervisorPolicy,
)
from jarvis.testlab.sweep_runner import SweepPolicy, SweepRunner
from jarvis.testlab.validation import TestLabError, fail
from jarvis.testlab.worker_launcher import WorkerLauncher

#: Directory of the whole Test Lab inside the runtime root.
TESTLAB_DIR_NAME = "testlab"
#: The supervisor work root, beside the stores and never equal to them (see the module docstring).
WORK_DIR_NAME = "work"
#: Where the live Jarvis writes its voice session reports (Slice 03 reads them for a bundle).
VOICE_REPORTS_DIR = Path("benchmarks") / "voice-sessions"
#: The live `RuntimeJournal` trace, the journal half of a DiagnosticBundle.
TRACE_FILE_NAME = "trace.jsonl"
#: Core's state database, read STRICTLY read-only when a bundle asks for Conversation Events.
STATE_DATABASE = Path("state") / "jarvis.sqlite3"

#: Operator opt-in for the two audio device capabilities. There is no product switch for
#: a device (the supervisor gates devices by contention detection and a lease, not by an
#: environment variable), so this is the composition layer's own name, in the same family
#: as the two it reuses, and off by default like them.
HARDWARE_OPT_IN_ENV = "JARVIS_TESTLAB_HARDWARE"
#: Lets stored runs keep `audio_clip` artifacts. Off by default: raw audio is the one
#: artifact kind that can carry a voice, and the store refuses the write without it.
AUDIO_ARTIFACTS_ENV = "JARVIS_TESTLAB_AUDIO_ARTIFACTS"
#: Money the operator authorizes for ONE run, in US dollars. Absent or unreadable: 0.
MAX_COST_ENV = "JARVIS_TESTLAB_MAX_COST_USD"

COMPOSITION_INVALID = "testlab_composition_invalid"


def _flag(environ: Mapping[str, str], name: str) -> bool:
    return environ.get(name) == "1"


def _max_cost_usd(environ: Mapping[str, str]) -> tuple[float, str | None]:
    """`(budget, refusal)`: the authorized per-run budget, and why it is not what was written.

    Reading this must never raise. Refusing to build the whole Test Lab over a mistyped
    budget would take the CLI away exactly when somebody is trying to look at a run — and
    since `install_testlab_routes` is called from `ControlCenter.__init__`, it would stop
    the Control Center itself from being constructed. So every unusable value falls back
    to a usable one, in the refusing direction, and says so:

    - unreadable, negative or not a number -> `0`, which refuses a paid run;
    - above `MAX_PROFILE_COST_USD` -> clamped to that bound, which `ResourceGrant`
      would otherwise reject outright.
    """
    raw = environ.get(MAX_COST_ENV)
    if raw is None:
        return 0.0, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0, f"{MAX_COST_ENV} is not a number; the per-run budget is 0"
    if value != value or value < 0 or value == float("inf"):
        return 0.0, f"{MAX_COST_ENV} is not a usable amount; the per-run budget is 0"
    if value > MAX_PROFILE_COST_USD:
        return float(MAX_PROFILE_COST_USD), (f"{MAX_COST_ENV} is above the {MAX_PROFILE_COST_USD} USD "
                                             f"ceiling a run may declare; it was clamped to it")
    return value, None


def read_environment_grant(environ: Mapping[str, str] | None = None) -> tuple[ResourceGrant, str | None]:
    """`(grant, refusal)` from the PROCESS environment (never a request).

    - `JARVIS_TESTLAB_LIVE=1` -> `realtime_provider`, `llm_provider`
    - `JARVIS_TESTLAB_HARDWARE=1` -> `audio_input_device`, `audio_output_device`
    - `JARVIS_TESTLAB_GUIDED=1` -> `human_presence`
    - `JARVIS_TESTLAB_MAX_COST_USD` -> the per-run money budget (default 0)

    The default grant is empty, which is exactly the `virtual` profile: free, no device,
    no provider, no human. Everything else is a deliberate act by whoever started the
    process.

    Total by construction: a value the domain still refuses leaves an EMPTY grant and a
    sentence saying why, which `status` shows and the CLI prints. One environment
    variable must not be able to take the Test Lab, or the Control Center, away.
    """
    source = os.environ if environ is None else environ
    capabilities: set[Capability] = set()
    if live_opt_in(source):
        capabilities |= {Capability.REALTIME_PROVIDER, Capability.LLM_PROVIDER}
    if _flag(source, HARDWARE_OPT_IN_ENV):
        capabilities |= {Capability.AUDIO_INPUT_DEVICE, Capability.AUDIO_OUTPUT_DEVICE}
    if guided_opt_in(source):
        capabilities.add(Capability.HUMAN_PRESENCE)
    budget, refusal = _max_cost_usd(source)
    try:
        return ResourceGrant(frozenset(capabilities), max_cost_usd=budget), refusal
    except TestLabError as exc:
        # Captured and REPORTED, never silent: a future bound this layer does not know
        # about must not be able to stop the Test Lab from being built.
        return ResourceGrant(), f"the environment grant was refused ({exc.code}); no capability is granted"


def environment_grant(environ: Mapping[str, str] | None = None) -> ResourceGrant:
    """The grant alone, for a caller that does not need the refusal sentence."""
    return read_environment_grant(environ)[0]


def narrow_grant(granted: ResourceGrant, asked: ResourceGrant | None) -> ResourceGrant:
    """`asked` intersected with what the environment authorized: a caller can only narrow.

    This is the one rule that makes the HTTP surface safe to expose: a request body may
    carry a grant, and the worst it can do is ask for less than the operator allowed.
    """
    if asked is None:
        return granted
    if not isinstance(asked, ResourceGrant):
        raise fail("grant must be a ResourceGrant")
    return ResourceGrant(
        capabilities=asked.capabilities & granted.capabilities,
        max_cost_usd=min(asked.max_cost_usd, granted.max_cost_usd),
        max_duration_s=(granted.max_duration_s if asked.max_duration_s is None
                        else min(asked.max_duration_s, granted.max_duration_s)
                        if granted.max_duration_s is not None else asked.max_duration_s))


@dataclass(frozen=True, slots=True)
class TestLabConfig:
    """Every path, policy and authorization the Test Lab is built from. Pure data.

    Built by `from_environment()` in production and constructed directly by a test or a
    script that wants a temporary root.
    """

    __test__ = False  # not a pytest test class, despite the name

    #: `<runtime>/testlab`: the three stores share it (their ids carry distinct prefixes).
    root: Path
    #: `<runtime>/testlab/work`: one scratch per run. Never equal to `root`.
    work_root: Path
    #: The LIVE runtime directory. The contention detector reads its voice signals, and
    #: `settings_path` inside it is the settings file a run COPIES (never writes).
    runtime_root: Path
    data_root: Path
    repo_root: Path = REPO_ROOT
    catalog_root: Path = DEFAULT_CATALOG_ROOT
    grant: ResourceGrant = field(default_factory=ResourceGrant)
    policy: SupervisorPolicy = field(default_factory=SupervisorPolicy)
    sweep_policy: SweepPolicy = field(default_factory=SweepPolicy)
    artifact_limits: ArtifactWriteLimits = field(default_factory=ArtifactWriteLimits)
    #: Add the native PortAudio reachability probe to the contention detector. Off by
    #: default (Slice 09 offered it and declined to wire it): it costs a native query on
    #: every device reservation, and it only says anything for a device run.
    probe_audio_backend: bool = False
    #: Why the environment grant is not what the environment asked for (a budget above the
    #: ceiling, a value the domain refuses). None when it is exactly what was written.
    #: Shown by `status` and printed by the CLI: a grant quietly reduced is a surprise
    #: waiting to be blamed on the diagnostic.
    grant_refusal: str | None = None

    def __post_init__(self) -> None:
        for name in ("root", "work_root", "runtime_root", "data_root", "repo_root", "catalog_root"):
            value = getattr(self, name)
            if not isinstance(value, Path):
                object.__setattr__(self, name, Path(value))
        if self.work_root == self.root:
            raise TestLabError(COMPOSITION_INVALID,
                               "the supervisor work root must not be the store root: the supervisor removes "
                               "every directory under its work root that no live run claims")
        if not isinstance(self.grant, ResourceGrant):
            raise fail("config.grant must be a ResourceGrant")
        if not isinstance(self.policy, SupervisorPolicy):
            raise fail("config.policy must be a SupervisorPolicy")
        if not isinstance(self.sweep_policy, SweepPolicy):
            raise fail("config.sweep_policy must be a SweepPolicy")
        if not isinstance(self.artifact_limits, ArtifactWriteLimits):
            raise fail("config.artifact_limits must be ArtifactWriteLimits")
        if type(self.probe_audio_backend) is not bool:
            raise fail("config.probe_audio_backend must be a boolean")
        if self.grant_refusal is not None and not isinstance(self.grant_refusal, str):
            raise fail("config.grant_refusal must be a sentence or None")

    @property
    def settings_path(self) -> Path:
        """The permanent Control Center settings file. Read and copied per run, never written."""
        return self.runtime_root / SETTINGS_FILE_NAME

    @property
    def trace_path(self) -> Path:
        return self.runtime_root / TRACE_FILE_NAME

    @property
    def reports_directory(self) -> Path:
        return self.runtime_root / VOICE_REPORTS_DIR

    @property
    def state_database(self) -> Path:
        return self.data_root / STATE_DATABASE

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, *,
                         runtime_root: Path | str | None = None, data_root: Path | str | None = None,
                         retention: TestLabRetentionPolicy | None = None,
                         **overrides: Any) -> TestLabConfig:
        """Resolve the roots from `V2Settings` / `JARVIS_RUNTIME_DIR` and the grant from the environment.

        `runtime_root` and `data_root` override the resolved ones (the Control Center
        already knows its runtime root and passes it, rather than re-reading the
        environment of a process a worker may have changed).
        """
        source = dict(os.environ if environ is None else environ)
        resolved_runtime, resolved_data = _roots(source, runtime_root, data_root)
        root = Path(resolved_runtime) / TESTLAB_DIR_NAME
        granted, refusal = read_environment_grant(source)
        policy = overrides.pop("policy", None)
        if policy is None:
            policy = SupervisorPolicy(maintenance=MaintenancePolicy(
                retention=retention if retention is not None else TestLabRetentionPolicy()))
        elif retention is not None:
            policy = replace(policy, maintenance=replace(policy.maintenance, retention=retention))
        return cls(root=root, work_root=root / WORK_DIR_NAME, runtime_root=resolved_runtime,
                   data_root=resolved_data, grant=overrides.pop("grant", None) or granted,
                   grant_refusal=refusal, policy=policy,
                   artifact_limits=overrides.pop("artifact_limits", None) or ArtifactWriteLimits(
                       allow_audio=_flag(source, AUDIO_ARTIFACTS_ENV)),
                   probe_audio_backend=overrides.pop("probe_audio_backend", _flag(source, HARDWARE_OPT_IN_ENV)),
                   **overrides)

    def to_dict(self) -> dict[str, Any]:
        """What `testlab status` and `GET /api/testlab/status` show about this composition.

        Paths are shown with the home directory as `~`: this document is served to a
        browser and printed by agents, and the absolute form carries the account name.
        """
        return {"root": display_path(self.root), "work_root": display_path(self.work_root),
                "runtime_root": display_path(self.runtime_root), "catalog_root": display_path(self.catalog_root),
                "settings_path": display_path(self.settings_path), "trace_path": display_path(self.trace_path),
                "grant": self.grant.to_dict(), "grant_refusal": self.grant_refusal,
                "allow_audio_artifacts": self.artifact_limits.allow_audio,
                "probe_audio_backend": self.probe_audio_backend,
                "opt_ins": {LIVE_OPT_IN_ENV: Capability.REALTIME_PROVIDER in self.grant.capabilities,
                            HARDWARE_OPT_IN_ENV: Capability.AUDIO_INPUT_DEVICE in self.grant.capabilities,
                            GUIDED_OPT_IN_ENV: Capability.HUMAN_PRESENCE in self.grant.capabilities},
                "max_concurrent_runs": self.policy.max_concurrent_runs,
                "retention_enabled": self.policy.maintenance.retention.enabled}


def display_path(path: Path) -> str:
    """A path with the home directory written `~`, for a document a browser or an agent reads.

    Best effort and never raising: the absolute form is still returned when there is no
    home to strip, because an operator needs a path they can actually open.
    """
    text = str(path)
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        return text
    if home and text.lower().startswith(home.lower()):
        return "~" + text[len(home):]
    return text


def _roots(environ: Mapping[str, str], runtime_root: Path | str | None,
           data_root: Path | str | None) -> tuple[Path, Path]:
    """`(runtime_root, data_root)`, from the arguments then `JARVIS_RUNTIME_DIR` / `JARVIS_DATA_ROOT`.

    The same defaults as `V2Settings.load()` (`./runtime`, `./data`), read from the given
    mapping rather than the process environment so a caller can compose a Test Lab for
    another root without mutating `os.environ`.
    """
    runtime = (Path(runtime_root) if runtime_root is not None
               else Path(environ.get("JARVIS_RUNTIME_DIR", "./runtime")))
    data = Path(data_root) if data_root is not None else Path(environ.get("JARVIS_DATA_ROOT", "./data"))
    return runtime.expanduser().resolve(), data.expanduser().resolve()


class TestLab:
    """The composed Test Lab: stores, catalog, supervisor and sweep runner, built lazily.

    ONE store instance is shared by everything (the Slice 07 listing cache is per
    instance, so a second one would answer from cold disk and the two could disagree
    about a record that became corrupt). Construction touches no file; `start()` takes
    the work root, adopts whatever a previous supervisor left and begins dispatching.
    """

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, config: TestLabConfig, *, diagnostics: DiagnosticSink | None = None,
                 launcher: WorkerLauncher | None = None, contention: DeviceContentionDetector | None = None,
                 catalog: Catalog | None = None) -> None:
        if not isinstance(config, TestLabConfig):
            raise fail("TestLab takes a TestLabConfig")
        self._config = config
        self._diagnostics = diagnostics
        self._launcher = launcher
        self._contention = contention
        self._store: FilesystemTestRunStore | None = None
        self._sweep_store: FilesystemSweepStore | None = None
        self._bundle_store: FilesystemBundleStore | None = None
        self._catalog = catalog
        self._supervisor: RunSupervisor | None = None
        self._sweep_runner: SweepRunner | None = None
        self._started = False

    @property
    def config(self) -> TestLabConfig:
        return self._config

    @property
    def diagnostics(self) -> DiagnosticSink | None:
        return self._diagnostics

    @property
    def started(self) -> bool:
        return self._started

    # ------------------------------------------------------------------ pieces

    @property
    def store(self) -> FilesystemTestRunStore:
        """The one run store instance. Everything reads and writes through it."""
        if self._store is None:
            self._store = FilesystemTestRunStore(self._config.root, limits=self._config.artifact_limits,
                                                 diagnostics=self._diagnostics)
        return self._store

    @property
    def sweep_store(self) -> FilesystemSweepStore:
        if self._sweep_store is None:
            self._sweep_store = FilesystemSweepStore(self._config.root, diagnostics=self._diagnostics)
        return self._sweep_store

    @property
    def bundle_store(self) -> FilesystemBundleStore:
        if self._bundle_store is None:
            self._bundle_store = FilesystemBundleStore(self._config.root, diagnostics=self._diagnostics)
        return self._bundle_store

    @property
    def catalog(self) -> Catalog:
        """The official catalog, loaded once. Supervisor and workers resolve the same registry."""
        if self._catalog is None:
            self._catalog = load_catalog(self._config.catalog_root, implementations=catalog_implementations(),
                                         sink=self._diagnostics)
        return self._catalog

    @property
    def contention(self) -> DeviceContentionDetector:
        """The device-contention detector. Without the hardware opt-in, the file probes only."""
        if self._contention is None:
            self._contention = self._build_contention()
        return self._contention

    def _build_contention(self) -> DeviceContentionDetector:
        if not self._config.probe_audio_backend:
            return default_contention_detector(self._config.runtime_root)
        # Imported here and not at module scope: `hardware.devices` pulls in
        # `jarvis.runtime.audio_devices` and through it `sounddevice`, which must not be
        # a cost of listing runs or reading a bundle from the CLI.
        from jarvis.testlab.hardware.devices import hardware_contention_detector

        return hardware_contention_detector(self._config.runtime_root)

    @property
    def supervisor(self) -> RunSupervisor:
        if self._supervisor is None:
            config = self._config
            self._supervisor = RunSupervisor(
                store=self.store, work_root=config.work_root, catalog=self.catalog,
                catalog_root=config.catalog_root, policy=config.policy, launcher=self._launcher,
                repo_root=config.repo_root, settings_path=config.settings_path,
                diagnostics=self._diagnostics, contention=self.contention)
        return self._supervisor

    @property
    def sweep_runner(self) -> SweepRunner:
        if self._sweep_runner is None:
            self._sweep_runner = SweepRunner(supervisor=self.supervisor, store=self.sweep_store,
                                             policy=self._config.sweep_policy, diagnostics=self._diagnostics)
        return self._sweep_runner

    # --------------------------------------------------------------- lifecycle

    async def start(self) -> AdoptionReport:
        """Take the work root, adopt orphan runs and start dispatching (idempotent)."""
        if self._started:
            return AdoptionReport()
        report = await self.supervisor.start()
        self._started = True
        return report

    async def aclose(self) -> None:
        """Stop every running worker and release the work root (idempotent)."""
        if not self._started:
            return
        self._started = False
        await self.supervisor.aclose()

    async def __aenter__(self) -> TestLab:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def build_test_lab(environ: Mapping[str, str] | None = None, *, runtime_root: Path | str | None = None,
                   data_root: Path | str | None = None, diagnostics: DiagnosticSink | None = None,
                   **overrides: Any) -> TestLab:
    """The one-line composition a script, the CLI and the Control Center all use."""
    return TestLab(TestLabConfig.from_environment(environ, runtime_root=runtime_root, data_root=data_root,
                                                 **overrides),
                   diagnostics=diagnostics)
