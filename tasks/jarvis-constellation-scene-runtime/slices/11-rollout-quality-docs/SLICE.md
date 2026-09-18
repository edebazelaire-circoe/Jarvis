# Slice 11 — Rollout, quality & docs

## Goal
Ship behind a feature flag, prove the whole feature end to end with real agents, keep legacy behaviour intact, and finish documentation.

## Context
Audit facts: flag patterns exist (`self_development.enabled` in `runtime/control-center-settings.json`, `JARVIS_*` env defaults); CI runs `python -W error::ResourceWarning -m pytest -q` + `python scripts/verify_release.py`; `test_documented_routes.py` binds docs to routes; background badges and theme API are undocumented today.

## Canonical Concepts
`scene.enabled` setting (default off until Human acceptance, then Human decides default). PM decision: projector and store run regardless of the flag (cheap, keeps history); the renderer and brain MCP wiring are gated. Legacy Agents panel, badges, Omega/circuit-board themes, Barehands, voice unchanged.

## Scope
### In Scope
Flag + settings UI entry, full-suite run, end-to-end scenario (voice/text request → background sub-agent → star → completion → brain artifact → reload → restart → user archive), docs (ARCHITECTURE, OPERATIONS, SECURITY, scene model), Human check list.
### Out of Scope
Changing default flag without Human.

## Dependencies
04–10.

## Implementation Steps
1. Flag. 2. Full suite + verify_release. 3. E2E real run with evidence (screenshots, trace excerpts). 4. Docs. 5. Human validation checklist.

## Files Likely Touched
Settings code/UI, docs, tests.

## Architecture Constraints
No regression in legacy panels; flag off = zero visible change.

## Automated Validation
Full suite; verify_release; documented routes; runtime + agent-trace analysis.

## Acceptance Criteria
TODO "Task done when" criteria all evidenced.

## Documentation Updates
All listed above.

## Handoff Notes
Skills: `/caveman`, `/coding-guideline` (+ `/impeccable` for settings UI). QA: all four.
