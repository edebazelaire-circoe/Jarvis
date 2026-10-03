"""Catalogue de base livré (prefab-foundation, Slices 05-06) : `jarvis.window`, `jarvis.document`, `jarvis.table`,
`jarvis.checklist`.

Contrat : `docs/prefabs.md` › *Base catalogue* (entrées et événements de
chaque famille, règle d'extension) et handoff doc 06 D-FAMILIES. Chaque
version livrée : manifeste valide, exemple valide, publication `base`/`system`
à la bonne empreinte, entrée du verrou ; Core la trouve par ses alias ; elle
compose la coquille partagée au lieu de la recopier. Le comportement de chaque
prefab dans le shim est prouvé par `test_prefab_base_behaviors_js.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import jarvis
from jarvis.adapters.file_prefab_library import FilePrefabLibrary, FilePrefabRuntime
from jarvis.core.prefab_service import PrefabService
from jarvis.domain.prefab import (
    MAX_MANIFEST_BYTES, CatalogLock, CreatorActor, EventClass, LockEntry, PrefabInstanceRef, ProvenanceOrigin,
    Publication, check_lock_coverage, decode_json_text, parse_bundle, validate_value,
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
    # Slice 06 (SLICE.md › Slice 00 contract, doc 06 R2) ; données et événements : test_prefab_checklist*.py.
    "jarvis.checklist": {"props": {"accent", "show_progress"}, "data": {"items"},
                         "events": {"item_toggled": "state", "checklist_completed": "notify"}},
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
                         {"body": ""} if prefab_id == "jarvis.document" else
                         {"items": []} if prefab_id == "jarvis.checklist" else {})):
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



# --- Script de publication : gardes indépendantes, régénération d'une v1 non livrée (reprise QA S05 F6) ---

STAMP = "2026-10-03T00:00:00Z"


@pytest.fixture
def published(tmp_path: Path) -> Path:
    """Paquet de scratch : `jarvis.window@1` publié et verrouillé par le script lui-même."""

    package = tmp_path / "base"
    folder = package / "jarvis.window" / "1"
    folder.mkdir(parents=True)
    for name in ("manifest.json", "template.html", "style.css", "behavior.js"):
        (folder / name).write_bytes((PACKAGE / "jarvis.window" / "1" / name).read_bytes())
    (package / "catalog.lock.json").write_bytes(CatalogLock().render().encode())
    writes, _ = lock_base_prefabs.plan(package, STAMP)
    for path, text in writes.items():
        path.write_bytes(text.encode())
    assert lock_base_prefabs.plan(package, STAMP)[0] == {}
    return package


def _edit(package: Path) -> str:
    """Modifie le style de la version ; rend sa nouvelle empreinte."""

    folder = package / "jarvis.window" / "1"
    (folder / "style.css").write_bytes((folder / "style.css").read_bytes() + b".edited{}\n")
    return lock_base_prefabs.fingerprint_of(folder)


def _publication_path(package: Path) -> Path:
    return package / "jarvis.window" / "1" / "publication.json"


def _republish(package: Path, digest: str) -> None:
    """Réécrit `publication.json` à `digest` (ce que la garde de publication devrait voir passer)."""

    data = json.loads(_publication_path(package).read_text(encoding="utf-8"))
    data["fingerprint"] = digest
    _publication_path(package).write_bytes(Publication.decode_text(json.dumps(data)).render().encode())


def _relock(package: Path, entries) -> None:
    (package / "catalog.lock.json").write_bytes(CatalogLock(tuple(entries)).render().encode())


def test_the_publication_guard_alone_refuses_an_edit_in_place(published):
    digest = _edit(published)
    _relock(published, [LockEntry("jarvis.window", 1, digest)])  # le verrou, lui, laisserait passer
    with pytest.raises(lock_base_prefabs.LockError, match="edited after publication"):
        lock_base_prefabs.plan(published, STAMP)


def test_the_lock_guard_alone_refuses_an_edit_in_place(published):
    digest = _edit(published)
    _republish(published, digest)  # la publication, elle, laisserait passer
    with pytest.raises(lock_base_prefabs.LockError, match="differs from catalog.lock.json"):
        lock_base_prefabs.plan(published, STAMP)


def test_an_unreleased_version_regenerates_only_with_both_its_publication_and_lock_entry_deleted(published):
    old = CatalogLock.decode_text((published / "catalog.lock.json").read_text(encoding="utf-8"))
    publication = _publication_path(published).read_bytes()
    digest = _edit(published)
    _publication_path(published).unlink()  # publication seule supprimée : le verrou refuse
    with pytest.raises(lock_base_prefabs.LockError, match="differs from catalog.lock.json"):
        lock_base_prefabs.plan(published, STAMP)
    _publication_path(published).write_bytes(publication)
    _relock(published, [])  # entrée seule supprimée : la publication refuse
    with pytest.raises(lock_base_prefabs.LockError, match="edited after publication"):
        lock_base_prefabs.plan(published, STAMP)
    _publication_path(published).unlink()  # les deux : le chemin documenté
    writes, lock = lock_base_prefabs.plan(published, STAMP)
    assert sorted(path.name for path in writes) == ["catalog.lock.json", "publication.json"]
    assert [entry.fingerprint for entry in lock.entries] == [digest] != [entry.fingerprint for entry in old.entries]
    assert Publication.decode_text(writes[_publication_path(published)]).fingerprint == digest


@pytest.mark.parametrize("target", ["catalog.lock.json", "jarvis.window/1/publication.json"])
def test_a_generated_file_with_cr_is_refused(published, target):
    path = published / target
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(lock_base_prefabs.LockError, match="contains CR"):
        lock_base_prefabs.plan(published, STAMP)


def test_check_reports_mismatch_and_missing_files_and_never_writes(published, monkeypatch, capsys):
    monkeypatch.setattr(lock_base_prefabs, "PACKAGE", published)
    monkeypatch.setattr(lock_base_prefabs, "ROOT", published.parent)
    snapshot = lambda: {path: path.read_bytes() for path in published.rglob("*") if path.is_file()}  # noqa: E731
    assert lock_base_prefabs.main(["--check"]) == 0
    _edit(published)
    before = snapshot()
    assert lock_base_prefabs.main(["--check"]) == 2  # publication/verrou en désaccord : refus, rien d'écrit
    assert "refused:" in capsys.readouterr().err and snapshot() == before
    _publication_path(published).unlink()
    _relock(published, [])
    before = snapshot()
    assert lock_base_prefabs.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "missing: base/jarvis.window/1/publication.json" in out and "missing: base/catalog.lock.json" in out
    assert snapshot() == before
    assert lock_base_prefabs.main(["--published-at", STAMP]) == 0
    assert lock_base_prefabs.main(["--check"]) == 0


@pytest.mark.parametrize(("query", "expected"), [
    ("tableau", "jarvis.table"), ("document", "jarvis.document"), ("fenêtre", "jarvis.window"),
    ("Fenêtre", "jarvis.window"), ("lecture", "jarvis.document"), ("view_table", "jarvis.table"),
    ("checklist", "jarvis.checklist"), ("liste de contrôle", "jarvis.checklist"), ("todo", "jarvis.checklist"),
])
async def test_core_search_finds_each_family_by_alias(service, query, expected):
    rows = await service.search(query, class_filter="base")
    assert rows and rows[0].prefab_id == expected


async def test_core_lists_every_family_healthy_and_validates_their_samples(service):
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
    assert set(rows["jarvis.checklist"].event_names) == {"item_toggled", "checklist_completed"}


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


def _rule(css: str, selector: str) -> str:
    """Déclarations (espaces normalisés) de toutes les règles dont la liste de sélecteurs contient `selector`."""

    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = [re.sub(r"\s*([:;,])\s*", r"\1", " ".join(declarations.split()))
             for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", body)
             if selector in [part.strip() for part in selectors.split(",")]]
    assert found, f"no rule for {selector!r}"
    return ";".join(found)


def test_window_ref_keeps_its_width_and_the_label_wraps_beside_it():
    """Reprise QA S05 F3 : `.win-ref` ne rétrécit plus (« r… », « docs/lo… ») ; le libellé passe à la
    ligne."""

    style = (PACKAGE / "jarvis.window" / "1" / "style.css").read_text(encoding="utf-8")
    ref = _rule(style, ".win-ref")
    assert "flex:none" in ref and "max-width:45%" in ref and "text-overflow:ellipsis" in ref
    assert "min-width:0" in _rule(style, ".win-main") and "flex:1 1 auto" in _rule(style, ".win-main")


def test_window_layout_matches_the_legacy_window_body_scrolls_items_pinned():
    """Reprise QA S05 F4 : même mise en page que `.sc-window` — le corps défile et s'efface, les entrées en bas."""

    folder = PACKAGE / "jarvis.window" / "1"
    style = (folder / "style.css").read_text(encoding="utf-8")
    template = (folder / "template.html").read_text(encoding="utf-8")
    win = _rule(style, ".win")
    assert "position:fixed" in win and "inset:0" in win and "flex-direction:column" in win
    assert "flex:1 1 auto" in _rule(style, ".win-body") and "min-height:0" in _rule(style, ".win-body")
    assert "overflow:hidden auto" in _rule(style, ".win-items") and "overflow:hidden auto" in _rule(style, ".win-body")
    items = _rule(style, ".win-items")
    assert "flex:none" in items and "max-height" not in items  # cadre à sa hauteur naturelle : rien n'est plafonné
    assert _rule(style, ".win[data-clamped] .win-items") == \
        "max-height:max(55%,calc(100% - var(--win-body-natural,0px)))"
    assert "mask-image" in _rule(style, ".win-body[data-more]")
    # La hauteur rapportée reste la hauteur naturelle : le corps du document ne contient que la cale.
    assert template.index('id="win-sizer"') > template.index("</main>")
    assert "max-height:none!important" in _rule(style, ".win[data-measure]>*")


def test_no_base_prefab_removes_the_keyboard_focus_ring():
    """Reprise QA S05 F5 : l'anneau `:focus-visible` de la coquille n'est retiré par aucun prefab de base."""

    for prefab_id in FAMILIES:
        style = (PACKAGE / prefab_id / "1" / "style.css").read_text(encoding="utf-8")
        style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
        for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
            if ":focus" in selectors:
                assert not re.search(r"outline\s*:\s*(none|0)\b", declarations), f"{prefab_id}: {selectors.strip()}"


def test_base_prefab_colours_come_from_shell_tokens():
    """Reprise QA S05 F8 : pas de couleur écrite en dur dans un prefab de base (les jetons `--jv-*` existent)."""

    for prefab_id in FAMILIES:
        style = (PACKAGE / prefab_id / "1" / "style.css").read_text(encoding="utf-8")
        style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
        style = re.sub(r'url\("data:[^"]*"\)', "", style)
        style = re.sub(r"(-webkit-)?mask-image:[^;}]*", "", style)  # un masque ne porte que l'alpha
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", style), prefab_id
    for token in ("--jv-veil", "--jv-title", "--jv-link"):
        assert re.search(re.escape(token) + r"\s*:", SHELL), token
