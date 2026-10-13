# Slice 04 — Materialize and compile the full variant Remotion project

## Goal

Turn a ready MasterProjectPlan into a normal bounded Remotion project workspace and prove the master composition compiles/runs under the pinned runtime.

## Context

This is the source-level bridge that was missing: all exact scene sources live together under one generated project/root instead of Remotion Studio receiving one scene source.

## Canonical Concepts

MasterProjectPlan, generated master composition, source namespace, public asset merge, runtime package tree.

## Scope
### In Scope

- pure project-file planning where possible;
- source namespacing under one project;
- generated root/master component using native Remotion sequencing;
- per-scene props/data wiring;
- deterministic merged public assets;
- bounded workspace materialization adapter;
- real compile/discovery tests with pinned Remotion.

### Out of Scope

- opening Studio;
- MP4 export;
- making master files canonical/editable;
- replacing current preview Player.

## Dependencies

`03-master-project-planner`.

## Implementation Steps

1. Implement a master workspace file planner separate from the existing scene `plan_workspace` so scene semantics remain stable.
2. Copy exact source bytes into collision-free source namespaces; preserve relative imports.
3. Merge public assets exactly per contract; never rewrite `staticFile()` strings silently.
4. Generate project/root/master Composition registration and master orchestration.
5. Wire scene instance props/data from the variant/snapshot plan.
6. Enforce current source/project bounds and safe-relative path rules.
7. Compile/discover master composition with the real pinned runtime in isolated tests.
8. Add a small materialization adapter reusable by Studio and render planning, or keep render file planning pure if existing architecture prefers that.

## Files Likely Touched

New domain/project-plan module, adapters near `remotion_studio_runner` and render plan, current source utilities, pinned runtime harness/tests, docs.

## Architecture Constraints

Use native Remotion sequencing/time. No wall-clock JS scheduler. No pre-rendered clip concatenation. Existing scene workspace files/behavior remain unchanged.

## Automated Validation

- real compile of 3+ scenes;
- composition discovery and exact duration;
- frame boundary/local-frame checks;
- audio/video media sample;
- asset collision negative control;
- safe path/link guards;
- project deterministic bytes/digest where expected.

## Acceptance Criteria

A ready variant can be represented as one self-contained generated Remotion source project using only the existing approved runtime dependencies and security policy, without mutating canonical presentation/source data.

## Documentation Updates

Document actual workspace shape and generated/canonical boundaries.

## Handoff Notes

Coding/runtime Slice: `/caveman` + `/coding-guideline`; QA, code-review and runtime-validation required.
