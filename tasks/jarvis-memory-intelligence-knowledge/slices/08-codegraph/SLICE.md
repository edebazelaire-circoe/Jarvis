# Slice 08 — CodeGraph

## Goal  
Add code-structure knowledge so coding/review agents can navigate symbols, files, calls and impact relationships.

## Context  
The user explicitly wants CodeGraph in this implementation rather than deferred.

## Canonical Concepts  
CodeGraph asset, repository snapshot, symbol identity, edge provenance, agent loadout.

## Scope  
### In Scope  
Repository indexing; symbols/files/imports/calls/references or equivalent relationships; incremental refresh; query API; source commit/version; agent consumption.  
### Out of Scope  
Replacing language servers or static analyzers wholesale.

## Dependencies  
01,07.

## Implementation Steps  
Choose graph representation; extract repository structure; persist as derived/rebuildable state; expose neighbor/path/impact queries; bind results to commit/file/line provenance; integrate loadouts and traces.

## Files Likely Touched  
knowledge/codegraph modules, repository adapters, agent context/tooling, tests.

## Architecture Constraints  
CodeGraph is derived state and must be rebuildable. Never present stale graph data without snapshot provenance. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Known-repo fixture graph tests, incremental update tests, stale snapshot detection, query correctness, performance limits.

## Acceptance Criteria  
A coding agent can answer “where is this used?” and “what is impacted?” with traceable graph evidence.

## Documentation Updates  
CodeGraph schema, refresh rules and supported query semantics.  


## Slice 00 contract

Binding contract, dependencies, wave and QA tier: see `docs/06-resolved-architecture.md` section 3 (this Slice, including any 05b/10a/10b split). It overrides the template above. Inherited red tests: `slices/00-project-manager/READINESS.md`.
