from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import io
import threading
import time
import wave


@dataclass(frozen=True, slots=True)
class AudioClip:
    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    mime_type: str = "audio/wav"

    @property
    def duration_ms(self) -> int:
        if self.mime_type == "audio/wav":
            try:
                with wave.open(io.BytesIO(self.data), "rb") as wav:
                    rate = wav.getframerate()
                    frames = wav.getnframes()
                    return int((frames / rate) * 1000) if rate else 0
            except (wave.Error, EOFError):
                pass
        bytes_per_second = self.sample_rate * self.channels * self.sample_width
        return int(len(self.data) / bytes_per_second * 1000) if bytes_per_second else 0


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolOutput:
    call_id: str
    name: str
    output: Any
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class UserTurn:
    turn_id: str
    text: str = ""
    continuation_token: str | None = None
    tool_outputs: tuple[ToolOutput, ...] = field(default_factory=tuple)


class CancellationToken:
    """Thread-safe cancellation primitive shared by async orchestration and audio threads."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.created_at = time.monotonic()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)
