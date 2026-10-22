# Réglages : navigation à six catégories et registre des sections

**Statut :** contrat canonique de la navigation des Réglages (niveau 3 : implémentation
réutilisable + tests de conformité).
**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 01.
**Remplace :** la partie `navigation` de
`tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json` (six onglets
d'implémentation). Les métadonnées d'options et de réglages de ce fichier restent valides.

- Implémentation : `jarvis/runtime/control_center_settings_registry.js`
  (`window.JarvisSettingsRegistry`, `module.exports` pour node), inséré dans la page
  servie par `control_center.py` (`SETTINGS_REGISTRY_SCRIPT_FILE`/`_MARKER`) juste après
  `control_center_shell.js`, donc avant tout module de réglages et avant `TABS`.
- Conformité : `tests/unit/test_control_center_settings_registry_js.py`.
- Compatibilité temporaire : [`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md).
- Shell qui dessine cette navigation (Slice 02) : [`settings-shell.md`](settings-shell.md).

## 1. Six catégories, et pas une de plus

| Ordre | ID stable | Libellé |
| --- | --- | --- |
| 1 | `voice_audio` | Voix & audio |
| 2 | `agents_models` | Agents & modèles |
| 3 | `memory_knowledge` | Mémoire & connaissances |
| 4 | `interface_interactions` | Interface & interactions |
| 5 | `connections` | Connexions |
| 6 | `advanced_diagnostics` | Avancé & diagnostic |

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
| 1 | `architecture_compat` | Architecture & compatibilité | `architecture_compat` |
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
- Ce qui va dans chaque groupe : [`INDEX.md`](INDEX.md) § « Avancé & diagnostic ».

## 2. Enregistrer une section

```js
const R = window.JarvisSettingsRegistry;
R.page.register({
  id: 'wake_word',              // requis, ^[a-z][a-z0-9_]{0,63}$, unique, jamais un ID de catégorie
  category: 'voice_audio',      // requis, une des six
  label: 'Mot d’éveil',         // requis
  description: '…',             // optionnel
  order: 50,                    // optionnel (0) ; à égalité, l'ordre d'enregistrement
  group: 'labs',                // requis dans une catégorie à groupes (Avancé & diagnostic), refusé ailleurs
  mount(host, context) {},      // requis : dessine la section dans `host`
  destroy() {},                 // requis en pratique pour toute section à état (minuteurs, requêtes, écouteurs)
  save: 'self',                 // requis : 'footer' (bouton Enregistrer du shell) | 'self' (la section s'enregistre) | 'readonly'
  isDirty() { return false },   // optionnel ; interdit avec 'readonly'
  advanced: false,              // optionnel : badge « avancé »
  applies: 'next_voice_start',  // optionnel : 'immediate' | 'next_turn' | 'next_core_start' | 'next_voice_start'
  aliases: ['wakeword'],        // optionnel : anciens ID qui doivent ouvrir cette section
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
| `settings_section_duplicate` | ID déjà enregistré, ou déjà pris comme alias |
| `settings_section_invalid` | description non objet, champ inconnu, ID mal formé ou égal à une catégorie, libellé vide, `mount` absent, `save` hors politique, `isDirty` sur `readonly`, `applies` inconnu, `aliases` mal formé |
| `settings_alias_conflict` | alias égal à un ID canonique, déjà porté par une autre section, ou contraire à `LEGACY_TAB_ALIASES` |
| `settings_section_group` | `group` absent ou non déclaré dans une catégorie à groupes, ou `group` dans une catégorie sans groupes |

L'appelant (le shell) attrape le refus, le journalise avec son code et l'affiche : une
section refusée ne disparaît jamais en silence.

### Résoudre une cible

`registry.resolve(target)` → `{category, section, source}` ou `null` :

| `source` | Cible |
| --- | --- |
| `category` | un ID de catégorie (`section: null` = page d'accueil de la catégorie) |
| `section` | un ID de section enregistrée |
| `section_alias` | un alias déclaré par une section |
| `legacy_tab` | un ID d'onglet hérité (§ 3) |
| `legacy_anchor` | une ancre interne héritée (`LEGACY_ANCHORS`, Bare Hands) |

Pour un alias hérité dont la section cible n'est pas encore enregistrée, `section` vaut
`null` : la catégorie s'ouvre, aucune section n'est devinée. Une cible inconnue rend `null`
et l'appelant le signale (`settings_target_unknown`).

## 3. Table des ID hérités (`LEGACY_TAB_ALIASES`)

Destination principale de chaque ID d'onglet actuel, plus les autres destinations du contenu
éclaté (`also`), d'après `tasks/jarvis-settings-ui-reorganization/docs/07-target-settings-map.md`.

| ID hérité | Destination principale | Autres destinations (`also`) |
| --- | --- | --- |
| `voice` | `voice_audio` / `conversation` | `voice_audio` / `voice_output`, `microphone_sound`, `turns_interruptions` ; `advanced_diagnostics` / `architecture_compat`, `diagnostics` |
| `wakeword` | `voice_audio` / `wake_word` | `advanced_diagnostics` / `diagnostics` |
| `prompts` | `advanced_diagnostics` / `prompts` (section enregistrée depuis la Slice 08, ID = ancien ID) | — |
| `cli` | `agents_models` / `main_agent` | `agents_models` / `agent_behavior`, `subagent_models` ; `advanced_diagnostics` / `runtime_cli` |
| `routing` (déjà redirigé vers `cli`) | `advanced_diagnostics` / `runtime_cli` | — |
| `keys` | `connections` / `providers` (section enregistrée depuis la Slice 07, [`connections.md`](connections.md)) | — |
| `shortcuts` | `interface_interactions` / `shortcuts` | — |
| `memory` | `memory_knowledge` / `recall` | `memory_knowledge` / `semantic_retrieval`, `consolidation`, `knowledge_sources`, `memory_center` ; `advanced_diagnostics` / `diagnostics` |
| `subagents` | `agents_models` / `subagents` | `advanced_diagnostics` / `work_methods` (promotion de Work Methods, groupe `labs`) |
| `appearance` | `interface_interactions` / `theme_scene` | — |
| `experimental` | `advanced_diagnostics` / `scene_gate` (section Scène constellation depuis la Slice 08, alias déclaré) | `interface_interactions` / `bare_hands` ; `advanced_diagnostics` / `barehands_lab` |

Ancres Bare Hands (`LEGACY_ANCHORS`, clés de `SECTION` dans `control_center_barehands.js`,
utilisées par `JarvisBarehands.showSettings(section)`) : `barehandsSettings` et
`barehandsCalibration` → `interface_interactions` / `bare_hands` ; `barehandsRecord` et
`barehandsBenchmarkSection` → `advanced_diagnostics` / `barehands_lab` (Slice 06).

Une destination `also` déjà enregistrée comme section dans une catégorie n'y fait plus apparaître de lien « encore
dans » vers l'onglet hérité (Slice 06 : Interface ne renvoie plus vers Expérimental).

Sections cibles prévues (enregistrées par les Slices 03 à 08) :
`voice_audio` : `conversation`, `voice_output`, `microphone_sound`, `turns_interruptions`, `wake_word` ·
`agents_models` : `main_agent`, `agent_behavior`, `subagent_models`, `subagents` ·
`memory_knowledge` : `recall`, `semantic_retrieval`, `consolidation`, `knowledge_sources`, `memory_center` ·
`interface_interactions` : `theme_scene`, `shortcuts`, `bare_hands` ·
`connections` : `providers` ·
`advanced_diagnostics` (groupes déclarés, § 1) : `architecture_compat`, `prompts`, `runtime_cli`, `diagnostics`,
`scene_gate`, `work_methods`, `barehands_lab` (Slice 06 : [`interface-interactions.md`](interface-interactions.md)).
Toutes sont enregistrées depuis la Slice 08 : plus aucun onglet hérité ne sert une section cible.

## 4. Cas particuliers relevés par l'audit

- **`experimental` partagé.** Jusqu'à la Slice 06, Bare Hands créait l'onglet et
  `control_center_scene_settings.js` y ajoutait la porte de test de la scène. Depuis la Slice 06,
  Bare Hands enregistre `bare_hands` (Interface), `barehands_lab` (Avancé, groupe `labs`) et la
  partie de diagnostic `barehands`. Depuis la Slice 08, `control_center_scene_settings.js` enregistre
  la section `scene_gate` (groupe `labs`, alias `experimental`) et ne dépend plus d'aucun onglet ;
  l'ID a disparu de `TABS`.
- **`ui_tab_next` / `ui_tab_prev`.** Depuis la Slice 02, ils parcourent les six catégories par
  `cycleCategory`, jamais les sections ni les anciens onglets.
- **Roue Jarvis** (`control_center_jarvis_wheel.js`). Elle lit `settingsTabs()` et ouvre
  `openSettingsTab(id)`. Dès la Slice 01, `openSettingsTab` accepte un ID d'onglet, une
  redirection, une catégorie ou une section cible. Depuis la Slice 02, `settingsTabs()` rend
  les six catégories (`{id, label, description}`) ; la ligne « Réglages de la voix » (`'voice'`)
  reste servie par l'alias, qui ouvre `voice_audio` / `conversation` depuis la Slice 03 (passage à
  `voice_audio` dans la roue : Slice 09).
- **Pied de page.** `save: 'footer'` montre le bouton Enregistrer du shell ; `self` et
  `readonly` le cachent (plus aucun onglet hérité depuis la Slice 08 ; `TABS[].save` reste lu par
  la machinerie retirée à la Slice 09).
- **Nettoyage.** Le shell appelle `destroy` de la section quittée avant d'en monter une autre ;
  `cleanupSettingsSurface()` reste le point d'appel pendant la migration.

## 5. Adaptateur des onglets hérités (migration, Slices 01-09)

Depuis la Slice 08, `TABS` est vide : l'adaptateur ne sert plus aucun onglet réel ; ses règles
restent testées sur des fixtures historiques jusqu'à son retrait (Slice 09). Il dit :

- `legacyTabFor(target, TABS)` : l'onglet lui-même ; sa redirection (`routing` → `cli`) ;
  pour une catégorie, son premier onglet dans l'ordre de `TABS` ; pour une section cible,
  l'onglet dont c'est la destination principale, sinon celui qui en porte une partie
  (`also`, qui couvre toutes les sections cibles prévues depuis la QA de la Slice 01) ;
  `null` sinon. `canonicalSettingsTab` s'en sert : un ID d'onglet actuel donne exactement
  le même onglet qu'avant.
- `navigationFromLegacyTabs(TABS)` → `{categories:[{id,label,tabs}], unassigned}` : les
  onglets actuels rangés sous les six catégories (destination principale).
- `test_no_module_injects_a_new_top_level_tab` fige la liste des modules qui font encore
  `TABS.push/splice` (`control_center_work.js`, `control_center_barehands.js`) : tout nouveau
  module doit enregistrer une section.
- Slice 03 : `voice_audio` n'a plus d'onglet hérité. Sections enregistrées : `conversation`,
  `voice_output`, `microphone_sound`, `turns_interruptions` (page), `wake_word`
  (`control_center_wake_word.js`), et sous `advanced_diagnostics` : `architecture_compat`,
  `diagnostics` (page ; Diagnostics est fait de parties, `registerSettingsDiagnostic`).
  Destinations des options Voix : [`voice-audio.md`](voice-audio.md).
- Slice 04 : ni `cli` ni `subagents` ne sont des onglets. Sections enregistrées (page) : `main_agent` (alias `cli`),
  `agent_behavior`, `subagent_models`, `subagents`, et sous `advanced_diagnostics` : `runtime_cli` (alias `routing`,
  groupe `runtime_cli`), `work_methods` (groupe `labs`). Destinations : [`agents-models.md`](agents-models.md).
- Slice 05 : `memory` n'est plus un onglet. Sections enregistrées (page) : `recall` (alias `memory`),
  `semantic_retrieval`, `consolidation`, `knowledge_sources` (`save:'self'`), `memory_center` (`readonly`), et la partie
  Mémoire de `advanced_diagnostics` / `diagnostics`. Destinations des champs servies par le serveur (`surface`) :
  [`memory.md`](memory.md).
- Slice 08 : ni `prompts` ni `experimental` ne sont des onglets ; `TABS` est vide. Sections enregistrées :
  `prompts` (page, `PROMPTS_SECTION`, groupe `prompts`) et `scene_gate` (`control_center_scene_settings.js`,
  groupe `labs`, alias `experimental`). Groupes déclarés : § 1.

## 6. Navigation du shell (Slice 02)

- `shellNavigation(TABS, registry)` → `{categories:[{id, label, description, notice, groups, items, related}], unassigned}` :
  `items` = sections enregistrées (ordre du registre, `{kind:'section', id, label, save, advanced, group}`), puis
  onglets hérités de la catégorie (`{kind:'tab', id, label}`) qu'aucune section ne déclare en alias ;
  `related` = onglets d'autres catégories qui portent encore une partie de celle-ci (`also`), montrés comme
  liens ; un onglet sans alias (`unassigned`) est rangé dans `advanced_diagnostics` pour rester atteignable
  et journalisé une fois (`settings_tab_unassigned`). `settingsNavigation()` de la page la rend.
- `shellTarget(cible, nav, registry, TABS)` → `{category, item}` ou `null` : catégorie seule (`item: null`) ;
  onglet hérité encore dans la navigation ; section enregistrée (ID, alias, ou destination d'un ancien ID) ;
  onglet qui sert une section cible ; sinon la catégorie seule d'un alias connu.
- Le shell, son clavier, son focus et la façon de monter une section : [`settings-shell.md`](settings-shell.md).
