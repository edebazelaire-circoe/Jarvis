# Réglages — alias des anciens onglets

**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 01. **État final :** Slice 09, complété par la
Slice 07 de `jarvis-architecture-agents-settings-editor` (alias `main_agent`, `subagent_models`).
**Contrat :** [`../settings/navigation-registry.md`](../settings/navigation-registry.md) § 3.

## Table finale (Slice 09)

L'ancien système d'onglets de premier niveau n'existe plus (`TABS`, `SET.tab`, `bindTab`, `canonicalSettingsTab`,
`legacyTabFor`, `navigationFromLegacyTabs`, `LEGACY_ANCHORS`, `#modalSub`, liens « encore dans » : retirés). La seule
compatibilité restante est la table explicite `LEGACY_TAB_ALIASES` de
`jarvis/runtime/control_center_settings_registry.js` ; aucune section ne déclare d'alias (le champ `aliases` de
`register` est refusé).

| Alias | Destination | Appelant du dépôt | Test |
| --- | --- | --- | --- |
| `memory` | `memory_knowledge` / `recall` | Memory Center › Réglages (`control_center_memory.js` : `root.selectTab('memory')`) | `test_every_remaining_alias_is_explicit_data_with_a_caller_and_its_declared_destination`, `test_memory_alias_opens_recall_and_every_memory_section` (node), `test_sections_destinations_alias_and_links` (vrai Chrome) |
| `main_agent` | `agents_models` / `architecture` | ce document (identifiant publié par la tâche settings-ui-reorganization) ; liens enregistrés hors du dépôt | `test_every_remaining_alias_is_explicit_data_with_a_caller_and_its_declared_destination`, `test_agent_sections_open_and_their_retired_ids_do_not` (node), `test_two_tabs_destinations_and_legacy_ids` (vrai Chrome) |
| `subagent_models` | `agents_models` / `subagents` | idem | idem |

### Alias de la Slice 07 de jarvis-architecture-agents-settings-editor

| Ancien ID | Statut | Ce que la section portait | Nouvelle destination | Raison |
| --- | --- | --- | --- | --- |
| `main_agent` | alias → `agents_models` / `architecture` | choix du CLI de Core et de son modèle ; version, clé et disponibilité du CLI | fenêtre du cerveau Core (clic droit ou « … » sur Core Brain, onglet Architecture) ; commande, chemin, permission et re-détection restent dans Avancé › Runtime & CLI | le cerveau Core se configure là où il est dessiné (D04, D13) |
| `subagent_models` | alias → `agents_models` / `subagents` | mode Auto / Dupliqué et inventaire comparatif des modèles | modèle de chaque rôle : onglet Sous-agents ; mode Auto / Dupliqué (compatibilité, il ne gouverne plus que les rôles qui héritent de leur profil) et inventaire : Avancé › Runtime & CLI | le choix d'un sous-agent est global par rôle (D16, D18) |

Aucun réglage n'est réécrit : `agent_cli`, `agent_cli_settings.<cli>.model`, `agent_routing.enabled`
(`delegation_mode`) et les profils restent les mêmes clés, écrites par les mêmes chemins (`PATCH
/api/brains/core/config` pour le CLI et le modèle de Core, `POST /api/settings` pour Runtime & CLI). Retirer ces alias :
quand plus aucun lien enregistré ni document ne publie ces identifiants ; supprimer alors les lignes de cette table,
celles de `LEGACY_TAB_ALIASES` et les entrées `ALIASES` / `ALIAS_CALLERS` de `test_control_center_settings_registry_js.py`.

Inventaire de la Slice 09 (grep du code, des tests et des documents durables) :

| Ancien ID | Avant la Slice 09 | Appelants trouvés | Décision |
| --- | --- | --- | --- |
| `voice` | alias de `conversation` | roue Jarvis, ligne « Réglages de la voix » (`openSettingsAt('voice')`) ; `docs/control-center-shell.md` | **retiré** : la roue ouvre `voice_audio` (`VOICE_SETTINGS_TARGET`), la doc suit |
| `wakeword` | alias de `wake_word` | aucun (tests seulement) | **retiré** |
| `prompts` | ID de la section `prompts` | tests | ce n'est pas un alias : l'ID de section reste |
| `cli` | alias de `main_agent` | aucun (tests ; fixture historique `agent-cli-ui.json`) | **retiré** |
| `routing` | alias de `runtime_cli` (ancienne redirection vers `cli`) | aucun (fixture historique) | **retiré** |
| `keys` | alias de `providers` | aucun (`docs/settings/connections.md` le décrivait seulement) | **retiré** |
| `shortcuts` | ID de la section `shortcuts` | tests | ce n'est pas un alias : l'ID de section reste |
| `memory` | alias de `recall` | Memory Center › Réglages | **gardé** |
| `subagents` | ID de la section `subagents` | tests | ce n'est pas un alias : l'ID de section reste |
| `appearance` | alias de `theme_scene` | aucun | **retiré** |
| `experimental` | alias de `scene_gate` | aucun (textes « onglet Expérimental » corrigés, voir LOG S09) | **retiré** |
| ancres `barehandsSettings`, `barehandsCalibration`, `barehandsRecord`, `barehandsBenchmarkSection` | `LEGACY_ANCHORS` → `bare_hands` / `barehands_lab` | aucun appel de `openSettingsTab` ; `JarvisBarehands.showSettings` passe par `SECTION_ENTRY` | **retirées** du registre |

Une cible inconnue (dont un ID retiré) se dit `settings_target_unknown` ; `openSettingsTab` ouvre alors la catégorie
par défaut (`DEFAULT_CATEGORY`, Voix & audio). Retirer `memory` : quand le Memory Center ouvre `recall` (ou
`memory_knowledge`) directement, supprimer la ligne de la table et l'entrée `ALIAS_CALLERS` du test.

## Historique (Slices 01-08)

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
  ([`../settings/architecture-agents.md`](../settings/architecture-agents.md), ex-`agents-models.md`). Testé : `test_agent_legacy_ids_open_their_sections`
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

- Slice 09 : retrait de l'ancien système d'onglets et des alias sans appelant ; table finale ci-dessus.

## Conditions de retrait (remplies à la Slice 09)

- Adaptateur, entrées `{kind:'tab'}` et liens `related` : retirés (toutes les catégories sont servies par des
  sections enregistrées depuis la Slice 08).
- Injecteurs : aucun (`test_no_legacy_tab_machinery_is_left_in_the_repository`).
- Alias : seul `memory` reste, tant que le Memory Center l'appelle (puis `main_agent` et `subagent_models` s'ajoutent à
  la Slice 07 de jarvis-architecture-agents-settings-editor, ci-dessus).
