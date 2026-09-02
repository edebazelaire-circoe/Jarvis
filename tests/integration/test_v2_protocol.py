from __future__ import annotations

import socket

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_authenticated_loopback_protocol_and_core_tool_roundtrip(tmp_path):
    port = free_port()
    token = "x" * 48
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=token)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=token)
    try:
        assert (await client.health())["ready"] is True
        conversation = await client.create_conversation()
        result = await client.call_tool("reminder_create", {"message": "test", "due_at": "2099-01-01T10:00:00+00:00"}, conversation_id=conversation["id"])
        assert result["executed"] is True
        context = await client.context(conversation["id"])
        assert context["conversation_id"] == conversation["id"]
    finally:
        await client.close(); await server.stop(); await core.stop()


@pytest.mark.asyncio
async def test_wrong_local_token_is_rejected(tmp_path):
    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token="a" * 48)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token="b" * 48)
    try:
        with pytest.raises(RuntimeError, match="401"):
            await client.health()
    finally:
        await client.close(); await server.stop(); await core.stop()
