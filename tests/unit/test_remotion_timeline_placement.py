"""Placement du lecteur dans une lecture de présentateur, pur (handoff jarvis-remotion-native-studio-playback-fix, Slice 07).

Prouvé sans E/S (`remotion_timeline.place`) : une scène nouvellement entrée part de son image locale 0 et joue jusqu'au `until` de
l'élément, même quand l'élément d'entrée révèle une ancre à `at_ms > 0` (défaut C) ; un retour ou un saut tient l'image d'arrêt de
l'élément visé sans rejouer les segments d'avant ; une reprise dans la même scène garde le même segment (donc la même image) ; la partition
qui avance dans la même scène joue le segment de la nouvelle ancre depuis l'image où le lecteur s'est arrêté ; une lecture enchaînée relancée
repart de 0. Plus une marche aléatoire semée qui vérifie ces invariants à chaque pas.
Contrat : `docs/presentation-studio.md` > *Presentation experience contract* § 5 et *Remotion timeline bridge › What the score asks for*.
"""

from __future__ import annotations

import random

from jarvis.domain.presentation_studio_scene import ScoreAnchor
from jarvis.domain.remotion_timeline import Arrival, Move, Placement, Segment, build_frame_map, place, target_segment

COMP = {"id": "Scene", "fps": 30, "duration_in_frames": 300}
#: S2 of the gate deck: 10 s @ 30 fps, anchors at 2 s (frame 60) and 6 s (frame 180).
TIMED = (ScoreAnchor("a", "A", None, 2000), ScoreAnchor("b", "B", None, 6000))


def fmap(scene_id="s2", anchors=TIMED, **comp):
    return build_frame_map(scene_id, {**COMP, **comp}, anchors)


def test_a_newly_entered_scene_plays_from_its_local_frame_zero_even_when_the_entering_item_reveals_a_later_anchor():
    m = fmap()
    entered = place(m, {"a"}, Move.FORWARD, None)
    assert entered.arrival is Arrival.ENTER and entered.segment == Segment("a", 0, 179)   # never from frame 60: the entry is played
    assert place(m, {"a", "b"}, Move.FORWARD, None).segment == Segment("b", 0, 299)
    assert place(m, set(), Move.FORWARD, None).segment == Segment(None, 0, 59)             # nothing revealed: the entry segment
    other = place(fmap("s1"), set(), Move.FORWARD, None)
    assert place(m, {"a"}, Move.FORWARD, other).segment == Segment("a", 0, 179), "another scene before it: still an entry"


def test_the_score_going_on_in_the_same_scene_plays_the_new_anchors_segment_from_where_the_player_stopped():
    m = fmap()
    entered = place(m, {"a"}, Move.FORWARD, None)
    moved = place(m, {"a", "b"}, Move.FORWARD, entered)
    assert moved.arrival is Arrival.PLAY and moved.segment == Segment("b", 180, 299)
    assert entered.segment.until + 1 == moved.segment.start, "continuous: no frame skipped, none replayed"
    same = place(m, {"a"}, Move.FORWARD, entered)
    assert same == entered, "an item that reveals nothing new keeps the segment (and so the browser's `seq`)"
    assert place(m, {"a", "b"}, Move.STEP, entered).segment == Segment("b", 180, 299), "an entry that finished: the step plays its segment"


def test_a_locked_sequence_step_never_cuts_an_entry_that_still_plays_it_continues_to_the_new_stop_frame():
    """Slice 07 rework, I2: step 0 is released when the voice starts, 600 ms after the entry began (frame 18 at 30 fps)."""

    m = fmap()
    entry = place(m, set(), Move.FORWARD, None)
    assert entry.segment == Segment(None, 0, 59)
    at_once = place(m, {"a", "b"}, Move.STEP, entry, entering=0)
    assert at_once.arrival is Arrival.ENTER and at_once.segment == Segment("b", 0, 299), "before the Player began: from frame 0"
    latency = place(m, {"a", "b"}, Move.STEP, entry, entering=18)
    assert latency.arrival is Arrival.ENTER and latency.segment == Segment("b", 18, 299), \
        "600 ms of voice latency: the entry goes on from frame 18 to the new stop frame, never cut to the anchor (180)"
    assert place(m, {"a", "b"}, Move.NONE, latency) == latency, "idempotent: the extended entry keeps its frame (same `seq`)"
    assert place(m, {"a", "b"}, Move.STEP, entry, entering=900).segment == Segment("b", 299, 299), "bounded by the new stop frame"
    assert place(m, {"a", "b"}, Move.FORWARD, entry, entering=18).segment == Segment("b", 180, 299), \
        "an explicit move (next, a cue, the end of the presenter's line) goes where it is asked"
    assert place(m, {"a", "b"}, Move.STEP, entry).segment == Segment("b", 180, 299), "the entry finished: the step's own segment"
    later = place(m, {"a", "b"}, Move.STEP, place(m, {"a"}, Move.JUMP, None), entering=0)
    assert later.segment == Segment("b", 180, 299), "only an entry is extended, never a hold"


def test_going_back_or_jumping_holds_the_target_items_stop_frame_without_replaying_earlier_segments():
    m = fmap()
    at_b = place(m, {"a", "b"}, Move.FORWARD, place(m, {"a"}, Move.FORWARD, None))
    back = place(m, {"a"}, Move.JUMP, at_b)
    assert back.arrival is Arrival.HOLD and back.segment == Segment("a", 179, 179)
    jumped_in = place(m, {"a", "b"}, Move.JUMP, place(fmap("s1"), set(), Move.FORWARD, None))
    assert jumped_in.arrival is Arrival.HOLD and jumped_in.segment == Segment("b", 299, 299)
    assert place(m, {"a"}, Move.JUMP, None).segment == Segment("a", 179, 179)
    on = place(m, {"a", "b"}, Move.FORWARD, back)
    assert on.segment == Segment("b", 180, 299), "after a hold, the next item plays its own segment"
    earlier = place(m, {"a"}, Move.FORWARD, at_b)      # a score whose next item hides the later anchor: never a replay from an anchor
    assert earlier.arrival is Arrival.HOLD and earlier.segment == Segment("a", 179, 179)


def test_a_pause_a_resume_or_any_non_move_keeps_the_placement_exactly():
    m = fmap()
    for previous in (place(m, {"a"}, Move.FORWARD, None), place(m, {"a"}, Move.JUMP, None)):
        assert place(m, {"a"}, Move.NONE, previous) == previous
    entered = place(m, {"a"}, Move.FORWARD, None)
    reloaded = place(fmap(fps=60, duration_in_frames=1200), {"a"}, Move.NONE, entered)   # hot reload: frames of the new version
    assert reloaded.arrival is Arrival.ENTER and reloaded.segment == Segment("a", 0, 359)


def test_a_restarted_chained_play_starts_the_scene_at_zero_and_a_jump_inside_it_plays_the_target():
    m = fmap()
    at_b = place(m, {"a", "b"}, Move.JUMP, None)
    assert place(m, {"a"}, Move.RESTART, at_b).segment == Segment("a", 0, 179)
    assert place(m, {"a"}, Move.SEEK, at_b).segment == Segment("a", 60, 179)
    assert place(m, {"a", "b"}, Move.SEEK, None).segment == Segment("b", 180, 299), "Slice 05 behaviour for a chained-play jump"


def test_a_scene_without_anchors_in_a_run_that_waits_for_its_media_is_one_segment_from_zero():
    whole = build_frame_map("s3", COMP, (), whole_scene=True)
    assert place(whole, set(), Move.FORWARD, None).segment == Segment(None, 0, 299)
    assert place(whole, set(), Move.JUMP, None).segment == Segment(None, 299, 299)


def test_a_random_walk_keeps_every_placement_inside_the_rules():
    moves = list(Move)
    for seed in range(40):
        rng = random.Random(seed)
        duration = rng.randint(1, 900)
        anchors = tuple(ScoreAnchor(f"x{i}", "X", None, rng.choice([None, rng.randint(0, 40_000)])) for i in range(rng.randint(1, 5)))
        maps = {"s1": build_frame_map("s1", {**COMP, "duration_in_frames": duration}, anchors),
                "s2": build_frame_map("s2", {**COMP, "duration_in_frames": duration}, anchors)}
        previous: Placement | None = None
        for _ in range(150):
            m = maps[rng.choice(["s1", "s2"])]
            revealed = {a.anchor_id for a in anchors if rng.random() < 0.4}
            move = rng.choice(moves)
            got = place(m, revealed, move, previous, entering=rng.choice([None, rng.randint(0, duration + 5)]))
            target, segment = target_segment(m, revealed), got.segment
            assert got.target == target and got.scene_id == m.scene_id
            assert 0 <= segment.start <= segment.until <= duration - 1
            assert segment.until == target.until, "anchors bound the stop frame, whatever the arrival"
            assert segment.anchor_id == target.anchor_id
            entered = previous is None or previous.scene_id != m.scene_id
            if entered and move in (Move.FORWARD, Move.STEP, Move.NONE, Move.RESTART):
                assert segment.start == 0, (seed, "a newly entered scene starts on its local frame 0")
            if move is Move.RESTART:
                assert segment.start == 0
            if got.arrival is Arrival.HOLD:
                assert segment.start == segment.until, "a hold plays nothing"
            if move is Move.NONE and not entered:
                assert got.arrival is previous.arrival
            assert place(m, revealed, Move.NONE, got) == got, "idempotent: reading the view again changes nothing"
            previous = got
