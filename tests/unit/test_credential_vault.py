"""Coffre des identifiants de plugins MCP (Slice 02 ; `docs/mcp/plugins.md` §3.2, ARCH §3.3).

Sentinelle : `SENTINEL-SECRET-7f3a` ne doit apparaître ni dans `data` des
lignes, ni dans un blob scellé, ni dans une réponse API, ni dans le journal.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import socket
import sqlite3

import aiohttp
import pytest

from jarvis.adapters.sqlite_mcp_plugins import SQLiteMcpPluginRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.credential_vault import (
    VAULT_BINDING_MISMATCH, VAULT_CREDENTIAL_MISSING, VAULT_UNSEAL_FAILED, CredentialVault,
)
from jarvis.core.mcp_plugin_service import McpPluginService
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.mcp_plugins import McpErrorCode, McpPluginError, new_plugin, origin_of
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.journal import RuntimeJournal
from tests.fakes.fake_sealer import MARKER, FakeSealer

SENTINEL = "SENTINEL-SECRET-7f3a"
T0 = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
TOKEN = "t" * 48
STATIC = {"kind": "static", "static": {"header_name": None, "value": SENTINEL}}


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, message, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [event[0] for event in self.events]


@pytest.fixture
async def env(tmp_path):
    state = SQLiteStateRepository(tmp_path / "jarvis.sqlite3")
    await state.initialize()
    store = SQLiteMcpPluginRepository(state)
    sink = RecordingSink()
    plugin = new_plugin("https://mail.example.com/mcp", plugin_id="mail", display_name=None, now=T0)
    await store.insert_plugin(plugin)
    try:
        yield store, sink, plugin, state.path
    finally:
        await state.close()


async def test_fake_sealer_round_trip_and_blob_is_not_plaintext(env):
    store, sink, plugin, path = env
    vault = CredentialVault(store, FakeSealer(), diagnostics=sink)
    ref = await vault.put_secret(plugin, STATIC)
    assert ref.startswith("cred_") and len(ref) == 37
    assert await vault.get_secret(replace(plugin, credential_ref=ref)) == STATIC
    blob = (await store.get(ref)).blob
    assert blob.startswith(MARKER) and SENTINEL.encode() not in blob
    conn = sqlite3.connect(path)
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    assert SENTINEL not in dump


async def test_binding_mismatch_returns_none(env):
    store, sink, plugin, _ = env
    vault = CredentialVault(store, FakeSealer(), diagnostics=sink)
    ref = await vault.put_secret(plugin, STATIC)
    bound = replace(plugin, credential_ref=ref)
    moved = replace(bound, endpoint="https://evil.example.com/mcp", endpoint_origin=origin_of("https://evil.example.com/mcp"))
    assert await vault.get_secret(moved) is None
    other = new_plugin("https://drive.example.com/mcp", plugin_id="drive", display_name=None, now=T0)
    await store.insert_plugin(other)
    assert await vault.get_secret(replace(other, credential_ref=ref)) is None  # row owned by another plugin
    assert sink.kinds().count(VAULT_BINDING_MISMATCH) == 2
    assert SENTINEL not in json.dumps(sink.events)


async def test_payload_bound_to_another_plugin_is_refused_even_if_the_row_is_moved(env):
    store, sink, plugin, path = env
    vault = CredentialVault(store, FakeSealer(), diagnostics=sink)
    other = new_plugin("https://drive.example.com/mcp", plugin_id="drive", display_name=None, now=T0)
    await store.insert_plugin(other)
    ref = await vault.put_secret(plugin, STATIC)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE mcp_credentials SET plugin_id='drive' WHERE credential_ref=?", (ref,))
    conn.commit()
    conn.close()
    assert await vault.get_secret(replace(other, credential_ref=ref)) is None


async def test_tampered_or_missing_blob_returns_none_and_is_journaled(env):
    store, sink, plugin, _ = env
    vault = CredentialVault(store, FakeSealer(), diagnostics=sink)
    ref = await vault.put_secret(plugin, STATIC)
    await store.put(ref, "mail", "dpapi-user-v1", b"garbage")
    assert await vault.get_secret(replace(plugin, credential_ref=ref)) is None
    assert await vault.get_secret(replace(plugin, credential_ref="cred_" + "0" * 32)) is None
    assert VAULT_UNSEAL_FAILED in sink.kinds() and VAULT_CREDENTIAL_MISSING in sink.kinds()


@pytest.mark.parametrize("sealer", [None, FakeSealer(available=False)])
async def test_unavailable_sealer_refuses_and_never_stores_plaintext(env, sealer):
    store, _, plugin, path = env
    vault = CredentialVault(store, sealer)
    assert vault.available is False
    with pytest.raises(McpPluginError) as refusal:
        await vault.put_secret(plugin, STATIC)
    assert refusal.value.code is McpErrorCode.VAULT_UNAVAILABLE and refusal.value.status == 409
    with pytest.raises(McpPluginError):
        await vault.get_secret(replace(plugin, credential_ref="cred_" + "0" * 32))
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT count(*) FROM mcp_credentials").fetchone()[0] == 0
    finally:
        conn.close()


async def test_forget_and_discard(env):
    store, _, plugin, _ = env
    vault = CredentialVault(store, FakeSealer())
    first = await vault.put_secret(plugin, STATIC)
    await vault.put_secret(plugin, STATIC)
    await vault.discard(first)
    assert await store.get(first) is None
    await vault.discard(None)
    assert await vault.forget(plugin) == 1


# ------------------------------------------------------------------ sentinelle de bout en bout


async def test_sentinel_absent_from_rows_api_bodies_and_journal(tmp_path):
    """Le secret passe par la vraie route ; il n'apparaît nulle part ailleurs que dans le blob scellé."""

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    runtime = tmp_path / "runtime"
    journal = RuntimeJournal(runtime)
    core = JarvisCoreApplication(data_root=tmp_path / "data", sealer=FakeSealer(), diagnostics=journal)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    bodies: list[str] = []
    try:
        created = await client.create_mcp_plugin("https://mail.example.com/mcp")
        plugin_id = created["plugin"]["plugin_id"]
        bodies.append(json.dumps(created))
        bodies.append(json.dumps(await client.set_mcp_plugin_credential(plugin_id, strategy="bearer", value=SENTINEL)))
        bodies.append(json.dumps(await client.set_mcp_plugin_credential(
            plugin_id, strategy="header", header_name="X-Api-Key", value=SENTINEL)))
        # Refusals must not echo the value either.
        for bad in ({"strategy": "header", "header_name": "Cookie", "value": SENTINEL},
                    {"strategy": "bearer", "value": SENTINEL + "\n"}):
            with pytest.raises(CoreProtocolError) as refusal:
                await client.set_mcp_plugin_credential(plugin_id, **bad)
            bodies.append(refusal.value.message)
        async with aiohttp.ClientSession() as session:
            async with session.put(f"http://127.0.0.1:{port}/v1/mcp/plugins/{plugin_id}/credential",
                                   headers={"Authorization": f"Bearer {TOKEN}"},
                                   data=b'{"strategy":"bearer","value":"' + SENTINEL.encode() + b'"') as response:
                bodies.append(await response.text())
        bodies.append(json.dumps(await client.list_mcp_plugins()))
        bodies.append(json.dumps(await client.get_mcp_plugin(plugin_id)))
        bodies.append(json.dumps(await client.update_mcp_plugin(plugin_id, enabled=False)))
        stored = await core.mcp_plugins.get(plugin_id)
        secret = await core.mcp_plugins._vault.get_secret(stored)
        assert secret["static"]["value"] == SENTINEL  # it really was stored, sealed
        bodies.append(json.dumps(await client.disconnect_mcp_plugin(plugin_id)))
    finally:
        await client.close()
        await server.stop()
        await core.stop()
    for body in bodies:
        assert SENTINEL not in body
        assert "credential_ref" not in body
    conn = sqlite3.connect(tmp_path / "data" / "state" / "jarvis.sqlite3")
    try:
        assert SENTINEL not in "\n".join(conn.iterdump())
    finally:
        conn.close()
    journal_text = "".join(path.read_text(encoding="utf-8") for path in runtime.rglob("*") if path.is_file())
    assert "mcp.plugin.credential_set" in journal_text  # the journal did record the operation
    assert SENTINEL not in journal_text
