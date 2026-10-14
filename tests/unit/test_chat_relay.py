"""`POST /api/chat/turns` du Control Center (`docs/chat.md` › *Sending text*, Slice 03).

Vrai `ControlCenter` (garde `_origin_guard`, routes montées) devant un transport
factice de Core, puis une fois la chaîne réelle Core → `LocalProtocolServer` →
`CoreSessionTransport` → Control Center (`tests/fakes/capture_stack.py`).
Le navigateur n'appelle jamais `/api/agent/ask` ni `/api/agent/send`.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jarvis.runtime.chat_relay import CHAT_TURN_TIMEOUT_S
from jarvis.runtime.control_center import ControlCenter
from tests.fakes.capture_stack import CaptureStack

TEXT = "Texte secret du message"


class FakeCore:
    """Transport de Core : rend `answer` (statut, JSON) ou lève `raises` ; garde chaque appel."""

    def __init__(self, answer=(202, {}), raises: BaseException | None = None) -> None:
        self.answer, self.raises, self.calls = answer, raises, []

    async def forward(self, method, path, *, params=None, body=None, timeout_s=None):
        self.calls.append({"method": method, "path": path, "body": json.loads(body) if body else None,
                           "timeout_s": timeout_s})
        if self.raises is not None:
            raise self.raises
        return self.answer


@pytest.fixture
async def center(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    control = ControlCenter(runtime_root=runtime, project_root=tmp_path)
    control.sessions = FakeCore()
    client = TestClient(TestServer(control._app))
    await client.start_server()
    try:
        yield control, client, runtime
    finally:
        await client.close()


def turn_body(**overrides) -> dict:
    return {"conversation_id": "c0nv-1", "client_request_id": str(uuid.uuid4()), "content": TEXT, **overrides}


def journal(runtime) -> list[dict]:
    path = runtime / "trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Host": "evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
async def test_the_guard_refuses_foreign_requests(center, headers):
    control, client, _ = center
    response = await client.post("/api/chat/turns", json=turn_body(), headers=headers)
    assert response.status == 403
    assert control.sessions.calls == []


async def test_json_only_and_bounded(center):
    control, client, _ = center
    response = await client.post("/api/chat/turns", data=json.dumps(turn_body()).encode(),
                                 headers={"Content-Type": "text/plain"})
    assert (response.status, (await response.json())["code"]) == (415, "invalid_content_type")
    response = await client.post("/api/chat/turns", json=turn_body(content="x" * (64 * 1024 + 1)))
    assert (response.status, (await response.json())["code"]) == (413, "request_too_large")
    for bad in (turn_body(extra=1), turn_body(client_request_id="nope"), turn_body(content=3),
                turn_body(conversation_id="../v1/x"), turn_body(attachments="jart_x"), {"content": TEXT},
                turn_body(conversation_id="c/brain-turns/cancel")):
        response = await client.post("/api/chat/turns", json=bad)
        body = await response.json()
        assert (response.status, body["code"]) == (400, "invalid_request"), bad
        assert TEXT not in json.dumps(body)
    assert control.sessions.calls == []


async def test_the_core_body_is_closed_and_the_answer_is_reshaped(center):
    control, client, runtime = center
    request = turn_body()
    control.sessions.answer = (202, {"turn_id": "brain-turn-x", "conversation_id": "c0nv-1", "duplicate": False,
                                     "correlation_id": "chat:" + request["client_request_id"], "revision": 3,
                                     "source": None, "speech": "internal"})
    response = await client.post("/api/chat/turns", json=request)
    assert response.status == 202
    assert await response.json() == {"ok": True, "correlation_id": "chat:" + request["client_request_id"],
                                     "turn_id": "brain-turn-x", "duplicate": False}
    [call] = control.sessions.calls
    assert call["method"] == "POST" and call["path"] == "/v1/conversations/c0nv-1/brain-turns"
    assert call["body"] == {"content": TEXT, "correlation_id": "chat:" + request["client_request_id"],
                            "source": "text", "addressing": "addressed", "attachments": []}
    assert call["timeout_s"] == CHAT_TURN_TIMEOUT_S == 15.0
    control.sessions.answer = (200, {"turn_id": "brain-turn-x", "correlation_id": "chat:x", "duplicate": True})
    response = await client.post("/api/chat/turns", json=request)
    assert response.status == 200 and (await response.json())["duplicate"] is True
    relayed = [line for line in journal(runtime) if line.get("kind") == "chat.turn.relayed"]
    assert [line["data"] for line in relayed] == [
        {"status": 202, "code": None, "correlation_id": "chat:" + request["client_request_id"], "attachments": 0},
        {"status": 200, "code": None, "correlation_id": "chat:" + request["client_request_id"], "attachments": 0}]
    assert TEXT not in (runtime / "trace.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("status, error, extra", [
    (409, {"code": "chat_input_locked", "message": "m", "reason": "voice_active"}, {"reason": "voice_active"}),
    (409, {"code": "chat_conversation_not_foreground", "message": "m", "current_conversation_id": "c-2"},
     {"current_conversation_id": "c-2"}),
    (409, {"code": "chat_request_conflict", "message": "m"}, {}),
    (400, {"code": "chat_text_too_long", "message": "m"}, {}),
    (404, {"code": "session_not_found", "message": "m"}, {}),
    (503, {"code": "core_unavailable", "message": "m"}, {}),
    (503, {"code": "core_stopping", "message": "m"}, {}),
])
async def test_core_codes_are_relayed(center, status, error, extra):
    control, client, runtime = center
    control.sessions.answer = (status, {"error": error})
    response = await client.post("/api/chat/turns", json=turn_body())
    assert response.status == status
    assert await response.json() == {"ok": False, "code": error["code"], "error": "m", "core_status": status, **extra}
    [line] = [line for line in journal(runtime) if line.get("kind") == "chat.turn.relayed"]
    assert (line["data"]["status"], line["data"]["code"]) == (status, error["code"])


async def test_core_timeout_is_a_504_to_replay(center):
    control, client, _ = center
    control.sessions.raises = asyncio.TimeoutError()
    response = await client.post("/api/chat/turns", json=turn_body())
    body = await response.json()
    assert response.status == 504 and body["code"] == "core_timeout" and body["core_status"] is None
    assert "resend the same client_request_id" in body["error"]
    control.sessions.raises = ConnectionRefusedError("down")
    response = await client.post("/api/chat/turns", json=turn_body())
    assert (response.status, (await response.json())["code"]) == (503, "core_unreachable")


async def test_the_real_chain_admits_a_text_turn(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        stack.core.voice_channel.started_at -= 10.0  # voix absente
        conversation_id = (await stack.core.sessions.current()).binding.conversation_id
        request = {"conversation_id": conversation_id, "client_request_id": str(uuid.uuid4()), "content": TEXT}
        status, body, _ = await stack.call("POST", "/api/chat/turns", json=request)
        assert status == 202 and body["ok"] is True and body["duplicate"] is False
        status, again, _ = await stack.call("POST", "/api/chat/turns", json=request)
        assert (status, again["turn_id"], again["duplicate"]) == (200, body["turn_id"], True)
        stack.core.voice_channel.report({"schema_version": 1, "voice_incarnation_id": "v", "seq": 1,
                                         "lifecycle_state": "active", "conversation_id": None, "ack": None})
        status, locked, _ = await stack.call("POST", "/api/chat/turns", json={**request,
                                                                             "client_request_id": str(uuid.uuid4())})
        assert (status, locked["code"], locked["reason"]) == (409, "chat_input_locked", "voice_active")
        record = await stack.core.brain.admitted_turn(conversation_id, body["correlation_id"])
        assert record.content == TEXT and record.metadata["source"] == "text"
        trace = stack.tmp_path.joinpath("runtime", "trace.jsonl").read_text(encoding="utf-8")
        assert TEXT not in trace and "/api/agent/ask" not in trace
