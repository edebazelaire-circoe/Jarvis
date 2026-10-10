"""Relais du Control Center vers le rendu de Core (Remotion Slice 16) : cinq adresses seulement, gardées, erreurs de Core rendues telles quelles."""

from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer

from jarvis.runtime.presentation_render_relay import CREATE_TIMEOUT_S
from jarvis.runtime.remotion_studio_relay import READ_TIMEOUT_S, SHORT_TIMEOUT_S
from tests.unit.test_control_center_mcp_plugins_api import RecordingCore, _center

RENDER = "/api/local-capabilities/remotion/render"
CORE = "/v1/local-capabilities/remotion/render"
JOB = "rj_0123456789ab"


async def client_for(tmp_path, core) -> TestClient:
    client = TestClient(TestServer(_center(tmp_path, core)._app))
    await client.start_server()
    return client


async def test_each_route_relays_to_the_matching_core_route_with_the_right_deadline(tmp_path):
    core = RecordingCore((200, {"job": {"state": "queued", "job_id": JOB}}))
    client = await client_for(tmp_path, core)
    try:
        for method, path, core_path, timeout in (
                ("GET", RENDER, CORE, READ_TIMEOUT_S), ("GET", RENDER + "/jobs", CORE + "/jobs", READ_TIMEOUT_S),
                ("GET", f"{RENDER}/jobs/{JOB}", f"{CORE}/jobs/{JOB}", READ_TIMEOUT_S),
                ("POST", RENDER + "/jobs", CORE + "/jobs", CREATE_TIMEOUT_S),
                ("POST", f"{RENDER}/jobs/{JOB}/cancel", f"{CORE}/jobs/{JOB}/cancel", SHORT_TIMEOUT_S)):
            core.calls.clear()
            response = await client.request(method, path, **({"data": b'{"snapshot_id":"s","format":"mp4"}'} if method == "POST" else {}))
            assert response.status == 200, (method, path)
            [call] = core.calls
            assert (call["method"], call["path"], call["timeout_s"]) == (method, core_path, timeout)
    finally:
        await client.close()


async def test_the_body_goes_through_unchanged_and_core_errors_are_returned_as_they_are(tmp_path):
    core = RecordingCore((409, {"error": {"code": "presentation_render_runtime_unavailable", "message": "install first"}}))
    client = await client_for(tmp_path, core)
    try:
        response = await client.post(RENDER + "/jobs", data=b'{"snapshot_id":"x","format":"still"}')
        assert response.status == 409 and (await response.json())["error"]["code"] == "presentation_render_runtime_unavailable"
        assert core.calls[0]["body"] == b'{"snapshot_id":"x","format":"still"}'
    finally:
        await client.close()


async def test_nothing_else_is_relayed_and_queries_are_refused(tmp_path):
    core = RecordingCore()
    client = await client_for(tmp_path, core)
    try:
        for method, path, status in (("DELETE", RENDER + "/jobs", 405), ("PUT", RENDER + "/jobs", 405), ("GET", f"{RENDER}/jobs/{JOB}/cancel", 405),
                                     ("POST", f"{RENDER}/jobs/{JOB}", 405), ("GET", RENDER + "/jobs?limit=3", 400), ("GET", RENDER + "?x=1", 400),
                                     ("POST", RENDER + "/jobs?x=1", 400), ("POST", RENDER + "/other", 404)):
            response = await client.request(method, path)
            assert response.status == status, (method, path, response.status)
            assert (await response.json())["error"]["code"] in {"not_found", "method_not_allowed", "presentation_render_invalid"}
        assert (await client.post(RENDER + "/jobs", data=b"x" * 9000)).status == 400
        assert core.calls == []
    finally:
        await client.close()


async def test_every_method_is_guarded_against_foreign_origins_and_hosts(tmp_path):
    core = RecordingCore()
    client = await client_for(tmp_path, core)
    try:
        for method, path in (("GET", RENDER), ("GET", RENDER + "/jobs"), ("POST", RENDER + "/jobs"), ("POST", f"{RENDER}/jobs/{JOB}/cancel")):
            for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                response = await client.request(method, path, headers=headers, data=b"{}" if method == "POST" else None)
                assert response.status == 403, (method, path, headers)
        assert core.calls == []
    finally:
        await client.close()


async def test_each_write_is_journaled_without_its_body(tmp_path):
    core = RecordingCore((202, {"job": {"state": "queued", "job_id": JOB}}))
    center = _center(tmp_path, core)
    client = TestClient(TestServer(center._app))
    await client.start_server()
    try:
        await client.post(RENDER + "/jobs", data=b'{"snapshot_id":"secret-looking","format":"mp4"}')
        logged = "".join(f.read_text(encoding="utf-8", errors="replace") for f in tmp_path.rglob("*.jsonl"))
        assert "presentation_render.relayed" in logged and "rj_0123456789ab" in logged and "secret-looking" not in logged
    finally:
        await client.close()
