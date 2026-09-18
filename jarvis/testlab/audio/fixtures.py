"""The Test Lab audio fixture root: what an `audio_ref` may name, and how it becomes PCM.

Binding contract: `docs/testlab.md` ("Audio profile"). Slice 04 registered the
`audio.inject` primitive with an `audio_ref` argument and left it homeless;
this module is the home.

**One declared root.** `audio_ref` is a relative POSIX path inside
`jarvis/testlab/fixtures/audio/`, validated by the Slice 02 artifact-path rule
(`check_artifact_path`: no absolute path, no drive, no backslash, no `..`, no
hidden segment, bounded length and segment shape) and then re-checked against
the resolved root, so neither a link nor a resolution trick can leave it. A
scenario can therefore name only audio a reviewer put in the repository — never
a recording of the user, never a file the scenario author chose at run time.

**Clips are synthetic and deterministic.** `build_reference_clip` generates
every shipped fixture from its parameters alone, and a test regenerates them and
compares bytes. There is no recording of a human voice in this root, so an
injected clip can never leak one.

Format: 16-bit signed little-endian mono WAV. The voice path runs at 24 kHz
(`SoundDeviceRealtimeAudio.sample_rate`), and a clip at another rate is
resampled on load by `resample_pcm16` — linear interpolation in the standard
library, because `audioop` was removed in Python 3.13.
"""

from __future__ import annotations

from array import array
from collections.abc import Iterable
from dataclasses import dataclass
import math
from pathlib import Path
import struct
import wave

from jarvis.testlab._fs import is_link
from jarvis.testlab.runs import check_artifact_path
from jarvis.testlab.validation import TestLabError, fail

#: The one declared root. Package data, like `jarvis/testlab/official/`.
AUDIO_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "audio"

#: The rate of the continuous voice path; a fixture is resampled to it on load.
VOICE_SAMPLE_RATE = 24_000
BYTES_PER_SAMPLE = 2
#: A fixture is a short stimulus, not a recording session. 60 s at 48 kHz mono.
MAX_FIXTURE_BYTES = 6 * 1024 * 1024
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 96_000

FIXTURE_UNKNOWN = "testlab_audio_fixture_unknown"
FIXTURE_UNSAFE = "testlab_audio_fixture_unsafe"
FIXTURE_INVALID = "testlab_audio_fixture_invalid"


class AudioFixtureError(TestLabError):
    """An `audio_ref` names nothing usable: outside the root, absent, or not a mono PCM16 WAV."""


@dataclass(frozen=True, slots=True)
class AudioClipData:
    """One loaded fixture: raw PCM16 mono at `sample_rate`, plus what it was on disk."""

    ref: str
    pcm: bytes
    sample_rate: int
    source_sample_rate: int

    @property
    def duration_ms(self) -> int:
        return len(self.pcm) * 1000 // (BYTES_PER_SAMPLE * self.sample_rate)

    @property
    def resampled(self) -> bool:
        return self.sample_rate != self.source_sample_rate


class AudioFixtureRoot:
    """Resolves an `audio_ref` to a file inside one declared root, and loads it as PCM.

    The root is a constructor argument so a test can declare its own; a run always
    gets `AUDIO_FIXTURE_ROOT`, because a run-chosen root would make the containment
    check meaningless.
    """

    __slots__ = ("_root",)

    def __init__(self, root: Path | str = AUDIO_FIXTURE_ROOT) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def refs(self) -> tuple[str, ...]:
        """Every fixture this root offers, as the refs a scenario may name."""
        try:
            resolved = self._root.resolve(strict=True)
        except OSError:
            return ()
        found = sorted(path.relative_to(resolved).as_posix()
                       for path in resolved.rglob("*.wav") if path.is_file() and not is_link(path))
        return tuple(found)

    def resolve(self, ref: object) -> Path:
        """The file `ref` names, or `AudioFixtureError`. Refuses traversal, links and absence."""
        try:
            check_artifact_path(ref, "audio_ref")
        except TestLabError as exc:
            raise AudioFixtureError(FIXTURE_UNSAFE, f"audio_ref is not a safe relative path ({exc.code})") from None
        text = str(ref)
        if not text.lower().endswith(".wav"):
            raise AudioFixtureError(FIXTURE_UNSAFE, "audio_ref must name a .wav fixture")
        try:
            root = self._root.resolve(strict=True)
        except OSError as exc:
            raise AudioFixtureError(FIXTURE_UNKNOWN,
                                    "the Test Lab audio fixture root does not exist on this host") from exc
        candidate = root.joinpath(*text.split("/"))
        # Every component, not only the leaf: a junction one level up would move the
        # whole subtree out of the root, and Windows junctions are not symlinks.
        for part in _ancestry(candidate, root):
            if is_link(part):
                raise AudioFixtureError(FIXTURE_UNSAFE, "audio_ref passes through a link, which a fixture root forbids")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise AudioFixtureError(FIXTURE_UNKNOWN, f"no audio fixture named {text!r} in the Test Lab fixture root") from exc
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise AudioFixtureError(FIXTURE_UNSAFE, "audio_ref resolves outside the Test Lab audio fixture root")
        return resolved

    def load(self, ref: object, *, sample_rate: int = VOICE_SAMPLE_RATE) -> AudioClipData:
        """Resolve and decode a fixture to mono PCM16 at `sample_rate`."""
        path = self.resolve(ref)
        pcm, source_rate = read_wav_pcm16(path)
        return AudioClipData(str(ref), resample_pcm16(pcm, source_rate, sample_rate), sample_rate, source_rate)


def _ancestry(candidate: Path, root: Path) -> Iterable[Path]:
    """`candidate` and every parent up to (excluding) `root`."""
    current = candidate
    while current != root:
        yield current
        parent = current.parent
        if parent == current:
            return
        current = parent


# ----------------------------------------------------------------- codec

def read_wav_pcm16(path: Path) -> tuple[bytes, int]:
    """Decode a mono 16-bit PCM WAV. Anything else is refused, never converted silently."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AudioFixtureError(FIXTURE_UNKNOWN, "the audio fixture could not be stated") from exc
    if size > MAX_FIXTURE_BYTES:
        raise AudioFixtureError(FIXTURE_INVALID, f"the audio fixture exceeds {MAX_FIXTURE_BYTES} bytes")
    try:
        with wave.open(str(path), "rb") as handle:
            channels, width, rate, frames = (handle.getnchannels(), handle.getsampwidth(),
                                             handle.getframerate(), handle.getnframes())
            if channels != 1 or width != BYTES_PER_SAMPLE:
                raise AudioFixtureError(FIXTURE_INVALID,
                                        f"the audio fixture must be mono 16-bit PCM (got {channels} channels, {width * 8} bits)")
            if not MIN_SAMPLE_RATE <= rate <= MAX_SAMPLE_RATE:
                raise AudioFixtureError(FIXTURE_INVALID,
                                        f"the audio fixture rate must be {MIN_SAMPLE_RATE}..{MAX_SAMPLE_RATE} Hz")
            pcm = handle.readframes(frames)
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioFixtureError(FIXTURE_INVALID, f"the audio fixture is not a readable WAV ({type(exc).__name__})") from exc
    if not pcm:
        raise AudioFixtureError(FIXTURE_INVALID, "the audio fixture holds no samples")
    return pcm, rate


def write_wav_pcm16(path: Path, pcm: bytes, sample_rate: int) -> None:
    """Write mono PCM16 as a WAV. Used to build the shipped fixtures, never during a run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(BYTES_PER_SAMPLE)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm)


def resample_pcm16(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    """Linear-interpolation resample of mono PCM16.

    Standard library only: `audioop`, which the repository used before, was removed
    in Python 3.13. Linear interpolation is enough for a STIMULUS — the fixture is
    the thing being played into the chain, not a measurement of it — and a test
    pins that it neither changes length by more than a sample nor clips.
    """
    if source_rate == target_rate:
        return pcm
    samples = array("h")
    samples.frombytes(pcm)
    count = len(samples)
    if count < 2:
        return pcm
    out_count = max(1, round(count * target_rate / source_rate))
    step = (count - 1) / max(1, out_count - 1) if out_count > 1 else 0.0
    out = array("h", bytes(out_count * BYTES_PER_SAMPLE))
    for index in range(out_count):
        position = index * step
        low = int(position)
        high = min(low + 1, count - 1)
        weight = position - low
        out[index] = int(round(samples[low] * (1.0 - weight) + samples[high] * weight))
    return out.tobytes()


def frame_peak_dbfs(pcm: bytes) -> float:
    """Peak level of a PCM16 block in dBFS, floored at -96. Mirrors `audio_devices._levels`."""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % BYTES_PER_SAMPLE])
    peak = max((abs(sample) for sample in samples), default=0)
    if peak == 0:
        return -96.0
    return 20.0 * math.log10(peak / 32768.0)


def apply_gain_db(pcm: bytes, gain_db: float) -> bytes:
    """Scale a PCM16 block, clipping at full scale. `audio.inject`'s `gain_db` argument."""
    if not gain_db:
        return pcm
    factor = 10.0 ** (float(gain_db) / 20.0)
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % BYTES_PER_SAMPLE])
    for index, sample in enumerate(samples):
        samples[index] = max(-32768, min(32767, int(round(sample * factor))))
    return samples.tobytes()


# -------------------------------------------------------------- generation

def build_reference_clip(*, sample_rate: int = VOICE_SAMPLE_RATE, duration_ms: int = 1000,
                         frequencies: tuple[int, ...] = (220, 440, 880), peak: float = 0.5,
                         attack_ms: int = 40, release_ms: int = 80) -> bytes:
    """Deterministic synthetic stimulus: summed sine partials under a trapezoid envelope.

    Not speech and never claimed to be: it is a bounded, repeatable signal whose
    energy sits in the band a voice occupies, which is what an echo-cancellation
    reference and a level measurement need. Pure arithmetic, so the shipped
    fixtures can be regenerated byte for byte by a test.
    """
    if duration_ms <= 0 or not frequencies or not 0.0 < peak <= 1.0:
        raise fail("build_reference_clip needs a positive duration, at least one partial and a peak in (0, 1]")
    count = int(sample_rate * duration_ms / 1000)
    attack = max(1, int(sample_rate * attack_ms / 1000))
    release = max(1, int(sample_rate * release_ms / 1000))
    scale = peak * 32767.0 / len(frequencies)
    out = array("h", bytes(count * BYTES_PER_SAMPLE))
    for index in range(count):
        envelope = min(1.0, index / attack, max(0.0, count - index) / release)
        value = sum(math.sin(2.0 * math.pi * frequency * index / sample_rate) for frequency in frequencies)
        out[index] = max(-32768, min(32767, int(round(value * scale * envelope))))
    return out.tobytes()


def build_silence(*, sample_rate: int = VOICE_SAMPLE_RATE, duration_ms: int = 500) -> bytes:
    """Digital silence, the control stimulus of a level or gate measurement."""
    return bytes(int(sample_rate * duration_ms / 1000) * BYTES_PER_SAMPLE)


#: The shipped fixtures and how each one is generated. A test regenerates every row
#: and compares bytes, so the repository holds no audio nobody can reproduce.
SHIPPED_FIXTURES: dict[str, dict[str, object]] = {
    "reference-tone-1s.wav": {"builder": "build_reference_clip", "duration_ms": 1000},
    "silence-500ms.wav": {"builder": "build_silence", "duration_ms": 500},
}


def render_shipped_fixture(name: str) -> bytes:
    """The PCM of one shipped fixture, from its declaration in `SHIPPED_FIXTURES`."""
    spec = SHIPPED_FIXTURES.get(name)
    if spec is None:
        raise AudioFixtureError(FIXTURE_UNKNOWN, f"{name!r} is not a shipped Test Lab audio fixture")
    duration_ms = int(spec["duration_ms"])  # type: ignore[arg-type]
    if spec["builder"] == "build_silence":
        return build_silence(duration_ms=duration_ms)
    return build_reference_clip(duration_ms=duration_ms)


def wav_bytes(pcm: bytes, sample_rate: int = VOICE_SAMPLE_RATE) -> bytes:
    """A canonical WAV container around PCM16, for an artifact written without a file."""
    data_size = len(pcm)
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + data_size, b"WAVE", b"fmt ", 16, 1, 1,
                         sample_rate, sample_rate * BYTES_PER_SAMPLE, BYTES_PER_SAMPLE, 16, b"data", data_size)
    return header + pcm
