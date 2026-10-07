"""Magasin de prefabs sur disque (Slice 02) : balayage des deux racines, publication atomique et immuable,
refus des liens et jonctions, balayage des publications interrompues, paquet jamais écrit.

Contrat : `docs/prefabs.md` › *Storage and library*. Dossiers temporaires seulement.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.adapters import file_prefab_library as lib_module
from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.domain.prefab import (
    MAX_VERSIONS_PER_ID, CreatorActor, Provenance, ProvenanceOrigin, Publication, parse_candidate, with_version,
)
from jarvis.ports.prefabs import PrefabRoot, PrefabStoreError, PrefabStoreErrorCode
from tests.fakes.prefabs import candidate, install_version


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "package" / "base"
    package.mkdir(parents=True)
    (package / "catalog.lock.json").write_text("{}", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    return package, data


@pytest.fixture
def library(roots) -> FilePrefabLibrary:
    return FilePrefabLibrary(*roots)


def bundle_and_publication(prefab_id: str = "lab.counter", version: int = 1):
    raw = candidate()
    bundle = parse_candidate({**raw, "manifest": with_version({**raw["manifest"], "id": prefab_id}, version)})
    publication = Publication(prefab_id, version, bundle.fingerprint(), "2026-10-03T12:00:00Z",
                              Provenance(ProvenanceOrigin.CUSTOM, CreatorActor.USER))
    return bundle, publication


def store_error(action) -> PrefabStoreError:
    with pytest.raises(PrefabStoreError) as caught:
        action()
    return caught.value


def junction(link: Path, target: Path) -> None:
    """Vraie jonction NTFS ; `skip` motivé seulement si Windows la refuse.

    Même règle que `test_board_memory_store`.
    """

    if os.name != "nt":
        pytest.skip("NTFS junctions exist only on Windows; the symlink test covers POSIX")
    import _winapi

    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError as exc:  # pragma: no cover - depends on the host
        pytest.skip(f"junction creation refused by the host: {exc}")


def tree_state(root: Path) -> list[tuple[str, int, int]]:
    return sorted((str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
                  for path in root.rglob("*"))


# ------------------------------------------------------------------ balayage


def test_scan_lists_both_roots_and_reports_strays(roots, library):
    package, data = roots
    install_version(package, "jarvis.counter")
    install_version(data / LIBRARY_DIR, "lab.counter")
    install_version(data / LIBRARY_DIR, "lab.counter", 2, origin=ProvenanceOrigin.REVISION)
    (data / LIBRARY_DIR / ".staging-0123456789abcdef").mkdir()
    (data / LIBRARY_DIR / "NotAnId").mkdir()
    (data / LIBRARY_DIR / "lab.counter" / "draft").mkdir()
    (data / LIBRARY_DIR / "lab.counter" / "3").mkdir()  # no manifest.json

    scan = library.scan()

    assert sorted((item.root, item.prefab_id, item.version) for item in scan.versions) == [
        (PrefabRoot.DATA, "lab.counter", 1), (PrefabRoot.DATA, "lab.counter", 2),
        (PrefabRoot.PACKAGE, "jarvis.counter", 1)]
    assert all(len(item.signature) == 5 for item in scan.versions)
    reasons = {(item.root, item.path): item.reason for item in scan.problems}
    assert reasons == {(PrefabRoot.DATA, "NotAnId"): "folder name is not a prefab id",
                       (PrefabRoot.DATA, "lab.counter/draft"): "not a version folder (1..9999)",
                       (PrefabRoot.DATA, "lab.counter/3"): "no manifest.json"}


def test_scan_reports_every_numbered_version_folder_even_uncatalogued(roots, library):
    package, data = roots
    install_version(package, "jarvis.counter")
    (package / "jarvis.counter" / "4").mkdir()  # no manifest.json: a problem, yet the number is taken
    install_version(data / LIBRARY_DIR, "lab.counter")
    (data / LIBRARY_DIR / "lab.counter" / "2").mkdir()
    (data / LIBRARY_DIR / "lab.counter" / "draft").mkdir()
    assert sorted(library.scan().version_folders) == [
        (PrefabRoot.DATA, "lab.counter", 1), (PrefabRoot.DATA, "lab.counter", 2),
        (PrefabRoot.PACKAGE, "jarvis.counter", 1), (PrefabRoot.PACKAGE, "jarvis.counter", 4)]


def test_scan_without_a_data_library_creates_nothing(roots, library):
    _, data = roots
    assert library.scan().versions == ()
    assert not (data / LIBRARY_DIR).exists()


def test_scan_bounds_versions_per_id(roots, library):
    package, _ = roots
    for version in range(1, MAX_VERSIONS_PER_ID + 2):
        folder = package / "jarvis.many" / str(version)
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{}", encoding="utf-8")
    scan = library.scan()
    assert len(scan.versions) == MAX_VERSIONS_PER_ID
    assert max(item.version for item in scan.versions) == MAX_VERSIONS_PER_ID
    assert any("more than 64 versions" in item.reason for item in scan.problems)


# ------------------------------------------------------------------ lecture


def test_read_version_returns_the_raw_texts(roots, library):
    package, _ = roots
    published = install_version(package, "jarvis.counter")
    files = library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 1)
    assert Publication.decode_text(files.publication) == published
    assert files.template == candidate()["template"]


def test_read_version_refusals(roots, library):
    package, _ = roots
    install_version(package, "jarvis.counter")
    folder = package / "jarvis.counter" / "1"
    assert store_error(lambda: library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 2)).code \
        is PrefabStoreErrorCode.UNKNOWN_VERSION
    assert store_error(lambda: library.read_version(PrefabRoot.PACKAGE, "../x", 1)).code \
        is PrefabStoreErrorCode.UNKNOWN_PREFAB
    (folder / "style.css").write_bytes(b"\xff\xfe")
    assert "not valid UTF-8" in store_error(
        lambda: library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 1)).message
    (folder / "style.css").write_bytes(b"x" * (32 * 1024 + 1))
    assert store_error(lambda: library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 1)).code \
        is PrefabStoreErrorCode.TAMPERED
    (folder / "style.css").unlink()
    error = store_error(lambda: library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 1))
    assert error.code is PrefabStoreErrorCode.TAMPERED and "style.css is missing" in error.message
    (folder / "style.css").write_text("", encoding="utf-8")
    (folder / "publication.json").unlink()
    assert library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 1).publication is None


def test_a_symlinked_file_inside_a_version_is_refused(roots, library, tmp_path):
    package, _ = roots
    install_version(package, "jarvis.counter")
    outside = tmp_path / "outside.css"
    outside.write_text(".x{}", encoding="utf-8")
    target = package / "jarvis.counter" / "1" / "style.css"
    target.unlink()
    try:
        os.symlink(outside, target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation impossible here (Windows needs Developer Mode or the privilege): {exc}")
    error = store_error(lambda: library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 1))
    assert error.code is PrefabStoreErrorCode.TAMPERED and "not a regular file" in error.message


def test_a_file_reported_as_a_link_is_refused_without_symlink_privilege(roots, library, monkeypatch):
    """Sans privilège de lien symbolique : `is_link` simulé pour un seul fichier, le reste du chemin réel."""

    package, _ = roots
    install_version(package, "jarvis.counter")
    linked = os.lstat(package / "jarvis.counter" / "1" / "style.css")
    real_is_link = lib_module.safe_folders.is_link

    def is_link(info: os.stat_result) -> bool:
        if (info.st_dev, info.st_ino) == (linked.st_dev, linked.st_ino):
            return True
        return real_is_link(info)

    monkeypatch.setattr(lib_module.safe_folders, "is_link", is_link)
    error = store_error(lambda: library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 1))
    assert error.code is PrefabStoreErrorCode.TAMPERED
    assert error.message == "jarvis.counter/1/style.css: not a regular file (link or folder refused)"


# ------------------------------------------------------------------ publication


def test_publish_writes_one_immutable_version_into_the_data_root(roots, library):
    _, data = roots
    bundle, publication = bundle_and_publication()
    assert library.publish(bundle, publication) == "lab.counter/1"
    folder = data / LIBRARY_DIR / "lab.counter" / "1"
    assert sorted(path.name for path in folder.iterdir()) == [
        "behavior.js", "manifest.json", "publication.json", "style.css", "template.html"]
    files = library.read_version(PrefabRoot.DATA, "lab.counter", 1)
    assert Publication.decode_text(files.publication) == publication
    assert files.behavior == bundle.behavior
    assert [item.name for item in (data / LIBRARY_DIR).iterdir()] == ["lab.counter"]  # no staging left


def test_publish_never_overwrites_a_version(roots, library):
    _, data = roots
    bundle, publication = bundle_and_publication()
    library.publish(bundle, publication)
    folder = data / LIBRARY_DIR / "lab.counter" / "1"
    before = tree_state(folder)
    other, other_publication = bundle_and_publication()
    error = store_error(lambda: library.publish(other, other_publication))
    assert error.code is PrefabStoreErrorCode.VERSION_EXISTS
    assert tree_state(folder) == before


def test_a_version_appearing_during_publish_is_not_overwritten(roots, library, monkeypatch):
    _, data = roots
    target = data / LIBRARY_DIR / "lab.counter" / "1"
    real_write = lib_module._write_file

    def racing_write(path: Path, text: str) -> None:
        real_write(path, text)
        if path.name == "publication.json":
            target.mkdir()
            (target / "manifest.json").write_text("concurrent", encoding="utf-8")

    monkeypatch.setattr(lib_module, "_write_file", racing_write)
    error = store_error(lambda: library.publish(*bundle_and_publication()))
    assert error.code is PrefabStoreErrorCode.VERSION_EXISTS
    assert (target / "manifest.json").read_text(encoding="utf-8") == "concurrent"
    assert [item.name for item in (data / LIBRARY_DIR).iterdir()] == ["lab.counter"]


def test_a_failure_between_files_leaves_no_version(roots, library, monkeypatch):
    _, data = roots
    calls = []
    real_write = lib_module._write_file

    def failing_write(path: Path, text: str) -> None:
        calls.append(path.name)
        if len(calls) == 3:
            raise OSError(28, "No space left on device")
        real_write(path, text)

    monkeypatch.setattr(lib_module, "_write_file", failing_write)
    error = store_error(lambda: library.publish(*bundle_and_publication()))
    assert error.code is PrefabStoreErrorCode.STORAGE_IO and "No space left" in error.message
    assert not (data / LIBRARY_DIR / "lab.counter" / "1").exists()
    assert library.scan().versions == ()
    assert [item.name for item in (data / LIBRARY_DIR).iterdir()] == ["lab.counter"]  # staging removed


def test_a_hard_crash_mid_publish_leaves_only_a_staging_folder_that_the_sweep_removes(roots, library, monkeypatch):
    _, data = roots
    real_write = lib_module._write_file
    calls = []

    def crashing_write(path: Path, text: str) -> None:
        calls.append(path.name)
        if len(calls) == 2:
            raise OSError(5, "process killed")
        real_write(path, text)

    monkeypatch.setattr(lib_module, "_write_file", crashing_write)
    monkeypatch.setattr(lib_module, "_remove_staging", lambda folder: False)  # a kill cleans nothing
    store_error(lambda: library.publish(*bundle_and_publication()))
    staging = [item for item in (data / LIBRARY_DIR).iterdir() if item.name.startswith(".staging-")]
    assert len(staging) == 1 and (staging[0] / "manifest.json").exists()
    assert library.scan().versions == () and library.scan().problems == ()

    monkeypatch.undo()
    report = library.sweep()
    assert report.removed == (staging[0].name,) and report.failed == ()
    assert not staging[0].exists()


def test_publish_refuses_a_bundle_that_does_not_match_its_publication(library):
    bundle, _ = bundle_and_publication("lab.counter", 1)
    _, other = bundle_and_publication("lab.other", 1)
    assert store_error(lambda: library.publish(bundle, other)).code is PrefabStoreErrorCode.INVALID_DEFINITION


# ------------------------------------------------------------------ liens et jonctions


def test_a_junctioned_library_is_never_written_through(roots, library, tmp_path):
    _, data = roots
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    junction(data / LIBRARY_DIR, elsewhere)
    error = store_error(lambda: library.publish(*bundle_and_publication()))
    assert error.code is PrefabStoreErrorCode.STORAGE_IO and "unsafe" in error.message
    assert list(elsewhere.iterdir()) == []
    assert any(item.root is PrefabRoot.DATA for item in library.scan().problems)
    assert library.sweep().failed


def test_a_junctioned_prefab_folder_is_refused_on_publish_and_scan(roots, library, tmp_path):
    _, data = roots
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (data / LIBRARY_DIR).mkdir()
    junction(data / LIBRARY_DIR / "lab.counter", elsewhere)
    install_version(elsewhere.parent / "seed", "lab.counter")
    os.replace(elsewhere.parent / "seed" / "lab.counter" / "1", elsewhere / "1")
    error = store_error(lambda: library.publish(*bundle_and_publication("lab.counter", 2)))
    assert error.code is PrefabStoreErrorCode.STORAGE_IO
    scan = library.scan()
    assert scan.versions == ()
    assert [(item.path, item.reason) for item in scan.problems] == [
        ("lab.counter", "symbolic link, junction or reparse point refused")]
    assert store_error(lambda: library.read_version(PrefabRoot.DATA, "lab.counter", 1)).code \
        is PrefabStoreErrorCode.STORAGE_IO


def test_a_junctioned_version_folder_in_the_package_is_not_catalogued(roots, library, tmp_path):
    package, _ = roots
    install_version(tmp_path / "seed", "jarvis.counter")
    (package / "jarvis.counter").mkdir()
    junction(package / "jarvis.counter" / "1", tmp_path / "seed" / "jarvis.counter" / "1")
    scan = library.scan()
    assert scan.versions == ()
    assert [item.path for item in scan.problems] == ["jarvis.counter/1"]


def test_a_symlinked_library_is_refused_on_posix_too(roots, library, tmp_path):
    _, data = roots
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        os.symlink(elsewhere, data / LIBRARY_DIR, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation impossible here (Windows needs Developer Mode or the privilege): {exc}")
    assert store_error(lambda: library.publish(*bundle_and_publication())).code is PrefabStoreErrorCode.STORAGE_IO
    assert list(elsewhere.iterdir()) == []


# ------------------------------------------------------------------ balayage des publications interrompues


def test_sweep_removes_only_staging_folders_it_can_empty_safely(roots, library):
    _, data = roots
    root = data / LIBRARY_DIR
    root.mkdir()
    plain = root / ".staging-00000000000000aa"
    plain.mkdir()
    (plain / "manifest.json").write_text("{}", encoding="utf-8")
    (plain / "style.css.tmp").write_text("x", encoding="utf-8")
    nested = root / ".staging-00000000000000bb"
    (nested / "sub").mkdir(parents=True)
    other = root / ".staging-not-ours"
    other.mkdir()
    report = library.sweep()
    assert report.removed == (plain.name,)
    assert report.failed == (nested.name,)
    assert not plain.exists() and (nested / "sub").exists() and other.exists()


def test_sweep_without_a_library_does_nothing(roots, library):
    _, data = roots
    report = library.sweep()
    assert report.removed == () and report.failed == ()
    assert not (data / LIBRARY_DIR).exists()


# ------------------------------------------------------------------ paquet jamais écrit


def test_the_package_root_is_never_written(roots, library):
    package, _ = roots
    install_version(package, "jarvis.counter")
    before = tree_state(package)
    package_mtime = package.stat().st_mtime_ns
    library.scan()
    library.read_version(PrefabRoot.PACKAGE, "jarvis.counter", 1)
    library.publish(*bundle_and_publication("lab.counter", 1))
    library.sweep()
    assert tree_state(package) == before
    assert package.stat().st_mtime_ns == package_mtime


# ------------------------------------------------------------------ retire / archive (Slice 01a)


def _tree_bytes(folder: Path) -> dict[str, bytes]:
    return {str(path.relative_to(folder)): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def test_retire_moves_one_version_whole_to_the_archive_and_keeps_its_number_occupied(roots, library):
    _, data = roots
    root = data / LIBRARY_DIR
    for version in (1, 2, 3):
        install_version(root, "presentation-studio.scene1", version)
    before = _tree_bytes(root / "presentation-studio.scene1" / "2")
    assert library.retire("presentation-studio.scene1", 2) == "presentation-studio.scene1/2"
    archived = root / ".archive" / "presentation-studio.scene1" / "2"
    assert _tree_bytes(archived) == before  # every byte kept, publication.json included
    assert not (root / "presentation-studio.scene1" / "2").exists()
    scan = library.scan()
    assert [item.version for item in scan.versions] == [1, 3]
    assert (PrefabRoot.DATA, "presentation-studio.scene1", 2) in scan.version_folders
    assert scan.problems == ()


def test_retiring_the_last_version_leaves_no_id_folder_but_the_number_stays_taken(roots, library):
    _, data = roots
    root = data / LIBRARY_DIR
    install_version(root, "presentation-studio.scene1", 1)
    library.retire("presentation-studio.scene1", 1)
    assert not (root / "presentation-studio.scene1").exists()
    assert library.scan().versions == ()
    assert library.scan().version_folders == ((PrefabRoot.DATA, "presentation-studio.scene1", 1),)


def test_retire_refuses_what_is_not_a_data_version_and_moves_nothing(roots, library):
    package, data = roots
    install_version(package, "jarvis.counter")
    install_version(data / LIBRARY_DIR, "lab.counter")
    install_version(data / LIBRARY_DIR, "presentation-studio.scene1")
    # Outside the retention namespace nothing moves, whatever the root: user data and bases are never archived.
    assert store_error(lambda: library.retire("jarvis.counter", 1)).code is PrefabStoreErrorCode.INVALID_DEFINITION
    assert store_error(lambda: library.retire("lab.counter", 1)).code is PrefabStoreErrorCode.INVALID_DEFINITION
    assert store_error(lambda: library.retire("presentation-studio.scene1", 7)).code \
        is PrefabStoreErrorCode.UNKNOWN_VERSION
    assert store_error(lambda: library.retire("not an id", 1)).code is PrefabStoreErrorCode.UNKNOWN_PREFAB
    assert store_error(lambda: library.retire("presentation-studio./x", 1)).code is PrefabStoreErrorCode.UNKNOWN_PREFAB
    assert store_error(lambda: library.retire("presentation-studio.scene1", 0)).code \
        is PrefabStoreErrorCode.UNKNOWN_VERSION
    assert (package / "jarvis.counter" / "1" / "manifest.json").exists()
    assert (data / LIBRARY_DIR / "lab.counter" / "1" / "manifest.json").exists()
    assert (data / LIBRARY_DIR / "presentation-studio.scene1" / "1" / "manifest.json").exists()
    assert not (data / LIBRARY_DIR / ".archive").exists()


def test_retire_never_overwrites_an_archive_slot(roots, library):
    _, data = roots
    root = data / LIBRARY_DIR
    install_version(root, "presentation-studio.scene1", 1)
    slot = root / ".archive" / "presentation-studio.scene1" / "1"
    slot.mkdir(parents=True)
    (slot / "keep.txt").write_text("precious", encoding="utf-8")
    error = store_error(lambda: library.retire("presentation-studio.scene1", 1))
    assert error.code is PrefabStoreErrorCode.STORAGE_IO
    assert (slot / "keep.txt").read_text(encoding="utf-8") == "precious"
    assert (root / "presentation-studio.scene1" / "1" / "manifest.json").exists()


def test_a_junction_archive_id_folder_is_a_scan_problem_not_followed(roots, library, tmp_path):
    _, data = roots
    outside = tmp_path / "outside"
    (outside / "7").mkdir(parents=True)
    (data / LIBRARY_DIR / ".archive").mkdir(parents=True)
    junction(data / LIBRARY_DIR / ".archive" / "presentation-studio.scene1", outside)
    scan = library.scan()
    assert scan.version_folders == ()
    assert any(".archive/presentation-studio.scene1" in item.path for item in scan.problems)
