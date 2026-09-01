from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import time


class JarvisState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StateEvent:
    state: JarvisState
    turn_id: str | None = None
    message: str | None = None
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            object.__setattr__(self, "timestamp", time.time())
