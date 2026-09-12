# 07 — Core Work-State Integration

## Problem

`AgentTaskTracker` can reconstruct rich Claude subtask state, including current activity/model/status/timing metadata, and the Control Center can display it. Core brain state currently does not own that rich representation.

This violates the agreed principle that JARVIS itself should know the operational facts the UI shows.

## Target contract

Provider-specific observers remain at the edge:

```text
Claude stream-json -> AgentTaskTracker -> WorkObservationSink
Codex verified stream -> Codex observer -> WorkObservationSink
Jobs -> JobService/progress -> WorkObservationSink
```

Core normalizes these into a bounded store.

## Suggested domain types

Names are provisional. Prefer existing naming conventions if equivalents exist.

```python
@dataclass(frozen=True)
class WorkObservation:
    source: str
    external_id: str
    status: WorkStatus
    observed_at: datetime
    activity: str = ""
    summary: str = ""
    model: str = ""
    parent_external_id: str | None = None
    progress_fraction: float | None = None
    error_class: str | None = None

@dataclass(frozen=True)
class WorkSnapshot:
    revision: int
    items: tuple[WorkItem, ...]
    updated_at: datetime
```

## Identifier mapping

Do not pretend provider task IDs are the same as brain `work_id` when they are not.

Add an explicit mapping/link when known:

- Core `work_id`
- provider external task id
- correlation id / brain turn id

Unknown links remain unknown; never infer by label alone.

## Brain access

Two acceptable shapes:

1. extend brain execution context with a bounded `WorkSnapshot`; or
2. inject a typed `WorkStateReader` into a Core-side brain adapter/context builder.

Recommendation: create a `BrainContext` aggregate if extending `BrainBackend.run_turn` can be done with a staged compatibility adapter. Avoid stuffing unbounded task arrays into `BrainWorkingState.to_public_payload()`.

## UI access

Expose a Core endpoint/event projection with the normalized task state. During migration, keep `/api/agent/tasks` compatible by translating from Core where possible. Delete direct runtime authority only after UI parity tests pass.

## Speech policy

State change != speech.

Suggested policy:

- normal progress: UI only by default;
- meaningful milestone after long delay: optional progress speech;
- blocker/failure needing user choice: high priority speech/notification;
- completion/result: normal result policy;
- background/muted: persist state, no forced speech; surface on reactivation/notification according to policy.
