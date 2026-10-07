# Slice 05 — V2 Brain memory integration

## Goal  
Make the authoritative V2 Brain retrieve and inject memory/knowledge under explicit budgets.

## Context  
V2 currently rehydrates conversation summary/recent turns; long-term memory must join this path without moving orchestration to a proxy.

## Canonical Concepts  
Context Assembler, stable context, dynamic recall, authoritative Brain.

## Scope  
### In Scope  
Brain dependency injection, recall query construction, stable profile/scenario injection, turn-dynamic memory recall, provenance labels, token/time budgets, traces and failure isolation.  
### Out of Scope  
Tencent MemoryProxy.

## Dependencies  
03,04.

## Implementation Steps  
Add memory services to V2 app wiring; assemble stable and dynamic context separately; cap memory/tool calls; include provenance labels; record recall metrics; ensure voice latency degradation is bounded.

## Files Likely Touched  
jarvis/core/v2_app.py, brain_service.py, v2_services.py, runtime factory, tests.

## Architecture Constraints  
Brain remains sole context authority. Surface/reflex models cannot directly mutate durable memory. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Integration tests for recall, empty/degraded memory, budget truncation, prompt composition, latency timeout and trace evidence.

## Acceptance Criteria  
V2 answers can use relevant long-term memory; memory failure never blocks an otherwise valid response; injected context is bounded and inspectable.

## Documentation Updates  
Update Brain/context contracts and runtime diagrams.  
