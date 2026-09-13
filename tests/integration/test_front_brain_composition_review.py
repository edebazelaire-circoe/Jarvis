"""Independent Task10 QA across direct-conversation composition boundaries.

Provider calls, native audio and the optional analyzer are controlled. The
bridge, scheduler, sidecar, OpenAI request encoder and playback join are real.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
from jarvis.domain.front_brain_hints import (
    FrontBrainHintResult,
    FrontBrainHintValue,
    HintAnalysisStatus,
)
from jarvis.domain.reflex_policy import ReflexAction
from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.domain.voice_events import (
    AssistantAudioChunk,
    AssistantAudioPartCompleted,
    AssistantGenerationFinished,
    AssistantTranscriptCompleted,
    UserCommitSource,
    UserTranscriptCommitted,
    UserTranscriptDelta,
    VoiceEvent,
    VoiceGenerationStatus,
)
from jarvis.domain.voice_frontend import (
    VoiceAudioChunk,
    VoiceContext,
    VoiceCorrelation,
    VoiceObservation,
)
from jarvis.domain.voice_playback import VoiceAudioPart, VoiceDevicePlaybackStatus
from jarvis.runtime.front_brain_sidecar import FrontBrainSidecar, FrontBrainSidecarConfig
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.runtime.voice_playback_manifest import VoicePlaybackManifests
from tests.fakes.audio_device import BufferedOutputStream
from tests.fakes.speech_context import context, source


CONVERSATION = "conversation-1"
SESSION = "session"


async def until(predicate, timeout: float = 2) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.001)


class CoreBoundary:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.backend_submissions = 0

    async def events(self, *, on_connected=None):
        if on_connected is not None:
            result = on_connected()
            if hasattr(result, "__await__"):
                await result
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def speech_context(self, conversation_id):
        return context(conversation_id)

    async def submit_brain_turn(self, *args, **kwargs):
        self.backend_submissions += 1
        raise AssertionError("direct conversation must not submit a strong-backend turn")


class DirectSessionBoundary:
    canonical_history = True

    def __init__(self, admission_source: SpeechSource, *, analysis=None, request_gate=None) -> None:
        self.source = admission_source
        self.analysis = analysis
        self.request_gate = request_gate
        self.requests: list[tuple[tuple[str, ...], SpeechSource, str]] = []
        self.invalidated: list[str] = []
        self.discarded: list[str | None] = []
        self.active_output_id: str | None = None

    async def admit_conversation(self, core, conversation_id, provider_item_id, *, addressing):
        del core, conversation_id, addressing
        if self.analysis is not None:
            self.analysis.admit_item(provider_item_id, self.source)
        return SimpleNamespace(source=self.source)

    async def request_conversation(self, input_item_ids, *, source, output_id):
        self.requests.append((input_item_ids, source, output_id))
        self.active_output_id = output_id
        if self.request_gate is not None:
            await self.request_gate.wait()
        return output_id

    async def invalidate_unstarted_output(self, output_id):
        self.invalidated.append(output_id)
        if self.active_output_id == output_id:
            self.active_output_id = None

    def discard_transcript(self, item_id):
        self.discarded.append(item_id)


class Diagnostics:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def emit(self, channel, message, *, data=None, **kwargs):
        del message, kwargs
        self.records.append((channel, data or {}))


class ControlledAnalyzer:
    def __init__(self, *, resist_cancellation=False) -> None:
        self.requests = []
        self.gates: list[asyncio.Event] = []
        self.cancelled = 0
        self.resist_cancellation = resist_cancellation

    async def analyze(self, request):
        self.requests.append(request)
        gate = asyncio.Event()
        self.gates.append(gate)
        while not gate.is_set():
            try:
                await gate.wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                if not self.resist_cancellation:
                    raise
        return FrontBrainHintResult(
            request.request_id,
            HintAnalysisStatus.AVAILABLE,
            FrontBrainHintValue(suggested_action=ReflexAction.DELEGATE),
            max(0, request.deadline_monotonic_ns - 1),
        )


def hint_event(*, item="input", revision=1, text="Jarvis", final=False, session=SESSION):
    payload = (
        UserTranscriptCommitted("transcript-" + item, text, revision, UserCommitSource.PROVIDER)
        if final
        else UserTranscriptDelta("transcript-" + item, text, revision)
    )
    return VoiceEvent(
        f"event-{item}-{revision}",
        revision,
        VoiceCorrelation(session, turn_id="turn-" + item, provider_input_id=item),
        VoiceObservation(datetime.now(timezone.utc), 1),
        payload,
    )


def make_sidecar(analyzer, diagnostics=None):
    worker = FrontBrainSidecar(
        analyzer,
        session_id=SESSION,
        configuration_id="config",
        config=FrontBrainSidecarConfig(debounce_s=0, min_interval_s=0, deadline_s=5),
        diagnostics=diagnostics,
    )
    worker.update_context(context=VoiceContext(), source=None, source_complete=True)
    worker.start()
    return worker


async def direct_harness(*, analysis=None, request_gate=None):
    core = CoreBoundary()
    current = source()
    session = DirectSessionBoundary(current, analysis=analysis, request_gate=request_gate)
    scheduler = SpeechScheduler(core=core, conversation_id=CONVERSATION, session=session,
                                reconnect_delay_s=.01, output_timeout_s=.1)
    scheduler.update_speech_context(context(CONVERSATION))
    bridge = RealtimeConversationBridge(
        core=core,
        session=session,
        conversation_id=CONVERSATION,
        audio=SimpleNamespace(),
        on_addressed=lambda: None,
        on_mute=lambda: None,
        continuous=True,
        direct_conversation=True,
        on_conversation=scheduler.request_conversation,
        output_admission=scheduler.output_admission,
    )
    await scheduler.start()
    await until(lambda: scheduler.presentation_snapshot()["source_complete"])
    return core, session, scheduler, bridge


@pytest.mark.asyncio
async def test_simple_admitted_turn_requests_direct_response_without_backend_or_luna():
    core, session, scheduler, bridge = await direct_harness()
    try:
        await bridge._handle_transcript(ProtocolEnvelope(
            "realtime.transcript", {"item_id": "input", "text": "Jarvis, réponds directement."}
        ))
        await until(lambda: len(session.requests) == 1)
        assert session.requests[0][0] == ("input",)
        assert core.backend_submissions == 0 and session.analysis is None
        assert session.discarded == ["input"]
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_front_brain_direct_response_does_not_wait_for_blocked_luna():
    analyzer = ControlledAnalyzer()
    sidecar = make_sidecar(analyzer)
    sidecar.allow_item("input", "permission")
    sidecar.observe(hint_event())
    await until(lambda: len(analyzer.requests) == 1)
    core, session, scheduler, bridge = await direct_harness(analysis=sidecar)
    try:
        await bridge._handle_transcript(ProtocolEnvelope(
            "realtime.transcript", {"item_id": "input", "text": "Jarvis, quelle heure est-il ?"}
        ))
        await until(lambda: len(session.requests) == 1)
        assert not analyzer.gates[0].is_set()
        assert core.backend_submissions == 0
    finally:
        await scheduler.stop()
        for gate in analyzer.gates:
            gate.set()
        await sidecar.close()


@pytest.mark.asyncio
async def test_unknown_or_rejected_inputs_make_zero_luna_calls():
    analyzer = ControlledAnalyzer()
    sidecar = make_sidecar(analyzer)
    try:
        sidecar.allow_item("unknown", "permission")
        sidecar.observe(hint_event(item="unknown", session="old-session"))
        sidecar.reject_item("rejected", "owner_unverified")
        sidecar.allow_item("rejected", "late-permission")
        sidecar.observe(hint_event(item="rejected"))
        await asyncio.sleep(.02)
        assert analyzer.requests == []
    finally:
        await sidecar.close()


@pytest.mark.asyncio
async def test_rejected_partial_late_result_is_unusable_and_final_replaces_partial():
    analyzer = ControlledAnalyzer(resist_cancellation=True)
    diagnostics = Diagnostics()
    sidecar = make_sidecar(analyzer, diagnostics)
    try:
        sidecar.allow_item("rejected", "permission-r")
        sidecar.observe(hint_event(item="rejected"))
        await until(lambda: len(analyzer.requests) == 1)
        rejected_request = analyzer.requests[0].request_id
        sidecar.reject_item("rejected", "owner_unverified")
        await until(lambda: analyzer.cancelled == 1)
        analyzer.gates[0].set()
        await until(lambda: not sidecar._flight)
        assert not [data for channel, data in diagnostics.records
                    if channel == "voice.hint.consumed" and data.get("request_id") == rejected_request]

        sidecar.allow_item("accepted", "permission-a")
        sidecar.observe(hint_event(item="accepted"))
        await until(lambda: len(analyzer.requests) == 2)
        partial_request = analyzer.requests[1].request_id
        sidecar.observe(hint_event(item="accepted", revision=2, text="Jarvis final", final=True))
        sidecar.admit_item("accepted", source())
        await until(lambda: analyzer.cancelled == 2)
        analyzer.gates[1].set()
        await until(lambda: not sidecar._flight)
        # Core admission returns an origin, but the final hint must wait until
        # the authoritative source projection catches up to that exact source.
        assert len(analyzer.requests) == 2
        sidecar.update_source(source=source(), source_complete=True)
        await until(lambda: len(analyzer.requests) == 3)
        assert analyzer.requests[2].input.committed
        assert analyzer.requests[2].request_id != partial_request
        analyzer.gates[2].set()
        await until(lambda: any(channel == "voice.hint.consumed" for channel, _ in diagnostics.records))
        assert [data["request_id"] for channel, data in diagnostics.records if channel == "voice.hint.consumed"] == [analyzer.requests[2].request_id]
    finally:
        for gate in analyzer.gates:
            gate.set()
        await sidecar.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("retire", ["new_source", "stop"])
async def test_source_change_or_stop_while_provider_awaits_blocks_first_native_write(retire):
    gate = asyncio.Event()
    core, session, scheduler, bridge = await direct_harness(request_gate=gate)
    del bridge
    try:
        assert scheduler.request_conversation(input_item_ids=("input",), source=source())
        await until(lambda: len(session.requests) == 1)
        output_id = session.requests[0][2]
        admission = scheduler.output_admission(output_id)
        assert admission is not None
        if retire == "new_source":
            scheduler.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
            await until(lambda: output_id in session.invalidated)
        else:
            await scheduler.stop()

        audio = SoundDeviceRealtimeAudio()
        stream = BufferedOutputStream()
        audio._output = stream
        wrote = await audio.play_b64_guarded(base64.b64encode(b"\x01\x00" * 240).decode(), admission)
        assert not wrote and stream.writes == []
        gate.set()
    finally:
        gate.set()
        await scheduler.stop()


@pytest.mark.asyncio
async def test_openai_direct_request_is_exact_item_reference_in_default_conversation():
    class Wire:
        def __init__(self):
            self.sent = []
        async def send_json(self, value):
            self.sent.append(value)

    wire = Wire()
    session = OpenAIRealtimeSession(wire, SimpleNamespace(), owns_http=False)
    returned = await session.request_conversation(("provider-item-a", "provider-item-b"), output_id="local-output")
    assert returned == "local-output"
    assert wire.sent == [{"type": "response.create", "response": {
        "input": [
            {"type": "item_reference", "id": "provider-item-a"},
            {"type": "item_reference", "id": "provider-item-b"},
        ],
        "output_modalities": ["audio"],
        "metadata": {"jarvis_output_id": "local-output"},
    }}]
    assert "conversation" not in wire.sent[0]["response"]


@pytest.mark.asyncio
async def test_multipart_complete_requires_exact_checked_device_proof():
    parts = (VoiceAudioPart("part-a", 0, 0), VoiceAudioPart("part-b", 0, 1))
    pcm = (b"\x01\x00" * 240, b"\x02\x00" * 120)
    correlation = VoiceCorrelation(SESSION, output_id="output", provider_output_id="response")
    ledger = VoicePlaybackManifests()
    for index, part in enumerate(parts):
        ledger.observe(SimpleNamespace(correlation=correlation, payload=AssistantAudioChunk(VoiceAudioChunk(pcm[index]), part)))
        ledger.observe(SimpleNamespace(correlation=correlation, payload=AssistantTranscriptCompleted(f"transcript-{index}", f"text-{index}", part)))
        ledger.observe(SimpleNamespace(correlation=correlation, payload=AssistantAudioPartCompleted(part)))
    evidence = ledger.observe(SimpleNamespace(correlation=correlation, payload=AssistantGenerationFinished(
        VoiceGenerationStatus.COMPLETED, parts, ("text-0", "text-1")
    )))
    assert evidence is None
    manifest = ledger.freeze(SESSION, "output", "response")
    assert manifest is not None

    audio = SoundDeviceRealtimeAudio()
    stream = BufferedOutputStream()
    audio._output = stream
    try:
        for part, block in zip(parts, pcm):
            audio.set_active_output(output_id="output", response_id="response", item_id=part.item_id,
                                    content_index=part.content_index, output_index=part.output_index)
            await audio.play_b64(base64.b64encode(block).decode())
        drain = asyncio.create_task(audio.complete_output(manifest))
        await until(stream.draining.is_set)
        stream.consume()
        proof = await drain
        assert proof.status is VoiceDevicePlaybackStatus.COMPLETE
        complete = ledger.complete(manifest, proof)
        assert complete is not None and complete.status.value == "complete"
        assert complete.confirmed_text == "text-0text-1"
    finally:
        stream.consume()
        await audio.close()


@pytest.mark.asyncio
async def test_sidecar_shutdown_does_not_cancel_independent_job():
    analyzer = ControlledAnalyzer()
    sidecar = make_sidecar(analyzer)
    job_gate = asyncio.Event()
    job = asyncio.create_task(job_gate.wait(), name="independent-core-job")
    sidecar.allow_item("input", "permission")
    sidecar.observe(hint_event())
    await until(lambda: len(analyzer.requests) == 1)
    try:
        await sidecar.close()
        assert not job.done() and not job.cancelled()
    finally:
        job_gate.set()
        await job
