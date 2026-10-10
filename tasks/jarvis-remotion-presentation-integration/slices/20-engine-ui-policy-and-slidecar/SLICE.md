# Slice 20 - Remotion default, Slidecar experiment and no fallback

## Goal
Make engine behavior unambiguous in UI/settings while protecting all existing Slidecar source and test workflows.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Force Remotion in normal agent authoring, preview and export; no agent engine-choice tool or LLM decision.
- Expose Slidecar only behind explicit Human experimental control, clearly labelled and logged.
- Fail closed to visible Remotion error, with diagnosis/repair; NEVER render Slidecar to hide breakage.
- Allow controlled experiments and migration checks without changing previously persisted engine identity or files.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
02-engine-and-compatibility-contract, 10-remotion-player-host, 11-remotion-studio-process-ui, 13-remotion-controls-bridge

## Implementation Steps
1. Force Remotion in normal agent authoring, preview and export; no agent engine-choice tool or LLM decision.
2. Expose Slidecar only behind explicit Human experimental control, clearly labelled and logged.
3. Fail closed to visible Remotion error, with diagnosis/repair; NEVER render Slidecar to hide breakage.
4. Allow controlled experiments and migration checks without changing previously persisted engine identity or files.

## Files Likely Touched
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- `docs/OPERATIONS.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Policy/unit/mocking tests and real runtime fault injection, experimental flag visibility, reload persistence.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Ordinary presentation always uses Remotion, while a user can deliberately test Slidecar.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- **Split**: the policy enforcement (no engine argument on any agent tool, typed errors, no fallback) moves to Slice 02 as tests; this Slice keeps the Human-only experimental toggle, its visibility/logging, repair guidance UI and the persisted-engine-identity migration for existing documents (legacy documents read as `slidecar`, see Slice 02 amendment). Order: after 10 and 13 as before, but its tests depend on Slice 02, not on a late Slice.


## PM addendum after Slice 20 QA (2026-10-10)
"Ordinary presentation always uses Remotion" reads: every presentation created by the plain create route, and every one a human creates without the experiment, is Remotion. Agent-assembled drafts (`presentation_draft_assemble`, HTML scenes) are `slidecar` until Slice 15 flips the assembler (see its PM addendum); they are journaled as `slidecar_created` with actor `agent`, and their use is quoted truthfully. The engine-naming doors of the Control Center relay additionally require `Sec-Fetch-Site: same-origin` (casual-access barrier, `docs/SECURITY.md`).
