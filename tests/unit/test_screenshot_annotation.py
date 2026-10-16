"""Capture annotée : `POST /v1/artifacts/{id}/annotations` (Core) et son relais `POST /api/artifacts/{id}/annotations`.

Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 05.B ; architecture résolue §6 (D7). Chaîne réelle
(`CaptureStack` : vrai Core, vrai Control Center, source de capture d'écran **factice**, jamais l'écran du
poste). Une annotation est une NOUVELLE capture dérivée (`metadata.annotated_from`, relation `derived_from`,
même Session et même Context) ; l'original n'est jamais réécrit. Le corps est un PNG vérifié (signature,
`IHDR`, dimensions de l'original, ≤ 8 Mio) ; le relais est gardé comme toutes les routes `/api/artifacts`.
Contrat : `docs/capture.md` › *Screenshot preview and quick actions* › Annotate.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import zlib

import aiohttp
import pytest

from jarvis.adapters.fake_capture import FakeOneShotSource
from jarvis.core.screenshot_annotation import MAX_ANNOTATION_BYTES, png_size
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery
from jarvis.domain.capture import CaptureChannel
from tests.fakes.capture_stack import TOKEN, CaptureStack

W, H = 64, 36


def png(width: int, height: int, shade: int = 0) -> bytes:
    rows = b"".join(b"\x00" + bytes((x * 4 + shade) % 256 for x in range(width) for _ in range(3)) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


ORIGINAL = png(W, H)
ANNOTATED = png(W, H, shade=90)


@pytest.fixture
async def stack(tmp_path):
    async with CaptureStack(tmp_path) as opened:
        opened.core.captures._sources._one_shot[CaptureChannel.SCREEN] = (
            lambda: FakeOneShotSource(data=ORIGINAL, width=W, height=H))
        yield opened


async def _shot(stack) -> str:
    status, body, _ = await stack.call("POST", "/api/captures/screenshot", json={})
    assert status == 201, body
    return body["artifact"]["artifact_id"]


async def _post(stack, artifact_id: str, data: bytes, *, content_type: str = "image/png", headers: dict | None = None):
    return await stack.call("POST", f"/api/artifacts/{artifact_id}/annotations", data=data,
                            headers={"Content-Type": content_type, **(headers or {})})


async def _screenshots(stack) -> list:
    return list((await stack.core.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.SCREENSHOT,), limit=50))).items)


def _payload(stack, artifact) -> bytes:
    return Path(stack.core.artifacts.payload_path(artifact)).read_bytes()


async def test_creates_new_derived_screenshot_original_untouched(stack):
    original_id = await _shot(stack)
    before = await stack.core.artifacts.get(original_id)
    before_bytes = _payload(stack, before)
    status, body, _ = await _post(stack, original_id, ANNOTATED)
    assert status == 201, body
    assert body["annotated_from"] == original_id
    derived_id = body["artifact"]["artifact_id"]
    assert derived_id != original_id and body["artifact"]["kind"] == "screenshot" and body["artifact"]["state"] == "complete"
    assert str(stack.data_root) not in str(body) and "payload_ref" not in body["artifact"], "never a path"
    derived = await stack.core.artifacts.get(derived_id)
    assert derived.metadata["annotated_from"] == original_id and derived.source == "annotation"
    assert (derived.jarvis_session_id, derived.context_id) == (before.jarvis_session_id, before.context_id)
    assert (derived.width, derived.height, derived.mime_type) == (W, H, "image/png")
    assert _payload(stack, derived) == ANNOTATED and derived.size_bytes == len(ANNOTATED)
    status, relations, _ = await stack.call("GET", f"/api/artifacts/{derived_id}/relations?direction=origins")
    assert status == 200 and [(r["relation"], r["origin_artifact_id"]) for r in relations["origins"]] == [
        ("derived_from", original_id)]
    after = await stack.core.artifacts.get(original_id)
    assert after == before, "the original row is untouched"
    assert hashlib.sha256(_payload(stack, after)).digest() == hashlib.sha256(before_bytes).digest() == hashlib.sha256(
        ORIGINAL).digest(), "the original bytes are untouched"
    # L'original ne peut plus être supprimé seul : la dérivée en dépend (refus codé, montré par l'aperçu).
    status, refused, _ = await stack.call("DELETE", f"/api/artifacts/{original_id}")
    assert (status, refused["error"]["code"]) == (409, "artifact_has_dependents")
    # Une annotation d'annotation est permise (même règle), l'originale reste intacte.
    status, again, _ = await _post(stack, derived_id, png(W, H, shade=200))
    assert status == 201 and again["annotated_from"] == derived_id
    trace = [row for row in stack.trace() if (row.get("data") or {}).get("action") == "artifact_annotate"]
    assert [row["data"]["status"] for row in trace] == [201, 201]


async def test_rejects_non_png_oversize_and_dimension_mismatch(stack):
    original_id = await _shot(stack)
    recording = await stack.core.artifacts.create(kind=ArtifactKind.SCREEN_RECORDING, source="test", payload_name="screen.mp4")
    pending = await stack.core.artifacts.create(kind=ArtifactKind.SCREENSHOT, source="test", payload_name="screenshot.png")
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 200
    broken = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    cases = [
        (original_id, jpeg, "image/png", 415, "annotation_not_png"),
        (original_id, broken, "image/png", 415, "annotation_not_png"),
        (original_id, ANNOTATED, "image/jpeg", 415, "annotation_not_png"),
        (original_id, png(W + 1, H), "image/png", 400, "annotation_dimensions_mismatch"),
        (original_id, png(W, H * 2), "image/png", 400, "annotation_dimensions_mismatch"),
        (original_id, b"", "image/png", 400, "annotation_empty"),
        (original_id, ANNOTATED + b"\x00" * (MAX_ANNOTATION_BYTES + 1 - len(ANNOTATED)), "image/png", 413, "annotation_too_large"),
        (recording.artifact_id, ANNOTATED, "image/png", 400, "annotation_source_invalid"),
        (pending.artifact_id, ANNOTATED, "image/png", 409, "annotation_source_not_ready"),
        ("jart_" + "0" * 32, ANNOTATED, "image/png", 404, "artifact_not_found"),
        ("not-an-artifact", ANNOTATED, "image/png", 400, "invalid_artifact"),
    ]
    for artifact_id, data, content_type, status, code in cases:
        got, body, _ = await _post(stack, artifact_id, data, content_type=content_type)
        assert (got, body["error"]["code"]) == (status, code), (artifact_id[:12], len(data), content_type, body)
    # Core lui-même, sans le relais : même borne, lue en flux (la borne du corps entier du serveur est 6 Mio).
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "image/png"}
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{stack.core_url}/v1/artifacts/{original_id}/annotations", headers=headers,
                             data=b"\x89PNG" + b"\x00" * (MAX_ANNOTATION_BYTES + 10)) as response:
            assert response.status == 413 and (await response.json())["error"]["code"] == "annotation_too_large"
        big = png(W, H) + b"\x00" * (7 * 1024 * 1024)  # 7 Mio : au-dessus de la borne du serveur, sous celle de l'annotation
        async with http.post(f"{stack.core_url}/v1/artifacts/{original_id}/annotations", headers=headers, data=big) as response:
            assert response.status == 201, await response.text()
    shots = await _screenshots(stack)
    assert sorted(a.source for a in shots) == ["annotation", "capture.screen", "test"], "only the valid annotation was written"
    assert png_size(ORIGINAL) == (W, H)
    original = await stack.core.artifacts.get(original_id)
    assert _payload(stack, original) == ORIGINAL


async def test_loopback_guard(stack):
    original_id = await _shot(stack)
    foreign = [
        {"Origin": "http://evil.example"},
        {"Origin": "http://127.0.0.1:1"},
        {"Host": "evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ]
    for headers in foreign:
        status, body, text = await _post(stack, original_id, ANNOTATED, headers=headers)
        assert status == 403, (headers, status, text[:200])
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{stack.core_url}/v1/artifacts/{original_id}/annotations",
                             headers={"Content-Type": "image/png"}, data=ANNOTATED) as response:
            assert response.status == 401, "Core requires its bearer token"
    assert [a.artifact_id for a in await _screenshots(stack)] == [original_id], "nothing was written"
