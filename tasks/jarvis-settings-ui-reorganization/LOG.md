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

## 2026-10-21 - Slice 03 (implémentation)

### Décisions

- Destination de chaque option Voix décrite par le serveur : `surface` = `{category, section}` (+ `context` pour `wake_toggle`) dans `voice.option_metadata` (`voice_settings_schema.py` : `SURFACE_SECTIONS`, `_SURFACE`, `_SURFACE_CONTEXT`). Une option sans destination lève `RuntimeError`. `categories`/`category`/`destination` inchangés (contrat gardé, plus utilisés pour la navigation). Aucune table option → section dans le navigateur.
- Onglet `voice` retiré de `TABS` ; sept sous-onglets supprimés (`tabVoice`, `bindVoiceSurface`, `selectVoiceTab`, CSS `.voice-tabs`). Sections enregistrées (`VOICE_SECTIONS`, `save:'footer'`, `applies:'next_voice_start'`) : `conversation` (alias `voice`), `voice_output` (modèles, voix, transcription, catalogue comparatif replié), `microphone_sound` (périphériques d'abord, réduction de bruit, AEC, test audio sur les périphériques choisis), `turns_interruptions` ; sous `advanced_diagnostics` : `architecture_compat` (architecture, invariants, retour cerveau Claude, pile/mode historiques, VAD fin, vérificateur) et `diagnostics` (lecture seule, faite de parties `registerSettingsDiagnostic` : Voix, Mot d'éveil). Brouillon partagé `SET.draft` : `draftFrom`/`saveDraft` non modifiés, charge utile identique (vérifiée en bac à sable).
- Mot d'éveil : `control_center_wake_word.js` enregistre la section `wake_word` (`save:'self'`, alias `wakeword`) au lieu de `TABS.splice` ; route, charge utile et sémantique inchangées ; la saisie survit au changement de section/catégorie ; état du bloc, version illisible, clés ignorées et dernier événement du détecteur → partie « Mot d'éveil » de Diagnostics (lien « Voir le diagnostic » depuis la section). Un refus de lecture n'est pas relu en boucle quand le shell remonte la section pendant la même ouverture.
- `wake_toggle` : éditeur unique = onglet Raccourcis (filtre et renvoi vers Voix supprimés) ; Tours & interruptions montre la touche effective en lecture seule + « Modifier dans Interface & interactions › Raccourcis ».
- Les champs de pile portent le libellé serveur de leur pile (deux « Fin de tour »), les cases à cocher Voix sont sur la ligne de leur libellé.

### Fichiers

`jarvis/runtime/voice_settings_schema.py`, `control_center.html`, `control_center_wake_word.js` ; docs `docs/settings/voice-audio.md` (nouveau, table option → section vérifiée par test), `voice-settings-schema.md`, `settings/navigation-registry.md`, `settings/settings-shell.md`, `settings/INDEX.md`, `legacy/settings-tab-aliases.md`, `OPERATIONS.md`, `control-center-shell.md` ; tests `test_voice_settings_surface.py` (nouveau), `test_voice_settings_ui.py`, `test_control_center_voice_architecture.py`, `test_control_center_settings_registry_js.py`, `test_wake_word_settings_browser.py`, `test_settings_shell_browser.py`, `test_jarvis_wheel_browser.py`, `tests/integration/test_settings_redesign_migration.py`.

### Tests

- Non navigateur (voice_architecture, voice_settings_ui, wake_word_settings_ui, registry_js, shell_js, mvp, quality, catalog_ui, wheel_js, intégration migration, voice_settings_surface, voice_settings_schema, settings_ia_contract, shell_layers) : 243 passed. `-k shortcut` : 19 passed. `-k "(voice_settings or wake) and not browser"` : 800 passed, 3 skipped.
- Navigateur : `test_wake_word_settings_browser` 20 passed, `test_settings_shell_browser` + `test_jarvis_wheel_browser` 11 passed.
- Flake observé puis traité : `test_une_lecture_en_echec…` et `test_un_bloc_d_une_version_etrangere…` échouaient parfois quand `openSettings` remontait la section au milieu du test ; produit (pas de relecture en boucle d'un refus) et `OPEN` du test (attendre les réglages lus) corrigés, 9 passages isolés + suite complète verts.

### Preuves

Bac à sable `setui` (Core 127.77.0.1:27653, Control Center 27654, données/runtime au scratchpad, visualiseur coupé), Chrome jetable piloté par CDP : `evidence/s03/` — 7 vues (Conversation, Voix & transcription, Micro & son, Tours, Mot d'éveil, Architecture & compatibilité, Diagnostics) × {1920×1080, 1366×768} × {100 %, 125 %}, plus enregistrement Mot d'éveil, enregistrement Voix et lien vers Raccourcis ; PNG quantifiés (2,9 Mo) ; `runtime-check.json` (aucun débordement horizontal, pied caché sur Mot d'éveil et Diagnostics, brouillon gardé après passage par Avancé, POST `/api/wake-word` = cinq champs, POST `/api/settings` = `voice/cli/routing/audio/agenda_reminders` sans `architecture`, un seul éditeur `wake_toggle`, alias `voice` → `conversation`, `wakeword` → `wake_word`, console sans erreur). PID arrêtés après vérification de leur ligne de commande : 24532/8216 (Core), 17692/23192 (Control Center), 25724 (cerveau du bac à sable) ; Core utilisateur 17653 intact.

## 2026-10-21 - Slice 03 — retravail (QA)

- B1 : commentaire de `control_center_wake_word.js` sans route citée. B2 : fixture Agent/CLI (`voice` → `rehosted_as_sections`) et test (alias vérifié). B3 : enregistrements au chargement dans `installVoiceSettingsSections()`, appelé seulement si `window` existe (extraits node). B4 : `.set-section-body>*` (et `details.rd`, enfants de `.catalog-shell`) bornés à leur colonne ; mesuré par `test_open_voice_model_comparison_does_not_overflow` (1366×768 : 57 px avant, ≤ 1 px après ; 1093×614 : 276 px avant). B5 : `test_saving_from_a_voice_section_posts_the_whole_unchanged_payload_shape` ; mutation `audio:{}` dans `draftFrom` détectée sur copie jetable puis restaurée. N2 : panne de lecture réparée par l'événement « servie une fois » (plus de minuterie), réglages lus avant le clic ; attentes du détecteur portées à 15 s (cause probable : lecture du journal lente quand la suite charge la machine, pas reproduite isolément). N3 : commentaire du registre.
- Tests (comptes exacts) : wake_ui + agent_cli + appearance 61 ; mvp + quality + voice_architecture + voice_settings_ui + routing_settings_screen + catalog_ui 145 ; memory_settings_js + subagents_settings_js + scene_settings_ui + scene_view_prefs + barehands_tools_settings_js + barehands_cards_js + wheel_js + mcp_inspector_js 153 ; registry_js + shell_js + intégration migration + voice_settings_surface + voice_settings_schema + settings_ia_contract + shell_layers 66 ; `-k shortcut` 19 ; `-k "(voice_settings or wake) and not browser"` 801 + 3 skipped. Navigateur, deux passes identiques : wake_word_settings_browser 10 + 10, settings_shell_browser + jarvis_wheel_browser 13, dossier_fullscreen_browser 19 + 3 skipped.
- Aucun processus de bac à sable lancé pendant ce retravail (mesures B4 sur l'instance isolée des tests).

## 2026-10-21 - Slice 03 — décision QA (agent 0)

- QA initiale sur `2d114097` : RETRAVAIL. Bloquants B1-B3 (trois tests de régression cassés par la Slice : commentaire citant une route, fixture Agent/CLI, extrait node sans `window`), B4 (débordement 57 px à 1366×768 avec « Comparer les modèles vocaux » ouvert), B5 (mutation `audio:{}` de la charge non détectée). Le contrat produit tenait en bac à sable : cinq sections, unicité DOM = `surface` serveur (56 options − `wake_toggle`), charge utile et persistance, alias, clavier, console vide ; les trois placements signalés sont conformes à `docs/07`.
- Re-QA sur `55b59ad0` + `ccc46063` : APPROUVÉ. Mutations M1-M6 détectées (charge `audio`/`agenda_reminders`/pile inactive, règle CSS B4, garde `window`, appel `installVoiceSettingsSections`) ; suites Settings vertes, navigateur deux passes sans échec.
- Reporté : focus sur BODY après « Modifier dans … › Raccourcis » et « Voir le diagnostic » (Slice 06/10) ; premier Tab parti une fois sur `dockMore` après retour, non reproduit (Slice 10) ; cause de lenteur du test du détecteur non prouvée (attente 15 s) ; l'appel `installVoiceSettingsSections()` n'est gardé que par un test de texte (N-a).
- Écarts de méthode QA consignés : une passe navigateur basculée en arrière-plan par l'outil après 600 s ; bases SQLite jetables du bac à sable QA supprimées sans copie (aucune donnée utilisateur ni dépôt).
- `origin/main` inchangé (`20292e5c`).

## 2026-10-21 - Slice 04 (implémentation)

### Décisions

- Onglets `cli` et `subagents` retirés de `TABS` (restent : prompts, keys, shortcuts, memory + injectés). `agents_models` : quatre sections enregistrées (`AGENT_SECTIONS`, `SUBAGENT_SECTIONS`, `installAgentSettingsSections()` gardée par `typeof window` et par `typeof` de la fonction pour les extraits node) : `main_agent` · Agent principal (alias `cli` ; CLI piloté, version, clé, disponibilité, modèle principal par le sélecteur existant alimenté par le catalogue du fournisseur), `agent_behavior` · Comportement (verbosité, politesse/formalité, rappels de rendez-vous), `subagent_models` · Modèles des sous-agents (mode Auto/Dupliqué + l'unique `JarvisCatalog` surface `subagents`), `subagents` · Rôles des sous-agents (`save:'self'`, ID = ancien ID d'onglet).
- Avancé & diagnostic, ids explicites pour la Slice 08 : `runtime_cli` · Runtime & CLI (groupe `runtime_cli`, order 30, alias `routing`, pied Enregistrer : commande, chemin résolu, re-détecter, permission, « Configuration avancée des sous-agents » = profils, candidats ordonnés, recours Général, source des listes) ; `work_methods` · Work Methods apprises (groupe `labs`, order 50, `save:'self'` : approches observées + promotion). `also` du registre : `cli` → + `subagent_models` ; `subagents` → `work_methods` (au lieu de `labs`).
- Promotion des Work Methods sous Avancé : `docs/subagent-roles.md` § 1bis (« capacités et méthode par défaut suivent le code… Seule autre écriture… la promotion explicite ») et § 8 (« Seule écriture : les instructions ») ; `docs/work-methods.md` (« La promotion est un acte explicite, jamais un effet de bord », « la seule écriture est la promotion explicite d'un candidat »). Aucun document ne la classe comme configuration ordinaire de rôle : outil d'opérateur. Module `control_center_subagents_settings.js` : option `view` (`roles` par défaut, `work_methods`) ; la vue rôles ne lit plus les candidats (lien « Avancé & diagnostic › Work Methods apprises » pour un rôle porteur de mission), la vue Work Methods ne lit pas les instances ; un bloc par rôle porteur de mission, notice de promotion unique.
- Écart assumé à `docs/07` : `delegation_mode` dans Modèles des sous-agents, pas Comportement (interrupteur qui applique les profils de candidats : il règle le choix du modèle d'un sous-agent ; consigne de l'agent 0 « Sous-agents (mode utilisateur…) »). Rappels de rendez-vous (absents de docs/07, portés par l'ancien onglet) : Comportement. Tutoiement « JARVIS te rappelle tes rendez-vous » corrigé en vouvoiement.
- Préservé : brouillon partagé `SET.draft`, `draftFrom`/`saveDraft` intacts (charge identique, figée clé par clé) ; `SET.subagentDrafts` ; conflits de révision des rôles (texte gardé, révisions relues) ; voie canonique des prompts ; `JarvisCatalog` créé au montage de Modèles des sous-agents, détruit par son `destroy` ; sondes CLI/modèles locales, gardées par `currentAgentSection(revision)` (ex-`currentAgentTab`) ; candidats demandés seulement à l'ouverture de la divulgation, qui reste ouverte au remontage et se ferme quand on quitte Runtime & CLI ; sémantique de routage inchangée. Aucune capacité inventée.
- `canonicalSettingsTab` et `routing.tab:'cli'` ne servent plus à la page (extraits de tests seulement) : laissés pour la Slice 09, consigné dans `docs/legacy/settings-tab-aliases.md`.

### Fichiers

`jarvis/runtime/control_center.html`, `control_center_subagents_settings.js`, `control_center_settings_registry.js` ; docs `docs/settings/agents-models.md` (nouveau), `settings/INDEX.md`, `settings/navigation-registry.md`, `settings/settings-shell.md`, `settings/migration-rollout.md`, `legacy/settings-tab-aliases.md`, `subagent-roles.md` § 8, `work-methods.md`, `OPERATIONS.md` ; fixture `tasks/jarvis-settings-model-catalog-ux/.../agent-cli-ui.json` ; tests `test_agents_models_settings_browser.py` (nouveau), `test_agent_cli_settings_ui.py` (+ charge figée, + répartition des champs), `test_routing_settings_screen.py`, `test_control_center_subagents_settings_js.py`, `test_control_center_settings_registry_js.py` (+ `test_agent_legacy_ids_open_their_sections`), `test_control_center_mvp.py`, `test_control_center_voice_architecture.py`, `test_voice_settings_ui.py`, `test_control_center_prompts.py`, `test_settings_shell_browser.py`, `tests/integration/test_settings_redesign_migration.py`.

### Tests (comptes exacts, depuis `setui`, `.venv` du dépôt principal)

- mvp + quality + voice_architecture + voice_settings_ui + wake_word_settings_ui + agent_cli_settings_ui + routing_settings_screen + catalog_ui : 203 passed.
- memory_settings_js + subagents_settings_js + appearance + scene_settings_ui + scene_view_prefs + barehands_tools_settings_js + barehands_cards_js + jarvis_wheel_js + mcp_inspector_js : 158 passed.
- settings_registry_js + settings_shell_js + intégration settings_redesign_migration + settings_ia_contract + voice_settings_surface + voice_settings_schema + shell_layers + variants_css_orphans + control_center_prompts : 75 passed.
- documented_routes + delivery_quality + wake_word_docs : 80 passed. `-k "shortcut and not browser"` : 16 passed.
- Balayage large `-k "(subagent or work_method or routing or agent_cli or catalog or control_center or settings) and not browser"` (unit + intégration) : 2410 passed, 1 skipped, 9 failed ; 1 corrigé ensuite (test_control_center_prompts, borne `tabCli`) ; les 8 autres échouaient aussi sur `d6df9f8d`. **Correction (retravail QA) :** seuls 7 sont préexistants sur main (`test_app::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`, 6 × `test_control_center_mcp_api`) ; `test_control_center_voice_architecture_ui_review::test_page_announces_deferred_architecture_apply_and_uses_task16_live_control` passe sur `20292e5c` et `77740b68` et échoue depuis `2d114097` (S3 a retiré la phrase de `modalSub`) : régression de test des Réglages, corrigée au retravail. `test_control_center_voice_architecture_ui_review` rejoint la liste de régression Réglages.
- Navigateur (chaque commande < 600 s) : settings_shell_browser + jarvis_wheel_browser 13 passed ; agents_models_settings_browser + dossier_fullscreen_browser 25 passed, 3 skipped (6 + 19) ; wake_word_settings_browser 12 + 8 passed.
- Mutations (copie jetable `git worktree add --detach` de `fc5f2ff8` au scratchpad, supprimée ensuite) : 12/12 tuées. M1 `delegation_mode` retiré, M2 `permission_mode` perdu, M3 clé ajoutée sous `cli`, M4 sous-clé `profile` des profils perdue (test de charge figée) ; M5 conflit : brouillon jeté, M6 `expected_effective_revision` non envoyée, M7 conflit sans relecture ; M8 vue rôles qui lit les candidats ; M9 commande/permission rendues dans Agent principal ; M10 catalogue non détruit ; M11 sections non enregistrées (navigateur) ; M12 alias `cli` retiré.

### Preuves

Bac à sable `setui` (Core 127.77.0.1:27653, Control Center 127.0.0.1:27654, données/runtime au scratchpad `s04`, visualiseur coupé), Chrome jetable par CDP : `evidence/s04/` : 6 sections × {1920×1080, 1366×768} × {100 %, 125 %} divulgations et catalogue ouverts, plus la tournée 1920×1080, rôle enregistré, conflit ; 32 PNG quantifiés (2,9 Mo) ; `runtime-check.json` : débordement horizontal 0 partout, clavier (flèche/Entrée sur le rail, Tab vers Fermer puis les entrées, flèche droite + Entrée ouvre Comportement), alias `cli`/`routing`/`subagents`, enregistrement Comportement (POST `/api/settings` = `voice/cli/routing/audio/agenda_reminders`, `cli` = `agent/settings/delegation_mode/behavior`) relu après rechargement, instructions du rôle `concept` enregistrées et relues, conflit réel côté serveur (400 `prompt_override_concurrent` avec révisions périmées) et côté écran (texte gardé, révisions relues), console sans erreur. Ligne de la roue : `test_jarvis_wheel_browser`. PID arrêtés un par un après vérification de leur ligne de commande, sans `/T` : 32884 (cerveau claude du bac à sable ; ses MCP partis avec lui, vérifié), 11208 (Control Center ; lanceur 14700 parti avec lui), 20656 (Core ; lanceur 36684 parti avec lui). Core utilisateur 17653 (PID 31824) intact. Données du bac à sable laissées en place.

## 2026-10-21 - Slice 04 — retravail (QA)

- B1 : `test_page_announces_deferred_architecture_apply_and_uses_task16_live_control` réécrit sur l'annonce canonique (commit `S3: fix`) : monte la vraie section `architecture_compat` (`voiceSectionSpec`) avec les vraies primitives, exige `applies:'next_voice_start'`, le badge « Au prochain démarrage de Voice » et l'avis « Redémarrez Voice pour appliquer » de `voiceRestartHtml`. Mutations tuées sur copie jetable : libellé du badge vidé, `applies` retiré de la section, avis de redémarrage retiré.
- B2 : `test_leaving_roles_then_work_methods_destroys_each_view` (node, vraie page + vrai module) : monter puis quitter `subagents` puis `work_methods` pendant le chargement → vue détruite, compteur d'attente arrêté, réponse tardive ignorée. Tue la mutation `destroySubagentSettings` sans `view.destroy()` (copie jetable `git worktree add --detach`, supprimée).
- Liste de régression Réglages : + `test_control_center_voice_architecture_ui_review`. Entrée « préexistants » corrigée (7, pas 8).
- Tests : voice_architecture_ui_review + subagents_settings_js + agent_cli_settings_ui + registry_js + shell_js + intégration settings_redesign_migration + voice_architecture + mvp : 114 passed. `test_agents_models_settings_browser` deux passes : 6 + 6 passed. Aucun bac à sable lancé.

## 2026-10-21 - Slice 04 — décision QA (agent 0)

- QA initiale sur `f645f51a` : RETRAVAIL. Produit conforme en bac à sable (charges `/api/settings` et écritures de rôles identiques, unicité comptée dans le DOM, conflit de révision réel, persistance, alias `cli`/`routing`/`subagents`, 0 px de débordement catalogue ouvert, console vide ; arbitrages docs/07 acceptés). Bloquants : B1 `test_control_center_voice_architecture_ui_review::test_page_announces_deferred…` cassé par `2d114097` (S3), pas préexistant (bissection) ; B2 destruction de la vue Rôles/Work Methods gardée par un test de texte seulement (mutation survivante).
- Retravail `3e47b4c3` (S3: fix), `56c17532`, `4889c375`. Re-QA par agent 0 (retravail limité aux tests) : 40 passed sur les deux fichiers ; mutations rejouées sur worktree jetable — `view.destroy()` retiré → `test_leaving_roles_then_work_methods_destroys_each_view` échoue ; libellé du badge `next_voice_start` changé → test d'annonce différée échoue. APPROUVÉ.
- Préexistants sur origin/main `20292e5c` (7) : `test_app::test_the_control_center_receives_a_tools_gateway_target…`, 6 tests de `test_control_center_mcp_api`.
- Reporté Slice 09/10 : focus sur BODY après liens internes (« Régler la commande », renvois Work Methods), titre/pastille de Work Methods, commentaires citant des routes dans `control_center.html`, filtres du catalogue coupés à 1366×768 (défilement interne, préexistant), pas d'outline au focus de `#f_cli_model`.

## 2026-10-22 - Slice 05 (implémentation)

### Décisions

- Destination de chaque champ mémoire servie par le serveur : `surface = {category:'memory_knowledge', section}` dans le
  schéma (`memory_settings.py` : `SURFACE_SECTIONS`, `_SURFACE`, `surface()`), aussi sur `schema.loadouts`. Section du bloc
  sans destination → `RuntimeError`. Valeurs, précédence env/fichier/défaut, charge et codes inchangés. Aucune liste de
  champs dans le navigateur : le module range par `surface.section`.
- Onglet `memory` retiré de `TABS` (et de `renderTab`). `memory_knowledge` : cinq sections enregistrées par la page
  (`MEMORY_SECTIONS`, `installMemorySettingsSections()` gardée par `typeof window` + `typeof` de la fonction) : `recall`
  · Rappel (alias `memory`), `semantic_retrieval`, `consolidation`, `knowledge_sources` (Tencent + Wiki/graphe/Skills +
  résumé des loadouts en lecture seule), toutes `save:'self'` (bouton « Enregistrer la mémoire », correctif mémoire seul,
  comme avant) ; `memory_center` · Centre mémoire (`readonly`, bouton « Ouvrir le Memory Center », qui ferme les Réglages).
- Avancé › Diagnostics : partie « Mémoire » (`registerSettingsDiagnostic`, order 30) : chaque étage et son badge, raison +
  code + comment réparer, combinaisons coupées à la lecture, valeurs imposées par l'environnement. La page ordinaire garde
  une ligne courte (étages de la section, nombre de points à vérifier) + « Voir le diagnostic mémoire » (ouvre
  Diagnostics, focus sur `#diagnostic_memory`, gardée en vue pendant que Voix et Mot d'éveil se remplissent au-dessus).
- Module `control_center_memory_settings.js` : vues `fields` (une section), `center`, `diagnostics` sur un état partagé
  (`createStore`, un par ouverture des Réglages, une seule lecture). Brouillon partagé entre sections mémoire : une règle
  de compatibilité peut ramener un champ d'une autre section (couper la sémantique remet la consolidation en manuel) ;
  la section le dit (« Enregistre aussi les changements en attente… ») et l'enregistrement envoie tout le brouillon.
  `destroy()` : plus aucun dessin, réponse tardive ignorée. `show` supprimé (seul appelant : l'ancien onglet). Rendu par
  les primitives du shell (`field`, `section`, `badge`, `appliesBadge`, `notice`, `actions`). Moment d'application lu
  dans `status.restart_required` (badge par section, par groupe dans Sources de connaissances) ; avis « Redémarrage de
  Core nécessaire pour … » tant qu'un tel champ est en attente, rappel après l'enregistrement.
- Écarts : aucun avec docs/07. Le résumé « Connaissances par agent » est dans Sources de connaissances (destination servie
  `schema.loadouts.surface`). Libellé d'entrée « Centre mémoire » ; le bouton garde « Memory Center ».

### Table champ → section (servie par le serveur, vérifiée par `test_memory_settings_surface`)

| Champs | Section |
| --- | --- |
| `recall.enabled`, `recall.max_items`, `recall.timeout_ms` | `recall` |
| `semantic.enabled`, `semantic.provider`, `semantic.allow_private` | `semantic_retrieval` |
| `consolidation.mode`, `consolidation.auto_min_confidence`, `consolidation.max_candidates_per_run` | `consolidation` |
| `tencent.enabled`, `tencent.url`, `tencent.service_id`, `tencent.allow_private`, `knowledge.wiki_enabled`, `knowledge.codegraph_enabled`, `knowledge.skills_enabled`, `loadouts` (lecture seule) | `knowledge_sources` |
| aucun champ : entrée du Memory Center | `memory_center` |
| aucun champ : état et dégradation des étages | `advanced_diagnostics` / `diagnostics` › Mémoire |

### Fichiers

`jarvis/runtime/memory_settings.py`, `control_center_memory_settings.js`, `control_center.html` ; docs
`docs/settings/memory.md` (table champ → section, schéma complété de `tencent.service_id` et `tencent.allow_private`),
`settings/INDEX.md`, `settings/navigation-registry.md`, `settings/settings-shell.md`, `legacy/settings-tab-aliases.md`,
`OPERATIONS.md` ; tests `test_control_center_memory_settings_js.py` (réécrit), `test_memory_settings_surface.py` (nouveau),
`test_memory_settings_browser.py` (nouveau), `test_control_center_settings_registry_js.py` (+ `SLICE_05_SECTIONS`,
`test_memory_legacy_id_opens_recall_and_every_memory_section`, `test_page_memory_sections_match_the_registered_fixture`),
`test_memory_settings_endpoints.py`, `tests/integration/test_settings_redesign_migration.py`.

### Tests (comptes exacts, depuis `setui` @ `28e055d8`, `.venv` du dépôt principal)

- mvp + quality + voice_architecture + voice_settings_ui + wake_word_settings_ui + agent_cli_settings_ui +
  routing_settings_screen + catalog_ui + voice_architecture_ui_review : 209 passed.
- memory_settings_js + subagents_settings_js + appearance + scene_settings_ui + scene_view_prefs +
  barehands_tools_settings_js + barehands_cards_js + jarvis_wheel_js + mcp_inspector_js + control_center_memory_js
  (Memory Center) : 174 passed.
- settings_registry_js + settings_shell_js + intégration settings_redesign_migration + settings_ia_contract +
  voice_settings_surface + voice_settings_schema + shell_layers + variants_css_orphans + control_center_prompts +
  memory_settings_surface + memory_settings + memory_settings_endpoints : 271 passed.
- documented_routes + delivery_quality + wake_word_docs : 80 passed.
- Navigateur (chaque commande < 600 s) : settings_shell_browser + jarvis_wheel_browser 13 passed (deux passes, @ `d1fd5690`
  et @ `28e055d8`) ; memory_settings_browser 6 passed @ `d1fd5690`, puis memory_settings_js + memory_settings_surface +
  settings_registry_js + quality + variants_css_orphans + shell_layers + memory_settings_browser 123 passed @ `28e055d8` ;
  agents_models_settings_browser 6 passed ; wake_word_settings_browser 12 + 8 passed ; dossier_fullscreen_browser
  19 passed, 3 skipped (ces trois @ `d1fd5690`).
- Balayage large sans navigateur (unit + intégration, @ `d1fd5690`) : `-k "memory and not browser"` 1308 passed,
  4 skipped ; `-k "settings and not memory and not browser"` 711 passed, 1 failed ; `-k "control_center and not settings
  and not memory and not browser"` 809 passed, 6 failed, 1 skipped ; `-k "(subagent or work_method or routing or
  agent_cli or catalog or knowledge or loadout or wheel or shell or registry) and not settings and not memory and not
  control_center and not browser"` 1091 passed, 3 skipped. Les 7 échecs sont exactement les préexistants de main
  (`test_app::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`, 6 ×
  `test_control_center_mcp_api`). Régression attrapée en route et corrigée avant commit :
  `test_control_center_quality::test_the_page_renders_the_solo_owner_and_aec_status_from_the_api` refuse le mot
  « embedding » dans la page (description de Recherche sémantique reformulée).

### Mutations (copies jetables `git worktree add --detach` au scratchpad, supprimées ensuite) : 14/14 tuées

M1 Tencent servi dans `semantic_retrieval` (surface) ; M2 chaque section rend tous les champs ; M3 la charge envoie toutes
les valeurs ; M4 `destroy` sans effet (réponse tardive dessinée) ; M5 la section ne détruit pas sa vue ; M6 alias `memory`
retiré (tué par le test qui lie la fixture du registre à `MEMORY_SECTIONS`) ; M7 avis de redémarrage retiré ; M8 correctif
croisé sémantique → consolidation retiré ; M9 état non partagé ; M10 lien diagnostic non câblé ; M11 sections non
installées (vrai Chrome) ; M12 clé inconnue ajoutée à la charge ; M13 partie Mémoire non inscrite (vrai Chrome) ;
M14 partie Mémoire non gardée en vue après le lien (vrai Chrome).

### Preuves

Bac à sable `setui` (Core 127.77.0.1:27653, Control Center 127.0.0.1:27654, données/runtime au scratchpad `s05`,
visualiseur coupé), Chrome sans tête par CDP : `evidence/s05/` : 31 PNG quantifiés (2,1 Mo) — six vues × {1920×1080,
1366×768} × {100 %, 125 %}, plus enregistrement, brouillon en attente vu d'une autre section, avis de redémarrage avant et
après, diagnostic ouvert par le lien, Memory Center ouvert ; `runtime-check.json`. Constats : cinq entrées, aucun onglet
« Mémoire » ; chaque champ dans sa section ; clavier (flèches + Entrée sur le rail jusqu'à Mémoire & connaissances, Tab
vers Fermer puis les entrées, flèche droite + Entrée ouvre Recherche sémantique) ; alias `memory` → `recall` ; POST
`/api/settings` = `{"memory":{"recall":{"max_items":5}}}` puis `{"memory":{"semantic":{"enabled":false}}}` (première passe :
`{"memory":{"recall":{"max_items":4}}}` puis `{"memory":{"semantic":{"provider":"openai","enabled":true}}}`), relus après
rechargement ; sémantique sans clé → « 1 point à vérifier », détail `semantic_no_key` dans Diagnostics, focus sur la
partie, en vue ; Memory Center ouvert (Réglages fermés, focus sur l'onglet Notes) ; débordement 0 aux quatre tailles ;
console vide. La première passe a trouvé la partie Mémoire hors écran après le lien (corrigé, `36085b29`) et la borne
des nombres repliée à 125 % (corrigé, `28e055d8`). PID arrêtés un par un après vérification de leur ligne de commande,
sans `/T` : 22472 (cerveau claude du bac à sable, enfant du Control Center ; ses dix MCP partis avec lui, vérifié),
26960 (Control Center ; lanceur 3776 parti avec lui), 528 (Core ; lanceur 17780 parti avec lui). Core utilisateur 17653
(PID 31824) intact. Données du bac à sable laissées en place.

## 2026-10-22 - Slice 05 — retravail (QA)

- B1 (`c6d85fb7`) : le store tient ses vues vivantes (`views`) ; `submit` et la lecture partagée redessinent toutes les vues à
  leur issue (succès et refus). La section ouverte pendant un envoi n'est plus figée sur « Enregistrement… » : elle montre
  le message réel, ses champs réactivés, l'avis et « Enregistre aussi… » selon le brouillon réel. Une vue détruite quitte
  le store. Tests : `test_leaving_a_section_during_a_save_redraws_the_section_now_shown[succès|refus]`.
- N4 : une vue montée après un enregistrement terminé ne reprend ni le message ni l'avis d'après-enregistrement (gardés si
  l'envoi est en cours). Test : `test_a_section_opened_after_a_save_does_not_repeat_its_message`.
- N2 : le maintien en vue de la partie Mémoire rend la main à molette, touche, pointeur et toucher (écoutes en capture sur
  le contenu) ; minuteur de 4 s, écoutes et observateur arrêtés par `stopMemoryDiagnosticPin`, appelé par le `destroy` de
  la partie (changement de section ou de catégorie, fermeture) et par un nouveau lien. Commentaire corrigé. Test node sur
  le vrai code de la page : `test_the_diagnostic_pin_yields_to_any_user_scroll_and_is_cleaned_up`.
- Mutations (copie jetable `git worktree add --detach`, supprimée) : 7/7 tuées — R1 `submit` ne redessine que sa vue,
  R2 vue non inscrite au store, R3 vue détruite gardée au store, R4 message repris par une vue montée après, R5 minuteur
  de 4 s et écoute de la molette retirés (mutation de la QA), R6 le clavier ne rend pas la main, R7 `destroy` n'arrête pas
  le maintien.
- Tests @ `c6d85fb7` : memory_settings_js + memory_settings_surface + memory_settings + memory_settings_endpoints +
  control_center_memory_js + registry_js + shell_js + intégration settings_redesign_migration + quality + mvp : 347 passed.
  `test_memory_settings_browser` deux passes : 6 + 6 passed ; `test_settings_shell_browser` deux passes : 9 + 9 passed.
  Aucun bac à sable lancé.

## 2026-10-22 - Slice 05 — décision QA (agent 0)

- QA initiale sur `5261df9d` : RETRAVAIL. Contrat tenu (16 champs, une section chacun ; `memory_settings.py` : ajout de `surface` seul, sorties serveur identiques octet pour octet entre `cb7b0082` et `5261df9d` ; POST identiques ancien/nouveau module ; champs inconnus préservés ; brouillon partagé annoncé avant envoi ; ordre des sources conforme à docs/07). Bloquant B1 : changer de section pendant un enregistrement laissait la nouvelle section figée (« Enregistrement… », champs désactivés, message perdu). Joints : N4 (messages répétés), N2 (maintien en vue sourd au clavier, minuteur non annulé, mutation survivante).
- Retravail `c6d85fb7`, `7093b92d`. Re-QA : APPROUVÉ. B1 succès/refus et N2 (PageUp, fermeture avant 4 s, re-clic) rejoués en bac à sable ; mutations M1-M3 détectées.
- Reporté Slice 10 : focus sur BODY après « Enregistrer la mémoire » et après changement de section ; brouillon mémoire jeté à la fermeture sans prévenir (préexistant) ; message de refus non revu après changement de section (brouillon gardé) ; test du maintien en vue aveugle aux options `capture` du retrait (mutation M4 survivante, code correct) ; `docs/ARCHITECTURE.md:102` et `docs/memory.md:830` parlent encore d'un onglet Mémoire ; « Sidecar Tencent » répété ; `workspace.unknown_action {"name":"settings"}` du bouton du Memory Center (préexistant) ; un échec ponctuel non identifié dans une passe groupée des suites navigateur (harnais commun, vert en relance).

## 2026-10-22 - Slice 06 (implémentation)

### Décisions

- Plus aucun injecteur d'onglet : `control_center_work.js` et `control_center_barehands.js` enregistrent des sections
  (`test_no_module_injects_a_new_top_level_tab` : liste vide). `TABS` = `prompts`, `keys`, `experimental`.
- `interface_interactions` : `theme_scene` · Thème & scène visuelle (order 10, `save:'self'`, alias `appearance`,
  `THEME_SCENE_SECTION` de `control_center_work.js` ; la scène s'y monte par `window.JarvisSceneViewSettings.mount(slot)`
  de `control_center_scene_page.js`, plus d'enveloppe de `renderTab`) ; `shortcuts` · Raccourcis (order 20,
  `SHORTCUTS_SECTION` de la page, ID = ancien ID d'onglet) ; `bare_hands` · Bare Hands (order 30, module Bare Hands).
- Thème : un choix applique `activate(id)` (clé `jarvis.ui.theme` inchangée) et marque la carte en place, sans redessiner
  (avant : `renderTab()` arrachait le focus du bouton radio). Réglages de la scène : clé `JarvisSceneView.KEY`,
  « Réinitialiser » inchangés.
- Raccourcis : unique éditeur de chaque raccourci, `wake_toggle` compris. Capture : `destroy` de la section l'annule
  (changement de section, de catégorie, fermeture) ; après envoi, rien n'est redessiné si la section a été quittée
  (`startCapture(button, isCurrent)`), sinon le focus revient sur la touche redessinée. L'Échap pendant la capture est
  arrêté par l'écoute en capture de `window` (les Réglages restent ouverts). `#shortcutHint` devient `role=status`.
  Voix › Tours & interruptions garde la touche en lecture seule + lien (contexte, pas un second éditeur : conservé).
- Focus après lien interne, une fois dans le shell : `openSettingsLink(cible, {focus})` (= `context.open` des sections,
  `openTab` des sous-agents, liens `data-voice-open`). Focus sur le sélecteur demandé s'il est dessiné (touche
  `wake_toggle`, `#diagnostic_wake_word` pour « Voir le diagnostic » du Mot d'éveil), sinon sur l'entrée ouverte de
  `#modalTabs` (« Régler la commande », renvois Work Methods / modèles) ; jamais `body`. « Voir le diagnostic mémoire »
  garde son focus sur sa partie.
- Bare Hands : préférences ordinaires (aperçu de cible, assistance, sensibilité, retour en veille, proposer la
  calibration, Calibrer…, Effacer le profil, Réinitialiser les réglages, deux limites connues, état du cycle de vie en
  lecture) dans `bare_hands`. La lecture de diagnostic à l'écran est traitée en outil d'opérateur (docs/07 : « if kept
  operator-only » ; c'est une lecture de mesures) → Avancé. Le texte de « Réinitialiser » dit qu'elle touche aussi
  cette case (comportement inchangé : `SETTINGS_DEFAULTS` + `enabled` reporté). `refreshPanel` ne dessine que si une
  entrée est montée (`settingsShown`) ; `destroy` retire l'hôte (réponses tardives sans effet). `showSettings(clé)`
  ouvre l'entrée qui porte la clé (`SECTION_ENTRY`, liée par test à `LEGACY_ANCHORS`) et ne redessine pas une entrée
  déjà ouverte ; résultat `{ok, entry, section}` (l'ancien champ `tab` n'avait aucun lecteur, HUD compris).
- Registre : ancres `barehandsRecord`/`barehandsBenchmarkSection` → `barehands_lab` ; `experimental.also` +
  `barehands_lab` ; un lien « encore dans » n'apparaît plus vers une destination déjà enregistrée comme section dans la
  catégorie (Interface ne renvoie plus vers Expérimental).

### Table réglage → section

| Réglage | Section |
| --- | --- |
| Thème Circuit imprimé / Cosmos (`localStorage` `jarvis.ui.theme`) | `interface_interactions` › `theme_scene` |
| Étoiles et orbites (`localStorage` `JarvisSceneView.KEY`), « Réinitialiser » | `interface_interactions` › `theme_scene` |
| Tous les raccourcis de `shortcuts.py` (`wake_toggle`, `ui_settings`, `ui_close`, panneaux, `ui_tab_next/prev`) | `interface_interactions` › `shortcuts` |
| `targetPreview`, `assistance`, `sensitivity`, `sleepTimeoutMs`, `calibrationEnabled`, Calibrer…, Effacer le profil, Réinitialiser | `interface_interactions` › `bare_hands` |
| `diagnostics` (lecture à l'écran), Test (`SECTION.benchmark`), Enregistrement (`SECTION.record`) | `advanced_diagnostics` › `barehands_lab` |
| État des fichiers MediaPipe, dernière commande vocale | `advanced_diagnostics` › `diagnostics`, partie `barehands` |
| Porte de test de la scène + redémarrage du cerveau | onglet `experimental` (inchangé, Slice 08) |

### Pour la Slice 08 : entrées d'Avancé créées

- Section `barehands_lab` (groupe `labs`, order 60, `save:'self'`, `advanced:true`, libellé « Bare Hands · essais »),
  enregistrée par `control_center_barehands.js` (`installSettingsSections`, `SETTINGS_ENTRY.lab`).
- Partie de diagnostic `barehands` (order 40, `registerSettingsDiagnostic`), même module.
- État de `experimental` : **gardé** dans `TABS`, déclaré par la page (plus par Bare Hands), rangé dans Avancé ; il ne
  porte plus que `control_center_scene_settings.js` (inchangé, il enveloppe toujours `renderTab`). `renderTab` rend un
  contenu vide pour cet onglet, la scène s'y ajoute. Alias `experimental` → Labs inchangé. À la Slice 08 : enregistrer
  la porte de la scène (Labs), retirer `experimental` de `TABS` et la branche `experimental` de `renderTab`/`modalSub`.

### Fichiers

`jarvis/runtime/control_center.html`, `control_center_work.js`, `control_center_scene_page.js`,
`control_center_barehands.js`, `control_center_settings_registry.js`, `control_center_wake_word.js` ; docs
`docs/settings/interface-interactions.md` (nouveau), `settings/INDEX.md`, `settings/settings-shell.md` (§ 3 liens
internes, § 4 parties), `settings/navigation-registry.md`, `settings/voice-audio.md`, `legacy/settings-tab-aliases.md`,
`OPERATIONS.md`, `barehands-contracts.md` ; fixture `tasks/jarvis-settings-model-catalog-ux/.../agent-cli-ui.json`
(`shortcuts`, `appearance` → `rehosted_as_sections`) ; tests `test_interface_settings_browser.py` (nouveau),
`test_control_center_appearance.py`, `test_scene_view_prefs.py`, `test_scene_settings_ui.py`,
`test_barehands_tools_settings_js.py` (double du shell : entrées enregistrées), `test_barehands_palette_js.py`,
`test_control_center_settings_registry_js.py` (`SLICE_06_SECTIONS`, ancres ↔ `SECTION_ENTRY`),
`test_voice_settings_ui.py`, `test_voice_settings_surface.py`, `test_agent_cli_settings_ui.py`,
`test_control_center_subagents_settings_js.py`, `test_settings_shell_browser.py`, `test_jarvis_wheel_browser.py`,
`test_wake_word_settings_browser.py` (focus après « Voir le diagnostic »), `_wake_word_settings_browser.mjs` (F10, F11),
`tests/integration/test_settings_redesign_migration.py`.

### Tests (comptes exacts, depuis `setui` @ `2ec2a203`, `.venv` du dépôt principal)

- mvp + quality + voice_architecture + voice_settings_ui + wake_word_settings_ui + agent_cli_settings_ui +
  routing_settings_screen + catalog_ui + voice_architecture_ui_review : 209 passed.
- memory_settings_js + subagents_settings_js + appearance + scene_settings_ui + scene_view_prefs +
  barehands_tools_settings_js + barehands_cards_js + jarvis_wheel_js + mcp_inspector_js + control_center_memory_js :
  179 passed.
- settings_registry_js + settings_shell_js + intégration settings_redesign_migration + settings_ia_contract +
  voice_settings_surface + voice_settings_schema + shell_layers + variants_css_orphans + control_center_prompts +
  memory_settings_surface + memory_settings + memory_settings_endpoints : 273 passed.
- documented_routes + delivery_quality + wake_word_docs + remotion_no_fallback_privacy : 105 passed.
- `-k "shortcut and not browser"` : 16 passed. `-k "barehands and not browser"` : 1095 passed, 1 skipped, 2 failed
  (`test_barehands_interaction_js::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine` et
  `…_resizes_only_on_two_distinct_compatible_zones` : échouent aussi sur `f2e42635` et sur main `20292e5c`, worktree
  jetable). `test_barehands_palette_js` (garde-fou de `refreshPanel` lu sur la source) corrigé pour `settingsShown`.
- Navigateur (chaque commande < 600 s) : interface_settings_browser 9 passed ; settings_shell_browser + jarvis_wheel_browser
  13 passed ; agents_models_settings_browser + memory_settings_browser 12 passed ; wake_word_settings_browser 10 + 10
  passed ; dossier_fullscreen_browser + scene_task_graph_browser 35 passed, 3 skipped.
- Balayage large sans navigateur (unit + intégration) : `-k "settings and not memory and not browser"` 714 passed,
  1 failed ; `-k "control_center and not settings and not memory and not browser"` 809 passed, 6 failed, 1 skipped ;
  `-k "memory and not browser"` 1312 passed, 4 skipped ; `-k "(subagent or work_method or routing or agent_cli or
  catalog or knowledge or loadout or wheel or shell or registry) and not settings and not memory and not control_center
  and not browser"` 1091 passed, 3 skipped ; `-k "(scene or theme or appearance or cosmos or wake or voice_settings) and
  not settings and not memory and not control_center and not barehands and not browser and not subagent and not routing
  and not wheel and not shell and not registry"` 2621 passed, 19 skipped, 1 failed. Échecs : les 7 préexistants de main
  (`test_app::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`, 6 ×
  `test_control_center_mcp_api`) et `test_scene_group_drag_js::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`
  (échoue aussi sur main `20292e5c`, worktree jetable ; hors du balayage des Slices précédentes).

### Mutations (copie jetable `git worktree add --detach` de `2ec2a203` au scratchpad, supprimée ensuite) : 16/16 tuées

M1 `wake_toggle` filtré hors des Raccourcis (navigateur) ; M2 `destroy` des Raccourcis sans annuler la capture (F10
enregistré après départ) ; M3 focus non rendu à la touche après envoi ; M4 `openSettingsLink` sans pose du focus ;
M5 thème : section redessinée au choix (node) ; M6 clé `localStorage` du thème changée (navigateur) ; M7 vue de la scène
non détruite ; M8 Bare Hands dessine sans hôte monté ; M9 `destroy` Bare Hands garde l'hôte ; M10 la réinitialisation
allume Bare Hands (navigateur, POST `enabled:true`) ; M11 lecture de diagnostic remise dans la section ordinaire ;
M12 ancre `barehandsRecord` → `labs` ; M13 lien « encore dans » vers une section déjà enregistrée ; M14 Bare Hands
réinjecte un onglet ; M15 la capture laisse passer Échap jusqu'au shell (Réglages fermés) ; M16 lien de Voix sans cible
de focus.

### Preuves

Bac à sable `setui` (Core 127.77.0.1:27653, Control Center 127.0.0.1:27654, données/runtime au scratchpad `s06`,
visualiseur coupé), Chrome sans tête par CDP (`_wake_word_settings_browser.mjs`) : `evidence/s06/` — 31 PNG quantifiés
(2,5 Mo) : six vues (Thème & scène, Raccourcis, Bare Hands, Bare Hands · essais, Diagnostics, Expérimental) ×
{1920×1080, 1366×768} × {100 %, 125 % = largeur CSS /1,25}, détails ouverts, plus capture en cours, raccourci enregistré,
Tours en lecture seule, focus après lien, confirmation de réinitialisation Bare Hands, Cosmos, thème après rechargement ;
`runtime-check.json`. Constats : débordement horizontal 0 partout ; Cosmos appliqué tout de suite (`jarvis.ui.theme` =
`cosmos`, focus resté sur le bouton radio), relu après rechargement, remis à Circuit imprimé ; taille des étoiles
écrite sous `JarvisSceneView.KEY` puis réinitialisée ; capture + Échap : Réglages ouverts, touche inchangée,
« Capture annulée. » ; F10 → un seul POST `/api/shortcuts` `{"shortcuts":{"wake_toggle":"f10"}}`, focus sur la touche,
un seul éditeur ; Voix › Tours montre `f10` (0 éditeur), le lien ouvre Raccourcis avec le focus sur la touche ;
Bare Hands : aperçu décoché puis réinitialisé (deux POST `/api/barehands`, `enabled:false` les deux fois, cycle de vie
`off` avant/après) ; alias `appearance`, `shortcuts`, `barehandsSettings`, `barehandsRecord`, `experimental` ;
clavier seul : Début + 3 × flèche + Entrée sur le rail → Interface, Tab × 2 → entrées, Début + flèche droite + Entrée →
Raccourcis, Tab → touche `wake_toggle`, Entrée → capture, Échap → annulée (Réglages ouverts, focus sur la touche) ;
console vide. Le fichier de réglages du bac à sable porte `wake_toggle` = `f10` ; celui du poste de l'utilisateur
(`C:/Projects/jarvis/jarvis/runtime/control-center-settings.json`, lu seulement) garde `manual_wake_key` = `f9`.
PID arrêtés un par un après vérification de leur ligne de commande, sans `/T` : 26560 (cerveau claude du bac à sable,
`--mcp-config` sous `scratchpad\s06` ; ses dix MCP partis avec lui, vérifié), 28140 (Control Center ; lanceur 35964
parti avec lui), 37096 (Core ; lanceur 5780 parti avec lui). Core utilisateur 17653 (PID 31824) intact. Données du bac à
sable laissées en place.

### Écarts et reports

- `experimental` gardé (porte de la scène, Slice 08), libellé « Expérimental » inchangé, rangé dans Avancé.
- Non couvert par un test : la garde `isCurrent` de la réponse tardive d'un enregistrement de raccourci (code présent,
  mutation non construite) ; le chargement de `/api/shortcuts` dans la section quand les raccourcis ne sont pas encore
  lus (le démarrage de la page les lit toujours).
- À 1093×614, la liste des entrées d'Avancé défile horizontalement (Prompts, Expérimental hors vue : comportement des
  listes étroites de la Slice 02) ; « Arrêter » de l'enregistrement s'étire sur la ligne (mise en page héritée
  `.field.inline`). Pour la Slice 10.
- Les commentaires historiques de `control_center_barehands.js` et de `docs/barehands-contracts.md` parlent encore de
  « l'onglet Expérimental » (notes de Slices passées ; tête de fichier et tableaux d'entrée corrigés).

## 2026-10-22 - Slice 06 — retravail (QA)

- B1 (`83387ef1`) : maintien en vue généralisé dans le shell (`pinSettingsTarget` / `stopSettingsPin`, 4 s, rend la
  main à molette, touche, pointeur, toucher ; arrêté au lien suivant, au changement de section ou de catégorie et à la
  fermeture par `cleanupSettingsSurface`). Toute cible trouvée par `openSettingsLink` en profite ; « Voir le diagnostic
  mémoire » passe désormais par `context.open('diagnostics', {focus:'#diagnostic_memory'})` (plus de mécanisme à part).
  Test : `test_wake_word_diagnostic_link_keeps_its_part_in_view_after_voice_fills[1440x900|1366x768]` (partie Voix
  remplie plus haute que la zone visible, partie Mot d'éveil visible et focalisée 2,5 s après le lien). Le test node de
  la Slice 05 sur le maintien teste désormais le mécanisme du shell via la partie Mémoire.
- B2 : `test_a_late_shortcut_save_redraws_nothing_once_the_section_is_left[section|close]` (POST des raccourcis
  retenu, départ vers Thème & scène ou fermeture, puis réponse : 0 rendu, focus et hôte inchangés, valeur `f10` gardée
  et servie).
- N4 : clé `jarvis.scene.view` figée dans `test_theme_applies_in_place_persists_and_scene_view_resets`. N5 : commentaires
  de `control_center_barehands.js` (l. 4218, 6986, 7250, 7254, 9444, 9453, 9569, 9623, 9778), `OPERATIONS.md`,
  `ARCHITECTURE.md` et le double de `test_barehands_cards_js` mis à jour ; `settings-shell.md` § 3 décrit le maintien.
- Mutations (copie jetable `git worktree add --detach` de `83387ef1`, supprimée) : 5/5 tuées — R1 cible du lien sans
  maintien, R2a/R2b garde `isCurrent` de `startCapture` retirée (section / fermeture), R3 maintien sourd aux gestes,
  R4 clé de la scène changée.
- Tests : memory_settings_js + settings_shell_js + registry_js + scene_view_prefs + barehands_cards_js + appearance +
  quality + mvp 159 passed ; `-k "shortcut and not browser"` 16 passed. Navigateur : interface_settings_browser
  13 / 12 + 1 échec / 13 / 13 (quatre passes ; l'échec unique de la 2e passe n'a pas été identifié — sortie non
  conservée — et ne s'est pas reproduit en deux passes de plus) ; memory_settings_browser 6 + 6 ;
  settings_shell_browser 9 + 9 ; wake_word_settings_browser 10 + 10 et 10 + 10 (deux passes de chaque moitié).
  Aucun bac à sable lancé.

## 2026-10-22 - Slice 06 — décision QA (agent 0)

- QA initiale sur `fdee4491` : RETRAVAIL. Contrats inchangés (clés `jarvis.ui.theme`/`jarvis.scene.view`, POST `/api/barehands` identiques octet pour octet, POST raccourcis identique, Bare Hands jamais allumé), aucun lecteur de l'ancien `.tab` de `showSettings`, 8 raccourcis = 8 éditeurs, liens internes sans focus sur BODY. Bloquants : B1 cible de « Voir le diagnostic » (Mot d'éveil) focalisée mais hors écran ; B2 garde de réponse tardive d'un enregistrement de raccourci non testée (mutation survivante). Préexistants confirmés sur `20292e5c` et `f2e42635` : 3 de plus (2 `test_barehands_interaction_js::test_the_practice_frame_*`, `test_scene_group_drag_js::test_the_page_commits_a_group_drag…`), soit 10 au total avec les 7 connus.
- Retravail `83387ef1`, `70838816` : maintien en vue unique dans le shell (`pinSettingsTarget`/`stopSettingsPin`) réutilisé par la Mémoire, tests B1/B2, clé de scène figée, docs Expérimental. Re-QA : APPROUVÉ ; B1 rejoué en bac à sable (souris/clavier, 1366×768 et 1440×900, PageUp, molette, fermeture, lien suivant) ; `test_interface_settings_browser` 4/4 passes vertes (l'échec isolé vu par l'implémenteur non reproduit).
- Écart de méthode : la re-QA a laissé une partie de ses tests en arrière-plan.
- Pour la Slice 08 : `experimental` reste dans `TABS` et ne porte plus que la porte de scène ; entrées Avancé créées : section `barehands_lab` (groupe labs), partie de diagnostic `barehands`.
- Reporté Slice 10 : Tab enregistré pendant une capture de raccourci (préexistant) ; pas de contour après lien à la souris ; `outline:none` sur les contrôles Bare Hands (préexistant) ; libellé « Barehands éteint » ; lien des modèles remplacé pendant le chargement des sous-agents (focus sur BODY) ; liste d'Avancé qui défile à 1093 px ; test B1 navigateur ne prouve pas la croissance de Voix (observateur couvert seulement en unitaire) ; retrait des écoutes avec `capture` non testé ; `block:'start'` au lieu de `nearest` pour les petites cibles ; profil Chrome non suivi `.tmp-cosmos/` à la racine de `setui` (à ne pas committer, à nettoyer en fin de tâche).

## 2026-10-22 - Slice 07 (implémentation)

### Décisions

- `connections` › `providers` · Fournisseurs (order 10, `save:'self'`, alias `keys`, `CONNECTIONS_SECTION` de la page),
  rendue par un module pur nouveau `control_center_connections_settings.js` (`window.JarvisConnectionsSettings`,
  `html`, `create`, inséré par `control_center.py`). `TABS` = `prompts`, `experimental` (Slice 08). `tabKeys`,
  `addCredential`/`deleteCredential`/`bindCredential`, la branche `keys` de `renderTab`/`modalSub`/`bindTab` et le CSS
  `table.keys`/`.keyform` retirés.
- Une carte par fournisseur de `credentials_state` (ordre du serveur) : libellé, état (« Clé enregistrée » ok,
  « Variable d'environnement » avertissement, « Non configuré » neutre), clé active (radio + badge « Active »), clés
  (nom + indice), « Remplacer la valeur », « Supprimer » (confirmation sur place), retombée sur l'environnement (noms des
  variables seulement), « Ajouter une clé » (divulgation). Note d'usage = `providers[].hint` du serveur, omise s'il n'y
  en a pas ; aucune liste de fournisseurs, variables ni libellés dans le JS (test statique).
- Charges inchangées : ajout `{provider,name,value}`, liaison `{provider,id}`, suppression `{id}`. Remplacer = même
  route d'enregistrement avec `{id,provider,name,value}` (mise à jour par `id` déjà offerte par le magasin ; aucune
  route ni stockage changé).
- Secrets : la valeur est lue puis effacée du champ avant l'envoi ; journaux `connections_credential_*` sans valeur
  (action, fournisseur, code, statut). Régions vivantes `#connectionsStatus` (status) et `#connectionsError` (alert,
  message réel du serveur). Pendant l'écriture : commandes désactivées, attente dite ; au-delà de 15 s (`WAIT_MS`)
  l'erreur le dit et la section rend la main ; `destroy` arrête le minuteur et rend la vue muette. L'état reçu remplace
  `SET.data.credentials` et vide `SET.catalog` même section quittée ; rien n'est redessiné (`dead` + `isCurrent`).
- Focus : nouvelle clé / clé remplacée ou liée / titre de la carte (suppression, `tabindex=-1`) ; bouton de
  confirmation à l'ouverture, « Supprimer » d'origine après « Annuler ». Formulaire de remplacement ouvert : sous la
  ligne, « Supprimer » reste en tête (`order:2`).
- Liens entrants : Agent principal (aide du modèle) « Connexions › <fournisseur> » (`data-settings-open="providers"` +
  nouveau `data-settings-focus` lu par le délégué de la section → `context.open(cible,{focus})`) ; Mémoire (ligne du
  secret) `data-mem-open="providers"` libellé « Connexions ». Messages serveur et textes de page « onglet API Keys » →
  « Réglages › Connexions » (`app.py`, `model_catalog.py`, `memory_relay.py`, `memory_settings.py`,
  `control_center_catalog.js`, `control_center_wake_word.js`).

### Fichiers

`jarvis/runtime/control_center_connections_settings.js` (nouveau), `control_center.html`, `control_center.py`,
`control_center_memory_settings.js`, `control_center_catalog.js`, `control_center_wake_word.js`, `credentials.py`
(commentaire), `memory_relay.py`, `memory_settings.py`, `model_catalog.py`, `jarvis/app.py` ; docs
`docs/settings/connections.md` (nouveau), `settings/INDEX.md`, `settings/navigation-registry.md`,
`legacy/settings-tab-aliases.md`, `OPERATIONS.md`, `memory-tencent.md` ; fixture
`tasks/jarvis-settings-model-catalog-ux/.../agent-cli-ui.json` (`keys` → `rehosted_as_sections`) ; tests
`test_control_center_connections_settings_js.py` et `test_connections_settings_browser.py` (nouveaux),
`test_control_center_settings_registry_js.py` (`SLICE_07_SECTIONS`), `test_agent_cli_settings_ui.py`,
`test_control_center_memory_settings_js.py`, `test_control_center_mvp.py`, `test_control_center_voice_architecture.py`,
`test_voice_settings_ui.py`, `test_environment.py`, `test_settings_workbench.py`, `test_interface_settings_browser.py`,
`tests/integration/test_settings_redesign_migration.py`.

### Tests (comptes exacts, depuis `setui` @ `b6786c09` (+ CSS `order:2`), `.venv` du dépôt principal ; sorties complètes au scratchpad `s07/logs`)

- mvp + quality + voice_architecture + voice_settings_ui + wake_word_settings_ui + agent_cli_settings_ui +
  routing_settings_screen + catalog_ui + voice_architecture_ui_review : 209 passed.
- memory_settings_js + subagents_settings_js + appearance + scene_settings_ui + scene_view_prefs +
  barehands_tools_settings_js + barehands_cards_js + jarvis_wheel_js + mcp_inspector_js + control_center_memory_js :
  179 passed.
- settings_registry_js + settings_shell_js + intégration settings_redesign_migration + settings_ia_contract +
  voice_settings_surface + voice_settings_schema + shell_layers + variants_css_orphans + control_center_prompts +
  memory_settings_surface + memory_settings + memory_settings_endpoints : 274 passed.
- documented_routes + delivery_quality + wake_word_docs + remotion_no_fallback_privacy + settings_endpoints (API des
  clés) + settings_workbench (magasin de clés, catalogue) + environment + connections_settings_js (5) + credential_vault :
  232 passed.
- Navigateur (chaque commande < 600 s) : connections_settings_browser 9 passed (deux passes, avant et après le
  correctif CSS) ; settings_shell_browser + jarvis_wheel_browser 13 passed ; agents_models_settings_browser +
  memory_settings_browser 12 passed ; interface_settings_browser 12 passed + 1 failed à la 1re passe
  (`test_sections_aliases_single_wake_editor_and_barehands_split` attendait encore `keys` dans `TABS` : test mis à
  jour, `b6786c09`), puis 13 passed ; wake_word_settings_browser 10 + 10 passed.
- Balayage large sans navigateur (unit + intégration) : `-k "settings and not memory and not browser"` 720 passed,
  1 failed ; `-k "control_center and not settings and not memory and not browser"` 809 passed, 6 failed, 1 skipped ;
  `-k "memory and not browser"` 1311 passed, 4 skipped, 1 failed ; `-k "(subagent or work_method or routing or
  agent_cli or catalog or knowledge or loadout or wheel or shell or registry or credential or keys or connection or
  environment or model_catalog) and not settings and not memory and not control_center and not browser"` 1417 passed,
  3 skipped ; `-k "(scene or theme or appearance or cosmos or wake or voice_settings) and not settings and not memory
  and not control_center and not barehands and not browser and not subagent and not routing and not wheel and not shell
  and not registry"` 2621 passed, 19 skipped, 1 failed ; `-k "(barehands or shortcut) and not browser"` 1111 passed,
  1 skipped, 2 failed. Échecs : les 10 préexistants connus (test_app tools_gateway, 6 × test_control_center_mcp_api,
  2 × barehands practice_frame, scene_group_drag) et `test_memory_context::test_recall_over_2000_notes_…_stays_in_budget`
  (TimeoutError de la synchronisation d'index de 2000 notes sous charge ; relancé seul : `test_memory_context.py`
  38 passed ; non prouvé sur `20292e5c` ; ce chemin ne touche aucun fichier de la Slice hors deux libellés de message).

### Mutations (copie jetable `git worktree add --detach` de `b6786c09` au scratchpad, supprimée ensuite) : 15/16 tuées

M1 charge d'ajout + `label` ; M3 garde de réponse tardive retirée (`alive` toujours vrai + `dead` ignoré, tuée par le
cas « fermeture ») ; M4 `destroy` sans arrêt du minuteur ; M5 pas d'échéance ; M6 note serveur absente ; M7 ligne
d'environnement absente ; M8 alias `keys` retiré ; M9 charge de liaison réordonnée ; M10 suppression sans
confirmation ; M11 remplacement sans `name` ; M12 état ignoré après départ ; M13 `data-settings-focus` ignoré ;
M14 valeur dans un journal ; M15 champ valeur en `type=text` ; M16 focus non posé après ajout. Survivante,
équivalente : M2 (ne plus vider le champ avant l'envoi) — `write()` redessine la section (champs neufs et vides) dans
le même tour, avant la requête ; l'effacement est une seconde barrière, non observable tant que ce rendu a lieu.

### Preuves

Bac à sable `setui` (Core 127.77.0.1:27653, Control Center 127.0.0.1:27654, `JARVIS_DATA_ROOT`/`JARVIS_RUNTIME_DIR` au
scratchpad `s07`, visualiseur coupé, `DEEPGRAM_API_KEY` factice dans les seuls processus du bac à sable). Isolement du
magasin vérifié AVANT tout ajout : `settings_path` = `JARVIS_RUNTIME_DIR/control-center-settings.json`, lecture des clés
= 0 clé et la seule variable factice ; aucun `.env` dans `setui`, aucune variable de fournisseur dans le shell. Clés
factices `sk-test-FAKE-sandbox-…` seulement. Pilotage `_wake_word_settings_browser.mjs` : `evidence/s07/` — 17 PNG
quantifiés (1,36 Mo) : parcours (état initial, ajout au clavier, refus de doublon, liaison, remplacement ouvert,
confirmation de suppression, après suppression, lien d'Agent principal), focus clavier, Fournisseurs à 1920×1080 et
1366×768, 100 % et 125 % (largeur CSS /1,25), divulgations fermées et ouvertes ; `runtime-check.json`. Constats :
débordement 0 partout ; six POST aux charges attendues (ajout ×3 dont le doublon refusé « Une clé OpenAI porte déjà le
nom « Perso » », liaison, remplacement, suppression) ; aucune valeur factice dans le DOM, les champs ni les lectures des
clés et des réglages ; valeur vidée après refus, nom gardé ; Deepgram « Variable d'environnement » (nom seul) ; alias
`keys` → `connections/providers` ; lien d'Agent principal → focus `connection_anthropic_title` ; lien Mémoire →
Fournisseurs ; clavier seul : rail (Début + 4 × flèche + Entrée) → Connexions, Tab jusqu'à « Supprimer » avec contour ;
console vide. Fichier du bac à sable : une clé `Travail` factice liée ; fichier de l'utilisateur non lu (date 16/10
inchangée). PID arrêtés un par un après vérification de la ligne de commande, sans `/T` : 9128 (cerveau claude,
`--mcp-config` sous `scratchpad\s07`, ses 10 MCP partis avec lui), 31572 (Control Center), 6744 (Core) ; lanceurs
18544 et 35512 partis avec leur enfant. Core utilisateur 17653 (PID 31824) et Control Center 17654 (PID 34676) intacts.
Données du bac à sable laissées en place.

### Écarts et reports

- Disque C tombé à 0 octet libre pendant la Slice (ENOSPC à la première capture ; cause hors de cette Slice). Libéré :
  92 rendus `.mp4` d'un vieux temp Claude (`C--Projects-remotion-test\8b0e1fcd…`, 298 Mo, aucune base touchée). À
  surveiller : `pytest-of-Clarice\pytest-8122` (3,1 Go, 05:44) et le temp Claude `7314dd51…` (1,9 Go) contiennent des
  bases de test, laissés en place.
- « Remplacer la valeur » garde le nom ; renommer une clé n'est pas offert (hors périmètre, le magasin le permet).
- La région d'état garde le dernier message jusqu'à l'action suivante (comme avant).
- « API Keys » subsiste dans `docs/mcp/plan-outils-interface.md` (note historique d'une autre tâche).

## S07 — décision QA (agent 0), 2026-10-22

QA indépendante : **approuvable, aucun finding bloquant**. Charges et routes identiques à `tabKeys` (six POST vérifiés en
bac à sable) ; remplacement par `id` préexistant côté serveur (`credentials.py:246-256`, 9e1a7622) ; aucune valeur
factice dans DOM, champs, `/api/credentials`, `/api/settings`, console, `trace.jsonl` ni sorties Core/CC ; alias `keys`,
liens Agent principal et Mémoire OK ; aucun débordement à 1366×768. Tests : ciblés tous verts ; balayage large
23 162 passed / 12 failed / 95 skipped, les 12 échecs identiques sur `20292e5c`. La liste des échecs préexistants passe
à 12 : `test_brain_capability_parity::test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt` et
`test_tool_brain_choices::test_ui_projection_is_consistent_in_the_single_metadata_copy` s'ajoutent aux 10 connus.
`test_memory_context::…2000_notes…stays_in_budget` : intermittent lié au temps (limite fixe 30 s, indexation 15-20 s),
1/9 sur `setui`, 0/22 sur `20292e5c`, aucun fichier d'index ou de magasin touché par la tâche ; non imputé à la Slice.
Mutations QA : 6/8 tuées (E et F survivantes, voir ci-dessous). Slice 07 approuvée.

Non bloquants, confiés en commit `S7: fix` à l'agent de la Slice 08 :
- N1 : succès tardif après l'échéance affiche à la fois « Clé ajoutée » et l'erreur d'échéance (`view.error` non vidé,
  `control_center_connections_settings.js:156-158`).
- N2 : réponse d'un ajout dépassé traitée comme échec par `add()` (remet l'ancien nom pendant un second envoi).
- N4 : tests manquants — valeur dans un `console.*` (mutation E), garde du remplacement vide (mutation F).

Reportés à la Slice 10 : N3 (régions vivantes recréées à chaque rendu, statut hors de vue après défilement), N5 (message
serveur réaffiché tel quel), N6 (contour de la carte focalisée), N7 (« API Keys » dans
`docs/mcp/plan-outils-interface.md:118`).

Écarts de méthode QA : un lot pytest > 600 s basculé en arrière-plan par l'outil puis relancé en petits lots ; disque C
entre 3,4 et 4,9 Go libres pendant la QA (jamais sous 500 Mo).

## 2026-10-22 - Slice 08 (implémentation)

### Décisions

- Groupes déclarés dans le registre (`CATEGORY_GROUPS`, gelé comme `CATEGORIES`) : seule `advanced_diagnostics` en
  déclare cinq, dans cet ordre : `architecture_compat` (Architecture & compatibilité), `prompts` (Prompts &
  instructions), `runtime_cli` (Runtime & CLI), `diagnostics` (Diagnostics), `labs` (Labs & outils de test). Dans une
  catégorie à groupes, `group` est requis et doit être déclaré ; ailleurs il est refusé (nouveau code
  `settings_section_group`). `sections()` trie par rang du groupe, puis `order`, puis ordre d'enregistrement ;
  `R.groups(id)`, `snapshot().groups`, `shellNavigation` → `{notice, groups, items[].group}`.
- Avis de catégorie (`notice` du registre, Avancé seulement) : « Outils d’opérateur : architecture, prompts, runtime,
  état constaté et essais de JARVIS. Les réglages du quotidien sont dans les autres catégories. » Description de la
  catégorie inchangée (une version plus longue était tronquée à 1093×614, test du shell).
- Liste des entrées : un `div.set-group role=none` par groupe non vide, intitulé `span.set-group-label` (monospace,
  `aria-hidden`) qui décrit ses onglets (`aria-describedby`) ; les flèches ne parcourent que les onglets. En largeur
  ≥ 900 px la liste passe à la ligne au lieu de défiler (Labs en seconde ligne à 1366 et 1440) ; en dessous elle défile.
  Monospace réservé à Avancé : intitulés de groupe et éditeurs de prompt (`[data-category=advanced_diagnostics]`).
- Prompts : section `prompts` (ID = ancien ID d'onglet, groupe `prompts`, order 10, `save:'self'`, `PROMPTS_SECTION`).
  `tabPrompts` → `promptWorkbenchHtml` (contenu identique) ; `savePromptLayer`/`resetPromptLayer` : même route, mêmes
  charges, `SET.prompts` et `SET.restartNotice` comme avant ; l'issue se dit dans une région d'état propre
  (`[data-prompt-status]`, le pied est caché pour `self`) ; réponse arrivée section quittée : état gardé, rien dessiné ;
  focus rendu au bouton de la couche après le rendu.
- Scène : section `scene_gate` (« Scène constellation », groupe `labs`, order 40, alias `experimental`, `save:'self'`)
  enregistrée par `control_center_scene_settings.js` dans son `setTimeout` d'installation ; dessin dans l'hôte monté
  (`view.host`), plus d'enveloppe de `renderTab`, plus de `TABS`, `SET.tab`, `#modalContent` ni `#modalSub`. Sémantique
  de la porte, du battement `/api/status`, de la confirmation et du redémarrage inchangée.
  `LEGACY_TAB_ALIASES.experimental` → `scene_gate`.
- `TABS = []` ; branches `prompts`/`experimental` de `renderTab` et `modalSub` retirées. Laissés pour la Slice 09 :
  `TABS` vide, branche onglet de `renderTab`, `bindTab` (plus jamais appelé avec contenu), `canonicalSettingsTab`,
  `routing.tab:'cli'`, `legacyTabFor` (dont l'ancre → `experimental`), `navigationFromLegacyTabs`.
- Doublons : aucun. L'atelier ne projette aucune couche `subagent_role.*` (programmes Voix/backend seulement,
  `_prompt_payload`), donc pas de second éditeur des instructions de rôle ; `scene.enabled` n'a d'éditeur qu'ici (Thème
  & scène ne règle que l'apparence locale) ; champs Voix/Agent déjà uniques (Slices 03-04).

### Inventaire et affectation (sections `advanced_diagnostics`, grep sur `control_center*.js` + page)

| Section | Enregistrée par | Groupe | order |
| --- | --- | --- | --- |
| `architecture_compat` | page (`VOICE_SECTIONS`) | `architecture_compat` | 10 |
| `prompts` | page (`PROMPTS_SECTION`, Slice 08) | `prompts` | 10 |
| `runtime_cli` (alias `routing`) | page (`AGENT_SECTIONS`) | `runtime_cli` | 30 |
| `diagnostics` (parties Voix 10, Mot d'éveil, Mémoire 30, Bare Hands 40) | page + `control_center_wake_word.js`, `control_center_barehands.js` | `diagnostics` | 40 |
| `scene_gate` (alias `experimental`) | `control_center_scene_settings.js` (Slice 08) | `labs` | 40 |
| `work_methods` | page (`SUBAGENT_SECTIONS`) | `labs` | 50 |
| `barehands_lab` | `control_center_barehands.js` | `labs` | 60 |

Aucune autre : `test_advanced_groups_are_declared_once_and_every_page_registration_names_one` relève tout
`{id:…,category:'advanced_diagnostics'` du code servi et exige un groupe déclaré.

### Fichiers

`jarvis/runtime/control_center_settings_registry.js`, `control_center.html`, `control_center_scene_settings.js`,
`control_center.py` (commentaire) ; docs `docs/settings/INDEX.md` (§ Avancé & diagnostic), `navigation-registry.md`,
`settings-shell.md`, `interface-interactions.md`, `docs/legacy/settings-tab-aliases.md`, `OPERATIONS.md`,
`ARCHITECTURE.md` ; fixture `tasks/jarvis-settings-model-catalog-ux/.../agent-cli-ui.json` (`tabs: []`, `prompts` →
`rehosted_as_sections`) ; tests `test_advanced_settings_browser.py` (nouveau), `test_control_center_settings_registry_js.py`,
`test_scene_settings_ui.py`, `test_control_center_prompts.py`, `test_control_center_voice_architecture.py` (rendu tardif
de l'atelier), `test_control_center_voice_architecture_ui_review.py`, `test_voice_settings_ui.py`,
`test_agent_cli_settings_ui.py`, `test_settings_shell_browser.py`, `test_interface_settings_browser.py`,
`test_connections_settings_browser.py`, `tests/integration/test_settings_redesign_migration.py`.

### Report S07 (commit séparé `7eb74cc1`, `S7: fix`)

- N1 : la branche succès de `write()` vide `view.error`. N2 : `write()` rend `undefined` pour une réponse ignorée,
  `add()` n'y touche pas (ni nom remis, ni focus). N4 : capture de `console.log/info/warn/error/debug` dans le parcours
  complet (5 journaux `connections_credential_written` vus, aucune valeur factice) ; remplacement à valeur vide refusé
  sur place sans requête ; `test_a_late_success_clears_the_deadline_error_and_an_ignored_reply_touches_nothing`.
- Mutations (copie jetable de `7eb74cc1`, supprimée) : 4/4 tuées — N1 (`view.error` non vidé), N2 (`next===undefined`
  retiré), E (valeur dans `log.info`), F (garde du remplacement vide retirée).

### Tests (comptes exacts, depuis `setui`, `.venv` du dépôt principal, chaque commande < 600 s)

- Connexions après S7 fix : connections_settings_browser + connections_settings_js 14 passed + 1 failed (échéance trop
  courte du nouveau test, réglée), puis le test seul 1 passed ; connections_settings_browser complet 10 passed (après S8).
- Lot A (mvp, quality, voice_architecture, voice_settings_ui, wake_word_settings_ui, agent_cli_settings_ui,
  routing_settings_screen, catalog_ui, voice_architecture_ui_review) : 209 passed.
- Lot B (memory_settings_js, subagents_settings_js, appearance, scene_settings_ui, scene_view_prefs,
  barehands_tools_settings_js, barehands_cards_js, jarvis_wheel_js, mcp_inspector_js, control_center_memory_js) : 179 passed.
- Lot C (registry_js, shell_js, intégration settings_redesign_migration, settings_ia_contract, voice_settings_surface,
  voice_settings_schema, shell_layers, variants_css_orphans, control_center_prompts, memory_settings_surface,
  memory_settings, memory_settings_endpoints) : 275 passed (registry_js : 19 après l'ajout du test d'ordre).
- Lot D (documented_routes, delivery_quality, wake_word_docs, remotion_no_fallback_privacy, settings_endpoints,
  settings_workbench, environment, connections_settings_js, credential_vault) : 232 passed. Après docs et commentaires :
  12 fichiers touchés, 169 passed.
- Navigateur : advanced_settings_browser 5 + 1 failed (attente fausse dans le test, corrigée) puis passé ; seconde passe
  advanced + jarvis_wheel_browser 10 passed ; interface_settings_browser 13 ; settings_shell_browser +
  jarvis_wheel_browser 11 passed + 2 failed (`test_categories_keyboard_shortcuts_escape_and_focus_return` : liste
  attendue d'avant ; `test_no_category_overflows…[1093-614]` : description d'Avancé allongée tronquée — description
  rendue à l'originale), puis settings_shell_browser 9 passed ; agents_models + memory_settings_browser 12 ;
  wake_word_settings_browser 11 + 9. Aucun échec intermittent observé.
- Balayage large sans navigateur (unit + intégration) : `-k "settings and not memory and not browser"` 722 passed,
  1 failed ; `-k "control_center and not settings and not memory and not browser"` 809 passed, 6 failed, 1 skipped ;
  `-k "(scene or prompt) and not browser and not settings and not control_center and not barehands"` 2305 passed,
  2 failed, 17 skipped ; `-k "(barehands or shortcut) and not browser"` 1110 passed, 2 failed, 1 skipped ;
  `-k "(subagent or work_method or routing or agent_cli or catalog or wheel or shell or registry or connection or
  credential or theme or appearance or tool_brain) and not settings and not control_center and not browser and not
  scene and not prompt and not barehands"` 1322 passed, 1 failed, 1 skipped. Les 12 échecs sont exactement les 12
  préexistants connus (test_app tools_gateway, 6 × mcp_api, 2 × barehands practice_frame, scene_group_drag,
  brain_capability_parity, tool_brain_choices). `test_memory_context` n'a pas échoué.

### Mutations S8 (copie jetable `git worktree add --detach` de `d22870ed`, supprimée) : 12/12 tuées

M1 groupe non exigé ; M2 tri sans rang de groupe (survivante au premier passage : les `order` de la page donnaient le
même ordre → `test_advanced_sections_are_ordered_by_declared_group_before_their_order`, puis tuée) ; M3 `edit` sans
`expected_effective_revision` ; M4 `reset` avec texte ; M5 rendu tardif de l'atelier sans garde `isCurrent` ; M6 charge
de la porte changée ; M7 corps du redémarrage vide ; M8 porte rangée dans Diagnostics ; M9 liste sans groupes ;
M10 avis absent ; M11 alias `experimental` retiré de la section (survivante : la table héritée résolvait encore → la
source `section_alias` est vérifiée en vrai Chrome, puis tuée) ; M12 redémarrage sans confirmation.

### Preuves

Bac à sable `setui` (Core 127.77.0.1:27653, Control Center 127.0.0.1:27654, `JARVIS_DATA_ROOT`/`JARVIS_RUNTIME_DIR`
au scratchpad `s08`, visualiseur coupé), pilotage `_wake_word_settings_browser.mjs` : `evidence/s08/` — 9 PNG
quantifiés (0,87 Mo) et `runtime-check.json`. Constats : cinq groupes dans l'ordre, sections sous leur groupe, avis
d'opérateur, `TABS` vide et aucune entrée `data-tab` dans les six catégories ; les 7 sections se montent sans erreur ;
diagnostics Voix, Mot d'éveil, Mémoire, Bare Hands remplis ; alias `prompts` (section), `experimental` et `routing`
(`section_alias`) ; Prompts : `voice.persona` enregistrée au clavier (POST `edit` avec les deux révisions), relue par
`/api/prompts`, puis remise au défaut (POST `{action:'reset'}`), focus sur la couche, fichier du bac à sable sans
`prompt_overrides` après ; porte : Espace → `{scene:{enabled:false}}` puis `true`, fichier `{"scene":{"enabled":true}}` ;
redémarrage : statut et route simulés dans la page (aucun processus relancé), confirmation « Redémarrer le brain ? »,
corps `{"new_conversation":true}` ; clavier seul (rail Fin + Entrée, liste Début + flèches sur les seuls onglets,
Entrée, Tab vers `#f_scene` avec contour) ; débordement 0 partout (page, colonne, contenu, liste) à 1920×1080,
1366×768 et 1093×614, détails ouverts ; console sans exception ni `console.error/warn`.
PID lancés et arrêtés un par un après vérification de la ligne de commande (et du port écouté), sans `/T` : 7572
(cerveau claude, `--mcp-config` sous `scratchpad\s08` ; ses 10 MCP partis avec lui), 9584 (Control Center), 17800
(Core) ; lanceurs 27992 et 33464 et leurs conhost partis avec leur enfant. Core utilisateur 17653 (PID 31824) et Control
Center 17654 (PID 34676) intacts. Données du bac à sable laissées en place. Disque C : 3,6 Go libres au début, 3,5 Go
à la fin.

### Écarts et reports

- Labs passe en seconde ligne dès 1440 px ; l'intitulé du groupe garde son filet gauche en début de ligne (nuance
  visuelle, Slice 10).
- La Scène garde son propre titre (`h3` du module) au lieu de `JarvisSettingsUI.section` : relocation pure, pas de
  réécriture du rendu.
- Mentions « onglet Expérimental » hors de cette Slice (Bare Hands, Slice 06) : `barehands_commands.py:149` (message
  au cerveau), `settings_mcp.py:158` (libellé), commentaires de `control_center_barehands_*.js`,
  `docs/barehands-contracts.md` (historique). Non modifiées (périmètre Bare Hands ; tests de parité déjà rouges) :
  Slice 09/10.
- `bindTab` n'a plus d'appelant avec contenu ; ses liaisons `data-field`/`data-refresh` sont mortes depuis la
  Slice 03 : retrait avec la machinerie (Slice 09).
- Le redémarrage du cerveau a été vérifié par requête simulée dans la page, pas par un vrai redémarrage.

## S08 — décision QA (agent 0), 2026-10-22

QA indépendante : **approuvable, aucun finding bloquant**, correctif S7 (`7eb74cc1`) compris. Les 7 sections d'Avancé
portent chacune un groupe déclaré (relevé par grep sur tout le code servi, refus à l'exécution `settings_section_group`) ;
`TABS.length=0`, `#modalSub` vide en vrai Chrome. Charges identiques à `cb6f011c` : prompts edit/reset, porte
`{scene:{enabled:…}}`, redémarrage `{"new_conversation":true}` — ce dernier cliqué pour de vrai en bac à sable après
preuve que le cerveau était l'enfant du Control Center du bac à sable. Cycle de vie et focus corrects ; N1, N2, N4 de S07
corrigés et probants. Débordement nul pour les 7 sections à 1366×768 et 1093×614 ; clavier seul OK. Tests : ciblés tous
verts ; balayage 22 919 passed / 14 failed / 93 skipped = les 12 préexistants + l'intermittent connu
`test_memory_context::…2000_notes…` + `test_device_playback_completion::test_runtime_provider_can_close_while_device_pending_but_cannot_reopen`
(vert 4/4 en relance, `wait_for` 0,2-0,3 s sous charge concurrente, aucun fichier importé dans le diff : intermittent,
non imputé). Mutations QA 7/10 tuées ; survivantes Q7 (effacement de `view.error` au remontage, hérité), Q8
(`SET.data.scene` corrigé par le battement), Q10 (presque équivalente). Slice 08 approuvée.

Confiés à la Slice 09 : textes qui citent encore l'« onglet Expérimental » alors qu'il n'existe plus —
`barehands_commands.py:149` (renvoyé au cerveau comme erreur d'outil), `settings_mcp.py:158` (libellé montré au
cerveau), `docs/OPERATIONS.md:1160`, commentaires `control_center_barehands_*.js`, `docs/barehands-contracts.md` ; Bare
Hands est dans Interface › Bare Hands.

Reportés à la Slice 10 : filet gauche de Labs en début de ligne ; Scène sans `JarvisSettingsUI.section` (h3 propre, pas
de badge) ; atelier de prompts qui perd un texte en cours d'une autre couche à l'enregistrement (préexistant) ;
minuteur du redémarrage non arrêté par `destroy` ; tests manquants (garde de réponse tardive de la scène, débordement
d'Avancé à 1093×614, mutations Q7/Q8).

Écarts de méthode QA : quatre pytest au-delà de 600 s basculés en arrière-plan par l'outil (attendus sans Monitor,
intégration relancée en deux moitiés au premier plan) ; disque C au plus bas à 1,38 Go.

## 2026-10-22 - Slice 09 (implémentation)

### Décisions

- **Une seule table d'alias, explicite.** `LEGACY_TAB_ALIASES` du registre est la seule source : `{id: {category,
  section}}`, gelée, sans `also` ni `tab`. Le champ `aliases` des sections est retiré de `register` (refusé comme champ
  inconnu, `settings_section_invalid`) ; un ID de section égal à un alias est refusé (`settings_alias_conflict`).
  `resolve` rend `source: 'alias'` (plus de `section_alias`, `legacy_tab`, `legacy_anchor`). `DEFAULT_CATEGORY`
  (= `voice_audio`, la première) est une donnée du registre.
- **Alias gardé : `memory` seul** (→ `memory_knowledge` / `recall`), appelant `control_center_memory.js`
  (`root.selectTab('memory')`, bouton Réglages du Memory Center). Le test exige l'appelant (`ALIAS_CALLERS`).
- **Retirés** (aucun appelant du dépôt ni document durable qui s'en serve) : `voice` (la roue passe à `voice_audio`,
  comme prévu par `navigation-registry.md` § 4), `wakeword`, `cli`, `routing` (et la redirection historique
  `routing` → `cli`), `keys`, `appearance`, `experimental`, et les ancres `LEGACY_ANCHORS` (`barehandsSettings`,
  `barehandsCalibration`, `barehandsRecord`, `barehandsBenchmarkSection` : `JarvisBarehands.showSettings` passe par
  sa propre table `SECTION_ENTRY`, personne n'appelait `openSettingsTab` avec une ancre). `prompts`, `shortcuts` et
  `subagents` ne sont pas des alias : ce sont les ID mêmes de leurs sections.
- **Machinerie retirée** : `TABS`, `SET.tab`, branche onglet de `renderTab`, `bindTab` (et ses liaisons
  `data-field`/`data-refresh` mortes), `canonicalSettingsTab`, `legacyTabFor`, `navigationFromLegacyTabs`,
  `#modalSub` (+ CSS `.set-sub`), liens « encore dans » (`related`, `#settingsRelated`, `.set-related`, `.set-link`),
  alerte `settings_tab_unassigned`, repli `TABS` de `voiceHomeLabel`. `shellNavigation(registry)` →
  `{categories}` ; `shellTarget(cible, nav, registry)`. Les noms `renderTabs` / `renderTab` / `selectTab` restent :
  ce sont les points d'appel du shell et de nombreux modules et tests ; ils ne concernent plus d'onglet (documenté
  dans `settings-shell.md` § 1). Aucune persistance touchée (la position des Réglages n'a jamais été persistée).
- **`openSettingsTab(id)`** : catégorie, section ou alias ; une cible inconnue (dont un ID retiré) est journalisée
  (`console.warn('settings_target_unknown', {target})`) et ouvre le shell sur `DEFAULT_CATEGORY` (réglages fermés :
  ils s'ouvrent ; ouverts : l'emplacement y passe, par `showSettingsTarget`, nouvelle fonction partagée avec
  `selectTab`). `selectTab` et `openSettingsLink` d'une cible inconnue la journalisent et ne bougent rien (inchangé).
- **Roue** : `settingsTabs()` = les six catégories (inchangé) ; la ligne « Réglages de la voix » ouvre
  `VOICE_SETTINGS_TARGET = 'voice_audio'` (détail « ouvre les réglages, catégorie Voix & audio »).
  `ui_tab_next` / `ui_tab_prev` : comportement inchangé et défini (six catégories en boucle par `cycleCategory`),
  testé (node + `test_settings_shell_browser`) et prouvé en bac à sable.

### Inventaire des ID hérités (grep code, tests, docs durables)

| ID | Avant | Appelants trouvés | Décision |
| --- | --- | --- | --- |
| `voice` | alias de `conversation` | roue (`openSettingsAt('voice')`), `docs/control-center-shell.md` | retiré ; roue → `voice_audio`, doc mise à jour |
| `wakeword` | alias de `wake_word` | tests seulement | retiré |
| `prompts` | ID de section | tests | reste (ID de section) |
| `cli` | alias de `main_agent` | tests, fixture historique `agent-cli-ui.json` | retiré (fixture : `retired_programmatic_ids`) |
| `routing` | alias de `runtime_cli` (redirection `cli`) | tests, fixture historique | retiré |
| `keys` | alias de `providers` | tests, `connections.md` (description de l'alias) | retiré |
| `shortcuts` | ID de section | tests | reste (ID de section) |
| `memory` | alias de `recall` | Memory Center › Réglages | **gardé**, testé |
| `subagents` | ID de section | tests | reste (ID de section) |
| `appearance` | alias de `theme_scene` | tests | retiré |
| `experimental` | alias de `scene_gate` | tests | retiré |
| ancres Bare Hands | `LEGACY_ANCHORS` | aucun appel `openSettingsTab` | retirées |

### Textes corrigés (onglets disparus)

- Montrés au cerveau : `barehands_commands.py` (erreur `barehands_disabled` : « il faut l'allumer … par
  settings_set(barehands.enabled, true) avec l'accord de l'utilisateur, ou par l'utilisateur dans Réglages › Interface
  & interactions › Bare Hands »), test `test_the_gate_refuses_before_waiting_rather_than_after` mis à jour ;
  `settings_mcp.py` `EXTRA_CATEGORIES` (`hands`, `agenda`) — constante en fait non lue par `describe` (morte), libellés
  corrigés quand même ; `app.py` (2 erreurs « onglet Mode vocal ») et `presentation_runtime.py`
  (`LEGACY_REFUSAL_MESSAGE`, `DUPLEX_REFUSAL_MESSAGE`) → « Réglages › Avancé & diagnostic › Architecture &
  compatibilité ».
- Montrés à l'utilisateur : `control_center_boards.js` (refus PRESENTATION, même destination), confirmation de
  réinitialisation Bare Hands (« Les réglages Bare Hands ne sont pas touchés »), journal de repli Bare Hands, détail de
  la ligne voix de la roue.
- Commentaires : `control_center_barehands*.js`, `control_center.py`, `control_center_scene_settings.js`,
  `control_center_work.js`, page. Docs : `OPERATIONS.md` (Test Bare Hands, A1.1, A1.2, refus PRESENTATION, note des
  ID), `SECURITY.md` (2), `ARCHITECTURE.md`, `control-center-shell.md` (roue), note de remplacement en tête de
  `barehands-contracts.md` (l'histoire n'est pas réécrite).
- Laissés (historiques ou hors périmètre) : mentions « Mode vocal » de `docs/HARDWARE_ACCEPTANCE.md` et
  `docs/fixes/…`, `docs/mcp/plan-outils-interface.md`, `docs/work-methods.md:240` ; fonctions mortes de l'ancien onglet
  Voix (`authSectionHtml`, `aecHtml`, `renderField`) non retirées (contenu, pas machinerie d'onglets) — Slice 10.

### Fichiers

Code : `control_center_settings_registry.js`, `control_center.html`, `control_center_jarvis_wheel.js`,
`control_center_wake_word.js`, `control_center_work.js`, `control_center_scene_settings.js`,
`control_center_barehands.js`, `_contracts.js`, `_hud.js`, `control_center_boards.js`, `control_center.py`,
`barehands_commands.py`, `settings_mcp.py`, `presentation_runtime.py`, `app.py`. Docs : `docs/legacy/settings-tab-aliases.md`
(table finale + inventaire), `docs/settings/navigation-registry.md` (§ 2, 3, 4, 5, 6), `settings-shell.md`, `INDEX.md`
(note de remplacement des consommateurs du contrat IA), `connections.md`, `interface-interactions.md`, `memory.md`,
`voice-audio.md`, `agents-models.md`, `OPERATIONS.md`, `SECURITY.md`, `ARCHITECTURE.md`, `control-center-shell.md`,
`barehands-contracts.md` ; `tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json`
(`navigation_superseded_by`), fixture `agent-cli-ui.json`. Tests : registre (réécrit), shell, wheel js/navigateur,
advanced/agents/connections/interface/memory navigateur, agent_cli, agenda, appearance, memory_settings, subagents,
voice_settings_surface/ui, scene_settings_ui, routing_settings_screen, barehands_cards, barehands_command_channel,
intégration `settings_redesign_migration`.

### Tests (comptes exacts, depuis `setui`, `.venv` du dépôt principal, chaque commande < 600 s, sorties au scratchpad `s09/logs`)

- Nouveaux / réécrits (registre, node) : `test_every_remaining_alias_is_explicit_data_with_a_caller_and_its_declared_destination`,
  `test_no_legacy_tab_machinery_is_left_in_the_repository` (aucun `TABS.push/splice/unshift` dans `jarvis/`, ni
  `const TABS=`, `SET.tab`, `bindTab`, `canonicalSettingsTab`, `legacyTabFor`, `LEGACY_ANCHORS`, `modalSub`…),
  `test_an_unknown_or_retired_id_is_logged_and_opens_the_default_category[closed|open]`,
  `test_page_routes_categories_sections_and_aliases_into_the_six_category_shell` (sous-menu = six catégories),
  `test_no_registered_section_declares_an_alias`, `test_category_cycle_wraps_in_canonical_order` ; roue : ligne voix →
  `voice_audio` (node) et espion `openSettingsTab` → `["voice_audio"]`, aucune cible inconnue (vrai Chrome).
- Registre : 20 passed. Premier lot touché (14 fichiers) : 214 passed, 3 failed (attentes à mettre à jour :
  apparence `aliases`, mémoire `aliases:['memory']`, libellé « Voix & audio » dans un commentaire) → corrigés, 23 + 15 passed.
- Roue js + navigateur : 11 passed (62 s). Navigateur : advanced + agents_models 12 passed (329 s) ; connections +
  memory 16 passed (434 s) ; interface 12 passed + 1 failed (ordre de ma propre tournée), puis 1 passed ;
  settings_shell 9 passed (245 s) ; wake_word 11 + 9 passed (305 s + 247 s).
- Lot A (18 fichiers settings/roue/scène/Bare Hands) : 344 passed, 1 failed (`test_routing_settings_screen` attendait
  `aliases:['routing']` et la garde de l'ancien rendu d'onglet) → corrigé ; lot C (20 fichiers dont routing, registre,
  shell, intégration, IA contract, surfaces, prompts, mémoire, routes documentées, endpoints, connexions, canal Bare
  Hands, settings_mcp, agenda, présentation) : 548 passed.
- Balayage sans navigateur (unit + intégration, après commit `9c509238`) : `-k "settings and not memory and not
  browser"` 723 passed, 1 failed ; `-k "control_center and not settings and not memory and not browser"` 809 passed,
  6 failed, 1 skipped ; `-k "(scene or prompt) and not browser and not settings and not control_center and not
  barehands"` 2305 passed, 2 failed, 17 skipped ; `-k "(barehands or shortcut) and not browser"` 1109 passed,
  2 failed, 1 skipped ; `-k "(subagent or work_method or routing or agent_cli or catalog or wheel or shell or registry
  or connection or credential or theme or appearance or tool_brain or app or presentation_runtime or boards) and not
  settings and not control_center and not browser and not scene and not prompt and not barehands"` 1763 passed,
  1 failed, 1 skipped. Les 12 échecs sont exactement les 12 préexistants connus ; aucun intermittent observé.

### Mutations (copie jetable `git worktree add --detach` de `9c509238` au scratchpad, supprimée) : 13/13 tuées

M1 alias `memory` vers une autre section ; M2 alias retiré réintroduit (`voice`) ; M3 table vidée ; M4 ID inconnu sans
catégorie par défaut ; M5 ID inconnu sans journal ; M6 catégorie par défaut = la dernière ; M7 sous-menu de la roue à
cinq catégories ; M8 roue vers l'ancien ID `voice` ; M9 repli caché dans une condition (`keys`) ; M10 champ `aliases`
de nouveau accepté ; M11 ID de section égal à un alias accepté ; M12 un module refait `TABS.push` ; M13 alias résolu
sans vérifier que sa section est enregistrée.

### Preuves

Bac à sable `setui` (Core 127.77.0.1:27653, Control Center 127.0.0.1:27654, `JARVIS_DATA_ROOT`/`JARVIS_RUNTIME_DIR` au
scratchpad `s09`, visualiseur coupé), vrais clics et frappes CDP (`_interaction_mode_browser.mjs`, 1440×900) :
`evidence/s09/` — 6 PNG quantifiés (0,47 Mo) et `runtime-check.json`. Constats : roue › Paramètres = six entrées dans
l'ordre du registre, « Avancé & diagnostic » ouvre `advanced_diagnostics` / `architecture_compat` ; roue › JARVIS ›
Réglages de la voix → `openSettingsTab('voice_audio')` → Voix & audio / Conversation ; `memory` → `recall`
(`source: alias`), table = `{memory}` ; `openSettingsTab('nope')` réglages fermés → Voix & audio / Conversation et
`settings_target_unknown` ; ouverts sur Fournisseurs, `openSettingsTab('experimental')` → Voix & audio et journal ;
les huit anciens ID testés résolvent `null` ; Ctrl+→ ×2, Ctrl+← ×2, Ctrl+← : voice_audio → agents_models →
memory_knowledge → voice_audio → advanced_diagnostics (boucle) ; `typeof TABS` = `undefined`, aucune entrée
`data-tab`, ni `#settingsRelated` ni `#modalSub` ; console sans erreur ni exception (seuls les deux avertissements
attendus). PID lancés puis arrêtés un par un après vérification de la ligne de commande et du port écouté, sans `/T` :
15072 (cerveau claude du Control Center du bac à sable, `--mcp-config` sous `scratchpad\s09` ; ses 10 MCP partis avec
lui, vérifié), 39496 (Control Center, port 27654 ; lanceur 38876 parti avec lui), 37920 (Core, port 27653 ; lanceur
3164 parti avec lui). Core utilisateur 17653 (PID 31824) et Control Center 17654 (PID 34676) intacts. Données du bac à
sable laissées en place. Disque C : 58 Go libres au début et à la fin.

### Écarts et reports

- Noms `renderTab` / `renderTabs` / `selectTab` gardés (points d'appel, plus d'onglet derrière) : renommage = churn
  de nombreux modules et tests sans effet ; à trancher par la QA si le contrat l'exige.
- Fonctions mortes de l'ancien onglet Voix (`authSectionHtml`, `aecHtml`, `renderField`, `catalog` pour
  `data-refresh`) : contenu hors machinerie d'onglets, non retirées (Slice 10).
- `EXTRA_CATEGORIES` de `settings_mcp.py` n'est lue par aucun code : le libellé n'atteint pas le cerveau ; corrigé
  sans le brancher.
- Doubles de test Bare Hands (`test_barehands_tools_settings_js.py`) gardent un `global.TABS=[]` sentinelle et un
  `modalSub` factice : sans effet (le module n'en lit aucun), laissés.
- Ancien texte « Mode vocal » dans des documents historiques (`HARDWARE_ACCEPTANCE.md`, `docs/fixes/…`) non réécrit.

## S09 — décision QA (agent 0), 2026-10-22

QA indépendante : **approuvable, aucun finding bloquant**. Aucun appelant oublié d'un ID retiré : code JS, serveur,
MCP, `ui_intent`, prompts du cerveau, valeurs persistées (aucune), liens profonds (aucun) et `C:/DevTools/skills-lib`
(aucune mention). Seul alias `memory` (appelant : bouton du Memory Center, clic réel en bac à sable → Rappel). Aucun
`TABS.*` ; `LEGACY_TAB_ALIASES = {memory}` seule table ; ID retiré → `settings_target_unknown` + Voix & audio. Les
destinations citées par les textes corrigés existent. Six catégories : mémoire de la dernière section, Échap puis
réouverture, Ctrl+→/← en boucle — comme avant. Garder les noms `renderTab`/`renderTabs`/`selectTab` est accepté. Tests :
74 navigateur verts, balayage 8 527 passed, échecs = les 12 préexistants + l'intermittent `test_memory_context`.
Mutations QA 8/12 tuées. Slice 09 approuvée.

Non bloquants, confiés à la passe de finitions avant la Slice 10 :
- N1 : test navigateur du bouton Réglages du Memory Center → Rappel (mutation Q1 survivante).
- N2 : tests des messages corrigés `app.py:1101/1167`, `presentation_runtime.py:159-167`, `control_center_boards.js:410`
  (Q6-Q8 survivantes).
- N3 : commentaires/docs périmés (`docs/ARCHITECTURE.md:2554`, `control_center_wake_word.js:12/847`,
  `control_center.html:4466`, `control_center.py:837`).
- N4 : `workspace.unknown_action {"name":"settings"}` au clic du Memory Center (préexistant, déjà relevé en S05).
- N5 : le message Bare Hands « avec l'accord de l'utilisateur » contredit `BRAIN_SETTINGS_PROMPT` ; décision agent 0
  (option recommandée) : aligner le message sur la politique du prompt de réglages existant.

## 2026-10-23 - Passe de finitions avant S10

Seul writer de `setui`, depuis `4602d3af`. Reports non bloquants des Slices 00-09 (entrées de décision QA et lignes
« Reporté »), dédoublonnés.

### Reports et leur sort

| Item | Origine | Décision |
| --- | --- | --- |
| Bande de pied vide sur les entrées sans Enregistrer | S02 | déjà résolu (pied caché si `save` ≠ `footer`, S02) |
| Rangée « encore dans » encombrée dans Avancé | S02 | déjà résolu (liens retirés, S09) |
| Contraste des états désactivés / lecture seule | S02, re-QA S02 | corrigé : opacité 0,7 dans le shell, ≥ 4,5:1 mesuré sur toutes les sections (`511f4253`) |
| Couleurs forcées non vérifiées | re-QA S02 | corrigé : focus et arrivées en `Highlight`, désactivés en `GrayText` ; testé en émulation (`511f4253`) |
| Mouvement réduit limité au shell | S02 | corrigé : animations et transitions des modules aussi (`511f4253`) |
| Route clavier seule de la roue, raccourci `s`, Échap sous une confirmation | re-QA S02 | hors périmètre : vérifications de la QA S10 (aucun défaut connu) |
| Action de roue qui cache un élément focalisé hors d'elle | re-QA S02 | hors périmètre : aucun cas dans le dépôt |
| Focus sur BODY après « Modifier dans … › Raccourcis », « Voir le diagnostic » | S03 | déjà résolu en S06 (`openSettingsLink`) ; contour ajouté (`ff976902`) |
| Premier Tab parti une fois sur `dockMore` | S03 | non reproduit (à revoir par la QA S10 au clavier) |
| Lenteur du test du détecteur (attente 15 s) | S03 | hors périmètre : harnais de test, pas de défaut produit |
| `installVoiceSettingsSections()` gardé par un test de texte (N-a) | S03 | déjà couvert : retirer l'appel fait échouer `test_settings_shell_browser` (mutation M22) |
| Focus sur BODY après « Régler la commande », renvois Work Methods | S04 | déjà résolu en S06 ; arrivée marquée (`ff976902`) |
| Titre / pastille de Work Methods apprises | S04 | corrigé : tête de section du shell (`9fb8fd54`) |
| Commentaires citant des routes dans `control_center.html` | S04 | vérifié : aucune route citée en commentaire qui ne soit enregistrée par le serveur |
| Filtres du catalogue coupés à 1366×768 | S04 | corrigé : passage à la ligne, groupe trop large compris (`9fb8fd54`, `9532eb25`) |
| Pas de contour au focus de `#f_cli_model` | S04 | corrigé : `.field input:focus{outline:none}` n'efface plus le contour dans le shell (`ff976902`) |
| Focus sur BODY après « Enregistrer la mémoire » | S05 | corrigé : `keepFocus`, boutons `aria-disabled` (`2e124a60`) |
| Focus sur BODY après changement de section | S05 | corrigé : depuis le contenu (Ctrl+→), focus sur l'entrée ouverte, arrivée marquée (`2e124a60`, `b7155dac`) |
| Brouillon mémoire jeté à la fermeture sans prévenir | S05 | hors périmètre : décision produit (ci-dessous) |
| Message de refus non revu après changement de section | S05 | hors périmètre : le brouillon est gardé ; le message dit ce qui vient d'arriver (règle N4 de S05) |
| Test du maintien en vue aveugle à `capture` (M4) | S05, S06 | corrigé : double DOM sensible à l'option (M17 tuée, `2e124a60`) |
| `ARCHITECTURE.md:102`, `memory.md:830` (onglet Mémoire) | S05 | corrigé (`2e124a60`) |
| « Sidecar Tencent » répété | S05 | corrigé : « Sidecar actif », « Recherche sémantique active » (`2e124a60`) |
| `workspace.unknown_action {"name":"settings"}` | S05, S09 N4 | corrigé : Sessions & Boards ignore les clics et envois du Memory Center qu'il héberge (`2e124a60`) |
| Échec ponctuel non identifié d'une passe navigateur groupée | S05 | non reproduit ; un seul échec d'infrastructure vu ici (Chrome sans port de débogage), relancé vert |
| Garde de réponse tardive d'un raccourci | S06 | déjà résolu au retravail S06 (B2) |
| `/api/shortcuts` lu par la section si absent | S06 | hors périmètre : chemin inatteignable (la page les lit au démarrage), non testé |
| Liste d'Avancé qui défile à 1093 px | S06 | déjà résolu en S08 (passage à la ligne) ; test ajouté à 1093×614 (`464dc166`) |
| « Arrêter » étiré | S06 | corrigé : règle dans la page, la feuille Bare Hands n'existant que Bare Hands allumé (`ff976902`) |
| Mentions « onglet Expérimental » | S06, S08 | déjà résolu en S09 ; restes historiques volontaires (« ancien onglet ») |
| Tab enregistré pendant une capture | S06 | voulu : `shortcuts.py` accepte `Tab` ; documenté (`interface-interactions.md` § 3), inchangé |
| Pas de contour après lien suivi à la souris | S06 | corrigé : `landFocus` (`data-settings-landed`, `ff976902`) |
| `outline:none` des contrôles Bare Hands | S06 | corrigé (même règle que `#f_cli_model`) |
| « Barehands éteint » | S06 | corrigé : « Bare Hands … » pour tous les états, OPERATIONS.md suivi (`ff976902`) |
| Lien des modèles remplacé pendant le chargement des sous-agents | S06 | corrigé : `keepFocus` dans la vue des rôles (`ff976902`) |
| Croissance de Voix non prouvée en navigateur | S06 | corrigé : test qui ajoute 1 600 px APRÈS le lien (`ff976902`) |
| Retrait des écoutes avec `capture` non testé | S06 | corrigé (voir M4 de S05) |
| `block:'start'` pour les petites cibles | S06 | corrigé : `nearest` pour une touche ou un bouton, `start` pour une partie (`ff976902`) |
| Profil Chrome `.tmp-cosmos/` à la racine | S06 | hors périmètre : non touché, à nettoyer en fin de tâche |
| N3 régions vivantes recréées, statut hors de vue | S07 | corrigé : nœuds stables, erreur collée en haut, succès sur la carte focalisée (`630c8850`) |
| N5 message serveur réaffiché tel quel | S07 | conforme : message réel du serveur (règle des erreurs), inchangé |
| N6 contour de la carte focalisée | S07 | corrigé (`landFocus`, `630c8850`) |
| N7 « API Keys » dans `plan-outils-interface.md:118` | S07 | hors périmètre : plan historique déclaré en tête du document |
| Renommer une clé | S07 | décision produit (ci-dessous) |
| Filet gauche de Labs en début de ligne | S08 | corrigé (`464dc166`) |
| Scène sans `JarvisSettingsUI.section` | S08 | corrigé : tête du shell, badges « Avancé » et « Mode test » (`464dc166`) |
| Texte en cours d'une autre couche perdu à l'enregistrement | S08 | décision produit (ci-dessous) |
| Minuteur du redémarrage non arrêté par `destroy` | S08 | corrigé : compteur arrêté au départ, repris au retour ; échéance inchangée (`464dc166`) |
| Tests : réponse tardive de la scène, débordement 1093×614, Q7, Q8 | S08 | corrigé : tests navigateur, mutations M9, M10, M23, M24 tuées (`464dc166`) |
| N1 test Memory Center › Réglages | S09 | corrigé (`2e124a60`) |
| N2 tests des messages corrigés (Q6-Q8) | S09 | corrigé : destinations des messages vérifiées sur le registre vivant (M19 tuée, `5e56bf85`) |
| N3 commentaires et docs périmés | S09 | corrigé (`5e56bf85`) |
| N5 message Bare Hands contre `BRAIN_SETTINGS_PROMPT` | S09 | corrigé : allumer sur demande sans redemander de confirmation ni renvoyer à l'interface (`5e56bf85`) |
| Code mort `authSectionHtml`, `aecHtml`, `renderField`, `data-refresh` | S08, S09 | corrigé : retirés avec leurs aides (`authVerdictHtml`, `authEffectiveHtml`, `verifierHtml`, `catalog()`), déjà sans appelant sur main (`5e56bf85`) |
| `EXTRA_CATEGORIES` de `settings_mcp.py` jamais lue | S09 | hors périmètre : constante du serveur MCP, pas des Réglages |
| Doubles de test Bare Hands avec `TABS` sentinelle | S09 | hors périmètre : sans effet |

### Commits

`5e56bf85` S9, `2e124a60` S5, `9fb8fd54` S4, `ff976902` S6, `630c8850` S7, `464dc166` S8, `511f4253` S2, `9532eb25` S4
(groupe de filtres trop large, trouvé par `test_open_voice_model_comparison_does_not_overflow`), `b7155dac` S5 (arrivée
sans contour après Ctrl+→, trouvée en bac à sable). Commits séparés par indexation de hunks : seul l'état final a été
testé, pas chaque commit isolément.

### Tests (depuis `setui`, `.venv` du dépôt principal, chaque commande < 600 s, sorties au scratchpad `s10p/logs`)

- Hors navigateur : lot A 209 passed ; lot B 179 passed ; lot C 276 passed + 1 failed (`z-index` non déclaré de
  l'erreur collée, retiré) puis `test_control_center_shell_layers` 12 passed ; lot D + canal Bare Hands + palette +
  settings_mcp 302 passed ; workspace js + presentations js + cycle de vie et contrats Bare Hands 100 passed.
- Navigateur : memory + connections 17 ; settings_shell + wheel 11 passed + 2 failed (filtres du comparatif Voix,
  corrigé par `9532eb25`) puis settings_shell 9 ; agents_models + wheel 10 ; interface 13 + 1 échec d'infrastructure
  (Chrome sans port) puis ce test 4 passed ; advanced + destinations 10 ; accessibilité 9 ; wake_word 10 + 10 ;
  memory 7 ; connections 10 ; dossier_fullscreen 19 + 3 skipped ; workspace_manager 2. Après `b7155dac` :
  settings_shell + accessibilité 18 ; interface 14.
- Balayage (unit + intégration) : settings 723 / 1 failed ; control_center 809 / 6 failed / 1 skipped ; scene ou prompt
  2305 / 2 failed / 17 skipped ; barehands ou shortcut 1109 / 2 failed / 1 skipped ; agents, catalogue, workspace, app
  2127 / 1 failed / 4 skipped ; memory 1311 / 1 failed / 4 skipped. Total 8384 passed, 13 failed : les 12 préexistants
  de `20292e5c` et l'intermittent `test_memory_context::…2000_notes…`.

### Mutations (worktree jetable `git worktree add --detach` au scratchpad, supprimé) : 24/24 tuées

M1 garde Memory Center retirée ; M2 `disabled` au lieu d'`aria-disabled` ; M3 rendu mémoire sans `keepFocus` ; M4 pas
de reprise du focus au changement de section ; M5 arrivée non marquée ; M6 contour des champs hérités retiré ; M7 rôles
sans `keepFocus` ; M8 régions vivantes recréées ; M9 compteur gardé par `destroy` ; M10 compteur non repris ; M11 filet
de Labs d'avant ; M12 « Arrêter » étiré ; M13 filtres qui défilent ; M14 opacité des désactivés retirée ; M15 opacité
non forcée en couleurs forcées ; M16 mouvement réduit limité ; M17 retrait sans `capture` ; M18 message Bare Hands
« avec l'accord » ; M19 message de `app.py` sur l'onglet Mode vocal ; M20 Work Methods sans tête ; M21 Scène sans
primitives ; M22 `installVoiceSettingsSections()` non appelé (survivante contre le test du Memory Center, mauvais
choix de test, tuée par `test_settings_shell_browser`) ; M23 erreur de la scène gardée au remontage (Q7) ;
M24 `SET.data.scene` non posé par la réponse (Q8). Non testés : `block:'nearest'` (position), garde du bouton
« Annuler les changements » sur un brouillon vide (mutation équivalente).

### Preuves

Bac à sable `setui` (Core 127.77.0.1:27653, Control Center 127.0.0.1:27654, données et runtime au scratchpad `s10p`,
visualiseur coupé), vrais clics et frappes CDP : `evidence/s10-prep/` — 10 PNG quantifiés (0,72 Mo) et
`runtime-check.json`. Constats : arrivées marquées avec contour après lien à la souris (raccourci, diagnostic mémoire)
et après Ctrl+→ ; `#f_cli_model` avec contour ; focus sur « Enregistrer la mémoire » après l'envoi (un POST
`{"memory":{"recall":{"max_items":4}}}`) ; Scène et Work Methods avec tête de section ; Memory Center › « Ouvrir les
réglages mémoire » → `memory_knowledge`/`recall`, aucun `unknown_action` ; Labs sans filet en début de ligne à 1366 et
1093, liste sans défilement, filtres tous visibles, « Arrêter » 57 px ; contraste minimal 4,64 sur 29 éléments
désactivés ou en lecture seule ; mouvement réduit 0,01 ms ; couleurs forcées conformes ; aucune exception console.
PID lancés puis arrêtés un par un après vérification de la ligne de commande et du port, sans `/T` : 22060 (cerveau
claude, `--mcp-config` sous `scratchpad\s10p` ; ses 10 MCP partis avec lui, vérifié), 11224 (Control Center, 27654 ;
lanceur 37120 parti avec lui), 15048 (Core, 27653 ; lanceur 2924 parti avec lui). Core utilisateur 17653 (PID 31824) et
Control Center 17654 (PID 34676) intacts. Disque C : 58 à 60 Go libres.

### Décisions produit laissées au Human

- Prévenir à la fermeture des Réglages quand un brouillon mémoire non enregistré serait perdu.
- Garder le texte en cours des autres couches de l'atelier de prompts quand on en enregistre une.
- Renommer une clé de fournisseur (le magasin le permet ; non offert).
- Verdicts en clair de Solo Owner et de l'annulation d'écho, commande de réparation du vérificateur : leur rendu lisible
  (`authVerdictHtml`, `verifierHtml`…) n'était plus appelé sur main avant cette tâche ; Diagnostics les montre en JSON.
  Les remettre en clair serait une nouvelle fonctionnalité.

### Écarts et doutes

- Le premier test choisi pour M22 ne tuait pas la mutation (une attente `wait` vaine du harnais ne fait pas échouer un
  test à elle seule) : refait avec le bon test. Chaque nouveau test vérifie l'état par une évaluation, pas par une
  attente.
- La feuille de style du module Bare Hands n'est injectée que Bare Hands allumé : ses règles de section (espacements,
  contour des boutons radio) manquent quand il est éteint. Préexistant, non changé (le contour du shell couvre le focus).
- Commits séparés par hunks : seul l'état final et ses suites ont été testés.

## 2026-10-23 - Slice 10 (QA de livraison, accessibilité intégrée)

Seul writer de `setui` @ `c88a319a`. `git fetch` : `origin/main` = `20292e5c`, aucune dérive, aucun merge nécessaire.
Aucune correction de produit dans cette Slice (contrat : les findings retournent à leur Slice) ; ajoutés : deux tests
en échec attendu strict (findings), preuves, `HUMAN-CHECKS.md`, revue de `docs/settings/INDEX.md`.

### QA indépendante de la passe de finitions (`4602d3af..c88a319a`)

Verdict : **approuvée**, chaque correction tient, sauf le correctif S5 du Memory Center, incomplet (N1 ci-dessous).

- Aucun changement de route, de charge ni de persistance : aucune ligne du diff ne touche un `fetch`, une route
  `/api/*`, un corps de requête ni une clé `localStorage` ; `memory_settings.py` ne change que deux libellés,
  `barehands_commands.py` qu'un message ; aucune fonctionnalité nouvelle.
- `keepFocus` / `landFocus` (`control_center_settings_ui.js`) : sélecteur par `id` (échappé par `JSON.stringify`,
  forme CSS valide), sinon premier attribut `data-*` avec sa valeur ; un élément désactivé ne reprend pas le focus ;
  `landFocus` marque l'arrivée et la retire au `blur` (`once`). Utilisés par la mémoire (boutons en `aria-disabled`,
  `submit` et « Annuler » gardés par `dirty()`/`busy`), les rôles des sous-agents, Connexions (régions vivantes
  stables), `showSettingsTarget` et `focusSettingsLanding`. Corrects.
- Code mort de l'ancien onglet Voix : sur `4602d3af`, `authSectionHtml` et `aecHtml` n'avaient aucun appelant ;
  `renderField`, `catalog()`, `authVerdictHtml`, `authEffectiveHtml`, `verifierHtml`, `voiceSeen`, `whenOf`,
  `codeTag`, `AUTH_*`, `AEC_STATUS` n'étaient appelés que depuis ce groupe (grep sur `jarvis/`). Restent : les doubles
  de test qui les définissent (sans effet) et `#authRefresh`, bouton vivant de la partie Voix de Diagnostics.
- Sessions & Boards : `foreign()` ne vise que `[data-memory-center]`, posé par le Memory Center sur son seul hôte
  `#memoryCenterMount` ; les actions de la vue (dont `memory-delete-confirm` et `#wspConfirmRecursive`, dans l'arbre
  de la mémoire du Board, hors de cet hôte) passent toujours. Le Memory Center fait lui-même son `preventDefault` à
  l'envoi. `test_workspace_manager_browser` vert ; mutation Q2 (garde élargie à `.wsp`) tuée. Mais l'envoi de ses
  formulaires journalise encore `workspace.unknown_action` : N1.

### Tests (depuis `setui`, `.venv` du dépôt principal, au premier plan, chaque commande < 600 s ; sorties au scratchpad `s10/logs`)

- Suites Réglages hors navigateur (liste Slice 00 et ajouts des Slices) : lot A 209 passed ; lot B 179 passed ;
  lot C 277 passed ; lot D (+ canal Bare Hands, palette, settings_mcp) 302 passed.
- Navigateur, un ou deux fichiers par commande : settings_shell + jarvis_wheel 13 ; accessibilité + destinations
  des messages 11 ; advanced + agents_models 14 ; connections 10 ; memory 7 ; interface 14 ; wake_word 10 + 10 ;
  dossier_fullscreen 19 + 3 skipped ; tool_wheel + capture_wheel 35 + 1 skipped ; workspace_manager +
  dossier_navigation 3. Total 146 passed, 4 skipped, aucun échec ni intermittent. Après ajout des tests de findings :
  accessibilité 9 passed + 1 xfailed, memory 7 passed + 1 xfailed ; documents lus par des tests 92 + 36 passed.
- Balayage complet du dépôt (918 fichiers de `tests/` hors navigateur, 21 lots) : **23 230 passed, 13 failed,
  95 skipped**. Échecs : exactement les 12 préexistants de `20292e5c` (test_app tools_gateway, 6 ×
  test_control_center_mcp_api, 2 × barehands practice_frame, scene_group_drag, brain_capability_parity,
  tool_brain_choices) et l'intermittent `test_memory_context::…2000_notes…` (rejoué : un échec isolé de plus, puis
  5/5 ; sur un worktree jetable de `20292e5c`, 4/4 en 28-44 s contre 29-32 s sur `setui`, pour une borne de 30 s :
  lié au temps, non imputé).

### Mutations (worktree jetable `git worktree add --detach` de `c88a319a` au scratchpad, supprimé) : 2/8 tuées

Q2 garde du Memory Center élargie à toute la vue (tuée, workspace_manager) ; Q4 `keepFocus` sans effet (tuée,
accessibilité). Survivantes : Q1 garde `foreign(form)` de l'écoute `submit` retirée (a révélé N1 : le test ajouté
échoue sur le vrai code, d'où l'échec attendu) ; Q3 `data-settings-landed` jamais retiré (effet minime : la règle
exige `:focus`) ; Q5 `id` non échappé (équivalente pour les `id` du produit) ; Q6 `block:'nearest'` partout
(position non testée, cible toujours en vue) ; Q7 erreur de Connexions non collée en haut (rendu non testé) ; Q8
double gris d'un profil de routage éteint (aucun profil éteint dans le banc d'essai : voir N2).

### Bac à sable réel

`setui`, Core 127.77.0.1:27653, Control Center 127.0.0.1:27654, `JARVIS_DATA_ROOT`/`JARVIS_RUNTIME_DIR` au
scratchpad `s10`, visualiseur coupé, magasin de clés vide sous ce runtime (vérifié avant tout pilotage ; aucune clé
ajoutée, aucun POST pendant les parcours). Pilote CDP dérivé du harnais des tests (`evidence/s10/harness/`) : vrais
clics et frappes, zoom réel (largeur CSS = largeur / 1,25 et `deviceScaleFactor` 1,25), instrumentation injectée avant
la page. `evidence/s10/` : 29 PNG quantifiés (2,9 Mo) et `runtime-check.json`.

- Les 25 sections des six catégories, détails ouverts, à 1366×768, 1440×900 et 1920×1080, à 100 % et 125 % : page,
  colonne, contenu et liste des entrées sans débordement (0 px partout), aucune entrée coupée, aucun échec de
  montage. Seule la table du catalogue comparatif défile dans son propre conteneur (`.catalog-table-wrap`) à 1366 et
  1440 à 125 %.
- Clavier seul : depuis le début de la page, 1 Tab jusqu'à l'ancre de la roue, flèche droite, 4 flèches jusqu'à
  « Paramètres », flèche droite (six catégories dans l'ordre), flèches, Entrée → Connexions, focus sur la catégorie
  dans le rail, toujours là 900 ms après ; Échap → focus rendu à l'ancre ; JARVIS › « Réglages de la voix » au
  clavier → Voix & audio. Raccourci `s` depuis `body` → Réglages ouverts, focus sur Voix & audio ; Début + 3 flèches
  ne charge rien, Entrée ouvre Interface ; Tab → entrées, Fin + Entrée → Bare Hands ; « Réinitialiser les réglages »
  + Entrée → confirmation par-dessus les Réglages, focus sur « Annuler », Tab y reste ; Échap ferme la confirmation
  seule (Réglages ouverts, focus rendu au bouton), deux fois. Pied : Tab jusqu'à « Enregistrer », puis retour au
  rail ; « Fermer » → focus sur « Plus d'outils ». Le premier Tab parti sur `dockMore` (S03) n'est pas reproduit.
- Traversée Tab de chaque section depuis son entrée : contour visible sur chaque élément atteint, contrôles tous
  nommés (libellé, `aria-label` ou texte), sauf la sortie du shell de B1 dans 2 sections sur 25.
- Régions vivantes : `#modalStatus` (status, polite) partout ; régions propres de Connexions (`status` + `alert`),
  Raccourcis (`#shortcutHint`), catalogue, mémoire (avis), thème.
- Mouvement réduit : aucun élément animé ou en transition dans le shell (113 puis 343 nœuds), contre l'animation
  `set-fade` 0,18 s et les transitions du rail sans la préférence. Couleurs forcées : focus en `Highlight`, boutons
  désactivés de la mémoire en `GrayText` à opacité 1.
- Cycle de vie : `setInterval`, `setTimeout` ≥ 1 s, `addEventListener` sur `window` et `document`, `fetch`
  instrumentés ; trois tournées complètes des 25 sections puis fermeture : 6 intervalles (ceux de la page au repos,
  mêmes origines), même table d'écoutes globales qu'au repos, mêmes 3 longues requêtes en vol (commandes plein écran,
  explorateur du studio, patchs de la scène) ; aucune croissance d'une tournée à l'autre. Aucune fuite.
- Console : aucune exception ; seuls les 424 attendus de `/api/models` (pas de clé de fournisseur) et le 404 de
  `/favicon.ico`.
- PID lancés puis arrêtés un par un après vérification de la ligne de commande, sans `/T` : 38236 (cerveau claude,
  `--mcp-config` sous `scratchpad\s10\runtime` ; ses 10 MCP partis avec lui, vérifié), 23756 (Control Center, port
  27654 ; lanceur 3708 parti avec lui), 12644 (Core, port 27653 ; lanceur 15520 parti avec lui). Core utilisateur
  17653 (PID 31824) et Control Center 17654 (PID 34676) intacts. Données du bac à sable laissées en place. Disque C :
  60 Go libres au début, 56,8 Go avant le bac à sable.

### Findings

Bloquant :

- **B1 (Slice 02, piège de Tab du shell)** — `jarvis/runtime/control_center.html:6007-6008` : la liste des
  focusables du piège garde les contrôles d'un `<details>` fermé (`getClientRects().length>0` est vrai pour eux dans
  Chrome) ; le « dernier » est alors le bouton « Ajouter » caché de la dernière carte, pas le vrai dernier contrôle.
  Scénario : Réglages › Connexions › Fournisseurs, focus sur le dernier « Ajouter une clé », Tab → `body`, puis les
  Tab suivants parcourent la page derrière le shell `aria-modal` (ancre de la roue, `#boardsButton`,
  `#openTimeline`, `#agentsButton`, ERR, `#dockMore`, `#chatTab`) avant de revenir au rail. Vu aussi en bac à sable
  sur Agents & modèles › Rôles des sous-agents (rôles chargés : dernier contrôle = résumé « Afficher et modifier les
  instructions »). Contrat rompu : « Tab et Maj+Tab bouclent dans le shell … le focus ne part jamais derrière lui »
  (commentaire de l'écoute, même fichier) et docs/04 « No focus trap regressions ». Test :
  `tests/unit/test_settings_accessibility_browser.py::test_tab_from_the_last_reachable_control_stays_in_the_shell`
  (échec attendu strict, à retirer par la reprise).

Non bloquants :

- **N1 (Slice 05, correctif `2e124a60` incomplet)** — `control_center_workspace.js:1769-1770` : l'écoute `submit` de
  Sessions & Boards ignore les formulaires du Memory Center par `foreign(form)`, mais le Memory Center redessine son
  hôte dans sa propre écoute `submit` (`control_center_memory.js:361-366` → `runRecall` → `render()`, l. 128) : le
  formulaire est détaché quand l'événement arrive, `closest('[data-memory-center]')` rend `null`, et
  `workspace.unknown_action {"name":"recall"}` (de même `notes`) est encore journalisé. Aucun effet visible
  (avertissement au journal). Test :
  `tests/unit/test_memory_settings_browser.py::test_a_memory_center_form_sent_with_enter_is_not_a_workspace_action`
  (échec attendu strict).
- **N2 (Slice 02, contraste)** — `control_center.html:765` (`.settings-shell .routing-off{opacity:.7}`) : dans
  Avancé › Runtime & CLI › Configuration avancée, un profil désactivé grise ses aides (`.hint`) à 4,24:1, sous le
  4,5:1 visé par la passe de finitions (WCAG exempte les composants inactifs, pas ce texte d'explication). Le test de
  contraste n'a aucun profil éteint (mutation Q8 survivante).
- **N3 (préexistant, catalogue des tâches précédentes)** — `.catalog-table-wrap` (`control_center.html:997`) défile
  horizontalement à 1366 et 1440 à 125 % sans `tabindex`, rôle ni nom ; au clavier, seul le focus des boutons de la
  table la fait défiler.
- **N4 (tests)** — mutations survivantes Q3, Q6, Q7, Q8 ci-dessus (Q5 équivalente).

### Documentation

`docs/settings/INDEX.md` revu : liens tous valides (vérifiés), chaque document de `docs/settings/` indexé ; titre
historique « Agent / CLI settings backend » remplacé par un titre d'index, table « Documents des Réglages », liste des
suites navigateur, aides de focus `keepFocus`/`landFocus` ajoutées à la ligne des primitives. Contenu Agent / CLI
inchangé.

### Recette humaine

`HUMAN-CHECKS.md` : HV-SETTINGS-001 à 008 rédigés pour le Human, décisions produit à trancher (brouillon mémoire,
texte des autres couches de prompts, renommage de clé, verdicts Solo Owner / annulation d'écho et commande de
réparation du vérificateur), ligne de redémarrage.

### Redémarrage

Aucun schéma ni aucune persistance changés par la tâche (`git diff 20292e5c..HEAD` : rien sous `jarvis/adapters/` ni
`tests/schema/`, aucune `_MIGRATIONS`) : aucune migration. Le code servi change (page et onze modules Python de Core
et du Control Center) : redémarrage de JARVIS par le Human après le merge.

### Verdict de livraison

Validation machine **non épuisée** : B1 doit retourner à la Slice 02 ; après la reprise, rejouer
`test_settings_accessibility_browser.py` (l'échec attendu doit devenir un succès et être retiré) et la traversée Tab
du bac à sable. N1 à N4 peuvent partir avec la reprise ou en `Issues/`.

### Rework après QA de livraison (2026-10-23)

Commits : `a89dcf93` S2 (B1, N2, N3 et tests Q3/Q6/Q7/Q8), `0b297049` S5 (N1), `74392243` et `1c4bc3d6` S2 (tests du
piège de Tab durcis), puis ce commit S10 (preuves, `HUMAN-CHECKS.md`, LOG). Aucune route, charge, persistance ni
fonctionnalité nouvelle ; aucun schéma touché.

- **B1** — cause : le piège de Tab (`control_center.html`) prenait pour focusables tous les contrôles ayant des boîtes ;
  Chrome en donne au contenu d'un `<details>` fermé, d'où un « dernier » caché, un Tab non intercepté et la sortie du
  shell. Correctif : `settingsReachable(root)` ne garde que les contrôles réellement focusables et rendus (ni
  `:disabled`, ni `tabindex<0`, ni `type=hidden`, ni sous `[hidden]`/`[inert]`, ni dans le contenu d'un `<details>`
  fermé hors de son résumé direct, `checkVisibility` et `visibility`) ; dernier recours : un Tab laissé au navigateur
  qui finirait sur `body` ou derrière le shell (hors d'une autre boîte `aria-modal`) revient au bout du shell dans le
  sens de la frappe. Tests : `test_tab_from_the_last_reachable_control_stays_in_the_shell[providers|subagents]` (Tab
  depuis le vrai dernier → premier, Maj+Tab depuis le premier → vrai dernier, aucun `focusout` hors du shell même un
  instant ; échec attendu retiré), `test_the_trap_keeps_the_focus_in_the_shell_when_its_list_is_wrong`.
- **N1** — cause : le Memory Center redessine son hôte dans sa propre écoute `submit`/`click` ; quand l'événement
  arrive à Sessions & Boards la cible est détachée et `closest('[data-memory-center]')` rend `null`. Correctif :
  `foreign(event)` lit `event.composedPath()`, figé à l'envoi (clic et envoi). Test : Entrée dans Test de rappel puis
  dans la recherche des Notes, `/api/memory/recall-explain` et `/api/memory/search` appelés, aucun
  `workspace.unknown_action` (échec attendu retiré) ; `test_workspace_manager_browser` vert.
- **N2** — `.settings-shell .routing-off{opacity:1}` : le bloc d'un profil éteint n'est plus grisé (ni `.routing-off`
  hérité à 0,5, ni `[aria-disabled]` à 0,7) ; ses aides restent à pleine opacité, ses commandes désactivées sont grisées
  une seule fois (0,7). Test : `test_a_disabled_routing_profile_stays_readable_and_greyed_once` (profil éteint dans le
  brouillon, rien d'enregistré ; tout ≥ 4,5:1, opacité cumulée ≥ 0,7, aides à 1).
- **N3** — `.catalog-table-wrap` du catalogue (`control_center_catalog.js`) : `tabindex="0"`, `role="region"`,
  `aria-label` (le nom de la légende), contour `:focus-visible`. Les tables du Test Lab (même classe, hors Réglages)
  gardent leur balisage. Test : `test_the_scrolling_catalog_table_is_reachable_and_named` (1093×614, Tab depuis le
  contrôle précédent, contour, défilement).
- **N4** — Q3 : `test_the_landing_mark_is_removed_when_the_focus_leaves` ; Q6 :
  `test_a_part_reached_by_a_link_comes_to_the_top_of_the_content` ; Q7 :
  `test_a_connections_error_stays_at_the_top_while_scrolling` (refus simulé dans la page) ; Q8 : test N2 ; Q1 : test N1.

#### Mutations (worktree jetable `git worktree add --detach` de `74392243` au scratchpad, supprimé) : 11/12 tuées

Tuées : M1b liste sans `closedAround` ni `checkVisibility` (2 tests), M2 dernier recours retiré, M3/Q1 garde `submit`
retirée, M3b ancienne garde `closest`, M4/Q8 bloc éteint regrisé à 0,7, M5 ancienne règle (aides à 4,24:1), M6
`tabindex` du catalogue retiré, M7 contour du catalogue retiré, Q3 marque d'arrivée jamais retirée, Q6
`block:'nearest'` partout, Q7 erreur non collée. Survivante M1a (`closedAround` seul retiré) : équivalente dans Chrome,
où `checkVisibility` exclut déjà le contenu d'un `<details>` fermé (`content-visibility:hidden`) ; `closedAround`
reste comme garde pour un moteur sans `checkVisibility`.

#### Tests (depuis `setui`, `.venv` du dépôt principal, au premier plan, chaque commande < 600 s)

- Hors navigateur : lot A 209 passed ; lot B 179 passed ; lot C 277 passed ; lot D + settings_mcp + palette +
  workspace_manager_js + workspace_presentations_js 315 passed ; canal Bare Hands 35 passed.
- Navigateur : accessibilité 17 passed (fichier entier deux fois : 1 échec non identifié au premier passage, 17/17 au
  second ; moitiés 8 + 9 vertes ; le test des Rôles des sous-agents avait échoué une fois quand la lecture tardive des
  instances redessinait la liste après le marquage, corrigé par `1c4bc3d6`, puis 3 × 3 passes vertes) ; settings_shell +
  jarvis_wheel 13 ; advanced + agents_models 14 ; connections + destinations des messages 12 ; interface 14 ;
  wake_word 20 ; dossier_fullscreen 19 + 3 skipped ; tool_wheel + capture_wheel 35 + 1 skipped ; workspace_manager +
  dossier_navigation 3 ; memory 8. Aucun échec à la passe finale.

#### Bac à sable réel (B1 au clavier, N2, N3)

`setui`, Core 127.77.0.1:27653 (PID 7852 → 18412), Control Center 127.0.0.1:27654 (PID 6952 → 36616, cerveau claude
8516 dont `--mcp-config` sous `scratchpad\s10rw\runtime`), `JARVIS_DATA_ROOT`/`JARVIS_RUNTIME_DIR` au scratchpad
`s10rw`, visualiseur coupé ; pilote CDP `evidence/s10/harness/s10_driver.mjs`, plans `evidence/s10-rework/harness/`.
- 25 sections sur 25 : les bouts de `settingsReachable` sont ceux d'un calcul indépendant ; Tab depuis le vrai dernier →
  premier, Maj+Tab depuis le premier → vrai dernier, traversée complète jusqu'au rail, aucun `focusout` hors du shell.
  Quatre sections ont des contrôles cachés dans un `<details>` fermé (Voix › Sortie vocale 25, Rôles des sous-agents 5,
  Fournisseurs 24, Prompts 12) : toutes tiennent. `evidence/s10-rework/b1-keyboard.json`, captures
  `b1-providers-…`, `b1-subagents-…` (focus revenu sur la catégorie du rail).
- Profil éteint (brouillon seul) : bloc à 1, aides à 1, commandes désactivées à 0,7 ; catalogue à 1366×768 et 125 % :
  défile de 150 px, `role=region`, nommé, atteint par Tab, contour 2 px. `n2-n3-visual.json`, `n2-…png`, `n3-…png`.
- Aucune exception, aucun POST, console sans autre message que les 424 attendus de `/api/models` et le 404 du favicon.
- Arrêtés un par un après vérification de la ligne de commande, sans `/T` : 8516 (cerveau), 36616 (Control Center ; son
  lanceur 6952 parti avec lui), 18412 (Core ; lanceur 7852 parti avec lui). Core utilisateur 17653 (PID 31824) et
  Control Center 17654 (PID 34676) intacts. Données du bac à sable laissées en place. Disque C : 58 Go libres.

Verdict de la reprise : B1 et N1 à N4 corrigés ; validation machine à rejouer par une re-QA.
