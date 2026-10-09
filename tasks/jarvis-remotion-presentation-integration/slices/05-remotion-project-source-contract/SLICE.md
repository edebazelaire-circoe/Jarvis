# Slice 05 - Source workspace and module layout

## Goal
Define and implement stable source module layout for Remotion scenes without treating each presentation as an independent Node project.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Create project manifest, source modules, variant/scenes and scoped public assets using canonical data root.
- Implement deterministic path resolution and content hashing; keep source read/write through Core.
- Keep per-scene editability and score identity stable, store Remotion engine/version/dependency lock.
- No raw absolute path or stale ephemeral ports in Board context.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
02-engine-and-compatibility-contract, 04-remotion-one-time-provisioning

## Implementation Steps
1. Create project manifest, source modules, variant/scenes and scoped public assets using canonical data root.
2. Implement deterministic path resolution and content hashing; keep source read/write through Core.
3. Keep per-scene editability and score identity stable, store Remotion engine/version/dependency lock.
4. No raw absolute path or stale ephemeral ports in Board context.

## Files Likely Touched
- `docs/local-data.md` (verify actual final-branch path before editing)
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Crash/reopen, path traversal, changed data root, modules with same filenames, source identity tests.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- One prepared presentation source reopens after Core/host restart; no node_modules copied.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/local-data.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- **Decide first, with evidence**: store a Remotion scene source as a **new bundle kind of the existing versioned prefab library** (immutable `(id, version)` folders, `PrefabService.save`, `PrefabDraftCoalescer`, `StudioPinRegistry`, retention and `held_pins()`, hot-reload rollback: `docs/prefabs.md:343-397`, `jarvis/core/presentation_studio_reload.py:110`) **or** a separate `<data_root>/remotion/` tree. Recommended: reuse the prefab pipeline (it already solves pinning, retention, undo pins, scene-local variants, crash recovery), with Remotion files held in the bundle and one shared Node dependency tree. To be proven in this Slice: the prefab bundle file set and manifest are closed (`_MANIFEST_KEYS`, `jarvis/domain/prefab.py:614`; `compose_candidate`, `jarvis/domain/presentation_studio_reload.py:159`), so TSX files need a manifest/schema change (see Slice 17 amendment on manifest versioning).
- **Add**: the compile contract (what turns the TSX source into a browser bundle for the Player, in which managed process, with which timeout and output cache). Slice 10 consumes it; it does not exist anywhere in the plan.
- Per-scene identity must stay `StudioScene.scene_id` and score anchors `ScoreAnchor` (`presentation_studio_scene.py:222`) must keep resolving.
