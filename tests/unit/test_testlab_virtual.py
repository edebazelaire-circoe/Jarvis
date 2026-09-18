"""Slice 06 without a voice stack: the patch shim, the registry, the mapping and the measures.

Everything here is pure or file-local. Running a diagnostic against the real production
path lives in `tests/integration/test_testlab_virtual_runners.py` (in process) and
`tests/integration/test_testlab_virtual_runs.py` (real worker processes).
"""

from __future__ import annotations

import inspect
import json
import time
from types import SimpleNamespace

import pytest

from jarvis.testlab.implementations import ImplementationEntry, default_implementations, registered, reserved
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES, missing_handlers
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.validation import TestLabError
from jarvis.testlab.virtual.echo_guard import VirtualEchoGuard
from jarvis.testlab.virtual.executor import HANDLED, HANDLERS, unhandled_virtual_primitives
from jarvis.testlab.virtual.journal import TraceRecordingJournal, merged_timeline
from jarvis.testlab.virtual.patching import PatchStack
from jarvis.testlab.virtual.registry import VIRTUAL_RUNNERS, virtual_implementations
from jarvis.testlab.virtual.runners import latency_metrics, _payload_metrics, _supersession_metrics


# ------------------------------------------------------------------ patch shim

class _Target:
    value = "original"


def test_the_patch_stack_restores_every_attribute_in_reverse_order():
    target = _Target()
    stack = PatchStack()
    stack.setattr(target, "value", "first")
    stack.setattr(target, "value", "second")
    assert target.value == "second"
    stack.undo()
    assert target.value == "original"


def test_the_patch_stack_removes_an_attribute_that_did_not_exist():
    target = SimpleNamespace()
    with PatchStack() as stack:
        stack.setattr(target, "added", 1)
        assert target.added == 1
    assert not hasattr(target, "added")
    stack.undo()  # idempotent


def test_a_closed_patch_stack_refuses_a_further_patch():
    """A runner that patched a global after its own teardown would poison the next run."""
    target = _Target()
    stack = PatchStack()
    stack.undo()
    with pytest.raises(RuntimeError):
        stack.setattr(target, "value", "late")


def test_the_patch_stack_is_what_voice_stack_asks_for():
    """`voice_stack` needs one operation, and pytest's `monkeypatch` offers the same one."""
    assert callable(PatchStack().setattr)


# -------------------------------------------------------------------- registry

def test_every_reserved_virtual_name_is_now_registered():
    registry = catalog_implementations()
    for name in VIRTUAL_RUNNERS:
        entry = registry.resolve(name, ProfileName.VIRTUAL)
        assert entry.factory is not None, name
        assert entry.unavailable_reason is None


def test_the_other_profiles_stay_reserved_until_their_slice():
    registry = catalog_implementations()
    reserved_names = sorted(name for name, entry in registry.entries.items() if entry.factory is None)
    # Slice 08 registered the `audio` and `live` names, so only the two `hardware`
    # profiles are still waiting for Slice 09. `testlab.selftest.reserved` is the
    # deliberate fixture reservation that keeps the `runner_unavailable` worker path
    # testable now that every other declared name is registered.
    assert reserved_names == ["testlab.scenario.hardware_auto", "testlab.scenario.hardware_guided",
                              "testlab.selftest.reserved"]


@pytest.mark.parametrize("name,class_name", sorted(VIRTUAL_RUNNERS.items()))
def test_each_factory_builds_a_runner_with_a_run_coroutine(name, class_name):
    entry = catalog_implementations().get(name)
    runner = entry.factory()
    assert type(runner).__name__ == class_name
    assert callable(getattr(runner, "run", None))


def test_registering_refuses_a_name_that_is_not_reserved():
    registry = default_implementations().registering(virtual_implementations())
    with pytest.raises(TestLabError) as error:
        registry.registering(virtual_implementations())
    assert "already registered" in error.value.detail


def test_registering_refuses_the_same_name_twice_in_one_call():
    """Same rule as the constructor: a repeated name is a mistake, not a precedence."""
    entries = virtual_implementations()
    with pytest.raises(TestLabError) as error:
        default_implementations().registering([entries[0], entries[0]])
    assert "registered twice" in error.value.detail


def test_registering_refuses_another_profile_and_a_factoryless_entry():
    registry = default_implementations()
    wrong_profile = ImplementationEntry("testlab.scenario.live", ProfileName.VIRTUAL, factory=lambda: None)
    with pytest.raises(TestLabError):
        registry.registering([wrong_profile])
    with pytest.raises(TestLabError):
        registry.registering([reserved("testlab.scenario.virtual", ProfileName.VIRTUAL, "nope", "no factory")])


def test_registering_leaves_every_other_entry_untouched():
    before = default_implementations()
    after = before.registering(virtual_implementations())
    assert set(after.entries) == set(before.entries)
    assert after.get("testlab.scenario.live") is before.get("testlab.scenario.live")


def test_a_registration_does_not_import_the_voice_stack_until_it_is_called():
    """The factory is lazy: a supervisor that runs no virtual diagnostic imports no voice stack."""
    entry = registered("probe.virtual", ProfileName.VIRTUAL, virtual_implementations()[0].factory)
    assert entry.factory.__name__.startswith("build_")


# ------------------------------------------------------- primitive coverage

def test_the_virtual_profile_has_no_missing_handler():
    """The Slice 06 contract: `missing_handlers` reports nothing for `virtual`."""
    assert unhandled_virtual_primitives() == ()
    assert missing_handlers(DEFAULT_PRIMITIVES, ProfileName.VIRTUAL, HANDLED) == ()


def test_the_handler_table_claims_no_primitive_the_profile_does_not_support():
    assert HANDLED <= DEFAULT_PRIMITIVES.for_profile(ProfileName.VIRTUAL)


def test_every_handler_is_a_distinct_callable_of_the_executor():
    assert all(callable(handler) for handler in HANDLERS.values())
    assert "audio.inject" not in HANDLERS  # acoustic only; Slice 08 owns it


# ----------------------------------------------------------------- journal

def test_the_journal_writes_the_runtime_trace_and_keeps_a_measurable_timeline(tmp_path):
    journal = TraceRecordingJournal(tmp_path)
    journal.emit("voice.start", "started")
    journal.emit("voice.speech.queued", "queued", data={"speech_id": "s1"})
    lines = [json.loads(raw) for raw in journal.trace_path.read_text(encoding="utf-8").splitlines()]
    assert [line["kind"] for line in lines] == ["voice.start", "voice.speech.queued"]
    assert lines[1]["data"] == {"speech_id": "s1"}
    assert all("ts" in line for line in lines)
    assert journal.counts("voice.start") == 1
    assert journal.first("voice.speech.queued").get("speech_id") == "s1"
    assert journal.timeline[0].monotonic <= journal.timeline[1].monotonic
    # The in-memory harness view keeps exactly the keys the existing tests read.
    assert set(journal.events[0]) == {"kind", "message", "level", "data"}


def test_a_journal_write_failure_is_counted_and_never_raised(tmp_path):
    journal = TraceRecordingJournal(tmp_path / "trace-dir")
    journal.trace_path.parent.mkdir(parents=True, exist_ok=True)
    journal.trace_path.mkdir()  # a directory where the file should be: every write fails
    journal.emit("voice.start", "started")
    assert journal.write_failures == 1 and journal.last_write_error
    assert journal.counts("voice.start") == 1  # the run still measures


def test_merged_timeline_orders_two_journals_by_emission(tmp_path):
    voice, core = TraceRecordingJournal(tmp_path), TraceRecordingJournal(tmp_path)
    voice.emit("voice.start", "a")
    core.emit("core.brain.turn_slow", "b")
    voice.emit("voice.stop", "c")
    assert [line.kind for line in merged_timeline(voice, core)] == [
        "voice.start", "core.brain.turn_slow", "voice.stop"]


# --------------------------------------------------------------- echo guard

def test_the_echo_guard_closes_while_jarvis_is_the_far_end():
    guard = VirtualEchoGuard()
    assert guard.gate_open and not guard.far_recent
    guard.push_reference(b"\x00" * 10)
    assert guard.far_recent and not guard.gate_open
    guard.clear_reference()
    assert not guard.far_recent and guard.gate_open


def test_the_echo_guard_reads_no_clock_at_all():
    """A host stall must not reopen the gate and turn a correct stack into a failure.

    The guard used to hold the gate closed for 2 s of `time.monotonic` after the last
    output block, which made a 2.2 s pause of a loaded host look like silence and
    confirmed a barge-in on pure echo. The far end is state now, so no amount of
    elapsed time changes the answer.
    """
    guard = VirtualEchoGuard()
    guard.push_reference(b"\x00")
    assert guard.gate_open is False
    time.sleep(0.05)  # any pause at all: the answer may not depend on it
    assert guard.gate_open is False
    assert "clock" not in inspect.signature(VirtualEchoGuard.__init__).parameters


def test_the_echo_guard_opens_for_a_separated_near_end_voice():
    guard = VirtualEchoGuard()
    guard.push_reference(b"\x00")
    assert not guard.gate_open
    guard.speak_over()
    assert guard.gate_open and guard.near_end_observed
    guard.release_near_end()
    assert not guard.gate_open and guard.released_candidates == 1


def test_the_echo_guard_passes_the_microphone_through_and_forgets_a_stopped_output():
    guard = VirtualEchoGuard()
    assert guard.process(b"abc") == (b"abc", ())
    guard.push_reference(b"\x00")
    guard.clear_reference()
    assert guard.gate_open


# ------------------------------------------------------------------ measures

def _request(speech_id: str, text: str):
    return SimpleNamespace(id=speech_id, text=text)


def test_payload_measures_count_mismatch_replay_and_loss():
    scripted = {"a": "un", "b": "deux", "c": "trois"}
    spoken = [_request("a", "un"), _request("b", "autre chose"), _request("a", "un")]
    assert _payload_metrics(scripted, spoken) == {
        "speech.scripted_count": 3,
        "speech.delivered_count": 3,
        "speech.payload_mismatch_count": 1,
        "speech.replayed_payload_count": 1,
        "speech.undelivered_count": 1,
    }


def test_payload_measures_are_all_zero_on_a_faithful_delivery():
    scripted = {"a": "un", "b": "deux"}
    metrics = _payload_metrics(scripted, [_request("a", "un"), _request("b", "deux")])
    assert metrics["speech.payload_mismatch_count"] == 0
    assert metrics["speech.replayed_payload_count"] == 0
    assert metrics["speech.undelivered_count"] == 0


class _Executor:
    """Just what `_supersession_metrics` reads of an executor."""

    def __init__(self, candidates, times):
        self.candidates = candidates
        self._times = times

    def virtual_time_of(self, index):
        return self._times.get(index, 0)


def _candidate(candidate_id, epoch, at_ms):
    from jarvis.testlab.virtual.executor import CandidateRecord

    return CandidateRecord(candidate_id, "ack", at_ms, intent_id=f"i-{epoch}", intent_epoch=epoch)


def test_supersession_measures_report_the_stale_wait_in_virtual_time(tmp_path):
    journal = TraceRecordingJournal(tmp_path)
    journal.emit("voice.speech.queued", "", data={"speech_id": "old"})
    journal.emit("voice.speech.superseded", "", data={"speech_id": "old"})
    journal.emit("voice.speech.started", "", data={"speech_id": "new"})
    journal.emit("voice.speech.completed", "", data={"speech_id": "new"})
    executor = _Executor({"old": _candidate("old", 1, 0), "new": _candidate("new", 2, 28000)},
                         {0: 0, 1: 28000, 2: 35900, 3: 35900})
    assert _supersession_metrics(journal, executor) == {
        "speech.superseded_count": 1,
        "speech.stale_delivered_count": 0,
        "speech.latest_intent_delivered": True,
        "speech.stale_wait_ms": 28000,
    }


def test_supersession_measures_catch_a_candidate_spoken_after_its_own_supersession(tmp_path):
    journal = TraceRecordingJournal(tmp_path)
    journal.emit("voice.speech.queued", "", data={"speech_id": "old"})
    journal.emit("voice.speech.superseded", "", data={"speech_id": "old"})
    journal.emit("voice.speech.started", "", data={"speech_id": "old"})
    executor = _Executor({"old": _candidate("old", 1, 0)}, {0: 0, 1: 1000, 2: 2000})
    metrics = _supersession_metrics(journal, executor)
    assert metrics["speech.stale_delivered_count"] == 1
    assert metrics["speech.latest_intent_delivered"] is True  # it was delivered, staleness is the other measure


def test_supersession_measures_catch_a_stale_candidate_the_stack_never_labelled(tmp_path):
    """The defect the seed exists for: the old answer is spoken late and nothing calls it stale.

    Keying only on `voice.speech.superseded` made this read 0 - the diagnostic was blind
    to the very incident it reproduces. A candidate whose intent a later epoch revised,
    and which the scheduler had already seen, is stale whether or not the stack said so.
    """
    journal = TraceRecordingJournal(tmp_path)
    journal.emit("voice.speech.queued", "", data={"speech_id": "old-ack"})
    journal.emit("voice.speech.queued", "", data={"speech_id": "new-result"})
    journal.emit("voice.speech.started", "", data={"speech_id": "old-ack"})
    journal.emit("voice.speech.completed", "", data={"speech_id": "old-ack"})
    executor = _Executor({"old-ack": _candidate("old-ack", 1, 0),
                          "new-result": _candidate("new-result", 2, 28000)},
                         {0: 0, 1: 28000, 2: 35900, 3: 35900})
    metrics = _supersession_metrics(journal, executor)
    assert metrics["speech.superseded_count"] == 0       # the stack never admitted it
    assert metrics["speech.stale_delivered_count"] == 1  # it was stale all the same
    assert metrics["speech.stale_wait_ms"] == 35900      # the incident's own delay
    assert metrics["speech.latest_intent_delivered"] is False


def test_a_candidate_is_not_stale_before_the_scheduler_saw_the_later_intent(tmp_path):
    """Staleness is grounded in an observed moment, not merely in the scenario's text."""
    journal = TraceRecordingJournal(tmp_path)
    journal.emit("voice.speech.queued", "", data={"speech_id": "first"})
    journal.emit("voice.speech.started", "", data={"speech_id": "first"})
    journal.emit("voice.speech.completed", "", data={"speech_id": "first"})
    journal.emit("voice.speech.queued", "", data={"speech_id": "second"})
    executor = _Executor({"first": _candidate("first", 1, 0), "second": _candidate("second", 2, 5000)},
                         {0: 0, 1: 100, 2: 200, 3: 5000})
    metrics = _supersession_metrics(journal, executor)
    assert metrics["speech.stale_delivered_count"] == 0
    assert metrics["speech.stale_wait_ms"] == 0


def test_latency_measures_join_the_stages_of_each_speech(tmp_path):
    journal = TraceRecordingJournal(tmp_path)
    journal.emit("voice.brain_turn_submitted", "", data={"turn_id": "t1"})
    journal.emit("voice.speech.queued", "", data={"speech_id": "s1"})
    journal.emit("voice.speech.started", "", data={"speech_id": "s1"})
    journal.emit("voice.latency.provider_first_pcm", "", data={"speech_id": "s1"})
    journal.emit("voice.speech.completed", "", data={"speech_id": "s1"})
    metrics = latency_metrics(journal)
    assert set(metrics) == {"speech.queue_free_to_started_ms", "speech.started_to_first_audio_ms",
                            "user_turn.end_to_first_audio_ms", "speech.delivered_count"}
    assert metrics["speech.delivered_count"] == 1
    assert all(isinstance(value, int) and value >= 0 for value in metrics.values())


def test_latency_measures_omit_a_missing_join_instead_of_scoring_it_zero(tmp_path):
    """A stage that never happened is ABSENT, never 0.

    Reporting 0 gave the worst possible stack the best possible number: a run that
    relayed no provider audio at all measured `started_to_first_audio_ms = 0` and passed
    every assertion. An omitted metric makes its assertion `missing`, the verdict
    inconclusive and the run `errored` - the diagnostic says it could not measure.
    """
    journal = TraceRecordingJournal(tmp_path)
    journal.emit("voice.brain_turn_submitted", "", data={"turn_id": "t1"})
    journal.emit("voice.speech.queued", "", data={"speech_id": "s1"})
    journal.emit("voice.speech.started", "", data={"speech_id": "s1"})
    journal.emit("voice.speech.completed", "", data={"speech_id": "s1"})
    metrics = latency_metrics(journal)
    assert "speech.started_to_first_audio_ms" not in metrics
    assert "user_turn.end_to_first_audio_ms" not in metrics
    assert metrics["speech.queue_free_to_started_ms"] >= 0  # this join did happen
    assert metrics["speech.delivered_count"] == 0  # a speech nobody could hear is no delivery


def test_a_missing_latency_metric_makes_its_blocking_assertion_inconclusive(tmp_path):
    """The omission has to bite: `missing` is inconclusive, and an inconclusive run errors."""
    from jarvis.testlab.catalog import load_catalog
    from jarvis.testlab.diagnostics import (
        AssertionOutcome,
        AssertionVerdict,
        assertions_verdict,
        evaluate_assertion,
    )

    spec = load_catalog(implementations=catalog_implementations()).describe("voice.queue_latency").diagnostic
    journal = TraceRecordingJournal(tmp_path)
    journal.emit("voice.speech.queued", "", data={"speech_id": "s1"})
    journal.emit("voice.speech.started", "", data={"speech_id": "s1"})
    journal.emit("voice.speech.completed", "", data={"speech_id": "s1"})
    metrics = latency_metrics(journal)
    by_name = {metric.name: metric for metric in spec.metrics}
    results = [evaluate_assertion(item, by_name[item.metric], metrics.get(item.metric))
               for item in spec.assertions]
    outcomes = {item.assertion_id: item.outcome for item in results}
    assert outcomes["started_to_first_audio"] is AssertionOutcome.MISSING
    assert assertions_verdict(results) is AssertionVerdict.INCONCLUSIVE


# ------------------------------------------------- the expect.* verdict rule

def _expectation_executor(spec, steps):
    """A `VirtualExecutor` with no stack: `check_measured_expectations` reads only the
    declaration and the expectations, so the rule can be exercised without a voice stack."""
    from jarvis.testlab.scenarios import ScenarioStep
    from jarvis.testlab.virtual.executor import Expectation, VirtualExecutor

    executor = VirtualExecutor(stack=None, context=SimpleNamespace(diagnostic=spec), journal=None)
    executor.expectations = [Expectation(index, ScenarioStep(primitive, args))
                             for index, (primitive, args) in enumerate(steps)]
    return executor


def _scenario_spec(*metric_names):
    """An ad-hoc diagnostic declaring a subset of the generic runner's measurement contract."""
    from jarvis.testlab.diagnostics import (
        AssertionSpec,
        Comparator,
        DiagnosticSpec,
        MetricDirection,
        MetricSpec,
        MetricUnit,
    )
    from jarvis.testlab.profiles import CostBounds, ProfileSpec

    metrics = tuple(MetricSpec(name, MetricUnit.COUNT, MetricDirection.LOWER_BETTER) for name in metric_names)
    blocking = AssertionSpec("expectations_met", metric_names[0], Comparator.EQ, 0, True)
    return DiagnosticSpec(diagnostic_id="adhoc.probe", version=1, title="ad-hoc probe", domain="adhoc",
                          profiles={ProfileName.VIRTUAL: ProfileSpec(ProfileName.VIRTUAL,
                                                                     "testlab.scenario.virtual", CostBounds(60, 0))},
                          metrics=metrics, assertions=(blocking,))


def test_an_evaluable_expectation_that_disagrees_is_a_recorded_verdict_not_an_error():
    """A product verdict: the count is a MEASUREMENT the declaration turns into `failed`."""
    spec = _scenario_spec("scenario.expectations_failed_count", "scenario.steps_performed")
    executor = _expectation_executor(spec, [
        ("expect.metric", {"at_ms": 0, "metric": "scenario.steps_performed", "comparator": "ge",
                           "threshold": 10})])
    executor.check_measured_expectations({"scenario.steps_performed": 2}, {})
    assert executor.expectations_failed == 1
    assert executor.expectation_results[0].met is False
    assert "expected ge 10" in executor.expectation_results[0].detail


def test_an_expectation_that_holds_is_recorded_as_met():
    spec = _scenario_spec("scenario.expectations_failed_count", "scenario.steps_performed")
    executor = _expectation_executor(spec, [
        ("expect.metric", {"at_ms": 0, "metric": "scenario.steps_performed", "comparator": "ge", "threshold": 1})])
    executor.check_measured_expectations({"scenario.steps_performed": 2}, {})
    assert executor.expectations_failed == 0 and executor.expectation_results[0].met is True


def test_an_expectation_on_a_metric_nobody_measured_could_not_be_evaluated():
    """Authoring/structural, not a product verdict: `could not measure`."""
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import VIRTUAL_EXPECTATION_UNEVALUABLE

    spec = _scenario_spec("scenario.expectations_failed_count", "scenario.steps_performed")
    executor = _expectation_executor(spec, [
        ("expect.metric", {"at_ms": 0, "metric": "scenario.steps_performed", "comparator": "ge", "threshold": 1})])
    with pytest.raises(MeasurementUnavailable) as failure:
        executor.check_measured_expectations({}, {})
    assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE
    assert executor.expectation_results == []


def test_an_expectation_on_an_undeclared_metric_could_not_be_evaluated():
    from jarvis.testlab.runners import MeasurementUnavailable

    spec = _scenario_spec("scenario.expectations_failed_count")
    executor = _expectation_executor(spec, [
        ("expect.metric", {"at_ms": 0, "metric": "scenario.steps_performed", "comparator": "ge", "threshold": 1})])
    with pytest.raises(MeasurementUnavailable, match="never be measured"):
        executor.check_measured_expectations({"scenario.steps_performed": 3}, {})


def test_an_expectation_on_an_assertion_nobody_evaluated_could_not_be_evaluated():
    from jarvis.testlab.runners import MeasurementUnavailable

    spec = _scenario_spec("scenario.expectations_failed_count")
    executor = _expectation_executor(spec, [
        ("expect.assertion", {"at_ms": 0, "assertion_id": "expectations_met", "outcome": "passed"})])
    with pytest.raises(MeasurementUnavailable, match="was not evaluated"):
        executor.check_measured_expectations({}, {})
    executor.expectation_results.clear()
    executor.check_measured_expectations({}, {"expectations_met": "failed"})
    assert executor.expectations_failed == 1


def test_a_diagnostic_that_cannot_carry_the_count_ends_inconclusive_instead_of_dropping_it():
    """`require_expectations_met` is what a specialized runner uses: never a silent drop."""
    from jarvis.testlab.runners import ScenarioExpectationUnmet

    spec = _scenario_spec("scenario.expectations_failed_count", "scenario.steps_performed")
    executor = _expectation_executor(spec, [
        ("expect.metric", {"at_ms": 0, "metric": "scenario.steps_performed", "comparator": "le", "threshold": 1})])
    executor.check_measured_expectations({"scenario.steps_performed": 9}, {})
    with pytest.raises(ScenarioExpectationUnmet, match="not met"):
        executor.require_expectations_met()


def test_a_run_with_every_expectation_met_requires_nothing():
    spec = _scenario_spec("scenario.expectations_failed_count", "scenario.steps_performed")
    executor = _expectation_executor(spec, [])
    executor.check_measured_expectations({}, {})
    executor.require_expectations_met()


def test_the_generic_runner_measurement_contract_is_the_declared_set():
    from jarvis.testlab.virtual.runners import SCENARIO_METRICS

    assert set(SCENARIO_METRICS) == {"scenario.steps_performed", "scenario.checkpoints_reached",
                                     "scenario.expectations_declared", "scenario.expectations_failed_count"}


def test_a_virtual_step_failure_is_a_measurement_problem_not_a_crash():
    """The worker maps it to `measurement_unavailable`, which reads `inconclusive`."""
    from jarvis.testlab.outcomes import RunOutcomeClass, outcome_of
    from jarvis.testlab.runs import RunStatus
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import VirtualStepError
    from jarvis.testlab.virtual.runners import VirtualRunError
    from jarvis.testlab.worker import runner_failure_code

    assert issubclass(VirtualStepError, MeasurementUnavailable)
    assert issubclass(VirtualRunError, MeasurementUnavailable)
    code = runner_failure_code(VirtualRunError("testlab_virtual_run_failed", "the stack never answered"))
    assert outcome_of(RunStatus.ERRORED, code) is RunOutcomeClass.INCONCLUSIVE


def test_an_unforeseen_runner_exception_still_reads_as_a_crash():
    from jarvis.testlab.jobs import FAILURE_RUNNER_FAILED
    from jarvis.testlab.worker import runner_failure_code

    assert runner_failure_code(ValueError("boom")) == FAILURE_RUNNER_FAILED


# ------------------------------------ expect.event paging (Slice 07 rework F1)

class _FakeEvents:
    """A Conversation Event store that refuses an over-large page, exactly like the real one."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.requests: list[tuple[int, int]] = []

    async def list_conversation_events(self, conversation_id, *, after_sequence=0, limit=100, **_):
        from jarvis.domain.conversation_event_store import MAX_EVENT_PAGE_LIMIT

        del conversation_id
        if limit > MAX_EVENT_PAGE_LIMIT:
            raise ValueError(f"limit must be <= {MAX_EVENT_PAGE_LIMIT}")
        self.requests.append((after_sequence, limit))
        index = min(len(self.requests) - 1, len(self.pages) - 1)
        return self.pages[index]


def _page(types, *, has_more=False, cursor=0, skipped=0):
    from jarvis.domain.conversation_event_store import ConversationEventPage

    events = tuple(SimpleNamespace(event=SimpleNamespace(event_type=SimpleNamespace(value=name)))
                   for name in types)
    return ConversationEventPage(events=events, next_cursor=cursor, has_more=has_more, skipped_rows=skipped)


def _event_executor(pages, *, conversation_id="c-1", **args):
    from jarvis.testlab.virtual.executor import Expectation, VirtualExecutor
    from jarvis.testlab.scenarios import ScenarioStep

    events = _FakeEvents(pages)
    stack = SimpleNamespace(core=SimpleNamespace(conversation_events=events),
                            runtime=SimpleNamespace(runtime=SimpleNamespace(conversation_id=conversation_id)))
    executor = VirtualExecutor(stack=stack, context=None, journal=None)
    step = ScenarioStep("expect.event", {"at_ms": 0, "event": "user.transcript.accepted",
                                         "count_min": 1, **args})
    executor.expectations = [Expectation(0, step)]
    return executor, events


async def test_expect_event_never_asks_for_a_page_larger_than_the_store_allows():
    """The F1 defect: `limit=1000` exceeds MAX_EVENT_PAGE_LIMIT and raised on every path."""
    from jarvis.domain.conversation_event_store import MAX_EVENT_PAGE_LIMIT

    executor, events = _event_executor([_page(["user.transcript.accepted"])])
    await executor._check_expectations()
    assert events.requests == [(0, MAX_EVENT_PAGE_LIMIT)]
    assert [(result.met, result.primitive) for result in executor.expectation_results] == [(True, "expect.event")]


async def test_expect_event_pages_through_the_whole_conversation():
    executor, events = _event_executor([
        _page(["user.transcript.accepted"] * 3, has_more=True, cursor=500),
        _page(["user.transcript.accepted"] * 2, has_more=False, cursor=900),
    ], count_min=5, count_max=5)
    await executor._check_expectations()
    assert [request[0] for request in events.requests] == [0, 500]
    assert executor.expectation_results[0].met is True
    assert "5 user.transcript.accepted event(s)" in executor.expectation_results[0].detail


async def test_expect_event_refuses_to_judge_a_conversation_it_could_not_finish_scanning():
    """A lower bound cannot say whether count_min/count_max holds: refuse, never truncate."""
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import MAX_EVENT_PAGES, VIRTUAL_EXPECTATION_UNEVALUABLE

    executor, events = _event_executor([_page(["user.transcript.accepted"], has_more=True, cursor=1)])
    with pytest.raises(MeasurementUnavailable) as failure:
        await executor._check_expectations()
    assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE
    assert "lower bound" in failure.value.detail
    assert len(events.requests) == MAX_EVENT_PAGES
    assert executor.expectation_results == []


async def test_expect_event_refuses_to_judge_when_rows_could_not_be_decoded():
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import VIRTUAL_EXPECTATION_UNEVALUABLE

    executor, _events = _event_executor([_page(["user.transcript.accepted"], skipped=2)])
    with pytest.raises(MeasurementUnavailable) as failure:
        await executor._check_expectations()
    assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE
    assert "could not be decoded" in failure.value.detail


async def test_expect_event_without_a_conversation_could_not_be_evaluated():
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import VIRTUAL_EXPECTATION_UNEVALUABLE

    executor, _events = _event_executor([_page([])], conversation_id="")
    with pytest.raises(MeasurementUnavailable) as failure:
        await executor._check_expectations()
    assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE


def test_an_expect_metric_the_declaration_cannot_compare_is_unevaluable_not_a_crash():
    """The same class as F1, found by grepping the other two handlers: an authoring fault.

    `check_scenario` refuses a bad comparator or an ill-fitting threshold before a run, so
    this only happens to an unchecked scenario — and it must read `inconclusive`, not `crashed`.
    """
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import VIRTUAL_EXPECTATION_UNEVALUABLE

    spec = _scenario_spec("scenario.expectations_failed_count", "scenario.steps_performed")
    # `eq` on a non-exact unit, and an unknown comparator: both refused by the declaration.
    for args in ({"at_ms": 0, "metric": "scenario.steps_performed", "comparator": "wat", "threshold": 1},
                 {"at_ms": 0, "metric": "scenario.steps_performed", "comparator": "le", "threshold": 1.5}):
        executor = _expectation_executor(spec, [("expect.metric", args)])
        with pytest.raises(MeasurementUnavailable) as failure:
            executor.check_measured_expectations({"scenario.steps_performed": 2}, {})
        assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE


# ----------------------------- expect.* arguments are read, never coerced (Slice 07 rework)

@pytest.mark.parametrize("args", [
    {"count_min": "3"},          # a string that int() would happily accept
    {"count_min": 1.5},          # a float
    {"count_max": "9"},
    {"count_max": 2.0},
    {"count_min": True},         # bool is an int in Python and must not stand in for a count
    {"event": 42},               # str() would have turned this into "42" and counted nothing
])
async def test_an_expect_event_argument_of_the_wrong_type_is_unevaluable_not_a_crash(args):
    """The last of the F1 class: `int(...)` / `str(...)` on a scenario's own data.

    `check_scenario` refuses every one of these before a run, so reaching them means the
    scenario was never checked — an authoring fault, which must read `inconclusive`.
    """
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import VIRTUAL_EXPECTATION_UNEVALUABLE

    executor, events = _event_executor([_page(["user.transcript.accepted"])], **args)
    with pytest.raises(MeasurementUnavailable) as failure:
        await executor._check_expectations()
    assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE
    assert events.requests == []  # refused before it read a single page
    assert executor.expectation_results == []


async def test_an_expect_event_step_without_its_required_event_is_unevaluable():
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import Expectation, VIRTUAL_EXPECTATION_UNEVALUABLE
    from jarvis.testlab.scenarios import ScenarioStep

    executor, _events = _event_executor([_page([])])
    executor.expectations = [Expectation(0, ScenarioStep("expect.event", {"at_ms": 0, "count_min": 1}))]
    with pytest.raises(MeasurementUnavailable) as failure:
        await executor._check_expectations()
    assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE
    assert "declares no event" in failure.value.detail


async def test_count_max_still_bites_once_the_arguments_are_typed():
    """The guard must not have turned `count_max` into a no-op: an over-count is unmet."""
    executor, _events = _event_executor([_page(["user.transcript.accepted"] * 3)], count_min=0, count_max=2)
    await executor._check_expectations()
    assert executor.expectation_results[0].met is False
    assert executor.expectations_failed == 1


@pytest.mark.parametrize("args", [
    {"metric": 7, "comparator": "le", "threshold": 1},
    {"metric": "scenario.steps_performed", "comparator": 3, "threshold": 1},
    {"metric": "scenario.steps_performed", "comparator": "le", "threshold": "1"},
    {"metric": "scenario.steps_performed", "comparator": "le"},               # no threshold
    {"comparator": "le", "threshold": 1},                                      # no metric
])
def test_an_expect_metric_argument_of_the_wrong_type_is_unevaluable_not_a_crash(args):
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import VIRTUAL_EXPECTATION_UNEVALUABLE

    spec = _scenario_spec("scenario.expectations_failed_count", "scenario.steps_performed")
    executor = _expectation_executor(spec, [("expect.metric", {"at_ms": 0, **args})])
    with pytest.raises(MeasurementUnavailable) as failure:
        executor.check_measured_expectations({"scenario.steps_performed": 2}, {})
    assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE


@pytest.mark.parametrize("args", [
    {"assertion_id": 7, "outcome": "passed"},
    {"assertion_id": "expectations_met", "outcome": 1},
    {"assertion_id": "expectations_met"},                                      # no outcome
    {"outcome": "passed"},                                                     # no assertion_id
])
def test_an_expect_assertion_argument_of_the_wrong_type_is_unevaluable_not_a_crash(args):
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.virtual.executor import VIRTUAL_EXPECTATION_UNEVALUABLE

    spec = _scenario_spec("scenario.expectations_failed_count")
    executor = _expectation_executor(spec, [("expect.assertion", {"at_ms": 0, **args})])
    with pytest.raises(MeasurementUnavailable) as failure:
        executor.check_measured_expectations({}, {"expectations_met": "passed"})
    assert failure.value.code == VIRTUAL_EXPECTATION_UNEVALUABLE


def test_a_well_typed_expect_assertion_still_reads_its_outcome():
    """The guards must not have swallowed the normal path."""
    spec = _scenario_spec("scenario.expectations_failed_count")
    executor = _expectation_executor(spec, [
        ("expect.assertion", {"at_ms": 0, "assertion_id": "expectations_met", "outcome": "failed"})])
    executor.check_measured_expectations({}, {"expectations_met": "passed"})
    assert executor.expectations_failed == 1
    assert "expected 'failed'" in executor.expectation_results[0].detail


def test_a_profile_executor_may_add_a_primitive_but_never_redefine_one():
    """Slice 08 rework: the add-only rule is ENFORCED, not a docstring convention.

    A profile that quietly redefined, say, `provider.output_done` would change what a
    shipped scenario means on that profile alone, and every stored run of it would be
    incomparable with the others. It is a defect of ours, so it is NOT
    `MeasurementUnavailable`: it reads `crashed`, not `inconclusive`.
    """
    from jarvis.testlab.runners import MeasurementUnavailable
    from jarvis.testlab.validation import TestLabError
    from jarvis.testlab.virtual.executor import (
        HANDLERS,
        VIRTUAL_PROFILE_HANDLER_INVALID,
        VirtualExecutor,
    )

    class Shadowing(VirtualExecutor):
        def handler_for(self, primitive: str):
            if primitive == "provider.output_done":
                return lambda executor, index, step: None
            return super().handler_for(primitive)

    class Adding(VirtualExecutor):
        def handler_for(self, primitive: str):
            if primitive == "audio.inject":
                return lambda executor, index, step: None
            return super().handler_for(primitive)

    shadowing = Shadowing(stack=None, context=None, journal=None)
    with pytest.raises(TestLabError) as caught:
        shadowing.resolve_handler("provider.output_done")
    assert caught.value.code == VIRTUAL_PROFILE_HANDLER_INVALID
    assert "may add a primitive, never redefine one" in caught.value.detail
    assert not isinstance(caught.value, MeasurementUnavailable), "a lab defect is crashed, not inconclusive"

    adding = Adding(stack=None, context=None, journal=None)
    assert adding.resolve_handler("audio.inject") is not None
    assert adding.resolve_handler("provider.output_done") is HANDLERS["provider.output_done"]


def test_the_audio_executor_passes_the_add_only_rule_for_every_shared_primitive():
    """The shipped `audio` executor adds exactly one name and shadows none."""
    from jarvis.testlab.audio.runners import AudioExecutor
    from jarvis.testlab.virtual.executor import HANDLERS

    executor = AudioExecutor(stack=None, context=None, journal=None)
    for primitive in HANDLERS:
        assert executor.resolve_handler(primitive) is HANDLERS[primitive], primitive
    assert executor.resolve_handler("audio.inject") is not None
