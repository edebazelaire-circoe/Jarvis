# Slice 12 - Cue, roles and timeline bridge

## Goal
Map existing PresentationScore and playback state to Remotion frames/segments without replacing Jarvis cue authorization.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Keep existing soft cues, locked sequence steps and speech ownership as canonical state.
- Translate visual actions/anchors to a Player segment seek/play/pause boundary with monotonic timing.
- Preserve interruption, detour, return, who-speaks rules; spontaneous ambient text cannot execute arbitrary actions.
- Expose unsupported score operations explicitly.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
02-engine-and-compatibility-contract, 10-remotion-player-host

## Implementation Steps
1. Keep existing soft cues, locked sequence steps and speech ownership as canonical state.
2. Translate visual actions/anchors to a Player segment seek/play/pause boundary with monotonic timing.
3. Preserve interruption, detour, return, who-speaks rules; spontaneous ambient text cannot execute arbitrary actions.
4. Expose unsupported score operations explicitly.

## Files Likely Touched
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- `docs/presentation-mode.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Fuzz cue matching, duplicate/lost/late events, locked timing, pause/recovery, no spontaneous arbitrary action.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Human and Jarvis presenter can drive Remotion scenes following the existing score and security rules.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/presentation-mode.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
