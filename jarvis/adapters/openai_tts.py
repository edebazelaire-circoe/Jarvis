from __future__ import annotations

import time
import httpx

from jarvis.audio.playback import SoundDevicePlayback
from jarvis.domain.errors import ProviderError
from jarvis.domain.messages import CancellationToken
from jarvis.domain.results import SpeechResult
from .openai_http import OpenAIHTTP


class OpenAITTSBackend:
    # The current speech API accepts at most 4096 input characters. Leave
    # margin for provider-side counting quirks and split in the adapter so a
    # verbose agent reply degrades to sequential speech instead of a 400.
    MAX_CHARS_PER_REQUEST = 3900

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        voice: str,
        instructions: str = "",
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 45.0,
        client: httpx.AsyncClient | None = None,
        playback: SoundDevicePlayback | None = None,
    ) -> None:
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.http = OpenAIHTTP(api_key=api_key, base_url=base_url, timeout_s=timeout_s, client=client)
        self.playback = playback or SoundDevicePlayback()

    async def speak(self, text: str, *, interrupt: CancellationToken) -> SpeechResult:
        if not text.strip():
            return SpeechResult(0, False, "openai", self.model, {"empty": True})
        started = time.perf_counter()
        network_ms = 0
        playback_ms = 0
        audio_bytes = 0
        chunk_count = 0
        interrupted = interrupt.cancelled
        for chunk in self._split_text(text):
            if interrupt.cancelled:
                interrupted = True
                break
            payload = {
                "model": self.model,
                "voice": self.voice,
                "input": chunk,
                "response_format": "wav",
            }
            if self.instructions:
                payload["instructions"] = self.instructions
            request_started = time.perf_counter()
            response = await self.http.post_json("/audio/speech", payload, operation="tts")
            network_ms += int((time.perf_counter() - request_started) * 1000)
            audio = response.content
            if not audio:
                raise ProviderError("openai", "tts", "Empty speech response")
            this_playback_ms, this_interrupted = await self.playback.play_wav(audio, interrupt=interrupt)
            playback_ms += this_playback_ms
            audio_bytes += len(audio)
            chunk_count += 1
            if this_interrupted or interrupt.cancelled:
                interrupted = True
                break
        return SpeechResult(
            duration_ms=int((time.perf_counter() - started) * 1000),
            interrupted=interrupted,
            provider="openai",
            model=self.model,
            diagnostics={
                "network_ms": network_ms,
                "playback_ms": playback_ms,
                "audio_bytes": audio_bytes,
                "chunk_count": chunk_count,
            },
        )

    @classmethod
    def _split_text(cls, text: str) -> list[str]:
        remaining = text.strip()
        chunks: list[str] = []
        while remaining:
            if len(remaining) <= cls.MAX_CHARS_PER_REQUEST:
                chunks.append(remaining)
                break
            window = remaining[: cls.MAX_CHARS_PER_REQUEST + 1]
            cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "), window.rfind("\n"))
            if cut >= cls.MAX_CHARS_PER_REQUEST // 2:
                cut += 1
            else:
                cut = window.rfind(" ", 0, cls.MAX_CHARS_PER_REQUEST + 1)
            if cut <= 0:
                cut = cls.MAX_CHARS_PER_REQUEST
            chunks.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        return [chunk for chunk in chunks if chunk]
