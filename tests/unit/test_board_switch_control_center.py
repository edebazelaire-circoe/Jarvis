"""Bascule de Board de bout en bout : Control Center <-> Core réels (handoff board-session, Slice 04b).

Core réel (`JarvisCoreApplication` + `LocalProtocolServer`) dont le backend
cerveau est le vrai `ControlCenterBrainBackend` pointé sur un Control Center
réel servi en HTTP ; seuls les agents CLI sont doublés (`StubAgent`). C'est la
seule façon de prouver que `POST /api/boards/switch` traverse Core, revient
au pool par `POST /api/agent/bindings/activate`, et que les deux côtés
finissent d'accord.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID, BrainLifecycle
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.core_sessions import CoreSessionTransport
from tests.unit.test_board_brains_control_center import (
    TOKEN, JsonRequest, free_port, make_control, serve, trace,
)


class Stack:
    """Un Control Center servi et un Core servi, chacun pointé sur l'autre."""

    def __init__(self, tmp_path) -> None:
        self.tmp_path = tmp_path
        self.core_port = free_port()
        token_file = tmp_path / "token"
        token_file.write_text(TOKEN, encoding="utf-8")
        self.transport = CoreSessionTransport(host="127.0.0.1", port=self.core_port, token_file=token_file)
        self.control = make_control(tmp_path, sessions=self.transport)
        self.runner = None
        self.base = ""
        self.core: JarvisCoreApplication | None = None
        self.server: LocalProtocolServer | None = None
        self.backend: ControlCenterBrainBackend | None = None

    async def serve_control(self) -> None:
        self.runner, self.base = await serve(self.control)

    async def start_core(self, *, with_host: bool = True) -> JarvisCoreApplication:
        self.backend = ControlCenterBrainBackend(base_url=self.base) if with_host else None
        self.core = JarvisCoreApplication(data_root=self.tmp_path / "core", brain_backend=self.backend)
        await self.core.start()
        if self.core._host_align_task is not None:
            await asyncio.wait_for(self.core._host_align_task, timeout=10)
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.core_port, token=TOKEN)
        await self.server.start()
        return self.core

    async def stop_core(self) -> None:
        if self.server is not None:
            await self.server.stop()
        if self.core is not None:
            await self.core.stop()
        if self.backend is not None:
            await self.backend.close()
        await self.transport.close()
        self.core = self.server = self.backend = None

    async def close(self) -> None:
        await self.stop_core()
        await self.control.board_routes.close()
        await self.control.board_brains.aclose()
        if self.runner is not None:
            await self.runner.cleanup()

    async def call(self, method: str, path: str, **kwargs):
        async with aiohttp.ClientSession() as http:
            async with http.request(method, self.base + path, **kwargs) as response:
                return response.status, await response.json(content_type=None)


@pytest.fixture
async def stack(tmp_path):
    stack = Stack(tmp_path)
    await stack.serve_control()
    try:
        yield stack
    finally:
        await stack.close()


# ------------------------------------------------------------------ proxy


async def test_the_board_and_session_routes_relay_core_with_its_codes(stack):
    await stack.start_core(with_host=False)
    status, listed = await stack.call("GET", "/api/boards")
    assert status == 200 and listed["active_board_id"] == DEFAULT_BOARD_ID
    status, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    assert status == 201 and created["board"]["title"] == "Projet B"
    board_id = created["board"]["board_id"]
    status, edited = await stack.call("PATCH", f"/api/boards/{board_id}", json={"context_summary": "Lot 2"})
    assert status == 200 and edited["board"]["context_summary"] == "Lot 2"
    assert (await stack.call("GET", f"/api/boards/{board_id}"))[1]["board"]["board_id"] == board_id
    assert (await stack.call("GET", "/api/boards/active"))[1]["board"]["board_id"] == DEFAULT_BOARD_ID
    status, refused = await stack.call("GET", "/api/boards/board_" + "0" * 32)
    assert status == 404 and refused["error"]["code"] == "board_not_found"
    status, refused = await stack.call("POST", "/api/boards", json={"nope": 1})
    assert status == 400 and refused["error"]["code"] == "invalid_board"
    status, refused = await stack.call("POST", "/api/boards/default/archive")
    assert status == 409 and refused["error"]["code"] == "board_is_active"
    status, current = await stack.call("GET", "/api/sessions/current")
    assert status == 200 and current["binding"]["board_id"] == DEFAULT_BOARD_ID
    status, history = await stack.call("GET", "/api/sessions", params={"limit": "5"})
    assert status == 200 and len(history["sessions"]) == 1
    status, switched = await stack.call("POST", "/api/boards/switch", json={"board_id": board_id})
    assert status == 200 and switched["changed"] and switched["board"]["board_id"] == board_id
    status, fresh = await stack.call("POST", "/api/sessions/new", json={})
    assert status == 201 and fresh["session"]["active_board_id"] == board_id
    assert trace(stack.tmp_path, "board.request.relayed")[-1]["data"]["action"] == "new_session"


async def test_the_proxy_says_core_is_unreachable(stack):
    status, answer = await stack.call("GET", "/api/boards")
    assert status == 503 and answer["error"]["code"] == "core_unreachable"
    assert trace(stack.tmp_path, "board.request.core_unreachable")[-1]["level"] == "warning"


async def test_the_proxy_refuses_an_unknown_origin(stack):
    await stack.start_core(with_host=False)
    status, answer = await stack.call("POST", "/api/boards/switch", json={"board_id": "default", "origin": "x"})
    assert status == 400 and answer["error"]["code"] == "invalid_request"


# ------------------------------------------------------------------ bascule réelle


async def test_a_switch_moves_the_control_center_foreground_and_keeps_a_busy_brain(stack):
    core = await stack.start_core()
    first = await core.sessions.current()
    agent_a = stack.control.agent
    assert stack.control.board_brains.foreground.key == first.binding.conversation_id, "aligned at Core start"
    agent_a.start_subagent("task-long")
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})

    status, switched = await stack.call("POST", "/api/boards/switch", json={"board_id": created["board"]["board_id"]})

    assert status == 200
    target = switched["binding"]
    assert stack.control.board_brains.foreground.key == target["conversation_id"]
    assert stack.control.agent is not agent_a and agent_a.running, "A keeps its sub-agent"
    assert target["agent_cli"] == "claude" and target["agent_session_id"] == stack.control.agent.session_id
    old = next(b for b in await core.boards._repo.list_bindings(first.session.jarvis_session_id)
               if b.board_id == DEFAULT_BOARD_ID)
    assert old.lifecycle is BrainLifecycle.BACKGROUND_RUNNING
    assert core.speech_authority.conversation_id == target["conversation_id"]

    status, back = await stack.call("POST", "/api/boards/switch", json={"board_id": DEFAULT_BOARD_ID})
    assert status == 200 and back["binding"]["conversation_id"] == first.binding.conversation_id
    assert stack.control.agent is agent_a, "A/B/A: the same live CLI"


async def test_a_new_session_from_the_ui_gets_a_fresh_cli_through_core(stack):
    core = await stack.start_core()
    old_agent = stack.control.agent
    status, fresh = await stack.call("POST", "/api/sessions/new", json={})
    assert status == 201
    assert stack.control.board_brains.foreground.key == fresh["binding"]["conversation_id"]
    assert stack.control.agent is not old_agent and stack.control.agent.starts == [None]
    old_entry = stack.control.board_brains.entry_of(old_agent)
    assert old_entry is None or old_entry.closed
    assert core.speech_authority.conversation_id == fresh["binding"]["conversation_id"]


# ------------------------------------------------------------------ Core redémarré


async def test_a_core_restart_realigns_the_control_center_foreground(stack):
    core = await stack.start_core()
    before = await core.sessions.current()
    old_agent = stack.control.agent
    assert stack.control.board_brains.foreground.key == before.binding.conversation_id
    await stack.stop_core()

    core = await stack.start_core()                         # Core redémarré = Session neuve
    after = await core.sessions.current()

    assert after.binding.conversation_id != before.binding.conversation_id
    assert stack.control.board_brains.foreground.key == after.binding.conversation_id
    assert stack.control.agent is not old_agent, "the new Session has a fresh CLI"
    assert after.binding.agent_cli == "claude", "no binding left pending"
    old_entry = stack.control.board_brains.entry_of(old_agent)
    assert old_entry is None or old_entry.closed, "the closed Session's brain is never foreground again"


async def test_the_control_center_realigns_on_the_first_turn_when_core_could_not(stack):
    core = await stack.start_core(with_host=False)
    await stack.control._adopt_core_session()
    old = await core.sessions.current()
    assert stack.control.board_brains.foreground.key == old.binding.conversation_id
    await stack.stop_core()
    core = await stack.start_core(with_host=False)           # redémarré sans pouvoir nous joindre
    new = await core.sessions.current()

    answer = await stack.control.agent_ask(JsonRequest({
        "text": "bonjour", "conversation": {"conversation_id": new.binding.conversation_id}}))

    assert answer.status == 200
    assert stack.control.board_brains.foreground.key == new.binding.conversation_id
    assert trace(stack.tmp_path, "board_brain.realigned")[-1]["data"]["previous_conversation_id"] == \
        old.binding.conversation_id
    for _ in range(100):
        if (await core.sessions.current()).binding.agent_cli == "claude":
            break
        await asyncio.sleep(0.02)
    assert (await core.sessions.current()).binding.agent_cli == "claude"


# ------------------------------------------------------------------ demande du cerveau


async def test_a_switch_asked_by_the_brain_during_its_turn_is_deferred_until_the_turn_ends(stack):
    core = await stack.start_core(with_host=False)
    stack.control.board_routes._grace_s = 0.05
    release = asyncio.Event()
    agent = stack.control.agent

    async def slow_ask(text: str, **_) -> dict:
        await release.wait()
        return {"ok": True, "text": "Je passe au Board B."}

    agent.ask = slow_ask
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    turn = asyncio.create_task(stack.control.agent_ask(JsonRequest({"text": "passe sur B"})))
    await asyncio.sleep(0.05)

    status, answer = await stack.call("POST", "/api/boards/switch",
                                      json={"board_id": created["board"]["board_id"], "origin": "brain"})
    assert status == 202 and answer == {"ok": True, "status": "scheduled", "action": "switch"}
    assert (await core.sessions.current()).session.active_board_id == DEFAULT_BOARD_ID, "not under the turn"

    release.set()
    await turn
    for _ in range(100):
        if (await core.sessions.current()).session.active_board_id != DEFAULT_BOARD_ID:
            break
        await asyncio.sleep(0.02)
    assert (await core.sessions.current()).session.active_board_id == created["board"]["board_id"]
    assert trace(stack.tmp_path, "board.request.deferred_applied")[-1]["data"]["action"] == "switch"


async def test_a_brain_request_without_a_turn_in_flight_is_applied_at_once(stack):
    core = await stack.start_core(with_host=False)
    status, fresh = await stack.call("POST", "/api/sessions/new", json={"origin": "brain"})
    assert status == 201
    assert (await core.sessions.current()).session.jarvis_session_id == fresh["session"]["jarvis_session_id"]


# ------------------------------------------------------------------ hôte lent (QA Slice 04b, S2)
#
# Le délai par défaut de `LocalCoreClient` (10 s) est réduit à 0,3 s et l'hôte
# (ce Control Center, appelé par Core) met 0,8 s à activer : la même course
# qu'une activation de CLI de 10 à 60 s, à l'échelle d'un test.


def _short_default_timeout(monkeypatch) -> None:
    from jarvis.protocol.client import LocalCoreClient

    async def short_http(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=0.3))
        return self._session

    monkeypatch.setattr(LocalCoreClient, "_http", short_http)


def _slow_host(stack, delay_s: float) -> None:
    original = stack.backend.post_activation

    async def slow(payload):
        await asyncio.sleep(delay_s)
        return await original(payload)

    stack.backend.post_activation = slow


async def test_a_switch_waits_for_a_slow_host_instead_of_answering_503(stack, monkeypatch):
    _short_default_timeout(monkeypatch)                      # avant toute session HTTP du relais
    core = await stack.start_core()
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    _slow_host(stack, 0.8)

    status, switched = await stack.call("POST", "/api/boards/switch", json={"board_id": created["board"]["board_id"]})

    assert status == 200, switched
    assert (await core.sessions.current()).session.active_board_id == created["board"]["board_id"]


async def test_a_restart_in_a_new_session_waits_for_a_slow_host(stack, monkeypatch):
    _short_default_timeout(monkeypatch)
    core = await stack.start_core()
    before = await core.sessions.current()
    _slow_host(stack, 0.8)
    from tests.unit.test_scene_settings_ui import _RestartRequest

    response = await stack.control.agent_restart(_RestartRequest(b'{"new_conversation": true}'))

    assert response.status == 200
    assert (await core.sessions.current()).session.jarvis_session_id != before.session.jarvis_session_id


async def test_a_transition_past_its_deadline_says_the_outcome_is_unknown(stack, monkeypatch):
    from jarvis.runtime import core_sessions

    core = await stack.start_core()
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    monkeypatch.setattr(core_sessions, "CORE_TRANSITION_TIMEOUT_S", 0.3)
    _slow_host(stack, 1.0)

    status, answer = await stack.call("POST", "/api/boards/switch", json={"board_id": created["board"]["board_id"]})

    assert status == 504 and answer["error"]["code"] == "core_transition_timeout"
    assert "unknown" in answer["error"]["message"]
    assert trace(stack.tmp_path, "board.request.core_timeout")[-1]["level"] == "warning"
    for _ in range(200):                                     # Core valide ensuite : la réponse ne mentait pas
        if (await core.sessions.current()).session.active_board_id == created["board"]["board_id"]:
            break
        await asyncio.sleep(0.02)
    assert (await core.sessions.current()).session.active_board_id == created["board"]["board_id"]


def test_the_transition_timeout_outlasts_the_host_activation_and_its_rollback():
    from jarvis.adapters.control_center_brain import ControlCenterBoardHost
    from jarvis.runtime.core_sessions import CORE_TRANSITION_TIMEOUT_S

    assert CORE_TRANSITION_TIMEOUT_S > 2 * ControlCenterBoardHost.TIMEOUT_S


async def test_a_restart_past_its_deadline_never_says_nothing_changed(stack, monkeypatch):
    from aiohttp import web

    from jarvis.runtime import core_sessions
    from tests.unit.test_scene_settings_ui import _RestartRequest

    core = await stack.start_core()
    before = await core.sessions.current()
    monkeypatch.setattr(core_sessions, "CORE_TRANSITION_TIMEOUT_S", 0.3)
    _slow_host(stack, 1.0)

    with pytest.raises(web.HTTPServiceUnavailable) as refused:
        await stack.control.agent_restart(_RestartRequest(b'{"new_conversation": true}'))

    assert "core_transition_timeout" in refused.value.text and "rien n'a changé" not in refused.value.text
    assert trace(stack.tmp_path, "agent.restart.session_timeout")[-1]["level"] == "error"
    assert trace(stack.tmp_path, "agent.restart.session_failed") == []
    for _ in range(200):
        if (await core.sessions.current()).session.jarvis_session_id != before.session.jarvis_session_id:
            break
        await asyncio.sleep(0.02)
    assert (await core.sessions.current()).session.jarvis_session_id != before.session.jarvis_session_id


# ------------------------------------------------------------------ grâce du report (QA Slice 04b, D2)


async def test_a_deferred_brain_request_waits_the_turn_then_the_1_5_s_grace_before_relaying(tmp_path, monkeypatch):
    """Le mutant D2 (grâce retirée) survivait : la grâce laisse Core publier la réponse du tour avant la bascule."""

    from jarvis.runtime import board_routes
    from jarvis.runtime.journal import RuntimeJournal

    assert board_routes.BRAIN_DEFER_GRACE_S == 1.5
    steps: list = []

    class Transport:
        async def forward(self, method, path, *, params=None, body=None):  # noqa: ANN001, ANN202
            steps.append(("forward", path))
            return 200, {"changed": True}

    async def idle() -> None:
        steps.append("turn_idle")

    async def fake_sleep(seconds: float) -> None:
        steps.append(("sleep", seconds))

    monkeypatch.setattr(board_routes.asyncio, "sleep", fake_sleep)
    routes = board_routes.BoardSessionRoutes(transport=Transport(), journal=RuntimeJournal(tmp_path),
                                             ask_in_flight=lambda: True, wait_asks_idle=idle)

    await routes._run_deferred("switch", "/v1/boards/switch", b'{"board_id": "b"}', {"board_id": "b"})

    assert steps == ["turn_idle", ("sleep", 1.5), ("forward", "/v1/boards/switch")]
    assert trace(tmp_path, "board.request.deferred_applied")[-1]["data"]["action"] == "switch"


def test_the_control_center_keeps_the_default_deferral_grace(tmp_path):
    from jarvis.runtime.board_routes import BRAIN_DEFER_GRACE_S

    control = make_control(tmp_path)
    assert control.board_routes._grace_s == BRAIN_DEFER_GRACE_S == 1.5
