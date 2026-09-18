"""The `hardware:auto` and `hardware:guided` runners: real speakers, a real microphone, a real room.

Binding contract: `docs/testlab.md` ("Hardware profiles", "Guided runs").

These two profiles are the `audio` profile with ONE substitution, exactly as the `audio`
profile is the `virtual` profile with one substitution:

| Piece | `audio` | `hardware:*` |
|---|---|---|
| Audio bridge | `InjectedSourceAudio` (production writer, no PortAudio) | `DeviceAudio`: the PRODUCTION `SoundDeviceRealtimeAudio`, opening real streams |
| Microphone | a fixture pushed into `capture.process` | the room, through PortAudio's own callback |
| Speaker | `ImmediateOutputStream` | the workstation's output device |
| Echo coupling | the declared `echo.coupling_db` | whatever the room does |
| Duplex capture, canceller, near-end detector | production | production (unchanged) |

**What `hardware:auto` adds over `audio`.** The coupling stops being a number the run
states and becomes what the speaker, the room and the microphone actually do: real
delay, real reverberation, real clock drift between the two streams, real device
failure, real underruns. An `audio` run proves the canceller keeps the gate closed
against an echo the run itself constructed; a `hardware:auto` run proves it against an
echo nobody designed. No human is involved, so it can only make the NEGATIVE claim:
nothing confirmed a barge-in while the room was (assumed) quiet.

**What `hardware:guided` adds over `auto`.** A human. Two things follow, and only these
two: the silence is DECLARED rather than assumed (the human was asked to be quiet and
the run recorded whether they were), and a real human voice can be asked to interrupt,
which is the only way to measure the TRUE positive. "The echo gate never fires" and
"the echo gate fires for a person" are different claims, and the second one needs a
person.

Every device dead end is `MeasurementUnavailable` (`jarvis.testlab.hardware.devices`),
so a run reads `inconclusive` and never `crashed`: a microphone another application
holds is a fact about the workstation, not a defect of Jarvis and not a defect of ours.
"""

from __future__ import annotations

from array import array
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import math
from typing import Any

from jarvis.audio.duplex import NEAR_END
from jarvis.domain.v2 import SpeechKind
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.testlab.audio.chain import ChainMetadata, INPUT_BLOCK_MS, build_capture
from jarvis.testlab.audio.fixtures import (
    VOICE_SAMPLE_RATE,
    AudioFixtureError,
    AudioFixtureRoot,
    apply_gain_db,
    frame_peak_dbfs,
    wav_bytes,
)
from jarvis.testlab.audio.runners import (
    METADATA_SCHEMA,
    METADATA_SCHEMA_VERSION,
    OUTPUT_BLOCK_BYTES,
    wrap_slice,
)
from jarvis.testlab.diagnostics import MetricValue
from jarvis.testlab.hardware.devices import (
    DEVICE_NO_OUTPUT,
    DEVICE_NO_SIGNAL,
    DEVICE_OPEN_FAILED,
    DeviceSelection,
    check_device_formats,
    device_failure,
    read_configured_devices,
    resolve_device_selection,
)
from jarvis.testlab.hardware.prompts import (
    DEFAULT_PROMPT_DEADLINE_S,
    MAX_PROMPT_DEADLINE_S,
    GuidedAction,
    GuidedPrompter,
    GuidedPromptUnavailable,
    GuidedSession,
    prompt_for,
)
from jarvis.testlab.runners import MeasurementUnavailable, RunCancelled, RunContext, RunOutcome
from jarvis.testlab.runs import ArtifactKind
from jarvis.testlab.virtual.executor import VirtualExecutor
from jarvis.testlab.virtual.harness import CHUNK_MS, FakeAudio, VoiceStack
from jarvis.testlab.virtual.runners import (
    BARGE_IN_CONFIRMED_KINDS,
    BARGE_IN_DECISION_KINDS,
    BARGE_IN_REFUSED_KINDS,
    SPEECH_TERMINAL_KINDS,
    close_session,
    commit_trace,
    expectation_metrics,
    open_session,
    submit_user_turn,
    virtual_voice_stack,
    wait_condition,
)

HARDWARE_RUN_FAILED = "testlab_hardware_run_failed"
GUIDED_STEP_NOT_FOLLOWED = "testlab_guided_step_not_followed"
#: The human did the interrupt step and nothing was confirmed, in a diagnostic that
#: cannot express that as a verdict. "Could not measure", never a silent pass.
GUIDED_CLAIM_UNMEASURED = "testlab_guided_claim_unmeasured"
#: The metric that carries the guided positive claim, and the one a diagnostic declares a
#: blocking assertion on when it wants a zero to READ as a product failure.
TRUE_CONFIRMED_METRIC = "barge_in.true_confirmed_count"
#: How much output had been written when the first barge-in candidate was raised.
#: DECLARED, so `FIRST_ONSET_BLOCK` is visible in the evidence instead of being an
#: invisible constant: a reader sees that the candidate came after the canceller's
#: pre-roll, and a sweep can move it.
FIRST_ONSET_METRIC = "barge_in.first_candidate_offset_ms"

METADATA_ARTIFACT = "hardware_profile.json"
CLIP_ARTIFACT = "capture.wav"
#: The fixture a hardware seed plays through the speaker when a scenario names none.
DEFAULT_CLIP_REF = "reference-tone-1s.wav"
#: The first output block a barge-in candidate may be raised over. The production echo
#: canceller keeps a 400 ms pre-roll and learns the room's coupling from the first frames;
#: a candidate raised before that has elapsed measures the CONVERGENCE of the canceller,
#: not the gate, and would report a false positive that says nothing about Jarvis.
FIRST_ONSET_BLOCK = 400 // CHUNK_MS
#: Above this, with NOTHING playing, the room is not quiet: something as loud as a voice
#: is in it. The same floor the product's own device diagnostic calls "signal detected".
VOICE_FLOOR_DBFS = -50.0
#: One 16-bit LSB, which is what a stream of digital silence peaks at. At or below this,
#: the microphone heard literally nothing — not "a quiet room", which still carries the
#: echo of what Jarvis played.
SILENCE_FLOOR_DBFS = -90.0
#: How far above the echo-only level a near-end report has to be before the run treats it
#: as a person. The echo-only level is not a constant: it is measured in the SILENT phase
#: of the same run, in the same room, at the same volume.
ECHO_MARGIN_DB = 6.0
#: Microphone blocks the run listens to before Jarvis speaks, to learn what the room
#: sounds like on its own. Three 50 ms blocks; a human takes longer than that to breathe.
BASELINE_BLOCKS = 3
#: Blocks dropped before a baseline: the room is still returning Jarvis's last block.
SETTLE_BLOCKS = 1
#: Pause between two guided utterances, so the scheduler releases the floor before the
#: next turn asks for it. A human pauses far longer than this between two questions.
PHASE_SETTLE_S = 0.5

#: Prompt ids of the guided self-echo seed. Stable: they are what the stored evidence,
#: the CLI and the UI all call the same step.
PROMPT_SILENCE = "keep_silent_while_jarvis_speaks"
#: One brain work per phase: the guided seed says two separate things.
QUIET_WORK_ID = "self-echo-quiet"
CUT_IN_WORK_ID = "self-echo-interrupt"
DEFAULT_INTERRUPT_PHRASE = "jarvis arrete toi"
PROMPT_INTERRUPT = "interrupt_jarvis"
PROMPT_DONE = "confirm_the_session"


class HardwareRunError(MeasurementUnavailable):
    """A hardware run could not be brought to a state its diagnostic can measure.

    `MeasurementUnavailable`, like every other acoustic dead end in the Test Lab: no
    fixture, an output nobody played, a stimulus the stack never answered. It reads
    `inconclusive`, because none of it is a statement about Jarvis.
    """


def _failed(detail: str) -> HardwareRunError:
    return HardwareRunError(HARDWARE_RUN_FAILED, detail)


@dataclass(frozen=True, slots=True)
class RoomPlayback:
    """What one pass of `play_through_the_room` did."""

    #: Provider onsets the stack decided on (confirmed or rejected).
    decided: int
    #: Output already written when the FIRST barge-in candidate was raised, in ms, or
    #: `None` when none was. `FIRST_ONSET_BLOCK` makes this at least 400 ms by design;
    #: the metric exists so the convergence gap is visible in the evidence instead of
    #: being a constant buried in the runner.
    first_onset_ms: int | None = None
    #: The most audio this utterance ever had audible, in ms, sampled WHILE it played.
    #: `played_output_ms` is the cursor of the current output and goes back to zero when
    #: the device releases it — which is exactly what a confirmed barge-in does. Reading
    #: it afterwards reported "nothing was played" for the one case the run wants.
    played_ms: int = 0


@dataclass(frozen=True, slots=True)
class SpokenPhase:
    """What one utterance of a guided run produced, counted on its own.

    Separate counters per phase are the whole point: a barge-in the human caused in the
    `interrupt` phase must never be reported as a false positive of the `silent` phase.
    """

    text: str
    #: Provider onsets the stack decided on (confirmed or rejected).
    decided: int
    #: Output written when the first candidate was raised, in ms (`None`: none raised).
    first_onset_ms: int | None
    confirmed: int
    refused: int
    completed: bool
    #: Audio this utterance actually played, read while the output was still open:
    #: `played_output_ms` is the cursor of the CURRENT output and returns to zero when
    #: the device releases it, so reading it after the fact would report silence.
    played_ms: int


# ------------------------------------------------------------- the device audio

class LevelledCapture:
    """The production `CaptureProcessor`, with the RAW microphone level read on the way in.

    Measurement only: `process` returns exactly what the production object returned, and
    every other attribute IS the production object's. Nothing about the chain changes.

    It records EVIDENCE, never a decision. "Did the human make a sound during this step?"
    is answered by the product's own near-end signal, and it must be: on a hardware
    profile the raw microphone carries Jarvis's echo at exactly the level a voice has, and
    telling those two apart is the near-end detector's entire job. What the raw level adds
    is the number an operator reads afterwards — "the room was at -20 dBFS while I was
    asked to be silent" — which neither the cleaned frame (a working canceller makes it
    tiny, and a closed gate makes it nothing) nor a boolean can give them.
    """

    __slots__ = ("_inner", "peak", "session_peak")

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        #: Peak since the last `reset_peak` (one guided step).
        self.peak = 0
        #: Peak since the run began. Never reset: it is what proves the microphone was
        #: wired to something at all.
        self.session_peak = 0

    def process(self, pcm: bytes) -> tuple[bytes, tuple[str, ...]]:
        level = _peak_abs(pcm)
        self.peak = max(self.peak, level)
        self.session_peak = max(self.session_peak, level)
        return self._inner.process(pcm)

    def reset_peak(self) -> None:
        """Start a new window. `session_peak` is never reset: it is the run's own floor check."""
        self.peak = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class DeviceAudio(SoundDeviceRealtimeAudio):
    """The PRODUCTION audio bridge, opening this run's REAL devices, with level accounting.

    Nothing about the audio path is substituted: this IS
    `jarvis.runtime.realtime_audio.SoundDeviceRealtimeAudio`, so the PortAudio streams,
    the callback, the chunked writer, the reference push and the duplex capture are the
    ones Realtime Voice runs. The subclass adds exactly two things, neither of which
    changes behaviour:

    - the run's `DeviceSelection` wins over whatever the runtime was configured with, so
      the devices the pre-flight checked are the devices that get opened;
    - a peak level and the capture signals per window, so a guided step can say what the
      microphone heard while it was open — which is the evidence a human-as-actor run
      exists to produce.

    It registers in `FakeAudio.instances` because that list is how `VoiceStack.audio`
    finds the bridge the harness mounted. That is the harness's lookup, not a claim that
    this class is a double: it is the opposite of one.
    """

    #: Set per run by `device_audio_class`; the default is "PortAudio's own defaults".
    _selection: DeviceSelection = DeviceSelection()

    def __init__(self, *, input_device=None, output_device=None, **rates) -> None:  # noqa: ANN001
        selection = type(self)._selection
        super().__init__(
            input_device=selection.input_device if selection.input_device is not None else input_device,
            output_device=selection.output_device if selection.output_device is not None else output_device,
            **rates)
        #: Every capture signal the production callback raised, in order.
        self.capture_signals: list[str] = []
        self._peak_sample = 0
        FakeAudio.instances.append(self)

    def _deliver_capture(self, captured: int, processed: bytes, signals: tuple[str, ...]) -> None:
        """The production delivery, plus the level and signal accounting a guided step reads."""
        if processed:
            self._peak_sample = max(self._peak_sample, _peak_abs(processed))
        self.capture_signals.extend(str(signal) for signal in signals)
        super()._deliver_capture(captured, processed, signals)

    @property
    def written_output_ms(self) -> int:
        """Audio handed to the OUTPUT DEVICE, before the stream latency is subtracted.

        `played_output_ms` is the audible figure, and it is the right one for a barge-in
        cursor and the wrong one for "has this block reached the device yet": on a device
        whose latency exceeds one block, the audible figure is still zero when two blocks
        have already been written. A run that waited on it would raise its stimulus before
        Jarvis was playing at all.
        """
        with self._cursor_lock:
            return int(self._written_ms_locked())

    def heard_voice_since(self, mark: tuple[int, int], *, above_dbfs: float) -> bool:
        """Did the capture report a near-end voice LOUD ENOUGH not to be Jarvis, since `mark`?

        Both halves are needed and neither is enough. The near-end signal is the product's
        own live judgement, and it is the only thing that can say "somebody is talking over
        Jarvis" while Jarvis is talking. The level is what tells that judgement apart from
        the canceller's own residual: `above_dbfs` is what this microphone reads when
        Jarvis speaks and NOBODY is talking, measured in this same run, so a voice has to
        beat the echo rather than merely exist alongside it.
        """
        peak, signals, _captured = self.heard_since(mark)
        return NEAR_END in signals and peak > above_dbfs

    @property
    def run_peak_dbfs(self) -> float | None:
        """Loudest raw microphone sample of the whole run, or `None` without a level probe."""
        probe = self.capture
        if not isinstance(probe, LevelledCapture):
            return None
        return _sample_dbfs(probe.session_peak)

    # A "window" is one guided step: mark it open, read what was heard while it was.
    def mark(self) -> tuple[int, int]:
        self._peak_sample = 0
        probe = self.capture
        if isinstance(probe, LevelledCapture):
            probe.reset_peak()
        return len(self.capture_signals), int(self.captured_bytes)

    def heard_since(self, mark: tuple[int, int]) -> tuple[float, tuple[str, ...], int]:
        """`(peak dBFS, capture signals, bytes captured)` since `mark`.

        The peak is the RAW microphone level when the run mounted a `LevelledCapture`,
        which is what a guided run does; it falls back to the cleaned level otherwise,
        and says so by simply being quieter.
        """
        probe = self.capture
        raw = probe.peak if isinstance(probe, LevelledCapture) else 0
        signals = tuple(self.capture_signals[mark[0]:])
        return _sample_dbfs(max(raw, self._peak_sample)), signals, int(self.captured_bytes) - mark[1]


def _peak_abs(pcm: bytes) -> int:
    samples = array("h")
    samples.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    return max((abs(sample) for sample in samples), default=0)


def _sample_dbfs(peak: int) -> float:
    """Peak sample as dBFS, on the product's own scale (`SoundDeviceAudioDiagnostics._levels`)."""
    return 20.0 * math.log10(max(peak, 1) / 32768.0)


def device_audio_class(selection: DeviceSelection) -> type[DeviceAudio]:
    """A `DeviceAudio` bound to one run's devices.

    A class, because the harness substitutes a CLASS for `SoundDeviceRealtimeAudio` and
    the voice runtime constructs it itself; a fresh subclass per run, because a class
    attribute shared between runs would leak one run's device choice into the next.
    """
    return type("RunDeviceAudio", (DeviceAudio,), {"_selection": selection})


# ---------------------------------------------------------------- the socle

@asynccontextmanager
async def hardware_voice_stack(context: RunContext, *, echo_cancellation: bool = True):
    """Mount the production voice path over this workstation's REAL audio devices.

    Order matters and is the safety property of this Slice: the devices are chosen and
    pre-flighted BEFORE anything is mounted, so the common failures (no such device, a
    format the driver refuses, a microphone another application holds) are reported with
    their own code and nothing is opened. The supervisor has already refused the run if
    the live Jarvis holds the devices; this is the layer below that, for everything the
    detector cannot see.

    The stack is always torn down, including on cancellation, the run deadline and a
    crash: `virtual_voice_stack` stops the voice runtime in its own `finally`, which
    closes the bridge, and the `finally` here closes it again if anything got past that.
    Closing twice is safe; leaving the microphone open is not.
    """
    selection = resolve_device_selection(context.parameters, read_configured_devices(context.runtime_dir))
    context.log(f"devices: input={selection.input_device!r} ({selection.input_source}) "
                f"output={selection.output_device!r} ({selection.output_source})")
    check_device_formats(selection)
    build = build_capture(capture_rate=VOICE_SAMPLE_RATE, render_rate=VOICE_SAMPLE_RATE,
                          echo_cancellation=echo_cancellation)
    if build.aec_error is not None:
        context.log(f"echo canceller unavailable: {build.aec_error}")
    context.log(f"audio chain: aec_engaged={build.aec_engaged} reason={build.aec_unavailable_reason}")
    capture = LevelledCapture(build.capture)
    try:
        async with virtual_voice_stack(context, capture_factory=lambda: capture,
                                       audio_class=device_audio_class(selection)) as (stack, journal, core):
            yield stack, journal, core, build, selection
    finally:
        # Read here, not at entry: the bridge is constructed when the voice runtime
        # ACTIVATES, which is several awaits after the stack is mounted.
        # Belt and braces: the runtime's own teardown already closes the bridge, and a
        # device this process still held after the run is the one outcome that would
        # break the user's live Jarvis rather than just this run. Closing twice is safe.
        for opened in [item for item in FakeAudio.instances if isinstance(item, DeviceAudio)]:
            try:
                await opened.close()
            except Exception as exc:
                # Captured: the run is over, and a close that failed is worth saying
                # out loud rather than raising over a measurement already taken.
                context.log(f"an audio device did not close cleanly: {type(exc).__name__}: {exc}")


def mounted_device_audio(stack: VoiceStack) -> DeviceAudio:
    """The real bridge the voice runtime mounted, once the session is open.

    `VoiceStack.audio` is the harness's own lookup (`FakeAudio.instances[-1]`); this
    wrapper exists to fail with a sentence instead of an `IndexError` when a caller
    reaches for the bridge before the voice has woken.
    """
    audio = FakeAudio.instances[-1] if FakeAudio.instances else None
    if not isinstance(audio, DeviceAudio):
        raise _failed("the hardware profile did not mount its real audio bridge; the voice never activated")
    return audio


async def open_device_session(context: RunContext, stack: VoiceStack) -> None:
    """Wake the voice, turning any failure to actually open the devices into "could not measure".

    Broad on purpose, with the argument written here: everything between this call and
    PortAudio is native code on a machine we do not control, and every way it can fail —
    a device unplugged since the pre-flight, a driver that hangs until the harness gives
    up waiting for `audio.start`, an exclusive hold taken a moment ago — means the same
    thing to a reader: this run never got the microphone. Reading any of it as `crashed`
    would blame the lab for the workstation.
    """
    try:
        await open_session(context, stack)
    except (RunCancelled, MeasurementUnavailable):
        raise
    except Exception as exc:
        raise device_failure(
            DEVICE_OPEN_FAILED,
            f"the voice runtime could not open the selected audio devices ({type(exc).__name__}); "
            "no measurement was taken and nothing was left holding them") from exc


def hardware_metadata(context: RunContext, build: Any, selection: DeviceSelection,
                      audio: DeviceAudio) -> ChainMetadata:
    """What this run actually exercised. Device IDS, never an enumeration of the machine."""
    return ChainMetadata(
        profile=context.profile.value, sample_rate=int(audio.sample_rate),
        output_sample_rate=int(audio.output_sample_rate), input_block_ms=INPUT_BLOCK_MS,
        input_device=None if selection.input_device is None else str(selection.input_device),
        output_device=None if selection.output_device is None else str(selection.output_device),
        device_opened=True, duplex_engaged=audio.capture is not None, aec_engaged=build.aec_engaged,
        aec_unavailable_reason=build.aec_unavailable_reason, canceller=build.canceller_name)


def write_metadata(context: RunContext, metadata: ChainMetadata,
                   extra: Mapping[str, Any] | None = None) -> None:
    """Commit `hardware_profile.json`: a bounded `report`, the same shape the audio profile writes."""
    document: dict[str, Any] = {"schema": METADATA_SCHEMA, "schema_version": METADATA_SCHEMA_VERSION,
                                "run_id": context.run_id, **metadata.to_dict()}
    if extra:
        document.update(extra)
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    context.put_artifact(METADATA_ARTIFACT, kind=ArtifactKind.REPORT, media_type="application/json", data=payload)


def load_clip(ref: object = DEFAULT_CLIP_REF, *, gain_db: float = 0.0,
              root: AudioFixtureRoot | None = None) -> bytes:
    """A shipped fixture as PCM at the voice rate. A missing one is a measurement dead end."""
    try:
        clip = (root if root is not None else AudioFixtureRoot()).load(ref)
    except AudioFixtureError as exc:
        raise HardwareRunError(exc.code, exc.detail) from exc
    return apply_gain_db(clip.pcm, gain_db)


def _terminal_of(journal, speech_id: str) -> str | None:
    for line in journal.timeline:
        if line.kind in SPEECH_TERMINAL_KINDS and line.data.get("speech_id") == speech_id:
            return line.kind
    return None


def check_device_evidence(context: RunContext, audio: DeviceAudio, played_ms: int) -> None:
    """Refuse to report an acoustic measurement taken with a dead microphone or a mute speaker.

    This is the anti-vacuity rule of the hardware profiles. "No false barge-in" from a
    microphone that captured nothing is not a passing run, it is an empty one, and a
    passing empty run is worse than an inconclusive one because somebody will believe it.

    Three checks, and the third is why counting bytes is not enough: a driver that streams
    digital silence delivers as many bytes as a working one. So the run also requires that
    SOMETHING was above the digital floor over its whole length — one LSB, `-90.3` dBFS.
    That is a bound on "the microphone is wired to nothing", not a judgement about the
    room: a quiet room still carries Jarvis's own echo, which is the whole stimulus. The
    level comes from `LevelledCapture`, so a run that did not mount one (no duplex
    capture) keeps the byte check alone and says so in the log rather than failing.
    """
    if played_ms <= 0:
        raise device_failure(DEVICE_NO_OUTPUT,
                             "nothing was played through the output device, so no echo could exist and "
                             "nothing about the echo gate was measured")
    if int(audio.captured_bytes) <= 0:
        raise device_failure(DEVICE_NO_SIGNAL,
                             "the microphone delivered no audio at all during the run, so every acoustic "
                             "measurement would be vacuous")
    peak = audio.run_peak_dbfs
    if peak is None:
        context.log("no capture level was observed (this run mounted no duplex capture); the "
                    "microphone evidence is the byte count alone")
    elif peak <= SILENCE_FLOOR_DBFS:
        raise device_failure(DEVICE_NO_SIGNAL,
                             f"the microphone delivered {audio.captured_bytes} bytes of digital silence "
                             f"(peak {peak:.1f} dBFS) while Jarvis was playing, so it heard neither the "
                             "room nor Jarvis and every acoustic measurement would be vacuous")
    context.log(f"device evidence: played_ms={played_ms} captured_bytes={audio.captured_bytes} "
                f"peak_dbfs={peak} signals={sorted(set(audio.capture_signals))}")


def store_clip(context: RunContext, pcm: bytes, *, path: str = CLIP_ARTIFACT) -> bool:
    """Store an audio clip IF this run was allowed audio artifacts. Returns whether it was.

    Never by default. On a hardware profile the clip is a recording of the user's ROOM,
    so all three Slice 08 conditions must hold (the caller asked, the profile can produce
    audio, the store allows it) and the store still refuses at commit. A refusal is
    logged, not fatal: losing the optional evidence must not lose the measurement.
    """
    from jarvis.testlab.store import TestLabStoreError

    try:
        context.put_artifact(path, kind=ArtifactKind.AUDIO_CLIP, media_type="audio/wav",
                             data=wav_bytes(pcm, VOICE_SAMPLE_RATE))
    except TestLabStoreError as exc:
        context.log(f"audio clip not stored ({exc.code}): {exc.detail}")
        return False
    return True


# ------------------------------------------------- voice.self_echo.hardware_auto

@dataclass(frozen=True, slots=True)
class SelfEchoHardwareRunner:
    """`voice.self_echo` in a real room, with no human: the negative acoustic claim.

    Jarvis speaks through the workstation's speaker; the workstation's microphone hears
    whatever the room returns; the production canceller and near-end detector decide.
    Provider VAD onsets are raised while that is happening, and every one the stack
    CONFIRMS is a barge-in triggered by Jarvis's own voice in a real room.

    What it cannot prove: that a real human voice WOULD get through. A gate that never
    opens passes this diagnostic perfectly and is completely broken, which is why the
    guided profile exists and why the two should be read together.
    """

    async def run(self, context: RunContext) -> RunOutcome:
        duration_ms = int(context.parameters["output.duration_ms"])
        echoes = int(context.parameters["echo.candidate_count"])
        clip = load_clip()
        async with hardware_voice_stack(context) as (stack, journal, _core, build, selection):
            await open_device_session(context, stack)
            audio = mounted_device_audio(stack)
            handle = await submit_user_turn(context, stack, "jarvis raconte moi la journee en detail")
            await handle.start_work("self-echo", label="self echo")
            request = await handle.say("voici le recit complet de la journee que jarvis prononce",
                                       kind=SpeechKind.RESULT, work_id="self-echo")
            await wait_condition(context, lambda: len(stack.session.spoken) >= 1,
                                 "the scheduler dispatching the speech to the surface")
            playback = await play_through_the_room(context, stack, journal, audio, request.id,
                                                   duration_ms, echoes, clip,
                                                   onset=self.raise_onset)
            played_ms = playback.played_ms
            if _terminal_of(journal, request.id) is None:
                await stack.session.finish_output(status="completed", transcript=request.text)
            await handle.complete_work("self-echo", summary=request.text)
            handle.finish(public_summary=request.text)
            await wait_condition(context, lambda: bool(_terminal_of(journal, request.id)),
                                 "a terminal status for the speech")
            confirmed = journal.counts(*BARGE_IN_CONFIRMED_KINDS)
            refused = journal.counts(*BARGE_IN_REFUSED_KINDS)
            completed = _terminal_of(journal, request.id) == "voice.speech.completed"
            metadata = hardware_metadata(context, build, selection, audio)
            context.log(f"self echo (hardware): aec={build.aec_engaged} decisions={playback.decided} "
                        f"confirmed={confirmed} refused={refused} played_ms={played_ms} "
                        f"first_onset_ms={playback.first_onset_ms}")
            check_device_evidence(context, audio, played_ms)
            await close_session(context, stack)
        if playback.decided == 0 and echoes:
            raise _failed("the stack never decided on a provider onset over the room's echo, so nothing "
                          "about barge-in was measured")
        write_metadata(context, metadata, {"echo_source": "room",
                                           "reference_peak_dbfs": round(frame_peak_dbfs(clip), 1)})
        await commit_trace(context, journal)
        return declared_metrics(context, {
            "barge_in.false_confirmed_count": confirmed,
            "barge_in.rejected_count": refused,
            "output.completed": completed,
            "output.played_ms": played_ms,
            FIRST_ONSET_METRIC: playback.first_onset_ms,
        })

    async def raise_onset(self, context: RunContext, stack: VoiceStack) -> bool:
        """One provider VAD onset over the room's echo.

        Overridable seam, the same one `SelfEchoAudioRunner.inject_echo_candidate` offers:
        a test makes a REAL near-end noise in the room here, which is how the matching
        positive case is built without a person. Nothing in a real run overrides it — on
        `hardware:guided` the human makes the noise, and the runner still raises the onset
        because the Realtime session is the deterministic double on both profiles.
        """
        del context
        await stack.session.interrupt()
        return True


async def play_through_the_room(context: RunContext, stack: VoiceStack, journal, audio: DeviceAudio,
                                speech_id: str, duration_ms: int, candidates: int, clip: bytes,
                                *, onset: Any = None) -> RoomPlayback:
    """Play the fixture block by block through the REAL speaker, raising provider onsets.

    No echo is injected: the room is what returns the sound, which is the whole point of
    the profile. Nothing here paces the output either — a real output stream blocks until
    its buffer has room, and that IS the pacing; inventing a second one would measure the
    harness rather than the room.

    Two rules, and both of them are about not manufacturing the result:

    - **each block reaches the device before the next one is queued.** `play_audio` only
      hands the provider double a block; the bridge writes it later. A run that queued
      eight blocks and then raised its stimulus would raise it while nothing had played,
      the echo canceller would have no far end, and the gate would open — a false positive
      built by the runner. The wait is on `written_output_ms`, not on the audible figure,
      so a device with a long latency does not stall it.
    - **the output never stops while a decision is pending.** An onset is raised and the
      next block is played immediately; the decisions are collected after the last block.
      Stopping to wait would let Jarvis fall silent mid-sentence, the far-end window would
      expire, and the gate would open for a reason that has nothing to do with the room.

    Every onset must still be DECIDED (confirmed or rejected): the anti-vacuity rule the
    virtual and audio seeds use, because a stack that never answers provider VAD would
    pass every assertion while being deaf.
    """
    blocks = max(1, duration_ms // CHUNK_MS)
    every = max(1, blocks // candidates) if candidates else 0
    before = journal.counts(*BARGE_IN_DECISION_KINDS)
    raised = 0
    first_onset_ms: int | None = None
    played_ms = 0
    for block in range(blocks):
        context.check_cancelled()
        if _terminal_of(journal, speech_id) is not None:
            break
        offset = (block * OUTPUT_BLOCK_BYTES) % max(OUTPUT_BLOCK_BYTES, len(clip))
        await stack.session.play_audio(pcm=wrap_slice(clip, offset, OUTPUT_BLOCK_BYTES))
        written = (block + 1) * CHUNK_MS
        await wait_condition(context,
                             lambda: (audio.written_output_ms >= written
                                      or _terminal_of(journal, speech_id) is not None),
                             f"{written} ms of Jarvis output reaching the output device")
        played_ms = max(played_ms, int(audio.played_output_ms))
        if (candidates and raised < candidates and block >= FIRST_ONSET_BLOCK
                and (block - FIRST_ONSET_BLOCK) % every == 0):
            if first_onset_ms is None:
                # One microphone block before the first candidate, and only the first: the
                # canceller's far-end window is filled by what the room RETURNS, not by
                # what was written, and a candidate raised before anything came back is
                # decided against an empty reference — a confirmation that says nothing
                # about the room. One block is 50 ms against 400 ms already playing, so
                # the output does not fall silent for it.
                await wait_for_capture(context, audio)
            if await raise_provider_onset(context, stack, onset):
                first_onset_ms = first_onset_ms if first_onset_ms is not None else audio.written_output_ms
                raised += 1
    while raised < candidates and _terminal_of(journal, speech_id) is None:
        context.check_cancelled()
        if not await raise_provider_onset(context, stack, onset):
            # The onset DECLINED: there is nothing for the provider to report. Retrying
            # after the output has ended would only invent a stimulus the situation did
            # not contain.
            break
        first_onset_ms = first_onset_ms if first_onset_ms is not None else audio.written_output_ms
        raised += 1
    await wait_condition(context, lambda: audio.played_output_ms > 0 or played_ms > 0
                         or _terminal_of(journal, speech_id) is not None,
                         "Jarvis's output reaching the output device")
    played_ms = max(played_ms, int(audio.played_output_ms))
    if raised:
        await wait_condition(
            context,
            lambda: (journal.counts(*BARGE_IN_DECISION_KINDS) >= before + raised
                     or _terminal_of(journal, speech_id) is not None),
            "a barge-in decision for every provider onset raised over the room's echo")
    return RoomPlayback(decided=journal.counts(*BARGE_IN_DECISION_KINDS) - before,
                        first_onset_ms=first_onset_ms,
                        played_ms=max(played_ms, int(audio.played_output_ms)))


async def raise_provider_onset(context: RunContext, stack: VoiceStack, onset: Any = None) -> bool:
    """One provider VAD onset, if there is one to raise. The decision is collected later.

    Returns whether an onset was actually raised. A seam may DECLINE: a real provider
    reports that the user is speaking when the user is speaking, and a run that raised the
    report anyway would be asking the echo gate to decide on a person who is not there.
    """
    if onset is None:
        await stack.session.interrupt()
        return True
    return bool(await onset(context, stack))


async def measure_room(context: RunContext, audio: DeviceAudio) -> float:
    """What the microphone hears with nothing playing: this room's own level, in dBFS.

    The control measurement of any acoustic claim. A room that is already as loud as a
    voice cannot support "no false barge-in while it was quiet", and saying so is the
    honest outcome — a number an operator reads and acts on, not a hidden assumption.

    The first block is dropped: taken right after Jarvis stopped, it still carries the
    tail of what the room is returning, and measuring that would report Jarvis as noise.
    """
    for _ in range(SETTLE_BLOCKS):
        await wait_for_capture(context, audio)
    mark = audio.mark()
    for _ in range(BASELINE_BLOCKS):
        await wait_for_capture(context, audio)
    peak, _signals, _captured = audio.heard_since(mark)
    return peak


async def wait_for_capture(context: RunContext, audio: DeviceAudio) -> None:
    """Wait for one more microphone block to come back through the production capture path."""
    before = int(audio.captured_bytes)
    await wait_condition(context, lambda: int(audio.captured_bytes) > before,
                         "a microphone block reaching the duplex capture")


# ----------------------------------------------- voice.self_echo.hardware_guided

@dataclass(frozen=True, slots=True)
class SelfEchoGuidedRunner:
    """`voice.self_echo` with the human as an actor: the negative AND the positive claim.

    Jarvis speaks TWICE, and the human is addressed before each time:

    1. **remain silent** while Jarvis speaks. Provider onsets are raised over the room's
       own echo, and every one the stack confirms is a FALSE positive. The run records
       whether the microphone heard a near-end voice during the window: a human who spoke
       anyway voids the claim, because "no false barge-in while the room was quiet" is a
       statement about a quiet room.
    2. **interrupt** Jarvis, who is speaking again. One onset is raised, and whether the
       stack confirms it is the TRUE positive. A human who spoke and was not heard is not
       an error — it IS the measurement, and the declared assertion decides what it means.
    3. **acknowledge** that the session sounded right, which is the one judgement no
       metric can make.

    Two utterances rather than one, because the first one ends when the human interrupts
    it or when it runs out: a second phase sharing the first speech would have nothing
    left to interrupt. The phases are counted separately, so a confirmation caused by the
    human in phase 2 can never be reported as a false positive of phase 1.
    """

    #: Injected by a test; `None` means the file channel a CLI or the UI drives.
    prompter: GuidedPrompter | None = None

    async def run(self, context: RunContext) -> RunOutcome:
        duration_ms = int(context.parameters["output.duration_ms"])
        echoes = int(context.parameters["echo.candidate_count"])
        phrase = str(context.parameters.get("human.interrupt_phrase") or DEFAULT_INTERRUPT_PHRASE)
        clip = load_clip()
        async with hardware_voice_stack(context) as (stack, journal, _core, build, selection):
            session = GuidedSession(context=context, prompter=build_prompter(context, self.prompter))
            try:
                await open_device_session(context, stack)
                audio = mounted_device_audio(stack)
                # --- phase 1: the human is asked to be quiet; every confirmation is false.
                await session.ask(prompt_for(GuidedAction.REMAIN_SILENT, PROMPT_SILENCE,
                                             deadline_s=_phase_deadline(context, duration_ms)))
                baseline = await measure_room(context, audio)
                context.log(f"room baseline with nothing playing: {baseline:.1f} dBFS")
                mark = audio.mark()
                quiet = await self._speak(context, stack, journal, audio, clip, QUIET_WORK_ID,
                                          "jarvis raconte moi la journee en detail",
                                          "voici le recit complet de la journee que jarvis prononce",
                                          duration_ms, echoes)
                peak, signals, captured = audio.heard_since(mark)
                quiet_room = RoomVoice(before_dbfs=baseline,
                                       after_dbfs=await measure_room(context, audio),
                                       near_end_seen=NEAR_END in signals, window_peak_dbfs=peak)
                # `certain` in BOTH steps: "a person made a sound" means the same thing
                # and is measured the same way, whichever claim needs it. A suspicion is
                # recorded (`near_end_seen`) and never decides on its own — that is the
                # whole lesson of the empty room that certified a human interrupt.
                session.observe(PROMPT_SILENCE, voice=quiet_room.certain,
                                peak_dbfs=max(peak, baseline, quiet_room.after_dbfs),
                                **quiet_room.to_dict())
                context.log(f"silent phase: peak={peak:.1f} dBFS room before={baseline:.1f} "
                            f"after={quiet_room.after_dbfs:.1f} captured={captured} B "
                            f"signals={sorted(set(signals))} decided={quiet.decided} "
                            f"confirmed={quiet.confirmed} first_onset_ms={quiet.first_onset_ms}")

                # --- phase 2: the human is asked to interrupt; a confirmation is the measurement.
                await session.ask(prompt_for(GuidedAction.INTERRUPT, PROMPT_INTERRUPT, phrase=phrase,
                                             deadline_s=_phase_deadline(context, duration_ms)))
                mark = audio.mark()
                # What this microphone reads while Jarvis speaks and NOBODY is talking,
                # measured a moment ago in this same room: the bar a voice has to clear.
                echo_level = quiet_room.window_peak_dbfs
                cut_in = await self._speak(context, stack, journal, audio, clip, CUT_IN_WORK_ID,
                                           "jarvis continue ton recit s il te plait",
                                           "jarvis poursuit son recit pour laisser le temps de le couper",
                                           duration_ms, 1,
                                           onset=heard_voice_onset(mark, above_dbfs=echo_level
                                                                   + ECHO_MARGIN_DB))
                peak, signals, captured = audio.heard_since(mark)
                spoken_room = RoomVoice(before_dbfs=quiet_room.after_dbfs,
                                        after_dbfs=await measure_room(context, audio),
                                        near_end_seen=NEAR_END in signals, window_peak_dbfs=peak)
                # The SAME object, the same measurements and the same predicate as phase 1.
                # The window peak carries Jarvis's echo at a voice's level, and the near-end
                # signal also rises on the canceller's residual, so either of them alone
                # certifies an empty room as a human interrupt — measured, deterministically,
                # from 2 500 ms of speech upwards. Only a silent-window measurement can say
                # a person was there.
                session.observe(PROMPT_INTERRUPT, voice=spoken_room.certain,
                                peak_dbfs=max(peak, spoken_room.after_dbfs),
                                **spoken_room.to_dict())
                context.log(f"interrupt phase: peak={peak:.1f} dBFS room after="
                            f"{spoken_room.after_dbfs:.1f} echo_bar={echo_level + ECHO_MARGIN_DB:.1f} "
                            f"captured={captured} B signals={sorted(set(signals))} "
                            f"decided={cut_in.decided} confirmed={cut_in.confirmed} "
                            f"voice_certain={spoken_room.certain}")

                await session.ask(prompt_for(GuidedAction.ACKNOWLEDGE, PROMPT_DONE))
            finally:
                # Always: the transcript of a run a human abandoned is exactly the
                # evidence worth keeping, and the store is still open here.
                session.commit()
            played_ms = quiet.played_ms + cut_in.played_ms
            metadata = hardware_metadata(context, build, selection, audio)
            check_device_evidence(context, audio, played_ms)
            await close_session(context, stack)
        require_silent_phase(session, quiet.confirmed)
        require_measurable_interrupt(context, session, cut_in.confirmed, heard=spoken_room.certain)
        if quiet.decided == 0 and echoes:
            raise _failed("the stack never decided on a provider onset while the human was silent, so "
                          "nothing about the echo gate was measured")
        write_metadata(context, metadata, {"echo_source": "room", "guided": True,
                                           "prompt_count": session.prompt_count})
        await commit_trace(context, journal)
        return declared_metrics(context, {
            "barge_in.false_confirmed_count": quiet.confirmed,
            TRUE_CONFIRMED_METRIC: cut_in.confirmed,
            "barge_in.rejected_count": quiet.refused + cut_in.refused,
            "output.completed": quiet.completed and cut_in.completed,
            "output.played_ms": played_ms,
            "guided.prompt_count": session.prompt_count,
            "guided.late_prompt_count": session.late_count,
            FIRST_ONSET_METRIC: quiet.first_onset_ms,
        })

    async def _speak(self, context: RunContext, stack: VoiceStack, journal, audio: DeviceAudio,
                     clip: bytes, work_id: str, asked: str, text: str, duration_ms: int,
                     candidates: int, *, onset: Any = None) -> SpokenPhase:
        """One TURN: the user asks, Jarvis answers through the real speaker, onsets are raised.

        A whole turn per phase, and that is not a stylistic choice: a second result under a
        work the scheduler has already completed is superseded rather than spoken, and a
        second work inside the same turn is not dispatched either (measured). Asking again
        is also what the person in front of the workstation actually does. The cost is a
        race with the floor the previous speech has not finished releasing, which the
        settle below bounds and the `played_ms` check below catches when it is not enough.
        """
        confirmed = journal.counts(*BARGE_IN_CONFIRMED_KINDS)
        refused = journal.counts(*BARGE_IN_REFUSED_KINDS)
        dispatched = len(stack.session.spoken)
        handle = await submit_user_turn(context, stack, asked)
        await handle.start_work(work_id, label="self echo")
        request = await handle.say(text, kind=SpeechKind.RESULT, work_id=work_id)
        await wait_condition(context, lambda: len(stack.session.spoken) > dispatched,
                             "the scheduler dispatching the speech to the surface")
        playback = await play_through_the_room(context, stack, journal, audio, request.id,
                                               duration_ms, candidates, clip, onset=onset)
        played_ms = playback.played_ms
        if _terminal_of(journal, request.id) is None:
            await stack.session.finish_output(status="completed", transcript=request.text)
        await wait_condition(context, lambda: bool(_terminal_of(journal, request.id)),
                             "a terminal status for the speech")
        await handle.complete_work(work_id, summary=request.text)
        handle.finish(public_summary=request.text)
        if played_ms <= 0:
            # Never attributed to the human: a phase that played nothing measured nothing,
            # and reporting "they did not interrupt" for it would blame the person for a
            # sentence Jarvis never said.
            raise device_failure(
                DEVICE_NO_OUTPUT,
                f"the '{work_id}' phase reached the device with no audio, so nothing could be heard "
                "and nothing about that step was measured")
        # Let the scheduler release the floor before the next phase asks for it. A bounded
        # settle and not a condition, because "the floor is free" is not observable from
        # here; what IS observable is the failure above if it was not.
        await context.sleep(PHASE_SETTLE_S)
        return SpokenPhase(
            text=request.text, decided=playback.decided, played_ms=played_ms,
            first_onset_ms=playback.first_onset_ms,
            confirmed=journal.counts(*BARGE_IN_CONFIRMED_KINDS) - confirmed,
            refused=journal.counts(*BARGE_IN_REFUSED_KINDS) - refused,
            completed=_terminal_of(journal, request.id) == "voice.speech.completed")


@dataclass(frozen=True, slots=True)
class RoomVoice:
    """What the run knows about whether a PERSON made a sound during one guided step.

    Three measurements, and what separates them is whether they can be Jarvis:

    - `before_dbfs` / `after_dbfs` are taken with NOTHING playing, at either end of the
      step. Nothing Jarvis does can raise them, so they are the only evidence that can
      CERTIFY a voice.
    - `near_end_seen` is the product's live judgement while Jarvis was speaking. It is the
      only thing that can catch somebody who starts and stops inside the step, and it is
      the only thing that can be the canceller's own residual. It SUSPECTS; it never
      certifies.

    Both guided steps use this same object. What differs is which predicate each CLAIM
    needs, and that is a property of the claim rather than an asymmetry: proving nobody
    spoke must be conservative (a suspicion is enough to void it), and proving somebody DID
    must not be (a suspicion would certify an empty room, which is exactly the defect this
    class exists to make impossible).
    """

    before_dbfs: float
    after_dbfs: float
    near_end_seen: bool
    #: What the microphone read during the step, echo included. Evidence for an operator,
    #: never a decision: on a hardware profile it carries Jarvis at a voice's level.
    window_peak_dbfs: float

    @property
    def certain(self) -> bool:
        """A voice was in the room, on evidence that cannot be Jarvis."""
        return max(self.before_dbfs, self.after_dbfs) > VOICE_FLOOR_DBFS

    @property
    def suspected(self) -> bool:
        """Something was heard over Jarvis. Possibly a person, possibly a residual."""
        return self.near_end_seen

    def to_dict(self) -> dict[str, Any]:
        """The provenance of the decision, stored with the prompt record."""
        return {"room_before_dbfs": round(self.before_dbfs, 1),
                "room_after_dbfs": round(self.after_dbfs, 1),
                "window_peak_dbfs": round(self.window_peak_dbfs, 1),
                "near_end_seen": self.near_end_seen,
                "voice_floor_dbfs": VOICE_FLOOR_DBFS,
                "certain": self.certain}


def heard_voice_onset(mark: tuple[int, int], *, above_dbfs: float) -> Any:
    """The interrupt phase's provider onset: raised only when a voice was actually heard.

    A provider reports that the user is speaking when the user is speaking. Raising the
    report unconditionally asks the echo gate to decide on a person who is not there, and
    what it decides then is about the canceller — which is exactly what it looked like: a
    confirmation, with the room empty, reported as "a real voice got through". Declining
    instead leaves `barge_in.true_confirmed_count` at zero and lets
    `require_measurable_interrupt` say the claim was not measured.

    `above_dbfs` is what this microphone reads while Jarvis speaks and nobody is talking,
    measured in the SILENT phase of this same run: the bare near-end signal was not enough,
    because the detector also raises on the canceller's residual over a long utterance.
    """
    async def raise_when_heard(context: RunContext, stack: VoiceStack) -> bool:
        del context
        if not mounted_device_audio(stack).heard_voice_since(mark, above_dbfs=above_dbfs):
            return False
        await stack.session.interrupt()
        return True

    return raise_when_heard


def require_silent_phase(session: GuidedSession, confirmed: int) -> None:
    """A human who spoke during "remain silent" voids the false-positive claim.

    This is the diagnostic deciding, which is where that decision belongs: the same
    observation on the `interrupt` step is not a problem at all, it is the point. The
    module that records prompts never makes this call.

    Two ways in, and the second is narrow on purpose. A voice CERTAIN to have been in the
    room voids the claim outright. A mere suspicion — the capture reported a near-end that
    may equally have been the canceller's residual — voids it only if the phase actually
    confirmed a barge-in, because then the confirmation cannot be attributed to either. A
    suspicion on its own must not: over several seconds of continuous speech the detector
    raises on its own residual in an empty room, and voiding every long run for that would
    make the diagnostic unusable at its own declared default.
    """
    record = session.record_of(PROMPT_SILENCE)
    if record is None or not record.usable:
        return
    if record.followed is False:
        raise GuidedPromptUnavailable(
            GUIDED_STEP_NOT_FOLLOWED,
            f"the room measured {record.evidence.get('room_after_dbfs')} dBFS with nothing playing "
            "while the human was asked to stay silent, so a barge-in confirmed in that window cannot "
            "be attributed to Jarvis's own echo")
    if confirmed and record.evidence.get("near_end_seen"):
        raise GuidedPromptUnavailable(
            GUIDED_STEP_NOT_FOLLOWED,
            f"the capture reported a near-end voice during the silent step and {confirmed} barge-in(s) "
            "were confirmed in that window, so the confirmation cannot be attributed to Jarvis's own "
            "echo rather than to somebody in the room")


def require_measurable_interrupt(context: RunContext, session: GuidedSession, confirmed: int, *,
                                 heard: bool) -> None:
    """Nothing confirmed, or nobody there to confirm: say so, never pass quietly.

    A guided run exists to make the positive claim — a real voice gets through the echo
    gate. A run where it did not, reported as `passed` because no blocking assertion
    happened to cover it, is the exact failure the guided profile was built to prevent.

    `heard` is the silent-window evidence that a person was in the room at all. Without it
    a confirmation cannot be a human interrupt whatever the counter says, so the claim was
    not measured: an empty room used to reach here with `confirmed == 1` and report the one
    claim only a person can make.

    Whether "the human was there and nothing was confirmed" is a VERDICT or a measurement
    failure is a property of the DECLARATION, not of this runner — the same rule
    `expectation_metrics` applies to scenario expectations. A diagnostic that declares a
    BLOCKING assertion on `barge_in.true_confirmed_count` has said "zero is a product
    failure", and the metric is reported so the supervisor can fail the run on it. A
    diagnostic that has not said that cannot express the verdict, so the honest outcome is
    `inconclusive`.
    """
    record = session.record_of(PROMPT_INTERRUPT)
    if record is None or not record.usable:
        return
    if not heard:
        raise GuidedPromptUnavailable(
            GUIDED_CLAIM_UNMEASURED,
            "the human acknowledged the interrupt step but no voice was measured in the room with "
            "nothing playing, so nothing confirmed in that window can be attributed to a person "
            "rather than to Jarvis's own echo")
    if confirmed > 0:
        return
    if _blocks_on(context, TRUE_CONFIRMED_METRIC):
        context.log(f"no barge-in was confirmed while the human interrupted; "
                    f"{TRUE_CONFIRMED_METRIC} is reported as 0 and the declaration decides")
        return
    raise GuidedPromptUnavailable(
        GUIDED_CLAIM_UNMEASURED,
        "the human acknowledged the interrupt step and the stack confirmed no barge-in, so the one "
        f"claim a guided run exists to make was not measured; declare a blocking assertion on "
        f"{TRUE_CONFIRMED_METRIC} to read this as a product failure instead")


def _blocks_on(context: RunContext, metric: str) -> bool:
    """Does this diagnostic declare a BLOCKING assertion on `metric`?"""
    return any(item.metric == metric and item.blocking for item in context.diagnostic.assertions)


def _phase_deadline(context: RunContext, duration_ms: int) -> float:
    """A prompt deadline that fits inside what is left of the run's own budget."""
    remaining = context.remaining_s
    wanted = max(DEFAULT_PROMPT_DEADLINE_S, duration_ms / 1000 + DEFAULT_PROMPT_DEADLINE_S)
    return max(1.0, min(wanted, MAX_PROMPT_DEADLINE_S, remaining if remaining > 1.0 else wanted))


def build_prompter(context: RunContext, injected: GuidedPrompter | None = None) -> GuidedPrompter:
    """The presenter a guided worker talks to the human through.

    By default the file channel in the run scratch, which is what a CLI (Slice 10) or the
    Control Center (Slice 11) watches. The registry builds every runner with no
    arguments, so the default is what a real run gets; a test constructs the runner with
    its own `prompter=` and needs no terminal.
    """
    if injected is not None:
        return injected
    from jarvis.testlab.hardware.channel import FilePrompter

    return FilePrompter(context.runtime_dir.parent)


# ------------------------------------------- testlab.scenario.hardware_auto/guided

@dataclass
class HardwareExecutor(VirtualExecutor):
    """`VirtualExecutor` on a real device: `audio.inject` plays, and time actually passes.

    Two overrides, both forced by the profile and neither of them a handler replacement:

    - `audio.inject` is ADDED (the shared table has none), and on a hardware profile it
      means "play this fixture through the speaker". On the `audio` profile the same
      primitive means "push this into the capture path", because that profile has no
      speaker. Same name, same argument schema, the one meaning each profile can give it.
    - `_advance_to` really waits. On `virtual` and `audio`, `at_ms` is simulated time; on
      a hardware profile there is a room, a driver and possibly a human, and pretending
      3 s passed when it did not would measure nothing.
    """

    clip_root: AudioFixtureRoot | None = None
    played_ms: int = 0

    def handler_for(self, primitive: str):
        if primitive == "audio.inject":
            return HardwareExecutor._handle_audio_inject
        return super().handler_for(primitive)

    async def _advance_to(self, at_ms: int) -> None:
        delta_ms = max(0, at_ms - self.at_ms)
        if delta_ms:
            await self.context.sleep(min(delta_ms / 1000, max(0.0, self.context.remaining_s)))
        await super()._advance_to(at_ms)

    async def _handle_audio_inject(self, index: int, step: Any) -> None:
        """Play a declared fixture through the REAL output device."""
        del index
        args = step.args
        pcm = load_clip(args.get("audio_ref"), gain_db=float(args.get("gain_db") or 0.0), root=self.clip_root)
        for offset in range(0, len(pcm), OUTPUT_BLOCK_BYTES):
            self.context.check_cancelled()
            await self.stack.session.play_audio(pcm=wrap_slice(pcm, offset, OUTPUT_BLOCK_BYTES))
        self.played_ms = int(self.stack.audio.played_output_ms)
        self.context.log(f"audio.inject {args.get('audio_ref')}: {len(pcm)} bytes played through the output "
                         f"device, played_ms={self.played_ms}")


@dataclass
class GuidedExecutor(HardwareExecutor):
    """`HardwareExecutor` plus the four `human.*` primitives. Guided-only, by declaration."""

    session: GuidedSession | None = None

    def handler_for(self, primitive: str):
        handler = _HUMAN_HANDLERS.get(primitive)
        if handler is not None:
            return handler
        return super().handler_for(primitive)

    async def _ask(self, action: GuidedAction, step: Any) -> None:
        """One `human.*` step: `text` is the phrase for a spoken action, the wording otherwise.

        `prompt_id` is the scenario's, unchanged, because it is how the stored evidence,
        the CLI and the UI all name the same step.
        """
        session = self.session
        if session is None:  # pragma: no cover - the runner always supplies one
            raise _failed("a human.* step needs a guided session; this executor was built without one")
        args = step.args
        spoken = action in (GuidedAction.SAY_PHRASE, GuidedAction.INTERRUPT)
        text = args.get("text")
        deadline_ms = args.get("deadline_ms")
        await session.ask(prompt_for(
            action, str(args["prompt_id"]),
            text=None if spoken or not text else str(text),
            phrase=str(text) if spoken else None,
            deadline_s=(deadline_ms / 1000) if isinstance(deadline_ms, int) and deadline_ms
            else DEFAULT_PROMPT_DEADLINE_S))

    async def _handle_human_silence(self, index: int, step: Any) -> None:
        del index
        await self._ask(GuidedAction.REMAIN_SILENT, step)

    async def _handle_human_speak(self, index: int, step: Any) -> None:
        del index
        await self._ask(GuidedAction.SAY_PHRASE, step)

    async def _handle_human_interrupt(self, index: int, step: Any) -> None:
        del index
        await self._ask(GuidedAction.INTERRUPT, step)

    async def _handle_human_acknowledge(self, index: int, step: Any) -> None:
        del index
        await self._ask(GuidedAction.ACKNOWLEDGE, step)


#: `human.*` is the guided vocabulary, and only `GuidedExecutor` performs it. Kept as a
#: module constant for the same reason the shared table is: one reviewed place.
_HUMAN_HANDLERS = {
    "human.silence": GuidedExecutor._handle_human_silence,
    "human.speak": GuidedExecutor._handle_human_speak,
    "human.interrupt": GuidedExecutor._handle_human_interrupt,
    "human.acknowledge": GuidedExecutor._handle_human_acknowledge,
}


#: What the generic hardware runner can report, whatever the scenario is: the four
#: scenario properties, plus the two facts only a device profile can state.
HARDWARE_SCENARIO_METRICS = ("scenario.steps_performed", "scenario.checkpoints_reached",
                             "scenario.expectations_declared", "scenario.expectations_failed_count",
                             "audio.played_ms", "audio.captured_ms")
#: The guided runner adds what the HUMAN did, which is the only thing a guided run has
#: that an auto run does not.
GUIDED_SCENARIO_METRICS = HARDWARE_SCENARIO_METRICS + ("guided.prompt_count", "guided.late_prompt_count",
                                                       "guided.unfollowed_count")


@dataclass(frozen=True, slots=True)
class HardwareScenarioRunner:
    """Generic scenario runner of `hardware:auto`: the real device stack, no human."""

    profile_metrics: tuple[str, ...] = HARDWARE_SCENARIO_METRICS

    async def run(self, context: RunContext) -> RunOutcome:
        scenario = _require_scenario(context, self.profile_metrics)
        async with hardware_voice_stack(context) as (stack, journal, _core, build, selection):
            await open_device_session(context, stack)
            audio = mounted_device_audio(stack)
            executor = HardwareExecutor(stack=stack, context=context, journal=journal)
            await executor.run(scenario)
            metrics = _scenario_metrics(context, executor, scenario, audio)
            metadata = hardware_metadata(context, build, selection, audio)
            context.log(f"hardware scenario: steps={len(scenario.steps)} played_ms={metrics['audio.played_ms']} "
                        f"captured_ms={metrics['audio.captured_ms']} unmet={executor.expectations_failed}")
            await close_session(context, stack)
        write_metadata(context, metadata)
        await commit_trace(context, journal)
        declared = {spec.name for spec in context.diagnostic.metrics}
        return RunOutcome(metrics={name: value for name, value in metrics.items() if name in declared})


@dataclass(frozen=True, slots=True)
class GuidedScenarioRunner:
    """Generic scenario runner of `hardware:guided`: the real device stack, with a human actor."""

    profile_metrics: tuple[str, ...] = GUIDED_SCENARIO_METRICS
    #: Injected by a test; `None` means the file channel a CLI or the UI drives.
    prompter: GuidedPrompter | None = None

    async def run(self, context: RunContext) -> RunOutcome:
        scenario = _require_scenario(context, self.profile_metrics)
        async with hardware_voice_stack(context) as (stack, journal, _core, build, selection):
            session = GuidedSession(context=context, prompter=build_prompter(context, self.prompter))
            try:
                await open_device_session(context, stack)
                audio = mounted_device_audio(stack)
                executor = GuidedExecutor(stack=stack, context=context, journal=journal, session=session)
                await executor.run(scenario)
            finally:
                session.commit()
            metrics = _scenario_metrics(context, executor, scenario, audio)
            metrics.update({"guided.prompt_count": session.prompt_count,
                            "guided.late_prompt_count": session.late_count,
                            "guided.unfollowed_count": len(session.unfollowed)})
            metadata = hardware_metadata(context, build, selection, audio)
            context.log(f"guided scenario: steps={len(scenario.steps)} prompts={session.prompt_count} "
                        f"late={session.late_count} unfollowed={list(session.unfollowed)}")
            await close_session(context, stack)
        write_metadata(context, metadata, {"guided": True, "prompt_count": session.prompt_count})
        await commit_trace(context, journal)
        declared = {spec.name for spec in context.diagnostic.metrics}
        return RunOutcome(metrics={name: value for name, value in metrics.items() if name in declared})


def declared_metrics(context: RunContext, measured: Mapping[str, Any]) -> RunOutcome:
    """Report what the diagnostic declared, and only that.

    A seed runner measures more than one version of its declaration asks for — Slice 09
    added `barge_in.first_candidate_offset_ms`, which the published v2 does not declare.
    Reporting an undeclared metric makes `check_run_against_spec` refuse the completed
    run (`result_contradicts_spec`, read as `crashed`), so the runner offers and the
    declaration selects, exactly as the generic scenario runners already do. A value of
    `None` is simply not measured.
    """
    declared = {spec.name for spec in context.diagnostic.metrics}
    return RunOutcome(metrics={name: value for name, value in measured.items()
                               if name in declared and value is not None})


def _require_scenario(context: RunContext, measurable: tuple[str, ...]):
    scenario = context.scenario
    if scenario is None:
        raise _failed("the generic hardware runner needs a scenario; this run carried none")
    declared = {spec.name for spec in context.diagnostic.metrics}
    unmeasurable = sorted(declared - set(measurable))
    if unmeasurable:
        raise _failed(f"the generic hardware runner cannot measure {unmeasurable}; declare a specialized "
                      "implementation for this diagnostic")
    return scenario


def _scenario_metrics(context: RunContext, executor: HardwareExecutor, scenario,
                      audio: DeviceAudio) -> dict[str, MetricValue]:
    metrics: dict[str, MetricValue] = {
        "scenario.steps_performed": len(scenario.steps),
        "scenario.checkpoints_reached": len(executor.checkpoints),
        "audio.played_ms": max(executor.played_ms, int(audio.played_output_ms)),
        "audio.captured_ms": int(audio.captured_bytes) * 1000 // (2 * VOICE_SAMPLE_RATE),
    }
    # Evaluated before the expectation counts are added, exactly as the virtual and
    # audio runners do: an `expect.metric` must read what the scenario produced.
    executor.check_measured_expectations(metrics, {})
    metrics.update(expectation_metrics(context, executor))
    return metrics
