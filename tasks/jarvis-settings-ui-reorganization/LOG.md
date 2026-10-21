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

## 2026-10-21 - Slice 02 (implémentation)

### Décisions

- Shell plein écran (`#overlay` › `#settingsShell`) : rail des six catégories dessiné depuis le registre (`shellNavigation`, jamais une liste recopiée ; seuls pictogramme et teinte par ID dans la page), colonne principale : intro de la catégorie, entrées de la catégorie (`#modalTabs`), liens « encore dans » (`related`), phrase de l'onglet (`#modalSub`), contenu seul à défiler, pied Enregistrer. Texte courant en sans-serif, monospace réservée à `code/kbd/samp/pre`. Identifiants historiques conservés (modules et tests hérités).
- Adaptateur : chaque catégorie liste d'abord ses sections enregistrées, puis les onglets hérités qui lui reviennent (rendus par `renderTab` et les modules injectés, inchangés). Un onglet hérité encore présent s'ouvre lui-même ; il cède sa place à la section qui le déclare en alias. Onglet sans alias rangé dans Avancé (atteignable) et journalisé une fois.
- Emplacement `SET.category` + `SET.section` XOR `SET.tab`, mémoire de la dernière entrée par catégorie ; `ensureSettingsLocation` absorbe les modules qui posent `SET.tab` eux-mêmes (Bare Hands `showSettings` vérifié en bac à sable).
- Sections enregistrées : `registerSettingsSection` (refus journalisé `settings_section_rejected` + notice dans la catégorie), `mountRegisteredSection` (`mount(host, context)` avec `isCurrent()`, `say`, `open`, `data()`, `draft()`, `markDirty()` ; échec → notice `role=alert` codée `settings_section_mount_failed`), `destroy` via `cleanupSettingsSurface()` → `destroyRegisteredSection()`. Pied : `save:'footer'` seulement ; onglets hérités : comportement d'avant (`tab.save`, pied caché pour `subagents`, vérifié en bac à sable).
- Clic extérieur supprimé : le shell couvre la fenêtre, plus d'extérieur, et un clic dans un vide fermerait une page en cours. Échap garanti (même si `ui_close` est réaffecté, même depuis un champ) sauf capture de raccourci, textarea/contenteditable ou `defaultPrevented`. Tab bouclé dans le shell. Focus à la catégorie active à l'ouverture, rendu à l'élément d'ouverture à la fermeture (« Plus d’outils » pour le bouton Réglages du popover), jamais volé ailleurs. Listes ARIA à activation manuelle (flèches/Début/Fin déplacent, Entrée ouvre) : parcourir ne charge rien.
- `ui_tab_next/prev` → `cycleCategory` ; libellés des raccourcis renommés « Catégorie de réglages suivante/précédente » (ID et touches inchangés). `settingsTabs()` → six catégories ; la roue (`settingsItemsOf`) fait une ligne par catégorie, notes courtes par ID de catégorie, repli sur la description.
- QA Slice 01 : (a) `also` de `voice` et `memory` complété (`voice_output`, `microphone_sound`, `turns_interruptions` ; `semantic_retrieval`, `consolidation`, `knowledge_sources`), test sur toutes les sections cibles prévues ; (b) commentaire de la garde `typeof TABS` corrigé (extraits de tests seulement, zone morte temporelle dans la page).
- Échec déjà présent `test_async_browser_render_does_not_restore_a_previous_panel` corrigé (double incomplet : `SET.data/draft`, `querySelectorAll`, suffixe Rappels d'agenda).

### Fichiers

`jarvis/runtime/control_center.html`, `control_center_settings_ui.js` (nouveau, primitives), `control_center_settings_registry.js` (`shellNavigation`, `shellTarget`, `also`), `control_center.py` (insertion des primitives), `control_center_jarvis_wheel.js`, `control_center_work.js` (Cosmos), `shortcuts.py` (libellés) ; docs `docs/settings/settings-shell.md` (nouveau, contrat du shell et du montage des sections), `navigation-registry.md`, `INDEX.md`, `docs/legacy/settings-tab-aliases.md`, `docs/control-center-shell.md`, `docs/OPERATIONS.md` ; tests `test_control_center_settings_shell_js.py` et `test_settings_shell_browser.py` (nouveaux), `test_control_center_settings_registry_js.py`, `test_control_center_mvp.py`, `test_jarvis_wheel_js.py`, `test_jarvis_wheel_browser.py`, `test_control_center_subagents_settings_js.py`, `test_control_center_voice_architecture.py`.

### Tests

- Suites Réglages (liste Slice 00 hors navigateur) + registre + nouveau node + `test_settings_redesign_migration` + `test_settings_ia_contract` : 395 passed.
- Navigateur : `test_settings_shell_browser` 6 passed, `test_jarvis_wheel_browser` 3 passed, `test_wake_word_settings_browser` 20 passed, `test_global_launcher_browser` + `test_control_center_shell_layers` + `test_variants_css_orphans` 21 passed. Autres : tests de raccourcis (`-k shortcut`) 18 passed ; documents lus par des tests 84 passed.
- Non relancé : `test_dossier_fullscreen_browser` (chemin non touché).

### Preuves

Bac à sable `setui` (Core 27653, Control Center 27654, données au scratchpad, visualiseur coupé). Avant : `references/current-settings-ui.png`. Après : `evidence/s02/` — 6 catégories × {1920×1080, 1366×768} × {100 %, 125 %} (125 % = largeur CSS /1,25, deviceScaleFactor 1,25), PNG quantifiés (2,1 Mo), `runtime-check.json` (débordement horizontal 0 partout, pied caché sur Sous-agents, Bare Hands `showSettings` → Avancé/Expérimental ; console sans erreur JS, seul le 424 réel de `/api/models` sans clé Anthropic).

## 2026-10-21 - Slice 02 QA decision (agent 0)

QA (qa-verification + code-review + runtime-validation, independent sandbox run, 11 mutations / 9 killed): REWORK. Blocking B1: opened from the Jarvis wheel, focus ends on the wheel anchor outside the `aria-modal` shell (wheel `restoreFocus` overrides `settingsFocusIn`). Sent back with N1 (Escape/Tab trap lost when focus is on `body` and `ui_close` rebound), N2 (focus lost after Save), N3 (surviving mutations: Tab trap, textarea exception), N4 (inexact textarea comment), N5 (truncated Memory description). Deferred polish: empty footer band on non-save tabs, crowded "encore dans" row in Advanced, disabled/read-only contrast (Slice 10).

## 2026-10-21 - Slice 02 rework (QA)

- B1 : la roue d'outils ne reprend plus un focus qu'une action a porté hors d'elle (`restoreFocus`, `control_center_tool_wheel.js`) ; `openSettingsTab(cible, {returnFocus})` (la roue passe son ancre) ; ouverture par la roue → focus sur la catégorie active, toujours là 800 ms après, Tab reste dans le shell, Échap rend le focus à l'ancre (`test_jarvis_wheel_browser`).
- N1 : écoute Échap/Tab sur `document` tant que les réglages sont ouverts (cible dans le shell ou `body`) : Échap ferme avec `ui_close` réaffecté et focus sur `body`, Tab depuis `body` entre dans le shell. N2 : focus rendu à « Enregistrer » après `saveDraft`. N3 : tests du piège de Tab, de l'exception textarea, de `body`, du champ réellement focalisé. N4 : formulation « une saisie longue ne ferme pas la page » (code + `settings-shell.md`). N5 : descriptions des catégories raccourcies au registre, plus de troncature au rail (testé aux quatre tailles), captures `evidence/s02/` refaites.
- Tests : shell node + mvp + quality + agent_cli + voice_architecture + intégration migration + appearance + subagents + voice_settings_ui 183 passed ; registre + wheel_js + wheel_browser 22 passed ; settings_shell_browser 7 passed ; tool_wheel js+browser 36 passed ; `-k shortcut` 18 passed. Bac à sable : Core 9700/34284, Control Center 28096/16536, arrêtés par PID.

## 2026-10-21 - Slice 02 re-QA decision (agent 0)

Re-QA of `77740b68`: APPROVED. B1/N1/N2/N4/N5 verified in a real sandbox run; surviving mutations now killed (m8, m9) plus m12-m15 on the rework; other wheel consumers (capture wheel, dossier, input arbitration) checked, browser suites green (tool wheel, capture wheel, dossier, screenshot preview, wake word). Residual non-blocking risk: a wheel action that moves focus to a visible element outside the wheel and hides it later would leave focus on body (no such case in the repository). Not machine-verified yet (for Slice 10): keyboard-only wheel route, `s` shortcut route, Escape with a confirm over Settings, disabled/read-only contrast, forced-colors.
