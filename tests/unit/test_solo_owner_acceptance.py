"""Tâche 14 — recette automatisée Solo Owner, de la capture au fournisseur.

Les fichiers des tâches 04 à 08 prouvent chaque pièce séparément (capture,
état du propriétaire, barge-in, rejeu, porte d'entrée, refus). Ce fichier
ferme les trois trous relevés par la matrice d'acceptation de la tâche 14, en
faisant tourner **ensemble** la capture duplex réelle, le fil du vérificateur
(`SpeakerVerificationWorker` avec un vérificateur scripté) et le pont de
conversation :

1. une conversation de collègues pendant que JARVIS parle : ni baisse de
   volume, ni coupure, ni un octet vers le fournisseur — puis le propriétaire
   enchaîne sans silence : arrêt local avant toute réponse du fournisseur et
   préfixe rejoué une seule fois, jamais depuis le début du collègue ;
2. JARVIS silencieux : une autre voix ne devient ni tour, ni activité utile ;
   le propriétaire, lui, ouvre le flux et son tour réarme le délai ;
3. retour arrière `open_room` : avec un vérificateur branché en ombre, ce que
   le fournisseur reçoit et ce que le pont décide sont identiques, octet pour
   octet, à la chaîne d'avant le handoff (sans vérificateur).

Aucun audio ni empreinte n'est versionné : tout est synthétisé ici.
"""

from __future__ import annotations

import asyncio
import math

import numpy as np

from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
from jarvis.audio.duplex import CaptureProcessor
from jarvis.audio.speaker_shadow import OWNER_INPUT_DROPPED, SpeakerVerificationWorker
from jarvis.domain.speaker import SpeakerVerification, VerificationStatus
from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.runtime.realtime_audio import (
    BARGE_IN_OWNER_CONFIRMED_KIND,
    OWNER_REPLAY_KIND,
    BargeInAuthority,
)
from tests.unit.test_owner_barge_in import (
    ControllableSession,
    Live,
    ManualClock,
    RecordingAudio,
    RecordingJournal,
    build_bridge,
    event,
    jarvis_speaking,
    until,
)
from tests.unit.test_owner_input_gate import QuietAudio, solo_capture, solo_runtime
from tests.unit.test_owner_replay import sent
from tests.unit.test_v2_continuous_live import FakeClock

RATE = 24000
TIMEOUT_S = 2.0


# --------------------------------------------------------------------------
# Outillage : voix de synthèse et capture pilotée comme PortAudio


def tone(seconds: float, *, amplitude: float, freq: float = 220.0) -> bytes:
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * np.sin(2 * math.pi * freq * t) * 32767).astype(np.int16).tobytes()


def mix(*parts: bytes) -> bytes:
    arrays = [np.frombuffer(part, dtype=np.int16).astype(np.int32) for part in parts]
    total = np.zeros(max(len(array) for array in arrays), dtype=np.int32)
    for array in arrays:
        total[: len(array)] += array
    return total.clip(-32768, 32767).astype(np.int16).tobytes()


class PassThroughCanceller:
    """Annuleur neutre : l'écho résiduel du mélange tient lieu de fuite."""

    def process_render(self, frame: bytes) -> None:
        del frame

    def process_capture(self, frame: bytes) -> bytes:
        return frame


def verdict(score: float, *, detected: bool, evidence_ms: int) -> SpeakerVerification:
    return SpeakerVerification(
        status=VerificationStatus.OK,
        engine="fake-speaker/1",
        owner_score=score,
        owner_detected=detected,
        evidence_ms=evidence_ms,
        profile_id="owner-test",
    )


def run_capture(processor: CaptureProcessor, mic: bytes, reference: bytes, out: bytearray | None = None) -> list[str]:
    """Blocs de 50 ms, référence en avance : la cadence de `SoundDeviceRealtimeAudio`.

    Rend les signaux de la capture, que l'appelant relaie au pont comme
    `_deliver_capture` le fait en production.
    """

    block, pushed = 1200 * 2, 0
    signals: list[str] = []
    for offset in range(0, len(mic), block):
        while pushed < min(len(reference), offset + 4800 * 2):
            processor.push_reference(reference[pushed : pushed + 4800])
            pushed += 4800
        processed, emitted = processor.process(mic[offset : offset + block])
        signals += list(emitted)
        if out is not None:
            out += processed
    return signals


def owner_worker(script) -> SpeakerVerificationWorker:  # noqa: ANN001
    return SpeakerVerificationWorker(
        ScriptedSpeakerVerifier(script),
        sample_rate=RATE,
        max_pending_ms=60_000,
        enforce=True,
    )


# --------------------------------------------------------------------------
# 1. JARVIS parle : une conversation voisine ne le touche pas, le propriétaire si


async def test_a_colleague_talks_through_the_answer_then_the_owner_interrupts_without_leaking_him():
    """Chaîne complète : capture réelle + fil du vérificateur + pont, JARVIS audible."""

    stranger = verdict(0.2, detected=False, evidence_ms=1500)
    owner = verdict(0.95, detected=True, evidence_ms=500)
    worker = owner_worker([stranger] * 20 + [owner] * 40)
    processor = CaptureProcessor(
        capture_rate=RATE,
        render_rate=RATE,
        canceller=PassThroughCanceller(),
        observer=worker,
        owner_buffer_ms=2500,
    )
    calls: list[str] = []
    audio, journal = RecordingAudio(calls), RecordingJournal()
    audio.capture = processor
    session = ControllableSession(calls)
    bridge = build_bridge(audio, source=worker, session=session, journal=journal, authority=BargeInAuthority.OWNER)
    echo = tone(4.0, amplitude=0.02)
    reference = tone(4.0, amplitude=0.3)
    colleague = mix(echo[: RATE * 2 * 2], tone(2.0, amplitude=0.4, freq=180.0))
    forwarded = bytearray()
    try:
        async with Live(bridge) as live:
            await live.send(*jarvis_speaking(chunks=3))
            # Deux secondes de conversation voisine pendant la réponse.
            await asyncio.to_thread(run_capture, processor, colleague, reference[: RATE * 2 * 2], forwarded)
            assert await asyncio.to_thread(worker.flush, TIMEOUT_S)
            await live.idle()
            assert audio.gains == []  # D04 : pas de baisse de volume spéculative
            assert audio.stop_output_calls == 0 and calls == []
            assert not any(forwarded)  # rien du collègue n'a atteint le fournisseur
            assert journal.of(BARGE_IN_OWNER_CONFIRMED_KIND) == []

            # Le propriétaire enchaîne, sans silence : reconnu, il coupe.
            after = mix(echo[RATE * 2 * 2 :], tone(2.0, amplitude=0.4, freq=180.0))
            signals = await asyncio.to_thread(run_capture, processor, after, reference[RATE * 2 * 2 :], forwarded)
            assert await asyncio.to_thread(worker.flush, TIMEOUT_S)
            await until(lambda: audio.stop_output_calls == 1)
            await live.idle()
            # Le rejeu est appliqué au bloc suivant : la capture continue.
            signals += await asyncio.to_thread(run_capture, processor, tone(0.5, amplitude=0.4, freq=180.0), b"", forwarded)
            for signal in signals:
                bridge._on_capture_signal(signal)
            await live.idle()
    finally:
        processor.close()

    # Arrêt local avant toute réponse du fournisseur, puis annulation/troncature.
    assert calls[:3] == ["stop_output", "cancel_output", "truncate"]
    confirmed = journal.of(BARGE_IN_OWNER_CONFIRMED_KIND)
    assert len(confirmed) == 1 and confirmed[0]["data"]["provider_speech_started"] is False
    replays = journal.of(OWNER_REPLAY_KIND)
    assert len(replays) == 1  # le préfixe est rejoué une fois, jamais deux
    replay = replays[0]["data"]
    assert replay["replay_ms"] > 0 and replay["clamped_ms"] == 0
    # Le rejeu part de la preuve qui a reconnu le propriétaire, pas du début du
    # collègue : la fuite du relais reste bornée (tâche 07).
    assert replay["replay_from_ms"] >= 1500
    dropped = journal.of(OWNER_INPUT_DROPPED)
    assert all(item["data"]["source"] == "capture" for item in dropped)


# --------------------------------------------------------------------------
# 2. JARVIS silencieux : une autre voix ne crée ni tour ni activité utile


def drive(audio: QuietAudio, pcm: bytes) -> None:
    """Faire tourner la capture comme PortAudio, puis la file d'envoi du pont."""

    block = 1200 * 2
    for offset in range(0, len(pcm), block):
        raw = pcm[offset : offset + block]
        processed, signals = audio.capture.process(raw)
        audio._deliver_capture(len(raw), processed, signals)


async def test_jarvis_silent_a_colleague_is_never_a_turn_and_the_owner_rearms_the_session(monkeypatch):
    """Runtime complet, vrai fil du vérificateur : seul le propriétaire compte."""

    stranger = verdict(0.2, detected=False, evidence_ms=1500)
    owner = verdict(0.95, detected=True, evidence_ms=1500)
    worker = owner_worker([stranger] * 20 + [owner] * 60)
    # Détecteur réel : c'est lui qui ouvre le candidat acoustique, JARVIS muet.
    capture = CaptureProcessor(capture_rate=RATE, render_rate=RATE, observer=worker, owner_buffer_ms=2500)
    clock = FakeClock()
    rig = solo_runtime(monkeypatch, capture=capture, clock=clock, timeout_s=10)
    task = asyncio.create_task(rig.runtime.run())
    try:
        await rig.wakeword.queue.put("f9")
        await rig.journal.wait_until(lambda: rig.journal.count("audio.start") == 1)
        audio = QuietAudio.instances[-1]
        await until(lambda: capture._owner_gate_wanted)  # garde confiée avant le premier bloc

        # Deux secondes de conversation voisine : rien ne part, rien ne compte.
        drive(audio, tone(2.0, amplitude=0.4, freq=180.0))
        assert await asyncio.to_thread(worker.flush, TIMEOUT_S)
        await asyncio.sleep(0.05)
        assert not any(bytes(rig.session.audio))
        assert rig.core.brain_turns == []
        clock.advance(6)
        assert await rig.runtime.check_timeout() is False

        # Le propriétaire parle : reconnu, son audio part, son tour réarme tout.
        drive(audio, tone(2.5, amplitude=0.4, freq=180.0))
        assert await asyncio.to_thread(worker.flush, TIMEOUT_S)
        await asyncio.sleep(0.05)  # le pont demande l'ouverture du flux
        drive(audio, tone(0.3, amplitude=0.4, freq=180.0))  # appliquée au bloc suivant : rejeu
        await until(lambda: any(bytes(rig.session.audio)))
        await rig.session.push("realtime.speech_started", item_id="item-owner")
        await rig.session.push("realtime.transcript", text="Jarvis, rappelle-moi le rendez-vous.", item_id="item-owner")
        await until(lambda: len(rig.core.brain_turns) == 1)
        clock.advance(6)
        assert await rig.runtime.check_timeout() is False  # le propriétaire a réarmé le délai
        clock.advance(6)
        assert await rig.runtime.check_timeout() is True  # 12 s sans rien d'utile
    finally:
        rig.wakeword.closed = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert rig.core.brain_turns[0]["content"] == "Jarvis, rappelle-moi le rendez-vous."
    assert rig.runtime.runtime.state is VoiceLifecycleState.BACKGROUND


# --------------------------------------------------------------------------
# 3. Retour arrière : `open_room` rend exactement la chaîne d'avant le handoff


async def open_room_run(*, verifier: bool) -> dict[str, object]:
    """Salle ouverte : capture réelle + pont acoustique, avec ou sans vérificateur."""

    worker = owner_worker([verdict(0.99, detected=True, evidence_ms=1500)] * 60) if verifier else None
    processor = CaptureProcessor(
        capture_rate=RATE,
        render_rate=RATE,
        canceller=PassThroughCanceller(),
        observer=worker,  # type: ignore[arg-type]
    )
    calls: list[str] = []
    audio, journal = RecordingAudio(calls), RecordingJournal()
    audio.capture = processor
    session = ControllableSession(calls)
    clock = ManualClock()
    bridge = build_bridge(
        audio,
        session=session,
        journal=journal,
        authority=BargeInAuthority.ACOUSTIC,
        clock=clock,
        barge_in_confirm_s=0.05,
    )
    forwarded = bytearray()
    mic = mix(tone(2.0, amplitude=0.02), bytes(RATE * 2) + tone(1.0, amplitude=0.4, freq=180.0))
    try:
        async with Live(bridge) as live:
            await live.send(*jarvis_speaking(chunks=3))
            signals = run_capture(processor, mic, tone(2.0, amplitude=0.3), forwarded)
            for signal in signals:
                bridge._on_capture_signal(signal)
            await live.idle()
            await live.send(event("realtime.speech_started", item_id="item-1"))
            await live.idle()
    finally:
        if worker is not None:
            assert worker.flush(TIMEOUT_S)
        processor.close()
    return {
        "forwarded": bytes(forwarded),
        "gains": list(audio.gains),
        "calls": list(calls),
        "kinds": [item["kind"] for item in journal.events],
        "stops": audio.stop_output_calls,
    }


async def test_rolling_back_to_open_room_restores_the_previous_chain_byte_for_byte():
    """`conversation_mode = open_room` : le vérificateur n'existe que pour mesurer."""

    baseline = await open_room_run(verifier=False)
    with_verifier = await open_room_run(verifier=True)

    assert with_verifier["forwarded"] == baseline["forwarded"]
    assert with_verifier["gains"] == baseline["gains"] == [0.3]  # la baisse acoustique est de retour
    assert with_verifier["calls"] == baseline["calls"]
    assert with_verifier["kinds"] == baseline["kinds"]
    assert with_verifier["stops"] == baseline["stops"] == 1  # coupé sur la confirmation du fournisseur
    assert not any(kind.startswith("voice.owner") or kind.startswith("voice.barge_in.") for kind in baseline["kinds"])
