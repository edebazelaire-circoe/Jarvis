"""Transport de la scène par la boucle locale (handoff jarvis-constellation-scene-runtime, Slice 03).

Chaîne réelle : `JarvisCoreApplication` (SQLite réel) → `LocalProtocolServer`
(`/v1/scene/*`, jeton, version de protocole) ; puis Control Center →
`CoreSceneView` → `CoreSceneTransport` → mêmes routes (`/api/scene*`).

Ce qui doit tenir :

- instantané `{scene_id, epoch, revision, snapshot}` ; patchs par long-poll
  réveillé par un commit, rendu à l'échéance, borné, sans instantané ;
- `resync_required` sur autre époque (Core redémarré), autre `scene_id`,
  révision hors d'atteinte ;
- acteurs HTTP : `brain` et `user` ; `runtime` refusé (403) ; un refus du
  domaine (archive du cerveau) est un 200 `rejected_authority` ;
- entrée illisible : 400 sans trace de pile ; corps trop gros : 413 ; scène
  indisponible ou écriture échouée : 503 avec code ; `/v1/health` porte la
  disponibilité de la scène sans changer ses autres champs ;
- le Control Center impose `user`, garde l'origine, et dégrade comme `/api/work`.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.scene import SceneSnapshot
from jarvis.domain.v2 import PROTOCOL_VERSION
from jarvis.ports.scene import SceneStoreError, SceneStoreErrorCode
from jarvis.protocol import scene_wire
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.scene_view import CORE_UNREACHABLE, CoreSceneTransport, CoreSceneView
from tests.unit.test_scene_service import MemoryRepository


async def core_waiting(app: JarvisCoreApplication, count: int = 1, *, timeout: float = 30.0) -> None:
    """Attendre qu'au moins `count` long-polls attendent une révision dans Core (borné, pas une durée fixe)."""

    async def poll() -> None:
        while len(getattr(app.scene._changed, "_waiters", ())) < count:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


async def until(condition, *, timeout: float = 30.0) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CoreProcess:
    """Un Core réel sur la boucle locale, redémarrable sur le même dossier de données."""

    def __init__(self, tmp_path, *, scene_repository=None) -> None:  # noqa: ANN001
        self.data_root = tmp_path / "data"
        self.token_file = tmp_path / "core.token"
        self.port = free_port()
        self.scene_repository = scene_repository
        self.core: JarvisCoreApplication | None = None
        self.server: LocalProtocolServer | None = None
        self.generation = 0
        self.token = ""

    async def start(self) -> JarvisCoreApplication:
        self.generation += 1
        self.token = f"{self.generation}" * 48
        self.token_file.write_text(self.token, encoding="utf-8")
        self.core = JarvisCoreApplication(data_root=self.data_root, scene_repository=self.scene_repository)
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=self.token)
        await self.server.start()
        return self.core

    async def stop(self) -> None:
        if self.server is not None:
            await self.server.stop()
        if self.core is not None:
            await self.core.stop()
        self.server = self.core = None

    def headers(self, **overrides: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION), **overrides}

    async def request(self, method: str, path: str, *, headers: dict | None = None, **kwargs) -> tuple[int, dict, str]:  # noqa: ANN003
        async with aiohttp.ClientSession() as session:
            async with session.request(method, f"http://127.0.0.1:{self.port}{path}", headers=headers or self.headers(), **kwargs) as response:
                text = await response.text()
                try:
                    body = json.loads(text)
                except ValueError:
                    body = {}
                return response.status, body, text


@pytest.fixture
async def core(tmp_path):
    process = CoreProcess(tmp_path)
    await process.start()
    try:
        yield process
    finally:
        await process.stop()


def artifact(object_id: str, *, actor: str = "user", title: str = "Résumé") -> dict:
    return {
        "schema_version": 1, "op": "upsert_object", "actor": actor, "object_id": object_id,
        "fields": {"kind": "artifact", "category": "research", "payload": {"title": title, "summary": "", "items": []}},
    }


async def snapshot_of(process: CoreProcess) -> dict:
    status, body, _ = await process.request("GET", "/v1/scene/snapshot")
    assert status == 200, body
    return body


def patches_path(body: dict, *, after: int | None = None, wait_s: float = 0) -> str:
    after = body["revision"] if after is None else after
    return f"/v1/scene/patches?scene_id={body['scene_id']}&epoch={body['epoch']}&after={after}&wait_s={wait_s}"


# ------------------------------------------------------------------ Core


async def test_the_snapshot_carries_scene_id_epoch_and_revision(core):
    status, body, _ = await core.request("POST", "/v1/scene/commands", json=artifact("art-1"))
    assert status == 200 and body["outcome"] == "applied"

    snap = await snapshot_of(core)

    assert set(snap) == {"scene_id", "epoch", "revision", "snapshot"}
    assert snap["epoch"] == core.core.scene.epoch and snap["revision"] == 1
    decoded = SceneSnapshot.from_payload(snap["snapshot"])
    assert decoded == await core.core.scene.snapshot() and decoded.scene_id == snap["scene_id"]
    # UTF-8 réel, pas d'échappement `\uXXXX` qui gonflerait la réponse.
    status, _, text = await core.request("GET", "/v1/scene/snapshot")
    assert "Résumé" in text


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/v1/scene/snapshot", {}),
        ("GET", "/v1/scene/patches?scene_id=s&epoch=e&after=0", {}),
        ("POST", "/v1/scene/commands", {"json": artifact("art-x")}),
    ],
)
async def test_scene_routes_require_the_token_and_the_protocol_version(core, method, path, kwargs):
    no_token = {"X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
    status, body, _ = await core.request(method, path, headers=no_token, **kwargs)
    assert status == 401 and body["error"]["code"] == "unauthorized"
    status, body, _ = await core.request(method, path, headers={**no_token, "Authorization": "Bearer " + "z" * 48}, **kwargs)
    assert status == 401
    status, body, _ = await core.request(method, path, headers=core.headers(**{"X-Jarvis-Protocol": "999"}), **kwargs)
    assert status == 426 and body["error"]["code"] == "protocol_mismatch"
    assert (await core.core.scene.snapshot()).revision == 0


async def test_runtime_is_refused_over_http_brain_and_user_are_accepted(core):
    runtime_star = {
        "schema_version": 1, "op": "upsert_object", "actor": "runtime", "object_id": "star-1",
        "fields": {"kind": "agent", "category": "agent", "exec_state": "running"},
    }
    status, body, _ = await core.request("POST", "/v1/scene/commands", json=runtime_star)
    assert status == 403 and body["error"]["code"] == scene_wire.SCENE_ACTOR_FORBIDDEN
    assert (await core.core.scene.snapshot()).revision == 0

    status, brain, _ = await core.request("POST", "/v1/scene/commands", json=artifact("art-brain", actor="brain"))
    assert status == 200 and brain["outcome"] == "applied" and brain["reason"] is None
    assert set(brain) == {"outcome", "reason", "scene_id", "epoch", "revision", "patch"}
    assert brain["revision"] == 1 and brain["patch"]["revision"] == 1 and brain["epoch"] == core.core.scene.epoch
    assert brain["patch"]["ops"][0]["object"]["origin"] == "brain"
    status, user, _ = await core.request("POST", "/v1/scene/commands", json=artifact("art-user"))
    assert status == 200 and user["outcome"] == "applied" and user["revision"] == 2


async def test_a_brain_authority_refusal_is_a_domain_refusal_not_an_http_error(core):
    # Réalignement baseline (main, 19/09/2026) : le cerveau archive désormais ;
    # le refus d'autorité qui lui reste est une vérité d'une autre couche, ici
    # la création d'un nœud d'exécution (`execution_node`).
    await core.request("POST", "/v1/scene/commands", json=artifact("art-1"))
    star = {"schema_version": 1, "op": "upsert_object", "actor": "brain", "object_id": "star-brain",
            "fields": {"kind": "agent", "category": "agent"}}

    status, body, _ = await core.request("POST", "/v1/scene/commands", json=star)

    assert status == 200
    assert body["outcome"] == "rejected_authority" and body["reason"] == "execution_node"
    assert body["patch"] is None and body["revision"] == 1
    status, duplicate, _ = await core.request("POST", "/v1/scene/commands", json=artifact("art-1"))
    assert status == 200 and duplicate["outcome"] == "duplicate" and duplicate["reason"] is None
    archive = {"schema_version": 1, "op": "archive", "actor": "brain", "object_id": "art-1"}
    status, brain, _ = await core.request("POST", "/v1/scene/commands", json=archive)
    assert status == 200 and brain["outcome"] == "applied" and brain["patch"]["ops"][0]["op"] == "archive_object"


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"\xff\xfe",
        b"[]",
        b'{"schema_version": 1, "schema_version": 1, "op": "archive", "actor": "user", "object_id": "a"}',
        b'{"schema_version": 1, "op": "set_geometry", "actor": "user", "object_id": "a", "geometry": {"x": NaN, "y": 0, "w": 1, "h": 1}}',
        b'{"op": "archive", "actor": "user", "object_id": "a"}',
        b'{"schema_version": 2, "op": "archive", "actor": "user", "object_id": "a"}',
        b'{"schema_version": 1, "op": "explode", "actor": "user", "object_id": "a"}',
        b'{"schema_version": 1, "op": "archive", "actor": "user", "object_id": "a", "extra": 1}',
        b'{"schema_version": 1, "op": "archive", "actor": "user"}',
        b'{"schema_version": 1, "op": "archive", "actor": "user", "object_id": 7}',
        b'{"schema_version": 1, "op": "upsert_object", "actor": "user", "object_id": "a", "fields": "x"}',
        b'{"schema_version": 1, "op": "set_geometry", "actor": "user", "object_id": "a", "geometry": {"x": ' + b"9" * 400 + b', "y": 0, "w": 1, "h": 1}}',
        b"[" * 20_000 + b"]" * 20_000,
    ],
    ids=lambda raw: raw[:24].decode("latin-1"),
)
async def test_malformed_commands_are_400_without_a_stack_trace(core, raw):
    status, body, text = await core.request("POST", "/v1/scene/commands", data=raw, headers={**core.headers(), "Content-Type": "application/json"})

    assert status == 400, text[:300]
    assert body["error"]["code"] == "invalid_request"
    assert "Traceback" not in text and 'File "' not in text and len(text) < 600
    assert (await core.core.scene.snapshot()).revision == 0


async def test_an_oversize_command_is_413_announced_or_streamed(core):
    big = json.dumps(artifact("art-1", title="x" * (scene_wire.MAX_SCENE_COMMAND_BYTES + 10))).encode()

    status, body, _ = await core.request("POST", "/v1/scene/commands", data=big)
    assert status == 413 and body["error"]["code"] == scene_wire.PAYLOAD_TOO_LARGE

    async def chunks():
        for start in range(0, len(big), 8192):
            yield big[start:start + 8192]

    status, body, _ = await core.request("POST", "/v1/scene/commands", data=chunks())
    assert status == 413 and body["error"]["code"] == scene_wire.PAYLOAD_TOO_LARGE
    assert (await core.core.scene.snapshot()).revision == 0


async def test_a_long_poll_wakes_on_commit(core):
    snap = await snapshot_of(core)
    started = time.monotonic()
    poll = asyncio.create_task(core.request("GET", patches_path(snap, wait_s=20)))
    await core_waiting(core.core)
    assert not poll.done()

    status, command, _ = await core.request("POST", "/v1/scene/commands", json=artifact("art-1"))
    status, body, _ = await asyncio.wait_for(poll, 5)

    assert status == 200 and time.monotonic() - started < 5
    assert body["resync_required"] is False and body["more"] is False
    assert body["revision"] == 1 and [patch["revision"] for patch in body["patches"]] == [1]
    assert body["patches"][0] == command["patch"]
    assert "snapshot" not in body and body["epoch"] == snap["epoch"]


async def test_a_long_poll_returns_at_its_deadline_without_patches(core):
    snap = await snapshot_of(core)
    started = time.monotonic()

    status, body, _ = await core.request("GET", patches_path(snap, wait_s=0.4))

    elapsed = time.monotonic() - started
    assert status == 200 and 0.35 <= elapsed < 3
    assert body == {"scene_id": snap["scene_id"], "epoch": snap["epoch"], "revision": 0, "resync_required": False, "more": False, "patches": []}


async def test_resync_is_immediate_for_another_epoch_scene_or_unreachable_revision(core):
    await core.request("POST", "/v1/scene/commands", json=artifact("art-1"))
    snap = await snapshot_of(core)

    cases = {
        "epoch": patches_path({**snap, "epoch": "old-epoch"}, after=0, wait_s=20),
        "scene": patches_path({**snap, "scene_id": "other-scene"}, after=0, wait_s=20),
        "ahead": patches_path(snap, after=9, wait_s=20),
    }
    for name, path in cases.items():
        started = time.monotonic()
        status, body, _ = await core.request("GET", path)
        assert status == 200 and time.monotonic() - started < 2, name
        assert body["resync_required"] is True and body["patches"] == [], name
        assert (body["scene_id"], body["epoch"], body["revision"]) == (snap["scene_id"], snap["epoch"], 1), name


@pytest.mark.parametrize(
    "query",
    [
        "scene_id=s&epoch=e",
        "scene_id=s&epoch=e&after=-1",
        "scene_id=s&epoch=e&after=1.5",
        "scene_id=s&epoch=e&after=1&wait_s=nan",
        "scene_id=s&epoch=e&after=1&wait_s=inf",
        "scene_id=s&epoch=e&after=1&wait_s=-2",
        "scene_id=s&epoch=e&after=1&after=2",
        "scene_id=s&epoch=&after=1",
        "epoch=e&after=1",
        "scene_id=s&epoch=e&after=1&snapshot=1",
        "scene_id=s&epoch=e&after=" + "9" * 40,
    ],
)
async def test_invalid_patch_queries_are_400(core, query):
    status, body, text = await core.request("GET", f"/v1/scene/patches?{query}")
    assert status == 400 and body["error"]["code"] == "invalid_request" and "Traceback" not in text


async def test_a_patch_response_is_bounded_and_says_more(core, monkeypatch):
    for index in range(6):
        await core.request("POST", "/v1/scene/commands", json=artifact(f"art-{index}", title="é" * 150))
    snap = await snapshot_of(core)
    monkeypatch.setattr(scene_wire, "MAX_PATCH_RESPONSE_BYTES", 1500)

    status, first, text = await core.request("GET", patches_path(snap, after=0))
    assert status == 200 and len(text.encode()) < 1500 + 1024
    assert first["more"] is True and 1 <= len(first["patches"]) < 6
    assert first["revision"] == first["patches"][-1]["revision"]
    got = [patch["revision"] for patch in first["patches"]]
    after = first["revision"]
    while True:
        status, page, _ = await core.request("GET", patches_path(snap, after=after))
        got += [patch["revision"] for patch in page["patches"]]
        after = page["revision"]
        if not page["more"]:
            break
    assert got == [1, 2, 3, 4, 5, 6] and after == 6

    monkeypatch.setattr(scene_wire, "MAX_PATCH_RESPONSE_BYTES", 10)
    status, single, _ = await core.request("GET", patches_path(snap, after=0))
    assert [patch["revision"] for patch in single["patches"]] == [1] and single["more"] is True


async def test_a_core_restart_changes_the_epoch_and_forces_resync(tmp_path):
    process = CoreProcess(tmp_path)
    await process.start()
    try:
        await process.request("POST", "/v1/scene/commands", json=artifact("art-1"))
        before = await snapshot_of(process)
        await process.stop()
        await process.start()

        status, body, _ = await process.request("GET", patches_path(before, wait_s=20))
        after = await snapshot_of(process)
    finally:
        await process.stop()

    assert status == 200 and body["resync_required"] is True and body["patches"] == []
    assert body["epoch"] == after["epoch"] != before["epoch"]
    assert body["scene_id"] == before["scene_id"] and body["revision"] == before["revision"] == 1
    assert after["snapshot"] == before["snapshot"]


async def test_stopping_the_server_releases_a_pending_long_poll(core):
    snap = await snapshot_of(core)
    poll = asyncio.create_task(core.request("GET", patches_path(snap, wait_s=25)))
    await core_waiting(core.core)

    started = time.monotonic()
    await core.server.stop()
    core.server = None
    status, body, _ = await asyncio.wait_for(poll, 10)

    assert time.monotonic() - started < 5
    assert status == 200 and body["patches"] == [] and body["resync_required"] is False


async def test_health_keeps_its_fields_and_adds_scene_availability(core):
    status, body, _ = await core.request("GET", "/v1/health")
    assert status == 200
    assert {"protocol_version", "ready", "status", "detail"} <= set(body)
    assert body["ready"] is True and body["protocol_version"] == PROTOCOL_VERSION
    assert body["scene"] == {"state": "ready", "code": None, "saturated": False, "objects": 0, "object_limit": 512}


async def test_an_unavailable_scene_is_503_with_its_code_and_core_stays_ready(tmp_path):
    scene_file = tmp_path / "data" / "state" / "scene.sqlite3"
    scene_file.parent.mkdir(parents=True)
    scene_file.write_bytes(b"not a scene database" * 64)
    process = CoreProcess(tmp_path)
    await process.start()
    try:
        requests = [
            ("GET", "/v1/scene/snapshot", {}),
            ("GET", "/v1/scene/patches?scene_id=s&epoch=e&after=0&wait_s=10", {}),
            ("POST", "/v1/scene/commands", {"json": artifact("art-1")}),
        ]
        for method, path, kwargs in requests:
            status, body, _ = await process.request(method, path, **kwargs)
            assert status == 503, (path, body)
            assert body["error"]["code"] == scene_wire.SCENE_UNAVAILABLE and body["error"]["store_code"] == "corrupted"
            assert body["error"]["scene"] == {"state": "unavailable", "code": "corrupted", "saturated": False, "objects": None, "object_limit": 512}
        status, health, _ = await process.request("GET", "/v1/health")
    finally:
        await process.stop()

    assert status == 200 and health["ready"] is True and health["scene"] == {"state": "unavailable", "code": "corrupted", "saturated": False, "objects": None, "object_limit": 512}


async def test_a_persistence_failure_is_503_and_nothing_advances(tmp_path):
    repository = MemoryRepository()
    process = CoreProcess(tmp_path, scene_repository=repository)
    await process.start()
    try:
        repository.fail_commit = SceneStoreError(SceneStoreErrorCode.STORAGE_IO, "disk full")
        status, body, _ = await process.request("POST", "/v1/scene/commands", json=artifact("art-1"))
        assert status == 503
        assert body["error"]["code"] == scene_wire.SCENE_PERSIST_FAILED and body["error"]["store_code"] == "storage_io"
        assert "disk full" in body["error"]["message"] and body["error"]["scene"] == {"state": "ready", "code": None, "saturated": False, "objects": 0, "object_limit": 512}
        repository.fail_commit = None
        status, retry, _ = await process.request("POST", "/v1/scene/commands", json=artifact("art-1"))
        assert status == 200 and retry["revision"] == 1
    finally:
        await process.stop()


# ------------------------------------------------------------ Control Center


@pytest.fixture
async def stack(tmp_path):
    process = CoreProcess(tmp_path)
    await process.start()
    view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=process.port, token_file=process.token_file))
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path, scene_view=view)
    client = TestClient(TestServer(control._app))
    await client.start_server()
    try:
        yield process, control, client
    finally:
        await client.close()
        await view.aclose()
        await process.stop()


async def test_the_control_center_serves_snapshot_long_poll_and_user_commands(stack):
    process, _, client = stack
    response = await client.get("/api/scene")
    scene = await response.json()
    assert response.status == 200 and scene["core_reachable"] is True and scene["error"] is None
    assert scene["scene"] == {"state": "ready", "code": None, "saturated": False, "objects": 0, "object_limit": 512} and scene["revision"] == 0
    assert scene["epoch"] == process.core.scene.epoch and scene["snapshot"]["objects"] == []

    query = f"/api/scene/patches?scene_id={scene['scene_id']}&epoch={scene['epoch']}&after=0&wait_s=20"
    poll = asyncio.create_task(client.get(query))
    await core_waiting(process.core)
    assert not poll.done()
    command = await client.post("/api/scene/commands", json={"schema_version": 1, "op": "upsert_object", "object_id": "art-1",
                                                              "fields": {"kind": "artifact", "category": "research"}})
    applied = await command.json()
    patches = await (await asyncio.wait_for(poll, 5)).json()

    assert command.status == 200 and applied["outcome"] == "applied" and applied["revision"] == 1
    assert applied["patch"]["ops"][0]["object"]["origin"] == "user"
    assert patches["error"] is None and patches["revision"] == 1 and patches["patches"] == [applied["patch"]]
    assert (await process.core.scene.snapshot()).get_object("art-1").origin.value == "user"


@pytest.mark.parametrize("actor", ["brain", "runtime", "", None, 1])
async def test_the_control_center_never_sends_another_actor_than_user(stack, actor):
    process, control, client = stack
    body = {"schema_version": 1, "op": "archive", "actor": actor, "object_id": "art-1"}

    response = await client.post("/api/scene/commands", json=body)

    assert response.status == 403 and (await response.json())["error"]["code"] == scene_wire.SCENE_ACTOR_FORBIDDEN
    assert (await process.core.scene.snapshot()).revision == 0


async def test_the_control_center_user_archives_like_the_brain(stack):
    # Réalignement baseline (main, 19/09/2026) : le cerveau a la main de
    # l'utilisateur, archivage compris ; le proxy relaie l'archivage `user`.
    process, _, client = stack
    await process.request("POST", "/v1/scene/commands", json=artifact("art-1", actor="brain"))
    await process.request("POST", "/v1/scene/commands", json=artifact("art-2", actor="brain"))
    status, brain, _ = await process.request("POST", "/v1/scene/commands", json={"schema_version": 1, "op": "archive", "actor": "brain", "object_id": "art-1"})
    assert brain["outcome"] == "applied" and brain["revision"] == 3

    response = await client.post("/api/scene/commands", json={"schema_version": 1, "op": "archive", "actor": "user", "object_id": "art-2"})
    body = await response.json()

    assert response.status == 200 and body["outcome"] == "applied" and body["revision"] == 4


async def test_long_polls_beyond_the_control_center_cap_are_told_to_retry(stack):
    process, control, client = stack
    control.scene_view.max_concurrent_waits = 4
    scene = await (await client.get("/api/scene")).json()
    query = f"/api/scene/patches?scene_id={scene['scene_id']}&epoch={scene['epoch']}&after=0&wait_s=20"
    held = [asyncio.create_task(client.get(query)) for _ in range(4)]
    await until(lambda: control.scene_view.waiting == 4)
    await core_waiting(process.core, 4)

    started = time.monotonic()
    busy = await client.get(query)
    busy_body = await busy.json()
    command = await client.post("/api/scene/commands", json=artifact("art-1"))
    elapsed = time.monotonic() - started
    woken = [await (await asyncio.wait_for(task, 10)).json() for task in held]

    assert busy.status == 200 and busy_body["error"]["code"] == "patch_waits_busy" and busy_body["retry_after_ms"] == 1000
    assert command.status == 200 and elapsed < 2
    assert all(body["revision"] == 1 and len(body["patches"]) == 1 for body in woken)
    assert control.scene_view.waiting == 0


async def test_the_control_center_guards_origin_size_and_shape(stack):
    process, _, client = stack
    body = {"schema_version": 1, "op": "archive", "object_id": "art-1"}

    forbidden = await client.post("/api/scene/commands", json=body, headers={"Origin": "http://evil.example"})
    oversize = await client.post("/api/scene/commands", data=b"{" + b" " * (scene_wire.MAX_SCENE_COMMAND_BYTES + 1) + b"}")
    malformed = await client.post("/api/scene/commands", data=b'{"schema_version": 1, "op": "archive"}')
    bad_query = await client.get("/api/scene/patches?after=x")

    assert forbidden.status == 403
    assert oversize.status == 413 and (await oversize.json())["error"]["code"] == scene_wire.PAYLOAD_TOO_LARGE
    assert malformed.status == 400 and "Traceback" not in await malformed.text()
    assert bad_query.status == 400
    assert (await process.core.scene.snapshot()).revision == 0


async def test_the_control_center_degrades_when_core_is_down_then_resyncs_after_restart(stack):
    process, _, client = stack
    await client.post("/api/scene/commands", json=artifact("art-1"))
    before = await (await client.get("/api/scene")).json()
    await process.stop()

    down = await (await client.get("/api/scene")).json()
    down_patches = await (await client.get(
        f"/api/scene/patches?scene_id={before['scene_id']}&epoch={before['epoch']}&after=1&wait_s=1")).json()
    down_command = await client.post("/api/scene/commands", json=artifact("art-2"))

    assert down["core_reachable"] is False and down["snapshot"] is None and down["error"]["code"] == CORE_UNREACHABLE
    assert down_patches["patches"] == [] and down_patches["resync_required"] is False and down_patches["error"]["code"] == CORE_UNREACHABLE
    assert down_command.status == 503 and (await down_command.json())["error"]["code"] == CORE_UNREACHABLE

    await process.start()  # nouveau jeton, même dossier de données
    resync = await (await client.get(
        f"/api/scene/patches?scene_id={before['scene_id']}&epoch={before['epoch']}&after=1&wait_s=20")).json()
    after = await (await client.get("/api/scene")).json()

    assert resync["error"] is None and resync["resync_required"] is True and resync["epoch"] != before["epoch"]
    assert after["snapshot"] == before["snapshot"] and after["epoch"] == resync["epoch"]


async def test_the_control_center_reports_an_unavailable_scene_with_its_code(tmp_path):
    scene_file = tmp_path / "data" / "state" / "scene.sqlite3"
    scene_file.parent.mkdir(parents=True)
    scene_file.write_bytes(b"not a scene database" * 64)
    process = CoreProcess(tmp_path)
    await process.start()
    view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=process.port, token_file=process.token_file))
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path, scene_view=view)
    try:
        async with TestClient(TestServer(control._app)) as client:
            scene = await (await client.get("/api/scene")).json()
            command = await client.post("/api/scene/commands", json=artifact("art-1"))
            command_body = await command.json()
    finally:
        await view.aclose()
        await process.stop()

    assert scene["core_reachable"] is True and scene["snapshot"] is None
    assert scene["error"]["code"] == scene_wire.SCENE_UNAVAILABLE
    # Le message de Core nomme le fichier ; la page n'en reçoit pas le chemin.
    assert "<chemin>" in scene["error"]["message"] and "<chemin>" in command_body["error"]["message"]
    assert tmp_path.name not in json.dumps([scene, command_body], ensure_ascii=False)
    assert scene["scene"] == {"state": "unavailable", "code": "corrupted", "saturated": False, "objects": None, "object_limit": 512}
    assert command.status == 503 and command_body["scene"] == {"state": "unavailable", "code": "corrupted", "saturated": False, "objects": None, "object_limit": 512}


async def test_health_and_the_control_center_say_when_the_scene_is_full(core):
    """Slice 04 QA F1 : la saturation se lit dans `/v1/health` sans changer ses champs d'origine."""

    from jarvis.domain.scene import MAX_SCENE_OBJECTS, SceneActor, SceneCommand, SceneObjectFields, SceneObjectKind, SceneOp
    from jarvis.runtime.scene_view import CoreSceneView

    for index in range(MAX_SCENE_OBJECTS):
        await core.core.scene.apply(SceneCommand(
            op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id=f"note-{index}",
            fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="note"),
        ))
    status, body, _ = await core.request("GET", "/v1/health")
    assert status == 200 and body["ready"] is True and body["status"] == "ok"
    assert body["scene"] == {"state": "ready", "code": None, "saturated": True, "objects": MAX_SCENE_OBJECTS, "object_limit": MAX_SCENE_OBJECTS}
    served = CoreSceneView._ready({"snapshot": {"objects": [{}] * MAX_SCENE_OBJECTS}})
    assert served["scene"]["saturated"] is True and served["scene"]["objects"] == MAX_SCENE_OBJECTS
