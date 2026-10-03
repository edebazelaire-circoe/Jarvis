"""Le serveur MCP `jarvis-workspace` (handoff board-memory-workspace-inspector, Slice 06).

Deux parties :

- **les neuf outils Board/Session déplacés de `jarvis-console`** (handoff
  board-session, Slice 05 ; mêmes noms, mêmes sémantiques, `board_kind` en
  plus). Leurs tests ont suivi l'outil sans changer d'assertion, sauf la nature
  du Board. Deux étages de preuve : un **faux Control Center** scripté
  (chaque outil, son verbe, sa route, son corps exact, chaque code d'erreur
  stable, le résultat `scheduled`) et un **vrai Control Center relié à un vrai
  Core** (pile de `test_board_switch_control_center`), y compris la bascule
  différée pendant un tour du cerveau ;
- **l'historique, la mémoire et les liens** (`session_list`, `session_get`,
  `board_inspect`, `board_memory_*`, `board_artifacts`, `board_artifact_link`)
  : chaque outil contre la vraie pile Core + relais `/api/workspace/*` (chemin
  heureux, origine `brain` au ledger, aucune activation) et contre le faux
  Control Center (correspondance des refus), plus la configuration, le
  sous-processus stdio et la déclaration au cerveau (profil `conversation`
  seulement).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis.runtime.workspace_mcp import (  # noqa: E402
    SERVER_NAME,
    TOOL_NAMES,
    WorkspaceMcpTarget,
    WorkspaceToolError,
    WorkspaceTools,
    build_server,
    mcp_config,
)
from jarvis.runtime import workspace_mcp  # noqa: E402


# ============================================================ Boards et Sessions (board-session, Slice 05, déplacés)

import asyncio

import jsonschema
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from jarvis.runtime import workspace_boards
from jarvis.runtime.board_routes import BoardSessionRoutes
from jarvis.runtime.journal import RuntimeJournal

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
        #: Retard avant chaque réponse : un Control Center muet (délai d'outil dépassé).
        self.delay_s = 0.0

    def answer(self, method: str, path: str, status: int, body: object) -> None:
        self.answers[(method, path)] = (status, body)

    async def _handle(self, request: web.Request) -> web.Response:
        raw = await request.read()
        body = json.loads(raw) if raw else None
        self.requests.append((request.method, request.path, dict(request.query), body))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
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
    ws = WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", fake.port, tmp_path),
                                   journal=RuntimeJournal(tmp_path))
    try:
        yield fake, ws
    finally:
        await ws.close()
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


async def test_the_moved_board_tools_keep_their_names_and_order_at_the_head_of_the_server():
    assert TOOL_NAMES[:len(BOARD_TOOLS)] == BOARD_TOOLS  # mêmes noms, même ordre qu'avant le déplacement
    server = build_server(tools=WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", 1)))
    listed = {tool.name: tool for tool in await server.list_tools()}
    assert tuple(listed) == TOOL_NAMES
    for name in ("board_get", "board_update", "board_archive", "board_switch"):
        assert listed[name].inputSchema["required"][0] == "board_id"
        assert listed[name].inputSchema["properties"]["board_id"]["pattern"] == r"^(default|board_[A-Za-z0-9_-]+)$"
    for name in ("board_get_active", "session_current", "session_new"):
        assert listed[name].inputSchema["properties"] == {}, name
    create = listed["board_create"].inputSchema
    assert create["required"] == ["title"]
    assert set(create["properties"]) == {"title", "board_kind", "context_summary", "task_refs", "artifact_refs",
                                         "project_refs"}
    # Motif, pas enum (voir `workspace_mcp.BOARD_KIND_PATTERN`) : exactement les valeurs de `BoardKind`.
    import re

    from jarvis.domain.workspace_board import BoardKind

    pattern = create["properties"]["board_kind"]["anyOf"][0]["pattern"]
    assert pattern == workspace_mcp.BOARD_KIND_PATTERN
    assert all(re.match(pattern, kind.value) for kind in BoardKind)
    assert not any(re.match(pattern, value) for value in ("Meeting", "meetings", "", "reunion"))
    assert create["properties"]["title"]["maxLength"] == 120
    for name in TOOL_NAMES:
        assert listed[name].outputSchema is not None, name  # résultat typé (contrat §5.2)


async def test_no_low_level_voice_brain_or_authority_tool_is_exposed():
    """06 section D : ni bind_voice, ni attach_brain, ni autorité de parole. Seulement des opérations de haut niveau."""

    server = build_server(tools=WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", 1)))
    for tool in await server.list_tools():
        for banned in ("voice", "bind", "attach", "authority", "speech", "brain", "foreground"):
            assert banned not in tool.name, tool.name
        assert "origin" not in tool.inputSchema["properties"], tool.name  # jamais choisi par le modèle


async def test_the_descriptions_say_what_a_board_and_a_new_session_are():
    """Le modèle doit comprendre : Board = espace de travail ; bascule = conversation + voix, le fond continue ;
    nouvelle Session = fil neuf sans toucher Boards ni tâches ; « nouvelle conversation » y mène."""

    server = build_server(tools=WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", 1)))
    described = {tool.name: tool.description for tool in await server.list_tools()}
    assert "espace de travail" in described["board_list"]
    assert "la conversation et la voix passent sur ce Board" in described["board_switch"]
    assert "garde son travail de fond" in described["board_switch"]
    assert "scheduled" in described["board_switch"] and "scheduled" in described["session_new"]
    assert "nouvelle conversation" in described["session_new"] and "nouvelle session" in described["session_new"]
    assert "Ne touche ni aux Boards ni aux tâches" in described["session_new"]
    assert "Ne bascule pas" in described["board_create"] and "board_switch" in described["board_create"]
    instructions = workspace_mcp._SERVER_INSTRUCTIONS
    for words in ("espace de travail", "board_switch", "session_new", "nouvelle conversation", "scheduled"):
        assert words in instructions, words


# ------------------------------------------------------------ comportement contre un faux Control Center


async def test_board_list_reads_the_ui_route_and_marks_the_active_board(fake_cc, tmp_path):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards", 200, {"boards": [_board("default", "Jarvis"), _board()],
                                            "active_board_id": "default"})
    listed = await ws.boards.list_boards()
    assert fake.requests == [("GET", "/api/boards", {}, None)]
    assert listed["active_board_id"] == "default"
    assert [(b["board_id"], b["active"]) for b in listed["boards"]] == [("default", True), ("board_ab12", False)]
    assert set(listed["boards"][0]) == {"board_id", "title", "board_kind", "status", "active", "interaction_mode",
                                        "last_opened_at"}
    assert listed["boards"][0]["board_kind"] == "empty"  # payload sans nature (avant v8) : empty
    await ws.boards.list_boards(include_archived=True)
    assert fake.requests[-1] == ("GET", "/api/boards", {"include_archived": "true"}, None)
    assert _journal(tmp_path, "board.tool")[-1]["data"]["tool"] == "board_list"


async def test_board_get_and_get_active_show_the_board_without_runtime_fields(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(context_summary="Lot 2",
                                                                         task_refs=["t1"]), "active": False})
    fake.answer("GET", "/api/boards/active", 200, {"board": _board("default", "Jarvis"), "active": True})
    got = await ws.boards.get_board("board_ab12")
    assert got["context_summary"] == "Lot 2" and got["task_refs"] == ["t1"] and got["active"] is False
    assert "scene_ref" not in got and "runtime_metadata" not in got and "interaction_mode_origin" not in got
    active = await ws.boards.get_active()
    assert active["board_id"] == "default" and active["active"] is True
    assert [r[:2] for r in fake.requests] == [("GET", "/api/boards/board_ab12"), ("GET", "/api/boards/active")]


async def test_board_create_update_and_archive_send_the_ui_bodies(fake_cc):
    fake, ws = fake_cc
    fake.answer("POST", "/api/boards", 201, {"board": _board(), "active": False})
    fake.answer("PATCH", "/api/boards/board_ab12", 200, {"board": _board(title="Veille"), "active": False})
    fake.answer("POST", "/api/boards/board_ab12/archive", 200, {"board": _board(status="archived"),
                                                                "active": False})
    created = await ws.boards.create_board("Recherche", context_summary=None, task_refs=["t1"],
                                                artifact_refs=None, project_refs=None)
    assert created["board_id"] == "board_ab12"
    assert fake.requests[-1] == ("POST", "/api/boards", {}, {"title": "Recherche", "task_refs": ["t1"]})
    updated = await ws.boards.update_board("board_ab12", title="Veille", context_summary=None)
    assert updated["title"] == "Veille"
    assert fake.requests[-1] == ("PATCH", "/api/boards/board_ab12", {}, {"title": "Veille"})
    archived = await ws.boards.archive_board("board_ab12")
    assert archived["status"] == "archived"
    assert fake.requests[-1][:2] == ("POST", "/api/boards/board_ab12/archive")


async def test_board_update_without_any_field_is_refused_before_sending(fake_cc):
    fake, ws = fake_cc
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.update_board("board_ab12", title=None, context_summary=None)
    assert failure.value.code == "invalid_board" and "Rien n'a été écrit" in str(failure.value)
    assert fake.requests == []


async def test_board_switch_is_asked_as_the_brain_and_says_scheduled_when_deferred(fake_cc, tmp_path):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch"})
    result = await ws.boards.switch_board("board_ab12")
    assert fake.requests[-1] == ("POST", "/api/boards/switch", {}, {"board_id": "board_ab12", "origin": "brain"})
    assert result["status"] == "scheduled" and result["title"] == "Recherche"
    assert result["note"] == "Passage sur « Recherche » à la fin de ta réponse."  # une phrase, pour la voix (B2)
    assert "previous_board_id" not in result
    assert _journal(tmp_path, "board.tool")[-1]["data"]["status"] == "scheduled"


async def test_board_switch_applied_at_once_names_the_previous_board(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 200, {"session": _SESSION, "binding": _BINDING, "board": _board(),
                                                    "previous_board_id": "default", "changed": True})
    result = await ws.boards.switch_board("board_ab12")
    assert result["status"] == "applied" and result["previous_board_id"] == "default"


async def test_board_switch_to_the_active_board_or_an_archived_one_sends_nothing(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/default", 200, {"board": _board("default", "Jarvis"), "active": True})
    fake.answer("GET", "/api/boards/board_old", 200, {"board": _board("board_old", status="archived"),
                                                      "active": False})
    fake.answer("GET", "/api/boards/pending", 200, {"ok": True, "pending": []})
    same = await ws.boards.switch_board("default")
    assert same["status"] == "unchanged"
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.switch_board("board_old")
    assert failure.value.code == "board_archived"
    assert all(method == "GET" for method, *_ in fake.requests), "no switch posted"


async def test_session_current_reads_the_open_session(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    current = await ws.boards.current_session()
    assert current == {"jarvis_session_id": "jsess_old", "started_at": _T, "active_board_id": "default",
                       "visited_board_ids": ["default"], "conversation_id": "conv-1"}


async def test_session_new_targets_the_session_it_read_and_says_scheduled(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    fake.answer("POST", "/api/sessions/new", 202, {"ok": True, "status": "scheduled", "action": "new_session"})
    result = await ws.boards.new_session()
    assert fake.requests[-1] == ("POST", "/api/sessions/new", {},
                                 {"origin": "brain", "expected_session_id": "jsess_old"})
    assert result["status"] == "scheduled" and result["closed_session_id"] == "jsess_old"
    assert result["board_id"] == "default" and "jarvis_session_id" not in result
    assert result["note"] == "Nouvelle session à la fin de ta réponse." and result["merged"] is False

    fake.answer("POST", "/api/sessions/new", 201, {"session": {**_SESSION, "jarvis_session_id": "jsess_new"},
                                                   "binding": _BINDING, "closed_session": _SESSION})
    applied = await ws.boards.new_session()
    assert applied["status"] == "applied" and applied["jarvis_session_id"] == "jsess_new"


@pytest.mark.parametrize(("status", "code"), [
    (404, "board_not_found"), (409, "board_archived"), (409, "board_is_active"), (409, "session_closed"),
    (404, "session_not_found"), (409, "brain_not_foreground"), (502, "board_activation_failed"),
    (500, "board_switch_rolled_back"), (400, "invalid_title"), (400, "context_summary_too_long"),
    (400, "invalid_board"), (400, "invalid_request"), (503, "core_unreachable"), (503, "core_unconfigured"),
])
async def test_every_stable_code_of_the_relay_becomes_a_coded_tool_error(fake_cc, tmp_path, status, code):
    fake, ws = fake_cc
    fake.answer("POST", "/api/boards/board_ab12/archive", status,
                {"error": {"code": code, "message": f"core says {code}"}})
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.archive_board("board_ab12")
    assert failure.value.code == code
    message = str(failure.value)
    assert message.startswith(f"Refus {code} : ") and workspace_boards.ERROR_SENTENCES[code] in message
    assert f"core says {code}" in message  # la cause réelle, jamais remplacée
    failed = _journal(tmp_path, "board.tool_failed")[-1]
    assert failed["level"] == "warning" and failed["data"]["code"] == code and failed["data"]["status"] == status


async def test_a_switch_refused_by_core_keeps_its_code(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 502, {"error": {"code": "board_activation_failed",
                                                              "message": "cli did not start"}})
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.switch_board("board_ab12")
    assert failure.value.code == "board_activation_failed" and "le Board actuel reste actif" in str(failure.value)


async def test_an_unreadable_answer_and_an_absent_control_center_are_said(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/active", 500, "Internal Server Error")
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.get_active()
    assert failure.value.code == "http_500" and "Internal Server Error" in str(failure.value)
    fake.answer("GET", "/api/boards/active", 200, "not json")
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.get_active()
    assert failure.value.code == "control_center_bad_response"
    fake.answer("GET", "/api/boards/active", 200, {"nope": 1})
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.get_active()
    assert failure.value.code == "control_center_bad_response"
    await fake.stop()
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.get_active()
    assert failure.value.code == "control_center_unreachable"


async def test_a_transport_failure_carries_its_stable_code_in_the_text_the_brain_reads(fake_cc):
    """QA S6 : injoignable, muet ou illisible, le texte de l'erreur d'outil porte son code comme un refus."""

    from mcp.shared.memory import create_connected_server_and_client_session

    fake, ws = fake_cc
    route = "/api/workspace/boards/board_ab12"
    fake.answer("GET", route, 200, "not json")
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.board_inspect("board_ab12")
    assert str(failure.value).startswith("Échec control_center_bad_response : Réponse illisible")
    fake.answer("GET", route, 200, {"nope": 1})
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.board_inspect("board_ab12")
    assert str(failure.value).startswith("Échec control_center_bad_response : Réponse inattendue")
    fake.answer("GET", "/api/boards/active", 200, {"nope": 1})
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.get_active()
    assert str(failure.value).startswith("Échec control_center_bad_response : ")

    fake.answer("GET", route, 200, {"board": _board(), "active": False})
    fake.delay_s = 1.0
    with pytest.raises(WorkspaceToolError) as failure:
        await ws._send("board_inspect", "GET", route, timeout_s=0.1)
    assert failure.value.code == "control_center_timeout"
    assert str(failure.value).startswith("Échec control_center_timeout : Le Control Center n'a pas répondu")
    fake.delay_s = 0.0

    await fake.stop()
    async with create_connected_server_and_client_session(build_server(tools=ws)) as session:
        result = await session.call_tool("board_inspect", {"board_id": "board_ab12"})
    assert result.isError
    assert result.content[0].text.startswith("Échec control_center_unreachable : Le Control Center est injoignable")
    codes = [row["data"]["code"] for row in _journal(ws.target.runtime_root, "board.tool_failed")]
    assert codes[-2:] == ["control_center_timeout", "control_center_unreachable"]


async def test_every_route_the_board_tools_hit_is_a_ui_route(fake_cc):
    """Parité avec l'écran : chaque requête des outils tombe sur une route du relais `BoardSessionRoutes`."""

    fake, ws = fake_cc
    fake.answer("GET", "/api/boards", 200, {"boards": [], "active_board_id": "default"})
    fake.answer("GET", "/api/boards/active", 200, {"board": _board("default"), "active": True})
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards", 201, {"board": _board(), "active": False})
    fake.answer("PATCH", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/board_ab12/archive", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch"})
    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    fake.answer("POST", "/api/sessions/new", 202, {"ok": True, "status": "scheduled", "action": "new_session"})
    boards = ws.boards
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

    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch"})
    server = build_server(tools=ws)
    advertised = {tool.name: tool.outputSchema for tool in await server.list_tools()}
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("board_switch", {"board_id": "board_ab12"})
    assert result.isError is False, result.content[0].text
    assert result.structuredContent["status"] == "scheduled"
    jsonschema.validate(result.structuredContent, advertised["board_switch"])
    assert json.dumps(result.structuredContent) == json.dumps(json.loads(result.content[0].text))


async def test_through_mcp_a_refusal_is_a_tool_error_with_its_code(fake_cc):
    from mcp.shared.memory import create_connected_server_and_client_session

    fake, ws = fake_cc
    fake.answer("POST", "/api/boards/default/archive", 409, {"error": {"code": "board_is_active",
                                                                       "message": "the active board"}})
    async with create_connected_server_and_client_session(build_server(tools=ws)) as session:
        result = await session.call_tool("board_archive", {"board_id": "default"})
    assert result.isError is True
    assert result.content[0].text.startswith("Refus board_is_active : ")


async def test_through_mcp_unknown_or_malformed_arguments_send_nothing(fake_cc):
    from mcp.shared.memory import create_connected_server_and_client_session

    fake, ws = fake_cc
    async with create_connected_server_and_client_session(build_server(tools=ws)) as session:
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
    ws = WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", port))
    try:
        yield stack, ws
    finally:
        await ws.close()
        await stack.close()


async def test_the_tools_do_what_the_screen_does_on_a_real_control_center_and_core(real_stack):
    """Créer, lire, modifier, basculer (hors tour : appliqué), nouvelle Session, archiver : Core relu à chaque pas."""

    from mcp.shared.memory import create_connected_server_and_client_session

    from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
    from tests.unit.test_board_brains_control_center import trace

    stack, ws = real_stack
    core = await stack.start_core()
    server = build_server(tools=ws)
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

    stack, ws = real_stack
    core = await stack.start_core(with_host=False)
    stack.control.board_routes._grace_s = 0.05
    release = asyncio.Event()

    async def slow_ask(text: str, **_) -> dict:
        await release.wait()
        return {"ok": True, "text": "Je passe sur Recherche."}

    stack.control.agent.ask = slow_ask
    created = await ws.boards.create_board("Recherche")
    first = (await core.sessions.current()).session.jarvis_session_id
    turn = asyncio.create_task(stack.control.agent_ask(JsonRequest({"text": "bascule sur Recherche"})))
    await asyncio.sleep(0.05)

    switched = await ws.boards.switch_board(created["board_id"])
    renewed = await ws.boards.new_session()
    assert switched["status"] == "scheduled" and renewed["status"] == "scheduled"
    assert renewed["closed_session_id"] == first
    current = await core.sessions.current()
    assert current.session.active_board_id == DEFAULT_BOARD_ID and current.session.jarvis_session_id == first

    release.set()
    await turn
    # Attendre la condition observée, pas un temps : l'état de Core change avant que la ligne
    # `board.request.deferred_applied` de `new_session` soit écrite (course côté test, READINESS §5).
    deadline = asyncio.get_running_loop().time() + 15.0
    while True:
        applied = {row["data"]["action"] for row in trace(stack.tmp_path, "board.request.deferred_applied")}
        if applied == {"switch", "new_session"} or asyncio.get_running_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)
    current = await core.sessions.current()
    assert current.session.active_board_id == created["board_id"]
    assert current.session.jarvis_session_id != first
    assert applied == {"switch", "new_session"}


# ------------------------------------------------------------ reprise QA Slice 05 (B1, B2, B3)


_JARGON = ("tour", "Session", "scheduled", "arrière-plan", "Board actif", "Core", "binding", "foreground")


def _voice_sentence(note: str) -> None:
    """B2 : une seule phrase courte, sans vocabulaire interne, que la voix peut dire telle quelle."""

    assert len(note) <= 60, note
    assert note.endswith(".") and note.count(". ") == 0 and "\n" not in note, note
    assert not any(word in note for word in _JARGON), note


async def test_b2_every_note_is_one_short_sentence_for_the_voice(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    fake.answer("GET", "/api/boards/default", 200, {"board": _board("default", "Jarvis"), "active": True})
    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    notes = []
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch"})
    notes.append((await ws.boards.switch_board("board_ab12"))["note"])
    fake.answer("POST", "/api/boards/switch", 200, {"session": _SESSION, "binding": _BINDING, "board": _board(),
                                                    "previous_board_id": "default", "changed": True})
    notes.append((await ws.boards.switch_board("board_ab12"))["note"])
    fake.answer("GET", "/api/boards/pending", 200, {"ok": True, "pending": []})
    notes.append((await ws.boards.switch_board("default"))["note"])
    fake.answer("GET", "/api/boards/pending", 200, {"ok": True, "pending": [{"action": "switch",
                                                                             "board_id": "board_ab12"}]})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch",
                                                    "replaced_board_id": "board_ab12"})
    notes.append((await ws.boards.switch_board("default"))["note"])
    fake.answer("POST", "/api/sessions/new", 202, {"ok": True, "status": "scheduled", "action": "new_session"})
    notes.append((await ws.boards.new_session())["note"])
    fake.answer("POST", "/api/sessions/new", 201, {"session": {**_SESSION, "jarvis_session_id": "jsess_new"},
                                                   "binding": _BINDING, "closed_session": _SESSION})
    notes.append((await ws.boards.new_session())["note"])
    assert len(set(notes)) == 6
    for note in notes:
        _voice_sentence(note)


async def test_b3_a_switch_back_to_the_active_board_with_a_pending_switch_is_not_unchanged(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/default", 200, {"board": _board("default", "Jarvis"), "active": True})
    fake.answer("GET", "/api/boards/pending", 200, {"ok": True, "pending": [{"action": "switch",
                                                                             "board_id": "board_ab12"}]})
    fake.answer("POST", "/api/boards/switch", 202, {"ok": True, "status": "scheduled", "action": "switch",
                                                    "replaced_board_id": "board_ab12"})
    result = await ws.boards.switch_board("default")
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
    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/active", 404 if isinstance(body, str) else 400, body)
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.boards.get_active()
    message = str(failure.value)
    assert failure.value.code == code and f"({source} : " in message
    assert ("(Core : " in message) is (source == "Core")
    assert _journal(tmp_path, "board.tool_failed")[-1]["data"]["source"] == source


def test_b3_binding_refusals_say_what_to_do_next():
    assert "session_new" in workspace_boards.ERROR_SENTENCES["binding_not_found"]
    assert "session_current" in workspace_boards.ERROR_SENTENCES["binding_conflict"]
    for code in ("binding_not_found", "binding_conflict"):
        assert "dis-le à l'utilisateur" in workspace_boards.ERROR_SENTENCES[code]


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

    stack, ws = real_stack
    core = await stack.start_core(with_host=False)
    before = len(await core.boards._repo.list_sessions(limit=100))
    first = (await core.sessions.current()).session.jarvis_session_id
    turn, release = await _in_turn(stack)

    one = await ws.boards.new_session()
    two = await ws.boards.new_session()
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

    stack, ws = real_stack
    core = await stack.start_core(with_host=False)
    b = (await ws.boards.create_board("Recherche"))["board_id"]
    c = (await ws.boards.create_board("Veille"))["board_id"]
    turn, release = await _in_turn(stack)

    first = await ws.boards.switch_board(b)
    second = await ws.boards.switch_board(c)
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

    stack, ws = real_stack
    core = await stack.start_core(with_host=False)
    b = (await ws.boards.create_board("Recherche"))["board_id"]
    turn, release = await _in_turn(stack)

    assert (await ws.boards.switch_board(b))["status"] == "scheduled"
    back = await ws.boards.switch_board(DEFAULT_BOARD_ID)
    assert back["status"] == "scheduled", "a pending switch exists: not unchanged"
    assert back["replaced_board_id"] == b and back["note"].startswith("Tu restes sur")

    release.set()
    await turn
    await _settle(stack)
    session = (await core.sessions.current()).session
    assert session.active_board_id == DEFAULT_BOARD_ID and b not in session.visited_board_ids


async def test_b1_a_stale_deferred_new_session_is_info_not_an_error(real_stack):
    from tests.unit.test_board_brains_control_center import trace

    stack, ws = real_stack
    core = await stack.start_core(with_host=False)
    turn, release = await _in_turn(stack)

    assert (await ws.boards.new_session())["status"] == "scheduled"
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


# ------------------------------------------------------------ reprise QA 06/07, point 3


def test_the_transition_tools_wait_longer_than_the_relay_which_waits_longer_than_core():
    from jarvis.adapters.control_center_brain import ControlCenterBoardHost
    from jarvis.runtime import workspace_boards
    from jarvis.runtime.core_sessions import CORE_TRANSITION_TIMEOUT_S

    assert workspace_boards.TRANSITION_TIMEOUT_S > CORE_TRANSITION_TIMEOUT_S > 2 * ControlCenterBoardHost.TIMEOUT_S


async def test_a_504_outcome_unknown_is_an_honest_unknown_status_not_a_failure(fake_cc):
    from jarvis.runtime.mcp_results import BoardSwitchResult, SessionNewResult

    fake, ws = fake_cc
    fake.answer("GET", "/api/boards/board_ab12", 200, {"board": _board(), "active": False})
    unknown = {"error": {"code": "core_transition_timeout", "message": "the outcome is unknown"}}
    fake.answer("POST", "/api/boards/switch", 504, unknown)
    switched = await ws.boards.switch_board("board_ab12")
    assert switched["status"] == "unknown" and switched["board_id"] == "board_ab12"
    BoardSwitchResult.model_validate(switched)
    _voice_sentence(switched["note"])

    fake.answer("GET", "/api/sessions/current", 200, {"session": _SESSION, "binding": _BINDING})
    fake.answer("POST", "/api/sessions/new", 504, unknown)
    renewed = await ws.boards.new_session()
    assert renewed["status"] == "unknown" and renewed["closed_session_id"] == "jsess_old"
    SessionNewResult.model_validate(renewed)
    _voice_sentence(renewed["note"])

    fake.answer("GET", "/api/boards", 504, unknown)            # jamais pour une lecture : refus codé
    with pytest.raises(WorkspaceToolError, match="core_transition_timeout"):
        await ws.boards.list_boards()


# ============================================================ historique, mémoire et liens (Slice 06 board-memory)
#
# Vraie chaîne : Core sur SQLite et une racine de données réelle, `LocalProtocolServer`, vrai `ControlCenter`
# (`tests/fakes/capture_stack.py`), monde de `test_workspace_inspection_api.build` : Session close et Session
# ouverte, Board B actif, Board A inactif avec mémoire, Board archivé avec mémoire, Artifacts liés.

from tests.fakes.capture_stack import TOKEN, CaptureStack  # noqa: E402
from tests.unit.test_workspace_inspection_api import build, snapshot  # noqa: E402


class Brain:
    """Le serveur réel, en mémoire, sur le vrai Control Center d'une `CaptureStack` (comme `test_capture_mcp`)."""

    def __init__(self, stack: CaptureStack) -> None:
        self.stack = stack
        self.tools = WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", stack.cc_port, None))
        self.server = build_server(tools=self.tools)
        self.schemas: dict = {}

    async def __aenter__(self) -> "Brain":
        from mcp.shared.memory import create_connected_server_and_client_session

        self.schemas = {tool.name: tool.outputSchema for tool in await self.server.list_tools()}
        self._session_cm = create_connected_server_and_client_session(self.server)
        self.session = await self._session_cm.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._session_cm.__aexit__(*exc)
        await self.tools.close()

    async def call(self, name: str, arguments: dict | None = None) -> dict:
        result = await self.session.call_tool(name, arguments or {})
        assert result.isError is False, result.content[0].text
        jsonschema.validate(result.structuredContent, self.schemas[name])
        text = json.dumps(result.structuredContent, ensure_ascii=False)
        assert TOKEN not in text and str(self.stack.tmp_path) not in text
        assert str(self.stack.tmp_path).replace("\\", "\\\\") not in text
        return result.structuredContent

    async def refused(self, name: str, arguments: dict | None = None) -> str:
        result = await self.session.call_tool(name, arguments or {})
        assert result.isError is True, result.structuredContent
        return result.content[0].text


async def _events(stack: CaptureStack, session_id: str, kind: str) -> list[dict]:
    status, body, _ = await stack.call("GET", f"/api/workspace/sessions/{session_id}/activity",
                                       params={"kind": kind, "limit": "100"})
    assert status == 200, body
    return body["events"]


async def test_history_and_inspection_tools_read_any_board_without_activating_anything(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)
        before = await snapshot(stack)

        listed = await brain.call("session_list", {"limit": 1})
        assert [s["jarvis_session_id"] for s in listed["sessions"]] == [w.open_session]
        assert listed["sessions"][0]["status"] == "open" and listed["next_cursor"]
        older = await brain.call("session_list", {"cursor": listed["next_cursor"]})
        assert [s["jarvis_session_id"] for s in older["sessions"]] == [w.closed_session]
        assert older["sessions"][0]["status"] == "closed" and "next_cursor" not in older

        closed = await brain.call("session_get", {"session_id": w.closed_session})
        assert closed["status"] == "closed" and "speech_authority_board_id" not in closed
        visited = {b["board_id"]: b for b in closed["boards"]}
        assert w.board_a in visited and visited[w.board_a]["board_kind"] == "meeting"
        assert closed["contexts_total"] == 2 and {c["context_id"] for c in closed["contexts"]} == {
            w.first_context, w.second_context}
        opened = await brain.call("session_get", {"session_id": w.open_session})
        assert opened["active_board_id"] == w.board_b and opened["problems"] == []
        assert opened["speech_authority_board_id"] == w.board_b

        old = await brain.call("board_inspect", {"board_id": w.board_archived})
        assert old["status"] == "archived" and old["active"] is False
        assert old["memory"] == {"exists": True, "entries": 1, "files": 1, "bytes": 8, "truncated": False,
                                 "summary_md": False}
        a = await brain.call("board_inspect", {"board_id": w.board_a})
        assert a["board_kind"] == "meeting" and a["memory"]["summary_md"] is True and a["active"] is False
        assert w.closed_session in {s["jarvis_session_id"] for s in a["sessions"]}
        assert not any(s["active_in_session"] for s in a["sessions"] if s["session_status"] == "open")
        # QA S6 : quand le Board a servi dans chaque Session (dates de la liaison, gardées telles que Core les rend).
        assert all(s["created_at"] and s["last_active_at"] and s["last_active_at"] >= s["created_at"]
                   for s in a["sessions"])

        tree = await brain.call("board_memory_tree", {"board_id": w.board_a})
        assert {e["path"] for e in tree["entries"]} >= {"summary.md", "notes", "notes/plan.md", "image.bin"}
        assert tree["exists"] is True and tree["truncated"] is False
        page = await brain.call("board_memory_read", {"board_id": w.board_a, "path": "notes/plan.md",
                                                      "max_bytes": 256})
        assert page["text"] == "étape 1\nétape 2 décisions\n" and page["eof"] is True and len(page["sha256"]) == 64
        found = await brain.call("board_memory_search", {"board_id": w.board_a, "query": "DÉCISIONS"})
        assert {m["path"] for m in found["matches"]} == {"summary.md", "notes/plan.md"}
        assert found["truncated"] is False and "note" not in found
        archived = await brain.call("board_memory_read", {"board_id": w.board_archived, "path": "vieux.md"})
        assert archived["text"] == "archive\n"
        on_b = await brain.call("board_artifacts", {"board_id": w.board_b})
        assert [item["artifact_id"] for item in on_b["items"]] == [w.art_closed, w.art_audio]  # récents d'abord

        assert await snapshot(stack) == before, "a read through the brain tools changed the foreground"


async def test_memory_mutations_through_the_brain_tools_name_the_board_and_record_origin_brain(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)
        a = w.board_a
        written = await brain.call("board_memory_write", {"board_id": a, "path": "notes/idée.md",
                                                          "content": "piste 1\n"})
        assert written["created"] is True and written["mode"] == "create" and written["bytes"] == 8
        refusal = await brain.refused("board_memory_write", {"board_id": a, "path": "notes/idée.md",
                                                             "content": "x"})
        assert refusal.startswith("Refus memory_exists : ") and "(Core : " in refusal
        replaced = await brain.call("board_memory_write", {"board_id": a, "path": "notes/idée.md",
                                                           "content": "piste 2\n", "mode": "replace",
                                                           "expected_sha256": written["sha256"]})
        assert replaced["created"] is False
        stale = await brain.refused("board_memory_write", {"board_id": a, "path": "notes/idée.md", "content": "y",
                                                           "mode": "replace", "expected_sha256": written["sha256"]})
        assert stale.startswith("Refus memory_conflict : ")
        moved = await brain.call("board_memory_move", {"board_id": a, "source": "notes", "target": "classé"})
        assert moved == {"board_id": a, "source": "notes", "target": "classé", "kind": "directory"}
        not_empty = await brain.refused("board_memory_delete", {"board_id": a, "path": "classé"})
        assert not_empty.startswith("Refus memory_conflict : ")
        gone = await brain.call("board_memory_delete", {"board_id": a, "path": "classé", "recursive": True})
        assert gone["removed"] == 3 and gone["recursive"] is True
        archived = await brain.refused("board_memory_write", {"board_id": w.board_archived, "path": "n.md",
                                                              "content": "z"})
        assert archived.startswith("Refus board_archived : ")
        escape = await brain.refused("board_memory_read", {"board_id": a, "path": "../secret.md"})
        assert escape.startswith("Refus memory_path_escape : ")

        rows = [*await _events(stack, w.open_session, "board.memory.written"),
                *await _events(stack, w.open_session, "board.memory.moved"),
                *await _events(stack, w.open_session, "board.memory.deleted")]
        assert len(rows) == 4 and all(row["data"]["origin"] == "brain" and row["data"]["board_id"] == a
                                      for row in rows)
        session = (await stack.core.sessions.current()).session
        assert session.active_board_id == w.board_b, "a mutation on another Board never switches"


async def test_board_artifact_link_and_unlink_are_idempotent_and_said(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)
        automatic = [item["artifact_id"] for item in (await brain.call("board_artifacts", {"board_id": w.board_a}))[
            "items"]]
        assert w.art_audio in automatic and w.art_closed not in automatic  # liens automatiques (Board actif)
        linked = await brain.call("board_artifact_link", {"board_id": w.board_a, "artifact_id": w.art_closed})
        assert linked == {"board_id": w.board_a, "artifact_id": w.art_closed, "linked": True, "changed": True}
        again = await brain.call("board_artifact_link", {"board_id": w.board_a, "artifact_id": w.art_closed})
        assert again["changed"] is False
        listed = await brain.call("board_artifacts", {"board_id": w.board_a})
        assert [item["artifact_id"] for item in listed["items"]] == [w.art_closed, *automatic]
        unlinked = await brain.call("board_artifact_link", {"board_id": w.board_a, "artifact_id": w.art_closed,
                                                            "linked": False})
        assert unlinked["linked"] is False and unlinked["changed"] is True
        after = await brain.call("board_artifacts", {"board_id": w.board_a})
        assert [item["artifact_id"] for item in after["items"]] == automatic, "the automatic links stay"
        rows = [*await _events(stack, w.open_session, "board.artifact.linked"),
                *await _events(stack, w.open_session, "board.artifact.unlinked")]
        assert [row["data"]["origin"] for row in rows] == ["brain", "brain"]
        missing = await brain.refused("board_artifact_link", {"board_id": w.board_a,
                                                              "artifact_id": "jart_" + "f" * 32})
        assert missing.startswith("Refus artifact_not_found : ")


async def test_identifiers_and_unknown_arguments_are_refused_before_anything_is_sent(fake_cc):
    from mcp.shared.memory import create_connected_server_and_client_session

    fake, ws = fake_cc
    async with create_connected_server_and_client_session(build_server(tools=ws)) as session:
        for name, arguments in (
            ("session_get", {"session_id": "../x"}),
            ("board_memory_read", {"board_id": "../etc", "path": "a.md"}),
            ("board_memory_tree", {"board_id": "default", "depth": 9}),
            ("board_memory_read", {"board_id": "default", "path": "a.md", "max_bytes": 1_000_000}),
            ("board_memory_write", {"board_id": "default", "path": "a.md", "content": "x", "mode": "overwrite"}),
            ("board_memory_write", {"board_id": "default", "path": "a.md", "content": "x", "origin": "user"}),
            ("board_artifact_link", {"board_id": "default", "artifact_id": "not-an-artifact"}),
            ("board_memory_search", {"board_id": "default", "query": ""}),
        ):
            result = await session.call_tool(name, arguments)
            assert result.isError is True, (name, arguments)
    assert fake.requests == []


async def test_an_incomplete_search_is_said_never_read_as_nothing_found(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/workspace/boards/default/memory/search", 200, {
        "board_id": "default", "query": "x", "matches": [], "files_scanned": 500, "files_skipped": 3,
        "truncated": True})
    found = await ws.memory_search("default", query="x")
    assert found["truncated"] is True and found["matches"] == []
    assert found["note"] == workspace_mcp.SEARCH_INCOMPLETE_NOTE and "Recherche incomplète" in found["note"]
    assert fake.requests[-1][2] == {"q": "x", "limit": "20"}


async def test_mutations_send_origin_brain_on_the_ui_routes(fake_cc):
    fake, ws = fake_cc
    base = "/api/workspace/boards/board_ab12"
    fake.answer("POST", base + "/memory/write", 201, {
        "board_id": "board_ab12", "path": "n.md", "mode": "create", "created": True, "bytes": 1, "size": 1,
        "sha256": "a" * 64, "entry": {}, "activity_seq": 4, "jarvis_session_id": "jsess_x"})
    fake.answer("POST", base + "/memory/move", 200, {"board_id": "board_ab12", "from": "n.md", "to": "m.md",
                                                    "entry": {"kind": "file"}})
    fake.answer("POST", base + "/memory/delete", 200, {"board_id": "board_ab12", "path": "m.md", "recursive": False,
                                                      "removed": 1})
    fake.answer("POST", base + "/artifacts/jart_abc", 201, {"link": {}, "created": True})
    fake.answer("DELETE", base + "/artifacts/jart_abc", 200, {"removed": True})
    await ws.memory_write("board_ab12", path="n.md", content="x")
    await ws.memory_move("board_ab12", source="n.md", target="m.md")
    await ws.memory_delete("board_ab12", path="m.md")
    await ws.artifact_link("board_ab12", "jart_abc")
    await ws.artifact_link("board_ab12", "jart_abc", linked=False)
    assert fake.requests == [
        ("POST", base + "/memory/write", {}, {"path": "n.md", "content": "x", "mode": "create", "origin": "brain"}),
        ("POST", base + "/memory/move", {}, {"from": "n.md", "to": "m.md", "origin": "brain"}),
        ("POST", base + "/memory/delete", {}, {"path": "m.md", "recursive": False, "origin": "brain"}),
        ("POST", base + "/artifacts/jart_abc", {}, {"origin": "brain"}),
        ("DELETE", base + "/artifacts/jart_abc", {"origin": "brain"}, None),
    ]


@pytest.mark.parametrize("status, code, words", [
    (500, "workspace_ledger_failed", "A ÉTÉ appliqué"),
    (409, "board_archived", "archivé"),
    (404, "memory_not_found", "board_memory_tree"),
    (413, "memory_too_large", "256 Kio"),
    (504, "core_timeout", "issue est inconnue"),
])
async def test_every_workspace_refusal_keeps_its_code_and_says_what_to_do(fake_cc, tmp_path, status, code, words):
    fake, ws = fake_cc
    fake.answer("POST", "/api/workspace/boards/board_ab12/memory/write", status,
                {"error": {"code": code, "message": f"core says {code}"}})
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.memory_write("board_ab12", path="n.md", content="x")
    assert failure.value.code == code and words in str(failure.value) and f"core says {code}" in str(failure.value)
    source = "Control Center" if code in workspace_boards.RELAY_CODES else "Core"
    assert f"({source} : " in str(failure.value)
    failed = _journal(tmp_path, "board.tool_failed")[-1]["data"]
    assert failed["tool"] == "board_memory_write" and failed["code"] == code


async def test_an_origin_refusal_of_the_control_center_keeps_its_stable_code(fake_cc):
    fake, ws = fake_cc
    fake.answer("GET", "/api/workspace/sessions", 403, {"ok": False, "code": "forbidden_origin", "error": "origin"})
    with pytest.raises(WorkspaceToolError) as failure:
        await ws.session_list()
    assert failure.value.code == "forbidden_origin" and "(Control Center : origin)" in str(failure.value)


# ------------------------------------------------------------ configuration et déclaration au cerveau


def test_the_mcp_config_launches_this_server_and_carries_no_secret(tmp_path):
    target = WorkspaceMcpTarget("127.0.0.1", 17654, tmp_path)
    document = mcp_config(target, python="python.exe")
    entry = document["mcpServers"][SERVER_NAME]
    assert entry["args"] == ["-m", "jarvis", "workspace-mcp"] and entry["type"] == "stdio"
    assert entry["env"]["JARVIS_CONTROL_CENTER_PORT"] == "17654"
    path = workspace_mcp.write_mcp_config(target, tmp_path)
    assert path.name == "workspace-mcp.json" and json.loads(path.read_text(encoding="utf-8")) == mcp_config(target)
    assert "token" not in path.read_text(encoding="utf-8").lower()


async def test_the_workspace_subcommand_serves_over_stdio(tmp_path):
    """Le vrai processus, le vrai protocole : `python -m jarvis workspace-mcp` liste ses vingt outils."""

    import os

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "jarvis", "workspace-mcp"],
        env={**os.environ, "JARVIS_CONTROL_CENTER_HOST": "127.0.0.1", "JARVIS_CONTROL_CENTER_PORT": "1",
             "JARVIS_RUNTIME_DIR": str(tmp_path)},
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert tuple(tool.name for tool in listed.tools) == TOOL_NAMES
            result = await session.call_tool("board_list", {})
            assert result.isError is True and "Le Control Center est injoignable" in result.content[0].text


async def test_only_the_conversation_brain_declares_jarvis_workspace_and_the_gateway_lists_it(monkeypatch, tmp_path):
    from jarvis.runtime import claude_local
    from jarvis.runtime.claude_local import BRAIN_WORKSPACE_PROMPT, ClaudeLocalAgent
    from jarvis.runtime.settings_mcp import ConsoleMcpTarget
    from jarvis.runtime.tools_gateway_mcp import ENV_NATIVE_SERVERS, ToolsGatewayTarget
    from tests.unit.test_claude_tools_gateway_args import SENTINEL, _config_paths, _Process

    runtime = tmp_path / "runtime"
    token = tmp_path / "core.token"
    token.write_text(SENTINEL, encoding="utf-8")
    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append([str(arg) for arg in args])
        return _Process()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    for profile in ("conversation", "job_result"):
        agent = ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path, execution_profile=profile,
                                 console_mcp=ConsoleMcpTarget("127.0.0.1", 47002, runtime),
                                 workspace_mcp=WorkspaceMcpTarget("127.0.0.1", 47002, runtime),
                                 capture_mcp=ConsoleMcpTarget("127.0.0.1", 47002, runtime),
                                 tools_mcp=ToolsGatewayTarget("127.0.0.1", 47001, token, runtime))
        if agent._process_tree is not None:
            monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
        await agent.start()
        assert agent.snapshot()["workspace_tools"] is (profile == "conversation")
        agent.process.returncode = 0  # type: ignore[union-attr]
        assert agent.snapshot()["workspace_tools"] is False
        await agent.stop()

    conversation, job = started
    paths = _config_paths(conversation)
    assert [path.name for path in paths] == ["console-mcp.json", "workspace-mcp.json", "capture-mcp.json",
                                             "tools-mcp.json"]
    assert SENTINEL not in paths[1].read_text(encoding="utf-8")
    gateway = json.loads(paths[3].read_text(encoding="utf-8"))["mcpServers"]["jarvis-tools"]
    assert gateway["env"][ENV_NATIVE_SERVERS] == "jarvis-console,jarvis-workspace,jarvis-capture"
    assert BRAIN_WORKSPACE_PROMPT.strip() in conversation[conversation.index("--append-system-prompt") + 1]
    assert _config_paths(job) == [], "a background job never receives the native servers"


async def test_a_workspace_config_that_cannot_be_written_is_said_and_the_brain_still_starts(monkeypatch, tmp_path):
    from jarvis.runtime.claude_local import ClaudeLocalAgent
    from jarvis.runtime.journal import read_jsonl_tail

    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path,
                             workspace_mcp=WorkspaceMcpTarget("127.0.0.1", 47002, tmp_path / "runtime"))

    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("disk refused")

    monkeypatch.setattr(workspace_mcp, "write_mcp_config", refuse)
    assert agent._workspace_mcp_args() == []
    errors = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=10)
              if e["kind"] == "agent.workspace_mcp_failed"]
    assert errors and errors[0]["data"]["code"] == "workspace_mcp_config_write_failed"


def test_the_control_center_always_hands_the_workspace_target_to_the_claude_brain(tmp_path):
    from jarvis.runtime.claude_local import ClaudeLocalAgent
    from jarvis.runtime.control_center import ControlCenter

    target = WorkspaceMcpTarget("127.0.0.1", 17654, tmp_path)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, workspace_mcp=target)
    assert isinstance(control.agent, ClaudeLocalAgent)
    control._apply_agent_settings(control._settings())
    assert control.agent.workspace_mcp == target


def test_the_brain_prompt_says_how_to_look_at_another_board_without_switching():
    from jarvis.runtime.claude_local import BRAIN_SETTINGS_PROMPT, BRAIN_WORKSPACE_PROMPT

    assert "mcp__jarvis-workspace__board_list" in BRAIN_WORKSPACE_PROMPT
    for words in ("board_inspect", "board_memory_read", "board_memory_search", "sans y aller",
                  "Jamais board_switch pour regarder", "sous-agent"):
        assert words in BRAIN_WORKSPACE_PROMPT, words
    assert "board_" not in BRAIN_SETTINGS_PROMPT and "jarvis-console" not in BRAIN_WORKSPACE_PROMPT
    assert len(BRAIN_WORKSPACE_PROMPT.encode("utf-8")) <= 700
