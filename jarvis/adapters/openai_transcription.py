from __future__ import annotations

import time
import httpx

from jarvis.domain.errors import ProviderError
from jarvis.domain.messages import AudioClip
from jarvis.domain.results import TranscriptionResult
from .openai_http import OpenAIHTTP


class OpenAITranscriptionBackend:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 45.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.http = OpenAIHTTP(api_key=api_key, base_url=base_url, timeout_s=timeout_s, client=client)

    async def transcribe(self, audio: AudioClip) -> TranscriptionResult:
        started = time.perf_counter()
        response = await self.http.post_multipart(
            "/audio/transcriptions",
            data={"model": self.model},
            files={"file": ("speech.wav", audio.data, audio.mime_type)},
            operation="transcription",
        )
        try:
            payload = response.json()
            text = str(payload.get("text", "")).strip()
        except Exception as exc:
            raise ProviderError("openai", "transcription", "Invalid transcription response") from exc
        if not text:
            raise ProviderError("openai", "transcription", "Empty transcription response")
        duration_ms = int((time.perf_counter() - started) * 1000)
        usage = payload.get("usage") if isinstance(payload, dict) else None
        diagnostics = {"http_status": response.status_code}
        if isinstance(usage, dict):
            diagnostics["usage_type"] = usage.get("type")
            diagnostics["total_tokens"] = usage.get("total_tokens")
        return TranscriptionResult(
            text=text,
            duration_ms=duration_ms,
            provider="openai",
            model=self.model,
            diagnostics=diagnostics,
        )
