"""`BoardService` : stockage, gardes, migration `default`, mode d'interaction par Board (Slice 02).

Contrat : `docs/boards.md` › *Persistence* et `docs/interaction-mode.md`.
Base temporaire uniquement.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.board_service import BoardService
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_ID, BoardError, BoardKind, BoardStatus, InteractionModeOrigin, create_board, open_session,
)

T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


class Bus:
    async def publish(self, envelope) -> None:
        pass


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.lines.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.lines]


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
async def world(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    journal = Journal()
    modes = InteractionModeService(events=Bus(), diagnostics=journal, epoch="e1")
    repo = SQLiteBoardRepository(state)
    service = BoardService(repo, interaction_mode=modes, diagnostics=journal, clock=Clock())
    try:
        yield service, modes, repo, journal
    finally:
        await service.stop()
        await state.close()


# ------------------------------------------------------------------ migration `default`


async def test_ensure_default_creates_the_default_board_once(world):
    service, _, repo, journal = world
    assert await service.ensure_default() is True
    board = await service.get_active()
    assert board.board_id == DEFAULT_BOARD_ID
    assert board.interaction_mode_origin is InteractionModeOrigin.UNSET
    assert await service.ensure_default() is False
    assert await service.get_active() == board
    assert await repo.count_boards() == 1
    assert journal.kinds().count("core.board.default_created") == 1


async def test_ensure_default_does_nothing_when_boards_already_exist(world):
    service, _, repo, journal = world
    await repo.save_board(create_board("Existant", now=T0))
    assert await service.ensure_default() is False
    assert [b.title for b in await service.list(include_archived=True)] == ["Existant"]
    assert "core.board.default_absent" in journal.kinds()
    await service.restore_interaction_mode()  # ne lève pas : dit la cause
    assert "core.board.interaction_mode.restore_failed" in journal.kinds()


# ------------------------------------------------------------------ CRUD et gardes


async def test_create_get_update_list(world):
    service, _, _, _ = world
    await service.start()
    board = await service.create({"title": "  Projet B ", "context_summary": "but", "task_refs": ["t1"]})
    assert (board.title, board.context_summary, board.task_refs) == ("Projet B", "but", ("t1",))
    assert await service.get(board.board_id) == board
    updated = await service.update(board.board_id, {"title": "Projet B2", "project_refs": ["p"]})
    assert (updated.title, updated.task_refs, updated.project_refs) == ("Projet B2", ("t1",), ("p",))
    assert [b.board_id for b in await service.list()] == [DEFAULT_BOARD_ID, board.board_id]
    assert (await service.get_active()).board_id == DEFAULT_BOARD_ID


async def test_board_kind_is_created_updated_and_stored_without_touching_the_mode(world):
    """board-memory-workspace-inspector S01 : `board_kind` passe par le chemin d'édition existant."""

    service, _, repo, _ = world
    await service.start()
    board = await service.create({"title": "Réunion", "board_kind": "meeting"})
    assert board.board_kind is BoardKind.MEETING
    updated = await service.update(board.board_id, {"board_kind": "presentation"})
    assert updated.board_kind is BoardKind.PRESENTATION
    assert (updated.interaction_mode, updated.interaction_mode_origin) == (
        board.interaction_mode, board.interaction_mode_origin)
    assert (await repo.get_board(board.board_id)).board_kind is BoardKind.PRESENTATION
    for bad in ("Meeting", "", None, 1):
        with pytest.raises(BoardError) as exc:
            await service.update(board.board_id, {"board_kind": bad})
        assert exc.value.code == "invalid_board"
    assert (await service.get(board.board_id)).board_kind is BoardKind.PRESENTATION


@pytest.mark.parametrize("payload, code", [
    ({}, "invalid_title"),
    ({"title": ""}, "invalid_title"),
    ({"title": 3}, "invalid_title"),
    ({"title": "x", "interaction_mode": "presentation"}, "invalid_board"),
    ({"title": "x", "task_refs": "t1"}, "invalid_board"),
    ({"title": "x", "context_summary": "y" * 1501}, "context_summary_too_long"),
    ([], "invalid_board"),
])
async def test_create_refuses_bad_payloads_with_stable_codes(world, payload, code):
    service, _, _, _ = world
    await service.start()
    with pytest.raises(BoardError) as exc:
        await service.create(payload)
    assert exc.value.code == code
    assert len(await service.list(include_archived=True)) == 1


async def test_unknown_board_is_board_not_found(world):
    service, _, _, _ = world
    await service.start()
    for action in (lambda: service.get("board_nope"), lambda: service.update("board_nope", {"title": "x"}),
                   lambda: service.archive("board_nope")):
        with pytest.raises(BoardError) as exc:
            await action()
        assert exc.value.code == "board_not_found" and exc.value.status == 404


async def test_active_board_cannot_be_archived_and_archived_board_cannot_be_updated(world):
    service, _, _, _ = world
    await service.start()
    with pytest.raises(BoardError) as exc:
        await service.archive(DEFAULT_BOARD_ID)
    assert exc.value.code == "board_is_active" and exc.value.status == 409
    board = await service.create({"title": "B"})
    archived = await service.archive(board.board_id)
    assert archived.status is BoardStatus.ARCHIVED
    assert await service.archive(board.board_id) == archived  # rejouable
    with pytest.raises(BoardError) as exc:
        await service.update(board.board_id, {"title": "x"})
    assert exc.value.code == "board_archived"
    assert [b.board_id for b in await service.list()] == [DEFAULT_BOARD_ID]


async def test_the_active_board_follows_the_open_session(world):
    """V1 : pas de pointeur séparé, la Session ouverte fait foi (Slice 03 l'écrira)."""

    service, _, repo, _ = world
    await service.start()
    board = await service.create({"title": "B"})
    await repo.save_session(open_session(board, now=T0))
    assert (await service.get_active()).board_id == board.board_id
    await service.archive(DEFAULT_BOARD_ID)  # `default` n'est plus actif : archivable
    with pytest.raises(BoardError) as exc:
        await service.archive(board.board_id)
    assert exc.value.code == "board_is_active"


# ------------------------------------------------------------------ mode d'interaction


async def test_a_user_mode_change_is_written_on_the_active_board(world):
    service, modes, _, journal = world
    await service.start()
    await modes.request("presentation", source="control_center")
    await service.drain()
    board = await service.get_active()
    assert (board.interaction_mode, board.interaction_mode_origin) == (
        InteractionMode.PRESENTATION, InteractionModeOrigin.USER)
    assert "core.board.interaction_mode.persisted" in journal.kinds()
    other = await service.create({"title": "B"})
    assert (await service.get(other.board_id)).interaction_mode is InteractionMode.ASSISTANT


async def test_the_legacy_replay_is_adopted_exactly_once(world):
    service, modes, _, journal = world
    await service.start()
    await modes.request("presentation", source="startup")  # rejeu du Control Center
    await service.drain()
    board = await service.get_active()
    assert (board.interaction_mode, board.interaction_mode_origin) == (
        InteractionMode.PRESENTATION, InteractionModeOrigin.MIGRATED)
    # Second rejeu d'une autre valeur : le Board n'est pas écrasé, Core revient à son mode.
    await modes.request("assistant", source="core_restart")
    await service.drain()
    board = await service.get_active()
    assert (board.interaction_mode, board.interaction_mode_origin) == (
        InteractionMode.PRESENTATION, InteractionModeOrigin.MIGRATED)
    assert modes.mode is InteractionMode.PRESENTATION and modes.state.source == "board_restore"
    assert journal.kinds().count("core.board.interaction_mode.migrated") == 1
    assert "core.board.interaction_mode.legacy_replay_overridden" in journal.kinds()


async def test_a_late_user_click_save_retry_is_a_choice_not_a_replay(world):
    service, modes, _, _ = world
    await service.start()
    await modes.request("presentation", source="startup")
    await service.drain()
    await modes.request("assistant", source="save_retry")
    await service.drain()
    board = await service.get_active()
    assert (board.interaction_mode, board.interaction_mode_origin) == (
        InteractionMode.ASSISTANT, InteractionModeOrigin.USER)
    assert modes.mode is InteractionMode.ASSISTANT


async def test_restore_applies_the_active_board_mode_and_skips_an_unset_board(world):
    service, modes, repo, journal = world
    await service.ensure_default()
    await service.restore_interaction_mode()
    assert modes.revision == 0  # `unset` : rien demandé, le rejeu du CC migrera
    assert "core.board.interaction_mode.restore_skipped" in journal.kinds()
    board = await service.get_active()
    from jarvis.domain.workspace_board import set_interaction_mode
    await repo.save_board(set_interaction_mode(board, InteractionMode.PRESENTATION, now=T0 + timedelta(hours=1)))
    await service.restore_interaction_mode()
    assert (modes.mode, modes.state.source, modes.revision) == (InteractionMode.PRESENTATION, "board_restore", 1)


async def test_a_persist_failure_is_traced_with_its_cause(world):
    service, modes, repo, journal = world
    await service.start()

    async def broken(board):
        raise RuntimeError("disk I/O error")

    repo.save_board = broken  # type: ignore[method-assign]
    await modes.request("presentation", source="control_center")
    await service.drain()
    failures = [(level, data) for kind, level, data in journal.lines
                if kind == "core.board.interaction_mode.persist_failed"]
    assert failures and failures[0][0] == "error" and failures[0][1]["mode"] == "presentation"
    assert modes.mode is InteractionMode.PRESENTATION  # le mode effectif n'est pas perdu


# ------------------------------------------------------------------ Core de bout en bout


async def test_the_board_mode_survives_a_core_restart_and_legacy_is_migrated_once(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        assert (await core.boards.get_active()).board_id == DEFAULT_BOARD_ID
        assert core.interaction_mode.revision == 0
        await core.interaction_mode.request("presentation", source="startup")  # rejeu CC = migration
        await core.boards.drain()
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        board = await core.boards.get_active()
        assert board.interaction_mode_origin is InteractionModeOrigin.MIGRATED
        # Restauré au démarrage : révision 1, donc le CC ne rejoue plus (il ne le fait qu'à 0).
        state = core.interaction_mode.state
        assert (state.mode, state.source, state.revision) == (InteractionMode.PRESENTATION, "board_restore", 1)
        assert len(await core.boards.list(include_archived=True)) == 1
        await core.interaction_mode.request("assistant", source="control_center")
        await core.boards.drain()
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        board = await core.boards.get_active()
        assert (board.interaction_mode, board.interaction_mode_origin) == (
            InteractionMode.ASSISTANT, InteractionModeOrigin.USER)
        assert core.interaction_mode.mode is InteractionMode.ASSISTANT
    finally:
        await core.stop()


# ------------------------------------------------------------------ Slice 02 rework (QA)


async def test_a_sqlite_operational_error_in_the_mode_listener_is_traced(world, monkeypatch):
    service, modes, repo, journal = world
    await service.start()

    async def locked(fn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(repo._state, "run_serialized", locked)
    await modes.request("presentation", source="control_center")
    await service.drain()
    failures = [(level, data) for kind, level, data in journal.lines
                if kind == "core.board.interaction_mode.persist_failed"]
    assert failures, "a SQLite failure in the background task must leave a trace"
    level, data = failures[0]
    assert (level, data["code"], data["exception_type"]) == ("error", "board_store_failed", "BoardStoreUnavailable")


async def test_an_unexpected_failure_in_the_mode_listener_is_traced(world):
    service, modes, repo, journal = world
    await service.start()

    async def bug(board):
        raise KeyError("unexpected")

    repo.save_board = bug  # type: ignore[method-assign]
    await modes.request("presentation", source="control_center")
    await service.drain()
    assert any(kind == "core.board.interaction_mode.persist_failed" and data["exception_type"] == "KeyError"
               for kind, _, data in journal.lines)


async def test_stop_drains_pending_mode_writes_before_returning(world):
    service, modes, repo, _ = world
    await service.start()
    release = asyncio.Event()
    save = repo.save_board

    async def slow(board):
        await release.wait()
        await save(board)

    repo.save_board = slow  # type: ignore[method-assign]
    await modes.request("presentation", source="control_center")
    stopping = asyncio.create_task(service.stop())
    await asyncio.sleep(0.05)
    assert not stopping.done(), "stop() must wait for the in-flight write"
    release.set()
    await asyncio.wait_for(stopping, 5)
    board = await repo.get_board(DEFAULT_BOARD_ID)
    assert board.interaction_mode is InteractionMode.PRESENTATION


async def test_stop_unsubscribes_the_mode_listener(world):
    service, modes, repo, journal = world
    await service.start()
    await service.stop()
    await modes.request("presentation", source="control_center")
    await service.drain()
    assert not service._pending
    board = await repo.get_board(DEFAULT_BOARD_ID)
    assert board.interaction_mode_origin is InteractionModeOrigin.UNSET
    assert "core.board.interaction_mode.persisted" not in journal.kinds()


async def test_the_listener_uses_the_source_of_its_own_change(world):
    service, modes, _, journal = world
    await service.start()
    # Two changes back to back: each task must carry its own source, not the
    # service's current one read later.
    await modes.request("presentation", source="startup")
    await modes.request("assistant", source="control_center")
    await service.drain()
    sources = [data["source"] for kind, _, data in journal.lines
               if kind in {"core.board.interaction_mode.migrated", "core.board.interaction_mode.persisted"}]
    assert sources == ["startup", "control_center"]
