# Slice 04 — Intent-aware global tool registry and execution gateway

## Goal
Merge managed external tools into the existing canonical catalog. Add stable plugin-qualified ids, catalog revisions, tested hybrid relevance, list_tools(intent) with complete actionable schemas for a small recommended set plus compact bounded/paginated others, repeated discovery, generic call_tool(tool_id, arguments), dynamic tool-list invalidation, and hard context/response budget tests.

## Dependencies
03-remote-mcp-connection-manager

## Quality gates
qa-verification + code-review + runtime-validation + agent-trace-analysis. Coding loads /caveman and /coding-guideline. Regressions caused by this slice are blocking.

## Acceptance criteria
Normal behavior is implemented against the canonical MCP catalog/gateway, secret boundaries remain intact, context stays bounded, and trace evidence proves the required agent behavior.

## Slice 00 contract

Binding design: `docs/06-resolved-architecture.md` (ARCH) §6, §7, §9, §14 C2/C5/C8/C12.

### Scope (files)
- Create `jarvis/domain/tool_relevance.py` (fold, tokens, synonyms, BM25F `rank`, ARCH §7.4) and `jarvis/domain/tool_discovery.py` (`build_list_response`, cursor encode/decode, byte budget, ARCH §7.2).
- Create `jarvis/runtime/tools_gateway_mcp.py` (`SERVER_NAME = "jarvis-tools"`, `ToolsGatewayTarget`, `mcp_config`, `write_mcp_config`, `codex_config_overrides` + `toml_value`, `build_server(target=None, *, tools=None)`, `serve_stdio`) with the strict schemas of ARCH §7.1; add the `tools-mcp` subcommand in `jarvis/app.py`.
- Modify `jarvis/runtime/mcp_tool_meta.py` (`TOOLS` ServerMeta, `SERVERS += TOOLS`, `Registration` += `"managed"`) and `jarvis/runtime/mcp_catalog.py` (`build_introspection_server("jarvis-tools")`, `describe_external_tool`, `merge_external`, `AGENT_SNAPSHOT_FLAGS`, `list_view`/`detail_view` without `server_meta()` for plugins).
- Extend `jarvis/core/mcp_plugin_service.py` (`external_tools(since_revision)`, `call`, catalog revision) and `jarvis/protocol/server.py` / `client.py` (`GET /v1/mcp/tools`, `POST /v1/mcp/tools/call`).
- Modify `jarvis/runtime/control_center.py`: `mcp_tools` / `mcp_tool_detail` (:4773-4791) serve `merge_external(native, core external)` with a 2 s Core timeout; `_mcp_availability` (:4689-4743) knows `jarvis-tools` and plugin facts.
- Amend `tests/unit/test_mcp_catalog.py:188-195` (exempt `jarvis-tools` only from the meta-tool regex; everything else unchanged).

### Out of scope
Passing the gateway to Claude/Codex (Slice 05); plugin UI (Slice 06); live server (Slice 07); confirmation gate for destructive external tools (ARCH §15 Q3).

### Acceptance criteria
- [ ] `jarvis-tools` passes every native parity gate of `test_mcp_catalog.py` (metadata <-> introspection order, annotations, `tools/list` equality).
- [ ] Gateway context cost (name + description + input schema, both tools) <= 2 500 B; instructions <= 1 200 B; display/console budgets unchanged.
- [ ] `list_tools` returns <= 5 FULL `recommended` (description, input_schema, side_effect, invocation, `call_as` for natives), compact `others` (summary <= 120 chars), `next_cursor`, `catalog_revision`; whole response <= 24 576 B on a 500-tool synthetic catalog; different intents give different recommendations; a stale cursor restarts with `catalog_changed`.
- [ ] Natives listed = exactly the servers in `JARVIS_TOOLS_NATIVE_SERVERS` minus `jarvis-tools`; `jarvis-drive` never listed.
- [ ] Disabled or disconnected plugin tools absent from `list_tools`; `call_tool` on them -> `mcp_plugin_disabled` / `mcp_plugin_disconnected`; native id -> `native_tool_call_directly` with `call_as`; unknown -> `mcp_tool_unknown`.
- [ ] `call_tool` bounds: args <= 64 KiB with required/closed-key check; result <= 32 KiB (`truncated`); remote error redacted, <= 4 KiB; timeout 60 s default, 120 s max.
- [ ] Relevance quality gate: recall@3 >= 0.9 on >= 20 FR/EN intents; deterministic (same input => byte-identical output).
- [ ] CC `/api/mcp/tools` still answers natives when Core is down (`unavailable` entry `plugins`) and serves plugin descriptors + details (`/api/mcp/tools/{plugin_id}/{name}`) when up; no secret in any body.
- [ ] A tool-list mutation on the fake server => new `catalog_revision` visible to the next `list_tools`.

### Required tests
- `tests/unit/test_tool_relevance.py`: fold / stem / synonyms, BM25 order, tie-break, recall@3 on fixture `tests/fixtures/tool_intents.json`.
- `tests/unit/test_tool_discovery.py`: budget with 500 tools, <= 5 recommended, `too_large` path, cursor paging + stale + wrong intent, empty intent.
- `tests/unit/test_tools_gateway_mcp.py`: in-memory client session; strict schemas; budgets; list/call against a fake Core; error codes; native exclusion; `toml_value`.
- `tests/unit/test_mcp_catalog.py`: amended regex test + external descriptor shape, merge with Core down, plugin availability fact.
- `tests/unit/test_control_center_mcp_api.py`: merged list/detail, Core-down path, secret sentinel absent.
- `tests/unit/test_mcp_protocol_routes.py`: `/v1/mcp/tools`, `/v1/mcp/tools/call`.

### Required evidence for QA
Pytest output; recorded `list_tools` responses for 3 intents with measured bytes; agent-trace-analysis of an in-memory client transcript (list -> call -> re-list for a prerequisite) showing no redundant call and no secret.

### Pre-existing red tests (not yours)
see READINESS.md §Baseline
