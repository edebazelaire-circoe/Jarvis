# Slice 04 — Jarvis Intent and Speech-Progress Contract

## Goal

Teach Jarvis that UI execution is delegated and expose typed UI intentions plus real speech/response progress so Tool Brain can synchronize actions to what the user is hearing.

## Context

Jarvis should understand the UI capabilities of the whole system while avoiding direct UI tool execution in the normal path. Long responses require future generated chunks and current playback position, not only final text.

## Canonical Concepts

UI capability manifest, UI intent, response ID, speech chunk, playback progress, interruption/cancellation.

## Scope

### In Scope

- Jarvis prompt/runtime architectural description of Tool Brain delegation.
- UI capability manifest made available to Jarvis without advertising mutating UI tools as normal direct calls.
- Structured optional UI intent/relevance emission.
- Response/chunk identity and current/upcoming speech projection for Tool Brain.
- Speech interruption/cancellation events.
- Correlation IDs linking Jarvis response, Mouth/Reflex playback and Tool Brain decisions.
- Debug/fallback direct-UI path, if retained, made explicit and observable.

### Out of Scope

- Tool Brain action selection.
- Removing non-UI tools from Jarvis.

## Dependencies

- `01-runtime-contract-audit`
- `02-ui-tool-choice-contract`

## Implementation Steps

1. Reuse canonical response/Mouth events found in Slice 01.
2. Define the minimum typed UI intent payload; avoid low-level layout commands.
3. Expose current and upcoming generated response segments in a bounded form.
4. Emit progress/interrupt events at the authoritative playback layer.
5. Update Jarvis system/runtime instructions so delegated UI is described accurately.
6. Add tests that Jarvis does not falsely claim UI incapability and does not normally double-call UI tools.
7. Add trace fixtures correlating one long response to speech progress events.

## Files Likely Touched

Jarvis Brain prompt/runtime configuration, speech/Mouth event pipeline, event schema and tests identified by Slice 01.

## Architecture Constraints

Do not leak hidden reasoning/chain-of-thought. Future context is the already-generated response plan/chunks and explicit UI intent, not private internal reasoning.

## Automated Validation

- Intent events validate against schema.
- Chunk order/progress is monotonic within a response except explicit cancellation/restart semantics.
- Interruption marks future speech-bound actions obsolete.
- Jarvis UI capability descriptions stay in sync with catalog metadata.

## Acceptance Criteria

- Tool Brain can tell what Jarvis is saying now and what generated segment comes next.
- Jarvis knows UI is available but delegated.
- No normal-path duplicate UI execution exists.

## Documentation Updates

Promote intent and speech-progress contracts to Level 3.

## Handoff Notes

Use `/caveman` and `/coding-guideline`. Prompt/runtime changes require `agent-trace-analysis`.
