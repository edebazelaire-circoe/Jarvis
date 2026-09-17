# Slice 06 — Split voice settings into top sub-tabs and embed the voice catalog

## Goal

Reorganize the current dense voice-model/settings page into clear top categories and reuse the catalog comparison component for voice models.

## Context

The exact setting list is large and evolving. Category mapping from Slice 01 and supported turn-taking contract from the voice-arbitration task are authoritative.

## Canonical Concepts

- top category/sub-tab bar
- Architecture
- Conversation
- Turn-taking & interruptions
- Models
- Audio
- Advanced
- Diagnostic (labels may be polished without changing category intent)
- shared voice model catalog

## Scope

### In Scope

- Refactor existing voice controls into categories.
- Expose supported turn-taking controls in one place.
- Embed role-filtered voice catalog.
- Preserve save/load semantics.

### Out of Scope

- Changing voice runtime behavior.
- Adding unsupported knobs.

## Dependencies

01, 04

## Implementation Steps

1. Freshness-check voice arbitration/settings contract before coding.
2. Use `/impeccable` and Claude routing if supported.
3. Create top sub-tab navigation with deep-link/state retention where appropriate.
4. Move every existing voice option into exactly one category.
5. Use shared table for realtime/transcription/speech models with role filters.
6. Group internal/diagnostic knobs away from primary workflow.
7. Add UI tests and runtime validation.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center.py`
- `jarvis/runtime/voice_stack.py only for schema metadata if required`
- `tests/*voice*`
- `tests/*control_center*`

## Architecture Constraints

- Frontend must reflect supported runtime settings, not create semantics.
- Preserve existing values during category migration.

## Automated Validation

- Category mapping test.
- Save/reload regression test.
- Voice catalog role-filter tests.
- Responsive runtime validation.

## Acceptance Criteria

- All voice settings remain reachable in a coherent category.
- Turn-taking/interruption settings are easy to locate.
- Models tab clearly distinguishes usable vs unavailable voice models.

## Documentation Updates

Update voice settings reference and category map.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
