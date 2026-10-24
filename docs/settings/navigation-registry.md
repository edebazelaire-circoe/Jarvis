# Réglages : navigation à six catégories et registre des sections

**Statut :** contrat canonique de la navigation des Réglages (niveau 3 : implémentation
réutilisable + tests de conformité).
**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 01.
**Remplace :** la partie `navigation` de
`tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json` (six onglets
d'implémentation). Les métadonnées d'options et de réglages de ce fichier restent valides. Depuis la Slice 09,
l'ancien système d'onglets (`TABS`, adaptateur `legacyTabFor`) n'existe plus : seule la table explicite des alias
(§ 3) en garde la compatibilité.

- Implémentation : `jarvis/runtime/control_center_settings_registry.js`
  (`window.JarvisSettingsRegistry`, `module.exports` pour node), inséré dans la page
  servie par `control_center.py` (`SETTINGS_REGISTRY_SCRIPT_FILE`/`_MARKER`) juste après
  `control_center_shell.js`, donc avant tout module de réglages et avant l'état des Réglages (`SET`).
- Conformité : `tests/unit/test_control_center_settings_registry_js.py`.
- Alias hérités encore servis et leurs appelants : [`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md).
- Shell qui dessine cette navigation (Slice 02) : [`settings-shell.md`](settings-shell.md).

## 1. Six catégories, et pas une de plus

| Ordre | ID stable | Libellé |
| --- | --- | --- |
| 1 | `voice_audio` | Personnalisation |
| 2 | `agents_models` | Architecture & Agents (exactement deux sections, ses deux onglets : `architecture`, `subagents`) |
| 3 | `memory_knowledge` | Mémoire & Connaissances |
| 4 | `interface_interactions` | Interface & Interactions |
| 5 | `connections` | Connexions |
| 6 | `advanced_diagnostics` | Avancé & Diagnostics |

- Les ID sont ASCII et stables ; les libellés et descriptions ne sont que de la présentation.
- `CATEGORIES`, `CATEGORY_IDS` et chaque catégorie sont gelés. Le registre n'a aucune
  fonction qui ajoute une catégorie : un module **enregistre une section**, il ne touche
  jamais la navigation de premier niveau.
- `cycleCategory(id, step)` donne la catégorie voisine dans cet ordre, en boucle (un ID
  inconnu part de la première ou de la dernière).
- `notice` (facultatif) : avis montré sous l'intro de la catégorie. Seule `advanced_diagnostics`
  en porte un (outils d'opérateur, Slice 08).

### Groupes déclarés (`CATEGORY_GROUPS`, Slice 08)

Une catégorie peut déclarer des groupes, gelés dans le registre comme les catégories. Seule
`advanced_diagnostics` en déclare, dans cet ordre d'affichage :

| Ordre | ID de groupe | Libellé | Sections (ordre) |
| --- | --- | --- | --- |
| 1 | `architecture_compat` | Architecture & compatibilité | `architecture_compat`, `memory_advanced` (Mémoire, refonte-ui-settings S05) |
| 2 | `prompts` | Prompts & instructions | `prompts` |
| 3 | `runtime_cli` | Runtime & CLI | `runtime_cli` |
| 4 | `diagnostics` | Diagnostics | `diagnostics` |
| 5 | `labs` | Labs & outils de test | `scene_gate`, `work_methods`, `barehands_lab` |

- Dans une catégorie qui déclare des groupes, chaque section **doit** porter un `group` parmi eux ;
  dans une autre, `group` est refusé (`settings_section_group`). L'appartenance est une donnée
  explicite de l'enregistrement, jamais déduite.
- `sections(id)` les ordonne par groupe (ordre de `CATEGORY_GROUPS`), puis `order`, puis ordre
  d'enregistrement. `R.groups(id)` rend les groupes d'une catégorie (liste vide sinon) ;
  `snapshot()` et `shellNavigation` les portent (`groups`), chaque entrée porte son `group`.
- Ce qui va dans chaque groupe : [`INDEX.md`](INDEX.md) § « Avancé & Diagnostics ».

## 2. Enregistrer une section

```js
const R = window.JarvisSettingsRegistry;
R.page.register({
  id: 'wake_word',              // requis, ^[a-z][a-z0-9_]{0,63}$, unique, jamais un ID de catégorie
  category: 'voice_audio',      // requis, une des six
  label: 'Mot d’éveil',         // requis
  description: '…',             // optionnel
  order: 50,                    // optionnel (0) ; à égalité, l'ordre d'enregistrement
  group: 'labs',                // requis dans une catégorie à groupes (Avancé & Diagnostics), refusé ailleurs
  mount(host, context) {},      // requis : dessine la section dans `host`
  destroy() {},                 // requis en pratique pour toute section à état (minuteurs, requêtes, écouteurs)
  save: 'self',                 // requis : 'footer' (bouton Enregistrer du shell) | 'self' (la section s'enregistre) | 'readonly'
  isDirty() { return false },   // optionnel ; interdit avec 'readonly'
  advanced: false,              // optionnel : badge « avancé »
  applies: 'next_voice_start',  // optionnel : 'immediate' | 'next_turn' | 'next_core_start' | 'next_voice_start'
});
```

- `R.page` est l'instance de la page ; `R.createRegistry()` en crée une isolée (tests).
- Une entrée enregistrée est gelée. Tout champ non listé est refusé.
- Le registre ne porte **aucune métadonnée de réglage** (plages, options, défauts) : elles
  restent décrites par le serveur (schéma Voix, `memory_settings.py`, métadonnées agent/CLI…).
- Le registre ne lit ni n'écrit aucun réglage : pas de réseau, pas de stockage, pas de DOM.

### Refus déterministes

`register` lève une `Error` (`name = 'SettingsRegistryError'`) portant un `code` stable ; le
même appel donne toujours le même code et le même message, et un refus n'enregistre rien.

| Code | Cas |
| --- | --- |
| `settings_category_unknown` | catégorie absente ou hors des six (aussi `sections(id)` sur une catégorie inconnue) |
| `settings_section_duplicate` | ID déjà enregistré |
| `settings_section_invalid` | description non objet, champ inconnu (dont `aliases` depuis la Slice 09), ID mal formé ou égal à une catégorie, libellé vide, `mount` absent, `save` hors politique, `isDirty` sur `readonly`, `applies` inconnu |
| `settings_alias_conflict` | ID de section égal à un alias hérité de `LEGACY_TAB_ALIASES` (il masquerait l'alias) |
| `settings_section_group` | `group` absent ou non déclaré dans une catégorie à groupes, ou `group` dans une catégorie sans groupes |

L'appelant (le shell) attrape le refus, le journalise avec son code et l'affiche : une
section refusée ne disparaît jamais en silence.

### Résoudre une cible

`registry.resolve(target)` → `{category, section, source}` ou `null` :

| `source` | Cible |
| --- | --- |
| `category` | un ID de catégorie (`section: null` = page d'accueil de la catégorie) |
| `section` | un ID de section enregistrée |
| `alias` | un alias hérité de `LEGACY_TAB_ALIASES` (§ 3) |

Pour un alias dont la section cible n'est pas enregistrée, `section` vaut `null` : la catégorie s'ouvre, aucune
section n'est devinée. Une cible inconnue (dont un ancien ID retiré à la Slice 09) rend `null` et l'appelant le
signale (`settings_target_unknown`) ; `openSettingsTab` ouvre alors la catégorie par défaut `DEFAULT_CATEGORY`
(`voice_audio`, la première).

## 3. Alias hérités (`LEGACY_TAB_ALIASES`, Slice 09)

Une table gelée du registre, seule source des alias : aucune section ne déclare d'alias, aucune condition n'en devine.
Un alias n'y reste que tant qu'un appelant du dépôt ou un document durable s'en sert (`docs/02-architecture.md` § 6 de
la tâche) ; chaque alias restant est testé (`test_every_remaining_alias_is_explicit_data_with_a_caller_and_its_declared_destination`,
qui exige aussi l'appelant).

| Alias | Destination | Appelant qui le garde |
| --- | --- | --- |
| `memory` | `memory_knowledge` / `recall` | bouton Réglages du Memory Center (`control_center_memory.js`, `selectTab('memory')`) |
| `main_agent` | `agents_models` / `architecture` | [`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md) (section retirée par la Slice 07 de jarvis-architecture-agents-settings-editor : CLI et modèle de Core dans la fenêtre du cerveau) |
| `subagent_models` | `agents_models` / `subagents` | idem (modèle de chaque rôle dans l'onglet Sous-agents ; mode Auto / Dupliqué et inventaire dans Runtime & CLI) |

Retirés à la Slice 09 (aucun appelant ni document durable) : `voice` (la roue ouvre désormais `voice_audio`),
`wakeword`, `cli`, `routing` (et sa redirection historique vers `cli`), `keys`, `appearance`, `experimental`, et
les ancres Bare Hands `barehandsSettings`, `barehandsCalibration`, `barehandsRecord`, `barehandsBenchmarkSection`
(`LEGACY_ANCHORS` ; `JarvisBarehands.showSettings` passe par sa propre table `SECTION_ENTRY`). `prompts`, `shortcuts`
et `subagents` ne sont pas des alias : ce sont les ID mêmes de leurs sections. La table historique complète (avec les
destinations `also` du contenu éclaté) est dans [`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md).

Sections enregistrées (Slices 03 à 08 ; hub du 2026-10-23 : `theme_scene` et `agent_behavior` passés dans
Personnalisation, `mcp_plugins` ajouté) :
`voice_audio` : `theme_scene`, `agent_behavior`, `conversation`, `voice_output`, `microphone_sound`, `turns_interruptions`, `wake_word` ·
`agents_models` : `architecture`, `subagents` (Slice 07 de jarvis-architecture-agents-settings-editor ; un onglet interne = une section, [`architecture-agents.md`](architecture-agents.md) § 1) ·
`memory_knowledge` : `recall` (onglet Mémoire), `knowledge_sources` (Connaissances), `memory_center` (refonte-ui-settings S05/S06 ; `semantic_retrieval` et `consolidation` sont devenus des alias de `recall`) ·
`interface_interactions` : `shortcuts`, `bare_hands` ·
`connections` : `mcp_plugins`, `providers` ·
`advanced_diagnostics` (groupes déclarés, § 1) : `architecture_compat`, `memory_advanced`, `prompts`, `runtime_cli`, `diagnostics`,
`scene_gate`, `work_methods`, `barehands_lab`.

## 4. Cas particuliers relevés par l'audit

- **`experimental` partagé.** Jusqu'à la Slice 06, Bare Hands créait l'onglet et
  `control_center_scene_settings.js` y ajoutait la porte de test de la scène. Depuis la Slice 06, Bare Hands enregistre
  `bare_hands` (Interface), `barehands_lab` (Avancé, groupe `labs`) et la partie de diagnostic `barehands` ; depuis la
  Slice 08, la porte de test est la section `scene_gate` (groupe `labs`) ; depuis la Slice 09, `experimental` n'est
  plus un alias.
- **`ui_tab_next` / `ui_tab_prev`.** Depuis la Slice 02, ils parcourent les six catégories par
  `cycleCategory`, jamais les sections ni les anciens onglets.
- **Roue Jarvis** (`control_center_jarvis_wheel.js`). Elle lit `settingsTabs()` (les six catégories,
  `{id, label, description}`) et ouvre `openSettingsTab(id)` ; la ligne « Réglages de la voix » ouvre `voice_audio`
  (`VOICE_SETTINGS_TARGET`, Slice 09 ; c'était l'alias `voice` avant).
- **Pied de page.** `save: 'footer'` montre le bouton Enregistrer du shell ; `self` et `readonly` le cachent, une
  catégorie vide aussi.
- **Nettoyage.** Le shell appelle `destroy` de la section quittée avant d'en monter une autre ;
  `cleanupSettingsSurface()` reste le point d'appel pendant la migration.

## 5. Adaptateur des onglets hérités (Slices 01-08, retiré à la Slice 09)

De la Slice 01 à la Slice 08, `legacyTabFor`, `navigationFromLegacyTabs` et `canonicalSettingsTab` rangeaient les
onglets du `TABS` de la page sous les six catégories pendant que chaque catégorie recevait ses sections (Slice 03 :
Voix et Mot d'éveil ; 04 : Agent / CLI et Sous-agents ; 05 : Mémoire ; 06 : Raccourcis, Apparence, Bare Hands ;
07 : API Keys ; 08 : Prompts et Expérimental). À la Slice 09, `TABS` était vide : l'adaptateur, `TABS`, `SET.tab`,
`bindTab`, `#modalSub`, les liens « encore dans » (`related`, `#settingsRelated`) et l'alerte `settings_tab_unassigned`
ont été retirés. `test_no_legacy_tab_machinery_is_left_in_the_repository` empêche leur retour (aucun
`TABS.push`/`splice` dans le dépôt). Détail par Slice : `tasks/jarvis-settings-ui-reorganization/LOG.md`.

## 6. Navigation du shell (Slice 02, simplifiée à la Slice 09)

- `shellNavigation(registry)` → `{categories:[{id, label, description, notice, groups, items}]}` : `items` = sections
  enregistrées, dans l'ordre du registre (`{kind:'section', id, label, save, advanced, group}`).
  `settingsNavigation()` de la page la rend.
- `shellTarget(cible, nav, registry)` → `{category, item}` ou `null` : catégorie seule (`item: null`) ; section
  enregistrée (par son ID ou un alias de § 3) ; la catégorie seule d'un alias dont la section n'est pas enregistrée ;
  `null` pour une cible inconnue.
- Le shell, son clavier, son focus et la façon de monter une section : [`settings-shell.md`](settings-shell.md).
