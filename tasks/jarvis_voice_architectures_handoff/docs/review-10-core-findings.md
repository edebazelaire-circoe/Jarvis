# Independent Task10 Core admission review

Scope: canonical admission, ledger checkpoint, shared `BrainOrchestrator.submit`
persistence, SQLite dispatch reservation, crash/cancellation recovery and
diagnostic privacy. Production files were not changed by this review.

## Final status

**Accepted with no open Core finding.** All four independently reproduced
findings are resolved and their permanent reviewer regressions pass.

- **F1 resolved:** a first late admission of canonical A after B no longer
  replaces B. Server-owned canonical predecessor/order evidence gates direct
  activation, later backend submission and uncertain-result promotion.
- **F2 resolved:** retry republishes `brain.source.changed` when its source is
  still current. Retry of A after B became current cannot publish stale A.
- **F3 resolved:** dispatch claim reconstructs and validates the complete typed
  binding, deterministic identities, USER metadata, owned source, server order
  proof and checkpointed canonical evidence. Generic/assistant/legacy and
  malformed records cannot claim the operational marker.
- **F4 resolved:** each admitted USER retains its bounded server-generated
  `voice_admission_order`. SQLite follows durable predecessor proofs
  iteratively, without an arbitrary depth cutoff, when the bounded ledger has
  evicted an ancestor. A valid linear chain advances; missing, cyclic, corrupt
  or sibling/fork evidence fails closed.

The F4 reviewer scenario now advances an addressed source after 132 intervening
uncertain admissions. Owner coverage extends the linear path to 400 admissions
across restart and exercises direct activation, backend submit and uncertain
promotion. It also covers reversed observation arrival, evicted fork parents,
missing/cyclic ancestors, corrupt current proofs and a lower-epoch attempt.

## Passing adversarial coverage

The 15 reviewer scenarios cover:

- late A after B and publication-failure retry;
- forged dispatch metadata, assistant rows and actual compatibility turns;
- checkpoint, turn, conversation timestamp, JSONL archive, source allocation
  and activation failures with retry/restart convergence;
- cancellation before activation and cancellation while waiting for the SQLite
  claim lock;
- two independent SQLite connections converging on one dispatch claim;
- uncertain submit without confirming response, stopping, and canonical-order
  eviction beyond the in-memory retention window.

The reviewed diagnostic omits transcript text, and
`VoiceTurnAdmissionRequest.__repr__` excludes it. Admission alone produced no
backend call, job, speech request, assistant history or COMPLETE evidence.

## Exact verification

From `C:\Projects\jarvis\jarvis`:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_voice_admission_review.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Reviewer gate: **15 passed in 7.43 s**.

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_voice_turn_admission.py tests\unit\test_voice_admission_protocol.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Owner admission/protocol gate: **72 passed in 25.55 s**. This includes the
400-turn restart progression, direct/submit/promotion variants, forks with
evicted parents, missing/cyclic evidence and server-order corruption matrix.

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_voice_ledger_protocol.py tests\unit\test_core_brain_outcomes.py tests\unit\test_brain_outcome_review_races.py tests\unit\test_brain_delegation.py tests\unit\test_v2_brain_orchestrator.py tests\unit\test_v2_brain_migration.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Targeted Core regression gate: **135 passed in 11.92 s**.
