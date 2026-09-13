from __future__ import annotations

import aiohttp
import asyncio
import pytest

from tests.integration.test_v2_brain_protocol import protocol_stack, auth_headers
from jarvis.domain.v2 import ProtocolEnvelope


@pytest.mark.parametrize("suffix,method,body", [
    ("speech-context", "get", None), ("outcomes", "get", None),
    ("outcomes/missing", "get", None), ("outcomes/missing/select", "post", {"selection_id": "choice"}),
])
async def test_outcome_routes_require_existing_loopback_authorization(tmp_path, suffix, method, body):
    async with protocol_stack(tmp_path) as (_, client, port):
        conv = (await client.create_conversation())["id"]
        async with aiohttp.ClientSession() as session:
            async with session.request(method, f"http://127.0.0.1:{port}/v1/conversations/{conv}/{suffix}",
                                       headers=auth_headers(token="wrong"), json=body) as response:
                assert response.status == 401


@pytest.mark.parametrize("suffix", ["outcomes?limit=0", "outcomes?limit=129", "outcomes?limit=NaN",
                                   "outcomes?limit=1.1", "outcomes?limit=32&limit=1", "outcomes?extra=1",
                                   "speech-context?source=client", "outcomes/missing?source=client"])
async def test_outcome_reads_reject_invalid_and_unbounded_query(tmp_path, suffix):
    async with protocol_stack(tmp_path) as (_, client, port):
        conv = (await client.create_conversation())["id"]
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/v1/conversations/{conv}/{suffix}", headers=auth_headers()) as response:
                assert response.status == 400


@pytest.mark.parametrize("body", [None, [], {}, {"selection_id": True}, {"selection_id": "x" * 257},
                                {"selection_id": "ok", "source": {}}, {"selection_id": "ok", "text": "forged"}])
async def test_selection_rejects_invalid_identity_and_forged_authority(tmp_path, body):
    async with protocol_stack(tmp_path) as (_, client, port):
        conv = (await client.create_conversation())["id"]
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://127.0.0.1:{port}/v1/conversations/{conv}/outcomes/missing/select",
                                    headers=auth_headers(), json=body) as response:
                assert response.status == 400


async def test_unknown_conversation_is_not_created_by_outcome_read(tmp_path):
    async with protocol_stack(tmp_path) as (_, _, port):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/v1/conversations/missing/outcomes", headers=auth_headers()) as response:
                assert response.status == 404


async def test_event_subscription_barrier_precedes_snapshot_and_first_event(tmp_path):
    async with protocol_stack(tmp_path) as (core, client, _):
        connected = asyncio.Event()
        stream = client.events(on_connected=connected.set)
        first = asyncio.create_task(anext(stream))
        try:
            await asyncio.wait_for(connected.wait(), 1)
            assert not first.done()
            # The server has subscribed before sending connected, so an event
            # published after this barrier cannot be lost before a snapshot.
            await core.events.publish(ProtocolEnvelope(message_type="test.after.connected", payload={}))
            assert (await asyncio.wait_for(first, 1)).message_type == "test.after.connected"
        finally:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await stream.aclose()
