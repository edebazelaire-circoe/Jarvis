# Task10 parent review

Accepted on 2026-09-12 after implementation review, three independent QA
passes, parent regression gates and the full release verification.

## Reviewed behavior

Explicit Simple and Front Brain are real direct conversational compositions.
Both retain the canonical Realtime reader, local admission, source freshness,
first-write admission and checked device-drain evidence. Front Brain adds the
bounded Luna sidecar in parallel; a slow, failed or unavailable analysis never
delays the direct response. Hints remain diagnostic advisory values and cannot
speak, submit work or change addressing.

Confirmed history is sent as bounded role-preserving conversation items and is
referenced with the exact current admitted provider item. It is not copied into
session instructions, and rejected ambient input is excluded. Compatibility
`legacy` and `continuous_brain` metadata and behavior remain distinct. Duplex
is refused before credentials or provider construction until Task12.

Core admission checkpoints the server-owned canonical record before persisting
the USER/source pair. HTTP arrival order cannot replace provider turn order.
The durable order proof survives bounded snapshot eviction and restart; a
400-turn linear conversation progresses, while forks, cycles, missing evidence
and forged metadata fail closed. Admission, later backend submit and uncertain
promotion all use the same transactional activation rule.

## Findings repaired

- Luna initially accepted remote plaintext base URLs and an outer JSON exponent
  overflow. HTTPS/exact-loopback validation and finite parsing now reject both.
- Sidecar construction, final-source admission and cancellation-resistant stale
  results were tightened with permanent tests.
- Direct composition races around a future Core source, scheduler wakeups,
  missing item IDs and late provider output were reproduced and repaired.
- Core QA found late canonical rollback, lost source-event replay and forgeable
  dispatch metadata. A later eviction test found that the first fix could freeze
  after the current order left the 128-entry snapshot. Fixed-size server order
  evidence plus durable iterative ancestry now resolves all four findings.
- App review found an internal configuration exception escaping for an unknown
  legacy setting. The user-facing mapping was restored while versioned Duplex
  keeps its precise unsupported error.
- The first release run exposed a stale AST assertion that confused backend mode
  with manual capture/VAD behavior. Production was correct; static and behavior
  tests now verify those independent choices.

Detailed evidence: `review-10-luna-findings.md`,
`review-10-composition-findings.md`, `review-10-core-findings.md`,
`10-implementation-evidence.md`, `10-core-admission-evidence.md` and
`10-surface-policy-regression-review.md`. No finding remains open.

## Parent gates

- Direct composition and adjacent runtime: **428 passed in 9.98 s**.
- Independent Luna/sidecar review: **58 passed in 0.80 s**.
- Independent final composition/config review: **88 passed in 5.96 s**.
- Independent Core review: **15 passed**; owner expanded Core gate:
  **271 passed in 44.66 s**.
- Global whitespace check: passed.

Final release command:

```powershell
$env:PYTHONWARNINGS='error'
$env:PYTEST_ADDOPTS='-o asyncio_default_fixture_loop_scope=function'
$env:PYTHONUNBUFFERED='1'
.venv/Scripts/python.exe scripts/verify_release.py
```

Result: **2595 passed, 4 skipped in 294.40 s; release verification passed**.
The skips are the two opt-in live-provider tests, POSIX-only signal coverage and
the unavailable Windows symlink case. No live model call, microphone benchmark,
monetary guarantee or hardware acoustic claim was made. Task11 owns durable
independent backend jobs; Task12 owns GPT-Live Duplex.
