from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pytest

from jarvis.domain.events import StateEvent
from jarvis.domain.messages import CancellationToken, UserTurn
from jarvis.domain.results import AgentResult, SpeechResult


@dataclass
class RecordingStatePublisher:
    events: list[StateEvent] = field(default_factory=list)
    waveforms: list[list[float] | None] = field(default_factory=list)
    cleaned: bool = False

    async def publish(self, event: StateEvent, *, waveform=None):
        self.events.append(event)
        self.waveforms.append(None if waveform is None else list(waveform))

    async def cleanup(self):
        self.cleaned = True


class ScriptedAgent:
    def __init__(self, *results: AgentResult):
        self.results = deque(results)
        self.turns: list[UserTurn] = []

    async def respond(self, turn, tools):
        self.turns.append(turn)
        if not self.results:
            raise AssertionError("No scripted agent result left")
        return self.results.popleft()


class RecordingTTS:
    def __init__(self):
        self.texts: list[str] = []
        self.tokens: list[CancellationToken] = []

    async def speak(self, text: str, *, interrupt: CancellationToken):
        self.texts.append(text)
        self.tokens.append(interrupt)
        return SpeechResult(
            duration_ms=1,
            interrupted=interrupt.cancelled,
            provider="fake",
            model="fake",
        )


class RecordingBoard:
    def __init__(self, *, fail: bool = False):
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def present(self, title, body, *, x=None, y=None):
        if self.fail:
            raise ConnectionError("board down")
        payload = {"title": title, "body": body, "x": x, "y": y}
        self.calls.append(payload)
        return {"presented": True, **payload}

    async def health(self):
        return not self.fail


@pytest.fixture
def agent_result_factory():
    def make(text="", tool_calls=(), continuation_token=None):
        return AgentResult(
            text=text,
            tool_calls=tuple(tool_calls),
            provider="fake",
            model="fake",
            duration_ms=1,
            continuation_token=continuation_token,
        )
    return make
