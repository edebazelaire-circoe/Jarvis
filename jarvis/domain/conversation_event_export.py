"""Machine-readable JSONL export of one conversation, and its offline importer (Slice 06).

Binding contract: `docs/conversation-events.md`, section "JSONL export".
The export is a projection of the store, never a second record: every event
line is exactly the stored event as the query API serves it
(`encode_stored_event`: `{"sequence", "recorded_at", "event"}`, the event being
the codec output). One header line opens the file, one trailer line closes it:

    {"format": EXPORT_FORMAT, "export_version": 1, "schema_version": 1,
     "conversation_id", "exported_at", "through_sequence",
     "counts": {"stored_rows", "first_sequence", "last_sequence"}}
    {"sequence", "recorded_at", "event"}            (0..n, ascending sequence)
    {"format": EXPORT_FORMAT, "complete": true,
     "counts": {"events", "skipped_rows"}}

- `through_sequence` freezes the export at the conversation's last sequence
  when it started: events appended while it streams are not included, so the
  header counts describe exactly what follows;
- `skipped_rows` counts stored rows that did not decode (the store skipped and
  diagnosed them); they never appear as lines;
- a file without trailer is **incomplete** (stream interrupted), and the
  importer says so;
- there is **no integrity check**: the counts detect truncation and torn lines,
  not a deliberate edit (a removed event line with a matching edited trailer and
  header, or an edited but codec-valid content, reads as complete).

`read_export` decodes a file strictly, line by line: invalid lines are skipped
and reported with their line number and a reason naming the rule (never the
value). `transcript_from_export` and `reconstruct_export` rebuild the readable
transcript and the reconstruction offline with the same pure functions the live
routes use, so both are byte-identical to the live rendering of the same events.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from jarvis.domain.conversation_event_query import decode_stored_event
from jarvis.domain.conversation_event_store import ConversationEventExtent, StoredConversationEvent
from jarvis.domain.conversation_events import (
    CONVERSATION_EVENT_SCHEMA_VERSION, ConversationEventError, ConversationItem, format_event_time, parse_event_time,
    reconstruct_conversation,
)
from jarvis.domain.conversation_transcript import TranscriptBuilder, TranscriptMode
from jarvis.domain.voice_state import state_id

EXPORT_FORMAT = "jarvis.conversation-events.export"
EXPORT_VERSION = 1
EXPORT_MEDIA_TYPE = "application/x-ndjson"
#: Longest line the importer decodes (a contract-valid event line is < 200 KiB).
MAX_EXPORT_LINE_BYTES = 1024 * 1024

_HEADER_FIELDS = frozenset({"format", "export_version", "schema_version", "conversation_id", "exported_at",
                            "through_sequence", "counts"})
_HEADER_COUNTS = frozenset({"stored_rows", "first_sequence", "last_sequence"})
_TRAILER_FIELDS = frozenset({"format", "complete", "counts"})
_TRAILER_COUNTS = frozenset({"events", "skipped_rows"})


class ExportFormatError(ValueError):
    """The file is not a conversation event export (missing or invalid header). Names rules, never values."""


def encode_export_line(record: dict[str, Any]) -> bytes:
    """One compact UTF-8 JSON line (keys sorted, so equal records give equal bytes)."""
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def export_header(conversation_id: str, *, exported_at: datetime,
                  extent: ConversationEventExtent | None) -> dict[str, Any]:
    state_id(conversation_id, "conversation_id")
    return {
        "format": EXPORT_FORMAT, "export_version": EXPORT_VERSION, "schema_version": CONVERSATION_EVENT_SCHEMA_VERSION,
        "conversation_id": conversation_id, "exported_at": format_event_time(exported_at),
        "through_sequence": extent.last_sequence if extent is not None else 0,
        "counts": {"stored_rows": extent.stored_rows if extent is not None else 0,
                   "first_sequence": extent.first_sequence if extent is not None else None,
                   "last_sequence": extent.last_sequence if extent is not None else None},
    }


def export_trailer(*, events: int, skipped_rows: int) -> dict[str, Any]:
    return {"format": EXPORT_FORMAT, "complete": True, "counts": {"events": events, "skipped_rows": skipped_rows}}


def _fnv1a(text: str) -> str:
    """FNV-1a 32 bits of the UTF-8 bytes, 8 hex digits (the page computes the same)."""
    value = 0x811C9DC5
    for byte in text.encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{value:08x}"


def file_stem(conversation_id: str) -> str:
    """Safe download stem: ids are opaque, so anything outside `[A-Za-z0-9._-]` becomes `_`;
    an id that lost characters gets a short hash, so two such ids never share a name."""
    safe = "".join(char if char.isascii() and (char.isalnum() or char in "._-") else "_" for char in conversation_id)
    stem = safe[:80].strip("._") or "sans-id"
    return f"conversation-{stem}" + ("" if safe == conversation_id else f"-{_fnv1a(conversation_id)}")


def export_filename(conversation_id: str) -> str:
    return f"{file_stem(conversation_id)}.events.jsonl"


# ----------------------------------------------------------------- import

@dataclass(frozen=True, slots=True)
class ExportHeader:
    conversation_id: str
    exported_at: datetime
    through_sequence: int
    stored_rows: int


@dataclass(frozen=True, slots=True)
class ExportLineError:
    line: int
    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ExportReadResult:
    header: ExportHeader
    events: tuple[StoredConversationEvent, ...]
    #: Lines of the file that did not decode or break the export rules (skipped).
    invalid_lines: tuple[ExportLineError, ...]
    #: True only when the trailer is present and its counts match the lines read.
    complete: bool
    #: Stored rows the exporting store skipped as unreadable (from the trailer; 0 without trailer).
    skipped_rows: int


def _counts(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} must have exactly the fields {', '.join(sorted(fields))}")
    for key, item in value.items():
        if item is not None and (type(item) is not int or item < 0):
            raise ValueError(f"{name}.{key} must be a nonnegative integer")
    return value


def _header(payload: object) -> ExportHeader:
    if not isinstance(payload, dict) or set(payload) != _HEADER_FIELDS or payload.get("format") != EXPORT_FORMAT:
        raise ExportFormatError(f"first line must be the {EXPORT_FORMAT} header")
    if payload["export_version"] != EXPORT_VERSION or payload["schema_version"] != CONVERSATION_EVENT_SCHEMA_VERSION:
        raise ExportFormatError(f"unsupported export_version or schema_version; expected {EXPORT_VERSION} / "
                                f"{CONVERSATION_EVENT_SCHEMA_VERSION}")
    try:
        state_id(payload["conversation_id"], "conversation_id")
        exported_at = parse_event_time(payload["exported_at"], "exported_at")
        counts = _counts(payload["counts"], _HEADER_COUNTS, "counts")
        through = payload["through_sequence"]
        if type(through) is not int or through < 0 or counts["stored_rows"] is None:
            raise ValueError("through_sequence and counts.stored_rows must be nonnegative integers")
    except (ValueError, ConversationEventError) as exc:
        raise ExportFormatError(f"invalid export header: {exc}") from None
    return ExportHeader(payload["conversation_id"], exported_at, through, counts["stored_rows"])


def read_export(lines: Iterable[bytes | str], *, max_line_bytes: int = MAX_EXPORT_LINE_BYTES) -> ExportReadResult:
    """Decode an export file line by line. Raises `ExportFormatError` only for a missing/invalid header."""
    header: ExportHeader | None = None
    events: list[StoredConversationEvent] = []
    invalid: list[ExportLineError] = []
    trailer: dict[str, Any] | None = None
    last_sequence = 0
    for number, raw in enumerate(lines, 1):
        data = raw.encode("utf-8", "surrogatepass") if isinstance(raw, str) else raw
        if number == 1 and data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]  # a UTF-8 BOM added by an editor is not part of the header
        if len(data) > max_line_bytes:
            if header is None:
                raise ExportFormatError("first line must be the export header")
            invalid.append(ExportLineError(number, "oversized_line", f"line exceeds {max_line_bytes} bytes"))
            continue
        if not data.strip():
            continue
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if header is None:
                raise ExportFormatError("first line must be the export header (JSON)") from None
            invalid.append(ExportLineError(number, "invalid_json", type(exc).__name__))
            continue
        if header is None:
            header = _header(payload)
            continue
        if trailer is not None:
            invalid.append(ExportLineError(number, "after_trailer", "line after the export trailer"))
            continue
        if isinstance(payload, dict) and payload.get("format") == EXPORT_FORMAT:
            try:
                if set(payload) != _TRAILER_FIELDS or payload["complete"] is not True:
                    raise ValueError("trailer must be {format, complete: true, counts}")
                trailer = _counts(payload["counts"], _TRAILER_COUNTS, "trailer counts")
            except ValueError as exc:
                invalid.append(ExportLineError(number, "invalid_trailer", str(exc)))
            continue
        try:
            stored = decode_stored_event(payload, "event line")
        except ValueError as exc:
            invalid.append(ExportLineError(number, "invalid_event", str(exc)))
            continue
        if stored.event.conversation_id != header.conversation_id:
            invalid.append(ExportLineError(number, "other_conversation", "event of another conversation"))
        elif stored.sequence <= last_sequence or stored.sequence > header.through_sequence:
            invalid.append(ExportLineError(number, "sequence_out_of_order",
                                           "sequence must ascend and stay within through_sequence"))
        else:
            last_sequence = stored.sequence
            events.append(stored)
    if header is None:
        raise ExportFormatError("empty file: no export header")
    complete = (trailer is not None and trailer["events"] == len(events) and not invalid
                and trailer["events"] + trailer["skipped_rows"] == header.stored_rows)
    return ExportReadResult(header, tuple(events), tuple(invalid), complete,
                            trailer["skipped_rows"] if trailer is not None else 0)


def reconstruct_export(result: ExportReadResult, *, include_diagnostic: bool = True) -> tuple[ConversationItem, ...]:
    return reconstruct_conversation((stored.event for stored in result.events), include_diagnostic=include_diagnostic)


def transcript_from_export(result: ExportReadResult, *, mode: TranscriptMode = TranscriptMode.PLAIN,
                           utc_offset_minutes: int = 0) -> str:
    """The readable transcript of an export, byte-identical to the live route for the same events and inputs."""
    builder = TranscriptBuilder(result.header.conversation_id, mode=mode, utc_offset_minutes=utc_offset_minutes)
    for stored in result.events:
        builder.add(stored.event)
    builder.note_skipped_rows(result.skipped_rows)
    return builder.render()
