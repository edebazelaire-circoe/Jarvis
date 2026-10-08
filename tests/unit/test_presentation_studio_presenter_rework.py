"""Slice 14 rework (QA-1): B1 a run where Jarvis does not speak is never paused by the user's turns; P1 a line queued behind a line
that is still playing does not time out; I2 pinned entry condition for Slice 21 (origin of a brain start).
"""

from __future__ import annotations

import pytest

from jarvis.core.presentation_studio_playback import PlaybackStatus
from tests.fakes.presentation_studio_presenter import (
    SEQ_INTRO, SEQ_WRAP, TEXT_A, advance, item_content, lines_content, locked_content, make_presenter, set_ms,
)
from tests.unit.test_presentation_studio_playback_service import Rig, applied
from tests.unit.test_presentation_studio_presenter_sequences import Show, open_rig, where


@pytest.mark.parametrize("role, extra", [("user_presenter", {}), ("rehearsal", {})])
async def test_turns_and_floor_signals_never_pause_or_block_a_run_where_jarvis_does_not_speak(tmp_path, role, extra):
    rig = await open_rig(tmp_path, lines_content())
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body(role, **extra)))
    for _ in range(3):
        voice.user_turn()
        voice.floor()
        voice.other_speech()
        await presenter.pump()
        assert where(rig)["phase"] == "playing" and where(rig)["pending"] is None
    assert presenter.view()["interrupted"] is False and brain.calls == []
    result = await rig.run("next")
    assert result.status is PlaybackStatus.APPLIED and where(rig)["position"]["index"] == 2    # `next` is not refused as `paused`
    await rig.close()


@pytest.mark.parametrize("role, extra", [("jarvis_presenter", {}), ("rehearsal", {"jarvis_speaks": True})])
async def test_a_run_where_jarvis_speaks_is_still_paused_by_the_users_turn(tmp_path, role, extra):
    rig = await open_rig(tmp_path, item_content(interruption="allow"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body(role, **extra)))
    await presenter.pump()
    voice.user_turn()
    await presenter.pump()
    assert where(rig)["phase"] == "paused" and presenter.view()["interrupted"] is True
    await rig.close()


async def test_in_a_run_where_jarvis_does_not_speak_a_locked_sequence_is_still_interruptible_under_its_policy(tmp_path):
    rig = await open_rig(tmp_path, locked_content())
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("user_presenter")))
    applied(await rig.run("next"))
    await presenter.pump()
    voice.user_turn()
    await presenter.pump()
    assert where(rig)["pending"] == "pause"                     # at_boundary: taken at the next step boundary
    assert brain.calls == []
    await rig.close()


# ------------------------------------------------------------------ P1: queued behind a line that is still playing

async def test_a_step_line_queued_behind_a_playing_line_does_not_time_out_while_the_voice_is_busy(tmp_path):
    rig = await open_rig(tmp_path, locked_content())
    presenter, brain, voice = make_presenter(rig)
    show = Show(rig, presenter, brain, voice)
    await show.to_host()
    await show.start_speech()
    await show.at(6500)                                         # `wrap` is issued while `intro` is still playing
    assert brain.texts[-1] == SEQ_WRAP
    wrap = brain.last_id
    await show.at(6500 + 11_000)                                # more than START_TIMEOUT_S after the issue
    assert where(rig)["phase"] == "playing" and where(rig)["problems"] == [], "busy is not failing"
    assert presenter.next_wake_s() is None or presenter.next_wake_s() > 0
    voice.completed(show.ids["intro"])                          # the earlier line ends: the clock of `wrap` starts now
    await presenter.pump()
    advance(rig, 9_999)
    await presenter.pump()
    assert where(rig)["phase"] == "playing"
    advance(rig, 2)
    await presenter.pump()
    assert where(rig)["phase"] == "paused" and "speech_not_started" in where(rig)["problems"]   # still a real failure when it never starts
    await rig.close()


async def test_a_queued_line_that_starts_after_the_earlier_one_ends_is_fine(tmp_path):
    rig = await open_rig(tmp_path, locked_content())
    presenter, brain, voice = make_presenter(rig)
    show = Show(rig, presenter, brain, voice)
    await show.to_host()
    await show.start_speech()
    await show.at(6500)
    wrap = brain.last_id
    await show.at(6500 + 30_000)
    voice.completed(show.ids["intro"])
    voice.started(wrap)
    await presenter.pump()
    assert where(rig)["phase"] == "playing" and presenter.view()["line"] == "playing"
    await rig.close()


# ------------------------------------------------------------------ I2: entry condition for Slice 21

async def test_entry_condition_for_slice_21_a_brain_actor_with_an_explicit_request_origin_is_accepted_by_the_start_contract(tmp_path):
    """PINS the current behaviour: the Slice 12 start contract takes `origin` from the body. A Core caller with actor `brain` and
    origin `explicit_user_request` switches the mode and starts a Jarvis run. Slice 21 MUST therefore derive the origin from the real
    turn (a user request admitted as addressed) and never from model input; this test fails the day the contract changes."""

    rig = await Rig(tmp_path).open(content=lines_content())
    set_ms(rig, 1_000_000)
    body = rig.start_body("jarvis_presenter", actor="brain", origin="explicit_user_request")
    result = await rig.service.start(body)
    assert result.status is PlaybackStatus.APPLIED
    assert rig.mode.state.source == "presentation_studio_run" or rig.mode.mode.value == "assistant"
    applied(await rig.run("stop"))
    await rig.close()


async def test_a_line_that_is_still_playing_is_not_said_again_when_the_user_pauses_and_continues(tmp_path):
    rig = await open_rig(tmp_path, item_content(interruption="allow"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started()
    applied(await rig.run("pause"))
    await presenter.pump()
    advance(rig, 5000)
    applied(await rig.run("resume"))
    await presenter.pump()
    assert brain.texts == [TEXT_A], "the line in flight ends naturally (01c); it is not issued a second time"
    voice.completed()
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2
    await rig.close()
