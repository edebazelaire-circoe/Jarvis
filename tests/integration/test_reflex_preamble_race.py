"""Synthetic interleavings through real frontend, bridge/device writer and Core ledger.

No hardware drain or real provider quality claim: only transport/native stream
edges are controlled. Source fixture text is scenario data, not provider facts.
"""
from __future__ import annotations

import asyncio
import base64
import threading
from unittest.mock import AsyncMock

import pytest

from jarvis.adapters.openai_realtime import OUTPUT_ID_METADATA_KEY
from jarvis.domain.v2 import ProtocolEnvelope, SpeechRequest
from jarvis.runtime.output_admission import OutputAdmissionState
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from tests.fakes.speech_context import source, context
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.unit.test_realtime_frontend_pipeline import pipeline, until
from tests.unit.test_voice_duplex import EmptyCore, RecordingJournal


class DeviceStream:
    latency = 0
    def __init__(self):
        self.writes = []
        self.entered = threading.Event()
        self.release = None
    def write(self, block):
        self.entered.set()
        if self.release is not None:
            assert self.release.wait(2), "test native write was not released"
        self.writes.append(block)


async def rig(pipeline, *, declared_work=True):
    facade, wire, client, conversation, events, history = pipeline
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=conversation, session=facade,
                                journal=RecordingJournal(), reflex_delay_s=.01)
    scheduler.update_speech_context(context(conversation, "request"))
    scheduler._running = True
    if declared_work:
        await scheduler.handle_core_event(ProtocolEnvelope(message_type="brain.work.started", payload={
            "conversation_id": conversation, "correlation_id": "request", "work_id": "work"}))
    audio = SoundDeviceRealtimeAudio()
    audio._output = DeviceStream()
    bridge = RealtimeConversationBridge(core=client, session=facade, conversation_id=conversation, audio=audio,
        continuous=True, on_addressed=lambda: None, on_mute=lambda: None, output_admission=scheduler.output_admission)
    return scheduler, audio, bridge


def request(scheduler, *, expires_in=1):
    scheduler.request_reflex("Peux-tu comparer les prix entre les deux architectures ?", correlation_id="request")
    now = asyncio.get_running_loop().time()
    scheduler._reflex.due = now - .001
    scheduler._reflex.expires = now + expires_in


def emit_response(wire, output_id, *, response_id="preamble"):
    wire.push(type="response.created", response={"id": response_id, "metadata": {OUTPUT_ID_METADATA_KEY: output_id}})
    wire.push(type="response.output_audio.delta", response_id=response_id, item_id="audio", delta=base64.b64encode(bytes(960)).decode())
    wire.push(type="response.output_audio_transcript.done", response_id=response_id, item_id="audio", transcript="Je prends un instant pour examiner cela.")


async def wait_condition(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(.001)


@pytest.mark.parametrize("answer_correlation", ["request", "another-request"])
async def test_useful_result_during_response_create_invalidates_before_any_pcm(pipeline, answer_correlation):
    facade, wire, client, conversation, events, history = pipeline
    scheduler, audio, bridge = await rig(pipeline)
    entered, release = asyncio.Event(), asyncio.Event()
    original = wire.send_json
    async def send(payload):
        await original(payload)
        if payload["type"] == "response.create":
            entered.set()
            await release.wait()
    wire.send_json = send
    request(scheduler)
    launch = asyncio.create_task(scheduler._maybe_speak_reflex())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        reserved = wire.sent[-1]["response"]["metadata"][OUTPUT_ID_METADATA_KEY]
        emit_response(wire, reserved)
        audio_event = await until(events, "realtime.audio")
        await until(events, "realtime.assistant_transcript")
        scheduler._enqueue(SpeechRequest(conversation, "The useful answer", correlation_id=answer_correlation, source=source(answer_correlation)))
        scheduler._invalidate_reflex("repeated_signal")
        scheduler.note_user_speech(True)
        release.set()
        await launch
        await bridge._play_audio(1, audio_event)
        await wait_condition(lambda: any(item["type"] == "response.cancel" for item in wire.sent))
        assert [item for item in wire.sent if item["type"] == "response.cancel"] == [{"type": "response.cancel", "response_id": "preamble"}]
        assert audio._output.writes == []
        await facade._dispatcher.flush()
        speech = (await client.voice_snapshot(conversation))["snapshot"]["speeches"][0]
        assert speech["generated"][0]["text"] and speech["played_ms"] == 0 and speech["confirmed_text"] is None
        assert not await history.read(conversation_id=conversation)
    finally:
        release.set()
        await asyncio.gather(launch, return_exceptions=True)
        await scheduler.stop()


async def test_result_while_device_lock_is_held_blocks_first_native_write(pipeline):
    facade, wire, client, conversation, events, _ = pipeline
    scheduler, audio, bridge = await rig(pipeline)
    bridge._note_first_audio = AsyncMock()
    bridge.on_speaking = AsyncMock()
    request(scheduler)
    await scheduler._maybe_speak_reflex()
    output = scheduler._live_reflex.output_id
    emit_response(wire, output)
    audio_event = await until(events, "realtime.audio")
    audio._output_lock.acquire()
    playing = asyncio.create_task(bridge._play_audio(1, audio_event))
    try:
        await asyncio.sleep(.01)  # Worker is waiting on the existing device lock.
        assert scheduler.output_admission(output).state is OutputAdmissionState.RESERVED
        scheduler._enqueue(SpeechRequest(conversation, "Useful answer", correlation_id="request", source=source("request")))
    finally:
        audio._output_lock.release()
    await playing
    assert audio._output.writes == [] and audio.written_output_ms == 0
    bridge._note_first_audio.assert_not_awaited()
    bridge.on_speaking.assert_not_awaited()
    await scheduler.stop()


async def test_result_after_native_write_started_does_not_rewrite_it_as_unplayed(pipeline):
    facade, wire, client, conversation, events, _ = pipeline
    scheduler, audio, bridge = await rig(pipeline)
    request(scheduler)
    await scheduler._maybe_speak_reflex()
    output = scheduler._live_reflex.output_id
    emit_response(wire, output)
    audio_event = await until(events, "realtime.audio")
    audio._output.release = threading.Event()
    playing = asyncio.create_task(bridge._play_audio(1, audio_event))
    try:
        assert await asyncio.to_thread(audio._output.entered.wait, 1)
        assert scheduler.output_admission(output).state is OutputAdmissionState.WRITE_STARTED
        scheduler._enqueue(SpeechRequest(conversation, "Useful answer", correlation_id="request", source=source("request")))
        assert scheduler.output_admission(output).state is OutputAdmissionState.WRITE_STARTED
    finally:
        audio._output.release.set()
    await playing
    assert audio._output.writes and scheduler.output_admission(output).state is OutputAdmissionState.WRITTEN
    assert not any(item["type"] == "response.cancel" for item in wire.sent)
    await scheduler.stop()


async def test_expiry_during_start_without_any_new_turn_blocks_late_pcm(pipeline):
    facade, wire, client, conversation, events, _ = pipeline
    scheduler, audio, bridge = await rig(pipeline)
    entered, release = asyncio.Event(), asyncio.Event()
    original = wire.send_json
    async def send(payload):
        await original(payload)
        if payload["type"] == "response.create":
            entered.set()
            await release.wait()
    wire.send_json = send
    request(scheduler, expires_in=.03)
    launch = asyncio.create_task(scheduler._maybe_speak_reflex())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        output = scheduler._live_reflex.output_id
        await wait_condition(lambda: scheduler.output_admission(output).state is OutputAdmissionState.INVALIDATED)
        release.set()
        await launch
        emit_response(wire, output)
        audio_event = await until(events, "realtime.audio")
        await bridge._play_audio(1, audio_event)
        assert audio._output.writes == []
    finally:
        release.set()
        await asyncio.gather(launch, return_exceptions=True)
        await scheduler.stop()


async def test_blocked_exact_cancel_does_not_block_reader_or_cancel_new_response(pipeline):
    facade, wire, client, conversation, events, _ = pipeline
    scheduler, audio, bridge = await rig(pipeline)
    request(scheduler)
    await scheduler._maybe_speak_reflex()
    output = scheduler._live_reflex.output_id
    emit_response(wire, output)
    await until(events, "realtime.audio")
    cancel_entered, cancel_release = asyncio.Event(), asyncio.Event()
    original = wire.send_json
    async def send(payload):
        await original(payload)
        if payload["type"] == "response.cancel":
            cancel_entered.set()
            await cancel_release.wait()
    wire.send_json = send
    try:
        await facade.invalidate_reflex(output)
        await asyncio.wait_for(cancel_entered.wait(), 1)
        await facade.invalidate_reflex(output)
        wire.push(type="response.created", response={"id": "preamble", "metadata": {OUTPUT_ID_METADATA_KEY: output}})
        wire.push(type="response.done", response={"id": "preamble", "status": "cancelled"})
        wire.push(type="response.created", response={"id": "useful-response"})
        wire.push(type="conversation.item.input_audio_transcription.completed", item_id="user", transcript="new input")
        assert (await until(events, "realtime.transcript")).payload["text"] == "new input"
        assert [item for item in wire.sent if item["type"] == "response.cancel"] == [{"type": "response.cancel", "response_id": "preamble"}]
        await asyncio.wait_for(facade.close(), 1)
        assert wire.closed
    finally:
        cancel_release.set()
        await scheduler.stop()


async def test_a_silent_brain_reaches_the_speaker_without_any_declared_work(pipeline):
    """Le chemin complet, decide -> emis -> joue, sans `brain.work.started`.

    Ce que ce test prouve, et qu'un test de politique ne peut pas prouver : la
    decision PREAMBLE traverse la facade, le frontend canonique et l'unique
    lecteur de fil jusqu'a un `response.create` audio, puis le PCM rendu est
    reellement ecrit sur le peripherique. Le reflexe avait deja ete decide sans
    jamais etre emis ; c'est cette moitie-la du chemin que l'on verrouille ici.
    """
    facade, wire, client, conversation, events, _ = pipeline
    scheduler, audio, bridge = await rig(pipeline, declared_work=False)
    request(scheduler)

    await scheduler._maybe_speak_reflex()

    output = scheduler._live_reflex.output_id
    created = [item for item in wire.sent if item["type"] == "response.create"]
    assert len(created) == 1, "un seul preambule, et il part vraiment sur le fil"
    assert created[0]["response"]["output_modalities"] == ["audio"]
    assert created[0]["response"]["metadata"][OUTPUT_ID_METADATA_KEY] == output
    assert scheduler._reflex_decisions["request"].reason == "brain_silent_wait"

    emit_response(wire, output)
    audio_event = await until(events, "realtime.audio")
    await bridge._play_audio(1, audio_event)

    assert audio._output.writes, "le preambule doit atteindre le peripherique de sortie"
    assert scheduler.output_admission(output).state is OutputAdmissionState.WRITTEN
    assert not any(item["type"] == "response.cancel" for item in wire.sent)
    await scheduler.stop()


async def test_an_undeclared_preamble_is_still_dropped_when_the_answer_is_ready(pipeline):
    """Relacher la porte ne doit pas laisser le reflexe doubler le cerveau."""
    facade, wire, client, conversation, events, _ = pipeline
    scheduler, audio, bridge = await rig(pipeline, declared_work=False)
    scheduler._enqueue(SpeechRequest(conversation, "La reponse du cerveau", correlation_id="request",
                                     source=source("request")))
    scheduler.request_reflex("Peux-tu comparer les prix entre les deux architectures ?", correlation_id="request")

    assert scheduler._reflex is None

    await scheduler._maybe_speak_reflex()

    assert not any(item["type"] == "response.create" for item in wire.sent)
    assert audio._output.writes == []
    await scheduler.stop()
