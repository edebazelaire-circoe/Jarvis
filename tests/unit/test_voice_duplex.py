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

from jarvis.adapters.openai_realtime import (
    OUTPUT_ID_METADATA_KEY,
    OpenAIRealtimeSession,
    build_reflex_instruction,
    build_turn_detection,
)
from jarvis.audio.duplex import NEAR_END, CaptureProcessor, NearEndDetector, frame_db
from jarvis.domain.v2 import AddressingDecision, ProtocolEnvelope, SpeechKind, SpeechPriority, SpeechRequest
from jarvis.ports.v2 import supports_reflex
from jarvis.runtime import voice_stack
from jarvis.runtime.realtime_audio import (
    NEAR_END_SIGNAL,
    ConservativeAddressingClassifier,
    RealtimeConversationBridge,
    SoundDeviceRealtimeAudio,
)
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

    async def speak(self, request: SpeechRequest) -> str:
        self.spoken.append(request)
        self.calls.append("speak")
        return f"out-{len(self.spoken)}"

    async def speak_reflex(self, *, transcript: str, avoid=()) -> str:  # noqa: ANN001
        self.reflexes.append({"transcript": transcript, "avoid": tuple(avoid)})
        self.calls.append("speak_reflex")
        return f"reflex-{len(self.reflexes)}"

    async def cancel_output(self, cursor=None) -> None:  # noqa: ANN001
        self.calls.append("cancel_output")

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

    def release_near_end(self) -> None:
        self.released += 1

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

        def abort(self) -> None:
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

        def abort(self) -> None:
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


async def test_local_speech_ducks_jarvis_then_the_provider_confirms_the_cut():
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
    assert audio.gains[-1] == pytest.approx(bridge.barge_in_duck_gain)
    assert audio.stop_output_calls == 0

    await queue.put(event("realtime.speech_started"))
    await until(lambda: journal.count("voice.barge_in") == 1)
    await queue.put(None)
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert audio.stop_output_calls == 1


async def test_unconfirmed_local_speech_restores_jarvis():
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

    assert audio.gains[-1] == 1.0
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
    bridge = build_bridge(
        GuardedAudio(guarded=False), clock=clock, on_reflex=lambda text, **kw: requested.append(text)
    )

    await feed(bridge, [event("realtime.transcript", text="Merci !", item_id="i1")])
    clock.now += 120  # la conversation n'est plus engagée
    await feed(bridge, [event("realtime.transcript", text="Tu viens déjeuner avec nous ?", item_id="i2")])

    assert requested == []


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

        def abort(self) -> None:
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

        def abort(self) -> None:
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


async def test_a_refused_overlapping_response_does_not_kill_the_session():
    journal = RecordingJournal()
    bridge = build_bridge(GuardedAudio(guarded=False), journal=journal)

    await feed(
        bridge,
        [event("realtime.error", error={"code": "conversation_already_has_active_response", "message": "busy"})],
    )

    assert journal.count("voice.provider_refused") == 1


# --------------------------------------------------------------------------
# 4. L'ordonnanceur : accusé de réception et tour de parole


class EmptyCore:
    async def events(self):
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
    )
    return ProtocolEnvelope(message_type="brain.speech.requested", payload=request.to_payload())


async def test_an_acknowledgement_is_spoken_when_the_brain_is_slow():
    session, journal = ControllableSession(), RecordingJournal()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=CONVERSATION, session=session, journal=journal, reflex_delay_s=0.05)
    await scheduler.start()
    try:
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
    playing = {"out-1"}
    scheduler.output_alive = lambda output_id: output_id in playing
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
