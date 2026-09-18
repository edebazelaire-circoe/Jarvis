# Slice 10 — Restart reconciliation

## Goal
After browser reload, Control Center restart, Core restart, or brain restart, the scene is restored and reconciled with execution truth without losing completed-but-unreviewed work.

## Context
Audit facts: Core work state is memory-only; on Core restart it is empty under a new `store_id`, `JobService.recover` marks pending/running jobs interrupted (`core_restarted`), producers re-send full state (`WorkIngressForwarder` resync, 30 s idle full re-send), and a new producer interrupts its unmentioned items (`producer_restarted`). The tracker marks all running tasks `interrupted` on brain `process_started/stopped`. The scene store (02) is durable.

## Canonical Concepts
On Core start: persisted execution nodes with non-terminal `exec_state` become `unknown` until re-observed; after a grace window aligned with producer resync (≥ one full re-send period) still-unobserved nodes become `interrupted` with a runtime attention signal. Terminal nodes and all brain/user objects are untouched. Never delete; never change disposition. Browser: snapshot on load, resume patches.

## Scope
### In Scope
Reconciler in Core, grace timer, tests for each restart path, runtime validation of real restarts.
### Out of Scope
Persisting Core work state itself.

## Dependencies
02, 03, 04, 05.

## Implementation Steps
1. Startup marking. 2. Re-observation matching by `(source, external_id)`. 3. Grace expiry. 4. Tests + real restart runs.

## Files Likely Touched
`jarvis/core/scene_projector.py` or `scene_reconciler.py`, `jarvis/core/v2_app.py`, tests.

## Architecture Constraints
Deterministic, journaled transitions; no scene-wide wipe on `store_id` change.

## Automated Validation
Unit + `tests/integration/test_v2_core_recovery.py`.

## Acceptance Criteria
Completed task star + artifact survive Core and Control Center restarts; a sub-agent killed by restart shows interrupted, not silently removed.

## Documentation Updates
OPERATIONS.md restart behaviour.

## Handoff Notes
Skills: `/caveman`, `/coding-guideline`. QA: qa-verification + code-review + runtime-validation.
