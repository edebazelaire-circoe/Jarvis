# Slice 02 — Master project, compatibility, Studio and export contract

## Goal

Turn the audit into a precise Level-2 contract before implementation.

## Context

The user has locked the product direction but not low-level policies such as mixed FPS/dimensions or asset collisions. Those choices must be explicit, small and fail-closed.

## Canonical Concepts

Master Remotion project, master composition, compatibility status, project key, Studio target, whole-variant render scope.

## Scope
### In Scope

- define exact master compatibility inputs and typed refusal codes;
- define master video spec and duration rules;
- define deterministic project key/digest inputs;
- define source/public layout and collision policy;
- define generated vs canonical/editable workspace files;
- define Studio target/state/unpublished edits semantics;
- define additive render/export API semantics and Artifact metadata;
- define voice/user-level behavior when master is ready/incompatible.

### Out of Scope

- product code beyond lightweight contract/conformance scaffolding if appropriate;
- phase C;
- arbitrary master-workspace publish-back.

## Dependencies

`01-current-state-and-compatibility-audit`.

## Implementation Steps

1. Reconcile P1-P5 with the audit; record final decisions.
2. Update canonical repository docs at Level 2 without claiming Level 3 implementation yet.
3. Define stable codes/messages for incompatible engine/source/spec/assets and stale master basis.
4. Define project identity and invalidation on repin/order/source changes.
5. Define user semantics: project-level Studio, full-video export, voice re-edit refresh.
6. Define backward compatibility: current scene Studio/render/player remain valid and no caller silently changes meaning.
7. Add doc-conformance tests if current repo practice uses them.

## Files Likely Touched

`docs/presentation-studio.md`, `docs/remotion-studio.md`, `docs/remotion-render.md`, `docs/remotion-source.md`, `docs/ARCHITECTURE.md`, possibly a new focused master-project contract doc if consistent with repository conventions, plus documentation tests.

## Architecture Constraints

One planner contract must be reusable by Studio/render/UI/agent. Do not let each subsystem define readiness independently.

## Automated Validation

- docs name all required/default/optional/forbidden behavior;
- existing doc tests pass;
- new codes/API shapes are uniquely named and do not collide with scene-level semantics;
- documentation clearly labels the existing Variants composition clock as compatibility playback, not the new master Remotion Composition.

## Acceptance Criteria

A fresh implementer can build Slices 03-08 without making a new product decision. Any unresolved trust/schema decision escalates before coding.

## Documentation Updates

This Slice is itself the documentation prerequisite; record current->target levels in the main docs and keep `docs/05-documentation-levels.md` aligned.

## Handoff Notes

If the audit proves a persistent master-spec field is necessary, split a dedicated model/migration Slice before Slice 03 rather than hiding it in implementation.
