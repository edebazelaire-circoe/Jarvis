"""Arrêt brutal pendant la rétention des prefabs du Studio (Slice 01a) : vrai processus enfant tué (`os._exit`)
au milieu d'un archivage, sur un vrai système de fichiers ; puis un Core neuf relit le disque.

L'archivage est un seul `os.rename` : le processus est tué soit juste **avant** (rien n'a bougé), soit juste
**après** (la version est entière dans l'archive). Dans les deux cas : jamais une version coupée en deux, jamais
un octet perdu, un numéro retiré jamais réattribué, et le Core suivant reprend la passe.

Contrat : `docs/prefabs.md` › *Retention of studio scene sources*.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from tests.fakes.prefabs import candidate, install_version

SCENE = "presentation-studio.scene1"
REPO = Path(__file__).resolve().parents[2]
CRASH_EXIT = 77

CHILD = textwrap.dedent('''
    import asyncio, os, sys
    from pathlib import Path
    from jarvis.adapters.file_prefab_library import FilePrefabLibrary
    from jarvis.core import prefab_service
    from jarvis.core.prefab_service import PrefabService
    from tests.fakes.prefabs import candidate

    data, when, nth = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    prefab_service.RETENTION_TRIGGER_VERSIONS = 4
    prefab_service.RETENTION_KEEP_LAST = 2
    real_rename, seen = os.rename, [0]

    def rename(source, target, *args, **kwargs):
        if ".archive" not in str(target):
            return real_rename(source, target, *args, **kwargs)
        seen[0] += 1
        if seen[0] == nth and when == "before":
            os._exit(77)
        real_rename(source, target, *args, **kwargs)
        if seen[0] == nth and when == "after":
            os._exit(77)

    os.rename = rename

    class NoPins:
        async def pinned_versions(self, ids):
            return {i: frozenset({2}) for i in ids}

    service = PrefabService(FilePrefabLibrary(data.parent / "package", data), pin_registry=NoPins())
    asyncio.run(service.save(candidate(id="presentation-studio.scene1"), actor="user"))
    sys.exit(0)
''')


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir()
    data.mkdir()
    for version in range(1, 9):
        install_version(data / LIBRARY_DIR, SCENE, version)
    return package, data


def snapshot(folder: Path) -> dict[str, bytes]:
    return {str(path.relative_to(folder)): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def run_child(data: Path, when: str, nth: int) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.run([sys.executable, "-c", CHILD, str(data), when, str(nth)], env=env, cwd=REPO,
                          capture_output=True, text=True, timeout=120)


def disk(data: Path) -> tuple[list[int], list[int]]:
    live = sorted(int(p.name) for p in (data / LIBRARY_DIR / SCENE).iterdir())
    archive = data / LIBRARY_DIR / ".archive" / SCENE
    return live, (sorted(int(p.name) for p in archive.iterdir()) if archive.exists() else [])


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("nth", [1, 3])
async def test_a_process_killed_at_each_retire_step_leaves_a_consistent_library(roots, when, nth):
    _, data = roots
    originals = {v: snapshot(data / LIBRARY_DIR / SCENE / str(v)) for v in range(1, 9)}
    result = run_child(data, when, nth)
    assert result.returncode == CRASH_EXIT, result.stderr  # the child really died at the injected point
    live, archived = disk(data)
    # Pinned v2 and the last two (v7, v8) are never retired; v1,3,4,5,6 are, oldest first.
    expected_moved = [1, 3, 4, 5, 6][:nth if when == "after" else nth - 1]
    assert archived == expected_moved
    assert sorted(live + archived) == list(range(1, 9))  # nothing lost, nothing doubled
    for version in archived:  # moved whole: every byte of every file
        assert snapshot(data / LIBRARY_DIR / ".archive" / SCENE / str(version)) == originals[version]
    for version in live:
        assert snapshot(data / LIBRARY_DIR / SCENE / str(version)) == originals[version]
    # A fresh Core reads a healthy library, counts the archive as spent, and carries on.
    service = PrefabService(FilePrefabLibrary(*roots))
    await service.start()
    assert [entry.version for entry in service._entries_of(SCENE) if entry.ok] == live
    publication = await service.save(candidate(id=SCENE), actor="user")
    assert publication.version == 9


async def test_the_next_core_finishes_the_interrupted_pass(roots):
    _, data = roots
    assert run_child(data, "after", 2).returncode == CRASH_EXIT
    assert disk(data)[1] == [1, 3]

    class Pins:
        async def pinned_versions(self, ids):
            return {i: frozenset({2}) for i in ids}

    from jarvis.core import prefab_service
    saved = (prefab_service.RETENTION_TRIGGER_VERSIONS, prefab_service.RETENTION_KEEP_LAST)
    prefab_service.RETENTION_TRIGGER_VERSIONS, prefab_service.RETENTION_KEEP_LAST = 4, 2
    try:
        service = PrefabService(FilePrefabLibrary(*roots), pin_registry=Pins())
        await service.save(candidate(id=SCENE), actor="user")
    finally:
        prefab_service.RETENTION_TRIGGER_VERSIONS, prefab_service.RETENTION_KEEP_LAST = saved
    live, archived = disk(data)
    assert archived == [1, 3, 4, 5, 6] and live == [2, 7, 8, 9]


def test_a_killed_publish_next_to_a_retire_leaves_only_a_swept_staging_folder(roots):
    """Le crash de `publish` (autre étape) reste couvert : un `.staging-*` à balayer, jamais une demi-version."""

    _, data = roots
    staging = data / LIBRARY_DIR / ".staging-0123456789abcdef"
    staging.mkdir()
    (staging / "manifest.json").write_text("{", encoding="utf-8")
    report = FilePrefabLibrary(*roots).sweep()
    assert report.removed == (".staging-0123456789abcdef",) and not staging.exists()
