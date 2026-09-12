# Slice 09R — Preserve the latest confirmed intent

Date: 2026-09-12. Review correction to the existing intent-revision implementation.

## Finding and invariant

An older uncertain turn could finish after a newer addressed or confirmed turn.
Its late promotion restored the older user intent, despite the user's correction.
Cold reconstruction had the same problem for two uncertain turns confirmed in the
opposite order from their arrival.

The invariant is now explicit: the latest **confirmed** user turn by arrival order
owns the current intent. A newer unconfirmed or recused observation does not suppress
an older valid confirmation. Result arrival order does not decide user intent.

## Change

- Core retains an arrival sequence on pending uncertain turns and a confirmed-order
  watermark per conversation. Late stale promotion has no effect on intent or its
  revisions; backend work, public result and speech delivery remain intact.
- Cold reconstruction uses persisted turn order and matching assistant provenance
  to apply the same rule. Existing history-window and persistence limits remain.
- The barge-in test shadowed its SQLite repository with a state dictionary, losing
  the handle without closing it. It now uses distinct repository/snapshot names and
  stops the orchestrator and closes the repository in `finally`.

Slice 02R changes remain intact. No Voice/provider behavior, protocol fields,
cancellation policy, database schema or new event channel was added.

## Files

- `jarvis/core/brain_service.py`
- `tests/unit/test_v2_intent_revision.py`
- `tests/unit/test_v2_barge_in.py`
- This report.

## Observability / test contract

Existing DiagnosticSink/RuntimeJournal architecture follows Decision 27. No new
diagnostic subsystem or temporary probes were introduced.

- `brain.intent.revised` retains conversation/turn correlation and monotone state
  revision. Only a confirmation that wins by arrival order publishes this event.
- A stale older confirmation produces no false intent revision. Its existing
  `brain.speech.requested`, work completion and public-fact updates still proceed.
- No WorkCanceller calls occur from this path; an unconfirmed newer turn may remain
  active while the older confirmation completes.
- Tests inspect actual Core bus events, working state, persisted assistant turns and
  cold rehydration. No raw logs, hardware run or live provider result is claimed.
- Strict warning handling verifies SQLite resources are closed at teardown.

## Validation evidence

1. Baseline intent + barge-in with `-W error`: **43 assertions passed, process failed**
   with an unclosed SQLite `ResourceWarning` during final collection.
2. New four-case regression before production correction: **2 failed, 2 passed**.
   Newer addressed and newer confirmed cases restored January instead of February;
   newer recused and still-unconfirmed cases already retained correct behavior.
3. After production/test cleanup, intent + barge-in + brain orchestrator:
   **71 passed**, strict warnings, exit 0.
4. Final strict gate: intent revision, barge-in, brain orchestrator, speech scheduler,
   latency telemetry, architecture, brain protocol and async conversation integration:
   **161 passed**, `-W error`, exit 0.

All four regression cases assert matching live/cold intent, exact revision
correlations, preservation of the older public result and completed work, retention
of still-running newer work, and absence of automatic cancellation.

## Remaining scope

Arrival ordering is local to a running Core; cold reconstruction derives chronology
from the existing bounded persisted history. This does not extend restart durability
or make unspoken results persistent. No unrelated features or commits were added.

Next step: parent code review and independent validation before any further slice.
