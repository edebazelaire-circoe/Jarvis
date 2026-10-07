# Slice 03 — Hybrid retriever

## Goal  
Add local semantic recall fused with existing lexical BM25/FTS recall, with deterministic fallback and bounded latency.

## Context  
Tencent demonstrates a useful hybrid pattern; Jarvis must retain a local lexical-only path.

## Canonical Concepts  
MemoryRetriever, hybrid fusion, recall budget, derived index.

## Scope  
### In Scope  
Embedding adapter, local vector index/store choice, lexical+semantic parallel retrieval, RRF or documented equivalent, filters, dedup, timeouts, metrics, rebuild.  
### Out of Scope  
Long-term consolidation and MemoryCore sidecar.

## Dependencies  
01,02.

## Implementation Steps  
Implement local semantic index; add optional embedding provider; fuse ranked lists; enforce count/token/time budgets; expose degraded capability state; build evaluation fixtures.

## Files Likely Touched  
jarvis/adapters/, jarvis/ports/, runtime wiring, tests.

## Architecture Constraints  
Embeddings are optional; failed embeddings never break lexical recall; no remote dependency required for core startup. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Recall fixture tests, RRF deterministic tests, timeout/fallback tests, index rebuild tests, p50/p95 benchmark evidence.

## Acceptance Criteria  
Hybrid improves representative recall without materially regressing latency; lexical-only mode remains fully functional.

## Documentation Updates  
Document retrieval strategy, fusion and budgets.  
