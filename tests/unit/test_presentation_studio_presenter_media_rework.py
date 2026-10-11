"""Partition, voix et média : reprise de la Slice 07 (handoff jarvis-remotion-native-studio-playback-fix, QA B1, I1, I2, I3).

Même banc que `test_presentation_studio_presenter_media.py` (vrai service de lecture, vrai présentateur, horloge et parole fausses, source de
composition fausse), plus :
- B1 : une scène dont `show` CÈDE vraiment la main (`await asyncio.sleep(0)`) et la vraie boucle du présentateur (`run_loop=True`). Le
  présentateur est réveillé au commit, AVANT la synchronisation du cadre : il doit l'être encore après, et la question « cette scène est-elle
  une vidéo ? » doit porter sur la scène courante, jamais sur la précédente. Un silence sur une scène HTML finit alors sur sa cible, au départ
  comme après un `next` de l'utilisateur ;
- I1 : une scène Remotion dont la ligne de temps n'a pas pu être lue est tenue pendant un silence de Jarvis (jamais coupée), mais jamais en
  silence : la vue le dit (`page_wait`, `reason: timeline_unresolved`) après la cible + la marge ;
- I2 : une latence de voix réaliste (600 ms) entre l'entrée de la scène et le pas 0 d'une séquence verrouillée ne coupe pas l'entrée ;
- I3 : les mutants M3 (`resume` -> RESTART), M7 (un `done` périmé accepté), M11 (`previous` -> FORWARD) sont tués.
Contrat : `docs/presentation-studio.md` > *Presentation experience contract* § 5 ; *Playback runtime contract* › *Failure modes*.
"""

from __future__ import annotations

import asyncio
import time

from jarvis.core.presentation_studio_autoplay import PAGE_SILENCE_MARGIN_MS
from jarvis.core.presentation_studio_playback import _MOVE_OF, _move_of
from jarvis.domain.remotion_timeline import Move
from tests.fakes.presentation_studio_presenter import advance, locked_content, make_presenter, set_ms
from tests.unit.test_presentation_studio_playback_service import I1, I2, I3, Rig, S1, S2, S3, applied
from tests.unit.test_presentation_studio_presenter_media import deck, jarvis_content, kinds, open_rig, page, segment, speak_line, where
from tests.unit.test_remotion_timeline_service import COMP, Compositions


def silences_content() -> dict:
    """Three explicit silences, 1 s target each, one per scene (S1, S2, S3)."""

    items = [{"item_id": item, "scene_id": scene, "presenter": "none", "kind": "silence", "target_duration_ms": 1000}
             for item, scene in ((I1, S1), (I2, S2), (I3, S3))]
    items[0]["next_item_id"], items[1]["next_item_id"] = I2, I3
    return {"start_item_id": I1, "items": items, "cues": [], "sequences": [], "recovery_points": []}


def yielding_stage(rig, turns: int = 6) -> None:
    """The stage's `show` really yields (a real scene service awaits its store and its windows): the presenter loop runs in the middle."""

    real = rig.stage.show

    async def show(payload):
        for _ in range(turns):
            await asyncio.sleep(0)
        return await real(payload)

    rig.stage.show = show


def record_waits(presenter) -> list:
    """Every timeout the presenter loop chose for its wait (`None`: it sleeps until something wakes it)."""

    seen: list = []
    read = presenter.next_wake_s

    def next_wake_s():
        seen.append(read())
        return seen[-1]

    presenter.next_wake_s = next_wake_s
    return seen


async def settle() -> None:
    for _ in range(40):
        await asyncio.sleep(0)


async def until_position(rig, index: int, *, within_s: float = 3.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        if where(rig)["position"]["index"] == index or where(rig)["phase"] == "stopped":
            return True
        await asyncio.sleep(0.02)
    return False


async def html_rig(tmp_path):
    rig = await Rig(tmp_path).open(scenes=deck(), content=silences_content())
    rig.build(timeline_source=Compositions(None))   # a real timeline source (production wires one), answering "HTML" for this pin
    set_ms(rig, 1_000_000)
    yielding_stage(rig)
    return rig


# ------------------------------------------------------------------ B1: a silence over an HTML scene ends on its target

async def test_b1_an_html_silence_at_the_start_of_a_jarvis_run_ends_on_its_target_when_the_stage_yields(tmp_path):
    rig = await html_rig(tmp_path)
    presenter, _brain, _voice = make_presenter(rig, run_loop=True)
    waits = record_waits(presenter)
    try:
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        await settle()
        assert rig.service.media_segment() is None, "the scene on the stage is known to be HTML: a soft pace applies"
        assert waits and waits[-1] is not None and 0 < waits[-1] <= 1.0, \
            f"the loop must wait for the 1 s target, never sleep until a wake-up that never comes: {waits}"
        advance(rig, 1000)
        assert await until_position(rig, 2), "the HTML silence ended on its target"
    finally:
        await presenter.close()
        await rig.close()


async def test_b1_a_user_next_onto_an_html_silence_ends_it_on_its_target_when_the_stage_yields(tmp_path):
    rig = await html_rig(tmp_path)
    presenter, _brain, _voice = make_presenter(rig, run_loop=True)
    waits = record_waits(presenter)
    try:
        applied(await rig.service.start(rig.start_body("rehearsal", jarvis_speaks=True)))
        await settle()
        rig.service._compositions.clear()   # the next scene's kind is not known before its own sync (a first visit of that pin)
        applied(await rig.run("next"))
        await settle()
        assert where(rig)["position"]["index"] == 2 and rig.service.media_segment() is None
        assert waits[-1] is not None and 0 < waits[-1] <= 1.0, f"woken after the stage sync, the loop waits for the target: {waits}"
        assert kinds(rig, "timeline_resolved") == [], "an HTML scene gets no timeline"
        advance(rig, 1000)
        assert await until_position(rig, 3), "the HTML silence the user moved to ended on its target"
    finally:
        await presenter.close()
        await rig.close()


async def test_b1_while_the_stage_syncs_the_kind_of_the_new_scene_is_pending_never_the_previous_scenes(tmp_path):
    rig = await html_rig(tmp_path)
    presenter, _brain, _voice = make_presenter(rig)
    try:
        seen: list = []
        real = rig.stage.show

        async def show(payload):
            seen.append(rig.service.media_segment())
            return await real(payload)

        rig.stage.show = show
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        rig.service._compositions.clear()
        applied(await rig.run("next"))
        assert seen == ["pending", "pending"], "before its sync the scene is not known: pending (the presenter holds and is woken)"
        assert rig.service.media_segment() is None
    finally:
        await rig.close()


# ------------------------------------------------------------------ I1: an unresolved timeline is held, and said

async def test_i1_a_jarvis_silence_on_a_remotion_scene_without_timeline_is_held_and_said_after_its_target_and_a_margin(tmp_path):
    content = jarvis_content()
    content["items"][0] = {**content["items"][0], "kind": "silence", "presenter": "none", "target_duration_ms": 2000}
    content["items"][0].pop("text")
    rig = await Rig(tmp_path).open(scenes=deck(), content=content)
    rig.build(timeline_source=Compositions(RuntimeError("manifest unreadable")))
    set_ms(rig, 1_000_000)
    try:
        presenter, _brain, _voice = make_presenter(rig)
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        await presenter.pump()
        assert "timeline_unresolved" in where(rig)["notices"] and "timeline" not in where(rig)
        assert rig.service.media_segment() == "playing", "held: the motion is never cut, `target_duration_ms` never paces it"
        advance(rig, 2000 + PAGE_SILENCE_MARGIN_MS - 1)
        await presenter.pump()
        assert where(rig)["position"]["index"] == 1 and "page_wait" not in where(rig)
        advance(rig, 1)
        await presenter.pump()
        held = where(rig)
        assert held["position"]["index"] == 1, "never advanced on a guess"
        assert held["page_wait"] == {"seq": None, "started": False, "waited_ms": 17_000, "reason": "timeline_unresolved"}
        where(rig)
        assert len(kinds(rig, "timeline_unresolved_held")) == 1, "traced once per item entry"
        applied(await rig.run("pause"))
        assert "page_wait" not in where(rig), "a pause is not a hold"
        applied(await rig.run("resume"))
        applied(await rig.run("next"))                          # « Suivant » works
        assert where(rig)["position"]["index"] == 2 and "page_wait" not in where(rig)
        applied(await rig.run("stop"))                          # « Arrêter » works
        assert where(rig)["phase"] == "stopped"
    finally:
        await rig.close()


# ------------------------------------------------------------------ I2: realistic voice latency never cuts an entry

async def test_i2_a_locked_sequence_step_released_600_ms_after_the_entry_continues_the_entry_instead_of_cutting_it(tmp_path):
    rig = await open_rig(tmp_path, locked_content())
    try:
        presenter, _brain, voice = make_presenter(rig)
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        await speak_line(presenter, voice)
        await presenter.pump()                                  # I2 hosts `demo`: its intro line is handed over
        assert segment(rig) == (S2, None, 0, 59, True), "the entry: frame 0 to the frame before the first anchor"
        await page(rig, "started")                              # the Player began the entry
        advance(rig, 600)                                       # the voice starts 600 ms later: step 0 reveals `marker` (frame 180)
        voice.started()
        await presenter.pump()
        assert where(rig)["sequence"]["step"] >= 1
        assert segment(rig) == (S2, "marker", 18, 299, True), \
            "the entry goes on from the frame it reached (18) to the step's stop frame: never cut to 180"
        seq = where(rig)["timeline"]["seq"]
        advance(rig, 2500)
        await presenter.pump()                                  # step `mid` changes a value, not the segment
        assert where(rig)["timeline"]["seq"] == seq and segment(rig)[2:4] == (18, 299)
    finally:
        await rig.close()


async def test_i2_once_the_entry_said_done_the_step_plays_its_own_segment(tmp_path):
    rig = await open_rig(tmp_path, locked_content())
    try:
        presenter, _brain, voice = make_presenter(rig)
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        await speak_line(presenter, voice)
        await presenter.pump()
        await page(rig, "started", "done", played_ms=2000)     # a slow voice: the 2 s entry finished first
        voice.started()
        await presenter.pump()
        assert segment(rig) == (S2, "marker", 180, 299, True), "nothing left to protect: the anchor's segment"
    finally:
        await rig.close()


# ------------------------------------------------------------------ I3: surviving mutants

async def test_m3_a_resume_after_a_next_inside_a_scene_continues_the_same_segment_and_seq(tmp_path):
    rig = await open_rig(tmp_path, jarvis_content())
    try:
        applied(await rig.service.start(rig.start_body("user_presenter")))
        applied(await rig.run("next"))
        applied(await rig.run("next"))                          # I3 reveals `marker` in S2: the forward segment 180-299
        assert segment(rig) == (S2, "marker", 180, 299, True)
        seq = where(rig)["timeline"]["seq"]
        advance(rig, 1500)                                      # mid-way
        applied(await rig.run("pause"))
        assert segment(rig) == (S2, "marker", 180, 299, False)
        advance(rig, 20_000)
        applied(await rig.run("resume"))
        tl = where(rig)["timeline"]
        assert segment(rig) == (S2, "marker", 180, 299, True) and tl["seq"] == seq, "resume continues, never reordered from 0"
        assert tl["play_ms"] == 1500, "the played time of the segment is kept (pause excluded)"
    finally:
        await rig.close()


async def test_m7_a_done_for_an_old_segment_sent_after_the_next_one_is_on_is_ignored(tmp_path):
    rig = await open_rig(tmp_path, jarvis_content())
    try:
        presenter, _brain, voice = make_presenter(rig)
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        old = where(rig)["timeline"]["seq"]
        await page(rig, "started")                              # S1's segment began
        await speak_line(presenter, voice)                      # the line ends: I2 enters S2 (a media silence)
        assert where(rig)["position"]["index"] == 2 and where(rig)["timeline"]["seq"] != old
        applied(await rig.service.advance({"actor": "user", "seq": old, "event": "done"}))   # S1's `done`, late
        assert rig.service.media_segment() == "playing" and not kinds(rig, "media_segment_done")
        assert [d["seq"] for d in kinds(rig, "autoplay_report_ignored")] == [old]
        await page(rig, "started")                              # the next segment has started
        applied(await rig.service.advance({"actor": "user", "seq": old, "event": "done"}))
        await presenter.pump()
        assert where(rig)["position"]["index"] == 2 and rig.service.media_segment() == "playing"
        assert not kinds(rig, "media_segment_done"), "a stale `done` never ends the current segment"
    finally:
        await rig.close()


async def test_m11_previous_and_goto_back_into_an_earlier_scene_hold_a_non_zero_stop_frame(tmp_path):
    assert {name: _MOVE_OF[name] for name in ("previous", "goto", "hide", "sequence_abort")} == dict.fromkeys(
        ("previous", "goto", "hide", "sequence_abort"), Move.JUMP)
    assert {name: _MOVE_OF[name] for name in ("start", "next", "cue", "reveal", "sequence_done", "skip_sequence")} == dict.fromkeys(
        ("start", "next", "cue", "reveal", "sequence_done", "skip_sequence"), Move.FORWARD)
    assert _MOVE_OF["sequence_step"] is Move.STEP and _MOVE_OF["play"] is Move.RESTART
    assert all(name not in _MOVE_OF for name in ("pause", "resume", "detour", "speaking", "boundary", "stage_synced"))
    rig = await open_rig(tmp_path, jarvis_content())
    try:
        applied(await rig.service.start(rig.start_body("user_presenter")))
        for _ in range(3):
            applied(await rig.run("next"))
        assert where(rig)["position"]["index"] == 4 and where(rig)["scene"]["number"] == 3   # S3, anchorless: no timeline in a user run
        applied(await rig.run("previous"))                      # back into S2 on I3: its stop frame 299, held
        assert segment(rig) == (S2, "marker", 299, 299, False)
        applied(await rig.run("previous"))                      # same scene, I2: its stop frame 179, held
        assert segment(rig) == (S2, "reveal", 179, 179, False)
        applied(await rig.run("goto", position=4))
        applied(await rig.run("goto", position=2))              # a jump back into S2: I2's stop frame, held, nothing replayed
        assert segment(rig) == (S2, "reveal", 179, 179, False)
        state = rig.service.state
        assert _move_of("previous", state, state) is Move.JUMP and _move_of("resume", state, state) is Move.NONE
    finally:
        await rig.close()
