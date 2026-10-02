# Slice 08 — Release QA and documentation

## Goal
Run full native + managed-plugin regression, canonical catalog parity, dynamic descriptor checks, model-context and list_tools response byte budgets, secret scans across logs/traces/API/model input, restart/reconnect persistence, final Brain/subagent traces, Control Center accessibility/visual validation, and canonical operations/migration documentation cleanup.

## Dependencies
07-circoe-drive-integration-validation

## Quality gates
qa-verification + code-review + runtime-validation + agent-trace-analysis. Coding loads /caveman and /coding-guideline. Regressions caused by this slice are blocking.

## Acceptance criteria
All slice criteria are green; native MCP behavior remains parity-tested; plugin state survives restart/reconnect as designed; large catalogs stay bounded; no secret sentinel leaks; final Circuit Toolbox Brain + delegated-subagent evidence exists; canonical docs match shipped behavior.

## Slice 00 contract

Binding design: `docs/06-resolved-architecture.md` (ARCH) §12, §13, §15.

### Scope (files)
- Full regression (native MCP parity, catalog API, inspector JS, plugin API/JS, Core routes, schema migrations, architecture tests, Claude/Codex argv, prompt fingerprints) run in foreground chunks.
- Docs: `docs/ARCHITECTURE.md` (Core-owned plugin runtime, gateway), `docs/SECURITY.md` (vault/DPAPI threat model, SSRF policy, OAuth, redaction), `docs/OPERATIONS.md` (add/connect/reconnect/remove a plugin, dev loopback flag, recovering from `expired`, v4 backup/rollback), `docs/state-model.md` (schema v4 tables), `docs/mcp/tool-contract.md` §10.x "Implementation facts" for this handoff, `docs/mcp/plugins.md` final numbers.
- Close or file every open question of ARCH §15 with its evidence; update ARCH if shipped behavior differs (with a dated note).

### Out of scope
New features; migrating Drive; per-agent policy.

### Acceptance criteria
- [ ] All tests green except entries listed in READINESS.md §Baseline (unchanged or fixed, never worse).
- [ ] Restart persistence: Core restart keeps plugins, enabled flags and sealed credentials; enabled+authorized plugins reconnect without UI; expired ones show `expired`; CC restart changes nothing for plugins.
- [ ] Budgets re-measured on the final surface: `list_tools` <= 24 576 B (500-tool synthetic + real Circuit Toolbox), gateway context cost <= 2 500 B, display/console baselines unchanged.
- [ ] Secret scan: a sentinel credential through the full flow never appears in `runtime/trace.jsonl`, journal, `/api/*` bodies, model input (CLI stream-json transcripts), `--mcp-config` files, `jarvis.sqlite3` plaintext (only sealed), QA notes.
- [ ] Final Brain + delegated-subagent traces against Circuit Toolbox exist and pass agent-trace-analysis.
- [ ] Control Center accessibility/visual validation green; HV checks completed.
- [ ] Canonical docs match shipped behavior (reviewer spot-checks 10 claims against code).

### Required tests
- `tests/unit/test_mcp_secret_sentinel.py`: end-to-end sentinel over fake plugin (create -> credential -> connect -> list -> call -> disconnect) scanning trace, journal, API bodies, config files and DB bytes.
- `tests/integration/test_mcp_plugin_restart.py`: Core restart persistence and non-interactive reconnect on the fake server.
- Budget re-measure assertions live in `test_tool_discovery.py` / `test_tools_gateway_mcp.py` (no new file needed).

### Required evidence for QA
Chunked pytest outputs; measured byte table; sentinel scan report; final trace excerpts; docs diff; list of closed/filed open questions.

### Pre-existing red tests (not yours)
see READINESS.md §Baseline
