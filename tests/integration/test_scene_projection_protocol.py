"""Projection de la scène par le vrai protocole (handoff jarvis-constellation-scene-runtime, Slice 04).

Chaîne réelle, sans tour du cerveau : flux `stream-json` → `AgentTaskTracker` →
`TrackerWorkObserver` → `WorkIngressForwarder` / `CoreWorkTransport` →
`POST /v1/work/observations` → `WorkStateStore` → `SceneProjector` →
`GET /v1/scene/snapshot`.
"""

from __future__ import annotations

import asyncio

import aiohttp

from jarvis.core.scene_projector import signal_object_id, star_object_id
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import PROTOCOL_VERSION
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.work_ingress import CoreWorkTransport, TrackerWorkObserver, WorkIngressForwarder
from tests.integration.test_work_state_protocol import TOKEN, free_port


async def until(condition, *, timeout: float = 10.0) -> None:
    async def poll() -> None:
        while not await condition():
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), timeout)


def objects_by_id(body: dict) -> dict[str, dict]:
    return {item["object_id"]: item for item in body["snapshot"]["objects"]}


async def test_an_http_observation_becomes_a_star_in_the_http_scene_snapshot(tmp_path):
    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
    batch = {
        "source": "claude",
        "producer_id": "cc-1",
        "observations": [
            {"source": "claude", "external_id": "toolu_A", "status": "running", "kind": "agent",
             "observed_at": "2026-09-16T15:00:00+00:00", "label": "Audit"},
            {"source": "claude", "external_id": "bash_1", "status": "running", "kind": "shell",
             "observed_at": "2026-09-16T15:00:00+00:00", "label": "npm test"},
        ],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://127.0.0.1:{port}/v1/work/observations", json=batch, headers=headers) as response:
                assert response.status == 200

        async def star_visible() -> bool:
            return "claude:toolu_A" in objects_by_id(await client.scene_snapshot())

        await until(star_visible)
        body = await client.scene_snapshot()
        star = objects_by_id(body)["claude:toolu_A"]
        assert (star["kind"], star["exec_state"], star["origin"], star["payload"]["title"]) == ("agent", "running", "runtime", "Audit")
        assert star["work_ref"] == {"source": "claude", "external_id": "toolu_A", "work_id": None}
        assert "claude:bash_1" not in objects_by_id(body)
        assert body["revision"] == 1
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def test_a_real_stream_reaches_the_scene_with_topology_and_signals(tmp_path):
    port = free_port()
    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    tracker = AgentTaskTracker(provider="claude")
    forwarder = WorkIngressForwarder(
        source="claude", transport=CoreWorkTransport(host="127.0.0.1", port=port, token_file=token_file), flush_interval_s=0
    )
    observer = TrackerWorkObserver(tracker, forwarder.offer)
    tracker.subscribe(observer.sync)
    forwarder.on_resync = observer.resync
    forwarder.start()
    try:
        tracker.observe_claude({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_P", "name": "Agent", "input": {"description": "Parent", "prompt": "secret prompt", "run_in_background": True}},
        ]}})
        tracker.observe_claude({"type": "system", "subtype": "task_started", "task_id": "a-parent", "tool_use_id": "toolu_P", "description": "Parent", "task_type": "local_agent"})
        # Le sous-agent lance un sous-agent et une commande shell.
        tracker.observe_claude({"type": "assistant", "parent_tool_use_id": "toolu_P", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_C", "name": "Agent", "input": {"description": "Enfant", "prompt": "secret child"}},
        ]}})
        tracker.observe_claude({"type": "system", "subtype": "task_started", "task_id": "b-shell", "description": "pytest", "task_type": "local_bash"})
        tracker.observe_claude({"type": "system", "subtype": "task_notification", "task_id": "b-shell", "status": "failed"})
        tracker.observe_claude({"type": "user", "parent_tool_use_id": "toolu_P", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_C", "is_error": True, "content": "échec"},
        ]}})

        parent_id, child_id = star_object_id("claude", "toolu_P"), star_object_id("claude", "toolu_C")

        async def projected() -> bool:
            body = await client.scene_snapshot()
            objects = objects_by_id(body)
            return child_id in objects and objects[child_id]["exec_state"] == "failed" and any(
                relation["kind"] == "parent_of" for relation in body["snapshot"]["relations"]
            )

        await until(projected)
        body = await client.scene_snapshot()
        objects = objects_by_id(body)
        assert set(objects) == {parent_id, child_id, signal_object_id(child_id)}
        relations = {(item["kind"], item["from_id"], item["to_id"]) for item in body["snapshot"]["relations"]}
        assert relations == {("parent_of", parent_id, child_id), ("explains", signal_object_id(child_id), child_id)}
        assert "secret" not in str(body)
    finally:
        await forwarder.aclose()
        await client.close()
        await server.stop()
        await core.stop()
