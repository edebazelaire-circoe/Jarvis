# Slice 04 — Consolidation pipeline

## Goal  
Turn conversations/evidence into candidate memories and higher abstractions without allowing an LLM to silently rewrite durable truth.

## Context  
Current maintenance only promotes short-term notes marked retain. Target behavior needs deduplication, contradiction handling and L0-L3 abstraction.

## Canonical Concepts  
L0 raw evidence; L1 atomic memory; L2 scenario/context; L3 stable profile. Retention classes remain separate policy dimensions.

## Scope  
### In Scope  
Candidate extraction, dedup, conflict detection, temporal supersession, scoring, promotion policy, provenance, manual/automatic policy modes.  
### Out of Scope  
UI design and Tencent adapter implementation.

## Dependencies  
02,03.

## Implementation Steps  
Define pipeline stages and policies; implement candidate store; detect semantic duplicates/conflicts; support approve/auto policy thresholds; preserve historical assertions; update maintenance worker; add traces.

## Files Likely Touched  
jarvis/core/memory_maintenance.py, memory domain/services, tests.

## Architecture Constraints  
LLM output is a proposal until policy commits it. Contradictory memories remain explainable and temporally ordered. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Dedup/conflict fixtures, temporal preference changes, idempotent reruns, protected-class behavior, malformed extractor output, trace assertions.

## Acceptance Criteria  
Repeated evidence does not create uncontrolled duplicates; changed preferences supersede rather than erase history; all durable promotions have provenance.

## Documentation Updates  
Document consolidation state machine and policy knobs.  
