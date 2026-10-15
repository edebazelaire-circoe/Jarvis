# Slice 01 - Shell contract, design language, and layer registry

## Goal
Establish the canonical UI contract for the new orbital shell before components are migrated.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `00-project-manager`

## Scope / implementation steps
Define and implement the shared shell foundations: layout zones, spacing/tokens, edge anchor geometry, right rail width behavior, bottom-center safe area, bottom-left context zone, global top chrome region, focus states, reduced motion, icon sizing, semantic colors, and an explicit z-index/layer registry. Create or extend the canonical Control Center UI documentation discovered by the PM.

Do not move all features yet. This Slice should make later component placement deterministic and keep current UI functional. Add regression tests for layer ordering rather than relying on arbitrary z-index numbers.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center.html`
- `shared Control Center theme/shell modules discovered at HEAD`
- `tests covering scene/layer order`
- `canonical Control Center UI docs (create/extend after audit)`

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
- A durable shell/layer contract exists and is referenced by later slices.
- Target art direction is represented through reusable tokens/classes, not copied one-off values in every module.
- Existing scene, dialogs, Studio/Variantes, Board chooser and mode chooser still stack correctly.
- `prefers-reduced-motion`, focus-visible and icon-only accessibility conventions are defined.
- Current UI remains functional before migration slices land.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
