# QA-1 - Slice 03 generic fullscreen borderless surface (standard tier, user-visible)

Reviewed commit `d744ef45` (diff `4dcc5cd4..d744ef45`, 16 files, +3440). Worktree `C:/Projects/jarvis/bipq`, detached, HEAD checked before and after: `d744ef45`, `git status` clean after every mutant. No product code modified.

## Verdict recommendation for PM: APPROVE (no BLOCKING). 5 POLISH, 4 ISSUE. Fix POLISH 1 (wrong server state) in a cheap follow-up commit if a rework pass happens anyway; none gates the merge.

## Contract completeness (SLICE.md)

| Item | Result |
| --- | --- |
| enter/exit API | Present: page `JarvisFullscreen.enter/exit/cancel/state/onNavigate`; agent side `POST /api/fullscreen/commands`, `GET /api/fullscreen/state`. Exercised for real (below). |
| Selected display + graceful fallback | `display` current/primary/other/index, `getScreenDetails()`, fallback reported as `display_selection` (`unavailable/denied/missing`). Real headless Chrome, `display:"other"`: entered on current display, `display_selection: denied`, no error. Real multi-monitor NOT verified (headless). |
| Chrome hidden | Real Chrome: entered host 800x600 (= viewport), frame 800x600 at 0,0, title `display:none`. Plain (non-prefab) window and scene root also enter fullscreen, but their own chrome stays visible (CSS only hides chrome when `> .sc-prefab-slot` exists). Documented ("A window without a frame slot is fullscreened as is"). |
| Restore size/position/focus | Real Chrome: rect before == rect after (`[40,120,380,280]`), focus back on the previous button, marker `data-jv-fullscreen` removed, `tabindex` removed. Server state back to `exited`. |
| Keyboard/emergency exit | Escape (CDP key) exits; nav keys ArrowRight/PageDown/PageUp/End/ArrowLeft/Space/Home all reach `onNavigate` (raw keydown list == nav list). |
| Eligible windows / prefabs | prefab window, plain `[data-object-id]` window, scene root: all enter. Missing target -> 200 `refused` `fullscreen_target_missing`. |
| No regression in window mode | Stylesheet has only `:fullscreen` rules + `#jvFullscreenPrompt` rules (listed at runtime). Existing suites green (below). |

## R4 constraints

- Host element contains the frame, never the frame: confirmed (`fullscreenElement` is `[data-object-id]` host, `Disallowed by permissions policy` behaviour is covered by the implementer's browser test).
- `sandbox`/CSP/`jv:1` untouched: diff touches NO prefab host/protocol/shim file (`git diff --stat` on `control_center_prefab_host.js`, `control_center_prefab_protocol.js`, `jarvis/prefabs`: empty). Diff grep of added lines for sandbox/csp/allow/jv:1: only docs, comments and test assertions. Runtime: frame `sandbox` read back = `allow-scripts`, `allow` null, no `allowfullscreen`, both before arm, while armed and while fullscreen; frame stays `ready`.
- Armed request + visible one-click prompt: `POST enter` -> 200 `needs_gesture` in 0.02 s, never `entered`; prompt `role=alertdialog`, button, cancel, countdown. Without a real click nothing enters.
- `fullscreenchange` is truth: server state `entered` appears only after the click; Escape/`exit` -> `exited` via the event. Mutant 3 (report `entered` at arm) is killed.
- CSS overlay never reported as fullscreen: only `requestFullscreen` path sets `entered`.
- Explicit states: `needs_gesture`, `unsupported`, `refused`, `expired` all reachable and visible/logged (`[fullscreen]` console lines present; no page errors in the run).

## Evidence run

Existing + new suites, one file at a time, all green: `test_surface_fullscreen` 31, `test_fullscreen_commands` 24, `test_fullscreen_js` 29, `test_fullscreen_browser` 7, `test_documented_routes` 3, `test_barehands_command_channel` 35, `test_barehands_commands_js` 16, `test_presentation_attention_browser` 31 (144 s), `test_prefab_host_js` 18, `test_control_center_mvp` 23, `test_control_center_quality` 73. Not run: full suite and the 10 baseline-red tests (not ours).

Real headless Chrome (CDP, Python/aiohttp driver in my scratchpad) against an isolated `ControlCenter` (free port, own `JARVIS_DATA_ROOT`, live Jarvis 17653/17654 never touched). The served page, real `control_center_fullscreen.js`, real `JarvisPrefabHost` with the `test.counter` bundle injected into the served page (no Core => no scene/prefab relay, so windows were injected into `#sceneLayer`). Scenarios and results:

- arm -> prompt -> real mouse click -> fullscreen -> Escape -> restore: PASS (server state needs_gesture / entered / exited each checked).
- expire (`arm_s:3`): server `expired`, prompt gone, focus restored. PASS.
- cancel via `exit` command and via "Annuler" button: PASS, focus restored.
- double-arm concurrent: one 200, one 409 `fullscreen_command_busy`. Sequential re-arm: single prompt. PASS.
- Local `enter()` without gesture arms (`needs_gesture`); with gesture enters. `enter` while already entered: `entered`. `exit` command: `exited`. PASS.
- Receipt forgery from a null-origin sandboxed frame (opaque origin, fetch of state POST/GET, commands GET/POST): all blocked (`Failed to fetch`, CORS/guard), server state unchanged. `Origin: http://evil.example`, `Origin: null`, `Sec-Fetch-Site: cross-site`, bad `Host`: all 403 `fullscreen_forbidden_origin` on all five routes.
- 22 adversarial POST bodies (non-JSON, array, null, unknown field, `exit` with fields, display -1/true/16/"../x", `arm_s` 0/1e999/NaN/121/"30", object_id with slash/129 chars/number, bad keys, 5000-deep nesting, 2 KB, invalid UTF-8, empty), 6 poll queries (`wait_s` nan/-1/inf/26/abc, unknown param), 7 bad state reports, 2 KB report, unknown/short/65-char receipt ids: all coded 4xx, nothing crashed, state unchanged. No 500 seen.
- Idle polling: 0 extra `/api/fullscreen/commands` GETs in 8 s (25 s long-poll held); JS floor `MIN_POLL_GAP_MS` covers instant-reply servers (unit-tested, attention-browser test updated legitimately).

## Mutation testing (5 mutants, each restored, hash equal, status clean)

| # | Mutant | Result |
| --- | --- | --- |
| 1 | skip deadline check in `complete()` | SURVIVED. Equivalent in practice: `request()` `wait_for(deadline)` already drops `_pending`, so a late receipt hits the unknown-id 404 path first. Dead-ish guard; harmless. A test could pin it by calling `complete` with a patched clock. |
| 2 | drop `FULLSCREEN_ROUTE_PREFIX` from `READ_GUARDED_ROUTES` | killed (`test_a_prefab_frame_or_a_foreign_site_can_neither_consume_nor_dictate`) |
| 3 | `handle()` returns `entered` at arm | killed (js + browser) |
| 4 | drop focus restore on exit | killed (js + browser) |
| 5 | set frame sandbox to `allow-scripts allow-same-origin` on enter | killed (js static test + browser) |

## Findings

### BLOCKING
None.

### POLISH

1. **Server state corrupted by a refused `enter` while another surface is fullscreen.** `fullscreen_commands.py:_apply` (line ~462, `after == "entered"` branch) + transition `("entered","browser_denied") -> entered`. Scenario (reproduced): obj_1 fullscreen, agent sends `enter obj_plain`; page correctly answers `refused/fullscreen_other_surface_entered`, but `GET /api/fullscreen/state` then returns `state: entered, object_id: "obj_plain", code: "fullscreen_other_surface_entered"` while the real fullscreen element is obj_1. The agent reads a wrong object and a stale refusal code on an `entered` state. Fix: on `entered` + non-entry event keep `_object_id`/code; do not overwrite from the receipt of a refused request.
2. **Hidden tab can win the armed command.** `control_center_fullscreen.js` `createCommandChannel`: `setVisible(false)` only stops the NEXT poll; the in-flight 25 s long-poll stays registered, wins `deliver()`, arms an invisible prompt, and the agent is told `needs_gesture` ("click the prompt") while the user looks at another tab. Reproduced with two tabs: prompt landed in the hidden tab (2 of 6 trials; the rest were the closed-tab issue below). Same-origin sibling `exit` can also land on the other tab, report `exited` without cancelling the hidden tab's still-armed prompt (server `exited`, hidden tab local state `needs_gesture`, stale prompt reappears when the tab is shown, until its 30 s deadline). Fix idea: abort the in-flight poll on `visibilitychange` hidden; cancel local armed prompt when hidden or on any `exit`. Docs say hidden tab = `fullscreen_no_visible_page`; that is only true after the in-flight poll ends (up to 25 s).
3. **Control Center dialog makes the prompt inert (the risk the implementer flagged), reproduced.** Opened `confirmDialog(...)`, then armed: receipt 200 `needs_gesture`, prompt present but `inert: true` (the dialog's `MutationObserver` marks every new body child inert, `control_center.html` ~3205-3212), real click does nothing, state stays `needs_gesture` until expiry; after closing the dialog the same prompt is clickable again. It is documented in OPERATIONS "limites connues", but the user sees a prompt they cannot press. Cheap fixes: exempt `#jvFullscreenPrompt` in `confirmInertCandidate`, or have `arm()` refuse/queue while `CONFIRM.resolve` is set and say so in the receipt (`refused` with a reason the agent can speak).
4. **`keys:"host"` (the default) reclaims focus from a prefab text field.** `bindKeys` blur handler refocuses the host whenever focus lands in the iframe. Real Chrome check: click in a prefab `<input>` with `keys:"host"`: frame `document.hasFocus()` = false, `document.activeElement` = host DIV; with `keys:"none"`: frame has focus. Typing via CDP still reached the input in both cases (CDP routes keys to the OOPIF widget), so real-user typing under `host` is NOT proven broken, only very likely. Opt-out exists and is documented, but the safe default for an interactive prefab (Slice 18) is `none`, or the reclaim should only run when the click was a nav gesture. Decide before Slice 18 builds on it.
5. **Human recipe is not copy-paste executable on the Human's shell.** `docs/OPERATIONS.md` (new section): the `curl ... ^` / `\"` form is cmd.exe syntax only; in PowerShell `curl` is an alias for `Invoke-WebRequest` and fails on `-X/-H`; "l'identifiant de la fenêtre" is never explained (where to read it?). Give a PowerShell form (`curl.exe`, here-string or a one-line `Invoke-RestMethod`), say how to get the `object_id`. The text is French and the steps are otherwise coherent and match observed behaviour.

### ISSUE (non-blocking, track)

1. **Dead-socket loss of a command (inherited from Bare Hands, accepted there).** Reproduced once: after closing a second tab that had a poll in flight, the next `exit` returned 504 `fullscreen_command_expired` ("la page a pris la commande..."), then worked. For `exit` an unknown outcome is more annoying than for an arm. A redelivery after a few hundred ms, or aborting polls on `pagehide`, would remove it. Not caused by this Slice's design choices.
2. **Trust model equals Bare Hands, no more.** Any local client without an `Origin` header, or a page on ANOTHER loopback origin (tested `Origin: http://127.0.0.1:1` -> 200 on all routes), can arm a prompt, and can forge a page report (`POST /api/fullscreen/state {"state":"entered"}` -> server state `entered` with no browser fullscreen; I forged and reset it). A prefab frame, `null` origin, foreign site, cross-site fetch and rebinding Host are all refused. Ids are 24-byte `token_urlsafe`, single-use, one pending command at a time, arming capped 3-120 s, 3 s delivery deadline, so DoS is limited to prompt-flapping by a local process. Acceptable for a loopback tool; state in SECURITY if not already.
3. **Parallel infrastructure.** `fullscreen_commands.py` (359 lines) and `control_center_fullscreen.js` channel (~70 lines of long-poll, backoff, visibility, receipt) are a near copy of `barehands_commands.py` / `control_center_barehands_commands.js` (388 / 591 lines). The semantic differences (armed state outliving delivery, server-held state) are real and justify a sibling for now; judgement: the shared long-poll/backoff/visibility plumbing should be factored when a third command channel appears, and items POLISH 2 and ISSUE 1 would then be fixed once for both. Not a Slice 03 gate.
4. **Toasts and error lines are invisible while fullscreen** (only the fullscreen element's subtree renders). E.g. an `exitFullscreen()` failure toast cannot be seen; Escape still works and the failure is logged and reported. Reasoned, not reproduced.

## Docs accuracy

Claims checked against runtime: needs_gesture never entered, states and codes table, closed list of page codes, 3 s receipt deadline, 3-120 s arm, 403 `fullscreen_forbidden_origin`, 504 codes, `display_selection` values, nav key list, `keys:"none"` opt-out, "element is never moved in the DOM", stylesheet only `:fullscreen` + dialog. All true. One imprecise claim: hidden tab -> `fullscreen_no_visible_page` (see POLISH 2). `docs/presentation-studio.md` edits: one table cell, one new section inserted before "Binding facts", one row in the maturity table. Merge-conflict surface is small but the new section sits in the middle of the page where Slices 02/04/05 (already merged in `feat/ips-s03` lineage: `d8866ef9 S4: docs ...` also touched this page) and later Slices will add sections: expect a trivial textual conflict at the insert point and in the same table; resolve by keeping both. `docs/09-canonical-names.md` states and routes match the code; `docs/08` row 03 satisfied except "expose through current UI/scene tooling" (see Q2).

## Implementer's open questions

1. **Rename `refused` -> `denied`? No.** `refused` is the canonical state in `docs/09-canonical-names.md` line 22 and in the docs/code/tests. `denied` already means two other things here (page code `fullscreen_denied`, `display_selection: denied`); a state of the same word would blur them. Keep `refused`.
2. **Window-menu entry now? Yes, small and worth it, as an explicit follow-up in this Slice or the first of Slice 18.** The Slice is user-visible, yet today the only way for a human to reach fullscreen is a curl command; the menu click is also a genuine user gesture, so it uses `JarvisFullscreen.enter()` without the arm/prompt round-trip (verified at runtime: with gesture -> `entered` directly; without -> arms). It also turns the Human recipe from curl-driven into click-driven and makes POLISH 5 mostly moot. If the PM wants a minimal Slice, defer to Slice 18 but then say so in `docs/presentation-studio.md`.

## Not verified

Real multi-monitor and the Chrome `window-management` permission prompt; a physical Escape key; real focus routing for typing into an iframe on a headed browser; scene windows driven by a live Core (windows were injected, no Core/prefab relay in the isolated server); the 10 baseline-red tests and the full suite; journal file contents (only console and HTTP state inspected; the broker's `fullscreen.*` emits are covered by `test_fullscreen_commands`); toast visibility inside fullscreen (reasoned).
