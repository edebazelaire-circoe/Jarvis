"""Explicit speech provenance, exact semantic spans and independent outcomes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re

MAX_SPEECH_CHUNK_TEXT = 8192
MAX_SPEECH_TEXT = 65536
MAX_SPEECH_CHUNKS = 16
MAX_SPEECH_DEPENDENCIES = 16
MAX_OUTCOME_TEXT = 65536


def speech_id(value: object, name: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not value or len(value) > 256 or value != value.strip() or not value.isprintable():
        raise ValueError(f"{name} must be a bounded printable identity")


def _shape(value: object, required: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Invalid speech presentation fields")
    return dict(value)


@dataclass(frozen=True, slots=True)
class SpeechDependency:
    work_id: str
    source_correlation_id: str

    def __post_init__(self) -> None:
        speech_id(self.work_id, "work_id")
        speech_id(self.source_correlation_id, "source_correlation_id")

    def to_payload(self) -> dict:
        return {"work_id": self.work_id, "source_correlation_id": self.source_correlation_id}

    @classmethod
    def from_payload(cls, value: object) -> SpeechDependency:
        return cls(**_shape(value, {"work_id", "source_correlation_id"}))


@dataclass(frozen=True, slots=True)
class SpeechSource:
    turn_id: str
    correlation_id: str
    intent_id: str
    intent_epoch: int
    dependencies: tuple[SpeechDependency, ...] = ()

    def __post_init__(self) -> None:
        for name in ("turn_id", "correlation_id", "intent_id"):
            speech_id(getattr(self, name), name)
        if type(self.intent_epoch) is not int or not 0 <= self.intent_epoch <= 2**63 - 1:
            raise ValueError("intent_epoch must be a bounded nonnegative integer")
        if not isinstance(self.dependencies, tuple) or len(self.dependencies) > MAX_SPEECH_DEPENDENCIES or any(not isinstance(item, SpeechDependency) for item in self.dependencies):
            raise ValueError("Speech dependencies must be a bounded typed tuple")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("Speech dependencies must be unique")

    def to_payload(self) -> dict:
        return {"turn_id": self.turn_id, "correlation_id": self.correlation_id, "intent_id": self.intent_id,
                "intent_epoch": self.intent_epoch, "dependencies": [item.to_payload() for item in self.dependencies]}

    @classmethod
    def from_payload(cls, value: object) -> SpeechSource:
        data = _shape(value, {"turn_id", "correlation_id", "intent_id", "intent_epoch", "dependencies"})
        if not isinstance(data["dependencies"], list) or len(data["dependencies"]) > MAX_SPEECH_DEPENDENCIES:
            raise ValueError("Invalid speech dependency list")
        data["dependencies"] = tuple(SpeechDependency.from_payload(item) for item in data["dependencies"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class SpeechTextSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end <= MAX_SPEECH_TEXT:
            raise ValueError("Speech span must be a bounded nonempty exact range")

    def to_payload(self) -> dict:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_payload(cls, value: object) -> SpeechTextSpan:
        return cls(**_shape(value, {"start", "end"}))


class SpeechCandidateStatus(StrEnum):
    ELIGIBLE = "eligible"
    SELECTED = "selected"
    STARTED = "started"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class SpeechChunk:
    chain_id: str
    index: int
    count: int
    span: SpeechTextSpan

    def __post_init__(self) -> None:
        speech_id(self.chain_id, "chain_id")
        if type(self.index) is not int or type(self.count) is not int or not 0 <= self.index < self.count <= MAX_SPEECH_CHUNKS:
            raise ValueError("Invalid bounded chunk order")
        if not isinstance(self.span, SpeechTextSpan):
            raise ValueError("Chunk span must be typed")

    def to_payload(self) -> dict:
        return {"chain_id": self.chain_id, "index": self.index, "count": self.count, "span": self.span.to_payload()}


def semantic_text_spans(text: str) -> tuple[SpeechTextSpan, ...]:
    """Only explicit paragraph boundaries; preserve whitespace, decimals and abbreviations."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_SPEECH_TEXT:
        raise ValueError("Speech text must be nonempty and bounded")
    boundaries = [0]
    for match in re.finditer(r"\r?\n[ \t]*\r?\n", text):
        if text[boundaries[-1]:match.end()].strip() and text[match.end():].strip():
            boundaries.append(match.end())
    boundaries.append(len(text))
    if len(boundaries) - 1 > MAX_SPEECH_CHUNKS:
        raise ValueError("Semantic speech chain exceeds chunk bound")
    if any(end - start > MAX_SPEECH_CHUNK_TEXT for start, end in zip(boundaries, boundaries[1:])):
        raise ValueError("A semantic paragraph exceeds the provider chunk limit")
    return tuple(SpeechTextSpan(start, end) for start, end in zip(boundaries, boundaries[1:]))


class OutcomeKind(StrEnum):
    TURN_RESULT = "turn_result"
    WORK_RESULT = "work_result"
    SPEECH_RESULT = "speech_result"


class OutcomeStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BackendOutcome:
    id: str
    conversation_id: str
    source: SpeechSource | None
    work_id: str | None
    text: str = field(repr=False)
    created_at: datetime
    kind: OutcomeKind
    status: OutcomeStatus

    def __post_init__(self) -> None:
        speech_id(self.id, "outcome_id")
        speech_id(self.conversation_id, "conversation_id")
        speech_id(self.work_id, "work_id", optional=True)
        if self.source is not None and not isinstance(self.source, SpeechSource):
            raise ValueError("Outcome source must be typed")
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > MAX_OUTCOME_TEXT:
            raise ValueError("Outcome text must be nonempty and bounded")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Outcome timestamp must be timezone aware")
        if not isinstance(self.kind, OutcomeKind) or not isinstance(self.status, OutcomeStatus):
            raise ValueError("Outcome kind/status must be typed")

    def to_payload(self) -> dict:
        return {"id": self.id, "conversation_id": self.conversation_id, "source": self.source.to_payload() if self.source else None,
                "work_id": self.work_id, "text": self.text, "created_at": self.created_at.isoformat(), "kind": self.kind.value, "status": self.status.value}

    @classmethod
    def from_payload(cls, value: object) -> BackendOutcome:
        data = _shape(value, {"id", "conversation_id", "source", "work_id", "text", "created_at", "kind", "status"})
        data["source"] = SpeechSource.from_payload(data["source"]) if data["source"] is not None else None
        if not isinstance(data["created_at"], str):
            raise ValueError("Outcome timestamp must be ISO8601 text")
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["kind"], data["status"] = OutcomeKind(data["kind"]), OutcomeStatus(data["status"])
        return cls(**data)
