"""DiagnosticBundle capture service, bounded readers and filesystem bundle store (docs/testlab.md, "DiagnosticBundle")."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import sqlite3

import pytest

from jarvis.domain.conversation_event_store import ConversationEventStoreError
from jarvis.testlab.bundle import SourceStatus
from jarvis.testlab.bundle_builder import SessionSelector
from jarvis.testlab.bundle_capture import (
    ExportEventSource,
    StateDatabaseEventSource,
    StoreEventSource,
    TraceReadLimits,
    capture_diagnostic_bundle,
    project_bundle_trace_entry,
    read_session_events,
    read_session_trace,
    read_voice_session_reports,
)
from jarvis.testlab.filesystem_bundle_store import BUNDLE_NAME, FilesystemBundleStore
from jarvis.testlab.store import (
    BundleConflictError,
    BundleNotFoundError,
    BundlePutStatus,
    BundleQuery,
    BundleRecordCorruptError,
    TestLabStoreError,
)
from tests.fakes import testlab_bundle as fx
from tests.fakes.conversation_events import RecordingDiagnostics, open_store

WINDOW = {"start": fx.at(-30000), "end": fx.at(90000)}


@pytest.fixture
def trace_path(tmp_path):
    path = tmp_path / "trace.jsonl"
    fx.write_trace(path)
    return path


# ------------------------------------------------------------ projection

def test_projection_keeps_allowlisted_scalars_only():
    entry = {"ts": "2026-09-16T10:00:00.000123+00:00", "kind": "voice.barge_in", "level": "info",
             "message": "SECRET words the user said",
             "data": {"speech_id": "s1", "played_ms": 12, "stop_latency_ms": 1.5, "authority": "acoustic",
                      "device_stopped": True, "configuration_id": "a" * 64, "measure": "sk-live-SECRET",
                      "segment_id": "seg/../x", "arguments": {"password": "hunter2"}, "error": "SECRET",
                      "elapsed_ms": float("nan"), "text": "SECRET"}}
    projected = project_bundle_trace_entry(entry)
    assert projected["data"] == {"speech_id": "s1", "played_ms": 12, "stop_latency_ms": 1.5, "authority": "acoustic",
                                 "device_stopped": True, "configuration_id": "a" * 64}
    assert "message" not in projected and "SECRET" not in json.dumps(projected)


# ------------------------------------------------------------ trace reader

def test_window_reader_selects_the_session_and_counts_damage(trace_path):
    result = read_session_trace(trace_path, fx.selector(), **WINDOW)
    evidence = result.evidence
    kinds = [line.kind for line in evidence.lines]
    assert "agent.event" not in kinds and "tool.call" not in kinds
    assert all(line.data.get("conversation_id") in (None, fx.CONVERSATION) for line in evidence.lines)
    assert not any(line.data.get("speech_id") == "s-other" for line in evidence.lines)
    assert (evidence.corrupt_lines, evidence.oversized_lines, evidence.truncated) == (1, 1, False)
    assert evidence.status is SourceStatus.AVAILABLE and evidence.stopped_by == "window_end"
    assert len(result.raw_lines) == len(evidence.lines)
    matched = {line.kind for line in evidence.lines if not line.matched}
    assert "provider.error" in matched  # uncorrelated line kept by time window


def test_reader_stops_at_the_window_end_and_ignores_later_growth(trace_path):
    before = read_session_trace(trace_path, fx.selector(), start=fx.at(-30000), end=fx.at(60000)).evidence
    with open(trace_path, "ab") as handle:
        for index in range(50):
            line = {"ts": fx.at(200000 + index).isoformat(), "kind": "voice.speech.started", "level": "info",
                    "message": "", "data": {"conversation_id": fx.CONVERSATION, "speech_id": f"late-{index}"}}
            handle.write((json.dumps(line) + "\n").encode())
    after = read_session_trace(trace_path, fx.selector(), start=fx.at(-30000), end=fx.at(60000)).evidence
    assert after.stopped_by == "window_end" and after == before


def test_id_only_reader_uses_the_extent_of_matched_lines(trace_path):
    evidence = read_session_trace(trace_path, fx.selector()).evidence
    assert evidence.lines[0].matched and evidence.lines[-1].matched
    assert evidence.lines[-1].kind == "voice.realtime.usage"  # `voice.stop` and later lines (no id) are outside
    assert evidence.start_truncated is False and evidence.status is SourceStatus.AVAILABLE


def test_reader_bounds_are_recorded_as_truncation(trace_path):
    few = read_session_trace(trace_path, fx.selector(), limits=TraceReadLimits(max_selected_lines=5), **WINDOW)
    assert few.evidence.status is SourceStatus.TRUNCATED and few.evidence.stopped_by == "max_selected"
    assert len(few.evidence.lines) == 5
    tail = read_session_trace(trace_path, fx.selector(), limits=TraceReadLimits(max_bytes=4096)).evidence
    assert tail.start_truncated is True and tail.status is SourceStatus.TRUNCATED


def test_bisection_reads_only_near_the_window(tmp_path):
    path = tmp_path / "trace.jsonl"
    filler = [{"ts": fx.at(-3_600_000 + index * 100).isoformat(), "kind": "voice.state.updated", "level": "info",
               "message": "", "data": {"conversation_id": "old"}} for index in range(20000)]
    fx.write_trace(path, filler + fx.session_trace_entries())
    size = path.stat().st_size
    result = read_session_trace(path, fx.selector(), **WINDOW)
    assert result.bytes_read < size / 2
    assert {line.data.get("speech_id") for line in result.evidence.lines} >= {"s1", "s2", "s3", "s4", "s5", "s6"}


def test_missing_trace_is_missing(tmp_path):
    evidence = read_session_trace(tmp_path / "absent.jsonl", fx.selector()).evidence
    assert (evidence.status, evidence.reason) == (SourceStatus.MISSING, "trace_file_missing")


# ------------------------------------------------------ conversation events

async def test_export_source_complete_incomplete_and_invalid(tmp_path):
    path = tmp_path / "events.jsonl"
    fx.write_export(path)
    evidence = await read_session_events(ExportEventSource(path), fx.selector())
    assert (evidence.status, evidence.origin, evidence.export_complete) == (SourceStatus.AVAILABLE, "export", True)
    assert len(evidence.events) == len(fx.session_events())
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:-1]))
    assert (await read_session_events(ExportEventSource(path), fx.selector())).export_complete is False
    path.write_bytes(b"not an export\n")
    invalid = await read_session_events(ExportEventSource(path), fx.selector())
    assert (invalid.status, invalid.reason) == (SourceStatus.UNAVAILABLE, "export_invalid")
    missing = await read_session_events(ExportEventSource(tmp_path / "nope.jsonl"), fx.selector())
    assert missing.status is SourceStatus.MISSING


async def _stored_database(path):
    state, store = await open_store(path)
    events = [stored.event for stored in fx.session_events()]
    for index in range(0, len(events), 32):
        await store.append_many(events[index:index + 32])
    return state, store


async def test_store_source_by_conversation_session_and_window(tmp_path):
    state, store = await _stored_database(tmp_path / "state.sqlite3")
    try:
        total = len(fx.session_events())
        by_conversation = await read_session_events(StoreEventSource(store), fx.selector())
        assert len(by_conversation.events) == total and by_conversation.status is SourceStatus.AVAILABLE
        by_session = await read_session_events(StoreEventSource(store), SessionSelector(session_id=fx.SESSION))
        assert len(by_session.events) > 6  # session-tagged turns plus untagged events inside their extent
        window = await read_session_events(StoreEventSource(store),
                                           SessionSelector(start=fx.at(0), end=fx.at(5000)))
        assert {item.event.speech_id for item in window.events} - {None} == {"s1"}
        unknown = await read_session_events(StoreEventSource(store), SessionSelector(conversation_id="nobody"))
        assert unknown.status is SourceStatus.EMPTY
    finally:
        await state.close()


async def test_state_database_is_read_strictly_read_only(tmp_path):
    path = tmp_path / "state.sqlite3"
    state, _ = await _stored_database(path)
    await state.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence = await read_session_events(StateDatabaseEventSource(path), fx.selector())
    assert evidence.status is SourceStatus.AVAILABLE and len(evidence.events) == len(fx.session_events())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    from jarvis.adapters.sqlite_conversation_events import SQLiteConversationEventStore
    from jarvis.testlab.bundle_capture import ReadOnlyStateDatabase

    writer = SQLiteConversationEventStore(ReadOnlyStateDatabase(path))  # type: ignore[arg-type]
    with pytest.raises(ConversationEventStoreError):
        await writer.append(replace(fx.session_events()[0].event, event_id="cev-" + "f" * 64))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


async def test_state_database_without_the_table_or_file(tmp_path):
    bare = tmp_path / "v1.sqlite3"
    connection = sqlite3.connect(bare)
    connection.execute("CREATE TABLE turns(id TEXT)")
    connection.commit()
    connection.close()
    evidence = await read_session_events(StateDatabaseEventSource(bare), fx.selector())
    assert (evidence.status, evidence.reason) == (SourceStatus.UNAVAILABLE, "conversation_events_table_absent")
    missing = await read_session_events(StateDatabaseEventSource(tmp_path / "nope.sqlite3"), fx.selector())
    assert (missing.status, missing.reason) == (SourceStatus.MISSING, "state_database_missing")


# ------------------------------------------------------------ voice reports

def _report(directory, session_id, **changes):
    payload = {"schema": "jarvis.voice_benchmark.session", "schema_version": 1, "session_id": session_id,
               "architecture": "continuous_brain", "configuration_id": fx.CONFIGURATION,
               "session_fingerprint": "e" * 64, "terminal_status": "stopped", "trace_evidence_complete": True,
               "provider_id": "openai", "annotations": [{"note_fingerprint": "SECRET"}],
               "latency_metrics": {"speech_queue_wait_ms": {"count": 2, "samples_ms": [1.0, 3.0], "min_ms": 1.0,
                                                            "max_ms": 3.0, "mean_ms": 2.0}},
               "event_counts": {"user_interruption": 1}, **changes}
    path = directory / f"{session_id}-0123456789ab.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_voice_session_reports_are_projected_and_filtered(tmp_path):
    _report(tmp_path, fx.SESSION)
    _report(tmp_path, "other-session")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    evidence = read_voice_session_reports(tmp_path, [fx.SESSION])
    assert evidence.status is SourceStatus.AVAILABLE and len(evidence.reports) == 1
    assert evidence.reason == "some_reports_unreadable"  # broken.json cannot be matched, so it is visible
    report = evidence.reports[0]
    assert report.latency == (("speech_queue_wait_ms", 2, 1.0, 3.0, 2.0),) and report.counts == (("user_interruption", 1),)
    assert read_voice_session_reports(tmp_path / "absent", [fx.SESSION]).status is SourceStatus.MISSING
    assert read_voice_session_reports(tmp_path, ["nobody"]).status is SourceStatus.EMPTY


# ------------------------------------------------------------------ service

async def test_capture_builds_stores_and_reimports_idempotently(tmp_path, trace_path):
    export = tmp_path / "events.jsonl"
    fx.write_export(export)
    reports = tmp_path / "reports"
    reports.mkdir()
    _report(reports, fx.SESSION)
    store = FilesystemBundleStore(tmp_path / "testlab", max_path_chars=None)
    diagnostics = RecordingDiagnostics()
    first = await capture_diagnostic_bundle(fx.selector(), captured_at=fx.CAPTURED_AT, trace_path=trace_path,
                                            event_source=ExportEventSource(export), reports_directory=reports,
                                            store=store, diagnostics=diagnostics)
    assert first.put.status is BundlePutStatus.STORED
    document = first.bundle.to_dict()
    assert document["coverage"]["voice_session_reports"] == {"status": "available", "reports": 1, "reason": None}
    assert len(document["anomalies"]["findings"]) == 6
    assert document["aggregates"]["trace_summary"]
    encoded = first.bundle.encode().decode("utf-8")
    assert not [marker for marker in fx.SECRET_MARKERS if marker in encoded]
    assert diagnostics.kinds()[-1] == "testlab_bundle_captured"
    assert "SECRET" not in json.dumps(diagnostics.entries)

    with open(trace_path, "ab") as handle:  # the journal keeps growing after the session
        handle.write((json.dumps({"ts": fx.at(900000).isoformat(), "kind": "voice.start", "level": "info",
                                  "message": "", "data": {}}) + "\n").encode())
    again = await capture_diagnostic_bundle(fx.selector(), captured_at=fx.CAPTURED_AT + timedelta(hours=1),
                                            trace_path=trace_path, event_source=ExportEventSource(export),
                                            reports_directory=reports, store=store)
    assert again.put.status is BundlePutStatus.DUPLICATE and again.bundle.bundle_id == first.bundle.bundle_id
    stored = store.get_bundle(first.bundle.bundle_id)
    assert stored.encode() == first.bundle.encode()  # the first capture is kept


async def test_capture_with_missing_sources_is_explicit(tmp_path):
    diagnostics = RecordingDiagnostics()
    result = await capture_diagnostic_bundle(
        fx.selector(), captured_at=fx.CAPTURED_AT, trace_path=tmp_path / "absent.jsonl",
        event_source=StateDatabaseEventSource(tmp_path / "absent.sqlite3"), diagnostics=diagnostics)
    coverage = result.bundle.to_dict()["coverage"]
    assert coverage["runtime_journal"]["status"] == "missing"
    assert coverage["conversation_events"]["reason"] == "state_database_missing"
    assert coverage["voice_session_reports"]["status"] == "not_requested"
    warnings = [entry for entry in diagnostics.entries if entry[2] == "warning"]
    assert {entry[3]["source"] for entry in warnings} == {"conversation_events", "runtime_journal"}
    assert result.put is None


async def test_capture_of_a_truncated_trace_says_so(tmp_path, trace_path):
    export = tmp_path / "events.jsonl"
    fx.write_export(export)
    result = await capture_diagnostic_bundle(fx.selector(), captured_at=fx.CAPTURED_AT, trace_path=trace_path,
                                             event_source=ExportEventSource(export),
                                             trace_limits=TraceReadLimits(max_selected_lines=8))
    journal = result.bundle.to_dict()["coverage"]["runtime_journal"]
    assert (journal["status"], journal["truncated"], journal["stopped_by"]) == ("truncated", True, "max_selected")


# ------------------------------------------------------------ bundle store

async def _bundle(tmp_path, trace_path, **selector):
    export = tmp_path / "events.jsonl"
    if not export.exists():
        fx.write_export(export)
    return (await capture_diagnostic_bundle(fx.selector(**selector), captured_at=fx.CAPTURED_AT,
                                            trace_path=trace_path, event_source=ExportEventSource(export))).bundle


async def test_bundle_store_layout_get_list_and_errors(tmp_path, trace_path):
    store = FilesystemBundleStore(tmp_path / "testlab", max_path_chars=None)
    full = await _bundle(tmp_path, trace_path)
    early = await _bundle(tmp_path, trace_path, start=fx.at(-30000), end=fx.at(5000))
    for bundle in (full, early):
        assert store.put_bundle(bundle).status is BundlePutStatus.STORED
    assert (tmp_path / "testlab" / "bundles" / full.bundle_id / BUNDLE_NAME).read_bytes() == full.encode()
    page = store.list_bundles(BundleQuery(limit=1))
    assert len(page.bundles) == 1 and page.next_cursor is not None
    rest = store.list_bundles(BundleQuery(limit=1, after_bundle_id=page.next_cursor))
    assert {page.bundles[0].bundle_id, rest.bundles[0].bundle_id} == {full.bundle_id, early.bundle_id}
    assert store.list_bundles(BundleQuery(conversation_id="nobody")).bundles == ()
    assert page.bundles[0].finding_count >= 0
    with pytest.raises(BundleNotFoundError):
        store.get_bundle("tlb-20260916T100000000Z-0000000000000000")
    with pytest.raises(TestLabStoreError) as caught:
        store.get_bundle("../escape")
    assert caught.value.code == "testlab_store_path_unsafe"


async def test_bundle_store_corruption_is_reported_never_skipped(tmp_path, trace_path):
    store = FilesystemBundleStore(tmp_path / "testlab", max_path_chars=None)
    bundle = await _bundle(tmp_path, trace_path)
    store.put_bundle(bundle)
    record = tmp_path / "testlab" / "bundles" / bundle.bundle_id / BUNDLE_NAME
    record.write_bytes(record.read_bytes()[:-10])
    (tmp_path / "testlab" / "bundles" / "stray").mkdir()
    with pytest.raises(BundleRecordCorruptError):
        store.get_bundle(bundle.bundle_id)
    page = store.list_bundles()
    assert page.bundles == () and {entry.code for entry in page.corrupt} == {"testlab_store_corrupt"}
    assert len(page.corrupt) == 2
    with pytest.raises(BundleRecordCorruptError):
        store.put_bundle(bundle)  # never overwrites unreadable evidence


async def test_bundle_store_conflict_on_same_id_with_other_content(tmp_path, trace_path, monkeypatch):
    store = FilesystemBundleStore(tmp_path / "testlab", max_path_chars=None)
    bundle = await _bundle(tmp_path, trace_path)
    store.put_bundle(bundle)

    class Forged:
        bundle_id = bundle.bundle_id
        content_fingerprint = "0" * 64

    monkeypatch.setattr(store, "_read", lambda *_: Forged())
    with pytest.raises(BundleConflictError) as caught:
        store.put_bundle(bundle)
    assert caught.value.code == "testlab_store_conflict"


# -------------------------------------------- rework: damage and open windows (R3, R7)

def _raw_trace(path, lines, *, sep=b"\n", bom=False, tail=b""):
    with open(path, "wb") as handle:
        if bom:
            handle.write(b"\xef\xbb\xbf")
        for line in lines:
            handle.write((line if isinstance(line, bytes) else json.dumps(line).encode()) + sep)
        handle.write(tail)


def _entry(ms, kind, **data):
    return {"ts": fx.at(ms).isoformat(), "kind": kind, "level": "info", "message": "m",
            "data": {"conversation_id": "c", **data}}


GOOD = [_entry(1000, "voice.speech.started", speech_id="a"), _entry(2000, "voice.speech.completed", speech_id="a")]
BAD_UTF8 = b'{"ts": "2026-09-16T10:00:01.500+00:00", "kind": "voice.speech.started", "data": {"x": "\xff"}}'


def test_a_trace_of_undecodable_lines_is_never_empty(tmp_path):
    path = tmp_path / "garbage.jsonl"
    path.write_bytes(b"\xff\xfe not json\r\n" * 50)
    for selector, window in ((SessionSelector(conversation_id="c"), {}),
                             (SessionSelector(start=fx.at(0), end=fx.at(3_600_000)),
                              {"start": fx.at(0), "end": fx.at(3_600_000)})):
        evidence = read_session_trace(path, selector, **window).evidence
        assert (evidence.status, evidence.reason, evidence.corrupt_lines) == (
            SourceStatus.UNAVAILABLE, "no_decodable_lines", 50)
    path.write_bytes(b'{"kind": "voice.start"}\n' * 3)
    evidence = read_session_trace(path, SessionSelector(conversation_id="c")).evidence
    assert (evidence.status, evidence.reason, evidence.untimed_lines) == (SourceStatus.UNAVAILABLE, "no_timed_lines", 3)


def test_bom_cr_only_crlf_and_damage_after_the_last_match(tmp_path):
    selector = SessionSelector(conversation_id="c")
    for name, options in (("bom", {"bom": True}), ("crlf", {"sep": b"\r\n"}), ("cr", {"sep": b"\r"})):
        path = tmp_path / f"{name}.jsonl"
        _raw_trace(path, GOOD, **options)
        evidence = read_session_trace(path, selector).evidence
        assert [line.kind for line in evidence.lines] == ["voice.speech.started", "voice.speech.completed"], name
        assert (evidence.corrupt_lines, evidence.status) == (0, SourceStatus.AVAILABLE), name
    bom = tmp_path / "bom.jsonl"
    assert read_session_trace(bom, selector).evidence.lines[0].offset == 3
    after = tmp_path / "after.jsonl"
    _raw_trace(after, [*GOOD, BAD_UTF8], sep=b"\r\n")
    assert read_session_trace(after, selector).evidence.corrupt_lines == 1


def test_a_torn_final_line_is_not_decoded_and_is_reported(tmp_path):
    path = tmp_path / "torn.jsonl"
    complete = json.dumps(_entry(3000, "voice.speech.queued", speech_id="b")).encode()
    _raw_trace(path, GOOD, tail=complete)  # valid JSON, but no newline yet
    evidence = read_session_trace(path, SessionSelector(conversation_id="c")).evidence
    assert evidence.torn_tail is True and [line.data.get("speech_id") for line in evidence.lines] == ["a", "a"]


def test_window_open_until_a_later_line_exists(tmp_path):
    path = tmp_path / "trace.jsonl"
    _raw_trace(path, GOOD)
    window = {"start": fx.at(0), "end": fx.at(10_000)}
    opened = read_session_trace(path, SessionSelector(conversation_id="c"), **window).evidence
    assert (opened.window_open, opened.stopped_by) == (True, "file_end")
    _raw_trace(path, [*GOOD, _entry(60_000, "voice.start")])
    closed = read_session_trace(path, SessionSelector(conversation_id="c"), **window).evidence
    assert (closed.window_open, closed.stopped_by) == (False, "window_end")


# ------------------------------------------------ rework: store lock sweep (6)

async def test_run_store_sweep_keeps_bundle_locks(tmp_path, trace_path):
    from jarvis.testlab.filesystem_store import FilesystemTestRunStore

    root = tmp_path / "testlab"
    bundles = FilesystemBundleStore(root, max_path_chars=None)
    bundle = await _bundle(tmp_path, trace_path)
    bundles.put_bundle(bundle)
    orphan_run_lock = root / "locks" / "tlr-20260916T100000000Z-0000000000000000.lock"
    orphan_run_lock.write_bytes(b"")
    runs = FilesystemTestRunStore(root, max_path_chars=None)
    assert runs.remove_stale_temporaries() == 1
    assert (root / "locks" / f"{bundle.bundle_id}.lock").exists() and not orphan_run_lock.exists()
