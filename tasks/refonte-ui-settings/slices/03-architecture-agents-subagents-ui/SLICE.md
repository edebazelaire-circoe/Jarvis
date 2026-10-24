# Slice 03 — Architecture & Agents / Sous-agents UI refactor

## Goal

Refactor the **Sous-agents** view to the supplied dense-but-readable reference: overview metrics, delegation policy, role routing rows, routing matrix and global rules, all backed by live role/routing/model data.

## Context

Reference: `references/ui/02-architecture-agents-subagents.png`.

The current canonical Architecture & Agents implementation already owns role routing and related runtime semantics. This Slice is a visual/compositional refactor, not a replacement of those contracts.

## Canonical Concepts

- `REFERENCE.md`
- `docs/06-visual-contract.md`
- current canonical seven-role registry or whatever the live registry returns after Slice 00
- existing routing candidate/fallback/model catalog contracts
- `jarvis-architecture-agents-settings-editor` decisions

## Scope

### In Scope

- Header and `Architecture` / `Sous-agents` internal tab treatment consistent with the reference family.
- Overview metrics sourced from live state (active roles, providers/models, tools/capabilities, routing health where actually measurable).
- Delegation policy card with current supported global routing toggles/settings.
- Main role list/table with strong per-role identity, mission summary, preferred candidate/model, priority if canonical, fallback, tools/capabilities and usage conditions.
- Overflow/ellipsis action affordance for role-specific secondary actions when supported.
- Add/configure sub-agent affordances only if compatible with the canonical registry/instance model.
- Routing matrix or equivalent visual mapping using live task profiles/roles when that mapping is a supported concept.
- Global rules panel using actual supported constraints/settings.
- Loading, unavailable candidate, missing tool, degraded provider and mutation-error states.

### Out of Scope

- Do not reduce the canonical role registry to the five roles shown in the mockup.
- Do not restore a standalone `Brains` tab.
- Do not invent a fake "98% good delegation" metric if the runtime does not expose a meaningful equivalent.
- Do not reimplement routing persistence or model catalog ownership.

## Dependencies

- `01-settings-visual-foundation`

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent when supported.
2. Capture the current Sous-agents page before-state and inspect existing robust data/error/revision handling.
3. Build the top overview/policy region from real metrics/settings, omitting or relabeling unsupported illustrative metrics rather than fabricating them.
4. Recompose the role list into the reference row/card language with consistent column alignment and per-role accent identity.
5. Preserve live ordered candidate/fallback semantics; selectors must show availability/degradation accurately.
6. Render tools/capabilities compactly using icons/chips with accessible labels and overflow counts where needed.
7. Make conditions/mission copy concise in the dense table while keeping full detail accessible through existing detail/action patterns.
8. Build/refine the routing matrix using live role/task mapping; support horizontal compression/scroll only inside the matrix when necessary, not the whole page.
9. Recompose global rules into readable rows with trailing controls.
10. Verify the tab model matches the canonical current Architecture + Sous-agents contract even though the reference image contains an older Brains tab.
11. Validate long role names, provider/model strings, missing candidates and seven-or-more role rows.
12. Capture final 1254×1254 screenshot plus narrower viewport evidence.

## Files Likely Touched

Resolve exact paths during Slice 00. Likely current sub-agent Settings renderer/controller, role/routing UI module, shared Settings CSS and targeted UI tests.

## Architecture Constraints

- Canonical role registry is source of truth.
- Server/runtime model availability is source of truth.
- Existing optimistic revision/error semantics must survive the visual rewrite.
- Role count is dynamic.

## Automated Validation

- All live roles render; no role is dropped because the reference shows fewer rows.
- Candidate/fallback changes persist through existing APIs and surface errors.
- Unavailable models/tools show degraded/disabled states rather than disappearing silently.
- Matrix remains usable with canonical role/task counts.
- Keyboard navigation reaches row actions/selects and tabs.
- Screenshot test covers a populated state with the full canonical role registry.

## Acceptance Criteria

- The view visually matches the supplied Sous-agents reference in density, hierarchy and neon/glass treatment.
- No obsolete Brains tab is introduced.
- No illustrative metric or role count is hard-coded.
- Existing routing behavior remains correct.

## Documentation Updates

Document the live-data mapping for overview metrics and the intentional differences from illustrative mockup data.

## Handoff Notes

Visual fidelity includes density and alignment, not literal reproduction of stale sample values.
