"""Canal vocal et état du Chat de bout en bout : routes Core, client typé, relais du Control Center, garde, 400 stricts.

Chaîne réelle (`tests/fakes/capture_stack.py`) : Core → `LocalProtocolServer`
→ `CoreSessionTransport` → vrai `ControlCenter`, ports éphémères, tout sous
`tmp_path`. Aucun Voice : ses rapports sont envoyés par le client typé, comme
le ferait `PersistentVoiceRuntime.send_voice_channel_report`.
"""

from __future__ import annotations

import uuid

import aiohttp
import pytest

from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.runtime.chat_relay import ChatRelayRoutes, GUARDED_PREFIXES
from jarvis.runtime.control_center import READ_GUARDED_ROUTES
from tests.fakes.capture_stack import TOKEN, CaptureStack


def report(seq: int, state: str, *, ack: dict | None = None, incarnation: str = "voice-test") -> dict:
    return {"schema_version": 1, "voice_incarnation_id": incarnation, "seq": seq, "lifecycle_state": state,
            "conversation_id": None, "ack": ack}


@pytest.fixture
async def stack(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        client = LocalCoreClient(host="127.0.0.1", port=int(stack.core_url.rsplit(":", 1)[1]), token=TOKEN)
        try:
            yield stack, client
        finally:
            await client.close()


async def test_the_full_switch_through_core_and_the_control_center(stack):
    stack, client = stack
    mode_before = stack.core.interaction_mode.snapshot()
    session_before = (await stack.core.sessions.current()).to_payload()

    answer = await client.voice_channel_report(report(1, "active"), timeout_s=2.0)
    assert answer["accepted"] is True and answer["disable_request"] is None
    assert answer["epoch"] == stack.core.voice_channel.epoch

    status, state, _ = await stack.call("GET", "/api/chat/state")
    assert status == 200
    binding = session_before["binding"]
    assert (state["jarvis_session_id"], state["board_id"], state["conversation_id"]) == (
        binding["jarvis_session_id"], binding["board_id"], binding["conversation_id"])
    assert state["voice"]["state"] == "active"
    assert (state["chat_writable"], state["locked_reason"]) == (False, "voice_active")

    client_id = str(uuid.uuid4())
    status, disabled, _ = await stack.call("POST", "/api/chat/voice/disable", json={"client_request_id": client_id})
    assert status == 202 and disabled["state"] == "switching"
    status, again, _ = await stack.call("POST", "/api/chat/voice/disable", json={"client_request_id": client_id})
    assert status == 202 and again["request_id"] == disabled["request_id"]
    assert (await client.chat_state())["locked_reason"] == "voice_switching"

    answer = await client.voice_channel_report(report(2, "active"), timeout_s=2.0)
    assert answer["disable_request"]["request_id"] == disabled["request_id"]
    await client.voice_channel_report(report(3, "background", ack={"request_id": disabled["request_id"],
                                                                   "result": "accepted", "code": None}),
                                      timeout_s=2.0)

    _, state, _ = await stack.call("GET", "/api/chat/state")
    assert (state["chat_writable"], state["locked_reason"]) == (True, None)
    assert state["voice"]["request"] == {"request_id": disabled["request_id"], "status": "accepted", "code": None}
    # La bascule ne touche ni la Session, ni le Board, ni la liaison, ni le mode d'interaction.
    assert (await stack.core.sessions.current()).to_payload() == session_before
    assert stack.core.interaction_mode.snapshot() == mode_before
    relayed = [e for e in stack.trace() if e.get("kind") == "chat.request.relayed"]
    assert [e["data"]["action"] for e in relayed] == ["voice_disable", "voice_disable"]
    assert all(set(e["data"]) == {"action", "status", "code"} for e in relayed)


async def test_nothing_to_do_when_voice_is_absent(stack):
    stack, client = stack
    stack.core.voice_channel.started_at -= 10.0  # après la période de grâce, sans rapport
    assert (await client.chat_state())["voice"]["state"] == "absent"
    assert await client.disable_voice_channel(str(uuid.uuid4())) == {"state": "absent", "request_id": None,
                                                                      "status": None}


async def test_core_starts_unknown(stack):
    stack, client = stack
    state = await client.chat_state()
    assert state["voice"]["state"] == "unknown" and state["locked_reason"] == "voice_unknown"
    assert state["voice"]["report_age_ms"] is None and state["schema_version"] == 1


async def test_core_routes_require_the_token(stack):
    stack, _ = stack
    async with aiohttp.ClientSession() as session:
        for method, path in (("POST", "/v1/voice/channel/report"), ("POST", "/v1/voice/channel/disable"),
                             ("GET", "/v1/chat/state")):
            async with session.request(method, stack.core_url + path, json={}) as response:
                assert response.status == 401
                assert (await response.json())["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("payload", [
    {**report(1, "active"), "extra": True},
    {**report(1, "active"), "seq": "1"},
    {**report(1, "active"), "schema_version": 2},
    {**report(1, "active"), "ack": {"request_id": "vcr-1", "result": "nope"}},
    [],
])
async def test_a_malformed_report_is_a_strict_400(stack, payload):
    _, client = stack
    with pytest.raises(CoreProtocolError) as refused:
        await client.voice_channel_report(payload if isinstance(payload, dict) else {"x": payload}, timeout_s=2.0)
    assert (refused.value.status, refused.value.code) == (400, "invalid_request")


async def test_raw_bodies_are_strict(stack):
    stack, _ = stack
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with aiohttp.ClientSession() as session:
        cases = [("/v1/voice/channel/report", b'{"seq": 1, "seq": 2}'), ("/v1/voice/channel/report", b"not json"),
                 ("/v1/voice/channel/report", b"x" * 5000), ("/v1/voice/channel/disable", b'{"client_request_id": 1}'),
                 ("/v1/voice/channel/disable", b'{"client_request_id": "not-a-uuid"}'),
                 ("/v1/voice/channel/disable", b"{}")]
        for path, body in cases:
            async with session.post(stack.core_url + path, data=body, headers=headers) as response:
                assert response.status == 400, (path, body)
                assert (await response.json())["error"]["code"] == "invalid_request"
        async with session.get(stack.core_url + "/v1/chat/state?x=1", headers=headers) as response:
            assert response.status == 400


async def test_a_stale_report_is_answered_but_ignored(stack):
    _, client = stack
    await client.voice_channel_report(report(5, "background"), timeout_s=2.0)
    answer = await client.voice_channel_report(report(5, "active"), timeout_s=2.0)
    assert answer["accepted"] is False
    assert (await client.chat_state())["voice"]["state"] == "background"


async def test_the_control_center_relay_refusals_use_the_chat_envelope(stack):
    stack, _ = stack
    status, body, _ = await stack.call("POST", "/api/chat/voice/disable", data=b'{"client_request_id": "x"}')
    assert (status, body) == (415, {"ok": False, "code": "invalid_content_type",
                                    "error": "Content-Type: application/json expected", "core_status": None})
    status, body, _ = await stack.call("POST", "/api/chat/voice/disable", json={"client_request_id": "x" * 70000})
    assert (status, body["code"]) == (413, "request_too_large")
    status, body, _ = await stack.call("POST", "/api/chat/voice/disable", json={"client_request_id": "nope"})
    assert (status, body["code"], body["core_status"]) == (400, "invalid_request", 400)
    status, body, _ = await stack.call("GET", "/api/chat/state", params={"x": "1"})
    assert (status, body["code"]) == (400, "invalid_request")


async def test_the_chat_prefix_is_guarded_for_every_method(stack):
    stack, _ = stack
    assert set(GUARDED_PREFIXES) <= set(READ_GUARDED_ROUTES)
    for method, path in (("GET", "/api/chat/state"), ("POST", "/api/chat/voice/disable")):
        status, _, _ = await stack.call(method, path, json={"client_request_id": str(uuid.uuid4())},
                                        headers={"Sec-Fetch-Site": "cross-site"})
        assert status == 403
        status, _, _ = await stack.call(method, path, json={"client_request_id": str(uuid.uuid4())},
                                        headers={"Origin": "https://evil.example"})
        assert status == 403


async def test_the_relay_never_forwards_a_voice_report():
    relay = ChatRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    paths = {route.path for route in relay.routes()}
    assert paths == {"/api/chat/state", "/api/chat/voice/disable"}
    assert set(vars(relay)) == {"_transport", "_journal"}  # aucun état du Chat dans le Control Center
    client = LocalCoreClient(host="127.0.0.1", port=9, token=TOKEN)
    try:
        with pytest.raises(ValueError):
            await client.forward_json("POST", "/v1/voice/channel/report", body=b"{}")
    finally:
        await client.close()


async def test_core_unreachable_is_a_503_without_core_status(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    class Down:
        async def forward(self, *args, **kwargs):
            raise ConnectionRefusedError("refused")

    class Journal:
        def __init__(self):
            self.kinds = []

        def emit(self, kind, message, *, level="info", data=None):
            self.kinds.append(kind)

    journal = Journal()
    app = web.Application()
    app.add_routes(ChatRelayRoutes(transport=lambda: Down(), journal=journal).routes())
    async with TestClient(TestServer(app)) as cc:
        response = await cc.get("/api/chat/state")
        body = await response.json()
        assert response.status == 503 and body["code"] == "core_unreachable" and body["core_status"] is None
        assert body["ok"] is False
        assert journal.kinds == ["chat.request.core_unreachable"]
