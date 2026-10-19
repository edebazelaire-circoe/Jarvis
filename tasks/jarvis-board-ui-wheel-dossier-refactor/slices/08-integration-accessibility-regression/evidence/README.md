# Slice 08 — evidence, decisions, rollback

Sandbox of 2026-10-18/19: Core `127.77.0.1:28693` and Control Center `127.0.0.1:28694` started from the worktree
`C:/Projects/jarvis/wdr` (`PYTHONPATH` = the worktree), data and runtime roots under the session scratchpad `s08`,
`JARVIS_VISUALIZER_ENABLED=0`, `JARVIS_OPEN_BROWSER=0` (journal `ui.browser` `opened: false`: no tab opened in the
user's browser). The data root started as a **v8** `jarvis.sqlite3` shaped like this PC's real Boards (audit
Slice 00 §4). Only the sandbox PIDs were stopped (`taskkill /T`); the user's JARVIS was never touched.

## Files

| File | What it shows |
| --- | --- |
| `board-switches.log` | first start after the v8 → v9 migration, switches through Assistant / Réunion / Présentation by the page's route, Core restart: « Jarvis PRESENTATION » comes back in PRESENTATION (`board_restore`) |
| `agent-turns.log` | real model turns (Claude, through `/api/chat/turns`): read after a human Dossier correction, `dossier_view`, « retire du Board », Ranger |
| `hidden-archived-dossier.log` | Masquer, Afficher sur le Board, Ranger by the page's routes; scene snapshot and Dossier listing after them |
| `ferme-1920x1032-circuit.png`, `ferme-1440x900-cosmos.png` | main shell, both themes: Board card bottom-left, 4-button launcher, no top-left selector, no state badge, no mode control, no hidden chip |
| `roue-ouverte-1920x1032-circuit.png`, `roue-jarvis-…`, `roue-capture-…`, `roue-settings-1280x720-circuit.png`, `roue-dossier-1440x900-cosmos.png`, `roue-selection-600x800-circuit.png` | the five categories, one submenu each time (`visibleSubs` ≤ 1 at every step), three sizes, both themes |
| `panneau-boards-1280x720-circuit.png` | Board panel above the card (wheel closed: exclusive surfaces) |
| `clavier-capture-1280x720-circuit.png` | keyboard only: Enter on the anchor → JARVIS, ArrowDown ×3 → Capture, ArrowRight → first row focused |
| `roue-capture-1280x720-circuit-rm.png` | reduced motion |
| `refus-capture-375x667-circuit.png`, `refus-capture-500x800-circuit.png`, `refus-capture-1280x720-circuit-fc.png` | real refused screen recording (no ffmpeg): the note stops before the launcher (375: note 10-199 px, launcher from 211; 500: 10-324 / 336), forced colours |
| `selection-groupe-ranger-raison-1440x900-circuit.png` | Sélection on a group: « rien à ranger — … Un groupe n'est qu'un cadre : rangez ses objets un par un. » |
| `dossier-correction-enregistree-1440x900-circuit.png`, `dossier-liste-titres-1440x900-circuit.png`, `dossier-apres-ranger-1440x900-circuit.png` | human correction saved (« Enregistré. Jarvis lira cette version. »), a read note listed by its heading, Dossier after Ranger |
| `jarvis-ouvre-compte-rendu-1440x900-circuit.png` | the page after Jarvis's `dossier_view` (`opened` in 183 ms) |
| `dossier-core-arrete-1440x900-circuit.png` | Core stopped while the Control Center answers: Board card « Indisponible · Core ne répond pas », scene frozen; the Dossier said « Core ne répond pas… » (`coreLost: true`) before it was closed |

## Trace: Dossier ↔ agent parity after a human correction

1. The human edits `notes/decision-budget.md` in the real Dossier (`memory/write replace` with the read
   `expected_sha256`) and adds « Correction de Clarice (18 octobre) : la reconduction ne vaut que si l'abonnement
   annuel est retenu ; sinon, nouveau comité. » — flash « Enregistré. Jarvis lira cette version. »; the canonical file
   on disk carries it (`memory/read`, sha `1dfb5fed…`).
2. Turn « Que dit maintenant la note sur la décision budget ? » → `Read …\boards\board_a6ea9d38…\memory\notes\decision-budget.md`
   (the active Board « Projet Atlas », the very file the Dossier wrote) → the answer quotes the correction.
   **Parity holds** (the corrected canonical source, never a UI copy; right Board). **Not via `board_memory_read`**:
   the brain read the canonical path with `Read` (known since Slice 05) → `Issues/brain-behaviour-follow-ups.md`.
3. « Ouvre le compte rendu du comité dans le Dossier. » → `dossier_list` (Board `board_a6ea9d38…`) → `dossier_view`
   → `dossier.navigation.delivered` → `answered opened` 183 ms → « C'est ouvert. » (after the known « no visible
   output » retry, 36 s turn).
4. « Retire du Board la fenêtre « Brouillon à retirer ». » → `scene_query` → `scene_archive` → `archive_selection`
   (the wheel's Retirer); no Dossier write.
5. « Range la fenêtre « Idée slogan » dans le Dossier. » → `dossier_ranger` → `core.workspace.mutated memory_write
   create origin brain` → `core.dossier.mutated stored 1 archived 1 origin brain`, entry `notes/idee-slogan-c02b9612.md`.

No arbitrary filesystem bypass for writes: every write went through Core's workspace / Dossier services with the
active Board. The read in 2 is the only bypass seen (read-only, canonical path, the active Board's own memory).

## Decision → test or proof

| Decision | Machine proof |
| --- | --- |
| D01 fixed type | `test_workspace_board_contract.py::test_the_board_type_is_chosen_at_creation_and_designates_the_mode`, `test_board_kind_migration_v9.py` (whole matrix, the 3 real Boards of this PC); `board-switches.log` |
| D02 not editable | `test_board_service.py::test_the_board_type_is_chosen_at_creation_and_never_changed_by_an_update`, `test_boards_hud_js.py::test_edit_renames_only_the_type_is_never_offered_and_a_patch_is_painted_after_the_server`, MCP `board_kind_immutable` (`test_workspace_mcp.py`) |
| D03 no mode selector | `test_boards_hud_js.py::test_the_served_page_has_no_retired_shell_controls`; every writer refuses `interaction_mode_derived` (`test_interaction_mode_control_plane.py`, `test_settings_mcp.py::test_no_setting_describes_or_offers_a_mode`); sandbox audit `modeHud:false, modeChooser:false` |
| D04 Board card bottom-left | `test_boards_card_browser.py::test_a_pleine_largeur_la_carte_est_au_bord_gauche_sans_rien_recouvrir`, `test_global_launcher_browser.py::test_board_card_bottom_left_unchanged`; `ferme-*.png` |
| D05 no top-left selector, no state badge | `test_the_served_page_has_no_retired_shell_controls`, `test_control_center_shell_browser.py`; audit `topbar:false, state:false` |
| D06 no permanent hidden chip | `test_status_centre_browser.py` (no eye), Sélection › Masqués (`test_selection_actions_js.py`); audit `eye:false` |
| D07 five categories | `test_tool_wheel_js.py::test_five_categories_in_locked_order_and_no_retired_first_level` (no Vidéo/Capture d'écran/Audio/Boards/Fichiers/Recherche/Outils); audit `slots` |
| D08 one submenu | `test_tool_wheel_browser.py::test_one_category_tree_visible_keyboard_and_switching`; audit `visibleSubs` ≤ 1 at every sandbox step |
| D09 real graphic redesign | qualitative comparison below; human check HVAL-03-01 |
| D10 reference = style only | no reference-only entries in the wheel (D07 test); comparison below |
| D11 Capture is one category | `test_capture_rail_js.py` (category sum and rows), `test_capture_wheel_browser.py`; `roue-capture-*.png` |
| D12 transient indicators, audio + video together | `test_capture_wheel_browser.py::test_audio_and_video_independent`, `::test_video_toggle_rec_timer_survives_wheel_close_and_reload`, `::test_status_loss_keeps_stop_and_refuses_start`; sandbox `recHidden:true` with no capture |
| D13 Dossier shared by human and Jarvis | `test_dossier_service_api.py::test_a_human_edit_is_what_the_agent_reads_next`, `test_dossier_fullscreen_browser.py`; trace above |
| D14 not a technical dump | `test_dossier_fullscreen_browser.py` (advanced details behind a disclosure), `test_dossier_service_api.py` (human view by default) |
| D15 Masquer ≠ Ranger | `test_selection_actions_browser.py::test_masquer_is_one_patch_selection_and_never_reaches_the_dossier`, `test_dossier_service_api.py::test_masquer_never_creates_a_dossier_entry_and_show_hidden_is_visibility_only`, `::test_ranger_materializes_ephemeral_content_once_then_removes_the_representation`; `hidden-archived-dossier.log` |
| D16 Board and Dossier = two views | `test_dossier_fullscreen_browser.py::test_afficher_sur_le_board_presents_the_same_source`; sandbox: present then Ranger of `notes/arbitrages-licences.md` = `confirmed` (same file, no copy) |
| D17 no first-level search | D07 test; search lives in the Dossier (`memory/search`) |
| D18 no « Outils » catch-all | D07 test |
| D19 canonical owners, no fake state | `test_jarvis_wheel_js.py::test_unknown_before_the_first_beat_and_after_a_lost_beat_never_a_stale_fact`, `test_capture_wheel_browser.py::test_audio_toggle_start_stop_matches_status` (never checked before Core), `test_dossier_fullscreen_browser.py::test_core_stopped_while_the_control_center_answers_is_said_as_core_lost`, `test_status_centre_browser.py::test_a_lost_status_says_the_pill_counts_are_unconfirmed`; no placeholder left in the wheel (`test_tool_wheel_js.py`) |
| D20 completed-task lifecycle = Issue | `Issues/task-completion-lifecycle-follow-up.md` |
| D28 mouse, keyboard, Bare Hands kept | `test_tool_wheel_browser.py` (mouse, keyboard, Bare Hands plans; `::test_a_motionless_pointer_never_takes_the_keyboard_focus`), `test_selection_actions_browser.py::test_a_bare_hands_pointer_reaching_the_wheel_keeps_the_selection`, `test_selection_method_browser.py`; `clavier-capture-*.png` |

## Qualitative comparison with the two references

**`assets/current-ui-before.png` (what had to go).** Gone, checked on the real page: the top-left « BOARD
Présentation Jarvis » selector and the « VOICE SLEEP · CLAUDE RUNNING » badge, the large « MODE D'INTERACTION »
panel and « MODE SIMPLE » button, « 52 OBJETS MASQUÉS AFFICHER », the F9 capsule, the ten-icon dock. Now: one Board
card bottom-left (type + title), a four-button launcher (CNV, AGT, ERR, « Plus d'outils »), the wheel's thin anchor
on the left edge, the Chat tab. Permanent chrome dropped from about seven groups to three.

**`assets/style-reference-radial-ui.png` (direction, not spec).** Kept: dark navy glass, a left-anchored layered
half-disc with a luminous core, labelled sectors on one band, a selected sector outlined with a bright rim arc, a
curved glass submenu attached to the rim with an uppercase heading and icon-tile rows (title + note + chevron).
Deliberately different: one submenu only (the reference shows two, D08); no Boards / Fichiers / Recherche / Outils
(D07, D17, D18); no large glowing orb or heavy ring decoration; monospace type throughout (the reference mixes a sans
for row titles); smaller tiles. The JARVIS and Paramètres panels flare a little above / below their sector to keep
every row on screen at 720 px (QA S03 point 5, kept for the human). Visual judgement: HVAL-03-01, HVAL-09-01.

## Rollback

1. **Stop JARVIS** (the Human does it), then **set the bases aside, never delete them**: copy `jarvis.sqlite3`,
   its `-wal` and `-shm`, and `scene.sqlite3` with its own, to a dated folder.
2. **`jarvis.sqlite3` v9 → v8**: restore `jarvis.sqlite3.v8.bak` (written once before the v9 step, in
   `journal_mode=DELETE`, next to the base) as `jarvis.sqlite3`; leave no `-wal` / `-shm` of the v9 base next to it
   (a `-wal` set aside is never replayed into another base). Boards created after v9 stay only in the base set
   aside. `docs/boards.md` › *Persistence*, `docs/local-data.md`.
3. **Scene key `registry_artifact_id`**: an older binary refuses a scene payload carrying it (`check_wire_keys`).
   Before going back, archive the scene objects that carry it (windows presented from the Dossier for a registry
   Artifact), or keep `scene.sqlite3` set aside and start the older binary on a copy without them —
   `docs/dossier.md` › *Rollback*. No scene schema version changed (v1).
4. **Code**: revert the task's merge commit in `main` (or check out the previous `main`). No other data migration
   exists in this task; the Dossier is a projection (no table), the legacy `interaction_mode` key in
   `control-center-settings.json` was never removed (ignored since Slice 01b).
5. **Expected after rollback**: « Jarvis PRESENTATION » is again `presentation` with its stored `assistant` mode,
   i.e. it starts in SIMPLE as before this task.

**Expected at the first start after the merge** (no rollback): the v9 step runs once (`core.state.migrated`,
`jarvis.sqlite3.v8.bak`), « Jarvis PRESENTATION » keeps type Présentation and **starts in PRESENTATION mode**
(D22 rule 1, Slice 00 Q1; sandbox proof in `board-switches.log`), « Board principal » becomes Assistant, « Mon Q »
stays archived.
