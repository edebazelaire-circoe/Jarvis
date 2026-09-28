# Slice 08 — Integration and release QA

Branch `task/jarvis-mcp-semantic-batch-inspector`, HEAD `a9a5b16` at start (docs fix `aa4c7dd` during this slice), 2026-09-25. One writer, one isolated instance at a time, pytest in the foreground in chunks.

**Verdict: PASS.** No regression. All 23 in-domain inherited failures are green. Only the 8 out-of-domain failures from `Issues/01` remain. Static checks are clean. A live run with the real brain gave one call → one Core command → one revision on every set turn. The inspector matches the live CLI. D1 and D-S5-1 hold in a real browser.

Companion reports: `runtime-validation.md` (page, inspector, D1/D-S5-1) and `agent-trace-analysis.md` (live brain trace, the six Slice 04 points, parity).

## 1. Regression sweep (HEAD `a9a5b16`)

Command: `.venv/Scripts/python -m pytest -q -p no:cacheprovider <files>`, run in the foreground. The file lists and per-chunk summaries are in `evidence/sweep/`.

| Chunk | Files | Passed | Failed | Skipped | Failures |
|---|--:|--:|--:|--:|---|
| unit u00 | 32 | 651 | 2 | 0 | `test_barehands_interaction_js` ×2 (Issues/01) |
| unit u01 | 31 | 670 | 2 | 0 | `test_barehands_tutorial_retired_js` ×1, `test_brain_delegation` ×1 (Issues/01) |
| unit u02 | 27 | 716 | 0 | 1 | — |
| unit u03 | 33 | 669 | 0 | 1 | — |
| unit u04 | 32 | 1 252 | 0 | 1 | — |
| unit u05 | 34 | 1 367 | 0 | 1 | — |
| unit u06 | 33 | 1 022 | 0 | 0 | — |
| unit u07 | 33 | 966 | 0 | 2 | — |
| **unit total** | **255** | **7 313** | **4** | **6** | baseline `ddcdb71`: 6 991 / 25 / 6 over 248 files |
| integration i00 | 32 | 284 | 0 | 9 | — |
| integration i01 | 33 | 287 | 4 | 13 | `test_testlab_audio_runners` ×2, `test_testlab_hardware_runners` ×1, `test_testlab_live_runners` ×1 (Issues/01) |
| **integration total** | **65** | **571** | **4** | **22** | baseline: 566 / 6 / 22 |

- Unit: +7 new files and +322 passing tests. The 21 in-domain unit failures are green: scene_artifacts 6, batch_tools 3, capture 1, query_tools 2, service 2, settings 2, transport_client 4, interaction_logic 1.
- Integration: `test_scene_transport` 2 are green. Slice 03 added 3 tests.
- The 8 remaining failures are exactly the Issues/01 list, owned outside this task. **No regression.** No bisect at `ddcdb71` was needed.
- The baseline counted 67 integration "files" and this sweep ran 65 `test_*.py`. `ddcdb71` also has 65 `test_*.py`, so the difference is in how the files were counted, not a lost file.

## 2. Static and release checks

- `scripts/verify_release.py` was run with its pytest step stubbed (`evidence/scripts/verify_release_stub.py`), because a single-process full pytest gets OOM-killed. The stock script **fails** on `subprocess.run(` in `jarvis/runtime/barehands_replay.py:144`. That line is identical at `ddcdb71`, so it is **pre-existing and not this task's**. With that check reported instead of fatal, every other check passes: core imports, benchmark allow-list, locked runtime sources, and privacy default. **FLAGGED** for the PM, since the release script is red on main too.
- `node --check` passes on all 5 JS files changed by the branch (`control_center_mcp_inspector.js`, `_scene_interact.js`, `_scene_layout.js`, `_scene_page.js`, `_work.js`).
- **Leftovers:**
  - `best_effort`, `scene_set_visibility`, `_connected_ids`, `MAX_BATCH_TARGETS`, `MAX_DISPOSE_TARGETS`, `MAX_BULK_TARGETS`, `BULK_DEADLINE_S`, `bulk_deadline_s`, `_show_all_hidden`, `_update_many` and the old `connected` key have **no code hit**. The only hits are historical mentions in docs: the tool-contract §7 migration inventory, the historical plan, and "removed by Slice 05" notes.
  - No TODO/FIXME/XXX/HACK was added in `git diff ddcdb71..HEAD`.
- **Stale doc claims:**
  - There is no "un SceneCommand par appel" and no "until Slice 05" left.
  - `docs/mcp/plan-outils-interface.md` is labelled historical (the "Contrat livré" box, with `scene_set_visibility` marked as removed).
  - Fixed in `aa4c7dd`:
    - The Slice 02 box in `scene-selection-batch.md` still said "Not wired into any command yet".
    - ARCHITECTURE said `DISPLAY_TOOLS` was "the exact ten" names.
    - The open points in tool-contract §9 and §10.3 were still waiting on Slice 08.
    - The context figure read 31 832 where Slice 05 QA measured 31 833.
- **Context budget** (`build_catalog()`):

  | Server | Tools | Model-visible bytes |
  |---|--:|--:|
  | jarvis-display | 13 | 31 864 (≤ 33 090) |
  | jarvis-console | 3 | 2 918 |
  | jarvis-barehands | 5 | 4 107 |
  | jarvis-drive | 7 | 2 126 |

  - 41 015 B in total over 28 tools. 21 of those tools are declared by Jarvis, the same as the baseline (13 + 3 + 5).
  - No `list_tools`/`get_tool` meta-tool and no alias.
  - `barehands_tutorial` is the only deprecated tool. It is pre-existing, with its legacy doc and removal condition, and does not come from this task.

## 3. Runtime, trace, parity

See the companion reports. In summary:

- **Live turns:** 8 real brain turns in French, **$0.585 total** (Claude Code 2.1.282, `claude-opus-5-5[1m]`). Five set turns each made one set call, one Core command and +1 revision. There was one honest refusal, one move back and one settings read.
- **Page:** one coherent transition per turn, and the page sent 0 scene commands.
- **D1:** a corner drag of the orbiting group sent one `translate_selection` bounded by the orbits. Nothing was off-screen in 1 322 samples over 264 s, which is more than one full 240 s orbit.
- **D-S5-1:** after the brain moved the group to the edge, the edge capsule was held still (`sc-orbit` off), stayed on-screen in 306/306 samples and kept its link attached. Once the group was moved back inside, it orbits again.
- **Inspector:** focus stays on the row toggle during a refresh and in search during indexing. Escape with focus on `<body>` closes the view and returns focus to MCP. After a brain restart, reopening re-reads the list and clears the pending notice. There is no horizontal page scroll at 360 px. Compact and detailed `scene_update_many` both render.
- **Parity:**
  - Inspector list vs the CLI `system/init`: names and counts are equal for display 13, console 3, barehands 5 and drive 7.
  - The 21 definitions the model received vs inspector detail: `input_schema` and `description` are equal, and bytes are equal to `context_bytes`. The only difference is the CLI's own rewrite of `…` → `...` (FLAGGED, not a Jarvis defect).

## 4. Not verified

- Scene switched **off** in this slice: `JARVIS_SCENE_ENABLED=1` pins it on. That configuration was proven by Slice 06 at the same API code: the CLI loses its display tools and the API reports `disabled`.
- Live Bare Hands MCP turns, `settings_get`/`settings_set`, `scene_get`, and a duplicate `scene_link` on the real API. They are unit-tested, and Slice 04 measured them on a fake endpoint.
- Theme variants other than the default during this slice (Slice 07 covered Cosmos).
- The user's real Chrome: headless Chrome 153 over CDP was used, and the extension was not used.
