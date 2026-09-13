from dataclasses import replace
import asyncio
import json

import pytest
from aiohttp.test_utils import TestServer

from jarvis.domain.back_brain import BackBrainAdvisoryReference, BackBrainResult, BackBrainSubmitRequest
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.unit.test_back_brain_tasks import admitted, stack


@pytest.fixture
async def protocol(stack):
    core, worker, root = stack
    server = TestServer(LocalProtocolServer(core, host="127.0.0.1", port=0, token="t" * 48)._app())
    await server.start_server()
    client = LocalCoreClient(host="127.0.0.1", port=server.port, token="t" * 48)
    try:
        yield core, worker, client
    finally:
        await client.close()
        await server.close()


async def test_real_http_immediate_acceptance_query_list_and_owned_cancel(protocol):
    core, worker, client = protocol
    request, admission = await admitted(core)
    accepted = await asyncio.wait_for(client.submit_back_brain_task(request.conversation_id, source_correlation_id=admission.correlation_id), 1)
    await asyncio.wait_for(worker.started.wait(), 1)
    status = await client.back_brain_task_status(request.conversation_id, accepted.job_id)
    assert status["status"] == "running" and status["source_current"] is True
    assert (await client.list_back_brain_tasks(request.conversation_id))["tasks"][0] == status
    queue = core.events.subscribe()
    cancelled = await client.cancel_back_brain_task(request.conversation_id, accepted.job_id)
    assert cancelled["status"] == "cancelled" and cancelled["cancellation"] == "confirmed"
    assert worker.cancels == [accepted.job_id]
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    core.events.unsubscribe(queue)
    assert sum(event.message_type == "job.cancelled" for event in events) == 1


@pytest.mark.parametrize("mutation", ["text", "command", "source", "version_bool", "null_source", "scope", "duplicate_json", "nan", "overflow", "oversize", "conversation", "query"])
async def test_strict_ingress_refuses_without_reserved_turn_or_job(protocol, mutation):
    core, worker, client = protocol
    request, admission = await admitted(core)
    body = BackBrainSubmitRequest(request.conversation_id, admission.correlation_id).to_payload()
    url = client.base_url + f"/v1/conversations/{request.conversation_id}/back-brain/tasks"
    if mutation in {"text", "command", "source"}:
        body[mutation] = "untrusted"
    elif mutation == "version_bool":
        body["schema_version"] = True
    elif mutation == "null_source":
        body["source_correlation_id"] = None
    elif mutation == "scope":
        body["scope"] = "arbitrary_shell"
    elif mutation == "conversation":
        body["conversation_id"] = "another-conversation"
    elif mutation == "oversize":
        body["source_correlation_id"] = "x" * 17000
    elif mutation == "query":
        url += "?extra=1"
    encoded = json.dumps(body)
    if mutation == "duplicate_json":
        encoded = encoded[:-1] + ',"schema_version":1}'
    elif mutation == "nan":
        encoded = encoded.replace('"schema_version": 1', '"schema_version": NaN')
    elif mutation == "overflow":
        encoded = encoded.replace('"schema_version": 1', '"schema_version": 1e999')
    session = await client._http()
    async with session.post(url, headers=client.headers, data=encoded) as response:
        assert response.status == 400
    assert await core.state.list_jobs() == () and worker.calls == []
    assert "backend_dispatch_reserved" not in (await core.state.get_turn(admission.turn_id)).metadata


async def test_auth_cross_conversation_and_strict_cancel_body(protocol):
    core, worker, client = protocol
    request, admission = await admitted(core)
    session = await client._http()
    root = client.base_url + f"/v1/conversations/{request.conversation_id}/back-brain/tasks"
    async with session.post(root, json=BackBrainSubmitRequest(request.conversation_id, admission.correlation_id).to_payload()) as response:
        assert response.status == 401
    accepted = await client.submit_back_brain_task(request.conversation_id, source_correlation_id=admission.correlation_id)
    other = await core.conversations.create()
    with pytest.raises(CoreProtocolError) as error:
        await client.cancel_back_brain_task(other.id, accepted.job_id)
    assert error.value.status == 404
    async with session.post(root + f"/{accepted.job_id}/cancel", headers=client.headers, json={"schema_version": 1, "command": "stop all"}) as response:
        assert response.status == 400
    assert not worker.cancels


@pytest.mark.parametrize("query", ["limit=0", "limit=33", "limit=1e999", "limit=-1", "limit=1&limit=2", "extra=1", "limit=" + "9" * 5000])
async def test_list_rejects_invalid_or_overflow_limits(protocol, query):
    core, _, client = protocol
    request, _ = await admitted(core)
    session = await client._http()
    async with session.get(client.base_url + f"/v1/conversations/{request.conversation_id}/back-brain/tasks?{query}", headers=client.headers) as response:
        assert response.status == 400


async def test_protocol_version_and_health_block_new_submissions(protocol):
    core, worker, client = protocol
    request, admission = await admitted(core)
    session = await client._http()
    root = client.base_url + f"/v1/conversations/{request.conversation_id}/back-brain/tasks"
    body = BackBrainSubmitRequest(request.conversation_id, admission.correlation_id).to_payload()
    async with session.post(root, headers={**client.headers, "X-Jarvis-Protocol": "999"}, json=body) as response:
        assert response.status == 426
    core.health.ready = False
    async with session.post(root, headers=client.headers, json=body) as response:
        assert response.status == 503
    assert await core.state.list_jobs() == () and worker.calls == []


@pytest.mark.parametrize("text", ["", "   ", "x" * 16385, "\ud800"])
def test_result_rejects_empty_oversize_and_invalid_unicode(text):
    with pytest.raises(ValueError):
        BackBrainResult(text, "controlled", "configured", None)


async def test_advisory_record_is_typed_immutable_and_cannot_acquire_authority(protocol):
    core, worker, client = protocol
    request, _ = await admitted(core)
    unavailable = await client.submit_back_brain_task(request.conversation_id, scope="speculative_analysis", session_id=request.session_id, delegation_id="delegation-a")
    assert unavailable.status == "unavailable" and unavailable.job_id is None
    references = await core.state.list_back_brain_advisories(request.conversation_id)
    assert len(references) == 1 and isinstance(references[0], BackBrainAdvisoryReference)
    with pytest.raises(ValueError, match="conflicting immutable"):
        await core.state.save_back_brain_advisory(replace(references[0], snapshot_revision=references[0].snapshot_revision + 1))
    with pytest.raises(ValueError):
        replace(references[0], authorizes_actions=True)
    with pytest.raises(ValueError):
        BackBrainAdvisoryReference.from_payload({**references[0].to_payload(), "job_id": "invented"})
    assert worker.calls == [] and await core.state.list_jobs() == ()


async def test_advisory_exact_input_and_projection_bounds(protocol):
    core, _, client = protocol
    request, _ = await admitted(core)
    await client.submit_back_brain_task(request.conversation_id, scope="speculative_analysis", session_id=request.session_id, delegation_id="bounded-ref")
    reference = (await core.state.list_back_brain_advisories(request.conversation_id))[0]
    dependency = reference.dependencies[0]
    assert dependency.text == request.text
    with pytest.raises(ValueError):
        replace(dependency, text="x" * 8193)
    with pytest.raises(ValueError):
        replace(reference, dependencies=tuple(replace(dependency, transcript_id=f"input-{index}") for index in range(9)))
    with pytest.raises(ValueError, match="16KiB"):
        replace(reference, dependencies=tuple(replace(dependency, transcript_id=f"input-{index}", text="x" * 3000) for index in range(8)))
