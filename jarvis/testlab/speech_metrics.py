"""Speech presentation metrics read back from the Conversation Events journal.

Closing metrics of the task `jarvis-voice-stale-speech-presentation` (Slice 06,
`tasks/jarvis-voice-stale-speech-presentation/docs/04-testing-and-quality.md`,
« Métriques de clôture »): how the mouth really ended its speeches on a real
session, per voice surface, and whether an outdated formulation was ever said.

Read-only, and no second reader: events come through the Test Lab capture
readers (`bundle_capture.read_session_events` over `StateDatabaseEventSource`:
sqlite `mode=ro` + `PRAGMA query_only`, rows decoded by the
`SQLiteConversationEventStore` codec checks) and the optional runtime journal
through `bundle_capture.read_session_trace` (bounded, allowlisted projection).
Percentiles are `trace_summary.summarize_values`.

Snapshot (`--snapshot`): the Core journal of 2026-09-28 has a stale `-wal` that
makes SQLite read a malformed, truncated view (Issue `journal-wal-corrupt.md`).
The snapshot copies the main file **bytes** (never opened by SQLite in place),
measures that copy, and checks the WAL view on a second private copy; a WAL view
that fails integrity, or that holds events the file lacks, is reported loudly.

    python scripts/measure_speech_metrics.py --db data/state/jarvis.sqlite3 --snapshot --baseline
    python scripts/measure_speech_metrics.py --db data/state/jarvis.sqlite3 --snapshot \\
        --window after=2026-10-01T09:00Z..2026-10-01T10:00Z --baseline --json

Surface of a speech: `correlation_id` prefix `live:` (GPT-Live, Duplex) or
`realtime:` (OpenAI Realtime), else the surface its voice session shows
elsewhere, else `unknown`. Definitions of every metric: `docs/OPERATIONS.md`
« Speech presentation metrics ».
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from typing import Any

from jarvis.core.brain_service import BRAIN_NOTICE_RELAYED_KIND
from jarvis.domain.conversation_event_store import StoredConversationEvent
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import TRANSIENT_SPEECH_KINDS
from jarvis.runtime.speech_scheduler import (
    COMPLETION_LOCAL_QUIESCENCE,
    HELD_FOR_BRAIN,
    LIVE_PAUSE_FLOOR_MS,
    OUTPUT_STALLED,
    VERDICT_NOT_REVALIDATED,
    VERDICT_REVALIDATED,
    SpeechScheduler,
)
from jarvis.runtime.trace_summary import summarize_values
from jarvis.testlab.bundle import SourceStatus
from jarvis.testlab.bundle_builder import SessionSelector, TraceLine
from jarvis.testlab.bundle_capture import (
    EventReadLimits,
    StateDatabaseEventSource,
    TraceReadLimits,
    read_session_events,
    read_session_trace,
)

LIVE, REALTIME, UNKNOWN = "live", "realtime", "unknown"
SURFACES = (LIVE, REALTIME, UNKNOWN)
TERMINALS = {
    T.MOUTH_SPEECH_COMPLETED: "completed", T.MOUTH_SPEECH_INTERRUPTED: "interrupted",
    T.MOUTH_SPEECH_SUPERSEDED: "superseded", T.MOUTH_SPEECH_EXPIRED: "expired",
    T.MOUTH_SPEECH_FAILED: "failed", T.MOUTH_SPEECH_UNCONFIRMED: "unconfirmed",
}
TRANSIENT_KINDS = frozenset(kind.value for kind in TRANSIENT_SPEECH_KINDS)
#: `OUTPUT_TIMEOUT_S` (30 s) safety net: the Live signature of the stale-mouth bug.
NEAR_TIMEOUT_S = (29.5, 30.5)
HELD_TIMEOUT_REASON = "held_for_brain_timeout"
#: A pause at least this share of the Live grace is close to ending the speech early (Slice 06 part B).
NEAR_GRACE_SHARE = 0.8
LIVE_GRACE_MS = SpeechScheduler.LIVE_COMPLETION_GRACE_MS
#: Events are read this far around a window so a speech queued inside it keeps its end.
WINDOW_MARGIN = timedelta(minutes=2)
#: Two barge-in markers closer than this are one barge-in (floor taken + interrupted speech).
BARGE_IN_DEDUP = timedelta(seconds=2)
#: Slice 03 (typed relays) accepted 2026-09-28; any journal event after this date was
#: written by code that joins every relay to `core.brain.notice_relayed`.
SLICE_03_CUTOFF = datetime(2026, 9, 29, tzinfo=timezone.utc)
#: Reference windows of READINESS B2 (UTC).
BASELINE_WINDOWS = (
    ("baseline-18-21/09", datetime(2026, 9, 18, tzinfo=timezone.utc), datetime(2026, 9, 22, tzinfo=timezone.utc)),
    ("session-28/09", datetime(2026, 9, 28, 12, 54, tzinfo=timezone.utc),
     datetime(2026, 9, 28, 12, 59, tzinfo=timezone.utc)),
)
#: Targets of « Métriques de clôture » (Slice 06). `None` limit: must be 0.
TARGETS = (
    ("live_release_after_quiescence_p95_ms", "Libération bouche Live après quiescence, p95", "< 1000 ms"),
    ("live_output_stalled", "`speech_output_stalled` sur Live (trace)", "0"),
    ("live_delivery_not_complete_near_30s", "Live `delivery_not_complete` à ~30 s (journal)", "0"),
    ("outdated_started", "Paroles d'une intention dépassée démarrées sans réémission", "0"),
    ("held_then_started", "Paroles retenues pour le cerveau puis démarrées", "0"),
    ("current_intent_queue_wait_p95_ms", "Attente en file (intention courante) au-delà de la parole en cours, p95",
     "< 2000 ms"),
    ("relay_violations", "Relais sans genre / transitoires sans TTL (+ non typés d'avant S03, heuristique)", "0"),
)
EXIT_OK, EXIT_USAGE, EXIT_INCONCLUSIVE = 0, 2, 3


class MeasureError(Exception):
    """The journal could not be read or snapshotted; the message says what and where."""


# ------------------------------------------------------------------ model

@dataclass(slots=True)
class Speech:
    speech_id: str
    conversation_id: str
    session_id: str | None = None
    correlation_id: str | None = None
    chain: str | None = None
    kind: str | None = None
    queued: datetime | None = None
    started: datetime | None = None
    held: list[tuple[datetime, str]] = field(default_factory=list)
    terminal: str | None = None
    ended: datetime | None = None
    reason: str | None = None
    basis: str | None = None
    release_ms: float | None = None
    #: Live pauses between sentences (`live_pauses_ms`, first values only), their count and max;
    #: `None` count: the completion predates the measure (before Slice 06 part B).
    pauses_ms: tuple[float, ...] = ()
    pause_count: int | None = None
    pause_max_ms: float | None = None
    surface: str = UNKNOWN

    @property
    def first_seen(self) -> datetime | None:
        seen = [at for at in (self.queued, self.started, self.ended, *(at for at, _ in self.held)) if at]
        return min(seen) if seen else None

    @property
    def duration_s(self) -> float | None:
        if self.started is None or self.ended is None:
            return None
        return (self.ended - self.started).total_seconds()


def _surface_of(correlation_id: str | None) -> str | None:
    if correlation_id and correlation_id.startswith("live:"):
        return LIVE
    if correlation_id and correlation_id.startswith("realtime:"):
        return REALTIME
    return None


def _session_surfaces(events: Iterable[StoredConversationEvent]) -> dict[str, str]:
    votes: dict[str, Counter] = defaultdict(Counter)
    for stored in events:
        surface = _surface_of(stored.event.correlation_id)
        if surface and stored.event.session_id:
            votes[stored.event.session_id][surface] += 1
    return {session: counter.most_common(1)[0][0] for session, counter in votes.items()}


def build_speeches(events: Sequence[StoredConversationEvent]) -> dict[str, Speech]:
    """One record per `speech_id` from its `mouth.speech.*` facts (first terminal wins)."""
    sessions = _session_surfaces(events)
    speeches: dict[str, Speech] = {}
    for stored in sorted(events, key=lambda item: (item.event.occurred_at, item.sequence)):
        event = stored.event
        if not event.event_type.value.startswith("mouth.speech.") or not event.speech_id:
            continue
        speech = speeches.setdefault(event.speech_id, Speech(event.speech_id, event.conversation_id))
        attributes = event.attributes
        speech.session_id = speech.session_id or event.session_id
        speech.correlation_id = speech.correlation_id or event.correlation_id
        speech.chain = speech.chain or event.parent_event_id
        speech.kind = speech.kind or attributes.get("kind")
        at = event.occurred_at
        if event.event_type is T.MOUTH_SPEECH_QUEUED:
            speech.queued = speech.queued or at
        elif event.event_type is T.MOUTH_SPEECH_HELD:
            speech.held.append((at, str(attributes.get("reason") or HELD_FOR_BRAIN)))
        elif event.event_type is T.MOUTH_SPEECH_STARTED:
            speech.started = speech.started or at
        elif event.event_type in TERMINALS and speech.terminal is None:
            speech.terminal, speech.ended = TERMINALS[event.event_type], at
            speech.reason = attributes.get("reason") or attributes.get("code")
            speech.basis = attributes.get("completion_basis")
            release = attributes.get("release_after_quiescence_ms")
            speech.release_ms = float(release) if isinstance(release, (int, float)) else None
            count = attributes.get("live_pause_count")
            if isinstance(count, int) and not isinstance(count, bool):
                speech.pause_count = count
                maximum = attributes.get("live_pause_max_ms")
                speech.pause_max_ms = float(maximum) if isinstance(maximum, (int, float)) else None
                speech.pauses_ms = tuple(float(value) for value in attributes.get("live_pauses_ms") or ()
                                         if isinstance(value, (int, float)) and not isinstance(value, bool))
            if speech.started is None and event.started_at is not None and event.started_at < at:
                speech.started = event.started_at
    for speech in speeches.values():
        speech.surface = (_surface_of(speech.correlation_id) or sessions.get(speech.session_id or "") or UNKNOWN)
    return speeches


@dataclass(frozen=True, slots=True)
class Turn:
    at: datetime
    conversation_id: str
    correlation_id: str


def build_turns(events: Sequence[StoredConversationEvent]) -> list[Turn]:
    """Accepted brain turns, each at the time it became the current intent.

    An addressed turn is current from its acceptance. An `uncertain` turn only if
    the brain takes it (promotion), which the journal does not record as such
    (`brain.turn.unpromoted` is a bus/trace fact, not a conversation event): it is
    current from its first speech — `brain.speech.requested` or `mouth.speech.*`
    under its correlation. An uncertain turn that never speaks never becomes current.
    """
    first_speech: dict[tuple[str, str], datetime] = {}
    for stored in events:
        event = stored.event
        if event.correlation_id and (event.event_type is T.BRAIN_SPEECH_REQUESTED
                                     or event.event_type.value.startswith("mouth.speech.")):
            key = (event.conversation_id, event.correlation_id)
            first_speech[key] = min(first_speech.get(key, event.occurred_at), event.occurred_at)
    turns: list[Turn] = []
    for stored in events:
        event = stored.event
        if event.event_type is not T.BRAIN_TURN_ACCEPTED or not event.correlation_id:
            continue
        at = event.occurred_at
        if event.attributes.get("addressing") == "uncertain":
            promoted = first_speech.get((event.conversation_id, event.correlation_id))
            if promoted is None:
                continue
            at = max(at, promoted)
        turns.append(Turn(at, event.conversation_id, event.correlation_id))
    return sorted(turns, key=lambda turn: turn.at)


def _current_correlation(turns: Sequence[Turn], conversation_id: str, at: datetime) -> str | None:
    current = None
    for turn in turns:
        if turn.at > at:
            break
        if turn.conversation_id == conversation_id:
            current = turn.correlation_id
    return current


# ---------------------------------------------------------------- metrics

def _stats(values: Sequence[float]) -> dict[str, object]:
    return summarize_values(list(values))


def _outdated(speech: Speech, turns: Sequence[Turn], chain_started: dict[str, datetime]) -> bool:
    """Started while a newer turn than its own was current, outside a chain already in delivery.

    A durable formulation only: a transient one (ack/progress) of a past intent is
    dropped by design, and a chain already speaking finishes (Slice 04, rank 0).
    """
    if speech.started is None or speech.kind in TRANSIENT_KINDS or not speech.correlation_id:
        return False
    current = _current_correlation(turns, speech.conversation_id, speech.started)
    if current is None or current == speech.correlation_id:
        return False
    newer = next((turn.at for turn in turns if turn.conversation_id == speech.conversation_id
                  and turn.correlation_id == current), None)
    own = next((turn.at for turn in turns if turn.conversation_id == speech.conversation_id
                and turn.correlation_id == speech.correlation_id), None)
    if own is not None and newer is not None and own >= newer:
        return False  # its own turn is at least as new as the current one
    first = chain_started.get(speech.chain or speech.speech_id)
    return not (first is not None and newer is not None and first < newer)


def _queue_wait_ms(speech: Speech, speeches: Sequence[Speech], releases: Sequence[tuple[datetime, str]]) -> float | None:
    """Start minus the latest of: queued, end of the speech in progress, end of a floor freeze."""
    if speech.started is None or speech.queued is None:
        return None
    ready = speech.queued
    for other in speeches:
        if (other is not speech and other.conversation_id == speech.conversation_id and other.ended is not None
                and other.started is not None and other.ended <= speech.started and other.ended > ready):
            ready = other.ended
    for at, conversation_id in releases:
        if conversation_id == speech.conversation_id and ready < at <= speech.started:
            ready = at
    return max(0.0, (speech.started - ready).total_seconds() * 1000)


def _floor(events: Sequence[StoredConversationEvent], window: tuple[datetime, datetime]) -> dict[str, Any]:
    taken, released, durations = Counter(), Counter(), []
    for stored in events:
        event = stored.event
        if not window[0] <= event.occurred_at < window[1]:
            continue
        if event.event_type is T.MOUTH_FLOOR_TAKEN:
            taken[str(event.attributes.get("while") or "?")] += 1
        elif event.event_type is T.MOUTH_FLOOR_RELEASED:
            released[str(event.attributes.get("reason") or "?")] += 1
            if isinstance(event.attributes.get("duration_ms"), (int, float)):
                durations.append(float(event.attributes["duration_ms"]))
    return {"taken_by_while": dict(taken), "released_by_reason": dict(released),
            "duration_ms": _stats(durations), "timeouts": released.get("timeout", 0)}


def _live_silence_after_barge_in(events: Sequence[StoredConversationEvent], speeches: Sequence[Speech],
                                 surfaces: dict[str, str], window: tuple[datetime, datetime]) -> dict[str, Any]:
    """Live: time from a barge-in to the next speech heard (Issue `live-barge-in-mutes-incarnation.md`)."""
    markers: list[tuple[datetime, str]] = []
    for stored in events:
        event = stored.event
        barge = (event.event_type is T.MOUTH_FLOOR_TAKEN
                 or (event.event_type is T.MOUTH_SPEECH_INTERRUPTED and event.attributes.get("reason") == "user_barge_in"))
        surface = _surface_of(event.correlation_id) or surfaces.get(event.session_id or "")
        if barge and surface == LIVE and window[0] <= event.occurred_at < window[1]:
            markers.append((event.occurred_at, event.conversation_id))
    markers.sort()
    kept: list[tuple[datetime, str]] = []
    for at, conversation_id in markers:
        if not kept or at - kept[-1][0] > BARGE_IN_DEDUP or conversation_id != kept[-1][1]:
            kept.append((at, conversation_id))
    delays, never, unconfirmed = [], 0, 0
    heard = sorted((s.ended, s.conversation_id) for s in speeches
                   if s.surface == LIVE and s.terminal == "completed" and s.ended is not None)
    for at, conversation_id in kept:
        following = [end for end, cid in heard if cid == conversation_id and end > at]
        unconfirmed += sum(1 for s in speeches if s.surface == LIVE and s.terminal == "unconfirmed"
                           and s.conversation_id == conversation_id and s.ended and s.ended > at
                           and (not following or s.ended <= following[0]))
        if following:
            delays.append((following[0] - at).total_seconds() * 1000)
        else:
            never += 1
    return {"barge_ins": len(kept), "next_heard_ms": _stats(delays), "never_heard_again": never,
            "unconfirmed_before_next_heard": unconfirmed}


def relay_cutoff(events: Sequence[StoredConversationEvent]) -> datetime:
    """From when relays are identified positively: `SLICE_03_CUTOFF`, or earlier if a typed relay is seen."""
    typed = [stored.event.occurred_at for stored in events if _is_typed_relay(stored.event)]
    return min([SLICE_03_CUTOFF, *typed])


def _is_typed_relay(event) -> bool:  # noqa: ANN001
    return (event.event_type is T.BRAIN_SPEECH_REQUESTED and event.trace_ref is not None
            and event.trace_ref.journal_kind == BRAIN_NOTICE_RELAYED_KIND)


def _relays(events: Sequence[StoredConversationEvent], window: tuple[datetime, datetime]) -> dict[str, Any]:
    """Relays: positively (joined to `core.brain.notice_relayed`) from the Slice 03 cut-off on.

    Before it a relay carried no trace kind nor declared kind; the heuristic
    (`result`, no work, no key) is applied ONLY before the cut-off and reported
    as `legacy_heuristic`: after it, a plain workless brain answer has the same
    shape and is not a relay.
    """
    cutoff = relay_cutoff(events)
    typed, legacy, without_kind, transient_without_ttl = Counter(), 0, 0, 0
    for stored in events:
        event = stored.event
        if event.event_type is not T.BRAIN_SPEECH_REQUESTED or not window[0] <= event.occurred_at < window[1]:
            continue
        kind = event.attributes.get("kind")
        if _is_typed_relay(event):
            typed[str(kind)] += 1
            without_kind += kind is None
            transient_without_ttl += kind in TRANSIENT_KINDS and not event.attributes.get("expires_at")
        elif (event.occurred_at < cutoff and not event.work_id and kind == "result"
              and not event.attributes.get("supersedes_key")):
            legacy += 1
    return {"typed_by_kind": dict(typed), "without_kind": without_kind,
            "transient_without_ttl": transient_without_ttl, "legacy_heuristic": legacy,
            "cutoff": cutoff.isoformat(), "violations": without_kind + transient_without_ttl}


def _stalls(lines: Sequence[TraceLine] | None, window: tuple[datetime, datetime]) -> dict[str, int] | None:
    if lines is None:
        return None
    counts = Counter()
    for line in lines:
        if line.kind == OUTPUT_STALLED and window[0] <= line.ts < window[1]:
            counts[_surface_of(str(line.data.get("correlation_id") or "")) or UNKNOWN] += 1
    return {surface: counts.get(surface, 0) for surface in SURFACES}


def measure(events: Sequence[StoredConversationEvent], *, start: datetime, end: datetime,
            trace_lines: Sequence[TraceLine] | None = None) -> dict[str, Any]:
    """Every Slice 06 metric for the speeches first seen in [start, end). Pure."""
    window = (start, end)
    everything = build_speeches(events)
    speeches = [s for s in everything.values() if s.first_seen is not None and start <= s.first_seen < end]
    turns = build_turns(events)
    surfaces = _session_surfaces(events)
    releases = sorted((stored.event.occurred_at, stored.event.conversation_id) for stored in events
                      if stored.event.event_type is T.MOUTH_FLOOR_RELEASED)
    chain_started: dict[str, datetime] = {}
    for speech in everything.values():
        if speech.started is not None:
            key = speech.chain or speech.speech_id
            chain_started[key] = min(chain_started.get(key, speech.started), speech.started)
    stalls = _stalls(trace_lines, window)
    per_surface: dict[str, Any] = {}
    all_outdated, all_waits = 0, []
    for surface in SURFACES:
        mine = [s for s in speeches if s.surface == surface]
        if not mine:
            continue
        started = [s for s in mine if s.started is not None]
        by_basis: dict[str, list[float]] = defaultdict(list)
        for s in started:
            if s.duration_s is not None:
                label = f"completed/{s.basis or '-'}" if s.terminal == "completed" else f"{s.terminal}/{s.reason or '-'}"
                by_basis[label].append(s.duration_s * 1000)
        outdated = [s for s in started if _outdated(s, turns, chain_started)]
        waits = [w for s in started if s not in outdated and not s.held
                 for w in [_queue_wait_ms(s, list(everything.values()), releases)] if w is not None]
        all_outdated += len(outdated)
        all_waits += waits
        per_surface[surface] = {
            "speeches": len(mine), "started": len(started),
            "started_without_terminal": sum(1 for s in started if s.terminal is None),
            "started_terminals": _count_rows(Counter((s.terminal or "OPEN", s.reason or "-") for s in started)),
            "unstarted_terminals": _count_rows(Counter((s.terminal or "OPEN", s.reason or "-")
                                                       for s in mine if s.started is None)),
            "completed": sum(1 for s in started if s.terminal == "completed"),
            "completed_by_basis": dict(Counter(s.basis or "-" for s in started if s.terminal == "completed")),
            "unconfirmed": sum(1 for s in mine if s.terminal == "unconfirmed"),
            "delivery_not_complete_near_30s": sum(
                1 for s in started if s.terminal == "interrupted" and s.reason == "delivery_not_complete"
                and s.duration_s is not None and NEAR_TIMEOUT_S[0] <= s.duration_s <= NEAR_TIMEOUT_S[1]),
            "duration_ms_by_end": {label: _stats(values) for label, values in sorted(by_basis.items())},
            "release_after_quiescence_ms": _stats([s.release_ms for s in started if s.terminal == "completed"
                                                   and s.basis == COMPLETION_LOCAL_QUIESCENCE
                                                   and s.release_ms is not None]),
            "live_pauses": _pauses(started),
            "outdated_started": len(outdated),
            "current_intent_queue_wait_ms": _stats(waits),
            "output_stalled": None if stalls is None else stalls[surface],
        }
    held = [s for s in speeches if s.held]
    verdicts = Counter()
    for s in held:
        if s.terminal == "superseded" and s.reason in (VERDICT_REVALIDATED, VERDICT_NOT_REVALIDATED):
            verdicts[s.reason] += 1
        elif s.terminal == "expired" and s.reason == HELD_TIMEOUT_REASON:
            verdicts[HELD_TIMEOUT_REASON] += 1
        else:
            verdicts[f"{s.terminal or 'OPEN'}/{s.reason or '-'}"] += 1
    report = {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "speeches": len(speeches),
        "surfaces": per_surface,
        "held": {"speeches": len(held), "by_reason": dict(Counter(r for s in held for _, r in s.held[:1])),
                 "verdicts": dict(verdicts),
                 "held_then_started": sum(1 for s in held if s.started and s.started > s.held[0][0])},
        "floor": _floor(events, window),
        "live_silence_after_barge_in": _live_silence_after_barge_in(events, speeches, surfaces, window),
        "relays": _relays(events, window),
        "outdated_started": all_outdated,
        "current_intent_queue_wait_ms": _stats(all_waits),
    }
    report["targets"] = evaluate_targets(report)
    return report


def _pauses(started: Sequence[Speech]) -> dict[str, Any]:
    """Pauses between sentences of Live speeches ended by local quiescence (who sizes the grace)."""
    measured = [s for s in started if s.pause_count is not None]
    near = LIVE_GRACE_MS * NEAR_GRACE_SHARE
    return {"speeches_measured": len(measured), "speeches_with_pause": sum(1 for s in measured if s.pause_count),
            "pauses": sum(s.pause_count or 0 for s in measured),
            "pauses_ms": _stats([value for s in measured for value in s.pauses_ms]),
            "max_per_speech_ms": _stats([s.pause_max_ms for s in measured if s.pause_count and s.pause_max_ms]),
            "grace_ms": LIVE_GRACE_MS, "floor_ms": LIVE_PAUSE_FLOOR_MS,
            "speeches_with_pause_near_grace": sum(1 for s in measured
                                                  if s.pause_max_ms is not None and s.pause_max_ms >= near)}


def _count_rows(counter: Counter) -> list[dict[str, Any]]:
    return [{"terminal": terminal, "reason": reason, "count": count}
            for (terminal, reason), count in sorted(counter.items())]


def _relay_target(relays: dict[str, Any]) -> tuple[int, bool | None]:
    """Typed violations, plus pre-Slice-03 untyped relays (heuristic, before the cut-off only)."""
    value = relays["violations"] + relays["legacy_heuristic"]
    if value:
        return value, False
    return value, True if relays["typed_by_kind"] else None


def evaluate_targets(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Each target as `pass` / `fail` / `n/a` (nothing measurable in the window)."""
    live = report["surfaces"].get(LIVE)
    release = live["release_after_quiescence_ms"]["p95"] if live else None
    wait = report["current_intent_queue_wait_ms"]["p95"]
    values = {
        "live_release_after_quiescence_p95_ms": (release, None if release is None else release < 1000),
        "live_output_stalled": ((live or {}).get("output_stalled"),
                                None if not live or live["output_stalled"] is None else live["output_stalled"] == 0),
        "live_delivery_not_complete_near_30s": ((live or {}).get("delivery_not_complete_near_30s"),
                                                None if not live else live["delivery_not_complete_near_30s"] == 0),
        "outdated_started": (report["outdated_started"], report["outdated_started"] == 0 if report["speeches"] else None),
        "held_then_started": (report["held"]["held_then_started"],
                              report["held"]["held_then_started"] == 0 if report["held"]["speeches"] else None),
        "current_intent_queue_wait_p95_ms": (wait, None if wait is None else wait < 2000),
        "relay_violations": _relay_target(report["relays"]),
    }
    return [{"metric": key, "label": label, "target": target, "value": values[key][0],
             "verdict": {True: "pass", False: "fail", None: "n/a"}[values[key][1]]}
            for key, label, target in TARGETS]


# --------------------------------------------------------------- reading

@dataclass(frozen=True, slots=True)
class Snapshot:
    path: Path
    warnings: tuple[str, ...]
    info: dict[str, Any]


def _view(path: Path) -> tuple[str, int | None, str | None]:
    """(`integrity_check` first line, event count, last `occurred_at`) of a PRIVATE copy."""
    connection = sqlite3.connect(path)
    try:
        check = " / ".join(connection.execute("PRAGMA integrity_check").fetchone()[0].splitlines()[:2])
        try:
            count, last = connection.execute("SELECT count(*), max(occurred_at) FROM conversation_events").fetchone()
        except sqlite3.Error as exc:
            return check, None, f"unreadable: {exc}"
        return check, count, last
    finally:
        connection.close()


def snapshot_journal(source: Path, into: Path, *, with_wal: bool = False) -> Snapshot:
    """Copy the journal's bytes into `into` and measure the copy; the original is never opened by SQLite.

    Default: the main file alone (Issue `journal-wal-corrupt.md`). The WAL view is
    always checked on a second private copy (main + `-wal`, no `-shm`) and compared.
    `with_wal=True` measures that WAL view instead, refused when it fails integrity.
    """
    if not source.is_file():
        raise MeasureError(f"journal introuvable : {source} [state_database_missing]")
    into.mkdir(parents=True, exist_ok=True)
    wal = source.with_name(source.name + "-wal")
    warnings: list[str] = []
    file_copy = into / "journal-file-only.sqlite3"
    try:
        shutil.copyfile(source, file_copy)
        file_view = _view(file_copy)
        _to_rollback_journal(file_copy)
    except (OSError, sqlite3.Error) as exc:
        raise MeasureError(f"copie du journal impossible ({source}) : {type(exc).__name__}: {exc}") from exc
    info: dict[str, Any] = {"source": str(source), "file_only": {"integrity": file_view[0], "events": file_view[1],
                                                                 "last_event": file_view[2]}}
    wal_view = None
    if wal.is_file() and wal.stat().st_size > 0:
        wal_dir = into / "with-wal"
        wal_dir.mkdir(exist_ok=True)
        wal_copy = wal_dir / source.name
        try:
            shutil.copyfile(source, wal_copy)
            shutil.copyfile(wal, wal_dir / wal.name)
            wal_view = _view(wal_copy)
        except (OSError, sqlite3.Error) as exc:
            wal_view = (f"unreadable: {type(exc).__name__}: {exc}", None, None)
        info["with_wal"] = {"integrity": wal_view[0], "events": wal_view[1], "last_event": wal_view[2],
                            "wal_bytes": wal.stat().st_size}
        if wal_view[0] != "ok":
            warnings.append(f"ATTENTION : la vue AVEC le WAL échoue à l'intégrité ({wal_view[0]}) — "
                            f"mesure faite sur le fichier seul (Issue journal-wal-corrupt.md).")
        elif (wal_view[1] or 0) > (file_view[1] or 0):
            warnings.append(f"ATTENTION : le WAL contient {wal_view[1] - (file_view[1] or 0)} évènements absents du "
                            f"fichier seul (dernier {wal_view[2]}) ; relancer avec --snapshot-with-wal pour les voir.")
    else:
        info["with_wal"] = None
    if file_view[0] != "ok":
        warnings.append(f"ATTENTION : le fichier seul échoue à l'intégrité ({file_view[0]}).")
    if with_wal:
        if wal_view is None:
            warnings.append("aucun WAL à côté du journal : --snapshot-with-wal mesure le fichier seul.")
        elif wal_view[0] != "ok":
            raise MeasureError(f"vue avec WAL refusée : intégrité « {wal_view[0]} » [wal_view_malformed]")
        else:
            wal_copy = into / "with-wal" / source.name
            _to_rollback_journal(wal_copy)
            return Snapshot(wal_copy, tuple(warnings), {**info, "measured": "with_wal"})
    return Snapshot(file_copy, tuple(warnings), {**info, "measured": "file_only"})


def _to_rollback_journal(path: Path) -> None:
    # Private copy only: without its `-shm` a WAL-mode file cannot be opened `mode=ro`;
    # rollback mode lets the canonical read-only reader open it.
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE").fetchone()
    finally:
        connection.close()


def check_live_view(path: Path) -> list[str]:
    """Direct (non-snapshot) read: `quick_check` through a read-only connection, as the reader sees it."""
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            check = connection.execute("PRAGMA quick_check").fetchone()[0].splitlines()[0]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return [f"ATTENTION : journal illisible en lecture seule ({type(exc).__name__}: {exc})."]
    if check != "ok":
        return [f"ATTENTION : la vue lue (avec WAL) échoue à l'intégrité ({check}) — résultats douteux ; "
                f"relancer avec --snapshot (Issue journal-wal-corrupt.md)."]
    return []


@dataclass(frozen=True, slots=True)
class Window:
    name: str
    start: datetime
    end: datetime
    session_id: str | None = None
    conversation_id: str | None = None


async def read_window(db: Path, window: Window, trace: Path | None) -> tuple[dict[str, Any], list[str]]:
    """Read one window through the Test Lab readers, then `measure` it."""
    selector = SessionSelector(conversation_id=window.conversation_id, session_id=window.session_id,
                               start=window.start - WINDOW_MARGIN, end=window.end + WINDOW_MARGIN)
    evidence = await read_session_events(StateDatabaseEventSource(db), selector,
                                         limits=EventReadLimits(max_events=1_000_000, max_conversations=64))
    warnings: list[str] = []
    if evidence.status in (SourceStatus.MISSING, SourceStatus.UNAVAILABLE):
        raise MeasureError(f"journal non lisible : {evidence.status.value} [{evidence.reason}]")
    if evidence.truncated:
        warnings.append(f"{window.name} : lecture du journal tronquée ({len(evidence.events)} évènements).")
    if evidence.skipped_rows:
        warnings.append(f"{window.name} : {evidence.skipped_rows} lignes illisibles ignorées (codec).")
    lines = None
    trace_info: dict[str, Any] | None = None
    if trace is not None:
        result = read_session_trace(trace, selector, start=selector.start, end=selector.end,
                                    limits=TraceReadLimits())
        lines = result.evidence.lines
        trace_info = {"status": result.evidence.status.value, "reason": result.evidence.reason,
                      "lines": len(lines), "truncated": result.evidence.truncated}
        if result.evidence.status in (SourceStatus.MISSING, SourceStatus.UNAVAILABLE) or not lines:
            # A trace that does not cover the window proves nothing: "0 stall" would be a lie.
            warnings.append(f"{window.name} : trace {result.evidence.status.value} "
                            f"[{result.evidence.reason or 'aucune ligne dans la fenêtre'}] — "
                            f"`speech_output_stalled` non mesuré.")
            lines = None
        elif result.evidence.truncated:
            warnings.append(f"{window.name} : trace {result.evidence.status.value} ({len(lines)} lignes) — "
                            f"`speech_output_stalled` est une borne basse.")
    report = measure(evidence.events, start=window.start, end=window.end, trace_lines=lines)
    report["window"].update(name=window.name, session_id=window.session_id, conversation_id=window.conversation_id)
    report["sources"] = {"journal": {"status": evidence.status.value, "events": len(evidence.events),
                                     "skipped_rows": evidence.skipped_rows, "truncated": evidence.truncated},
                         "trace": trace_info}
    return report, warnings


# -------------------------------------------------------------- rendering

def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.0f}" if abs(value) >= 10 else f"{value:.2f}"
    return str(value)


def render(document: dict[str, Any]) -> str:
    out: list[str] = []
    for warning in document["warnings"]:
        out.append(f"! {warning}")
    for report in document["windows"]:
        w = report["window"]
        out.append(f"\n## {w['name']}  [{w['start']} .. {w['end']}[  — {report['speeches']} paroles")
        for surface, s in report["surfaces"].items():
            out.append(f"  {surface}: {s['speeches']} paroles, {s['started']} démarrées, {s['completed']} completed "
                       f"{s['completed_by_basis'] or ''}, {s['unconfirmed']} unconfirmed, "
                       f"{s['delivery_not_complete_near_30s']} delivery_not_complete ~30 s, "
                       f"{s['started_without_terminal']} sans fin, stalls {_fmt(s['output_stalled'])}")
            for row in s["started_terminals"]:
                out.append(f"      {row['count']:5d}  {row['terminal']:12s} {row['reason']}")
            for label, stats in s["duration_ms_by_end"].items():
                out.append(f"      durée {label}: n={stats['count']} p50={_fmt(stats['p50'])} "
                           f"p95={_fmt(stats['p95'])} max={_fmt(stats['max'])} ms")
            pauses = s["live_pauses"]
            if pauses["speeches_measured"]:
                values = pauses["pauses_ms"]
                out.append(f"      pauses entre phrases: {pauses['pauses']} dans {pauses['speeches_with_pause']}/"
                           f"{pauses['speeches_measured']} paroles, p50={_fmt(values['p50'])} "
                           f"p95={_fmt(values['p95'])} max={_fmt(pauses['max_per_speech_ms']['max'])} ms ; "
                           f"≥ {NEAR_GRACE_SHARE:g}× grâce ({pauses['grace_ms']} ms): "
                           f"{pauses['speeches_with_pause_near_grace']} paroles")
        held = report["held"]
        floor = report["floor"]
        silence = report["live_silence_after_barge_in"]
        relays = report["relays"]
        out.append(f"  retenues: {held['speeches']} {held['by_reason']} verdicts {held['verdicts']} "
                   f"retenue→démarrée {held['held_then_started']}")
        out.append(f"  parole: prise {floor['taken_by_while']} rendue {floor['released_by_reason']} "
                   f"durée p95 {_fmt(floor['duration_ms']['p95'])} ms")
        out.append(f"  Live après barge-in: {silence['barge_ins']} coupures, prochaine parole entendue p50 "
                   f"{_fmt(silence['next_heard_ms']['p50'])} ms, jamais {silence['never_heard_again']}, "
                   f"unconfirmed entre-temps {silence['unconfirmed_before_next_heard']}")
        out.append(f"  relais typés {relays['typed_by_kind']} sans genre {relays['without_kind']} "
                   f"transitoires sans TTL {relays['transient_without_ttl']} "
                   f"non typés d'avant S03 (heuristique, avant {relays['cutoff'][:10]}) {relays['legacy_heuristic']}")
    names = [report["window"]["name"] for report in document["windows"]]
    out.append("\n## Cibles (Slice 06)")
    out.append("  " + " | ".join(["métrique", "cible", *names]))
    for index, (key, label, target) in enumerate(TARGETS):
        cells = [f"{_fmt(r['targets'][index]['value'])} {r['targets'][index]['verdict']}" for r in document["windows"]]
        out.append("  " + " | ".join([label, target, *cells]))
    return "\n".join(out)


# -------------------------------------------------------------------- CLI

def parse_instant(text: str, *, end: bool = False) -> datetime:
    """ISO instant (naive = UTC) or a date; a date as an END means the end of that day."""
    text = text.strip()
    try:
        if len(text) == 10:
            day = date.fromisoformat(text)
            value = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            return value + timedelta(days=1) if end else value
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"instant illisible : {text!r} (ISO 8601 ou AAAA-MM-JJ)") from None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_window(text: str) -> Window:
    name, sep, span = text.partition("=")
    if not sep or ".." not in span:
        raise argparse.ArgumentTypeError(f"fenêtre attendue NOM=DEBUT..FIN, reçu {text!r}")
    first, last = span.split("..", 1)
    start, end = parse_instant(first), parse_instant(last, end=True)
    if end <= start:
        raise argparse.ArgumentTypeError(f"fenêtre {name!r} : la fin précède le début")
    return Window(name.strip() or "window", start, end)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="measure_speech_metrics",
        description="Métriques de présentation de la parole (Slice 06) lues dans le journal des évènements "
                    "de conversation, en lecture seule.")
    parser.add_argument("--db", type=Path, default=Path("data/state/jarvis.sqlite3"),
                        help="journal Core (SQLite) ; défaut data/state/jarvis.sqlite3")
    parser.add_argument("--trace", type=Path, help="runtime/trace.jsonl, pour `speech_output_stalled`")
    parser.add_argument("--from", dest="start", help="début de la fenêtre (ISO ou AAAA-MM-JJ, UTC)")
    parser.add_argument("--to", dest="end", help="fin de la fenêtre (exclue ; une date = fin de ce jour)")
    parser.add_argument("--session", help="identifiant de session voix (filtre)")
    parser.add_argument("--conversation", help="identifiant de conversation (filtre)")
    parser.add_argument("--window", action="append", type=parse_window, default=[],
                        help="fenêtre nommée NOM=DEBUT..FIN (répétable) ; plusieurs = comparaison avant/après")
    parser.add_argument("--baseline", action="store_true",
                        help="ajoute les fenêtres de référence 18–21/09 et 28/09 12:54–12:59Z (READINESS B2)")
    snap = parser.add_mutually_exclusive_group()
    snap.add_argument("--snapshot", action="store_true",
                      help="copie le fichier SANS son WAL et mesure la copie (vérifie la vue avec WAL à part)")
    snap.add_argument("--snapshot-with-wal", action="store_true",
                      help="copie fichier + WAL et mesure la copie, refusé si la vue avec WAL est corrompue")
    parser.add_argument("--snapshot-dir", type=Path, help="garder la copie ici (défaut : dossier temporaire effacé)")
    parser.add_argument("--json", action="store_true", help="sortie JSON seule sur stdout")
    return parser


def _windows(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[Window]:
    windows: list[Window] = []
    if args.baseline:
        windows += [Window(name, start, end) for name, start, end in BASELINE_WINDOWS]
    if args.start or args.end:
        if not (args.start and args.end):
            parser.error("--from et --to vont ensemble")
        try:
            windows.append(Window("window", parse_instant(args.start), parse_instant(args.end, end=True)))
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
    windows += args.window
    if not windows and (args.session or args.conversation):
        windows.append(Window("session", datetime(2000, 1, 1, tzinfo=timezone.utc),
                              datetime.now(timezone.utc) + timedelta(days=1)))
    if not windows:
        parser.error("donner une fenêtre (--from/--to, --window, --baseline) ou --session/--conversation")
    return [Window(w.name, w.start, w.end, args.session, args.conversation) for w in windows]


def run(args: argparse.Namespace, windows: Sequence[Window]) -> dict[str, Any]:
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="jarvis-speech-metrics-") as scratch:
        db, snapshot_info = args.db, None
        if args.snapshot or args.snapshot_with_wal:
            snap = snapshot_journal(args.db, args.snapshot_dir or Path(scratch), with_wal=args.snapshot_with_wal)
            db, snapshot_info = snap.path, snap.info
            warnings += snap.warnings
        else:
            if not args.db.is_file():
                raise MeasureError(f"journal introuvable : {args.db} [state_database_missing]")
            warnings += check_live_view(args.db)
        reports = []
        for window in windows:
            report, notes = asyncio.run(read_window(db, window, args.trace))
            reports.append(report)
            warnings += notes
    return {"schema": "jarvis.speech_metrics", "schema_version": 1, "db": str(args.db), "snapshot": snapshot_info,
            "warnings": warnings, "windows": reports}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass  # intentional: a console that cannot switch keeps its encoding; output still flows
    windows = _windows(args, parser)
    print(f"mesure : {args.db} ({len(windows)} fenêtre(s))", file=sys.stderr)
    try:
        document = run(args, windows)
    except MeasureError as exc:
        print(f"Mesure impossible : {exc}", file=sys.stderr)
        return EXIT_INCONCLUSIVE
    if args.json:
        for warning in document["warnings"]:
            print(warning, file=sys.stderr)
    print(json.dumps(document, ensure_ascii=False, indent=2) if args.json else render(document))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
