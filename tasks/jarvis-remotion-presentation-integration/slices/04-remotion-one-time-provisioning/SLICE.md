# Slice 04 - Remotion environment installation and lifecycle

## Goal
Install and manage one pinned Node/Remotion environment per Jarvis runtime profile; make it user hands-off and repairable.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Check required Node/npm versions and platform support.
- Install pinned compatible remotion/@remotion/react/cli package set once in managed cache with integrity checks.
- Avoid global npm writes and dependency tree per presentation.
- Provide health, missing, installing, ready, broken, repairing states and lock/timeout management.
- Uninstall/disable never destroys presentation source or imported assets.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
03-local-plugin-host-contract

## Implementation Steps
1. Check required Node/npm versions and platform support.
2. Install pinned compatible remotion/@remotion/react/cli package set once in managed cache with integrity checks.
3. Avoid global npm writes and dependency tree per presentation.
4. Provide health, missing, installing, ready, broken, repairing states and lock/timeout management.
5. Uninstall/disable never destroys presentation source or imported assets.

## Files Likely Touched
- `docs/OPERATIONS.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Real target OS installation harness, concurrent install, interrupted npm, offline/permission errors, restart.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Fresh install and restart/repair verified; no duplicate runtimes per deck.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
