"""Transaction de bascule de Board et nouvelle Session avec l'hôte des cerveaux (handoff board-session, Slice 04b).

Contrat : `docs/boards.md` › *Switch and speech authority*. Base temporaire,
hôte (Control Center) simulé : il enregistre ses activations et peut échouer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.board_service import BoardService
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.session_manager import SessionManager
from jarvis.core.speech_authority import BOARD_SWITCHED, BOARD_VOICE_BINDING_CHANGED, SpeechAuthority
from jarvis.core.v2_services import ConversationService
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_ID, BoardError, BoardErrorCode, BrainLifecycle, archive_board, set_interaction_mode,
)
from jarvis.ports.workspace_board import HOST_UNCHANGED, HOST_UNKNOWN, BoardActivation

T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


class Bus:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, envelope) -> None:
        self.events.append(envelope)

    def types(self) -> list[str]:
        return [event.message_type for event in self.events]


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.lines.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.lines]

    def data(self, kind: str) -> dict:
        return next(data for k, _, data in self.lines if k == kind)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def host_error(state: str = HOST_UNCHANGED) -> BoardError:
    error = BoardError(BoardErrorCode.BOARD_ACTIVATION_FAILED, "claude would not start")
    error.host_state = state
    return error


class Host:
    """Hôte simulé : `failures` est consommé une activation après l'autre (None = réussite)."""

    def __init__(self) -> None:
        self.calls = []
        self.failures: list[BaseException | None] = []
        self.previous_lifecycle = BrainLifecycle.SUSPENDED

    async def activate(self, binding) -> BoardActivation:
        self.calls.append(binding)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        return BoardActivation(agent_cli="claude", agent_session_id=f"cli-{binding.conversation_id[:8]}",
                               previous_lifecycle=self.previous_lifecycle)


@pytest.fixture
async def world(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    journal, clock, bus, host, authority = Journal(), Clock(), Bus(), Host(), SpeechAuthority()
    modes = InteractionModeService(events=Bus(), diagnostics=journal, epoch="e1")
    repo = SQLiteBoardRepository(state)
    boards = BoardService(repo, interaction_mode=modes, diagnostics=journal, clock=clock)
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    sessions = SessionManager(repo, boards=boards, conversations=conversations, diagnostics=journal, clock=clock,
                              authority=authority, host=host, events=bus)
    boards.configure_transitions(sessions=sessions, authority=authority, host=host, events=bus)
    await boards.ensure_default()
    await sessions.start()
    await boards.start(ensure_default=False)
    world = type("World", (), {})()
    world.__dict__.update(state=state, journal=journal, bus=bus, host=host, authority=authority, modes=modes,
                          repo=repo, boards=boards, sessions=sessions)
    try:
        yield world
    finally:
        await boards.stop()
        await state.close()


async def snapshot(world) -> tuple:
    """Tout ce qu'une bascule peut écrire : Session, liaisons, Boards."""

    view = await world.sessions.current()
    bindings = tuple(sorted((b.board_id, b.lifecycle.value, b.agent_session_id)
                            for b in await world.repo.list_bindings(view.session.jarvis_session_id)))
    boards = tuple((b.board_id, b.last_opened_at) for b in await world.repo.list_boards())
    return view.session, bindings, boards


# ------------------------------------------------------------------ réussite


async def test_switch_activates_then_commits_then_moves_the_authority_then_publishes(world):
    before = await world.sessions.current()
    assert world.authority.conversation_id == before.binding.conversation_id
    board = await world.boards.create({"title": "Projet B"})
    world.host.previous_lifecycle = BrainLifecycle.BACKGROUND_RUNNING

    result = await world.boards.switch(board.board_id)

    assert result.changed and result.previous_board_id == DEFAULT_BOARD_ID
    assert [b.board_id for b in world.host.calls] == [board.board_id]
    view = await world.sessions.current()
    assert view.session.active_board_id == board.board_id
    assert view.session.visited_board_ids == (DEFAULT_BOARD_ID, board.board_id)
    assert view.binding.lifecycle is BrainLifecycle.FOREGROUND
    assert view.binding.agent_cli == "claude" and view.binding.agent_session_id.startswith("cli-")
    demoted = next(b for b in await world.repo.list_bindings(view.session.jarvis_session_id)
                   if b.board_id == DEFAULT_BOARD_ID)
    # Ce que l'hôte a fait de l'ancien : il travaille encore, il n'est pas suspendu.
    assert demoted.lifecycle is BrainLifecycle.BACKGROUND_RUNNING
    assert (await world.boards.get(board.board_id)).last_opened_at is not None
    assert world.authority.conversation_id == view.binding.conversation_id
    assert world.bus.types() == [BOARD_SWITCHED, BOARD_VOICE_BINDING_CHANGED]
    changed = world.bus.events[-1]
    assert changed.payload["conversation_id"] == view.binding.conversation_id
    assert changed.payload["board_id"] == board.board_id and changed.payload["reason"] == "board_switch"
    assert "core.board.switched" in world.journal.kinds()


async def test_a_b_a_returns_to_the_same_binding_and_conversation(world):
    first = await world.sessions.current()
    board = await world.boards.create({"title": "Projet B"})
    await world.boards.switch(board.board_id)
    back = await world.boards.switch(DEFAULT_BOARD_ID)

    assert back.binding.conversation_id == first.binding.conversation_id
    assert back.session.visited_board_ids == (DEFAULT_BOARD_ID, board.board_id)
    assert [b.conversation_id for b in world.host.calls][-1] == first.binding.conversation_id
    assert world.authority.conversation_id == first.binding.conversation_id


async def test_switch_to_the_active_board_changes_nothing(world):
    before = await snapshot(world)
    result = await world.boards.switch(DEFAULT_BOARD_ID)
    assert not result.changed
    assert await snapshot(world) == before
    assert world.host.calls == [] and world.bus.events == []


@pytest.mark.parametrize("board_id,code", [("board_" + "0" * 32, BoardErrorCode.BOARD_NOT_FOUND),
                                           ("", BoardErrorCode.INVALID_BOARD)])
async def test_switch_refuses_an_unknown_or_empty_board_before_touching_anything(world, board_id, code):
    before = await snapshot(world)
    with pytest.raises(BoardError) as caught:
        await world.boards.switch(board_id)
    assert caught.value.code is code
    assert await snapshot(world) == before and world.host.calls == []


async def test_switch_refuses_an_archived_board(world):
    board = await world.boards.create({"title": "Vieux"})
    await world.repo.save_board(archive_board(board, active_board_id=DEFAULT_BOARD_ID, now=T0 + timedelta(days=1)))
    with pytest.raises(BoardError) as caught:
        await world.boards.switch(board.board_id)
    assert caught.value.code is BoardErrorCode.BOARD_ARCHIVED and world.host.calls == []


# ------------------------------------------------------------------ retours arrière


async def test_host_failure_aborts_with_nothing_committed(world):
    board = await world.boards.create({"title": "Projet B"})
    before_authority = world.authority.binding
    before = await snapshot(world)
    world.host.failures = [host_error()]

    with pytest.raises(BoardError) as caught:
        await world.boards.switch(board.board_id)

    assert caught.value.code is BoardErrorCode.BOARD_ACTIVATION_FAILED and caught.value.status == 502
    session, bindings, boards = await snapshot(world)
    assert session == before[0] and boards == before[2]
    # Seule la liaison `suspended` de B existe en plus (A/B/A la reprendra).
    assert [b for b in bindings if b[0] == DEFAULT_BOARD_ID] == [b for b in before[1] if b[0] == DEFAULT_BOARD_ID]
    assert dict((b[0], b[1]) for b in bindings)[board.board_id] == "suspended"
    assert world.authority.binding == before_authority
    assert world.bus.events == []
    # L'hôte a dit « rien n'a changé » : pas de réactivation inutile.
    assert len(world.host.calls) == 1
    assert world.journal.data("core.board.activation_failed")["host_state"] == HOST_UNCHANGED


async def test_an_uncertain_host_failure_restores_the_previous_brain(world):
    board = await world.boards.create({"title": "Projet B"})
    previous = (await world.sessions.current()).binding
    world.host.failures = [host_error(HOST_UNKNOWN), None]

    with pytest.raises(BoardError):
        await world.boards.switch(board.board_id)

    assert [b.board_id for b in world.host.calls] == [board.board_id, DEFAULT_BOARD_ID]
    assert world.host.calls[-1].conversation_id == previous.conversation_id
    assert "core.board.host_restored" in world.journal.kinds()


async def test_mode_failure_rolls_back_host_and_commits_nothing(world):
    board = await world.boards.create({"title": "Réunion"})
    # Mode réservé (jamais activable en V1) : Core refuse de l'appliquer.
    await world.repo.save_board(set_interaction_mode(board, InteractionMode.MEETING, now=T0 + timedelta(days=1)))
    before = await snapshot(world)
    before_authority = world.authority.binding
    previous = before_authority

    with pytest.raises(BoardError) as caught:
        await world.boards.switch(board.board_id)

    assert caught.value.code is BoardErrorCode.BOARD_SWITCH_ROLLED_BACK and caught.value.status == 500
    session, bindings, boards = await snapshot(world)
    assert session == before[0] and boards == before[2]
    assert [b for b in bindings if b[0] == DEFAULT_BOARD_ID] == [b for b in before[1] if b[0] == DEFAULT_BOARD_ID]
    assert world.authority.binding == before_authority
    assert [b.board_id for b in world.host.calls] == [board.board_id, DEFAULT_BOARD_ID]
    assert world.host.calls[-1].conversation_id == previous.conversation_id
    assert world.modes.mode is InteractionMode.ASSISTANT
    assert world.bus.events == []
    assert world.journal.data("core.board.switch_rolled_back")["step"] == "mode"


async def test_commit_failure_restores_host_and_mode(world, monkeypatch):
    board = await world.boards.create({"title": "Présentation"})
    await world.repo.save_board(set_interaction_mode(board, InteractionMode.PRESENTATION, now=T0 + timedelta(days=1)))
    before = await snapshot(world)
    before_authority = world.authority.binding

    async def refuse(**_):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(world.repo, "commit_switch", refuse)
    with pytest.raises(BoardError) as caught:
        await world.boards.switch(board.board_id)
    monkeypatch.undo()

    assert caught.value.code is BoardErrorCode.BOARD_SWITCH_ROLLED_BACK
    assert "database is locked" in str(caught.value)
    session, bindings, boards = await snapshot(world)
    assert session == before[0] and boards == before[2]
    assert world.authority.binding == before_authority
    assert world.modes.mode is InteractionMode.ASSISTANT  # PRESENTATION appliqué puis retiré
    assert [b.board_id for b in world.host.calls] == [board.board_id, DEFAULT_BOARD_ID]
    assert world.bus.events == []


async def test_switch_applies_the_board_mode_as_board_switch_and_does_not_rewrite_it(world):
    board = await world.boards.create({"title": "Présentation"})
    await world.repo.save_board(set_interaction_mode(board, InteractionMode.PRESENTATION, now=T0 + timedelta(days=1)))
    await world.boards.switch(board.board_id)
    await world.boards.drain()
    assert world.modes.state.mode is InteractionMode.PRESENTATION
    assert world.modes.state.source == "board_switch"
    # Le Board de départ (`unset`) n'a pas reçu ce mode.
    assert (await world.boards.get(DEFAULT_BOARD_ID)).interaction_mode is InteractionMode.ASSISTANT


async def test_choosing_the_mode_already_active_records_it_on_the_board(world):
    """QA Slice 04b, S1 : sans cet enregistrement, A restait `unset` et gardait le mode de B au retour."""

    bus = world.modes._events
    await world.modes.request("assistant", source="user")          # déjà le mode effectif
    await world.boards.drain()
    a = await world.boards.get(DEFAULT_BOARD_ID)
    assert (a.interaction_mode, a.interaction_mode_origin.value) == (InteractionMode.ASSISTANT, "user")
    assert bus.events == []                                          # rien n'a changé : aucun évènement

    b = await world.boards.create({"title": "Présentation"})
    await world.repo.save_board(set_interaction_mode(b, InteractionMode.PRESENTATION, now=T0 + timedelta(days=1)))
    await world.boards.switch(b.board_id)
    assert world.modes.mode is InteractionMode.PRESENTATION
    await world.boards.switch(DEFAULT_BOARD_ID)
    assert world.modes.mode is InteractionMode.ASSISTANT


async def test_switching_to_an_unset_board_applies_the_default_mode_not_the_previous_one(world):
    await world.modes.request("presentation", source="user")
    await world.boards.drain()
    b = await world.boards.create({"title": "Neuf"})
    assert b.interaction_mode_origin.value == "unset"

    await world.boards.switch(b.board_id)
    await world.boards.drain()

    assert world.modes.mode is InteractionMode.ASSISTANT
    assert world.modes.state.source == "board_switch"
    assert (await world.boards.get(b.board_id)).interaction_mode_origin.value == "unset"   # rien écrit
    assert (await world.boards.get(DEFAULT_BOARD_ID)).interaction_mode is InteractionMode.PRESENTATION
    await world.boards.switch(DEFAULT_BOARD_ID)
    assert world.modes.mode is InteractionMode.PRESENTATION


# ------------------------------------------------------------------ nouvelle Session


async def test_new_session_activates_the_new_binding_before_committing(world):
    before = await world.sessions.current()
    world.host.previous_lifecycle = BrainLifecycle.BACKGROUND_RUNNING
    closed, view = await world.sessions.start_new_session()

    assert [b.conversation_id for b in world.host.calls] == [view.binding.conversation_id]
    assert world.host.calls[0].jarvis_session_id == view.session.jarvis_session_id
    assert view.binding.agent_cli == "claude" and view.binding.agent_session_id is not None
    assert world.authority.conversation_id == view.binding.conversation_id
    old = next(b for b in await world.repo.list_bindings(closed.jarvis_session_id))
    assert old.conversation_id == before.binding.conversation_id
    assert old.lifecycle is BrainLifecycle.BACKGROUND_RUNNING
    assert world.bus.types() == [BOARD_VOICE_BINDING_CHANGED]
    assert world.bus.events[0].payload["reason"] == "new_session"


async def test_new_session_host_failure_commits_nothing(world):
    before = await snapshot(world)
    before_authority = world.authority.binding
    world.host.failures = [host_error()]
    with pytest.raises(BoardError) as caught:
        await world.sessions.start_new_session()
    assert caught.value.code is BoardErrorCode.BOARD_ACTIVATION_FAILED
    assert await snapshot(world) == before
    assert world.authority.binding == before_authority and world.bus.events == []


async def test_new_session_commit_failure_restores_the_previous_brain(world, monkeypatch):
    before = await snapshot(world)
    previous = world.authority.binding

    async def refuse(**_):
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(world.repo, "commit_switch", refuse)
    with pytest.raises(BoardError) as caught:
        await world.sessions.start_new_session()
    monkeypatch.undo()
    assert caught.value.code is BoardErrorCode.BOARD_SWITCH_ROLLED_BACK
    assert await snapshot(world) == before
    assert world.host.calls[-1].conversation_id == previous.conversation_id
    assert world.authority.binding == previous and world.bus.events == []


async def test_align_host_at_start_records_the_reported_cli(world):
    assert await world.boards.align_host()
    view = await world.sessions.current()
    assert [b.conversation_id for b in world.host.calls] == [view.binding.conversation_id]
    assert view.binding.agent_cli == "claude" and view.binding.agent_session_id is not None


async def test_align_host_failure_is_said_not_raised(world):
    world.host.failures = [RuntimeError("connection refused")]
    assert not await world.boards.align_host()
    assert world.journal.data("core.board.host_align_deferred")["exception_type"] == "RuntimeError"
