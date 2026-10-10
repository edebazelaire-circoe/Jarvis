"""Vocabulaire pur de l'edition de source Remotion (handoff jarvis-remotion-presentation-integration, Slice 14).

`parse_source_edit` (clefs `sources`, `assets`, `restore_version`), `parse_remotion_edit` (formes et plafonds),
`compose_remotion_candidate` (fichiers ajoutes, remplaces, supprimes ; listes du manifeste recalculees), `format_diagnostics`.
"""

from __future__ import annotations

import base64
import json

import pytest

from jarvis.domain.prefab import PrefabRef, parse_candidate
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_reload import ReloadResult, ReloadStatus, parse_source_edit
from jarvis.domain.presentation_studio_remotion_edit import (
    MAX_EDIT_ASSETS_B64, candidate_files, compose_remotion_candidate, format_diagnostics, parse_remotion_edit,
)
from jarvis.domain.remotion_source import MAX_MODULE_BYTES, MAX_MODULES
from tests.fakes.remotion_scene import PNG_1X1, scene_candidate, scene_files

REQUEST = {"actor": "brain", "basis": {"variant_revision": 3}, "scene_id": "pss_000000000001"}


def request(files: dict, **extra) -> dict:
    return {**REQUEST, "files": files, **extra}


def invalid(files: dict) -> str:
    with pytest.raises(PresentationStudioError) as caught:
        parse_source_edit(request(files))
    assert caught.value.code is C.INVALID_PRESENTATION
    return caught.value.message


# ------------------------------------------------------------------ requete

def test_a_remotion_request_carries_sources_assets_and_deletions():
    parsed = parse_source_edit(request({"sources": {"src/Scene.tsx": "export default () => null", "src/old.ts": None},
                                        "assets": {"public/a.png": "AA==", "public/b.png": None}}, request_id="psq_0123456789ab"))
    assert parsed.targets_remotion and parsed.files == {} and parsed.restore is None
    assert parsed.sources == {"src/Scene.tsx": "export default () => null", "src/old.ts": None}
    assert parsed.assets == {"public/a.png": "AA==", "public/b.png": None} and parsed.request_id == "psq_0123456789ab"


def test_a_slidecar_request_is_unchanged():
    parsed = parse_source_edit(request({"style": "p{}", "manifest": {"id": "x"}}))
    assert not parsed.targets_remotion and parsed.files == {"style": "p{}", "manifest": {"id": "x"}} and parsed.sources == {}


def test_restore_version_stands_alone_and_names_a_pin():
    parsed = parse_source_edit(request({"restore_version": {"id": "presentation-studio.p0.s0", "version": 2}}))
    assert parsed.restore == PrefabRef("presentation-studio.p0.s0", 2) and parsed.files == {}
    assert "stands alone" in invalid({"restore_version": {"id": "a", "version": 1}, "sources": {"src/a.ts": "x"}})
    invalid({"restore_version": {"id": "a", "version": 0}})
    invalid({"restore_version": {"id": "", "version": 1}})
    invalid({"restore_version": {"id": "a", "version": 1, "extra": 1}})
    invalid({"restore_version": "a@1"})


@pytest.mark.parametrize("files", [
    {"style": "p{}", "sources": {"src/a.ts": "x"}},
    {"template": "<p>", "assets": {"public/a.png": "AA=="}},
    {"sources": {}},
    {"assets": {}, "manifest": None},
    {"sources": []},
    {"sources": {"src/a.ts": 5}},
    {"sources": {"": "x"}},
    {"sources": {"x" * 200: "x"}},
    {"assets": {"public/a.png": 5}},
    {"assets": {"public/a.png": "A" * (MAX_EDIT_ASSETS_B64 + 1)}},
    {"sources": {"src/a.ts": "x" * (MAX_MODULE_BYTES + 1)}},
    {"sources": {f"src/m{i}.ts": "x" for i in range(MAX_MODULES + 1)}},
    {"script": "x"},
])
def test_malformed_remotion_requests_are_coded_errors(files):
    invalid(files)


# ------------------------------------------------------------------ composition

def base() -> tuple[dict, dict[str, bytes]]:
    candidate = scene_candidate()
    bundle = parse_candidate(candidate)
    return json.loads(json.dumps(candidate["manifest"])), dict(bundle.sources)


def compose(manifest_files, **edits):
    manifest, files = manifest_files
    return compose_remotion_candidate(manifest, files, sources=edits.get("sources", {}), assets=edits.get("assets", {}),
                                      manifest=edits.get("manifest"), prefab_id="presentation-studio.p000000000001.s000000000001")


def test_composition_replaces_adds_and_deletes_and_recomputes_the_lists():
    candidate, problems = compose(base(), sources={"src/Scene.tsx": "export default () => null", "src/lib/new.ts": "export {}",
                                                   "src/theme.json": None},
                                  assets={"public/dot.png": None, "public/b.png": base64.b64encode(PNG_1X1).decode()})
    assert problems == [] and candidate is not None
    block = candidate["manifest"]["source"]
    assert block["modules"] == ["src/Scene.tsx", "src/lib/Title.tsx", "src/lib/new.ts"] and block["assets"] == ["public/b.png"]
    assert candidate["manifest"]["id"] == "presentation-studio.p000000000001.s000000000001"
    assert set(candidate["sources"]) == set(block["modules"]) and set(candidate["assets"]) == {"public/b.png"}
    bundle = parse_candidate(candidate)      # the candidate is the exact shape `parse_candidate` accepts
    assert bundle.remotion_source().digest and set(candidate_files(candidate)) == set(block["modules"]) | {"public/b.png"}


def test_the_untouched_files_and_the_block_are_the_pins_own():
    manifest, files = base()
    candidate, _ = compose((manifest, files), sources={"src/lib/Title.tsx": "export const Title = () => null;"})
    assert candidate["sources"]["src/Scene.tsx"] == scene_files()["src/Scene.tsx"]
    assert {k: v for k, v in candidate["manifest"]["source"].items() if k not in ("modules", "assets")} == \
           {k: v for k, v in manifest["source"].items() if k not in ("modules", "assets")}
    assert candidate["manifest"] is not manifest and manifest["source"]["modules"] == ["src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json"]


def test_a_manifest_in_the_request_replaces_the_base_but_core_owns_the_file_lists():
    manifest, files = base()
    sent = json.loads(json.dumps(manifest))
    sent["source"]["composition"]["duration_in_frames"] = 150
    sent["source"]["modules"] = ["src/ignored.ts"]
    candidate, _ = compose((manifest, files), manifest=sent)
    assert candidate["manifest"]["source"]["composition"]["duration_in_frames"] == 150
    assert candidate["manifest"]["source"]["modules"] == ["src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json"]


@pytest.mark.parametrize(("edits", "needle"), [
    ({"sources": {"src/none.ts": None}}, "does not have"),
    ({"assets": {"public/none.png": None}}, "does not have"),
    ({"assets": {"public/a.png": "###"}}, "base64"),
])
def test_composition_names_what_cannot_be_done(edits, needle):
    candidate, problems = compose(base(), **edits)
    assert candidate is None and needle in problems[0]


def test_a_manifest_without_a_source_block_is_refused():
    candidate, problems = compose_remotion_candidate({"id": "x"}, {}, sources={}, assets={}, manifest=None, prefab_id="p")
    assert candidate is None and "no Remotion source block" in problems[0]


# ------------------------------------------------------------------ diagnostics et resultat

def test_diagnostics_read_file_line_column_text_and_are_bounded():
    rows = [{"file": f"src/f{i}.tsx", "line": i, "column": 2, "text": "Unexpected }"} for i in range(1, 6)]
    text = format_diagnostics(rows)
    assert text.startswith("src/f1.tsx:1:2 Unexpected }") and text.count(" | ") == 2 and text.endswith("(+2 more)")
    assert format_diagnostics([]) == ""


def test_a_build_failure_is_a_refusal_with_422_and_its_diagnostics_on_the_wire():
    from jarvis.domain.presentation_studio_edit import StudioActor
    rows = ({"file": "src/Scene.tsx", "line": 4, "column": 9, "text": "Unexpected }"},)
    result = ReloadResult(ReloadStatus.REFUSED_VALIDATION, StudioActor.BRAIN, "pst_x", "psv_x", "pss_x", 3, 3, 0, None, None,
                          code=C.SOURCE_BUILD_FAILED.value, message="m", diagnostics=rows)
    wire = result.to_dict()
    assert result.http_status == 422 and wire["diagnostics"] == list(rows) and wire["error"]["diagnostics"] == list(rows)
    plain = ReloadResult(ReloadStatus.REFUSED_VALIDATION, StudioActor.BRAIN, "pst_x", "psv_x", "pss_x", 3, 3, 0, None, None,
                         code=C.SOURCE_INVALID.value, message="m")
    assert plain.http_status == 400 and "diagnostics" not in plain.to_dict()


def test_nothing_sensible_is_accepted_for_empty_inputs():
    assert parse_remotion_edit(None, None) == ({}, {})
