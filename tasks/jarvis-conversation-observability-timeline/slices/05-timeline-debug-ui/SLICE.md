# Slice 05 — Build the live four-lane transcript/debug timeline

## Goal

Create the full-screen synchronized timeline requested by the user, driven by the query/live API.

## Context

This is an observability/debug surface, not a normal chat transcript. It must make timing and overlap visually obvious.

## Canonical Concepts

- dark/blurred full-screen view
- shared vertical time axis
- User lane left/white
- Mouth/Reflex/Jarvis lane light blue
- Brain lane orange
- sub-agent red duration blocks adjacent to Brain
- timestamps/durations
- clickable non-user event details
- virtualization for long sessions

## Scope

### In Scope

- Implement the timeline renderer and live append.
- Represent instantaneous messages and duration spans.
- Provide detail drawer/panel with IDs, model/status/latency/cancel reason when available, and trace navigation.
- Handle overlapping spans and long sessions efficiently.

### Out of Scope

- Changing event semantics.
- Displaying hidden chain-of-thought.

## Dependencies

04

## Implementation Steps

1. Use `/impeccable` and Claude routing if supported.
2. Create the Transcript/Debug navigation surface.
3. Implement lane layout and a central/shared temporal ruler.
4. Implement duration geometry and overlap handling.
5. Implement click detail panel for Brain/Mouth/sub-agent/tool events.
6. Add live updates, reconnect status, empty/error states, and session selector.
7. Add accessibility/keyboard basics and long-session virtualization.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_work.js or split frontend assets`
- `jarvis/runtime/control_center.py`
- `tests/*ui*`

## Architecture Constraints

- Timeline consumes canonical APIs only.
- Color is supplemental; actor labels/icons/text must preserve readability.
- User entries do not require diagnostic trace drill-down.

## Automated Validation

- Frontend unit/snapshot tests where supported.
- Runtime browser validation with deterministic fixture containing overlaps.
- Performance test/fixture for long session.

## Acceptance Criteria

- All four requested lanes render correctly.
- Overlap and duration are visually preserved.
- Non-user details expose trace linkage and useful metadata.
- Live updates append without page reload.

## Documentation Updates

Document the timeline UX, actor colors/lanes, and troubleshooting states.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
