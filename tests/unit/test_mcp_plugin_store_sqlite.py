"""Magasin SQLite des plugins MCP : `McpPluginRepository` + `SealedSecretStore` sur le schéma v4 (Slice 02).

Contrat : `docs/mcp/plugins.md` §2.3. Tout tourne sur une base temporaire.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters.sqlite_mcp_plugins import SQLiteMcpPluginRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.domain.mcp_plugins import (
    AuthStrategy, ConnectionStatus, McpErrorCode, McpPluginError, attach_credential, mark_connection, new_plugin,
    set_enabled,
)
from jarvis.ports.mcp_plugins import McpPluginStoreError, McpPluginStoreUnavailable

T0 = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
REF = "cred_" + "b" * 32


def make(plugin_id: str = "mail", endpoint: str = "https://mail.example.com/mcp", minutes: int = 0):
    return new_plugin(endpoint, plugin_id=plugin_id, display_name=None, now=T0 + timedelta(minutes=minutes))


@pytest.fixture
async def store(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    try:
        yield SQLiteMcpPluginRepository(state), state.path
    finally:
        await state.close()


def raw(path: Path, sql: str, params=()):
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(sql, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


async def test_crud_round_trip(store):
    repo, _ = store
    first, second = make(), make("drive", "https://drive.example.com/mcp", 1)
    await repo.insert_plugin(first)
    await repo.insert_plugin(second)
    assert await repo.list_plugins() == (first, second)
    assert await repo.get_plugin("mail") == first
    assert await repo.get_plugin("nope") is None
    renamed = set_enabled(first, False, now=T0 + timedelta(minutes=5))
    await repo.save_plugin(renamed)
    assert await repo.get_plugin("mail") == renamed
    assert await repo.delete_plugin("mail") is True
    assert await repo.delete_plugin("mail") is False
    assert await repo.list_plugins() == (second,)


async def test_key_columns_mirror_the_payload(store):
    repo, path = store
    plugin = mark_connection(make(), ConnectionStatus.CONNECTING, now=T0)
    await repo.insert_plugin(plugin)
    row = raw(path, "SELECT plugin_id,endpoint,enabled,connection_status,auth_status,data FROM mcp_plugins")[0]
    assert row[:5] == ("mail", "https://mail.example.com/mcp", 1, "connecting", "unknown")
    assert json.loads(row[5]) == plugin.to_payload()


async def test_unique_endpoint_and_id_become_duplicate(store):
    repo, _ = store
    await repo.insert_plugin(make())
    for clash in (make("other"), make("mail", "https://other.example.com/")):
        with pytest.raises(McpPluginError) as refusal:
            await repo.insert_plugin(clash)
        assert refusal.value.code is McpErrorCode.PLUGIN_DUPLICATE
    await repo.insert_plugin(make("drive", "https://drive.example.com/"))
    with pytest.raises(McpPluginError) as refusal:
        await repo.save_plugin(make("drive", "https://mail.example.com/mcp"))
    assert refusal.value.code is McpErrorCode.PLUGIN_DUPLICATE


async def test_saving_a_missing_row_is_unknown(store):
    repo, _ = store
    with pytest.raises(McpPluginError) as refusal:
        await repo.save_plugin(make())
    assert refusal.value.code is McpErrorCode.PLUGIN_UNKNOWN


@pytest.mark.parametrize("sql", [
    "INSERT INTO mcp_plugins VALUES ('x','https://x/',2,'disconnected','unknown','t','t','{}')",
    "INSERT INTO mcp_plugins VALUES ('x','https://x/',1,'online','unknown','t','t','{}')",
    "INSERT INTO mcp_plugins VALUES ('x','https://x/',1,'disconnected','maybe','t','t','{}')",
    "INSERT INTO mcp_credentials VALUES ('cred_x','ghost','dpapi-user-v1','t','t',x'00')",
])
async def test_check_and_foreign_key_constraints(store, sql):
    _, path = store
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)
    finally:
        conn.close()


async def test_scheme_check_refuses_plaintext(store):
    repo, _ = store
    await repo.insert_plugin(make())
    with pytest.raises(McpPluginStoreUnavailable) as failure:
        await repo.put(REF, "mail", "plaintext", b"secret")
    assert failure.value.code == "mcp_plugin_store_failed" and "CHECK" in str(failure.value)


async def test_unreadable_row_is_surfaced_not_skipped(store):
    repo, path = store
    await repo.insert_plugin(make())
    await repo.insert_plugin(make("drive", "https://drive.example.com/", 1))
    raw(path, "UPDATE mcp_plugins SET data=json_set(data,'$.surprise',1) WHERE plugin_id='mail'")
    with pytest.raises(McpPluginStoreError) as failure:
        await repo.list_plugins()
    assert failure.value.code == "mcp_plugin_store_unreadable" and failure.value.key == "mail"
    raw(path, "UPDATE mcp_plugins SET data=json_remove(data,'$.surprise'), enabled=0 WHERE plugin_id='mail'")
    with pytest.raises(McpPluginStoreError, match="key columns disagree"):
        await repo.get_plugin("mail")
    raw(path, "UPDATE mcp_plugins SET data='not json', enabled=1 WHERE plugin_id='mail'")
    with pytest.raises(McpPluginStoreError, match="JSONDecodeError"):
        await repo.get_plugin("mail")


async def test_sealed_secret_rows(store):
    repo, _ = store
    await repo.insert_plugin(make())
    await repo.put(REF, "mail", "dpapi-user-v1", b"\x00sealed\xff")
    stored = await repo.get(REF)
    assert (stored.credential_ref, stored.plugin_id, stored.scheme, stored.blob) == (
        REF, "mail", "dpapi-user-v1", b"\x00sealed\xff")
    await repo.delete(REF)
    assert await repo.get(REF) is None
    await repo.put(REF, "mail", "dpapi-user-v1", b"a")
    await repo.put("cred_" + "c" * 32, "mail", "dpapi-user-v1", b"b")
    assert await repo.delete_for_plugin("mail") == 2


async def test_delete_removes_plugin_and_credentials_atomically(store):
    repo, path = store
    plugin = attach_credential(make(), strategy=AuthStrategy.BEARER, credential_ref=REF, now=T0)
    await repo.insert_plugin(plugin)
    await repo.put(REF, "mail", "dpapi-user-v1", b"blob")
    assert await repo.delete_plugin("mail") is True
    assert raw(path, "SELECT count(*) FROM mcp_credentials")[0][0] == 0
    assert raw(path, "SELECT count(*) FROM mcp_plugins")[0][0] == 0


async def test_failed_delete_rolls_back_the_credential_delete(store):
    repo, path = store
    await repo.insert_plugin(make())
    await repo.put(REF, "mail", "dpapi-user-v1", b"blob")
    # A trigger makes the plugin-row delete fail after the credential delete ran.
    raw(path, "CREATE TRIGGER s2_block BEFORE DELETE ON mcp_plugins BEGIN SELECT RAISE(ABORT, 's2 blocked'); END")
    with pytest.raises(McpPluginStoreUnavailable, match="s2 blocked"):
        await repo.delete_plugin("mail")
    assert raw(path, "SELECT count(*) FROM mcp_credentials")[0][0] == 1
    assert raw(path, "SELECT count(*) FROM mcp_plugins")[0][0] == 1


async def test_save_plugins_is_one_transaction(store):
    repo, _ = store
    first = mark_connection(make(), ConnectionStatus.CONNECTING, now=T0)
    await repo.insert_plugin(first)
    ghost = make("ghost", "https://ghost.example.com/")
    with pytest.raises(McpPluginError):
        await repo.save_plugins([mark_connection(first, ConnectionStatus.DISCONNECTED, now=T0), ghost])
    assert (await repo.get_plugin("mail")).connection_status is ConnectionStatus.CONNECTING
