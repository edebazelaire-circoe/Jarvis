"""A `sounddevice` double with a simulated room, for the Test Lab hardware profiles.

The `hardware:auto` and `hardware:guided` runners mount the PRODUCTION
`SoundDeviceRealtimeAudio`, which does `import sounddevice as sd` inside `_open()`. Put
this module in `sys.modules["sounddevice"]` and the production open, the production
PortAudio callback, the production chunked writer, the production duplex capture and the
real WebRTC echo canceller all run exactly as they do on the workstation — over a room
that is a few lines of arithmetic instead of a laptop.

That is the point: the default suite must never touch the user's microphone, and it must
still exercise the code that would. What is a double here is PortAudio and the room.
Everything above them is the product.

`FakeRoom` couples the two streams the way a laptop does: whatever the output stream
writes comes back into the input stream's callback, attenuated, with whatever "near-end
voice" the test scripted mixed on top. A test can therefore build both cases that matter
— an echo that correlates with what Jarvis played, and a real voice that does not —
without a speaker.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import math
import random
import threading
import time
from typing import Any

#: The production input stream's own block: `blocksize=1200` frames at 24 kHz (50 ms).
INPUT_BLOCK_FRAMES = 1200
BYTES_PER_FRAME = 2
INPUT_BLOCK_BYTES = INPUT_BLOCK_FRAMES * BYTES_PER_FRAME
VOICE_SAMPLE_RATE = 24_000


class FakeAudioError(RuntimeError):
    """What the double raises when a test asks it to behave like a broken device."""


def _scale(pcm: bytes, factor: float) -> bytes:
    samples = array("h")
    samples.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    for index, value in enumerate(samples):
        samples[index] = max(-32768, min(32767, int(value * factor)))
    return samples.tobytes()


def _mix(left: bytes, right: bytes) -> bytes:
    size = max(len(left), len(right))
    left, right = left.ljust(size, b"\x00"), right.ljust(size, b"\x00")
    a, b = array("h"), array("h")
    a.frombytes(left[:size - size % 2])
    b.frombytes(right[:size - size % 2])
    for index in range(len(a)):
        a[index] = max(-32768, min(32767, a[index] + b[index]))
    return a.tobytes()


@dataclass
class FakeRoom:
    """The acoustic coupling between the double's output and its input.

    `coupling` is a linear factor (0.25 is about -12 dB). `near_end` is what the "human"
    is saying right now: a test sets it to model somebody speaking, and clears it to model
    a silent room.

    **The microphone is driven BY the speaker, block for block, not by a wall clock.**
    That is the one property a double of a duplex device has to get right: the production
    echo canceller consumes one reference frame per captured frame, so a microphone that
    ran faster than the speaker would empty the reference queue while Jarvis was still
    talking, the far-end window would expire, and the echo gate would open — a false
    positive manufactured by the harness and reported as a product defect. In lockstep the
    ratio is exact and the run is deterministic.

    **The idle tick is the one wall clock in the room.** While nothing is playing there is
    no speaker to drive the microphone, so a daemon thread delivers a block every
    `idle_interval_s` (50 ms, real time) carrying silence plus whatever voice the test put
    in the room. That is what the near-end detector learns its noise floor from, and it is
    the only part of this double whose rate depends on the host: a loaded machine delivers
    fewer idle blocks, never fewer echo blocks. Anything a test asserts about what happened
    WHILE Jarvis was speaking is therefore lockstep and deterministic; anything it asserts
    about the silence between utterances is not, and should be expressed as "at least one
    block" rather than a count.
    """

    coupling: float = 0.25
    #: What the microphone hears besides the echo. Set by a test, block by block.
    near_end: bytes = b""
    #: A room returns what the speaker played a moment ago, shaped — never a delay-free,
    #: exactly-scaled copy of it. The difference is not cosmetic: an echo canceller given a
    #: perfect copy converges until the near-end detector expects a residual no room
    #: produces, and the gate then opens on its own arithmetic after a few seconds of
    #: continuous speech. Measured at the seed's declared default of 8 000 ms, the copy
    #: made `hardware:auto` FAIL a healthy product; with the delay, the drift and the noise
    #: it plays the full 8 000 ms clean. Same model as the `audio` profile's
    #: `jarvis.testlab.audio.chain.room_response`, so the two profiles differ in what is
    #: REAL, not in what the room does.
    shaped: bool = True
    #: A room is never digitally silent. Pure zero is physically impossible and it drives
    #: the near-end detector's noise floor to its own minimum, after which the residual of
    #: several seconds of speech clears the margin and the gate opens in an EMPTY room —
    #: measured at the seeds' declared default of 8 000 ms. About -65 dBFS: quiet, audibly
    #: a room, and well under the -50 dBFS a voice has to beat.
    noise_floor: int = 18
    #: Blocks the output stream wrote, in order (what Jarvis "played").
    played: list[bytes] = field(default_factory=list)
    #: Blocks the input stream delivered, in order (what the "microphone" heard).
    captured: list[bytes] = field(default_factory=list)
    _carry: bytes = b""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _noise: random.Random = field(default_factory=lambda: random.Random(20260918))

    def write(self, pcm: bytes) -> tuple[bytes, ...]:
        """Take one played block; return the microphone blocks the room returns for it.

        One block of delay: what comes back now is what the speaker played a moment ago.
        """
        from jarvis.testlab.audio.chain import room_response

        with self._lock:
            self.played.append(bytes(pcm))
            echo = _scale(bytes(pcm), self.coupling)
            if self.shaped:
                echo = room_response(echo, seed=len(self.played))
            self._carry += echo
            blocks = []
            # One whole block stays behind, which IS the delay.
            while len(self._carry) >= 2 * INPUT_BLOCK_BYTES:
                blocks.append(self._carry[:INPUT_BLOCK_BYTES])
                self._carry = self._carry[INPUT_BLOCK_BYTES:]
        return tuple(self._mic(block) for block in blocks)

    def idle_block(self) -> bytes:
        """One microphone block with nothing playing: silence, plus any voice in the room."""
        return self._mic(bytes(INPUT_BLOCK_BYTES))

    def _mic(self, echo: bytes) -> bytes:
        near = self.near_end
        block = echo[:INPUT_BLOCK_BYTES].ljust(INPUT_BLOCK_BYTES, b"\x00")
        if self.noise_floor:
            block = _mix(block, self._room_noise())
        if near:
            block = _mix(block, near[:INPUT_BLOCK_BYTES])
        with self._lock:
            self.captured.append(block)
        return block

    def _room_noise(self) -> bytes:
        """This room's own quiet hiss, in every block, echo or not."""
        amplitude = self.noise_floor
        return array("h", (self._noise.randint(-amplitude, amplitude)
                           for _ in range(INPUT_BLOCK_FRAMES))).tobytes()


class _Stream:
    def __init__(self, owner: "FakeSoundDevice", kind: str) -> None:
        self._owner = owner
        self._kind = kind
        self.started = False
        self.closed = False
        self.aborted = False
        self.latency = 0.01

    def start(self) -> None:
        self._owner.record(f"{self._kind}.start")
        self.started = True

    def stop(self, ignore_errors: bool = True) -> None:
        del ignore_errors
        self._owner.record(f"{self._kind}.stop")
        self.started = False

    def abort(self, ignore_errors: bool = True) -> None:
        del ignore_errors
        self._owner.record(f"{self._kind}.abort")
        self.aborted = True
        self.started = False

    def close(self, ignore_errors: bool = True) -> None:
        del ignore_errors
        self._owner.record(f"{self._kind}.close")
        self.closed = True
        self.started = False


class FakeRawOutputStream(_Stream):
    """Writes a block and hands the room's answer straight to the input callback.

    Called from the production writer's own thread (`asyncio.to_thread`), which is where
    PortAudio would call it, so the microphone blocks reach the loop through exactly the
    `call_soon_threadsafe` path a real callback uses.
    """

    def __init__(self, owner: "FakeSoundDevice", **options: Any) -> None:
        super().__init__(owner, "output")
        self.options = options

    def write(self, pcm) -> None:  # noqa: ANN001
        if self._owner.fail_on_write:
            raise FakeAudioError("the output device refused a write")
        for block in self._owner.room.write(bytes(pcm)):
            self._owner.deliver(block)


class FakeRawInputStream(_Stream):
    """The microphone: driven by the speaker, plus a slow idle tick for the silence between.

    The idle tick is a daemon thread and not a task, because that is what PortAudio does:
    the production callback runs off the event loop and hands its block back with
    `loop.call_soon_threadsafe`, and a double that called it on the loop would not
    exercise that path at all.
    """

    def __init__(self, owner: "FakeSoundDevice", *, callback, **options: Any) -> None:  # noqa: ANN001
        super().__init__(owner, "input")
        self.options = options
        self.callback = callback
        owner.input_stream = self
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        super().start()
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._idle, name="fake-portaudio-input", daemon=True)
        self._thread.start()

    def _idle(self) -> None:
        while not self._stop.wait(self._owner.idle_interval_s):
            self._owner.deliver(self._owner.room.idle_block())

    def stop(self, ignore_errors: bool = True) -> None:
        self._stop.set()
        super().stop(ignore_errors)

    def abort(self, ignore_errors: bool = True) -> None:
        self._stop.set()
        super().abort(ignore_errors)

    def close(self, ignore_errors: bool = True) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        super().close(ignore_errors)


class _Default:
    def __init__(self, device: tuple[int, int]) -> None:
        self.device = device


class FakeSoundDevice:
    """The module object a test installs as `sys.modules["sounddevice"]`."""

    def __init__(self, *, room: FakeRoom | None = None, devices: list[dict] | None = None,
                 default_device: tuple[int, int] = (0, 1), idle_interval_s: float = 0.05,
                 input_error: Exception | None = None, output_error: Exception | None = None,
                 enumeration_error: Exception | None = None, open_error: Exception | None = None,
                 fail_on_write: bool = False) -> None:
        self.room = room if room is not None else FakeRoom()
        #: How often the microphone delivers a block while NOTHING is playing. Only the
        #: silence between utterances runs on this clock; whatever the speaker plays comes
        #: back in lockstep with it.
        self.idle_interval_s = max(0.001, float(idle_interval_s))
        self.input_error = input_error
        self.output_error = output_error
        self.enumeration_error = enumeration_error
        self.open_error = open_error
        self.fail_on_write = fail_on_write
        self.default = _Default(default_device)
        self.input_stream: FakeRawInputStream | None = None
        self.streams: list[_Stream] = []
        #: Every stream lifecycle call the production code made, in order.
        self.calls: list[str] = []
        #: Every format question the pre-flight asked, as `(end, device)`.
        self.checked: list[tuple[str, Any]] = []
        self._devices = devices if devices is not None else [
            {"name": "Fake microphone", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0,
             "default_samplerate": 48000.0},
            {"name": "Fake speaker", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2,
             "default_samplerate": 48000.0},
        ]

    # ------------------------------------------------------------- the module API

    def record(self, event: str) -> None:
        self.calls.append(event)

    def query_devices(self):
        if self.enumeration_error is not None:
            raise self.enumeration_error
        return list(self._devices)

    def query_hostapis(self):
        if self.enumeration_error is not None:
            raise self.enumeration_error
        return [{"name": "Fake Host API"}]

    def check_input_settings(self, *, device=None, **options) -> None:  # noqa: ANN001
        del options
        self.checked.append(("input", device))
        if self.input_error is not None:
            raise self.input_error

    def check_output_settings(self, *, device=None, **options) -> None:  # noqa: ANN001
        del options
        self.checked.append(("output", device))
        if self.output_error is not None:
            raise self.output_error

    def RawInputStream(self, *, callback, **options):  # noqa: N802, ANN001
        if self.open_error is not None:
            raise self.open_error
        stream = FakeRawInputStream(self, callback=callback, **options)
        self.streams.append(stream)
        return stream

    def RawOutputStream(self, **options):  # noqa: N802
        if self.open_error is not None:
            raise self.open_error
        stream = FakeRawOutputStream(self, **options)
        self.streams.append(stream)
        return stream

    # ---------------------------------------------------------------- the room

    def deliver(self, block: bytes) -> None:
        """Hand one microphone block to the production PortAudio callback."""
        stream = self.input_stream
        if stream is None or stream.closed or not stream.started:
            return
        try:
            stream.callback(block, INPUT_BLOCK_FRAMES, None, None)
        except Exception:
            # Exactly what PortAudio does with a raising callback, and what this double
            # must do too: the stream survives. The production callback never raises.
            pass

    # -------------------------------------------------------------- assertions

    @property
    def open_streams(self) -> list[_Stream]:
        return [stream for stream in self.streams if not stream.closed]

    def wait_for_capture(self, blocks: int = 1, *, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.room.captured) >= blocks:
                return True
            time.sleep(0.01)
        return False


def install(monkeypatch, device: FakeSoundDevice) -> FakeSoundDevice:
    """Make `import sounddevice` return `device` for the duration of one test."""
    import sys

    monkeypatch.setitem(sys.modules, "sounddevice", device)
    return device


def speech_like(frames: int = INPUT_BLOCK_FRAMES, *, peak: float = 0.95) -> bytes:
    """A loud, uncorrelated signal standing in for a human voice next to the microphone.

    Same shape and level as the near-end stimulus the `audio` profile's own discrimination
    test uses (`build_reference_clip(peak=0.95, frequencies=(330, 1450))`): a real near-end
    detector needs a residual that is unmistakably not the echo, and a quiet one would make
    the positive case a test of the threshold rather than of the gate.
    """
    amplitude = max(1, int(32767 * peak / 2))
    samples = array("h", (
        max(-32768, min(32767, int(amplitude * (math.sin(2 * math.pi * 330 * index / VOICE_SAMPLE_RATE)
                                                + math.sin(2 * math.pi * 1450 * index / VOICE_SAMPLE_RATE)))))
        for index in range(frames)))
    return samples.tobytes()
