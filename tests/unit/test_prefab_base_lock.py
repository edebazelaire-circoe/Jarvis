"""Verrou du catalogue de base (`jarvis/prefabs/base/catalog.lock.json`, Slice 02).

Motif du Test Lab : chaque version de base livrée est verrouillée avec son
empreinte. Une édition en place (dérive), une version non verrouillée, une
version verrouillée disparue (orpheline) ou un dossier étranger font échouer
ce test. Publier une base = nouveau dossier `<id>/<v+1>/` + `publication.json`
+ entrée du verrou, jamais une réécriture. Contrat : `docs/prefabs.md` ›
*Storage and library*.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import jarvis
from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.domain.prefab import (
    LOCK_DRIFT, LOCK_ORPHAN, LOCK_UNLOCKED, MAX_MANIFEST_BYTES, CatalogLock, LockEntry, ProvenanceOrigin, Publication,
    check_lock_coverage, decode_json_text, parse_bundle,
)
from jarvis.ports.prefabs import PrefabRoot
from tests.fakes.prefabs import install_version

PACKAGE = Path(jarvis.__file__).resolve().parent / "prefabs" / "base"


def shipped_fingerprints(package: Path, data: Path) -> dict[tuple[str, int], str]:
    """`{(id, v): empreinte}` des versions du paquet, chacune relue, validée et conforme à sa publication."""

    library = FilePrefabLibrary(package, data)
    scan = library.scan()
    assert scan.problems == (), [(item.path, item.reason) for item in scan.problems]
    found = {}
    for item in scan.versions:
        assert item.root is PrefabRoot.PACKAGE
        files = library.read_version(item.root, item.prefab_id, item.version)
        bundle = parse_bundle(decode_json_text(files.manifest, MAX_MANIFEST_BYTES, "manifest"), files.template,
                              files.style, files.behavior)
        assert (bundle.manifest.prefab_id, bundle.manifest.version) == (item.prefab_id, item.version)
        assert files.publication is not None, f"{item.prefab_id}@{item.version} ships no publication.json"
        publication = Publication.decode_text(files.publication)
        assert publication.provenance.origin is ProvenanceOrigin.BASE
        assert publication.fingerprint == bundle.fingerprint(), f"{item.prefab_id}@{item.version} edited in place"
        found[(item.prefab_id, item.version)] = bundle.fingerprint()
    return found


def test_the_shipped_lock_matches_the_shipped_base_prefabs(tmp_path):
    lock_text = (PACKAGE / "catalog.lock.json").read_text(encoding="utf-8")
    lock = CatalogLock.decode_text(lock_text)
    assert lock.render() == lock_text.replace("\r\n", "\n"), "catalog.lock.json is not in its canonical form"
    found = shipped_fingerprints(PACKAGE, tmp_path)
    assert check_lock_coverage(found, lock) == ()
    assert all(prefab_id.startswith("jarvis.") for prefab_id, _ in found)


def test_the_package_holds_only_the_lock_and_base_id_folders():
    strays = [path.name for path in PACKAGE.iterdir()
              if path.name != "catalog.lock.json" and not (path.is_dir() and path.name.startswith("jarvis."))]
    assert strays == []


@pytest.fixture
def locked_package(tmp_path: Path) -> tuple[Path, Path, CatalogLock]:
    package = tmp_path / "base"
    package.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    install_version(package, "jarvis.counter")
    lock = CatalogLock(tuple(LockEntry(*key, digest) for key, digest in shipped_fingerprints(package, data).items()))
    return package, data, lock


def test_a_fingerprint_drift_fails(locked_package):
    package, data, lock = locked_package
    folder = package / "jarvis.counter" / "1"
    (folder / "style.css").write_bytes(b".edited{}")
    publication = json.loads((folder / "publication.json").read_text(encoding="utf-8"))
    bundle = parse_bundle(json.loads((folder / "manifest.json").read_text(encoding="utf-8")),
                          (folder / "template.html").read_text(encoding="utf-8"), ".edited{}",
                          (folder / "behavior.js").read_text(encoding="utf-8"))
    publication["fingerprint"] = bundle.fingerprint()  # even a matching publication cannot hide the edit
    (folder / "publication.json").write_text(json.dumps(publication), encoding="utf-8")
    codes = [code for code, _ in check_lock_coverage(shipped_fingerprints(package, data), lock)]
    assert codes == [LOCK_DRIFT]


def test_an_unlocked_version_and_an_orphan_fail(locked_package):
    package, data, lock = locked_package
    install_version(package, "jarvis.counter", 2, origin=ProvenanceOrigin.BASE)
    assert [code for code, _ in check_lock_coverage(shipped_fingerprints(package, data), lock)] == [LOCK_UNLOCKED]
    orphan = CatalogLock((*lock.entries, LockEntry("jarvis.gone", 1, "a" * 64)))
    found = shipped_fingerprints(package, data)
    full = CatalogLock((*orphan.entries, LockEntry("jarvis.counter", 2, found[("jarvis.counter", 2)])))
    assert [code for code, _ in check_lock_coverage(found, full)] == [LOCK_ORPHAN]
