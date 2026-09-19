"""Parameter sweeps: the declaration, the points it expands to, and the record it leaves.

Binding contract: `docs/testlab.md` ("Sweeps"). Pure: this module declares what a
sweep IS and checks it against a diagnostic; `jarvis.testlab.sweep_runner` is the
orchestrator that submits the runs, and `jarvis.testlab.filesystem_sweep_store`
persists what this module describes.

Locked product decision 9: a run may apply isolated overrides and sweep
parameters, but **never mutates permanent Jarvis configuration**. A sweep is the
sharpest form of that temptation — it finds a winning value — so the rule is
mechanical here: a `SweepSpec` has no field that names a settings file, the
runner has no write path to one, and every swept value travels as a run-local
parameter or a run-local override, exactly like a single run's. The sweep
reports; the human decides.

Two guards keep a sweep from becoming a load test on a workstation:

- every swept parameter is validated against the diagnostic's own
  `ParameterSpec` (or the manifest's override allowlist), so a sweep cannot
  reach a setting a single run could not;
- the expansion is bounded (`MAX_SWEEP_POINTS`, `MAX_SWEEP_RUNS`) and refused as
  a whole rather than truncated, because a silently shortened sweep is a
  conclusion drawn from evidence nobody asked for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from jarvis.testlab.diagnostics import (
    MAX_PARAMETERS,
    DiagnosticSpec,
    ParameterSpec,
    Scalar,
    check_parameter_value,
    freeze_scalar_map,
    resolve_parameters,
)
from jarvis.testlab.identity import (
    TESTLAB_SCHEMA_VERSION,
    check_diagnostic_id,
    check_diagnostic_version,
    check_run_id,
    check_sweep_id,
    id_timestamp,
)
from jarvis.testlab.outcomes import RunOutcomeClass
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import MAX_FAILURE_DETAIL_CHARS, MAX_OVERRIDES, RunFailure, RunStatus
from jarvis.testlab.scenarios import SHAPE_ONLY, Scenario
from jarvis.testlab.validation import (
    LIMIT_EXCEEDED,
    REFERENCE_INVALID,
    TestLabError,
    check_document_header,
    check_enum,
    check_hex,
    check_name,
    check_number,
    check_text,
    content_fingerprint,
    decode_enum,
    exact_fields,
    fail,
    format_time,
    name_for_message,
    parse_time,
    scan_private,
)

SWEEP_SPEC_SCHEMA = "jarvis.testlab.sweep"
SWEEP_RECORD_SCHEMA = "jarvis.testlab.sweep_record"
SWEEP_SUMMARY_SCHEMA = "jarvis.testlab.sweep_summary"

#: At most four axes: beyond that the cartesian product stops being readable long
#: before it stops being computable.
MAX_SWEPT_PARAMETERS = 4
MAX_SWEEP_VALUES = 64
MAX_SWEEP_POINTS = 256
#: Points times repetitions. A sweep is an experiment on a workstation, not a fleet job.
MAX_SWEEP_RUNS = 512
MAX_REPETITIONS = 16
MAX_SWEEP_TITLE_CHARS = 120
MAX_SWEEP_DESCRIPTION_CHARS = 512

SWEEP_INVALID = "testlab_sweep_invalid"
SWEEP_NOT_FOUND = "testlab_sweep_not_found"


class SweepError(TestLabError):
    """A sweep declaration the Test Lab refuses, or a sweep it cannot find."""


class SweepTarget(StrEnum):
    #: A declared diagnostic parameter.
    PARAMETER = "parameter"
    #: A run-local setting override; must be in the manifest's override allowlist.
    OVERRIDE = "override"


@dataclass(frozen=True, slots=True)
class SweptParameter:
    """One axis of a sweep: a name and the explicit values it takes.

    A range is expanded to explicit values at construction (`from_range`), so the
    stored declaration is always the exact list of values that ran — a sweep read
    six months later never depends on how a range was rounded today.
    """

    name: str
    target: SweepTarget
    values: tuple[Scalar, ...]

    def __post_init__(self) -> None:
        check_name(self.name, "swept.name", max_chars=96)
        check_enum(SweepTarget, self.target, f"swept {self.name}.target")
        if not isinstance(self.values, tuple) or not self.values:
            raise fail(f"swept {self.name}.values must be a non-empty tuple")
        if len(self.values) > MAX_SWEEP_VALUES:
            raise fail(f"swept {self.name} exceeds {MAX_SWEEP_VALUES} values", LIMIT_EXCEEDED)
        seen: list[Scalar] = []
        for value in self.values:
            if any(existing == value and type(existing) is type(value) for existing in seen):
                raise fail(f"swept {self.name} repeats a value")
            seen.append(value)

    @classmethod
    def from_range(cls, name: str, target: SweepTarget, *, start: int | float, stop: int | float,
                   step: int | float) -> SweptParameter:
        """Inclusive numeric range, expanded to explicit values.

        Values are computed as `start + i * step`, never accumulated, so a float
        range does not drift; `stop` is included when it lands exactly on a step.
        """
        for label, value in (("start", start), ("stop", stop), ("step", step)):
            check_number(value, f"swept {name}.{label}")
        if step == 0 or (stop - start) / step < 0:
            raise fail(f"swept {name}: step must be non-zero and point from start to stop")
        count = int((stop - start) / step) + 1
        if count > MAX_SWEEP_VALUES:
            raise fail(f"swept {name} would expand to {count} values, over {MAX_SWEEP_VALUES}", LIMIT_EXCEEDED)
        integral = all(type(value) is int for value in (start, stop, step))
        values = tuple((start + index * step) if integral else round(start + index * step, 9)
                       for index in range(count))
        return cls(name, target, values)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "target": self.target.value, "values": list(self.values)}

    @classmethod
    def from_dict(cls, payload: object) -> SweptParameter:
        data = exact_fields(payload, frozenset({"name", "target", "values"}), "swept")
        if not isinstance(data["values"], list):
            raise fail("swept.values must be a list")
        return cls(data["name"], decode_enum(SweepTarget, data["target"], "swept.target"), tuple(data["values"]))


@dataclass(frozen=True, slots=True)
class SweepSpec:
    """What to sweep: one diagnostic, one profile, a fixed base, and the axes that vary."""

    diagnostic_id: str
    profile: ProfileName
    #: None: the latest published version, resolved once for the whole sweep.
    version: int | None = None
    #: Parameters held fixed at every point. Swept names must not appear here.
    parameters: Mapping[str, Scalar] = field(default_factory=dict)
    #: Run-local setting overrides held fixed at every point.
    overrides: Mapping[str, Scalar] = field(default_factory=dict)
    swept: tuple[SweptParameter, ...] = ()
    #: Runs per point. More than one separates a real effect from host noise.
    repetitions: int = 1
    #: Replaces the manifest scenario for every run of the sweep.
    scenario: Scenario | None = None
    title: str | None = None
    description: str | None = None
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        check_diagnostic_id(self.diagnostic_id)
        check_enum(ProfileName, self.profile, "sweep.profile")
        if self.version is not None:
            check_diagnostic_version(self.version, "sweep.version")
        object.__setattr__(self, "parameters", freeze_scalar_map(self.parameters, "sweep.parameters"))
        object.__setattr__(self, "overrides", freeze_scalar_map(self.overrides, "sweep.overrides",
                                                                limit=MAX_OVERRIDES))
        if not isinstance(self.swept, tuple) or any(not isinstance(item, SweptParameter) for item in self.swept):
            raise fail("sweep.swept must be a tuple of SweptParameter")
        if not 1 <= len(self.swept) <= MAX_SWEPT_PARAMETERS:
            raise fail(f"sweep.swept must declare 1 to {MAX_SWEPT_PARAMETERS} axes")
        names = [item.name for item in self.swept]
        if len(set(names)) != len(names):
            raise fail("sweep.swept declares the same name twice")
        clashing = sorted(set(names) & (set(self.parameters) | set(self.overrides)))
        if clashing:
            raise fail(f"sweep: {', '.join(name_for_message(name) for name in clashing)} is both swept and fixed",
                       REFERENCE_INVALID)
        check_number(self.repetitions, "sweep.repetitions", minimum=1, maximum=MAX_REPETITIONS, integer=True)
        if self.scenario is not None and not isinstance(self.scenario, Scenario):
            raise fail("sweep.scenario must be a Scenario or null")
        check_text(self.title, "sweep.title", max_chars=MAX_SWEEP_TITLE_CHARS, optional=True)
        check_text(self.description, "sweep.description", max_chars=MAX_SWEEP_DESCRIPTION_CHARS, optional=True)
        if self.point_count > MAX_SWEEP_POINTS:
            raise fail(f"sweep expands to {self.point_count} points, over {MAX_SWEEP_POINTS}", LIMIT_EXCEEDED)
        if self.run_count > MAX_SWEEP_RUNS:
            raise fail(f"sweep would start {self.run_count} runs, over {MAX_SWEEP_RUNS}", LIMIT_EXCEEDED)

    @property
    def point_count(self) -> int:
        """Distinct parameter combinations (the cartesian product of the axes)."""
        total = 1
        for item in self.swept:
            total *= len(item.values)
        return total

    @property
    def run_count(self) -> int:
        return self.point_count * self.repetitions

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SWEEP_SPEC_SCHEMA,
            "schema_version": self.schema_version,
            "diagnostic_id": self.diagnostic_id,
            "profile": self.profile.value,
            "version": self.version,
            "parameters": dict(self.parameters),
            "overrides": dict(self.overrides),
            "swept": [item.to_dict() for item in self.swept],
            "repetitions": self.repetitions,
            "scenario": None if self.scenario is None else self.scenario.to_dict(),
            "title": self.title,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, payload: object) -> SweepSpec:
        scan_private(payload, "sweep")
        data = exact_fields(payload, _SPEC_FIELDS, "sweep")
        check_document_header(data, SWEEP_SPEC_SCHEMA, TESTLAB_SCHEMA_VERSION, "sweep")
        if not isinstance(data["swept"], list):
            raise fail("sweep.swept must be a list")
        return cls(
            diagnostic_id=data["diagnostic_id"],
            profile=decode_enum(ProfileName, data["profile"], "sweep.profile"),
            version=data["version"],
            parameters=data["parameters"],
            overrides=data["overrides"],
            swept=tuple(SweptParameter.from_dict(item) for item in data["swept"]),
            repetitions=data["repetitions"],
            scenario=None if data["scenario"] is None else Scenario.from_dict(data["scenario"],
                                                                              primitives=SHAPE_ONLY),
            title=data["title"],
            description=data["description"],
        )

    def fingerprint(self) -> str:
        """Content fingerprint of the declaration: two identical sweeps compare as one experiment."""
        return content_fingerprint(self.to_dict())


_SPEC_FIELDS = frozenset({"schema", "schema_version", "diagnostic_id", "profile", "version", "parameters",
                          "overrides", "swept", "repetitions", "scenario", "title", "description"})


@dataclass(frozen=True, slots=True)
class SweepPoint:
    """One combination of swept values, with the effective inputs of its runs."""

    index: int
    #: The swept values only, keyed by name: what distinguishes this point.
    values: Mapping[str, Scalar]
    #: Base parameters merged with the swept parameters of this point.
    parameters: Mapping[str, Scalar]
    #: Base overrides merged with the swept overrides of this point.
    overrides: Mapping[str, Scalar]

    def __post_init__(self) -> None:
        check_number(self.index, "point.index", minimum=0, maximum=MAX_SWEEP_POINTS, integer=True)
        for name in ("values", "parameters", "overrides"):
            object.__setattr__(self, name, freeze_scalar_map(getattr(self, name), f"point.{name}",
                                                             limit=MAX_PARAMETERS + MAX_OVERRIDES))

    @property
    def label(self) -> str:
        """Readable identity of the point: `name=value` pairs, sorted, for logs and reports."""
        return " ".join(f"{name}={self.values[name]}" for name in sorted(self.values))

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "values": dict(self.values), "parameters": dict(self.parameters),
                "overrides": dict(self.overrides)}

    @classmethod
    def from_dict(cls, payload: object) -> SweepPoint:
        data = exact_fields(payload, frozenset({"index", "values", "parameters", "overrides"}), "point")
        return cls(data["index"], data["values"], data["parameters"], data["overrides"])


def expand_points(spec: SweepSpec) -> tuple[SweepPoint, ...]:
    """The cartesian product of the axes, in declaration order, last axis varying fastest.

    Deterministic and total: the same spec always expands to the same points, in the
    same order, which is what makes a sweep replayable from its stored declaration.
    """
    if not isinstance(spec, SweepSpec):
        raise fail("expand_points takes a SweepSpec")
    combinations: list[list[tuple[SweptParameter, Scalar]]] = [[]]
    for axis in spec.swept:
        combinations = [combination + [(axis, value)] for combination in combinations for value in axis.values]
    points: list[SweepPoint] = []
    for index, combination in enumerate(combinations):
        parameters = dict(spec.parameters)
        overrides = dict(spec.overrides)
        values: dict[str, Scalar] = {}
        for axis, value in combination:
            values[axis.name] = value
            target = parameters if axis.target is SweepTarget.PARAMETER else overrides
            target[axis.name] = value
        points.append(SweepPoint(index, values, parameters, overrides))
    return tuple(points)


def check_sweep_spec(spec: SweepSpec, diagnostic: DiagnosticSpec,
                     override_allowlist: Sequence[ParameterSpec] = ()) -> tuple[SweepPoint, ...]:
    """Validate a sweep against the declaration it will run, and return its points.

    Every swept and fixed value is checked with `check_parameter_value`, exactly as a
    single run's would be, so a sweep can never reach a value, a setting or a profile a
    single `RunRequest` could not. Raises `SweepError` on the first violation.
    """
    if not isinstance(spec, SweepSpec) or not isinstance(diagnostic, DiagnosticSpec):
        raise SweepError(SWEEP_INVALID, "check_sweep_spec takes a SweepSpec and its DiagnosticSpec")
    if spec.diagnostic_id != diagnostic.diagnostic_id:
        raise SweepError(SWEEP_INVALID, "the sweep names another diagnostic than the declaration supplied")
    if spec.profile not in diagnostic.profiles:
        raise SweepError(SWEEP_INVALID,
                         f"{diagnostic.diagnostic_id} does not declare profile {spec.profile.value}")
    declared = {item.name: item for item in diagnostic.parameters}
    allowed = {item.name: item for item in override_allowlist}
    _check_values(spec.parameters, declared, SweepTarget.PARAMETER, "parameters")
    _check_values(spec.overrides, allowed, SweepTarget.OVERRIDE, "overrides")
    for axis in spec.swept:
        index = declared if axis.target is SweepTarget.PARAMETER else allowed
        parameter = index.get(axis.name)
        if parameter is None:
            raise SweepError(SWEEP_INVALID, f"swept {axis.target.value} {name_for_message(axis.name)} is not "
                                            + ("declared by the diagnostic" if axis.target is SweepTarget.PARAMETER
                                               else "in the manifest override allowlist"))
        for position, value in enumerate(axis.values):
            try:
                check_parameter_value(parameter, value, f"swept.{axis.name}[{position}]")
            except TestLabError as exc:
                raise SweepError(SWEEP_INVALID, exc.detail) from None
    points = expand_points(spec)
    for point in points:
        try:
            resolve_parameters(diagnostic.parameters, point.parameters)
        except TestLabError as exc:
            raise SweepError(SWEEP_INVALID, exc.detail) from None
    return points


def _check_values(values: Mapping[str, Scalar], index: Mapping[str, ParameterSpec], target: SweepTarget,
                  where: str) -> None:
    for name, value in values.items():
        parameter = index.get(name)
        if parameter is None:
            raise SweepError(SWEEP_INVALID, f"sweep.{where}.{name_for_message(name)} is not "
                                            + ("a declared parameter" if target is SweepTarget.PARAMETER
                                               else "in the manifest override allowlist"))
        try:
            check_parameter_value(parameter, value, f"sweep.{where}.{name}")
        except TestLabError as exc:
            raise SweepError(SWEEP_INVALID, exc.detail) from None


# ---------------------------------------------------------------- record

class SweepStatus(StrEnum):
    RUNNING = "running"
    #: Every point was executed; individual points may still have failed.
    COMPLETED = "completed"
    #: A caller stopped the sweep; the points already executed are kept.
    CANCELLED = "cancelled"
    #: The sweep itself could not proceed (the store, the supervisor, the catalog).
    FAILED = "failed"


SWEEP_TERMINAL_STATUSES = frozenset({SweepStatus.COMPLETED, SweepStatus.CANCELLED, SweepStatus.FAILED})


@dataclass(frozen=True, slots=True)
class SweepRunOutcome:
    """One run of one point, as the sweep record keeps it."""

    run_id: str
    status: RunStatus
    outcome: RunOutcomeClass
    failure_code: str | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        check_run_id(self.run_id)
        check_enum(RunStatus, self.status, "sweep run.status")
        check_enum(RunOutcomeClass, self.outcome, "sweep run.outcome")
        check_name(self.failure_code, "sweep run.failure_code", optional=True)
        if self.score is not None:
            check_number(self.score, "sweep run.score", minimum=0, maximum=100)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "status": self.status.value, "outcome": self.outcome.value,
                "failure_code": self.failure_code, "score": self.score}

    @classmethod
    def from_dict(cls, payload: object) -> SweepRunOutcome:
        data = exact_fields(payload, frozenset({"run_id", "status", "outcome", "failure_code", "score"}), "sweep run")
        return cls(data["run_id"], decode_enum(RunStatus, data["status"], "sweep run.status"),
                   decode_enum(RunOutcomeClass, data["outcome"], "sweep run.outcome"), data["failure_code"],
                   data["score"])


@dataclass(frozen=True, slots=True)
class SweepPointResult:
    """One point of the sweep and every run it produced. A failed point never abandons the sweep."""

    point: SweepPoint
    runs: tuple[SweepRunOutcome, ...] = ()
    #: Why no run could be started for this point at all (never a product verdict).
    failure: RunFailure | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.point, SweepPoint):
            raise fail("point result needs a SweepPoint")
        if not isinstance(self.runs, tuple) or any(not isinstance(item, SweepRunOutcome) for item in self.runs):
            raise fail("point.runs must be a tuple of SweepRunOutcome")
        if self.failure is not None and not isinstance(self.failure, RunFailure):
            raise fail("point.failure must be a RunFailure or null")

    @property
    def outcomes(self) -> tuple[RunOutcomeClass, ...]:
        return tuple(run.outcome for run in self.runs)

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(run.run_id for run in self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {"point": self.point.to_dict(), "runs": [run.to_dict() for run in self.runs],
                "failure": None if self.failure is None else self.failure.to_dict()}

    @classmethod
    def from_dict(cls, payload: object) -> SweepPointResult:
        data = exact_fields(payload, frozenset({"point", "runs", "failure"}), "point result")
        if not isinstance(data["runs"], list):
            raise fail("point.runs must be a list")
        return cls(SweepPoint.from_dict(data["point"]),
                   tuple(SweepRunOutcome.from_dict(item) for item in data["runs"]),
                   None if data["failure"] is None else RunFailure.from_dict(data["failure"]))


@dataclass(frozen=True, slots=True)
class SweepRecord:
    """The persisted sweep: its declaration, every point it ran, and how it ended.

    It is written when the sweep starts and rewritten as points finish, so a human
    watching a long sweep sees progress and a crashed orchestrator leaves evidence
    of what had already run.
    """

    sweep_id: str
    created_at: datetime
    spec: SweepSpec
    status: SweepStatus
    #: Resolved once for the whole sweep: every run is judged by the same declaration.
    diagnostic_version: int
    diagnostic_fingerprint: str
    points: tuple[SweepPointResult, ...] = ()
    finished_at: datetime | None = None
    failure: RunFailure | None = None
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        check_sweep_id(self.sweep_id)
        if self.sweep_id.split("-")[1] != id_timestamp(self.created_at):
            raise fail("created_at must equal the time embedded in sweep_id")
        if not isinstance(self.spec, SweepSpec):
            raise fail("sweep record needs a SweepSpec")
        check_enum(SweepStatus, self.status, "sweep.status")
        check_diagnostic_version(self.diagnostic_version, "sweep.diagnostic_version")
        check_hex(self.diagnostic_fingerprint, "sweep.diagnostic_fingerprint", lengths=(64,))
        if not isinstance(self.points, tuple) or any(not isinstance(item, SweepPointResult) for item in self.points):
            raise fail("sweep.points must be a tuple of SweepPointResult")
        if len(self.points) > MAX_SWEEP_POINTS:
            raise fail(f"sweep.points exceed {MAX_SWEEP_POINTS} entries", LIMIT_EXCEEDED)
        if (self.finished_at is not None) != (self.status in SWEEP_TERMINAL_STATUSES):
            raise fail("finished_at is set exactly when the sweep status is terminal")
        if self.finished_at is not None and self.finished_at < self.created_at:
            raise fail("finished_at must not precede created_at")
        if self.failure is not None and not isinstance(self.failure, RunFailure):
            raise fail("sweep.failure must be a RunFailure or null")
        if (self.status is SweepStatus.FAILED) and self.failure is None:
            raise fail("a failed sweep records why")

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(run_id for point in self.points for run_id in point.run_ids)

    def outcome_counts(self) -> Mapping[str, int]:
        """How many runs of this sweep ended in each outcome, sorted by outcome name."""
        counts: dict[str, int] = {}
        for point in self.points:
            for outcome in point.outcomes:
                counts[outcome.value] = counts.get(outcome.value, 0) + 1
        return MappingProxyType(dict(sorted(counts.items())))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SWEEP_RECORD_SCHEMA,
            "schema_version": self.schema_version,
            "sweep_id": self.sweep_id,
            "created_at": format_time(self.created_at),
            "finished_at": format_time(self.finished_at),
            "status": self.status.value,
            "diagnostic_version": self.diagnostic_version,
            "diagnostic_fingerprint": self.diagnostic_fingerprint,
            "spec": self.spec.to_dict(),
            "points": [item.to_dict() for item in self.points],
            "failure": None if self.failure is None else self.failure.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: object) -> SweepRecord:
        scan_private(payload, "sweep record")
        data = exact_fields(payload, _RECORD_FIELDS, "sweep record")
        check_document_header(data, SWEEP_RECORD_SCHEMA, TESTLAB_SCHEMA_VERSION, "sweep record")
        if not isinstance(data["points"], list):
            raise fail("sweep.points must be a list")
        if data["created_at"] is None:
            raise fail("sweep created_at is required")
        return cls(
            sweep_id=data["sweep_id"],
            created_at=parse_time(data["created_at"], "created_at"),
            spec=SweepSpec.from_dict(data["spec"]),
            status=decode_enum(SweepStatus, data["status"], "sweep.status"),
            diagnostic_version=data["diagnostic_version"],
            diagnostic_fingerprint=data["diagnostic_fingerprint"],
            points=tuple(SweepPointResult.from_dict(item) for item in data["points"]),
            finished_at=parse_time(data["finished_at"], "finished_at", optional=True),
            failure=None if data["failure"] is None else RunFailure.from_dict(data["failure"]),
        )


_RECORD_FIELDS = frozenset({"schema", "schema_version", "sweep_id", "created_at", "finished_at", "status",
                            "diagnostic_version", "diagnostic_fingerprint", "spec", "points", "failure"})


def sweep_failure(detail: str) -> RunFailure:
    """A bounded `RunFailure` for a sweep-level problem (the code is always `sweep_failed`)."""
    return RunFailure("sweep_failed", detail[:MAX_FAILURE_DETAIL_CHARS])
