"""Temporary typed facade for existing audio fences; no raw-session escape.

Remove when the bridge/scheduler consume VoiceFrontend natively (migration17).
See docs/legacy/realtime-frontend-facade.md. Gemini does not use this facade.
"""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from dataclasses import replace
import json
import uuid

from jarvis.adapters.openai_realtime import OpenAIRealtimeSession, build_session_instructions
from jarvis.adapters.openai_realtime_frontend import OpenAIRealtimeFrontend
from jarvis.domain.v2 import PlaybackCursor, ProtocolEnvelope, SpeechRequest
from jarvis.domain.voice_architecture import SimpleVoiceConfig, VoiceModelRef
from jarvis.domain.prompt_registry import PromptTarget
from jarvis.domain.voice_events import (
    AssistantAudioPartCompleted,
    AssistantAudioChunk, AssistantGenerationFinished, AssistantGenerationStarted,
    AssistantPlaybackEvidence, AssistantTranscriptCompleted, AssistantTranscriptDelta,
    FrontendLifecycleChanged, UserSpeechActivity, UserTranscriptCommitted, UserTranscriptDelta,
    UserTurnOpened, VoiceFrontendFailed, VoicePlaybackStatus, VoiceSpeechPhase, VoiceToolCallRequested,
    VoiceUsageUpdated,
)
from jarvis.domain.voice_frontend import (
    VoiceAudioChunk, VoiceContextMessage, VoiceContextRole, VoiceCorrelation, VoiceFrontendConfig,
    VoiceOperation, VoiceOperationStatus, VoiceReflexRequest, VoiceStopReason, VoiceTextUpdate, VoiceToolResult, VoiceConversationRequest,
)
from jarvis.runtime.voice_observations import VoiceObservationDispatcher
from jarvis.runtime.voice_playback_manifest import VoicePlaybackManifests
from jarvis.domain.voice_playback import VoiceAudioPart, VoiceDevicePlaybackProof, VoicePlaybackManifest


class RealtimeFrontendSession:
    canonical_history = True

    def __init__(self, frontend: OpenAIRealtimeFrontend, session_id: str, *, prompt_evidence=None) -> None:
        self.frontend = frontend
        self.session_id = session_id
        self._dispatcher: VoiceObservationDispatcher | None = None
        self._outputs: OrderedDict[str, VoiceCorrelation] = OrderedDict()
        self._pending_users: OrderedDict[str, object] = OrderedDict()
        self._pending_open: OrderedDict[str, object] = OrderedDict()
        self._input_order: OrderedDict[str, tuple[str | None, str]] = OrderedDict()
        self._source_turns: OrderedDict[str, str] = OrderedDict()
        self._reading = False
        self._reader_ended = asyncio.Event()
        self._reader_ended.set()
        self._closed = False
        self._close_task: asyncio.Task | None = None
        self._playback_manifests = VoicePlaybackManifests()
        self.analysis = None
        self._admitted_items: OrderedDict[str, object] = OrderedDict()
        self._conversation_sources: OrderedDict[str, object] = OrderedDict()
        self._conversation_references: OrderedDict[str, int] = OrderedDict()
        self._back_brain = None
        self.journal = None
        self.conversation_id: str | None = None
        self.prompt_applications = [dict(prompt_evidence)] if isinstance(prompt_evidence, dict) else []
        self._prompt_event_cursor = 0

    @classmethod
    async def connect(cls, *, context: dict[str, object], **settings):
        model = str(settings["model"])
        mode = settings.pop("architecture_config", None) or SimpleVoiceConfig(VoiceModelRef("openai", model))
        conversational = bool(settings.pop("conversational", False))
        prompt_overrides = settings.pop("prompt_overrides", None)
        if conversational and "voice_ledger" not in context:
            # Legacy history can contain intended partial assistant text. Until
            # canonical evidence exists, do not present it as heard context.
            context = {**context, "recent_turns": [item for item in context.get("recent_turns", []) if isinstance(item, dict) and item.get("kind") == "user"]}
        compatibility = "explicit" if conversational else (
            "continuous_brain" if bool(settings.get("continuous_brain", False)) else "legacy"
        )
        from jarvis.runtime.prompt_runtime import prompt_channel, prompt_evidence, resolve_prompt
        resolution = resolve_prompt(
            PromptTarget("conversation", mode.architecture.value, "openai", model, compatibility, "session"),
            overrides=prompt_overrides,
            variables={"context": context},
        )
        instructions = prompt_channel(resolution, "session.instructions")
        resolved_tools = json.loads(prompt_channel(resolution, "session.tools"))
        if not isinstance(resolved_tools, list):
            raise ValueError("resolved Realtime tools must be a list")
        settings["tools"] = resolved_tools
        from jarvis.runtime.conversation_context import selected_voice_context
        from jarvis.domain.voice_frontend import VoiceContext
        initial_context = selected_voice_context(context) if conversational else VoiceContext()
        config = VoiceFrontendConfig(mode, instructions=instructions, initial_context=initial_context)
        async def connector(selected):
            return await OpenAIRealtimeSession.connect(
                context=context,
                instructions_override=selected.instructions,
                prompt_overrides=prompt_overrides,
                **settings,
            )
        frontend = OpenAIRealtimeFrontend(connector)
        facade = cls(
            frontend,
            str(uuid.uuid4()),
            prompt_evidence=prompt_evidence(resolution, application="acknowledged", channel="session.instructions"),
        )
        if conversational:
            from jarvis.runtime.back_brain_delegation import BackBrainDelegationController
            facade._back_brain = BackBrainDelegationController(facade)
        result = await frontend.start(config, operation=facade._operation())
        facade._require(result)
        for item_id in getattr(frontend, "initial_context_item_ids", ()):
            facade._remember_conversation_reference(item_id, 0)
        return facade

    def _operation(self, correlation: VoiceCorrelation | None = None) -> VoiceOperation:
        return VoiceOperation(str(uuid.uuid4()), correlation or VoiceCorrelation(self.session_id))

    @staticmethod
    def _require(result) -> None:
        if result.status not in (VoiceOperationStatus.ACCEPTED, VoiceOperationStatus.COMPLETED):
            raise RuntimeError(result.error.code.value if result.error else "voice_operation_failed")

    async def attach_core(self, core, conversation_id: str, *, on_failure=None, journal=None) -> None:
        self.journal = journal
        self.conversation_id = conversation_id
        if self._back_brain is not None:
            self._back_brain.journal = journal
        self._dispatcher = VoiceObservationDispatcher(core, conversation_id, self.session_id, on_failure=on_failure, journal=journal)
        await self._dispatcher.start()
        self._flush_prompt_evidence()

    def _flush_prompt_evidence(self) -> None:
        applications = self.prompt_applications + list(self.frontend.prompt_applications)
        if self.journal is None:
            return
        for item in applications[self._prompt_event_cursor:]:
            self.journal.emit("voice.prompt", "Prompt application recorded", data=dict(item))
        self._prompt_event_cursor = len(applications)

    @property
    def active_output_id(self) -> str | None:
        return self.frontend.active_output_id

    async def send_audio(self, pcm: bytes) -> None:
        for offset in range(0, len(pcm), 48000):
            self._require(await self.frontend.send_audio(VoiceAudioChunk(pcm[offset:offset + 48000]), operation=self._operation()))

    async def finish_input(self) -> bool:
        result = await self.frontend.finish_input(operation=self._operation())
        if result.status is VoiceOperationStatus.REJECTED and result.error.code.value == "voice_invalid_input":
            return False
        self._require(result)
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        self._require(await self.frontend.send_tool_result(VoiceToolResult(call_id, json.dumps(result, ensure_ascii=False)), operation=self._operation()))

    async def send_back_brain_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        self._require(await self.frontend.send_tool_result(
            VoiceToolResult(call_id, json.dumps(result, ensure_ascii=False), request_response=False), operation=self._operation()))

    def dispatch_back_brain(self, core, conversation_id: str, call_id: str) -> bool:
        return self._back_brain is not None and self._back_brain.offer(core, conversation_id, call_id)

    def set_back_brain_presenter(self, presenter) -> None:
        if self._back_brain is not None:
            self._back_brain.presenter = presenter

    async def send_context(self, text: str) -> None:
        self._require(await self.frontend.append_context_message(VoiceContextMessage(VoiceContextRole.USER, text), request_response=True, operation=self._operation()))

    async def keepalive(self) -> None:
        await self.frontend.keepalive()

    async def speak_reserved(self, request: SpeechRequest, *, output_id: str) -> str:
        return await self.speak(request, output_id=output_id)

    async def request_conversation(self, input_item_ids: tuple[str, ...], *, source, output_id: str) -> str:
        if self._closed or any(item not in self._admitted_items for item in input_item_ids) or self._conversation_sources.get(input_item_ids[-1]) != source:
            raise ValueError("conversation input is not admitted")
        prior = [item for item, epoch in self._conversation_references.items()
                 if epoch <= source.intent_epoch and item not in input_item_ids]
        selected = tuple(prior[-(16 - len(input_item_ids)):]) + input_item_ids if len(input_item_ids) < 16 else input_item_ids
        correlation = VoiceCorrelation(self.session_id, output_id=output_id,
            turn_id=self._source_turns.get(source.correlation_id), source_correlation_id=source.correlation_id,
            provider_input_id=input_item_ids[-1])
        if self._back_brain is not None:
            self._back_brain.reserve(correlation, source)
        result = await self.frontend.request_conversation(VoiceConversationRequest(selected), operation=self._operation(correlation))
        self._require(result)
        return str(result.output_id)

    async def admit_conversation(self, core, conversation_id: str, provider_item_id: str, *, addressing):
        event = self._pending_users.get(provider_item_id) or self._admitted_items.get(provider_item_id)
        if event is None or self._dispatcher is None:
            raise ValueError("canonical committed input is unavailable")
        self.admit_transcript(provider_item_id)
        await self._dispatcher.flush()
        result = await core.admit_voice_turn(conversation_id, session_id=self.session_id,
            canonical_turn_id=event.correlation.turn_id, transcript_id=event.payload.transcript_id,
            transcript_revision=event.payload.revision, provider_item_id=provider_item_id,
            text=event.payload.text, addressing=addressing)
        self._source_turns[result.source.correlation_id] = event.correlation.turn_id
        self._conversation_sources[provider_item_id] = result.source
        while len(self._conversation_sources) > 128:
            self._conversation_sources.popitem(last=False)
        self._remember_conversation_reference(provider_item_id, result.source.intent_epoch)
        if self.analysis is not None:
            if not result.duplicate:
                self.analysis.remember_context(VoiceContextMessage(VoiceContextRole.USER, event.payload.text))
            self.analysis.admit_item(provider_item_id, result.source)
        return result

    async def submit_back_brain(self, core, conversation_id: str, acceptance):
        """Submit an already admitted Core source; no text synthesis or speech."""
        from jarvis.domain.voice_admission import VoiceTurnAdmissionAcceptance
        if not isinstance(acceptance, VoiceTurnAdmissionAcceptance) or acceptance.conversation_id != conversation_id:
            raise ValueError("back brain admission does not match conversation")
        return await core.submit_back_brain_task(conversation_id, source_correlation_id=acceptance.correlation_id)

    async def speak(self, request: SpeechRequest, *, output_id: str | None = None) -> str:
        correlation = VoiceCorrelation(self.session_id, speech_id=request.id, output_id=output_id,
            turn_id=self._source_turns.get(request.correlation_id),
            source_correlation_id=request.correlation_id, backend_work_id=request.work_id)
        if self._dispatcher is not None:
            await self._dispatcher.register_speech(correlation, request.text)
        result = await self.frontend.append_spoken_result(VoiceTextUpdate(request.text), operation=self._operation(correlation))
        self._require(result)
        self._flush_prompt_evidence()
        return str(result.output_id)

    async def speak_reflex(self, *, transcript: str, avoid=(), output_id: str | None = None, correlation_id: str | None = None) -> str:
        correlation = VoiceCorrelation(self.session_id, output_id=output_id, source_correlation_id=correlation_id,
                                       turn_id=self._source_turns.get(correlation_id))
        result = await self.frontend.request_reflex(VoiceReflexRequest(transcript, tuple(avoid)), operation=self._operation(correlation))
        self._require(result)
        self._flush_prompt_evidence()
        return str(result.output_id)

    async def invalidate_reflex(self, output_id: str) -> None:
        await self.invalidate_unstarted_output(output_id)

    async def invalidate_unstarted_output(self, output_id: str) -> None:
        if self._back_brain is not None:
            self._back_brain.invalidate(output_id)
        self._playback_manifests.invalidate(output_id)
        correlation = self._outputs.get(output_id, VoiceCorrelation(self.session_id, output_id=output_id))
        self._require(await self.frontend.invalidate_unstarted_output(operation=self._operation(correlation)))

    def _cursor_correlation(self, cursor: PlaybackCursor | None) -> VoiceCorrelation:
        if cursor is None:
            return self._outputs.get(self.active_output_id, VoiceCorrelation(self.session_id))
        for correlation in reversed(self._outputs.values()):
            if ((cursor.provider_response_id and correlation.provider_output_id == cursor.provider_response_id)
                    or correlation.speech_id == cursor.speech_id or correlation.output_id == cursor.speech_id):
                return replace(correlation, provider_item_id=cursor.provider_item_id or correlation.provider_item_id)
        return VoiceCorrelation(self.session_id, speech_id=cursor.speech_id, provider_output_id=cursor.provider_response_id,
                                provider_item_id=cursor.provider_item_id)

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        correlation = self._cursor_correlation(cursor)
        if self._back_brain is not None:
            self._back_brain.invalidate(correlation.output_id)
        self._playback_manifests.invalidate(correlation.output_id)
        self._require(await self.frontend.cancel_speech(operation=self._operation(correlation)))

    async def truncate(self, cursor: PlaybackCursor) -> None:
        correlation = self._cursor_correlation(cursor)
        if self._back_brain is not None:
            self._back_brain.invalidate(correlation.output_id)
        self._playback_manifests.invalidate(correlation.output_id)
        # One cancellation+truncate operation is accepted, never called confirmed.
        part = VoiceAudioPart(cursor.provider_item_id, cursor.content_index) if cursor.provider_item_id and cursor.content_index is not None else None
        evidence = AssistantPlaybackEvidence(VoicePlaybackStatus.PARTIAL if cursor.played_ms else VoicePlaybackStatus.UNPLAYED, cursor.played_ms, part=part)
        self._require(await self.frontend.cancel_speech(operation=self._operation(correlation), playback=evidence))

    def admit_transcript(self, provider_item_id: str | None, *, source_correlation_id: str | None = None) -> None:
        event = self._pending_users.pop(str(provider_item_id), None)
        if event is not None and self._dispatcher is not None:
            self._admitted_items[str(provider_item_id)] = event
            while len(self._admitted_items) > 128:
                self._admitted_items.popitem(last=False)
            opened = self._pending_open.pop(str(provider_item_id), None)
            if opened is not None:
                previous = opened.correlation.previous_provider_input_id
                visited = set()
                while previous in self._input_order and self._input_order[previous][1] == "rejected":
                    if previous in visited:
                        raise RuntimeError("voice_input_order_cycle")
                    visited.add(previous)
                    previous = self._input_order[previous][0]
                turn = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.session_id}/input/{previous}")) if previous else None
                opened = replace(opened, payload=replace(opened.payload, previous_turn_id=turn))
                self._dispatcher.observe(opened)
            self._dispatcher.observe(event)
            if source_correlation_id and event.correlation.turn_id:
                self._source_turns[source_correlation_id] = event.correlation.turn_id
                while len(self._source_turns) > 128:
                    self._source_turns.popitem(last=False)
            original = self._input_order.get(str(provider_item_id), (None, "pending"))[0]
            self._input_order[str(provider_item_id)] = (original, "admitted")

    def discard_transcript(self, provider_item_id: str | None) -> None:
        if self.analysis is not None and provider_item_id is not None and str(provider_item_id) not in self._admitted_items:
            self.analysis.reject_item(str(provider_item_id), "application_rejected")
        self._pending_users.pop(str(provider_item_id), None)
        self._pending_open.pop(str(provider_item_id), None)
        key = str(provider_item_id)
        if key in self._input_order and self._input_order[key][1] != "admitted":
            previous = self._input_order[key][0]
            visited = {key}
            while previous in self._input_order and self._input_order[previous][1] == "rejected":
                if previous in visited:
                    raise RuntimeError("voice_input_order_cycle")
                visited.add(previous)
                previous = self._input_order[previous][0]
            # Compress rejected ancestry, so a long ambient run cannot hide the
            # last admitted/pending predecessor when old buffer entries expire.
            self._input_order[key] = (previous, "rejected")

    def observe_playback(self, payload: dict, *, played_ms: int | None, written_ms: int | None, terminal: bool = False) -> None:
        if self._dispatcher is None:
            return
        correlation = self._outputs.get(str(payload.get("output_id")))
        if correlation is None:
            return
        if played_ms is not None and played_ms > 0:
            status = VoicePlaybackStatus.UNKNOWN if terminal else VoicePlaybackStatus.PARTIAL
        elif written_ms == 0:
            status, played_ms = VoicePlaybackStatus.UNPLAYED, 0
        else:
            status = VoicePlaybackStatus.UNKNOWN
        # Cached PortAudio latency gives only a lower bound. No word or complete
        # delivery claim until Task07 establishes an actual drain/epoch boundary.
        self._dispatcher.local(AssistantPlaybackEvidence(status, played_ms), correlation)

    def playback_manifest(self, payload: dict) -> VoicePlaybackManifest | None:
        return self._playback_manifests.freeze(self.session_id, str(payload.get("output_id")), str(payload.get("response_id")))

    def observe_device_completion(self, manifest: VoicePlaybackManifest, proof: VoiceDevicePlaybackProof) -> bool:
        evidence = self._playback_manifests.complete(manifest, proof)
        correlation = self._outputs.get(manifest.output_id)
        if evidence is None or correlation is None or self._dispatcher is None or self._closed:
            return False
        self._dispatcher.local(evidence, correlation)
        self._remember_heard_references(manifest, correlation)
        if self.analysis is not None and evidence.confirmed_text:
            self.analysis.remember_context(VoiceContextMessage(VoiceContextRole.ASSISTANT, evidence.confirmed_text))
        return True

    def _remember_conversation_reference(self, item_id: str, epoch: int) -> None:
        self._conversation_references[item_id] = epoch
        while len(self._conversation_references) > 16:
            self._conversation_references.popitem(last=False)

    def _remember_heard_references(self, manifest, correlation) -> None:
        source = next((source for source in self._conversation_sources.values() if source.correlation_id == correlation.source_correlation_id), None)
        if source is not None and manifest is not None:
            for extent in manifest.parts:
                self._remember_conversation_reference(extent.part.item_id, source.intent_epoch)

    def _observe(self, event) -> None:
        if self._back_brain is not None:
            self._back_brain.observe(event)
        if self.analysis is not None:
            self.analysis.observe(event)
        if isinstance(event.payload, VoiceUsageUpdated) and self.journal is not None:
            self.journal.emit("voice.realtime.usage", "Realtime session usage updated", data={
                "conversation_id": self.conversation_id,
                "session_id": self.session_id,
                "input_tokens": event.payload.input_tokens,
                "output_tokens": event.payload.output_tokens,
                "duration_seconds": event.payload.duration_s,
                "source": event.payload.source.value,
            })
        if isinstance(event.payload, VoiceFrontendFailed):
            self._playback_manifests.invalidate()
        completion = self._playback_manifests.observe(event)
        if event.correlation.output_id:
            self._outputs[event.correlation.output_id] = event.correlation
            while len(self._outputs) > 128:
                self._outputs.popitem(last=False)
        if isinstance(event.payload, UserTranscriptCommitted):
            if len(self._pending_users) >= 128:
                raise RuntimeError("voice_user_admission_overflow")
            self._pending_users[str(event.correlation.provider_input_id)] = event
        elif isinstance(event.payload, UserTurnOpened):
            key = str(event.correlation.provider_input_id)
            previous = event.correlation.previous_provider_input_id
            if previous is not None and previous not in self._input_order:
                # OpenAI donne le dernier élément de la conversation, le plus
                # souvent la réponse de l'assistant : ce n'est pas une entrée.
                # L'entrée qui précède est alors la dernière observée ; sans
                # cela le tour pointe vers un parent que Core ne connaîtra
                # jamais et toute la suite de la session reste sans réponse.
                previous = next((item for item in reversed(self._input_order) if item != key), None)
                event = replace(event, correlation=replace(event.correlation, previous_provider_input_id=previous))
            self._pending_open[key] = event
            self._input_order[key] = (previous, "pending")
            while len(self._input_order) > 256:
                self._input_order.popitem(last=False)
            while len(self._pending_open) > 128:
                self._pending_open.popitem(last=False)  # Unadmitted segments carry no accepted intent.
        elif isinstance(event.payload, (UserTranscriptDelta, UserSpeechActivity)):
            pass  # Existing owner/address gate owns admission; speculative Core access is Task10.
        elif self._dispatcher is not None:
            self._dispatcher.observe(event)
        if completion is not None and self._dispatcher is not None:
            self._dispatcher.local(completion, event.correlation)
            manifest = self._playback_manifests.freeze(self.session_id, str(event.correlation.output_id), str(event.correlation.provider_output_id))
            self._remember_heard_references(manifest, event.correlation)
            if self.analysis is not None and completion.confirmed_text:
                self.analysis.remember_context(VoiceContextMessage(VoiceContextRole.ASSISTANT, completion.confirmed_text))

    async def events(self):
        self._reading = True
        self._reader_ended.clear()
        try:
            async for event in self.frontend.events():
                self._observe(event)
                converted = self._legacy_event(event)
                if converted is not None:
                    yield converted
        finally:
            self._reading = False
            self._reader_ended.set()

    @staticmethod
    def _legacy_event(event):
        correlation, payload = event.correlation, event.payload
        fields = {"output_id": correlation.output_id, "speech_id": correlation.speech_id,
                  "response_id": correlation.provider_output_id, "item_id": correlation.provider_item_id,
                  "provider_event_id": event.provider_event_id}
        part = getattr(payload, "part", None)
        fields["content_index"] = part.content_index if part is not None else None
        fields["output_index"] = part.output_index if part is not None else None
        if part is not None:
            fields["item_id"] = part.item_id
        kind = None
        if isinstance(payload, AssistantAudioChunk):
            kind, fields["pcm_b64"] = "realtime.audio", base64.b64encode(payload.audio.pcm).decode("ascii")
        elif isinstance(payload, AssistantGenerationStarted):
            kind = "realtime.output_started"
        elif isinstance(payload, AssistantGenerationFinished):
            kind, fields["status"] = "realtime.response_done", payload.status.value
        elif isinstance(payload, AssistantAudioPartCompleted):
            kind = "realtime.audio_done"
        elif isinstance(payload, (AssistantTranscriptCompleted, AssistantTranscriptDelta)):
            kind = "realtime.assistant_transcript" if isinstance(payload, AssistantTranscriptCompleted) else "realtime.assistant_transcript_delta"
            fields["text"] = payload.text if isinstance(payload, AssistantTranscriptCompleted) else payload.delta
        elif isinstance(payload, (UserTranscriptCommitted, UserTranscriptDelta)):
            kind = "realtime.transcript" if isinstance(payload, UserTranscriptCommitted) else "realtime.transcript_delta"
            fields = {"text": payload.text if isinstance(payload, UserTranscriptCommitted) else payload.delta,
                      "item_id": correlation.provider_input_id}
        elif isinstance(payload, UserTurnOpened):
            kind, fields = "realtime.input_committed", {"item_id": correlation.provider_input_id}
        elif isinstance(payload, UserSpeechActivity):
            kind = "realtime.speech_started" if payload.phase is VoiceSpeechPhase.STARTED else "realtime.speech_stopped"
            fields = {"item_id": correlation.provider_input_id}
        elif isinstance(payload, VoiceToolCallRequested):
            kind, fields = "realtime.tool_call", {"call_id": payload.call_id, "name": payload.name, "arguments": json.loads(payload.arguments_json)}
        elif isinstance(payload, VoiceFrontendFailed):
            kind, fields = "realtime.error", {"error": {"code": payload.error.provider_code or payload.error.code.value,
                                                        "message": payload.error.safe_message or payload.error.code.value}}
        return ProtocolEnvelope(message_type=kind, payload=fields) if kind else None

    async def close(self) -> None:
        if self._closed:
            return
        if self._close_task is None or self._close_task.done():
            self._close_task = asyncio.create_task(self._close())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await asyncio.shield(self._close_task)
            raise

    async def _close(self) -> None:
        if self._back_brain is not None:
            await self._back_brain.close()
        if self.analysis is not None:
            await self.analysis.close()
        self._playback_manifests.invalidate()
        result = await self.frontend.stop(VoiceStopReason.USER, operation=self._operation())
        if self._reading:
            await asyncio.wait_for(self._reader_ended.wait(), 2.0)
        # Bridge cancellation may have released the subscription before stop.
        # Drain only remaining evidence; audio is never played during cleanup.
        self._require(result)
        try:
            async for event in self.frontend.events():
                self._observe(event)
            if self._dispatcher is not None:
                await self._dispatcher.close()
        except Exception:
            if self._dispatcher is None:
                raise
            await self._dispatcher.reconcile_closed()
        self._closed = True
