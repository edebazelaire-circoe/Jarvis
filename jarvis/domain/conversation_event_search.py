"""Bounded search over safe Conversation Event fields (Slice 06).

Binding contract: `docs/conversation-events.md`, section "Search".

What is searched, per stored event (nothing else, ever):

- `content`, **only when the event is public** (what the user said, heard or
  was shown). Diagnostic content (speech requests, sub-agent descriptions,
  work labels) is never matched;
- safe metadata: `event_type`, `actor`, `event_id` and the envelope ids
  (`SEARCH_ID_FIELDS`), and the status-code attributes `SEARCH_ATTRIBUTE_KEYS`.

Never searched: journal lines (`runtime/trace.jsonl`), attributes outside
`SEARCH_ATTRIBUTE_KEYS`, `trace_ref`, `producer`, times. A stored row that does
not decode through the codec is never returned.

Matching is case- and accent-insensitive for French without dependencies
(`fold`: NFKD, combining marks removed, `casefold`, `œ`/`æ` ligatures
expanded, typographic apostrophes `’ ‘ ʼ` read as `'`). The query is split on
whitespace; every term must occur in at least one searched field of the same
event: as a substring of public content and status codes; in an id field as
the whole id or a substring of at least `MIN_ID_SUBSTRING` characters; in
`event_type` / `actor` as the whole value or a run of whole dotted tokens
(`interrupted`, `speech.interrupted`), never a fragment (`re` matches nothing there).

Pure domain: parameters, matching, snippets and the wire codec. The scan itself
(newest first, bounded per request, cursor = last scanned sequence) lives in
the store adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from jarvis.domain.conversation_event_query import MAX_SEQUENCE, id_param, int_param, visibility_param
from jarvis.domain.conversation_event_store import StoredConversationEvent
from jarvis.domain.conversation_events import (
    ConversationEventError, ConversationVisibility, format_event_time, parse_event_time,
)
from jarvis.domain.voice_state import state_id

SEARCH_SCHEMA_VERSION = 1
MAX_QUERY_CHARS = 200
MAX_QUERY_TERMS = 8
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
#: Rows one search request may scan (newest first) before it returns with
#: `scan_limited` and a cursor to continue. Measured at 50 000 events: see the contract.
MAX_SEARCH_SCAN_ROWS = 50_000
#: Rows read per store transaction (only the searchable columns, extracted by SQLite).
SEARCH_SCAN_CHUNK = 250
#: Longest stretch of matching work on Core's event loop before the scan yields
#: (`await asyncio.sleep(0)`), so appends and every other task keep running.
SEARCH_SLICE_S = 0.002
SNIPPET_CONTEXT_CHARS = 60
#: Shortest term matched inside an id (shorter terms must equal the whole id).
MIN_ID_SUBSTRING = 6

SEARCH_ID_FIELDS = ("event_id", "conversation_id", "session_id", "turn_id", "correlation_id", "task_id", "work_id",
                    "speech_id", "outcome_id", "span_id")
SEARCH_ATTRIBUTE_KEYS = ("status", "code", "reason", "error_class")
SEARCH_PARAMS = frozenset({"q", "conversation_id", "before_sequence", "limit", "visibility"})

_SPECIAL = {"œ": "oe", "Œ": "oe", "æ": "ae", "Æ": "ae", "ø": "o", "Ø": "o", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d",
            "’": "'", "‘": "'", "ʼ": "'"}
_LIGATURES = str.maketrans(_SPECIAL)
_SPECIAL_RE = re.compile("[" + "".join(_SPECIAL) + "]")
_SPACES = re.compile(r"\s+")
_LATIN_COMBINING = re.compile("[\u0300-\u034e\u0350-\u036f]")  # U+034F (grapheme joiner) has class 0
_combining_table: dict[int, None] | None = None
#: Planes holding every code point with a nonzero canonical combining class.
_COMBINING_PLANES = ((0, 0x20000), (0xE0000, 0xE1000))


def _combining() -> dict[int, None]:
    """`str.translate` table deleting every combining mark (934 code points, built once in ~40 ms)."""
    global _combining_table
    if _combining_table is None:
        _combining_table = {code: None for low, high in _COMBINING_PLANES for code in range(low, high)
                            if unicodedata.combining(chr(code))}
    return _combining_table


def warm_search_tables() -> None:
    """Build the lazy folding table now (callers run this in a worker thread, off Core's loop)."""
    _combining()


def fold_text(text: str) -> str:
    """Comparison form for matching: accents and case removed, whitespace kept as is.

    Same result as removing every combining mark from the NFKD form, in C-level
    steps: ASCII text (ids, types, codes) only needs `lower()`; French accents
    fall in U+0300–U+036F and leave ASCII behind; anything else uses the full table.
    """
    if text.isascii():
        return text.lower()
    if _SPECIAL_RE.search(text):
        text = text.translate(_LIGATURES)
    stripped = _LATIN_COMBINING.sub("", unicodedata.normalize("NFKD", text))
    if not stripped.isascii():
        stripped = stripped.translate(_combining())
    return stripped.casefold()


def fold(text: str) -> str:
    """Case- and accent-insensitive comparison form (`Élan` -> `elan`, `cœur` -> `coeur`), whitespace collapsed."""
    return _SPACES.sub(" ", fold_text(text))


def _folded_with_origin(text: str) -> tuple[str, list[int]]:
    """Folded text plus, for each folded character, the index of the original character it came from."""
    out: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        piece = fold_text(char) if not char.isspace() else " "
        out.append(piece)
        origin.extend([index] * len(piece))
    return "".join(out), origin


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    terms: tuple[str, ...]

    @classmethod
    def parse(cls, raw: object) -> "SearchQuery":
        """Raises `ValueError` naming the rule, never the value."""
        if not isinstance(raw, str):
            raise ValueError("q must be text")
        try:
            raw.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("q must be valid Unicode text") from None
        if len(raw) > MAX_QUERY_CHARS or any(unicodedata.category(c) == "Cc" and not c.isspace() for c in raw):
            raise ValueError(f"q must be at most {MAX_QUERY_CHARS} characters of printable text")
        terms = tuple(dict.fromkeys(term for term in fold(raw).split(" ") if term))
        if not terms:
            raise ValueError("q must contain at least one non-blank term")
        if len(terms) > MAX_QUERY_TERMS:
            raise ValueError(f"q must contain at most {MAX_QUERY_TERMS} terms")
        return cls(raw, terms)


@dataclass(frozen=True, slots=True)
class SearchMatch:
    #: Searched fields that matched at least one term (`content`, `event_type`, `correlation_id`...).
    fields: tuple[str, ...]


def searchable_fields(payload: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The only (field, text) pairs of an encoded event the search may read."""
    fields: list[tuple[str, str]] = []
    content = payload.get("content")
    if payload.get("visibility") == ConversationVisibility.PUBLIC.value and isinstance(content, str):
        fields.append(("content", content))
    for name in ("event_type", "actor", *SEARCH_ID_FIELDS):
        value = payload.get(name)
        if isinstance(value, str):
            fields.append((name, value))
    attributes = payload.get("attributes")
    if isinstance(attributes, Mapping):
        for key in SEARCH_ATTRIBUTE_KEYS:
            value = attributes.get(key)
            if isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool)):
                fields.append((f"attributes.{key}", str(value)))
    return fields


_TOKEN_FIELDS = frozenset({"event_type", "actor"})


def _term_in(term: str, name: str, value: str) -> bool:
    """Where a folded term matches a folded field value (see the module rules).

    Ids need the whole id or a term of at least `MIN_ID_SUBSTRING` characters
    (a short number such as `17` would otherwise match nearly every event
    through the hex digits of its `event_id`); `event_type` / `actor` need
    whole dotted tokens (`re` must not match every `…accepted`).
    """
    if name in SEARCH_ID_FIELDS:
        return term == value or (len(term) >= MIN_ID_SUBSTRING and term in value)
    if name in _TOKEN_FIELDS:
        return term == value or f".{term}." in f".{value}."
    return term in value


def match_payload(query: SearchQuery, payload: Mapping[str, Any]) -> SearchMatch | None:
    folded = [(name, fold_text(value)) for name, value in searchable_fields(payload)]
    matched: dict[str, None] = {}
    for term in query.terms:
        hit = False
        for name, value in folded:
            if _term_in(term, name, value):
                matched[name] = None
                hit = True
        if not hit:
            return None
    return SearchMatch(tuple(matched))


def snippet(query: SearchQuery, stored: StoredConversationEvent,
            match: SearchMatch) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Excerpt around the first term found in public content, else the matched metadata.

    Returns the snippet and the code-point ranges of the terms inside it.
    """
    event = stored.event
    if "content" in match.fields and event.visibility is ConversationVisibility.PUBLIC and event.content:
        text = event.content
        folded, origin = _folded_with_origin(text)
        starts = [folded.find(term) for term in query.terms if term in folded]
        first = min(starts) if starts else 0
        center = origin[first] if origin else 0
        begin = max(0, center - SNIPPET_CONTEXT_CHARS)
        end = min(len(text), center + SNIPPET_CONTEXT_CHARS * 2)
        body = _SPACES.sub(" ", text[begin:end])
        excerpt = ("…" if begin > 0 else "") + body + ("…" if end < len(text) else "")
    else:
        parts = [event.event_type.value]
        payload_fields = dict(searchable_fields({**_metadata(stored)}))
        for name in match.fields:
            if name not in ("content", "event_type") and name in payload_fields:
                parts.append(f"{name} = {payload_fields[name]}")
        excerpt = " · ".join(parts)
    return excerpt, _marks(query, excerpt)


def _metadata(stored: StoredConversationEvent) -> dict[str, Any]:
    event = stored.event
    payload: dict[str, Any] = {"event_type": event.event_type.value, "actor": event.actor.value,
                               "visibility": event.visibility.value}
    for name in SEARCH_ID_FIELDS:
        payload[name] = getattr(event, name)
    payload["attributes"] = dict(event.attributes)
    return payload


def _marks(query: SearchQuery, excerpt: str) -> tuple[tuple[int, int], ...]:
    folded, origin = _folded_with_origin(excerpt)
    ranges: list[tuple[int, int]] = []
    for term in query.terms:
        start = folded.find(term)
        while start >= 0:
            ranges.append((origin[start], origin[start + len(term) - 1] + 1))
            start = folded.find(term, start + len(term))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return tuple(merged)


# ------------------------------------------------------------------- pages

@dataclass(frozen=True, slots=True)
class ConversationEventSearchHit:
    conversation_id: str
    event_id: str
    sequence: int
    occurred_at: Any  # datetime
    event_type: str
    actor: str
    visibility: str
    matched: tuple[str, ...]
    snippet: str
    #: Code-point ranges `[start, end)` of the query terms inside `snippet`.
    marks: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class ConversationEventSearchPage:
    """Hits newest first. Continue with `before_sequence=next_cursor` while `has_more`."""

    hits: tuple[ConversationEventSearchHit, ...]
    #: Last scanned sequence (exclusive bound of the next page); None when nothing was scanned.
    next_cursor: int | None
    has_more: bool
    #: Scanned rows that did not decode (skipped; the store diagnosed them).
    skipped_rows: int
    #: Rows scanned by this request.
    scanned_rows: int
    #: True when the request stopped on its scan budget, not on `limit` or the end of the log.
    scan_limited: bool


def build_hit(query: SearchQuery, stored: StoredConversationEvent, match: SearchMatch) -> ConversationEventSearchHit:
    excerpt, marks = snippet(query, stored, match)
    event = stored.event
    return ConversationEventSearchHit(event.conversation_id, event.event_id, stored.sequence, event.occurred_at,
                                      event.event_type.value, event.actor.value, event.visibility.value,
                                      match.fields, excerpt, marks)


def search_query(params: Mapping[str, str]) -> dict[str, Any]:
    if "q" not in params:
        raise ValueError("q is required")
    return {"query": SearchQuery.parse(params["q"]),
            "conversation_id": id_param(params, "conversation_id", required=False),
            "before_sequence": int_param(params, "before_sequence", default=None, minimum=1, maximum=MAX_SEQUENCE),
            "limit": int_param(params, "limit", default=DEFAULT_SEARCH_LIMIT, minimum=1, maximum=MAX_SEARCH_LIMIT),
            "visibility": visibility_param(params)}


def encode_search_page(page: ConversationEventSearchPage) -> dict[str, Any]:
    return {"schema_version": SEARCH_SCHEMA_VERSION,
            "hits": [{"conversation_id": hit.conversation_id, "event_id": hit.event_id, "sequence": hit.sequence,
                      "occurred_at": format_event_time(hit.occurred_at), "event_type": hit.event_type,
                      "actor": hit.actor, "visibility": hit.visibility, "matched": list(hit.matched),
                      "snippet": hit.snippet, "marks": [list(mark) for mark in hit.marks]} for hit in page.hits],
            "next_cursor": page.next_cursor, "has_more": page.has_more, "skipped_rows": page.skipped_rows,
            "scanned_rows": page.scanned_rows, "scan_limited": page.scan_limited}


_PAGE_FIELDS = frozenset({"schema_version", "hits", "next_cursor", "has_more", "skipped_rows", "scanned_rows",
                          "scan_limited"})
_HIT_FIELDS = frozenset({"conversation_id", "event_id", "sequence", "occurred_at", "event_type", "actor", "visibility",
                         "matched", "snippet", "marks"})


def _int(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def decode_search_page(payload: object) -> ConversationEventSearchPage:
    """Strict decode of a Core search answer; out of contract is a `ValueError`."""
    if not isinstance(payload, Mapping) or set(payload) != _PAGE_FIELDS or payload["schema_version"] != SEARCH_SCHEMA_VERSION:
        raise ValueError(f"search page must have exactly the fields {', '.join(sorted(_PAGE_FIELDS))}")
    if not isinstance(payload["hits"], list):
        raise ValueError("search page hits must be a list")
    hits = []
    last = None
    for index, raw in enumerate(payload["hits"]):
        name = f"hits[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _HIT_FIELDS:
            raise ValueError(f"{name} must have exactly the fields {', '.join(sorted(_HIT_FIELDS))}")
        try:
            state_id(raw["conversation_id"], f"{name}.conversation_id")
            occurred = parse_event_time(raw["occurred_at"], f"{name}.occurred_at")
        except ConversationEventError as exc:
            raise ValueError(str(exc)) from None
        sequence = _int(raw["sequence"], f"{name}.sequence", 1)
        if last is not None and sequence >= last:
            raise ValueError("search hits must be in descending sequence")
        last = sequence
        texts = [raw[key] for key in ("event_id", "event_type", "actor", "visibility", "snippet")]
        if not all(isinstance(text, str) for text in texts) or not isinstance(raw["matched"], list) \
                or not all(isinstance(m, str) for m in raw["matched"]) or not isinstance(raw["marks"], list):
            raise ValueError(f"{name} has a field of the wrong type")
        marks = []
        for mark in raw["marks"]:
            if not (isinstance(mark, list) and len(mark) == 2 and all(type(v) is int and v >= 0 for v in mark)):
                raise ValueError(f"{name}.marks must be [start, end] pairs")
            marks.append((mark[0], mark[1]))
        hits.append(ConversationEventSearchHit(raw["conversation_id"], raw["event_id"], sequence, occurred,
                                               raw["event_type"], raw["actor"], raw["visibility"],
                                               tuple(raw["matched"]), raw["snippet"], tuple(marks)))
    cursor = payload["next_cursor"]
    if cursor is not None:
        _int(cursor, "next_cursor")
    if type(payload["has_more"]) is not bool or type(payload["scan_limited"]) is not bool:
        raise ValueError("has_more and scan_limited must be booleans")
    return ConversationEventSearchPage(tuple(hits), cursor, payload["has_more"],
                                      _int(payload["skipped_rows"], "skipped_rows"),
                                      _int(payload["scanned_rows"], "scanned_rows"), payload["scan_limited"])
