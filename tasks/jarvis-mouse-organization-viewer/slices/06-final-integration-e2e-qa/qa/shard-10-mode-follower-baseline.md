# Shard 10: two mode-follower startup timeouts

## Actual comparison

Root `97d56f1144cb721e7c5303f43ff71d291ed1d9bc` completed shard 10 with
952 passed, 3 failed and 5 skipped in 873.72 seconds. The settings-destination
failure was already listed by the gate; this investigation covers only the
two newly observed mode-follower failures.

The two exact cases also fail at detached baseline
`c0858a8000e2ca23b57231edb8f46c643080ad07`: **2 failed in 21.07 seconds**.
The retained JUnit reports two tests, two failures, no errors or skips. Its
suite duration is 16.806 seconds; the console's pytest duration is recorded
above without substituting one measurement for the other.

| Case in `tests/unit/test_interaction_mode_follower.py` | Root and baseline failure |
| --- | --- |
| `test_mode_change_while_voice_is_idle_reaches_the_coordinator` | line 227 waits for `core.listening == 1`, then `until` line 185 raises `AssertionError: condition jamais atteinte` |
| `test_legacy_architecture_refuses_presentation_visibly_once` | line 324 waits for `core.listening == 1 and core.snapshot_reads == 1`, then the same line 185 timeout |

Both failures occur before the test publishes the presentation-mode event.
They do not establish that the presentation delivery or legacy refusal itself
is incorrect. Actual listener and snapshot counter values were not captured;
no particular count or internal cause is inferred from these timeout traces.

## Bounded reproduction

Working directory: `C:/Projects/jarvis/movb`. Interpreter:
`C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe`.
Only these two exact tests were executed, with `PYTHONDONTWRITEBYTECODE=1`:

```powershell
python -m pytest --assert=plain --tb=short -p no:cacheprovider -q `
  tests/unit/test_interaction_mode_follower.py::test_mode_change_while_voice_is_idle_reaches_the_coordinator `
  tests/unit/test_interaction_mode_follower.py::test_legacy_architecture_refuses_presentation_visibly_once `
  --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/baseline-shard-10-mode-follower.xml
```

Evidence: [console log](baseline-shard-10-mode-follower.log),
[JUnit](baseline-shard-10-mode-follower.xml). Original root trace:
`C:/Projects/jarvis/mov/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/evidence/shard-10.log`.

The cases use the module's in-memory `FakeCore`, `IdleWake`, coordinator,
signals and journal doubles. The realtime factory raises if entered; the
legacy presentation builder likewise raises before any session or microphone
hub can be constructed. The wake source waits on an unset asyncio event.
Each case's `finally` requests runtime exit and awaits its owned task. No
browser, provider/model request, audio hardware, real HTTP server or broader
test file was used.

## Source identity and recommendation

`git diff --name-only c0858a80 97d56f11 --` returned no differences for the
selected test module and the inspected dependencies `voice_v2.py`,
`interaction_mode_observer.py`, `completion_watch.py` and
`presentation_runtime.py`.

Recommendation: classify these two observed failures as proven pre-existing
and unrelated to this task, based on the matching actual baseline failures
and unchanged relevant source. PM owns the classification decision. The
canonical gate remains truthfully red; no ignore, product change, additional
instrumentation or repeat run was introduced.
