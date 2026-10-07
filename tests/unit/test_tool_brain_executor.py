"""Exécuteur des actions du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S6). Contrat : §14.

La scène est la **vraie** (`SceneService` sur dépôt mémoire), les Boards sont soit un double qui dit son état, soit
le vrai `BoardService` (bascule). Ce qui doit tenir :

- la mutation passe par `SceneService.apply_if` / `BoardService.switch(origin="brain")`, jamais ailleurs ;
- hors mode `active` (porte fermée), rien ne s'exécute, l'action reste en file ;
- exactement une fois : double déclenchement et courses concurrentes ne mutent qu'une fois ;
- matrice d'invalidation : id inconnu, objet archivé, époque périmée, Board changé, parole interrompue ; le refus est
  typé, le propriétaire n'est jamais atteint avec un id fabriqué, l'invalidation prévient le runtime ;
- une panne ou une annulation en vol n'est jamais rejouée ; une bascule différée est un statut à part entière.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.board_service import BoardService
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.scene_service import SceneService
from jarvis.core.session_manager import SessionManager
from jarvis.core.speech_authority import SpeechAuthority
from jarvis.core.v2_services import ConversationService
from jarvis.domain.scene import (
    SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload,
)
from jarvis.domain.workspace_board import Board, BoardError, BoardErrorCode, BoardStatus
from jarvis.runtime.tool_brain_choices import read_ui_state
from jarvis.runtime.tool_brain_executor import (
    NO_ADAPTER, NOT_DUE, SKIPPED, BoardSwitchAdapter, SceneMoveAdapter, UiActionExecutor,
    core_board_switcher, default_adapters,
)
from jarvis.runtime.tool_brain_queue import (
    CANCELLED, DONE, FAILED, INVALIDATED, QUEUED, SCHEDULED, ActionRecord, ToolBrainActionQueue, Trigger,
    TriggerContext, preconditions_from,
)
from tests.unit.test_board_switch import Bus, Clock as BoardClock, Host, Journal
from tests.unit.test_scene_service import MemoryRepository

AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
DISPLAY, WORKSPACE = "jarvis-display", "jarvis-workspace"
NOTE_A, NOTE_B = "brain-note-a", "brain-note-b"


class Clock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


class FakeBoards:
    """Dit son état ; `before_read` permet de faire arriver un fait pendant la relecture de l'état."""

    def __init__(self) -> None:
        self.active = "default"
        self.before_read = None
        self.fail = None

    async def list(self, *, include_archived=False):
        if self.fail is not None:
            raise self.fail
        return (Board(board_id="default", title="Principal", created_at=AT, updated_at=AT),
                Board(board_id="board_aaa", title="Projet A", created_at=AT, updated_at=AT),
                Board(board_id="board_old", title="Ancien", created_at=AT, updated_at=AT, status=BoardStatus.ARCHIVED))

    async def active_board_id(self):
        if self.before_read is not None:
            self.before_read()
        return self.active


class SpyScene:
    """Le vrai `SceneService`, avec un compteur sur la seule porte d'écriture qu'on lui connaît."""

    def __init__(self, service: SceneService) -> None:
        self.service, self.writes = service, 0
        self.fail: BaseException | None = None
        self.delay = 0.0

    @property
    def epoch(self):
        return self.service.epoch

    async def snapshot(self):
        return await self.service.snapshot()

    async def apply_if(self, plan):
        self.writes += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return await self.service.apply_if(plan)

    async def apply(self, command):  # pragma: no cover - the executor must never call it
        raise AssertionError("the executor writes through apply_if only")


def note(object_id: str, *, geometry: bool = True) -> SceneCommand:
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id=object_id,
                        fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="note",
                                                 payload=ScenePayload(title=object_id),
                                                 geometry=SceneGeometry(0, 0, 10, 10) if geometry else None))


class Rig:
    def __init__(self, scene: SpyScene, boards, *, adapters=None, gate=lambda: True) -> None:
        self.clock, self.scene, self.boards = Clock(), scene, boards
        self.queue = ToolBrainActionQueue(clock=self.clock)
        self.speech = None
        self.results, self.traces = [], []
        self.executor = UiActionExecutor(scene, boards, self.queue,
                                         adapters if adapters is not None else default_adapters(scene, boards),
                                         gate=gate)
        self.executor.attach(context=lambda: TriggerContext(self.clock(), self.speech),
                             on_result=lambda result, record: self.results.append((result, record)),
                             trace=lambda kind, message, **kw: self.traces.append((kind, kw.get("level"), kw.get("data"))))

    async def plan(self, action_id, tool="scene_move", arguments=None, *, server=DISPLAY, trigger=None, ref="now",
                   **extra) -> str:
        state = await read_ui_state(self.scene, self.boards)
        observed = state.ref() if ref == "now" else ref
        arguments = arguments if arguments is not None else {"object_ids": [NOTE_A], "dx": 5, "dy": 0}
        added = self.queue.add(ActionRecord(action_id, server, tool, arguments, trigger=Trigger.from_payload(trigger),
                                            planned_from=observed, preconditions=preconditions_from(observed), **extra))
        assert added.queued, added
        return action_id

    async def x_of(self, object_id=NOTE_A) -> float:
        return (await self.scene.snapshot()).get_object(object_id).geometry.x

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.traces]


@pytest.fixture
async def rig():
    service = SceneService(MemoryRepository())
    await service.start()
    for object_id in (NOTE_A, NOTE_B):
        await service.apply(note(object_id))
    yield Rig(SpyScene(service), FakeBoards())
    await service.close()


# ------------------------------------------------------------------ exécution par le propriétaire


async def test_scene_move_goes_through_apply_if_once_and_the_scene_really_moves(rig):
    await rig.plan("a1")
    before = (await rig.scene.snapshot()).revision
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (DONE, "applied") and rig.scene.writes == 1
    assert await rig.x_of() == 5 and await rig.x_of(NOTE_B) == 0  # only the chosen object
    assert (await rig.scene.snapshot()).revision == before + 1 and result.detail["revision"] == before + 1
    assert rig.queue.get("a1").status == DONE and "tool_brain.action.done" in rig.kinds()
    assert rig.traces[-1][2] == {"action_id": "a1", "tool": "scene_move", "code": "applied", "decision_id": None,
                                 "trigger": "now"}  # ids and codes only, never arguments


async def test_a_duplicate_trigger_and_concurrent_executions_mutate_exactly_once(rig):
    await rig.plan("a1")
    rig.scene.delay = 0.01
    first, second, third = await asyncio.gather(*(rig.executor.execute("a1") for _ in range(3)))
    statuses = sorted(item.status for item in (first, second, third))
    assert statuses == [DONE, SKIPPED, SKIPPED] and rig.scene.writes == 1 and await rig.x_of() == 5
    again = await rig.executor.execute("a1")
    assert (again.status, again.code) == (SKIPPED, "not_pending") and await rig.x_of() == 5


async def test_a_closed_gate_executes_nothing_and_leaves_the_action_pending(rig):
    closed = Rig(rig.scene, rig.boards, gate=lambda: False)
    await closed.plan("a1")
    result = await closed.executor.execute("a1")
    assert (result.status, result.code) == (SKIPPED, "execution_disabled")
    assert rig.scene.writes == 0 and await rig.x_of() == 0
    assert closed.queue.get("a1").status == QUEUED and closed.results == []


async def test_an_unattached_executor_refuses_to_act(rig):
    bare = UiActionExecutor(rig.scene, rig.boards, rig.queue, default_adapters(rig.scene, rig.boards), gate=lambda: True)
    await rig.plan("a1")
    with pytest.raises(RuntimeError):
        await bare.execute("a1")
    assert rig.scene.writes == 0


async def test_an_action_that_is_not_due_is_skipped_and_stays_queued(rig):
    await rig.plan("a1", trigger={"type": "delay", "seconds": 5})
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (SKIPPED, NOT_DUE) and rig.queue.get("a1").status == QUEUED
    rig.clock.now += 6
    assert (await rig.executor.execute("a1")).status == DONE


async def test_an_expired_action_is_retired_not_executed(rig):
    await rig.plan("a1")
    rig.clock.now += 31
    result = await rig.executor.execute("a1")
    assert result.status == "expired" and rig.scene.writes == 0 and await rig.x_of() == 0


# ------------------------------------------------------------------ matrice d'invalidation


async def _archive(rig, object_id):
    from jarvis.domain.scene_selection import SceneSelection

    update = await rig.scene.service.apply(SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=SceneActor.USER,
                                                        selection=SceneSelection(ids=(object_id,))))
    assert update.outcome.value == "applied"


@pytest.mark.parametrize("case,code", [
    ("unknown_id", "unknown_object"), ("archived", "object_archived"), ("stale_epoch", "stale_scene_epoch"),
    ("board_switched", "stale_active_board"), ("other_scene", "stale_scene_epoch")])
async def test_invalidation_matrix_refuses_typed_wakes_the_runtime_and_never_reaches_the_owner(rig, case, code):
    args = {"object_ids": [NOTE_A], "dx": 5, "dy": 0}
    ref = "now"
    if case == "unknown_id":
        args["object_ids"] = ["brain-fabricated-id"]
    if case == "stale_epoch":
        state = await read_ui_state(rig.scene, rig.boards)
        ref = state.ref().__class__(state.ref().scene_id, "older-epoch", state.ref().revision, state.ref().active_board_id)
    if case == "other_scene":
        state = await read_ui_state(rig.scene, rig.boards)
        ref = state.ref().__class__("scene-elsewhere", state.ref().epoch, 1, state.ref().active_board_id)
    await rig.plan("a1", arguments=args, ref=ref)
    if case == "archived":
        await _archive(rig, NOTE_A)
    if case == "board_switched":
        rig.boards.active = "board_aaa"  # the user left the board the action was planned for
    revision = (await rig.scene.snapshot()).revision

    result = await rig.executor.execute("a1")

    assert result.status == INVALIDATED and result.code == code
    assert code in {item["code"] for item in result.detail["refusals"]}
    assert rig.scene.writes == 0 and (await rig.scene.snapshot()).revision == revision  # the owner was never reached
    assert rig.queue.get("a1").status == INVALIDATED
    (notified, record), = rig.results
    assert notified.status == INVALIDATED and record.action_id == "a1"  # the runtime is told, to replan at once
    assert ("tool_brain.action.invalidated", "warning") in [(kind, level) for kind, level, _ in rig.traces]


async def test_an_interrupted_response_never_executes_its_bound_action(rig):
    await rig.plan("a1", trigger={"type": "speech_chunk", "chunk_id": "k1"})
    rig.speech = {"chains": [{"chain": "r1", "corr": "c1", "n": 2, "state": "playing", "phases": "Pp",
                              "chunks": [{"id": "k1", "i": 0, "ph": "playing"}]}], "obsolete_chunk_ids": []}
    cut = {"chains": [{"chain": "r1", "corr": "c1", "n": 2, "state": "interrupted", "phases": "io",
                       "chunks": [{"id": "k1", "i": 0, "ph": "interrupted"}]}], "obsolete_chunk_ids": ["k2"]}
    rig.speech = cut
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (CANCELLED, "speech_obsolete")
    assert rig.scene.writes == 0 and await rig.x_of() == 0 and rig.results[-1][0].status == CANCELLED


async def test_an_interruption_arriving_while_the_state_is_re_read_still_stops_the_write(rig):
    await rig.plan("a1", trigger={"type": "speech_chunk", "chunk_id": "k1"})
    live = {"chains": [{"chain": "r1", "corr": "c1", "n": 2, "state": "playing", "phases": "Pp",
                        "chunks": [{"id": "k1", "i": 0, "ph": "playing"}]}], "obsolete_chunk_ids": []}
    rig.speech = live

    def interrupt():
        rig.speech = {"chains": [{"chain": "r1", "corr": "c1", "n": 2, "state": "interrupted", "phases": "io",
                                  "chunks": [{"id": "k1", "i": 0, "ph": "interrupted"}]}], "obsolete_chunk_ids": []}

    rig.boards.before_read = interrupt  # the user talks over Jarvis between the due-check and the write
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (CANCELLED, "speech_obsolete") and rig.scene.writes == 0


async def test_the_owners_own_refusal_is_an_invalidation_not_a_failure(rig):
    await rig.scene.service.apply(note("brain-note-loose", geometry=False))
    await rig.plan("a1", arguments={"object_ids": ["brain-note-loose"], "dx": 1, "dy": 0})
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (INVALIDATED, "unplaced") and rig.scene.writes == 1
    assert rig.results[-1][0].status == INVALIDATED


async def test_a_plan_for_another_scene_cannot_write_even_if_it_reaches_the_owner(rig):
    """Défense en profondeur : `apply_if` relit `scene_id` sous son verrou."""

    adapter = SceneMoveAdapter(rig.scene)
    from jarvis.runtime.tool_brain_executor import ExecContext

    outcome = await adapter.execute({"object_ids": [NOTE_A], "dx": 5, "dy": 0}, ExecContext(scene_id="scene-elsewhere"))
    assert (outcome.status, outcome.code) == ("refused", "stale_scene_epoch") and await rig.x_of() == 0


@pytest.mark.parametrize("arguments", [
    {"object_ids": [NOTE_A]}, {"object_ids": [NOTE_A], "dx": "5", "dy": 0},
    {"object_ids": [NOTE_A], "select": {"kinds": ["artifact"]}, "dx": 1, "dy": 0}, {"dx": 1, "dy": 0},
    {"object_ids": [NOTE_A], "dx": 1, "dy": 0, "pin": False}])
async def test_malformed_arguments_are_refused_before_any_write(rig, arguments):
    from jarvis.runtime.tool_brain_executor import ExecContext

    before = (await rig.scene.service.snapshot()).revision
    outcome = await SceneMoveAdapter(rig.scene).execute(arguments, ExecContext())
    # S7 : le plan se valide sous le verrou de scène (`run_scene_plan`) ; rien n'est écrit, la révision ne bouge pas.
    assert (outcome.status, outcome.code) == ("refused", "invalid_arguments")
    assert (await rig.scene.service.snapshot()).revision == before


# ------------------------------------------------------------------ pannes


async def test_an_owner_failure_is_failed_said_and_never_retried(rig):
    await rig.plan("a1")
    rig.scene.fail = RuntimeError("disk full")
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (FAILED, "execution_failed") and "disk full" in result.detail["detail"]
    assert rig.scene.writes == 1
    rig.scene.fail = None
    assert (await rig.executor.execute("a1")).code == "not_pending" and rig.scene.writes == 1 and await rig.x_of() == 0
    assert ("tool_brain.action.failed", "warning") in [(kind, level) for kind, level, _ in rig.traces]


async def test_a_cancellation_during_the_write_leaves_the_action_failed_and_is_never_replayed(rig):
    await rig.plan("a1")
    rig.scene.service._repository.commit_delay = 0.05  # the owner is slow *inside* its own protected write
    task = asyncio.ensure_future(rig.executor.execute("a1"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.1)  # the protected write finished on its own
    view = rig.queue.get("a1")
    assert (view.status, view.code) == (FAILED, "execution_interrupted")
    assert await rig.x_of() == 5  # applied once by the owner, and nothing replays it
    assert (await rig.executor.execute("a1")).code == "not_pending" and await rig.x_of() == 5


async def test_an_unreadable_state_means_no_mutation(rig):
    await rig.plan("a1")
    rig.boards.fail = OSError("db locked")
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (FAILED, "state_unreadable") and rig.scene.writes == 0


async def test_a_tool_without_an_adapter_fails_typed_and_touches_no_owner(rig):
    bare = Rig(rig.scene, rig.boards, adapters={})
    await bare.plan("a1", tool="scene_get", arguments={"object_ids": [NOTE_A]})
    result = await bare.executor.execute("a1")
    assert (result.status, result.code) == (FAILED, NO_ADAPTER) and rig.scene.writes == 0


async def test_the_default_adapters_are_exactly_the_reviewed_reversible_mutation_paths(rig):
    """S6 : `scene_move` et `board_switch` ; S7 : les mutateurs de scène réversibles et les verbes de surface.

    Jamais `scene_archive` (irréversible : S8), la création de contenu ni une lecture.
    """

    adapters = set(default_adapters(rig.scene, rig.boards))
    assert adapters == {(DISPLAY, "scene_move"), (WORKSPACE, "board_switch"), (DISPLAY, "scene_update_object"),
                        (DISPLAY, "scene_update_many"), (DISPLAY, "scene_pin"), (DISPLAY, "scene_link"),
                        (DISPLAY, "scene_unlink"), ("jarvis-surface", "surface_open"), ("jarvis-surface", "surface_focus"),
                        ("jarvis-surface", "surface_scroll"), ("jarvis-surface", "surface_history"),
                        ("jarvis-surface", "surface_zoom")}
    from jarvis.runtime.mcp_tool_meta import tool_meta

    for server, tool in adapters:
        meta = tool_meta(server, tool)
        assert meta.side_effect == "write" and meta.reversibility == "reversible", (server, tool)


# ------------------------------------------------------------------ Board : bascule et différé


def switcher(*answers):
    calls = []
    script = list(answers)

    async def switch(board_id):
        calls.append(board_id)
        answer = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    switch.calls = calls
    return switch


def board_rig(rig, answer):
    adapters = {(WORKSPACE, "board_switch"): BoardSwitchAdapter(answer)}
    return Rig(rig.scene, rig.boards, adapters=adapters)


BOARD_ARGS = {"board_id": "board_aaa"}


async def test_an_applied_switch_cancels_the_other_pending_actions_that_targeted_the_old_board(rig):
    answer = switcher({"status": "applied", "board_id": "board_aaa", "previous_board_id": "default"})
    local = Rig(rig.scene, rig.boards, adapters={**default_adapters(rig.scene, rig.boards),
                                                  (WORKSPACE, "board_switch"): BoardSwitchAdapter(answer)})
    await local.plan("sw", "board_switch", BOARD_ARGS, server=WORKSPACE)
    await local.plan("mv", trigger={"type": "event", "name": "later_fact"})
    result = await local.executor.execute("sw")
    assert (result.status, result.code) == (DONE, "applied") and answer.calls == ["board_aaa"]
    assert (local.queue.get("mv").status, local.queue.get("mv").code) == (CANCELLED, "authority_changed")


async def test_a_deferred_switch_is_scheduled_not_done_and_never_replayed(rig):
    answer = switcher({"status": "scheduled", "board_id": "board_aaa", "replaced_board_id": None})
    local = board_rig(rig, answer)
    await local.plan("sw", "board_switch", BOARD_ARGS, server=WORKSPACE)
    result = await local.executor.execute("sw")
    assert (result.status, result.code) == (SCHEDULED, "scheduled") and result.detail["board_id"] == "board_aaa"
    assert local.queue.get("sw").status == SCHEDULED
    assert (await local.executor.execute("sw")).code == "not_pending" and answer.calls == ["board_aaa"]
    assert ("tool_brain.action.scheduled", "info") in [(kind, level) for kind, level, _ in local.traces]


async def test_an_unchanged_switch_is_done_with_its_own_code(rig):
    local = board_rig(rig, switcher({"status": "unchanged", "board_id": "board_aaa"}))
    await local.plan("sw", "board_switch", BOARD_ARGS, server=WORKSPACE)
    result = await local.executor.execute("sw")
    assert (result.status, result.code) == (DONE, "unchanged")


async def test_the_switch_of_an_archived_or_unknown_board_never_reaches_the_owner(rig):
    answer = switcher({"status": "applied"})
    local = board_rig(rig, answer)
    for action_id, board_id, code in (("s1", "board_old", "board_archived"), ("s2", "board_ghost", "board_not_found")):
        await local.plan(action_id, "board_switch", {"board_id": board_id}, server=WORKSPACE)
        result = await local.executor.execute(action_id)
        assert (result.status, result.code) == (INVALIDATED, code)
    assert answer.calls == []


@pytest.mark.parametrize("error,status,code", [
    (BoardError(BoardErrorCode.BOARD_ARCHIVED, "archived meanwhile"), INVALIDATED, "board_archived"),
    (BoardError(BoardErrorCode.BOARD_NOT_FOUND, "gone"), INVALIDATED, "board_not_found"),
    (BoardError(BoardErrorCode.BOARD_SWITCH_ROLLED_BACK, "host refused"), FAILED, "execution_failed"),
    (BoardError(BoardErrorCode.BOARD_ACTIVATION_FAILED, "claude would not start"), FAILED, "execution_failed"),
    (RuntimeError("boom"), FAILED, "execution_failed")])
async def test_owner_errors_of_a_switch_are_classified_not_swallowed(rig, error, status, code):
    local = board_rig(rig, switcher(error))
    await local.plan("sw", "board_switch", BOARD_ARGS, server=WORKSPACE)
    result = await local.executor.execute("sw")
    assert (result.status, result.code) == (status, code)


async def test_an_unknown_owner_status_is_a_failure_not_a_success(rig):
    local = board_rig(rig, switcher({"status": "maybe"}))
    await local.plan("sw", "board_switch", BOARD_ARGS, server=WORKSPACE)
    assert (await local.executor.execute("sw")).status == FAILED


# ------------------------------------------------------------------ vrai BoardService


@pytest.fixture
async def real_boards(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    journal, clock, bus, host, authority = Journal(), BoardClock(), Bus(), Host(), SpeechAuthority()
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
    try:
        yield boards, bus, journal
    finally:
        await boards.stop()
        await state.close()


async def test_a_real_board_switch_runs_through_boardservice_with_the_brain_origin(real_boards):
    boards, bus, journal = real_boards
    service = SceneService(MemoryRepository())
    await service.start()
    target = await boards.create({"title": "Projet B"})
    local = Rig(SpyScene(service), boards)
    await local.plan("sw", "board_switch", {"board_id": target.board_id}, server=WORKSPACE)
    other = await local.plan("mv", trigger={"type": "event", "name": "later"})

    result = await local.executor.execute("sw")

    assert (result.status, result.code) == (DONE, "applied")
    assert await boards.active_board_id() == target.board_id
    assert ("core.board.switched", {"origin": "brain"}) in [
        (kind, {"origin": data["origin"]}) for kind, _, data in journal.lines if kind == "core.board.switched"]
    assert [event.payload["origin"] for event in bus.events if event.message_type == "board.switched"] == ["brain"]
    assert local.queue.get(other).code == "authority_changed"
    await local.plan("again", "board_switch", {"board_id": target.board_id}, server=WORKSPACE)
    assert (await local.executor.execute("again")).code == "unchanged"  # already there: the owner says so
    await service.close()


async def test_a_real_scene_move_through_the_default_adapters_and_the_real_board_state(real_boards):
    boards, _, _ = real_boards
    service = SceneService(MemoryRepository())
    await service.start()
    await service.apply(note(NOTE_A))
    local = Rig(SpyScene(service), boards)
    await local.plan("mv", arguments={"object_ids": [NOTE_A], "dx": 7, "dy": -2, "pin": True})
    result = await local.executor.execute("mv")
    assert result.status == DONE and result.detail["changed"] == 1
    moved = (await service.snapshot()).get_object(NOTE_A)
    assert (moved.geometry.x, moved.geometry.y) == (7, -2) and moved.constraints.pinned_by_user
    await service.close()


def test_core_board_switcher_reports_unchanged_for_the_active_board():
    class Result:
        changed, previous_board_id = False, "default"

    class Boards:
        async def switch(self, board_id, *, origin="protocol"):
            assert origin == "brain"
            return Result()

    assert asyncio.run(core_board_switcher(Boards())("default")) == {
        "status": "unchanged", "board_id": "default", "previous_board_id": "default"}


# ------------------------------------------------------------------ rework S6 : aucune action ne reste `executing`


class _Boom:
    """Un point de la séquence après la prise qui lève : l'action doit tout de même finir."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def __call__(self, *args, **kwargs):
        raise self.error


@pytest.mark.parametrize("hook", ["recheck", "_refusals"])
async def test_any_exception_between_the_claim_and_the_adapter_still_ends_the_action(rig, monkeypatch, hook):
    await rig.plan("a1")
    target = rig.queue if hook == "recheck" else rig.executor
    monkeypatch.setattr(target, hook, _Boom(RuntimeError("bug in the sequence")))
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (FAILED, "execution_failed") and "bug in the sequence" in result.detail["detail"]
    view = rig.queue.get("a1")
    assert view.status == FAILED and rig.queue.stats()["failed"] == 1
    assert rig.scene.writes == 0 and [item for item, _ in rig.results] == [result]  # the decider is told
    assert "Traceback" in rig.traces[-1][2]["traceback"] and "bug in the sequence" in rig.traces[-1][2]["traceback"]


async def test_a_cancellation_before_the_adapter_settles_the_action_emits_the_result_and_reraises(rig, monkeypatch):
    await rig.plan("a1")
    monkeypatch.setattr(rig.queue, "recheck", _Boom(asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await rig.executor.execute("a1")
    assert (rig.queue.get("a1").status, rig.queue.get("a1").code) == (FAILED, "execution_interrupted")
    assert [(result.status, result.code) for result, _ in rig.results] == [(FAILED, "execution_interrupted")]
    assert rig.scene.writes == 0


async def test_a_scene_that_is_not_served_is_an_infrastructure_failure_not_an_invalidation(rig):
    from jarvis.ports.scene import SceneStoreErrorCode, SceneUnavailableError

    await rig.plan("a1")
    rig.scene.fail = SceneUnavailableError(SceneStoreErrorCode.CORRUPTED, "scene diverged")
    result = await rig.executor.execute("a1")
    assert (result.status, result.code) == (FAILED, "scene_unavailable") and "diverged" in result.detail["detail"]
    assert rig.queue.stats()["invalidated"] == 0  # no replan streak, no thrash cooldown


async def test_a_failed_adapter_keeps_its_stack_in_the_journal_but_not_in_the_decider_detail(rig):
    await rig.plan("a1")
    rig.scene.fail = RuntimeError("disk full")
    result = await rig.executor.execute("a1")
    assert "traceback" not in result.detail and result.detail["error_class"] == "RuntimeError"
    assert "RuntimeError: disk full" in rig.traces[-1][2]["traceback"]
