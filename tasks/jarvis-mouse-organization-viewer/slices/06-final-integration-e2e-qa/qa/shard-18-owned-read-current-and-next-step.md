# Shard 18 owned-read: current isolated pass and bounded next-step proposal

Following the baseline pass, PM authorized exactly one current execution.
`git diff --name-only 97d56f11 HEAD -- jarvis` returned no differences in
`mov5`: its product is identical to frozen root despite later QA/test commits.

## Actual current result

The exact `[owned_read]` parameter **passed in 2.67 seconds**, exit 0, with
pytest assertion rewriting enabled to retain small health/task diagnostics
if it failed. Main venv interpreter, cwd `C:/Projects/jarvis/mov5`,
`PYTHONDONTWRITEBYTECODE=1`:

```powershell
python -m pytest --tb=short -p no:cacheprovider -q `
  'tests/unit/test_back_brain_tasks.py::test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]' `
  --junitxml=tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/current-shard-18-owned-read.xml
```

Retained [console](current-shard-18-owned-read.log) and
[JUnit](current-shard-18-owned-read.xml). The earlier exact baseline run
passed in 16.34 seconds. These are whole pytest durations, not measured
internal stop/recovery timings; their difference does not identify a cause.
The original broad-run failure remains blocking/unclassified. An isolated
pass does not replace its raw red trace or prove order independence.

## Reachable control flow, beyond file equality

1. The test starts a real temporary Core/SQLite, admits synthetic canonical
   voice records in process, then submits through `BackBrainTaskService`.
   Its `_submit` calls `jobs.owned.accept(job, source.turn_id)`; the owner
   transaction schedules `_execute` and publishes the accepted event.
2. `_execute` first calls `_read_owned`. The injected outage raises only
   when `get_job` is called from a `jarvis-job-*` task. `_read_owned`
   retains ownership/persistence evidence and retries with a 50 ms sleep,
   before starting a worker. The final worker-call assertion passed: the
   controlled worker was never executed in this isolated scenario.
3. `Core.stop` first stops its other services, then `BackBrainTaskService.stop`
   checks owned submissions, and `JobService.stop` awaits `OwnedJobExecution.stop`.
   The owner maintains one shielded stop reconciliation task. Its bounded
   wait uses `min(.5, cleanup_timeout_s + .25)` (here `.3` seconds); an
   unfinished reconciliation returns false. Core then reports persistence/
   cleanup uncertainty instead of closing authoritative storage.
4. In both successful and early-return paths, Core's `finally` calls
   `_stop_scene`: playback/presenter, file watcher, projector and scene close.
   After the test clears its injected outage, the second stop retries the
   same owned reconciliation; if it completes, `JobService.stop` cancels/
   gathers/clears remaining tasks and Core closes storage, sets health
   `stopped`. Those stop/retry/storage functions are unchanged from baseline.

MOV product changes are limited to `scene.py`, `scene_batch.py` and UI/host
modules. The **modified scene domain module is loaded** by this Core
composition: its additional enum/argument definitions are not bypassed at
import time. Scene startup/restart reconciliation and runtime projection
also remain in the lifecycle, so claiming the entire scene subsystem is
absent from this test would be false.

The test does not create a Control Center/browser, submit a scene layout
command, resize or organize objects. Its job events are not layout commands;
the projector consumes `CORE_WORK_UPDATED`, while the owned executor's first
read precedes its running-work observation. Any runtime scene projection
uses existing runtime upsert/patch/link/signal operations. Those can reach
shared `SceneCommand` validation, where MOV added a default-None `targets`
argument/guard, but cannot select the new layout branch without that op.
The actual layout target comparison/atomic planner in `scene_batch.py`
requires an explicit selection operation; no source path in this scenario
requests it. UI JS and the new host injection/content paths are not executed.

This is a source/control-flow analysis, **not an instrumented executed-line
trace**. It distinguishes loaded shared domain changes from the new layout
operation without claiming measured coverage, internal state values or a
definitive scheduling cause. Inspected Core, owner, JobService, BackBrain,
admission/ledger, projector/service and SQLite files are unchanged.

## Proposed bounded order/timing comparison — not executed

Root shard log lines 106–107 show the immediate predecessor was
`test_work_projection_failure_never_orphans_authoritative_job[True]`, then
the failing `[owned_read]` case. A next bounded allocation could run exactly
that ordered pair once at baseline and once at current, sequentially:
four test executions total, with assertion rewriting, `--durations=2` and
retained JUnit/logs. Stop after those two runs regardless of outcome; no
full file or automatic repeat-until-green.

This pair checks one concrete order hypothesis while keeping the same
temporary-DB/controlled-worker resource boundary. If both pairs pass, report
that limited result and request a separate decision on instrumentation or a
larger captured prefix; do not infer the broad failure is resolved. If it
fails, preserve actual rewritten health/task values before proposing a fix.
No artificial system load or modification of cleanup deadlines is proposed.

No further runtime, broad repetition, product mutation or registry ignore
was performed after this one current pass. PM was informed immediately.
