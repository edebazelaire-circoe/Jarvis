"""Horloge de composition (handoff jarvis-remotion-native-studio-playback-fix, Slice 04), la carte pure de
`jarvis/domain/composition_clock.py`.

Prouvé : base de temps au fps maître (le plus grand), durées irrégulières et cadences mêlées 24/25/30/60, bornes `start-1/start/end`,
recouvrement (la scène entrante gagne), navigation précédent/suivant/vignette/glissière, pause conservée exactement, fin tenue sans
bouclage, deck d'une scène, deck vide et manifestes invalides refusés avec un code (jamais une valeur par défaut).
Contrat : `docs/presentation-studio.md` > *Composition clock (Level 3)*.
"""

from __future__ import annotations

import pytest

from jarvis.domain.composition_clock import (
    EMPTY, FRAME_OUT_OF_RANGE, SCENE_INVALID, SCENE_OUT_OF_RANGE, TRANSITION_INVALID, CompositionError, SceneManifest, Seek,
    Transport, build_composition, composition_key, pause, play, scene_manifest, seek, tick, to_wire,
)
from jarvis.domain.remotion_timeline import build_frame_map

#: The Slice 03 fixture: 9 scenes of 3 s, 8 s and 30 s at 24, 25, 30 and 60 fps.
DECK = [("s1", 24, 72), ("s2", 25, 200), ("s3", 30, 900), ("s4", 60, 180), ("s5", 24, 192), ("s6", 25, 750),
        ("s7", 30, 90), ("s8", 60, 480), ("s9", 24, 720)]


def manifests(rows):
    return [SceneManifest(scene_id, "Scene", fps, frames) for scene_id, fps, frames in rows]


@pytest.fixture
def deck():
    return build_composition(manifests(DECK))


def test_the_master_fps_is_the_highest_scene_fps_and_each_scene_keeps_its_authored_seconds(deck):
    assert deck.fps == 60
    assert [s.length for s in deck.scenes] == [180, 480, 1800, 180, 480, 1800, 180, 480, 1800]
    assert [s.start for s in deck.scenes] == [0, 180, 660, 2460, 2640, 3120, 4920, 5100, 5580]
    assert deck.total_frames == 7380 and deck.last_frame == 7379        # 123 s at 60 fps = 3+8+30 three times


def test_a_non_divisible_length_rounds_up_by_less_than_one_master_frame():
    cmap = build_composition(manifests([("a", 25, 199), ("b", 60, 10)]))
    assert cmap.scenes[0].length == 478                                  # 199 * 60 / 25 = 477.6 -> 478
    assert cmap.scenes[1].start == 478


def test_every_native_frame_round_trips_through_the_composition_frame(deck):
    for span in deck.scenes:
        for native in range(span.duration_in_frames):
            f = deck.frame_of(span.index, native)
            here = deck.locate(f)
            assert (here.scene_index, here.native_frame) == (span.index, native)
        # every master frame shows a native frame of its own scene, in order, never past the last one
        shown = [deck.locate(f).native_frame for f in range(span.start, span.end)]
        assert shown == sorted(shown) and shown[0] == 0 and shown[-1] == span.duration_in_frames - 1
        assert set(shown) == set(range(span.duration_in_frames))         # each local frame 0..len-1 is shown


def test_boundaries_start_minus_one_start_and_end(deck):
    s3 = deck.scenes[2]
    before, at, last = deck.locate(s3.start - 1), deck.locate(s3.start), deck.locate(s3.end - 1)
    assert (before.scene_id, before.native_frame) == ("s2", 199)
    assert (at.scene_id, at.local_frame, at.native_frame, at.local_progress) == ("s3", 0, 0, 0.0)
    assert (last.scene_id, last.native_frame) == ("s3", 899)
    assert deck.locate(s3.end).scene_id == "s4" and deck.locate(s3.end).native_frame == 0
    assert deck.locate(deck.last_frame).native_frame == 719
    with pytest.raises(CompositionError) as err:
        deck.locate(deck.total_frames)
    assert err.value.code == FRAME_OUT_OF_RANGE


def test_during_an_overlap_the_incoming_scene_is_current_from_its_local_frame_zero():
    cmap = build_composition(manifests([("a", 30, 90), ("b", 30, 90), ("c", 30, 90)]), [0, 15, 30])
    assert [(s.start, s.end) for s in cmap.scenes] == [(0, 90), (75, 165), (135, 225)]
    assert cmap.total_frames == 225
    assert cmap.locate(74).scene_id == "a"
    entering = cmap.locate(75)
    assert (entering.scene_id, entering.local_frame) == ("b", 0)          # the first frame of its entry transition is its frame 0
    assert cmap.locate(89).scene_id == "b"                                # a still plays underneath: b is current
    assert cmap.previous_start(80) == 0 and cmap.next_start(80) == 135


@pytest.mark.parametrize("transitions", [[0, 90, 0], [0, 60, 30], [5, 0, 0], [0, -1, 0], [0, 1.5, 0], [0, 0]])
def test_an_overlap_that_leaves_a_scene_no_frame_of_its_own_is_refused(transitions):
    with pytest.raises(CompositionError) as err:
        build_composition(manifests([("a", 30, 90), ("b", 30, 90), ("c", 30, 90)]), transitions)
    assert err.value.code == TRANSITION_INVALID


def test_next_previous_and_thumbnail_land_on_a_scene_start_and_keep_the_play_state(deck):
    mid_s3 = deck.start_of(2) + 400
    paused, playing = Transport(mid_s3, False), Transport(mid_s3, True)
    assert seek(deck, paused, Seek.NEXT) == Transport(deck.start_of(3), False)
    assert seek(deck, playing, Seek.NEXT) == Transport(deck.start_of(3), True)
    assert seek(deck, paused, Seek.PREVIOUS) == Transport(deck.start_of(1), False)
    assert seek(deck, Transport(30, True), Seek.PREVIOUS) == Transport(0, True)          # from scene 1: frame 0
    assert seek(deck, playing, Seek.SCENE, 2) == Transport(deck.start_of(2), True)        # thumbnail: restart this scene
    last = Transport(deck.start_of(8) + 5, True)
    assert seek(deck, last, Seek.NEXT) is last                                            # next is disabled on the last scene
    assert deck.next_start(deck.start_of(8)) is None
    with pytest.raises(CompositionError) as err:
        seek(deck, paused, Seek.SCENE, 9)
    assert err.value.code == SCENE_OUT_OF_RANGE


def test_scrub_lands_on_the_exact_frame_and_pause_holds_it_exactly(deck):
    scrubbed = seek(deck, Transport(0, True), Seek.SCRUB, 4321)
    assert scrubbed == Transport(4321, True)
    held = pause(deck, scrubbed)
    assert held == Transport(4321, False)
    assert play(deck, held) == Transport(4321, True)                                      # resume continues from f
    with pytest.raises(CompositionError):
        seek(deck, held, Seek.SCRUB, -1)
    assert seek(deck, held, Seek.STEP, 1) == Transport(4322, False)
    assert seek(deck, Transport(4321, True), Seek.STEP, 1) == Transport(4321, True)       # steps only while paused
    assert seek(deck, Transport(0, False), Seek.STEP, -1) == Transport(0, False)


def test_the_end_holds_the_final_frame_never_wraps_and_only_replay_restarts(deck):
    end = seek(deck, Transport(100, True), Seek.END)
    assert end == Transport(deck.last_frame, False, True)
    assert play(deck, end) is end                                                         # never loops by itself
    assert seek(deck, end, Seek.REPLAY) == Transport(0, True)
    assert seek(deck, end, Seek.HOME) == Transport(0, False)                              # Home keeps the play state
    assert seek(deck, Transport(5, False), Seek.END) == Transport(deck.last_frame, False)  # paused End: shown, not « Terminé »


def test_a_player_tick_maps_to_f_and_a_scene_end_hands_over_to_the_next_scene_frame_zero(deck):
    state = Transport(deck.start_of(1), True)
    assert tick(deck, state, 1, 100) == Transport(deck.start_of(1) + 240, True)           # 25 fps frame 100 = 4 s = master 240
    assert tick(deck, state, 1, 199, scene_ended=True) == Transport(deck.start_of(2), True)
    assert tick(deck, Transport(7000, False), 8, 300) == Transport(deck.frame_of(8, 300), False)   # a tick never resumes
    assert tick(deck, state, 8, 719, scene_ended=True) == Transport(deck.last_frame, False, True)
    with pytest.raises(CompositionError) as err:
        tick(deck, state, 1, 200)
    assert err.value.code == FRAME_OUT_OF_RANGE


def test_a_one_scene_deck_is_its_own_composition():
    one = build_composition(manifests([("only", 30, 90)]))
    assert (one.fps, one.total_frames, one.next_start(10), one.previous_start(10)) == (30, 90, None, 0)
    assert tick(one, Transport(0, True), 0, 89, scene_ended=True) == Transport(89, False, True)


def test_an_empty_deck_and_invalid_manifests_are_refused_with_a_code():
    with pytest.raises(CompositionError) as err:
        build_composition([])
    assert err.value.code == EMPTY
    for bad in ({"id": "S", "fps": 0, "duration_in_frames": 10}, {"id": "S", "fps": 30, "duration_in_frames": 0},
                {"id": "S", "fps": 121, "duration_in_frames": 10}, {"id": "", "fps": 30, "duration_in_frames": 10},
                {"id": "S", "fps": 29.97, "duration_in_frames": 10}, {"id": "S", "fps": True, "duration_in_frames": 10},
                {"id": "S", "fps": 30}):
        with pytest.raises(CompositionError) as err:
            scene_manifest("s1", bad)
        assert (err.value.code, err.value.scene_id) == (SCENE_INVALID, "s1")
    with pytest.raises(CompositionError) as err:
        build_composition(manifests([("a", 30, 90), ("a", 30, 90)]))
    assert err.value.code == SCENE_INVALID


def test_the_key_is_bound_to_presentation_variant_and_pins():
    pins = [("s1", "presentation-studio.p1.s1", 1), ("s2", "presentation-studio.p1.s2", 3)]
    key = composition_key("p1", "v1", pins)
    assert key.startswith("cmp_") and key == composition_key("p1", "v1", list(pins))
    assert key != composition_key("p1", "v2", pins)
    assert key != composition_key("p1", "v1", [pins[0], ("s2", "presentation-studio.p1.s2", 4)])
    assert key != composition_key("p1", "v1", list(reversed(pins)))
    wire = to_wire(build_composition(manifests([("a", 30, 90)])), key=key)
    assert wire == {"version": 1, "key": key, "fps": 30, "total_frames": 90,
                    "scenes": [{"scene_id": "a", "composition_id": "Scene", "fps": 30, "duration_in_frames": 90, "start": 0,
                                "length": 90, "transition_in": 0}]}


def test_the_anchor_map_and_the_composition_clock_share_one_bounds_check():
    with pytest.raises(Exception) as anchor_err:
        build_frame_map("s1", {"id": "S", "fps": 0, "duration_in_frames": 10}, [], whole_scene=True)
    with pytest.raises(CompositionError) as clock_err:
        scene_manifest("s1", {"id": "S", "fps": 0, "duration_in_frames": 10})
    assert str(anchor_err.value) in str(clock_err.value)
