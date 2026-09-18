# Slice 04 — Runtime topology projection

## Goal
Without any LLM turn, every real sub-agent/job becomes a scene star immediately, parent/child links appear, and terminal/attention facts attach minimal signals (Decisions 3, 4, 17).

## Context
Audit facts: Core `WorkStateStore` publishes `core.work.updated` (`jarvis/core/work_state.py:58, :390`) with `{store_id, revision, previous_status, item}`; items carry `source`, `external_id`, `parent_external_id`, `status` (pending/running/blocked/completed/failed/cancelled/interrupted), `error_class`, `summary`. Producers: Claude CLI brain sub-tasks via `TrackerWorkObserver`→`WorkIngressForwarder` (source `claude`; kinds agent/shell), Core jobs (source `job`, incl. back-brain jobs). Codex brain and back-brain job-internal sub-agents produce no sub-tasks. `CoreEventBus` subscribers can be evicted when slow (`v2_services.py:74,187`). Tracker `kind` (`agent`/`shell`/`other`) is not currently guaranteed in `WorkItem` — verify and, if missing, carry it through the ingress contract.

## Canonical Concepts
`SceneProjector` in Core subscribes to `core.work.updated` and issues `actor=runtime` commands. Star rule: `agent` sub-tasks and Core jobs → star; shell/bash/other tool tasks → no star (Decision 4). Identity: `object_id` derived deterministically from `(source, external_id)`. `parent_external_id` → `parent_of` relation. Status → `exec_state` only (never colour, never disposition). `failed`/`interrupted`/`blocked` → `attention` signal object linked to the node, carrying `error_class` and bounded message. On bus eviction or revision gap → full reconciliation from `WorkStateStore.snapshot()`. Initial geometry: none (renderer AutoResolver places unplaced objects; `placed_by=runtime` means "no explicit placement").

PM amendment (Slice 01 QA, F1): the Slice 01 reducer lets runtime create signals but not retire them (no runtime `unlink` of `explains`, no hide/archive; `None` means unchanged so `work_ref`/`geometry` cannot be cleared). This Slice must define and implement the runtime signal lifecycle (e.g. runtime may unlink/resolve `attention` objects whose `origin` is runtime when the underlying work recovers or is superseded) as a reviewed domain change, without granting runtime archive or layout rights. Signals must not accumulate unboundedly per work item (one live attention per `(source, external_id)` updated in place).

PM amendment (Slice 02 QA): `JarvisCoreApplication.stop()` closes the scene before `back_brain.stop()`/`jobs.stop()`; a projector fed by job/work events would hit `SceneUnavailableError` during shutdown. Reorder so writers (projector) stop before the scene closes, and treat `SceneUnavailableError` from the projector as a journaled, non-fatal condition.

## Scope
### In Scope
Projector, subscription resilience, kind propagation if missing, runtime signal lifecycle (see amendment), tests with the fake bus and real `WorkStateStore`.
### Out of Scope
Restart reconciliation of persisted scene vs empty Core (10); artifacts (07).

## Dependencies
01, 02 (03 not required).

## Implementation Steps
1. Verify `kind` availability end to end. 2. Projector + deterministic ids. 3. Gap/eviction resync. 4. Tests: shell task yields no star; nested sub-agent linked; failure creates attention; completion keeps object active; duplicate observations idempotent.

## Files Likely Touched
`jarvis/core/scene_projector.py`, `jarvis/core/v2_app.py`, possibly `jarvis/domain/work_state.py` + `jarvis/runtime/work_ingress.py` (kind), tests.

## Architecture Constraints
Runtime never composes semantics; no geometry beyond "unplaced"; does not block the work pipeline (lossy-safe with resync).

## Automated Validation
Unit + `tests/integration/test_work_state_protocol.py`, `test_work_ui_projection.py` green.

## Acceptance Criteria
Real Claude brain spawning a background sub-agent produces a star in the Core scene snapshot within one work update, with no brain turn involved (trace evidence).

## Documentation Updates
ARCHITECTURE.md (projection authority), state-model doc.

## Handoff Notes
Skills: `/caveman`, `/coding-guideline`. QA: qa-verification + code-review + runtime-validation + agent-trace-analysis (real sub-agent run).
