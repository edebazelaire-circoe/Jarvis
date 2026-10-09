"""La section 11 de `docs/remotion-isolation.md` et *Typed variables and fast edits* de `docs/presentation-studio.md` (Slice 13) contre le code."""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.domain.remotion_controls import (
    DATA_KEY, MAX_DEPTH, MAX_INPUT_BYTES, MAX_NODES, RESERVED_REASON, UNSAFE_KEYS, URL_REASON, ControlKind,
)
from jarvis.runtime.remotion_relay import REPORT_EVENTS

ROOT = Path(__file__).resolve().parents[2]
ISOLATION = (ROOT / "docs" / "remotion-isolation.md").read_text(encoding="utf-8")
SECTION = ISOLATION[ISOLATION.index("## 11. Slice 13"):]
STUDIO = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
CONTRACT = STUDIO[STUDIO.index("## Typed variables and fast edits"):]
CONTRACT = CONTRACT[:CONTRACT.index("\n## ", 10)]
PROPS_JS = (ROOT / "jarvis" / "runtime" / "control_center_remotion_props.js").read_text(encoding="utf-8")
FRAME_JS = (ROOT / "jarvis" / "runtime" / "control_center_remotion_frame.js").read_text(encoding="utf-8")


def test_the_documented_bounds_are_the_code_ones_in_both_languages():
    assert MAX_INPUT_BYTES == 64 * 1024 and MAX_DEPTH == 8 and MAX_NODES == 2000 and DATA_KEY == "data"
    assert "plus de 8 niveaux, plus de 2 000 valeurs, plus de 64 Kio" in SECTION
    for pattern in (rf"MAX_INPUT_BYTES={MAX_INPUT_BYTES // 1024}\*1024", rf"MAX_DEPTH={MAX_DEPTH};", rf"MAX_NODES={MAX_NODES};"):
        assert re.search(pattern, PROPS_JS), pattern
    for key in UNSAFE_KEYS:
        assert key in SECTION and f"'{key}'" in PROPS_JS


def test_every_kind_and_every_withheld_rule_is_documented():
    for kind in ControlKind:
        assert f"`{kind.value}`" in CONTRACT, kind
    assert "connect-src 'none'" in SECTION and "staticFile" in SECTION and "staticFile" in URL_REASON
    assert f"`{DATA_KEY}`" in SECTION and "reserved" in RESERVED_REASON
    assert "not supported by the remotion engine" in CONTRACT


def test_the_wire_additions_documented_exist():
    assert "props_rejected" in REPORT_EVENTS and "`props_rejected`" in SECTION
    assert "props:['props','data']" in FRAME_JS and "props {props, data?}" in SECTION
    assert "input_contract" in SECTION and "input_contract" in CONTRACT


def test_the_cited_conformance_files_exist():
    for name in re.findall(r"tests/unit/(test_[a-z_]+\.py)", SECTION + CONTRACT):
        assert (ROOT / "tests" / "unit" / name).is_file(), name
    assert (ROOT / "tests" / "fixtures" / "remotion_input_props_cases.json").is_file()
    assert (ROOT / "scripts" / "remotion_player_harness.py").is_file()


def test_the_contract_states_there_is_no_second_editor_and_the_bridge_is_inbound_only():
    assert "no second editor" in CONTRACT and "`control.set`" in CONTRACT and "`control.reset`" in CONTRACT
    assert "inbound only" in CONTRACT and "never renders, exports" in CONTRACT
