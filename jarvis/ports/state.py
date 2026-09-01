from __future__ import annotations

from typing import Protocol, Sequence
from jarvis.domain.events import StateEvent


class StatePublisher(Protocol):
    async def publish(self, event: StateEvent, *, waveform: Sequence[float] | None = None) -> None: ...
    async def cleanup(self) -> None: ...
