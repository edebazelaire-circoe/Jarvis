"""Relais du Control Center vers l'export de Core (presentation-edition-v1 Slice 03) : deux adresses, gardées, `actor` forcé à l'utilisateur."""

from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer

from jarvis.runtime.export_relay import EXPORT_TIMEOUT_S
from tests.unit.test_control_center_mcp_plugins_api import RecordingCore, _center

EXPORTS = "/api/exports"


async def client_for(tmp_path, core) -> TestClient:
    client = TestClient(TestServer(_center(tmp_path, core)._app))
    await client.start_server()
    return client


async def test_the_two_routes_relay_to_core_and_the_body_goes_through_unchanged(tmp_path):
    core = RecordingCore((201, {"export": {"file_name": "Atelier - video.mp4"}}))
    client = await client_for(tmp_path, core)
    try:
        response = await client.post(EXPORTS, data=b'{"artifact_id":"jart_x"}')
        assert response.status == 201 and (await response.json())["export"]["file_name"] == "Atelier - video.mp4"
        [call] = core.calls
        assert (call["method"], call["path"], call["body"], call["timeout_s"]) == ("POST", "/v1/exports", b'{"artifact_id":"jart_x"}',
                                                                                 EXPORT_TIMEOUT_S)
        core.calls.clear()
        response = await client.get(EXPORTS + "/root")
        assert response.status == 201  # RecordingCore answers its one canned reply
        assert core.calls[0]["method"] == "GET" and core.calls[0]["path"] == "/v1/exports/root"
    finally:
        await client.close()


async def test_core_refusals_come_back_as_they_are(tmp_path):
    core = RecordingCore((409, {"error": {"code": "export_destination_unsafe", "message": "junction"}}))
    client = await client_for(tmp_path, core)
    try:
        response = await client.post(EXPORTS, data=b'{"artifact_id":"jart_x"}')
        assert response.status == 409 and (await response.json())["error"]["code"] == "export_destination_unsafe"
    finally:
        await client.close()


async def test_the_control_center_exports_for_the_user_only_and_refuses_bad_bodies(tmp_path):
    core = RecordingCore()
    client = await client_for(tmp_path, core)
    try:
        for body in (b'{"artifact_id":"jart_x","actor":"brain"}', b"not json", b"x" * 5000):
            response = await client.post(EXPORTS, data=body)
            assert response.status == 400 and (await response.json())["error"]["code"] == "export_invalid", body[:30]
        assert (await client.post(EXPORTS + "?path=C:/", data=b"{}")).status == 400
        assert core.calls == []
    finally:
        await client.close()


async def test_every_method_is_guarded_against_foreign_origins_and_hosts(tmp_path):
    core = RecordingCore()
    client = await client_for(tmp_path, core)
    try:
        for method, path in (("GET", EXPORTS + "/root"), ("POST", EXPORTS)):
            for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                response = await client.request(method, path, headers=headers, data=b"{}" if method == "POST" else None)
                assert response.status == 403, (method, path, headers)
        assert core.calls == []
    finally:
        await client.close()


async def test_each_export_is_journaled_without_its_body(tmp_path):
    core = RecordingCore((201, {"export": {"file_name": "secret-title.mp4"}}))
    center = _center(tmp_path, core)
    client = TestClient(TestServer(center._app))
    await client.start_server()
    try:
        await client.post(EXPORTS, data=b'{"artifact_id":"jart_x","file_name":"secret-title"}')
        logged = "".join(f.read_text(encoding="utf-8", errors="replace") for f in tmp_path.rglob("*.jsonl"))
        assert "export.request.relayed" in logged and "secret-title" not in logged
    finally:
        await client.close()
