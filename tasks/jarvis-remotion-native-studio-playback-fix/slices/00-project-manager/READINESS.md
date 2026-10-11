# Slice 00 — Readiness report

**Agent 0:** Project Manager (Claude Code, handle-task). **Date:** 2026-10-11.
**Status:** READY (with the planning repairs below).

## Declared state

- Task branch `task/jarvis-remotion-native-studio-playback-fix`, worktree `C:/Projects/jarvis/brn`.
  The main checkout `C:/Projects/jarvis/jarvis` stays on `main` because it runs the Human's live Jarvis.
- Base: `origin/main` = `d2332e61` = the handoff's reference SHA. Re-fetched on 2026-10-11 and unchanged.
  The task branch is `origin/main` plus `a8377529` (S0 handoff mirror: 67 files, sizes verified).
- The local `main` of the live checkout is `df642ce5`, 7 commits **behind** `origin/main`.
  It lacks the rail, the PRS dock removal and the chained-playback commits. The Human's screenshots may therefore show slightly older code than the task base.
- Overlap check: no branch ahead of `origin/main` touches presentation, Remotion, prefab host or scene page files. Checked: ephemeral-tasks, wake-word, session-context, memory-intelligence and the open `fix/*` branches.
- The concurrent IAsk session (peer `iask-20`) works in another repository, so there is no conflict.

## Blind audit

Full report: `blind-audit.md`, in this folder. It was written before reading the handoff's conclusions. Main facts:

- **Three transports:**
  - the stage page's own `rs-bar` (`control_center_remotion_stage.js:118-131`);
  - the floating band `#jvStudioBand` (`control_center_presentation_studio_player.js`);
  - the preview hosts' slide navigation.
  None reads a shared clock. The `rs-bar` scrub only seeks the sandboxed Player, and Core never hears about it. This explains defect D.
- **"8 s"** is the agent-authored score `target_duration_ms`. **"30 s"** is the scene's composition length.
  Nothing ties the two together. This explains defect E.
- **One composition per scene, swapped at each boundary.**
  - Seamless preload and take-over exist only for the run stage window, for `presentation-studio.*` pins, in `scene`/`all` scope.
  - The Explorer and window preview hosts remount on every slide change and loop freely. This explains defects B and C in Variants.
- **« Tout jouer »** in the Explorer starts a *manual* run. It passes no `scope`, which contradicts its tooltip.
- **Floating viewer:** the `studio-stage-<run_id>` Board window plus the band.
  - Its clients: brain/voice MCP (`presentation_play`, `presentation_view stage_fullscreen_enter`), the cue follower, the presenter, hot reload, scene-variant preview, the Tool Brain guard and `bind_playback`.
  - Slice 09 is therefore the riskiest removal.
- **Native Remotion Studio:**
  - It is reachable only from the MCP dialog card, not from the Presentation workspace.
  - Its edits are staged aside in `studio/edits/` and never persisted.
  - "Studio" is overloaded: the rail calls the Variant Explorer "Studio".
- **Doc vs code contradictions** (`presentation-studio.md`):
  - :2504 / :2367 promise "no remount";
  - :2466 promises "plays once" while the Player has `loop:true`;
  - :2506 promises "starts paused" while the stage page sends `play` on ready;
  - :2398 / :2429 describe the band out of date.

**Resolved by Slice 01 (`8410b752`, `../01-independent-intention-and-code-audit/AUDIT.md`):** the lower row is in no code, history, worktree or data on this host. Screenshot 2 was most likely taken on another machine, with player changes that were never pushed. The task builds on `origin/main` only, and Slice 03 reproduces on the task base. Agent 0 adopted Slice 01's recommendations: detours and aux windows render inside Variants; the rail shows only an indicator (no auto-open of Variants); the unpushed foreign work is out of scope and is reported to the Human.

**Original gap left for Slice 01:** screenshot 2's lower transport could not be located. It shows `|◀ ◀◀ ▶ ▶▶ ▶|`, `6/9 · 2 s / 8 s`, an « 8 s par slide » selector, loop, fullscreen and the hint « Espace lecture · F plein écran ».
- Its strings were searched for and not found in `jarvis/` at `d2332e61`, in the live checkout, or in `~/.jarvis`.
- Slice 01 must find its owner before Slices 04 and 10 design anything. Candidates: built or escaped strings, a prefab/scene module, or agent-authored deck content.

## Baseline tests (branch point `a8377529`)

Full detail: `baseline.md`. The whole `tests/unit` + `tests/integration` suite ran at `a8377529`: **21 343 passed, 94 failed, 0 errors, 95 skipped.**

- **16 fail every time, also when rerun in isolation. They are inherited and not this task's: implementers must not fix them.**
  - `test_app.py` (1)
  - `test_barehands_interaction_js.py` (2)
  - `test_brain_capability_parity.py` (1)
  - `test_brain_delegation.py` (1)
  - `test_control_center_voice_architecture.py` (1)
  - `test_interaction_mode_hud_browser.py` (1)
  - `test_scene_artifacts.py` (1)
  - `test_scene_query_tools.py` (1)
  - `test_scene_group_drag_js.py` (1)
  - `test_tool_brain_choices.py` (1)
  - `test_tool_brain_intents.py` (3)
  - `test_wake_word_settings_browser.py[cosmos]` (1)
  - `integration/test_settings_redesign_migration.py` (1)
- **None of the 16 is in the presentation or Remotion domain.** Any presentation or Remotion failure is therefore attributable to the current Slice.
- **78 pass in isolation:**
  - 77 come from one long chunk of `test_presentation_studio_reload*` / `scene_variants_crash`. Their child processes failed to start with exit code `0xC0000142`, which means Windows ran out of resources (environment).
  - 1 is the inspector browser test, which fails on timing under load.
  - **Gate rule:** run the presentation reload files on their own, one file per process. Never batch them into a long chunk.

## Reconciliation with the handoff

The handoff analysis (`docs/00-07`, slices) agrees with the audit. Corrections:

1. The handoff's hypotheses on the "8 s" and "30 s" owners are now confirmed with file:line (see above). Slice 03 still has to reproduce them at runtime.
2. The handoff's `docs/02-architecture.md` lists `control_center_presentation_window.js` as "separate presentation window".
   - It is a third preview host, with its own ◀ ▶ / strip / « Plein écran » / « Jouer ».
   - Slices 09/10 must treat it alongside the Explorer, not ignore it.
3. Screenshot 1 is the run stage window (`STUDIO_STAGE` = Board window category `studio_stage`) plus the band. It is not a separate product module.
   - "Removing the floating viewer" therefore means migrating the run stage to the Variants surface. It does not mean deleting a standalone file.

## Decisions taken by agent 0 (Human delegated autonomy)

- **Workspace Task Type:** the vocabulary does not exist in this repository. The gate is waived, as on the previous presentation tasks. Slices are assigned by role: implementer, QA, Plan.
- **End of video:** hold the final frame (the handoff's proposal; matches the current "holds its last image" contract).
- **Slice order:** the handoff's order is kept.
  - Slice 01 is narrowed to the gaps the blind audit left: the lower-transport owner, intent reconciliation, and the full client inventory of the floating viewer and the window host. It does not redo the audit.
  - Slices 02 and 03 may run in parallel after 01, because they touch different files (doc contract vs runtime reproduction).
- **Human-only gates kept:**
  - Drive folder moves (no move tool);
  - declared HV checks;
  - the trust/approval boundary for the Slice 12 native authoring workspace (an irreversible security decision; proposed, not taken);
  - Remotion licensing;
  - final acceptance and merge.

## Execution pipeline

- Implementer in `brn`. QA in the detached `brq` once the baseline frees it. Reworks on `fix/rnsp-sN-rework` branches.
- Foreground tests only, one file at a time (low RAM). Never touch the live Jarvis (Core `127.77.0.1:17653`).
- QA tiers follow the handoff's matrix:
  - `qa-verification` for every Slice;
  - `code-review` for code;
  - `runtime-validation` with real headless Chrome for UI and runtime;
  - `agent-trace-analysis` with real traces for Slice 13.
