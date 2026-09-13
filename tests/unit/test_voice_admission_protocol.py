from dataclasses import replace
import json

import pytest
from aiohttp.test_utils import TestServer

from jarvis.domain.voice_admission import VoiceTurnAdmissionAcceptance
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.unit.test_voice_turn_admission import admission_stack, canonical_input


@pytest.fixture
async def protocol(admission_stack):
    core, backend = admission_stack
    server = TestServer(LocalProtocolServer(core, host="127.0.0.1", port=0, token="t" * 48)._app())
    await server.start_server()
    client = LocalCoreClient(host="127.0.0.1", port=server.port, token="t" * 48)
    try:
        yield core, backend, client
    finally:
        await client.close()
        await server.close()


async def test_http_typed_admission_and_duplicate_preserve_exact_text(protocol):
    core, backend, client = protocol
    request, _ = await canonical_input(core)
    values = request.to_payload()
    del values["schema_version"]
    first = await client.admit_voice_turn(**values)
    second = await client.admit_voice_turn(**values)
    assert isinstance(first, VoiceTurnAdmissionAcceptance)
    assert second == replace(first, duplicate=True)
    assert (await core.state.get_turn(first.turn_id)).content == request.text
    assert backend.calls == []


@pytest.mark.parametrize("mutation", [
    "correlation", "unknown", "missing", "bool_revision", "bool_version", "ambient",
    "duplicate_json", "nonfinite", "overflow", "wrong_conversation", "oversize", "server_order",
])
async def test_http_strict_schema_rejects_without_persistence(protocol, mutation):
    core, backend, client = protocol
    request, _ = await canonical_input(core)
    value = request.to_payload()
    if mutation == "correlation":
        value["correlation_id"] = "client-assigned"
    elif mutation == "server_order":
        value["voice_admission_order"] = {"observation_order": 888}
    elif mutation == "unknown":
        value["source"] = {"intent_epoch": 88}
    elif mutation == "missing":
        value.pop("provider_item_id")
    elif mutation == "bool_revision":
        value["transcript_revision"] = True
    elif mutation == "bool_version":
        value["schema_version"] = True
    elif mutation == "ambient":
        value["addressing"] = "ambient"
    elif mutation == "wrong_conversation":
        value["conversation_id"] = "other"
    raw = json.dumps(value)
    if mutation == "duplicate_json":
        raw = raw[:-1] + ',"schema_version":1}'
    elif mutation == "nonfinite":
        raw = raw.replace('"transcript_revision": 1', '"transcript_revision": NaN')
    elif mutation == "overflow":
        raw = raw.replace('"transcript_revision": 1', '"transcript_revision": 1e9999')
    elif mutation == "oversize":
        raw += " " * 65536
    session = await client._http()
    async with session.post(client.base_url + f"/v1/conversations/{request.conversation_id}/voice/admitted-turns",
                            headers=client.headers, data=raw.encode()) as response:
        assert response.status == 400
        assert (await response.json())["error"]["code"] == "invalid_request"
    assert await core.conversations.list_turns(request.conversation_id) == ()
    assert backend.calls == []


async def test_http_auth_health_and_unknown_evidence_are_enforced(protocol):
    core, backend, client = protocol
    request, _ = await canonical_input(core)
    session = await client._http()
    url = client.base_url + f"/v1/conversations/{request.conversation_id}/voice/admitted-turns"
    async with session.post(url, json=request.to_payload()) as response:
        assert response.status == 401
    async with session.post(url + "?force=true", headers=client.headers, json=request.to_payload()) as response:
        assert response.status == 400
    values = request.to_payload()
    del values["schema_version"]
    with pytest.raises(CoreProtocolError) as missing:
        await client.admit_voice_turn(**{**values, "transcript_revision": 2})
    assert missing.value.status == 400
    with pytest.raises(CoreProtocolError) as unknown:
        await client.admit_voice_turn(**{**values, "conversation_id": "unknown"})
    assert unknown.value.status == 404
    core.health.ready = False
    async with session.post(url, headers=client.headers, json=request.to_payload()) as response:
        assert response.status == 503
    assert backend.calls == [] and await core.conversations.list_turns(request.conversation_id) == ()
