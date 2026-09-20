"""Canonical voice evidence. Generated text, input commit and playback differ."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar
from jarvis.domain.voice_playback import VoiceAudioPart

from jarvis.domain.voice_frontend import (
    FrontendState, ProviderEventId, VoiceAudioChunk, VoiceCorrelation,
    VoiceEventId, VoiceFrontendError, VoiceObservation, VoiceOperationId,
    VoiceSessionInterval, VoiceTranscriptId, VoiceTurnId, nonnegative, nonnegative_int,
    bounded_json_object, bounded_text,
)


@dataclass(frozen=True, slots=True)
class FrontendLifecycleChanged:
    kind: ClassVar[str] = "frontend.lifecycle_changed"
    state: FrontendState


class VoiceActivitySource(StrEnum):
    LOCAL = "local"
    PROVIDER = "provider"


class VoiceSpeechPhase(StrEnum):
    STARTED = "started"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class UserSpeechActivity:
    """VAD evidence only: neither owner authorization nor a committed turn."""

    kind: ClassVar[str] = "user.speech_activity"
    phase: VoiceSpeechPhase
    source: VoiceActivitySource


@dataclass(frozen=True, slots=True)
class UserTurnOpened:
    """Observed input ordering, independently of asynchronously arriving ASR.

    This is a grouping boundary, not transcript completion/action authorization.
    previous_turn_id=None denotes the first known turn. Emit only when ordering
    is known; absence of this event means order remains unknown/revisable.
    """

    kind: ClassVar[str] = "user.turn_opened"
    previous_turn_id: VoiceTurnId | None
    source: VoiceActivitySource


@dataclass(frozen=True, slots=True)
class UserTranscriptDelta:
    """Exact append fragment within a revisable application transcript grouping.

    revision increases with observations within this grouping; it does not reset
    previously accumulated text. Provisional hypothesis replacement is a Core
    operation, not an alternate interpretation of a delta. A committed payload
    supplies an explicit full-text replacement when that boundary is accepted.
    """

    kind: ClassVar[str] = "user.transcript_delta"
    transcript_id: VoiceTranscriptId
    delta: str = field(repr=False)
    revision: int = 0

    def __post_init__(self) -> None:
        nonnegative_int(self.revision, "revision")


class UserCommitSource(StrEnum):
    PROVIDER = "provider"
    APPLICATION = "application"


@dataclass(frozen=True, slots=True)
class UserTranscriptRevised:
    """Explicit replacement of provisional text; never a commit or permission."""

    kind: ClassVar[str] = "user.transcript_revised"
    transcript_id: VoiceTranscriptId
    text: str = field(repr=False)
    revision: int

    def __post_init__(self) -> None:
        nonnegative_int(self.revision, "revision")


@dataclass(frozen=True, slots=True)
class UserTranscriptCommitted:
    """Complete replacement at revision; source states who accepted its boundary.

    APPLICATION is an explicit admission decision, not a claim of provider
    finality. Providers lacking final events emit deltas, never a silence final.
    """

    kind: ClassVar[str] = "user.transcript_committed"
    transcript_id: VoiceTranscriptId
    text: str = field(repr=False)
    revision: int
    source: UserCommitSource

    def __post_init__(self) -> None:
        nonnegative_int(self.revision, "revision")


@dataclass(frozen=True, slots=True)
class AssistantTranscriptDelta:
    kind: ClassVar[str] = "assistant.transcript_delta"
    transcript_id: VoiceTranscriptId
    delta: str = field(repr=False)
    part: VoiceAudioPart | None = None

    def __post_init__(self) -> None:
        if self.part is not None and not isinstance(self.part, VoiceAudioPart):
            raise ValueError("Transcript audio part must be typed")


@dataclass(frozen=True, slots=True)
class AssistantTranscriptCompleted:
    """Provider completed generated transcript; no local playback implication."""

    kind: ClassVar[str] = "assistant.transcript_completed"
    transcript_id: VoiceTranscriptId
    text: str = field(repr=False)
    part: VoiceAudioPart | None = None

    def __post_init__(self) -> None:
        if self.part is not None and not isinstance(self.part, VoiceAudioPart):
            raise ValueError("Transcript audio part must be typed")


@dataclass(frozen=True, slots=True)
class AssistantAudioChunk:
    kind: ClassVar[str] = "assistant.audio_chunk"
    audio: VoiceAudioChunk
    part: VoiceAudioPart | None = None

    def __post_init__(self) -> None:
        if self.part is not None and not isinstance(self.part, VoiceAudioPart):
            raise ValueError("Audio part must be typed")


@dataclass(frozen=True, slots=True)
class AssistantAudioPartCompleted:
    """Provider closed one audio part; not whole generation or device completion."""
    kind: ClassVar[str] = "assistant.audio_part_completed"
    part: VoiceAudioPart

    def __post_init__(self) -> None:
        if not isinstance(self.part, VoiceAudioPart):
            raise ValueError("Completed audio part requires identity")


@dataclass(frozen=True, slots=True)
class AssistantAudioReceived:
    """Cumulative decoded duration; lightweight Core evidence without PCM."""
    kind: ClassVar[str] = "assistant.audio_received"
    received_ms: float

    def __post_init__(self) -> None:
        nonnegative(self.received_ms, "received_ms")


@dataclass(frozen=True, slots=True)
class VoiceToolCallRequested:
    """Untrusted arguments. Existing application policy grants tool authority."""
    kind: ClassVar[str] = "frontend.tool_call_requested"
    call_id: str
    name: str
    arguments_json: str = field(repr=False)

    def __post_init__(self) -> None:
        bounded_text(self.call_id, 256, "call_id")
        bounded_text(self.name, 128, "tool name")
        if any(not value or value != value.strip() or not value.isprintable() for value in (self.call_id, self.name)):
            raise ValueError("Tool call requires identity and name")
        bounded_json_object(self.arguments_json)


@dataclass(frozen=True, slots=True)
class AssistantGenerationStarted:
    kind: ClassVar[str] = "assistant.generation_started"


@dataclass(frozen=True, slots=True)
class AssistantSpeechActivity:
    """Local device start/stop, never provider generation start/done."""

    kind: ClassVar[str] = "assistant.speech_activity"
    phase: VoiceSpeechPhase


class VoiceGenerationStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AssistantGenerationFinished:
    """Explicit provider generation evidence, never inferred from an empty queue."""

    kind: ClassVar[str] = "assistant.generation_finished"
    status: VoiceGenerationStatus
    audio_parts: tuple[VoiceAudioPart, ...] | None = None
    audio_transcripts: tuple[str | None, ...] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.audio_parts is not None:
            if not isinstance(self.audio_parts, tuple) or len(self.audio_parts) > 128 or any(not isinstance(part, VoiceAudioPart) for part in self.audio_parts):
                raise ValueError("Generation audio parts must be a bounded typed tuple")
            if len(set(self.audio_parts)) != len(self.audio_parts):
                raise ValueError("Generation audio parts must be unique")
        if self.audio_transcripts is not None:
            if not isinstance(self.audio_transcripts, tuple) or self.audio_parts is None or len(self.audio_transcripts) != len(self.audio_parts):
                raise ValueError("Final transcripts must align with the part inventory")
            for text in self.audio_transcripts:
                if text is not None:
                    bounded_text(text, 8192, "final audio transcript")
            if sum(len(text or "") for text in self.audio_transcripts) > 8192:
                raise ValueError("Final transcript inventory exceeds bound")


class VoicePlaybackStatus(StrEnum):
    UNPLAYED = "unplayed"
    PARTIAL = "partial"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AssistantPlaybackEvidence:
    """Local device evidence, distinct from provider generation and text timing.

    played_ms is the cumulative local cursor for the correlated output, not a
    delta. confirmed_text is ONLY an independently aligned played span. None
    means word alignment unknown, even if all known audio finished playing.
    COMPLETE requires explicit end-of-output evidence plus drained local audio.
    It proves device delivery, not acoustic perception by a person.
    """

    kind: ClassVar[str] = "assistant.playback_evidence"
    status: VoicePlaybackStatus
    played_ms: float | None
    confirmed_text: str | None = field(default=None, repr=False)
    part: VoiceAudioPart | None = None

    def __post_init__(self) -> None:
        if self.part is not None and not isinstance(self.part, VoiceAudioPart):
            raise ValueError("Playback part must be typed")
        if self.played_ms is not None:
            nonnegative(self.played_ms, "played_ms")
        if self.status == VoicePlaybackStatus.UNPLAYED and self.played_ms != 0:
            raise ValueError("Unplayed output requires a zero cursor")
        if self.status in (VoicePlaybackStatus.PARTIAL, VoicePlaybackStatus.COMPLETE) and not self.played_ms:
            raise ValueError("Partial/complete playback requires positive playback evidence")
        if self.confirmed_text is not None and (not self.played_ms or self.status == VoicePlaybackStatus.UNKNOWN):
            raise ValueError("Confirmed text requires known positive playback evidence")


class VoiceInterruptionStage(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class UserInterruption:
    """Provider confirmation does not replace JARVIS owner/admission checks."""

    kind: ClassVar[str] = "user.interruption"
    stage: VoiceInterruptionStage
    source: VoiceActivitySource


@dataclass(frozen=True, slots=True)
class VoiceDelegationRequested:
    """Trigger only. Core builds work from a bounded, revision-tagged snapshot.

    Exact provider delegation ID lives in correlation; no invented task text.
    A trigger neither commits a transcript nor authorizes an external action.

    offset_ms is the provider's own session clock at emission. It is a
    diagnostic only: the provider emits the trigger within the same few
    milliseconds as the last input fragment, so it bounds no transcript.
    None means the source did not state one, never zero.
    """

    kind: ClassVar[str] = "frontend.delegation_requested"
    context_revision: int
    offset_ms: int | None = None

    def __post_init__(self) -> None:
        nonnegative_int(self.context_revision, "context_revision")
        if self.offset_ms is not None:
            nonnegative_int(self.offset_ms, "offset_ms")


@dataclass(frozen=True, slots=True)
class VoiceFrontendFailed:
    kind: ClassVar[str] = "frontend.error"
    error: VoiceFrontendError


class VoiceUsageSource(StrEnum):
    PROVIDER_SNAPSHOT = "provider_snapshot"
    PROVIDER_FINAL = "provider_final"
    LOCAL_ESTIMATE = "local_estimate"


@dataclass(frozen=True, slots=True)
class VoiceUsageUpdated:
    """Cumulative session counters; replace snapshots, never sum them.

    None is unknown/unsupported, not zero. Backend usage remains separate.
    Final usage alone does not establish a confirmed lifecycle stop.
    """

    kind: ClassVar[str] = "frontend.usage_updated"
    source: VoiceUsageSource
    duration_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.duration_s is not None:
            nonnegative(self.duration_s, "duration_s")
        for name in ("input_tokens", "output_tokens"):
            if (value := getattr(self, name)) is not None:
                nonnegative_int(value, name)


VoiceEventPayload = (
    FrontendLifecycleChanged | UserSpeechActivity | UserTurnOpened | UserTranscriptDelta | UserTranscriptRevised
    | UserTranscriptCommitted | AssistantTranscriptDelta | AssistantTranscriptCompleted
    | AssistantAudioChunk | AssistantGenerationStarted | AssistantGenerationFinished
    | AssistantSpeechActivity | AssistantPlaybackEvidence
    | UserInterruption | VoiceDelegationRequested | VoiceFrontendFailed | VoiceUsageUpdated
    | AssistantAudioReceived | AssistantAudioPartCompleted | VoiceToolCallRequested
)


@dataclass(frozen=True, slots=True)
class VoiceEvent:
    """One ordered canonical stream per frontend incarnation.

    sequence orders local observations, not provider time or causality. event_id
    identifies replay duplicates. Consumers dedupe by session/event ID and reject
    stale sessions. provider_interval is optional source timing, not played time.
    Runtime playback producers use this same envelope, not a provider SDK type.
    """

    event_id: VoiceEventId
    sequence: int
    correlation: VoiceCorrelation
    observation: VoiceObservation
    payload: VoiceEventPayload
    operation_id: VoiceOperationId | None = None
    provider_event_id: ProviderEventId | None = None
    provider_interval: VoiceSessionInterval | None = None

    def __post_init__(self) -> None:
        nonnegative_int(self.sequence, "sequence")
        if isinstance(self.payload, (UserTurnOpened, UserTranscriptCommitted)) and self.correlation.turn_id is None:
            raise ValueError("An opened/committed turn requires a JARVIS turn ID")
