# Slice 10 - Release evidence, documentation closeout, and human acceptance

## Goal
Consolidate QA evidence, update canonical documentation and run the final user-oriented acceptance checks without hiding residual risk.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `09-integration-responsive-accessibility`

## Scope / implementation steps
Run full targeted automated suites and any broader regression suite required by the files touched. Collect `qa-verification`, `code-review`, `runtime-validation` and trace analysis evidence where applicable from prior slices. Confirm no task-introduced regression remains parked in `Issues/`.

Update canonical docs, screenshots/diagrams if the repository keeps them, migration notes (if any), and the new shell/layer contract. Record exact final SHA(s), test commands and isolated runtime configuration.

Only after machine evidence is complete, run the human checks in this Slice and the design acceptance against `assets/target-ui-reference.png`.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `documentation and test evidence only unless a blocking defect is returned to its owning Slice`

## Architecture constraints
- No optimistic duplicate state when a canonical Core/runtime owner exists.
- Preserve error/refusal semantics and make unknown/unconfirmed states explicit.
- Update the explicit Control Center layer registry when introducing/moving overlays.
- Author-provided text is rendered safely; previews use bounded/safe routes.
- Code slices run `/caveman` and `/coding-guideline`; frontend code additionally runs `/impeccable` and uses a Claude agent when supported by the host.

## Automated validation
- `qa-verification` is mandatory.
- `runtime-validation` is mandatory.
- Run focused unit/integration tests for the exact behavior changed, plus neighboring regression tests named by current repository contracts.
- Runtime/UI validation must use an isolated Jarvis instance/worktree/data root unless the user explicitly authorizes the live instance.

## Acceptance criteria
- All required QA agents report pass or all blocking findings are resolved.
- Canonical docs match implementation.
- Final runtime evidence demonstrates wheel, capture, notification center, eye toggle, workspace rail, context zone and overlays.
- Human acceptance confirms the UI intent.
- Remaining issues are explicitly non-regressions with owner/impact, or release is blocked.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
