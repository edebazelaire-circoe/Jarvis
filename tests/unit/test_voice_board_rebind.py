"""Voice se relie au Board qui a la parole, sans redémarrer (handoff board-session, Slice 04b).

`board.voice_binding.changed` passe **avant** le filtre de conversation de
l'ordonnanceur ; le runtime draine, coupe (`board_switch`) et rouvre sur la
conversation que Core dit active. Doubles de `test_v2_speech_scheduler.py`.
"""

from __future__ import annotations

import asyncio

from jarvis.core.speech_authority import BOARD_VOICE_BINDING_CHANGED
from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind, VoiceLifecycleState
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION, FakeCore, FakeVoiceSession, RecordingJournal, _runtime, _wake, build_scheduler, busy_surface,
    speech_envelope, wait_for,
)

OTHER = "conversation-B"


def binding_changed(conversation_id: str = OTHER) -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type=BOARD_VOICE_BINDING_CHANGED,
                            payload={"conversation_id": conversation_id, "board_id": "board_b",
                                     "jarvis_session_id": "jsess_x", "reason": "board_switch"},
                            conversation_id=conversation_id)


# ------------------------------------------------------------------ ordonnanceur


async def test_the_scheduler_forwards_the_binding_change_before_its_conversation_filter():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    asked: list[str] = []
    scheduler.on_voice_binding_changed = asked.append
    await scheduler.start()
    try:
        await core.publish(binding_changed())
        await wait_for(lambda: asked == [OTHER])
        # Plus aucun évènement cerveau accepté : ni l'ancienne conversation, ni la nouvelle.
        await core.publish(speech_envelope("Ancien Board.", kind=SpeechKind.RESULT))
        await core.publish(speech_envelope("Nouveau Board.", kind=SpeechKind.RESULT, conversation_id=OTHER))
        await journal.wait_until(lambda: sum(1 for e in journal.of("voice.speech.ignored")
                                             if e["data"].get("reason") == "board_rebind") == 2)
        await asyncio.sleep(0.02)
        assert session.spoken == []
        assert journal.of("voice.board.rebind_requested")[0]["data"]["target_conversation_id"] == OTHER
    finally:
        await scheduler.stop()


async def test_drain_lets_authorized_speech_finish_then_expires_the_rest_at_the_deadline():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        await busy_surface(scheduler)
        await core.publish(speech_envelope("Dit avant la bascule.", kind=SpeechKind.RESULT))
        await journal.wait_until(lambda: journal.count("voice.speech.queued") == 1)
        await core.publish(binding_changed())
        await wait_for(lambda: scheduler._rebinding_to == OTHER)

        assert await scheduler.drain(0.1) is False
        assert scheduler.pending_count == 0
        assert journal.of("voice.board.rebind_drained")[-1]["data"]["code"] == "voice_rebind_drain_timeout"
    finally:
        await scheduler.stop()


async def test_a_binding_change_to_the_current_conversation_is_ignored():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    asked: list[str] = []
    scheduler.on_voice_binding_changed = asked.append
    await scheduler.start()
    try:
        await core.publish(binding_changed(CONVERSATION))
        await core.publish(speech_envelope("Toujours le même Board.", kind=SpeechKind.RESULT))
        await wait_for(lambda: session.texts() == ["Toujours le même Board."])
        assert asked == []
    finally:
        await scheduler.stop()


# ------------------------------------------------------------------ runtime


class SessionCore(FakeCore):
    """Core à Sessions : `current_session` dit la conversation qui a la parole."""

    def __init__(self) -> None:
        super().__init__()
        self.current = CONVERSATION

    async def current_session(self) -> dict:
        return {"session": {"jarvis_session_id": "jsess_x"},
                "binding": {"conversation_id": self.current, "board_id": "b", "jarvis_session_id": "jsess_x"}}


async def test_voice_rebinds_to_the_new_board_without_restarting(monkeypatch):
    journal = RecordingJournal()
    runtime, wakeword, _, session = _runtime(monkeypatch, journal=journal)
    core = SessionCore()
    runtime.core = core
    run_task = await _wake(runtime, wakeword, journal)
    try:
        assert runtime.runtime.conversation_id == CONVERSATION
        first_scheduler = runtime._speech
        core.current = OTHER
        await core.publish(binding_changed())
        await journal.wait_until(lambda: journal.count("voice.board.rebound") == 1)

        assert runtime.runtime.conversation_id == OTHER
        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
        assert runtime._speech is not first_scheduler and runtime._speech.conversation_id == OTHER
        assert not run_task.done(), "Voice itself never restarted"
        assert journal.count("voice.background") == 1 and journal.count("voice.active") == 2
        rebinding = journal.of("voice.board.rebinding")[0]["data"]
        assert rebinding == {"previous_conversation_id": CONVERSATION, "conversation_id": OTHER, "drained": True}

        # Une seule conversation parle désormais : la nouvelle.
        await core.publish(speech_envelope("Ancien Board.", kind=SpeechKind.RESULT, created_offset_s=1))
        await core.publish(speech_envelope("Nouveau Board.", kind=SpeechKind.RESULT, conversation_id=OTHER,
                                           created_offset_s=2))
        await wait_for(lambda: "Nouveau Board." in session.texts())
        assert "Ancien Board." not in session.texts()
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_a_binding_change_while_voice_sleeps_is_left_to_the_next_activation(monkeypatch):
    journal = RecordingJournal()
    runtime, _, _, _ = _runtime(monkeypatch, journal=journal)
    runtime.request_board_rebind(OTHER)
    assert await runtime.rebind_board() is False
    assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    assert journal.of("voice.board.rebind_deferred")[0]["data"]["conversation_id"] == OTHER


async def test_a_rebind_never_reopens_over_an_unconfirmed_close(monkeypatch):
    journal = RecordingJournal()
    runtime, wakeword, _, _ = _runtime(monkeypatch, journal=journal)
    core = SessionCore()
    runtime.core = core
    run_task = await _wake(runtime, wakeword, journal)
    try:
        async def stuck_mute(reason=None):  # noqa: ANN001 - la fermeture Live n'est pas confirmée
            runtime.runtime.state = VoiceLifecycleState.ERROR

        runtime.mute = stuck_mute
        runtime.request_board_rebind(OTHER)
        await journal.wait_until(lambda: journal.count("voice.board.rebind_failed") == 1)
        assert journal.of("voice.board.rebind_failed")[0]["data"]["code"] == "voice_rebind_close_pending"
        assert journal.count("voice.active") == 1, "never a second session over the first"
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
