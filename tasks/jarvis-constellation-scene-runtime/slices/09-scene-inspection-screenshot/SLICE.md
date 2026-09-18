# Slice 09 — Scene inspection & screenshot

## Goal
Structured scene inspection for the brain beyond the compact listing (filter by kind/category/text/work, detail by id), plus an exceptional on-demand screenshot (Decision 16).

## Context
Audit facts: no screenshot capability exists in Jarvis code (no Playwright/html2canvas/mss/ImageGrab). The Claude brain already runs with `--chrome`, but that controls the user's Chrome session and is not guaranteed to show the Control Center. Rendered positions may include resolver placements that only the browser knows unless committed (see 05).

## Canonical Concepts
`scene_query` / `scene_get` MCP tools returning compact text/JSON. Screenshot: Slice starts with a short spike comparing (a) browser-side capture of the scene layer requested through the transport and returned as a PNG file under `runtime/`, (b) OS window capture, (c) brain `--chrome` screenshot; PM approves the choice before implementation. New heavy dependencies require PM approval. Tool is explicitly marked exceptional in its description.

## Scope
### In Scope
Query tools, spike report, chosen screenshot path, tests.
### Out of Scope
Continuous visual feedback loops.

## Dependencies
03, 05, 06.

## Implementation Steps
1. Query tools. 2. Spike + PM decision recorded in LOG. 3. Screenshot implementation. 4. Real brain trace showing inspect-before-mutate.

## Files Likely Touched
`jarvis/runtime/display_mcp.py`, Core/Control Center routes, `control_center_scene.js`, tests.

## Architecture Constraints
Screenshot never on the normal control path; bounded size; loopback only.

## Automated Validation
Unit tests; agent-trace-analysis.

## Acceptance Criteria
Brain can locate an object by query and verify an overlap visually on demand.

## Documentation Updates
OPERATIONS.md, SECURITY.md (screen content exposure).

## Handoff Notes
Skills: `/caveman`, `/coding-guideline` (+ `/impeccable` if browser capture). QA: qa-verification + code-review + runtime-validation + agent-trace-analysis.
