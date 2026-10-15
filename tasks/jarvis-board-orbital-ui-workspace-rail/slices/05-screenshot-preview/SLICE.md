# Slice 05 - Non-blocking screenshot preview and quick actions

## Goal
After successful screenshots, show a temporary real preview with useful actions without blocking the Board.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `04-capture-wheel-migration`

## Scope / implementation steps
Create a transient preview component driven by the successful capture/artifact identity. Load only the supported safe payload/thumbnail route. Preview auto-dismisses after a short interval unless being interacted with.

Quick actions required by product intent: Open, Annotate, Send to Jarvis, Delete. Each button must call a real supported path. If Annotate or Send-to-Jarvis lacks a canonical path at HEAD, implement the smallest real supported flow in this Slice or explicitly revise the Slice with PM approval; never ship a dead affordance.

Preview errors are presentation errors only and must not mutate the completed screenshot artifact/capture state.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `capture/artifact UI relay modules discovered at HEAD`
- `new screenshot preview module`
- `attachment/chat integration only if required for Send to Jarvis`
- `artifact UI tests`

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
- Successful screenshot produces a real preview; failed screenshot does not.
- Preview is non-modal and never blocks Board interaction.
- Auto-dismiss/focus behavior is predictable.
- Every visible quick action works through a canonical API.
- Preview failure never changes capture truth.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
