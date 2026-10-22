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
