# 08 — Slice 00 readiness audit (HEAD reconciliation)

Written by Slice 00 on 2026-10-17. This page supersedes the planning pointers of
`README.md` › *Existing architecture discovered at planning time* wherever they
disagree. Every later Slice reads it before its own `SLICE.md`.

## 1. Baseline

- Branch `task/jarvis-board-ui-wheel-dossier-refactor`, worktree `C:/Projects/jarvis/wdr`,
  audited HEAD `2fb66040` (= local `main@8a14f06e` + merge of `origin/main@cd5dfa47`).
  `git fetch` on 2026-10-17: `origin/main` is still `cd5dfa47`, HEAD is 26 ahead / 0 behind.
- Planning reference `cd5dfa47` only held the orbital-ui task **up to its Slice 04
  merge (`0ab33d84`)**. The 23 commits `b048542d..3ac713bf` (orbital S04 polish, S05-S10)
  are in HEAD but were not seen by the planner. What they changed is in §3.
- Schema: `jarvis.sqlite3` is at `_SCHEMA_VERSION = 8` (`jarvis/adapters/sqlite_state.py`),
  snapshots `tests/schema/jarvis_state.v3..v8.sql`; `scene.sqlite3` at v1.

## 2. Owners at HEAD (blind audit)

| Concern | Owner at HEAD | Contract / tests |
| --- | --- | --- |
| Board, `BoardKind{empty, meeting, presentation}`, per-Board `interaction_mode` + `InteractionModeOrigin{unset, migrated, user}` | `jarvis/domain/workspace_board.py` (pure), stored as JSON in `work_boards.data` by `jarvis/adapters/sqlite_workspace_board.py` (no column for either field) | `docs/boards.md` › *Board kind*, *Interaction mode per Board*; `test_workspace_board_contract.py`, `test_board_store_sqlite.py`, `test_board_service.py`, `test_board_protocol.py`, `test_board_switch.py` |
| Board create/update/switch, mode persistence listener, `board_restore` / `board_switch` re-application | `jarvis/core/board_service.py` | `docs/boards.md` › *Switch transaction* |
| Live effective mode (revision, epoch, event `interaction.mode.changed`) | `jarvis/core/interaction_mode.py` (`InteractionModeService.request`), routes `GET/POST /v1/interaction-mode` in `jarvis/protocol/server.py` | `docs/interaction-mode.md`; `test_interaction_mode_control_plane.py`, `test_interaction_mode_protocol.py`, `test_interaction_mode_follower.py` |
| Legacy global mode key + replay `startup`/`core_restart`, `POST /api/interaction-mode` | `jarvis/runtime/interaction_mode_settings.py`, `jarvis/runtime/control_center.py`, `jarvis/runtime/interaction_mode_view.py` | `test_interaction_mode_control_plane.py`, `test_control_center_presentation_status.py` |
| Voice follower | `jarvis/runtime/interaction_mode_observer.py`, `jarvis/runtime/voice_v2.py`, `jarvis/runtime/speech_scheduler.py`, presentation runtime modules | `test_interaction_mode_follower.py`, `tests/integration/test_presentation_scenarios.py` |
| Brain surfaces that mutate mode/kind | `settings_set("interaction_mode")` in `jarvis/runtime/settings_mcp.py`; `board_create`/`board_update(board_kind)` in `jarvis/runtime/workspace_mcp.py` / `workspace_boards.py`; prompt line in `jarvis/runtime/claude_local.py:245` (« passe en mode présentation… ») ; perception `jarvis/runtime/tool_brain_perception.py:374-378`, `tool_brain_choices.py:218` | `test_settings_mcp.py`, `test_workspace_mcp.py`, `test_mcp_catalog.py` |
| Presentation Studio run transient mode | `jarvis/domain/presentation_studio_roles.py` (`plan_mode_entry`), source `presentation_studio_run` (transient, never persisted) | `docs/presentation-studio.md` › *Playback roles and speech authority* (Decision A); `test_presentation_studio_roles.py`, `test_variants_run_*` |
| Mode HUD (bottom-left) incl. Voice presence report (« Refusé par la voix », deaf session, mic failure) and « way out of PRESENTATION » during a Variants run | `jarvis/runtime/control_center_interaction_mode.js` (1 575 lines); kept live over Variants by `data-keep-live="run"` / `html.jvx-run` (`control_center_presentation_studio_explorer*.js`, registry rank 9150); Studio reload band measures `#interactionModeHud` (`control_center_presentation_studio_reload.js`) | `test_interaction_mode_hud_js.py`, `test_interaction_mode_hud_browser.py`, `test_variants_run_browser.py`, `test_variants_run_surface_docs.py` |
| Board quick control (top-left, in `.topbar`) | `jarvis/runtime/control_center_boards.js` (`#boardsHud`, `#boardsPanel`, kind badges `Générique/Réunion/Présentation`, kind on create **and edit**) | `docs/boards.md` › *Control Center Boards control*; `test_boards_hud_js.py`, `test_boards_hud_browser.py`, `test_boards_status.py` |
| Shell zones, layer registry, controls | `docs/control-center-shell.md` (Level 3), `jarvis/runtime/control_center_shell.js` (`JarvisShell.ZONES`), tokens in `control_center.html` | `test_control_center_shell_layers.py`, `test_control_center_shell_browser.py` |
| Orbital wheel | `jarvis/runtime/control_center_tool_wheel.js` (`SLOTS` 4 wedges, pure `reduce`, `register`, `setStatus`, radial sub-arc + second level **in place of** the first) | `test_tool_wheel_js.py`, `test_tool_wheel_browser.py` |
| Selection method (Mouse / Bare Hands) | `jarvis/runtime/control_center_input_arbitration.js` (`register({id:'selection', menu:true})`) | `test_selection_method_browser.py` |
| Capture | Core `CaptureService` (truth); page `control_center_capture_rail.js` (controller), `control_center_capture_wheel.js` (wedges Vidéo/Capture d'écran/Audio + `#recIndicators`) | `docs/capture.md`; `test_capture_*`, `test_capture_wheel_browser.py`, `test_capture_rail_js.py` |
| Status centre (bottom-centre) | page: `#recIndicators` \| `#bgPills` \| `#hiddenEye` | `test_status_centre_browser.py` |
| Hidden objects | Core scene `visibility hidden` (canonical); browser view pref `showHidden` (ghosts) in `control_center_scene_view.js`; eye + hidden list (`openHiddenMenu`, « Tout réafficher ») in `control_center_scene_page.js` | `docs/scene-model.md` › *Visibility vs disposition*; `test_scene_view_prefs.py`, `test_scene_renderer_logic.py` |
| Scene selection batches | `jarvis/domain/scene.py` (`patch_selection` visibility/representation, `archive_selection`, `archive_many` orphan rule), `jarvis/runtime/display_mcp.py` (hide guard) | `docs/scene-selection-batch.md`; `test_scene_selection.py`, `test_scene_batch.py`, `test_scene_batch_tools.py` |
| Board memory + Artifact links | `jarvis/domain/board_memory.py`, `jarvis/adapters/board_memory_store.py`, `jarvis/core/workspace_service.py`, `jarvis/adapters/sqlite_board_artifact_links.py` (v8), MCP `jarvis-workspace` | `docs/boards.md` › *Board memory*, *Workspace inspection API*, *Board memory mutations*; `test_board_memory_*`, `test_workspace_inspection_api.py`, `test_workspace_memory_mutations.py`, `test_workspace_mcp.py`, `test_board_artifact_links.py` |
| Technical Sessions & Boards manager | `jarvis/runtime/control_center_workspace.js` (`.wsp`, launcher « Plus d’outils » › WSP) | `test_workspace_manager_js.py`, `test_workspace_manager_browser.py` |
| Global launcher | page `.dock`: row CNV, AGT, ERR, **SET**, « Plus d’outils » | `test_global_launcher_browser.py` |

## 3. What orbital-ui S04-polish..S10 changed (unseen by the planner)

| Area | State at HEAD | Consequence for this handoff |
| --- | --- | --- |
| Hidden objects | The scene note « N objets masqués — afficher » (in `current-ui-before.png`) is **already gone** (S06). It was replaced by a **permanent** eye `#hiddenEye` in the bottom-centre status centre (count only in its label, ghosts view pref, hidden list on secondary). | D06 still applies: the eye is a permanent hidden-object toggle. Slice 02 removes `#hiddenEye` from the status centre; Slice 06 moves « Afficher les masqués (N) » (= the `showHidden` ghosts pref) and the hidden list (« Tout réafficher » = canonical `set_visibility visible`) into Sélection. The ghost rendering is reused, not rewritten. |
| F9 capsule | Gone (S06). The wake hint now lives as the `.state` line's `title`/`aria-description` (`setWakeHint`). | Removing `.state` (D05) must re-home the wake-key hint (JARVIS submenu, Slice 04) — otherwise F9 becomes undiscoverable. |
| Background pills | Moved into the status centre (S06). | Unaffected; status centre keeps the pills. |
| Recording indicators | `#recIndicators` already transient (one chip per **open** Core capture, Core duration, activation stops it), bottom-centre in the status centre; right-edge column at ≤ 700 px. | Slice 04 reuses them; the human asked for video REC « en haut à gauche » → relocate to the top-left zone freed by Slice 02 (not a new HUD). |
| Launcher | 10-button dock → row CNV/AGT/ERR/SET + « Plus d’outils » (S08). D11 kept Board in the top line pending HV-08-01. | HV-08-01 is now answered by D04 (Board bottom-left). `SET` duplicates the wheel's Paramètres: Slice 02/04 fold `SET` into « Plus d’outils » (shortcut `s` kept), wheel Paramètres opens the same `#openSettings` route. |
| Geometry coupled to the mode control | Status centre side insets `--shell-gutter + 254 px`, screenshot preview rung, `.sc-status` rung `max(52px, --sc-status-h + 28px)`, Bare Hands badge second rung, Board drop tray centring, Studio reload band placement all measure the bottom-left mode control. | Slice 02 replaces those references with the Board card's geometry in the same commit (registry + conformance tests). |
| Integration matrix | `docs/control-center-shell.md` › *Integration matrix (Slice 09)* and `test_control_center_shell_browser.py` (889 added lines) assert the current layout at 1440×900, 1280×720, 900×600, 600×800. | Every UI Slice updates the matrix rows it invalidates; Slice 08 re-runs the whole matrix. |

## 4. BoardKind / InteractionMode — real storage and migration plan

**Real storage.** Both `board_kind` and `interaction_mode` (+ `interaction_mode_origin`)
are keys of the JSON payload in `work_boards.data`; `work_boards` columns are only
`board_id, status, created_at, updated_at, data` (v3 DDL). Decoding is strict
(`_strict_keys`, `_parse_enum`). A payload without `board_kind` decodes as `empty`.
The global legacy key lives in `runtime/control-center-settings.json` (`interaction_mode`).

**Real data on this PC** (read from a scratch copy of the live DB, deleted after):
three Boards — `default` « Board principal » (`empty`, mode `assistant`, origin `user`),
archived « Mon Q » (`empty`, `assistant`, `unset`), active
« Jarvis PRESENTATION » (`presentation`, mode `assistant`, origin `user`).

**Plan (Slice 01a).**

1. `BoardKind` becomes `{assistant, presentation, meeting}`, default `assistant`
   (D21: evolve, no parallel `BoardType`). User labels Assistant / Présentation / Réunion.
2. New versioned migration `_MIGRATIONS[9]` in `jarvis/adapters/sqlite_state.py`,
   `_SCHEMA_VERSION = 9`: one data-only `UPDATE work_boards SET data = json_remove(json_set(data,
   '$.board_kind', <CASE>), '$.interaction_mode', '$.interaction_mode_origin') WHERE …`
   (JSON1 is available: SQLite 3.50.4; `json_set` already used in this file). `<CASE>`:
   kind `presentation|meeting` → kept; kind `empty`/absent **and** origin `user|migrated`
   **and** mode `presentation|meeting` → that mode (D22 rules 3-4); otherwise `assistant`.
   Idempotent (a second run changes nothing) and guarded by the version row.
   Automatic pre-migration copy `jarvis.sqlite3.v8.bak` (existing mechanism).
   An `unset` Board ignores the global key: at HEAD an `unset` Board already behaves
   as assistant on switch, so behaviour is preserved.
3. No DDL change, but the version still moves, **on purpose**: a v8 binary would
   crash decoding `board_kind: "assistant"` (strict enum); with v9 it refuses the file
   (« newer than supported ») instead. Snapshot `tests/schema/jarvis_state.v9.sql`
   (same DDL as v8) written with `JARVIS_WRITE_SCHEMA_SNAPSHOT=1 pytest
   tests/unit/test_schema_migrations.py` and committed with the migration. Add a
   migration test with legacy payload fixtures for the whole matrix of
   `docs/04-testing-and-quality.md` plus the idempotency re-run.
4. Domain: `interaction_mode`, `interaction_mode_origin`, `InteractionModeOrigin`,
   `set_interaction_mode`, `adopt_legacy_interaction_mode` leave `Board`; storage decoding
   stays strict (no `empty` after v9). API input: `board_kind` required-or-defaulted on
   create (`assistant` when omitted); `empty` accepted on create only as a deprecated
   alias of `assistant` (documented, never stored). `board_kind` leaves `EDITABLE_FIELDS`:
   a `PATCH` carrying it gets a stable refusal (new code, e.g. `board_kind_immutable`, 409).
   MCP `board_update` loses `board_kind`; `board_create` keeps it.
5. Diagnostics: Core start logs one `core.board.kind_normalized` summary only if Slice 01a
   chooses a Python step (the runner today executes SQL strings; extending it to accept
   a callable step is allowed but must keep one transaction per step).
6. Rollback: restore `jarvis.sqlite3.v8.bak` (never delete the v9 file without a copy), revert
   the code. Written in `docs/boards.md` › *Persistence*.

**Plan (derived interaction mode).** Items 1-2 land in **Slice 01a** (they cannot be separated from removing the stored mode fields); items 3-5 are **Slice 01b**.

1. `InteractionModeService` stays as the internal live seam (Voice, speech scheduler,
   presentation runtime, Studio consume it unchanged — D23). Its baseline is set **only** by
   `BoardService` from the active Board's kind at Core start and on every switch:
   assistant → `assistant`; presentation → `presentation`; meeting →
   `behaving_interaction_mode(meeting)` = `assistant` with an explicit
   `meeting_planned` status (never a refused request, so a switch to a Meeting Board never
   rolls back — today a stored `meeting` would).
2. Persistence listener (`_persist_mode`, `with_unchanged`) and `NON_PERSISTED_SOURCES`
   logic are deleted: nothing writes a mode on a Board any more.
3. Transient Studio runs keep `source="presentation_studio_run"` and restore to the
   Board-derived baseline (Decision A of the Studio stays valid; it is an activity, not a user
   mode toggle). `foreign_change` classification still works.
4. User-facing writers retired: Control Center `POST /api/interaction-mode` and its replay
   (`startup`/`core_restart`/`save_retry`), global key writes in `interaction_mode_settings.py`
   (the key is left in the file, ignored), `settings_set("interaction_mode")` item of
   `settings_mcp.py`, prompt line `claude_local.py:245` (rewritten: behaviour follows the
   Board type; to present, open/create a Présentation Board). Core `POST /v1/interaction-mode`
   accepts only the transient Studio source (other sources → stable refusal, e.g.
   `interaction_mode_derived`, 409). `GET` routes and `/api/status.interaction_mode` stay
   read-only for display.
5. Agent-visible surfaces change → `agent-trace-analysis` required (real trace: « passe en
   mode présentation » must lead to Board creation/switch guidance, never a mode write).

## 5. HUMAN-CHECKS of `jarvis-board-orbital-ui-workspace-rail` that become obsolete

Obsolete (superseded by this task; do not ask the Human): HV-01-01, HV-02-01, HV-04-01,
HV-06-01 (eye part), HV-06-02, HV-06-03, HV-06-06, HV-06-07, HV-06-08 (mode-button wording),
HV-06-09, HV-08-01 (answered by D04), HV-09-01, HV-09-06, HV-10-01; HV-09-02..05 and
HV-06-04/05 in their current wording (they name the mode selector, the eye and the top
Board row) — re-written as this task's Slice 09 accessibility checks.

Still valid (can be done now or folded into this task's Slice 09): HV-03-01 (Mouse /
Bare Hands arbitration), HV-05-01..05 (screenshot preview, incl. the real-turn HV-05-02),
HV-07-01 (rail), HV-08-02..05 (launcher, unless `SET` moves), HV-09-07, HV-09-08.

## 6. Dossier (step 9) — what exists and what is missing

Exists and is reusable as-is: memory `tree/stat/read/search/write(create|replace|append,
expected_sha256)/mkdir/move/delete` (Core `/v1/workspace/boards/{id}/memory/*`, relay
`/api/workspace/...`, MCP `board_memory_*`), Board-linked registry Artifacts list/link/unlink
(v8), artifact relations/provenance, presentation sources per Board, `session_activity`
family `board` (`board.memory.written`, `.moved`) for « what changed », windows bound to a file
(`payload.source_path`, watcher), archived-Board read-only rule.

Genuinely missing (Slice 05 scope):

1. A composed **Dossier listing** (memory entries + linked Artifacts as one human-facing
   entry list with kind/title/modified/preview capability) exposed identically to the UI
   and MCP (today an agent must call `board_memory_tree` + `board_artifacts` and merge).
2. A **scene → durable backing** resolver: scene payloads carry no registry `artifact_id`
   nor Board-memory locator (only `source_path`, an absolute file path). Note the naming trap:
   a *scene artifact* (`kind=artifact`, payload title/summary/items, lives only in the scene)
   is not a *registry Artifact* (`artifacts` table). Ranger of a scene artifact or note =
   materialize its payload once into Board memory (Markdown, provenance) via `memory_write`.
3. A composed **Ranger** operation (durable confirm → then `archive_selection`) with per-item
   result; no such service exists.
4. A **present-from-Dossier** operation creating/reusing a scene object pointing at the same
   source (window with `source_path` for a memory file is reusable; a registry Artifact needs
   a scene reference field — JSON payload key, no scene DDL).
5. An **agent → UI navigation seam** to open/focus Dossier entries (precedent: the Studio
   explorer channel that opens Variants on a voice-started run).

No new table is needed for any of these.

## 7. Hidden vs archived (step 10)

Confirmed at HEAD: hidden = active, not rendered, recoverable (`set_visibility`), plus a
browser-only ghost view; archived = out of `SceneSnapshot.objects`, tombstone, history.
Batch ops exist: `patch_selection {visibility, representation, …}`, `archive_selection`,
`archive_many` (orphan scene artifacts only), MCP hide guard. No third disposition is needed;
Dossier durability is a separate dimension. Destructive durable deletion already exists only
as `memory/delete` (confirm policy) — never through scene archive.

## 8. Other active work that touches the same files

- Drive `to-do`: this task and `jarvis-board-orbital-ui-workspace-rail` (still in to-do though
  merged in local `main`; recette pending). `current`: unified-chat-and-board-drop,
  interactive-presentation-studio, scene-window-prefab-foundation, memory-intelligence-knowledge
  — all already merged into HEAD; none edits the same files concurrently.
- Worktree `C:/Projects/jarvis/eph` (`task/jarvis-ephemeral-tasks@39ea9909`, already an ancestor
  of HEAD) holds **13 uncommitted files** dated 2026-10-07 (runtime archive of completed
  ephemeral stars in `jarvis/domain/scene.py`, `control_center.html`,
  `control_center_scene_layout.js`, `control_center_work.js`, `agent_tasks.py`, …). It overlaps
  this task's `Issues/task-completion-lifecycle-follow-up.md` and the files of Slices 02/06.
  Not touched by Slice 00. Its fate is a Human decision; until then it must not be merged
  into this branch.
- Other worktrees (`bor`, `boqa`, fix branches under `.claude/worktrees`) are task-complete
  or unrelated; `bor`/`boqa` can be cleaned once orbital-ui closes.
