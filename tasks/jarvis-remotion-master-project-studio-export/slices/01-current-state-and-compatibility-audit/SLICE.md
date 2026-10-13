# Slice 01 — Fresh current-state and master-compatibility audit

## Goal

Prove the exact seams for an additive master project and resolve the known compatibility risks before designing behavior-heavy code.

## Context

At planning time Studio and render are scene-scoped while Variants creates full-deck behavior with a Jarvis interval map. The likely minimal master implementation depends on whether scene sources can be mounted together without changing semantics, especially around `useVideoConfig`, FPS/dimensions and `public/staticFile` assets.

## Canonical Concepts

Scene source manifest, source block/composition, exact pin, frozen package, Remotion Studio workspace, render plan, current CompositionClock.

## Scope
### In Scope

- code-read of current owners and contracts;
- real fixture/source census for video specs and asset layouts;
- evaluate exact behavior of `Sequence`/`Series` with local frames and `useVideoConfig` under the pinned Remotion version;
- asset collision census;
- determine whether master generation can remain schema-free;
- identify exact additive API seams for Studio/render/status.

### Out of Scope

- product behavior changes;
- replacing current Player;
- normalizing/mutating stored legacy source code.

## Dependencies

`00-project-manager`.

## Implementation Steps

1. Read current canonical docs and implementation, not just the previous task report.
2. Enumerate every currently supported scene composition width/height/fps in fixtures and representative generated examples.
3. Build a throw-away control Remotion project using the pinned runtime to test child scene behavior in a parent `Sequence`/`Series`, including `useCurrentFrame`, `useVideoConfig`, audio and video media.
4. Inventory `public/**` and `staticFile()` assumptions; prove collision behavior.
5. Confirm what the frozen presentation package already contains and whether it is sufficient for master render without a new persistence schema.
6. Map exact current Studio process/workspace lifecycle and determine the safest target-union seam.
7. Map exact user-level export/MCP/UI seams and old caller compatibility requirements.
8. Produce a compact AUDIT/decision input for Slice 02. If a fundamental conflict is discovered, return to PM instead of implementing around it.

## Files Likely Touched

Audit/evidence under this Slice only; temporary isolated harness code if needed and removed or retained as evidence. No product code.

## Architecture Constraints

Do not prove the concept by pre-rendering scenes and concatenating clips. The target is a source-level editable Remotion master project. No live Jarvis data.

## Automated Validation

- pinned Remotion control harness executes;
- source/fixture census is reproducible;
- audit identifies exact functions/modules/routes and current test owners;
- negative control demonstrates at least one incompatibility if the risk is real.

## Acceptance Criteria

- compatibility risks are evidence-backed, not speculative;
- Slice 02 has enough facts to lock one small compatibility envelope;
- no schema migration is assumed without proof;
- the old-path regression surface is enumerated.

## Documentation Updates

Store audit findings in Slice material and correct this handoff if owner names moved.

## Handoff Notes

Audit-only Slice. Resolve a valid current Workspace Task Type; do not fabricate one. Runtime evidence is expected because pinned Remotion semantics are central.
