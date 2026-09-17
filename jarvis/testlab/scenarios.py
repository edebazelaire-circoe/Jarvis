"""Safe declarative Test Lab scenario: ordered steps of registered primitives with JSON data.

Binding contract: `docs/testlab.md` ("Scenarios"). A scenario never carries
code: every step names a registered primitive (vocabulary owned by Slice 04)
and passes bounded JSON data. Code-carrying keys, code-looking strings,
private fields and non-JSON values are rejected at any depth, with the path,
never the value. Nothing here evaluates anything.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from jarvis.testlab.identity import SCENARIO_SCHEMA, TESTLAB_SCHEMA_VERSION
from jarvis.testlab.validation import (
    LIMIT_EXCEEDED,
    MAX_VALUE_DEPTH,
    REFERENCE_INVALID,
    SIMPLE_NAME,
    canonical_json,
    check_document_header,
    check_name,
    check_open_key,
    check_text,
    content_fingerprint,
    exact_fields,
    fail,
    freeze_json,
    name_for_message,
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
        data = exact_fields(payload, _STEP_FIELDS, where)
        return cls(data["primitive"], data["args"])


_STEP_FIELDS = frozenset({"primitive", "args"})


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    steps: tuple[ScenarioStep, ...]
    title: str | None = None
    description: str | None = None
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        check_name(self.scenario_id, "scenario_id")
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
        scenario = cls(data["scenario_id"], steps, data["title"], data["description"])
        if primitives is not SHAPE_ONLY:
            check_scenario_primitives(scenario, primitives)
        return scenario

    def fingerprint(self) -> str:
        """Content fingerprint: two runs executed the same scenario exactly when fingerprints match."""
        return content_fingerprint(self.to_dict())


_SCENARIO_FIELDS = frozenset({"schema", "schema_version", "scenario_id", "title", "description", "steps"})


def check_scenario_primitives(scenario: Scenario, registered: Collection[str]) -> None:
    """Every step names a registered primitive (the registry itself belongs to the catalog, Slice 04)."""
    if not isinstance(scenario, Scenario):
        raise fail("check_scenario_primitives takes a Scenario")
    for index, step in enumerate(scenario.steps):
        if step.primitive not in registered:
            raise fail(f"steps[{index}].primitive is not a registered primitive", REFERENCE_INVALID)
