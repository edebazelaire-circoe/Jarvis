# Slice 02 — Personalisation UI refactor

## Goal

Refactor the Jarvis **Personalisation** Settings view to the supplied three-column visual reference while preserving live voice, personality/profile and proactive-behavior semantics.

## Context

Reference: `references/ui/01-personnalisation.png`.

The screenshot establishes a desktop composition with Voice and global behavior on the left, personality and quick preferences in the center, and profile/proactivity controls on the right. The page must feel like one coherent Settings workspace rather than disconnected legacy forms.

## Canonical Concepts

- `REFERENCE.md`
- `docs/06-visual-contract.md`
- live voice/audio settings contracts
- live personality/profile/proactivity contracts discovered during Slice 00

## Scope

### In Scope

- Page header/breadcrumb/subtitle matching the reference hierarchy.
- Left column `Voix GPT Live` card: voice selector, preview/listen action, volume, speaking rate and language where those controls are supported by live contracts.
- Left column `Comportement global`: response style, technical level and focus domains mapped to canonical settings.
- Center `Personnalité`: general tone, humor, formality, response length and custom instructions using existing canonical fields or clearly mapped equivalents.
- Center `Préférences rapides`: quick style presets such as concise/detailed/technical/creative only when backed by real preset behavior; otherwise implement as presentation over canonical fields rather than a parallel store.
- Right profile selector/dropdown: active profile summary, profile list, selection and create-profile entry when the live profile model supports them.
- Right `Proactivité & automatisations`: proactive suggestions, reminders, contextual automations, context analysis and discreet mode mapped to actual settings/capabilities.
- Loading, empty, disabled, unavailable and error states for all externally supplied options.
- Responsive collapse from 3 columns to 2/1 without losing logical reading order.

### Out of Scope

- Do not invent voice models, personalities or automation capabilities absent from the runtime.
- Do not expose secret/provider setup here; link to the canonical credential home when required.
- Do not create a second profile persistence mechanism.

## Dependencies

- `01-settings-visual-foundation`

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent when supported.
2. Capture the current Personalisation page before-state at the same route/state.
3. Map every reference control to an existing canonical field/action; document any unsupported visual-only item before implementing.
4. Build the three-column desktop composition using shared Settings primitives.
5. Rework Voice GPT Live controls into the large reference card; keep server/catalog option ownership and current preview behavior.
6. Rework personality controls into aligned slider rows with clear endpoint labels and current values; preserve accessible labels and keyboard operation.
7. Rework custom instructions into a bounded textarea with live character/validation state if currently supported.
8. Implement quick-preference cards as deterministic mappings over canonical personality fields; selecting a preset must visibly update the underlying controls rather than store divergent hidden state.
9. Rework profile selection into the reference top-right control/dropdown pattern with correct focus trapping/return and click-outside/Escape behavior.
10. Rework proactivity controls into full-width labeled rows with switches and plain-language descriptions.
11. Validate responsive layouts and long localized labels; prevent card overflow.
12. Capture final screenshots at 1672×941 plus a narrower desktop/tablet viewport and compare against the reference.

## Files Likely Touched

Resolve exact paths in Slice 00. Expect the Personalisation/voice/profile Settings renderer, related controller/view-model files, shared Settings CSS and focused frontend tests.

## Architecture Constraints

- One canonical writable home per setting.
- Presets project onto canonical fields; they are not a second settings database.
- Voice/provider catalogs stay server-owned.
- Profile and automation capability availability comes from live runtime state.

## Automated Validation

- All supported controls load current values and persist through existing APIs.
- Selecting a quick preset updates the canonical field values consistently.
- Profile dropdown is keyboard navigable and closes predictably.
- Slider/switch/select controls have visible focus and disabled states.
- No horizontal overflow at 1672×941, 1440×900 and a narrower supported viewport.
- Screenshot test covers the fully populated target state plus at least one unavailable/error state.

## Acceptance Criteria

- The page is immediately recognizable as the supplied Personalisation reference in hierarchy, spacing, panel treatment and accent usage.
- Three-column desktop balance matches the reference closely.
- All visible values are real or fixture-driven, not hard-coded demo data.
- Existing Personalisation functionality remains intact.

## Documentation Updates

Document the page composition, preset-to-field mapping and any capability-based omissions from the reference.

## Handoff Notes

The reference's exact copy is not the contract when runtime terminology differs; preserve the visual hierarchy while using canonical product language.
