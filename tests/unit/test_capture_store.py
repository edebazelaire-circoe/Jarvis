"""Table `captures` (v7) : migration, conflit par appareil, comparer-échanger, activité dans la transaction.

Handoff session-context-recording, Slice 05. Contrat : `docs/capture.md`.
Bases temporaires (`tmp_path`) seulement ; jamais une base réelle.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters import sqlite_state
from jarvis.adapters.sqlite_captures import SQLiteCaptureRepository
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_state import SQLiteStateRepository, pre_migration_backup_path
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.domain.capture import (
    CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode, CaptureState, StopReason, activate, finish,
    new_capture, request_stop,
)
from jarvis.domain.session_activity import ActivityDraft, ActivityError, ActivityKind, ActivityQuery
from jarvis.domain.workspace_board import default_board, open_session
from jarvis.ports.capture import CaptureStoreError

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"


def _inspect(path: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "state" / "jarvis.sqlite3"


@pytest.fixture
async def stores(db):
    state = SQLiteStateRepository(db)
    await state.initialize()
    boards = SQLiteBoardRepository(state)
    board = default_board(now=T0)
    await boards.save_board(board)
    await boards.save_session(open_session(board, now=T0, jarvis_session_id=SID))
    try:
        yield SQLiteCaptureRepository(state), SQLiteActivityLedger(state)
    finally:
        await state.close()


def cap(channel=CaptureChannel.AUDIO, mode=CaptureMode.CONTINUOUS, *, device="default", minutes=0):  # noqa: ANN001
    return new_capture(channel=channel, mode=mode, source="fake", device=device, now=T0 + timedelta(minutes=minutes),
                       jarvis_session_id=SID)


async def test_v6_file_migrates_to_v7_after_a_backup_and_matches_a_fresh_file(db, tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_state, "_SCHEMA_VERSION", 6)
        state = SQLiteStateRepository(db)
        await state.initialize()
        await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(6,)]
    state = SQLiteStateRepository(db)
    await state.initialize()
    await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(7,)]
    assert _inspect(pre_migration_backup_path(db, 6), "SELECT version FROM schema_version") == [(6,)]
    assert _inspect(db, "SELECT COUNT(*) FROM captures") == [(0,)]
    fresh = tmp_path / "fresh" / "jarvis.sqlite3"
    repo = SQLiteStateRepository(fresh)
    await repo.initialize()
    await repo.close()
    schema = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    assert _inspect(db, schema) == _inspect(fresh, schema)


async def test_one_open_continuous_capture_per_channel_device(stores, db):
    captures, _ = stores
    first = cap()
    await captures.insert_capture(first)
    with pytest.raises(CaptureError) as caught:
        await captures.insert_capture(cap())
    assert (caught.value.code, caught.value.capture_id) == (CaptureErrorCode.ALREADY_ACTIVE, first.capture_id)
    await captures.insert_capture(cap(device="usb"))
    await captures.insert_capture(cap(CaptureChannel.SCREEN))
    await captures.insert_capture(cap(CaptureChannel.SCREEN, CaptureMode.ONE_SHOT))
    await captures.insert_capture(cap(CaptureChannel.SCREEN, CaptureMode.ONE_SHOT))  # jamais en conflit
    # l'index unique partiel tient même sans la vérification de l'adaptateur
    with pytest.raises(sqlite3.IntegrityError):
        conn = sqlite3.connect(db)
        try:
            conn.execute("INSERT INTO captures(capture_id,channel,mode,device,state,created_at,updated_at,data) "
                         "VALUES('jcap_raw','audio','continuous','default','active','t','t','{}')")
        finally:
            conn.close()
    # une fois finie, l'appareil se libère
    stopping = request_stop(first, now=T0, reason=StopReason.USER)
    done = finish(stopping, now=T0, state=CaptureState.FAILED, error_code="permission_denied")
    await captures.update_capture(first, stopping)
    await captures.update_capture(stopping, done)
    await captures.insert_capture(cap())


async def test_update_is_compare_and_swap_with_its_activity_in_the_same_transaction(stores):
    captures, ledger = stores
    record = cap()
    await captures.insert_capture(record)
    active = activate(record, now=T0)
    event = ActivityDraft(kind=ActivityKind.CAPTURE_STARTED, occurred_at=T0, jarvis_session_id=SID,
                          capture_ids=(record.capture_id,))
    (written,) = await captures.update_capture(record, active, activity=(event,))
    assert written.kind is ActivityKind.CAPTURE_STARTED and await captures.get_capture(record.capture_id) == active
    with pytest.raises(CaptureError) as caught:  # ligne lue avant le changement
        await captures.update_capture(record, request_stop(record, now=T0, reason=StopReason.USER))
    assert caught.value.code is CaptureErrorCode.INVALID_TRANSITION
    stopping = request_stop(active, now=T0, reason=StopReason.USER)
    with pytest.raises(ActivityError):  # événement déjà écrit : tout est annulé
        await captures.update_capture(active, stopping, activity=(event,))
    assert (await captures.get_capture(record.capture_id)).state is CaptureState.ACTIVE
    assert len(await ledger.list(ActivityQuery())) == 1
    with pytest.raises(CaptureError) as caught:
        await captures.update_capture(replace(record, capture_id="jcap_missing"),
                                      replace(active, capture_id="jcap_missing"))
    assert caught.value.code is CaptureErrorCode.CAPTURE_NOT_FOUND


async def test_unknown_session_is_refused(stores):
    captures, _ = stores
    stray = new_capture(channel=CaptureChannel.AUDIO, mode=CaptureMode.CONTINUOUS, source="fake", now=T0,
                        jarvis_session_id="jsess_unknown")
    with pytest.raises(CaptureError) as caught:
        await captures.insert_capture(stray)
    assert caught.value.code is CaptureErrorCode.INVALID_CAPTURE


async def test_open_and_recent_listings_and_unreadable_rows(stores, db):
    captures, _ = stores
    old, new = cap(minutes=0), cap(CaptureChannel.SCREEN, minutes=5)
    await captures.insert_capture(old)
    await captures.insert_capture(new)
    stopping = request_stop(old, now=T0, reason=StopReason.USER)
    await captures.update_capture(old, stopping)
    await captures.update_capture(stopping, finish(stopping, now=T0, state=CaptureState.COMPLETE))
    assert [r.capture_id for r in await captures.open_captures(limit=10)] == [new.capture_id]
    assert [r.capture_id for r in await captures.recent_captures(limit=10)] == [new.capture_id, old.capture_id]
    with pytest.raises(CaptureError):
        await captures.open_captures(limit=0)
    conn = sqlite3.connect(db)
    try:
        conn.execute("UPDATE captures SET device='other' WHERE capture_id=?", (new.capture_id,))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(CaptureStoreError):
        await captures.get_capture(new.capture_id)
