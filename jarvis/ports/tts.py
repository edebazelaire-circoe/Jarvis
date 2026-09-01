from __future__ import annotations

from typing import Protocol
from jarvis.domain.messages import CancellationToken
from jarvis.domain.results import SpeechResult


class TTSBackend(Protocol):
    async def speak(self, text: str, *, interrupt: CancellationToken) -> SpeechResult: ...
