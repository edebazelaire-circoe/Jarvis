"""Durable Conversation Event store (Slice 02): docs/conversation-events.md, section Storage."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import random
import sqlite3

import pytest

from jarvis.adapters import sqlite_state
from jarvis.adapters.sqlite_conversation_events import SQLiteConversationEventStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository, pre_migration_backup_path, rollback_after_failure
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_event_store import (
    LOOKUP_FIELDS, MAX_APPEND_BATCH, MAX_EVENT_PAGE_LIMIT, MAX_RETENTION_CONVERSATIONS_PER_RUN,
    MAX_SUMMARY_PAGE_LIMIT, AppendStatus, ConversationEventRetentionPolicy, ConversationEventStoreError,
    RetentionSkipReason,
)
from jarvis.domain.conversation_events import (
    ConversationEventError, ConversationEventType as T, decode_conversation_event, encode_conversation_event,
    format_event_time, parse_event_time, reconstruct_conversation,
)
from jarvis.domain.v2 import Conversation, ConversationStatus, ConversationTurn, TurnKind
from tests.fakes.conversation_events import BASE, MutableClock, RecordingDiagnostics, make_event, open_store

FIXTURES = Path(__file__).parents[1] / "fixtures"
OVERLAP = FIXTURES / "conversation_events" / "overlapping_conversation.json"
STATE_V1 = FIXTURES / "sqlite_state" / "state_v1.sql"


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "state" / "jarvis.sqlite3"


def fixture_events():
    return [decode_conversation_event(row["event"]) for row in json.loads(OVERLAP.read_text(encoding="utf-8"))["events"]]


async def raw(state: SQLiteStateRepository, sql: str, params=()):
    return await state.run_serialized(lambda conn: conn.execute(sql, params).fetchall())


def ids(page) -> list[str]:
    return [stored.event.event_id for stored in page.events]


# --------------------------------------------------------------- schema

async def test_fresh_state_db_is_v2_wal_and_full_sync(db):
    state, _ = await open_store(db)
    try:
        assert [tuple(r) for r in await raw(state, "SELECT version FROM schema_version")] == [(2,)]
        assert (await raw(state, "PRAGMA journal_mode"))[0][0] == "wal"
        assert (await raw(state, "PRAGMA synchronous"))[0][0] == 2  # FULL
        indexes = {row[0] for row in await raw(state, "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='conversation_events'")}
        assert {f"idx_conversation_events_{name}" for name in LOOKUP_FIELDS} <= indexes
    finally:
        await state.close()


def test_sqlite_lookup_columns_mirror_the_domain_lookup_fields():
    assert sqlite_state._CONVERSATION_EVENT_LOOKUP_COLUMNS == LOOKUP_FIELDS


async def test_v1_database_from_real_schema_upgrades_in_place_without_losing_rows(db):
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.executescript(STATE_V1.read_text(encoding="utf-8"))
    conn.close()
    state, store = await open_store(db)
    try:
        assert [tuple(r) for r in await raw(state, "SELECT version FROM schema_version")] == [(2,)]
        assert (await state.get_conversation("conv-v1")).status is ConversationStatus.CLOSED
        assert [t.content for t in await state.list_turns("conv-v1")] == ["bonjour"]
        assert (await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", conversation_id="conv-v1"))).sequence == 1
    finally:
        await state.close()
    state, store = await open_store(db)  # idempotent re-open: one version row, data intact
    try:
        assert [tuple(r) for r in await raw(state, "SELECT version FROM schema_version")] == [(2,)]
        assert len((await store.list_conversation_events("conv-v1")).events) == 1
    finally:
        await state.close()


async def test_interrupted_migration_rolls_back_and_is_retried(db, monkeypatch):
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.executescript(STATE_V1.read_text(encoding="utf-8"))
    conn.close()
    monkeypatch.setitem(sqlite_state._MIGRATIONS, 2, (*sqlite_state._MIGRATIONS[2], "CREATE TABLE broken ("))
    with pytest.raises(RuntimeError, match="operational state database unavailable"):
        await SQLiteStateRepository(db).initialize()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(1,)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='conversation_events'").fetchall() == []
    finally:
        conn.close()
    monkeypatch.undo()
    state, store = await open_store(db)
    try:
        assert [tuple(r) for r in await raw(state, "SELECT version FROM schema_version")] == [(2,)]
        assert (await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"))).status is AppendStatus.APPENDED
    finally:
        await state.close()


async def test_newer_schema_is_refused_and_old_binary_refuses_v2(db, monkeypatch):
    state, _ = await open_store(db)
    await state.close()
    monkeypatch.setattr(sqlite_state, "_SCHEMA_VERSION", 1)  # the pre-Slice-02 binary
    with pytest.raises(RuntimeError, match="state DB schema 2 is newer than supported 1"):
        await SQLiteStateRepository(db).initialize()
    monkeypatch.undo()
    conn = sqlite3.connect(db)
    conn.execute("UPDATE schema_version SET version=3")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="state DB schema 3 is newer than supported 2"):
        await SQLiteStateRepository(db).initialize()


# ------------------------------------------------------ append semantics

async def test_overlapping_conversation_round_trips_with_spans_and_durations(db):
    events = fixture_events()
    shuffled = events[:]
    random.Random(2).shuffle(shuffled)
    state, store = await open_store(db)
    try:
        results = await store.append_many(shuffled[:7]) + await store.append_many(shuffled[7:])
        assert [r.sequence for r in results] == list(range(1, len(events) + 1))
        assert {r.status for r in results} == {AppendStatus.APPENDED}
        page = await store.list_conversation_events("conv-demo", limit=MAX_EVENT_PAGE_LIMIT)
        assert [s.event for s in page.events] == shuffled  # sequence = append order, payload identical
        assert reconstruct_conversation(s.event for s in page.events) == reconstruct_conversation(events)
    finally:
        await state.close()


async def test_identical_duplicate_is_a_noop_returning_the_stored_sequence(db):
    diagnostics = RecordingDiagnostics()
    state, store = await open_store(db, diagnostics=diagnostics)
    try:
        event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1")
        first = await store.append(event)
        await store.append(make_event(T.BRAIN_TURN_ACCEPTED, "b1"))
        # A producer retry rebuilds the same fact: an equal, distinct object.
        again = await store.append(decode_conversation_event(json.loads(json.dumps(encode_conversation_event(event)))))
        assert (first.status, again.status, again.sequence) == (AppendStatus.APPENDED, AppendStatus.DUPLICATE, 1)
        assert (await raw(state, "SELECT count(*) FROM conversation_events"))[0][0] == 2
        assert diagnostics.entries == []
    finally:
        await state.close()


async def test_conflict_keeps_first_copy_reports_status_and_diagnoses_without_content(db):
    diagnostics = RecordingDiagnostics()
    state, store = await open_store(db, diagnostics=diagnostics)
    try:
        event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", content="premier texte")
        await store.append(event)
        retry = replace(event, occurred_at=event.occurred_at + timedelta(seconds=1), content="second texte")
        result = await store.append(retry)
        assert (result.status, result.sequence) == (AppendStatus.CONFLICT, 1)
        assert (await store.get_event(event.event_id)).event == event
        [(kind, _, level, data)] = diagnostics.entries
        assert (kind, level) == ("core.conversation_events.append_conflict", "warning")
        assert data == {"event_id": event.event_id, "stored_sequence": 1, "reason": "payload_differs",
                        "conversation_id": "conv-a", "event_type": "user.transcript.accepted",
                        "producer": "test.producer"}
        assert "texte" not in json.dumps(data)
    finally:
        await state.close()


async def test_broken_diagnostic_sink_never_fails_the_append(db):
    state, store = await open_store(db, diagnostics=RecordingDiagnostics(fail=True))
    try:
        event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1")
        await store.append(event)
        result = await store.append(replace(event, content="autre"))
        assert result.status is AppendStatus.CONFLICT
        assert store.diagnostic_failures == 1
    finally:
        await state.close()


async def test_duplicate_and_conflict_inside_one_batch(db):
    state, store = await open_store(db, diagnostics=RecordingDiagnostics())
    try:
        event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1")
        results = await store.append_many([event, event, replace(event, content="autre")])
        assert [(r.status, r.sequence) for r in results] == [
            (AppendStatus.APPENDED, 1), (AppendStatus.DUPLICATE, 1), (AppendStatus.CONFLICT, 1)]
    finally:
        await state.close()


async def test_invalid_input_is_rejected_before_storage(db):
    state, store = await open_store(db)
    try:
        with pytest.raises(ConversationEventError):
            await store.append_many([make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"), {"event_type": "user.transcript.accepted"}])
        assert (await raw(state, "SELECT count(*) FROM conversation_events"))[0][0] == 0
    finally:
        await state.close()


async def test_failure_mid_batch_rolls_back_every_event_of_the_batch(db):
    state, store = await open_store(db)
    try:
        before = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u0")
        await store.append(before)
        batch = [make_event(T.BRAIN_TURN_ACCEPTED, f"b{i}", ms=i) for i in range(5)]
        await state.run_serialized(lambda conn: conn.execute(
            "CREATE TEMP TRIGGER fail_third BEFORE INSERT ON conversation_events "
            f"WHEN NEW.event_id = '{batch[2].event_id}' BEGIN SELECT RAISE(ABORT, 'disk gone'); END"))
        with pytest.raises(ConversationEventStoreError, match="append failed.*disk gone"):
            await store.append_many(batch)
        assert ids(await store.list_conversation_events("conv-a")) == [before.event_id]
        await state.run_serialized(lambda conn: conn.execute("DROP TRIGGER temp.fail_third"))
        results = await store.append_many(batch)  # a retry after the failure is safe and complete
        assert [r.status for r in results] == [AppendStatus.APPENDED] * 5
        assert results[0].sequence > 1
    finally:
        await state.close()


async def test_closed_repository_refuses_appends(db):
    state, store = await open_store(db)
    await state.close()
    with pytest.raises(RuntimeError, match="not initialized"):
        await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"))


async def test_events_survive_close_and_reopen_and_sequence_continues(db):
    state, store = await open_store(db)
    first = await store.append_many([make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"), make_event(T.BRAIN_TURN_ACCEPTED, "b1")])
    await state.close()
    state, store = await open_store(db)
    try:
        assert ids(await store.list_conversation_events("conv-a")) == [r.event_id for r in first]
        assert (await store.append(make_event(T.BRAIN_TURN_ACCEPTED, "b2"))).sequence == 3
    finally:
        await state.close()


# ------------------------------------------------------- order and cursor

async def test_sequence_order_wins_over_occurred_at_and_pagination_is_stable(db):
    state, store = await open_store(db)
    try:
        # Out-of-order and equal producer clocks.
        events = [make_event(T.BRAIN_TURN_ACCEPTED, f"b{i}", ms=ms) for i, ms in enumerate([500, 100, 100, 100, 0, 900, 100])]
        for event in events:
            await store.append(event)
        await store.append(make_event(T.BRAIN_TURN_ACCEPTED, "other", conversation_id="conv-b"))
        whole = await store.list_conversation_events("conv-a", limit=MAX_EVENT_PAGE_LIMIT)
        assert ids(whole) == [e.event_id for e in events]
        assert (whole.has_more, whole.next_cursor) == (False, 7)

        collected, cursor, pages = [], 0, 0
        while True:
            page = await store.list_conversation_events("conv-a", after_sequence=cursor, limit=2)
            collected += ids(page)
            cursor, pages = page.next_cursor, pages + 1
            if pages == 2:  # events appended while a reader pages arrive after, never before, its cursor
                late = make_event(T.BRAIN_TURN_ACCEPTED, "late", ms=-1000)
                await store.append(late)
            if not page.has_more:
                break
        assert collected == [e.event_id for e in events] + [late.event_id]
        empty = await store.list_conversation_events("conv-a", after_sequence=cursor)
        assert (empty.events, empty.next_cursor, empty.has_more) == ((), cursor, False)
    finally:
        await state.close()


async def test_time_range_lookup_and_get_queries(db):
    state, store = await open_store(db)
    try:
        events = [
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", ms=0, session_id="sess-1"),
            make_event(T.BRAIN_WORK_STARTED, "w1", ms=1000),
            make_event(T.SUBAGENT_STARTED, "t1", ms=1500, work_id="work-w1"),
            make_event(T.BRAIN_MESSAGE_PUBLISHED, "m1", ms=2000),
            make_event(T.MOUTH_SPEECH_STARTED, "s1", ms=3000, session_id="sess-1"),
            make_event(T.BRAIN_WORK_STARTED, "w1", ms=1000, conversation_id="conv-b"),
        ]
        await store.append_many(events)
        in_range = await store.list_events_in_time_range(BASE + timedelta(seconds=1), BASE + timedelta(seconds=3))
        assert ids(in_range) == [events[1].event_id, events[2].event_id, events[3].event_id, events[5].event_id]
        scoped = await store.list_events_in_time_range(BASE, BASE + timedelta(seconds=3), conversation_id="conv-b")
        assert ids(scoped) == [events[5].event_id]
        assert ids(await store.list_events_by_id("work_id", "work-w1")) == [events[1].event_id, events[2].event_id, events[5].event_id]
        assert ids(await store.list_events_by_id("work_id", "work-w1", conversation_id="conv-a")) == [events[1].event_id, events[2].event_id]
        assert ids(await store.list_events_by_id("span_id", "task-t1")) == [events[2].event_id]
        assert ids(await store.list_events_by_id("task_id", "task-t1")) == [events[2].event_id]
        assert ids(await store.list_events_by_id("outcome_id", "outcome-m1")) == [events[3].event_id]
        assert ids(await store.list_events_by_id("speech_id", "speech-s1")) == [events[4].event_id]
        assert ids(await store.list_events_by_id("session_id", "sess-1")) == [events[0].event_id, events[4].event_id]
        assert ids(await store.list_events_by_id("turn_id", "turn-u1")) == [events[0].event_id]
        assert ids(await store.list_events_by_id("correlation_id", "corr-m1")) == [events[3].event_id]
        stored = await store.get_event(events[2].event_id)
        assert (stored.sequence, stored.event) == (3, events[2])
        assert await store.get_event("cev-" + "0" * 64) is None
        with pytest.raises(ValueError, match="lookup field"):
            await store.list_events_by_id("data", "x")
        with pytest.raises(ValueError, match="lookup field"):
            await store.list_events_by_id("conversation_id; DROP TABLE conversation_events", "x")
        with pytest.raises(ValueError, match="start must not be after end"):
            await store.list_events_in_time_range(BASE + timedelta(seconds=1), BASE)
        with pytest.raises(ValueError, match="timezone-aware"):
            await store.list_events_in_time_range(BASE.replace(tzinfo=None), BASE)
    finally:
        await state.close()


async def test_conversation_and_session_listings(db):
    clock = MutableClock()
    state, store = await open_store(db, clock=clock)
    try:
        await store.append_many([
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "a1", conversation_id="conv-a", ms=500, session_id="s1"),
            make_event(T.BRAIN_TURN_ACCEPTED, "a2", conversation_id="conv-a", ms=100),
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "b1", conversation_id="conv-b", ms=50, session_id="s9"),
            make_event(T.MOUTH_SPEECH_STARTED, "a3", conversation_id="conv-a", ms=900, session_id="s2"),
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "c1", conversation_id="conv-c", ms=0),
        ])
        page = await store.list_conversations(limit=2)
        assert [s.conversation_id for s in page.summaries] == ["conv-c", "conv-a"]
        conv_a = page.summaries[1]
        assert (conv_a.event_count, conv_a.first_sequence, conv_a.last_sequence) == (3, 1, 4)
        assert (conv_a.first_occurred_at, conv_a.last_occurred_at) == (BASE + timedelta(milliseconds=100), BASE + timedelta(milliseconds=900))
        assert conv_a.last_recorded_at == BASE
        assert (page.next_cursor, page.has_more) == (4, True)
        rest = await store.list_conversations(before_sequence=page.next_cursor, limit=2)
        assert ([s.conversation_id for s in rest.summaries], rest.has_more) == (["conv-b"], False)

        sessions = await store.list_sessions("conv-a")
        assert [(s.session_id, s.event_count) for s in sessions.summaries] == [("s1", 1), (None, 1), ("s2", 1)]
        second = await store.list_sessions("conv-a", after_sequence=sessions.summaries[0].first_sequence, limit=1)
        assert ([s.session_id for s in second.summaries], second.has_more) == ([None], True)
        assert (await store.list_sessions("conv-z")).summaries == ()
    finally:
        await state.close()


@pytest.mark.parametrize("call", [
    lambda s: s.list_conversation_events("conv-a", limit=0),
    lambda s: s.list_conversation_events("conv-a", limit=MAX_EVENT_PAGE_LIMIT + 1),
    lambda s: s.list_conversation_events("conv-a", limit=True),
    lambda s: s.list_conversation_events("conv-a", after_sequence=-1),
    lambda s: s.list_conversation_events(""),
    lambda s: s.list_events_by_id("work_id", "", limit=1),
    lambda s: s.list_conversations(limit=MAX_SUMMARY_PAGE_LIMIT + 1),
    lambda s: s.list_conversations(before_sequence=-5),
    lambda s: s.list_sessions("conv-a", limit=0),
    lambda s: s.append_many([make_event(T.BRAIN_TURN_ACCEPTED, f"b{i}") for i in range(MAX_APPEND_BATCH + 1)]),
])
async def test_limits_are_enforced(db, call):
    state, store = await open_store(db)
    try:
        with pytest.raises(ValueError):
            await call(store)
        assert await store.append_many([]) == ()
    finally:
        await state.close()


# -------------------------------------------------------- corrupt rows

async def test_undecodable_rows_are_skipped_counted_and_diagnosed_once(db):
    diagnostics = RecordingDiagnostics()
    state, store = await open_store(db, diagnostics=diagnostics)
    try:
        events = [make_event(T.BRAIN_TURN_ACCEPTED, f"b{i}", ms=i) for i in range(6)]
        await store.append_many(events)
        forged = json.loads((await raw(state, "SELECT data FROM conversation_events WHERE sequence=3"))[0][0])
        forged["attributes"] = {"reasoning": "secret chain of thought"}
        await raw(state, "UPDATE conversation_events SET data='{\"truncated' WHERE sequence=2")
        await raw(state, "UPDATE conversation_events SET data=? WHERE sequence=3", (json.dumps(forged),))
        await raw(state, "UPDATE conversation_events SET event_type='user.transcript.accepted' WHERE sequence=4")
        await raw(state, "UPDATE conversation_events SET recorded_at='yesterday' WHERE sequence=5")

        page = await store.list_conversation_events("conv-a", limit=5)
        assert ids(page) == [events[0].event_id]
        assert (page.skipped_rows, page.next_cursor, page.has_more) == (4, 5, True)
        assert ids(await store.list_conversation_events("conv-a", after_sequence=page.next_cursor)) == [events[5].event_id]
        reasons = [(e[2], e[3]["sequence"], e[3]["reason"]) for e in diagnostics.entries]
        assert reasons == [("error", 2, "invalid_json"), ("error", 3, "invalid_event"),
                           ("error", 4, "column_mismatch"), ("error", 5, "invalid_recorded_at")]
        assert "secret" not in json.dumps(diagnostics.entries)

        await store.list_conversation_events("conv-a", limit=5)  # live polling re-reads
        assert (len(diagnostics.entries), store.unreadable_rows) == (4, 8)
        assert await store.get_event(events[1].event_id) is None
        result = await store.append(events[1])
        assert (result.status, result.sequence) == (AppendStatus.CONFLICT, 2)
        assert diagnostics.entries[-1][3]["reason"] == "stored_copy_unreadable"
    finally:
        await state.close()


# --------------------------------------------------------- concurrency

async def test_concurrent_appends_from_two_connections_get_unique_sequences(db):
    state_a, store_a = await open_store(db)
    state_b, store_b = await open_store(db)
    try:
        own_a = [make_event(T.BRAIN_TURN_ACCEPTED, f"a{i}") for i in range(25)]
        own_b = [make_event(T.BRAIN_TURN_ACCEPTED, f"b{i}") for i in range(25)]
        shared = [make_event(T.USER_TRANSCRIPT_ACCEPTED, f"s{i}") for i in range(10)]
        calls = [store_a.append(e) for e in own_a] + [store_b.append(e) for e in own_b]
        calls += [store_a.append(e) for e in shared] + [store_b.append(e) for e in shared]
        random.Random(7).shuffle(calls)
        results = await asyncio.gather(*calls)
        appended = [r for r in results if r.status is AppendStatus.APPENDED]
        assert len(appended) == 60 and len({r.sequence for r in appended}) == 60
        by_id: dict[str, list] = {}
        for r in results:
            by_id.setdefault(r.event_id, []).append(r)
        for event in shared:
            statuses = sorted(r.status.value for r in by_id[event.event_id])
            assert statuses == ["appended", "duplicate"]
            assert len({r.sequence for r in by_id[event.event_id]}) == 1
        page = await store_b.list_conversation_events("conv-a", limit=MAX_EVENT_PAGE_LIMIT)
        assert [s.sequence for s in page.events] == sorted(r.sequence for r in appended)
    finally:
        await state_a.close()
        await state_b.close()


# ----------------------------------------------------------- retention

async def _conversation(state, conversation_id: str, status: ConversationStatus) -> None:
    await state.save_conversation(replace(Conversation(id=conversation_id), status=status))


async def test_retention_is_disabled_by_default(db):
    state, store = await open_store(db)
    try:
        await _conversation(state, "conv-a", ConversationStatus.CLOSED)
        await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"))
        report = await store.apply_retention(ConversationEventRetentionPolicy())
        assert (report.enabled, report.cutoff, report.pruned, report.skipped) == (False, None, (), ())
        assert (await raw(state, "SELECT count(*) FROM conversation_events"))[0][0] == 1
    finally:
        await state.close()


def test_retention_policy_is_validated():
    for bad in ({"enabled": 1}, {"max_age": timedelta(0)}, {"max_age": 30},
                {"max_conversations_per_run": MAX_RETENTION_CONVERSATIONS_PER_RUN + 1}):
        with pytest.raises(ValueError):
            ConversationEventRetentionPolicy(**bad)


async def test_retention_prunes_only_closed_idle_conversations_with_closed_spans(db):
    clock = MutableClock(BASE)
    diagnostics = RecordingDiagnostics()
    state, store = await open_store(db, diagnostics=diagnostics, clock=clock)
    try:
        for cid, status in [("old-closed", ConversationStatus.CLOSED), ("old-active", ConversationStatus.ACTIVE),
                            ("old-open-span", ConversationStatus.CLOSED), ("recent-closed", ConversationStatus.CLOSED),
                            ("archive-fails", ConversationStatus.CLOSED), ("grows", ConversationStatus.CLOSED)]:
            await _conversation(state, cid, status)
        await state.save_turn(ConversationTurn(conversation_id="old-closed", kind=TurnKind.USER, content="bonjour", correlation_id="c"))
        for cid in ("old-closed", "old-active", "archive-fails", "grows", "no-conversation-row"):
            await store.append_many([make_event(T.BRAIN_WORK_STARTED, f"{cid}-w", conversation_id=cid),
                                     make_event(T.BRAIN_WORK_COMPLETED, f"{cid}-w", conversation_id=cid, ms=10,
                                                work_id=f"work-{cid}-w", span_id=f"work-{cid}-w")])
        await store.append(make_event(T.SUBAGENT_STARTED, "t", conversation_id="old-open-span"))
        clock.now = BASE + timedelta(days=40)
        await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", conversation_id="recent-closed"))
        highest = (await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "last", conversation_id="old-closed"))).sequence
        # `old-closed` just got activity: move the last event's record time back to the idle window.
        await raw(state, "UPDATE conversation_events SET recorded_at='2026-09-16T10:00:00.000Z' WHERE sequence=?", (highest,))
        clock.now = BASE + timedelta(days=45)

        archived = []

        async def archive(summary):
            archived.append(summary.conversation_id)
            if summary.conversation_id == "archive-fails":
                raise OSError("archive volume offline")
            if summary.conversation_id == "grows":
                await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "during-archive", conversation_id="grows"))

        report = await store.apply_retention(ConversationEventRetentionPolicy(enabled=True, max_age=timedelta(days=30)),
                                             archive=archive)
        assert report.cutoff == BASE + timedelta(days=15)
        assert report.pruned == (("old-closed", 3),)
        assert dict(report.skipped) == {"archive-fails": RetentionSkipReason.ARCHIVE_FAILED,
                                        "grows": RetentionSkipReason.NEW_ACTIVITY}
        assert (report.blocked_open_span, report.blocked_unreadable) == (1, 0)  # old-open-span, never selected
        assert "old-open-span" not in archived and "old-active" not in archived
        remaining = {row[0] for row in await raw(state, "SELECT DISTINCT conversation_id FROM conversation_events")}
        assert remaining == {"old-active", "old-open-span", "recent-closed", "archive-fails", "grows", "no-conversation-row"}
        assert [t.content for t in await state.list_turns("old-closed")] == ["bonjour"]  # other tables untouched
        assert (await state.get_conversation("old-closed")) is not None
        kinds = diagnostics.kinds()
        assert kinds.count("core.conversation_events.archive_failed") == 1
        assert kinds[-1] == "core.conversation_events.retention_applied"
        assert diagnostics.entries[-1][3]["events_deleted"] == 3
        # Pruning the highest row never lets a sequence be reused.
        assert (await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "after-prune", conversation_id="old-closed"))).sequence > highest + 1
    finally:
        await state.close()


async def test_retention_never_prunes_a_conversation_reopened_before_delete(db):
    clock = MutableClock(BASE)
    state, store = await open_store(db, clock=clock)
    try:
        await _conversation(state, "conv-a", ConversationStatus.CLOSED)
        await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"))
        clock.now = BASE + timedelta(days=365)

        async def archive(summary):
            await _conversation(state, "conv-a", ConversationStatus.ACTIVE)

        report = await store.apply_retention(ConversationEventRetentionPolicy(enabled=True, max_age=timedelta(days=1)),
                                             archive=archive)
        assert (report.pruned, report.skipped) == ((), (("conv-a", RetentionSkipReason.NOT_CLOSED),))
        assert (await raw(state, "SELECT count(*) FROM conversation_events"))[0][0] == 1
    finally:
        await state.close()


# ---------------------------------------------------------- composition

async def test_core_composition_constructs_the_store_on_the_state_db(tmp_path):
    app = JarvisCoreApplication(data_root=tmp_path)
    assert isinstance(app.conversation_events, SQLiteConversationEventStore)
    await app.state.initialize()
    try:
        assert (await app.conversation_events.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"))).sequence == 1
        assert (tmp_path / "state" / "jarvis.sqlite3").is_file()
    finally:
        await app.state.close()


async def test_sequence_is_never_reused_after_pruning_the_newest_rows(db):
    clock = MutableClock(BASE)
    state, store = await open_store(db, clock=clock)
    try:
        await _conversation(state, "conv-a", ConversationStatus.CLOSED)
        results = await store.append_many([make_event(T.BRAIN_TURN_ACCEPTED, f"b{i}") for i in range(3)])
        clock.now = BASE + timedelta(days=2)
        report = await store.apply_retention(ConversationEventRetentionPolicy(enabled=True, max_age=timedelta(days=1)))
        assert report.pruned == (("conv-a", 3),)
        assert (await raw(state, "SELECT count(*) FROM conversation_events"))[0][0] == 0
        # A reader holding cursor 3 must never miss the next event.
        assert (await store.append(make_event(T.BRAIN_TURN_ACCEPTED, "next"))).sequence == results[-1].sequence + 1
        assert len((await store.list_conversation_events("conv-a", after_sequence=3)).events) == 1
    finally:
        await state.close()


# ------------------------------------------------- rework (QA APPROVE_WITH_ISSUES)

def _v1_file(db: Path) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.executescript(STATE_V1.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _inspect(path: Path, sql: str):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_parse_event_time_is_the_strict_inverse_of_format_event_time():
    assert parse_event_time(format_event_time(BASE + timedelta(milliseconds=7))) == BASE + timedelta(milliseconds=7)
    for bad in (None, "garbage", "2026-13-01T00:00:00.000Z", "2026-09-16T10:00:00+00:00", "2026-09-16T10:00:00.000"):
        with pytest.raises(ConversationEventError, match="recorded_at"):
            parse_event_time(bad, "recorded_at")


async def test_summary_listings_skip_groups_whose_times_do_not_parse(db):
    diagnostics = RecordingDiagnostics()
    state, store = await open_store(db, diagnostics=diagnostics)
    try:
        await store.append_many([
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "a1", conversation_id="conv-a", session_id="s1"),
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "b1", conversation_id="conv-b", session_id="s1"),
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "b2", conversation_id="conv-b", session_id="s2"),
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "c1", conversation_id="conv-c"),
        ])
        await raw(state, "UPDATE conversation_events SET occurred_at='garbage' WHERE sequence=3")
        await raw(state, "UPDATE conversation_events SET data='{broken' WHERE sequence=1")

        page = await store.list_conversations()
        assert [s.conversation_id for s in page.summaries] == ["conv-c", "conv-a"]
        assert (page.skipped_summaries, page.next_cursor, page.has_more) == (1, 1, False)
        assert page.summaries[1].event_count == 1  # raw row count: the undecodable row still counts
        # The cursor comes from integer sequences, so paging walks past the skipped group.
        first = await store.list_conversations(limit=1)
        middle = await store.list_conversations(before_sequence=first.next_cursor, limit=1)
        assert (middle.summaries, middle.skipped_summaries, middle.next_cursor, middle.has_more) == ((), 1, 3, True)
        last = await store.list_conversations(before_sequence=middle.next_cursor, limit=1)
        assert [s.conversation_id for s in last.summaries] == ["conv-a"]

        sessions = await store.list_sessions("conv-b")
        assert ([s.session_id for s in sessions.summaries], sessions.skipped_summaries, sessions.next_cursor) == (["s1"], 1, 3)
        await store.list_sessions("conv-b")
        entries = [e for e in diagnostics.entries if e[0] == "core.conversation_events.summary_unreadable"]
        assert [(e[2], e[3]["conversation_id"], e[3]["session_id"]) for e in entries] == [
            ("error", "conv-b", None), ("error", "conv-b", "s2")]  # once per group, despite repeated reads
        assert "garbage" not in json.dumps(diagnostics.entries)
    finally:
        await state.close()


async def test_retention_blocks_conversations_with_unreadable_rows(db):
    clock = MutableClock(BASE)
    state, store = await open_store(db, clock=clock)
    try:
        cases = {"bad-time": "UPDATE conversation_events SET occurred_at='garbage' WHERE conversation_id='bad-time'",
                 "bad-calendar": "UPDATE conversation_events SET recorded_at='0000-99-99T00:00:00.000Z' WHERE conversation_id='bad-calendar'",
                 "bad-json": "UPDATE conversation_events SET data='{' WHERE conversation_id='bad-json'",
                 "bad-type": "UPDATE conversation_events SET event_type='user.transcript.renamed' WHERE conversation_id='bad-type'"}
        for cid in [*cases, "fine"]:
            await _conversation(state, cid, ConversationStatus.CLOSED)
            await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, cid, conversation_id=cid))
        for sql in cases.values():
            await raw(state, sql)
        clock.now = BASE + timedelta(days=10)
        report = await store.apply_retention(ConversationEventRetentionPolicy(enabled=True, max_age=timedelta(days=1),
                                                                              max_conversations_per_run=1))
        assert (report.pruned, report.skipped, report.blocked_unreadable, report.blocked_open_span) == (
            (("fine", 1),), (), 4, 0)
        remaining = {row[0] for row in await raw(state, "SELECT DISTINCT conversation_id FROM conversation_events")}
        assert remaining == set(cases)
    finally:
        await state.close()


async def test_blocked_conversations_never_starve_retention(db):
    clock = MutableClock(BASE)
    state, store = await open_store(db, clock=clock)
    try:
        for i in range(3):  # crash-orphaned sub-agent spans, oldest sequences
            await _conversation(state, f"stuck-{i}", ConversationStatus.CLOSED)
            await store.append(make_event(T.SUBAGENT_STARTED, f"stuck-{i}", conversation_id=f"stuck-{i}"))
        for i in range(3):
            await _conversation(state, f"done-{i}", ConversationStatus.CLOSED)
            await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, f"done-{i}", conversation_id=f"done-{i}"))
        clock.now = BASE + timedelta(days=10)
        policy = ConversationEventRetentionPolicy(enabled=True, max_age=timedelta(days=1), max_conversations_per_run=3)
        first = await store.apply_retention(policy)
        assert (first.pruned, first.blocked_open_span) == ((("done-0", 1), ("done-1", 1), ("done-2", 1)), 3)
        second = await store.apply_retention(policy)
        assert (second.pruned, second.skipped, second.blocked_open_span) == ((), (), 3)
        remaining = {row[0] for row in await raw(state, "SELECT DISTINCT conversation_id FROM conversation_events")}
        assert remaining == {"stuck-0", "stuck-1", "stuck-2"}  # orphaned spans are kept, never auto-closed
    finally:
        await state.close()


@pytest.mark.parametrize(("damage", "reason"), [
    ("UPDATE conversation_events SET data='{' WHERE conversation_id='conv-a'", RetentionSkipReason.UNREADABLE),
    ("UPDATE conversation_events SET span_id='work-other' WHERE event_type='brain.work.completed'", RetentionSkipReason.OPEN_SPAN),
])
async def test_retention_recheck_inside_the_delete_transaction(db, damage, reason):
    clock = MutableClock(BASE)
    state, store = await open_store(db, clock=clock)
    try:
        await _conversation(state, "conv-a", ConversationStatus.CLOSED)
        await store.append_many([make_event(T.BRAIN_WORK_STARTED, "w"),
                                 make_event(T.BRAIN_WORK_COMPLETED, "w", ms=5)])
        clock.now = BASE + timedelta(days=10)

        async def archive(summary):
            await raw(state, damage)

        report = await store.apply_retention(ConversationEventRetentionPolicy(enabled=True, max_age=timedelta(days=1)),
                                             archive=archive)
        assert (report.pruned, report.skipped) == ((), (("conv-a", reason),))
        assert (await raw(state, "SELECT count(*) FROM conversation_events"))[0][0] == 2
    finally:
        await state.close()


async def test_existing_v1_db_is_backed_up_once_before_migration(db):
    _v1_file(db)
    backup = pre_migration_backup_path(db, 1)
    assert backup.name == "jarvis.sqlite3.v1.bak"
    state, _ = await open_store(db)
    await state.close()
    assert _inspect(backup, "SELECT version FROM schema_version") == [(1,)]
    assert _inspect(backup, "SELECT id, conversation_id FROM turns") == [("turn-v1", "conv-v1")]
    assert _inspect(backup, "SELECT name FROM sqlite_master WHERE name='conversation_events'") == []
    assert _inspect(backup, "PRAGMA quick_check") == [("ok",)]
    assert not backup.with_name(backup.name + ".partial").exists()
    copied = backup.read_bytes()
    state, _ = await open_store(db)  # already v2: no new backup
    await state.close()
    assert backup.read_bytes() == copied
    assert sorted(p.name for p in db.parent.glob("*.bak")) == ["jarvis.sqlite3.v1.bak"]


async def test_fresh_database_gets_no_backup(db):
    state, _ = await open_store(db)
    await state.close()
    assert list(db.parent.glob("*.bak*")) == []


async def test_existing_backup_is_never_overwritten(db):
    _v1_file(db)
    backup = pre_migration_backup_path(db, 1)
    backup.write_bytes(b"first pre-migration copy")
    state, _ = await open_store(db)
    try:
        assert [tuple(r) for r in await raw(state, "SELECT version FROM schema_version")] == [(2,)]
    finally:
        await state.close()
    assert backup.read_bytes() == b"first pre-migration copy"


async def test_backup_failure_aborts_the_migration_and_leaves_v1_untouched(db):
    _v1_file(db)
    backup = pre_migration_backup_path(db, 1)
    blocker = backup.with_name(backup.name + ".partial")
    blocker.mkdir()  # the temporary backup file cannot be created
    (blocker / "keep").write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"pre-migration backup to jarvis.sqlite3.v1.bak failed, migration aborted"):
        await SQLiteStateRepository(db).initialize()
    assert not backup.exists()
    assert _inspect(db, "SELECT version FROM schema_version") == [(1,)]
    assert _inspect(db, "SELECT name FROM sqlite_master WHERE name='conversation_events'") == []
    assert _inspect(db, "SELECT count(*) FROM turns") == [(1,)]
    (blocker / "keep").unlink()
    blocker.rmdir()
    state, _ = await open_store(db)  # once the cause is fixed, the backup and migration both happen
    await state.close()
    assert backup.is_file() and _inspect(db, "SELECT version FROM schema_version") == [(2,)]


async def test_run_serialized_never_leaves_the_shared_connection_in_a_transaction(db):
    state, store = await open_store(db)
    try:
        insert = ("INSERT INTO devices(id, data) VALUES ('leak', '{}')")

        def leaves_open(conn):
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(insert)
            return "looks fine"

        with pytest.raises(RuntimeError, match="left a transaction open; it was rolled back"):
            await state.run_serialized(leaves_open)

        def fails_inside(conn):
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(insert)
            raise ValueError("callback bug")

        with pytest.raises(ValueError, match="callback bug"):
            await state.run_serialized(fails_inside)
        assert await raw(state, "SELECT id FROM devices WHERE id='leak'") == []
        assert await state.run_serialized(lambda conn: conn.in_transaction) is False
        assert (await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"))).status is AppendStatus.APPENDED
    finally:
        await state.close()


class _RollbackFails:
    """Connection proxy whose ROLLBACK fails, as on a disk I/O error."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction

    def execute(self, sql, *args):
        if sql == "ROLLBACK":
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.execute(sql, *args)


def test_failing_rollback_never_masks_the_migration_failure(monkeypatch):
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES (1)")
        monkeypatch.setitem(sqlite_state._MIGRATIONS, 2, ("CREATE TABLE broken (",))
        with pytest.raises(sqlite3.OperationalError, match="incomplete input|syntax error") as caught:
            SQLiteStateRepository._migrate(_RollbackFails(conn), 1)
        assert any("ROLLBACK also failed: OperationalError: disk I/O error" in note for note in caught.value.__notes__)
    finally:
        conn.close()


def test_rollback_after_failure_is_silent_without_a_transaction():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        failure = ValueError("original")
        rollback_after_failure(conn, failure)
        assert getattr(failure, "__notes__", []) == []
    finally:
        conn.close()
