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


# -- Preuve locale mesurée pendant la fenêtre (18/09/2026, poste réel) ---------
#
# Le « soutien » exigé le 17/09 ne regardait que `_user_speaking`, c'est-à-dire
# le verrou du VAD du fournisseur — que l'écho de JARVIS tient ouvert bien plus
# longtemps que la fenêtre. La trace de la session 7e3b132c montre des coupures
# confirmées avec un micro à −79, −93 et −103 dBFS, du silence donc, à 0,7 à
# 1,3 s du début de chaque phrase. La preuve est désormais comptée dans la
# capture : des trames réellement « proches », assez nombreuses et assez fortes.


class MeasuredAudio(GuardedAudio):
    """Garde d'écho **et** compteur de trames proches, comme la capture duplex.

    `voiced_frames` avance comme le ferait le détecteur devant une vraie voix ;
    `margin_db` est le dépassement que la trace rapporte.
    """

    def __init__(self, *, margin_db: float = 18.0, **options) -> None:
        super().__init__(**options)
        self.processed = 0
        self.voiced = 0
        self.margin_db = margin_db

    @property
    def near_end_frame_counters(self) -> tuple[int, int]:
        return self.processed, self.voiced

    def near_end_diagnostics(self):  # type: ignore[override]
        return {"mic_db": -28.0, "margin_db": self.margin_db, "latched": True, "guard_open": self.gate_open}


async def _capture(audio: MeasuredAudio, duration_s: float, *, voice_s: float) -> None:
    """Faire tourner la capture `duration_s`, dont `voice_s` de voix réelle.

    Le micro produit toujours ses trames de 10 ms ; seules les premières sont
    jugées « proches ». Une capture muette et une capture arrêtée ne se
    ressemblent que pour qui ne compte pas les deux.
    """

    loop = asyncio.get_running_loop()
    start = loop.time()
    while (elapsed := loop.time() - start) < duration_s:
        await asyncio.sleep(0.01)
        audio.processed += 1
        if elapsed < voice_s:
            audio.voiced += 1


async def _measured_bridge(*, margin_db: float = 18.0, **options):
    audio = MeasuredAudio(margin_db=margin_db, guarded=True, gate_open=False)
    session, journal = ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio, session=session, journal=journal, barge_in_confirm_s=2.0, **options)
    queue: asyncio.Queue = asyncio.Queue()

    async def stream():
        while (item := await queue.get()) is not None:
            yield item

    running = asyncio.create_task(bridge._consume(stream()))
    await queue.put(event("realtime.output_started", output_id="out-1", speech_id="out-1"))
    await queue.put(audio_delta(400, output_id="out-1", speech_id="out-1", item_id="item-1", content_index=0))
    await until(lambda: bridge._playing)
    return bridge, audio, session, journal, queue, running


async def _confirming(bridge, journal, queue, audio) -> None:
    bridge._on_capture_signal(NEAR_END_SIGNAL)
    await until(lambda: journal.count("voice.barge_in_pending") == 1)
    await queue.put(event("realtime.speech_started", item_id="seg-1"))
    await until(lambda: journal.count("voice.barge_in_confirming") == 1)
    assert audio.gains[-1] == bridge.barge_in_duck_gain


async def test_a_short_echo_burst_gives_the_volume_back_without_waiting_for_the_window():
    bridge, audio, session, journal, queue, running = await _measured_bridge(
        barge_in_sustain_s=1.2, barge_in_silence_grace_ms=150, barge_in_min_voiced_ms=350,
    )
    try:
        await _confirming(bridge, journal, queue, audio)
        talking = asyncio.create_task(_capture(audio, 3.0, voice_s=0.08))  # une bouffée, puis plus rien
        await until(lambda: journal.count("voice.barge_in_rejected") == 1)
        rejected = journal.of("voice.barge_in_rejected")[-1]["data"]

        # Le VAD du fournisseur n'a jamais dit « stop » : avant, cela suffisait à couper.
        assert bridge._user_speaking
        assert journal.count("voice.barge_in") == 0
        assert audio.stop_output_calls == 0 and "cancel_output" not in session.calls
        assert audio.gains[-1] == 1.0 and bridge._playing
        assert rejected["code"] == "barge_in_local_voice_gone"
        # Le volume revient bien avant la fin de la fenêtre, pas au bout de 0,6 s.
        assert rejected["ducked_ms"] < 600
        assert rejected["learned"] is True  # bouffée brève : c'était de l'écho
    finally:
        talking.cancel()
        await _finish(queue, running)


async def test_real_sustained_speech_still_cuts_jarvis():
    bridge, audio, session, journal, queue, running = await _measured_bridge(
        barge_in_sustain_s=0.4, barge_in_silence_grace_ms=150, barge_in_min_voiced_ms=250,
    )
    try:
        await _confirming(bridge, journal, queue, audio)
        talking = asyncio.create_task(_capture(audio, 3.0, voice_s=3.0))
        await until(lambda: journal.count("voice.barge_in") == 1)
        talking.cancel()

        assert audio.stop_output_calls == 1 and "cancel_output" in session.calls
        assert journal.count("voice.barge_in_rejected") == 0
    finally:
        await _finish(queue, running)


async def test_speech_that_never_rises_above_the_echo_does_not_cut():
    bridge, audio, session, journal, queue, running = await _measured_bridge(
        margin_db=2.0, barge_in_sustain_s=0.4, barge_in_silence_grace_ms=300,
        barge_in_min_voiced_ms=250, barge_in_min_margin_db=6.0,
    )
    try:
        await _confirming(bridge, journal, queue, audio)
        talking = asyncio.create_task(_capture(audio, 3.0, voice_s=3.0))
        await until(lambda: journal.count("voice.barge_in_rejected") == 1)
        talking.cancel()
        rejected = journal.of("voice.barge_in_rejected")[-1]["data"]

        assert journal.count("voice.barge_in") == 0 and audio.stop_output_calls == 0
        assert rejected["code"] == "barge_in_local_voice_too_weak"
        assert audio.gains[-1] == 1.0
        # Une voix tenue n'est jamais apprise comme de l'écho : le détecteur
        # resterait sourd au locuteur suivant.
        assert rejected["learned"] is False
    finally:
        await _finish(queue, running)


async def test_a_stack_without_local_evidence_keeps_the_previous_decision():
    """Sans capture duplex (piles de test, capture brute), rien n'a changé."""

    bridge, audio, session, journal, queue, running = await _speaking_bridge(barge_in_sustain_s=0.2)
    try:
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await until(lambda: journal.count("voice.barge_in_pending") == 1)
        await queue.put(event("realtime.speech_started", item_id="user-item"))
        await until(lambda: journal.count("voice.barge_in") == 1)
        assert audio.stop_output_calls == 1
    finally:
        await _finish(queue, running)


def test_the_barge_in_thresholds_are_tunable_from_the_environment(monkeypatch):
    from jarvis.runtime import realtime_audio as module

    monkeypatch.setenv("JARVIS_BARGE_IN_SUSTAIN_S", "1,4")  # virgule décimale tolérée
    monkeypatch.setenv("JARVIS_BARGE_IN_MIN_VOICED_MS", "n'importe quoi")
    assert module._env_float("JARVIS_BARGE_IN_SUSTAIN_S", 0.9, minimum=0.0, maximum=5.0) == 1.4
    assert module._env_float("JARVIS_BARGE_IN_MIN_VOICED_MS", 350.0) == 350.0
    monkeypatch.setenv("JARVIS_BARGE_IN_DUCK_GAIN", "42")  # hors bornes
    assert module._env_float("JARVIS_BARGE_IN_DUCK_GAIN", 0.6, minimum=0.05, maximum=1.0) == 0.6


def test_the_defaults_require_a_sustained_and_loud_enough_voice():
    bridge = build_bridge(GuardedAudio())
    assert bridge.barge_in_sustain_s >= 0.9      # une bouffée d'écho est plus brève
    assert bridge.barge_in_duck_gain >= 0.5      # plus doux que les −10,5 dB d'avant
    assert bridge.barge_in_min_voiced_ms >= 250
    assert bridge.barge_in_min_margin_db > 0
