# Slice 10 - Embed Remotion Player into Jarvis scene fullscreen

## Goal
Show playable, seekable, prop-driven Remotion previews through Jarvis with the existing surface semantics.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Bind a Remotion composition to a current logical Studio scene, preserve scene identity and stage window owner.
- Support props updates without rendering video, play/pause/seek/duration and status.
- Honor browser audio/autoplay and fullscreen user gesture constraints.
- Do not let a Player host evade existing prefab/Scene security restrictions.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
05-remotion-project-source-contract, 06-remotion-source-isolation, 02-engine-and-compatibility-contract

## Implementation Steps
1. Bind a Remotion composition to a current logical Studio scene, preserve scene identity and stage window owner.
2. Support props updates without rendering video, play/pause/seek/duration and status.
3. Honor browser audio/autoplay and fullscreen user gesture constraints.
4. Do not let a Player host evade existing prefab/Scene security restrictions.

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
- Real browser Player props, seek, multiple scene switching, Player mount failures, fullscreen Esc.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- One Remotion scene displays in Jarvis and can change color/timing rapidly while staying editable.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- **Host reality**: playback shows a scene as a **prefab window object** on a stage window (`jarvis/core/presentation_studio_stage.py:168` `SceneStage`, playback `jarvis/core/presentation_studio_playback.py`), and fullscreen needs a user gesture (R06). Decide in this Slice whether the Player runs inside the sandboxed prefab frame (`control_center_prefab_host.js`) or as a new window kind; either way the stage ledger/reclaim rules (Doc `:2048`) and the pin registry must keep working. Do not claim voice-only fullscreen.
- Depends on the compile contract added to Slice 05.
