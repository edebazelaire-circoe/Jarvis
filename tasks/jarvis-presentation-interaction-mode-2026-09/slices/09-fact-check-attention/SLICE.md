# Slice 09 - Add fact-check attention events, floating warning, and discreet sound

## Goal
Surface meaningful Presentation contradictions without unsolicited spoken interruption.

## Context
Control Center already has a background-event ledger and discreet pills. Reuse and extend it rather than creating a second notification system.

## Canonical Concepts
`PresentationAttention`; existing `BackgroundEventLedger`; confidence/evidence gating; one sound per new event deduped across polling/tabs.

## Scope
### In Scope
- Typed categories such as contradiction, uncertainty, useful_context, source_found, data_issue; V1 emphasis contradiction/mismatch.
- Require evidence/source/provenance and confidence before contradiction.
- Emit attention from completed speculative fact-check.
- Extend background classifier/payload as needed.
- Small floating warning that can open detail/resource context.
- Short discreet non-speech sound for newly arrived relevant warning.
- Dedupe sound across polling/reload/multiple tabs.
- Never spontaneous TTS.
### Out of Scope
User-configurable alert preferences; vocal interruption on contradiction.

## Dependencies
Slices 03 and 08.

## Implementation Steps
1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Define attention schema/evidence rules.
3. Extend background classifier/payload with stable IDs/resource refs.
4. Add floating warning view.
5. Implement sound via browser-safe audio/WebAudio or existing infrastructure.
6. Ensure one leader/tab emits sound and each event sounds at most once locally.
7. Test false-positive prevention, dedupe, polling, reload, zero speech.

## Files Likely Touched
`background_events.py`, `control_center.html`, notification JS module, presentation fact-check events/service, tests.

## Architecture Constraints
Search failure/absence is not contradiction; sound is UI attention not TTS; alert dismissal does not mutate facts.

## Automated Validation
Background ledger, Node UI logic, status/poll and attention contract tests.

## Acceptance Criteria
Supported contradiction -> one warning + one discreet cue; polling no replay; failures no false contradiction; no automatic speech.

## Documentation Updates
Document categories, evidence threshold and UI/sound dedupe.

## Handoff Notes
Human check `HV-PRES-ALERT-01` validates discretion.
