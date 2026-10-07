# Implementation Strategy

Implement contracts first, then canonical metadata/provenance, local hybrid retrieval, consolidation, V2 Brain integration, Tencent adapter, Wiki/CodeGraph/Skills, settings, Memory Center, critic validation, and final rollout.

Migration is additive: existing Markdown notes and retention directories remain valid. New metadata must tolerate legacy notes. Derived indexes are rebuilt rather than treated as migration-critical truth. Tencent features are feature-gated and must not prevent startup or recall when disabled/unavailable.

Benchmark correctness and latency: recall quality, false recalls, p50/p95 latency, injected tokens and fallback behavior.  
