"""Ligne de temps d'une scène Remotion, pure (handoff jarvis-remotion-presentation-integration, Slice 12).

Prouvé sans E/S : la table d'images (cadence, durée, identifiant de composition du manifeste ; déterministe et bornée), le découpage en
segments par les ancres, le segment demandé par la partition (ancre révélée la plus loin, réversible), le temps joué du segment (pauses
exclues), le report des ancres d'une version à l'autre (par `scene_id`, en ms), et que les révélations d'une séquence verrouillée
déplacent le segment. La forme d'une ancre d'avant (sans `at_ms`) ne bouge pas d'un octet.
Contrat : `docs/presentation-studio.md` > *Remotion timeline bridge*.
"""

from __future__ import annotations

import json
import random

import pytest

from jarvis.domain import presentation_studio_playback as pb
from jarvis.domain.presentation_studio_roles import StudioRole
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_scene import MAX_ANCHOR_AT_MS, ScoreAnchor
from jarvis.domain.presentation_studio_score import parse_score
from jarvis.domain.remotion_timeline import (
    ANCHOR_CLAMPED, ANCHORS_PARTLY_TIMED, ANCHORS_SHARE_FRAME, DRIFT_TOLERANCE_MS, FrameMap, Mark, SegmentClock, TimelineError,
    build_frame_map, frame_of_ms, segment_for, target_segment, timeline_wire,
)
from tests.fakes.presentation_studio_score import document, scenes

COMP = {"id": "Intro-Scene", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": 300}


def anchors(*specs):
    return tuple(ScoreAnchor(name, name.title(), None, at) for name, at in specs)


# ------------------------------------------------------------------ the anchor keeps its old shape

def test_an_anchor_without_a_position_serialises_exactly_as_before():
    anchor = ScoreAnchor("callout", "Callout", "accent")
    assert json.dumps(anchor.to_dict(), sort_keys=True) == '{"anchor_id": "callout", "control_id": "accent", "label": "Callout"}'
    assert ScoreAnchor.from_dict(anchor.to_dict()) == anchor


def test_a_positioned_anchor_round_trips_and_the_position_is_validated():
    anchor = ScoreAnchor("beat", "Beat", None, 2500)
    assert anchor.to_dict()["at_ms"] == 2500 and ScoreAnchor.from_dict(anchor.to_dict()) == anchor
    for bad in (-1, MAX_ANCHOR_AT_MS + 1, 1.5, "2000", True):
        with pytest.raises(PresentationStudioError):
            ScoreAnchor("beat", "Beat", None, bad)  # type: ignore[arg-type]
    with pytest.raises(PresentationStudioError):
        ScoreAnchor.from_dict({"anchor_id": "beat", "label": "Beat", "at_frames": 3})   # an unknown key is still a refusal


# ------------------------------------------------------------------ frame mapping

def test_positions_become_frames_with_the_manifests_cadence_and_are_clamped():
    fmap = build_frame_map("s1", COMP, anchors(("a", 0), ("b", 2000), ("c", 6000), ("d", 999_999)))
    assert (fmap.composition_id, fmap.fps, fmap.duration_frames) == ("Intro-Scene", 30, 300)
    assert [m.frame for m in fmap.marks] == [0, 60, 180, 299]
    assert fmap.marks[3].clamped and ANCHOR_CLAMPED in fmap.problems
    assert frame_of_ms(34, 30, 300) == 1 and frame_of_ms(16, 30, 300) == 0 and frame_of_ms(10**9, 30, 300) == 299


def test_the_same_position_is_another_frame_at_another_cadence_and_duration():
    """Carry-over between versions: the author wrote milliseconds, the new version has its own fps and length."""

    spec = anchors(("a", 1000), ("b", 4000))
    old = build_frame_map("s1", COMP, spec)
    new = build_frame_map("s1", {**COMP, "fps": 60, "duration_in_frames": 120}, spec)    # 2 s long at 60 fps
    assert [m.frame for m in old.marks] == [30, 120] and [m.frame for m in new.marks] == [60, 119]
    assert new.marks[1].clamped and old.frame_of("b") == 120 and new.frame_of("a") == 60
    assert new.scene_id == old.scene_id == "s1"                          # anchors still resolve by scene id


def test_anchors_without_a_position_are_spread_evenly_and_deterministically():
    spec = anchors(("a", None), ("b", None), ("c", None), ("d", None))
    assert [m.frame for m in build_frame_map("s1", COMP, spec).marks] == [0, 75, 150, 225]
    assert build_frame_map("s1", COMP, spec) == build_frame_map("s1", COMP, spec)
    assert build_frame_map("s1", COMP, anchors(("only", None))).marks == (Mark("only", 0),)


def test_mixed_and_colliding_anchors_are_reported_not_hidden():
    mixed = build_frame_map("s1", COMP, anchors(("a", 3000), ("b", None)))
    assert ANCHORS_PARTLY_TIMED in mixed.problems
    same = build_frame_map("s1", COMP, anchors(("a", 1000), ("b", 1010)))
    assert ANCHORS_SHARE_FRAME in same.problems and same.marks[0].frame == same.marks[1].frame
    assert build_frame_map("s1", COMP, anchors(("a", 1000), ("b", 2000))).problems == ()


def test_a_scene_without_anchors_has_no_timeline_and_a_bad_composition_is_refused():
    assert build_frame_map("s1", COMP, ()) is None
    for bad in ({**COMP, "fps": 0}, {**COMP, "fps": 121}, {**COMP, "duration_in_frames": 0}, {**COMP, "duration_in_frames": 108_001},
                {**COMP, "fps": 29.97}, {**COMP, "id": ""}, {"id": "X"}):
        with pytest.raises(TimelineError):
            build_frame_map("s1", bad, anchors(("a", 0)))
    assert build_frame_map("s1", {"id": "X", "fps": 24, "durationInFrames": 48}, anchors(("a", 0))).duration_frames == 48   # descriptor spelling


def test_frames_are_always_inside_the_composition_whatever_the_inputs():
    rng = random.Random(12)
    for _ in range(400):
        fps, duration = rng.randint(1, 120), rng.randint(1, 5000)
        spec = tuple(ScoreAnchor(f"a{i}", "A", None, rng.choice([None, rng.randint(0, MAX_ANCHOR_AT_MS)])) for i in range(rng.randint(1, 16)))
        fmap = build_frame_map("s", {"id": "C", "fps": fps, "duration_in_frames": duration}, spec)
        assert all(0 <= m.frame <= duration - 1 for m in fmap.marks)
        for mark in fmap.marks:
            seg = segment_for(fmap, mark.anchor_id)
            assert seg.start == mark.frame <= seg.until <= duration - 1
        entry = segment_for(fmap, None)
        assert 0 == entry.start <= entry.until <= duration - 1


# ------------------------------------------------------------------ segments

def timed():
    return build_frame_map("s1", COMP, anchors(("intro", 1000), ("middle", 4000), ("end", 8000)))    # frames 30, 120, 240


def test_the_timeline_is_cut_into_segments_that_stop_on_the_frame_before_the_next_anchor():
    fmap = timed()
    assert (segment_for(fmap, None).start, segment_for(fmap, None).until) == (0, 29)                # the lead-in plays up to the first beat
    assert (segment_for(fmap, "intro").start, segment_for(fmap, "intro").until) == (30, 119)
    assert (segment_for(fmap, "middle").start, segment_for(fmap, "middle").until) == (120, 239)
    assert (segment_for(fmap, "end").start, segment_for(fmap, "end").until) == (240, 299)           # the last one plays to the end
    with pytest.raises(KeyError):
        segment_for(fmap, "nope")


def test_an_anchor_at_frame_zero_has_no_lead_in_and_adjacent_anchors_hold_their_frame():
    zero = build_frame_map("s1", COMP, anchors(("a", 0), ("b", 4000)))
    entry = segment_for(zero, None)
    assert (entry.start, entry.until) == (0, 0)
    tight = build_frame_map("s1", COMP, anchors(("a", 1000), ("b", 1034)))     # 30 and 31
    assert (segment_for(tight, "a").start, segment_for(tight, "a").until) == (30, 30)


def test_the_furthest_revealed_anchor_sets_the_playhead_and_hiding_goes_back():
    fmap = timed()
    assert target_segment(fmap, set()).anchor_id is None
    assert target_segment(fmap, {"intro"}).anchor_id == "intro"
    assert target_segment(fmap, {"intro", "end"}).anchor_id == "end"
    assert target_segment(fmap, {"intro", "middle"}).anchor_id == "middle"
    assert target_segment(fmap, {"intro"}).anchor_id == "intro"                    # "end" hidden: reversible
    assert target_segment(fmap, {"ghost"}).anchor_id is None                       # an anchor the scene lost is ignored, not an error


def test_the_wire_form_is_small_typed_and_a_hold_is_never_playing():
    fmap = timed()
    wire = timeline_wire(fmap, segment_for(fmap, "middle"), playing=True, seq=3, play_ms=1500)
    assert wire == {"scene_id": "s1", "composition_id": "Intro-Scene", "fps": 30, "duration_frames": 300, "anchor_id": "middle",
                    "from_frame": 120, "until_frame": 239, "playing": True, "seq": 3, "play_ms": 1500,
                    "tolerance_ms": DRIFT_TOLERANCE_MS, "problems": []}
    assert len(json.dumps(wire)) < 400
    hold = build_frame_map("s1", COMP, anchors(("a", 0), ("b", 4000)))
    assert timeline_wire(hold, segment_for(hold, None), playing=True, seq=1, play_ms=0)["playing"] is False


# ------------------------------------------------------------------ the segment clock

def test_the_clock_counts_played_time_only_and_a_new_segment_restarts_it():
    clock = SegmentClock()
    assert clock.observe("k1", True, 1000, 5000) == (1, 0)
    assert clock.observe("k1", True, 1700, 5000) == (1, 700)
    assert clock.observe("k1", False, 2000, 5000) == (1, 1000)                       # paused
    assert clock.observe("k1", False, 9000, 5000) == (1, 1000)                       # the pause costs nothing
    assert clock.observe("k1", True, 9000, 5000) == (1, 1000)                        # resumed: same segment, same seq
    assert clock.observe("k1", True, 9500, 5000) == (1, 1500)
    assert clock.observe("k2", True, 9600, 5000) == (2, 0)                           # another segment: restart, seq moves
    assert clock.observe("k2", True, 99_000, 5000) == (2, 5000)                      # capped at the segment length
    clock.reset()
    assert clock.observe("k2", True, 100_000, 5000) == (3, 0)                        # a new run never inherits, seq stays monotonic


def test_observing_twice_with_the_same_state_changes_nothing():
    clock = SegmentClock()
    clock.observe("k", True, 0, 10_000)
    first = clock.observe("k", True, 500, 10_000)
    assert clock.observe("k", True, 500, 10_000) == first


# ------------------------------------------------------------------ the locked sequence keeps the master clock

def sequence_plan():
    fixture = scenes()
    spec = {6: anchors(("callout", 1000), ("chart", 4000))}
    from dataclasses import replace
    stage = tuple(replace(s, anchors=spec[i + 1]) if (i + 1) in spec else s for i, s in enumerate(fixture))
    return pb.compile_plan(parse_score(document()), stage, variant_revision=1), stage


def test_a_locked_sequences_reveals_move_the_playhead_step_by_step_and_a_hide_pulls_it_back():
    plan, stage = sequence_plan()
    fmap = build_frame_map(stage[5].scene_id, COMP, stage[5].anchors)
    E, P = pb.EventKind, pb.Phase
    state = pb.apply(plan, pb.idle_state(), pb.PlaybackEvent(E.START, 0, run_id="run-1", role=StudioRole.USER_PRESENTER)).state
    state = pb.apply(plan, state, pb.PlaybackEvent(E.GOTO, 1, position=5)).state
    assert state.sequence is not None and state.phase is P.PLAYING

    def anchor_now(s):
        revealed = {a for scene, a in pb.progress_of(plan, s).revealed if scene == fmap.scene_id}
        return target_segment(fmap, revealed).anchor_id

    assert anchor_now(state) is None                                              # nothing revealed yet: the lead-in
    state = pb.apply(plan, state, pb.PlaybackEvent(E.SEQUENCE_STEP, 2, step=1)).state
    assert anchor_now(state) == "chart"                                           # step "intro" reveals the chart
    state = pb.apply(plan, state, pb.PlaybackEvent(E.SEQUENCE_STEP, 3, step=2)).state
    assert anchor_now(state) == "chart"                                           # a motion step moves no beat
    paused = pb.apply(plan, state, pb.PlaybackEvent(E.PAUSE, 4)).state
    assert paused.phase in (P.PAUSED, P.PLAYING) and anchor_now(paused) == "chart"   # the executor's pause keeps the beat
    # the Score is untouched by any of this: the same document parses to the same plan
    assert pb.compile_plan(parse_score(document()), stage, variant_revision=1).order == plan.order


def test_the_frame_map_is_a_value_and_does_not_depend_on_the_order_the_dict_was_written():
    a = build_frame_map("s1", {"id": "C", "fps": 30, "duration_in_frames": 90}, anchors(("x", 500)))
    b = build_frame_map("s1", {"duration_in_frames": 90, "fps": 30, "id": "C"}, anchors(("x", 500)))
    assert a == b and isinstance(a, FrameMap)


def test_the_wrap_step_of_the_sequence_does_not_hide_an_anchor_that_was_never_revealed_and_stays_reversible():
    plan, stage = sequence_plan()
    fmap = build_frame_map(stage[5].scene_id, COMP, stage[5].anchors)
    E = pb.EventKind
    state = pb.apply(plan, pb.idle_state(), pb.PlaybackEvent(E.START, 0, run_id="run-1", role=StudioRole.USER_PRESENTER)).state
    state = pb.apply(plan, state, pb.PlaybackEvent(E.GOTO, 1, position=5)).state
    state = pb.apply(plan, state, pb.PlaybackEvent(E.SEQUENCE_STEP, 2, step=3)).state          # all three steps started
    revealed = {a for scene, a in pb.progress_of(plan, state).revealed if scene == fmap.scene_id}
    assert revealed == {"chart"} and target_segment(fmap, revealed).anchor_id == "chart"
