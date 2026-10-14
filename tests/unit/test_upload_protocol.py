"""Pièce jointe du chat de bout en bout (chat Slice 07, `docs/chat.md` › *Attachments*).

Chaîne réelle : navigateur simulé (multipart **en flux**, octets générés) →
vrai `ControlCenter` (`POST /api/chat/uploads`, garde `/api/chat`) →
`CoreSessionTransport` → `LocalProtocolServer` (`PUT /v1/uploads/…`) → Core
(SQLite et payloads sous `tmp_path`). Aucun fichier n'est alloué en entier.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid

import aiohttp
import pytest

from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactState
from tests.fakes.capture_stack import TOKEN, CaptureStack, until

BOUNDARY = "jarvis-test-boundary-7d1f"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 50 + b"%%EOF\n"


async def generated(total: int, *, seed: int = 3, piece: int = 50_000, fail_after: int | None = None):
    sent = 0
    while sent < total:
        if fail_after is not None and sent >= fail_after:
            raise ConnectionResetError("browser tab closed")
        size = min(piece, total - sent)
        yield bytes((seed + sent + i) % 251 for i in range(size))
        sent += size


def digest_of(total: int, *, seed: int = 3, piece: int = 50_000) -> str:
    digest, sent = hashlib.sha256(), 0
    while sent < total:
        size = min(piece, total - sent)
        digest.update(bytes((seed + sent + i) % 251 for i in range(size)))
        sent += size
    return digest.hexdigest()


async def as_stream(data: bytes):
    yield data


def multipart(upload_id: str, filename: str, content_type: str, body):
    """Corps multipart du navigateur, produit en flux (nom de fichier en UTF-8 brut, comme un navigateur)."""

    async def gen():
        yield (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"client_upload_id\"\r\n\r\n{upload_id}\r\n"
               f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
               f"Content-Type: {content_type}\r\n\r\n").encode("utf-8")
        async for chunk in body:
            yield chunk
        yield f"\r\n--{BOUNDARY}--\r\n".encode()

    return gen()


HEADERS = {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"}


@pytest.fixture
async def stack(tmp_path):
    async with CaptureStack(tmp_path) as opened:
        yield opened


async def upload(stack, filename: str, content_type: str, body, *, upload_id: str | None = None, headers=None):
    return await stack.call("POST", "/api/chat/uploads", data=multipart(upload_id or str(uuid.uuid4()), filename,
                                                                         content_type, body),
                            headers={**HEADERS, **(headers or {})})


async def uploads_of(stack) -> list:
    return list((await stack.core.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.UPLOAD,), limit=50))).items)


async def test_two_files_one_after_the_other_through_the_control_center(stack):
    status, png, text = await upload(stack, "capture d’écran été.png", "image/png", as_stream(PNG))
    assert status == 201, text
    assert png["ok"] is True and png["state"] == "complete" and png["replayed"] is False
    assert (png["original_name"], png["mime_type"], png["size_bytes"]) == ("capture d’écran été.png", "image/png",
                                                                           len(PNG))
    assert png["brain_readable"] is True and png["artifact_id"].startswith("jart_up_")
    status, pdf, _ = await upload(stack, "rapport.pdf", "application/pdf", as_stream(PDF))
    assert status == 201 and pdf["mime_type"] == "application/pdf"
    root = str(stack.core.artifacts._payloads.root())
    for answer in (png, pdf):
        assert set(answer) == {"ok", "artifact_id", "original_name", "mime_type", "size_bytes", "state", "replayed",
                               "brain_readable"}
        assert root not in json.dumps(answer) and "upload." not in json.dumps(answer)
    assert len(await uploads_of(stack)) == 2


async def test_a_file_above_six_mib_goes_through_as_a_stream(stack):
    total = 7 * 1024 * 1024 + 123
    status, body, text = await upload(stack, "gros.bin", "application/octet-stream", generated(total))
    assert status == 201, text
    artifact = await stack.core.artifacts.get(body["artifact_id"])
    assert (artifact.size_bytes, artifact.metadata["sha256"]) == (total, digest_of(total))
    assert body["brain_readable"] is False


async def test_the_bound_is_held_through_the_relay(stack, monkeypatch):
    monkeypatch.setenv("JARVIS_UPLOAD_MAX_BYTES", "100000")
    status, body, _ = await upload(stack, "x.bin", "application/octet-stream", generated(2_000_000))
    assert status == 413 and body["code"] == "upload_too_large" and body["core_status"] == 413
    [artifact] = await uploads_of(stack)
    assert (artifact.state, artifact.error_code) == (ArtifactState.FAILED, "upload_too_large")
    assert not (stack.core.artifacts._payloads.root() / artifact.artifact_id).exists()


async def test_an_announced_body_above_the_bound_is_refused_by_the_control_center(stack, monkeypatch):
    monkeypatch.setenv("JARVIS_UPLOAD_MAX_BYTES", "1000")
    status, body, _ = await stack.call("POST", "/api/chat/uploads", data=b"x" * 70_000, headers=HEADERS)
    assert status == 413 and body["code"] == "upload_too_large" and body["core_status"] is None
    assert await uploads_of(stack) == []


async def test_replay_and_conflict_codes_are_relayed(stack):
    upload_id = str(uuid.uuid4())
    first = await upload(stack, "a.png", "image/png", as_stream(PNG), upload_id=upload_id)
    again = await upload(stack, "a.png", "image/png", as_stream(PNG), upload_id=upload_id)
    other = await upload(stack, "a.png", "image/png", as_stream(PNG[:-1] + b"!"), upload_id=upload_id)
    assert (first[0], again[0], again[1]["replayed"]) == (201, 200, True)
    assert again[1]["artifact_id"] == first[1]["artifact_id"]
    assert (other[0], other[1]["code"], other[1]["core_status"]) == (409, "upload_conflict", 409)
    empty = await upload(stack, "vide.txt", "text/plain", as_stream(b""))
    assert (empty[0], empty[1]["code"]) == (400, "upload_empty")
    assert len(await uploads_of(stack)) == 1


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"},
                                     {"Sec-Fetch-Site": "same-site"}, {"Host": "evil.example"}])
async def test_the_chat_guard_refuses_foreign_uploads(stack, headers):
    status, _, _ = await upload(stack, "a.png", "image/png", as_stream(PNG), headers=headers)
    assert status == 403
    assert await uploads_of(stack) == []


@pytest.mark.parametrize("data,headers,code,status", [
    (b"{}", {"Content-Type": "application/json"}, "invalid_content_type", 415),
    (b"--" + BOUNDARY.encode() + b"--\r\n", HEADERS, "invalid_request", 400),
])
async def test_malformed_requests_never_reach_core(stack, data, headers, code, status):
    got, body, _ = await stack.call("POST", "/api/chat/uploads", data=data, headers=headers)
    assert (got, body["code"]) == (status, code)


async def test_fields_out_of_order_or_a_bad_upload_id_are_refused(stack):
    async def swapped():
        yield (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.png\"\r\n\r\n").encode()
        yield PNG + f"\r\n--{BOUNDARY}--\r\n".encode()

    status, body, _ = await stack.call("POST", "/api/chat/uploads", data=swapped(), headers=HEADERS)
    assert (status, body["code"]) == (400, "invalid_request")
    status, body, _ = await upload(stack, "a.png", "image/png", as_stream(PNG), upload_id="../../x")
    assert (status, body["code"]) == (400, "invalid_request")
    assert await uploads_of(stack) == []


async def test_a_browser_that_stops_mid_file_leaves_a_failed_artifact_and_no_partial(stack):
    with pytest.raises(Exception):  # noqa: B017 - the test client sees its own generator fail
        await upload(stack, "coupé.bin", "application/octet-stream", generated(3_000_000, fail_after=1_000_000))

    async def failed():
        items = await uploads_of(stack)
        return bool(items) and items[0].state is ArtifactState.FAILED

    await until(failed)
    [artifact] = await uploads_of(stack)
    assert artifact.error_code == "upload_incomplete"
    assert not (stack.core.artifacts._payloads.root() / artifact.artifact_id).exists()


async def test_core_route_needs_the_token_and_a_closed_query(stack):
    url = f"{stack.core_url}/v1/uploads/{uuid.uuid4()}?purpose=chat"
    async with aiohttp.ClientSession() as http:
        async with http.put(url, data=PNG) as response:
            assert response.status == 401
        auth = {"Authorization": f"Bearer {TOKEN}"}
        async with http.put(url + "&debug=1", data=PNG, headers=auth) as response:
            assert response.status == 400 and (await response.json())["error"]["code"] == "invalid_request"
        async with http.put(url.replace("purpose=chat", "purpose=board"), data=PNG, headers=auth) as response:
            assert response.status == 400
        async with http.put(url, data=PNG, headers={**auth, "X-Jarvis-Upload-Name": "%C3%A9t%C3%A9.png"}) as response:
            body = await response.json()
            assert response.status == 201 and body["original_name"] == "été.png" and "path" not in body
    assert len(await uploads_of(stack)) == 1


async def test_the_journal_has_ids_sizes_and_codes_never_the_name_nor_bytes(stack):
    status, body, _ = await upload(stack, "dossier-médical-confidentiel.png", "image/png", as_stream(PNG))
    assert status == 201
    await upload(stack, "dossier-médical-confidentiel.txt", "text/plain", as_stream(b""))
    text = json.dumps(stack.trace(), ensure_ascii=False)
    assert "confidentiel" not in text and "médical" not in text
    relayed = [entry for entry in stack.trace() if entry.get("kind") == "chat.upload.relayed"]
    assert [entry["data"]["status"] for entry in relayed] == [201, 400]
    assert relayed[0]["data"]["artifact_id"] == body["artifact_id"] and relayed[1]["data"]["code"] == "upload_empty"


async def test_brain_readability_follows_the_foreground_agent(stack):
    stack.center._agent_id = "codex"
    status, body, _ = await upload(stack, "a.pdf", "application/pdf", as_stream(PDF))
    assert status == 201 and body["brain_readable"] is False
    assert (await stack.core.artifacts.get(body["artifact_id"])).metadata["brain_readable"] is False


async def test_no_session_means_no_upload(stack):
    await asyncio.sleep(0)
    stack.core.sessions._repo.current_session = _no_session  # type: ignore[method-assign]
    status, body, _ = await upload(stack, "a.png", "image/png", as_stream(PNG))
    assert (status, body["code"]) == (404, "session_not_found")


async def _no_session():
    return None
