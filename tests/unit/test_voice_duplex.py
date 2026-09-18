"""Échanges vocaux en mode continu : écho, bruit, barge-in et accusé de réception.

Ces tests figent les corrections du 11 septembre 2026 (docs/fixes/voice-duplex/) :

1. JARVIS doit pouvoir être coupé pendant qu'il parle, même quand le
   fournisseur a déjà envoyé toute sa phrase (l'audio en attente ne doit plus
   faire attendre `speech_started`).
2. Il ne doit ni s'entendre lui-même, ni prendre un bruit de bureau ou une
   conversation voisine pour une demande.
3. La réponse rapide de la surface doit être pertinente et ne pas se répéter :
   plus de « Entendu. » automatique à chaque segment.

Ce qui n'est pas prouvé ici : l'efficacité réelle de l'annulation d'écho sur
les haut-parleurs et le micro d'un poste — seul un essai sur poste le dira.
"""

from __future__ import annotations

import asyncio
import base64
import math
import threading

import numpy as np
import pytest

from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
from jarvis.adapters.openai_realtime import (
    OUTPUT_ID_METADATA_KEY,
    OpenAIRealtimeSession,
    build_reflex_instruction,
    build_turn_detection,
)
from jarvis.audio.duplex import NEAR_END, CaptureProcessor, NearEndDetector, frame_db
from jarvis.domain.speaker import OwnerState
from jarvis.domain.v2 import AddressingDecision, ProtocolEnvelope, SpeechKind, SpeechPriority, SpeechRequest
from jarvis.ports.v2 import supports_reflex
from jarvis.runtime import voice_stack
from jarvis.runtime.realtime_audio import (
    NEAR_END_SIGNAL,
    ConservativeAddressingClassifier,
    RealtimeConversationBridge,
    SoundDeviceRealtimeAudio,
)
from tests.fakes.speech_context import source, context
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.runtime.turn_filters import EchoGuard, looks_like_request, mentions_jarvis, noise_reason

CONVERSATION = "conv-duplex"
RATE = 24000
FRAME = RATE // 100  # 10 ms
TIMEOUT_S = 2.0


# --------------------------------------------------------------------------
# Outillage


def tone(seconds: float, *, amplitude: float, freq: float = 220.0) -> bytes:
    t = np.arange(int(RATE * seconds)) / RATE
    signal = amplitude * np.sin(2 * math.pi * freq * t)
    return (signal * 32767).astype(np.int16).tobytes()


def silence(seconds: float) -> bytes:
    return bytes(int(RATE * seconds) * 2)


def noise(seconds: float, *, amplitude: float, seed: int = 1) -> bytes:
    rng = np.random.default_rng(seed)
    return (amplitude * rng.standard_normal(int(RATE * seconds)) * 32767).clip(-32768, 32767).astype(np.int16).tobytes()


def mix(*parts: bytes) -> bytes:
    arrays = [np.frombuffer(part, dtype=np.int16).astype(np.int32) for part in parts]
    size = max(len(array) for array in arrays)
    total = np.zeros(size, dtype=np.int32)
    for array in arrays:
        total[: len(array)] += array
    return total.clip(-32768, 32767).astype(np.int16).tobytes()


def run_capture(processor: CaptureProcessor, mic: bytes, reference: bytes = b"") -> tuple[bytes, list[float]]:
    """Faire tourner la capture comme PortAudio : blocs de 50 ms, référence en avance."""

    block = 1200 * 2
    out = bytearray()
    signals: list[float] = []
    pushed = 0
    for offset in range(0, len(mic), block):
        while pushed < min(len(reference), offset + 4800 * 2):
            processor.push_reference(reference[pushed:pushed + 4800])
            pushed += 4800
        chunk, emitted = processor.process(mic[offset:offset + block])
        out += chunk
        signals.extend(offset / 2 / RATE for signal in emitted if signal == NEAR_END)
    return bytes(out), signals


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]

    def count(self, kind: str) -> int:
        return len(self.of(kind))


class RecordingCore:
    def __init__(self) -> None:
        self.brain_turns: list[dict[str, object]] = []
        self.turns: list[dict[str, object]] = []

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str, source: str = "realtime", addressing: str = "addressed", provider_item_id=None, interrupted_speech_id=None):  # noqa: ANN001,E501
        self.brain_turns.append({"content": content, "addressing": addressing, "correlation_id": correlation_id, "interrupted_speech_id": interrupted_speech_id})
        return {"turn_id": f"turn-{len(self.brain_turns)}", "revision": len(self.brain_turns), "duplicate": False}

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id=None, metadata=None):  # noqa: ANN001
        self.turns.append({"kind": kind, "content": content, "metadata": metadata or {}})
        return {"id": f"turn-{len(self.turns)}"}


class ControllableSession:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.spoken: list[SpeechRequest] = []
        self.reflexes: list[dict[str, object]] = []
        self.active_output_id: str | None = None

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def finish_input(self) -> bool:
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def events(self):  # pragma: no cover - les tests injectent les évènements
        return
        yield

    async def close(self) -> None:
        return None

    async def speak_reserved(self, request: SpeechRequest, *, output_id: str) -> str:
        await self.speak(request)
        self.reserved_output_id = output_id
        return output_id

    async def invalidate_unstarted_output(self, output_id: str) -> None:
        self.calls.append("invalidate_unstarted_output")

    async def speak(self, request: SpeechRequest) -> str:
        self.spoken.append(request)
        self.calls.append("speak")
        return f"out-{len(self.spoken)}"

    async def speak_reflex(self, *, transcript: str, avoid=(), output_id=None, correlation_id=None) -> str:  # noqa: ANN001
        self.reflexes.append({"transcript": transcript, "avoid": tuple(avoid)})
        self.calls.append("speak_reflex")
        return output_id or f"reflex-{len(self.reflexes)}"

    async def cancel_output(self, cursor=None) -> None:  # noqa: ANN001
        self.calls.append("cancel_output")

    async def invalidate_reflex(self, output_id: str) -> None:
        self.calls.append("invalidate_reflex")

    async def truncate(self, cursor) -> None:  # noqa: ANN001
        self.calls.append("truncate")


class GuardedAudio(SoundDeviceRealtimeAudio):
    """Audio sans périphérique, avec une garde d'écho pilotable par le test."""

    def __init__(self, *, guarded: bool = True, gate_open: bool = False) -> None:
        super().__init__()
        self.guarded = guarded
        self.gate_open = gate_open
        self.far_recent = False
        self.released = 0
        self.learns: list[bool] = []
        self.gains: list[float] = []
        self.stop_output_calls = 0

    @property
    def has_echo_guard(self) -> bool:
        return self.guarded

    @property
    def echo_guard_open(self) -> bool:
        return self.gate_open

    @property
    def far_end_recent(self) -> bool:
        return self.far_recent

    def release_near_end(self, *, learn: bool = True) -> None:  # type: ignore[override]
        self.released += 1
        self.learns.append(learn)

    def set_output_gain(self, gain: float) -> None:
        self.gains.append(gain)
        super().set_output_gain(gain)

    async def play_b64(self, value: str) -> None:
        self._credit_written(self._output_epoch, len(base64.b64decode(value)))

    async def stop_output(self) -> None:
        self.stop_output_calls += 1
        await super().stop_output()

    async def close(self) -> None:
        return None


def build_bridge(audio, *, session=None, core=None, journal=None, clock=None, on_reflex=None, on_user_speech=None, continuous=True, **options):  # noqa: ANN001
    return RealtimeConversationBridge(
        core=core or RecordingCore(),
        session=session or ControllableSession(),
        conversation_id=CONVERSATION,
        audio=audio,
        on_addressed=lambda: None,
        on_mute=lambda: None,
        on_reflex=on_reflex,
        on_user_speech=on_user_speech,
        auto_turn=True,
        continuous=continuous,
        journal=journal,
        clock=clock,
        **options,
    )


def event(message_type: str, **payload: object) -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type=message_type, payload=payload)


def audio_delta(chunks: int, **payload: object) -> ProtocolEnvelope:
    pcm = base64.b64encode(b"\x01\x00" * (SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES * chunks)).decode()
    return event("realtime.audio", pcm_b64=pcm, **payload)


async def feed(bridge: RealtimeConversationBridge, events: list[ProtocolEnvelope]) -> None:
    async def stream():
        for item in events:
            yield item
            await bridge.wait_idle()

    await bridge._consume(stream())


async def until(predicate, *, timeout: float = TIMEOUT_S) -> None:  # noqa: ANN001
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition jamais atteinte")


class ManualClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --------------------------------------------------------------------------
# 1. Capture duplex : garde d'écho et parole proche


def test_the_bridge_and_the_capture_agree_on_the_near_end_signal():
    assert NEAR_END_SIGNAL == NEAR_END


def test_frame_energy_is_measured_in_dbfs():
    assert frame_db(silence(0.01)) < -100
    assert abs(frame_db(tone(0.01, amplitude=1.0)) - (-3.0)) < 0.5


def test_without_jarvis_speaking_the_microphone_passes_through():
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    mic = tone(0.5, amplitude=0.1)

    out, signals = run_capture(processor, mic)

    assert out == mic
    assert signals == []
    assert processor.gate_open


def test_jarvis_echo_never_reaches_the_provider():
    """Le cœur de la boucle « Entendu » : l'écho seul est remplacé par du silence."""

    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    reference = tone(2.0, amplitude=0.3)
    echo = tone(2.0, amplitude=0.2)  # l'écho au micro, sans annuleur

    out, signals = run_capture(processor, mix(echo, noise(2.0, amplitude=0.002)), reference)

    sent = np.frombuffer(out, dtype=np.int16)
    assert signals == []
    assert not np.any(sent[FRAME * 10:])  # passé les premières trames, rien que du silence
    assert not processor.gate_open


def test_the_user_talking_over_jarvis_opens_the_guard_with_the_start_of_the_sentence():
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    reference = tone(3.0, amplitude=0.3)
    echo = tone(3.0, amplitude=0.02)  # écho faible : un casque, ou l'annuleur a fait son travail
    user = silence(1.5) + tone(1.5, amplitude=0.4, freq=180.0)

    out, signals = run_capture(processor, mix(echo, user, noise(3.0, amplitude=0.001)), reference)

    assert len(signals) == 1
    assert 1.5 <= signals[0] <= 2.0  # moins d'une demi-seconde après le début
    assert processor.near_end_active
    # Le pré-roll est parti avec l'ouverture : la sortie contient plus que le
    # direct, et ce surplus précède le signal.
    assert len(out) > len(mix(echo, user)) - 1200 * 2


def test_a_released_guard_closes_again_while_jarvis_still_speaks():
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    reference = tone(3.0, amplitude=0.3)
    user = silence(1.0) + tone(0.6, amplitude=0.4, freq=180.0) + silence(1.4)

    _, signals = run_capture(processor, mix(tone(3.0, amplitude=0.02), user), reference[: len(reference) // 2])
    assert signals
    processor.release_near_end()
    out, _ = run_capture(processor, mix(tone(1.0, amplitude=0.02)), tone(1.0, amplitude=0.3))

    assert not processor.gate_open
    assert not np.any(np.frombuffer(out, dtype=np.int16)[FRAME * 5:])


def test_keyboard_clicks_do_not_count_as_speech():
    """Des bruits brefs n'ouvrent pas la garde : une syllabe dure plus qu'un clic."""

    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    reference = tone(3.0, amplitude=0.3)
    clicks = bytearray(silence(3.0))
    loud = noise(0.02, amplitude=0.5)
    for start in np.arange(0.5, 2.8, 0.13):
        offset = int(start * RATE) * 2
        clicks[offset:offset + len(loud)] = loud

    _, signals = run_capture(processor, mix(tone(3.0, amplitude=0.02), bytes(clicks)), reference)

    assert signals == []


def test_without_canceller_the_user_must_be_clearly_louder_than_the_echo():
    """Sans annuleur, l'écho peut égaler la voix : la garde reste prudente."""

    detector = NearEndDetector(initial_coupling_db=5.0)
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, detector=detector)
    reference = tone(3.0, amplitude=0.3)
    echo = tone(3.0, amplitude=0.3)
    user = silence(1.5) + tone(1.5, amplitude=0.3, freq=180.0)  # aussi fort que l'écho

    _, signals = run_capture(processor, mix(echo, user), reference)

    assert signals == []


class PassThroughCanceller:
    def __init__(self) -> None:
        self.render_frames = 0
        self.capture_frames = 0

    def process_render(self, frame: bytes) -> None:
        assert len(frame) == FRAME * 2
        self.render_frames += 1

    def process_capture(self, frame: bytes) -> bytes:
        self.capture_frames += 1
        return frame


class BrokenCanceller(PassThroughCanceller):
    def process_capture(self, frame: bytes) -> bytes:
        raise RuntimeError("apm down")


def test_the_canceller_sees_one_reference_frame_per_captured_frame():
    canceller = PassThroughCanceller()
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, canceller=canceller)

    run_capture(processor, silence(0.5), tone(0.2, amplitude=0.3))

    assert canceller.render_frames == canceller.capture_frames == 50


def test_a_failing_canceller_degrades_to_the_guard_alone():
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, canceller=BrokenCanceller())
    mic = tone(0.3, amplitude=0.1)

    out, _ = run_capture(processor, mic)

    assert processor.canceller_failed
    assert out == mic


def test_mixed_rates_consume_reference_by_duration():
    """Gemini capte en 16 kHz et rend en 24 kHz : la référence avance au même pas."""

    processor = CaptureProcessor(capture_rate=16000, render_rate=RATE)
    processor.push_reference(tone(1.0, amplitude=0.3))
    processor.process(bytes(16000 * 2 // 2))  # 500 ms captés

    assert len(processor._reference) == RATE * 2 // 2  # 500 ms de référence restent


def _speechlike(seconds: float, *, amplitude: float, seed: int) -> np.ndarray:
    """Voix synthétique : harmoniques d'une fondamentale qui varie, hachée en syllabes."""

    t = np.arange(int(RATE * seconds)) / RATE
    f0 = 120 + 40 * np.sin(2 * math.pi * 0.7 * t + seed)
    phase = 2 * math.pi * np.cumsum(f0) / RATE
    voiced = sum((1 / k) * np.sin(k * phase) for k in range(1, 15))
    envelope = (np.sin(2 * math.pi * 3 * t + seed) > -0.2) * (0.5 + 0.5 * np.abs(np.sin(2 * math.pi * 0.9 * t)))
    signal = voiced * envelope
    return signal / np.max(np.abs(signal)) * amplitude


def test_the_webrtc_canceller_removes_jarvis_and_keeps_the_user():
    """Chaîne réelle : AEC3 + garde, sur un écho retardé, filtré et saturé."""

    pytest.importorskip("livekit")
    from jarvis.adapters.webrtc_echo import create_echo_canceller

    far = _speechlike(8.0, amplitude=0.5, seed=2)
    far[: RATE // 2] = 0
    response = np.zeros(int(RATE * 0.08))
    response[[0, int(RATE * 0.007), int(RATE * 0.019), int(RATE * 0.045)]] = [1.0, 0.4, -0.3, 0.15]
    echo = np.tanh(2 * np.convolve(far, response)[: len(far)] * 0.6) / 2
    echo = np.concatenate([np.zeros(int(RATE * 0.15)), echo])[: len(far)]
    user = _speechlike(8.0, amplitude=0.2, seed=12)
    user[: int(RATE * 5.0)] = 0
    user[int(RATE * 6.5):] = 0
    mic = echo + user + 0.003 * np.random.default_rng(3).standard_normal(len(far))
    to_pcm = lambda values: (np.clip(values, -1, 1) * 32767).astype(np.int16).tobytes()  # noqa: E731

    processor = CaptureProcessor(
        capture_rate=RATE, render_rate=RATE, canceller=create_echo_canceller(capture_rate=RATE, render_rate=RATE)
    )
    out, signals = run_capture(processor, to_pcm(mic), to_pcm(far))

    sent = np.frombuffer(out, dtype=np.int16)
    assert not np.any(sent[RATE:int(RATE * 4.9)])  # JARVIS seul : rien ne part
    assert len(signals) == 1 and 5.0 <= signals[0] <= 5.8  # l'utilisateur, lui, passe


def test_reset_keeps_the_room_but_not_an_optimistic_coupling():
    """Entre deux réveils, le casque a pu laisser place aux haut-parleurs."""

    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    run_capture(processor, tone(4.0, amplitude=0.001), tone(4.0, amplitude=0.3))
    floor, warmed = processor.detector.floor_db, processor.detector._far_frames
    assert processor.detector.coupling_db < processor.detector.initial_coupling_db
    processor.push_reference(tone(0.5, amplitude=0.3))

    processor.reset()

    assert processor.gate_open
    assert processor._reference == bytearray()
    assert processor.detector.coupling_db == processor.detector.initial_coupling_db
    assert (processor.detector.floor_db, processor.detector._far_frames) == (floor, warmed)


def test_a_rejected_detection_teaches_the_detector_the_real_echo_level():
    """Couplage appris au casque, puis haut-parleurs : pas de barge-in en boucle."""

    detector = NearEndDetector(initial_coupling_db=-15.0, warmup_frames=0)
    detector.coupling_db = -50.0  # appris au casque
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, detector=detector)
    echo, reference = tone(3.0, amplitude=0.05), tone(3.0, amplitude=0.3)  # haut-parleurs

    _, first = run_capture(processor, echo[: len(echo) // 3], reference[: len(reference) // 3])
    assert first  # l'écho passe d'abord pour l'utilisateur…
    processor.release_near_end()  # … le fournisseur ne confirme pas
    _, again = run_capture(processor, echo[len(echo) // 3:], reference[len(reference) // 3:])

    assert again == []


def test_the_detector_still_learns_when_the_proof_arrives_after_jarvis_fell_silent():
    """Barge-in confirmé sur l'écho, coupure, puis le transcript le démasque.

    Entre le verrou et la preuve, JARVIS s'est tu et la fenêtre a été vidée :
    sans `latched_excess_db`, l'apprentissage tardif ne rattrapait rien et le
    même écho rouvrait la garde à la phrase suivante (poste réel, 18/09/2026).
    """

    detector = NearEndDetector(initial_coupling_db=-15.0, warmup_frames=0)
    detector.coupling_db = -50.0  # appris au casque
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, detector=detector)
    echo, reference = tone(3.0, amplitude=0.05), tone(3.0, amplitude=0.3)

    _, first = run_capture(processor, echo[: len(echo) // 3], reference[: len(reference) // 3])
    assert first
    # La sortie est coupée : plus de référence, JARVIS se tait, la fenêtre se vide.
    processor.clear_reference()
    run_capture(processor, silence(1.0), silence(1.0))
    assert not detector._recent_excess and detector.latched_excess_db is not None

    learned_from = detector.coupling_db
    processor.release_near_end(learn=True)  # le transcript était une hallucination
    run_capture(processor, silence(0.02), silence(0.02))  # la demande s'applique au bloc suivant

    assert detector.coupling_db > learned_from
    _, again = run_capture(processor, echo[len(echo) // 3:], reference[len(reference) // 3:])
    assert again == []


def test_the_detector_reports_its_levels_without_touching_them():
    detector = NearEndDetector(initial_coupling_db=-15.0, warmup_frames=0)
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, detector=detector)
    run_capture(processor, tone(0.5, amplitude=0.05), tone(0.5, amplitude=0.3))

    before = (detector.coupling_db, detector.floor_db, detector.latched)
    data = processor.near_end_diagnostics().as_data()

    assert (detector.coupling_db, detector.floor_db, detector.latched) == before
    assert set(data) == {"mic_db", "ref_env_db", "floor_db", "coupling_db", "excess_db",
                         "margin_db", "far_frames", "warming_up", "latched", "guard_open"}
    assert data["ref_env_db"] > data["mic_db"]  # l'écho est sous ce qui est joué
    assert data["excess_db"] == pytest.approx(data["mic_db"] - data["ref_env_db"], abs=0.11)
    # Ce que le bridge journalise, et rien sans capture duplex.
    assert SoundDeviceRealtimeAudio(capture=processor).near_end_diagnostics() == data
    assert SoundDeviceRealtimeAudio().near_end_diagnostics() is None


def test_the_preroll_never_replays_what_was_already_sent():
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, canceller=PassThroughCanceller())
    # L'utilisateur parle déjà quand JARVIS commence (0,5 s) : ses premières
    # trames partent en direct, puis la garde se ferme, puis la parole est
    # confirmée. Seules les trames remplacées par du silence sont rejouées.
    mic = mix(silence(0.3) + tone(1.7, amplitude=0.4, freq=180.0), tone(2.0, amplitude=0.01))
    reference = silence(0.5) + tone(1.5, amplitude=0.3)

    out, signals = run_capture(processor, mic, reference)

    assert len(signals) == 1
    replayed_s = (len(out) - len(mic)) / 2 / RATE
    gated_s = signals[0] + 0.05 - 0.5  # de la fermeture à la confirmation
    assert 0 < replayed_s <= gated_s + 0.01


async def test_played_blocks_become_the_echo_reference_and_a_cut_clears_them():
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    audio = SoundDeviceRealtimeAudio(capture=processor)

    class Stream:
        latency = 0.0

        def write(self, block) -> None:  # noqa: ANN001
            del block

        def abort(self, *, ignore_errors=True) -> None:
            return None

        def start(self) -> None:
            return None

    audio._output = Stream()
    audio.set_active_output(output_id="out-1")
    await audio.play_b64(base64.b64encode(tone(0.2, amplitude=0.3)).decode())
    assert len(processor._reference) == len(tone(0.2, amplitude=0.3))

    await audio.stop_output()
    assert processor._reference == bytearray()


async def test_ducking_lowers_the_blocks_actually_written():
    audio = SoundDeviceRealtimeAudio()
    written: list[bytes] = []

    class Stream:
        latency = 0.0

        def write(self, block) -> None:  # noqa: ANN001
            written.append(bytes(block))

    audio._output = Stream()
    audio.set_output_gain(0.25)
    audio._applied_gain = 0.25
    await audio.play_b64(base64.b64encode(tone(0.1, amplitude=0.4)).decode())

    level = np.abs(np.frombuffer(written[0], dtype=np.int16)).max()
    assert 0.2 * 0.4 * 32767 < level < 0.3 * 0.4 * 32767


def test_the_capture_callback_delivers_processed_audio_and_signals_on_the_loop():
    received: list[str] = []
    audio = SoundDeviceRealtimeAudio()
    audio.on_capture_signal = received.append

    audio._deliver_capture(2400, b"\x00" * 4800, (NEAR_END,))

    assert audio.captured_bytes == 2400
    assert audio._queue.qsize() == 1
    assert received == [NEAR_END]


# --------------------------------------------------------------------------
# 1 bis. Vérification du locuteur en ombre : la capture ne change pas d'un octet


class RecordingObserver:
    def __init__(self, *, fail: bool = False) -> None:
        self.frames: list[bytes] = []
        self.contexts: list[object] = []
        self.resets = 0
        self.closed = False
        self.fail = fail

    def observe(self, frame: bytes, context) -> None:  # noqa: ANN001
        if self.fail:
            raise RuntimeError("observer down")
        self.frames.append(frame)
        self.contexts.append(context)

    def reset(self) -> None:
        self.resets += 1

    def close(self, *, ignore_errors=True) -> None:
        self.closed = True


class HalvingCanceller(PassThroughCanceller):
    def process_capture(self, frame: bytes) -> bytes:
        self.capture_frames += 1
        return (np.frombuffer(frame, dtype=np.int16) // 2).astype(np.int16).tobytes()


def _capture_trace(observer, mic: bytes, reference: bytes) -> list[tuple]:  # noqa: ANN001
    """Tout ce que la capture rend, bloc par bloc : audio, signaux, garde, parole proche.

    La dernière entrée fige l'état appris du détecteur : l'observateur ne doit
    pas plus le toucher que l'audio.
    """

    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, canceller=PassThroughCanceller(), observer=observer)
    block, trace, pushed = 1200 * 2, [], 0
    for offset in range(0, len(mic), block):
        while pushed < min(len(reference), offset + 4800 * 2):
            processor.push_reference(reference[pushed:pushed + 4800])
            pushed += 4800
        chunk, emitted = processor.process(mic[offset:offset + block])
        trace.append((chunk, emitted, processor.gate_open, processor.near_end_active))
    detector = processor.detector
    trace.append((detector.coupling_db, detector.floor_db, detector.latched, detector._far_frames, processor.stream_ms))
    return trace


def _keyboard(seconds: float) -> bytes:
    """Clics de 20 ms toutes les 130 ms, comme au test de la garde."""

    clicks = bytearray(silence(seconds))
    loud = noise(0.02, amplitude=0.5)
    for start in np.arange(0.5, seconds - 0.2, 0.13):
        offset = int(start * RATE) * 2
        clicks[offset:offset + len(loud)] = loud
    return bytes(clicks)


_SHADOW_SCENARIOS = {
    # L'utilisateur coupe JARVIS : garde fermée, puis ouverte avec pré-roll.
    "barge_in": (
        mix(tone(3.0, amplitude=0.02), silence(1.5) + tone(1.5, amplitude=0.4, freq=180.0), noise(3.0, amplitude=0.001)),
        tone(3.0, amplitude=0.3),
    ),
    # JARVIS seul : rien que du silence part.
    "echo_only": (mix(tone(2.0, amplitude=0.2), noise(2.0, amplitude=0.002)), tone(2.0, amplitude=0.3)),
    # JARVIS se tait : le micro passe tel quel.
    "idle": (tone(1.0, amplitude=0.1), b""),
    # JARVIS se tait, une voix parle six secondes d'affilée : candidat long.
    "long_voice": (mix(tone(6.0, amplitude=0.3, freq=180.0), noise(6.0, amplitude=0.001)), b""),
    # Clavier pendant que JARVIS parle.
    "keyboard": (mix(tone(3.0, amplitude=0.02), _keyboard(3.0)), tone(3.0, amplitude=0.3)),
}


def _shadow_worker(verifier, journal=None, **options):  # noqa: ANN001, ANN003, ANN202
    from jarvis.audio.speaker_shadow import SpeakerVerificationWorker

    # File large : un test tourne plus vite que le temps réel, rien ne doit être sauté.
    return SpeakerVerificationWorker(verifier, sample_rate=RATE, diagnostics=journal, max_pending_ms=60_000, **options)


@pytest.mark.parametrize("scenario", sorted(_SHADOW_SCENARIOS))
@pytest.mark.parametrize("verifier_kind", ["owner", "stranger", "overlap", "crashing", "broken_listener", "broken_observer"])
def test_shadow_verification_leaves_the_capture_byte_for_byte_identical(scenario, verifier_kind):  # noqa: ANN001
    from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
    from jarvis.audio.speaker_shadow import SpeakerVerificationWorker

    mic, reference = _SHADOW_SCENARIOS[scenario]
    baseline = _capture_trace(None, mic, reference)
    scripts = {
        "owner": [0.2, 0.9] * 30,
        "stranger": [0.2] * 60,
        "overlap": [0.2, 0.9, 0.3, 0.95] * 15,
        "crashing": [0.5, RuntimeError("model lost")],
        "broken_listener": [0.9] * 60,
    }
    journal = RecordingJournal()
    verifier = None
    if verifier_kind == "broken_observer":
        observer = RecordingObserver(fail=True)
    else:
        verifier = ScriptedSpeakerVerifier(scripts[verifier_kind])
        observer = _shadow_worker(verifier, journal)
        if verifier_kind == "broken_listener":
            observer.add_owner_listener(lambda snapshot: 1 / 0)
    try:
        shadowed = _capture_trace(observer, mic, reference)
        if isinstance(observer, SpeakerVerificationWorker):
            assert observer.flush(TIMEOUT_S)
    finally:
        observer.close()

    assert shadowed == baseline
    if verifier is not None:
        assert verifier.calls  # le vérificateur a bien écouté
        assert all(str(event["kind"]).startswith("voice.owner.") for event in journal.events)


def test_the_observer_sees_the_echo_cancelled_frames():
    observer = RecordingObserver()
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, canceller=HalvingCanceller(), observer=observer)
    mic = tone(0.3, amplitude=0.4)

    run_capture(processor, mic)

    assert len(observer.frames) == 30 and {len(frame) for frame in observer.frames} == {FRAME * 2}
    assert b"".join(observer.frames) == (np.frombuffer(mic, dtype=np.int16) // 2).astype(np.int16).tobytes()
    assert [context.stream_ms for context in observer.contexts] == list(range(0, 300, 10))
    assert {context.sample_rate for context in observer.contexts} == {RATE}
    assert not any(context.far_end for context in observer.contexts)  # JARVIS se tait


@pytest.mark.parametrize("canceller", [None, BrokenCanceller], ids=["no_canceller", "failed_canceller"])
def test_without_a_canceller_the_observer_sees_the_raw_microphone(canceller):  # noqa: ANN001
    """Ce que le vérificateur reçoit vraiment quand l'AEC manque ou tombe.

    `_cancel_echo` est alors un passe-plat : la trame remise à l'observateur
    porte encore l'écho de JARVIS. Comportement voulu (l'état dégradé est
    montré, le micro n'est pas coupé), mais la documentation doit le dire tel
    quel plutôt que promettre une trame « nettoyée » — d'où ce test.
    """

    observer = RecordingObserver()
    processor = CaptureProcessor(
        capture_rate=RATE, render_rate=RATE, canceller=canceller() if canceller else None, observer=observer
    )
    mic, reference = _SHADOW_SCENARIOS["barge_in"]

    run_capture(processor, mic, reference)

    assert b"".join(observer.frames) == mic  # rien n'a été retiré : micro brut
    assert processor.canceller_failed is (canceller is not None)


def test_the_frame_context_carries_near_end_far_end_and_the_guard():
    """Ce que l'observateur apprend de chaque trame : candidat, JARVIS audible, garde, horloge."""

    observer = RecordingObserver()
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, canceller=PassThroughCanceller(), observer=observer)
    mic, reference = _SHADOW_SCENARIOS["barge_in"]

    _, signals = run_capture(processor, mic, reference)

    contexts = observer.contexts
    assert len(contexts) == 300 and all(context.far_end for context in contexts)
    assert not any(context.near_end for context in contexts[:150])  # écho seul : jamais candidat
    assert sum(context.near_end for context in contexts[150:]) >= 140  # l'utilisateur, lui, l'est
    first_latched = next(index for index, context in enumerate(contexts) if context.near_end_latched)
    assert abs(first_latched * 0.01 - signals[0]) <= 0.05  # même instant que le signal `near_end`
    assert not any(context.gate_open for context in contexts[10:first_latched])
    assert all(context.gate_open for context in contexts[first_latched:])
    assert processor.stream_ms == 3000

    processor.reset()
    run_capture(processor, silence(0.1))

    assert processor.stream_ms == 100 and contexts[300].stream_ms == 0  # nouvelle session, nouvelle horloge


def _owner_trace(worker) -> list:  # noqa: ANN001
    published: list = []
    worker.add_owner_listener(published.append)
    return published


class _RecordingPcmVerifier(ScriptedSpeakerVerifier):
    """Vérificateur qui dit toujours « propriétaire » et garde ce qu'il reçoit."""

    def __init__(self, score: float = 0.99, windows: int = 200) -> None:
        super().__init__([score] * windows)
        self.received: list[bytes] = []

    def process(self, pcm: bytes, sample_rate: int):  # noqa: ANN201
        self.received.append(pcm)
        return super().process(pcm, sample_rate)


@pytest.mark.parametrize(
    "canceller,echo_amplitude",
    [(None, 0.2), (PassThroughCanceller, 0.005)],
    ids=["guard_only_loud_echo", "aec_residual"],
)
def test_echo_only_playback_never_becomes_the_owner(canceller, echo_amplitude):  # noqa: ANN001
    """Même un vérificateur qui dit « propriétaire » à tout : l'écho n'est pas un candidat."""

    verifier = _RecordingPcmVerifier()
    journal = RecordingJournal()
    worker = _shadow_worker(verifier, journal)
    published = _owner_trace(worker)
    processor = CaptureProcessor(
        capture_rate=RATE, render_rate=RATE, canceller=canceller() if canceller else None, observer=worker
    )
    try:
        run_capture(processor, mix(tone(4.0, amplitude=echo_amplitude), noise(4.0, amplitude=0.002)), tone(4.0, amplitude=0.3))
        assert worker.flush(TIMEOUT_S)
    finally:
        processor.close()

    assert published == [] and journal.events == []
    assert worker.owner_state.state is OwnerState.IDLE
    # L'écho résiduel n'entre jamais dans la preuve du moteur : silence numérique.
    assert len(verifier.received) == 40 and not any(any(pcm) for pcm in verifier.received)


def test_real_aec_echo_never_becomes_the_owner_but_the_user_does():
    """Chaîne réelle AEC3 : JARVIS seul pendant 4,5 s, puis l'utilisateur par-dessus."""

    pytest.importorskip("livekit")
    from jarvis.adapters.webrtc_echo import create_echo_canceller

    far = _speechlike(8.0, amplitude=0.5, seed=2)
    far[: RATE // 2] = 0
    response = np.zeros(int(RATE * 0.08))
    response[[0, int(RATE * 0.007), int(RATE * 0.019), int(RATE * 0.045)]] = [1.0, 0.4, -0.3, 0.15]
    echo = np.tanh(2 * np.convolve(far, response)[: len(far)] * 0.6) / 2
    echo = np.concatenate([np.zeros(int(RATE * 0.15)), echo])[: len(far)]
    user = _speechlike(8.0, amplitude=0.2, seed=12)
    user[: int(RATE * 5.0)] = 0
    user[int(RATE * 6.5):] = 0
    mic = echo + user + 0.003 * np.random.default_rng(3).standard_normal(len(far))
    to_pcm = lambda values: (np.clip(values, -1, 1) * 32767).astype(np.int16).tobytes()  # noqa: E731

    verifier = _RecordingPcmVerifier(windows=100)
    worker = _shadow_worker(verifier)
    published = _owner_trace(worker)
    processor = CaptureProcessor(
        capture_rate=RATE,
        render_rate=RATE,
        canceller=create_echo_canceller(capture_rate=RATE, render_rate=RATE),
        observer=worker,
    )
    try:
        run_capture(processor, to_pcm(mic), to_pcm(far))
        assert worker.flush(TIMEOUT_S)
    finally:
        processor.close()

    confirmed = [snapshot for snapshot in published if snapshot.state is OwnerState.OWNER_CONFIRMED]
    assert confirmed, "l'utilisateur doit être confirmé"
    assert all(snapshot.candidate_onset_ms >= 4900 for snapshot in published if snapshot.candidate_onset_ms is not None)
    assert 5000 <= confirmed[0].owner_onset_ms <= 5800 and confirmed[0].far_end
    # Lecture seule (1 s à 4,9 s) : le moteur n'a reçu que du silence numérique.
    assert not any(any(pcm) for pcm in verifier.received[10:49])


@pytest.mark.parametrize("jarvis_speaks", [False, True], ids=["jarvis_silent", "jarvis_speaking"])
def test_keyboard_clicks_never_become_the_owner(jarvis_speaks):  # noqa: ANN001
    verifier = _RecordingPcmVerifier()
    journal = RecordingJournal()
    worker = _shadow_worker(verifier, journal)
    published = _owner_trace(worker)
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, observer=worker)
    mic = mix(tone(3.0, amplitude=0.02), _keyboard(3.0)) if jarvis_speaks else _keyboard(3.0)
    try:
        run_capture(processor, mic, tone(3.0, amplitude=0.3) if jarvis_speaks else b"")
        assert worker.flush(TIMEOUT_S)
    finally:
        processor.close()

    assert published == [] and journal.events == []
    assert worker.owner_state.state is OwnerState.IDLE


def test_the_owner_is_confirmed_after_a_long_stranger_sentence_without_silence():
    """D06 au bout de la chaîne : quatre secondes d'étranger, puis le propriétaire, d'une traite."""

    from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
    from jarvis.audio.speaker_shadow import OWNER_CANDIDATE, OWNER_CONFIRMED, OWNER_REJECTED
    from jarvis.domain.speaker import SpeakerVerification, VerificationStatus

    owner = SpeakerVerification(
        status=VerificationStatus.OK, engine="fake-speaker/1", owner_score=0.9, owner_detected=True, evidence_ms=1500
    )
    journal = RecordingJournal()
    worker = _shadow_worker(ScriptedSpeakerVerifier([0.2] * 40 + [owner] * 20), journal)
    published = _owner_trace(worker)
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, observer=worker)
    mic, _ = _SHADOW_SCENARIOS["long_voice"]
    try:
        out, _ = run_capture(processor, mic)
        assert worker.flush(TIMEOUT_S)
    finally:
        processor.close()

    assert out == mic  # JARVIS se tait : le micro passe, vérification ou non
    assert [snapshot.state for snapshot in published] == [OwnerState.REJECTED, OwnerState.OWNER_CONFIRMED]
    confirmed = published[-1]
    assert (confirmed.candidate_onset_ms, confirmed.confirmed_ms, confirmed.owner_onset_ms) == (0, 4100, 2600)
    assert not confirmed.far_end
    kinds = [event["kind"] for event in journal.events]
    assert kinds == [OWNER_CANDIDATE, OWNER_CONFIRMED] and OWNER_REJECTED not in kinds
    assert journal.events[-1]["data"]["after_non_owner"] is True


def test_an_owner_barge_in_is_confirmed_with_stream_timestamps():
    """Ce que la tâche 05 consommera : confirmation, début estimé, JARVIS audible."""

    from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
    from jarvis.audio.speaker_shadow import OWNER_CONFIRMED

    journal = RecordingJournal()
    # « Propriétaire » à chaque fenêtre, écho compris : seul le candidat compte.
    worker = _shadow_worker(ScriptedSpeakerVerifier([0.99] * 40), journal)
    published = _owner_trace(worker)
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, canceller=PassThroughCanceller(), observer=worker)
    mic, reference = _SHADOW_SCENARIOS["barge_in"]
    try:
        run_capture(processor, mic, reference)
        assert worker.flush(TIMEOUT_S)
    finally:
        processor.close()

    assert [snapshot.state for snapshot in published] == [OwnerState.OWNER_CONFIRMED]
    owner = published[0]
    # L'utilisateur commence à 1,5 s ; la 12e trame proche tombe dans la
    # fenêtre 1,6–1,7 s, jugée aussitôt.
    assert (owner.candidate_onset_ms, owner.owner_onset_ms, owner.confirmed_ms) == (1500, 1500, 1700)
    assert owner.far_end and owner.session == 0
    confirmed = [event["data"] for event in journal.events if event["kind"] == OWNER_CONFIRMED]
    assert confirmed[0]["confirm_ms"] == 200 and confirmed[0]["far_end"] is True


def test_each_capture_session_starts_a_fresh_owner_state():
    from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier

    verifier = ScriptedSpeakerVerifier([0.9] * 100)
    worker = _shadow_worker(verifier)
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, observer=worker)
    mic, _ = _SHADOW_SCENARIOS["long_voice"]
    try:
        processor.reset()  # activation
        run_capture(processor, mic[: len(mic) // 3])
        assert worker.flush(TIMEOUT_S)
        first = worker.owner_state
        processor.reset()  # retour au fond, micro fermé
        assert worker.flush(TIMEOUT_S)
        ended = worker.owner_state
        run_capture(processor, mic[: len(mic) // 3])
        assert worker.flush(TIMEOUT_S)
        second = worker.owner_state
    finally:
        processor.close()

    assert (first.session, first.state, first.confirmed_ms) == (1, OwnerState.OWNER_CONFIRMED, 200)
    assert (ended.session, ended.state, ended.candidate_onset_ms) == (2, OwnerState.IDLE, None)
    # Même horloge repartie de zéro : mêmes instants, rien hérité de la session d'avant.
    assert (second.session, second.state, second.confirmed_ms, second.candidate_onset_ms) == (2, OwnerState.OWNER_CONFIRMED, 200, 0)
    assert verifier.resets == 2
    assert worker.telemetry.machine.region is not None and len(worker.telemetry.machine._near) <= 40


def test_a_failing_observer_is_dropped_without_touching_the_microphone():
    observer = RecordingObserver(fail=True)
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, observer=observer)
    mic = tone(0.3, amplitude=0.1)

    out, _ = run_capture(processor, mic)
    processor.reset()

    assert out == mic
    assert processor.observer_failed
    assert observer.resets == 0  # écarté pour de bon, comme un annuleur en panne


def test_the_capture_resets_and_closes_its_observer():
    observer = RecordingObserver()
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, observer=observer)

    processor.reset()
    processor.close()
    processor.close()

    assert observer.resets == 1 and observer.closed
    assert processor.observer is None


# --------------------------------------------------------------------------
# 2. Filtres de transcript


@pytest.mark.parametrize(
    "text,reason",
    [
        ("директор", "foreign_script"),
        ("Sous-titres réalisés par la communauté d'Amara.org", "hallucination"),
        ("Merci d'avoir regardé !", "hallucination"),
        ("euh", "filler"),
        ("...", "no_letters"),
        ("Est-ce qu'on est à jour au niveau des commits ?", None),
        ("Euh, Jarvis", None),
        ("OK", None),
    ],
)
def test_noise_transcripts_are_recognised(text, reason):  # noqa: ANN001
    assert noise_reason(text) == reason


@pytest.mark.parametrize(
    "text,reason",
    [
        # Poste réel du 18/09/2026 : haut-parleurs, micro ambiant, l'écho
        # résiduel devient une phrase brève sans rapport avec la question.
        ("La plateforme.", "residual_echo"),
        ("Le budget.", "residual_echo"),
        ("Mhm.", "filler"),
        ("Merci.", "playback_hallucination"),
        ("Bonjour à tous.", "playback_hallucination"),
        ("Au revoir.", "playback_hallucination"),
        # Une vraie interruption brève reste un propos : il suffit d'un mot
        # d'interruction dans le segment.
        ("Non, arrête.", None),
        ("Stop ça.", None),
        ("Attendez...", None),
        ("D'accord.", None),
        ("Continue là.", None),
        # Le nom prononcé l'emporte, et une phrase entière n'est jamais brève.
        ("Merci Jarvis.", None),
        ("Qu'est-ce qu'il y a ?", None),
    ],
)
def test_speaker_echo_is_only_filtered_over_jarvis_voice(text, reason):  # noqa: ANN001
    """Les mêmes phrases dites dans le silence restent des propos de l'utilisateur."""

    assert noise_reason(text, near_playback=True) == reason
    assert noise_reason(text) == (reason if reason in (None, "filler") else None)


def test_the_echo_loop_of_the_eleventh_of_september_is_recognised():
    """Les faux tours relevés dans runtime/trace.jsonl ce jour-là."""

    guard = EchoGuard()
    for spoken in ("Un instant.", "Un instant.", "Entendu.", "Oui."):
        guard.remember(spoken)

    for heard in ("Un instant, un instant.", "Entendu. Oui.", "Attendu, oui."):
        assert guard.is_echo(heard), heard
    assert not guard.is_echo("Est-ce qu'on est à jour au niveau des commits sur le projet ?")
    assert not guard.is_echo("Oui, pousse les commits sur GitHub")


def test_a_single_word_is_never_taken_for_echo():
    """« Oui. » répondu aussitôt à « … oui ou non ? » est une vraie réponse.

    Un mot isolé en écho reste possible, mais la garde d'écho l'arrête en amont :
    le fournisseur ne reçoit pas le micro pendant que JARVIS parle.
    """

    guard = EchoGuard()
    guard.remember("Voulez-vous que je pousse les commits, oui ou non ?")

    assert not guard.is_echo("Oui.")


def test_only_what_was_heard_can_come_back_as_echo():
    guard = EchoGuard()
    guard.remember("Voici le plan : d'abord les tests, ensuite le résumé des commits", key="speech-1")

    guard.limit("speech-1", 0.3)  # coupé au tiers

    assert guard.is_echo("Voici le plan")
    assert not guard.is_echo("Ensuite le résumé des commits")


def test_the_echo_memory_forgets_old_sentences():
    clock = ManualClock()
    guard = EchoGuard(clock=clock, horizon_s=30)
    guard.remember("Entendu.")
    clock.now += 31

    assert not guard.is_echo("Entendu.")


def test_request_forms_are_recognised():
    assert looks_like_request("Regarde dans mon Drive le fichier des comptes de janvier et donne moi le total")
    assert looks_like_request("Est-ce que tu peux me préparer un résumé de tous les mails reçus hier")
    assert not looks_like_request("il faudrait vraiment que quelqu'un rappelle le client avant ce soir")
    assert mentions_jarvis("Merci Jarvis !")
    assert not mentions_jarvis("la jarvisation du projet")


def test_addressing_follows_the_engagement_window():
    classifier = ConservativeAddressingClassifier()
    long_request = "Regarde dans mon Drive le fichier des comptes de janvier et donne moi le total"
    overheard = "il faudrait vraiment que quelqu'un rappelle le client avant la fin de la journée"

    assert classifier.classify(long_request, active=True, engaged=True) is AddressingDecision.ADDRESSED
    assert classifier.classify(overheard, active=True, engaged=True) is AddressingDecision.UNCERTAIN
    assert classifier.classify("Tu viens manger ?", active=True, engaged=False) is AddressingDecision.UNCERTAIN
    assert classifier.classify("Merci Jarvis", active=True, engaged=False) is AddressingDecision.ADDRESSED
    # Legacy : pas de fenêtre, l'ancienne règle de forme.
    assert classifier.classify(long_request, active=True) is AddressingDecision.UNCERTAIN


# --------------------------------------------------------------------------
# 3. Le bridge : barge-in, écho, bruit, accusé


async def test_user_speech_cuts_jarvis_even_while_received_audio_is_still_queued():
    """Point 1 du retour utilisateur : « lorsqu'il parle, il ne m'écoute plus ».

    Le fournisseur a envoyé toute la phrase d'un coup ; seul le premier bloc est
    en train d'être écrit. `speech_started` doit couper tout de suite, sans
    attendre la fin de l'audio reçu, et rien de ce qui restait ne doit sortir.
    """

    release = threading.Event()
    written: list[bytes] = []

    class SlowStream:
        latency = 0.0

        def write(self, block) -> None:  # noqa: ANN001
            if not written:
                assert release.wait(5)
            written.append(bytes(block))

        def abort(self, *, ignore_errors=True) -> None:
            return None

        def start(self) -> None:
            return None

    audio = SoundDeviceRealtimeAudio()
    audio._output = SlowStream()
    session, journal = ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio, session=session, journal=journal)
    queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()

    async def stream():
        while (item := await queue.get()) is not None:
            yield item

    running = asyncio.create_task(bridge._consume(stream()))
    await queue.put(event("realtime.output_started", output_id="out-1", speech_id="speech-1", response_id="resp-1"))
    for _ in range(10):
        await queue.put(audio_delta(5, output_id="out-1", speech_id="speech-1", response_id="resp-1", item_id="item-1"))
    await queue.put(event("realtime.response_done", status="completed", output_id="out-1", speech_id="speech-1"))
    await until(lambda: bridge._playing)
    await queue.put(event("realtime.speech_started", item_id="item-user"))
    # Le barge-in a commencé alors que 49 blocs attendent encore d'être joués.
    await until(lambda: bridge._drop_audio_before > 0)
    # `stop_output()` attend, par sûreté, la fin de l'écriture en cours dans
    # PortAudio — au plus un bloc de 100 ms sur un vrai périphérique.
    release.set()
    await until(lambda: journal.count("voice.barge_in") == 1)
    await queue.put(None)
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert session.calls[:2] == ["cancel_output", "truncate"]
    # Au plus le bloc qui était déjà dans PortAudio : 10 × 5 blocs reçus.
    assert len(written) <= 1


async def test_speech_behind_a_closed_echo_guard_does_not_cut_jarvis():
    audio = GuardedAudio(guarded=True, gate_open=False)
    session, journal = ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio, session=session, journal=journal)

    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-1", speech_id="speech-1"),
            audio_delta(2, output_id="out-1", speech_id="speech-1"),
            event("realtime.speech_started"),
        ],
    )

    assert audio.stop_output_calls == 0
    assert journal.count("voice.barge_in_ignored") == 1


async def test_local_candidate_preserves_volume_until_provider_confirms_cut():
    audio = GuardedAudio(guarded=True, gate_open=True)
    session, journal = ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio, session=session, journal=journal)
    queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()

    async def stream():
        while (item := await queue.get()) is not None:
            yield item

    running = asyncio.create_task(bridge._consume(stream()))
    await queue.put(event("realtime.output_started", output_id="out-1", speech_id="speech-1"))
    await queue.put(audio_delta(2, output_id="out-1", speech_id="speech-1", item_id="item-1"))
    await until(lambda: bridge._playing)

    bridge._on_capture_signal(NEAR_END_SIGNAL)
    await until(lambda: journal.count("voice.barge_in_pending") == 1)
    assert audio.gains == []
    assert audio.stop_output_calls == 0

    await queue.put(event("realtime.speech_started"))
    await until(lambda: journal.count("voice.barge_in") == 1)
    await queue.put(None)
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert audio.stop_output_calls == 1


async def test_unconfirmed_local_speech_never_changes_volume():
    audio = GuardedAudio(guarded=True, gate_open=True)
    journal = RecordingJournal()
    bridge = build_bridge(audio, journal=journal, barge_in_confirm_s=0.05)
    queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()

    async def stream():
        while (item := await queue.get()) is not None:
            yield item

    running = asyncio.create_task(bridge._consume(stream()))
    await queue.put(event("realtime.output_started", output_id="out-1", speech_id="speech-1"))
    await queue.put(audio_delta(2, output_id="out-1", speech_id="speech-1"))
    await until(lambda: bridge._playing)
    bridge._on_capture_signal(NEAR_END_SIGNAL)

    await until(lambda: journal.count("voice.barge_in_rejected") == 1)
    await queue.put(None)
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert audio.gains == []
    assert audio.released == 1
    assert audio.stop_output_calls == 0


async def test_jarvis_hearing_himself_is_not_a_turn():
    """Point 2 : « il a confondu sa propre voix avec des commandes »."""

    audio = GuardedAudio(guarded=False)
    core, journal = RecordingCore(), RecordingJournal()
    bridge = build_bridge(audio, core=core, journal=journal)

    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-1"),
            audio_delta(1, output_id="out-1"),
            event("realtime.assistant_transcript", text="Je regarde l'état des commits.", output_id="out-1"),
            event("realtime.response_done", status="completed", output_id="out-1"),
            event("realtime.speech_started", item_id="item-echo"),
            event("realtime.input_committed", item_id="item-echo"),
            event("realtime.transcript", text="Je regarde l'état des comités.", item_id="item-echo"),
        ],
    )

    assert core.brain_turns == []
    assert journal.of("voice.transcript_dropped")[0]["data"]["reason"] == "echo"


async def test_a_short_hallucination_over_the_speakers_is_not_a_turn():
    """Poste réel du 18/09/2026 : « La plateforme. » née de l'écho, pas de l'utilisateur."""

    audio = GuardedAudio(guarded=False)
    core, journal = RecordingCore(), RecordingJournal()
    bridge = build_bridge(audio, core=core, journal=journal)

    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-1"),
            audio_delta(1, output_id="out-1"),
            event("realtime.assistant_transcript", text="Je propose d'allonger le délai. Je l'applique ?", output_id="out-1"),
            event("realtime.response_done", status="completed", output_id="out-1"),
            event("realtime.speech_started", item_id="item-echo"),
            event("realtime.transcript", text="La plateforme.", item_id="item-echo"),
        ],
    )

    assert core.brain_turns == []
    assert journal.of("voice.transcript_dropped")[0]["data"]["reason"] == "residual_echo"


async def test_barge_in_traces_carry_the_detector_levels():
    """Sans ces chiffres, un faux barge-in sur haut-parleurs ne se diagnostique qu'en devinant."""

    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    run_capture(processor, tone(0.5, amplitude=0.05), tone(0.5, amplitude=0.3))
    audio = SoundDeviceRealtimeAudio(capture=processor)
    journal = RecordingJournal()
    bridge = build_bridge(audio, journal=journal)
    bridge._playing = True

    await bridge._on_near_end()

    data = journal.of("voice.barge_in_pending")[0]["data"]
    assert data["near_coupling_db"] == pytest.approx(processor.detector.coupling_db, abs=0.05)
    assert {"near_mic_db", "near_ref_env_db", "near_floor_db", "near_margin_db", "near_latched"} <= set(data)


async def test_a_dropped_echo_teaches_the_detector_even_after_a_confirmed_cut():
    """Le chaînon manquant : un barge-in confirmé sur l'écho n'apprenait rien.

    Le détecteur n'apprenait qu'au *rejet* d'un candidat. Confirmé puis coupé,
    le même niveau d'écho rouvrait la garde à chaque phrase.
    """

    audio = GuardedAudio(guarded=False)
    core, journal = RecordingCore(), RecordingJournal()
    bridge = build_bridge(audio, core=core, journal=journal)

    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-1"),
            audio_delta(1, output_id="out-1"),
            event("realtime.assistant_transcript", text="Je propose d'allonger le délai. Je l'applique ?", output_id="out-1"),
            event("realtime.response_done", status="completed", output_id="out-1"),
            event("realtime.speech_started", item_id="item-echo"),
            event("realtime.transcript", text="La plateforme.", item_id="item-echo"),
        ],
    )

    assert core.brain_turns == []
    assert audio.learns == [True]
    assert journal.of("voice.echo_learned")[0]["data"]["reason"] == "residual_echo"


async def test_office_noise_is_never_learned_as_speaker_echo():
    """Un bruit de bureau vient du micro de près : l'apprendre rendrait JARVIS sourd."""

    audio = GuardedAudio(guarded=False)
    core = RecordingCore()
    bridge = build_bridge(audio, core=core)

    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-1"),
            audio_delta(1, output_id="out-1"),
            event("realtime.response_done", status="completed", output_id="out-1"),
            event("realtime.speech_started", item_id="i1"),
            event("realtime.transcript", text="директор", item_id="i1"),
        ],
    )

    assert core.brain_turns == [] and audio.learns == []


async def test_a_short_answer_over_jarvis_voice_is_still_a_turn():
    """La règle brève ne doit pas manger la réponse la plus naturelle à une question."""

    core = RecordingCore()
    bridge = build_bridge(GuardedAudio(guarded=False), core=core)

    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-1"),
            audio_delta(1, output_id="out-1"),
            event("realtime.assistant_transcript", text="Je propose d'allonger le délai. Je l'applique ?", output_id="out-1"),
            event("realtime.response_done", status="completed", output_id="out-1"),
            event("realtime.speech_started", item_id="item-1"),
            event("realtime.transcript", text="Non, arrête.", item_id="item-1"),
        ],
    )

    assert [turn["content"] for turn in core.brain_turns] == ["Non, arrête."]


async def test_repeating_jarvis_long_after_he_spoke_is_a_real_answer():
    clock = ManualClock()
    audio = GuardedAudio(guarded=False)
    core = RecordingCore()
    bridge = build_bridge(audio, core=core, clock=clock)

    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-1"),
            audio_delta(1, output_id="out-1"),
            event("realtime.assistant_transcript", text="Oui.", output_id="out-1"),
            event("realtime.response_done", status="completed", output_id="out-1"),
        ],
    )
    clock.now += 10
    await feed(bridge, [event("realtime.speech_started", item_id="item-2"), event("realtime.transcript", text="Oui.", item_id="item-2")])

    assert [turn["content"] for turn in core.brain_turns] == ["Oui."]


async def test_office_noise_transcribed_in_another_language_is_dropped():
    core, journal = RecordingCore(), RecordingJournal()
    bridge = build_bridge(GuardedAudio(guarded=False), core=core, journal=journal)

    await feed(bridge, [event("realtime.speech_started", item_id="i1"), event("realtime.transcript", text="директор", item_id="i1")])

    assert core.brain_turns == []
    assert journal.of("voice.transcript_dropped")[0]["data"]["reason"] == "foreign_script"


async def test_a_real_request_asks_the_scheduler_for_an_acknowledgement():
    requested: list[tuple[str, dict[str, object]]] = []
    bridge = build_bridge(GuardedAudio(guarded=False), on_reflex=lambda text, **kw: requested.append((text, kw)))

    await feed(bridge, [event("realtime.transcript", text="Est-ce qu'on est à jour au niveau des commits ?", item_id="i1")])

    assert len(requested) == 1
    text, options = requested[0]
    assert text.startswith("Est-ce qu'on est à jour")
    assert options["correlation_id"].endswith(":i1")


async def test_short_social_turns_and_doubtful_turns_get_no_acknowledgement():
    requested: list[str] = []
    clock = ManualClock()
    session = ControllableSession()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=CONVERSATION, session=session, reflex_delay_s=.05)
    scheduler._running = True
    def gate(text, **kwargs):
        requested.append(text)
        scheduler.request_reflex(text, **kwargs)
    bridge = build_bridge(GuardedAudio(guarded=False), clock=clock, on_reflex=gate)

    await feed(bridge, [event("realtime.transcript", text="Merci !", item_id="i1")])
    clock.now += 120  # la conversation n'est plus engagée
    await feed(bridge, [event("realtime.transcript", text="Tu viens déjeuner avec nous ?", item_id="i2")])

    assert requested == ["Merci !"]  # Admitted social input reaches explicit WAIT policy.
    assert scheduler._reflex is None and session.reflexes == []
    await scheduler.stop()


async def test_outside_the_engagement_window_a_turn_is_uncertain_unless_jarvis_is_named():
    clock = ManualClock()
    core = RecordingCore()
    bridge = build_bridge(GuardedAudio(guarded=False), core=core, clock=clock)
    clock.now += 120

    await feed(
        bridge,
        [
            event("realtime.transcript", text="Tu viens déjeuner avec nous ?", item_id="i1"),
            event("realtime.transcript", text="Jarvis, quelle heure est-il ?", item_id="i2"),
        ],
    )

    assert [(turn["content"], turn["addressing"]) for turn in core.brain_turns] == [
        ("Tu viens déjeuner avec nous ?", "uncertain"),
        ("Jarvis, quelle heure est-il ?", "addressed"),
    ]


async def _surface_states(bridge) -> list[str]:  # noqa: ANN001
    states: list[str] = []
    bridge.on_idle = lambda: states.append("idle")
    bridge.on_listening = lambda: states.append("listening")
    bridge.on_thinking = lambda: states.append("thinking")
    return states


async def test_outside_the_engagement_window_the_surface_stays_idle():
    """Une phrase qui n'était pas pour JARVIS n'allume ni l'écoute ni le traitement.

    Le commit du VAD tombe sur n'importe quelle voix de la pièce : s'y fier
    pour afficher « traitement » donne à l'utilisateur l'impression que JARVIS
    s'est déclenché pour lui. Le doute part quand même au cerveau (Décision
    44) : la session n'est pas rendue sourde, elle est rendue discrète.
    """

    clock = ManualClock()
    core = RecordingCore()
    bridge = build_bridge(GuardedAudio(guarded=False), core=core, clock=clock)
    states = await _surface_states(bridge)
    clock.now += 120  # la conversation n'est plus engagée

    await feed(
        bridge,
        [
            event("realtime.input_committed", item_id="i1"),
            event("realtime.transcript", text="Tu viens déjeuner avec nous ?", item_id="i1"),
        ],
    )

    assert states == ["idle"]
    assert [turn["addressing"] for turn in core.brain_turns] == ["uncertain"]


async def test_a_named_sentence_still_wakes_the_surface_after_the_window():
    """Le réveil explicite passe toujours : la veille ne rend pas JARVIS sourd."""

    clock = ManualClock()
    core = RecordingCore()
    bridge = build_bridge(GuardedAudio(guarded=False), core=core, clock=clock)
    states = await _surface_states(bridge)
    clock.now += 120

    await feed(
        bridge,
        [
            event("realtime.input_committed", item_id="i1"),
            event("realtime.transcript", text="Jarvis, quelle heure est-il ?", item_id="i1"),
        ],
    )

    assert states == ["thinking"]
    assert [turn["addressing"] for turn in core.brain_turns] == ["addressed"]


async def test_the_scheduler_learns_when_the_user_speaks():
    states: list[bool] = []
    bridge = build_bridge(GuardedAudio(guarded=False), on_user_speech=states.append)

    await feed(bridge, [event("realtime.speech_started"), event("realtime.speech_stopped")])

    assert states == [True, False]


async def test_a_barge_in_also_cuts_an_output_that_has_not_played_yet():
    """Revue du 11/09, défaut 1 : la sortie suivante est reçue, pas encore jouée.

    La phrase R0 vient de finir ; R1 commence chez le fournisseur mais son
    `output_started` attend encore dans la file de lecture. L'utilisateur parle :
    R1 doit être coupée — ses blocs à venir jetés — et le curseur de R0, déjà
    entendue en entier, ne doit pas servir.
    """

    release = threading.Event()

    class SlowStream:
        latency = 0.0
        writes = 0

        def write(self, block) -> None:  # noqa: ANN001
            SlowStream.writes += 1
            if SlowStream.writes == 2:
                assert release.wait(5)

        def abort(self, *, ignore_errors=True) -> None:
            return None

        def start(self) -> None:
            return None

    audio = SoundDeviceRealtimeAudio()
    audio._output = SlowStream()
    session, journal = ControllableSession(), RecordingJournal()
    interruptions: list[object] = []
    bridge = build_bridge(audio, session=session, journal=journal)
    bridge.on_interruption = interruptions.append
    queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()

    async def stream():
        while (item := await queue.get()) is not None:
            yield item

    running = asyncio.create_task(bridge._consume(stream()))
    # R0 : un bloc, qui bloque le lecteur au deuxième bloc (celui de R1).
    await queue.put(event("realtime.output_started", output_id="out-0", speech_id="speech-0"))
    await queue.put(audio_delta(1, output_id="out-0", speech_id="speech-0"))
    await queue.put(event("realtime.response_done", status="completed", output_id="out-0", speech_id="speech-0"))
    await queue.put(event("realtime.output_started", output_id="out-1", speech_id="speech-1"))
    await queue.put(audio_delta(1, output_id="out-1", speech_id="speech-1"))
    await until(lambda: SlowStream.writes == 2)
    # Le premier bloc de R1 est dans PortAudio ; l'utilisateur coupe.
    await queue.put(event("realtime.speech_started"))
    await until(lambda: bridge._drop_audio_before > 0)
    release.set()
    await until(lambda: journal.count("voice.barge_in") == 1)
    # Le fournisseur n'a pas encore vu l'annulation : R1 envoie encore.
    await queue.put(audio_delta(3, output_id="out-1", speech_id="speech-1"))
    await queue.put(None)
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert SlowStream.writes == 2  # rien de R1 après la coupure
    assert bridge._interrupted_speech_id == "speech-1"  # et non R0, entendue en entier
    assert "cancel_output" in session.calls


async def test_a_barge_in_before_any_audio_of_the_new_output_uses_no_stale_cursor():
    audio = GuardedAudio(guarded=False)
    session = ControllableSession()
    interruptions: list[object] = []
    core = RecordingCore()
    bridge = build_bridge(audio, session=session, core=core)
    bridge.on_interruption = interruptions.append

    # R0 entendue en entier.
    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-0", speech_id="speech-0"),
            audio_delta(2, output_id="out-0", speech_id="speech-0", item_id="item-0"),
            event("realtime.response_done", status="completed", output_id="out-0", speech_id="speech-0"),
        ],
    )
    # R1 reçue d'un bloc avec la parole de l'utilisateur, sans rythme temps réel.
    await bridge._consume(
        _burst(
            [
                event("realtime.output_started", output_id="out-1", speech_id="speech-1"),
                audio_delta(2, output_id="out-1", speech_id="speech-1"),
                event("realtime.speech_started"),
                event("realtime.transcript", text="Jarvis, attends.", item_id="item-u"),
            ]
        )
    )

    assert interruptions and interruptions[0] is None  # pas le curseur de R0
    assert core.brain_turns[-1]["interrupted_speech_id"] == "speech-1"


async def _burst(events: list[ProtocolEnvelope]):
    for item in events:
        yield item


async def test_legacy_mode_keeps_the_exact_order_of_the_stream():
    """Le legacy n'a rien à couper : un évènement ne double jamais l'audio."""

    seen: list[str] = []
    audio = GuardedAudio(guarded=False)
    bridge = build_bridge(audio, continuous=False)
    bridge.on_thinking = lambda: seen.append("thinking")
    bridge.on_speaking = lambda: seen.append("speaking")

    await bridge._consume(
        _burst(
            [
                event("realtime.output_started", output_id="out-0"),
                audio_delta(1, output_id="out-0"),
                event("realtime.input_committed", item_id="i1"),
                audio_delta(1, output_id="out-0"),
            ]
        )
    )

    assert seen == ["speaking", "thinking", "speaking"]


async def test_a_noise_segment_returns_the_face_to_listening():
    states: list[str] = []
    bridge = build_bridge(GuardedAudio(guarded=False))
    bridge.on_thinking = lambda: states.append("thinking")
    bridge.on_listening = lambda: states.append("listening")

    await feed(bridge, [event("realtime.input_committed", item_id="i1"), event("realtime.transcript", text="", item_id="i1")])

    assert states == ["thinking", "listening"]


async def test_a_cut_between_the_call_and_the_writer_thread_plays_nothing():
    """Revue du 11/09, défaut 6 : l'époque est figée avant de passer au thread."""

    written: list[bytes] = []

    class Stream:
        latency = 0.0

        def write(self, block) -> None:  # noqa: ANN001
            written.append(bytes(block))

        def abort(self, *, ignore_errors=True) -> None:
            return None

        def start(self) -> None:
            return None

    audio = SoundDeviceRealtimeAudio()
    audio._output = Stream()
    with audio._cursor_lock:
        epochs = (audio._output_epoch, audio._playback_epoch)
    await audio.stop_output()  # la coupure passe entre l'appel et le thread
    await asyncio.to_thread(audio._write_output, tone(0.2, amplitude=0.3), epochs)

    assert written == []


def test_the_cursor_counts_from_the_start_of_the_item_actually_playing():
    """Crash du 11/09 12:41 : préambule de 4,45 s puis texte, coupé à 23,9 s.

    La troncature visait le premier élément avec la durée de toute la réponse ;
    le fournisseur refusait (« Audio content of 4450ms is already shorter than
    23868ms ») et Voice tombait.
    """

    audio = SoundDeviceRealtimeAudio()
    ms = lambda value: int(value * 48)  # noqa: E731 - octets pour `value` ms à 24 kHz
    audio.set_active_output(output_id="out-1", speech_id="speech-1", item_id="item-preamble")
    audio._credit_written(audio._output_epoch, ms(4450))
    audio.set_active_output(output_id="out-1", speech_id="speech-1", item_id="item-text")
    audio._credit_written(audio._output_epoch, ms(19418))

    cursor = audio.playback_cursor()

    assert cursor.provider_item_id == "item-text"
    assert cursor.played_ms == 19418


async def test_the_adapter_never_truncates_beyond_what_an_item_contains():
    from jarvis.domain.v2 import PlaybackCursor

    websocket = FakeWebSocket()
    session = OpenAIRealtimeSession(websocket, object(), owns_http=False)  # type: ignore[arg-type]
    output = session._register_output(speech_id="speech-1")
    output.item_id = "item-preamble"
    output.item_audio_ms["item-preamble"] = 4450.0

    await session.truncate(PlaybackCursor(speech_id="speech-1", played_ms=23868, provider_item_id="item-preamble"))

    assert websocket.sent[-1]["audio_end_ms"] == 4450


async def test_a_refused_truncation_does_not_kill_voice():
    audio = GuardedAudio(guarded=False)
    journal = RecordingJournal()
    bridge = build_bridge(audio, journal=journal)

    await feed(
        bridge,
        [
            event("realtime.output_started", output_id="out-1", speech_id="speech-1"),
            audio_delta(2, output_id="out-1", speech_id="speech-1", item_id="item-1"),
            event("realtime.speech_started"),
            event(
                "realtime.error",
                error={"code": "invalid_value", "message": "Audio content of 4450ms is already shorter than 23868ms"},
            ),
        ],
    )

    assert journal.count("voice.barge_in") == 1
    assert journal.count("provider.error") == 0
    assert "invalid_value" in {item["data"]["code"] for item in journal.of("voice.barge_in_degraded")}


async def test_a_refused_overlapping_response_does_not_kill_the_session():
    journal = RecordingJournal()
    bridge = build_bridge(GuardedAudio(guarded=False), journal=journal)

    await feed(
        bridge,
        [event("realtime.error", error={"code": "conversation_already_has_active_response", "message": "busy"})],
    )

    assert journal.count("voice.provider_refused") == 1


async def test_a_refused_tool_result_does_not_kill_the_session():
    """13/09 : l'accusé de délégation refusé fermait Voice alors que le job tournait."""
    journal = RecordingJournal()
    bridge = build_bridge(GuardedAudio(guarded=False), journal=journal)

    await feed(
        bridge,
        [event("realtime.error", error={"code": "invalid_tool_call_id", "message": "voice_provider_failed"})],
    )

    assert journal.count("provider.error") == 0
    assert "invalid_tool_call_id" in {item["data"]["code"] for item in journal.of("voice.provider_refused")}


# --------------------------------------------------------------------------
# 4. L'ordonnanceur : accusé de réception et tour de parole


class EmptyCore:
    async def speech_context(self, conversation_id):
        return context(conversation_id, "c1")

    async def events(self, *, on_connected=None):
        if on_connected is not None:
            on_connected()
        await asyncio.Event().wait()
        yield  # pragma: no cover

    async def append_turn(self, *args, **kwargs):  # noqa: ANN002,ANN003
        return {}


def brain_speech(correlation_id: str) -> ProtocolEnvelope:
    request = SpeechRequest(
        conversation_id=CONVERSATION,
        text="Tout est commité.",
        kind=SpeechKind.RESULT,
        priority=SpeechPriority.HIGH,
        correlation_id=correlation_id,
        source=source(correlation_id),
    )
    return ProtocolEnvelope(message_type="brain.speech.requested", payload=request.to_payload())


async def test_an_acknowledgement_is_spoken_when_the_brain_is_slow():
    session, journal = ControllableSession(), RecordingJournal()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=CONVERSATION, session=session, journal=journal, reflex_delay_s=0.05)
    await scheduler.start()
    try:
        await scheduler.handle_core_event(ProtocolEnvelope(message_type="brain.work.started", payload={
            "conversation_id": CONVERSATION, "correlation_id": "c1", "work_id": "work-1"}))
        scheduler.request_reflex("Est-ce qu'on est à jour au niveau des commits ?", correlation_id="c1", avoid=("Je regarde.",))
        await until(lambda: session.reflexes)
    finally:
        await scheduler.stop()

    assert session.reflexes == [{"transcript": "Est-ce qu'on est à jour au niveau des commits ?", "avoid": ("Je regarde.",)}]
    assert journal.count("voice.reflex.started") == 1


async def test_a_fast_brain_answer_makes_the_acknowledgement_unnecessary():
    session, journal = ControllableSession(), RecordingJournal()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=CONVERSATION, session=session, journal=journal, reflex_delay_s=0.2)
    await scheduler.start()
    try:
        scheduler.request_reflex("Est-ce qu'on est à jour ?", correlation_id="c1")
        await scheduler.handle_core_event(brain_speech("c1"))
        await until(lambda: session.spoken)
        await asyncio.sleep(0.3)
    finally:
        await scheduler.stop()

    assert session.reflexes == []
    assert journal.of("voice.reflex.skipped")[0]["data"]["reason"] == "brain_answered"


async def test_jarvis_waits_for_the_user_to_finish_before_speaking():
    session = ControllableSession()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=CONVERSATION, session=session, user_speech_hold_s=2.0)
    await scheduler.start()
    try:
        scheduler.note_user_speech(True)
        await scheduler.handle_core_event(brain_speech("c1"))
        await asyncio.sleep(0.1)
        assert session.spoken == []
        scheduler.note_user_speech(False)
        await until(lambda: session.spoken)
    finally:
        await scheduler.stop()


async def test_an_acknowledgement_is_dropped_when_the_user_speaks_again():
    """Revue du 11/09, défaut 5 : pas d'accusé périmé au milieu d'une nouvelle phrase."""

    session, journal = ControllableSession(), RecordingJournal()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=CONVERSATION, session=session, journal=journal, reflex_delay_s=0.05)
    await scheduler.start()
    try:
        scheduler.request_reflex("Est-ce qu'on est à jour au niveau des commits ?", correlation_id="c1")
        scheduler.note_user_speech(True)
        await asyncio.sleep(0.1)
        scheduler.note_user_speech(False)
        await asyncio.sleep(0.1)
    finally:
        await scheduler.stop()

    assert session.reflexes == []
    assert journal.of("voice.reflex.skipped")[0]["data"]["reason"] == "user_speaking"


async def test_a_long_answer_still_playing_locally_is_not_taken_for_a_stall():
    """Revue du 11/09, défaut 4 : le fournisseur a fini de générer, pas de jouer."""

    session, journal = ControllableSession(), RecordingJournal()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=CONVERSATION, session=session, journal=journal, output_timeout_s=0.05)
    playing = {"active"}
    scheduler.output_alive = lambda output_id: bool(playing) and output_id == getattr(session, "reserved_output_id", None)
    await scheduler.start()
    try:
        await scheduler.handle_core_event(brain_speech("c1"))
        await scheduler.handle_core_event(brain_speech("c2"))
        await until(lambda: session.spoken)
        await asyncio.sleep(0.3)  # six délais de vérification
        assert len(session.spoken) == 1  # la seconde attend
        playing.clear()
        await until(lambda: len(session.spoken) == 2)
    finally:
        await scheduler.stop()


async def test_a_disabled_acknowledgement_is_never_spoken():
    session = ControllableSession()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=CONVERSATION, session=session, reflex_delay_s=0)
    await scheduler.start()
    try:
        scheduler.request_reflex("Est-ce qu'on est à jour ?", correlation_id="c1")
        await asyncio.sleep(0.1)
    finally:
        await scheduler.stop()

    assert session.reflexes == []


# --------------------------------------------------------------------------
# 5. Le fournisseur : plus de réponse ni de coupure automatiques en continu


def test_continuous_mode_takes_back_response_creation_and_interruption():
    vad = build_turn_detection(continuous_brain=True, threshold=0.6)

    assert vad["create_response"] is False
    assert vad["interrupt_response"] is False
    assert vad["threshold"] == 0.6


def test_legacy_mode_keeps_automatic_responses():
    vad = build_turn_detection(continuous_brain=False)

    assert vad["create_response"] is True and vad["interrupt_response"] is True


def test_semantic_vad_has_no_silence_threshold():
    vad = build_turn_detection(continuous_brain=True, vad_type="semantic_vad", eagerness="low", threshold=0.7)

    assert vad == {"type": "semantic_vad", "eagerness": "low", "create_response": False, "interrupt_response": False}


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


class FakeHttp:
    def __init__(self) -> None:
        self.ws = FakeWebSocket()

    async def ws_connect(self, url: str, **kwargs: object):  # noqa: ANN401
        del url, kwargs
        return self.ws

    async def close(self) -> None:
        return None


async def test_the_session_asks_for_noise_reduction_and_a_fixed_language():
    http = FakeHttp()

    await OpenAIRealtimeSession.connect(
        api_key="k",
        model="m",
        voice="cedar",
        context={},
        continuous_brain=True,
        transcription_model="gpt-4o-transcribe",
        transcription_language="fr",
        noise_reduction="far_field",
        session=http,  # type: ignore[arg-type]
    )

    audio_input = http.ws.sent[0]["session"]["audio"]["input"]
    assert audio_input["transcription"] == {"model": "gpt-4o-transcribe", "language": "fr"}
    assert audio_input["noise_reduction"] == {"type": "far_field"}
    assert audio_input["turn_detection"]["create_response"] is False


async def test_a_reflex_is_a_single_tracked_response_without_a_user_turn():
    websocket = FakeWebSocket()
    session = OpenAIRealtimeSession(websocket, object(), owns_http=False)  # type: ignore[arg-type]

    output_id = await session.speak_reflex(transcript="Vérifie les commits", avoid=("Je regarde.",))

    assert supports_reflex(session)
    assert [message["type"] for message in websocket.sent] == ["response.create"]
    response = websocket.sent[0]["response"]
    assert response["metadata"] == {OUTPUT_ID_METADATA_KEY: output_id}
    assert "Vérifie les commits" in response["instructions"]
    assert "« Je regarde. »" in response["instructions"]


def test_the_reflex_instruction_keeps_the_truth_boundary():
    instruction = build_reflex_instruction("Pousse les commits")

    assert "Interdit : donner la réponse ou un résultat" in instruction
    assert "Ne reprends aucune" not in instruction


def test_the_new_settings_are_exposed_in_the_control_center():
    keys = {field.key for field in voice_stack.OPENAI_REALTIME.fields}

    assert {"echo_cancellation", "noise_reduction", "transcription_language", "ack_delay_ms", "vad_type", "vad_eagerness"} <= keys
    defaults = voice_stack.OPENAI_REALTIME.defaults()
    assert defaults["echo_cancellation"] is True
    assert defaults["noise_reduction"] == "far_field"
    assert defaults["transcription_language"] == "fr"
