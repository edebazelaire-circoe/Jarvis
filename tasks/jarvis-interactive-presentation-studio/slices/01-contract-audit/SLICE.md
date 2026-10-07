# Slice 01 - Presentation Artifact Integration Contract Audit

## Goal
Produce the evidence-backed integration map and canonical names this feature must use before new domain contracts are implemented.

## Context
The repository already has PRESENTATION mode and the active Scene/Prefab task may land while this task waits in `to-do`.

## Canonical Concepts
Interaction mode, ambient authority, presentation working set, scene/window lifecycle, prefab definition/instance, tool/UI intent, resource references.

## Scope
### In Scope
- Map current files/APIs/events for Presentation ambient lane, explicit address, TTS/speech policy, Scene/Prefab, browser/window host, project persistence and agent tools.
- Confirm whether generic fullscreen, edit/prefab authoring or Tool Brain contracts already exist.
- Define the integration seam for this task without duplicating existing systems.

### Out of Scope
- New user-visible behavior.

## Dependencies
- `00-project-manager`

## Implementation Steps
1. Audit canonical docs first, then implementation/tests.
2. Produce a dependency/capability matrix for all later Slices.
3. Identify reusable resource-reference and persistence conventions.
4. Record exact runtime/event/tool names that later Slices must call.
5. Convert any true contract gap into a prerequisite Slice rather than coding around it.

## Files Likely Touched
Canonical documentation and task planning only unless a very small stale-doc correction is required.

## Architecture Constraints
No second Presentation context store, scene runtime, prefab library or UI action scheduler.

## Automated Validation
Documentation-link/path checks and existing relevant contract tests.

## Acceptance Criteria
Later Slices can name real integration points instead of guesses.

## Documentation Updates
Raise/document canonical integration concepts to Level 2 where currently implicit.

## Handoff Notes
Use `/caveman` and `/coding-guideline` only if code corrections become unavoidable; otherwise keep this a contract/audit Slice.
