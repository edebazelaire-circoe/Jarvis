"""The `virtual` profile runners: the four seed diagnostics and the generic scenario runner.

Binding contract: `docs/testlab.md` ("Virtual profile"). Each runner mounts the
production voice path with the three controlled doubles of the harness (Realtime
session, audio device, brain backend), drives one scripted or scenario-authored
situation, and returns exactly the metrics its manifest declares — no more (the
supervisor refuses an undeclared metric) and no fewer (a missing one makes its
assertion `missing`, which is inconclusive, never `passed`).

A runner measures; the supervisor judges. Nothing here computes a verdict, writes a
run record, or reads anything outside the per-run scratch.

Determinism, cancellation and deadlines:

- no `sleep` is ever used as synchronization. Every wait is a condition with a budget
  taken from `RunContext.remaining_s`; the only real waits are stimuli a metric
  measures (the scripted brain's thinking time), and they go through
  `RunContext.sleep`, which returns on a cancel.
- `RunContext.check_cancelled()` runs between steps and inside every wait, so a
  cancelled run ends cooperatively long before the supervisor's forced kill, and a
  passed deadline ends it as `timed_out`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

from jarvis.domain.v2 import SpeechKind, SpeechRequest
from jarvis.testlab.diagnostics import MetricValue
from jarvis.testlab.runners import MeasurementUnavailable, RunContext, RunOutcome
from jarvis.testlab.runs import ArtifactKind
from jarvis.testlab.virtual.echo_guard import VirtualEchoGuard
from jarvis.testlab.virtual.executor import POLL_S, STEP_TIMEOUT_S, VirtualExecutor, VirtualStepError
from jarvis.testlab.virtual.harness import CHUNK_MS, BrainTurnHandle, VoiceStack, voice_stack
from jarvis.testlab.virtual.journal import TraceRecordingJournal, TraceLine
from jarvis.testlab.virtual.patching import PatchStack

VIRTUAL_RUN_FAILED = "testlab_virtual_run_failed"
TRACE_ARTIFACT = "trace.jsonl"
TRACE_MEDIA_TYPE = "application/x-ndjson"
#: The voice returns to background after this long without useful activity. A run is
#: bounded by the supervisor's deadline, so the session must never expire under it.
SESSION_IDLE_TIMEOUT_S = 3600.0
#: Barge-in decisions, as the DiagnosticBundle maps them (docs/testlab.md, "Evidence sources").
BARGE_IN_CONFIRMED_KINDS = ("voice.barge_in", "voice.barge_in.owner_confirmed")
BARGE_IN_REFUSED_KINDS = ("voice.barge_in_rejected", "voice.barge_in_ignored")
#: Every line that is the stack ANSWERING a barge-in candidate, either way. An injected
#: onset that produces none of them means the stack did not decide, not that it decided well.
BARGE_IN_DECISION_KINDS = BARGE_IN_CONFIRMED_KINDS + BARGE_IN_REFUSED_KINDS
SPEECH_TERMINAL_KINDS = ("voice.speech.completed", "voice.speech.interrupted", "voice.speech.superseded",
                         "voice.speech.expired", "voice.speech.speak_failed")


class VirtualRunError(MeasurementUnavailable):
    """The virtual stack could not reach a state the diagnostic needs to measure anything.

    A `MeasurementUnavailable` since Slice 07: the worker records
    `measurement_unavailable` and the run reads `inconclusive` — "could not
    measure", told apart from the `assertions_inconclusive` of a metric that was
    simply never reported, and from the `runner_failed` of an unforeseen defect.
    """


def _failed(detail: str) -> VirtualRunError:
    return VirtualRunError(VIRTUAL_RUN_FAILED, detail)


# --------------------------------------------------------------------- socle

@asynccontextmanager
async def virtual_voice_stack(context: RunContext, *, capture_factory=None, audio_class=None,
                              realtime_factory=None):
    """Mount the production voice path with the harness doubles, inside the run scratch.

    The three keyword seams are what the `audio` and `live` profiles (Slice 08) change,
    and nothing else: a real duplex capture instead of `VirtualEchoGuard`, an audio class
    that injects a controlled stimulus into the production capture path, and a factory
    that opens a REAL provider session. A `virtual` run passes none of them.

    The journals write `<runtime_dir>/trace.jsonl` with the live runtime's own kinds and
    ids, so a `DiagnosticBundle` captured over a run reads the evidence it reads from a
    real session (Slice 03 carried this to Slice 06). `session_id` is derived from the run
    id, which is what makes the run's lines segment into one voice session.
    """
    patches = PatchStack()
    journal = TraceRecordingJournal(context.runtime_dir)
    core_journal = TraceRecordingJournal(context.runtime_dir)
    capture = capture_factory if capture_factory is not None else (lambda: VirtualEchoGuard())
    context.log(f"voice stack: runtime={context.runtime_dir} data={context.data_root} profile={context.profile.value}")
    try:
        async with voice_stack(context.data_root, patches, active_timeout_s=SESSION_IDLE_TIMEOUT_S,
                               journal=journal, core_journal=core_journal, capture_factory=capture,
                               audio_class=audio_class, realtime_factory=realtime_factory,
                               session_id_factory=lambda index: f"{context.run_id}-s{index}") as stack:
            yield stack, journal, core_journal
    finally:
        patches.undo()


async def wait_condition(context: RunContext, predicate: Callable[[], bool], what: str) -> None:
    """Wait for an observable condition, bounded by the RUN's remaining time.

    Never a fixed wall clock: a loaded host makes a run slower, not wrong, and only the
    supervisor's deadline ends it (Issues/voice-harness-wall-clock-flake-under-load.md).
    """
    loop = asyncio.get_running_loop()
    budget = max(0.0, min(STEP_TIMEOUT_S, context.remaining_s))
    deadline = loop.time() + budget
    while True:
        context.check_cancelled()
        if predicate():
            return
        if loop.time() >= deadline:
            raise _failed(f"{what} never happened within {budget:.1f}s of the run budget")
        await asyncio.sleep(POLL_S)


async def commit_trace(context: RunContext, journal: TraceRecordingJournal) -> None:
    """Store the run's `trace.jsonl` as evidence, and say so when a line was lost.

    Streamed, not read whole: a long run's journal has no declared bound, and the store
    hashes and writes in chunks anyway.
    """
    if journal.write_failures:
        context.log(f"trace incomplete: {journal.write_failures} line(s) lost "
                    f"({journal.last_write_error}); the stored trace is shorter than the run")
    path = journal.trace_path
    if not path.is_file():
        context.log("no trace file was written; the run has no journal artifact")
        return
    with path.open("rb") as handle:
        context.put_artifact(TRACE_ARTIFACT, kind=ArtifactKind.TRACE_EXCERPT, media_type=TRACE_MEDIA_TYPE,
                             data=handle)


async def open_session(context: RunContext, stack: VoiceStack) -> None:
    """Wake the voice and wait for the Realtime session and the speech scheduler."""
    context.check_cancelled()
    await stack.wake()
    context.log(f"session open: {stack.session.session_id}")


async def close_session(context: RunContext, stack: VoiceStack) -> None:
    """Stop the voice the way production does, so the trace ends with `voice.stop`."""
    if not await stack.shutdown(timeout=max(1.0, min(STEP_TIMEOUT_S, context.remaining_s))):
        context.log("the voice runtime did not stop within the run budget; the trace ends mid-session")


async def submit_user_turn(context: RunContext, stack: VoiceStack, text: str) -> BrainTurnHandle:
    submitted = stack.journal.count("voice.brain_turn_submitted")
    await stack.session.user_says(text)
    await wait_condition(context, lambda: stack.journal.count("voice.brain_turn_submitted") > submitted,
                         "the brain turn submission of the user turn")
    return await stack.backend.next_turn(timeout=max(1.0, min(STEP_TIMEOUT_S, context.remaining_s)))


#: The two measurements that carry scenario expectations. ANY diagnostic that declares
#: `scenario.expectations_failed_count` — a seed with a scenario as much as an ad-hoc
#: probe — turns a failed expectation into a product verdict through its own blocking
#: assertion. A diagnostic that does not declare it cannot express one, so an unmet
#: expectation ends `inconclusive` BY DESIGN (docs/testlab.md, "The expect.* verdict rule").
EXPECTATION_COUNT_METRIC = "scenario.expectations_failed_count"
EXPECTATION_METRICS = ("scenario.expectations_declared", EXPECTATION_COUNT_METRIC)


def expectation_metrics(context: RunContext, executor: VirtualExecutor) -> dict[str, MetricValue]:
    """Scenario expectations as MEASUREMENTS when the declaration can carry them.

    Why this is not "generic runner only": `expect.event` is the one expectation form
    that states something a seed's own metrics cannot (the Conversation Event log), and
    a real defect there must be able to read `failed`, not "could not measure". So the
    rule is a property of the DECLARATION, not of the runner: declare the metric and a
    blocking assertion on it, and your scenario's expectations become a verdict; declare
    neither, and an unmet expectation refuses the run as inconclusive rather than being
    dropped. Either way no runner decides a status — the supervisor still derives it.
    """
    declared = {spec.name for spec in context.diagnostic.metrics}
    if EXPECTATION_COUNT_METRIC not in declared:
        executor.require_expectations_met()
        return {}
    measured: dict[str, MetricValue] = {EXPECTATION_COUNT_METRIC: executor.expectations_failed}
    if "scenario.expectations_declared" in declared:
        measured["scenario.expectations_declared"] = len(executor.expectations)
    return measured


def _ms_between(start: TraceLine | None, end: TraceLine | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, round((end.monotonic - start.monotonic) * 1000))


def speech_lines(journal: TraceRecordingJournal, kind: str, speech_id: str) -> list[TraceLine]:
    """Journal lines of one kind for one speech. Public: the `live` profile measures on the same joins."""
    return [line for line in journal.lines(kind) if line.data.get("speech_id") == speech_id]


# ------------------------------------------------------------- voice.self_echo

@dataclass(frozen=True, slots=True)
class SelfEchoRunner:
    """`voice.self_echo`: Jarvis speaks while its own output comes back as provider VAD onsets.

    Nothing the scenario injects is a real user: every candidate is echo. A barge-in
    confirmed here is therefore false by construction, which is what makes the count a
    verdict rather than an observation.
    """

    async def run(self, context: RunContext) -> RunOutcome:
        duration_ms = int(context.parameters["output.duration_ms"])
        echoes = int(context.parameters["echo.candidate_count"])
        async with virtual_voice_stack(context) as (stack, journal, _core):
            await open_session(context, stack)
            handle = await submit_user_turn(context, stack, "jarvis raconte moi la journee en detail")
            await handle.start_work("self-echo", label="self echo")
            request = await handle.say("voici le recit complet de la journee que jarvis prononce",
                                       kind=SpeechKind.RESULT, work_id="self-echo")
            await wait_condition(context, lambda: len(stack.session.spoken) >= 1,
                                 "the scheduler dispatching the speech to the surface")
            await self._play_with_echo(context, stack, journal, request.id, duration_ms, echoes)
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
            context.log(f"self echo: echoes={echoes} confirmed={confirmed} refused={refused} played_ms={played_ms}")
            await close_session(context, stack)
        await commit_trace(context, journal)
        return RunOutcome(metrics={
            "barge_in.false_confirmed_count": confirmed,
            "barge_in.rejected_count": refused,
            "output.completed": completed,
            "output.played_ms": played_ms,
        })

    async def _play_with_echo(self, context: RunContext, stack: VoiceStack, journal: TraceRecordingJournal,
                              speech_id: str, duration_ms: int, echoes: int) -> None:
        """Play the output in 100 ms blocks, injecting the echo candidates as it plays.

        Each block is waited for on the device's own cursor before the next one, so an
        echo candidate is always injected while Jarvis is audibly the far end. Pushing
        blocks and candidates back to back would inject them before a single byte reached
        the device, which is a different situation entirely.

        A cut output ends the playback instead of failing the run: an interrupted speech
        is a measurement (`output.completed` false), not an error of the harness.

        Known heuristic: how the candidates are spaced over the blocks (`every`) is a
        spread, not a contract. What the diagnostic asserts is the decision on each one,
        not when in the output it landed.
        """
        blocks = max(1, duration_ms // CHUNK_MS)
        every = max(1, blocks // echoes) if echoes else 0
        injected = 0
        for block in range(blocks):
            context.check_cancelled()
            if _terminal_of(journal, speech_id) is not None:
                break
            await stack.session.play_audio(chunks=1)
            audible = (block + 1) * CHUNK_MS
            await wait_condition(context,
                                 lambda: (stack.audio.played_output_ms >= audible
                                          or _terminal_of(journal, speech_id) is not None),
                                 f"{audible} ms of Jarvis output reaching the device")
            if echoes and injected < echoes and block % every == 0:
                await self._inject_and_await_decision(context, stack, journal)
                injected += 1
        while injected < echoes and _terminal_of(journal, speech_id) is None:
            context.check_cancelled()
            await self._inject_and_await_decision(context, stack, journal)
            injected += 1

    async def _inject_and_await_decision(self, context: RunContext, stack: VoiceStack,
                                         journal: TraceRecordingJournal) -> None:
        """Inject one echo candidate and require the stack to DECIDE on it.

        Without this wait the diagnostic passed vacuously: a stack that ignores provider
        VAD entirely produces no confirmation and no rejection, so both counts stay 0 and
        every assertion holds — a stack that can never be interrupted would look perfect
        on the barge-in diagnostic. A stimulus the stack never answers is not evidence of
        correctness, so it fails the run with a structured, actionable failure instead.
        """
        before = journal.counts(*BARGE_IN_DECISION_KINDS)
        await self.inject_echo_candidate(context, stack)
        await wait_condition(
            context, lambda: journal.counts(*BARGE_IN_DECISION_KINDS) > before,
            "a barge-in decision (" + " / ".join(BARGE_IN_DECISION_KINDS) + ") for the injected provider onset; "
            "a stack that never answers provider VAD cannot be judged by this diagnostic")

    async def inject_echo_candidate(self, context: RunContext, stack: VoiceStack) -> None:
        """One provider VAD onset caused by Jarvis's own output.

        Overridable seam: a test injects a *real* barge-in here to prove the diagnostic
        can fail. Nothing in a run ever overrides it. The seam is the stimulus only; the
        requirement that the stack decides is enforced by `_inject_and_await_decision`,
        which a subclass therefore cannot weaken.
        """
        del context
        await stack.session.interrupt()


def _terminal_of(journal: TraceRecordingJournal, speech_id: str) -> str | None:
    for line in journal.timeline:
        if line.kind in SPEECH_TERMINAL_KINDS and line.data.get("speech_id") == speech_id:
            return line.kind
    return None


# ------------------------------------------------------ speech.payload_integrity

@dataclass(frozen=True, slots=True)
class PayloadIntegrityRunner:
    """`speech.payload_integrity`: what the brain scripted against what the surface delivered.

    The harness knows both sides exactly, which is why this seed never uses the provider
    divergence signal (`voice.state.spoken_diverged`): that signal compares raw strings and
    fires on ordinary transcription noise (see
    `tasks/.../Issues/speech-payload-integrity-needs-normalized-measure.md`).
    """

    async def run(self, context: RunContext) -> RunOutcome:
        count = int(context.parameters["speech.request_count"])
        scripted: dict[str, str] = {}
        async with virtual_voice_stack(context) as (stack, journal, _core):
            await open_session(context, stack)
            handle = await submit_user_turn(context, stack, "jarvis enumere les points du rapport")
            await handle.start_work("payload", label="payload")
            for index in range(count):
                context.check_cancelled()
                text = self.payload_text(index)
                request = await handle.say(text, kind=SpeechKind.RESULT, work_id="payload")
                scripted[request.id] = text
                delivered = index + 1
                await wait_condition(context, lambda: len(stack.session.spoken) >= delivered,
                                     f"payload {index + 1} reaching the surface")
                await stack.speak_and_finish(chunks=1, transcript=text)
                await self.after_delivery(context, stack, request)
            handle.finish(public_summary=self.payload_text(count - 1))
            await wait_condition(context, lambda: journal.counts("voice.speech.completed") >= count,
                                 "every scripted payload reaching a terminal status")
            spoken = list(stack.session.spoken)
            metrics = _payload_metrics(scripted, spoken)
            context.log(f"payloads: scripted={len(scripted)} delivered={len(spoken)} "
                        f"mismatch={metrics['speech.payload_mismatch_count']}")
            await close_session(context, stack)
        # After the teardown: the last lines of a run are written while Core stops, and an
        # artifact that stopped one line early would not be the run's journal.
        await commit_trace(context, journal)
        return RunOutcome(metrics=metrics)

    @staticmethod
    def payload_text(index: int) -> str:
        """Distinct, bounded payloads: two identical texts would hide a replay."""
        return f"point numero {index + 1} du rapport demande par l utilisateur"

    async def after_delivery(self, context: RunContext, stack: VoiceStack, request: SpeechRequest) -> None:
        """Overridable seam: a test corrupts the delivered payload here to prove the failure path."""
        del context, stack, request


def _payload_metrics(scripted: Mapping[str, str], spoken: list[SpeechRequest]) -> dict[str, MetricValue]:
    seen: set[str] = set()
    mismatch = replayed = 0
    for request in spoken:
        if scripted.get(request.id) != request.text:
            mismatch += 1
        if request.id in seen:
            replayed += 1
        seen.add(request.id)
    return {
        "speech.scripted_count": len(scripted),
        "speech.delivered_count": len(spoken),
        "speech.payload_mismatch_count": mismatch,
        "speech.replayed_payload_count": replayed,
        "speech.undelivered_count": len(set(scripted) - seen),
    }


# ----------------------------------------------------- speech.stale_supersession

@dataclass(frozen=True, slots=True)
class StaleSupersessionRunner:
    """`speech.stale_supersession`: runs the scenario converted from the `stale_ack_35_9s` fixture.

    The whole situation is authored data: a busy output, an acknowledgement queued behind
    it, a later user turn that revises the intent, then the release. Every decision —
    supersession, admission, delivery — is the production speech scheduler's.
    """

    async def run(self, context: RunContext) -> RunOutcome:
        scenario = context.scenario
        if scenario is None:
            raise _failed("this diagnostic needs a scenario; the manifest ships one and none was supplied")
        async with virtual_voice_stack(context) as (stack, journal, _core):
            await open_session(context, stack)
            executor = VirtualExecutor(stack=stack, context=context, journal=journal)
            await executor.run(scenario)
            metrics = _supersession_metrics(journal, executor)
            executor.check_measured_expectations(metrics, {})
            # A version of this diagnostic that declares `scenario.expectations_failed_count`
            # turns an unmet expectation into its own verdict; v1 does not, so one refuses
            # the run as inconclusive instead of being dropped.
            metrics.update(expectation_metrics(context, executor))
            context.log(f"supersession: superseded={metrics['speech.superseded_count']} "
                        f"stale_delivered={metrics['speech.stale_delivered_count']} "
                        f"latest_delivered={metrics['speech.latest_intent_delivered']}")
            await close_session(context, stack)
        # After the teardown: the last lines of a run are written while Core stops, and an
        # artifact that stopped one line early would not be the run's journal.
        await commit_trace(context, journal)
        return RunOutcome(metrics=metrics)


#: The scheduler lines that prove a candidate reached it (either is the first one emitted).
_SCHEDULER_SEEN_KINDS = ("voice.speech.queued", "voice.speech.presentation_decided")
_SUPERSEDED_KINDS = ("voice.speech.superseded", "voice.speech.expired")
_DELIVERY_KINDS = ("voice.speech.started", "voice.speech.completed")


def _supersession_metrics(journal: TraceRecordingJournal, executor: VirtualExecutor) -> dict[str, MetricValue]:
    """Derive the four declared measures from the journal and the scenario's virtual timeline.

    **Staleness is keyed on candidate identity, not on the label the stack applied.** The
    earlier version only counted a delivery that followed a `voice.speech.superseded` line,
    so a stack that never noticed the revision and spoke the old acknowledgement 35.9 s
    late measured `stale_delivered_count = 0` — the diagnostic was blind to the exact
    defect it exists for. A candidate is stale here when either

    - the stack admitted it (`voice.speech.superseded` / `.expired` before its delivery), or
    - the scheduler had already SEEN a candidate of a later `intent_epoch` before this one
      started. The epochs are the scenario's own declaration and the moment the later
      candidate reached the scheduler is a journal line, so this is observed fact, not a
      relabelling of the run.

    `superseded_count` stays the count the stack admitted. The two disagreeing —
    `superseded_count = 0` with `stale_delivered_count = 1` — is itself the finding: the
    answer was stale and the stack never knew.
    """
    seen_at: dict[str, int] = {}
    ended_at: dict[str, int] = {}
    delivered_at: dict[str, int] = {}
    for index, line in enumerate(journal.timeline):
        speech_id = line.data.get("speech_id")
        if not isinstance(speech_id, str):
            continue
        if line.kind in _SCHEDULER_SEEN_KINDS:
            seen_at.setdefault(speech_id, index)
        if line.kind in _SUPERSEDED_KINDS:
            ended_at.setdefault(speech_id, index)
        elif line.kind in _DELIVERY_KINDS:
            delivered_at.setdefault(speech_id, index)

    stale_delivered = 0
    stale_wait_ms = 0
    for candidate_id, record in executor.candidates.items():
        revised_at = _revision_index(candidate_id, record, executor, seen_at)
        admitted_at = ended_at.get(candidate_id)
        delivery = delivered_at.get(candidate_id)
        stale_at = min((index for index in (revised_at, admitted_at) if index is not None), default=None)
        if admitted_at is not None:
            record.ended_at_ms = executor.virtual_time_of(admitted_at)
        if stale_at is None or (delivery is not None and delivery < stale_at):
            # Never stale, or already spoken before the revision reached the scheduler:
            # an answer that was still current when it was said never waited as a stale one.
            continue
        resolved_at = stale_at
        if delivery is not None and delivery > stale_at:
            stale_delivered += 1
            resolved_at = delivery  # a stale payload that IS spoken waited until it spoke
        stale_wait_ms = max(stale_wait_ms, executor.virtual_time_of(resolved_at) - record.enqueued_at_ms)

    epochs = [(record.intent_epoch, record.candidate_id) for record in executor.candidates.values()
              if record.intent_epoch is not None]
    latest = max(epochs)[1] if epochs else None
    return {
        "speech.superseded_count": len(ended_at),
        "speech.stale_delivered_count": stale_delivered,
        "speech.latest_intent_delivered": bool(latest is not None and latest in delivered_at),
        "speech.stale_wait_ms": max(0, stale_wait_ms),
    }


def _revision_index(candidate_id: str, record, executor: VirtualExecutor,
                    seen_at: dict[str, int]) -> int | None:  # noqa: ANN001 - CandidateRecord
    """Journal index at which the scheduler first saw a candidate of a LATER intent epoch."""
    if record.intent_epoch is None:
        return None
    later = [seen_at[other.candidate_id] for other in executor.candidates.values()
             if other.candidate_id != candidate_id and other.intent_epoch is not None
             and other.intent_epoch > record.intent_epoch and other.candidate_id in seen_at]
    return min(later) if later else None


# ---------------------------------------------------------- voice.queue_latency

@dataclass(frozen=True, slots=True)
class QueueLatencyRunner:
    """`voice.queue_latency`: the scheduler's own delays, on virtual doubles.

    What it measures is internal: enqueue to dispatch, speech start to the first PCM the
    bridge relayed, and the end-to-end reaction of one turn (dominated by the scripted
    brain's thinking time, which is a run parameter). It measures no provider and no
    device: see "What the virtual profile cannot prove" in `docs/testlab.md`.
    """

    async def run(self, context: RunContext) -> RunOutcome:
        count = int(context.parameters["speech.request_count"])
        think_s = int(context.parameters["brain.result_delay_ms"]) / 1000
        async with virtual_voice_stack(context) as (stack, journal, _core):
            await open_session(context, stack)
            handle = await submit_user_turn(context, stack, "jarvis donne moi les quatre points du jour")
            await handle.start_work("latency", label="latency")
            # A real wait, because it is the quantity `user_turn.end_to_first_audio_ms`
            # measures — the brain thinking. It goes through `RunContext.sleep`, so a
            # cancel ends it at once instead of after the full delay.
            await context.sleep(think_s)
            for index in range(count):
                context.check_cancelled()
                request = await handle.say(f"point {index + 1} de la reponse du jour",
                                           kind=SpeechKind.RESULT, work_id="latency")
                await wait_condition(context, lambda: bool(speech_lines(journal, "voice.speech.started", request.id)),
                                     f"speech {index + 1} starting")
                await self.play_first_audio(context, stack)
                await stack.session.finish_output(status="completed", transcript=request.text)
                await wait_condition(context,
                                     lambda: bool(speech_lines(journal, "voice.speech.completed", request.id)),
                                     f"speech {index + 1} completing")
            handle.finish(public_summary="")
            metrics = latency_metrics(journal)
            context.log(f"latency: {metrics}")
            await close_session(context, stack)
        # After the teardown: the last lines of a run are written while Core stops, and an
        # artifact that stopped one line early would not be the run's journal.
        await commit_trace(context, journal)
        return RunOutcome(metrics=metrics)

    async def play_first_audio(self, context: RunContext, stack: VoiceStack) -> None:
        """Relay the first provider PCM of the started speech.

        Overridable seam: a test delays it past the declared threshold to prove that the
        blocking assertion actually fails. Nothing in a run ever overrides it.
        """
        del context
        await stack.session.play_audio(chunks=1)


def latency_metrics(journal: TraceRecordingJournal) -> dict[str, MetricValue]:
    """Per-speech stage joins, reported as the run's worst case.

    `queue_free_to_started` is measured from the later of the speech's own queueing and
    the terminal status of the previous delivered speech: that is the moment the queue and
    the floor were both free for it.

    **A missing join is omitted, never reported as 0.** A run where no provider audio was
    ever relayed used to measure `started_to_first_audio_ms = 0` and pass every assertion:
    the worst possible stack scored the best possible number. An omitted metric makes its
    assertion `missing`, the verdict inconclusive and the run `errored`
    (`assertions_inconclusive`), which is the Slice 01 doctrine — a diagnostic that cannot
    measure says so instead of certifying silence.

    `delivered_count` counts AUDIBLE deliveries — a speech that reached `completed` and
    for which the bridge relayed at least one block of provider audio. A speech that
    completed without a single sample was not delivered to anyone.
    """
    queue_free = started_to_audio = 0
    previous_terminal: TraceLine | None = None
    delivered = 0
    started_lines = journal.lines("voice.speech.started")
    missing_audio = False
    for started in started_lines:
        speech_id = str(started.data.get("speech_id") or "")
        queued = next(iter(speech_lines(journal, "voice.speech.queued", speech_id)), None)
        free = max((line for line in (queued, previous_terminal) if line is not None),
                   key=lambda line: line.monotonic, default=None)
        queue_free = max(queue_free, _ms_between(free, started) or 0)
        first_audio = next(iter(speech_lines(journal, "voice.latency.provider_first_pcm", speech_id)), None)
        if first_audio is None:
            missing_audio = True
        else:
            started_to_audio = max(started_to_audio, _ms_between(started, first_audio) or 0)
        completed = next(iter(speech_lines(journal, "voice.speech.completed", speech_id)), None)
        if completed is not None:
            previous_terminal = completed
            if first_audio is not None:
                delivered += 1
    metrics: dict[str, MetricValue] = {"speech.delivered_count": delivered}
    if started_lines:
        metrics["speech.queue_free_to_started_ms"] = queue_free
        if not missing_audio:
            metrics["speech.started_to_first_audio_ms"] = started_to_audio
    turn_to_audio = _ms_between(journal.first("voice.brain_turn_submitted"),
                                journal.first("voice.latency.provider_first_pcm"))
    if turn_to_audio is not None:
        metrics["user_turn.end_to_first_audio_ms"] = turn_to_audio
    return metrics


# -------------------------------------------------------- generic scenario runner

@dataclass(frozen=True, slots=True)
class ScenarioRunner:
    """`testlab.scenario.virtual`: performs an ad-hoc scenario and measures the scenario itself.

    **The measurement contract (Slice 07).** An ad-hoc diagnostic declares its own
    metrics, and the only things a generic runner can honestly measure are properties
    of the scenario it just performed. Those four are `SCENARIO_METRICS`; a diagnostic
    that declares anything else is refused loudly rather than stored with a verdict
    derived from nothing.

    The expectation half is `expectation_metrics`, which is shared with every
    specialized runner: the rule is a property of the DECLARATION, not of the runner
    (see that function and docs/testlab.md, "The `expect.*` verdict rule").
    """

    async def run(self, context: RunContext) -> RunOutcome:
        scenario = context.scenario
        if scenario is None:
            raise _failed("the generic virtual runner needs a scenario")
        declared = {spec.name for spec in context.diagnostic.metrics}
        unmeasurable = sorted(declared - set(SCENARIO_METRICS))
        if unmeasurable:
            raise _failed(f"the generic virtual runner cannot measure {unmeasurable}; declare a specialized "
                          "implementation for this diagnostic")
        async with virtual_voice_stack(context) as (stack, journal, _core):
            await open_session(context, stack)
            executor = VirtualExecutor(stack=stack, context=context, journal=journal)
            await executor.run(scenario)
            metrics: dict[str, MetricValue] = {"scenario.steps_performed": len(scenario.steps),
                                               "scenario.checkpoints_reached": len(executor.checkpoints)}
            # Evaluated before the expectation counts are added, so an `expect.metric` reads
            # what the scenario produced and never its own count (which would be circular).
            executor.check_measured_expectations(metrics, {})
            metrics.update(expectation_metrics(context, executor))
            context.log(f"scenario: steps={metrics['scenario.steps_performed']} "
                        f"checkpoints={metrics['scenario.checkpoints_reached']} "
                        f"expectations={len(executor.expectations)} unmet={executor.expectations_failed}")
            await close_session(context, stack)
        await commit_trace(context, journal)
        return RunOutcome(metrics={name: value for name, value in metrics.items() if name in declared})


#: What the generic scenario runner can report, whatever the scenario is. A diagnostic
#: using `testlab.scenario.virtual` declares a subset of these and nothing else.
SCENARIO_METRICS = ("scenario.steps_performed", "scenario.checkpoints_reached",
                    "scenario.expectations_declared", "scenario.expectations_failed_count")


__all__ = ["PayloadIntegrityRunner", "QueueLatencyRunner", "ScenarioRunner", "SelfEchoRunner",
           "StaleSupersessionRunner", "VirtualRunError", "VirtualStepError", "virtual_voice_stack",
           "wait_condition"]
