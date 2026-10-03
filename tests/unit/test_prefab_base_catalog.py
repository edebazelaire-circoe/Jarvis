"""Catalogue de base livré (prefab-foundation, Slice 05) : `jarvis.window`, `jarvis.document`, `jarvis.table`.

Contrat : `docs/prefabs.md` › *Base catalogue* (entrées et événements de
chaque famille, règle d'extension) et handoff doc 06 D-FAMILIES. Chaque
version livrée : manifeste valide, exemple valide, publication `base`/`system`
à la bonne empreinte, entrée du verrou ; Core la trouve par ses alias ; elle
compose la coquille partagée au lieu de la recopier. Le comportement de chaque
prefab dans le shim est prouvé par `test_prefab_base_behaviors_js.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import jarvis
from jarvis.adapters.file_prefab_library import FilePrefabLibrary, FilePrefabRuntime
from jarvis.core.prefab_service import PrefabService
from jarvis.domain.prefab import (
    MAX_MANIFEST_BYTES, CatalogLock, CreatorActor, EventClass, PrefabInstanceRef, ProvenanceOrigin, Publication,
    check_lock_coverage, decode_json_text, parse_bundle, validate_value,
)
from scripts import lock_base_prefabs

PACKAGE = Path(jarvis.__file__).resolve().parent / "prefabs" / "base"
RUNTIME = PACKAGE.parent / "runtime"
SHELL = (RUNTIME / "shell.css").read_text(encoding="utf-8")

#: Entrées et événements fixés par le contrat de la Slice 05 (SLICE.md › Slice 00 contract).
FAMILIES = {
    "jarvis.window": {"props": {"accent", "density"}, "data": {"body", "items"}, "events": {}},
    "jarvis.document": {"props": {"accent", "scale"}, "data": {"body"}, "events": {}},
    "jarvis.table": {"props": {"accent", "zebra"}, "data": {"columns", "rows"}, "events": {"row_selected": "notify"}},
}


def bundle_of(prefab_id: str, version: int = 1):
    folder = PACKAGE / prefab_id / str(version)
    text = {name: (folder / name).read_bytes().decode("utf-8")
            for name in ("manifest.json", "template.html", "style.css", "behavior.js")}
    return parse_bundle(decode_json_text(text["manifest.json"], MAX_MANIFEST_BYTES, "manifest"),
                        text["template.html"], text["style.css"], text["behavior.js"])


@pytest.fixture
async def service(tmp_path):
    prefabs = PrefabService(FilePrefabLibrary(PACKAGE, tmp_path), runtime=FilePrefabRuntime(RUNTIME))
    await prefabs.start()
    return prefabs


@pytest.mark.parametrize("prefab_id", sorted(FAMILIES))
def test_each_base_manifest_is_valid_and_declares_its_contract(prefab_id):
    bundle = bundle_of(prefab_id)
    manifest = bundle.manifest
    expected = FAMILIES[prefab_id]
    assert (manifest.prefab_id, manifest.version, manifest.family) == (prefab_id, 1, "window")
    assert set(manifest.props.properties) == expected["props"]
    assert set(manifest.data.properties) == expected["data"]
    assert {name: EventClass(event.event_class).value for name, event in manifest.events.items()} == expected["events"]
    assert manifest.props.properties["accent"].type.value == "color"
    for name in ("manifest.json", "template.html", "style.css", "behavior.js"):
        assert b"\r" not in (PACKAGE / prefab_id / "1" / name).read_bytes(), f"{prefab_id}/{name} must be LF"


@pytest.mark.parametrize("prefab_id", sorted(FAMILIES))
def test_each_sample_validates_and_the_empty_instance_too(prefab_id):
    manifest = bundle_of(prefab_id).manifest
    for props, data in ((manifest.sample_props, manifest.sample_data),
                        ({}, {"columns": [{"label": "A"}]} if prefab_id == "jarvis.table" else
                         {"body": ""} if prefab_id == "jarvis.document" else {})):
        _, problems = validate_value(manifest.props, props, "props")
        _, more = validate_value(manifest.data, data, "data")
        assert problems + more == ()


def test_the_bounds_of_the_contract_are_enforced():
    window, table = bundle_of("jarvis.window").manifest, bundle_of("jarvis.table").manifest
    document = bundle_of("jarvis.document").manifest
    assert validate_value(window.data, {"items": [{"label": "x"}] * 65}, "data")[1]
    assert validate_value(window.data, {"body": "x" * 8001}, "data")[1]
    assert validate_value(window.props, {"density": "airy"}, "props")[1]
    assert validate_value(document.data, {"body": "x" * 12001}, "data")[1]
    assert validate_value(document.props, {"scale": "xl"}, "props")[1]
    assert validate_value(table.data, {"columns": []}, "data")[1]
    assert validate_value(table.data, {"columns": [{"label": "c"}] * 9}, "data")[1]
    assert validate_value(table.data, {"columns": [{"label": "c" * 41}]}, "data")[1]
    assert validate_value(table.data, {"columns": [{"label": "c", "align": "justify"}]}, "data")[1]
    assert validate_value(table.data, {"columns": [{"label": "c"}], "rows": [["v"]] * 65}, "data")[1]
    assert validate_value(table.data, {"columns": [{"label": "c"}], "rows": [["v"] * 9]}, "data")[1]
    assert validate_value(table.data, {"columns": [{"label": "c"}], "rows": [["v" * 201]]}, "data")[1]
    filled, problems = validate_value(table.data, {"columns": [{"label": "c"}]}, "data")
    assert problems == () and filled == {"columns": [{"label": "c", "align": "left"}], "rows": []}


def test_each_version_ships_a_base_system_publication_and_the_lock_matches(tmp_path):
    lock = CatalogLock.decode_text((PACKAGE / "catalog.lock.json").read_text(encoding="utf-8"))
    found = {}
    for prefab_id in FAMILIES:
        fingerprint = bundle_of(prefab_id).fingerprint()
        publication = Publication.decode_text((PACKAGE / prefab_id / "1" / "publication.json").read_text("utf-8"))
        assert publication.provenance.origin is ProvenanceOrigin.BASE
        assert publication.provenance.created_by is CreatorActor.SYSTEM
        assert publication.provenance.derived_from is None and publication.fingerprint == fingerprint
        found[(prefab_id, 1)] = fingerprint
    assert set(found) <= set(lock.index)
    assert check_lock_coverage({key: digest for key, digest in found.items()},
                               CatalogLock(tuple(entry for entry in lock.entries if entry.key in found))) == ()
    # Le script de publication n'a plus rien à écrire : verrou et publications sont à jour.
    writes, _ = lock_base_prefabs.plan(PACKAGE, "2026-10-03T00:00:00Z")
    assert writes == {}


def test_the_lock_script_refuses_an_edit_in_place_and_writes_a_new_version(tmp_path):
    package = tmp_path / "base"
    folder = package / "jarvis.window" / "1"
    folder.mkdir(parents=True)
    for name in ("manifest.json", "template.html", "style.css", "behavior.js"):
        (folder / name).write_bytes((PACKAGE / "jarvis.window" / "1" / name).read_bytes())
    (package / "catalog.lock.json").write_bytes(CatalogLock().render().encode())
    writes, lock = lock_base_prefabs.plan(package, "2026-10-03T00:00:00Z")
    assert sorted(path.name for path in writes) == ["catalog.lock.json", "publication.json"]
    for path, text in writes.items():
        path.write_bytes(text.encode())
    assert [entry.key for entry in lock.entries] == [("jarvis.window", 1)]
    (folder / "style.css").write_bytes(b".edited{}\n")
    with pytest.raises(lock_base_prefabs.LockError, match="publish a new version"):
        lock_base_prefabs.plan(package, "2026-10-03T00:00:00Z")
    (folder / "style.css").write_bytes(b".edited{}\r\n")
    with pytest.raises(lock_base_prefabs.LockError, match="LF"):
        lock_base_prefabs.plan(package, "2026-10-03T00:00:00Z")


@pytest.mark.parametrize(("query", "expected"), [
    ("tableau", "jarvis.table"), ("document", "jarvis.document"), ("fenêtre", "jarvis.window"),
    ("Fenêtre", "jarvis.window"), ("lecture", "jarvis.document"), ("view_table", "jarvis.table"),
])
async def test_core_search_finds_each_family_by_alias(service, query, expected):
    rows = await service.search(query, class_filter="base")
    assert rows and rows[0].prefab_id == expected


async def test_core_lists_the_three_families_healthy_and_validates_their_samples(service):
    rows = {row.prefab_id: row for row in await service.search(class_filter="base", limit=50)}
    assert set(FAMILIES) <= set(rows)
    for prefab_id in FAMILIES:
        assert rows[prefab_id].family == "window" and rows[prefab_id].latest_version == 1
        manifest = bundle_of(prefab_id).manifest
        result = await service.validate_instance(PrefabInstanceRef(prefab_id, 1, manifest.sample_props,
                                                                    manifest.sample_data))
        assert result.ok, result.detail
        assert result.props["accent"] == "#6ee7ff"
        bundle = await service.bundle(prefab_id, 1)
        assert bundle["manifest"]["id"] == prefab_id and bundle["runtime"]["shell_css"] == SHELL
    assert rows["jarvis.table"].event_names == ("row_selected",)


def _selectors(css: str) -> list[str]:
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [part.strip() for block in re.findall(r"([^{}]+)\{", body) for part in block.split(",")]


@pytest.mark.parametrize("prefab_id", sorted(FAMILIES))
def test_each_style_composes_the_shell_and_never_copies_it(prefab_id):
    style = (PACKAGE / prefab_id / "1" / "style.css").read_text(encoding="utf-8")
    template = (PACKAGE / prefab_id / "1" / "template.html").read_text(encoding="utf-8")
    behavior = (PACKAGE / prefab_id / "1" / "behavior.js").read_text(encoding="utf-8")
    shell_selectors = set(_selectors(SHELL))
    for selector in _selectors(style):
        assert selector not in shell_selectors, f"{prefab_id} redefines shell selector {selector!r}"
        assert not re.match(r"\.jv-[\w-]+$", selector), f"{prefab_id} restyles shell class {selector!r} globally"
        assert selector not in (":root", "html", "body", "*"), f"{prefab_id} restyles the shell root {selector!r}"
    assert "--jv-accent" in style, f"{prefab_id} must follow the accent prop"
    assert "jv-" in template + behavior, f"{prefab_id} must compose shell classes"
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "Function(", "localStorage", "fetch("):
        assert forbidden not in behavior, f"{prefab_id} behavior uses {forbidden}"


def test_window_labels_wrap_where_the_legacy_window_cuts_them():
    style = (PACKAGE / "jarvis.window" / "1" / "style.css").read_text(encoding="utf-8")
    label = re.search(r"\.win-label\{([^}]*)\}", style).group(1)
    assert "white-space:normal" in label and "overflow-wrap:anywhere" in label and "ellipsis" not in label
    legacy = (Path(jarvis.__file__).resolve().parent / "runtime" / "control_center_scene_page.js").read_text("utf-8")
    assert re.search(r"\.sc-items \.sc-item-label\{[^}]*white-space:nowrap", legacy), "legacy renderer unchanged"
