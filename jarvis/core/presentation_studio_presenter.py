"""Jarvis presenter of the Presentation Studio (handoff jarvis-interactive-presentation-studio, Slice 14).

The driver that lets **Jarvis present a prepared score** on top of the Slice 12 playback runtime:

- it speaks the lines of `presenter=jarvis` items **only** through `BrainOrchestrator.announce_notice` with the Slice 01c
  `ScoreLineNotice` arguments (`kind=progress`, `supersedes_key=presentation_studio:<run_id>`, `ttl_s`). There is no second TTS
  stack, no provider call, no speech state of its own: after the hand-over it only **observes** the facts the existing speech
  stack already records (`brain.speech.requested`, `mouth.speech.*`, `mouth.floor.taken`, folded by
  `jarvis/domain/presentation_studio_line.py`, the same phase words as `jarvis/runtime/tool_brain_speech.py`);
- it advances item by item: a spoken line ends the item when the mouth says `completed`; a silence item (explicit, speaks nothing,
  still executes its bound actions, which the playback service applies when the item is entered) lasts its soft target duration;
  a `user` item is the user's: Jarvis speaks nothing and waits for the user's navigation;
- it executes **locked sequences** (`presentation_studio_sequence`): every step is released at `t0 + shift + offset` on the
  injected monotonic clock, its actions applied by the Slice 12 stage (a `sequence_step` report), its Jarvis line issued as above;
- it never decides alone to leave a state the user did not choose: an interruption (the user takes the floor, an admitted user turn,
  a speech cut) **pauses** the run through the machine, which applies the item's declared `interruption` policy; the run resumes
  only on the user's explicit continue (`resume`), at the item's declared recovery; a failure (the speech stack refuses the line,
  never starts it, fails, is not heard) **pauses with a stated problem**, never hangs, never skips silently.

Text privacy: a score line is data to say. This module never logs, traces, evaluates or emits the text of a line, a step or a note:
only ids, counts (`chars`), codes and times. `note` is never read at all (it is the *user's* intention).

Concurrency: `pump()` is the whole driver, serialised by its own lock, deterministic given the clock and the facts it was given; the
asyncio loop around it (`_loop`) only waits for a wake-up or the next deadline. The playback service wakes the driver through
`add_observer` (a sync callback that sets an event, run under the service lock: it must never call back into a command).

Contract: `docs/presentation-studio.md` > *Jarvis presenter and locked sequences*.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import time
from typing import Any, Protocol

from jarvis.domain.presentation_studio_line import FACT_OF_EVENT, FactKind, LinePhase, SpeechFact, SpeechLine, observe
from jarvis.domain.presentation_studio_playback import EventKind, Phase, PlaybackPlan, PlaybackState
from jarvis.domain.presentation_studio_roles import SUPERSEDES_PREFIX, ScoreLineNotice
from jarvis.domain.presentation_studio_score import ItemKind, LockedSequence, Presenter, Recovery, ScoreItem
from jarvis.domain.presentation_studio_sequence import (
    InputKind, InterruptionPlan, LogEntry, SequenceClock, SequenceSchedule, Verdict, begin, due, elapsed_ms, end_due, finish,
    input_verdict, interruption_plan, log_entry, next_deadline_ms, pause as pause_clock, release, resume as resume_clock, start,
)
from jarvis.ports.v2 import DiagnosticSink

TRACE = "core.presentation_studio"

#: The speech stack must START a handed-over line within this time, else `speech_not_started` (the voice process is not connected,
#: the surface is busy, nothing records mouth events...): a visible pause with the reason, never a hang.
START_TIMEOUT_S = 10.0
#: ...and must END it within this time of starting, else `speech_stalled`.
LINE_TIMEOUT_S = 180.0
#: Breathing room between a finished line and the next item.
GAP_MS = 300
#: How long a silence item without a target lasts (a silence with a `target_duration_ms` lasts that, as a soft pace).
SILENCE_DEFAULT_MS = 1500
#: One `pump()` stops after this many consecutive actions (the next wake-up goes on): no unbounded loop on a misbehaving fake.
MAX_ACTIONS_PER_PUMP = 64
MAX_FACTS = 256
MAX_LOG = 256
MAX_LINES = 40

# Stable problem / reason codes (tokens, shown on the band, in diagnostics and in the event).
SPEECH_NOT_STARTED = "speech_not_started"
SPEECH_STALLED = "speech_stalled"
ANNOUNCE_REFUSED = "announce_refused"
ANNOUNCE_FAILED = "announce_failed"
LINE_INVALID = "line_invalid"
PRESENTER_CRASHED = "presenter_crashed"
_FAILURE_OF = {LinePhase.OBSOLETE: "speech_obsolete", LinePhase.FAILED: "speech_failed",
               LinePhase.UNCONFIRMED: "speech_unconfirmed"}
_STEP = "step:"


def _applied(result: Any) -> bool:
    return getattr(getattr(result, "status", None), "value", getattr(result, "status", None)) == "applied"


class Brain(Protocol):
    """What the presenter needs of `BrainOrchestrator`: the one verbatim-speech call. Nothing else."""

    async def announce_notice(self, text: str, *, kind: Any = None, supersedes_key: str | None = None,
                              ttl_s: float | None = None, work_id: str | None = None,
                              conversation_id: str | None = None) -> bool: ...


class Playback(Protocol):
    """The part of `PresentationStudioPlaybackService` the presenter drives."""

    @property
    def state(self) -> PlaybackState: ...

    @property
    def plan(self) -> PlaybackPlan | None: ...

    def running_variant(self) -> tuple[str, str] | None: ...

    def add_observer(self, observer: Callable[[], None]) -> None: ...

    def set_presenter_view(self, view: Callable[[], Mapping[str, Any] | None]) -> None: ...

    def resolve_problem(self, code: str) -> None: ...

    async def notify(self, kind: EventKind, **fields: Any) -> Any: ...

    async def halt(self, problem: str) -> Any: ...

    async def finish(self, reason: str) -> Any: ...


@dataclass(slots=True)
class _Run:
    run_id: str
    speaks: bool
    presentation_id: str | None = None
    variant_id: str | None = None
    key: tuple[int, int] | None = None
    #: What the playback state said about pauses when this entry began / when we last thawed: a pause we missed is still seen.
    seen_resumes: int = 0
    seen_paused_ms: int = 0
    item_t0: int = 0
    frozen_since: int | None = None
    frozen_total: int = 0
    lines: dict[str, SpeechLine] = field(default_factory=dict)
    stale: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LINES))
    issued: int = 0
    primary_tag: str | None = None
    #: Sequence executor state for the current entry.
    clock: SequenceClock | None = None
    seq_state: str = "idle"          # idle | waiting_start | running | done
    wait_tag: str | None = None
    t0_basis: str | None = None
    #: Step lines waiting to be handed over: one unstarted line at a time, so a later line never replaces an unstarted earlier one.
    queue: list[tuple[str, str]] = field(default_factory=list)
    #: Text of the step lines issued in this entry, for a retry after a failure (never traced, never in a view or an event).
    sent: dict[str, str] = field(default_factory=dict)
    log: deque[LogEntry] = field(default_factory=lambda: deque(maxlen=MAX_LOG))
    #: Interruption bookkeeping.
    signal: str | None = None
    interrupted: bool = False
    interrupt_key: tuple[int, int] | None = None
    recover_on_resume: bool = False
    done_at: int | None = None
    speaking_sent: bool = False
    problem: str | None = None
    finishing: bool = False
    #: Every issue, in order: `(entry key, tag)`, for the invariants the tests check (bounded).
    issue_log: deque[tuple[tuple[int, int] | None, str]] = field(default_factory=lambda: deque(maxlen=MAX_LOG))


class PresentationStudioPresenter:
    def __init__(self, playback: Playback, brain: Brain, *, events: Any | None = None, diagnostics: DiagnosticSink | None = None,
                 monotonic: Callable[[], float] = time.monotonic, start_timeout_s: float = START_TIMEOUT_S,
                 line_timeout_s: float = LINE_TIMEOUT_S, gap_ms: int = GAP_MS, silence_default_ms: int = SILENCE_DEFAULT_MS,
                 run_loop: bool = True) -> None:
        self._playback, self._brain, self._events, self._diagnostics = playback, brain, events, diagnostics
        self._monotonic = monotonic
        self._start_timeout_ms, self._line_timeout_ms = int(start_timeout_s * 1000), int(line_timeout_s * 1000)
        self._gap_ms, self._silence_default_ms = int(gap_ms), int(silence_default_ms)
        self._run: _Run | None = None
        self._facts: deque[tuple[FactKind, str | None, str | None, int | None, int]] = deque(maxlen=MAX_FACTS)
        self._wake = asyncio.Event()
        self._pump_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        #: False: no background task, `pump()` is driven by hand (the fake-clock tests); Core always runs the loop.
        self._run_loop = run_loop
        self._event_seq = 0
        playback.add_observer(self.wake)
        playback.set_presenter_view(self.view)

    # ------------------------------------------------------------------ inputs

    def wake(self) -> None:
        """Sync, non-blocking (called under the playback lock): make sure the loop runs and re-evaluates."""

        self._wake.set()
        if self._closed or not self._run_loop or (self._task is not None and not self._task.done()):
            return
        try:
            self._task = asyncio.get_running_loop().create_task(self._loop(), name="jarvis-studio-presenter")
        except RuntimeError:
            return  # no running loop (a synchronous caller): `pump()` is driven by hand

    def on_event(self, event: Any) -> None:
        """Conversation-event listener (`ConversationEventEmitter.add_listener`): sync, never raises, copies no content.

        Only ids, the kind and two tokens are read. A `brain.speech.requested` is kept only when its `supersedes_key` is this run's
        (that is how the presenter learns the speech id of the line it just handed over)."""

        run = self._run
        try:
            kind = FACT_OF_EVENT.get(event.event_type)
            if kind is None or run is None:
                return
            attributes = event.attributes or {}
            if kind is FactKind.REQUESTED and attributes.get("supersedes_key") != f"{SUPERSEDES_PREFIX}{run.run_id}":
                return
            reason = attributes.get("reason")
            played = attributes.get("played_ms")
            self._facts.append((kind, getattr(event, "speech_id", None), reason if isinstance(reason, str) else None,
                                played if type(played) is int else None, self._now_ms()))
            self._wake.set()
        except Exception as exc:  # noqa: BLE001 - a listener never fails its producer (the emitter isolates it too); said
            self._trace("presenter_event_failed", "Fait de parole illisible", level="warning",
                        data={"error_class": type(exc).__name__})

    async def close(self) -> None:
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # ------------------------------------------------------------------ reads

    @property
    def action_log(self) -> tuple[LogEntry, ...]:
        """Released steps of the current run (ids, offsets and times: the determinism witness)."""

        return tuple(self._run.log) if self._run else ()

    @property
    def issue_log(self) -> tuple[tuple[tuple[int, int] | None, str], ...]:
        return tuple(self._run.issue_log) if self._run else ()

    def view(self) -> Mapping[str, Any] | None:
        """Bounded, content-free status for the band (`presenter` in the answer of `where`)."""

        run = self._run
        if run is None:
            return None
        now = self._now_ms()
        out: dict[str, Any] = {"speaks": run.speaks, "lines": run.issued, "interrupted": run.interrupted,
                               "problem": run.problem, "line": None, "sequence": None}
        line = run.lines.get(run.primary_tag) if run.primary_tag else None
        if line is None and run.lines:
            line = next(reversed(run.lines.values()))
        if line is not None:
            out["line"] = line.phase.value
        clock = run.clock
        if clock is not None:
            out["sequence"] = {"state": run.seq_state, "step": clock.released, "of": len(clock.schedule),
                               "elapsed_ms": elapsed_ms(clock, now), "duration_ms": clock.schedule.duration_ms,
                               "basis": run.t0_basis}
        return out

    def next_wake_s(self) -> float | None:
        """Seconds until the next deadline the driver owns (a start timeout, a silence, a step, a gap...); `None`: only a wake-up."""

        deadline = self._next_deadline_ms()
        return None if deadline is None else max(0.0, (deadline - self._now_ms()) / 1000)

    # ------------------------------------------------------------------ the loop

    async def _loop(self) -> None:
        try:
            while not self._closed:
                self._wake.clear()  # before the pump: a change during it sets the event again, nothing is lost
                try:
                    await self.pump()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - captured in `_crashed`: the run is ended cleanly with a stated reason
                    await self._crashed(exc)
                if self._run is None and not self._playback.state.active:
                    return
                try:
                    await asyncio.wait_for(self._wake.wait(), self.next_wake_s())
                except asyncio.TimeoutError:
                    # intentional: reaching the deadline is the point of this wait; the next pump decides what is due
                    pass
        finally:
            self._task = None

    async def _crashed(self, exc: BaseException) -> None:
        self._trace("presenter_crashed", "Le presentateur Jarvis a plante : fin propre de la seance", level="error",
                    data={"error_class": type(exc).__name__})
        run = self._run
        if run is not None:
            self._emit("line_failed", run, PRESENTER_CRASHED)
        try:
            if self._playback.state.active:
                await self._playback.finish(PRESENTER_CRASHED)
        except Exception as inner:  # noqa: BLE001 - captured: nothing more can be done, the error row says it
            self._trace("presenter_crash_finish_failed", "Fin propre apres plantage impossible", level="error",
                        data={"error_class": type(inner).__name__})
        self._run = None

    # ------------------------------------------------------------------ the driver

    async def pump(self) -> None:
        """Do everything that is due now, then return. Idempotent; safe to call at any time and from tests."""

        async with self._pump_lock:
            for _ in range(MAX_ACTIONS_PER_PUMP):
                if not await self._step():
                    return

    async def _step(self) -> bool:
        now = self._now_ms()
        state, plan = self._playback.state, self._playback.plan
        self._absorb(state)
        run = self._run
        if not state.active or plan is None or state.run_id is None:
            if run is not None:
                self._detach(state)
            return False
        if run is None or run.run_id != state.run_id:
            run = self._attach(state)
        return await self._drive(run, state, plan, now)

    def _attach(self, state: PlaybackState) -> _Run:
        where = self._playback.running_variant()
        run = _Run(run_id=state.run_id or "", speaks=state.jarvis_speaks,
                   presentation_id=where[0] if where else None, variant_id=where[1] if where else None)
        self._run = run
        self._facts.clear()
        self._trace("presenter_attached", "Presentateur Jarvis rattache a la lecture",
                    data={"run_id": run.run_id, "speaks": run.speaks, "role": state.role.value if state.role else None})
        return run

    def _detach(self, state: PlaybackState) -> None:
        run, self._run = self._run, None
        if run is not None:
            self._trace("presenter_detached", "Presentateur Jarvis detache de la lecture", data={
                "run_id": run.run_id, "lines": run.issued, "steps": len(run.log), "phase": state.phase.value})

    async def _drive(self, run: _Run, state: PlaybackState, plan: PlaybackPlan, now: int) -> bool:
        if state.phase in (Phase.PAUSED, Phase.DETOUR, Phase.RESUMING):
            self._freeze(run, now)
            return False
        if state.phase is Phase.ENDED:
            if run.speaks and not run.finishing:
                run.finishing = True
                self._trace("presenter_completed", "Presentation menee a son terme par Jarvis",
                            data={"run_id": run.run_id, "lines": run.issued})
                self._emit("completed", run, None)
                await self._playback.finish("completed")  # stage released, aux retired, MODE RESTORED (01c)
                return True
            return False
        if state.phase is not Phase.PLAYING:
            return False
        key = (state.position, state.epoch)
        if run.key != key:
            self._enter_item(run, state, key, now)
        item = plan.item_at(state.position)
        if run.frozen_since is None and state.resumes != run.seen_resumes:
            # A pause and its resume both happened between two of our looks: rebuild the freeze from the machine's own account.
            run.frozen_since = now - max(0, state.run_paused_ms - run.seen_paused_ms)
            if run.clock is not None:
                run.clock = pause_clock(run.clock, run.frozen_since)
        if run.frozen_since is not None:
            return await self._thaw(run, state, plan, item, now)
        if run.signal is not None:
            return await self._interrupt(run, state, plan, item)
        if await self._sync_speaking(run):
            return True
        if state.sequence is not None:
            return await self._drive_sequence(run, state, plan, item, now)
        if not run.speaks:
            return False  # the user paces this run; the executor only owns locked sequences
        return await self._drive_item(run, state, item, now)

    # ------------------------------------------------------------------ entering, freezing, thawing

    def _enter_item(self, run: _Run, state: PlaybackState, key: tuple[int, int], now: int) -> None:
        if run.clock is not None and run.seq_state in ("running", "waiting_start"):
            self._emit("sequence_skipped", run, "left_before_done")
            self._trace("presenter_sequence_left", "Sequence verrouillee quittee avant sa fin",
                        data={"run_id": run.run_id, "sequence_id": run.clock.schedule.sequence_id})
        self._forget_lines(run)
        run.key, run.item_t0, run.frozen_since, run.frozen_total = key, now, None, 0
        run.seen_resumes, run.seen_paused_ms = state.resumes, state.run_paused_ms
        run.clock, run.seq_state, run.wait_tag, run.t0_basis = None, "idle", None, None
        run.queue, run.sent = [], {}
        run.done_at, run.speaking_sent, run.signal = None, False, None
        if run.interrupt_key != key:
            run.interrupted = False

    @staticmethod
    def _forget_lines(run: _Run) -> None:
        """Forget the lines of the entry left behind: a late fact of any of them changes nothing."""

        run.stale.extend(line.speech_id for line in run.lines.values() if line.speech_id)
        run.lines, run.primary_tag = {}, None

    def _freeze(self, run: _Run, now: int) -> None:
        if run.frozen_since is None and run.key is not None:
            run.frozen_since = now
            if run.clock is not None:
                run.clock = pause_clock(run.clock, now)
        run.signal = None  # an interruption while the run is already stopped has nothing left to pause

    async def _thaw(self, run: _Run, state: PlaybackState, plan: PlaybackPlan, item: ScoreItem, now: int) -> bool:
        """PLAYING again after a pause, a detour or a stage re-sync: every timer picks up where it stopped; then, if the pause was
        an interruption of THIS entry, the item's declared recovery applies. Resume is always the user's explicit act."""

        gap = max(0, now - (run.frozen_since if run.frozen_since is not None else now))
        run.frozen_total += gap
        run.frozen_since = None
        run.seen_resumes, run.seen_paused_ms = state.resumes, state.run_paused_ms
        if run.clock is not None:
            run.clock = resume_clock(run.clock, now)
        if run.problem is not None:
            self._playback.resolve_problem(run.problem)
            run.problem = None
        recover = run.interrupted and run.interrupt_key == run.key
        self._trace("presenter_resumed", "Presentateur Jarvis : reprise sur demande explicite", data={
            "run_id": run.run_id, "frozen_ms": gap, "recovery": recover})
        if not recover:
            self._reissue_unheard(run)
            return True
        run.interrupted = False
        if state.sequence is not None:
            if run.recover_on_resume:
                result = await self._playback.notify(EventKind.SEQUENCE_ABORT)
                run.clock, run.seq_state = None, "idle"  # left through the recovery point: the entry that follows starts afresh
                self._emit("sequence_aborted", run, "recovery_point")
                self._trace("presenter_sequence_recovered", "Sequence reprise a son point de reprise", data={
                    "run_id": run.run_id, "applied": _applied(result)})
            return True
        recovery = item.recovery
        if recovery is Recovery.SKIP_TO_NEXT:
            await self._playback.notify(EventKind.NEXT)
        elif recovery is Recovery.RECOVERY_POINT and item.recovery_point_id is not None:
            target = plan.recovery_position(item.recovery_point_id, state.position)
            await self._playback.notify(EventKind.GOTO, position=state.position if target is None else target)
        elif recovery is Recovery.RESTART_ITEM:
            self._forget_lines(run)
            run.done_at, run.item_t0, run.frozen_total = None, now, 0
        else:
            self._reissue_unheard(run)
        return True

    def _reissue_unheard(self, run: _Run) -> None:
        """"Resume re-issues the current line from its start" (01c): a line that was neither heard in full nor still playing is
        forgotten, so the item says it again, once; a line heard in full is kept (the item is done, never said twice)."""

        for tag, line in tuple(run.lines.items()):
            if line.phase not in (LinePhase.HEARD, LinePhase.PLAYING):
                if line.speech_id:
                    run.stale.append(line.speech_id)
                run.lines.pop(tag)
                if tag == run.primary_tag:
                    run.primary_tag = None
                if tag.startswith(_STEP) and tag in run.sent:
                    run.queue.append((tag, run.sent[tag]))

    # ------------------------------------------------------------------ facts and interruption

    def _absorb(self, state: PlaybackState) -> None:
        """Fold the facts that arrived since the last look. A user signal (floor, turn, a cut line) older than the last explicit
        continue is that continue's own cause, not a new interruption: it is dropped."""

        run = self._run
        while self._facts:
            kind, speech_id, reason, played, at = self._facts.popleft()
            if run is None:
                continue
            fact = SpeechFact(kind, at, speech_id, reason, played)
            if kind is FactKind.REQUESTED:
                if speech_id is None or speech_id in run.stale:
                    continue
                unbound = next((tag for tag, line in run.lines.items() if line.speech_id is None and not line.terminal), None)
                if unbound is not None:
                    run.lines[unbound] = observe(run.lines[unbound], fact)
                continue
            if kind in (FactKind.FLOOR_TAKEN, FactKind.USER_TURN):
                if at <= state.resumed_at_ms:
                    continue
                outstanding = any(not line.terminal for line in run.lines.values())
                running = run.clock is not None and run.seq_state in ("running", "waiting_start")
                if (kind is FactKind.USER_TURN or outstanding or running) and run.signal is None:
                    run.signal = kind.value  # the first cause is the one reported
                continue
            for tag, line in tuple(run.lines.items()):
                moved = observe(line, fact)
                if moved is not line:
                    run.lines[tag] = moved
                    if moved.phase is LinePhase.INTERRUPTED and run.signal is None and at > state.resumed_at_ms:
                        run.signal = "speech_interrupted"

    async def _interrupt(self, run: _Run, state: PlaybackState, plan: PlaybackPlan, item: ScoreItem) -> bool:
        """The user addressed Jarvis (or cut a line): ask the machine to PAUSE; it applies the item's `interruption` policy exactly
        (`allow` now, `at_boundary` pending until the boundary, `refuse` refused). Never an automatic resume."""

        source, run.signal = run.signal, None
        sequence = plan.sequences.get(state.sequence.sequence_id) if state.sequence is not None else None
        decision: InterruptionPlan = (interruption_plan(item.interruption, sequence.on_interrupt) if sequence is not None
                                      else InterruptionPlan(input_verdict(item.interruption, InputKind.PAUSE), False))
        if decision.verdict is Verdict.REFUSE:
            self._trace("presenter_interruption_ignored", "Interruption refusee par la partition (item non interruptible)",
                        data={"run_id": run.run_id, "source": source, "interruption": item.interruption.value})
            self._emit("interrupted", run, "refused_by_policy")
            return True  # handled: the line (if it was cut) is judged on the next look
        result = await self._playback.notify(EventKind.PAUSE)
        if not _applied(result):
            return False
        run.interrupted, run.interrupt_key, run.recover_on_resume = True, run.key, decision.recover_on_resume
        self._trace("presenter_interrupted", "Lecture interrompue par l'utilisateur : en pause, reprise sur demande explicite", data={
            "run_id": run.run_id, "source": source, "verdict": decision.verdict.value, "recover_on_resume": decision.recover_on_resume})
        self._emit("interrupted", run, source)
        return True

    # ------------------------------------------------------------------ one item (no sequence)

    async def _drive_item(self, run: _Run, state: PlaybackState, item: ScoreItem, now: int) -> bool:
        if item.presenter is Presenter.USER:
            return False  # the user's speech and the user's pace; Jarvis says nothing and the user navigates
        if item.presenter is Presenter.JARVIS and item.kind is ItemKind.SPEECH and item.text:
            return await self._drive_line_item(run, state, item, now)
        if item.presenter is Presenter.JARVIS:
            return await self._drive_after_sequence(run, now)  # a host: its steps spoke
        # explicit silence: nothing is said, the bound actions were applied when the item was entered; a soft pace
        target = item.target_duration_ms if item.target_duration_ms is not None else self._silence_default_ms
        if now - run.item_t0 - run.frozen_total >= target:
            return await self._advance(run, "silence_done")
        return False

    async def _drive_line_item(self, run: _Run, state: PlaybackState, item: ScoreItem, now: int) -> bool:
        tag = item.item_id
        line = run.lines.get(tag)
        if line is None:
            run.primary_tag = tag
            return await self._issue(run, tag, item.text, now)
        verdict = self._judge(line, now)
        if verdict == "wait":
            return False
        if verdict == "heard":
            if run.done_at is None:
                run.done_at = line.ended_ms if line.ended_ms is not None else now
                self._trace("presenter_line_heard", "Ligne dite en entier", data={
                    "run_id": run.run_id, "position": state.position + 1, "played_ms": line.played_ms, "chars": line.chars})
            return False if now < run.done_at + self._gap_ms else await self._advance(run, "line_heard")
        if verdict == "cut":
            # Cut by the user, yet the run is still PLAYING: the policy refused the pause (`refuse`), or it waits for the boundary.
            if state.pending is not None:
                return _applied(await self._playback.notify(EventKind.BOUNDARY))  # the item ends here: the pause takes effect
            return await self._advance(run, "line_cut_policy_refused_pause")
        await self._fail(run, verdict, (tag,))
        return True

    def _judge(self, line: SpeechLine, now: int) -> str:
        """`wait`, `heard`, `cut` (interrupted: the policy decides), or a failure code."""

        if line.phase is LinePhase.HEARD:
            return "heard"
        if line.phase is LinePhase.INTERRUPTED:
            return "cut"
        if line.phase in _FAILURE_OF:
            return _FAILURE_OF[line.phase]
        if line.phase is LinePhase.PENDING:
            return SPEECH_NOT_STARTED if line.wait_ms(now) > self._start_timeout_ms else "wait"
        if line.started_ms is not None and now - line.started_ms > self._line_timeout_ms:
            return SPEECH_STALLED
        return "wait"

    async def _advance(self, run: _Run, why: str) -> bool:
        applied = _applied(await self._playback.notify(EventKind.NEXT))
        self._trace("presenter_advanced", "Item suivant", data={"run_id": run.run_id, "why": why, "applied": applied})
        return applied

    # ------------------------------------------------------------------ speaking the line

    async def _issue(self, run: _Run, tag: str, text: str, now: int) -> bool:
        """Hand one line to the existing speech path. True when handed over; otherwise the run was paused with the reason."""

        try:
            notice = ScoreLineNotice(text, run_id=run.run_id)
        except ValueError:
            await self._fail(run, LINE_INVALID, (tag,))
            return False
        run.lines[tag] = SpeechLine(tag, now, len(text))
        run.issued += 1
        run.issue_log.append((run.key, tag))
        self._trace("presenter_line_issued", "Ligne de la partition remise a la parole de Jarvis", data={
            "run_id": run.run_id, "tag": tag, "chars": len(text), "kind": notice.call_kwargs()["kind"].value})
        try:
            spoken = await self._brain.announce_notice(notice.text, **notice.call_kwargs())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - captured as an error row; the run pauses with `announce_failed`
            self._trace("presenter_announce_failed", "announce_notice a leve une erreur", level="error",
                        data={"run_id": run.run_id, "tag": tag, "error_class": type(exc).__name__})
            await self._fail(run, ANNOUNCE_FAILED, (tag,))
            return False
        self._absorb(self._playback.state)  # the `brain.speech.requested` of this very line was queued while we awaited: bind its speech id
        if not spoken:
            self._trace("presenter_announce_refused", "Ligne non publiee par Core (aucune intention courante, politique, arret)",
                        level="warning", data={"run_id": run.run_id, "tag": tag})
            await self._fail(run, ANNOUNCE_REFUSED, (tag,))
            return False
        return True

    async def _fail(self, run: _Run, code: str, tags: tuple[str, ...]) -> None:
        """A visible failure: the run is paused with `code` on the band, a diagnostic, an event. The user's resume is the retry."""

        run.problem = code
        for tag in tags:
            line = run.lines.pop(tag, None)
            if line is not None and line.speech_id:
                run.stale.append(line.speech_id)  # a late fact of an abandoned line changes nothing
            if tag.startswith(_STEP) and tag != run.wait_tag and tag in run.sent and run.clock is not None:
                run.queue.insert(0, (tag, run.sent[tag]))  # the step was released: its line is retried, not the sequence
        if run.primary_tag in tags:
            run.primary_tag = None
        run.done_at = None
        self._trace("presenter_line_failed", "Ligne de la partition non dite : lecture en pause", level="warning",
                    data={"run_id": run.run_id, "code": code})
        self._emit("line_failed", run, code)
        await self._playback.halt(code)
        self._freeze(run, self._now_ms())  # the run is paused now: timers stop here, the user's resume is the retry

    async def _sync_speaking(self, run: _Run) -> bool:
        """Tell the machine who speaks (`speaking`): Jarvis while one of the run's lines plays. Informational, never blocking."""

        playing = any(line.phase is LinePhase.PLAYING for line in run.lines.values())
        if playing == run.speaking_sent:
            return False
        if _applied(await self._playback.notify(EventKind.SPEAKING, speaker=Presenter.JARVIS if playing else None)):
            run.speaking_sent = playing
            return True
        return False

    # ------------------------------------------------------------------ locked sequences

    async def _drive_sequence(self, run: _Run, state: PlaybackState, plan: PlaybackPlan, item: ScoreItem, now: int) -> bool:
        sequence = plan.sequences[state.sequence.sequence_id]
        if run.clock is None:
            return await self._begin_sequence(run, sequence, item, now)
        if run.seq_state == "waiting_start":
            return await self._await_t0(run, now)
        clock = run.clock
        for tag, line in run.lines.items():
            verdict = self._judge(line, now)
            if verdict not in ("wait", "heard", "cut"):
                await self._fail(run, verdict, (tag,))
                return True
        if run.queue and not any(line.phase is LinePhase.PENDING for line in run.lines.values()):
            tag, text = run.queue.pop(0)
            await self._issue(run, tag, text, now)
            return True
        steps = due(clock, now)
        if steps:
            if state.pending is not None:
                # An interruption waits for this boundary: take it BEFORE the step starts; the step stays due and is released at
                # once on resume (its time was shifted by the pause, so it is exactly as late as it was).
                return _applied(await self._playback.notify(EventKind.BOUNDARY))
            return await self._release_step(run, sequence, steps[0], now)
        if end_due(clock, now):
            if not _applied(await self._playback.notify(EventKind.SEQUENCE_DONE)):
                return False
            run.clock, run.seq_state = finish(clock), "done"
            self._trace("presenter_sequence_done", "Sequence verrouillee terminee", data={
                "run_id": run.run_id, "sequence_id": sequence.sequence_id, "steps": len(sequence.steps),
                "duration_ms": sequence.duration_ms})
            self._emit("sequence_done", run, None)
            return True
        return False

    async def _begin_sequence(self, run: _Run, sequence: LockedSequence, item: ScoreItem, now: int) -> bool:
        run.clock = begin(SequenceSchedule.of(sequence))
        first = sequence.steps[0]
        if run.speaks and first.speaker is Presenter.JARVIS:
            tag = f"{_STEP}{first.step_id}"
            run.wait_tag, run.seq_state = tag, "waiting_start"
            self._trace("presenter_sequence_begun", "Sequence verrouillee : attente du debut de la parole (t0)", data={
                "run_id": run.run_id, "sequence_id": sequence.sequence_id, "steps": len(sequence.steps)})
            run.sent[tag] = first.text
            await self._issue(run, tag, first.text, now)
            return True
        run.clock = start(run.clock, now)
        run.seq_state, run.t0_basis = "running", "explicit_start"
        self._trace("presenter_sequence_started", "Sequence verrouillee demarree (t0 = depart explicite)", data={
            "run_id": run.run_id, "sequence_id": sequence.sequence_id, "steps": len(sequence.steps)})
        return True

    async def _await_t0(self, run: _Run, now: int) -> bool:
        """The first words of the sequence fix t0. Bounded: they must start (`speech_not_started`), never a hang."""

        tag = run.wait_tag or ""
        line = run.lines.get(tag)
        if line is None:
            run.clock, run.seq_state, run.wait_tag = None, "idle", None  # the line failed and was dropped: restart on resume
            return True
        if line.started_ms is not None:
            run.clock = start(run.clock, line.started_ms)  # t0 = the instant the first words started (`mouth.speech.started`)
            run.seq_state, run.t0_basis = "running", "speech_started"
            self._trace("presenter_sequence_started", "Sequence verrouillee demarree (t0 = parole demarree)", data={
                "run_id": run.run_id, "sequence_id": run.clock.schedule.sequence_id, "lag_ms": line.started_ms - line.issued_ms})
            return True
        verdict = self._judge(line, now)
        if verdict == "wait":
            return False
        run.clock, run.seq_state, run.wait_tag = None, "idle", None  # nothing was released: the whole sequence restarts on resume
        await self._fail(run, SPEECH_NOT_STARTED if verdict in ("cut", "heard") else verdict, (tag,))
        return True

    async def _release_step(self, run: _Run, sequence: LockedSequence, step: Any, now: int) -> bool:
        if not _applied(await self._playback.notify(EventKind.SEQUENCE_STEP, step=step.index + 1)):
            return False  # the run moved meanwhile (a pause): nothing is released, the step stays due
        spec = sequence.steps[step.index]
        actions = tuple(a.key() for a in (*spec.visual, *spec.motion))
        run.clock = release(run.clock, step.index)
        entry = log_entry(run.clock, step, now, actions)
        run.log.append(entry)
        self._trace("presenter_sequence_step", "Etape de sequence liberee", data={
            "run_id": run.run_id, "sequence_id": sequence.sequence_id, "step_id": spec.step_id, "offset_ms": spec.offset_ms,
            "late_ms": entry.late_ms, "actions": len(actions)})
        if run.speaks and spec.speaker is Presenter.JARVIS and step.index > 0:
            tag = f"{_STEP}{spec.step_id}"
            run.sent[tag] = spec.text
            run.queue.append((tag, spec.text))
        return True

    async def _drive_after_sequence(self, run: _Run, now: int) -> bool:
        """The sequence is done and the timeline is the user's again: the host item ends when its last line has been heard."""

        if run.seq_state != "done" or run.clock is None:
            return False
        if run.queue:
            tag, text = run.queue[0]
            if not any(line.phase is LinePhase.PENDING for line in run.lines.values()):
                run.queue.pop(0)
                await self._issue(run, tag, text, now)
                return True
            return False
        for tag, line in run.lines.items():
            verdict = self._judge(line, now)
            if verdict == "wait":
                return False
            if verdict not in ("heard", "cut"):
                await self._fail(run, verdict, (tag,))
                return True
        if run.done_at is None:
            ends = [line.ended_ms for line in run.lines.values() if line.ended_ms is not None]
            run.done_at = max([*ends, run.clock.t0_ms + run.clock.shift_ms + run.clock.schedule.duration_ms])
        return False if now < run.done_at + self._gap_ms else await self._advance(run, "sequence_done")

    # ------------------------------------------------------------------ deadlines, events, traces

    def _next_deadline_ms(self) -> int | None:
        run, state = self._run, self._playback.state
        if run is None or state.phase is not Phase.PLAYING or run.frozen_since is not None:
            return None
        deadlines: list[int] = []
        for line in run.lines.values():
            if not line.terminal:
                deadlines.append(line.issued_ms + self._start_timeout_ms if line.started_ms is None
                                 else line.started_ms + self._line_timeout_ms)
        if run.clock is not None:
            when = next_deadline_ms(run.clock)
            if when is not None:
                deadlines.append(when)
        if run.done_at is not None:
            deadlines.append(run.done_at + self._gap_ms)
        plan = self._playback.plan
        if run.speaks and state.sequence is None and plan is not None and 0 <= state.position < len(plan):
            item = plan.item_at(state.position)
            if item.kind is ItemKind.SILENCE:
                target = item.target_duration_ms if item.target_duration_ms is not None else self._silence_default_ms
                deadlines.append(run.item_t0 + run.frozen_total + target)
        return min(deadlines) if deadlines else None

    def _emit(self, status: str, run: _Run, code: str | None) -> None:
        if self._events is None:
            return
        self._event_seq += 1
        try:
            self._events.changed(presentation_id=run.presentation_id or "unknown", variant_id=run.variant_id, status=status,
                                 role=self._playback.state.role.value if self._playback.state.role else None,
                                 run_id=run.run_id, seq=self._event_seq, code=code, count=run.issued)
        except Exception as exc:  # noqa: BLE001 - observability never undoes a presenter decision; the failure is journaled
            self._trace("presenter_event_unrecorded", "Evenement du presentateur non pose", level="warning",
                        data={"error_class": type(exc).__name__, "status": status})

    def _now_ms(self) -> int:
        return round(self._monotonic() * 1000)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE}.{kind}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never changes what the presenter does
            pass
