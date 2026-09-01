from __future__ import annotations

from typing import Protocol
from jarvis.domain.messages import AudioClip
from jarvis.domain.results import TranscriptionResult


class TranscriptionBackend(Protocol):
    async def transcribe(self, audio: AudioClip) -> TranscriptionResult: ...
