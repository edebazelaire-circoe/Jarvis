from __future__ import annotations

from dataclasses import asdict, replace
import json

import pytest

from jarvis.domain import voice_events as events
from jarvis.domain.voice_event_codec import decode_voice_event, encode_voice_event
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceAudioChunk, VoiceCorrelation, VoiceErrorCode, VoiceFrontendError,
    VoiceSessionId, VoiceSessionInterval,
)
from tests.fakes.voice_frontend import FakeVoiceFrontend


CORRELATION = VoiceCorrelation(VoiceSessionId("session"), turn_id="turn", output_id="local-output",
                               provider_output_id="response", provider_item_id="item",
                               source_correlation_id="brain-correlation", backend_work_id="backend-work")
PAYLOADS = [
    events.FrontendLifecycleChanged(FrontendState.STARTING),
    events.UserSpeechActivity(events.VoiceSpeechPhase.STARTED, events.VoiceActivitySource.LOCAL),
    events.UserTurnOpened(None, events.VoiceActivitySource.PROVIDER),
    events.UserTranscriptDelta("transcript", " exact ", 0),
    events.UserTranscriptRevised("transcript", "correction", 1),
    events.UserTranscriptCommitted("transcript", "final", 2, events.UserCommitSource.PROVIDER),
    events.AssistantTranscriptDelta("generated", "part "),
    events.AssistantTranscriptCompleted("generated", "full generated"),
    events.AssistantAudioReceived(35.5),
    events.AssistantGenerationStarted(),
    events.AssistantGenerationFinished(events.VoiceGenerationStatus.INCOMPLETE),
    events.AssistantSpeechActivity(events.VoiceSpeechPhase.STOPPED),
    events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.PARTIAL, 20, "heard"),
    events.UserInterruption(events.VoiceInterruptionStage.CONFIRMED, events.VoiceActivitySource.LOCAL),
    events.VoiceDelegationRequested(4),
    events.VoiceToolCallRequested("call", "tool", '{"bounded":"arguments"}'),
    events.VoiceFrontendFailed(VoiceFrontendError(VoiceErrorCode.TRANSPORT, None, FrontendState.UNKNOWN_REAP_REQUIRED)),
    events.VoiceUsageUpdated(events.VoiceUsageSource.PROVIDER_FINAL, 10, 5, None),
]


@pytest.mark.parametrize("payload", PAYLOADS, ids=lambda payload: payload.kind)
def test_canonical_event_strict_json_roundtrip(payload):
    event = FakeVoiceFrontend().event(payload, correlation=CORRELATION)
    event = replace(event, provider_interval=VoiceSessionInterval(5, 12), operation_id="operation", provider_event_id="provider-event")
    encoded = encode_voice_event(event)
    assert decode_voice_event(json.loads(json.dumps(encoded))) == event
    encoded["correlation"]["turn_id"] = "changed"
    assert event.correlation.turn_id == "turn"


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema_version=True),
    lambda d: d.update(schema_version=2),
    lambda d: d.update(sequence=1.5),
    lambda d: d.update(event_id=""),
    lambda d: d.update(provider_payload={"secret":"PRIVATE"}),
    lambda d: d["correlation"].update(provider_item_id=["PRIVATE"]),
    lambda d: d["correlation"].update(source_correlation_id="PRIVATE\n"),
    lambda d: d["correlation"].update(backend_work_id=123),
    lambda d: d["observation"].update(monotonic_ns=True),
    lambda d: d["observation"].update(observed_at="2026-01-01"),
    lambda d: d["payload"].update(kind="session.output_audio.delta"),
    lambda d: d["payload"].update(delta="PRIVATE" * 8192),
    lambda d: d["payload"].update(revision=-1),
    lambda d: d["payload"].update(extra="PRIVATE"),
])
def test_malformed_event_rejected_without_echoing_private_payload(change):
    encoded = encode_voice_event(FakeVoiceFrontend().event(events.UserTranscriptDelta("transcript", "fine"), correlation=CORRELATION))
    change(encoded)
    with pytest.raises(ValueError) as failure:
        decode_voice_event(encoded)
    assert "PRIVATE" not in str(failure.value)


def test_pcm_is_refused_by_encoder_and_decoder():
    event = FakeVoiceFrontend().event(events.AssistantAudioChunk(VoiceAudioChunk(b"\0\0")), correlation=CORRELATION)
    with pytest.raises(ValueError, match="PCM"):
        encode_voice_event(event)
    data = encode_voice_event(FakeVoiceFrontend().event(events.AssistantAudioReceived(1), correlation=CORRELATION))
    data["payload"] = {"kind": "assistant.audio_chunk", "audio": {"pcm": "AAAA"}}
    with pytest.raises(ValueError):
        decode_voice_event(data)


@pytest.mark.parametrize("payload,field,value", [
    (events.AssistantAudioReceived(1), "received_ms", float("inf")),
    (events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.UNKNOWN, None), "played_ms", float("nan")),
    (events.VoiceUsageUpdated(events.VoiceUsageSource.PROVIDER_FINAL), "input_tokens", True),
    (events.VoiceToolCallRequested("call", "tool", "{}"), "arguments_json", '{"x":1e999}'),
])
def test_nonfinite_and_invalid_nested_values_rejected(payload, field, value):
    data = encode_voice_event(FakeVoiceFrontend().event(payload, correlation=CORRELATION))
    data["payload"][field] = value
    with pytest.raises(ValueError):
        decode_voice_event(data)
