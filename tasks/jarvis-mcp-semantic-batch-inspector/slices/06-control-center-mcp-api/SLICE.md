# Slice 06 — Control Center MCP catalog API


## Goal
Expose read-only compact list and detailed tool endpoints backed by the canonical catalog, including provable known/configured/advertised/conditional/deprecated status, stable errors and secret-leak tests. No tool execution endpoint.


## Context
This Slice implements part of the MCP semantic-batch/inspector handoff. Read canonical docs and perform a targeted repository freshness check before changes.


## Canonical Concepts
SceneSelection, canonical constellation, atomic scene batch, canonical MCP catalog, human inspector.


## Scope
### In Scope
Expose read-only compact list and detailed tool endpoints backed by the canonical catalog, including provable known/configured/advertised/conditional/deprecated status, stable errors and secret-leak tests. No tool execution endpoint.


### Out of Scope
New Bare Hands gesture bindings; unrelated UI redesign; arbitrary tool explosion or boolean selector DSL.


## Dependencies
04, 05


## Implementation Steps
1. Freshness-check relevant repository contracts and tests.
2. Implement only this Slice's semantic boundary.
3. Add or adjust targeted tests before broad integration.
4. Update canonical documentation when contracts change.
5. Run required QA and return evidence to the Project Manager.


## Files Likely Touched
Use the architecture document's touch points and current repository evidence. Slice 00 may refine this list after blind audit.


## Architecture Constraints
Require `/caveman` and `/coding-guideline` for coding work.
Do not duplicate domain semantics in MCP/UI. Do not increase model-visible tool surface merely for inspector convenience.


## Automated Validation
`qa-verification`; `code-review` for code changes; `runtime-validation` for runtime/user-visible behavior; `agent-trace-analysis` for MCP/catalog/prompt/runtime changes.
Tests must prove the acceptance claims of this Slice, not only happy-path execution.


## Acceptance Criteria
Expose read-only compact list and detailed tool endpoints backed by the canonical catalog, including provable known/configured/advertised/conditional/deprecated status, stable errors and secret-leak tests. No tool execution endpoint.
No regression caused by this Slice remains unresolved.


## Documentation Updates
Update canonical scene/MCP docs for any contract delivered here; never leave stale duplicate truth.


## Handoff Notes
Project Manager adjudicates QA. Human validation, when declared, occurs only after machine-detectable failures are cleared.

## Slice 00 refinements
Read `slices/00-project-manager/READINESS.md` §2–§5 before starting: blind-audit touch points, inherited red tests (not yours), and baseline-realignment ownership.
