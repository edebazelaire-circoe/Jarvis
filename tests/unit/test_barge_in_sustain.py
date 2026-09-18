"""Barge-in en salle ouverte : l'écho ne coupe plus JARVIS (17/09/2026).

Trace réelle, session b2fa1757 : un candidat acoustique né de l'écho ouvrait la
garde, le VAD d'OpenAI entendait la voix de JARVIS et « confirmait » en moins
d'une seconde. JARVIS se coupait lui-même ; le segment suivant ne contenait que
« Merci. » ou rien. Une bouffée d'écho est brève, une vraie interruption dure :
la confirmation baisse la voix, et la coupure attend `barge_in_sustain_s`.
"""
from __future__ import annotations

import asyncio

from jarvis.runtime.realtime_audio import NEAR_END_SIGNAL
from tests.unit.test_voice_duplex import (
    ControllableSession, GuardedAudio, RecordingJournal, audio_delta, build_bridge, event, until,
)


async def _speaking_bridge(**options):
    audio = GuardedAudio(guarded=True, gate_open=False)
    session, journal = ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio, session=session, journal=journal, barge_in_confirm_s=0.8, **options)
    queue: asyncio.Queue = asyncio.Queue()

    async def stream():
        while (item := await queue.get()) is not None:
            yield item

    running = asyncio.create_task(bridge._consume(stream()))
    await queue.put(event("realtime.output_started", output_id="out-1", speech_id="out-1"))
    await queue.put(audio_delta(40, output_id="out-1", speech_id="out-1", item_id="item-1", content_index=0))
    await until(lambda: bridge._playing)
    return bridge, audio, session, journal, queue, running


async def _finish(queue, running):
    await queue.put(None)
    await asyncio.wait_for(running, timeout=2.0)


async def test_an_echo_burst_confirmed_by_the_provider_no_longer_cuts_jarvis():
    bridge, audio, session, journal, queue, running = await _speaking_bridge(barge_in_sustain_s=0.4)
    try:
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await until(lambda: journal.count("voice.barge_in_pending") == 1)
        await queue.put(event("realtime.speech_started", item_id="echo-item"))
        await until(lambda: journal.count("voice.barge_in_confirming") == 1)
        # Entendu tout de suite : la voix baisse avant toute preuve.
        assert audio.gains[-1] == bridge.barge_in_duck_gain
        await queue.put(event("realtime.speech_stopped", item_id="echo-item"))
        await until(lambda: journal.count("voice.barge_in_rejected") == 1)
        await asyncio.sleep(0.6)  # au-delà du délai de confirmation et du candidat

        assert journal.count("voice.barge_in") == 0
        assert audio.stop_output_calls == 0 and "cancel_output" not in session.calls
        assert audio.gains[-1] == 1.0 and bridge._playing
        assert journal.of("voice.barge_in_rejected")[-1]["data"]["code"] == "barge_in_speech_too_short"
    finally:
        await _finish(queue, running)


async def test_sustained_speech_still_interrupts_after_ducking():
    bridge, audio, session, journal, queue, running = await _speaking_bridge(barge_in_sustain_s=0.2)
    try:
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await until(lambda: journal.count("voice.barge_in_pending") == 1)
        await queue.put(event("realtime.speech_started", item_id="user-item"))
        await until(lambda: journal.count("voice.barge_in_confirming") == 1)
        assert journal.count("voice.barge_in") == 0 and audio.gains[-1] == bridge.barge_in_duck_gain
        await until(lambda: journal.count("voice.barge_in") == 1)

        assert audio.stop_output_calls == 1 and "cancel_output" in session.calls
        assert journal.count("voice.barge_in_rejected") == 0
    finally:
        await _finish(queue, running)


async def test_provider_speech_before_the_local_candidate_also_needs_to_last():
    bridge, audio, session, journal, queue, running = await _speaking_bridge(barge_in_sustain_s=0.3)
    try:
        await queue.put(event("realtime.speech_started", item_id="echo-item"))
        await until(lambda: bridge._user_speaking)
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await until(lambda: journal.count("voice.barge_in_confirming") == 1)
        await queue.put(event("realtime.speech_stopped", item_id="echo-item"))
        await until(lambda: journal.count("voice.barge_in_rejected") == 1)
        await asyncio.sleep(0.4)
        assert journal.count("voice.barge_in") == 0 and audio.stop_output_calls == 0
    finally:
        await _finish(queue, running)


# -- Confirmation tardive du fournisseur (17/09/2026, session e95f4ae6) ---------
#
# Pendant qu'il parlait par-dessus JARVIS, l'utilisateur a ouvert cinq candidats
# en douze secondes : aucun confirmé dans les 0,8 s, et le `speech_started`
# arrivé 140 ms après le dernier a été ignoré, garde fermée. Chaque rejet
# apprenait en plus sa voix comme de l'écho. Mesuré contre le vrai Realtime,
# avec le même motif de garde : confirmation entre 225 et 818 ms.


class LearningAudio(GuardedAudio):
    def __init__(self, **options) -> None:
        super().__init__(**options)
        self.learns: list[bool] = []

    def release_near_end(self, *, learn: bool = True) -> None:  # type: ignore[override]
        self.released += 1
        self.learns.append(learn)


async def _learning_bridge(**options):
    audio = LearningAudio(guarded=True, gate_open=False)
    session, journal = ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio, session=session, journal=journal, **options)
    queue: asyncio.Queue = asyncio.Queue()

    async def stream():
        while (item := await queue.get()) is not None:
            yield item

    running = asyncio.create_task(bridge._consume(stream()))
    await queue.put(event("realtime.output_started", output_id="out-1", speech_id="out-1"))
    await queue.put(audio_delta(400, output_id="out-1", speech_id="out-1", item_id="item-1", content_index=0))
    await until(lambda: bridge._playing)
    return bridge, audio, session, journal, queue, running


def test_the_default_confirmation_window_covers_the_measured_provider_latency():
    bridge = build_bridge(GuardedAudio())
    assert bridge.barge_in_confirm_s >= 1.2


async def test_a_confirmation_just_after_the_window_still_interrupts():
    bridge, audio, session, journal, queue, running = await _learning_bridge(barge_in_confirm_s=0.1, barge_in_sustain_s=0.1)
    try:
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await until(lambda: journal.count("voice.barge_in_rejected") == 1)
        await queue.put(event("realtime.speech_started", item_id="user-item"))
        await until(lambda: journal.count("voice.barge_in") == 1)

        assert journal.count("voice.barge_in_late_confirmation") == 1
        assert journal.count("voice.barge_in_ignored") == 0
        assert audio.stop_output_calls == 1
    finally:
        await _finish(queue, running)


async def test_a_confirmation_long_after_the_window_is_still_ignored():
    bridge, audio, session, journal, queue, running = await _learning_bridge(barge_in_confirm_s=0.05, barge_in_sustain_s=0.05)
    bridge.BARGE_IN_LATE_CONFIRM_S = 0.1
    try:
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await until(lambda: journal.count("voice.barge_in_rejected") == 1)
        await asyncio.sleep(0.3)
        await queue.put(event("realtime.speech_started", item_id="echo-item"))
        await until(lambda: journal.count("voice.barge_in_ignored") == 1)
        await asyncio.sleep(0.2)
        assert journal.count("voice.barge_in") == 0 and audio.stop_output_calls == 0
    finally:
        await _finish(queue, running)


async def test_only_repeated_rejections_learn_the_voice_as_echo():
    bridge, audio, session, journal, queue, running = await _learning_bridge(barge_in_confirm_s=0.05)
    try:
        for expected in (1, 2, 3):
            bridge._on_capture_signal(NEAR_END_SIGNAL)
            await until(lambda: journal.count("voice.barge_in_rejected") == expected)
        assert audio.learns == [False, True, True]
    finally:
        await _finish(queue, running)


def test_a_release_without_learning_keeps_the_coupling():
    from jarvis.audio.duplex import NearEndDetector

    detector = NearEndDetector(initial_coupling_db=-30.0)
    detector._recent_excess.extend([5.0, 8.0])
    detector.latched = True
    detector.release(learn=False)
    assert detector.coupling_db == -30.0 and not detector.latched

    detector._recent_excess.extend([5.0, 8.0])
    detector.release()
    assert detector.coupling_db == 8.0 - detector.echo_margin_db + 2.0
