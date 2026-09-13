# Task16 — GPT-Live global safety indicator evidence

Accepted 2026-09-13.

## Result

The Control Center now projects Core's durable GPT-Live lifecycle in a global,
high-contrast banner with an elapsed timer and immediate Stop action. STARTING,
ACTIVE, IDLE_CANDIDATE, STOPPING and UNKNOWN_REAP_REQUIRED are visible. A close
failure, stale Core read or unavailable Core never becomes an OFF rendering.
The banner is removed only after a successful Core read returns no unresolved
session.

Stop is an atomic, session-bound runtime-bus command. Voice consumes each ID at
most once and calls the existing idempotent user-mute path. Accepted and failed
command receipts remain distinct from Core terminal evidence. A stale request
cannot stop a replacement session. Unknown/reap and failed states expose retry.

Elapsed time uses Core timestamps and its durable counter floor. Matching Voice
telemetry adds the configured semantic-idle countdown and model identity. Core
provider usage is labelled separately. Monetary estimates appear only with a
complete, timezone-stamped, matching pricing document and include source and
basis metadata; there is no built-in price.

## Verification

- Task16 focused Python/browser/runtime gate: **180 passed**.
- Live and Control Center compatibility gate: **500 passed, 2442 deselected**.
- Final release: **3062 passed, 5 skipped in 329.16 s**; all release checks passed.
- Python compilation, Node syntax validation and `git diff --check` passed.

No provider, billable Live session or audio hardware was used. The tests prove
lifecycle projection, UI behavior and stop routing with deterministic fakes;
they do not prove provider-side closure outside Task13's receipt/reaper contract.
