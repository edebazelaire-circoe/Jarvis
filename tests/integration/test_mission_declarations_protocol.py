"""Déclarations de sous-agents par la boucle locale (organic-agent-orchestration, Slice 05).

Chaîne réelle : hook → registre local → `AgentTaskTracker` → `DeclarationRelay` → `CoreMissionTransport` →
`POST /v1/missions/declarations` (jeton exigé) → `MissionHistoryService` (base temporaire de Core) ; puis la
lecture par `CoreMissionView` et le `role_id` porté par Work State. Aucune base réelle, aucun JARVIS vivant.
"""

from __future__ import annotations

import socket

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import routing_hook
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.declaration_relay import CoreMissionTransport, DeclarationRelay
from jarvis.runtime.mission_view import CoreMissionView
from jarvis.runtime.work_ingress import CoreWorkTransport, TrackerWorkObserver, WorkIngressForwarder

TOKEN = "m" * 48


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def stack(tmp_path):
    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    try:
        yield core, port, token_file
    finally:
        await server.stop()
        await core.stop()


async def test_a_declared_team_reaches_core_history_and_work_state(stack, tmp_path):
    core, port, token_file = stack
    runtime = tmp_path / "runtime"
    tracker = AgentTaskTracker(provider="claude")
    relay = DeclarationRelay(runtime_root=runtime, source="claude",
                             transport=CoreMissionTransport(host="127.0.0.1", port=port, token_file=token_file))
    ingress = WorkIngressForwarder(source="claude",
                                   transport=CoreWorkTransport(host="127.0.0.1", port=port, token_file=token_file))
    relay.attach(tracker)
    observer = TrackerWorkObserver(tracker, ingress.offer, role_of=relay.role_for)
    tracker.subscribe(observer.sync)
    relay.on_joined = observer.sync
    for tool_use_id, task_id, description, caller, parent_task, depth in (
        ("toolu_A", "taskA", "[code] [coder] Corriger le bug", None, None, 1),
        ("toolu_Q", "taskQ", "[general] [qa] Relire le correctif", "taskA", "taskA", 2),
    ):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id,
                 "tool_input": {"description": description, "prompt": "p", "subagent_type": "general-purpose"}}
        if caller:
            event["agent_id"] = caller
        routing_hook.run(event, runtime, spawn_guard=True)
        started = {"type": "system", "subtype": "task_started", "task_id": task_id, "tool_use_id": tool_use_id,
                   "description": description, "subagent_type": "general-purpose", "task_type": "local_agent",
                   "spawn_depth": depth}
        if parent_task:
            started["parent_task_id"] = parent_task
        tracker.observe_claude(started)
    try:
        assert await relay.flush() is True
        assert await ingress.flush() is True
        view = CoreMissionView(CoreMissionTransport(host="127.0.0.1", port=port, token_file=token_file))
        status, owner = await view.for_work("claude", "taskA")
        assert status == 200 and owner["role_id"] == "coder" and owner["mission_owner"] is True
        status, tree = await view.mission(owner["mission_id"])
        assert status == 200 and tree["missions"][0]["objective"] == "Corriger le bug"
        assert {(i["role_id"], i["mission_owner"]) for i in tree["instances"]} == {("coder", True), ("qa", False)}
        status, health = await view.health()
        assert status == 200 and health["store_id"] == core.work_state.store_id and health["state"] == "ok"
        roles = {item.external_id: item.role_id for item in core.work_state.current_snapshot().items}
        assert roles == {"taskA": "coder", "taskQ": "qa"}
        await view.close()
    finally:
        await relay.aclose()
        await ingress.aclose()


async def test_the_route_requires_the_session_token(stack, tmp_path):
    _core, port, _token_file = stack
    client = LocalCoreClient(host="127.0.0.1", port=port, token="x" * 48)
    try:
        with pytest.raises(CoreProtocolError) as refused:
            await client.mission_health()
        assert refused.value.status == 401
    finally:
        await client.close()
