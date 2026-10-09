# Slice 22 - QA, migration, performance and final Human sign-off

## Goal
Prove the Remotion-first product path and release safely with existing branch integration and documentation.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Rerun the complete regression against final main/branch merge-base and reconcile inherited baseline reds.
- Measure install once, source reload latency, media render jobs, memory/process and disk usage.
- Test physical target OS browser/fullscreen, genuine Studio and Player, real voice cues, live edit, variants, prefab imports and frozen exports.
- Publish operations docs, user experience and error recovery; do not release when no-fallback policy or privacy boundary is unverified.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
08-artifact-board-registration, 12-score-to-remotion-runtime, 14-source-edit-hmr-and-agents, 15-remotion-one-shot-authoring, 16-render-export-and-derived-artifacts, 19-promotion-pins-and-upgrades, 20-engine-ui-policy-and-slidecar, 21-voice-tools-and-toolbrain

## Implementation Steps
1. Rerun the complete regression against final main/branch merge-base and reconcile inherited baseline reds.
2. Measure install once, source reload latency, media render jobs, memory/process and disk usage.
3. Test physical target OS browser/fullscreen, genuine Studio and Player, real voice cues, live edit, variants, prefab imports and frozen exports.
4. Publish operations docs, user experience and error recovery; do not release when no-fallback policy or privacy boundary is unverified.

## Files Likely Touched
- `docs/OPERATIONS.md` (verify actual final-branch path before editing)
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- `docs/artifacts.md` (verify actual final-branch path before editing)
- `docs/prefabs.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Unit/integration/E2E suites + real browser, Node, voice trace and media playback, mutation and fault injection.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Report with automated pass/fail evidence, unresolved issues, Human checks and release decision.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/artifacts.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/prefabs.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
