"""Accueil vocal de la première séance (retour utilisateur du 2026-10-29).

Le texte (`jarvis/domain/voice_greeting.py`), sa mise en file par
`SpeechScheduler.greet` (il porte l'intention courante de Core, l'attend au
plus `GREETING_TTL_S`, et se périme si l'utilisateur enchaîne), et la règle
« une fois par processus, sur un réveil » de `PersistentVoiceRuntime.activate`.
"""

from __future__ import annotations

import asyncio

import pytest

import jarvis.runtime.realtime_audio as realtime_audio

from jarvis.domain.v2 import SpeechKind, SpeechProvenance
from jarvis.domain.voice_greeting import GREETING_ONLINE, greeting_text
from jarvis.runtime.speech_scheduler import GREETING_TTL_S, SPEECH_GREETING_DROPPED
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture
from tests.fakes.speech_context import context, source
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION,
    FakeAudio,
    FakeClock,
    FakeCore,
    FakeVoiceSession,
    FakeWakeWord,
    RecordingJournal,
    build_scheduler,
)


def board(title, board_id="board_abc"):
    return {"board": {"board_id": board_id, "title": title}, "active": True}


def test_a_named_board_is_offered_back():
    assert greeting_text(board("Présentation  IAsk")) == "Oui, monsieur. Voulez-vous reprendre « Présentation IAsk » ?"


@pytest.mark.parametrize("payload", [
    None, {}, {"board": None}, board(None), board("   "), board("x" * 81),
    board("Board principal", board_id="default"),
])
def test_without_a_work_board_jarvis_only_says_it_is_online(payload):
    assert greeting_text(payload) == GREETING_ONLINE


def test_the_greeting_carries_the_current_core_intent():
    scheduler = build_scheduler(FakeCore(), FakeVoiceSession())
    scheduler.greet("Oui, monsieur. Je suis en ligne.")
    spoken = scheduler._pop_next()
    assert spoken is not None and spoken.text == "Oui, monsieur. Je suis en ligne."
    assert spoken.kind is SpeechKind.ACK and spoken.provenance is SpeechProvenance.SYSTEM_NOTIFICATION
    assert spoken.source == source() and spoken.correlation_id == source().correlation_id


def test_the_greeting_waits_for_core_to_announce_its_intent():
    scheduler = build_scheduler(FakeCore(), FakeVoiceSession())
    scheduler.update_speech_context(context(CONVERSATION, complete=False))
    scheduler.greet(GREETING_ONLINE)
    assert scheduler._pop_next() is None
    scheduler.update_speech_context(context(CONVERSATION))
    spoken = scheduler._pop_next()
    assert spoken is not None and spoken.text == GREETING_ONLINE


def test_a_greeting_that_core_never_backs_is_dropped_and_said_so():
    clock, journal = FakeClock(), RecordingJournal()
    scheduler = build_scheduler(FakeCore(), FakeVoiceSession(), clock=clock, journal=journal)
    scheduler.update_speech_context(context(CONVERSATION, complete=False))
    scheduler.greet(GREETING_ONLINE)
    clock.advance(GREETING_TTL_S + 1)
    scheduler.update_speech_context(context(CONVERSATION))
    assert scheduler._pop_next() is None
    assert journal.count(SPEECH_GREETING_DROPPED) == 1


def test_a_request_spoken_right_after_the_wake_supersedes_the_greeting():
    scheduler = build_scheduler(FakeCore(), FakeVoiceSession())
    scheduler.greet(GREETING_ONLINE)
    scheduler.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    assert scheduler._pop_next() is None
    assert scheduler.presentation_snapshot()["candidates"][0]["reason"] == "stale_source"


# ---------------------------------------------------------------------------
# Câblage : une fois par processus, sur un réveil
# ---------------------------------------------------------------------------


def _greeting_runtime(monkeypatch, *, journal, greet=True, board_payload=None):
    FakeAudio.instances.clear()
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    core, session, wakeword = FakeCore(), FakeVoiceSession(), FakeWakeWord()
    if board_payload is not None:
        async def active_board():
            return board_payload
        core.active_board = active_board

    async def factory(context):
        del context
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=wakeword, core=core, realtime_factory=factory, active_timeout_s=90.0,
        journal=journal, auto_turn=True, voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
        greet_on_first_wake=greet,
    )
    return runtime, wakeword, session


async def _wake_once(runtime, wakeword, journal, count):
    await wakeword.queue.put("f9")
    await journal.wait_until(lambda: journal.count("audio.start") == count)


async def test_the_first_wake_greets_and_offers_the_active_board(monkeypatch):
    journal = RecordingJournal()
    runtime, wakeword, session = _greeting_runtime(monkeypatch, journal=journal, board_payload=board("Présentation IAsk"))
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake_once(runtime, wakeword, journal, 1)
        await journal.wait_until(lambda: len(session.spoken) == 1)
        assert session.texts() == ["Oui, monsieur. Voulez-vous reprendre « Présentation IAsk » ?"]
        # Rendormi puis réveillé : pas de second accueil.
        await runtime.mute()
        await _wake_once(runtime, wakeword, journal, 2)
        await asyncio.sleep(0.05)
        assert len(session.spoken) == 1
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_without_the_setting_the_wake_stays_silent(monkeypatch):
    journal = RecordingJournal()
    runtime, wakeword, session = _greeting_runtime(monkeypatch, journal=journal, greet=False)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake_once(runtime, wakeword, journal, 1)
        await asyncio.sleep(0.05)
        assert session.spoken == []
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
