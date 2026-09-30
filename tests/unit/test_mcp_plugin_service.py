"""`McpPluginService`, partie CRUD et identifiants (Slice 02 ; `docs/mcp/plugins.md` §2.2, §3, ARCH §4.1)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from jarvis.adapters.sqlite_mcp_plugins import SQLiteMcpPluginRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.credential_vault import CredentialVault
from jarvis.core.mcp_plugin_service import (
    PLUGIN_CREATED, PLUGIN_CREDENTIAL_SET, PLUGIN_REFUSED, PLUGIN_STORE_FAILED, PLUGINS_CONNECTING_RESET,
    PLUGINS_STARTED, McpPluginService,
)
from jarvis.domain.mcp_plugins import (
    AuthStatus, AuthStrategy, ConnectionStatus, McpErrorCode, McpPluginError, mark_connection,
)
from jarvis.ports.mcp_plugins import McpPluginStoreError
from tests.fakes.fake_sealer import FakeSealer

CIRCUIT = "https://circoetoolbox-server-production.up.railway.app/mcp"
SENTINEL = "SENTINEL-SECRET-7f3a"
T0 = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, message, level, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [event[3] for event in self.events if event[0] == kind]


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
async def env(tmp_path):
    state = SQLiteStateRepository(tmp_path / "jarvis.sqlite3")
    await state.initialize()
    store = SQLiteMcpPluginRepository(state)
    sink = RecordingSink()

    def build(*, sealer=FakeSealer(), allow_loopback_http=False):
        return McpPluginService(store, CredentialVault(store, sealer, diagnostics=sink), diagnostics=sink,
                                allow_loopback_http=allow_loopback_http, clock=Clock(), revision_base=100)

    try:
        yield build, store, sink
    finally:
        await state.close()


async def code_of(awaitable) -> McpErrorCode:
    with pytest.raises(McpPluginError) as refusal:
        await awaitable
    return refusal.value.code


async def test_create_validates_and_derives_the_id(env):
    build, _, sink = env
    service = build()
    plugin = await service.create(CIRCUIT)
    assert plugin.plugin_id == "circoetoolbox-server-production"
    assert plugin.enabled and plugin.connection_status is ConnectionStatus.DISCONNECTED
    assert service.catalog_revision == 101
    assert [p.plugin_id for p in await service.list_plugins()] == [plugin.plugin_id]
    assert sink.of(PLUGIN_CREATED) == [{"plugin_id": plugin.plugin_id,
                                        "endpoint_origin": "https://circoetoolbox-server-production.up.railway.app"}]


async def test_duplicate_endpoint_after_normalization(env):
    build, _, sink = env
    service = build()
    await service.create("https://Mail.Example.com:443/mcp")
    assert await code_of(service.create("https://mail.example.com/mcp")) is McpErrorCode.PLUGIN_DUPLICATE
    assert sink.of(PLUGIN_REFUSED)[-1] == {"operation": "create", "code": "mcp_plugin_duplicate"}


async def test_same_host_other_path_gets_a_suffixed_id(env):
    build, _, _ = env
    service = build()
    first = await service.create("https://mail.example.com/a")
    second = await service.create("https://mail.example.com/b", "Mail B")
    assert (first.plugin_id, second.plugin_id, second.display_name) == ("mail", "mail-2", "Mail B")


@pytest.mark.parametrize("endpoint, code", [
    ("http://mail.example.com/", McpErrorCode.ENDPOINT_INVALID),
    ("https://10.0.0.1/", McpErrorCode.ENDPOINT_FORBIDDEN),
    ("https://mail.example.com/?token=x", McpErrorCode.ENDPOINT_INVALID),
])
async def test_create_refusals(env, endpoint, code):
    build, _, _ = env
    assert await code_of(build().create(endpoint)) is code


async def test_loopback_flag_is_injected(env):
    build, _, _ = env
    assert await code_of(build().create("http://127.0.0.1:9/mcp")) is McpErrorCode.ENDPOINT_INVALID
    assert (await build(allow_loopback_http=True).create("http://127.0.0.1:9/mcp")).plugin_id == "127"


async def test_update_enabled_never_touches_connection(env):
    build, store, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    await store.save_plugin(mark_connection(plugin, ConnectionStatus.CONNECTED, auth_status=AuthStatus.AUTHORIZED,
                                            now=T0 + timedelta(hours=1)))
    disabled = await service.update(plugin.plugin_id, enabled=False)
    assert disabled.enabled is False
    assert (disabled.connection_status, disabled.auth_status) == (ConnectionStatus.CONNECTED, AuthStatus.AUTHORIZED)
    renamed = await service.update(plugin.plugin_id, display_name="Circuit")
    assert renamed.display_name == "Circuit" and renamed.enabled is False


@pytest.mark.parametrize("kwargs", [{}, {"enabled": "yes"}, {"display_name": 3}, {"display_name": "x" * 65}])
async def test_update_refusals(env, kwargs):
    build, _, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.update(plugin.plugin_id, **kwargs)) is McpErrorCode.PLUGIN_INVALID


async def test_unknown_plugin(env):
    build, _, _ = env
    service = build()
    for call in (service.get("nope"), service.update("nope", enabled=True), service.disconnect("nope"),
                 service.remove("nope"), service.set_static_credential("nope", strategy="bearer", value="x"),
                 service.connect("nope")):
        assert await code_of(call) is McpErrorCode.PLUGIN_UNKNOWN


async def test_static_credential_is_sealed_and_replaced(env):
    build, store, sink = env
    service = build()
    plugin = await service.create(CIRCUIT)
    first = await service.set_static_credential(plugin.plugin_id, strategy="bearer", value=SENTINEL)
    assert (first.auth_strategy, first.auth_status) == (AuthStrategy.BEARER, AuthStatus.UNKNOWN)
    second = await service.set_static_credential(plugin.plugin_id, strategy="header", header_name="X-Api-Key",
                                                 value="other")
    assert second.credential_ref != first.credential_ref
    assert await store.get(first.credential_ref) is None  # the old blob is gone
    assert await service._vault.get_secret(second) == {"kind": "static",
                                                        "static": {"header_name": "X-Api-Key", "value": "other"}}
    assert sink.of(PLUGIN_CREDENTIAL_SET)[-1] == {"plugin_id": plugin.plugin_id, "strategy": "header"}
    assert SENTINEL not in json.dumps(sink.events)


@pytest.mark.parametrize("kwargs", [
    {"strategy": "oauth", "value": "x"},
    {"strategy": "none", "value": "x"},
    {"strategy": "bearer", "header_name": "X-A", "value": "x"},
    {"strategy": "header", "value": "x"},
    {"strategy": "header", "header_name": "Cookie", "value": "x"},
    {"strategy": "header", "header_name": "mcp-session-id", "value": "x"},
    {"strategy": "header", "header_name": "X Bad", "value": "x"},
    {"strategy": "bearer", "value": ""},
    {"strategy": "bearer", "value": "a\r\nb"},
    {"strategy": "bearer", "value": "x" * 4097},
    {"strategy": "bearer", "value": 42},
])
async def test_static_credential_refusals(env, kwargs):
    build, store, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.set_static_credential(plugin.plugin_id, **kwargs)) is McpErrorCode.PLUGIN_INVALID
    assert await store.delete_for_plugin(plugin.plugin_id) == 0


async def test_vault_unavailable_refuses_static_credentials(env):
    build, store, _ = env
    service = build(sealer=None)
    assert service.vault_available is False
    plugin = await service.create(CIRCUIT)  # a `none` plugin stays possible
    assert await code_of(service.set_static_credential(plugin.plugin_id, strategy="bearer", value=SENTINEL)) \
        is McpErrorCode.VAULT_UNAVAILABLE
    assert (await service.get(plugin.plugin_id)).credential_ref is None
    assert await store.delete_for_plugin(plugin.plugin_id) == 0


async def test_failed_plugin_write_discards_the_new_blob(env, monkeypatch):
    build, store, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)

    async def refuse(value):
        raise McpPluginStoreError("mcp_plugins", value.plugin_id, "s2 injected failure")

    monkeypatch.setattr(store, "save_plugin", refuse)
    with pytest.raises(McpPluginStoreError):
        await service.set_static_credential(plugin.plugin_id, strategy="bearer", value=SENTINEL)
    assert await store.delete_for_plugin(plugin.plugin_id) == 0


async def test_disconnect_forgets_credentials_and_keeps_enabled(env):
    build, store, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    await service.update(plugin.plugin_id, enabled=False)
    await service.set_static_credential(plugin.plugin_id, strategy="bearer", value=SENTINEL)
    gone = await service.disconnect(plugin.plugin_id)
    assert gone.enabled is False
    assert (gone.credential_ref, gone.auth_strategy, gone.connection_status) == (
        None, AuthStrategy.NONE, ConnectionStatus.DISCONNECTED)
    assert await store.delete_for_plugin(plugin.plugin_id) == 0
    assert await store.get_plugin(plugin.plugin_id) == gone


async def test_disconnect_of_an_enabled_plugin_keeps_it_enabled(env):
    build, store, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    await service.set_static_credential(plugin.plugin_id, strategy="bearer", value=SENTINEL)
    assert (await service.get(plugin.plugin_id)).enabled is True
    gone = await service.disconnect(plugin.plugin_id)
    assert gone.enabled is True and gone.credential_ref is None
    assert (await store.get_plugin(plugin.plugin_id)).enabled is True


async def test_remove_deletes_row_and_credentials(env):
    build, store, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    await service.set_static_credential(plugin.plugin_id, strategy="bearer", value=SENTINEL)
    await service.remove(plugin.plugin_id)
    assert await store.get_plugin(plugin.plugin_id) is None
    assert await store.delete_for_plugin(plugin.plugin_id) == 0
    assert await service.list_plugins() == ()


async def test_start_resets_live_looking_rows_only(env):
    # Slice 03: a Core that stopped holds no session, so `connected` is reset
    # like `connecting`; `error` keeps its code for the UI.
    build, store, sink = env
    service = build()
    a = await service.create("https://a.example.com/")
    b = await service.create("https://b.example.com/")
    c = await service.create("https://c.example.com/")
    await store.save_plugin(mark_connection(a, ConnectionStatus.CONNECTING, now=T0 + timedelta(hours=1)))
    await store.save_plugin(mark_connection(b, ConnectionStatus.CONNECTED, auth_status=AuthStatus.AUTHORIZED,
                                            now=T0 + timedelta(hours=1)))
    await store.save_plugin(mark_connection(c, ConnectionStatus.ERROR, error_code=McpErrorCode.REMOTE_TIMEOUT,
                                            now=T0 + timedelta(hours=1)))
    restarted = build()
    await restarted.start()
    assert (await store.get_plugin("a")).connection_status is ConnectionStatus.DISCONNECTED
    reset_b = await store.get_plugin("b")
    assert (reset_b.connection_status, reset_b.auth_status) == (ConnectionStatus.DISCONNECTED, AuthStatus.AUTHORIZED)
    assert (await store.get_plugin("c")).last_error_code is McpErrorCode.REMOTE_TIMEOUT
    assert sink.of(PLUGINS_CONNECTING_RESET) == [{"count": 2, "plugin_ids": ["a", "b"]}]
    assert sink.of(PLUGINS_STARTED)[-1] == {"vault_available": True, "connector": False, "allow_loopback_http": False}


async def test_start_survives_an_unreadable_registry(env, monkeypatch):
    build, store, sink = env
    service = build()

    async def broken():
        raise McpPluginStoreError("mcp_plugins", "x", "damaged")

    monkeypatch.setattr(store, "list_plugins", broken)
    await service.start()  # does not raise
    assert sink.of(PLUGIN_STORE_FAILED)[-1]["operation"] == "start"


async def test_connector_dependent_operations_answer_503(env):
    build, _, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    for call in (service.connect(plugin.plugin_id), service.refresh(plugin.plugin_id),
                 service.complete_oauth("c", "s", None), service.external_tools(None),
                 service.call("x.y", {}, caller={"agent": "claude"})):
        assert await code_of(call) is McpErrorCode.CONNECTOR_UNAVAILABLE


async def test_revision_moves_on_every_change(env):
    build, _, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    start = service.catalog_revision
    await service.update(plugin.plugin_id, enabled=False)
    await service.update(plugin.plugin_id, enabled=False)  # no-op: no bump
    await service.disconnect(plugin.plugin_id)
    await service.remove(plugin.plugin_id)
    assert service.catalog_revision == start + 3


async def test_random_revision_base_differs_between_services(env):
    _, store, _ = env
    bases = {McpPluginService(store, CredentialVault(store, None)).catalog_revision for _ in range(5)}
    assert len(bases) > 1 and all(base > 0 for base in bases)


def test_public_view_of_a_service_plugin_has_no_ref():
    from jarvis.domain.mcp_plugins import new_plugin
    plugin = replace(new_plugin(CIRCUIT, plugin_id="c", display_name=None, now=T0), credential_ref="cred_" + "d" * 32)
    assert "credential_ref" not in plugin.public_view()


# ------------------------------------------------------------------ Slice 03 : connexion, OAuth, reprise, démarrage

import asyncio  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from jarvis.core import mcp_plugin_service as service_module  # noqa: E402
from jarvis.core.mcp_plugin_service import (  # noqa: E402
    PLUGIN_CONNECTION_FAILED, PLUGIN_EXPIRED_AT_BOOT, PLUGIN_RECONNECT_SCHEDULED, PLUGIN_REVOCATION_FAILED,
    PLUGIN_REVOKED, PLUGIN_TOOL_CALLED,
)
from tests.fakes.scripted_mcp_connector import AUTH_URL, ISSUER, ScriptedConnector  # noqa: E402

@pytest.fixture
async def live(tmp_path):
    state = SQLiteStateRepository(tmp_path / "live.sqlite3")
    await state.initialize()
    store = SQLiteMcpPluginRepository(state)
    sink = RecordingSink()
    services = []
    clock = {"mono": 1000.0}

    def build(connector, *, sealer=None, backoff=(0.01, 0.02), ttl=300.0, wait=2.0):
        service = McpPluginService(store, CredentialVault(store, sealer or FakeSealer(), diagnostics=sink),
                                   connector=connector, diagnostics=sink, clock=Clock(), revision_base=100,
                                   backoff_s=backoff, connect_wait_s=wait, authorization_ttl_s=ttl,
                                   monotonic=lambda: clock["mono"])
        services.append(service)
        return service

    try:
        yield build, store, sink, clock
    finally:
        for service in services:
            await service.stop()
        await state.close()


async def _eventually(predicate, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


async def test_connect_none_is_connected_and_interactive_only_once(live):
    build, _, _, _ = live
    connector = ScriptedConnector("ok")
    service = build(connector)
    plugin = await service.create(CIRCUIT)
    outcome = await service.connect(plugin.plugin_id, strategy="none")
    assert outcome.status == "connected" and outcome.authorization_url is None
    assert (outcome.plugin.auth_status, outcome.plugin.auth_strategy) == (AuthStatus.NOT_REQUIRED, AuthStrategy.NONE)
    assert outcome.plugin.tools[0]["tool_id"] == f"{plugin.plugin_id}.search"
    assert connector.opens == [("none", True)]


@pytest.mark.parametrize("strategy", ["bearer", 3, "header"])
async def test_connect_strategy_must_be_auto_none_or_oauth(live, strategy):
    build, _, _, _ = live
    service = build(ScriptedConnector())
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.connect(plugin.plugin_id, strategy=strategy)) is McpErrorCode.PLUGIN_INVALID


async def test_connect_refuses_a_disabled_plugin_and_oauth_without_vault(live):
    build, _, _, _ = live
    service = build(ScriptedConnector(), sealer=FakeSealer(available=False))
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.connect(plugin.plugin_id, strategy="oauth")) is McpErrorCode.VAULT_UNAVAILABLE
    await service.update(plugin.plugin_id, enabled=False)
    assert await code_of(service.connect(plugin.plugin_id)) is McpErrorCode.PLUGIN_DISABLED


async def test_oauth_connect_answers_the_authorization_url_then_completes(live):
    build, _, sink, _ = live
    service = build(ScriptedConnector("authorize"))
    plugin = await service.create(CIRCUIT)
    outcome = await service.connect(plugin.plugin_id)
    assert outcome.status == "authorizing" and outcome.authorization_url == AUTH_URL.format(state="st1")
    assert outcome.plugin.auth_status is AuthStatus.AUTHORIZING
    done = await service.complete_oauth("the-code", "st1", ISSUER)
    assert (done.connection_status, done.auth_status, done.auth_strategy) == (
        ConnectionStatus.CONNECTED, AuthStatus.AUTHORIZED, AuthStrategy.OAUTH)
    sealed = (await service._vault.get_secret(done))["oauth"]
    assert sealed["code_seen"] == "the-code" and sealed["tokens"]["access_token"] == SENTINEL
    assert SENTINEL not in json.dumps(sink.events) and SENTINEL not in json.dumps(done.public_view())
    assert "st1" not in json.dumps(sink.events)  # neither the state nor the URL is journaled


@pytest.mark.parametrize("state, iss, code", [
    ("unknown", ISSUER, McpErrorCode.OAUTH_STATE_INVALID),
    ("st1", "https://evil.example.com", McpErrorCode.OAUTH_ISSUER_MISMATCH),
    ("st1", None, McpErrorCode.OAUTH_ISSUER_MISMATCH),
    (42, ISSUER, McpErrorCode.OAUTH_STATE_INVALID),
])
async def test_complete_oauth_refusals(live, state, iss, code):
    build, _, _, _ = live
    service = build(ScriptedConnector("authorize"))
    plugin = await service.create(CIRCUIT)
    await service.connect(plugin.plugin_id)
    assert await code_of(service.complete_oauth("c", state, iss)) is code


async def test_state_is_single_use(live):
    build, _, _, _ = live
    service = build(ScriptedConnector("authorize"))
    plugin = await service.create(CIRCUIT)
    await service.connect(plugin.plugin_id)
    await service.complete_oauth("c", "st1", ISSUER)
    assert await code_of(service.complete_oauth("c", "st1", ISSUER)) is McpErrorCode.OAUTH_STATE_INVALID


async def test_expired_state_is_refused(live):
    build, _, _, clock = live
    service = build(ScriptedConnector("authorize"), ttl=300.0)
    plugin = await service.create(CIRCUIT)
    await service.connect(plugin.plugin_id)
    clock["mono"] += 301
    assert await code_of(service.complete_oauth("c", "st1", ISSUER)) is McpErrorCode.OAUTH_STATE_INVALID


async def test_access_denied_fails_without_retry(live):
    build, _, sink, _ = live
    service = build(ScriptedConnector("authorize"))
    plugin = await service.create(CIRCUIT)
    await service.connect(plugin.plugin_id)
    assert await code_of(service.complete_oauth(None, "st1", ISSUER, "access_denied")) is McpErrorCode.OAUTH_DENIED
    failed = await service.get(plugin.plugin_id)
    assert (failed.auth_status, failed.last_error_code) == (AuthStatus.FAILED, McpErrorCode.OAUTH_DENIED)
    assert sink.of(PLUGIN_RECONNECT_SCHEDULED) == []


async def test_transport_failures_back_off_then_reconnect_non_interactively(live):
    build, _, sink, _ = live
    connector = ScriptedConnector(McpErrorCode.REMOTE_UNREACHABLE, McpErrorCode.REMOTE_TIMEOUT, "ok")
    service = build(connector, backoff=(0.01, 0.02, 0.05))
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.connect(plugin.plugin_id, strategy="none")) is McpErrorCode.REMOTE_UNREACHABLE

    async def connected():
        return (await service.get(plugin.plugin_id)).connection_status is ConnectionStatus.CONNECTED

    await _eventually(connected)
    assert [e["delay_s"] for e in sink.of(PLUGIN_RECONNECT_SCHEDULED)] == [0.01, 0.02]
    assert connector.opens == [("none", True), ("none", None), ("none", None)]


async def test_authorization_failures_are_not_retried(live):
    build, _, sink, _ = live
    service = build(ScriptedConnector(McpErrorCode.REAUTHORIZATION_REQUIRED))
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.connect(plugin.plugin_id, strategy="none")) \
        is McpErrorCode.REAUTHORIZATION_REQUIRED
    assert (await service.get(plugin.plugin_id)).auth_status is AuthStatus.REQUIRED
    assert sink.of(PLUGIN_CONNECTION_FAILED)[-1]["retry"] is False


async def test_connect_answers_within_its_bound(live):
    build, _, _, _ = live
    service = build(ScriptedConnector("hang"), wait=0.2)
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.connect(plugin.plugin_id, strategy="none")) is McpErrorCode.REMOTE_TIMEOUT
    assert (await service.get(plugin.plugin_id)).last_error_code is McpErrorCode.REMOTE_TIMEOUT


async def test_list_changed_relists_and_bumps_the_revision(live):
    build, _, _, _ = live
    connector = ScriptedConnector("ok")
    service = build(connector)
    plugin = await service.create(CIRCUIT)
    first = (await service.connect(plugin.plugin_id, strategy="none")).plugin
    connector.tools.append({"name": "other", "inputSchema": {"type": "object"}})
    await connector.sessions[-1].changed()

    async def bumped():
        return (await service.get(plugin.plugin_id)).capability_revision == first.capability_revision + 1

    await _eventually(bumped)
    assert len((await service.refresh(plugin.plugin_id)).tools) == 2


async def test_refresh_needs_a_live_session(live):
    build, _, _, _ = live
    service = build(ScriptedConnector())
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.refresh(plugin.plugin_id)) is McpErrorCode.PLUGIN_DISCONNECTED


async def test_broken_session_reconnects(live):
    build, _, _, _ = live
    connector = ScriptedConnector("ok", "ok")
    service = build(connector)
    plugin = await service.create(CIRCUIT)
    await service.connect(plugin.plugin_id, strategy="none")
    session = connector.sessions[-1]
    session.code = McpErrorCode.REMOTE_PROTOCOL
    session.broken.set()

    async def reopened():
        return len(connector.sessions) == 2 and (
            await service.get(plugin.plugin_id)).connection_status is ConnectionStatus.CONNECTED

    await _eventually(reopened)


async def test_invoke_checks_state_before_any_network(live):
    build, store, sink, _ = live
    connector = ScriptedConnector("ok")
    service = build(connector)
    plugin = await service.create(CIRCUIT)
    assert await code_of(service.invoke(plugin.plugin_id, "search", {})) is McpErrorCode.PLUGIN_DISCONNECTED
    await service.connect(plugin.plugin_id, strategy="none")
    assert (await service.invoke(plugin.plugin_id, "search", {}))["isError"] is False
    assert sink.of(PLUGIN_TOOL_CALLED)[-1]["ok"] is True
    await service.update(plugin.plugin_id, enabled=False)
    assert await code_of(service.invoke(plugin.plugin_id, "search", {})) is McpErrorCode.PLUGIN_DISABLED
    await service.update(plugin.plugin_id, enabled=True)
    current = await store.get_plugin(plugin.plugin_id)
    await store.save_plugin(mark_connection(current, ConnectionStatus.CONNECTED, auth_status=AuthStatus.EXPIRED,
                                            now=T0 + timedelta(days=1)))
    assert await code_of(service.invoke(plugin.plugin_id, "search", {})) is McpErrorCode.REAUTHORIZATION_REQUIRED
    assert connector.calls == ["search"]


async def test_boot_reconnects_only_non_interactive_candidates(live):
    build, store, sink, _ = live
    seed = build(ScriptedConnector())
    none_ok = await seed.create("https://a.example.com/")
    disabled = await seed.create("https://b.example.com/")
    expired = await seed.create("https://c.example.com/")
    static = await seed.create("https://d.example.com/")
    unknown = await seed.create("https://e.example.com/")
    later = T0 + timedelta(days=1)
    await store.save_plugin(mark_connection(none_ok, ConnectionStatus.DISCONNECTED,
                                            auth_status=AuthStatus.NOT_REQUIRED, now=later))
    await store.save_plugin(mark_connection(disabled, ConnectionStatus.DISCONNECTED,
                                            auth_status=AuthStatus.NOT_REQUIRED, now=later))
    await seed.update(disabled.plugin_id, enabled=False)
    ref = await seed._vault.put_secret(expired, {"kind": "oauth", "oauth": {
        "tokens": {"access_token": "old"}, "expires_at": 1.0}})
    await store.save_plugin(replace(expired, credential_ref=ref, auth_strategy=AuthStrategy.OAUTH,
                                    auth_status=AuthStatus.AUTHORIZED, updated_at=later))
    await seed.set_static_credential(static.plugin_id, strategy="header", header_name="X-Key", value=SENTINEL)
    connector = ScriptedConnector()
    booted = build(connector)
    await booted.start()

    async def two_opened():
        return len(connector.opens) == 2

    await _eventually(two_opened)
    assert sorted(connector.opens) == [("header", None), ("none", None)]  # never interactive
    assert (await booted.get(expired.plugin_id)).auth_status is AuthStatus.EXPIRED
    assert sink.of(PLUGIN_EXPIRED_AT_BOOT)[-1] == {"plugin_id": expired.plugin_id,
                                                   "code": "mcp_plugin_reauthorization_required"}
    assert (await booted.get(unknown.plugin_id)).connection_status is ConnectionStatus.DISCONNECTED
    assert SENTINEL not in json.dumps(sink.events)


async def test_stop_is_bounded_even_with_a_hanging_owner(live, monkeypatch):
    build, _, _, _ = live
    monkeypatch.setattr(service_module, "STOP_BUDGET_S", 0.6)
    service = build(ScriptedConnector("ok", "hang"), wait=10.0)
    a = await service.create("https://a.example.com/")
    b = await service.create("https://b.example.com/")
    await service.connect(a.plugin_id, strategy="none")
    hanging = asyncio.create_task(service.connect(b.plugin_id, strategy="none"))
    await asyncio.sleep(0.05)
    loop = asyncio.get_running_loop()
    started = loop.time()
    await service.stop()
    assert loop.time() - started < 1.0
    assert await code_of(hanging) is McpErrorCode.PLUGIN_DISCONNECTED
    assert (await service.get(a.plugin_id)).connection_status is ConnectionStatus.DISCONNECTED


async def test_disconnect_revokes_best_effort_then_forgets(live):
    build, store, sink, _ = live
    connector = ScriptedConnector("authorize", "authorize")
    service = build(connector)
    plugin = await service.create(CIRCUIT)
    await service.connect(plugin.plugin_id)
    await service.complete_oauth("c", "st1", ISSUER)
    await service.disconnect(plugin.plugin_id)
    assert connector.revoked[0]["revocation_endpoint"] == ISSUER + "/revoke"
    assert sink.of(PLUGIN_REVOKED) == [{"plugin_id": plugin.plugin_id}]
    await service.connect(plugin.plugin_id)
    await service.complete_oauth("c", "st2", ISSUER)
    connector.revoke_error = McpErrorCode.REMOTE_UNREACHABLE
    gone = await service.disconnect(plugin.plugin_id)
    assert sink.of(PLUGIN_REVOCATION_FAILED)[-1] == {"plugin_id": plugin.plugin_id, "code": "mcp_remote_unreachable"}
    assert gone.credential_ref is None and await store.delete_for_plugin(plugin.plugin_id) == 0


async def test_disconnect_keeps_an_enabled_plugin_enabled(live):
    build, _, _, _ = live
    service = build(ScriptedConnector("ok"))
    plugin = await service.create(CIRCUIT)
    await service.connect(plugin.plugin_id, strategy="none")
    gone = await service.disconnect(plugin.plugin_id)
    assert gone.enabled is True and gone.connection_status is ConnectionStatus.DISCONNECTED
    assert await code_of(service.invoke(plugin.plugin_id, "search", {})) is McpErrorCode.PLUGIN_DISCONNECTED
