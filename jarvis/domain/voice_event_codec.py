"""Strict canonical Core ingress codec. Audio bytes never cross this boundary."""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime

from jarvis.domain import voice_events as events
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceCorrelation, VoiceErrorCode, VoiceFrontendError, VoiceObservation,
    VoiceOperationKind, VoiceSessionInterval, bounded_text, nonnegative, nonnegative_int,
)
from jarvis.domain.voice_state import correlation_valid, state_id
from jarvis.domain.voice_playback import VoiceAudioPart


_PAYLOADS = (
    events.FrontendLifecycleChanged, events.UserSpeechActivity, events.UserTurnOpened,
    events.UserTranscriptDelta, events.UserTranscriptRevised, events.UserTranscriptCommitted,
    events.AssistantTranscriptDelta, events.AssistantTranscriptCompleted,
    events.AssistantAudioReceived, events.AssistantAudioPartCompleted, events.AssistantGenerationStarted,
    events.AssistantGenerationFinished, events.AssistantSpeechActivity,
    events.AssistantPlaybackEvidence, events.UserInterruption,
    events.VoiceDelegationRequested, events.VoiceToolCallRequested,
    events.VoiceFrontendFailed, events.VoiceUsageUpdated,
)
_BY_KIND = {cls.kind: cls for cls in _PAYLOADS}
_EVENT_FIELDS = {
    "schema_version", "event_id", "sequence", "correlation", "observation", "payload",
    "operation_id", "provider_event_id", "provider_interval",
}
_ENUM_FIELDS = {
    events.FrontendLifecycleChanged: {"state": FrontendState},
    events.UserSpeechActivity: {"phase": events.VoiceSpeechPhase, "source": events.VoiceActivitySource},
    events.UserTurnOpened: {"source": events.VoiceActivitySource},
    events.UserTranscriptCommitted: {"source": events.UserCommitSource},
    events.AssistantGenerationFinished: {"status": events.VoiceGenerationStatus},
    events.AssistantSpeechActivity: {"phase": events.VoiceSpeechPhase},
    events.AssistantPlaybackEvidence: {"status": events.VoicePlaybackStatus},
    events.UserInterruption: {"stage": events.VoiceInterruptionStage, "source": events.VoiceActivitySource},
    events.VoiceUsageUpdated: {"source": events.VoiceUsageSource},
}


def _shape(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("invalid canonical object fields")
    return dict(value)


def decode_voice_correlation(payload: object) -> VoiceCorrelation:
    try:
        correlation = VoiceCorrelation(**_shape(payload, {item.name for item in fields(VoiceCorrelation)}))
        correlation_valid(correlation)
        return correlation
    except (ValueError, TypeError):
        raise ValueError("invalid canonical voice correlation") from None


def _decode_error(payload: object) -> VoiceFrontendError:
    data = _shape(payload, {item.name for item in fields(VoiceFrontendError)})
    data["code"] = VoiceErrorCode(data["code"])
    data["state"] = FrontendState(data["state"])
    if data["operation"] is not None:
        data["operation"] = VoiceOperationKind(data["operation"])
    if type(data["retryable"]) is not bool:
        raise ValueError("retryable must be boolean")
    return VoiceFrontendError(**data)


def _decode_payload(payload: object) -> events.VoiceEventPayload:
    if not isinstance(payload, dict) or not isinstance(payload.get("kind"), str):
        raise ValueError("canonical payload kind required")
    cls = _BY_KIND.get(payload["kind"])
    if cls is None:
        raise ValueError("unsupported canonical payload; PCM is forbidden")
    payload = dict(payload)
    # Version1 events written before Task07 had no optional part inventory.
    if cls in (events.AssistantTranscriptDelta, events.AssistantTranscriptCompleted, events.AssistantPlaybackEvidence):
        payload.setdefault("part", None)
    if cls is events.AssistantGenerationFinished:
        payload.setdefault("audio_parts", None)
        payload.setdefault("audio_transcripts", None)
    data = _shape(payload, {"kind", *(item.name for item in fields(cls))})
    del data["kind"]
    for key, enum in _ENUM_FIELDS.get(cls, {}).items():
        data[key] = enum(data[key])
    for name in ("transcript_id", "call_id"):
        if name in data:
            state_id(data[name], name)
    if "previous_turn_id" in data:
        state_id(data["previous_turn_id"], "previous_turn_id", optional=True)
    for name in ("delta", "text", "confirmed_text"):
        if name in data and (data[name] is not None or name != "confirmed_text"):
            bounded_text(data[name], 8192, name)
    for name in ("revision", "context_revision"):
        if name in data:
            nonnegative_int(data[name], name)
    if "error" in data:
        data["error"] = _decode_error(data["error"])
    if data.get("part") is not None:
        data["part"] = VoiceAudioPart(**_shape(data["part"], {"item_id", "content_index", "output_index"}))
    if data.get("audio_parts") is not None:
        if not isinstance(data["audio_parts"], (list, tuple)) or len(data["audio_parts"]) > 128:
            raise ValueError("Invalid audio part inventory")
        data["audio_parts"] = tuple(VoiceAudioPart(**_shape(part, {"item_id", "content_index", "output_index"})) for part in data["audio_parts"])
    if data.get("audio_transcripts") is not None:
        if not isinstance(data["audio_transcripts"], (list, tuple)) or len(data["audio_transcripts"]) > 128:
            raise ValueError("Invalid audio transcript inventory")
        data["audio_transcripts"] = tuple(data["audio_transcripts"])
    return cls(**data)


def decode_voice_event(payload: object) -> events.VoiceEvent:
    """Reject unknown fields/types/versions/PCM without echoing private payloads."""
    try:
        data = _shape(payload, _EVENT_FIELDS)
        if type(data.pop("schema_version")) is not int or payload["schema_version"] != 1:
            raise ValueError("unsupported canonical event version")
        state_id(data["event_id"], "event_id")
        nonnegative_int(data["sequence"], "sequence")
        for name in ("operation_id", "provider_event_id"):
            state_id(data[name], name, optional=True)
        data["correlation"] = decode_voice_correlation(data["correlation"])
        observation = _shape(data["observation"], {"observed_at", "monotonic_ns"})
        if not isinstance(observation["observed_at"], str):
            raise ValueError("observation time must be ISO8601")
        observation["observed_at"] = datetime.fromisoformat(observation["observed_at"])
        data["observation"] = VoiceObservation(**observation)
        if data["provider_interval"] is not None:
            interval = _shape(data["provider_interval"], {"start_ms", "end_ms"})
            data["provider_interval"] = VoiceSessionInterval(**interval)
        data["payload"] = _decode_payload(data["payload"])
        return events.VoiceEvent(**data)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("invalid canonical voice event") from None


def encode_voice_event(event: events.VoiceEvent) -> dict[str, object]:
    """JSON-ready canonical event; validating before return prevents SDK leakage."""
    if not isinstance(event, events.VoiceEvent) or type(event.payload) not in _PAYLOADS:
        raise ValueError("unsupported canonical event; PCM is forbidden")
    payload = asdict(event)
    payload["schema_version"] = 1
    payload["observation"]["observed_at"] = event.observation.observed_at.isoformat()
    payload["payload"]["kind"] = event.payload.kind
    decode_voice_event(payload)
    return payload
