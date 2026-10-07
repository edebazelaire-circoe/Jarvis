# Slice 09 — Tool Brain Observability Timeline Extension

## Goal

Extend the existing conversation observability/live transcript interface so Tool Brain decisions and tool-call queue behavior are visible on the same time axis as User, Mouth/Reflex, Brain and sub-agent activity.

## Context

A live transcription/debug timeline already exists. The user explicitly does not want a second transcription system; this Slice adapts the existing view.

## Canonical Concepts

Conversation event, Tool Brain event, queue span, tool-call span, shared time axis, diagnostic drill-down.

## Scope

### In Scope

- Emit Tool Brain lifecycle/decision/queue/tool events into the canonical conversation event log.
- Correlate Tool Brain events with user turn, Jarvis response, speech chunk, snapshot and tool action IDs.
- Add a Tool Brain lane or clear overlay to the existing live timeline.
- Visualize queued/waiting, executing, completed, cancelled, failed and invalidated/replanned actions.
- Drill-down to snapshot/decision/tool metadata appropriate for debugging.
- Preserve the current lanes and canonical transcript projections.

### Out of Scope

- New transcript storage.
- LLM-generated rewriting of canonical conversation history.
- Redesigning unrelated timeline aesthetics.

## Dependencies

- `05-tool-brain-runtime`
- `06-action-queue-revalidation`
- `08-autonomy-ownership-guardrails`

## Implementation Steps

1. Reuse the canonical conversation-event envelope and live stream.
2. Add Tool Brain event types/correlation fields.
3. Extend timeline projection/view model.
4. Add Tool Brain lane/overlays with compact default detail and drill-down.
5. Show queue scheduling and cancellations on the shared time axis.
6. Add browser/UI regression tests using real emitted events.
7. Validate long-response and interruption scenarios visually and by automated timing assertions.

## Files Likely Touched

Existing conversation event/timeline backend and Control Center/frontend timeline files discovered in Slice 01.

## Architecture Constraints

Canonical events drive the view. The frontend must not infer Tool Brain history from transient DOM state.

## Automated Validation

- Event schema/query/live-stream tests.
- Frontend rendering tests for all action states.
- Correlation tests from user turn -> Jarvis response/chunk -> Tool Brain decision -> tool execution.
- Existing timeline lanes remain regression-free.

## Acceptance Criteria

- A developer can diagnose why an element appeared, moved, did not appear, or was cancelled without reading raw logs manually.
- Existing transcript functionality remains intact.

## Documentation Updates

Update timeline/event docs with Tool Brain lane and event semantics.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`, and a Claude agent when host routing supports it. Frontend/runtime changes require `runtime-validation` and `agent-trace-analysis`.
