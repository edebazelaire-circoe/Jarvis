# Architecture tests: bounded readiness conformance correction

PM explicitly approved this test-only correction after reviewing the source
audit and actual isolated baseline/current passes. This is **not** proof that
the original broad-run failures were pre-existing or caused by one particular
timeout. Original raw red shard evidence remains unchanged.

Only the two affected plans in
`test_architecture_agents_settings_browser.py` use the new readiness sequence.
Their local `settleMs:1` replaces reliance on the shared driver's arbitrary
1100 ms initial sleep. Their initial wait now requires document complete,
the canonical registered Settings/personalization globals and the opener DOM.
It keeps the existing standard **5000 ms** wait deadline. Global `OPEN` and
every other case/driver/fixture remain unchanged.

The first case's existing TOUR now awaits current Runtime & CLI section,
`SET.clis`, and the actual command/permission inputs before sampling. It
does not fake those fields, change Settings state, trigger another detection
request or retry an action. The prior 400 ms was an unconditional sleep, not
a product readiness SLO. PM authorized replacing it with the **existing
standard 5000 ms** bounded wait. That explicitly changes this phase's
observation window; no Core/browser/architecture deadline or process timeout
was enlarged. Other TOUR pauses are unchanged.

On deadline expiry, the loop stops and the original assertions inspect the
actual state and fail normally if controls remain absent. Every original
assertion predicate is preserved; the compound Runtime & CLI assertion now
also includes `rt` as its failure diagnostic. No ignore, fallback success,
larger global timeout or retry-until-green was introduced.

Justification is the unchanged canonical UI path: Runtime & CLI mounts its
loading view first, starts asynchronous CLI detection and fills inputs only
after a current-generation response. The contract permits that pending
state. Sampling an arbitrary fixed delay is not a readiness observation.
Similarly, an HTML opener may exist before the complete served-page script
and bindings are ready. The repair checks those required conditions instead
of assigning a speculative cause to the original failures.

Static checks, without pytest/Chrome/model/hardware:

- Python compile passed.
- AST comparison proves exactly the two intended test functions changed,
  all their assertion predicates remain identical, and `OPEN` is unchanged.
- Exactly two local plans use `settleMs:1`.
- Node `--check` passed on the assembled TOUR expression (parse only).
- `git diff --check` passed.

Evidence: [static validation log](architecture-readiness-static.log).
Independent S1 execution of these two affected cases remains queued behind
the higher-priority dense-graph diagnostic, followed by PM's affected
canonical gate. No runtime pass is claimed for this correction yet. No
product source or shared browser harness was changed, and the dense-graph
blocker is unaffected.
