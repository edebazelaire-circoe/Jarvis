"""Known anomaly signatures of a DiagnosticBundle: deterministic, versioned, table-driven.

Binding contract: `docs/testlab.md` ("DiagnosticBundle", "Anomaly rules"). Pure:
no I/O, no clock, no model. A rule reads the sections the builder already
derived (never raw logs) plus thresholds declared as data, and reports findings
with the evidence references that triggered them.

Every time horizon (the window after a barge-in, the grace before an outcome is
missing) is bounded by the **voice session segment** of its subject
(`RuleContext.segments`): evidence of a later session never decides a finding.

Extending: add an `AnomalyRule` to `DEFAULT_RULES` and its evaluator to
`RULE_EVALUATORS` (same `rule_id`), document the row in `docs/testlab.md`, and
bump `version` whenever the rule's meaning or a default threshold changes.

A rule is evaluated only when at least one of the sources it `requires_any` was
read (`available`, `empty` or `truncated`); otherwise it is listed with
`evaluated: false`, so an absent finding is never mistaken for a clean session.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from types import MappingProxyType
from typing import Any

from jarvis.testlab.bundle import BargeInOutcome, SpeechOutcome
from jarvis.testlab.validation import check_number, fail, format_time, parse_time

SOURCE_CONVERSATION_EVENTS = "conversation_events"
SOURCE_RUNTIME_JOURNAL = "runtime_journal"
_SOURCES = frozenset({SOURCE_CONVERSATION_EVENTS, SOURCE_RUNTIME_JOURNAL})
_RULE_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_THRESHOLD_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
MAX_FINDING_EVIDENCE = 32


@dataclass(frozen=True, slots=True)
class AnomalyRule:
    """One declared signature: stable id, version, the sources it needs and its thresholds (data)."""

    rule_id: str
    version: int
    requires_any: frozenset[str]
    thresholds: Mapping[str, int | float] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or len(self.rule_id) > 64 or not _RULE_ID.fullmatch(self.rule_id):
            raise fail("rule_id must be a dotted lowercase name of at most 64 characters")
        if type(self.version) is not int or not 1 <= self.version <= 2**31 - 1:
            raise fail("rule version must be a positive integer")
        if not isinstance(self.requires_any, frozenset) or not self.requires_any or not self.requires_any <= _SOURCES:
            raise fail(f"requires_any must be a nonempty subset of {', '.join(sorted(_SOURCES))}")
        if not isinstance(self.thresholds, Mapping) or len(self.thresholds) > 16:
            raise fail("thresholds must be a mapping of at most 16 entries")
        for name, value in self.thresholds.items():
            if not isinstance(name, str) or not _THRESHOLD_NAME.fullmatch(name):
                raise fail("threshold names must be lowercase snake_case")
            check_number(value, f"thresholds.{name}", minimum=0)
        object.__setattr__(self, "thresholds", MappingProxyType(dict(sorted(self.thresholds.items()))))

    def row(self, *, evaluated: bool) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "version": self.version, "evaluated": evaluated,
                "skipped_reason": None if evaluated else "source_unavailable",
                "thresholds": [{"name": name, "value": value} for name, value in self.thresholds.items()]}


@dataclass(frozen=True, slots=True)
class Segment:
    """One voice session segment of the evidence (docs/testlab.md, "Voice session segments")."""

    start: datetime
    end: datetime
    #: Journal kind that closed the segment (`voice.stop`, `voice.failure`, `audio.device_closed`), else None.
    end_kind: str | None = None


@dataclass(frozen=True, slots=True)
class RuleContext:
    """What rules read. Sections are the JSON-ready items the builder emits (times as wire text)."""

    turns: Sequence[Mapping[str, Any]]
    speech: Sequence[Mapping[str, Any]]
    barge_in: Sequence[Mapping[str, Any]]
    latency: Sequence[Mapping[str, Any]]
    #: speech_id -> normalized payload text (`normalize_payload`). In memory only, never emitted.
    speech_payloads: Mapping[str, str]
    #: `reconstruct_conversation` anomalies: (item_id, started_at, code, event_id).
    reconstruction: Sequence[tuple[str, datetime, str, str]]
    #: Voice session segments in time order (contiguous, non-overlapping).
    segments: Sequence[Segment]
    #: Session-ending or failure facts in time order: (at, cause code, evidence refs).
    failures: Sequence[tuple[datetime, str, tuple[str, ...]]]
    #: Sources that were read (`available`, `empty`, `truncated`).
    read_sources: frozenset[str]


def normalize_payload(text: str) -> str:
    """Comparison form of a speech payload: case-folded, whitespace collapsed."""
    return " ".join(text.casefold().split())


def segment_of(segments: Sequence[Segment], at: datetime) -> Segment | None:
    """The segment whose start is the latest one at or before `at`."""
    index = bisect.bisect_right([segment.start for segment in segments], at) - 1
    return segments[index] if index >= 0 else None


def _t(value: str | None) -> datetime | None:
    return parse_time(value, "time", optional=True)


def _ms(delta: timedelta) -> int:
    return int(delta / timedelta(milliseconds=1))


def _finding(rule: AnomalyRule, *, at: str, subject_kind: str, subject_id: str, measured: Mapping[str, Any],
             evidence: Sequence[str]) -> dict[str, Any]:
    refs = sorted(dict.fromkeys(evidence))[:MAX_FINDING_EVIDENCE]
    return {"rule_id": rule.rule_id, "rule_version": rule.version, "at": at, "subject_kind": subject_kind,
            "subject_id": subject_id, "measured": [{"name": name, "value": value} for name, value in measured.items()],
            "evidence": refs}


# ------------------------------------------------------------- evaluators

def _self_barge_in(rule: AnomalyRule, context: RuleContext) -> list[dict[str, Any]]:
    """Confirmed barge-in of audible Jarvis output, with no user activity within the window.

    Audible: `played_ms > 0`, or a first audible/device write on the episode's
    output before the episode. User activity is the episode's
    `next_user_activity_ms` (see the builder's `user_activity_at`: an onset still
    open, an onset after, or a commit/transcript/turn submission closing an
    utterance already under way; same segment). The
    horizon is the episode start plus the window, bounded by its segment: an
    episode whose segment ends before the window closes is undecidable and gives
    no finding.
    """
    window_ms = rule.thresholds["user_activity_window_ms"]
    findings = []
    for episode in context.barge_in:
        if (episode["outcome"] != BargeInOutcome.CONFIRMED or episode["jarvis_speaking"] is not True
                or episode["audible"] is not True):
            continue  # only a cut of audible Jarvis output can be a self barge-in
        gap = episode["next_user_activity_ms"]
        if gap is not None and gap <= window_ms:
            continue
        started = _t(episode["started_at"])
        segment = segment_of(context.segments, started)
        if segment is None or segment.end < started + timedelta(milliseconds=window_ms):
            continue
        findings.append(_finding(rule, at=episode["started_at"], subject_kind="barge_in_episode",
                                 subject_id=episode["episode_id"],
                                 measured={"played_ms": episode["played_ms"],
                                           "stop_latency_ms": episode["stop_latency_ms"],
                                           "next_user_activity_ms": gap},
                                 evidence=episode["evidence"]))
    return findings


def _delivered_after_supersession(rule: AnomalyRule, context: RuleContext) -> list[dict[str, Any]]:
    """A start, completion or interruption later than the speech's own supersession or expiry."""
    findings = []
    for speech in context.speech:
        retired = [terminal for terminal in speech["terminals"]
                   if terminal["outcome"] in (SpeechOutcome.SUPERSEDED, SpeechOutcome.STALE)]
        if not retired:
            continue
        retire = min(retired, key=lambda terminal: terminal["at"])
        retire_at = _t(retire["at"])
        candidates = ([speech["started_at"]] if speech["started_at"] is not None else []) + [
            terminal["at"] for terminal in speech["terminals"]
            if terminal["outcome"] in (SpeechOutcome.SPOKEN, SpeechOutcome.INTERRUPTED)]
        late = sorted(value for value in candidates if _t(value) > retire_at)
        if not late:
            continue
        findings.append(_finding(rule, at=late[0], subject_kind="speech", subject_id=speech["speech_id"],
                                 measured={"retired_as": retire["outcome"], "delay_ms": _ms(_t(late[0]) - retire_at)},
                                 evidence=speech["evidence"]))
    return findings


def _duplicate_payload(rule: AnomalyRule, context: RuleContext) -> list[dict[str, Any]]:
    """Two delivered speeches of one conversation and one segment with the same payload within `window_ms`."""
    window = rule.thresholds["window_ms"]
    groups: dict[tuple[str | None, str], list[Mapping[str, Any]]] = {}
    for speech in context.speech:
        payload = context.speech_payloads.get(speech["speech_id"])
        if speech["started_at"] is None or payload is None or len(payload) < rule.thresholds["min_chars"]:
            continue
        groups.setdefault((speech["conversation_id"], payload), []).append(speech)
    findings = []
    for _, items in sorted(groups.items(), key=lambda entry: (entry[0][0] or "", entry[0][1])):
        items.sort(key=lambda item: (item["started_at"], item["speech_id"]))
        for first, second in zip(items, items[1:]):
            gap = _ms(_t(second["started_at"]) - _t(first["started_at"]))
            if gap > window or segment_of(context.segments, _t(first["started_at"])) != segment_of(
                    context.segments, _t(second["started_at"])):
                continue
            findings.append(_finding(rule, at=second["started_at"], subject_kind="speech",
                                     subject_id=second["speech_id"],
                                     measured={"gap_ms": gap, "chars": len(context.speech_payloads[second["speech_id"]])},
                                     evidence=[*second["evidence"], *first["evidence"]]))
    return findings


def _missing_delivery_outcome(rule: AnomalyRule, context: RuleContext) -> list[dict[str, Any]]:
    """Speech queued, started or dropped with no terminal outcome before its segment ends.

    Flagged when the segment continues at least `grace_ms` after the speech's
    last stage, or when the segment was closed by a session end
    (`voice.stop`, `voice.failure`, `audio.device_closed`). `silent_ms` runs to
    the segment end, never past it; `cause` is the first session-ending or
    failure fact after the last stage inside the segment.
    """
    grace = timedelta(milliseconds=rule.thresholds["grace_ms"])
    findings = []
    for speech in context.speech:
        if speech["outcome"] not in (SpeechOutcome.QUEUED, SpeechOutcome.STARTED, SpeechOutcome.DROPPED):
            continue
        last_wire = max(value for value in (speech["requested_at"], speech["queued_at"], speech["dispatched_at"],
                                            speech["started_at"]) if value is not None)
        last = _t(last_wire)
        segment = segment_of(context.segments, last)
        if segment is None or (segment.end - last < grace and segment.end_kind is None):
            continue
        cause = next(((code, refs) for at, code, refs in context.failures if last <= at <= segment.end), None)
        findings.append(_finding(rule, at=last_wire, subject_kind="speech", subject_id=speech["speech_id"],
                                 measured={"state": speech["outcome"], "silent_ms": _ms(segment.end - last),
                                           "cause": None if cause is None else cause[0],
                                           "segment_end": segment.end_kind},
                                 evidence=[*speech["evidence"], *(() if cause is None else cause[1])]))
    return findings


def _latency_above_threshold(rule: AnomalyRule, context: RuleContext) -> list[dict[str, Any]]:
    """A joined latency measure strictly above its declared threshold (thresholds named after measures)."""
    findings = []
    for join in context.latency:
        stages = {stage["stage"]: stage for stage in join["stages"]}
        for measure in join["measures"]:
            threshold = rule.thresholds.get(measure["name"])
            if threshold is None or measure["ms"] <= threshold:
                continue
            source, target = stages[measure["from_stage"]], stages[measure["to_stage"]]
            findings.append(_finding(rule, at=target["at"], subject_kind="latency_join",
                                     subject_id=f"{join['join_id']}#{measure['name']}",
                                     measured={"measure": measure["name"], "ms": measure["ms"],
                                               "threshold_ms": threshold},
                                     evidence=[*source["evidence"], *target["evidence"]]))
    return findings


def _reconstruction_anomaly(rule: AnomalyRule, context: RuleContext) -> list[dict[str, Any]]:
    """Inconsistencies `reconstruct_conversation` absorbed (duplicate span open/close, close before open, conflict)."""
    return [_finding(rule, at=format_time(started_at), subject_kind="conversation_item", subject_id=item_id,
                     measured={"code": code}, evidence=[event_id])
            for item_id, started_at, code, event_id in context.reconstruction]


_BOTH = frozenset({SOURCE_CONVERSATION_EVENTS, SOURCE_RUNTIME_JOURNAL})
_JOURNAL = frozenset({SOURCE_RUNTIME_JOURNAL})

#: The declared rule table (docs/testlab.md, "Anomaly rules"). Thresholds are data.
#: `voice.state.spoken_diverged` is deliberately NOT a rule: its producer compares raw strings
#: (docs/testlab.md, "Why no payload divergence rule"); speech items only count it.
DEFAULT_RULES: tuple[AnomalyRule, ...] = (
    AnomalyRule("voice.self_barge_in", 1, _JOURNAL, {"user_activity_window_ms": 20000},
                "Confirmed barge-in of audible Jarvis output, with no user activity within the window."),
    AnomalyRule("speech.delivered_after_supersession", 1, _BOTH, {},
                "Speech started, completed or interrupted after its own supersession or expiry."),
    AnomalyRule("speech.duplicate_payload", 1, frozenset({SOURCE_CONVERSATION_EVENTS}),
                {"window_ms": 120000, "min_chars": 12},
                "Two delivered speeches of one conversation carrying the same payload within the window."),
    AnomalyRule("speech.missing_delivery_outcome", 1, _BOTH, {"grace_ms": 30000},
                "Speech queued, started or dropped without a terminal delivery outcome in its session."),
    AnomalyRule("latency.above_threshold", 1, _BOTH,
                {"user_turn_end_to_first_audio_ms": 8000, "speech_queue_free_to_started_ms": 3000,
                 "speech_started_to_first_audio_ms": 4000},
                "Joined latency measure above its declared threshold."),
    AnomalyRule("events.reconstruction_anomaly", 1, frozenset({SOURCE_CONVERSATION_EVENTS}), {},
                "Conversation Events inconsistency absorbed by reconstruct_conversation."),
)

RULE_EVALUATORS: Mapping[str, Callable[[AnomalyRule, RuleContext], list[dict[str, Any]]]] = MappingProxyType({
    "voice.self_barge_in": _self_barge_in,
    "speech.delivered_after_supersession": _delivered_after_supersession,
    "speech.duplicate_payload": _duplicate_payload,
    "speech.missing_delivery_outcome": _missing_delivery_outcome,
    "latency.above_threshold": _latency_above_threshold,
    "events.reconstruction_anomaly": _reconstruction_anomaly,
})

#: Thresholds each evaluator reads (a supplied rule must declare them).
REQUIRED_THRESHOLDS: Mapping[str, frozenset[str]] = MappingProxyType({
    "voice.self_barge_in": frozenset({"user_activity_window_ms"}),
    "speech.duplicate_payload": frozenset({"window_ms", "min_chars"}),
    "speech.missing_delivery_outcome": frozenset({"grace_ms"}),
})


def check_rules(rules: Sequence[AnomalyRule]) -> None:
    """Every rule has an evaluator, its required thresholds, and a unique id."""
    if not isinstance(rules, tuple) or any(not isinstance(rule, AnomalyRule) for rule in rules):
        raise fail("rules must be a tuple of AnomalyRule")
    if len({rule.rule_id for rule in rules}) != len(rules) or len(rules) > 64:
        raise fail("rules must have unique ids (at most 64 rules)")
    for rule in rules:
        if rule.rule_id not in RULE_EVALUATORS:
            raise fail(f"rule {rule.rule_id} has no registered evaluator")
        missing = REQUIRED_THRESHOLDS.get(rule.rule_id, frozenset()) - set(rule.thresholds)
        if missing:
            raise fail(f"rule {rule.rule_id} misses threshold(s) {', '.join(sorted(missing))}")


def evaluate_rules(rules: Sequence[AnomalyRule], context: RuleContext) -> tuple[list[dict[str, Any]],
                                                                               list[dict[str, Any]]]:
    """(rule rows, findings sorted by time, rule id and subject). Pure and deterministic."""
    check_rules(rules)
    rows, findings = [], []
    for rule in rules:
        evaluated = bool(rule.requires_any & context.read_sources)
        rows.append(rule.row(evaluated=evaluated))
        if evaluated:
            findings.extend(RULE_EVALUATORS[rule.rule_id](rule, context))
    findings.sort(key=lambda item: (item["at"], item["rule_id"], item["subject_id"]))
    return rows, findings
