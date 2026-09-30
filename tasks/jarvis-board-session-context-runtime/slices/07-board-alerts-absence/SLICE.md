# Slice 07 - Board-attributed global alerts and return-after-absence behavior

## Goal
Extend the existing BackgroundEventLedger/alerts path with optional board_id/source metadata, global visibility from any active Board, source-Board labels, a safe go-to-Board action, unread persistence across restart/new Session, and explicit proof that inactive Board completions/failures become notifications rather than grabbing Voice.

## Context
Jarvis already has a background-event/alerts pipeline and an active voice/runtime architecture. This Slice extends those canonical paths instead of inventing a parallel system.

## Canonical Concepts
Board; Session; BoardConversationBinding; global notification projection; Board attribution; deterministic runtime; single speech authority.

## Scope
### In Scope
Extend the existing BackgroundEventLedger/alerts path with optional board_id/source metadata, global visibility from any active Board, source-Board labels, a safe go-to-Board action, unread persistence across restart/new Session, and explicit proof that inactive Board completions/failures become notifications rather than grabbing Voice.
### Out of Scope
Galaxy/minimap visualization; automatic cross-Board context merging; a new digest engine; speaking every background event.

## Dependencies
02, 04

## Implementation Steps
Audit the current event -> ledger -> UI/runtime flow first; carry stable Board identity through canonical events; preserve acknowledgement/restart behavior; route navigation through normal switch_board; add traceable tests.

## Files Likely Touched
`jarvis/runtime/background_events.py`, current notification rendering, journal/task event producers, Board switch service, persistence/runtime tests; exact owners follow Slice 00 audit.

## Architecture Constraints
A notification is global projection, not implicit prompt/context fusion. Inactive Boards never gain speech authority from an alert.

## Automated Validation
Baseline qa-verification; code-review; runtime-validation; agent-trace-analysis where runtime/agent event routing changes. Cover restart/absence and cross-Board behavior.

## Acceptance Criteria
While the user is on Board B or absent, Board A can finish/fail work; the alert survives, identifies A, is visible from B/new Session, and can navigate to A through the normal switch transaction without contaminating B context.

## Documentation Updates
Update notification/absence and Board runtime documentation.

## Handoff Notes
Coding work loads /caveman and /coding-guideline. Human validation follows maximal machine QA.

## Slice 00 contract (authoritative, overrides the generic sections above)

Architecture: `docs/06-resolved-architecture.md`. Readiness: `slices/00-project-manager/READINESS.md` (inherited red tests = not yours).

- Depends on 02, 04a, 04b. `background_events.py`: `BackgroundEvent.board_id` (+ payload); `core.brain.speech_withheld_inactive_board` -> attention; persistence of entries, ack cursor and follower offset to `runtime/background-events.json` (bounded 60) so unread survives CC restart and new Session.
- Core diagnostics carrying `conversation_id` get `board_id` (via `BoardService`).
- UI: pills/popover show the source Board label; "go to Board" calls `POST /api/boards/switch` (normal transaction). Loads /impeccable for the UI part.
- Tests: attribution from a pool agent journal; restart keeps unread; inactive completion never produces speech (Core gate) but produces an alert; navigation uses switch.
