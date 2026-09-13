"""Provider-neutral voice commands, identity, lifecycle and result values.

No credentials or provider payload dictionaries belong in these values. Text is
application context, not diagnostic data; adapters enforce their own token limits
in addition to the transport-independent character bounds below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import math
import json
from typing import NewType

from jarvis.domain.voice_architecture import VoiceModeConfig


VoiceSessionId = NewType("VoiceSessionId", str)
VoiceTurnId = NewType("VoiceTurnId", str)
VoiceTaskId = NewType("VoiceTaskId", str)
VoiceSpeechId = NewType("VoiceSpeechId", str)
VoiceOutputId = NewType("VoiceOutputId", str)
VoiceOperationId = NewType("VoiceOperationId", str)
VoiceEventId = NewType("VoiceEventId", str)
VoiceTranscriptId = NewType("VoiceTranscriptId", str)
ProviderSessionId = NewType("ProviderSessionId", str)
ProviderOutputId = NewType("ProviderOutputId", str)
ProviderInputId = NewType("ProviderInputId", str)
ProviderEventId = NewType("ProviderEventId", str)
ProviderDelegationId = NewType("ProviderDelegationId", str)


def nonnegative(value: int | float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


def nonnegative_int(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def bounded_text(value: str, limit: int, name: str) -> None:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{name} must be text of at most {limit} characters")


@dataclass(frozen=True, slots=True)
class VoiceCorrelation:
    """Opaque IDs; never parse prefixes or join sessions using timestamps.

    session_id is a new JARVIS frontend incarnation, not a conversation ID.
    Optional IDs mean unknown/not applicable, not permission to invent identity.
    A Live delegation ID need not imply a committed turn or backend task yet.
    """

    session_id: VoiceSessionId
    turn_id: VoiceTurnId | None = None
    task_id: VoiceTaskId | None = None
    speech_id: VoiceSpeechId | None = None
    provider_session_id: ProviderSessionId | None = None
    provider_output_id: ProviderOutputId | None = None
    provider_delegation_id: ProviderDelegationId | None = None
    provider_input_id: ProviderInputId | None = None
    previous_provider_input_id: ProviderInputId | None = None
    output_id: VoiceOutputId | None = None
    provider_item_id: str | None = None
    source_correlation_id: str | None = None
    backend_work_id: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id is required")


@dataclass(frozen=True, slots=True)
class VoiceObservation:
    """Local receipt time. monotonic_ns is process-local, never wall-clock time."""

    observed_at: datetime
    monotonic_ns: int

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        nonnegative_int(self.monotonic_ns, "monotonic_ns")


@dataclass(frozen=True, slots=True)
class VoiceSessionInterval:
    """Provider session-relative milliseconds, [start, end); NOT word alignment."""

    start_ms: float
    end_ms: float

    def __post_init__(self) -> None:
        nonnegative(self.start_ms, "start_ms")
        nonnegative(self.end_ms, "end_ms")
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must follow start_ms")


class FrontendState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    STOPPED = "stopped"
    UNKNOWN_REAP_REQUIRED = "unknown_reap_required"


class VoiceOperationKind(StrEnum):
    START = "start"
    STOP = "stop"
    SEND_AUDIO = "send_audio"
    FINISH_INPUT = "finish_input"
    QUIET_CONTEXT = "quiet_context"
    SPOKEN_RESULT = "spoken_result"
    RUNTIME_INSTRUCTION = "runtime_instruction"
    CANCEL_SPEECH = "cancel_speech"
    TOOL_RESULT = "tool_result"
    REFLEX = "reflex"
    CONTEXT_MESSAGE = "context_message"
    CONVERSATION = "conversation"


class VoiceOperationStatus(StrEnum):
    ACCEPTED = "accepted"  # Sent/queued; not provider consumption or playback.
    COMPLETED = "completed"  # Operation-specific evidence; never implied speech.
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"
    FAILED = "failed"
    UNKNOWN = "unknown"  # Side effect/finalization cannot be established.


class VoiceErrorCode(StrEnum):
    UNSUPPORTED = "voice_operation_unsupported"
    INVALID_STATE = "voice_invalid_state"
    INVALID_INPUT = "voice_invalid_input"
    CONTEXT_LIMIT = "voice_context_limit"
    AUTHENTICATION = "voice_authentication_failed"
    RATE_LIMIT = "voice_rate_limited"
    TRANSPORT = "voice_transport_failed"
    PROVIDER = "voice_provider_failed"
    TIMEOUT = "voice_operation_timeout"
    CLOSE_UNCONFIRMED = "voice_close_unconfirmed"
    CANCELLED = "voice_operation_cancelled"


@dataclass(frozen=True, slots=True)
class VoiceFrontendError:
    """Adapter-sanitized diagnostics only; no raw exceptions, URLs or payloads."""

    code: VoiceErrorCode
    operation: VoiceOperationKind | None
    state: FrontendState
    retryable: bool = False
    safe_message: str = field(default="", repr=False)
    provider_code: str | None = None

    def __post_init__(self) -> None:
        bounded_text(self.safe_message, 512, "safe_message")
        if self.provider_code is not None:
            bounded_text(self.provider_code, 128, "provider_code")


@dataclass(frozen=True, slots=True)
class VoiceOperation:
    operation_id: VoiceOperationId
    correlation: VoiceCorrelation


@dataclass(frozen=True, slots=True)
class VoiceConversationRequest:
    """Explicit references to admitted input, never a reinserted user message."""
    input_item_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.input_item_ids, tuple) or not 1 <= len(self.input_item_ids) <= 16 or len(set(self.input_item_ids)) != len(self.input_item_ids):
            raise ValueError("conversation requires one to sixteen unique input references")
        for value in self.input_item_ids:
            if not isinstance(value, str) or not value or len(value) > 256 or not value.isprintable() or value.strip() != value:
                raise ValueError("invalid conversation input reference")


@dataclass(frozen=True, slots=True)
class VoiceOperationResult:
    operation: VoiceOperation
    kind: VoiceOperationKind
    status: VoiceOperationStatus
    state: FrontendState
    error: VoiceFrontendError | None = None
    provider_output_id: ProviderOutputId | None = None
    output_id: VoiceOutputId | None = None


    def __post_init__(self) -> None:
        unsuccessful = self.status in {
            VoiceOperationStatus.UNSUPPORTED, VoiceOperationStatus.REJECTED,
            VoiceOperationStatus.FAILED, VoiceOperationStatus.UNKNOWN,
        }
        if unsuccessful != (self.error is not None):
            raise ValueError("Unsuccessful operations require diagnostics; successes must not carry errors")
        if self.error and (self.error.state != self.state or self.error.operation not in (None, self.kind)):
            raise ValueError("Error must describe the result's operation and state")
        if self.kind == VoiceOperationKind.STOP and self.status == VoiceOperationStatus.COMPLETED and self.state != FrontendState.STOPPED:
            raise ValueError("Completed stop requires confirmed STOPPED state")
        if self.kind == VoiceOperationKind.STOP and self.status == VoiceOperationStatus.UNKNOWN and self.state == FrontendState.STOPPED:
            raise ValueError("Unknown stop cannot claim STOPPED state")


class VoiceStopReason(StrEnum):
    USER = "user"
    IDLE = "idle"
    SWITCH = "switch"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    CANCELLED = "cancelled"


class VoiceContextRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    DEVELOPER = "developer"


@dataclass(frozen=True, slots=True)
class VoiceContextMessage:
    role: VoiceContextRole
    text: str = field(repr=False)

    def __post_init__(self) -> None:
        bounded_text(self.text, 8192, "context message")


@dataclass(frozen=True, slots=True)
class VoiceContext:
    """Bounded application-selected projection, not a second history store.

    revision tags the source snapshot. Assistant messages must be selected using
    playback evidence; intent/generated text is never automatically heard history.
    These character limits do not guarantee any provider's token budget.
    """

    revision: int = 0
    messages: tuple[VoiceContextMessage, ...] = ()

    def __post_init__(self) -> None:
        nonnegative_int(self.revision, "revision")
        if not isinstance(self.messages, tuple) or any(not isinstance(m, VoiceContextMessage) for m in self.messages):
            raise ValueError("messages must be an immutable tuple of VoiceContextMessage")
        if len(self.messages) > 128 or sum(len(m.text) for m in self.messages) > 32768:
            raise ValueError("context exceeds 128 messages or 32768 characters")


@dataclass(frozen=True, slots=True)
class VoiceTextUpdate:
    """Intent/facts/instruction according to the method called; never heard proof."""

    text: str = field(repr=False)
    context_revision: int = 0

    def __post_init__(self) -> None:
        bounded_text(self.text, 8192, "text update")
        nonnegative_int(self.context_revision, "context_revision")


@dataclass(frozen=True, slots=True)
class VoicePcmFormat:
    """Raw mono signed PCM16 little endian. Adapters negotiate/resample below port."""

    sample_rate_hz: int = 24000

    def __post_init__(self) -> None:
        if type(self.sample_rate_hz) is not int or not 8000 <= self.sample_rate_hz <= 192000:
            raise ValueError("sample_rate_hz must be an integer between 8000 and 192000")


@dataclass(frozen=True, slots=True)
class VoiceAudioChunk:
    pcm: bytes = field(repr=False)
    format: VoicePcmFormat = VoicePcmFormat()

    def __post_init__(self) -> None:
        if not isinstance(self.pcm, bytes) or not self.pcm or len(self.pcm) % 2:
            raise ValueError("PCM chunks require nonempty complete PCM16 samples")
        if len(self.pcm) > self.format.sample_rate_hz * 2:
            raise ValueError("PCM chunks are bounded to one second")


@dataclass(frozen=True, slots=True)
class VoiceFrontendConfig:
    mode: VoiceModeConfig
    initial_context: VoiceContext = VoiceContext()
    instructions: str = field(default="", repr=False)
    input_format: VoicePcmFormat = VoicePcmFormat()

    def __post_init__(self) -> None:
        bounded_text(self.instructions, 65536, "instructions")


def bounded_json_object(text: str) -> None:
    """Immutable application tool data, never an SDK envelope or instruction."""
    bounded_text(text, 16384, "tool JSON")
    def reject_constant(value: str) -> None:
        raise ValueError("tool JSON requires finite values")
    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("tool JSON requires finite values")
        return number
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate tool JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(text, parse_constant=reject_constant, parse_float=finite_float, object_pairs_hook=pairs)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("tool data must be a bounded JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("tool data must be an object")


@dataclass(frozen=True, slots=True)
class VoiceToolResult:
    call_id: str
    result_json: str = field(repr=False)
    request_response: bool = True

    def __post_init__(self) -> None:
        bounded_text(self.call_id, 256, "call_id")
        if not self.call_id or self.call_id != self.call_id.strip() or not self.call_id.isprintable() or type(self.request_response) is not bool:
            raise ValueError("Tool result needs a call ID and boolean continuation")
        bounded_json_object(self.result_json)


@dataclass(frozen=True, slots=True)
class VoiceReflexRequest:
    transcript: str = field(repr=False)
    avoid: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        bounded_text(self.transcript, 8192, "reflex transcript")
        if not isinstance(self.avoid, tuple) or len(self.avoid) > 16:
            raise ValueError("Reflex avoidance must be a bounded tuple")
        for phrase in self.avoid:
            bounded_text(phrase, 512, "reflex avoidance")
