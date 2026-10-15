# 03 - Implementation strategy

## Strategy

Do not attempt a single CSS rewrite. The current UI has multiple state owners and overlay contracts. Migrate in slices so every step can be independently validated and rolled back.

## Phase 0 - readiness and contract reconciliation

Slice 00 performs a blind audit before reading implementation prescriptions. It verifies HEAD, adjacent in-flight tasks, canonical contracts, current selectors/IDs, test coverage, and whether any recently landed code already changes these surfaces.

The PM then reconciles this handoff with reality. If a conflict exists, update the handoff first; do not code against stale assumptions.

## Phase 1 - define the new shell contract

Create/extend a canonical Control Center UI contract for:

- left wheel geometry/open-close/input semantics;
- bottom status center semantics;
- right active workspace rail semantics;
- bottom-left context zone;
- global chrome information architecture;
- z-index/layer map;
- accessibility requirements.

This prevents later slices from inventing incompatible local conventions.

## Phase 2 - build the wheel shell without moving domain behavior yet

Implement the wheel component and its anchor, keyboard behavior, reveal/retract animation, reduced-motion behavior and Bare Hands reveal seam. Initially wire Selection only or stub domain callbacks through injected interfaces in tests. Do not move capture ownership yet.

Acceptance: the wheel can be driven with Mouse, keyboard and Bare Hands event input, and the rest of the page is unaffected.

## Phase 3 - selection arbitration

Connect Selection to canonical Mouse/Bare Hands control. Remove extra selection choices from this surface. Implement deliberate Mouse takeover and explicit-only Bare Hands return. Add the redesigned Bare Hands icon.

Acceptance: no flapping on micro movement, click takeover immediate, explicit return reliable.

## Phase 4 - migrate capture controls

Refactor the capture rail controller so it can render into the wheel and persistent indicator without creating new state ownership. Preserve status polling, write/re-read and error semantics.

Acceptance: Audio/Video can start/stop, Screenshot captures, active state survives wheel closure/reload behavior exactly as canonical status allows.

## Phase 5 - screenshot preview

Add the non-blocking preview after successful Screenshot. Wire only real actions. Validate auto-dismiss and failure isolation.

## Phase 6 - bottom status center + eye toggle

Relocate background pills to bottom center and preserve popover/category behavior. Remove the visual F9 hint. Add eye toggle over canonical scene visibility. Add active recording indicators adjacent to bottom center.

## Phase 7 - right active workspace rail

Move the presentation rail to the right and rebuild cards with type recognition and previews. Preserve context actions and Studio integration. Then add additional Board-linked artifacts only through a documented adapter/model.

This phase is intentionally after capture because new captures may become useful workspace items; do not create circular dependencies in UI state.

## Phase 8 - global chrome simplification + context zone

Audit every current right dock/topbar tool. Define destination for each:

- permanent compact top icon;
- grouped global launcher;
- keyboard/voice-only secondary access *only if there is still a visible discoverable path*;
- bottom-left context zone;
- removed only if proven obsolete and approved.

Recompose Board access around the bottom-left context zone without merging canonical state owners.

## Phase 9 - integration, responsive, layering and accessibility

Once the pieces exist, run the whole shell against:

- standard Board;
- presentation mode;
- Variantes/Studio open;
- modal/Settings/full-screen tools;
- small/short viewport;
- Mouse only;
- keyboard only;
- Bare Hands active;
- active Audio/Video capture;
- capture status loss;
- notifications open;
- hidden-object toggle state.

## Visual implementation details

### Wheel geometry

- Keep the center of the circle outside/near the left screen edge so only a semi-circle is visible.
- Four primary items should have generous angular separation for hand pointing.
- Selection may open a second compact inner/outer arc containing Mouse/Bare Hands, not a rectangular dropdown that breaks the radial metaphor.
- Label appears adjacent to the currently focused wedge only; do not label every wedge permanently.
- At rest only anchor/core is visible.

### Motion

- Reveal/retract should be fast and physically coherent (radial expansion + opacity), not bouncy.
- Hover focus should not move item geometry.
- Recording start uses a clear state transition, not an indefinite decorative pulse.
- `prefers-reduced-motion` disables nonessential movement while preserving visibility/state.

### Rail cards

- Cards are wider than the old 158px presentation rail so a preview can be meaningful.
- Preview should preserve aspect ratio; presentation previews favor 16:9/slide-like frame.
- Video preview overlays a play glyph/type marker.
- Type badge/icon should be secondary to preview and title.
- Status dot/pill appears in a stable card corner and never replaces text state for accessibility.
- On hover/focus, show context menu affordance; do not fill the card with persistent buttons.

### Bottom status center

- Horizontal capsule or grouped icon buttons, centered a little above bottom edge.
- Each category: icon + compact count badge.
- Alert uses orange; complete uses green; pending question uses cyan/blue or product-defined semantic color.
- Eye toggle sits just to the right of the category group or in the same baseline, separated visually.
- Active capture indicator may sit next to the group with explicit `REC`/audio label + timer.

## Rollback strategy

Keep refactors separable:

- wheel can be disabled and old palette/capture rail restored until capture migration is complete;
- notification rendering can revert to `.bgpills` data presentation without changing the source model;
- right rail can fall back to old card renderer while keeping the new placement data adapter;
- no schema migration should be required merely for visual recomposition.

Any new persistence for `changed/unreviewed` must be isolated and versioned only if truly necessary, with an explicit migration and rollback plan.
