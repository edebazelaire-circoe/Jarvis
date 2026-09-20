# Slice 08 — Integrate, migrate, validate and document the refined Bare Hands UX

## Goal

Prove the complete UI refinement works coherently on top of the existing Bare Hands V1 without regressing tracking, interaction, calibration, diagnostics, voice/MCP control, or scene behavior.

## Context

The previous Slices deliberately change presentation and entry points in pieces. This Slice closes migrations, removes stale duplicate UI, runs end-to-end validation, and updates the canonical documentation to the final single-flow model.

## Canonical Concepts

- main lifecycle button/state synchronization
- quick actions and Settings IA
- fixed tool palette
- Help/Diagnostics surfaces
- unified calibration flow
- legacy tutorial compatibility decision
- existing Bare Hands contextual interaction contract

## Scope

### In Scope

- Integrate all refined surfaces into the normal Control Center.
- Remove obsolete/dead UI paths and stale CSS/DOM hooks after compatibility is proven.
- Verify persisted settings/profile migration on existing users.
- Verify current voice/MCP commands and receipts against the final lifecycle/calibration model.
- Run full Bare Hands + relevant Control Center/scene test suites.
- Run browser/runtime/offline/resource-cleanup validation.
- Update canonical docs and user help.
- Produce final Human validation only after all machine QA is clear.

### Out of Scope

- New Bare Hands tools/gestures.
- Broader frame visual redesign.
- New hardware/tracker work.

## Dependencies

01, 02, 03, 04, 05, 06, 07

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Freshness-check all touched modules and migrations.
3. Run targeted tests for each prior Slice, then the broader relevant suite.
4. Validate no stale Settings/Experimental entry is required for normal Bare Hands use.
5. Validate HUD state sync across UI, C-wake, voice, inactivity and failures.
6. Validate tool palette, context menu, Help, Diagnostics and Calibration together.
7. Validate calibration steps on real browser DOM and scene adapters.
8. Validate offline MediaPipe/assets, camera teardown and privacy invariants.
9. Remove obsolete tutorial/modal/tool-settings code only after coverage proves it is unused.
10. Update docs and migration notes.

## Files Likely Touched

- all Bare Hands UI/runtime modules changed by Slices 01–07
- relevant scene/command/settings modules
- tests
- `docs/barehands-contracts.md`
- user/developer Bare Hands documentation

## Architecture Constraints

- Existing contextual interaction semantics remain unchanged.
- UI state is a projection of canonical runtime state.
- No separate tutorial flow survives.
- No new tool sneaks into the palette.
- Calibration/profile privacy and no-cloud operation remain intact.

## Automated Validation

- full relevant Python/Node/browser test suites;
- Settings/profile migration fixtures;
- lifecycle/resource teardown tests;
- command channel/trace tests;
- calibration timing and window practice tests;
- diagnostics privacy tests;
- no external runtime asset requests;
- stale selector/DOM hook scan for removed modal/tutorial/tool-settings UI.

## Acceptance Criteria

- Bare Hands can be operated day-to-day from the main HUD without visiting Settings.
- Pointer/Pan/Select are one-click accessible from the left palette.
- Right-click provides Settings, Calibration, Help/Gestures and Diagnostics.
- Calibration is calm, full-screen, visually guided and does not start while the user is merely reading.
- Real frame move/resize is taught/tested inside calibration.
- Separate Tutorial is gone.
- Existing interaction, diagnostics, voice, privacy, offline and cleanup behavior still pass.

## Documentation Updates

Update `docs/barehands-contracts.md` and related user/developer documentation to describe the new UI hierarchy, unified calibration flow, tutorial compatibility migration, and final calibration sequence.

## Handoff Notes

Baseline `qa-verification`, `code-review`, and `runtime-validation` are required. Add `agent-trace-analysis` for any command/MCP migration touched by the integrated result.
