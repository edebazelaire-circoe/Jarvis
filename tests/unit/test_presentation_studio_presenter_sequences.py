"""Locked sequences and interruptions through the Jarvis presenter, on the real playback service (jarvis-interactive-presentation-studio, Slice 14).

A fake monotonic clock (integer milliseconds) shared by the service and the presenter; a fake `announce_notice`; the Voice process
reduced to the facts it records. What is proven: exact offsets from t0, t0 = the speech start, step actions bound through the
Slice 12 stage, a pause that preserves the remaining offsets, the three interruption policies (`allow` / `at_boundary` / `refuse`)
and the recovery after an explicit continue, the user's `skip_sequence` escape, a stop, deterministic logs.
Contract: `docs/presentation-studio.md` > *Jarvis presenter and locked sequences*.
"""

from __future__ import annotations

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from tests.fakes.presentation_studio_presenter import (
    SEQ_INTRO, SEQ_WRAP, TEXT_A, TEXT_D, advance, item_content, locked_content, make_presenter, now_ms, set_ms,
)
from tests.unit.test_presentation_studio_playback_service import I1, I2, I3, Rig, applied

START = 1_000_000


async def open_rig(tmp_path, content, name="a"):
    folder = tmp_path / name
    folder.mkdir()
    rig = await Rig(folder).open(content=content)
    set_ms(rig, START)
    return rig


def where(rig) -> dict:
    return rig.service.where()


def statuses(rig) -> list[tuple[str, str | None]]:
    return [(a.get("status"), a.get("code")) for k, _, a in rig.conversation.recorded
            if k is T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED]


class Show:
    """A presenter run up to the host of the locked sequence: I1 spoken and heard, the first words of the sequence issued."""

    def __init__(self, rig, presenter, brain, voice) -> None:
        self.rig, self.presenter, self.brain, self.voice = rig, presenter, brain, voice
        self.t0: int | None = None
        self.ids: dict[str, str] = {}

    async def to_host(self) -> None:
        applied(await self.rig.service.start(self.rig.start_body("jarvis_presenter")))
        await self.presenter.pump()
        self.voice.started(); self.voice.completed()
        await self.presenter.pump()                                  # I1 heard -> the host: the intro line is handed over
        assert self.brain.texts == [TEXT_A, SEQ_INTRO]
        self.ids["intro"] = self.brain.last_id

    async def start_speech(self, lag_ms: int = 400) -> None:
        advance(self.rig, lag_ms)
        self.voice.started(self.ids["intro"])
        await self.presenter.pump()
        self.t0 = now_ms(self.rig)

    async def at(self, offset_ms: int) -> None:
        set_ms(self.rig, self.t0 + offset_ms)
        await self.presenter.pump()


@pytest.fixture
async def show(tmp_path):
    rig = await open_rig(tmp_path, locked_content())
    presenter, brain, voice = make_presenter(rig)
    yield Show(rig, presenter, brain, voice)
    await rig.close()


# ------------------------------------------------------------------ exact offsets from t0, t0 = the first words

async def test_the_sequence_waits_for_the_first_words_then_releases_every_step_at_its_exact_offset(show):
    await show.to_host()
    state = where(show.rig)
    assert state["owner"] == "sequence" and state["sequence"]["step"] == 0 and show.presenter.view()["sequence"]["state"] == "waiting_start"
    await show.start_speech(lag_ms=400)
    assert where(show.rig)["sequence"]["step"] == 1                                       # step 0 at t0, with the first words
    view = show.presenter.view()["sequence"]
    assert (view["basis"], view["state"], view["duration_ms"]) == ("speech_started", "running", 9000)
    await show.at(2999)
    assert where(show.rig)["sequence"]["step"] == 1
    await show.at(3000)
    assert where(show.rig)["sequence"]["step"] == 2
    assert (await show.rig.stage_object()).payload.prefab.props["mode"] == "compact"      # the step's action, bound through the stage
    show.voice.completed(show.ids["intro"])
    await show.at(6600)                                                                    # polled 100 ms late
    assert where(show.rig)["sequence"]["step"] == 3 and show.brain.texts[-1] == SEQ_WRAP
    assert (await show.rig.stage_object()).payload.prefab.props["label"] == "Fin"
    wrap = show.brain.last_id
    show.voice.started(wrap)
    log = show.presenter.action_log
    assert [(e.step_id, e.scheduled_ms - show.t0, e.late_ms) for e in log] == [("intro", 0, 0), ("mid", 3000, 0), ("wrap", 6500, 100)]
    assert [len(e.actions) for e in log] == [1, 1, 1]
    await show.at(8999)
    assert where(show.rig)["owner"] == "sequence"
    await show.at(9000)
    assert where(show.rig)["owner"] == "user" and where(show.rig)["sequence"] is None
    show.voice.completed(wrap)
    await show.presenter.pump()
    assert where(show.rig)["position"]["index"] == 3 and show.brain.texts[-1] == TEXT_D
    assert statuses(show.rig) == [("sequence_done", None)]


async def test_a_silent_first_step_or_a_run_where_jarvis_does_not_speak_starts_at_the_explicit_start(tmp_path):
    content = locked_content()
    content["sequences"][0]["steps"][0] = {"step_id": "intro", "offset_ms": 0, "speaker": "none",
                                           "visual": [{"kind": "reveal", "scene_id": content["items"][1]["scene_id"],
                                                       "anchor_id": "marker"}]}
    rig = await open_rig(tmp_path, content, "silent")
    presenter, brain, voice = make_presenter(rig)
    content_speaks = locked_content()
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump(); voice.started(); voice.completed()
    await presenter.pump()
    t0 = now_ms(rig)
    assert presenter.view()["sequence"]["basis"] == "explicit_start" and where(rig)["sequence"]["step"] == 1
    set_ms(rig, t0 + 6500)
    await presenter.pump()
    assert brain.texts[-1] == SEQ_WRAP and presenter.action_log[-1].scheduled_ms == t0 + 6500
    await rig.close()
    # the user presenter: Jarvis stays silent, the sequence still runs its visuals
    rig2 = await open_rig(tmp_path, content_speaks, "user")
    presenter2, brain2, _ = make_presenter(rig2)
    applied(await rig2.service.start(rig2.start_body("user_presenter")))
    applied(await rig2.run("next"))
    await presenter2.pump()
    t1 = now_ms(rig2)
    assert presenter2.view()["sequence"]["basis"] == "explicit_start" and where(rig2)["sequence"]["step"] == 1
    set_ms(rig2, t1 + 9000)
    await presenter2.pump()
    assert brain2.calls == [] and where(rig2)["owner"] == "user" and [e.step_id for e in presenter2.action_log] == ["intro", "mid", "wrap"]
    await rig2.close()


async def test_the_same_score_on_the_same_clock_gives_the_same_action_log(tmp_path):
    logs = []
    for name in ("one", "two"):
        rig = await open_rig(tmp_path, locked_content(), name)
        presenter, brain, voice = make_presenter(rig)
        show = Show(rig, presenter, brain, voice)
        await show.to_host()
        await show.start_speech(lag_ms=250)
        for offset in (3000, 6500, 9000):
            await show.at(offset)
        logs.append([entry.key() for entry in presenter.action_log])
        await rig.close()
    assert logs[0] == logs[1] and len(logs[0]) == 3


async def test_a_sequence_that_never_gets_its_first_words_is_a_visible_pause_and_resume_starts_it_afresh(show):
    await show.to_host()
    advance(show.rig, 10_001)
    await show.presenter.pump()
    state = where(show.rig)
    assert state["phase"] == "paused" and "speech_not_started" in state["problems"] and state["sequence"]["step"] == 0
    applied(await show.rig.run("resume"))
    await show.presenter.pump()
    assert show.brain.texts == [TEXT_A, SEQ_INTRO, SEQ_INTRO] and where(show.rig)["problems"] == []
    show.ids["intro"] = show.brain.last_id
    await show.start_speech(lag_ms=50)
    assert where(show.rig)["sequence"]["step"] == 1                      # a clean restart: t0 is the new first words


# ------------------------------------------------------------------ pause preserves the remaining offsets

async def test_a_user_pause_freezes_the_sequence_and_resume_keeps_every_remaining_offset(show):
    await show.to_host()
    await show.start_speech()
    await show.at(1000)
    applied(await show.rig.run("pause"))            # at_boundary: asked, taken at the next boundary
    await show.presenter.pump()
    await show.at(3000)                              # the boundary (step `mid`): the pause is taken BEFORE the step starts
    assert where(show.rig)["phase"] == "paused" and where(show.rig)["sequence"]["step"] == 1
    advance(show.rig, 30_000)
    await show.presenter.pump()
    assert where(show.rig)["sequence"]["step"] == 1                      # nothing moved while paused
    applied(await show.rig.run("resume"))
    await show.presenter.pump()
    assert where(show.rig)["sequence"]["step"] == 2                      # `mid` is released at once, exactly as late as it was
    entry = show.presenter.action_log[-1]
    assert (entry.step_id, entry.scheduled_ms - show.t0, entry.late_ms) == ("mid", 33_000, 0)
    set_ms(show.rig, show.t0 + 6500 + 30_000 - 1)
    await show.presenter.pump()
    assert where(show.rig)["sequence"]["step"] == 2
    advance(show.rig, 1)
    await show.presenter.pump()
    assert where(show.rig)["sequence"]["step"] == 3                      # `wrap` still 3500 ms after `mid`: nothing was lost or doubled


async def test_a_pause_and_a_resume_between_two_pumps_are_still_felt_by_the_clock(show):
    await show.to_host()
    await show.start_speech()
    await show.at(1000)
    applied(await show.rig.run("pause")) if False else None
    # the machine pauses (a stage failure takes `halt`), the user resumes, and the presenter never got to look in between
    await show.rig.service.halt("probe")
    advance(show.rig, 5000)
    show.rig.service.resolve_problem("probe")
    applied(await show.rig.run("resume"))
    await show.presenter.pump()
    set_ms(show.rig, show.t0 + 3000 + 5000 - 1)
    await show.presenter.pump()
    assert where(show.rig)["sequence"]["step"] == 1
    advance(show.rig, 1)
    await show.presenter.pump()
    assert where(show.rig)["sequence"]["step"] == 2


# ------------------------------------------------------------------ interruption by the user's address: the three policies

async def test_at_boundary_the_interruption_waits_for_the_boundary_and_never_resumes_alone(show):
    await show.to_host()
    await show.start_speech()
    await show.at(1000)
    show.voice.floor()                                                   # the user takes the floor over the intro
    show.voice.interrupted(show.ids["intro"])
    await show.presenter.pump()
    state = where(show.rig)
    assert state["phase"] == "playing" and state["pending"] == "pause" and show.presenter.view()["interrupted"] is True
    await show.at(2999)
    assert where(show.rig)["sequence"]["step"] == 1 and where(show.rig)["phase"] == "playing"
    await show.at(3000)
    assert where(show.rig)["phase"] == "paused" and where(show.rig)["sequence"]["step"] == 1 and where(show.rig)["pending"] is None
    for _ in range(3):                                                   # the user's turn is answered; no automatic resume
        advance(show.rig, 20_000)
        show.voice.other_speech()
        await show.presenter.pump()
    assert where(show.rig)["phase"] == "paused" and show.brain.texts == [TEXT_A, SEQ_INTRO]
    applied(await show.rig.run("resume"))
    await show.presenter.pump()
    assert where(show.rig)["sequence"]["step"] == 2 and show.brain.texts == [TEXT_A, SEQ_INTRO]    # pause_resume: not re-said
    assert ("interrupted", "floor_taken") in statuses(show.rig)
    await show.at(6500 + 60_000)
    assert where(show.rig)["sequence"]["step"] == 3
    assert show.brain.texts[-1] == SEQ_WRAP


async def test_abort_to_recovery_lands_exactly_on_the_recovery_point_when_the_user_says_continue(tmp_path):
    rig = await open_rig(tmp_path, locked_content(on_interrupt="abort_to_recovery"))
    presenter, brain, voice = make_presenter(rig)
    show = Show(rig, presenter, brain, voice)
    await show.to_host()
    await show.start_speech()
    await show.at(1000)
    voice.floor()
    await presenter.pump()
    await show.at(3000)
    assert where(rig)["phase"] == "paused"
    position, epoch = where(rig)["position"]["index"], rig.service.state.epoch
    applied(await rig.run("resume"))
    await presenter.pump()
    state = where(rig)
    assert state["position"]["index"] == position == 2                   # the recovery point is the host: position restored exactly
    assert rig.service.state.epoch == epoch + 1 and state["sequence"]["step"] == 0     # re-entered afresh, never half-played
    assert brain.texts == [TEXT_A, SEQ_INTRO, SEQ_INTRO]                 # the choreography restarts from its first words
    assert ("sequence_aborted", "recovery_point") in statuses(rig)
    voice.started(brain.last_id)
    await presenter.pump()
    assert state["owner"] == "sequence" and where(rig)["sequence"]["step"] == 1
    await rig.close()


async def test_refuse_ignores_the_interruption_exactly_and_the_choreography_goes_on(tmp_path):
    rig = await open_rig(tmp_path, locked_content(interruption="refuse"))
    presenter, brain, voice = make_presenter(rig)
    show = Show(rig, presenter, brain, voice)
    await show.to_host()
    await show.start_speech()
    await show.at(1000)
    voice.floor()
    voice.user_turn()
    await presenter.pump()
    assert where(rig)["phase"] == "playing" and where(rig)["pending"] is None and presenter.view()["interrupted"] is False
    assert ("interrupted", "refused_by_policy") in statuses(rig)
    refused = await rig.run("pause")
    assert refused.reason == "interruption_refused"                     # the user's own pause is refused the same way
    await show.at(3000)
    assert where(rig)["sequence"]["step"] == 2                          # on time
    applied(await rig.run("stop"))                                      # only an explicit stop interrupts
    assert where(rig)["phase"] == "stopped"
    await presenter.pump()
    assert presenter.view() is None
    await rig.close()


async def test_allow_pauses_a_plain_item_at_once_and_resume_says_the_cut_line_again_from_its_start(tmp_path):
    rig = await open_rig(tmp_path, item_content(interruption="allow"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started()
    voice.floor()
    voice.interrupted()
    await presenter.pump()
    assert where(rig)["phase"] == "paused" and presenter.view()["interrupted"] is True
    position, epoch = where(rig)["position"]["index"], rig.service.state.epoch
    for _ in range(3):
        advance(rig, 15_000)
        await presenter.pump()
    assert where(rig)["phase"] == "paused" and len(brain.calls) == 1     # never resumes alone
    applied(await rig.run("resume"))
    await presenter.pump()
    assert (where(rig)["position"]["index"], rig.service.state.epoch) == (position, epoch)   # continue_item: same entry
    assert brain.texts == [TEXT_A, TEXT_A]                                # re-issued from its start, once
    voice.started(); voice.completed()
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2
    await rig.close()


@pytest.mark.parametrize("recovery, expected_position, expected_texts", [
    ("restart_item", 1, [TEXT_A, TEXT_A]),
    ("skip_to_next", 2, [TEXT_A, "Deux ZXQV-LIGNE."]),
    ("recovery_point", 1, [TEXT_A, TEXT_A]),
])
async def test_the_declared_recovery_decides_where_an_explicit_continue_lands(tmp_path, recovery, expected_position, expected_texts):
    rig = await open_rig(tmp_path, item_content(interruption="allow", recovery=recovery))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started(); voice.interrupted()
    await presenter.pump()
    assert where(rig)["phase"] == "paused"
    applied(await rig.run("resume"))
    await presenter.pump()
    assert where(rig)["position"]["index"] == expected_position and brain.texts == expected_texts
    await rig.close()


async def test_at_boundary_on_a_plain_item_lets_the_line_finish_then_pauses_before_the_next_item(tmp_path):
    rig = await open_rig(tmp_path, item_content(interruption="at_boundary"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started()
    voice.user_turn()                                                   # an admitted user turn, the line keeps playing
    await presenter.pump()
    assert where(rig)["phase"] == "playing" and where(rig)["pending"] == "pause"
    voice.completed()
    await presenter.pump()
    assert where(rig)["phase"] == "paused" and where(rig)["position"]["index"] == 2 and brain.texts == [TEXT_A]
    applied(await rig.run("resume"))
    await presenter.pump()
    assert brain.texts == [TEXT_A, "Deux ZXQV-LIGNE."]                  # the next item starts at its own beginning
    await rig.close()


async def test_a_cut_line_with_a_pending_boundary_pauses_on_the_same_item_and_continue_says_it_again(tmp_path):
    rig = await open_rig(tmp_path, item_content(interruption="at_boundary"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started(); voice.floor(); voice.interrupted()
    await presenter.pump()
    assert where(rig)["phase"] == "paused" and where(rig)["position"]["index"] == 1
    applied(await rig.run("resume"))
    await presenter.pump()
    assert brain.texts == [TEXT_A, TEXT_A] and where(rig)["position"]["index"] == 1
    await rig.close()


async def test_a_refused_pause_on_a_plain_item_keeps_the_choreography_and_moves_on_after_a_cut_line(tmp_path):
    rig = await open_rig(tmp_path, item_content(interruption="refuse"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started(); voice.floor(); voice.interrupted()
    await presenter.pump()
    assert where(rig)["phase"] == "playing" and where(rig)["position"]["index"] == 2 and brain.texts[-1] == "Deux ZXQV-LIGNE."
    await rig.close()


async def test_speech_that_is_not_ours_never_moves_the_run(tmp_path):
    rig = await open_rig(tmp_path, item_content(interruption="allow"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    for _ in range(3):
        voice.other_speech()
        await presenter.pump()
    assert where(rig)["phase"] == "playing" and where(rig)["position"]["index"] == 1 and presenter.view()["line"] == "pending"
    await rig.close()


async def test_a_user_turn_between_two_items_pauses_the_run_too(tmp_path):
    content = item_content(interruption="allow")
    rig = await open_rig(tmp_path, content)
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started(); voice.completed()
    voice.user_turn()                                                   # arrives in the same instant as the end of the line
    await presenter.pump()
    assert where(rig)["phase"] == "paused"
    await rig.close()


# ------------------------------------------------------------------ the user's escape and the stop

async def test_skip_sequence_is_the_users_escape_and_the_presenter_carries_on_after_it(show):
    await show.to_host()
    await show.start_speech()
    await show.at(1000)
    state = applied(await show.rig.run("skip_sequence"))
    assert state["position"]["index"] == 4 - 1 and state["owner"] == "user"
    await show.presenter.pump()
    assert show.brain.texts[-1] == TEXT_D and ("sequence_skipped", "left_before_done") in statuses(show.rig)
    assert show.presenter.action_log[-1].step_id == "intro"             # nothing more was released for the skipped sequence


async def test_a_stop_mid_sequence_ends_the_run_cleanly_and_nothing_is_said_afterwards(show):
    await show.to_host()
    await show.start_speech()
    applied(await show.rig.run("stop"))
    texts = list(show.brain.texts)
    set_ms(show.rig, show.t0 + 9000)
    await show.presenter.pump()
    await show.presenter.pump()
    assert show.brain.texts == texts and show.presenter.view() is None and await show.rig.stage_object() is None
    assert where(show.rig)["last_run"]["reason"] == "user"


async def test_the_presenter_recovers_a_run_it_never_saw_and_a_core_restart_leaves_nothing_to_resume(tmp_path):
    rig = await open_rig(tmp_path, item_content(interruption="allow"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started()
    # Core restarts: the playback state is memory, a new service has no run; the scene's leftovers are taken back by id
    reborn = rig.build()
    await reborn.start_service()
    presenter2, brain2, _ = make_presenter(rig)
    await presenter2.pump()
    assert reborn.where() == {"phase": "idle", "running": False} and brain2.calls == [] and presenter2.view() is None
    refused = await rig.run("resume")
    assert refused.reason == "not_running"
    assert await rig.stage_object() is None
    await rig.close()


# ------------------------------------------------------------------ the turn that says "continue" is not an interruption

async def test_the_turn_that_says_continue_is_the_cause_of_the_resume_not_a_new_interruption(tmp_path):
    rig = await open_rig(tmp_path, item_content(interruption="allow"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    voice.started(); voice.floor(); voice.interrupted()
    await presenter.pump()
    assert where(rig)["phase"] == "paused"
    advance(rig, 8000)
    voice.user_turn()                                  # the user says "continue": the turn is accepted, THEN the resume is called
    applied(await rig.run("resume"))
    await presenter.pump()                             # the loop only looks now: the turn's fact predates the resume
    assert where(rig)["phase"] == "playing" and brain.texts == [TEXT_A, TEXT_A]
    advance(rig, 1)
    voice.user_turn()                                  # a NEW turn after the continue is an interruption again
    await presenter.pump()
    assert where(rig)["phase"] == "paused"
    await rig.close()


# ------------------------------------------------------------------ the temporary mode is never stored; a restart brings back the preference

from tests.unit.test_board_service import world as board_world  # noqa: E402,F401  (the real Board + mode service fixture)


async def test_the_temporary_mode_is_never_stored_and_a_core_restart_brings_back_the_stored_preference(tmp_path, board_world):
    from jarvis.domain.interaction_mode import InteractionMode  # noqa: PLC0415
    from jarvis.domain.presentation_studio_roles import STUDIO_RUN_MODE_SOURCE  # noqa: PLC0415
    from tests.fakes.presentation_studio_presenter import lines_content  # noqa: PLC0415

    service, modes, _, journal = board_world
    await service.start()
    await modes.request("presentation", source="control_center")        # the user's preference, stored on the Board
    await service.drain()
    rig = await Rig(tmp_path).open(content=lines_content())
    rig.mode = modes
    rig.build()
    set_ms(rig, START)
    presenter, brain, voice = make_presenter(rig)
    state = applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await service.drain()
    assert modes.mode is InteractionMode.ASSISTANT and modes.state.source == STUDIO_RUN_MODE_SOURCE and state["mode"] == "assistant"
    board = await service.get_active()
    assert board.interaction_mode is InteractionMode.PRESENTATION      # the stored preference was never touched by the run
    # Core restarts mid-run: the run and the presenter are memory and are gone; the Board restore is the only thing that sets the mode
    rig.build()
    await service.restore_interaction_mode()
    assert modes.mode is InteractionMode.PRESENTATION and modes.state.source == "board_restore"
    await rig.close()


# ------------------------------------------------------------------ races and structure

async def test_a_step_refused_because_the_run_paused_meanwhile_is_not_released_and_comes_back_once(show):
    from jarvis.domain.presentation_studio_playback import EventKind  # noqa: PLC0415

    await show.to_host()
    await show.start_speech()

    class RacingPlayback:
        """The user's pause lands between the presenter's look at the clock and its report of the step."""

        def __init__(self, inner) -> None:
            self.inner, self.raced = inner, False

        def __getattr__(self, name):
            return getattr(self.inner, name)

        async def notify(self, kind, **fields):
            if kind is EventKind.SEQUENCE_STEP and not self.raced:
                self.raced = True
                await self.inner.halt("race")            # the run is paused just before the report
            return await self.inner.notify(kind, **fields)

    show.presenter._playback = RacingPlayback(show.rig.service)
    set_ms(show.rig, show.t0 + 3000)
    await show.presenter.pump()
    assert where(show.rig)["phase"] == "paused" and where(show.rig)["sequence"]["step"] == 1
    assert [e.step_id for e in show.presenter.action_log] == ["intro"], "a refused report releases nothing"
    show.rig.service.resolve_problem("race")
    applied(await show.rig.run("resume"))
    await show.presenter.pump()
    assert [e.step_id for e in show.presenter.action_log] == ["intro", "mid"] and where(show.rig)["sequence"]["step"] == 2


async def test_the_presenter_cannot_resume_a_run_it_has_no_verb_for_and_never_names_one(tmp_path):
    import pytest  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    from jarvis.domain.presentation_studio_playback import EventKind  # noqa: PLC0415

    rig = await open_rig(tmp_path, item_content(interruption="allow"))
    for forbidden in (EventKind.RESUME, EventKind.DETOUR, EventKind.RETURN, EventKind.STOP, EventKind.SKIP_SEQUENCE, EventKind.START):
        with pytest.raises(ValueError, match="not a timeline report"):
            await rig.service.notify(forbidden)
    source = (Path(__file__).resolve().parents[2] / "jarvis/core/presentation_studio_presenter.py").read_text(encoding="utf-8")
    assert "EventKind.RESUME" not in source and ".resume(" not in source.replace("resume_clock(", "")
    await rig.close()
