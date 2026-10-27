"""Mise à jour sur un profil existant, et frontière du retour arrière (presentation-edition-v1 Slice 10, `docs/release.md`).

Bases JETABLES créées par le test (`scripts/release_seed_profile.py`, sous `tmp_path`) : jamais une base du dépôt ni du
JARVIS vivant. Programme factice (`make_package` de `test_product_setup`), ruche, menu Démarrer et Bureau simulés.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from jarvis import product_setup as S
from jarvis.adapters import sqlite_scene, sqlite_state
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.presentation_studio_service import PresentationStudioService
from scripts import release_seed_profile as SEED
from tests.unit.test_product_setup import RecordingShortcuts, make_package, quiet, targets


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


async def start_core_stores(home: Path) -> list[str]:
    """Ce que fait le nouveau Core au démarrage sur les deux bases : migrations après sauvegarde. Rend les Boards lus."""

    state = SQLiteStateRepository(home / "data" / "state" / "jarvis.sqlite3")
    await state.initialize()
    try:
        boards = [b.board_id for b in await SQLiteBoardRepository(state).list_boards(include_archived=True)]
    finally:
        await state.close()
    scene = SQLiteSceneRepository(home / "data" / "state" / "scene.sqlite3")
    await scene.initialize()
    await scene.close()
    return sorted(boards)


@pytest.fixture
def seeded(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "v020", "0.2.0"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    manifest = SEED.seed(t.home)
    return t, manifest


def test_the_seeded_profile_is_an_older_schema_with_real_rows(seeded):
    t, manifest = seeded
    assert manifest["state_from"] < sqlite_state._SCHEMA_VERSION and manifest["scene_from"] < sqlite_scene._SCHEMA_VERSION
    report = SEED.verify(t.home, manifest)
    assert not report["green"]  # pas encore migrée : versions anciennes, aucune sauvegarde
    assert any("à la version 10" in p for p in report["problems"]) and len(report["boards"]) == 3


def test_an_update_keeps_the_profile_byte_for_byte_then_core_migrates_it_after_backups(seeded, tmp_path):
    t, manifest = seeded
    before = tree(t.home)
    result = S.install(make_package(tmp_path / "v030", "0.3.0"), t, move=False, progress=quiet(),
                       shortcuts=RecordingShortcuts())
    assert result["mode"] == "update" and result["data_kept"]
    assert tree(t.home) == before  # l'installeur ne touche jamais la maison, bases comprises
    assert asyncio.run(start_core_stores(t.home)) == ["board_seed_ancien", "board_seed_rapport", "default"]
    report = SEED.verify(t.home, manifest)
    assert report["green"], report["problems"]
    assert report["databases"]["jarvis.sqlite3"] == {"now": sqlite_state._SCHEMA_VERSION, "backup": "jarvis.sqlite3.v10.bak",
                                                     "backup_version": 10}
    assert report["databases"]["scene.sqlite3"]["backup"] == "scene.sqlite3.v1.bak"
    # La Presentation du profil reste lisible par le Studio du nouveau code (aucun dossier jugé abîmé).
    studio = PresentationStudioService(FilePresentationStudioStore(t.home / "data"))
    listed = asyncio.run(studio.list_presentations(50)).to_dict()
    assert manifest["presentation"]["presentation_id"] in json.dumps(listed)
    assert "corrupt" not in json.dumps(listed)
    # Un second démarrage ne rejoue rien et ne réécrit pas la sauvegarde.
    backup = t.home / "data" / "state" / "jarvis.sqlite3.v10.bak"
    stamp = backup.stat().st_mtime_ns
    asyncio.run(start_core_stores(t.home))
    assert backup.stat().st_mtime_ns == stamp and SEED.verify(t.home, manifest)["green"]


def test_the_rollback_boundary_an_older_core_refuses_the_newer_base_until_its_backup_is_restored(seeded, tmp_path,
                                                                                               monkeypatch):
    """`docs/release.md` › *Rollback* : réinstaller l'ancienne version ne suffit pas, la base migrée est refusée ;
    restaurer la sauvegarde (après avoir mis la base migrée de côté, jamais supprimée) rend l'ancien Core utilisable."""

    t, manifest = seeded
    S.install(make_package(tmp_path / "v030", "0.3.0"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    asyncio.run(start_core_stores(t.home))
    # Retour du programme : l'installeur accepte une version plus ANCIENNE (mode « update ») et garde la maison.
    rolled = S.install(make_package(tmp_path / "v020b", "0.2.0"), t, move=False, progress=quiet(),
                       shortcuts=RecordingShortcuts())
    assert rolled["mode"] == "update" and t.registry.read()["DisplayVersion"] == "0.2.0"
    state_dir = t.home / "data" / "state"
    monkeypatch.setattr(sqlite_state, "_SCHEMA_VERSION", manifest["state_from"])  # l'ancien Core
    with pytest.raises(RuntimeError, match="newer than supported"):
        asyncio.run(start_core_stores(t.home))
    # Procédure documentée, JARVIS arrêté : mettre la base migrée de côté (copie), puis remettre la sauvegarde.
    migrated = state_dir / "jarvis.sqlite3"
    aside = state_dir / f"jarvis.sqlite3.v{manifest['state_current']}.before-rollback.bak"
    shutil.copy2(migrated, aside)
    shutil.copy2(state_dir / "jarvis.sqlite3.v10.bak", migrated)
    monkeypatch.setattr(sqlite_scene, "_SCHEMA_VERSION", manifest["scene_from"])
    shutil.copy2(state_dir / "scene.sqlite3", state_dir / f"scene.sqlite3.v{manifest['scene_current']}.before-rollback.bak")
    shutil.copy2(state_dir / "scene.sqlite3.v1.bak", state_dir / "scene.sqlite3")
    assert asyncio.run(start_core_stores(t.home)) == ["board_seed_ancien", "board_seed_rapport", "default"]
    # Rien de la maison n'a été perdu : fichiers semés intacts, base migrée gardée à côté.
    for relative, digest in manifest["files"].items():
        assert hashlib.sha256((t.home / relative).read_bytes()).hexdigest() == digest
    with sqlite3.connect(f"file:{aside.as_posix()}?mode=ro&immutable=1", uri=True) as conn:
        assert max(row[0] for row in conn.execute("SELECT version FROM schema_version")) > manifest["state_from"]


def test_the_seed_tool_refuses_a_non_empty_home(tmp_path):
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "x").write_text("y", encoding="utf-8")
    with pytest.raises(SystemExit, match="n'est pas vide"):
        SEED.seed(tmp_path / "home")


def test_the_seed_tool_cli_writes_its_manifest_and_verify_reports_red_before_migration(tmp_path, capsys):
    home, manifest = tmp_path / "Local" / "CIRCOE" / "Jarvis", tmp_path / "manifest.json"
    assert SEED.main(["seed", "--home", str(home), "--manifest", str(manifest)]) == 0
    assert json.loads(manifest.read_text(encoding="utf-8"))["schema"] == SEED.SCHEMA
    assert SEED.main(["verify", "--home", str(home), "--manifest", str(manifest), "--report", str(tmp_path / "r.json")]) == 1
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["green"] is False
