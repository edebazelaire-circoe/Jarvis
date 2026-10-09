"""The agent surface carries no engine (Remotion Slice 02, `docs/presentation-engine.md` rule 1).

Only a Human UI action may reach `EngineSelectionPolicy`; no `jarvis-presentation` tool may expose an engine or an actor.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.runtime.mcp_catalog import build_introspection_server

FORBIDDEN = re.compile(r"engine|actor|slidecar|remotion|renderer|runtime_kind", re.IGNORECASE)


def property_names(node, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                found.extend(value)
            property_names(value, found)
    elif isinstance(node, list):
        for item in node:
            property_names(item, found)
    return found


def enum_values(node, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "enum" and isinstance(value, list):
                found.extend(str(v) for v in value)
            enum_values(value, found)
    elif isinstance(node, list):
        for item in node:
            enum_values(item, found)
    return found


async def test_no_presentation_tool_exposes_an_engine_or_actor_parameter():
    tools = await build_introspection_server("jarvis-presentation").list_tools()
    assert len(tools) >= 12, "the jarvis-presentation server must list its tools"
    for tool in tools:
        for name in property_names(tool.inputSchema):
            assert not FORBIDDEN.search(name), f"{tool.name} exposes parameter {name!r}"
        for value in enum_values(tool.inputSchema):
            assert not re.search(r"slidecar|remotion", value, re.IGNORECASE), f"{tool.name} offers an engine as an enum value"


def test_the_guard_would_catch_a_leak():
    """Mutation guard for the parity test itself."""

    leaked = {"type": "object", "properties": {"op": {"enum": ["a", "remotion"]},
                                               "details": {"properties": {"engine": {"type": "string"}}}}}
    assert any(FORBIDDEN.search(name) for name in property_names(leaked))
    assert any(FORBIDDEN.search(value) for value in enum_values(leaked))


def test_the_agent_modules_and_the_create_route_never_route_an_engine():
    root = Path(__file__).resolve().parents[2] / "jarvis"
    for relative in ("runtime/presentation_studio_mcp.py", "runtime/presentation_studio_mcp_tools.py",
                     "runtime/presentation_studio_mcp_support.py", "runtime/presentation_studio_relay.py",
                     "protocol/presentation_studio_routes.py"):
        text = (root / relative).read_text(encoding="utf-8")
        assert not re.search(r"presentation_studio_engine|EngineSelectionPolicy|\bengine\s*=", text), relative
