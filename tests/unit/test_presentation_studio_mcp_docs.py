"""The Slice 21 documentation says what the tools do (jarvis-interactive-presentation-studio)."""

from __future__ import annotations

from pathlib import Path

from jarvis.runtime import presentation_studio_mcp as server
from jarvis.runtime.presentation_studio_mcp_tools import EDIT_OPS, OPERATION_EVENTS
from jarvis.runtime.claude_local import BRAIN_PRESENTATION_PROMPT
from jarvis.domain.presentation_studio_authoring_policy import OP_ASSEMBLE, OP_CHECK, OP_FINALIZE

ROOT = Path(__file__).resolve().parents[2]


def section() -> str:
    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    start = page.index("## Agent and voice operations (Level 3, Slice 21)")
    return page[start:page.index("## Reused owners (do not rebuild)")]


def test_every_tool_is_in_the_reference_the_prompt_and_the_planner_mapping():
    text = section()
    for name in server.TOOL_NAMES:
        assert f"`{name}`" in text, name
        assert name in BRAIN_PRESENTATION_PROMPT, name
    assert len(server.TOOL_NAMES) == 12 and "twelve" in text
    # the three operation names of the Slice 11 planner are tools, one to one
    assert {OP_CHECK, OP_ASSEMBLE, OP_FINALIZE} <= set(server.TOOL_NAMES)


def test_every_edit_op_and_correlated_event_is_documented():
    text = section()
    for op in EDIT_OPS:
        assert op in text, op
    for event in {e for e in OPERATION_EVENTS.values() if e}:
        assert event in text, event
    for phrase in ("studio_owned", "expected_entry_id", "mode_switch_refused", "AddressedTurnTracker", "`speech`", "untrusted",
                   "Not exposed on purpose", "Real-model traces", "Limits and left to do"):
        assert phrase in text, phrase


def test_the_reference_is_linked_from_the_status_table_and_the_tool_contract():
    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    assert "#agent-and-voice-operations-level-3-slice-21" in page and "**implemented (Level 3)**" in page
    contract = (ROOT / "docs" / "mcp" / "tool-contract.md").read_text(encoding="utf-8")
    assert "jarvis-presentation" in contract and "10.15" in contract
