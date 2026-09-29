"""Les réglages du Control Center, ouverts au cerveau (20/09/2026).

Ce que ce fichier épingle :

- **le catalogue** : trois outils de réglages puis neuf outils Board/Session
  (Slice 05 board-session, section en fin de fichier), dans l'ordre du
  contrat, et un vrai serveur stdio qui les liste — pas un faux ;
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


# ------------------------------------------------------- mode d'interaction


@pytest.fixture
async def moded(tmp_path):
    """Un vrai Control Center **relié à un vrai service Core du mode** : sans Core,
    `POST /api/interaction-mode` enregistre mais répond 503, et on ne prouverait
    rien de l'effet à chaud."""

    import socket

    from jarvis.core.interaction_mode import InteractionModeService
    from jarvis.runtime.interaction_mode_view import CoreInteractionModeView
    from test_interaction_mode_control_plane import RecordingBus, ServiceReader

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    service = InteractionModeService(events=RecordingBus())
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path,
                            interaction_mode_view=CoreInteractionModeView(ServiceReader(service)))
    await control.start(port=port)
    console = ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", port))
    try:
        yield console, control, service, port
    finally:
        await console.close()
        await control.stop()


async def _status_mode(port: int) -> dict:
    """Ce que lit le sélecteur du bas-gauche : `interaction_mode` de `GET /api/status`."""

    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}/api/status") as response:
            return (await response.json())["interaction_mode"]


async def test_the_interaction_mode_is_found_by_the_words_the_brain_searched(moded):
    """« présentation », « interaction », « réunion » : les trois recherches du 29/09 revenues vides."""

    tools, *_ = moded
    for needle in ("présentation", "interaction", "réunion", "simple"):
        shown = await tools.describe(search=needle)
        assert "interaction_mode" in shown, needle
    line = await tools.describe(category="interaction")
    assert "[assistant, presentation, meeting]" in line


async def test_the_brain_switches_to_presentation_like_the_selector(moded):
    """« Passe en mode présentation » : même effet que le sélecteur, à chaud, relu."""

    tools, control, service, port = moded
    from jarvis.runtime import interaction_mode_settings

    done = await tools.set("interaction_mode", "présentation")
    assert done["before"] == "assistant" and done["after"] == "presentation"
    assert done["changed"] is True and done["restart_required"] is None
    # Enregistré, appliqué par Core, et vu par l'écran.
    assert interaction_mode_settings.load(control._settings()).value == "presentation"
    assert service.snapshot()["mode"] == "presentation"
    status = await _status_mode(port)
    assert status["mode"] == "presentation" and status["core_reachable"] is True

    back = await tools.set("interaction_mode", "SIMPLE")
    assert back["after"] == "assistant"
    assert service.snapshot()["mode"] == "assistant"
    assert (await _status_mode(port))["mode"] == "assistant"
    assert (await tools.get(["interaction_mode"]))["settings"]["interaction_mode"]["value"] == "assistant"


async def test_meeting_is_refused_with_the_servers_sentence(moded):
    """RÉUNION est annoncé, pas activable : le refus du serveur, tel quel, et rien de changé."""

    tools, _control, service, _port = moded
    with pytest.raises(ConsoleToolError) as failure:
        await tools.set("interaction_mode", "réunion")
    assert failure.value.code == "interaction_mode_not_implemented"
    assert service.snapshot()["mode"] == "assistant"
    with pytest.raises(ConsoleToolError) as failure:
        await tools.set("interaction_mode", "duplex")
    assert failure.value.code == "settings_bad_value"


# ============================================================ Boards et Sessions (board-session, Slice 05)
#
# Neuf outils de plus sur `jarvis-console`, qui passent par les **mêmes routes
# que l'écran** (`/api/boards*`, `/api/sessions*` du Control Center, relais de
# Core). Deux étages de preuve :
#
# - un **faux Control Center** scripté : chaque outil, son verbe, sa route, son
#   corps exact, chaque code d'erreur stable et le résultat `scheduled` ;
# - un **vrai Control Center relié à un vrai Core** (pile de
#   `test_board_switch_control_center`) : les outils font ce que l'écran fait,
#   y compris la bascule différée pendant un tour du cerveau.

import asyncio  # noqa: E402

import jsonschema  # noqa: E402
from aiohttp import web  # noqa: E402
from aiohttp.test_utils import make_mocked_request  # noqa: E402

from jarvis.runtime import console_boards  # noqa: E402
from jarvis.runtime.board_routes import BoardSessionRoutes  # noqa: E402
from jarvis.runtime.journal import RuntimeJournal  # noqa: E402

BOARD_TOOLS = ("board_list", "board_get", "board_get_active", "board_create", "board_update", "board_archive",
               "board_switch", "session_current", "session_new")

_T = "2026-09-29T10:00:00+00:00"


def _board(board_id: str = "board_ab12", title: str = "Recherche", **extra) -> dict:
    """La forme exacte de `Board.to_payload()` : un champ de plus ou de moins ferait mentir le faux."""

    return {"board_id": board_id, "title": title, "status": "active", "created_at": _T, "updated_at": _T,
            "last_opened_at": None, "context_summary": "", "task_refs": [], "artifact_refs": [],
            "project_refs": [], "scene_ref": {"kind": "global", "scene_id": "scene", "revision_at_leave": 3},
            "interaction_mode": "assistant", "interaction_mode_origin": "unset",
            "runtime_metadata": {"k": "v"}, **extra}


_SESSION = {"jarvis_session_id": "jsess_old", "started_at": _T, "ended_at": None, "end_reason": None,
            "status": "open", "active_board_id": "default", "visited_board_ids": ["default"]}
_BINDING = {"jarvis_session_id": "jsess_old", "board_id": "default", "conversation_id": "conv-1",
            "agent_cli": "claude", "agent_session_id": None, "lifecycle": "foreground", "created_at": _T,
            "last_active_at": _T, "status": "open"}


class FakeControlCenter:
    """Un Control Center scripté : chaque requête est notée, chaque réponse est choisie par le test."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict, object]] = []
        self.answers: dict[tuple[str, str], tuple[int, object]] = {}
        self.runner: web.AppRunner | None = None
        self.port = 0

    def answer(self, method: str, path: str, status: int, body: object) -> None:
        self.answers[(method, path)] = (status, body)

    async def _handle(self, request: web.Request) -> web.Response:
        raw = await request.read()
        body = json.loads(raw) if raw else None
        self.requests.append((request.method, request.path, dict(request.query), body))
        status, answer = self.answers.get((request.method, request.path), (404, {"error": {
            "code": "http_error", "message": "not scripted"}}))
        if isinstance(answer, str):
            return web.Response(status=status, text=answer)
        return web.json_response(answer, status=status)

    async def start(self) -> None:
        import socket

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        await web.TCPSite(self.runner, "127.0.0.1", self.port).start()

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None


@pytest.fixture
async def fake_cc(tmp_path):
    fake = FakeControlCenter()
    await fake.start()
    console = ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", fake.port, tmp_path),
                                   journal=RuntimeJournal(tmp_path))
    try:
        yield fake, console
    finally:
        await console.close()
        await fake.stop()


def _journal(tmp_path, kind: str) -> list[dict]:
    path = tmp_path / "trace.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("kind") == kind]


async def _is_ui_route(method: str, path: str) -> bool:
    """La requête tombe-t-elle sur une route du relais que l'écran appelle (`BoardSessionRoutes.routes()`) ?"""

    async def idle() -> None:
        return None

    app = web.Application()
    app.add_routes(BoardSessionRoutes(transport=None, journal=None, ask_in_flight=lambda: False,
                                      wait_asks_idle=idle).routes())
    match = await app.router.resolve(make_mocked_request(method, path, app=app))
    return match.http_exception is None


# ------------------------------------------------------------ catalogue


async def test_the_board_tools_follow_the_settings_tools_in_registration_order():
    assert TOOL_NAMES == ("settings_describe", "settings_get", "settings_set", *BOARD_TOOLS)
    server = build_server(tools=ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", 1)))
    listed = {tool.name: tool for tool in await server.list_tools()}
    assert tuple(listed) == TOOL_NAMES
    for name in ("board_get", "board_update", "board_archive", "board_switch"):
        assert listed[name].inputSchema["required"][0] == "board_id"
        assert listed[name].inputSchema["properties"]["board_id"]["pattern"] == r"^(default|board_[A-Za-z0-9_-]+)$"
    for name in ("board_get_active", "session_current", "session_new"):
        assert listed[name].inputSchema["properties"] == {}, name
    create = listed["board_create"].inputSchema
    assert create["required"] == ["title"]
    assert set(create["properties"]) == {"title", "context_summary", "task_refs", "artifact_refs", "project_refs"}
    assert create["properties"]["title"]["maxLength"] == 120
    for name in BOARD_TOOLS:
        assert listed[name].outputSchema is not None, name  # résultat typé (contrat §5.2)


async def test_no_low_level_voice_brain_or_authority_tool_is_exposed():
    """06 section D : ni bind_voice, ni attach_brain, ni autorité de parole. Seulement des opérations de haut niveau."""

    server = build_server(tools=ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", 1)))
    for tool in await server.list_tools():
        for banned in ("voice", "bind", "attach", "authority", "speech", "brain", "foreground"):
            assert banned not in tool.name, tool.name
        assert "origin" not in tool.inputSchema["properties"], tool.name  # jamais choisi par le modèle


async def test_the_descriptions_say_what_a_board_and_a_new_session_are():
    """Le modèle doit comprendre : Board = espace de travail ; bascule = conversation + voix, le fond continue ;
    nouvelle Session = fil neuf sans toucher Boards ni tâches ; « nouvelle conversation » y mène."""

    from jarvis.runtime import settings_mcp

    server = build_server(tools=ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", 1)))
    described = {tool.name: tool.description for tool in await server.list_tools()}
    assert "espace de travail" in described["board_list"]
    assert "la conversation et la voix passent sur ce Board" in described["board_switch"]
    assert "garde son travail de fond" in described["board_switch"]
    assert "scheduled" in described["board_switch"] and "scheduled" in described["session_new"]
    assert "nouvelle conversation" in described["session_new"] and "nouvelle session" in described["session_new"]
    assert "Ne touche ni aux Boards ni aux tâches" in described["session_new"]
    assert "Ne bascule pas" in described["board_create"] and "board_switch" in described["board_create"]
    instructions = settings_mcp._SERVER_INSTRUCTIONS
    for words in ("espace de travail", "board_switch", "session_new", "nouvelle conversation", "scheduled"):
        assert words in instructions, words


# ------------------------------------------------------------ comportement contre un faux Control Center


async def test_board_list_reads_the_ui_route_and_marks_the_active_board(fake_cc, tmp_path):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards", 200, {"boards": [_board("default", "Jarvis"), _board()],
                                            "active_board_id": "default"})
    listed = await console.boards.list_boards()
    assert fake.requests == [("GET", "/api/boards", {}, None)]
    assert listed["active_board_id"] == "default"
    assert [(b["board_id"], b["active"]) for b in listed["boards"]] == [("default", True), ("board_ab12", False)]
    assert set(listed["boards"][0]) == {"board_id", "title", "status", "active", "interaction_mode", "last_opened_at"}
    await console.boards.list_boards(include_archived=True)
    assert fake.requests[-1] == ("GET", "/api/boards", {"include_archived": "true"}, None)
    assert _journal(tmp_path, "board.tool")[-1]["data"]["tool"] == "board_list"


async def test_board_get_and_get_active_show_the_board_without_runtime_fields(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(context_summary="Lot 2",
                                                                         task_refs=["t1"]), "active": False})
    fake.answer("GET", "/api/boards/active", 200, {"board": _board("default", "Jarvis"), "active": True})
    got = await console.boards.get_board("board_ab12")
    assert got["context_summary"] == "Lot 2" and got["task_refs"] == ["t1"] and got["active"] is False
    assert "scene_ref" not in got and "runtime_metadata" not in got and "interaction_mode_origin" not in got
    active = await console.boards.get_active()
    assert active["board_id"] == "default" and active["active"] is True
    assert [r[:2] for r in fake.requests] == [("GET", "/api/boards/board_ab12"), ("GET", "/api/boards/active")]


async def test_board_create_update_and_archive_send_the_ui_bodies(fake_cc):
    fake, console = fake_cc
    fake.answer("POST", "/api/boards", 201, {"board": _board(), "active": False})
    fake.answer("PATCH", "/api/boards/board_ab12", 200, {"board": _board(title="Veille"), "active": False})
    fake.answer("POST", "/api/boards/board_ab12/archive", 200, {"board": _board(status="archived"),
                                                                "active": False})
    created = await console.boards.create_board("Recherche", context_summary=None, task_refs=["t1"],
                                                artifact_refs=None, project_refs=None)
    assert created["board_id"] == "board_ab12"
    assert fake.requests[-1] == ("POST", "/api/boards", {}, {"title": "Recherche", "task_refs": ["t1"]})
    updated = await console.boards.update_board("board_ab12", title="Veille", context_summary=None)
    assert updated["title"] == "Veille"
    assert fake.requests[-1] == ("PATCH", "/api/boards/board_ab12", {}, {"title": "Veille"})
    archived = await console.boards.archive_board("board_ab12")
    assert archived["status"] == "archived"
    assert fake.requests[-1][:2] == ("POST", "/api/boards/board_ab12/archive")


async def test_board_update_without_any_field_is_refused_before_sending(fake_cc):
    fake, console = fake_cc
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.update_board("board_ab12", title=None, context_summary=None)
    assert failure.value.code == "invalid_board" and "Rien n'a été écrit" in str(failure.value)
    assert fake.requests == []


async def test_board_switch_is_asked_as_the_brain_and_says_scheduled_when_deferred(fake_cc, tmp_path):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch"})
    result = await console.boards.switch_board("board_ab12")
    assert fake.requests[-1] == ("POST", "/api/boards/switch", {}, {"board_id": "board_ab12", "origin": "brain"})
    assert result["status"] == "scheduled" and result["title"] == "Recherche"
    assert result["note"] == "Passage sur « Recherche » à la fin de ta réponse."  # une phrase, pour la voix (B2)
    assert "previous_board_id" not in result
    assert _journal(tmp_path, "board.tool")[-1]["data"]["status"] == "scheduled"


async def test_board_switch_applied_at_once_names_the_previous_board(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 200, {"session": _SESSION, "binding": _BINDING, "board": _board(),
                                                    "previous_board_id": "default", "changed": True})
    result = await console.boards.switch_board("board_ab12")
    assert result["status"] == "applied" and result["previous_board_id"] == "default"


async def test_board_switch_to_the_active_board_or_an_archived_one_sends_nothing(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/default", 200, {"board": _board("default", "Jarvis"), "active": True})
    fake.answer("GET", "/api/boards/board_old", 200, {"board": _board("board_old", status="archived"),
                                                      "active": False})
    fake.answer("GET", "/api/boards/pending", 200, {"ok": True, "pending": []})
    same = await console.boards.switch_board("default")
    assert same["status"] == "unchanged"
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.switch_board("board_old")
    assert failure.value.code == "board_archived"
    assert all(method == "GET" for method, *_ in fake.requests), "no switch posted"


async def test_session_current_reads_the_open_session(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    current = await console.boards.current_session()
    assert current == {"jarvis_session_id": "jsess_old", "started_at": _T, "active_board_id": "default",
                       "visited_board_ids": ["default"], "conversation_id": "conv-1"}


async def test_session_new_targets_the_session_it_read_and_says_scheduled(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    fake.answer("POST", "/api/sessions/new", 202, {"ok": True, "status": "scheduled", "action": "new_session"})
    result = await console.boards.new_session()
    assert fake.requests[-1] == ("POST", "/api/sessions/new", {},
                                 {"origin": "brain", "expected_session_id": "jsess_old"})
    assert result["status"] == "scheduled" and result["closed_session_id"] == "jsess_old"
    assert result["board_id"] == "default" and "jarvis_session_id" not in result
    assert result["note"] == "Nouvelle session à la fin de ta réponse." and result["merged"] is False

    fake.answer("POST", "/api/sessions/new", 201, {"session": {**_SESSION, "jarvis_session_id": "jsess_new"},
                                                   "binding": _BINDING, "closed_session": _SESSION})
    applied = await console.boards.new_session()
    assert applied["status"] == "applied" and applied["jarvis_session_id"] == "jsess_new"


@pytest.mark.parametrize(("status", "code"), [
    (404, "board_not_found"), (409, "board_archived"), (409, "board_is_active"), (409, "session_closed"),
    (404, "session_not_found"), (409, "brain_not_foreground"), (502, "board_activation_failed"),
    (500, "board_switch_rolled_back"), (400, "invalid_title"), (400, "context_summary_too_long"),
    (400, "invalid_board"), (400, "invalid_request"), (503, "core_unreachable"), (503, "core_unconfigured"),
])
async def test_every_stable_code_of_the_relay_becomes_a_coded_tool_error(fake_cc, tmp_path, status, code):
    fake, console = fake_cc
    fake.answer("POST", "/api/boards/board_ab12/archive", status,
                {"error": {"code": code, "message": f"core says {code}"}})
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.archive_board("board_ab12")
    assert failure.value.code == code
    message = str(failure.value)
    assert message.startswith(f"Refus {code} : ") and console_boards.ERROR_SENTENCES[code] in message
    assert f"core says {code}" in message  # la cause réelle, jamais remplacée
    failed = _journal(tmp_path, "board.tool_failed")[-1]
    assert failed["level"] == "warning" and failed["data"]["code"] == code and failed["data"]["status"] == status


async def test_a_switch_refused_by_core_keeps_its_code(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 502, {"error": {"code": "board_activation_failed",
                                                              "message": "cli did not start"}})
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.switch_board("board_ab12")
    assert failure.value.code == "board_activation_failed" and "le Board actuel reste actif" in str(failure.value)


async def test_an_unreadable_answer_and_an_absent_control_center_are_said(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/active", 500, "Internal Server Error")
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.get_active()
    assert failure.value.code == "http_500" and "Internal Server Error" in str(failure.value)
    fake.answer("GET", "/api/boards/active", 200, "not json")
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.get_active()
    assert failure.value.code == "control_center_bad_response"
    fake.answer("GET", "/api/boards/active", 200, {"nope": 1})
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.get_active()
    assert failure.value.code == "control_center_bad_response"
    await fake.stop()
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.get_active()
    assert failure.value.code == "control_center_unreachable"


async def test_every_route_the_board_tools_hit_is_a_ui_route(fake_cc):
    """Parité avec l'écran : chaque requête des outils tombe sur une route du relais `BoardSessionRoutes`."""

    fake, console = fake_cc
    fake.answer("GET", "/api/boards", 200, {"boards": [], "active_board_id": "default"})
    fake.answer("GET", "/api/boards/active", 200, {"board": _board("default"), "active": True})
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards", 201, {"board": _board(), "active": False})
    fake.answer("PATCH", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/board_ab12/archive", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch"})
    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    fake.answer("POST", "/api/sessions/new", 202, {"ok": True, "status": "scheduled", "action": "new_session"})
    boards = console.boards
    await boards.list_boards()
    await boards.get_board("board_ab12")
    await boards.get_active()
    await boards.create_board("Recherche")
    await boards.update_board("board_ab12", title="X")
    await boards.archive_board("board_ab12")
    await boards.switch_board("board_ab12")
    await boards.current_session()
    await boards.new_session()
    hit = {(method, path) for method, path, *_ in fake.requests}
    assert len(hit) == 9
    for method, path in hit:
        assert path.startswith(("/api/boards", "/api/sessions")), path  # jamais Core (`/v1/...`)
        assert await _is_ui_route(method, path), (method, path)


# ------------------------------------------------------------ par le protocole MCP


async def test_through_mcp_a_deferred_switch_is_a_typed_scheduled_result(fake_cc):
    from mcp.shared.memory import create_connected_server_and_client_session

    fake, console = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch"})
    server = build_server(tools=console)
    advertised = {tool.name: tool.outputSchema for tool in await server.list_tools()}
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("board_switch", {"board_id": "board_ab12"})
    assert result.isError is False, result.content[0].text
    assert result.structuredContent["status"] == "scheduled"
    jsonschema.validate(result.structuredContent, advertised["board_switch"])
    assert json.dumps(result.structuredContent) == json.dumps(json.loads(result.content[0].text))


async def test_through_mcp_a_refusal_is_a_tool_error_with_its_code(fake_cc):
    from mcp.shared.memory import create_connected_server_and_client_session

    fake, console = fake_cc
    fake.answer("POST", "/api/boards/default/archive", 409, {"error": {"code": "board_is_active",
                                                                       "message": "the active board"}})
    async with create_connected_server_and_client_session(build_server(tools=console)) as session:
        result = await session.call_tool("board_archive", {"board_id": "default"})
    assert result.isError is True
    assert result.content[0].text.startswith("Refus board_is_active : ")


async def test_through_mcp_unknown_or_malformed_arguments_send_nothing(fake_cc):
    from mcp.shared.memory import create_connected_server_and_client_session

    fake, console = fake_cc
    async with create_connected_server_and_client_session(build_server(tools=console)) as session:
        extra = await session.call_tool("board_switch", {"board_id": "board_ab12", "origin": "user"})
        bad_id = await session.call_tool("board_get", {"board_id": "../v1/boards"})
        long_title = await session.call_tool("board_create", {"title": "x" * 121})
        none = await session.call_tool("session_new", {"force": True})
    assert extra.isError and "Arguments inconnus refusés, rien n'a été envoyé : origin" in extra.content[0].text
    assert bad_id.isError and bad_id.content[0].text.startswith("Argument invalide, rien n'a été envoyé")
    assert long_title.isError and "title" in long_title.content[0].text
    assert none.isError and "Arguments permis : aucun" in none.content[0].text
    assert fake.requests == []


# ------------------------------------------------------------ vrai Control Center + vrai Core


@pytest.fixture
async def real_stack(tmp_path):
    from tests.unit.test_board_switch_control_center import Stack

    stack = Stack(tmp_path)
    await stack.serve_control()
    port = int(stack.base.rsplit(":", 1)[1])
    console = ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", port))
    try:
        yield stack, console
    finally:
        await console.close()
        await stack.close()


async def test_the_tools_do_what_the_screen_does_on_a_real_control_center_and_core(real_stack):
    """Créer, lire, modifier, basculer (hors tour : appliqué), nouvelle Session, archiver : Core relu à chaque pas."""

    from mcp.shared.memory import create_connected_server_and_client_session

    from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
    from tests.unit.test_board_brains_control_center import trace

    stack, console = real_stack
    core = await stack.start_core()
    server = build_server(tools=console)
    advertised = {tool.name: tool.outputSchema for tool in await server.list_tools()}

    async with create_connected_server_and_client_session(server) as session:
        async def call(name: str, arguments: dict | None = None) -> dict:
            result = await session.call_tool(name, arguments or {})
            assert result.isError is False, (name, result.content[0].text)
            jsonschema.validate(result.structuredContent, advertised[name])  # contrat §5.1 (5)
            return result.structuredContent

        created = await call("board_create", {"title": "Recherche", "context_summary": "Veille techno"})
        board_id = created["board_id"]
        assert (await core.boards.get(board_id)).title == "Recherche"
        assert {b["board_id"] for b in (await call("board_list"))["boards"]} == {DEFAULT_BOARD_ID, board_id}
        assert (await call("board_get_active"))["board_id"] == DEFAULT_BOARD_ID
        await call("board_update", {"board_id": board_id, "task_refs": ["task-1"]})
        assert (await core.boards.get(board_id)).task_refs == ("task-1",)

        switched = await call("board_switch", {"board_id": board_id})
        assert switched["status"] == "applied" and switched["previous_board_id"] == DEFAULT_BOARD_ID
        assert (await core.sessions.current()).session.active_board_id == board_id
        assert (await call("board_switch", {"board_id": board_id}))["status"] == "unchanged"
        relayed = trace(stack.tmp_path, "board.request.relayed")[-1]["data"]
        assert relayed == {"action": "switch", "origin": "brain", "board_id": board_id}

        before = await call("session_current")
        fresh = await call("session_new")
        assert fresh["status"] == "applied" and fresh["closed_session_id"] == before["jarvis_session_id"]
        now = await core.sessions.current()
        assert now.session.jarvis_session_id == fresh["jarvis_session_id"] != before["jarvis_session_id"]
        assert now.session.active_board_id == board_id, "same Board"
        assert (await core.boards.get(board_id)).task_refs == ("task-1",), "Board untouched"

        refused = await session.call_tool("board_archive", {"board_id": board_id})
        assert refused.isError and refused.content[0].text.startswith("Refus board_is_active")
        archived = await call("board_archive", {"board_id": DEFAULT_BOARD_ID})
        assert archived["status"] == "archived"
        gone = await session.call_tool("board_switch", {"board_id": DEFAULT_BOARD_ID})
        assert gone.isError and gone.content[0].text.startswith("Refus board_archived")
        missing = await session.call_tool("board_get", {"board_id": "board_" + "0" * 32})
        assert missing.isError and missing.content[0].text.startswith("Refus board_not_found")


async def test_a_switch_and_a_new_session_asked_during_a_turn_are_scheduled_then_applied(real_stack):
    """Le cas réel : l'outil est appelé pendant le tour du cerveau. `scheduled`, puis appliqué après le tour."""

    from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
    from tests.unit.test_board_brains_control_center import JsonRequest, trace

    stack, console = real_stack
    core = await stack.start_core(with_host=False)
    stack.control.board_routes._grace_s = 0.05
    release = asyncio.Event()

    async def slow_ask(text: str, **_) -> dict:
        await release.wait()
        return {"ok": True, "text": "Je passe sur Recherche."}

    stack.control.agent.ask = slow_ask
    created = await console.boards.create_board("Recherche")
    first = (await core.sessions.current()).session.jarvis_session_id
    turn = asyncio.create_task(stack.control.agent_ask(JsonRequest({"text": "bascule sur Recherche"})))
    await asyncio.sleep(0.05)

    switched = await console.boards.switch_board(created["board_id"])
    renewed = await console.boards.new_session()
    assert switched["status"] == "scheduled" and renewed["status"] == "scheduled"
    assert renewed["closed_session_id"] == first
    current = await core.sessions.current()
    assert current.session.active_board_id == DEFAULT_BOARD_ID and current.session.jarvis_session_id == first

    release.set()
    await turn
    for _ in range(200):
        current = await core.sessions.current()
        if current.session.jarvis_session_id != first and current.session.active_board_id != DEFAULT_BOARD_ID:
            break
        await asyncio.sleep(0.02)
    assert current.session.active_board_id == created["board_id"]
    assert current.session.jarvis_session_id != first
    applied = {row["data"]["action"] for row in trace(stack.tmp_path, "board.request.deferred_applied")}
    assert applied == {"switch", "new_session"}


# ------------------------------------------------------------ reprise QA Slice 05 (B1, B2, B3)


_JARGON = ("tour", "Session", "scheduled", "arrière-plan", "Board actif", "Core", "binding", "foreground")


def _voice_sentence(note: str) -> None:
    """B2 : une seule phrase courte, sans vocabulaire interne, que la voix peut dire telle quelle."""

    assert len(note) <= 60, note
    assert note.endswith(".") and note.count(". ") == 0 and "\n" not in note, note
    assert not any(word in note for word in _JARGON), note


async def test_b2_every_note_is_one_short_sentence_for_the_voice(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("GET", "/api/boards/default", 200, {"board": _board("default", "Jarvis"), "active": True})
    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    notes = []
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch"})
    notes.append((await console.boards.switch_board("board_ab12"))["note"])
    fake.answer("POST", "/api/boards/switch", 200, {"session": _SESSION, "binding": _BINDING, "board": _board(),
                                                    "previous_board_id": "default", "changed": True})
    notes.append((await console.boards.switch_board("board_ab12"))["note"])
    fake.answer("GET", "/api/boards/pending", 200, {"ok": True, "pending": []})
    notes.append((await console.boards.switch_board("default"))["note"])
    fake.answer("GET", "/api/boards/pending", 200, {"ok": True, "pending": [{"action": "switch",
                                                                             "board_id": "board_ab12"}]})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch",
                                                    "replaced_board_id": "board_ab12"})
    notes.append((await console.boards.switch_board("default"))["note"])
    fake.answer("POST", "/api/sessions/new", 202, {"ok": True, "status": "scheduled", "action": "new_session"})
    notes.append((await console.boards.new_session())["note"])
    fake.answer("POST", "/api/sessions/new", 201, {"session": {**_SESSION, "jarvis_session_id": "jsess_new"},
                                                   "binding": _BINDING, "closed_session": _SESSION})
    notes.append((await console.boards.new_session())["note"])
    assert len(set(notes)) == 6
    for note in notes:
        _voice_sentence(note)


async def test_b3_a_switch_back_to_the_active_board_with_a_pending_switch_is_not_unchanged(fake_cc):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/default", 200, {"board": _board("default", "Jarvis"), "active": True})
    fake.answer("GET", "/api/boards/pending", 200, {"ok": True, "pending": [{"action": "switch",
                                                                             "board_id": "board_ab12"}]})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch",
                                                    "replaced_board_id": "board_ab12"})
    result = await console.boards.switch_board("default")
    assert result["status"] == "scheduled" and result["replaced_board_id"] == "board_ab12"
    assert result["note"] == "Tu restes sur « Jarvis »."
    assert fake.requests[-1] == ("POST", "/api/boards/switch", {}, {"board_id": "default", "origin": "brain"})


@pytest.mark.parametrize(("body", "code", "source"), [
    ({"error": {"code": "board_not_found", "message": "board x not found"}}, "board_not_found", "Core"),
    ({"error": {"code": "core_unreachable", "message": "Core is unreachable: refused"}}, "core_unreachable",
     "Control Center"),
    ({"error": {"code": "invalid_request", "message": "body must be JSON"}}, "invalid_request", "Control Center"),
    ("404: Not Found", "http_404", "Control Center"),
])
async def test_b3_a_refusal_is_attributed_to_who_wrote_it(fake_cc, tmp_path, body, code, source):
    fake, console = fake_cc
    fake.answer("GET", "/api/boards/active", 404 if isinstance(body, str) else 400, body)
    with pytest.raises(ConsoleToolError) as failure:
        await console.boards.get_active()
    message = str(failure.value)
    assert failure.value.code == code and f"({source} : " in message
    assert ("(Core : " in message) is (source == "Core")
    assert _journal(tmp_path, "board.tool_failed")[-1]["data"]["source"] == source


def test_b3_binding_refusals_say_what_to_do_next():
    assert "session_new" in console_boards.ERROR_SENTENCES["binding_not_found"]
    assert "session_current" in console_boards.ERROR_SENTENCES["binding_conflict"]
    for code in ("binding_not_found", "binding_conflict"):
        assert "dis-le à l'utilisateur" in console_boards.ERROR_SENTENCES[code]


async def _in_turn(stack):  # noqa: ANN202
    """Un tour du cerveau en vol sur le vrai Control Center ; rend (tâche du tour, déclencheur de fin)."""

    from tests.unit.test_board_brains_control_center import JsonRequest

    stack.control.board_routes._grace_s = 0.05
    release = asyncio.Event()

    async def slow_ask(text: str, **_) -> dict:
        await release.wait()
        return {"ok": True, "text": "ok"}

    stack.control.agent.ask = slow_ask
    turn = asyncio.create_task(stack.control.agent_ask(JsonRequest({"text": "tour"})))
    await asyncio.sleep(0.05)
    return turn, release


async def _settle(stack) -> None:  # noqa: ANN001
    for _ in range(300):
        if not stack.control.board_routes._pending and (stack.control.board_routes._runner is None
                                                        or stack.control.board_routes._runner.done()):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("deferred requests still pending")


async def test_b1_a_second_session_new_in_the_same_turn_is_merged_one_session_opens(real_stack):
    from tests.unit.test_board_brains_control_center import trace

    stack, console = real_stack
    core = await stack.start_core(with_host=False)
    before = len(await core.boards._repo.list_sessions(limit=100))
    first = (await core.sessions.current()).session.jarvis_session_id
    turn, release = await _in_turn(stack)

    one = await console.boards.new_session()
    two = await console.boards.new_session()
    assert one["status"] == two["status"] == "scheduled"
    assert one["merged"] is False and two["merged"] is True
    assert [item["action"] for item in (await stack.call("GET", "/api/boards/pending"))[1]["pending"]] == [
        "new_session"]

    release.set()
    await turn
    await _settle(stack)
    now = (await core.sessions.current()).session.jarvis_session_id
    assert now != first
    assert len(trace(stack.tmp_path, "board.request.deferred_applied")) == 1
    assert trace(stack.tmp_path, "board.request.deferred_failed") == []
    assert trace(stack.tmp_path, "board.request.deferred_merged")[-1]["level"] == "info"
    assert len(await core.boards._repo.list_sessions(limit=100)) == before + 1, "exactly one new Session"


async def test_b1_a_later_switch_replaces_the_pending_one(real_stack):
    from tests.unit.test_board_brains_control_center import trace

    stack, console = real_stack
    core = await stack.start_core(with_host=False)
    b = (await console.boards.create_board("Recherche"))["board_id"]
    c = (await console.boards.create_board("Veille"))["board_id"]
    turn, release = await _in_turn(stack)

    first = await console.boards.switch_board(b)
    second = await console.boards.switch_board(c)
    assert first["status"] == second["status"] == "scheduled" and second["replaced_board_id"] == b

    release.set()
    await turn
    await _settle(stack)
    session = (await core.sessions.current()).session
    assert session.active_board_id == c and b not in session.visited_board_ids, "B never switched to"
    assert [row["data"]["board_id"] for row in trace(stack.tmp_path, "board.request.deferred_applied")] == [c]
    assert trace(stack.tmp_path, "board.request.deferred_replaced")[-1]["data"]["replaced_board_id"] == b


async def test_b3_switching_back_to_the_current_board_cancels_the_pending_switch(real_stack):
    from jarvis.domain.workspace_board import DEFAULT_BOARD_ID

    stack, console = real_stack
    core = await stack.start_core(with_host=False)
    b = (await console.boards.create_board("Recherche"))["board_id"]
    turn, release = await _in_turn(stack)

    assert (await console.boards.switch_board(b))["status"] == "scheduled"
    back = await console.boards.switch_board(DEFAULT_BOARD_ID)
    assert back["status"] == "scheduled", "a pending switch exists: not unchanged"
    assert back["replaced_board_id"] == b and back["note"].startswith("Tu restes sur")

    release.set()
    await turn
    await _settle(stack)
    session = (await core.sessions.current()).session
    assert session.active_board_id == DEFAULT_BOARD_ID and b not in session.visited_board_ids


async def test_b1_a_stale_deferred_new_session_is_info_not_an_error(real_stack):
    from tests.unit.test_board_brains_control_center import trace

    stack, console = real_stack
    core = await stack.start_core(with_host=False)
    turn, release = await _in_turn(stack)

    assert (await console.boards.new_session())["status"] == "scheduled"
    status, _ = await stack.call("POST", "/api/sessions/new", json={})     # l'écran ouvre une Session entre-temps
    assert status == 201
    opened = (await core.sessions.current()).session.jarvis_session_id

    release.set()
    await turn
    await _settle(stack)
    assert (await core.sessions.current()).session.jarvis_session_id == opened, "no second Session"
    assert len(await core.boards._repo.list_sessions(limit=100)) == 2, "start + the screen's, nothing else"
    stale = trace(stack.tmp_path, "board.request.deferred_stale")
    assert stale and stale[-1]["level"] == "info" and stale[-1]["data"]["code"] == "session_closed"
    assert trace(stack.tmp_path, "board.request.deferred_failed") == []
