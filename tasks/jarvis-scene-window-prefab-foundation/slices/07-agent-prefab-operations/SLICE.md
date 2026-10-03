# Slice 07 — Agent-Facing Prefab Operations

## Goal

Expose the prefab system to Jarvis through controlled, inspectable operations suitable for the project's MCP/tool architecture.

## Context

Jarvis must be able to choose, inspect, instantiate, fork, create, and save prefabs instead of relying on hardcoded UI knowledge.

## Canonical Concepts

Prefab catalog operation, definition mutation, instance operation, explicit base edit.

## Scope

### In Scope

Operations equivalent to:

- list/search prefabs
- inspect prefab schema/code/provenance as permitted
- instantiate prefab in scene
- update prefab instance inputs/data
- fork/clone prefab definition
- create new prefab definition
- validate/preview candidate definition
- save/promote candidate into shared library
- explicitly modify a base prefab only through the protected path

Exact names must match current Jarvis tool/MCP conventions.

### Out of Scope

- Giving prefab JavaScript direct tool access.
- Silent base prefab edits.

## Dependencies

- `06-structured-interactive-prefabs`

## Implementation Steps

1. Define read vs instance-mutation vs definition-mutation surfaces.
2. Reuse existing Jarvis tool authorization/gating conventions.
3. Add explicit base-edit intent/gate.
4. Validate all generated definitions before library publication.
5. Emit trace/audit evidence for definition changes.
6. Make catalog descriptions useful for model selection without shipping full source unless requested/needed.

## Files Likely Touched

Agent tool/MCP contracts, prefab service/catalog, authorization/gate code, trace/logging, tests.

## Architecture Constraints

Backend/runtime remains the authority for validation and mutation. Frontend descriptors must not become a second capability catalog.

## Automated Validation

- Tool schema/conformance tests.
- Read-only operations do not mutate.
- Invalid definitions rejected.
- Base edit denied without explicit gate.
- Trace evidence records actor/action/target/result.

## Acceptance Criteria

- Jarvis can complete the reuse-first workflow end to end through supported operations.
- Definition changes are gated, validated, and traceable.
- No prefab gains arbitrary Jarvis authority.

## Documentation Updates

Document model-visible operation catalog and base-edit rules.

## Handoff Notes

Use `/caveman` and `/coding-guideline`. This Slice also requires `agent-trace-analysis` QA with real traces.

## Slice 00 contract (binding)

Create / touch:
- `jarvis/runtime/display_prefabs.py`: `PrefabDisplayTools` (transport `CorePrefabTransport`); tools of 06 R6 registered in `display_mcp.build_server`; `scene_create_object`/`scene_update_object` gain `prefab` (strict TypedDict); `scene_get` detail adds `prefab`.
- `jarvis/protocol/prefab_routes.py`: `POST /v1/prefabs/validate`, `POST /v1/prefabs`, `POST /v1/prefabs/{prefab_id}/base-edits`.
- `jarvis/core/v2_app.py`: wire the base-edit witness to `ConversationEventQueryService.search` (06 R6 gate; freshness-check the `SearchQuery` shape first).
- `jarvis/runtime/mcp_tool_meta.py` `DISPLAY`: 6 new `ToolMeta` (labels, side-effect class, atomicity, rules); `docs/mcp/tool-contract.md` §6 + new §10.x per §10.2.
- `jarvis/domain/brain_context.py`: `BrainPrefabEvent`, `BrainContext.prefab_events`.
- `jarvis/core/brain_service.py`: provider from `PrefabEventService.take_undelivered_notify`.
- `jarvis/adapters/control_center_brain.py`: `_turn_context` adds `prefab_events`, absent when empty.
- `jarvis/runtime/claude_local.py`: `BRAIN_PREFAB_PROMPT` appended after `BRAIN_ARTIFACT_PROMPT`; `jarvis/runtime/prompt_catalog.py` descriptor `backend.claude.conversation.prefabs` + `PromptStep`. `BRAIN_DISPLAY_PROMPT` unchanged.
- `docs/ARCHITECTURE.md` §"Brain display MCP" (~2379), `docs/SECURITY.md` control 16 → implemented.

Acceptance:
- `test_display_mcp_prefabs.py`: strict schemas (unknown arg refused); read tools do not mutate (library listing before/after); `prefab_save` invalid → errors listed, nothing written; `jarvis.*` save refused with hint; `prefab_edit_base` without witness refused; create with `prefab` and no version pins latest; non-window kind refused with a clear message; `scene_get` shows `latest_version`.
- MCP catalogue parity tests (`mcp_tool_meta` ↔ registered tools) green.
- `test_brain_context_prefab_events.py`: notify delivered once, ≤8, context byte-identical when none.
- Prompt fingerprint tests updated only for the new descriptor.
- **agent-trace-analysis** with real Claude CLI turns: (a) "affiche une checklist de …" → `prefab_search` then `scene_create_object` with `jarvis.checklist` (no ad-hoc authoring); (b) "fais-en une variante rouge avec une colonne priorité et garde-la" → `prefab_get include_source` → `prefab_validate` → `prefab_save derived_from`; (c) a base-edit attempt without explicit user words → refused and explained; (d) a notify event reaches the next turn.

Depends on: 06.
QA: qa-verification + code-review + agent-trace-analysis (+ runtime-validation for scene effects).
