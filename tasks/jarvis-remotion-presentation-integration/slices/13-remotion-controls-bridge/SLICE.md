# Slice 13 - Shared typed variables and fast edits

## Goal
Map existing semantic scene controls to Remotion props/schema and expose editable params without duplicating the editor.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Carry colors/text/spacing/timing/data/motion params via safe validated inputProps.
- Declare bounds/defaults/labels; allow per-engine-only parameters with explicit unsupported tags.
- Re-use existing inspector/control metadata instead of rebuild; durable patch must update source model.
- Never confuse Player preview-only props with canonical saved state.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
02-engine-and-compatibility-contract, 10-remotion-player-host

## Implementation Steps
1. Carry colors/text/spacing/timing/data/motion params via safe validated inputProps.
2. Declare bounds/defaults/labels; allow per-engine-only parameters with explicit unsupported tags.
3. Re-use existing inspector/control metadata instead of rebuild; durable patch must update source model.
4. Never confuse Player preview-only props with canonical saved state.

## Files Likely Touched
- `docs/prefabs.md` (verify actual final-branch path before editing)
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Color/spacing/stagger updates, unsafe prop reject, stale CAS, inspector resets and parity checks.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Voice/GUI share same edit operation and preview update; no MP4 render on simple edits.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/prefabs.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
