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
- Les injecteurs `TABS.push/splice` de `control_center_wake_word.js`,
  `control_center_work.js` et `control_center_barehands.js` (liste figée par
  `test_no_module_injects_a_new_top_level_tab`).

## Conditions de retrait

- Adaptateur, entrées `{kind:'tab'}` et liens `related` : quand toutes les catégories sont
  servies par des sections enregistrées (fin des Slices 03-08) ; `settingsNavigation()` et
  `shellNavigation` restent, sans onglets hérités.
- Injecteurs : à la Slice 09, quand chaque module enregistre ses sections.
- Alias : quand plus aucun appelant du dépôt (roue Jarvis `'voice'`, Bare Hands
  `showSettings`, Memory Center `selectTab('memory')`, Sous-agents `openTab('cli')`) ni
  document durable ne cite un ancien ID (Slice 09).
