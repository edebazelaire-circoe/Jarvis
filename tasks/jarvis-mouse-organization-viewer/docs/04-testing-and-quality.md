# 04 - Testing and Quality

## QA doctrine

Every implemented Slice receives `qa-verification`. Every code Slice receives `code-review`. Every user-visible/runtime Slice receives `runtime-validation`. If a Slice changes agent prompts, routing, provider adapters or agent runtime, also run `agent-trace-analysis` on real traces.

A regression introduced by the current Slice blocks approval and cannot be parked in `Issues/`.

Do not run the full repository unit/integration/E2E suite in each Slice. Use focused tests in Slices 01-05. The complete suite runs once in Slice 06 after convergence.

## Focused test matrix

### Pointer resize

- each of 4 edges;
- each of 4 corners;
- min/max bounds;
- viewport/control collision bounds;
- Shift pressed before resize;
- Shift pressed mid-resize;
- Shift released mid-resize;
- no geometry jump on rebase;
- selected/group drag remains unaffected;
- Bare Hands side-based resize remains unchanged.

### Selection/context menu

- right-click selected member preserves N-item selection;
- right-click unselected member selects only it;
- Ctrl/Cmd-click still toggles;
- selection band still works across windows/prefabs;
- context-menu keyboard path (Menu / Shift+F10) preserves keyboard-composed selection.

### Atomic organization

- one user action -> one command -> at most one scene revision;
- no partial layout on one invalid member;
- deterministic box results;
- custom grids at representative sizes including 3x8;
- align/distribute/same-size edge cases;
- group clamping without relative-layout corruption;
- stale undo refuses rather than overwriting newer geometry.

### Viewer

- single image;
- five-image comparison;
- document scroll;
- image zoom/pan;
- all layout presets;
- custom grid;
- open by double-click, Enter and context menu;
- mixed-selection degradation notice;
- Escape and close button;
- focus trap and focus restore;
- reduced motion;
- Board snapshot/geometry unchanged after open/layout/close;
- prefab iframe pointer/focus behavior remains safe;
- no collision with presentation/fullscreen overlays.

### Agent viewer

- running agent with mission + progress;
- running agent without progress fraction;
- no published plan;
- child work available;
- completed / failed / cancelled / interrupted;
- missing Work State after restart but durable Mission History present -> live state unknown, never guessed;
- related artifacts;
- Stop success/refusal;
- Ask through canonical route/fallback;
- no raw prompt, trace or private reasoning fields in response/UI.

## Accessibility

- complete keyboard path;
- visible focus;
- semantic buttons/menu roles;
- no information conveyed only by color;
- viewer content remains readable at 200 percent zoom;
- Escape and focus restoration tested;
- screen-reader announcements for skipped viewer items and refused actions.

## Performance

- layout planning must remain bounded by scene object limits;
- viewer should lazy-load heavy content where practical;
- image zoom/pan should not trigger whole-scene rerenders;
- agent status refresh uses existing bounded polling/event mechanisms rather than a new high-frequency loop.

## Final convergence suite

Slice 06 runs the full Jarvis unit/integration/E2E suite once, plus targeted browser/runtime scenarios for the new feature. It also checks task-overlap regressions against current presentation, prefab and chat work.

