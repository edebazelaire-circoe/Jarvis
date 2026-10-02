"""Magasin SQLite des Boards : migration v3 et `BoardRepository` (handoff board-session, Slice 02).

Contrat : `docs/boards.md` › *Persistence*. Tout tourne sur une base
temporaire ; jamais sur `data/state`.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters import sqlite_state
from jarvis.adapters.sqlite_state import SQLiteStateRepository, pre_migration_backup_path
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.domain.v2 import Device
from jarvis.domain.workspace_board import (
    BindingStatus, BoardError, BrainLifecycle, SessionEndReason, SessionStatus, archive_board, close_session_with_bindings,
    create_board, default_board, new_binding, open_session, promote_binding, set_lifecycle, update_board,
    visit_board,
)
from jarvis.ports.workspace_board import BoardStoreError, BoardStoreUnavailable

T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
BOARD_TABLES = {"work_boards", "jarvis_sessions", "board_conversation_bindings"}


def t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "state" / "jarvis.sqlite3"


def _inspect(path: Path, sql: str):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _tables(path: Path) -> set[str]:
    return {row[0] for row in _inspect(path, "SELECT name FROM sqlite_master WHERE type='table'")}


async def _v2_file(db: Path, monkeypatch) -> None:
    """Une base réelle au schéma 2 (binaire d'avant la Slice), avec une ligne de données."""

    with monkeypatch.context() as patch:
        patch.setattr(sqlite_state, "_SCHEMA_VERSION", 2)
        state = SQLiteStateRepository(db)
        await state.initialize()
        await state.save_device(Device(device_id="dev-v2"))
        await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(2,)]
    assert not BOARD_TABLES & _tables(db)


@pytest.fixture
async def repo(db):
    state = SQLiteStateRepository(db)
    await state.initialize()
    try:
        yield SQLiteBoardRepository(state), state
    finally:
        await state.close()


# ------------------------------------------------------------------ migration


async def test_v2_database_is_backed_up_then_migrated_to_current_without_losing_rows(db, monkeypatch):
    await _v2_file(db, monkeypatch)
    state = SQLiteStateRepository(db)
    await state.initialize()
    await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(sqlite_state._SCHEMA_VERSION,)]
    assert BOARD_TABLES <= _tables(db)
    assert _inspect(db, "SELECT id FROM devices") == [("dev-v2",)]
    backup = pre_migration_backup_path(db, 2)
    assert backup.name == "jarvis.sqlite3.v2.bak" and backup.is_file()
    assert _inspect(backup, "SELECT version FROM schema_version") == [(2,)]
    assert not BOARD_TABLES & _tables(backup)
    assert _inspect(backup, "SELECT id FROM devices") == [("dev-v2",)]
    assert _inspect(backup, "PRAGMA quick_check") == [("ok",)]
    # La migration ne porte aucune donnée produit : le Board `default` est l'affaire du service.
    assert _inspect(db, "SELECT count(*) FROM work_boards") == [(0,)]


async def test_running_the_migration_twice_is_idempotent(db, monkeypatch):
    await _v2_file(db, monkeypatch)
    for _ in range(2):
        state = SQLiteStateRepository(db)
        await state.initialize()
        await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(sqlite_state._SCHEMA_VERSION,)]
    assert sorted(p.name for p in db.parent.glob("*.bak")) == ["jarvis.sqlite3.v2.bak"]
    # `_migrate` rejoué directement sur une base déjà v3 : la version relue sous verrou l'arrête.
    conn = sqlite3.connect(db, isolation_level=None)
    try:
        SQLiteStateRepository._migrate(conn, 2)
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(sqlite_state._SCHEMA_VERSION,)]
    finally:
        conn.close()


async def test_a_crash_mid_migration_rolls_v3_back_and_the_next_start_retries(db, monkeypatch):
    await _v2_file(db, monkeypatch)
    # Panne simulée au milieu de l'étape 3 : après les deux premières tables.
    steps = sqlite_state._MIGRATIONS[3]
    broken = (*steps[:4], "CREATE TABLE broken (", *steps[4:])
    with monkeypatch.context() as patch:
        patch.setitem(sqlite_state._MIGRATIONS, 3, broken)
        with pytest.raises(RuntimeError, match="operational state database unavailable"):
            await SQLiteStateRepository(db).initialize()
    assert _inspect(db, "SELECT version FROM schema_version") == [(2,)]
    assert not BOARD_TABLES & _tables(db)  # rien de l'étape n'a survécu
    assert pre_migration_backup_path(db, 2).is_file()  # la copie précède toute instruction
    state = SQLiteStateRepository(db)
    await state.initialize()
    await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(sqlite_state._SCHEMA_VERSION,)]
    assert BOARD_TABLES <= _tables(db)


async def test_a_fresh_database_is_created_at_the_current_version(db):
    state = SQLiteStateRepository(db)
    await state.initialize()
    await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(sqlite_state._SCHEMA_VERSION,)]
    assert BOARD_TABLES <= _tables(db)
    assert list(db.parent.glob("*.bak*")) == []


# ------------------------------------------------------------------ Boards


async def test_boards_round_trip_list_order_and_archived_filter(repo):
    boards, _ = repo
    default = default_board(now=T0)
    other = update_board(create_board("Projet B", now=t(1)), now=t(2), context_summary="résumé\nligne", task_refs=["t1"])
    assert await boards.insert_board_if_empty(default) is True
    assert await boards.insert_board_if_empty(create_board("jamais", now=t(1))) is False
    await boards.save_board(other)
    assert await boards.get_board(other.board_id) == other
    assert await boards.get_board("board_absent") is None
    assert [b.board_id for b in await boards.list_boards()] == ["default", other.board_id]
    archived = archive_board(other, active_board_id="default", now=t(3))
    await boards.save_board(archived)
    assert [b.board_id for b in await boards.list_boards()] == ["default"]
    assert [b.board_id for b in await boards.list_boards(include_archived=True)] == ["default", other.board_id]
    assert await boards.count_boards() == 2


async def test_a_damaged_board_row_is_surfaced_never_skipped(repo):
    boards, state = repo
    await boards.save_board(default_board(now=T0))
    await state.run_serialized(lambda c: c.execute("UPDATE work_boards SET data='{\"nope\":1}'"))
    with pytest.raises(BoardStoreError, match="work_boards row 'default' is unreadable"):
        await boards.get_board("default")
    await state.run_serialized(lambda c: c.execute(
        "UPDATE work_boards SET data=?, status='archived'", (json.dumps(default_board(now=T0).to_payload()),)))
    with pytest.raises(BoardStoreError, match="key columns disagree"):
        await boards.list_boards(include_archived=True)


# ------------------------------------------------------------------ Sessions : garde SQL


async def test_a_closed_session_row_is_never_rewritten_by_the_sql_guard(repo):
    boards, state = repo
    default = default_board(now=T0)
    await boards.save_board(default)
    session = open_session(default, now=T0)
    await boards.save_session(session)
    assert await boards.current_session() == session
    closed, _ = close_session_with_bindings(session, (), reason=SessionEndReason.NEW_SESSION, now=t(1))
    await boards.save_session(closed)
    assert await boards.current_session() is None
    stored = await state.run_serialized(lambda c: c.execute("SELECT data FROM jarvis_sessions").fetchall())
    # Réécriture d'une Session close : refusée par le SQL lui-même, même avec une
    # valeur « ouverte » forgée (le domaine l'aurait déjà refusée).
    for forged in (session, closed):
        with pytest.raises(BoardError) as exc:
            await boards.save_session(forged)
        assert exc.value.code == "session_closed"
    assert await state.run_serialized(lambda c: c.execute("SELECT data FROM jarvis_sessions").fetchall()) == stored
    assert (await boards.get_session(session.jarvis_session_id)).status is SessionStatus.CLOSED


async def test_at_most_one_open_session_in_the_file(repo):
    boards, _ = repo
    default = default_board(now=T0)
    await boards.save_board(default)
    await boards.save_session(open_session(default, now=T0))
    with pytest.raises(BoardError) as exc:
        await boards.save_session(open_session(default, now=t(1)))
    assert exc.value.code == "invalid_session"


async def test_list_sessions_is_newest_first_and_bounded(repo):
    boards, _ = repo
    default = default_board(now=T0)
    await boards.save_board(default)
    ids = []
    for minute in range(3):
        session = open_session(default, now=t(minute * 10))
        closed, _ = close_session_with_bindings(session, (), reason=SessionEndReason.NEW_SESSION, now=t(minute * 10 + 1))
        if minute == 0:
            # Ligne historique d'avant D02 : close par un redémarrage de Core.
            closed = dataclasses.replace(closed, end_reason=SessionEndReason.CORE_RESTART)
        await boards.save_session(session)
        await boards.save_session(closed)
        ids.append(session.jarvis_session_id)
    assert [s.jarvis_session_id for s in await boards.list_sessions(limit=2)] == [ids[2], ids[1]]
    assert (await boards.get_session(ids[0])).end_reason is SessionEndReason.CORE_RESTART
    with pytest.raises(ValueError):
        await boards.list_sessions(limit=0)


# ------------------------------------------------------------------ liaisons


async def _session_with_two_bindings(boards: SQLiteBoardRepository):
    a, b = default_board(now=T0), create_board("B", now=T0)
    await boards.save_board(a)
    await boards.save_board(b)
    session = visit_board(open_session(a, now=T0), b)
    await boards.save_session(session)
    ba = new_binding(session, a, conversation_id="conv-a", agent_cli="claude", now=T0)
    bb = new_binding(session, b, conversation_id="conv-b", agent_cli="codex", now=T0, existing=[ba])
    return (a, b), session, (ba, bb)


async def test_bindings_queries_by_session_conversation_and_liveness(repo):
    boards, _ = repo
    _, session, (ba, bb) = await _session_with_two_bindings(boards)
    ba, bb = promote_binding(session, (ba, bb), ba, now=t(1))
    await boards.save_binding(ba)
    await boards.save_binding(bb)
    # Ordre stable : création, puis board_id ("board_…" < "default").
    assert await boards.list_bindings(session.jarvis_session_id) == (bb, ba)
    assert await boards.binding_by_conversation("conv-b") == bb
    assert await boards.binding_by_conversation("conv-x") is None
    assert await boards.list_live_bindings() == (ba,)
    # Une Session close garde ses CLI de fond vivants : ils restent « live ».
    closed, (ca, cb) = close_session_with_bindings(
        session, (ba, bb), reason=SessionEndReason.NEW_SESSION, now=t(2),
        foreground_to=BrainLifecycle.BACKGROUND_RUNNING)
    await boards.commit_switch(sessions=[closed], boards=[], bindings=[ca, cb])
    assert await boards.list_live_bindings() == (ca,)
    await boards.save_binding(set_lifecycle(ca, BrainLifecycle.SUSPENDED, now=t(3)))
    assert await boards.list_live_bindings() == ()


async def test_one_foreground_per_session_is_enforced_by_the_file(repo):
    boards, _ = repo
    _, _, (ba, bb) = await _session_with_two_bindings(boards)
    await boards.save_binding(ba.__class__(**{**_fields(ba), "lifecycle": BrainLifecycle.FOREGROUND}))
    with pytest.raises(BoardError) as exc:
        await boards.save_binding(bb.__class__(**{**_fields(bb), "lifecycle": BrainLifecycle.FOREGROUND}))
    assert exc.value.code == "binding_conflict"


def _fields(binding) -> dict:
    return {name: getattr(binding, name) for name in binding.__dataclass_fields__}


async def test_commit_switch_writes_everything_in_one_transaction(repo):
    boards, _ = repo
    (a, b), session, (ba, bb) = await _session_with_two_bindings(boards)
    on_a = visit_board(session, a)
    ba, bb = promote_binding(on_a, (ba, bb), ba, now=t(1))
    await boards.commit_switch(sessions=[on_a], boards=[], bindings=[ba, bb])
    assert (await boards.current_session()).active_board_id == a.board_id
    # Bascule vers B : B promu, passé AVANT la démotion de A dans la liste reçue ;
    # l'adaptateur ordonne pour l'index partiel « un foreground ».
    switched = visit_board(on_a, b)
    promoted = promote_binding(switched, (ba, bb), bb, now=t(2))
    await boards.commit_switch(sessions=[switched], boards=[update_board(b, now=t(2), title="B'")],
                               bindings=[promoted[1], promoted[0]])
    assert (await boards.current_session()).active_board_id == b.board_id
    assert {x.board_id: x.lifecycle for x in await boards.list_bindings(session.jarvis_session_id)} == {
        a.board_id: BrainLifecycle.SUSPENDED, b.board_id: BrainLifecycle.FOREGROUND}
    assert (await boards.get_board(b.board_id)).title == "B'"


async def test_a_failing_commit_switch_writes_nothing(repo):
    boards, _ = repo
    (a, b), session, (ba, bb) = await _session_with_two_bindings(boards)
    closed, closed_bindings = close_session_with_bindings(session, (ba, bb), reason=SessionEndReason.NEW_SESSION,
                                                          now=t(1))
    await boards.commit_switch(sessions=[closed], boards=[], bindings=list(closed_bindings))
    before_board = await boards.get_board(b.board_id)
    # Un lot qui réécrit la Session close échoue sur la garde SQL : le Board
    # modifié dans le même lot, écrit avant, ne doit pas survivre.
    with pytest.raises(BoardError) as exc:
        await boards.commit_switch(sessions=[closed], boards=[update_board(b, now=t(2), title="jamais")], bindings=[])
    assert exc.value.code == "session_closed"
    assert await boards.get_board(b.board_id) == before_board


# ------------------------------------------------------------------ Slice 02 rework (QA)


async def test_a_closed_binding_never_reopens_nor_becomes_foreground_but_its_lifecycle_moves(repo):
    boards, _ = repo
    _, session, (ba, bb) = await _session_with_two_bindings(boards)
    ba, bb = promote_binding(session, (ba, bb), ba, now=t(1))
    closed, (ca, cb) = close_session_with_bindings(
        session, (ba, bb), reason=SessionEndReason.NEW_SESSION, now=t(2),
        foreground_to=BrainLifecycle.BACKGROUND_RUNNING)
    await boards.commit_switch(sessions=[closed], boards=[], bindings=[ca, cb])
    # Lifecycle of a closed binding may still move (its CLI finishes, then suspends).
    suspended = set_lifecycle(ca, BrainLifecycle.SUSPENDED, now=t(3))
    await boards.save_binding(suspended)
    reopened = ca.__class__(**{**_fields(suspended), "status": BindingStatus.OPEN})
    foreground = ca.__class__(**{**_fields(suspended), "status": BindingStatus.OPEN,
                                 "lifecycle": BrainLifecycle.FOREGROUND})
    for forged in (reopened, foreground):
        with pytest.raises(BoardError) as exc:
            await boards.save_binding(forged)
        assert exc.value.code == "session_closed"
        with pytest.raises(BoardError) as exc:
            await boards.commit_switch(sessions=[], boards=[], bindings=[forged])
        assert exc.value.code == "session_closed"
    stored = {b.board_id: b for b in await boards.list_bindings(session.jarvis_session_id)}
    assert stored[ca.board_id] == suspended


async def test_commit_switch_orders_a_new_session_listed_before_the_closing_one(repo):
    boards, _ = repo
    (a, _), session, (ba, bb) = await _session_with_two_bindings(boards)
    ba, bb = promote_binding(session, (ba, bb), ba, now=t(1))
    await boards.commit_switch(sessions=[], boards=[], bindings=[ba, bb])
    closed, closed_bindings = close_session_with_bindings(session, (ba, bb), reason=SessionEndReason.NEW_SESSION,
                                                          now=t(2))
    fresh = open_session(a, now=t(2))
    binding = new_binding(fresh, a, conversation_id="conv-new", agent_cli="claude", now=t(2))
    (fg,) = promote_binding(fresh, (binding,), binding, now=t(2))
    # The opening Session FIRST: the adapter must still close the old one before
    # inserting it (unique partial index "one open session").
    await boards.commit_switch(sessions=[fresh, closed], boards=[], bindings=[fg, *closed_bindings])
    assert (await boards.current_session()) == fresh
    assert (await boards.get_session(session.jarvis_session_id)).status is SessionStatus.CLOSED


async def test_a_sqlite_failure_becomes_a_board_store_error(repo, monkeypatch):
    boards, state = repo

    async def locked(fn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(state, "run_serialized", locked)
    with pytest.raises(BoardStoreUnavailable) as exc:
        await boards.get_board("default")
    assert isinstance(exc.value, BoardStoreError) and exc.value.code == "board_store_failed"
    assert "database is locked" in str(exc.value) and "get_board" in str(exc.value)


# ------------------------------------------------------------------ Slice 03 QA (reprise)


async def test_the_sql_guard_alone_refuses_a_closed_binding_turned_foreground(repo):
    """La clause `excluded.lifecycle='foreground'` seule, sans le domaine devant elle.

    Le domaine refuse de construire une liaison close et foreground ; ce test
    la forge quand même et l'écrit par le SQL de l'adaptateur. Retirer la
    clause (en gardant `excluded.status='open'`) laisserait passer l'écriture.
    """

    from jarvis.adapters.sqlite_workspace_board import _put_binding
    from jarvis.domain.workspace_board import BoardConversationBinding

    boards, state = repo
    _, session, (ba, bb) = await _session_with_two_bindings(boards)
    closed, (ca, cb) = close_session_with_bindings(session, (ba, bb), reason=SessionEndReason.NEW_SESSION, now=t(1))
    await boards.commit_switch(sessions=[closed], boards=[], bindings=[ca, cb])
    forged = object.__new__(BoardConversationBinding)
    for name, value in {**_fields(ca), "lifecycle": BrainLifecycle.FOREGROUND}.items():
        object.__setattr__(forged, name, value)
    assert forged.status is BindingStatus.CLOSED and forged.lifecycle is BrainLifecycle.FOREGROUND

    with pytest.raises(BoardError) as exc:
        await state.run_serialized(lambda conn: _put_binding(conn, forged))

    assert exc.value.code == "session_closed"
    assert {b.board_id: b for b in await boards.list_bindings(session.jarvis_session_id)}[ca.board_id] == ca
