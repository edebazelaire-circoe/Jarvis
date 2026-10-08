"""State machine of the playback runtime (jarvis-interactive-presentation-studio, Slice 12), pure.

Every phase x event of the closed table, every typed refusal, a seeded random walk that never reaches an illegal
state, exact detour/resume, locked-sequence ownership, reversible progress, the bounded "where are we" answer and the
armed-set message. Contract: `docs/presentation-studio.md` > *Playback runtime contract*.
"""

from __future__ import annotations

import json
import random

import pytest

from jarvis.domain import presentation_studio_playback as pb
from jarvis.domain.presentation_studio_armed_set import (
    ARMED_CHANGED, ReportLedger, ReportLimiter, build_armed_set, changed_payload, parse_cue_report,
)
from jarvis.domain.presentation_studio_roles import StudioRole
from jarvis.domain.presentation_studio_score import Presenter
from tests.fakes.presentation_studio_score import cue_id, item_id, scene_id, scenes, score

PLAN = pb.compile_plan(score(), scenes(), variant_revision=3)
AUX = pb.AuxRef("aux-one", "Chart of margins", "lab.chart", 2)
AUX2 = pb.AuxRef("aux-two", "Second", "lab.chart", 3)
E = pb.EventKind
P = pb.Phase
LOCKED = 5       # position of the locked "demo" item (psi_6) in the expanded order
LOOP_A, LOOP_B = 7, 9


def ev(kind, at=0, **kw):
    return pb.PlaybackEvent(kind, at, **kw)


class Run:
    """Drives the machine and checks the invariants after every step."""

    def __init__(self, plan=PLAN, role=StudioRole.USER_PRESENTER, at=0):
        self.plan, self.state, self.at, self.effects, self.last = plan, pb.idle_state(), at, (), None
        self.do(E.START, run_id="run-1", role=role)

    def do(self, kind, dt=10, **kw):
        self.at += dt
        before = self.state
        t = pb.apply(self.plan, before, pb.PlaybackEvent(kind, self.at, **kw))
        assert pb.check_invariants(self.plan, t.state) == [], (kind, t)
        if not t.ok:
            assert t.state == before, "a refusal leaves the state untouched"
        assert t.state.generation >= before.generation
        assert (t.state.armed != before.armed) == (t.state.generation != before.generation)
        self.state, self.effects, self.last = t.state, t.effects, t
        return t

    def goto(self, position):
        t = self.do(E.GOTO, position=position)
        assert t.ok, t.refusal
        return t

    def to_end(self):
        self.goto(len(self.plan) - 1)
        assert self.do(E.NEXT).ok
        assert self.state.phase is P.ENDED


def refusal(t):
    assert not t.ok
    return t.refusal.code


# ------------------------------------------------------------------ the plan


def test_the_plan_is_the_expanded_score_order_with_the_loop():
    assert len(PLAN) == 14 and PLAN.order[LOOP_A] == PLAN.order[LOOP_B] == item_id(8)
    assert PLAN.positions_of(item_id(8)) == (7, 9)
    assert PLAN.scenes[scene_id(3)].number == 3 and PLAN.scenes[scene_id(2)].anchors == {"callout": None, "chart": "accent"}
    assert PLAN.sequence_at(LOCKED).sequence_id == "demo" and PLAN.sequence_at(0) is None
    assert PLAN.score_revision == 1 and PLAN.variant_revision == 3


def test_a_score_naming_a_scene_the_variant_lacks_is_not_compiled():
    with pytest.raises(ValueError, match="scenes the variant does not hold"):
        pb.compile_plan(score(), scenes()[:3], variant_revision=1)


def test_only_the_next_armable_cue_is_ever_armed():
    assert PLAN.armed_targets(0) == {cue_id(1): 1}
    assert PLAN.armed_targets(1) == {}                      # next item has no cue
    assert PLAN.armed_targets(2) == {}                      # cue 2 is not armable (manual advance)
    assert PLAN.armed_targets(6) == {cue_id(3): 7}


# ------------------------------------------------------------------ every phase x event of the closed table

def _state_in(phase: P) -> Run:
    run = Run()
    if phase is P.IDLE:
        run.state = pb.idle_state()
    elif phase is P.PAUSED:
        run.do(E.PAUSE)
    elif phase is P.DETOUR:
        run.do(E.DETOUR, aux=AUX)
    elif phase is P.RESUMING:
        run.do(E.PAUSE)
        run.do(E.RESUME)
    elif phase is P.ENDED:
        run.to_end()
    elif phase is P.STOPPED:
        run.do(E.STOP)
    assert run.state.phase is phase
    return run


SAMPLE = {
    E.START: dict(run_id="run-2", role=StudioRole.USER_PRESENTER), E.GOTO: dict(position=2),
    E.DETOUR: dict(aux=AUX), E.REVEAL: dict(anchor_id="callout"), E.HIDE: dict(anchor_id="callout"),
    E.CUE_SATISFIED: dict(cue_id=cue_id(1)), E.STAGE_FAILED: dict(problem="stage_failed"),
    E.SEQUENCE_STEP: dict(step=1), E.SPEAKING: dict(speaker=Presenter.USER),
}


@pytest.mark.parametrize("phase", list(P))
@pytest.mark.parametrize("kind", list(E))
def test_every_phase_and_event_is_either_a_legal_transition_or_a_typed_refusal(phase, kind):
    run = _state_in(phase)
    before = run.state
    t = pb.apply(PLAN, before, pb.PlaybackEvent(kind, run.at + 5, **SAMPLE.get(kind, {})))
    assert pb.check_invariants(PLAN, t.state) == []
    if phase not in pb.TABLE[kind]:
        assert not t.ok and t.state == before and t.effects == ()
        assert isinstance(t.refusal.code, pb.RefusalCode) and t.refusal.message
    elif not t.ok:
        assert t.state == before and isinstance(t.refusal.code, pb.RefusalCode)
    else:
        assert all(isinstance(e, pb.Effect) for e in t.effects)


def test_the_table_has_a_row_and_a_handler_for_every_event_kind():
    assert set(pb.TABLE) == set(E) == set(pb._HANDLERS)
    assert all(phases <= set(P) for phases in pb.TABLE.values())


@pytest.mark.parametrize("phase, kind, code", [
    (P.IDLE, E.NEXT, pb.RefusalCode.NOT_RUNNING), (P.STOPPED, E.NEXT, pb.RefusalCode.NOT_RUNNING),
    (P.PAUSED, E.NEXT, pb.RefusalCode.PAUSED), (P.DETOUR, E.NEXT, pb.RefusalCode.IN_DETOUR),
    (P.RESUMING, E.NEXT, pb.RefusalCode.RESUMING), (P.ENDED, E.REVEAL, pb.RefusalCode.AT_END),
    (P.PLAYING, E.START, pb.RefusalCode.ALREADY_RUNNING), (P.PAUSED, E.START, pb.RefusalCode.ALREADY_RUNNING),
    (P.IDLE, E.STOP, pb.RefusalCode.NOT_RUNNING), (P.STOPPED, E.STOP, pb.RefusalCode.NOT_RUNNING),
    (P.PLAYING, E.RESUME, pb.RefusalCode.ILLEGAL_TRANSITION), (P.PAUSED, E.PAUSE, pb.RefusalCode.ILLEGAL_TRANSITION),
    (P.PLAYING, E.RETURN, pb.RefusalCode.ILLEGAL_TRANSITION), (P.PAUSED, E.CUE_SATISFIED, pb.RefusalCode.PAUSED),
])
def test_the_refusal_names_the_real_reason(phase, kind, code):
    run = _state_in(phase)
    assert refusal(pb.apply(PLAN, run.state, pb.PlaybackEvent(kind, run.at + 5, **SAMPLE.get(kind, {})))) is code


def test_a_stopped_run_can_start_a_fresh_one_and_idle_can_start():
    run = _state_in(P.STOPPED)
    first_generation = run.state.generation
    assert run.do(E.START, run_id="run-2", role=StudioRole.REHEARSAL).ok
    assert run.state.phase is P.PLAYING and run.state.run_id == "run-2" and run.state.generation > first_generation


# ------------------------------------------------------------------ start and roles

def test_start_lands_on_the_first_item_and_asks_for_the_stage_and_the_arm():
    run = Run()
    s = run.state
    assert (s.phase, s.position, s.role, s.run_id, s.jarvis_speaks) == (P.PLAYING, 0, StudioRole.USER_PRESENTER, "run-1", False)
    assert run.effects == (pb.Effect.SYNC_STAGE, pb.Effect.ARM_CHANGED) and s.armed == (cue_id(1),) and s.generation == 1


@pytest.mark.parametrize("role, speaks, ok", [
    (StudioRole.USER_PRESENTER, None, True), (StudioRole.USER_PRESENTER, True, False),
    (StudioRole.JARVIS_PRESENTER, None, True), (StudioRole.JARVIS_PRESENTER, False, False),
    (StudioRole.REHEARSAL, None, True), (StudioRole.REHEARSAL, True, True),
])
def test_roles_follow_the_slice_01c_requirements(role, speaks, ok):
    t = pb.apply(PLAN, pb.idle_state(), pb.PlaybackEvent(E.START, 0, run_id="r", role=role, jarvis_speaks=speaks))
    assert t.ok is ok
    if ok:
        assert t.state.jarvis_speaks is (role is StudioRole.JARVIS_PRESENTER or bool(speaks))
    else:
        assert refusal(t) is pb.RefusalCode.ROLE_INVALID


def test_an_empty_score_cannot_be_started():
    empty = pb.PlaybackPlan("pst_" + "a" * 32, "psv_" + "b" * 32, "psr_000000000001", 1, 1, (), {}, {}, {}, {}, {}, 0)
    t = pb.apply(empty, pb.idle_state(), pb.PlaybackEvent(E.START, 0, run_id="r", role=StudioRole.REHEARSAL))
    assert refusal(t) is pb.RefusalCode.EMPTY_SCORE


# ------------------------------------------------------------------ navigation

def test_next_previous_goto_and_the_ends():
    run = Run()
    assert refusal(run.do(E.PREVIOUS)) is pb.RefusalCode.AT_START
    assert run.do(E.NEXT).ok and run.state.position == 1
    assert run.do(E.PREVIOUS).ok and run.state.position == 0
    run.goto(4)
    assert run.state.position == 4
    assert refusal(run.do(E.GOTO, position=99)) is pb.RefusalCode.UNKNOWN_TARGET
    assert refusal(run.do(E.GOTO, item_id="psi_ffffffffffff")) is pb.RefusalCode.UNKNOWN_TARGET
    assert refusal(run.do(E.GOTO, scene_id="pss_ffffffffffff")) is pb.RefusalCode.UNKNOWN_TARGET
    assert run.do(E.GOTO, scene_id=scene_id(3)).ok and run.state.position == 2
    run.to_end()
    assert refusal(run.do(E.NEXT)) is pb.RefusalCode.AT_END
    assert run.do(E.PREVIOUS).ok and run.state.phase is P.PLAYING and run.state.position == len(PLAN) - 1


def test_goto_an_item_in_a_loop_picks_the_nearest_occurrence():
    run = Run()
    run.goto(LOOP_B)
    run.do(E.GOTO, item_id=item_id(8))
    assert run.state.position == LOOP_B
    run.goto(1)
    run.do(E.GOTO, item_id=item_id(8))
    assert run.state.position == LOOP_A


def test_malformed_events_are_value_errors_not_states():
    for bad in (dict(kind=E.GOTO, at_ms=0), dict(kind=E.GOTO, at_ms=0, position=1, scene_id="x"),
                dict(kind=E.CUE_SATISFIED, at_ms=0, cue_id="hello there"), dict(kind=E.CUE_SATISFIED, at_ms=0),
                dict(kind=E.NEXT, at_ms=-1), dict(kind=E.DETOUR, at_ms=0), dict(kind=E.REVEAL, at_ms=0),
                dict(kind=E.START, at_ms=0), dict(kind=E.STAGE_FAILED, at_ms=0)):
        with pytest.raises(ValueError):
            pb.PlaybackEvent(**bad)


# ------------------------------------------------------------------ pause, detour, resume: exact position

def test_pause_and_resume_return_to_the_same_item_through_a_synced_stage():
    run = Run()
    run.goto(3)
    before = run.state
    assert run.do(E.PAUSE).ok and run.state.phase is P.PAUSED and run.state.armed == ()
    assert run.do(E.RESUME).ok and run.state.phase is P.RESUMING and pb.Effect.SYNC_STAGE in run.effects
    assert run.state.armed == ()                                       # not armed until the stage is back
    assert run.do(E.STAGE_SYNCED).ok and run.state.phase is P.PLAYING
    assert run.state.position == before.position and run.state.armed == before.armed


def test_a_failed_stage_sync_pauses_with_a_visible_problem_instead_of_playing_on():
    run = Run()
    run.do(E.PAUSE)
    run.do(E.RESUME)
    assert run.do(E.STAGE_FAILED, problem="stage_failed").ok
    assert run.state.phase is P.PAUSED and run.state.problems == ("stage_failed",)
    assert run.do(E.RESUME).ok and run.do(E.STAGE_SYNCED).ok and run.state.phase is P.PLAYING


@pytest.mark.parametrize("position", [0, 1, 2, 3, 4, 6, LOOP_A, LOOP_B, 10, 12])
def test_detour_and_return_restore_the_exact_score_position(position):
    run = Run()
    run.goto(position)
    item = PLAN.item_at(position)
    before = run.state
    if item.interruption.value == "refuse":
        return
    t = run.do(E.DETOUR, aux=AUX)
    assert t.ok and run.state.phase is P.DETOUR and run.state.position == position and run.state.aux == (AUX,)
    assert pb.Effect.SHOW_AUX in t.effects and run.state.armed == ()
    assert refusal(run.do(E.NEXT)) is pb.RefusalCode.IN_DETOUR              # the position is frozen
    t = run.do(E.RETURN)
    assert t.ok and pb.Effect.RETIRE_AUX in t.effects and run.state.aux == ()
    run.do(E.STAGE_SYNCED)
    assert run.state.phase is P.PLAYING
    if item.recovery.value == "continue_item":
        assert run.state.position == position and run.state.armed == before.armed


def test_nested_detours_pop_one_at_a_time_and_the_stack_is_bounded():
    run = Run()
    for index in range(pb.MAX_AUX_STACK):
        assert run.do(E.DETOUR, aux=pb.AuxRef(f"aux-{index}", "t", "lab.chart", 1)).ok
    assert refusal(run.do(E.DETOUR, aux=AUX)) is pb.RefusalCode.AUX_STACK_FULL and len(run.state.aux) == pb.MAX_AUX_STACK
    for left in range(pb.MAX_AUX_STACK - 1, 0, -1):
        assert run.do(E.RETURN).ok and run.state.phase is P.DETOUR and len(run.state.aux) == left
    assert run.do(E.RETURN).ok and run.state.phase is P.RESUMING
    assert refusal(run.do(E.RETURN)) is pb.RefusalCode.ILLEGAL_TRANSITION


def test_a_detour_from_a_pause_returns_to_the_pause():
    run = Run()
    run.goto(2)
    run.do(E.PAUSE)
    assert run.do(E.DETOUR, aux=AUX).ok and run.state.detour_from is P.PAUSED
    assert run.do(E.RETURN).ok and run.state.phase is P.PAUSED and run.state.position == 2


def test_restart_item_recovery_starts_the_item_afresh():
    """psi_4 (position 3) restarts itself: same item, runtime of the item cleared, clock restarted."""

    run = Run()
    run.goto(3)
    assert PLAN.item_at(3).recovery is pb.Recovery.RESTART_ITEM
    run.do(E.PAUSE)
    run.do(E.DETOUR, aux=AUX)
    run.do(E.RETURN)
    assert run.state.phase is P.PAUSED                                     # a detour from a pause returns to the pause
    run.do(E.RESUME)
    run.do(E.STAGE_SYNCED)
    run.goto(3)
    run.do(E.DETOUR, aux=AUX, dt=500)
    run.do(E.RETURN, dt=500)
    returned_at = run.at
    run.do(E.STAGE_SYNCED)
    assert run.state.position == 3 and run.state.manual == () and run.state.item_paused_ms == 0
    assert run.state.item_started_ms == returned_at


def test_recovery_to_a_point_and_skip_to_next_are_exact():
    run = Run()
    run.goto(11)                                     # psi_10: recovery_point "opening" -> item 1 (position 0)
    assert PLAN.item_at(11).recovery_point_id == "opening"
    run.do(E.DETOUR, aux=AUX)
    run.do(E.RETURN)
    assert run.state.position == 0 and run.state.phase is P.RESUMING


def test_skip_to_next_past_the_end_ends_the_run_cleanly():
    items = dict(PLAN.items)
    last = PLAN.order[-1]
    from dataclasses import replace
    items[last] = replace(items[last], recovery=pb.Recovery.SKIP_TO_NEXT)
    plan = pb.PlaybackPlan(**{**{f: getattr(PLAN, f) for f in PLAN.__dataclass_fields__}, "items": items})
    run = Run(plan)
    run.goto(len(plan) - 1)
    run.do(E.DETOUR, aux=AUX)
    t = run.do(E.RETURN)
    assert t.ok and run.state.phase is P.ENDED and run.state.aux == ()


def test_interruption_policy_of_the_item_is_enforced():
    items = dict(PLAN.items)
    from dataclasses import replace
    mid = PLAN.order[2]
    items[mid] = replace(items[mid], interruption=pb.Interruption.REFUSE)
    plan = pb.PlaybackPlan(**{**{f: getattr(PLAN, f) for f in PLAN.__dataclass_fields__}, "items": items})
    run = Run(plan)
    run.goto(2)
    assert refusal(run.do(E.PAUSE)) is pb.RefusalCode.INTERRUPTION_REFUSED
    assert refusal(run.do(E.DETOUR, aux=AUX)) is pb.RefusalCode.INTERRUPTION_REFUSED
    assert run.do(E.STOP).ok                                           # the explicit stop always works


# ------------------------------------------------------------------ locked sequence ownership

def test_a_locked_sequence_owns_the_timeline_until_it_is_done():
    run = Run()
    run.goto(LOCKED)
    s = run.state
    assert s.sequence == pb.SequenceRun("demo", 0, 3) and s.owner == "sequence" and s.armed == ()
    for kind, extra in ((E.NEXT, {}), (E.PREVIOUS, {}), (E.GOTO, dict(position=0)), (E.CUE_SATISFIED, dict(cue_id=cue_id(3)))):
        assert refusal(run.do(kind, **extra)) is pb.RefusalCode.LOCKED_SEQUENCE, kind
    assert run.do(E.SEQUENCE_STEP, step=1).ok and run.state.sequence.started == 1
    assert refusal(run.do(E.SEQUENCE_STEP, step=0)) is pb.RefusalCode.BAD_STEP      # forward only
    assert refusal(run.do(E.SEQUENCE_STEP, step=9)) is pb.RefusalCode.BAD_STEP
    assert run.do(E.SEQUENCE_DONE).ok and run.state.owner == "user" and run.state.sequence is None
    assert run.do(E.NEXT).ok and run.state.position == LOCKED + 1


def test_an_interruption_at_the_boundary_waits_for_the_next_step_boundary():
    run = Run()
    run.goto(LOCKED)
    assert PLAN.item_at(LOCKED).interruption.value == "at_boundary"
    assert run.do(E.PAUSE).ok and run.state.phase is P.PLAYING and run.state.pending.kind == "pause"
    t = run.do(E.SEQUENCE_STEP, step=1)
    assert t.ok and run.state.phase is P.PAUSED and run.state.pending is None and run.state.sequence.started == 1
    assert run.do(E.RESUME).ok and run.do(E.STAGE_SYNCED).ok
    assert run.state.sequence.started == 1 and run.state.phase is P.PLAYING      # the sequence continues, not restarts


def test_a_pending_detour_shows_at_the_boundary_event():
    run = Run()
    run.goto(LOCKED)
    assert run.do(E.DETOUR, aux=AUX).ok and run.state.phase is P.PLAYING and run.state.pending.aux == AUX
    assert run.do(E.BOUNDARY).ok and run.state.phase is P.DETOUR and run.state.aux == (AUX,)
    assert run.state.sequence is not None                                    # still the sequence's, after the detour


def test_abort_follows_the_sequence_policy():
    run = Run()
    run.goto(LOCKED)
    run.do(E.SEQUENCE_STEP, step=2)
    assert run.do(E.SEQUENCE_ABORT).ok                                       # demo: pause_resume
    assert run.state.phase is P.PAUSED and run.state.sequence.started == 2
    assert refusal(pb.apply(PLAN, pb.idle_state(), pb.PlaybackEvent(E.SEQUENCE_ABORT, 1))) is pb.RefusalCode.ILLEGAL_TRANSITION
    no_sequence = Run()
    assert refusal(no_sequence.do(E.SEQUENCE_ABORT)) is pb.RefusalCode.NO_SEQUENCE


def test_abort_to_recovery_goes_to_the_recovery_point():
    from dataclasses import replace
    demo = PLAN.sequences["demo"]
    sequences = {"demo": replace(demo, on_interrupt=pb.SequenceInterrupt.ABORT_TO_RECOVERY, recovery_id="opening")}
    plan = pb.PlaybackPlan(**{**{f: getattr(PLAN, f) for f in PLAN.__dataclass_fields__}, "sequences": sequences})
    run = Run(plan)
    run.goto(LOCKED)
    assert run.do(E.SEQUENCE_ABORT).ok
    assert run.state.position == 0 and run.state.sequence is None and run.state.phase is P.PLAYING


def test_a_sequence_that_refuses_interruption_only_stops():
    from dataclasses import replace
    items = dict(PLAN.items)
    host = PLAN.order[LOCKED]
    items[host] = replace(items[host], interruption=pb.Interruption.REFUSE)
    plan = pb.PlaybackPlan(**{**{f: getattr(PLAN, f) for f in PLAN.__dataclass_fields__}, "items": items})
    run = Run(plan)
    run.goto(LOCKED)
    assert refusal(run.do(E.SEQUENCE_ABORT)) is pb.RefusalCode.INTERRUPTION_REFUSED
    assert refusal(run.do(E.PAUSE)) is pb.RefusalCode.INTERRUPTION_REFUSED
    assert run.do(E.STOP).ok and run.state.sequence is None


# ------------------------------------------------------------------ cue satisfied: typed ids only

def test_a_satisfied_armed_cue_moves_to_its_item_and_fires_once():
    run = Run()
    t = run.do(E.CUE_SATISFIED, cue_id=cue_id(1))
    assert t.ok and run.state.position == 1 and run.state.fired == (cue_id(1),)
    assert pb.Effect.SYNC_STAGE in t.effects
    assert refusal(run.do(E.CUE_SATISFIED, cue_id=cue_id(1))) is pb.RefusalCode.CUE_ALREADY_FIRED


def test_an_unarmed_or_unknown_cue_is_refused_and_changes_nothing():
    run = Run()
    before = run.state
    assert refusal(run.do(E.CUE_SATISFIED, cue_id=cue_id(3))) is pb.RefusalCode.CUE_NOT_ARMED        # armed later
    assert refusal(run.do(E.CUE_SATISFIED, cue_id=cue_id(2))) is pb.RefusalCode.CUE_NOT_ARMED        # not armable
    assert refusal(run.do(E.CUE_SATISFIED, cue_id="psc_ffffffffffff")) is pb.RefusalCode.CUE_NOT_ARMED
    assert run.state == before


def test_the_armed_set_follows_the_position_and_is_empty_outside_a_free_playing_run():
    run = Run()
    assert run.state.armed == (cue_id(1),)
    run.do(E.NEXT)
    assert run.state.armed == ()
    run.goto(6)
    assert run.state.armed == (cue_id(3),)
    generation = run.state.generation
    run.do(E.PAUSE)
    assert run.state.armed == () and run.state.generation == generation + 1
    run.do(E.RESUME)
    run.do(E.STAGE_SYNCED)
    assert run.state.armed == (cue_id(3),)
    run.do(E.DETOUR, aux=AUX)
    assert run.state.armed == ()


def test_a_cue_can_fire_again_when_a_declared_loop_arms_it_again():
    run = Run()
    run.goto(6)
    assert run.do(E.CUE_SATISFIED, cue_id=cue_id(3)).ok and run.state.position == LOOP_A
    run.goto(LOOP_B)
    run.do(E.PREVIOUS)                       # position 8 (psi_9); the next position (9) is item 8 again
    assert run.state.position == 8
    assert run.state.armed == (cue_id(3),)           # its cue is armed again by the declared loop
    assert run.do(E.CUE_SATISFIED, cue_id=cue_id(3)).ok and run.state.position == LOOP_B


# ------------------------------------------------------------------ reveal, hide and reversible progress

def test_navigation_is_reversible_values_and_reveals_are_a_fold_of_the_score():
    key_glow, key_accent = (scene_id(3), "glow"), (scene_id(8), "accent")
    run = Run()
    run.goto(1)
    assert (scene_id(2), "callout") in pb.progress_of(PLAN, run.state).revealed
    run.goto(2)                                                         # psi_3: glow := 8 on scene 3
    assert pb.progress_of(PLAN, run.state).values[key_glow] == (8, False)
    run.goto(7)                                                         # psi_8: accent := #ff8800 on scene 8
    assert pb.progress_of(PLAN, run.state).values[key_accent] == ("#ff8800", False)
    run.goto(1)                                                         # back: later values are gone, the earlier stay
    after = pb.progress_of(PLAN, run.state)
    assert key_accent not in after.values and key_glow not in after.values
    assert (scene_id(2), "callout") in after.revealed
    run.goto(7)
    assert pb.progress_of(PLAN, run.state) == pb.progress_at(PLAN, 7)   # position determines progress, not the route


def test_a_control_bound_anchor_drives_its_control_and_a_marker_does_not():
    progress = pb.progress_at(PLAN, 4)                                   # psi_5 reveals "chart" (bound to "accent") on scene 5
    assert progress.values[(scene_id(5), "accent")] == (True, True)
    assert (scene_id(5), "chart") in progress.revealed
    marker = pb.progress_at(PLAN, 1)                                     # "callout" has no control
    assert (scene_id(2), "callout") in marker.revealed and not any(k[0] == scene_id(2) for k in marker.values)


def test_manual_reveal_and_hide_are_bounded_per_item_and_cleared_on_navigation():
    run = Run()
    run.goto(1)
    assert run.do(E.HIDE, anchor_id="callout").ok
    assert (scene_id(2), "callout") not in pb.progress_of(PLAN, run.state).revealed
    assert run.do(E.REVEAL, anchor_id="chart").ok
    assert pb.progress_of(PLAN, run.state).values[(scene_id(2), "accent")] == (True, True)
    assert refusal(run.do(E.REVEAL, anchor_id="nope")) is pb.RefusalCode.UNKNOWN_ANCHOR
    run.do(E.NEXT)
    run.do(E.PREVIOUS)
    assert run.state.manual == () and (scene_id(2), "callout") in pb.progress_of(PLAN, run.state).revealed


def test_sequence_step_actions_apply_as_steps_start_and_all_apply_once_past():
    run = Run()
    run.goto(LOCKED)
    assert (scene_id(6), "chart") not in pb.progress_of(PLAN, run.state).revealed
    run.do(E.SEQUENCE_STEP, step=1)
    assert (scene_id(6), "chart") in pb.progress_of(PLAN, run.state).revealed
    assert (scene_id(6), "glow") not in pb.progress_of(PLAN, run.state).values
    run.do(E.SEQUENCE_STEP, step=3)
    run.do(E.SEQUENCE_DONE)
    run.do(E.NEXT)
    values = pb.progress_of(PLAN, run.state).values
    assert values[(scene_id(6), "glow")] == (9, False)


# ------------------------------------------------------------------ speaker, silence and time

def test_speaker_and_explicit_silence_are_state():
    run = Run()
    run.goto(2)
    assert pb.where_are_we(PLAN, run.state, run.at)["silence"] is True      # psi_3 is an explicit silence item
    assert run.do(E.SPEAKING, speaker=Presenter.JARVIS).ok and run.state.speaking is Presenter.JARVIS
    run.do(E.NEXT)
    assert run.state.speaking is None


def test_elapsed_time_excludes_pauses_and_detours_and_compares_with_the_soft_target():
    run = Run(at=1000)
    run.goto(2)                                        # psi_3: soft target 4000 ms
    start = run.at
    run.at += 3000
    w = pb.where_are_we(PLAN, run.state, run.at)
    assert w["elapsed"]["item_ms"] == 3000 and w["elapsed"]["item_target_ms"] == 4000 and not w["elapsed"]["item_over_target"]
    run.do(E.PAUSE, dt=0)
    run.at += 60_000
    assert pb.where_are_we(PLAN, run.state, run.at)["elapsed"]["item_ms"] == 3000      # frozen while paused
    run.do(E.RESUME, dt=0)
    run.do(E.STAGE_SYNCED, dt=0)
    run.at += 2000
    w = pb.where_are_we(PLAN, run.state, run.at)
    assert w["elapsed"]["item_ms"] == 5000 and w["elapsed"]["item_over_target"] is True
    assert w["elapsed"]["run_ms"] == run.at - 1010 - 60_000 and start < run.at


# ------------------------------------------------------------------ "where are we": bounded, no script

def test_where_are_we_is_a_bounded_answer_without_the_script():
    run = Run()
    run.goto(1)                                                         # next is psi_3 (silence, no cue)
    w = pb.where_are_we(PLAN, run.state, run.at)
    assert w["scene"]["title"] == "Scene 2" and w["position"] == {"index": 2, "of": 14}
    assert w["next"]["scene_title"] == "Scene 3" and w["next"]["cue"] is None
    text = json.dumps(w, ensure_ascii=False)
    for line in ("Explain the context in my own words", "Bonjour, voici le plan", "Merci de votre attention"):
        assert line not in text, "the script (text / note) never leaves through where_are_we"
    run.goto(0)
    cue = pb.where_are_we(PLAN, run.state, run.at)["next"]["cue"]
    assert cue["label"] == "Context done" and cue["armed"] is True and len(cue["phrases"]) <= pb.MAX_WHERE_PHRASES
    assert "next.cue.label" in pb.where_are_we(PLAN, run.state, run.at)["untrusted"]


def test_the_answer_stays_bounded_with_the_longest_allowed_free_text():
    from dataclasses import replace
    long = "é" * pb.MAX_LABEL
    items = dict(PLAN.items)
    for index in (0, 1):
        items[PLAN.order[index]] = replace(items[PLAN.order[index]], label=long)
    scenes_ = {k: replace(v, title=long, section=long) for k, v in PLAN.scenes.items()}
    cues = dict(PLAN.cues)
    plan = pb.PlaybackPlan(**{**{f: getattr(PLAN, f) for f in PLAN.__dataclass_fields__}, "items": items, "scenes": scenes_})
    run = Run(plan)
    run.do(E.DETOUR, aux=pb.AuxRef("aux-x", long, "lab.chart", 1))
    w = pb.where_are_we(plan, run.state, run.at)
    assert len(json.dumps(w, ensure_ascii=False).encode("utf-8")) <= pb.MAX_WHERE_BYTES and cues


def test_where_are_we_before_and_after_a_run_is_a_small_fact():
    assert pb.where_are_we(PLAN, pb.idle_state(), 0) == {"phase": "idle", "running": False}
    assert pb.where_are_we(None, pb.idle_state(), 0) == {"phase": "idle", "running": False}
    run = _state_in(P.STOPPED)
    assert pb.where_are_we(PLAN, run.state, 5) == {"phase": "stopped", "running": False, "run_id": "run-1"}


# ------------------------------------------------------------------ rebase after an edit

def test_rebase_keeps_the_run_on_the_same_item_and_reports_a_removed_one():
    run = Run()
    run.goto(7)
    new = pb.PlaybackPlan(**{**{f: getattr(PLAN, f) for f in PLAN.__dataclass_fields__}, "score_revision": 2})
    state, problem = pb.rebase(PLAN, run.state, new)
    assert state.position == 7 and problem is None
    short_order = tuple(i for i in PLAN.order if i != item_id(8))
    short = pb.PlaybackPlan(**{**{f: getattr(PLAN, f) for f in PLAN.__dataclass_fields__}, "order": short_order})
    state, problem = pb.rebase(PLAN, run.state, short)
    assert problem == "item_removed" and state.position == short.first_position_of_scene(scene_id(8))         and short.item_at(state.position).item_id == item_id(8) or state.position == 0
    settled = pb.settle_after_rebase(short, run.state, state).state
    assert pb.check_invariants(short, settled) == []


# ------------------------------------------------------------------ the random walk

#: The walk leans on navigation so that it reaches the interesting corners (locked item, end, detours).
_WEIGHTS = {E.NEXT: 6, E.PREVIOUS: 2, E.GOTO: 4, E.PAUSE: 2, E.RESUME: 2, E.DETOUR: 3, E.RETURN: 3, E.STAGE_SYNCED: 3,
            E.CUE_SATISFIED: 3, E.SEQUENCE_STEP: 2, E.SEQUENCE_DONE: 2, E.BOUNDARY: 1, E.START: 1, E.STOP: 1}


def _random_event(rng: random.Random, plan: pb.PlaybackPlan, at: int, first: bool = False) -> pb.PlaybackEvent:
    if first:
        return pb.PlaybackEvent(E.START, at, run_id="run-r", role=rng.choice(list(StudioRole)))
    kinds = [kind for kind in E for _ in range(_WEIGHTS.get(kind, 1))]
    kind = rng.choice(kinds)
    kw: dict = {}
    if kind is E.START:
        kw = dict(run_id="run-r", role=rng.choice(list(StudioRole)), jarvis_speaks=rng.choice([None, True, False]))
    elif kind is E.GOTO:
        kw = rng.choice([dict(position=rng.randrange(0, len(plan) + 2)), dict(item_id=rng.choice(plan.order)),
                         dict(scene_id=rng.choice(list(plan.scenes))), dict(position=len(plan) - 1)])
    elif kind is E.DETOUR:
        kw = dict(aux=pb.AuxRef(f"aux-{rng.randrange(9)}", "t", "lab.chart", 1))
    elif kind in (E.REVEAL, E.HIDE):
        kw = dict(anchor_id=rng.choice(["callout", "chart", "nope"]))
    elif kind is E.CUE_SATISFIED:
        kw = dict(cue_id=rng.choice([cue_id(1), cue_id(2), cue_id(3), "psc_ffffffffffff"]))
    elif kind is E.SEQUENCE_STEP:
        kw = dict(step=rng.randrange(0, 5))
    elif kind is E.STAGE_FAILED:
        kw = dict(problem="stage_failed")
    elif kind is E.SPEAKING:
        kw = dict(speaker=rng.choice([None, Presenter.USER, Presenter.JARVIS]))
    return pb.PlaybackEvent(kind, at, **kw)


@pytest.mark.parametrize("seed", range(40))
def test_random_sequences_never_reach_an_illegal_state(seed):
    rng = random.Random(seed)
    state, at = pb.idle_state(), 0
    seen_phases: set = set()
    for step in range(150):
        at += rng.randrange(0, 500)
        event = _random_event(rng, PLAN, at, first=step == 0)
        t = pb.apply(PLAN, state, event)
        assert pb.check_invariants(PLAN, t.state) == [], (seed, event, t)
        assert len(t.state.aux) <= pb.MAX_AUX_STACK
        assert set(t.state.armed) <= set(PLAN.cues)
        assert t.state.generation >= state.generation
        if not t.ok:
            assert t.state == state and t.effects == ()
        seen_phases.add(t.state.phase)
        state = t.state
    assert len(seen_phases) >= 2, "the walk must actually move through the machine"


def test_the_walks_between_them_cover_every_phase():
    covered: set = {P.IDLE}
    for seed in range(40):
        rng = random.Random(seed)
        state, at = pb.idle_state(), 0
        for step in range(150):
            at += 1
            state = pb.apply(PLAN, state, _random_event(rng, PLAN, at, first=step == 0)).state
            covered.add(state.phase)
    assert covered == set(P)


# ------------------------------------------------------------------ the armed-set message

def test_the_armed_set_message_carries_ids_phrases_run_and_generation_only():
    run = Run()
    msg = build_armed_set(PLAN, run.state, ttl_s=90.0)
    wire = msg.to_dict()
    assert wire["run_id"] == "run-1" and wire["generation"] == run.state.generation and wire["expires_in_s"] == 90.0
    assert wire["cues"] == [{"cue_id": cue_id(1), "phrases": ["next the context", "passons au contexte"],
                             "semantics": ["topic_context"]}]
    assert wire["ambiguous"] == {}
    assert changed_payload(run.state) == {"run_id": "run-1", "generation": run.state.generation, "count": 1}
    assert ARMED_CHANGED == "presentation_studio.armed.changed"
    run.do(E.PAUSE)
    assert build_armed_set(PLAN, run.state).cues == ()
    assert build_armed_set(None, pb.idle_state()).to_dict()["cues"] == []


def test_cue_reports_are_exactly_three_typed_fields():
    ok = parse_cue_report({"run_id": "run-1", "generation": 2, "cue_id": cue_id(1)})
    assert (ok.run_id, ok.generation, ok.cue_id) == ("run-1", 2, cue_id(1))
    for bad in ({}, {"run_id": "r", "generation": 1, "cue_id": cue_id(1), "text": "hello"},
                {"run_id": "r", "generation": True, "cue_id": cue_id(1)}, {"run_id": "r", "generation": -1, "cue_id": cue_id(1)},
                {"run_id": "r", "generation": 1, "cue_id": "passons au contexte"}, {"run_id": "", "generation": 1, "cue_id": cue_id(1)},
                "psc_000000000001", None):
        with pytest.raises(ValueError):
            parse_cue_report(bad)


def test_the_report_limiter_is_a_token_bucket_and_the_ledger_is_bounded():
    limiter = ReportLimiter(rate_per_s=2.0, burst=3)
    assert [limiter.allow(0.0) for _ in range(4)] == [True, True, True, False]
    assert limiter.allow(0.6) is True and limiter.allow(0.6) is False
    ledger = ReportLedger(size=2)
    reports = [parse_cue_report({"run_id": "r", "generation": g, "cue_id": cue_id(1)}) for g in range(3)]
    for report in reports:
        ledger.remember(report, {"g": report.generation})
    assert ledger.get(reports[0]) is None and ledger.get(reports[2]) == {"g": 2}
    ledger.clear()
    assert ledger.get(reports[2]) is None
