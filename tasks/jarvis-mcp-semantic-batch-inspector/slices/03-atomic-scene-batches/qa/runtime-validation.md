# Slice 03 — runtime validation (atomic scene batches / page group drag)

HEAD `e0dd185`, branch `task/jarvis-mcp-semantic-batch-inspector`, 2026-09-25. No source modified.

## Environment

- Isolated Core + Control Center started from this worktree (`.venv/Scripts/python.exe -m jarvis core` / `control-center`),
  `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` under the session scratchpad (fresh scene, revision 0),
  `JARVIS_CORE_PORT=17683`, `JARVIS_UI_PORT=17685`, `JARVIS_SCENE_ENABLED=1`, `JARVIS_VISUALIZER_ENABLED=0`.
  The user's live Jarvis (17653/17654) was not touched.
- The Claude-in-Chrome extension was **not connected**. Fallback: headless Chrome (fresh profile) driven over the
  DevTools protocol — real page, real `Input.dispatchMouseEvent` pointer events (click, ctrl-click, drag).
  Page instrumentation injected via `Runtime.evaluate` only: a `fetch` wrapper recording `POST /api/scene/commands`
  bodies/responses, a console mirror, a rAF sampler of node `transform`s. Revisions read from `GET /api/scene`.
- Side effect: `webbrowser.open` also opened `http://127.0.0.1:17685/` in the user's default browser
  (the `BROWSER` override did not suppress it). That tab acted as a second scene page (it committed some resolver
  placements, see check 5). It now points at a stopped instance and can be closed.
- The Control Center also started a `claude.exe` agent process at launch (the page shows "CLAUDE RUNNING"). It was killed with the instance.
- Seed (as `user`): a1..a4 capsules (a3 pinned), h1 hidden, u1 unplaced, w1 window; links a1→a2, a1→a3, a4→a1 (explains), a1→h1.
  Everything orbits except w1. Page-side the resolver places u1 within about 0.7 s (placed_by=resolver).

## Results

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Select ≥3 placed (incl. pinned) + drag → one `translate_selection`, revision +1 | PASS | select a1, ctrl-click a2 a3(pinned) a4, drag +80,+40 px → exactly one POST `{"op":"translate_selection","selection":{"ids":["a1","a2","a3","a4"]},"delta":{"dx":19.9,"dy":10},"pin":true}`; revision 14→15; all 4 pinned. Hidden h1 is not rendered, so the page cannot select it (by design). The hidden member was covered through HTTP instead (check 9). `logs/c1-*.txt` |
| 2 | Offsets preserved, no jump back | PASS | offsets identical before/after (40/30 units). rAF sampling from press to 4.7 s after release: transforms go monotonically to the target and stay there, with no return to the old place. `logs/c2-samples.txt` |
| 3 | Hard drag against an edge: the group stops together | PASS | drag −900,−500 px → delta clamped by the page to (−66.9, −49.5); a1 lands exactly on the safe-area corner (−152, −72), offsets intact, rev 16→17. `03-after-edge-drag.png`. (Core reports `clamped:false` because the page already sent the clamped delta.) |
| 4 | Orbiting members re-seat after drop | PASS, with a defect (D1) | `--sc-orbit-*` / `animation-delay` recomputed per member after the drop (`logs/c4-orbit-*.txt`). See D1: at the edge the members orbit **off-screen**. |
| 5 | Unplaced carried object snaps back + console line | PASS | race script: create u5, ctrl-click it into {a2,a4} and drag within 0.45 s (before resolver commit). POST ids `["a2","a4"]` only (rev 27). Console: `scene.user_drag_unplaced_skipped {"object_ids":["u5"],"count":1}`. u5 kept its resolver place (52,−21). `logs/c5-*.txt` |
| 6 | Refusal mid-drag → every member rolls back, single notice | PASS | {a1,a2,a4} drag. `archive a4` sent via API before release (rev 31). POST → `outcome:"invalid", reason:"object_archived"`, `refused:[{"id":"a4",...}]`; revision stays 31. a1/a2 transforms return to their pre-drag values. One `scene.user_group_move_refused` and one toast "Déplacement impossible — refusé : l'objet est déjà archivé". `05-refusal-notice.png`, `logs/c6-*.txt` |
| 7 | Single-object drag unchanged | PASS | drag u1 alone → `pin` (rev 18) + `set_geometry` (rev 19), console `scene.user_moved {"steps":"pin+geometry"}`. No batch. Stored place reflects the orbit unturn. `logs/c7-*.txt` |
| 8 | CC response `patch_omitted: true` + `batch` | PASS | every applied selection command through CC: `"patch_omitted":true` + `batch` (requested/effective/clamped for translate). duplicate/refused have `batch` and no patch. |
| 9 | HTTP: patch_selection / pin_selection / archive_selection one revision each; refused = unchanged | PASS | hide constellation(a1) 31→32 (matched a1,a2,a3,h1, h1 unchanged). show 32→33. translate constellation 33→34. unpin_selection kinds 34→35. pin_selection 35→36. repeat → duplicate 36→36. archive_selection [u3,u5,a4(archived)] 36→37 with a4 `unchanged`. Refused (unknown id, archived id, unknown constellation root) 36→36. delta (0,0) → 400. actor brain → 403. Hidden h1 moves with a constellation translate (hidden_count 1, 43→44). `logs/c9-http.txt`, `logs/c9-hidden.txt` |

No page console errors or warnings. Core trace has no errors (`logs/core-scene-trace.jsonl`).

## Defect found

**D1 — A group drag can put orbiting objects on a path that leaves the screen.** Severity medium, UX. The code documents
the invariant "jamais un objet qui sort de l'écran en tournant" (`control_center_scene_layout.js`, ORBIT_GAIN_MAX comment),
and `orbitFits` is supposed to bound every rotating place.
`groupDelta` (page) and `group_clamp` (Core) bound only to `SCENE_SAFE_AREA`, not to `orbitFits`. Single drag (`dragBox`/`clampBox`) does check it.
Repro: select 4 capsules, drag hard toward the top-left corner. They are stored at (−152,−72)…, with orbit rx ≈ 700 px
in a 1280 px viewport. After that, sampled rects show members off-screen for part of each turn (`a1: 608,784 OFFSCREEN`,
`a3 … OFFSCREEN`). `03-after-edge-drag.png`, `04-after-edge-drag-orbit-later.png`.
Spec §5.2 accepts that members "re-seat" and forbids a per-member orbit correction, so this is a contract gap that the PM needs to decide. Options:
a common clamp that also honours `orbitFits` for turning members, or accept it and document it.

## Minor observations (not blocking)

- The refusal toast / `user_command_refused` log names `move.ids[0]` (a2), not the offending member (a4). The message text is still correct.
- The CC journal `scene.command_forbidden` logs the actor with its JSON quotes (`"\"brain\""`), which is cosmetic.

## Not verified

- Page selection of a hidden object: hidden objects are not rendered, so they can't be selected. Hidden-member translation was checked over HTTP only.
- Filter-mode `skipped: unplaced` for translate/pin via HTTP: every unplaced object got a resolver place within about 0.7 s from the open page(s), so no unplaced object existed to test with. Unit tests cover it.
- The browser used was headless Chrome over CDP, not the Claude-in-Chrome extension.
