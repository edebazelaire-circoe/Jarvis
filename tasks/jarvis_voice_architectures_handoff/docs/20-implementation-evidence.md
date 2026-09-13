# Task20 implementation evidence

Accepted 2026-09-13.

Task20 adds a strict versioned common-suite codec and CLI. The suite freezes 14
ordered scenarios, three explicit configurations, exact prompt/config/component
fingerprints, representative E2E nodes and migration evidence. All evidence
roles and scenario parameters are bound by immutable code contracts; globally
valid tests cannot be reassigned to another architecture, scenario or migration
claim.

The runner invokes pytest itself. A nonzero gate or incomplete evidence writes
no benchmark report. Successful runs write atomic JSON/text cross-architecture
reports and three Task18-shaped session reports. Shared policy evidence remains
distinct from per-mode success; unavailable live metrics remain null.

The migration audit found that compatibility sessions were labelled `simple`
in metrics and switch provenance. Production startup now derives one
operational architecture: `legacy` or `continuous_brain` for compatibility,
and `simple`, `front_brain` or `duplex` for explicit modes. Invalid explicit
configuration also marks a pending restart failed and raises an actionable
startup error.

Validation before the final release gate:

- real benchmark CLI: **26 passed**;
- runner adversarial gate: **24 passed**;
- expanded Task20 gate: **144 passed** with warnings as errors;
- independent app/benchmark/config review gate: **99 passed**;
- orchestrator expanded Task20 gate: **174 passed** with warnings as errors;
- final release: **3176 passed, 5 skipped in 333.76 s**; all release checks
  passed;
- `git diff --check`: passed.

No provider, billable session, external network, microphone or speaker was
used. No new default was selected from offline evidence.
