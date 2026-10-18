"""`BoardService` : stockage, gardes, migration `default`, type fixé et mode dérivé du type (Slice 02, 01a).

Contrat : `docs/boards.md` › *Persistence* et `docs/interaction-mode.md`.
Base temporaire uniquement.
"""

from __future__ import annotations

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
    DEFAULT_BOARD_ID, BoardError, BoardKind, BoardStatus, create_board, open_session,
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
        await state.close()


# ------------------------------------------------------------------ migration `default`


async def test_ensure_default_creates_the_default_board_once(world):
    service, _, repo, journal = world
    assert await service.ensure_default() is True
    board = await service.get_active()
    assert board.board_id == DEFAULT_BOARD_ID
    assert board.board_kind is BoardKind.ASSISTANT
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


# ------------------------------------------------------------------ type fixé et mode dérivé (Slice 01a, D01-D03)


async def test_the_board_type_is_chosen_at_creation_and_never_changed_by_an_update(world):
    """D02 : un `PATCH` qui porte `board_kind` est refusé `board_kind_immutable`, même à valeur égale."""

    service, _, repo, journal = world
    await service.start()
    board = await service.create({"title": "Réunion", "board_kind": "meeting"})
    assert board.board_kind is BoardKind.MEETING
    for kind in ("presentation", "meeting", "Meeting", None):
        with pytest.raises(BoardError) as exc:
            await service.update(board.board_id, {"title": "Autre", "board_kind": kind})
        assert (exc.value.code, exc.value.status) == ("board_kind_immutable", 409)
        assert "create a new board" in str(exc.value)
    stored = await repo.get_board(board.board_id)
    assert (stored.title, stored.board_kind) == ("Réunion", BoardKind.MEETING)  # rien écrit, pas même le titre
    refusals = [(level, data) for kind, level, data in journal.lines if kind == "core.board.kind_change_refused"]
    assert len(refusals) == 4 and refusals[0][0] == "warning"
    assert refusals[0][1]["board_id"] == board.board_id and refusals[0][1]["code"] == "board_kind_immutable"


async def test_creation_defaults_to_assistant_and_maps_the_deprecated_empty_alias(world):
    service, _, _, journal = world
    await service.start()
    assert (await service.create({"title": "Sans type"})).board_kind is BoardKind.ASSISTANT
    legacy = await service.create({"title": "Ancien client", "board_kind": "empty"})
    assert legacy.board_kind is BoardKind.ASSISTANT and legacy.to_payload()["board_kind"] == "assistant"
    created = [data for kind, _, data in journal.lines if kind == "core.board.created"]
    assert created[-1] == {"board_id": legacy.board_id, "board_kind": "assistant", "deprecated_kind": "empty"}
    assert "deprecated_kind" not in created[-2]
    for bad in ("Meeting", "", None, 1, "simple"):
        with pytest.raises(BoardError) as exc:
            await service.create({"title": "x", "board_kind": bad})
        assert exc.value.code == "invalid_board"


@pytest.mark.parametrize("kind, mode, status", [
    ("assistant", InteractionMode.ASSISTANT, None),
    ("presentation", InteractionMode.PRESENTATION, None),
    # Réunion : valide et ouvrable, comportement assistant dit, jamais un refus.
    ("meeting", InteractionMode.ASSISTANT, "meeting_planned"),
])
async def test_restore_applies_the_mode_designated_by_the_active_board_type(world, kind, mode, status):
    service, modes, repo, journal = world
    await service.ensure_default()
    board = await service.create({"title": "Actif", "board_kind": kind})
    await repo.save_session(open_session(board, now=T0))
    await service.restore_interaction_mode()
    assert modes.mode is mode
    assert modes.state.source == ("board_restore" if mode is not InteractionMode.ASSISTANT else "default")
    applied = [data for k, _, data in journal.lines if k == "core.board.interaction_mode.applied"]
    assert applied[-1]["board_kind"] == kind and applied[-1]["source"] == "board_restore"
    assert applied[-1].get("status") == status
    assert "core.board.interaction_mode.apply_failed" not in journal.kinds()


async def test_a_live_mode_change_is_never_stored_and_is_undone_by_restore(world):
    """Slice 01b : seuls `BoardService` et une lecture du Studio (transitoire) changent le mode vivant ; rien ne l'enregistre."""

    from jarvis.domain.presentation_studio_roles import STUDIO_RUN_MODE_SOURCE

    service, modes, repo, journal = world
    await service.start()
    before = (await repo.get_board(DEFAULT_BOARD_ID)).to_payload()
    for source in ("board_switch", STUDIO_RUN_MODE_SOURCE):
        await modes.request("presentation", source=source)
        await modes.request("assistant", source=source)
    await modes.request("presentation", source=STUDIO_RUN_MODE_SOURCE)
    after = (await repo.get_board(DEFAULT_BOARD_ID)).to_payload()
    assert after == before and "interaction_mode" not in after  # rien enregistré, rien d'autre touché
    assert not any(kind.startswith("core.board.interaction_mode.persist") or kind.endswith(".migrated")
                   for kind in journal.kinds())
    await service.restore_interaction_mode()  # = le prochain démarrage de Core
    assert (modes.mode, modes.state.source) == (InteractionMode.ASSISTANT, "board_restore")


async def test_the_service_does_not_listen_to_mode_changes_any_more(world):
    service, modes, _, _ = world
    await service.start()
    assert modes._listeners == []  # plus aucun abonné : rien n'écrit de mode sur un Board


# ------------------------------------------------------------------ Core de bout en bout


async def test_the_board_type_mode_survives_a_core_restart_and_a_transient_change_does_not(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        assert (await core.boards.get_active()).board_kind is BoardKind.ASSISTANT
        board = await core.boards.create({"title": "Démo", "board_kind": "presentation"})
        await core.boards.switch(board.board_id)
        assert (core.interaction_mode.mode, core.interaction_mode.state.source) == (
            InteractionMode.PRESENTATION, "board_switch")
        await core.interaction_mode.request("assistant", source="presentation_studio_run")  # lecture du Studio : vivant seulement
        assert core.interaction_mode.mode is InteractionMode.ASSISTANT
    finally:
        await core.stop()
    rows = _sql(tmp_path, "SELECT data FROM work_boards")
    assert rows and all("interaction_mode" not in data for (data,) in rows)
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        assert (await core.boards.get_active()).board_id == board.board_id
        state = core.interaction_mode.state
        assert (state.mode, state.source, state.revision) == (InteractionMode.PRESENTATION, "board_restore", 1)
        assert len(await core.boards.list(include_archived=True)) == 2
    finally:
        await core.stop()


def _sql(root, query):
    path = next(root.rglob("jarvis.sqlite3"))
    conn = sqlite3.connect(path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()
