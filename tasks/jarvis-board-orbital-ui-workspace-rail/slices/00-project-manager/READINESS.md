# Slice 00 - Readiness

## Declared state

| Item | Value |
|---|---|
| Planning reference | `57f28a7472577f8a193303023a99b026855f09ba` |
| `origin/main` | `57f28a74` (0 commits ahead of planning reference) |
| Task branch | `task/jarvis-board-orbital-ui-workspace-rail`, worktree `C:/Projects/jarvis/bor` |
| Handoff mirror commit | `c8e753e5` |
| Current HEAD | `b956fd49` = merge of `task/jarvis-unified-chat-and-board-drop` `e614669d` (Chat tab/panel, Board drop overlay/tray, moved `.toasts`) |
| Baseline/QA worktree | `C:/Projects/jarvis/boq`, still detached at `c8e753e5`: move it to `b956fd49` before the baseline sweep |
| Drive | handoff still in `to-do`; the Human moves it to `current` |

## Blind-audit summary (verified at `b956fd49`)

Full table with `file:line`: `../../docs/06-resolved-architecture.md` §1 (F1-F26). Corrections to the blind audit:

- `.sc-status` carries five other scene notes; only the hidden-objects note is replaced (F10).
- A canonical per-browser scene view-pref store with a filter-toggle precedent exists (`JarvisSceneView.showEphemeral`, F11).
- Audio capture accepts any input device token, not only the default; enumeration exists only in the Control Center process (F16).
- `docs/boards.md` placement statement is accurate ("top-right; top-left in Cosmos"), not stale (F23).
- Presentation rail dialog rank 9400 and all unified-chat ranks are missing from the registry comment (F3, F4).
- `CONTROL_SELECTOR` already misses `#interactionModeHud`, `#chatTab`, `#presentationRail`, `#boardDropTray` (F24).
- Two more tests couple to `.voicehint`: `test_control_center_chat_ui.py:77`, `test_control_center_chat_browser.py:385` (F25).
- Default theme is `circuit-board`; the user runs Cosmos; the two themes are two layouts (F2).

## Decisions D0-D13

Resolved in `../../docs/06-resolved-architecture.md` §3-§8. Summary:

| D | Resolution |
|---|---|
| D0 | Task Type `waived` |
| D1 | built on `b956fd49`, lands after unified-chat; shell owns chat/drop/toasts placement |
| D2 | `docs/control-center-shell.md` (S01) + `test_control_center_shell_layers.py` parsing base + Cosmos CSS |
| D3 | wheel = new module `control_center_tool_wheel.js`; captures via capture controller; no `data-bh-tool` |
| D4 | secondary = `contextmenu` (right-click, thumb+middle pinch, `ContextMenu`/`Shift+F10`); no long press |
| D5 | Mouse = BH `off` via `JarvisBarehands.disable()`; Bare Hands = HUD `choose('active')` path; no new field; takeover on trusted non-BH pointer events (click immediate; movement path+net within window, tunable, logged); BH tools in the Bare Hands sub-arc |
| D6 | new `GET /v1/captures/targets` (displays + Core-side mics, name tokens); single entry shown as informative only choice; no window/system audio |
| D7 | preview + lightbox Open + Delete with `.cdialog` + Send via Core allowlist widening (`screenshot`, same Session) and `JarvisChat.attachExisting`; Annotate implemented as gated S05.B (derived `screenshot` artifact, `derived_from`) |
| D8 | failed / attention / done / said (canonical); ids kept; `#voiceHint` removed, key hint moves to `.state` description |
| D9 | `showHidden` field in `JarvisSceneView`; ghosts + per-object "Réafficher"; list menu kept on secondary |
| D10 | Stage A preview ref + engine type from Core rail; yellow = additive `unreviewed` key in `rail.json` (no SQLite), set by brain work success, cleared by user `review`; Stage B adapter over `/api/workspace/artifacts` |
| D11 | CHANGED: Board control stays in the top state line as in the approved target; bottom-left fallback specified; Human check HV-08-01 |
| D12 | tiers: S01-S03 ui, S04 critical, S05 ui+adversarial, S06-S09 ui, S10 docs; isolated runtime only |
| D13 | one implementer per worktree; S02 // S07 after S01, S02 merges first |

## Planning repairs

1. "Long-press" wording replaced by the secondary channel (D4) in `README.md` (:56, :57, :143), `docs/01-decision-log.md` (D08), `docs/04-testing-and-quality.md`; SLICE files had none. `06-resolved-architecture.md` wins over `02`/`03` on any conflict.
2. Task Type set to `waived` in `task.json` and every `metadata.json`; `qa_tier` added.
3. S01 scope extended: geometry unification of both themes, `data-shell-control` + shared `CONTROL_SELECTOR`, registry rows for chat/drop/rail-dialog ranks.
4. S04 gains a Core route (`/v1/captures/targets`) and Core relay change; QA tier critical.
5. S05 split into S05.A (preview, Open, Delete, Send) and S05.B (Annotate, gated); Send changes a Core attachment rule -> `agent-trace-analysis` required.
6. S06 removes `#voiceHint` and the `sc-hidden` note; owns the `.voicehint` test migrations.
7. S07 gains Core changes (rail row `preview`/`type`, `unreviewed` key, `review` action); still no SQLite migration.
8. D11 changed (Board stays top state line); S08 no longer moves `#boardsHud` unless the Human picks the fallback.
9. Dependencies refreshed: S06 depends on S01 and S04 (recording indicators); S08 depends on S06, S07; S09 on S03-S08.
10. Issues to be opened by their slice if triggered: `bh-left-reveal-gesture.md` (S02), `barehands-return-latency.md` (S03, only if > 3 s), `screenshot-annotate.md` (S05, only if S05.B fails).

## Blockers

None found. Non-blocking dependency: unified-chat must land in `main` before this task lands (D1).

## Verdict

**READY** (pending agent 0 review and the baseline sweep below).

## Baseline failures

_To be filled by agent 0 from the baseline sweep on `b956fd49` (worktree `boq` moved to that SHA)._
