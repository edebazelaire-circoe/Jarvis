"""The `live` profile runners: a REAL provider session behind capability, budget and opt-in gates.

Binding contract: `docs/testlab.md` ("Live profile"). The `live` profile is the
`audio` profile with one thing swapped: the deterministic Realtime double becomes
a real provider session. Everything else — the production writer, the production
duplex capture and the real echo canceller — is identical, so a difference between
an `audio` run and a `live` run of the same diagnostic is a difference the PROVIDER
made.

Two registrations:

- `voice.queue_latency.live` — the seed latency diagnostic against the real
  provider, which is the one thing the `virtual` profile explicitly cannot
  measure: "the provider's own generation latency, its jitter and its cancel
  behaviour are the `live` profile's" (docs/testlab.md).
- `testlab.scenario.live` — the generic scenario runner.

Cost is measured, not assumed: the runner folds the `voice.realtime.usage` lines
the session emits and recomputes the estimate on every update, aborting with
`CostBudgetExceeded` the moment it crosses the run's budget. Provider, model,
voice, config fingerprint, usage and estimate are committed as a bounded JSON
report artifact.

**This file has never been run against a real provider.** Slice 08 implements and
tests it with doubles; the first real execution is the human gate of Slices 09
and 12.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any

from jarvis.domain.v2 import SpeechKind
from jarvis.testlab.audio.chain import InjectedSourceAudio, build_capture, chain_metadata
from jarvis.testlab.audio.fixtures import VOICE_SAMPLE_RATE
from jarvis.testlab.audio.runners import AudioExecutor, AudioInjector, AUDIO_SCENARIO_METRICS
from jarvis.testlab.diagnostics import MetricValue
from jarvis.testlab.live.cost import USAGE_KIND, CostBudget, CostBudgetExceeded, CostModel
from jarvis.testlab.live.session import LiveGateError, ProviderIdentity, factory_or_refuse, resolve_identity
from jarvis.testlab.runners import MeasurementUnavailable, RunContext, RunOutcome
from jarvis.testlab.runs import ArtifactKind
from jarvis.testlab.virtual.harness import VoiceStack
from jarvis.testlab.virtual.runners import (
    latency_metrics,
    speech_lines,
    close_session,
    commit_trace,
    expectation_metrics,
    open_session,
    submit_user_turn,
    wait_condition,
    virtual_voice_stack,
)

LIVE_RUN_FAILED = "testlab_live_run_failed"
METADATA_ARTIFACT = "live_profile.json"
METADATA_SCHEMA = "jarvis.testlab.provider_metadata"
METADATA_SCHEMA_VERSION = 1


class LiveRunError(MeasurementUnavailable):
    """The real provider could not be brought to a state this diagnostic can measure.

    `MeasurementUnavailable` -> `inconclusive`: a provider that refused the session,
    a session that never produced audio, a turn that never came back. Those are
    facts about the provider on the day, not defects of the lab, and reading them as
    `crashed` would bury a real finding under a false one.
    """


def _failed(detail: str) -> LiveRunError:
    return LiveRunError(LIVE_RUN_FAILED, detail)


class UsageWatcher:
    """Feeds every `voice.realtime.usage` journal line to the budget, and aborts on a crossing.

    Attached to the journal the stack already writes, so it observes exactly the
    lines a `DiagnosticBundle` would later read — no second accounting path that
    could disagree with the evidence.
    """

    __slots__ = ("budget", "_seen", "_journal")

    def __init__(self, budget: CostBudget, journal: Any) -> None:
        self.budget = budget
        self._journal = journal
        self._seen = 0

    def poll(self) -> None:
        """Fold the usage lines that appeared since the last poll. Raises `CostBudgetExceeded`."""
        lines = self._journal.lines(USAGE_KIND)
        fresh, self._seen = lines[self._seen:], len(lines)
        for line in fresh:
            self.budget.observe(line.data)


def write_metadata(context: RunContext, identity: ProviderIdentity, budget: CostBudget,
                   chain: Mapping[str, Any], extra: Mapping[str, Any] | None = None) -> None:
    """Commit provider identity, configuration identity, usage and cost as one report artifact."""
    document: dict[str, Any] = {"schema": METADATA_SCHEMA, "schema_version": METADATA_SCHEMA_VERSION,
                                "run_id": context.run_id, "provider": identity.to_dict(),
                                "cost": budget.to_dict(), "chain": dict(chain)}
    if extra:
        document.update(extra)
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    context.put_artifact(METADATA_ARTIFACT, kind=ArtifactKind.REPORT, media_type="application/json", data=payload)


#: Where the run's settings copy lives, and the key the Control Center keeps prices under.
SETTINGS_FILE_NAME = "control-center-settings.json"
PRICING_SETTING = "live_pricing"
#: A settings copy is a small JSON document; anything larger is not one of ours.
MAX_SETTINGS_BYTES = 1024 * 1024


def read_pricing(context: RunContext) -> object:
    """The `live_pricing` setting of THIS run, from the settings copy in its own scratch.

    One source, the one the Control Center already writes and the Live status surface
    already reads. Not a diagnostic parameter: a price is configuration of the
    workstation, not an input of the experiment, and making every priced diagnostic
    declare a parameter would put the same number in every manifest.
    """
    path = Path(context.runtime_dir) / SETTINGS_FILE_NAME
    try:
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            context.log("the run settings copy is too large to read for pricing; the run is unpriced")
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Captured with its cause: an unreadable settings copy makes the run UNPRICED,
        # which is recorded and visible, never an invented number.
        context.log(f"no usable pricing in the run settings copy ({type(exc).__name__}); the run is unpriced")
        return None
    return document.get(PRICING_SETTING) if isinstance(document, dict) else None


def build_budget(context: RunContext, identity: ProviderIdentity) -> CostBudget:
    """The mid-run budget of this run: the profile's declared ceiling and the configured price.

    The ceiling comes from the DECLARATION the run was queued against, which the
    caller's grant already had to cover; the runner cannot widen it.
    """
    profile = context.diagnostic.profiles[context.profile]
    model = CostModel.from_settings(identity.model_id, read_pricing(context))
    return CostBudget(max_cost_usd=float(profile.cost.max_cost_usd), model=model)


@asynccontextmanager
async def live_voice_stack(context: RunContext, *, session_factory: Any = None, echo_cancellation: bool = True):
    """Mount the voice path with the production audio chain AND a real provider session.

    `session_factory` is the injection seam: `None` builds the real OpenAI factory
    after checking the gates, and the default test suite passes a double, which is
    how every path below is covered without spending anything.
    """
    identity = resolve_identity(config_fingerprint=None)
    factory = session_factory
    if factory is None:
        try:
            factory = factory_or_refuse(identity, log=context.log)
        except LiveGateError as exc:
            # Re-raised as "could not measure", with the real cause kept: a live run
            # without its opt-in learned nothing about the product.
            raise LiveRunError(exc.code, exc.detail) from exc
    build = build_capture(capture_rate=VOICE_SAMPLE_RATE, render_rate=VOICE_SAMPLE_RATE,
                          echo_cancellation=echo_cancellation)
    context.log(f"live chain: provider={identity.provider} model={identity.model_id} aec={build.aec_engaged}")
    async with virtual_voice_stack(context, capture_factory=lambda: build.capture,
                                   audio_class=InjectedSourceAudio,
                                   realtime_factory=factory) as (stack, journal, core_journal):
        yield stack, journal, core_journal, build, identity



async def arm_session(context: RunContext, stack: VoiceStack, journal: Any) -> None:
    """Overridable seam: hand the run's journal to a provider DOUBLE, once the session is open.

    A real provider session needs nothing here. A test double needs the journal to
    emit the `voice.realtime.usage` lines a real session emits, which is what lets the
    whole cost path — folding, estimating, the mid-run abort and the metadata — be
    proven without spending anything. Nothing in a real run overrides it.
    """
    arm = getattr(stack.session, "arm_usage", None)
    if callable(arm):
        arm(journal)
        context.log("provider double armed with the run journal (no real provider in this run)")


# --------------------------------------------------- voice.queue_latency.live

@dataclass(frozen=True, slots=True)
class QueueLatencyLiveRunner:
    """`voice.queue_latency` against the real provider: the delays are the provider's own.

    The virtual seed measures the SCHEDULER's delays on a controlled clock. Here the
    same joins are measured while a real session generates the audio, so
    `speech.started_to_first_audio_ms` is real generation latency and
    `user_turn.end_to_first_audio_ms` is a real end-to-end number.
    """

    #: The session factory. `None` means the real provider; a test passes a double.
    session_factory: Any = None

    async def run(self, context: RunContext) -> RunOutcome:
        count = int(context.parameters["speech.request_count"])
        think_s = int(context.parameters["brain.result_delay_ms"]) / 1000
        async with live_voice_stack(context, session_factory=self.session_factory) as (
                stack, journal, _core, build, identity):
            budget = build_budget(context, identity)
            watcher = UsageWatcher(budget, journal)
            await open_session(context, stack)
            await arm_session(context, stack, journal)
            identity = _with_session(identity, stack)
            handle = await submit_user_turn(context, stack, "jarvis donne moi les quatre points du jour")
            await handle.start_work("latency", label="latency")
            # The same real wait as the virtual seed, for the same reason: it is the
            # quantity `user_turn.end_to_first_audio_ms` measures.
            await context.sleep(think_s)
            for index in range(count):
                context.check_cancelled()
                request = await handle.say(f"point {index + 1} de la reponse du jour",
                                           kind=SpeechKind.RESULT, work_id="latency")
                await wait_condition(context, lambda: bool(speech_lines(journal, "voice.speech.started", request.id)),
                                     f"speech {index + 1} starting")
                # The difference from the virtual seed, and the whole point of this
                # profile: nothing here plays the audio or closes the output. The real
                # provider does both, and how long it takes is the measurement.
                await wait_condition(
                    context,
                    lambda: bool(speech_lines(journal, "voice.latency.provider_first_pcm", request.id)),
                    f"the real provider's first PCM for speech {index + 1}")
                watcher.poll()
                await wait_condition(context,
                                     lambda: bool(speech_lines(journal, "voice.speech.completed", request.id)),
                                     f"speech {index + 1} completing at the provider")
                watcher.poll()
            handle.finish(public_summary="")
            metrics = latency_metrics(journal)
            chain = chain_metadata(context.profile.value, build, stack.audio).to_dict()
            context.log(f"live latency: {metrics} usage={budget.usage.to_dict()} cost={budget.cost_usd} "
                        f"basis={budget.model.basis}")
            await close_session(context, stack)
        watcher.poll()
        write_metadata(context, identity, budget, chain)
        await commit_trace(context, journal)
        if "speech.started_to_first_audio_ms" not in metrics:
            raise _failed("the real provider relayed no audio for any speech, so no latency could be measured")
        return RunOutcome(metrics=metrics)


def _with_session(identity: ProviderIdentity, stack: VoiceStack) -> ProviderIdentity:
    from jarvis.testlab.live.session import require_session_id

    return replace(identity, session_id=require_session_id(stack.session))


# ------------------------------------------------------- testlab.scenario.live

@dataclass(frozen=True, slots=True)
class LiveScenarioRunner:
    """Generic scenario runner of the `live` profile: the audio executor over a real session."""

    session_factory: Any = None

    async def run(self, context: RunContext) -> RunOutcome:
        scenario = context.scenario
        if scenario is None:
            raise _failed("the generic live runner needs a scenario; this run carried none")
        declared = {spec.name for spec in context.diagnostic.metrics}
        unmeasurable = sorted(declared - set(AUDIO_SCENARIO_METRICS))
        if unmeasurable:
            raise _failed(f"the generic live runner cannot measure {unmeasurable}; declare a specialized "
                          "implementation for this diagnostic")
        async with live_voice_stack(context, session_factory=self.session_factory) as (
                stack, journal, _core, build, identity):
            budget = build_budget(context, identity)
            watcher = UsageWatcher(budget, journal)
            injector = AudioInjector(stack)
            await open_session(context, stack)
            await arm_session(context, stack, journal)
            identity = _with_session(identity, stack)
            executor = AudioExecutor(stack=stack, context=context, journal=journal, injector=injector)
            try:
                await executor.run(scenario)
            finally:
                # Whatever the scenario did, the spend it caused is folded and recorded.
                # A budget crossing raised here replaces a step failure on purpose: the
                # run must stop costing money before anything else is reported.
                watcher.poll()
            metrics: dict[str, MetricValue] = {
                "scenario.steps_performed": len(scenario.steps),
                "scenario.checkpoints_reached": len(executor.checkpoints),
                "audio.injected_block_count": injector.audio.injected_blocks,
                "audio.injected_ms": injector.injected_ms,
            }
            executor.check_measured_expectations(metrics, {})
            metrics.update(expectation_metrics(context, executor))
            chain = chain_metadata(context.profile.value, build, injector.audio).to_dict()
            chain["injected"] = [report.to_dict() for report in injector.reports]
            await close_session(context, stack)
        write_metadata(context, identity, budget, chain)
        await commit_trace(context, journal)
        return RunOutcome(metrics={name: value for name, value in metrics.items() if name in declared})


__all__ = ["CostBudgetExceeded", "LiveRunError", "LiveScenarioRunner", "QueueLatencyLiveRunner", "UsageWatcher",
           "arm_session", "build_budget", "live_voice_stack", "write_metadata"]
