"""Core <-> Voice contract for armed cues (handoff jarvis-interactive-presentation-studio, Slice 12 owns it, Slice 13 follows it).

The armed cue set lives in Core (it follows the playback position, which needs the scene service and survives a Voice
crash). The cue **follower** lives in Voice next to the ambient lane (R5). Two seams, both decided here:

1. **Core -> Voice: invalidate, then pull.** Same pattern as `interaction.mode.changed` (event, then snapshot): Core
   publishes a content-free bus message `presentation_studio.armed.changed` `{run_id, generation, count}` on the stream
   Voice already subscribes to, and the follower fetches `GET /v1/presentation-studio/playback/armed` (bearer, loopback).
   The phrases never travel on the bus or in an event, a trace or a log: only the pull carries them, and the pull is not
   relayed to the Control Center page. A follower that (re)subscribes simply pulls: nothing is lost by a missed message.
2. **Voice -> Core: a typed report, never text.** `POST /v1/presentation-studio/cues/satisfied`
   `{run_id, generation, cue_id}`. Extra keys are refused (no `text`, no `transcript`). The report is judged against the
   state Core holds *now*: right run, current generation, not expired, id in the armed set, one report per (run,
   generation, cue) answered once, bounded rate.

Pure: no clock (callers pass monotonic seconds), no I/O.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jarvis.domain.presentation_studio_playback import PlaybackPlan, PlaybackState
from jarvis.domain.presentation_studio_score import CUE_ID

#: Bus message type published when the armed set changes (content-free).
ARMED_CHANGED = "presentation_studio.armed.changed"
#: How long Core honours a set after the follower last pulled it. A pull renews it: a live follower polls at TTL/3,
#: a dead one stops being obeyed. The Human-visible effect of a dead follower is "cues no longer fire", never a stray fire.
ARMED_SET_TTL_S = 90.0
#: At most this many reports per second, with a short burst (a follower in a loop must not hammer the run).
REPORT_RATE_PER_S = 3.0
REPORT_BURST = 5
#: Answers remembered for idempotency (a retry of a report that already fired returns the same answer).
REMEMBERED_REPORTS = 8
MAX_ARMED_CUES = 4


class ReportCode(StrEnum):
    STALE_RUN = "stale_run"
    STALE_GENERATION = "stale_generation"
    EXPIRED = "armed_set_expired"
    NOT_ARMED = "cue_not_armed"
    RATE_LIMITED = "rate_limited"
    MALFORMED = "malformed_report"


@dataclass(frozen=True, slots=True)
class ArmedCue:
    cue_id: str
    #: Normalised phrases and semantic labels (Slice 10): finite sets, no pattern.
    phrases: tuple[str, ...]
    semantics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"cue_id": self.cue_id, "phrases": list(self.phrases), "semantics": list(self.semantics)}


@dataclass(frozen=True, slots=True)
class ArmedSetMessage:
    """What the follower pulls. `cues == ()` means "nothing is armed": the follower must produce nothing."""

    run_id: str | None
    generation: int
    expires_in_s: float
    cues: tuple[ArmedCue, ...]
    #: phrase -> cue ids, only phrases that name more than one cue of THIS armed set: the follower must not fire on them.
    ambiguous: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "generation": self.generation, "expires_in_s": self.expires_in_s,
                "cues": [c.to_dict() for c in self.cues], "ambiguous": {p: list(ids) for p, ids in self.ambiguous}}


def build_armed_set(plan: PlaybackPlan | None, state: PlaybackState, *, ttl_s: float = ARMED_SET_TTL_S) -> ArmedSetMessage:
    """The message for the current state. Pure; the cues come from the stored score, never from anything said."""

    if plan is None or not state.armed or state.run_id is None:
        return ArmedSetMessage(state.run_id, state.generation, ttl_s, ())
    cues = tuple(ArmedCue(cue_id, plan.cues[cue_id].predicate.phrases, plan.cues[cue_id].predicate.semantics)
                 for cue_id in state.armed[:MAX_ARMED_CUES])
    return ArmedSetMessage(state.run_id, state.generation, ttl_s, cues,
                           _ambiguous(cues))


def _ambiguous(cues: tuple[ArmedCue, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Phrases that name more than one cue of the armed set (the same logic as `ambiguous_phrases`, over the armed ids)."""

    seen: dict[str, list[str]] = {}
    for cue in cues:
        for phrase in cue.phrases:
            seen.setdefault(phrase, []).append(cue.cue_id)
    return tuple((phrase, tuple(sorted(ids))) for phrase, ids in sorted(seen.items()) if len(ids) > 1)


def changed_payload(state: PlaybackState) -> dict[str, Any]:
    """The bus payload: identity and size only, never a phrase."""

    return {"run_id": state.run_id, "generation": state.generation, "count": len(state.armed)}


@dataclass(frozen=True, slots=True)
class CueReport:
    run_id: str
    generation: int
    cue_id: str


def parse_cue_report(raw: object) -> CueReport:
    """Strict: exactly `{run_id, generation, cue_id}`. Anything else (text included) is `ValueError`, a 400."""

    if not isinstance(raw, dict) or set(raw) != {"run_id", "generation", "cue_id"}:
        raise ValueError("a cue report is exactly {run_id, generation, cue_id}")
    run_id, generation, cue_id = raw["run_id"], raw["generation"], raw["cue_id"]
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 64:
        raise ValueError("run_id must be a string of 1-64 characters")
    if type(generation) is not int or generation < 0:
        raise ValueError("generation must be a non-negative integer")
    if not isinstance(cue_id, str) or not CUE_ID.fullmatch(cue_id):
        raise ValueError("cue_id must be a psc_ id")
    return CueReport(run_id, generation, cue_id)


class ReportLimiter:
    """Token bucket over caller-supplied monotonic seconds."""

    def __init__(self, rate_per_s: float = REPORT_RATE_PER_S, burst: int = REPORT_BURST) -> None:
        self._rate, self._burst = rate_per_s, float(burst)
        self._tokens, self._at = float(burst), None

    def allow(self, now_s: float) -> bool:
        if self._at is not None:
            self._tokens = min(self._burst, self._tokens + max(0.0, now_s - self._at) * self._rate)
        self._at = now_s
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True


class ReportLedger:
    """Remembers the answer of the last reports: a duplicate gets the same answer and fires nothing."""

    def __init__(self, size: int = REMEMBERED_REPORTS) -> None:
        self._answers: OrderedDict[tuple[str, int, str], dict[str, Any]] = OrderedDict()
        self._size = size

    def get(self, report: CueReport) -> dict[str, Any] | None:
        return self._answers.get((report.run_id, report.generation, report.cue_id))

    def remember(self, report: CueReport, answer: dict[str, Any]) -> None:
        self._answers[(report.run_id, report.generation, report.cue_id)] = answer
        while len(self._answers) > self._size:
            self._answers.popitem(last=False)

    def clear(self) -> None:
        self._answers.clear()


__all__ = ["ARMED_CHANGED", "ARMED_SET_TTL_S", "ArmedCue", "ArmedSetMessage", "CueReport", "ReportCode", "ReportLedger",
           "ReportLimiter", "build_armed_set", "changed_payload", "parse_cue_report"]
