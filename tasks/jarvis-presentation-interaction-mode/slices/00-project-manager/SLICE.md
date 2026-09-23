# Slice 00 - Project Manager readiness and orchestration gate

## Goal
You are the Project Manager and orchestrator for this handoff. Execute this Slice yourself; do not delegate it. Establish that the handoff still matches the live Jarvis repository and make the plan safe to dispatch.

## Context
The handoff was created from `edebazelaire-circoe/Jarvis`, `main` at `ddcdb71e17d7be76236c7dd6ab070af90e8f7d65` on 2026-09-23. Voice, Scene, Bare Hands, settings, and Control Center code are changing quickly, so freshness is mandatory.

## Canonical Concepts
- Voice architecture: Simple / Front Brain / Duplex.
- Existing authorization `conversation_mode`: open-room / solo-owner; not the new interaction mode.
- Existing Scene authority matrix, background event ledger, wake backends, and addressed back-brain admission.

## Scope
### In Scope
- Perform an independent blind repository/context audit based only on Slice goals before reading `docs/05-documentation-levels.md`.
- Reconcile findings with the handoff.
- Verify architecture boundaries, recent competing tasks, test baselines, and settings/control-plane conventions.
- Resolve Workspace Task Types for every Slice, or stop for explicit waiver.
- Repair planning when stale: enrich, split, reorder, supersede, or add Slices.
- Produce `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
### Out of Scope
- Editing product code.
- Delegating Slice 00.
- Treating meeting behavior as defined.

## Dependencies
None.

## Implementation Steps
1. Audit current branch/commit and active handoffs touching voice, wake/arbitration, Bare Hands HUD, Scene, prompts, background events or settings.
2. Inspect current implementation/tests for canonical concepts.
3. Only after blind audit, read handoff documentation-level conclusions and reconcile.
4. Resolve Task Types using the host's real vocabulary; never invent one.
5. Run/record an appropriate clean baseline test set.
6. Check existing/pending work that already introduces interaction modes or shared capture.
7. Amend task if drift makes a Slice unsafe/redundant.
8. Set readiness state; no implementation dispatch below READY.
9. Run targeted freshness check immediately before every later Slice dispatch.

## Files Likely Touched
Planning files in this handoff only.

## Architecture Constraints
- Product code is delegated to Work Agents.
- Preserve project root and task identity.
- Meeting is future/reserved.

## Automated Validation
- Confirm dependency IDs resolve and Human IDs are unique.
- Confirm baseline green or document pre-existing failures precisely.
- Confirm every coding/frontend Slice carries required skills/routing.

## Acceptance Criteria
- Blind audit precedes handoff reconciliation.
- Task Types resolved or explicitly waived.
- Readiness state recorded.
- No dispatch unless READY.
- Stale assumptions repaired, not ignored.

## Documentation Updates
Update `LOG.md`, `slices/TODO.md`, and affected handoff docs if planning changes are required.

## Handoff Notes
Every later Slice receives a targeted freshness check immediately before dispatch.
