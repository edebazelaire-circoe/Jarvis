"""Le pool des cerveaux de Board dans le Control Center (handoff board-session, Slice 04a).

Agents doublés (`StubAgent`, injectés par `agent_factory`) ; Core **réel**
(`JarvisCoreApplication` + `LocalProtocolServer`) quand la route touche aux
Sessions : c'est la seule façon de prouver qu'une nouvelle Session et le rapport
du CLI arrivent vraiment dans le magasin de Core.
"""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
import uuid

import aiohttp
import pytest
from aiohttp import web

from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.workspace_board import (
    BoardConversationBinding, BrainLifecycle, DEFAULT_BOARD_ID, new_board_id, new_session_id,
)
from jarvis.protocol.client import CoreProtocolError
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import control_center as control_center_module
from jarvis.runtime import interaction_mode_settings as mode_settings
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.interaction_mode_view import CoreInteractionModeView
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

TOKEN = "t" * 48
T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ doublures


class StubAgent:
    """Surface de `ClaudeLocalAgent` dont le Control Center se sert, sans processus."""

    count = 0

    def __init__(self, cli: str, root: Path) -> None:
        StubAgent.count += 1
        self.name = f"{cli}-{StubAgent.count}"
        self.cli = cli
        self.command = cli
        self.model = ""
        self.permission_mode = "default"
        self.cwd = root
        self.journal = RuntimeJournal(root)
        self.subtasks = AgentTaskTracker(provider=cli, journal=self.journal)
        self.session_id: str | None = None
        self.running = False
        self.starts: list[str | None] = []
        self.restarts: list[bool] = []
        self.stops = 0
        self.asked: list[str] = []
        self.speaks_notices = True
        self.notice_epoch = uuid.uuid4().hex[:12]
        self.notices: list[dict] = []

    @property
    def state(self) -> str:
        return "running" if self.running else "stopped"

    @property
    def last_notice_seq(self) -> int:
        return len(self.notices)

    def notice(self, text: str) -> None:
        self.notices.append({"seq": len(self.notices) + 1, "text": text})

    async def wait_notices(self, after: int, *, timeout_s: float = 25.0) -> list[dict]:
        del timeout_s
        return [dict(n) for n in self.notices if n["seq"] > after]

    async def start(self, *, resume: bool = True) -> dict:
        self.starts.append(self.session_id if resume else None)
        self.running = True
        if self.session_id is None:
            self.session_id = f"sess-{self.name}"
        return self.snapshot()

    async def stop(self) -> dict:
        self.stops += 1
        self.running = False
        self.subtasks.process_stopped()
        return self.snapshot()

    async def restart(self, *, resume: bool = True) -> dict:
        self.restarts.append(resume)
        await self.stop()
        if not resume:
            self.session_id = None
        return await self.start(resume=resume)

    async def ask(self, text: str, *, timeout_s: float = 180.0) -> dict:
        del timeout_s
        self.asked.append(text)
        return {"ok": True, "text": f"réponse de {self.name}"}

    def snapshot(self) -> dict:
        return {"name": self.name, "state": self.state, "session_id": self.session_id}

    def start_subagent(self, task_id: str) -> None:
        self.subtasks.observe_claude({"type": "system", "subtype": "task_started", "task_id": task_id,
                                      "description": "Refactor", "is_backgrounded": True,
                                      "task_type": "local_agent", "subagent_type": "general-purpose"},
                                     now_ms=self.subtasks.now_ms())


class JsonRequest:
    def __init__(self, payload: object, query: dict | None = None) -> None:
        self._payload = payload
        self.query = query or {}

    async def json(self) -> object:
        return self._payload


def binding(conversation_id: str, *, session: str | None = None, board_id: str | None = None) -> BoardConversationBinding:
    return BoardConversationBinding(
        jarvis_session_id=session or new_session_id(), board_id=board_id or new_board_id(),
        conversation_id=conversation_id, agent_cli="pending", created_at=T0, last_active_at=T0,
        lifecycle=BrainLifecycle.FOREGROUND,
    )


def make_control(tmp_path: Path, **kwargs) -> ControlCenter:
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path,
                         agent_factory=lambda cli: StubAgent(cli, tmp_path), **kwargs)


def trace(tmp_path: Path, kind: str) -> list[dict]:
    return [item for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=2000) if item["kind"] == kind]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def core(tmp_path):
    port = free_port()
    app = JarvisCoreApplication(data_root=tmp_path / "core")
    await app.start()
    server = LocalProtocolServer(app, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN, encoding="utf-8")
    transport = CoreSessionTransport(host="127.0.0.1", port=port, token_file=token_file)
    try:
        yield app, transport
    finally:
        await transport.close()
        await server.stop()
        await app.stop()


async def serve(control: ControlCenter):
    runner = web.AppRunner(control._app)
    await runner.setup()
    port = free_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    return runner, f"http://127.0.0.1:{port}"


# ------------------------------------------------------------------ routage des tours


async def test_ask_routes_by_conversation_and_refuses_a_demoted_brain_with_409(tmp_path):
    control = make_control(tmp_path)
    board_a, board_b = binding("conv-a"), binding("conv-b")
    first = await control.board_brains.activate(board_a)
    first.agent.start_subagent("task-1")  # garde A vivant en arrière-plan
    second = await control.board_brains.activate(board_b)
    assert control.agent is second.agent

    refused = await control.agent_ask(JsonRequest({"text": "bonjour", "conversation": {"conversation_id": "conv-a"}}))
    assert refused.status == 409
    body = json.loads(refused.text)
    assert body["code"] == "brain_not_foreground" and body["ok"] is False
    assert first.agent.asked == []
    assert trace(tmp_path, "board_brain.ask_refused")[-1]["data"]["board_id"] == board_a.board_id

    for conversation in ({"conversation_id": "conv-b"}, {"conversation_id": "inconnue"}, None):
        payload = {"text": "bonjour", **({"conversation": conversation} if conversation else {})}
        answered = json.loads((await control.agent_ask(JsonRequest(payload))).text)
        assert answered["text"] == f"réponse de {second.agent.name}"
    assert len(second.agent.asked) == 3


# ------------------------------------------------------------------ relais


async def test_notices_produced_in_background_are_not_replayed_after_promotion(tmp_path):
    control = make_control(tmp_path)
    first = await control.board_brains.activate(binding("conv-a"))
    agent_a = first.agent
    agent_a.start_subagent("task-1")
    second = await control.board_brains.activate(binding("conv-b"))
    # Core lit le foreground B et retient son époque.
    seen = json.loads((await control.agent_notices(JsonRequest(None, {"after": "0", "wait": "0"}))).text)
    assert seen["epoch"] == second.agent.notice_epoch
    agent_a.notice("A a fini, mais A n'avait pas la parole.")
    agent_a.notice("Encore A.")

    await control.board_brains.activate(binding("conv-a", session=first.jarvis_session_id,
                                                board_id=first.board_id))

    # L'époque change (A n'est pas B) : sans filigrane, tout serait rejoué depuis 0.
    replay = json.loads((await control.agent_notices(
        JsonRequest(None, {"after": str(seen["last_seq"]), "wait": "0", "epoch": seen["epoch"]}))).text)
    assert replay["epoch"] == agent_a.notice_epoch and replay["notices"] == []
    agent_a.notice("A, de nouveau au premier plan.")
    fresh = json.loads((await control.agent_notices(
        JsonRequest(None, {"after": str(replay["last_seq"]), "wait": "0", "epoch": replay["epoch"]}))).text)
    assert [n["text"] for n in fresh["notices"]] == ["A, de nouveau au premier plan."]


# ------------------------------------------------------------------ route d'activation


async def test_the_internal_activate_route_returns_the_agent_session_id(tmp_path):
    control = make_control(tmp_path)
    runner, base = await serve(control)
    board = binding("conv-a")
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(base + "/api/agent/bindings/activate", json=board.to_payload()) as response:
                assert response.status == 200
                answer = await response.json()
            async with http.post(base + "/api/agent/bindings/activate", json={"board_id": "x"}) as response:
                assert response.status == 400 and (await response.json())["code"] == "invalid_binding"
            # Une page étrangère ne peut pas activer un cerveau.
            async with http.post(base + "/api/agent/bindings/activate", json=board.to_payload(),
                                 headers={"Origin": "http://evil.example"}) as response:
                assert response.status == 403
            async with http.post(base + "/api/agent/bindings/activate", json=board.to_payload(),
                                 headers={"Sec-Fetch-Site": "cross-site"}) as response:
                assert response.status == 403
    finally:
        await runner.cleanup()
    assert answer["ok"] is True and answer["lifecycle"] == "foreground"
    assert answer["agent_cli"] == "claude" and answer["agent_session_id"] == control.agent.session_id
    assert answer["board_id"] == board.board_id and control.board_brains.foreground.key == "conv-a"


async def test_an_activation_whose_cli_cannot_start_is_a_502_and_changes_nothing(tmp_path):
    control = make_control(tmp_path)
    first = await control.board_brains.activate(binding("conv-a"))

    class Broken(StubAgent):
        async def start(self, *, resume: bool = True) -> dict:
            raise RuntimeError("Claude CLI not found")

    control.board_brains._factory = lambda cli: Broken(cli, tmp_path)

    class Body:
        def __init__(self, raw: bytes) -> None:
            self.raw, self.content_length, self.can_read_body, self.content = raw, len(raw), True, self

        async def iter_chunked(self, size: int):  # noqa: ARG002
            yield self.raw

    response = await control.agent_binding_activate(Body(json.dumps(binding("conv-b").to_payload()).encode()))
    assert response.status == 502 and json.loads(response.text)["code"] == "board_activation_failed"
    assert control.board_brains.foreground is first
    assert trace(tmp_path, "board_brain.activation_failed")[-1]["level"] == "error"


# ------------------------------------------------------------------ Core réel : adoption, nouvelle Session


async def test_startup_adopts_the_running_agent_as_the_core_foreground_binding(tmp_path, core):
    app, sessions = core
    control = make_control(tmp_path, sessions=sessions)
    agent = control.agent
    await agent.start()

    await control._adopt_core_session()

    current = await app.sessions.current()
    assert control.board_brains.foreground.key == current.binding.conversation_id
    assert control.agent is agent and agent.stops == 0, "adoption never restarts the CLI"
    assert current.binding.agent_cli == "claude" and current.binding.agent_session_id == agent.session_id
    assert agent.journal.context == {"board_id": DEFAULT_BOARD_ID,
                                     "jarvis_session_id": current.session.jarvis_session_id}
    await control.board_brains.aclose()


async def test_restart_new_conversation_opens_a_core_session_and_demotes_the_old_brain(tmp_path, core):
    app, sessions = core
    control = make_control(tmp_path, sessions=sessions)
    old_agent = control.agent
    await old_agent.start()
    await control._adopt_core_session()
    before = await app.sessions.current()
    old_agent.start_subagent("task-long")

    from tests.unit.test_scene_settings_ui import _RestartRequest
    response = await control.agent_restart(_RestartRequest(b'{"new_conversation": true}'))
    payload = json.loads(response.text)

    after = await app.sessions.current()
    assert after.session.jarvis_session_id != before.session.jarvis_session_id
    assert payload["board_brain"]["conversation_id"] == after.binding.conversation_id
    new_agent = control.agent
    assert new_agent is not old_agent and new_agent.starts == [None], "a fresh CLI, no --resume"
    assert old_agent.stops == 0 and old_agent.running, "the old brain's sub-agent keeps running"
    old_entry = control.board_brains.find(before.binding.conversation_id)
    assert old_entry.lifecycle is BrainLifecycle.BACKGROUND_RUNNING and old_entry.closed
    assert old_agent.restarts == [] and new_agent.restarts == []
    # Core connaît le CLI de la nouvelle liaison.
    assert after.binding.agent_cli == "claude" and after.binding.agent_session_id == new_agent.session_id
    await control.board_brains.aclose()


async def test_restart_new_conversation_keeps_the_historical_behaviour_without_core_sessions(tmp_path):
    class OldCore:
        async def new_session(self, **kwargs):  # noqa: ANN003
            raise CoreProtocolError(404, "http_error", "Not Found")

        async def close(self) -> None:
            return None

    control = make_control(tmp_path, sessions=OldCore())
    agent = control.agent
    await agent.start()
    from tests.unit.test_scene_settings_ui import _RestartRequest
    await control.agent_restart(_RestartRequest(b'{"new_conversation": true}'))
    assert agent.restarts == [False] and control.agent is agent
    assert trace(tmp_path, "agent.restart.session_unavailable")[-1]["data"]["code"] == "core_sessions_unsupported"


# ------------------------------------------------------------------ mode d'interaction : fin du rejeu


class BoardsCore:
    """`GET /v1/boards/active` d'un Core à Boards, origine du mode au choix."""

    def __init__(self, origin: str) -> None:
        self.origin = origin

    async def active_board(self) -> dict:
        return {"board": {"board_id": "default", "interaction_mode": "assistant",
                          "interaction_mode_origin": self.origin}, "active": True}

    async def close(self) -> None:
        return None


class ServiceReader:
    def __init__(self, service: InteractionModeService) -> None:
        self.service = service
        self.writes: list[tuple[str, str | None]] = []

    async def interaction_mode(self) -> dict:
        return self.service.snapshot()

    async def set_interaction_mode(self, mode: str, *, source: str | None = None) -> dict:
        self.writes.append((mode, source))
        state, disposition = await self.service.request(mode, source=source or "protocol")
        return {**self.service.snapshot(), "disposition": disposition.value, "revision": state.revision}

    async def close(self) -> None:
        return None


class Bus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, envelope) -> None:  # noqa: ANN001
        self.published.append(envelope)


async def _core_restart_replay(tmp_path, monkeypatch, origin: str):  # noqa: ANN202
    monkeypatch.setattr(control_center_module, "INTERACTION_MODE_REPLAY_BACKOFF_S", 0.0)
    bus = Bus()
    service = InteractionModeService(events=bus)
    reader = ServiceReader(service)
    control = make_control(tmp_path, sessions=BoardsCore(origin),
                           interaction_mode_view=CoreInteractionModeView(reader))
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})  # préférence globale ≠ Board (assistant)
    control._write_settings(settings)

    control._schedule_interaction_mode_replay("core_restart")
    await control._interaction_mode_replay
    return control, service, reader, bus


async def test_no_mode_flip_on_core_restart_when_the_active_board_owns_its_mode(tmp_path, monkeypatch):
    control, service, reader, bus = await _core_restart_replay(tmp_path, monkeypatch, "user")
    assert reader.writes == [] and bus.published == [], "no presentation -> assistant flip"
    assert service.mode is InteractionMode.ASSISTANT
    assert trace(tmp_path, "interaction.mode.replay_retired")[-1]["data"]["source"] == "core_restart"


async def test_the_legacy_mode_is_still_replayed_once_as_migration_input(tmp_path, monkeypatch):
    control, service, reader, _ = await _core_restart_replay(tmp_path, monkeypatch, "unset")
    assert reader.writes == [("presentation", "core_restart")]
    assert service.mode is InteractionMode.PRESENTATION


async def test_a_mode_chosen_with_board_core_is_not_written_to_the_global_preference(tmp_path):
    service = InteractionModeService(events=Bus())
    reader = ServiceReader(service)
    control = make_control(tmp_path, sessions=BoardsCore("user"), interaction_mode_view=CoreInteractionModeView(reader))

    response = await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))

    assert json.loads(response.text)["effective"]["mode"] == "presentation"
    assert reader.writes == [("presentation", "control_center")]
    assert "interaction_mode" not in control._settings(), "the Board keeps the mode, not the global setting"


async def test_core_backend_keeps_the_brain_not_foreground_code_of_a_real_control_center(tmp_path):
    """De bout en bout : le 409 du Control Center arrive dans Core avec son code, pas en panne HTTP."""

    from jarvis.adapters.control_center_brain import BRAIN_NOT_FOREGROUND, ControlCenterBrainBackend
    from jarvis.domain.v2 import BrainRunStatus, BrainTurnInput

    control = make_control(tmp_path)
    first = await control.board_brains.activate(binding("conv-a"))
    first.agent.start_subagent("task-1")
    await control.board_brains.activate(binding("conv-b"))
    runner, base = await serve(control)

    class Sink:
        def __init__(self) -> None:
            self.events: list = []

        async def emit(self, event) -> None:  # noqa: ANN001
            self.events.append(event)

    backend = ControlCenterBrainBackend(base_url=base, timeout_s=5)
    sink = Sink()
    try:
        result = await backend.run_turn(
            BrainTurnInput(conversation_id="conv-a", text="Bonjour.", correlation_id="corr-1"), None, sink)
    finally:
        await backend.close()
        await runner.cleanup()
    assert result.status is BrainRunStatus.FAILED and result.error == BRAIN_NOT_FOREGROUND
    assert first.agent.asked == []
