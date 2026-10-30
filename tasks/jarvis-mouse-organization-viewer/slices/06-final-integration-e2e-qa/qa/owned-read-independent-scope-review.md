# Independent owned-read shutdown scope audit

Source-only review of the shard18
`test_back_brain_tasks.py::test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]`
failure, comparing canonical baseline `c0858a80` to frozen product `97d56f11`.
Reviewed S2 note at `71ce72f9`, exact test/fixture, Core/Job/OwnedJob/BackBrain
stop/read flow and all MOV Python product deltas. No test, browser, model,
instrumentation or product edit executed by this reviewer.

## Changed Python reachability

Only three production Python files differ: `domain/scene.py`,
`domain/scene_batch.py` and `runtime/control_center.py`. Verified the test,
Core lifecycle/services/projector, BackBrain/OwnedJob executor, SQLite state
and scene adapters have no baseline→current diff. File equality is useful
scope evidence, not proof that changed scene domain code is unexecuted.

Core imports the changed scene domain and runs scene startup/projection/stop.
Existing runtime upsert/patch/link/signal commands can reach shared
SceneCommand validation/serialization and apply_scene_command's selection
dispatch. For these operations the added targets field defaults to None:
argument enumeration includes one extra None-filtered field, the optional
batch-import guard remains false when all selection fields are absent, and
the LAYOUT_SELECTION-only validation remains guarded. Serialized commands
still omit targets. Runtime allowed operations are unchanged and exclude the
new layout op; adding it to SELECTION_OPS cannot turn an existing runtime
upsert/patch into a selection command.

The new scene_batch target compare/planner requires an explicit layout op,
explicit IDs and target records. The test submits an owned BackBrain job,
not a scene layout command. Its injected initial owned read loops before
the executor's RUNNING observation/worker invocation. Startup or independent
runtime projection may still execute shared scene checks; this is not an
instrumented line-coverage claim. No changed Python code introduces an await,
timer, SQLite operation, health write or owner-task cleanup in this path.
ControlCenter's changed HTML injection path is not constructed by this fixture.

No concrete MOV semantic change was found that changes health/shutdown or
jobs._running behavior in this scenario. Added synchronous definitions/checks
can coexist with scheduling variation; static analysis does not rule out an
order/load-sensitive failure or identify its cause.

## Specific unchanged timing mechanism worth distinguishing

The test sets cleanup_timeout_s=.05, releases its outage, then wraps the
second Core.stop in wait_for(...,1). OwnedJobExecution.stop has its own
min(.5, cleanup_timeout_s+.25)=.30-second bounded wait and can return False
earlier than that outer one-second deadline. Core then returns with persistence
or cleanup unknown, retaining ownership, rather than raising TimeoutError or
setting stopped. Pending owned reads/cancellation must still finish queued
SQLite operations and the existing50ms retry. The cancellation task name
`jarvis-job-cancel-*` also matches the test's injected outage prefix.

Therefore a loaded second stop can plausibly fail the final stopped/not-running
assertion even when the outer call returned within1s. This is a **possible
source-supported mechanism**, not observed timing from the failed run. Exact
health.status/detail, owned._stop_task state, persistence_failures and owned
running/cancellation-task state at failure would distinguish it. No generic
hardening, deadline increase or sleep-until-green is recommended here.

## Classification recommendation

Retain the original red gate trace as an **unresolved intermittent failure**.
Baseline's isolated16.34s pass and current's isolated2.67s pass are whole-pytest
durations; they do not prove a pre-existing failure, internal stop timing or
resolution. S2's bounded predecessor→case baseline/current comparison can
test that specific order hypothesis. If it does not reproduce, report that
limited result without inventing coverage or calling the original red a pass.
If it fails, preserve actual assertion values/owner state before choosing a
scoped correction. PM owns the final evidence-based disposition; this review
establishes no MOV-caused shutdown defect and does not certify baseline flakiness.
