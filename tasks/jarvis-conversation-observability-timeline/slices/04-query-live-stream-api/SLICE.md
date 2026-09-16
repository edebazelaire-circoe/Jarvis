# Slice 04 — Expose conversation query and live-stream APIs

## Goal

Provide stable APIs for initial timeline hydration, incremental live events, event details, and trace links.

## Context

The frontend must consume canonical events and never tail raw files directly.

## Canonical Concepts

- session listing/detail
- paginated/range event query
- SSE/WebSocket or existing push transport for live append
- event detail/trace reference
- reconnect cursor

## Scope

### In Scope

- Expose read/query endpoint(s).
- Expose live event stream using an existing transport where appropriate.
- Support reconnect without duplicate UI rows.
- Add bounded payloads and pagination.

### Out of Scope

- Frontend implementation.
- Public remote exposure beyond current Jarvis Control Center security model.

## Dependencies

02, 03

## Implementation Steps

1. Audit existing Control Center/API streaming patterns.
2. Implement session/event endpoints and live stream.
3. Use event_id/cursor for resume.
4. Enforce access/redaction rules.
5. Add API tests for pagination, reconnect and concurrent append.

## Files Likely Touched

- `jarvis/runtime/control_center.py`
- `jarvis/runtime/*api*`
- `tests/integration/*control_center*`

## Architecture Constraints

- Do not expose raw trace files as the primary API.
- Live stream and persisted query must converge on the same events.

## Automated Validation

- API schema tests.
- Reconnect/idempotency test.
- Long-session pagination test.

## Acceptance Criteria

- Reloading the page yields the same event set as live consumption.
- No duplicate/lost event after reconnect in tested failure window.

## Documentation Updates

Document API contracts and cursor/reconnect semantics.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
