"""Test Lab scenario primitives: the closed, registered vocabulary of scenario steps.

Binding contract: `docs/testlab.md` ("Scenario primitives"). Pure: no I/O, no clock.

The vocabulary productizes the `jarvis.voice_replay` v1 action DSL
(`jarvis.testlab.replay`): every replay action (`user.turn`, `brain.ready`,
`provider.output_started`, ...) is a primitive with the SAME argument schema, and
the replay codec validates its action data through this module. The Test Lab adds
the common `at_ms` argument (virtual time of the step) and primitives the replay DSL
lacks: user speech by bounded text, interruption, virtual wait, audio injection by
fixture reference, run-local parameter override and expectations.

A primitive is data: a name, typed arguments and the profiles that can perform it.
Nothing here executes a step. `PrimitiveHandler` is the executor-facing seam that a
profile runner (Slice 06 onwards) implements; there is no code, import path or
command anywhere in a primitive, a step or its arguments (structural guarantee), and
the Slice 01 name/value guards run on every scenario payload on top of it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any, Protocol

from jarvis.domain.conversation_events import ConversationEventType
from jarvis.testlab.diagnostics import (
    AssertionOutcome,
    AssertionSpec,
    Comparator,
    DiagnosticSpec,
    MetricSpec,
    ParameterSpec,
    Scalar,
    check_assertion_threshold,
    check_parameter_value,
)
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.redaction import redact_identifying_text
from jarvis.testlab.runs import check_artifact_path
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.validation import (
    FORBIDDEN_PRIVATE_DATA,
    PARAMETER_INVALID,
    REFERENCE_INVALID,
    ForbiddenCodeError,
    TestLabError,
    TestLabRedactionError,
    check_name,
    check_number,
    check_open_key,
    check_scalar_value,
    check_text,
    fail,
    is_private_key,
    name_for_message,
)

#: Virtual timeline bound of one scenario: the `jarvis.voice_replay` bound (7 days).
MAX_TIMELINE_MS = 7 * 24 * 60 * 60 * 1000
MAX_INT64 = (1 << 63) - 1
MAX_IDENTIFIER_CHARS = 128
#: Authored user utterances are short test inputs, never pasted conversations.
MAX_SPEECH_TEXT_CHARS = 280
MAX_EXPECTED_EVENT_COUNT = 10_000
MIN_GAIN_DB = -60
MAX_GAIN_DB = 20
#: Common argument of every Test Lab step (not part of replay action data).
AT_MS = "at_ms"

#: Replay identifier: opaque, safe, bounded (same pattern as `jarvis.voice_replay` v1).
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
AUDIO_EXTENSIONS = (".wav",)

# Stable error codes (docs/testlab.md, "Errors").
PRIMITIVE_UNKNOWN = "testlab_primitive_unknown"
PRIMITIVE_ARGS_INVALID = "testlab_primitive_args_invalid"
PRIMITIVE_PROFILE_UNSUPPORTED = "testlab_primitive_profile_unsupported"
SCENARIO_TIMELINE_INVALID = "testlab_scenario_timeline_invalid"
ALL_PROFILES = frozenset(ProfileName)


class PrimitiveError(TestLabError):
    """A scenario step does not fit the registered vocabulary (name, arguments, timeline or profile)."""


class ArgRule(StrEnum):
    """Why an argument failed. The replay codec maps it back to its historical `fixture_*` codes."""

    #: Missing or unknown argument, or a cross-argument requirement (`output_id` or `playback_id`).
    FIELDS = "fields"
    #: A text-typed argument is not a nonempty trimmed string.
    NOT_TEXT = "not_text"
    TOO_LONG = "too_long"
    #: Wrong type, out of range, not in the vocabulary, unsafe identifier.
    INVALID = "invalid"


class PrimitiveArgError(PrimitiveError):
    """`testlab_primitive_args_invalid`, with the failed `rule` and the argument name (never its value)."""

    def __init__(self, rule: ArgRule, detail: str, argument: str | None = None) -> None:
        super().__init__(PRIMITIVE_ARGS_INVALID, detail)
        self.rule = rule
        self.argument = argument


# ---------------------------------------------------------------- arguments

class ArgKind(StrEnum):
    IDENTIFIER = "identifier"
    TIME_MS = "time_ms"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    SPEECH_TEXT = "speech_text"
    METRIC_NAME = "metric_name"
    ASSERTION_ID = "assertion_id"
    PARAMETER_NAME = "parameter_name"
    SCALAR = "scalar"
    THRESHOLD = "threshold"
    EVENT_TYPE = "event_type"
    AUDIO_REF = "audio_ref"
    DECIBEL = "decibel"


@dataclass(frozen=True, slots=True)
class ArgSpec:
    """Type of one argument name. A name has one type across every primitive (as in the replay DSL)."""

    name: str
    kind: ArgKind
    nullable: bool = False
    choices: tuple[str, ...] = ()
    maximum: int | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind.value, "nullable": self.nullable, "choices": list(self.choices),
                "maximum": self.maximum, "description": self.description}


def _arg(name: str, kind: ArgKind, description: str, **options: Any) -> ArgSpec:
    return ArgSpec(name, kind, description=description, **options)


_I, _T = ArgKind.IDENTIFIER, ArgKind.TIME_MS
#: Every argument name, in VALIDATION ORDER. The first 20 rows are the `jarvis.voice_replay`
#: v1 fields in the order that codec always checked them, so a fixture with several faults
#: still reports the same first fault.
ARG_SPECS: Mapping[str, ArgSpec] = MappingProxyType({spec.name: spec for spec in (
    _arg("turn_id", _I, "User turn identity (opaque)."),
    _arg("work_id", _I, "Brain work identity (opaque)."),
    _arg("candidate_id", _I, "Speech or barge-in candidate identity (opaque)."),
    _arg("intent_id", _I, "Conversation intent identity (opaque)."),
    _arg("output_id", _I, "Provider/local output identity (opaque)."),
    _arg("playback_id", _I, "Local playback identity (opaque)."),
    _arg("content_tag", _I, "Opaque tag standing for the user's words (no text)."),
    _arg("result_tag", _I, "Opaque tag standing for a brain result (no text)."),
    _arg("generated_tag", _I, "Opaque tag standing for provider-generated words (no text)."),
    _arg("checkpoint_id", _I, "Named point where the executor settles and checks state."),
    _arg("provider_item_id", _I, "Provider conversation item identity, null when the provider gave none.",
         nullable=True),
    _arg("intent_epoch", ArgKind.INTEGER, "Monotonic intent revision.", maximum=MAX_INT64),
    _arg("ttl_ms", _T, "Candidate time to live.", maximum=MAX_TIMELINE_MS),
    _arg("played_ms", _T, "Audio already played.", maximum=MAX_TIMELINE_MS),
    _arg("provider_still_active", ArgKind.BOOLEAN, "The provider still holds an active response."),
    _arg("addressing", ArgKind.CHOICE, "Whether the user addressed Jarvis.", choices=("certain", "uncertain")),
    _arg("kind", ArgKind.CHOICE, "Speech candidate kind.", choices=("ack", "result")),
    _arg("status", ArgKind.CHOICE, "Provider output terminal status.",
         choices=("completed", "cancelled", "failed", "interrupted")),
    _arg("reason", ArgKind.CHOICE, "Why the session stops or closes.", choices=("manual", "remote", "error")),
    _arg("reason_code", ArgKind.CHOICE, "Rejection or cancel refusal code.",
         choices=("no_active_response", "noise", "not_owner", "uncertain")),
    # Test Lab additions.
    _arg("text", ArgKind.SPEECH_TEXT, "Authored synthetic utterance, single line, bounded, no identifying data."),
    _arg("audio_ref", ArgKind.AUDIO_REF, "Audio fixture file, relative to the Test Lab audio fixture root."),
    _arg("gain_db", ArgKind.DECIBEL, "Playback gain applied to the fixture."),
    _arg("parameter", ArgKind.PARAMETER_NAME, "Declared diagnostic parameter or allowlisted setting."),
    _arg("value", ArgKind.SCALAR, "Run-local value (checked against the declaration)."),
    _arg("event", ArgKind.EVENT_TYPE, "Conversation Events type the run must record."),
    _arg("count_min", ArgKind.INTEGER, "Fewest expected occurrences (default 1).", maximum=MAX_EXPECTED_EVENT_COUNT),
    _arg("count_max", ArgKind.INTEGER, "Most expected occurrences.", maximum=MAX_EXPECTED_EVENT_COUNT),
    _arg("metric", ArgKind.METRIC_NAME, "Declared diagnostic metric."),
    _arg("comparator", ArgKind.CHOICE, "Comparison of the metric with the threshold.",
         choices=tuple(item.value for item in Comparator)),
    _arg("threshold", ArgKind.THRESHOLD, "Threshold fitting the metric unit."),
    _arg("assertion_id", ArgKind.ASSERTION_ID, "Declared diagnostic assertion."),
    _arg("outcome", ArgKind.CHOICE, "Expected assertion outcome.",
         choices=tuple(item.value for item in AssertionOutcome)),
)})
_ORDER = {name: index for index, name in enumerate(ARG_SPECS)}


def _text(value: object, name: str, max_chars: int) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise PrimitiveArgError(ArgRule.NOT_TEXT, f"{name} must be a non-empty trimmed string", name)
    if len(value) > max_chars:
        raise PrimitiveArgError(ArgRule.TOO_LONG, f"{name} exceeds {max_chars} characters", name)
    return value


def _invalid(name: str, rule: str) -> PrimitiveArgError:
    return PrimitiveArgError(ArgRule.INVALID, f"{name} {rule}", name)


def _as_arg_error(exc: TestLabError, name: str) -> PrimitiveArgError:
    return PrimitiveArgError(ArgRule.INVALID, exc.detail, name)


def check_arg_value(spec: ArgSpec, value: object, path: str) -> None:
    """Validate one argument value against its type. Errors name the path, never the value."""
    if spec.nullable and value is None:
        return
    kind = spec.kind
    if kind is ArgKind.IDENTIFIER:
        if IDENTIFIER.fullmatch(_text(value, path, MAX_IDENTIFIER_CHARS)) is None:
            raise _invalid(path, "is not a safe identifier")
    elif kind in (ArgKind.TIME_MS, ArgKind.INTEGER):
        maximum = spec.maximum if spec.maximum is not None else MAX_TIMELINE_MS
        if type(value) is not int or not 0 <= value <= maximum:
            raise _invalid(path, f"must be an integer from 0 to {maximum}")
    elif kind is ArgKind.BOOLEAN:
        if type(value) is not bool:
            raise _invalid(path, "must be a boolean")
    elif kind is ArgKind.CHOICE:
        if _text(value, path, MAX_IDENTIFIER_CHARS) not in spec.choices:
            raise _invalid(path, "is not in the vocabulary")
    elif kind is ArgKind.SPEECH_TEXT:
        _check_speech_text(value, path)
    elif kind in (ArgKind.METRIC_NAME, ArgKind.ASSERTION_ID, ArgKind.PARAMETER_NAME):
        _check_declared_name(kind, value, path)
    elif kind is ArgKind.SCALAR:
        try:
            check_scalar_value(value, path)
        except (TestLabRedactionError, ForbiddenCodeError):
            raise
        except TestLabError as exc:
            raise _as_arg_error(exc, path) from None
    elif kind is ArgKind.THRESHOLD:
        if type(value) is not bool:
            try:
                check_number(value, path)
            except TestLabError as exc:
                raise _as_arg_error(exc, path) from None
    elif kind is ArgKind.EVENT_TYPE:
        if _text(value, path, MAX_IDENTIFIER_CHARS) not in _EVENT_TYPES:
            raise _invalid(path, "is not a Conversation Events type")
    elif kind is ArgKind.AUDIO_REF:
        try:
            check_artifact_path(value, path)
        except TestLabError as exc:
            raise _as_arg_error(exc, path) from None
        if not str(value).lower().endswith(AUDIO_EXTENSIONS):
            raise _invalid(path, f"must name a {'/'.join(AUDIO_EXTENSIONS)} fixture")
    elif kind is ArgKind.DECIBEL:
        try:
            check_number(value, path, minimum=MIN_GAIN_DB, maximum=MAX_GAIN_DB)
        except TestLabError as exc:
            raise _as_arg_error(exc, path) from None
    else:  # pragma: no cover - ArgKind is closed; a new kind must get a branch
        raise _invalid(path, "has an unsupported argument kind")


_EVENT_TYPES = frozenset(item.value for item in ConversationEventType)


def _check_speech_text(value: object, path: str) -> None:
    """Privacy stance: scenario text is an authored test input, never user data. It stays short,
    single-line and printable, and anything the identifying-text redaction would change (an email
    address, URL credentials, an SSH remote user) is refused rather than silently rewritten."""
    _text(value, path, MAX_SPEECH_TEXT_CHARS)
    try:
        check_text(value, path, max_chars=MAX_SPEECH_TEXT_CHARS)
    except TestLabError as exc:
        raise _as_arg_error(exc, path) from None
    if redact_identifying_text(str(value))[1]:
        raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA,
                                    f"{path}: identifying data (email, URL credentials) is forbidden in scenario text")


def _check_declared_name(kind: ArgKind, value: object, path: str) -> None:
    """Names of declared parameters, metrics and assertions: the Slice 01 name rules apply to them."""
    text = _text(value, path, 96)
    if kind is ArgKind.PARAMETER_NAME:
        check_open_key(text, path)  # private and code names raise their own error family
        return
    if kind is ArgKind.METRIC_NAME and is_private_key(text):
        raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA, f"{path}: forbidden name (private data)")
    try:
        check_name(text, path)
    except TestLabError as exc:
        raise _as_arg_error(exc, path) from None


# --------------------------------------------------------------- primitives

class PrimitiveFamily(StrEnum):
    # `jarvis.voice_replay` v1 ports.
    USER = "user"
    BRAIN = "brain"
    SCHEDULER = "scheduler"
    PROVIDER = "provider"
    OWNER = "owner"
    DEVICE = "device"
    CONTROL = "control"
    # Test Lab additions.
    TIME = "time"
    AUDIO = "audio"
    PARAMETER = "parameter"
    EXPECT = "expect"


@dataclass(frozen=True, slots=True)
class PrimitiveSpec:
    """One registered primitive: `<family>.<action>`, typed arguments, supporting profiles.

    `required`/`optional` exclude the common `at_ms`. `replay` marks the primitives of the
    `jarvis.voice_replay` v1 DSL (their argument schema is that DSL's, unchanged).
    """

    name: str
    family: PrimitiveFamily
    required: tuple[str, ...]
    optional: tuple[str, ...]
    profiles: frozenset[ProfileName]
    description: str
    replay: bool = False
    #: Each group needs at least one of its arguments.
    requires_any: tuple[tuple[str, ...], ...] = ()
    #: `(low, high)` pairs that must satisfy low <= high when both are present.
    ordered: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        check_name(self.name, "primitive.name")
        if self.name.split(".")[0] != self.family.value or self.name.count(".") != 1:
            raise fail(f"primitive {self.name} must be named <family>.<action>")
        names = (*self.required, *self.optional)
        if len(set(names)) != len(names) or AT_MS in names or any(name not in ARG_SPECS for name in names):
            raise fail(f"primitive {self.name} declares unknown, repeated or reserved arguments")
        grouped = {name for group in self.requires_any for name in group} | {
            name for pair in self.ordered for name in pair}
        if not grouped <= set(self.optional):
            raise fail(f"primitive {self.name}: argument rules may only name optional arguments")
        if not isinstance(self.profiles, frozenset) or not self.profiles or not self.profiles <= ALL_PROFILES:
            raise fail(f"primitive {self.name} must support at least one profile")
        check_text(self.description, f"primitive {self.name}.description", max_chars=240)

    @property
    def action(self) -> str:
        return self.name.split(".", 1)[1]

    def supports(self, profile: ProfileName) -> bool:
        return profile in self.profiles

    def to_dict(self) -> dict[str, Any]:
        """Introspection form (catalog, CLI, Control Center): argument types included."""
        return {"name": self.name, "family": self.family.value, "description": self.description,
                "replay": self.replay, "profiles": [item.value for item in ProfileName if item in self.profiles],
                "arguments": {"common": [AT_MS], "required": list(self.required), "optional": list(self.optional),
                              "requires_any": [list(group) for group in self.requires_any],
                              "ordered": [list(pair) for pair in self.ordered]},
                "types": {name: ARG_SPECS[name].to_dict() for name in (*self.required, *self.optional)}}


def check_primitive_data(spec: PrimitiveSpec, data: Mapping[str, Any], where: str) -> None:
    """Validate step data WITHOUT `at_ms` (the replay action data): fields, then types in `ARG_SPECS` order."""
    if not isinstance(data, Mapping):
        raise PrimitiveArgError(ArgRule.FIELDS, f"{where} must be an object")
    actual = set(data)
    missing = sorted(set(spec.required) - actual)
    unknown = sorted(name_for_message(name) for name in actual - set(spec.required) - set(spec.optional))
    if missing or unknown:
        raise PrimitiveArgError(ArgRule.FIELDS, f"{where} {spec.name}: missing={missing}, unknown={unknown}")
    for name in sorted(actual, key=_ORDER.__getitem__):
        check_arg_value(ARG_SPECS[name], data[name], f"{where}.{name}")
    for group in spec.requires_any:
        if not actual & set(group):
            raise PrimitiveArgError(ArgRule.FIELDS, f"{where} {spec.name} needs {' or '.join(group)}")
    for low, high in spec.ordered:
        if low in actual and high in actual and data[low] > data[high]:
            raise PrimitiveArgError(ArgRule.INVALID, f"{where}: {low} must be <= {high}", low)


def _primitive(name: str, required: tuple[str, ...], optional: tuple[str, ...], profiles: Iterable[ProfileName],
               description: str, **options: Any) -> PrimitiveSpec:
    return PrimitiveSpec(name, PrimitiveFamily(name.split(".")[0]), required, optional, frozenset(profiles),
                         description, **options)


_VIRTUAL = (ProfileName.VIRTUAL,)
_SPOKEN = (ProfileName.VIRTUAL, ProfileName.LIVE, ProfileName.HARDWARE_GUIDED)
_ACOUSTIC = (ProfileName.AUDIO, ProfileName.LIVE, ProfileName.HARDWARE_AUTO, ProfileName.HARDWARE_GUIDED)

#: The `jarvis.voice_replay` v1 actions. They drive controlled doubles (scripted brain,
#: fake provider, owner decisions, fake device), which only the `virtual` profile has;
#: `control.*` works on every profile. Slices 08/09 widen a set only with a runner that
#: performs the primitive on that profile.
REPLAY_PRIMITIVES: tuple[PrimitiveSpec, ...] = (
    _primitive("user.turn", ("turn_id", "content_tag"), ("addressing",), _VIRTUAL,
               "A committed user turn identified by an opaque content tag.", replay=True),
    _primitive("brain.hold", ("work_id",), (), _VIRTUAL, "The scripted brain starts holding work.", replay=True),
    _primitive("brain.ready", ("work_id", "result_tag"), (), _VIRTUAL,
               "The scripted brain produces a result tag for held work.", replay=True),
    _primitive("brain.release", ("work_id",), (), _VIRTUAL, "The scripted brain releases held work.", replay=True),
    _primitive("scheduler.enqueue", ("candidate_id", "kind"), ("work_id", "intent_id", "intent_epoch", "ttl_ms"),
               _VIRTUAL, "A speech candidate enters the speech scheduler.", replay=True),
    _primitive("provider.output_started", ("output_id",), (), _VIRTUAL, "The fake provider starts an output.",
               replay=True),
    _primitive("provider.transcript_final", ("output_id", "generated_tag"), (), _VIRTUAL,
               "The fake provider reports the generated words as an opaque tag.", replay=True),
    _primitive("provider.output_done", ("output_id", "status"), (), _VIRTUAL,
               "The fake provider ends an output with a terminal status.", replay=True),
    _primitive("provider.cancel_rejected", ("output_id", "reason_code"), (), _VIRTUAL,
               "The fake provider refuses a cancel.", replay=True),
    _primitive("provider.session_closed", ("reason",), (), _VIRTUAL, "The fake provider session closes.",
               replay=True),
    _primitive("owner.candidate", ("candidate_id",), (), _VIRTUAL, "A barge-in owner candidate opens.", replay=True),
    _primitive("owner.rejected", ("candidate_id",), ("reason_code",), _VIRTUAL,
               "The barge-in owner candidate is rejected.", replay=True),
    _primitive("owner.confirmed", ("candidate_id", "played_ms"), ("provider_item_id",), _VIRTUAL,
               "The barge-in owner candidate is confirmed.", replay=True),
    _primitive("device.output_busy", (), ("output_id", "playback_id", "played_ms"), _VIRTUAL,
               "The fake output device is playing.", replay=True, requires_any=(("output_id", "playback_id"),)),
    _primitive("device.consume", ("output_id", "played_ms"), (), _VIRTUAL,
               "The fake output device consumes played audio.", replay=True),
    _primitive("device.release", ("output_id",), ("provider_still_active",), _VIRTUAL,
               "The fake output device releases an output.", replay=True),
    _primitive("control.stop", ("reason",), (), ALL_PROFILES, "The session is stopped.", replay=True),
    _primitive("control.checkpoint", ("checkpoint_id",), (), ALL_PROFILES,
               "The executor settles and records a named checkpoint.", replay=True),
)

TESTLAB_PRIMITIVES: tuple[PrimitiveSpec, ...] = (
    _primitive("user.speech", ("turn_id", "text"), ("addressing",), _SPOKEN,
               "The user says an authored utterance (virtual transcript, live text input, guided: the human says it)."),
    _primitive("user.interrupt", ("turn_id", "text"), (), _SPOKEN,
               "The user starts speaking over Jarvis output with an authored utterance."),
    _primitive("time.wait", (), (), ALL_PROFILES,
               "Virtual time advances to at_ms with no stimulus (lets timers, TTLs and queues act)."),
    _primitive("audio.inject", ("audio_ref",), ("gain_db",), _ACOUSTIC,
               "A known audio fixture is played into the audio input path (reference only, never bytes)."),
    _primitive("parameter.override", ("parameter", "value"), (), ALL_PROFILES,
               "Run-local value of a declared parameter or allowlisted setting, applied before the run starts."),
    _primitive("expect.event", ("event",), ("count_min", "count_max"), ALL_PROFILES,
               "The run must record the Conversation Events type between count_min (default 1) and count_max times.",
               ordered=(("count_min", "count_max"),)),
    _primitive("expect.metric", ("metric", "comparator", "threshold"), (), ALL_PROFILES,
               "Ad-hoc check of a declared metric, evaluated on the final run metrics."),
    _primitive("expect.assertion", ("assertion_id", "outcome"), (), ALL_PROFILES,
               "A declared assertion must end with this outcome (a reproduction expects failed)."),
)


class PrimitiveRegistry(Collection[str]):
    """Immutable registry of primitive specs; a `Collection` of names, so it is the `primitives`
    argument of `Scenario.from_dict`. Adding a primitive is a reviewed code change, never data."""

    def __init__(self, specs: Iterable[PrimitiveSpec]) -> None:
        indexed: dict[str, PrimitiveSpec] = {}
        for spec in specs:
            if not isinstance(spec, PrimitiveSpec):
                raise fail("a primitive registry holds PrimitiveSpec values")
            if spec.name in indexed:
                raise fail(f"primitive {spec.name} is registered twice")
            indexed[spec.name] = spec
        self._specs = MappingProxyType(dict(sorted(indexed.items())))

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __iter__(self) -> Iterator[str]:
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    @property
    def specs(self) -> tuple[PrimitiveSpec, ...]:
        return tuple(self._specs.values())

    def get(self, name: str) -> PrimitiveSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise PrimitiveError(PRIMITIVE_UNKNOWN, f"{name_for_message(name)} is not a registered primitive")
        return spec

    def replay_actions(self) -> Mapping[str, PrimitiveSpec]:
        """The `jarvis.voice_replay` v1 action vocabulary, by `<port>.<action>`."""
        return MappingProxyType({name: spec for name, spec in self._specs.items() if spec.replay})

    def for_profile(self, profile: ProfileName) -> frozenset[str]:
        return frozenset(name for name, spec in self._specs.items() if spec.supports(profile))

    def to_dict(self) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self._specs.values()]


DEFAULT_PRIMITIVES = PrimitiveRegistry((*REPLAY_PRIMITIVES, *TESTLAB_PRIMITIVES))


# ----------------------------------------------------------------- scenarios

@dataclass(frozen=True, slots=True)
class ScenarioContext:
    """What a scenario is checked against once it belongs to a diagnostic (declared names)."""

    parameters: tuple[ParameterSpec, ...] = ()
    override_allowlist: tuple[ParameterSpec, ...] = ()
    metrics: tuple[MetricSpec, ...] = ()
    assertions: tuple[AssertionSpec, ...] = ()

    @classmethod
    def for_diagnostic(cls, spec: DiagnosticSpec, override_allowlist: tuple[ParameterSpec, ...] = ()) -> ScenarioContext:
        return cls(spec.parameters, override_allowlist, spec.metrics, spec.assertions)


@dataclass(frozen=True, slots=True)
class ScenarioCheck:
    """Facts established by `check_scenario`."""

    #: `at_ms` of the last step: the virtual timeline length.
    end_ms: int
    primitives: frozenset[str]
    #: Profiles that support every step of the scenario.
    supported_profiles: frozenset[ProfileName]
    #: The `parameter.override` prelude, name -> value (validated when a context is given).
    overrides: Mapping[str, Scalar] = field(default_factory=dict)


def check_scenario(scenario: Scenario, *, primitives: PrimitiveRegistry = DEFAULT_PRIMITIVES,
                   profiles: Iterable[ProfileName] = (), context: ScenarioContext | None = None) -> ScenarioCheck:
    """Check a decoded scenario against the vocabulary: registered primitives, argument schemas,
    non-decreasing `at_ms` within `MAX_TIMELINE_MS`, the override prelude, every `profiles` entry
    supporting every step, and (with `context`) declared parameter, metric and assertion names.

    Without `context` the declared-name checks are skipped (standalone ad-hoc scenario); an
    executor always passes the diagnostic's context.
    """
    if not isinstance(scenario, Scenario) or not isinstance(primitives, PrimitiveRegistry):
        raise fail("check_scenario takes a Scenario and a PrimitiveRegistry")
    wanted = tuple(profiles)
    previous = 0
    overrides: dict[str, Scalar] = {}
    prelude = True
    used: set[str] = set()
    supported = set(ALL_PROFILES)
    for index, step in enumerate(scenario.steps):
        where = f"steps[{index}]"
        if step.primitive not in primitives:
            raise PrimitiveError(PRIMITIVE_UNKNOWN, f"{where}.primitive is not a registered primitive")
        spec = primitives.get(step.primitive)
        at_ms = _check_step_time(step, where, previous)
        previous = at_ms
        check_primitive_data(spec, {key: value for key, value in step.args.items() if key != AT_MS}, f"{where}.args")
        for profile in wanted:
            if not spec.supports(profile):
                raise PrimitiveError(PRIMITIVE_PROFILE_UNSUPPORTED,
                                     f"{where}: primitive {spec.name} is not supported by profile {profile.value}")
        used.add(spec.name)
        supported &= spec.profiles
        if spec.name == "parameter.override":
            if not prelude or at_ms != 0:
                raise PrimitiveError(SCENARIO_TIMELINE_INVALID,
                                     f"{where}: parameter.override must come first, at at_ms 0")
            _check_override(step.args, where, overrides, context)
        else:
            prelude = False
        if context is not None:
            _check_expectation(spec.name, step.args, index, context)
    return ScenarioCheck(previous, frozenset(used), frozenset(supported), MappingProxyType(dict(sorted(overrides.items()))))


def _check_step_time(step: ScenarioStep, where: str, previous: int) -> int:
    if AT_MS not in step.args:
        raise PrimitiveArgError(ArgRule.FIELDS, f"{where}.args: missing={[AT_MS]}", AT_MS)
    at_ms = step.args[AT_MS]
    if type(at_ms) is not int or not 0 <= at_ms <= MAX_TIMELINE_MS:
        raise PrimitiveError(SCENARIO_TIMELINE_INVALID, f"{where}.args.at_ms must be an integer from 0 to "
                                                        f"{MAX_TIMELINE_MS}")
    if at_ms < previous:
        raise PrimitiveError(SCENARIO_TIMELINE_INVALID, f"{where}.args.at_ms goes backwards")
    return at_ms


def _check_override(args: Mapping[str, Any], where: str, overrides: dict[str, Scalar],
                    context: ScenarioContext | None) -> None:
    name = args["parameter"]
    if name in overrides:
        raise PrimitiveArgError(ArgRule.INVALID, f"{where}: parameter {name} is overridden twice", "parameter")
    value = args["value"]
    if context is not None:
        declared = {spec.name: spec for spec in (*context.parameters, *context.override_allowlist)}
        spec = declared.get(name)
        if spec is None:
            raise fail(f"{where}.args.parameter is neither a declared parameter nor an allowlisted setting",
                       PARAMETER_INVALID)
        value = check_parameter_value(spec, value, f"{where}.args.value")
    overrides[name] = value


def _check_expectation(primitive: str, args: Mapping[str, Any], index: int, context: ScenarioContext) -> None:
    where = f"steps[{index}]"
    if primitive == "expect.metric":
        metric = {spec.name: spec for spec in context.metrics}.get(args["metric"])
        if metric is None:
            raise fail(f"{where}.args.metric is not declared by the diagnostic", REFERENCE_INVALID)
        # An expectation is an ad-hoc assertion: it is checked by exactly the assertion rules.
        check_assertion_threshold(AssertionSpec(f"expect_step_{index}", metric.name, Comparator(args["comparator"]),
                                                args["threshold"], False), metric)
    elif primitive == "expect.assertion":
        if args["assertion_id"] not in {spec.assertion_id for spec in context.assertions}:
            raise fail(f"{where}.args.assertion_id is not declared by the diagnostic", REFERENCE_INVALID)


# ------------------------------------------------------------ executor seam

class PrimitiveHandler(Protocol):
    """Executor-facing seam, implemented by profile runners (Slice 06 onwards), never by data.

    The executor advances its virtual clock to `step.args["at_ms"]`, then calls the handler
    registered for `step.primitive` on its profile. A handler may be sync or async. This
    module defines no executor; a scenario stays inert data until a runner performs it.
    """

    def __call__(self, step: ScenarioStep, /) -> Awaitable[None] | None: ...


def missing_handlers(primitives: PrimitiveRegistry, profile: ProfileName, handlers: Collection[str]) -> tuple[str, ...]:
    """Primitives the profile supports that a runner's handler table does not cover (sorted)."""
    return tuple(sorted(primitives.for_profile(profile) - set(handlers)))
