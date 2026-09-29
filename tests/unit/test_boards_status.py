"""Bloc `boards` de `GET /api/status` (handoff board-session, Slice 06).

Le contrôle Boards du haut-droit suit ce bloc chaque seconde : une bascule faite
par la voix ou par MCP doit y apparaître sans que la page ne la demande. On
l'exerce sur un vrai Core et un vrai Control Center (`Stack` de la Slice 04b).
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
from tests.unit.test_board_brains_control_center import make_control
from tests.unit.test_board_switch_control_center import Stack


@pytest.fixture
async def stack(tmp_path):
    stack = Stack(tmp_path)
    await stack.serve_control()
    try:
        yield stack
    finally:
        await stack.close()


async def _boards(control) -> dict:
    return json.loads((await control.status(None)).text)["boards"]


async def test_the_status_names_the_active_board_and_the_open_session(stack):
    core = await stack.start_core()
    current = await core.sessions.current()

    boards = await _boards(stack.control)

    assert boards["available"] is True and boards["error"] is None
    assert boards["active"] == {"board_id": DEFAULT_BOARD_ID, "title": boards["active"]["title"]}
    assert boards["active"]["title"]
    assert boards["jarvis_session_id"] == current.session.jarvis_session_id
    assert {"board_id": DEFAULT_BOARD_ID, "lifecycle": "foreground", "agent_cli": boards["bindings"][0]["agent_cli"],
            "closed": False} in boards["bindings"]


async def test_a_switch_made_elsewhere_reaches_the_status_with_the_left_board_working(stack):
    """La bascule passe par la route (comme MCP) ; le statut suivant la montre."""

    await stack.start_core()
    stack.control.board_brains.foreground.agent.start_subagent("t1")        # A travaille encore
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    b = created["board"]["board_id"]
    status, _ = await stack.call("POST", "/api/boards/switch", json={"board_id": b})
    assert status == 200

    boards = await _boards(stack.control)

    assert boards["active"] == {"board_id": b, "title": "Projet B"}
    lifecycles = {row["board_id"]: row["lifecycle"] for row in boards["bindings"]}
    assert lifecycles == {DEFAULT_BOARD_ID: "background_running", b: "foreground"}


async def test_a_new_session_changes_the_session_id_and_keeps_the_board(stack):
    await stack.start_core()
    before = await _boards(stack.control)
    status, _ = await stack.call("POST", "/api/sessions/new", json={})
    assert status == 201

    after = await _boards(stack.control)

    assert after["jarvis_session_id"] != before["jarvis_session_id"]
    assert after["active"] == before["active"]


async def test_the_status_survives_a_core_that_does_not_answer(stack):
    """Core arrêté : le bloc dit pourquoi, le statut ne tombe pas."""

    boards = await _boards(stack.control)                    # Core jamais démarré

    assert boards["available"] is False and boards["active"] is None
    assert boards["error"]["code"] == "core_unreachable"


async def test_without_a_core_transport_the_boards_are_unavailable_and_say_so(tmp_path):
    control = make_control(tmp_path)
    try:
        boards = await _boards(control)
    finally:
        await control.board_brains.aclose()

    assert boards["available"] is False
    assert boards["error"]["code"] == "core_unconfigured"
    assert boards["active"] is None
