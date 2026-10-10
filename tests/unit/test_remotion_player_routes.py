"""Routes de Core de la lecture d'une scène Remotion (Slice 10) : `GET /v1/remotion/sandbox`, `GET /v1/remotion/player/...`, et
le paquet `{kind: "remotion"}` de `GET /v1/prefabs/.../bundle`. Contrat : `jarvis/protocol/remotion_player_routes.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_engine import EngineAvailability
from jarvis.domain.remotion_compile import CompileDiagnostic, CompileErrorCode, RemotionCompileError
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from jarvis.protocol.prefab_routes import PrefabProtocolRoutes
from jarvis.protocol.remotion_player_routes import PREFIX, RemotionPlayerProtocolRoutes

ID = "presentation-studio.p000000000001.s000000000001"


class FakePlayer:
    def __init__(self, *, raises: Exception | None = None, state: EngineAvailability = EngineAvailability(True)) -> None:
        self.raises, self.state, self.calls = raises, state, []

    def availability(self):
        return self.state

    def sandbox_info(self):
        return {"configured": True, "origin": "http://127.77.0.2:17655", "embedder_origin": "http://127.0.0.1:17654", "listening": False}

    async def describe(self, prefab_id, version):
        self.calls.append((prefab_id, version))
        if self.raises:
            raise self.raises
        return {"kind": "remotion", "prefab_id": prefab_id, "version": version, "page_url": "http://127.77.0.2:17655/page/x/y"}


class FakePrefabs:
    def __init__(self, *, remotion: bool) -> None:
        self.remotion, self.bundled = remotion, 0

    async def manifest(self, prefab_id, version):
        return SimpleNamespace(source=object() if self.remotion else None, title="Une scène")

    async def bundle(self, prefab_id, version):
        self.bundled += 1
        return {"id": prefab_id, "version": version, "fingerprint": "f" * 64, "manifest": {}, "files": {}, "runtime": {"version": 1}}


async def client_for(core) -> TestClient:
    app = web.Application()
    app.add_routes([*RemotionPlayerProtocolRoutes(core).routes(), *PrefabProtocolRoutes(core).routes()])
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def core_of(player=None, prefabs=None, ready=True):
    return SimpleNamespace(health=SimpleNamespace(ready=ready), remotion_player=player or FakePlayer(), prefabs=prefabs or FakePrefabs(remotion=True))


async def test_the_sandbox_route_reports_the_engine_state_and_the_origin():
    client = await client_for(core_of(FakePlayer(state=EngineAvailability(False, "not installed", "install it"))))
    try:
        response = await client.get(PREFIX + "/sandbox")
        body = await response.json()
        assert response.status == 200 and body["engine"] == {"ready": False, "reason": "not installed", "repair": "install it"}
        assert body["sandbox"]["origin"] == "http://127.77.0.2:17655"
        assert (await client.get(PREFIX + "/sandbox?x=1")).status == 400
    finally:
        await client.close()


async def test_the_player_route_returns_the_descriptor_uncached():
    player = FakePlayer()
    client = await client_for(core_of(player))
    try:
        response = await client.get(f"{PREFIX}/player/{ID}/3")
        assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
        assert (await response.json())["page_url"].endswith("/page/x/y") and player.calls == [(ID, 3)]
        for bad in ("0", "abc", "10000", "-1"):
            assert (await client.get(f"{PREFIX}/player/{ID}/{bad}")).status in (400, 404), bad
        assert player.calls == [(ID, 3)]
    finally:
        await client.close()


@pytest.mark.parametrize("error, status, code", [
    (PresentationStudioError(C.ENGINE_UNAVAILABLE, "remotion is unavailable: nope. Repair: install"), 409, "presentation_studio_engine_unavailable"),
    (PrefabStoreError(PrefabStoreErrorCode.UNKNOWN_VERSION, "no such version"), 404, "unknown_version"),
    (PrefabStoreError(PrefabStoreErrorCode.INVALID_DEFINITION, "refused by a guard", errors=("src/Scene.tsx:2: network_api",)), 400, "invalid_definition"),
])
async def test_a_refusal_is_a_typed_envelope_with_the_real_cause(error, status, code):
    client = await client_for(core_of(FakePlayer(raises=error)))
    try:
        response = await client.get(f"{PREFIX}/player/{ID}/1")
        body = await response.json()
        assert response.status == status and body["error"]["code"] == code and body["error"]["message"]
    finally:
        await client.close()


async def test_a_compile_error_carries_its_diagnostics_and_its_status():
    error = RemotionCompileError(CompileErrorCode.SOURCE_ERROR, "src/Scene.tsx:3:5: Unexpected token",
                                 diagnostics=(CompileDiagnostic("src/Scene.tsx", 3, 5, "Unexpected token"),))
    client = await client_for(core_of(FakePlayer(raises=error)))
    try:
        response = await client.get(f"{PREFIX}/player/{ID}/1")
        body = await response.json()
        assert response.status == 422 and body["error"]["code"] == "compile_source_error"
        assert body["error"]["diagnostics"] == [{"file": "src/Scene.tsx", "line": 3, "column": 5, "text": "Unexpected token"}]
    finally:
        await client.close()


async def test_a_core_that_is_not_ready_says_so():
    client = await client_for(core_of(ready=False))
    try:
        assert (await client.get(PREFIX + "/sandbox")).status == 503
    finally:
        await client.close()


async def test_the_prefab_bundle_of_a_remotion_source_is_a_kind_and_nothing_executable():
    prefabs = FakePrefabs(remotion=True)
    client = await client_for(core_of(prefabs=prefabs))
    try:
        response = await client.get(f"/v1/prefabs/{ID}/1/bundle")
        assert response.status == 200 and await response.json() == {"kind": "remotion", "id": ID, "version": 1, "title": "Une scène"}
        assert prefabs.bundled == 0, "the HTML bundle builder was never asked about a Remotion source"
    finally:
        await client.close()


async def test_the_prefab_bundle_of_an_html_prefab_is_unchanged():
    prefabs = FakePrefabs(remotion=False)
    client = await client_for(core_of(prefabs=prefabs))
    try:
        response = await client.get("/v1/prefabs/jarvis.counter/1/bundle")
        body = await response.json()
        assert response.status == 200 and body["fingerprint"] == "f" * 64 and "kind" not in body and prefabs.bundled == 1
        assert response.headers["ETag"]
    finally:
        await client.close()
