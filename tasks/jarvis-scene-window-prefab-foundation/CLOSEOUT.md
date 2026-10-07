# Close-out — Jarvis Scene Window & Prefab Foundation

Branch `task/jarvis-scene-window-prefab-foundation` (worktree `bpf`), base `origin/main@257e911`,
merged with `origin/main@085928d` at `1523823`. Status: **awaiting Human validation** — every machine
check below is done; the three Human checks at the end remain.

## Slices

| Slice | Result |
| --- | --- |
| 00 project manager | READY: blind audit, binding doc 06 (R0-R9), Slice contracts, baseline at `1600dbf` |
| 01 contract audit | `docs/prefabs.md`, scene-model *Prefab windows*, ARCHITECTURE, SECURITY §16 |
| 02 prefab schema | strict domain `jarvis/domain/prefab.py`, atomic file library, Core catalogue, base-edit gate seam; QA rework |
| 03 dynamic runtime | one sandboxed frame runtime (`allow-scripts`, CSP first), shim + shell, read routes; containment rework |
| 04 scene ↔ prefab bridge | `ScenePayload.prefab`, Core validator, `apply_if` (R9.1), events (state/notify, ring, rate limit), page slot; QA rework (stored block with defaults, `event_result`) |
| 05 window families | `jarvis.window`, `jarvis.document`, `jarvis.table` + `lock_base_prefabs`; gesture shield rework |
| 06 structured interactive | `jarvis.checklist` (state + notify, keyboard, one write in flight); QA rework |
| 07 agent operations | six `prefab_*` tools on `jarvis-display`, `prefab` arg on create/update, real witness, notify delivery, prompt; real traces; QA rework |
| 08 library | PFB dock view, `POST /api/prefabs` relay (fork as user), provenance badges; QA rework |
| 09 integration hardening | re-audit, legacy retention proof, Presentation seam, stress, full suites, probe replay, real lifecycle trace, privacy sweep, final levels, this close-out |

## Commits by Slice (`git log --oneline 1600dbf^..HEAD`)

- **S0**: `1600dbf`, `d80b4a6`, `67a8c68`; baseline fixes (branch `fix/scene-baseline-2026-10-03`, merged `a51cc6a`): `0b2d482`, `084aeef`, `96c725f`.
- **S1**: `a1217f2`.
- **S2**: `7927662`, `eadb8e1`, `b5fb14e` (rework).
- **S3**: `3191ac9`, `eb4a39b`, `888937c`, `a7ee10e`, `423033b` (rework).
- **S4**: `c323e87`, `b8066db`, `f2683de`, `e9d54a7`, `c783f09`, `1b38cad` (rework).
- **S5**: `e85f6ca`, `6596371`, `9a81565`, `9e08d44`, `b00c142` (rework).
- **S6**: `d1bf63a`, `e383e6c`, `9e5661c`, `2b810f8` (rework).
- **S7**: `abd88fc`, `33aa707`, `f4324ab`, `630aba3`, `52c6f7c`, `f1431bd`, `ed14b42`, `491b68e` (rework).
- **S8**: `3e83813`, `6d7f711`, `c6bbb6c`, `b734dc1`, `1744e90`, `5f7b552` (rework).
- **S9**: `a727b8e`, `cdab695`, `a1389a7`, `6dfff21`, `d64d132`, `c973781`, `d0d50cf`, `40dd7b6` + the close-out commit.
- **origin/main brought in** (not this task): `c57cc65`, `514513f`, `ffebb9b`, `dea0fd0`, `085928d`; merge `1523823`.

## Tests and validators (Slice 09, final code)

| Run | Result |
| --- | --- |
| `tests/unit`, 409 files in 12 alphabetical chunks (node JS suites included) | **12 285 passed, 6 failed, 14 skipped** — the 6 are the inherited list: `test_app` (1), `test_barehands_interaction_js` (2), `test_brain_delegation` (1), `test_interaction_mode_hud_browser` (1), `test_scene_group_drag_js` page single-command (1). The 4 baseline `barge_in_decider` failures are fixed by origin/main `514513f`. |
| `tests/integration`, 72 files in 3 chunks | 628 passed, 23 skipped, 2 failed → `test_scene_transport::test_stopping_the_server_releases_a_pending_long_poll` deterministic since `085928d` (helper counted the file watcher's own revision wait), fixed `a1389a7` (file 56/56); `test_remote_mcp_connector::test_access_denied_marks_the_plugin_failed` 5 s timeout under load, 36/36 three times alone |
| Re-run after the S9 code fixes (56 files touching prompt, display tools, prefab events) | 1 689 passed, `test_brain_delegation` inherited, one `test_presentation_integration` test load-flaky (3/3 alone, file 76/76) |
| Gates | `test_v2_architecture` + `test_documented_routes` + `test_prefab_protocol_js` (sole `srcdoc` site, literal sandbox) + `test_schema_migrations`: 33 passed; base lock `--check` covered by `test_prefab_base_catalog` |
| New S9 tests | `test_prefab_events::test_a_sustained_flood_is_one_warning_and_one_end_never_one_per_refusal` (mutant killed), `test_display_mcp_prefabs::test_the_presentation_seam_…`, `test_task_evidence_privacy.py` (2), refusal/prompt pins |
| Browser probe replay S04–S08 (8 probes, fresh scratch, 18993/18994) | all steps pass, 0 console errors, 0 `core.*` error diagnostics; S08 `rw_probe` step `rwAfterFrame` fails on a probe timing race (Issue `library-preview-swap-keeps-two-frames`) |
| Stress (`slices/09-…/evidence/`) | 200 cycles: ≤ 1 frame, 0 growth (documents 1, nodes 1060, listeners 236, `message` 0); 30 windows: 24 live + 6 paused, resume by selection; floods: host 10/100, Core 50 recorded / 150 × 429; 0 `core.*` error; 1 warning + 1 end (fixed `cdab695`) |
| Real agent trace (9 turns, 3 CLI sessions, 2.08 $) | discovery, instantiate, tick (real mouse), read state, fork, rediscover, reuse in a new Session, implicit improve (no base edit), c2 re-trace: FAIL (main brain retried) → fixed `d0d50cf` → PASS |
| Privacy sweep | `privacy_sweep.py`: 140 text files clean; S04/S05 leaks redacted; 11 S05 PNGs regenerated |

## Documentation updated

`docs/prefabs.md` (canonical contract; S09: *Legacy windows*, *Consumers (Presentation seam)*,
*Documentation levels*, lifecycle stress, rate-limit diagnostics, witness intake limitation),
`docs/scene-model.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md` (PFB), `docs/SECURITY.md` §16,
`docs/mcp/tool-contract.md` (§10.13, prompt 1 353 B), `docs/local-data.md`,
`docs/mcp/plan-outils-interface.md` (`view_table` → `jarvis.table`); handoff docs 05/06 carry the final
levels.

## Final documentation levels

All prefab concepts at **Level 3** (contract + implementation + conformance tests): definition,
inputs, instance, runtime lifecycle, event bridge, base protection, provenance/versioning, agent
operations, library UI, window families (4 locked base prefabs). Presentation seam at **Level 2**
(documented contract + one conformance test; behaviour belongs to the Presentation task). Legacy
windows unchanged at Level 3.

## Canonical implementations reused

Scene reducer and `SceneService` (one scene path, `apply_if` seam), `BrainContext` per-turn channel,
`jarvis-display` MCP + `mcp_tool_meta.DISPLAY`, `safe_folders` + `file_replace.replace_with_retry`,
`prompt_registry.fingerprint`, Test Lab lock pattern, `ConversationEventQueryService.search` (witness
prefilter), `JarvisSceneLayout.markdownBlocks`, Control Center relay/Origin guard pattern
(`CaptureRelayRoutes`), the dock full-screen view pattern (`.mcpi`/`.wsp`), the legacy window renderer
(kept). No second renderer, catalogue or event path (re-audited in S09).

## Residual risks

- Base-edit witness: a confirmation must be recorded by Core (voice); typed CC turns are refused.
- Iframe cost: bounded at 24 live frames; beyond, windows show a paused card until selected.
- Capture cannot rasterize frame content (title, `prefab id@version` and summary only).
- Downgrade: an older build cannot read a `scene.sqlite3` containing a `prefab` key (same as `annotation`).
- Brain-authored behaviour JS may be poor; sandbox + error band contain it; lint is not a boundary.
- 16 KiB payload bound limits long documents/tables (clear `prefab_invalid` detail).
- History: redacted strings remain in earlier commits of this branch (rewrite = Human decision).

## Issues (`Issues/`)

Open: `constellation-decision-1-forward-reference`, `legacy-window-item-labels-nowrap`,
`prefab-library-per-data-root`, `prefab-notify-events-do-not-wake-brain`,
`presentation-stager-reveal-calls-missing-set-visibility`, `rework-fenetres-no-durable-record`,
`scene-group-drag-lost-single-command`, `scene-selection-never-reaches-brain`. Partly resolved:
`scene-file-watcher-undocumented-unguarded` (documented and event-driven upstream; path guard and actor
remain). New in S09: `base-edit-witness-needs-core-intake`, `base-prefab-v1-publication-date`,
`prefab-relay-logs-each-rate-limited-request`, `library-preview-swap-keeps-two-frames`.

## Human checks

Do them on the live JARVIS after merging (the worktree's data root is separate:
Issue `prefab-library-per-data-root`). **A base-edit request or confirmation must be spoken, so that
Core records it**: typed in the Control Center chat, it is refused (`base_edit_unconfirmed`).

1. **HV-WINDOW-FAMILIES-01 — Confirm the base window catalogue or name the missing Rework FENETRES
   families.** No durable record of the Rework FENETRES families exists in the repository, so the base
   catalogue was decided from evidence: jarvis.window (generic window, parity with today's window),
   jarvis.document (read a long content in full, from the 2026-09-22 feedback) and jarvis.table (from the
   view_table proposal). After automated and browser QA are green, open the live Jarvis scene where the
   three base prefabs are placed next to a legacy window with the same content. (1) Confirm that
   jarvis.window looks and behaves like the current window (drag, resize, pin, selection) and that item
   labels are now readable. (2) Confirm the catalogue, or name the Rework FENETRES families that are
   missing or wrong. Any family you name is recorded as a follow-up task, not added to this one.
2. **HV-PREFAB-LIBRARY-01 — Validate prefab library management.** After automated and browser QA are
   green: first ask JARVIS out loud for a base edit, for example « modifie le prefab de base tableau :
   accent orange par défaut », so that a base prefab edited at your request exists. Then open the PFB
   library from the dock. Check that at a glance you can tell base prefabs, the base prefab edited at
   your request (amber), forks and custom prefabs apart, and that each fork shows which prefab it came
   from. Open the edited base: its history must quote your exact words. Preview the checklist, place it on
   the scene, then use 'Forker en nouveau prefab' with a fresh id such as perso.checklist-rouge; the new
   fork appears with its parent. Fork again with that same id: the library must say « Identifiant déjà
   pris » and publish nothing. Confirm that forking cannot be confused with modifying a base prefab: the
   library offers no base-edit button and explains that only JARVIS can edit a base, and only when you
   explicitly ask for it.
3. **HV-PREFAB-E2E-01 — Validate the end-to-end reusable object workflow with JARVIS** (last). After all
   machine QA and agent trace analysis pass, talk to JARVIS. (1) Ask it to show a checklist for a real
   task: it must reuse jarvis.checklist, not invent one. (2) Tick two items on screen, then ask JARVIS
   what is done: it must read the state. (3) Ask for a variant (for example a red accent and a priority
   on each item) and ask it to keep it: a new prefab is saved as a fork. (4) Open the library and find
   it. In a new session, ask for it by name and see it reused. (5) Ask JARVIS to 'improve the window
   prefab' without saying you want the base changed: it must make a variant or ask, not edit the base.
   Then explicitly ask it to modify the base jarvis.window: a new base version appears in the library
   with your quoted words. (S09 trace note: JARVIS may read "the window prefab" as the window on screen;
   say "le modèle de fenêtre générique" if it does.)
4. **Real-mouse drag and resize across prefab frames.** Since the S05 rework (gesture shield) the CDP
   mouse drags land exactly (S09 replay: 4/4 at 0 px), but no physical mouse has tried. With the real mouse: drag a prefab window by its head and by its grip, resize it, and drag
   another window across a prefab frame — the gesture must not be captured by the frame, and the window
   must land where released.
