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


async def test_remove_deletes_row_and_credentials(env):
    build, store, _ = env
    service = build()
    plugin = await service.create(CIRCUIT)
    await service.set_static_credential(plugin.plugin_id, strategy="bearer", value=SENTINEL)
    await service.remove(plugin.plugin_id)
    assert await store.get_plugin(plugin.plugin_id) is None
    assert await store.delete_for_plugin(plugin.plugin_id) == 0
    assert await service.list_plugins() == ()


async def test_start_resets_connecting_rows_only(env):
    build, store, sink = env
    service = build()
    a = await service.create("https://a.example.com/")
    b = await service.create("https://b.example.com/")
    await store.save_plugin(mark_connection(a, ConnectionStatus.CONNECTING, now=T0 + timedelta(hours=1)))
    await store.save_plugin(mark_connection(b, ConnectionStatus.CONNECTED, now=T0 + timedelta(hours=1)))
    restarted = build()
    await restarted.start()
    assert (await store.get_plugin("a")).connection_status is ConnectionStatus.DISCONNECTED
    assert (await store.get_plugin("b")).connection_status is ConnectionStatus.CONNECTED
    assert sink.of(PLUGINS_CONNECTING_RESET) == [{"count": 1, "plugin_ids": ["a"]}]
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
