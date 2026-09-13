"""Duplex GPT-Live composition over the canonical VoiceFrontend port."""
from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
import uuid

from jarvis.adapters.openai_live_frontend import OpenAILiveFrontend, aiohttp_live_connector
from jarvis.domain.live_prompt import LIVE_OPERATING_RULES
from jarvis.domain.prompt_registry import PromptTarget
from jarvis.domain.v2 import PlaybackCursor, ProtocolEnvelope, SpeechRequest
from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
from jarvis.domain.voice_events import (
    AssistantAudioChunk, AssistantPlaybackEvidence, AssistantTranscriptDelta,
    UserTranscriptDelta, VoiceDelegationRequested,
    VoiceFrontendFailed, VoicePlaybackStatus, VoiceUsageSource, VoiceUsageUpdated,
)
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceAudioChunk, VoiceCorrelation, VoiceFrontendConfig,
    VoiceOperation, VoiceOperationResult, VoiceOperationStatus, VoicePcmFormat, VoiceStopReason,
    VoiceTextUpdate,
)
from jarvis.runtime.conversation_context import selected_voice_context
from jarvis.runtime.live_delegation import LiveDelegationController
from jarvis.runtime.live_primary_owner import DurableLiveSessionOwner
from jarvis.runtime.voice_observations import VoiceObservationDispatcher


class LiveFrontendSession:
    """Migration facade for the existing device bridge; canonical Core remains primary."""

    canonical_history = True
    audio_observation_starts_output = True
    requires_local_quiescence_without_output_final = True

    def __init__(self, frontend: OpenAILiveFrontend, session_id: str, *, poll_interval_s: float = .05,
                 lifecycle_owner: DurableLiveSessionOwner | None = None, prompt_evidence=None) -> None:
        self.frontend, self.session_id = frontend, session_id
        self._poll_interval_s = poll_interval_s
        self.core = None
        self.conversation_id: str | None = None
        self._dispatcher: VoiceObservationDispatcher | None = None
        self._delegations: LiveDelegationController | None = None
        self._outputs: OrderedDict[str, VoiceCorrelation] = OrderedDict()
        self._declared_outputs: set[str] = set()
        self._reading = False
        self._reader_ended = asyncio.Event()
        self._reader_ended.set()
        self._close_task: asyncio.Task | None = None
        self._closed = False
        self.stop_result = None
        self.journal = None
        self.input_observation_revision = 0
        self._playback_suppressed = False
        self._lifecycle_owner = lifecycle_owner
        self.prompt_applications = [dict(prompt_evidence)] if isinstance(prompt_evidence, dict) else []

    @classmethod
    async def connect(cls, *, api_key: str, voice: str, context: dict[str, object],
                      architecture_config: DuplexVoiceConfig | None = None,
                      connector=None, poll_interval_s: float = .05,
                      start_timeout_s: float = 15.0, ack_timeout_s: float = 15.0,
                      close_timeout_s: float = 5.0, queue_limit: int = 256,
                      core=None, prompt_overrides=None, **_unused):
        mode = architecture_config or DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))
        from jarvis.runtime.prompt_runtime import prompt_channel, prompt_evidence, resolve_prompt
        resolution = resolve_prompt(
            PromptTarget("conversation", "duplex", "openai", mode.conversation_model.model_id, "explicit", "session"),
            overrides=prompt_overrides,
            variables={"context": context},
        )
        session_id = str(uuid.uuid4())
        owner = DurableLiveSessionOwner(core, session_id) if core is not None else None
        frontend = OpenAILiveFrontend(
            connector or aiohttp_live_connector(api_key), voice=voice,
            start_timeout_s=start_timeout_s, ack_timeout_s=ack_timeout_s,
            close_timeout_s=close_timeout_s, queue_limit=queue_limit,
            lifecycle_hooks=owner,
        )
        session = cls(frontend, session_id, poll_interval_s=poll_interval_s,
                      lifecycle_owner=owner,
                      prompt_evidence=prompt_evidence(resolution, application="sent", channel="session.instructions"))
        if owner is not None:
            owner.set_fenced_callback(session._on_fenced)
        config = VoiceFrontendConfig(mode, initial_context=selected_voice_context(context),
                                     instructions=prompt_channel(resolution, "session.instructions"),
                                     input_format=VoicePcmFormat(24000))
        operation = session._operation()
        # No durable lease and no provider socket exist until the exact bounded
        # startup payload has passed validation.
        frontend.validate_start(config, operation)
        if owner is not None:
            await owner.reserve()
        try:
            result = await frontend.start(config, operation=operation)
            session._require(result)
            return session
        except BaseException as failure:
            # ``start`` is shielded by the adapter and can outlive this caller.
            # Keep a facade-owned cleanup task until that owner settles, then
            # stop the resulting incarnation and wait for transport cleanup.
            cleanup = asyncio.create_task(
                session._cleanup_failed_connect(config), name="jarvis-live-connect-cleanup",
            )
            cancelled = isinstance(failure, asyncio.CancelledError)
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
                except BaseException:
                    break
            if not cleanup.cancelled():
                try:
                    cleanup.result()
                except BaseException:
                    pass
            if cancelled:
                raise asyncio.CancelledError from None
            raise

    async def _cleanup_failed_connect(self, config: VoiceFrontendConfig) -> None:
        # Latch stop before joining the shielded start owner. If it is blocked
        # in provider-ID binding, the bind may complete for recovery but its
        # following ACTIVE transition is fenced.
        if self._lifecycle_owner is not None:
            try:
                await self._lifecycle_owner.begin_stop(VoiceStopReason.CANCELLED.value)
            except BaseException:
                pass
        try:
            await self.frontend.start(config, operation=self._operation())
        except BaseException:
            pass
        try:
            await self.frontend.stop(VoiceStopReason.CANCELLED, operation=self._operation())
        except BaseException:
            pass
        if self._lifecycle_owner is not None and self.frontend.state is not FrontendState.STOPPED:
            try:
                await self._lifecycle_owner.mark_unknown("connect_cleanup_unconfirmed")
            except BaseException:
                pass
        try:
            await self.frontend.wait_transport_closed()
        except BaseException:
            pass
        if self._lifecycle_owner is not None:
            try:
                await self._lifecycle_owner.close()
            except BaseException:
                pass

    async def _on_fenced(self) -> None:
        # Do not call back into the heartbeat owner task. A separate stop owner
        # performs urgent provider close even though further CAS is fenced.
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close(VoiceStopReason.ERROR), name="jarvis-live-fenced-stop",
            )

    def operation_id(self) -> str:
        return str(uuid.uuid4())

    def _operation(self, correlation: VoiceCorrelation | None = None) -> VoiceOperation:
        return VoiceOperation(self.operation_id(), correlation or VoiceCorrelation(self.session_id))

    @staticmethod
    def _require(result) -> None:
        if result.status not in {VoiceOperationStatus.ACCEPTED, VoiceOperationStatus.COMPLETED}:
            raise RuntimeError(result.error.code.value if result.error else "voice_operation_failed")

    async def attach_core(self, core, conversation_id: str, *, on_failure=None, journal=None) -> None:
        self.core, self.conversation_id = core, conversation_id
        self.journal = journal
        self._dispatcher = VoiceObservationDispatcher(core, conversation_id, self.session_id,
                                                      on_failure=on_failure, journal=journal)
        await self._dispatcher.start()
        if journal is not None:
            for item in self.prompt_applications:
                journal.emit("voice.prompt", "Prompt application recorded", data=dict(item))
        self._delegations = LiveDelegationController(self, poll_interval_s=self._poll_interval_s)

    async def flush_observations(self) -> None:
        if self._dispatcher is None:
            raise RuntimeError("Live Core observation dispatcher is not attached")
        await self._dispatcher.flush()

    @property
    def active_output_id(self) -> str | None:
        return next(reversed(self._outputs), None) if self._outputs else None

    async def send_audio(self, pcm: bytes) -> None:
        if self._lifecycle_owner is not None:
            self._lifecycle_owner.assert_active()
        for offset in range(0, len(pcm), 48000):
            chunk = pcm[offset:offset + 48000]
            if chunk:
                self._require(await self.frontend.send_audio(VoiceAudioChunk(chunk), operation=self._operation()))

    async def finish_input(self) -> bool:
        return False

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result
        raise RuntimeError("voice_operation_unsupported")

    async def send_context(self, text: str) -> None:
        if self._lifecycle_owner is not None:
            self._lifecycle_owner.assert_active()
        self._require(await self.frontend.append_quiet_context(VoiceTextUpdate(text), operation=self._operation()))

    async def keepalive(self) -> None:
        return None

    async def speak_reserved(self, request: SpeechRequest, *, output_id: str) -> str:
        return await self.speak(request, output_id=output_id)

    async def speak(self, request: SpeechRequest, *, output_id: str | None = None) -> str:
        if self._lifecycle_owner is not None:
            self._lifecycle_owner.assert_active()
        correlation = VoiceCorrelation(self.session_id, speech_id=request.id, output_id=output_id,
                                       source_correlation_id=request.correlation_id, backend_work_id=request.work_id)
        if self._dispatcher is not None:
            await self._dispatcher.register_speech(correlation, request.text)
        self._require(await self.frontend.append_spoken_result(VoiceTextUpdate(request.text),
                                                               operation=self._operation(correlation)))
        return output_id or str(uuid.uuid4())

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        del cursor  # Device suppression happens first; Live has no exact native cancel.
        self.suppress_playback_until_session_end()

    @property
    def playback_suppressed(self) -> bool:
        return self._playback_suppressed

    def suppress_playback_until_session_end(self) -> None:
        """No primary Live boundary distinguishes a new answer from an old tail.

        After application-authorized interruption, every output stays inaudible
        for this incarnation. Only a new session after confirmed close may play;
        input, transcript, delegation and append ACK cannot clear this latch.
        The bridge calls this synchronously before awaiting the device stop.
        """
        self._playback_suppressed = True

    async def truncate(self, cursor: PlaybackCursor) -> None:
        del cursor  # No alignment primitive exists for Live.

    async def invalidate_unstarted_output(self, output_id: str) -> None:
        del output_id

    def set_back_brain_presenter(self, presenter) -> None:
        del presenter  # Live commentary append is the result presentation path.

    def observe_playback(self, payload: dict, *, played_ms: int | None,
                         written_ms: int | None, terminal: bool = False) -> None:
        del terminal
        if self._dispatcher is None:
            return
        correlation = self._outputs.get(str(payload.get("output_id")))
        if correlation is None:
            return
        if played_ms is not None and played_ms > 0:
            status = VoicePlaybackStatus.PARTIAL
        elif written_ms == 0:
            status, played_ms = VoicePlaybackStatus.UNPLAYED, 0
        else:
            status = VoicePlaybackStatus.UNKNOWN
        self._dispatcher.local(AssistantPlaybackEvidence(status, played_ms, confirmed_text=None), correlation)

    def _observe(self, event) -> None:
        if isinstance(event.payload, UserTranscriptDelta):
            self.input_observation_revision += 1
        if event.correlation.output_id:
            key = str(event.correlation.output_id)
            self._outputs[key] = event.correlation
            while len(self._outputs) > 128:
                expired, _ = self._outputs.popitem(last=False)
                self._declared_outputs.discard(expired)
        if isinstance(event.payload, VoiceUsageUpdated) and self.journal is not None:
            try:
                self.journal.emit("voice.live.usage", "Live session usage updated", data={
                    "session_id": self.session_id,
                    "seconds": event.payload.duration_s,
                    "source": event.payload.source.value,
                    "usage_type": (
                        "final" if event.payload.source is VoiceUsageSource.PROVIDER_FINAL else "cumulative"
                    ),
                })
            except Exception:
                pass
        if self._dispatcher is not None:
            self._dispatcher.observe(event)
        if isinstance(event.payload, VoiceDelegationRequested) and self._delegations is not None:
            self._delegations.offer(event)

    def _legacy_events(self, event):
        payload, correlation = event.payload, event.correlation
        output_id = str(correlation.output_id) if correlation.output_id else None
        common = {"output_id": output_id, "response_id": None, "item_id": None,
                  "speech_id": correlation.speech_id}
        if isinstance(payload, AssistantAudioChunk):
            if self.playback_suppressed:
                return  # Canonical received evidence remains, never playback.
            if output_id not in self._declared_outputs:
                self._declared_outputs.add(output_id)
                yield ProtocolEnvelope(message_type="realtime.output_started", payload=common)
            yield ProtocolEnvelope(message_type="realtime.audio", payload={**common,
                "pcm_b64": base64.b64encode(payload.audio.pcm).decode("ascii")})
        elif isinstance(payload, AssistantTranscriptDelta):
            yield ProtocolEnvelope(message_type="realtime.assistant_transcript_delta",
                                   payload={**common, "text": payload.delta})
        elif isinstance(payload, UserTranscriptDelta):
            yield ProtocolEnvelope(message_type="realtime.transcript_delta",
                                   payload={"text": payload.delta, "item_id": None})
        elif isinstance(payload, VoiceFrontendFailed):
            yield ProtocolEnvelope(message_type="realtime.error", payload={"error": {
                "code": payload.error.code.value, "message": payload.error.safe_message or payload.error.code.value}})

    async def events(self):
        self._reading = True
        self._reader_ended.clear()
        try:
            async for event in self.frontend.events():
                self._observe(event)
                for converted in self._legacy_events(event):
                    yield converted
        finally:
            self._reading = False
            self._reader_ended.set()

    async def stop(self, reason: VoiceStopReason = VoiceStopReason.USER) -> VoiceOperationResult:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(reason), name="jarvis-live-session-close")
        return await asyncio.shield(self._close_task)

    async def close(self, reason: VoiceStopReason = VoiceStopReason.USER) -> VoiceOperationResult:
        return await self.stop(reason)

    async def _close(self, reason: VoiceStopReason) -> VoiceOperationResult:
        if self._closed:
            return self.stop_result
        if self._delegations is not None:
            await self._delegations.close()
        if self._lifecycle_owner is not None:
            persistence = self._lifecycle_owner.request_stop(reason.value)
            try:
                await asyncio.wait_for(asyncio.shield(persistence), timeout=.05)
            except BaseException:
                # The owned Core mutation continues. Storage latency/failure
                # never suppresses the urgent provider close.
                pass
        self.stop_result = await self.frontend.stop(reason, operation=self._operation())
        if (self._lifecycle_owner is not None
                and self.stop_result.status is not VoiceOperationStatus.COMPLETED):
            uncertain = self._lifecycle_owner.request_unknown(
                f"{reason.value}_close_unconfirmed",
            )
            try:
                await asyncio.wait_for(asyncio.shield(uncertain), timeout=.05)
            except BaseException:
                pass
        if self._reading:
            try:
                await asyncio.wait_for(self._reader_ended.wait(), 2)
            except TimeoutError:
                pass
        if not self._reading:
            # Bridge cancellation may release the subscription before stop.
            # Drain canonical lifecycle/failure evidence without playing audio.
            async for event in self.frontend.events():
                self._observe(event)
        if self._dispatcher is not None:
            await self._dispatcher.close()
        if self._lifecycle_owner is not None:
            await self._lifecycle_owner.close()
        self._closed = True
        return self.stop_result
