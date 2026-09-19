"""The real local audio chain of the `audio` profile: production writer, production AEC, injected source.

Binding contract: `docs/testlab.md` ("Audio profile"). The `virtual` profile
replaces the duplex capture with `VirtualEchoGuard`, a double that states acoustic
STATE and performs no acoustics. The `audio` profile puts the production
`jarvis.audio.duplex.CaptureProcessor` back, with the real WebRTC echo canceller
(`jarvis.adapters.webrtc_echo`) when the optional `livekit.rtc` package is
installed, and drives it with a fixture instead of a microphone.

What stays real:

- the OUTPUT path is the production writer (`SoundDeviceRealtimeAudio._write_output`):
  chunking, gain ramp, admission, epochs, byte accounting and `push_reference` per
  block, so the canceller's far-end reference is what Jarvis actually "played";
- the CAPTURE path is the production callback body: `capture.process(raw)` and then
  `_deliver_capture(len(raw), processed, signals)`, byte for byte the two lines the
  PortAudio callback runs;
- the echo canceller, the near-end detector, the pre-roll and the gate are the
  production objects, doing real arithmetic on real samples.

What is NOT real, and therefore what this profile cannot prove: no PortAudio
stream is opened, so there is no device, no room, no speaker, no microphone, no
clock drift and no underrun. The acoustic coupling is whatever the fixture states
(a clip injected while Jarvis speaks IS the echo, by construction), not what a
room would do. Those are the `hardware:auto` and `hardware:guided` questions
(Slice 09).
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import random
from typing import Any

from jarvis.audio.duplex import CaptureProcessor
from jarvis.testlab.audio.fixtures import BYTES_PER_SAMPLE, VOICE_SAMPLE_RATE
from jarvis.testlab.virtual.harness import FakeAudio

#: One PortAudio input block of the production stream: `blocksize=1200` frames at
#: 24 kHz, i.e. 50 ms. Injection uses the same block size so the capture processor
#: sees exactly the block shape it sees in production.
INPUT_BLOCK_FRAMES = 1200
INPUT_BLOCK_BYTES = INPUT_BLOCK_FRAMES * BYTES_PER_SAMPLE
INPUT_BLOCK_MS = INPUT_BLOCK_FRAMES * 1000 // VOICE_SAMPLE_RATE


@dataclass(slots=True)
class CaptureBuild:
    """What was actually mounted, so a run records what it exercised rather than what it asked for."""

    capture: CaptureProcessor
    capture_rate: int
    render_rate: int
    #: True when a real echo canceller is in the chain.
    aec_engaged: bool
    #: Why there is none, when there is none: `not_installed` or `construction_failed`.
    aec_unavailable_reason: str | None = None
    canceller_name: str | None = None
    #: Exception type and message when construction failed, for the run log only.
    aec_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"capture_rate": self.capture_rate, "render_rate": self.render_rate,
                "aec_engaged": self.aec_engaged, "aec_unavailable_reason": self.aec_unavailable_reason,
                "canceller": self.canceller_name}


def build_capture(*, capture_rate: int = VOICE_SAMPLE_RATE, render_rate: int = VOICE_SAMPLE_RATE,
                  echo_cancellation: bool = True, observer: Any = None) -> CaptureBuild:
    """Build the PRODUCTION duplex capture, with the real canceller when one is installed.

    A missing `livekit.rtc` is not a failure: `CaptureProcessor` runs without a
    canceller (with a more conservative near-end detector, exactly as production
    does on a host without the optional package). The run records which of the two
    it got, because "no false barge-in" means different things behind an AEC and
    in front of one.
    """
    canceller = None
    reason: str | None = None
    name: str | None = None
    error: str | None = None
    if echo_cancellation:
        from jarvis.adapters.webrtc_echo import create_echo_canceller, echo_cancellation_installed

        if not echo_cancellation_installed():
            reason = "not_installed"
        else:
            try:
                canceller = create_echo_canceller(capture_rate=capture_rate, render_rate=render_rate)
            except Exception as exc:
                # Captured, not swallowed: the run continues without a canceller and
                # SAYS so in its metadata and its log, because a measurement taken
                # without the AEC must never be read as a measurement of the AEC.
                reason = "construction_failed"
                canceller = None
                name = None
                error = f"{type(exc).__name__}: {exc}"[:200]
            else:
                if canceller is None:
                    reason = "not_installed"
                else:
                    name = type(canceller).__name__
    else:
        reason = "disabled_by_parameter"
    # No `owner_buffer_ms`: the Solo Owner replay buffer belongs to a diagnostic that
    # measures the owner gate, and no Slice 08 diagnostic does. A knob no caller sets is
    # dead contract data; the Slice that needs it adds it with its runner.
    # `observer` is the production `CaptureObserver` seam: it receives the cleaned frame and
    # what the guard concluded about it, once per 10 ms frame, and can change nothing.
    capture = CaptureProcessor(capture_rate=capture_rate, render_rate=render_rate, canceller=canceller,
                               observer=observer)
    return CaptureBuild(capture=capture, capture_rate=capture_rate, render_rate=render_rate,
                        aec_engaged=canceller is not None, aec_unavailable_reason=reason, canceller_name=name,
                        aec_error=error)


class InjectedSourceAudio(FakeAudio):
    """`FakeAudio` with an injected capture source instead of a canned block.

    Two differences from `FakeAudio`, both about honesty of the stimulus:

    - `start()` enqueues NOTHING. `FakeAudio` primes the input queue with a canned
      block so a virtual scenario always has some input; on the `audio` profile the
      input is the measurement's own stimulus, and a phantom block would be an
      unaccounted one.
    - `inject_block()` runs the production callback body, so injected audio reaches
      the provider through `capture.process` -> `_deliver_capture` -> `_put_input`,
      the same three calls a real microphone block makes.
    """

    #: Blocks pushed through `inject_block`, for the run's own accounting.
    injected_blocks: int
    injected_bytes: int
    capture_signals: list[str]

    def __init__(self, *, input_device=None, output_device=None, **rates) -> None:  # noqa: ANN001
        super().__init__(input_device=input_device, output_device=output_device, **rates)
        self.injected_blocks = 0
        self.injected_bytes = 0
        self.capture_signals = []

    async def start(self) -> None:
        """No canned input: the `audio` profile's only input is what a scenario injects."""
        return None

    def inject_block(self, pcm: bytes) -> tuple[str, ...]:
        """One microphone block, through the production capture path. Returns the signals raised.

        Mirrors `SoundDeviceRealtimeAudio._open.callback`: a capture exception falls
        back to the raw block instead of killing the stream, exactly as PortAudio
        requires, and the run learns about it through the returned signals and the log.
        """
        capture = self.capture
        if capture is None:
            self._enqueue(pcm)
            signals: tuple[str, ...] = ()
        else:
            try:
                processed, signals = capture.process(pcm)
            except Exception as exc:
                # Same contract as the production callback: never raise into the audio
                # source. The block passes through raw and the caller sees `capture_failed`.
                processed, signals = pcm, ("capture_failed",)
                self.capture_signals.append(f"capture_failed:{type(exc).__name__}")
                del exc
            self._deliver_capture(len(pcm), processed, signals)
        self.injected_blocks += 1
        self.injected_bytes += len(pcm)
        for signal in signals:
            self.capture_signals.append(str(signal))
        return signals


@dataclass(slots=True)
class InjectionReport:
    """What one `audio.inject` step actually did."""

    ref: str
    blocks: int
    bytes_injected: int
    duration_ms: int
    gain_db: float
    source_sample_rate: int
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"ref": self.ref, "blocks": self.blocks, "bytes": self.bytes_injected,
                "duration_ms": self.duration_ms, "gain_db": self.gain_db,
                "source_sample_rate": self.source_sample_rate, "signals": list(self.signals)}


#: What a room adds to what the speaker played, on top of the declared coupling. These are
#: not decoration: a delay-free, exactly-scaled, noiseless copy is CANCELLABLE in a way no
#: room is, and an echo canceller given one converges until the near-end detector learns an
#: expectation no real room could produce. Measured on the `audio` profile at the seed's own
#: default (8 000 ms): with the ideal copy the gate opens on the residual at ~3.4 s and the
#: run FAILS a healthy product; with delay, drift and noise together it plays all 8 000 ms
#: with zero false confirmations. See `Issues/self-barge-in-after-seconds-of-speech.md`.
ECHO_DELAY_BLOCKS = 1
ECHO_DRIFT_DB = 3.0
ECHO_NOISE_AMPLITUDE = 40


def room_response(pcm: bytes, *, seed: int, drift_db: float = ECHO_DRIFT_DB,
                  noise: int = ECHO_NOISE_AMPLITUDE) -> bytes:
    """Shape one block the way a room does: slow level drift plus a little broadband noise.

    Deterministic for a given `seed`, so a run is reproducible; the delay is the caller's,
    because only the caller knows its own block schedule.
    """
    generator = random.Random(seed)
    samples = array("h")
    samples.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    for index in range(len(samples)):
        gain = 10 ** ((drift_db * (index % _DRIFT_PERIOD) / _DRIFT_PERIOD - drift_db / 2) / 20)
        value = int(samples[index] * gain) + (generator.randint(-noise, noise) if noise else 0)
        samples[index] = max(-32768, min(32767, value))
    return samples.tobytes()


#: Samples over which the drift completes one cycle: about two seconds at the voice rate.
_DRIFT_PERIOD = VOICE_SAMPLE_RATE * 2


def split_blocks(pcm: bytes, block_bytes: int = INPUT_BLOCK_BYTES) -> list[bytes]:
    """Split PCM into production-sized input blocks; the tail is zero-padded like a stream's."""
    if not pcm:
        return []
    blocks = [pcm[start:start + block_bytes] for start in range(0, len(pcm), block_bytes)]
    tail = blocks[-1]
    if len(tail) < block_bytes:
        blocks[-1] = tail + bytes(block_bytes - len(tail))
    return blocks


@dataclass(slots=True)
class ChainMetadata:
    """Non-identifying record of what the `audio` profile exercised.

    Device ids are recorded as what was REQUESTED (always `None` on this profile,
    because no device is opened) rather than as an enumeration of the workstation's
    hardware: a device name is a fact about the user's machine, and the Test Lab
    records facts about the run.
    """

    profile: str
    sample_rate: int
    output_sample_rate: int
    input_block_ms: int
    input_device: str | None
    output_device: str | None
    device_opened: bool
    duplex_engaged: bool
    aec_engaged: bool
    aec_unavailable_reason: str | None
    canceller: str | None
    injected: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile, "sample_rate": self.sample_rate,
                "output_sample_rate": self.output_sample_rate, "input_block_ms": self.input_block_ms,
                "input_device": self.input_device, "output_device": self.output_device,
                "device_opened": self.device_opened, "duplex_engaged": self.duplex_engaged,
                "aec_engaged": self.aec_engaged, "aec_unavailable_reason": self.aec_unavailable_reason,
                "canceller": self.canceller, "injected": list(self.injected)}


def chain_metadata(profile: str, build: CaptureBuild, audio: InjectedSourceAudio) -> ChainMetadata:
    return ChainMetadata(
        profile=profile, sample_rate=int(audio.sample_rate), output_sample_rate=int(audio.output_sample_rate),
        input_block_ms=INPUT_BLOCK_MS, input_device=None, output_device=None, device_opened=False,
        duplex_engaged=audio.capture is not None, aec_engaged=build.aec_engaged,
        aec_unavailable_reason=build.aec_unavailable_reason, canceller=build.canceller_name)

