"""Ingress de l'état de travail par la boucle locale (handoff work-state, tâche 11).

Chaîne réelle : tracker Claude → observateur → file → `CoreWorkTransport` →
`POST /v1/work/observations` → `WorkStateStore` → `GET /v1/work/snapshot`.
Core répond seul : aucun Control Center n'est monté pour lire l'instantané.
"""

from __future__ import annotations

import asyncio
import socket

import aiohttp
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import PROTOCOL_VERSION
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.work_ingress import CoreWorkTransport, TrackerWorkObserver, WorkIngressForwarder

TOKEN = "w" * 48


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def core_stack(tmp_path):
    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        yield core, client, port
    finally:
        await client.close()
        await server.stop()
        await core.stop()


def batch(**overrides) -> dict:
    observation = {
        "source": "claude", "external_id": "toolu_A", "status": "running",
        "observed_at": "2026-09-11T15:00:00+00:00", "label": "Persist voice arch setting",
    }
    observation.update(overrides.pop("observation", {}))
    payload = {"source": "claude", "producer_id": "cc-1", "observations": [observation]}
    payload.update(overrides)
    return payload


async def raw_post(port: int, payload, *, token: str = TOKEN) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://127.0.0.1:{port}/v1/work/observations", json=payload, headers=headers) as response:
            return response.status, await response.json()


async def test_an_ingested_batch_is_readable_from_core_alone(core_stack):
    core, client, _ = core_stack

    result = await client.ingest_work_observations(batch())
    snapshot = await client.work_snapshot()

    assert result["outcomes"] == {"created": 1} and result["revision"] == 1
    assert result["store_id"] == snapshot["store_id"] == core.work_state.store_id
    assert snapshot["revision"] == 1
    assert [item["external_id"] for item in snapshot["items"]] == ["toolu_A"]
    assert snapshot["items"][0]["status"] == "running"


@pytest.mark.parametrize(
    "payload",
    [
        batch(observation={"prompt": "Rends le réglage persistant."}),
        batch(observation={"raw": {"type": "system"}}),
        batch(trace=[]),
        batch(observation={"status": "exploded"}),
        batch(observation={"observed_at": "hier"}),
        batch(observation={"tokens": "beaucoup"}),
        batch(observation={"source": "codex"}),
        ["pas", "un", "objet"],
    ],
    ids=["prompt", "raw", "envelope-trace", "status", "date", "tokens-type", "source-mismatch", "not-object"],
)
async def test_an_invalid_or_raw_batch_is_refused_and_nothing_is_applied(core_stack, payload):
    core, _, port = core_stack

    status, body = await raw_post(port, payload)

    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert core.work_state.revision == 0


async def test_the_work_ingress_requires_the_session_token(core_stack):
    core, _, port = core_stack

    status, _ = await raw_post(port, batch(), token="x" * 48)

    assert status == 401 and core.work_state.revision == 0


async def test_tracker_subtasks_reach_core_through_the_real_transport(core_stack, tmp_path):
    core, client, port = core_stack
    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    tracker = AgentTaskTracker(provider="claude")
    forwarder = WorkIngressForwarder(source="claude", transport=CoreWorkTransport(host="127.0.0.1", port=port, token_file=token_file))
    observer = TrackerWorkObserver(tracker, forwarder.offer)
    tracker.subscribe(observer.sync)
    forwarder.on_resync = observer.resync

    tracker.observe_claude({
        "type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_A", "name": "Agent", "input": {"description": "Persist", "prompt": "secret", "run_in_background": True}},
        ]},
    })
    tracker.observe_claude({"type": "system", "subtype": "task_started", "task_id": "a1", "tool_use_id": "toolu_A", "description": "Persist", "task_type": "local_agent"})
    assert await forwarder.flush() is True
    tracker.process_stopped()
    assert await forwarder.flush() is True
    await forwarder.aclose()

    snapshot = await client.work_snapshot()
    [item] = snapshot["items"]
    assert item["external_id"] == "toolu_A" and item["status"] == "interrupted" and item["error_class"] == "process_stopped"
    assert "secret" not in str(snapshot)


async def test_a_restarted_core_relearns_the_subtasks_without_a_new_stream_event(tmp_path):
    """Core redémarre (magasin vide, nouveau jeton) pendant qu'aucune sous-tâche ne bouge."""

    port = free_port()
    token_file = tmp_path / "core.token"

    async def serve(token: str) -> tuple[JarvisCoreApplication, LocalProtocolServer]:
        token_file.write_text(token, encoding="utf-8")
        core = JarvisCoreApplication(data_root=tmp_path / "data")
        await core.start()
        server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=token)
        await server.start()
        return core, server

    async def until(condition) -> None:
        async def poll() -> None:
            while not condition():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(poll(), timeout=10)

    def statuses(core: JarvisCoreApplication) -> dict[str, str]:
        return {item.external_id: item.status.value for item in core.work_state.current_snapshot().items}

    tracker = AgentTaskTracker(provider="claude")
    forwarder = WorkIngressForwarder(
        source="claude",
        transport=CoreWorkTransport(host="127.0.0.1", port=port, token_file=token_file),
        flush_interval_s=0,
        retry_min_s=0.02,
        retry_max_s=0.05,
        resync_interval_s=0.05,
    )
    observer = TrackerWorkObserver(tracker, forwarder.offer)
    tracker.subscribe(observer.sync)
    forwarder.on_resync = observer.resync

    core, server = await serve("a" * 48)
    forwarder.start()
    try:
        tracker.observe_claude({"type": "system", "subtype": "task_started", "task_id": "a1", "description": "Persist", "task_type": "local_bash"})
        tracker.observe_claude({"type": "system", "subtype": "task_started", "task_id": "b1", "description": "Tests", "task_type": "local_agent"})
        tracker.observe_claude({"type": "system", "subtype": "task_notification", "task_id": "b1", "status": "completed", "summary": "Verts."})
        await until(lambda: statuses(core) == {"a1": "running", "b1": "completed"})
        first_store = core.work_state.store_id
        await server.stop()
        await core.stop()

        core, server = await serve("b" * 48)

        await until(lambda: statuses(core) == {"a1": "running", "b1": "completed"})
        assert core.work_state.store_id != first_store
        assert forwarder.dropped_total == 0
    finally:
        await forwarder.aclose()
        await server.stop()
        await core.stop()


async def test_the_transport_waits_for_a_missing_token_without_failing_the_agent(tmp_path):
    forwarder = WorkIngressForwarder(
        source="claude",
        transport=CoreWorkTransport(host="127.0.0.1", port=free_port(), token_file=tmp_path / "absent.token"),
    )
    tracker = AgentTaskTracker(provider="claude")
    tracker.subscribe(TrackerWorkObserver(tracker, forwarder.offer).sync)

    tracker.observe_claude({"type": "system", "subtype": "task_started", "task_id": "a1", "description": "Persist", "task_type": "local_agent"})

    assert await forwarder.flush() is False
    assert forwarder.pending_count == 1
    await forwarder.aclose()


async def test_an_empty_batch_from_a_new_producer_claims_the_source_and_interrupts_the_old_instance(core_stack):
    """Slice 10 : un Control Center redémarré au tracker vide revendique la source par un lot vide."""

    core, _, port = core_stack
    status, _ = await raw_post(port, batch())  # instance cc-1 : toolu_A en cours
    assert status == 200
    status, body = await raw_post(port, {"source": "claude", "producer_id": "cc-2", "observations": []})
    assert status == 200 and body["interrupted"] == 1 and body["outcomes"] == {}
    item = core.work_state.current_snapshot().items[0]
    assert (item.status.value, item.error_class) == ("interrupted", "producer_restarted")
    status, body = await raw_post(port, {"source": "claude", "producer_id": "cc-2", "observations": []})
    assert status == 200 and body["interrupted"] == 0  # même instance : rien de plus
