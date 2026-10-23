# Réglages : Architecture & Agents et ses destinations

**Statut :** contrat de surface (niveau 3 : sections enregistrées, routes montées, tests de conformité et navigateur).
**Introduit :** tâche `jarvis-architecture-agents-settings-editor`, Slice 07, qui **remplace** la Slice 04
(« Agents & modèles ») de `jarvis-settings-ui-reorganization` ; l'ancien contrat de cette page s'appelait
`agents-models.md`.
**S'appuie sur :** [`navigation-registry.md`](navigation-registry.md) (catégories, sections, alias),
[`settings-shell.md`](settings-shell.md) (montage d'une section, clavier), [`architecture-tab.md`](architecture-tab.md)
(canevas), [`brain-config-panel.md`](brain-config-panel.md) (fenêtre d'un cerveau), [`../architecture-graph.md`](../architecture-graph.md)
et [`../brain-config.md`](../brain-config.md) (contrats serveur), [`../subagent-roles.md`](../subagent-roles.md) § 8 et § 10
(onglet Sous-agents, routage par rôle), [`../work-methods.md`](../work-methods.md) (promotion).

Règle produit : **le graphe décide de ce qui peut parler à quoi ; un cerveau décide quand il délègue ; la configuration
globale des sous-agents décide quel agent ou modèle exécute un rôle délégué.**

- Page : `control_center.html` (`ARCHITECTURE_SECTION`, `mountArchitectureSettings`, `destroyArchitectureSettings`,
  `syncCoreCliDraft`, `SUBAGENT_SECTIONS`, `subagentSectionSpec`, `mountSubagentSettings`, `AGENT_SECTIONS`,
  `agentSectionSpec`, `installAgentSettingsSections`).
- Modules injectés par `ControlCenter.index()` (un marqueur chacun) : `control_center_architecture_settings.js`
  (`JarvisArchitectureSettings`), `control_center_brain_config_panel.js` (`JarvisBrainConfigPanel`),
  `control_center_subagent_routing.js` (`JarvisSubagentRouting`, inséré **avant** le module des sous-agents qui le lit),
  `control_center_subagents_settings.js` (`JarvisSubagentSettings`, vues `roles` et `work_methods`).
- Serveur : `ControlCenter._install_architecture_services` (§ 4).
- Conformité : `tests/unit/test_architecture_settings_mount.py` (assemblage serveur, crochet, règle de bascule de Voice),
  `tests/unit/test_architecture_agents_settings_browser.py` (vrai Chrome contre un vrai Control Center isolé : deux
  onglets, contrôles interdits absents, fenêtre du cerveau sur le canevas, Échap/Tab, délégation réelle, onglet
  Sous-agents, alias, charge `/api/settings`, débordement), `tests/unit/test_agent_cli_settings_ui.py` (Runtime & CLI,
  charge figée clé par clé, catalogue), `tests/unit/test_control_center_settings_registry_js.py` (catégorie, sections,
  alias), `tests/unit/test_control_center_subagents_settings_js.py` (page servie).

## 1. Deux onglets, et rien d'autre

La catégorie `agents_models` (id inchangé, libellé « Architecture & Agents ») a **exactement deux sections**, rendues
par le shell comme ses deux onglets internes (`#modalTabs`, onglets ARIA à activation manuelle). Il n'y a pas
d'onglet « Brains » : un cerveau se configure dans sa fenêtre flottante.

| Section | Contenu | Enregistrement |
| --- | --- | --- |
| `architecture` · Architecture | le graphe réel (`GET /api/architecture`) : nœuds de l'architecture vocale effective, liaisons typées, verrouillées, basculables ou gouvernées ; bandeau en lecture seule de l'architecture vocale avec lien vers Avancé ; disposition des nœuds (`/api/architecture/layout`) ; fenêtre d'un cerveau (`/api/brains/{id}/config`) | chaque geste s'enregistre (`save: 'self'`) |
| `subagents` · Sous-agents | les sept rôles du registre : identité, mission, capacités, Work Methods (lecture seule), instructions éditables, instances en cours ; **modèles du rôle** : candidats harness + modèle ordonnés, repli automatique, provenance, restauration de l'héritage (`/api/subagent-role-routing`) | la section s'enregistre (`save: 'self'`) |

**Pourquoi des sections.** Le registre a déjà la notion d'entrée d'une catégorie, dessinée par le shell comme une liste
d'onglets, avec ses règles (activation manuelle, focus, `destroy` à la sortie, alias). Deux sections enregistrées sont
donc les deux onglets internes : aucun second niveau d'onglets, aucun champ nouveau dans le registre (ses clés
autorisées sont inchangées), aucune seconde navigation. Le registre garde ses six catégories.

### Onglet Architecture

- **Montage** : `mountArchitectureSettings(host, context)` crée `[data-architecture-page]` › `#architectureCanvas`
  (canevas, adaptateur `JarvisArchitectureSettings.createHttpAdapter()`) et `#brainConfigPanels` (hôte de la fenêtre,
  distinct du canevas, qu'il réécrit). Module absent : notice codée `architecture_module_missing`.
- **Configurer…** (menu du nœud par clic droit, Menu, Maj+F10 ou le bouton « … » ; bouton de l'inspecteur ; liaison
  gouvernée) → `JarvisBrainConfigPanel.open(#brainConfigPanels, {adapter: createHttpAdapter(), brainId, field,
  returnFocus: canvasReturnFocus(…), anchor: le nœud, nodeLabel, onFocusConnection, onSaved, onClose})`.
- **Voir sur le graphe** (résumé des connexions de la fenêtre) → `view.select('connection', id)` ; rien n'est écrit.
- **Après un enregistrement** de la fenêtre, le graphe est relu (`view.load()`) : la tendance de délégation de Core
  gouverne la liaison `core.agents->subagents.spawn`, le mode du Tool Brain sa liaison.
- **CLI et modèle de Core** : la fenêtre écrit par `PATCH /api/brains/core/config` ; `syncCoreCliDraft` aligne alors
  `SET.data.cli` et `SET.draft.cli` (`agent`, `settings[<CLI>].model`). Sans cela, « Enregistrer » d'une section à pied
  (Runtime & CLI, Comportement), qui envoie toujours `cli.agent` et `cli.settings`, réécrirait l'ancien CLI.
- **Liens internes** : les boutons `data-settings-open` du canevas (« Changer dans Avancé › Architecture vocale » →
  `architecture_compat`) et de la fenêtre (« Ouvrir Sous-agents » → `subagents`) passent par `context.open`.
- **Placement initial** de la fenêtre : contre le bord droit du canevas si le nœud configuré reste libre, sinon contre le
  bord gauche de l'écran (sur le rail des catégories), sinon du côté qui a le plus de place ; elle ne couvre pas le nœud
  (mesuré à 1440 × 900 dans le test navigateur).
- **Démontage** : `destroy` de la section (changement d'onglet, de catégorie, fermeture des Réglages) appelle
  `destroy()` de la fenêtre (sa couche est `position: fixed` : elle survivrait à la section sinon) puis du canevas.
  Un brouillon non appliqué de la fenêtre est alors perdu (limite connue : le shell n'interroge pas `isDirty`).
- **Échap** : le canevas (menu, création, sélection) et la fenêtre (fermeture, confirmation) consomment la touche
  (`preventDefault`) ; une Échap non consommée alors qu'une fenêtre est ouverte la ferme d'abord (avec un brouillon, elle
  demande) ; le shell ne ferme les Réglages que pour une Échap que personne n'a prise. Le hub, qui écoute en capture,
  n'agit que lorsqu'il est affiché.
- **Tab** : la fenêtre (`aria-modal="false"`) fait tourner le focus en elle-même ; le piège du shell ignore une touche
  déjà traitée (`defaultPrevented`), il n'y a donc qu'un piège actif à la fois.

### Onglet Sous-agents

Le module des sous-agents (vue `roles`) reçoit `routing: JarvisSubagentSettings.createRoutingHttpAdapter()` : la fiche
d'un rôle porte ses modèles (§ 10 de [`../subagent-roles.md`](../subagent-roles.md)). Écritures : instructions par la voie
des prompts (`subagent_role.<id>`), politique d'un rôle par `PUT` / `DELETE /api/subagent-role-routing/{role_id}`, une
seule à la fois, révisée. Brouillons dans `SET.subagentDrafts`, d'un onglet à l'autre.

### Ce qui n'apparaît pas sur la page

Aucun contrôle de personnalité (ton, politesse, formalité, longueur, humour : Personnalisation › Comportement), aucune
commande, chemin, autorisation ni re-détection de CLI (Avancé › Runtime & CLI), plus de sélecteur Auto / Dupliqué ni
d'inventaire brut des modèles (Avancé › Runtime & CLI). Le test navigateur le vérifie sur les deux onglets (sélecteurs
interdits et libellés de contrôle).

## 2. Ce qui vit dans Avancé & Diagnostics (et Personnalisation)

| Section | Catégorie / groupe | Contenu | Enregistrement |
| --- | --- | --- | --- |
| `runtime_cli` · Runtime & CLI | `advanced_diagnostics` / `runtime_cli` | commande et chemin résolu du CLI de Core, « re-détecter », mode d'autorisation / bac à sable ; **routage des sous-agents par profil (compatibilité)** : mode Auto / Dupliqué (`cli.delegation_mode`), « Configuration avancée des sous-agents » (profils, candidats, recours au profil Général), **inventaire comparatif** des modèles (`JarvisCatalog`, chargé à l'ouverture de sa divulgation) | pied « Enregistrer » |
| `work_methods` · Work Methods apprises | `advanced_diagnostics` / `labs` | approches observées, promotion explicite | la section s'enregistre |
| `architecture_compat` | `advanced_diagnostics` / `architecture_compat` | choix de l'architecture vocale (le graphe l'affiche en lecture seule) | pied « Enregistrer » |
| `agent_behavior` · Comportement | `voice_audio` (Personnalisation) | longueur et ton des réponses, rappels de rendez-vous | pied « Enregistrer » |

Le mode Auto / Dupliqué n'est plus le concept principal : une politique **explicite** de rôle s'applique quel que soit
le mode ; un rôle qui **hérite** suit la politique par profil, donc ne lie qu'en Auto. Il reste lu et écrit comme avant.

## 3. Table de correspondance réglage → destination

| Réglage (clé ou route) | Destination | Écrivain |
| --- | --- | --- |
| `agent_cli` (CLI de Core) | fenêtre du cerveau Core, champ `provider` | `PATCH /api/brains/core/config` (et toujours `POST /api/settings` `cli.agent`) |
| `agent_cli_settings.<cli>.model` | fenêtre du cerveau Core, champ `model` | idem (`cli.settings[<CLI>].model`) |
| `agent_cli_settings.<cli>.command`, `.permission_mode` | Avancé › Runtime & CLI | `POST /api/settings` |
| tendance de délégation de Core (`brain-config.json`) | fenêtre du cerveau Core | `PATCH /api/brains/core/config` |
| instructions d'un cerveau (`backend.system.addition`…) | fenêtre du cerveau | `PATCH` (voie des prompts) |
| liaisons basculables (`brain_orchestration`, `voice_surface.back_brain_delegation`, `tool_brain.mode`) | onglet Architecture | `POST /api/architecture/connections/{id}` |
| disposition des nœuds (`architecture-layout.json`) | onglet Architecture | `PUT /api/architecture/layout` |
| `cli.delegation_mode` (Auto / Dupliqué) | Avancé › Runtime & CLI | `POST /api/settings` |
| `routing.profiles` | Avancé › Runtime & CLI | `POST /api/settings` |
| politique d'un rôle (`subagent-role-routing.json`) | onglet Sous-agents | `PUT` / `DELETE /api/subagent-role-routing/{role_id}` |
| instructions d'un rôle (`subagent_role.<id>`) | onglet Sous-agents | `POST /api/prompts/subagent_role.<id>` |
| `cli.behavior.*`, `agenda_reminders.*` | Personnalisation › Comportement | `POST /api/settings` |
| promotion d'un candidat de Work Method | Avancé › Work Methods apprises | `POST /api/work-methods/promotions` |

**Migration : aucun réglage réécrit.** Les clés sont les mêmes qu'avant la Slice 07 ; seules les surfaces qui les
éditent ont bougé. La charge de `POST /api/settings` est inchangée clé par clé
(`test_agent_cli_save_payload_is_frozen_key_by_key`, `test_saving_from_behavior_posts_the_unchanged_payload_and_reads_back`).
Alias : `main_agent` → `architecture`, `subagent_models` → `subagents`
([`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md)) ; `subagents` reste l'ID de sa section.

## 4. Serveur : montage (Slice 07)

`ControlCenter._install_architecture_services(runtime_root)` construit **une fois**, pour la vie du Control Center :

| Objet | Rôle |
| --- | --- |
| `architecture_graph` (`ArchitectureGraphService`) | snapshot et écritures de topologie ; son `write_lock` sérialise les écritures de `control-center-settings.json` faites hors de `/api/settings` (graphe et cerveaux) |
| `ArchitectureLayoutStore` | disposition, à part |
| `brain_config` (`BrainConfigService`) | descripteurs et `PATCH` ; un store de tendance (`brain-config.json`) et un store de surcharges de prompt gardés par le service |
| `role_routing_routes` (`SubagentRoleRoutingApi` + `RoleRoutingStore`) | politique par rôle |

- Routes ajoutées à la même `web.Application` que le reste : handlers `async` de la boucle aiohttp, sans exécuteur ; le
  middleware d'origine protège les écritures comme les autres routes.
- **Catalogue** de la fenêtre du cerveau : `ControlCenter._catalog_view_dict(surface, role)`, la fonction qui sert
  `GET /api/catalog`. **Candidats** du routage par rôle : `ControlCenter._measure_routing_candidates()`, le calcul de
  `GET /api/routing/candidates`. Une seule vérité serveur, aucune liste recopiée.
- **Crochet** `after_settings_write` (`_after_brain_settings_write`) : après une écriture du CLI ou du modèle de Core,
  même effet qu'un `POST /api/settings` qui les change : autre CLI → `_switch_agent` (l'ancien s'arrête avant que le
  nouveau démarre), sinon `_apply_agent_settings` (effectif au prochain lancement de chaque CLI). Journal
  `brain_config.agents_reconfigured`.
- **Bascule de Voice** : une seule règle, `voice_switch.plan_voice_switch(previous, updated, running_configuration_id=…)`
  (source = configuration publiée par Voice si son battement est frais, sinon les réglages précédents ; rien si l'une
  des compositions n'est pas démarrable, si l'identité ne change pas ou si la cible n'a pas de modèle), appelée par
  `POST /api/settings` et par `ArchitectureGraphService.write_settings` (graphe, modèles vocaux de la fenêtre).

## 5. Limites connues

- `POST /api/settings` n'a toujours ni révision ni verrou partagé avec le graphe : une écriture concurrente est détectée
  par les révisions calculées du graphe et des cerveaux, pas empêchée. Côté page, `syncCoreCliDraft` évite l'écrasement
  du CLI de Core par un brouillon périmé ; une modification de l'architecture vocale dans Avancé, dans la même ouverture
  des Réglages qu'une bascule du graphe, peut encore renvoyer l'ancienne valeur de `brain_orchestration`.
- Le brouillon d'une fenêtre de cerveau n'est pas gardé quand on quitte l'onglet (voir § 1).
