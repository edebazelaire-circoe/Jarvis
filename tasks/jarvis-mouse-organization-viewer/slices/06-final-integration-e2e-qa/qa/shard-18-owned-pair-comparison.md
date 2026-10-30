# Owned-read immediate-predecessor comparison: four authorized executions

PM authorized one exact ordered pair at baseline, then the same pair once
at current, sequentially. All four cases passed; execution stopped after
that allocation, with no retries or broader file run.

| Revision | Actual pytest result | owned-read call duration | JUnit case duration, including setup/teardown |
| --- | --- | --- | --- |
| Baseline `c0858a8000e2ca23b57231edb8f46c643080ad07` (`movb`) | 2 passed in 4.27 s | 0.42 s | predecessor 0.390 s; owned-read 0.616 s |
| Current product identical to `97d56f1144cb721e7c5303f43ff71d291ed1d9bc` (`mov5`) | 2 passed in 2.92 s | 0.42 s | predecessor 0.227 s; owned-read 0.610 s |

JUnit confirms two tests, zero failures/errors/skips for each run. Its suite
durations are 4.146 s and 2.652 s respectively; these and whole pytest/call
durations are different measurements, not internal stop-phase timings.

Evidence: [baseline log](baseline-shard-18-owned-pair.log),
[baseline JUnit](baseline-shard-18-owned-pair.xml),
[current log](current-shard-18-owned-pair.log),
[current JUnit](current-shard-18-owned-pair.xml).

Both runs used the main venv interpreter, `PYTHONDONTWRITEBYTECODE=1`, assertion
rewriting and exactly these arguments (output path differs by run):

```powershell
python -m pytest --tb=short --durations=2 -p no:cacheprovider -q `
  'tests/unit/test_back_brain_tasks.py::test_work_projection_failure_never_orphans_authoritative_job[True]' `
  'tests/unit/test_back_brain_tasks.py::test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]' `
  --junitxml=<retained-run-specific-path>
```

The predecessor was checked before execution: it uses the same temporary
Core/SQLite fixture and Event-controlled `ControlledWorker`. It injects one
controlled terminal work-projection failure, releases the deterministic
worker, and verifies durable completion, exact result, one worker call and
no remaining owned task. No provider, physical adapter, browser or external
server is needed. Each case owns a separate temporary Core/data root, while
the two cases share one pytest process in the recorded order.

The source/control-flow distinction remains as documented in
[current analysis](shard-18-owned-read-current-and-next-step.md): unchanged
BackBrain/owner/JobService/storage stop machinery, shared scene domain loaded
as part of Core lifecycle, no user selection/layout command into the new
atomic planner. The predecessor does exercise running work projection; it
does not request `layout_selection`. Runtime projector scheduling/precise
executed-line coverage was not instrumented in these runs.

This concrete immediate-predecessor order did not reproduce the canonical
shard failure. It does not reproduce the longer shard prefix or its timing,
and does not disprove a broader interaction. Keep the original line-669
failure **unclassified**, with raw red evidence intact; no baseline/pre-existing
label, resolved claim or known-failure ignore follows from these passes.
Any further captured-prefix or diagnostic allocation requires a separate PM
decision. No product edit, repeated-until-green loop or artificial load was
introduced.
