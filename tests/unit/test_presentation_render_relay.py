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


# ------------------------------------------------------------------ a render larger than 8 MiB opens from the Board (an img / a link sends no Range)

import hashlib  # noqa: E402
import os  # noqa: E402

from jarvis.domain.artifacts import ArtifactKind  # noqa: E402
from tests.fakes.capture_stack import CaptureStack  # noqa: E402

MIB = 1024 * 1024


async def derivative(stack, kind, name, mime, data):
    artifact = await stack.core.artifacts.create(kind=kind, source="presentation.studio", payload_name=name, mime_type=mime)
    await stack.core.artifacts.store_payload(artifact.artifact_id, data)
    return artifact.artifact_id


async def test_a_big_still_and_a_big_pdf_are_streamed_whole_through_the_relay_without_a_range(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + os.urandom(9 * MIB + 12345)
    pdf = b"%PDF-1.4\n" + os.urandom(17 * MIB + 7) + b"\n%%EOF\n"
    async with CaptureStack(tmp_path) as stack:
        still = await derivative(stack, ArtifactKind.PRESENTATION_STILL, "still.png", "image/png", png)
        document = await derivative(stack, ArtifactKind.PRESENTATION_PDF, "render.pdf", "application/pdf", pdf)
        for artifact_id, data, mime in ((still, png, "image/png"), (document, pdf, "application/pdf")):
            response = await stack.cc.get(f"/api/artifacts/{artifact_id}/payload")  # what <img src> and the PDF link do: no Range header
            body = await response.read()
            assert response.status == 200 and response.headers["Content-Length"] == str(len(data)) and response.headers["Content-Type"] == mime
            assert hashlib.sha256(body).hexdigest() == hashlib.sha256(data).hexdigest() and len(body) > 8 * MIB
            assert response.headers["X-Content-Type-Options"] == "nosniff" and response.headers["Accept-Ranges"] == "bytes"
            part = await stack.cc.get(f"/api/artifacts/{artifact_id}/payload", headers={"Range": "bytes=100-199"})  # ranges are unchanged
            assert part.status == 206 and await part.read() == data[100:200]
            tail = await stack.cc.get(f"/api/artifacts/{artifact_id}/payload", headers={"Range": f"bytes={len(data) - 50}-"})
            assert tail.status == 206 and await tail.read() == data[-50:]


async def test_a_payload_that_fits_one_block_is_still_answered_in_one_piece(tmp_path):
    small = b"\x89PNG\r\n\x1a\n" + os.urandom(1000)
    async with CaptureStack(tmp_path) as stack:
        artifact_id = await derivative(stack, ArtifactKind.PRESENTATION_STILL, "still.png", "image/png", small)
        response = await stack.cc.get(f"/api/artifacts/{artifact_id}/payload")
        assert response.status == 200 and await response.read() == small and "Transfer-Encoding" not in response.headers


async def test_a_pending_or_unknown_derivative_keeps_its_typed_refusal_and_a_dead_core_mid_stream_truncates_loudly(tmp_path, monkeypatch):
    big = b"\x89PNG\r\n\x1a\n" + os.urandom(20 * MIB)
    async with CaptureStack(tmp_path) as stack:
        artifact_id = await derivative(stack, ArtifactKind.PRESENTATION_STILL, "still.png", "image/png", big)
        status, body, _ = await stack.call("GET", "/api/artifacts/jart_unknown/payload")
        assert status == 404 and body["error"]["code"] == "artifact_not_found"
        real = stack.sessions.forward_bytes
        calls = {"n": 0}

        async def flaky(path, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 3:  # the 413, the first block, then Core goes away
                raise ConnectionError("core went away")
            return await real(path, **kwargs)

        monkeypatch.setattr(stack.sessions, "forward_bytes", flaky)
        got = b""
        try:
            response = await stack.cc.get(f"/api/artifacts/{artifact_id}/payload")
            got = await response.read()
            truncated = len(got) != len(big)
        except Exception:  # noqa: BLE001 - a connection closed mid-body surfaces as a client error: that IS the loud truncation
            truncated = True
        assert truncated, "a partial file is never presented as a whole one"
        logged = "".join(f.read_text(encoding="utf-8", errors="replace") for f in tmp_path.rglob("*.jsonl"))
        assert "payload_stream_failed" in logged
