"""Test Lab `TestRun` record, its state machine and its strict codec.

Binding contract: `docs/testlab.md` ("TestRun", "Run state machine"). Pure:
times are supplied values, never read from a clock; artifacts are typed
references, never blobs. Constructing a `TestRun` validates every invariant,
so a record whose status contradicts its blocking assertions cannot exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any

from jarvis.domain.conversation_events import TRACE_JOIN_FIELDS
from jarvis.domain.voice_state import state_id
from jarvis.testlab.diagnostics import (
    MAX_ASSERTIONS,
    MAX_METRICS,
    SCORE_MAX,
    SCORE_MIN,
    AssertionOutcome,
    AssertionResult,
    AssertionSpec,
    AssertionVerdict,
    DiagnosticSpec,
    MetricSpec,
    assertions_verdict,
    check_metric_value,
    check_parameter_value,
    evaluate_assertion,
    freeze_scalar_map,
)
from jarvis.testlab.identity import (
    TESTLAB_SCHEMA_VERSION,
    TEST_RUN_SCHEMA,
    check_bundle_id,
    check_diagnostic_id,
    check_diagnostic_version,
    check_run_id,
    check_sweep_id,
    id_timestamp,
)
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.validation import (
    FIELD_INVALID,
    FORBIDDEN_PRIVATE_DATA,
    LIMIT_EXCEEDED,
    REFERENCE_INVALID,
    SIMPLE_NAME,
    TestLabError,
    TestLabRedactionError,
    check_bool,
    check_document_header,
    check_enum,
    check_hex,
    check_name,
    check_number,
    check_text,
    check_time,
    decode_enum,
    exact_fields,
    fail,
    format_time,
    is_private_key,
    name_for_message,
    parse_time,
    scan_private,
)

MAX_OVERRIDES = 64
MAX_ENVIRONMENT = 32
MAX_ARTIFACTS = 256
MAX_ARTIFACT_PATH_CHARS = 200
MAX_ARTIFACT_PATH_SEGMENTS = 8
MAX_FAILURE_DETAIL_CHARS = 512
MAX_ARTIFACT_SIZE_BYTES = 2**53

TRANSITION_ILLEGAL = "testlab_transition_illegal"

_PATH_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_MEDIA_TYPE = re.compile(r"[a-z]+/[a-z0-9][a-z0-9.+-]*")


class RunTransitionError(TestLabError):
    """A status change the run state machine does not allow."""


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_STATUSES = frozenset({RunStatus.PASSED, RunStatus.FAILED, RunStatus.ERRORED, RunStatus.CANCELLED,
                               RunStatus.TIMED_OUT})

#: Legal transitions. `queued -> errored` covers a worker that never starts.
RUN_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = MappingProxyType({
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.ERRORED}),
    RunStatus.RUNNING: frozenset({RunStatus.PASSED, RunStatus.FAILED, RunStatus.ERRORED, RunStatus.CANCELLED,
                                  RunStatus.TIMED_OUT}),
    **{status: frozenset() for status in TERMINAL_STATUSES},
})


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    check_enum(RunStatus, current, "current status")
    check_enum(RunStatus, target, "target status")
    return target in RUN_TRANSITIONS[current]


def check_transition(current: RunStatus, target: RunStatus) -> None:
    if not can_transition(current, target):
        raise RunTransitionError(TRANSITION_ILLEGAL, f"a run cannot go from {current.value} to {target.value}")


# ------------------------------------------------------------------ parts

@dataclass(frozen=True, slots=True)
class CodeIdentity:
    """The code a run executed: git commit plus whether the worktree had uncommitted changes."""

    git_revision: str
    dirty: bool

    def __post_init__(self) -> None:
        check_hex(self.git_revision, "code.git_revision", lengths=(40, 64))
        check_bool(self.dirty, "code.dirty")

    def to_dict(self) -> dict[str, Any]:
        return {"git_revision": self.git_revision, "dirty": self.dirty}

    @classmethod
    def from_dict(cls, payload: object) -> CodeIdentity:
        data = exact_fields(payload, frozenset({"git_revision", "dirty"}), "code")
        return cls(data["git_revision"], data["dirty"])


def check_artifact_path(path: object, name: str = "artifact.path") -> None:
    """Relative POSIX path of safe segments inside the run directory (no absolute, drive, `..` or hidden segment).

    Shared by `ArtifactRef` and the run store (docs/testlab.md, "Storage"), which adds the filesystem checks.
    """
    if (not isinstance(path, str) or not path or len(path) > MAX_ARTIFACT_PATH_CHARS
            or len(path.split("/")) > MAX_ARTIFACT_PATH_SEGMENTS
            or any(not _PATH_SEGMENT.fullmatch(segment) or segment.endswith(".") for segment in path.split("/"))):
        raise fail(f"{name} must be a relative POSIX path of safe segments inside the run directory")


class ArtifactKind(StrEnum):
    CONFIG_SNAPSHOT = "config_snapshot"
    SCENARIO = "scenario"
    EVENT_LOG = "event_log"
    TRACE_EXCERPT = "trace_excerpt"
    WORKER_LOG = "worker_log"
    METRICS = "metrics"
    REPORT = "report"
    #: Bounded, opt-in audio evidence (retention is profile-driven, Slice 02/08).
    AUDIO_CLIP = "audio_clip"


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Reference to a stored run output. The bytes live in the artifact store, never in the record."""

    kind: ArtifactKind
    #: POSIX path relative to the run directory; no absolute path, drive, `..` or hidden segment.
    path: str
    media_type: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        check_enum(ArtifactKind, self.kind, "artifact.kind")
        check_artifact_path(self.path)
        if not isinstance(self.media_type, str) or len(self.media_type) > 64 or not _MEDIA_TYPE.fullmatch(self.media_type):
            raise fail("artifact.media_type must be a lowercase type/subtype")
        check_hex(self.sha256, "artifact.sha256", lengths=(64,))
        check_number(self.size_bytes, "artifact.size_bytes", minimum=0, maximum=MAX_ARTIFACT_SIZE_BYTES, integer=True)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "path": self.path, "media_type": self.media_type, "sha256": self.sha256,
                "size_bytes": self.size_bytes}

    @classmethod
    def from_dict(cls, payload: object) -> ArtifactRef:
        data = exact_fields(payload, frozenset({"kind", "path", "media_type", "sha256", "size_bytes"}), "artifact")
        return cls(decode_enum(ArtifactKind, data["kind"], "artifact.kind"), data["path"], data["media_type"],
                   data["sha256"], data["size_bytes"])


@dataclass(frozen=True, slots=True)
class RunFailure:
    """Why a run errored, timed out or was cancelled: stable code plus a bounded, secret-free detail."""

    code: str
    detail: str | None = None

    def __post_init__(self) -> None:
        check_name(self.code, "failure.code", pattern=SIMPLE_NAME)
        check_text(self.detail, "failure.detail", max_chars=MAX_FAILURE_DETAIL_CHARS, optional=True)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail}

    @classmethod
    def from_dict(cls, payload: object) -> RunFailure:
        data = exact_fields(payload, frozenset({"code", "detail"}), "failure")
        return cls(data["code"], data["detail"])


#: Failure code set by `complete_run` when blocking assertions could not conclude.
FAILURE_ASSERTIONS_INCONCLUSIVE = "assertions_inconclusive"
#: How many missing blocking assertions the failure detail names before abbreviating.
MAX_NAMED_MISSING_ASSERTIONS = 8


def inconclusive_detail(results: tuple[AssertionResult, ...]) -> str:
    """Why the blocking assertions could not conclude, naming them.

    An assertion id designates exactly one metric in the declaration, so naming the
    assertions answers "which measurement is missing" for anyone holding the spec —
    without putting a measured VALUE in a failure detail. An empty detail used to make
    the two "could not measure" shapes indistinguishable without re-deriving the run.
    """
    missing = sorted(result.assertion_id for result in results
                     if result.blocking and result.outcome is AssertionOutcome.MISSING)
    if not missing:
        return "the diagnostic evaluated no blocking assertion, so nothing could conclude"
    named = ", ".join(missing[:MAX_NAMED_MISSING_ASSERTIONS])
    rest = len(missing) - MAX_NAMED_MISSING_ASSERTIONS
    return (f"no measurement for blocking assertion(s): {named}" + (f" and {rest} more" if rest > 0 else ""))[
        :MAX_FAILURE_DETAIL_CHARS]


def _freeze_metrics(values: object) -> Mapping[str, bool | int | float]:
    if not isinstance(values, Mapping):
        raise fail("metrics must be an object")
    if len(values) > MAX_METRICS:
        raise fail(f"metrics exceed {MAX_METRICS} entries", LIMIT_EXCEEDED)
    frozen: dict[str, bool | int | float] = {}
    for key, value in values.items():
        check_name(key, "metrics key")
        if is_private_key(key):
            raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA, f"metrics.{name_for_message(key)}: forbidden name")
        if type(value) is not bool:
            check_number(value, f"metrics.{key}")
        frozen[key] = value
    return MappingProxyType(dict(sorted(frozen.items())))


def _freeze_join_ids(values: object) -> Mapping[str, str]:
    if not isinstance(values, Mapping):
        raise fail("join_ids must be an object")
    frozen: dict[str, str] = {}
    for key, value in values.items():
        if key not in TRACE_JOIN_FIELDS:
            raise fail(f"join_ids keys must be among {', '.join(TRACE_JOIN_FIELDS)}")
        try:
            state_id(value, f"join_ids.{key}")
        except ValueError as exc:
            raise fail(str(exc)) from None
        frozen[key] = value
    return MappingProxyType({key: frozen[key] for key in TRACE_JOIN_FIELDS if key in frozen})


# --------------------------------------------------------------- TestRun

@dataclass(frozen=True, slots=True)
class TestRun:
    """One persistent, replayable, comparable execution of one diagnostic on one profile."""

    __test__ = False  # not a pytest test class, despite the name

    run_id: str
    diagnostic_id: str
    diagnostic_version: int
    profile: ProfileName
    status: RunStatus
    #: When the run was queued; equals the time embedded in `run_id`.
    created_at: datetime
    code: CodeIdentity
    #: `content_fingerprint` of the effective configuration snapshot the run used.
    config_fingerprint: str
    #: `DiagnosticSpec.fingerprint()` of the declaration the run was judged by.
    diagnostic_fingerprint: str
    #: Effective diagnostic parameters (declared defaults merged with supplied values).
    parameters: Mapping[str, Any] = field(default_factory=dict)
    #: Run-local setting overrides (dotted setting path -> JSON scalar). Never written to permanent settings.
    overrides: Mapping[str, Any] = field(default_factory=dict)
    #: Execution environment facts (dotted name -> JSON scalar), e.g. `os`, `python_version`, `host.cpu_count`.
    environment: Mapping[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    assertion_results: tuple[AssertionResult, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    #: 0..100 synthesis declared by the diagnostic's score contract; never decides the status.
    score: float | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    failure: RunFailure | None = None
    bundle_id: str | None = None
    sweep_id: str | None = None
    parent_run_id: str | None = None
    scenario_id: str | None = None
    scenario_fingerprint: str | None = None
    #: Conversation Events trace join values (`TRACE_JOIN_FIELDS` names -> opaque ids).
    join_ids: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __hash__(self) -> int:
        return hash(self.run_id)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        check_run_id(self.run_id)
        check_diagnostic_id(self.diagnostic_id)
        check_diagnostic_version(self.diagnostic_version)
        check_enum(ProfileName, self.profile, "profile")
        check_enum(RunStatus, self.status, "status")
        if not isinstance(self.code, CodeIdentity):
            raise fail("code must be a CodeIdentity")
        check_hex(self.config_fingerprint, "config_fingerprint", lengths=(64,))
        check_hex(self.diagnostic_fingerprint, "diagnostic_fingerprint", lengths=(64,))
        object.__setattr__(self, "parameters", freeze_scalar_map(self.parameters, "parameters"))
        object.__setattr__(self, "overrides", freeze_scalar_map(self.overrides, "overrides", limit=MAX_OVERRIDES))
        object.__setattr__(self, "environment", freeze_scalar_map(self.environment, "environment",
                                                                  limit=MAX_ENVIRONMENT))
        object.__setattr__(self, "metrics", _freeze_metrics(self.metrics))
        object.__setattr__(self, "join_ids", _freeze_join_ids(self.join_ids))
        self._check_times()
        self._check_outcome()
        if not isinstance(self.artifacts, tuple) or any(not isinstance(item, ArtifactRef) for item in self.artifacts):
            raise fail("artifacts must be a tuple of ArtifactRef")
        if len(self.artifacts) > MAX_ARTIFACTS:
            raise fail(f"artifacts exceed {MAX_ARTIFACTS} entries", LIMIT_EXCEEDED)
        if len({artifact.path for artifact in self.artifacts}) != len(self.artifacts):
            raise fail("artifacts must not repeat a path")
        check_bundle_id(self.bundle_id, optional=True)
        check_sweep_id(self.sweep_id, optional=True)
        check_run_id(self.parent_run_id, "parent_run_id", optional=True)
        if self.parent_run_id == self.run_id:
            raise fail("parent_run_id must differ from run_id")
        check_name(self.scenario_id, "scenario_id", optional=True)
        check_hex(self.scenario_fingerprint, "scenario_fingerprint", lengths=(64,), optional=True)
        if (self.scenario_id is None) != (self.scenario_fingerprint is None):
            raise fail("scenario_id and scenario_fingerprint are set together or not at all")

    def _check_times(self) -> None:
        check_time(self.created_at, "created_at")
        check_time(self.started_at, "started_at", optional=True)
        check_time(self.finished_at, "finished_at", optional=True)
        if self.run_id.split("-")[1] != id_timestamp(self.created_at):
            raise fail("created_at must equal the time embedded in run_id")
        status = self.status
        if status is RunStatus.QUEUED and self.started_at is not None:
            raise fail("started_at must be null while queued")
        if status is not RunStatus.QUEUED and self.started_at is None and status not in (
                RunStatus.CANCELLED, RunStatus.ERRORED):
            raise fail(f"started_at is required for {status.value}")
        if (self.finished_at is not None) != (status in TERMINAL_STATUSES):
            raise fail("finished_at is set exactly when the status is terminal")
        if self.started_at is not None and self.started_at < self.created_at:
            raise fail("started_at must not precede created_at")
        if self.finished_at is not None and self.finished_at < (self.started_at or self.created_at):
            raise fail("finished_at must not precede started_at or created_at")

    def _check_outcome(self) -> None:
        results = self.assertion_results
        if not isinstance(results, tuple) or any(not isinstance(item, AssertionResult) for item in results):
            raise fail("assertion_results must be a tuple of AssertionResult")
        if len(results) > MAX_ASSERTIONS:
            raise fail(f"assertion_results exceed {MAX_ASSERTIONS} entries", LIMIT_EXCEEDED)
        if len({result.assertion_id for result in results}) != len(results):
            raise fail("assertion_results must not repeat an assertion_id")
        status = self.status
        terminal = status in TERMINAL_STATUSES
        if not terminal and (results or self.metrics or self.score is not None):
            raise fail(f"assertion_results, metrics and score are recorded only on a terminal run, not {status.value}")
        if self.score is not None:
            check_number(self.score, "score", minimum=SCORE_MIN, maximum=SCORE_MAX)
        verdict = assertions_verdict(results)
        if status is RunStatus.PASSED and verdict is not AssertionVerdict.PASSED:
            raise fail("a passed run needs every blocking assertion passed", REFERENCE_INVALID)
        if status is RunStatus.FAILED and verdict is not AssertionVerdict.FAILED:
            raise fail("a failed run needs at least one failed blocking assertion", REFERENCE_INVALID)
        if status in (RunStatus.PASSED, RunStatus.FAILED) and self.failure is not None:
            raise fail(f"failure must be null for {status.value}")
        if status in (RunStatus.ERRORED, RunStatus.TIMED_OUT) and self.failure is None:
            raise fail(f"failure is required for {status.value}")
        if not terminal and self.failure is not None:
            raise fail(f"failure must be null for {status.value}")
        if self.failure is not None and not isinstance(self.failure, RunFailure):
            raise fail("failure must be a RunFailure")

    @property
    def verdict(self) -> AssertionVerdict:
        return assertions_verdict(self.assertion_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TEST_RUN_SCHEMA,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "diagnostic_id": self.diagnostic_id,
            "diagnostic_version": self.diagnostic_version,
            "profile": self.profile.value,
            "status": self.status.value,
            "created_at": format_time(self.created_at),
            "started_at": format_time(self.started_at),
            "finished_at": format_time(self.finished_at),
            "code": self.code.to_dict(),
            "config_fingerprint": self.config_fingerprint,
            "diagnostic_fingerprint": self.diagnostic_fingerprint,
            "parameters": dict(self.parameters),
            "overrides": dict(self.overrides),
            "environment": dict(self.environment),
            "assertion_results": [result.to_dict() for result in self.assertion_results],
            "metrics": dict(self.metrics),
            "score": self.score,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "failure": None if self.failure is None else self.failure.to_dict(),
            "bundle_id": self.bundle_id,
            "sweep_id": self.sweep_id,
            "parent_run_id": self.parent_run_id,
            "scenario_id": self.scenario_id,
            "scenario_fingerprint": self.scenario_fingerprint,
            "join_ids": dict(self.join_ids),
        }

    @classmethod
    def from_dict(cls, payload: object) -> TestRun:
        """Strict decode: redaction scan first, exact fields, schema and version, then every invariant."""
        scan_private(payload, "run")
        data = exact_fields(payload, _RUN_FIELDS, "run")
        check_document_header(data, TEST_RUN_SCHEMA, TESTLAB_SCHEMA_VERSION, "run")
        for name in ("assertion_results", "artifacts"):
            if not isinstance(data[name], list):
                raise fail(f"{name} must be a list")
        if data["created_at"] is None:
            raise fail("created_at is required")
        return cls(
            run_id=data["run_id"],
            diagnostic_id=data["diagnostic_id"],
            diagnostic_version=data["diagnostic_version"],
            profile=decode_enum(ProfileName, data["profile"], "profile"),
            status=decode_enum(RunStatus, data["status"], "status"),
            created_at=parse_time(data["created_at"], "created_at"),
            started_at=parse_time(data["started_at"], "started_at", optional=True),
            finished_at=parse_time(data["finished_at"], "finished_at", optional=True),
            code=CodeIdentity.from_dict(data["code"]),
            config_fingerprint=data["config_fingerprint"],
            diagnostic_fingerprint=data["diagnostic_fingerprint"],
            parameters=data["parameters"],
            overrides=data["overrides"],
            environment=data["environment"],
            assertion_results=tuple(AssertionResult.from_dict(item) for item in data["assertion_results"]),
            metrics=data["metrics"],
            score=data["score"],
            artifacts=tuple(ArtifactRef.from_dict(item) for item in data["artifacts"]),
            failure=None if data["failure"] is None else RunFailure.from_dict(data["failure"]),
            bundle_id=data["bundle_id"],
            sweep_id=data["sweep_id"],
            parent_run_id=data["parent_run_id"],
            scenario_id=data["scenario_id"],
            scenario_fingerprint=data["scenario_fingerprint"],
            join_ids=data["join_ids"],
        )


_RUN_FIELDS = frozenset({
    "schema", "schema_version", "run_id", "diagnostic_id", "diagnostic_version", "profile", "status", "created_at",
    "started_at", "finished_at", "code", "config_fingerprint", "diagnostic_fingerprint", "parameters", "overrides",
    "environment", "assertion_results",
    "metrics", "score", "artifacts", "failure", "bundle_id", "sweep_id", "parent_run_id", "scenario_id",
    "scenario_fingerprint", "join_ids",
})


# ------------------------------------------------------------ transitions

def transition_run(run: TestRun, target: RunStatus, *, at: datetime, failure: RunFailure | None = None) -> TestRun:
    """Move a run to `running`, `cancelled`, `errored` or `timed_out` at the supplied time.

    `passed` and `failed` are never set directly: use `complete_run`, which
    derives them from the blocking assertions.
    """
    if not isinstance(run, TestRun):
        raise fail("transition_run takes a TestRun", FIELD_INVALID)
    check_enum(RunStatus, target, "target status")
    if target in (RunStatus.PASSED, RunStatus.FAILED):
        raise RunTransitionError(TRANSITION_ILLEGAL, f"{target.value} is derived from assertions; use complete_run")
    check_transition(run.status, target)
    if target is RunStatus.RUNNING:
        if failure is not None:
            raise fail("failure must be null when a run starts running")
        return replace(run, status=target, started_at=at)
    return replace(run, status=target, finished_at=at, failure=failure)


def complete_run(run: TestRun, *, at: datetime, assertion_results: tuple[AssertionResult, ...],
                 metrics: Mapping[str, Any], score: float | None = None,
                 artifacts: tuple[ArtifactRef, ...] | None = None) -> TestRun:
    """Finish a running run from its evidence. Blocking assertions decide, the score never does.

    failed blocking assertion -> `failed`; all blocking passed -> `passed`;
    otherwise (missing measurement, no blocking result) -> `errored` with
    failure code `assertions_inconclusive` and a detail naming the blocking
    assertions that had no measurement (`inconclusive_detail`).
    """
    if not isinstance(run, TestRun):
        raise fail("complete_run takes a TestRun", FIELD_INVALID)
    if not isinstance(assertion_results, tuple):
        raise fail("assertion_results must be a tuple of AssertionResult")
    verdict = assertions_verdict(assertion_results)
    target = {AssertionVerdict.PASSED: RunStatus.PASSED, AssertionVerdict.FAILED: RunStatus.FAILED}.get(
        verdict, RunStatus.ERRORED)
    check_transition(run.status, target)
    failure = (RunFailure(FAILURE_ASSERTIONS_INCONCLUSIVE, inconclusive_detail(assertion_results))
               if target is RunStatus.ERRORED else None)
    return replace(run, status=target, finished_at=at, assertion_results=assertion_results, metrics=metrics,
                   score=score, failure=failure, artifacts=run.artifacts if artifacts is None else artifacts)


# ------------------------------------------------------- spec conformance

def _same_result(recorded: AssertionResult, derived: AssertionResult) -> bool:
    """Equal outcome and observed value, a boolean never standing in for a number (True == 1 in Python)."""
    return (recorded.outcome is derived.outcome and recorded.observed == derived.observed
            and (type(recorded.observed) is bool) == (type(derived.observed) is bool))


def _check_result(result: AssertionResult, assertion: AssertionSpec, metric: MetricSpec, run: TestRun) -> None:
    where = f"assertion_results {result.assertion_id}"
    if assertion.blocking is not result.blocking:
        raise fail(f"{where}: blocking differs from the spec", REFERENCE_INVALID)
    if result.outcome is not AssertionOutcome.MISSING:
        check_metric_value(metric, result.observed, where)
    derived = evaluate_assertion(assertion, metric, run.metrics.get(assertion.metric))
    if not _same_result(result, derived):
        raise fail(f"{where}: recorded outcome or observed value contradicts the run metrics and the spec",
                   REFERENCE_INVALID)


def check_run_against_spec(run: TestRun, spec: DiagnosticSpec) -> None:
    """Cross-check a run with the diagnostic it claims.

    Identity and declaration fingerprint, profile, parameters, metrics, and every
    recorded assertion result re-derived from `run.metrics` with
    `evaluate_assertion` (outcome and observed value must be identical), so a
    verdict cannot be forged by recording results that the metrics do not support.
    """
    if not isinstance(run, TestRun) or not isinstance(spec, DiagnosticSpec):
        raise fail("check_run_against_spec takes a TestRun and a DiagnosticSpec", FIELD_INVALID)
    if (run.diagnostic_id, run.diagnostic_version) != (spec.diagnostic_id, spec.version):
        raise fail("run diagnostic_id/diagnostic_version differ from the spec", REFERENCE_INVALID)
    if run.diagnostic_fingerprint != spec.fingerprint():
        raise fail("run diagnostic_fingerprint differs from the spec declaration", REFERENCE_INVALID)
    if run.profile not in spec.profiles:
        raise fail(f"profile {run.profile.value} is not supported by the diagnostic", REFERENCE_INVALID)
    declared = {parameter.name: parameter for parameter in spec.parameters}
    if set(run.parameters) != set(declared):
        raise fail("run parameters must list exactly the declared parameters", REFERENCE_INVALID)
    for name, value in run.parameters.items():
        check_parameter_value(declared[name], value, f"parameters.{name}")
    metrics = spec.metric_index
    for name, value in run.metrics.items():
        if name not in metrics:
            raise fail(f"metrics.{name} is not declared by the diagnostic", REFERENCE_INVALID)
        check_metric_value(metrics[name], value, f"metrics.{name}")
    assertions = spec.assertion_index
    for result in run.assertion_results:
        assertion = assertions.get(result.assertion_id)
        if assertion is None:
            raise fail(f"assertion_results {result.assertion_id} is not declared", REFERENCE_INVALID)
        _check_result(result, assertion, metrics[assertion.metric], run)
    if run.status in (RunStatus.PASSED, RunStatus.FAILED) and len(run.assertion_results) != len(assertions):
        raise fail("a passed or failed run records a result for every declared assertion", REFERENCE_INVALID)
