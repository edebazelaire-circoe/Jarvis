"""Liste de contrôle : tout ce que Core sait faire est exposé ET documenté, pour chaque porte d'entrée.

Constat du 2026-10-07 : « active Bare Hands » recevait « je ne sais même pas ce
que c'est ». Trois listes décidaient de ce que chaque voix et chaque cerveau
connaît (outils MCP déclarés, consignes, outils de surface) et rien ne les
comparait. Ce fichier est la comparaison, et il est volontairement fait pour
échouer :

- une action de Core (`v2_policy.POLICIES`) sans ligne dans
  `brain_capabilities.CORE_ACTION_COVERAGE` ;
- un outil d'un serveur que JARVIS déclare au cerveau, absent de sa consigne ;
- un serveur déclaré qu'aucune famille de `brain_capabilities.CAPABILITIES` ne
  nomme, donc que les voix de surface ne savent pas qu'elles ont ;
- une famille que la consigne d'une voix de surface (GPT-Live duplex, Simple /
  Front Brain, legacy) ne nomme pas ;
- un « manque connu » (`gap`) ou une écriture retenue (`withheld`) qui serait en
  réalité exposé.

La preuve porte sur le **vrai** lancement du cerveau (l'argv que reçoit le CLI,
les `--mcp-config` écrits, la consigne système envoyée), pas sur des constantes.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_display_mcp import _launch, _prompt  # noqa: E402 - le harnais de lancement, réutilisé

from jarvis.domain import brain_capabilities as caps  # noqa: E402
from jarvis.domain.live_prompt import LIVE_OPERATING_RULES  # noqa: E402
from jarvis.domain.conversation_prompt import CONVERSATION_OPERATING_RULES  # noqa: E402
from jarvis.adapters.openai_realtime import CONTINUOUS_BRAIN_OPERATING_RULES, OPERATING_RULES  # noqa: E402
from jarvis.runtime import mcp_tool_meta  # noqa: E402
from jarvis.runtime.barehands_mcp import BarehandsMcpTarget  # noqa: E402
from jarvis.runtime.claude_local import ClaudeLocalAgent  # noqa: E402
from jarvis.runtime.display_mcp import DisplayMcpTarget  # noqa: E402
from jarvis.runtime.drive_mcp import DriveMcpTarget  # noqa: E402
from jarvis.runtime.realtime_tools import REALTIME_TOOLS, tools_for  # noqa: E402
from jarvis.runtime.settings_mcp import ConsoleMcpTarget  # noqa: E402
from jarvis.runtime.tools_gateway_mcp import ToolsGatewayTarget  # noqa: E402
from jarvis.security.v2_policy import POLICIES  # noqa: E402

#: Outils documentés **par famille** dans la consigne : leur nom nu n'y figure pas,
#: la famille y est nommée. La consigne du tour (« Mode CALIBRATION ») porte leurs règles.
GROUP_DOCUMENTED = {"calibration_": "calibration_*"}


@pytest.fixture
async def brain(monkeypatch, tmp_path):
    """Le cerveau conversationnel lancé pour de vrai, toutes cibles posées, Bare Hands **éteint**."""

    runtime = tmp_path / "runtime"
    token = tmp_path / "core.token"
    token.write_text("secret-" * 8, encoding="utf-8")
    agent = ClaudeLocalAgent(
        runtime_root=runtime, cwd=tmp_path,
        display_mcp=DisplayMcpTarget("127.0.0.1", 17999, token, runtime),
        barehands_mcp=BarehandsMcpTarget("127.0.0.1", 17654, runtime),
        console_mcp=ConsoleMcpTarget("127.0.0.1", 17654, runtime),
        capture_mcp=ConsoleMcpTarget("127.0.0.1", 17654, runtime),
        workspace_mcp=ConsoleMcpTarget("127.0.0.1", 17654, runtime),
        memory_mcp=ConsoleMcpTarget("127.0.0.1", 17654, runtime),
        drive_mcp=DriveMcpTarget(runtime_root=runtime),
        tools_mcp=ToolsGatewayTarget(core_host="127.0.0.1", core_port=17653, token_file=token, runtime_root=runtime),
    )
    argv = await _launch(monkeypatch, agent)
    declared: list[str] = []
    for index, arg in enumerate(argv):
        if arg == "--mcp-config":
            declared += list(json.loads(Path(argv[index + 1]).read_text(encoding="utf-8"))["mcpServers"])
    return {"servers": declared, "prompt": _prompt(argv, "--append-system-prompt")}


def _mentioned(prompt: str, tool: str) -> bool:
    if tool in prompt:
        return True
    return any(tool.startswith(prefix) and group in prompt for prefix, group in GROUP_DOCUMENTED.items())


# ------------------------------------------------------------------ actions de Core


def test_every_core_action_is_classified_for_the_brain():
    assert set(POLICIES) == set(caps.COVERAGE_BY_ACTION), (
        "Action de Core sans ligne dans brain_capabilities.CORE_ACTION_COVERAGE (ou ligne orpheline) : "
        f"{sorted(set(POLICIES) ^ set(caps.COVERAGE_BY_ACTION))}")


def test_every_tool_given_to_the_legacy_surface_is_a_core_action():
    surface = {tool["name"] for tool in REALTIME_TOOLS} - {"claude_task"}
    assert surface <= set(POLICIES), sorted(surface - set(POLICIES))


@pytest.mark.parametrize("coverage", [c for c in caps.CORE_ACTION_COVERAGE
                                      if c.status in (caps.BRAIN_EXPOSED, caps.BRAIN_EQUIVALENT)],
                         ids=lambda c: c.action)
async def test_an_exposed_core_action_is_declared_and_documented_for_the_brain(brain, coverage):
    assert coverage.server in brain["servers"], f"{coverage.action} : {coverage.server} n'est pas déclaré au cerveau"
    meta = mcp_tool_meta.server_meta(coverage.server)
    assert coverage.tools, coverage.action
    for tool in coverage.tools:
        assert tool in meta.tools, f"{coverage.action} : {tool} n'existe pas dans {coverage.server}"
        assert _mentioned(brain["prompt"], tool), f"{coverage.action} : {tool} n'est pas dans la consigne du cerveau"


@pytest.mark.parametrize("coverage", [c for c in caps.CORE_ACTION_COVERAGE
                                      if c.status in (caps.BRAIN_WITHHELD, caps.BRAIN_GAP, caps.BRAIN_VIA_GATEWAY)],
                         ids=lambda c: c.action)
def test_a_withheld_gap_or_gateway_action_says_why_and_is_not_secretly_exposed(coverage):
    assert coverage.note.strip(), f"{coverage.action} : un manque ou une retenue sans raison écrite"
    for meta in mcp_tool_meta.SERVERS:
        if meta.server == "jarvis-tools":
            continue
        assert coverage.action not in meta.tools, (
            f"{coverage.action} est déclaré comme {coverage.status} mais {meta.server} l'expose : mets le statut à jour")


def test_drive_writes_are_not_given_to_the_brain():
    from jarvis.runtime import drive_mcp

    meta = mcp_tool_meta.server_meta("jarvis-drive")
    assert set(meta.tools) == set(drive_mcp.READ_ONLY_TOOLS)
    assert not set(meta.tools) & set(drive_mcp.WRITE_TOOLS)


# ------------------------------------------------------------------ cerveau Claude


async def test_every_jarvis_declared_server_is_really_declared_to_the_brain(brain):
    expected = {meta.server for meta in mcp_tool_meta.SERVERS if meta.registration == "jarvis"}
    assert expected <= set(brain["servers"]), sorted(expected - set(brain["servers"]))


async def test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt(brain):
    missing = {meta.server: [tool for tool in meta.tools if not _mentioned(brain["prompt"], tool)]
               for meta in mcp_tool_meta.SERVERS if meta.server in brain["servers"] and meta.server != "jarvis-tools"}
    missing = {server: tools for server, tools in missing.items() if tools}
    assert not missing, f"Outils exposés au cerveau mais absents de sa consigne : {missing}"


async def test_bare_hands_is_known_to_the_brain_even_when_it_is_switched_off(brain):
    """Cause du 2026-10-07 : éteint, ni le serveur ni la consigne n'existaient."""

    prompt = brain["prompt"]
    assert "jarvis-barehands" in brain["servers"]
    assert "barehands_activate" in prompt
    assert "settings_set(barehands.enabled, true)" in prompt
    assert "active Bare Hands" in prompt


# ------------------------------------------------------------------ voix de surface


def test_every_declared_server_is_named_by_a_capability_the_surfaces_are_told_about():
    named = {server for capability in caps.CAPABILITIES for server in capability.servers}
    jarvis_servers = {meta.server for meta in mcp_tool_meta.SERVERS if meta.registration == "jarvis"}
    assert jarvis_servers <= named, f"Serveurs que les voix de surface ne savent pas avoir : {sorted(jarvis_servers - named)}"
    assert named <= {meta.server for meta in mcp_tool_meta.SERVERS}


@pytest.mark.parametrize("capability", caps.CAPABILITIES, ids=lambda c: c.id)
@pytest.mark.parametrize("surface,text", [
    ("duplex GPT-Live", LIVE_OPERATING_RULES),
    ("Simple / Front Brain", CONVERSATION_OPERATING_RULES),
    ("legacy", OPERATING_RULES),
])
def test_every_surface_prompt_names_every_capability(surface, text, capability):
    assert capability.keyword in text, f"{surface} ne mentionne pas « {capability.keyword} » : il répondrait qu'il ne sait pas"


def test_the_duplex_surface_is_told_not_to_refuse_what_the_backend_can_do():
    assert "never answer that you cannot" in LIVE_OPERATING_RULES
    assert "Bare Hands" in LIVE_OPERATING_RULES


def test_the_continuous_surface_owns_nothing_and_leaves_everything_to_the_brain():
    """Exemption nommée : en mode continu la surface n'a aucun outil et ne répond jamais sur le fond."""

    assert tools_for(continuous_brain=True) == []
    assert "appartient au cerveau" in CONTINUOUS_BRAIN_OPERATING_RULES


# ------------------------------------------------------------------ Drive en lecture seule


def test_the_read_only_drive_server_registers_no_write_tool():
    import asyncio

    from jarvis.runtime import drive_mcp

    async def names(read_only: bool) -> set[str]:
        return {tool.name for tool in await drive_mcp.build_server(read_only=read_only).list_tools()}

    assert asyncio.run(names(True)) == set(drive_mcp.READ_ONLY_TOOLS)
    assert asyncio.run(names(False)) == set(drive_mcp.READ_ONLY_TOOLS) | set(drive_mcp.WRITE_TOOLS)


def test_the_drive_config_carries_the_read_only_marker(tmp_path):
    from jarvis.runtime import drive_mcp

    path = drive_mcp.write_mcp_config(DriveMcpTarget(runtime_root=tmp_path), tmp_path)
    server = json.loads(path.read_text(encoding="utf-8"))["mcpServers"][drive_mcp.SERVER_NAME]
    assert server["args"] == ["-m", "jarvis", "drive-mcp"]
    assert server["env"] == {drive_mcp.ENV_READ_ONLY: "1"}
    assert drive_mcp.read_only_from_env(server["env"]) is True
    assert drive_mcp.read_only_from_env({}) is False
