# Jarvis Board UI — wheel, Board switcher and Dossier

## Purpose

Refactor the Jarvis Control Center so the UI matches the current product model instead of the older “interaction mode” model.

The central product change is simple but cross-cutting:

> A Board has a fixed **type** chosen at creation — **Assistant**, **Présentation** or **Réunion** — and Jarvis derives its behaviour from the active Board. The user no longer turns one Board from SIMPLE into PRESENTATION or REUNION from a separate mode selector.

The user-facing UI must then become quieter and more coherent:

- one compact Board switcher at bottom-left;
- one redesigned orbital wheel at the left edge;
- exactly five primary wheel categories: **JARVIS**, **Sélection**, **Dossier**, **Capture**, **Paramètres**;
- exactly one contextual second-level radial menu visible at a time;
- transient recording indicators only while capture is active;
- a new full-screen **Dossier** workspace for the Board's human-readable documentary context;
- explicit removal of obsolete permanent chrome instead of stacking new controls on top of the old ones.

This is primarily a **UI / UX refactor**, but the UI cannot be correct until the legacy mutable `InteractionMode` axis is reconciled with the fixed Board type contract. Slice 01 therefore precedes the visual work.

## Visual references

### `assets/style-reference-radial-ui.png` — style direction, not a literal spec

This is the preferred visual basis for the new wheel. It is intentionally **not** a pixel-perfect target and its information architecture is **not** authoritative.

Keep from it:

- the dark navy/black Jarvis visual language;
- the left-edge semi-circular / layered radial construction;
- thin luminous cyan strokes, restrained glow, dark translucent surfaces;
- a clear selected primary sector plus an attached contextual secondary layer;
- the sense that the wheel is an integrated system control rather than a generic web dropdown;
- the density, typography and restrained sci-fi/HUD character.

Do **not** copy from it blindly:

- it shows more than one expanded secondary panel at once — that is explicitly wrong;
- some labels/actions in the generated reference are obsolete (`Boards`, `Fichiers`, `Recherche`, `Outils`, etc.);
- its Board and runtime labels are illustrative only;
- it is not evidence for backend capabilities;
- decorative HUD elements must never reduce readability or steal working space.

**The wheel's graphic style must materially move toward this reference.** A functional change that leaves the old wheel looking essentially unchanged does not satisfy this task.

### `assets/current-ui-before.png` — removal / regression reference

This captures the UI before the requested refactor. It is used to verify what must disappear or move.

## Locked human intent

1. **Board type is fixed.** A Board does not switch between SIMPLE / PRESENTATION / REUNION. The Board is created as Assistant / Présentation / Réunion and Jarvis adapts to the active Board.
2. **The old interaction-mode selector disappears.** Remove the large `MODE D'INTERACTION` panel and the compact `MODE SIMPLE` control from the main UI.
3. **The old top-left Board selector disappears.** Board navigation moves to the bottom-left Board card.
4. **The `VOICE SLEEP • CLAUDE RUNNING`-style persistent badge disappears.** Runtime state belongs in the JARVIS wheel submenu and/or transient status cues, not permanent top-left chrome.
5. **The permanent hidden-object chip disappears.** Hidden objects are a temporary scene visibility state, not a storage area.
6. **Wheel primary categories are:** JARVIS / Sélection / Dossier / Capture / Paramètres. No first-level Recherche or Outils. No first-level Boards control.
7. **Only the selected wheel category exposes its submenu.** Never display two second-level menus at the same time.
8. **Capture is one category.** Screenshot, screen/video recording and audio recording are secondary actions. Audio and video may run simultaneously. Active recordings are indicated only while active.
9. **Dossier is the Board's documentary workspace.** It is shared between the human and Jarvis/agents, readable and editable by the human, and built on canonical Board memory/artifact data rather than a new silo.
10. **Board and Dossier are two views of the same work.** The Board is spatial/display-oriented; Dossier is durable/document-oriented.
11. **`Masquer` is temporary visibility. `Ranger` is durable organization + removal of the scene representation.** They are not aliases.
12. **The task-completion lifecycle idea is captured as a follow-up Issue, not silently folded into this UI task.**

See `docs/01-decision-log.md` and `docs/07-human-intent-audit.md` for the complete decision/audit record.

## What must be removed or replaced

The implementation is not complete if it only adds new components while leaving the obsolete ones in place.

| Existing / legacy UI | Required outcome |
| --- | --- |
| Top-left active Board selector / `#boardsHud` placement | Remove from top-left; reuse/refactor canonical Board switching into bottom-left Board card |
| Persistent state badge such as `VOICE SLEEP • CLAUDE RUNNING` / generic `.state` | Remove from permanent chrome; expose useful runtime truth contextually in JARVIS submenu or transient indicators |
| `MODE D'INTERACTION` selector | Remove |
| bottom-left `MODE SIMPLE` / `#interactionModeHud` | Remove |
| permanent `N objets masqués — afficher` / hidden-object toggle | Remove from permanent chrome; expose contextual show-hidden/cleanup actions |
| four first-level wheel slots `Sélection / Vidéo / Capture d'écran / Audio` | Replace by five primary categories `JARVIS / Sélection / Dossier / Capture / Paramètres` |
| global first-level `Recherche` | Do not add; search belongs to Jarvis conversation or within Dossier |
| global first-level `Outils` | Do not add as a catch-all |
| separate first-level `Fichiers` | Replace conceptually by `Dossier` |
| editable Board kind after creation | Remove from normal UI/API; type is immutable after creation |
| user-driven `/api/interaction-mode` mode switching | Retire from ordinary UI; reconcile as derived/compatibility runtime behaviour in Slice 01 |

Do not remove critical error/refusal/safety feedback merely because a generic status badge disappears.

## Existing architecture discovered at planning time

Planning reference: `main@cd5dfa47c53e6d8c7baa39892a5f0ffbe225bef5`.

Relevant owners at that revision:

- `docs/control-center-shell.md` — Level 3 shell geometry/layer contract.
- `jarvis/runtime/control_center_tool_wheel.js` — current retractable wheel with Mouse/keyboard/Bare Hands interaction and nested radial submenu mechanics.
- `jarvis/runtime/control_center_capture_wheel.js` + `control_center_capture_rail.js` — capture presentation/controller; Core remains capture truth.
- `jarvis/runtime/control_center_interaction_mode.js` — old bottom-left mutable mode selector to retire.
- `jarvis/runtime/control_center_boards.js` — current Board quick browser; its canonical switching behaviour should be retained while its placement/semantics change.
- `docs/boards.md` — current Board contract including `board_kind`, Board memory and mutable per-Board `interaction_mode`.
- `docs/interaction-mode.md` — current independent mode contract; directly conflicts with the new human intent and must be reconciled before visual work.
- `docs/scene-model.md` / `docs/scene-selection-batch.md` — canonical scene visibility, archive and atomic selection operations.
- `docs/capture.md` — Core `CaptureService` is the only status truth; UI must remain a projection.
- `jarvis/runtime/control_center_workspace.js` — existing deep technical Sessions/Boards/memory/artifact manager; useful source but **not** the target human-facing Dossier.

Slice 00 must re-audit current HEAD before dispatching anything. These pointers are planning evidence, not permission to ignore newer code.

**Slice 00 result (2026-10-17):** the audited owners, the BoardKind/InteractionMode migration plan, the orbital-ui S04-S10 deltas (eye, F9 hint, status centre, launcher) and the missing Dossier operations are in `docs/08-readiness-audit.md`, which supersedes the pointers above where they disagree.

## Target mental model

```text
ACTIVE BOARD (fixed type)
        |
        +--> Jarvis behaviour policy derived from Board type
        |
        +--> SCENE / BOARD VIEW
        |      spatial representations, tasks, artifacts, stars, windows
        |      visible <-> hidden; representation can be removed/archived
        |
        +--> DOSSIER VIEW
               durable organized documentary context
               Board memory + linked Artifacts + curated summaries/resources
               human-readable by default, advanced agent provenance/logs optional
```

`Ranger` is intentionally a composed operation:

```text
selected scene representation
    -> ensure durable Dossier backing exists / is linked
    -> preserve provenance
    -> remove/archive scene representation
```

`Masquer` remains only:

```text
scene visibility visible -> hidden
```

## Scope boundary: completed task lifecycle

The idea of replacing finished task cards with useful result summaries/notifications and archiving them in background is valuable but is a separate lifecycle feature. It is captured under `Issues/task-completion-lifecycle-follow-up.md` so it is not lost and so this UI refactor does not grow uncontrolled.

## Implementation entrypoint

Start with `slices/00-project-manager/SLICE.md`, then follow `slices/TODO.md`.

The Project Manager must not dispatch implementation until Slice 00 produces `READY`.

## Quality doctrine

Every implemented Slice runs `qa-verification`. Code changes also run `code-review`. User-visible/runtime behaviour runs `runtime-validation`. Changes to agent-visible Dossier/Board context, UI commands, routing or MCP surfaces additionally require `agent-trace-analysis` with real trace evidence. Frontend work loads `/impeccable`; code work loads `/caveman` and `/coding-guideline`. Use a Claude Work Agent for frontend work where the host supports it.

Human validation happens only after automated validation is maximized. A regression introduced by the current Slice is fixed in that Slice, not parked in `Issues/`.
