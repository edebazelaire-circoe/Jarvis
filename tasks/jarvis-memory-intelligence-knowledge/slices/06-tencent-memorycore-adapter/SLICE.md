# Slice 06 — Tencent MemoryCore adapter

## Goal  
Provide an optional sidecar/API adapter for Tencent MemoryCore without surrendering Jarvis authority.

## Context  
MemoryCore can run locally and offers layered memory and hybrid retrieval. It is evolving quickly, so coupling must stay narrow.

## Canonical Concepts  
MemoryRetriever adapter, capability negotiation, derived state, local-only fallback.

## Scope  
### In Scope  
Configuration, lifecycle/health probe, identity mapping, write/mirror policy, recall mapping, timeout/retry, feature flag, rebuild/resync strategy, license/update documentation.  
### Out of Scope  
MemoryProxy as front-door LLM proxy.

## Dependencies  
01,02,03,05.

## Implementation Steps  
Implement adapter against documented v3/SDK boundary; map team/agent/user dimensions; decide what derived content is mirrored; enforce timeouts; expose health/degraded status; add fake adapter tests and optional real PoC benchmark.

## Files Likely Touched  
jarvis/adapters/tencent_memory.py or equivalent, config/settings, runtime wiring, tests, docs.

## Architecture Constraints  
Tencent data is disposable/rebuildable relative to Jarvis canonical memory. Jarvis must start and recall locally with Tencent absent. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Contract tests, sidecar unavailable/slow tests, identity isolation tests, resync tests, optional live PoC metrics.

## Acceptance Criteria  
Feature can be enabled/disabled without migration risk; no canonical write depends solely on Tencent success.

## Documentation Updates  
Integration contract, operational dependencies and upgrade policy.  
