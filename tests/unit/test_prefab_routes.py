"""Routes de lecture du catalogue des prefabs dans Core (prefab-foundation, Slice 03).

Contrat : `jarvis/protocol/prefab_routes.py`, `docs/prefabs.md` › *Core routes*.
Vrai Core (`JarvisCoreApplication`, paquet livré + racine de données de test)
derrière le vrai `LocalProtocolServer` : jeton exigé, lignes du catalogue,
détail, version avec ou sans sources, paquet avec runtime et `ETag`, refus
codés. Un prefab inconnu du code (`test.counter`) est servi par le seul
chemin du catalogue.
"""

from __future__ import annotations

import aiohttp
import pytest

from jarvis.protocol.prefab_routes import PrefabProtocolRoutes
from tests.fakes.capture_stack import TOKEN, CaptureStack
from tests.fakes.prefabs import candidate, install_version

AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Core:
    """`async with Core(tmp_path) as core` : `core.get(path, **kw) -> (status, json, headers)` direct sur Core."""

    def __init__(self, tmp_path) -> None:
        self.stack = CaptureStack(tmp_path)
        library = tmp_path / "data" / "prefabs"
        install_version(library, "test.counter", 1)
        install_version(library, "test.netprobe", 1, source=candidate("test.netprobe"))

    async def __aenter__(self) -> "Core":
        await self.stack.__aenter__()
        self.http = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.http.close()
        await self.stack.__aexit__(*exc)

    async def get(self, path: str, *, headers: dict | None = None, **kwargs):
        async with self.http.get(self.stack.core_url + path, headers={**AUTH, **(headers or {})}, **kwargs) as response:
            body = await response.json(content_type=None) if response.status != 304 else None
            return response.status, body, response.headers.copy()  # insensible à la casse


def test_the_route_table_has_fixed_segments_first():
    routes = [(route.method, route.path) for route in PrefabProtocolRoutes(object()).routes()]
    # Slice 04 : `/v1/prefabs/events` (GET, POST) avant tout `{prefab_id}`. Slice 07 : `POST /v1/prefabs/validate`
    # (segment fixe, avant `{prefab_id}` aussi), `POST /v1/prefabs`, `POST /v1/prefabs/{prefab_id}/base-edits`.
    assert routes == [("GET", "/v1/prefabs/events"), ("POST", "/v1/prefabs/events"), ("POST", "/v1/prefabs/validate"),
                      ("GET", "/v1/prefabs"), ("POST", "/v1/prefabs"), ("GET", "/v1/prefabs/{prefab_id}"),
                      ("GET", "/v1/prefabs/{prefab_id}/{version}"), ("GET", "/v1/prefabs/{prefab_id}/{version}/bundle"),
                      ("POST", "/v1/prefabs/{prefab_id}/base-edits")]


async def test_the_catalogue_lists_a_prefab_core_code_never_names(tmp_path):
    async with Core(tmp_path) as core:
        status, body, _ = await core.get("/v1/prefabs")
        assert status == 200
        rows = {row["id"]: row for row in body["prefabs"]}
        # The package ships the base catalogue (Slice 05); the custom ones are the published fixtures.
        assert [prefab_id for prefab_id, row in rows.items() if row["class"] == "custom"] == ["test.counter",
                                                                                            "test.netprobe"]
        counter = rows["test.counter"]
        assert counter["latest_version"] == 1 and counter["class"] == "custom" and counter["family"] == "window"
        assert "data.count" in counter["input_names"] and counter["event_names"] == ["incremented", "reset_requested"]
        status, body, _ = await core.get("/v1/prefabs", params={"query": "sonde", "class": "custom", "limit": "5"})
        assert status == 200 and [row["id"] for row in body["prefabs"]] == ["test.netprobe"]
        status, body, _ = await core.get("/v1/prefabs", params={"class": "base"})
        assert status == 200 and {row["id"] for row in body["prefabs"]} >= {"jarvis.window", "jarvis.document",
                                                                             "jarvis.table"}
        assert {row["class"] for row in body["prefabs"]} == {"base"}


async def test_detail_version_and_sources(tmp_path):
    async with Core(tmp_path) as core:
        status, body, _ = await core.get("/v1/prefabs/test.counter")
        assert status == 200 and body["id"] == "test.counter" and body["version"] == 1
        assert body["publication"]["provenance"]["origin"] == "custom" and "files" not in body
        assert [row["version"] for row in body["history"]] == [1]
        status, body, _ = await core.get("/v1/prefabs/test.counter/1")
        assert status == 200 and "files" not in body
        status, body, _ = await core.get("/v1/prefabs/test.counter/1", params={"include_source": "1"})
        assert status == 200 and set(body["files"]) == {"template", "style", "behavior"}


async def test_the_bundle_carries_the_runtime_and_an_etag(tmp_path):
    async with Core(tmp_path) as core:
        status, body, headers = await core.get("/v1/prefabs/test.netprobe/1/bundle")
        assert status == 200
        assert body["manifest"]["id"] == "test.netprobe" and set(body["files"]) == {"template", "style", "behavior"}
        runtime = body["runtime"]
        assert "createShim" in runtime["shim"] and "--jv-accent" in runtime["shell_css"] and len(runtime["version"]) == 16
        assert headers["ETag"] == f'"{body["fingerprint"]}.{runtime["version"]}"'
        status, _, _ = await core.get("/v1/prefabs/test.netprobe/1/bundle", headers={"If-None-Match": headers["ETag"]})
        assert status == 304


@pytest.mark.parametrize("path, params, status, code", [
    ("/v1/prefabs/test.none", None, 404, "unknown_prefab"),
    ("/v1/prefabs/not-an-id", None, 404, "unknown_prefab"),
    ("/v1/prefabs/test.counter/9", None, 404, "unknown_version"),
    ("/v1/prefabs/test.counter/0", None, 404, "unknown_version"),
    ("/v1/prefabs/test.counter/x1", None, 404, "unknown_version"),
    ("/v1/prefabs/test.counter/12345", None, 404, "unknown_version"),
    ("/v1/prefabs/test.counter/9/bundle", None, 404, "unknown_version"),
    ("/v1/prefabs", {"limit": "51"}, 400, "invalid_request"),
    ("/v1/prefabs", {"class": "other"}, 400, "invalid_request"),
    ("/v1/prefabs", {"query": "x" * 121}, 400, "invalid_definition"),
    ("/v1/prefabs", {"unexpected": "1"}, 400, "invalid_request"),
    ("/v1/prefabs/test.counter/1", {"include_source": "yes"}, 400, "invalid_request"),
    ("/v1/prefabs/test.counter/1/bundle", {"x": "1"}, 400, "invalid_request"),
])
async def test_refusals_are_coded(tmp_path, path, params, status, code):
    async with Core(tmp_path) as core:
        got, body, _ = await core.get(path, params=params)
        assert (got, body["error"]["code"]) == (status, code)


async def test_a_tampered_version_is_refused_with_its_code(tmp_path):
    async with Core(tmp_path) as core:
        behavior = tmp_path / "data" / "prefabs" / "test.counter" / "1" / "behavior.js"
        behavior.write_bytes(behavior.read_bytes() + b"\n// edited in place\n")
        await core.get("/v1/prefabs")  # un listage relit le catalogue (docs/prefabs.md › Catalogue)
        status, body, _ = await core.get("/v1/prefabs/test.counter/1/bundle")
        assert (status, body["error"]["code"]) == (409, "tampered")


async def test_the_token_is_required(tmp_path):
    async with Core(tmp_path) as core:
        async with core.http.get(core.stack.core_url + "/v1/prefabs") as response:
            assert response.status == 401


def test_the_netprobe_fixture_is_a_valid_lf_candidate():
    """`test.netprobe` (preuve navigateur du bac à sable) suit les règles de la Slice 02, octets LF."""

    from pathlib import Path

    from jarvis.domain.prefab import parse_candidate

    bundle = parse_candidate(candidate("test.netprobe"))
    assert bundle.manifest.prefab_id == "test.netprobe" and set(bundle.manifest.events) == {"probed"}
    folder = Path(__file__).resolve().parents[1] / "fixtures" / "prefabs" / "test.netprobe" / "1"
    for name in ("manifest.json", "template.html", "style.css", "behavior.js"):
        assert b"\r\n" not in (folder / name).read_bytes(), name
    for probe in ("fetch(", "parent.document", "localStorage", "window.open(", "securitypolicyviolation"):
        assert probe in bundle.behavior, probe


# ------------------------------------------------------------------ écritures de définition (Slice 07)

async def _post(core: Core, path: str, body, *, auth: bool = True):
    headers = AUTH if auth else {}
    async with core.http.post(core.stack.core_url + path, json=body, headers=headers) as response:
        return response.status, await response.json(content_type=None)


def _library(tmp_path) -> list[str]:
    root = tmp_path / "data" / "prefabs"
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


async def test_validate_answers_without_writing(tmp_path):
    async with Core(tmp_path) as core:
        before = _library(tmp_path)
        status, body = await _post(core, "/v1/prefabs/validate", {"candidate": candidate("test.counter", id="custom.one")})
        assert status == 200 and body["ok"] is True and len(body["fingerprint"]) == 64 and body["errors"] == []
        status, body = await _post(core, "/v1/prefabs/validate", {"candidate": candidate("test.counter", title="")})
        assert status == 200 and body["ok"] is False and body["errors"] and "fingerprint" not in body
        for bad in ({}, {"candidate": {}, "extra": 1}, ["candidate"]):
            status, body = await _post(core, "/v1/prefabs/validate", bad)
            assert status == 400 and body["error"]["code"] == "invalid_request"
        assert _library(tmp_path) == before
        status, _ = await _post(core, "/v1/prefabs/validate", {"candidate": {}}, auth=False)
        assert status == 401


async def test_save_publishes_custom_and_refuses_base_ids(tmp_path):
    async with Core(tmp_path) as core:
        status, body = await _post(core, "/v1/prefabs", {"actor": "brain",
                                                         "candidate": candidate("test.counter", id="custom.one")})
        assert status == 201 and (body["prefab_id"], body["version"]) == ("custom.one", 1)
        assert body["provenance"]["origin"] == "custom" and body["provenance"]["created_by"] == {"actor": "brain"}
        status, body = await _post(core, "/v1/prefabs", {
            "actor": "brain", "candidate": candidate("test.counter", id="custom.two"),
            "derived_from": {"id": "custom.one", "version": 1}})
        assert status == 201 and body["provenance"]["origin"] == "fork"
        status, body = await _post(core, "/v1/prefabs", {"actor": "brain",
                                                         "candidate": candidate("test.counter", id="jarvis.counter")})
        assert status == 403 and body["error"]["code"] == "base_protected" and "prefab_edit_base" in body["error"]["message"]
        status, body = await _post(core, "/v1/prefabs", {"actor": "brain", "candidate": candidate(),
                                                         "derived_from": {"prefab_id": "custom.one"}})
        assert status == 400 and body["error"]["code"] == "invalid_request"
        status, body = await _post(core, "/v1/prefabs", {"actor": "system", "candidate": candidate("test.counter", id="custom.x")})
        assert status == 400 and body["error"]["code"] == "invalid_definition"
        assert not (tmp_path / "data" / "prefabs" / "jarvis.counter").exists()


async def test_base_edits_go_through_the_gate(tmp_path):
    async with Core(tmp_path) as core:
        status, base, _ = await core.get("/v1/prefabs/jarvis.checklist/1", params={"include_source": "1"})
        assert status == 200
        wanted = {"manifest": base["manifest"], **base["files"]}
        request = {"actor": "brain", "candidate": wanted, "user_request": "modifie la checklist de base",
                   "confirmed_by_user": True}
        status, body = await _post(core, "/v1/prefabs/jarvis.checklist/base-edits", request)
        assert status == 403 and body["error"]["code"] == "base_edit_unconfirmed"  # aucun tour de l'utilisateur ne le dit
        status, body = await _post(core, "/v1/prefabs/jarvis.checklist/base-edits", {**request, "actor": "user"})
        assert status == 400 and body["error"]["code"] == "invalid_definition"  # l'UI n'édite jamais une base
        status, body = await _post(core, "/v1/prefabs/jarvis.checklist/base-edits", {**request, "confirmed_by_user": "yes"})
        assert status == 403 and body["error"]["code"] == "base_edit_unconfirmed"
        status, body = await _post(core, "/v1/prefabs/jarvis.checklist/base-edits",
                                   {key: value for key, value in request.items() if key != "user_request"})
        assert status == 400 and body["error"]["code"] == "invalid_request"
        assert not (tmp_path / "data" / "prefabs" / "jarvis.checklist").exists()


@pytest.mark.parametrize("error, code", [("persist", "scene_persist_failed"), ("unavailable", "scene_unavailable")])
async def test_a_scene_that_cannot_write_an_event_answers_503_like_the_scene_route(error, code):
    """Reprise QA S04 (A10) : même statut que `POST /v1/scene/commands` (`_scene_failure`), jamais un 500."""

    import json
    from types import SimpleNamespace

    from aiohttp.test_utils import make_mocked_request

    from jarvis.ports.scene import ScenePersistenceError, SceneStoreErrorCode, SceneUnavailableError

    async def failing(_request):
        if error == "persist":
            raise ScenePersistenceError(SceneStoreErrorCode.STORAGE_IO, "scene revision 3 was not persisted")
        raise SceneUnavailableError(SceneStoreErrorCode.UNAVAILABLE, "scene is unavailable")

    routes = PrefabProtocolRoutes(SimpleNamespace(health=SimpleNamespace(ready=True)))
    response = await routes._guarded(failing)(make_mocked_request("POST", "/v1/prefabs/events"))
    assert response.status == 503 and json.loads(response.body)["error"]["code"] == code
