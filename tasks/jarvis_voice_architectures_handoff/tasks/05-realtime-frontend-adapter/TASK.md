# Task 05 — Wrap the existing Realtime path in the VoiceFrontend adapter

## Goal

Move current Realtime behavior behind the common frontend contract without intentionally changing user-visible behavior yet.

## Context

This is the strangler/refactor step that proves the abstraction before adding new architectures.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Implement adapter around current Realtime Mini/full path.
- Translate provider events to canonical events.
- Translate canonical control operations to provider session/output operations.
- Feed provider output transcript / actual spoken events into the spoken ledger.
- Preserve current model selection and existing Gemini separation as discovered.

### Out of Scope
- Reflex policy redesign.
- GPT-Live.
- Luna sidecar.
- Settings UI redesign.

## Dependencies
- Tasks 03-04.

## Implementation Steps
- 1. Identify current provider client ownership from Task 01.
- 2. Wrap session create/update/close and audio flow behind adapter.
- 3. Map transcript and speech events to canonical events with IDs.
- 4. Map cancellation/interrupt outcomes and errors.
- 5. Route usage data into canonical session usage event.
- 6. Run existing tests and compare baseline behavior.

## Files Likely Touched
- Current Realtime runtime/client modules
- New Realtime adapter
- Voice wiring/composition root
- Adapter tests

## Architecture Constraints
- Behavior-preserving refactor first.
- No provider SDK event should bypass the adapter into Core.
- Do not silently drop diagnostic provider IDs needed for debugging.

## Testing Requirements
- Existing voice tests remain green or documented pre-existing failures remain unchanged.
- Synthetic adapter event mapping tests.
- Actual output transcript reaches spoken ledger.

## Acceptance Criteria
- JARVIS can run its current Realtime voice path exclusively through `VoiceFrontend`.
- Core no longer needs direct Realtime event handling for the migrated path.

## Documentation Updates
- Update current-code-map after moved ownership.

## Handoff Notes

Keep this change small enough that later behavior regressions can be attributed to policy tasks, not abstraction work.

### Inventory/review integration notes (2026-09-12)

`PersistentVoiceRuntime.activate` composes the session, scheduler and audio bridge. The bridge owns the single provider reader and already orders output events behind audio through `_dispatch` / `ORDERED_OUTPUT_EVENTS`; preserve those playout fences. Provider transcript reception is generated evidence, while the local audio bridge supplies playback evidence. Do not create competing consumers of the provider stream. Replace the old scheduler-intended-text history assumption with the Task04 ledger's explicit delivery semantics; avoid duplicate assistant turns from the bridge and scheduler. Read the verified Realtime contract notes when available, including cancellation outcomes and a true quiet-context operation separate from existing response-triggering `send_context`.
