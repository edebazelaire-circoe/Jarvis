# Issue 004: a newer Voice loses whole event batches against an older Core when the vocabulary grows

Found by Slice 10 QA, 2026-10-06. This is a general gap in the conversation-event contract, not a Presentation defect.

## Behaviour

When Voice runs code that emits a new event type (e.g. `system.mode.changed`) while Core still runs older code, Core rejects the whole ingest batch with a 400: `events[i]: event_type is not in the vocabulary`. The Voice forwarder then drops the entire batch, up to 32 events, including unrelated mouth and brain events. The drop is counted (`dropped_rejected`) and logged once.

## Impact

Only during a partial restart, where Voice is restarted on new code before Core. The normal stack restarts both.

## Directions

- Have Core skip unknown types per event instead of rejecting the batch.
- Or have the forwarder retry the batch without the rejected index.
- Or state the restart order in `docs/conversation-events.md`.
