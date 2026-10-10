"""La documentation de `jarvis-remotion` (Remotion Slice 21) dit ce que le code fait : outils, gardes, budget, et plus aucune phrase périmée « aucun outil »."""

from __future__ import annotations

from pathlib import Path

from jarvis.runtime.remotion_mcp import TOOL_NAMES

DOCS = Path(__file__).resolve().parents[2] / "docs"
RUNTIME = (DOCS / "remotion-runtime.md").read_text(encoding="utf-8")
SECTION = RUNTIME[RUNTIME.index("## 13. Surface de l'agent"):]


def test_the_section_names_every_tool_and_every_guard():
    for tool in TOOL_NAMES:
        assert f"`{tool}`" in SECTION, tool
    for phrase in ("remotion_user_turn_required", "presentation_studio_source_request_user_only", "remotion_licence_user_only", "needs_user",
                   "n'appelle jamais `POST .../studio/open`", "user_request", "authorised_boards", "published_to_library: false",
                   "remotion_import.allowed_owners", "Limite assumée", "110 000", "5 178", "next_step", "est gardée par Core", "Attestation globale", "core_timeout", "control-center-settings.json", "presentation_studio_source_request_required"):
        assert phrase in SECTION, phrase


def test_the_other_remotion_contracts_point_to_the_agent_surface_and_no_longer_say_there_is_none():
    for name in ("remotion-render.md", "remotion-import.md", "remotion-studio.md"):
        text = (DOCS / name).read_text(encoding="utf-8")
        assert "remotion-runtime.md" in text and "jarvis-remotion" in text, name
    assert "Aucun outil MCP, aucun chemin du cerveau" not in (DOCS / "remotion-render.md").read_text(encoding="utf-8")
    assert "aucun outil MCP, aucun budget de contexte touché" not in (DOCS / "remotion-import.md").read_text(encoding="utf-8")
    assert "jarvis-remotion" in (DOCS / "presentation-engine.md").read_text(encoding="utf-8")


def test_the_tool_contract_and_the_tool_brain_contract_carry_the_server():
    contract = (DOCS / "mcp" / "tool-contract.md").read_text(encoding="utf-8")
    assert "| `jarvis-remotion`" in contract and "### 10.17" in contract and "REMOTION_CONTEXT_BUDGET_BYTES" in contract
    brain = (DOCS / "tool-brain-contracts.md").read_text(encoding="utf-8")
    assert "## 19. Remotion agent verbs: ownership" in brain and "studio_owned" in brain and "remotion_user_turn_required" in brain


def test_the_source_request_rule_is_amended_in_the_contract_and_the_runbook():
    studio = (DOCS / "presentation-studio.md").read_text(encoding="utf-8")
    assert "Amended by the Remotion Slice 21 rework" in studio and "a pending request IS the authority" in studio
    assert "never blocks an edit. Revisit" not in studio, "the Slice 06 rule is gone for the brain"
    assert "forge both" in studio and "SOURCE_REQUEST_TTL_S" in studio
    operations = (DOCS / "OPERATIONS.md").read_text(encoding="utf-8")
    assert "Le `request_id` est obligatoire (acteur `brain`, Slice 21)" in operations and "**n'appelle pas** `scene.source_request`" in operations
