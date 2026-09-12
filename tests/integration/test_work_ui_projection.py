"""Le panneau Agents lit Core par la boucle locale (handoff work-state, tâche 13).

Chaîne réelle : tracker Claude du Control Center → relais → `POST
/v1/work/observations` → `WorkStateStore` ; puis `GET /api/work` du Control
Center → `CoreWorkView` → `CoreWorkTransport` → `GET /v1/work/snapshot`. Le
cerveau lit le même magasin : même `store_id`, même révision, mêmes faits. La
trace brute reste servie par `/api/agent/tasks/{external_id}/trace`. Core
arrêté : « Core indisponible » ; Core redémarré : nouveau magasin, état
réappris, la révision repart de bas sans être prise pour une réponse périmée.
"""

from __future__ import annotations

from datetime import datetime, timezone
import socket

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.brain_context import build_brain_work_context
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.work_ingress import CoreWorkTransport, WorkIngressForwarder
from jarvis.runtime.work_view import CORE_UNREACHABLE, CoreWorkView

SESSION = "ac329510-db70-42d4-84ac-5fddd9b11c0d"
T0 = 1_789_047_300.0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def agent_call(tool_use_id: str, description: str) -> dict:
    return {
        "type": "assistant", "parent_tool_use_id": None, "session_id": SESSION,
        "message": {"model": "claude-opus-5", "role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Agent",
             "input": {"description": description, "prompt": "Prompt du sous-agent.", "run_in_background": True, "model": "sonnet"}},
        ]},
    }


def task_started(task_id: str, tool_use_id: str, description: str) -> dict:
    return {
        "type": "system", "subtype": "task_started", "task_id": task_id, "tool_use_id": tool_use_id,
        "description": description, "is_backgrounded": True, "task_type": "local_agent",
        "subagent_type": "general-purpose", "prompt": "Prompt du sous-agent.", "session_id": SESSION,
    }


def progress(task_id: str, tool_use_id: str, activity: str) -> dict:
    return {
        "type": "system", "subtype": "task_progress", "task_id": task_id, "tool_use_id": tool_use_id,
        "description": activity, "usage": {"total_tokens": 900, "tool_uses": 2}, "session_id": SESSION,
    }


def notification(task_id: str, tool_use_id: str, status: str, summary: str) -> dict:
    return {
        "type": "system", "subtype": "task_notification", "task_id": task_id, "tool_use_id": tool_use_id,
        "status": status, "summary": summary, "session_id": SESSION,
    }


class CoreProcess:
    """Un Core réel sur la boucle locale, redémarrable avec un nouveau jeton."""

    def __init__(self, tmp_path, token_file) -> None:  # noqa: ANN001
        self.tmp_path = tmp_path
        self.token_file = token_file
        self.port = free_port()
        self.core: JarvisCoreApplication | None = None
        self.server: LocalProtocolServer | None = None
        self.generation = 0

    async def start(self) -> JarvisCoreApplication:
        self.generation += 1
        token = f"{self.generation}" * 48
        self.token_file.write_text(token, encoding="utf-8")
        self.core = JarvisCoreApplication(data_root=self.tmp_path / f"data-{self.generation}")
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=token)
        await self.server.start()
        return self.core

    async def stop(self) -> None:
        if self.server is not None:
            await self.server.stop()
        if self.core is not None:
            await self.core.stop()
        self.server = self.core = None


@pytest.fixture
async def stack(tmp_path):
    token_file = tmp_path / "core.token"
    process = CoreProcess(tmp_path, token_file)
    await process.start()
    clock = Clock()
    forwarder = WorkIngressForwarder(
        source="claude",
        transport=CoreWorkTransport(host="127.0.0.1", port=process.port, token_file=token_file),
    )
    view = CoreWorkView(CoreWorkTransport(host="127.0.0.1", port=process.port, token_file=token_file))
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path, work_ingress=forwarder, work_view=view)
    control.agent.subtasks.clock = clock
    client = TestClient(TestServer(control._app))
    await client.start_server()
    try:
        yield process, control, forwarder, client, clock
    finally:
        await client.close()
        await forwarder.aclose()
        await view.aclose()
        await process.stop()


def feed(control: ControlCenter, *events: dict) -> None:
    for event in events:
        control.agent._record(event)


async def test_the_panel_shows_what_core_holds_and_the_brain_reads(stack):
    process, control, forwarder, client, clock = stack
    core = process.core
    feed(control, agent_call("toolu_A", "Analyse du dépôt"), task_started("a1", "toolu_A", "Analyse du dépôt"))
    clock.advance(3)
    feed(control, progress("a1", "toolu_A", "Read · app.py"), agent_call("toolu_B", "Relecture"))
    clock.advance(40)
    feed(control, task_started("b1", "toolu_B", "Relecture"), notification("b1", "toolu_B", "failed", "Délai dépassé."))
    assert await forwarder.flush()

    response = await client.get("/api/work")
    body = await response.json()
    snapshot = core.work_state.current_snapshot()
    brain = build_brain_work_context(snapshot, now=datetime.fromtimestamp(clock.now, tz=timezone.utc), store_id=core.work_state.store_id)
    reader = LocalCoreClient(host="127.0.0.1", port=process.port, token=process.token_file.read_text())
    try:
        direct = await reader.work_snapshot()
    finally:
        await reader.close()

    assert response.status == 200 and body["source"] == "core" and body["core_reachable"] is True
    assert (body["store_id"], body["revision"]) == (brain.store_id, brain.revision) == (direct["store_id"], direct["revision"])
    assert body["items"] == direct["items"]
    shown = {item["external_id"]: item for item in body["items"]}
    assert set(shown) == {entry.external_id for entry in brain.items} == {"toolu_A", "toolu_B"}
    for entry in brain.items:
        item = shown[entry.external_id]
        assert (item["status"], item["label"], item["activity"], item["model"], item["error_class"]) == (
            entry.status.value, entry.label, entry.activity, entry.model, entry.error_class,
        )
    assert shown["toolu_A"]["status"] == "running" and shown["toolu_A"]["activity"] == "Read · app.py"
    assert shown["toolu_B"]["status"] == "failed" and shown["toolu_B"]["summary"] == "Délai dépassé."
    # Rien du flux brut : le prompt reste dans le diagnostic du Control Center.
    assert "Prompt du sous-agent" not in await response.text()

    # La trace brute se retrouve depuis l'identifiant que Core connaît.
    for external_id in shown:
        trace = await client.get(f"/api/agent/tasks/{external_id}/trace")
        assert trace.status == 200 and (await trace.json())["task"]["work_key"] == external_id
    revision = core.work_state.revision
    for _ in range(3):
        await client.get("/api/work")
    assert core.work_state.revision == revision  # lire n'écrit rien


async def test_core_down_then_restarted_is_explicit_then_relearned(stack):
    process, control, forwarder, client, clock = stack
    feed(control, agent_call("toolu_A", "Analyse du dépôt"), task_started("a1", "toolu_A", "Analyse du dépôt"))
    assert await forwarder.flush()
    for activity in ("Read · app.py", "Grep · work"):
        clock.advance(1)
        feed(control, progress("a1", "toolu_A", activity))
        assert await forwarder.flush()
    before = await (await client.get("/api/work")).json()
    assert before["revision"] == 3

    await process.stop()
    down = await (await client.get("/api/work")).json()
    compat = await client.get("/api/agent/tasks")

    assert down["core_reachable"] is False and down["items"] == []
    assert down["error"]["code"] == CORE_UNREACHABLE
    assert compat.status == 200 and [task["id"] for task in (await compat.json())["tasks"]] == ["a1"]

    core = await process.start()  # nouveau jeton, magasin vide
    empty = await (await client.get("/api/work")).json()  # la lecture relit le jeton d'elle-même
    assert empty["core_reachable"] is True and empty["items"] == [] and empty["revision"] == 0
    # Le relais renvoie l'état complet (ici sans attendre sa sonde de 30 s) ;
    # son premier envoi tombe sur l'ancien jeton, le suivant passe.
    forwarder.on_resync()
    for _ in range(3):
        if await forwarder.flush():
            break
    after = await (await client.get("/api/work")).json()

    assert after["core_reachable"] is True and after["stale"] is False
    assert after["store_id"] == core.work_state.store_id != before["store_id"]
    assert after["revision"] < before["revision"]  # un autre magasin : pas une réponse périmée
    assert [item["external_id"] for item in after["items"]] == ["toolu_A"]
