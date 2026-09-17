# 03 - Implementation Strategy

1. Freeze domain/schema contracts before behavior-heavy work.
2. Add persistence and DiagnosticBundle normalization early so later work produces durable evidence.
3. Implement safe scenario/catalog contracts before profile runners.
4. Add supervisor/worker isolation before live/hardware execution.
5. Generalize the existing async conversation harness into the first `virtual` profile rather than duplicating it.
6. Add metrics/scoring/sweeps on top of durable runs.
7. Add audio/live/hardware profiles progressively, with explicit resource gates.
8. Expose native API/CLI before UI so both agents and Control Center use the same backend contracts.
9. Add Control Center UI after backend contracts stabilize.
10. Finish with seed diagnostics, cross-profile comparison, retention, docs, and release integration.

Migration rule: preserve existing pytest/integration tests. Category 2 may reuse their harnesses, but it does not replace normal deterministic CI coverage.

Freshness rule: immediately before every Slice, recheck relevant current files because voice and observability work are active in parallel.
