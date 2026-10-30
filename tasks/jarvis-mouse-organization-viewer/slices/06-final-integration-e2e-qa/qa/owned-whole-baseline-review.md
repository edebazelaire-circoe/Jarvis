# One uninstrumented whole baseline BackBrain file — passed, no reproduction

PM allocated exactly one whole-file run after isolated baseline/current and
predecessor-pair runs passed, and the delay experiment remained inconclusive.
Executed once on clean baseline worktree `movb`, exact revision
`c0858a8000e2ca23b57231edb8f46c643080ad07`. No repeat/current whole-file run.

## Provider/scope audit before execution

`tests/unit/test_back_brain_tasks.py` explicitly constructs its owned Core
with ControlledWorker; its progress test substitutes a controlled subclass.
Voice admissions use FakeVoiceFrontend and canonical in-process ledger facts.
Core's omitted brain backend becomes NullBrainBackend; no Board CLI host is
attached. Notifications are null delivery and calendar is in-memory. The file
contains no provider/CLI/browser subprocess execution. Restart constructions
either use another ControlledWorker or no worker. This was a mocked-provider,
temporary Core/SQLite file, not a paid model or live-user-runtime test.

## Actual execution

Main venv Python, baseline cwd/imports, no bytecode writes/cache, no diagnostic
plugin, unchanged tests/deadlines. Assertion rewriting retained for precise
small health/task values if a failure recurred. Command/runner and exact
runner/child PIDs/timestamps are in `owned-whole-baseline-run.json`.

```text
python -m pytest --tb=short -p no:cacheprovider -q tests/unit/test_back_brain_tasks.py --durations=5 --junitxml=<QA>/owned-whole-baseline.xml
```

**34 passed in17.73seconds**, exit0. The disputed `[owned_read]` test's call
duration was0.48seconds; that is pytest call timing, not measured internal stop
phases. Log `owned-whole-baseline.log`, JUnit `owned-whole-baseline.xml`.
No failing status/owner diagnostics were produced because the exact original
assertions passed. Normal fixture cleanup completed and the child exited.

## Evidence-based classification recommendation

This entire-file prefix/order did not reproduce the initial broad current
failure. Together with earlier isolated/pair passes it remains evidence of
non-reproduction, **not** proof of a baseline failure or measured cause.
The previous source audit found no direct MOV semantic change to shutdown,
owner tasks, repository or health transitions. Modified scene definitions and
shared default-None checks are reachable; the new explicit layout planner is
not requested by this scenario. No uninstrumented executed-line/timing trace
from the original failed run exists, so do not overstate that distinction as
coverage proof.

Recommend describing the initial red as **unreproduced and source-unattributed
to MOV**, with the original unresolved evidence retained. It cannot honestly
be labeled a demonstrated pre-existing failure from these results. No unrelated
Core hardening, deadline inflation, registry ignore or additional random
repetition is justified by this allocation. PM owns the explicit final gate
disposition/risk decision; this review does not silently turn the original
full gate into all-pass or certify the remaining classification as resolved.
