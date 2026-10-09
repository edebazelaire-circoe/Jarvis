"""La section « Comparison and composition in the explorer » (Slice 19, interface) dit ce que les fichiers font vraiment."""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.runtime import control_center as cc

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
START = DOC.index("## Comparison and composition in the explorer (Slice 19, interface)")
SECTION = DOC[START:DOC.index("## Comparison and semantic composition contract", START)]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTROLLER = (RUNTIME / "control_center_presentation_studio_explorer.js").read_text(encoding="utf-8")
COMPARE = (RUNTIME / "control_center_presentation_studio_explorer_compare.js").read_text(encoding="utf-8")


def test_the_owners_and_the_tests_named_by_the_section_exist():
    for name in ("compare_core", "compare", "compose"):
        assert (RUNTIME / f"control_center_presentation_studio_explorer_{name}.js").is_file(), name
        assert f"explorer_{name}.js" in SECTION or name == "compare_core" and "compare_core.js" in SECTION, name
    for test in ("core_js", "js", "browser", "docs"):
        assert (ROOT / "tests" / "unit" / f"test_presentation_studio_explorer_compare_{test}.py").is_file(), test
    assert (ROOT / "tests" / "fakes" / "explorer_compare_world.cjs").is_file()


def test_the_three_markers_are_registered_once_between_the_widgets_and_the_controller():
    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    markers = (cc.STUDIO_EXPLORER_CORE_SCRIPT_MARKER, cc.STUDIO_EXPLORER_WIDGETS_SCRIPT_MARKER, cc.STUDIO_EXPLORER_COMPARE_CORE_SCRIPT_MARKER,
               cc.STUDIO_EXPLORER_COMPARE_SCRIPT_MARKER, cc.STUDIO_EXPLORER_COMPOSE_SCRIPT_MARKER, cc.STUDIO_EXPLORER_SCRIPT_MARKER)
    assert [html.count(marker) for marker in markers] == [1] * 6
    positions = [html.index(marker) for marker in markers]
    assert positions == sorted(positions), "pure model, then DOM modules, then the controller that uses them"
    for name in (cc.STUDIO_EXPLORER_COMPARE_CORE_SCRIPT_FILE, cc.STUDIO_EXPLORER_COMPARE_SCRIPT_FILE, cc.STUDIO_EXPLORER_COMPOSE_SCRIPT_FILE):
        assert (RUNTIME / name).is_file(), name


def test_the_page_api_listed_in_the_section_is_the_one_the_page_installs():
    installed = CONTROLLER[CONTROLLER.index("compare:Object.freeze({open:"):]
    for entry in ("open", "close", "isOpen", "view", "state", "marks", "mark", "focus", "mode", "navigate", "link", "unlink", "refresh"):
        assert re.search(rf"\b{entry}:", installed), entry
        assert f"`compare.{entry}" in SECTION or f"/ `.{entry}" in SECTION or f"`.{entry}" in SECTION or entry in ("close",), entry
    for entry in ("plan", "create", "dialog"):
        assert f"compose.{entry}" in SECTION and re.search(rf"\b{entry}:", installed), entry
    for op in ("open", "close", "focus", "mode", "navigate", "link", "unlink"):
        assert f"'{op}'" in COMPARE or f"op==='{op}'" in COMPARE, op
    for op in ("plan", "create", "dialog"):
        assert f"op==='{op}'" in COMPARE, op


def test_the_keys_and_the_limits_of_the_section_are_the_ones_in_the_code():
    for key in ("'m'", "'f'", "'l'"):
        assert key in COMPARE, key
    assert "event.key==='C'&&event.shiftKey" in COMPARE and "(event.key==='c'||event.key==='C')" in CONTROLLER
    core = (RUNTIME / "control_center_presentation_studio_explorer_compare_core.js").read_text(encoding="utf-8")
    assert "NARROW_PX=560" in core and "MAX_MARKS=4" in core and "MAX_RATIONALE=400" in core and "MAX_LINKS=64" in core
    for fragment in ("560 px", "2 or 4", "400 characters", "64-link"):
        assert fragment in SECTION, fragment
    assert "Python broker" in SECTION and "open` and `close` only" in SECTION, "the broker decision is written down for Slice 21"
