# Slice 05 — Agent and subagent capability propagation

## Goal
Expose the stable discovery/execution gateway to normal Claude and Codex Jarvis runtimes and delegated subagents without copied credentials or re-authentication. Prove inheritance with real traces, add capability status/snapshots, and keep deliberately restricted profiles restricted unless a separate approved contract changes them.

## Dependencies
04-intent-tool-registry-and-gateway

## Quality gates
qa-verification + code-review + runtime-validation + agent-trace-analysis. Coding loads /caveman and /coding-guideline. Regressions caused by this slice are blocking.

## Acceptance criteria
Normal behavior is implemented against the canonical MCP catalog/gateway, secret boundaries remain intact, context stays bounded, and trace evidence proves the required agent behavior.

## Slice 00 contract

Binding design: `docs/06-resolved-architecture.md` (ARCH) §8, §15 Q1/Q4/Q5.

### Scope (files)
- Modify `jarvis/runtime/claude_local.py`: ctor arg `tools_mcp`; `_tools_mcp_args()` (pattern `_console_mcp_args`, :923-950), conversation profile only, written after display/barehands/console args so `native_servers` lists exactly the servers declared this launch; argv after `*console_args` (:853); `snapshot()["tools_gateway"]`; journal `agent.tools_mcp_failed` on write failure; `agent.start` data gains `tools_mcp`.
- Add `BRAIN_TOOLS_PROMPT` in `claude_local.py`, composed into the four conversation programs like `BRAIN_SETTINGS_PROMPT` (:165); declare it in `jarvis/runtime/prompt_catalog.py` (pattern :139). Short: use `mcp__jarvis-tools__list_tools` when no loaded tool fits; call it again for each new prerequisite; call recommended tools directly (`call_as`) or through `call_tool`.
- Modify `jarvis/runtime/codex_local.py:253-273`: ctor/attr `tools_mcp`; `_turn_command` inserts `codex_config_overrides(target)` (literal TOML strings, `tool_timeout_sec=130`) before `-`, for `exec` and `exec resume`; `snapshot()["tools_gateway"]`; Codex prompt gets the same guidance through its prompt target.
- Modify `jarvis/runtime/control_center.py` (ctor `tools_mcp`, `_apply_agent_settings` :1194-1247 sets `agent.tools_mcp` for both CLIs, `_mcp_availability` flag) and `jarvis/app.py` (build `ToolsGatewayTarget` from `settings.core_host/core_port/token_file`, next to `DisplayMcpTarget`).
- If the subagent trace disproves inheritance (ARCH §8.3): implement the `--agents` fallback (delegation agent with `mcpServers: ["jarvis-tools"]`) and document it; otherwise document the proof.

### Out of scope
`speculative_analysis`, `presentation_preparation` (must stay `--strict-mcp-config`, no gateway) and `job_result` (no native MCP in V1); UI; any per-agent plugin policy.

### Acceptance criteria
- [ ] Claude conversation argv contains one `--mcp-config` for `jarvis-tools` whose file has no token value, only paths/port/env names; restricted profiles' argv unchanged byte for byte; `job_result` argv unchanged.
- [ ] `JARVIS_TOOLS_NATIVE_SERVERS` equals the declared native set for each of the four display/barehands combinations.
- [ ] Codex argv carries the four/five `-c mcp_servers.jarvis-tools.*` overrides; a path with spaces and one with `'` round-trip (`codex mcp get jarvis-tools --json` probe in a test marked `requires_codex`, skipped when absent).
- [ ] Real trace (Claude): the brain calls `list_tools` then a recommended external tool via `call_tool` against the fake plugin; a delegated subagent does the same without any credential in its prompt/config (Q1 answered with evidence).
- [ ] Real trace (Codex): same discovery + call; Q4 (approvals in non-bypass sandbox) recorded.
- [ ] Q5 recorded: whether `jarvis-tools` is deferred behind ToolSearch; prompt names the tool accordingly.
- [ ] Prompt fingerprint tests updated deliberately; no other prompt text changes.

### Required tests
- `tests/unit/test_claude_tools_gateway_args.py`: conversation vs restricted vs job_result argv; native set per combination; write failure journaled and brain still starts; snapshot flag.
- `tests/unit/test_codex_agent.py` (amended): overrides present on both `exec` forms, TOML quoting, snapshot flag.
- `tests/unit/test_prompt_registry.py` / `test_prompt_runtime_wiring.py` / `test_control_center_prompts.py` (amended fingerprints + new descriptor).
- `tests/unit/test_mcp_catalog.py` / `test_control_center_mcp_api.py`: `jarvis-tools` `advertised` from both agents' snapshots.

### Required evidence for QA
Redacted `runtime/trace.jsonl` excerpts (Claude brain, Claude subagent with `parent_tool_use_id`, Codex turn) showing `list_tools` -> `call_tool`; agent-trace-analysis report; secret-sentinel grep over traces, argv logs and prompts returning nothing.

### Pre-existing red tests (not yours)
see READINESS.md §Baseline
