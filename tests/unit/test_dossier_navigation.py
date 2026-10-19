"""Canal agent -> page du Dossier (`jarvis/runtime/dossier_navigation.py`, wheel-dossier-refactor Slice 05).

Le consommateur (la page) arrive en Slice 07 : ici, le contrat du transport est éprouvé contre une page simulée
(long-poll + reçu à jeton). Chaque issue est nommée ; aucune ne vaut succès par défaut.
"""

from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.dossier_navigation import NAVIGATION_ROUTE, PAGE_TOKEN_HEADER, DossierNavigationRoutes

NAV = NAVIGATION_ROUTE + "/commands"
ASK = {"board_id": "board_ab12", "entry_id": "memory:notes/plan.md"}


@pytest.fixture
async def channel():
    routes = DossierNavigationRoutes()
    routes.broker.deadline_s = 0.5
    app = web.Application()
    app.add_routes(routes.routes())
    client = TestClient(TestServer(app))
    await client.start_server()
    yield client, routes
    routes.close()
    await client.close()


async def _json(response) -> tuple[int, dict]:
    return response.status, await response.json()


async def _poll(client, **params) -> dict:
    status, body = await _json(await client.get(NAV, params={"wait_s": "2", **params}))
    assert status == 200, body
    return body


async def test_a_refused_receipt_is_returned_with_its_code(channel):
    client, routes = channel
    ask = asyncio.ensure_future(client.post(NAV, json=ASK))
    command = (await _poll(client, page="pagea"))["command"]
    assert (command["action"], command["board_id"], command["entry_id"]) == ("open_entry", "board_ab12",
                                                                              "memory:notes/plan.md")
    assert command["remaining_ms"] > 0
    assert (await _poll(client, wait_s="0"))["command"] is None, "delivered once, exclusively"
    status, _ = await _json(await client.post(f"{NAV}/{command['id']}", json={"state": "refused", "code": "busy_ui"},
                                              headers={PAGE_TOKEN_HEADER: routes.broker.page_token}))
    assert status == 200
    status, answer = await _json(await ask)
    assert status == 200 and (answer["state"], answer["code"]) == ("refused", "busy_ui")


async def test_no_page_expired_page_busy_and_bad_token_are_each_named(channel):
    client, routes = channel
    status, body = await _json(await client.post(NAV, json=ASK))
    assert (status, body["error"]["code"]) == (504, "no_visible_page")

    ask = asyncio.ensure_future(client.post(NAV, json=ASK))
    command = (await _poll(client))["command"]
    status, busy = await _json(await client.post(NAV, json=ASK))
    assert (status, busy["error"]["code"]) == (409, "command_busy")
    status, forged = await _json(await client.post(f"{NAV}/{command['id']}", json={"state": "opened"}))
    assert (status, forged["error"]["code"]) == (403, "bad_page_token")
    status, body = await _json(await ask)
    assert (status, body["error"]["code"]) == (504, "command_expired"), "taken but never answered: unknown"
    status, late = await _json(await client.post(f"{NAV}/{command['id']}", json={"state": "opened"},
                                                 headers={PAGE_TOKEN_HEADER: routes.broker.page_token}))
    assert (status, late["error"]["code"]) == (404, "unknown_command_id")


async def test_a_malformed_receipt_answers_the_agent_at_once_and_a_hidden_page_gets_nothing(channel):
    client, routes = channel
    routes.broker.deadline_s = 3.0
    ask = asyncio.ensure_future(client.post(NAV, json=ASK))
    assert (await _poll(client, page="hidden1", visible="0"))["command"] is None
    assert (await _poll(client, page="hidden1", wait_s="0.2"))["command"] is not None, "visible again: delivered"
    command_id = routes.broker._pending.command_id  # noqa: SLF001
    status, _ = await _json(await client.post(f"{NAV}/{command_id}", json={"state": "maybe"},
                                              headers={PAGE_TOKEN_HEADER: routes.broker.page_token}))
    assert status == 400
    status, body = await _json(await asyncio.wait_for(ask, 1.0))
    assert (status, body["error"]["code"]) == (502, "bad_receipt") and "n'annoncez ni succès" in body["error"]["message"]


@pytest.mark.parametrize("body, code", [
    ({"board_id": "board_ab12"}, "bad_request"),
    ({**ASK, "extra": 1}, "bad_request"),
    ({"board_id": "x y", "entry_id": "memory:a.md"}, "bad_request"),
    ({"board_id": "board_ab12", "entry_id": "memory:../a.md"}, "dossier_entry_invalid"),
])
async def test_malformed_requests_are_refused_before_any_delivery(channel, body, code):
    client, _ = channel
    status, refused = await _json(await client.post(NAV, json=body))
    assert (status, refused["error"]["code"]) == (400, code)
    assert (await _poll(client, wait_s="0"))["command"] is None


async def test_closing_the_control_center_answers_a_waiting_agent(channel):
    client, routes = channel
    routes.broker.deadline_s = 5.0
    ask = asyncio.ensure_future(client.post(NAV, json=ASK))
    await asyncio.sleep(0.05)
    routes.close()
    status, body = await _json(await asyncio.wait_for(ask, 1.0))
    assert (status, body["error"]["code"]) == (503, "command_cancelled")


async def test_the_status_block_says_a_command_waits_until_one_page_takes_it(channel):
    """Slice 08 (QA B1) : la page ne tient plus de long-poll ; `/api/status.dossier_navigation.pending` lui dit
    de relever la commande d'un GET court. Remise exclusive : un seul relevé l'obtient."""
    client, routes = channel
    routes.broker.deadline_s = 2.0
    assert routes.broker.status_block() == {"pending": False}
    asked = asyncio.ensure_future(client.post(NAV, json=ASK))
    for _ in range(50):
        if routes.broker.status_block()["pending"]:
            break
        await asyncio.sleep(0.02)
    assert routes.broker.status_block() == {"pending": True}
    first = await _json(await client.get(NAV, params={"wait_s": "0", "page": "pageA", "visible": "1"}))
    second = await _json(await client.get(NAV, params={"wait_s": "0", "page": "pageB", "visible": "1"}))
    assert first[1]["command"] is not None and second[1]["command"] is None, "a single page executes it"
    assert routes.broker.status_block() == {"pending": False}
    await client.post(f"{NAV}/{first[1]['command']['id']}", json={"state": "opened"},
                      headers={PAGE_TOKEN_HEADER: routes.broker.page_token})
    status, body = await _json(await asked)
    assert status == 200 and body["state"] == "opened"
