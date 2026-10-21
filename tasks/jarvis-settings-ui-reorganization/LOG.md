# Execution Log

Reserved for durable execution notes written by the Project Manager and implementation agents while the task is running. Do not pre-populate progress.

## 2026-10-21 - Slice 00 (agent 0)

### Lifecycle fallback

No `docs/workflows/AGENT_TASK_LIFECYCLE.md` in the repository: Drive queue IDs and base branch come from project memory (base `main`, no `dev`). Worktree `C:/Projects/jarvis/setui`, branch `task/jarvis-settings-ui-reorganization` from `origin/main` `20292e5c` (= source SHA, no drift). Drive to-do -> current move requested from the Human (the Drive MCP cannot move folders).

### Handoff integrity

The Drive publication is incomplete again: folders of Slices 05-10 contained no file, and `references/current-settings-ui.png` is missing. Agent 0 authored Slices 05-10 (SLICE.md, metadata, human checks) strictly from docs 02/03/04/06/07 (Slice 00 authority to repair the plan); no new product decision. The screenshot is a before-state only: agents capture the live before-state in a sandbox if needed. Not blocking.

### Blind audit (current main 20292e5c)

Confirms `docs/06`: base `TABS` in `control_center.html` = voice, prompts, cli, keys, shortcuts, memory, subagents; injected: `wakeword` (`control_center_wake_word.js`, splice after voice), `appearance` (`control_center_work.js`, splice before `config`), `experimental` (`control_center_barehands.js` push). Discrepancies / additions not in the handoff:

1. `experimental` tab ID is shared by Bare Hands and `control_center_scene_settings.js` (scene test gate); `control_center_scene_page.js` also hooks into `renderTab`. Slices 06 and 08 must coordinate its removal.
2. `ui_tab_next` / `ui_tab_prev` shortcuts cycle the top-level `TABS`: must cycle the six categories (Slices 01/02).
3. Programmatic callers: `openSettingsTab` / `settingsTabs` used by the Jarvis wheel (Paramètres submenu built from `settingsTabs()`, `voice_settings` row opens `'voice'`). Covered by aliases (Slice 01) and cleanup (Slice 09).
4. Footer (Save) hidden for `subagents`; per-tab subtitle map `modalSub`; `cleanupSettingsSurface()` is the existing controller cleanup hook to reuse.
5. No in-flight branch touches the Settings files (all task/fix branches are at or behind origin/main). Worktree `eph` has uncommitted edits in `control_center.html`/`control_center_work.js` unrelated to Settings (ephemeral tasks): merge risk low, watch at close-out.
6. Canonical references all exist: `docs/settings/INDEX.md` (has a "Sous-agents tab" section to update), `docs/settings/memory.md`, `docs/voice-settings-schema.md`, `docs/subagent-roles.md`, old IA contract.

### Task Types

Workspace Task Type vocabulary still not exposed: resolved as `waived-by-agent-0`, same precedent as `jarvis-organic-agent-orchestration`.

### Skills and routing

`/caveman`, `/coding-guideline`, `/impeccable`, `qa-verification`, `code-review`, `runtime-validation` available. Sub-agents are Claude agents (host Agent tool): satisfies "Claude Work Agent" routing. Machine limits: at most 3 agents at once, tests in small foreground batches, one writer per worktree -> Slices run sequentially in `setui`.

### Settings regression suites (exact list)

`test_control_center_mvp`, `test_control_center_quality`, `test_control_center_voice_architecture`, `test_voice_settings_ui`, `test_wake_word_settings_ui`, `test_wake_word_settings_browser`, `test_agent_cli_settings_ui`, `test_routing_settings_screen`, `test_control_center_catalog_ui`, `test_control_center_memory_settings_js`, `test_control_center_subagents_settings_js`, `test_control_center_appearance`, `test_scene_settings_ui`, `test_scene_view_prefs`, `test_barehands_tools_settings_js`, `test_barehands_cards_js`, `test_jarvis_wheel_js`, `test_jarvis_wheel_browser`, `test_dossier_fullscreen_browser`, `test_control_center_mcp_inspector_js` (all under `tests/unit/`). Known failures already on main: `test_brain_capability_parity`, `test_brain_delegation` (not Settings).

### Readiness

**READY** (after context rework done in this Slice). Dispatch order: 01 -> 02 -> 03 -> 04 -> 05 -> 06 -> 07 -> 08 -> 09 -> 10, sequential in one worktree.

### Baseline sweep (before any dispatch, branch = main + handoff only)

Non-browser Settings suites: 361 passed, 1 failed. Pre-existing on main: `test_control_center_voice_architecture.py::test_async_browser_render_does_not_restore_a_previous_panel` (its `tabCli` stub ignores `tabAgenda`, which reads `agenda_reminders` from an undefined object). Not caused by this task; Slices must not count it as their regression, and may fix it if they touch that render path. Browser suites (`test_wake_word_settings_browser`, `test_jarvis_wheel_browser`, `test_dossier_fullscreen_browser`) deferred to the Slices that touch them and Slice 10.

## 2026-10-21 - Slice 01 (implémentation)

### Décisions

- Registre pur `jarvis/runtime/control_center_settings_registry.js` (`window.JarvisSettingsRegistry`, `module.exports`), inséré par `control_center.py` juste après `control_center_shell.js`, donc avant `TABS` et tout module de réglages. Aucun réseau, stockage ni DOM.
- Six catégories gelées ; le registre n'expose aucune fonction d'ajout de catégorie. `register` refuse par codes stables : `settings_section_invalid`, `settings_category_unknown`, `settings_section_duplicate`, `settings_alias_conflict`. Politique d'enregistrement explicite : `save` ∈ `footer|self|readonly`.
- Alias : `voice`, `wakeword`, `prompts`, `cli`, `routing` (déjà redirigé vers `cli`), `keys`, `shortcuts`, `memory`, `subagents`, `appearance`, `experimental`, chacun vers une catégorie/section principale + `also`. `experimental` → Labs (son nom, la scène, l'enregistrement, le banc d'essai) ; les préférences Bare Hands passent par `LEGACY_ANCHORS` (`barehandsSettings`/`barehandsCalibration` → `interface_interactions/bare_hands`).
- Adaptateur sans changement visuel : `canonicalSettingsTab` passe par `legacyTabFor` (un ID d'onglet actuel donne le même onglet ; catégories et sections cibles ouvrent l'onglet qui les sert) ; `openSettingsTab` signale une cible inconnue (`settings_target_unknown`) ; nouvelle `settingsNavigation()` (onglets actuels rangés sous les six catégories, `settings_tab_unassigned` sinon). `settingsTabs()`, `ui_tab_next/prev` et le rendu sont inchangés (Slice 02 : `cycleCategory`, six catégories dans la roue).

### Fichiers

`jarvis/runtime/control_center_settings_registry.js` (nouveau), `control_center.html`, `control_center.py`, `tests/unit/test_control_center_settings_registry_js.py` (nouveau), `docs/settings/navigation-registry.md` (nouveau, contrat canonique), `docs/legacy/settings-tab-aliases.md` (nouveau), `docs/settings/INDEX.md`, `tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json` (clé `navigation_superseded_by`, navigation conservée telle quelle pour le test d'intégration qui la lit).

### Tests

Nouveaux : 9 passés. Suites Réglages listées en Slice 00 (hors navigateur) + `test_settings_ia_contract`, `tests/integration/test_settings_redesign_migration.py`, `test_variants_css_orphans`, `test_remotion_no_fallback_privacy` : tout passe sauf l'échec déjà présent `test_async_browser_render_does_not_restore_a_previous_panel`. Suites navigateur non lancées (aucun changement visuel).

## 2026-10-21 - Slice 01 QA decision (agent 0)

QA (qa-verification + code-review, read-only, 10/10 mutations caught, page assembly via `ControlCenter.index()` checked): APPROVED, no blocking finding. Accepted: `experimental` primary alias -> `advanced_diagnostics/labs` (Bare Hands ordinary prefs via anchors); `save` policy mandatory (stricter than docs/02, documented); `openSettingsTab('routing')` now opens `cli` like `selectTab` already did (no repository caller). Carried into Slice 02 (needed by its routing): `legacyTabFor` returns null for same-category target sections `voice_output`, `microphone_sound`, `turns_interruptions`, `semantic_retrieval`, `consolidation`, `knowledge_sources`; misleading "page partielle" comment on the `typeof TABS` guard in `canonicalSettingsTab` (TDZ, guard is illusory).
