# Slice 07 - Right-side active workspace rail with rich previews

## Goal
Move the current presentation rail to the right and evolve it into the active workspace rail without inventing a second registry.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `01-shell-contract-and-design-system`

## Scope / implementation steps
First preserve the complete existing presentation-rail behavior while moving/rebuilding its visual renderer on the right. Replace monogram-only rows with cards: real preview where available, recognizable type treatment, title, lightweight metadata, status and context menu.

Then, if current Board/artifact APIs support it cleanly, include additional context-linked image/video/document artifacts through a view-model adapter. Do not crawl arbitrary files or maintain local membership.

Status mapping: blue working, green ready/done, yellow changed/unreviewed only if backed by canonical state, explicit orange/red problem/error retained. Context switch must refresh the working set. Existing actions (open Variantes, Studio, edit, present, hide/show, rename, archive/restore where applicable) remain available.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center_presentation_rail.js`
- `presentation rail routes/view model`
- `workspace/artifact UI adapters if broadening beyond presentations`
- `presentation rail tests`

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
- Rail is on the right and no longer competes with the left wheel.
- Presentation behavior/actions are preserved.
- Cards visually identify type and use truthful preview/fallback.
- Status is semantic and never relies on color alone.
- `problem` is not mislabeled as `changed`.
- Current-context membership is server/canonical-data-driven.
- Studio/Variantes coexists with the new rail without layering regressions.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
