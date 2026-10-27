# Slice 00 — Project Manager readiness gate

## Goal
You are the Project Manager and orchestrator for this V1.2 amendment handoff. Execute this Slice yourself; do not delegate it.

## Context
This task was created against `main` SHA `2d6ca879afac7a0e773598cff0872b4f819fa876` and has a parent handoff at `Jarvis/task/to-do/jarvis-presentation-edition-v1/`. The repository already implements many of the mechanisms discussed here; V1.2 must amend rather than duplicate them.

## Canonical Concepts
- Board/Session/Board memory/Dossier: `docs/boards.md`.
- Agent roles: `jarvis/domain/subagent_roles.py`.
- Work Methods/relations: `jarvis/domain/work_methods.py` and agent-relations contracts.
- Artifact registry: `docs/artifacts.md`.
- Parent V1 productionization handoff.

## Scope
### In Scope
- perform an independent blind audit of current repository/runtime before reading this handoff's documentation-level conclusions;
- reconcile current `main`, parent V1 and V1.2 amendments;
- inspect active/current/to-do Jarvis tasks for overlap and hot files;
- resolve valid existing Workspace Task Types for every implementation Slice;
- decide readiness: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`;
- repair, split, reorder, supersede or add Slices when evidence requires it;
- confirm which parent V1 Slices should be amended/superseded rather than implemented twice.

### Out of Scope
- no product-code edits;
- no implementation dispatch below `READY`.

## Dependencies
None.

## Implementation Steps
1. Blind-audit current Presentation product policy, brain/tool permissions, Board memory/Dossier, roles/Work Methods/relations, Voice lifecycle/wake word, Settings surfaces, diagnostics, data root/exports, packaging and platform abstractions.
2. Record the current `main` SHA and any changes since task creation.
3. Inspect parent V1 task and current/to-do Jarvis queues for conflicting work.
4. Only now read/reconcile `docs/05-documentation-levels.md` and the locked amendments.
5. Resolve actual valid Workspace Task Types; block a Slice rather than invent a type.
6. Verify external blockers: IGuard contract, support-report destination, wake-word license, macOS signing/notarization/real-device access.
7. Produce one readiness state and the initial dispatch set.
8. Before every later Slice dispatch, run a targeted freshness check of its canonical code/docs and update planning if stale.

## Files Likely Touched
Only this task handoff/planning metadata.

## Architecture Constraints
- V1.2 is newer product intent when it conflicts with parent V1 planning, but code/contracts remain the factual source of current implementation.
- Do not fork Level-3 concepts to satisfy the amendment.
- No product code from Slice 00.

## Automated Validation
Repository/document/Drive queue reconciliation only. No full suite required here.

## Acceptance Criteria
- one readiness state exists;
- current SHA and overlapping tasks are recorded;
- every implementation Slice has a valid resolved Task Type or explicit blocker;
- parent V1 overlap/supersession is explicit;
- no known architecture contradiction is hidden.

## Documentation Updates
Amend this handoff if current evidence invalidates planning assumptions.

## Handoff Notes
Global QA doctrine from README applies. Project Manager remains responsible for all QA verdicts and Human escalation.