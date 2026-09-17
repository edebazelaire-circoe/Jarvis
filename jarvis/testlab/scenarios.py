"""Safe declarative Test Lab scenario: ordered steps of registered primitives with JSON data.

Binding contract: `docs/testlab.md` ("Scenarios"). A scenario never carries
code: every step names a registered primitive (vocabulary owned by Slice 04)
and passes bounded JSON data. Code-carrying keys, code-looking strings,
private fields and non-JSON values are rejected at any depth, with the path,
never the value. Nothing here evaluates anything.

Slice 04 adds the optional `provenance` of an incident-derived scenario (the
`jarvis.voice_replay` provenance, productized) and the primitive vocabulary in
`jarvis.testlab.primitives`, which checks step arguments, timeline and profiles.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.testlab.identity import SCENARIO_SCHEMA, TESTLAB_SCHEMA_VERSION
from jarvis.testlab.validation import (
    LIMIT_EXCEEDED,
    MAX_VALUE_DEPTH,
    REFERENCE_INVALID,
    SIMPLE_NAME,
    TestLabError,
    canonical_json,
    check_document_header,
    check_enum,
    check_name,
    check_open_key,
    check_text,
    check_time,
    content_fingerprint,
    decode_enum,
    exact_fields,
    fail,
    format_time,
    freeze_json,
    name_for_message,
    parse_time,
    scan_code,
    scan_private,
    thaw_json,
)

MAX_STEPS = 256
MAX_STEP_ARGS_BYTES = 4 * 1024
#: Same bound as `jarvis.voice_replay` fixtures.
MAX_SCENARIO_BYTES = 64 * 1024
MAX_SCENARIO_TITLE_CHARS = 120
MAX_SCENARIO_DESCRIPTION_CHARS = 512
#: Provenance bounds are the `jarvis.voice_replay` evidence bounds, so every replay fixture converts.
MAX_SOURCE_PATH_CHARS = 256
MAX_SOURCE_REF_CHARS = 160
MAX_FACT_CHARS = 512
MAX_EVIDENCE_ITEMS = 32


class _ShapeOnly:
    """Sentinel type of `SHAPE_ONLY`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "SHAPE_ONLY"


#: Explicit opt-out for `Scenario.from_dict(..., primitives=SHAPE_ONLY)`: check shape and
#: safety but not primitive registration (fixture tooling, catalog linting). A scenario
#: that will execute is always decoded against the catalog's registered primitive names.
SHAPE_ONLY = _ShapeOnly()


def _check_arg_keys(value: object, path: str, depth: int = 0) -> None:
    """Every object key at every depth is a snake_case name, never private, never code."""
    if depth > MAX_VALUE_DEPTH:
        raise fail(f"{path}: nesting exceeds {MAX_VALUE_DEPTH} levels", LIMIT_EXCEEDED)
    if isinstance(value, Mapping):
        for key, item in value.items():
            check_open_key(key, path, max_chars=64)
            check_name(key, f"{path}.{name_for_message(key)}", pattern=SIMPLE_NAME)
            _check_arg_keys(item, f"{path}.{key}", depth + 1)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_arg_keys(item, f"{path}[{index}]", depth + 1)


# --------------------------------------------------------------- provenance

class ProvenanceSourceKind(StrEnum):
    """Closed vocabulary, identical to `jarvis.voice_replay` v1 `source_kind`."""

    HUMAN_TRACE_RECONSTRUCTION = "human_trace_reconstruction"
    SANITIZED_TRACE = "sanitized_trace"


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    """One sourced statement: `source_ref` points into the source, `fact` states what it shows."""

    source_ref: str
    fact: str

    def __post_init__(self) -> None:
        check_text(self.source_ref, "evidence.source_ref", max_chars=MAX_SOURCE_REF_CHARS)
        check_text(self.fact, "evidence.fact", max_chars=MAX_FACT_CHARS)
        scan_code(self.source_ref, "evidence.source_ref")
        scan_code(self.fact, "evidence.fact")

    def to_dict(self) -> dict[str, Any]:
        return {"source_ref": self.source_ref, "fact": self.fact}

    @classmethod
    def from_dict(cls, payload: object, where: str = "evidence") -> ScenarioEvidence:
        data = exact_fields(payload, _EVIDENCE_FIELDS, where)
        return cls(data["source_ref"], data["fact"])


_EVIDENCE_FIELDS = frozenset({"source_ref", "fact"})
_EVIDENCE_CATEGORIES = ("reported", "derived", "constructed")


def _check_source_path(value: object) -> None:
    """Repo-relative POSIX path: no leading `/`, drive colon, backslash, empty, `.` or `..` segment."""
    check_text(value, "provenance.source_path", max_chars=MAX_SOURCE_PATH_CHARS)
    text = str(value)
    if (text.startswith("/") or "\\" in text or ":" in text
            or any(segment in ("", ".", "..") for segment in text.split("/"))):
        raise fail("provenance.source_path must be a repo-relative POSIX path")


def _check_evidence(values: object, name: str) -> None:
    if not isinstance(values, tuple) or any(not isinstance(item, ScenarioEvidence) for item in values):
        raise fail(f"provenance.{name} must be a tuple of ScenarioEvidence")
    if len(values) > MAX_EVIDENCE_ITEMS:
        raise fail(f"provenance.{name} exceeds {MAX_EVIDENCE_ITEMS} entries", LIMIT_EXCEEDED)


@dataclass(frozen=True, slots=True)
class ScenarioProvenance:
    """Where an incident-derived scenario comes from (the `jarvis.voice_replay` provenance).

    `origin` is the wall-clock instant of the source timeline's `at_ms` 0 (UTC, ms).
    `reported` facts come from the source, `derived` ones are inferred from it,
    `constructed` ones are synthetic choices of the scenario author.
    """

    source_path: str
    source_kind: ProvenanceSourceKind
    origin: datetime
    reported: tuple[ScenarioEvidence, ...] = ()
    derived: tuple[ScenarioEvidence, ...] = ()
    constructed: tuple[ScenarioEvidence, ...] = ()

    def __post_init__(self) -> None:
        _check_source_path(self.source_path)
        check_enum(ProvenanceSourceKind, self.source_kind, "provenance.source_kind")
        check_time(self.origin, "provenance.origin")
        for name in _EVIDENCE_CATEGORIES:
            _check_evidence(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {"source_path": self.source_path, "source_kind": self.source_kind.value,
                                    "origin": format_time(self.origin)}
        for name in _EVIDENCE_CATEGORIES:
            document[name] = [item.to_dict() for item in getattr(self, name)]
        return document

    @classmethod
    def from_dict(cls, payload: object) -> ScenarioProvenance:
        data = exact_fields(payload, _PROVENANCE_FIELDS, "provenance")
        evidence: dict[str, tuple[ScenarioEvidence, ...]] = {}
        for name in _EVIDENCE_CATEGORIES:
            items = data[name]
            if not isinstance(items, list):
                raise fail(f"provenance.{name} must be a list")
            evidence[name] = tuple(ScenarioEvidence.from_dict(item, f"provenance.{name}[{index}]")
                                   for index, item in enumerate(items))
        return cls(data["source_path"],
                   decode_enum(ProvenanceSourceKind, data["source_kind"], "provenance.source_kind"),
                   parse_time(data["origin"], "provenance.origin"),
                   evidence["reported"], evidence["derived"], evidence["constructed"])


_PROVENANCE_FIELDS = frozenset({"source_path", "source_kind", "origin", *_EVIDENCE_CATEGORIES})


# --------------------------------------------------------------------- steps

@dataclass(frozen=True, slots=True)
class ScenarioStep:
    #: Registered primitive name (dotted lowercase, e.g. `user.turn`), resolved by the catalog.
    primitive: str
    #: Read-only JSON object (objects -> MappingProxyType, lists -> tuple).
    args: Mapping[str, Any]

    def __hash__(self) -> int:
        return hash((self.primitive, canonical_json(self.args)))

    def __post_init__(self) -> None:
        check_name(self.primitive, "step.primitive")
        if not isinstance(self.args, Mapping):
            raise fail("step.args must be an object")
        scan_private(self.args, "step.args")
        scan_code(self.args, "step.args")
        _check_arg_keys(self.args, "step.args")
        frozen = freeze_json(self.args, "step.args")
        if len(canonical_json(frozen).encode("utf-8")) > MAX_STEP_ARGS_BYTES:
            raise fail(f"step.args exceeds {MAX_STEP_ARGS_BYTES} encoded bytes", LIMIT_EXCEEDED)
        object.__setattr__(self, "args", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {"primitive": self.primitive, "args": thaw_json(self.args)}

    @classmethod
    def from_dict(cls, payload: object, where: str = "step") -> ScenarioStep:
        """Decode one step. Inside a scenario, `where` is `steps[<index>]`, so a rejected argument
        is named with the same indexed path the primitive checks use (`steps[0].args.text`)."""
        data = exact_fields(payload, _STEP_FIELDS, where)
        try:
            return cls(data["primitive"], data["args"])
        except TestLabError as exc:
            raise _at_step(exc, where) from None


def _at_step(error: TestLabError, where: str) -> TestLabError:
    """Re-label a standalone `step.…` path as the step's indexed path. Values are never touched."""
    if where == "step" or not error.detail.startswith("step."):
        return error
    return type(error)(error.code, f"{where}.{error.detail[len('step.'):]}")


_STEP_FIELDS = frozenset({"primitive", "args"})


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    steps: tuple[ScenarioStep, ...]
    title: str | None = None
    description: str | None = None
    schema_version: int = TESTLAB_SCHEMA_VERSION
    #: Source of an incident-derived scenario (Slice 04); None for a scenario authored from scratch.
    provenance: ScenarioProvenance | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        check_name(self.scenario_id, "scenario_id")
        if self.provenance is not None and not isinstance(self.provenance, ScenarioProvenance):
            raise fail("provenance must be a ScenarioProvenance or None")
        check_text(self.title, "title", max_chars=MAX_SCENARIO_TITLE_CHARS, optional=True)
        check_text(self.description, "description", max_chars=MAX_SCENARIO_DESCRIPTION_CHARS, optional=True)
        for value, name in ((self.title, "title"), (self.description, "description")):
            scan_code(value, name)
        if not isinstance(self.steps, tuple) or any(not isinstance(step, ScenarioStep) for step in self.steps):
            raise fail("steps must be a tuple of ScenarioStep")
        if not 1 <= len(self.steps) <= MAX_STEPS:
            raise fail(f"steps must contain 1 to {MAX_STEPS} entries", LIMIT_EXCEEDED)
        if len(canonical_json(self.to_dict()).encode("utf-8")) > MAX_SCENARIO_BYTES:
            raise fail(f"scenario exceeds {MAX_SCENARIO_BYTES} encoded bytes", LIMIT_EXCEEDED)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCENARIO_SCHEMA, "schema_version": self.schema_version, "scenario_id": self.scenario_id,
                "title": self.title, "description": self.description,
                "provenance": None if self.provenance is None else self.provenance.to_dict(),
                "steps": [step.to_dict() for step in self.steps]}

    @classmethod
    def from_dict(cls, payload: object, *, primitives: Collection[str] | _ShapeOnly) -> Scenario:
        """Strict decode. Private data first, then code, then shape, then primitive registration.

        `primitives` is required: the registered primitive names, or `SHAPE_ONLY`
        to deliberately skip the registration check.
        """
        if primitives is not SHAPE_ONLY and (isinstance(primitives, (str, bytes))
                                             or not isinstance(primitives, Collection)):
            raise fail("primitives must be a collection of registered primitive names or SHAPE_ONLY")
        scan_private(payload, "scenario")
        scan_code(payload, "scenario")
        data = exact_fields(payload, _SCENARIO_FIELDS, "scenario")
        check_document_header(data, SCENARIO_SCHEMA, TESTLAB_SCHEMA_VERSION, "scenario")
        if not isinstance(data["steps"], list):
            raise fail("steps must be a list")
        steps = tuple(ScenarioStep.from_dict(item, f"steps[{index}]") for index, item in enumerate(data["steps"]))
        provenance = None if data["provenance"] is None else ScenarioProvenance.from_dict(data["provenance"])
        scenario = cls(data["scenario_id"], steps, data["title"], data["description"], provenance=provenance)
        if primitives is not SHAPE_ONLY:
            check_scenario_primitives(scenario, primitives)
        return scenario

    def fingerprint(self) -> str:
        """Content fingerprint: two runs executed the same scenario exactly when fingerprints match."""
        return content_fingerprint(self.to_dict())


_SCENARIO_FIELDS = frozenset({"schema", "schema_version", "scenario_id", "title", "description", "provenance",
                              "steps"})


def check_scenario_primitives(scenario: Scenario, registered: Collection[str]) -> None:
    """Every step names a registered primitive (the registry itself belongs to the catalog, Slice 04)."""
    if not isinstance(scenario, Scenario):
        raise fail("check_scenario_primitives takes a Scenario")
    for index, step in enumerate(scenario.steps):
        if step.primitive not in registered:
            raise fail(f"steps[{index}].primitive is not a registered primitive", REFERENCE_INVALID)
