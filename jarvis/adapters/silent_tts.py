from __future__ import annotations

from jarvis.domain.messages import CancellationToken
from jarvis.domain.results import SpeechResult


class SilentTTSBackend:
    """Development/text-mode TTS adapter that preserves orchestration semantics."""

    async def speak(self, text: str, *, interrupt: CancellationToken) -> SpeechResult:
        del text
        return SpeechResult(
            duration_ms=0,
            interrupted=interrupt.cancelled,
            provider="silent",
            model="none",
            diagnostics={"speech_disabled": True},
        )
