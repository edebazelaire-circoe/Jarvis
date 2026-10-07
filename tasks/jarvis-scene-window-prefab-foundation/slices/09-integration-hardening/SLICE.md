# Slice 09 — Integration Hardening and Presentation Handoff Seam

## Goal

Complete migration, eliminate unsafe duplicate paths where proven obsolete, run full QA, and leave a stable public seam for the Presentation task to consume later.

## Context

This task should end with a reusable substrate, not a demo path. Presentation integration remains separate but needs a precise dependency contract.

## Canonical Concepts

Scene contract, prefab catalog, prefab instance, Presentation consumption seam.

## Scope

### In Scope

- Complete audited legacy call-site migration.
- Remove duplicate/dead paths only with evidence.
- Full regression suite and browser runtime validation.
- Real agent trace proving discovery -> instantiate -> interact -> fork/save -> rediscover.
- Produce concise integration notes for Presentation mode: which public operations/contracts it may rely on.

### Out of Scope

- Implementing the Presentation conductor or board-local presentation settings.

## Dependencies

- `08-prefab-library-management`

## Implementation Steps

1. Re-run repository-wide architecture and duplicate-path audit.
2. Migrate remaining in-scope window/prefab call sites.
3. Remove obsolete paths after proof of no consumers.
4. Run full frontend/backend/runtime/visual tests appropriate to touched code.
5. Run a real agent/tool trace for the full prefab lifecycle.
6. Write the stable Presentation integration seam and explicit non-goals.
7. Escalate to Human validation only after all machine findings are cleared.

## Files Likely Touched

Migration call sites, conformance tests, architecture docs, Presentation dependency/integration note (documentation only).

## Architecture Constraints

Do not sneak Presentation behavior into this final Slice. Only document/use the public dependency seam.

## Automated Validation

- Full relevant unit/integration/browser suite.
- Architecture/conformance gates.
- Leak/lifecycle stress test.
- Real agent trace analysis.
- No new console/server errors in representative scene flows.

## Acceptance Criteria

- No known duplicate canonical prefab runtime remains in scope.
- Window and custom prefab flows use the same supported substrate.
- End-to-end reuse/fork/save workflow is proven.
- Presentation has a stable documented consumption contract.
- All regressions are cleared.

## Documentation Updates

Finalize documentation levels and integration seam docs.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.

## Slice 00 contract (binding)

Do:
1. Re-audit: grep for any second renderer, catalogue or event path; confirm `srcdoc` in one file; architecture and documented-routes gates.
2. Legacy retention proof (D-LEGACY): list consumers of the legacy window path (`scene_projector.py`, `display_mcp.add_artifact`, `presentation_staging.py`, file watcher) in `docs/prefabs.md` §"Legacy windows", and state that they are retained. **No deletion.**
3. Stress (browser + node): 200 create/archive cycles of prefab windows; frame count ≤ cap and back to 0; no listener growth; 30 simultaneous prefab windows → cap and placeholder; event flood → rate limit with no Core error storm.
4. Full suites: `pytest` (whole), node JS suites, Chrome flows of S04-S08 replayed; no new console errors or `core.*` error diagnostics during flows.
5. Real agent trace of discovery → instantiate → interact → fork/save → rediscover → reuse (agent-trace-analysis).
6. Presentation seam: `docs/prefabs.md` §"Consumers": public operations Presentation may use (`prefab_search`, `prefab_get`, `scene_create_object` with `prefab` and `visibility` through `SceneDisplayTools.create_object(visibility="hidden")`, `scene_update_object`, `prefab_events`), and non-goals. Documentation only; `presentation_staging.py` untouched (see Issue on `set_visibility`).
7. Finalize documentation levels in `docs/prefabs.md` and this handoff's doc 05.

Acceptance: all of the above evidenced in LOG.md; zero regressions; Issues updated.
Depends on: 08.
QA: qa-verification + code-review + runtime-validation + agent-trace-analysis. Human: HV-PREFAB-E2E-01 last.
