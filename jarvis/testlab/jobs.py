"""Test Lab worker protocol: the job the supervisor writes, the result the worker writes.

Binding contract: `docs/testlab.md` ("Supervisor and workers"). Pure: strict
codecs, the closed failure-code vocabulary and the names of the per-run protocol
files. No I/O, no clock: `jarvis.testlab.supervisor` and `jarvis.testlab.worker`
do the reading and writing.

Why files and not a pipe: the result must survive the death of either process. A
pipe dies with the worker, so a supervisor that crashed mid-run would find
nothing to adopt, while `result.json` is still on disk. This is the isolated
one-shot idiom of `jarvis/runtime/speaker_benchmark.py::_run_isolated`
(READINESS B3), with the job also written as a file so the command line carries
no run data.

The worker reports MEASUREMENTS, never a verdict: `metrics`, the join ids it
observed and the artifacts it wrote. The supervisor derives every
`AssertionResult` from those metrics with `evaluate_assertion`, computes the
declared score with `jarvis.testlab.scoring`, and checks the completed run with
`check_run_against_spec`, so a worker cannot declare itself passed.

`WorkerResult` carries NO score (Slice 07). It used to declare one that nothing
ever computed; a field the supervisor would have to ignore is dead contract data
and a way for a runner to publish a judgement it has no declaration to justify.
The score is now derived where the declaration lives, in the supervisor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from jarvis.testlab.diagnostics import MAX_METRICS, freeze_scalar_map
from jarvis.testlab.identity import (
    TESTLAB_SCHEMA_VERSION,
    check_diagnostic_id,
    check_diagnostic_version,
    check_run_id,
)
from jarvis.testlab.profiles import MAX_IMPLEMENTATION_CHARS, ProfileName
from jarvis.testlab.runs import MAX_ARTIFACTS, MAX_OVERRIDES, ArtifactRef, RunFailure
from jarvis.testlab.scenarios import SHAPE_ONLY, Scenario
from jarvis.testlab.validation import (
    LIMIT_EXCEEDED,
    SIMPLE_NAME,
    check_document_header,
    check_enum,
    check_hex,
    check_name,
    check_number,
    check_text,
    decode_enum,
    exact_fields,
    fail,
)

WORKER_JOB_SCHEMA = "jarvis.testlab.worker_job"
WORKER_RESULT_SCHEMA = "jarvis.testlab.worker_result"

MAX_JOB_PATH_CHARS = 512
#: A worker may report at most as many metrics as a diagnostic may declare.
MAX_RESULT_METRICS = MAX_METRICS

# ------------------------------------------------------------ run scratch

#: Per-run scratch layout under `<work_root>/<run_id>/`. Nothing here is durable
#: evidence: what must survive the run is committed to the store as an artifact.
JOB_FILE_NAME = "job.json"
RESULT_FILE_NAME = "result.json"
#: Presence means "stop cooperatively"; the worker polls it on its heartbeat tick.
CANCEL_FILE_NAME = "cancel.json"
#: Written by the supervisor at spawn: pid and spawn time, for the adoption report.
WORKER_FILE_NAME = "worker.json"
#: Refreshed by the worker: proof it is alive and how far it has got.
HEARTBEAT_FILE_NAME = "heartbeat.json"
#: Held by the worker for its whole life. The OS releases it when the worker dies,
#: which is how a later supervisor knows whether a run still has a live worker.
WORKER_LOCK_NAME = "worker.lock"
WORKER_LOG_NAME = "worker.log"
STDERR_LOG_NAME = "worker-stderr.log"
RUNTIME_DIR_NAME = "runtime"
DATA_DIR_NAME = "data"

#: Artifact paths the supervisor commits from the scratch (run-directory relative).
WORKER_LOG_ARTIFACT = "worker.log"
STDERR_LOG_ARTIFACT = "worker-stderr.log"


# ---------------------------------------------------------- failure codes

#: Closed vocabulary of `RunFailure.code` values this Slice produces
#: (docs/testlab.md, "Supervisor and workers"). Every terminal run that is not
#: `passed` or `failed` carries one of these.
FAILURE_PERMISSION_DENIED = "permission_denied"
FAILURE_RESOURCE_WAIT_TIMEOUT = "resource_wait_timeout"
FAILURE_WORKER_SPAWN_FAILED = "worker_spawn_failed"
FAILURE_WORKER_STARTUP_TIMEOUT = "worker_startup_timeout"
FAILURE_WORKER_UNRESPONSIVE = "worker_unresponsive"
FAILURE_WORKER_CRASHED = "worker_crashed"
FAILURE_WORKER_LOST = "worker_lost"
FAILURE_WORKER_ACTIVE_ELSEWHERE = "worker_active_elsewhere"
FAILURE_RUN_ABANDONED = "run_abandoned"
#: A terminal record this supervisor never wrote: something concluded the run behind it.
FAILURE_RUN_CONCLUDED_OUT_OF_BAND = "run_concluded_out_of_band"
FAILURE_RUN_TIMEOUT = "run_timeout"
FAILURE_CANCELLED = "cancelled_by_caller"
FAILURE_RESULT_INVALID = "worker_result_invalid"
FAILURE_RESULT_CONTRADICTS_SPEC = "result_contradicts_spec"
FAILURE_JOB_INVALID = "worker_job_invalid"
FAILURE_ISOLATION_VIOLATION = "isolation_violation"
FAILURE_CATALOG_UNAVAILABLE = "catalog_unavailable"
FAILURE_RUNNER_UNAVAILABLE = "runner_unavailable"
FAILURE_RUNNER_FAILED = "runner_failed"
FAILURE_SUPERVISOR_STOPPED = "supervisor_stopped"
#: Slice 07: the runner reached the stack but could not obtain a measurement the
#: declaration needs (a stimulus the stack never answered, a step the situation could
#: not perform, an expectation that could not be evaluated). "Could not measure", which
#: `jarvis.testlab.outcomes` reads as `inconclusive` — not a crash and not a verdict.
FAILURE_MEASUREMENT_UNAVAILABLE = "measurement_unavailable"
#: Slice 07: an evaluable scenario expectation disagreed, in a diagnostic that declares
#: no metric able to carry it. The authored situation did not materialise, so the run is
#: not the experiment that was asked for; also `inconclusive`.
FAILURE_SCENARIO_EXPECTATION_UNMET = "scenario_expectation_unmet"
#: Slice 08 (READINESS B9): the workstation's audio devices are held, or their
#: availability could not be established, so the run was never started. The Test Lab
#: refuses rather than taking a device the live Jarvis may be using — `refused`.
FAILURE_DEVICE_CONTENTION = "device_contention"
#: Slice 08: contention appeared WHILE a device run was executing (the live Jarvis
#: started). The run is stopped; what it measured happened next to another user of the
#: device, so it is `inconclusive`, never a verdict.
FAILURE_DEVICE_CONTENTION_DURING_RUN = "device_contention_during_run"
#: Slice 08: a `live` run was submitted without the explicit `JARVIS_TESTLAB_LIVE=1`
#: opt-in. Nothing was called and nothing was spent — `refused`.
FAILURE_LIVE_OPT_IN_MISSING = "live_opt_in_missing"
#: Slice 08: the estimated provider spend crossed the run's budget mid-run and the
#: session was stopped. Partial measurements, no verdict — `inconclusive`.
FAILURE_COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
#: Slice 09: a `hardware:guided` run was submitted without `JARVIS_TESTLAB_GUIDED=1`, the
#: operator declaring that a human is at this workstation now. Nothing was opened and
#: nobody's time was spent — `refused`. The declared `human_presence` capability says the
#: diagnostic needs a person; this says one is actually there.
FAILURE_HUMAN_PRESENCE_MISSING = "human_presence_missing"
#: Slice 08: the SUPERVISOR broke around this run — an injected resource gate or the
#: supervision loop raised. Never the worker's fault, so never the worker's code, and
#: it reads `crashed` because it is a defect of ours, not a finding about the product.
FAILURE_SUPERVISOR_FAULT = "supervisor_fault"

FAILURE_CODES = frozenset({
    FAILURE_PERMISSION_DENIED, FAILURE_RESOURCE_WAIT_TIMEOUT, FAILURE_WORKER_SPAWN_FAILED,
    FAILURE_WORKER_STARTUP_TIMEOUT, FAILURE_WORKER_UNRESPONSIVE, FAILURE_WORKER_CRASHED, FAILURE_WORKER_LOST,
    FAILURE_WORKER_ACTIVE_ELSEWHERE, FAILURE_RUN_ABANDONED, FAILURE_RUN_CONCLUDED_OUT_OF_BAND,
    FAILURE_RUN_TIMEOUT, FAILURE_CANCELLED,
    FAILURE_RESULT_INVALID, FAILURE_RESULT_CONTRADICTS_SPEC, FAILURE_JOB_INVALID, FAILURE_ISOLATION_VIOLATION,
    FAILURE_CATALOG_UNAVAILABLE, FAILURE_RUNNER_UNAVAILABLE, FAILURE_RUNNER_FAILED, FAILURE_SUPERVISOR_STOPPED,
    FAILURE_MEASUREMENT_UNAVAILABLE, FAILURE_SCENARIO_EXPECTATION_UNMET,
    FAILURE_DEVICE_CONTENTION, FAILURE_DEVICE_CONTENTION_DURING_RUN, FAILURE_LIVE_OPT_IN_MISSING,
    FAILURE_COST_BUDGET_EXCEEDED, FAILURE_SUPERVISOR_FAULT, FAILURE_HUMAN_PRESENCE_MISSING,
})


def _check_path_value(value: object, name: str) -> None:
    check_text(value, name, max_chars=MAX_JOB_PATH_CHARS)


# -------------------------------------------------------------- worker job

@dataclass(frozen=True, slots=True)
class WorkerJob:
    """Everything a worker needs, and nothing a worker may decide.

    The declaration it must obey (`diagnostic_fingerprint`), where it may write
    (`store_root`, `scratch_root`) and how long it may take (`max_duration_s`)
    are all fixed here by the supervisor.
    """

    run_id: str
    diagnostic_id: str
    diagnostic_version: int
    #: `DiagnosticSpec.fingerprint()` the supervisor resolved; the worker refuses a catalog that drifted.
    diagnostic_fingerprint: str
    profile: ProfileName
    #: Registered implementation name of this profile, resolved by the worker's registry.
    implementation: str
    #: Root of the run store the worker writes artifacts to.
    store_root: str
    #: Per-run scratch directory: job, result, heartbeat, run-local runtime and data roots.
    scratch_root: str
    #: Catalog root the worker loads; the supervisor loaded the same one.
    catalog_root: str
    #: Effective diagnostic parameters (declared defaults merged with supplied values).
    parameters: Mapping[str, Any] = field(default_factory=dict)
    #: Run-local setting overrides, already applied to the scratch settings copy.
    overrides: Mapping[str, Any] = field(default_factory=dict)
    scenario: Scenario | None = None
    #: Wall-clock budget of the run itself, from the profile's declared `max_duration_s`.
    max_duration_s: float = 60.0
    heartbeat_interval_s: float = 2.0
    #: Slice 08: may this run's store write `audio_clip` artifacts? The supervisor sets
    #: it only when the caller asked, the profile can produce audio AND its own store
    #: allows audio; the worker builds `ArtifactWriteLimits(allow_audio=...)` from it.
    #: A job that says True against a store built without audio still gets a refusal at
    #: write time, which is the point of having the limit on the store as well.
    allow_audio: bool = False
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        check_run_id(self.run_id)
        check_diagnostic_id(self.diagnostic_id)
        check_diagnostic_version(self.diagnostic_version)
        check_hex(self.diagnostic_fingerprint, "job.diagnostic_fingerprint", lengths=(64,))
        check_enum(ProfileName, self.profile, "job.profile")
        check_name(self.implementation, "job.implementation", max_chars=MAX_IMPLEMENTATION_CHARS)
        for name in ("store_root", "scratch_root", "catalog_root"):
            _check_path_value(getattr(self, name), f"job.{name}")
        object.__setattr__(self, "parameters", freeze_scalar_map(self.parameters, "job.parameters"))
        object.__setattr__(self, "overrides", freeze_scalar_map(self.overrides, "job.overrides",
                                                                limit=MAX_OVERRIDES))
        if self.scenario is not None and not isinstance(self.scenario, Scenario):
            raise fail("job.scenario must be a Scenario or null")
        check_number(self.max_duration_s, "job.max_duration_s", minimum=0.001, maximum=24 * 60 * 60)
        check_number(self.heartbeat_interval_s, "job.heartbeat_interval_s", minimum=0.01, maximum=60)
        if type(self.allow_audio) is not bool:
            raise fail("job.allow_audio must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": WORKER_JOB_SCHEMA,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "diagnostic_id": self.diagnostic_id,
            "diagnostic_version": self.diagnostic_version,
            "diagnostic_fingerprint": self.diagnostic_fingerprint,
            "profile": self.profile.value,
            "implementation": self.implementation,
            "store_root": self.store_root,
            "scratch_root": self.scratch_root,
            "catalog_root": self.catalog_root,
            "parameters": dict(self.parameters),
            "overrides": dict(self.overrides),
            "scenario": None if self.scenario is None else self.scenario.to_dict(),
            "max_duration_s": self.max_duration_s,
            "heartbeat_interval_s": self.heartbeat_interval_s,
            "allow_audio": self.allow_audio,
        }

    @classmethod
    def from_dict(cls, payload: object) -> WorkerJob:
        """Strict decode. The scenario is decoded shape-only; the worker re-checks its
        primitives against the registry, so an unknown primitive keeps its own error code."""
        data = exact_fields(payload, _JOB_FIELDS, "job")
        check_document_header(data, WORKER_JOB_SCHEMA, TESTLAB_SCHEMA_VERSION, "job")
        scenario = None if data["scenario"] is None else Scenario.from_dict(data["scenario"], primitives=SHAPE_ONLY)
        return cls(
            run_id=data["run_id"],
            diagnostic_id=data["diagnostic_id"],
            diagnostic_version=data["diagnostic_version"],
            diagnostic_fingerprint=data["diagnostic_fingerprint"],
            profile=decode_enum(ProfileName, data["profile"], "job.profile"),
            implementation=data["implementation"],
            store_root=data["store_root"],
            scratch_root=data["scratch_root"],
            catalog_root=data["catalog_root"],
            parameters=data["parameters"],
            overrides=data["overrides"],
            scenario=scenario,
            max_duration_s=data["max_duration_s"],
            heartbeat_interval_s=data["heartbeat_interval_s"],
            allow_audio=data["allow_audio"],
        )


_JOB_FIELDS = frozenset({
    "schema", "schema_version", "run_id", "diagnostic_id", "diagnostic_version", "diagnostic_fingerprint",
    "profile", "implementation", "store_root", "scratch_root", "catalog_root", "parameters", "overrides",
    "scenario", "max_duration_s", "heartbeat_interval_s", "allow_audio",
})


# ----------------------------------------------------------- worker result

class WorkerStatus(StrEnum):
    #: The runner produced measurements. The supervisor derives the verdict from them.
    MEASURED = "measured"
    #: The runner could not produce measurements; `failure` says why.
    FAILED = "failed"


def _freeze_metrics(values: object) -> Mapping[str, bool | int | float]:
    if not isinstance(values, Mapping):
        raise fail("result.metrics must be an object")
    if len(values) > MAX_RESULT_METRICS:
        raise fail(f"result.metrics exceed {MAX_RESULT_METRICS} entries", LIMIT_EXCEEDED)
    frozen: dict[str, bool | int | float] = {}
    for key, value in values.items():
        check_name(key, "result.metrics key")
        if type(value) is not bool:
            check_number(value, f"result.metrics.{key}")
        frozen[key] = value
    return MappingProxyType(dict(sorted(frozen.items())))


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """What one worker measured, written atomically so it survives the worker's death."""

    run_id: str
    status: WorkerStatus
    metrics: Mapping[str, bool | int | float] = field(default_factory=dict)
    #: Conversation Events join values the runner observed (`TRACE_JOIN_FIELDS` names).
    join_ids: Mapping[str, str] = field(default_factory=dict)
    #: References the worker already committed through `put_artifact`.
    artifacts: tuple[ArtifactRef, ...] = ()
    failure: RunFailure | None = None
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        check_run_id(self.run_id)
        check_enum(WorkerStatus, self.status, "result.status")
        object.__setattr__(self, "metrics", _freeze_metrics(self.metrics))
        if not isinstance(self.join_ids, Mapping):
            raise fail("result.join_ids must be an object")
        object.__setattr__(self, "join_ids", MappingProxyType(dict(sorted(self.join_ids.items()))))
        if not isinstance(self.artifacts, tuple) or any(not isinstance(item, ArtifactRef) for item in self.artifacts):
            raise fail("result.artifacts must be a tuple of ArtifactRef")
        if len(self.artifacts) > MAX_ARTIFACTS:
            raise fail(f"result.artifacts exceed {MAX_ARTIFACTS} entries", LIMIT_EXCEEDED)
        if self.failure is not None and not isinstance(self.failure, RunFailure):
            raise fail("result.failure must be a RunFailure or null")
        if (self.status is WorkerStatus.FAILED) != (self.failure is not None):
            raise fail("result.failure is set exactly when the status is failed")
        if self.status is WorkerStatus.FAILED and self.metrics:
            raise fail("a failed result carries no metrics")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": WORKER_RESULT_SCHEMA,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status.value,
            "metrics": dict(self.metrics),
            "join_ids": dict(self.join_ids),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "failure": None if self.failure is None else self.failure.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: object) -> WorkerResult:
        data = exact_fields(payload, _RESULT_FIELDS, "result")
        check_document_header(data, WORKER_RESULT_SCHEMA, TESTLAB_SCHEMA_VERSION, "result")
        if not isinstance(data["artifacts"], list):
            raise fail("result.artifacts must be a list")
        return cls(
            run_id=data["run_id"],
            status=decode_enum(WorkerStatus, data["status"], "result.status"),
            metrics=data["metrics"],
            join_ids=data["join_ids"],
            artifacts=tuple(ArtifactRef.from_dict(item) for item in data["artifacts"]),
            failure=None if data["failure"] is None else RunFailure.from_dict(data["failure"]),
        )


_RESULT_FIELDS = frozenset({"schema", "schema_version", "run_id", "status", "metrics", "join_ids",
                            "artifacts", "failure"})


def worker_failure(code: str, detail: str | None = None) -> RunFailure:
    """A `RunFailure` whose code belongs to the closed Slice 05 vocabulary."""
    check_name(code, "failure.code", pattern=SIMPLE_NAME)
    if code not in FAILURE_CODES:
        raise fail(f"failure code {code} is not part of the supervisor vocabulary")
    return RunFailure(code, detail)
