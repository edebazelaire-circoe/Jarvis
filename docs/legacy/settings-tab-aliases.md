# Réglages — alias des anciens onglets et onglets hérités montés dans le shell

**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 01.
**Contrat :** [`../settings/navigation-registry.md`](../settings/navigation-registry.md) § 3 et § 5.

## Ce qui est temporaire

- `LEGACY_TAB_ALIASES` et `LEGACY_ANCHORS` dans
  `jarvis/runtime/control_center_settings_registry.js` : les anciens ID d'onglets
  (`voice`, `wakeword`, `prompts`, `cli`, `routing`, `keys`, `shortcuts`, `memory`,
  `subagents`, `appearance`, `experimental`) et les ancres Bare Hands, vers leur
  catégorie/section cible.
- L'adaptateur `legacyTabFor` / `navigationFromLegacyTabs` : il range le `TABS` actuel sous
  les six catégories.
- Les onglets hérités montés comme sections temporaires du shell à six catégories (Slice 02 :
  entrées `{kind:'tab'}` de `shellNavigation`, rendues par `renderTab` et les modules
  injectés), et les liens `related` vers les onglets d'autres catégories
  ([`../settings/settings-shell.md`](../settings/settings-shell.md)).
- Plus aucun injecteur `TABS.push/splice` (liste vide figée par `test_no_module_injects_a_new_top_level_tab`) :
  `control_center_wake_word.js` en est sorti à la Slice 03, `control_center_work.js` et
  `control_center_barehands.js` à la Slice 06.
- Slice 03 : les onglets `voice` et `wakeword` n'existent plus ; leurs ID restent des alias
  (`voice` → `voice_audio` / `conversation`, déclaré par la section ; `wakeword` → `wake_word`).
  Le renvoi de l'onglet Raccourcis vers Voix pour `wake_toggle` est supprimé : Raccourcis en est
  l'unique éditeur ([`../settings/voice-audio.md`](../settings/voice-audio.md) § 3).
- Slice 04 : les onglets `cli` et `subagents` n'existent plus ; leurs ID restent des alias (`cli` → `agents_models` /
  `main_agent`, déclaré par la section ; `routing` → `advanced_diagnostics` / `runtime_cli`, déclaré par la section ;
  `subagents` = l'ID de la section des rôles). Le renvoi du module des sous-agents vers `cli` est remplacé par
  `subagent_models`. `canonicalSettingsTab` et la redirection `routing` → `tab:'cli'` ne servent plus à la page
  (seulement aux extraits de tests) : retrait à la Slice 09
  ([`../settings/agents-models.md`](../settings/agents-models.md)). Testé : `test_agent_legacy_ids_open_their_sections`
  (registre), `test_category_sections_destinations_and_legacy_ids` (vrai Chrome).
- Slice 05 : l'onglet `memory` n'existe plus ; son ID reste l'alias de la section `recall` (`memory_knowledge`,
  déclaré par la section : `aliases:['memory']`). Appelant connu : le bouton Réglages du Memory Center
  (`selectTab('memory')`). Le détail des étages va dans la partie Mémoire de `advanced_diagnostics` / `diagnostics`
  ([`../settings/memory.md`](../settings/memory.md)). Testé : `test_memory_legacy_id_opens_recall_and_every_memory_section`
  (registre), `test_sections_destinations_alias_and_links` (vrai Chrome).

- Slice 06 : les onglets `appearance` et `shortcuts` n'existent plus ; `appearance` est l'alias de la section
  `theme_scene` (déclaré par la section), `shortcuts` est l'ID de la section des raccourcis. Bare Hands n'injecte plus
  `experimental` : ses ancres (`barehandsSettings`, `barehandsCalibration` → `bare_hands` ; `barehandsRecord`,
  `barehandsBenchmarkSection` → `barehands_lab`) ouvrent ses sections. L'onglet `experimental` reste, déclaré par la
  page, pour la seule porte de test de la scène, jusqu'à la Slice 08 ; son alias (→ Labs) reste.
  ([`../settings/interface-interactions.md`](../settings/interface-interactions.md)). Testé :
  `test_sections_aliases_single_wake_editor_and_barehands_split` (vrai Chrome),
  `test_page_routes_categories_sections_and_legacy_ids_into_the_six_category_shell` (registre).

- Slice 07 : l'onglet `keys` (« API Keys ») n'existe plus ; son ID est l'alias de la section `providers` de
  `connections` (déclaré par la section : `aliases:['keys']`). `TABS` = `prompts`, `experimental` (Slice 08).
  Appelants du dépôt : aucun par l'ancien ID (les liens de la Mémoire et d'Agent principal visent `providers`)
  ([`../settings/connections.md`](../settings/connections.md)). Testé :
  `test_page_routes_categories_sections_and_legacy_ids_into_the_six_category_shell` (registre),
  `test_category_cards_alias_environment_fallback_and_links` (vrai Chrome).

- Slice 08 : les onglets `prompts` et `experimental` n'existent plus ; **`TABS` est vide**, plus aucun onglet de
  premier niveau. `prompts` est l'ID de la section Prompts d'Avancé (groupe `prompts`) ; `experimental` est l'alias de
  la section `scene_gate` (Scène constellation, groupe `labs`, déclaré par `control_center_scene_settings.js` :
  `aliases:['experimental']`, cible de `LEGACY_TAB_ALIASES.experimental`). Le module de la scène n'enveloppe plus
  `renderTab`. Restent pour la Slice 09 : `TABS` (vide), la branche onglet de `renderTab`, `bindTab` (plus appelé
  qu'avec un onglet), `canonicalSettingsTab`, `routing.tab:'cli'`, `legacyTabFor` et l'ancre → `experimental` de
  l'adaptateur. Testé : `test_page_routes_categories_sections_and_legacy_ids_into_the_six_category_shell` (registre),
  `test_five_declared_groups_notice_every_section_and_diagnostic_reachable` (vrai Chrome).

## Conditions de retrait

- Adaptateur, entrées `{kind:'tab'}` et liens `related` : quand toutes les catégories sont
  servies par des sections enregistrées (fin des Slices 03-08) ; `settingsNavigation()` et
  `shellNavigation` restent, sans onglets hérités.
- Injecteurs : à la Slice 09, quand chaque module enregistre ses sections.
- Alias : quand plus aucun appelant du dépôt (roue Jarvis `'voice'`, Bare Hands
  `showSettings`, Memory Center `selectTab('memory')`) ni
  document durable ne cite un ancien ID (Slice 09).
