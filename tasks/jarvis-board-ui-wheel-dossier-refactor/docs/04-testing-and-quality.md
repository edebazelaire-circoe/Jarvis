# 04 — Testing and quality

## Mandatory QA chain

Every implemented Slice:

1. implementation's focused tests;
2. `qa-verification`;
3. `code-review` for code changes;
4. `runtime-validation` for user-visible/runtime behaviour;
5. `agent-trace-analysis` when the Slice changes agent-visible Board/Dossier context, tool routing, MCP commands, UI commands, or agent/runtime orchestration;
6. Project Manager decides pass/rework from evidence;
7. human validation only after machine validation is maximized.

A defect introduced by the current Slice is repaired in the current Slice. It is not moved to `Issues/` merely to make the Slice appear complete.

## Isolation

Runtime/browser/E2E tests must use an isolated Jarvis instance/worktree/data root unless the human explicitly authorizes the live instance. Do not stop/restart the user's active Jarvis process as a side effect of validation.

## Required regression families

Slice 00 re-resolves exact test names at HEAD. Planning-time families include:

- shell/layer registry and responsive browser tests;
- orbital tool-wheel pure reducer + browser tests;
- Board domain/store/service/protocol/switch tests;
- interaction-mode contract/control-plane tests while migration is in progress;
- Board HUD browser/status tests (to be replaced/updated with bottom-left switcher tests);
- capture rail/controller/wheel/browser tests;
- scene selection/batch/domain/MCP tests;
- Workspace inspection/memory/artifact tests;
- Board/Session E2E tests;
- agent/MCP catalog and trace tests for new Dossier commands.

## Board type migration matrix

At minimum test persisted old payloads:

| Legacy state | Expected normalized type |
| --- | --- |
| explicit `board_kind=presentation` | Présentation |
| explicit `board_kind=meeting` | Réunion |
| `empty` + explicit Presentation interaction preference | Présentation |
| `empty` + explicit Meeting interaction preference | Réunion |
| `empty` / missing + no explicit non-default preference | Assistant |
| new Board | selected type, immutable afterward |

Test that a user cannot independently change product behaviour mode after creation. Test that Board switching still preserves one speech authority and does not cancel background work.

## UI deletion assertions

Browser/DOM tests should explicitly assert absence, not merely ignore obsolete UI:

- no old interaction-mode launcher/chooser in ordinary shell;
- no duplicate top-left Board selector;
- no permanent hidden-object count/toggle;
- no permanent `VOICE … RUNNING` state badge matching the retired UI role;
- no first-level wheel slots Video/Screenshot/Audio;
- no first-level Recherche/Outils/Fichiers/Boards slots;
- no editable Board type in ordinary edit flow.

## Wheel behaviour matrix

Inputs:

- mouse/pointer;
- keyboard;
- Bare Hands synthesized pointer/click where available.

States:

- closed anchor;
- open with no selected second level;
- each primary category focused/activated;
- submenu replacement when another category is selected;
- escape/back/outside close;
- reduced motion;
- unavailable action / status unknown.

Critical invariant: **at most one second-level menu subtree is visible.**

## Capture matrix

- screenshot while idle;
- audio start/stop;
- screen/video start/stop;
- audio + video concurrently;
- multiple devices/targets if Core advertises them;
- status lost / Core unavailable;
- failed start;
- reload while capture active;
- active indicator timer derives from Core activation timestamp, not click time;
- stop available from transient indicator;
- no Pause control unless Core has a canonical pause state/API at implementation time.

## Dossier semantics matrix

- Board memory document appears once and opens;
- linked Artifact appears with provenance and preview;
- Ranger on an already durable artifact archives/removes representation only after link/view confirmation;
- Ranger on an ephemeral content object materializes once then removes representation;
- Ranger refusal leaves representation visible if durability did not complete;
- Masquer never creates a Dossier entry;
- Show hidden changes scene visibility only;
- Present from Dossier creates a representation pointing to the same durable source;
- edit/correction is visible to subsequent canonical Board-context retrieval;
- archived Board Dossier remains readable according to existing archive rules and writes remain refused if current contract says so;
- advanced agent/log/provenance details are not forced into default human view.

## Accessibility

- logical tab order;
- visible focus in wheel and Dossier;
- keyboard parity for every clickable primary action;
- semantic labels for icon-only controls;
- screen reader announces selected Board type/title and recording state;
- no essential state encoded by colour/glow alone;
- reduced motion disables ornamental sweep/rotation/pulsing while retaining active state;
- minimum pointer targets consistent with current shell contract;
- full-screen Dossier owns focus while open and restores it on close.

## Visual acceptance

The generated style reference is evaluated qualitatively, not by pixel diff. Human acceptance should answer:

- Does the wheel clearly feel redesigned toward the reference rather than cosmetically patched?
- Is the selected sector obvious without excessive glow?
- Is the submenu visually attached to the selected sector and alone?
- Is the Board switcher unobtrusive when closed?
- Does Dossier feel like a serious full-screen working environment, not a debug file tree?
- Has permanent clutter actually decreased?
