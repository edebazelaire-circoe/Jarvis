"""Contrat pur `board_kind` + mémoire de Board (handoff board-memory-workspace-inspector, Slice 01).

Domaine pur : aucun disque, aucune base. Voir `docs/boards.md` › *Board kind*
et *Board memory*.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import pytest

from jarvis.domain.board_memory import (
    BOARDS_DIR, MAX_MEMORY_IO_BYTES, MAX_MEMORY_PATH_CHARS, MEMORY_DIR, MEMORY_HTTP_STATUS, MEMORY_SUMMARY_NAME,
    BoardMemoryError, BoardMemoryErrorCode, BoardMemoryPath, board_memory_root,
)
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.session_activity import ActivityDraft, ActivityKind
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_KIND, Board, BoardError, BoardKind, InteractionModeOrigin, archive_board, create_board,
    default_board, set_interaction_mode, update_board,
)

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
HEX = "0123456789abcdef0123456789abcdef"


def t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


# ---------------------------------------------------------------- board_kind


def test_board_kind_is_a_closed_set_with_empty_by_default():
    assert [k.value for k in BoardKind] == ["empty", "meeting", "presentation"]
    assert DEFAULT_BOARD_KIND is BoardKind.EMPTY
    assert create_board("B", now=T0).board_kind is BoardKind.EMPTY
    assert default_board(now=T0).board_kind is BoardKind.EMPTY


def test_board_kind_round_trips_through_the_payload():
    board = update_board(create_board("B", now=T0), now=t(1), board_kind=BoardKind.MEETING)
    payload = board.to_payload()
    assert payload["board_kind"] == "meeting"
    assert Board.from_payload(payload) == board


def test_a_payload_written_before_board_kind_decodes_as_empty():
    payload = create_board("Ancien", now=T0).to_payload()
    del payload["board_kind"]
    assert Board.from_payload(payload).board_kind is BoardKind.EMPTY


@pytest.mark.parametrize("raw", ["Meeting", "réunion", "", None, 1, ["meeting"]])
def test_an_unknown_board_kind_is_refused_on_decode(raw):
    payload = {**create_board("B", now=T0).to_payload(), "board_kind": raw}
    with pytest.raises(BoardError) as exc:
        Board.from_payload(payload)
    assert exc.value.code == "invalid_board"


def test_board_kind_must_be_the_enum_on_the_value():
    with pytest.raises(BoardError) as exc:
        Board(board_id="board_x", title="B", created_at=T0, updated_at=T0, board_kind="meeting")  # type: ignore[arg-type]
    assert exc.value.code == "invalid_board"


def test_changing_board_kind_never_touches_the_interaction_mode():
    board = set_interaction_mode(create_board("B", now=T0), InteractionMode.ASSISTANT, now=t(1))
    for kind in (BoardKind.PRESENTATION, BoardKind.MEETING, BoardKind.EMPTY):
        changed = update_board(board, now=t(2), board_kind=kind)
        assert changed.board_kind is kind
        assert (changed.interaction_mode, changed.interaction_mode_origin) == (
            InteractionMode.ASSISTANT, InteractionModeOrigin.USER)
    # Et l'inverse : changer le mode ne change pas la nature.
    meeting = update_board(create_board("R", now=T0), now=t(1), board_kind=BoardKind.MEETING)
    assert set_interaction_mode(meeting, InteractionMode.PRESENTATION, now=t(2)).board_kind is BoardKind.MEETING


def test_update_without_board_kind_keeps_it_and_archived_board_refuses_it():
    board = update_board(create_board("B", now=T0), now=t(1), board_kind=BoardKind.PRESENTATION)
    assert update_board(board, now=t(2), title="B2").board_kind is BoardKind.PRESENTATION
    archived = archive_board(board, active_board_id=None, now=t(3))
    with pytest.raises(BoardError) as exc:
        update_board(archived, now=t(4), board_kind=BoardKind.EMPTY)
    assert exc.value.code == "board_archived"


# ---------------------------------------------------------------- emplacement


def test_memory_root_is_relative_and_derived_from_the_board_id_only():
    assert board_memory_root(f"board_{HEX}") == PurePosixPath(BOARDS_DIR, f"board_{HEX}", MEMORY_DIR)
    assert board_memory_root("default").as_posix() == "boards/default/memory"
    assert not board_memory_root("default").is_absolute()


@pytest.mark.parametrize("board_id", [
    "", "board_", "x", "board_../x", "board_a/b", "board_A", "board_a b", "../default", "C:/x", None, 3,
    "board_" + "a" * 200,
])
def test_memory_root_refuses_an_unsafe_board_id(board_id):
    with pytest.raises(BoardError) as exc:
        board_memory_root(board_id)  # type: ignore[arg-type]
    assert exc.value.code == "invalid_board"


def test_memory_path_locator_joins_under_the_root():
    path = BoardMemoryPath.parse("notes/réunion 2026.md")
    assert path.locator("default").as_posix() == "boards/default/memory/notes/réunion 2026.md"
    assert path.parts == ("notes", "réunion 2026.md") and path.name == "réunion 2026.md"
    assert path.parent == BoardMemoryPath("notes") and BoardMemoryPath("notes").parent is None
    assert str(path) == "notes/réunion 2026.md"
    assert BoardMemoryPath(MEMORY_SUMMARY_NAME).is_summary and not path.is_summary


@pytest.mark.parametrize("raw, expected", [
    ("summary.md", True), ("Summary.md", True), ("SUMMARY.MD", True),
    ("notes/summary.md", False), ("summary.md.bak", False), ("summary", False),
])
def test_summary_is_recognised_at_the_root_whatever_the_case(raw, expected):
    assert BoardMemoryPath.parse(raw).is_summary is expected


# ---------------------------------------------------------------- chemin


@pytest.mark.parametrize("raw", [
    "summary.md", "a/b/c.txt", "Notes", ".hidden", "a.b.c", "con_notes.md", "console.md", "com10.txt", "café/è.md",
    "a" * MAX_MEMORY_PATH_CHARS, "notes~draft.md", "~tmp", "a~b1.md", "notes~1draft.md", "a~1.tar.gz", "com0.txt",
    "auxiliary.tar.gz",
])
def test_valid_memory_paths_are_accepted(raw):
    assert BoardMemoryPath.parse(raw).value == raw


@pytest.mark.parametrize("raw", [
    "/etc/passwd", "\\\\server\\share", "\\x", "C:/x", "c:x", "a:b", "..", "../x", "a/../b", "a/..", "..\\x",
    "a\\..\\b",
])
def test_paths_leaving_the_memory_are_memory_path_escape(raw):
    with pytest.raises(BoardMemoryError) as exc:
        BoardMemoryPath.parse(raw)
    assert exc.value.code is BoardMemoryErrorCode.MEMORY_PATH_ESCAPE and exc.value.status == 400


@pytest.mark.parametrize("raw", [
    "", ".", "./a", "a/./b", "a//b", "a/", "a\\b", "a\x00b", "a\nb", "a\tb", "x/a:b", "ab:c", "a*b", "a?b", "a|b", 'a"b',
    "a<b", "a>b", "CON", "nul.txt", "Aux.md", "com1", "LPT9.log", "dir/prn", " a", "a ", "a.", "a/b.",
    "a" * (MAX_MEMORY_PATH_CHARS + 1), None, 3, b"a",
    # `.` et `:` seuls ou en segment.
    ":", ":a", "a/:", "a/.", "./", ".:",
    # Nom réservé coupé au **premier** point : `aux.tar.gz` ouvre encore le périphérique.
    "aux.tar.gz", "nul.a.b", "dir/CON.tar.gz",
    # Chiffres en exposant : Windows les réserve aussi.
    "COM¹", "LPT³", "com².txt", "Lpt¹.log.txt",
    # Noms courts 8.3 : alias NTFS d'un nom long.
    "PROGRA~1", "SUMMAR~1.MD", "VERYLO~1.MD", "a~12.txt", "dir/NOTES~2/x.md", "~1",
])
def test_malformed_paths_are_memory_path_invalid(raw):
    with pytest.raises(BoardMemoryError) as exc:
        BoardMemoryPath.parse(raw)
    assert exc.value.code is BoardMemoryErrorCode.MEMORY_PATH_INVALID and exc.value.status == 400


def test_memory_path_is_immutable():
    path = BoardMemoryPath("a.md")
    with pytest.raises(AttributeError):
        path.value = "b.md"  # type: ignore[misc]


# ---------------------------------------------------------------- erreurs et limites


def test_memory_error_codes_are_stable_and_mapped_to_http():
    assert {c.value: MEMORY_HTTP_STATUS[c] for c in BoardMemoryErrorCode} == {
        "memory_path_invalid": 400, "memory_path_escape": 400, "memory_not_found": 404, "memory_exists": 409,
        "memory_conflict": 409, "memory_too_large": 413, "memory_not_text": 415,
    }
    err = BoardMemoryError(BoardMemoryErrorCode.MEMORY_CONFLICT, "x")
    assert isinstance(err, ValueError) and err.code == "memory_conflict" and err.status == 409
    assert (MAX_MEMORY_PATH_CHARS, MAX_MEMORY_IO_BYTES) == (240, 256 * 1024)


# ---------------------------------------------------------------- ledger


def test_board_activity_kinds_exist_and_need_no_session():
    kinds = {ActivityKind.BOARD_MEMORY_WRITTEN: "board.memory.written",
             ActivityKind.BOARD_MEMORY_MOVED: "board.memory.moved",
             ActivityKind.BOARD_MEMORY_DELETED: "board.memory.deleted",
             ActivityKind.BOARD_ARTIFACT_LINKED: "board.artifact.linked",
             ActivityKind.BOARD_ARTIFACT_UNLINKED: "board.artifact.unlinked"}
    for kind, value in kinds.items():
        assert kind.value == value and kind.family == "board"
        draft = ActivityDraft(kind=kind, occurred_at=T0, data={"board_id": "default", "path": "summary.md"})
        assert draft.to_payload()["kind"] == value


# ---------------------------------------------------------------- pureté


def test_board_memory_module_is_pure():
    forbidden = {"sqlite3", "aiohttp", "httpx", "requests", "os", "shutil", "io", "subprocess", "jarvis.runtime",
                 "jarvis.adapters", "jarvis.core", "jarvis.protocol"}
    tree = ast.parse((ROOT / "jarvis/domain/board_memory.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            if node.module == "pathlib":
                # Chemins purs seulement : jamais `Path`, qui toucherait le disque.
                assert {a.name for a in node.names} == {"PurePosixPath"}
    assert not {n for n in names if any(n == f or n.startswith(f + ".") for f in forbidden)}
