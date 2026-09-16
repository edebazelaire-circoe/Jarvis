"""Conversation Event store across process death and a real v1 state DB (Slice 02)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

import pytest

from jarvis.domain.conversation_event_store import MAX_EVENT_PAGE_LIMIT, AppendStatus
from jarvis.domain.conversation_events import ConversationEventType as T
from tests.fakes.conversation_events import make_event, open_store

ROOT = Path(__file__).resolve().parents[2]
REAL_STATE_DB = ROOT / "data" / "state" / "jarvis.sqlite3"

# The child acknowledges two events, then starts a 4-event batch whose third
# INSERT hard-kills the process (os._exit inside SQLite, transaction open,
# connection never closed): the closest in-process stand-in for a power cut.
CHILD = textwrap.dedent("""
    import asyncio, json, os, sys
    from pathlib import Path
    from jarvis.domain.conversation_events import ConversationEventType as T
    from tests.fakes.conversation_events import make_event, open_store

    async def main(path):
        state, store = await open_store(Path(path))
        acked = await store.append_many([make_event(T.USER_TRANSCRIPT_ACCEPTED, "ack-1"),
                                         make_event(T.BRAIN_TURN_ACCEPTED, "ack-2")])
        print(json.dumps([[r.event_id, r.sequence, r.status.value] for r in acked]), flush=True)
        batch = [make_event(T.BRAIN_TURN_ACCEPTED, f"lost-{i}", ms=i) for i in range(4)]

        def arm(conn):
            conn.create_function("die", 0, lambda: os._exit(9))
            conn.execute("CREATE TEMP TRIGGER die_mid_batch BEFORE INSERT ON conversation_events "
                         f"WHEN NEW.event_id = '{batch[2].event_id}' BEGIN SELECT die(); END")

        await state.run_serialized(arm)
        await store.append_many(batch)
        print("unreachable", flush=True)

    asyncio.run(main(sys.argv[1]))
""")


async def test_process_killed_mid_batch_keeps_acknowledged_events_and_no_partial_batch(tmp_path):
    db = tmp_path / "state" / "jarvis.sqlite3"
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    child = subprocess.run([sys.executable, "-c", CHILD, str(db)], cwd=ROOT, env=env, capture_output=True,
                           text=True, timeout=60)
    assert child.returncode == 9, child.stderr
    acked = json.loads(child.stdout.splitlines()[0])
    assert "unreachable" not in child.stdout
    assert [status for _, _, status in acked] == ["appended", "appended"]

    state, store = await open_store(db)  # restart: WAL recovery, quick_check inside initialize
    try:
        page = await store.list_conversation_events("conv-a", limit=MAX_EVENT_PAGE_LIMIT)
        assert [(s.event.event_id, s.sequence) for s in page.events] == [(event_id, seq) for event_id, seq, _ in acked]
        assert page.skipped_rows == 0
        # The interrupted batch is retried whole after restart, with fresh sequences.
        retry = await store.append_many([make_event(T.BRAIN_TURN_ACCEPTED, f"lost-{i}", ms=i) for i in range(4)])
        assert [r.status for r in retry] == [AppendStatus.APPENDED] * 4
        assert [r.sequence for r in retry] == [3, 4, 5, 6]
        # A replay of the acknowledged events is a duplicate, not a second copy.
        again = await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "ack-1"))
        assert (again.status, again.sequence) == (AppendStatus.DUPLICATE, acked[0][1])
    finally:
        await state.close()


# Reads the operator's live conversation data, so it never runs by default: the
# automated migration coverage is the v1 schema fixture in the unit tests.
@pytest.mark.skipif(os.environ.get("JARVIS_TEST_REAL_STATE_DB") != "1" or not REAL_STATE_DB.is_file(),
                    reason="reads live user data in data/state/jarvis.sqlite3: opt in with JARVIS_TEST_REAL_STATE_DB=1")
async def test_copy_of_the_real_state_db_upgrades_without_losing_rows(tmp_path):
    copy = tmp_path / "state" / "jarvis.sqlite3"
    copy.parent.mkdir(parents=True)
    # Read-only online backup: the tracked file (and a Core possibly using it) is never written.
    source = sqlite3.connect(f"file:{REAL_STATE_DB.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(copy)
    try:
        source.backup(target)
        tables = [row[0] for row in target.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {name: target.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in tables}
        version = target.execute("SELECT version FROM schema_version").fetchone()[0]
    finally:
        target.close()
        source.close()
    assert version in (1, 2)

    state, store = await open_store(copy)
    try:
        after = {name: (await state.run_serialized(lambda c, n=name: c.execute(f'SELECT count(*) FROM "{n}"').fetchone()))[0]
                 for name in tables}
        assert after == counts
        assert [tuple(r) for r in await state.run_serialized(lambda c: c.execute("SELECT version FROM schema_version").fetchall())] == [(2,)]
        result = await store.append(make_event(T.USER_TRANSCRIPT_ACCEPTED, "migrated", conversation_id="conv-migration-probe"))
        assert result.status is AppendStatus.APPENDED
    finally:
        await state.close()
