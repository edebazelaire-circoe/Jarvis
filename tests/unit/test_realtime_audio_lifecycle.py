"""Cycle de vie des flux PortAudio.

Le crash 0xC0000005 du 8 septembre venait d'ici : un F9 pendant que JARVIS
parlait annulait la tâche du bridge, `asyncio.to_thread` rendait la main sans
interrompre le thread d'écriture, et le `finally` libérait le flux pendant que
PortAudio écrivait dedans. Ces tests fixent l'invariant : aucun flux n'est
libéré tant qu'un thread est à l'intérieur de PortAudio.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import threading

import pytest

from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio


CHUNK_BYTES = SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES * SoundDeviceRealtimeAudio._BYTES_PER_FRAME


def pcm_b64(chunks: int) -> str:
    return base64.b64encode(b"\x01\x00" * (SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES * chunks)).decode()


class FakeOutputStream:
    """Flux de sortie qui signale toute libération pendant une écriture."""

    def __init__(self, *, block_first_write: threading.Event | None = None) -> None:
        self.block_first_write = block_first_write
        self.writes: list[bytes] = []
        self.writing = False
        self.aborted = False
        self.closed = False
        self.freed_while_writing = False
        self.thread: threading.Thread | None = None

    def write(self, pcm) -> None:  # noqa: ANN001
        self.writing = True
        try:
            if self.block_first_write is not None and not self.writes:
                assert self.block_first_write.wait(5), "l'écriture n'a jamais été libérée"
            self.writes.append(bytes(pcm))
        finally:
            self.writing = False

    def start(self) -> None:
        self.thread = threading.current_thread()

    def abort(self) -> None:
        self.aborted = True
        self.freed_while_writing |= self.writing

    def stop(self) -> None:
        self.freed_while_writing |= self.writing

    def close(self) -> None:
        self.freed_while_writing |= self.writing
        self.closed = True


class FakeInputStream:
    def __init__(self) -> None:
        self.stopped = False
        self.aborted = False
        self.closed = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.current_thread()

    def stop(self) -> None:
        self.stopped = True

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        self.closed = True


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition jamais atteinte"
        await asyncio.sleep(0.005)


async def test_close_never_frees_the_output_stream_while_portaudio_is_writing():
    """Le scénario exact du crash : F9 pendant que JARVIS parle."""
    gate = threading.Event()
    audio = SoundDeviceRealtimeAudio()
    stream = FakeOutputStream(block_first_write=gate)
    audio._output = stream

    playing = asyncio.create_task(audio.play_b64(pcm_b64(1)))
    await _until(lambda: stream.writing)

    # Ce que fait mute() sur une interruption manuelle : annuler la tâche du
    # bridge, qui enchaîne aussitôt sur close() dans son finally.
    playing.cancel()
    closing = asyncio.create_task(audio.close())
    await asyncio.sleep(0.05)
    assert not closing.done(), "close() a libéré le flux sans attendre l'écriture en vol"

    gate.set()
    await asyncio.wait_for(closing, timeout=5)
    await asyncio.gather(playing, return_exceptions=True)

    assert stream.freed_while_writing is False
    assert stream.closed is True
    assert stream.aborted is True


async def test_closing_stops_playback_at_the_next_block_instead_of_finishing_it():
    """La fermeture reste réactive : elle n'attend qu'un bloc, pas la réponse entière."""
    gate = threading.Event()
    audio = SoundDeviceRealtimeAudio()
    stream = FakeOutputStream(block_first_write=gate)
    audio._output = stream

    playing = asyncio.create_task(audio.play_b64(pcm_b64(10)))
    await _until(lambda: stream.writing)

    closing = asyncio.create_task(audio.close())
    await asyncio.sleep(0.05)
    gate.set()
    await asyncio.wait_for(closing, timeout=5)
    await asyncio.gather(playing, return_exceptions=True)

    assert len(stream.writes) == 1
    assert stream.writes[0] == b"\x01\x00" * SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES
    assert stream.freed_while_writing is False


async def test_playback_is_written_in_bounded_blocks():
    audio = SoundDeviceRealtimeAudio()
    stream = FakeOutputStream()
    audio._output = stream

    await audio.play_b64(pcm_b64(3))

    assert [len(chunk) for chunk in stream.writes] == [CHUNK_BYTES] * 3


async def test_playback_after_close_is_a_no_op():
    audio = SoundDeviceRealtimeAudio()
    stream = FakeOutputStream()
    audio._output = stream
    await audio.close()

    await audio.play_b64(pcm_b64(2))

    assert stream.writes == []


async def test_input_teardown_waits_for_callbacks_rather_than_aborting():
    """stop() attend les callbacks en vol ; abort() les abandonnerait."""
    audio = SoundDeviceRealtimeAudio()
    stream = FakeInputStream()
    audio._input = stream

    await audio.stop_input()

    assert stream.stopped is True
    assert stream.aborted is False
    assert stream.closed is True
    assert await audio._queue.get() is None


async def test_close_is_safe_when_no_stream_was_ever_opened():
    audio = SoundDeviceRealtimeAudio()

    await audio.close()
    await audio.close()


async def test_devices_are_opened_off_the_event_loop(monkeypatch):
    """Ouvrir PortAudio prend des centaines de ms : la boucle ne doit pas geler."""

    class FakeSoundDevice:
        @staticmethod
        def RawInputStream(**kwargs):  # noqa: ANN003
            return FakeInputStream()

        @staticmethod
        def RawOutputStream(**kwargs):  # noqa: ANN003
            return FakeOutputStream()

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    audio = SoundDeviceRealtimeAudio()

    await audio.start()

    assert audio._input.thread is not threading.main_thread()
    assert audio._output.thread is not threading.main_thread()


async def test_a_failed_output_open_does_not_leak_the_input_stream(monkeypatch):
    opened: list[FakeInputStream] = []

    class FailingSoundDevice:
        @staticmethod
        def RawInputStream(**kwargs):  # noqa: ANN003
            stream = FakeInputStream()
            opened.append(stream)
            return stream

        @staticmethod
        def RawOutputStream(**kwargs):  # noqa: ANN003
            raise OSError("device unavailable")

    monkeypatch.setitem(sys.modules, "sounddevice", FailingSoundDevice)
    audio = SoundDeviceRealtimeAudio()

    with pytest.raises(RuntimeError, match="périphériques audio Voice"):
        await audio.start()

    assert opened and opened[0].closed is True
