# Slice 05 — Runtime validation (page view of the live brain turns)

HEAD `f2d706e`, 2026-09-25. No source modified. Companion to `agent-trace-analysis.md`, which ran the same 7 brain turns.

**Verdict: CONCERNS.** Every brain action produced exactly one coherent scene transition. One residual defect: after a brain `scene_move` to the edge, an orbiting member goes partly off-screen (the D1 gap, now reached through MCP).

## Environment

- Isolated Core `127.77.0.1:17683` and Control Center `127.0.0.1:17685`, started from this worktree (`trace-evidence/env.sh`, `start.sh`). Data and runtime were in the scratchpad. There is a port guard against empty, 17653 and 17654. The live Jarvis was untouched.
- **Side effects suppressed, with no source change:**
  - The browser tab: the CC ran through `python -c "import webbrowser; webbrowser.open=lambda *a,**k: True; runpy.run_module('jarvis')" control-center`. The `BROWSER` env var does not work because a failing `GenericBrowser` falls back to `windows-default`.
  - The auto-spawned `claude.exe`: `JARVIS_CLAUDE_CLI=__qa_no_brain_claude__`. The CC logs `agent.unavailable` ("Claude CLI not found", 2 ERR badges on the page) and keeps running.
- Page: headless Chrome 153 (fresh profile, 1280×720) over CDP (`trace-evidence/cdp.py`). The Claude-in-Chrome extension was not used. A 200 ms sampler recorded every `.sc-node[data-object-id]` rect, with a console error/warn mirror (`page-analysis.txt`).
- Everything started was stopped at the end: Core, CC, Chrome, tail. Other pre-existing Jarvis instances (17664, from 24/09) were left alone.

## Results

| Turn | Brain action | Rev Δ (Core) | Page transition | Result |
|---|---|---|---|---|
| T1 hide constellation | `scene_update_many` constellation → hidden | +1 | **one** rendered-set change: orion, budget, equipe, planning gone together (risques already hidden). Badge « 5 objets masqués ». | PASS. `screenshots/t1-before.png`, `t1-after.png` |
| T2 show all | `scene_update_many` hidden → visible | +1 | one change: 5 members back together | PASS. `t2-after.png` |
| T3 move left | `scene_move` dx −30 → effective −12, clamped | +1 | no appear/disappear. Stored geometry of all 5 members shifted by exactly −12 (orion −130→−142, budget −140→−152, equipe/risques −80→−92, planning −100→−112): the group moved rigidly, and `placed_by` became `brain` | PASS, with D-S5-1 below. `t3-before.png`, `t3-after.png` |
| T4 archive finished stars | `scene_archive` completed agents | +1 | one change: the 3 completed stars gone together, the running star stays | PASS. `t4-after.png` |
| T5 unpin all | `scene_pin` 2 ids, unpin | +1 | no visual change expected (pin icon only) | PASS |
| T6 unknown object | none | 0 | none | PASS |
| T7 archive idees (+ unknown) | `scene_archive` [idees] | +1 | one change: idees gone | PASS. `t7-after.png` |

The page did not send a single scene command during the brain turns. No console errors or warnings came from the page. The ERR badge shows only the two intentional "Claude CLI not found" entries.

## Defect

**D-S5-1 — Orbiting member partly off-screen after a brain `scene_move` to the edge (the Slice 03 D1 gap, now reached through MCP).** Severity: minor to medium (UX).
- Core `group_clamp` bounds a `translate_selection` to `SCENE_SAFE_AREA` only (amendment §5.2). The page's `orbitGroupDelta` fix protects **user drags** only.
- After T3, `orion-budget` sits exactly on the safe-area edge (x = −152). Its orbit then leaves the 1280×720 viewport:
  - It is partly off-screen in **191 of 1 073 samples (18 %) over 214 s**, by up to **7 px** (x −7…1287, y −3…723). It is never fully off-screen.
  - Before the move, the same object stayed on-screen in 884 of 884 samples (x 55…1242, y 24…696).
  - The screenshot `screenshots/t3-orbit-offscreen.png` shows « Budget Orion » clipped at the left edge and running under the pointer dock.
  - Pinning does not change the orbit: `courses` had identical extents pinned and unpinned.
- Repro: seed a linked group near the left edge (member at x −140), then ask the brain « déplace cette constellation un peu vers la gauche ». Core returns `clamped:true`, effective −12. Sample the member's rect for 1–2 minutes.
- For the PM to decide: bound the Core group clamp by orbit fit too, as the page's `orbitGroupDelta` does, or accept it and document it for brain moves.

## Not verified

- Claude-in-Chrome in the user's real browser (headless Chrome was used). The Theme/Cosmos variants and other viewport sizes.
- Rigid motion *on screen* frame by frame. Orbits move every member continuously and with different radii, so rigidity was checked through the stored geometry (a uniform −12 on all 5 members) and the single revision, not through pixel offsets.
- A transition finer than the 200 ms sampling interval. Each turn showed exactly one set change at that granularity.
