# Slice 09 — Presentation editing UX pass

## Goal
Perform the dedicated V1 editing pass so users can modify a generated Presentation confidently without understanding the internal scene/variant/Remotion model.

## Context
Jarvis already has semantic edit, variants, scene-local variants, preview, undo/history and Remotion source workflows. The user explicitly requested a later pass on editing after the broader Presentation product UI.

## Canonical Concepts
- Presentation Studio edit/history/variants contracts in `docs/presentation-studio.md`;
- scene-local variants and Remotion source/edit docs;
- internal document/export boundary from Slice 03;
- product UI structure from Slice 08.

## Scope
### In Scope
- audit and refine scene selection/edit entry points;
- semantic editing prompt/action flow;
- undo/history visibility where supported;
- variant creation/comparison/selection;
- media/image replacement and source clarity;
- preview/review loop after edits;
- explicit save/publish/export mental model without leaking internal persistence complexity;
- loading/error/conflict/recovery states;
- keyboard/accessibility and responsive layout.

### Out of Scope
- no new presentation engine architecture;
- no arbitrary code editor for end users unless current product requirements explicitly include it;
- no general filesystem browser.

## Dependencies
Hard `depends_on`: `03-internal-documents-and-export-boundary`, `08-presentation-product-ui`.

## Implementation Steps
1. Run a real editing journey against current main: generated deck -> change copy -> replace visual -> create variant -> compare -> undo -> preview -> export.
2. Record every point where internal terms, hidden state, stale previews or ambiguous save semantics make the journey unsafe/confusing.
3. Define the V1 editing interaction contract and state model for the UI.
4. Rework selection/inspector/edit controls to make the active scene/variant/source unambiguous.
5. Make edit submission/status/reload behavior honest: no optimistic confirmation before Core state is read back.
6. Integrate media replacement through bounded internal assets; never expose arbitrary filesystem write paths.
7. Make undo/history and variant operations recoverable and clearly scoped.
8. Ensure preview refresh and rendered result correspond to the edited canonical version.
9. Add browser/runtime tests and a Human review package with representative edit flows.

## Files Likely Touched
- Presentation Studio explorer/inspector/edit/variant/preview modules;
- related CSS and runtime routes only when needed;
- edit/variant browser tests;
- Presentation editing documentation.

## Architecture Constraints
- canonical edit state remains inside AppData Presentation storage;
- exported files are not edited in place as canonical source;
- UI must read authoritative state after mutation;
- preserve current safety/compile gates for Remotion source changes.

## Automated Validation
- browser tests for edit/variant/undo/preview flows;
- integration tests linking UI mutations to canonical Presentation state;
- conflict/reload/restart tests where current contracts support them;
- export-after-edit regression test.

## Acceptance Criteria
- a user can make common content/visual edits and understand what changed;
- active scene/variant is always clear;
- preview reflects authoritative edited state;
- undo/variant operations do not silently affect unrelated scenes;
- edited deck can be exported and reopened from internal canonical state.

## Documentation Updates
Update editing/variant/inspector docs and add V1 user-flow screenshots or states.

## Handoff Notes
Frontend coding Slice: `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent where supported. QA: `qa-verification`, `code-review`, `runtime-validation`.

## Slice 08 handoff (2026-10-26, I-006)
- In scope: in the `presentation` edition without developer mode, Variantes must not offer « Remotion Studio »
  (`control_center_presentation_studio_explorer_remotion.js:122,198`) nor send the user to the MCP dialog's
  « Plugins externes » tab (`:189`), which is hidden there. Declare the button `data-surface="developer"` (contract:
  `docs/control-center-shell.md` › *Product edition UI*) and give the message a product wording; add a browser test in
  `presentation` (hidden) and with `JARVIS_DEVELOPER_MODE=1` (shown).
