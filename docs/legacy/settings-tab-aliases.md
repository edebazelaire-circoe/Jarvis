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
- Les injecteurs `TABS.push/splice` de `control_center_work.js` et
  `control_center_barehands.js` (liste figée par `test_no_module_injects_a_new_top_level_tab`).
  `control_center_wake_word.js` en est sorti à la Slice 03 : il enregistre la section `wake_word`.
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

## Conditions de retrait

- Adaptateur, entrées `{kind:'tab'}` et liens `related` : quand toutes les catégories sont
  servies par des sections enregistrées (fin des Slices 03-08) ; `settingsNavigation()` et
  `shellNavigation` restent, sans onglets hérités.
- Injecteurs : à la Slice 09, quand chaque module enregistre ses sections.
- Alias : quand plus aucun appelant du dépôt (roue Jarvis `'voice'`, Bare Hands
  `showSettings`, Memory Center `selectTab('memory')`) ni
  document durable ne cite un ancien ID (Slice 09).
