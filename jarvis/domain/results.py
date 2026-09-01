from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .messages import ToolCall


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    duration_ms: int
    provider: str
    model: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentResult:
    text: str
    tool_calls: tuple[ToolCall, ...]
    provider: str
    model: str
    duration_ms: int
    continuation_token: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SpeechResult:
    duration_ms: int
    interrupted: bool
    provider: str
    model: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class MemoryHit:
    memory_id: str
    title: str
    snippet: str
    score: float


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    turn_id: str
    text: str
    awaiting_confirmation: bool = False
    action_id: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
