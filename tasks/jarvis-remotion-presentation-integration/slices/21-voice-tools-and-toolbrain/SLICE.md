# Slice 21 - Voice commands, authoring agents and tool ownership

## Goal
Wire voice commands and subagent tasks to the common presentation semantic API, preserving existing Tool Brain/ambient authorization and no engine auto-choice.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Expose install/status/studio/preview/edit/export/variants/prefabs verbs through approved MCP/agent routes.
- Route high-confidence small changes to props; structural to subagent source edit; present live result and failures.
- No ambient non-addressed request can install, export, promote, switch engine, or mutate a source.
- Make agent select stable IDs from observed state, not invent ids; preserve one UI owner.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
11-remotion-studio-process-ui, 12-score-to-remotion-runtime, 14-source-edit-hmr-and-agents, 19-promotion-pins-and-upgrades, 20-engine-ui-policy-and-slidecar

## Implementation Steps
1. Expose install/status/studio/preview/edit/export/variants/prefabs verbs through approved MCP/agent routes.
2. Route high-confidence small changes to props; structural to subagent source edit; present live result and failures.
3. No ambient non-addressed request can install, export, promote, switch engine, or mutate a source.
4. Make agent select stable IDs from observed state, not invent ids; preserve one UI owner.

## Files Likely Touched
- `docs/mcp/tool-contract.md` (verify actual final-branch path before editing)
- `docs/tool-brain-contracts.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- End-to-end agent traces with addressed/ambient/noise, tool brain ownership, rollback, no double call.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Voice-first complete creation/edit/export with trace evidence; unsupported capabilities visibly refused.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/mcp/tool-contract.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/tool-brain-contracts.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- **Overlap and budget**: the agent surface exists (`jarvis-presentation`, 12 tools; Tool Brain ownership guard `studio_owned` in `jarvis/runtime/tool_brain_executor.py`; turn attestation `presentation_studio_turn.py`; `presentation_edit` already has the CONTROL vs `scene.source_request` split the "small change -> props, structural -> subagent" bullet asks for). The tool context budget is nearly full (`tests/unit/test_mcp_catalog.py:233` limit 17 100 B, about 16 849 B used per the old LOG). New verbs (install/status/Studio open/export) must go to a **separate server or category** or the budget constant must be raised deliberately with evidence; do not squeeze them into the 12 tools.
- Real-trace analysis (agent-trace-analysis) is mandatory again; the old harness `tests/replay/presentation_studio_authoring_real_trace.py` is the starting point.
