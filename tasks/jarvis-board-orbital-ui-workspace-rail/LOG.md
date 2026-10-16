# Handoff log

## 2026-10-15 - task creation

- Reconstructed the GrillMe decisions into durable product requirements.
- Preserved the user-provided current screenshot and the user-approved generated target mockup in `assets/`.
- Inspected the Jarvis Google Drive task layout and current/to-do folders.
- Inspected the GitHub repository default branch and the main Control Center/Bare Hands/capture/interaction-mode/presentation-rail code paths.
- Observed repository commit `57f28a7472577f8a193303023a99b026855f09ba` as the newest commit returned during planning. Slice 00 must revalidate HEAD before implementation.
- No product code was edited and no runtime was started/stopped.

## 2026-10-15 - agent 0 start (handle-task)

- `docs/workflows/AGENT_TASK_LIFECYCLE.md` absent from the repo: fallback to the Drive queue IDs from project memory (to-do `1pbNoTQ_nZKv3NVIe2ok-J6kplfnpmjmm`, current `1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D`, done `16yBLZRVOEbfDAN_CRh5722bkN46IUmo7`). No `dev` branch: task branch created from `origin/main`.
- Handoff folder `1jGRXzyMmTP4h0205a2-NjqPBEVW_n7CZ` found in `to-do`; mirrored byte-for-byte (45 files, sizes verified, every JSON parses). The Drive connector has no move tool: the Human moves the folder to `current`.
- Branch `task/jarvis-board-orbital-ui-workspace-rail` at `57f28a74` (= planning reference, `origin/main` identical) in worktree `C:/Projects/jarvis/bor`. Main checkout left on `main` (Human's live Jarvis).

## 2026-10-15 17:45 - agent 0 resumes (new session)

- The previous agent-0 session stopped at 17:37 local during Slice 00 (its blind audit and baseline sweep sub-agents froze at the same instant, no process left in `bor`/`boq`). Resumed as `continue`: branch, S0 commit `c8e753e5` and worktrees kept as is.
- Worktrees owned by this task: `C:/Projects/jarvis/bor` (task branch, implementer), `C:/Projects/jarvis/boq` (detached, baseline/QA). Every other short worktree belongs to other sessions.
- `origin/main` = `57f28a74` (unchanged, 0 commits behind).
- Overlap detected: `task/jarvis-unified-chat-and-board-drop` (Slice 09, near close-out, not yet merged into `main`) changes 3 `jarvis/runtime/control_center*` files (+312/-17). To be reconciled in READINESS.
- Slice 00 blind audit and wide baseline sweep re-dispatched.
- Drive handoff still in `to-do`: the Human must move it to `current` (no move tool).

## 2026-10-16 - S01 implemented (shell contract, design language, layer registry)

- New canonical contract `docs/control-center-shell.md` (Level 3): zones, tokens, single layer registry (page layers, contained ranks, reserved 37/38/40/60), `CONTROL_SELECTOR` membership, a11y/motion rules. New module `jarvis/runtime/control_center_shell.js` (`window.JarvisShell`, `SHELL_SCRIPT_FILE`, served first). Old registry comment of `control_center.html` replaced by a pointer + `@shell-layer` mirror; `docs/ARCHITECTURE.md` stacking table replaced by a pointer.
- One geometry, two skins: the Cosmos zones are now the base for both themes (state line top-left, launcher top-right row, panels under it); Cosmos `STYLE` keeps no position/rank for shell surfaces; Cosmos ranks 42/45/48/49/50/51 collapse to the base ranks (`git log -S`: no recorded stacking reason). Extra fixes found by the browser checks: legacy `@media(max-width:700px)` geometry of the vertical dock removed, brand hidden in both themes, state line single row above 700 px with room reserved for the pills, side panels (incl. Studio inspector) stop above the chat tab, drop tray climbs under the launcher on narrow screens.
- Every control host carries `data-shell-control`; the scene and the capture rail read `JarvisShell.CONTROL_SELECTOR` (identical fallback literal, `shell.missing` journal). The scene now also measures `#interactionModeHud`, `#chatTab`, `#presentationRail`, `#boardDropTray`, `#toolWheel`. Empty `#toolWheel` host declared (rank 30), no wheel behaviour.
- Tests: new `test_control_center_shell_layers.py` (9) and `test_control_center_shell_browser.py` (20, both themes x 1440x900/1280x720/900x600/600x800). Sweep of every test file touching the changed files (112 files) before and after: only pre-existing failures remain (settings_redesign_migration 1, barehands_interaction_js 2, control_center_voice_architecture 1, interaction_mode_hud_browser 3, workspace_presentations_js 1).

## 2026-10-16 - S02 implemented (retractable orbital tool wheel)

- New module `jarvis/runtime/control_center_tool_wheel.js` (`window.JarvisToolWheel`, `TOOL_WHEEL_SCRIPT_FILE`, served after the capture rail): pure block (slots, geometry, event reducer -> effects, view) + browser block (DOM, focus, injected callbacks). Behind `JarvisToolWheel.enabled=false` by default (host stays `hidden`, nothing built); S04 removes the flag.
- Closed = 14 px anchor at mid left edge (rank 30). Open = half-disc r 200 px, rank 37 (`#toolWheel[data-open]`, page layer row + `@shell-layer` mirror; reserved row removed). Exactly 4 wedges Selection / Video / Screenshot / Audio, 39 deg each, whole sector = pointer target (clip-path, no gaps), 52 px dots 83 px apart; one label, on the highlighted wedge.
- Reveal: mouse `pointerover` on the anchor; Bare Hands = the same `pointerover` from the synthetic pointer (9001-9002), no new gesture (Issue `Issues/bh-left-reveal-gesture.md`); keyboard Enter/Space/ArrowRight. No network, no polling, document listener only while open. Activation on `click` only (BH pinch fires once); secondary = `contextmenu` / `ContextMenu` / `Shift+F10` (500 ms dedupe), opens the reusable radial sub-arc (`onSecondary` -> entries, promise shows « Chargement… »). Close: Esc (sub-arc first), activation, pointerdown outside, focus leaving (no trap), pointer leaving 400 ms grace (pointer-opened only); focus returns to the anchor, never left on a hidden element. Reduced motion: 0 ms via `--shell-dur*`, no transitionend dependency. Unbound slot / failing callback: journal + toast with the real cause.
- Docs: `docs/control-center-shell.md` › Tool wheel (+ zones, layer row 37, invariants); `docs/05-documentation-levels.md` new L3 row.
- Harness `tests/unit/_interaction_mode_browser.mjs` (additive): `mouse` action (real CDP mouse event at a point), `shift` on `key`, F10/ContextMenu/ArrowLeft/ArrowRight codes, `@file` plan.
- Tests: new `test_tool_wheel_js.py` (11) and `test_tool_wheel_browser.py` (9: mouse, keyboard, BH synthetic 9001, reduced motion, focus, far pointer, Cosmos, 900x600 and 600x800). Sweep of the 150 test files referencing the touched files: only pre-existing failures (barehands_interaction_js 2, control_center_voice_architecture 1, interaction_mode_hud_browser 2-3 load-sensitive, brain_delegation 1, presentation_attention 1 — the last two verified identical on a clean `6cf5983a` worktree).

## 2026-10-16 - Slice 01 QA

- **S1 `6cf5983a` QA (tier ui, worktree `boqa`): `PASS_WITH_POLISH`.** No weakened guard among the migrated tests; headless Chrome probe (2 themes x 4 sizes x 5 states, ~37 targets) against base `5ae4c49f`: several old overlaps fixed (bgpills off-screen, panels over chat tab/Boards/state line).
- **Polish batched** (agent 0, no rework loop): P1 GPT-Live banner over the capture-rail screenshot button at 900x600 circuit-board; P2 drop tray under the banner at 600x800 Cosmos; P3 toasts over the drop tray with a panel open at 1280x720 -> S06/S09. P4 the "scene objects stop against #chatTab" claim is only proven by selector membership -> S09 real held-object test. P6 `control_center.py:448` lost the `WORK_SCRIPT_FILE` comment; P7 `control_center_boards.js:1506` comment still says top-right -> next implementer. Registry-test blind spots (inline `style=` z-index, JS `style.zIndex`, non-Cosmos theme overrides) -> S09.
- **For the Human (HV-01-01):** default circuit-board theme now uses the Cosmos geometry (top tool row, no brand).
- **Environment:** C: fell to 127 MB free during QA; the browser harnesses leave a ~12 MB Chrome profile per run in `%TEMP%\jarvis-*-cdp-*`.

## 2026-10-16 - S03 implemented (Mouse/Bare Hands selection arbitration)

- Preliminary `S0:` commit `445605a2`: every headless-Chrome harness (`tests/unit/_*_browser.mjs`) now deletes its `jarvis-*-cdp-*` profile at Node exit through one helper, `tests/unit/_cdp_profile.mjs` (Chrome tree killed, `rmSync` with retries, failure ignored; also covers `process.exit()` that skipped `finally`). `S1:` polish `ca1491f8` (P6/P7 of the S01 QA). `S2:` polish `8d4f79fd` (P1-P6 of the S02 QA).
- New module `jarvis/runtime/control_center_input_arbitration.js` (`window.JarvisInputArbitration`, `INPUT_ARBITRATION_SCRIPT_FILE`, served after the wheel and the BH HUD). No new owner: Selection is a projection of the BH lifecycle seam (`openLifecycleSeam('selection')`): off = Souris; active/sleep = Bare Hands; error = Bare Hands + « ! » + code (never Souris); starting = wait ring + 1 s counter. Selection is a `menu:true` wedge: primary activation opens exactly Souris / Bare Hands (new BH icon: tracking-frame corners + thumb/index pinch; the hand icon is not reused). Bare Hands' secondary activation opens a second level: installed tools (`tool(id)` → `saveSettings({tool})`), Veille, Aide, Diagnostic, Calibration (HUD gates).
- Souris = `JarvisBarehandsHudControl.selectMethod('mouse')` = HUD `choose('off')` = `disable()`; Bare Hands = `selectMethod('bare_hands')` = `choose('active')`. `disable({reason:'mouse_takeover'})` only changes the stop toast (« Souris reprise — Bare Hands éteint »).
- Takeover: pure `decide()`; trusted, non-BH-pointer events only, only in `active`; pointerdown/click/wheel/contextmenu immediate; move = path >= 48 px AND net >= 24 px within 400 ms; one transition per episode; 1500 ms cooldown after any entry into `active`; tunable (`configure`), journalled (`input_arbitration.takeover {reason,input,distance_px,net_px,window_ms}`).
- Wheel generic additions (`control_center_tool_wheel.js`): `menu:true` slots, `setStatus(id,{icon,tone,text})` projected on the wedge, its label and the anchor (visible closed), sub-arc entries with `icon`/`note`/`detail`/`tone`/`data-tw-item`, second level (`onSecondary` on an entry, laid out from the parent angle downwards, Esc returns), secondary dedupe reset on close.
- Wheel on: `#barehandsHud` and `#barehandsPalette` leave the default view (`body:has(#toolWheel:not([hidden]))` in the HUD sheet); flag off = rollback, both come back. Flag stays off until S04 (tests enable it).
- Return latency (fake camera, real MediaPipe assets via `SELECTION_REAL_VENDOR`, headless CPU/SwiftShader): 389-877 ms (fake landmarker ~150 ms) < 3 s, no Issue filed. Real-webcam warm-up not covered (HV-03-01).
- Deviation from D5 wording: voice return from `off` is two brain calls (broker refuses `barehands_disabled` while the switch is off and the command channel only polls while enabled; the brain turns the switch on via `settings_set(barehands.enabled, true)`, then `barehands_activate`), already the documented MCP behaviour; tested end to end on the page side.
- Docs: `docs/control-center-shell.md` › Tool wheel (+ Selection method), `docs/barehands-contracts.md` § 1 selector note + § 8 palette (canonical selector moves to the second level while the wheel is on), task `docs/05-documentation-levels.md` (arbitration L3, BH tool presentation L3).
- Harness `_interaction_mode_browser.mjs` (additive): `CDP_CHROME_FLAGS` env (fake camera), `click` on a missing selector names it.
- Tests: new `test_input_arbitration_js.py` (11, properties over 10 000 seeds) and `test_selection_method_browser.py` (8, real page + real BH engine, fake camera, test HTTP server over the real `barehands_test_mode`); `test_tool_wheel_js.py` +1 (menu slot/second level) and the art-key assertion migrated (extra keys = sub-arc icons); `test_tool_wheel_browser.py` Cosmos label now « Sélection · Souris »; `test_barehands_hud_js.py` +2 (`selectMethod` mapping, wheel-on hiding rule). Palette/HUD node tests unchanged (invariants hold; CSS-level hiding is measured in Chrome).
- Commands: `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest <file> -q` one file at a time from `bor`; latency: `SELECTION_REAL_VENDOR=<main>/third_party/barehands/vendor ... test_selection_method_browser.py -s -k latency`; evidence: `SELECTION_SHOTS=<dir>`.
- Sweep before/after (68 files touching the changed files): only pre-existing failures (barehands_interaction_js 2, interaction_mode_hud_browser 2-3 load-sensitive, wake_word_settings_browser 1 flaky).
