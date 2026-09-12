# Slice 02R — Failed backend work settlement

Date: 2026-09-12. Scope: review correction to the existing Core brain implementation.

## Finding and change

A backend could emit ACCEPTED with a work id, then raise an unexpected exception.
Core reported the failed turn, but left that work permanently active. The same
defect affected a returned FAILED result and a mismatched result correlation.

Core now associates newly activated backend work with its conversation and owning
turn. A terminal turn failure removes only that turn's remaining owned work,
publishes the existing work failure/state events, and discards unfinished latency
measurements. Reporting progress on already-active work does not transfer ownership.
Completed, explicitly failed or cancelled work releases its ownership; turn teardown
also releases remaining ownership bookkeeping.

Actual JobService jobs are not cancelled. Explicit cancellation and clean shutdown
retain their existing behavior. No new speech, fallback, provider behavior, diagnostic
channel or persistence schema was added. Latency keys include the conversation so
failure cleanup cannot erase a homonymous work's measurements in another conversation.

## Files

- `jarvis/core/brain_service.py`
- `tests/unit/test_v2_brain_orchestrator.py`
- This report.

## Observability / test contract

Existing DiagnosticSink/RuntimeJournal integration follows Decision 27; no parallel
LogBroker subsystem was introduced.

- Correlation: accepted conversation id + owning turn correlation id + work id.
- Normal terminal work keeps its existing completion/cancellation events.
- Failure: one `brain.work.failed` per orphaned owned work, followed by its
  `brain.state.updated`; existing turn-level failure with null work id remains.
- Stable error classes exercised: `RuntimeError`, `backend_unavailable`, and
  `backend_correlation_mismatch`.
- Existing diagnostic evidence: `core.brain.turn_failed` or
  `core.brain.backend_contract_violation`; no speech is fabricated for an exception.
- Independent work, finished work, other conversations and actual jobs survive.
- Failed-work timers and ownership entries are removed; another conversation's
  completion still emits `core.brain.latency.work_completed`.
- No temporary probes were introduced. Event assertions and RecordingSink inspect
  emitted evidence directly. No hardware or live-provider run was required or claimed.

## Validation

1. Pre-change `test_v2_brain_orchestrator.py`: **21 passed**.
2. New regression before production fix: **3 failed**, one per failure variant;
   every failure showed `('independent', 'orphan')` instead of `('independent',)`.
3. After correction, orchestrator suite: **24 passed**.
4. Strict gate (`-W error`): orchestrator, intent revision, work progress, brain
   contracts, brain migration, brain protocol, Core recovery: **140 passed**.
5. Parent independent review/gate: orchestrator, latency telemetry, work progress,
   migration, brain protocol, architecture: **117 passed**, also `-W error`.

The regression additionally proves no WorkCanceller call, no spurious speech,
preservation of completed work and concurrent work, conversation isolation, matching
failure correlations, public state repair and cleanup of failed-work measurements.

## Remaining scope and next slice

This correction addresses terminal failure, not a redesign of successful detached
work or backend-reported cancellation. Restart persistence remains governed by
existing handoff decisions. No files for intent revision or Voice were modified.

Parent accepted slice 02R. Next writer: Voice slice 05R, then separate Core slice 09R
for late uncertain-turn promotion and its reported SQLite test cleanup.
