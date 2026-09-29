"""Contrat pur Board / Session / liaison (handoff board-session, Slice 01).

Domaine pur : rien n'est persisté, servi ni affiché ici. Voir `docs/boards.md`.
"""
from __future__ import annotations

import ast
import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.workspace_board import (
    BOARD_ID_PREFIX, DEFAULT_BOARD_ID, HTTP_STATUS, MAX_CONTEXT_SUMMARY_CHARS, MAX_TITLE_CHARS,
    SESSION_ID_PREFIX, BindingStatus, Board, BoardConversationBinding, BoardError, BoardErrorCode,
    BoardStatus, BrainLifecycle, InteractionModeOrigin, JarvisSession, SceneRef, SessionEndReason,
    SessionStatus, adopt_legacy_interaction_mode, archive_board, check_bindings, close_binding,
    close_session, create_board, default_board, find_binding, mark_opened, new_binding, open_session,
    promote_binding, record_agent_session, set_interaction_mode, set_lifecycle, update_board, visit_board,
)

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


def t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def code_of(excinfo: pytest.ExceptionInfo[BoardError]) -> str:
    return excinfo.value.code.value


@pytest.fixture
def boards() -> tuple[Board, Board]:
    return default_board(now=T0), create_board("  Projet B  ", now=T0)


# ---------------------------------------------------------------- codes et identifiants


def test_error_codes_are_stable_and_all_mapped_to_http():
    assert {c.value for c in BoardErrorCode} == {
        "board_not_found", "board_archived", "board_is_active", "session_not_found", "session_closed",
        "binding_not_found", "binding_conflict", "invalid_title", "context_summary_too_long",
        "invalid_board", "invalid_session", "invalid_binding",
    }
    assert set(HTTP_STATUS) == set(BoardErrorCode)
    err = BoardError(BoardErrorCode.BOARD_IS_ACTIVE, "x")
    assert isinstance(err, ValueError) and err.code == "board_is_active" and err.status == 409


def test_ids_use_the_documented_prefixes_and_default(boards):
    default, other = boards
    assert default.board_id == DEFAULT_BOARD_ID == "default" and default.is_default
    assert other.board_id.startswith(BOARD_ID_PREFIX) and other.title == "Projet B"
    session = open_session(default, now=T0)
    assert session.jarvis_session_id.startswith(SESSION_ID_PREFIX)
    assert default.interaction_mode_origin is InteractionModeOrigin.UNSET


def test_enum_values_are_the_wire_values():
    assert [s.value for s in BoardStatus] == ["active", "archived"]
    assert [s.value for s in SessionStatus] == ["open", "closed"]
    assert [s.value for s in BrainLifecycle] == ["foreground", "background_running", "suspended"]
    assert [s.value for s in InteractionModeOrigin] == ["unset", "migrated", "user"]


# ---------------------------------------------------------------- Board


@pytest.mark.parametrize("title", ["", "   ", "a\nb", "x" * (MAX_TITLE_CHARS + 1), 42])
def test_invalid_titles_are_refused_with_invalid_title(title):
    with pytest.raises(BoardError) as exc:
        create_board(title, now=T0)
    assert code_of(exc) == "invalid_title"


def test_context_summary_is_bounded_not_truncated(boards):
    _, board = boards
    ok = update_board(board, now=t(1), context_summary="x" * MAX_CONTEXT_SUMMARY_CHARS)
    assert len(ok.context_summary) == MAX_CONTEXT_SUMMARY_CHARS and ok.updated_at == t(1)
    with pytest.raises(BoardError) as exc:
        update_board(board, now=t(1), context_summary="x" * (MAX_CONTEXT_SUMMARY_CHARS + 1))
    assert code_of(exc) == "context_summary_too_long"


def test_update_changes_only_given_fields_and_board_is_immutable(boards):
    _, board = boards
    updated = update_board(board, now=t(2), title="Renommé", task_refs=["t1", "t2"])
    assert (updated.title, updated.task_refs, updated.artifact_refs) == ("Renommé", ("t1", "t2"), ())
    assert board.title == "Projet B"
    with pytest.raises(dataclasses.FrozenInstanceError):
        board.title = "x"  # type: ignore[misc]
    meta = {"k": "v"}
    b2 = update_board(board, now=t(2), runtime_metadata=meta)
    meta["k"] = "changed"
    assert b2.runtime_metadata["k"] == "v"
    with pytest.raises(TypeError):
        b2.runtime_metadata["k"] = "x"  # type: ignore[index]


@pytest.mark.parametrize("kwargs", [
    {"task_refs": ["a", "a"]},
    {"artifact_refs": ["x" * 300]},
    {"project_refs": [" a"]},
    {"runtime_metadata": {"bad key": 1}},
    {"runtime_metadata": {"k": {"nested": 1}}},
])
def test_invalid_board_fields_are_refused(boards, kwargs):
    _, board = boards
    with pytest.raises(BoardError) as exc:
        update_board(board, now=t(1), **kwargs)
    assert code_of(exc) == "invalid_board"


def test_archive_refuses_active_board_and_archived_board_refuses_edits(boards):
    default, board = boards
    with pytest.raises(BoardError) as exc:
        archive_board(default, active_board_id=DEFAULT_BOARD_ID, now=t(1))
    assert code_of(exc) == "board_is_active"
    archived = archive_board(board, active_board_id=DEFAULT_BOARD_ID, now=t(1))
    assert archived.status is BoardStatus.ARCHIVED
    assert archive_board(archived, active_board_id=DEFAULT_BOARD_ID, now=t(2)) is archived
    for action in (
        lambda: update_board(archived, now=t(2), title="x"),
        lambda: mark_opened(archived, now=t(2)),
        lambda: open_session(archived, now=t(2)),
        lambda: visit_board(open_session(default, now=t(2)), archived),
    ):
        with pytest.raises(BoardError) as exc:
            action()
        assert code_of(exc) == "board_archived"


def test_interaction_mode_per_board_and_idempotent_legacy_adoption(boards):
    default, _ = boards
    migrated = adopt_legacy_interaction_mode(default, InteractionMode.PRESENTATION, now=t(1))
    assert (migrated.interaction_mode, migrated.interaction_mode_origin) == (
        InteractionMode.PRESENTATION, InteractionModeOrigin.MIGRATED)
    assert adopt_legacy_interaction_mode(migrated, InteractionMode.ASSISTANT, now=t(2)) is migrated
    chosen = set_interaction_mode(migrated, InteractionMode.ASSISTANT, now=t(3))
    assert chosen.interaction_mode_origin is InteractionModeOrigin.USER
    assert adopt_legacy_interaction_mode(chosen, InteractionMode.PRESENTATION, now=t(4)) is chosen
    with pytest.raises(BoardError):
        set_interaction_mode(default, InteractionMode.ASSISTANT, now=t(1), origin=InteractionModeOrigin.UNSET)


# ---------------------------------------------------------------- Session


def test_a_b_a_visit_keeps_first_visit_order_without_duplicates(boards):
    a, b = boards
    session = open_session(a, now=T0)
    s1 = visit_board(session, b)
    s2 = visit_board(s1, a)
    assert (s1.active_board_id, s1.visited_board_ids) == (b.board_id, (a.board_id, b.board_id))
    assert (s2.active_board_id, s2.visited_board_ids) == (a.board_id, (a.board_id, b.board_id))
    assert visit_board(s2, a) is s2


def test_closed_session_is_immutable(boards):
    a, b = boards
    closed = close_session(open_session(a, now=T0), reason=SessionEndReason.NEW_SESSION, now=t(5))
    assert (closed.status, closed.ended_at, closed.end_reason) == (
        SessionStatus.CLOSED, t(5), SessionEndReason.NEW_SESSION)
    for action in (
        lambda: close_session(closed, reason=SessionEndReason.CORE_RESTART, now=t(6)),
        lambda: visit_board(closed, b),
        lambda: new_binding(closed, a, conversation_id="c", agent_cli="claude", now=t(6)),
    ):
        with pytest.raises(BoardError) as exc:
            action()
        assert code_of(exc) == "session_closed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        closed.status = SessionStatus.OPEN  # type: ignore[misc]


@pytest.mark.parametrize("kwargs", [
    {"status": SessionStatus.CLOSED},  # fermée sans ended_at
    {"ended_at": T0},  # ouverte avec ended_at
    {"active_board_id": "board_x"},  # actif hors des visités
    {"visited_board_ids": ("default", "default")},
    {"jarvis_session_id": "sess_1"},
    {"started_at": datetime(2026, 9, 29)},  # naïf
])
def test_invalid_sessions_are_refused(kwargs):
    base = {"jarvis_session_id": "jsess_1", "started_at": T0, "active_board_id": "default",
            "visited_board_ids": ("default",)}
    with pytest.raises(BoardError) as exc:
        JarvisSession(**{**base, **kwargs})
    assert code_of(exc) == "invalid_session"


# ---------------------------------------------------------------- liaisons


def _two_bindings(a: Board, b: Board):
    session = visit_board(open_session(a, now=T0), b)
    ba = new_binding(session, a, conversation_id="conv-a", agent_cli="claude", now=T0)
    bb = new_binding(session, b, conversation_id="conv-b", agent_cli="claude", now=T0, existing=[ba])
    return session, (ba, bb)


def test_a_b_a_returns_the_same_binding(boards):
    a, b = boards
    session, bindings = _two_bindings(a, b)
    assert find_binding(bindings, session.jarvis_session_id, a.board_id).conversation_id == "conv-a"
    with pytest.raises(BoardError) as exc:
        new_binding(session, a, conversation_id="conv-a2", agent_cli="claude", now=t(1), existing=bindings)
    assert code_of(exc) == "binding_conflict"


def test_exactly_one_foreground_per_session(boards):
    a, b = boards
    _, (ba, bb) = _two_bindings(a, b)
    step1 = promote_binding((ba, bb), ba, now=t(1))
    assert [x.lifecycle for x in step1] == [BrainLifecycle.FOREGROUND, BrainLifecycle.SUSPENDED]
    step2 = promote_binding(step1, step1[1], now=t(2), demote_to=BrainLifecycle.BACKGROUND_RUNNING)
    assert [x.lifecycle for x in step2] == [BrainLifecycle.BACKGROUND_RUNNING, BrainLifecycle.FOREGROUND]
    assert step2[1].last_active_at == t(2)
    two_fg = (replace_lifecycle(ba, BrainLifecycle.FOREGROUND), replace_lifecycle(bb, BrainLifecycle.FOREGROUND))
    with pytest.raises(BoardError) as exc:
        check_bindings(two_fg)
    assert code_of(exc) == "binding_conflict"
    with pytest.raises(BoardError) as exc:
        set_lifecycle(ba, BrainLifecycle.FOREGROUND, now=t(3))
    assert code_of(exc) == "invalid_binding"


def replace_lifecycle(binding: BoardConversationBinding, lifecycle: BrainLifecycle) -> BoardConversationBinding:
    return dataclasses.replace(binding, lifecycle=lifecycle)


def test_closed_binding_never_becomes_foreground_but_may_finish_background_work(boards):
    a, b = boards
    _, (ba, bb) = _two_bindings(a, b)
    closed = close_binding(ba, now=t(1), lifecycle=BrainLifecycle.BACKGROUND_RUNNING)
    assert closed.status is BindingStatus.CLOSED
    assert set_lifecycle(closed, BrainLifecycle.SUSPENDED, now=t(2)).lifecycle is BrainLifecycle.SUSPENDED
    with pytest.raises(BoardError) as exc:
        promote_binding((closed, bb), closed, now=t(2))
    assert code_of(exc) == "session_closed"
    with pytest.raises(BoardError) as exc:
        promote_binding((bb,), ba, now=t(2))
    assert code_of(exc) == "binding_not_found"
    with pytest.raises(BoardError) as exc:
        dataclasses.replace(closed, lifecycle=BrainLifecycle.FOREGROUND)
    assert code_of(exc) == "invalid_binding"


def test_agent_session_id_is_recorded(boards):
    a, b = boards
    _, (ba, _) = _two_bindings(a, b)
    assert ba.agent_session_id is None
    assert record_agent_session(ba, "claude-sess-1", now=t(1)).agent_session_id == "claude-sess-1"


# ---------------------------------------------------------------- sérialisation


def test_payload_round_trip(boards):
    a, b = boards
    board = update_board(
        set_interaction_mode(b, InteractionMode.PRESENTATION, now=t(1)), now=t(2),
        context_summary="Résumé\nsur deux lignes", task_refs=["t1"], artifact_refs=["docs/x.md"],
        project_refs=["p1"], scene_ref=SceneRef(scene_id="scene-1", revision_at_leave=7),
        runtime_metadata={"agent_cli": "claude", "count": 2, "flag": True, "none": None},
    )
    board = mark_opened(board, now=t(3))
    assert Board.from_payload(board.to_payload()) == board
    session = close_session(visit_board(open_session(a, now=T0), b), reason=SessionEndReason.CORE_RESTART, now=t(4))
    assert JarvisSession.from_payload(session.to_payload()) == session
    _, (ba, _) = _two_bindings(a, b)
    ba = record_agent_session(ba, "sid", now=t(1))
    assert BoardConversationBinding.from_payload(ba.to_payload()) == ba
    import json
    assert Board.from_payload(json.loads(json.dumps(board.to_payload()))) == board


@pytest.mark.parametrize("mutate, code", [
    (lambda p: p.update(extra=1), "invalid_board"),
    (lambda p: p.pop("title"), "invalid_board"),
    (lambda p: p.update(status="deleted"), "invalid_board"),
    (lambda p: p.update(created_at="yesterday"), "invalid_board"),
    (lambda p: p.update(created_at="2026-09-29T10:00:00"), "invalid_board"),  # naïf
    (lambda p: p.update(task_refs="t1"), "invalid_board"),
    (lambda p: p.update(interaction_mode="SIMPLE"), "invalid_board"),
    (lambda p: p.update(scene_ref={"kind": "board", "scene_id": "s"}), "invalid_board"),
    (lambda p: p.update(board_id="nope"), "invalid_board"),
    (lambda p: p.update(title=""), "invalid_title"),
])
def test_board_payload_validation_rejects(boards, mutate, code):
    payload = boards[1].to_payload()
    mutate(payload)
    with pytest.raises(BoardError) as exc:
        Board.from_payload(payload)
    assert code_of(exc) == code


@pytest.mark.parametrize("cls, payload", [
    (JarvisSession, None),
    (JarvisSession, {"jarvis_session_id": "jsess_1"}),
    (BoardConversationBinding, []),
    (BoardConversationBinding, {"jarvis_session_id": "jsess_1", "board_id": "default"}),
])
def test_non_object_or_incomplete_payloads_are_refused(cls, payload):
    with pytest.raises(BoardError):
        cls.from_payload(payload)


# ---------------------------------------------------------------- pureté


def test_domain_and_port_modules_import_no_io():
    forbidden = {"sqlite3", "aiohttp", "httpx", "requests", "os", "pathlib", "subprocess", "jarvis.runtime",
                 "jarvis.adapters", "jarvis.core"}
    for rel in ("jarvis/domain/workspace_board.py", "jarvis/ports/workspace_board.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        assert not {n for n in names if any(n == f or n.startswith(f + ".") for f in forbidden)}, rel
