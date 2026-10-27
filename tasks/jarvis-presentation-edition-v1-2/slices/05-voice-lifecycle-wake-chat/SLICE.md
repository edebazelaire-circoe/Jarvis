# Slice 05 — Voice lifecycle, wake word and chat

## Goal
Make Jarvis application lifecycle and voice state understandable and deterministic for a normal user: app open means Jarvis is running, voice idles in Sleep, explicit Off disables voice, wake word activates it, and chat remains usable independently.

## Context
The repository already has Voice runtimes, interaction modes, session rebind and wake-word work. The amendment is a product contract over those pieces, not a replacement voice stack.

## Canonical Concepts
- existing Voice runtime and wake-word contracts/docs discovered in Slice 00;
- Presentation interaction mode and Board-derived mode;
- app launcher/process supervision;
- Settings voice/transcription controls.

## Scope
### In Scope
- formalize application lifecycle vs voice lifecycle;
- normal launch starts Core/Control Center/Voice support processes and enters Voice Sleep with wake-word listener armed unless user explicitly persisted Off;
- explicit Off stops microphone/wake listener and persists as the user's choice;
- manual/wake activation transitions Sleep -> Active using existing voice/session semantics;
- when active interaction ends, return to the existing safe idle behavior (normally Sleep) without inventing a second state machine;
- closing the application shuts down Core, Voice and child runtimes and releases microphone/audio resources;
- chat works in Sleep and Off;
- chat submission must not silently activate mic, wake listener or spoken output if voice is Off;
- expose current state consistently to UI/status/settings and diagnostics.

### Out of Scope
- new speech provider;
- a new interaction-mode system separate from Board type;
- always-on ambient transcription while Voice Off;
- shipping a wake-word model whose product license is unresolved.

## Dependencies
- `01-presentation-product-brain-scope`.

## Implementation Steps
1. Blind-audit current Voice stop/sleep/wake/active semantics and wake-word implementation; map them to the product states instead of duplicating them.
2. Add one canonical persisted user preference for explicit Voice Off / normal Sleep startup if such ownership does not already exist.
3. Wire app startup: if Off persisted, keep voice off; otherwise initialize wake listener and report Sleep only after readiness is real.
4. Wire shutdown supervision so closing the product stops Core/Control Center/Voice/Remotion/helper children gracefully, then forcibly cleans stragglers if needed.
5. Define chat behavior under every voice state; chat responses stay text-only when voice is Off unless the user explicitly re-enables voice.
6. Update status/settings UI contracts and stable diagnostic events for transitions/refusals/failures.
7. Handle missing/licensing-invalid wake-word provider as a visible degraded state, not silent Active listening.

## Files Likely Touched
Voice runtime/state/wake-word modules, app launcher/supervisor, Settings/status surfaces, chat response routing, tests/docs.

## Architecture Constraints
- state ownership is singular;
- persisted Off is user intent and cannot be overwritten by restart;
- no microphone access in Off;
- app close is a process boundary, not merely UI close.

## Automated Validation
- startup matrix: fresh profile -> Sleep; persisted Off -> Off;
- Off has no active mic/wake resources;
- wake event from Sleep activates the correct Board/session;
- chat in Sleep/Off reaches brain and does not alter voice state unexpectedly;
- closing app ends all supervised child processes and frees ports/audio handles;
- crash/restart recovery tests;
- real runtime-validation with microphone plus wake-word provider where licensing/config allows.

## Acceptance Criteria
The state shown to the user matches actual microphone/wake behavior, explicit Off survives restart, normal launch is wake-ready Sleep, and chat remains a reliable independent surface.

## Documentation Updates
Create/update one product voice-lifecycle contract and cross-link wake word, Settings and launcher docs.

## Handoff Notes
If existing runtime has different internal names, preserve them internally and map to user-facing Off/Sleep/Active only at the product contract layer.