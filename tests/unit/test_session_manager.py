"""`SessionManager` : Sessions Jarvis et liaisons Board (handoff board-session, Slice 03).

Contrat : `docs/boards.md` › *Sessions*. Base temporaire uniquement.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.board_service import BoardService
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.session_manager import PENDING_AGENT_CLI, SessionManager
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.v2_services import ConversationService
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.v2 import Conversation, Job
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_ID, BindingStatus, BoardError, BrainLifecycle, SessionEndReason, SessionStatus, archive_board,
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
    clock = Clock()
    modes = InteractionModeService(events=Bus(), diagnostics=journal, epoch="e1")
    repo = SQLiteBoardRepository(state)
    boards = BoardService(repo, interaction_mode=modes, diagnostics=journal, clock=clock)
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    sessions = SessionManager(repo, boards=boards, conversations=conversations, diagnostics=journal, clock=clock)
    await boards.ensure_default()
    await sessions.start()
    try:
        yield sessions, boards, repo, state, journal
    finally:
        await boards.stop()
        await state.close()


# ------------------------------------------------------------------ démarrage


async def test_start_opens_a_session_on_default_with_a_foreground_binding(world):
    sessions, _, repo, state, journal = world
    view = await sessions.current()
    assert view.session.is_open and view.session.active_board_id == DEFAULT_BOARD_ID
    assert view.binding.lifecycle is BrainLifecycle.FOREGROUND
    assert view.binding.agent_cli == PENDING_AGENT_CLI
    assert await state.get_conversation(view.binding.conversation_id) is not None
    opened = [data for kind, _, data in journal.lines if kind == "core.session.opened"]
    assert opened and opened[0]["origin"] == "core_start" and opened[0]["adopted_conversation"] is False


async def test_opening_resuming_and_renewing_a_session_marks_its_board_opened(tmp_path):
    """Le Board de tous les jours n'est jamais basculé : ouvrir, reprendre (redémarrage de Core)
    ou renouveler la Session horodate quand même son `last_opened_at` (docs/boards.md › Sessions).
    Un autre Board, jamais visité, reste `None`."""

    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        opened_at = (await core.boards.get(DEFAULT_BOARD_ID)).last_opened_at
        assert opened_at is not None
        other = await core.boards.create({"title": "Projet B"})
        again = await core.sessions.start()  # idempotent : ne rouvre rien
        assert (await core.boards.get(DEFAULT_BOARD_ID)).last_opened_at == opened_at
        assert again.session.active_board_id == DEFAULT_BOARD_ID
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        resumed_at = (await core.boards.get(DEFAULT_BOARD_ID)).last_opened_at
        assert resumed_at is not None and resumed_at > opened_at
        # Horloge maîtrisée : le renouvellement doit écrire exactement son propre instant,
        # strictement après la reprise (un `boards=()` laisserait `resumed_at`).
        renewed_clock = resumed_at + timedelta(hours=1)
        core.sessions._clock = lambda: renewed_clock
        await core.sessions.start_new_session()
        renewed_at = (await core.boards.get(DEFAULT_BOARD_ID)).last_opened_at
        assert renewed_at == renewed_clock and renewed_at > resumed_at
        assert (await core.boards.get(other.board_id)).last_opened_at is None
    finally:
        await core.stop()


# ------------------------------------------------------------------ A/B/A


async def test_a_b_a_in_one_session_reuses_the_first_binding(world):
    sessions, boards, repo, _, _ = world
    session = (await sessions.current()).session
    other = await boards.create({"title": "Projet B"})
    a1 = await sessions.binding_for(session.jarvis_session_id, DEFAULT_BOARD_ID)
    b = await sessions.binding_for(session.jarvis_session_id, other.board_id)
    a2 = await sessions.binding_for(session.jarvis_session_id, DEFAULT_BOARD_ID)
    assert a1 == a2 and a1 == (await sessions.current()).binding
    assert b.conversation_id != a1.conversation_id
    assert b.lifecycle is BrainLifecycle.SUSPENDED  # pas de promotion ici (04b)
    b_again = await sessions.binding_for(session.jarvis_session_id, other.board_id)
    assert b_again == b
    assert len(await repo.list_bindings(session.jarvis_session_id)) == 2


async def test_binding_for_an_archived_board_is_refused_without_a_conversation(world):
    sessions, boards, repo, state, _ = world
    session = (await sessions.current()).session
    other = await boards.create({"title": "Archivé"})
    await boards.archive(other.board_id)
    with pytest.raises(BoardError) as raised:
        await sessions.binding_for(session.jarvis_session_id, other.board_id)
    assert raised.value.code.value == "board_archived"
    assert len(await repo.list_bindings(session.jarvis_session_id)) == 1


# ------------------------------------------------------------------ Session close immuable


async def test_a_closed_session_cannot_be_mutated(world):
    sessions, boards, repo, _, _ = world
    old = (await sessions.current()).session
    await sessions.start_new_session()
    closed = await repo.get_session(old.jarvis_session_id)
    other = await boards.create({"title": "Projet B"})
    with pytest.raises(BoardError) as raised:
        await sessions.binding_for(old.jarvis_session_id, other.board_id)
    assert raised.value.code.value == "session_closed"
    with pytest.raises(BoardError) as raised:
        await sessions.start_new_session(expected_session_id=old.jarvis_session_id)
    assert raised.value.code.value == "session_closed"
    # Le dépôt lui-même refuse de réécrire la ligne close.
    with pytest.raises(BoardError) as raised:
        await repo.save_session(closed)
    assert raised.value.code.value == "session_closed"
    assert await repo.get_session(old.jarvis_session_id) == closed
    assert [b.status for b in await repo.list_bindings(old.jarvis_session_id)] == [BindingStatus.CLOSED]


# ------------------------------------------------------------------ nouvelle Session


async def test_new_session_closes_the_old_one_and_keeps_the_active_board(world):
    sessions, boards, repo, _, journal = world
    before = await sessions.current()
    other = await boards.create({"title": "Projet B"})
    await sessions.binding_for(before.session.jarvis_session_id, other.board_id)
    closed, view = await sessions.start_new_session()
    assert closed.jarvis_session_id == before.session.jarvis_session_id
    assert (closed.status, closed.end_reason) == (SessionStatus.CLOSED, SessionEndReason.NEW_SESSION)
    assert view.session.active_board_id == before.session.active_board_id
    assert view.binding.conversation_id != before.binding.conversation_id
    assert view.binding.lifecycle is BrainLifecycle.FOREGROUND
    old = await repo.list_bindings(closed.jarvis_session_id)
    assert {b.status for b in old} == {BindingStatus.CLOSED}
    assert all(b.lifecycle is not BrainLifecycle.FOREGROUND for b in old)
    assert (await sessions.current()) == view
    assert [s.jarvis_session_id for s in await sessions.history()] == [
        view.session.jarvis_session_id, closed.jarvis_session_id]
    assert "core.session.closed" in journal.kinds()


async def test_history_limit_is_bounded(world):
    sessions, _, _, _, _ = world
    for limit in (0, 101, "3"):
        with pytest.raises(BoardError):
            await sessions.history(limit=limit)  # type: ignore[arg-type]
    assert len(await sessions.history(limit=1)) == 1


# ------------------------------------------------------------------ Core de bout en bout


async def test_new_session_leaves_boards_mode_and_jobs_untouched(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        other = await core.boards.create({"title": "Projet B", "task_refs": ["t1"]})
        await core.interaction_mode.request("presentation", source="control_center")
        await core.boards.drain()
        before = await core.sessions.current()
        job = Job(kind="noop", payload={}, requested_by_conversation_id=before.binding.conversation_id)
        await core.state.save_job(job)
        boards_before = await core.boards.list(include_archived=True)
        stored_job = await core.state.get_job(job.id)

        _, view = await core.sessions.start_new_session()
        await core.boards.drain()

        # Seul le Board actif de la Session neuve est rouvert (`last_opened_at`, `updated_at`).
        after = await core.boards.list(include_archived=True)
        reopened = {b.board_id: b for b in after}[view.session.active_board_id]
        assert reopened.last_opened_at is not None
        assert [replace(b, last_opened_at=None, updated_at=b.created_at) for b in after] == [
            replace(b, last_opened_at=None, updated_at=b.created_at) for b in boards_before]
        assert [b for b in after if b.board_id != reopened.board_id] == [
            b for b in boards_before if b.board_id != reopened.board_id]
        assert (await core.boards.get(other.board_id)).task_refs == ("t1",)
        assert core.interaction_mode.mode is InteractionMode.PRESENTATION
        assert await core.state.get_job(job.id) == stored_job
        assert view.binding.conversation_id != before.binding.conversation_id
        assert await core.state.get_conversation(view.binding.conversation_id) is not None
    finally:
        await core.stop()


async def _move_open_session_to(core: JarvisCoreApplication, board_id: str) -> None:
    """Le Board actif ne bouge que par la bascule (Slice 04b) : écrit ici directement."""

    session = (await core.sessions.current()).session
    visited = session.visited_board_ids if board_id in session.visited_board_ids else (
        *session.visited_board_ids, board_id)
    await core.sessions._repo.save_session(replace(session, active_board_id=board_id, visited_board_ids=visited))


async def _switch_open_session_to(core: JarvisCoreApplication, board_id: str) -> None:
    """Bascule réelle sans hôte : liaison du Board créée puis promue (A/B/A), comme `BoardService.switch`."""

    session = (await core.sessions.current()).session
    await core.sessions.binding_for(session.jarvis_session_id, board_id)
    await core.sessions.commit_promotion(session.jarvis_session_id, await core.boards.get(board_id), None)


async def test_core_restart_resumes_the_open_session(tmp_path):
    """D02 / D-SESS (Slice 03 session-context) : un redémarrage **reprend** la Session ouverte.

    Changement délibéré : avant, ce test exigeait une Session neuve et l'ancienne
    close `core_restart`. Même Session, même Board actif, même conversation de
    la liaison active ; aucune Session close, aucune conversation créée.
    """

    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        other = await core.boards.create({"title": "Projet B"})
        await _switch_open_session_to(core, other.board_id)
        first = await core.sessions.current()
        await core.sessions.record_agent(first.session.jarvis_session_id, other.board_id, agent_cli="claude",
                                         agent_session_id="claude-thread-1")
        first_context = await core.sessions.current_context()
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await core.start()
    try:
        second = await core.sessions.current()
        assert second.session.jarvis_session_id == first.session.jarvis_session_id
        assert second.session.active_board_id == other.board_id
        assert second.binding.conversation_id == first.binding.conversation_id
        assert second.binding.lifecycle is BrainLifecycle.FOREGROUND
        assert second.binding.agent_session_id == "claude-thread-1"  # align_host la reprend par `--resume`
        assert [s.jarvis_session_id for s in await core.sessions.history()] == [first.session.jarvis_session_id]
        assert core.speech_authority.conversation_id == first.binding.conversation_id
        resumed = [data for kind, _, data in journal.lines if kind == "core.session.resumed"]
        assert resumed and resumed[0]["conversation_id"] == first.binding.conversation_id
        assert resumed[0]["has_agent_session_id"] is True and resumed[0]["reconciled_bindings"] == 0
        assert "core.session.opened" not in journal.kinds() and "core.session.closed" not in journal.kinds()
        context = await core.sessions.current_context()
        assert context.context == first_context.context  # même Context actif, non réécrit
        assert [c.context_id for c in await core.sessions.list_contexts()] == [context.context.context_id]
        assert Path(context.workspace_path).is_dir()
    finally:
        await core.stop()


async def test_repeated_start_is_idempotent(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await core.start()
    try:
        first = await core.sessions.current()
        again = await core.sessions.start()
        assert again == first
        assert [kind for kind in journal.kinds() if kind.startswith("core.session.")].count("core.session.opened") == 1
        assert len(await core.sessions.history()) == 1
        assert len(await core.sessions.list_contexts()) == 1
    finally:
        await core.stop()


async def test_resume_reconciles_a_stray_foreground_binding(tmp_path):
    """Base écrite ailleurs : la liaison active n'est plus foreground. La reprise la remet, l'autre est suspendue."""

    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        other = await core.boards.create({"title": "Projet B"})
        session = (await core.sessions.current()).session
        b = await core.sessions.binding_for(session.jarvis_session_id, other.board_id)
        bindings = await core.sessions._repo.list_bindings(session.jarvis_session_id)
        a = next(x for x in bindings if x.board_id == DEFAULT_BOARD_ID)
        await core.sessions._repo.commit_switch(sessions=(), boards=(), bindings=(
            replace(a, lifecycle=BrainLifecycle.SUSPENDED), replace(b, lifecycle=BrainLifecycle.FOREGROUND)))
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await core.start()
    try:
        view = await core.sessions.current()
        assert (view.session.jarvis_session_id, view.binding.board_id) == (session.jarvis_session_id, DEFAULT_BOARD_ID)
        assert view.binding.lifecycle is BrainLifecycle.FOREGROUND
        stray = next(x for x in await core.sessions._repo.list_bindings(session.jarvis_session_id)
                     if x.board_id == other.board_id)
        assert stray.lifecycle is BrainLifecycle.SUSPENDED and stray.conversation_id == b.conversation_id
        resumed = [data for kind, _, data in journal.lines if kind == "core.session.resumed"]
        assert resumed[0]["reconciled_bindings"] == 2
    finally:
        await core.stop()


async def test_resume_falls_back_to_default_when_the_active_board_is_archived(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        other = await core.boards.create({"title": "Projet B"})
        await _switch_open_session_to(core, other.board_id)
        first = await core.sessions.current()
        default_binding = next(x for x in await core.sessions._repo.list_bindings(first.session.jarvis_session_id)
                               if x.board_id == DEFAULT_BOARD_ID)
        # Archivé hors du service (qui refuse d'archiver le Board actif) : cas d'une base réécrite ailleurs.
        await core.sessions._repo.save_board(archive_board(other, active_board_id=None, now=datetime.now(timezone.utc)))
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await core.start()
    try:
        view = await core.sessions.current()
        assert view.session.jarvis_session_id == first.session.jarvis_session_id  # même Session, repliée
        assert view.session.active_board_id == DEFAULT_BOARD_ID
        assert view.binding.conversation_id == default_binding.conversation_id  # A/B/A : sa liaison
        assert view.binding.lifecycle is BrainLifecycle.FOREGROUND
        assert "core.session.last_board_unavailable" in journal.kinds()
    finally:
        await core.stop()


async def test_resume_rebuilds_a_missing_active_binding(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        other = await core.boards.create({"title": "Projet B"})
        first = await core.sessions.current()
        await _move_open_session_to(core, other.board_id)  # Board actif sans liaison : base abîmée
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await core.start()
    try:
        view = await core.sessions.current()
        assert view.session.jarvis_session_id == first.session.jarvis_session_id
        assert view.binding.board_id == other.board_id and view.binding.lifecycle is BrainLifecycle.FOREGROUND
        assert view.binding.conversation_id != first.binding.conversation_id
        assert "core.session.binding_rebuilt" in journal.kinds()
        old = next(x for x in await core.sessions._repo.list_bindings(first.session.jarvis_session_id)
                   if x.board_id == DEFAULT_BOARD_ID)
        assert old.lifecycle is BrainLifecycle.SUSPENDED
    finally:
        await core.stop()


# ------------------------------------------------------------------ migration : reprise de la conversation


async def test_only_the_migration_run_adopts_the_latest_conversation(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    await state.save_conversation(Conversation(id="older", updated_at=T0))
    await state.save_conversation(Conversation(id="voice-now", updated_at=T0 + timedelta(hours=1)))
    await state.save_conversation(Conversation(id="middle", updated_at=T0 + timedelta(minutes=30)))
    await state.close()

    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        first = await core.sessions.current()
        assert first.binding.conversation_id == "voice-now"
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        # Reprise (Slice 03 session-context) : même Session, même conversation adoptée.
        second = await core.sessions.current()
        assert second.session.jarvis_session_id == first.session.jarvis_session_id
        assert second.binding.conversation_id == "voice-now"
        # Seule une nouvelle Session explicite change de conversation ; jamais une adoption de plus.
        _, third = await core.sessions.start_new_session()
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        assert (await core.sessions.current()).binding.conversation_id == third.binding.conversation_id
        assert third.binding.conversation_id not in {"older", "voice-now", "middle"}
    finally:
        await core.stop()


async def test_the_migration_run_on_an_empty_store_creates_a_conversation(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        view = await core.sessions.current()
        assert await core.state.get_conversation(view.binding.conversation_id) is not None
    finally:
        await core.stop()


# ------------------------------------------------------------------ reprise QA Slice 03


async def test_binding_for_refuses_even_an_existing_binding_of_a_closed_session(world):
    """`ensure_open` avant la recherche : la liaison existante d'une Session close n'est pas rendue."""

    sessions, _, _, _, _ = world
    old = await sessions.current()
    await sessions.start_new_session()
    with pytest.raises(BoardError) as raised:
        await sessions.binding_for(old.session.jarvis_session_id, DEFAULT_BOARD_ID)
    assert raised.value.code.value == "session_closed"


async def _store_with_conversations(tmp_path) -> None:
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    await state.save_conversation(Conversation(id="older", updated_at=T0))
    await state.save_conversation(Conversation(id="voice-now", updated_at=T0 + timedelta(hours=1)))
    await state.close()


async def test_a_crash_after_ensure_default_still_adopts_at_the_next_start(tmp_path):
    """`default` validé, Core tué avant `SessionManager.start()` : le démarrage suivant adopte."""

    await _store_with_conversations(tmp_path)
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    boards = BoardService(SQLiteBoardRepository(state), interaction_mode=InteractionModeService(events=Bus()))
    assert await boards.ensure_default() is True
    await state.close()  # « crash » : aucune Session écrite

    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        assert (await core.sessions.current()).binding.conversation_id == "voice-now"
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        # Une Session existe désormais : elle est reprise (Slice 03 session-context), jamais réadoptée.
        assert (await core.sessions.current()).binding.conversation_id == "voice-now"
        assert len(await core.sessions.history()) == 1
    finally:
        await core.stop()


async def test_a_slice_02_era_store_with_default_and_no_session_adopts(tmp_path):
    """Base où la Slice 02 a créé `default` (mode déjà choisi), sans aucune Session : adoption."""

    await _store_with_conversations(tmp_path)
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    repo = SQLiteBoardRepository(state)
    boards = BoardService(repo, interaction_mode=InteractionModeService(events=Bus()))
    await boards.ensure_default()
    assert await repo.list_sessions(limit=1) == ()
    await state.close()

    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await core.start()
    try:
        assert (await core.sessions.current()).binding.conversation_id == "voice-now"
        opened = [data for kind, _, data in journal.lines if kind == "core.session.opened"]
        assert opened[-1]["adopted_conversation"] is True
    finally:
        await core.stop()
