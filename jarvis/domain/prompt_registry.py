"""Pure, bounded prompt inspection and resolution. No provider I/O or authority."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
import re
from string import Formatter

MAX_PROMPT_TEXT = 32768
MAX_RENDERED_PROMPT_TEXT = MAX_PROMPT_DOCUMENT_BYTES = 262144
MAX_OVERRIDE_TEXT = 8192
MAX_OVERRIDE_ENTRIES = 128
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_REVISION = re.compile(r"[0-9a-f]{64}\Z")


class PromptError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def prompt_id(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PromptError("prompt_id_invalid", "Prompt ID must be a bounded stable identifier")
    return value


def _json_value(value: object, depth: int = 0) -> None:
    if depth > 16:
        raise PromptError("prompt_document_invalid", "Prompt document nesting is too deep")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item, depth + 1)
        return
    raise PromptError("prompt_document_invalid", "Prompt document must contain finite JSON values")


def fingerprint(value: object) -> str:
    _json_value(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise PromptError("prompt_document_invalid", "Prompt document cannot be encoded") from exc
    if len(encoded) > MAX_PROMPT_DOCUMENT_BYTES:
        raise PromptError("prompt_document_too_large", "Prompt document exceeds its byte bound")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise PromptError("prompt_text_invalid", "Prompt text must be bounded text without control characters")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise PromptError("prompt_text_invalid", "Prompt text must be valid Unicode") from exc
    return value


def validate_template(text: str, variables: tuple[str, ...]) -> None:
    try:
        fields = []
        for _, field, spec, conversion in Formatter().parse(text):
            if field is not None:
                if field not in variables or spec or conversion:
                    raise ValueError
                fields.append(field)
        if sorted(fields) != sorted(variables):
            raise ValueError
    except ValueError as exc:
        raise PromptError("prompt_placeholder_invalid", "Every declared placeholder must occur exactly once, without formatting") from exc


def decode_prompt_overrides(raw: object) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "overrides"}:
        raise PromptError("prompt_override_schema_invalid", "Expected versioned prompt overrides")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise PromptError("prompt_override_version_unsupported", "Prompt override schema_version must be integer 1")
    entries = raw["overrides"]
    if not isinstance(entries, dict) or len(entries) > MAX_OVERRIDE_ENTRIES:
        raise PromptError("prompt_override_bound", "Prompt overrides exceed their entry bound")
    for key, item in entries.items():
        prompt_id(key)
        if not isinstance(item, dict) or set(item) != {"base_revision", "text"}:
            raise PromptError("prompt_override_schema_invalid", "Each override needs only base_revision and text")
        revision = item["base_revision"]
        if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
            raise PromptError("prompt_revision_invalid", "Prompt base_revision must be a SHA-256 revision")
        _text(item["text"], MAX_OVERRIDE_TEXT)
    fingerprint(raw)
    return deepcopy(entries)


class PromptOperation(StrEnum):
    APPEND = "append"
    REPLACE = "replace"
    MESSAGE = "message"


@dataclass(frozen=True, slots=True)
class PromptTarget:
    role: str
    architecture: str | None = None
    provider: str | None = None
    model: str | None = None
    compatibility: str | None = "explicit"
    invocation: str = "session"

    def __post_init__(self):
        for value in asdict(self).values():
            if value is not None:
                prompt_id(value)


@dataclass(frozen=True, slots=True)
class PromptDescriptor:
    prompt_id: str
    source_path: str
    source_symbol: str
    default_text: str
    editable: bool = False
    variables: tuple[str, ...] = ()
    apply_policy: str = "next_session"
    source_revision: str = ""
    dynamic: bool = False
    dependencies: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        prompt_id(self.prompt_id)
        if (not isinstance(self.source_path, str) or not self.source_path or not isinstance(self.source_symbol, str)
                or not self.source_symbol or type(self.editable) is not bool or type(self.dynamic) is not bool):
            raise PromptError("prompt_descriptor_invalid", "Prompt descriptor requires provenance and strict flags")
        _text(self.source_path, 512)
        _text(self.source_symbol, 256)
        if self.source_revision and (not isinstance(self.source_revision, str) or not _REVISION.fullmatch(self.source_revision)):
            raise PromptError("prompt_revision_invalid", "Source revision must be an empty value or SHA-256")
        _text(self.default_text, MAX_PROMPT_TEXT)
        if not isinstance(self.variables, tuple) or len(set(self.variables)) != len(self.variables):
            raise PromptError("prompt_descriptor_invalid", "Prompt variables must be a unique tuple")
        for name in self.variables:
            prompt_id(name)
        if not isinstance(self.dependencies, tuple):
            raise PromptError("prompt_descriptor_invalid", "Dependencies must be a tuple")
        for name, identifier in self.dependencies:
            prompt_id(name)
            prompt_id(identifier)
        if len({name for name, _ in self.dependencies}) != len(self.dependencies) or set(self.variables) & {name for name, _ in self.dependencies}:
            raise PromptError("prompt_descriptor_invalid", "Dependency variables must be distinct")
        if self.dynamic and self.editable:
            raise PromptError("prompt_read_only", "Dynamic data builders cannot be edited")
        if self.variables and not self.dynamic:
            validate_template(self.default_text, self.variables + tuple(name for name, _ in self.dependencies))
        if self.apply_policy not in {"next_session", "next_invocation", "acknowledged_replacement", "read_only"}:
            raise PromptError("prompt_descriptor_invalid", "Unknown prompt application policy")

    @property
    def default_revision(self) -> str:
        return fingerprint(asdict(self))

    def to_payload(self) -> dict:
        return {**asdict(self), "variables": list(self.variables), "default_revision": self.default_revision}


@dataclass(frozen=True, slots=True)
class PromptStep:
    prompt_id: str
    channel: str
    operation: PromptOperation = PromptOperation.APPEND
    separator: str = ""

    def __post_init__(self):
        prompt_id(self.prompt_id)
        prompt_id(self.channel)
        _text(self.separator, 256)
        if not isinstance(self.operation, PromptOperation):
            raise PromptError("prompt_program_invalid", "Unknown prompt composition operation")


@dataclass(frozen=True, slots=True)
class PromptProgram:
    program_id: str
    target: PromptTarget
    steps: tuple[PromptStep, ...]

    def __post_init__(self):
        prompt_id(self.program_id)
        if not isinstance(self.target, PromptTarget) or not isinstance(self.steps, tuple) or not 1 <= len(self.steps) <= 64 or any(not isinstance(step, PromptStep) for step in self.steps):
            raise PromptError("prompt_program_invalid", "Prompt program needs a typed target and bounded typed steps")

    def matches(self, target: PromptTarget) -> bool:
        # None on a descriptor target means all configured models/architectures.
        return all(expected is None or expected == getattr(target, key) for key, expected in asdict(self.target).items())


@dataclass(frozen=True, slots=True)
class PromptResolution:
    program_id: str
    target: PromptTarget
    layers: tuple[dict, ...]
    channels: tuple[dict, ...]
    missing_variables: tuple[str, ...]
    static_fingerprint: str
    render_fingerprint: str | None

    def to_payload(self) -> dict:
        return deepcopy({**asdict(self), "layers": list(self.layers), "channels": list(self.channels),
                         "missing_variables": list(self.missing_variables), "application": "preview_only",
                         "provider_internal_prompts": "unavailable"})


class PromptRegistry:
    def __init__(self, descriptors: tuple[PromptDescriptor, ...], programs: tuple[PromptProgram, ...],
                 *, renderers: Mapping[str, Callable[[Mapping[str, object]], str]] | None = None):
        self._descriptors = {item.prompt_id: item for item in descriptors}
        self.programs = programs
        self._renderers = dict(renderers or {})
        if len(self._descriptors) != len(descriptors) or len({item.program_id for item in programs}) != len(programs):
            raise PromptError("prompt_duplicate", "Prompt IDs and program IDs must be unique")
        for program in programs:
            prompt_id(program.program_id)
            if not program.steps:
                raise PromptError("prompt_program_invalid", "Prompt program must have layers")
            for step in program.steps:
                self.require(step.prompt_id)
                prompt_id(step.channel)
                if not isinstance(step.operation, PromptOperation):
                    raise PromptError("prompt_program_invalid", "Unknown prompt composition operation")
        for item in descriptors:
            if item.dynamic and item.prompt_id not in self._renderers:
                raise PromptError("prompt_renderer_missing", "Dynamic descriptor needs its actual builder")
            for _name, dependency in item.dependencies:
                required = self.require(dependency)
                if required.dynamic or required.variables or required.dependencies:
                    raise PromptError("prompt_dependency_invalid", "Dependencies must be static leaf layers")

    def describe(self) -> tuple[PromptDescriptor, ...]:
        return tuple(self._descriptors.values())

    def require(self, identifier: str) -> PromptDescriptor:
        prompt_id(identifier)
        if identifier not in self._descriptors:
            raise PromptError("prompt_unknown", "Unknown prompt layer")
        return self._descriptors[identifier]

    def inspect(self, overrides: object | None = None) -> dict:
        entries = decode_prompt_overrides(overrides) if overrides is not None else {}
        layers = []
        for descriptor in self.describe():
            override = entries.get(descriptor.prompt_id)
            value, conflict = self._effective(descriptor, override)
            effective_revision = fingerprint({"base": descriptor.default_revision, "text": value})
            bindings = [{"program_id": program.program_id, "target": asdict(program.target),
                         "order": index, **asdict(step)} for program in self.programs
                        for index, step in enumerate(program.steps) if step.prompt_id == descriptor.prompt_id]
            layers.append({**descriptor.to_payload(), "current_text": value,
                           "effective_revision": effective_revision, "override": deepcopy(override),
                           "conflict": conflict, "bindings": bindings})
        return {"schema_version": 1, "layers": layers,
                "unknown_overrides": {key: item for key, item in entries.items() if key not in self._descriptors},
                "provider_internal_prompts": "unavailable", "application": "preview_only"}

    @staticmethod
    def _effective(descriptor: PromptDescriptor, override: dict | None) -> tuple[str, str | None]:
        if override is None:
            return descriptor.default_text, None
        if not descriptor.editable:
            return descriptor.default_text, "prompt_read_only"
        if override["base_revision"] != descriptor.default_revision:
            return descriptor.default_text, "prompt_override_stale"
        try:
            validate_template(override["text"], descriptor.variables + tuple(name for name, _ in descriptor.dependencies))
        except PromptError as exc:
            return descriptor.default_text, exc.code
        return override["text"], None

    def resolve(self, target: PromptTarget, *, overrides: object | None = None,
                variables: Mapping[str, object] | None = None) -> PromptResolution:
        programs = [item for item in self.programs if item.matches(target)]
        if len(programs) != 1:
            raise PromptError("prompt_target_unsupported", "Target must match exactly one registered program")
        entries = decode_prompt_overrides(overrides) if overrides is not None else {}
        values = dict(variables or {})
        fingerprint(values)  # Reject nonfinite/oversized input before rendering.
        program = programs[0]
        layers, channels, missing, static = [], [], set(), []
        for index, step in enumerate(program.steps):
            descriptor = self.require(step.prompt_id)
            text, conflict = self._effective(descriptor, entries.get(descriptor.prompt_id))
            dependencies = {}
            for name, identifier in descriptor.dependencies:
                value, dependency_conflict = self._effective(self.require(identifier), entries.get(identifier))
                dependencies[name] = value
                conflict = conflict or dependency_conflict
            bound_values = {**values, **dependencies}
            absent = set(descriptor.variables) - values.keys()
            missing.update(absent)
            rendered = None if absent else (self._renderers[descriptor.prompt_id](bound_values) if descriptor.dynamic
                                            else text.format_map(bound_values) if descriptor.variables or descriptor.dependencies else text)
            if rendered is not None:
                # Static prose keeps its tight descriptor bound. Dynamic JSON
                # can legitimately be larger; the owning adapter still applies
                # its actual serialized request byte ceiling before any send.
                _text(rendered, MAX_RENDERED_PROMPT_TEXT if descriptor.dynamic else MAX_PROMPT_TEXT)
            effective_revision = fingerprint({"base": descriptor.default_revision, "text": text, "dependencies": dependencies})
            layers.append({"prompt_id": descriptor.prompt_id, "revision": effective_revision,
                           "base_revision": descriptor.default_revision, "effective_revision": effective_revision,
                           "source": "override" if entries.get(descriptor.prompt_id) and not conflict else "default",
                           "conflict": conflict, "order": index, "channel": step.channel,
                           "operation": step.operation.value, "text": rendered,
                           "missing_variables": sorted(absent)})
            static.append({"id": descriptor.prompt_id, "revision": descriptor.default_revision, "text": text, "dependencies": dependencies,
                           "channel": step.channel, "operation": step.operation.value, "separator": step.separator})
            if step.operation is PromptOperation.MESSAGE:
                channels.append({"channel": step.channel, "operation": step.operation.value, "text": rendered})
            else:
                existing = next((item for item in channels if item["channel"] == step.channel), None)
                if existing is None or step.operation is PromptOperation.REPLACE:
                    if existing is not None:
                        channels.remove(existing)
                    channels.append({"channel": step.channel, "operation": step.operation.value, "text": rendered})
                elif rendered is None or existing["text"] is None:
                    existing["text"] = None
                elif rendered:
                    existing["text"] += (step.separator if existing["text"] else "") + rendered
        static_hash = fingerprint({"program": program.program_id, "target": asdict(target), "layers": static})
        rendered_hash = None if missing else fingerprint({"static": static_hash, "channels": channels})
        return PromptResolution(program.program_id, target, tuple(layers), tuple(channels), tuple(sorted(missing)), static_hash, rendered_hash)
