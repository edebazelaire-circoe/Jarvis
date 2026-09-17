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
