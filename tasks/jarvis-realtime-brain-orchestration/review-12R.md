# Slice 12R — Repair validation fixture cleanup and timing

Date: 2026-09-12. Tests only; no production behavior, warning suppression or test
omission. The parent requested this correction after the full strict release gate.

## 12R1 — Six SQLite repositories left open by the work-context fixture

The initial release verifier reported 1890 passed, 4 skipped and 1 failed in
582.12 seconds. Garbage collection happened during a debug-console test, exposing
six unclosed SQLite connections allocated by earlier tests. The failing test name
was not the resource owner.

Source confirmed: `Stack` in `tests/unit/test_brain_work_context.py` retained neither
the repository created by `build_stack` nor any cleanup call for its brain.
Its `close()` stopped only the attention policy. Six tests construct that stack.

Reproduction before editing:

- Work-context file alone, strict warnings: **34 test assertions passed, process
  exit 1**, with six unclosed-database exceptions during final garbage collection.
- Work-context + brain delegation + debug console, with `-X tracemalloc=10` and
  strict warnings: **69 passed, 1 error**. The same six leaks surfaced during a
  later delegation fixture setup. This confirmed GC timing rather than a console
  behavior regression.

The fixture now retains its repository. Existing `finally: await stack.close()`
call sites stop policy, then stop the brain and close SQLite through nested
`finally` cleanup, even when earlier cleanup raises. No global monkeypatch or
garbage-collection workaround was introduced.

After correction, the same work-context + delegation + debug-console suite:
**70 passed in 7.27 seconds**, strict warnings, exit 0.

## 12R2 — Explicit short timeout in three deployment test fixtures

Two unit tests and one end-to-end test attempted to reduce the readiness timeout
by monkeypatching `READY_TIMEOUT_S` to 0.05. The actual `_await_health` default had
already captured 120 seconds at function definition, so each unhealthy-provider
scenario unnecessarily waited two minutes.

The three tests now bind the real coordinator method through `functools.partial`
with `timeout_s=0.05`. They retain the existing 0.01-second polling interval and
exercise real health polling, rollback, Git state and safety assertions. Production
timeout values and method implementations are untouched; no sleeps are mocked.

Validation:

- Two affected unit tests: **2 passed in 7.75 seconds**; call durations 2.55 and
  2.22 seconds, including their Git operations.
- Full deployment unit file: **20 passed in 48.31 seconds**.
- Full self-development end-to-end file: **9 passed in 34.27 seconds**; unhealthy
  deployment test call took 3.34 seconds.

All commands used `-W error -o asyncio_default_fixture_loop_scope=function`.

## Files and observability contract

- `tests/unit/test_brain_work_context.py`
- `tests/unit/test_deployment.py`
- `tests/integration/test_self_development_end_to_end.py`
- This report.

No application logging or channels changed. Expected validation evidence is clean
resource teardown with warning escalation enabled, plus unchanged deployment event
and rollback assertions. Existing RuntimeJournal-based scenario checks remain.
There are no temporary probes, warning filters, production changes or commits.

Parent reviewed and accepted all fixture changes. Independent full release
verification is being rerun by the parent; this report does not claim its outcome.
