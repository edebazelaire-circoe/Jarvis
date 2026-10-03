"""Qui coupe JARVIS quand on lui parle par-dessus : le fournisseur ou ce poste.

Le fil GPT-Live n'émet jamais `speech_started` : en mode « provider », une vraie
voix est rejetée (`barge_in_not_confirmed`) et JARVIS continue. En mode « local »
(défaut), la preuve mesurée localement (voix proche, marge d'énergie) coupe seule.
Même capture duplex réelle, même PCM, un seul paramètre qui change.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceConfigError, VoiceModelRef
from jarvis.runtime.realtime_audio import NEAR_END_SIGNAL
from tests.unit.test_barge_in_while_thinking import _bridge, _consume, _finish, Microphone
from tests.unit.test_voice_duplex import audio_delta, event, mix, noise, silence, tone, until


async def _jarvis_speaks(queue, bridge):
    await queue.put(event("realtime.output_started", output_id="out-1", speech_id="out-1"))
    await queue.put(audio_delta(40, output_id="out-1", speech_id="out-1", item_id="item-1", content_index=0))
    await until(lambda: bridge._playing)


async def _user_talks_over(decider, *, voice: bool):
    bridge, audio, capture, session, journal, *_ = _bridge(barge_in_decider=decider)
    queue, running = await _consume(bridge)
    microphone = Microphone(capture)
    try:
        await _jarvis_speaks(queue, bridge)
        reference = tone(3.0, amplitude=0.3)
        if voice:
            mic = mix(tone(3.0, amplitude=0.02), silence(1.5) + tone(1.5, amplitude=0.4, freq=180.0),
                      noise(3.0, amplitude=0.001))
        else:
            mic = mix(tone(3.0, amplitude=0.02), noise(3.0, amplitude=0.001))
        microphone.play(mic, reference)
        if voice:
            # Le détecteur réel lève lui-même le candidat quand la voix arrive.
            await until(lambda: microphone.signals >= 1, timeout=5.0)
            bridge._on_capture_signal(NEAR_END_SIGNAL)
        else:
            await asyncio.sleep(0.05)
            bridge._on_capture_signal(NEAR_END_SIGNAL)
        # Jamais de `speech_started` : c'est exactement le fil GPT-Live.
        await asyncio.sleep(2.0)
        return journal, audio, bridge
    finally:
        await _finish(queue, running, microphone)


async def test_local_decider_cuts_on_a_real_voice_without_any_provider_event():
    journal, audio, _ = await _user_talks_over("local", voice=True)
    assert journal.count("voice.barge_in") == 1, journal.of("voice.barge_in_rejected")
    assert audio.stop_output_calls >= 1
    assert journal.of("voice.barge_in_confirming")[0]["data"]["decider"] == "local"


async def test_provider_decider_keeps_waiting_for_an_event_that_never_comes():
    journal, audio, _ = await _user_talks_over("provider", voice=True)
    assert journal.count("voice.barge_in") == 0
    assert journal.of("voice.barge_in_rejected")[-1]["data"]["code"] == "barge_in_not_confirmed"
    assert audio.stop_output_calls == 0


async def test_local_decider_does_not_cut_on_jarvis_own_echo():
    journal, audio, _ = await _user_talks_over("local", voice=False)
    assert journal.count("voice.barge_in") == 0
    assert audio.stop_output_calls == 0
    assert audio.gains[-1] == 1.0 if audio.gains else True


async def test_provider_speech_started_does_not_cut_in_local_mode():
    bridge, audio, capture, session, journal, *_ = _bridge(barge_in_decider="local")
    queue, running = await _consume(bridge)
    microphone = Microphone(capture)
    try:
        await _jarvis_speaks(queue, bridge)
        microphone.play(mix(tone(3.0, amplitude=0.02), noise(3.0, amplitude=0.001)), tone(3.0, amplitude=0.3))
        await asyncio.sleep(0.05)
        await queue.put(event("realtime.speech_started", item_id="echo"))
        await asyncio.sleep(0.5)
        assert journal.count("voice.barge_in") == 0
    finally:
        await _finish(queue, running, microphone)


def test_config_default_is_local_and_validates():
    ref = VoiceModelRef("openai", "gpt-live-1")
    assert DuplexVoiceConfig(ref).barge_in_decider == "local"
    assert DuplexVoiceConfig(ref, barge_in_decider="provider").barge_in_decider == "provider"
    with pytest.raises(VoiceConfigError):
        DuplexVoiceConfig(ref, barge_in_decider="nobody")
