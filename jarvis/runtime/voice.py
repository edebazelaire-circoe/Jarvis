from __future__ import annotations

import asyncio
import uuid
from typing import Any

from jarvis.domain.errors import AudioDeviceError


class VoiceRuntime:
    """Legacy push-to-talk runtime kept as the v0.2 fallback path.

    Capture locking deliberately covers only recorder start/stop. Transcription,
    agent execution and TTS run outside the lock so a new press can barge in and
    cancel speech through the orchestrator.
    """

    def __init__(self, *, recorder: Any, transcriber: Any, orchestrator: Any, logger: Any | None = None) -> None:
        self.recorder = recorder
        self.transcriber = transcriber
        self.orchestrator = orchestrator
        self.logger = logger
        self._capture_lock = asyncio.Lock()
        self._capturing = False
        self._turn_id: str | None = None

    async def press(self) -> None:
        async with self._capture_lock:
            if self._capturing:
                return
            turn_id = uuid.uuid4().hex
            accepted = await self.orchestrator.begin_listening(turn_id=turn_id)
            if not accepted:
                return
            try:
                self.recorder.start()
            except Exception as exc:
                await self.orchestrator.handle_runtime_error(exc, turn_id=turn_id, context="capture")
                return
            self._turn_id = turn_id
            self._capturing = True
            if self.logger:
                self.logger.event("voice.capture_started", turn_id=turn_id)

    async def release(self) -> None:
        async with self._capture_lock:
            if not self._capturing:
                return
            turn_id = self._turn_id or uuid.uuid4().hex
            self._capturing = False
            self._turn_id = None
            try:
                clip = self.recorder.stop()
            except Exception as exc:
                await self.orchestrator.handle_runtime_error(exc, turn_id=turn_id, context="capture")
                return

        try:
            if not getattr(clip, "data", b""):
                raise AudioDeviceError("Aucun audio capture")
            await self.orchestrator.begin_transcribing(turn_id=turn_id)
            result = await self.transcriber.transcribe(clip)
            text = result.text.strip()
            if not text:
                raise AudioDeviceError("Transcription vide")
            if self.logger:
                self.logger.event("voice.transcribed", turn_id=turn_id, transcript=text)
            await self.orchestrator.handle_text(text, turn_id=turn_id)
        except Exception as exc:
            await self.orchestrator.handle_runtime_error(exc, turn_id=turn_id, context="transcription")
