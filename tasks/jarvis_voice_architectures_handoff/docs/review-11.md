# Task11 parent review

Accepted on 2026-09-12 after implementation review, independent adversarial
replays, parent regression gates and the full release verification.

## Reviewed behavior

Task11 extends the existing Core `JobService` with durable, typed back-brain
submit/status/list/cancel operations. Acceptance binds a deterministic Job to an
already admitted, addressed Core source and atomically reserves that source for
one backend dispatch. It captures the exact request and eligible immutable
context dependencies. Retries return the same Job and never infer a new origin.

Each admitted job runs through an independent Claude or Codex wrapper using the
configured provider, model and permissions. It does not share the conversational
agent lock. Windows jobs are attached to a Job Object before resume and retain
their owner until native cleanup is confirmed. Progress, result, error and
cancellation are durable Core state. Frontend replacement and restart do not
cancel completed or running work; restart conservatively marks unfinished work
interrupted instead of replaying it.

Explicit Simple and Front Brain expose one no-argument `back_brain_delegate`
tool. Its controller binds the call to the admitted operation and rejects forged
arguments or mismatched session/response/input/source identity. Only confirmed
Core acceptance creates a fixed source/job-bound acknowledgement through the
existing scheduler. Device playback is still the sole proof that it was heard.
Job completion remains silent and cannot authorize speech or actions.

Restricted speculative execution remains unavailable because the selected CLI
profiles do not enforce a verified context-only capability boundary. Core keeps
a typed immutable advisory reference with exact transcript dependencies, without
creating a Job, USER commit or action authority.

## Findings repaired

- Cancellation of a submit caller after the acceptance COMMIT could leave a
  durable PENDING Job without an execution owner. Core now owns and coalesces
  the acceptance-to-scheduling continuation.
- One-shot RUNNING or terminal persistence failures could release ownership and
  lose a result. Reads and transitions now reconcile under the same owner, while
  permanent outages remain visible and keep shutdown retryable.
- Independent QA found three further exits outside that reconciliation: the
  initial Job read, the post-cleanup read and the RUNNING WorkState projection.
  Each reproduced an orphan. All are covered by permanent fault-injection tests.
- A shutdown race could require a third Stop after storage recovered. The bounded
  caller now joins one continuing stop reconciliation until it confirms closure.
- Slow native cleanup originally converted successful work into failure or
  cancellation. The runtime retains the exact result and polls cleanup without
  changing intent. RuntimeJournal failures are best effort and cannot change the
  business outcome.
- Early advisory provenance lacked exact source text, and admitted job context
  relied too heavily on a global snapshot revision. Typed exact dependencies and
  separate source/dependency freshness now survive correction and restart.
- The first implementation seam had no production delegation caller. The direct
  conversation tool, trusted lineage checks, scheduler ACK and silent result path
  now exercise the actual composition.

No finding remains open. Detailed contracts and limitations are in
`11-core-back-brain-evidence.md` and `11-runtime-implementation-evidence.md`.

## Parent gates

- Final focused Task11 gate: **105 passed in 9.72 s**.
- Independent adversarial review: **178 passed in 24.89 s**.
- Core owner regression: **271 passed in 49.02 s**.
- Expanded application/runtime gate: **277 passed in 25.07 s**; owner combined
  gate: **312 passed in 17.37 s**.
- Global whitespace check: passed.

Final release command:

```powershell
$env:PYTHONWARNINGS='error'
$env:PYTEST_ADDOPTS='-o asyncio_default_fixture_loop_scope=function'
$env:PYTHONUNBUFFERED='1'
.venv/Scripts/python.exe scripts/verify_release.py
```

Result: **2700 passed, 4 skipped in 320.97 s; release verification passed**.
The skips are two opt-in live-provider tests, one POSIX-only signal test and the
unavailable symlink case. Tests launched no provider inference or real agent CLI.
The Windows ownership test used only controlled Python parent/child processes.
No hardware acoustic, live-model adherence or exactly-once remote-side-effect
claim is made. Task12 owns the GPT-Live client-delegation adapter.
