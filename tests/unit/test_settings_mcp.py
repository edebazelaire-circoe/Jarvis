"""Les réglages du Control Center, ouverts au cerveau (20/09/2026).

Ce que ce fichier épingle :

- **le catalogue** : trois outils, dans l'ordre du contrat, et un vrai serveur
  stdio qui les liste — pas un faux ;
- **l'interrupteur maître de Bare Hands est atteignable**, dans les deux sens,
  contre un vrai Control Center ; c'est la demande de l'utilisateur, répétée
  trois fois, et le trou que ce chantier comble ;
- **la trappe n'existe pas** : le serveur des réglages est déclaré au cerveau
  *sans condition*, donc éteindre Bare Hands n'emporte pas l'outil qui le
  rallume. C'est la propriété qui a décidé de l'architecture, et elle se casse
  silencieusement si quelqu'un ajoute un garde ;
- **aucune consigne ne renvoie le geste à l'utilisateur** : ni l'instruction du
  serveur, ni les descriptions d'outils, ni la consigne système du cerveau.

Le Control Center est réel (`ControlCenter` sur un port éphémère, son propre
`runtime_root`), pas un double : la difficulté de ces outils est la forme exacte
du corps HTTP par réglage, et un faux serveur l'aurait acceptée quelle qu'elle
soit.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.barehands_mcp import BarehandsMcpTarget
from jarvis.runtime.settings_mcp import (
    SERVER_NAME,
    TOOL_NAMES,
    ConsoleMcpTarget,
    ConsoleSettingsTools,
    ConsoleToolError,
    build_server,
    mcp_config,
)


@pytest.fixture
async def center(tmp_path, aiohttp_unused_port=None):
    """Un vrai Control Center, sur un port libre, avec son propre fichier de réglages."""

    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    await control.start(port=port)
    try:
        yield control, port
    finally:
        await control.stop()


@pytest.fixture
async def tools(center):
    control, port = center
    console = ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", port))
    try:
        yield console
    finally:
        await console.close()


async def test_the_master_switch_of_bare_hands_goes_both_ways(tools, center):
    """« éteins complètement Bare Hands » : le geste que JARVIS renvoyait à l'utilisateur.

    Le constat qui a ouvert ce chantier est que `barehands_activate` et
    `barehands_deactivate` ne font que le réveil et la veille : aucun outil
    n'atteignait `enabled`. Ici on écrit, puis on **relit sur le serveur**, pas
    dans la réponse de l'outil.
    """

    control, _ = center
    from jarvis.runtime import barehands_test_mode as barehands

    # Par défaut Bare Hands est éteint : on l'allume d'abord, sinon « éteindre »
    # ne changerait rien et le test passerait sans rien prouver.
    await tools.set("barehands.enabled", True)
    off = await tools.set("barehands.enabled", False)
    assert off["before"] is True and off["after"] is False and off["changed"] is True
    assert barehands.load(control._settings())["enabled"] is False

    on = await tools.set("barehands.enabled", True)
    assert on["before"] is False and on["after"] is True
    assert barehands.load(control._settings())["enabled"] is True


async def test_the_words_of_speech_reach_the_switch(tools):
    """« éteins » arrive au cerveau en mots, pas en booléen JSON.

    Un modèle rend ce réglage tantôt `false`, tantôt `"false"`, tantôt « non ».
    Refuser la chaîne ferait échouer une demande parfaitement claire sur une
    question de typage que l'utilisateur n'a jamais posée.
    """

    for spoken in ("false", "off", "non", False, 0):
        assert (await tools.set("barehands.enabled", spoken))["after"] is False
        assert (await tools.set("barehands.enabled", "oui"))["after"] is True


async def test_writing_one_bare_hands_setting_keeps_the_other_eight(tools, center):
    """La route exige `enabled` à chaque écriture : l'oublier éteindrait Bare Hands par accident."""

    control, _ = center
    from jarvis.runtime import barehands_test_mode as barehands

    await tools.set("barehands.enabled", True)
    before = dict(barehands.load(control._settings()))
    await tools.set("barehands.sensitivity", 2.5)
    after = barehands.load(control._settings())
    assert after["sensitivity"] == 2.5
    assert after["enabled"] is True
    for key in before:
        if key != "sensitivity":
            assert after[key] == before[key], key


async def test_a_value_out_of_bounds_is_refused_with_the_reason(tools):
    with pytest.raises(ConsoleToolError) as failure:
        await tools.set("barehands.sensitivity", 99)
    assert failure.value.code == "settings_out_of_range"
    assert "4" in str(failure.value)


async def test_an_unknown_setting_points_at_the_catalogue(tools):
    with pytest.raises(ConsoleToolError) as failure:
        await tools.set("barehands.turbo", True)
    assert failure.value.code == "settings_unknown_option"
    assert "settings_describe" in str(failure.value)


async def test_the_catalogue_covers_the_interface_beyond_bare_hands(tools):
    """Le chantier ne livre pas un interrupteur : il livre les réglages."""

    shown = await tools.describe()
    for option_id in ("barehands.enabled", "scene.enabled", "openai.voice",
                      "cli.delegation_mode", "self_development.enabled"):
        assert option_id in shown, option_id
    # Les sept catégories du schéma vocal plus les quatre familles ajoutées.
    for category in ("hands", "scene", "agent", "self_development", "turn_taking", "models"):
        assert await tools.describe(category=category)


async def test_a_diagnostic_projection_says_it_is_read_only_not_that_it_belongs_to_the_user(tools):
    """Un refus légitime nomme la couche, jamais une permission de l'utilisateur."""

    with pytest.raises(ConsoleToolError) as failure:
        await tools.set("authorization.status", "x")
    assert failure.value.code == "settings_readonly"
    message = str(failure.value)
    assert "l'interface ne l'écrit pas non plus" in message
    assert "utilisateur" not in message or "l'interface" in message


async def test_no_instruction_sends_the_gesture_back_to_the_user():
    """La phrase que l'utilisateur refuse, sous toutes ses formes, dans toute la surface.

    Elle est revenue une fois déjà : le chantier de la scène l'avait retirée du
    prompt d'affichage, et elle survivait dans les descriptions d'outils.
    """

    from jarvis.runtime import barehands_mcp, claude_local, settings_mcp

    server = build_server(tools=ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", 1)))
    listed = await server.list_tools()
    texts = [settings_mcp._SERVER_INSTRUCTIONS, claude_local.BRAIN_SETTINGS_PROMPT,
             claude_local.BRAIN_BAREHANDS_PROMPT, barehands_mcp._SERVER_INSTRUCTIONS]
    texts += [tool.description or "" for tool in listed]
    for text in texts:
        lowered = text.lower()
        for banned in ("l'interrupteur est à lui", "appartient à l'utilisateur",
                       "seul l'utilisateur", "c'est à l'utilisateur de"):
            assert banned not in lowered, (banned, text[:120])
    # Et la consigne dit explicitement de ne pas y renvoyer.
    assert "Ne le renvoie jamais au Control Center" in claude_local.BRAIN_SETTINGS_PROMPT


async def test_the_tool_catalogue_is_what_the_contract_says():
    server = build_server(tools=ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", 1)))
    listed = await server.list_tools()
    assert tuple(tool.name for tool in listed) == TOOL_NAMES
    for tool in listed:
        assert tool.inputSchema.get("additionalProperties") is False, tool.name
        assert tool.description, tool.name


async def test_the_console_subcommand_serves_over_stdio(tmp_path, center):
    """Le vrai processus, le vrai protocole : `python -m jarvis console-mcp`."""

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    import os

    _, port = center
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jarvis", "console-mcp"],
        env={**os.environ, "JARVIS_CONTROL_CENTER_HOST": "127.0.0.1",
             "JARVIS_CONTROL_CENTER_PORT": str(port), "JARVIS_RUNTIME_DIR": str(tmp_path)},
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert tuple(tool.name for tool in listed.tools) == TOOL_NAMES
            result = await session.call_tool(
                "settings_set", {"option_id": "barehands.enabled", "value": True}
            )
            assert result.isError is False
            assert json.loads(result.content[0].text)["after"] is True


# --------------------------------------------------------------- pas de trappe


async def test_the_settings_server_is_declared_to_the_brain_without_any_gate(tmp_path):
    """**La propriété qui a décidé de l'architecture.**

    Les serveurs `jarvis-display` et `jarvis-barehands` sont retirés au cerveau
    quand leur réglage est faux. Si celui-ci l'était aussi, le premier
    « éteins Bare Hands » emporterait l'outil capable de le rallumer, et le
    cerveau serait enfermé dans l'état éteint — une extinction qu'il ne pourrait
    pas défaire. Ce test échoue si quelqu'un ajoute un garde ici.
    """

    from jarvis.runtime import barehands_test_mode as barehands
    from jarvis.runtime.claude_local import ClaudeLocalAgent

    control = ControlCenter(
        runtime_root=tmp_path, project_root=tmp_path,
        console_mcp=ConsoleMcpTarget("127.0.0.1", 17654, tmp_path),
        barehands_mcp=BarehandsMcpTarget("127.0.0.1", 17654, tmp_path),
    )
    # L'agent que le centre pilote lui-même, pas un double : c'est sur celui-là
    # que `_apply_agent_settings` agit.
    agent = control.agent
    assert isinstance(agent, ClaudeLocalAgent)

    for switch in (True, False):
        settings = control._settings()
        barehands.apply(settings, {"enabled": switch})
        control._write_settings(settings)
        control._apply_agent_settings(settings)
        assert agent.console_mcp is not None, f"retiré alors que barehands.enabled={switch}"
        assert (agent.barehands_mcp is not None) is switch


async def test_the_launched_brain_always_carries_the_settings_config(tmp_path):
    """Le vrai argv : un `--mcp-config` de plus, présent quels que soient les interrupteurs."""

    from jarvis.runtime.claude_local import ClaudeLocalAgent

    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path,
                             console_mcp=ConsoleMcpTarget("127.0.0.1", 17654, tmp_path))
    args = agent._console_mcp_args()
    assert args and args[0] == "--mcp-config"
    written = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    assert SERVER_NAME in written["mcpServers"]
    assert written["mcpServers"][SERVER_NAME]["args"] == ["-m", "jarvis", "console-mcp"]

    # Sans cible (cas de panne d'écriture uniquement), rien — mais ce n'est
    # jamais un choix de l'utilisateur.
    assert ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)._console_mcp_args() == []


def test_the_mcp_config_names_its_own_subcommand(tmp_path):
    document = mcp_config(ConsoleMcpTarget("127.0.0.1", 17654, tmp_path), python="py")
    entry = document["mcpServers"][SERVER_NAME]
    assert entry["command"] == "py" and entry["type"] == "stdio"
    assert entry["env"]["JARVIS_CONTROL_CENTER_PORT"] == "17654"
