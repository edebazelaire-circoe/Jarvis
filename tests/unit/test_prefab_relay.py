"""Relais prefabs du Control Center (prefab-foundation, Slice 03).

Contrat : `jarvis/runtime/prefab_relay.py`, `docs/prefabs.md` › *Control Center
routes*. Ce qui doit tenir : chaque route du Control Center relaie la route
Core de même forme (et elle existe), statut et JSON de Core rendus tels
quels, `/api/prefabs` gardé sur toutes les méthodes — `Origin: null` (un cadre
de prefab, origine opaque) compris —, `CorePrefabTransport` borné à
`/v1/prefabs`, pannes de Core codées, aucun état côté Control Center.
"""

from __future__ import annotations

import pytest

from jarvis.protocol.client import FORWARDABLE_PREFIXES
from jarvis.protocol.prefab_routes import PrefabProtocolRoutes
from jarvis.runtime.control_center import READ_GUARDED_ROUTES
from jarvis.runtime.prefab_relay import GUARDED_PREFIXES, CorePrefabTransport, PrefabRelayRoutes
from tests.fakes.capture_stack import CaptureStack
from tests.fakes.prefabs import install_version


def stack_with_prefabs(tmp_path) -> CaptureStack:
    install_version(tmp_path / "data" / "prefabs", "test.counter", 1)
    return CaptureStack(tmp_path)


def test_the_prefix_is_guarded_for_every_method_and_relayable():
    assert GUARDED_PREFIXES == ("/api/prefabs",)
    assert set(GUARDED_PREFIXES) <= set(READ_GUARDED_ROUTES)
    assert "/v1/prefabs" in FORWARDABLE_PREFIXES


def test_every_relay_route_has_its_core_route():
    core_routes = {(route.method, route.path) for route in PrefabProtocolRoutes(object()).routes()}
    relay = PrefabRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = {(route.method, "/v1" + route.path[len("/api"):]) for route in relay.routes()}
    assert mapped == core_routes
    # Seule écriture : les événements des cadres (Slice 04), acteur forcé à `user`.
    assert {key for key in mapped if key[0] != "GET"} == {("POST", "/v1/prefabs/events")}
    assert set(vars(relay)) == {"_transport", "_journal"}


async def test_the_relay_returns_core_status_and_bodies_unchanged(tmp_path):
    async with stack_with_prefabs(tmp_path) as stack:
        status, body, _ = await stack.call("GET", "/api/prefabs", params={"query": "counter"})
        assert status == 200 and [row["id"] for row in body["prefabs"]] == ["test.counter"]
        status, body, _ = await stack.call("GET", "/api/prefabs/test.counter")
        assert status == 200 and body["publication"]["provenance"]["origin"] == "custom"
        status, body, _ = await stack.call("GET", "/api/prefabs/test.counter/1", params={"include_source": "1"})
        assert status == 200 and "template" in body["files"]
        status, body, _ = await stack.call("GET", "/api/prefabs/test.counter/1/bundle")
        assert status == 200 and "createShim" in body["runtime"]["shim"]
        status, body, _ = await stack.call("GET", "/api/prefabs/test.counter/7/bundle")
        assert (status, body["error"]["code"]) == (404, "unknown_version")
        status, body, _ = await stack.call("GET", "/api/prefabs/test.missing")
        assert (status, body["error"]["code"]) == (404, "unknown_prefab")
        status, body, _ = await stack.call("GET", "/api/prefabs", params={"limit": "99"})
        assert (status, body["error"]["code"]) == (400, "invalid_request")


@pytest.mark.parametrize("path", ["/api/prefabs", "/api/prefabs/test.counter", "/api/prefabs/test.counter/1",
                                  "/api/prefabs/test.counter/1/bundle"])
@pytest.mark.parametrize("headers", [
    {"Origin": "null"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"},
])
async def test_every_route_is_refused_from_a_frame_or_a_foreign_origin(tmp_path, path, headers):
    async with stack_with_prefabs(tmp_path) as stack:
        status, body, _ = await stack.call("GET", path, headers=headers)
        assert status == 403 and body["code"] == "forbidden_origin"


async def test_a_frame_cannot_write_through_the_scene_either(tmp_path):
    """`Origin: null` (cadre sandboxé) refusé aussi sur l'écriture de scène (garde générique d'écriture)."""

    async with stack_with_prefabs(tmp_path) as stack:
        status, _, text = await stack.call("POST", "/api/scene/commands", headers={"Origin": "null"}, json={})
        assert status == 403 and "forbidden origin" in text


async def test_core_down_or_unknown_is_a_coded_503(tmp_path):
    async with stack_with_prefabs(tmp_path) as stack:
        await stack.server.stop()
        status, body, _ = await stack.call("GET", "/api/prefabs/test.counter/1/bundle")
        assert (status, body["error"]["code"]) == (503, "core_unreachable")
        stack.center.sessions = None
        status, body, _ = await stack.call("GET", "/api/prefabs")
        assert (status, body["error"]["code"]) == (503, "core_unconfigured")
        unreachable = [e for e in stack.trace() if e.get("kind") == "prefab.request.core_unreachable"]
        assert unreachable and unreachable[0]["data"]["action"] == "prefab_bundle"


class Recording:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def forward(self, method, path, *, params=None, body=None, timeout_s=None):
        self.calls.append((method, path, params))
        return 200, {"ok": True}


async def test_the_typed_transport_stays_under_v1_prefabs():
    inner = Recording()
    transport = CorePrefabTransport(inner)
    await transport.search(query="table", prefab_class="base", limit=5)
    await transport.detail("jarvis.table")
    await transport.version("jarvis.table", 2, include_source=True)
    await transport.bundle("jarvis.table", 2)
    assert inner.calls == [
        ("GET", "/v1/prefabs", [("query", "table"), ("class", "base"), ("limit", "5")]),
        ("GET", "/v1/prefabs/jarvis.table", None),
        ("GET", "/v1/prefabs/jarvis.table/2", [("include_source", "1")]),
        ("GET", "/v1/prefabs/jarvis.table/2/bundle", None),
    ]
    for path in ("/v1/scene/commands", "/v1/prefabsx", "/v1/workspace/sessions"):
        with pytest.raises(ValueError):
            await transport.forward("GET", path)
