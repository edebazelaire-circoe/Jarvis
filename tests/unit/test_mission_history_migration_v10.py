"""Migration v10 de `jarvis.sqlite3` : historique durable des missions (organic-agent-orchestration, Slice 03).

Additive (DDL seul, aucune ligne produit). La base v9 de départ est construite
depuis l'instantané figé `tests/schema/jarvis_state.v9.sql` (et vérifiée égale
à celle du code v9), dans un dossier temporaire : jamais une base réelle.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters import sqlite_state
from jarvis.adapters.sqlite_state import SQLiteStateRepository

SNAPSHOTS = Path(__file__).resolve().parents[1] / "schema"
V10_TABLES = ("missions", "agent_instances", "mission_owners", "agent_relations", "agent_relation_participants",
              "agent_handoff_packets", "agent_relation_messages")
T = "2026-10-02T22:59:06.219733+00:00"


def _snapshot_statements(version: int) -> list[str]:
    """Le DDL d'un instantané, tables d'abord (l'instantané est trié par type puis nom)."""

    text = (SNAPSHOTS / f"jarvis_state.v{version}.sql").read_text(encoding="utf-8")
    blocks: list[tuple[str, str]] = []
    kind = None
    for line in text.splitlines():
        if line.startswith("-- schema_version"):
            continue
        if line.startswith("-- "):
            kind = line.split()[1]
            continue
        if line.strip():
            blocks.append((kind or "", line))
    order = {"table": 0, "index": 1, "trigger": 2, "view": 3}
    return [sql for kind, sql in sorted(blocks, key=lambda block: order.get(block[0], 9))]


def _schema(path: Path) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                            "ORDER BY type, name").fetchall()
    finally:
        conn.close()


def _normal(schema: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    return [(kind, name, " ".join((sql or "").split())) for kind, name, sql in schema]


async def _open(path: Path) -> SQLiteStateRepository:
    repository = SQLiteStateRepository(path)
    await repository.initialize()
    return repository


def _build_v9_from_snapshot(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        for statement in _snapshot_statements(9):
            conn.execute(statement.rstrip(";"))
        conn.execute("INSERT INTO schema_version(version) VALUES (9)")
        conn.execute("INSERT INTO devices(id, data) VALUES ('dev-v9', '{\"name\": \"poste\"}')")
        conn.execute("INSERT INTO work_boards(board_id, status, created_at, updated_at, data) VALUES (?,?,?,?,?)",
                     ("board-v9", "active", T, T, '{"board_id": "board-v9", "board_kind": "assistant"}'))
        conn.commit()
    finally:
        conn.close()


def test_the_v9_snapshot_is_the_schema_the_v9_code_builds(tmp_path, monkeypatch):
    built = tmp_path / "code" / "jarvis.sqlite3"
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_state, "_SCHEMA_VERSION", 9)
        asyncio.run(_close(_open(built)))
    snap = tmp_path / "snap" / "jarvis.sqlite3"
    _build_v9_from_snapshot(snap)
    assert _normal(_schema(snap)) == _normal(_schema(built))


async def _close(opening) -> None:
    repository = await opening
    await repository.close()


def test_a_v9_file_migrates_to_v10_after_a_backup_and_keeps_its_rows(tmp_path):
    old = tmp_path / "old" / "jarvis.sqlite3"
    _build_v9_from_snapshot(old)

    repository = asyncio.run(_open(old))
    assert repository.migrations_applied == [{"from": 9, "to": 10, "rows": 0}]
    asyncio.run(repository.close())

    fresh = tmp_path / "fresh" / "jarvis.sqlite3"
    asyncio.run(_close(_open(fresh)))
    assert _normal(_schema(old)) == _normal(_schema(fresh))

    conn = sqlite3.connect(old)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(10,)]
        assert conn.execute("SELECT id, data FROM devices").fetchall() == [("dev-v9", '{"name": "poste"}')]
        assert conn.execute("SELECT board_id FROM work_boards").fetchall() == [("board-v9",)]
        for table in V10_TABLES:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table  # no product row
    finally:
        conn.close()

    backup = old.parent / "jarvis.sqlite3.v9.bak"
    assert backup.exists()
    conn = sqlite3.connect(backup)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(9,)]
        assert conn.execute("SELECT id FROM devices").fetchall() == [("dev-v9",)]
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(V10_TABLES)
    finally:
        conn.close()

    # Déjà à jour : rien ne se rejoue, la sauvegarde n'est pas réécrite.
    stamp = backup.stat().st_mtime_ns
    repository = asyncio.run(_open(old))
    assert repository.migrations_applied == []
    asyncio.run(repository.close())
    assert backup.stat().st_mtime_ns == stamp


def test_a_failed_v10_step_rolls_back_and_leaves_v9_intact(tmp_path, monkeypatch):
    """Une transaction par étape : un DDL qui échoue au milieu ne laisse ni table partielle ni version 10."""

    path = tmp_path / "jarvis.sqlite3"
    _build_v9_from_snapshot(path)
    broken = (*sqlite_state._MIGRATIONS[10][:3], "CREATE TABLE devices (id TEXT)")  # `devices` exists: fails
    monkeypatch.setitem(sqlite_state._MIGRATIONS, 10, broken)
    with pytest.raises(RuntimeError, match="table devices already exists"):
        asyncio.run(_open(path))
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(9,)]
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='missions'").fetchone()[0] == 0
        assert conn.execute("SELECT id FROM devices").fetchall() == [("dev-v9",)]
    finally:
        conn.close()
    monkeypatch.undo()
    asyncio.run(_close(_open(path)))  # le démarrage suivant rejoue l'étape entière
    assert {"missions", "agent_instances"} <= {row[1] for row in _schema(path)}


def test_v10_carries_no_execution_status_column(tmp_path):
    """D16 : aucun statut d'exécution dans l'historique ; `status` n'existe que pour missions et relations."""

    path = tmp_path / "jarvis.sqlite3"
    asyncio.run(_close(_open(path)))
    conn = sqlite3.connect(path)
    try:
        for table in V10_TABLES:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert not columns & {"work_status", "progress", "progress_fraction", "activity", "ended_at",
                                  "error_class", "prompt", "trace", "reasoning"}, table
            if table not in ("missions", "agent_relations"):
                assert "status" not in columns, table
    finally:
        conn.close()
