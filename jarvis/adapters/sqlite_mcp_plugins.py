"""SQLite adapter of the MCP plugin registry and sealed credential store (generic-mcp-plugin-runtime, Slice 02).

Ports: `jarvis.ports.mcp_plugins.McpPluginRepository` and `SealedSecretStore`.
Contract: `docs/mcp/plugins.md` §2.3, §3.2. Tables `mcp_plugins` and
`mcp_credentials` come from migration v4 of `sqlite_state`.

Like `sqlite_workspace_board`, it shares the operational state DB file,
connection, lock and worker thread of `SQLiteStateRepository` through
`run_serialized`; lifecycle (initialize, migration, backup, close) belongs to
that repository.

Guarantees:

- `data` is the plugin's `to_payload()`; every read decodes it with the strict
  domain `from_payload` and cross-checks the key columns. A row failing either
  is surfaced as `McpPluginStoreError`, never skipped or repaired;
- a plugin row carries only the opaque `credential_ref`; `blob` is stored as
  handed over (already sealed by `CredentialVault`), never decoded here;
- `delete_plugin` removes the credential rows and the plugin row in one
  `BEGIN IMMEDIATE` transaction: all or nothing;
- UNIQUE on `endpoint` (and the primary key) become
  `McpPluginError(mcp_plugin_duplicate)`, never a raw `IntegrityError`;
- any other `sqlite3.Error` becomes `McpPluginStoreUnavailable`
  (`mcp_plugin_store_failed`), SQLite's words kept.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import sqlite3
from typing import TypeVar

from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.mcp_plugins import McpErrorCode, McpPlugin, McpPluginError, canonical_json
from jarvis.domain.v2 import utc_now
from jarvis.ports.mcp_plugins import McpPluginStoreError, McpPluginStoreUnavailable, SealedSecret

T = TypeVar("T")


def _plugin_row(row: sqlite3.Row) -> McpPlugin:
    key = row["plugin_id"]
    try:
        plugin = McpPlugin.from_payload(json.loads(row["data"]))
    except (ValueError, TypeError) as exc:  # JSONDecodeError and McpPluginError are ValueErrors
        raise McpPluginStoreError("mcp_plugins", key, f"{type(exc).__name__}: {exc}") from exc
    if (plugin.plugin_id != key or plugin.endpoint != row["endpoint"] or int(plugin.enabled) != row["enabled"]
            or plugin.connection_status.value != row["connection_status"]
            or plugin.auth_status.value != row["auth_status"]):
        raise McpPluginStoreError("mcp_plugins", key, "key columns disagree with data")
    return plugin


def _values(plugin: McpPlugin) -> tuple:
    return (plugin.endpoint, int(plugin.enabled), plugin.connection_status.value, plugin.auth_status.value,
            plugin.updated_at.isoformat(), canonical_json(plugin.to_payload()), plugin.plugin_id)


def _update(conn: sqlite3.Connection, plugin: McpPlugin) -> None:
    try:
        cursor = conn.execute(
            "UPDATE mcp_plugins SET endpoint=?,enabled=?,connection_status=?,auth_status=?,updated_at=?,data=? "
            "WHERE plugin_id=?", _values(plugin))
    except sqlite3.IntegrityError as exc:
        raise McpPluginError(McpErrorCode.PLUGIN_DUPLICATE,
                             f"plugin {plugin.plugin_id}: endpoint already registered by another plugin") from exc
    if cursor.rowcount == 0:
        raise McpPluginError(McpErrorCode.PLUGIN_UNKNOWN, f"plugin {plugin.plugin_id} does not exist")


class SQLiteMcpPluginRepository:
    """`McpPluginRepository` + `SealedSecretStore` over the shared state DB (schema v4)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.Error as exc:
            operation = getattr(fn, "__qualname__", "operation").split(".<locals>")[0].rsplit(".", 1)[-1]
            raise McpPluginStoreUnavailable(operation, f"{type(exc).__name__}: {exc}") from exc

    # ------------------------------------------------------------ plugins

    async def list_plugins(self) -> Sequence[McpPlugin]:
        def list_plugins(c: sqlite3.Connection):
            return c.execute("SELECT * FROM mcp_plugins ORDER BY created_at, plugin_id").fetchall()

        return tuple(_plugin_row(row) for row in await self._run(list_plugins))

    async def get_plugin(self, plugin_id: str) -> McpPlugin | None:
        def get_plugin(c: sqlite3.Connection):
            return c.execute("SELECT * FROM mcp_plugins WHERE plugin_id=?", (plugin_id,)).fetchone()

        row = await self._run(get_plugin)
        return _plugin_row(row) if row else None

    async def insert_plugin(self, plugin: McpPlugin) -> None:
        def insert_plugin(c: sqlite3.Connection) -> None:
            try:
                c.execute(
                    "INSERT INTO mcp_plugins(endpoint,enabled,connection_status,auth_status,updated_at,data,plugin_id,"
                    "created_at) VALUES(?,?,?,?,?,?,?,?)", (*_values(plugin), plugin.created_at.isoformat()))
            except sqlite3.IntegrityError as exc:
                raise McpPluginError(McpErrorCode.PLUGIN_DUPLICATE,
                                     f"plugin {plugin.plugin_id} or its endpoint is already registered") from exc

        await self._run(insert_plugin)

    async def save_plugin(self, plugin: McpPlugin) -> None:
        def save_plugin(c: sqlite3.Connection) -> None:
            _update(c, plugin)

        await self._run(save_plugin)

    async def save_plugins(self, plugins: Sequence[McpPlugin]) -> None:
        def save_plugins(c: sqlite3.Connection) -> None:
            def write(conn: sqlite3.Connection) -> None:
                for plugin in plugins:
                    _update(conn, plugin)

            immediate_transaction(c, write)

        if plugins:
            await self._run(save_plugins)

    async def delete_plugin(self, plugin_id: str) -> bool:
        def delete_plugin(c: sqlite3.Connection) -> bool:
            deleted = False

            def write(conn: sqlite3.Connection) -> None:
                nonlocal deleted
                conn.execute("DELETE FROM mcp_credentials WHERE plugin_id=?", (plugin_id,))
                deleted = conn.execute("DELETE FROM mcp_plugins WHERE plugin_id=?", (plugin_id,)).rowcount == 1

            immediate_transaction(c, write)
            return deleted

        return await self._run(delete_plugin)

    # ------------------------------------------------------------ sealed secrets

    async def put(self, ref: str, plugin_id: str, scheme: str, blob: bytes) -> None:
        now = utc_now().isoformat()

        def put(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT INTO mcp_credentials(credential_ref,plugin_id,scheme,created_at,updated_at,blob) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(credential_ref) DO UPDATE SET plugin_id=excluded.plugin_id,"
                "scheme=excluded.scheme,updated_at=excluded.updated_at,blob=excluded.blob",
                (ref, plugin_id, scheme, now, now, sqlite3.Binary(blob)))

        await self._run(put)

    async def get(self, ref: str) -> SealedSecret | None:
        def get(c: sqlite3.Connection):
            return c.execute("SELECT credential_ref,plugin_id,scheme,blob FROM mcp_credentials WHERE credential_ref=?",
                             (ref,)).fetchone()

        row = await self._run(get)
        if row is None:
            return None
        return SealedSecret(credential_ref=row["credential_ref"], plugin_id=row["plugin_id"], scheme=row["scheme"],
                            blob=bytes(row["blob"]))

    async def delete(self, ref: str) -> None:
        def delete(c: sqlite3.Connection) -> None:
            c.execute("DELETE FROM mcp_credentials WHERE credential_ref=?", (ref,))

        await self._run(delete)

    async def delete_for_plugin(self, plugin_id: str) -> int:
        def delete_for_plugin(c: sqlite3.Connection) -> int:
            return c.execute("DELETE FROM mcp_credentials WHERE plugin_id=?", (plugin_id,)).rowcount

        return await self._run(delete_for_plugin)
