# Slice 15 — Cleanup, migration and documentation

Base `c486eae7`. Work Agent, 2026-10-12. Commits: `2d8cb83b` (old-presentation fixture and test), `c6ecf553` (code), `96c752c6` (docs),
then this file, the evidence and the LOG entry. Canonical doc: `docs/presentation-studio.md` › *Retirement map and migration readers
(Level 3, Slice 15)*; this file holds the proofs behind it.

Task Type: none in this repository (waived by agent 0, READINESS). No schema change, **no migration**, no Jarvis restart needed for data.
The page code changed (`control_center_presentation_studio_player.js`, `_explorer_core.js`, `control_center_remotion_stage.js` comment) and
an MCP description changed: a Control Center reload and an MCP server restart pick them up whenever the Human next restarts; nothing breaks
before.

## 1. Re-audit on HEAD (what was looked for, what was found)

Searched with `git grep` on `jarvis/`, `tests/`, `docs/` at `c486eae7` (commands in `evidence/README.md`).

| Looked for | Found on HEAD | Verdict |
| --- | --- | --- |
| Floating viewer: `studio_stage`, `studio_aux`, `STUDIO_STAGE`, `studio-stage-*` | Core `presentation_studio_stage.py` (`LegacyStageReclaimer`, `StageLedger`, `LEGACY_CATEGORIES`), adapter `file_presentation_studio_stage_ledger.py`, page `RETIRED_CATEGORIES`, Tool Brain guard, sanitizer pattern; `STUDIO_STAGE_MEDIA_*` in `control_center.py` is the unrelated Variants stage-media module | **kept: migration readers** (§ 3) |
| Band `#jvStudioBand`, `JarvisStudioPlayer` band API | only in a history comment of `player.js`; the client keeps `chain()` (the band's « ▶ Slide / ▶▶ Tout » toggle) exported on `window.JarvisStudioPlayer.chain` | `chain` **removed** (no caller, § 2) |
| Window host `JarvisPresentationWindow`, `control_center_presentation_window.js` | file gone (Slice 09); one history comment in `rail.js` | nothing to remove |
| Old transports: `rs-bar` | `control_center_remotion_stage.{js,html}` only, built when the stage page has no `embed` | **kept** (§ 4 decision); stale comment fixed |
| Fullscreen `onNavigate` / `keys: "host"` | generic module `control_center_fullscreen.js`, route `POST /api/fullscreen/commands` accepts `keys`; no presentation caller (Variants passes `none`) | **kept**: public API of a generic module, reachable by the route; docs corrected |
| 8 s dwell / loop controls, « 8 s par slide », second transport row | no code; `target_duration_ms` dwell in `presentation_studio_autoplay.py` paces only items without a media segment (contract § 4) | nothing to remove |
| Variant bar `jvx-vbar`, tree hint | tests and docs only (absence assertions) | nothing to remove |
| Retired MCP verbs | `window_open/close`, `stage_fullscreen_enter` retargeted to Variants (Slice 09); Core refuses `open_window/close_window` 400 | **kept** (old brains / traces) |
| Orphaned CSS (`.jvx-*` rules whose class no module builds) | `.jvx-upgrades` (the notice is `.jvx-upg`) and `.jvx-scene-role`, both born in Slice 10 (`1be16cb8`) | **fixed / removed** (§ 2) |
| Unreferenced functions | Python: every `def` of the playback / run surface / stage / reload-stage / preview / autoplay / rail / MCP modules is referenced at least twice in `jarvis/`. JS: none in the presentation, rail, Remotion, prefab-host, fullscreen modules (two named IIFEs only) | nothing |
| Orphaned tests | no skipped or xfail test of a retired surface; « run stage » test names in `test_presentation_continuous_playback_browser.py` already target Variants | nothing |
| Stale docs and operator steps | `presentation-studio.md` (rs-bar, play-on-ready, `chain`, `keys: host`), `OPERATIONS.md` (Variants opened from the band, refused / closed during a run, band fullscreen), `presentation-speculative-preparation.md` (stage window as current), `ARCHITECTURE.md` (reload follows the stage window) | **corrected** |

## 2. Removal inventory

| Removed / changed | Proof it was unreachable or wrong | Test |
| --- | --- | --- |
| `createStudioPlayer().chain` and `window.JarvisStudioPlayer.chain` (`control_center_presentation_studio_player.js`) | `git grep "\.chain("` on `jarvis/`: no caller (the only `.chain(` calls are the prefab library's and the score's, other objects); its only user was the band, deleted by Slice 09. Core's `play {scope}` verb is untouched (Variants, MCP and voice use it directly). | `test_presentation_studio_player_js.py::test_start_run_uses_the_voice_route` (asserts `chain` undefined) |
| `#… .jvx-stage-note .jvx-scene-role` (narrow-preview rule) | no module builds `jvx-scene-role`; the role chip is `.jvx-chip` inside `.jvx-scene-line`, which the same rule already hides | `test_variants_css_orphans.py::test_every_variants_style_rule_names_a_class_the_page_builds` |
| `[data-run] .jvx-upgrades` → `[data-run] .jvx-upg` | the upgrade notice is built as `section.jvx-upg` (`explorer_upgrades.js:85`); the Slice 10 contract says the run dims it; it was never dimmed. Mutant (rule put back to `.jvx-upgrades`) fails both tests of the file. | `test_variants_css_orphans.py` (2 tests) |
| `jarvis-presentation` descriptions: « explorateur ouvert » → « Variantes ouvert », « + explorateur » → « + Variantes »; module table row | stale wording left by Slice 10 for budget reasons | `test_presentation_retirement_map_docs.py::test_the_presentation_tools_declare_variantes_not_explorateur`, `test_mcp_catalog.py` |
| Comment in `control_center_remotion_stage.js` (« the run stage keeps its bar until Slice 09 ») | Slice 09 done | — |

MCP budget moved: declared surface 113 521 → **113 495 B** (budget 113 700: 205 B left, was 179); `jarvis-presentation` 20 888 → **20 862 B**
(budget 21 000). Measured with the catalogue fixture of `test_mcp_catalog.py`.

## 3. Kept for migration, and why

| Kept | Why | Can go when |
| --- | --- | --- |
| `LegacyStageReclaimer`, `StageLedger`, `FileStageLedger` | a data root that ran a Core older than Slice 09 may hold `studio-stage-*` / `studio-aux-*` Board objects and the id ledger; they are archived once, the ledger kept aside `.retired-<ts>` | never provable per PC; cost is one bounded scan at Core start |
| `RETIRED_CATEGORIES` (scene layout), `LEGACY_CATEGORIES` (Tool Brain, `studio_owned`) | until archived, such an object must stay invisible and untouchable | same |
| sanitizer pattern `studio-stage-[\w-]+` | an old template may name a stage handle | same |
| Core 400 on `open_window` / `close_window`; MCP `window_open` / `window_close` as Variants windowed | an older brain, script or trace keeps working or is told | when no brain prompt or trace uses them (not measurable here) |
| `StageError`, `StageWindows`, `stage_object_id` names | still the run surface's error type, the reload's binding table and the view field (renaming = churn without user value, and `stage_object_id` is in MCP inspect answers) | a later rename Slice, if wanted |
| `rs-bar` on Board Remotion prefab windows | § 4 | — |

**Old presentations open and play** (SLICE step 3). `tests/fixtures/presentation_studio_task_base_a8377529/` was written by the task base
code itself: a pytest run inside a detached worktree at `a8377529` (generator below) assembled a 3-scene Remotion deck through the real
authoring door, made a 3-scene window presentation with a score and an art direction, branched a variant, and copied what Core wrote
(`presentations/`, `prefabs/`; SQLite bases excluded, repo rule; LF pinned in `.gitattributes` because prefab fingerprints hash bytes).
A stage ledger in the base format is added. `test_presentation_studio_task_base_data.py` (2 tests) proves on HEAD: both presentations
listed, graph with the branch, every variant and score read (`problems == []`), composition clock 3 scenes / 900 frames, documents
**byte-identical** after opening; both play in the Variants run surface (`variants-run-*`, scene 1 then 2, no Board object), and the old
ledger is read once and kept aside. Saved view state, playlist ownership and variant metadata: no format changed in this task (diff
`a8377529..HEAD` of `jarvis/domain` / `adapters` / `core`: no change to the presentation, variant, score, art-direction or scene documents;
Slice 13's `brief.authoring` is a draft field). Import/export path: unchanged formats (Slice 12 publish creates ordinary new source versions).

Generator (run from the base worktree, not committed):

```python
# tests/unit/test_zz_s15_gen_fixture.py at a8377529, S15_OUT=<dir>
core, world = await open_world(tmp_path); deck = await assemble_deck(world, count=3)
await core.call("POST", f"/{deck.pid}/variants", json={"title": "Branche courte"})
# then copytree(tmp_path, out, ignore *.sqlite3*, *.token)
```

## 4. Decisions (decided by agent 0's Work Agent unless noted)

- **`rs-bar` kept on Board Remotion prefab windows.** Slice 09 flagged it. Without `embed` the stage page is a Remotion prefab placed on the
  Board (not a presentation); its bar is that window's only transport, so it is not a duplicate owner. Removing it would leave such a window
  with no control. The test pins it to the stage page only.
- **`onNavigate` / `keys: "host"` kept**: public API of the generic fullscreen module reachable through `POST /api/fullscreen/commands`;
  not provably dead. Flag: with `keys: "host"` and no listener, the navigation keys are consumed and do nothing (pre-existing, no product
  caller passes `host` today).
- **No feature flag** (agent 0): nothing retired has a switch back; Slidecar unchanged (explicit Human experiment, no fallback).
- **One retirement index** in `presentation-studio.md`, older per-Slice maps kept for detail; the index wins.
- **Issue 01**: I2 (run slider without thumb/fill), I3 (Tab never reaches the header), I4 (media fullscreen browser flake), I5 (Enter on
  the Studio confirmation) are **not cleanup**: they are UI defects or flakes of live surfaces, not dead or duplicate code. Left to Slice 16's
  release sweep. The `.jvx-upgrades` orphan rule found here is a Slice 10 defect of the same family; it was fixed here because it is an
  orphaned selector (cleanup scope).

## 5. Licensing note (SLICE step 4)

Facts, not legal advice; the decision stays the Human's. Source: `node_modules/remotion/LICENSE.md` of the gate runtime (Remotion
4.0.534, SHA-256 `bd65083b…b673`), the same file in `@remotion/player`, `renderer`, `bundler`, `cli`, `web-renderer`; `@remotion/studio`,
`studio-server` and several helpers declare MIT; `@remotion/sdk`, `studio-protocol`, `media-parser` « Remotion License ».

- Free License: individuals, for-profit organisations with **up to 3 employees**, non-profits, and evaluation before commercial use; videos
  and images may be made commercially; selling or relicensing a derivative of Remotion is not allowed.
- Company License: required for every other entity (remotion.pro). The file announces a change in Remotion 5.0.
- This task's use: Player, renderer and native Remotion Studio run locally from the user's own install; Jarvis distributes no Remotion
  code, passes no `licenseKey` (in 4.0.534 `renderMedia` sends a usage event only when one is passed).
- The existing gate is **kept**: `docs/remotion-integration-release.md` › *Remotion licence* (now with these facts) and Human check row 0
  (HV-22-02). Nothing here decides the tier.

## 6. Rollback plan

- Code: revert `c6ecf553` and `96c752c6` (and the task's earlier Slices if needed). No data step: no format or schema changed.
- Data written by this task's Slices that an older Core does not read: the ledger renamed `<file>.retired-<ts>` (its ids are already
  archived; rename it back only to make an older Core re-read it) and unpublished Remotion Studio edits in the workspace or `studio-edits/`
  (Slice 12; copy them out first). Before any rollback: copy `presentations/`, `prefabs/`, `state/` of the data root (repo rule).
- No parallel UI is kept to fall back on, by design.

## 7. Validation

Slice tests and the wide sweep: `evidence/README.md`.
