"""The `audio` profile runners: the real local audio chain, a fixture instead of a microphone.

Binding contract: `docs/testlab.md` ("Audio profile"). Two registrations:

- `voice.self_echo.audio` — the seed self-echo diagnostic run against the REAL
  duplex capture and the REAL echo canceller, with Jarvis's own output injected
  back as the microphone signal. This is the acoustic claim the `virtual` profile
  explicitly cannot make (docs/testlab.md, "What the virtual profile cannot prove").
- `testlab.scenario.audio` — the generic scenario runner for the primitives the
  `audio` profile declares (`audio.inject`, `time.wait`, `control.*`,
  `parameter.override`, `expect.*`).

No provider and no device: the Realtime session is the deterministic double and
no PortAudio stream is opened, which is what lets this profile run in a normal
pytest chunk. A dead end that is ACOUSTIC (no fixture, a capture that refused
every block, an output that never became the far end) raises
`MeasurementUnavailable`, so the run reads `inconclusive` and not `crashed`
(Slice 07 carry-over).
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from typing import Any

from jarvis.domain.v2 import SpeechKind
from jarvis.testlab.audio.chain import (
    INPUT_BLOCK_BYTES,
    room_response,
    ChainMetadata,
    InjectedSourceAudio,
    InjectionReport,
    build_capture,
    chain_metadata,
    split_blocks,
)
from jarvis.testlab.audio.fixtures import (
    VOICE_SAMPLE_RATE,
    AudioFixtureError,
    AudioFixtureRoot,
    apply_gain_db,
    frame_peak_dbfs,
    wav_bytes,
)
from jarvis.testlab.diagnostics import MetricValue
from jarvis.testlab.runners import MeasurementUnavailable, RunContext, RunOutcome
from jarvis.testlab.runs import ArtifactKind
from jarvis.testlab.virtual.executor import VirtualExecutor
from jarvis.testlab.virtual.harness import CHUNK_MS, VoiceStack
from jarvis.testlab.virtual.runners import (
    close_session,
    commit_trace,
    expectation_metrics,
    open_session,
    submit_user_turn,
    wait_condition,
    BARGE_IN_CONFIRMED_KINDS,
    BARGE_IN_DECISION_KINDS,
    BARGE_IN_REFUSED_KINDS,
    SPEECH_TERMINAL_KINDS,
    virtual_voice_stack,
)

AUDIO_RUN_FAILED = "testlab_audio_run_failed"
#: One 100 ms output block of the production writer, as PCM16 at 24 kHz.
OUTPUT_BLOCK_BYTES = VOICE_SAMPLE_RATE // 10 * 2
#: Acoustic coupling of the simulated room: how much quieter the echo comes back. A
#: parameter of the STIMULUS, not of the product, DECLARED by the diagnostic
#: (`echo.coupling_db`) so it can be swept and overridden like any other. This constant
#: is only the fallback for a declaration that predates it.
DEFAULT_ECHO_GAIN_DB = -12.0
#: The first output block a barge-in candidate may be raised over: the canceller's own
#: 400 ms pre-roll, the same rule the hardware runners apply.
FIRST_CANDIDATE_BLOCK = 400 // CHUNK_MS
ECHO_COUPLING_PARAMETER = "echo.coupling_db"
#: The fixture every audio seed plays when a scenario names none.
DEFAULT_CLIP_REF = "reference-tone-1s.wav"

METADATA_ARTIFACT = "audio_profile.json"
METADATA_SCHEMA = "jarvis.testlab.profile_metadata"
METADATA_SCHEMA_VERSION = 1
CLIP_ARTIFACT = "capture.wav"


class AudioRunError(MeasurementUnavailable):
    """The real audio chain could not be brought to a state this diagnostic can measure.

    `MeasurementUnavailable`, so the worker records `measurement_unavailable` and the
    run reads `inconclusive`: no device, no usable fixture, a capture that never
    became the far end, an injected stimulus the stack never answered. Every one of
    them is a statement about the situation, not a defect of the lab.
    """


def _failed(detail: str) -> AudioRunError:
    return AudioRunError(AUDIO_RUN_FAILED, detail)


# --------------------------------------------------------------------- socle

@asynccontextmanager
async def audio_voice_stack(context: RunContext, *, echo_cancellation: bool = True):
    """Mount the voice path with the PRODUCTION duplex capture and an injected source."""
    build = build_capture(capture_rate=VOICE_SAMPLE_RATE, render_rate=VOICE_SAMPLE_RATE,
                          echo_cancellation=echo_cancellation)
    if build.aec_error is not None:
        context.log(f"echo canceller unavailable: {build.aec_error}")
    context.log(f"audio chain: aec_engaged={build.aec_engaged} reason={build.aec_unavailable_reason} "
                f"rate={build.capture_rate}")
    async with virtual_voice_stack(context, capture_factory=lambda: build.capture,
                                   audio_class=InjectedSourceAudio) as (stack, journal, core_journal):
        yield stack, journal, core_journal, build


class AudioInjector:
    """Performs `audio.inject`: a fixture, resolved inside the declared root, becomes microphone blocks."""

    __slots__ = ("_root", "_stack", "_reports")

    def __init__(self, stack: VoiceStack, *, root: AudioFixtureRoot | None = None) -> None:
        self._root = root if root is not None else AudioFixtureRoot()
        self._stack = stack
        self._reports: list[InjectionReport] = []

    @property
    def reports(self) -> tuple[InjectionReport, ...]:
        return tuple(self._reports)

    @property
    def injected_ms(self) -> int:
        """Audio that went through the production capture path, from the blocks actually pushed."""
        return self.audio.injected_bytes * 1000 // (2 * VOICE_SAMPLE_RATE)

    @property
    def audio(self) -> InjectedSourceAudio:
        device = self._stack.audio
        if not isinstance(device, InjectedSourceAudio):
            raise _failed("the audio profile did not mount its injected audio source")
        return device

    def load(self, ref: object, *, gain_db: float = 0.0) -> bytes:
        """Fixture PCM at the voice rate, with `gain_db` applied. Refuses anything outside the root."""
        try:
            clip = self._root.load(ref)
        except AudioFixtureError as exc:
            # Re-raised as a MEASUREMENT failure, keeping the real cause: a scenario
            # naming a fixture that is not there is an authoring dead end, never a crash.
            raise AudioRunError(exc.code, exc.detail) from exc
        return apply_gain_db(clip.pcm, gain_db)

    def inject(self, ref: object, *, gain_db: float = 0.0) -> InjectionReport:
        """Push a whole fixture through the production capture path, block by block."""
        try:
            clip = self._root.load(ref)
        except AudioFixtureError as exc:
            raise AudioRunError(exc.code, exc.detail) from exc
        pcm = apply_gain_db(clip.pcm, gain_db)
        signals = self.inject_pcm(pcm)
        report = InjectionReport(ref=str(ref), blocks=len(split_blocks(pcm)), bytes_injected=len(pcm),
                                 duration_ms=clip.duration_ms, gain_db=float(gain_db),
                                 source_sample_rate=clip.source_sample_rate, signals=signals)
        self._reports.append(report)
        return report

    def inject_pcm(self, pcm: bytes) -> tuple[str, ...]:
        """Raw PCM as production-sized microphone blocks; returns every signal the capture raised."""
        audio = self.audio
        signals: list[str] = []
        for block in split_blocks(pcm, INPUT_BLOCK_BYTES):
            signals.extend(audio.inject_block(block))
        return tuple(signals)


def write_metadata(context: RunContext, metadata: ChainMetadata, extra: Mapping[str, Any] | None = None) -> None:
    """Commit what the profile exercised as a bounded JSON report artifact.

    A `report`, not a metric: device ids, rates and "was the canceller engaged" are
    facts about the RUN, not measurements of the product, and a manifest that had to
    declare them as metrics would have to be versioned every time a probe is added.
    """
    document: dict[str, Any] = {"schema": METADATA_SCHEMA, "schema_version": METADATA_SCHEMA_VERSION,
                                "run_id": context.run_id, **metadata.to_dict()}
    if extra:
        document.update(extra)
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    context.put_artifact(METADATA_ARTIFACT, kind=ArtifactKind.REPORT, media_type="application/json", data=payload)


def store_clip(context: RunContext, pcm: bytes, *, path: str = CLIP_ARTIFACT) -> bool:
    """Store an audio clip IF the run was allowed audio artifacts. Returns whether it was.

    Never by default: `ArtifactWriteLimits.allow_audio` is off unless the caller asked
    for it and the profile can produce audio, and the store refuses the write otherwise
    (`testlab_store_artifact_refused`). This helper turns that refusal into a logged
    fact instead of a failed run, because losing the optional evidence must not lose
    the measurement.
    """
    from jarvis.testlab.store import TestLabStoreError

    try:
        context.put_artifact(path, kind=ArtifactKind.AUDIO_CLIP, media_type="audio/wav",
                             data=wav_bytes(pcm, VOICE_SAMPLE_RATE))
    except TestLabStoreError as exc:
        # Captured with its real code: audio artifacts are opt-in and bounded, and a
        # store that refuses one is behaving exactly as designed.
        context.log(f"audio clip not stored ({exc.code}): {exc.detail}")
        return False
    return True


def _terminal_of(journal, speech_id: str) -> str | None:
    for line in journal.timeline:
        if line.kind in SPEECH_TERMINAL_KINDS and line.data.get("speech_id") == speech_id:
            return line.kind
    return None


# ------------------------------------------------------- voice.self_echo.audio

@dataclass(frozen=True, slots=True)
class SelfEchoAudioRunner:
    """`voice.self_echo` on the real audio chain: real reference, real canceller, real gate.

    The virtual runner proves the DECISION logic with a guard double that declares
    the acoustic state. This one makes the state real: the production writer pushes
    each played block as the canceller's far-end reference, the same block comes back
    into `CaptureProcessor.process` attenuated by a declared coupling, and the
    near-end detector — not a double — decides whether the provider hears the
    microphone. `_barge_in_allowed()` then reads a gate that was computed from
    samples.

    What it still cannot prove: there is no room, no speaker and no microphone, so
    the coupling is the one the parameter states. A real room is `hardware:auto`.
    """

    async def run(self, context: RunContext) -> RunOutcome:
        duration_ms = int(context.parameters["output.duration_ms"])
        echoes = int(context.parameters["echo.candidate_count"])
        # Through the DECLARED parameter path: `resolve_parameters` has already merged
        # the manifest default with any supplied or swept value, so a declaration that
        # carries `echo.coupling_db` always supplies it. The fallback is for a
        # declaration written before it existed, never a way to bypass the declaration.
        echo_gain_db = float(context.parameters.get(ECHO_COUPLING_PARAMETER, DEFAULT_ECHO_GAIN_DB))
        async with audio_voice_stack(context) as (stack, journal, _core, build):
            injector = AudioInjector(stack)
            clip = injector.load(DEFAULT_CLIP_REF)
            echo = apply_gain_db(clip, echo_gain_db)
            await open_session(context, stack)
            handle = await submit_user_turn(context, stack, "jarvis raconte moi la journee en detail")
            await handle.start_work("self-echo", label="self echo")
            request = await handle.say("voici le recit complet de la journee que jarvis prononce",
                                       kind=SpeechKind.RESULT, work_id="self-echo")
            await wait_condition(context, lambda: len(stack.session.spoken) >= 1,
                                 "the scheduler dispatching the speech to the surface")
            injected = await self._play_with_echo(context, stack, journal, injector, request.id,
                                                  duration_ms, echoes, clip, echo)
            if _terminal_of(journal, request.id) is None:
                await stack.session.finish_output(status="completed", transcript=request.text)
            await handle.complete_work("self-echo", summary=request.text)
            handle.finish(public_summary=request.text)
            await wait_condition(context, lambda: bool(_terminal_of(journal, request.id)),
                                 "a terminal status for the speech")
            played_ms = int(stack.audio.played_output_ms)
            confirmed = journal.counts(*BARGE_IN_CONFIRMED_KINDS)
            refused = journal.counts(*BARGE_IN_REFUSED_KINDS)
            completed = _terminal_of(journal, request.id) == "voice.speech.completed"
            far_end_seen = build.capture.far_recent or injector.audio.injected_blocks > 0
            metadata = chain_metadata(context.profile.value, build, injector.audio)
            metadata.injected = [report.to_dict() for report in injector.reports]
            context.log(f"self echo (audio): aec={build.aec_engaged} echoes={injected} confirmed={confirmed} "
                        f"refused={refused} played_ms={played_ms} peak_echo_dbfs={frame_peak_dbfs(echo):.1f}")
            await close_session(context, stack)
        if injected == 0 and echoes:
            raise _failed("no echo candidate could be injected, so nothing about barge-in was measured")
        if not far_end_seen:
            raise _failed("Jarvis never became the far end of the capture, so the echo guard was never exercised")
        write_metadata(context, metadata, {"echo_coupling_db": echo_gain_db,
                                           "echo_peak_dbfs": round(frame_peak_dbfs(echo), 1),
                                           "reference_peak_dbfs": round(frame_peak_dbfs(clip), 1)})
        await commit_trace(context, journal)
        return RunOutcome(metrics={
            "barge_in.false_confirmed_count": confirmed,
            "barge_in.rejected_count": refused,
            "output.completed": completed,
            "output.played_ms": played_ms,
        })

    async def _play_with_echo(self, context: RunContext, stack: VoiceStack, journal, injector: AudioInjector,
                              speech_id: str, duration_ms: int, echoes: int, clip: bytes, echo: bytes) -> int:
        """Play the fixture 100 ms at a time; the room returns it, shaped and one block late.

        Reference and capture advance together, one output block for one block of echo:
        letting the reference run ahead would leave the canceller aligning frames against
        audio that had not been played yet, which is a property of this harness and not of
        the product.

        The echo is NOT a copy of what was played (`room_response`, `ECHO_DELAY_BLOCKS`).
        It used to be, and that was a defect of the diagnostic: measured at this seed's own
        declared default of 8 000 ms, an exact delay-free copy let the canceller converge
        until the near-end detector expected a residual no real room produces, the gate
        opened at ~3.4 s, and the run FAILED a healthy product. The first candidate also
        waits for the canceller's 400 ms pre-roll, for the same reason the hardware runner
        does: before that, what a candidate measures is convergence, not the gate.
        """
        blocks = max(1, duration_ms // CHUNK_MS)
        every = max(1, blocks // echoes) if echoes else 0
        injected = 0
        delayed: bytes | None = None
        for block in range(blocks):
            context.check_cancelled()
            if _terminal_of(journal, speech_id) is not None:
                break
            offset = (block * OUTPUT_BLOCK_BYTES) % max(OUTPUT_BLOCK_BYTES, len(clip))
            await stack.session.play_audio(pcm=wrap_slice(clip, offset, OUTPUT_BLOCK_BYTES))
            audible = (block + 1) * CHUNK_MS
            await wait_condition(context,
                                 lambda: (stack.audio.played_output_ms >= audible
                                          or _terminal_of(journal, speech_id) is not None),
                                 f"{audible} ms of Jarvis output reaching the device")
            # The room returns the PREVIOUS block, shaped. One block of delay, drift and
            # noise, and none of the three is decoration: see `room_response`.
            shaped = room_response(wrap_slice(echo, offset, OUTPUT_BLOCK_BYTES), seed=block)
            if delayed is not None:
                injector.inject_pcm(delayed)
            delayed = shaped
            if (echoes and injected < echoes and block >= FIRST_CANDIDATE_BLOCK
                    and (block - FIRST_CANDIDATE_BLOCK) % every == 0):
                await self._await_decision(context, stack, journal)
                injected += 1
        if delayed is not None:
            injector.inject_pcm(delayed)
        while injected < echoes and _terminal_of(journal, speech_id) is None:
            context.check_cancelled()
            injector.inject_pcm(room_response(wrap_slice(echo, 0, OUTPUT_BLOCK_BYTES), seed=blocks))
            await self._await_decision(context, stack, journal)
            injected += 1
        return injected

    async def _await_decision(self, context: RunContext, stack: VoiceStack, journal) -> None:
        """Raise one provider VAD onset and require the stack to DECIDE on it.

        Same anti-vacuity rule as the virtual seed (Slice 06 QA): a stack that never
        answers provider VAD produces neither a confirmation nor a rejection, and
        would pass every assertion while being deaf. Here the decision is worth more,
        because the gate it consults was computed by the real near-end detector.
        """
        before = journal.counts(*BARGE_IN_DECISION_KINDS)
        await self.inject_echo_candidate(context, stack)
        await wait_condition(
            context, lambda: journal.counts(*BARGE_IN_DECISION_KINDS) > before,
            "a barge-in decision for the injected provider onset over real captured echo")

    async def inject_echo_candidate(self, context: RunContext, stack: VoiceStack) -> None:
        """One provider VAD onset. Overridable seam: a test raises a REAL near-end voice here."""
        del context
        await stack.session.interrupt()


def wrap_slice(pcm: bytes, offset: int, size: int) -> bytes:
    """`size` bytes from `offset`, wrapping, so a short fixture still fills a long output.

    Public because the `hardware:*` runners (Slice 09) play the same fixtures through a
    real speaker and need the same wrap.
    """
    if not pcm:
        return bytes(size)
    out = bytearray()
    position = offset % len(pcm)
    while len(out) < size:
        out += pcm[position:position + size - len(out)]
        position = 0
    return bytes(out[:size])


# ------------------------------------------------------ testlab.scenario.audio

@dataclass(frozen=True, slots=True)
class AudioScenarioRunner:
    """Generic scenario runner of the `audio` profile.

    It is the virtual executor with one primitive added — `audio.inject`, which the
    `virtual` profile is the only one not to support — because everything else the
    `audio` profile declares (`time.wait`, `control.*`, `parameter.override`,
    `expect.*`) is profile-independent and already implemented. Widening the replay
    primitives (`provider.*`, `scheduler.*`, `owner.*`) to this profile is a
    deliberate non-goal of Slice 08: they drive doubles, and which of them remain
    doubles on a real chain is a decision for the manifest that needs them.
    """

    async def run(self, context: RunContext) -> RunOutcome:
        scenario = context.scenario
        if scenario is None:
            raise _failed("the generic audio runner needs a scenario; this run carried none")
        declared = {spec.name for spec in context.diagnostic.metrics}
        unmeasurable = sorted(declared - set(AUDIO_SCENARIO_METRICS))
        if unmeasurable:
            raise _failed(f"the generic audio runner cannot measure {unmeasurable}; declare a specialized "
                          "implementation for this diagnostic")
        async with audio_voice_stack(context) as (stack, journal, _core, build):
            injector = AudioInjector(stack)
            await open_session(context, stack)
            executor = AudioExecutor(stack=stack, context=context, journal=journal, injector=injector)
            await executor.run(scenario)
            metrics: dict[str, MetricValue] = {
                "scenario.steps_performed": len(scenario.steps),
                "scenario.checkpoints_reached": len(executor.checkpoints),
                "audio.injected_block_count": injector.audio.injected_blocks,
                "audio.injected_ms": injector.injected_ms,
            }
            # Evaluated before the expectation counts are added, exactly as the virtual
            # runner does: an `expect.metric` must read what the scenario produced.
            executor.check_measured_expectations(metrics, {})
            metrics.update(expectation_metrics(context, executor))
            metadata = chain_metadata(context.profile.value, build, injector.audio)
            metadata.injected = [report.to_dict() for report in injector.reports]
            context.log(f"audio scenario: steps={len(scenario.steps)} blocks={injector.audio.injected_blocks} "
                        f"aec={build.aec_engaged} unmet={executor.expectations_failed}")
            await close_session(context, stack)
        write_metadata(context, metadata)
        await commit_trace(context, journal)
        return RunOutcome(metrics={name: value for name, value in metrics.items() if name in declared})


#: What the generic audio runner can report, whatever the scenario is. The four
#: scenario properties of `testlab.scenario.virtual`, plus the two facts only this
#: profile can state: how much audio actually went through the capture path.
AUDIO_SCENARIO_METRICS = ("scenario.steps_performed", "scenario.checkpoints_reached",
                          "scenario.expectations_declared", "scenario.expectations_failed_count",
                          "audio.injected_block_count", "audio.injected_ms")


@dataclass
class AudioExecutor(VirtualExecutor):
    """`VirtualExecutor` plus `audio.inject`, performed on the real capture path."""

    injector: AudioInjector | None = None

    def handler_for(self, primitive: str):
        if primitive == "audio.inject":
            return AudioExecutor._handle_audio_inject
        return super().handler_for(primitive)

    def _handle_audio_inject(self, index: int, step: Any) -> None:
        """Play a declared fixture into the production capture path."""
        del index
        injector = self.injector
        if injector is None:  # pragma: no cover - the runner always supplies one
            raise _failed("audio.inject needs an injector; this executor was built without one")
        args = step.args
        report = injector.inject(args.get("audio_ref"), gain_db=float(args.get("gain_db") or 0.0))
        self.context.log(f"audio.inject {report.ref}: {report.blocks} blocks, {report.duration_ms} ms, "
                         f"gain {report.gain_db} dB")
