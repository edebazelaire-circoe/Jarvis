from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.adapters.openai_transcription import OpenAITranscriptionBackend
from jarvis.domain.messages import AudioClip


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("JARVIS_LIVE_OPENAI") != "1", reason="opt-in live provider test")
async def test_real_openai_transcription_fixture():
    key = os.environ["OPENAI_API_KEY"]
    model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
    audio = Path("tests/fixtures/bonjour-jarvis.wav").read_bytes()
    result = await OpenAITranscriptionBackend(api_key=key, model=model).transcribe(AudioClip(audio))
    normalized = result.text.casefold()
    assert "jarvis" in normalized
    assert "transcription" in normalized
