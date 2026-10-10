"""`jarvis-remotion` sur le vrai protocole MCP (Remotion Slice 21) : schémas stricts, refus rendus au modèle, parité « pas de moteur, pas d'accusé ».

Le vrai `build_server` (FastMCP) derrière une vraie session MCP, les vrais outils, un client de Core scripté. Ce que le modèle peut ENVOYER est
fermé par le schéma ; ce qu'il envoie quand même est refusé avant que l'outil n'existe pour Core.
"""

from __future__ import annotations

import json
import re

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from jarvis.runtime import mcp_catalog, mcp_tool_meta
from jarvis.runtime.remotion_mcp import SERVER_NAME, TOOL_NAMES, build_server, mcp_config, write_mcp_config
from tests.unit.remotion_mcp_world import JOB, PID, SHA, VID, make_tools


async def call(tools, name, arguments):
    async with create_connected_server_and_client_session(build_server(tools=tools)) as session:
        result = await session.call_tool(name, arguments)
    text = "".join(block.text for block in result.content if getattr(block, "type", "") == "text")
    return result.isError, text


async def test_the_server_lists_exactly_its_six_tools_with_closed_schemas():
    tools, _, _ = make_tools(__import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    async with create_connected_server_and_client_session(build_server(tools=tools)) as session:
        listed = (await session.list_tools()).tools
    assert [t.name for t in listed] == list(TOOL_NAMES) == ["remotion_status", "remotion_setup", "remotion_studio", "remotion_export",
                                                            "remotion_import", "remotion_upgrades"]
    assert all(t.inputSchema.get("additionalProperties") is False for t in listed)


@pytest.mark.parametrize("name,arguments", [
    ("remotion_setup", {"op": "install", "engine": "slidecar"}),
    ("remotion_export", {"op": "start", "format": "mp4", "engine": "remotion"}),
    ("remotion_export", {"op": "start", "format": "mp4", "authorised_boards": ["b1"]}),
    ("remotion_studio", {"acknowledge_unsandboxed_scene": True}),
    ("remotion_status", {"target": "capability", "actor": "user"}),
    ("remotion_upgrades", {"op": "try", "scene_id": "pss_0123456789ab", "licence_ack": ["GPL-3.0"]}),
    ("remotion_import", {"op": "plan", "repo_url": "https://github.com/remotion-dev/x", "commit": SHA, "scope": "library"}),
], ids=lambda v: v if isinstance(v, str) else "")
async def test_an_argument_the_model_must_never_send_is_refused_before_any_tool_runs(tmp_path, name, arguments):
    tools, core, _ = make_tools(tmp_path, turn=True)
    failed, text = await call(tools, name, arguments)
    assert failed and "Arguments inconnus refusés, rien n'a été envoyé" in text
    assert core.calls == [] and tools._cc.requests == [], "ni Core ni le Control Center n'ont été joints"


async def test_a_setting_outside_the_closed_export_list_is_a_schema_refusal(tmp_path):
    tools, core, _ = make_tools(tmp_path, turn=True)
    for settings in ({"concurrency": 2}, {"engine": "slidecar"}, {"crf": 99}, {"scale": 9}):
        failed, text = await call(tools, "remotion_export", {"op": "start", "format": "mp4", "settings": settings, "user_request": "exporte"})
        assert failed and "Argument invalide" in text, settings
    assert core.writes == []


async def test_over_the_wire_an_ambient_turn_cannot_install_export_import_or_try(tmp_path):
    tools, core, cc = make_tools(tmp_path, turn=False)
    calls = [("remotion_setup", {"op": "install", "user_request": "installe"}),
             ("remotion_export", {"op": "start", "format": "mp4", "user_request": "exporte"}),
             ("remotion_export", {"op": "cancel", "job_id": JOB, "user_request": "annule"}),
             ("remotion_import", {"op": "plan", "repo_url": "https://github.com/remotion-dev/x", "commit": SHA, "user_request": "importe"}),
             ("remotion_upgrades", {"op": "try", "scene_id": "pss_0123456789ab", "user_request": "essaie"})]
    for name, arguments in calls:
        failed, text = await call(tools, name, arguments)
        assert failed and "remotion_user_turn_required" in text, name
    assert core.calls == []
    assert {route for _, route, _ in cc.requests} == {"/api/presentation-studio/agent/turn"}


async def test_over_the_wire_the_addressed_turn_unlocks_the_gesture_and_nothing_else(tmp_path):
    tools, core, _ = make_tools(tmp_path, turn=True)
    failed, text = await call(tools, "remotion_export", {"op": "start", "format": "mp4", "user_request": "exporte en MP4"})
    assert not failed and JOB in text
    assert core.writes == ["remotion_render_create"]
    # the Studio stays a pointer even then
    failed, text = await call(tools, "remotion_studio", {})
    assert not failed and "needs_user" in text and core.writes == ["remotion_render_create"]


async def test_over_the_wire_a_core_failure_is_an_error_result_with_its_code(tmp_path):
    from tests.unit.remotion_mcp_world import refusal

    tools, core, _ = make_tools(tmp_path, turn=True)
    core.refusals["remotion_render_create"] = refusal("presentation_render_browser_unavailable", "no browser")
    failed, text = await call(tools, "remotion_export", {"op": "start", "format": "mp4", "user_request": "exporte"})
    assert failed and "presentation_render_browser_unavailable" in text and "Chrome" in text


# ------------------------------------------------------------------ parité : aucun moteur, aucun acteur, aucun accusé, nulle part

FORBIDDEN_PARAMETER = re.compile(r"engine|actor|origin|slidecar|renderer|runtime_kind|acknowledge|licence_ack|keep_assets|authorised_boards", re.IGNORECASE)


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


async def test_no_tool_of_jarvis_remotion_exposes_an_engine_an_actor_or_an_acknowledgement():
    listed = await mcp_catalog.build_introspection_server(SERVER_NAME).list_tools()
    assert len(listed) == 6
    for tool in listed:
        for name in property_names(tool.inputSchema):
            assert not FORBIDDEN_PARAMETER.search(name), f"{tool.name} exposes parameter {name!r}"
        for value in enum_values(tool.inputSchema):
            assert not re.search(r"slidecar|remotion", value, re.IGNORECASE), f"{tool.name} offers an engine as an enum value"


async def test_no_native_tool_of_any_server_takes_an_engine_parameter():
    """Étend la parité de la Slice 02 à TOUS les serveurs déclarés au cerveau : le moteur n'est jamais un argument d'outil."""

    for meta in mcp_tool_meta.SERVERS:
        if meta.server in ("jarvis-tools", "jarvis-drive"):
            continue
        for tool in await mcp_catalog.build_introspection_server(meta.server).list_tools():
            names = property_names(tool.inputSchema)
            assert not [n for n in names if re.fullmatch(r"engine|engine_id|default_engine|slidecar|renderer|runtime_kind", n, re.IGNORECASE)], (meta.server, tool.name)


def executable_tokens(source: str) -> list[str]:
    """Names, attributes and string literals of the code, docstrings left out (a docstring may say what the module does NOT do)."""

    import ast

    tree = ast.parse(source)
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
                  and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.Attribute):
            found.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            found.append(node.value)
    return found


def test_the_remotion_modules_never_name_the_engine_selection_policy_or_the_unsandboxed_acknowledgement_route():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
    for name in ("remotion_mcp.py", "remotion_mcp_tools.py"):
        code = "\n".join(executable_tokens((root / name).read_text(encoding="utf-8")))
        assert not re.search(r"EngineSelectionPolicy|resolve_engine|set_default_engine|studio_open|acknowledge_unsandboxed|/studio/open|/studio/restart|licence_ack\"", code), name
    # the typed client has no route that opens the Studio or sets an engine for these tools to call
    from jarvis.protocol.client import LocalCoreClient

    assert not [n for n in dir(LocalCoreClient) if re.search(r"studio_open|studio_restart|set_engine|choose_engine|default_engine", n)]


def test_the_allow_list_of_import_owners_is_not_a_setting_the_brain_can_write():
    """`remotion_import.allowed_owners` est un fichier de réglages de l'utilisateur ; `settings_set` ne l'expose pas."""

    from pathlib import Path

    runtime = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
    for name in ("settings_mcp.py", "agent_settings.py", "scene_settings.py", "interaction_mode_settings.py", "memory_settings.py",
                 "voice_settings_schema.py", "wake_word_settings.py"):
        assert "allowed_owners" not in (runtime / name).read_text(encoding="utf-8"), name


# ------------------------------------------------------------------ déclaration au cerveau

def test_the_mcp_config_names_this_server_alone_and_the_remotion_subcommand(tmp_path):
    from jarvis.runtime.display_mcp import DisplayMcpTarget
    from jarvis.runtime.presentation_studio_mcp_support import PresentationMcpTarget
    from jarvis.runtime.settings_mcp import ConsoleMcpTarget

    target = PresentationMcpTarget(DisplayMcpTarget(core_host="127.77.0.1", core_port=17653, token_file=tmp_path / "t", runtime_root=tmp_path),
                                   ConsoleMcpTarget("127.0.0.1", 8765, tmp_path))
    config = mcp_config(target, python="python")
    assert list(config["mcpServers"]) == [SERVER_NAME] and config["mcpServers"][SERVER_NAME]["args"] == ["-m", "jarvis", "remotion-mcp"]
    path = write_mcp_config(target, tmp_path / "out")
    assert path.name == "remotion-mcp.json" and json.loads(path.read_text(encoding="utf-8")) == mcp_config(target, python=None)
    assert "token" not in path.read_text(encoding="utf-8").lower().replace("token_file", "")


def test_the_brain_prompt_declares_remotion_only_in_the_studio_programs():
    from jarvis.runtime import claude_local
    from jarvis.runtime.prompt_catalog import conversation_session_name

    assert conversation_session_name(tools=True, display=True, hands=False, studio=True).count("studio") == 1
    prompt = claude_local.BRAIN_REMOTION_PROMPT
    for tool in TOOL_NAMES:
        assert tool in prompt, f"{tool} absent de la consigne"
    assert len(prompt.encode("utf-8")) <= 2_600, "consigne serrée"
    assert "Slidecar" in prompt and "ne se change jamais par toi" in prompt
    assert "n'ouvre rien" in prompt
