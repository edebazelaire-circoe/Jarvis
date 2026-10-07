# Slice 12 — Memory Center UX

## Goal  
Create a deep inspection/management surface where users can understand what Jarvis remembers, why, how it was derived, and what memory intelligence is doing.

## Context  
The user explicitly allows broad visual interpretation and considers a dedicated memory page highly valuable.

## Canonical Concepts  
Memory Center, provenance, abstraction level, retention class, derived index health, knowledge assets, recall diagnostics.

## Scope  
### In Scope  
Search/browse memory; inspect canonical content/provenance/version/conflicts; view L0-L3/retention dimensions without conflating them; inspect Wiki/CodeGraph/Skills/loadouts; show index/sidecar health; safe rebuild/test actions; recall test sandbox; navigation from Settings.  
### Out of Scope  
A prescribed graph visualization or mandatory layout.

## Dependencies  
02,03,04,06,07,08,09,10.

## Implementation Steps  
Design multiple candidate information architectures; choose based on usability; implement deep page/panel; add safe actions with confirmations where destructive; provide “why recalled?” diagnostics; test realistic datasets; apply /impeccable and Claude routing where supported.

## Files Likely Touched  
Control Center routes/UI modules, memory diagnostics endpoints, frontend tests.

## Architecture Constraints  
Visual representation is intentionally free. Optimize for comprehension and action, not feature density. Never imply derived state is canonical.

## Automated Validation  
Browser/runtime flows for browse/search/filter/detail/rebuild/recall-test, empty/error/degraded states, accessibility and responsive checks.

## Acceptance Criteria  
A non-author can tell what Jarvis remembers, where it came from, whether it is canonical/derived, and safely test or adjust the system.

## Documentation Updates  
Memory Center user guide and UX decisions.  
