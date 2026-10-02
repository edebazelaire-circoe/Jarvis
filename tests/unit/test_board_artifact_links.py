"""Liens Board-artifact (v8) : migration v7 -> v8, magasin, lien automatique au Board actif.

Handoff board-memory-workspace-inspector, Slice 02 (R2). Contrat :
`docs/artifacts.md` › *Board links*. Bases temporaires (`tmp_path`) seulement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sqlite3

import pytest

from jarvis.adapters import sqlite_artifacts, sqlite_state
from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_board_artifact_links import SQLiteBoardArtifactLinks
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_state import SQLiteStateRepository, pre_migration_backup_path
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.artifact_service import ArtifactService
from jarvis.domain.artifacts import ArtifactError, ArtifactErrorCode, ArtifactKind, finalize_artifact, new_artifact
from jarvis.domain.board_artifact_links import BoardArtifactLink, BoardArtifactLinkOrigin
from jarvis.domain.session_activity import ActivityDraft, ActivityKind, ActivityQuery
from jarvis.domain.workspace_board import (
    BoardError, BoardErrorCode, SessionEndReason, close_session, create_board, default_board, open_session,
    visit_board,
)

T0 = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"
OTHER_SID = "jsess_fedcba9876543210"


def t(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _inspect(path: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def art(kind=ArtifactKind.SCREENSHOT, *, now=T0, **kw):  # noqa: ANN001, ANN202
    return new_artifact(kind=kind, source="test", now=now, **kw)


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "state" / "jarvis.sqlite3"


@pytest.fixture
async def stores(db):
    state = SQLiteStateRepository(db)
    await state.initialize()
    try:
        yield (SQLiteBoardRepository(state), SQLiteArtifactRepository(state), SQLiteBoardArtifactLinks(state),
               SQLiteActivityLedger(state))
    finally:
        await state.close()


# ------------------------------------------------------------------ migration v7 -> v8


async def test_a_v7_copy_with_rows_migrates_to_v8_after_a_backup_and_keeps_every_row(tmp_path, monkeypatch):
    source = tmp_path / "v7" / "jarvis.sqlite3"
    board = create_board("Réunion", now=T0)
    artifact = art(jarvis_session_id=SID)
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_state, "_SCHEMA_VERSION", 7)
        # v7 n'a pas la table des liens : on écrit les lignes comme un binaire v7.
        patch.setattr(sqlite_artifacts, "link_to_active_board", lambda conn, artifact: None)
        state = SQLiteStateRepository(source)
        await state.initialize()
        boards = SQLiteBoardRepository(state)
        await boards.save_board(default_board(now=T0))
        await boards.save_board(board)
        await boards.save_session(open_session(board, now=T0, jarvis_session_id=SID))
        await SQLiteArtifactRepository(state).create_artifact(artifact)
        await state.close()
    assert _inspect(source, "SELECT version FROM schema_version") == [(7,)]
    db = tmp_path / "copy" / "jarvis.sqlite3"  # jamais la base d'origine : une copie
    db.parent.mkdir()
    shutil.copy2(source, db)
    before = {table: _inspect(db, f"SELECT * FROM {table} ORDER BY 1")
              for table in ("work_boards", "jarvis_sessions", "artifacts", "session_activity")}

    state = SQLiteStateRepository(db)
    await state.initialize()
    try:
        assert await SQLiteBoardRepository(state).get_board(board.board_id) == board
        assert await SQLiteArtifactRepository(state).get_artifact(artifact.artifact_id) == artifact
        links = SQLiteBoardArtifactLinks(state)
        assert await links.boards_of_artifact(artifact.artifact_id, limit=10) == ()  # aucun rattrapage
    finally:
        await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(8,)]
    for table, rows in before.items():
        assert _inspect(db, f"SELECT * FROM {table} ORDER BY 1") == rows, table
    backup = pre_migration_backup_path(db, 7)
    assert _inspect(backup, "SELECT version FROM schema_version") == [(7,)]
    assert _inspect(backup, "SELECT COUNT(*) FROM artifacts") == [(1,)]
    assert _inspect(source, "SELECT version FROM schema_version") == [(7,)]  # l'original n'a pas bougé
    fresh = tmp_path / "fresh" / "jarvis.sqlite3"
    repo = SQLiteStateRepository(fresh)
    await repo.initialize()
    await repo.close()
    schema = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    assert _inspect(db, schema) == _inspect(fresh, schema)


# ------------------------------------------------------------------ lien automatique


async def test_a_new_artifact_is_linked_to_the_active_board_of_the_open_session(stores):
    boards, artifacts, links, ledger = stores
    first, second = default_board(now=T0), create_board("Présentation", now=T0)
    await boards.save_board(first)
    await boards.save_board(second)
    session = open_session(first, now=T0, jarvis_session_id=SID)
    await boards.save_session(session)
    before = art(jarvis_session_id=SID)
    events = await artifacts.create_artifact(before, activity=(
        ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0, jarvis_session_id=SID,
                      artifact_ids=(before.artifact_id,)),))
    await boards.save_session(visit_board(session, second))
    after = art(now=t(1))  # sans Session nommée : le Board actif de la Session ouverte

    await artifacts.create_artifact(after)

    assert await links.boards_of_artifact(before.artifact_id, limit=10) == (
        BoardArtifactLink(first.board_id, before.artifact_id, BoardArtifactLinkOrigin.ACTIVE_BOARD, T0),)
    assert await links.links_of_board(second.board_id, limit=10) == (
        BoardArtifactLink(second.board_id, after.artifact_id, BoardArtifactLinkOrigin.ACTIVE_BOARD, t(1)),)
    # Le lien automatique n'ajoute aucun événement : `artifact.created` reste le fait.
    assert [e.kind for e in await ledger.list(ActivityQuery())] == [ActivityKind.ARTIFACT_CREATED]
    assert len(events) == 1


async def test_no_link_without_an_open_session_or_for_an_artifact_of_another_session(stores):
    boards, artifacts, links, _ledger = stores
    board = default_board(now=T0)
    await boards.save_board(board)
    orphan = art()
    await artifacts.create_artifact(orphan)  # aucune Session : aucun lien
    closed = close_session(open_session(board, now=T0, jarvis_session_id=OTHER_SID),
                           reason=SessionEndReason.NEW_SESSION, now=t(1))
    await boards.save_session(open_session(board, now=T0, jarvis_session_id=OTHER_SID))
    await boards.save_session(closed)
    await boards.save_session(open_session(board, now=t(2), jarvis_session_id=SID))
    late = art(now=t(3), jarvis_session_id=OTHER_SID)  # d'une Session close : Board inconnu
    await artifacts.create_artifact(late)
    assert await links.boards_of_artifact(orphan.artifact_id, limit=10) == ()
    assert await links.boards_of_artifact(late.artifact_id, limit=10) == ()
    assert await links.count_links(board.board_id) == 0


async def test_the_auto_link_shares_the_artifact_transaction(stores, monkeypatch):
    boards, artifacts, links, _ledger = stores
    board = default_board(now=T0)
    await boards.save_board(board)
    await boards.save_session(open_session(board, now=T0, jarvis_session_id=SID))
    real = sqlite_artifacts.link_to_active_board

    def failing(conn, artifact):  # noqa: ANN001, ANN202
        real(conn, artifact)
        raise sqlite3.OperationalError("disk I/O error after the link")

    monkeypatch.setattr(sqlite_artifacts, "link_to_active_board", failing)
    artifact = art(jarvis_session_id=SID)
    with pytest.raises(Exception, match="disk I/O error"):
        await artifacts.create_artifact(artifact)
    assert await artifacts.get_artifact(artifact.artifact_id) is None
    assert await links.count_links(board.board_id) == 0


async def test_artifact_service_create_links_through_the_store(stores, tmp_path):
    boards, artifacts, links, ledger = stores
    board = create_board("Atelier", now=T0)
    await boards.save_board(board)
    await boards.save_session(open_session(board, now=T0, jarvis_session_id=SID))
    data_root = tmp_path / "data"
    data_root.mkdir()
    service = ArtifactService(artifacts, ledger, FileArtifactPayloads(data_root), clock=lambda: t(5))
    created = await service.create(kind=ArtifactKind.SCREENSHOT, source="test", jarvis_session_id=SID)
    [link] = await links.links_of_board(board.board_id, limit=10)
    assert (link.artifact_id, link.origin, link.linked_at) == (
        created.artifact_id, BoardArtifactLinkOrigin.ACTIVE_BOARD, t(5))


async def test_deleting_an_artifact_drops_its_links(stores):
    boards, artifacts, links, _ledger = stores
    board = default_board(now=T0)
    await boards.save_board(board)
    await boards.save_session(open_session(board, now=T0, jarvis_session_id=SID))
    artifact = finalize_artifact(art(jarvis_session_id=SID), now=T0, text="note")
    await artifacts.create_artifact(artifact)
    assert await links.count_links(board.board_id) == 1
    await artifacts.delete_artifact(artifact.artifact_id, cascade=False, now=t(1), origin="test")
    assert await links.count_links(board.board_id) == 0


# ------------------------------------------------------------------ liens explicites


async def test_explicit_link_unlink_and_listing(stores):
    boards, artifacts, links, ledger = stores
    first, second = default_board(now=T0), create_board("Archives", now=T0)
    await boards.save_board(first)
    await boards.save_board(second)
    a1, a2, a3 = art(now=t(1)), art(now=t(2)), art(now=t(3))
    for a in (a1, a2, a3):
        await artifacts.create_artifact(a)  # aucune Session : aucun lien automatique
    event = ActivityDraft(kind=ActivityKind.BOARD_ARTIFACT_LINKED, occurred_at=t(4),
                          artifact_ids=(a1.artifact_id,), data={"board_id": second.board_id})
    link, created, events = await links.link(second.board_id, a1.artifact_id, now=t(4), activity=(event,))
    assert created and link.origin is BoardArtifactLinkOrigin.EXPLICIT and [e.event_id for e in events] == [
        event.event_id]
    again, created_again, no_events = await links.link(second.board_id, a1.artifact_id, now=t(9), activity=(
        ActivityDraft(kind=ActivityKind.BOARD_ARTIFACT_LINKED, occurred_at=t(9)),))
    assert (again, created_again, no_events) == (link, False, ())  # idempotent, rien d'écrit
    await links.link(second.board_id, a2.artifact_id, now=t(5))
    await links.link(second.board_id, a3.artifact_id, now=t(6))
    await links.link(first.board_id, a1.artifact_id, now=t(7))

    page = await links.links_of_board(second.board_id, limit=2)
    assert [x.artifact_id for x in page] == [a3.artifact_id, a2.artifact_id]
    rest = await links.links_of_board(second.board_id, limit=2, before=page[-1])
    assert [x.artifact_id for x in rest] == [a1.artifact_id]
    assert [x.board_id for x in await links.boards_of_artifact(a1.artifact_id, limit=10)] == [
        second.board_id, first.board_id]
    assert await links.count_links(second.board_id) == 3

    removed, removed_events = await links.unlink(second.board_id, a1.artifact_id, activity=(
        ActivityDraft(kind=ActivityKind.BOARD_ARTIFACT_UNLINKED, occurred_at=t(8)),))
    assert removed and len(removed_events) == 1
    assert await links.unlink(second.board_id, a1.artifact_id) == (False, ())
    assert await links.count_links(second.board_id) == 2
    kinds = [e.kind for e in await ledger.list(ActivityQuery())]
    assert kinds == [ActivityKind.BOARD_ARTIFACT_LINKED, ActivityKind.BOARD_ARTIFACT_UNLINKED]


async def test_link_refuses_unknown_board_or_artifact_and_bad_values(stores):
    boards, artifacts, links, _ledger = stores
    board = default_board(now=T0)
    await boards.save_board(board)
    artifact = art()
    await artifacts.create_artifact(artifact)
    with pytest.raises(BoardError) as missing_board:
        await links.link("board_missing", artifact.artifact_id, now=T0)
    assert missing_board.value.code is BoardErrorCode.BOARD_NOT_FOUND
    with pytest.raises(ArtifactError) as missing_artifact:
        await links.link(board.board_id, "jart_00000000000000000000000000000000", now=T0)
    assert missing_artifact.value.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND
    with pytest.raises(BoardError):
        await links.links_of_board(board.board_id, limit=0)
    with pytest.raises(BoardError):
        await links.link(board.board_id, artifact.artifact_id, now=datetime(2026, 10, 2))  # naïve
    with pytest.raises(ValueError):
        await links.link(board.board_id, artifact.artifact_id, now=T0, origin="guessed")
    assert await links.count_links(board.board_id) == 0


async def test_links_survive_a_restart(db):
    state = SQLiteStateRepository(db)
    await state.initialize()
    board = default_board(now=T0)
    await SQLiteBoardRepository(state).save_board(board)
    artifact = art()
    await SQLiteArtifactRepository(state).create_artifact(artifact)
    await SQLiteBoardArtifactLinks(state).link(board.board_id, artifact.artifact_id, now=T0)
    await state.close()
    state = SQLiteStateRepository(db)
    await state.initialize()
    try:
        assert await SQLiteBoardArtifactLinks(state).links_of_board(board.board_id, limit=5) == (
            BoardArtifactLink(board.board_id, artifact.artifact_id, BoardArtifactLinkOrigin.EXPLICIT, T0),)
    finally:
        await state.close()
