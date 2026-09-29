"""Bloc `board` du tour, hôte des cerveaux côté Core et route de bascule (handoff board-session, Slice 04b)."""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timezone

import aiohttp
import pytest
from aiohttp import web

from jarvis.adapters.control_center_brain import ControlCenterBoardHost, ControlCenterBrainBackend, _turn_context
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.brain_context import MAX_BRAIN_BOARD_CONTEXT_CHARS, BrainBoardContext
from jarvis.domain.v2 import BrainTurnInput
from jarvis.domain.work_state import WorkObservation, WorkStatus, apply_observation
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_ID, BoardConversationBinding, BoardError, BoardErrorCode, BrainLifecycle, create_board,
    new_session_id, update_board,
)
from jarvis.ports.workspace_board import HOST_UNCHANGED, HOST_UNKNOWN
from jarvis.protocol.server import LocalProtocolServer

T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
TOKEN = "t" * 48


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ------------------------------------------------------------------ bloc board


def test_the_board_block_keeps_title_and_summary_whole_and_counts_the_refs_that_do_not_fit():
    board = update_board(create_board("Refonte", now=T0), now=T0, context_summary="x" * 1_500,
                         task_refs=tuple(f"TASK-{i:03d}-" + "t" * 40 for i in range(20)),
                         artifact_refs=("a/1",), project_refs=("p/1",))
    block = BrainBoardContext.from_board(board)
    payload = block.to_payload()
    assert payload["title"] == "Refonte" and payload["context_summary"] == "x" * 1_500
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    assert size <= MAX_BRAIN_BOARD_CONTEXT_CHARS
    kept = len(block.task_refs) + len(block.artifact_refs) + len(block.project_refs)
    assert 0 < kept < 22 and block.omitted_refs == 22 - kept
    # Ordre tâches -> artefacts -> projets, références entières, jamais coupées.
    assert block.task_refs == board.task_refs[:len(block.task_refs)]
    assert block.artifact_refs == () and block.project_refs == ()


def test_a_small_board_block_has_every_ref_and_no_omission_marker():
    board = update_board(create_board("Petit", now=T0), now=T0, task_refs=("T-1",), project_refs=("repo",))
    payload = BrainBoardContext.from_board(board).to_payload()
    assert payload == {"board_id": board.board_id, "title": "Petit", "context_summary": "", "task_refs": ["T-1"],
                       "artifact_refs": [], "project_refs": ["repo"]}


def test_the_turn_context_carries_the_board_block_only_when_there_is_one():
    turn = BrainTurnInput(conversation_id="c1", text="bonjour")
    assert "board" not in _turn_context(turn, None)
    board = BrainBoardContext(board_id=DEFAULT_BOARD_ID, title="Board principal", context_summary="Résumé")
    assert _turn_context(turn, None, board=board)["board"]["context_summary"] == "Résumé"


def test_the_first_board_affirmed_on_a_work_item_wins():
    first = apply_observation(None, WorkObservation(source="claude", external_id="t", status=WorkStatus.RUNNING,
                                                    observed_at=T0, board_id="board_a"), revision=1).item
    later = apply_observation(first, WorkObservation(source="claude", external_id="t", status=WorkStatus.RUNNING,
                                                     observed_at=T0, activity="x", board_id="board_b"), revision=2)
    assert later.item.board_id == "board_a" and "board_id" in later.conflicts
    untagged = apply_observation(None, WorkObservation(source="claude", external_id="u", status=WorkStatus.RUNNING,
                                                       observed_at=T0), revision=3).item
    tagged = apply_observation(untagged, WorkObservation(source="claude", external_id="u", status=WorkStatus.RUNNING,
                                                         observed_at=T0, activity="y", board_id="board_a"), revision=4)
    assert tagged.item.board_id == "board_a"


# ------------------------------------------------------------------ hôte côté Core


def _binding() -> BoardConversationBinding:
    return BoardConversationBinding(jarvis_session_id=new_session_id(), board_id=DEFAULT_BOARD_ID,
                                    conversation_id="conv-1", agent_cli="pending", created_at=T0, last_active_at=T0,
                                    lifecycle=BrainLifecycle.SUSPENDED)


async def _host_against(handler):
    app = web.Application()
    app.router.add_post("/api/agent/bindings/activate", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = free_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    backend = ControlCenterBrainBackend(base_url=f"http://127.0.0.1:{port}")
    return runner, backend


async def test_the_host_reads_the_cli_and_what_became_of_the_previous_brain():
    seen = []

    async def handler(request):
        seen.append(await request.json())
        return web.json_response({"ok": True, "agent_cli": "claude", "agent_session_id": "s-1",
                                  "previous": {"conversation_id": "conv-0", "lifecycle": "background_running"}})

    runner, backend = await _host_against(handler)
    try:
        activation = await backend.board_host.activate(_binding())
    finally:
        await backend.close()
        await runner.cleanup()
    assert seen[0]["conversation_id"] == "conv-1"
    assert (activation.agent_cli, activation.agent_session_id) == ("claude", "s-1")
    assert activation.previous_lifecycle is BrainLifecycle.BACKGROUND_RUNNING


@pytest.mark.parametrize("status,body,code", [
    (502, {"ok": False, "code": "board_activation_failed", "error": "Claude CLI not found"},
     BoardErrorCode.BOARD_ACTIVATION_FAILED),
    (409, {"ok": False, "code": "session_closed", "error": "closed"}, BoardErrorCode.SESSION_CLOSED),
    (400, {"ok": False, "code": "weird", "error": "?"}, BoardErrorCode.BOARD_ACTIVATION_FAILED),
])
async def test_a_host_refusal_keeps_its_code_and_says_nothing_changed(status, body, code):
    async def handler(request):
        return web.json_response(body, status=status)

    runner, backend = await _host_against(handler)
    try:
        with pytest.raises(BoardError) as caught:
            await backend.board_host.activate(_binding())
    finally:
        await backend.close()
        await runner.cleanup()
    assert caught.value.code is code and caught.value.host_state == HOST_UNCHANGED
    assert f"HTTP {status}" in str(caught.value)


async def test_an_unreachable_host_changed_nothing_and_a_slow_one_is_unknown(monkeypatch):
    backend = ControlCenterBrainBackend(base_url=f"http://127.0.0.1:{free_port()}")
    try:
        with pytest.raises(BoardError) as caught:
            await backend.board_host.activate(_binding())
        assert caught.value.host_state == HOST_UNCHANGED and "unreachable" in str(caught.value)
    finally:
        await backend.close()

    async def slow(request):
        await asyncio.sleep(1)
        return web.json_response({"ok": True, "agent_cli": "claude"})

    monkeypatch.setattr(ControlCenterBoardHost, "TIMEOUT_S", 0.1)
    runner, backend = await _host_against(slow)
    try:
        with pytest.raises(BoardError) as caught:
            await backend.board_host.activate(_binding())
    finally:
        await backend.close()
        await runner.cleanup()
    assert caught.value.code is BoardErrorCode.BOARD_ACTIVATION_FAILED and caught.value.host_state == HOST_UNKNOWN


# ------------------------------------------------------------------ route Core


@pytest.fixture
async def stack(tmp_path):
    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
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


async def test_the_switch_route_answers_the_transaction_and_its_refusals(stack):
    core, base = stack
    board = await core.boards.create({"title": "Projet B"})
    status, body = await _raw("POST", base + "/v1/boards/switch", json={"board_id": board.board_id})
    assert status == 200 and body["changed"] and body["board"]["board_id"] == board.board_id
    assert body["previous_board_id"] == DEFAULT_BOARD_ID and body["binding"]["lifecycle"] == "foreground"
    status, body = await _raw("POST", base + "/v1/boards/switch", json={"board_id": board.board_id})
    assert status == 200 and body["changed"] is False
    for payload, code, expected in (({"board_id": "board_" + "0" * 32}, "board_not_found", 404),
                                    ({"board": "x"}, "invalid_board", 400),
                                    ({"board_id": 3}, "invalid_board", 400)):
        status, body = await _raw("POST", base + "/v1/boards/switch", json=payload)
        assert (status, body["error"]["code"]) == (expected, code)


async def test_new_session_refuses_an_unknown_field(stack):
    _, base = stack
    status, body = await _raw("POST", base + "/v1/sessions/new", json={"activate_host": False})
    assert status == 400 and body["error"]["code"] == "invalid_session"
    status, _ = await _raw("POST", base + "/v1/sessions/new", json={})
    assert status == 201
