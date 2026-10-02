# Slice 02 — Plugin registry and credential vault

## Goal
Implement persistent managed-plugin definitions and a secret-storage boundary: CRUD, stable ids/endpoints/icon metadata, connection/auth/enabled states, opaque credential_ref, endpoint validation, duplicate detection, and enable/disable separate from connect/disconnect/remove. Add deterministic test vault, production-appropriate storage, and secret-sentinel/redaction tests.

## Dependencies
01-plugin-and-tool-discovery-contracts

## Quality gates
qa-verification + code-review + runtime-validation where applicable + agent-trace-analysis for MCP/runtime behavior. Coding loads /caveman and /coding-guideline. Regressions caused by the slice are blocking.

## Acceptance criteria
Canonical contracts/tests updated, no secret leakage, dependencies green, and runtime evidence captured before completion.

## Slice 00 contract

Binding design: `docs/06-resolved-architecture.md` (ARCH) §2, §3, §4.1 (CRUD part), §4.3 (plugin routes without connect/oauth/tools), §9.

### Scope (files)
- Create `jarvis/domain/mcp_plugins.py` (model, enums, `plugin_id_for`, transitions, `public_view`, strict `from_payload`, `McpPluginError`, `redact`), `jarvis/domain/mcp_endpoint.py` (`validate_endpoint`, `is_forbidden_address`; static validation only, no DNS).
- Create `jarvis/ports/mcp_plugins.py` (`McpPluginRepository`, `SealedSecretStore`, `Sealer`; declare `RemoteMcpConnector`/`RemoteMcpSession`/`AuthorizationPrompt` protocols for Slice 03).
- Create `jarvis/adapters/sqlite_mcp_plugins.py` (registry + `mcp_credentials` over `run_serialized`, `sqlite_state.py:318`; pattern `sqlite_workspace_board.py`).
- Create `jarvis/adapters/dpapi_sealer.py` (`DpapiSealer`, `UnavailableSealer`); `tests/fakes/fake_sealer.py`.
- Create `jarvis/core/credential_vault.py`, `jarvis/core/mcp_plugin_service.py` (list/create/update/set_static_credential/disconnect/remove; `connect`/`call`/`external_tools` raise `mcp_connector_unavailable` until Slice 03-04).
- Modify `jarvis/adapters/sqlite_state.py` (`_SCHEMA_VERSION = 4`, `_MIGRATIONS[4]` exactly ARCH §3.2); add `tests/schema/jarvis_state.v4.sql` (generated with `JARVIS_WRITE_SCHEMA_SNAPSHOT=1`).
- Modify `jarvis/core/v2_app.py` (construct adapter over `self.state`, service with injected `sealer`, start/stop), `jarvis/app.py:_run_core_v2` (inject `DpapiSealer()` on Windows else `UnavailableSealer()`), `tests/unit/test_v2_architecture.py` (one exception entry `jarvis.adapters.sqlite_mcp_plugins`).
- Modify `jarvis/protocol/server.py` + `jarvis/protocol/client.py`: `GET/POST /v1/mcp/plugins`, `GET/PATCH/DELETE /v1/mcp/plugins/{id}`, `PUT /v1/mcp/plugins/{id}/credential`, `POST /v1/mcp/plugins/{id}/disconnect`.

### Out of scope
Network, MCP SDK, OAuth, SSRF DNS resolution, catalog merge, gateway, UI, CC relay routes. Fixing the lost Board wiring (ARCH §14 C7) unless agent 0 assigns it.

### Acceptance criteria
- [ ] Migration v4 applies on a v3 DB (backup `jarvis.sqlite3.v3.bak` created) and a fresh DB; both schemas equal the frozen `jarvis_state.v4.sql`; v1-v3 snapshots untouched.
- [ ] Duplicate endpoint → 409 `mcp_plugin_duplicate`; invalid endpoint → 400 `mcp_endpoint_invalid` with reason; `plugin_id` slug rules (ARCH §3.1) incl. `jarvis-` prefix refusal and `-2` de-dup.
- [ ] enable/disable never touches connection/auth state; disconnect never touches `enabled`; remove deletes row + credential rows in one transaction.
- [ ] Rows hold only `credential_ref`; `public_view` and every `/v1/mcp/plugins*` response omit it and any secret; sealed blob ≠ plaintext.
- [ ] Vault `get_secret` returns `None` on binding mismatch (plugin_id or origin changed); sealer unavailable ⇒ `409 mcp_vault_unavailable` for non-`none` strategies, never plaintext.
- [ ] Rows left `connecting` are reset to `disconnected` at service start.
- [ ] Architecture tests green with exactly one new exception; `jarvis/core` imports no sqlite3/httpx/runtime.

### Required tests
- `tests/unit/test_mcp_plugin_domain.py`: slug, transitions, strict payload round-trip, `public_view` has no `credential_ref`, `redact` (vault value, Bearer, JWT shape).
- `tests/unit/test_mcp_endpoint_policy.py`: https-only, loopback-http flag, userinfo, fragment, secret-looking query keys, non-global IP literals (10/8, 127/8, 169.254.169.254, ::1, fd00::/8, 100.64/10), IDNA, length.
- `tests/unit/test_mcp_plugin_store_sqlite.py`: CRUD, UNIQUE endpoint, CHECK constraints, strict decode error surfaced (not skipped), atomic delete.
- `tests/unit/test_schema_migrations.py` (existing): v4 snapshot, v3→v4 equality, backup.
- `tests/unit/test_credential_vault.py`: FakeSealer round-trip, binding mismatch, unavailable sealer, secret sentinel `SENTINEL-SECRET-7f3a` absent from rows' `data`, API bodies and journal.
- `tests/unit/test_dpapi_sealer.py`: real DPAPI round-trip + tamper refusal (`skipif not win32`).
- `tests/unit/test_mcp_plugin_service.py` (CRUD part) and `tests/unit/test_mcp_protocol_routes.py` (routes above, 401 without token, codes/statuses of ARCH §9).

### Required evidence for QA
Pytest output of the files above + `test_v2_architecture.py`; `sqlite3 .schema` diff v3→v4 on a copy of a real v3 DB (never the live one; copy first, CLAUDE.md); grep of the test DB + journal for the sentinel returning nothing.

### Pre-existing red tests (not yours)
see READINESS.md §Baseline
