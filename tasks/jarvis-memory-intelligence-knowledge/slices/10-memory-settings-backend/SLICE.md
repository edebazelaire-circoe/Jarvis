# Slice 10 — Memory settings backend

## Goal  
Expose memory capabilities, effective state and safe configuration through the server-driven Settings model.

## Context  
Jarvis Settings are already described by the server and validated; memory should follow the same pattern.

## Canonical Concepts  
Memory settings schema, effective state, capability/degraded status.

## Scope  
### In Scope  
Settings payload and persistence for memory enablement, semantic retrieval, embedding provider/model, Tencent adapter, consolidation mode, recall budgets, knowledge assets/loadouts; read-only health/stats; validation and migration.  
### Out of Scope  
Final visual layout.

## Dependencies  
03,04,06,07,08,09.

## Implementation Steps  
Define settings defaults/effective values/source; keep secrets out of browser; validate incompatible combinations; report disabled/degraded reasons; persist atomically; expose diagnostics endpoints needed by UI.

## Files Likely Touched  
jarvis/runtime/control_center.py, config modules, settings endpoint tests.

## Architecture Constraints  
Server remains source of truth for available options. Disabling optional intelligence must leave canonical memory usable. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Round-trip/default/env precedence tests, invalid-combination refusal, secret non-disclosure, degraded sidecar/embedding state tests.

## Acceptance Criteria  
UI can render memory configuration without hard-coded backend assumptions and users can understand effective state.

## Documentation Updates  
Settings schema and compatibility matrix.  


## Slice 00 contract

Binding contract, dependencies, wave and QA tier: see `docs/06-resolved-architecture.md` section 3 (this Slice, including any 05b/10a/10b split). It overrides the template above. Inherited red tests: `slices/00-project-manager/READINESS.md`.
