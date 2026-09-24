# Slice 07 — Human MCP inspector UI


## Goal
Add the MCP dock button and dedicated inspector with status summary, search, semantic tabs, compact default cards, per-card/global detail expansion, parameter required/optional/default/constraints, readable output schemas, badges, and keyboard/focus/responsive/reduced-motion behavior. No arbitrary tool execution.


## Context
This Slice implements part of the MCP semantic-batch/inspector handoff. Read canonical docs and perform a targeted repository freshness check before changes.


## Canonical Concepts
SceneSelection, canonical constellation, atomic scene batch, canonical MCP catalog, human inspector.


## Scope
### In Scope
Add the MCP dock button and dedicated inspector with status summary, search, semantic tabs, compact default cards, per-card/global detail expansion, parameter required/optional/default/constraints, readable output schemas, badges, and keyboard/focus/responsive/reduced-motion behavior. No arbitrary tool execution.


### Out of Scope
New Bare Hands gesture bindings; unrelated UI redesign; arbitrary tool explosion or boolean selector DSL.


## Dependencies
06


## Implementation Steps
1. Freshness-check relevant repository contracts and tests.
2. Implement only this Slice's semantic boundary.
3. Add or adjust targeted tests before broad integration.
4. Update canonical documentation when contracts change.
5. Run required QA and return evidence to the Project Manager.


## Files Likely Touched
Use the architecture document's touch points and current repository evidence. Slice 00 may refine this list after blind audit.


## Architecture Constraints
Require `/caveman` and `/coding-guideline` for coding work. Also require `/impeccable` and Claude Work Agent routing when supported.
Do not duplicate domain semantics in MCP/UI. Do not increase model-visible tool surface merely for inspector convenience.


## Automated Validation
`qa-verification`; `code-review` for code changes; `runtime-validation` for runtime/user-visible behavior; `agent-trace-analysis` for MCP/catalog/prompt/runtime changes.
Tests must prove the acceptance claims of this Slice, not only happy-path execution.


## Acceptance Criteria
Add the MCP dock button and dedicated inspector with status summary, search, semantic tabs, compact default cards, per-card/global detail expansion, parameter required/optional/default/constraints, readable output schemas, badges, and keyboard/focus/responsive/reduced-motion behavior. No arbitrary tool execution.
No regression caused by this Slice remains unresolved.


## Documentation Updates
Update canonical scene/MCP docs for any contract delivered here; never leave stale duplicate truth.


## Handoff Notes
Project Manager adjudicates QA. Human validation, when declared, occurs only after machine-detectable failures are cleared.