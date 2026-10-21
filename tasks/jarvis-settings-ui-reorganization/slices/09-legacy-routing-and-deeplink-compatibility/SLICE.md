# Slice 09 - Legacy tab cleanup and compatibility aliases

> Authored by agent 0 during Slice 00: the Drive publication of this handoff contained an empty folder for this Slice. Content is derived strictly from `docs/02`, `docs/03`, `docs/04`, `docs/06` and `docs/07`; no new product decision is introduced.

## Goal

Remove the legacy top-level tab machinery and keep only explicit, tested aliases for programmatic callers.

## Context

Known programmatic callers on the audited `main`:

- `openSettingsTab(tab)` / `settingsTabs()` in `control_center.html`, used by the Jarvis wheel (`control_center_jarvis_wheel.js`): the Paramètres submenu lists `settingsTabs()`, and the `voice_settings` row opens `'voice'`.
- Legacy IDs: `voice`, `wakeword`, `prompts`, `cli`, `keys`, `shortcuts`, `memory`, `subagents`, `appearance`, `experimental`.
- `ui_tab_next` / `ui_tab_prev` shortcuts.

## Canonical Concepts

- `docs/02-architecture.md` section 6
- Slice 01 alias table

## Scope

### In Scope

- Delete remaining `TABS` mutation paths and the old tab renderer branches.
- `openSettingsTab` accepts category IDs, section IDs and legacy aliases; unknown IDs log and open the shell on its default category.
- `settingsTabs()` (or its successor) returns the six categories; wheel submenu shows them.
- Remove aliases no longer used by any repository caller or durable doc; keep and test the rest.

### Out of Scope

- No persistence change.

## Dependencies

- `08-advanced-diagnostics-labs`

## Implementation Steps

1. Grep repository callers and docs for every legacy ID.
2. Remove dead legacy code paths.
3. Finalize alias table and tests.
4. Update wheel tests and docs.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_jarvis_wheel.js`
- `tests/unit/test_jarvis_wheel_js.py`, `tests/unit/test_jarvis_wheel_browser.py`, Settings tests

## Architecture Constraints

- Aliases are explicit data, not fallbacks hidden in conditionals.

## Automated Validation

- Every remaining legacy ID resolves to the declared destination.
- No `TABS.push`/`TABS.splice` left in the repository.
- Wheel Paramètres submenu lists exactly six entries.

## Acceptance Criteria

- The old top-level tab system no longer exists; compatibility is explicit and tested.

## Documentation Updates

Superseding note in `tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json` consumers / `docs/settings/INDEX.md`.

## Handoff Notes

Run the wheel browser harness only in a sandbox (never the live JARVIS).
