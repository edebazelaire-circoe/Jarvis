"""Conformance tests for the Test Lab run store port and filesystem adapter (docs/testlab.md, Storage)."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
import os
import shutil
import threading
import time

import pytest

from jarvis.testlab.diagnostics import AssertionResult, evaluate_assertion
from jarvis.testlab.filesystem_store import (
    ARTIFACT_TMP_PREFIX,
    DELETING_PREFIX,
    RECORD_NAME,
    RECORD_TMP_PREFIX,
    STAGING_PREFIX,
    MANIFEST_NAME,
    FilesystemTestRunStore,
)
from jarvis.testlab.identity import format_run_id, format_sweep_id
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import (
    TRANSITION_ILLEGAL,
    ArtifactKind,
    ArtifactRef,
    RunFailure,
    RunStatus,
    RunTransitionError,
    TestRun,
    complete_run,
    transition_run,
)
from jarvis.testlab.store import (
    DEFAULT_ARTIFACT_MAX_BYTES,
    STORE_ARTIFACT_MISMATCH,
    STORE_ARTIFACT_REFUSED,
    STORE_ARTIFACT_TOO_LARGE,
    STORE_BUSY,
    STORE_CONFLICT,
    STORE_CORRUPT,
    STORE_DELETION_PENDING,
    STORE_ENVIRONMENT_REFUSED,
    STORE_IMMUTABLE_FIELD,
    STORE_NOT_FOUND,
    STORE_PATH_UNSAFE,
    STORE_RUN_EXISTS,
    ArtifactWriteLimits,
    RunConflictError,
    RunNotFoundError,
    RunQuery,
    RunRecordCorruptError,
    TestLabStoreError,
    check_run_update,
)
from jarvis.testlab.validation import TestLabError, canonical_json
from tests.fakes.testlab import T0, at, queued_run, self_echo_spec

S = RunStatus
SPEC = self_echo_spec()
PASSING = {"barge_in.false_count": 0, "output.stopped": True, "speech.ready_to_play_ms": 1200}


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, data or {}))


def results_for(metrics: dict) -> tuple[AssertionResult, ...]:
    return tuple(evaluate_assertion(assertion, SPEC.metric_index[assertion.metric], metrics.get(assertion.metric))
                 for assertion in SPEC.assertions)


def run_at(ms: int, nonce: str = "0123456789abcdef", **changes) -> TestRun:
    return queued_run(SPEC, run_id=format_run_id(at(ms), nonce), created_at=at(ms), **changes)


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


@pytest.fixture
def store(tmp_path, sink) -> FilesystemTestRunStore:
    return FilesystemTestRunStore(tmp_path / "testlab", diagnostics=sink)


def started(store: FilesystemTestRunStore, run: TestRun) -> TestRun:
    store.create_run(run)
    running = transition_run(run, S.RUNNING, at=run.created_at + (at(10) - T0))
    return store.update_run(running, expected=run)


def passed(store: FilesystemTestRunStore, run: TestRun, artifacts: tuple[ArtifactRef, ...] = ()) -> TestRun:
    running = started(store, run)
    done = complete_run(running, at=running.started_at + (at(100) - T0), assertion_results=results_for(PASSING),
                        metrics=PASSING, score=50.0, artifacts=artifacts or None)
    return store.update_run(done, expected=running)


# ------------------------------------------------------------ round trip

def test_create_get_round_trip_writes_canonical_json(store):
    run = queued_run()
    assert store.create_run(run) is run
    assert store.get_run(run.run_id) == run
    record = store.runs_dir / run.run_id / RECORD_NAME
    assert record.read_bytes() == canonical_json(run.to_dict()).encode("utf-8")
    assert not list(store.runs_dir.glob(f"{STAGING_PREFIX}*"))


def test_full_lifecycle_round_trip(store, sink):
    run = queued_run()
    done = passed(store, run)
    assert done.status is S.PASSED
    assert store.get_run(run.run_id) == done
    kinds = [event[0] for event in sink.events]
    assert kinds.count("testlab_run_created") == 1
    assert kinds.count("testlab_run_status_changed") == 2


def test_create_refuses_existing_run(store):
    run = queued_run()
    store.create_run(run)
    with pytest.raises(TestLabStoreError) as caught:
        store.create_run(run)
    assert caught.value.code == STORE_RUN_EXISTS


@pytest.mark.parametrize("make", [
    lambda: transition_run(queued_run(), S.RUNNING, at=at(5)),
    lambda: queued_run(artifacts=(ArtifactRef(ArtifactKind.REPORT, "report.json", "application/json", "a" * 64, 1),)),
])
def test_create_refuses_non_queued_or_artifacts(store, make):
    with pytest.raises(TestLabStoreError) as caught:
        store.create_run(make())
    assert caught.value.code == STORE_CONFLICT


def test_get_unknown_run_is_not_found(store):
    with pytest.raises(RunNotFoundError) as caught:
        store.get_run(format_run_id(T0, "ffffffffffffffff"))
    assert caught.value.code == STORE_NOT_FOUND


@pytest.mark.parametrize("bad", ["../escape", "tlr-bad", "C:\\x", ""])
def test_run_id_must_be_a_run_id(store, bad):
    with pytest.raises(TestLabStoreError) as caught:
        store.get_run(bad)
    assert caught.value.code == STORE_PATH_UNSAFE


# ----------------------------------------------------------- update rule

def test_update_rejects_regressed_status_built_with_replace(store):
    """F10: dataclasses.replace builds a valid record with a regressed status; the store refuses it."""
    running = started(store, queued_run())
    regressed = replace(running, status=S.QUEUED, started_at=None)
    with pytest.raises(RunTransitionError) as caught:
        store.update_run(regressed, expected=running)
    assert caught.value.code == TRANSITION_ILLEGAL
    assert store.get_run(running.run_id) == running


def test_update_rejects_skipping_running_to_passed(store):
    run = queued_run()
    store.create_run(run)
    forged = replace(run, status=S.PASSED, started_at=at(1), finished_at=at(2),
                     assertion_results=results_for(PASSING), metrics=PASSING)
    with pytest.raises(RunTransitionError):
        store.update_run(forged, expected=run)


@pytest.mark.parametrize("terminal", [S.PASSED, S.ERRORED, S.CANCELLED])
def test_terminal_record_is_immutable(store, terminal):
    run = queued_run()
    if terminal is S.PASSED:
        final = passed(store, run)
    else:
        store.create_run(run)
        final = store.update_run(transition_run(run, terminal, at=at(3), failure=RunFailure("worker_lost")),
                                 expected=run)
    for mutated in (final, replace(final, score=10.0) if terminal is S.PASSED else replace(final, join_ids={"turn_id": "t1"})):
        with pytest.raises(RunTransitionError) as caught:
            store.update_run(mutated, expected=final)
        assert caught.value.code == TRANSITION_ILLEGAL
    with pytest.raises(RunConflictError):
        store.put_artifact(run.run_id, "late.txt", kind=ArtifactKind.REPORT, media_type="text/plain", data=b"x")


@pytest.mark.parametrize("field, value", [
    ("config_fingerprint", "e" * 64),
    ("parameters", {**queued_run().parameters, "turns": 7}),
    ("sweep_id", format_sweep_id(T0, "0123456789abcdef")),
    ("profile", ProfileName.LIVE),
])
def test_update_rejects_identity_changes(store, field, value):
    run = queued_run()
    store.create_run(run)
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(run, **{field: value}), expected=run)
    assert caught.value.code == STORE_IMMUTABLE_FIELD


def test_update_rejects_started_at_rewrite_and_artifact_removal(store):
    run = queued_run()
    store.create_run(run)
    ref = store.put_artifact(run.run_id, "config_snapshot.json", kind=ArtifactKind.CONFIG_SNAPSHOT,
                             media_type="application/json", data=b"{}")
    with_ref = store.update_run(replace(run, artifacts=(ref,)), expected=run)
    running = store.update_run(transition_run(with_ref, S.RUNNING, at=at(5)), expected=with_ref)
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(running, started_at=at(6)), expected=running)
    assert caught.value.code == STORE_IMMUTABLE_FIELD
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(running, artifacts=()), expected=running)
    assert caught.value.code == STORE_IMMUTABLE_FIELD


def test_check_run_update_is_pure_and_allows_same_status_enrichment():
    run = queued_run()
    check_run_update(run, replace(run, join_ids={"conversation_id": "c1"}))
    with pytest.raises(TestLabStoreError):
        check_run_update(run, replace(run, run_id=format_run_id(T0, "ffffffffffffffff")))


# ------------------------------------------------------------- CAS/locks

def test_cas_conflict_on_status(store):
    run = queued_run()
    store.create_run(run)
    running = transition_run(run, S.RUNNING, at=at(5))
    store.update_run(running, expected=run)
    cancelled = transition_run(run, S.CANCELLED, at=at(6))
    with pytest.raises(RunConflictError) as caught:
        store.update_run(cancelled, expected=run)  # the supervisor still believes the run is queued
    assert caught.value.code == STORE_CONFLICT
    assert "status" in caught.value.detail
    assert store.get_run(run.run_id).status is S.RUNNING


def test_cas_conflict_on_same_status_content(store):
    running = started(store, queued_run())
    first = store.update_run(replace(running, join_ids={"turn_id": "t1"}), expected=running)
    with pytest.raises(RunConflictError):
        store.update_run(replace(running, join_ids={"turn_id": "t2"}), expected=running)
    assert store.get_run(running.run_id) == first


def test_concurrent_writers_exactly_one_wins(store):
    running = started(store, queued_run())
    barrier = threading.Barrier(8)
    outcomes: list[str] = []

    def writer(index: int) -> None:
        barrier.wait()
        target = replace(running, join_ids={"turn_id": f"t{index}"})
        try:
            store.update_run(target, expected=running)
            outcomes.append("ok")
        except RunConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict"] * 7 + ["ok"]


def test_lock_held_elsewhere_gives_busy(tmp_path):
    store = FilesystemTestRunStore(tmp_path, lock_timeout_s=0.05)
    run = queued_run()
    store.create_run(run)
    with store._lock(run.run_id):
        started_at = time.monotonic()
        with pytest.raises(TestLabStoreError) as caught:
            store.update_run(transition_run(run, S.RUNNING, at=at(5)), expected=run)
        assert time.monotonic() - started_at < 2
    assert caught.value.code == STORE_BUSY
    store.update_run(transition_run(run, S.RUNNING, at=at(5)), expected=run)  # released: now succeeds


# ------------------------------------------------------ corrupt / crashes

@pytest.mark.parametrize("content", [b'{"schema": "jarvis.testlab.run"', b"\xff\xfe", b"[]", b"{}"])
def test_corrupt_record_is_typed_error_and_listed_distinctly(store, sink, content):
    good = run_at(0, "0000000000000001")
    bad = run_at(1000, "0000000000000002")
    store.create_run(good)
    store.create_run(bad)
    (store.runs_dir / bad.run_id / RECORD_NAME).write_bytes(content)
    with pytest.raises(RunRecordCorruptError) as caught:
        store.get_run(bad.run_id)
    assert caught.value.code == STORE_CORRUPT
    page = store.list_runs()
    assert [run.run_id for run in page.runs] == [good.run_id]
    assert [entry.entry for entry in page.corrupt] == [bad.run_id]
    assert any(event[0] == "testlab_run_listing_corrupt" and event[1] == "warning" for event in sink.events)
    with pytest.raises(RunRecordCorruptError):
        store.update_run(transition_run(bad, S.RUNNING, at=at(1001)), expected=bad)


def test_record_of_another_run_is_corrupt(store):
    a, b = run_at(0, "0000000000000001"), run_at(5, "0000000000000002")
    store.create_run(a)
    store.create_run(b)
    (store.runs_dir / b.run_id / RECORD_NAME).write_bytes((store.runs_dir / a.run_id / RECORD_NAME).read_bytes())
    with pytest.raises(RunRecordCorruptError):
        store.get_run(b.run_id)


def test_missing_record_and_stray_entries_are_reported(store):
    good = run_at(0, "0000000000000001")
    store.create_run(good)
    empty = run_at(5, "0000000000000002").run_id
    (store.runs_dir / empty).mkdir()
    (store.runs_dir / "notes.txt").write_text("stray", encoding="utf-8")
    (store.runs_dir / f"{STAGING_PREFIX}{good.run_id}-dead").mkdir()  # protocol temporary: not a run, not corrupt
    page = store.list_runs()
    assert [run.run_id for run in page.runs] == [good.run_id]
    assert sorted(entry.entry for entry in page.corrupt) == sorted([empty, "notes.txt"])
    with pytest.raises(RunRecordCorruptError):
        store.get_run(empty)


def test_crash_leftover_temp_is_ignored_then_cleaned(store):
    run = queued_run()
    store.create_run(run)
    run_dir = store.runs_dir / run.run_id
    leftover = run_dir / f"{RECORD_TMP_PREFIX}deadbeef.tmp"
    leftover.write_bytes(b'{"schema": "jarvis.testlab.run", "status": "pas')  # interrupted write
    stream = run_dir / f"{ARTIFACT_TMP_PREFIX}deadbeef.tmp"
    stream.write_bytes(b"partial")
    staging = store.runs_dir / f"{STAGING_PREFIX}{run.run_id}-0000"
    staging.mkdir()
    deleting = store.runs_dir / f"{DELETING_PREFIX}0123456789abcdef"
    deleting.mkdir()
    assert store.get_run(run.run_id) == run
    # Temporaries are invisible to reads; an unfinished deletion is reported, never hidden.
    assert [(entry.entry, entry.code) for entry in store.list_runs().corrupt] == [
        (deleting.name, "testlab_store_deletion_pending")]
    assert store.remove_stale_temporaries() == 1  # the deletion is retried at any age; the rest is too recent
    assert not deleting.exists() and store.list_runs().corrupt == ()
    old = time.time() - 7200
    for path in (leftover, stream, staging):
        os.utime(path, (old, old))
    assert store.remove_stale_temporaries() == 3
    assert not leftover.exists() and not stream.exists() and not staging.exists()
    assert store.get_run(run.run_id) == run


def test_failed_replace_keeps_previous_record_and_removes_temp(store, monkeypatch):
    run = queued_run()
    store.create_run(run)

    def refuse(source, target):
        raise PermissionError("held by antivirus")

    monkeypatch.setattr("jarvis.testlab.filesystem_store.replace_with_retry", refuse)
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(transition_run(run, S.RUNNING, at=at(5)), expected=run)
    assert caught.value.code == "testlab_store_io"
    run_dir = store.runs_dir / run.run_id
    assert store.get_run(run.run_id) == run
    assert not [path for path in run_dir.iterdir() if path.name.endswith(".tmp")]


# ------------------------------------------------------------- listing

def test_list_ordering_filters_and_pagination(store):
    sweep = format_sweep_id(T0, "00000000000000ff")
    runs = [run_at(0, "0000000000000001"), run_at(1000, "0000000000000002", sweep_id=sweep),
            run_at(1000, "0000000000000003", profile=ProfileName.LIVE), run_at(2000, "0000000000000004", sweep_id=sweep)]
    for run in runs:
        store.create_run(run)
    passed_run = run_at(3000, "0000000000000005")
    passed(store, passed_run)
    ids = [run.run_id for run in runs] + [passed_run.run_id]

    assert [run.run_id for run in store.list_runs().runs] == ids[::-1]
    assert [run.run_id for run in store.list_runs(RunQuery(newest_first=False)).runs] == ids
    assert [run.run_id for run in store.list_runs(RunQuery(sweep_id=sweep)).runs] == [ids[3], ids[1]]
    assert [run.run_id for run in store.list_runs(RunQuery(profile=ProfileName.LIVE)).runs] == [ids[2]]
    assert [run.run_id for run in store.list_runs(RunQuery(statuses=frozenset({S.PASSED}))).runs] == [ids[4]]
    assert [run.run_id for run in store.list_runs(RunQuery(diagnostic_id="voice.other")).runs] == []
    window = RunQuery(created_from=at(1000), created_until=at(2000), newest_first=False)
    assert [run.run_id for run in store.list_runs(window).runs] == [ids[1], ids[2]]

    first = store.list_runs(RunQuery(limit=2))
    assert [run.run_id for run in first.runs] == [ids[4], ids[3]] and first.next_cursor == ids[3]
    second = store.list_runs(RunQuery(limit=2, after_run_id=first.next_cursor))
    assert [run.run_id for run in second.runs] == [ids[2], ids[1]] and second.next_cursor == ids[1]
    last = store.list_runs(RunQuery(limit=2, after_run_id=second.next_cursor))
    assert [run.run_id for run in last.runs] == [ids[0]] and last.next_cursor is None


def test_list_empty_store(tmp_path):
    page = FilesystemTestRunStore(tmp_path / "never").list_runs()
    assert page.runs == () and page.corrupt == () and page.next_cursor is None


@pytest.mark.parametrize("changes", [dict(limit=0), dict(limit=501), dict(statuses={S.PASSED}),
                                     dict(created_from=at(5), created_until=at(5)), dict(after_run_id="x")])
def test_run_query_validation(changes):
    with pytest.raises(TestLabError):
        RunQuery(**changes)


# ------------------------------------------------------------ artifacts

def test_put_read_artifact_sha_and_size(store):
    run = queued_run()
    store.create_run(run)
    payload = b"line\n" * 100_000  # several stream chunks
    ref = store.put_artifact(run.run_id, "events/trace.jsonl", kind=ArtifactKind.EVENT_LOG,
                             media_type="application/x-ndjson", data=io.BytesIO(payload))
    assert ref.sha256 == hashlib.sha256(payload).hexdigest() and ref.size_bytes == len(payload)
    assert store.list_artifacts(run.run_id) == ()  # not committed until the record references it
    with pytest.raises(TestLabStoreError) as caught:
        store.read_artifact(run.run_id, ref.path)
    assert caught.value.code == STORE_NOT_FOUND
    updated = store.update_run(replace(run, artifacts=(ref,)), expected=run)
    assert store.list_artifacts(run.run_id) == (ref,)
    assert store.read_artifact(run.run_id, ref.path) == payload
    with store.open_artifact(run.run_id, ref.path) as handle:
        assert handle.read(5) == b"line\n"
    chunks = store.put_artifact(run.run_id, "metrics.json", kind=ArtifactKind.METRICS, media_type="application/json",
                                data=iter([b"{", b"}"]))
    assert chunks.size_bytes == 2
    with pytest.raises(TestLabStoreError) as caught:
        store.put_artifact(updated.run_id, ref.path, kind=ArtifactKind.EVENT_LOG, media_type="application/x-ndjson",
                           data=b"overwrite")
    assert caught.value.code == STORE_ARTIFACT_REFUSED


def test_update_rejects_forged_or_missing_artifact_reference(store):
    run = queued_run()
    store.create_run(run)
    ref = store.put_artifact(run.run_id, "report.json", kind=ArtifactKind.REPORT, media_type="application/json",
                             data=b'{"ok": true}')
    forged = replace(ref, sha256="0" * 64)
    missing = replace(ref, path="absent.json")
    for bad in (forged, missing, replace(ref, size_bytes=ref.size_bytes + 1)):
        with pytest.raises(TestLabStoreError) as caught:
            store.update_run(replace(run, artifacts=(bad,)), expected=run)
        assert caught.value.code == STORE_ARTIFACT_MISMATCH


def test_read_artifact_detects_tampering(store):
    run = queued_run()
    store.create_run(run)
    ref = store.put_artifact(run.run_id, "report.json", kind=ArtifactKind.REPORT, media_type="application/json",
                             data=b"12345")
    store.update_run(replace(run, artifacts=(ref,)), expected=run)
    (store.runs_dir / run.run_id / "report.json").write_bytes(b"54321")
    with pytest.raises(TestLabStoreError) as caught:
        store.read_artifact(run.run_id, "report.json")
    assert caught.value.code == STORE_ARTIFACT_MISMATCH
    assert store.read_artifact(run.run_id, "report.json", verify=False) == b"54321"


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "C:/Windows/x", "a\\b", ".hidden", "a/../b",
                                  "record.json", "RECORD.JSON", "con", "sub/NUL.txt", "lpt1.log", "x/", ""])
def test_artifact_path_traversal_and_reserved_names_rejected(store, path):
    run = queued_run()
    store.create_run(run)
    with pytest.raises(TestLabStoreError) as caught:
        store.put_artifact(run.run_id, path, kind=ArtifactKind.REPORT, media_type="text/plain", data=b"x")
    assert caught.value.code == STORE_PATH_UNSAFE
    assert sorted(p.name for p in (store.runs_dir / run.run_id).iterdir()) == [RECORD_NAME]


def test_artifact_path_case_collision_rejected(store):
    run = queued_run()
    store.create_run(run)
    ref = store.put_artifact(run.run_id, "Report.json", kind=ArtifactKind.REPORT, media_type="application/json",
                             data=b"{}")
    store.update_run(replace(run, artifacts=(ref,)), expected=run)
    stored = store.get_run(run.run_id)
    with pytest.raises(TestLabStoreError) as caught:
        store.put_artifact(stored.run_id, "report.json", kind=ArtifactKind.REPORT, media_type="application/json",
                           data=b"{}")
    assert caught.value.code == STORE_PATH_UNSAFE


def _make_link(link, target) -> bool:
    if os.name == "nt":
        import _winapi
        try:
            _winapi.CreateJunction(str(target), str(link))
            return True
        except OSError:
            return False
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def test_artifact_path_through_link_rejected(store, tmp_path):
    run = queued_run()
    store.create_run(run)
    outside = tmp_path / "outside"
    outside.mkdir()
    if not _make_link(store.runs_dir / run.run_id / "logs", outside):
        pytest.skip("this host cannot create a directory link")
    with pytest.raises(TestLabStoreError) as caught:
        store.put_artifact(run.run_id, "logs/escape.txt", kind=ArtifactKind.WORKER_LOG, media_type="text/plain",
                           data=b"x")
    assert caught.value.code == STORE_PATH_UNSAFE
    assert list(outside.iterdir()) == []


def test_run_directory_link_rejected(store, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    run_id = queued_run().run_id
    store.runs_dir.mkdir(parents=True)
    if not _make_link(store.runs_dir / run_id, outside):
        pytest.skip("this host cannot create a directory link")
    with pytest.raises(TestLabStoreError) as caught:
        store.get_run(run_id)
    assert caught.value.code == STORE_PATH_UNSAFE
    assert [entry.entry for entry in store.list_runs().corrupt] == [run_id]


def test_size_cap_enforced_while_streaming(tmp_path):
    caps = dict(DEFAULT_ARTIFACT_MAX_BYTES)
    caps[ArtifactKind.WORKER_LOG] = 1000
    store = FilesystemTestRunStore(tmp_path, limits=ArtifactWriteLimits(max_bytes_by_kind=caps))
    run = queued_run()
    store.create_run(run)
    consumed: list[int] = []

    def endless():
        while True:
            consumed.append(1)
            yield b"x" * 300

    with pytest.raises(TestLabStoreError) as caught:
        store.put_artifact(run.run_id, "worker.log", kind=ArtifactKind.WORKER_LOG, media_type="text/plain",
                           data=endless())
    assert caught.value.code == STORE_ARTIFACT_TOO_LARGE
    assert len(consumed) == 4  # stopped at the first chunk beyond the cap, never buffered the stream
    assert sorted(p.name for p in (store.runs_dir / run.run_id).iterdir()) == [RECORD_NAME]


def test_audio_is_opt_in(tmp_path):
    run = queued_run()
    closed = FilesystemTestRunStore(tmp_path / "closed")
    closed.create_run(run)
    with pytest.raises(TestLabStoreError) as caught:
        closed.put_artifact(run.run_id, "clip.wav", kind=ArtifactKind.AUDIO_CLIP, media_type="audio/wav", data=b"RIFF")
    assert caught.value.code == STORE_ARTIFACT_REFUSED
    opened = FilesystemTestRunStore(tmp_path / "open", limits=ArtifactWriteLimits(allow_audio=True))
    opened.create_run(run)
    assert opened.put_artifact(run.run_id, "clip.wav", kind=ArtifactKind.AUDIO_CLIP, media_type="audio/wav",
                               data=b"RIFF").size_bytes == 4


def test_invalid_media_type_refused(store):
    run = queued_run()
    store.create_run(run)
    with pytest.raises(TestLabStoreError) as caught:
        store.put_artifact(run.run_id, "a.bin", kind=ArtifactKind.REPORT, media_type="Not A Type", data=b"x")
    assert caught.value.code == STORE_ARTIFACT_REFUSED


def test_write_limits_validation():
    with pytest.raises(TestLabError):
        ArtifactWriteLimits(max_bytes_by_kind={ArtifactKind.REPORT: 10})
    with pytest.raises(TestLabError):
        ArtifactWriteLimits(allow_audio="yes")


# --------------------------------------------------------------- delete

def test_delete_only_terminal_runs(store, sink):
    active = run_at(0, "0000000000000001")
    store.create_run(active)
    with pytest.raises(RunConflictError):
        store.delete_run(active.run_id)
    done = run_at(5, "0000000000000002")
    passed(store, done)
    store.delete_run(done.run_id)
    with pytest.raises(RunNotFoundError):
        store.get_run(done.run_id)
    assert [run.run_id for run in store.list_runs().runs] == [active.run_id]
    assert not (store.locks_dir / f"{done.run_id}.lock").exists()
    assert not list(store.runs_dir.glob(f"{DELETING_PREFIX}*"))
    assert any(event[0] == "testlab_run_deleted" for event in sink.events)
    with pytest.raises(RunNotFoundError):
        store.delete_run(done.run_id)


def test_storage_usage(store):
    run = run_at(0, "0000000000000001")
    store.create_run(run)
    ref = store.put_artifact(run.run_id, "trace.jsonl", kind=ArtifactKind.EVENT_LOG,
                             media_type="application/x-ndjson", data=b"a" * 100)
    store.update_run(replace(run, artifacts=(ref,)), expected=run)
    bad = run_at(5, "0000000000000002")
    store.create_run(bad)
    (store.runs_dir / bad.run_id / RECORD_NAME).write_text("nope", encoding="utf-8")
    usage = store.storage_usage()
    assert [item.run_id for item in usage.runs] == [run.run_id]
    item = usage.runs[0]
    run_dir = store.runs_dir / run.run_id
    protocol = (run_dir / RECORD_NAME).stat().st_size + (run_dir / MANIFEST_NAME).stat().st_size
    assert item.total_bytes == 100 + protocol
    assert dict(item.bytes_by_kind) == {ArtifactKind.EVENT_LOG: 100}
    assert [entry.entry for entry in usage.corrupt] == [bad.run_id]


def test_broken_diagnostic_sink_never_fails_the_store(tmp_path):
    class Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("sink down")

    store = FilesystemTestRunStore(tmp_path, diagnostics=Broken())
    run = queued_run()
    store.create_run(run)
    assert store.diagnostic_failures == 1
    assert json.loads((store.runs_dir / run.run_id / RECORD_NAME).read_text(encoding="utf-8"))["status"] == "queued"


def test_update_rejects_case_colliding_new_references(store):
    run = queued_run()
    store.create_run(run)
    ref = store.put_artifact(run.run_id, "a.json", kind=ArtifactKind.REPORT, media_type="application/json",
                             data=b"{}")
    twin = replace(ref, path="A.json")
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(run, artifacts=(ref, twin)), expected=run)
    assert caught.value.code == STORE_PATH_UNSAFE


def test_run_deleted_during_listing_is_not_reported_corrupt(store, monkeypatch):
    done = run_at(0, "0000000000000001")
    passed(store, done)
    names, stray = store._entries()
    store.delete_run(done.run_id)
    monkeypatch.setattr(store, "_entries", lambda: (list(names), list(stray)))
    page = store.list_runs()
    assert page.runs == () and page.corrupt == ()


# --------------------------------------------- rework: write-time manifest (S1)

def _running_with(store: FilesystemTestRunStore) -> TestRun:
    run = queued_run()
    store.create_run(run)
    running = transition_run(run, S.RUNNING, at=at(1))
    return store.update_run(running, expected=run)


def test_report_bytes_relabelled_audio_clip_refused_when_audio_not_allowed(store):
    """QA S1 repro: 2 MB put as `report`, referenced as `audio_clip` in a store without audio."""
    running = _running_with(store)
    ref = store.put_artifact(running.run_id, "voice.wav", kind=ArtifactKind.REPORT, media_type="audio/wav",
                             data=b"RIFF" + b"\0" * 2_000_000)
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(running, artifacts=(replace(ref, kind=ArtifactKind.AUDIO_CLIP),)), expected=running)
    assert caught.value.code == STORE_ARTIFACT_REFUSED
    assert store.get_run(running.run_id).artifacts == ()


def test_event_log_relabelled_config_snapshot_over_cap_refused(store):
    """QA S1 repro: 3 MiB `event_log` referenced as `config_snapshot` (cap 1 MiB)."""
    running = _running_with(store)
    ref = store.put_artifact(running.run_id, "big.log", kind=ArtifactKind.EVENT_LOG, media_type="text/plain",
                             data=b"z" * (3 * 1024 * 1024))
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(running, artifacts=(replace(ref, kind=ArtifactKind.CONFIG_SNAPSHOT),)),
                         expected=running)
    assert caught.value.code == STORE_ARTIFACT_TOO_LARGE


@pytest.mark.parametrize("change", [dict(kind=ArtifactKind.METRICS), dict(media_type="text/plain")])
def test_kind_and_media_type_chosen_at_put_are_authoritative(store, change):
    running = _running_with(store)
    ref = store.put_artifact(running.run_id, "report.json", kind=ArtifactKind.REPORT, media_type="application/json",
                             data=b"{}")
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(running, artifacts=(replace(ref, **change),)), expected=running)
    assert caught.value.code == STORE_ARTIFACT_MISMATCH
    assert store.update_run(replace(running, artifacts=(ref,)), expected=running).artifacts == (ref,)


def test_bytes_without_manifest_entry_cannot_be_referenced(store):
    """A crash between moving the bytes and writing the manifest leaves bytes no reference can commit."""
    running = _running_with(store)
    payload = b"orphan"
    (store.runs_dir / running.run_id / "orphan.txt").write_bytes(payload)
    ref = ArtifactRef(ArtifactKind.REPORT, "orphan.txt", "text/plain", hashlib.sha256(payload).hexdigest(), len(payload))
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(running, artifacts=(ref,)), expected=running)
    assert caught.value.code == STORE_ARTIFACT_MISMATCH


def test_store_reopened_without_audio_refuses_audio_reference(tmp_path):
    root = tmp_path / "testlab"
    writer = FilesystemTestRunStore(root, limits=ArtifactWriteLimits(allow_audio=True))
    running = _running_with(writer)
    ref = writer.put_artifact(running.run_id, "clip.wav", kind=ArtifactKind.AUDIO_CLIP, media_type="audio/wav",
                              data=b"RIFF")
    strict = FilesystemTestRunStore(root)
    with pytest.raises(TestLabStoreError) as caught:
        strict.update_run(replace(running, artifacts=(ref,)), expected=running)
    assert caught.value.code == STORE_ARTIFACT_REFUSED


def test_corrupt_manifest_is_typed(store):
    running = _running_with(store)
    ref = store.put_artifact(running.run_id, "r.json", kind=ArtifactKind.REPORT, media_type="application/json",
                             data=b"{}")
    (store.runs_dir / running.run_id / MANIFEST_NAME).write_text('{"schema": 1', encoding="utf-8")
    with pytest.raises(RunRecordCorruptError):
        store.update_run(replace(running, artifacts=(ref,)), expected=running)
    with pytest.raises(RunRecordCorruptError):
        store.put_artifact(running.run_id, "s.json", kind=ArtifactKind.REPORT, media_type="application/json",
                           data=b"{}")


# ------------------------------------------------ rework: path budget (S2)

def test_default_path_budget_matches_host_policy():
    budget = FilesystemTestRunStore(".").max_path_chars
    if os.name == "nt":
        assert budget in (None, 259)
    else:
        assert budget is None


def test_artifact_path_over_budget_is_typed_before_any_write(tmp_path):
    probe = FilesystemTestRunStore(tmp_path / "testlab", max_path_chars=None)
    run = queued_run()
    probe.create_run(run)
    run_dir = probe.runs_dir / run.run_id
    base = len(os.path.abspath(run_dir)) + 1
    store = FilesystemTestRunStore(tmp_path / "testlab", max_path_chars=base + 40)
    assert store.put_artifact(run.run_id, "a" * 40, kind=ArtifactKind.REPORT, media_type="text/plain",
                              data=b"x").size_bytes == 1
    for path in ("b" * 41, "d" * 30 + "/x"):  # file over budget; directory over budget minus 12
        with pytest.raises(TestLabStoreError) as caught:
            store.put_artifact(run.run_id, path, kind=ArtifactKind.REPORT, media_type="text/plain", data=b"x")
        assert caught.value.code == STORE_PATH_UNSAFE
        assert "path budget" in caught.value.detail and str(tmp_path) not in caught.value.detail
    assert sorted(p.name for p in run_dir.iterdir()) == sorted([MANIFEST_NAME, RECORD_NAME, "a" * 40])


def test_create_run_over_budget_creates_nothing(tmp_path):
    root = tmp_path / "testlab"
    store = FilesystemTestRunStore(root, max_path_chars=len(os.path.abspath(root)) + 60)
    with pytest.raises(TestLabStoreError) as caught:
        store.create_run(queued_run())
    assert caught.value.code == STORE_PATH_UNSAFE and str(tmp_path) not in caught.value.detail
    assert not store.runs_dir.exists() or list(store.runs_dir.iterdir()) == []


# ------------------------------------------- rework: environment boundary (5)

def test_create_run_refuses_environment_names_outside_captured_set(store):
    with pytest.raises(TestLabStoreError) as caught:
        store.create_run(queued_run(environment={"os": "windows", "host.name_hash": "abc"}))
    assert caught.value.code == STORE_ENVIRONMENT_REFUSED
    assert "host.name_hash" not in caught.value.detail
    assert store.list_runs().runs == ()


def test_update_run_refuses_environment_names_outside_captured_set(store):
    running = _running_with(store)
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(running, environment={**running.environment, "user.locale": "fr"}), expected=running)
    assert caught.value.code == STORE_ENVIRONMENT_REFUSED


# ----------------------------------------------------------- rework: nits (6)

def test_read_artifact_verifies_the_bytes_it_returns_in_one_read(store, monkeypatch):
    running = _running_with(store)
    ref = store.put_artifact(running.run_id, "r.txt", kind=ArtifactKind.REPORT, media_type="text/plain", data=b"12345")
    store.update_run(replace(running, artifacts=(ref,)), expected=running)
    monkeypatch.setattr(store, "_verify_artifact", lambda *a, **k: pytest.fail("second read"))
    assert store.read_artifact(running.run_id, "r.txt") == b"12345"
    (store.runs_dir / running.run_id / "r.txt").write_bytes(b"54321")
    with pytest.raises(TestLabStoreError) as caught:
        store.read_artifact(running.run_id, "r.txt")
    assert caught.value.code == STORE_ARTIFACT_MISMATCH


def test_sweep_removes_empty_subdirectories_but_never_the_run(store):
    run = queued_run()
    store.create_run(run)
    run_dir = store.runs_dir / run.run_id
    ref = store.put_artifact(run.run_id, "kept/log.txt", kind=ArtifactKind.WORKER_LOG, media_type="text/plain",
                             data=b"x")
    (run_dir / "empty" / "deeper").mkdir(parents=True)
    old = time.time() - 7200
    for path in (run_dir / "empty" / "deeper", run_dir / "empty", run_dir / "kept", run_dir):
        os.utime(path, (old, old))
    assert store.remove_stale_temporaries() == 2
    assert not (run_dir / "empty").exists() and (run_dir / "kept" / "log.txt").exists()
    assert (run_dir / RECORD_NAME).exists() and (run_dir / MANIFEST_NAME).exists()
    store.update_run(replace(run, artifacts=(ref,)), expected=run)
    empty_run = run_at(5, "0000000000000009")
    store.create_run(empty_run)
    os.utime(store.runs_dir / empty_run.run_id, (old, old))
    assert store.remove_stale_temporaries() == 0 and (store.runs_dir / empty_run.run_id).is_dir()


def test_diagnostic_failures_counter_is_thread_safe(tmp_path):
    class Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("sink down")

    store = FilesystemTestRunStore(tmp_path, diagnostics=Broken())
    threads = [threading.Thread(target=lambda: [store._diagnose("k", "m") for _ in range(500)]) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert store.diagnostic_failures == 4000


# ------------------------------------------------------- rework 2: R1 deletion

def test_delete_run_with_artifact_at_the_path_budget_leaves_nothing(tmp_path):
    """R1: the hidden deletion name is never longer than a run id, so rmtree reaches every stored path."""
    store = FilesystemTestRunStore(tmp_path / "testlab")
    budget = store.max_path_chars or 259
    run = queued_run()
    store.create_run(run)
    run_dir = store.runs_dir / run.run_id
    name_chars = budget - len(os.path.abspath(run_dir)) - 1
    if not 1 <= name_chars <= 200:
        pytest.skip("temporary directory too deep or too shallow for a single-segment budget path")
    path = "e" * name_chars
    ref = store.put_artifact(run.run_id, path, kind=ArtifactKind.REPORT, media_type="text/plain", data=b"x")
    assert len(os.path.abspath(run_dir / path)) == budget
    stored = store.update_run(replace(run, artifacts=(ref,)), expected=run)
    store.update_run(transition_run(stored, S.CANCELLED, at=at(5), failure=RunFailure("operator_cancel")),
                     expected=stored)
    store.delete_run(run.run_id)
    assert list(store.runs_dir.iterdir()) == []
    usage = store.storage_usage()
    assert usage.runs == () and usage.corrupt == ()


def test_unfinished_deletion_is_visible_and_retried_by_the_sweep(store, monkeypatch):
    done = run_at(0, "0000000000000001")
    passed(store, done)
    real_rmtree = shutil.rmtree

    def held_open(path, *args, **kwargs):
        raise PermissionError("held open")

    monkeypatch.setattr("jarvis.testlab.filesystem_store.shutil.rmtree", held_open)
    store.delete_run(done.run_id)
    leftovers = [entry.name for entry in store.runs_dir.iterdir()]
    assert len(leftovers) == 1 and leftovers[0].startswith(DELETING_PREFIX)
    assert len(leftovers[0]) <= len(done.run_id)
    for corrupt in (store.list_runs().corrupt, store.storage_usage().corrupt):
        assert [(entry.entry, entry.code) for entry in corrupt] == [(leftovers[0], STORE_DELETION_PENDING)]
    monkeypatch.setattr("jarvis.testlab.filesystem_store.shutil.rmtree", real_rmtree)
    assert store.remove_stale_temporaries() == 1  # retried at any age
    assert list(store.runs_dir.iterdir()) == [] and store.storage_usage().corrupt == ()


# --------------------------------------------------------- rework 2: R2 links

def test_sweep_never_follows_a_junction_out_of_the_store(store, tmp_path):
    run = queued_run()
    store.create_run(run)
    outside = tmp_path / "outside"
    (outside / "emptydir").mkdir(parents=True)
    victim = outside / ".record-0123456789abcdef.tmp"
    victim.write_text("victim", encoding="utf-8")
    (outside / "big.bin").write_bytes(b"z" * 5000)
    old = time.time() - 7200
    for path in (outside / "emptydir", victim, outside):
        os.utime(path, (old, old))
    linked_run = run_at(1, "0000000000000007").run_id
    if not _make_link(store.runs_dir / linked_run, outside):
        pytest.skip("this host cannot create a directory link")
    if not _make_link(store.runs_dir / run.run_id / "inner", outside):
        pytest.skip("this host cannot create a directory link")
    store.remove_stale_temporaries(older_than_s=0)
    assert victim.exists() and (outside / "emptydir").is_dir() and (outside / "big.bin").exists()
    usage = store.storage_usage()
    assert usage.runs[0].total_bytes < 5000  # the inner link's target is not counted
    assert linked_run in [entry.entry for entry in usage.corrupt]


# --------------------------------------- rework 2: environment and manifest

def test_legacy_record_with_foreign_environment_can_still_finish_and_be_deleted(store):
    run = queued_run()
    store.create_run(run)
    legacy = queued_run(environment={"os": "windows", "host.legacy_label": "box"})
    (store.runs_dir / run.run_id / RECORD_NAME).write_bytes(canonical_json(legacy.to_dict()).encode("utf-8"))
    stored = store.get_run(run.run_id)
    with pytest.raises(TestLabStoreError) as caught:
        store.update_run(replace(stored, environment={**stored.environment, "host.other_label": "x"}), expected=stored)
    assert caught.value.code == STORE_ENVIRONMENT_REFUSED
    cancelled = store.update_run(transition_run(stored, S.CANCELLED, at=at(3)), expected=stored)
    assert cancelled.environment["host.legacy_label"] == "box"
    store.delete_run(run.run_id)
    assert store.list_runs().runs == ()


def test_corrupt_manifest_surfaces_in_listing_and_usage_while_run_stays_readable(store):
    running = _running_with(store)
    store.put_artifact(running.run_id, "r.json", kind=ArtifactKind.REPORT, media_type="application/json", data=b"{}")
    (store.runs_dir / running.run_id / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    page = store.list_runs()
    assert [run.run_id for run in page.runs] == [running.run_id]
    assert [(entry.entry, entry.code) for entry in page.corrupt] == [(running.run_id, STORE_CORRUPT)]
    usage = store.storage_usage()
    assert [run.run_id for run in usage.runs] == [running.run_id]
    assert [(entry.entry, entry.code) for entry in usage.corrupt] == [(running.run_id, STORE_CORRUPT)]
    assert store.get_run(running.run_id) == running


def test_sweep_shortens_a_long_deletion_leftover_before_removing_it(store):
    long_name = f"{DELETING_PREFIX}{queued_run().run_id}-0000"
    (store.runs_dir / long_name / "sub").mkdir(parents=True)
    (store.runs_dir / long_name / "sub" / "f.txt").write_bytes(b"x")
    assert store.remove_stale_temporaries() == 1
    assert list(store.runs_dir.iterdir()) == []


# ------------------------------------- listing cache (Slice 07, QA F2 repros)

def test_the_listing_cache_notices_a_terminal_record_that_became_corrupt(store, tmp_path):
    """A cache that trusted immutability switched the Slice 02 corruption mechanism off.

    A terminal record is immutable THROUGH the store, but the file is an ordinary file:
    truncated by a crash, edited by hand or restored from a backup, it becomes corrupt.
    The long-lived supervisor process is exactly where that must still be reported.
    """
    good = passed(store, run_at(0, "0000000000000001"))
    bad = passed(store, run_at(1000, "0000000000000002"))
    first = store.list_runs()
    assert sorted(run.run_id for run in first.runs) == sorted((good.run_id, bad.run_id))
    assert first.corrupt == ()

    (store.runs_dir / bad.run_id / RECORD_NAME).write_bytes(b'{"schema": "jarvis.testlab.run"')

    same_instance = store.list_runs()
    fresh = FilesystemTestRunStore(tmp_path / "testlab").list_runs()
    assert [run.run_id for run in same_instance.runs] == [run.run_id for run in fresh.runs] == [good.run_id]
    assert [entry.entry for entry in same_instance.corrupt] == [entry.entry for entry in fresh.corrupt] == [
        bad.run_id]


def test_the_listing_cache_never_gives_one_process_two_truths(store):
    """`list_runs` must not serve a record that `get_run` in the same process refuses."""
    run = passed(store, run_at(0, "0000000000000003"))
    store.list_runs()  # populates the cache
    (store.runs_dir / run.run_id / RECORD_NAME).write_bytes(b"{}")
    with pytest.raises(RunRecordCorruptError):
        store.get_run(run.run_id)
    page = store.list_runs()
    assert page.runs == () and [entry.entry for entry in page.corrupt] == [run.run_id]


def test_the_listing_cache_reflects_an_edited_terminal_record(store):
    """An edit that still decodes is served as the NEW record, never as the cached one."""
    run = passed(store, run_at(0, "0000000000000004"))
    assert store.list_runs().runs[0].score == 50.0
    edited = json.loads((store.runs_dir / run.run_id / RECORD_NAME).read_text(encoding="utf-8"))
    edited["score"] = 1.0
    (store.runs_dir / run.run_id / RECORD_NAME).write_text(canonical_json(edited), encoding="utf-8")
    assert store.list_runs().runs[0].score == 1.0 == store.get_run(run.run_id).score


def test_the_listing_cache_serves_an_untouched_terminal_record_without_re_reading(store, monkeypatch):
    """The point of the cache: the second listing decodes nothing it already decoded."""
    run = passed(store, run_at(0, "0000000000000005"))
    assert store.list_runs().runs[0].run_id == run.run_id
    reads: list[str] = []
    original = FilesystemTestRunStore._read_record

    def counted(self, run_dir, run_id):
        reads.append(run_id)
        return original(self, run_dir, run_id)

    monkeypatch.setattr(FilesystemTestRunStore, "_read_record", counted)
    assert store.list_runs().runs[0].run_id == run.run_id
    assert reads == []


def test_a_non_terminal_record_is_never_cached(store):
    run = started(store, run_at(0, "0000000000000006"))
    assert store.list_runs().runs[0].status is S.RUNNING
    done = complete_run(run, at=at(200), assertion_results=results_for(PASSING), metrics=PASSING)
    store.update_run(done, expected=run)
    assert store.list_runs().runs[0].status is S.PASSED


def test_a_deleted_run_leaves_the_listing_cache(store):
    run = passed(store, run_at(0, "0000000000000007"))
    store.list_runs()
    store.delete_run(run.run_id)
    assert store.list_runs().runs == ()


def test_the_listing_cache_can_be_switched_off(tmp_path):
    off = FilesystemTestRunStore(tmp_path / "off", listing_cache_size=0)
    run = passed(off, run_at(0, "0000000000000008"))
    off.list_runs()
    assert off._listing_cache == {}
    assert off.list_runs().runs[0].run_id == run.run_id
    with pytest.raises(TypeError):
        FilesystemTestRunStore(tmp_path / "bad", listing_cache_size=-1)


def test_the_listing_cache_is_bounded(tmp_path):
    small = FilesystemTestRunStore(tmp_path / "small", listing_cache_size=2)
    for index in range(4):
        passed(small, run_at(index * 10, f"{index:016x}"))
    small.list_runs()
    assert len(small._listing_cache) == 2
