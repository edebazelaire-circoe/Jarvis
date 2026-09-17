"""Storage-neutral types of the Conversation Event store (Slice 02).

Binding contract: `docs/conversation-events.md`, section "Storage". The port is
`jarvis.ports.v2.ConversationEventStore`; the SQLite adapter is
`jarvis/adapters/sqlite_conversation_events.py`.

Invariants carried by these types:

- the store **sequence** is the canonical order and the only cursor. It is
  assigned at append, strictly increasing, never reused (not even after a
  retention prune), and independent of producer clocks;
- a page reports how many stored rows it had to skip because they could not be
  decoded, so a damaged record is visible instead of silently shorter;
- every query is bounded (`MAX_EVENT_PAGE_LIMIT`, `MAX_SUMMARY_PAGE_LIMIT`,
  `MAX_APPEND_BATCH`); an out-of-range limit is a caller error;
- retention is disabled by default and can only ever remove events of a
  conversation that Core has closed, whose spans are all closed and which saw no
  store activity for `max_age`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from jarvis.domain.conversation_events import ConversationEvent
from jarvis.domain.voice_state import state_id

#: Same bound as the Core voice observation batch (1-32 encoded events).
MAX_APPEND_BATCH = 32
DEFAULT_EVENT_PAGE_LIMIT = 100
MAX_EVENT_PAGE_LIMIT = 500
DEFAULT_SUMMARY_PAGE_LIMIT = 50
MAX_SUMMARY_PAGE_LIMIT = 100
MAX_RETENTION_CONVERSATIONS_PER_RUN = 64

#: Envelope ids a lookup may filter on (each has a partial index). The
#: `conversation_id` has its own cursor query and is not listed.
LOOKUP_FIELDS = ("session_id", "turn_id", "correlation_id", "task_id", "work_id", "speech_id", "outcome_id",
                 "span_id")


class ConversationEventStoreError(RuntimeError):
    """The storage failed: the append (or read) was **not** acknowledged. Retry is safe."""


class AppendStatus(StrEnum):
    #: New event committed at `sequence`.
    APPENDED = "appended"
    #: Identical event already stored at `sequence`; nothing written.
    DUPLICATE = "duplicate"
    #: Same `event_id`, different (or unreadable) stored payload. The first copy
    #: at `sequence` is kept, a diagnostic is emitted, the producer is not failed.
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class AppendResult:
    event_id: str
    #: Sequence of the stored copy (the new row, or the first copy on duplicate/conflict).
    sequence: int
    status: AppendStatus


@dataclass(frozen=True, slots=True)
class StoredConversationEvent:
    sequence: int
    #: Core store clock read when `append*` was called, before the transaction
    #: (UTC, ms); not the commit instant. Retention age uses it, never producer clocks.
    recorded_at: datetime
    event: ConversationEvent


@dataclass(frozen=True, slots=True)
class ConversationEventPage:
    """Events in ascending sequence. Resume with `after_sequence=next_cursor`."""

    events: tuple[StoredConversationEvent, ...]
    #: Last scanned sequence (readable or not), or the request cursor when nothing matched.
    next_cursor: int
    has_more: bool
    #: Rows in the scanned window that could not be decoded (skipped, diagnosed).
    skipped_rows: int = 0


@dataclass(frozen=True, slots=True)
class ConversationEventSummary:
    """Activity of one conversation, or of one session inside it (`session_id` may be None)."""

    conversation_id: str
    session_id: str | None
    #: Raw stored row count, unreadable rows included (they are not decoded here).
    event_count: int
    first_sequence: int
    last_sequence: int
    #: Producer clocks (advisory across processes), min/max of `occurred_at`.
    first_occurred_at: datetime
    last_occurred_at: datetime
    last_recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationEventSummaryPage:
    summaries: tuple[ConversationEventSummary, ...]
    #: Conversations: pass as `before_sequence` (last_sequence of the last scanned row).
    #: Sessions: pass as `after_sequence` (first_sequence of the last scanned row). None when empty.
    next_cursor: int | None
    has_more: bool
    #: Scanned groups whose aggregated times do not parse (skipped, diagnosed).
    skipped_summaries: int = 0


@dataclass(frozen=True, slots=True)
class ConversationEventExtent:
    """Raw stored rows of one conversation and their sequence bounds (no row is decoded)."""

    stored_rows: int
    first_sequence: int
    last_sequence: int


class RetentionSkipReason(StrEnum):
    #: Conversation row missing, or status not `closed` (active history is never removed).
    NOT_CLOSED = "not_closed"
    #: A span opened in this conversation has no close yet (including a span
    #: orphaned by a crash: it blocks retention forever, never auto-closed).
    OPEN_SPAN = "open_span"
    #: A stored row has an unknown type, invalid JSON or an unparseable time.
    UNREADABLE = "unreadable"
    #: New events were stored after selection (e.g. during archiving).
    NEW_ACTIVITY = "new_activity"
    #: The archive hook raised: nothing is deleted without its archive.
    ARCHIVE_FAILED = "archive_failed"


@dataclass(frozen=True, slots=True)
class ConversationEventRetentionPolicy:
    """Prune events of closed, idle conversations. Disabled unless explicitly enabled."""

    enabled: bool = False
    max_age: timedelta = timedelta(days=180)
    max_conversations_per_run: int = 16

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("retention enabled must be a boolean")
        if not isinstance(self.max_age, timedelta) or self.max_age <= timedelta(0):
            raise ValueError("retention max_age must be a positive timedelta")
        check_limit(self.max_conversations_per_run, MAX_RETENTION_CONVERSATIONS_PER_RUN, "max_conversations_per_run")


@dataclass(frozen=True, slots=True)
class RetentionReport:
    enabled: bool
    #: Events whose conversation's last `recorded_at` is before this are eligible. None when disabled.
    cutoff: datetime | None
    #: (conversation_id, events deleted)
    pruned: tuple[tuple[str, int], ...] = ()
    #: Selected this run but not pruned (state changed, archive failed).
    skipped: tuple[tuple[str, RetentionSkipReason], ...] = ()
    #: Closed idle conversations excluded before selection, so they never
    #: consume the per-run budget: open span / unreadable row counts.
    blocked_open_span: int = 0
    blocked_unreadable: int = 0


def check_limit(value: object, maximum: int, name: str = "limit") -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")


def check_cursor(value: object, name: str = "after_sequence") -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer sequence")


def check_lookup(field: object, value: object) -> None:
    if field not in LOOKUP_FIELDS:
        raise ValueError(f"lookup field must be one of {', '.join(LOOKUP_FIELDS)}")
    state_id(value, str(field))
