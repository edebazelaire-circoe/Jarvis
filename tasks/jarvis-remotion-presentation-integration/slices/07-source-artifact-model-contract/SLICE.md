# Slice 07 - Editable source parent vs terminal Artifacts

## Goal
Reconcile editable presentations with existing closed/terminal Artifact model before touching persistence.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Audit `ArtifactKind`, terminal `complete` invariants, relations, payload ref rules and `Presentation` file store.
- Define stable navigable identity for mutable parent source without rewriting finalized Artifact payload.
- Choose minimal mapping/extension and record migration plus schema evolution, backward compatibility and Board lookup.
- Explicitly distinguish editable source, frozen snapshot and rendered derivatives.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
01-final-branch-conformance, 02-engine-and-compatibility-contract

## Implementation Steps
1. Audit `ArtifactKind`, terminal `complete` invariants, relations, payload ref rules and `Presentation` file store.
2. Define stable navigable identity for mutable parent source without rewriting finalized Artifact payload.
3. Choose minimal mapping/extension and record migration plus schema evolution, backward compatibility and Board lookup.
4. Explicitly distinguish editable source, frozen snapshot and rendered derivatives.

## Files Likely Touched
- `docs/artifacts.md` (verify actual final-branch path before editing)
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
- Contract tests for parent identity, immutable derived children, no accidental overwrites and no phantom artifact links.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Accepted Level 2 contract satisfying user intent and repository immutability simultaneously.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/artifacts.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/local-data.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- Confirmed against code: `ArtifactKind` is closed (7 kinds, `jarvis/domain/artifacts.py:136-148`), `complete`/`partial`/`failed` are terminal (`:150-163`), relation kinds closed (`:165-180`), and `WorkspaceService.artifact_link` accepts only a valid `jart_` artifact id (`jarvis/core/workspace_service.py:801-805`). A Presentation (`pres_`/`<data_root>/presentations/`) therefore **cannot** be Board-linked today and is explicitly "not an Artifact" (`docs/presentation-studio.md:10-17`).
- Therefore the recommended split to evaluate (P01): the mutable source stays a Presentation reached through a **stable catalog link** (no mutable Artifact); frozen snapshots and rendered derivatives (MP4, still, PDF) are real, immutable Artifacts with new kinds and a new relation kind (adding a kind needs the enum value plus `docs/artifacts.md`, no migration: `artifacts.py:137-139`). Board memory also holds `artifact_refs` (`jarvis/core/board_service.py:95,219`): name one owner for "which Boards show this".
- Any `jarvis.sqlite3` change goes through `_MIGRATIONS` with the schema snapshot (CLAUDE.md); say so in the Slice's acceptance.
