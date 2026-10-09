"""The interruption policy of a locked sequence, as data (`presentation_studio_sequence`), agrees with the playback machine
(`presentation_studio_playback.apply`) on every cell (jarvis-interactive-presentation-studio, Slice 14).

Two modules state the same table (the executor reads one, the machine enforces the other); this file is what stops them drifting.
Plans are compiled for real from the Slice 12 fixture score with the declared policy changed on one item.
"""

from __future__ import annotations

import pytest

from jarvis.domain import presentation_studio_playback as pb
from jarvis.domain.presentation_studio_roles import StudioRole
from jarvis.domain.presentation_studio_score import Interruption, parse_score
from jarvis.domain.presentation_studio_sequence import InputKind, Verdict, input_verdict
from tests.fakes.presentation_studio_score import mutated, scenes

E, P = pb.EventKind, pb.Phase
LOCKED, PLAIN = 5, 0          # positions in the Slice 12 fixture score: the locked "demo" host, and an ordinary Jarvis item
AUX = pb.AuxRef("aux-one", "Chart", "lab.chart", 2)


def plan_with(interruption: str, *, position: int):
    """The fixture score with `interruption` declared on the item at `position`, compiled for real."""

    doc = mutated(["items", position, "interruption"], interruption)
    return pb.compile_plan(parse_score(doc), scenes(), variant_revision=1)


def at(plan, position):
    state = pb.apply(plan, pb.idle_state(), pb.PlaybackEvent(E.START, 0, run_id="run-1", role=StudioRole.USER_PRESENTER)).state
    if position:
        state = pb.apply(plan, state, pb.PlaybackEvent(E.GOTO, 1, position=position)).state
    assert state.position == position and state.phase is P.PLAYING
    return state


def outcome(plan, state, kind, **fields):
    transition = pb.apply(plan, state, pb.PlaybackEvent(kind, 5, **fields))
    if not transition.ok:
        return Verdict.REFUSE, transition
    after = transition.state
    if after.phase in (P.PAUSED, P.DETOUR):
        return Verdict.NOW, transition
    if after.pending is not None:
        return Verdict.AT_BOUNDARY, transition
    raise AssertionError(f"{kind}: applied but neither taken nor pending")


@pytest.mark.parametrize("policy", ["at_boundary", "refuse"])
@pytest.mark.parametrize("kind, event, fields", [
    (InputKind.PAUSE, E.PAUSE, {}), (InputKind.DETOUR, E.DETOUR, {"aux": AUX})])
def test_the_policy_table_is_what_the_machine_does_at_a_locked_sequence(policy, kind, event, fields):
    plan = plan_with(policy, position=LOCKED)
    state = at(plan, LOCKED)
    assert state.sequence is not None
    verdict, transition = outcome(plan, state, event, **fields)
    assert verdict is input_verdict(Interruption(policy), kind)
    if verdict is Verdict.REFUSE:
        assert transition.refusal.code is pb.RefusalCode.INTERRUPTION_REFUSED


@pytest.mark.parametrize("kind, event, fields", [
    (InputKind.PAUSE, E.PAUSE, {}), (InputKind.DETOUR, E.DETOUR, {"aux": AUX})])
def test_the_policy_table_is_what_the_machine_does_on_an_item_that_allows_interruption(kind, event, fields):
    plan = plan_with("allow", position=PLAIN)
    verdict, _ = outcome(plan, at(plan, PLAIN), event, **fields)
    assert verdict is input_verdict(Interruption.ALLOW, kind) is Verdict.NOW


@pytest.mark.parametrize("policy", ["at_boundary", "refuse"])
@pytest.mark.parametrize("event, fields", [(E.NEXT, {}), (E.PREVIOUS, {}), (E.GOTO, {"position": 2}),
                                           (E.CUE_SATISFIED, {"cue_id": "psc_000000000001"})])
def test_navigation_is_refused_while_a_sequence_owns_the_timeline_whatever_the_policy(policy, event, fields):
    plan = plan_with(policy, position=LOCKED)
    state = at(plan, LOCKED)
    transition = pb.apply(plan, state, pb.PlaybackEvent(event, 5, **fields))
    assert input_verdict(Interruption(policy), InputKind.NAVIGATE) is Verdict.REFUSE and not transition.ok
    assert transition.refusal.code in (pb.RefusalCode.LOCKED_SEQUENCE, pb.RefusalCode.CUE_NOT_ARMED)
    assert transition.state == state


@pytest.mark.parametrize("policy", ["at_boundary", "refuse"])
def test_stop_and_skip_always_get_out_whatever_the_policy(policy):
    plan = plan_with(policy, position=LOCKED)
    state = at(plan, LOCKED)
    assert pb.apply(plan, state, pb.PlaybackEvent(E.SKIP_SEQUENCE, 5)).ok
    stop = pb.apply(plan, state, pb.PlaybackEvent(E.STOP, 5))
    assert stop.ok and stop.state.phase is P.STOPPED
    assert input_verdict(Interruption(policy), InputKind.SKIP) is input_verdict(Interruption(policy), InputKind.STOP) is Verdict.NOW


def test_a_pending_pause_is_taken_by_the_boundary_event_before_the_next_step():
    plan = plan_with("at_boundary", position=LOCKED)
    state = pb.apply(plan, at(plan, LOCKED), pb.PlaybackEvent(E.PAUSE, 6)).state
    assert state.pending is not None and state.phase is P.PLAYING and state.sequence is not None
    taken = pb.apply(plan, state, pb.PlaybackEvent(E.BOUNDARY, 7)).state
    assert taken.phase is P.PAUSED and taken.sequence is not None and taken.sequence.started == 0   # ownership kept, no step lost


def test_an_abort_to_recovery_sequence_lands_on_its_recovery_point_exactly():
    doc = mutated(["sequences", 0, "on_interrupt"], "abort_to_recovery")
    doc["sequences"][0]["recovery_id"] = "demo_start"
    plan = pb.compile_plan(parse_score(doc), scenes(), variant_revision=1)
    state = pb.apply(plan, at(plan, LOCKED), pb.PlaybackEvent(E.SEQUENCE_STEP, 8, step=2)).state
    aborted = pb.apply(plan, state, pb.PlaybackEvent(E.SEQUENCE_ABORT, 9))
    assert aborted.ok and aborted.state.position == plan.recovery_position("demo_start", LOCKED) == LOCKED
    assert aborted.state.epoch == state.epoch + 1 and aborted.state.sequence.started == 0   # re-entered afresh


def test_the_epoch_moves_exactly_when_an_item_is_entered():
    plan = plan_with("at_boundary", position=LOCKED)
    state = at(plan, 0)
    epoch = state.epoch
    paused = pb.apply(plan, state, pb.PlaybackEvent(E.PAUSE, 3)).state
    resumed = pb.apply(plan, paused, pb.PlaybackEvent(E.RESUME, 4)).state
    synced = pb.apply(plan, resumed, pb.PlaybackEvent(E.STAGE_SYNCED, 5)).state
    assert synced.epoch == epoch                                              # pause + resume re-enters nothing
    assert pb.apply(plan, synced, pb.PlaybackEvent(E.NEXT, 6)).state.epoch == epoch + 1


def test_a_step_scene_goto_moves_the_stage_scene_until_the_sequence_ends():
    doc = mutated(["sequences", 0, "steps", 1, "visual"], [{"kind": "scene_goto", "scene_id": "pss_000000000009"}])
    plan = pb.compile_plan(parse_score(doc), scenes(), variant_revision=1)
    state = at(plan, LOCKED)
    assert pb.stage_scene_id(plan, state) == "pss_000000000006"               # the host item's scene
    state = pb.apply(plan, state, pb.PlaybackEvent(E.SEQUENCE_STEP, 8, step=1)).state
    assert pb.stage_scene_id(plan, state) == "pss_000000000006"               # step 0 visits nothing
    state = pb.apply(plan, state, pb.PlaybackEvent(E.SEQUENCE_STEP, 9, step=2)).state
    assert pb.stage_scene_id(plan, state) == "pss_000000000009"               # step 1 visits scene 9
    done = pb.apply(plan, state, pb.PlaybackEvent(E.SEQUENCE_DONE, 10)).state
    assert pb.stage_scene_id(plan, done) == "pss_000000000006"                # ownership returns: the stage returns to the item
