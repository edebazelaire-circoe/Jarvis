# Task11 Core implementation evidence

Implementation delivered for parent review; this note does not accept the slice. Runtime/controller evidence is in [11-runtime-implementation-evidence.md](11-runtime-implementation-evidence.md). No provider inference or agent CLI job was launched by these Core tests.

## Authority and durable acceptance

`BackBrainTaskService` extends the existing `JobService` with `kind=back_brain`; there is no second executable task system. `BackBrainSubmitRequest` accepts only a Core10 `source_correlation_id` for `admitted_work`. Core derives the exact addressed USER request, session/item/transcript binding, source and context. It verifies the durable canonical checkpoint, exact snapshot revision and canonical order, and requires the submitted source to remain current inside the acceptance transaction. An old job may finish after a newer intention; an old intention cannot first launch as current.

`SQLiteStateRepository.accept_admitted_job` uses `BEGIN IMMEDIATE` to validate provenance, claim the existing USER dispatch flag and insert the Job atomically. A source-derived opaque Job ID is also its idempotency key. Identical retries return the same Job; immutable conflicts fail. Two initialized connections racing from no Job/flag produce one creation and one duplicate. Capacity is sixteen active Jobs; refusal leaves the dispatch flag untouched. The legacy BrainOrchestrator uses that same dispatch claim, preventing a second backend for this admission.

Acceptance and scheduling form a shielded Core-owned continuation. Caller cancellation after SQLite COMMIT cannot abandon PENDING. Only the transaction winner schedules execution. The worker semaphore permits one execution at a time; this does not promise filesystem write isolation between independently configured tools. Production registration and controller caller belong to the runtime implementation linked above.

## Exact provenance and freshness

An admitted Job persists `BackBrainWorkPayload`: exact request text, exact bounded context text and `BackBrainProvenance`. Context contains at most sixteen eligible immutable Core turns within 8192 characters, retaining whole messages. Eligible USER turns have complete Core10 admission/order evidence; eligible ASSISTANT turns have exact confirmed-heard span evidence. The current request is separate, not repeated in context. `context_dependencies` stores each projected turn ID, kind and SHA-256 of exact UTF-8 text. SQLite rechecks those dependencies and the exact rendered context in the acceptance transaction.

Status computes `source_current` and `dependencies_current` separately from the global snapshot revision. `fresh` requires both. Unrelated transcript updates do not stale immutable context; missing dependencies yield unknown, changed dependencies yield false. A job never rewrites its origin when the current source changes. Results enter durable Job state, never a speech request or fabricated assistant history.

`speculative_analysis` returns `unavailable/restricted_execution_unavailable` before spawn under Decision22. It creates no Job, USER turn or commit. The separate typed immutable `BackBrainAdvisoryReference` records server-derived session/delegation reference and up to eight exact input dependencies: transcript ID, revision, provider item, committed flag and text. Each text is at most 8192 characters; the complete serialized projection is at most 16 KiB. Retention keeps 128 references per conversation, reads at most 32. Revision corrections do not rewrite the source reference. List freshness compares exact dependencies; its canonical ledger checkpoint preserves the observed correction across restart. A missing dependency is unknown, never silently current.

## Lifecycle, cancellation and recovery

Start, progress, result, error and cancellation persist before publication. `OwnedJobExecution` retains ownership across transient SQLite reads and transitions, including the post-cleanup terminal write. The exact pending result remains held without re-executing work. Permanent storage failure exposes `state_persistence_unavailable`; retries are coalesced diagnostically and continue under Core ownership. Stop is bounded by the cleanup budget, keeps pending submission/execution/stop continuations and storage open, and reports `state_persistence_unknown` or `cleanup_unknown` until a later retry resolves them.

Cancellation first fences admission to execution and persists `cancel_requested`. Public cancel does not cancel the execution coroutine across a native COMMIT. Worker `cancel_owned` performs actual cancellation; `cleanup_owned` checks natural completion without changing intent. An incomplete cleanup keeps the slot and owner. Natural cleanup is polled and preserves the original successful/failed result when no cancellation was requested. Only confirmed cleanup permits a terminal cancelled state. Concurrent cancel/natural completion has one durable terminal and one terminal publication in the controlled race tests.

Restart marks durable PENDING/RUNNING jobs INTERRUPTED, never replays them. Completed results and advisory origins rehydrate through the same conversation endpoints after frontend replacement or Core restart. This is not exactly-once execution across a host crash: the conservative interrupted state requires explicit follow-up, and remote side effects are not rolled back.

WorkState and event publication are projections of the authoritative Job. Their failure is diagnosed and cannot remove an active owner, fail a successful backend, or replace a result. There is no event outbox guarantee: clients recover from bounded Job status/list. Normal diagnostics use the repository's `DiagnosticSink` (`core.job.*`) and runtime journal, not a fictitious LogBroker CLI. They carry IDs, revisions, states and stable error codes, excluding request/result text. Persistence retries emit one diagnostic per outage; no temporary probes remain.

## Transport and files

Authenticated loopback routes are POST/GET `/v1/conversations/{id}/back-brain/tasks`, GET `/{job_id}` and POST `/{job_id}/cancel`. Schema version is exactly integer 1. Strict codecs reject unknown/duplicate keys, nonfinite values, boolean versions, invalid Unicode, oversized IDs/text/body, cross-conversation Jobs and unknown query fields. HTTP bodies are bounded to 16 KiB; list limit is 1..32 and the repository query filters conversation/kind before LIMIT. Typed status/list distinguish dependency freshness, cancellation uncertainty and persistence uncertainty.

Core/domain files: `jarvis/domain/back_brain.py`, Job additions in `domain/v2.py`, `core/back_brain.py`, `core/owned_job_execution.py`, `core/voice_ledger.py`, `core/v2_services.py`, `core/v2_app.py`, `ports/v2.py`, `adapters/sqlite_state.py`, `protocol/server.py` and `protocol/client.py`. Permanent owned tests: `tests/unit/test_back_brain_tasks.py` and `tests/unit/test_back_brain_protocol.py`.

## Verification

- Owned task tests: **34 passed in 5.62 s**, including caller cancellation after acceptance/start COMMIT, initial/post-cleanup read outages, transition outages, bounded Stop during submission/list/read/transition failure, cleanup recovery, cancel races and running/terminal projection failure. Stop callers wait at most 0.5 seconds on the owned stop continuation; the continuation keeps reconciling after timeout and subsequent callers join it.
- Core10 regression: **271 passed in 49.02 s**. Exact command follows; this gate includes canonical order beyond the bounded snapshot, restart and admission/retention protocols.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_voice_admission_review.py tests/unit/test_voice_turn_admission.py tests/unit/test_voice_admission_protocol.py tests/unit/test_voice_ledger_protocol.py tests/unit/test_brain_outcome_protocol.py tests/integration/test_voice_outcome_retention.py tests/unit/test_v2_brain_orchestrator.py tests/unit/test_v2_brain_migration.py tests/unit/test_core_brain_outcomes.py tests/unit/test_brain_outcome_review_races.py tests/unit/test_brain_work_context.py tests/integration/test_v2_brain_protocol.py tests/integration/test_brain_work_context_protocol.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Final expanded Task11/runtime/controller/legacy Job and WorkState gate: **312 passed in 17.37 s**, warnings as errors:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_back_brain_tasks.py tests/unit/test_back_brain_protocol.py tests/unit/test_back_brain_worker.py tests/unit/test_back_brain_delegation.py tests/unit/test_owned_process_tree.py tests/integration/test_back_brain_voice_composition.py tests/integration/test_v2_jobs.py tests/integration/test_v2_core_recovery.py tests/unit/test_v2_work_progress.py tests/unit/test_work_state_store.py tests/unit/test_work_state_contracts.py tests/integration/test_work_state_protocol.py tests/unit/test_brain_work_context.py tests/integration/test_brain_work_context_protocol.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Independent reviewer recheck: **178 passed in 24.89 s** across twelve modules; the isolated Stop recovery node passed in 0.90 s. Three independent initial-read/post-cleanup-read/running-projection reproductions now complete with the exact result, one worker invocation, no remaining owner and a duplicate retry. Scoped `git diff --check` and compilation pass. Parent owns full release acceptance.
