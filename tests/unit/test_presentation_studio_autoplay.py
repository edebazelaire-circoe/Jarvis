"""Lecture enchaînée (portée `scene` / `all`) dans le service de lecture de Core (handoff jarvis-remotion-presentation-integration, Slice 23).

Banc réel de la Slice 12 (scène, catalogue, service d'édition, fichiers) avec la source de composition factice de la Slice 12 Remotion ;
l'horloge de Core est la fausse horloge du banc (`rig.mono`), les échéances sont de vraies minuteries de la boucle d'événements (petites).
Prouvé : la portée se règle au `start` et par `play`, la ligne de temps dit `auto` et la source (`prefab`) de sa scène ; Core avance seul à
l'échéance quand aucune page ne dit rien, et tient la dernière image à la fin ; un rapport `done` de la page avance tout de suite, un rapport périmé
ou venu trop tôt ne change rien ; la pause arrête tout et la reprise recalcule sur le temps joué ; `scene` s'arrête à la fin de la scène ;
une lecture où Jarvis dit les lignes n'a pas de portée ; la scène suivante est annoncée (`next_scene`) et lisible (`preload_hint`).
Contrat : `docs/presentation-studio.md` > *Remotion timeline bridge* > *Chained playback*.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.core.presentation_studio_autoplay import AutoTimings
from jarvis.core.presentation_studio_playback import PlaybackStatus
from jarvis.domain.presentation_studio_playback_requests import Scope, parse_advance, parse_play, parse_start
from jarvis.adapters.file_prefab_library import LIBRARY_DIR
from tests.fakes.prefabs import install_version
from tests.unit.test_presentation_studio_playback_service import Rig, applied, S1, S2, S3
from tests.unit.test_presentation_studio_score_service import scene_body
from tests.unit.test_remotion_timeline_service import Compositions

SLOW = {"id": "Scene", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": 300}      # S2 'marker' segment: frames 150..299 = 5 s
FAST = {"id": "Scene", "width": 1280, "height": 720, "fps": 120, "duration_in_frames": 24}      # the same segment: frames 12..23 = 100 ms
QUICK = AutoTimings(min_dwell_ms=20, default_dwell_ms=30, grace_ms=30, load_allowance_ms=0)
#: Never fires during a test: the reports are the only thing that moves the run.
QUIET = AutoTimings(min_dwell_ms=600_000, default_dwell_ms=600_000, grace_ms=600_000, load_allowance_ms=600_000)


async def open_rig(tmp_path, composition, timings):
    rig = await Rig(tmp_path).open()
    rig.build(timeline_source=Compositions(composition), autoplay=timings)
    return rig


async def until(predicate, seconds=6.0):
    end = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < end:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


def at(rig) -> int:
    return rig.service.where()["position"]["index"]


async def finish(rig):
    if rig.service.state.active:
        await rig.service.stop({"actor": "user"})
    await rig.close()


# ------------------------------------------------------------------ requests

def test_the_scope_is_a_closed_word_on_start_play_and_the_segment_report_is_exact():
    base = {"actor": "user", "presentation_id": "pst_" + "0" * 32, "role": "user_presenter"}
    assert parse_start(base).scope is Scope.MANUAL and parse_start({**base, "scope": "all"}).scope is Scope.ALL
    for bad in ("everything", "", None, 3, ["all"]):
        with pytest.raises(ValueError, match="scope must be one of"):
            parse_start({**base, "scope": bad})
    assert parse_play({"actor": "user", "scope": "scene"})[1] is Scope.SCENE
    for body in ({"actor": "user"}, {"actor": "user", "scope": "scene", "x": 1}, {"scope": "scene"}):
        with pytest.raises(ValueError):
            parse_play(body)
    assert parse_advance({"actor": "user", "seq": 3, "event": "done"})[1:] == (3, "done")
    for body in ({"actor": "user", "seq": -1, "event": "done"}, {"actor": "user", "seq": 1.5, "event": "done"},
                 {"actor": "user", "seq": True, "event": "done"}, {"actor": "user", "seq": 1, "event": "next"},
                 {"actor": "user", "seq": 1, "event": "done", "frame": 4}, {"actor": "user", "event": "done"}):
        with pytest.raises(ValueError):
            parse_advance(body)


# ------------------------------------------------------------------ the view

async def test_a_chained_start_says_its_scope_the_source_of_the_scene_and_the_scene_to_come(tmp_path):
    rig = await open_rig(tmp_path, SLOW, QUIET)
    try:
        manual = applied(await rig.service.start(rig.start_body()))
        assert manual["scope"] == "manual" and manual["timeline"]["auto"] is False
        await rig.service.stop({"actor": "user"})
        state = applied(await rig.service.start(rig.start_body(scope="all")))
        assert state["scope"] == "all"
        timeline = state["timeline"]
        assert timeline["auto"] is True and timeline["prefab"] == "lab.counter@1"
        # item 1 shows S1, the next element shows S2 (the same source here: nothing to load beside) ...
        assert "next_scene" not in state and rig.service.preload_hint() is None
    finally:
        await finish(rig)


async def test_the_scene_to_come_is_named_and_readable_only_when_it_is_another_source(tmp_path):
    rig = Rig(tmp_path)
    install_version(rig.env.data / LIBRARY_DIR, "lab.counter", 2)                  # a second version: another source for scene S2
    await rig.open(scenes=[scene_body(S1), {**scene_body(S2), "prefab": {"id": "lab.counter", "version": 2}, "props": {"label": "Deux"}},
                           scene_body(S3)])
    try:
        rig.build(timeline_source=Compositions(SLOW), autoplay=QUIET)
        applied(await rig.service.start(rig.start_body()))
        # item 1 (S1), the next element shows S2 at version 2: the scene to come is announced one element ahead
        moved = rig.service.where()
        assert moved["position"]["index"] == 1
        hint = rig.service.preload_hint()
        assert hint is not None and hint["scene_id"] == S2 and hint["prefab"]["id"] == "lab.counter" and hint["prefab"]["version"] == 2
        assert hint["prefab"]["props"] == {"label": "Deux"} and set(hint) == {"scene_id", "title", "prefab"}
        assert moved["next_scene"] == {"scene_id": S2, "prefab": "lab.counter@2", "rev": moved["next_scene"]["rev"]}
        applied(await rig.run("next"))                                              # on S2: the next element is S2 again
        assert rig.service.preload_hint() is None and "next_scene" not in rig.service.where()
        applied(await rig.run("next"))
        hint = rig.service.preload_hint()
        assert hint is not None and hint["scene_id"] == S3 and hint["prefab"]["version"] == 1
    finally:
        await finish(rig)


# ------------------------------------------------------------------ Core's own deadline (no page)

async def test_with_no_page_at_all_core_goes_on_by_itself_through_every_element_and_holds_the_last_image(tmp_path):
    rig = await open_rig(tmp_path, FAST, QUICK)
    try:
        applied(await rig.service.start(rig.start_body(scope="all")))
        assert await until(lambda: rig.service.where()["scope"] == "manual"), rig.service.where()
        where = rig.service.where()
        assert where["position"]["index"] == 4 and where["phase"] == "playing" and where["scene"]["title"] == "Trois"
        assert where["timeline"]["auto"] is False, "the chain is over: the last image is held, nothing moves any more"
        await asyncio.sleep(0.2)
        assert at(rig) == 4 and rig.service.where()["phase"] == "playing"
        kinds = rig.env.sink.kinds() if hasattr(rig.env.sink, "kinds") else []
        assert not kinds or "core.presentation_studio.autoplay_finished" in kinds
    finally:
        await finish(rig)


async def test_play_scene_goes_through_the_elements_of_the_scene_then_holds_without_leaving_it(tmp_path):
    rig = await open_rig(tmp_path, FAST, QUICK)
    try:
        applied(await rig.service.start(rig.start_body()))
        applied(await rig.run("next"))                                            # item 2, scene S2
        assert at(rig) == 2
        played = applied(await rig.service.play({"actor": "user", "scope": "scene"}))
        assert played["scope"] == "scene" and played["scene"]["title"] == "Deux" and at(rig) == 2
        assert await until(lambda: rig.service.where()["scope"] == "manual"), rig.service.where()
        where = rig.service.where()
        assert where["position"]["index"] == 3 and where["scene"]["title"] == "Deux", "S2 has two elements: it ends on the second, never on S3"
        await asyncio.sleep(0.2)
        assert at(rig) == 3
    finally:
        await finish(rig)


async def test_play_all_restarts_the_current_scene_from_its_first_element_and_goes_on_from_there(tmp_path):
    rig = await open_rig(tmp_path, FAST, QUICK)
    try:
        applied(await rig.service.start(rig.start_body()))
        applied(await rig.run("next"))
        applied(await rig.run("next"))                                            # item 3: the second element of S2
        started = applied(await rig.service.play({"actor": "user", "scope": "all"}))
        assert at(rig) == 2 and started["scope"] == "all", "back to the first element of the scene being played"
        assert await until(lambda: rig.service.where()["scope"] == "manual")
        assert at(rig) == 4
    finally:
        await finish(rig)


# ------------------------------------------------------------------ the page's reports

async def test_a_done_report_goes_on_at_once_but_only_for_the_segment_core_is_in_and_only_once_it_could_be_true(tmp_path):
    rig = await open_rig(tmp_path, SLOW, QUIET)
    try:
        applied(await rig.service.start(rig.start_body(scope="all")))
        applied(await rig.run("goto", position=2))                                  # S2 'marker': frames 150..299, 5 s
        seq = rig.service.where()["timeline"]["seq"]
        before = at(rig)
        stale = applied(await rig.service.advance({"actor": "user", "seq": seq - 1, "event": "done"}))
        assert at(rig) == before and stale["timeline"]["seq"] == seq, "another segment's report changes nothing"
        early = applied(await rig.service.advance({"actor": "user", "seq": seq, "event": "done"}))
        assert at(rig) == before and early["position"]["index"] == before, "5 s of a segment cannot have been played in no time"
        applied(await rig.service.advance({"actor": "user", "seq": seq, "event": "started"}))
        rig.mono.t += 5
        moved = applied(await rig.service.advance({"actor": "user", "seq": seq, "event": "done"}))
        assert moved["position"]["index"] == before + 1, "a true done goes on, and the answer carries the new state"
        again = applied(await rig.service.advance({"actor": "user", "seq": seq, "event": "done"}))
        assert again["position"]["index"] == before + 1, "a duplicate report does not skip a second element"
    finally:
        await finish(rig)


async def test_a_started_report_restarts_the_played_time_of_the_segment_at_the_moment_the_scene_was_really_playing(tmp_path):
    rig = await open_rig(tmp_path, SLOW, QUIET)
    try:
        applied(await rig.service.start(rig.start_body(scope="all")))
        applied(await rig.run("goto", position=2))
        seq = rig.service.where()["timeline"]["seq"]
        rig.mono.t += 40                                                            # the scene took 40 s to compile and load
        assert rig.service.where()["timeline"]["play_ms"] == 5000, "capped at the segment: Core's clock alone says it is over"
        applied(await rig.service.advance({"actor": "user", "seq": seq, "event": "started"}))
        assert rig.service.where()["timeline"]["play_ms"] == 0 and rig.service.where()["timeline"]["seq"] == seq
        applied(await rig.service.advance({"actor": "user", "seq": seq, "event": "done"}))
        assert at(rig) == 2, "the load time was not played time: this done is premature"
    finally:
        await finish(rig)


async def test_a_report_in_a_manual_run_or_with_nothing_running_changes_nothing(tmp_path):
    rig = await open_rig(tmp_path, SLOW, QUIET)
    try:
        idle = await rig.service.advance({"actor": "user", "seq": 1, "event": "done"})
        assert idle.status is PlaybackStatus.REFUSED and idle.reason == "not_running"
        applied(await rig.service.start(rig.start_body()))
        applied(await rig.run("goto", position=2))
        seq = rig.service.where()["timeline"]["seq"]
        rig.mono.t += 6
        applied(await rig.service.advance({"actor": "user", "seq": seq, "event": "done"}))
        assert at(rig) == 2, "a manual run advances by the presenter only"
    finally:
        await finish(rig)


# ------------------------------------------------------------------ pause, edge cases

async def test_a_pause_stops_the_deadline_and_the_resume_recomputes_it_on_the_time_played(tmp_path):
    rig = await open_rig(tmp_path, FAST, QUICK)
    try:
        applied(await rig.service.start(rig.start_body()))
        applied(await rig.run("goto", position=2))
        applied(await rig.service.play({"actor": "user", "scope": "all"}))
        applied(await rig.run("pause"))
        assert at(rig) == 2 and rig.service.where()["phase"] == "paused"
        await asyncio.sleep(0.6)
        assert at(rig) == 2, "nothing advances while paused"
        applied(await rig.run("resume"))
        assert await until(lambda: at(rig) == 4), rig.service.where()
    finally:
        await finish(rig)


async def test_playing_while_paused_resumes_first_and_a_detour_or_jarvis_speaking_refuses(tmp_path):
    rig = await open_rig(tmp_path, SLOW, QUIET)
    try:
        applied(await rig.service.start(rig.start_body()))
        applied(await rig.run("pause"))
        state = applied(await rig.service.play({"actor": "user", "scope": "scene"}))
        assert state["phase"] == "playing" and state["scope"] == "scene"
        handed = applied(await rig.service.play({"actor": "user", "scope": "manual"}))
        assert handed["scope"] == "manual" and "auto" in handed["timeline"] and handed["timeline"]["auto"] is False
        await rig.service.stop({"actor": "user"})
        refused = await rig.service.start(rig.start_body(role="jarvis_presenter", scope="all"))
        assert refused.status is PlaybackStatus.REFUSED and refused.reason == "illegal_transition"
        speaks = await rig.service.start(rig.start_body(role="rehearsal", jarvis_speaks=True, scope="scene"))
        assert speaks.status is PlaybackStatus.REFUSED
        idle = await rig.service.play({"actor": "user", "scope": "all"})
        assert idle.status is PlaybackStatus.REFUSED and idle.reason == "not_running"
    finally:
        await finish(rig)


async def test_a_user_move_while_chained_re_arms_without_a_double_advance_and_stop_leaves_no_timer(tmp_path):
    rig = await open_rig(tmp_path, FAST, QUICK)
    try:
        applied(await rig.service.start(rig.start_body(scope="all")))
        applied(await rig.run("next"))
        applied(await rig.run("next"))
        position = at(rig)
        assert position == 3
        assert await until(lambda: rig.service.where()["scope"] == "manual")
        assert at(rig) == 4, "one step per element, never two for a click that came in the middle"
        await rig.service.stop({"actor": "user"})
        assert rig.service._auto_handle is None and rig.service.scope is Scope.MANUAL
    finally:
        await rig.close()


async def test_a_run_without_a_timeline_source_dwells_on_each_element_by_its_target(tmp_path):
    rig = await Rig(tmp_path).open()
    try:
        rig.build(autoplay=QUICK)
        applied(await rig.service.start(rig.start_body(scope="all")))
        assert "timeline" not in rig.service.where()
        assert await until(lambda: rig.service.where()["scope"] == "manual")
        assert at(rig) == 4
    finally:
        await finish(rig)
