"""Test Lab diagnostic declarations: parameters, metrics, assertions, score, `DiagnosticSpec`.

Binding contract: `docs/testlab.md` ("Diagnostics", "Parameters", "Metrics,
assertions and score"). Pure declarations plus the value checks that give them
meaning. Assertions are primary: a blocking assertion that fails fails the run
whatever the score. The score is a declared synthesis computed by Slice 07.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from jarvis.testlab.identity import (
    DIAGNOSTIC_SPEC_SCHEMA,
    TESTLAB_SCHEMA_VERSION,
    check_diagnostic_id,
    check_diagnostic_version,
    diagnostic_domain,
)
from jarvis.testlab.profiles import ProfileName, ProfileSpec, profiles_by_name
from jarvis.testlab.validation import (
    FORBIDDEN_PRIVATE_DATA,
    LIMIT_EXCEEDED,
    MAX_JSON_TEXT_CHARS,
    MAX_STRING_VALUE_CHARS,
    PARAMETER_INVALID,
    REFERENCE_INVALID,
    SIMPLE_NAME,
    ForbiddenCodeError,
    TestLabError,
    TestLabRedactionError,
    check_bool,
    check_document_header,
    check_enum,
    check_name,
    check_open_key,
    check_number,
    check_scalar_value,
    check_text,
    content_fingerprint,
    decode_enum,
    exact_fields,
    fail,
    is_private_key,
    name_for_message,
    scan_private,
)

MAX_PARAMETERS = 32
MAX_METRICS = 64
MAX_ASSERTIONS = 64
MAX_SCORE_COMPONENTS = 16
MAX_ENUM_CHOICES = 32
MAX_TITLE_CHARS = 120
MAX_DESCRIPTION_CHARS = 512
MAX_SCORE_WEIGHT = 1000
SCORE_MIN = 0.0
SCORE_MAX = 100.0

Scalar = bool | int | float | str
MetricValue = bool | int | float


def _description(value: object, name: str) -> None:
    check_text(value, name, max_chars=MAX_DESCRIPTION_CHARS, optional=True)


def _unique(names: Iterable[str], what: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise fail(f"{what} {name_for_message(name)} is declared twice")
        seen.add(name)


def _tuple_of(values: object, cls: type, name: str, limit: int) -> None:
    if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
        raise fail(f"{name} must be a tuple of {cls.__name__}")
    if len(values) > limit:
        raise fail(f"{name} exceeds {limit} entries", LIMIT_EXCEEDED)


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise fail(f"{name} must be a list")
    return value


# -------------------------------------------------------------- parameters

class ParameterType(StrEnum):
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    STR = "str"
    ENUM = "enum"


def freeze_scalar_map(values: object, path: str, *, limit: int = MAX_PARAMETERS) -> Mapping[str, Scalar]:
    """Validated read-only `{dotted name: JSON scalar}` map (effective parameters, overrides)."""
    if not isinstance(values, Mapping):
        raise fail(f"{path} must be an object")
    if len(values) > limit:
        raise fail(f"{path} exceeds {limit} entries", LIMIT_EXCEEDED)
    frozen: dict[str, Scalar] = {}
    for key, value in values.items():
        check_open_key(key, path)
        check_scalar_value(value, f"{path}.{key}")
        frozen[key] = value
    return MappingProxyType(dict(sorted(frozen.items())))


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """One typed, bounded input of a diagnostic (also usable to describe an overridable setting)."""

    name: str
    type: ParameterType
    default: Scalar
    minimum: int | float | None = None
    maximum: int | float | None = None
    choices: tuple[str, ...] = ()
    max_length: int | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        check_open_key(self.name, "parameter")
        where = f"parameter {self.name}"
        check_enum(ParameterType, self.type, f"{where}.type")
        numeric = self.type in (ParameterType.INT, ParameterType.FLOAT)
        if not numeric and (self.minimum is not None or self.maximum is not None):
            raise fail(f"{where}: minimum/maximum apply to int and float only")
        if numeric:
            for bound in ("minimum", "maximum"):
                value = getattr(self, bound)
                if value is not None:
                    check_number(value, f"{where}.{bound}", integer=self.type is ParameterType.INT)
            if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
                raise fail(f"{where}: minimum must be <= maximum")
        if not isinstance(self.choices, tuple):
            raise fail(f"{where}.choices must be a tuple")
        if self.type is ParameterType.ENUM:
            if not 1 <= len(self.choices) <= MAX_ENUM_CHOICES:
                raise fail(f"{where}: enum needs 1 to {MAX_ENUM_CHOICES} choices")
            for index, choice in enumerate(self.choices):
                path = f"{where}.choices[{index}]"
                check_text(choice, path, max_chars=64)
                check_scalar_value(choice, path)  # a choice is a value: only the value code heuristic applies
            _unique(self.choices, f"{where} choice")
        elif self.choices:
            raise fail(f"{where}: choices apply to enum only")
        if self.type is ParameterType.STR:
            if self.max_length is not None:
                check_number(self.max_length, f"{where}.max_length", minimum=1, maximum=MAX_STRING_VALUE_CHARS,
                             integer=True)
        elif self.max_length is not None:
            raise fail(f"{where}: max_length applies to str only")
        _description(self.description, f"{where}.description")
        object.__setattr__(self, "default", check_parameter_value(self, self.default, f"{where}.default"))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type.value, "default": self.default, "minimum": self.minimum,
                "maximum": self.maximum, "choices": list(self.choices), "max_length": self.max_length,
                "description": self.description}

    @classmethod
    def from_dict(cls, payload: object) -> ParameterSpec:
        data = exact_fields(payload, _PARAMETER_FIELDS, "parameter")
        return cls(data["name"], decode_enum(ParameterType, data["type"], "parameter.type"), data["default"],
                   data["minimum"], data["maximum"], tuple(_list(data["choices"], "parameter.choices")),
                   data["max_length"], data["description"])


_PARAMETER_FIELDS = frozenset({"name", "type", "default", "minimum", "maximum", "choices", "max_length",
                               "description"})


def check_parameter_value(spec: ParameterSpec, value: object, path: str) -> Scalar:
    """Validate one value against its spec. Returns it normalized (an int for a float becomes float)."""
    try:
        check_scalar_value(value, path)
        if spec.type is ParameterType.BOOL:
            check_bool(value, path)
            return value
        if spec.type in (ParameterType.INT, ParameterType.FLOAT):
            check_number(value, path, minimum=spec.minimum, maximum=spec.maximum,
                         integer=spec.type is ParameterType.INT)
            return float(value) if spec.type is ParameterType.FLOAT else value
        if not isinstance(value, str):
            raise fail(f"{path} must be a string")
        if spec.type is ParameterType.ENUM:
            if value not in spec.choices:
                raise fail(f"{path} is not one of the declared choices")
            return value
        limit = spec.max_length if spec.max_length is not None else MAX_JSON_TEXT_CHARS
        if len(value) > limit:
            raise fail(f"{path} exceeds {limit} characters")
        return value
    except (TestLabRedactionError, ForbiddenCodeError):
        raise
    except TestLabError as exc:
        # Every parameter violation shares one stable code; the detail keeps the precise rule.
        raise fail(exc.detail, PARAMETER_INVALID) from None


def resolve_parameters(specs: tuple[ParameterSpec, ...], supplied: Mapping[str, object]) -> Mapping[str, Scalar]:
    """Effective values: every declared parameter, supplied value or default. Unknown keys are rejected."""
    _tuple_of(specs, ParameterSpec, "parameters", MAX_PARAMETERS)
    if not isinstance(supplied, Mapping):
        raise fail("supplied parameters must be an object", PARAMETER_INVALID)
    by_name = {spec.name: spec for spec in specs}
    for key in supplied:
        check_open_key(key, "parameters")
        if key not in by_name:
            raise fail(f"parameters.{name_for_message(key)} is not declared", PARAMETER_INVALID)
    resolved = {name: check_parameter_value(spec, supplied[name], f"parameters.{name}") if name in supplied
                else spec.default for name, spec in sorted(by_name.items())}
    return MappingProxyType(resolved)


# ---------------------------------------------------------------- metrics

class MetricUnit(StrEnum):
    MS = "ms"
    SECONDS = "s"
    COUNT = "count"
    #: 0..1.
    RATIO = "ratio"
    #: 0..100.
    PERCENT = "percent"
    BOOLEAN = "boolean"
    DB = "db"
    HZ = "hz"
    USD = "usd"
    CHARS = "chars"


class MetricDirection(StrEnum):
    HIGHER_BETTER = "higher_better"
    LOWER_BETTER = "lower_better"
    #: Informational: comparisons show a difference, never an improvement.
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    unit: MetricUnit
    direction: MetricDirection
    description: str | None = None

    def __post_init__(self) -> None:
        check_name(self.name, "metric.name")
        if is_private_key(self.name):
            raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA, "metric.name: forbidden name (private data)")
        check_enum(MetricUnit, self.unit, f"metric {self.name}.unit")
        check_enum(MetricDirection, self.direction, f"metric {self.name}.direction")
        _description(self.description, f"metric {self.name}.description")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "unit": self.unit.value, "direction": self.direction.value,
                "description": self.description}

    @classmethod
    def from_dict(cls, payload: object) -> MetricSpec:
        data = exact_fields(payload, _METRIC_FIELDS, "metric")
        return cls(data["name"], decode_enum(MetricUnit, data["unit"], "metric.unit"),
                   decode_enum(MetricDirection, data["direction"], "metric.direction"), data["description"])


_METRIC_FIELDS = frozenset({"name", "unit", "direction", "description"})


def check_metric_value(spec: MetricSpec, value: object, path: str) -> None:
    """A measured value fits its unit: boolean for `boolean`, finite number otherwise (bounded where natural)."""
    if spec.unit is MetricUnit.BOOLEAN:
        check_bool(value, path)
        return
    integer = spec.unit in (MetricUnit.COUNT, MetricUnit.CHARS)
    minimum = 0 if spec.unit in (MetricUnit.COUNT, MetricUnit.CHARS, MetricUnit.RATIO, MetricUnit.PERCENT) else None
    maximum = {MetricUnit.RATIO: 1, MetricUnit.PERCENT: 100}.get(spec.unit)
    check_number(value, path, minimum=minimum, maximum=maximum, integer=integer)


# ------------------------------------------------------------- assertions

class Comparator(StrEnum):
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    EQ = "eq"
    NE = "ne"


_COMPARE = {
    Comparator.LT: lambda observed, threshold: observed < threshold,
    Comparator.LE: lambda observed, threshold: observed <= threshold,
    Comparator.GT: lambda observed, threshold: observed > threshold,
    Comparator.GE: lambda observed, threshold: observed >= threshold,
    Comparator.EQ: lambda observed, threshold: observed == threshold,
    Comparator.NE: lambda observed, threshold: observed != threshold,
}


@dataclass(frozen=True, slots=True)
class AssertionSpec:
    """`metric <comparator> threshold`. `blocking`: a failure fails the run, whatever the score."""

    assertion_id: str
    metric: str
    comparator: Comparator
    threshold: MetricValue
    blocking: bool
    description: str | None = None

    def __post_init__(self) -> None:
        check_name(self.assertion_id, "assertion.assertion_id")
        where = f"assertion {self.assertion_id}"
        check_name(self.metric, f"{where}.metric")
        check_enum(Comparator, self.comparator, f"{where}.comparator")
        if type(self.threshold) is not bool:
            check_number(self.threshold, f"{where}.threshold")
        check_bool(self.blocking, f"{where}.blocking")
        _description(self.description, f"{where}.description")

    def to_dict(self) -> dict[str, Any]:
        return {"assertion_id": self.assertion_id, "metric": self.metric, "comparator": self.comparator.value,
                "threshold": self.threshold, "blocking": self.blocking, "description": self.description}

    @classmethod
    def from_dict(cls, payload: object) -> AssertionSpec:
        data = exact_fields(payload, _ASSERTION_FIELDS, "assertion")
        return cls(data["assertion_id"], data["metric"],
                   decode_enum(Comparator, data["comparator"], "assertion.comparator"), data["threshold"],
                   data["blocking"], data["description"])


_ASSERTION_FIELDS = frozenset({"assertion_id", "metric", "comparator", "threshold", "blocking", "description"})


class AssertionOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    #: The metric was not measured: no evidence, never a pass.
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class AssertionResult:
    assertion_id: str
    outcome: AssertionOutcome
    blocking: bool
    #: The measured metric value; None exactly when the outcome is `missing`.
    observed: MetricValue | None = None

    def __post_init__(self) -> None:
        check_name(self.assertion_id, "assertion_result.assertion_id")
        where = f"assertion_result {self.assertion_id}"
        check_enum(AssertionOutcome, self.outcome, f"{where}.outcome")
        check_bool(self.blocking, f"{where}.blocking")
        if (self.observed is None) != (self.outcome is AssertionOutcome.MISSING):
            raise fail(f"{where}: observed must be null exactly when the outcome is missing")
        if self.observed is not None and type(self.observed) is not bool:
            check_number(self.observed, f"{where}.observed")

    def to_dict(self) -> dict[str, Any]:
        return {"assertion_id": self.assertion_id, "outcome": self.outcome.value, "blocking": self.blocking,
                "observed": self.observed}

    @classmethod
    def from_dict(cls, payload: object) -> AssertionResult:
        data = exact_fields(payload, _ASSERTION_RESULT_FIELDS, "assertion_result")
        return cls(data["assertion_id"], decode_enum(AssertionOutcome, data["outcome"], "assertion_result.outcome"),
                   data["blocking"], data["observed"])


_ASSERTION_RESULT_FIELDS = frozenset({"assertion_id", "outcome", "blocking", "observed"})


#: Units whose values compare exactly: the only ones `eq` / `ne` accept. Measured
#: durations, ratios and levels are floats, where exact equality is noise (0.1 + 0.2 != 0.3).
EXACT_UNITS = frozenset({MetricUnit.COUNT, MetricUnit.CHARS, MetricUnit.BOOLEAN})


def _check_threshold_fits(assertion: AssertionSpec, metric: MetricSpec) -> None:
    where = f"assertion {assertion.assertion_id}"
    if metric.unit is MetricUnit.BOOLEAN:
        if type(assertion.threshold) is not bool or assertion.comparator not in (Comparator.EQ, Comparator.NE):
            raise fail(f"{where}: a boolean metric takes a boolean threshold with eq or ne", REFERENCE_INVALID)
        return
    if type(assertion.threshold) is bool:
        raise fail(f"{where}: a numeric metric takes a numeric threshold", REFERENCE_INVALID)
    try:
        check_metric_value(metric, assertion.threshold, f"{where}.threshold")
    except TestLabError as exc:
        raise fail(f"{exc.detail} (threshold must fit the metric unit)", REFERENCE_INVALID) from None
    if assertion.comparator in (Comparator.EQ, Comparator.NE) and metric.unit not in EXACT_UNITS:
        raise fail(f"{where}: eq and ne apply only to count, chars and boolean metrics; use lt/le/gt/ge",
                   REFERENCE_INVALID)


def evaluate_assertion(assertion: AssertionSpec, metric: MetricSpec, value: MetricValue | None) -> AssertionResult:
    """Pure comparison of one measured value (None: not measured) against its assertion."""
    if not isinstance(assertion, AssertionSpec) or not isinstance(metric, MetricSpec):
        raise fail("evaluate_assertion takes an AssertionSpec and its MetricSpec")
    if assertion.metric != metric.name:
        raise fail(f"assertion {assertion.assertion_id} does not measure metric {metric.name}", REFERENCE_INVALID)
    _check_threshold_fits(assertion, metric)
    if value is None:
        return AssertionResult(assertion.assertion_id, AssertionOutcome.MISSING, assertion.blocking)
    check_metric_value(metric, value, f"metrics.{metric.name}")
    passed = _COMPARE[assertion.comparator](value, assertion.threshold)
    outcome = AssertionOutcome.PASSED if passed else AssertionOutcome.FAILED
    return AssertionResult(assertion.assertion_id, outcome, assertion.blocking, value)


class AssertionVerdict(StrEnum):
    PASSED = "passed"
    #: At least one blocking assertion failed.
    FAILED = "failed"
    #: No blocking failure, but a blocking assertion is missing or none was evaluated.
    INCONCLUSIVE = "inconclusive"


def assertions_verdict(results: Iterable[AssertionResult]) -> AssertionVerdict:
    """Blocking assertions decide; non-blocking ones and the score never do."""
    blocking = [result for result in results if _result(result).blocking]
    if any(result.outcome is AssertionOutcome.FAILED for result in blocking):
        return AssertionVerdict.FAILED
    if not blocking or any(result.outcome is AssertionOutcome.MISSING for result in blocking):
        return AssertionVerdict.INCONCLUSIVE
    return AssertionVerdict.PASSED


def _result(value: object) -> AssertionResult:
    if not isinstance(value, AssertionResult):
        raise fail("assertion results must be AssertionResult values")
    return value


# ------------------------------------------------------------------ score

class ScoreMethod(StrEnum):
    #: The diagnostic declares no score; the run score is null.
    NONE = "none"
    #: Weighted mean of components, each mapped linearly from worst (0) to best (100), clamped.
    WEIGHTED_MEAN = "weighted_mean"


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    metric: str
    weight: float
    #: Metric value scoring 100.
    best: float
    #: Metric value scoring 0. Must differ from `best`; its side gives the direction.
    worst: float

    def __post_init__(self) -> None:
        check_name(self.metric, "score.component.metric")
        where = f"score component {self.metric}"
        check_number(self.weight, f"{where}.weight", maximum=MAX_SCORE_WEIGHT)
        if self.weight <= 0:
            raise fail(f"{where}.weight must be > 0")
        check_number(self.best, f"{where}.best")
        check_number(self.worst, f"{where}.worst")
        if self.best == self.worst:
            raise fail(f"{where}: best and worst must differ")

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "weight": self.weight, "best": self.best, "worst": self.worst}

    @classmethod
    def from_dict(cls, payload: object) -> ScoreComponent:
        data = exact_fields(payload, _COMPONENT_FIELDS, "score.component")
        return cls(data["metric"], data["weight"], data["best"], data["worst"])


_COMPONENT_FIELDS = frozenset({"metric", "weight", "best", "worst"})


@dataclass(frozen=True, slots=True)
class ScoreContract:
    method: ScoreMethod = ScoreMethod.NONE
    components: tuple[ScoreComponent, ...] = ()

    def __post_init__(self) -> None:
        check_enum(ScoreMethod, self.method, "score.method")
        _tuple_of(self.components, ScoreComponent, "score.components", MAX_SCORE_COMPONENTS)
        if (self.method is ScoreMethod.NONE) != (not self.components):
            raise fail("score: method none takes no component, weighted_mean needs at least one")
        _unique((component.metric for component in self.components), "score component")

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method.value, "components": [component.to_dict() for component in self.components]}

    @classmethod
    def from_dict(cls, payload: object) -> ScoreContract:
        data = exact_fields(payload, _SCORE_FIELDS, "score")
        return cls(decode_enum(ScoreMethod, data["method"], "score.method"),
                   tuple(ScoreComponent.from_dict(item) for item in _list(data["components"], "score.components")))


_SCORE_FIELDS = frozenset({"method", "components"})


# ---------------------------------------------------------- DiagnosticSpec

@dataclass(frozen=True, slots=True)
class DiagnosticSpec:
    """Stable identity of one diagnostic and everything a run of it is judged by.

    Constructing validates every cross-reference: an invalid spec never exists in memory.
    """

    diagnostic_id: str
    version: int
    title: str
    domain: str
    #: Supported profiles, keyed by name (read-only; wire form is a list in vocabulary order).
    profiles: Mapping[ProfileName, ProfileSpec]
    metrics: tuple[MetricSpec, ...]
    assertions: tuple[AssertionSpec, ...]
    score: ScoreContract = field(default_factory=ScoreContract)
    parameters: tuple[ParameterSpec, ...] = ()
    description: str | None = None
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __hash__(self) -> int:
        return hash((self.diagnostic_id, self.version))

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        check_diagnostic_id(self.diagnostic_id)
        check_diagnostic_version(self.version, "version")
        check_text(self.title, "title", max_chars=MAX_TITLE_CHARS)
        check_name(self.domain, "domain", pattern=SIMPLE_NAME)
        if self.domain != diagnostic_domain(self.diagnostic_id):
            raise fail("domain must equal the first segment of diagnostic_id", REFERENCE_INVALID)
        _description(self.description, "description")
        if not isinstance(self.profiles, Mapping) or not self.profiles:
            raise fail("profiles must map at least one profile name to its ProfileSpec")
        indexed = profiles_by_name(self.profiles.values())
        if any(key is not spec.name for key, spec in zip(self.profiles, self.profiles.values())):
            raise fail("profiles keys must equal each ProfileSpec name", REFERENCE_INVALID)
        object.__setattr__(self, "profiles", MappingProxyType({name: indexed[name] for name in ProfileName
                                                              if name in indexed}))
        _tuple_of(self.parameters, ParameterSpec, "parameters", MAX_PARAMETERS)
        _unique((parameter.name for parameter in self.parameters), "parameter")
        _tuple_of(self.metrics, MetricSpec, "metrics", MAX_METRICS)
        if not self.metrics:
            raise fail("metrics must declare at least one metric")
        _unique((metric.name for metric in self.metrics), "metric")
        _tuple_of(self.assertions, AssertionSpec, "assertions", MAX_ASSERTIONS)
        _unique((assertion.assertion_id for assertion in self.assertions), "assertion")
        if not any(assertion.blocking for assertion in self.assertions):
            raise fail("assertions must declare at least one blocking assertion")
        metrics = self.metric_index
        for assertion in self.assertions:
            metric = metrics.get(assertion.metric)
            if metric is None:
                raise fail(f"assertion {assertion.assertion_id} references an undeclared metric", REFERENCE_INVALID)
            _check_threshold_fits(assertion, metric)
        if not isinstance(self.score, ScoreContract):
            raise fail("score must be a ScoreContract")
        for component in self.score.components:
            metric = metrics.get(component.metric)
            if metric is None or metric.unit is MetricUnit.BOOLEAN:
                raise fail(f"score component {component.metric} must reference a declared numeric metric",
                           REFERENCE_INVALID)
            if ((metric.direction is MetricDirection.HIGHER_BETTER and component.best < component.worst)
                    or (metric.direction is MetricDirection.LOWER_BETTER and component.best > component.worst)):
                raise fail(f"score component {component.metric}: best/worst contradict the metric direction",
                           REFERENCE_INVALID)

    @property
    def metric_index(self) -> Mapping[str, MetricSpec]:
        return {metric.name: metric for metric in self.metrics}

    @property
    def assertion_index(self) -> Mapping[str, AssertionSpec]:
        return {assertion.assertion_id: assertion for assertion in self.assertions}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DIAGNOSTIC_SPEC_SCHEMA,
            "schema_version": self.schema_version,
            "diagnostic_id": self.diagnostic_id,
            "version": self.version,
            "title": self.title,
            "domain": self.domain,
            "description": self.description,
            "profiles": [profile.to_dict() for profile in self.profiles.values()],
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "metrics": [metric.to_dict() for metric in self.metrics],
            "assertions": [assertion.to_dict() for assertion in self.assertions],
            "score": self.score.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: object) -> DiagnosticSpec:
        """Strict decode: redaction scan first, exact fields, schema and version, then full validation."""
        scan_private(payload, "diagnostic")
        data = exact_fields(payload, _SPEC_FIELDS, "diagnostic")
        check_document_header(data, DIAGNOSTIC_SPEC_SCHEMA, TESTLAB_SCHEMA_VERSION, "diagnostic")
        profiles = [ProfileSpec.from_dict(item) for item in _list(data["profiles"], "profiles")]
        return cls(
            data["diagnostic_id"], data["version"], data["title"], data["domain"],
            profiles_by_name(profiles),
            tuple(MetricSpec.from_dict(item) for item in _list(data["metrics"], "metrics")),
            tuple(AssertionSpec.from_dict(item) for item in _list(data["assertions"], "assertions")),
            ScoreContract.from_dict(data["score"]),
            tuple(ParameterSpec.from_dict(item) for item in _list(data["parameters"], "parameters")),
            data["description"],
        )

    def fingerprint(self) -> str:
        """Semantic fingerprint: detects a changed declaration under the same version.

        Covers schema, id, version, domain, profiles, parameters, metrics,
        assertions and score contract. Cosmetic wording (`title` and every
        `description`) is excluded, so a wording edit keeps stored runs conforming.
        """
        return content_fingerprint(_without_descriptions(
            {key: value for key, value in self.to_dict().items() if key not in _COSMETIC_FIELDS}))


_COSMETIC_FIELDS = frozenset({"title", "description"})


def _without_descriptions(value: Any) -> Any:
    """Drop every nested `description` (parameters, metrics, assertions): wording, not semantics."""
    if isinstance(value, dict):
        return {key: _without_descriptions(item) for key, item in value.items() if key != "description"}
    if isinstance(value, list):
        return [_without_descriptions(item) for item in value]
    return value


_SPEC_FIELDS = frozenset({"schema", "schema_version", "diagnostic_id", "version", "title", "domain", "description",
                          "profiles", "parameters", "metrics", "assertions", "score"})
