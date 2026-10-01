"""Source micro de l'enregistrement explicite, file sans perte silencieuse, réparation WAV.

Handoff session-context-recording, Slice 06. Contrat : `docs/capture.md` › *Audio recording*.
Aucun vrai micro : `FakeInput` remplace `sounddevice` (blocs poussés à la main
depuis le fil du test, comme le ferait PortAudio) ; spool et base réels sous
`tmp_path`.
"""

from __future__ import annotations

import array
import asyncio
from dataclasses import dataclass, field
import io
import math
from pathlib import Path
import struct
import threading
import time
import wave

import pytest

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.sounddevice_recording import (
    AudioRecordingSources, MicrophoneRecordingSource, OpenedInput, WavCaptureRepair, device_from_token, source_error,
)
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_captures import SQLiteCaptureRepository
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_session_context import SQLiteContextRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.audio.wav_pcm import WavFormatError, parse_wav_header, wav_header
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.capture_service import CaptureAssociation, CaptureService
from jarvis.domain.artifacts import ArtifactState
from jarvis.domain.capture import (
    CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode, CaptureState, attach_artifact, new_capture,
)
from jarvis.domain.session_activity import ActivityKind, ActivityQuery
from jarvis.domain.session_context import create_context
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import default_board, open_session
from jarvis.ports.capture import CaptureSourceError, RepairTarget

AUDIO = CaptureChannel.AUDIO
RATE = 16_000
BLOCK = RATE // 10  # 100 ms


def tone(ms: int, amplitude: int = 9000) -> bytes:
    count = RATE * ms // 1000
    return array.array("h", [int(amplitude * math.sin(2 * math.pi * 180 * i / RATE)) for i in range(count)]).tobytes()


def wait_until(predicate, timeout: float = 3.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


async def until(predicate, timeout: float = 3.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


class FakeStream:
    def __init__(self, owner: FakeInput) -> None:
        self.owner = owner

    def start(self) -> None:
        if self.owner.start_error is not None:
            raise source_error(self.owner.start_error, "cannot start input 'Fake Mic'")
        self.owner.started = True

    def stop(self) -> None:
        self.owner.started = False

    def close(self) -> None:
        self.owner.closed = True


class FakeInput:
    """`InputBackend` scripté : `push` joue le rôle du callback PortAudio."""

    def __init__(self, *, rate: int = RATE, open_error: Exception | None = None,
                 start_error: Exception | None = None) -> None:
        self.rate = rate
        self.open_error = open_error
        self.start_error = start_error
        self.started = False
        self.closed = False
        self.device = "unset"
        self.callback = None
        self.finished = None

    def open(self, *, device, sample_rates, block_ms, callback, finished):  # noqa: ANN001, ANN201
        self.device = device
        if self.open_error is not None:
            raise source_error(self.open_error, f"cannot open input {device!r}")
        self.callback, self.finished = callback, finished
        return OpenedInput(stream=FakeStream(self), sample_rate=self.rate, device_name="Fake Mic")

    def close(self, opened: OpenedInput) -> None:
        opened.stream.stop()
        opened.stream.close()

    def push(self, pcm: bytes, *, overflow: bool = False) -> None:
        assert self.callback is not None
        self.callback(pcm, overflow)


@dataclass
class Env:
    root: Path
    state: SQLiteStateRepository
    artifacts: ArtifactService
    service: CaptureService
    inputs: list[FakeInput] = field(default_factory=list)

    async def aclose(self) -> None:
        await self.service.close()
        await self.state.close()

    async def events(self, *kinds: ActivityKind):
        return await self.artifacts.activity(ActivityQuery(kinds=kinds, limit=500))


async def make_env(root: Path, *, factory=None, repairs=None, seed: bool = True, **source_options) -> Env:  # noqa: ANN001, ANN003
    state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
    await state.initialize()
    artifacts = ArtifactService(SQLiteArtifactRepository(state), SQLiteActivityLedger(state),
                                FileArtifactPayloads(root))
    if seed:
        boards, contexts = SQLiteBoardRepository(state), SQLiteContextRepository(state)
        board = default_board(now=utc_now())
        await boards.save_board(board)
        session = open_session(board, now=utc_now())
        await boards.save_session(session)
        transition = create_context(session, (), now=utc_now())
        await contexts.commit_contexts(transition.changed)
        association = CaptureAssociation(session.jarvis_session_id, transition.active.context_id)
    else:
        session = await SQLiteBoardRepository(state).current_session()
        contexts = await SQLiteContextRepository(state).list_contexts(session.jarvis_session_id)
        association = CaptureAssociation(session.jarvis_session_id, contexts[-1].context_id)
    inputs: list[FakeInput] = []

    def backend() -> FakeInput:
        made = factory() if factory else FakeInput()
        inputs.append(made)
        return made

    async def associate() -> CaptureAssociation:
        return association

    options = {"header_refresh_s": 1000.0, **source_options}
    sources = AudioRecordingSources(configured_device=lambda: 3, backend_factory=backend, **options)
    service = CaptureService(SQLiteCaptureRepository(state), artifacts, sources, association=associate,
                             repairs=repairs, start_timeout_s=2.0, stop_timeout_s=5.0)
    return Env(root, state, artifacts, service, inputs)


def payload_path(env: Env, artifact_id: str, name: str = "source.wav") -> Path:
    return env.root / "artifacts" / artifact_id / name


# ------------------------------------------------------------------ cycle nominal


async def test_a_recording_is_a_valid_wav_written_by_the_writer_thread(tmp_path):
    env = await make_env(tmp_path)
    try:
        record = await env.service.start(AUDIO)
        mic = env.inputs[-1]
        assert mic.device == 3, "même réglage d'appareil que Voice (`default` -> réglage)"
        audio = tone(1000)
        for start in range(0, len(audio), BLOCK * 2):
            mic.push(audio[start:start + BLOCK * 2])
        await until(lambda: env.service.status().captures[0].bytes_written == 44 + len(audio))
        final = await env.service.stop(record.capture_id)

        assert (final.state, final.gaps, final.error_code) == (CaptureState.COMPLETE, 0, None)
        artifact = await env.artifacts.get(record.artifact_id)
        assert (artifact.state, artifact.mime_type, artifact.duration_ms) == (ArtifactState.COMPLETE, "audio/wav", 1000)
        assert artifact.metadata["sample_rate"] == RATE and artifact.metadata["audio_device"] == "Fake Mic"
        assert artifact.metadata["gap_count"] == 0 and artifact.metadata["sample_format"] == "pcm_s16le"
        with wave.open(str(payload_path(env, record.artifact_id)), "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()) == (RATE, 1, 2,
                                                                                                    RATE)
            assert wav.readframes(RATE) == audio
        assert mic.closed and not mic.started
    finally:
        await env.aclose()


async def test_the_header_is_refreshed_in_place_while_recording(tmp_path):
    env = await make_env(tmp_path, header_refresh_s=0.0)
    try:
        record = await env.service.start(AUDIO)
        env.inputs[-1].push(tone(200))
        partial = payload_path(env, record.artifact_id, "source.wav.partial")
        wait_until(lambda: declared_data_bytes(partial) == len(tone(200)))
        await env.service.stop(record.capture_id)
    finally:
        await env.aclose()


def declared_data_bytes(path: Path) -> int | None:
    """Taille déclarée par l'en-tête, `None` tant qu'il n'est pas entièrement sur disque (lecture
    concurrente de l'écrivain : fichier absent, plus court que 44 octets ou en-tête en cours)."""

    try:
        return parse_wav_header(path.read_bytes()[:44]).declared_data_bytes
    except (OSError, WavFormatError):
        return None


# ------------------------------------------------------------------ file bornée, jamais de perte silencieuse


class GatedSink:
    """`CaptureSink` dont l'écriture attend une porte : simule un disque lent."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.gaps: list[tuple[str, int | None]] = []
        self.lost_calls: list[tuple[str, str]] = []

    @property
    def bytes_written(self) -> int:
        return len(self.data)

    def write(self, data: bytes) -> None:
        if self.data:  # l'en-tête passe, le PCM attend la porte
            self.entered.set()
            self.gate.wait(5)
        self.data.extend(data)

    def write_at(self, offset: int, data: bytes) -> None:
        self.data[offset:offset + len(data)] = data

    def sync(self) -> None:
        pass

    def gap(self, *, reason: str, lost_ms: int | None = None) -> None:
        self.gaps.append((reason, lost_ms))

    def lost(self, code, reason: str) -> None:  # noqa: ANN001
        self.lost_calls.append((str(code), reason))


async def test_an_overflowing_queue_becomes_dated_silence_and_a_gap_never_a_silent_loss():
    mic = FakeInput()
    source = MicrophoneRecordingSource(backend=mic, device=None, queue_seconds=0.2, header_refresh_s=1000.0)
    sink = GatedSink()
    await source.start(sink)
    blocks = [bytes([n]) * (BLOCK * 2) for n in range(1, 8)]
    mic.push(blocks[0])
    assert sink.entered.wait(2), "l'écrivain tient le premier bloc"
    for block in blocks[1:6]:
        mic.push(block)  # file de 2 : blocs 2-3 gardés, 4-6 refusés et comptés
    sink.gate.set()
    wait_until(lambda: source._queue.empty())
    mic.push(blocks[6])
    await source.stop()

    pcm = bytes(sink.data[44:])
    expected = blocks[0] + blocks[1] + blocks[2] + bytes(3 * BLOCK * 2) + blocks[6]
    assert pcm == expected, "le silence est inséré à la place exacte des blocs perdus"
    assert sink.gaps == [("queue_overflow", 300)]
    info = source.media_info()
    assert info.duration_ms == 700, "le temps du fichier reste celui du mur"
    assert (info.details["gap_count"], info.details["gap_lost_ms"], info.details["dropped_blocks"]) == (1, 300, 3)
    assert parse_wav_header(bytes(sink.data[:44])).declared_data_bytes == len(expected)


async def test_an_overflow_at_the_very_end_is_padded_after_the_last_block():
    mic = FakeInput()
    source = MicrophoneRecordingSource(backend=mic, device=None, queue_seconds=0.1, header_refresh_s=1000.0)
    sink = GatedSink()
    await source.start(sink)
    mic.push(b"\x01" * (BLOCK * 2))
    assert sink.entered.wait(2)
    mic.push(b"\x02" * (BLOCK * 2))
    mic.push(b"\x03" * (BLOCK * 2))  # refusé, aucun bloc après lui
    sink.gate.set()
    await source.stop()
    assert bytes(sink.data[44:]) == b"\x01" * (BLOCK * 2) + b"\x02" * (BLOCK * 2) + bytes(BLOCK * 2)
    assert sink.gaps == [("queue_overflow", 100)]


async def test_a_driver_overflow_is_a_gap_and_the_capture_ends_partial(tmp_path):
    env = await make_env(tmp_path)
    try:
        record = await env.service.start(AUDIO)
        env.inputs[-1].push(tone(100), overflow=True)
        await until(lambda: env.service.status().captures[0].gaps == 1)
        final = await env.service.stop(record.capture_id)
        assert (final.state, final.error_code, final.gaps) == (CaptureState.PARTIAL, "capture_gap", 1)
        (gap,) = await env.events(ActivityKind.CAPTURE_GAP)
        assert gap.data["reason"] == "input_overflow" and gap.data["lost_ms"] is None
        artifact = await env.artifacts.get(record.artifact_id)
        assert artifact.state is ArtifactState.PARTIAL and artifact.metadata["input_overflows"] == 1
    finally:
        await env.aclose()


# ------------------------------------------------------------------ appareil refusé, perdu, en conflit


@pytest.mark.parametrize(("message", "code"), [
    ("Error opening RawInputStream: Device unavailable [PaErrorCode -9985]", CaptureErrorCode.SOURCE_UNAVAILABLE),
    ("Error opening RawInputStream: Unanticipated host error [PaErrorCode -9999]: 'Access is denied.'",
     CaptureErrorCode.PERMISSION_DENIED),
    ("No input device matching 'USB'", CaptureErrorCode.SOURCE_UNAVAILABLE),
])
async def test_a_refused_device_fails_the_start_with_a_stable_code(tmp_path, message, code):
    env = await make_env(tmp_path, factory=lambda: FakeInput(open_error=RuntimeError(message)))
    try:
        with pytest.raises(CaptureError) as caught:
            await env.service.start(AUDIO)
        assert caught.value.code is code
        assert message[:40] in str(caught.value), "la cause réelle est dite, jamais réétiquetée"
        failed = await env.service.get(caught.value.capture_id)
        assert (failed.state, failed.error_code) == (CaptureState.FAILED, code.value)
    finally:
        await env.aclose()


async def test_a_microphone_held_exclusively_elsewhere_is_source_unavailable_and_frees_the_device(tmp_path):
    """Voice (ou une autre application) tient l'entrée en mode exclusif : le démarrage du flux échoue."""

    env = await make_env(tmp_path, factory=lambda: FakeInput(
        start_error=RuntimeError("Error starting stream: Device unavailable [PaErrorCode -9985]")))
    try:
        with pytest.raises(CaptureError) as caught:
            await env.service.start(AUDIO)
        assert caught.value.code is CaptureErrorCode.SOURCE_UNAVAILABLE
        assert env.inputs[-1].closed, "le flux ouvert est refermé"
        assert env.service.status().captures == ()
    finally:
        await env.aclose()


async def test_a_lost_device_stops_the_recording_as_partial_with_a_gap(tmp_path):
    env = await make_env(tmp_path)
    try:
        record = await env.service.start(AUDIO)
        mic = env.inputs[-1]
        mic.push(tone(300))
        await until(lambda: env.service.status().captures[0].bytes_written > 44)
        mic.finished()  # le pilote arrête le flux : appareil débranché
        await until(lambda: not env.service.status().captures)
        final = await env.service.get(record.capture_id)
        assert (final.state, final.error_code, final.stop_reason.value) == (CaptureState.PARTIAL, "source_lost",
                                                                            "source_lost")
        (gap,) = await env.events(ActivityKind.CAPTURE_GAP)
        assert gap.data["reason"] == "source_lost"
        with wave.open(str(payload_path(env, record.artifact_id)), "rb") as wav:
            assert wav.getnframes() == RATE * 300 // 1000, "les octets reçus restent une preuve lisible"
    finally:
        await env.aclose()


async def test_a_silent_stalled_device_is_reported_lost(tmp_path):
    env = await make_env(tmp_path, stall_s=0.2)
    try:
        record = await env.service.start(AUDIO)
        await until(lambda: not env.service.status().captures)
        final = await env.service.get(record.capture_id)
        assert final.error_code == "source_lost"
    finally:
        await env.aclose()


class SlowStartInput(FakeInput):
    """Micro lent à démarrer (Bluetooth) : `stream.start()` rend la main après `delay_s`."""

    def __init__(self, delay_s: float) -> None:
        super().__init__()
        self.delay_s = delay_s

    def open(self, **kwargs):  # noqa: ANN003, ANN201
        opened = super().open(**kwargs)
        start = opened.stream.start

        def slow_start() -> None:
            time.sleep(self.delay_s)
            start()

        opened.stream.start = slow_start
        return opened


async def test_a_slow_starting_microphone_is_not_reported_lost():
    mic = SlowStartInput(delay_s=3.5)  # plus long que le délai de silence (3 s)
    source = MicrophoneRecordingSource(backend=mic, device=None, header_refresh_s=1000.0)
    sink = GatedSink()
    sink.gate.set()
    await source.start(sink)
    await asyncio.sleep(0.3)
    assert sink.lost_calls == [], "le silence se compte depuis le démarrage effectif du flux"
    assert source.health().ok
    mic.push(tone(100))
    await source.stop()
    assert bytes(sink.data[44:]) == tone(100)


def test_the_registry_reuses_the_voice_device_setting_and_refuses_the_rest():
    made: list[MicrophoneRecordingSource] = []
    sources = AudioRecordingSources(configured_device=lambda: "Headset", backend_factory=FakeInput)
    made.append(sources.continuous(AUDIO, source=None, device="default"))
    assert made[0]._device == "Headset"
    assert sources.continuous(AUDIO, source="microphone", device="2")._device == 2
    assert sources.source_name(AUDIO, CaptureMode.CONTINUOUS, None) == "microphone"
    for call in (lambda: sources.continuous(CaptureChannel.SCREEN, source=None, device="default"),
                 lambda: sources.continuous(AUDIO, source="desktop", device="default"),
                 lambda: sources.one_shot(CaptureChannel.SCREEN, source=None, device="default")):
        with pytest.raises(CaptureError) as caught:
            call()
        assert caught.value.code is CaptureErrorCode.UNSUPPORTED_SOURCE
    assert device_from_token("default", lambda: None) is None


def test_source_error_keeps_the_cause_and_maps_permissions():
    error = source_error(OSError("0x80070005"), "open")
    assert isinstance(error, CaptureSourceError) and error.code is CaptureErrorCode.PERMISSION_DENIED
    assert "OSError" in str(error)


# ------------------------------------------------------------------ réparation après la mort de Core


def write_torn_wav(path: Path, pcm: bytes, *, extra: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_header(sample_rate=RATE, channels=1, data_bytes=0) + pcm + extra)


def target_for(partial: Path | None, final: Path | None) -> RepairTarget:
    record = attach_artifact(new_capture(channel=AUDIO, mode=CaptureMode.CONTINUOUS, source="microphone",
                                         now=utc_now()), "jart_x", now=utc_now())
    size = (lambda p: None if p is None or not p.exists() else p.stat().st_size)
    base = partial or final
    assert base is not None
    return RepairTarget(capture=record, artifact_id="jart_x",
                        partial_path=partial or base.with_name("source.wav.partial"),
                        final_path=final or base.with_name("source.wav"),
                        partial_bytes=size(partial), final_bytes=size(final))


def test_repair_rewrites_sizes_from_the_real_length_and_drops_a_torn_sample(tmp_path):
    partial = tmp_path / "source.wav.partial"
    pcm = tone(500)
    write_torn_wav(partial, pcm, extra=b"\x7f")  # demi-échantillon écrit au moment de la mort
    outcome = WavCaptureRepair().repair(target_for(partial, None))
    assert outcome.repaired and outcome.duration_ms == 500 and "trimmed_bytes=1" in outcome.detail
    data = partial.read_bytes()
    assert len(data) == 44 + len(pcm)
    assert struct.unpack_from("<I", data, 4)[0] == 36 + len(pcm)
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getnframes() == len(pcm) // 2 and wav.readframes(len(pcm)) == pcm


def test_repair_uses_the_final_file_when_the_rename_already_happened(tmp_path):
    final = tmp_path / "source.wav"
    write_torn_wav(final, tone(100))
    outcome = WavCaptureRepair().repair(target_for(None, final))
    assert outcome.repaired and outcome.duration_ms == 100


@pytest.mark.parametrize(("content", "detail"), [
    (b"RIFF\x00\x00", "not_repaired"), (b"garbage" * 10, "not_repaired"), (b"", "no_bytes"),
])
def test_repair_leaves_an_unreadable_file_as_it_is(tmp_path, content, detail):
    partial = tmp_path / "source.wav.partial"
    partial.write_bytes(content)
    outcome = WavCaptureRepair().repair(target_for(partial, None))
    assert not outcome.repaired and outcome.detail.startswith(detail)
    assert partial.read_bytes() == content


def _die(env: Env) -> None:
    """Mort brutale de Core : plus aucune écriture n'atteint le disque, rien n'est finalisé."""

    for run in env.service._runs.values():
        with run.sink._lock:
            run.sink._closed = True
            run.sink._spool.close()
        run.source._stopping.set()
        run.source._writer.join(2)
    env.service._runs.clear()
    env.service._holders.clear()


async def test_core_death_mid_recording_is_repaired_into_a_playable_partial_wav(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(AUDIO)
    pcm = tone(800)
    first.inputs[-1].push(pcm)
    await until(lambda: first.service.status().captures[0].bytes_written == 44 + len(pcm))
    _die(first)
    with open(payload_path(first, record.artifact_id, "source.wav.partial"), "ab") as handle:
        handle.write(b"\x01")  # échantillon déchiré
    await first.aclose()

    second = await make_env(tmp_path, repairs={AUDIO: WavCaptureRepair()}, seed=False)
    try:
        report = await second.service.recover()
        assert report.partial == (record.capture_id,) and report.repair_failed == ()
        artifact = await second.artifacts.get(record.artifact_id)
        assert (artifact.state, artifact.duration_ms, artifact.size_bytes) == (ArtifactState.PARTIAL, 800,
                                                                               44 + len(pcm))
        with wave.open(str(payload_path(second, record.artifact_id)), "rb") as wav:
            assert wav.getnframes() == len(pcm) // 2
        recovered = await second.service.get(record.capture_id)
        assert recovered.data["repair"].startswith("wav_sizes_rewritten")
    finally:
        await second.aclose()
