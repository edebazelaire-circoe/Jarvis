"""Documentation and wiring parity of the edit inspector (jarvis-interactive-presentation-studio, Slice 07).

The page contract (`docs/presentation-studio.md` > *Edit inspector UI*), the operations recipe, the canonical names, the relay route and
the marker splice must say what the code does: constants, the read-only relay route, the 15 theme variables, the owner file, the page.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime import control_center as cc
from jarvis.runtime.presentation_studio_relay import PresentationStudioRelayRoutes
from tests.fakes.capture_stack import CaptureStack

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_presentation_studio_inspector.js"


def page(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def section() -> str:
    text = page("presentation-studio.md")
    start = text.index("## Edit inspector UI (Level 3, Slice 07)")
    return text[start:text.index("\n## ", start + 10)]


def module_constants() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    done = subprocess.run([node, "-e", "const M=require(process.argv[1]);console.log(JSON.stringify({p:M.PREVIEW_MIN_MS,t:M.TEXT_PREVIEW_MS,"
                           "i:M.IDLE_COMMIT_MS,r:M.RELOAD_RETRY_MS,poll:M.POLL_MS,applied:M.APPLIED_THEME,off:M.NOT_APPLIED_THEME,key:M.STORAGE_KEY}))",
                           str(MODULE)], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def test_the_section_names_its_owner_its_tests_and_every_test_file_exists():
    body = section()
    assert "control_center_presentation_studio_inspector.js" in body and "STUDIO_INSPECTOR" not in body.split("Owner:")[0]
    for name in ("test_presentation_studio_inspector_js.py", "test_presentation_studio_inspector_behaviour_js.py",
                 "test_presentation_studio_inspector_browser.py", "test_presentation_studio_inspector_docs.py"):
        assert (ROOT / "tests" / "unit" / name).is_file(), name
    for helper in ("_studio_inspector_bench.cjs", "_presentation_studio_inspector_browser.mjs"):
        assert (ROOT / "tests" / "unit" / helper).is_file() and helper in body
    assert (ROOT / "tests" / "fakes" / "presentation_studio_inspector_browser.py").is_file()
    assert MODULE.is_file()


def test_the_documented_bounds_are_the_ones_the_module_uses():
    body = section()
    constants = module_constants()
    for needle in (f"`PREVIEW_MIN_MS` = {constants['p']} ms", f"`TEXT_PREVIEW_MS` = {constants['t']} ms", f"`IDLE_COMMIT_MS` = {constants['i']} ms"):
        assert needle in body, needle
    schedule = ", ".join(f"{ms / 1000:g}" for ms in constants["r"])
    assert f"`RELOAD_RETRY_MS` = {schedule} s" in body
    assert len(constants["r"]) == 5 and sum(constants["r"]) <= 20000
    assert "every 4 s" in body and constants["poll"] == 4000
    assert constants["key"] in body, "the one stored key is documented"


def test_the_fifteen_theme_variables_are_named_in_the_decision():
    body = section()
    constants = module_constants()
    assert len(constants["applied"]) == 5 and len(constants["off"]) == 10
    for name in constants["applied"] + constants["off"]:
        assert f"`{name}`" in body, name
    assert "`non appliqué`" in body and "own `revision`" in body


def test_the_read_only_art_direction_relay_is_documented_everywhere_it_is_listed():
    relay = PresentationStudioRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    art = [r for r in relay.routes() if r.path.endswith("/art-direction")]
    assert [(r.method, r.path) for r in art] == [("GET", "/api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/art-direction")]
    studio = page("presentation-studio.md")
    assert "`GET /api/presentation-studio/presentations/{id}/variants/{vid}/art-direction`" in section()
    assert "read-only `GET .../variants/{variant_id}/art-direction`" in studio
    assert "No Control Center relay and no MCP tool yet" not in studio, "the Slice 09 sentence is stale since Slice 07"
    names = (ROOT / "tasks/jarvis-interactive-presentation-studio/docs/09-canonical-names.md").read_text(encoding="utf-8")
    assert "## 19. Slice 07 additions" in names and "studio_art_direction" in names
    assert "art-direction" in (ROOT / "jarvis/runtime/presentation_studio_relay.py").read_text(encoding="utf-8").split('"""')[1]


def test_the_operations_recipe_exists_and_links_the_contract():
    ops = page("OPERATIONS.md")
    start = ops.index("### Inspecteur d'édition d'une présentation (studio, Slice 07) : vérification humaine")
    recipe = ops[start:ops.index("\n### ", start + 10)]
    assert "presentation-studio.md#edit-inspector-ui-level-3-slice-07" in recipe and "JARVIS_DATA_ROOT" in recipe
    for needle in ("Clavier seul", "Lecture", "Direction artistique", "Petit écran", "Mouvement réduit", "non appliqué"):
        assert needle in recipe, needle


def test_the_concept_table_the_levels_table_and_the_architecture_know_the_inspector():
    studio = page("presentation-studio.md")
    assert "| Edit inspector (GUI) |" in studio and "[Edit inspector UI](#edit-inspector-ui-level-3-slice-07)" in studio
    assert "| Edit inspector UI (generated widgets" in studio
    assert "control_center_presentation_studio_inspector.js" in page("ARCHITECTURE.md")


def test_the_marker_is_spliced_once_and_the_dock_button_exists():
    html = (ROOT / "jarvis/runtime/control_center.html").read_text(encoding="utf-8")
    assert html.count(cc.STUDIO_INSPECTOR_SCRIPT_MARKER) == 1
    assert html.index(cc.STUDIO_PLAYER_SCRIPT_MARKER) < html.index(cc.STUDIO_INSPECTOR_SCRIPT_MARKER), "after the player it reads"
    assert cc.STUDIO_INSPECTOR_SCRIPT_FILE == MODULE.name
    order = [cc.STUDIO_INSPECTOR_CORE_SCRIPT_MARKER, cc.STUDIO_INSPECTOR_WIDGETS_SCRIPT_MARKER, cc.STUDIO_INSPECTOR_SCRIPT_MARKER]
    assert all(html.count(marker) == 1 for marker in order) and [html.index(m) for m in order] == sorted(html.index(m) for m in order), "core, widgets, controller"
    for marker, file in zip(order, (cc.STUDIO_INSPECTOR_CORE_SCRIPT_FILE, cc.STUDIO_INSPECTOR_WIDGETS_SCRIPT_FILE, cc.STUDIO_INSPECTOR_SCRIPT_FILE)):
        assert (ROOT / "jarvis/runtime" / file).is_file() and marker.startswith("/*__CONTROL_CENTER_PRESENTATION_STUDIO_INSPECTOR")
    dock = html[html.index('<nav class="dock"'):html.index("</nav>", html.index('<nav class="dock"'))]
    assert 'id="openStudioInspector"' in dock and 'aria-controls="jvStudioInspector"' in dock and 'aria-expanded="false"' in dock


async def test_the_served_page_carries_the_module_and_no_leftover_marker(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        status, _, text = await stack.call("GET", "/")
    assert status == 200 and "root.JarvisStudioInspector=api" in text
    assert len(re.findall(r"/\*__CONTROL_CENTER_[A-Z_]+__\*/", text)) == 0, "every marker was replaced"
    assert text.count("jvStudioInspector") >= 2


def test_the_module_says_what_it_does_not_do():
    head = MODULE.read_text(encoding="utf-8")[:6000]
    for needle in ("aucun chemin d'écriture propre", "UNE modification = UNE entrée d'historique", "caché ENTIÈREMENT", "non appliqué", "SA PROPRE"):
        assert needle in head, needle
