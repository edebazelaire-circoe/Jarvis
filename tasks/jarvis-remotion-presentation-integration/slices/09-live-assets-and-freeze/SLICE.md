# Slice 09 - Live Board references and immutable freeze

## Goal
Resolve infoboard assets safely for editing and package self-contained assets when the user freezes or exports.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Resolve validated Board/Context/Artifact IDs and explicit resource_ref; never trust freeform paths blindly.
- Support live changes and missing assets as visible errors during edit.
- Freeze exact code, score, DA, pins, dependency versions and required binaries with hashes.
- Ensure frozen export works after source Board moves, session expires or external URL changes.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
05-remotion-project-source-contract, 06-remotion-source-isolation, 08-artifact-board-registration

## Implementation Steps
1. Resolve validated Board/Context/Artifact IDs and explicit resource_ref; never trust freeform paths blindly.
2. Support live changes and missing assets as visible errors during edit.
3. Freeze exact code, score, DA, pins, dependency versions and required binaries with hashes.
4. Ensure frozen export works after source Board moves, session expires or external URL changes.

## Files Likely Touched
- `docs/artifacts.md` (verify actual final-branch path before editing)
- `docs/local-data.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Missing/moved asset, incomplete download, checksum, offline reopen, revocation and secret-leak tests.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Frozen package replays without original board/local paths or expiring remote URLs.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/artifacts.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/local-data.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- Existing base: `ResourceReference` kinds (`jarvis/domain/presentation_working_set.py:247-261`) are references only, resolved by the working-set owner; there is **no** freeze or export code (R17). The freeze package is new; the live-reference resolution should reuse the working-set resolver, not add a second one.
