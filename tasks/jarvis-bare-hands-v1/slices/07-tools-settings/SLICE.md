# Slice 07 — Add Bare Hands Tools and Settings surfaces

## Goal

Expose the user-facing interaction tools separately from engine/settings configuration without changing the default contextual behavior.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture and contracts
- per-hand stable identity and latched capture
- BODY content interaction vs edge/corner frame manipulation
- semantic component hooks and compatibility DOM events

## Scope

### In Scope

- Add an extensible Bare Hands Tool contract and palette with initial modes: default/pointer, hand/pan, highlighter, drawing and selection.
- Tool behavior must be capability-gated by target/component; unsupported tools must fail safely.
- Keep default mode context-sensitive rather than globally forcing drag.
- Expand Bare Hands Settings beyond the legacy enabled boolean: enable/disable, target-feedback visibility, calibration entry, tutorial entry, sleep timeout/default, reset profile, and only safe/understandable sensitivity or assistance controls.
- Target-feedback toggle must change live preview behavior.
- Preserve a clear distinction between Tools (“what the hand does”) and Settings (“how Bare Hands behaves”).

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

01, 05, 06

## Implementation Steps

1. Load /caveman and /coding-guideline before coding; for browser/frontend UI also load /impeccable and use Claude routing when supported.
2. Freshness-check the exact current Control Center/Constellation contracts before editing.
3. Implement the smallest reusable mechanism that satisfies the locked interaction rules.
4. Add deterministic tests for state, geometry and error paths before relying on webcam checks.
5. Preserve offline operation, cleanup and clean-room licensing boundaries.
6. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- Control Center settings UI
- Bare Hands tool palette/components
- `jarvis/runtime/control_center_barehands.js` — it creates the shared "Expérimental" tab (`:507`) and monkey-patches `renderTab`
- `jarvis/runtime/barehands_test_mode.py` and the `GET`/`POST /api/barehands` route pair
- settings schema/persistence/backend
- target resolver integration
- `jarvis/runtime/control_center.py` and `jarvis/runtime/control_center.html` — marker constant, marker placement and load-order assertion for any new page module (Slice 00, F3)
- UI/unit tests

## Architecture Constraints

- Bare Hands **creates** the "Expérimental" settings tab, and `control_center_scene_settings.js` prepends its own section to it and depends on that injection order (documented at `control_center.py:224-226`). Restructuring Bare Hands settings can silently break the Scene settings section; keep the order and the existing assertions (Slice 00, F5).
- `barehands_test_mode` is deliberately absent from `_settings_payload` / `GET /api/settings`. It has its own immediate-write route pair so the toggle applies hot and does not depend on the rest of the settings validating (rationale at `control_center.py:1661-1666`). Preserve that unless the Human decides otherwise.
- Follow the established settings-module shape (`SETTING_KEY`, a tolerant `load`, a strict `apply` raising a stable `.code`, and `describe`), as in `jarvis/runtime/scene_settings.py`.

- One hand on a manipulation zone moves; it never resizes.
- Only two compatible manipulation-zone captures on the same object may resize it.
- BODY remains content interaction.
- Captures are latched until release.
- Two hands on distinct objects stay independent.
- Current component names/APIs must be discovered rather than invented.

## Automated Validation

Settings round-trip/schema tests; tool capability-gating fixtures; target-feedback toggle runtime test; accessibility/keyboard and responsive UI checks; migration test from the existing barehands_test_mode setting.

## Acceptance Criteria

Tools and Settings are visibly and architecturally distinct. Default interaction remains contextual. Target preview can be disabled. Unsupported tool/target combinations are safe and understandable.

## Documentation Updates

Document tool IDs/capabilities, settings schema/defaults, migration behavior and extension rules.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review for code changes and runtime-validation for user-visible/runtime behavior. Regressions introduced by this Slice are blocking.
