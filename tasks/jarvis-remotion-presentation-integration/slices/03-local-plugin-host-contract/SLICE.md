# Slice 03 - Installable local capability vs remote MCP plugins

## Goal
Design a local Remotion capability lifecycle without violating the existing remote MCP Plugin registry.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Audit Plugin UI, Core plugin service and host process permissions.
- Choose the narrowest packaging and install entrypoint, diagnostic state and system requirements.
- Make UI feel like one plugin to the user while preserving distinct local/remote transports.
- Define install/update/repair/disable/uninstall and version pinning/ownership semantics.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
01-final-branch-conformance

## Implementation Steps
1. Audit Plugin UI, Core plugin service and host process permissions.
2. Choose the narrowest packaging and install entrypoint, diagnostic state and system requirements.
3. Make UI feel like one plugin to the user while preserving distinct local/remote transports.
4. Define install/update/repair/disable/uninstall and version pinning/ownership semantics.

## Files Likely Touched
- `docs/mcp/plugins.md` (verify actual final-branch path before editing)
- `docs/OPERATIONS.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Contract/API routing tests, no new provider-specific path through remote MCP credential storage.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Approved Level 2 capability contract, no fake remote MCP endpoint.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/mcp/plugins.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- Confirmed against code: `McpPlugin` is URL-only and `transport` must be `streamable_http` (`jarvis/domain/mcp_plugins.py:203-234`); local stdio servers are operator-managed (`docs/mcp/plugins.md:1093-1101`). So the choice is **a sibling local-capability registry** (not a new `transport` value of `McpPlugin`, which would change external MCP semantics). Unify only the user-facing card in `jarvis/runtime/control_center_mcp_plugins.js`.
- Do not reuse the credential vault or OAuth path for a local Node runtime (not needed, widens blast radius).
- Decision to record: who starts the Node child (Core vs a Control Center helper) and how that interacts with the repository rule "no agent starts or stops Core/Control Center/voice" (CLAUDE.md): provisioning code must be testable in a sandbox with its own data root, never against the live profile.
