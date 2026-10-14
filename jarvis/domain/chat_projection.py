"""Chat projection of Conversation Events (handoff jarvis-unified-chat-and-board-drop, Slice 02).

Binding contract: `docs/chat.md`, section "Projection". The Chat is a view of
the existing ledger, never a second transcript: this module stores nothing and
reads nothing but the stored events it is given.

Two layers, forced by the stream (a promotion arrives after the cursor has
passed the uncertain turn):

- `is_chat_event`, the **stateless** filter Core applies to a page
  (`projection=chat`, Slice 05): three types only;
- `project_chat`, the reference implementation of the **stateful** rules the
  browser model (`jarvis/runtime/control_center_chat_model.js`) applies to the
  pages it accumulates. Both are played on `tests/fixtures/chat_projection/cases.json`
  and must give the same items.

Invariants: pure domain, no clock and no time heuristic (order is the store
`sequence`), items keyed by `event_id` (first copy wins on a replayed page),
only the requested conversation counts.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from jarvis.domain.conversation_event_store import StoredConversationEvent
from jarvis.domain.conversation_events import ConversationEvent, ConversationEventType as T, ConversationItem
from jarvis.domain.conversation_transcript import TranscriptEntry, collapse_published_messages

#: Value of the `projection` query parameter (`docs/chat.md`, "Reading").
CHAT_PROJECTION = "chat"
CHAT_EVENT_TYPES = frozenset({T.USER_TRANSCRIPT_ACCEPTED, T.BRAIN_MESSAGE_PUBLISHED, T.BRAIN_TURN_FAILED})
#: `attributes.addressing` of a user turn the Chat may show; any other value is excluded by prudence.
_SHOWN_ADDRESSING = frozenset({None, "addressed", "uncertain"})
_UNCERTAIN = "uncertain"
#: `failure_code` of a `brain.turn.failed` that carries no `attributes.code`: the
#: bubble still leaves "pending" (bounded failure), the code says nothing more.
UNKNOWN_FAILURE_CODE = "brain_turn_failed"


@dataclass(frozen=True, slots=True)
class ChatItem:
    """One Chat bubble; exactly the nine fields of `docs/chat.md` "Projection output"."""

    role: Literal["user", "brain"]
    event_id: str
    sequence: int
    correlation_id: str | None
    text: str | None
    kind: str | None
    status: str | None
    failure_code: str | None
    collapsed_event_ids: tuple[str, ...] = ()


def is_chat_event(event: ConversationEvent) -> bool:
    """Stateless filter: may this event matter to the Chat (shown, promoting or failing a bubble)?"""
    if event.event_type is T.USER_TRANSCRIPT_ACCEPTED:
        return event.attributes.get("addressing") in _SHOWN_ADDRESSING
    return event.event_type in CHAT_EVENT_TYPES


def _failure_code(event: ConversationEvent) -> str:
    code = event.attributes.get("code")
    return code if isinstance(code, str) and code else UNKNOWN_FAILURE_CODE


def _entry(event: ConversationEvent) -> TranscriptEntry:
    """A publication as the transcript sees it, so the folding rule is reused, not copied."""
    item = ConversationItem(event.event_id, event.actor, event.event_type, "published", event.visibility,
                            event.occurred_at, event.occurred_at, event.content, None, (event.event_id,))
    return TranscriptEntry(item, event.correlation_id, event.producer, event.attributes)


def project_chat(stored_events: Iterable[StoredConversationEvent], *,
                 conversation_id: str) -> tuple[ChatItem, ...]:
    """Chat items of `conversation_id`, ordered by `sequence`, from stored events in any page order.

    Events of other conversations are dropped before any rule runs: they never
    promote, fold or fail a bubble here. A replayed event (same `event_id`)
    keeps its first copy.
    """
    unique: dict[str, StoredConversationEvent] = {}
    for stored in stored_events:
        if stored.event.conversation_id == conversation_id and is_chat_event(stored.event):
            unique.setdefault(stored.event.event_id, stored)
    rows = sorted(unique.values(), key=lambda s: (s.sequence, s.event.event_id))
    published = {s.event.correlation_id for s in rows
                 if s.event.event_type is T.BRAIN_MESSAGE_PUBLISHED and s.event.correlation_id is not None}
    # The latest failure of a correlation is its status.
    failures = {s.event.correlation_id: _failure_code(s.event) for s in rows
                if s.event.event_type is T.BRAIN_TURN_FAILED}
    folded = {entry.item.item_id: tuple(c.item_id for c in entry.collapsed)
              for entry in collapse_published_messages(
                  _entry(s.event) for s in rows if s.event.event_type is T.BRAIN_MESSAGE_PUBLISHED)}
    items: list[ChatItem] = []
    for stored in rows:
        event = stored.event
        if event.event_type is T.USER_TRANSCRIPT_ACCEPTED:
            # An uncertain turn is shown, at its own sequence, once the Brain answered its correlation.
            if event.attributes.get("addressing") == _UNCERTAIN and event.correlation_id not in published:
                continue
            failure = failures.get(event.correlation_id) if event.correlation_id is not None else None
            items.append(ChatItem("user", event.event_id, stored.sequence, event.correlation_id, event.content,
                                  None, None, failure))
        elif event.event_type is T.BRAIN_MESSAGE_PUBLISHED and event.event_id in folded:
            items.append(ChatItem("brain", event.event_id, stored.sequence, event.correlation_id, event.content,
                                  event.attributes.get("kind"), event.attributes.get("status"), None,
                                  folded[event.event_id]))
    return tuple(items)
