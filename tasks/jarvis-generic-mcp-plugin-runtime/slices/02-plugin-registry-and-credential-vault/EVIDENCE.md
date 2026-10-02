# Slice 02 — Evidence

Branch `task/jarvis-generic-mcp-plugin-runtime`, base `6676666`. Commits:
`935dad1` (domain), `4ff326d` (v4 migration + store), `7f9918f` (DPAPI sealer),
`ad6ba9d` (vault + service + routes + wiring), and the commit that adds this file.
Date 2026-09-30, Windows 11, Python 3.14.6, foreground pytest
(`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`).

## 1. Pytest

Slice files + architecture + migrations (one run):

| File | Tests |
| --- | ---: |
| `tests/unit/test_mcp_plugin_domain.py` | 43 |
| `tests/unit/test_mcp_endpoint_policy.py` | 52 |
| `tests/unit/test_mcp_plugin_store_sqlite.py` | 14 |
| `tests/unit/test_credential_vault.py` | 8 |
| `tests/unit/test_dpapi_sealer.py` | 6 (1 skipped: non-Windows fallback) |
| `tests/unit/test_mcp_plugin_service.py` | 35 |
| `tests/unit/test_mcp_protocol_routes.py` | 35 |
| `tests/unit/test_v2_architecture.py` | 8 |
| `tests/unit/test_schema_migrations.py` | 8 |

Result: **208 passed, 1 skipped**.

Regression chunks (post-commit, foreground):

| Command scope | Result |
| --- | --- |
| every `tests/unit/test_*sqlite*`, `test_*protocol*`, `test_*core*` (11 files) + `test_conversation_event_store.py` | 272 passed |
| other unit files constructing `JarvisCoreApplication` / touching `sqlite_state` (40 files, 2 chunks) | 1 134 passed, 1 failed — `test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` (READINESS "not yours") |
| `tests/integration/test_board_session_e2e.py`, `test_brain_work_context_protocol.py` | 9 passed |
| 26 other integration files constructing Core (non-live) | 258 passed |

Tests adjusted (not weakened): 12 assertions pinned to schema `3` in
`test_board_store_sqlite.py`, `test_conversation_event_store.py` and
`tests/integration/test_board_session_e2e.py` now compare with
`sqlite_state._SCHEMA_VERSION` (they meant "current version"; the next
migration would break them again otherwise), and
`test_newer_schema_is_refused_and_old_binary_refuses_v2` derives its
"newer than supported" versions from it.

Acceptance checks, with the test that proves each:

- Migration v4 on a v3 DB (backup `.v3.bak`) and a fresh DB, both equal to the
  frozen snapshot; v1–v3 snapshots untouched —
  `test_a_v3_state_file_migrates_to_v4_after_a_backup_and_keeps_its_rows`,
  `test_state_schema_matches_its_frozen_snapshot`; only `tests/schema/jarvis_state.v4.sql` added.
- 409 `mcp_plugin_duplicate`, 400 `mcp_endpoint_invalid` with reason, slug
  rules (`jarvis-` → `p-jarvis-…`, `-2`) — `test_duplicate_is_409`,
  `test_invalid_endpoint_says_why`, `test_plugin_id_slug_rules`.
- enable/disable never touches connection/auth, disconnect never touches
  `enabled`, remove atomic — `test_enable_disable_never_touch_connection_or_auth`,
  `test_disconnect_forgets_credentials_and_keeps_enabled`,
  `test_enable_and_disconnect_axes_stay_independent`,
  `test_failed_delete_rolls_back_the_credential_delete`.
- Rows hold only `credential_ref`; no response carries it; blob ≠ plaintext —
  `test_public_view_never_carries_the_credential_ref`,
  `test_fake_sealer_round_trip_and_blob_is_not_plaintext`, `test_real_dpapi_round_trip`.
- `get_secret` → `None` on binding mismatch; 409 `mcp_vault_unavailable`
  without sealer — `test_binding_mismatch_returns_none`,
  `test_payload_bound_to_another_plugin_is_refused_even_if_the_row_is_moved`,
  `test_vault_unavailable_is_409_and_listing_says_so`.
- `connecting` rows reset at start — `test_connecting_rows_are_reset_at_core_start`.
- Architecture: exactly one new exception (`jarvis.adapters.sqlite_mcp_plugins`);
  `jarvis/core` imports no sqlite3/httpx/runtime — `test_v2_architecture.py` 8/8.

## 2. Schema v3 → v4 on a copy of a real database

The live `data/state/jarvis.sqlite3` is at **v2** (last written 2026-09-29), so a
real v3 file was produced from it: the three files (`jarvis.sqlite3`, `-wal`,
`-shm`) were **copied** to the session scratchpad (`s2_realdb_v3/`), the copy
was opened by the v3 binary (`_SCHEMA_VERSION = 3`) — backup `jarvis.sqlite3.v2.bak`
— then by this branch. The live file was never opened (mtime still
`Sep 29 10:47` after the run). Script: scratchpad `s2_schema_diff.py`.

```text
version before: 3
version after: 4
quick_check: ok
mcp rows: 0 0
row counts unchanged: True (20 tables, 4921 rows)
backups: ['jarvis.sqlite3.v2.bak', 'jarvis.sqlite3.v3.bak']
after == frozen v4 snapshot: True
--- v3
+++ v4
@@ -1 +1 @@
--- schema_version = [(3,)]
+-- schema_version = [(4,)]
@@ -29,0 +30,2 @@
+-- index idx_mcp_credentials_plugin ON mcp_credentials
+CREATE INDEX idx_mcp_credentials_plugin ON mcp_credentials(plugin_id);
@@ -69,0 +72,4 @@
+-- table mcp_credentials ON mcp_credentials
+CREATE TABLE mcp_credentials ( credential_ref TEXT PRIMARY KEY, plugin_id TEXT NOT NULL REFERENCES mcp_plugins(plugin_id), scheme TEXT NOT NULL CHECK (scheme IN ('dpapi-user-v1')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, blob BLOB NOT NULL);
+-- table mcp_plugins ON mcp_plugins
+CREATE TABLE mcp_plugins ( plugin_id TEXT PRIMARY KEY, endpoint TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), connection_status TEXT NOT NULL CHECK (connection_status IN ('disconnected','connecting','connected','error')), auth_status TEXT NOT NULL CHECK (auth_status IN ('unknown','not_required','required','authorizing','authorized','expired','failed')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
```

The same script run directly on a v2 copy (v2 → v4 in one start) also ends
equal to the frozen snapshot, row counts unchanged (17 tables, 4 921 rows),
backup `jarvis.sqlite3.v2.bak` only.

## 3. Secret sentinel

Scratchpad script `s2_sentinel.py`: a real Core (`default_sealer()` →
**`DpapiSealer`**, real `RuntimeJournal`) behind `LocalProtocolServer`; the
client creates the Circuit Toolbox plugin, sets `SENTINEL-SECRET-7f3a` as a
Bearer then as `X-Api-Key`, tries a refused `Cookie` header with it, lists.

```text
sealer: DpapiSealer | unsealed value matches: True
credential_ref in any API body: False
./api_bodies.json  ./data/state/jarvis.sqlite3  ./data/state/scene.sqlite3  ./runtime/trace.jsonl
--- grep -ra "SENTINEL-SECRET-7f3a" .   → no match (grep exit=1)
--- sqlite iterdump: sentinel in dump: False
plugins/creds: (1,) [('cred_ab88e51db9b36d11100bb418fd04c1c0', 'dpapi-user-v1', 438)]
journal kinds: mcp.plugins.started ×1, mcp.plugin.created ×1, mcp.plugin.credential_set ×2, mcp.plugin.refused ×1
```

The journal records every operation (identifiers and codes only); the unsealed
value really is the sentinel, so its absence elsewhere is meaningful. The same
checks run in CI as `test_sentinel_absent_from_rows_api_bodies_and_journal`
(FakeSealer).

## 4. Deviations and additions (reported, documented in plugins.md)

- New code `mcp_plugin_invalid` (400) for refused fields/bodies — ARCH §9 names none.
- Store failure codes `mcp_plugin_store_unreadable` / `mcp_plugin_store_failed`
  (500), same family as `board_store_*`.
- `localhost` / `*.localhost` classified as loopback without DNS
  (`mcp_endpoint_forbidden` unless the dev flag).
- `McpPlugin.tools` is a bounded tuple of JSON objects until Slice 04 adds
  `ExternalToolDescriptor`; timestamps are aware `datetime` (ISO strings on the wire).
- `disconnect` also resets `auth_strategy` to `none` (credentials forgotten ⇒
  nothing left to authenticate with). RFC 7009 revocation (E10) needs the
  connector: Slice 03.
- `immediate_transaction` promoted from `SQLiteBoardRepository._transaction`
  into `sqlite_state` and reused by both adapters (no second helper).
- `SealedSecretStore` method names follow ARCH (`put/get/delete/delete_for_plugin`).
- Error-handling skill: Core has no `send_error_response`; the Core canon
  (middleware → `{"error": {"code", "message"}}`) is used, and every refusal /
  store failure is journaled by the service (`mcp.plugin.refused`,
  `mcp.plugin.store_failed`).
