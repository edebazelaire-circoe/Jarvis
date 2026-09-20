"""Tampon de vérification du propriétaire et rejeu du début de phrase (tâche 06).

Handoff `tasks/jarvis_solo_owner_duplex_handoff/`, D07, D08, D09, spec §1.4–1.5.
Ce fichier prouve, pour la garde confiée au propriétaire (Solo Owner) :

- que le début de phrase survit à 0,5 / 1 / 2 s et plus de vérification, à
  16, 24 et 48 kHz, et que le tampon trop court est tronqué et signalé ;
- que rien n'est envoyé deux fois ni dans le désordre — pré-roll, garde
  ouverte, rejeu et direct confondus, même quand les commandes arrivent d'un
  autre fil pendant que la capture tourne ;
- qu'un étranger qui parlait avant le propriétaire n'est pas rejoué, et que sa
  voix n'atteint pas le fournisseur pendant que JARVIS parle ;
- que le tampon est borné, remis à zéro avec la session, absent en salle
  ouverte, et que la salle ouverte reste identique à l'octet près ;
- côté bridge : arrêt local, puis annulation et troncature, puis rejeu ; la
  trace `voice.owner.replay` ; le `speech_started` du fournisseur corrélé au
  rejeu ; le verrou acoustique qui ne se relâche plus sur une voix soutenue.

Chaque trame de test porte son indice dans ses échantillons : la sortie se lit
comme une suite d'indices (0 = silence envoyé à la place du micro).
"""

from __future__ import annotations

import asyncio
import math
import random
import threading

import numpy as np
import pytest

from jarvis.audio.duplex import FRAME_MS, OWNER_REPLAY, CaptureProcessor, NearEndDiagnostics, OwnerReplay
from jarvis.domain.speaker import OwnerState, OwnerStateSnapshot, VerifierAvailability
from jarvis.runtime.realtime_audio import (
    BARGE_IN_OWNER_CONFIRMED_KIND,
    BARGE_IN_PROVIDER_ADVISORY_KIND,
    NEAR_END_SIGNAL,
    OWNER_REPLAY_DROPPED_SIGNAL,
    OWNER_REPLAY_KIND,
    OWNER_REPLAY_SIGNAL,
    SoundDeviceRealtimeAudio,
)
from tests.unit.test_owner_barge_in import (
    ControllableSession,
    FakeOwnerSource,
    Live,
    ManualClock,
    RecordingAudio,
    RecordingJournal,
    build_bridge,
    event,
    jarvis_speaking,
    snapshot,
    until,
)

RATE = 24000
BASE = 1000  # échantillon d'une trame = BASE + indice
MARGIN_FRAMES = CaptureProcessor(capture_rate=RATE, render_rate=RATE).owner_replay_margin_ms // FRAME_MS


# --------------------------------------------------------------------------
# Outillage


class ScriptedDetector:
    """Détecteur de parole proche piloté : JARVIS audible et verrou à la trame près."""

    def __init__(self, *, far=lambda index: True, confirm_at=()) -> None:  # noqa: ANN001
        self.far = far
        self.confirm_at = set(confirm_at)
        self.index = -1
        self.latched = False
        self.last_near = False
        self.coupling_db = self.initial_coupling_db = 0.0
        self.latched_excess_db = None
        self.warmup_frames = 0
        self._refractory = 0
        self._far_frames = 0

    @property
    def far_recent(self) -> bool:
        return bool(self.far(self.index))

    def diagnostics(self, *, guard_open: bool, echo_lead_ms: int = 0,
                    echo_lead_confidence: float = 0.0) -> NearEndDiagnostics:
        return NearEndDiagnostics(
            mic_db=-30.0, ref_env_db=-20.0, floor_db=-60.0, coupling_db=self.coupling_db,
            excess_db=-10.0, margin_db=0.0, far_frames=self._far_frames, warming_up=False,
            latched=self.latched, guard_open=guard_open,
            echo_lead_ms=echo_lead_ms, echo_lead_confidence=echo_lead_confidence,
        )

    def update(self, mic_db: float, ref_db: float) -> bool:
        del mic_db, ref_db
        self.index += 1
        confirmed = self.index in self.confirm_at and not self.latched
        self.latched = (self.latched or confirmed) and self.far_recent
        return confirmed

    def release(self) -> None:
        self.latched = False

    def _reset_window(self) -> None:
        return None


def frames(start: int, stop: int, *, rate: int = RATE, base: int = BASE) -> bytes:
    size = rate // 100
    return b"".join(np.full(size, base + index, dtype=np.int16).tobytes() for index in range(start, stop))


def decode(pcm: bytes, *, rate: int = RATE, base: int = BASE) -> list[int | None]:
    """Indices des trames envoyées ; None pour une trame de silence."""

    size = rate // 100
    samples = np.frombuffer(pcm, dtype=np.int16)
    assert len(samples) % size == 0
    out: list[int | None] = []
    for offset in range(0, len(samples), size):
        frame = samples[offset:offset + size]
        if not frame.any():
            out.append(None)
            continue
        assert (frame == frame[0]).all(), "une trame a été coupée ou mélangée"
        out.append(int(frame[0]) - base)
    return out


def sent(pcm: bytes, **options) -> list[int]:  # noqa: ANN003
    return [index for index in decode(pcm, **options) if index is not None]


def owner_capture(*, rate: int = RATE, buffer_ms: int = 2500, far=lambda index: True, confirm_at=(), **options):  # noqa: ANN001, ANN003, ANN202
    processor = CaptureProcessor(
        capture_rate=rate,
        render_rate=rate,
        detector=ScriptedDetector(far=far, confirm_at=confirm_at),  # type: ignore[arg-type]
        owner_buffer_ms=buffer_ms,
        **options,
    )
    assert processor.set_owner_gate(True)
    return processor


def feed(processor: CaptureProcessor, start: int, stop: int, *, rate: int = RATE, block_frames: int = 5, base: int = BASE):  # noqa: ANN202
    """Blocs de 50 ms comme PortAudio ; rend (audio envoyé, signaux)."""

    out = bytearray()
    signals: list[str] = []
    for first in range(start, stop, block_frames):
        chunk, emitted = processor.process(frames(first, min(stop, first + block_frames), rate=rate, base=base))
        out += chunk
        signals.extend(emitted)
    return bytes(out), signals


def strictly_increasing(indices: list[int]) -> bool:
    return all(later > earlier for earlier, later in zip(indices, indices[1:]))


# --------------------------------------------------------------------------
# 1. Le début de phrase survit à la vérification


@pytest.mark.parametrize("rate", [16000, 24000, 48000])
@pytest.mark.parametrize("delay_ms", [500, 1000, 2000, 2300])
def test_the_sentence_start_survives_the_verification_delay(rate, delay_ms):  # noqa: ANN001
    """JARVIS parle ; le propriétaire commence à 3 s, confirmé `delay_ms` plus tard."""

    onset = 300
    confirm = onset + delay_ms // FRAME_MS
    processor = owner_capture(rate=rate)

    before, _ = feed(processor, 0, confirm, rate=rate)
    assert sent(before, rate=rate) == []  # JARVIS audible : rien que du silence
    processor.open_owner_flow(onset * FRAME_MS, candidate_onset_ms=onset * FRAME_MS)
    after, signals = feed(processor, confirm, confirm + 100, rate=rate)

    first = onset - MARGIN_FRAMES
    assert sent(after, rate=rate) == list(range(first, confirm + 100))  # une fois, dans l'ordre, sans trou
    assert set(range(onset, onset + 20)) <= set(sent(after, rate=rate))  # les premières syllabes
    assert signals.count(OWNER_REPLAY) == 1
    (replay,) = processor.take_owner_replays()
    assert replay == OwnerReplay(
        owner_onset_ms=onset * FRAME_MS,
        requested_from_ms=first * FRAME_MS,
        from_ms=first * FRAME_MS,
        until_ms=confirm * FRAME_MS,
        replay_ms=(confirm - first) * FRAME_MS,
        margin_ms=MARGIN_FRAMES * FRAME_MS,
        already_sent_ms=0,
        clamped_ms=0,
        buffer_ms=2500,
    )
    assert processor.take_owner_replays() == ()


def test_a_verification_longer_than_the_buffer_replays_what_is_left_and_says_so():
    processor = owner_capture(buffer_ms=500)
    feed(processor, 0, 400)
    processor.open_owner_flow(2000, candidate_onset_ms=2000)  # confirmé 2 s après le début
    out, _ = feed(processor, 400, 420)

    assert sent(out) == list(range(350, 420))  # les 500 ms que le tampon garde
    (replay,) = processor.take_owner_replays()
    assert (replay.from_ms, replay.replay_ms, replay.buffer_ms) == (3500, 500, 500)
    assert replay.clamped_ms == 3500 - (2000 - MARGIN_FRAMES * FRAME_MS)
    assert replay.already_sent_ms == 0


def test_the_margin_is_clamped_to_the_start_of_the_stream():
    processor = owner_capture()
    feed(processor, 0, 50)
    processor.open_owner_flow(50, candidate_onset_ms=50)
    out, _ = feed(processor, 50, 55)

    assert sent(out) == list(range(0, 55))
    (replay,) = processor.take_owner_replays()
    assert replay.requested_from_ms == 0 and replay.clamped_ms == 0


def test_a_configurable_margin_of_zero_replays_from_the_onset_exactly():
    processor = owner_capture(owner_replay_margin_ms=0)
    feed(processor, 0, 200)
    processor.open_owner_flow(1200)
    out, _ = feed(processor, 200, 205)

    assert sent(out)[0] == 120


# --------------------------------------------------------------------------
# 2. Un étranger n'est ni rejoué ni entendu pendant que JARVIS parle


def test_a_stranger_talking_before_the_owner_is_not_replayed():
    """Candidat ouvert à 1 s par un étranger ; le propriétaire enchaîne à 1,8 s, sans marge."""

    processor = owner_capture()
    feed(processor, 0, 330)
    processor.open_owner_flow(1800, candidate_onset_ms=1000)
    out, _ = feed(processor, 330, 340)

    assert sent(out) == list(range(180, 340))
    (replay,) = processor.take_owner_replays()
    assert replay.margin_ms == 0 and replay.from_ms == 1800


def test_the_acoustic_latch_no_longer_forwards_near_end_while_jarvis_speaks():
    """La même voix ouvre la garde en salle ouverte, pas quand elle appartient au propriétaire."""

    acoustic = CaptureProcessor(
        capture_rate=RATE, render_rate=RATE, detector=ScriptedDetector(confirm_at={100}), owner_buffer_ms=2500  # type: ignore[arg-type]
    )
    open_room, open_signals = feed(acoustic, 0, 200)
    owner = owner_capture(confirm_at={100})
    solo, solo_signals = feed(owner, 0, 200)

    assert sent(open_room)[0] < 100 and sent(open_room)[-1] == 199  # pré-roll puis direct
    assert sent(solo) == []  # le verrou n'ouvre rien : aucune voix ne part en tour
    assert solo_signals == open_signals == ["near_end"]  # le bridge est toujours prévenu du candidat
    assert owner.near_end_active and not owner.gate_open


def test_a_rejection_closes_the_flow_again_while_jarvis_speaks():
    processor = owner_capture()
    feed(processor, 0, 200)
    processor.open_owner_flow(1500)
    first, _ = feed(processor, 200, 250)
    processor.close_owner_flow()
    second, _ = feed(processor, 250, 300)
    processor.open_owner_flow(2800, candidate_onset_ms=2000)  # le propriétaire reprend
    third, _ = feed(processor, 300, 320)

    assert sent(first)[-1] == 249
    assert sent(second) == []
    assert sent(third) == list(range(280, 320))  # rien de ce qui a déjà été envoyé, rien d'avant 2,8 s
    assert [replay.replay_ms for replay in processor.take_owner_replays()] == [
        (200 - (150 - MARGIN_FRAMES)) * FRAME_MS,
        200,
    ]


# --------------------------------------------------------------------------
# 3. Jamais deux fois, jamais dans le désordre


def test_frames_the_open_guard_already_sent_are_not_replayed():
    """Garde acoustique ouverte (JARVIS se tait) jusqu'à 1 s, puis au propriétaire ; confirmé à 2,5 s.

    Tâche 07 : garde au propriétaire, le silence de JARVIS n'ouvre plus rien ;
    c'est la garde acoustique d'avant la remise au propriétaire qui a envoyé.
    """

    processor = CaptureProcessor(
        capture_rate=RATE,
        render_rate=RATE,
        detector=ScriptedDetector(far=lambda index: index >= 100),  # type: ignore[arg-type]
        owner_buffer_ms=2500,
    )
    feed(processor, 0, 100)
    assert processor.set_owner_gate(True)
    feed(processor, 100, 250)
    processor.open_owner_flow(800, candidate_onset_ms=800)
    out, _ = feed(processor, 250, 260)
    whole = sent(feed(processor, 260, 261)[0])

    assert sent(out) == list(range(100, 260))
    assert whole == [260]
    (replay,) = processor.take_owner_replays()
    assert replay.from_ms == 1000 and replay.already_sent_ms == 1000 - (800 - MARGIN_FRAMES * FRAME_MS)


def test_frames_the_acoustic_preroll_sent_are_not_replayed():
    """Salle ouverte d'abord (garde acoustique, pré-roll vidé), puis la garde passe au propriétaire."""

    processor = CaptureProcessor(
        capture_rate=RATE,
        render_rate=RATE,
        detector=ScriptedDetector(far=lambda index: index < 150 or index >= 160, confirm_at={100}),  # type: ignore[arg-type]
        owner_buffer_ms=2500,
    )
    acoustic, _ = feed(processor, 0, 160)
    preroll = processor._preroll.maxlen
    assert sent(acoustic)[0] == 101 - preroll and sent(acoustic)[-1] == 159  # pré-roll, puis direct
    assert processor.set_owner_gate(True)
    gated, _ = feed(processor, 160, 250)
    processor.open_owner_flow(900, candidate_onset_ms=900)
    replayed, _ = feed(processor, 250, 255)

    assert sent(gated) == []
    assert sent(replayed) == list(range(160, 255))
    total = sent(acoustic + gated + replayed)
    assert strictly_increasing(total) and len(total) == len(set(total))


def test_the_acoustic_preroll_never_sends_what_the_owner_left_out():
    """Après un rejeu, un retour à la garde acoustique ne rattrape pas l'étranger d'avant."""

    processor = CaptureProcessor(
        capture_rate=RATE,
        render_rate=RATE,
        detector=ScriptedDetector(far=lambda index: index < 240 or index >= 245, confirm_at={250}),  # type: ignore[arg-type]
        owner_buffer_ms=2500,
        preroll_ms=1000,  # le pré-roll couvre encore l'étranger au moment du repli
    )
    assert processor.set_owner_gate(True)
    feed(processor, 0, 200)
    processor.open_owner_flow(1900, candidate_onset_ms=1500)  # étranger de 1,5 à 1,9 s
    out, _ = feed(processor, 200, 240)
    processor.set_owner_gate(False)  # vérificateur en panne : règle acoustique
    later, _ = feed(processor, 240, 260)

    everything = sent(out + later)
    assert everything[0] == 190 and strictly_increasing(everything)
    assert not set(range(150, 190)) & set(everything)


def test_the_flush_is_exactly_once_while_frames_keep_arriving_from_another_thread():
    """Commandes depuis un fil « boucle », capture dans un fil « PortAudio » : ordre et unicité tiennent."""

    processor = owner_capture(buffer_ms=1000)
    total_frames = 3000
    captured: list[bytes] = []
    replays: list[str] = []
    done = threading.Event()

    def capture() -> None:
        for first in range(0, total_frames, 5):
            chunk, signals = processor.process(frames(first, first + 5))
            captured.append(chunk)
            replays.extend(signal for signal in signals if signal == OWNER_REPLAY)
            if first % 50 == 0:
                threading.Event().wait(0.0005)
        done.set()

    def commands() -> None:
        rng = random.Random(6)
        while not done.is_set():
            now = processor.stream_ms
            if rng.random() < 0.5:
                processor.open_owner_flow(max(0, now - rng.randrange(0, 1500)))
            else:
                processor.close_owner_flow()
            threading.Event().wait(rng.uniform(0.0002, 0.003))

    workers = [threading.Thread(target=capture), threading.Thread(target=commands)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)

    indices = sent(b"".join(captured))
    assert len(replays) >= 5  # des ouvertures ont bien croisé le flux
    assert strictly_increasing(indices)  # ni doublon, ni retour en arrière
    assert len(processor._owner_replays) <= 4  # rapports bornés même sans lecteur


def test_each_opening_replays_a_contiguous_prefix_then_goes_live():
    processor = owner_capture(buffer_ms=1000)
    out = bytearray()
    reports: list[OwnerReplay] = []
    rng = random.Random(3)
    frame = 0
    for _ in range(40):
        step = rng.randrange(20, 120)
        chunk, _ = feed(processor, frame, frame + step)
        out += chunk
        frame += step
        if rng.random() < 0.6:
            processor.open_owner_flow(max(0, (frame - rng.randrange(0, 150)) * FRAME_MS))
        else:
            processor.close_owner_flow()
        reports.extend(processor.take_owner_replays())
    chunk, _ = feed(processor, frame, frame + 5)
    out += chunk
    reports.extend(processor.take_owner_replays())

    indices = sent(bytes(out))
    assert strictly_increasing(indices)
    assert reports
    present = set(indices)
    for replay in reports:
        assert set(range(replay.from_ms // FRAME_MS, replay.until_ms // FRAME_MS)) <= present


# --------------------------------------------------------------------------
# 4. Bornes, sessions, salle ouverte


def test_the_buffer_is_bounded_over_a_long_run():
    processor = owner_capture(rate=48000, buffer_ms=2500)
    size = 48000 // 100 * 2
    for first in range(0, 30_000, 50):  # cinq minutes de JARVIS audible
        processor.process(bytes(size * 50))
        if first % 1000 == 0:
            processor.open_owner_flow(processor.stream_ms)
            processor.close_owner_flow()

    ring = processor._owner_ring
    assert ring is not None and len(ring) == ring.maxlen == 250
    assert sum(len(item) for item in ring) == 250 * size  # 240 Ko à 48 kHz pour 2,5 s
    assert len(processor._preroll) <= processor._preroll.maxlen
    assert len(processor._owner_replays) <= 4


def test_a_session_reset_forgets_the_buffer_the_gate_and_any_pending_request():
    processor = owner_capture()
    feed(processor, 0, 200)
    processor.open_owner_flow(1000)
    processor.reset()

    assert processor.stream_ms == 0 and not processor.owner_gate
    out, signals = feed(processor, 0, 50, base=5000)  # nouvelle session, JARVIS audible
    assert OWNER_REPLAY not in signals and processor.take_owner_replays() == ()
    assert sent(out, base=5000) == [] and not processor.owner_gate  # garde acoustique, fermée

    assert processor.set_owner_gate(True)
    feed(processor, 50, 100, base=5000)
    processor.open_owner_flow(0)
    replayed, _ = feed(processor, 100, 101, base=5000)
    # Tout vient de la nouvelle session : une trame d'avant se lirait en indice négatif.
    assert sent(replayed, base=5000) == list(range(0, 101))


def test_open_room_has_no_owner_buffer_and_cannot_hand_over_the_gate():
    processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE)

    assert processor.owner_buffer_ms == 0 and processor._owner_ring is None
    assert processor.set_owner_gate(True) is False
    processor.open_owner_flow(0)  # sans effet
    out, signals = feed(processor, 0, 20)
    assert OWNER_REPLAY not in signals and processor.take_owner_replays() == ()


def _tone(seconds: float, *, amplitude: float, freq: float = 220.0) -> bytes:
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * np.sin(2 * math.pi * freq * t) * 32767).astype(np.int16).tobytes()


def _run(processor: CaptureProcessor, mic: bytes, reference: bytes) -> tuple[bytes, list[tuple[str, ...]]]:
    block, pushed, out, signals = 1200 * 2, 0, bytearray(), []
    for offset in range(0, len(mic), block):
        while pushed < min(len(reference), offset + 4800 * 2):
            processor.push_reference(reference[pushed:pushed + 4800])
            pushed += 4800
        chunk, emitted = processor.process(mic[offset:offset + block])
        out += chunk
        signals.append(emitted)
    return bytes(out), signals


def test_open_room_output_is_byte_for_byte_identical_with_or_without_the_buffer():
    """Détecteur réel : écho, parole par-dessus JARVIS, relâche, fin de parole."""

    reference = _tone(3.0, amplitude=0.3) + bytes(RATE * 2)
    user = bytes(int(RATE * 1.5) * 2) + _tone(1.2, amplitude=0.4, freq=180.0) + bytes(int(RATE * 1.3) * 2)
    echo = _tone(4.0, amplitude=0.02)
    mic = np.clip(
        np.frombuffer(user, dtype=np.int16).astype(np.int32) + np.frombuffer(echo, dtype=np.int16).astype(np.int32),
        -32768,
        32767,
    ).astype(np.int16).tobytes()

    runs = []
    for buffer_ms in (None, 2500):
        processor = CaptureProcessor(capture_rate=RATE, render_rate=RATE, owner_buffer_ms=buffer_ms)
        runs.append(_run(processor, mic, reference))
    baseline, with_buffer = runs

    assert any("near_end" in emitted for emitted in baseline[1])  # le scénario ouvre bien la garde
    assert with_buffer == baseline


# --------------------------------------------------------------------------
# 5. Bridge : arrêt local, fournisseur, puis rejeu ; trace et corrélation


class ReplayRig:
    """Capture réelle (détecteur piloté) derrière l'audio du bridge ; la boucle joue PortAudio."""

    def __init__(self, *, buffer_ms: int = 2500, far=lambda index: True) -> None:  # noqa: ANN001
        self.calls: list[str] = []
        self.processor = CaptureProcessor(
            capture_rate=RATE,
            render_rate=RATE,
            detector=ScriptedDetector(far=far),  # type: ignore[arg-type]
            owner_buffer_ms=buffer_ms,
        )
        self.audio = RecordingAudio(self.calls)
        self.audio.capture = self.processor
        self.source = FakeOwnerSource()
        self.journal = RecordingJournal()
        self.session = ControllableSession(self.calls)
        self.clock = ManualClock()
        self.bridge = build_bridge(
            self.audio, source=self.source, session=self.session, journal=self.journal, clock=self.clock, barge_in_confirm_s=0.05
        )
        self.sent = bytearray()
        self.frame = 0

    def capture(self, count: int) -> None:
        """Faire tourner la capture sur la boucle, signaux relayés comme `_deliver_capture`."""

        for _ in range(0, count, 5):
            chunk, signals = self.processor.process(frames(self.frame, self.frame + 5))
            self.frame += 5
            self.sent += chunk
            if "owner_replay" in signals:
                self.calls.append("replay")
            for signal in signals:
                self.bridge._on_capture_signal(signal)


@pytest.mark.parametrize("delay_ms", [500, 1000, 2000])
async def test_the_owner_cut_stops_locally_then_the_provider_then_replays_the_sentence(delay_ms):  # noqa: ANN001
    rig = ReplayRig()
    onset = 300
    confirm = onset + delay_ms // FRAME_MS
    async with Live(rig.bridge) as live:
        await live.send(*jarvis_speaking(chunks=3))
        assert rig.processor.owner_gate is False  # appliqué au premier bloc
        rig.capture(confirm)
        assert rig.processor.owner_gate and sent(bytes(rig.sent)) == []
        rig.source.publish(snapshot(1, onset=onset * FRAME_MS, confirmed=confirm * FRAME_MS))
        await until(lambda: rig.audio.stop_output_calls == 1)
        await live.idle()
        rig.capture(50)
        await live.idle()

    assert rig.calls == ["stop_output", "cancel_output", "truncate", "replay"]
    assert sent(bytes(rig.sent)) == list(range(onset - MARGIN_FRAMES, confirm + 50))
    (trace,) = rig.journal.of(OWNER_REPLAY_KIND)
    data = trace["data"]
    assert trace["level"] == "info" and data["barge_in"] is True
    assert (data["owner_onset_ms"], data["confirmed_ms"], data["stop_stream_ms"]) == (
        onset * FRAME_MS,
        confirm * FRAME_MS,
        confirm * FRAME_MS,
    )
    assert data["replay_from_ms"] == (onset - MARGIN_FRAMES) * FRAME_MS
    assert data["replay_until_ms"] == confirm * FRAME_MS and data["confirm_to_replay_ms"] == 0
    assert data["replay_ms"] == (confirm - onset + MARGIN_FRAMES) * FRAME_MS
    assert data["clamped_ms"] == 0 and data["buffer_ms"] == 2500 and "code" not in data
    # Scalaires seulement : ni audio, ni empreinte.
    assert all(value is None or isinstance(value, (int, float, str, bool)) for value in data.values())
    assert rig.journal.of(BARGE_IN_OWNER_CONFIRMED_KIND)[0]["data"]["owner_onset_ms"] == onset * FRAME_MS


async def test_a_clamped_replay_is_an_explicit_warning():
    rig = ReplayRig(buffer_ms=1000)
    async with Live(rig.bridge) as live:
        await live.send(*jarvis_speaking())
        rig.capture(500)
        rig.source.publish(snapshot(1, onset=1000, confirmed=5000))
        await until(lambda: rig.audio.stop_output_calls == 1)
        await live.idle()
        rig.capture(5)
        await live.idle()

    (trace,) = rig.journal.of(OWNER_REPLAY_KIND)
    assert trace["level"] == "warning" and trace["data"]["code"] == "owner_replay_clamped"
    assert trace["data"]["replay_ms"] == 1000 and trace["data"]["clamped_ms"] == (400 - (100 - MARGIN_FRAMES)) * FRAME_MS
    assert sent(bytes(rig.sent))[0] == 400


async def test_provider_speech_on_the_replay_is_correlated_with_its_length():
    rig = ReplayRig()
    async with Live(rig.bridge) as live:
        await live.send(*jarvis_speaking())
        rig.capture(200)
        rig.source.publish(snapshot(1, onset=1000, confirmed=2000))
        await until(lambda: rig.audio.stop_output_calls == 1)
        await live.idle()
        rig.capture(5)
        await live.idle()
        rig.clock.now += 0.4
        await live.send(event("realtime.speech_started", item_id="item-owner"))

    advisory = rig.journal.of(BARGE_IN_PROVIDER_ADVISORY_KIND)
    assert [item["data"]["relation"] for item in advisory] == ["after_owner_stop"]
    assert advisory[0]["data"]["lag_ms"] == 400 and advisory[0]["data"]["replay_ms"] == 1000 + MARGIN_FRAMES * FRAME_MS
    assert rig.audio.stop_output_calls == 1


async def test_a_confirmation_while_jarvis_is_silent_replays_the_sentence_without_cutting():
    """Tâche 07 : JARVIS silencieux, rien ne part avant la confirmation ; puis le début de phrase, une fois."""

    rig = ReplayRig(far=lambda index: False)
    async with Live(rig.bridge) as live:
        rig.capture(100)
        assert sent(bytes(rig.sent)) == []  # garde au propriétaire : le silence de JARVIS n'ouvre rien
        rig.source.publish(snapshot(1, far_end=False, onset=500, confirmed=900))
        await live.idle()
        rig.capture(5)
        await live.idle()

    assert rig.audio.stop_output_calls == 0 and rig.calls == ["replay"]  # ni arrêt, ni annulation
    assert sent(bytes(rig.sent)) == list(range(50 - MARGIN_FRAMES, 105))  # du début estimé, sans doublon
    (trace,) = rig.journal.of(OWNER_REPLAY_KIND)
    assert trace["data"]["barge_in"] is False and trace["data"]["replay_ms"] == 1000 - 500 + MARGIN_FRAMES * FRAME_MS


async def test_a_stranger_verdict_closes_the_flow_and_the_owner_reopens_it():
    rig = ReplayRig()
    async with Live(rig.bridge) as live:
        await live.send(*jarvis_speaking(chunks=6))
        rig.capture(200)
        rig.source.publish(snapshot(1, onset=1000, confirmed=2000))
        await until(lambda: rig.audio.stop_output_calls == 1)
        await live.idle()
        rig.capture(50)
        rig.source.publish(snapshot(2, state=OwnerState.REJECTED, onset=1000))
        await live.idle()
        rig.capture(50)
        # Le propriétaire reprend dans le même candidat, ouvert par l'étranger à 1 s.
        rig.source.publish(
            OwnerStateSnapshot(
                sequence=3,
                session=1,
                state=OwnerState.OWNER_CONFIRMED,
                stream_ms=3000,
                candidate_onset_ms=1000,
                owner_onset_ms=2800,
                confirmed_ms=3000,
                owner_score=0.9,
                evidence_ms=1500,
                far_end=True,
            )
        )
        await live.idle()
        rig.capture(10)
        await live.idle()

    indices = sent(bytes(rig.sent))
    assert strictly_increasing(indices)
    assert indices[0] == 100 - MARGIN_FRAMES
    assert not set(range(250, 280)) & set(indices)  # l'étranger, JARVIS toujours audible
    assert indices[-1] == 309 and set(range(280, 310)) <= set(indices)
    assert rig.audio.stop_output_calls == 1  # la seconde confirmation ne recoupe rien
    assert [item["data"]["barge_in"] for item in rig.journal.of(OWNER_REPLAY_KIND)] == [True, False]


async def test_a_verifier_failure_keeps_the_input_closed_and_ends_the_session():
    """Tâche 07 : jamais de repli sur la règle acoustique — la garde reste au propriétaire, flux fermé."""

    rig = ReplayRig(far=lambda index: index < 100)
    live = Live(rig.bridge)
    async with live:
        await live.send(*jarvis_speaking())
        rig.capture(20)
        rig.source.publish(snapshot(1, onset=0, confirmed=200))
        await until(lambda: rig.audio.stop_output_calls == 1)
        await live.idle()
        rig.capture(10)
        assert sent(bytes(rig.sent))[-1] == 29  # le propriétaire passe
        # Comme `ShadowOwnerTelemetry._fail` : disponibilité d'abord, puis un état `idle` publié.
        rig.source.availability = VerifierAvailability.FAILED
        rig.source.publish(snapshot(2, state=OwnerState.IDLE))
        await until(lambda: live.task.done())  # la session se désactive d'elle-même
        before = len(sent(bytes(rig.sent)))
        rig.capture(200)  # JARVIS se tait, quelqu'un parle : rien ne part

    assert rig.processor.owner_gate and len(sent(bytes(rig.sent))) == before
    assert rig.journal.of("voice.authorization_refused")[0]["data"]["code"] == "owner_verifier_unavailable"


async def test_the_gate_stays_with_the_owner_until_the_capture_is_reset():
    """Fin de session : flux refermé, garde gardée — rendre la main à la règle acoustique laisserait passer le micro brut."""

    rig = ReplayRig(far=lambda index: False)
    async with Live(rig.bridge):
        rig.capture(5)
        assert rig.processor.owner_gate
    rig.capture(50)

    assert rig.processor.owner_gate and sent(bytes(rig.sent)) == []
    rig.processor.reset()
    assert not rig.processor.owner_gate


async def test_the_latch_is_kept_while_the_verifier_candidate_is_open():
    """Le fournisseur n'entend plus la voix : son silence ne vaut plus « c'était de l'écho »."""

    rig = ReplayRig()
    async with Live(rig.bridge) as live:
        await live.send(*jarvis_speaking(chunks=20))
        rig.capture(5)
        rig.source.publish(snapshot(1, state=OwnerState.CANDIDATE))
        rig.bridge._on_capture_signal(NEAR_END_SIGNAL)
        await live.idle()
        await asyncio.sleep(0.2)  # quatre délais acoustiques
        await live.idle()
        assert rig.audio.released == 0 and rig.journal.count("voice.barge_in_rejected") == 0
        rig.source.publish(snapshot(2, state=OwnerState.IDLE))
        await until(lambda: rig.audio.released == 1)

    assert rig.journal.count("voice.barge_in_rejected") == 1
    assert rig.audio.stop_output_calls == 0 and rig.audio.gains == []


class _PassThroughCanceller:
    def process_render(self, frame: bytes) -> None:
        del frame

    def process_capture(self, frame: bytes) -> bytes:
        return frame


async def test_the_real_detector_and_verifier_thread_replay_the_owner_from_his_first_syllable():
    """JARVIS parle ; le propriétaire le coupe à 1,5 s. Rien ne part avant, tout part après, une fois."""

    from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
    from jarvis.audio.speaker_shadow import SpeakerVerificationWorker

    worker = SpeakerVerificationWorker(ScriptedSpeakerVerifier([0.99] * 40), sample_rate=RATE, max_pending_ms=60_000)
    processor = CaptureProcessor(
        capture_rate=RATE, render_rate=RATE, canceller=_PassThroughCanceller(), observer=worker, owner_buffer_ms=2500
    )
    audio, journal = RecordingAudio(), RecordingJournal()
    audio.capture = processor
    owner = bytes(int(RATE * 1.5) * 2) + _tone(1.5, amplitude=0.4, freq=180.0)
    echo = _tone(3.0, amplitude=0.02)
    mic = np.clip(
        np.frombuffer(owner, dtype=np.int16).astype(np.int32) + np.frombuffer(echo, dtype=np.int16).astype(np.int32),
        -32768,
        32767,
    ).astype(np.int16).tobytes()
    reference = _tone(3.0, amplitude=0.3)
    bridge = build_bridge(audio, source=worker, journal=journal)
    block, cut_at = 1200 * 2, RATE * 2 * 2  # blocs de 50 ms ; 2 s captées avant la coupure
    out, pushed = bytearray(), 0

    def run(start: int, stop: int) -> list[str]:
        nonlocal pushed
        signals: list[str] = []
        for offset in range(start, stop, block):
            while pushed < min(len(reference), offset + 4800 * 2):
                processor.push_reference(reference[pushed:pushed + 4800])
                pushed += 4800
            chunk, emitted = processor.process(mic[offset:offset + block])
            out.extend(chunk)
            signals.extend(emitted)
        return signals

    try:
        async with Live(bridge) as live:
            await live.send(*jarvis_speaking())
            await asyncio.to_thread(run, 0, cut_at)
            assert await asyncio.to_thread(worker.flush, 2.0)
            await until(lambda: audio.stop_output_calls == 1)
            await live.idle()
            for signal in await asyncio.to_thread(run, cut_at, len(mic)):
                bridge._on_capture_signal(signal)
            await live.idle()
    finally:
        processor.close()

    start = (1500 - processor.owner_replay_margin_ms) * RATE // 1000 * 2
    assert not any(out[:cut_at])  # ni écho ni voix pendant la vérification
    assert bytes(out[cut_at:]) == mic[start:]  # début de phrase, puis direct : une fois, dans l'ordre
    data = journal.of(OWNER_REPLAY_KIND)[0]["data"]
    assert (data["owner_onset_ms"], data["confirmed_ms"], data["replay_until_ms"]) == (1500, 1700, 2000)
    assert data["replay_ms"] == 2000 - 1500 + processor.owner_replay_margin_ms and data["clamped_ms"] == 0


def test_the_bridge_and_the_capture_agree_on_the_replay_signal():
    assert OWNER_REPLAY_SIGNAL == OWNER_REPLAY


# --------------------------------------------------------------------------
# 6. File d'envoi : le rejeu ne se perd pas en route


def _fill(audio: SoundDeviceRealtimeAudio, count: int, value: int = 1) -> None:
    for _ in range(count):
        audio._deliver_capture(4, bytes([value]) * 4, ())


def test_a_saturated_input_queue_drops_the_live_block_not_the_owner_replay():
    """Le fournisseur n'envoie plus ; la capture a déjà marqué le préfixe envoyé (`_sent_until`)."""

    audio = SoundDeviceRealtimeAudio()
    signals: list[str] = []
    audio.on_capture_signal = signals.append
    replay = b"\x2a\x2a\x2a\x2a"

    _fill(audio, 64)  # file pleine : plus rien ne part vers le fournisseur
    audio._deliver_capture(4, replay, (OWNER_REPLAY_SIGNAL,))
    _fill(audio, 300, value=2)  # le direct continue d'arriver, sans relâche

    queued = []
    while not audio._queue.empty():
        queued.append(audio._queue.get_nowait())
    assert replay in queued  # le début de phrase est toujours là
    assert audio.dropped_replays == 0 and OWNER_REPLAY_DROPPED_SIGNAL not in signals


def test_a_replay_that_is_lost_all_the_same_is_never_a_silent_success():
    """Deux rejeux coincés derrière un envoi bloqué : invraisemblable, mais jamais muet (spec §3)."""

    audio = SoundDeviceRealtimeAudio()
    signals: list[str] = []
    audio.on_capture_signal = signals.append

    _fill(audio, 64)
    audio._deliver_capture(4, b"\x2a\x2a\x2a\x2a", (OWNER_REPLAY_SIGNAL,))
    _fill(audio, 63, value=2)  # le premier rejeu est maintenant en tête de file
    audio._deliver_capture(4, b"\x2b\x2b\x2b\x2b", (OWNER_REPLAY_SIGNAL,))

    assert audio.dropped_replays == 1
    assert signals.count(OWNER_REPLAY_DROPPED_SIGNAL) == 1


async def test_the_bridge_says_it_when_a_replay_never_reaches_the_provider():
    rig = ReplayRig()
    async with Live(rig.bridge) as live:
        rig.bridge._on_capture_signal(OWNER_REPLAY_DROPPED_SIGNAL)
        await live.idle()

    entry = rig.journal.of(OWNER_REPLAY_KIND)[-1]
    assert (entry["level"], entry["data"]["code"]) == ("warning", "owner_replay_dropped")


# --------------------------------------------------------------------------
# 7. Une capture qui refuse la garde ne dégrade pas Solo Owner en silence


async def test_a_capture_that_refuses_the_owner_gate_closes_the_session_instead_of_degrading():
    """Spec §3 : sans la garde, « le propriétaire coupe mais tout le monde passe » — jamais en silence."""

    rig = ReplayRig()
    # Capture sans tampon de rejeu : `set_owner_gate` refuse, comme sur un poste
    # où l'anneau n'a pas pu être alloué.
    rig.audio.capture = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    live = Live(rig.bridge)

    async with live:
        await until(lambda: live.task.done())

    assert not rig.bridge._input_gated()
    refusal = rig.journal.of("voice.authorization_refused")[0]["data"]
    assert refusal["code"] == "solo_owner_capture_unsupported"
    assert rig.journal.of("voice.barge_in.authority")[-1]["data"]["input"] == "closed"
