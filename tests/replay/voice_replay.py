"""Strict, policy-free driver for deterministic voice regression fixtures.

Fixtures describe external stimuli and source provenance.  Production policy
stays in the real components wired by integration tests; this module only
decodes bounded JSON, advances a fake clock, and invokes named handlers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import inspect
import json
import math
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any


SCHEMA = "jarvis.voice_replay"
SCHEMA_VERSION = 1
MAX_FIXTURE_BYTES = 64 * 1024
MAX_STEPS = 256
# Replay targets one bounded voice session.  Seven days leaves ample room for
# field incidents while keeping datetime/timedelta arithmetic predictably safe.
MAX_TIMELINE_MS = 7 * 24 * 60 * 60 * 1000
MAX_INT64 = (1 << 63) - 1
MAX_IDENTIFIER_LENGTH = 128
MAX_SOURCE_REF_LENGTH = 160
MAX_FACT_LENGTH = 512

_SCENARIO_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ACTIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "user": frozenset({"turn"}),
        "brain": frozenset({"hold", "ready", "release"}),
        "scheduler": frozenset({"enqueue"}),
        "provider": frozenset(
            {"output_started", "transcript_final", "output_done", "cancel_rejected", "session_closed"}
        ),
        "owner": frozenset({"candidate", "rejected", "confirmed"}),
        "device": frozenset({"output_busy", "consume", "release"}),
        "control": frozenset({"stop", "checkpoint"}),
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

_ACTION_FIELDS: Mapping[str, tuple[frozenset[str], frozenset[str]]] = MappingProxyType(
    {
        "user.turn": (frozenset({"turn_id", "content_tag"}), frozenset({"addressing"})),
        "brain.hold": (frozenset({"work_id"}), frozenset()),
        "brain.ready": (frozenset({"work_id", "result_tag"}), frozenset()),
        "brain.release": (frozenset({"work_id"}), frozenset()),
        "scheduler.enqueue": (
            frozenset({"candidate_id", "kind"}),
            frozenset({"work_id", "intent_id", "intent_epoch", "ttl_ms"}),
        ),
        "provider.output_started": (frozenset({"output_id"}), frozenset()),
        "provider.transcript_final": (frozenset({"output_id", "generated_tag"}), frozenset()),
        "provider.output_done": (frozenset({"output_id", "status"}), frozenset()),
        "provider.cancel_rejected": (frozenset({"output_id", "reason_code"}), frozenset()),
        "provider.session_closed": (frozenset({"reason"}), frozenset()),
        "owner.candidate": (frozenset({"candidate_id"}), frozenset()),
        "owner.rejected": (frozenset({"candidate_id"}), frozenset({"reason_code"})),
        "owner.confirmed": (
            frozenset({"candidate_id", "played_ms"}),
            frozenset({"provider_item_id"}),
        ),
        "device.output_busy": (
            frozenset(),
            frozenset({"output_id", "playback_id", "played_ms"}),
        ),
        "device.consume": (frozenset({"output_id", "played_ms"}), frozenset()),
        "device.release": (frozenset({"output_id"}), frozenset({"provider_still_active"})),
        "control.stop": (frozenset({"reason"}), frozenset()),
        "control.checkpoint": (frozenset({"checkpoint_id"}), frozenset()),
    }
)


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


ReplayHandler = Callable[[ReplayStep], object | Awaitable[object]]


class ReplayClock:
    """Wall and monotonic fake clocks sharing one integer-millisecond cursor."""

    def __init__(self, origin: datetime, *, monotonic_start: float = 0.0):
        if origin.tzinfo is None or origin.utcoffset() is None:
            raise ReplayFixtureError("clock_origin_invalid", "origin must include a UTC offset")
        if isinstance(monotonic_start, bool) or not isinstance(monotonic_start, (int, float)):
            raise ReplayFixtureError("clock_start_invalid", "monotonic_start must be a finite number")
        if not math.isfinite(monotonic_start) or monotonic_start < 0:
            raise ReplayFixtureError("clock_start_invalid", "monotonic_start must be finite and non-negative")
        self._origin = origin
        self._monotonic_start = float(monotonic_start)
        self._elapsed_ms = 0

    @property
    def elapsed_ms(self) -> int:
        return self._elapsed_ms

    def now(self) -> datetime:
        return self._origin + timedelta(milliseconds=self._elapsed_ms)

    def monotonic(self) -> float:
        return self._monotonic_start + self._elapsed_ms / 1000

    def monotonic_ns(self) -> int:
        return round(self.monotonic() * 1_000_000_000)

    def advance_to_ms(self, at_ms: int) -> None:
        _strict_nonnegative_int(
            at_ms, "at_ms", code="clock_target_invalid", maximum=MAX_TIMELINE_MS
        )
        if at_ms < self._elapsed_ms:
            raise ReplayFixtureError("clock_went_backwards", f"{at_ms} < {self._elapsed_ms}")
        self._elapsed_ms = at_ms


class ReplayDriver:
    """Advance time and dispatch fixture actions without evaluating policy."""

    def __init__(self, clock: ReplayClock):
        self.clock = clock

    async def run(self, fixture: ReplayFixture, handlers: Mapping[str, ReplayHandler]) -> None:
        for step in fixture.steps:
            self.clock.advance_to_ms(step.at_ms)
            handler = handlers.get(step.kind)
            if handler is None:
                raise ReplayFixtureError("replay_handler_missing", step.kind)
            result = handler(step)
            if inspect.isawaitable(result):
                await result


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
    if source_kind not in {"human_trace_reconstruction", "sanitized_trace"}:
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
    if port not in _ACTIONS or action not in _ACTIONS[port]:
        raise ReplayFixtureError("fixture_action_unknown", f"{port}.{action}")
    payload = data["data"]
    if not isinstance(payload, dict):
        raise ReplayFixtureError("fixture_shape_invalid", f"steps[{index}].data must be an object")
    _validate_json_value(payload, f"steps[{index}].data", depth=0)
    _validate_action_data(f"{port}.{action}", payload, index)
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


def _identifier(value: object, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    text = _bounded_string(value, field, MAX_IDENTIFIER_LENGTH)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ReplayFixtureError("fixture_action_data_invalid", f"{field} is not a safe identifier")
    return text


def _enum(value: object, field: str, allowed: frozenset[str]) -> str:
    text = _bounded_string(value, field, MAX_IDENTIFIER_LENGTH)
    if text not in allowed:
        raise ReplayFixtureError("fixture_action_data_invalid", f"{field} has unknown value {text!r}")
    return text


def _strict_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReplayFixtureError("fixture_action_data_invalid", f"{field} must be a boolean")
    return value


def _action_int(value: object, field: str) -> int:
    maximum = MAX_INT64 if field.endswith(".intent_epoch") else MAX_TIMELINE_MS
    return _strict_nonnegative_int(
        value, field, code="fixture_action_data_invalid", maximum=maximum
    )


def _validate_action_data(kind: str, data: dict[str, Any], index: int) -> None:
    required, optional = _ACTION_FIELDS[kind]
    actual = set(data)
    missing = sorted(required - actual)
    unknown = sorted(actual - required - optional)
    if missing or unknown:
        raise ReplayFixtureError(
            "fixture_action_data_invalid",
            f"steps[{index}] {kind}: missing={missing}, unknown={unknown}",
        )
    field_prefix = f"steps[{index}].data"

    for field in ("turn_id", "work_id", "candidate_id", "intent_id", "output_id", "playback_id"):
        if field in data:
            _identifier(data[field], f"{field_prefix}.{field}")
    for field in ("content_tag", "result_tag", "generated_tag", "checkpoint_id"):
        if field in data:
            _identifier(data[field], f"{field_prefix}.{field}")
    if "provider_item_id" in data:
        _identifier(data["provider_item_id"], f"{field_prefix}.provider_item_id", nullable=True)
    for field in ("intent_epoch", "ttl_ms", "played_ms"):
        if field in data:
            _action_int(data[field], f"{field_prefix}.{field}")
    if "provider_still_active" in data:
        _strict_bool(data["provider_still_active"], f"{field_prefix}.provider_still_active")

    enum_fields: tuple[tuple[str, frozenset[str]], ...] = (
        ("addressing", frozenset({"certain", "uncertain"})),
        ("kind", frozenset({"ack", "result"})),
        ("status", frozenset({"completed", "cancelled", "failed", "interrupted"})),
        ("reason", frozenset({"manual", "remote", "error"})),
        ("reason_code", frozenset({"no_active_response", "noise", "not_owner", "uncertain"})),
    )
    for field, allowed in enum_fields:
        if field in data:
            _enum(data[field], f"{field_prefix}.{field}", allowed)

    if kind == "device.output_busy" and not ({"output_id", "playback_id"} & actual):
        raise ReplayFixtureError(
            "fixture_action_data_invalid", f"steps[{index}] {kind} needs output_id or playback_id"
        )


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
    if depth > 16:
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
