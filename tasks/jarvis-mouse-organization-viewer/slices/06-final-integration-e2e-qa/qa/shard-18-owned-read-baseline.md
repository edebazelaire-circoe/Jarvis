# Shard 18: owned-read baseline passes; current failure remains unclassified

Frozen root `97d56f1144cb721e7c5303f43ff71d291ed1d9bc` completed shard 18
with **1504 passed, 3 failed, 3 skipped** in the original pytest run. The
gate JSON reports no session problems and 1050.4 seconds including its retry.
The registered intermittent memory-context case initially failed waiting
for readiness, then the canonical runner retried it alone: **1 passed in
33.33 seconds**. Preserve that tolerated result; it is not a third unknown.
Original raw evidence remains `qa/evidence/shard-18.log/.json` at root.

## Exact current failure

`test_back_brain_tasks.py::test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]`
fails at line 669 after the second `await core.stop()`:

```python
assert core.health.status == "stopped" and not core.jobs._running
```

The plain assertion trace does not record either actual operand. No health
value, task count, owner leak or scheduling cause is inferred here.

## Resource boundary and one authorized baseline run

The fixture constructs real `JarvisCoreApplication`/SQLite under `tmp_path`
with an injected `ControlledWorker` for `back_brain`. The worker is an asyncio
Event-controlled deterministic result/cancellation double. The admission
helper builds canonical in-process inputs; no external frontend, hardware,
browser, protocol server or live model is used. This is not an all-mock DB
test: temporary SQLite and real Core lifecycle execute. Fixture `finally`
releases its worker and stops only its own Core.

The selected test injects a controlled `OSError` into owned-task `get_job`
reads, sets `cleanup_timeout_s=.05`, checks bounded stop under that outage,
then clears the outage and requests another bounded stop. Its cleanup and
recovery are the behavior under investigation.

Ran **only this one exact parameter** in detached baseline
`C:/Projects/jarvis/movb` at
`c0858a8000e2ca23b57231edb8f46c643080ad07`, using the main venv Python and
`PYTHONDONTWRITEBYTECODE=1`:

```powershell
python -m pytest --assert=plain --tb=short -p no:cacheprovider -q `
  'tests/unit/test_back_brain_tasks.py::test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]' `
  --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/baseline-shard-18-owned-read.xml
```

Actual result: **1 passed in 16.34 seconds**, exit 0. Retained
[console](baseline-shard-18-owned-read.log) and
[JUnit](baseline-shard-18-owned-read.xml).

## Disposition remains open

The selected test/admission helper and inspected `v2_app.py`,
`v2_services.py`, `owned_job_execution.py`, `back_brain.py` and
`sqlite_state.py` are unchanged between baseline and frozen root. That source
identity does not override the observed baseline pass: **no pre-existing
classification is recommended from this run**. The current failure remains
blocking/unclassified pending PM's bounded follow-up allocation.

PM was informed immediately of the baseline pass before any broader runtime
work. No other parameter, full file, repeated baseline, current runtime,
instrumentation, product fix or ignore was executed/added. The independent
host Escape contract correction is recorded separately.
