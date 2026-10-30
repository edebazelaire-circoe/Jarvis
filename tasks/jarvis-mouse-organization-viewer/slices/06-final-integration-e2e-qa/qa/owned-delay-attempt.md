# Bounded healed-read diagnostic — inconclusive, no repeat

One actual baseline execution attempted; **current was not executed**. The
runner hit its45-second process deadline and stopped. No completed pytest
verdict or JUnit was produced. The exact owned pytest child was killed and
waited by subprocess.run's timeout handling; no process-name/tree cleanup,
browser, model, hardware or user data was involved. Root97d remained frozen.

The selected test file was unchanged: baseline/current SHA256 both
`a56e749a51e14d762bf6358c571b7bdd15bb070d08c43bcb8cfc356f5a7fe6cb`.
Baseline revision was `c0858a8000e2ca23b57231edb8f46c643080ad07`.
The command actually invoked from mov3 was:

```text
<main venv python> <S06>/qa/run_owned_read_delay.py
```

It spawned the exact original case under movb's cwd/imports with
`--assert=plain --tb=short -p no:cacheprovider -p owned_read_delay_plugin -q`
and an explicit QA JUnit destination. The ordinary product/test file and all
deadlines remained untouched. The QA plugin intercepted the existing
SQLiteStateRepository.get_job class seam, which the test's failing instance
wrapper captures. That wrapper raises during its outage before reaching the
hook. On the second Core.stop phase, the hook selected one healed
`jarvis-job-cancel-*` read for an async400ms delay; only this one delay was
selected. Core.stop wrappers recorded permitted health/task counts/timings.

## Actual phase evidence

The plugin wrote `owned-delay-baseline.json` before process timeout:

| Phase | Actual Core.stop duration | Health after | Stop task | Running | Worker calls |
|---|---|---|---|---|---|
| Initial outage stop |0.313104s|state_persistence_unknown|pending|1,not done|0|
| Healed stop |0.135030s|stopped|done|0|0|
| Original fixture's final stop |0.000012s|stopped|done|0|0|

The hook recorded injection_count1 and delay_start_phase2. Its completion or
finally duration was **not present before the fixture wrote JSON**. The plugin
cleanup snapshot confirms Core stopped with zero running jobs and worker
calls. Those recorded conditions satisfy the disputed final state, but there
is no completed pytest verdict, so this is not reported as a passed test.

The400ms async delay did **not** force the intended early-unknown final state.
Another owned path could finish the job while the delayed cancellation read
was pending; cancellation-task ownership/loop teardown is a possible reason
the diagnostic pytest process later did not exit, but no stack/timing trace
was captured to prove that exit cause. The parent process timed out after45s.
This is a diagnostic-interference limitation, not a demonstrated product
regression or the original broad-run cause.

## Runner limitation and disposition

The initial runner failed to catch TimeoutExpired, so its tool traceback was
the immediate timeout evidence and no aggregate comparison file was written.
After preserving the actual phase file, the QA runner was amended **without
rerunning** to record partial timeout output/stop before the other revision,
refuse overwriting existing evidence and require explicit opt-in for any
separately allocated future run. No current comparison or second baseline
execution was attempted. The retained plugin represents the actual hook used.

The evidence remains **inconclusive** for the proposed healed-read mechanism.
Do not classify the original gate failure as pre-existing merely because an
injected baseline experiment was attempted. Earlier isolated/pair passes and
unchanged shutdown source remain separate facts; no original failing health/
owner state or internal timing was measured. Recommendation: retain the
original unresolved disposition, stop this diagnostic allocation and let PM
decide a further bounded method if necessary. No deadline inflation, product
hardening, repeat-until-green or fabricated coverage claim.
