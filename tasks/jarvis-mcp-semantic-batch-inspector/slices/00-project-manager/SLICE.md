# Slice 00 — Project Manager readiness gate


## Goal
Blind-audit current main, reconcile the handoff, resolve Workspace Task Types, validate QA and Human manifests, and emit exactly one readiness state. Do not edit product code or dispatch implementation before READY.


## Context
This Slice implements part of the MCP semantic-batch/inspector handoff. Read canonical docs and perform a targeted repository freshness check before changes.


## Canonical Concepts
SceneSelection, canonical constellation, atomic scene batch, canonical MCP catalog, human inspector.


## Scope
### In Scope
Blind-audit current main, reconcile the handoff, resolve Workspace Task Types, validate QA and Human manifests, and emit exactly one readiness state. Do not edit product code or dispatch implementation before READY.


### Out of Scope
New Bare Hands gesture bindings; unrelated UI redesign; arbitrary tool explosion or boolean selector DSL.


## Dependencies
None.


## Implementation Steps
1. Perform an independent blind audit of current repository state before relying on handoff conclusions.
2. Reconcile the audit with this handoff and repair planning if needed.
3. Resolve existing Workspace Task Types without inventing values.
4. Confirm every implemented Slice gets `qa-verification`; code changes get `code-review`; runtime/user-visible behavior gets `runtime-validation`; MCP/catalog/prompt/routing/runtime changes get `agent-trace-analysis`.
5. Confirm `/caveman` + `/coding-guideline` on coding Slices and `/impeccable` + Claude routing for frontend when supported.
6. Validate dependency graph and Human-check IDs.
7. Emit `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.


## Files Likely Touched
Use the architecture document's touch points and current repository evidence. Slice 00 may refine this list after blind audit.


## Architecture Constraints
Project Manager may repair planning but must not use Slice 00 to implement product code.
Do not duplicate domain semantics in MCP/UI. Do not increase model-visible tool surface merely for inspector convenience.


## Automated Validation
`qa-verification`; `code-review` for code changes; `runtime-validation` for runtime/user-visible behavior; `agent-trace-analysis` for MCP/catalog/prompt/runtime changes.
Tests must prove the acceptance claims of this Slice, not only happy-path execution.


## Acceptance Criteria
Blind-audit current main, reconcile the handoff, resolve Workspace Task Types, validate QA and Human manifests, and emit exactly one readiness state. Do not edit product code or dispatch implementation before READY.
No regression caused by this Slice remains unresolved.


## Documentation Updates
Update canonical scene/MCP docs for any contract delivered here; never leave stale duplicate truth.


## Handoff Notes
Project Manager adjudicates QA. Human validation, when declared, occurs only after machine-detectable failures are cleared.