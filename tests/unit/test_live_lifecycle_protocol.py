"""Authenticated local protocol surface for Task13A lifecycle authority."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import TestServer

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.live_lifecycle import LiveCloseEvidence, LiveLifecycleState
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.unit.test_live_lifecycle_lease import TestClock


TOKEN = "l" * 48
NOW = datetime(2026, 9, 12, 15, tzinfo=timezone.utc)


@pytest.fixture
async def protocol(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    core.live_lifecycle.clock = TestClock()
    server = TestServer(LocalProtocolServer(core, host="127.0.0.1", port=0, token=TOKEN)._app())
    await server.start_server()
    client = LocalCoreClient(host="127.0.0.1", port=server.port, token=TOKEN)
    try:
        yield core, client
    finally:
        await client.close()
        await server.close()
        await core.stop()


async def test_full_lifecycle_round_trip_is_typed_and_durable(protocol):
    _, client = protocol
    record = await client.reserve_live_session(
        "logical-session", "voice-incarnation",
    )
    assert record.state is LiveLifecycleState.STARTING and record.owner_epoch == 1
    assert await client.live_session_status() == record
    record = await client.mark_live_session_start(
        record.session_id, record.owner_incarnation_id, record.owner_epoch,
        record.revision,
    )
    record = await client.bind_live_session(
        record.session_id, record.owner_incarnation_id, record.owner_epoch,
        record.revision, "provider-session",
    )
    record = await client.transition_live_session(
        record.session_id, record.owner_incarnation_id, record.owner_epoch,
        record.revision, LiveLifecycleState.ACTIVE,
    )
    record = await client.heartbeat_live_session(
        record.session_id, record.owner_incarnation_id, record.owner_epoch,
        record.revision,
    )
    record = await client.update_live_session_usage(
        record.session_id, record.owner_incarnation_id, record.owner_epoch,
        record.revision, 2.0, 1.5,
    )
    record = await client.transition_live_session(
        record.session_id, record.owner_incarnation_id, record.owner_epoch,
        record.revision, LiveLifecycleState.IDLE_CANDIDATE,
    )
    record = await client.transition_live_session(
        record.session_id, record.owner_incarnation_id, record.owner_epoch,
        record.revision, LiveLifecycleState.STOPPING, "idle",
    )
    record = await client.finalize_live_session(
        record.session_id, record.owner_incarnation_id, record.owner_epoch,
        record.revision, "provider-session",
        5.0, 4.0, "idle", LiveCloseEvidence.PROVIDER_SESSION_CLOSED,
    )
    assert record.state is LiveLifecycleState.STOPPED
    assert await client.live_session_status("logical-session") == record
    assert await client.live_session_status() is None


async def test_protocol_conflict_and_malformed_body_do_not_replace_lease(protocol):
    _, client = protocol
    held = await client.reserve_live_session(
        "held", "owner-a",
    )
    with pytest.raises(CoreProtocolError) as conflict:
        await client.reserve_live_session(
            "other", "owner-b",
        )
    assert conflict.value.status == 409 and conflict.value.code == "live_lease_held"

    session = await client._http()
    async with session.post(
        client.base_url + "/v1/live/sessions/held/heartbeat", headers=client.headers,
        json={
            "owner_incarnation_id": "owner-a", "owner_epoch": 1,
            "expected_revision": held.revision,
            "provider_payload": {"secret": "PRIVATE"},
        },
    ) as response:
        assert response.status == 400
        assert (await response.json())["error"]["code"] == "invalid_request"
    assert await client.live_session_status() == held

    async with session.post(
        client.base_url + "/v1/live/sessions/held/transition", headers=client.headers,
        json={
            "owner_incarnation_id": "owner-a", "owner_epoch": 1,
            "expected_revision": held.revision, "target": {"invalid": True},
            "close_reason": None,
        },
    ) as response:
        assert response.status == 400


async def test_expired_record_can_be_claimed_through_protocol_but_not_replaced(protocol):
    _, client = protocol
    record = await client.reserve_live_session(
        "expired", "owner-a",
    )
    client_clock = protocol[0].live_lifecycle.clock
    client_clock.value = record.lease_deadline + timedelta(seconds=1)
    claimed = await client.claim_live_session_reap(
        record.session_id, "reaper", record.revision,
    )
    assert claimed.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
    assert claimed.owner_incarnation_id == "reaper" and claimed.owner_epoch == 2
    with pytest.raises(CoreProtocolError) as conflict:
        await client.reserve_live_session("replacement", "owner-b")
    assert conflict.value.code == "live_lease_held"
