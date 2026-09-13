"""Provider-neutral durable ownership for possibly billable Live sessions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import math


SCHEMA_VERSION = 1
MAX_LEASE_SECONDS = 300.0
MAX_USAGE_SECONDS = 315_576_000.0  # Ten years; rejects corrupt/non-finite counters.


class LiveLifecycleState(StrEnum):
    STARTING = "starting"
    ACTIVE = "active"
    IDLE_CANDIDATE = "idle_candidate"
    STOPPING = "stopping"
    STOPPED = "stopped"
    UNKNOWN_REAP_REQUIRED = "unknown_reap_required"


class LiveOwnerKind(StrEnum):
    PRIMARY = "primary"
    REAPER = "reaper"


class LiveCloseEvidence(StrEnum):
    PROVIDER_SESSION_CLOSED = "provider_session_closed"
    START_NOT_SENT = "start_not_sent"


class LiveLifecycleOperation(StrEnum):
    RESERVE = "reserve"
    MARK_START = "mark_start"
    BIND = "bind"
    HEARTBEAT = "heartbeat"
    TRANSITION = "transition"
    USAGE = "usage"
    CLAIM_REAP = "claim_reap"
    FINALIZE = "finalize"


NONTERMINAL_LIVE_STATES = frozenset(LiveLifecycleState) - {LiveLifecycleState.STOPPED}
_TRANSITIONS = {
    LiveLifecycleState.STARTING: {
        LiveLifecycleState.ACTIVE, LiveLifecycleState.STOPPING,
        LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
    },
    LiveLifecycleState.ACTIVE: {
        LiveLifecycleState.IDLE_CANDIDATE, LiveLifecycleState.STOPPING,
        LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
    },
    LiveLifecycleState.IDLE_CANDIDATE: {
        LiveLifecycleState.ACTIVE, LiveLifecycleState.STOPPING,
        LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
    },
    LiveLifecycleState.STOPPING: {
        LiveLifecycleState.STOPPED, LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
    },
    LiveLifecycleState.UNKNOWN_REAP_REQUIRED: {
        LiveLifecycleState.STOPPING, LiveLifecycleState.STOPPED,
    },
    LiveLifecycleState.STOPPED: set(),
}


class LiveLifecycleConflict(RuntimeError):
    """Stable conflict that callers may retry only with unchanged identity."""

    CODES = {
        "live_lease_held", "live_identity_conflict", "live_stale_owner",
        "live_stale_revision", "live_invalid_transition", "live_reap_not_eligible",
        "live_close_unconfirmed", "live_session_not_found", "live_core_not_accepting",
    }

    def __init__(self, code: str) -> None:
        if code not in self.CODES:
            raise ValueError("invalid Live lifecycle conflict code")
        self.code = code
        super().__init__(code)


def live_id(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 128
            or value.strip() != value or not value.isprintable()):
        raise ValueError(f"invalid {name}")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"invalid {name}") from exc
    return value


def live_time(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"invalid {name}")
    try:
        if value.utcoffset() is None:
            raise ValueError(f"invalid {name}")
        value = value.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not 2000 <= value.year <= 2200:
        raise ValueError(f"invalid {name}")
    return value


def live_seconds(value: object, name: str, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {name}")
    try:
        finite = math.isfinite(value)
    except OverflowError as exc:
        raise ValueError(f"invalid {name}") from exc
    if not finite or not 0 <= value <= MAX_USAGE_SECONDS:
        raise ValueError(f"invalid {name}")
    return float(value)


def parse_live_time(value: object, name: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError(f"invalid {name}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc
    return live_time(parsed, name)


@dataclass(frozen=True, slots=True)
class LiveSessionRecord:
    session_id: str
    provider_session_id: str | None
    owner_incarnation_id: str
    owner_epoch: int
    owner_kind: LiveOwnerKind
    state: LiveLifecycleState
    start_may_have_been_sent: bool
    heartbeat_at: datetime
    lease_deadline: datetime
    created_at: datetime
    updated_at: datetime
    state_entered_at: datetime
    activated_at: datetime | None
    stopped_at: datetime | None
    active_seconds: float
    provider_usage_seconds: float | None
    provider_usage_final: bool
    close_reason: str | None
    close_evidence: LiveCloseEvidence | None
    last_operation: LiveLifecycleOperation
    revision: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        live_id(self.session_id, "session_id")
        if self.provider_session_id is not None:
            live_id(self.provider_session_id, "provider_session_id")
        live_id(self.owner_incarnation_id, "owner_incarnation_id")
        if type(self.owner_epoch) is not int or not 1 <= self.owner_epoch <= 2**63 - 1:
            raise ValueError("invalid owner_epoch")
        if not isinstance(self.owner_kind, LiveOwnerKind):
            raise ValueError("invalid owner_kind")
        if not isinstance(self.state, LiveLifecycleState):
            raise ValueError("invalid Live lifecycle state")
        if type(self.start_may_have_been_sent) is not bool:
            raise ValueError("invalid start_may_have_been_sent")
        heartbeat = live_time(self.heartbeat_at, "heartbeat_at")
        deadline = live_time(self.lease_deadline, "lease_deadline")
        created = live_time(self.created_at, "created_at")
        updated = live_time(self.updated_at, "updated_at")
        entered = live_time(self.state_entered_at, "state_entered_at")
        if deadline < heartbeat or (deadline - heartbeat).total_seconds() > MAX_LEASE_SECONDS:
            raise ValueError("invalid lease interval")
        if not created <= entered <= updated or heartbeat > updated:
            raise ValueError("invalid lifecycle timestamps")
        for value, name in ((self.activated_at, "activated_at"), (self.stopped_at, "stopped_at")):
            if value is not None:
                live_time(value, name)
                if not created <= value <= updated:
                    raise ValueError(f"invalid {name}")
        live_seconds(self.active_seconds, "active_seconds")
        live_seconds(self.provider_usage_seconds, "provider_usage_seconds", optional=True)
        if type(self.provider_usage_final) is not bool:
            raise ValueError("invalid provider_usage_final")
        if self.close_reason is not None:
            live_id(self.close_reason, "close_reason")
        if self.close_evidence is not None and not isinstance(self.close_evidence, LiveCloseEvidence):
            raise ValueError("invalid close_evidence")
        if not isinstance(self.last_operation, LiveLifecycleOperation):
            raise ValueError("invalid last_operation")
        if type(self.revision) is not int or not 1 <= self.revision <= 2**63 - 1:
            raise ValueError("invalid revision")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported Live lifecycle schema")
        if self.state in {LiveLifecycleState.ACTIVE, LiveLifecycleState.IDLE_CANDIDATE}:
            if (not self.start_may_have_been_sent or self.provider_session_id is None
                    or self.activated_at is None):
                raise ValueError("active Live state requires provider identity and activation time")
        if self.provider_usage_final and self.provider_usage_seconds is None:
            raise ValueError("final usage requires provider seconds")
        if self.provider_usage_final and self.state is not LiveLifecycleState.STOPPED:
            raise ValueError("final provider usage requires STOPPED")
        if self.state in {
            LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
            LiveLifecycleState.STOPPED,
        } and self.close_reason is None:
            raise ValueError("closing or uncertain state requires close_reason")
        if self.state is LiveLifecycleState.STOPPED:
            provider_closed = (
                self.close_evidence is LiveCloseEvidence.PROVIDER_SESSION_CLOSED
                and self.start_may_have_been_sent and self.provider_session_id is not None
                and self.provider_usage_final and self.provider_usage_seconds is not None
            )
            never_started = (
                self.close_evidence is LiveCloseEvidence.START_NOT_SENT
                and not self.start_may_have_been_sent and self.provider_session_id is None
                and not self.provider_usage_final and self.provider_usage_seconds is None
                and self.active_seconds == 0
            )
            if self.stopped_at is None or self.close_reason is None or not (provider_closed or never_started):
                raise ValueError("STOPPED requires provider receipt or durable not-started proof")
        elif self.stopped_at is not None:
            raise ValueError("only STOPPED has stopped_at")
        elif self.close_evidence is not None:
            raise ValueError("only STOPPED has close_evidence")

    def to_payload(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "provider_session_id": self.provider_session_id,
            "owner_incarnation_id": self.owner_incarnation_id,
            "owner_epoch": self.owner_epoch,
            "owner_kind": self.owner_kind.value,
            "state": self.state.value,
            "start_may_have_been_sent": self.start_may_have_been_sent,
            "heartbeat_at": self.heartbeat_at.isoformat(),
            "lease_deadline": self.lease_deadline.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "state_entered_at": self.state_entered_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "active_seconds": self.active_seconds,
            "provider_usage_seconds": self.provider_usage_seconds,
            "provider_usage_final": self.provider_usage_final,
            "close_reason": self.close_reason,
            "close_evidence": self.close_evidence.value if self.close_evidence else None,
            "last_operation": self.last_operation.value,
            "revision": self.revision,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, value: object) -> LiveSessionRecord:
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("invalid Live session record fields")
        fields = dict(value)
        fields["state"] = LiveLifecycleState(fields["state"])
        fields["owner_kind"] = LiveOwnerKind(fields["owner_kind"])
        fields["close_evidence"] = (
            None if fields["close_evidence"] is None else LiveCloseEvidence(fields["close_evidence"])
        )
        fields["last_operation"] = LiveLifecycleOperation(fields["last_operation"])
        for name in ("heartbeat_at", "lease_deadline", "created_at", "updated_at", "state_entered_at"):
            fields[name] = parse_live_time(fields[name], name)
        for name in ("activated_at", "stopped_at"):
            fields[name] = None if fields[name] is None else parse_live_time(fields[name], name)
        return cls(**fields)

    def next(self, **changes: object) -> LiveSessionRecord:
        return replace(self, revision=self.revision + 1, **changes)

    def permits(self, target: LiveLifecycleState) -> bool:
        return target in _TRANSITIONS[self.state]
