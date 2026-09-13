"""Bounded non-audio canonical batches from Voice to the existing Core owner."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
import time
import uuid

from jarvis.domain.voice_event_codec import encode_voice_event
from jarvis.domain.voice_events import AssistantAudioChunk, AssistantAudioReceived, FrontendLifecycleChanged, VoiceEvent
from jarvis.domain.voice_frontend import FrontendState, VoiceCorrelation, VoiceObservation


class VoiceObservationDispatcher:
    def __init__(self, core, conversation_id: str, session_id: str, *, on_failure=None, journal=None) -> None:
        self.core, self.conversation_id, self.session_id = core, conversation_id, session_id
        self._queue: asyncio.Queue[VoiceEvent] = asyncio.Queue(maxsize=256)
        self._sequence = 0
        self._received: dict[str, float] = {}
        self._worker: asyncio.Task | None = None
        self._failure: Exception | None = None
        self._on_failure, self._journal = on_failure, journal

    async def start(self) -> None:
        result = await asyncio.wait_for(self.core.bind_voice_session(self.conversation_id, self.session_id), 3.0)
        if result.get("result", {}).get("disposition") not in ("applied", "duplicate"):
            raise RuntimeError("voice_ledger_bind_rejected")
        self._worker = asyncio.create_task(self._run(), name="jarvis-voice-observations")

    def observe(self, event: VoiceEvent) -> None:
        if self._failure is not None:
            raise RuntimeError("voice_observation_failed") from None
        if isinstance(event.payload, AssistantAudioChunk):
            key = str(event.correlation.output_id or event.correlation.provider_output_id or event.correlation.speech_id or "")
            if not key:
                raise RuntimeError("voice_audio_identity_missing")
            duration = len(event.payload.audio.pcm) * 1000 / (event.payload.audio.format.sample_rate_hz * 2)
            self._received[key] = self._received.get(key, 0) + duration
            if len(self._received) > 128:
                self._received.pop(next(iter(self._received)))
            event = replace(event, payload=AssistantAudioReceived(self._received[key]))
        # Assignment at the merged boundary, not provider receipt: local events
        # delayed behind acoustic fences cannot conflict with provider counters.
        self._sequence += 1
        event = replace(event, sequence=self._sequence)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            self._fail(exc)
            raise RuntimeError("voice_observation_overflow") from None

    def local(self, payload, correlation: VoiceCorrelation) -> None:
        self.observe(VoiceEvent(str(uuid.uuid4()), 0, correlation,
                                VoiceObservation(datetime.now(timezone.utc), time.monotonic_ns()), payload))

    async def register_speech(self, correlation: VoiceCorrelation, text: str) -> None:
        await self.flush()
        result = await asyncio.wait_for(self.core.register_voice_speech(self.conversation_id, asdict(correlation), text), 3.0)
        if result.get("result", {}).get("disposition") not in ("applied", "duplicate"):
            raise RuntimeError("voice_ledger_speech_rejected")

    async def _run(self) -> None:
        try:
            while True:
                batch = [await self._queue.get()]
                # One bounded control batch, never a request carrying PCM or a
                # synchronous HTTP call from the audio callback (at most 20 Hz).
                await asyncio.sleep(0.05)
                while len(batch) < 32 and not self._queue.empty():
                    batch.append(self._queue.get_nowait())
                try:
                    result = await asyncio.wait_for(self.core.submit_voice_observations(
                        self.conversation_id, self.session_id, [encode_voice_event(event) for event in batch]), 3.0)
                    results = result.get("results", [])
                    if len(results) != len(batch) or any(item.get("disposition") not in ("applied", "ignored", "duplicate", "stale") for item in results):
                        raise RuntimeError("voice_ledger_evidence_rejected")
                finally:
                    for _ in batch:
                        self._queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        if self._failure is not None:
            return
        self._failure = exc
        if self._journal is not None:
            self._journal.emit("voice.observation_failed", "Canonical voice evidence transport failed", level="error",
                               data={"code": "voice_observation_failed", "conversation_id": self.conversation_id,
                                     "session_id": self.session_id, "exception_type": type(exc).__name__})
        if self._on_failure is not None:
            self._on_failure()

    async def flush(self) -> None:
        if self._failure is not None:
            raise RuntimeError("voice_observation_failed") from None
        await asyncio.wait_for(self._queue.join(), 4.0)
        if self._failure is not None:
            raise RuntimeError("voice_observation_failed") from None

    async def close(self) -> None:
        try:
            await self.flush()
        finally:
            if self._worker is not None:
                self._worker.cancel()
                await asyncio.gather(self._worker, return_exceptions=True)

    async def reconcile_closed(self) -> None:
        """Control-only recovery after confirmed transport close, never audio proof.

        A failed observation stream stays failed. Missing text is not replayed or
        guessed; this explicit reconciliation only releases the old session.
        """
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        response = await asyncio.wait_for(self.core.voice_snapshot(self.conversation_id), 3.0)
        snapshot = response.get("snapshot")
        if snapshot is None or snapshot.get("current_session_id") != self.session_id:
            raise RuntimeError("voice_close_reconciliation_session_mismatch")
        if snapshot.get("lifecycle") == FrontendState.STOPPED.value:
            return
        self._sequence = max(self._sequence, snapshot.get("sequence_floor", -1),
                             *(entry["sequence"] for entry in snapshot.get("seen_events", [])))
        events = []
        for state in (FrontendState.STOPPING, FrontendState.STOPPED):
            self._sequence += 1
            events.append(encode_voice_event(VoiceEvent(str(uuid.uuid4()), self._sequence,
                VoiceCorrelation(self.session_id), VoiceObservation(datetime.now(timezone.utc), time.monotonic_ns()),
                FrontendLifecycleChanged(state))))
        result = await asyncio.wait_for(self.core.submit_voice_observations(self.conversation_id, self.session_id, events), 3.0)
        if any(item.get("disposition") not in ("applied", "duplicate") for item in result.get("results", [])) or len(result.get("results", [])) != 2:
            raise RuntimeError("voice_close_reconciliation_rejected")
