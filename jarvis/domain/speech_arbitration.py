from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class SpeechOutputOwner(StrEnum):
    """Component that owns the audible output reservation.

    Ownership is intentionally about speech/output only. Brain work is not
    owned or cancelled by this state machine.
    """

    BRAIN = "brain"
    SURFACE_REFLEX = "surface_reflex"
    DIRECT_CONVERSATION = "direct_conversation"


class SpeechLifecycleState(StrEnum):
    RESERVED = "reserved"
    GENERATING = "generating"
    PLAYING = "playing"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SpeechTerminalReason(StrEnum):
    """Stable business reasons for terminal speech transitions.

    Provider statuses are deliberately absent. A provider callback is evidence,
    not a business reason; callers must classify why the speech ended.
    """

    OUTPUT_COMPLETED = "output_completed"
    USER_BARGE_IN = "user_barge_in"
    BRAIN_SUPERSEDED = "brain_superseded"
    REFLEX_PREEMPTED = "reflex_preempted"
    VOICE_BACKGROUND = "voice_background"
    EXPIRED = "expired"
    START_CANCELLED = "start_cancelled"
    START_FAILED = "start_failed"
    PROVIDER_ERROR = "provider_error"
    OUTPUT_STALLED = "output_stalled"


TERMINAL_STATES = frozenset(
    {
        SpeechLifecycleState.COMPLETED,
        SpeechLifecycleState.INTERRUPTED,
        SpeechLifecycleState.CANCELLED,
        SpeechLifecycleState.FAILED,
    }
)

_REASON_STATE = {
    SpeechTerminalReason.OUTPUT_COMPLETED: SpeechLifecycleState.COMPLETED,
    SpeechTerminalReason.USER_BARGE_IN: SpeechLifecycleState.INTERRUPTED,
    SpeechTerminalReason.BRAIN_SUPERSEDED: SpeechLifecycleState.CANCELLED,
    SpeechTerminalReason.REFLEX_PREEMPTED: SpeechLifecycleState.CANCELLED,
    SpeechTerminalReason.VOICE_BACKGROUND: SpeechLifecycleState.CANCELLED,
    SpeechTerminalReason.EXPIRED: SpeechLifecycleState.CANCELLED,
    SpeechTerminalReason.START_CANCELLED: SpeechLifecycleState.CANCELLED,
    SpeechTerminalReason.START_FAILED: SpeechLifecycleState.FAILED,
    SpeechTerminalReason.PROVIDER_ERROR: SpeechLifecycleState.FAILED,
    SpeechTerminalReason.OUTPUT_STALLED: SpeechLifecycleState.FAILED,
}

_ALLOWED_TRANSITIONS = {
    SpeechLifecycleState.RESERVED: frozenset(
        {
            SpeechLifecycleState.GENERATING,
            SpeechLifecycleState.CANCELLED,
            SpeechLifecycleState.FAILED,
        }
    ),
    SpeechLifecycleState.GENERATING: frozenset(
        {
            SpeechLifecycleState.PLAYING,
            SpeechLifecycleState.COMPLETED,
            SpeechLifecycleState.INTERRUPTED,
            SpeechLifecycleState.CANCELLED,
            SpeechLifecycleState.FAILED,
        }
    ),
    SpeechLifecycleState.PLAYING: frozenset(
        {
            SpeechLifecycleState.COMPLETED,
            SpeechLifecycleState.INTERRUPTED,
            SpeechLifecycleState.FAILED,
        }
    ),
    SpeechLifecycleState.COMPLETED: frozenset(),
    SpeechLifecycleState.INTERRUPTED: frozenset(),
    SpeechLifecycleState.CANCELLED: frozenset(),
    SpeechLifecycleState.FAILED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class SpeechIdentity:
    """Stable identities that join scheduler, provider and Core evidence."""

    output_id: str
    owner: SpeechOutputOwner
    speech_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.output_id or self.output_id.strip() != self.output_id:
            raise ValueError("output_id must be a non-empty stable identifier")
        if self.speech_id is not None and not self.speech_id:
            raise ValueError("speech_id must be non-empty when present")
        if self.correlation_id is not None and not self.correlation_id:
            raise ValueError("correlation_id must be non-empty when present")


@dataclass(frozen=True, slots=True)
class SpeechLifecycle:
    """Pure lifecycle record for one audible output.

    The record never owns Brain work. In particular, USER_BARGE_IN terminates
    speech only; no transition in this module can cancel the underlying work.
    """

    identity: SpeechIdentity
    state: SpeechLifecycleState = SpeechLifecycleState.RESERVED
    terminal_reason: SpeechTerminalReason | None = None
    provider_status: str | None = None
    played_ms: int = 0

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def affects_brain_work(self) -> bool:
        return False

    def advance(
        self,
        state: SpeechLifecycleState,
        *,
        reason: SpeechTerminalReason | None = None,
        played_ms: int | None = None,
    ) -> SpeechLifecycle:
        """Return the next lifecycle state, rejecting ambiguous transitions."""

        if self.terminal:
            if state is self.state and reason is self.terminal_reason:
                return self
            raise ValueError(
                f"terminal speech {self.identity.output_id} cannot transition "
                f"from {self.state.value} to {state.value}"
            )
        if state is self.state and reason is None and played_ms is None:
            return self
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid speech transition: {self.state.value} -> {state.value}")

        if state in TERMINAL_STATES:
            if reason is None:
                raise ValueError("every terminal speech transition requires an explicit reason")
            expected = _REASON_STATE.get(reason)
            if expected is not state:
                raise ValueError(
                    f"terminal reason {reason.value} requires state "
                    f"{expected.value if expected is not None else 'unknown'}, not {state.value}"
                )
        elif reason is not None:
            raise ValueError("non-terminal speech transitions cannot carry a terminal reason")

        next_played = self.played_ms if played_ms is None else played_ms
        if isinstance(next_played, bool) or next_played < 0:
            raise ValueError("played_ms must be a non-negative integer")
        return replace(self, state=state, terminal_reason=reason, played_ms=int(next_played))

    def observe_provider_status(self, status: str | None) -> SpeechLifecycle:
        """Record provider evidence without allowing it to choose business truth."""

        normalized = status.strip() if isinstance(status, str) and status.strip() else None
        if normalized == self.provider_status:
            return self
        return replace(self, provider_status=normalized)

    def trace_fields(self) -> dict[str, object]:
        return {
            "speech_id": self.identity.speech_id,
            "output_id": self.identity.output_id,
            "correlation_id": self.identity.correlation_id,
            "owner": self.identity.owner.value,
            "speech_state": self.state.value,
            "terminal_reason": self.terminal_reason.value if self.terminal_reason is not None else None,
            "provider_status": self.provider_status,
            "played_ms": self.played_ms,
            "brain_work_cancelled": False,
        }


class SpeechArbiter:
    """Authoritative in-memory lifecycle ledger for the active voice surface.

    The scheduler remains the runtime owner. This class centralizes the pure
    transition rules so bridge/provider callbacks cannot each invent terminal
    semantics. Duplicate registrations and duplicate callbacks are idempotent;
    contradictory identity or terminal transitions fail loudly.
    """

    def __init__(self) -> None:
        self._by_output: dict[str, SpeechLifecycle] = {}

    def register(self, identity: SpeechIdentity) -> SpeechLifecycle:
        current = self._by_output.get(identity.output_id)
        if current is not None:
            if current.identity != identity:
                raise ValueError(f"output_id {identity.output_id} was reused with different identity")
            return current
        lifecycle = SpeechLifecycle(identity)
        self._by_output[identity.output_id] = lifecycle
        return lifecycle

    def get(self, output_id: str) -> SpeechLifecycle | None:
        return self._by_output.get(output_id)

    def advance(
        self,
        output_id: str,
        state: SpeechLifecycleState,
        *,
        reason: SpeechTerminalReason | None = None,
        played_ms: int | None = None,
    ) -> SpeechLifecycle:
        current = self._require(output_id)
        updated = current.advance(state, reason=reason, played_ms=played_ms)
        self._by_output[output_id] = updated
        return updated

    def observe_provider_status(self, output_id: str, status: str | None) -> SpeechLifecycle:
        current = self._require(output_id)
        updated = current.observe_provider_status(status)
        self._by_output[output_id] = updated
        return updated

    def _require(self, output_id: str) -> SpeechLifecycle:
        try:
            return self._by_output[output_id]
        except KeyError as exc:
            raise KeyError(f"unknown speech output_id: {output_id}") from exc
