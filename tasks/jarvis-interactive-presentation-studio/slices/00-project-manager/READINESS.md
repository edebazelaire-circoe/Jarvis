# Slice 00 - Readiness

**State: READY** (2026-10-07, Project Manager, agent 0).

## Declared state
Handoff mirrored from Drive `to-do` (folder 1Ym-uT3L-sKSZ4G4R47dtfxPjCD16HY_c): 81 files, sizes verified, JSON parses,
commit `0cb514d9`. Drive move `to-do` -> `current` is a Human action (the Drive connector has no move tool); pending.
Fallback recorded: the repo has no `docs/workflows/AGENT_TASK_LIFECYCLE.md` and no `dev` branch. Queue IDs and base branch
come from project memory: root 149pe77B1VcNH35eSms25EL7ALaDBW1RW; to-do 1pbNoTQ_nZKv3NVIe2ok-J6kplfnpmjmm;
current 1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D; done 16yBLZRVOEbfDAN_CRh5722bkN46IUmo7. Task branch
`task/jarvis-interactive-presentation-studio` created from `origin/main` 9721b3ca, worktree `C:/Projects/jarvis/bips`
(main checkout untouched: the Human's live Jarvis runs there).

## Blind audit
Done before reading the handoff docs (Explore agent, read-only). Findings and reconciliation: `docs/06-resolved-architecture.md`
(binding; wins over `docs/02-architecture.md`). Headline: foundation and Tool Brain are merged; no desktop host (browser
Fullscreen API, user gesture needed); ambient authority rule is enforced in three places and D09 needs a separate path;
`Artifact` vocabulary is taken; D23 holds with the repo's committed/ephemeral split.

## Task Types
Workspace Task Type vocabulary is not exposed in this environment. Gate waived under the standing Human waiver precedent
(four earlier tasks); every Slice keeps `task_type: null`. To be confirmed in passing at close-out, not a blocker.

## Dependency graph
23 Slices (00-22), no missing IDs, no cycles (checked by script). Cross-task dependencies evidence-backed: foundation merge
`0e199a77`, `docs/tool-brain-contracts.md` Level 3.

## Baseline (origin/main 9721b3ca, detached worktree `bipq`)
13736 passed, 10 failed, 0 errors, 40 skipped. Full detail: `BASELINE.md`. Failures present at the branch point,
**not ours, do not fix, do not mask**:
- test_barehands_interaction_js.py (2), test_control_center_voice_architecture.py (1), test_interaction_mode_hud_browser.py (1),
  test_scene_group_drag_js.py (1), test_app.py (1), test_brain_delegation.py (1),
  **test_tool_brain_intents.py (3)**: `BrainOrchestrator` has no `publish_ui_intent` though `server.py` calls it.
A failure outside this list is the current Slice's regression and is blocking.
Relevance: the last item means the `ui_intent_publish` channel (R7) is broken on main. Slice 01 must re-check it; Slice 21 may
only depend on it after it is repaired (add a repair Slice or Issue then; do not build on it silently).
Skips (40): symlink privilege, ffmpeg, axe-core, owner-voice model, POSIX/DPAPI, opt-in live tests.
Tests run foreground in chunks (low RAM); split integration+e2e in two (it exceeded 540 s).

## Plan repairs
See `docs/06-resolved-architecture.md` section 3. No Slice added, none removed. Slice 01 narrowed to confirm/complete R1-R10.

## QA tiers (by risk)
- critical (code-review + qa-verification + runtime-validation, mutations <=10): 02, 05, 06, 08, 13, 16.
- standard (qa-verification + code-review, runtime-validation where visible): 03, 04, 07, 09, 10, 11, 12, 14, 15, 17, 18, 19, 20.
- light: 01 (docs/audit), 21 (agent-trace-analysis required: tools/routing), 22 (release gate, wide sweep).
agent-trace-analysis additionally for 11, 13, 14, 21.

## Pipeline
Implementer in `bips`; QA in detached `bipq`; reworks on `fix/ips-sN-rework` branches in a QA worktree, cherry-picked when
`bips` is idle. One implementer per worktree, no `git stash`, foreground tests only, no Monitor in sub-agent prompts.
Freshness check (`git fetch`, `rev-list --left-right --count origin/main...HEAD`) before each dispatch and before close-out.
