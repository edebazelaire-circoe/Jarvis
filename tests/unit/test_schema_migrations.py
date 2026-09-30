"""Règle du dépôt : tout changement de schéma SQLite passe par une migration versionnée.

Chaque PC a ses propres bases (voir `CLAUDE.md`, « Données locales ») : un
fichier existant ne sera jamais recréé depuis le code, il ne peut évoluer que
par les migrations appliquées au démarrage. Ces tests le rendent vérifiable :

- le schéma d'une base neuve, à la version courante, est figé dans
  `tests/schema/<base>.v<version>.sql`. Toucher au DDL sans incrémenter la
  version et sans ajouter une migration fait échouer ce test ;
- une base créée à une version plus ancienne puis migrée aboutit exactement
  au même schéma qu'une base neuve ;
- chaque version a sa migration, et la migration sauvegarde la base d'abord.

Pour changer un schéma : ajouter l'étape dans `_MIGRATIONS` (même fichier que
le schéma), incrémenter `_SCHEMA_VERSION`, puis régénérer le fichier figé avec
`JARVIS_WRITE_SCHEMA_SNAPSHOT=1 pytest tests/unit/test_schema_migrations.py`.
Les fichiers figés des versions passées ne se modifient jamais.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters import sqlite_scene, sqlite_state
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository

SNAPSHOTS = Path(__file__).resolve().parents[1] / "schema"


def schema_of(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        version = conn.execute("SELECT version FROM schema_version").fetchall()
    finally:
        conn.close()
    lines = [f"-- schema_version = {version}"]
    for kind, name, table, sql in rows:
        body = " ".join((sql or "").split())
        lines.append(f"-- {kind} {name} ON {table}\n{body};")
    return "\n".join(lines) + "\n"


def check_snapshot(name: str, version: int, actual: str) -> None:
    snapshot = SNAPSHOTS / f"{name}.v{version}.sql"
    if os.getenv("JARVIS_WRITE_SCHEMA_SNAPSHOT") == "1" and not snapshot.exists():
        snapshot.write_text(actual, encoding="utf-8", newline="\n")
    assert snapshot.exists(), (
        f"{snapshot.name} manquant : un schéma à la version {version} sans fichier figé. "
        "Ajoutez la migration, puis JARVIS_WRITE_SCHEMA_SNAPSHOT=1 pour écrire le fichier."
    )
    assert snapshot.read_text(encoding="utf-8") == actual, (
        f"Le schéma de {name} a changé sans nouvelle version : ajoutez une étape à _MIGRATIONS "
        f"et incrémentez _SCHEMA_VERSION (actuellement {version}) au lieu de modifier le DDL existant."
    )


async def fresh_state(path: Path) -> None:
    repository = SQLiteStateRepository(path)
    await repository.initialize()
    await repository.close()


async def fresh_scene(path: Path) -> None:
    repository = SQLiteSceneRepository(path)
    await repository.initialize()
    await repository.close()


def test_every_state_version_has_its_migration_step():
    assert sorted(sqlite_state._MIGRATIONS) == list(range(2, sqlite_state._SCHEMA_VERSION + 1))


def test_every_scene_version_has_its_migration_step():
    assert sorted(sqlite_scene._MIGRATIONS) == list(range(2, sqlite_scene._SCHEMA_VERSION + 1))


def test_state_schema_matches_its_frozen_snapshot(tmp_path):
    path = tmp_path / "jarvis.sqlite3"
    asyncio.run(fresh_state(path))
    check_snapshot("jarvis_state", sqlite_state._SCHEMA_VERSION, schema_of(path))


def test_scene_schema_matches_its_frozen_snapshot(tmp_path):
    path = tmp_path / "scene.sqlite3"
    asyncio.run(fresh_scene(path))
    check_snapshot("scene", sqlite_scene._SCHEMA_VERSION, schema_of(path))


def test_every_frozen_snapshot_is_kept():
    for name, current in (("jarvis_state", sqlite_state._SCHEMA_VERSION), ("scene", sqlite_scene._SCHEMA_VERSION)):
        assert (SNAPSHOTS / f"{name}.v{current}.sql").exists(), name


def test_a_v1_state_file_migrates_to_the_fresh_schema_after_a_backup(tmp_path, monkeypatch):
    old = tmp_path / "old" / "jarvis.sqlite3"
    monkeypatch.setattr(sqlite_state, "_SCHEMA_VERSION", 1)
    asyncio.run(fresh_state(old))
    monkeypatch.undo()
    asyncio.run(fresh_state(old))
    fresh = tmp_path / "fresh" / "jarvis.sqlite3"
    asyncio.run(fresh_state(fresh))
    assert schema_of(old) == schema_of(fresh)
    assert (old.parent / "jarvis.sqlite3.v1.bak").exists()


def test_a_scene_migration_step_runs_once_after_a_backup_and_keeps_the_data(tmp_path, monkeypatch):
    """Le mécanisme de la scène, exercé par une migration d'essai (il n'y en a pas encore de vraie)."""

    path = tmp_path / "scene.sqlite3"
    asyncio.run(fresh_scene(path))
    conn = sqlite3.connect(path)
    scene_id = conn.execute("SELECT scene_id FROM scene_meta").fetchone()[0]
    conn.close()
    monkeypatch.setattr(sqlite_scene, "_SCHEMA_VERSION", 2)
    monkeypatch.setattr(sqlite_scene, "_MIGRATIONS", {2: ("CREATE TABLE scene_probe_v2 (id INTEGER)",)})
    asyncio.run(fresh_scene(path))
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(2,)]
        assert conn.execute("SELECT scene_id FROM scene_meta").fetchone()[0] == scene_id
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name = 'scene_probe_v2'").fetchone()[0] == 1
    finally:
        conn.close()
    backup = tmp_path / "scene.sqlite3.v1.bak"
    assert backup.exists()
    conn = sqlite3.connect(backup)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(1,)]
    finally:
        conn.close()
    asyncio.run(fresh_scene(path))  # déjà à jour : rien ne se rejoue
    fresh = tmp_path / "fresh" / "scene.sqlite3"
    asyncio.run(fresh_scene(fresh))
    assert schema_of(path) == schema_of(fresh)
