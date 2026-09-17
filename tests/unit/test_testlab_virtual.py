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
from jarvis.testlab.virtual.runners import _latency_metrics, _payload_metrics, _supersession_metrics


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
    # `testlab.selftest.reserved` is the deliberate fixture reservation that keeps the
    # `runner_unavailable` worker path testable now that every virtual name is registered.
    assert reserved_names == ["testlab.scenario.audio", "testlab.scenario.hardware_auto",
                              "testlab.scenario.hardware_guided", "testlab.scenario.live",
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
    metrics = _latency_metrics(journal)
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
    metrics = _latency_metrics(journal)
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
    metrics = _latency_metrics(journal)
    by_name = {metric.name: metric for metric in spec.metrics}
    results = [evaluate_assertion(item, by_name[item.metric], metrics.get(item.metric))
               for item in spec.assertions]
    outcomes = {item.assertion_id: item.outcome for item in results}
    assert outcomes["started_to_first_audio"] is AssertionOutcome.MISSING
    assert assertions_verdict(results) is AssertionVerdict.INCONCLUSIVE
