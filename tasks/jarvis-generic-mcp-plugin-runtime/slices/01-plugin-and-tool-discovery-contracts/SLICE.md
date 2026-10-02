# Slice 01 — Plugin and tool-discovery contracts

## Goal
Revise the canonical MCP contract so the existing single catalog remains authoritative while managed external plugins and model-facing list_tools(intent) are added deliberately. Define plugin lifecycle, stable namespacing, mixed-detail discovery (recommended FULL schemas plus compact bounded remainder), repeated discovery, generic call_tool semantics, auth/redaction boundaries, global V1 availability, restricted-profile exception, and Drive migration status.

## Dependencies
00-project-manager

## Quality gates
Every implemented slice gets qa-verification. Code changes get code-review. User-visible/runtime work gets runtime-validation. MCP/tool/routing/agent work gets agent-trace-analysis. Coding slices load /caveman and /coding-guideline; frontend also /impeccable. Regressions caused by this slice are blocking and cannot be parked in Issues/.

## Acceptance criteria
Implement only after dependencies are green; update canonical docs/tests; preserve the single MCP catalog and secret boundary; provide evidence required by this slice before marking complete.

## Slice 00 contract

Binding design: `docs/06-resolved-architecture.md` (cited below as ARCH §n). Docs-only Slice: no product code.

### Scope (files)
- Modify `docs/mcp/tool-contract.md`: §1 table (add `jarvis-tools`; `jarvis-barehands` = 16 tools, not 5; refresh stale line anchors), §2 (external descriptor fields `tool_id`, `plugin_id`, `invocation`, `registration="managed"`), §4.3 (plugin availability fact ARCH §6.3; Codex amendment C1 exception for `jarvis-tools`), §5.3 (replace "no meta-tool" by the single discovery server `jarvis-tools` exposing exactly `list_tools` + `call_tool`, with the budgets of ARCH §7.1-7.2), §8 (management routes `/api/mcp/plugins*`, callback `/api/mcp/oauth/callback`; restate "no tool-execution route in the Control Center").
- Create `docs/mcp/plugins.md`: process topology (ARCH §0), plugin model + states + transitions (ARCH §3.1), auth strategies, vault + threat model (ARCH §3.3), endpoint/SSRF policy (ARCH §5.1-5.2), OAuth flow incl. non-interactive rule and no-refresh expiry (ARCH §5.3), external descriptor normalization + bounds (ARCH §6.2), `list_tools` response contract + cursor + byte budget (ARCH §7.2), `call_tool` semantics + error codes (ARCH §7.3, §9), relevance rules (ARCH §7.4), propagation matrix per runtime/profile (ARCH §8), Drive classification (ARCH §11).
- Update `docs/mcp/tool-contract.md` header status line and cross-link `plugins.md`.

### Out of scope
Any `.py`/`.js` change; tests; ARCHITECTURE/SECURITY/OPERATIONS docs (Slice 08); per-board/per-agent policy; marketplace; SSE adapter.

### Acceptance criteria
- [ ] §5.3 no longer forbids model-facing discovery and names exactly two model-facing catalog tools, both on `jarvis-tools`.
- [ ] Every contradiction C1-C12 of ARCH §14 is reflected (topology, relevance in gateway, `/v1/mcp/*` namespace, callback path, operator servers excluded, Codex exception, barehands count, `managed` registration).
- [ ] `plugins.md` states numeric bounds identical to ARCH (24 576 B response, ≤5 recommended, 16 KiB recommended part, 16 KiB schema, 4 096 B description, 200 tools/plugin, 64 KiB args, 32 KiB result, 60/120 s timeouts, 4 MiB response cap).
- [ ] Error-code table identical to ARCH §9.
- [ ] Restricted profiles (`speculative_analysis`, `presentation_preparation`) and `job_result` explicitly keep no gateway.
- [ ] No secret, token, real Drive id or credential path appears in any doc example.

### Required tests
None new (docs). Run the existing suites that read docs, if any: `tests/unit/test_mcp_catalog.py` must stay unchanged-green (no code touched).

### Required evidence for QA
Diff of both docs; a checklist mapping each ARCH §14 item to the doc paragraph that carries it; `git diff --stat` showing docs only.

### Pre-existing red tests (not yours)
see READINESS.md §Baseline
