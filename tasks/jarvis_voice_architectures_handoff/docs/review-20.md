# Task20 orchestrator review

Accepted 2026-09-13 with no open P0/P1/P2 finding.

The first runner was rejected because it constructed each expected state and
then evaluated that same state as a 13/13 success. It was replaced by a CLI
that executes exact production-seam pytest nodes before writing evidence.

The first independent pass found that architecture-neutral policy tests were
then counted as successes for Simple, Front Brain and Duplex. The final report
separates `shared_contract_evidence`, per-architecture evidence and `not_run`;
Task18 annotations follow the same distinction.

The second adversarial pass showed that a global allowlist still allowed valid
tests to be reassigned to the wrong scenario, architecture or migration claim,
and allowed fixture parameters to disagree with the cited test. Suite v1 now
binds exact ordered definitions and node roles in immutable mappings. Tests
prove that role swaps and in-range parameter changes are rejected.

The migration review also found incorrect `simple` provenance for compatibility
sessions and an uncaught explicit `VoiceConfigError`. Both production issues
have direct startup tests. Compatibility migration is verified separately and
its samples remain excluded from architecture comparison.

Independent code verdict after remediation: no remaining P0/P1/P2. The offline
evidence cannot rank live performance, so the safe compatibility default is
preserved.

The documentary pass corrected the distinction between 16 exact selectors and
their 26 expanded pytest cases, removed an obsolete release-pending note, and
kept Task20/Task00 open until the final gate. Final release: **3176 passed,
5 skipped in 333.76 s**, all checks green. Final verdict: **ACCEPT**.
