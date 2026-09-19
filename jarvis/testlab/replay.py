"""`jarvis.voice_replay` v1 fixtures: strict codec and Test Lab scenario adapter.

Binding contract: `docs/testlab.md` ("Replay fixtures"). This module is the
production home of the bounded replay DSL that `tests/replay/voice_replay.py`
introduced; that file is now a thin compatibility layer over it (production code
cannot import from `tests/`), so every existing fixture and replay test keeps its
behaviour, its stable `fixture_*` error codes and its immutability.

The action vocabulary and the per-action argument schema live in
`jarvis.testlab.primitives` (single source of truth, shared with Test Lab
scenarios). Here stay the fixture document rules: size, schema header, scenario
id, origin, provenance and the non-decreasing timeline.

`replay_fixture_to_scenario` / `scenario_to_replay_fixture` convert a fixture to a
`jarvis.testlab.scenario` document and back, 1:1: each replay step becomes one
scenario step whose `args` are the action data plus the common `at_ms`, and the
fixture provenance (including `origin`) becomes the scenario provenance.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any

from jarvis.domain.conversation_events import to_event_time
from jarvis.testlab.primitives import (
    AT_MS,
    DEFAULT_PRIMITIVES,
    MAX_IDENTIFIER_CHARS,
    MAX_INT64,
    MAX_TIMELINE_MS,
    ArgRule,
    PrimitiveArgError,
    PrimitiveRegistry,
    check_primitive_data,
    check_scenario,
)
from jarvis.testlab.scenarios import (
    MAX_FACT_CHARS,
    MAX_SOURCE_REF_CHARS,
    ProvenanceSourceKind,
    Scenario,
    ScenarioEvidence,
    ScenarioProvenance,
    ScenarioStep,
)
from jarvis.testlab.validation import LIMIT_EXCEEDED, MAX_JSON_INT, fail

SCHEMA = "jarvis.voice_replay"
SCHEMA_VERSION = 1
MAX_FIXTURE_BYTES = 64 * 1024
MAX_STEPS = 256
MAX_IDENTIFIER_LENGTH = MAX_IDENTIFIER_CHARS
MAX_SOURCE_REF_LENGTH = MAX_SOURCE_REF_CHARS
MAX_FACT_LENGTH = MAX_FACT_CHARS
MAX_DATA_DEPTH = 16
SOURCE_KINDS = frozenset(item.value for item in ProvenanceSourceKind)
_EVIDENCE_CATEGORIES = ("reported", "derived", "constructed")

_SCENARIO_ID = re.compile(r"[a-z][a-z0-9_]{0,63}")
#: Argument rule -> the historical replay error code, so fixtures fail exactly as before.
_ARG_CODES: Mapping[ArgRule, str] = MappingProxyType({
    ArgRule.FIELDS: "fixture_action_data_invalid",
    ArgRule.NOT_TEXT: "fixture_shape_invalid",
    ArgRule.TOO_LONG: "fixture_value_too_long",
    ArgRule.INVALID: "fixture_action_data_invalid",
})


class ReplayFixtureError(ValueError):
    """Fixture or replay contract failure with stable machine-readable code."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    source_ref: str
    fact: str


@dataclass(frozen=True, slots=True)
class ReplayProvenance:
    source_path: str
    source_kind: str
    reported: tuple[ReplayEvidence, ...]
    derived: tuple[ReplayEvidence, ...]
    constructed: tuple[ReplayEvidence, ...]


@dataclass(frozen=True, slots=True)
class ReplayStep:
    at_ms: int
    port: str
    action: str
    data: Mapping[str, Any]

    @property
    def kind(self) -> str:
        return f"{self.port}.{self.action}"


@dataclass(frozen=True, slots=True)
class ReplayFixture:
    scenario_id: str
    origin: datetime
    provenance: ReplayProvenance
    steps: tuple[ReplayStep, ...]
    schema: str = SCHEMA
    schema_version: int = SCHEMA_VERSION


# -------------------------------------------------------------------- decode

def load_replay_fixture(path: str | Path) -> ReplayFixture:
    fixture_path = Path(path)
    try:
        size = fixture_path.stat().st_size
    except OSError as exc:
        raise ReplayFixtureError("fixture_read_failed", type(exc).__name__) from None
    if size > MAX_FIXTURE_BYTES:
        raise ReplayFixtureError("fixture_too_large", f"{size} bytes")
    try:
        raw = fixture_path.read_bytes()
    except OSError as exc:
        raise ReplayFixtureError("fixture_read_failed", type(exc).__name__) from None
    return loads_replay_fixture(raw)


def loads_replay_fixture(raw: str | bytes) -> ReplayFixture:
    if isinstance(raw, bytes):
        if len(raw) > MAX_FIXTURE_BYTES:
            raise ReplayFixtureError("fixture_too_large", f"{len(raw)} bytes")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ReplayFixtureError("fixture_encoding_invalid", "fixture must be UTF-8") from None
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > MAX_FIXTURE_BYTES:
            raise ReplayFixtureError("fixture_too_large", "encoded fixture exceeds 64 KiB")
        text = raw
    else:
        raise ReplayFixtureError("fixture_input_invalid", "expected str or bytes")

    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
            parse_float=_finite_float,
        )
    except ReplayFixtureError:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError, ValueError) as exc:
        raise ReplayFixtureError("fixture_json_invalid", type(exc).__name__) from None
    return _decode_fixture(document)


def _decode_fixture(value: object) -> ReplayFixture:
    data = _shape(
        value,
        {"schema", "schema_version", "scenario_id", "origin", "provenance", "steps"},
        "fixture",
    )
    if data["schema"] != SCHEMA:
        raise ReplayFixtureError("fixture_schema_unsupported", repr(data["schema"]))
    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise ReplayFixtureError("fixture_version_unsupported", repr(version))

    scenario_id = _nonempty_string(data["scenario_id"], "scenario_id")
    if _SCENARIO_ID.fullmatch(scenario_id) is None:
        raise ReplayFixtureError("fixture_scenario_invalid", scenario_id)
    origin = _aware_datetime(data["origin"])
    provenance = _decode_provenance(data["provenance"])

    raw_steps = data["steps"]
    if not isinstance(raw_steps, list):
        raise ReplayFixtureError("fixture_shape_invalid", "steps must be an array")
    if not raw_steps:
        raise ReplayFixtureError("fixture_shape_invalid", "steps must not be empty")
    if len(raw_steps) > MAX_STEPS:
        raise ReplayFixtureError("fixture_steps_exceeded", str(len(raw_steps)))
    steps: list[ReplayStep] = []
    previous = -1
    for index, raw_step in enumerate(raw_steps):
        step = _decode_step(raw_step, index)
        if step.at_ms < previous:
            raise ReplayFixtureError(
                "fixture_timeline_invalid", f"steps[{index}].at_ms={step.at_ms} follows {previous}"
            )
        previous = step.at_ms
        steps.append(step)
    return ReplayFixture(scenario_id, origin, provenance, tuple(steps))


def _decode_provenance(value: object) -> ReplayProvenance:
    data = _shape(value, {"source_path", "source_kind", "reported", "derived", "constructed"}, "provenance")
    source_path = _nonempty_string(data["source_path"], "provenance.source_path")
    path = PurePosixPath(source_path)
    if path.is_absolute() or ".." in path.parts or "\\" in source_path:
        raise ReplayFixtureError("fixture_provenance_invalid", "source_path must be a repo-relative POSIX path")
    source_kind = _nonempty_string(data["source_kind"], "provenance.source_kind")
    if source_kind not in SOURCE_KINDS:
        raise ReplayFixtureError("fixture_provenance_invalid", f"unknown source_kind {source_kind!r}")
    return ReplayProvenance(
        source_path=source_path,
        source_kind=source_kind,
        reported=_decode_evidence(data["reported"], "reported"),
        derived=_decode_evidence(data["derived"], "derived"),
        constructed=_decode_evidence(data["constructed"], "constructed"),
    )


def _decode_evidence(value: object, category: str) -> tuple[ReplayEvidence, ...]:
    if not isinstance(value, list):
        raise ReplayFixtureError("fixture_provenance_invalid", f"{category} must be an array")
    evidence: list[ReplayEvidence] = []
    for index, item in enumerate(value):
        data = _shape(item, {"source_ref", "fact"}, f"provenance.{category}[{index}]")
        source_ref = _bounded_string(
            data["source_ref"], f"{category}[{index}].source_ref", MAX_SOURCE_REF_LENGTH
        )
        fact = _bounded_string(data["fact"], f"{category}[{index}].fact", MAX_FACT_LENGTH)
        evidence.append(ReplayEvidence(source_ref, fact))
    return tuple(evidence)


def _decode_step(value: object, index: int) -> ReplayStep:
    data = _shape(value, {"at_ms", "port", "action", "data"}, f"steps[{index}]")
    at_ms = _strict_nonnegative_int(
        data["at_ms"], f"steps[{index}].at_ms", maximum=MAX_TIMELINE_MS
    )
    port = _nonempty_string(data["port"], f"steps[{index}].port")
    action = _nonempty_string(data["action"], f"steps[{index}].action")
    kind = f"{port}.{action}"
    spec = DEFAULT_PRIMITIVES.replay_actions().get(kind)
    if spec is None:
        raise ReplayFixtureError("fixture_action_unknown", kind)
    payload = data["data"]
    if not isinstance(payload, dict):
        raise ReplayFixtureError("fixture_shape_invalid", f"steps[{index}].data must be an object")
    _validate_json_value(payload, f"steps[{index}].data", depth=0)
    try:
        check_primitive_data(spec, payload, f"steps[{index}].data")
    except PrimitiveArgError as exc:
        raise ReplayFixtureError(_ARG_CODES[exc.rule], exc.detail) from None
    return ReplayStep(at_ms, port, action, _freeze_json(payload))


def _shape(value: object, expected: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayFixtureError("fixture_shape_invalid", f"{where} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ReplayFixtureError("fixture_shape_invalid", f"{where}: missing={missing}, unknown={unknown}")
    return value


def _strict_nonnegative_int(
    value: object,
    field: str,
    *,
    code: str = "fixture_timeline_invalid",
    maximum: int = MAX_INT64,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReplayFixtureError(code, f"{field} must be a non-negative integer")
    if value > maximum:
        raise ReplayFixtureError(code, f"{field} exceeds {maximum}")
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ReplayFixtureError("fixture_shape_invalid", f"{field} must be a non-empty trimmed string")
    return value


def _bounded_string(value: object, field: str, maximum: int) -> str:
    text = _nonempty_string(value, field)
    if len(text) > maximum:
        raise ReplayFixtureError("fixture_value_too_long", f"{field} exceeds {maximum} characters")
    return text


def _aware_datetime(value: object) -> datetime:
    text = _nonempty_string(value, "origin")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ReplayFixtureError("fixture_origin_invalid", "origin must be ISO-8601") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayFixtureError("fixture_origin_invalid", "origin must include a UTC offset")
    return parsed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayFixtureError("fixture_duplicate_field", key)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ReplayFixtureError("fixture_nonfinite_number", value)


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ReplayFixtureError("fixture_nonfinite_number", value)
    return parsed


def _validate_json_value(value: object, where: str, *, depth: int) -> None:
    if depth > MAX_DATA_DEPTH:
        raise ReplayFixtureError("fixture_data_too_deep", where)
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReplayFixtureError("fixture_nonfinite_number", where)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{where}[{index}]", depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ReplayFixtureError("fixture_shape_invalid", f"{where} keys must be non-empty strings")
            _validate_json_value(item, f"{where}.{key}", depth=depth + 1)
        return
    raise ReplayFixtureError("fixture_shape_invalid", f"{where} contains non-JSON data")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


# ------------------------------------------------------------------ adapter

def replay_fixture_to_scenario(fixture: ReplayFixture, *, primitives: PrimitiveRegistry = DEFAULT_PRIMITIVES,
                               title: str | None = None, description: str | None = None) -> Scenario:
    """A decoded replay fixture as a `jarvis.testlab.scenario`, provenance and timeline preserved.

    One scenario step per replay step, `args = {at_ms, **data}`. The fixture `origin`
    becomes `provenance.origin` (UTC, ms). The Test Lab bounds are slightly tighter than
    the replay ones in two documented places: an integer above 2^53 (a huge `intent_epoch`)
    and an origin with sub-millisecond precision are refused here, with a `TestLabError`.
    """
    if not isinstance(fixture, ReplayFixture):
        raise fail("replay_fixture_to_scenario takes a ReplayFixture")
    if fixture.origin.microsecond % 1000:
        raise fail("fixture origin must have millisecond precision to become a scenario provenance")
    for step in fixture.steps:
        for name, value in step.data.items():
            if type(value) is int and abs(value) > MAX_JSON_INT:
                raise fail(f"{step.kind}.{name} exceeds the Test Lab integer bound {MAX_JSON_INT}", LIMIT_EXCEEDED)
    reported, derived, constructed = (
        tuple(ScenarioEvidence(item.source_ref, item.fact) for item in getattr(fixture.provenance, category))
        for category in _EVIDENCE_CATEGORIES)
    provenance = ScenarioProvenance(fixture.provenance.source_path,
                                    ProvenanceSourceKind(fixture.provenance.source_kind),
                                    to_event_time(fixture.origin), reported, derived, constructed)
    steps = tuple(ScenarioStep(step.kind, {AT_MS: step.at_ms, **dict(step.data)}) for step in fixture.steps)
    scenario = Scenario(fixture.scenario_id, steps, title, description, provenance=provenance)
    check_scenario(scenario, primitives=primitives)
    return scenario


def scenario_to_replay_fixture(scenario: Scenario) -> ReplayFixture:
    """Inverse of `replay_fixture_to_scenario`: refuses a scenario with no provenance or a
    primitive outside the `jarvis.voice_replay` v1 vocabulary."""
    if not isinstance(scenario, Scenario):
        raise fail("scenario_to_replay_fixture takes a Scenario")
    if scenario.provenance is None:
        raise fail("a replay fixture needs the scenario provenance (source, origin, evidence)")
    actions = DEFAULT_PRIMITIVES.replay_actions()
    steps: list[ReplayStep] = []
    for index, step in enumerate(scenario.steps):
        if step.primitive not in actions:
            raise fail(f"steps[{index}].primitive {step.primitive} is not a jarvis.voice_replay action")
        port, action = step.primitive.split(".", 1)
        data = {key: value for key, value in step.args.items() if key != AT_MS}
        steps.append(ReplayStep(step.args[AT_MS], port, action, _freeze_json(data)))
    provenance = scenario.provenance
    reported, derived, constructed = (
        tuple(ReplayEvidence(item.source_ref, item.fact) for item in getattr(provenance, category))
        for category in _EVIDENCE_CATEGORIES)
    return ReplayFixture(scenario.scenario_id, provenance.origin,
                         ReplayProvenance(provenance.source_path, provenance.source_kind.value,
                                          reported, derived, constructed),
                         tuple(steps))


def load_replay_scenario(path: str | Path, **options: Any) -> Scenario:
    """Read a `jarvis.voice_replay` fixture file and return it as a Test Lab scenario."""
    return replay_fixture_to_scenario(load_replay_fixture(path), **options)
