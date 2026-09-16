# Slice 08 — User interaction & lifecycle

## Goal
Pointer and context-menu interactions that mutate the same scene model as `actor=user`: select, drag (pins), resize, representation toggle, hide/show, archive, and stop/cancel only where the runtime genuinely supports it.

## Context
Audit facts: existing context menu only on Agents cards (`openMenu`/`closeMenu`, `control_center.html:1558-1668`, keyboard accessible); no drag/resize anywhere; Barehands pointer replays clicks but has no drag. Stop support: individual Claude CLI sub-agents **cannot** be stopped (only the whole brain via `/api/agent/kill`); Core jobs can be cancelled (`JobService.cancel_work`, `POST /v1/conversations/{cid}/back-brain/tasks/{job_id}/cancel`).

## Canonical Concepts
User drag commits `set_geometry` + `pin` (`pinned_by_user`). Context menu reuses the existing menu component and keyboard behaviour. Archive = user-only command. "Stop" appears only for job-backed stars; never offered for Claude sub-agent stars (no fake capability). Hidden objects recoverable through a "hidden items" affordance.

PM amendment (Slice 04 QA, capacity): the active scene holds at most 512 objects; completed stars stay until user disposition (Decision 12) and runtime cannot delete. Measured saturation after ~400–420 sub-agents at the real failure mix. This Slice must add: (1) **archive cascade** — user archive of a star also archives its runtime attention signal (no orphan slots), as a reviewed domain/reducer change or a batched user command; (2) **bulk archive** user action (e.g. "archiver les travaux terminés" with confirmation, scoped to completed/cancelled execution stars and their signals, never running work, never brain/user artifacts unless explicitly selected); (3) render the saturation hint from the scene `saturated` flag (added in Slice 04 rework) with a direct path to bulk archive. Brain still has no archive capability.

## Scope
### In Scope
Interactions, menu entries, commands via `/api/scene/commands`, accessibility (keyboard), tests.
### Out of Scope
Voice command parsing (goes through brain/MCP).

## Dependencies
03, 05.

## Implementation Steps
1. Selection/hover. 2. Drag/resize with pin. 3. Menu actions. 4. Job cancel wiring. 5. Browser runtime validation.

## Files Likely Touched
`jarvis/runtime/control_center_scene.js`, `jarvis/runtime/control_center.html`, `jarvis/runtime/control_center.py`, tests.

## Architecture Constraints
Browser is not the owner: optimistic UI must reconcile to server revision. Chrome/panels stay usable.

## Automated Validation
Node tests for interaction reducers; `tests/unit/test_control_center_*`; runtime browser validation.

## Acceptance Criteria
User-archived object leaves active scene and persists so after reload; pinned object never moved by resolver or brain.

## Documentation Updates
OPERATIONS.md user controls.

## Handoff Notes
Skills: `/caveman`, `/coding-guideline`, `/impeccable`; Claude agent. QA: qa-verification + code-review + runtime-validation.
