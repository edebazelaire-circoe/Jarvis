# Slice 06 — Brain display MCP

## Goal
Give the main brain an MCP display tool surface acting on the same Core scene as `actor=brain`, with no archive capability (Decisions 1, 2, 14, 15).

## Context
Audit facts: the continuous brain is the Claude Code CLI spawned by `ClaudeLocalAgent` (`jarvis/runtime/claude_local.py:557-579`) with `--chrome`, a PreToolUse routing hook, and no repo-wired MCP (the only in-repo MCP server, `jarvis/runtime/drive_mcp.py`, is FastMCP over stdio, registered manually at user scope). The `speculative_analysis` profile uses `--strict-mcp-config --tools ""` and must stay tool-less. `mcp>=1.2,<2` is an optional extra. Core is reachable with `CoreWorkTransport` + `runtime/core.token`. Legacy realtime brain (`REALTIME_TOOLS`) and V1 `board_present` are out of scope for V1 display (PM decision: display tools target the Claude CLI brain only; record if Human disagrees).

## Canonical Concepts
- `jarvis/runtime/display_mcp.py` (`python -m jarvis display-mcp`), FastMCP stdio, lazily built like `drive_mcp.build_server`, calling Core `/v1/scene/*` as `actor=brain`.
- Tools (V1): `scene_inspect` (compact active-scene listing), `scene_create_object`, `scene_update_object` (geometry/layer/order/representation/payload), `scene_set_visibility`, `scene_link`/`scene_unlink`. **No archive tool**; test asserts catalog has no archive-like tool and Core rejects brain archive regardless.
- Repo wiring: `ClaudeLocalAgent` passes a generated `--mcp-config` for the display server on brain profiles that should have it (not `speculative_analysis`), gated by the scene feature flag; user-scope registration stays untouched.
- Brain prompt: short display guidance appended to `BRAIN_SYSTEM_PROMPT` via `prompt_runtime` (catalogued in `prompt_catalog.py`), respecting the existing delegate-long-work and no-redundant-announcement rules.

PM amendment (Slice 01 QA): relation layer 50 (`DEFAULT_RELATION_LAYER`) means "not announced" for runtime but is an explicit value for brain/user — MCP tool schemas must not default `layer` to 50 (omit when not provided). Surface reducer refusals (`object_archived`, `pinned_by_user`, `execution_node`, `resolver_actor`, ...) as explicit tool errors with the reason code. Relations carry no `origin`; runtime may unlink a brain-created `parent_of` between runtime stars — acceptable (runtime owns topology), document it in the tool guidance.

## Scope
### In Scope
MCP server, spawn wiring, prompt addition, tests, real-trace validation.
### Out of Scope
Artifact semantics (07), richer query/screenshot (09).

## Dependencies
01, 02, 03.

## Implementation Steps
1. Server + tools. 2. Spawn wiring + flag. 3. Prompt text. 4. Tests (catalog, actor forcing, pinned object refusal surfaced to brain as tool error). 5. Real run: ask the brain by voice/text to show/move an object; capture trace.

## Files Likely Touched
`jarvis/runtime/display_mcp.py`, `jarvis/app.py`, `jarvis/runtime/claude_local.py`, `jarvis/runtime/prompt_catalog.py`, docs, tests.

## Architecture Constraints
No dedicated display AI; adapter boundary kept (tools call a port, not renderer). Tool errors explicit and journaled.

## Automated Validation
Unit tests incl. `tests/unit/test_drive.py` pattern; `test_claude_debug_console.py`/routing hook tests green.

## Acceptance Criteria
Real Claude brain inspects and mutates the scene through MCP; changes visible in browser; archive impossible for brain (catalog + server).

## Documentation Updates
OPERATIONS.md (display MCP), ARCHITECTURE.md (authority model).

## Handoff Notes
Skills: `/caveman`, `/coding-guideline`. QA: qa-verification + code-review + runtime-validation + agent-trace-analysis (real traces from `runtime/trace.jsonl`).
