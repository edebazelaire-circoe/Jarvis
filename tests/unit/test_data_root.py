"""Données locales hors du dépôt (`jarvis/data_root.py`, `docs/local-data.md`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from jarvis import data_root
from jarvis.data_root import LegacyAdoptionError, adopt_legacy_data, resolve_data_root


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root: Path) -> dict[str, str]:
    """Empreinte de chaque fichier, sauf les `-shm` : index de mémoire partagée où tout lecteur SQLite note sa place."""

    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*"))
            if p.is_file() and not p.name.endswith("-shm")}


def wal_database(path: Path, rows: int) -> sqlite3.Connection:
    """Base WAL dont les dernières lignes ne sont que dans le -wal (connexion laissée ouverte)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
    for index in range(rows):
        conn.execute("INSERT INTO items(label) VALUES (?)", (f"row-{index}",))
    return conn


def test_the_default_root_is_per_pc_per_checkout_and_ignores_the_current_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(data_root.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    live, sandbox = tmp_path / "CIRCOE" / "Jarvis", tmp_path / "CIRCOE" / "jarvis-dst"
    root = resolve_data_root({}, project_root=live)
    assert root.parent.parent == (tmp_path / "home" / ".jarvis" / "instances").resolve()
    assert root.name == "data" and root.parent.name.startswith("Jarvis-")
    assert resolve_data_root({}, project_root=live) == root
    # Le bac à sable sur le même PC n'ouvre jamais les bases du JARVIS vivant.
    assert resolve_data_root({}, project_root=sandbox) != root
    assert resolve_data_root({"JARVIS_DATA_ROOT": str(tmp_path / "elsewhere")}, project_root=live) == (tmp_path / "elsewhere").resolve()
    assert resolve_data_root({"JARVIS_DATA_ROOT": "  "}, project_root=live) == root


def test_legacy_data_is_copied_with_its_wal_and_the_source_is_left_untouched(tmp_path):
    legacy, target = tmp_path / "repo" / "data", tmp_path / "home" / "data"
    live = wal_database(legacy / "state" / "jarvis.sqlite3", 50)
    scene = wal_database(legacy / "state" / "scene.sqlite3", 3)
    (legacy / "history").mkdir(parents=True)
    (legacy / "history" / "2026-09-30.jsonl").write_text('{"turn": 1}\n', encoding="utf-8")
    (legacy / "memory" / "long_term_memory").mkdir(parents=True)
    (legacy / "memory" / "long_term_memory" / "note.md").write_text("souvenir", encoding="utf-8")
    (legacy / "memory" / "Jarvis-V1.md").write_text("versionné", encoding="utf-8")
    (legacy / "memory" / ".jarvis").mkdir()
    (legacy / "memory" / ".jarvis" / "index.sqlite3").write_bytes(b"index")
    try:
        assert (legacy / "state" / "jarvis.sqlite3-wal").stat().st_size > 0
        before = tree_digest(legacy)
        report = adopt_legacy_data(target, legacy)
        after = tree_digest(legacy)
        # Seul ajout permis : le témoin de reprise.
        assert after.pop(data_root.LEGACY_MARKER) and after == before
    finally:
        live.close()
        scene.close()
    assert set(report.databases) == {"state/jarvis.sqlite3", "state/scene.sqlite3"}
    assert report.databases["state/jarvis.sqlite3"]["rows"] == {"items": 50}
    conn = sqlite3.connect(target / "state" / "jarvis.sqlite3")
    try:
        assert conn.execute("SELECT count(*), max(label) FROM items").fetchone() == (50, "row-9")
    finally:
        conn.close()
    assert (target / "history" / "2026-09-30.jsonl").read_text(encoding="utf-8") == '{"turn": 1}\n'
    assert (target / "memory" / "long_term_memory" / "note.md").exists()
    assert not (target / "memory" / "Jarvis-V1.md").exists()
    assert not (target / "memory" / ".jarvis").exists()
    assert not list(target.rglob("*.partial"))
    [record] = json.loads((target / data_root.ADOPTION_RECORD).read_text(encoding="utf-8"))
    assert record["source"] == str(legacy.resolve())
    marker = json.loads((legacy / data_root.LEGACY_MARKER).read_text(encoding="utf-8"))
    assert marker["target"] == str(target.resolve())


def test_a_legacy_folder_already_adopted_elsewhere_is_never_copied_twice(tmp_path):
    """Dépôt déplacé : la racine par défaut change, l'ancien ./data suit le dépôt. Pas de copie périmée."""

    legacy, first, second = tmp_path / "legacy", tmp_path / "first", tmp_path / "second"
    wal_database(legacy / "state" / "jarvis.sqlite3", 4).close()
    assert adopt_legacy_data(first, legacy).adopted
    report = adopt_legacy_data(second, legacy)
    assert report.adopted is False
    assert report.adopted_elsewhere == str(first.resolve())
    assert not (second / "state" / "jarvis.sqlite3").exists()


def test_nothing_already_in_the_new_root_is_ever_overwritten(tmp_path):
    legacy, target = tmp_path / "legacy", tmp_path / "target"
    wal_database(legacy / "state" / "jarvis.sqlite3", 5).close()
    wal_database(target / "state" / "jarvis.sqlite3", 1).close()
    (legacy / "history").mkdir(parents=True)
    (legacy / "history" / "day.jsonl").write_text("old", encoding="utf-8")
    (target / "history").mkdir(parents=True)
    (target / "history" / "day.jsonl").write_text("new", encoding="utf-8")
    before = tree_digest(target)
    report = adopt_legacy_data(target, legacy)
    assert report.databases == {} and report.files_copied == 0
    assert report.skipped == ["state/jarvis.sqlite3: déjà présent dans la nouvelle racine"]
    assert tree_digest(target) == before
    # Un second démarrage ne refait rien non plus.
    assert adopt_legacy_data(target, legacy).adopted is False


def test_an_orphan_legacy_wal_is_reported_and_never_carried_over(tmp_path):
    legacy, target = tmp_path / "legacy", tmp_path / "target"
    (legacy / "state").mkdir(parents=True)
    (legacy / "state" / "scene.sqlite3-wal").write_bytes(b"orphan")
    report = adopt_legacy_data(target, legacy)
    assert report.skipped == ["state/scene.sqlite3: -wal sans sa base dans l'ancien dossier, laissé en place"]
    assert not (target / "state" / "scene.sqlite3-wal").exists()
    assert (legacy / "state" / "scene.sqlite3-wal").read_bytes() == b"orphan"


def test_a_corrupt_legacy_database_is_refused_and_nothing_is_put_in_place(tmp_path):
    legacy, target = tmp_path / "legacy", tmp_path / "target"
    (legacy / "state").mkdir(parents=True)
    (legacy / "state" / "jarvis.sqlite3").write_bytes(b"not a database" * 100)
    with pytest.raises((LegacyAdoptionError, sqlite3.DatabaseError)):
        adopt_legacy_data(target, legacy)
    assert not (target / "state" / "jarvis.sqlite3").exists()
    assert not list(target.rglob("*.partial")) if target.exists() else True


def test_core_falls_back_to_the_legacy_folder_when_adoption_fails(tmp_path, monkeypatch):
    from jarvis import app
    from jarvis.v2_config import V2Settings

    monkeypatch.delenv("JARVIS_DATA_ROOT", raising=False)
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(data_root.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    legacy = tmp_path / "legacy"
    (legacy / "state").mkdir(parents=True)
    (legacy / "state" / "jarvis.sqlite3").write_bytes(b"not a database" * 100)
    monkeypatch.setattr(data_root, "LEGACY_DATA_ROOT", legacy)
    settings = app._adopt_legacy_data_root(V2Settings.load())
    assert settings.data_root == legacy
    journal = (tmp_path / "runtime").rglob("*.jsonl")
    assert any("core.data_root.adoption_failed" in path.read_text(encoding="utf-8") for path in journal)
