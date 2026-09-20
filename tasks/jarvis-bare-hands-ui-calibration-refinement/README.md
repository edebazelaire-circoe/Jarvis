# Jarvis — Bare Hands UI & Calibration Refinement

## Purpose

Refine the already-implemented Bare Hands V1 experience in Jarvis so that its controls are first-class, fast to reach, and visually coherent with the main Control Center. This task does **not** redesign the underlying hand-tracking or interaction model: it corrects the access hierarchy, moves existing tools out of Settings, replaces the dense calibration modal with a full-screen guided experience, and folds the separate tutorial into calibration.

This handoff comes from the 2026-09-20 UI review/grill session plus a fresh repository review of `edebazelaire-circoe/Jarvis` on `main` at commit `a949f40c16c4a61fc563e7d7cdf1c32da913c207`.

The previous implementation handoff remains the behavioral baseline:

- Drive: `Jarvis/task/to-do/jarvis-bare-hands-v1/`
- Repository canonical contract: `docs/barehands-contracts.md`

The central rule for this refinement is:

> **Do not redefine Bare Hands interaction semantics here. Make the existing capabilities reachable and understandable.**

## Project identity and destination

- Project: **Jarvis**
- Repository: `https://github.com/edebazelaire-circoe/Jarvis`
- Reviewed main SHA: `a949f40c16c4a61fc563e7d7cdf1c32da913c207`
- Queue: `Jarvis/task/to-do/jarvis-bare-hands-ui-calibration-refinement/`
- Existing current implementation includes lifecycle, stable tracking, gestures, target resolution, interaction/capture, tools/settings, calibration, a separate tutorial, diagnostic recording/replay, and a voice/MCP command channel.

## Locked product corrections

### First-class Bare Hands control

Bare Hands must no longer be primarily controlled through `Settings -> Experimental`.

Add a dedicated square Bare Hands button to the main HUD, near the upper-left status area indicated during the review, using the same visual language as the other main action buttons but slightly larger. The icon is a hand.

Visual states:

- **OFF**: strongly dimmed/greyed; camera is actually released and C-wake cannot activate it.
- **SLEEP**: normal Jarvis blue, no special glow; camera watcher is armed and C-wake may activate.
- **ACTIVE**: brighter electric blue with a subtle glow/highlight; do **not** use green for the active state.

A normal click opens a compact **visual state chooser**, not a text dropdown. It presents the same hand-button representation in the three selectable states `OFF`, `SLEEP`, `ACTIVE`, allowing direct selection.

The button is a projection of the actual Bare Hands state, never a local UI toggle. It must update when state changes through any path: direct UI selection, voice/MCP command, C-wake, inactivity returning ACTIVE to SLEEP, shutdown/error recovery, or settings/profile reload.

### Right-click menu

Right-click on the Bare Hands button opens a compact context menu containing:

- `Settings`
- `Calibration`
- `Help / Gestures`
- `Diagnostics`

There is no “Activate Bare Hands” item because mode selection belongs to the normal click/state chooser. There is no separate `Tutorial` item.

### Fast tool palette

The existing V1 tools are removed from Settings and surfaced as a fixed vertical palette on the left side of the main screen, analogous to a small Paint/Photoshop tool strip.

V1 must expose **only the already-installed tools**:

- `pointer`
- `pan`
- `select`

Do not add highlighter, draw, eraser, or any new tool in this task. Use icons, one-click selection, and a clear active-tool state. The palette is fixed and vertical in this refinement; drag/dock/horizontal customization is explicitly deferred.

### Settings becomes configuration only

The Bare Hands settings surface should contain persistent/system configuration, not session actions.

Remove or stop presenting as primary Settings controls:

- the master activation UI (OFF/SLEEP/ACTIVE is now the main HUD button);
- the Tools section;
- the separate Tutorial section/entry.

Keep the existing backend/state mechanisms where needed for compatibility, but the user-facing information architecture must make the distinction clear: **HUD state selector = lifecycle, tool palette = current intent, Settings = configuration**.

### Help / Gestures pop-up

`Help / Gestures` opens a small window/card, not a long raw text section in Settings. It should be airy, visually organized, and use simple hand-position icons/mini diagrams. It may show lifecycle meaning, primary/secondary pinch, C wake, feedback colors, and current supported gestures/actions, but it must derive truth from the canonical Bare Hands contracts. Do not imply that recognized-but-unbound gestures perform actions.

### Diagnostics entry

`Diagnostics` from the right-click menu exposes the already-implemented diagnostic recorder/replay surface. Reuse existing behavior; this task changes discoverability/presentation, not diagnostic semantics or retention policy.

### Calibration replaces the separate tutorial

There is no longer a separate user-facing Tutorial flow. Calibration is both measurement and guided learning.

The existing `control_center_barehands_tutorial.js` flow must cease to be a distinct product surface. A legacy `tutorial` command may remain only as a compatibility alias to Calibration if that is the safest current-contract migration; it must never open a second competing flow.

### Calibration visual direction

The existing centered modal/card is rejected.

Calibration becomes a **full-screen overlay experience**:

- the current Jarvis scene remains visible behind a darker, more strongly blurred veil;
- no central modal/window container;
- step number, large title, and one short sentence occupy the upper area;
- the center of the screen is reserved for the demonstration/test itself;
- progress remains visible but visually light;
- controls such as Skip/Quit/Close are secondary and do not compete with the exercise;
- the virtual hand is simple schematic/robotic line art, not a realistic anatomical hand;
- success feedback may turn green briefly, while normal guidance remains Jarvis blue.

### Calibration timing / arming

An exercise must not begin simply because the step screen appeared.

Each step has an intro/reading phase lasting a few seconds. After this minimum reading time:

- gesture/posture steps become **armed** and begin measuring only once user hand activity/intent is detected;
- if the user leaves their hands on their lap and does nothing, the instruction remains and no measurement timeout burns down;
- target exercises reveal the first target after the reading delay so the user has something to act on;
- window manipulation reveals the practice frame after the reading delay and begins when the user actually engages a valid handle.

The existing stage timeout/watchdog should apply to the active exercise phase, not to the initial reading phase.

### Calibration sequence

Use this seven-screen sequence:

1. **Main au repos** — open hand, natural stillness/jitter.
2. **Posture de réveil** — the C is specifically formed by thumb and index; keep the virtual illustration simple and unambiguous.
3. **Pincement pouce-index** — demonstrate and measure primary pinch/release; repeat as currently required.
4. **Pincement pouce-majeur** — same visual grammar as step 3 but with the middle finger; secondary/right-click pinch.
5. **Viser et cliquer** — targets appear across the usable screen area; the demonstration must visibly use a thumb-index pinch, not a pointing finger. This is the spatial targeting exercise.
6. **Manipulation de fenêtre** — one step with multiple sub-steps:
   - **6A Déplacer**: capture one edge/corner of a practice Jarvis frame with one hand and move the whole frame;
   - **6B Redimensionner**: capture two different compatible edges/corners with two hands and enlarge/reduce the frame.
   The practice frame should visually and behaviorally match the real Jarvis frame/window interaction, using the same target/capture/geometry engine rather than a fake drag toy.
7. **Calibration terminée** — summarize what was successfully calibrated and what fell back to defaults; offer the natural exit/use action and recalibration if needed.

Step 6 replaces the current separate generic `DRAG` and `RESIZE` exercises. It may still feed the existing click-vs-drag calibration metrics where technically appropriate, but the user-facing task is real Jarvis window manipulation.

## Explicit non-goals

- Do not redefine the already-agreed contextual interaction matrix (button, scrollable text, star drag, frame BODY, frame zones, bimanual constraints).
- Do not add new tools.
- Do not add new global hand gestures or bind currently-unbound gestures to actions.
- Do not change MediaPipe, tracking algorithms, pinch math, target-resolution math, or bimanual geometry unless required to connect the new UI safely.
- Do not redesign the Constellation frame visual language globally in this task beyond what the calibration practice frame must reuse.
- Do not reintroduce a separate Tutorial surface.

## How the Project Manager starts

1. Open `slices/TODO.md`.
2. Execute Slice `00-project-manager` personally; do not delegate it.
3. Perform the blind repository/context audit required by Slice 00 before relying on this handoff.
4. Reconcile this refinement against the current `docs/barehands-contracts.md`, current tests, and the prior `jarvis-bare-hands-v1` handoff.
5. Resolve the current Workspace Task Type vocabulary before any implementation Slice dispatch.
6. Reach `READY` before implementation dispatch.
7. Run a targeted freshness check immediately before every Slice.

## QA doctrine

Every implemented Slice receives a baseline `qa-verification` pass. Code changes also receive `code-review`. User-visible or runtime behavior also receives `runtime-validation`. Changes to agent prompts, MCP tools, routing, command modules, or agent runtime also require `agent-trace-analysis` with real trace evidence. QA agents return evidence/findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.

A regression caused by the current Slice is blocking and cannot be parked in `Issues/`. Human validation never substitutes for QA; maximize machine validation first.

## Required implementation skills

All coding Slices require `/caveman` and `/coding-guideline`. Frontend/browser Slices additionally require `/impeccable` and should route to a Claude agent when the host supports that routing rule.
