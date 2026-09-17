"""Capture visuelle exceptionnelle de la scène (handoff jarvis-constellation-scene-runtime, Slice 09, partie 2).

Canal décidé par le PM : `scene_capture` (cerveau) → `POST /v1/scene/captures`
(Core) → `capture_request` dans le long-poll des patchs → page meneuse visible →
`POST /api/scene/captures/<id>` (Control Center) → `PUT /v1/scene/captures/<id>`
(Core) → fichier sous `runtime/scene-captures/` → réponse au cerveau (chemin et
image). Ce qui doit tenir :

- PNG complet, ≤ 2 MiB, ≤ 1280×720, identifiant aléatoire à usage unique, non échu ;
- une seule capture en attente (`capture_busy`), `no_visible_page` à l'échéance ;
- le long-poll n'en est pas dérangé : demande donnée au long-poll seulement,
  redonnée au plus une fois par seconde, jamais à une lecture courte ;
- rétention : 5 fichiers, 24 h, au démarrage et à chaque capture ;
- route du Control Center : origine, taille, forme, identifiant ; aucune route n'en demande ;
- outil du cerveau : interrupteur, refus lisibles, résultat = texte + image.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import struct
import time
import zlib

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.adapters.file_scene_captures import CAPTURE_NAME, FileSceneCaptureStore
from jarvis.core.scene_capture import SceneCaptureBroker, SceneCaptureError
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.scene_capture import (
    CAPTURE_KEEP_FILES,
    MAX_CAPTURE_BYTES,
    check_capture_id,
    png_dimensions,
)
from jarvis.protocol.client import CoreProtocolError
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import claude_local
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.display_mcp import DisplayToolError, SceneDisplayTools, build_server, scene_gate_reader
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView, decode_patches_response
from tests.integration.test_scene_transport import CoreProcess


def png(width: int = 64, height: int = 36, *, color: bytes = b"\x10\x20\x30") -> bytes:
    raw = b"".join(b"\x00" + color * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------ domaine et fichiers


def test_png_validation_accepts_only_complete_bounded_pngs():
    assert png_dimensions(png(1280, 720)) == (1280, 720)
    good = png(10, 10)
    cases = {
        "signature": b"GIF89a" + good[6:],
        "truncated": good[:-12],
        "ihdr crc": good[:29] + b"\x00\x00\x00\x00" + good[33:],
        "too wide": png(1281, 10),
        "too tall": png(10, 721),
        "garbage": b"x" * 100,
        "empty": b"",
    }
    for name, data in cases.items():
        with pytest.raises(ValueError):
            png_dimensions(data)
        assert name
    with pytest.raises(ValueError, match="exceeds"):
        png_dimensions(good + b"\x00" * MAX_CAPTURE_BYTES)
    assert check_capture_id("a" * 32) == "a" * 32
    for bad in ("short", "a" * 65, "a" * 31 + "/", None, "a" * 31 + " "):
        with pytest.raises(ValueError):
            check_capture_id(bad)


def test_the_store_names_files_without_user_content_and_prunes_to_five_and_24h(tmp_path):
    store = FileSceneCaptureStore(tmp_path / "scene-captures")
    now = time.time()
    saved = [store.save(png(), now_epoch_s=now + index) for index in range(7)]
    assert all(CAPTURE_NAME.match(item.name) and Path(item.path).parent == store.directory for item in saved)
    assert len({item.name for item in saved}) == 7 and saved[0].size == len(png())
    other = store.directory / "notes.txt"
    other.write_text("à garder", encoding="utf-8")
    for index, item in enumerate(saved):
        os.utime(item.path, (now - 100 + index, now - 100 + index))
    assert store.prune(now_epoch_s=now, keep=5, max_age_s=24 * 3600) == 2
    left = sorted(p.name for p in store.directory.iterdir() if CAPTURE_NAME.match(p.name))
    assert left == sorted(item.name for item in saved[2:]) and other.exists()
    old = Path(saved[2].path)
    os.utime(old, (now - 25 * 3600, now - 25 * 3600))
    assert store.prune(now_epoch_s=now, keep=5, max_age_s=24 * 3600) == 1 and not old.exists()
    assert list(store.directory.glob("*.tmp")) == [] and FileSceneCaptureStore(tmp_path / "absent").prune(now_epoch_s=now, keep=5, max_age_s=1) == 0


# ------------------------------------------------------------------ courtier


class MemoryStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.saved: list[bytes] = []
        self.prunes = 0
        self.fail = fail

    def save(self, data: bytes, *, now_epoch_s: float):
        if self.fail:
            raise PermissionError("disk")
        from jarvis.ports.scene import StoredSceneCapture

        self.saved.append(data)
        return StoredSceneCapture(name=f"capture-{len(self.saved)}.png", path=f"/tmp/capture-{len(self.saved)}.png", size=len(data))

    def prune(self, *, now_epoch_s: float, keep: int, max_age_s: float) -> int:
        self.prunes += 1
        return 0


async def test_the_broker_serves_one_capture_to_a_long_poll_once_per_second_and_is_single_use():
    store = MemoryStore()
    broker = SceneCaptureBroker(store, deadline_s=2.0, redeliver_s=0.2)
    await broker.start()
    assert store.prunes == 1 and broker.delivery_due() is None and broker.deliver(long_poll=True) is None
    wake = broker.wake_event()
    request = asyncio.ensure_future(broker.request())
    await asyncio.sleep(0)
    assert wake.is_set() and broker.delivery_due() == 0
    with pytest.raises(SceneCaptureError) as busy:
        await broker.request()
    assert (busy.value.code, busy.value.status) == ("capture_busy", 409)
    assert broker.deliver(long_poll=False) is None  # une lecture courte (suiveur) ne la reçoit pas
    delivered = broker.deliver(long_poll=True)
    assert set(delivered) == {"id", "remaining_ms"} and 0 < delivered["remaining_ms"] <= 2000
    assert broker.deliver(long_poll=True) is None and 0 < broker.delivery_due() <= 0.2  # pas de boucle serrée
    await asyncio.sleep(0.25)
    assert broker.deliver(long_poll=True)["id"] == delivered["id"]  # redonnée (passation de meneur)
    with pytest.raises(SceneCaptureError) as garbage:
        await broker.complete(delivered["id"], b"not a png")
    assert (garbage.value.code, garbage.value.status) == ("invalid_png", 400) and not request.done()
    result = await broker.complete(delivered["id"], png(1280, 720))
    assert (await request) == result and result["width"] == 1280 and result["height"] == 720 and store.prunes == 2
    with pytest.raises(SceneCaptureError) as used:
        await broker.complete(delivered["id"], png())
    assert (used.value.code, used.value.status) == ("unknown_capture", 404)
    assert broker.delivery_due() is None


async def test_no_page_answers_before_the_deadline_then_a_late_upload_is_refused():
    broker = SceneCaptureBroker(MemoryStore(), deadline_s=0.2)
    request = asyncio.ensure_future(broker.request())
    await asyncio.sleep(0)
    capture_id = broker.deliver(long_poll=True)["id"]
    with pytest.raises(SceneCaptureError) as timeout:
        await request
    assert (timeout.value.code, timeout.value.status) == ("no_visible_page", 504)
    with pytest.raises(SceneCaptureError) as late:
        await broker.complete(capture_id, png())
    assert late.value.code == "unknown_capture"
    # La suivante est acceptée (plus rien en attente).
    follow = asyncio.ensure_future(broker.request())
    await asyncio.sleep(0)
    broker.close()
    with pytest.raises(SceneCaptureError) as cancelled:
        await follow
    assert cancelled.value.code == "capture_cancelled"
    with pytest.raises(SceneCaptureError) as closed:
        await broker.request()
    assert closed.value.code == "capture_unavailable"


async def test_a_store_failure_fails_the_capture_clearly():
    broker = SceneCaptureBroker(MemoryStore(fail=True), deadline_s=2.0)
    request = asyncio.ensure_future(broker.request())
    await asyncio.sleep(0)
    capture_id = broker.deliver(long_poll=True)["id"]
    with pytest.raises(SceneCaptureError) as failed:
        await broker.complete(capture_id, png())
    assert (failed.value.code, failed.value.status) == ("capture_store_failed", 500) and "PermissionError" in str(failed.value)
    with pytest.raises(SceneCaptureError):
        await request
    assert (await SceneCaptureBroker(None).start()) is None
    with pytest.raises(SceneCaptureError) as unavailable:
        await SceneCaptureBroker(None).request()
    assert unavailable.value.code == "capture_unavailable"


# ------------------------------------------------------------------ Core réel


class CaptureCore(CoreProcess):
    """Core réel avec un magasin de captures sur disque et une échéance réglable."""

    def __init__(self, tmp_path, *, deadline_s: float = 5.0) -> None:  # noqa: ANN001
        super().__init__(tmp_path)
        self.capture_dir = tmp_path / "runtime" / "scene-captures"
        self.deadline_s = deadline_s

    async def start(self) -> JarvisCoreApplication:
        self.generation += 1
        self.token = f"{self.generation}" * 48
        self.token_file.write_text(self.token, encoding="utf-8")
        self.core = JarvisCoreApplication(data_root=self.data_root, scene_capture_store=FileSceneCaptureStore(self.capture_dir))
        self.core.scene_captures.deadline_s = self.deadline_s
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=self.token)
        await self.server.start()
        return self.core


@pytest.fixture
async def capture_core(tmp_path):
    process = CaptureCore(tmp_path)
    await process.start()
    try:
        yield process
    finally:
        await process.stop()


BRAIN = {"schema_version": 1, "actor": "brain"}


async def scene_head(core: CoreProcess) -> tuple[str, str, int]:
    status, body, _ = await core.request("GET", "/v1/scene/snapshot")
    assert status == 200
    return body["scene_id"], body["epoch"], body["revision"]


async def fake_leader(core: CoreProcess, *, image: bytes, polls: int = 3) -> list[dict]:
    """Une page meneuse minimale : long-poll, puis envoi du PNG pour la première demande reçue."""

    scene_id, epoch, revision = await scene_head(core)
    seen = []
    for _ in range(polls):
        status, body, _ = await core.request(
            "GET", f"/v1/scene/patches?scene_id={scene_id}&epoch={epoch}&after={revision}&wait_s=5")
        assert status == 200, body
        seen.append(body)
        capture = body.get("capture_request")
        if capture:
            async with aiohttp.ClientSession() as session:
                async with session.put(f"http://127.0.0.1:{core.port}/v1/scene/captures/{capture['id']}",
                                       headers={**core.headers(), "Content-Type": "image/png"}, data=image) as response:
                    seen.append({"upload_status": response.status, "upload": await response.json()})
            return seen
    return seen


async def test_core_routes_run_the_whole_capture_and_keep_the_long_poll_intact(capture_core):
    leader = asyncio.ensure_future(fake_leader(capture_core, image=png(1280, 720)))
    await asyncio.sleep(0.2)  # le long-poll attend déjà
    status, body, _ = await capture_core.request("POST", "/v1/scene/captures", json=BRAIN)
    seen = await leader
    assert status == 200, body
    assert seen[-1]["upload_status"] == 200 and seen[-1]["upload"]["capture_id"] == body["capture_id"]
    assert body["width"] == 1280 and body["height"] == 720 and body["bytes"] == len(png(1280, 720))
    path = Path(body["path"])
    assert path.parent == capture_core.capture_dir.resolve() and CAPTURE_NAME.match(path.name) and path.read_bytes() == png(1280, 720)
    long_poll = seen[0]
    # Réponse de patchs normale, plus la demande : aucun patch inventé, révision inchangée.
    assert long_poll["patches"] == [] and long_poll["resync_required"] is False and set(long_poll["capture_request"]) == {"id", "remaining_ms"}
    assert long_poll["capture_request"]["id"] != body["capture_id"][:0] and len(long_poll["capture_request"]["id"]) >= 32
    # Usage unique.
    async with aiohttp.ClientSession() as session:
        async with session.put(f"http://127.0.0.1:{capture_core.port}/v1/scene/captures/{body['capture_id']}",
                               headers=capture_core.headers(), data=png()) as response:
            assert response.status == 404 and (await response.json())["error"]["code"] == "unknown_capture"


async def test_capture_route_refusals(capture_core, tmp_path):
    no_token = {"X-Jarvis-Protocol": capture_core.headers()["X-Jarvis-Protocol"]}
    status, _, _ = await capture_core.request("POST", "/v1/scene/captures", json=BRAIN, headers=no_token)
    assert status == 401
    status, body, _ = await capture_core.request("POST", "/v1/scene/captures", json={"schema_version": 1, "actor": "user"})
    assert status == 403 and body["error"]["code"] == "scene_actor_forbidden"
    for bad in ({"actor": "brain"}, {"schema_version": 1, "actor": "brain", "extra": 1}, [1]):
        status, _, _ = await capture_core.request("POST", "/v1/scene/captures", json=bad)
        assert status == 400, bad
    # Pas de page : refus clair à l'échéance.
    capture_core.core.scene_captures.deadline_s = 0.3
    started = time.monotonic()
    status, body, _ = await capture_core.request("POST", "/v1/scene/captures", json=BRAIN)
    assert status == 504 and body["error"]["code"] == "no_visible_page" and time.monotonic() - started < 3
    # Occupé : une seule capture en attente.
    capture_core.core.scene_captures.deadline_s = 1.0
    first = asyncio.ensure_future(capture_core.request("POST", "/v1/scene/captures", json=BRAIN))
    await asyncio.sleep(0.2)
    status, body, _ = await capture_core.request("POST", "/v1/scene/captures", json=BRAIN)
    assert status == 409 and body["error"]["code"] == "capture_busy"
    capture_id = capture_core.core.scene_captures._pending.capture_id
    async with aiohttp.ClientSession() as session:
        url = f"http://127.0.0.1:{capture_core.port}/v1/scene/captures/{capture_id}"
        async with session.put(url, headers=capture_core.headers(), data=io.BytesIO(b"x" * (MAX_CAPTURE_BYTES + 1))) as response:
            assert response.status == 413
        async with session.put(url, headers=capture_core.headers(), data=b"\x89PNG garbage") as response:
            assert response.status == 400 and (await response.json())["error"]["code"] == "invalid_png"
        async with session.put(url.replace(capture_id, "z" * 40), headers=capture_core.headers(), data=png()) as response:
            assert response.status == 404
    assert (await first)[0] == 504
    # Sans magasin : non configurée.
    bare = CoreProcess(tmp_path / "bare")
    (tmp_path / "bare").mkdir()
    await bare.start()
    try:
        status, body, _ = await bare.request("POST", "/v1/scene/captures", json=BRAIN)
        assert status == 503 and body["error"]["code"] == "capture_unavailable"
    finally:
        await bare.stop()


async def test_a_pending_capture_is_redelivered_to_a_new_long_poll_but_never_to_a_short_read(capture_core):
    capture_core.core.scene_captures.deadline_s = 4.0
    request = asyncio.ensure_future(capture_core.request("POST", "/v1/scene/captures", json=BRAIN))
    await asyncio.sleep(0.1)
    scene_id, epoch, revision = await scene_head(capture_core)
    base = f"/v1/scene/patches?scene_id={scene_id}&epoch={epoch}&after={revision}"
    _, short, _ = await capture_core.request("GET", base + "&wait_s=0")
    assert "capture_request" not in short
    t0 = time.monotonic()
    _, first, _ = await capture_core.request("GET", base + "&wait_s=5")
    immediate = time.monotonic() - t0
    t1 = time.monotonic()
    _, second, _ = await capture_core.request("GET", base + "&wait_s=5")
    redelivered_after = time.monotonic() - t1
    assert first["capture_request"]["id"] == second["capture_request"]["id"]
    assert immediate < 0.5 and 0.6 < redelivered_after < 2.5  # ancien meneur perdu : le suivant la reçoit, sans boucle serrée
    # Une commande pendant l'attente arrive normalement.
    poll = asyncio.ensure_future(capture_core.request("GET", base + "&wait_s=5"))
    await asyncio.sleep(0.05)
    await capture_core.request("POST", "/v1/scene/commands", json={
        "schema_version": 1, "op": "upsert_object", "actor": "user", "object_id": "note-1",
        "fields": {"kind": "window", "category": "note", "payload": {"title": "t"}}})
    _, third, _ = await poll
    assert [p["revision"] for p in third["patches"]] == [revision + 1]
    assert (await request)[0] == 504


async def test_retention_keeps_five_captures_and_runs_at_core_start(capture_core):
    for _ in range(CAPTURE_KEEP_FILES + 2):
        leader = asyncio.ensure_future(fake_leader(capture_core, image=png()))
        await asyncio.sleep(0.05)
        status, _, _ = await capture_core.request("POST", "/v1/scene/captures", json=BRAIN)
        await leader
        assert status == 200
    files = [p for p in capture_core.capture_dir.iterdir() if CAPTURE_NAME.match(p.name)]
    assert len(files) == CAPTURE_KEEP_FILES
    old = files[0]
    os.utime(old, (time.time() - 25 * 3600,) * 2)
    await capture_core.stop()
    await capture_core.start()
    assert not old.exists() and len([p for p in capture_core.capture_dir.iterdir() if CAPTURE_NAME.match(p.name)]) == CAPTURE_KEEP_FILES - 1


# ------------------------------------------------------------------ Control Center


class UploadTransport:
    def __init__(self, answer) -> None:  # noqa: ANN001
        self.answer = answer
        self.calls: list[tuple[str, int]] = []

    async def scene_capture_upload(self, capture_id, data, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls.append((capture_id, len(data)))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    async def close(self) -> None:
        return None


async def test_the_control_center_upload_route_checks_origin_size_shape_and_id_before_core(tmp_path):
    capture_id = "c" * 32
    transport = UploadTransport({"capture_id": capture_id, "bytes": 10, "width": 64, "height": 36, "duration_ms": 5})
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path,
                            scene_view=CoreSceneView(transport, journal=RuntimeJournal(tmp_path)))
    route = f"/api/scene/captures/{capture_id}"
    async with TestClient(TestServer(control._app)) as client:
        evil = await client.post(route, data=png(), headers={"Origin": "http://evil.example", "Content-Type": "image/png"})
        assert evil.status == 403
        assert (await client.post("/api/scene/captures/short", data=png())).status == 404
        assert (await client.post(route + "?x=1", data=png())).status == 400
        big = await client.post(route, data=io.BytesIO(b"\x89PNG" + b"\x00" * MAX_CAPTURE_BYTES))
        assert big.status == 413
        garbage = await client.post(route, data=b"<svg/>")
        assert garbage.status == 400 and (await garbage.json())["error"]["code"] == "invalid_png"
        assert (await client.post(route, data=png(1920, 1080))).status == 400
        assert transport.calls == []
        ok = await client.post(route, data=png(), headers={"Origin": "http://127.0.0.1:1234", "Content-Type": "image/png"})
        assert ok.status == 200 and (await ok.json())["capture_id"] == capture_id
        assert transport.calls == [(capture_id, len(png()))]
        assert (await client.get(route)).status == 405  # aucune route ne demande ni ne lit une capture
    for answer, status, code in (
        (CoreProtocolError(404, "unknown_capture", "Aucune capture en attente"), 404, "unknown_capture"),
        (CoreProtocolError(410, "capture_expired", "trop tard"), 410, "capture_expired"),
        (ConnectionRefusedError("refused"), 503, "core_unreachable"),
    ):
        control = ControlCenter(runtime_root=tmp_path / code, project_root=tmp_path, scene_view=CoreSceneView(UploadTransport(answer)))
        async with TestClient(TestServer(control._app)) as client:
            response = await client.post(route, data=png())
            assert response.status == status and (await response.json())["error"]["code"] == code
    journal = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "scene.capture_upload_refused" in journal and "scene.capture_uploaded" in journal


def test_the_relay_keeps_a_well_formed_capture_request_only():
    body = {"scene_id": "s", "epoch": "e", "revision": 3, "patches": [], "resync_required": False, "more": False}
    assert "capture_request" not in decode_patches_response(body, after=3)
    good = decode_patches_response({**body, "capture_request": {"id": "d" * 32, "remaining_ms": 4000}}, after=3)
    assert good["capture_request"] == {"id": "d" * 32, "remaining_ms": 4000}
    for bad in ({"id": "short", "remaining_ms": 1}, {"id": "d" * 32}, {"id": "d" * 32, "remaining_ms": True},
                {"id": "d" * 32, "remaining_ms": -1, "x": 1}, "text"):
        with pytest.raises(ValueError):
            decode_patches_response({**body, "capture_request": bad}, after=3)


# ------------------------------------------------------------------ outil du cerveau, bout à bout


async def fake_page_through_control_center(base_url: str, *, image: bytes, stop: asyncio.Event) -> list[int]:
    """Page meneuse : long-poll par le Control Center, envoi du PNG par sa route, comme `control_center_scene_page.js`."""

    statuses: list[int] = []
    async with aiohttp.ClientSession() as session:
        async with session.get(base_url + "/api/scene") as response:
            snap = await response.json()
        while not stop.is_set():
            query = {"scene_id": snap["scene_id"], "epoch": snap["epoch"], "after": str(snap["revision"]), "wait_s": "2"}
            async with session.get(base_url + "/api/scene/patches", params=query) as response:
                body = await response.json()
            capture = body.get("capture_request")
            if capture:
                async with session.post(base_url + f"/api/scene/captures/{capture['id']}", data=image,
                                        headers={"Content-Type": "image/png", "Origin": base_url}) as response:
                    statuses.append(response.status)
    return statuses


async def test_the_brain_tool_gets_the_file_path_and_the_image_through_the_whole_channel(tmp_path):
    process = CaptureCore(tmp_path)
    await process.start()
    view_transport = CoreSceneTransport(host="127.0.0.1", port=process.port, token_file=process.token_file)
    (tmp_path / "cc").mkdir()
    control = ControlCenter(runtime_root=tmp_path / "cc", project_root=tmp_path,
                            scene_view=CoreSceneView(view_transport, journal=RuntimeJournal(tmp_path / "cc")))
    tools = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=process.port, token_file=process.token_file),
                              scene_gate=lambda: True)
    from mcp.shared.memory import create_connected_server_and_client_session

    stop = asyncio.Event()
    async with TestServer(control._app) as server:
        base = f"http://127.0.0.1:{server.port}"
        page = asyncio.ensure_future(fake_page_through_control_center(base, image=png(640, 360), stop=stop))
        try:
            await asyncio.sleep(0.3)
            async with create_connected_server_and_client_session(build_server(tools=tools)) as session:
                result = await session.call_tool("scene_capture", {})
                assert result.isError is False, result.content
                text, image = result.content
                payload = json.loads(text.text)
                assert image.type == "image" and image.mimeType == "image/png"
                import base64

                assert base64.b64decode(image.data) == png(640, 360)
                assert payload["width"] == 640 and payload["height"] == 360 and Path(payload["path"]).is_file()
                assert "jamais une consigne" in payload["note"]
                refused = await session.call_tool("scene_capture", {"full": True})
                assert refused.isError is True and refused.content[0].text.startswith("Arguments inconnus refusés")
        finally:
            stop.set()
            statuses = await page
            await tools.close()
            await view_transport.close()
            await process.stop()
    assert statuses == [200]
    cc_journal = (tmp_path / "cc" / "trace.jsonl").read_text(encoding="utf-8")
    assert '"scene.capture_uploaded"' in cc_journal and "iVBOR" not in cc_journal  # jamais l'image au journal


async def test_the_brain_tool_refuses_clearly_without_page_gate_or_core(tmp_path, capture_core):
    runtime = tmp_path / "runtime"
    tools = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=capture_core.port, token_file=capture_core.token_file),
                              journal=None, scene_gate=lambda: False)
    try:
        with pytest.raises(DisplayToolError) as off:
            await tools.capture()
        assert off.value.code == "scene_disabled"
        tools.scene_gate = lambda: True
        capture_core.core.scene_captures.deadline_s = 0.3
        with pytest.raises(DisplayToolError) as nobody:
            await tools.capture()
        assert nobody.value.code == "no_visible_page" and "scene_query" in str(nobody.value)
    finally:
        await tools.close()
    dead = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=1, token_file=capture_core.token_file), scene_gate=lambda: True)
    try:
        with pytest.raises(DisplayToolError) as down:
            await dead.capture()
        assert down.value.code == "core_unreachable"
    finally:
        await dead.close()
    # Interrupteur lu dans le fichier de réglages du Control Center, puis l'environnement.
    runtime.mkdir(parents=True, exist_ok=True)
    reader = scene_gate_reader(runtime)
    assert reader() is False
    (runtime / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": True}}), encoding="utf-8")
    assert reader() is True and scene_gate_reader(None) is None


def test_the_capture_tool_is_counted_as_display_work_and_the_catalog_has_no_archive_or_pin():
    assert "mcp__jarvis-display__scene_capture" in claude_local.DISPLAY_TOOLS
    assert not any("archiv" in name or "pin" in name for name in claude_local.DISPLAY_TOOLS)

# La lecture du flux du CLI (image, lignes longues) est couverte par tests/unit/test_cli_stream.py (reprise QA).


# ------------------------------------------------------------------ reprise QA : PNG, usage unique, client parti, rétention


def chunked_png(*chunks: tuple[bytes, bytes], corrupt: bytes | None = None) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        if tag == corrupt:
            crc ^= 1
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return b"\x89PNG\r\n\x1a\n" + b"".join(chunk(tag, data) for tag, data in chunks)


def test_png_validation_walks_every_chunk():
    ihdr = (b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
    idat = (b"IDAT", zlib.compress(b"\x00" * 13 * 4))
    iend = (b"IEND", b"")
    assert png_dimensions(chunked_png(ihdr, idat, (b"tEXt", b"k\x00v"), iend)) == (4, 4)
    refused = {
        "idat crc": chunked_png(ihdr, idat, iend, corrupt=b"IDAT"),
        "no idat": chunked_png(ihdr, iend),
        "apng": chunked_png(ihdr, (b"acTL", b"\x00" * 8), idat, iend),
        "unknown critical": chunked_png(ihdr, (b"ABCD", b"x"), idat, iend),
        "second ihdr": chunked_png(ihdr, ihdr, idat, iend),
        "data after iend": chunked_png(ihdr, idat, iend) + b"trailing",
        "iend not empty": chunked_png(ihdr, idat, (b"IEND", b"x")),
        "chunk past end": chunked_png(ihdr, idat)[:-3],
    }
    for name, data in refused.items():
        with pytest.raises(ValueError):
            png_dimensions(data)
        assert name


async def test_single_use_is_atomic_under_parallel_uploads(capture_core):
    request = asyncio.ensure_future(capture_core.request("POST", "/v1/scene/captures", json=BRAIN))
    await asyncio.sleep(0.2)
    capture_id = capture_core.core.scene_captures._pending.capture_id

    async def put() -> int:
        async with aiohttp.ClientSession() as session:
            async with session.put(f"http://127.0.0.1:{capture_core.port}/v1/scene/captures/{capture_id}",
                                   headers=capture_core.headers(), data=png()) as response:
                return response.status

    statuses = await asyncio.gather(*(put() for _ in range(4)))
    assert sorted(statuses) == [200, 404, 404, 404]
    assert (await request)[0] == 200
    assert len([p for p in capture_core.capture_dir.iterdir() if CAPTURE_NAME.match(p.name)]) == 1


async def test_a_brain_call_that_leaves_frees_the_capture_at_once(capture_core, tmp_path):
    async with aiohttp.ClientSession() as session:
        call = asyncio.ensure_future(session.post(f"http://127.0.0.1:{capture_core.port}/v1/scene/captures",
                                                  headers=capture_core.headers(), json=BRAIN))
        await asyncio.sleep(0.3)
        assert capture_core.core.scene_captures._pending is not None
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
    started = time.monotonic()
    while capture_core.core.scene_captures._pending is not None and time.monotonic() - started < 2:
        await asyncio.sleep(0.05)
    assert capture_core.core.scene_captures._pending is None and time.monotonic() - started < 2
    leader = asyncio.ensure_future(fake_leader(capture_core, image=png()))
    await asyncio.sleep(0.05)
    status, body, _ = await capture_core.request("POST", "/v1/scene/captures", json=BRAIN)
    await leader
    assert status == 200, body  # plus de capture_busy


async def test_expired_uploads_are_journaled_and_prune_survives_a_vanished_file(tmp_path, monkeypatch):
    from jarvis.runtime.journal import RuntimeJournal

    journal = RuntimeJournal(tmp_path / "journal")
    broker = SceneCaptureBroker(MemoryStore(), deadline_s=0.3, diagnostics=journal)
    request = asyncio.ensure_future(broker.request())
    await asyncio.sleep(0)
    capture_id = broker.deliver(long_poll=True)["id"]
    broker._pending.deadline = asyncio.get_running_loop().time()  # échue, encore en attente
    with pytest.raises(SceneCaptureError) as expired:
        await broker.complete(capture_id, png())
    assert (expired.value.code, expired.value.status) == ("capture_expired", 410)
    with pytest.raises(SceneCaptureError):
        await request
    trace = (tmp_path / "journal" / "trace.jsonl").read_text(encoding="utf-8")
    assert '"capture_expired"' in trace

    store = FileSceneCaptureStore(tmp_path / "captures")
    saved = [store.save(png(), now_epoch_s=time.time() + index) for index in range(8)]
    victim = Path(saved[0].path)
    real_unlink = Path.unlink

    def flaky_unlink(self, missing_ok=False):  # noqa: ANN001
        if self == victim:
            real_unlink(self)
            raise FileNotFoundError(str(self))
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    store.prune(now_epoch_s=time.time() + 10, keep=5, max_age_s=24 * 3600)
    assert len([p for p in store.directory.iterdir() if CAPTURE_NAME.match(p.name)]) == 5


async def test_a_foreign_origin_on_the_upload_route_gets_the_scene_error_shape(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    async with TestClient(TestServer(control._app)) as client:
        response = await client.post("/api/scene/captures/" + "c" * 32, data=png(), headers={"Origin": "http://evil.example"})
        assert response.status == 403
        body = await response.json()
        assert body["error"]["code"] == "forbidden_origin"
