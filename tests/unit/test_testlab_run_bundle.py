"""Slice 12: the bundle of a run, and the one field of a terminal record that may be written.

Contract: `docs/testlab.md` ("Bundle of a run", "Update rule"). Three layers, tested
apart: the pure selection rules (`run_bundle`), the store rule that lets a run point at
its own normalization exactly once (`attach_bundle`), and the composition of the two
with the Slice 03 capture service (`TestLabApi.capture_run_bundle`).

No worker, no device, no provider: the run records are built here and the trace is a
handful of journal lines written to the store as the artifact a real runner commits.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import pytest

from jarvis.testlab.api import TestLabApi
from jarvis.testlab.composition import TestLab, TestLabConfig
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.identity import format_bundle_id
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.run_bundle import (
    RUN_BUNDLE_NO_TRACE,
    RunBundleError,
    run_session_selector,
    select_trace_artifact,
)
from jarvis.testlab.runs import (
    TERMINAL_STATUSES,
    ArtifactKind,
    ArtifactRef,
    RunStatus,
    complete_run,
    transition_run,
)
from jarvis.testlab.store import (
    STORE_IMMUTABLE_FIELD,
    RunQuery,
    TestLabStoreError,
    check_bundle_attachment,
)
from jarvis.testlab.supervisor import SupervisorPolicy
from tests.fakes.testlab import NONCE, T0, queued_run, self_echo_spec

TRACE_MEDIA_TYPE = "application/x-ndjson"
OTHER_BUNDLE = format_bundle_id(T0, "f" * 16)


def ref(path: str, kind: ArtifactKind = ArtifactKind.TRACE_EXCERPT) -> ArtifactRef:
    return ArtifactRef(kind, path, TRACE_MEDIA_TYPE, "0" * 64, 1)


# ------------------------------------------------------- the selection rules

def test_the_journal_artifact_is_chosen_by_kind_and_never_by_name():
    run = queued_run(artifacts=(ref("metrics.json", ArtifactKind.METRICS), ref("evidence/journal.ndjson")))
    assert select_trace_artifact(run).path == "evidence/journal.ndjson"


def test_a_run_with_no_journal_artifact_has_no_bundle_to_capture():
    with pytest.raises(RunBundleError) as caught:
        select_trace_artifact(queued_run(artifacts=(ref("metrics.json", ArtifactKind.METRICS),)))
    assert caught.value.code == RUN_BUNDLE_NO_TRACE


def test_two_journal_artifacts_are_refused_rather_than_guessed_at():
    run = queued_run(artifacts=(ref("a.jsonl"), ref("b.jsonl")))
    with pytest.raises(RunBundleError) as caught:
        select_trace_artifact(run)
    assert caught.value.code == RUN_BUNDLE_NO_TRACE and "2" in caught.value.detail


def test_the_selector_is_the_runs_first_voice_session_unless_one_is_named():
    run = queued_run()
    assert run_session_selector(run).session_id == f"{run.run_id}-s1"
    assert run_session_selector(run, session_id=f"{run.run_id}-s3").session_id == f"{run.run_id}-s3"


# --------------------------------------------------------- the attach rule

def test_attaching_the_same_bundle_twice_is_not_a_write():
    run = queued_run(bundle_id=OTHER_BUNDLE)
    assert check_bundle_attachment(run, OTHER_BUNDLE) is False
    assert check_bundle_attachment(queued_run(), OTHER_BUNDLE) is True


def test_a_run_already_pointing_at_another_bundle_refuses_the_second():
    other = format_bundle_id(T0 + timedelta(seconds=1), "e" * 16)
    with pytest.raises(TestLabStoreError) as caught:
        check_bundle_attachment(queued_run(bundle_id=OTHER_BUNDLE), other)
    assert caught.value.code == STORE_IMMUTABLE_FIELD


def test_the_store_attaches_a_bundle_to_a_terminal_run_and_nothing_else_changes(tmp_path):
    store = FilesystemTestRunStore(tmp_path / "store")
    spec = self_echo_spec()
    stored = store.create_run(queued_run(spec))
    running = store.update_run(transition_run(stored, RunStatus.RUNNING, at=T0), expected=stored)
    finished = store.update_run(
        complete_run(running, at=T0 + timedelta(seconds=1), assertion_results=(),
                     metrics={"barge_in.false_count": 0, "output.stopped": True,
                              "speech.ready_to_play_ms": 100}),
        expected=running)
    assert finished.status in TERMINAL_STATUSES

    attached = store.attach_bundle(finished.run_id, OTHER_BUNDLE)
    assert attached.bundle_id == OTHER_BUNDLE
    assert replace(attached, bundle_id=None).to_dict() == finished.to_dict()
    assert store.get_run(finished.run_id).bundle_id == OTHER_BUNDLE
    # Idempotent, and the second call is not a conflict.
    assert store.attach_bundle(finished.run_id, OTHER_BUNDLE).bundle_id == OTHER_BUNDLE
    # The listing agrees with the record, and the query finds it by its bundle.
    page = store.list_runs(RunQuery(bundle_id=OTHER_BUNDLE))
    assert [item.run_id for item in page.runs] == [finished.run_id]


def test_the_ordinary_update_path_still_refuses_to_set_a_bundle(tmp_path):
    """`attach_bundle` is the ONE way, so a runner or a supervisor cannot set it in passing."""
    store = FilesystemTestRunStore(tmp_path / "store")
    stored = store.create_run(queued_run())
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(stored, bundle_id=OTHER_BUNDLE), expected=stored)
    assert caught.value.code == STORE_IMMUTABLE_FIELD


def test_attaching_a_second_bundle_through_the_store_is_refused(tmp_path):
    store = FilesystemTestRunStore(tmp_path / "store")
    stored = store.create_run(queued_run())
    store.attach_bundle(stored.run_id, OTHER_BUNDLE)
    with pytest.raises(TestLabStoreError) as caught:
        store.attach_bundle(stored.run_id, format_bundle_id(T0 + timedelta(seconds=2), "d" * 16))
    assert caught.value.code == STORE_IMMUTABLE_FIELD


# ------------------------------------------------------------ the composition

def trace_lines(session_id: str) -> bytes:
    """A run's journal, in the shape `TraceRecordingJournal` writes (Slice 06)."""
    def line(offset_ms: int, kind: str, **data: object) -> str:
        moment = T0 + timedelta(milliseconds=offset_ms)
        stamp = moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
        return json.dumps({"ts": stamp, "kind": kind, "level": "info", "message": "",
                           "data": {"session_id": session_id, **data}}, ensure_ascii=False)

    return ("\n".join([
        line(0, "voice.start"),
        line(50, "voice.connecting"),
        line(120, "voice.active"),
        line(400, "voice.speech.queued", speech_id="s1", correlation_id="c1"),
        line(520, "voice.speech.started", speech_id="s1", correlation_id="c1"),
        line(1400, "voice.speech.completed", speech_id="s1", correlation_id="c1", outcome="completed",
             played_ms=880),
        line(1500, "voice.stop"),
    ]) + "\n").encode("utf-8")


@pytest.fixture
def lab(tmp_path) -> TestLab:
    root = tmp_path / "runtime" / "testlab"
    return TestLab(TestLabConfig(
        root=root, work_root=root / "work", runtime_root=tmp_path / "runtime", data_root=tmp_path / "data",
        policy=SupervisorPolicy(maintenance=MaintenancePolicy(enabled=False))))


def store_run_with_trace(lab: TestLab) -> str:
    """A terminal run carrying the `trace.jsonl` artifact a real virtual runner commits."""
    stored = lab.store.create_run(queued_run())
    running = lab.store.update_run(transition_run(stored, RunStatus.RUNNING, at=T0), expected=stored)
    artifact = lab.store.put_artifact(running.run_id, "trace.jsonl", kind=ArtifactKind.TRACE_EXCERPT,
                                      media_type=TRACE_MEDIA_TYPE, data=trace_lines(f"{running.run_id}-s1"))
    finished = lab.store.update_run(
        complete_run(running, at=T0 + timedelta(seconds=2), assertion_results=(),
                     metrics={"barge_in.false_count": 0, "output.stopped": True,
                              "speech.ready_to_play_ms": 100}, artifacts=(artifact,)),
        expected=running)
    return finished.run_id


async def test_a_runs_own_trace_becomes_a_bundle_the_run_then_references(lab):
    run_id = store_run_with_trace(lab)
    api = TestLabApi(lab)

    answer = await api.capture_run_bundle(run_id)

    assert answer["run_id"] == run_id and answer["artifact"] == "trace.jsonl"
    assert answer["stored"] == "stored"
    bundle_id = answer["bundle"]["bundle_id"]
    assert answer["attached_bundle_id"] == bundle_id
    # The reference is on the stored record, and the query is the way back.
    assert (await api.get_run(run_id))["run"]["bundle_id"] == bundle_id
    found = await api.query_runs(bundle_id=bundle_id)
    assert [item["run"]["run_id"] for item in found["runs"]] == [run_id]
    # One voice session, and its own trace is the journal: no conversation events asked for.
    assert answer["bundle"]["session_ids"] == [f"{run_id}-s1"]
    coverage = answer["coverage"]
    assert coverage["segments"]["count"] == 1
    assert coverage["conversation_events"]["status"] == "not_requested"
    assert coverage["runtime_journal"]["status"] == "available"
    assert list(coverage["warnings"]) == []


async def test_capturing_the_same_run_twice_is_idempotent(lab):
    """The bundle id is derived from the evidence, so the second capture is a duplicate."""
    run_id = store_run_with_trace(lab)
    api = TestLabApi(lab)
    first = await api.capture_run_bundle(run_id)
    second = await api.capture_run_bundle(run_id)
    assert second["bundle"]["bundle_id"] == first["bundle"]["bundle_id"]
    assert second["stored"] == "duplicate"
    assert second["attached_bundle_id"] == first["attached_bundle_id"]


async def test_capture_without_attaching_leaves_the_record_alone(lab):
    run_id = store_run_with_trace(lab)
    api = TestLabApi(lab)
    answer = await api.capture_run_bundle(run_id, attach=False)
    assert answer["attached_bundle_id"] is None
    assert (await api.get_run(run_id))["run"]["bundle_id"] is None
    assert await api.get_bundle(answer["bundle"]["bundle_id"])


async def test_capture_without_storing_attaches_nothing_either(lab):
    """A record may not point at a bundle that was never written."""
    run_id = store_run_with_trace(lab)
    api = TestLabApi(lab)
    answer = await api.capture_run_bundle(run_id, store=True, attach=False)
    built = await api.capture_run_bundle(run_id, store=False)
    assert built["stored"] is None and built["attached_bundle_id"] is None
    assert built["bundle"]["bundle_id"] == answer["bundle"]["bundle_id"]
    assert (await api.get_run(run_id))["run"]["bundle_id"] is None


async def test_a_run_with_no_trace_is_refused_with_its_own_code(lab):
    stored = lab.store.create_run(queued_run())
    api = TestLabApi(lab)
    with pytest.raises(RunBundleError) as caught:
        await api.capture_run_bundle(stored.run_id)
    assert caught.value.code == RUN_BUNDLE_NO_TRACE


async def test_the_bundle_is_read_from_the_stored_path_and_the_run_is_never_rewritten(lab, tmp_path):
    """The capture reads the artifact where the store put it; nothing is copied out of the run."""
    run_id = store_run_with_trace(lab)
    path = lab.store.artifact_path(run_id, "trace.jsonl")
    assert path == Path(lab.config.root) / "runs" / run_id / "trace.jsonl"
    before = lab.store.get_run(run_id)
    await TestLabApi(lab).capture_run_bundle(run_id, attach=False)
    assert lab.store.get_run(run_id).to_dict() == before.to_dict()


# ------------------------------------------------------------------- the CLI

async def test_the_cli_captures_a_runs_bundle_without_taking_the_work_root(lab):
    """`capture --run` is a read-and-write on the stores, never an execution."""
    import io

    from jarvis.testlab.cli import EXIT_OK, Console, build_parser, run_cli

    run_id = store_run_with_trace(lab)
    out, err = io.StringIO(), io.StringIO()
    console = Console(as_json=True, out=out, err=err)
    args = build_parser().parse_args(["--json", "capture", "--run", run_id])
    code = await run_cli(args, console, api=TestLabApi(lab))

    assert code == EXIT_OK
    payload = json.loads(out.getvalue())
    assert payload["run_id"] == run_id
    assert payload["attached_bundle_id"] == payload["bundle"]["bundle_id"]
    assert lab.started is False, "capturing a bundle must not start the supervisor"


async def test_the_cli_refuses_a_run_capture_that_also_asks_for_a_session_window(lab):
    """A run's trace IS the window; two ways of saying it would silently disagree."""
    import io

    from jarvis.testlab.cli import EXIT_USAGE, Console, build_parser, run_cli

    run_id = store_run_with_trace(lab)
    out, err = io.StringIO(), io.StringIO()
    console = Console(as_json=True, out=out, err=err)
    args = build_parser().parse_args(["--json", "capture", "--run", run_id,
                                      "--start", "2026-09-19T09:00:00Z"])
    # A bad command line is a USAGE error (2), not a failed run and not a store fault.
    assert await run_cli(args, console, api=TestLabApi(lab)) == EXIT_USAGE
    assert "session window" in err.getvalue()


async def test_only_the_call_that_wrote_the_reference_claims_it(lab):
    """`attached` is about THIS call; `attached_bundle_id` is about the record."""
    run_id = store_run_with_trace(lab)
    api = TestLabApi(lab)

    first = await api.capture_run_bundle(run_id)
    assert first["attached"] is True

    again = await api.capture_run_bundle(run_id)
    assert again["attached"] is False and again["attached_bundle_id"] == first["attached_bundle_id"]

    built = await api.capture_run_bundle(run_id, store=False)
    assert built["attached"] is False and built["attached_bundle_id"] == first["attached_bundle_id"]
