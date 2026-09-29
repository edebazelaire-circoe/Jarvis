"""`/v1/sessions*` de bout en bout : route, authentification, codes stables (handoff board-session, Slice 03)."""

from __future__ import annotations

import socket

import aiohttp
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer

TOKEN = "t" * 48


@pytest.fixture
async def stack(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        yield core, client, f"http://127.0.0.1:{port}"
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def _raw(method: str, url: str, *, token: str = TOKEN, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


async def test_current_session_carries_the_active_binding_conversation(stack):
    core, client, _ = stack
    current = await client.current_session()
    assert current["session"]["status"] == "open"
    assert current["session"]["active_board_id"] == DEFAULT_BOARD_ID
    binding = current["binding"]
    assert binding["board_id"] == DEFAULT_BOARD_ID and binding["lifecycle"] == "foreground"
    assert binding["jarvis_session_id"] == current["session"]["jarvis_session_id"]
    assert await core.state.get_conversation(binding["conversation_id"]) is not None


async def test_new_session_answers_201_and_history_lists_both(stack):
    _, client, _ = stack
    before = await client.current_session()
    created = await client.new_session(expected_session_id=before["session"]["jarvis_session_id"])
    assert created["closed_session"]["jarvis_session_id"] == before["session"]["jarvis_session_id"]
    assert created["closed_session"]["end_reason"] == "new_session"
    assert created["binding"]["conversation_id"] != before["binding"]["conversation_id"]
    assert (await client.current_session())["session"] == created["session"]
    history = (await client.list_sessions())["sessions"]
    assert [s["jarvis_session_id"] for s in history] == [
        created["session"]["jarvis_session_id"], before["session"]["jarvis_session_id"]]
    assert len((await client.list_sessions(limit=1))["sessions"]) == 1


async def test_a_closed_session_cannot_be_mutated_through_the_routes(stack):
    _, client, base = stack
    first = await client.current_session()
    await client.new_session()
    closed_before = (await client.list_sessions())["sessions"][1]
    # Le second clic d'un onglet resté sur l'ancienne Session : 409, rien n'est ouvert.
    with pytest.raises(CoreProtocolError) as raised:
        await client.new_session(expected_session_id=first["session"]["jarvis_session_id"])
    assert (raised.value.status, raised.value.code) == (409, "session_closed")
    history = (await client.list_sessions())["sessions"]
    assert len(history) == 2 and history[1] == closed_before
    status, body = await _raw("POST", base + "/v1/sessions/new", json={"expected_session_id": "jsess_" + "0" * 32})
    assert (status, body["error"]["code"]) == (404, "session_not_found")


@pytest.mark.parametrize("method, path, kwargs, code", [
    ("GET", "/v1/sessions?limit=0", {}, "invalid_session"),
    ("GET", "/v1/sessions?limit=101", {}, "invalid_session"),
    ("GET", "/v1/sessions?limit=abc", {}, "invalid_request"),
    ("GET", "/v1/sessions?other=1", {}, "invalid_request"),
    ("GET", "/v1/sessions/current?x=1", {}, "invalid_request"),
    ("POST", "/v1/sessions/new", {"json": {"unknown": 1}}, "invalid_session"),
    ("POST", "/v1/sessions/new", {"json": {"expected_session_id": 3}}, "invalid_session"),
    ("POST", "/v1/sessions/new", {"data": b"{not json", "headers": {"Content-Type": "application/json"}},
     "invalid_request"),
])
async def test_malformed_session_requests_are_400(stack, method, path, kwargs, code):
    _, _, base = stack
    headers = {"Authorization": f"Bearer {TOKEN}", **kwargs.pop("headers", {})}
    async with aiohttp.ClientSession() as session:
        async with session.request(method, base + path, headers=headers, **kwargs) as response:
            body = await response.json(content_type=None)
            assert (response.status, body["error"]["code"]) == (400, code)


async def test_session_routes_require_the_token(stack):
    _, _, base = stack
    for method, path in (("GET", "/v1/sessions/current"), ("GET", "/v1/sessions"), ("POST", "/v1/sessions/new")):
        status, body = await _raw(method, base + path, token="x" * 48)
        assert (status, body["error"]["code"]) == (401, "unauthorized")


async def test_session_routes_answer_503_when_core_is_not_ready(stack):
    core, client, _ = stack
    core.health.ready = False
    try:
        with pytest.raises(CoreProtocolError) as raised:
            await client.current_session()
        assert (raised.value.status, raised.value.code) == (503, "core_unavailable")
        with pytest.raises(CoreProtocolError) as raised:
            await client.new_session()
        assert raised.value.status == 503
    finally:
        core.health.ready = True


# ------------------------------------------------ rapport du CLI réel (Slice 04a)


async def test_the_control_center_reports_the_real_cli_of_a_binding(stack):
    _, client, _ = stack
    current = await client.current_session()
    assert current["binding"]["agent_cli"] == "pending"
    ids = {"jarvis_session_id": current["session"]["jarvis_session_id"], "board_id": DEFAULT_BOARD_ID}

    reported = await client.report_binding_agent(**ids, agent_cli="claude", agent_session_id="claude-sess-1")

    assert reported["binding"]["agent_cli"] == "claude"
    assert reported["binding"]["agent_session_id"] == "claude-sess-1"
    assert (await client.current_session())["binding"] == reported["binding"]
    # Une Session close accepte encore le rapport : son CLI finit peut-être du travail.
    await client.new_session()
    late = await client.report_binding_agent(**ids, agent_cli="claude", agent_session_id="claude-sess-2")
    assert late["binding"]["status"] == "closed" and late["binding"]["agent_session_id"] == "claude-sess-2"


@pytest.mark.parametrize("body, status, code", [
    ({"jarvis_session_id": "jsess_" + "0" * 32, "board_id": "default", "agent_cli": "claude",
      "agent_session_id": None}, 404, "session_not_found"),
    ({"board_id": "default", "agent_cli": "claude", "agent_session_id": None}, 400, "invalid_binding"),
    ({"jarvis_session_id": "x", "board_id": "default", "agent_cli": 3, "agent_session_id": None},
     400, "invalid_binding"),
])
async def test_a_bad_binding_report_is_refused_with_its_code(stack, body, status, code):
    _, _, base = stack
    got_status, payload = await _raw("POST", base + "/v1/sessions/bindings/report", json=body)
    assert (got_status, payload["error"]["code"]) == (status, code)


async def test_a_report_for_an_unbound_board_is_binding_not_found(stack):
    _, client, _ = stack
    current = await client.current_session()
    with pytest.raises(CoreProtocolError) as raised:
        await client.report_binding_agent(jarvis_session_id=current["session"]["jarvis_session_id"],
                                          board_id="board_" + "a" * 32, agent_cli="claude", agent_session_id=None)
    assert (raised.value.status, raised.value.code) == (404, "binding_not_found")
