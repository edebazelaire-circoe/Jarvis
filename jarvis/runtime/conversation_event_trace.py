"""Trace drill-down of one stored Conversation Event (Slice 04).

Binding contract: `docs/conversation-events.md`, section "Query and live API",
"Trace drill-down". The Control Center already reads `runtime/trace.jsonl`; this
module finds the journal evidence of an event **loaded from the store** and
returns a redacted projection of it.

Rules:

- the drill-down always starts from a stored event and resolves its own
  `trace_ref`. An id found in a journal line (`conversation_event_id` of a
  provisional sub-agent line, `task_id`, ...) is never followed;
- user events have no drill-down (locked intent): `TraceNotApplicable`;
- `trace_ref.source == agent_task`: a link to the existing
  `/api/agent/tasks/{task_id}/trace` route, nothing duplicated here;
- `trace_ref.source == runtime_journal`: bounded newest-first scan of the trace
  file (`scan_trace`). Lines are matched with `trace_entry_matches`; corrupt or
  interleaved fragments are counted and skipped; `agent.event` lines are never
  decoded into a result;
- every returned line is a **projection** (`project_trace_entry`): `ts`, `kind`,
  `level`, `message` only when it is one of the constant messages its producer
  writes for that kind (`STATIC_MESSAGES`), and `data` restricted to `TRACE_DATA_KEYS` with
  scalar, token-shaped values. Raw `arguments`, `result`, `error`, `text`,
  `summary`, `description` never leave this module.

Scan bounds (newest first, `ScanLimits`): at most `max_bytes` read and
`max_lines` complete lines; lines longer than `max_line_bytes` are skipped; the
scan stops at the first line older than `occurred_at - window` (journal lines
are appended in time order by each process, interleaved by a few milliseconds
across processes); lines newer than `occurred_at + window` are not decoded; at
most `max_matches` matches. `truncated` is true when a byte or line budget
stopped the scan before the window start or the file start.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from jarvis.domain.conversation_events import (
    ConversationActor, ConversationEvent, TraceSource, trace_entry_matches,
)

#: Journal `data` keys a projection may keep, grouped by the value rule that
#: applies to them (`_safe_data_value`). Anything else (arguments, result,
#: error, text, summary, description, label, prompt, ...) is dropped.
#: Opaque ids: printable, at most 256 characters, no `@`, `/`, `\`, `=`, `+` or whitespace.
TRACE_ID_KEYS = frozenset({
    "conversation_id", "session_id", "turn_id", "correlation_id", "task_id", "work_id", "speech_id", "outcome_id",
    "output_id", "call_id", "tool_use_id", "parent_id", "job_id", "candidate_id",
})
#: `cev-` + 64 lowercase hex only.
TRACE_EVENT_ID_KEYS = frozenset({"conversation_event_id"})
#: Lower-case code tokens `[a-z][a-z0-9_.-]{0,63}`, or a number (HTTP status, priority).
TRACE_CODE_KEYS = frozenset({"status", "code", "reason", "kind", "priority", "provider", "source", "disposition"})
#: Exception class names `[A-Z][A-Za-z0-9_]{0,63}`, or a lower-case code token (as above).
TRACE_CLASS_KEYS = frozenset({"error_class", "exception_type"})
#: Model and sub-agent type names `[a-z0-9][a-z0-9._:-]{0,63}`.
TRACE_MODEL_KEYS = frozenset({"model", "subagent_type"})
#: Booleans and numbers only.
TRACE_NUMBER_KEYS = frozenset({"duplicate", "background", "duration_ms", "played_ms", "tokens", "tool_uses", "depth",
                               "revision", "attempt"})
TRACE_DATA_KEYS = (TRACE_ID_KEYS | TRACE_EVENT_ID_KEYS | TRACE_CODE_KEYS | TRACE_CLASS_KEYS | TRACE_MODEL_KEYS
                   | TRACE_NUMBER_KEYS)
#: Credential shapes refused in every string value, whatever its key (case-insensitive
#: prefixes): API keys, provider and forge tokens, cloud keys, JWTs, bearer strings.
SECRET_PREFIXES = ("sk-", "sk_", "pk_", "rk_", "ghp_", "gho_", "ghs_", "ghu_", "github_pat_", "glpat-", "xox",
                   "akia", "asia", "aiza", "ya29.", "eyj", "hf_", "bearer")

#: Constant messages the producers of `trace_ref` kinds write (read at the
#: emitting sites, 2026-09-16). A line's `message` is returned only when it is
#: one of these exact strings for its kind; every other message (exception
#: text, sub-agent descriptions, tool names, or a producer that changed its
#: wording) is withheld (`message_redacted`). Drift can only hide a message,
#: never leak one.
STATIC_MESSAGES: Mapping[str, frozenset[str]] = {
    "core.brain.turn_failed": frozenset({"le backend cerveau a échoué", "le backend cerveau a rendu un échec"}),
    "core.brain.backend_contract_violation": frozenset({"le backend a rendu un résultat portant une autre corrélation"}),
    "core.brain.backend_task_started": frozenset({"backend task accepted"}),
    "core.brain.backend_task_result": frozenset({"backend task completed", "backend task failed",
                                                 "backend task cancelled"}),
    "core.brain.work_cancelled": frozenset({"travail annulé sur décision explicite du cerveau"}),
    "core.brain.turn_settlement_failed": frozenset({"public result settlement failed"}),
    "core.brain.outcome_selected": frozenset({"available outcome selected for presentation"}),
    "core.brain.outcome_retained": frozenset({"public outcome retained"}),
    "core.brain.outcome_matured": frozenset({"public outcome kind matured"}),
    "voice.speech.queued": frozenset({"Speech queued"}),
    "voice.speech.started": frozenset({"Speech generation requested"}),
    "voice.speech.completed": frozenset({"Speech completed"}),
    "voice.speech.interrupted": frozenset({"Speech interrupted"}),
    "voice.speech.superseded": frozenset({"Speech presentation retired", "Speech superseded on arrival"}),
    "voice.speech.expired": frozenset({"Speech presentation retired"}),
    "voice.speech.speak_failed": frozenset({"Speech request failed"}),
    "voice.reflex.started": frozenset({"Preamble generation requested"}),
}

#: Raw provider stream (thinking blocks included): never returned, whatever the reference says.
RAW_PROVIDER_STREAM_KIND = "agent.event"

_TOKEN_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_CODE_VALUE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_CLASS_VALUE = re.compile(r"[A-Z][A-Za-z0-9_]{0,63}")
_MODEL_VALUE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}")
_EVENT_ID_VALUE = re.compile(r"cev-[0-9a-f]{64}")
_ID_FORBIDDEN = re.compile(r"[@/\\=+\s]")
_MAX_ID_CHARS = 256
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]{8,15}(Z|[+-][0-9]{2}:[0-9]{2})?")
#: Dropped key names are listed only when they look like a code identifier; all are counted.
_KEY_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TS_HEAD = re.compile(rb'"ts"\s*:\s*"([^"]{10,40})"')
_CHUNK_BYTES = 256 * 1024


class TraceNotApplicable(Exception):
    """This event has no diagnostic drill-down (user events, locked intent)."""


@dataclass(frozen=True, slots=True)
class ScanLimits:
    max_bytes: int = 64 * 2**20
    max_lines: int = 500_000
    max_line_bytes: int = 256 * 1024
    max_matches: int = 8
    window: timedelta = timedelta(minutes=15)


@dataclass(slots=True)
class TraceScan:
    entries: list[dict[str, Any]] = field(default_factory=list)
    scanned_lines: int = 0
    scanned_bytes: int = 0
    corrupt_lines: int = 0
    oversized_lines: int = 0
    #: A byte/line budget or the match cap stopped the scan early.
    truncated: bool = False
    #: Why the scan ended: file_start, window_start, max_bytes, max_lines, max_matches, missing_file.
    stopped_by: str = "file_start"

    def to_payload(self) -> dict[str, Any]:
        return {"entries": self.entries, "match_count": len(self.entries), "scanned_lines": self.scanned_lines,
                "scanned_bytes": self.scanned_bytes, "corrupt_lines": self.corrupt_lines,
                "oversized_lines": self.oversized_lines, "truncated": self.truncated, "stopped_by": self.stopped_by}


# ----------------------------------------------------------------- projection

def _looks_secret(value: str) -> bool:
    return value.lower().startswith(SECRET_PREFIXES)


def _safe_data_value(key: str, value: object) -> bool:
    """The value rule of an allowlisted key (see the key groups above)."""
    if value is None or type(value) is bool:
        return True
    if type(value) in (int, float):
        return (key not in TRACE_ID_KEYS and key not in TRACE_EVENT_ID_KEYS and math.isfinite(value)
                and abs(value) <= 2**53)
    if not isinstance(value, str) or key in TRACE_NUMBER_KEYS or _looks_secret(value):
        return False
    if key in TRACE_EVENT_ID_KEYS:
        return bool(_EVENT_ID_VALUE.fullmatch(value))
    if key in TRACE_ID_KEYS:
        return 0 < len(value) <= _MAX_ID_CHARS and value.isprintable() and not _ID_FORBIDDEN.search(value)
    if key in TRACE_CLASS_KEYS:
        return bool(_CLASS_VALUE.fullmatch(value) or _CODE_VALUE.fullmatch(value))
    if key in TRACE_MODEL_KEYS:
        return bool(_MODEL_VALUE.fullmatch(value))
    return key in TRACE_CODE_KEYS and bool(_CODE_VALUE.fullmatch(value))


def project_trace_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Redacted view of one journal line: never raw text, never a value outside the allowlist.

    Total over any decoded JSON object: a malformed line (non-string message,
    nested data, odd keys) is projected, never raised on.
    """
    raw_kind = entry.get("kind")
    kind = raw_kind if isinstance(raw_kind, str) and len(raw_kind) <= 128 and _TOKEN_VALUE.fullmatch(raw_kind) else None
    raw_data = entry.get("data") if isinstance(entry.get("data"), Mapping) else {}
    data: dict[str, Any] = {}
    redacted: set[str] = set()
    redacted_count = 0
    for key, value in raw_data.items():
        if isinstance(key, str) and key in TRACE_DATA_KEYS and _safe_data_value(key, value):
            data[key] = value
            continue
        redacted_count += 1
        if isinstance(key, str) and _KEY_NAME.fullmatch(key):
            redacted.add(key)
    message = entry.get("message")
    keep_message = kind is not None and isinstance(message, str) and message in STATIC_MESSAGES.get(kind, ())
    ts, level = entry.get("ts"), entry.get("level")
    return {
        "ts": ts if isinstance(ts, str) and _TIMESTAMP.fullmatch(ts) else None,
        "kind": kind,
        "level": level if isinstance(level, str) and len(level) <= 16 and _CODE_VALUE.fullmatch(level) else None,
        "message": message if keep_message else None,
        "message_redacted": not keep_message and message is not None,
        "data": data,
        "redacted_keys": sorted(redacted),
        "redacted_key_count": redacted_count,
    }


# ----------------------------------------------------------------------- scan

def _parse_ts(line: bytes) -> datetime | None:
    match = _TS_HEAD.search(line, 0, 96)
    if match is None:
        return None
    try:
        value = datetime.fromisoformat(match.group(1).decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _lines_newest_first(handle, size: int, limits: ScanLimits, scan: TraceScan) -> Iterator[bytes]:
    """Complete lines from the end of the file; oversized lines are skipped and counted."""
    position, carry, discarding = size, b"", False
    while position > 0:
        if scan.scanned_bytes >= limits.max_bytes:
            scan.truncated, scan.stopped_by = True, "max_bytes"
            return
        step = min(_CHUNK_BYTES, position, limits.max_bytes - scan.scanned_bytes)
        position -= step
        handle.seek(position)
        chunk = handle.read(step)
        scan.scanned_bytes += len(chunk)
        parts = (chunk + carry).split(b"\n")
        if discarding:
            # The last part belongs to the oversized line already given up.
            if len(parts) == 1:
                carry = b""
                continue
            parts[-1] = b""
            discarding = False
        carry = parts[0]
        for line in reversed(parts[1:]):
            if len(line) > limits.max_line_bytes:
                scan.oversized_lines += 1
            elif line.strip():
                yield line
        if len(carry) > limits.max_line_bytes:
            scan.oversized_lines += 1
            carry, discarding = b"", True
    if carry.strip() and not discarding:
        yield carry


def scan_trace(path: Path, event: ConversationEvent, *, limits: ScanLimits = ScanLimits()) -> TraceScan:
    """Journal lines matching `event.trace_ref` (runtime_journal), newest first, bounded and redacted."""
    ref = event.trace_ref
    if ref is None or ref.source is not TraceSource.RUNTIME_JOURNAL:
        raise ValueError("scan_trace needs a runtime_journal trace_ref")
    scan = TraceScan()
    kind_bytes = json.dumps(ref.journal_kind)[1:-1].encode("utf-8")
    lower, upper = event.occurred_at - limits.window, event.occurred_at + limits.window
    try:
        handle = path.open("rb")
    except FileNotFoundError:
        scan.stopped_by = "missing_file"
        return scan
    with handle:
        size = path.stat().st_size
        for line in _lines_newest_first(handle, size, limits, scan):
            if scan.scanned_lines >= limits.max_lines:
                scan.truncated, scan.stopped_by = True, "max_lines"
                break
            scan.scanned_lines += 1
            ts = _parse_ts(line)
            if ts is not None and ts < lower:
                scan.stopped_by = "window_start"
                break
            if (ts is not None and ts > upper) or kind_bytes not in line:
                continue
            try:
                entry = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                scan.corrupt_lines += 1
                continue
            if not isinstance(entry, dict):
                scan.corrupt_lines += 1
                continue
            kind = entry.get("kind")
            if isinstance(kind, str) and (kind == RAW_PROVIDER_STREAM_KIND or kind.startswith(RAW_PROVIDER_STREAM_KIND + ".")):
                continue
            if trace_entry_matches(event, entry):
                scan.entries.append(project_trace_entry(entry))
                if len(scan.entries) >= limits.max_matches:
                    scan.truncated, scan.stopped_by = True, "max_matches"
                    break
    return scan


# ------------------------------------------------------------------ drill-down

def agent_task_trace_url(task_id: str) -> str:
    return f"/api/agent/tasks/{quote(task_id, safe='')}/trace"


def drill_down(event: ConversationEvent, trace_path: Path, *, limits: ScanLimits = ScanLimits()) -> dict[str, Any]:
    """Diagnostic evidence of a stored event. Raises `TraceNotApplicable` for user events.

    `status`: `found` / `not_found` (runtime journal scan), `agent_task` (link to
    the agent task trace route), `no_trace_ref` (the producer wrote no journal
    line for this fact). A sub-agent event also carries the agent task link.
    """
    if event.actor is ConversationActor.USER:
        raise TraceNotApplicable("user events have no diagnostic drill-down")
    ref = event.trace_ref
    agent_task = ({"task_id": event.task_id, "trace_url": agent_task_trace_url(event.task_id)}
                  if event.task_id is not None and (event.actor is ConversationActor.SUBAGENT
                                                    or (ref is not None and ref.source is TraceSource.AGENT_TASK))
                  else None)
    body: dict[str, Any] = {"ok": True, "event_id": event.event_id, "event_type": event.event_type.value,
                            "trace_ref": None, "agent_task": agent_task, "scan": None}
    if ref is None:
        return {**body, "status": "no_trace_ref"}
    body["trace_ref"] = {"source": ref.source.value, "journal_kind": ref.journal_kind, "join_keys": list(ref.join_keys)}
    if ref.source is TraceSource.AGENT_TASK:
        return {**body, "status": "agent_task"}
    scan = scan_trace(trace_path, event, limits=limits)
    return {**body, "status": "found" if scan.entries else "not_found", "scan": scan.to_payload()}
