"""Locked-sequence executor of the Presentation Studio, pure (handoff jarvis-interactive-presentation-studio, Slice 14).

A locked sequence is a segment of choreography whose relative timing is exact (`LockedSequence`: steps at `offset_ms`,
strictly increasing from 0, a `duration_ms`). This module answers, with no clock of its own and no I/O, *when each step
is due and what an interruption may do*:

- `SequenceSchedule` is the compiled, read-only timeline of one sequence;
- `SequenceClock` is its run state. **Every due time is `t0 + shift + offset`**, computed from the sequence start (t0),
  never from the previous step: a late poll delays one release (`late_ms` in the action log) and moves nothing else, so
  no drift can accumulate. `shift` is the time spent paused, added whole on resume, so a pause preserves every
  remaining offset exactly;
- `input_verdict` / `interruption_plan` are the interruption policy (`allow` / `at_boundary` / `refuse`) as data, so the
  executor and the tests read the same table. The playback machine (`presentation_studio_playback.apply`) enforces the
  same table; `tests/unit/test_presentation_studio_sequence.py` proves they agree on every cell.

Synchronisation with speech (policy, decided here): **t0 is the instant the first spoken line of the sequence started**
(`mouth.speech.started`) when the step at offset 0 is a Jarvis step. That fact is recorded when the scheduler asks the voice
surface to GENERATE the speech, before the first audio is written (no first-audio fact is exposed), so the first visuals lead
the first sound by the provider's generation latency and the line can still be cancelled inside that window; otherwise (a silent first step, or a run where Jarvis does not speak) t0 is the explicit start. The wait for
the speech to start is bounded by the presenter (`speech_not_started` is a visible failure, never a hang). Later spoken
steps are *issued* at their offset; the audio follows with the voice stack's own latency, which the presenter measures
and records (`lag_ms`) but cannot change.

Contract: `docs/presentation-studio.md` > *Jarvis presenter and locked sequences*.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from jarvis.domain.presentation_studio_score import Interruption, LockedSequence, SequenceInterrupt

#: Action log bound (the log is an inspection aid and a determinism witness, never a record of what was said).
MAX_LOG_ENTRIES = 256


# ------------------------------------------------------------------ the interruption policy, as data


class InputKind(StrEnum):
    #: The user's explicit address (a barge-in, an admitted turn), a pause request, a detour: an *interruption*.
    PAUSE = "pause"
    DETOUR = "detour"
    #: next / previous / goto / a cue: moving the timeline from outside while a sequence owns it.
    NAVIGATE = "navigate"
    #: An explicit stop: always honoured.
    STOP = "stop"
    #: The user-only escape (`skip_sequence`): always honoured, whatever the policy says.
    SKIP = "skip"


class Verdict(StrEnum):
    NOW = "now"
    #: Takes effect at the next step boundary (or the end of the sequence).
    AT_BOUNDARY = "at_boundary"
    REFUSE = "refuse"


def input_verdict(interruption: Interruption, kind: InputKind) -> Verdict:
    """What a sequence owning the timeline does with an input, by the host item's declared `interruption`.

    - `stop` and `skip` are never refused: a presenter must always be able to get out.
    - `navigate` is refused whatever the policy: a sequence that owns the timeline is not moved from outside
      (`locked_sequence_active`); the policy governs interruptions, not seeking.
    - `pause` and `detour` follow the policy exactly: `allow` -> now, `at_boundary` -> at the boundary, `refuse` -> refused.
    """

    interruption, kind = Interruption(interruption), InputKind(kind)
    if kind in (InputKind.STOP, InputKind.SKIP):
        return Verdict.NOW
    if kind is InputKind.NAVIGATE:
        return Verdict.REFUSE
    return {Interruption.ALLOW: Verdict.NOW, Interruption.AT_BOUNDARY: Verdict.AT_BOUNDARY,
            Interruption.REFUSE: Verdict.REFUSE}[interruption]


@dataclass(frozen=True, slots=True)
class InterruptionPlan:
    """What the executor does when the user addresses Jarvis mid-sequence."""

    verdict: Verdict
    #: `abort_to_recovery`: when the user says "continue", the sequence is left through its recovery point (position =
    #: the recovery point, exactly). `pause_resume`: the sequence continues from its remaining offsets.
    recover_on_resume: bool


def interruption_plan(interruption: Interruption, on_interrupt: SequenceInterrupt) -> InterruptionPlan:
    """The run is *paused* by the interruption (policy applied by the playback machine), never auto-resumed; the sequence's
    own `on_interrupt` only says where an explicit continue lands."""

    return InterruptionPlan(input_verdict(interruption, InputKind.PAUSE),
                            SequenceInterrupt(on_interrupt) is SequenceInterrupt.ABORT_TO_RECOVERY)


# ------------------------------------------------------------------ the schedule (compiled, read-only)


@dataclass(frozen=True, slots=True)
class SequenceSchedule:
    sequence_id: str
    step_ids: tuple[str, ...]
    offsets_ms: tuple[int, ...]
    duration_ms: int

    def __post_init__(self) -> None:
        if not self.offsets_ms or len(self.offsets_ms) != len(self.step_ids):
            raise ValueError("a schedule has one offset per step and at least one step")
        if self.offsets_ms[0] != 0 or any(b <= a for a, b in zip(self.offsets_ms, self.offsets_ms[1:])):
            raise ValueError("offsets start at 0 and strictly increase")
        if self.duration_ms <= self.offsets_ms[-1]:
            raise ValueError("duration_ms must exceed the last offset")

    @classmethod
    def of(cls, sequence: LockedSequence) -> SequenceSchedule:
        timeline = sequence.timeline()
        return cls(sequence.sequence_id, tuple(step_id for _, step_id in timeline),
                   tuple(offset for offset, _ in timeline), sequence.duration_ms)

    def __len__(self) -> int:
        return len(self.offsets_ms)


@dataclass(frozen=True, slots=True)
class DueStep:
    index: int
    step_id: str
    offset_ms: int
    scheduled_ms: int


@dataclass(frozen=True, slots=True)
class SequenceClock:
    """Run state of one sequence. `t0_ms is None`: not started yet (waiting for the speech to start, or not begun)."""

    schedule: SequenceSchedule
    t0_ms: int | None = None
    #: Total time spent paused (added whole on every resume): the only thing that moves a due time after t0.
    shift_ms: int = 0
    paused_at_ms: int | None = None
    #: Steps released so far (their actions were applied); steps are released in order, once.
    released: int = 0
    done: bool = False

    @property
    def started(self) -> bool:
        return self.t0_ms is not None

    @property
    def paused(self) -> bool:
        return self.paused_at_ms is not None


def begin(schedule: SequenceSchedule) -> SequenceClock:
    return SequenceClock(schedule)


def start(clock: SequenceClock, now_ms: int) -> SequenceClock:
    """Set t0. Exactly once: a second start would move every due time."""

    if clock.t0_ms is not None:
        raise ValueError("the sequence already has a t0")
    return replace(clock, t0_ms=now_ms)


def pause(clock: SequenceClock, now_ms: int) -> SequenceClock:
    if clock.paused or not clock.started or clock.done:
        return clock
    return replace(clock, paused_at_ms=now_ms)


def resume(clock: SequenceClock, now_ms: int) -> SequenceClock:
    if clock.paused_at_ms is None:
        return clock
    return replace(clock, shift_ms=clock.shift_ms + max(0, now_ms - clock.paused_at_ms), paused_at_ms=None)


def scheduled_ms(clock: SequenceClock, offset_ms: int) -> int:
    """`t0 + shift + offset`: from the sequence start, never from the previous step."""

    if clock.t0_ms is None:
        raise ValueError("the sequence has not started")
    return clock.t0_ms + clock.shift_ms + offset_ms


def due(clock: SequenceClock, now_ms: int) -> tuple[DueStep, ...]:
    """The steps not yet released whose time has come (empty while paused, not started or done). A peek: nothing is
    released until the caller has actually applied the step (`release`)."""

    if not clock.started or clock.paused or clock.done:
        return ()
    schedule = clock.schedule
    out = []
    for index in range(clock.released, len(schedule)):
        at = scheduled_ms(clock, schedule.offsets_ms[index])
        if at > now_ms:
            break
        out.append(DueStep(index, schedule.step_ids[index], schedule.offsets_ms[index], at))
    return tuple(out)


def release(clock: SequenceClock, index: int) -> SequenceClock:
    """The step `index` was applied. In order, once."""

    if index != clock.released or index >= len(clock.schedule):
        raise ValueError("steps are released in order, once")
    return replace(clock, released=index + 1)


def end_ms(clock: SequenceClock) -> int:
    return scheduled_ms(clock, clock.schedule.duration_ms)


def end_due(clock: SequenceClock, now_ms: int) -> bool:
    """Every step released and the exact length reached."""

    return (clock.started and not clock.paused and not clock.done and clock.released == len(clock.schedule)
            and now_ms >= end_ms(clock))


def finish(clock: SequenceClock) -> SequenceClock:
    return replace(clock, done=True)


def next_deadline_ms(clock: SequenceClock) -> int | None:
    """The next instant something is due (a step, else the end), `None` when nothing is scheduled (paused, done, not started)."""

    if not clock.started or clock.paused or clock.done:
        return None
    if clock.released < len(clock.schedule):
        return scheduled_ms(clock, clock.schedule.offsets_ms[clock.released])
    return end_ms(clock)


def elapsed_ms(clock: SequenceClock, now_ms: int) -> int:
    """Sequence time so far, frozen while paused, never beyond the length."""

    if clock.t0_ms is None:
        return 0
    edge = clock.paused_at_ms if clock.paused_at_ms is not None else now_ms
    return max(0, min(clock.schedule.duration_ms, edge - clock.t0_ms - clock.shift_ms))


# ------------------------------------------------------------------ the action log (determinism witness)


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One released step. Ids, offsets and times only: never a text, never an action value."""

    sequence_id: str
    step_id: str
    index: int
    offset_ms: int
    scheduled_ms: int
    released_ms: int
    #: Canonical keys of the step's actions in written order (`ActionRef.key()`), so two runs compare action for action.
    actions: tuple[str, ...]

    @property
    def late_ms(self) -> int:
        return max(0, self.released_ms - self.scheduled_ms)

    def key(self) -> tuple:
        """What must be identical between two runs of the same score on the same clock."""

        return (self.sequence_id, self.step_id, self.index, self.offset_ms, self.scheduled_ms, self.actions)


def log_entry(clock: SequenceClock, step: DueStep, released_ms: int, actions: tuple[str, ...]) -> LogEntry:
    return LogEntry(clock.schedule.sequence_id, step.step_id, step.index, step.offset_ms, step.scheduled_ms, released_ms, actions)
