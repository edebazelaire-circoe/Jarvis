"""`/v1/mcp/plugins*` de bout en bout : routes, authentification, codes stables (Slice 02 ; `docs/mcp/plugins.md` §8)."""

from __future__ import annotations

import json
import socket

import aiohttp
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.mcp_plugins import McpErrorCode
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import MAX_MCP_BODY_BYTES, LocalProtocolServer
from tests.fakes.fake_sealer import FakeSealer

TOKEN = "t" * 48
CIRCUIT = "https://circoetoolbox-server-production.up.railway.app/mcp"
PLUGIN_ID = "circoetoolbox-server-production"


async def _stack(tmp_path, sealer):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path, sealer=sealer)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    return core, server, LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN), f"http://127.0.0.1:{port}"


@pytest.fixture
async def stack(tmp_path):
    core, server, client, base = await _stack(tmp_path, FakeSealer())
    try:
        yield core, client, base
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def _raw(method: str, url: str, *, token: str = TOKEN, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


async def test_list_starts_empty_with_vault_and_revision(stack):
    _, client, _ = stack
    listing = await client.list_mcp_plugins()
    assert listing["plugins"] == [] and listing["vault_available"] is True
    assert isinstance(listing["catalog_revision"], int)


async def test_crud_round_trip(stack):
    _, client, base = stack
    status, created = await _raw("POST", base + "/v1/mcp/plugins", json={"endpoint": CIRCUIT})
    assert status == 201 and created["plugin"]["plugin_id"] == PLUGIN_ID
    assert "credential_ref" not in created["plugin"]
    assert (await client.get_mcp_plugin(PLUGIN_ID))["plugin"]["endpoint"] == CIRCUIT
    updated = await client.update_mcp_plugin(PLUGIN_ID, enabled=False, display_name="Circuit")
    assert (updated["plugin"]["enabled"], updated["plugin"]["display_name"]) == (False, "Circuit")
    assert updated["plugin"]["connection_status"] == "disconnected"
    credential = await client.set_mcp_plugin_credential(PLUGIN_ID, strategy="bearer", value="v")
    assert credential["plugin"]["auth_strategy"] == "bearer" and "credential_ref" not in credential["plugin"]
    disconnected = await client.disconnect_mcp_plugin(PLUGIN_ID)
    assert disconnected["plugin"]["enabled"] is False and disconnected["plugin"]["auth_strategy"] == "none"
    assert await client.delete_mcp_plugin(PLUGIN_ID) == {"removed": PLUGIN_ID}
    assert (await client.list_mcp_plugins())["plugins"] == []


@pytest.mark.parametrize("method, path", [
    ("GET", "/v1/mcp/plugins"),
    ("POST", "/v1/mcp/plugins"),
    ("GET", f"/v1/mcp/plugins/{PLUGIN_ID}"),
    ("PATCH", f"/v1/mcp/plugins/{PLUGIN_ID}"),
    ("DELETE", f"/v1/mcp/plugins/{PLUGIN_ID}"),
    ("PUT", f"/v1/mcp/plugins/{PLUGIN_ID}/credential"),
    ("POST", f"/v1/mcp/plugins/{PLUGIN_ID}/disconnect"),
])
async def test_every_route_needs_the_token(stack, method, path):
    _, _, base = stack
    status, body = await _raw(method, base + path, token="wrong" * 10, json={"endpoint": CIRCUIT})
    assert status == 401 and body["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("call, status, code", [
    (lambda c: c.get_mcp_plugin("nope"), 404, "mcp_plugin_unknown"),
    (lambda c: c.update_mcp_plugin("nope", enabled=True), 404, "mcp_plugin_unknown"),
    (lambda c: c.delete_mcp_plugin("nope"), 404, "mcp_plugin_unknown"),
    (lambda c: c.disconnect_mcp_plugin("nope"), 404, "mcp_plugin_unknown"),
    (lambda c: c.set_mcp_plugin_credential("nope", strategy="bearer", value="x"), 404, "mcp_plugin_unknown"),
    (lambda c: c.create_mcp_plugin("http://mail.example.com/"), 400, "mcp_endpoint_invalid"),
    (lambda c: c.create_mcp_plugin("https://169.254.169.254/"), 400, "mcp_endpoint_forbidden"),
    (lambda c: c.create_mcp_plugin("https://x.example.com/", display_name="y" * 65), 400, "mcp_plugin_invalid"),
])
async def test_refusals_keep_their_stable_code_and_status(stack, call, status, code):
    _, client, _ = stack
    with pytest.raises(CoreProtocolError) as refusal:
        await call(client)
    assert (refusal.value.status, refusal.value.code) == (status, code)


async def test_duplicate_is_409(stack):
    _, client, _ = stack
    await client.create_mcp_plugin(CIRCUIT)
    with pytest.raises(CoreProtocolError) as refusal:
        await client.create_mcp_plugin(CIRCUIT.replace("https://", "HTTPS://"))
    assert (refusal.value.status, refusal.value.code) == (409, "mcp_plugin_duplicate")


async def test_invalid_endpoint_says_why(stack):
    _, client, _ = stack
    with pytest.raises(CoreProtocolError) as refusal:
        await client.create_mcp_plugin("https://mail.example.com/mcp#x")
    assert "fragment" in refusal.value.message


@pytest.mark.parametrize("method, suffix, body", [
    ("POST", "", {}),
    ("POST", "", {"endpoint": CIRCUIT, "surprise": 1}),
    ("POST", "", [CIRCUIT]),
    ("PATCH", f"/{PLUGIN_ID}", {}),
    ("PATCH", f"/{PLUGIN_ID}", {"enabled": "false"}),
    ("PATCH", f"/{PLUGIN_ID}", {"connection_status": "connected"}),
    ("PUT", f"/{PLUGIN_ID}/credential", {"strategy": "bearer"}),
    ("PUT", f"/{PLUGIN_ID}/credential", {"strategy": "oauth", "value": "x"}),
    ("POST", f"/{PLUGIN_ID}/disconnect", {"force": True}),
])
async def test_malformed_bodies_are_400_mcp_plugin_invalid(stack, method, suffix, body):
    _, client, base = stack
    await client.create_mcp_plugin(CIRCUIT)
    status, answer = await _raw(method, base + "/v1/mcp/plugins" + suffix, json=body)
    assert (status, answer["error"]["code"]) == (400, "mcp_plugin_invalid")


async def test_bad_json_and_oversized_bodies(stack):
    _, _, base = stack
    status, answer = await _raw("POST", base + "/v1/mcp/plugins", data=b"{not json")
    assert (status, answer["error"]["code"]) == (400, "mcp_plugin_invalid")
    big = b'{"endpoint":"' + b"a" * MAX_MCP_BODY_BYTES + b'"}'
    status, answer = await _raw("POST", base + "/v1/mcp/plugins", data=big)
    assert (status, answer["error"]["code"]) == (400, "mcp_plugin_invalid")


async def test_body_refusals_are_journaled_by_code_only(tmp_path):
    sink = []

    class Sink:
        def emit(self, kind, message, *, level="info", data=None):
            sink.append((kind, dict(data or {})))

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path, sealer=FakeSealer(), diagnostics=Sink())
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    base = f"http://127.0.0.1:{port}"
    try:
        await _raw("POST", base + "/v1/mcp/plugins", json={"endpoint": CIRCUIT})
        await _raw("POST", base + "/v1/mcp/plugins", data=b'{"endpoint": "SENTINEL-SECRET-7f3a"')
        await _raw("PUT", base + f"/v1/mcp/plugins/{PLUGIN_ID}/credential",
                   json={"strategy": "bearer", "value": "SENTINEL-SECRET-7f3a", "surprise": 1})
        await _raw("GET", base + "/v1/mcp/plugins?x=1")
    finally:
        await server.stop()
        await core.stop()
    refused = [data for kind, data in sink if kind == "mcp.plugin.refused"]
    assert refused == [
        {"operation": "POST /v1/mcp/plugins", "code": "mcp_plugin_invalid"},
        {"operation": "PUT /v1/mcp/plugins/{plugin_id}/credential", "code": "mcp_plugin_invalid",
         "plugin_id": PLUGIN_ID},
        {"operation": "GET /v1/mcp/plugins", "code": "mcp_plugin_invalid"},
    ]
    assert "SENTINEL-SECRET-7f3a" not in json.dumps(sink)


async def test_query_parameters_are_refused(stack):
    _, _, base = stack
    status, answer = await _raw("GET", base + "/v1/mcp/plugins?x=1")
    assert (status, answer["error"]["code"]) == (400, "mcp_plugin_invalid")


async def test_enable_and_disconnect_axes_stay_independent(stack):
    core, client, _ = stack
    await client.create_mcp_plugin(CIRCUIT)
    await client.update_mcp_plugin(PLUGIN_ID, enabled=False)
    after = (await client.disconnect_mcp_plugin(PLUGIN_ID))["plugin"]
    assert after["enabled"] is False
    after = (await client.update_mcp_plugin(PLUGIN_ID, enabled=True))["plugin"]
    assert (after["enabled"], after["connection_status"], after["auth_status"]) == (True, "disconnected", "unknown")


async def test_disconnect_of_an_enabled_plugin_keeps_it_enabled(stack):
    _, client, _ = stack
    created = (await client.create_mcp_plugin(CIRCUIT))["plugin"]
    assert created["enabled"] is True
    await client.set_mcp_plugin_credential(PLUGIN_ID, strategy="bearer", value="v")
    after = (await client.disconnect_mcp_plugin(PLUGIN_ID))["plugin"]
    assert (after["enabled"], after["connection_status"], after["auth_strategy"]) == (True, "disconnected", "none")
    assert (await client.get_mcp_plugin(PLUGIN_ID))["plugin"]["enabled"] is True


async def test_list_revision_moves_after_a_change(stack):
    _, client, _ = stack
    before = (await client.list_mcp_plugins())["catalog_revision"]
    await client.create_mcp_plugin(CIRCUIT)
    assert (await client.list_mcp_plugins())["catalog_revision"] == before + 1


async def test_vault_unavailable_is_409_and_listing_says_so(tmp_path):
    core, server, client, _ = await _stack(tmp_path, None)
    try:
        assert (await client.list_mcp_plugins())["vault_available"] is False
        await client.create_mcp_plugin(CIRCUIT)
        with pytest.raises(CoreProtocolError) as refusal:
            await client.set_mcp_plugin_credential(PLUGIN_ID, strategy="bearer", value="x")
        assert (refusal.value.status, refusal.value.code) == (409, "mcp_vault_unavailable")
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def test_damaged_row_is_500_with_the_store_code(stack):
    core, client, _ = stack
    await client.create_mcp_plugin(CIRCUIT)

    def damage(conn):
        conn.execute("UPDATE mcp_plugins SET data='{}'")

    await core.state.run_serialized(damage)
    with pytest.raises(CoreProtocolError) as refusal:
        await client.list_mcp_plugins()
    assert (refusal.value.status, refusal.value.code) == (500, "mcp_plugin_store_unreadable")


async def test_connecting_rows_are_reset_at_core_start(tmp_path):
    core, server, client, _ = await _stack(tmp_path, FakeSealer())
    try:
        await client.create_mcp_plugin(CIRCUIT)

        def stuck(conn):
            conn.execute("UPDATE mcp_plugins SET connection_status='connecting', "
                         "data=json_set(data,'$.connection_status','connecting')")

        await core.state.run_serialized(stuck)
    finally:
        await client.close()
        await server.stop()
        await core.stop()
    core, server, client, _ = await _stack(tmp_path, FakeSealer())
    try:
        assert (await client.get_mcp_plugin(PLUGIN_ID))["plugin"]["connection_status"] == "disconnected"
    finally:
        await client.close()
        await server.stop()
        await core.stop()


# ------------------------------------------------------------------ Slice 03 : connect, refresh, retour OAuth

from tests.fakes.scripted_mcp_connector import AUTH_URL, ISSUER, SENTINEL, ScriptedConnector  # noqa: E402

NEW_ROUTES = [
    ("POST", f"/v1/mcp/plugins/{PLUGIN_ID}/connect"),
    ("POST", f"/v1/mcp/plugins/{PLUGIN_ID}/refresh"),
    ("POST", "/v1/mcp/oauth/callback"),
]


@pytest.mark.parametrize("method, path", NEW_ROUTES)
async def test_new_routes_need_the_token(stack, method, path):
    _, _, base = stack
    status, body = await _raw(method, base + path, token="wrong" * 10, json={})
    assert status == 401 and body["error"]["code"] == "unauthorized"


async def test_without_a_connector_the_new_routes_answer_503(stack):
    _, client, _ = stack
    await client.create_mcp_plugin(CIRCUIT)
    for call in (client.connect_mcp_plugin(PLUGIN_ID), client.refresh_mcp_plugin(PLUGIN_ID),
                 client.complete_mcp_oauth(state="s", code="c")):
        with pytest.raises(CoreProtocolError) as refusal:
            await call
        assert (refusal.value.status, refusal.value.code) == (503, "mcp_connector_unavailable")


async def _connected_stack(tmp_path, connector):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path, sealer=FakeSealer(), connector=connector)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    return core, server, LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN), f"http://127.0.0.1:{port}"


@pytest.fixture
async def scripted(tmp_path):
    connector = ScriptedConnector()
    core, server, client, base = await _connected_stack(tmp_path, connector)
    try:
        yield connector, client, base
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def test_connect_200_then_refresh(scripted):
    connector, client, base = scripted
    await client.create_mcp_plugin(CIRCUIT)
    status, body = await _raw("POST", base + f"/v1/mcp/plugins/{PLUGIN_ID}/connect", json={"strategy": "none"})
    assert status == 200 and body["status"] == "connected" and "authorization_url" not in body
    assert body["plugin"]["connection_status"] == "connected" and "credential_ref" not in body["plugin"]
    refreshed = await client.refresh_mcp_plugin(PLUGIN_ID)
    assert refreshed["plugin"]["tools"][0]["tool_id"] == f"{PLUGIN_ID}.search"


async def test_connect_202_then_callback_and_nothing_secret_in_bodies(scripted):
    connector, client, base = scripted
    connector.plan = ["authorize"]
    await client.create_mcp_plugin(CIRCUIT)
    status, started = await _raw("POST", base + f"/v1/mcp/plugins/{PLUGIN_ID}/connect")
    assert status == 202
    assert started["status"] == "authorizing" and started["authorization_url"] == AUTH_URL.format(state="st1")
    status, done = await _raw("POST", base + "/v1/mcp/oauth/callback",
                              json={"state": "st1", "code": "c", "iss": ISSUER})
    assert status == 200 and done["plugin"]["auth_status"] == "authorized"
    status, replay = await _raw("POST", base + "/v1/mcp/oauth/callback",
                                json={"state": "st1", "code": "c", "iss": ISSUER})
    assert (status, replay["error"]["code"]) == (400, "mcp_oauth_state_invalid")
    listed = await client.list_mcp_plugins()
    for body in (started, done, replay, listed):
        assert SENTINEL not in json.dumps(body)


async def test_callback_with_an_as_error_is_400_denied(scripted):
    connector, client, base = scripted
    connector.plan = ["authorize"]
    await client.create_mcp_plugin(CIRCUIT)
    await client.connect_mcp_plugin(PLUGIN_ID)
    status, body = await _raw("POST", base + "/v1/mcp/oauth/callback",
                              json={"state": "st1", "error": "access_denied",
                                    "error_description": "user said no " + SENTINEL, "iss": ISSUER})
    assert (status, body["error"]["code"]) == (400, "mcp_oauth_denied")
    assert SENTINEL not in json.dumps(body)
    assert (await client.get_mcp_plugin(PLUGIN_ID))["plugin"]["auth_status"] == "failed"


@pytest.mark.parametrize("path, body", [
    (f"/v1/mcp/plugins/{PLUGIN_ID}/connect", {"strategy": "bearer"}),
    (f"/v1/mcp/plugins/{PLUGIN_ID}/connect", {"force": True}),
    (f"/v1/mcp/plugins/{PLUGIN_ID}/refresh", {"x": 1}),
    ("/v1/mcp/oauth/callback", {"code": "c"}),
    ("/v1/mcp/oauth/callback", {"state": "s", "surprise": 1}),
])
async def test_new_routes_refuse_malformed_bodies(scripted, path, body):
    _, client, base = scripted
    await client.create_mcp_plugin(CIRCUIT)
    status, answer = await _raw("POST", base + path, json=body)
    assert (status, answer["error"]["code"]) == (400, "mcp_plugin_invalid")


async def test_connect_failures_keep_their_code_and_status(scripted):
    connector, client, _ = scripted
    connector.plan = [McpErrorCode.ENDPOINT_FORBIDDEN]
    await client.create_mcp_plugin(CIRCUIT)
    with pytest.raises(CoreProtocolError) as refusal:
        await client.connect_mcp_plugin(PLUGIN_ID)
    assert (refusal.value.status, refusal.value.code) == (400, "mcp_endpoint_forbidden")
    with pytest.raises(CoreProtocolError) as disconnected:
        await client.refresh_mcp_plugin(PLUGIN_ID)
    assert (disconnected.value.status, disconnected.value.code) == (409, "mcp_plugin_disconnected")
