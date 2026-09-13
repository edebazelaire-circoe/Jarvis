"""Real canonical pipeline with injected proof values; device tests own drain truth."""
from dataclasses import replace
import base64

import pytest

from jarvis.domain.v2 import PlaybackCursor
from jarvis.domain.voice_event_codec import decode_voice_event, encode_voice_event
from jarvis.domain.voice_events import AssistantTranscriptCompleted, AssistantAudioPartCompleted, AssistantGenerationFinished, VoiceGenerationStatus
from jarvis.domain.voice_frontend import VoiceCorrelation
from jarvis.domain.voice_playback import VoiceAudioPart, VoiceAudioPartExtent, VoiceDevicePlaybackProof, VoiceDevicePlaybackStatus
from jarvis.domain.voice_state import VoiceConversationSnapshot
from tests.fakes.voice_frontend import FakeVoiceFrontend
from tests.unit.test_realtime_frontend_pipeline import pipeline, until
from tests.unit.test_realtime_frontend_adapter import Wire
from jarvis.adapters.openai_realtime import OpenAIRealtimeSession


def item(item_id, *types):
    return {"id": item_id, "type": "message", "role": "assistant", "status": "completed", "content": [{"type": kind} for kind in types]}


def push_part(wire, *, item_id="one", index=0, output_index=0, text="Hello ", closed=True, response="r", byte_count=960):
    identity = dict(response_id=response, item_id=item_id, content_index=index, output_index=output_index)
    if byte_count:
        wire.push(type="response.output_audio.delta", **identity, delta=base64.b64encode(bytes(byte_count)).decode())
    if closed:
        wire.push(type="response.output_audio.done", **identity)
    if text is not None:
        wire.push(type="response.output_audio_transcript.done", **identity, transcript=text)


def proof(manifest):
    return VoiceDevicePlaybackProof(VoiceDevicePlaybackStatus.COMPLETE, manifest.session_id, manifest.output_id,
        manifest.provider_response_id, "controlled-device", 1, 1, "drain-operation", manifest.parts,
        manifest.received_bytes, manifest.received_bytes)


async def finish(wire, events, output, *, status="completed"):
    wire.push(type="response.done", response={"id": "r", "status": status, "output": output})
    return await until(events, "realtime.response_done")


async def test_three_parts_same_item_and_late_transcript_join_exact_old_output(pipeline):
    facade, wire, client, conversation, events, history = pipeline
    wire.push(type="response.created", response={"id": "r"})
    push_part(wire)
    push_part(wire, index=1, text="world")
    push_part(wire, item_id="two", output_index=1, text=None)
    done = await finish(wire, events, [item("one", "audio", "output_audio"), item("two", "output_audio")])
    manifest = facade.playback_manifest(done.payload)
    assert manifest is not None and len(manifest.parts) == 3
    assert not await history.read(conversation_id=conversation)
    assert facade.observe_device_completion(manifest, proof(manifest))
    await facade._dispatcher.flush()
    assert not await history.read(conversation_id=conversation)  # Device alone is not words.
    wire.push(type="response.created", response={"id": "next-response"})
    wire.push(type="response.output_audio_transcript.done", response_id="r", item_id="two", content_index=0, output_index=1, transcript="!")
    await until(events, "realtime.assistant_transcript")
    # The old transcript event may follow buffered earlier transcript envelopes.
    while facade._playback_manifests._outputs[manifest.output_id].transcripts.get(VoiceAudioPart("two", 0, 1)) != "!":
        await until(events, "realtime.assistant_transcript")
    await facade._dispatcher.flush()
    snapshot = (await client.voice_snapshot(conversation))["snapshot"]
    old = next(row for row in snapshot["speeches"] if row["correlation"]["output_id"] == manifest.output_id)
    assert old["confirmed_text"] == "Hello world!" and len({p["transcript_id"] for p in old["generated"]}) == 3
    assert [p["part"]["content_index"] for p in old["generated"]] == [0, 1, 0]
    assert len(await history.read(conversation_id=conversation)) == 1
    assert not facade.observe_device_completion(manifest, proof(manifest))
    assert VoiceConversationSnapshot.from_dict(snapshot).to_dict() == snapshot
    for speech in snapshot["speeches"]:
        for generated in speech["generated"]:
            generated.pop("part")  # Version1 pre-Task07 snapshots migrate to explicit unknown identity.
    restored = VoiceConversationSnapshot.from_dict(snapshot)
    assert all(generated.part is None for speech in restored.speeches for generated in speech.generated)


@pytest.mark.parametrize("failure", ["missing_part", "not_closed", "zero_audio", "wrong_index", "wrong_item", "cancelled", "incomplete", "failed_item", "unknown_content", "missing_manifest"])
async def test_no_complete_manifest_for_missing_or_ambiguous_generation(pipeline, failure):
    facade, wire, client, conversation, events, history = pipeline
    wire.push(type="response.created", response={"id": "r"})
    push_part(wire, closed=failure != "not_closed", byte_count=0 if failure == "zero_audio" else 960,
              output_index=1 if failure == "wrong_index" else 0, item_id="wrong" if failure == "wrong_item" else "one")
    output = [item("one", "output_audio")]
    if failure == "missing_part":
        output[0]["content"].append({"type": "output_audio"})
    if failure == "failed_item":
        output[0]["status"] = "incomplete"
    if failure == "unknown_content":
        output[0]["content"].append({"type": "unknown"})
    done = await finish(wire, events, None if failure == "missing_manifest" else output,
                        status=failure if failure in ("cancelled", "incomplete") else "completed")
    assert facade.playback_manifest(done.payload) is None
    await facade._dispatcher.flush()
    assert not await history.read(conversation_id=conversation)


@pytest.mark.parametrize("failure", ["dropped_write", "wrong_output", "wrong_session", "interrupted", "unknown"])
async def test_device_proof_must_cover_exact_output_and_all_received_bytes(pipeline, failure):
    facade, wire, client, conversation, events, history = pipeline
    wire.push(type="response.created", response={"id": "r"})
    push_part(wire)
    done = await finish(wire, events, [item("one", "output_audio")])
    manifest = facade.playback_manifest(done.payload)
    evidence = proof(manifest)
    if failure == "dropped_write":
        evidence = replace(evidence, parts=(VoiceAudioPartExtent(manifest.parts[0].part, 480),), written_bytes=480, confirmed_bytes=480)
    elif failure == "wrong_output":
        evidence = replace(evidence, output_id="another-output")
    elif failure == "wrong_session":
        evidence = replace(evidence, session_id="another-session")
    elif failure == "interrupted":
        await facade.truncate(PlaybackCursor(manifest.output_id, 0, "r", "one", 0))
    else:
        evidence = replace(evidence, status=VoiceDevicePlaybackStatus.UNKNOWN, confirmed_bytes=0)
    assert not facade.observe_device_completion(manifest, evidence)
    assert not facade.observe_device_completion(manifest, proof(manifest))  # Rejected proof cannot resurrect.
    await facade._dispatcher.flush()
    assert not await history.read(conversation_id=conversation)


async def test_known_text_content_is_excluded_from_audio_manifest(pipeline):
    facade, wire, _, _, events, _ = pipeline
    wire.push(type="response.created", response={"id": "r"})
    push_part(wire, index=1)
    done = await finish(wire, events, [item("one", "output_text", "output_audio")])
    assert [p.part.content_index for p in facade.playback_manifest(done.payload).parts] == [1]


@pytest.mark.parametrize("contradiction", ["late_part_close", "late_delta", "final_inventory_text", "late_audio"])
async def test_frozen_manifest_cannot_hide_late_contradiction(pipeline, contradiction):
    facade, wire, client, conversation, events, history = pipeline
    wire.push(type="response.created", response={"id": "r"})
    push_part(wire)
    output = [item("one", "output_audio")]
    if contradiction == "final_inventory_text":
        output[0]["content"][0]["transcript"] = "Contradictory generated text"
    done = await finish(wire, events, output)
    manifest = facade.playback_manifest(done.payload)
    assert manifest is not None
    if contradiction == "late_part_close":
        wire.push(type="response.output_audio.done", response_id="r", item_id="extra", content_index=0, output_index=1)
        await until(events, "realtime.audio_done")
    elif contradiction == "late_delta":
        wire.push(type="response.output_audio_transcript.delta", response_id="r", item_id="one", content_index=0, output_index=0, delta=" AFTER")
        await until(events, "realtime.assistant_transcript_delta")
    elif contradiction == "late_audio":
        wire.push(type="response.output_audio.delta", response_id="r", item_id="one", content_index=0, output_index=0,
                  delta=base64.b64encode(bytes(960)).decode())
        await until(events, "realtime.audio")
    assert not facade.observe_device_completion(manifest, proof(manifest))
    await facade._dispatcher.flush()
    assert not await history.read(conversation_id=conversation)


async def test_truncate_keeps_playing_part_zero_while_part_one_already_received(pipeline):
    facade, wire, _, _, events, _ = pipeline
    wire.push(type="response.created", response={"id": "r"})
    push_part(wire, byte_count=960)
    push_part(wire, index=1, byte_count=4800)
    first = await until(events, "realtime.audio")
    await until(events, "realtime.audio")
    await facade.truncate(PlaybackCursor(first.payload["output_id"], 80, "r", "one", 0))
    truncations = [event for event in wire.sent if event["type"] == "conversation.item.truncate"]
    assert truncations == [{"type": "conversation.item.truncate", "item_id": "one", "content_index": 0, "audio_end_ms": 20}]


@pytest.mark.parametrize("payload", [AssistantTranscriptCompleted("text", "Generated", VoiceAudioPart("item", 1, 0)),
    AssistantAudioPartCompleted(VoiceAudioPart("item", 1, 0)),
    AssistantGenerationFinished(VoiceGenerationStatus.COMPLETED, (VoiceAudioPart("item", 1, 0),))])
def test_part_event_codec_strict_roundtrip(payload):
    event = FakeVoiceFrontend().event(payload, correlation=VoiceCorrelation("session", output_id="output", provider_output_id="response"))
    encoded = encode_voice_event(event)
    assert decode_voice_event(encoded) == event
    part = encoded["payload"].get("part") or encoded["payload"]["audio_parts"][0]
    part["content_index"] = True
    with pytest.raises(ValueError):
        decode_voice_event(encoded)


async def test_duplicate_response_created_cannot_reopen_after_details_evicted():
    wire = Wire()
    session = OpenAIRealtimeSession(wire, object(), owns_http=False)
    events = session.events()
    try:
        for number in range(140):
            wire.push(type="response.created", response={"id": str(number)})
            started = await anext(events)
            assert started.message_type == "realtime.output_started"
        current = session.active_output_id
        assert "0" not in session._output_by_response
        wire.push(type="response.created", response={"id": "0"})
        wire.push(type="input_audio_buffer.speech_started", item_id="user")
        assert (await anext(events)).message_type == "realtime.speech_started"
        assert session.active_output_id == current and "0" not in session._output_by_response
        assert len(session._outputs) == session.MAX_TRACKED_OUTPUTS
    finally:
        await events.aclose()
        await session.close()


async def test_response_identity_retention_exhaustion_never_forgets_to_reopen():
    wire = Wire()
    session = OpenAIRealtimeSession(wire, object(), owns_http=False)
    session._seen_response_starts.update(str(number) for number in range(4096))
    events = session.events()
    try:
        wire.push(type="response.created", response={"id": "new"})
        with pytest.raises(ValueError, match="retention exhausted"):
            await anext(events)
        assert not session._outputs and len(session._seen_response_starts) == 4096
    finally:
        await events.aclose()
        await session.close()


async def test_truncate_rejects_an_explicit_part_that_was_never_received():
    wire = Wire()
    session = OpenAIRealtimeSession(wire, object(), owns_http=False)
    events = session.events()
    try:
        wire.push(type="response.created", response={"id": "r"})
        created = await anext(events)
        push_part(wire)
        await anext(events)
        with pytest.raises(ValueError, match="no received audio"):
            await session.truncate(PlaybackCursor(created.payload["output_id"], 10, "r", "one", 1))
        assert not wire.sent
    finally:
        await events.aclose()
        await session.close()
