"""Persistance des Contexts de Session : migration v5, magasin, adoption, dossiers.

Handoff session-context-recording, Slice 02. Contrat : `docs/session-context.md`
› *Persistence* et *Workspace folder*. Tout tourne sur des bases et dossiers
temporaires (`tmp_path`) ; jamais sur une base réelle.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import sys

import pytest

from jarvis.adapters import context_workspace, sqlite_state
from jarvis.adapters.context_workspace import ContextWorkspaceError, ensure_context_workspace
from jarvis.adapters.sqlite_session_context import SQLiteContextRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository, pre_migration_backup_path
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.session_contexts import ensure_context
from jarvis.domain.session_context import (
    ContextOrigin, SessionContext, SessionContextError, SessionContextErrorCode, activate_context, create_context,
    dormant_contexts_of_closed_session,
)
from jarvis.domain.workspace_board import SessionEndReason, close_session, default_board, open_session
from jarvis.ports.session_context import ContextStoreError, ContextStoreUnavailable
from jarvis.ports.workspace_board import BoardStoreError

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"
CID = "jctx_0123456789abcdef"


def t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


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
    try:
        yield SQLiteBoardRepository(state), SQLiteContextRepository(state)
    finally:
        await state.close()


async def _open_session(boards: SQLiteBoardRepository, *, now=T0, sid=SID):
    board = default_board(now=now)
    await boards.save_board(board)
    session = open_session(board, now=now, jarvis_session_id=sid)
    await boards.save_session(session)
    return session


# ------------------------------------------------------------------ migration v4 -> v5 et adoption


async def _v4_file_with_sessions(db: Path, monkeypatch):
    """Une base réelle au schéma 4 (binaire d'avant la Slice) : une Session close, une ouverte."""

    with monkeypatch.context() as patch:
        patch.setattr(sqlite_state, "_SCHEMA_VERSION", 4)
        state = SQLiteStateRepository(db)
        await state.initialize()
        boards = SQLiteBoardRepository(state)
        old = await _open_session(boards, sid="jsess_old")
        closed = close_session(old, reason=SessionEndReason.NEW_SESSION, now=t(1))
        await boards.save_session(closed)
        current = await _open_session(boards, now=t(2))
        await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(4,)]
    assert not _inspect(db, "SELECT name FROM sqlite_master WHERE name='session_contexts'")
    return closed, current


async def test_v4_file_migrates_to_v5_after_a_backup_without_fabricated_contexts(db, tmp_path, monkeypatch):
    closed, current = await _v4_file_with_sessions(db, monkeypatch)
    state = SQLiteStateRepository(db)
    await state.initialize()
    try:
        boards, contexts = SQLiteBoardRepository(state), SQLiteContextRepository(state)
        assert await boards.get_session(closed.jarvis_session_id) == closed
        assert await boards.current_session() == current
        # La migration ne porte aucune donnée produit : aucun Context inventé.
        assert await contexts.list_contexts(current.jarvis_session_id) == ()
    finally:
        await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(5,)]
    backup = pre_migration_backup_path(db, 4)
    assert _inspect(backup, "SELECT version FROM schema_version") == [(4,)]

    fresh = tmp_path / "fresh" / "jarvis.sqlite3"
    repo = SQLiteStateRepository(fresh)
    await repo.initialize()
    await repo.close()
    schema = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    assert _inspect(db, schema) == _inspect(fresh, schema)


async def test_ensure_context_adopts_the_open_session_once_and_ignores_closed_ones(db, monkeypatch):
    closed, current = await _v4_file_with_sessions(db, monkeypatch)
    state = SQLiteStateRepository(db)
    await state.initialize()
    try:
        contexts = SQLiteContextRepository(state)
        first = await ensure_context(contexts, current, now=t(10))
        assert first.adopted
        assert first.context.origin is ContextOrigin.ADOPTED and first.context.is_active
        assert first.context.created_at == t(10)  # pas d'historique antidaté
        again = await ensure_context(contexts, current, now=t(11))
        assert not again.adopted and again.context == first.context
        assert await ensure_context(contexts, closed, now=t(12)) is None
        assert await contexts.list_contexts(closed.jarvis_session_id) == ()
        assert await contexts.list_contexts(current.jarvis_session_id) == (first.context,)
    finally:
        await state.close()
    # Un redémarrage relit le même Context adopté.
    state = SQLiteStateRepository(db)
    await state.initialize()
    try:
        reread = await ensure_context(SQLiteContextRepository(state), current, now=t(20))
        assert not reread.adopted and reread.context == first.context
    finally:
        await state.close()


async def test_concurrent_ensure_context_adopts_exactly_once(stores):
    boards, contexts = stores
    session = await _open_session(boards)
    results = await asyncio.gather(*(ensure_context(contexts, session, now=t(1)) for _ in range(4)))
    assert sum(r.adopted for r in results) == 1
    assert len({r.context.context_id for r in results}) == 1
    assert len(await contexts.list_contexts(SID)) == 1


async def test_ensure_context_keeps_an_existing_created_context(stores):
    boards, contexts = stores
    session = await _open_session(boards)
    created = create_context(session, (), now=t(1), title="Projet")
    await contexts.commit_contexts(created.changed)
    ensured = await ensure_context(contexts, session, now=t(2))
    assert not ensured.adopted and ensured.context == created.active
    late = SessionContext(context_id="jctx_late", jarvis_session_id=SID, created_at=t(3), activated_at=t(3),
                          last_active_at=t(3), origin=ContextOrigin.ADOPTED)
    assert await contexts.insert_adopted_if_absent(late) is False


async def test_ensure_context_surfaces_a_session_whose_contexts_have_no_active_one(stores, db):
    boards, contexts = stores
    session = await _open_session(boards)
    created = create_context(session, (), now=t(1))
    await contexts.commit_contexts(created.changed)
    closed = close_session(session, reason=SessionEndReason.NEW_SESSION, now=t(2))
    # État incohérent fabriqué à la main : Session ouverte, Context dormant seul.
    dormant = dormant_contexts_of_closed_session(closed, created.contexts, now=t(2))
    await contexts.commit_contexts(dormant)
    with pytest.raises(SessionContextError) as caught:
        await ensure_context(contexts, session, now=t(3))
    assert caught.value.code is SessionContextErrorCode.CONTEXT_CONFLICT


# ------------------------------------------------------------------ magasin


async def test_create_and_activate_round_trip_in_one_transaction(stores):
    boards, contexts = stores
    session = await _open_session(boards)
    first = create_context(session, (), now=t(1), title="Un", runtime_metadata={"k": 1})
    await contexts.commit_contexts(first.changed)
    second = create_context(session, first.contexts, now=t(2), source_context_ids=[first.active.context_id])
    await contexts.commit_contexts(second.changed)
    assert await contexts.active_context(SID) == second.active
    assert await contexts.list_contexts(SID) == second.contexts
    back = activate_context(session, second.contexts, first.active.context_id, now=t(3))
    await contexts.commit_contexts(back.changed)
    assert await contexts.active_context(SID) == back.active
    assert await contexts.get_context(second.active.context_id) == back.dormanted
    assert await contexts.get_context("jctx_missing") is None
    assert await contexts.active_context("jsess_other") is None
    rows = dict(await _raw(contexts, "SELECT context_id, status FROM session_contexts"))
    assert rows == {first.active.context_id: "active", second.active.context_id: "dormant"}


async def _raw(contexts: SQLiteContextRepository, sql: str, params: tuple = ()):
    return await contexts._state.run_serialized(lambda c: [tuple(r) for r in c.execute(sql, params).fetchall()])


async def test_concurrent_activations_never_leave_two_active_rows(stores):
    """Deux bascules calculées sur le même instantané : une seule passe, l'autre est refusée en bloc."""

    boards, contexts = stores
    session = await _open_session(boards)
    a = create_context(session, (), now=t(1))
    b = create_context(session, a.contexts, now=t(2))
    c = create_context(session, b.contexts, now=t(3))
    await contexts.commit_contexts(a.changed)
    await contexts.commit_contexts(b.changed)
    await contexts.commit_contexts(c.changed)
    snapshot = c.contexts  # actif : c ; dormants : a, b
    to_a = activate_context(session, snapshot, a.active.context_id, now=t(4))
    to_b = activate_context(session, snapshot, b.active.context_id, now=t(4))
    outcomes = await asyncio.gather(contexts.commit_contexts(to_a.changed), contexts.commit_contexts(to_b.changed),
                                    return_exceptions=True)
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(failures) == 1
    assert isinstance(failures[0], SessionContextError)
    assert failures[0].code is SessionContextErrorCode.CONTEXT_CONFLICT
    assert len(await _raw(contexts, "SELECT 1 FROM session_contexts WHERE status='active'")) == 1


async def test_concurrent_activations_from_two_connections_never_leave_two_active_rows(db, stores):
    """Même course entre deux connexions (deux processus Core sur le même fichier)."""

    boards, contexts = stores
    session = await _open_session(boards)
    a = create_context(session, (), now=t(1))
    b = create_context(session, a.contexts, now=t(2))
    c = create_context(session, b.contexts, now=t(3))
    for step in (a, b, c):
        await contexts.commit_contexts(step.changed)
    other_state = SQLiteStateRepository(db)
    await other_state.initialize()
    try:
        other = SQLiteContextRepository(other_state)
        to_a = activate_context(session, c.contexts, a.active.context_id, now=t(4))
        to_b = activate_context(session, c.contexts, b.active.context_id, now=t(4))
        outcomes = await asyncio.gather(contexts.commit_contexts(to_a.changed), other.commit_contexts(to_b.changed),
                                        return_exceptions=True)
    finally:
        await other_state.close()
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(failures) == 1 and isinstance(failures[0], SessionContextError), outcomes
    assert len(await _raw(contexts, "SELECT 1 FROM session_contexts WHERE status='active'")) == 1


async def test_a_refused_write_rolls_back_the_whole_transaction(stores):
    boards, contexts = stores
    session = await _open_session(boards)
    a = create_context(session, (), now=t(1))
    await contexts.commit_contexts(a.changed)
    b = create_context(session, a.contexts, now=t(2))
    stranger = create_context(session, (), now=t(2), context_id="jctx_stranger").active
    stranger = SessionContext(**{**_fields(stranger), "jarvis_session_id": "jsess_unknown"})
    with pytest.raises(SessionContextError) as caught:
        await contexts.commit_contexts((*b.changed, stranger))
    assert caught.value.code is SessionContextErrorCode.INVALID_CONTEXT
    assert await contexts.list_contexts(SID) == a.contexts  # ni a endormi, ni b inséré


def _fields(context):
    return {name: getattr(context, name) for name in context.__slots__}


async def test_store_refuses_an_active_context_in_a_closed_session(stores):
    boards, contexts = stores
    session = await _open_session(boards)
    a = create_context(session, (), now=t(1))
    closed = close_session(session, reason=SessionEndReason.NEW_SESSION, now=t(2))
    await boards.save_session(closed)
    with pytest.raises(SessionContextError) as caught:
        await contexts.commit_contexts(a.changed)
    assert caught.value.code is SessionContextErrorCode.SESSION_CLOSED
    assert await contexts.insert_adopted_if_absent(
        SessionContext(**{**_fields(a.active), "origin": ContextOrigin.ADOPTED})) is False
    assert await contexts.list_contexts(SID) == ()


async def test_store_refuses_to_rewrite_a_context_identity(stores):
    boards, contexts = stores
    session = await _open_session(boards)
    a = create_context(session, (), now=t(1))
    await contexts.commit_contexts(a.changed)
    moved = SessionContext(**{**_fields(a.active), "created_at": t(0)})
    with pytest.raises(SessionContextError) as caught:
        await contexts.commit_contexts((moved,))
    assert caught.value.code is SessionContextErrorCode.CONTEXT_CONFLICT
    assert await contexts.get_context(a.active.context_id) == a.active


async def test_file_enforces_one_active_and_one_adopted_context_per_session(stores):
    boards, contexts = stores
    await _open_session(boards)
    insert = ("INSERT INTO session_contexts(context_id,jarvis_session_id,status,origin,created_at,activated_at,"
              "last_active_at,data) VALUES(?,?,?,?,'x','x','x','{}')")

    def write(conn):
        conn.execute(insert, ("jctx_a", SID, "active", "created"))
        conn.execute(insert, ("jctx_b", SID, "active", "created"))

    with pytest.raises(sqlite3.IntegrityError):
        await contexts._state.run_serialized(write)

    def adopt_twice(conn):
        conn.execute(insert, ("jctx_c", SID, "dormant", "adopted"))
        conn.execute(insert, ("jctx_d", SID, "dormant", "adopted"))

    with pytest.raises(sqlite3.IntegrityError):
        await contexts._state.run_serialized(adopt_twice)


async def test_unreadable_rows_are_surfaced_never_skipped(stores):
    boards, contexts = stores
    session = await _open_session(boards)
    a = create_context(session, (), now=t(1))
    await contexts.commit_contexts(a.changed)
    cid = a.active.context_id

    def damage(sql, params):
        def run(conn):
            conn.execute(sql, params)
        return contexts._state.run_serialized(run)

    await damage("UPDATE session_contexts SET status='dormant' WHERE context_id=?", (cid,))
    with pytest.raises(ContextStoreError) as caught:
        await contexts.get_context(cid)
    assert isinstance(caught.value, BoardStoreError) and caught.value.code == "context_store_unreadable"
    await damage("UPDATE session_contexts SET status='active', data='{not json' WHERE context_id=?", (cid,))
    with pytest.raises(ContextStoreError):
        await contexts.list_contexts(SID)


async def test_sqlite_failures_become_context_store_unavailable(stores):
    _, contexts = stores
    await contexts._state.run_serialized(lambda c: c.execute("DROP INDEX idx_session_contexts_session"))
    await contexts._state.run_serialized(lambda c: c.execute("ALTER TABLE session_contexts RENAME TO gone"))
    with pytest.raises(ContextStoreUnavailable) as caught:
        await contexts.list_contexts(SID)
    assert caught.value.code == "context_store_failed" and "no such table" in str(caught.value)


async def test_insert_adopted_refuses_a_non_adopted_context(stores):
    boards, contexts = stores
    session = await _open_session(boards)
    with pytest.raises(SessionContextError):
        await contexts.insert_adopted_if_absent(create_context(session, (), now=t(1)).active)


# ------------------------------------------------------------------ dossier de travail


def test_workspace_is_created_under_the_root_and_is_idempotent(tmp_path):
    made = ensure_context_workspace(tmp_path, SID, CID)
    expected = tmp_path.resolve() / "sessions" / SID / "contexts" / CID
    assert made.path == expected and made.created and expected.is_dir()
    (expected / "notes.md").write_text("agent", encoding="utf-8")
    again = ensure_context_workspace(tmp_path, SID, CID)
    assert again.path == expected and not again.created
    assert (expected / "notes.md").read_text(encoding="utf-8") == "agent"  # jamais vidé


@pytest.mark.parametrize("sid, cid", [
    ("..", CID), (SID, ".."), ("jsess_a/b", CID), (SID, "jctx_a\\b"), ("C:", CID), (SID, "jctx_é"),
    ("jsess_", CID), (SID, ""),
])
def test_workspace_refuses_invalid_ids_before_touching_the_disk(tmp_path, sid, cid):
    with pytest.raises(SessionContextError) as caught:
        ensure_context_workspace(tmp_path, sid, cid)
    assert caught.value.code is SessionContextErrorCode.INVALID_CONTEXT
    assert list(tmp_path.iterdir()) == []


def test_workspace_refuses_a_relative_or_missing_root(tmp_path):
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(Path("relative"), SID, CID)
    assert caught.value.code == context_workspace.UNSAFE
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(tmp_path / "missing", SID, CID)
    assert caught.value.code == context_workspace.FAILED
    assert not (tmp_path / "missing").exists()


def _junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        os.symlink(target, link, target_is_directory=True)
        return
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


@pytest.mark.parametrize("level", ["sessions", "session", "contexts", "context"])
def test_workspace_refuses_a_junction_at_any_level_and_writes_nothing_outside(tmp_path, level):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    chain = [root / "sessions", root / "sessions" / SID, root / "sessions" / SID / "contexts",
             root / "sessions" / SID / "contexts" / CID]
    index = ["sessions", "session", "contexts", "context"].index(level)
    for folder in chain[:index]:
        folder.mkdir()
    _junction(chain[index], outside)
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(root, SID, CID)
    assert caught.value.code == context_workspace.UNSAFE
    assert list(outside.iterdir()) == []
    assert chain[index].exists()  # refusé, jamais supprimé


def test_workspace_refuses_a_symbolic_link(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    try:
        os.symlink(outside, root / "sessions", target_is_directory=True)
    except OSError as exc:  # Windows sans le droit de créer des liens symboliques
        pytest.skip(f"symlink not permitted here: {exc}")
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(root, SID, CID)
    assert caught.value.code == context_workspace.UNSAFE
    assert list(outside.iterdir()) == []


def test_workspace_refuses_a_file_where_a_folder_is_expected(tmp_path):
    parent = tmp_path / "sessions" / SID / "contexts"
    parent.mkdir(parents=True)
    (parent / CID).write_text("not a folder", encoding="utf-8")
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(tmp_path, SID, CID)
    assert caught.value.code == context_workspace.UNSAFE
    assert (parent / CID).read_text(encoding="utf-8") == "not a folder"


def test_interrupted_creation_is_completed_by_the_next_ensure(tmp_path, monkeypatch):
    real_mkdir = os.mkdir

    def crash_on_leaf(path, *args, **kwargs):
        if Path(path).name == CID:
            raise PermissionError(13, "simulated crash", str(path))
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(context_workspace.os, "mkdir", crash_on_leaf)
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(tmp_path, SID, CID)
    assert caught.value.code == context_workspace.FAILED and "simulated crash" in str(caught.value)
    assert (tmp_path / "sessions" / SID / "contexts").is_dir()
    monkeypatch.undo()
    made = ensure_context_workspace(tmp_path, SID, CID)
    assert made.created and made.path.is_dir()


def test_workspace_accepts_an_existing_folder_with_another_case_on_windows(tmp_path):
    if sys.platform != "win32":
        pytest.skip("case-insensitive filesystem behaviour")
    (tmp_path / "Sessions").mkdir()
    made = ensure_context_workspace(tmp_path, SID, CID)
    assert made.path.is_dir()


# ------------------------------------------------------------------ rework QA Slice 02


async def test_ensure_context_returns_none_when_the_session_closes_between_read_and_insert(stores, monkeypatch):
    """M18 : l'insertion n'a rien fait parce que la Session s'est close entre-temps -> `None`, pas un conflit."""

    boards, contexts = stores
    session = await _open_session(boards)
    real_insert = contexts.insert_adopted_if_absent

    async def close_then_insert(context):  # noqa: ANN001, ANN202
        await boards.save_session(close_session(session, reason=SessionEndReason.NEW_SESSION, now=t(1)))
        return await real_insert(context)

    monkeypatch.setattr(contexts, "insert_adopted_if_absent", close_then_insert)
    assert await ensure_context(contexts, session, now=t(2)) is None
    assert await contexts.list_contexts(SID) == ()
    assert await contexts.session_is_open(SID) is False and await contexts.session_is_open("jsess_none") is False


async def test_commit_contexts_writes_dormant_rows_first_whatever_the_given_order(stores):
    """M2 : le nouvel actif donné avant l'ancien qui s'endort passe quand même (index d'un seul actif)."""

    boards, contexts = stores
    session = await _open_session(boards)
    first = create_context(session, (), now=t(1))
    await contexts.commit_contexts(first.changed)
    second = create_context(session, first.contexts, now=t(2))
    assert [c.is_active for c in second.changed] == [False, True]
    await contexts.commit_contexts(tuple(reversed(second.changed)))  # actif d'abord
    assert await contexts.active_context(SID) == second.active
    assert await contexts.get_context(first.active.context_id) == second.dormanted


def test_workspace_inspects_each_folder_it_just_created(tmp_path, monkeypatch):
    """M15 : ce que `mkdir` a « créé » est inspecté ; un fichier glissé à sa place est refusé."""

    real_mkdir = os.mkdir

    def file_instead_of_leaf(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if Path(path).name == CID:
            Path(path).write_text("not a folder", encoding="utf-8")
            return None
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(context_workspace.os, "mkdir", file_instead_of_leaf)
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(tmp_path, SID, CID)
    assert caught.value.code == context_workspace.UNSAFE and "not a directory" in str(caught.value)


def test_workspace_refuses_a_final_folder_that_resolves_outside_the_root(tmp_path, monkeypatch):
    """M12 : la vérification finale « reste sous la racine » refuse une résolution vers ailleurs."""

    real_resolve = Path.resolve
    outside = tmp_path / "outside"
    outside.mkdir()

    def resolve(self, strict=False):  # noqa: ANN001, ANN202
        if self.name == CID:
            return outside
        return real_resolve(self, strict=strict)

    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(root, SID, CID)
    assert caught.value.code == context_workspace.UNSAFE and "resolves outside" in str(caught.value)


def test_workspace_refuses_a_path_above_the_windows_folder_limit_before_touching_the_disk(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows MAX_PATH rule")
    sid, cid = "jsess_" + "a" * 122, "jctx_" + "b" * 123
    with pytest.raises(ContextWorkspaceError) as caught:
        ensure_context_workspace(tmp_path, sid, cid)
    assert caught.value.code == context_workspace.FAILED and "Windows folder limit" in str(caught.value)
    assert not (tmp_path / "sessions").exists()


def test_context_store_unavailable_keeps_its_own_message_and_family():
    error = ContextStoreUnavailable("list_contexts", "OperationalError: locked")
    assert isinstance(error, BoardStoreError) and error.code == "context_store_failed"
    assert str(error) == "context store list_contexts failed: OperationalError: locked"
    assert (error.table, error.key) == ("session_contexts", "list_contexts")
