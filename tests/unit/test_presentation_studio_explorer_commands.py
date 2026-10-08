"""Canal de l'explorateur de variantes, de l'agent à la page, sur un vrai Control Center (studio de présentation, Slice 18).

Chaîne réelle : requête HTTP de l'agent -> `ExplorerCommandBroker` -> long-poll -> reçu -> rapports d'état. Seule la page est remplacée par un
client qui appelle exactement les routes que la vraie page appelle (`control_center_presentation_studio_explorer.js`).

Épinglé ici :

- **une ouverture ne dit que ce que la page a constaté** : le reçu porte le `mode` (`windowed`, `fullscreen_armed`, `fullscreen`) ou un refus à
  code fermé (lecture en cours, présentation inconnue...) ; jamais un succès par défaut ;
- **aucune page = refus codé** (504 `explorer_no_visible_page`), une page qui prend la commande et se tait = `explorer_command_expired` ;
- **une commande en vol à la fois, remise exclusive, identifiant à usage unique** ; un reçu mal formé solde la commande tout de suite ;
- **le miroir d'état est daté** : une page muette depuis 60 s rend `unknown`, jamais `open` périmé ;
- **aucun contenu** (titre, raison) ne traverse le canal ni le journal ;
- **garde d'origine** : un cadre de prefab (`Origin: null`) ne peut ni consommer, ni dicter, ni lire.
"""

from __future__ import annotations

import asyncio
import socket

import aiohttp
from aiohttp import web
import pytest

from jarvis.domain import presentation_studio_explorer as vocab
from jarvis.runtime.control_center import (
    READ_GUARDED_ROUTES,
    SETTINGS_ERROR_CODE_HEADER,
    STUDIO_EXPLORER_CORE_SCRIPT_MARKER,
    STUDIO_EXPLORER_SCRIPT_MARKER,
    STUDIO_EXPLORER_WIDGETS_SCRIPT_MARKER,
    ControlCenter,
)
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.presentation_studio_explorer_commands import EXPLORER_ROUTE, ExplorerCommandBroker

PID = "pst_" + "0123456789abcdef" * 2
VID = "psv_" + "ab" * 16
OTHER_VID = "psv_" + "cd" * 16
PAGE = "pageAAAA1111"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class RunningCenter:
    def __init__(self, control: ControlCenter, port: int) -> None:
        self.control = control
        self.base = f"http://127.0.0.1:{port}" + EXPLORER_ROUTE

    async def ask(self, session, body, *, headers=None) -> tuple[int, dict, str]:
        async with session.post(f"{self.base}/commands", json=body, headers=headers) as response:
            return response.status, await response.json(), response.headers.get(SETTINGS_ERROR_CODE_HEADER, "")

    async def poll(self, session, wait_s: float = 5, extra: str = "") -> dict:
        async with session.get(f"{self.base}/commands?wait_s={wait_s}&page={PAGE}{extra}") as response:
            assert response.status == 200, await response.text()
            return await response.json()

    def token(self) -> dict:
        return {vocab.PAGE_TOKEN_HEADER: self.control.studio_explorer.broker.page_token}

    async def receipt(self, session, command_id, body, *, headers=None) -> tuple[int, dict, str]:
        async with session.post(f"{self.base}/commands/{command_id}", json=body, headers=self.token() if headers is None else headers) as response:
            return response.status, await response.json(), response.headers.get(SETTINGS_ERROR_CODE_HEADER, "")

    async def report(self, session, body, *, headers=None) -> tuple[int, dict, str]:
        async with session.post(f"{self.base}/state", json=body, headers=self.token() if headers is None else headers) as response:
            return response.status, await response.json(), response.headers.get(SETTINGS_ERROR_CODE_HEADER, "")

    async def state(self, session) -> dict:
        async with session.get(f"{self.base}/state") as response:
            assert response.status == 200
            return await response.json()


@pytest.fixture
async def running(tmp_path):
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path, barehands_vendor_root=tmp_path / "vendor")
    port = free_port()
    runner = web.AppRunner(control._app)  # noqa: SLF001 - démarrage sans l'agent, volontaire
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        yield RunningCenter(control, port)
    finally:
        control.studio_explorer.close()
        await runner.cleanup()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


def lines(control: ControlCenter, prefix: str = "explorer.") -> list[dict]:
    return [line for line in read_jsonl_tail(control.journal.trace_path, limit=300) if line["kind"].startswith(prefix)]


OPEN = {"action": "open", "presentation_id": PID}


# ------------------------------------------------------------------ ouvrir : le mode est celui que la page a constaté

async def test_an_open_request_is_answered_with_the_mode_the_page_observed_and_the_state_is_readable(running, session):
    task = asyncio.create_task(running.ask(session, {**OPEN, "variant_id": VID}))
    command = (await running.poll(session))["command"]
    assert command["action"] == "open" and command["presentation_id"] == PID and command["variant_id"] == VID
    assert command["fullscreen"] is True and command["arm_s"] == vocab.ARM_DEFAULT_S
    status, _, _ = await running.receipt(session, command["id"], {
        "state": "opened", "mode": "fullscreen_armed", "fullscreen": "needs_gesture", "presentation_id": PID, "variant_id": VID})
    assert status == 200
    status, answer, _ = await task
    assert status == 200
    assert answer["state"] == "opened" and answer["mode"] == "fullscreen_armed" and answer["fullscreen"] == "needs_gesture"
    assert answer["deliveries"] == 1 and "clic" in answer["explanation"] and "entered" not in answer["explanation"]
    # Le miroir ne dit « open » qu'après le rapport de la page.
    assert (await running.state(session))["state"] == "closed"
    status, snap, _ = await running.report(session, {"open": True, "mode": "fullscreen_armed", "fullscreen": "needs_gesture",
                                                     "presentation_id": PID, "variant_id": VID, "variant_number": 3})
    assert status == 200 and snap["state"] == "open" and snap["mode"] == "fullscreen_armed" and snap["variant_number"] == 3
    status, snap, _ = await running.report(session, {"open": True, "mode": "fullscreen", "fullscreen": "entered",
                                                     "presentation_id": PID, "variant_id": VID, "variant_number": 3})
    assert snap["mode"] == "fullscreen" and "plein écran" in snap["explanation"]
    status, snap, _ = await running.report(session, {"open": False, "fullscreen": "exited"})
    assert snap["state"] == "closed" and snap["mode"] is None and snap["presentation_id"] is None
    assert {"explorer.command_requested", "explorer.command_delivered", "explorer.command_answered",
            "explorer.state_changed"} <= {line["kind"] for line in lines(running.control)}


async def test_a_refusal_carries_a_closed_code_and_the_reason_is_bounded(running, session):
    task = asyncio.create_task(running.ask(session, OPEN))
    command = (await running.poll(session))["command"]
    status, _, _ = await running.receipt(session, command["id"], {
        "state": "refused", "code": vocab.RUN_IN_PROGRESS, "reason": "x" * 900})
    assert status == 200
    status, answer, _ = await task
    assert status == 200 and answer["state"] == "refused" and answer["code"] == vocab.RUN_IN_PROGRESS
    assert len(answer["reason"]) == vocab.MAX_REASON_CHARS
    assert "sans prétendre l'inverse" in answer["explanation"]


async def test_close_is_a_command_too_and_takes_no_field(running, session):
    status, answer, code = await running.ask(session, {"action": "close", "presentation_id": PID})
    assert status == 400 and code == vocab.BAD_REQUEST and "close ne prend aucun champ" in answer["error"]["message"]
    task = asyncio.create_task(running.ask(session, {"action": "close"}))
    command = (await running.poll(session))["command"]
    assert command == {"id": command["id"], "remaining_ms": command["remaining_ms"], "action": "close"}
    status, _, _ = await running.receipt(session, command["id"], {"state": "closed"})
    assert status == 200
    status, answer, _ = await task
    assert answer["state"] == "closed" and "fermé" in answer["explanation"]


# ------------------------------------------------------------------ aucune page, une page muette

async def test_no_visible_page_is_a_coded_504_never_an_optimistic_200(running, session):
    running.control.studio_explorer.broker.deadline_s = 0.3
    status, answer, code = await running.ask(session, OPEN)
    assert status == 504 and code == vocab.NO_VISIBLE_PAGE and answer["error"]["code"] == vocab.NO_VISIBLE_PAGE
    assert any(line["data"]["code"] == vocab.NO_VISIBLE_PAGE for line in lines(running.control, "explorer.command_expired"))


async def test_a_page_that_takes_the_command_and_stays_silent_is_a_different_code(running, session):
    running.control.studio_explorer.broker.deadline_s = 0.4
    task = asyncio.create_task(running.ask(session, OPEN))
    assert (await running.poll(session))["command"] is not None
    status, answer, code = await task
    assert status == 504 and code == vocab.COMMAND_EXPIRED and "issue est inconnue" in answer["error"]["message"]


async def test_a_hidden_page_never_receives_a_command(running, session):
    running.control.studio_explorer.broker.deadline_s = 0.5
    task = asyncio.create_task(running.ask(session, OPEN))
    assert (await running.poll(session, 0, "&visible=0"))["command"] is None
    status, _, code = await task
    assert status == 504 and code == vocab.NO_VISIBLE_PAGE, "the only page that spoke said it was hidden"
    # Visible again: the next poll receives the next command.
    running.control.studio_explorer.broker.deadline_s = 3
    task = asyncio.create_task(running.ask(session, OPEN))
    assert (await running.poll(session, 2, "&visible=1"))["command"] is not None
    task.cancel()


# ------------------------------------------------------------------ une commande à la fois, un identifiant à usage unique

async def test_one_command_in_flight_exclusive_delivery_and_single_use_id(running, session):
    first = asyncio.create_task(running.ask(session, OPEN))
    command = (await running.poll(session))["command"]
    status, busy, code = await running.ask(session, {"action": "close"})
    assert status == 409 and code == vocab.COMMAND_BUSY
    assert (await running.poll(session, 0.2))["command"] is None, "a command is delivered once"
    ok = {"state": "opened", "mode": "windowed", "fullscreen": "unsupported"}
    assert (await running.receipt(session, command["id"], ok))[0] == 200
    assert (await first)[0] == 200
    status, again, code = await running.receipt(session, command["id"], ok)
    assert status == 404 and code == vocab.UNKNOWN_COMMAND_ID
    status, _, code = await running.receipt(session, "short", ok)
    assert status == 404 and code == vocab.UNKNOWN_COMMAND_ID


@pytest.mark.parametrize("receipt", [
    {"state": "entered", "mode": "windowed"},                         # not an explorer state
    {"state": "opened"},                                              # opened without a mode
    {"state": "opened", "mode": "weird"},
    {"state": "refused"},                                             # a silent refusal would read as a transport failure
    {"state": "refused", "code": "free text"},
    {"state": "opened", "mode": "windowed", "extra": 1},
    {"state": "opened", "mode": "windowed", "fullscreen": "maybe"},
    {"state": "opened", "mode": "windowed", "variant_id": "../x"},
])
async def test_a_malformed_receipt_settles_the_command_at_once_with_its_cause(running, session, receipt):
    task = asyncio.create_task(running.ask(session, OPEN))
    command = (await running.poll(session))["command"]
    status, _, code = await running.receipt(session, command["id"], receipt)
    assert status == 400 and code == vocab.BAD_RECEIPT
    status, answer, code = await asyncio.wait_for(task, 3)
    assert status == 502 and code == vocab.RECEIPT_INVALID and "n'annonce ni succès ni échec" in answer["error"]["message"]


# ------------------------------------------------------------------ demandes refusées

@pytest.mark.parametrize("body", [
    None, [], {}, {"action": "toggle"}, {"action": "open"}, {**OPEN, "presentation_id": "pst_x"},
    {**OPEN, "variant_id": "psv_x"}, {**OPEN, "fullscreen": "yes"}, {**OPEN, "arm_s": 1}, {**OPEN, "arm_s": True},
    {**OPEN, "arm_s": 9999}, {**OPEN, "title": "ignored?"}, {**OPEN, "display": "other"},
])
async def test_a_bad_request_is_refused_before_any_page_is_asked(running, session, body):
    status, answer, code = await running.ask(session, body)
    assert status == 400 and code == vocab.BAD_REQUEST and answer["error"]["code"] == vocab.BAD_REQUEST
    assert running.control.studio_explorer.broker.expected("x" * 32) is None


async def test_the_request_and_receipt_sizes_are_bounded(running, session):
    status, _, code = await running.ask(session, {**OPEN, "variant_id": None, "pad": "x" * 2000})
    assert status == 413 and code == vocab.BAD_REQUEST
    async with session.post(f"{running.base}/state", data=b"{" + b" " * 2000 + b"}", headers=running.token()) as response:
        assert response.status == 413


@pytest.mark.parametrize("body", [
    {}, {"open": "yes"}, {"open": True}, {"open": True, "mode": "x"}, {"open": False, "variant_number": 0},
    {"open": False, "variant_number": True}, {"open": False, "title": "a title must never travel"},
    {"open": False, "presentation_id": "nope"}, {"open": False, "fullscreen": "perhaps"},
])
async def test_a_bad_state_report_is_refused_and_changes_nothing(running, session, body):
    before = await running.state(session)
    status, _, code = await running.report(session, body)
    assert status == 400 and code == vocab.BAD_RECEIPT
    assert await running.state(session) == before


# ------------------------------------------------------------------ miroir daté

def test_a_silent_page_makes_the_mirror_unknown_not_open():
    now = [100.0]
    broker = ExplorerCommandBroker(clock=lambda: now[0], silence_s=60)
    broker.report({"open": True, "mode": "windowed", "fullscreen": "unsupported", "presentation_id": PID, "variant_id": VID,
                   "variant_number": 2})
    assert broker.snapshot()["state"] == "open"
    now[0] += 59
    assert broker.snapshot()["state"] == "open"
    now[0] += 5
    snap = broker.snapshot()
    assert snap["state"] == "unknown" and snap["mode"] is None and "inconnu" in snap["explanation"]
    broker.mark_visibility(PAGE, True)      # a visible page polling again proves it alive
    assert broker.snapshot()["state"] == "open"
    broker.report({"open": False, "mode": None, "fullscreen": "exited", "presentation_id": None, "variant_id": None,
                   "variant_number": None})
    now[0] += 500
    assert broker.snapshot()["state"] == "closed", "a closed explorer does not become unknown"


async def test_closing_the_control_center_releases_a_waiting_agent_with_its_cause(running, session):
    task = asyncio.create_task(running.ask(session, OPEN))
    await asyncio.sleep(0.1)
    running.control.studio_explorer.close()
    status, answer, code = await asyncio.wait_for(task, 3)
    assert status == 503 and code == vocab.COMMAND_CANCELLED


# ------------------------------------------------------------------ vie privée et garde

async def test_no_title_or_reason_reaches_the_journal(running, session):
    task = asyncio.create_task(running.ask(session, {**OPEN, "variant_id": VID}))
    command = (await running.poll(session))["command"]
    await running.receipt(session, command["id"], {"state": "opened", "mode": "windowed", "fullscreen": "refused",
                                                   "reason": "SECRET-TITLE-IN-A-REASON"})
    await task
    await running.report(session, {"open": True, "mode": "windowed", "fullscreen": "refused", "presentation_id": PID,
                                   "variant_id": VID, "variant_number": 1})
    text = " ".join(str(line) for line in lines(running.control))
    assert "SECRET-TITLE" not in text and PID not in text, "ids of presentations and titles stay out of the journal"
    assert command["id"] not in text, "only the short id of a command is journalled"


async def test_a_prefab_frame_or_a_foreign_site_can_neither_dictate_consume_nor_read(running, session):
    assert EXPLORER_ROUTE.startswith(tuple(READ_GUARDED_ROUTES))
    for headers in ({"Origin": "null"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        status, _, _ = await running.ask(session, OPEN, headers=headers)
        assert status == 403, headers
        async with session.get(f"{running.base}/state", headers=headers) as response:
            assert response.status == 403
        async with session.get(f"{running.base}/commands?wait_s=0", headers=headers) as response:
            assert response.status == 403


async def test_poll_parameters_are_validated(running, session):
    for query in ("wait_s=abc", "wait_s=999", "wait_s=1&page=x", "visible=2", "bogus=1"):
        async with session.get(f"{running.base}/commands?{query}") as response:
            assert response.status == 400, query
            assert response.headers.get(SETTINGS_ERROR_CODE_HEADER) == vocab.BAD_REQUEST


def test_the_page_markers_are_registered_in_the_served_html():
    assert STUDIO_EXPLORER_CORE_SCRIPT_MARKER.startswith("/*__") and STUDIO_EXPLORER_SCRIPT_MARKER.startswith("/*__")
    from pathlib import Path
    html = (Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html").read_text(encoding="utf-8")
    markers = (STUDIO_EXPLORER_CORE_SCRIPT_MARKER, STUDIO_EXPLORER_WIDGETS_SCRIPT_MARKER, STUDIO_EXPLORER_SCRIPT_MARKER)
    assert [html.count(marker) for marker in markers] == [1, 1, 1]
    assert [html.index(marker) for marker in markers] == sorted(html.index(marker) for marker in markers), "pure functions, then widgets, then the controller"


# ------------------------------------------------------------------ jeton de page, accusé précoce, échéance réglable

async def test_a_receipt_or_a_state_report_without_the_page_token_is_refused_and_changes_nothing(running, session):
    task = asyncio.create_task(running.ask(session, OPEN))
    command = (await running.poll(session))["command"]
    ok = {"state": "opened", "mode": "windowed", "fullscreen": "unsupported"}
    for headers in ({}, {vocab.PAGE_TOKEN_HEADER: "nope"}, {vocab.PAGE_TOKEN_HEADER: ""}):
        status, answer, code = await running.receipt(session, command["id"], ok, headers=headers)
        assert status == 403 and code == vocab.BAD_PAGE_TOKEN and answer["error"]["code"] == vocab.BAD_PAGE_TOKEN, headers
        status, _, code = await running.report(session, {"open": True, "mode": "fullscreen", "fullscreen": "entered"}, headers=headers)
        assert status == 403 and code == vocab.BAD_PAGE_TOKEN
    assert (await running.state(session))["state"] == "closed", "a local process without the token cannot make the mirror say open or fullscreen"
    assert (await running.receipt(session, command["id"], ok))[0] == 200
    assert (await task)[0] == 200
    assert any(line["kind"] == "explorer.write_refused" for line in lines(running.control))


async def test_the_served_page_carries_the_token_the_broker_requires(running, session):
    async with session.get(running.base.replace(EXPLORER_ROUTE, "") + "/") as response:
        html = await response.text()
    token = running.control.studio_explorer.broker.page_token
    assert "__JARVIS_EXPLORER_PAGE_TOKEN__" not in html, "the placeholder is replaced when the page is served"
    assert token in html and html.count(token) == 1, "handed out with the page, once"


async def test_an_early_accepted_receipt_pushes_the_final_deadline_out_to_the_requested_work_time(running, session):
    broker = running.control.studio_explorer.broker
    broker.deadline_s = 0.3                     # the page must take the command within 0.3 s ...
    task = asyncio.create_task(running.ask(session, {**OPEN, "deadline_s": 5}))
    command = (await running.poll(session))["command"]
    status, answer, _ = await running.receipt(session, command["id"], {"state": "accepted"})
    assert status == 200 and answer.get("accepted") is True
    await asyncio.sleep(0.8)                    # ... and then has the full work time: the command is still pending after the delivery deadline
    assert not task.done()
    assert (await running.receipt(session, command["id"], {"state": "opened", "mode": "windowed", "fullscreen": "unsupported"}))[0] == 200
    status, final, _ = await task
    assert status == 200 and final["state"] == "opened"
    assert any(line["kind"] == "explorer.command_accepted" for line in lines(running.control))


async def test_without_the_early_ack_the_short_delivery_deadline_still_applies_and_the_work_deadline_is_bounded(running, session):
    broker = running.control.studio_explorer.broker
    broker.deadline_s = 0.3
    task = asyncio.create_task(running.ask(session, {**OPEN, "deadline_s": 5}))
    assert (await running.poll(session))["command"] is not None
    status, _, code = await task
    assert status == 504 and code == vocab.COMMAND_EXPIRED
    for bad in (3, 11, True, "5"):
        status, _, code = await running.ask(session, {**OPEN, "deadline_s": bad})
        assert status == 400 and code == vocab.BAD_REQUEST, bad
    assert vocab.parse_request({**OPEN, "deadline_s": 10}).deadline_s == 10 and vocab.parse_request(OPEN).deadline_s == vocab.WORK_DEADLINE_DEFAULT_S
    status, _, code = await running.receipt(session, "x" * 32, {"state": "accepted"})
    assert status == 404 and code == vocab.UNKNOWN_COMMAND_ID, "an accepted ack for no command in flight is refused"

