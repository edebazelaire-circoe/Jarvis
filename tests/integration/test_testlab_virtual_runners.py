"""The `virtual` runners against the real production voice path, in this process.

No subprocess here: the supervisor + worker path is
`tests/integration/test_testlab_virtual_runs.py`, and this file proves what a worker
cannot show cheaply — that each seed's assertions actually FAIL when the defect they
watch for is present, that a cancel stops a run cooperatively, that a step the harness
cannot perform fails loudly, and that the journal a run leaves behind has the session
shape a DiagnosticBundle needs.

Every fault is injected through a documented seam of the runner it belongs to; no
production branch exists for a fault.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from jarvis.domain.conversation_events import to_event_time
from jarvis.testlab.bundle_builder import SessionSelector
from jarvis.testlab.bundle_capture import capture_diagnostic_bundle
from jarvis.testlab.catalog import load_catalog
from jarvis.testlab.diagnostics import assertions_verdict, evaluate_assertion, resolve_parameters
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runners import RunArtifacts, RunCancelled, RunContext
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.validation import TestLabError
from jarvis.testlab.virtual.executor import VIRTUAL_STEP_FAILED, VirtualStepError
from jarvis.testlab.virtual.runners import (
    PayloadIntegrityRunner,
    QueueLatencyRunner,
    ScenarioRunner,
    SelfEchoRunner,
    StaleSupersessionRunner,
)
from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun
from jarvis.testlab.identity import format_run_id
from tests.fakes.testlab import CONFIG, ENVIRONMENT, NONCE, REVISION, T0

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "jarvis" / "testlab" / "official"
RUN_ID = format_run_id(T0, NONCE)
#: One in-process run is seconds; the budget only has to be far from a hang.
RUN_BUDGET_S = 120.0


def _entry(diagnostic_id: str, version: int | None = None):
    """One published version, the latest by default (what a versionless request resolves to)."""
    return load_catalog(CATALOG_ROOT, implementations=catalog_implementations()).describe(diagnostic_id, version)


def build_context(tmp_path: Path, diagnostic_id: str, *, parameters=None, scenario="manifest",
                  budget_s: float = RUN_BUDGET_S, overrides=None, version: int | None = None) -> RunContext:
    """A `RunContext` on a real run store, exactly as a worker builds one."""
    entry = _entry(diagnostic_id, version)
    spec = entry.diagnostic
    parameters = resolve_parameters(spec.parameters, dict(parameters or {}))
    store = FilesystemTestRunStore(tmp_path / "store")
    store.create_run(TestRun(run_id=RUN_ID, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                             profile=ProfileName.VIRTUAL, status=RunStatus.QUEUED, created_at=T0,
                             code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                             diagnostic_fingerprint=spec.fingerprint(), parameters=parameters,
                             environment=ENVIRONMENT))
    runtime_dir, data_root = tmp_path / "runtime", tmp_path / "data"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    return RunContext(
        run_id=RUN_ID, diagnostic=spec, profile=ProfileName.VIRTUAL,
        parameters=parameters, overrides=dict(overrides or {}),
        scenario=entry.manifest.scenario if scenario == "manifest" else scenario,
        runtime_dir=runtime_dir, data_root=data_root,
        artifacts=RunArtifacts(store, RUN_ID), cancelled=asyncio.Event(),
        deadline=asyncio.get_running_loop().time() + budget_s, log=lambda message: None)


def stored_run_for(context: RunContext, metrics) -> TestRun:
    """The terminal record the SUPERVISOR would store from these metrics, for reading its shape."""
    from jarvis.testlab.runs import complete_run, transition_run
    from jarvis.testlab.supervisor import derive_assertion_results

    spec = context.diagnostic
    queued = TestRun(run_id=RUN_ID, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                     profile=ProfileName.VIRTUAL, status=RunStatus.QUEUED, created_at=T0,
                     code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                     diagnostic_fingerprint=spec.fingerprint(), parameters=context.parameters,
                     environment=ENVIRONMENT)
    running = transition_run(queued, RunStatus.RUNNING, at=T0)
    return complete_run(running, at=T0, assertion_results=derive_assertion_results(spec, dict(metrics)),
                        metrics=dict(metrics))


def verdict_of(context: RunContext, metrics) -> tuple[str, dict[str, str]]:
    """The verdict the SUPERVISOR would derive from these metrics (never the runner's)."""
    values = dict(metrics)
    by_name = {metric.name: metric for metric in context.diagnostic.metrics}
    results = [evaluate_assertion(assertion, by_name[assertion.metric], values.get(assertion.metric))
               for assertion in context.diagnostic.assertions]
    return assertions_verdict(results).value, {result.assertion_id: result.outcome.value for result in results}


# ------------------------------------------------------------ failure paths

class _RealBargeInSelfEcho(SelfEchoRunner):
    """Fault: a genuine near-end voice the canceller separated, so the guard opens and Jarvis is cut."""

    async def inject_echo_candidate(self, context, stack):
        stack.audio.capture.speak_over()
        await stack.session.interrupt()


async def test_voice_self_echo_passes_and_fails_when_a_barge_in_is_really_confirmed(tmp_path):
    good = await SelfEchoRunner().run(build_context(tmp_path / "ok", "voice.self_echo",
                                                    parameters={"output.duration_ms": 1000,
                                                                "echo.candidate_count": 3}))
    context = build_context(tmp_path / "ko", "voice.self_echo",
                            parameters={"output.duration_ms": 1000, "echo.candidate_count": 1})
    bad = await _RealBargeInSelfEcho().run(context)

    assert dict(good.metrics)["barge_in.false_confirmed_count"] == 0
    assert dict(good.metrics)["barge_in.rejected_count"] == 3
    assert dict(good.metrics)["output.completed"] is True
    assert verdict_of(context, good.metrics)[0] == "passed"

    assert dict(bad.metrics)["barge_in.false_confirmed_count"] >= 1
    assert dict(bad.metrics)["output.completed"] is False
    outcome, results = verdict_of(context, bad.metrics)
    assert outcome == "failed"
    assert results == {"no_false_barge_in": "failed", "output_completes": "failed"}


class _CorruptedSurfacePayload(PayloadIntegrityRunner):
    """Fault: the surface delivered other words than the brain scripted."""

    async def after_delivery(self, context, stack, request):
        from dataclasses import replace

        stack.session.spoken[-1] = replace(request, text="des mots que le cerveau n a jamais demandes")


async def test_speech_payload_integrity_passes_and_fails_on_a_corrupted_payload(tmp_path):
    context = build_context(tmp_path / "ok", "speech.payload_integrity",
                            parameters={"speech.request_count": 2})
    good = await PayloadIntegrityRunner().run(context)
    bad = await _CorruptedSurfacePayload().run(build_context(tmp_path / "ko", "speech.payload_integrity",
                                                             parameters={"speech.request_count": 2}))

    assert dict(good.metrics) == {"speech.scripted_count": 2, "speech.delivered_count": 2,
                                  "speech.payload_mismatch_count": 0, "speech.replayed_payload_count": 0,
                                  "speech.undelivered_count": 0}
    assert verdict_of(context, good.metrics)[0] == "passed"

    assert dict(bad.metrics)["speech.payload_mismatch_count"] == 2
    outcome, results = verdict_of(context, bad.metrics)
    assert outcome == "failed" and results["payload_is_faithful"] == "failed"


#: The incident shape without the revision that makes the answer stale: nothing is ever
#: delivered, so the latest intent never speaks. Authored with the same primitives.
NEVER_DELIVERED = Scenario(
    scenario_id="stale_ack_never_released", title="An acknowledgement nobody releases",
    description="The busy output is never released, so the queued candidate never speaks.",
    steps=(
        ScenarioStep("device.output_busy", {"at_ms": 0, "output_id": "prior-output"}),
        ScenarioStep("scheduler.enqueue", {"at_ms": 0, "candidate_id": "old-ack", "kind": "ack",
                                           "intent_id": "intent-old", "intent_epoch": 1, "ttl_ms": 60000}),
        ScenarioStep("control.checkpoint", {"at_ms": 2000, "checkpoint_id": "queue_settled"}),
    ))


async def test_speech_stale_supersession_passes_the_seed_and_fails_an_undelivered_intent(tmp_path):
    """Pinned to v1: the four measurements of the situation itself, without the v2 expectation pair."""
    context = build_context(tmp_path / "ok", "speech.stale_supersession", version=1)
    good = await StaleSupersessionRunner().run(context)
    bad = await StaleSupersessionRunner().run(
        build_context(tmp_path / "ko", "speech.stale_supersession", version=1, scenario=NEVER_DELIVERED))

    assert dict(good.metrics) == {"speech.superseded_count": 1, "speech.stale_delivered_count": 0,
                                  "speech.latest_intent_delivered": True, "speech.stale_wait_ms": 28000}
    assert verdict_of(context, good.metrics)[0] == "passed"

    assert dict(bad.metrics)["speech.latest_intent_delivered"] is False
    outcome, results = verdict_of(context, bad.metrics)
    assert outcome == "failed" and results["latest_intent_wins"] == "failed"


def _v3_scenario_without_the_late_answer() -> Scenario:
    """v3's own situation with the durable answer of the past intent never enqueued.

    That is the defect `carried_over_answer_spoken` watches for, expressed as data: the
    brain's answer never reaches the surface, so there is nothing to carry over. Nothing
    else changes — the acknowledgement still dies, the current answer is still spoken.
    """
    shipped = _entry("speech.stale_supersession", 3).manifest.scenario
    steps = tuple(step for step in shipped.steps
                  if step.args.get("candidate_id") != "old-result")
    return Scenario("stale_ack_and_no_late_answer", steps, title="The late answer never arrives",
                    description="v3's situation, with the durable answer of the past intent missing.",
                    provenance=shipped.provenance)


async def test_speech_stale_supersession_v3_carries_the_answer_over_and_fails_without_it(tmp_path):
    """v3: the stale ACK is buried, the stale ANSWER is spoken, and both halves are measured.

    The two counts come from one journal: `stale_delivered_count` is the transient
    population (the acknowledgement, which must never speak) and
    `carried_over_delivered_count` the durable one (the answer, which must). Drop the
    answer from the situation and the new blocking assertion fails — which is the only
    thing that makes it a measurement rather than a sentence.
    """
    context = build_context(tmp_path / "ok", "speech.stale_supersession", version=3)
    good = await StaleSupersessionRunner().run(context)
    bad = await StaleSupersessionRunner().run(
        build_context(tmp_path / "ko", "speech.stale_supersession", version=3,
                      scenario=_v3_scenario_without_the_late_answer()))

    assert dict(good.metrics) == {"speech.superseded_count": 1, "speech.stale_delivered_count": 0,
                                  "speech.carried_over_delivered_count": 1,
                                  "speech.latest_intent_delivered": True, "speech.stale_wait_ms": 28000,
                                  "scenario.expectations_declared": 2, "scenario.expectations_failed_count": 0}
    assert verdict_of(context, good.metrics)[0] == "passed"

    assert dict(bad.metrics)["speech.carried_over_delivered_count"] == 0
    assert dict(bad.metrics)["speech.stale_delivered_count"] == 0  # the acknowledgement is still buried
    assert dict(bad.metrics)["scenario.expectations_failed_count"] == 1
    outcome, results = verdict_of(context, bad.metrics)
    assert outcome == "failed" and results["carried_over_answer_spoken"] == "failed"
    assert results["no_stale_delivery"] == "passed" and results["latest_intent_wins"] == "passed"


class _SlowFirstAudio(QueueLatencyRunner):
    """Fault: the first audio of a started speech arrives past the declared threshold."""

    async def play_first_audio(self, context, stack):
        await asyncio.sleep(4.2)
        await super().play_first_audio(context, stack)


async def test_voice_queue_latency_passes_and_fails_when_the_first_audio_is_late(tmp_path):
    context = build_context(tmp_path / "ok", "voice.queue_latency",
                            parameters={"speech.request_count": 2, "brain.result_delay_ms": 0})
    good = await QueueLatencyRunner().run(context)
    bad = await _SlowFirstAudio().run(build_context(tmp_path / "ko", "voice.queue_latency",
                                                    parameters={"speech.request_count": 1,
                                                                "brain.result_delay_ms": 0}))

    assert dict(good.metrics)["speech.delivered_count"] == 2
    assert dict(good.metrics)["speech.queue_free_to_started_ms"] <= 3000
    assert verdict_of(context, good.metrics)[0] == "passed"

    assert dict(bad.metrics)["speech.started_to_first_audio_ms"] > 4000
    outcome, results = verdict_of(context, bad.metrics)
    assert outcome == "failed" and results["started_to_first_audio"] == "failed"


# ------------------------------------------------------- vacuity: no evidence

class _DeafToProviderVad(SelfEchoRunner):
    """A stack that never answers a provider onset, modelled at the stimulus seam.

    Dropping the onset is indistinguishable, from the runner's side, from a bridge that
    ignores `realtime.speech_started` entirely: nothing is confirmed and nothing is
    rejected. That is the shape QA reproduced by mutating the bridge.
    """

    async def inject_echo_candidate(self, context, stack):
        del context, stack


async def test_voice_self_echo_refuses_to_pass_when_the_stack_never_decides(tmp_path):
    """Two zero counts are not a clean bill of health: a stimulus with no answer is no evidence.

    Slice 07 reads that refusal as `measurement_unavailable` / `inconclusive` — the
    diagnostic saying it could not measure — instead of `runner_failed` / `crashed`,
    which claimed the lab had broken.
    """
    from jarvis.testlab.outcomes import RunOutcomeClass, outcome_of
    from jarvis.testlab.worker import runner_failure_code

    context = build_context(tmp_path, "voice.self_echo",
                            parameters={"output.duration_ms": 500, "echo.candidate_count": 1}, budget_s=20.0)
    with pytest.raises(TestLabError) as error:
        await _DeafToProviderVad().run(context)
    assert "barge-in decision" in error.value.detail
    assert "voice.barge_in_ignored" in error.value.detail
    code = runner_failure_code(error.value)
    assert code == "measurement_unavailable"
    assert outcome_of(RunStatus.ERRORED, code) is RunOutcomeClass.INCONCLUSIVE


class _NoProviderAudio(QueueLatencyRunner):
    """A run where no provider audio is ever relayed: the user hears nothing at all."""

    async def play_first_audio(self, context, stack):
        del context, stack


async def test_voice_queue_latency_is_inconclusive_when_no_audio_is_ever_delivered(tmp_path):
    """The worst stack must not score the best number: a missing join is omitted, not zero."""
    context = build_context(tmp_path, "voice.queue_latency",
                            parameters={"speech.request_count": 1, "brain.result_delay_ms": 0})
    outcome = await _NoProviderAudio().run(context)
    metrics = dict(outcome.metrics)
    assert "speech.started_to_first_audio_ms" not in metrics
    assert "user_turn.end_to_first_audio_ms" not in metrics
    assert metrics["speech.delivered_count"] == 0
    verdict, results = verdict_of(context, metrics)
    assert verdict == "inconclusive"
    assert results["started_to_first_audio"] == "missing"
    # Slice 07: the stored shape a caller reads, and a detail that names what was missing.
    from jarvis.testlab.outcomes import RunOutcomeClass, classify_run

    stored = stored_run_for(context, metrics)
    summary = classify_run(stored)
    assert summary.outcome is RunOutcomeClass.INCONCLUSIVE
    assert stored.failure.code == "assertions_inconclusive"
    assert stored.failure.detail == "no measurement for blocking assertion(s): started_to_first_audio"
    assert summary.missing_assertions == ("started_to_first_audio",)


# -------------------------------------------------- refusals, cancel, deadline

UNCONFIRMED_BARGE_IN = Scenario(
    scenario_id="owner_confirmation_that_never_comes", title="An owner confirmation the stack never makes",
    description="The scenario declares a confirmed barge-in; the production stack decides otherwise.",
    steps=(
        ScenarioStep("owner.candidate", {"at_ms": 0, "candidate_id": "cand-1"}),
        ScenarioStep("owner.confirmed", {"at_ms": 100, "candidate_id": "cand-1", "played_ms": 500}),
    ))


async def test_a_step_the_stack_does_not_perform_fails_the_run_with_a_named_step(tmp_path):
    """Never a silent pass: the step, the primitive and what was expected are in the error."""
    context = build_context(tmp_path, "speech.stale_supersession", scenario=UNCONFIRMED_BARGE_IN, budget_s=20.0)
    with pytest.raises(VirtualStepError) as error:
        await StaleSupersessionRunner().run(context)
    assert error.value.code == VIRTUAL_STEP_FAILED
    assert "steps[1] owner.confirmed" in error.value.detail
    assert "confirmed barge-in" in error.value.detail


OVERRIDE_PRELUDE = Scenario(
    scenario_id="override_prelude_only", title="A prelude the run never applied",
    description="The scenario overrides a setting; the run resolved another value.",
    steps=(
        ScenarioStep("parameter.override", {"at_ms": 0, "parameter": "speech.request_count", "value": 9}),
        ScenarioStep("control.checkpoint", {"at_ms": 0, "checkpoint_id": "prelude"}),
    ))


async def test_an_override_the_run_never_applied_fails_instead_of_being_ignored(tmp_path):
    context = build_context(tmp_path, "speech.stale_supersession", scenario=OVERRIDE_PRELUDE, budget_s=20.0)
    with pytest.raises(VirtualStepError) as error:
        await StaleSupersessionRunner().run(context)
    assert "parameter.override" in error.value.detail and "was not applied" in error.value.detail


async def test_the_generic_scenario_runner_refuses_a_diagnostic_it_cannot_measure(tmp_path):
    """A runner that cannot produce the declared metrics fails; it never stores an empty verdict."""
    context = build_context(tmp_path, "voice.self_echo", scenario=OVERRIDE_PRELUDE, budget_s=20.0)
    with pytest.raises(TestLabError) as error:
        await ScenarioRunner().run(context)
    assert "cannot measure" in error.value.detail
    assert "barge_in.false_confirmed_count" in error.value.detail


async def test_a_cancel_ends_a_run_cooperatively(tmp_path):
    """The run stops on `RunCancelled` well before any forced kill, and leaves nothing running."""
    context = build_context(tmp_path, "voice.self_echo",
                            parameters={"output.duration_ms": 120000, "echo.candidate_count": 0})

    async def cancel_soon() -> None:
        await asyncio.sleep(0.3)
        context.cancelled.set()

    canceller = asyncio.create_task(cancel_soon())
    started = asyncio.get_running_loop().time()
    with pytest.raises(RunCancelled):
        await SelfEchoRunner().run(context)
    await canceller
    assert asyncio.get_running_loop().time() - started < 30.0


async def test_an_exhausted_budget_ends_the_run_instead_of_hanging(tmp_path):
    """The deadline comes from the run, not from a fixed wall clock in the harness."""
    context = build_context(tmp_path, "speech.stale_supersession", scenario=UNCONFIRMED_BARGE_IN, budget_s=0.0)
    with pytest.raises(TestLabError) as error:
        await StaleSupersessionRunner().run(context)
    assert "run budget" in error.value.detail


# ----------------------------------------------------- journal / session shape

async def test_a_run_leaves_a_live_shaped_journal_that_a_bundle_segments_into_one_session(tmp_path):
    context = build_context(tmp_path, "speech.payload_integrity", parameters={"speech.request_count": 1})
    outcome = await PayloadIntegrityRunner().run(context)
    del outcome

    trace = context.runtime_dir / "trace.jsonl"
    lines = [json.loads(raw) for raw in trace.read_text(encoding="utf-8").splitlines()]
    kinds = [line["kind"] for line in lines]
    assert "voice.start" in kinds and "voice.connecting" in kinds and "voice.stop" in kinds
    assert kinds.index("voice.start") < kinds.index("voice.connecting") < kinds.index("voice.stop")
    assert all({"ts", "kind", "level", "message", "data"} <= set(line) for line in lines)
    session_ids = {line["data"].get("session_id") for line in lines} - {None}
    assert session_ids == {f"{RUN_ID}-s1"}

    # The trace is committed as evidence, byte for byte (the supervisor puts the ref on the record).
    assert [ref.path for ref in context.committed] == ["trace.jsonl"]
    assert context.committed[0].sha256 == hashlib.sha256(trace.read_bytes()).hexdigest()
    assert context.committed[0].kind.value == "trace_excerpt"

    result = await capture_diagnostic_bundle(SessionSelector(session_id=f"{RUN_ID}-s1"),
                                             captured_at=to_event_time(datetime.now(timezone.utc)),
                                             trace_path=trace)
    segments = result.bundle.document["coverage"]["segments"]
    assert segments["count"] == 1
    assert segments["items"][0]["session_id"] == f"{RUN_ID}-s1"
    assert result.bundle.document["coverage"]["warnings"] == ()


# ------------------------------------ expect.* as a verdict (Slice 07 rework F1/F3)

#: A Conversation Event type a one-turn scenario really records (probed, not guessed).
RECORDED_EVENT = "user.transcript.accepted"
WAKE_STEPS = (ScenarioStep("user.turn", {"at_ms": 0, "turn_id": "t1", "content_tag": "hello"}),
              ScenarioStep("control.checkpoint", {"at_ms": 400, "checkpoint_id": "settled"}))


def _metric(name, unit="count", direction="lower_better", description="QA metric"):
    from jarvis.testlab.diagnostics import MetricDirection, MetricSpec, MetricUnit

    return MetricSpec(name, MetricUnit(unit), MetricDirection(direction), description)


def expectation_spec(diagnostic_id: str, implementation: str, *extra, carries_count: bool):
    """An AD-HOC diagnostic whose expectations are (or are not) expressible as a metric.

    The specialized cases use the published `speech.stale_supersession` v1 and v2 instead,
    which is the real declaration pair and therefore the stronger evidence.
    """
    from jarvis.testlab.diagnostics import AssertionSpec, Comparator, DiagnosticSpec, ScoreContract
    from jarvis.testlab.profiles import CostBounds, ProfileSpec

    metrics = list(extra)
    assertions = [AssertionSpec("declared_metric_sane", metric.name, Comparator.GE, 0, True)
                  for metric in extra if metric.unit.value == "count"][:1]
    if carries_count:
        metrics.append(_metric("scenario.expectations_failed_count", description="Unmet scenario expectations."))
        assertions.append(AssertionSpec("expectations_met", "scenario.expectations_failed_count",
                                        Comparator.EQ, 0, True, "Every scenario expectation held."))
    return DiagnosticSpec(
        diagnostic_id=diagnostic_id, version=1, title="QA expectation probe",
        domain=diagnostic_id.split(".")[0], description="Built by the test to exercise the expect rule.",
        profiles={ProfileName.VIRTUAL: ProfileSpec(ProfileName.VIRTUAL, implementation, CostBounds(120, 0))},
        metrics=tuple(metrics), assertions=tuple(assertions), score=ScoreContract())


def context_for(tmp_path: Path, spec, scenario) -> RunContext:
    """`build_context`, for a declaration the catalog does not publish."""
    store = FilesystemTestRunStore(tmp_path / "store")
    store.create_run(TestRun(run_id=RUN_ID, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                             profile=ProfileName.VIRTUAL, status=RunStatus.QUEUED, created_at=T0,
                             code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                             diagnostic_fingerprint=spec.fingerprint(), parameters={}, environment=ENVIRONMENT))
    runtime_dir, data_root = tmp_path / "runtime", tmp_path / "data"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    return RunContext(run_id=RUN_ID, diagnostic=spec, profile=ProfileName.VIRTUAL, parameters={}, overrides={},
                      scenario=scenario, runtime_dir=runtime_dir, data_root=data_root,
                      artifacts=RunArtifacts(store, RUN_ID), cancelled=asyncio.Event(),
                      deadline=asyncio.get_running_loop().time() + RUN_BUDGET_S, log=lambda message: None)


def event_scenario(scenario_id: str, **args) -> Scenario:
    return Scenario(scenario_id, title="one expect event step", description="A recorded event type, counted.",
                    steps=(*WAKE_STEPS, ScenarioStep("expect.event", {"at_ms": 500, "event": RECORDED_EVENT,
                                                                      **args})))


def adhoc_spec(*, carries_count: bool):
    return expectation_spec("qa.adhoc", "testlab.scenario.virtual",
                            _metric("scenario.steps_performed", direction="neutral", description="Steps performed."),
                            carries_count=carries_count)


def stale_scenario(scenario_id: str, shipped, **args) -> Scenario:
    return Scenario(scenario_id, title="the shipped scenario plus one expectation",
                    description="The stale-supersession situation with an event expectation appended.",
                    steps=(*shipped.manifest.scenario.steps,
                           ScenarioStep("expect.event", {"at_ms": 36000, "event": RECORDED_EVENT, **args})),
                    provenance=shipped.manifest.scenario.provenance)


async def test_an_expect_event_step_actually_runs_and_is_met(tmp_path):
    """It used to raise on every path: `limit=1000` exceeds the store's own page cap.

    A met expectation must now be an ordinary measured 0, and the run must pass.
    """
    spec = adhoc_spec(carries_count=True)
    context = context_for(tmp_path, spec, event_scenario("qa_event_met", count_min=1, count_max=9))
    outcome = await ScenarioRunner().run(context)
    assert dict(outcome.metrics)["scenario.expectations_failed_count"] == 0
    verdict, outcomes = verdict_of(context, outcome.metrics)
    assert verdict == "passed" and outcomes["expectations_met"] == "passed"


async def test_an_expect_event_step_that_disagrees_fails_the_run(tmp_path):
    """The product verdict: an unmet expectation is a measured 1 and the run FAILS."""
    spec = adhoc_spec(carries_count=True)
    context = context_for(tmp_path, spec, event_scenario("qa_event_unmet", count_min=99))
    outcome = await ScenarioRunner().run(context)
    assert dict(outcome.metrics)["scenario.expectations_failed_count"] == 1
    verdict, outcomes = verdict_of(context, outcome.metrics)
    assert verdict == "failed" and outcomes["expectations_met"] == "failed"


async def test_a_trivially_satisfiable_expect_event_no_longer_crashes(tmp_path):
    """QA's sharpest repro: `count_min 0` cannot be unmet, yet it used to end `crashed`."""
    spec = adhoc_spec(carries_count=True)
    context = context_for(tmp_path, spec, event_scenario("qa_event_zero", count_min=0, count_max=99))
    outcome = await ScenarioRunner().run(context)
    assert dict(outcome.metrics)["scenario.expectations_failed_count"] == 0


async def test_a_specialized_runner_carries_an_unmet_expectation_as_a_verdict(tmp_path):
    """F3: the rule is a property of the DECLARATION, not of the runner.

    A `speech.stale_supersession`-shaped diagnostic that declares the count metric fails
    on an unmet `expect.event`, instead of reporting "could not measure".
    """
    shipped = _entry("speech.stale_supersession", 2)
    context = context_for(tmp_path, shipped.diagnostic,
                          stale_scenario("qa_stale_unmet", shipped, count_min=99))
    outcome = await StaleSupersessionRunner().run(context)
    assert dict(outcome.metrics)["scenario.expectations_failed_count"] == 1
    verdict, outcomes = verdict_of(context, outcome.metrics)
    assert verdict == "failed" and outcomes["scenario_expectations_met"] == "failed"


async def test_a_specialized_runner_that_cannot_carry_the_count_is_inconclusive_by_design(tmp_path):
    """The shipped v1 declares no expectation metric, so an unmet one refuses the run."""
    from jarvis.testlab.outcomes import RunOutcomeClass, outcome_of
    from jarvis.testlab.runners import ScenarioExpectationUnmet
    from jarvis.testlab.worker import runner_failure_code

    shipped = _entry("speech.stale_supersession", 1)
    context = build_context(tmp_path, "speech.stale_supersession", version=1,
                            scenario=stale_scenario("qa_stale_v1_unmet", shipped, count_min=99))
    with pytest.raises(ScenarioExpectationUnmet) as failure:
        await StaleSupersessionRunner().run(context)
    code = runner_failure_code(failure.value)
    assert code == "scenario_expectation_unmet"
    assert outcome_of(RunStatus.ERRORED, code) is RunOutcomeClass.INCONCLUSIVE


async def test_a_specialized_runner_keeps_its_own_metrics_when_the_expectation_holds(tmp_path):
    """The expectation metrics are added, never instead of the diagnostic's own."""
    shipped = _entry("speech.stale_supersession", 2)
    v1_metrics = {item.name for item in _entry("speech.stale_supersession", 1).diagnostic.metrics}
    context = context_for(tmp_path, shipped.diagnostic, stale_scenario("qa_stale_met", shipped, count_min=0))
    outcome = await StaleSupersessionRunner().run(context)
    metrics = dict(outcome.metrics)
    assert metrics["scenario.expectations_failed_count"] == 0
    assert metrics["scenario.expectations_declared"] == 1
    assert set(metrics) >= v1_metrics
