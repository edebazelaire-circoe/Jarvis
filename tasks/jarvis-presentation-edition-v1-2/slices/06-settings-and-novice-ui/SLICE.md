# Slice 06 — Full Settings retained, novice product path simplified

## Goal
Reduce cognitive load for a non-expert Presentation user without removing the Settings and transcription/debug controls needed for support and field diagnosis.

## Context
The parent V1 proposed hiding developer surfaces. The user corrected this: keep Jarvis Control Settings, including transcription settings, because they are useful when debugging directly on another person's machine. The simplification target is the everyday product path, not feature deletion.

## Canonical Concepts
- current Settings navigation/shell and page registry;
- Presentation Board card/panel and product UI;
- Voice state from Slice 05;
- parent V1 Presentation UI/onboarding Slices.

## Scope
### In Scope
- preserve every currently supported Settings page/control unless it is objectively broken/dead and separately approved for removal;
- keep transcription, voice/provider, agent and technical diagnostics reachable;
- simplify the default user journey: choose/resume a Presentation project, talk/chat, access Dossier/research, create/edit/present/export;
- use progressive disclosure/grouping for advanced controls instead of deleting them;
- Presentation Board creation remains the only available product creation path; Assistant/Meeting stay visibly “coming soon/unavailable” rather than error states;
- expose a clear Voice Off/Sleep/Active control/status consistent with Slice 05;
- add an obvious entry point to “Report a problem” (Slice 07), preferably in Settings/Help and/or error surface;
- reduce technical vocabulary on normal screens while retaining raw codes/details inside diagnostics/settings.

### Out of Scope
- redesigning every Settings page from scratch;
- removing controls solely because novice users do not need them daily;
- hiding debugging information from support engineers;
- implementing Assistant/Meeting modes.

## Dependencies
- `01-presentation-product-brain-scope`;
- consume `05-voice-lifecycle-wake-chat` state contract when available.

## Implementation Steps
1. Inventory every current Settings page/control and mark essential-normal vs advanced/support without deleting either class.
2. Audit the normal Presentation journey from launch -> Board resume/create -> research/documents -> Presentation -> edit/present/export.
3. Refactor navigation/labels/layout so the normal journey is visually primary and advanced settings are secondary but discoverable.
4. Keep transcription and technical settings intact; ensure deep links/support instructions can reach them quickly.
5. Integrate Voice state control/status and Report-a-problem entry.
6. Keep Assistant/Meeting affordances as stable “Bientôt disponible” states with no hidden creation bypass.
7. Validate keyboard/focus/responsive behavior and real settings values; no mock-only UI.

## Files Likely Touched
Control Center product shell, Board UI, Settings registry/navigation/styles, Voice status widgets, Help/support surface, tests/docs.

## Architecture Constraints
- UI is a projection of server/runtime truth, not a second state owner;
- advanced settings remain functional and test-covered;
- no optimistic state for Voice/Board availability.

## Automated Validation
- browser tests for main workflow and Settings navigation;
- regression suite proving existing Settings/transcription controls remain reachable and functional;
- Board create UI only allows Presentation while showing other types as incoming;
- Voice state UI reflects runtime state;
- accessibility/focus/reduced-motion checks;
- visual screenshots at representative laptop and desktop sizes.

## Acceptance Criteria
A first-time user can find the Presentation workflow without understanding Jarvis internals, while a support/debug session can still access the full technical Settings surface.

## Documentation Updates
Update Settings navigation/product-shell docs and support/debug entry instructions.

## Handoff Notes
This Slice amends the parent V1 UI intent: simplify by prioritization and progressive disclosure, not by deleting Settings.