"""Actual canonical facade/transport/device writer with controlled race barriers."""
import asyncio
import base64

import pytest

from jarvis.adapters.openai_realtime import OUTPUT_ID_METADATA_KEY, SPEECH_ID_METADATA_KEY
from jarvis.domain.speech_presentation import SpeechDependency
from jarvis.domain.v2 import SpeechKind, SpeechRequest
from jarvis.runtime.output_admission import OutputAdmissionState
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.fakes.audio_device import BufferedOutputStream
from tests.fakes.speech_context import context, source
from tests.unit.test_realtime_frontend_pipeline import pipeline, until
from tests.unit.test_voice_duplex import EmptyCore, RecordingJournal


async def wait_for(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.001)


def setup(pipeline):
    facade, wire, client, conversation, events, history = pipeline
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=conversation, session=facade,
                                journal=RecordingJournal(), output_timeout_s=.03)
    scheduler.update_speech_context(context(conversation, "origin"))
    scheduler._running = True
    request = SpeechRequest(conversation, "Exact useful answer", kind=SpeechKind.RESULT,
                            correlation_id="origin", source=source("origin", work_id="retired-work"),
                            outcome_id="retained-outcome")
    scheduler._enqueue(request)
    assert scheduler._pop_next() == request
    audio = SoundDeviceRealtimeAudio()
    audio._output = BufferedOutputStream()
    bridge = RealtimeConversationBridge(core=client, session=facade, conversation_id=conversation, audio=audio,
        continuous=True, on_addressed=lambda: None, on_mute=lambda: None,
        output_admission=scheduler.output_admission, on_output_event=scheduler.note_output_event)
    return scheduler, request, audio, bridge


def emit_audio(wire, output, speech):
    wire.push(type="response.created", response={"id": "old-response", "metadata": {
        OUTPUT_ID_METADATA_KEY: output, SPEECH_ID_METADATA_KEY: speech}})
    wire.push(type="response.output_audio.delta", response_id="old-response", item_id="audio",
              content_index=0, output_index=0, delta=base64.b64encode(bytes(960)).decode())
    wire.push(type="response.output_audio_transcript.done", response_id="old-response", item_id="audio",
              content_index=0, output_index=0, transcript="Exact useful answer")


async def retire(wire, scheduler, events):
    wire.push(type="response.done", response={"id": "old-response", "status": "cancelled"})
    done = await until(events, "realtime.response_done")
    await scheduler.note_output_event(done)


@pytest.mark.parametrize("barrier", ["core_registration", "provider_create", "device_lock"])
async def test_a_result_the_brain_retires_before_the_first_write_never_becomes_heard(pipeline, barrier):
    """Depuis le 19/09/2026, une intention neuve ne suffit plus à retirer une
    réponse durable : elle est reportée et dite. Ce qui la retire encore, et
    qui est mesuré ici, c'est la désignation explicite du cerveau
    (`dependency_revoked`) — le seul retrait que la doctrine reconnaisse
    (Décision 35)."""

    facade, wire, client, conversation, events, history = pipeline
    scheduler, request, audio, bridge = setup(pipeline)
    entered, release = asyncio.Event(), asyncio.Event()
    if barrier == "core_registration":
        original = client.register_voice_speech
        async def register(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result
        client.register_voice_speech = register
    elif barrier == "provider_create":
        original = wire.send_json
        async def send(payload):
            await original(payload)
            if payload["type"] == "response.create":
                entered.set()
                await release.wait()
        wire.send_json = send
    launch = asyncio.create_task(scheduler._speak(request))
    playing = None
    locked = False
    try:
        if barrier != "device_lock":
            await asyncio.wait_for(entered.wait(), 1)
        else:
            await wait_for(lambda: any(item["type"] == "response.create" for item in wire.sent))
        output = scheduler._active.output_id
        if barrier != "core_registration":
            emit_audio(wire, output, request.id)
            started = await until(events, "realtime.output_started")
            await bridge._handle_event(started)
            audio_event = await until(events, "realtime.audio")
            await until(events, "realtime.assistant_transcript")
            if barrier == "device_lock":
                audio._output_lock.acquire()
                locked = True
                playing = asyncio.create_task(bridge._play_audio(1, audio_event))
                await asyncio.sleep(.01)
        scheduler.update_speech_context(context(conversation, "new-origin", epoch=2,
                                                invalid=(SpeechDependency("retired-work", "origin"),)))
        assert scheduler.output_admission(output).state is OutputAdmissionState.INVALIDATED
        await asyncio.sleep(0)  # Let the owned, exact cancellation reach the adapter.
        release.set()
        if barrier == "core_registration":
            await asyncio.wait_for(launch, 1)
            assert not any(item["type"] == "response.create" for item in wire.sent)
        else:
            if locked:
                audio._output_lock.release()
                locked = False
                assert await asyncio.wait_for(playing, 1) is None
            else:
                await bridge._play_audio(1, audio_event)
            await retire(wire, scheduler, events)
            await asyncio.wait_for(launch, 1)
        assert audio._output.writes == []
        await facade._dispatcher.flush()
        snapshot = (await client.voice_snapshot(conversation))["snapshot"]
        assert all(item["confirmed_text"] is None and item["played_ms"] in (None, 0) for item in snapshot["speeches"])
        assert not await history.read(conversation_id=conversation)
        assert request.outcome_id == "retained-outcome"
        # Repeated invalidation cannot cancel a useful output created afterward.
        new_output = await facade.speak_reserved(SpeechRequest(conversation, "New answer", correlation_id="new-origin"), output_id="new-output")
        wire.push(type="response.created", response={"id": "new-response", "metadata": {OUTPUT_ID_METADATA_KEY: new_output}})
        await until(events, "realtime.output_started")
        await asyncio.sleep(.01)
        assert all(item.get("response_id") != "new-response" for item in wire.sent if item["type"] == "response.cancel")
    finally:
        release.set()
        if locked:
            audio._output_lock.release()
        if playing is not None:
            await asyncio.gather(playing, return_exceptions=True)
        launch.cancel()
        await asyncio.gather(launch, return_exceptions=True)
        await scheduler.stop()
        await audio.close()


async def test_reserved_output_identity_cannot_be_reused_after_mapping_eviction(pipeline):
    facade, wire, client, conversation, events, history = pipeline
    lowlevel = facade.frontend._session
    request = SpeechRequest(conversation, "Bounded output")
    await lowlevel.speak(request, output_id="old-output")
    for index in range(lowlevel.MAX_TRACKED_OUTPUTS + 1):
        lowlevel._register_output(speech_id=None, output_id=f"reserved-{index}")
    assert "old-output" not in lowlevel._outputs
    with pytest.raises(ValueError, match="reused"):
        await lowlevel.speak(request, output_id="old-output")
    lowlevel._seen_local_outputs = {f"capacity-{index}" for index in range(4096)}
    with pytest.raises(ValueError, match="retention"):
        await lowlevel.speak(request, output_id="unseen-output")
    assert sum(item["type"] == "response.create" for item in wire.sent) == 1
