"""Relais Contexts / captures / Artifacts du Control Center (session-context-recording, Slice 09).

Contrat : `jarvis/runtime/capture_relay.py`, `docs/capture.md` › *HTTP API*. Ce
qui doit tenir : liste blanche de Core épinglée, chaque route du Control Center
relaie la route Core de même forme (et elle existe), statut et JSON rendus tels
quels, payload binaire relayé avec `Range` et borné, garde d'origine sur toutes
les méthodes, pannes de Core codées, aucun état de capture côté Control Center.
"""

from __future__ import annotations

import json

import pytest

from jarvis.protocol import client as core_client
from jarvis.protocol.capture_routes import CaptureProtocolRoutes
from jarvis.protocol.client import FORWARDABLE_PREFIXES, LocalCoreClient
from jarvis.runtime.capture_relay import GUARDED_PREFIXES, CaptureRelayRoutes
from jarvis.runtime.control_center import READ_GUARDED_ROUTES
from tests.fakes.capture_stack import TOKEN, CaptureStack


def test_the_forwardable_prefixes_are_pinned():
    """Ajouter un préfixe relayé est un choix délibéré : ce test doit changer avec lui."""

    assert FORWARDABLE_PREFIXES == ("/v1/boards", "/v1/sessions", "/v1/mcp/plugins", "/v1/mcp/oauth/callback",
                                    "/v1/contexts", "/v1/captures", "/v1/artifacts", "/v1/activity",
                                    "/v1/workspace/",  # inspection du workspace (board-memory S04), lecture seule
                                    "/v1/prefabs",  # catalogue des prefabs (prefab-foundation S03)
                                    "/v1/presentation-studio/presentations",  # Studio : lectures + edition (studio S05)
                                    "/v1/presentation-studio/playback")  # Studio : lecture d'une presentation (studio S12)
    assert not any(prefix.startswith("/v1/mcp/tools") for prefix in FORWARDABLE_PREFIXES)


async def test_the_core_client_refuses_anything_outside_its_relays():
    client = LocalCoreClient(host="127.0.0.1", port=9, token=TOKEN)
    try:
        with pytest.raises(ValueError):
            await client.forward_json("GET", "/v1/mcp/tools")
        for path in ("/v1/artifacts/jart_x", "/v1/captures/jcap_x/payload", "/v1/artifacts/jart_x/payload/x",
                     "/v1/scene/snapshot"):
            with pytest.raises(ValueError):
                await client.forward_bytes(path)
    finally:
        await client.close()


def test_every_prefix_is_guarded_for_every_method():
    assert set(GUARDED_PREFIXES) <= set(READ_GUARDED_ROUTES)


def test_every_relay_route_has_its_core_route():
    core_routes = {(route.method, route.path) for route in CaptureProtocolRoutes(object()).routes()}
    relay = CaptureRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = {(route.method, "/v1" + route.path[len("/api"):]) for route in relay.routes()}
    assert mapped == core_routes
    # Aucun état de capture dans le Control Center : un transport et un journal, rien d'autre.
    assert set(vars(relay)) == {"_transport", "_journal"}


async def test_the_relay_returns_core_status_and_bodies_unchanged(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        status, started, _ = await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
        assert status == 201 and started["capture"]["state"] == "active"
        status, busy, _ = await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
        assert (status, busy["error"]["code"]) == (409, "already_active")
        _, via_cc, _ = await stack.call("GET", "/api/captures/status")
        assert [c["capture_id"] for c in via_cc["captures"]] == [r.capture_id for r in
                                                                 stack.core.captures.status().captures]
        status, stopped, _ = await stack.call("POST", f"/api/captures/{started['capture']['capture_id']}/stop")
        assert status == 200 and stopped["capture"]["state"] == "complete"
        status, contexts, _ = await stack.call("GET", "/api/contexts")
        assert status == 200 and contexts["active_context_id"]
        status, missing, _ = await stack.call("GET", "/api/artifacts/jart_unknown")
        assert (status, missing["error"]["code"]) == (404, "artifact_not_found")
        status, page, _ = await stack.call("GET", "/api/artifacts", params={"limit": "1"})
        assert status == 200 and len(page["artifacts"]) == 1
        relayed = [e for e in stack.trace() if e.get("kind") == "capture.request.relayed"]
        assert {e["data"]["action"] for e in relayed} == {"capture_start", "capture_stop"}
        assert all("body" not in e["data"] for e in relayed)


async def test_the_status_relay_forwards_the_recent_bound(tmp_path):
    """Le rail de capture (Slice 10) lit `?recent=3` : le relais passe la borne à Core."""

    async with CaptureStack(tmp_path) as stack:
        for _ in range(4):
            _, started, _ = await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
            await stack.call("POST", f"/api/captures/{started['capture']['capture_id']}/stop")
        _, default, _ = await stack.call("GET", "/api/captures/status")
        status, bounded, _ = await stack.call("GET", "/api/captures/status", params={"recent": "3"})
        assert status == 200 and len(default["recent"]) == 4 and len(bounded["recent"]) == 3
        status, refused, _ = await stack.call("GET", "/api/captures/status", params={"recent": "21"})
        assert (status, refused["error"]["code"]) == (400, "invalid_request")


async def test_the_payload_is_relayed_in_bytes_with_its_range(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        _, shot, _ = await stack.call("POST", "/api/captures/screenshot", json={})
        artifact_id = shot["artifact"]["artifact_id"]
        response = await stack.cc.get(f"/api/artifacts/{artifact_id}/payload")
        whole = await response.read()
        assert response.status == 200 and whole.startswith(b"\x89PNG")
        assert response.headers["Content-Type"] == "image/png"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        response = await stack.cc.get(f"/api/artifacts/{artifact_id}/payload", headers={"Range": "bytes=2-5"})
        assert response.status == 206 and await response.read() == whole[2:6]
        assert response.headers["Content-Range"] == f"bytes 2-5/{len(whole)}"
        response = await stack.cc.get("/api/artifacts/jart_unknown/payload")
        assert response.status == 404 and json.loads(await response.read())["error"]["code"] == "artifact_not_found"
        response = await stack.cc.get(f"/api/artifacts/{artifact_id}/payload", params={"x": "1"})
        assert response.status == 400


async def test_a_payload_larger_than_the_relay_bound_is_never_half_sent(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        _, shot, _ = await stack.call("POST", "/api/captures/screenshot", json={})
        monkeypatch.setattr(core_client, "MAX_FORWARDED_PAYLOAD_BYTES", 8)
        status, body, _ = await stack.call("GET", f"/api/artifacts/{shot['artifact']['artifact_id']}/payload")
        assert (status, body["error"]["code"]) == (502, "payload_too_large_for_relay")


@pytest.mark.parametrize("method, path", [
    ("GET", "/api/artifacts"), ("GET", "/api/captures/status"), ("POST", "/api/captures/start"),
    ("GET", "/api/contexts"), ("GET", "/api/activity"), ("GET", "/api/artifacts/jart_x/payload"),
    ("DELETE", "/api/artifacts/jart_x"),
])
@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"},
])
async def test_every_method_is_refused_from_a_foreign_origin(tmp_path, method, path, headers):
    async with CaptureStack(tmp_path) as stack:
        status, body, _ = await stack.call(method, path, headers=headers, json={"channel": "audio"})
        assert status == 403 and body["code"] == "forbidden_origin"
        assert stack.core.captures.status().captures == ()


async def test_core_down_or_unknown_is_a_coded_503(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        await stack.server.stop()
        status, body, _ = await stack.call("GET", "/api/captures/status")
        assert (status, body["error"]["code"]) == (503, "core_unreachable")
        status, body, _ = await stack.call("GET", "/api/artifacts/jart_x/payload")
        assert (status, body["error"]["code"]) == (503, "core_unreachable")
        stack.center.sessions = None
        status, body, _ = await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
        assert (status, body["error"]["code"]) == (503, "core_unconfigured")
        await stack.server.start()
        stack.center.sessions = stack.sessions
        assert any(e.get("kind") == "capture.request.core_unreachable" for e in stack.trace())


# ------------------------------------------------------------------ rework QA Slice 09


async def test_a_repeated_query_parameter_keeps_every_value_through_the_relay(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        _, shot, _ = await stack.call("POST", "/api/captures/screenshot", json={})
        _, started, _ = await stack.call("POST", "/api/captures/start", json={"channel": "screen"})
        await stack.call("POST", f"/api/captures/{started['capture']['capture_id']}/stop")
        status, page, _ = await stack.call("GET", "/api/artifacts",
                                           params=[("kind", "screenshot"), ("kind", "screen_recording")])
        assert status == 200, page
        assert {item["kind"] for item in page["artifacts"]} == {"screenshot", "screen_recording"}


@pytest.mark.parametrize("path", ["/api/captures/..%2Fstatus", "/api/captures/jcap_x%2Fstop",
                                  "/api/artifacts/..%2F..%2Fcaptures%2Fstatus"])
async def test_relay_path_parameters_are_re_encoded_never_reinterpreted(tmp_path, path):
    """Mutant M9-22 : un `%2F` décodé ferait relayer une autre route de Core."""

    from yarl import URL

    async with CaptureStack(tmp_path) as stack:
        response = await stack.cc.request("GET", URL(path, encoded=True))
        body = json.loads(await response.read())
        assert response.status == 400 and body["error"]["code"] in {"invalid_capture", "invalid_artifact"}, body


async def test_the_payload_relay_rereads_the_token_and_replays_once_after_a_401(tmp_path, monkeypatch):
    """Mutant M9-26 : Core redémarré avec un autre jeton ; le relais binaire relit le jeton et rejoue."""

    async with CaptureStack(tmp_path) as stack:
        _, shot, _ = await stack.call("POST", "/api/captures/screenshot", json={})
        token_file = tmp_path / "core.token"
        await stack.sessions.close()
        token_file.write_text("w" * 48, encoding="utf-8")  # jeton périmé lu à la première connexion
        connect = stack.sessions._connect
        connections: list[object] = []

        def connect_then_restore():  # noqa: ANN202
            client = connect()
            if client not in connections:
                connections.append(client)
            token_file.write_text(TOKEN, encoding="utf-8")
            return client

        monkeypatch.setattr(stack.sessions, "_connect", connect_then_restore)
        response = await stack.cc.get(f"/api/artifacts/{shot['artifact']['artifact_id']}/payload")
        assert response.status == 200 and (await response.read()).startswith(b"\x89PNG")
        assert len(connections) == 2, "rejoué une fois avec le jeton relu"
