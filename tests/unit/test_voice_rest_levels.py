"""ACTIVE -> IDLE -> SLEEP (retour utilisateur du 2026-10-29, `docs/voice-lifecycle.md`).

- 10 s sans parole : la séance GPT-Live est fermée (IDLE), le micro local reste ouvert ;
- en IDLE la parole de l'utilisateur rouvre une séance avec la parole tampon (pré-roll), et
  « Hey Jarvis » passe toujours devant ;
- 30 s d'inactivité totale : SLEEP (gris), la parole ne rouvre plus ;
- la fin d'une tâche **entière** rouvre une séance et se dit, depuis IDLE comme depuis SLEEP ;
  une sous-tâche, un accusé ou une progression ne réveillent rien ;
- l'accueil du premier réveil marche toujours.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import numpy as np
import pytest

import jarvis.runtime.realtime_audio as realtime_audio
import jarvis.runtime.voice_v2 as voice_v2

from jarvis.adapters.wakeword_own_stream import SPEECH_LABEL, is_speech_label
from jarvis.audio.idle_speech import MIN_VOICED, IdleSpeechDetector, VerifierOwnerJudge
from jarvis.domain.v2 import SpeechKind, VoiceLifecycleState, utc_now
from jarvis.domain.voice_rest import RestLevel, is_task_completion_speech
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture
from tests.unit.test_v2_speech_scheduler import (
    FakeAudio,
    FakeClock,
    FakeCore,
    FakeVoiceSession,
    FakeWakeWord,
    RecordingJournal,
    speech_envelope,
)

IDLE_AFTER_S = 10.0
SLEEP_AFTER_S = 30.0


class RestWakeWord(FakeWakeWord):
    """Détecteur de repos de test : retient l'armement de la parole d'IDLE et rend un pré-roll."""

    def __init__(self) -> None:
        super().__init__()
        self.listening: list[bool] = []
        self.preroll: tuple[bytes, int] | None = None
        self.discarded = 0

    def set_speech_listening(self, enabled: bool) -> None:
        self.listening.append(enabled)

    def take_speech_preroll(self):  # noqa: ANN201
        taken, self.preroll = self.preroll, None
        if taken is None:
            self.discarded += 1
        return taken


def _runtime(monkeypatch, *, journal, clock, greet=False):
    FakeAudio.instances.clear()
    clock.value = utc_now()  # `ORIGIN` date de l'import : un accueil daté après lui serait déjà périmé
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    monkeypatch.setattr(voice_v2, "SPEECH_WAKE_GRACE_S", 0.05)
    core, session, wakeword = FakeCore(), FakeVoiceSession(), RestWakeWord()

    async def active_board():
        return {}

    core.active_board = active_board

    async def factory(context):
        del context
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=wakeword, core=core, realtime_factory=factory, active_timeout_s=IDLE_AFTER_S,
        sleep_timeout_s=SLEEP_AFTER_S, clock=clock, journal=journal, auto_turn=True,
        voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN, greet_on_first_wake=greet,
    )
    return runtime, wakeword, core, session


async def _stop(run_task):
    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)


async def _wake(runtime, wakeword, journal, label="f9", count=1):
    await wakeword.queue.put(label)
    await journal.wait_until(lambda: journal.count("audio.start") == count)


async def _go_idle(runtime, clock):
    clock.advance(IDLE_AFTER_S + 1)
    assert await runtime.check_timeout() is True
    assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND


async def _sleep_for_a_while(seconds=0.2):
    await asyncio.sleep(seconds)


# ---------------------------------------------------------------------------
# ACTIVE -> IDLE
# ---------------------------------------------------------------------------


async def test_the_voice_starts_asleep_and_gray(monkeypatch):
    runtime, *_ = _runtime(monkeypatch, journal=RecordingJournal(), clock=FakeClock())
    assert runtime.rest_level is RestLevel.SLEEP
    assert runtime._last_displayed == "sleep"  # noqa: SLF001


async def test_ten_seconds_without_speech_close_the_session_and_leave_the_microphone_to_the_wake_listener(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        clock.advance(IDLE_AFTER_S - 1)
        assert await runtime.check_timeout() is False and runtime.runtime.state is VoiceLifecycleState.ACTIVE
        clock.advance(2)
        assert await runtime.check_timeout() is True
        assert session.closed is True
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert runtime.rest_level is RestLevel.IDLE
        assert runtime._last_displayed == "idle"  # noqa: SLF001
        assert wakeword.listening[-1] is True  # la parole de l'utilisateur est écoutée en local
        assert journal.count("voice.idle") == 1
    finally:
        await _stop(run_task)


async def test_a_user_mute_goes_straight_to_sleep(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        await runtime.mute()
        assert runtime.rest_level is RestLevel.SLEEP
        assert wakeword.listening[-1] is False
    finally:
        await _stop(run_task)


# ---------------------------------------------------------------------------
# IDLE : la parole rouvre, avec le pré-roll ; le mot d'éveil passe devant
# ---------------------------------------------------------------------------


async def test_speech_in_idle_reopens_the_session_with_the_buffered_speech_and_does_not_postpone_sleep(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock, greet=True)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        await journal.wait_until(lambda: len(session.spoken) == 1)  # l'accueil du premier réveil
        await _go_idle(runtime, clock)
        engaged_before = runtime._engaged_at  # noqa: SLF001
        clock.advance(3)
        wakeword.preroll = (b"\x05\x00" * 16000 * 2, 16000)  # 2 s de parole à 16 kHz
        await wakeword.queue.put(SPEECH_LABEL)
        await journal.wait_until(lambda: journal.count("audio.start") == 2)
        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
        # La parole tampon est en tête de la file d'envoi, rééchantillonnée à 24 kHz (2 s = 96000 octets).
        assert abs(FakeAudio.instances[-1].primed_bytes - 2 * 24000 * 2) <= 8
        assert journal.count("voice.idle.preroll") == 1
        assert runtime._engaged_at == engaged_before  # noqa: SLF001 - une parole ambiante ne repousse pas SLEEP
        assert wakeword.listening[-1] is False  # séance ouverte : le détecteur de parole se tait
        assert len(session.spoken) == 1  # pas de second accueil
    finally:
        await _stop(run_task)


async def test_the_wake_word_always_wins_over_speech(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        await _go_idle(runtime, clock)
        wakeword.preroll = (b"\x05\x00" * 16000, 16000)
        await wakeword.queue.put(SPEECH_LABEL)
        await wakeword.queue.put("jarvis")  # « Hey Jarvis » finit de se dire dans le délai de grâce
        await journal.wait_until(lambda: journal.count("audio.start") == 2)
        assert journal.count("voice.idle.speech") == 0
        assert journal.of("voice.wake")[-1]["data"]["source"] == "wake_word"
        assert FakeAudio.instances[-1].primed_bytes == 0  # le mot d'éveil n'amorce aucun pré-roll
    finally:
        await _stop(run_task)


# ---------------------------------------------------------------------------
# IDLE -> SLEEP : 30 s au total, la parole ne rouvre plus
# ---------------------------------------------------------------------------


async def test_thirty_seconds_of_inactivity_put_the_voice_to_sleep_and_speech_no_longer_reopens(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        await _go_idle(runtime, clock)
        clock.advance(SLEEP_AFTER_S - IDLE_AFTER_S - 2)  # 29 s au total
        assert await runtime.check_timeout() is False
        assert runtime.rest_level is RestLevel.IDLE
        clock.advance(3)  # 32 s depuis le dernier engagement
        await runtime.check_timeout()
        assert runtime.rest_level is RestLevel.SLEEP
        assert runtime._last_displayed == "sleep"  # noqa: SLF001
        assert wakeword.listening[-1] is False
        assert journal.count("voice.sleep") == 1

        wakeword.preroll = (b"\x05\x00" * 16000, 16000)
        await wakeword.queue.put(SPEECH_LABEL)
        await _sleep_for_a_while()
        assert journal.count("audio.start") == 1  # rien ne s'est rouvert
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert wakeword.preroll is None  # la parole entendue a été jetée

        await _wake(runtime, wakeword, journal, count=2)  # « Hey Jarvis » / F9 rouvre toujours
    finally:
        await _stop(run_task)


async def test_a_session_closed_after_thirty_seconds_of_activity_rests_directly_in_sleep(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        clock.advance(SLEEP_AFTER_S + 5)
        assert await runtime.check_timeout() is True
        assert runtime.rest_level is RestLevel.SLEEP
    finally:
        await _stop(run_task)


# ---------------------------------------------------------------------------
# Fin de tâche entière : réveille et parle ; le reste ne réveille rien
# ---------------------------------------------------------------------------


async def _asleep(monkeypatch, journal, clock, greet=False):
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock, greet=greet)
    run_task = asyncio.create_task(runtime.run())
    await _wake(runtime, wakeword, journal)
    clock.advance(SLEEP_AFTER_S + 5)
    assert await runtime.check_timeout() is True
    assert runtime.rest_level is RestLevel.SLEEP
    await journal.wait_until(lambda: core.subscriptions >= 1)
    return runtime, wakeword, core, session, run_task


async def test_the_end_of_a_whole_task_wakes_the_voice_from_sleep_and_is_said(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session, run_task = await _asleep(monkeypatch, journal, clock)
    try:
        before = clock.now()
        await core.publish(speech_envelope("La refonte est terminée.", kind=SpeechKind.RESULT, work_id="work-1"))
        await journal.wait_until(lambda: journal.count("audio.start") == 2)
        await journal.wait_until(lambda: "La refonte est terminée." in session.texts())
        assert journal.count("voice.completion.wake") == 1
        assert runtime._engaged_at >= before  # noqa: SLF001 - les minuteries normales repartent
        # Puis les minuteries normales : 10 s plus tard la séance se referme en IDLE.
        clock.advance(IDLE_AFTER_S + 1)
        assert await runtime.check_timeout() is True
        assert runtime.rest_level is RestLevel.IDLE
    finally:
        await _stop(run_task)


async def test_the_end_of_a_whole_task_wakes_the_voice_from_idle_too(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        await _go_idle(runtime, clock)
        await journal.wait_until(lambda: core.subscriptions >= 1)
        await core.publish(speech_envelope("Le rapport est prêt.", kind=SpeechKind.RESULT))
        await journal.wait_until(lambda: journal.count("audio.start") == 2)
        await journal.wait_until(lambda: "Le rapport est prêt." in session.texts())
    finally:
        await _stop(run_task)


@pytest.mark.parametrize("kind", [SpeechKind.PROGRESS, SpeechKind.ACK])
async def test_a_progress_or_an_acknowledgement_never_wakes_the_voice(monkeypatch, kind):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session, run_task = await _asleep(monkeypatch, journal, clock)
    try:
        await core.publish(speech_envelope("J'avance sur la sous-tâche.", kind=kind))
        await _sleep_for_a_while()
        assert journal.count("audio.start") == 1
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    finally:
        await _stop(run_task)


async def test_a_result_arriving_after_a_user_mute_does_not_wake_the_voice(monkeypatch):
    """Décision 33 : ce que l'utilisateur a coupé lui-même ne se rattrape pas par une reprise surprise."""

    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        await runtime.mute()
        await journal.wait_until(lambda: core.subscriptions >= 1)
        await core.publish(speech_envelope("Fini.", kind=SpeechKind.RESULT))
        await _sleep_for_a_while()
        assert journal.count("audio.start") == 1
    finally:
        await _stop(run_task)


def test_only_a_durable_brain_result_or_error_is_a_task_completion():
    def payload(**fields):
        return {"kind": "result", "text": "Fini.", "provenance": "brain.speech", **fields}

    assert is_task_completion_speech("brain.speech.requested", payload())
    assert is_task_completion_speech("brain.speech.requested", payload(kind="error"))
    for kind in ("ack", "progress", "question"):
        assert not is_task_completion_speech("brain.speech.requested", payload(kind=kind))
    assert not is_task_completion_speech("brain.speech.requested", payload(provenance="system.notification"))
    assert not is_task_completion_speech("brain.speech.requested", payload(text="  "))
    assert not is_task_completion_speech("brain.turn.accepted", payload())


# ---------------------------------------------------------------------------
# L'accueil du premier réveil
# ---------------------------------------------------------------------------


async def test_the_first_wake_still_greets_from_the_initial_sleep(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock, greet=True)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        await journal.wait_until(lambda: len(session.spoken) == 1)
        assert session.texts() == ["Oui, monsieur. Je suis en ligne."]
    finally:
        await _stop(run_task)


# ---------------------------------------------------------------------------
# Détecteur de parole d'IDLE
# ---------------------------------------------------------------------------

FRAME = 1280  # 80 ms à 16 kHz


def _frame(amplitude: int) -> bytes:
    rng = np.random.default_rng(amplitude)
    return (rng.standard_normal(FRAME) * amplitude).astype(np.int16).tobytes()


QUIET, LOUD = _frame(8), _frame(4000)


def _armed(**kwargs) -> IdleSpeechDetector:
    detector = IdleSpeechDetector(**kwargs)
    detector.set_enabled(True)
    for _ in range(15):  # le plancher adaptatif apprend la pièce
        detector.feed(QUIET)
    return detector


def test_quiet_room_and_clicks_are_not_speech_but_sustained_voice_is():
    detector = _armed()
    assert not any(detector.feed(QUIET) for _ in range(20))
    assert not detector.feed(LOUD)  # un claquement isolé
    assert not any(detector.feed(QUIET) for _ in range(10))
    fired = [detector.feed(LOUD) for _ in range(MIN_VOICED + 2)]
    assert fired.count(True) == 1  # une seule fois


def test_the_preroll_keeps_the_lead_in_and_what_follows_then_disarms():
    detector = _armed()
    for _ in range(MIN_VOICED + 1):
        detector.feed(LOUD)
    for _ in range(5):
        detector.feed(LOUD)  # la parole continue pendant que la séance se rouvre
    pcm, rate = detector.take_preroll()
    assert rate == 16000 and len(pcm) > (MIN_VOICED + 5) * FRAME * 2
    assert detector.take_preroll()[0] == b""
    assert detector.enabled is False
    assert not detector.feed(LOUD)  # désarmé : plus rien ne se détecte ni ne se garde


def test_a_disarmed_detector_keeps_nothing():
    detector = IdleSpeechDetector()
    assert not any(detector.feed(LOUD) for _ in range(20))
    assert detector.take_preroll()[0] == b""


class _Verifier:
    def __init__(self, owner: bool) -> None:
        self.owner, self.fed = owner, 0

    def reset(self) -> None:
        self.fed = 0

    def process(self, frame: bytes, rate: int):  # noqa: ANN201
        from jarvis.domain.speaker import SpeakerVerification, VerificationStatus

        self.fed += 1
        if self.fed < 3:
            return SpeakerVerification(status=VerificationStatus.INSUFFICIENT_AUDIO, engine="test")
        return SpeakerVerification(status=VerificationStatus.OK, engine="test", owner_score=0.9 if self.owner else 0.1,
                                   owner_detected=self.owner, evidence_ms=240)


def test_solo_owner_only_the_owner_voice_confirms_speech():
    owner = _armed(judge=VerifierOwnerJudge(_Verifier(True)))
    assert any(owner.feed(LOUD) for _ in range(MIN_VOICED + 4))
    stranger = _armed(judge=VerifierOwnerJudge(_Verifier(False)))
    assert not any(stranger.feed(LOUD) for _ in range(MIN_VOICED + 12))
    assert stranger.abandoned_count >= 1 and stranger.confirmed_count == 0


def test_speech_label_is_not_a_wake_word():
    assert is_speech_label(SPEECH_LABEL) and not is_speech_label("jarvis") and not is_speech_label("f9")


# ---------------------------------------------------------------------------
# Le détecteur de mot d'éveil à flux propre porte la parole d'IDLE (micro réel remplacé par un faux flux)
# ---------------------------------------------------------------------------


class _Engine:
    sample_rate, frame_length = 16000, FRAME

    def __init__(self, hit_on_loud: bool = False) -> None:
        self.hit_on_loud, self.deleted = hit_on_loud, False

    def process(self, frame):  # noqa: ANN001, ANN201
        return 0 if self.hit_on_loud and max(frame) > 1000 else None

    def delete(self) -> None:
        self.deleted = True


def _install_fake_microphone(monkeypatch):
    import sys

    streams = []

    class FakeStream:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.callback = kwargs["callback"]
            streams.append(self)

        def start(self) -> None: ...
        def stop(self) -> None: ...
        def close(self) -> None: ...

    class FakeSoundDevice:
        RawInputStream = FakeStream

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    return streams


async def _speak(stream, frames):
    for frame in frames:
        stream.callback(frame, FRAME, None, None)
        await asyncio.sleep(0.02)


async def test_speech_heard_by_the_idle_microphone_is_announced_and_buffered(monkeypatch):
    from jarvis.adapters.wakeword_own_stream import OwnStreamWakeWordBackend

    streams = _install_fake_microphone(monkeypatch)
    detector = IdleSpeechDetector()
    wake = OwnStreamWakeWordBackend(engine_factory=_Engine, speech_detector=detector)
    await wake.start()
    try:
        wake.set_speech_listening(True)
        detections = wake.detections()
        waiting = asyncio.ensure_future(anext(detections))
        await _speak(streams[0], [QUIET] * 15 + [LOUD] * (MIN_VOICED + 2))
        assert await asyncio.wait_for(waiting, 2.0) == SPEECH_LABEL
        await _speak(streams[0], [LOUD] * 3)  # la parole continue pendant la réouverture
        await wake.suspend_for_active_session()
        pcm, rate = wake.take_speech_preroll()
        assert rate == 16000 and len(pcm) >= (MIN_VOICED + 5) * FRAME * 2
        assert wake.take_speech_preroll() is None  # une seule fois
    finally:
        await wake.close()


async def test_a_disarmed_idle_microphone_announces_nothing_and_the_wake_word_still_wins(monkeypatch):
    from jarvis.adapters.wakeword_own_stream import OwnStreamWakeWordBackend

    streams = _install_fake_microphone(monkeypatch)
    detector = IdleSpeechDetector()
    wake = OwnStreamWakeWordBackend(engine_factory=lambda: _Engine(hit_on_loud=True), keyword="hey_jarvis",
                                    speech_detector=detector)
    await wake.start()
    try:
        # SLEEP : désarmé, la parole ne se tampone pas ; le mot d'éveil, lui, est reconnu.
        wake.set_speech_listening(False)
        detections = wake.detections()
        waiting = asyncio.ensure_future(anext(detections))
        await _speak(streams[0], [QUIET] * 15 + [LOUD] * 3)
        assert await asyncio.wait_for(waiting, 2.0) == "hey_jarvis"
        assert wake.take_speech_preroll() is None
        # IDLE : armé, une trame que le mot d'éveil reconnaît n'est jamais comptée comme parole.
        wake.set_speech_listening(True)
        await _speak(streams[0], [QUIET] * 15 + [LOUD] * 3)
        assert await asyncio.wait_for(anext(detections), 2.0) == "hey_jarvis"
        assert detector.confirmed_count == 0
    finally:
        await wake.close()


async def test_an_automatic_reopening_that_fails_leaves_the_voice_resting_instead_of_crashing_it(monkeypatch):
    journal, clock = RecordingJournal(), FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock)
    run_task = asyncio.create_task(runtime.run())
    try:
        await _wake(runtime, wakeword, journal)
        await _go_idle(runtime, clock)

        async def unreachable(context):
            raise ConnectionError("fournisseur injoignable")

        runtime.realtime_factory = unreachable
        wakeword.preroll = (b"\x05\x00" * 16000, 16000)
        await wakeword.queue.put(SPEECH_LABEL)
        await journal.wait_until(lambda: journal.count("voice.unattended_activation_failed") == 1)
        assert not run_task.done()  # Voice vit toujours : le lanceur n'a pas à la relancer
        assert runtime.runtime.state is not VoiceLifecycleState.ACTIVE
    finally:
        await _stop(run_task)
