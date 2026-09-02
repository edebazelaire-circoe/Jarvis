from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
import uuid

PROTOCOL_VERSION = 1
DEFAULT_DEVICE_ID = "windows-desktop"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class TurnKind(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_REQUEST = "tool_request"
    TOOL_RESULT = "tool_result"
    SYSTEM_EVENT = "system_event"
    ERROR = "error"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ScheduledStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MissedRunPolicy(StrEnum):
    NOTIFY_LATE = "notify_late"
    RUN_IF_RECENT = "run_if_recent"
    SKIP = "skip"
    REQUIRE_CONFIRMATION = "require_confirmation"


class NotificationState(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"
    FAILED = "failed"


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class VoiceLifecycleState(StrEnum):
    BACKGROUND = "background"
    ACTIVE = "active"
    CONNECTING = "connecting"
    ERROR = "error"


class AddressingDecision(StrEnum):
    ADDRESSED = "addressed"
    AMBIENT = "ambient"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class Device:
    device_id: str = DEFAULT_DEVICE_ID
    kind: str = "windows-desktop"
    display_name: str = "Windows desktop"
    capabilities: tuple[str, ...] = ()
    last_seen_at: datetime = field(default_factory=utc_now)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.device_id.strip():
            raise ValueError("device_id is required")
        _aware(self.last_seen_at)


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str = field(default_factory=new_id)
    status: ConversationStatus = ConversationStatus.ACTIVE
    originating_device_id: str = DEFAULT_DEVICE_ID
    current_device_id: str = DEFAULT_DEVICE_ID
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    summary: str = ""
    transport_session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.originating_device_id:
            raise ValueError("conversation id and originating device are required")
        _aware(self.created_at)
        _aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    id: str = field(default_factory=new_id)
    conversation_id: str = ""
    kind: TurnKind = TurnKind.USER
    content: str = ""
    created_at: datetime = field(default_factory=utc_now)
    correlation_id: str = field(default_factory=new_id)
    reference_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        _aware(self.created_at)


@dataclass(frozen=True, slots=True)
class Job:
    id: str = field(default_factory=new_id)
    kind: str = ""
    status: JobStatus = JobStatus.PENDING
    requested_by_conversation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    idempotency_key: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("job kind is required")
        _aware(self.created_at)
        for value in (self.started_at, self.completed_at):
            if value is not None:
                _aware(value)


@dataclass(frozen=True, slots=True)
class ScheduledItem:
    id: str = field(default_factory=new_id)
    kind: str = "reminder"
    status: ScheduledStatus = ScheduledStatus.ACTIVE
    payload: dict[str, Any] = field(default_factory=dict)
    next_fire_at: datetime = field(default_factory=utc_now)
    recurrence_seconds: int | None = None
    missed_run_policy: MissedRunPolicy = MissedRunPolicy.NOTIFY_LATE
    max_lateness_seconds: int | None = None
    last_fire_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    requested_by_conversation_id: str | None = None
    idempotency_key: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        _aware(self.next_fire_at)
        _aware(self.created_at)
        if self.last_fire_at is not None:
            _aware(self.last_fire_at)
        if self.recurrence_seconds is not None and self.recurrence_seconds <= 0:
            raise ValueError("recurrence_seconds must be positive")
        if self.missed_run_policy is MissedRunPolicy.RUN_IF_RECENT and not self.max_lateness_seconds:
            raise ValueError("RUN_IF_RECENT requires max_lateness_seconds")


@dataclass(frozen=True, slots=True)
class Notification:
    id: str = field(default_factory=new_id)
    summary: str = ""
    body: str = ""
    state: NotificationState = NotificationState.PENDING
    priority: NotificationPriority = NotificationPriority.NORMAL
    target_device_id: str = DEFAULT_DEVICE_ID
    originating_reference_id: str | None = None
    delivery_policy: str = "system_notification"
    created_at: datetime = field(default_factory=utc_now)
    delivered_at: datetime | None = None
    expires_at: datetime | None = None
    idempotency_key: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("notification summary is required")
        _aware(self.created_at)
        for value in (self.delivered_at, self.expires_at):
            if value is not None:
                _aware(value)


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    id: str
    kind: TurnKind
    created_at: datetime
    correlation_id: str
    conversation_id: str | None = None
    content: str | None = None
    reference_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _aware(self.created_at)


@dataclass(frozen=True, slots=True)
class ProtocolEnvelope:
    message_type: str
    payload: dict[str, Any]
    correlation_id: str = field(default_factory=new_id)
    protocol_version: int = PROTOCOL_VERSION
    device_id: str = DEFAULT_DEVICE_ID
    conversation_id: str | None = None

    def __post_init__(self) -> None:
        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol version: {self.protocol_version}")
        if not self.message_type:
            raise ValueError("message_type is required")


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return jsonable(asdict(value))
    return value
