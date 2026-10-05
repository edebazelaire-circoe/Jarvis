# Slice 01 — Reconcile Presentation contracts with current Jarvis

## Goal

Establish the exact canonical boundaries Presentation must use before behavior implementation.

## Context

Existing Jarvis work already references `presentation-audio-capture`, `presentation-ambient-lane`, `presentation-working-set`, interaction-mode persistence, conversation observability, Session/Context, Tool Brain and Scene/Prefab concepts. The task must consolidate rather than duplicate them.

## Canonical Concepts

Interaction mode, ambient lane, addressed turn, Session, Context, working set, Tool Brain intent, scene/prefab instance, conversation event.

## Scope

### In Scope

- Identify current owners/APIs/events for each concept.
- Mark which Presentation pieces already exist and which are missing/incomplete.
- Define canonical authority boundary between ambient speech and addressed Jarvis turns.
- Define integration seams for Tool Brain and Scene/Prefab without reimplementing them.
- Upgrade/repair dedicated Presentation docs where contracts are ambiguous.

### Out of Scope

- Implementing behavior beyond minimal contract/schema scaffolding required to make the boundaries testable.

## Dependencies

- `00-project-manager`

## Implementation Steps

1. Audit current Presentation and interaction-mode docs/source/tests.
2. Audit existing ambient transcription and explicit-address routing.
3. Audit canonical event/timeline contract.
4. Audit Tool Brain and Scene/Prefab public contracts or current task output.
5. Produce a single source-of-truth Presentation contract map.
6. Add/repair schemas/enums/events only where ambiguity would block later Slices.

## Files Likely Touched

Presentation docs/contracts, shared interaction-mode/event schemas, focused contract tests.

## Architecture Constraints

Do not create parallel Session, recording, UI-tool, scene or event models.

## Automated Validation

Schema/contract tests; static checks that no duplicate Presentation settings/event registries were introduced; documentation link checks where available.

## Acceptance Criteria

A fresh implementer can identify the canonical owner and API/event path for every dependency used by Slices 02–10.

## Documentation Updates

Bring Presentation contract docs to at least Level 2, and Level 3 where reusable validators/schemas already exist.

## Handoff Notes

If a dependency contract is still being implemented elsewhere, record the exact required public shape and gate only the affected adapter Slice.
