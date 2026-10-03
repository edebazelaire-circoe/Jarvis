"""`/v1/boards*` de bout en bout : route, authentification, codes stables (handoff board-session, Slice 02)."""

from __future__ import annotations

import socket

import aiohttp
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import MAX_BOARD_BODY_BYTES, LocalProtocolServer

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


async def test_list_and_active_start_with_the_default_board(stack):
    _, client, _ = stack
    listing = await client.list_boards()
    assert [b["board_id"] for b in listing["boards"]] == [DEFAULT_BOARD_ID]
    assert listing["active_board_id"] == DEFAULT_BOARD_ID
    active = await client.active_board()
    assert active["active"] is True and active["board"]["board_id"] == DEFAULT_BOARD_ID
    assert active["board"]["interaction_mode_origin"] == "unset"


async def test_create_get_update_archive_round_trip(stack):
    _, client, _ = stack
    created = await client.create_board({"title": "Projet B", "task_refs": ["t1"]})
    board_id = created["board"]["board_id"]
    assert created["active"] is False and board_id.startswith("board_")
    assert (await client.get_board(board_id))["board"]["task_refs"] == ["t1"]
    updated = await client.update_board(board_id, {"context_summary": "Résumé\nsur deux lignes"})
    assert updated["board"]["context_summary"] == "Résumé\nsur deux lignes"
    archived = await client.archive_board(board_id)
    assert archived["board"]["status"] == "archived"
    assert [b["board_id"] for b in (await client.list_boards())["boards"]] == [DEFAULT_BOARD_ID]
    assert len((await client.list_boards(include_archived=True))["boards"]) == 2


async def test_create_answers_201(stack):
    _, _, base = stack
    status, body = await _raw("POST", base + "/v1/boards", json={"title": "B"})
    assert status == 201 and body["board"]["title"] == "B"


@pytest.mark.parametrize("call, status, code", [
    (lambda c: c.get_board("board_nope"), 404, "board_not_found"),
    (lambda c: c.update_board("board_nope", {"title": "x"}), 404, "board_not_found"),
    (lambda c: c.archive_board(DEFAULT_BOARD_ID), 409, "board_is_active"),
    (lambda c: c.create_board({}), 400, "invalid_title"),
    (lambda c: c.create_board({"title": "x", "surprise": 1}), 400, "invalid_board"),
    (lambda c: c.create_board({"title": "x", "context_summary": "y" * 1501}), 400, "context_summary_too_long"),
    (lambda c: c.update_board(DEFAULT_BOARD_ID, {}), 400, "invalid_board"),
])
async def test_refusals_keep_their_stable_code_and_status(stack, call, status, code):
    _, client, _ = stack
    with pytest.raises(CoreProtocolError) as refus:
        await call(client)
    assert (refus.value.status, refus.value.code) == (status, code)


async def test_an_archived_board_cannot_be_updated(stack):
    _, client, _ = stack
    board_id = (await client.create_board({"title": "B"}))["board"]["board_id"]
    await client.archive_board(board_id)
    with pytest.raises(CoreProtocolError) as refus:
        await client.update_board(board_id, {"title": "x"})
    assert (refus.value.status, refus.value.code) == (409, "board_archived")


async def test_malformed_requests_are_400_and_auth_is_required(stack):
    _, _, base = stack
    assert (await _raw("GET", base + "/v1/boards", token="x" * 48))[0] == 401
    status, body = await _raw("POST", base + "/v1/boards", data=b"{not json")
    assert status == 400 and body["error"]["code"] == "invalid_request"
    status, _ = await _raw("GET", base + "/v1/boards?include_archived=yes")
    assert status == 400
    status, _ = await _raw("GET", base + "/v1/boards?surprise=1")
    assert status == 400
    status, _ = await _raw("POST", base + f"/v1/boards/{DEFAULT_BOARD_ID}/archive", json={"force": True})
    assert status == 400
    status, _ = await _raw("POST", base + "/v1/boards", data=b"{" + b" " * MAX_BOARD_BODY_BYTES + b"}")
    assert status == 400


async def test_a_damaged_row_is_a_500_with_its_own_code(stack):
    core, _, base = stack
    await core.state.run_serialized(lambda c: c.execute("UPDATE work_boards SET data='{}'"))
    status, body = await _raw("GET", base + "/v1/boards")
    assert status == 500 and body["error"]["code"] == "board_store_unreadable"
    assert "work_boards row 'default'" in body["error"]["message"]


async def test_a_mode_change_over_the_protocol_lands_on_the_active_board(stack):
    core, client, _ = stack
    await client.set_interaction_mode("presentation", source="control_center")
    await core.boards.drain()
    board = (await client.active_board())["board"]
    assert (board["interaction_mode"], board["interaction_mode_origin"]) == ("presentation", "user")


async def test_board_kind_travels_over_http_and_never_touches_the_interaction_mode(stack):
    core, client, base = stack
    status, body = await _raw("POST", base + "/v1/boards", json={"title": "Réunion", "board_kind": "meeting"})
    assert status == 201 and body["board"]["board_kind"] == "meeting"
    status, body = await _raw("POST", base + "/v1/boards", json={"title": "Sans nature"})
    assert status == 201 and body["board"]["board_kind"] == "empty"

    await client.set_interaction_mode("presentation", source="control_center")
    await core.boards.drain()
    status, body = await _raw("PATCH", base + f"/v1/boards/{DEFAULT_BOARD_ID}", json={"board_kind": "meeting"})
    assert status == 200 and body["board"]["board_kind"] == "meeting"
    assert (body["board"]["interaction_mode"], body["board"]["interaction_mode_origin"]) == ("presentation", "user")

    for invalid in ("Meeting", "réunion", "", None, 1):
        status, body = await _raw("PATCH", base + f"/v1/boards/{DEFAULT_BOARD_ID}", json={"board_kind": invalid})
        assert status == 400 and body["error"]["code"] == "invalid_board", (invalid, body)
    status, body = await _raw("POST", base + "/v1/boards", json={"title": "x", "board_kind": "unknown"})
    assert status == 400 and body["error"]["code"] == "invalid_board"
    assert (await client.get_board(DEFAULT_BOARD_ID))["board"]["board_kind"] == "meeting"
