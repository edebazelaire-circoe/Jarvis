# Slice 10 evidence — simplify the existing Variants UI

Base `33015379`. Commits: `1be16cb8` (code and tests), `b8266568` (docs). Audit: `../AUDIT.md`. Contract:
`docs/presentation-studio.md` › *Variants control audit (Level 3, Slice 10)*. Everything ran in headless Chrome through the test harnesses,
on isolated Cores (free loopback ports, throw-away data roots), with the read-only Remotion gate runtime. The live Jarvis was never started,
stopped or contacted.

## Screenshots (SHA in each file name)

Made by `tests/unit/test_variants_controls_browser.py::test_evidence_variants_with_the_video_deck_idle_at_three_sizes_and_during_a_run`
(`JARVIS_VARIANTS_CONTROLS_EVIDENCE_DIR`, `JARVIS_VARIANTS_CONTROLS_SHOT_TAG`): the 9-scene Remotion deck of the Slice 03 gate, Variants
opened windowed, then the window resized to 1280×720, 800×600, 1920×1080, then a `user_presenter` run started from « Présenter ».

| File | What it shows |
| --- | --- |
| `before-33015379-variants-{800x600,1280x720,1920x1080}.png` | the base: one row under the stage, the slider squeezed to 59 / 64 px by the scene title and « Présenter », the `1/64` chip, the tree hint |
| `before-33015379-run-1280x720.png` | the base during a run: the actions at the same 0.5 opacity as an idle disabled action, the tree inert at full opacity |
| `after-b8266568-variants-{800x600,1280x720,1920x1080}.png` | Slice 10: row 1 the transport alone (slider 181 / 361 px), row 2 « Scène n sur N », title, « Présenter »; « n / 64 variantes »; « Touche ? : raccourcis clavier » |
| `after-b8266568-run-1280x720.png` | Slice 10 during a run: tree and actions dimmed (0.45 / 0.4), the reason under the actions, the presenter strip under the transport, one « Arrêter » |
| `after-b8266568-sheet-1280x720.png` | the keyboard sheet opened by `?` |
| `{before,after}-*-inventory.json` | every visible control at each size and in the run: name, state, effective opacity, inertness, box; readouts; overflow. The before file was read with names from `textContent` (a label hidden by CSS still counted as a name); the after file with `innerText` |

`b8266568` is the docs commit on top of `1be16cb8`: the code under test is `1be16cb8`'s. Home path and user name are redacted at write
time (derived at run time, never hard-coded).

## Measured (inventories)

| | before `33015379` | after `b8266568` |
| --- | --- | --- |
| slider width 800×600 / 1280×720 / run 1280×720 | 59 / 64 / 65 px | 181 / 361 / 282 px |
| graph actions during a run (effective opacity) | 0.5 (same as idle disabled), tree 1.0 | 0.4, tree 0.45, reason shown |
| tree count | `1/64` | `1 / 64 variantes` |
| keyboard sheet | none | `?`, « ⋯ › Raccourcis clavier » |
| variant bar in the DOM | yes (hidden with one variant) | no |
| forbidden controls (dwell, loop, `rs-bar`, « Tout jouer », « Jouer cette slide ») | none | none |

## Tests

Mutants (each reverted after its run):

| Mutant | Killed by |
| --- | --- |
| the `data-run` dimming CSS removed | `test_during_a_run_…[1280x720]`: « dimmer than an idle disabled action (0.5) » |
| the theater back to `min-height: 0` | `test_during_a_run_…`: the presenter strip drawn 112 px over the transport |
| the fullscreen button's `aria-label` removed | `test_each_control_appears_once_…[800x600]`: a visible control without a name |

Results, one file per process, fresh `JARVIS_DATA_ROOT` each (final code `1be16cb8`):

| File | Result |
| --- | --- |
| `test_variants_controls_js.py` (new) | 5 passed |
| `test_variants_controls_browser.py` (new) | 8 passed |
| `test_variants_controls_docs.py` (new) | 5 passed |
| `test_variants_transport_js.py` (updated: toolbar names, « ⋯ » entries) | 29 passed |
| `test_variants_transport_browser.py` (updated: toolbar names) | 5 passed |
| `test_presentation_rail_e2e_browser.py` (updated: no variant bar, `]` read on the tree) | 3 passed |
| `test_presentation_studio_explorer_browser.py` (updated: « Ouvrir les variantes ») | 18 passed |
| `test_presentation_studio_inspector_behaviour_js.py` (updated: « Ouvrir les variantes ») | 34 passed |
| `test_variants_run_js.py` / `_run_browser.py` | 9 / 6 passed |
| `test_variants_media_js.py` / `_media_fullscreen_browser.py` | 21 / 7 passed |
| `test_presentation_studio_explorer_{js,view_js,lifecycle_js,actions_js,rework_js,core_js,upgrades_js,compare_js,compare_core_js}.py` | 1, 15, 19, 23, 9, 14, 8, 12, 3 passed |
| `test_presentation_studio_presenter_js.py`, `_player_js.py`, `test_interaction_mode_hud_js.py`, `test_continuous_sequencing_js.py`, `test_barehands_contracts_js.py`, `test_control_center_presentation_rail_js.py`, `test_workspace_presentations_js.py` | 6, 9, 48, 21, 26, 9, 23 passed |
| `test_control_center_presentation_rail_browser.py`, `test_presentation_studio_presenter_browser.py`, `_explorer_compare_browser.py`, `_explorer_upgrades_browser.py`, `_inspector_browser.py`, `_reload_real_page_browser.py` | 13, 2, 3, 3, 16, 2 passed |
| `test_remotion_player_realpage_browser.py`, `test_presentation_continuous_playback_browser.py`, `test_remotion_timeline_realpage_browser.py`, `test_control_center_presentation_studio_engine_browser.py`, `test_workspace_presentations_browser.py`, `test_fullscreen_browser.py` | 7, 2, 2, 4, 2, 8 passed |
| `test_remotion_continuity_realpage_browser.py` | 1 failed in the long batch (a harness step timed out under load), 1 passed alone twice: the handover flake Slice 09 recorded (§ 6 of its evidence) |
| `test_presentation_studio_mcp_ops.py`, `_mcp.py`, `_mcp_policy.py`, `test_mcp_catalog.py`, `test_documented_routes.py` | 27, 23, 11, 92, 3 passed |
| every `*_docs.py` of presentation / remotion / variants (36 files) | all passed |
| release gate `test_presentation_playback_release_gate_browser.py` | 14 passed (`-k "not play_all_shows"`, first try) + 1 passed (`play_all_shows`, first try) |

`test_presentation_studio_explorer_upgrades_browser.py::test_the_zone_tells_the_newer_version…`, a pre-existing failure at `1793ad6e` per
Slice 09, passed here (3/3); nothing in this Slice targets it.

## Flags for QA

- Two rows under the stage (decided by agent 0's Work Agent, AUDIT § 4): the stage loses about 38 px of height on tall windows; on short
  ones (≤ 640 px) tighter gaps pay it back (the existing 300 px stage floor at 800×600 holds).
- « Présenter » moved out of the playback toolbar; « Arrêter » stays in it (fullscreen reach).
- A `?` typed while the focus is inside the scene's cross-origin frame is not relayed (the sandbox passes the § 4.15 keys only); said in
  the contract's limits.
- Human check HV-RFX-10-01 (visual control audit on the two screenshots and the live screen) is open: compare `../../evidence/02-variants-screen-base.png`
  with `after-b8266568-variants-1280x720.png` and `after-b8266568-run-1280x720.png`, then the live screen after the user restarts Jarvis.

## Note on the run screenshots (rework P5)

The white bar along the bottom of the image in `before-33015379-run-1280x720.png` and `after-b8266568-run-1280x720.png` is drawn by
the 9-scene test deck itself (its scene source draws a progress bar `#bar`, `tests/unit/presentation_playback_gate_world.py:60`), not by
Variants: it is part of the video, not a control.

## Rework after independent QA (Slice 10 rework commit)

- **B1** `?` in the stage fullscreen mounted the keyboard sheet outside the fullscreen element (unseen) and made the stage inert. Menus and
  dialogs now mount inside the fullscreen element while it is active (`.jvx-fs-layer`); the inert set follows the overlay's own path and
  gives back only what it made inert; Variants holds the Keyboard Lock on `Échap` while an overlay is open there, so the first `Échap`
  closes it and a real browser keeps the fullscreen (decided by agent 0). Headless Chrome leaves the fullscreen on an injected `Échap`
  whatever the lock (measured: the lock resolves, the page receives the key): the automated proof is the overlay drawn and hit inside the
  fullscreen, closed by the first press, the lock taken and released, Space playing and pausing afterwards; the fullscreen surviving the
  first press in a real browser joins HV-RFX-10-01.
- **P1** « explorateur » removed from every refusal, reason and sentence (page, command channel, MCP); the wording test scans those strings.
- **P3** the hint line stays visible (compact) on windows 640 px high or less.
- **P4** the evidence test skips (never fails) when `JARVIS_REMOTION_RUNTIME_DIR` has no `node_modules`.
- Mutants: the overlay layer forced to the windowed one, and the lock removed — each fails the new fullscreen test.
- Results (one file per process, fresh `JARVIS_DATA_ROOT`; runtime-backed files with the read-only gate runtime):
  `test_variants_controls_browser.py` 10 passed (the two new fullscreen tests included), `test_variants_controls_js.py` 5,
  `test_variants_controls_docs.py` 6 (the message scan included), `test_variants_transport_browser.py` 5, `test_variants_media_fullscreen_browser.py` 7,
  `test_variants_transport_js.py` 29, `test_variants_media_js.py` 21, `test_variants_run_js.py` 9 / `_browser.py` 6,
  `test_presentation_studio_explorer_{lifecycle,actions,view,rework,compare}_js.py` 19, 23, 15, 9, 12, `test_presentation_studio_explorer_browser.py` 18,
  `test_presentation_studio_explorer_commands.py` 48, `test_presentation_studio_mcp_ops.py` 27 (one expected sentence updated), `_mcp.py` 23,
  `_mcp_policy.py` 11, every presentation / remotion / variants docs test (36 files) passed, `test_task_evidence_privacy.py` 2.
