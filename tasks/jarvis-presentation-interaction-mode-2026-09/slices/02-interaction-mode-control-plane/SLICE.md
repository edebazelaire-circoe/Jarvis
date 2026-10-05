# Slice 02 - Add live interaction-mode control plane and persistence

## Goal
Make interaction mode a live, observable, persistent Jarvis state with one authoritative effective value and revision.

## Context
Presentation spans Core, Voice, and Control Center. A UI-only setting would drift. Control Center persists operator settings; Core already owns shared runtime truth/events.

## Canonical Concepts
InteractionMode; effective live mode vs stored preference; Core state/event ownership.

## Scope
### In Scope
- Persist requested mode in Control Center, default Simple.
- Add Core live state/service (or equivalent authoritative owner) with revision.
- Authenticated loopback get/set route(s) and event publication.
- Control Center startup reconciliation, `/api/status` and settings payloads.
- Voice observes mode/live changes without restart.
- Refuse Meeting activation with stable not-implemented code while advertising it.
- Diagnostics for requested/applied/refused changes without content leakage.
### Out of Scope
UI selector and Presentation behavior itself.

## Dependencies
Slice 01.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`.
2. Reuse repository control-plane patterns.
3. Add persistence migration/default.
4. Add typed transport codec/route/event.
5. Project effective state and supported modes into status.
6. Subscribe Voice/runtime to changes or safe mode snapshot seam.
7. Add concurrency/idempotence/startup reconciliation tests.

## Files Likely Touched
Core service/domain; protocol server/client; `control_center.py`; settings helpers; `voice_v2.py`/composition seam; tests.

## Architecture Constraints
Control Center UI is not authoritative; missing/invalid stored value yields Simple; Simple <-> Presentation should not require process restart when prerequisites exist.

## Automated Validation
Focused protocol/settings/status tests plus existing Control Center and voice runtime suites.

## Acceptance Criteria
All processes read one effective mode; Simple is migration/default; Presentation activates live; Meeting refusal explicit; status exposes effective mode/capabilities.

## Documentation Updates
Document persistence owner, live truth owner, routes/events and restart reconciliation.

## Handoff Notes
Slice 03 renders canonical status, not optimistic selection.
