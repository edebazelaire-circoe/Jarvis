"""Partition, voix et média sans conflit d'horloge (handoff jarvis-remotion-native-studio-playback-fix, Slice 07).

Vrai service de lecture et vrai présentateur Jarvis sur le banc de la Slice 12 (scène, catalogue, édition, fichiers), une horloge fausse
partagée, une parole fausse (`FakeBrain` / `Voice` : les faits `mouth.speech.*` que la vraie pile enregistre) et une source de composition
fausse (le manifeste Remotion : 300 images à 30 i/s). Le navigateur est joué par les rapports `advance {seq, started|done}` qu'il enverrait.

Prouvé, par scénario :
- `jarvis_presenter` sur des scènes Remotion avec et sans ancres : la parole est enchaînée, le média suit la partition, une scène entrée part
  de l'image 0 même quand son élément d'entrée révèle une ancre à `at_ms > 0`, la scène suivante dans la même scène joue depuis l'ancre,
  un silence sur un segment de média dure le média (jamais sa cible `target_duration_ms`), une page muette est dite (`page_wait`), un retour
  tient l'image d'arrêt ;
- une répétition parlée suit les mêmes règles ; une séquence verrouillée dont le pas 0 révèle une ancre joue quand même l'entrée depuis 0 ;
- `user_presenter` avec des cues : une cue qui entre une scène part de 0, `next` au clavier, pause et reprise gardent le segment, aucune
  cible ne rythme une course menée par l'utilisateur ;
- voix indisponible : le suivi de cues absent est un état (`follower: absent`), la course avance au clavier ; une ligne que la voix ne
  commence jamais met la course en pause avec sa raison, et le clavier la fait avancer ;
- une course où Jarvis ne parle pas n'apprend jamais la fin d'un segment par la page (aucune avance sur la parole de la page).
Contrat : `docs/presentation-studio.md` > *Presentation experience contract* § 5, *Jarvis presenter and locked sequences*, *Cue following contract*.
"""

from __future__ import annotations

import pytest

from jarvis.core.presentation_studio_presenter import SPEECH_NOT_STARTED, START_TIMEOUT_S
from tests.fakes.presentation_studio_presenter import SECRET, TEXT_A, TEXT_D, advance, locked_content, make_presenter, set_ms
from tests.unit.test_presentation_studio_playback_service import CUE, CUE2, I1, I2, I3, I4, S1, S2, S3, Rig, applied, score_content
from tests.unit.test_presentation_studio_score_service import scene_body
from tests.unit.test_remotion_timeline_service import COMP, Compositions

TEXT_B = f"Deux {SECRET}."
TIMED = [{"anchor_id": "reveal", "label": "Reveler", "at_ms": 2000}, {"anchor_id": "marker", "label": "Repere", "at_ms": 6000}]


def deck(*, s1_anchors=(), s3_anchors=()):
    """S1 and S3: Remotion scenes without anchors (by default); S2: anchors at 2 s and 6 s (frames 60 and 180 at 30 fps, 300 frames)."""

    return [{**scene_body(S1), "title": "Un", "anchors": list(s1_anchors)}, {**scene_body(S2), "title": "Deux", "anchors": TIMED},
            {**scene_body(S3), "title": "Trois", "anchors": list(s3_anchors)}]


def jarvis_content() -> dict:
    """I1 Jarvis line on S1 -> I2 silence (2 s target) entering S2 and revealing `reveal` (2 s) -> I3 Jarvis line revealing `marker`
    -> I4 silence (1 s target) on S3."""

    return {
        "start_item_id": I1,
        "items": [
            {"item_id": I1, "scene_id": S1, "presenter": "jarvis", "kind": "speech", "text": TEXT_A, "next_item_id": I2},
            {"item_id": I2, "scene_id": S2, "presenter": "none", "kind": "silence", "target_duration_ms": 2000,
             "visual": [{"kind": "reveal", "scene_id": S2, "anchor_id": "reveal"}], "next_item_id": I3},
            {"item_id": I3, "scene_id": S2, "presenter": "jarvis", "kind": "speech", "text": TEXT_B,
             "visual": [{"kind": "reveal", "scene_id": S2, "anchor_id": "marker"}], "next_item_id": I4},
            {"item_id": I4, "scene_id": S3, "presenter": "none", "kind": "silence", "target_duration_ms": 1000}],
        "cues": [], "sequences": [], "recovery_points": []}


async def open_rig(tmp_path, content, **kwargs):
    rig = await Rig(tmp_path).open(scenes=deck(**kwargs), content=content)
    rig.build(timeline_source=Compositions(COMP))
    set_ms(rig, 1_000_000)
    return rig


def where(rig) -> dict:
    return rig.service.where()


def segment(rig) -> tuple | None:
    tl = where(rig).get("timeline")
    return None if tl is None else (tl["scene_id"], tl["anchor_id"], tl["from_frame"], tl["until_frame"], tl["playing"])


async def page(rig, *events: str, played_ms: int = 6000) -> None:
    """What the page says about the segment it plays: the follower's `started`, then (`played_ms` later) `done` when the Player halts on
    the stop frame."""

    seq = where(rig)["timeline"]["seq"]
    for event in events:
        if event == "done":
            advance(rig, played_ms)
        applied(await rig.service.advance({"actor": "user", "seq": seq, "event": event}))


def kinds(rig, kind: str) -> list[dict]:
    return [data for _level, data in rig.env.sink.of(f"core.presentation_studio.{kind}")]


async def speak_line(presenter, voice) -> None:
    await presenter.pump()
    voice.started()
    voice.completed()
    await presenter.pump()


# ------------------------------------------------------------------ Jarvis presents: speech sequenced, the media follows the score

@pytest.mark.parametrize("role", ["jarvis_presenter", "rehearsal"])
async def test_jarvis_speaks_the_score_and_the_media_follows_it_entries_from_frame_zero_silences_last_the_media(tmp_path, role):
    rig = await open_rig(tmp_path, jarvis_content())
    try:
        presenter, brain, voice = make_presenter(rig)
        extra = {"jarvis_speaks": True} if role == "rehearsal" else {}
        state = applied(await rig.service.start(rig.start_body(role, **extra)))
        assert state["jarvis_speaks"] is True and state["timeline"]["auto"] is True, "the page reports in a run Jarvis paces"
        assert segment(rig) == (S1, None, 0, 299, True), "S1 has no anchor: one segment, played once from frame 0"
        await speak_line(presenter, voice)
        assert brain.texts == [TEXT_A] and where(rig)["position"]["index"] == 2

        # I2 enters S2 and reveals `reveal` (2 s = frame 60): the entry is played from local frame 0, the anchor only bounds the stop
        assert segment(rig) == (S2, "reveal", 0, 179, True)
        assert rig.service.media_segment() == "playing"
        advance(rig, 60_000)                                    # thirty times the 2 s target: the silence never cuts the media
        await presenter.pump()
        assert where(rig)["position"]["index"] == 2 and presenter.next_wake_s() is None, "no soft-target deadline on a media silence"
        assert "page_wait" not in where(rig)
        advance(rig, 30_000)                                    # past 6 s + 15 s + 60 s with no news from the page: said, never advanced
        await presenter.pump()
        assert where(rig)["page_wait"]["started"] is False and where(rig)["position"]["index"] == 2
        assert len(kinds(rig, "autoplay_page_silent")) == 1
        await page(rig, "started", "done")                      # the Player reached frame 179
        assert kinds(rig, "media_segment_done") and where(rig)["position"]["index"] == 2, "Core learns, the presenter moves"
        await presenter.pump()
        assert where(rig)["position"]["index"] == 3 and brain.texts == [TEXT_A, TEXT_B]

        # I3 reveals `marker` in the same scene: its segment plays on from the frame the Player stopped on
        assert segment(rig) == (S2, "marker", 180, 299, True)
        await page(rig, "started")
        voice.started()
        voice.completed()
        await presenter.pump()                                  # the line, not the media, ends a spoken item (the score's pace)

        # I4: S3 has no anchor, entered from 0; its 1 s target waits for the media
        assert where(rig)["position"]["index"] == 4 and segment(rig) == (S3, None, 0, 299, True)
        advance(rig, 5_000)
        await presenter.pump()
        assert where(rig)["position"]["index"] == 4
        await page(rig, "started", "done")
        await presenter.pump()
        final = where(rig)
        assert final["phase"] == "stopped" and final["last_run"]["reason"] == "completed"
        assert brain.texts == [TEXT_A, TEXT_B], "nothing but the score's lines was said"
        assert not kinds(rig, "autoplay_deadline"), "no deadline moved a media item"
    finally:
        await rig.close()


async def test_a_silence_on_a_held_frame_keeps_its_soft_target_and_going_back_holds_the_stop_frame(tmp_path):
    rig = await open_rig(tmp_path, jarvis_content())
    try:
        presenter, brain, voice = make_presenter(rig)
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        await speak_line(presenter, voice)
        await page(rig, "started", "done")
        await presenter.pump()
        assert where(rig)["position"]["index"] == 3
        applied(await rig.run("previous"))                      # back to I2: its stop frame, held, nothing replayed
        assert segment(rig) == (S2, "reveal", 179, 179, False)
        assert rig.service.media_segment() is None, "a hold has no media to wait for"
        await presenter.pump()
        advance(rig, 1999)
        await presenter.pump()
        assert where(rig)["position"]["index"] == 2
        advance(rig, 1)
        await presenter.pump()
        assert where(rig)["position"]["index"] == 3, "the silence's soft target paces only an item with no media segment"
        assert segment(rig) == (S2, "marker", 180, 299, True)
    finally:
        await rig.close()


async def test_a_page_report_in_a_run_the_user_paces_teaches_core_nothing_and_moves_nothing(tmp_path):
    rig = await open_rig(tmp_path, jarvis_content())
    try:
        state = applied(await rig.service.start(rig.start_body("user_presenter")))
        # Slice 09: a scene without anchors gets one whole segment in EVERY run (the Variants Player never plays by itself)
        assert state["timeline"]["anchor_id"] is None and state["timeline"]["from_frame"] == 0 and state["timeline"]["auto"] is False
        applied(await rig.run("next"))
        tl = where(rig)["timeline"]
        assert tl["auto"] is False and segment(rig) == (S2, "reveal", 0, 179, True)
        await page(rig, "started", "done")
        assert where(rig)["position"]["index"] == 2 and kinds(rig, "autoplay_report_ignored")
        assert rig.service.media_segment() == "playing", "nothing was learnt from the page"
    finally:
        await rig.close()


# ------------------------------------------------------------------ a locked sequence

async def test_a_locked_sequence_whose_first_step_reveals_an_anchor_still_plays_the_entry_from_frame_zero(tmp_path):
    rig = await open_rig(tmp_path, locked_content())
    try:
        presenter, brain, voice = make_presenter(rig)
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        await speak_line(presenter, voice)
        await presenter.pump()                                  # I2 hosts `demo`: step `intro` @0 reveals `marker` (6 s = frame 180)
        assert where(rig)["position"]["index"] == 2 and where(rig)["owner"] == "sequence"
        entry = segment(rig)
        voice.started()                                         # the intro line starts: t0 of the sequence, step 0 is released
        await presenter.pump()
        assert where(rig)["sequence"]["step"] >= 1
        assert segment(rig) == (S2, "marker", 0, 299, True), f"the entry is played from frame 0 up to the step's stop frame ({entry})"
        seq = where(rig)["timeline"]["seq"]
        voice.completed()
        advance(rig, 3000)
        await presenter.pump()                                  # step `mid` changes a value, not the segment: the Player is not re-ordered
        assert where(rig)["timeline"]["seq"] == seq
        assert not kinds(rig, "autoplay_deadline")
    finally:
        await rig.close()


# ------------------------------------------------------------------ the user presents, with cues

async def test_a_user_presenter_run_with_cues_enters_from_frame_zero_and_the_keyboard_still_drives(tmp_path):
    content = score_content()                                   # I2 (cue CUE) enters S2 and reveals `marker` (6 s)
    rig = await open_rig(tmp_path, content, s1_anchors=[{"anchor_id": "reveal", "label": "Reveler"}],
                         s3_anchors=[{"anchor_id": "reveal", "label": "Reveler", "at_ms": 1000}])
    try:
        applied(await rig.service.start(rig.start_body("user_presenter")))
        assert segment(rig) == (S1, None, 0, 0, False), "S1's only anchor is on frame 0: the entry is a hold on frame 0"
        armed = rig.service.armed_set()
        assert [c["cue_id"] for c in armed["cues"]] == [CUE]
        fired = await rig.service.report_cue({"run_id": armed["run_id"], "generation": armed["generation"], "cue_id": CUE})
        assert fired["status"] == "fired" and where(rig)["position"]["index"] == 2
        assert segment(rig) == (S2, "marker", 0, 299, True), "a cue that enters a scene plays it from local frame 0 (defect C)"
        seq = where(rig)["timeline"]["seq"]
        applied(await rig.run("pause"))
        advance(rig, 30_000)
        applied(await rig.run("resume"))
        assert where(rig)["timeline"]["seq"] == seq and segment(rig)[2:4] == (0, 299), "resume continues: same segment, same seq"
        applied(await rig.run("next"))                          # keyboard: I3 silence, same scene, same anchor: the Player goes on
        assert where(rig)["timeline"]["seq"] == seq
        advance(rig, 120_000)
        assert where(rig)["position"]["index"] == 3, "no soft target paces a run the user leads"
        applied(await rig.run("previous"))
        applied(await rig.run("previous"))                      # back to S1: its stop frame, held
        assert segment(rig) == (S1, None, 0, 0, False)
        applied(await rig.run("goto", position=4))              # a jump into S3: the item's stop frame, held
        assert segment(rig) == (S3, "reveal", 299, 299, False)
        assert not kinds(rig, "autoplay_deadline")
    finally:
        await rig.close()


# ------------------------------------------------------------------ voice unavailable: a status, never a playback failure

async def test_voice_unavailable_is_a_status_and_the_run_still_advances_by_keyboard(tmp_path):
    rig = await open_rig(tmp_path, score_content(), s3_anchors=[{"anchor_id": "reveal", "label": "Reveler", "at_ms": 1000}])
    try:
        applied(await rig.service.start(rig.start_body("user_presenter")))
        assert where(rig)["follower"] == "waiting"
        advance(rig, 11_000)                                    # nobody pulled the armed set: no ambient voice lane
        assert where(rig)["follower"] == "absent" and where(rig)["phase"] == "playing"
        assert len(kinds(rig, "playback_follower_absent")) == 1
        for expected in (2, 3, 4):
            applied(await rig.run("next"))
            assert where(rig)["position"]["index"] == expected
        assert segment(rig) is not None and segment(rig)[0] == S3 and segment(rig)[2] == 0
        assert where(rig)["problems"] == [], "an absent follower is not a playback problem"
    finally:
        await rig.close()


async def test_a_jarvis_line_the_voice_never_starts_pauses_with_its_reason_and_the_keyboard_moves_on(tmp_path):
    rig = await open_rig(tmp_path, jarvis_content())
    try:
        presenter, brain, voice = make_presenter(rig)
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        await presenter.pump()
        assert brain.texts == [TEXT_A]
        advance(rig, int(START_TIMEOUT_S * 1000) + 1)           # the voice process is not there: the line never starts
        await presenter.pump()
        stuck = where(rig)
        assert stuck["phase"] == "paused" and SPEECH_NOT_STARTED in stuck["problems"]
        assert stuck["timeline"]["playing"] is False and stuck["timeline"]["from_frame"] == 0, "the media holds, it is not failed"
        refused = await rig.run("next")
        assert refused.status.value == "refused" and refused.reason == "paused", "typed refusal: a paused run is resumed first"
        applied(await rig.run("resume"))
        applied(await rig.run("next"))                          # the user's keyboard moves the run on without the voice
        assert where(rig)["position"]["index"] == 2 and segment(rig) == (S2, "reveal", 0, 179, True)
    finally:
        await rig.close()
