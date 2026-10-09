"""Playback state machine of the Presentation Studio (handoff jarvis-interactive-presentation-studio, Slice 12).

Pure, deterministic, no clock, no I/O. It answers one question exactly: *where is the presentation, and what may
happen next?* Everything that touches the world (the stage window, the mode, the voice) is an **effect** the Core
service (`jarvis/core/presentation_studio_playback.py`) executes after a transition; the machine itself never does.

Shape
-----
- `PlaybackPlan` is a compiled, read-only view of one `Score` + the variant's scenes. The position of a run is an
  **index into `Score.playback_order()`** (declared loops already expanded, bounded by `MAX_EXPANDED_ITEMS`), so a
  looped item has several positions and "back" is exact.
- `PlaybackState` is the whole runtime state (R6: memory only, never persisted): role, phase, position, auxiliary
  stack (bounded), locked-sequence ownership, armed cue set (+ generation), speaker, pending interruption, manual
  reveal overrides, timers (as numbers the caller supplies: no clock here).
- `apply(plan, state, event)` is a **closed table**: `TABLE[event kind] = phases where it may happen`. Anything else
  is a typed `Refusal`, never an exception and never a half-applied state. A second pass (`_settle`) is the single
  place that recomputes the armed set, so *armed cues are always a subset of the score's armable cues, only while
  PLAYING with nobody owning the timeline, and the generation moves whenever the set moves*.
- Cue handling takes **only** a typed `CUE_SATISFIED(cue_id)` event whose id is in the currently armed set. Text never
  enters this module (R5). Matching ambient speech to a cue is Slice 13.

Navigation is reversible by construction: reveal/control progress is a **fold of the score actions over the played
positions** (`progress_at`), not an accumulation, so going back (or to any item) restores exactly the values and
reveals the score implies at that position. Playback never writes the variant: values are an ephemeral overlay.

Contract: `docs/presentation-studio.md` > *Playback runtime contract*.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
import re
from typing import Any

from jarvis.domain.presentation_studio_roles import StudioRole, requirements
from jarvis.domain.presentation_studio_scene import SLUG, StudioScene
from jarvis.domain.presentation_studio_score import (
    CUE_ID, ActionKind, ActionRef, CueDefinition, Interruption, ItemKind, LockedSequence, Presenter, Recovery, Score,
    ScoreItem, SequenceInterrupt,
)

#: Bounds (every collection of the runtime is bounded).
MAX_AUX_STACK = 4
MAX_MANUAL = 32
MAX_PROBLEMS = 8
#: How many upcoming items have their cue armed. One: the next item's cue. More would widen what ambient speech can
#: trigger and make "skip a slide" a spoken accident.
ARM_LOOKAHEAD = 1
MAX_WHERE_PHRASES = 3
MAX_WHERE_BYTES = 2048
MAX_LABEL = 80
MAX_REVEALED_SHOWN = 8

_RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_AUX_ID = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")


class Phase(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    #: An auxiliary resource is on the audience's screen; the score position is frozen.
    DETOUR = "detour"
    #: Transient: the stage is being brought back in line with the position (after pause / detour). Ends with
    #: `STAGE_SYNCED` (-> PLAYING) or `STAGE_FAILED` (-> PAUSED with a visible problem).
    RESUMING = "resuming"
    #: Past the last item; still inspectable, navigable backwards, stopped by `STOP`.
    ENDED = "ended"
    STOPPED = "stopped"


class EventKind(StrEnum):
    START = "start"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"
    NEXT = "next"
    PREVIOUS = "previous"
    GOTO = "goto"
    DETOUR = "detour"
    RETURN = "return"
    REVEAL = "reveal"
    HIDE = "hide"
    CUE_SATISFIED = "cue_satisfied"
    #: Item / step boundary: applies an interruption that was asked while the item said "wait for the boundary".
    BOUNDARY = "boundary"
    STAGE_SYNCED = "stage_synced"
    STAGE_FAILED = "stage_failed"
    #: Locked-sequence executor (Slice 14, `presentation_studio_sequence`) reports; this module only owns position and ownership.
    SEQUENCE_STEP = "sequence_step"
    SEQUENCE_DONE = "sequence_done"
    SEQUENCE_ABORT = "sequence_abort"
    SPEAKING = "speaking"
    #: The user's own escape (user only): leave the locked sequence the item hosts and continue after it. Born provisional
    #: in Slice 12, kept by Slice 14 next to the real executor (a presenter must always be able to get out).
    SKIP_SEQUENCE = "skip_sequence"


class Effect(StrEnum):
    """What the caller must do after a transition, in this order."""

    SYNC_STAGE = "sync_stage"
    SHOW_AUX = "show_aux"
    RETIRE_AUX = "retire_aux"
    RETIRE_ALL = "retire_all"
    ARM_CHANGED = "arm_changed"
    END_RUN = "end_run"


class RefusalCode(StrEnum):
    ILLEGAL_TRANSITION = "illegal_transition"
    NOT_RUNNING = "not_running"
    ALREADY_RUNNING = "already_running"
    EMPTY_SCORE = "empty_score"
    ROLE_INVALID = "role_invalid"
    PAUSED = "paused"
    IN_DETOUR = "in_detour"
    RESUMING = "resuming"
    AT_START = "at_start"
    AT_END = "at_end"
    LOCKED_SEQUENCE = "locked_sequence_active"
    NO_SEQUENCE = "no_sequence"
    UNKNOWN_TARGET = "unknown_target"
    UNKNOWN_ANCHOR = "unknown_anchor"
    CUE_NOT_ARMED = "cue_not_armed"
    CUE_ALREADY_FIRED = "cue_already_fired"
    INTERRUPTION_REFUSED = "interruption_refused"
    AUX_STACK_FULL = "aux_stack_full"
    NO_DETOUR = "no_detour"
    REVEAL_LIMIT = "reveal_limit"
    BAD_STEP = "bad_step"
    #: Slice 12 service level: the detour names a prefab (id, version, props, data) the catalogue does not accept.
    DETOUR_INVALID = "detour_invalid"
    #: Slice 12 service level: the interaction mode could not (or may not) be switched for this run.
    MODE_SWITCH_REFUSED = "mode_switch_refused"


@dataclass(frozen=True, slots=True)
class Refusal:
    code: RefusalCode
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


def _line(name: str, value: object, limit: int = MAX_LABEL, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty) or len(value) > limit or not value.isprintable():
        raise ValueError(f"{name} must be one printable line of at most {limit} characters")
    return value


@dataclass(frozen=True, slots=True)
class AuxRef:
    """An auxiliary resource on screen during a detour: identity and pin only (the displayable block lives in Core)."""

    aux_id: str
    title: str
    prefab_id: str
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.aux_id, str) or not _AUX_ID.fullmatch(self.aux_id):
            raise ValueError("aux_id must match [a-z][a-z0-9_-]{0,47}")
        _line("title", self.title)
        if not isinstance(self.prefab_id, str) or not self.prefab_id or type(self.version) is not int or self.version < 1:
            raise ValueError("an auxiliary resource pins an exact (prefab id, version)")

    def to_dict(self) -> dict[str, Any]:
        return {"aux_id": self.aux_id, "title": self.title, "prefab": {"id": self.prefab_id, "version": self.version}}


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    kind: EventKind
    at_ms: int
    run_id: str | None = None
    role: StudioRole | None = None
    jarvis_speaks: bool | None = None
    item_id: str | None = None
    scene_id: str | None = None
    position: int | None = None
    aux: AuxRef | None = None
    cue_id: str | None = None
    anchor_id: str | None = None
    step: int | None = None
    problem: str | None = None
    speaker: Presenter | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", EventKind(self.kind))
        if type(self.at_ms) is not int or self.at_ms < 0:
            raise ValueError("at_ms must be a non-negative integer (monotonic milliseconds)")
        if self.run_id is not None and not _RUN_ID.fullmatch(str(self.run_id)):
            raise ValueError("run_id is 1-64 characters of [A-Za-z0-9_-]")
        if self.cue_id is not None and not CUE_ID.fullmatch(str(self.cue_id)):
            raise ValueError("cue_id must be a psc_ id (a cue is named by id, never by text)")
        if self.anchor_id is not None and not SLUG.fullmatch(str(self.anchor_id)):
            raise ValueError("anchor_id must be a slug")
        if self.position is not None and (type(self.position) is not int or self.position < 0):
            raise ValueError("position must be a non-negative integer")
        if self.step is not None and (type(self.step) is not int or self.step < 0):
            raise ValueError("step must be a non-negative integer")
        if self.problem is not None:
            _line("problem", self.problem, 64)
        if self.aux is not None and not isinstance(self.aux, AuxRef):
            raise ValueError("aux must be an AuxRef")
        if self.kind is EventKind.START:
            if self.run_id is None or self.role is None:
                raise ValueError("start needs run_id and role")
            object.__setattr__(self, "role", StudioRole(self.role))
        if self.kind is EventKind.DETOUR and self.aux is None:
            raise ValueError("detour needs an auxiliary resource")
        if self.kind is EventKind.CUE_SATISFIED and self.cue_id is None:
            raise ValueError("cue_satisfied needs a cue_id")
        if self.kind in (EventKind.REVEAL, EventKind.HIDE) and self.anchor_id is None:
            raise ValueError(f"{self.kind.value} needs an anchor_id")
        if self.kind is EventKind.SEQUENCE_STEP and self.step is None:
            raise ValueError("sequence_step needs step")
        if self.kind is EventKind.GOTO and (self.item_id, self.scene_id, self.position).count(None) != 2:
            raise ValueError("goto names exactly one of item_id, scene_id, position")
        if self.kind is EventKind.STAGE_FAILED and self.problem is None:
            raise ValueError("stage_failed needs a problem code")


@dataclass(frozen=True, slots=True)
class SequenceRun:
    """A locked sequence owns the timeline until it is done or aborted. `started` = steps whose actions apply."""

    sequence_id: str
    started: int
    count: int


@dataclass(frozen=True, slots=True)
class Pending:
    kind: str  # "pause" | "detour"
    aux: AuxRef | None = None


@dataclass(frozen=True, slots=True)
class PlaybackState:
    run_id: str | None = None
    role: StudioRole | None = None
    jarvis_speaks: bool = False
    phase: Phase = Phase.IDLE
    position: int = 0
    aux: tuple[AuxRef, ...] = ()
    #: Phase to go back to when the last auxiliary resource is retired (PLAYING-ish -> RESUMING, PAUSED -> PAUSED).
    detour_from: Phase | None = None
    pending: Pending | None = None
    sequence: SequenceRun | None = None
    armed: tuple[str, ...] = ()
    #: Moves every time `armed` changes (and only then): a report for another generation is stale.
    generation: int = 0
    fired: tuple[str, ...] = ()
    speaking: Presenter | None = None
    #: Manual reveal / hide overrides on the active scene: ((scene_id, anchor_id), shown). Cleared when the item changes.
    manual: tuple[tuple[tuple[str, str], bool], ...] = ()
    problems: tuple[str, ...] = ()
    run_started_ms: int = 0
    item_started_ms: int = 0
    paused_at_ms: int | None = None
    item_paused_ms: int = 0
    run_paused_ms: int = 0
    #: Moves every time an item is (re-)entered (`_enter`: a move, a restart, a recovery point), never otherwise. A driver that
    #: keys its per-item work by `(position, epoch)` knows an item was re-entered even when the position did not change
    #: (`restart_item`), and knows it was NOT when a pause or a `continue_item` return resumed the same entry (Slice 14).
    epoch: int = 0
    #: Moves every time a pause (or a detour) actually ends. A driver that missed the pause itself (it was busy, a pause and a resume
    #: came between two of its looks) still learns that one happened, and from `run_paused_ms` how long it lasted (Slice 14).
    resumes: int = 0
    #: When the last pause ended (`at_ms` of the event; -1: never). A driver ignores any user signal older than the explicit
    #: continue that ended the pause: the turn that SAYS "continue" is the cause of the resume, not a new interruption.
    resumed_at_ms: int = -1

    @property
    def active(self) -> bool:
        return self.phase not in (Phase.IDLE, Phase.STOPPED)

    @property
    def owner(self) -> str:
        return "sequence" if self.sequence is not None else "user"


@dataclass(frozen=True, slots=True)
class Transition:
    state: PlaybackState
    effects: tuple[Effect, ...] = ()
    refusal: Refusal | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None


# ------------------------------------------------------------------ the plan (compiled, read-only)


@dataclass(frozen=True, slots=True)
class SceneFacts:
    scene_id: str
    title: str
    section: str
    number: int
    #: anchor_id -> control_id it drives (None: a plain marker, a synchronisation point with no pixel effect).
    anchors: Mapping[str, str | None]


@dataclass(frozen=True, slots=True)
class PlaybackPlan:
    """Read-only view of a score over its variant's scenes. Built by `compile_plan`; never mutated."""

    presentation_id: str
    variant_id: str
    score_id: str
    score_revision: int
    variant_revision: int
    order: tuple[str, ...]
    items: Mapping[str, ScoreItem]
    scenes: Mapping[str, SceneFacts]
    cues: Mapping[str, CueDefinition]
    sequences: Mapping[str, LockedSequence]
    recovery_points: Mapping[str, str]
    estimated_ms: int

    def __len__(self) -> int:
        return len(self.order)

    def item_at(self, position: int) -> ScoreItem:
        return self.items[self.order[position]]

    def scene_at(self, position: int) -> SceneFacts:
        return self.scenes[self.item_at(position).scene_id]

    def sequence_at(self, position: int) -> LockedSequence | None:
        refs = self.item_at(position).sequence_refs()
        return self.sequences[refs[0]] if refs else None

    def positions_of(self, item_id: str) -> tuple[int, ...]:
        return tuple(i for i, value in enumerate(self.order) if value == item_id)

    def first_position_of_scene(self, scene_id: str) -> int | None:
        return next((i for i, value in enumerate(self.order) if self.items[value].scene_id == scene_id), None)

    def armed_targets(self, position: int) -> dict[str, int]:
        """`{cue_id: position}` of the cues armed while the run stands at `position` (armable cues only)."""

        out: dict[str, int] = {}
        for target in range(position + 1, min(position + 1 + ARM_LOOKAHEAD, len(self.order))):
            cue_id = self.item_at(target).cue_id
            if cue_id is not None and self.cues[cue_id].armable:
                out[cue_id] = target
        return out

    def recovery_position(self, point_id: str, near: int) -> int | None:
        item_id = self.recovery_points.get(point_id)
        if item_id is None:
            return None
        spots = self.positions_of(item_id)
        before = [p for p in spots if p <= near]
        return max(before) if before else (min(spots) if spots else None)


def compile_plan(score: Score, scenes: tuple[StudioScene, ...], *, variant_revision: int) -> PlaybackPlan:
    """Pure. The caller has already refused a score with `problems` (a reference that does not resolve)."""

    by_id = {scene.scene_id: scene for scene in scenes}
    facts: dict[str, SceneFacts] = {}
    for number, scene in enumerate(scenes, start=1):
        facts[scene.scene_id] = SceneFacts(scene.scene_id, scene.title, scene.section, number,
                                           {a.anchor_id: a.control_id for a in scene.anchors})
    missing = sorted({i.scene_id for i in score.items} - by_id.keys())
    if missing:
        raise ValueError(f"the score names scenes the variant does not hold: {', '.join(missing[:3])}")
    return PlaybackPlan(
        presentation_id=score.presentation_id, variant_id=score.variant_id, score_id=score.score_id,
        score_revision=score.revision, variant_revision=variant_revision, order=score.playback_order(),
        items={i.item_id: i for i in score.items}, scenes=facts, cues={c.cue_id: c for c in score.cues},
        sequences={s.sequence_id: s for s in score.sequences},
        recovery_points={r.recovery_id: r.item_id for r in score.recovery_points},
        estimated_ms=score.estimated_duration_ms())


# ------------------------------------------------------------------ progress: a fold, never an accumulation


@dataclass(frozen=True, slots=True)
class Progress:
    """Values and reveals the score implies at a position. `values[(scene, control)] = (value, from_anchor)`."""

    values: Mapping[tuple[str, str], tuple[Any, bool]]
    revealed: frozenset[tuple[str, str]]


def _fold(plan: PlaybackPlan, actions: tuple[ActionRef, ...], values: dict, revealed: set) -> None:
    for action in actions:
        if action.kind is ActionKind.CONTROL_SET:
            values[(action.scene_id, action.control_id)] = (action.value, False)
        elif action.kind in (ActionKind.REVEAL, ActionKind.HIDE):
            shown = action.kind is ActionKind.REVEAL
            key = (action.scene_id, action.anchor_id)
            (revealed.add if shown else revealed.discard)(key)
            facts = plan.scenes.get(action.scene_id)
            control = facts.anchors.get(action.anchor_id) if facts is not None else None
            if control is not None:
                values[(action.scene_id, control)] = (shown, True)


def progress_at(plan: PlaybackPlan, position: int, sequence_started: int | None = None,
                manual: tuple[tuple[tuple[str, str], bool], ...] = ()) -> Progress:
    """Fold of every played item's actions up to `position` (visual then motion, then the steps of the locked
    sequence the item hosts), then the manual overrides of the active scene. `sequence_started` is the number of
    steps of the item AT `position` that have started (`None`: all of them, the sequence being done or not running)."""

    values: dict[tuple[str, str], tuple[Any, bool]] = {}
    revealed: set[tuple[str, str]] = set()
    for index in range(position + 1):
        item = plan.item_at(index)
        _fold(plan, item.visual + item.motion, values, revealed)
        sequence = plan.sequence_at(index)
        if sequence is not None:
            count = len(sequence.steps) if index < position or sequence_started is None                 else min(sequence_started, len(sequence.steps))
            for step in sequence.steps[:count]:
                _fold(plan, step.visual + step.motion, values, revealed)
    for (scene_id, anchor_id), shown in manual:
        facts = plan.scenes.get(scene_id)
        (revealed.add if shown else revealed.discard)((scene_id, anchor_id))
        control = facts.anchors.get(anchor_id) if facts is not None else None
        if control is not None:
            values[(scene_id, control)] = (shown, True)
    return Progress(values, frozenset(revealed))


def stage_scene_id(plan: PlaybackPlan, state: PlaybackState) -> str:
    """The scene the stage window shows: the item's own, unless the locked sequence that owns the timeline has *started* a
    `scene_goto` step (a step may visit any scene of the variant; the host item's scene is where the run is, and the stage
    returns to it when the sequence is done, aborted or skipped). Pure fold over the started steps, in written order."""

    scene_id = plan.item_at(state.position).scene_id
    sequence = plan.sequence_at(state.position)
    if sequence is None or state.sequence is None:
        return scene_id
    for step in sequence.steps[:state.sequence.started]:
        for action in step.visual:
            if action.kind is ActionKind.SCENE_GOTO and action.scene_id in plan.scenes:
                scene_id = action.scene_id
    return scene_id


def progress_of(plan: PlaybackPlan, state: PlaybackState) -> Progress:
    started = state.sequence.started if state.sequence is not None else None
    return progress_at(plan, state.position, started, state.manual)


# ------------------------------------------------------------------ the closed table

_P = Phase
#: Event kind -> the phases in which it may happen. Everything else is `illegal_transition`.
TABLE: Mapping[EventKind, frozenset[Phase]] = {
    EventKind.START: frozenset({_P.IDLE, _P.STOPPED}),
    EventKind.STOP: frozenset({_P.PLAYING, _P.PAUSED, _P.DETOUR, _P.RESUMING, _P.ENDED}),
    EventKind.PAUSE: frozenset({_P.PLAYING, _P.RESUMING}),
    EventKind.RESUME: frozenset({_P.PAUSED}),
    EventKind.NEXT: frozenset({_P.PLAYING, _P.ENDED}),
    EventKind.PREVIOUS: frozenset({_P.PLAYING, _P.ENDED}),
    EventKind.GOTO: frozenset({_P.PLAYING, _P.ENDED}),
    EventKind.DETOUR: frozenset({_P.PLAYING, _P.PAUSED, _P.DETOUR}),
    EventKind.RETURN: frozenset({_P.DETOUR}),
    EventKind.REVEAL: frozenset({_P.PLAYING}),
    EventKind.HIDE: frozenset({_P.PLAYING}),
    EventKind.CUE_SATISFIED: frozenset({_P.PLAYING}),
    EventKind.BOUNDARY: frozenset({_P.PLAYING}),
    EventKind.STAGE_SYNCED: frozenset({_P.RESUMING, _P.PLAYING}),
    EventKind.STAGE_FAILED: frozenset({_P.PLAYING, _P.RESUMING, _P.PAUSED, _P.DETOUR, _P.ENDED}),
    EventKind.SEQUENCE_STEP: frozenset({_P.PLAYING}),
    EventKind.SEQUENCE_DONE: frozenset({_P.PLAYING}),
    EventKind.SEQUENCE_ABORT: frozenset({_P.PLAYING, _P.PAUSED}),
    EventKind.SPEAKING: frozenset({_P.PLAYING}),
    EventKind.SKIP_SEQUENCE: frozenset({_P.PLAYING, _P.PAUSED}),
}

#: Why a phase refuses a navigation event, as the user should hear it (the generic table refusal is for the rest).
_PHASE_REASON = {
    _P.IDLE: (RefusalCode.NOT_RUNNING, "no presentation is running"),
    _P.STOPPED: (RefusalCode.NOT_RUNNING, "the run is over"),
    _P.PAUSED: (RefusalCode.PAUSED, "playback is paused: resume first"),
    _P.DETOUR: (RefusalCode.IN_DETOUR, "an auxiliary resource is on screen: return from the detour first"),
    _P.RESUMING: (RefusalCode.RESUMING, "the stage is being brought back: wait for it"),
    _P.ENDED: (RefusalCode.AT_END, "the presentation has ended"),
    _P.PLAYING: (RefusalCode.ILLEGAL_TRANSITION, "not allowed now"),
}


def _refuse(state: PlaybackState, code: RefusalCode, message: str) -> Transition:
    return Transition(state, (), Refusal(code, message))


def idle_state() -> PlaybackState:
    return PlaybackState()


def _enter(plan: PlaybackPlan, state: PlaybackState, position: int, at_ms: int, *, phase: Phase = Phase.PLAYING) -> PlaybackState:
    """Move to an item: per-item runtime (manual reveals, speaker, timers, locked-sequence ownership) starts afresh."""

    sequence = plan.sequence_at(position)
    return replace(state, phase=phase, position=position, manual=(), speaking=None, pending=None, epoch=state.epoch + 1,
                   sequence=SequenceRun(sequence.sequence_id, 0, len(sequence.steps)) if sequence is not None else None,
                   item_started_ms=at_ms, item_paused_ms=0,
                   paused_at_ms=at_ms if phase in (Phase.PAUSED, Phase.DETOUR) else None)


def _settle(plan: PlaybackPlan, before: PlaybackState, after: PlaybackState, effects: list[Effect]) -> Transition:
    """The single place that decides the armed set. Armed only while PLAYING, nobody else owning the timeline, no
    interruption pending: the armed set is then a subset of the armable cues of the next item(s)."""

    armed: tuple[str, ...] = ()
    if after.phase is Phase.PLAYING and after.sequence is None and after.pending is None:
        armed = tuple(plan.armed_targets(after.position))
    if after.phase in (Phase.STOPPED, Phase.IDLE):
        after = replace(after, aux=(), pending=None, sequence=None, detour_from=None, speaking=None)
    if armed != before.armed:
        after = replace(after, armed=armed, generation=before.generation + 1)
        effects.append(Effect.ARM_CHANGED)
    else:
        after = replace(after, armed=armed, generation=before.generation)
    return Transition(after, tuple(dict.fromkeys(effects)))


def _fired(state: PlaybackState, cue_id: str) -> tuple[str, ...]:
    return (*state.fired, cue_id)[-8:]


def _pause_clock(state: PlaybackState, at_ms: int) -> PlaybackState:
    return state if state.paused_at_ms is not None else replace(state, paused_at_ms=at_ms)


def _resume_clock(state: PlaybackState, at_ms: int) -> PlaybackState:
    if state.paused_at_ms is None:
        return state
    gap = max(0, at_ms - state.paused_at_ms)
    return replace(state, paused_at_ms=None, item_paused_ms=state.item_paused_ms + gap,
                   run_paused_ms=state.run_paused_ms + gap, resumes=state.resumes + 1, resumed_at_ms=at_ms)


def apply(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    """One transition. Never raises on a bad *situation* (a typed `Refusal`, state unchanged); raises `ValueError`
    only for a malformed event or plan, which the caller has already validated."""

    if state.phase not in TABLE[event.kind]:
        code, message = _PHASE_REASON[state.phase] if event.kind in _NAVIGATION else (
            RefusalCode.ILLEGAL_TRANSITION, f"{event.kind.value} is not possible while {state.phase.value}")
        if event.kind is EventKind.START and state.active:
            code, message = RefusalCode.ALREADY_RUNNING, "a presentation is already running"
        if event.kind is EventKind.STOP:
            code, message = RefusalCode.NOT_RUNNING, "no presentation is running"
        return _refuse(state, code, message)
    return _HANDLERS[event.kind](plan, state, event)


_NAVIGATION = frozenset({EventKind.NEXT, EventKind.PREVIOUS, EventKind.GOTO, EventKind.REVEAL, EventKind.HIDE,
                         EventKind.CUE_SATISFIED})


def _locked(state: PlaybackState) -> Transition | None:
    if state.sequence is not None:
        return _refuse(state, RefusalCode.LOCKED_SEQUENCE,
                       "a locked sequence owns the timeline: wait for it, abort it, or stop the run")
    return None


def _start(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    if len(plan) == 0:
        return _refuse(state, RefusalCode.EMPTY_SCORE, "the score has no item to play")
    try:
        needs = requirements(event.role, jarvis_speaks=event.jarvis_speaks)
    except ValueError as exc:
        return _refuse(state, RefusalCode.ROLE_INVALID, str(exc))
    fresh = replace(PlaybackState(), run_id=event.run_id, role=event.role, jarvis_speaks=needs.jarvis_speaks,
                    generation=state.generation, run_started_ms=event.at_ms)
    return _settle(plan, state, _enter(plan, fresh, 0, event.at_ms), [Effect.SYNC_STAGE])


def _stop(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    effects = [Effect.RETIRE_ALL, Effect.END_RUN] if state.aux else [Effect.END_RUN]
    return _settle(plan, state, replace(state, phase=Phase.STOPPED), effects)


def _apply_pending(plan: PlaybackPlan, state: PlaybackState, at_ms: int, effects: list[Effect]) -> PlaybackState:
    """An interruption asked while the item said "at the boundary" takes effect now."""

    pending = state.pending
    if pending is None:
        return state
    state = replace(state, pending=None)
    if pending.kind == "pause":
        return replace(_pause_clock(state, at_ms), phase=Phase.PAUSED)
    if pending.aux is not None and len(state.aux) < MAX_AUX_STACK:
        effects.append(Effect.SHOW_AUX)
        return replace(_pause_clock(state, at_ms), phase=Phase.DETOUR, aux=(*state.aux, pending.aux),
                       detour_from=Phase.PLAYING)
    return replace(state, problems=_problem(state, "pending_detour_dropped"))


def _problem(state: PlaybackState, code: str) -> tuple[str, ...]:
    return (*[p for p in state.problems if p != code], code)[-MAX_PROBLEMS:]


def _pause(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    item = plan.item_at(state.position)
    if state.phase is Phase.RESUMING:
        return _settle(plan, state, replace(_pause_clock(state, event.at_ms), phase=Phase.PAUSED), [])
    if item.interruption is Interruption.REFUSE:
        return _refuse(state, RefusalCode.INTERRUPTION_REFUSED, "this item can only be interrupted by stopping the run")
    if item.interruption is Interruption.AT_BOUNDARY:
        return _settle(plan, state, replace(state, pending=Pending("pause")), [])
    return _settle(plan, state, replace(_pause_clock(state, event.at_ms), phase=Phase.PAUSED), [])


def _resume(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    return _settle(plan, state, replace(_resume_clock(state, event.at_ms), phase=Phase.RESUMING), [Effect.SYNC_STAGE])


def _move(plan: PlaybackPlan, state: PlaybackState, target: int, at_ms: int, *, fired: str | None = None) -> Transition:
    """Land on `target`. An interruption that was waiting for a boundary takes effect after the move."""

    pending = state.pending
    effects = [Effect.SYNC_STAGE]
    moved = _enter(plan, replace(state, fired=_fired(state, fired) if fired else state.fired), target, at_ms)
    if pending is not None:
        moved = _apply_pending(plan, replace(moved, pending=pending), at_ms, effects)
    return _settle(plan, state, moved, effects)


def _next(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    locked = _locked(state)
    if locked is not None:
        return locked
    if state.position + 1 >= len(plan):
        if state.phase is Phase.ENDED:
            return _refuse(state, RefusalCode.AT_END, "the presentation has ended")
        return _settle(plan, state, replace(_pause_clock(state, event.at_ms), phase=Phase.ENDED, speaking=None,
                                            pending=None), [])
    return _move(plan, state, state.position + 1, event.at_ms)


def _previous(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    locked = _locked(state)
    if locked is not None:
        return locked
    if state.phase is Phase.ENDED:
        return _move(plan, _resume_clock(state, event.at_ms), len(plan) - 1, event.at_ms)
    if state.position == 0:
        return _refuse(state, RefusalCode.AT_START, "this is the first item")
    return _move(plan, state, state.position - 1, event.at_ms)


def _goto(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    locked = _locked(state)
    if locked is not None:
        return locked
    if event.position is not None:
        target = event.position if event.position < len(plan) else None
    elif event.item_id is not None:
        spots = plan.positions_of(event.item_id)
        # The nearest occurrence of a looped item, ties to the earlier one.
        target = min(spots, key=lambda p: (abs(p - state.position), p)) if spots else None
    else:
        target = plan.first_position_of_scene(event.scene_id or "")
    if target is None:
        return _refuse(state, RefusalCode.UNKNOWN_TARGET, "no such place in this presentation")
    return _move(plan, _resume_clock(state, event.at_ms) if state.phase is Phase.ENDED else state, target, event.at_ms)


def _detour(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    if len(state.aux) >= MAX_AUX_STACK:
        return _refuse(state, RefusalCode.AUX_STACK_FULL, f"at most {MAX_AUX_STACK} auxiliary resources at once")
    if state.phase is Phase.PLAYING:
        item = plan.item_at(state.position)
        if item.interruption is Interruption.REFUSE:
            return _refuse(state, RefusalCode.INTERRUPTION_REFUSED,
                           "this item can only be interrupted by stopping the run")
        if item.interruption is Interruption.AT_BOUNDARY or state.sequence is not None:
            return _settle(plan, state, replace(state, pending=Pending("detour", event.aux)), [])
    came_from = state.detour_from if state.phase is Phase.DETOUR else state.phase
    moved = replace(_pause_clock(state, event.at_ms), phase=Phase.DETOUR, aux=(*state.aux, event.aux),
                    detour_from=came_from, pending=None)
    return _settle(plan, state, moved, [Effect.SHOW_AUX])


def _return(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    if not state.aux:
        return _refuse(state, RefusalCode.NO_DETOUR, "no auxiliary resource is on screen")
    remaining = state.aux[:-1]
    if remaining:
        return _settle(plan, state, replace(state, aux=remaining), [Effect.RETIRE_AUX])
    if state.detour_from is Phase.PAUSED:
        return _settle(plan, state, replace(state, aux=(), detour_from=None, phase=Phase.PAUSED), [Effect.RETIRE_AUX])
    item = plan.item_at(state.position)
    base = replace(_resume_clock(state, event.at_ms), aux=(), detour_from=None)
    position = state.position
    effects = [Effect.RETIRE_AUX, Effect.SYNC_STAGE]
    if item.recovery is Recovery.SKIP_TO_NEXT:
        if position + 1 >= len(plan):
            return _settle(plan, state, replace(base, phase=Phase.ENDED, speaking=None, paused_at_ms=event.at_ms),
                           [Effect.RETIRE_AUX])
        position += 1
    elif item.recovery is Recovery.RECOVERY_POINT and item.recovery_point_id is not None:
        position = plan.recovery_position(item.recovery_point_id, position) or 0
    if item.recovery is Recovery.CONTINUE_ITEM:
        resumed = replace(base, phase=Phase.RESUMING)
    else:  # restart / skip / recovery point: the destination item starts afresh
        resumed = _enter(plan, base, position, event.at_ms, phase=Phase.RESUMING)
    return _settle(plan, state, resumed, effects)


def _reveal(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    facts = plan.scene_at(state.position)
    if event.anchor_id not in facts.anchors:
        return _refuse(state, RefusalCode.UNKNOWN_ANCHOR, "this scene has no such anchor")
    shown = event.kind is EventKind.REVEAL
    key = (facts.scene_id, event.anchor_id)
    manual = tuple(m for m in state.manual if m[0] != key)
    if len(manual) >= MAX_MANUAL:
        return _refuse(state, RefusalCode.REVEAL_LIMIT, "too many manual reveals on this item")
    return _settle(plan, state, replace(state, manual=(*manual, (key, shown))), [Effect.SYNC_STAGE])


def _cue(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    locked = _locked(state)
    if locked is not None:
        return locked
    target = plan.armed_targets(state.position).get(event.cue_id or "") if event.cue_id in state.armed else None
    if target is None:
        if event.cue_id in state.fired:
            return _refuse(state, RefusalCode.CUE_ALREADY_FIRED, "this cue has already fired")
        return _refuse(state, RefusalCode.CUE_NOT_ARMED, "this cue is not armed")
    return _move(plan, state, target, event.at_ms, fired=event.cue_id)


def _boundary(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    effects: list[Effect] = []
    return _settle(plan, state, _apply_pending(plan, state, event.at_ms, effects), effects)


def _synced(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    if state.phase is Phase.PLAYING:
        return _settle(plan, state, state, [])  # idempotent acknowledgement of the first sync
    return _settle(plan, state, replace(state, phase=Phase.PLAYING), [])


def _stage_failed(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    problems = _problem(state, event.problem or "stage_failed")
    if state.phase is Phase.PAUSED or state.phase is Phase.DETOUR or state.phase is Phase.ENDED:
        return _settle(plan, state, replace(state, problems=problems), [])
    return _settle(plan, state, replace(_pause_clock(state, event.at_ms), phase=Phase.PAUSED, problems=problems), [])


def _sequence_step(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    run = state.sequence
    if run is None:
        return _refuse(state, RefusalCode.NO_SEQUENCE, "no locked sequence is running")
    if event.step is None or not run.started <= event.step <= run.count:
        return _refuse(state, RefusalCode.BAD_STEP, "steps only move forward, within the sequence")
    moved = replace(state, sequence=replace(run, started=event.step))
    effects = [Effect.SYNC_STAGE] if event.step != run.started else []
    if state.pending is not None:
        moved = _apply_pending(plan, moved, event.at_ms, effects)
    return _settle(plan, state, moved, effects)


def _sequence_done(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    run = state.sequence
    if run is None:
        return _refuse(state, RefusalCode.NO_SEQUENCE, "no locked sequence is running")
    effects = [Effect.SYNC_STAGE]
    moved = replace(state, sequence=None)
    if state.pending is not None:
        moved = _apply_pending(plan, replace(moved, sequence=None), event.at_ms, effects)
    return _settle(plan, state, moved, effects)


def _sequence_abort(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    run = state.sequence
    if run is None:
        return _refuse(state, RefusalCode.NO_SEQUENCE, "no locked sequence is running")
    item = plan.item_at(state.position)
    if item.interruption is Interruption.REFUSE:
        return _refuse(state, RefusalCode.INTERRUPTION_REFUSED, "this sequence can only be interrupted by stopping the run")
    sequence = plan.sequences[run.sequence_id]
    if sequence.on_interrupt is SequenceInterrupt.ABORT_TO_RECOVERY and sequence.recovery_id is not None:
        target = plan.recovery_position(sequence.recovery_id, state.position)
        if target is None:
            return _refuse(state, RefusalCode.UNKNOWN_TARGET, "the recovery point no longer exists")
        base = _resume_clock(state, event.at_ms) if state.phase is Phase.PAUSED else state
        restarted = _enter(plan, replace(base, sequence=None), target, event.at_ms)
        return _settle(plan, state, restarted, [Effect.SYNC_STAGE])
    # pause_resume: stop at the step boundary; ownership stays with the sequence until it is resumed and done
    if state.phase is Phase.PAUSED:
        return _settle(plan, state, state, [])
    return _settle(plan, state, replace(_pause_clock(state, event.at_ms), phase=Phase.PAUSED, pending=None), [])


def _speaking(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    return _settle(plan, state, replace(state, speaking=event.speaker), [])


def _skip_sequence(plan: PlaybackPlan, state: PlaybackState, event: PlaybackEvent) -> Transition:
    """Leave the locked sequence of the current item and land on the item after it (a paused run stays paused there).

    Allowed whatever the item's interruption policy says: it is the user's own escape, not an interruption by the
    score. A pause that was waiting for the boundary takes effect after the move (`_move`)."""

    if state.sequence is None:
        return _refuse(state, RefusalCode.NO_SEQUENCE, "no locked sequence is running")
    freed = replace(state, sequence=None)
    target = state.position + 1
    if target >= len(plan):
        return _settle(plan, state, replace(_pause_clock(freed, event.at_ms), phase=Phase.ENDED, speaking=None, pending=None),
                       [Effect.SYNC_STAGE])
    if state.phase is Phase.PAUSED:
        return _settle(plan, state, _enter(plan, _resume_clock(freed, event.at_ms), target, event.at_ms, phase=Phase.PAUSED), [Effect.SYNC_STAGE])
    return _move(plan, freed, target, event.at_ms)


def drop_failed_aux(plan: PlaybackPlan, state: PlaybackState, aux_id: str, at_ms: int) -> Transition:
    """Not an event: the service's own undo of a detour whose window could not be shown. Removes the auxiliary resource
    from the stack and, when it was the only one, returns to the phase the detour came from (the stage never left the
    item, so nothing to re-sync). The armed set is recomputed by the single `_settle`."""

    remaining = tuple(a for a in state.aux if a.aux_id != aux_id)
    if len(remaining) == len(state.aux):
        return Transition(state)
    if remaining:
        return _settle(plan, state, replace(state, aux=remaining), [])
    if state.detour_from is Phase.PAUSED:
        return _settle(plan, state, replace(state, aux=(), detour_from=None, phase=Phase.PAUSED), [])
    return _settle(plan, state, replace(_resume_clock(state, at_ms), aux=(), detour_from=None, phase=Phase.PLAYING), [])


_HANDLERS = {
    EventKind.START: _start, EventKind.STOP: _stop, EventKind.PAUSE: _pause, EventKind.RESUME: _resume,
    EventKind.NEXT: _next, EventKind.PREVIOUS: _previous, EventKind.GOTO: _goto, EventKind.DETOUR: _detour,
    EventKind.RETURN: _return, EventKind.REVEAL: _reveal, EventKind.HIDE: _reveal, EventKind.CUE_SATISFIED: _cue,
    EventKind.BOUNDARY: _boundary, EventKind.STAGE_SYNCED: _synced, EventKind.STAGE_FAILED: _stage_failed,
    EventKind.SEQUENCE_STEP: _sequence_step, EventKind.SEQUENCE_DONE: _sequence_done,
    EventKind.SEQUENCE_ABORT: _sequence_abort, EventKind.SPEAKING: _speaking, EventKind.SKIP_SEQUENCE: _skip_sequence,
}
assert set(_HANDLERS) == set(EventKind) == set(TABLE), "every event kind has exactly one table row and one handler"


# ------------------------------------------------------------------ invariants (tests and a debug guard)


def check_invariants(plan: PlaybackPlan, state: PlaybackState) -> list[str]:
    """Everything that must hold in every reachable state. Empty list = sound."""

    bad: list[str] = []
    if state.phase is Phase.IDLE:
        return [] if state == idle_state() else ["an idle state is not pristine"]
    if not 0 <= state.position < len(plan):
        bad.append("position outside the expanded score order")
    if len(state.aux) > MAX_AUX_STACK:
        bad.append("auxiliary stack beyond its bound")
    if (state.phase is Phase.DETOUR) != bool(state.aux):
        bad.append("detour phase and auxiliary stack disagree")
    if state.armed and state.phase is not Phase.PLAYING:
        bad.append("cues armed outside PLAYING")
    armable = {cue_id for cue_id, cue in plan.cues.items() if cue.armable}
    if not set(state.armed) <= armable:
        bad.append("armed set is not a subset of the score's armable cues")
    free = state.phase is Phase.PLAYING and state.sequence is None and state.pending is None
    expected = set(plan.armed_targets(state.position)) if free and 0 <= state.position < len(plan) else set()
    if set(state.armed) != expected:
        bad.append("armed set is not exactly the lookahead of a free PLAYING position")
    if state.phase in (Phase.STOPPED,) and (state.aux or state.armed or state.sequence is not None):
        bad.append("a stopped run holds resources")
    if state.sequence is not None:
        hosted = plan.sequence_at(state.position)
        if hosted is None or hosted.sequence_id != state.sequence.sequence_id:
            bad.append("sequence ownership outside its host item")
        elif not 0 <= state.sequence.started <= state.sequence.count:
            bad.append("sequence step outside the sequence")
    if len(state.manual) > MAX_MANUAL or len(state.problems) > MAX_PROBLEMS or len(state.fired) > 8:
        bad.append("a runtime collection is beyond its bound")
    if state.generation < 0:
        bad.append("negative generation")
    return bad


# ------------------------------------------------------------------ "where are we"


def _elapsed(state: PlaybackState, now_ms: int) -> tuple[int, int]:
    """`(item_ms, run_ms)`: time since the item / run began, minus time spent paused or in a detour."""

    edge = state.paused_at_ms if state.paused_at_ms is not None else now_ms
    if state.phase is Phase.STOPPED or state.phase is Phase.IDLE:
        return 0, 0
    return (max(0, edge - state.item_started_ms - state.item_paused_ms),
            max(0, edge - state.run_started_ms - state.run_paused_ms))


def where_are_we(plan: PlaybackPlan | None, state: PlaybackState, now_ms: int) -> dict[str, Any]:
    """Bounded answer to "where are we, what comes next?" (<= `MAX_WHERE_BYTES` serialised, tested at the worst case).

    Never the item's `text` or `note` (the script), never a full cue predicate: scene title, item label, the next
    cue's *label* and at most `MAX_WHERE_PHRASES` trigger phrases, elapsed against the soft target. Titles and
    labels are author-typed free text: `untrusted` names every such field so a consumer treats them as data.
    """

    if plan is None or not state.active and state.phase is Phase.IDLE:
        return {"phase": state.phase.value, "running": False}
    if state.phase is Phase.STOPPED:
        return {"phase": state.phase.value, "running": False, "run_id": state.run_id}
    item = plan.item_at(state.position)
    scene = plan.scene_at(state.position)
    item_ms, run_ms = _elapsed(state, now_ms)
    progress = progress_of(plan, state)
    shown = sorted(a for s, a in progress.revealed if s == scene.scene_id)[:MAX_REVEALED_SHOWN]
    out: dict[str, Any] = {
        "phase": state.phase.value, "running": True, "run_id": state.run_id,
        "role": state.role.value if state.role else None, "jarvis_speaks": state.jarvis_speaks,
        "position": {"index": state.position + 1, "of": len(plan)},
        "scene": {"scene_id": scene.scene_id, "title": scene.title, "section": scene.section,
                  "number": scene.number, "of": len(plan.scenes)},
        "item": {"item_id": item.item_id, "label": item.label, "presenter": item.presenter.value,
                 "kind": item.kind.value, "timing": item.timing.value, "interruption": item.interruption.value,
                 "recovery": item.recovery.value},
        "speaking": state.speaking.value if state.speaking else None,
        "silence": item.kind is ItemKind.SILENCE,
        "revealed": shown,
        "elapsed": {"item_ms": item_ms, "item_target_ms": item.target_duration_ms,
                    "item_over_target": bool(item.target_duration_ms and item_ms > item.target_duration_ms),
                    "run_ms": run_ms, "run_estimated_ms": plan.estimated_ms},
        "owner": state.owner, "armed": len(state.armed), "generation": state.generation,
        "pending": state.pending.kind if state.pending else None, "problems": list(state.problems),
        "next": None, "detour": None, "sequence": None,
    }
    untrusted = ["scene.title", "scene.section", "item.label"]
    if state.aux:
        out["detour"] = {"depth": len(state.aux), "title": state.aux[-1].title}
        untrusted.append("detour.title")
    if state.sequence is not None:
        out["sequence"] = {"sequence_id": state.sequence.sequence_id, "step": state.sequence.started,
                           "of": state.sequence.count,
                           "duration_ms": plan.sequences[state.sequence.sequence_id].duration_ms}
    if state.position + 1 < len(plan):
        nxt = plan.item_at(state.position + 1)
        entry: dict[str, Any] = {"item_label": nxt.label, "scene_title": plan.scenes[nxt.scene_id].title,
                                 "presenter": nxt.presenter.value, "cue": None}
        untrusted += ["next.item_label", "next.scene_title"]
        if nxt.cue_id is not None:
            cue = plan.cues[nxt.cue_id]
            entry["cue"] = {"label": cue.label, "armable": cue.armable, "armed": nxt.cue_id in state.armed,
                            "phrases": [p for p in cue.predicate.phrases][:MAX_WHERE_PHRASES]}
            untrusted += ["next.cue.label", "next.cue.phrases"]
        out["next"] = entry
    out["untrusted"] = untrusted
    return out


# ------------------------------------------------------------------ plan changes during a run


def rebase(old: PlaybackPlan, state: PlaybackState, new: PlaybackPlan) -> tuple[PlaybackState, str | None]:
    """Keep a run on the same item after an edit changed the plan. Returns `(state, problem)`; `problem` is a stable
    code when the item is gone (the run lands on the first item of its scene, else the start) or the sequence changed.

    The run is never stopped by an edit: the caller leaves it PAUSED so the author resumes on purpose.
    """

    if len(new) == 0:
        return replace(state, position=0), "plan_empty"
    item_id = old.order[state.position]
    spots = new.positions_of(item_id)
    problem: str | None = None
    if spots:
        position = min(spots, key=lambda p: (abs(p - state.position), p))
    else:
        scene_id = old.item_at(state.position).scene_id
        found = new.first_position_of_scene(scene_id)
        position, problem = (found, "item_removed") if found is not None else (0, "scene_removed")
    sequence = state.sequence
    hosted = new.sequence_at(position)
    if sequence is not None and (hosted is None or hosted.sequence_id != sequence.sequence_id):
        sequence, problem = None, problem or "sequence_removed"
    elif sequence is not None:
        sequence = SequenceRun(sequence.sequence_id, min(sequence.started, len(hosted.steps)), len(hosted.steps))
    moved = replace(state, position=position, sequence=sequence,
                    manual=tuple(m for m in state.manual if m[0][0] in new.scenes and m[0][1] in new.scenes[m[0][0]].anchors))
    return moved, problem


def settle_after_rebase(plan: PlaybackPlan, before: PlaybackState, after: PlaybackState) -> Transition:
    """Recompute the armed set for the rebased state (the same single place as every transition)."""

    return _settle(plan, before, after, [Effect.SYNC_STAGE])
