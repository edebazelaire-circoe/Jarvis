# Slice 06 - Interface and interactions reorganization

> Authored by agent 0 during Slice 00: the Drive publication of this handoff contained an empty folder for this Slice. Content is derived strictly from `docs/02`, `docs/03`, `docs/04`, `docs/06` and `docs/07`; no new product decision is introduced.

## Goal

Gather appearance, every keyboard shortcut and ordinary Bare Hands preferences into `Interface & interactions`, giving `wake_toggle` its single canonical editor.

## Context

- `Apparence` is injected by `control_center_work.js` (`TABS.splice`) and extended by `control_center_scene_page.js`; preferences live in localStorage with immediate renderer application.
- `Raccourcis` renders `SET.shortcuts` but filters out `wake_toggle` (`control_center.html`, `item.id!=='wake_toggle'`), which is edited from Voice.
- Bare Hands (`control_center_barehands.js`) and scene settings (`control_center_scene_settings.js`) both target the same `experimental` tab ID.
- The `ui_tab_next` / `ui_tab_prev` shortcuts cycle the top-level list; after Slice 01/02 they must cycle the six categories (verify Slice 02 delivered this).

## Canonical Concepts

- `docs/07-target-settings-map.md` section 4
- `docs/02-architecture.md` section 5 (single canonical editable home)
- Bare Hands settings contracts (`control_center_barehands_contracts.js`)

## Scope

### In Scope

- Sections Theme & visual scene, Shortcuts, Bare Hands under `interface_interactions`.
- Shortcuts section lists every registered shortcut, including `wake_toggle`, with one editor each.
- Remove the read-only/link placeholder Slice 03 left in Voice only if it duplicates; Voice may keep effective-key context + deep link.
- Bare Hands ordinary preferences: target preview, aiming assistance, gesture sensitivity, sleep timeout, calibration enable/launch and calibration profile reset.
- Register Bare Hands benchmark, diagnostic recording, MediaPipe asset state, last voice command and on-screen diagnostics flag (if kept operator-only) as sections for Slice 08 under `advanced_diagnostics`.

### Out of Scope

- Do not change localStorage keys, shortcut registry persistence or Bare Hands bounds/lifecycle (the tool stays controlled from the wheel/session).
- Do not move scene test gate controls (Slice 08).

## Dependencies

- `02-settings-shell-visual-redesign`
- `03-voice-audio-reorganization` (wake_toggle hand-over)

## Implementation Steps

1. Freshness-check appearance, shortcut and Bare Hands settings code/tests.
2. Replace the `TABS.splice`/`TABS.push` injectors of appearance and Bare Hands with registry section registrations.
3. Render all shortcuts, `wake_toggle` included, in the Shortcuts section; ensure capture/cancel lifecycle still works.
4. Split Bare Hands rendering into ordinary vs operator sections.
5. Update tests.

## Files Likely Touched

- `jarvis/runtime/control_center_work.js`, `control_center_scene_page.js`
- `jarvis/runtime/control_center_barehands.js`
- `jarvis/runtime/control_center.html`
- appearance, scene view prefs, Bare Hands settings and shortcut tests

## Architecture Constraints

- One editable home per shortcut.
- localStorage contract and immediate renderer application unchanged.

## Automated Validation

- `wake_toggle` editable exactly once, in Shortcuts.
- Appearance keys unchanged; reset still works.
- Bare Hands settings save/reset unchanged; no Settings control starts/stops the Bare Hands tool.
- No `TABS` mutation from these modules.

## Acceptance Criteria

- No top-level `Apparence`, `Raccourcis` or `Expérimental` tab remains for ordinary preferences.

## Documentation Updates

Document appearance/scene preference ownership and the shortcut canonical home (`docs/settings/INDEX.md`).

## Handoff Notes

The `experimental` tab is shared with scene settings: coordinate with Slice 08 so the tab ID disappears only once both halves have homes.
