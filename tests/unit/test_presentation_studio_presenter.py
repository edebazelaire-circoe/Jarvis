"""Jarvis presenter on the real playback service, a fake clock and a fake speech stack (jarvis-interactive-presentation-studio, Slice 14).

Real objects: the scene, the prefab catalogue, the edit service, the stores, the playback machine and service, the interaction
mode service. Doubles: the clock (one monotonic fake shared by the service and the presenter, in integer milliseconds), `announce_notice`
(records the exact call) and the Voice process (the `mouth.speech.*` facts it records). The presenter is driven by hand
(`pump()`), so every case is deterministic. The real SpeechScheduler / PresentationSpeechGate path is
`test_presentation_studio_presenter_speech.py`. Contract: `docs/presentation-studio.md` > *Jarvis presenter and locked sequences*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.core.presentation_studio_playback import PlaybackStatus
from jarvis.core.presentation_studio_presenter import (
    ANNOUNCE_FAILED, ANNOUNCE_REFUSED, LINE_TIMEOUT_S, SPEECH_NOT_STARTED, SPEECH_STALLED, START_TIMEOUT_S,
)
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_studio_roles import STUDIO_RUN_MODE_SOURCE, SCORE_LINE_KIND
from jarvis.domain.v2 import SpeechKind
from tests.fakes.presentation_studio_presenter import (
    NOTE_SECRET, SECRET, SEQ_INTRO, SEQ_WRAP, TEXT_A, TEXT_D, advance, item_content, lines_content, locked_content, make_presenter,
    now_ms, set_ms,
)
from tests.unit.test_presentation_studio_playback_service import I1, I2, I3, I4, Rig, applied


@pytest.fixture
async def rig(tmp_path):
    made = await Rig(tmp_path).open(content=lines_content())
    set_ms(made, 1_000_000)
    yield made
    await made.close()


async def started(rig, role="jarvis_presenter", **extra):
    return applied(await rig.service.start(rig.start_body(role, **extra)))


def where(rig) -> dict:
    return rig.service.where()


# ------------------------------------------------------------------ speaking: only through announce_notice, with the 01c arguments

async def test_a_jarvis_line_is_handed_over_once_through_announce_notice_with_the_exact_01c_arguments(rig):
    presenter, brain, voice = make_presenter(rig)
    state = await started(rig)
    await presenter.pump()
    await presenter.pump()                                  # idempotent: nothing is said twice
    assert brain.texts == [TEXT_A]
    kwargs = brain.calls[0][1]
    assert kwargs == {"kind": SCORE_LINE_KIND, "supersedes_key": f"presentation_studio:{state['run_id']}", "ttl_s": 30.0}
    assert kwargs["kind"] is SpeechKind.PROGRESS
    assert not {"verbatim", "work_id", "conversation_id"} & kwargs.keys()
    assert presenter.view()["line"] == "pending" and presenter.view()["lines"] == 1


async def test_the_item_ends_when_the_mouth_says_completed_not_before(rig):
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    await presenter.pump()
    voice.started()
    await presenter.pump()
    assert where(rig)["speaking"] == "jarvis" and presenter.view()["line"] == "playing"
    advance(rig, 20_000)                                    # a long line: no wall-clock decision moves the run
    await presenter.pump()
    assert where(rig)["position"]["index"] == 1 and where(rig)["phase"] == "playing"
    voice.completed()
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2 and where(rig)["speaking"] is None


async def test_the_gap_between_a_finished_line_and_the_next_item_is_honoured(tmp_path):
    rig = await Rig(tmp_path).open(content=lines_content())
    set_ms(rig, 1_000_000)
    presenter, brain, voice = make_presenter(rig, gap_ms=300)
    await started(rig)
    await presenter.pump()
    voice.started()
    voice.completed()
    await presenter.pump()
    assert where(rig)["position"]["index"] == 1             # the gap has not elapsed
    assert presenter.next_wake_s() == pytest.approx(0.3)
    advance(rig, 299)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 1
    advance(rig, 1)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2
    await rig.close()


# ------------------------------------------------------------------ silence speaks nothing but its actions still run

async def test_a_silence_item_speaks_nothing_executes_its_bound_action_and_lasts_its_soft_target(rig):
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    await presenter.pump()
    voice.started()
    voice.completed()
    await presenter.pump()
    assert where(rig)["item"]["kind"] == "silence" and where(rig)["silence"] is True
    assert (await rig.stage_object()).payload.prefab.props["mode"] == "compact"        # the motion action ran on entry
    for _ in range(3):
        await presenter.pump()
    assert brain.texts == [TEXT_A]                                                     # nothing was said for the silence
    advance(rig, 1999)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2
    assert presenter.next_wake_s() == pytest.approx(0.001)
    advance(rig, 1)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 3 and brain.texts == [TEXT_A]


async def test_a_silence_without_a_target_lasts_the_default(tmp_path):
    content = lines_content()
    content["items"][1].pop("target_duration_ms")
    rig = await Rig(tmp_path).open(content=content)
    set_ms(rig, 1_000_000)
    presenter, brain, voice = make_presenter(rig, silence_default_ms=1500)
    await started(rig)
    await presenter.pump()
    voice.started(); voice.completed()
    await presenter.pump()
    advance(rig, 1499)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2
    advance(rig, 1)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 3
    await rig.close()


async def test_the_time_spent_paused_does_not_count_in_a_silence(rig):
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    await presenter.pump()
    voice.started(); voice.completed()
    await presenter.pump()
    advance(rig, 1500)
    applied(await rig.run("pause"))
    await presenter.pump()
    advance(rig, 60_000)
    applied(await rig.run("resume"))
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2             # still inside the silence: the 60 s of pause did not count
    advance(rig, 499)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2
    advance(rig, 1)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 3


async def test_a_user_item_is_the_users_jarvis_says_nothing_and_waits_for_the_users_navigation(rig):
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    applied(await rig.run("goto", position=3))
    for _ in range(3):
        await presenter.pump()
        advance(rig, 120_000)
    assert brain.texts == [] and where(rig)["position"]["index"] == 3 and where(rig)["item"]["presenter"] == "user"
    applied(await rig.run("next"))
    await presenter.pump()
    assert brain.texts == [TEXT_D]


async def test_the_end_of_the_score_stops_the_run_with_a_stated_reason_and_restores_the_mode(tmp_path):
    rig = await Rig(tmp_path).open(content=lines_content(), mode=InteractionMode.PRESENTATION)
    set_ms(rig, 1_000_000)
    presenter, brain, voice = make_presenter(rig)
    state = await started(rig)
    assert rig.mode.mode is InteractionMode.ASSISTANT and rig.mode.state.source == STUDIO_RUN_MODE_SOURCE
    assert state["mode"] == "assistant"
    await presenter.pump()
    voice.started(); voice.completed()
    await presenter.pump()
    advance(rig, 2000)
    await presenter.pump()
    applied(await rig.run("next"))
    await presenter.pump()
    voice.started(); voice.completed()
    await presenter.pump()
    final = where(rig)
    assert final["phase"] == "stopped" and final["last_run"]["reason"] == "completed" and final["last_run"]["problems"] == []
    assert rig.mode.mode is InteractionMode.PRESENTATION and rig.mode.state.source == STUDIO_RUN_MODE_SOURCE   # restored
    assert brain.texts == [TEXT_A, TEXT_D]
    statuses = [(a.get("status"), a.get("code")) for kind, _, a in rig.conversation.recorded
                if kind is T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED]
    assert statuses == [("completed", None)]
    await presenter.pump()
    assert presenter.view() is None                         # detached once the run is over
    await rig.close()


async def test_a_non_speaking_role_gets_no_line_and_the_presenter_never_moves_its_run(rig):
    presenter, brain, voice = make_presenter(rig)
    state = applied(await rig.service.start(rig.start_body("user_presenter")))
    assert state["jarvis_speaks"] is False
    for _ in range(3):
        await presenter.pump()
        advance(rig, 10_000)
    assert brain.calls == [] and where(rig)["position"]["index"] == 1
    assert presenter.view()["speaks"] is False


# ------------------------------------------------------------------ failures are visible, never a hang

async def test_a_line_core_does_not_publish_pauses_the_run_with_the_reason_and_resume_retries(rig):
    presenter, brain, voice = make_presenter(rig)
    brain.published = False                                  # no current intention / withheld / stopping (announce_notice False)
    await started(rig)
    await presenter.pump()
    state = where(rig)
    assert state["phase"] == "paused" and ANNOUNCE_REFUSED in state["problems"]
    assert state["presenter"]["problem"] == ANNOUNCE_REFUSED and state["presenter"]["line"] is None
    assert [r for r in rig.env.sink.rows if r[0] == "core.presentation_studio.presenter_announce_refused"]
    brain.published = True
    applied(await rig.run("resume"))
    await presenter.pump()
    assert brain.texts == [TEXT_A, TEXT_A] and ANNOUNCE_REFUSED not in where(rig)["problems"] and where(rig)["phase"] == "playing"
    statuses = [(a.get("status"), a.get("code")) for kind, _, a in rig.conversation.recorded
                if kind is T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED]
    assert statuses == [("line_failed", ANNOUNCE_REFUSED)]


async def test_announce_notice_raising_is_captured_and_said_not_swallowed(rig):
    presenter, brain, voice = make_presenter(rig)
    brain.error = RuntimeError(f"provider down {SECRET}")
    await started(rig)
    await presenter.pump()
    assert where(rig)["phase"] == "paused" and ANNOUNCE_FAILED in where(rig)["problems"]
    rows = [r for r in rig.env.sink.rows if r[0] == "core.presentation_studio.presenter_announce_failed"]
    assert rows and rows[0][1] == "error" and rows[0][2]["error_class"] == "RuntimeError"
    assert SECRET not in json.dumps(rig.env.sink.rows, default=str)       # the message of the exception is not copied


async def test_a_speech_stack_that_never_starts_the_line_is_a_visible_pause_after_a_bounded_wait(rig):
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    await presenter.pump()
    assert presenter.next_wake_s() == pytest.approx(START_TIMEOUT_S)         # the deadline is scheduled, not polled for
    advance(rig, int(START_TIMEOUT_S * 1000) - 1)
    await presenter.pump()
    assert where(rig)["phase"] == "playing"
    advance(rig, 2)
    await presenter.pump()
    state = where(rig)
    assert state["phase"] == "paused" and SPEECH_NOT_STARTED in state["problems"]
    assert presenter.next_wake_s() is None                                   # nothing left to wait for: the user decides


async def test_a_line_that_starts_but_never_ends_is_a_stalled_pause(rig):
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    await presenter.pump()
    voice.started()
    await presenter.pump()
    advance(rig, int(LINE_TIMEOUT_S * 1000) + 1)
    await presenter.pump()
    assert where(rig)["phase"] == "paused" and SPEECH_STALLED in where(rig)["problems"]


@pytest.mark.parametrize("event, code", [(T.MOUTH_SPEECH_FAILED, "speech_failed"), (T.MOUTH_SPEECH_UNCONFIRMED, "speech_unconfirmed"),
                                         (T.MOUTH_SPEECH_EXPIRED, "speech_obsolete"), (T.MOUTH_SPEECH_SUPERSEDED, "speech_obsolete")])
async def test_a_line_the_speech_stack_failed_or_dropped_pauses_the_run_with_its_code(rig, event, code):
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    await presenter.pump()
    voice.terminal(event)
    await presenter.pump()
    assert where(rig)["phase"] == "paused" and code in where(rig)["problems"]
    applied(await rig.run("resume"))
    await presenter.pump()
    assert brain.texts == [TEXT_A, TEXT_A]                   # the explicit continue says it again, once


async def test_a_late_fact_of_an_abandoned_line_changes_nothing(rig):
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    await presenter.pump()
    first = brain.last_id
    voice.terminal(T.MOUTH_SPEECH_FAILED)
    await presenter.pump()
    applied(await rig.run("resume"))
    await presenter.pump()
    second = brain.last_id
    assert first != second
    voice.started(first); voice.completed(first)             # a straggler of the abandoned line
    await presenter.pump()
    assert where(rig)["position"]["index"] == 1 and presenter.view()["line"] == "pending"
    voice.started(second); voice.completed(second)
    await presenter.pump()
    assert where(rig)["position"]["index"] == 2


async def test_a_mode_switch_failure_starts_nothing_and_the_presenter_never_speaks(tmp_path, monkeypatch):
    rig = await Rig(tmp_path).open(content=lines_content(), mode=InteractionMode.PRESENTATION)
    set_ms(rig, 1_000_000)
    presenter, brain, voice = make_presenter(rig)

    async def refused(value, *, source):
        raise ValueError("the mode service refuses")

    monkeypatch.setattr(rig.mode, "request", refused)
    result = await rig.service.start(rig.start_body("jarvis_presenter"))
    assert result.status is PlaybackStatus.REFUSED and result.reason == "mode_switch_refused"
    assert "refuses" in result.message and rig.mode.mode is InteractionMode.PRESENTATION
    await presenter.pump()
    assert brain.calls == [] and presenter.view() is None and await rig.stage_object() is None
    await rig.close()


async def test_a_foreign_mode_change_stops_the_run_and_nothing_more_is_said(rig):
    import asyncio
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    await presenter.pump()
    await rig.mode.request("presentation", source="control_center")        # the user picks PRESENTATION by hand
    await asyncio.gather(*list(rig.service._tasks))
    assert where(rig)["phase"] == "stopped" and where(rig)["last_run"]["reason"] == "mode_changed_by_user"
    voice.started(); voice.completed()
    await presenter.pump()
    await presenter.pump()
    assert brain.texts == [TEXT_A] and presenter.view() is None
    assert rig.mode.mode is InteractionMode.PRESENTATION                     # the user's choice, never forced back


# ------------------------------------------------------------------ text privacy: counts and ids only

async def test_no_script_or_note_reaches_a_log_an_event_a_trace_or_a_view(tmp_path):
    rig = await Rig(tmp_path).open(content=locked_content())
    set_ms(rig, 1_000_000)
    presenter, brain, voice = make_presenter(rig)
    await started(rig)
    views = []
    await presenter.pump()
    voice.started(); voice.completed()
    await presenter.pump()                                                    # now at the host: the intro line is issued
    voice.started()
    await presenter.pump()
    t0 = now_ms(rig)
    for offset in (0, 3000, 6500, 9000):
        set_ms(rig, t0 + offset)
        await presenter.pump()
        views.append(where(rig))
        if offset == 6500:
            voice.started()
        views.append(presenter.view())
    voice.floor()
    await presenter.pump()
    brain.published = False
    applied(await rig.run("resume")) if where(rig)["phase"] == "paused" else None
    await presenter.pump()
    everything = json.dumps({"rows": rig.env.sink.rows, "events": [(str(k), s, a) for k, s, a in rig.conversation.recorded],
                             "views": views, "log": [e.key() for e in presenter.action_log]}, default=str)
    for secret in (SECRET, NOTE_SECRET, "Regardez", "Voila", "Bonjour", "Merci"):
        assert secret not in everything, secret
    assert brain.texts[0] == TEXT_A and SEQ_INTRO in brain.texts           # the text only ever went to announce_notice
    await rig.close()


async def test_the_presenter_events_carry_only_the_allowed_attributes(rig):
    from jarvis.domain.conversation_events import ATTRIBUTE_KEYS
    presenter, brain, voice = make_presenter(rig)
    brain.published = False
    await started(rig)
    await presenter.pump()
    recorded = [(k, a) for k, _, a in rig.conversation.recorded if k is T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED]
    assert recorded and all(set(a) <= ATTRIBUTE_KEYS for _, a in recorded)
    assert recorded[0][1]["code"] == ANNOUNCE_REFUSED and recorded[0][1]["count"] == 1
