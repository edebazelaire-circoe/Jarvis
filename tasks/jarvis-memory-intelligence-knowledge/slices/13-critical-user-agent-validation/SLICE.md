# Slice 13 — Independent critic-agent user validation

## Goal  
Use an independent agent as a real user to stress the memory experience and force rework where the UI or behavior is confusing.

## Context  
This is a locked user requirement, not optional polish.

## Canonical Concepts  
Critic agent, user journey, evidence-backed UX validation.

## Scope  
### In Scope  
Independent agent session(s) that operate the actual UI/runtime; realistic tasks; settings changes; memory browse/search; provenance/conflict inspection; recall testing; Wiki/CodeGraph/Skill visibility; degraded-state understanding; issue classification and re-test.  
### Out of Scope  
Pure screenshot review or self-review by the implementing agent.

## Dependencies  
11,12.

## Implementation Steps  
Define user personas/tasks without revealing expected UI paths; run critic with browser/runtime tools; capture actions and confusion; file blocking findings; route fixes to owning Slice or add new Slice; rerun until acceptance.

## Files Likely Touched  
qa/ reports created by QA agent when evidence exists; product files only through rework Slices.

## Architecture Constraints  
Critic must judge from user-visible behavior, not implementation intent. Human validation follows machine/agent validation, never replaces it.

## Automated Validation  
Agent-trace evidence plus runtime/browser evidence for each journey.

## Acceptance Criteria  
Critic can complete core journeys, explain system state accurately, and finds no blocking usability or misleading-state defects.

## Documentation Updates  
Record tested journeys, findings and resulting design decisions.  


## Slice 00 contract

Binding contract, dependencies, wave and QA tier: see `docs/06-resolved-architecture.md` section 3 (this Slice, including any 05b/10a/10b split). It overrides the template above. Inherited red tests: `slices/00-project-manager/READINESS.md`.
