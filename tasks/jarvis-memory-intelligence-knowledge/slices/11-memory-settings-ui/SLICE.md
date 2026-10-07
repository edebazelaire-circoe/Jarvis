# Slice 11 — Memory settings UI

## Goal  
Add concise, understandable memory controls to the existing Settings experience.

## Context  
The user wants activatable/deactivatable modularity and visibility, while leaving visual interpretation to the implementation agent.

## Canonical Concepts  
Quick settings, effective state, safe affordances, degraded-state explanation.

## Scope  
### In Scope  
Memory settings section; toggles/selectors/budgets where useful; status summaries; links/entry into deep Memory Center; accessibility and responsive behavior.  
### Out of Scope  
Full memory exploration visualization, handled by Slice 12.

## Dependencies  
10.

## Implementation Steps  
Use server-provided schema/state; prototype layout; implement controls; show consequences/dependencies; prevent misleading enabled states; test keyboard/accessibility; apply /impeccable and route frontend work to Claude when supported.

## Files Likely Touched  
control_center HTML/JS/CSS and UI tests.

## Architecture Constraints  
Do not hard-code provider capability lists already owned by server. Visual form is flexible but state meaning must be unambiguous.

## Automated Validation  
DOM/JS unit tests, settings round-trip, browser/runtime validation, accessibility checks.

## Acceptance Criteria  
A user can safely enable/disable/configure memory features and understand what is active without reading docs.

## Documentation Updates  
User-facing settings guide and screenshots only if repository convention requires them.  
