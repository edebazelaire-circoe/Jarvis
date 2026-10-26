"""Édition produit et verrou des Boards Présentation (jarvis-presentation-edition-v1, Slice 01).

Contrat : `docs/product-edition.md`. Quatre étages, chacun en édition `full`
(non-régression) et `presentation` :

- la politique pure (`jarvis/domain/product_edition.py`) et sa résolution ;
- Core : création, bascule, `ensure_default`, repli de démarrage (`BoardService`,
  `SessionManager`, `JarvisCoreApplication`), Boards hérités intacts ;
- le protocole : requêtes forgées refusées 409 `board_kind_unavailable`,
  `GET /v1/boards/edition`, relais `/api/boards/edition` ;
- MCP `jarvis-workspace` (schéma, appel) et consigne du cerveau.

Bases temporaires uniquement.
"""

from __future__ import annotations

import asyncio
import socket

import aiohttp
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.product_edition import (
    FULL_EDITION, PRESENTATION_EDITION, PRODUCT_EDITION_ENV, BoardKindAvailability, ProductEdition,
    resolve_product_edition,
)
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID, BoardError, BoardErrorCode, BoardKind
from jarvis.protocol.server import LocalProtocolServer

TOKEN = "t" * 48


# ------------------------------------------------------------------ politique pure


def test_full_edition_keeps_every_board_kind_and_the_assistant_default():
    assert FULL_EDITION.edition is ProductEdition.FULL
    assert FULL_EDITION.available_board_kinds == tuple(BoardKind)
    assert FULL_EDITION.default_board_kind is BoardKind.ASSISTANT
    assert not FULL_EDITION.restricts_board_kinds
    assert all(FULL_EDITION.allows(kind) for kind in BoardKind)


def test_presentation_edition_allows_only_presentation():
    policy = PRESENTATION_EDITION
    assert policy.available_board_kinds == (BoardKind.PRESENTATION,)
    assert policy.default_board_kind is BoardKind.PRESENTATION and policy.restricts_board_kinds
    assert policy.availability(BoardKind.ASSISTANT) is BoardKindAvailability.UNAVAILABLE
    assert policy.availability(BoardKind.MEETING) is BoardKindAvailability.UNAVAILABLE
    assert policy.ensure_available(BoardKind.PRESENTATION, action="create") is BoardKind.PRESENTATION
    for kind in (BoardKind.ASSISTANT, BoardKind.MEETING):
        with pytest.raises(BoardError) as refused:
            policy.ensure_available(kind, action="switch")
        assert refused.value.code is BoardErrorCode.BOARD_KIND_UNAVAILABLE and refused.value.status == 409
        assert kind.value in str(refused.value) and "nothing written" in str(refused.value)


def test_the_availability_payload_is_the_ui_contract():
    payload = PRESENTATION_EDITION.to_payload()
    assert payload == {
        "edition": "presentation", "default_board_kind": "presentation",
        "board_kinds": [
            {"board_kind": "assistant", "availability": "unavailable", "available": False, "behavior_status": "ready"},
            {"board_kind": "presentation", "availability": "available", "available": True, "behavior_status": "ready"},
            {"board_kind": "meeting", "availability": "unavailable", "available": False, "behavior_status": "planned"},
        ],
    }
    assert [k["available"] for k in FULL_EDITION.to_payload()["board_kinds"]] == [True, True, True]


@pytest.mark.parametrize("environ, expected", [
    ({}, ProductEdition.FULL),
    ({PRODUCT_EDITION_ENV: ""}, ProductEdition.FULL),
    ({PRODUCT_EDITION_ENV: " full "}, ProductEdition.FULL),
    ({PRODUCT_EDITION_ENV: "presentation"}, ProductEdition.PRESENTATION),
    ({PRODUCT_EDITION_ENV: "PRESENTATION"}, ProductEdition.PRESENTATION),
])
def test_resolution_reads_the_environment_and_defaults_to_full(environ, expected):
    assert resolve_product_edition(environ).edition is expected


def test_an_installed_default_applies_only_when_nothing_is_configured():
    assert resolve_product_edition({}, installed_default=ProductEdition.PRESENTATION) is PRESENTATION_EDITION
    assert resolve_product_edition({PRODUCT_EDITION_ENV: "full"},
                                   installed_default=ProductEdition.PRESENTATION) is FULL_EDITION


def test_an_unreadable_edition_refuses_to_start_instead_of_falling_back_to_full():
    with pytest.raises(ConfigurationError) as refused:
        resolve_product_edition({PRODUCT_EDITION_ENV: "presentaton"})
    assert PRODUCT_EDITION_ENV in str(refused.value) and "presentaton" in str(refused.value)


# ------------------------------------------------------------------ Core


async def _core(tmp_path, edition=FULL_EDITION) -> JarvisCoreApplication:
    core = JarvisCoreApplication(data_root=tmp_path, product_edition=edition)
    await core.start()
    return core


async def test_a_fresh_presentation_core_starts_on_a_presentation_default_board(tmp_path):
    core = await _core(tmp_path, PRESENTATION_EDITION)
    try:
        active = await core.boards.get_active()
        assert active.board_id == DEFAULT_BOARD_ID and active.board_kind is BoardKind.PRESENTATION
        assert len(await core.boards.list()) == 1
    finally:
        await core.stop()


async def test_presentation_creation_defaults_to_presentation_and_refuses_other_kinds(tmp_path):
    core = await _core(tmp_path, PRESENTATION_EDITION)
    try:
        created = await core.boards.create({"title": "Pitch"})
        assert created.board_kind is BoardKind.PRESENTATION
        assert (await core.boards.create({"title": "Deck", "board_kind": "presentation"})).board_kind \
            is BoardKind.PRESENTATION
        before = len(await core.boards.list(include_archived=True))
        for kind in ("assistant", "meeting", "empty"):  # `empty` : alias déprécié d'assistant, refusé aussi
            with pytest.raises(BoardError) as refused:
                await core.boards.create({"title": "Interdit", "board_kind": kind})
            assert refused.value.code is BoardErrorCode.BOARD_KIND_UNAVAILABLE
        assert len(await core.boards.list(include_archived=True)) == before
    finally:
        await core.stop()


async def test_full_edition_still_creates_and_switches_to_every_kind(tmp_path):
    core = await _core(tmp_path)
    try:
        assert (await core.boards.get_active()).board_kind is BoardKind.ASSISTANT
        assert (await core.boards.create({"title": "Sans type"})).board_kind is BoardKind.ASSISTANT
        for kind in BoardKind:
            board = await core.boards.create({"title": f"B {kind.value}", "board_kind": kind.value})
            assert board.board_kind is kind
            assert (await core.boards.switch(board.board_id)).board.board_id == board.board_id
    finally:
        await core.stop()


async def _legacy_core_then_presentation(tmp_path, *, with_presentation_board: bool):
    """Une base écrite en `full` (Board `default` assistant + Réunion, Session ouverte), rouverte en `presentation`."""

    full = await _core(tmp_path)
    try:
        meeting = await full.boards.create({"title": "Réunion", "board_kind": "meeting"})
        await full.boards.switch(meeting.board_id)
        presentation = None
        if with_presentation_board:
            presentation = await full.boards.create({"title": "Pitch", "board_kind": "presentation"})
        legacy = {board.board_id: board for board in await full.boards.list()}
        session_id = (await full.sessions.current()).session.jarvis_session_id
    finally:
        await full.stop()
    return legacy, meeting, presentation, session_id


async def test_startup_never_resumes_on_a_legacy_board_and_creates_a_presentation_one(tmp_path):
    legacy, meeting, _, session_id = await _legacy_core_then_presentation(tmp_path, with_presentation_board=False)
    core = await _core(tmp_path, PRESENTATION_EDITION)
    try:
        view = await core.sessions.current()
        active = await core.boards.get(view.session.active_board_id)
        assert active.board_kind is BoardKind.PRESENTATION and active.board_id not in legacy
        # Même Session reprise : le Board hérité n'est plus actif, il reste dans les Boards visités.
        assert view.session.jarvis_session_id == session_id and meeting.board_id in view.session.visited_board_ids
        # Boards hérités intacts : ni réécrits, ni supprimés, ni archivés.
        for board_id, before in legacy.items():
            assert await core.boards.get(board_id) == before
        assert core.interaction_mode.state.mode.value == "presentation"
    finally:
        await core.stop()
    # Rejouable : au redémarrage suivant, le Board créé est retrouvé, aucun second n'est créé.
    core = await _core(tmp_path, PRESENTATION_EDITION)
    try:
        kinds = [board.board_kind for board in await core.boards.list()]
        assert kinds.count(BoardKind.PRESENTATION) == 1
        assert (await core.boards.get_active()).board_id == active.board_id
    finally:
        await core.stop()


async def test_startup_falls_back_on_the_last_available_presentation_board(tmp_path):
    legacy, _, presentation, _ = await _legacy_core_then_presentation(tmp_path, with_presentation_board=True)
    core = await _core(tmp_path, PRESENTATION_EDITION)
    try:
        assert (await core.boards.get_active()).board_id == presentation.board_id
        assert len(await core.boards.list()) == len(legacy)  # rien de créé
    finally:
        await core.stop()


async def test_a_legacy_board_cannot_be_activated_but_stays_readable_and_editable(tmp_path):
    legacy, meeting, _, _ = await _legacy_core_then_presentation(tmp_path, with_presentation_board=False)
    core = await _core(tmp_path, PRESENTATION_EDITION)
    try:
        active_before = (await core.sessions.current()).session.active_board_id
        for board_id in (DEFAULT_BOARD_ID, meeting.board_id):
            with pytest.raises(BoardError) as refused:
                await core.boards.switch(board_id)
            assert refused.value.code is BoardErrorCode.BOARD_KIND_UNAVAILABLE
        assert (await core.sessions.current()).session.active_board_id == active_before
        renamed = await core.boards.update(meeting.board_id, {"title": "Réunion (ancienne)"})
        assert renamed.board_kind is BoardKind.MEETING
        assert (await core.boards.archive(meeting.board_id)).status.value == "archived"
    finally:
        await core.stop()


# ------------------------------------------------------------------ protocole


@pytest.fixture
async def presentation_stack(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    await _legacy_core_then_presentation(tmp_path, with_presentation_board=False)
    core = await _core(tmp_path, PRESENTATION_EDITION)
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    try:
        yield core, f"http://127.0.0.1:{port}"
    finally:
        await server.stop()
        await core.stop()


async def _raw(method: str, url: str, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers={"Authorization": f"Bearer {TOKEN}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


@pytest.mark.parametrize("body", [
    {"title": "Forgé", "board_kind": "assistant"},
    {"title": "Forgé", "board_kind": "meeting"},
    {"title": "Forgé", "board_kind": "empty"},
])
async def test_a_forged_create_request_is_refused_409(presentation_stack, body):
    core, base = presentation_stack
    before = len(await core.boards.list(include_archived=True))
    status, refused = await _raw("POST", base + "/v1/boards", json=body)
    assert status == 409 and refused["error"]["code"] == "board_kind_unavailable"
    assert len(await core.boards.list(include_archived=True)) == before


async def test_a_forged_switch_to_a_legacy_board_is_refused_409(presentation_stack):
    core, base = presentation_stack
    active = (await core.sessions.current()).session.active_board_id
    status, refused = await _raw("POST", base + "/v1/boards/switch", json={"board_id": DEFAULT_BOARD_ID})
    assert status == 409 and refused["error"]["code"] == "board_kind_unavailable"
    assert (await core.sessions.current()).session.active_board_id == active


async def test_the_protocol_creates_presentation_by_default_and_says_the_edition(presentation_stack):
    _, base = presentation_stack
    status, created = await _raw("POST", base + "/v1/boards", json={"title": "Pitch"})
    assert status == 201 and created["board"]["board_kind"] == "presentation"
    status, edition = await _raw("GET", base + "/v1/boards/edition")
    assert status == 200 and edition == PRESENTATION_EDITION.to_payload()
    status, refused = await _raw("GET", base + "/v1/boards/edition", params={"x": "1"})
    assert status == 400


async def test_the_control_center_relays_the_edition_and_the_refusals(tmp_path):
    from tests.unit.test_board_switch_control_center import TOKEN as CC_TOKEN, Stack

    stack = Stack(tmp_path)
    await stack.serve_control()
    try:
        stack.core = JarvisCoreApplication(data_root=tmp_path / "core", product_edition=PRESENTATION_EDITION)
        await stack.core.start()
        stack.server = LocalProtocolServer(stack.core, host="127.0.0.1", port=stack.core_port, token=CC_TOKEN)
        await stack.server.start()
        status, edition = await stack.call("GET", "/api/boards/edition")
        assert status == 200 and edition["edition"] == "presentation", edition
        status, refused = await stack.call("POST", "/api/boards", json={"title": "X", "board_kind": "assistant"})
        assert status == 409 and refused["error"]["code"] == "board_kind_unavailable"
    finally:
        await stack.close()


# ------------------------------------------------------------------ MCP jarvis-workspace


async def _tools(edition):
    from jarvis.runtime.workspace_mcp import WorkspaceMcpTarget, WorkspaceTools, build_server

    server = build_server(tools=WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", 1)), edition=edition)
    return {tool.name: tool for tool in await server.list_tools()}


async def test_presentation_board_create_has_no_kind_to_choose():
    tool = (await _tools(PRESENTATION_EDITION))["board_create"]
    assert "board_kind" not in tool.inputSchema["properties"]
    for word in ("assistant", "meeting", "Réunion"):
        assert word not in (tool.description or "")
    assert "Présentation" in tool.description


async def test_full_board_create_keeps_the_three_kinds():
    tool = (await _tools(FULL_EDITION))["board_create"]
    kind = tool.inputSchema["properties"]["board_kind"]
    pattern = next(item["pattern"] for item in kind["anyOf"] if "pattern" in item)
    assert pattern == r"^(assistant|presentation|meeting)$"


async def test_through_mcp_presentation_create_sends_presentation_and_refuses_a_kind(tmp_path):
    from mcp.shared.memory import create_connected_server_and_client_session

    from jarvis.runtime.workspace_mcp import WorkspaceMcpTarget, WorkspaceTools, build_server
    from tests.unit.test_workspace_mcp import FakeControlCenter, _board

    fake = FakeControlCenter()
    await fake.start()
    ws = WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", fake.port, tmp_path))
    try:
        fake.answer("POST", "/api/boards", 201, {"board": _board(board_kind="presentation"), "active": False})
        server = build_server(tools=ws, edition=PRESENTATION_EDITION)
        async with create_connected_server_and_client_session(server) as session:
            forged = await session.call_tool("board_create", {"title": "Pitch", "board_kind": "assistant"})
            assert forged.isError and "Arguments inconnus" in forged.content[0].text
            assert fake.requests == []
            created = await session.call_tool("board_create", {"title": "Pitch"})
            assert created.isError is False, created.content[0].text
        assert fake.requests[-1][3] == {"title": "Pitch", "board_kind": "presentation"}
    finally:
        await ws.close()
        await fake.stop()


async def test_a_brain_switch_to_a_legacy_board_is_refused_before_sending(tmp_path):
    """Différée pendant un tour, la bascule ne rendrait son refus qu'au journal : il est dit avant l'envoi."""

    from jarvis.runtime import workspace_boards
    from jarvis.runtime.workspace_mcp import WorkspaceMcpTarget, WorkspaceToolError, WorkspaceTools
    from tests.unit.test_workspace_mcp import FakeControlCenter, _board

    fake = FakeControlCenter()
    await fake.start()
    ws = WorkspaceTools(WorkspaceMcpTarget("127.0.0.1", fake.port, tmp_path), edition=PRESENTATION_EDITION)
    try:
        fake.answer("GET", "/api/boards/default", 200,
                    {"board": _board("default", "Board principal", board_kind="assistant"), "active": False})
        with pytest.raises(WorkspaceToolError) as refused:
            await ws.boards.switch_board("default")
        assert refused.value.code == "board_kind_unavailable"
        assert workspace_boards.ERROR_SENTENCES["board_kind_unavailable"] in str(refused.value)
        assert [request[:2] for request in fake.requests] == [("GET", "/api/boards/default")]
    finally:
        await ws.close()
        await fake.stop()


def test_the_mcp_config_carries_the_edition_to_the_server(tmp_path, monkeypatch):
    from jarvis.runtime.workspace_mcp import SERVER_NAME, WorkspaceMcpTarget, mcp_config

    target = WorkspaceMcpTarget("127.0.0.1", 17654, tmp_path)
    monkeypatch.delenv(PRODUCT_EDITION_ENV, raising=False)
    assert mcp_config(target)["mcpServers"][SERVER_NAME]["env"][PRODUCT_EDITION_ENV] == "full"
    monkeypatch.setenv(PRODUCT_EDITION_ENV, "presentation")
    assert mcp_config(target)["mcpServers"][SERVER_NAME]["env"][PRODUCT_EDITION_ENV] == "presentation"


async def test_the_server_reads_the_edition_from_its_environment(monkeypatch):
    monkeypatch.setenv(PRODUCT_EDITION_ENV, "presentation")
    tool = (await _tools(None))["board_create"]
    assert "board_kind" not in tool.inputSchema["properties"]


# ------------------------------------------------------------------ consigne du cerveau


def test_the_presentation_prompt_offers_no_unavailable_kind():
    from jarvis.runtime import claude_local

    full = claude_local.workspace_prompt_for(None)
    assert full == claude_local.BRAIN_WORKSPACE_PROMPT == claude_local.workspace_prompt_for("full")
    presentation = claude_local.workspace_prompt_for("presentation")
    assert claude_local.BRAIN_WORKSPACE_KINDS_LINE not in presentation
    assert claude_local.BRAIN_WORKSPACE_PRESENTATION_KINDS_LINE in presentation
    assert "board_kind presentation / assistant / meeting" not in presentation
    assert "board_kind_unavailable" in presentation


def test_the_prompt_registry_renders_the_edition_line():
    from jarvis.runtime import claude_local
    from jarvis.runtime.prompt_catalog import _brain_workspace

    assert _brain_workspace({}) == claude_local.BRAIN_WORKSPACE_PROMPT
    assert _brain_workspace({claude_local.BRAIN_PRODUCT_EDITION_VARIABLE: "presentation"}) \
        == claude_local.workspace_prompt_for("presentation")
