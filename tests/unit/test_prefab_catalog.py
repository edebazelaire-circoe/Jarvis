"""Semantic catalog of prefabs (Slice 17 of jarvis-remotion-presentation-integration): manifest v3 `catalog` block, contract
derived at read for v1 / v2, immutable versions, old readers, library scan, base lock, service filters, Core route.

Contract: `docs/prefabs.md` > *Semantic catalog (manifest v3)*.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path

import aiohttp
import pytest

from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from jarvis.domain import prefab as p
from jarvis.domain.prefab_catalog import SemanticType, derive_catalog, matches, parse_catalog_block
from jarvis.domain.presentation_studio_engine import Engine, Support
from jarvis.ports.prefabs import PrefabStoreError
from tests.fakes.capture_stack import TOKEN, CaptureStack
from tests.fakes.prefabs import candidate as html_candidate, install_version
from tests.fakes.remotion_scene import scene_candidate

NOW = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
PACKAGE = Path(p.__file__).resolve().parents[1] / "prefabs" / "base"

CATALOG = {"type": "composition", "compatibility": {"remotion": "native", "slidecar": "adapter"},
           "stack": ["react", "remotion", "typescript"],
           "dependencies": [{"name": "remotion", "version": "4.0.534"}, {"name": "@remotion/player", "version": "^4.0.0"}],
           "license": "MIT",
           "upstream": {"name": "remotion-dev/template", "url": "https://github.com/remotion-dev/template", "ref": "v4"}}


def html_v3(**changes):
    raw = html_candidate()
    raw["manifest"] = {**raw["manifest"], "schema_version": 3, "catalog": copy.deepcopy({**CATALOG, "type": "component", "compatibility": {"slidecar": "native", "remotion": "adapter"}}),
                       **changes}
    return raw


def scene_v3(prefab_id="test.scene", **changes):
    raw = scene_candidate(prefab_id)
    raw["manifest"] = {**raw["manifest"], "schema_version": 3, "catalog": copy.deepcopy(CATALOG), **changes}
    return raw


def errors_of(raw):
    with pytest.raises(p.PrefabDefinitionError) as caught:
        p.parse_candidate(raw)
    return " | ".join(caught.value.errors)


# ------------------------------------------------------------------ vocabulary and block

def test_the_vocabulary_is_fixed_and_not_per_engine():
    assert [t.value for t in SemanticType] == ["component", "composition", "page", "presentation", "asset"]
    assert [e.value for e in Engine] == ["slidecar", "remotion"]


def test_a_v3_html_and_a_v3_remotion_candidate_parse_with_the_same_block_shape():
    html, scene = p.parse_candidate(html_v3()), p.parse_candidate(scene_v3())
    assert html.manifest.schema_version == 3 and not html.is_remotion
    assert scene.manifest.schema_version == 3 and scene.is_remotion
    for bundle in (html, scene):
        view = bundle.manifest.catalog_view()
        assert view["declared"] is True and set(view) >= {"type", "compatibility", "stack", "dependencies", "license",
                                                         "upstream", "parameters"}
    view = scene.manifest.catalog_view()
    assert view["type"] == "composition"
    assert view["compatibility"] == {"slidecar": "adapter", "remotion": "native"}
    assert view["dependencies"][1] == {"name": "@remotion/player", "version": "^4.0.0"}
    assert view["upstream"]["url"].startswith("https://") and view["license"] == "MIT"


def test_an_engine_the_block_does_not_declare_reads_unsupported():
    block, errors = parse_catalog_block({"type": "page", "compatibility": {"remotion": "native"}, "stack": ["html"]})
    assert errors == []
    view = derive_catalog(block=block, family="x", remotion=False)
    assert view["compatibility"] == {"slidecar": "unsupported", "remotion": "native"}
    assert view["license"] is None and view["upstream"] is None and view["dependencies"] == []


@pytest.mark.parametrize("change,needle", [
    ({"type": "widget"}, "catalog.type"),
    ({"type": "Component"}, "catalog.type"),
    ({"compatibility": {}}, "catalog.compatibility"),
    ({"compatibility": {"flash": "native"}}, "catalog.compatibility"),
    ({"compatibility": {"remotion": "maybe"}}, "catalog.compatibility"),
    ({"stack": []}, "catalog.stack"),
    ({"stack": ["React"]}, "catalog.stack"),
    ({"stack": ["react", "react"]}, "catalog.stack"),
    ({"dependencies": [{"name": "remotion"}]}, "catalog.dependencies[0]"),
    ({"dependencies": [{"name": "remotion", "version": ""}]}, "catalog.dependencies[0]"),
    ({"dependencies": [{"name": "a", "version": "1"}, {"name": "a", "version": "2"}]}, "listed once"),
    ({"license": "x" * 80}, "catalog.license"),
    ({"license": "MIT\nGPL"}, "catalog.license"),
    ({"upstream": {"name": "x", "url": "javascript:alert(1)"}}, "catalog.upstream"),
    ({"upstream": {"name": "x"}}, "catalog.upstream"),
    ({"upstream": {"name": "x", "url": "https://a.b", "verified": True}}, "catalog.upstream"),
    ({"surprise": 1}, "unknown fields"),
])
def test_a_bad_catalog_block_is_refused_with_its_path(change, needle):
    assert needle in errors_of(scene_v3(catalog={**CATALOG, **change}))


def test_a_missing_required_field_is_refused_not_defaulted():
    for key in ("type", "compatibility", "stack"):
        block = {k: v for k, v in CATALOG.items() if k != key}
        assert "missing fields" in errors_of(scene_v3(catalog=block))


def test_v1_and_v2_manifests_cannot_carry_a_catalog_and_v3_must():
    html = html_candidate()
    html["manifest"]["catalog"] = CATALOG
    assert "needs schema_version 3" in errors_of(html)
    scene = scene_candidate("test.scene")
    scene["manifest"]["catalog"] = CATALOG
    assert "needs schema_version 3" in errors_of(scene)
    bare = html_candidate()
    bare["manifest"]["schema_version"] = 3
    assert "catalog" in errors_of(bare)


def test_a_v3_manifest_carries_exactly_one_of_files_or_source():
    both = scene_v3()
    both["manifest"]["files"] = p.FILES
    assert "exactly one of files" in errors_of(both)
    neither = html_v3()
    del neither["manifest"]["files"]
    assert "exactly one of files" in errors_of(neither)


def test_schema_version_4_is_still_unknown():
    raw = html_v3()
    raw["manifest"]["schema_version"] = 4
    assert errors_of(raw) == "a catalog block needs schema_version 3 (this manifest is version 4)"
    bare = html_candidate()
    bare["manifest"]["schema_version"] = 4
    assert errors_of(bare) == "schema: must be 'jarvis.prefab' version 1 or 2 or 3"


def test_the_block_is_bounded_in_dependencies_stack_and_url_schemes():
    many = [{"name": f"pkg-{i}", "version": "1.0.0"} for i in range(33)]
    assert "at most 32" in errors_of(scene_v3(catalog={**CATALOG, "dependencies": many}))
    ok = [{"name": f"pkg-{i}", "version": "1.0.0"} for i in range(32)]
    assert p.parse_candidate(scene_v3(catalog={**CATALOG, "dependencies": ok})).manifest.catalog.dependencies[31].name == "pkg-31"
    assert "1..12" in errors_of(scene_v3(catalog={**CATALOG, "stack": [f"t{i}" for i in range(13)]}))
    assert p.parse_candidate(scene_v3(catalog={**CATALOG, "stack": [f"t{i}" for i in range(12)]})).manifest.catalog.stack[11] == "t11"
    for url in ("ftp://host/x", "data:text/html,<b>x</b>", "file:///etc/passwd", "https://"):
        assert "catalog.upstream" in errors_of(scene_v3(catalog={**CATALOG, "upstream": {"name": "x", "url": url}})), url


@pytest.mark.parametrize("compat", [{"remotion": "unsupported", "slidecar": "adapter"}, {"slidecar": "native"},
                                    {"remotion": "native", "slidecar": "native"}])
def test_a_remotion_source_cannot_declare_what_its_body_contradicts(compat):
    assert "Remotion source" in errors_of(scene_v3(catalog={**CATALOG, "compatibility": compat}))


@pytest.mark.parametrize("compat", [{"remotion": "native", "slidecar": "native"}, {"remotion": "adapter", "slidecar": "unsupported"},
                                    {"remotion": "adapter"}, {"remotion": "unsupported"}])
def test_an_html_bundle_cannot_declare_what_its_body_contradicts(compat):
    block = {**CATALOG, "type": "component", "compatibility": compat}
    assert "HTML bundle" in errors_of(html_v3(catalog=block))


def test_the_consistent_declarations_are_accepted_both_ways():
    for compat in ({"remotion": "adapter", "slidecar": "adapter"}, {"remotion": "native"}):
        assert p.parse_candidate(scene_v3(catalog={**CATALOG, "compatibility": compat})).is_remotion
    for compat in ({"slidecar": "native"}, {"slidecar": "adapter", "remotion": "adapter"}, {"slidecar": "native", "remotion": "unsupported"}):
        assert not p.parse_candidate(html_v3(catalog={**CATALOG, "type": "component", "compatibility": compat})).is_remotion


# ------------------------------------------------------------------ derived at read (backfill, nothing rewritten)

def test_a_legacy_html_prefab_reads_as_a_component_native_in_slidecar_and_unsupported_in_remotion():
    view = p.parse_candidate(html_candidate()).manifest.catalog_view()
    assert view["declared"] is False and view["type"] == "component"
    assert view["compatibility"] == {"slidecar": "native", "remotion": "unsupported"}
    assert view["stack"] == ["html", "css", "javascript"] and view["license"] is None and view["upstream"] is None


def test_a_v2_remotion_source_reads_as_a_composition_native_in_remotion_only():
    view = p.parse_candidate(scene_candidate("test.scene")).manifest.catalog_view()
    assert view["declared"] is False and view["type"] == "composition"
    assert view["compatibility"] == {"slidecar": "unsupported", "remotion": "native"}
    assert view["stack"] == ["react", "remotion", "typescript"]


@pytest.mark.parametrize("family,expected", [("window", "component"), ("page", "page"), ("deck", "presentation"),
                                             ("media", "asset"), ("anything-else", "component")])
def test_legacy_family_maps_to_a_type_without_inventing_one(family, expected):
    assert derive_catalog(block=None, family=family, remotion=False)["type"] == expected


def test_parameters_are_the_declared_props_only():
    manifest = p.parse_candidate(html_candidate()).manifest
    names = [item["name"] for item in manifest.catalog_view()["parameters"]]
    assert names == list(manifest.props.properties) and names
    assert all("type" in item and "required" in item for item in manifest.catalog_view()["parameters"])


def test_filters_match_native_or_adapter_never_unsupported():
    view = derive_catalog(block=None, family="window", remotion=False)
    assert matches(view, engine="slidecar") and not matches(view, engine="remotion")
    assert matches(view, kind="component", stack="html") and not matches(view, kind="page")
    assert not matches(view, stack="react")


# ------------------------------------------------------------------ library scan, base lock, old readers

def test_every_shipped_prefab_reads_and_has_a_contract(tmp_path):
    """Library-scan compatibility: every version shipped in the package parses, and derives a complete catalog view."""

    library = FilePrefabLibrary(PACKAGE, tmp_path)
    scan = library.scan()
    assert scan.problems == () and scan.versions
    for item in scan.versions:
        files = library.read_version(item.root, item.prefab_id, item.version)
        bundle = p.parse_stored_bundle(p.decode_json_text(files.manifest, p.MAX_MANIFEST_BYTES, "manifest"),
                                       files.template, files.style, files.behavior)
        view = bundle.manifest.catalog_view()
        assert view["type"] in {t.value for t in SemanticType}, item
        assert set(view["compatibility"]) == {e.value for e in Engine}, item
        assert view["compatibility"]["slidecar"] == "native" and view["compatibility"]["remotion"] == "unsupported", item
        assert bundle.manifest.schema_version == 1, "a published base version is never rewritten"


def test_the_base_catalog_lock_is_untouched_by_the_catalog_contract():
    """No shipped manifest was rewritten for this Slice: the lock still names only schema_version 1 versions (see also
    `test_prefab_base_lock.py`, which fails on any drift)."""

    lock = json.loads((PACKAGE / "catalog.lock.json").read_text(encoding="utf-8"))
    for entry in lock["entries"]:
        manifest = json.loads((PACKAGE / entry["prefab_id"] / str(entry["version"]) / "manifest.json").read_text("utf-8"))
        assert manifest["schema_version"] == 1 and "catalog" not in manifest


def make_service(tmp_path):
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir()
    data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    return PrefabService(FilePrefabLibrary(package, data), clock=lambda: NOW), data


async def test_publishing_stays_immutable_and_a_v3_version_follows_a_v1_one(tmp_path):
    service, data = make_service(tmp_path)
    first = await service.save(html_candidate("test.counter"), actor="user")
    second = await service.save(html_v3(id="test.counter"), actor="user")
    assert (first.version, second.version) == (1, 2)
    folder = data / "prefabs" / "test.counter"
    v1 = json.loads((folder / "1" / "manifest.json").read_text("utf-8"))
    v2 = json.loads((folder / "2" / "manifest.json").read_text("utf-8"))
    assert v1["schema_version"] == 1 and "catalog" not in v1, "the published version was not rewritten"
    assert v2["schema_version"] == 3 and v2["catalog"]["type"] == "component"
    detail = await service.get("test.counter", 1)
    assert detail.to_dict(catalog=True)["catalog"]["declared"] is False
    assert "catalog" not in detail.to_dict()
    assert (await service.get("test.counter")).to_dict(catalog=True)["catalog"]["declared"] is True


async def test_an_old_reader_refuses_a_v3_version_without_crashing_and_reads_the_rest(tmp_path, monkeypatch):
    service, data = make_service(tmp_path)
    await service.save(html_candidate("test.counter"), actor="user")
    await service.save(html_v3(id="test.counter"), actor="user")
    monkeypatch.setattr(p, "MANIFEST_VERSIONS", (1, 2))  # the reader as it was before this Slice
    fresh = PrefabService(FilePrefabLibrary(tmp_path / "package", data), clock=lambda: NOW)
    detail = await fresh.get("test.counter")
    assert detail.entry.version == 1 and detail.latest_version == 1
    rows = {row["version"]: row for row in detail.history}
    assert rows[2]["status"] == "tampered" and "version" in rows[2]["problem"]
    assert (await fresh.search("counter"))  # the catalogue still lists the id


async def test_service_filters_by_type_engine_and_stack(tmp_path):
    service, _ = make_service(tmp_path)
    await service.save(html_v3(id="test.cmp"), actor="user")
    await service.save(scene_v3("test.scene"), actor="user")
    ids = lambda rows: sorted(row.prefab_id for row in rows)  # noqa: E731
    assert ids(await service.search(semantic_type="composition")) == ["test.scene"]
    assert "test.scene" in ids(await service.search(engine="slidecar"))  # adapter counts as compatible
    assert ids(await service.search(engine="remotion", stack="remotion")) == ["test.cmp", "test.scene"]
    assert "jarvis.counter" in ids(await service.search(engine="slidecar"))
    assert "jarvis.counter" not in ids(await service.search(engine="remotion"))
    assert ids(await service.search(stack="html")) == ["jarvis.counter"]
    for bad in ({"semantic_type": "widget"}, {"engine": "flash"}, {"stack": ""}):
        with pytest.raises(PrefabStoreError):
            await service.search(**bad)


async def test_the_row_the_brain_reads_does_not_grow_and_rows_never_carry_parameters(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path)
    await service.save(html_v3(id="test.cmp"), actor="user")
    calls = []
    real = p.PrefabManifest.catalog_view
    monkeypatch.setattr(p.PrefabManifest, "catalog_view", lambda self, **kw: (calls.append(kw), real(self, **kw))[1])
    plain = await service.search("counter")
    assert calls == [] and all(row.catalog is None for row in plain), "no contract computed unless asked"
    assert "catalog" not in plain[0].to_dict()
    rows = await service.search(with_catalog=True)
    assert rows and all(row.catalog is not None and "parameters" not in row.catalog for row in rows)
    assert calls and all(kw == {"parameters": False} for kw in calls)
    row = next(r for r in rows if r.prefab_id == "test.cmp")
    assert "catalog" in row.to_dict(catalog=True)
    detail = (await service.get("test.cmp")).to_dict(catalog=True)
    assert detail["catalog"]["parameters"], "parameters live in the detail response only"


# ------------------------------------------------------------------ Core route

AUTH = {"Authorization": f"Bearer {TOKEN}"}


async def test_core_route_extensions_filter_validate_and_stay_opt_in(tmp_path):
    stack = CaptureStack(tmp_path)
    library = tmp_path / "data" / "prefabs"
    install_version(library, "test.counter", 1)
    async with stack, aiohttp.ClientSession() as http:
        async def get(path, **kw):
            async with http.get(stack.core_url + path, headers=AUTH, **kw) as response:
                return response.status, await response.json(content_type=None)

        status, body = await get("/v1/prefabs")
        assert status == 200 and all("catalog" not in row for row in body["prefabs"])
        status, body = await get("/v1/prefabs", params={"catalog": "1"})
        rows = {row["id"]: row for row in body["prefabs"]}
        assert rows["test.counter"]["catalog"]["type"] == "component"
        assert all("parameters" not in row["catalog"] for row in rows.values())
        plain_size = len(json.dumps((await get("/v1/prefabs"))[1]))
        assert len(json.dumps(body)) - plain_size < 400 * len(rows), "a list row carries the contract, not the parameters"
        assert rows["jarvis.window"]["catalog"]["compatibility"] == {"slidecar": "native", "remotion": "unsupported"}
        status, body = await get("/v1/prefabs", params={"engine": "remotion"})
        assert status == 200 and body["prefabs"] == []
        status, body = await get("/v1/prefabs", params={"type": "component", "engine": "slidecar", "stack": "html",
                                                        "class": "custom"})
        assert [row["id"] for row in body["prefabs"]] == ["test.counter"]
        for params in ({"type": "widget"}, {"engine": "flash"}, {"catalog": "2"}, {"nope": "1"}):
            status, _ = await get("/v1/prefabs", params=params)
            assert status == 400, params
        status, body = await get("/v1/prefabs/test.counter", params={"catalog": "1"})
        assert status == 200 and body["catalog"]["parameters"] and "catalog" not in (await get("/v1/prefabs/test.counter"))[1]
        status, body = await get("/v1/prefabs/test.counter/1", params={"catalog": "1", "include_source": "1"})
        assert status == 200 and body["catalog"]["declared"] is False and "files" in body


# ------------------------------------------------------------------ Slice 18 : provenance vérifiée et licence du moteur

VERIFIED = {"name": "someone/demo", "url": "https://github.com/someone/demo", "license": "MIT", "commit": "a" * 40,
            "archive_sha256": "b" * 64, "imported_at": "2026-10-10T12:00:00Z", "changes": ["entry generated", "deps mapped"]}


def test_the_upstream_block_carries_the_importer_keys_and_the_runtime_licence_is_separate():
    block, errors = parse_catalog_block({**CATALOG, "upstream": VERIFIED, "runtime_license": "Remotion License"})
    assert errors == [] and block.upstream.verified and block.upstream.changes == ("entry generated", "deps mapped")
    assert block.license == "MIT" and block.runtime_license == "Remotion License"
    view = derive_catalog(block=block, family="scene", remotion=True)
    assert view["upstream"]["commit"] == "a" * 40 and view["upstream"]["changes"] == ["entry generated", "deps mapped"]
    assert view["runtime_license"] == "Remotion License" and view["license"] == "MIT"
    # un bloc déclaré à la main (sans les clés vérifiées) n'est pas « vérifié »
    declared, _ = parse_catalog_block({**CATALOG})
    assert declared.upstream.verified is False and derive_catalog(block=declared, family="scene", remotion=True)["runtime_license"] is None


@pytest.mark.parametrize("bad", [{"commit": "main"}, {"commit": "A" * 40}, {"archive_sha256": "b" * 63}, {"imported_at": "yesterday"},
                                 {"changes": "one line"}, {"changes": [""]}, {"changes": ["x"] * 17}, {"changes": [5]}])
def test_malformed_importer_keys_are_refused(bad):
    block, errors = parse_catalog_block({**CATALOG, "upstream": {**VERIFIED, **bad}})
    assert block is None and any("catalog.upstream" in item for item in errors)


def test_a_catalog_without_the_new_keys_reads_exactly_as_before():
    block, errors = parse_catalog_block(CATALOG)
    assert errors == [] and block.runtime_license == "" and block.upstream.changes == () and block.upstream.to_dict() == CATALOG["upstream"]
