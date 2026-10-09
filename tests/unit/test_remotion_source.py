"""Source d'une scène Remotion : chemins, bloc `source`, fichiers, empreintes, manifeste v2, compatibilité v1 (Slice 05).

Domaine pur, aucune E/S. Contrat : `docs/remotion-source.md` §2-4.
"""

from __future__ import annotations

import copy

import pytest

from jarvis.domain import remotion_source as rs
from jarvis.domain.prefab import (
    PrefabDefinitionError, bundle_fingerprint, parse_bundle, parse_candidate, parse_manifest, parse_stored_bundle, renumber,
)
from tests.fakes.prefabs import candidate as html_candidate
from tests.fakes.remotion_scene import COMPOSITION, ENGINE, PNG_1X1, scene_candidate, scene_files


def bad(path, root=rs.MODULE_ROOT, extensions=rs.MODULE_EXTENSIONS):
    return rs.source_path_problem(path, root=root, extensions=extensions)


# ------------------------------------------------------------------ chemins


@pytest.mark.parametrize("path", [
    "src/Scene.tsx", "src/lib/Title.tsx", "src/a/b/c/d.ts", "src/theme.json", "src/x-y_z.1.js"])
def test_good_module_paths_are_accepted(path):
    assert bad(path) is None


@pytest.mark.parametrize("path,why", [
    ("../src/Scene.tsx", "relative POSIX|must live"),
    ("src/../../secret.ts", "traversal"),
    ("src/./Scene.tsx", "traversal"),
    ("src//Scene.tsx", "traversal"),
    ("/etc/passwd.ts", "relative POSIX"),
    ("C:/x/Scene.tsx", "relative POSIX"),
    ("src\\Scene.tsx", "relative POSIX"),
    ("src/Scene.tsx\x00.png", "relative POSIX"),
    ("src/.hidden.ts", "ASCII"),
    ("src/é.ts", "ASCII"),
    ("src/a b.ts", "ASCII"),
    ("src/node_modules/x.ts", "dependency tree is shared"),
    ("src/package.json", "dependency tree is shared"),
    ("src/tsconfig.json", "dependency tree is shared"),
    ("src/CON.ts", "reserved Windows"),
    ("src/nul.tsx", "reserved Windows"),
    ("src/x.ts.", "not allowed"),
    ("src/Scene.TSX", "extension"),
    ("src/Scene.css", "extension"),
    ("src/Scene", "extension"),
    ("public/a.png", "must live under src/"),
    ("lib/x.ts", "must live under src/"),
    ("src/" + "a/" * 8 + "x.ts", "deeper"),
    ("src/" + "x" * 130 + ".ts", "longer"),
    ("src/" + "y" * 70 + ".ts", "segment"),
    ("", "non-empty"),
    (None, "non-empty"),
    (7, "non-empty"),
], ids=lambda value: str(value)[:30])
def test_unsafe_module_paths_are_refused(path, why):
    problem = bad(path)
    assert problem is not None and any(word in problem for word in why.split("|")), problem


def test_asset_paths_have_their_own_root_and_extensions():
    assert bad("public/dot.png", rs.ASSET_ROOT, rs.ASSET_EXTENSIONS) is None
    assert bad("public/run.exe", rs.ASSET_ROOT, rs.ASSET_EXTENSIONS)
    assert bad("src/dot.png", rs.ASSET_ROOT, rs.ASSET_EXTENSIONS)
    assert bad("public/../src/Scene.tsx", rs.ASSET_ROOT, rs.ASSET_EXTENSIONS)


def test_case_collisions_and_file_folder_conflicts_are_reported():
    assert rs.path_set_problems(["src/Scene.tsx", "src/scene.tsx"])
    assert rs.path_set_problems(["src/a", "src/a/b.ts"])
    assert rs.path_set_problems(["src/a.ts", "src/lib/a.ts", "public/a.png"]) == []


# ------------------------------------------------------------------ bloc source


def block_dict(**changes):
    block = copy.deepcopy(scene_candidate()["manifest"]["source"])
    block.update(changes)
    return block


def test_the_source_block_round_trips():
    raw = block_dict()
    block = rs.parse_source_block(raw)
    assert block.to_dict() == raw
    assert block.entry == "src/Scene.tsx" and block.composition.fps == 30
    assert block.modules == ("src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json") and block.assets == ("public/dot.png",)


@pytest.mark.parametrize("changes,fragment", [
    ({"format": "html"}, "source.format"),
    ({"engine": {"name": "remotion"}}, "source.engine"),
    ({"engine": {**ENGINE.to_dict(), "version": "4.0"}}, "version"),
    ({"engine": {**ENGINE.to_dict(), "name": "slidecar"}}, "name"),
    ({"engine": {**ENGINE.to_dict(), "lock_sha256": "abc"}}, "lock_sha256"),
    ({"composition": {**COMPOSITION.to_dict(), "width": 0}}, "width"),
    ({"composition": {**COMPOSITION.to_dict(), "fps": 500}}, "fps"),
    ({"composition": {**COMPOSITION.to_dict(), "duration_in_frames": 0}}, "duration_in_frames"),
    ({"composition": {**COMPOSITION.to_dict(), "id": "9bad"}}, "composition.id"),
    ({"composition": {**COMPOSITION.to_dict(), "fps": True}}, "fps"),
    ({"entry": "src/lib/Title.tsx2"}, "source.entry"),
    ({"entry": "src/theme.json"}, "default-exports"),
    ({"entry": "src/Missing.tsx"}, "one of source.modules"),
    ({"modules": ["src/theme.json", "src/Scene.tsx"]}, "sorted"),
    ({"modules": ["src/Scene.tsx", "src/Scene.tsx"]}, "sorted"),
    ({"modules": ["src/Scene.tsx", "../x.ts"]}, "source.modules[1]"),
    ({"assets": ["public/run.exe"]}, "source.assets[0]"),
    ({"modules": "src/Scene.tsx"}, "source.modules"),
    ({"modules": ["src/Scene.tsx"] + [f"src/m{i:02d}.ts" for i in range(rs.MAX_MODULES)]}, "at most"),
])
def test_bad_source_blocks_are_refused_with_a_path(changes, fragment):
    with pytest.raises(rs.RemotionSourceError) as caught:
        rs.parse_source_block(block_dict(**changes))
    assert fragment in " ".join(caught.value.errors), caught.value.errors


def test_the_source_block_has_a_closed_key_set():
    with pytest.raises(rs.RemotionSourceError):
        rs.parse_source_block({**block_dict(), "extra": 1})
    with pytest.raises(rs.RemotionSourceError):
        rs.parse_source_block("src/Scene.tsx")


# ------------------------------------------------------------------ fichiers et empreintes


def parsed(files=None):
    candidate = scene_candidate(files=files) if files else scene_candidate()
    return parse_candidate(candidate)


def test_a_valid_candidate_becomes_a_bundle_with_every_file_as_bytes():
    bundle = parsed()
    assert bundle.is_remotion and bundle.manifest.schema_version == 2
    assert set(bundle.sources) == {"src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json", "public/dot.png"}
    assert bundle.sources["public/dot.png"] == PNG_1X1
    assert (bundle.template, bundle.style, bundle.behavior) == ("", "", "")
    source = bundle.remotion_source()
    assert source.text("src/lib/Title.tsx").startswith("import React")
    assert list(source.module_texts()) == ["src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json"]


def test_files_must_match_the_manifest_exactly():
    raw = scene_candidate()
    extra = copy.deepcopy(raw)
    extra["sources"]["src/Sneaky.ts"] = "export {}"
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_candidate(extra)
    assert "Sneaky" not in str(caught.value) or "not declared" in str(caught.value)
    source = parse_candidate(raw).manifest.source
    with pytest.raises(rs.RemotionSourceError) as caught:
        rs.parse_source(source, {"src/Scene.tsx": b"x"})
    assert any("missing" in item for item in caught.value.errors)
    with pytest.raises(rs.RemotionSourceError) as caught:
        rs.parse_source(source, {**parse_candidate(raw).sources, "src/Sneaky.ts": b"x"})
    assert any("not declared" in item for item in caught.value.errors)


@pytest.mark.parametrize("name,content,fragment", [
    ("src/lib/Title.tsx", "x" * (rs.MAX_MODULE_BYTES + 1), "at most"),
    ("src/lib/Title.tsx", "a\x00b", "NUL"),
    ("src/lib/Title.tsx", "ok", None),
], ids=["oversize", "nul", "fine"])
def test_module_size_and_content_bounds(name, content, fragment):
    files = {**scene_files(), name: content}
    if fragment is None:
        assert parsed(files)
        return
    with pytest.raises(PrefabDefinitionError) as caught:
        parsed(files)
    assert fragment in " ".join(caught.value.errors)


def test_oversize_assets_and_totals_are_refused():
    big = {**scene_files(), "public/big.png": b"0" * (rs.MAX_ASSET_BYTES + 1)}
    with pytest.raises(PrefabDefinitionError) as caught:
        parsed(big)
    assert "public/big.png" in " ".join(caught.value.errors)
    many = {**scene_files()}
    for index in range(5):
        many[f"public/a{index}.png"] = b"0" * (rs.MAX_ASSET_BYTES - 1)
    with pytest.raises(PrefabDefinitionError) as caught:
        parsed(many)
    assert "total" in " ".join(caught.value.errors)


def test_invalid_utf8_module_is_refused_before_it_reaches_a_compiler():
    source = parse_candidate(scene_candidate()).manifest.source
    files = dict(parse_candidate(scene_candidate()).sources)
    files["src/theme.json"] = b"\xff\xfe\x00"
    with pytest.raises(rs.RemotionSourceError):
        rs.parse_source(source, files)
    files["src/theme.json"] = b"\xff\xfe{}"
    with pytest.raises(rs.RemotionSourceError) as caught:
        rs.parse_source(source, files)
    assert "UTF-8" in " ".join(caught.value.errors)


@pytest.mark.parametrize("path", ["../escape.ts", "src/../../escape.ts", "src/node_modules/evil.ts", "src/package.json",
                                  "C:/win.ts", "src\\win.ts"])
def test_path_traversal_in_a_candidate_is_refused(path):
    files = {**scene_files(), path: "export {}"}
    with pytest.raises(PrefabDefinitionError):
        parse_candidate(scene_candidate(files=files))


def test_the_digest_depends_on_paths_and_bytes_only():
    a = parsed().remotion_source()
    reordered = dict(reversed(list(scene_files().items())))
    assert parsed(reordered).remotion_source().digest == a.digest
    changed = parsed(scene_files(" ")).remotion_source().digest
    assert changed != a.digest
    renamed = {("src/lib/Heading.tsx" if k == "src/lib/Title.tsx" else k): v for k, v in scene_files().items()}
    renamed["src/Scene.tsx"] = renamed["src/Scene.tsx"].replace("./lib/Title", "./lib/Heading")
    assert parsed(renamed).remotion_source().digest != a.digest


def test_the_digest_ignores_the_prefab_identity_and_version():
    one = parse_candidate(scene_candidate("presentation-studio.p000000000001.s000000000001"))
    two = parse_candidate(scene_candidate("presentation-studio.p000000000002.s000000000002"))
    assert one.remotion_source().digest == two.remotion_source().digest
    assert one.fingerprint() != two.fingerprint()  # the bundle fingerprint covers the manifest (id)


def test_two_scenes_may_use_the_same_file_names():
    one = parse_candidate(scene_candidate("presentation-studio.p000000000001.s000000000001"))
    two = parse_candidate(scene_candidate("presentation-studio.p000000000001.s000000000002",
                                          files={**scene_files(), "src/lib/Title.tsx": "export const Title = () => null;\n"}))
    assert set(one.sources) == set(two.sources)
    assert one.sources["src/Scene.tsx"] == two.sources["src/Scene.tsx"]
    assert one.sources["src/lib/Title.tsx"] != two.sources["src/lib/Title.tsx"]
    assert one.remotion_source().digest != two.remotion_source().digest


def test_the_isolation_hook_runs_on_every_parse(monkeypatch):
    seen = []

    def guard(source):
        seen.append(source.digest)
        return ["import 'fs' is forbidden"] if "fs" in source.text("src/theme.json") else []

    monkeypatch.setattr(rs, "SOURCE_GUARDS", (guard,))
    parsed()
    assert len(seen) == 1
    with pytest.raises(PrefabDefinitionError) as caught:
        parsed({**scene_files(), "src/theme.json": '{"fs": 1}'})
    assert "forbidden" in str(caught.value)


def test_candidate_decoding_rejects_bad_assets():
    assert rs.decode_candidate_files({"src/a.ts": "x"}, {"public/a.png": "AAAA"}) == {"src/a.ts": b"x", "public/a.png": b"\x00\x00\x00"}
    for assets in ({"public/a.png": "not base64!"}, {"public/a.png": 5}, {"src/a.ts": "AAAA"}, ["x"]):
        with pytest.raises(rs.RemotionSourceError):
            rs.decode_candidate_files({"src/a.ts": "x"}, assets)
    with pytest.raises(rs.RemotionSourceError):
        rs.decode_candidate_files({"src/a.ts": 5}, {})
    with pytest.raises(rs.RemotionSourceError):
        rs.decode_candidate_files("nope", {})


# ------------------------------------------------------------------ manifeste v2 et compatibilité v1


def test_a_v2_manifest_has_no_files_key_and_no_frame_events():
    raw = scene_candidate()["manifest"]
    assert "files" not in raw and raw["schema_version"] == 2
    assert parse_manifest(raw).source is not None
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_manifest({**raw, "files": {"template": "template.html", "style": "style.css", "behavior": "behavior.js"}})
    assert "unknown fields" in str(caught.value)
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_manifest({**raw, "events": {"go": {"class": "notify", "payload": {"type": "object", "properties": {}}}}})
    assert "frame events" in str(caught.value)
    missing = {key: value for key, value in raw.items() if key != "source"}
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_manifest(missing)
    assert "missing fields" in str(caught.value)


def test_schema_versions_stay_closed_per_version():
    html = html_candidate()["manifest"]
    assert parse_manifest(html).source is None
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_manifest({**html, "source": {}})  # a v1 manifest cannot smuggle a source block
    assert "unknown fields" in str(caught.value)
    for version in (0, 3, True, "2", 2.0):
        with pytest.raises(PrefabDefinitionError):
            parse_manifest({**scene_candidate()["manifest"], "schema_version": version})


def test_a_v2_manifest_cannot_be_parsed_as_an_html_bundle():
    raw = scene_candidate()["manifest"]
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_bundle(raw, "<div></div>", "", "")
    assert "Remotion source" in str(caught.value)


def test_html_bundles_keep_their_fingerprint_and_their_shape():
    """Régression de compatibilité : l'empreinte d'un prefab HTML (donc `publication.json` et `catalog.lock.json`) ne bouge pas."""

    raw = html_candidate()
    bundle = parse_bundle(raw["manifest"], raw["template"], raw["style"], raw["behavior"])
    assert bundle.sources == {} and not bundle.is_remotion
    assert bundle.fingerprint() == bundle_fingerprint(raw["manifest"], raw["template"], raw["style"], raw["behavior"])
    assert set(bundle.files()) == {"template", "style", "behavior"}
    assert parse_stored_bundle(raw["manifest"], raw["template"], raw["style"], raw["behavior"]).fingerprint() == bundle.fingerprint()
    with pytest.raises(PrefabDefinitionError):
        bundle.remotion_source()
    assert parse_candidate(raw).fingerprint() == bundle.fingerprint()


def test_renumbering_changes_the_fingerprint_with_the_version_and_keeps_the_sources():
    bundle = parse_candidate(scene_candidate())
    numbered = renumber(bundle, 5)
    assert numbered.manifest.version == 5 and numbered.sources == bundle.sources
    assert numbered.fingerprint() != bundle.fingerprint()
    assert renumber(bundle, 5).fingerprint() == numbered.fingerprint()


def test_a_remotion_candidate_has_its_own_closed_shape():
    raw = scene_candidate()
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_candidate({**raw, "template": "<div></div>"})
    assert "exactly" in str(caught.value)
    with pytest.raises(PrefabDefinitionError):
        parse_candidate({"manifest": raw["manifest"], "sources": raw["sources"]})
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_candidate({**raw, "sources": {**raw["sources"], "src/Scene.tsx": 5}})
    assert "string" in str(caught.value)


def test_the_candidate_builder_is_canonical():
    one = scene_candidate()
    two = scene_candidate(files=dict(reversed(list(scene_files().items()))))
    assert one["manifest"]["source"]["modules"] == sorted(one["manifest"]["source"]["modules"])
    assert one == two
    assert set(one["assets"]) == {"public/dot.png"} and set(one["sources"]) == {"src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json"}
