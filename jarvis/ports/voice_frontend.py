"""Canonical voice boundary. Existing RealtimeSession remains migration-only."""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from jarvis.domain.v2 import SpeechRequest
from jarvis.domain.voice_architecture import VoiceModelCapabilities
from jarvis.domain.voice_events import AssistantPlaybackEvidence, VoiceEvent
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceAudioChunk, VoiceFrontendConfig, VoiceOperation,
    VoiceOperationResult, VoiceStopReason, VoiceTextUpdate,
    VoiceToolResult, VoiceReflexRequest, VoiceContextMessage, VoiceConversationRequest,
)


@runtime_checkable
class VoiceFrontend(Protocol):
    """One incarnation, one event reader; controls may run concurrently with it.

    start configures and opens once. Repeated start must not open another remote
    session. stop is idempotent, bounded, safe during start, and stops local work
    without cancelling backend tasks. A requested close/socket loss is not proof
    of STOPPED: retain UNKNOWN_REAP_REQUIRED and provider identity until proven.
    Caller cancellation propagates CancelledError; implementations retain cleanup
    ownership, exposing unresolved state rather than silently orphaning a session.

    events() is a single-consumer iterator. Its cancellation/aclose releases the
    subscription, not the remote session. stop wakes a waiting reader, drains its
    terminal events and ends it, including uncertain stop; later reaping is owned
    by runtime. A stream ending by itself is not confirmation of provider close.
    Queues must be bounded; overflow is surfaced as failure, never silent loss of
    transcript/delegation/terminal events. One adapter reader normalizes transport
    messages, and runtime merges local playback evidence into canonical Core flow.

    Operations carry app correlation, never provider payloads. ACCEPTED means
    sent/queued only. Unsupported methods return UNSUPPORTED with stable code,
    even if another provider has superficially similar behavior. In particular,
    response-triggering context cannot masquerade as quiet context. Adapters must
    enforce provider token/format limits before sending; do not silently truncate.
    No method implicitly grants owner authorization or tool/action permission.
    """

    @property
    def state(self) -> FrontendState: ...

    @property
    def capabilities(self) -> VoiceModelCapabilities: ...

    async def start(self, config: VoiceFrontendConfig, *, operation: VoiceOperation) -> VoiceOperationResult: ...

    async def stop(self, reason: VoiceStopReason, *, operation: VoiceOperation) -> VoiceOperationResult: ...

    async def send_audio(self, chunk: VoiceAudioChunk, *, operation: VoiceOperation) -> VoiceOperationResult:
        """Upload admitted PCM; no provider ACK is implied. Keep pre-upload owner gate."""
        ...

    async def finish_input(self, *, operation: VoiceOperation) -> VoiceOperationResult:
        """Explicit manual input commit/response request; continuous duplex may reject as unsupported."""
        ...

    async def append_quiet_context(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult: ...

    async def append_spoken_result(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        """Request speech, possibly paraphrased; response is neither transcript nor playback."""
        ...

    async def feed_runtime_instruction(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult: ...

    async def cancel_speech(self, *, operation: VoiceOperation, playback: AssistantPlaybackEvidence | None = None) -> VoiceOperationResult:
        """Target correlated speech/output or all current output if absent.

        Runtime suppresses/drops local audio first; a provider ACK is not a local
        playback barrier. Cursor may permit truncation; unknown alignment must
        survive. This does not cancel the correlated backend task.
        """
        ...

    def events(self) -> AsyncIterator[VoiceEvent]: ...


@runtime_checkable
class VoiceCompatibilityControls(Protocol):
    """Typed migration controls needed by the existing Realtime conversation.

    Separate optional capability: other frontends need not invent tool/reflex
    behavior. Tool arguments/results remain data behind existing permissions.
    """
    async def send_tool_result(self, result: VoiceToolResult, *, operation: VoiceOperation) -> VoiceOperationResult: ...
    async def request_reflex(self, request: VoiceReflexRequest, *, operation: VoiceOperation) -> VoiceOperationResult: ...
    async def invalidate_unstarted_output(self, *, operation: VoiceOperation) -> VoiceOperationResult:
        """Cancel only the reserved local output; never a newer active response."""
        ...
    async def append_context_message(self, message: VoiceContextMessage, *, request_response: bool, operation: VoiceOperation) -> VoiceOperationResult: ...


@runtime_checkable
class ReservedSpeechOutput(Protocol):
    """Scheduler capability: exact output identity and pre-write invalidation.

    The runtime attaches its thread-safe admission token to the same identity.
    Cancellation targets only that reservation; it does not cancel backend work.
    """
    async def speak_reserved(self, request: "SpeechRequest", *, output_id: str) -> str: ...
    async def invalidate_unstarted_output(self, output_id: str) -> None: ...


@runtime_checkable
class VoiceConversationControl(Protocol):
    """Optional direct conversation capability; application admission is required."""
    async def request_conversation(self, request: VoiceConversationRequest, *, operation: VoiceOperation) -> VoiceOperationResult: ...
