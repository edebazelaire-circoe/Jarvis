"""Connexion MCP distante de bout en bout sur le faux serveur (Slice 03 ; `docs/mcp/plugins.md` §2.2-§5).

Faux serveur MCP + faux AS sur 127.0.0.1 (ports éphémères, drapeau de
bouclage), vrai SDK `mcp`, vrai `McpPluginService`, vrai coffre (FakeSealer),
vrai journal `trace.jsonl`. Aucun accès réseau hors bouclage : le seul nom
DNS non local est résolu par un résolveur injecté.

Sentinelle : `SENTINEL-SECRET-7f3a` (jetons, bearer, en-tête, texte d'erreur
distant) ne doit apparaître ni dans `trace.jsonl`, ni dans `public_view`, ni
dans un corps HTTP de Core.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import logging
import socket
import time
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("mcp")

from jarvis.adapters.remote_mcp import SdkRemoteMcpConnector, Timeouts  # noqa: E402
from jarvis.adapters.sqlite_mcp_plugins import SQLiteMcpPluginRepository  # noqa: E402
from jarvis.adapters.sqlite_state import SQLiteStateRepository  # noqa: E402
from jarvis.core.credential_vault import CredentialVault  # noqa: E402
from jarvis.core.mcp_plugin_service import (  # noqa: E402
    PLUGIN_CONNECTION_FAILED, PLUGIN_RECONNECT_SCHEDULED, PLUGIN_TOOLS_CHANGED, McpPluginService,
)
from jarvis.core.v2_app import JarvisCoreApplication  # noqa: E402
from jarvis.domain.mcp_plugins import (  # noqa: E402
    AuthStatus, AuthStrategy, ConnectionStatus, McpErrorCode, McpPluginError,
)
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient  # noqa: E402
from jarvis.protocol.server import LocalProtocolServer  # noqa: E402
from jarvis.runtime.journal import RuntimeJournal  # noqa: E402
from tests.fakes.fake_remote_mcp import SENTINEL, FakeConfig, running_fakes, tool  # noqa: E402
from tests.fakes.fake_sealer import FakeSealer  # noqa: E402

REDIRECT = "http://127.0.0.1:17654/api/mcp/oauth/callback"
FAST = Timeouts(connect_s=2.0, read_s=5.0, handshake_s=2.0)
TOKEN = "t" * 48


class Stack:
    def __init__(self, service: McpPluginService, repo, journal: RuntimeJournal, state) -> None:
        self.service = service
        self.repo = repo
        self.journal = journal
        self.state = state

    def trace(self) -> str:
        path = self.journal.runtime_root / "trace.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def events(self, kind: str) -> list[dict]:
        rows = [json.loads(line) for line in self.trace().splitlines() if line.strip()]
        return [row.get("data", {}) for row in rows if row.get("kind") == kind]


def _connector(**kwargs) -> SdkRemoteMcpConnector:
    return SdkRemoteMcpConnector(redirect_uri=REDIRECT, allow_loopback_http=True, timeouts=FAST, **kwargs)


def _connector_with(timeouts: Timeouts) -> SdkRemoteMcpConnector:
    return SdkRemoteMcpConnector(redirect_uri=REDIRECT, allow_loopback_http=True, timeouts=timeouts)


async def _stack(tmp_path, *, connector=None, backoff=(0.05, 0.1, 0.2), connect_wait_s=5.0, ttl=300.0,
                 name="jarvis.sqlite3") -> Stack:
    state = SQLiteStateRepository(tmp_path / name)
    await state.initialize()
    repo = SQLiteMcpPluginRepository(state)
    journal = RuntimeJournal(tmp_path / "runtime")
    service = McpPluginService(repo, CredentialVault(repo, FakeSealer(), diagnostics=journal),
                               connector=connector or _connector(), diagnostics=journal, allow_loopback_http=True,
                               backoff_s=backoff, connect_wait_s=connect_wait_s, authorization_ttl_s=ttl)
    return Stack(service, repo, journal, state)


@pytest.fixture
async def make(tmp_path):
    stacks: list[Stack] = []

    async def build(**kwargs) -> Stack:
        stack = await _stack(tmp_path, **kwargs)
        stacks.append(stack)
        return stack

    try:
        yield build
    finally:
        for stack in stacks:
            await stack.service.stop()
            await stack.state.close()


async def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


async def _oauth_connect(stack: Stack, world, plugin_id: str):
    outcome = await stack.service.connect(plugin_id)
    assert outcome.status == "authorizing" and outcome.authorization_url
    callback = await world.approve(outcome.authorization_url)
    plugin = await stack.service.complete_oauth(callback.get("code"), callback["state"], callback.get("iss"),
                                                callback.get("error"))
    return outcome, callback, plugin


def _deep_schema(levels: int) -> dict:
    schema: dict = {}
    for _ in range(levels):
        schema = {"a": schema}
    return {"type": "object", "properties": schema}


def _no_sentinel(*texts: str) -> None:
    for text in texts:
        assert SENTINEL not in text


# ------------------------------------------------------------------ sans authentification


async def test_unauthenticated_plugin_connects_with_normalized_bounded_tools(make):
    config = FakeConfig(tools=[
        tool("search_mail", read_only=True), tool("send_mail"), tool("bad name!"),
        tool("huge", schema={"type": "object", "description": "x" * 17_000}),
        tool("search_mail"),  # duplicate wire name
        tool("deep", schema=_deep_schema(14)),
    ])
    async with running_fakes(config) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome = await stack.service.connect(plugin.plugin_id)
        assert outcome.status == "connected"
        connected = outcome.plugin
        assert (connected.connection_status, connected.auth_status, connected.auth_strategy) == (
            ConnectionStatus.CONNECTED, AuthStatus.NOT_REQUIRED, AuthStrategy.NONE)
        assert connected.display_name == "Fake Remote" and connected.icon_url == "https://icons.example.com/fake.png"
        assert connected.server_identity["name"] == "Fake Remote"
        assert [t["tool_id"] for t in connected.tools] == [f"{plugin.plugin_id}.search_mail",
                                                           f"{plugin.plugin_id}.send_mail"]
        assert [t["side_effect"] for t in connected.tools] == ["read", "destructive"]
        assert [dict(r) for r in connected.rejected_tools] == [
            {"name": "bad name!", "code": "mcp_tool_name_invalid"},
            {"name": "huge", "code": "mcp_tool_schema_too_large"},
            {"name": "search_mail", "code": "mcp_tool_name_invalid"},
            {"name": "deep", "code": "mcp_tool_schema_too_large"},
        ]
        assert connected.capability_revision == 1
        assert world.seen("as") == []


async def test_more_than_200_tools_are_bounded(make):
    config = FakeConfig(tools=[tool(f"t{i:03d}") for i in range(250)])
    async with running_fakes(config) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        connected = (await stack.service.connect(plugin.plugin_id)).plugin
        assert len(connected.tools) == 200
        assert {r["code"] for r in connected.rejected_tools} == {"mcp_tool_list_too_large"}
        assert len(connected.rejected_tools) == 50


async def test_list_changed_bumps_the_capability_revision(make):
    async with running_fakes() as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        before = (await stack.service.connect(plugin.plugin_id)).plugin
        revision = stack.service.catalog_revision
        world.config.tools.append(tool("new_tool", read_only=True))
        assert await world.notify_tools_changed() >= 1
        after = await _wait(lambda: _plugin_if(stack, plugin.plugin_id,
                                               lambda p: p.capability_revision == before.capability_revision + 1))
        assert f"{plugin.plugin_id}.new_tool" in [t["tool_id"] for t in after.tools]
        assert stack.service.catalog_revision > revision
        assert stack.events(PLUGIN_TOOLS_CHANGED)[-1]["capability_revision"] == before.capability_revision + 1
        # an explicit refresh without change keeps the revision
        refreshed = await stack.service.refresh(plugin.plugin_id)
        assert refreshed.capability_revision == after.capability_revision


async def _plugin_if(holder, plugin_id, predicate):
    repo = holder.repo if isinstance(holder, Stack) else holder._repository
    plugin = await repo.get_plugin(plugin_id)
    return plugin if plugin is not None and predicate(plugin) else None


# ------------------------------------------------------------------ OAuth


async def test_full_oauth_flow_seals_tokens_and_leaks_nothing(make):
    async with running_fakes(FakeConfig(auth="oauth")) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome, callback, done = await _oauth_connect(stack, world, plugin.plugin_id)
        query = {key: values[0] for key, values in parse_qs(urlsplit(outcome.authorization_url).query).items()}
        assert outcome.authorization_url.startswith(world.as_base + "/authorize?")
        assert query["code_challenge_method"] == "S256" and query["state"] == callback["state"]
        assert query["resource"] == world.rs_base + "/mcp" and query["scope"] == "mail"
        assert query["redirect_uri"] == REDIRECT
        assert outcome.plugin.auth_status is AuthStatus.AUTHORIZING
        assert (done.connection_status, done.auth_status, done.auth_strategy) == (
            ConnectionStatus.CONNECTED, AuthStatus.AUTHORIZED, AuthStrategy.OAUTH)
        assert world.registrations[0]["grant_types"] == ["authorization_code"]  # Q2
        sealed = (await stack.service._vault.get_secret(done))["oauth"]
        assert sealed["tokens"]["access_token"].startswith(SENTINEL)
        assert isinstance(sealed["expires_at"], float) and sealed["client_info"]["client_id"].startswith("client-")
        assert (sealed["issuer"], sealed["iss_supported"]) == (world.as_base, True)
        blob = (await stack.repo.get(done.credential_ref)).blob
        assert SENTINEL.encode() not in blob
        _no_sentinel(json.dumps(done.public_view()), stack.trace())
        # the static header strategy's secret never went anywhere either; the AS saw no MCP call
        assert all(seen.path != "/mcp" for seen in world.seen("as"))


async def test_refresh_grant_follows_the_as_metadata(make):
    async with running_fakes(FakeConfig(auth="oauth", grants=("authorization_code", "refresh_token"),
                                        issue_refresh=True)) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        await _oauth_connect(stack, world, plugin.plugin_id)
        assert world.registrations[0]["grant_types"] == ["authorization_code", "refresh_token"]


@pytest.mark.parametrize("case", ["wrong", "replayed", "expired"])
async def test_bad_state_is_refused(make, case, monkeypatch):
    async with running_fakes(FakeConfig(auth="oauth")) as world:
        stack = await make(ttl=0.3 if case == "expired" else 300.0)
        plugin = await stack.service.create(world.rs_base + "/mcp")
        if case == "replayed":
            _, callback, _ = await _oauth_connect(stack, world, plugin.plugin_id)
            state, code = callback["state"], callback["code"]
        else:
            outcome = await stack.service.connect(plugin.plugin_id)
            callback = await world.approve(outcome.authorization_url)
            state, code = ("forged-" + callback["state"]) if case == "wrong" else callback["state"], callback["code"]
            if case == "expired":
                await asyncio.sleep(0.5)
        with pytest.raises(McpPluginError) as refused:
            await stack.service.complete_oauth(code, state, callback.get("iss"))
        assert refused.value.code is McpErrorCode.OAUTH_STATE_INVALID


async def test_wrong_iss_is_refused_when_advertised(make):
    async with running_fakes(FakeConfig(auth="oauth", wrong_iss=True)) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome = await stack.service.connect(plugin.plugin_id)
        callback = await world.approve(outcome.authorization_url)
        with pytest.raises(McpPluginError) as refused:
            await stack.service.complete_oauth(callback["code"], callback["state"], callback["iss"])
        assert refused.value.code is McpErrorCode.OAUTH_ISSUER_MISMATCH
        failed = await stack.service.get(plugin.plugin_id)
        assert (failed.auth_status, failed.last_error_code) == (AuthStatus.FAILED, McpErrorCode.OAUTH_ISSUER_MISMATCH)
        assert not [s for s in world.seen("as") if s.path == "/token"]  # the code was never exchanged


async def test_missing_iss_is_refused_when_advertised(make):
    async with running_fakes(FakeConfig(auth="oauth")) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome = await stack.service.connect(plugin.plugin_id)
        callback = await world.approve(outcome.authorization_url)
        with pytest.raises(McpPluginError) as refused:
            await stack.service.complete_oauth(callback["code"], callback["state"], None)
        assert refused.value.code is McpErrorCode.OAUTH_ISSUER_MISMATCH


async def test_iss_not_advertised_is_not_required(make):
    async with running_fakes(FakeConfig(auth="oauth", iss_supported=False)) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        _, callback, done = await _oauth_connect(stack, world, plugin.plugin_id)
        assert "iss" not in callback and done.auth_status is AuthStatus.AUTHORIZED


async def test_access_denied_marks_the_plugin_failed(make):
    async with running_fakes(FakeConfig(auth="oauth", deny=True)) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome = await stack.service.connect(plugin.plugin_id)
        callback = await world.approve(outcome.authorization_url)
        assert callback["error"] == "access_denied"
        with pytest.raises(McpPluginError) as refused:
            await stack.service.complete_oauth(None, callback["state"], callback.get("iss"), callback["error"])
        assert refused.value.code is McpErrorCode.OAUTH_DENIED
        failed = await stack.service.get(plugin.plugin_id)
        assert (failed.auth_status, failed.connection_status, failed.last_error_code) == (
            AuthStatus.FAILED, ConnectionStatus.ERROR, McpErrorCode.OAUTH_DENIED)
        assert not stack.events(PLUGIN_RECONNECT_SCHEDULED)  # an authorization refusal is never retried


# Correctif générique S7 (ARCH §16 E22) : le consentement du navigateur ne compte
# pas dans le budget initialize/list ; il n'est borné que par le TTL de l'autorisation.
# Consent (3 s) outlasts every network bound: connect, read and handshake.
SHORT_HANDSHAKE = Timeouts(connect_s=1.0, read_s=2.0, handshake_s=1.0)


async def test_slow_browser_consent_does_not_count_against_the_handshake_budget(make):
    async with running_fakes(FakeConfig(auth="oauth")) as world:
        stack = await make(connector=_connector_with(SHORT_HANDSHAKE), ttl=10.0)
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome = await stack.service.connect(plugin.plugin_id)
        assert outcome.status == "authorizing"
        await asyncio.sleep(3.0)  # the user reads the consent page: 3 × the handshake budget
        waiting = await stack.service.get(plugin.plugin_id)
        assert (waiting.connection_status, waiting.auth_status) == (ConnectionStatus.CONNECTING,
                                                                    AuthStatus.AUTHORIZING)
        callback = await world.approve(outcome.authorization_url)
        done = await stack.service.complete_oauth(callback["code"], callback["state"], callback.get("iss"))
        assert (done.connection_status, done.auth_status) == (ConnectionStatus.CONNECTED, AuthStatus.AUTHORIZED)
        assert not stack.events(PLUGIN_CONNECTION_FAILED)
        assert not stack.events(PLUGIN_RECONNECT_SCHEDULED)  # no non-interactive retry during the consent
        assert McpErrorCode.REMOTE_TIMEOUT.value not in stack.trace()


async def test_consent_that_never_comes_ends_on_oauth_timeout_without_retry(make):
    async with running_fakes(FakeConfig(auth="oauth")) as world:
        stack = await make(connector=_connector_with(SHORT_HANDSHAKE), ttl=2.0)
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome = await stack.service.connect(plugin.plugin_id)
        assert outcome.status == "authorizing"
        ended = await _wait(lambda: _plugin_if(stack, plugin.plugin_id,
                                               lambda p: p.auth_status is not AuthStatus.AUTHORIZING), timeout=6.0)
        assert (ended.connection_status, ended.auth_status, ended.last_error_code) == (
            ConnectionStatus.ERROR, AuthStatus.FAILED, McpErrorCode.OAUTH_TIMEOUT)
        failures = stack.events(PLUGIN_CONNECTION_FAILED)
        assert [(f["code"], f["retry"]) for f in failures] == [(McpErrorCode.OAUTH_TIMEOUT.value, False)]
        assert not stack.events(PLUGIN_RECONNECT_SCHEDULED)
        await asyncio.sleep(0.3)  # nothing else happens afterwards
        assert len(stack.events(PLUGIN_CONNECTION_FAILED)) == 1
        callback = await world.approve(outcome.authorization_url)  # a consent after the TTL is refused
        with pytest.raises(McpPluginError) as late:
            await stack.service.complete_oauth(callback["code"], callback["state"], callback.get("iss"))
        assert late.value.code is McpErrorCode.OAUTH_STATE_INVALID


async def test_a_timeout_after_consent_while_authorizing_is_never_retried_non_interactively(make):
    async with running_fakes(FakeConfig(auth="oauth", token_delay_s=1.5)) as world:
        stack = await make(connector=_connector_with(SHORT_HANDSHAKE), ttl=10.0)
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome = await stack.service.connect(plugin.plugin_id)
        callback = await world.approve(outcome.authorization_url)
        await stack.service.complete_oauth(callback["code"], callback["state"], callback.get("iss"))
        ended = await _wait(lambda: _plugin_if(stack, plugin.plugin_id,
                                               lambda p: p.connection_status is ConnectionStatus.ERROR))
        assert (ended.auth_status, ended.last_error_code) == (AuthStatus.FAILED, McpErrorCode.REMOTE_TIMEOUT)
        failures = stack.events(PLUGIN_CONNECTION_FAILED)
        assert [(f["code"], f["retry"]) for f in failures] == [(McpErrorCode.REMOTE_TIMEOUT.value, False)]
        assert not stack.events(PLUGIN_RECONNECT_SCHEDULED)


async def test_expired_token_without_refresh_needs_reauthorization_without_network(make, tmp_path):
    async with running_fakes(FakeConfig(auth="oauth", expires_in=1)) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        await _oauth_connect(stack, world, plugin.plugin_id)
        await asyncio.sleep(1.2)
        # a running session: the next call finds the token expired and asks nobody
        started = time.monotonic()
        with pytest.raises(McpPluginError) as refused:
            await stack.service.invoke(plugin.plugin_id, "search_mail", {"q": "x"}, timeout_s=5)
        assert refused.value.code is McpErrorCode.REAUTHORIZATION_REQUIRED
        assert time.monotonic() - started < 1.0
        expired = await _wait(lambda: _plugin_if(stack, plugin.plugin_id,
                                                 lambda p: p.auth_status is AuthStatus.EXPIRED))
        assert expired.connection_status is ConnectionStatus.DISCONNECTED
        # now in that state, a call answers at once, before any network
        seen = len(world.requests)
        started = time.monotonic()
        with pytest.raises(McpPluginError) as again:
            await stack.service.invoke(plugin.plugin_id, "search_mail", {}, timeout_s=5)
        assert again.value.code is McpErrorCode.REAUTHORIZATION_REQUIRED
        assert time.monotonic() - started < 1.0 and len(world.requests) == seen
        assert not [s for s in world.seen("as") if s.path == "/authorize"][1:]  # no second interactive flow


async def test_boot_with_an_expired_token_makes_no_network_attempt(make):
    async with running_fakes(FakeConfig(auth="oauth", expires_in=1)) as world:
        first = await make(name="boot.sqlite3")
        plugin = await first.service.create(world.rs_base + "/mcp")
        await _oauth_connect(first, world, plugin.plugin_id)
        await first.service.stop()
        await asyncio.sleep(1.2)
        seen = len(world.requests)
        booted = McpPluginService(first.repo, first.service._vault, connector=_connector(),
                                  diagnostics=first.journal, allow_loopback_http=True)
        await booted.start()
        try:
            after = await booted.get(plugin.plugin_id)
            assert (after.auth_status, after.connection_status) == (AuthStatus.EXPIRED, ConnectionStatus.DISCONNECTED)
            await asyncio.sleep(0.3)
            assert len(world.requests) == seen
            started = time.monotonic()
            with pytest.raises(McpPluginError) as refused:
                await booted.invoke(plugin.plugin_id, "search_mail", {})
            assert refused.value.code is McpErrorCode.REAUTHORIZATION_REQUIRED
            assert time.monotonic() - started < 1.0
        finally:
            await booted.stop()


async def test_boot_reconnects_valid_oauth_and_static_plugins_non_interactively(make):
    async with running_fakes(FakeConfig(auth="oauth")) as world:
        first = await make(name="boot2.sqlite3")
        plugin = await first.service.create(world.rs_base + "/mcp")
        await _oauth_connect(first, world, plugin.plugin_id)
        await first.service.stop()
        authorizations = len([s for s in world.seen("as") if s.path == "/authorize"])
        booted = McpPluginService(first.repo, first.service._vault, connector=_connector(),
                                  diagnostics=first.journal, allow_loopback_http=True)
        await booted.start()
        try:
            again = await _wait(lambda: _plugin_if(booted, plugin.plugin_id,
                                                   lambda p: p.connection_status is ConnectionStatus.CONNECTED))
            assert again.auth_status is AuthStatus.AUTHORIZED
            assert len([s for s in world.seen("as") if s.path == "/authorize"]) == authorizations
        finally:
            await booted.stop()


async def test_step_up_403_during_connect_then_reconnect_widens_the_scope(make):
    async with running_fakes(FakeConfig(auth="oauth", list_scope="extra")) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        outcome = await stack.service.connect(plugin.plugin_id)
        callback = await world.approve(outcome.authorization_url)
        first = await stack.service.complete_oauth(callback["code"], callback["state"], callback["iss"])
        # tools/list asked for more scope: one authorization per explicit connect, so it stops here
        assert first.auth_status is AuthStatus.FAILED
        assert first.last_error_code is McpErrorCode.REAUTHORIZATION_REQUIRED
        second = await stack.service.connect(plugin.plugin_id)
        assert second.status == "authorizing"
        scope = parse_qs(urlsplit(second.authorization_url).query)["scope"][0].split()
        assert "extra" in scope
        callback = await world.approve(second.authorization_url)
        done = await stack.service.complete_oauth(callback["code"], callback["state"], callback["iss"])
        assert done.connection_status is ConnectionStatus.CONNECTED


async def test_disconnect_revokes_then_forgets(make):
    async with running_fakes(FakeConfig(auth="oauth")) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        await _oauth_connect(stack, world, plugin.plugin_id)
        gone = await stack.service.disconnect(plugin.plugin_id)
        assert world.revoked == ["access_token"]
        assert (gone.credential_ref, gone.auth_strategy, gone.enabled) == (None, AuthStrategy.NONE, True)
        assert await stack.repo.delete_for_plugin(plugin.plugin_id) == 0


# ------------------------------------------------------------------ bearer / en-tête


@pytest.mark.parametrize("strategy", ["bearer", "header"])
async def test_static_credentials_go_to_the_plugin_origin_only(make, strategy):
    config = FakeConfig(auth=strategy)
    async with running_fakes(config) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        await stack.service.set_static_credential(
            plugin.plugin_id, strategy=strategy, header_name=config.static_header if strategy == "header" else None,
            value=config.static_value)
        outcome = await stack.service.connect(plugin.plugin_id)
        assert (outcome.plugin.auth_status, outcome.plugin.auth_strategy.value) == (AuthStatus.AUTHORIZED, strategy)
        assert world.seen("as") == []
        header = "authorization" if strategy == "bearer" else config.static_header.lower()
        assert all(config.static_value in seen.headers.get(header, "") for seen in world.seen("rs"))
        _no_sentinel(json.dumps(outcome.plugin.public_view()), stack.trace())


async def test_wrong_static_credential_fails_without_retry(make):
    async with running_fakes(FakeConfig(auth="bearer")) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        await stack.service.set_static_credential(plugin.plugin_id, strategy="bearer", value="nope")
        with pytest.raises(McpPluginError) as refused:
            await stack.service.connect(plugin.plugin_id)
        assert refused.value.code is McpErrorCode.REAUTHORIZATION_REQUIRED
        failed = await stack.service.get(plugin.plugin_id)
        assert (failed.auth_status, failed.connection_status) == (AuthStatus.FAILED, ConnectionStatus.ERROR)
        assert not stack.events(PLUGIN_RECONNECT_SCHEDULED)


async def test_cross_origin_redirect_is_not_followed_and_carries_no_auth(make):
    async with running_fakes(FakeConfig()) as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/redirect")
        await stack.service.set_static_credential(plugin.plugin_id, strategy="bearer", value=f"{SENTINEL}-static")
        with pytest.raises(McpPluginError) as refused:
            await stack.service.connect(plugin.plugin_id)
        assert refused.value.code is McpErrorCode.REMOTE_PROTOCOL
        assert world.seen("as") == []  # /steal never reached, with or without the bearer


# ------------------------------------------------------------------ SSRF, charges hostiles


async def test_dns_resolved_forbidden_address_is_refused_before_any_request(make):
    async def resolver(host, port):
        return {"evil.example.com": ["169.254.169.254"]}.get(host, [])

    stack = await make(connector=_connector(resolver=resolver))
    plugin = await stack.service.create("https://evil.example.com/mcp")
    with pytest.raises(McpPluginError) as refused:
        await stack.service.connect(plugin.plugin_id)
    assert refused.value.code is McpErrorCode.ENDPOINT_FORBIDDEN
    assert not stack.events(PLUGIN_RECONNECT_SCHEDULED)


@pytest.mark.parametrize("path, code", [
    ("/huge", McpErrorCode.RESPONSE_TOO_LARGE),
    ("/malformed", McpErrorCode.REMOTE_PROTOCOL),
    ("/crash", McpErrorCode.REMOTE_UNREACHABLE),
    ("/legacy", McpErrorCode.TRANSPORT_UNSUPPORTED),
])
async def test_hostile_or_broken_servers_get_a_stable_code(make, path, code):
    async with running_fakes() as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + path)
        started = time.monotonic()
        with pytest.raises(McpPluginError) as refused:
            await stack.service.connect(plugin.plugin_id)
        assert refused.value.code is code
        assert time.monotonic() - started < 3.0
        failed = await stack.service.get(plugin.plugin_id)
        assert failed.last_error_code is code and failed.connection_status is ConnectionStatus.ERROR


async def test_secret_looking_remote_error_never_reaches_the_journal(make):
    async with running_fakes() as world:
        stack = await make()
        plugin = await stack.service.create(world.rs_base + "/mcp")
        await stack.service.connect(plugin.plugin_id)
        result = await stack.service.invoke(plugin.plugin_id, "leak_error", {})
        assert result["isError"] is True  # redaction of the text is Slice 04's `call`
        _no_sentinel(stack.trace())


# ------------------------------------------------------------------ isolation, reprise, arrêt


async def test_one_failing_plugin_never_affects_another_and_backs_off(make, caplog):
    caplog.set_level(logging.WARNING)
    async with running_fakes() as world:
        stack = await make(backoff=(0.05, 0.1, 0.2), connect_wait_s=3.0)
        healthy = await stack.service.create(world.rs_base + "/mcp")
        crash = await stack.service.create(world.rs_base + "/crash")
        malformed = await stack.service.create(world.rs_base + "/malformed")
        slow = await stack.service.create(world.rs_base + "/slow")
        assert (await stack.service.connect(healthy.plugin_id)).status == "connected"
        for broken in (crash, malformed):
            with pytest.raises(McpPluginError):
                await stack.service.connect(broken.plugin_id)
        slow_connect = asyncio.create_task(stack.service.connect(slow.plugin_id))
        # while the others fail, time out and retry, the healthy plugin answers at once
        for _ in range(5):
            started = time.monotonic()
            result = await stack.service.invoke(healthy.plugin_id, "send_mail", {"q": "hi"})
            assert result["isError"] is False and time.monotonic() - started < 1.0
            assert len(await stack.service.list_plugins()) == 4
            await asyncio.sleep(0.05)
        with pytest.raises(McpPluginError) as timed_out:
            await slow_connect
        assert timed_out.value.code is McpErrorCode.REMOTE_TIMEOUT
        attempts = await _wait(lambda: _attempts(stack, crash.plugin_id, 3))
        assert [event["delay_s"] for event in attempts[:3]] == [0.05, 0.1, 0.2]
        assert (await stack.service.get(healthy.plugin_id)).connection_status is ConnectionStatus.CONNECTED
        started = time.monotonic()
        await stack.service.stop()
        assert time.monotonic() - started <= 5.0
    assert not [r for r in caplog.records if "cancel scope" in r.getMessage().lower()]


async def test_a_local_bug_inside_the_session_is_an_owner_crash_not_a_remote_failure(make, monkeypatch):
    """QA M1 : une erreur du service dans le contexte du connecteur n'est pas une panne distante."""

    from jarvis.core import mcp_plugin_service as service_module

    def broken_normalization(plugin_id, raw_tools):
        raise KeyError("local-bug")

    monkeypatch.setattr(service_module, "normalize_remote_tools", broken_normalization)
    async with running_fakes() as world:
        stack = await make(backoff=(0.05,))
        plugin = await stack.service.create(world.rs_base + "/mcp")
        with pytest.raises(McpPluginError) as crashed:
            await stack.service.connect(plugin.plugin_id)
        assert (crashed.value.code, crashed.value.status) == (McpErrorCode.INTERNAL_ERROR, 500)
        assert "local-bug" not in str(crashed.value) and "KeyError" not in str(crashed.value)
        await asyncio.sleep(0.3)  # a (wrong) backoff reconnect would have fired by now
        crash, = stack.events(service_module.PLUGIN_OWNER_CRASHED)
        assert (crash["plugin_id"], crash["exception_type"]) == (plugin.plugin_id, "KeyError")
        assert stack.events(PLUGIN_CONNECTION_FAILED) == []
        assert stack.events(PLUGIN_RECONNECT_SCHEDULED) == []
        row = await stack.service.get(plugin.plugin_id)
        assert row.connection_status is ConnectionStatus.ERROR
        assert row.last_error_code is McpErrorCode.INTERNAL_ERROR


async def test_a_store_failure_under_the_oauth_flow_is_not_relabelled_as_remote(make):
    """QA M1 : le coffre qui échoue en scellant les jetons (sous le SDK) reste une panne locale."""

    from jarvis.core import mcp_plugin_service as service_module
    from jarvis.ports.mcp_plugins import McpPluginStoreError

    async with running_fakes(FakeConfig(auth="oauth")) as world:
        stack = await make(backoff=(0.05,))
        plugin = await stack.service.create(world.rs_base + "/mcp")
        store_oauth = stack.service._store_oauth

        async def failing_store(plugin_id, oauth):
            if oauth.get("tokens"):
                raise McpPluginStoreError("mcp_credentials", plugin_id, "injected failure")
            await store_oauth(plugin_id, oauth)

        stack.service._store_oauth = failing_store
        outcome = await stack.service.connect(plugin.plugin_id)
        callback = await world.approve(outcome.authorization_url)
        await stack.service.complete_oauth(callback.get("code"), callback["state"], callback.get("iss"))
        crash, = await _wait(lambda: _events(stack, service_module.PLUGIN_OWNER_CRASHED))
        assert (crash["exception_type"], crash["code"]) == ("McpPluginStoreError", "mcp_plugin_store_unreadable")
        assert [e["code"] for e in stack.events(PLUGIN_CONNECTION_FAILED)] == []
        await asyncio.sleep(0.2)
        assert stack.events(PLUGIN_RECONNECT_SCHEDULED) == []
        assert (await stack.service.get(plugin.plugin_id)).connection_status is ConnectionStatus.ERROR
        _no_sentinel(stack.trace())


async def _events(stack, kind):
    return stack.events(kind) or None


async def _attempts(stack, plugin_id, count):
    events = [e for e in stack.events(PLUGIN_RECONNECT_SCHEDULED) if e["plugin_id"] == plugin_id]
    return events if len(events) >= count else None


async def test_disabled_plugin_is_not_retried(make):
    async with running_fakes() as world:
        stack = await make(backoff=(0.2,))
        crash = await stack.service.create(world.rs_base + "/crash")
        with pytest.raises(McpPluginError):
            await stack.service.connect(crash.plugin_id)
        await stack.service.update(crash.plugin_id, enabled=False)
        await asyncio.sleep(0.5)
        failures = [e for e in stack.events(PLUGIN_CONNECTION_FAILED) if e["plugin_id"] == crash.plugin_id]
        assert failures[-1]["retry"] is False
        with pytest.raises(McpPluginError) as refused:
            await stack.service.connect(crash.plugin_id)
        assert refused.value.code is McpErrorCode.PLUGIN_DISABLED


async def test_stop_is_bounded_with_a_hanging_server_and_leaves_no_task(make, caplog):
    caplog.set_level(logging.WARNING)
    async with running_fakes() as world:
        stack = await make(connect_wait_s=30.0)
        healthy = await stack.service.create(world.rs_base + "/mcp")
        slow = await stack.service.create(world.rs_base + "/slow")
        await stack.service.connect(healthy.plugin_id)
        pending = asyncio.create_task(stack.service.connect(slow.plugin_id))
        await asyncio.sleep(0.3)
        before = {task for task in asyncio.all_tasks() if task.get_name().startswith("mcp-plugin-owner")}
        assert len(before) == 2
        started = time.monotonic()
        await stack.service.stop()
        assert time.monotonic() - started <= 5.0
        assert all(task.done() for task in before)
        with pytest.raises(McpPluginError):
            await pending
        stopped = await stack.service.get(healthy.plugin_id)
        assert stopped.connection_status is ConnectionStatus.DISCONNECTED
    assert not [r for r in caplog.records if "cancel scope" in r.getMessage().lower()]


# ------------------------------------------------------------------ routes Core de bout en bout


async def test_core_routes_run_the_oauth_flow_and_never_echo_a_secret(tmp_path):
    async with running_fakes(FakeConfig(auth="oauth")) as world:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        journal = RuntimeJournal(tmp_path / "runtime")
        core = JarvisCoreApplication(data_root=tmp_path, sealer=FakeSealer(), connector=_connector(),
                                     mcp_allow_loopback_http=True, diagnostics=journal)
        await core.start()
        server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
        await server.start()
        client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
        bodies: list[str] = []
        try:
            created = await client.create_mcp_plugin(world.rs_base + "/mcp")
            pid = created["plugin"]["plugin_id"]
            started = await client.connect_mcp_plugin(pid)
            bodies.append(json.dumps(started))
            assert started["status"] == "authorizing" and started["authorization_url"].startswith(world.as_base)
            callback = await world.approve(started["authorization_url"])
            with pytest.raises(CoreProtocolError) as forged:
                await client.complete_mcp_oauth(state="forged", code=callback["code"], iss=callback["iss"])
            assert (forged.value.status, forged.value.code) == (400, "mcp_oauth_state_invalid")
            done = await client.complete_mcp_oauth(state=callback["state"], code=callback["code"],
                                                   iss=callback["iss"])
            bodies.append(json.dumps(done))
            assert done["plugin"]["connection_status"] == "connected"
            assert "credential_ref" not in done["plugin"]
            refreshed = await client.refresh_mcp_plugin(pid)
            listed = await client.list_mcp_plugins()
            bodies += [json.dumps(refreshed), json.dumps(listed), json.dumps(await client.get_mcp_plugin(pid))]
            with pytest.raises(CoreProtocolError) as replay:
                await client.complete_mcp_oauth(state=callback["state"], code=callback["code"], iss=callback["iss"])
            assert replay.value.code == "mcp_oauth_state_invalid"
            bodies.append(json.dumps(await client.disconnect_mcp_plugin(pid)))
        finally:
            await client.close()
            await server.stop()
            await core.stop()
        _no_sentinel(*bodies, (tmp_path / "runtime" / "trace.jsonl").read_text(encoding="utf-8"))
