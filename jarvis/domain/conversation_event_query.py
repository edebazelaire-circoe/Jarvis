"""Wire contract of the Conversation Event query API (Slice 04).

Binding contract: `docs/conversation-events.md`, section "Query and live API".
Core serves the stored log over authenticated `GET /v1/conversation-events...`
routes; the Control Center proxies them to the browser as `/api/conversations...`.
Both sides parse parameters and encode pages with this module, so the browser,
the Control Center and Core read one shape.

Invariants:

- a page carries the events **exactly as stored** (codec output) with their
  store `sequence` and `recorded_at`; the cursor is the store sequence
  (`next_cursor` = last scanned sequence, `has_more`, `skipped_rows`), never a
  producer clock;
- a visibility filter is applied after the scan: a filtered page can hold fewer
  events than `limit`, even none, while `next_cursor` still advances. A consumer
  always resumes from `next_cursor`, so reload and live polling converge on the
  same event set;
- query parameters are strict: unknown or repeated names, non-decimal numbers,
  out-of-range limits, invalid ids are a `ValueError` whose message names the
  parameter and the rule, never the offending value;
- decoding a response is strict (exact keys, codec decode of every event,
  ascending sequences): a Core answer out of contract is a `ValueError`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
import re
from typing import Any

from jarvis.domain.conversation_event_store import (
    DEFAULT_EVENT_PAGE_LIMIT, DEFAULT_SUMMARY_PAGE_LIMIT, LOOKUP_FIELDS, MAX_EVENT_PAGE_LIMIT, MAX_SUMMARY_PAGE_LIMIT,
    ConversationEventPage, ConversationEventSummary, ConversationEventSummaryPage, StoredConversationEvent,
)
from jarvis.domain.conversation_events import (
    ConversationEventError, ConversationVisibility, decode_conversation_event, encode_conversation_event,
    format_event_time, parse_event_time,
)
from jarvis.domain.conversation_transcript import TranscriptMode, check_utc_offset
from jarvis.domain.voice_state import state_id

QUERY_SCHEMA_VERSION = 1
#: Long-poll bound of `GET .../conversation-events?wait_ms=`: the request returns
#: as soon as the scan advances, or after at most this many milliseconds.
MAX_WAIT_MS = 25_000
#: Largest cursor accepted (SQLite INTEGER PRIMARY KEY range).
MAX_SEQUENCE = 2**63 - 1

_EVENT_ID = re.compile(r"cev-[0-9a-f]{64}")
_DECIMAL = re.compile(r"[0-9]{1,19}")
_SIGNED = re.compile(r"-?[0-9]{1,4}")
_PAGE_FIELDS = frozenset({"schema_version", "events", "next_cursor", "has_more", "skipped_rows"})
_STORED_FIELDS = frozenset({"sequence", "recorded_at", "event"})
_SUMMARY_PAGE_FIELDS = frozenset({"schema_version", "summaries", "next_cursor", "has_more", "skipped_summaries"})
_SUMMARY_FIELDS = frozenset({"conversation_id", "session_id", "event_count", "first_sequence", "last_sequence",
                             "first_occurred_at", "last_occurred_at", "last_recorded_at"})
_EVENT_FIELDS = frozenset({"schema_version", "sequence", "recorded_at", "event"})

#: Allowed query parameters per route (Core and Control Center share them).
CONVERSATIONS_PARAMS = frozenset({"before_sequence", "limit"})
SESSIONS_PARAMS = frozenset({"conversation_id", "after_sequence", "limit"})
EVENTS_PARAMS = frozenset({"conversation_id", "after_sequence", "limit", "visibility", "wait_ms"})
LOOKUP_PARAMS = frozenset({"field", "value", "conversation_id", "after_sequence", "limit", "visibility"})
#: Slice 06 projections (search parameters: `conversation_event_search.SEARCH_PARAMS`).
TRANSCRIPT_PARAMS = frozenset({"conversation_id", "mode", "utc_offset_minutes"})
EXPORT_PARAMS = frozenset({"conversation_id"})


# ----------------------------------------------------------------- parameters

def query_params(pairs: Iterable[tuple[str, str]], allowed: frozenset[str]) -> dict[str, str]:
    """Single-valued parameters among `allowed`. Unknown names are not echoed (caller text)."""
    params: dict[str, str] = {}
    for name, value in pairs:
        if name not in allowed:
            raise ValueError(f"unexpected query parameter; allowed: {', '.join(sorted(allowed))}")
        if name in params:
            raise ValueError(f"query parameter {name} must not be repeated")
        params[name] = value
    return params


def int_param(params: Mapping[str, str], name: str, *, default: int | None, minimum: int,
              maximum: int) -> int | None:
    raw = params.get(name)
    if raw is None:
        return default
    if not _DECIMAL.fullmatch(raw) or not minimum <= int(raw) <= maximum:
        raise ValueError(f"{name} must be a decimal integer between {minimum} and {maximum}")
    return int(raw)


def id_param(params: Mapping[str, str], name: str, *, required: bool) -> str | None:
    raw = params.get(name)
    if raw is None:
        if required:
            raise ValueError(f"{name} is required")
        return None
    state_id(raw, name)  # also refuses lone surrogates (not printable)
    return raw


def visibility_param(params: Mapping[str, str]) -> ConversationVisibility | None:
    raw = params.get("visibility")
    if raw is None:
        return None
    try:
        return ConversationVisibility(raw)
    except ValueError:
        raise ValueError(f"visibility must be one of {', '.join(v.value for v in ConversationVisibility)}") from None


def lookup_field_param(params: Mapping[str, str]) -> str:
    raw = params.get("field")
    if raw not in LOOKUP_FIELDS:
        raise ValueError(f"field must be one of {', '.join(LOOKUP_FIELDS)}")
    return raw


def check_event_id(value: object) -> str:
    if not isinstance(value, str) or not _EVENT_ID.fullmatch(value):
        raise ValueError("event_id must match cev-<64 lowercase hex>")
    return value


def conversations_query(params: Mapping[str, str]) -> dict[str, Any]:
    return {"before_sequence": int_param(params, "before_sequence", default=None, minimum=0, maximum=MAX_SEQUENCE),
            "limit": int_param(params, "limit", default=DEFAULT_SUMMARY_PAGE_LIMIT, minimum=1,
                               maximum=MAX_SUMMARY_PAGE_LIMIT)}


def sessions_query(params: Mapping[str, str]) -> dict[str, Any]:
    return {"conversation_id": id_param(params, "conversation_id", required=True),
            "after_sequence": int_param(params, "after_sequence", default=0, minimum=0, maximum=MAX_SEQUENCE),
            "limit": int_param(params, "limit", default=DEFAULT_SUMMARY_PAGE_LIMIT, minimum=1,
                               maximum=MAX_SUMMARY_PAGE_LIMIT)}


def events_query(params: Mapping[str, str]) -> dict[str, Any]:
    return {"conversation_id": id_param(params, "conversation_id", required=True),
            "after_sequence": int_param(params, "after_sequence", default=0, minimum=0, maximum=MAX_SEQUENCE),
            "limit": int_param(params, "limit", default=DEFAULT_EVENT_PAGE_LIMIT, minimum=1,
                               maximum=MAX_EVENT_PAGE_LIMIT),
            "visibility": visibility_param(params),
            "wait_ms": int_param(params, "wait_ms", default=0, minimum=0, maximum=MAX_WAIT_MS)}


def lookup_query(params: Mapping[str, str]) -> dict[str, Any]:
    field = lookup_field_param(params)
    return {"field": field, "value": id_param(params, "value", required=True),
            "conversation_id": id_param(params, "conversation_id", required=False),
            "after_sequence": int_param(params, "after_sequence", default=0, minimum=0, maximum=MAX_SEQUENCE),
            "limit": int_param(params, "limit", default=DEFAULT_EVENT_PAGE_LIMIT, minimum=1,
                               maximum=MAX_EVENT_PAGE_LIMIT),
            "visibility": visibility_param(params)}


def transcript_query(params: Mapping[str, str]) -> dict[str, Any]:
    raw = params.get("mode", TranscriptMode.PLAIN.value)
    try:
        mode = TranscriptMode(raw)
    except ValueError:
        raise ValueError(f"mode must be one of {', '.join(m.value for m in TranscriptMode)}") from None
    offset = params.get("utc_offset_minutes", "0")
    if not _SIGNED.fullmatch(offset):
        check_utc_offset(None)  # raises the rule message, never the value
    return {"conversation_id": id_param(params, "conversation_id", required=True), "mode": mode,
            "utc_offset_minutes": check_utc_offset(int(offset))}


def export_query(params: Mapping[str, str]) -> dict[str, Any]:
    return {"conversation_id": id_param(params, "conversation_id", required=True)}


def filter_visibility(page: ConversationEventPage, visibility: ConversationVisibility | None) -> ConversationEventPage:
    """Keep only `visibility` events; cursor, `has_more` and `skipped_rows` describe the scan, unchanged."""
    if visibility is None:
        return page
    return replace(page, events=tuple(item for item in page.events if item.event.visibility is visibility))


# ------------------------------------------------------------------- encoding

def encode_stored_event(stored: StoredConversationEvent) -> dict[str, Any]:
    return {"sequence": stored.sequence, "recorded_at": format_event_time(stored.recorded_at),
            "event": encode_conversation_event(stored.event)}


def encode_event_response(stored: StoredConversationEvent) -> dict[str, Any]:
    return {"schema_version": QUERY_SCHEMA_VERSION, **encode_stored_event(stored)}


def encode_event_page(page: ConversationEventPage) -> dict[str, Any]:
    return {"schema_version": QUERY_SCHEMA_VERSION, "events": [encode_stored_event(item) for item in page.events],
            "next_cursor": page.next_cursor, "has_more": page.has_more, "skipped_rows": page.skipped_rows}


def _encode_summary(summary: ConversationEventSummary) -> dict[str, Any]:
    return {"conversation_id": summary.conversation_id, "session_id": summary.session_id,
            "event_count": summary.event_count, "first_sequence": summary.first_sequence,
            "last_sequence": summary.last_sequence,
            "first_occurred_at": format_event_time(summary.first_occurred_at),
            "last_occurred_at": format_event_time(summary.last_occurred_at),
            "last_recorded_at": format_event_time(summary.last_recorded_at)}


def encode_summary_page(page: ConversationEventSummaryPage) -> dict[str, Any]:
    return {"schema_version": QUERY_SCHEMA_VERSION, "summaries": [_encode_summary(item) for item in page.summaries],
            "next_cursor": page.next_cursor, "has_more": page.has_more, "skipped_summaries": page.skipped_summaries}


# ------------------------------------------------------------------- decoding

def _object(payload: object, fields: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ValueError(f"{name} must have exactly the fields {', '.join(sorted(fields))}")
    if "schema_version" in fields and (type(payload["schema_version"]) is not int
                                       or payload["schema_version"] != QUERY_SCHEMA_VERSION):
        raise ValueError(f"{name}.schema_version must be {QUERY_SCHEMA_VERSION}")
    return payload


def _count(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _decode_stored(payload: object, name: str, fields: frozenset[str] = _STORED_FIELDS) -> StoredConversationEvent:
    item = _object(payload, fields, name)
    try:
        event = decode_conversation_event(item["event"])
        recorded_at = parse_event_time(item["recorded_at"], f"{name}.recorded_at")
    except ConversationEventError as exc:
        raise ValueError(f"{name}: {exc}") from None
    return StoredConversationEvent(_count(item["sequence"], f"{name}.sequence", minimum=1), recorded_at, event)


def decode_stored_event(payload: object, name: str = "stored event") -> StoredConversationEvent:
    """Strict decode of one `{"sequence", "recorded_at", "event"}` item (page row, export line)."""
    return _decode_stored(payload, name)


def decode_event_response(payload: object) -> StoredConversationEvent:
    return _decode_stored(payload, "conversation event response", _EVENT_FIELDS)


def decode_event_page(payload: object, *, after_sequence: int = 0) -> ConversationEventPage:
    """Strict decode; sequences must ascend past `after_sequence` and `next_cursor` must cover them."""
    page = _object(payload, _PAGE_FIELDS, "conversation event page")
    if not isinstance(page["events"], list):
        raise ValueError("conversation event page.events must be a list")
    events = tuple(_decode_stored(item, f"events[{index}]") for index, item in enumerate(page["events"]))
    next_cursor = _count(page["next_cursor"], "next_cursor")
    last = after_sequence
    for item in events:
        if item.sequence <= last:
            raise ValueError("conversation event page sequences must ascend past the request cursor")
        last = item.sequence
    if next_cursor < last:
        raise ValueError("conversation event page next_cursor is behind its events")
    return ConversationEventPage(events, next_cursor, _bool(page["has_more"], "has_more"),
                                 _count(page["skipped_rows"], "skipped_rows"))


def _decode_summary(payload: object, name: str) -> ConversationEventSummary:
    item = _object(payload, _SUMMARY_FIELDS, name)
    try:
        conversation_id, session_id = item["conversation_id"], item["session_id"]
        state_id(conversation_id, f"{name}.conversation_id")
        state_id(session_id, f"{name}.session_id", optional=True)
        return ConversationEventSummary(
            conversation_id, session_id, _count(item["event_count"], f"{name}.event_count", minimum=1),
            _count(item["first_sequence"], f"{name}.first_sequence", minimum=1),
            _count(item["last_sequence"], f"{name}.last_sequence", minimum=1),
            parse_event_time(item["first_occurred_at"], f"{name}.first_occurred_at"),
            parse_event_time(item["last_occurred_at"], f"{name}.last_occurred_at"),
            parse_event_time(item["last_recorded_at"], f"{name}.last_recorded_at"))
    except ConversationEventError as exc:
        raise ValueError(str(exc)) from None


def decode_summary_page(payload: object) -> ConversationEventSummaryPage:
    page = _object(payload, _SUMMARY_PAGE_FIELDS, "conversation summary page")
    if not isinstance(page["summaries"], list):
        raise ValueError("conversation summary page.summaries must be a list")
    summaries = tuple(_decode_summary(item, f"summaries[{index}]") for index, item in enumerate(page["summaries"]))
    cursor = page["next_cursor"]
    if cursor is not None:
        _count(cursor, "next_cursor", minimum=1)
    return ConversationEventSummaryPage(summaries, cursor, _bool(page["has_more"], "has_more"),
                                        _count(page["skipped_summaries"], "skipped_summaries"))
