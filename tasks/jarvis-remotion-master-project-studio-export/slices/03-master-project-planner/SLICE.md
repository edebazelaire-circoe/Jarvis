# Slice 03 — Pure deterministic master-project planner

## Goal

Implement the single pure authority that decides whether a variant is master-ready and, when ready, exactly what project/composition must be built.

## Context

Studio, renderer, UI and agent must never diverge on compatibility or project identity.

## Canonical Concepts

MasterProjectPlan/status from Slice 02; exact scene pins/source manifests; project key.

## Scope
### In Scope

- pure domain types/functions for plan/status;
- ordered scene/source validation;
- video-spec compatibility;
- deterministic duration/project key;
- public asset merge/collision plan;
- typed incompatibility reasons;
- unit/conformance fixtures.

### Out of Scope

- disk writes/processes;
- Studio/render/UI wiring;
- source rewriting to force compatibility.

## Dependencies

`02-master-project-contract`.

## Implementation Steps

1. Add pure domain representation with no I/O.
2. Build inputs from current variant + source manifest descriptors through a thin Core service/reader if needed.
3. Implement exact compatibility rules and project key.
4. Ensure all reason codes/messages are bounded and do not expose machine paths.
5. Add deterministic serialization/wire view if Studio/UI/agent needs it.
6. Cover positive/negative planner matrix from `docs/04-testing-and-quality.md`.

## Files Likely Touched

New/updated modules under `jarvis/domain/` and a small `jarvis/core/` read service; protocol/client read route if the contract requires one; tests/fixtures.

## Architecture Constraints

Pure planner does not compile, render, write files or start processes. It consumes canonical exact source metadata and returns facts. Existing Presentation documents remain source of truth.

## Automated Validation

Full planner unit matrix; deterministic key vectors; Python/JS conformance only if logic is ported to browser (prefer server-owned readiness to avoid a duplicate port).

## Acceptance Criteria

- one plan/status is used as the future seam;
- no product data written;
- mixed/incompatible cases fail with contract codes;
- repin/order changes invalidate the key correctly;
- old variant reads remain unchanged.

## Documentation Updates

Promote master-project planning/readiness from Level 2 to Level 3 in canonical docs once implementation/conformance is green.

## Handoff Notes

Coding Slice: `/caveman` + `/coding-guideline`; independent code-review and QA required.
