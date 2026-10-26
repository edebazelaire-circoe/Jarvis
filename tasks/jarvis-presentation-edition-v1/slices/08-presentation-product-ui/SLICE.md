# Slice 08 — Presentation Edition product UI

## Goal
Refine the distributed UI around the Presentation-only product journey so a new user understands what is available, what is incoming, how to create/open a Presentation Board, and how to move from sources to creation, preview, presenting and export.

## Context
The Control Center already has recent Settings visual refactors, Board card/navigation, Presentation Studio and many functional surfaces. This Slice is a product pass, not a wholesale visual rewrite.

## Canonical Concepts
- product availability from Slice 01;
- Board card/create flow: `jarvis/runtime/control_center_boards.js` and `docs/boards.md`;
- Presentation Studio/runtime docs and UI modules;
- onboarding/readiness from Slice 07;
- existing Settings visual foundation on `main`.

## Scope
### In Scope
- Board creation UI: Presentation available; Assistant and Meeting visible only as `Incoming/Bientot disponible` if kept visible, never actionable;
- remove/hide developer-only product surfaces from normal Presentation Edition navigation while preserving developer mode;
- Presentation home/workspace information architecture from Board -> sources/dossier -> create -> scenes -> preview -> present -> export;
- connector/readiness affordances where they support this journey;
- empty/loading/error/disabled states consistent with product policy;
- responsive/accessibility/focus behavior;
- visual review against current Settings/Control Center design system.

### Out of Scope
- no editing-detail redesign beyond navigation/seams owned by Slice 09;
- no new Meeting/Assistant functionality;
- no technical architecture/debug screen redesign for developer mode.

## Dependencies
Hard `depends_on`: `01-product-edition-and-board-lock`.
Soft `requires`: `07-installer-onboarding-health` for final onboarding/readiness surface integration.

## Implementation Steps
1. Audit the live Presentation journey and enumerate every user-visible branch that exposes unavailable/non-product capabilities.
2. Create/update a Presentation Edition UI contract with page states and navigation hierarchy.
3. Rework Board creation/selection to consume product availability, never duplicate it.
4. Apply `Incoming` treatment to Assistant/Meeting with accessible disabled semantics and no hidden API action.
5. Remove developer/debug-only controls from normal edition navigation; keep behind explicit developer mode where current architecture supports it.
6. Streamline the main Presentation workspace so sources, authoring, preview/presenter and export are discoverable without understanding Remotion/internal engine terms.
7. Integrate connector/readiness status only where it helps the user complete work; detailed diagnostics remain in Settings/health.
8. Add browser/runtime tests for navigation, focus, disabled states, error states and product-edition data binding.
9. Capture before/after reference screenshots for Human validation at representative viewport sizes.

## Files Likely Touched
- Control Center Board/product shell modules;
- Presentation Studio explorer/rail/run modules;
- Settings/readiness integration modules;
- related CSS/HTML/runtime tests;
- Presentation UI docs.

## Architecture Constraints
- UI consumes Core/product policy; it does not invent product availability;
- no optimistic success where Core is authoritative;
- no exposure of npm/MCP/CLI terminology in normal product copy;
- preserve developer mode/debug access separately.

## Automated Validation
- JS/unit/browser tests for Board availability and navigation;
- browser tests proving disabled Assistant/Meeting cannot create/switch;
- accessibility/focus checks;
- runtime smoke against real Control Center with Presentation Edition policy;
- screenshot comparison/review package for Human validation.

## Acceptance Criteria
- a first-time user can identify Presentation as the only available Board type;
- Assistant/Meeting read as future capabilities, not errors;
- the Presentation workflow is legible from source gathering through export;
- product UI contains no accidental developer-only route to forbidden capabilities.

## Documentation Updates
Update Control Center/Board/Presentation shell docs with edition-specific UI contract and screenshots/reference states.

## Handoff Notes
Frontend coding Slice: require `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent where supported. QA: `qa-verification`, `code-review`, `runtime-validation`.

## Slice 00 amendments (2026-10-26)
- Today the only "create a presentation" button lives in the "Présentations · moteur" card of the "Plugins externes" tab (`jarvis/runtime/control_center_presentation_studio_engine.js:279`). The product journey must not depend on it.
- The Board kind is chosen in the create row of `control_center_boards.js:82-123`.
- E11: `docs/settings/INDEX.md:78` still says "Brains & Architecture"; correct it if this Slice touches that page.
