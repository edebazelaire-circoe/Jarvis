"""Executing a Test Lab scenario on the virtual voice stack.

Binding contract: `docs/testlab.md` ("Virtual profile"). This module owns the
primitive-to-harness mapping: one `PrimitiveHandler` per primitive the `virtual`
profile declares, so `missing_handlers(DEFAULT_PRIMITIVES, VIRTUAL, VirtualExecutor.
HANDLED)` is empty. Nothing here decides a verdict; it performs stimuli, waits for
the production stack to react, and records what it saw.

Two rules shape every handler:

- **A step that cannot be performed fails the run.** There is no silent no-op: a
  handler either drives the stack, or raises `VirtualStepError` naming the step, the
  primitive, what was expected and what was observed.
- **Every wait is a condition with a deadline taken from the run.** No handler sleeps
  to "let things happen"; it waits for an observable journal line or stack state, and
  its budget is `RunContext.remaining_s` clamped by `STEP_TIMEOUT_S`. A run therefore
  ends on the supervisor's deadline, not on a fixed wall clock (see
  `tasks/jarvis-category2-test-lab/Issues/voice-harness-wall-clock-flake-under-load.md`).

Virtual time (`at_ms`) is the scenario's own timeline: it orders the steps and dates
what a scenario authored (how long a candidate waited before its supersession, for
example). It is never a real wait. Advancing it moves the injected `FakeClock` when
the run has one, so runtime timers observe the elapsed time without a sleep.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
import math
from typing import Any

from jarvis.domain.conversation_event_store import MAX_EVENT_PAGE_LIMIT
from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.v2 import (
    AddressingDecision,
    ProtocolEnvelope,
    SpeechKind,
    SpeechRequest,
    utc_now,
)
from jarvis.testlab.primitives import AT_MS, DEFAULT_PRIMITIVES, missing_handlers
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runners import MeasurementUnavailable, RunContext, ScenarioExpectationUnmet
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.validation import fail
from jarvis.testlab.virtual.harness import CHUNK_MS, BrainTurnHandle, VoiceStack
from jarvis.testlab.virtual.journal import TraceRecordingJournal

#: Upper bound of one step's wait. Always clamped further by `RunContext.remaining_s`,
#: so the run deadline, not this constant, is what ends a stuck run.
STEP_TIMEOUT_S = 15.0
#: Poll of a condition wait. Short enough to be invisible, long enough not to spin.
POLL_S = 0.005
#: Consecutive quiet polls that mean "the stack settled" for a checkpoint.
SETTLE_QUIET_POLLS = 8
#: Pages one `expect.event` step may scan (`MAX_EVENT_PAGE_LIMIT` events each). 10 000
#: events is far past any scenario; beyond it the count is a lower bound and the step
#: refuses to judge rather than truncating silently.
MAX_EVENT_PAGES = 20

VIRTUAL_STEP_FAILED = "testlab_virtual_step_failed"
#: An `expect.*` step there was nothing to evaluate against (the metric was never
#: measured, the assertion is not declared, no conversation was opened). An authoring
#: or structural problem, never a statement about the product: it is "could not
#: measure" (docs/testlab.md, "The expect.* verdict rule").
VIRTUAL_EXPECTATION_UNEVALUABLE = "testlab_virtual_expectation_unevaluable"
#: A profile executor redefined a primitive the shared table already performs. A defect
#: of ours, not a finding: it is NOT a `MeasurementUnavailable`, so it reads `crashed`.
VIRTUAL_PROFILE_HANDLER_INVALID = "testlab_virtual_profile_handler_invalid"

#: `_expect_arg` sentinel: this argument has no default and the step must carry it.
_REQUIRED = object()


class VirtualStepError(MeasurementUnavailable):
    """A scenario step could not be performed, or an expectation could not be evaluated.

    It is a `MeasurementUnavailable`, so the worker records
    `measurement_unavailable` and the run reads `inconclusive`: the authored
    situation was not established, which says nothing about the product. An
    expectation that WAS evaluated and disagreed is not this — it is recorded as
    an `ExpectationResult` and carried by a metric, or raised as
    `ScenarioExpectationUnmet` by the runner.
    """


def _step_error(index: int, step: ScenarioStep, detail: str, code: str = VIRTUAL_STEP_FAILED) -> VirtualStepError:
    return VirtualStepError(code, f"steps[{index}] {step.primitive}: {detail}")


@dataclass(slots=True)
class Expectation:
    """An `expect.*` step, kept until the end of the run (it reads final evidence)."""

    index: int
    step: ScenarioStep


@dataclass(frozen=True, slots=True)
class ExpectationResult:
    """The verdict of one evaluated `expect.*` step: what it wanted, what happened."""

    index: int
    primitive: str
    met: bool
    detail: str


@dataclass(slots=True)
class CandidateRecord:
    """What the executor knows about one speech candidate a scenario named."""

    candidate_id: str
    kind: str
    enqueued_at_ms: int
    intent_id: str | None = None
    intent_epoch: int | None = None
    #: Virtual time at which the journal first reported it superseded or expired.
    ended_at_ms: int | None = None


@dataclass(slots=True)
class VirtualExecutor:
    """Performs scenario steps against a running `VoiceStack`.

    It holds no policy: every decision it observes (a supersession, a barge-in
    rejection, an addressing classification) is the production stack's.
    """

    stack: VoiceStack
    context: RunContext
    journal: TraceRecordingJournal
    at_ms: int = 0
    #: `(at_ms, journal length after the step)`, so a journal line can be dated in virtual time.
    marks: list[tuple[int, int]] = field(default_factory=list)
    candidates: dict[str, CandidateRecord] = field(default_factory=dict)
    handles: list[BrainTurnHandle] = field(default_factory=list)
    work_handles: dict[str, BrainTurnHandle] = field(default_factory=dict)
    checkpoints: list[str] = field(default_factory=list)
    expectations: list[Expectation] = field(default_factory=list)
    #: One entry per EVALUATED expectation, in step order. An expectation that could not
    #: be evaluated raises instead, so this list never silently omits a verdict.
    expectation_results: list[ExpectationResult] = field(default_factory=list)
    session_closed: bool = False
    stopped: bool = False

    @property
    def expectations_failed(self) -> int:
        """Evaluated expectations the run did not meet. This is a MEASUREMENT, not a verdict."""
        return sum(1 for result in self.expectation_results if not result.met)

    def require_expectations_met(self) -> None:
        """Raise `ScenarioExpectationUnmet` when an evaluated expectation disagreed.

        For a diagnostic that declares no metric able to carry the count (every
        specialized runner): the authored situation did not materialise, so the run
        is not the experiment that was asked for, and it must not be stored as if the
        scenario had run as written. A diagnostic that DOES declare
        `scenario.expectations_failed_count` reports the count instead and lets its own
        blocking assertion turn it into `failed`.
        """
        unmet = [result for result in self.expectation_results if not result.met]
        if unmet:
            raise ScenarioExpectationUnmet(
                "testlab_scenario_expectation_unmet",
                f"{len(unmet)} scenario expectation(s) not met: "
                + "; ".join(f"steps[{result.index}] {result.primitive}: {result.detail}" for result in unmet[:4]))

    # ------------------------------------------------------------- pilotage

    def handler_for(self, primitive: str):
        """Which handler performs one primitive.

        The table stays a module constant (`HANDLERS`), reviewed in one place; this
        hook is how a PROFILE adds the primitives it, and only it, can perform —
        Slice 08's `audio.inject` on the real capture path. A profile may add, never
        replace, and `resolve_handler` ENFORCES that: a subclass that shadowed an
        existing name would silently change what a shipped scenario means.
        """
        return HANDLERS.get(primitive)

    def resolve_handler(self, primitive: str):
        """`handler_for`, checked against the shared table. Add-only, mechanically.

        A docstring convention is not a rule. A profile that returns something other
        than `HANDLERS[primitive]` for a primitive the shared table already performs is
        refused here, loudly, rather than quietly redefining `provider.output_done` for
        one profile and leaving every stored run of it uncomparable.
        """
        handler = self.handler_for(primitive)
        shared = HANDLERS.get(primitive)
        if shared is not None and handler is not shared:
            raise fail(f"{type(self).__name__} replaces the shared handler for {primitive}; a profile "
                       "executor may add a primitive, never redefine one", VIRTUAL_PROFILE_HANDLER_INVALID)
        return handler

    async def run(self, scenario: Scenario) -> None:
        """Perform every step in order. The first failure ends the run."""
        for index, step in enumerate(scenario.steps):
            self.context.check_cancelled()
            await self._advance_to(int(step.args[AT_MS]))
            handler = self.resolve_handler(step.primitive)
            if handler is None:  # pragma: no cover - HANDLED covers the registry, proven by a test
                raise _step_error(index, step, "this profile registers no handler for this primitive")
            result = handler(self, index, step)
            if isinstance(result, Awaitable):
                await result
            self.marks.append((self.at_ms, len(self.journal.timeline)))
        await self._check_expectations()

    def virtual_time_of(self, line_index: int) -> int:
        """Virtual time of the step during which journal line `line_index` was emitted."""
        for at_ms, length in self.marks:
            if line_index < length:
                return at_ms
        return self.at_ms

    async def _advance_to(self, at_ms: int) -> None:
        """Move the scenario's virtual clock forward, then let the stack act.

        This is not a wait: the elapsed time is given to the injected clock (which is
        what runtime timers read) and the loop is settled by condition, never by a sleep.
        """
        delta_ms = max(0, at_ms - self.at_ms)
        self.at_ms = max(self.at_ms, at_ms)
        clock = self.stack.clock
        if clock is not None and delta_ms:
            clock.advance(delta_ms / 1000)
        if delta_ms:
            await self._settle()

    async def _settle(self) -> None:
        """Yield until the journal has been quiet for `SETTLE_QUIET_POLLS` polls.

        Quiescence of the observable evidence, not a duration: a stack still emitting
        is still working, and a stack that stopped emitting has finished reacting.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._budget()
        quiet, seen = 0, len(self.journal.timeline)
        while quiet < SETTLE_QUIET_POLLS and loop.time() < deadline:
            self.context.check_cancelled()
            await asyncio.sleep(POLL_S)
            length = len(self.journal.timeline)
            quiet = quiet + 1 if length == seen else 0
            seen = length

    def _budget(self) -> float:
        """Seconds this step may wait: the run's remaining time, capped by the step bound."""
        return max(0.0, min(STEP_TIMEOUT_S, self.context.remaining_s))

    async def wait_for(self, predicate: Callable[[], bool], index: int, step: ScenarioStep, expected: str) -> None:
        """Wait for an observable condition; raise a structured step failure on the deadline."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._budget()
        while True:
            self.context.check_cancelled()
            if predicate():
                return
            if loop.time() >= deadline:
                raise _step_error(index, step, f"{expected} never happened within {self._budget():.1f}s of run budget")
            await asyncio.sleep(POLL_S)

    # --------------------------------------------------------------- outils

    @staticmethod
    def utterance(tag: str) -> str:
        """A bounded synthetic sentence standing for an opaque tag (a tag carries no words)."""
        words = str(tag).replace("_", " ").replace("-", " ").strip() or "contenu"
        return f"scenario {words}"[:240]

    def _live_handle(self) -> BrainTurnHandle | None:
        for handle in reversed(self.handles):
            if not handle.release.is_set():
                return handle
        return None

    def _journal_has(self, kind: str, **fields: Any) -> bool:
        return any(line.kind == kind and all(line.data.get(key) == value for key, value in fields.items())
                   for line in self.journal.timeline)

    def _refuse_when_closed(self, index: int, step: ScenarioStep) -> None:
        if self.session_closed or self.stopped:
            raise _step_error(index, step, "the scenario already closed the session; no stimulus can follow")

    async def _push(self, message_type: str, **payload: Any) -> None:
        await self.stack.session.push(message_type, **payload)

    # ------------------------------------------------------------ handlers

    async def _handle_user_turn(self, index: int, step: ScenarioStep) -> None:
        await self._user_says(index, step, self.utterance(step.args["content_tag"]))

    async def _handle_user_speech(self, index: int, step: ScenarioStep) -> None:
        await self._user_says(index, step, str(step.args["text"]))

    async def _handle_user_interrupt(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        await self.stack.session.interrupt()
        await self._user_says(index, step, str(step.args["text"]))

    async def _user_says(self, index: int, step: ScenarioStep, text: str) -> None:
        """A committed user turn, then the addressing the production classifier decided."""
        self._refuse_when_closed(index, step)
        seen = self.journal.counts("voice.transcript")
        submitted = self.journal.counts("voice.brain_turn_submitted")
        await self.stack.session.user_says(text, item_id=str(step.args["turn_id"]))
        await self.wait_for(lambda: self.journal.counts("voice.transcript") > seen, index, step,
                            "the transcript of the user turn")
        observed = str(self.journal.lines("voice.transcript")[-1].get("addressing", ""))
        declared = step.args.get("addressing")
        if declared is not None and observed != _ADDRESSING[str(declared)]:
            raise _step_error(index, step, f"the stack classified the utterance {observed!r}, not {declared!r}; the "
                                           "virtual profile observes addressing, it cannot impose it")
        if observed == AddressingDecision.AMBIENT.value:
            return
        await self.wait_for(lambda: self.journal.counts("voice.brain_turn_submitted") > submitted, index, step,
                            "the brain turn submission of the user turn")
        self.handles.append(await self.stack.backend.next_turn(timeout=self._budget()))

    async def _handle_brain_hold(self, index: int, step: ScenarioStep) -> None:
        work_id = str(step.args["work_id"])
        handle = self._live_handle()
        if handle is None:
            raise _step_error(index, step, "no brain turn is in flight; a brain.* step needs a preceding user turn")
        await handle.start_work(work_id, label=work_id)
        self.work_handles[work_id] = handle

    async def _handle_brain_ready(self, index: int, step: ScenarioStep) -> None:
        work_id = str(step.args["work_id"])
        handle = self.work_handles.get(work_id) or self._live_handle()
        if handle is None:
            raise _step_error(index, step, f"work {work_id} is not held by any brain turn in flight")
        text = self.utterance(step.args["result_tag"])
        await handle.say(text, kind=SpeechKind.RESULT, work_id=work_id)
        await handle.complete_work(work_id, summary=text)

    async def _handle_brain_release(self, index: int, step: ScenarioStep) -> None:
        work_id = str(step.args["work_id"])
        handle = self.work_handles.get(work_id) or self._live_handle()
        if handle is None:
            raise _step_error(index, step, f"work {work_id} is not held by any brain turn in flight")
        handle.finish(public_summary="")
        await self._settle()

    async def _handle_scheduler_enqueue(self, index: int, step: ScenarioStep) -> None:
        """A speech candidate enters the scheduler, with the identity the scenario names.

        Through the brain turn in flight when there is one (Core then stamps the real
        speech source), otherwise published straight onto Core's event bus with the
        scenario's own source: a candidate may predate any turn, and that is exactly
        the shape the stale-acknowledgement incident had.
        """
        self._refuse_when_closed(index, step)
        args = step.args
        candidate_id = str(args["candidate_id"])
        kind = SpeechKind.ACK if str(args["kind"]) == "ack" else SpeechKind.RESULT
        ttl_ms = args.get("ttl_ms")
        text = self.utterance(candidate_id)
        handle = self._live_handle()
        expires_at = utc_now() + timedelta(milliseconds=int(ttl_ms)) if ttl_ms else None
        if handle is not None:
            await handle.say(text, kind=kind, work_id=args.get("work_id"), expires_at=expires_at,
                             speech_id=candidate_id)
        else:
            await self._publish_candidate(index, step, candidate_id, kind, text, expires_at)
        self.candidates[candidate_id] = CandidateRecord(
            candidate_id, str(args["kind"]), self.at_ms,
            intent_id=args.get("intent_id"), intent_epoch=args.get("intent_epoch"))
        await self.wait_for(lambda: self._journal_has("voice.speech.presentation_decided", speech_id=candidate_id)
                            or self._journal_has("voice.speech.queued", speech_id=candidate_id),
                            index, step, f"the scheduler taking candidate {candidate_id} into account")

    async def _publish_candidate(self, index: int, step: ScenarioStep, candidate_id: str, kind: SpeechKind,
                                 text: str, expires_at) -> None:  # noqa: ANN001
        conversation_id = self.stack.runtime.runtime.conversation_id
        if not conversation_id:
            raise _step_error(index, step, "no conversation is open yet; wake the voice before enqueuing a candidate")
        correlation_id = f"{candidate_id}-corr"
        source = None
        if step.args.get("intent_id") is not None and step.args.get("intent_epoch") is not None:
            source = SpeechSource(turn_id=f"{candidate_id}-turn", correlation_id=correlation_id,
                                  intent_id=str(step.args["intent_id"]), intent_epoch=int(step.args["intent_epoch"]))
        request = SpeechRequest(conversation_id=conversation_id, text=text, kind=kind, id=candidate_id,
                                correlation_id=correlation_id, work_id=step.args.get("work_id"),
                                expires_at=expires_at, source=source)
        await self.stack.core.events.publish(ProtocolEnvelope(
            message_type="brain.speech.requested", payload=request.to_payload(),
            correlation_id=correlation_id, conversation_id=conversation_id))

    async def _handle_provider_output_started(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        await self._push("realtime.output_started", output_id=str(step.args["output_id"]))

    async def _handle_provider_transcript_final(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        await self._push("realtime.assistant_transcript", text=self.utterance(step.args["generated_tag"]),
                         speech_id=self.stack.session.active_speech_id or "")

    async def _handle_provider_output_done(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        output_id = str(step.args["output_id"])
        await self._push("realtime.audio_done", output_id=output_id)
        await self._push("realtime.response_done", output_id=output_id, status=str(step.args["status"]))

    async def _handle_provider_cancel_rejected(self, index: int, step: ScenarioStep) -> None:
        """Arm the fake provider to refuse the next cancel of this output.

        The refusal is observed later, as `voice.barge_in_degraded` /
        `barge_in_cancel_failed`: this step arms the fault, it does not assert it.
        """
        self._refuse_when_closed(index, step)
        self.stack.session.cancel_refusals[str(step.args["output_id"])] = str(step.args["reason_code"])

    async def _handle_provider_session_closed(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        await self.stack.session.close()
        self.session_closed = True
        await self._settle()

    async def _handle_owner_candidate(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        await self._push("realtime.speech_started")
        await self._settle()

    async def _handle_owner_rejected(self, index: int, step: ScenarioStep) -> None:
        """Observation, not a stimulus: the owner decision belongs to the code under test."""
        await self.wait_for(lambda: self.journal.counts("voice.barge_in_rejected", "voice.barge_in_ignored") > 0,
                            index, step, "a rejected barge-in candidate")

    async def _handle_owner_confirmed(self, index: int, step: ScenarioStep) -> None:
        await self.wait_for(lambda: self.journal.counts("voice.barge_in", "voice.barge_in.owner_confirmed") > 0,
                            index, step, "a confirmed barge-in")

    async def _handle_device_output_busy(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        output_id = str(step.args.get("output_id") or step.args.get("playback_id"))
        await self._push("realtime.output_started", output_id=output_id)
        played_ms = step.args.get("played_ms")
        if played_ms:
            await self._play(output_id, int(played_ms))
        await self.wait_for(lambda: self._journal_has("voice.output_started", output_id=output_id),
                            index, step, f"the surface reporting output {output_id} as open")

    async def _handle_device_consume(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        await self._play(str(step.args["output_id"]), int(step.args["played_ms"]))

    async def _handle_device_release(self, index: int, step: ScenarioStep) -> None:
        self._refuse_when_closed(index, step)
        output_id = str(step.args["output_id"])
        if not step.args.get("provider_still_active"):
            await self._push("realtime.audio_done", output_id=output_id)
        await self._push("realtime.response_done", output_id=output_id, status="completed")
        await self._settle()

    async def _play(self, output_id: str, played_ms: int) -> None:
        """Feed `played_ms` of provider audio for `output_id`, in whole 100 ms output blocks."""
        from jarvis.testlab.virtual.harness import audio_chunk_b64

        chunks = max(1, math.ceil(played_ms / CHUNK_MS))
        await self._push("realtime.audio", pcm_b64=audio_chunk_b64(chunks), output_id=output_id,
                         speech_id=self.stack.session.active_speech_id, item_id=f"{output_id}-item",
                         response_id=f"{output_id}-resp", content_index=0, output_index=0)

    async def _handle_control_stop(self, index: int, step: ScenarioStep) -> None:
        if not await self.stack.shutdown(timeout=self._budget()):
            raise _step_error(index, step, "the voice runtime did not stop within the run budget")
        self.stopped = True

    async def _handle_control_checkpoint(self, index: int, step: ScenarioStep) -> None:
        await self._settle()
        self.checkpoints.append(str(step.args["checkpoint_id"]))

    async def _handle_time_wait(self, index: int, step: ScenarioStep) -> None:
        del index, step
        await self._settle()

    async def _handle_parameter_override(self, index: int, step: ScenarioStep) -> None:
        """The prelude is applied before the run; the step proves it actually was."""
        name, value = str(step.args["parameter"]), step.args["value"]
        applied = self.context.overrides.get(name, self.context.parameters.get(name))
        if applied != value:
            raise _step_error(index, step, f"override {name} was not applied to this run "
                                           f"(the run resolved {applied!r})")

    def _handle_expect(self, index: int, step: ScenarioStep) -> None:
        self.expectations.append(Expectation(index, step))

    # ------------------------------------------------------------- attentes

    async def _check_expectations(self) -> None:
        for expectation in self.expectations:
            step = expectation.step
            if step.primitive == "expect.event":
                await self._check_event_expectation(expectation)
            # `expect.metric` and `expect.assertion` read the final measurements, which only
            # the runner has; it calls `check_measured_expectations` once it has them.

    def _record(self, expectation: Expectation, met: bool, detail: str) -> None:
        self.expectation_results.append(ExpectationResult(expectation.index, expectation.step.primitive, met, detail))

    def _expect_arg(self, expectation: Expectation, name: str, kind: type | tuple[type, ...],
                    default: Any = _REQUIRED) -> Any:
        """One argument of an `expect.*` step, read WITHOUT coercing it.

        Every argument here comes from the primitive schema, which `check_scenario`
        enforces before a run — so a missing or wrongly typed one means the scenario was
        never checked. That is an authoring fault, and it must read `inconclusive`, not
        `crashed`: coercing with `int(...)` or `str(...)` was the last of the F1 class,
        where a `ValueError` from a scenario's own data ended the run as a lab defect.
        """
        step = expectation.step
        if name not in step.args:
            if default is _REQUIRED:
                raise _step_error(expectation.index, step, f"the step declares no {name}",
                                  VIRTUAL_EXPECTATION_UNEVALUABLE)
            return default
        value = step.args[name]
        # `bool` is an `int` in Python and must never stand in for a count or a name.
        if type(value) is bool or not isinstance(value, kind):
            raise _step_error(expectation.index, step,
                              f"{name} is not a {getattr(kind, '__name__', 'valid value')} in this step",
                              VIRTUAL_EXPECTATION_UNEVALUABLE)
        return value

    async def _check_event_expectation(self, expectation: Expectation) -> None:
        step = expectation.step
        wanted = self._expect_arg(expectation, "event", str)
        low = self._expect_arg(expectation, "count_min", int, 1)
        high = self._expect_arg(expectation, "count_max", int, None)
        conversation_id = self.stack.runtime.runtime.conversation_id
        if not conversation_id:
            # Structural: with no conversation there is no evidence to be right or wrong about.
            raise _step_error(expectation.index, step, "no conversation was opened, so no Conversation Event exists",
                              VIRTUAL_EXPECTATION_UNEVALUABLE)
        count = await self._count_events(expectation, conversation_id, wanted)
        met = low <= count and (high is None or count <= high)
        self._record(expectation, met, f"{count} {wanted} event(s) recorded, expected "
                                       f"{low}..{high if high is not None else '*'}")

    async def _count_events(self, expectation: Expectation, conversation_id: str, wanted: str) -> int:
        """Count one event type over the whole conversation, by paging the event store.

        The store caps a page at `MAX_EVENT_PAGE_LIMIT`, and asking for more raises —
        which used to make EVERY `expect.event` step end `crashed`, met or not. Paging
        is therefore the contract, and so is refusing to answer from a partial scan: a
        conversation longer than `MAX_EVENT_PAGES` pages, or one whose window holds rows
        the store could not decode, yields a LOWER BOUND, and a count that may be short
        cannot say whether `count_min`/`count_max` holds. Both refuse with
        `testlab_virtual_expectation_unevaluable` ("could not measure") rather than
        judging the product on a truncated count.
        """
        events = self.stack.core.conversation_events
        count = 0
        cursor = 0
        for _ in range(MAX_EVENT_PAGES):
            page = await events.list_conversation_events(conversation_id, after_sequence=cursor,
                                                         limit=MAX_EVENT_PAGE_LIMIT)
            count += sum(1 for item in page.events if item.event.event_type.value == wanted)
            if page.skipped_rows:
                raise _step_error(expectation.index, expectation.step,
                                  f"{page.skipped_rows} Conversation Event row(s) could not be decoded, so the "
                                  f"{wanted} count is only a lower bound", VIRTUAL_EXPECTATION_UNEVALUABLE)
            if not page.has_more:
                return count
            cursor = page.next_cursor
        raise _step_error(expectation.index, expectation.step,
                          f"the conversation holds more than {MAX_EVENT_PAGES * MAX_EVENT_PAGE_LIMIT} events, so "
                          f"the {wanted} count is only a lower bound", VIRTUAL_EXPECTATION_UNEVALUABLE)

    def check_measured_expectations(self, metrics: Mapping[str, Any],
                                    assertion_outcomes: Mapping[str, str]) -> None:
        """Evaluate the `expect.metric` / `expect.assertion` steps against the final run evidence.

        An expectation that CAN be evaluated is recorded as an `ExpectationResult`,
        met or not: that is a product verdict, and the caller decides how to express
        it (a metric, or `require_expectations_met`). An expectation there is nothing
        to evaluate against raises `VirtualStepError` with
        `testlab_virtual_expectation_unevaluable`, which is "could not measure".
        """
        from jarvis.testlab.diagnostics import AssertionSpec, Comparator, AssertionOutcome, evaluate_assertion
        from jarvis.testlab.validation import TestLabError

        declared = {spec.name: spec for spec in self.context.diagnostic.metrics}
        for expectation in self.expectations:
            step = expectation.step
            if step.primitive == "expect.metric":
                name = self._expect_arg(expectation, "metric", str)
                comparator = self._expect_arg(expectation, "comparator", str)
                threshold = self._expect_arg(expectation, "threshold", (int, float))
                wanted = f"{comparator} {threshold!r}"
                if name not in declared:
                    raise _step_error(expectation.index, step,
                                      f"{name} is not declared by this diagnostic, so it can never be measured",
                                      VIRTUAL_EXPECTATION_UNEVALUABLE)
                try:
                    result = evaluate_assertion(
                        AssertionSpec(f"expect_step_{expectation.index}", name, Comparator(comparator),
                                      threshold, True),
                        declared[name], metrics.get(name))
                except (TestLabError, ValueError) as exc:
                    # An unknown comparator, or a threshold that does not fit the metric's unit.
                    # `check_scenario` refuses both before a run, so reaching this means the
                    # scenario was never checked: an AUTHORING fault, not a defect of the lab,
                    # and it must not read `crashed` (same class as the F1 page-limit defect).
                    raise _step_error(expectation.index, step,
                                      f"{name} cannot be compared as written ({getattr(exc, 'code', 'invalid')})",
                                      VIRTUAL_EXPECTATION_UNEVALUABLE) from None
                if result.outcome is AssertionOutcome.MISSING:
                    raise _step_error(expectation.index, step, f"{name} was never measured, so {wanted} cannot be "
                                                               "checked", VIRTUAL_EXPECTATION_UNEVALUABLE)
                self._record(expectation, result.outcome is AssertionOutcome.PASSED,
                             f"{name} measured {metrics.get(name)!r}, expected {wanted}")
            elif step.primitive == "expect.assertion":
                assertion_id = self._expect_arg(expectation, "assertion_id", str)
                expected = self._expect_arg(expectation, "outcome", str)
                observed = assertion_outcomes.get(assertion_id)
                if observed is None:
                    raise _step_error(expectation.index, step,
                                      f"assertion {assertion_id} was not evaluated by this run",
                                      VIRTUAL_EXPECTATION_UNEVALUABLE)
                self._record(expectation, observed == expected,
                             f"assertion {assertion_id} ended {observed!r}, expected {expected!r}")


#: Replay `addressing` vocabulary -> the classification the journal reports.
_ADDRESSING: Mapping[str, str] = {
    "certain": AddressingDecision.ADDRESSED.value,
    "uncertain": AddressingDecision.UNCERTAIN.value,
}

Handler = Callable[[VirtualExecutor, int, ScenarioStep], Awaitable[None] | None]

#: The primitive-to-harness mapping. Documented as a table in `docs/testlab.md`.
HANDLERS: Mapping[str, Handler] = {
    "user.turn": VirtualExecutor._handle_user_turn,
    "user.speech": VirtualExecutor._handle_user_speech,
    "user.interrupt": VirtualExecutor._handle_user_interrupt,
    "brain.hold": VirtualExecutor._handle_brain_hold,
    "brain.ready": VirtualExecutor._handle_brain_ready,
    "brain.release": VirtualExecutor._handle_brain_release,
    "scheduler.enqueue": VirtualExecutor._handle_scheduler_enqueue,
    "provider.output_started": VirtualExecutor._handle_provider_output_started,
    "provider.transcript_final": VirtualExecutor._handle_provider_transcript_final,
    "provider.output_done": VirtualExecutor._handle_provider_output_done,
    "provider.cancel_rejected": VirtualExecutor._handle_provider_cancel_rejected,
    "provider.session_closed": VirtualExecutor._handle_provider_session_closed,
    "owner.candidate": VirtualExecutor._handle_owner_candidate,
    "owner.rejected": VirtualExecutor._handle_owner_rejected,
    "owner.confirmed": VirtualExecutor._handle_owner_confirmed,
    "device.output_busy": VirtualExecutor._handle_device_output_busy,
    "device.consume": VirtualExecutor._handle_device_consume,
    "device.release": VirtualExecutor._handle_device_release,
    "control.stop": VirtualExecutor._handle_control_stop,
    "control.checkpoint": VirtualExecutor._handle_control_checkpoint,
    "time.wait": VirtualExecutor._handle_time_wait,
    "parameter.override": VirtualExecutor._handle_parameter_override,
    "expect.event": VirtualExecutor._handle_expect,
    "expect.metric": VirtualExecutor._handle_expect,
    "expect.assertion": VirtualExecutor._handle_expect,
}
#: Names of the primitives this executor performs (`missing_handlers` argument).
HANDLED = frozenset(HANDLERS)


def unhandled_virtual_primitives() -> tuple[str, ...]:
    """Virtual primitives with no handler. Empty is the Slice 06 contract; a test pins it."""
    return missing_handlers(DEFAULT_PRIMITIVES, ProfileName.VIRTUAL, HANDLED)
