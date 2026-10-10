"""La documentation de l'edition de source Remotion contre le code et le verrou (Slice 14)."""

from __future__ import annotations

import json
from pathlib import Path
import re

from jarvis.domain.presentation_studio_checks import HTTP_STATUS, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_remotion_edit import MAX_EDIT_ASSETS_B64, MAX_REMOTION_BODY_BYTES
from jarvis.protocol.presentation_studio_routes import PresentationStudioProtocolRoutes

ROOT = Path(__file__).resolve().parents[2]
STUDIO = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
ENGINE = (ROOT / "docs" / "presentation-engine.md").read_text(encoding="utf-8")
ISOLATION = (ROOT / "docs" / "remotion-isolation.md").read_text(encoding="utf-8")
HOST_JS = (ROOT / "jarvis" / "runtime" / "control_center_prefab_host.js").read_text(encoding="utf-8")
LOCK = json.loads((ROOT / "jarvis" / "capabilities" / "remotion" / "package-lock.json").read_text(encoding="utf-8"))["packages"]
SECTION = STUDIO[STUDIO.index("### Remotion sources (Slice 14)"):STUDIO.index("### Source requests (`scene.source_request`)")]


def test_the_codemods_decision_rests_on_the_pinned_lock():
    codemods = LOCK["node_modules/@remotion/codemods"]
    assert codemods["version"] == "4.0.534" and "@remotion/codemods" in SECTION and "4.0.534" in SECTION
    # transitive only: nothing in the capability's own manifest asks for it, and the lock carries no TypeScript compiler
    manifest = json.loads((ROOT / "jarvis" / "capabilities" / "remotion" / "package.json").read_text(encoding="utf-8"))
    assert "@remotion/codemods" not in manifest["dependencies"]
    assert "@remotion/codemods" in LOCK["node_modules/@remotion/cli"]["dependencies"]
    assert "node_modules/typescript" not in LOCK and "no `typescript` is in the pinned lock" in SECTION
    assert "node_modules/@remotion/sdk" in LOCK and "@remotion/sdk` is a different package" in SECTION


def test_the_typed_error_is_documented_with_its_status_and_wired_in_the_routes():
    assert C.SOURCE_BUILD_FAILED.value == "presentation_studio_source_build_failed" and HTTP_STATUS[C.SOURCE_BUILD_FAILED] == 422
    for page in (STUDIO, ENGINE):
        assert "presentation_studio_source_build_failed" in page
    assert "`presentation_studio_source_build_failed` (422, Slice 14)" in STUDIO and "**HTTP 422**" in SECTION
    routes = [(route.method, route.path) for route in PresentationStudioProtocolRoutes(object()).routes()]
    assert ("GET", "/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/source") in routes
    assert "/scenes/{scene_id}/source" in STUDIO


def test_documented_constants_are_the_code_s():
    assert re.search(r"const RENDER_PROOF_MS=10000;", HOST_JS) and "`RENDER_PROOF_MS` = 10 s" in SECTION and "RENDER_PROOF_MS" in ISOLATION
    assert MAX_EDIT_ASSETS_B64 == 2 * 1024 * 1024 and "2 Mi base64" in SECTION
    assert 4_000_000 < MAX_REMOTION_BODY_BYTES < 4_400_000 and "about 4.1 Mi" in SECTION


def test_no_new_agent_tool_was_added_for_this():
    catalog = (ROOT / "jarvis" / "runtime" / "presentation_studio_mcp_tools.py").read_text(encoding="utf-8")
    assert "source-edits" not in catalog and "restore_version" not in catalog and "no new MCP tool" in SECTION


def test_the_queue_bound_and_the_core_owned_manifest_keys_are_documented_as_coded():
    from jarvis.core.presentation_studio_reload import DEFAULT_COMPOSE_QUEUE_S
    assert DEFAULT_COMPOSE_QUEUE_S == 75.0 and "`DEFAULT_COMPOSE_QUEUE_S` = 75 s" in SECTION and "reload_busy" in SECTION
    for key in ("source.engine", "catalog", "schema_version", "runtime_license", "source_sha256"):
        assert key in SECTION
    assert "the user too" in SECTION.lower() and "brain` actor only" in SECTION
    assert "compiles the scene only" in SECTION and "75 s with the busy error" in SECTION
