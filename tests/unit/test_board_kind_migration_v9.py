"""Migration v9 de `jarvis.sqlite3` : type de Board fixé (handoff board-ui-wheel-dossier-refactor, Slice 01a).

Données seules (aucun DDL) : `board_kind` devient `assistant|presentation|meeting`
et les clés de mode par Board (`interaction_mode`, `interaction_mode_origin`)
quittent le payload. Règles D22 (`docs/boards.md` › *Persistence*) :

1. un type explicite `presentation` / `meeting` gagne, même sur un mode
   `assistant` choisi (décision humaine Q1) ;
2. `empty` ou absent + mode `presentation` / `meeting` choisi (origine `user`
   ou `migrated`) : ce mode devient le type, une fois ;
3. sinon : `assistant` (un Board `unset` se comportait déjà en assistant).

Base temporaire uniquement, construite par le code v8 lui-même (`_SCHEMA_VERSION`
ramené à 8), jamais une base réelle.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters import sqlite_state
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.domain.workspace_board import BoardKind, BoardStatus

T = "2026-10-02T22:59:06.219733+00:00"

#: (board_id, payload v8 : type, mode, origine ; None = clé absente) -> type attendu en v9.
MATRIX: list[tuple[str, str | None, str | None, str | None, str]] = [
    # Règle 1 : un type explicite gagne (Q1 : « Jarvis PRESENTATION », mode assistant choisi).
    ("board_p_user_assistant", "presentation", "assistant", "user", "presentation"),
    ("board_p_unset", "presentation", "assistant", "unset", "presentation"),
    ("board_m_user_presentation", "meeting", "presentation", "user", "meeting"),
    ("board_m_migrated_assistant", "meeting", "assistant", "migrated", "meeting"),
    # Règle 2 : `empty` + Présentation / Réunion choisie (user ou migrated) : le mode sème le type.
    ("board_e_user_presentation", "empty", "presentation", "user", "presentation"),
    ("board_e_migrated_presentation", "empty", "presentation", "migrated", "presentation"),
    ("board_e_user_meeting", "empty", "meeting", "user", "meeting"),
    ("board_e_migrated_meeting", "empty", "meeting", "migrated", "meeting"),
    # Règle 3 : sinon Assistant ; un Board `unset` ignore tout mode (et le réglage global).
    ("board_e_unset_presentation", "empty", "presentation", "unset", "assistant"),
    ("board_e_unset_meeting", "empty", "meeting", "unset", "assistant"),
    ("board_e_user_assistant", "empty", "assistant", "user", "assistant"),
    ("default", "empty", "assistant", "unset", "assistant"),
    # Type absent (Board écrit avant `board_kind`, v3..v7) : comme `empty`.
    ("board_absent_user_presentation", None, "presentation", "user", "presentation"),
    ("board_absent_unset", None, "assistant", "unset", "assistant"),
    ("board_absent_no_mode", None, None, None, "assistant"),
    # Mode choisi sans origine (forme impossible en v8) : pas un choix, Assistant.
    ("board_e_presentation_no_origin", "empty", "presentation", None, "assistant"),
]


def _payload(board_id: str, kind: str | None, mode: str | None, origin: str | None, *,
             status: str = "active") -> dict:
    """La forme exacte de `Board.to_payload()` en v8 (avec les clés de mode), clés optionnelles retirées."""

    data = {"artifact_refs": [], "board_id": board_id, "context_summary": f"résumé {board_id}", "created_at": T,
            "last_opened_at": None, "project_refs": ["p1"], "runtime_metadata": {"k": "v"}, "scene_ref": None,
            "status": status, "task_refs": ["t1"], "title": f"Titre {board_id}", "updated_at": T,
            "board_kind": kind, "interaction_mode": mode, "interaction_mode_origin": origin}
    return {key: value for key, value in data.items()
            if not (key in {"board_kind", "interaction_mode", "interaction_mode_origin"} and value is None)}


def _insert(conn: sqlite3.Connection, board_id: str, data: str, status: str = "active") -> None:
    conn.execute("INSERT INTO work_boards(board_id, status, created_at, updated_at, data) VALUES (?,?,?,?,?)",
                 (board_id, status, T, T, data))


async def _open(path: Path) -> None:
    repository = SQLiteStateRepository(path)
    await repository.initialize()
    await repository.close()


def _v8_file(path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str, str]]) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_state, "_SCHEMA_VERSION", 8)
        asyncio.run(_open(path))
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(8,)]
        for board_id, data, status in rows:
            _insert(conn, board_id, data, status)
        conn.commit()
    finally:
        conn.close()


def _other_fields(data: dict) -> dict:
    return {key: value for key, value in data.items()
            if key not in {"board_kind", "interaction_mode", "interaction_mode_origin"}}


def _rows(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute("SELECT board_id, data FROM work_boards"))
    finally:
        conn.close()


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    path = tmp_path / "state" / "jarvis.sqlite3"
    rows = [(board_id, json.dumps(_payload(board_id, kind, mode, origin), sort_keys=True), "active")
            for board_id, kind, mode, origin, _ in MATRIX]
    rows.append(("board_archived_presentation",
                 json.dumps(_payload("board_archived_presentation", "empty", "presentation", "user",
                                     status="archived"), sort_keys=True), "archived"))
    _v8_file(path, monkeypatch, rows)
    before = _rows(path)
    asyncio.run(_open(path))
    return path, before


def test_every_legacy_payload_gets_its_fixed_type_and_loses_its_mode_keys(migrated):
    path, before = migrated
    after = _rows(path)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(9,)]
    finally:
        conn.close()
    for board_id, _, _, _, expected in MATRIX:
        data = json.loads(after[board_id])
        assert data["board_kind"] == expected, board_id
        assert "interaction_mode" not in data and "interaction_mode_origin" not in data, board_id
        # Rien d'autre ne bouge : mêmes champs, mêmes valeurs.
        assert _other_fields(data) == _other_fields(json.loads(before[board_id])), board_id
    archived = json.loads(after["board_archived_presentation"])
    assert (archived["board_kind"], archived["status"]) == ("presentation", "archived")


def test_the_migrated_boards_decode_strictly_with_the_v9_code(migrated):
    path, _ = migrated

    async def read() -> dict[str, tuple[BoardKind, BoardStatus]]:
        state = SQLiteStateRepository(path)
        await state.initialize()
        try:
            boards = await SQLiteBoardRepository(state).list_boards(include_archived=True)
        finally:
            await state.close()
        return {board.board_id: (board.board_kind, board.status) for board in boards}

    decoded = asyncio.run(read())
    assert {board_id: kind.value for board_id, (kind, _) in decoded.items()} == {
        **{board_id: expected for board_id, _, _, _, expected in MATRIX},
        "board_archived_presentation": "presentation"}
    assert decoded["board_archived_presentation"][1] is BoardStatus.ARCHIVED


def test_the_migration_backs_the_v8_file_up_first_and_the_backup_keeps_the_legacy_payloads(migrated):
    path, before = migrated
    backup = path.with_name("jarvis.sqlite3.v8.bak")
    assert backup.is_file()
    conn = sqlite3.connect(backup)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(8,)]
        assert dict(conn.execute("SELECT board_id, data FROM work_boards")) == before
    finally:
        conn.close()


def test_the_migration_is_idempotent(migrated):
    path, _ = migrated
    first = _rows(path)
    asyncio.run(_open(path))  # second démarrage : la version garde l'étape, rien ne se rejoue
    assert _rows(path) == first
    # Même l'instruction rejouée à la main sur la base migrée ne change rien.
    conn = sqlite3.connect(path)
    try:
        for statement in sqlite_state._MIGRATIONS[9]:
            assert conn.execute(statement).rowcount == 0
        conn.commit()
    finally:
        conn.close()
    assert _rows(path) == first
    assert sorted(p.name for p in path.parent.glob("*.bak")) == ["jarvis.sqlite3.v8.bak"]


def test_a_damaged_or_out_of_contract_row_is_left_as_is_never_repaired(tmp_path, monkeypatch):
    path = tmp_path / "jarvis.sqlite3"
    weird_kind = json.dumps(_payload("board_weird", "workshop", "presentation", "user"), sort_keys=True)
    null_kind = json.dumps({**_payload("board_null", None, "presentation", "user"), "board_kind": None})
    rows = [("board_broken", "{not json", "active"), ("board_weird", weird_kind, "active"),
            ("board_null", null_kind, "active"),
            ("board_ok", json.dumps(_payload("board_ok", "empty", "meeting", "user")), "active")]
    _v8_file(path, monkeypatch, rows)
    asyncio.run(_open(path))  # ne lève pas : la migration ne lit que les payloads valides
    after = _rows(path)
    assert after["board_broken"] == "{not json"
    assert after["board_weird"] == weird_kind and after["board_null"] == null_kind
    assert json.loads(after["board_ok"])["board_kind"] == "meeting"


def test_the_real_data_shape_of_this_pc_migrates_as_decided(tmp_path, monkeypatch):
    """Les 3 Boards relevés par la Slice 00 (copie de la base réelle, LOG Slice 00) ; Q1 : règle 1."""

    path = tmp_path / "jarvis.sqlite3"
    rows = [("default", json.dumps(_payload("default", "empty", "assistant", "user")), "active"),
            ("board_monq", json.dumps(_payload("board_monq", "empty", "assistant", "unset", status="archived")),
             "archived"),
            ("board_pres", json.dumps(_payload("board_pres", "presentation", "assistant", "user")), "active")]
    _v8_file(path, monkeypatch, rows)
    asyncio.run(_open(path))
    kinds = {board_id: json.loads(data)["board_kind"] for board_id, data in _rows(path).items()}
    assert kinds == {"default": "assistant", "board_monq": "assistant", "board_pres": "presentation"}


def test_a_v8_binary_refuses_the_v9_file_instead_of_misreading_it(tmp_path, monkeypatch):
    path = tmp_path / "jarvis.sqlite3"
    asyncio.run(_open(path))
    monkeypatch.setattr(sqlite_state, "_SCHEMA_VERSION", 8)
    with pytest.raises(RuntimeError, match="newer than supported"):
        asyncio.run(_open(path))
