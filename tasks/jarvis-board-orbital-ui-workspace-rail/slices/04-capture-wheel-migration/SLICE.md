# Slice 04 - Migrate Video, Screenshot, and Audio into the wheel

## Goal
Replace the permanent capture rail presentation with wheel actions while preserving Core capture truth and recovery behavior.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `02-orbital-tool-wheel`
- `03-selection-input-arbitration`

## Scope / implementation steps
Refactor/reuse `control_center_capture_rail.js` logic instead of rewriting capture ownership. The new view consumes the same canonical status and write/re-read flow.

Audio: activation toggles start/stop, duration remains visible when wheel closes, secondary action shows supported audio sources.
Video: activation toggles screen recording, persistent `REC + duration`, secondary action shows supported targets.
Screenshot: immediate one-shot capture with default target; secondary action shows supported targets.

Only expose options backed by current capture adapters/API. Preserve status-loss handling, privacy-first stop, stale poll rejection, Core-derived timing, multi-tab/reload truth and independent audio/video channels.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center_capture_rail.js`
- `jarvis/runtime/control_center.html`
- `docs/capture.md only if contract changes`
- `existing capture JS/unit tests`

## Architecture constraints
- No optimistic duplicate state when a canonical Core/runtime owner exists.
- Preserve error/refusal semantics and make unknown/unconfirmed states explicit.
- Update the explicit Control Center layer registry when introducing/moving overlays.
- Author-provided text is rendered safely; previews use bounded/safe routes.
- Code slices run `/caveman` and `/coding-guideline`; frontend code additionally runs `/impeccable` and uses a Claude agent when supported by the host.

## Automated validation
- `qa-verification` is mandatory.
- `code-review` is mandatory.
- `runtime-validation` is mandatory.
- Run focused unit/integration tests for the exact behavior changed, plus neighboring regression tests named by current repository contracts.
- Runtime/UI validation must use an isolated Jarvis instance/worktree/data root unless the user explicitly authorizes the live instance.

## Acceptance criteria
- Old permanent capture rail can be removed/hidden without losing behavior.
- Audio and Video start/stop match canonical capture state and errors.
- Screenshot executes a real one-shot capture.
- Active capture indicators remain after wheel retracts.
- Reload/status-loss behavior remains at least as safe as before.
- No optimistic local recording state becomes authoritative.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
